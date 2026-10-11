"""Uncertainty reconciliation — decide when the VLM is worth calling and merge
OCR/VLM field reads with source attribution.

The product architecture is OCR-first: the API asks
``should_use_vlm(uncertainty)`` after OCR and only pays for a VLM call when an
escalation field (default: ``name``, ``strength_value``) is missing or weak, the
candidate matcher reports a mismatch, or the frame score is too low. Missing
optional fields (``manufacturer``, ``form``, ``instructions``) never escalate on
their own. ``reconcile_fields`` then merges both reads without ever fabricating
a value.

Equivalence rules (normalization, not semantics) keep noise out of conflicts:
case/whitespace folding, unit aliases (µg/ug -> mcg), dosage-form plurals
("TABLETS" == "Tablet"), leading-token variants for names/manufacturers
("Metformin" == "Metformin HCl", salt/suffix), and parsed-instruction item
comparison. Anything else is a real conflict: both values are preserved and the
resolution reason is recorded. Degenerate OCR text (fewer than 8 ASCII letters,
e.g. a single glyph) is replaced by a readable VLM value for instructions/name
regardless of confidence; the conflict records which rule fired.

Canonical field keys match ``services.vlm.client.CANONICAL_FIELDS``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

DEFAULTS: Dict[str, Any] = {
    # OCR field confidence below this is "weak"
    "min_field_confidence": 0.75,
    # when a rescan is required, prefer retaking the photo over spending a VLM call
    "invoke_on_rescan": False,
    # fields whose missing/weak state triggers escalation; optional fields
    # (manufacturer, form, instructions) never escalate on their own
    "escalation_fields": ("name", "strength_value"),
    # VLM must beat OCR by this margin to replace a disagreeing OCR value
    "prefer_margin": 0.15,
    # ...unless OCR is below min_field_confidence and VLM clears this bar
    "min_vlm_confidence": 0.55,
    # runtime signal from the candidate matcher: no registry match for the read
    "candidate_mismatch": False,
    # runtime signal from multi-frame fusion: frames still disagree after fusion
    "fusion_conflicts": False,
    # frame score below this escalates (None = disabled by default)
    "min_frame_score": None,
    # degenerate-text rule: an OCR value with fewer than this many ASCII letters
    # is replaced by a readable VLM value regardless of the confidence margin
    "degenerate_min_alpha": 8,
    # fields where the degenerate rule applies (instructions primary, name secondary)
    "degenerate_fields": ("instructions", "name"),
}

VALID_LEVELS = ("low", "medium", "high")
_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def _config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    merged = dict(DEFAULTS)
    if config:
        merged.update(config)
    # ``critical_fields`` was the Milestone-2 name; keep it as an alias.
    alias = merged.pop("critical_fields", None)
    if alias is not None:
        merged["escalation_fields"] = tuple(alias)
    merged["escalation_fields"] = tuple(merged.get("escalation_fields") or DEFAULTS["escalation_fields"])
    merged["degenerate_fields"] = tuple(merged.get("degenerate_fields") or DEFAULTS["degenerate_fields"])
    return merged


def should_use_vlm(uncertainty: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> bool:
    """Return True when an OCR read should be escalated to the VLM.

    Parameters
    ----------
    uncertainty:
        ``{"level": "low|medium|high", "reasons": [...], "rescan_required": bool,
        "fields": {canonical_key: {"confidence": 0..1}}, "frame_score": 0..1}``.
        Missing pieces are treated conservatively (missing level -> escalate).
        ``frame_score`` may also be nested at ``frame_quality.score``.
    config:
        Overrides/extra signals for ``DEFAULTS``:

        * ``min_field_confidence`` (float) — weak-field threshold;
        * ``escalation_fields`` (sequence of canonical keys) — only these fields
          can trigger escalation when missing or weak. Optional fields
          (``manufacturer``, ``form``, ``instructions``) never escalate alone.
          ``critical_fields`` is accepted as the Milestone-2 alias;
        * ``candidate_mismatch`` (bool) — runtime signal from the candidate
          matcher: the read did not match any registered candidate. Carried in
          ``config`` because the frozen v1 uncertainty block has no field for it;
          a truthy value escalates even when OCR was confident;
        * ``min_frame_score`` (float | None) — escalate when ``frame_score`` is
          below this value; ``None`` (default) disables the check.

    ``level: "high"`` always escalates; ``medium``/``low`` escalate only on
    missing/weak escalation fields (or when the caller supplies no per-field
    evidence at all, in which case the conservative choice is to escalate).
    """
    cfg = _config(config)
    if uncertainty.get("rescan_required") and not cfg["invoke_on_rescan"]:
        # Retake the photo; the VLM cannot fix a bad frame more cheaply.
        return False

    # Candidate mismatch beats confidence: "Metformin HCI" @ 0.87 reads fine to
    # the OCR but matches no registered drug, so it must be verified.
    if cfg.get("candidate_mismatch") or uncertainty.get("candidate_mismatch"):
        return True

    threshold = cfg.get("min_frame_score")
    if threshold is not None:
        frame_score = uncertainty.get("frame_score")
        if frame_score is None:
            frame_score = (uncertainty.get("frame_quality") or {}).get("score")
        if frame_score is not None and float(frame_score) < float(threshold):
            return True

    level = uncertainty.get("level")
    if level is None:
        return True  # unknown state: escalate rather than guess
    if level == "high":
        return True  # coarse high signal always escalates

    fields = uncertainty.get("fields") or {}
    if not fields:
        return True  # no per-field evidence: escalate rather than guess
    for key in cfg["escalation_fields"]:
        entry = fields.get(key)
        confidence = entry.get("confidence") if isinstance(entry, dict) else None
        if confidence is None or float(confidence) < cfg["min_field_confidence"]:
            return True
    return False


def should_use_vlm_multi(
    uncertainty: Dict[str, Any], config: Optional[Dict[str, Any]] = None
) -> bool:
    """Multi-frame escalation gate: send ALL frames when fusion is inconclusive.

    Single-frame behaviour is untouched; this only adds the fusion trigger. Order:

    1. ``rescan_required`` short-circuits first (retaking beats even a conflict);
    2. **fusion conflicts** escalate — ``uncertainty["fusion_conflicts"]`` is
       truthy (a bool, or a non-empty list of disagreeing canonical field names),
       or the runtime signal is carried in ``config``;
    3. otherwise defer to :func:`should_use_vlm` (weak/missing escalation fields,
       candidate mismatch, low frame score, level ``high``, ...).

    Multi-frame ``uncertainty`` extras the API may pass: ``frames`` (int, how
    many frames were fused; informational) and ``fusion_conflicts`` as above.
    """
    cfg = _config(config)
    if uncertainty.get("rescan_required") and not cfg["invoke_on_rescan"]:
        return False
    if cfg.get("fusion_conflicts") or uncertainty.get("fusion_conflicts"):
        return True
    return should_use_vlm(uncertainty, config)


def _normalize_value(value: Any) -> Any:
    """Comparison key: case/space-insensitive strings, exact numbers."""
    if isinstance(value, str):
        return " ".join(value.lower().split())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


_FORM_PLURALS = {
    "tablets": "tablet",
    "capsules": "capsule",
    "caplets": "caplet",
    "syrups": "syrup",
    "creams": "cream",
    "injections": "injection",
    "suppositories": "suppository",
    "solutions": "solution",
    "suspensions": "suspension",
}

_UNIT_ALIASES = {
    "µg": "mcg",
    "ug": "mcg",
    "microgram": "mcg",
    "micrograms": "mcg",
    "milligram": "mg",
    "milligrams": "mg",
    "gram": "g",
    "grams": "g",
}


def _tokens(value: Any) -> List[str]:
    text = str(value).strip().lower().replace(",", " ")
    return [token for token in (piece.strip(".;:") for piece in text.split()) if token]


def _normalize_form(value: Any) -> str:
    return " ".join(_FORM_PLURALS.get(token, token) for token in _tokens(value))


def _normalize_unit(value: Any) -> str:
    return _UNIT_ALIASES.get(str(value).strip().lower().rstrip("."), str(value).strip().lower())


def _numeric_equal(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _is_prefix_variant(shorter: List[str], longer: List[str]) -> bool:
    return bool(shorter) and len(shorter) <= len(longer) and longer[: len(shorter)] == shorter


def _ascii_alpha_count(value: Any) -> int:
    return sum(1 for char in str(value) if char.isascii() and char.isalpha())


def _degenerate_switch(key: str, ocr_value: Any, vlm_value: Any, cfg: Dict[str, Any]) -> bool:
    """True when OCR text is unreadable-ish and the VLM supplies readable text.

    Strictly a readability switch, not a semantic judgement: it keeps
    ``instructions``/``name`` from being held onto just because OCR was
    confidently wrong (e.g. a single glyph read at 0.90).
    """
    if key not in cfg["degenerate_fields"]:
        return False
    return (
        _ascii_alpha_count(ocr_value) < cfg["degenerate_min_alpha"]
        and _ascii_alpha_count(vlm_value) >= cfg["degenerate_min_alpha"]
    )


def _instruction_items(value: Any) -> List[str]:
    """Normalized parsed-instruction items; falls back to sentence splitting.

    Uses PI-2's parser when importable (no hard dependency on the OCR service).
    """
    try:
        from services.ocr.extract import parse_instructions  # lazy optional import

        items = parse_instructions(str(value))
        normalized = sorted(
            _normalize_value(item.text) for item in items if getattr(item, "text", None)
        )
        if normalized:
            return normalized
    except Exception:  # noqa: BLE001 - OCR stack is optional at reconcile time
        pass
    return sorted(_normalize_value(part) for part in re.split(r"[.;\n]+", str(value)) if part.strip())


def _instructions_equivalent(left: Any, right: Any) -> bool:
    left_items, right_items = _instruction_items(left), _instruction_items(right)
    if left_items and right_items:
        return left_items == right_items
    return _normalize_value(left) == _normalize_value(right)


def _same_value(key: str, left: Any, right: Any) -> bool:
    """True when two reads differ only by normalization noise, per field."""
    if key == "strength_value":
        return _numeric_equal(left, right)
    if key == "strength_unit":
        return _normalize_unit(left) == _normalize_unit(right)
    if key == "form":
        return _normalize_form(left) == _normalize_form(right)
    if key == "instructions":
        return _instructions_equivalent(left, right)
    if key in ("name", "manufacturer"):
        left_tokens, right_tokens = _tokens(left), _tokens(right)
        if left_tokens == right_tokens:
            return True
        shorter, longer = (
            (left_tokens, right_tokens) if len(left_tokens) <= len(right_tokens) else (right_tokens, left_tokens)
        )
        # Conservative salt/suffix rule: "Metformin" == "Metformin HCl".
        return _is_prefix_variant(shorter, longer)
    return _normalize_value(left) == _normalize_value(right)


def _equivalent_choice(key: str, ocr: Dict[str, Any], vlm: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the more specific read when two equivalent values differ textually."""
    confidence = min(1.0, max(ocr["confidence"], vlm["confidence"]))
    if key in ("name", "manufacturer", "form"):
        ocr_tokens, vlm_tokens = _tokens(ocr["value"]), _tokens(vlm["value"])
        if len(vlm_tokens) > len(ocr_tokens) and _is_prefix_variant(ocr_tokens, vlm_tokens):
            return {"value": vlm["value"], "confidence": confidence, "source": "vlm"}
    return {"value": ocr["value"], "confidence": confidence, "source": "ocr"}


@dataclass
class Conflict:
    """A field where OCR and VLM disagree; the winner is still in ``fields``.

    ``kind`` is ``"confidence"`` for normal margin-based resolution or
    ``"degenerate"`` when unreadable OCR text was replaced by readable VLM text.
    """

    key: str
    ocr_value: Any
    vlm_value: Any
    ocr_confidence: float
    vlm_confidence: float
    chosen_source: str
    reason: str = ""
    kind: str = "confidence"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.key,
            "ocr_value": self.ocr_value,
            "vlm_value": self.vlm_value,
            "ocr_confidence": self.ocr_confidence,
            "vlm_confidence": self.vlm_confidence,
            "chosen_source": self.chosen_source,
            "reason": self.reason,
            "kind": self.kind,
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
        reasons: List[str] = []
        for conflict in self.conflicts:
            detail = (
                f"ocr={conflict.ocr_value!r} vlm={conflict.vlm_value!r}, "
                f"kept {conflict.chosen_source}"
            )
            if conflict.kind == "degenerate":
                reasons.append(f"ocr_vlm_degenerate:{conflict.key} ({detail})")
            else:
                reasons.append(
                    f"ocr_vlm_conflict:{conflict.key} ({detail}: {conflict.reason})"
                )
        return reasons


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
    * both reads are equivalent after normalization -> keep the more specific
      value (e.g. the salt form), confidence ``max(ocr, vlm)``; no conflict. See
      the module docstring for the equivalence rules;
    * real disagreement -> VLM wins when ``vlm_conf >= ocr_conf + prefer_margin``,
      or when OCR is below ``min_field_confidence`` and VLM clears
      ``min_vlm_confidence``; **degenerate OCR text** (fewer than
      ``degenerate_min_alpha`` ASCII letters) is replaced by a readable VLM value
      for ``degenerate_fields`` (instructions, name) regardless of the margin;
      otherwise OCR wins. Both values and the resolution reason are recorded on
      the conflict.
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
            # A zero-confidence VLM value is not evidence: the model often emits a default
            # (e.g. form="tablet") for a field the label never states. Drop it instead of
            # presenting a guess as a read.
            if float(vlm["confidence"] or 0) <= 0:
                continue
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
        if _same_value(key, ocr["value"], vlm["value"]):
            result.fields[key] = _equivalent_choice(key, ocr, vlm)
            continue

        if _degenerate_switch(key, ocr["value"], vlm["value"], cfg):
            winner, source, kind = vlm, "vlm", "degenerate"
            reason = (
                f"ocr value has < {cfg['degenerate_min_alpha']} ASCII letters "
                f"(ocr={ocr['value']!r}); vlm value is readable (vlm={vlm['value']!r})"
            )
        else:
            kind = "confidence"
            vlm_wins = vlm["confidence"] >= ocr["confidence"] + cfg["prefer_margin"] or (
                ocr["confidence"] < cfg["min_field_confidence"]
                and vlm["confidence"] >= cfg["min_vlm_confidence"]
            )
            if vlm_wins:
                winner, source = vlm, "vlm"
                if vlm["confidence"] >= ocr["confidence"] + cfg["prefer_margin"]:
                    reason = (
                        f"vlm {vlm['confidence']:.2f} beats ocr {ocr['confidence']:.2f} "
                        f"by >= margin {cfg['prefer_margin']}"
                    )
                else:
                    reason = (
                        f"ocr {ocr['confidence']:.2f} below {cfg['min_field_confidence']} "
                        f"and vlm {vlm['confidence']:.2f} >= {cfg['min_vlm_confidence']}"
                    )
            else:
                winner, source = ocr, "ocr"
                reason = (
                    f"ocr {ocr['confidence']:.2f} kept; vlm {vlm['confidence']:.2f} does not clear "
                    f"margin {cfg['prefer_margin']}"
                )
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
                reason=reason,
                kind=kind,
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

    * an escalation field missing/weak -> ``high``;
    * only optional fields missing/weak -> ``medium`` (the gate still does not
      escalate on optional fields alone);
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
            bump("high" if key in cfg["escalation_fields"] else "medium")
            continue
        confidence = _entry(fields, key)["confidence"]
        confidences[key] = confidence
        if confidence < cfg["min_field_confidence"]:
            reasons.append(f"low_confidence:{key}({confidence:.2f})")
            bump("high" if key in cfg["escalation_fields"] else "medium")

    return {
        "level": level,
        "reasons": reasons,
        "rescan_required": False,
        "fields": {key: {"confidence": value} for key, value in confidences.items()},
    }
