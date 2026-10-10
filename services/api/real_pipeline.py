"""Real OCR-first scan pipeline (Milestone 2).

Composition (the API gateway is the only place services are composed):

    PI-1 Vision.analyze_frame  ->  frame quality + bottle/label localization
      | frame unacceptable       ->  needs_rescan, OCR skipped
      v
    PI-2 OCR.read_text         ->  verbatim raw text (label crop or full frame)
      v
    PI-2 extract_fields        ->  structured medication + instructions
      v
    optional PI-2 matcher      ->  candidates[] (lazy; lands separately)
      v
    optional PI-3 VLM          ->  only when should_use_vlm() says so AND
                                   MEDCHECK_VLM_ENABLED is set (default off)

Everything is synchronous CPU work executed in a worker thread by ``scan()``.
All field values come from the underlying services: this module never invents a
drug name, strength, or instruction (contracts/README.md rule 5).
"""
from __future__ import annotations

import asyncio
import importlib.util
import re
import time
from typing import Any, Callable, Dict, List, Optional

from services.api.pipeline import ScanContext, build_error_response, vlm_enabled
from services.common.contract import (
    Candidate,
    DoseInfo,
    FrameQuality,
    Instructions,
    Interpretation,
    Label,
    Medication,
    Safety,
    ScanResponse,
    Timing,
    Uncertainty,
)
from services.ocr.engine import OcrUnavailableError, read_text
from services.ocr.extract import extract_fields
from services.ocr.types import Extraction
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

_AUTO = object()


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


def _load_default_matcher() -> Optional[Callable[..., List[Any]]]:
    """PI-2 registry matcher, activated automatically once it is pushed."""
    if importlib.util.find_spec("services.ocr.matcher") is None:
        return None
    from services.ocr.matcher import match_candidates  # type: ignore[import-not-found]

    return match_candidates


def _default_vlm_client():
    return client_from_env()


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

    # -- pipeline ----------------------------------------------------------
    async def scan(self, ctx: ScanContext) -> ScanResponse:
        return await asyncio.to_thread(self._scan_sync, ctx)

    def _scan_sync(self, ctx: ScanContext) -> ScanResponse:
        started = time.perf_counter()
        stages: Dict[str, float] = {}
        hints = ctx.hints if isinstance(ctx.hints, dict) else {}

        try:
            vision = analyze_frame(ctx.image, hints=hints)
        except ImageDecodeError:
            return build_error_response(
                ctx.request_id, "INVALID_IMAGE", "Could not decode image bytes", mode="real"
            )

        quality = vision.quality.model_copy(update={"guidance": list(vision.guidance)})
        for name, value in vision.timing.stages.items():
            stages[name] = float(value)

        extraction: Optional[Extraction] = None
        raw_text: Optional[str] = None
        ocr_confidence = 0.0
        canonical: Dict[str, Dict[str, Any]] = {}
        candidates: List[Candidate] = []
        interpretation = Interpretation(available=False)
        uncertainty_dict: Dict[str, Any] = {
            "level": "high",
            "reasons": quality_reasons(quality),
            "rescan_required": True,
            "fields": {},
        }
        status = "needs_rescan"

        if vision.quality.acceptable:
            ocr_started = time.perf_counter()
            try:
                ocr_result = self._read_label_text(ctx.image, vision.label.bbox)
            except OcrUnavailableError as exc:
                return build_error_response(
                    ctx.request_id, "OCR_UNAVAILABLE", str(exc), mode="real"
                )
            stages["ocr"] = round((time.perf_counter() - ocr_started) * 1000.0, 3)
            raw_text = ocr_result.raw_text.strip() or None
            ocr_confidence = ocr_result.confidence

            extraction = extract_fields(ocr_result.raw_text, hints=extract_hints_from_request(hints))
            canonical = canonical_ocr_fields(extraction, ocr_result.confidence)
            uncertainty_dict = uncertainty_from_fields(canonical)

            match_started = time.perf_counter()
            matcher = self._get_matcher()
            known_candidates = known_candidates_from_request(hints)
            candidate_mismatch = False
            if matcher is not None and extraction is not None and known_candidates:
                try:
                    # PI-2's matcher prefers the Extraction object (its flat-dict
                    # path expects plain values, not {value,confidence,source}).
                    matched = matcher(
                        extraction,
                        known_candidates,
                        threshold=DEFAULT_MATCHER_THRESHOLD,
                    )
                    candidates = [Candidate.model_validate(item) for item in matched]
                except Exception:  # noqa: BLE001 - matching must never break a scan
                    candidates = []
                has_identity = (
                    extraction.name.value is not None or extraction.strength.value is not None
                )
                candidate_mismatch = bool(has_identity and not candidates)
            stages["match"] = round((time.perf_counter() - match_started) * 1000.0, 3)

            uncertainty_dict["frame_score"] = quality.score
            if vlm_enabled() and should_use_vlm(uncertainty_dict, escalation_config(candidate_mismatch)):
                vlm_started = time.perf_counter()
                vlm_result = self._interpret(ctx.image, raw_text)
                stages["vlm"] = round((time.perf_counter() - vlm_started) * 1000.0, 3)
                if vlm_result.available:
                    reconciled = reconcile_fields(canonical, vlm_result.fields)
                    canonical = reconciled.fields
                    uncertainty_dict = uncertainty_from_fields(canonical)
                    uncertainty_dict["reasons"].extend(reconciled.conflict_reasons())
                    interpretation = Interpretation(
                        available=True,
                        summary=vlm_result.summary,
                        source="vlm",
                        model=vlm_result.model,
                    )
                else:
                    uncertainty_dict["reasons"].append("vlm_unavailable")
            else:
                stages.setdefault("vlm", 0.0)

            status = self._status_for(vision, canonical, uncertainty_dict)
            if status == "no_medication_found":
                if not vision.bottle.detected:
                    uncertainty_dict["reasons"].append("no_bottle_detected")
                if not vision.label.detected:
                    uncertainty_dict["reasons"].append("no_label_detected")

        if extraction is not None and canonical:
            medication = Medication.model_validate(to_contract_medication(canonical))
            instructions_payload: Dict[str, Any] = {
                "raw_text": instructions_raw(canonical),
                "parsed": [item.to_contract() for item in extraction.instructions],
            }
            dose = _dose_payload(extraction, ocr_confidence)
            if dose is not None:
                instructions_payload["dose"] = dose
            instructions = Instructions.model_validate(instructions_payload)
        else:
            medication = Medication()
            instructions = Instructions()

        total_ms = round((time.perf_counter() - started) * 1000.0, 3)
        timing = Timing(
            total_ms=total_ms,
            stages={name: round(float(value), 3) for name, value in stages.items()},
        )
        uncertainty = Uncertainty(
            level=uncertainty_dict.get("level", "high"),
            reasons=list(dict.fromkeys(uncertainty_dict.get("reasons", []))),
            rescan_required=status == "needs_rescan",
        )
        label = Label(
            detected=vision.label.detected,
            confidence=vision.label.confidence,
            bbox=vision.label.bbox,
            text=raw_text,
        )
        return ScanResponse(
            request_id=ctx.request_id,
            status=status,
            mode="real",
            frame_quality=quality,
            bottle=vision.bottle,
            label=label,
            medication=medication,
            instructions=instructions,
            candidates=candidates,
            interpretation=interpretation,
            uncertainty=uncertainty,
            timing=timing,
            safety=Safety(),
            error=None,
        )

    @staticmethod
    def _status_for(vision: Any, canonical: Dict[str, Dict[str, Any]], uncertainty: Dict[str, Any]) -> str:
        if not vision.quality.acceptable:
            return "needs_rescan"
        name = (canonical.get("name") or {}).get("value")
        strength = (canonical.get("strength_value") or {}).get("value")
        if not vision.bottle.detected and not vision.label.detected and name is None and strength is None:
            return "no_medication_found"
        return "ok" if uncertainty.get("level") == "low" else "uncertain"
