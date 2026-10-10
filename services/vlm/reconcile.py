"""Uncertainty reconciliation — decide when the VLM is worth calling and merge
OCR/VLM field reads with source attribution.

The product architecture is OCR-first: the API asks
``should_use_vlm(uncertainty)`` after OCR and only pays for a VLM call when the
OCR read is weak or a critical field is low-confidence. ``reconcile_fields``
then merges both reads without ever fabricating a value.

Canonical field keys match ``services.vlm.client.CANONICAL_FIELDS``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

DEFAULTS: Dict[str, Any] = {
    # OCR field confidence below this is "weak"
    "min_field_confidence": 0.75,
    # uncertainty levels that alone justify a VLM call
    "invoke_on_levels": ("medium", "high"),
    # when a rescan is required, prefer retaking the photo over spending a VLM call
    "invoke_on_rescan": False,
    # fields that matter enough to trigger the VLM even at level "low"
    "critical_fields": ("name", "strength_value"),
    # VLM must beat OCR by this margin to replace a disagreeing OCR value
    "prefer_margin": 0.15,
    # ...unless OCR is below min_field_confidence and VLM clears this bar
    "min_vlm_confidence": 0.55,
}

VALID_LEVELS = ("low", "medium", "high")
_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def _config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    merged = dict(DEFAULTS)
    if config:
        merged.update(config)
    return merged


def should_use_vlm(uncertainty: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> bool:
    """Return True when an OCR read should be escalated to the VLM.

    Parameters
    ----------
    uncertainty:
        ``{"level": "low|medium|high", "reasons": [...], "rescan_required": bool,
        "fields": {canonical_key: {"confidence": 0..1}}}``. Missing pieces are
        treated conservatively (missing level -> escalate).
    config:
        Optional overrides of ``DEFAULTS``.
    """
    cfg = _config(config)
    if uncertainty.get("rescan_required") and not cfg["invoke_on_rescan"]:
        # Retake the photo; the VLM cannot fix a bad frame more cheaply.
        return False

    level = uncertainty.get("level")
    if level is None:
        return True  # unknown state: escalate rather than guess
    if level in cfg["invoke_on_levels"]:
        return True

    fields = uncertainty.get("fields") or {}
    for key in cfg["critical_fields"]:
        entry = fields.get(key) or {}
        confidence = entry.get("confidence")
        if confidence is None or float(confidence) < cfg["min_field_confidence"]:
            return True
    return False


def _normalize_value(value: Any) -> Any:
    """Comparison key: case/space-insensitive strings, exact numbers."""
    if isinstance(value, str):
        return " ".join(value.lower().split())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _same_value(left: Any, right: Any) -> bool:
    return _normalize_value(left) == _normalize_value(right)


@dataclass
class Conflict:
    """A field where OCR and VLM disagree; the winner is still in fields."""

    key: str
    ocr_value: Any
    vlm_value: Any
    ocr_confidence: float
    vlm_confidence: float
    chosen_source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.key,
            "ocr_value": self.ocr_value,
            "vlm_value": self.vlm_value,
            "ocr_confidence": self.ocr_confidence,
            "vlm_confidence": self.vlm_confidence,
            "chosen_source": self.chosen_source,
        }


@dataclass
class ReconcileResult:
    fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    conflicts: List[Conflict] = field(default_factory=list)
    used_vlm: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fields": self.fields,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "used_vlm": self.used_vlm,
        }

    def conflict_reasons(self) -> List[str]:
        """Human-readable reasons suitable for ``uncertainty.reasons``."""
        return [
            f"ocr_vlm_conflict:{c.key} (ocr={c.ocr_value!r} vlm={c.vlm_value!r}, kept {c.chosen_source})"
            for c in self.conflicts
        ]


def _entry(fields: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    entry = fields.get(key)
    if not isinstance(entry, dict):
        return None
    if entry.get("value") is None:
        return None
    confidence = entry.get("confidence", 0.5)
    try:
        confidence = min(1.0, max(0.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5
    return {"value": entry["value"], "confidence": confidence, "source": entry.get("source")}


def reconcile_fields(
    ocr_fields: Dict[str, Any],
    vlm_fields: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> ReconcileResult:
    """Merge OCR and VLM reads, attributing each kept value to its source.

    Rules (deterministic, no fabrication):

    * only one side has the field -> use it;
    * both agree -> keep OCR's value, confidence ``max(ocr, vlm)``, source OCR;
    * both disagree -> VLM wins when ``vlm_conf >= ocr_conf + prefer_margin``,
      or when OCR is below ``min_field_confidence`` and VLM clears
      ``min_vlm_confidence``; otherwise OCR wins. Every disagreement is recorded.
    """
    cfg = _config(config)
    keys: Iterable[str] = sorted(set(ocr_fields) | set(vlm_fields))
    result = ReconcileResult(used_vlm=bool(vlm_fields))

    for key in keys:
        ocr = _entry(ocr_fields, key)
        vlm = _entry(vlm_fields, key)
        if ocr is None and vlm is None:
            continue
        if ocr is None:
            result.fields[key] = {
                "value": vlm["value"],
                "confidence": vlm["confidence"],
                "source": "vlm",
            }
            continue
        if vlm is None:
            result.fields[key] = {
                "value": ocr["value"],
                "confidence": ocr["confidence"],
                "source": "ocr",
            }
            continue
        if _same_value(ocr["value"], vlm["value"]):
            result.fields[key] = {
                "value": ocr["value"],
                "confidence": min(1.0, max(ocr["confidence"], vlm["confidence"])),
                "source": "ocr",
            }
            continue

        vlm_wins = vlm["confidence"] >= ocr["confidence"] + cfg["prefer_margin"] or (
            ocr["confidence"] < cfg["min_field_confidence"]
            and vlm["confidence"] >= cfg["min_vlm_confidence"]
        )
        winner = vlm if vlm_wins else ocr
        source = "vlm" if vlm_wins else "ocr"
        result.fields[key] = {
            "value": winner["value"],
            "confidence": winner["confidence"],
            "source": source,
        }
        result.conflicts.append(
            Conflict(
                key=key,
                ocr_value=ocr["value"],
                vlm_value=vlm["value"],
                ocr_confidence=ocr["confidence"],
                vlm_confidence=vlm["confidence"],
                chosen_source=source,
            )
        )
    return result


def to_contract_medication(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Map canonical reconcile output onto the frozen contract's medication shape.

    Returns a dict matching ``medication`` in ``contracts/v1/scan_response.schema.json``
    (FieldString / FieldStrength). Only fields actually present are emitted.
    """
    def field_string(key: str) -> Optional[Dict[str, Any]]:
        entry = fields.get(key)
        if not entry or entry.get("value") is None:
            return None
        return {
            "value": str(entry["value"]),
            "confidence": float(entry.get("confidence", 0.0)),
            "source": entry.get("source", "none"),
        }

    medication: Dict[str, Any] = {
        "name": field_string("name")
        or {"value": None, "confidence": 0.0, "source": "none"}
    }
    strength_value = fields.get("strength_value")
    strength_unit = fields.get("strength_unit")
    if strength_value and strength_value.get("value") is not None:
        sources = {
            (strength_value or {}).get("source"),
            (strength_unit or {}).get("source"),
        }
        confidences = [
            float((strength_value or {}).get("confidence", 0.0)),
            float((strength_unit or {}).get("confidence", 0.0)) if strength_unit else 0.0,
        ]
        medication["strength"] = {
            "value": strength_value["value"],
            "unit": (strength_unit or {}).get("value"),
            "confidence": max(confidences),
            "source": sorted(s for s in sources if s)[0] if any(sources) else "none",
        }
    for key, contract_key in (("form", "form"), ("manufacturer", "manufacturer")):
        value = field_string(key)
        if value:
            medication[contract_key] = value
    return medication


def instructions_raw(fields: Dict[str, Any]) -> Optional[str]:
    """Verbatim instruction text if either reader captured it."""
    entry = fields.get("instructions")
    if not entry or entry.get("value") is None:
        return None
    return str(entry["value"])


# Expected fields used when grading an OCR read into an uncertainty object.
_EXPECTED_FIELDS = (
    "name",
    "strength_value",
    "strength_unit",
    "form",
    "manufacturer",
    "instructions",
)


def uncertainty_from_fields(
    fields: Dict[str, Any], config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Derive a contract-shaped uncertainty block from extracted field confidences.

    Used by OCR-first callers (and the evaluation) to decide whether to escalate:

    * any critical field missing/weak -> ``high``;
    * only non-critical fields missing/weak -> ``medium``;
    * everything present and confident -> ``low``.

    ``rescan_required`` is left False here; frame quality (vision service) owns it
    and the API may OR it in.
    """
    cfg = _config(config)
    reasons: List[str] = []
    level = "low"
    confidences: Dict[str, float] = {}

    def bump(candidate: str) -> None:
        nonlocal level
        if _LEVEL_RANK[candidate] > _LEVEL_RANK[level]:
            level = candidate

    for key in _EXPECTED_FIELDS:
        entry = fields.get(key)
        if not isinstance(entry, dict) or entry.get("value") is None:
            reason = f"missing:{key}"
            reasons.append(reason)
            bump("high" if key in cfg["critical_fields"] else "medium")
            continue
        confidence = _entry(fields, key)["confidence"]
        confidences[key] = confidence
        if confidence < cfg["min_field_confidence"]:
            reasons.append(f"low_confidence:{key}({confidence:.2f})")
            bump("high" if key in cfg["critical_fields"] else "medium")

    return {
        "level": level,
        "reasons": reasons,
        "rescan_required": False,
        "fields": {key: {"confidence": value} for key, value in confidences.items()},
    }
