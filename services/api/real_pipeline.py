"""Real OCR-first scan pipeline (Milestone 2 + M3 escalation + M7 multi-frame).

Composition (the API gateway is the only place services are composed):

    PI-1 Vision.analyze_frame  ->  frame quality + bottle/label localization
      | frame unacceptable       ->  needs_rescan, OCR skipped
      v
    PI-2 OCR.read_text         ->  verbatim raw text (label crop or full frame)
      v
    PI-2 extract_fields        ->  structured medication + instructions
      v
    optional PI-2 matcher      ->  candidates[] (registry)
      v
    optional PI-3 VLM          ->  only when should_use_vlm() says so AND
                                   MEDCHECK_VLM_ENABLED is set (default off)

``scan_multi`` runs the same frame path for each uploaded photo, skips frames
that fail quality/label checks, and fuses the accepted ``Extraction`` objects
with PI-2's ``fuse_extractions`` (with a conservative API-side fallback while
that helper lands). Everything is synchronous CPU work executed in a worker
thread by the public coroutines. All field values come from the underlying
services: this module never invents a drug name, strength, or instruction
(contracts/README.md rule 5).
"""
from __future__ import annotations

import asyncio
import importlib.util
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from services.api.pipeline import ScanContext, build_error_response, vlm_enabled
from services.common.contract import (
    Bottle,
    Candidate,
    CaptureInfo,
    DoseInfo,
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
from services.ocr.engine import OcrUnavailableError, read_text
from services.ocr.extract import extract_fields
from services.ocr.types import Extraction, FieldString, FieldStrength, InstructionItem, absent_string, absent_strength
from services.vision.pipeline import analyze_frame
from services.vision.preprocess import ImageDecodeError, decode_image
from services.vlm.client import VlmResult, client_from_env
from services.vlm.reconcile import (
    DEFAULTS as _VLM_DEFAULTS,
    instructions_raw,
    reconcile_fields,
    should_use_vlm,
    to_contract_medication,
    uncertainty_from_fields,
)

#: Score a registry candidate must reach for the matcher to keep it.
DEFAULT_MATCHER_THRESHOLD = 0.75

#: Identity-critical fields that may cost a VLM call (M3, agreed with PI-3).
ESCALATION_FIELDS = ("name", "strength_value")

VLM_QUESTION = "Verify the OCR read against the image and extract the label fields."

#: A label bbox within this normalized distance of a frame edge is "clipped".
_CLIP_EPS = 0.02

_AUTO = object()


# --------------------------------------------------------------------------
# Escalation config
# --------------------------------------------------------------------------
def escalation_config(candidate_mismatch: bool) -> Dict[str, Any]:
    """PI-3 M3 escalation policy (services/vlm/EVAL.md, Integration contract).

    Identity-critical fields (name, strength) drive escalation; optional fields
    such as manufacturer must never cost a ~1.7 s VLM call. ``candidate_mismatch``
    (hints supplied, identity read present, matcher found no registered match)
    forces verification even when the OCR read was confident. ``min_frame_score``
    escalates borderline frames that vision still accepted.
    """
    config: Dict[str, Any] = {
        "min_field_confidence": 0.75,
        "escalation_fields": ESCALATION_FIELDS,
        "min_frame_score": 0.45,
        "candidate_mismatch": bool(candidate_mismatch),
    }
    # Compatibility with the pre-M3 reconcile (no escalation_fields support):
    # suppress the level trigger so optional fields cannot escalate alone.
    # Inert once PI-3's M3 lands (DEFAULTS then carries escalation_fields).
    if "escalation_fields" not in _VLM_DEFAULTS:
        config["invoke_on_levels"] = ()
    return config


# --------------------------------------------------------------------------
# Mapping helpers
# --------------------------------------------------------------------------
def canonical_ocr_fields(extraction: Extraction, ocr_confidence: float) -> Dict[str, Dict[str, Any]]:
    """Map an OCR ``Extraction`` onto the VLM/reconcile canonical keys."""
    fields: Dict[str, Dict[str, Any]] = {}

    def put(key: str, value: Any, confidence: float) -> None:
        if value is None:
            return
        fields[key] = {
            "value": value,
            "confidence": round(float(confidence), 4),
            "source": "ocr",
        }

    put("name", extraction.name.value, extraction.name.confidence)
    put("strength_value", extraction.strength.value, extraction.strength.confidence)
    put("strength_unit", extraction.strength.unit, extraction.strength.confidence)
    put("form", extraction.form.value, extraction.form.confidence)
    put("manufacturer", extraction.manufacturer.value, extraction.manufacturer.confidence)
    if extraction.raw_text and extraction.raw_text.strip():
        fields["instructions"] = {
            "value": extraction.raw_text,
            "confidence": round(float(ocr_confidence), 4),
            "source": "ocr",
        }
    return fields


def extract_hints_from_request(hints: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive OCR biasing hints from request hints (never a value source)."""
    out: Dict[str, Any] = {}
    if not isinstance(hints, dict):
        return out
    known = hints.get("known_candidates")
    if not isinstance(known, list):
        return out
    names = [c.get("name") for c in known if isinstance(c, dict) and c.get("name")]
    if names:
        out["lexicon"] = names
        out["name"] = names[0]
    for candidate in known:
        strength = candidate.get("strength") if isinstance(candidate, dict) else None
        if isinstance(strength, dict):
            if strength.get("value") is not None:
                out["strength_value"] = strength["value"]
            if strength.get("unit") is not None:
                out["strength_unit"] = strength["unit"]
            break
    return out


def known_candidates_from_request(hints: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(hints, dict):
        return []
    known = hints.get("known_candidates")
    if not isinstance(known, list):
        return []
    return [c for c in known if isinstance(c, dict)]


def quality_reasons(quality: FrameQuality) -> List[str]:
    """Uncertainty reasons derived from the vision quality flags."""
    reasons: List[str] = []
    if quality.blur is not None and quality.blur.is_blurry:
        reasons.append("frame_too_blurry")
    if quality.exposure is not None and quality.exposure.too_dark:
        reasons.append("frame_too_dark")
    if quality.exposure is not None and quality.exposure.too_bright:
        reasons.append("frame_too_bright")
    if quality.glare is not None and quality.glare.has_glare:
        reasons.append("glare_detected")
    if not quality.acceptable and not reasons:
        reasons.append("frame_not_acceptable")
    return reasons


def label_is_clipped(bbox: Any) -> Optional[bool]:
    """v1.2 ``capture.per_frame.clipped``: label region touches a frame edge."""
    if bbox is None:
        return None
    gap = min(bbox.x, bbox.y, 1.0 - (bbox.x + bbox.w), 1.0 - (bbox.y + bbox.h))
    return bool(gap <= _CLIP_EPS)


# --------------------------------------------------------------------------
# Dose (v1.1)
# --------------------------------------------------------------------------
#: Temporary bridge pattern: an optional "Take" + "<number> <unit-word>" dose item.
_DOSE_ITEM_RE = re.compile(r"^\s*(?:take\s+)?(\d+(?:\.\d+)?)\s+([A-Za-z]+)\s*$", re.IGNORECASE)
_PLURAL_FORMS = {"tablets": "tablet", "capsules": "capsule", "pills": "pill", "drops": "drop"}


def _dose_payload(extraction: Extraction, ocr_confidence: float) -> Optional[Dict[str, Any]]:
    """Build the v1.1 ``instructions.dose`` block from PI-2's extraction.

    Prefers ``Extraction.dose_contract()`` once PI-2 ships it; when that method
    is absent, a conservative bridge parses only a single ``<number> <unit>``
    dose item (``1 tablet``). Ambiguous or absent doses are omitted — the API
    never invents a quantity.
    """
    factory = getattr(extraction, "dose_contract", None)
    if callable(factory):
        try:
            payload = factory()
        except Exception:  # noqa: BLE001 - a dose bug must not break a scan
            return None
        if payload is None:
            return None
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        try:
            return DoseInfo.model_validate(payload).model_dump(mode="json")
        except Exception:  # noqa: BLE001 - malformed PI-2 output is omitted
            return None
    return _fallback_dose(extraction, ocr_confidence)


def _fallback_dose(extraction: Extraction, ocr_confidence: float) -> Optional[Dict[str, Any]]:
    """Temporary PI-2 bridge; delete once ``services/ocr`` ships dose_contract()."""
    for item in extraction.instructions:
        if getattr(item, "kind", None) != "dose":
            continue
        match = _DOSE_ITEM_RE.match(item.text or "")
        if match is None:
            continue
        quantity = float(match.group(1))
        if quantity <= 0:
            continue
        return {
            "quantity": quantity,
            "unit": _PLURAL_FORMS.get(match.group(2).lower(), match.group(2).lower()),
            "confidence": round(min(1.0, max(0.0, float(ocr_confidence))), 4),
            "source": "ocr",
        }
    return None


# --------------------------------------------------------------------------
# PI-2 fusion (v1.2 multi-frame)
# --------------------------------------------------------------------------
def _best_string(values: List[FieldString]) -> FieldString:
    present = [value for value in values if value.value is not None]
    if not present:
        return absent_string()
    return max(present, key=lambda value: value.confidence)


def _fallback_fuse(extractions: List[Extraction]) -> tuple:
    """Conservative API-side fusion used until PI-2's fuse_extractions lands.

    Picks the highest-confidence value per field, unions instructions in frame
    order (deduplicated), joins raw text, and reports fields where frames
    disagreed. Never invents a value.
    """
    conflicts: List[str] = []

    def conflicting(field_name: str, entries: List[Any]) -> None:
        distinct = {str(entry) for entry in entries}
        if len(distinct) > 1:
            conflicts.append(f"{field_name}_conflict")

    names = [ext.name for ext in extractions if ext.name.value is not None]
    forms = [ext.form for ext in extractions if ext.form.value is not None]
    manufacturers = [ext.manufacturer for ext in extractions if ext.manufacturer.value is not None]
    strengths = [ext.strength for ext in extractions if ext.strength.value is not None]
    conflicting("name", [entry.value for entry in names])
    conflicting("form", [entry.value for entry in forms])
    conflicting("manufacturer", [entry.value for entry in manufacturers])
    conflicting("strength", [(entry.value, entry.unit) for entry in strengths])

    parsed: List[InstructionItem] = []
    seen: set = set()
    for extraction in extractions:
        for item in extraction.instructions:
            key = (item.kind, item.text)
            if key not in seen:
                seen.add(key)
                parsed.append(item)

    raw_parts: List[str] = []
    for extraction in extractions:
        text = (extraction.raw_text or "").strip()
        if text and text not in raw_parts:
            raw_parts.append(text)

    doses = [ext for ext in extractions if getattr(ext, "dose_quantity", None) is not None]
    conflicting(
        "dose",
        [(ext.dose_quantity, ext.dose_unit) for ext in doses],
    )
    best_dose = (
        max(doses, key=lambda ext: float(getattr(ext, "dose_confidence", 0.0)))
        if doses
        else None
    )

    return (
        Extraction(
            raw_text="\n".join(raw_parts),
            name=_best_string(names),
            strength=max(strengths, key=lambda value: value.confidence) if strengths else absent_strength(),
            form=_best_string(forms),
            manufacturer=_best_string(manufacturers),
            instructions=parsed,
            dose_quantity=best_dose.dose_quantity if best_dose else None,
            dose_unit=best_dose.dose_unit if best_dose else None,
            dose_confidence=best_dose.dose_confidence if best_dose else 0.0,
            dose_source=best_dose.dose_source if best_dose else "none",
        ),
        conflicts,
    )


def _normalize_pi2_fuse(result: Any) -> Optional[tuple]:
    """Normalize PI-2 ``FusionResult`` to ``(Extraction, reasons, frames_used)``."""
    if result is None:
        return None
    extraction = getattr(result, "extraction", None)
    if isinstance(extraction, Extraction):
        conflicts = getattr(result, "conflicts", None) or []
        reasons = [str(c) for c in conflicts]
        frames_used = int(getattr(result, "frames_used", 0) or 0)
        return extraction, reasons, frames_used
    if isinstance(result, tuple) and len(result) == 2:
        fused, conflicts = result
        if isinstance(fused, Extraction):
            return fused, [str(c) for c in (conflicts or [])], 1
        return None
    if isinstance(result, Extraction):
        return result, [], 1
    if isinstance(result, dict) and isinstance(result.get("extraction"), Extraction):
        conflicts = result.get("conflicts") or []
        reasons = [
            c if isinstance(c, str) else f"{c.get('field', c.get('key', 'unknown'))}_conflict"
            for c in conflicts
        ]
        return result["extraction"], reasons, len(result.get("per_frame_confidence") or []) or 1
    return None


def _fuse_extractions(extractions: List[Extraction]) -> tuple:
    """Fuse accepted per-frame extractions: PI-2's helper when available.

    Returns ``(fused_extraction, reasons, frames_used)``.
    """
    if len(extractions) == 1:
        return extractions[0], [], 1
    if importlib.util.find_spec("services.ocr.fuse") is not None:
        from services.ocr.fuse import fuse_extractions  # type: ignore[import-not-found]

        try:
            normalized = _normalize_pi2_fuse(fuse_extractions(extractions))
        except Exception:  # noqa: BLE001 - fusion failure must fall back, not crash
            normalized = None
        if normalized is not None:
            return normalized
    fused, conflicts = _fallback_fuse(extractions)
    return fused, conflicts, len(extractions)


# --------------------------------------------------------------------------
# Dependency loaders
# --------------------------------------------------------------------------
def _load_default_matcher() -> Optional[Callable[..., List[Any]]]:
    """PI-2 registry matcher, activated automatically once it is pushed."""
    if importlib.util.find_spec("services.ocr.matcher") is None:
        return None
    from services.ocr.matcher import match_candidates  # type: ignore[import-not-found]

    return match_candidates


def _default_vlm_client():
    return client_from_env()


# --------------------------------------------------------------------------
# Per-frame analysis result
# --------------------------------------------------------------------------
@dataclass
class FrameResult:
    """One frame's analysis outcome (VLM escalation excluded)."""

    ctx: ScanContext
    index: int = 0
    vision: Any = None
    quality: Optional[FrameQuality] = None
    guidance: List[str] = field(default_factory=list)
    extraction: Optional[Extraction] = None
    raw_text: Optional[str] = None
    ocr_confidence: float = 0.0
    canonical: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    candidates: List[Candidate] = field(default_factory=list)
    candidate_mismatch: bool = False
    uncertainty: Dict[str, Any] = field(default_factory=dict)
    interpretation: Interpretation = field(default_factory=Interpretation)
    stages: Dict[str, float] = field(default_factory=dict)
    status: str = "needs_rescan"
    error: Optional[ErrorInfo] = None

    @property
    def accepted(self) -> bool:
        return self.error is None and self.status in ("ok", "uncertain") and self.extraction is not None

    @property
    def capture_status(self) -> str:
        if self.status in ("ok", "uncertain"):
            return "accepted"
        return self.status


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------
class RealScanPipeline:
    """Real Vision -> OCR -> (matcher) -> (optional VLM) pipeline."""

    mode = "real"

    def __init__(
        self,
        *,
        matcher: Any = _AUTO,
        vlm_client_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        # ``matcher=_AUTO`` loads services.ocr.matcher when present; passing an
        # explicit callable or None overrides that (tests / future wiring).
        self._matcher_override = matcher
        self._vlm_client_factory = vlm_client_factory

    # -- dependency access -------------------------------------------------
    def _get_matcher(self) -> Optional[Callable[..., List[Any]]]:
        if self._matcher_override is not _AUTO:
            return self._matcher_override
        return _load_default_matcher()

    def _interpret(self, image_bytes: bytes, ocr_text: Optional[str]) -> VlmResult:
        try:
            factory = self._vlm_client_factory or _default_vlm_client
            client = factory()
            if hasattr(client, "__enter__"):
                with client as active:
                    return active.interpret(image_bytes, ocr_text, VLM_QUESTION)
            return client.interpret(image_bytes, ocr_text, VLM_QUESTION)
        except Exception as exc:  # noqa: BLE001 - a VLM failure must degrade, not crash
            return VlmResult(available=False, error=f"{type(exc).__name__}: {exc}")

    def _read_label_text(self, image_bytes: bytes, label_bbox: Any):
        rgb = decode_image(image_bytes)
        bbox = None
        if label_bbox is not None:
            bbox = (label_bbox.x, label_bbox.y, label_bbox.w, label_bbox.h)
            try:
                return read_text(rgb, bbox=bbox, channel_order="rgb")
            except ValueError:
                pass  # crop too small/invalid -> read the full frame instead
        return read_text(rgb, bbox=None, channel_order="rgb")

    def _match(self, extraction: Extraction, hints: Optional[Dict[str, Any]]) -> tuple:
        matcher = self._get_matcher()
        known_candidates = known_candidates_from_request(hints)
        candidates: List[Candidate] = []
        candidate_mismatch = False
        if matcher is not None and known_candidates:
            try:
                # PI-2's matcher prefers the Extraction object (its flat-dict
                # path expects plain values, not {value,confidence,source}).
                matched = matcher(extraction, known_candidates, threshold=DEFAULT_MATCHER_THRESHOLD)
                candidates = [Candidate.model_validate(item) for item in matched]
            except Exception:  # noqa: BLE001 - matching must never break a scan
                candidates = []
            has_identity = extraction.name.value is not None or extraction.strength.value is not None
            candidate_mismatch = bool(has_identity and not candidates)
        return candidates, candidate_mismatch

    # -- public API --------------------------------------------------------
    async def scan(self, ctx: ScanContext) -> ScanResponse:
        return await asyncio.to_thread(self._scan_sync, ctx)

    async def scan_multi(self, ctxs: List[ScanContext]) -> ScanResponse:
        return await asyncio.to_thread(self._scan_multi_sync, ctxs)

    # -- per-frame path ----------------------------------------------------
    def _analyze_frame_sync(self, ctx: ScanContext) -> FrameResult:
        stages: Dict[str, float] = {}
        hints = ctx.hints if isinstance(ctx.hints, dict) else {}
        frame = FrameResult(ctx=ctx)

        try:
            vision = analyze_frame(ctx.image, hints=hints)
        except ImageDecodeError:
            frame.status = "error"
            frame.error = ErrorInfo(code="INVALID_IMAGE", message="Could not decode image bytes")
            return frame

        frame.vision = vision
        frame.quality = vision.quality.model_copy(update={"guidance": list(vision.guidance)})
        frame.guidance = list(vision.guidance)
        for name, value in vision.timing.stages.items():
            stages[name] = float(value)
        frame.uncertainty = {
            "level": "high",
            "reasons": quality_reasons(frame.quality),
            "rescan_required": True,
            "fields": {},
        }
        frame.status = "needs_rescan"

        if not vision.quality.acceptable:
            frame.stages = stages
            return frame

        ocr_started = time.perf_counter()
        try:
            ocr_result = self._read_label_text(ctx.image, vision.label.bbox)
        except OcrUnavailableError as exc:
            frame.status = "error"
            frame.error = ErrorInfo(code="OCR_UNAVAILABLE", message=str(exc))
            frame.stages = stages
            return frame
        stages["ocr"] = round((time.perf_counter() - ocr_started) * 1000.0, 3)
        frame.raw_text = ocr_result.raw_text.strip() or None
        frame.ocr_confidence = ocr_result.confidence

        frame.extraction = extract_fields(
            ocr_result.raw_text, hints=extract_hints_from_request(hints)
        )
        frame.canonical = canonical_ocr_fields(frame.extraction, ocr_result.confidence)
        frame.uncertainty = uncertainty_from_fields(frame.canonical)

        match_started = time.perf_counter()
        frame.candidates, frame.candidate_mismatch = self._match(frame.extraction, hints)
        stages["match"] = round((time.perf_counter() - match_started) * 1000.0, 3)
        frame.uncertainty["frame_score"] = frame.quality.score

        frame.status = self._status_for(vision, frame.canonical, frame.uncertainty)
        if frame.status == "no_medication_found":
            if not vision.bottle.detected:
                frame.uncertainty["reasons"].append("no_bottle_detected")
            if not vision.label.detected:
                frame.uncertainty["reasons"].append("no_label_detected")

        frame.stages = stages
        return frame

    def _maybe_escalate(self, frame: FrameResult) -> None:
        """PI-3 VLM escalation for a frame (or a fused pseudo-frame)."""
        if not vlm_enabled() or not frame.vision or not frame.vision.quality.acceptable:
            frame.stages.setdefault("vlm", 0.0)
            return
        if not should_use_vlm(frame.uncertainty, escalation_config(frame.candidate_mismatch)):
            frame.stages.setdefault("vlm", 0.0)
            return
        vlm_started = time.perf_counter()
        vlm_result = self._interpret(frame.ctx.image, frame.raw_text)
        frame.stages["vlm"] = round((time.perf_counter() - vlm_started) * 1000.0, 3)
        if vlm_result.available:
            reconciled = reconcile_fields(frame.canonical, vlm_result.fields)
            frame.canonical = reconciled.fields
            frame.uncertainty = uncertainty_from_fields(frame.canonical)
            frame.uncertainty["frame_score"] = frame.quality.score if frame.quality else 0.0
            frame.uncertainty["reasons"].extend(reconciled.conflict_reasons())
            frame.interpretation = Interpretation(
                available=True,
                summary=vlm_result.summary,
                source="vlm",
                model=vlm_result.model,
            )
        else:
            frame.uncertainty["reasons"].append("vlm_unavailable")

    @staticmethod
    def _status_for(vision: Any, canonical: Dict[str, Dict[str, Any]], uncertainty: Dict[str, Any]) -> str:
        if not vision.quality.acceptable:
            return "needs_rescan"
        name = (canonical.get("name") or {}).get("value")
        strength = (canonical.get("strength_value") or {}).get("value")
        if not vision.bottle.detected and not vision.label.detected and name is None and strength is None:
            return "no_medication_found"
        return "ok" if uncertainty.get("level") == "low" else "uncertain"

    # -- single-frame assembly --------------------------------------------
    def _scan_sync(self, ctx: ScanContext) -> ScanResponse:
        started = time.perf_counter()
        frame = self._analyze_frame_sync(ctx)
        if frame.error is not None:
            return build_error_response(
                ctx.request_id, frame.error.code, frame.error.message, mode="real"
            )
        if frame.vision is not None and frame.vision.quality.acceptable:
            self._maybe_escalate(frame)
            frame.status = self._status_for(frame.vision, frame.canonical, frame.uncertainty)

        total_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return self._build_single_response(ctx.request_id, frame, total_ms)

    def _build_single_response(self, request_id: str, frame: FrameResult, total_ms: float) -> ScanResponse:
        medication, instructions = self._medication_payload(frame)
        uncertainty = Uncertainty(
            level=frame.uncertainty.get("level", "high"),
            reasons=list(dict.fromkeys(frame.uncertainty.get("reasons", []))),
            rescan_required=frame.status == "needs_rescan",
        )
        vision = frame.vision
        label = Label(
            detected=vision.label.detected,
            confidence=vision.label.confidence,
            bbox=vision.label.bbox,
            text=frame.raw_text,
        )
        return ScanResponse(
            request_id=request_id,
            status=frame.status,
            mode="real",
            frame_quality=frame.quality,
            bottle=vision.bottle,
            label=label,
            medication=medication,
            instructions=instructions,
            candidates=frame.candidates,
            interpretation=frame.interpretation,
            uncertainty=uncertainty,
            timing=Timing(
                total_ms=total_ms,
                stages={name: round(float(value), 3) for name, value in frame.stages.items()},
            ),
            safety=Safety(),
            error=None,
        )

    @staticmethod
    def _medication_payload(frame: FrameResult) -> tuple:
        if frame.extraction is None or not frame.canonical:
            return Medication(), Instructions()
        medication = Medication.model_validate(to_contract_medication(frame.canonical))
        instructions_payload: Dict[str, Any] = {
            "raw_text": instructions_raw(frame.canonical),
            "parsed": [item.to_contract() for item in frame.extraction.instructions],
        }
        dose = _dose_payload(frame.extraction, frame.ocr_confidence)
        if dose is not None:
            instructions_payload["dose"] = dose
        return medication, Instructions.model_validate(instructions_payload)

    # -- multi-frame path --------------------------------------------------
    def _scan_multi_sync(self, ctxs: List[ScanContext]) -> ScanResponse:
        started = time.perf_counter()
        frames: List[FrameResult] = []
        for index, ctx in enumerate(ctxs):
            frame = self._analyze_frame_sync(ctx)
            frame.index = index
            frames.append(frame)
        for frame in frames:
            # Multi-frame capture gates on label localization: a frame where the
            # label was not found is never fused (the single-scan full-frame OCR
            # fallback stays single-scan behaviour).
            if (
                frame.error is None
                and frame.vision is not None
                and frame.vision.quality.acceptable
                and not frame.vision.label.detected
            ):
                frame.status = "no_medication_found"
        accepted = [frame for frame in frames if frame.accepted]
        per_frame = [self._per_frame_result(frame) for frame in frames]

        stages: Dict[str, float] = {}
        for frame in frames:
            for name, value in frame.stages.items():
                stages[name] = round(stages.get(name, 0.0) + float(value), 3)

        capture = CaptureInfo(
            frames_requested=len(ctxs),
            frames_used=len(accepted),
            fusion="multi_frame",
            per_frame=per_frame,
        )

        if accepted:
            fusion_started = time.perf_counter()
            fused, fusion_reasons, fused_frames = _fuse_extractions(
                [frame.extraction for frame in accepted]
            )
            capture.frames_used = fused_frames
            stages["fusion"] = round((time.perf_counter() - fusion_started) * 1000.0, 3)
            best = max(accepted, key=lambda frame: frame.quality.score)
            ocr_confidence = max(frame.ocr_confidence for frame in accepted)

            fused_canonical = canonical_ocr_fields(fused, ocr_confidence)
            fused_frame = FrameResult(
                ctx=best.ctx,
                index=best.index,
                vision=best.vision,
                quality=best.quality,
                guidance=best.guidance,
                extraction=fused,
                raw_text=fused.raw_text or "\n".join(
                    frame.raw_text for frame in accepted if frame.raw_text
                ) or None,
                ocr_confidence=ocr_confidence,
                canonical=fused_canonical,
                uncertainty=uncertainty_from_fields(fused_canonical),
                stages={},
            )
            fused_frame.candidates, fused_frame.candidate_mismatch = self._match(
                fused, best.ctx.hints
            )
            fused_frame.uncertainty["frame_score"] = best.quality.score
            self._maybe_escalate(fused_frame)
            # Fusion accounting survives escalation (VLM reconciliation replaces
            # the uncertainty block above).
            if len(accepted) > 1:
                fused_frame.uncertainty["reasons"].append(f"fused_from_{len(accepted)}_frames")
            fused_frame.uncertainty["reasons"].extend(fusion_reasons)
            fused_frame.status = (
                "ok" if fused_frame.uncertainty.get("level") == "low" else "uncertain"
            )

            total_ms = round((time.perf_counter() - started) * 1000.0, 3)
            response = self._build_single_response(ctxs[0].request_id, fused_frame, total_ms)
            response.capture = capture
            response.timing.stages.update(
                {name: round(float(value), 3) for name, value in stages.items()}
            )
            return response

        total_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return self._build_rejected_multi_response(ctxs[0].request_id, frames, capture, stages, total_ms)

    @staticmethod
    def _per_frame_result(frame: FrameResult) -> PerFrameResult:
        vision = frame.vision
        clipped: Optional[bool] = None
        if vision is not None:
            clipped = getattr(vision, "label_clipped", None)
            if clipped is None:
                clipped = label_is_clipped(vision.label.bbox)
        return PerFrameResult(
            index=frame.index,
            status=frame.capture_status,
            label_detected=vision.label.detected if vision is not None else None,
            label_confidence=vision.label.confidence if vision is not None else None,
            clipped=clipped,
            guidance=list(frame.guidance) or None,
        )

    def _build_rejected_multi_response(
        self,
        request_id: str,
        frames: List[FrameResult],
        capture: CaptureInfo,
        stages: Dict[str, float],
        total_ms: float,
    ) -> ScanResponse:
        statuses = [frame.status for frame in frames]
        usable = [frame for frame in frames if frame.vision is not None]
        best = max(usable, key=lambda frame: frame.quality.score) if usable else None

        if all(status == "error" for status in statuses):
            first_error = next(frame.error for frame in frames if frame.error is not None)
            response = build_error_response(
                request_id, first_error.code, first_error.message, mode="real"
            )
            response.capture = capture
            response.timing = Timing(
                total_ms=total_ms,
                stages={name: round(float(value), 3) for name, value in stages.items()},
            )
            return response

        if all(status == "no_medication_found" for status in statuses):
            final_status = "no_medication_found"
            reasons: List[str] = []
            if best is not None and best.vision is not None:
                if not best.vision.bottle.detected:
                    reasons.append("no_bottle_detected")
                if not best.vision.label.detected:
                    reasons.append("no_label_detected")
        else:
            final_status = "needs_rescan"
            reasons = quality_reasons(best.quality) if best is not None and best.quality else ["frame_not_acceptable"]

        quality = best.quality if best is not None and best.quality is not None else FrameQuality(
            acceptable=False, score=0.0, guidance=[]
        )
        bottle = best.vision.bottle if best is not None and best.vision is not None else Bottle(
            detected=False, confidence=0.0
        )
        label = best.vision.label if best is not None and best.vision is not None else Label(
            detected=False, confidence=0.0, text=None
        )
        response = ScanResponse(
            request_id=request_id,
            status=final_status,
            mode="real",
            frame_quality=quality,
            bottle=bottle,
            label=Label(
                detected=label.detected,
                confidence=label.confidence,
                bbox=label.bbox,
                text=label.text,
            ),
            medication=Medication(),
            instructions=Instructions(),
            candidates=[],
            interpretation=Interpretation(available=False),
            uncertainty=Uncertainty(
                level="high",
                reasons=list(dict.fromkeys(reasons)),
                rescan_required=final_status == "needs_rescan",
            ),
            timing=Timing(
                total_ms=total_ms,
                stages={name: round(float(value), 3) for name, value in stages.items()},
            ),
            safety=Safety(),
            error=None,
            capture=capture,
        )
        return response
