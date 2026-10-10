"""Scan pipeline seam for the MedCheck API gateway.

Mock mode is fully implemented and deterministic: the fixture is selected from
a stable request hash over (image bytes, client, hints). Real Vision/OCR/VLM
components will be composed behind the same ``ScanPipeline`` protocol later
without changing the HTTP surface.

Contract models are imported from ``services.common.contract``; this module
must not redefine them.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Protocol

from services.api.fixtures import FIXTURES
from services.common.contract import (
    Bottle,
    ErrorInfo,
    FrameQuality,
    Instructions,
    Label,
    Medication,
    Safety,
    ScanResponse,
    Timing,
    Uncertainty,
)

RequestedMode = Literal["auto", "mock", "real"]
ResolvedMode = Literal["mock", "real"]


@dataclass(frozen=True)
class ScanContext:
    """Everything the pipeline needs for one scan request."""

    request_id: str
    image: bytes
    content_type: str
    client: str
    requested_mode: RequestedMode
    hints: Optional[Dict[str, Any]]


class PipelineUnavailable(RuntimeError):
    """Raised when a requested mode has no wired implementation yet."""


class ScanPipeline(Protocol):
    """Composition seam: Vision -> OCR -> candidates -> optional VLM."""

    mode: ResolvedMode

    async def scan(self, ctx: ScanContext) -> ScanResponse:  # pragma: no cover
        ...


def request_key(
    image: bytes,
    client: str = "unknown",
    hints: Optional[Dict[str, Any]] = None,
) -> str:
    """Stable request hash used to select deterministic mock fixtures."""
    digest = hashlib.sha256()
    digest.update(image)
    digest.update(b"\x00")
    digest.update(client.encode("utf-8", "replace"))
    digest.update(b"\x00")
    digest.update(json.dumps(hints or {}, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def choose_fixture(key: str) -> Dict[str, Any]:
    """Pick a fixture deterministically from a request hash."""
    index = int(key[:16], 16) % len(FIXTURES)
    return FIXTURES[index]


def build_fixture_response(
    fixture: Dict[str, Any],
    request_id: str,
    elapsed_ms: float,
) -> ScanResponse:
    """Build a contract-valid ``ScanResponse`` for one mock fixture."""
    total_ms = round(max(elapsed_ms, 0.0), 3)
    return ScanResponse(
        request_id=request_id,
        status=fixture["status"],
        mode="mock",
        frame_quality=FrameQuality(**fixture["frame_quality"]),
        bottle=Bottle(**fixture["bottle"]),
        label=Label(**fixture["label"]),
        medication=Medication(**fixture["medication"]),
        instructions=Instructions(**fixture["instructions"]),
        candidates=list(fixture["candidates"]),
        interpretation=dict(fixture["interpretation"]),
        uncertainty=Uncertainty(**fixture["uncertainty"]),
        timing=Timing(total_ms=total_ms, stages={"mock_pipeline": total_ms}),
        safety=Safety(),
        error=None,
    )


def build_error_response(
    request_id: str,
    code: str,
    message: str,
    detail: Any = None,
) -> ScanResponse:
    """Domain-level error payload (HTTP 200 + ``status:"error"``)."""
    return ScanResponse(
        request_id=request_id,
        status="error",
        mode="mock",
        frame_quality=FrameQuality(
            acceptable=False,
            score=0.0,
            blur={"score": 0.0, "is_blurry": False},
            exposure={"score": 0.0, "too_dark": False, "too_bright": False},
            glare={"score": 0.0, "has_glare": False},
            guidance=[],
        ),
        bottle=Bottle(detected=False, confidence=0.0),
        label=Label(detected=False, confidence=0.0, text=None),
        medication=Medication(),
        instructions=Instructions(),
        candidates=[],
        uncertainty=Uncertainty(level="high", reasons=[code.lower()], rescan_required=True),
        timing=Timing(total_ms=0.0, stages={}),
        safety=Safety(),
        error=ErrorInfo(code=code, message=message, detail=detail),
    )


def to_contract_json(response: ScanResponse) -> Dict[str, Any]:
    """Serialize a response so it validates against scan_response.schema.json.

    ``exclude_none`` drops optional object fields that the JSON schema does not
    allow as ``null`` (bbox, blur, strength, ...). Required-but-nullable keys
    (``medication.*.value``/``unit``, ``instructions.raw_text``) are re-added
    afterwards so the JSON Schema's ``required`` clauses stay satisfied.
    """
    payload = response.model_dump(mode="json", exclude_none=True)

    instructions = payload.get("instructions")
    if isinstance(instructions, dict):
        instructions.setdefault("raw_text", None)

    medication = payload.get("medication")
    if isinstance(medication, dict):
        for field_name in ("name", "form", "manufacturer", "strength"):
            field = medication.get(field_name)
            if isinstance(field, dict):
                field.setdefault("value", None)
        strength = medication.get("strength")
        if isinstance(strength, dict):
            strength.setdefault("unit", None)

    return payload


class MockPipeline:
    """Deterministic, fixture-backed pipeline. Never claims real inference."""

    mode: ResolvedMode = "mock"

    async def scan(self, ctx: ScanContext) -> ScanResponse:
        started = time.perf_counter()
        fixture = choose_fixture(request_key(ctx.image, ctx.client, ctx.hints))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return build_fixture_response(fixture, ctx.request_id, elapsed_ms)


_MOCK_PIPELINE = MockPipeline()


def get_pipeline(resolved_mode: ResolvedMode) -> ScanPipeline:
    """Return the pipeline for a resolved mode, or raise if not wired yet."""
    if resolved_mode == "mock":
        return _MOCK_PIPELINE
    raise PipelineUnavailable("real pipeline is not wired yet; use mode=mock or mode=auto")


def _self_check() -> None:
    """Fail fast at import time if any fixture violates the contract."""
    for fixture in FIXTURES:
        build_fixture_response(fixture, "req-selfcheck0000", 0.0)


_self_check()
