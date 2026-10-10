"""MedCheck inference API gateway (FastAPI, port 8300).

Endpoints (frozen v1 contract):
  GET  /health    -> 200 HealthResponse
  GET  /ready     -> 200 ReadyResponse | 503 not-ready envelope
  POST /v1/scan   -> 200 ScanResponse (even for domain errors) or 4xx/5xx for
                     transport-level failures (bad multipart, wrong media type,
                     payload too large, timeout).

Mock mode is fully implemented; real Vision/OCR/VLM modules plug in behind the
``ScanPipeline`` seam in ``services/api/pipeline.py``. Contract models come from
``services.common.contract`` — this service never redefines the contract.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from services.api.pipeline import (
    PipelineUnavailable,
    ResolvedMode,
    ScanContext,
    build_error_response,
    get_pipeline,
    real_component_status,
    real_pipeline_available,
    to_contract_json,
)
from services.common.contract import HealthResponse, ReadyResponse, ScanResponse

SERVICE_NAME = "medcheck-inference"
APP_VERSION = "0.1.0"

MAX_IMAGE_BYTES = 12 * 1024 * 1024  # frozen contract limit: 12 MiB
SCAN_TIMEOUT_S = 15.0  # per-scan budget
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png")
ALLOWED_CLIENTS = ("ios", "backend", "test", "unknown")
ALLOWED_MODES = ("auto", "mock", "real")

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

STARTED_MONOTONIC = time.monotonic()

app = FastAPI(
    title="MedCheck Inference Gateway",
    version=APP_VERSION,
    description="OCR-first medication label reading — mock mode (Gate 3).",
)


# --------------------------------------------------------------------------
# Config / helpers
# --------------------------------------------------------------------------
def _service_mode() -> ResolvedMode:
    """Service default mode for ``mode=auto``. Real is opt-in via env."""
    value = os.getenv("MEDCHECK_API_MODE", "mock").strip().lower()
    return "real" if value == "real" else "mock"


def _scan_timeout_s() -> float:
    try:
        return max(0.1, float(os.getenv("MEDCHECK_SCAN_TIMEOUT_S", SCAN_TIMEOUT_S)))
    except ValueError:
        return SCAN_TIMEOUT_S


def _error_body(
    code: str,
    message: str,
    detail: Any = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"error": {"code": code, "message": message, "detail": detail}}
    if request_id:
        body["request_id"] = request_id
    return body


def _transport_error(
    status_code: int,
    code: str,
    message: str,
    request_id: Optional[str] = None,
    detail: Any = None,
) -> JSONResponse:
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(
        status_code=status_code,
        content=_error_body(code, message, detail, request_id),
        headers=headers,
    )


def _matches_magic(content_type: str, data: bytes) -> bool:
    """Lightweight decode gate; full pixel decode belongs to Vision/OCR later."""
    if content_type == "image/jpeg":
        return data.startswith(_JPEG_MAGIC)
    if content_type == "image/png":
        return data.startswith(_PNG_MAGIC)
    return False


def _resolve_mode(requested: str) -> ResolvedMode:
    if requested == "mock":
        return "mock"
    if requested == "real":
        return "real"
    return _service_mode()  # auto


def _scan_json(response: ScanResponse, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content=to_contract_json(response),
        headers={"X-Request-ID": request_id},
    )


# --------------------------------------------------------------------------
# Transport-level error envelopes
# --------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request, exc: RequestValidationError) -> JSONResponse:
    detail: List[Dict[str, Any]] = [
        {
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    return _transport_error(
        400,
        "INVALID_REQUEST",
        "Invalid or missing multipart fields",
        detail=detail,
    )


@app.exception_handler(StarletteHTTPException)
async def _http_error_handler(request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {
        400: "BAD_REQUEST",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
    }
    code = codes.get(exc.status_code, "HTTP_ERROR")
    message = str(exc.detail) if exc.detail else code
    return _transport_error(exc.status_code, code, message, detail=None)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service=SERVICE_NAME,
        version=APP_VERSION,
        uptime_s=round(time.monotonic() - STARTED_MONOTONIC, 3),
    )


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    components = real_component_status()
    if _service_mode() == "real":
        available, reasons = real_pipeline_available()
        if available:
            return ReadyResponse(ready=True, mode="real", components=components, reasons=[])
        return JSONResponse(
            status_code=503,
            content={"ready": False, "mode": "real", "components": components, "reasons": reasons},
        )
    components["pipeline"] = "mock"
    return ReadyResponse(ready=True, mode="mock", components=components, reasons=[])


@app.post("/v1/scan", response_model=ScanResponse)
async def scan_v1(
    image: UploadFile = File(..., description="JPEG or PNG medication label photo (max 12 MiB)"),
    client: str = Form("unknown"),
    mode: str = Form("auto"),
    hints: Optional[str] = Form(None),
) -> JSONResponse:
    request_id = "req-" + uuid.uuid4().hex[:12]

    if client not in ALLOWED_CLIENTS:
        return _transport_error(
            400,
            "INVALID_CLIENT",
            f"client must be one of {list(ALLOWED_CLIENTS)}",
            request_id,
        )
    if mode not in ALLOWED_MODES:
        return _transport_error(
            400,
            "INVALID_MODE",
            f"mode must be one of {list(ALLOWED_MODES)}",
            request_id,
        )

    content_type = (image.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        return _transport_error(
            415,
            "UNSUPPORTED_IMAGE_TYPE",
            f"image must be one of {list(ALLOWED_IMAGE_TYPES)}, got {content_type or 'missing'}",
            request_id,
        )

    data = await image.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return _transport_error(
            413,
            "PAYLOAD_TOO_LARGE",
            f"image must be at most {MAX_IMAGE_BYTES} bytes (12 MiB)",
            request_id,
        )
    if not data:
        return _transport_error(400, "EMPTY_IMAGE", "image part is empty", request_id)

    parsed_hints: Optional[Dict[str, Any]] = None
    if hints is not None and hints.strip():
        try:
            parsed_hints = json.loads(hints)
        except json.JSONDecodeError as exc:
            return _transport_error(
                400,
                "INVALID_HINTS",
                "hints must be a JSON-encoded object",
                request_id,
                detail=str(exc),
            )
        if not isinstance(parsed_hints, dict):
            return _transport_error(
                400,
                "INVALID_HINTS",
                "hints must decode to a JSON object",
                request_id,
            )

    if not _matches_magic(content_type, data):
        domain_error = build_error_response(request_id, "INVALID_IMAGE", "Could not decode image bytes")
        return _scan_json(domain_error, request_id)

    resolved = _resolve_mode(mode)
    try:
        pipeline = get_pipeline(resolved)
    except PipelineUnavailable as exc:
        return _transport_error(503, "REAL_PIPELINE_UNAVAILABLE", str(exc), request_id)

    ctx = ScanContext(
        request_id=request_id,
        image=data,
        content_type=content_type,
        client=client,
        requested_mode=mode,  # type: ignore[arg-type]
        hints=parsed_hints,
    )
    try:
        response = await asyncio.wait_for(pipeline.scan(ctx), timeout=_scan_timeout_s())
    except asyncio.TimeoutError:
        return _transport_error(
            504,
            "SCAN_TIMEOUT",
            f"scan exceeded {_scan_timeout_s()}s budget",
            request_id,
        )

    return _scan_json(response, request_id)
