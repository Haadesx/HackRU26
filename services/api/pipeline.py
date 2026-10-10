"""Scan pipeline seam for the MedCheck API gateway.

Mock mode is fully implemented and deterministic: the fixture is selected from
a stable request hash over (image bytes, client, hints). Real Vision/OCR/VLM
components will be composed behind the same ``ScanPipeline`` protocol later
without changing the HTTP surface.

Contract models are imported from ``services.common.contract``; this module
must not redefine them.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol

from services.api.fixtures import FIXTURES
from services.common.contract import (
    Bottle,
    CaptureInfo,
    ErrorInfo,
    FrameQuality,
    Instructions,
    Interpretation,
    Label,
    Medication,
    PerFrameResult,
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

    async def scan_multi(self, ctxs: List[ScanContext]) -> ScanResponse:  # pragma: no cover
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
        label_meta=fixture.get("label_meta"),
    )


def build_error_response(
    request_id: str,
    code: str,
    message: str,
    detail: Any = None,
    mode: ResolvedMode = "mock",
) -> ScanResponse:
    """Domain-level error payload (HTTP 200 + ``status:"error"``)."""
    return ScanResponse(
        request_id=request_id,
        status="error",
        mode=mode,
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
    (``medication.*.value``/``unit``, ``instructions.raw_text``,
    ``instructions.dose.quantity``/``unit``) are re-added afterwards so the JSON
    Schema's ``required`` clauses stay satisfied.
    """
    payload = response.model_dump(mode="json", exclude_none=True)

    instructions = payload.get("instructions")
    if isinstance(instructions, dict):
        instructions.setdefault("raw_text", None)
        dose = instructions.get("dose")
        if isinstance(dose, dict):
            dose.setdefault("quantity", None)
            dose.setdefault("unit", None)

    medication = payload.get("medication")
    if isinstance(medication, dict):
        for field_name in ("name", "form", "manufacturer", "strength"):
            field = medication.get(field_name)
            if isinstance(field, dict):
                field.setdefault("value", None)
        strength = medication.get("strength")
        if isinstance(strength, dict):
            strength.setdefault("unit", None)

    label_meta = payload.get("label_meta")
    if isinstance(label_meta, dict):
        for field_name in (
            "quantity_start",
            "refills_remaining",
            "pharmacy_name",
            "pharmacy_phone",
            "prescriber",
            "schedule_times",
        ):
            field_entry = label_meta.get(field_name)
            if isinstance(field_entry, dict):
                field_entry.setdefault("value", None)

    return payload


class MockPipeline:
    """Deterministic, fixture-backed pipeline. Never claims real inference."""

    mode: ResolvedMode = "mock"

    async def scan(self, ctx: ScanContext) -> ScanResponse:
        started = time.perf_counter()
        fixture = choose_fixture(request_key(ctx.image, ctx.client, ctx.hints))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return build_fixture_response(fixture, ctx.request_id, elapsed_ms)

    async def scan_multi(self, ctxs: List[ScanContext]) -> ScanResponse:
        return await asyncio.to_thread(self._scan_multi_sync, ctxs)

    @staticmethod
    def _fixture_clipped(fixture: Dict[str, Any]) -> Optional[bool]:
        bbox = (fixture.get("label") or {}).get("bbox")
        if not bbox:
            return None
        gap = min(bbox["x"], bbox["y"], 1.0 - (bbox["x"] + bbox["w"]), 1.0 - (bbox["y"] + bbox["h"]))
        return bool(gap <= 0.02)

    def _scan_multi_sync(self, ctxs: List[ScanContext]) -> ScanResponse:
        started = time.perf_counter()
        selected = [
            (index, ctx, choose_fixture(request_key(ctx.image, ctx.client, ctx.hints)))
            for index, ctx in enumerate(ctxs)
        ]
        accepted = [item for item in selected if item[2]["status"] in ("ok", "uncertain")]

        per_frame = [
            PerFrameResult(
                index=index,
                status="accepted" if fixture["status"] in ("ok", "uncertain") else fixture["status"],
                label_detected=fixture["label"]["detected"],
                label_confidence=fixture["label"]["confidence"],
                clipped=self._fixture_clipped(fixture),
                guidance=list(fixture["frame_quality"]["guidance"]) or None,
            )
            for index, _ctx, fixture in selected
        ]
        capture = CaptureInfo(
            frames_requested=len(ctxs),
            frames_used=len(accepted),
            fusion="multi_frame",
            per_frame=per_frame,
        )

        def _total_ms() -> float:
            return round((time.perf_counter() - started) * 1000.0, 3)

        if accepted:
            base = accepted[0][2]
            reasons: List[str] = []
            if len(accepted) > 1:
                reasons.append(f"fused_from_{len(accepted)}_frames")
            names = {
                fixture["medication"]["name"]["value"]
                for _i, _c, fixture in accepted
                if fixture["medication"]["name"]["value"]
            }
            if len(names) > 1:
                reasons.append("fusion_conflict:name")
            all_ok = all(fixture["status"] == "ok" for _i, _c, fixture in accepted)
            elapsed = _total_ms()
            return ScanResponse(
                request_id=ctxs[0].request_id,
                status="ok" if all_ok else "uncertain",
                mode="mock",
                frame_quality=FrameQuality(**base["frame_quality"]),
                bottle=Bottle(**base["bottle"]),
                label=Label(**base["label"]),
                medication=Medication.model_validate(base["medication"]),
                instructions=Instructions.model_validate(base["instructions"]),
                candidates=list(base["candidates"]),
                interpretation=Interpretation(available=False),
                uncertainty=Uncertainty(
                    level="low" if all_ok else "medium",
                    reasons=list(dict.fromkeys(reasons)),
                    rescan_required=False,
                ),
                timing=Timing(total_ms=elapsed, stages={"mock_multi": elapsed}),
                safety=Safety(),
                error=None,
                capture=capture,
                label_meta=base.get("label_meta"),
            )

        base = selected[0][2]
        all_no_medication = all(fixture["status"] == "no_medication_found" for _i, _c, fixture in selected)
        final_status = "no_medication_found" if all_no_medication else "needs_rescan"
        elapsed = _total_ms()
        return ScanResponse(
            request_id=ctxs[0].request_id,
            status=final_status,
            mode="mock",
            frame_quality=FrameQuality(**base["frame_quality"]),
            bottle=Bottle(**base["bottle"]),
            label=Label(**base["label"]),
            medication=Medication(),
            instructions=Instructions(),
            candidates=[],
            interpretation=Interpretation(available=False),
            uncertainty=Uncertainty(
                level="high",
                reasons=["no_label_detected"] if all_no_medication else ["frame_not_acceptable"],
                rescan_required=final_status == "needs_rescan",
            ),
            timing=Timing(total_ms=elapsed, stages={"mock_multi": elapsed}),
            safety=Safety(),
            error=None,
            capture=capture,
        )


_MOCK_PIPELINE = MockPipeline()

# Real-mode components (PI-1 Vision + PI-2 OCR). Checked by spec so /ready and
# get_pipeline can report availability without importing the heavy stack.
_REAL_MODULES: Dict[str, tuple] = {
    "vision": ("numpy", "cv2", "PIL", "services.vision.pipeline"),
    "ocr": ("rapidocr_onnxruntime", "services.ocr.engine", "services.ocr.extract"),
}


def vlm_enabled() -> bool:
    """Whether the optional PI-3 VLM fallback is enabled (off by default)."""
    return os.getenv("MEDCHECK_VLM_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _missing_real_modules() -> list:
    missing = []
    for modules in _REAL_MODULES.values():
        for module in modules:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
    return missing


def real_pipeline_available() -> tuple:
    """``(available, reasons)`` for real mode without importing the stack."""
    missing = _missing_real_modules()
    return (not missing, [f"missing:{name}" for name in missing])


def real_component_status() -> Dict[str, str]:
    """Per-component readiness map for ``GET /ready``."""
    missing = set(_missing_real_modules())
    components = {
        name: ("missing" if any(module in missing for module in modules) else "ready")
        for name, modules in _REAL_MODULES.items()
    }
    components["pipeline"] = "unavailable" if missing else "real"
    components["vlm"] = "enabled" if vlm_enabled() else "disabled"
    return components


_REAL_PIPELINE: Optional[ScanPipeline] = None


def get_pipeline(resolved_mode: ResolvedMode) -> ScanPipeline:
    """Return the pipeline for a resolved mode, or raise if not wired yet."""
    if resolved_mode == "mock":
        return _MOCK_PIPELINE
    global _REAL_PIPELINE
    if _REAL_PIPELINE is None:
        try:
            from services.api.real_pipeline import RealScanPipeline
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise PipelineUnavailable(f"real pipeline dependencies unavailable: {exc}") from exc
        _REAL_PIPELINE = RealScanPipeline()
    return _REAL_PIPELINE


def _self_check() -> None:
    """Fail fast at import time if any fixture violates the contract."""
    for fixture in FIXTURES:
        build_fixture_response(fixture, "req-selfcheck0000", 0.0)


_self_check()
