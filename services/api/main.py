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
import hmac
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
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
MIN_MULTI_FRAMES = 2
MAX_MULTI_FRAMES = 6

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

STARTED_MONOTONIC = time.monotonic()

app = FastAPI(
    title="MedCheck Inference Gateway",
    version=APP_VERSION,
    description="OCR-first medication label reading — mock mode (Gate 3).",
)


def _cors_origins() -> List[str]:
    """``MEDCHECK_CORS_ORIGINS`` (comma-separated). Empty/unset disables CORS."""
    raw = os.getenv("MEDCHECK_CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# Configured at startup; restart the process to apply env changes. `*` is for
# local dev only (browsers then allow any origin).
_CORS_ORIGINS = _cors_origins()
if _CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
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


def _api_key() -> str:
    """Optional shared secret; empty means auth is disabled (local dev)."""
    return os.getenv("MEDCHECK_API_KEY", "").strip()


def _check_api_key(authorization: Optional[str], request_id: str) -> Optional[JSONResponse]:
    """Enforce ``Authorization: Bearer <MEDCHECK_API_KEY>`` when configured.

    Uses ``hmac.compare_digest`` (constant-time) and returns the standard error
    envelope on failure. /health and /ready stay open for probes.
    """
    key = _api_key()
    if not key:
        return None
    expected = f"Bearer {key}".encode("utf-8", "surrogateescape")
    provided = (authorization or "").encode("utf-8", "surrogateescape")
    if hmac.compare_digest(provided, expected):
        return None
    return _transport_error(
        401,
        "UNAUTHORIZED",
        "Missing or invalid bearer token",
        request_id,
    )


def _validate_scan_form(
    client: str,
    mode: str,
    hints: Optional[str],
    request_id: str,
) -> tuple:
    """Shared /v1/scan and /v1/scan/multi form validation.

    Returns ``(error_response, parsed_hints)``; exactly one is meaningful.
    """
    if client not in ALLOWED_CLIENTS:
        return (
            _transport_error(
                400,
                "INVALID_CLIENT",
                f"client must be one of {list(ALLOWED_CLIENTS)}",
                request_id,
            ),
            None,
        )
    if mode not in ALLOWED_MODES:
        return (
            _transport_error(
                400,
                "INVALID_MODE",
                f"mode must be one of {list(ALLOWED_MODES)}",
                request_id,
            ),
            None,
        )
    parsed_hints: Optional[Dict[str, Any]] = None
    if hints is not None and hints.strip():
        try:
            parsed_hints = json.loads(hints)
        except json.JSONDecodeError as exc:
            return (
                _transport_error(
                    400,
                    "INVALID_HINTS",
                    "hints must be a JSON-encoded object",
                    request_id,
                    detail=str(exc),
                ),
                None,
            )
        if not isinstance(parsed_hints, dict):
            return (
                _transport_error(
                    400,
                    "INVALID_HINTS",
                    "hints must decode to a JSON object",
                    request_id,
                ),
                None,
            )
    return None, parsed_hints


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
        401: "UNAUTHORIZED",
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
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    request_id = "req-" + uuid.uuid4().hex[:12]

    auth_error = _check_api_key(authorization, request_id)
    if auth_error is not None:
        return auth_error

    form_error, parsed_hints = _validate_scan_form(client, mode, hints, request_id)
    if form_error is not None:
        return form_error

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

    resolved = _resolve_mode(mode)

    if not _matches_magic(content_type, data):
        domain_error = build_error_response(
            request_id, "INVALID_IMAGE", "Could not decode image bytes", mode=resolved
        )
        return _scan_json(domain_error, request_id)
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


@app.post("/v1/scan/multi", response_model=ScanResponse)
async def scan_multi_v1(
    images: List[UploadFile] = File(..., description="2-6 JPEG/PNG label photos (12 MiB each)"),
    client: str = Form("unknown"),
    mode: str = Form("auto"),
    hints: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    request_id = "req-" + uuid.uuid4().hex[:12]

    auth_error = _check_api_key(authorization, request_id)
    if auth_error is not None:
        return auth_error

    form_error, parsed_hints = _validate_scan_form(client, mode, hints, request_id)
    if form_error is not None:
        return form_error

    if not MIN_MULTI_FRAMES <= len(images) <= MAX_MULTI_FRAMES:
        return _transport_error(
            400,
            "INVALID_FRAME_COUNT",
            f"images must contain {MIN_MULTI_FRAMES}..{MAX_MULTI_FRAMES} frames",
            request_id,
            detail={"received": len(images)},
        )

    resolved = _resolve_mode(mode)
    contexts: List[ScanContext] = []
    for index, upload in enumerate(images):
        content_type = (upload.content_type or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_IMAGE_TYPES:
            return _transport_error(
                415,
                "UNSUPPORTED_IMAGE_TYPE",
                f"images[{index}] must be one of {list(ALLOWED_IMAGE_TYPES)}, got {content_type or 'missing'}",
                request_id,
                detail={"index": index},
            )
        data = await upload.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            return _transport_error(
                413,
                "PAYLOAD_TOO_LARGE",
                f"images[{index}] must be at most {MAX_IMAGE_BYTES} bytes (12 MiB)",
                request_id,
                detail={"index": index},
            )
        if not data:
            return _transport_error(
                400, "EMPTY_IMAGE", f"images[{index}] is empty", request_id, detail={"index": index}
            )
        if not _matches_magic(content_type, data):
            domain_error = build_error_response(
                request_id,
                "INVALID_IMAGE",
                f"Could not decode image bytes in frame {index}",
                mode=resolved,
            )
            return _scan_json(domain_error, request_id)
        contexts.append(
            ScanContext(
                request_id=request_id,
                image=data,
                content_type=content_type,
                client=client,
                requested_mode=mode,  # type: ignore[arg-type]
                hints=parsed_hints,
            )
        )

    try:
        pipeline = get_pipeline(resolved)
    except PipelineUnavailable as exc:
        return _transport_error(503, "REAL_PIPELINE_UNAVAILABLE", str(exc), request_id)

    try:
        response = await asyncio.wait_for(pipeline.scan_multi(contexts), timeout=_scan_timeout_s())
    except asyncio.TimeoutError:
        return _transport_error(
            504,
            "SCAN_TIMEOUT",
            f"multi-scan exceeded {_scan_timeout_s()}s budget",
            request_id,
        )

    return _scan_json(response, request_id)
