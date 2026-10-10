"""Registered-candidate matcher for MedCheck (PI-2 / Orion).

Objective: medication identification against caller-supplied registered
candidates. The matcher scores OCR extraction fields (name + strength) against
each candidate and returns contract-shaped ``Candidate`` models, best first.

Safety invariants:

* Candidates are **only** the ones passed in; the matcher never invents a name
  or looks one up from the lexicon.
* A strength mismatch is a hard signal: exact name + mismatched strength scores
  below the default threshold and is dropped.
* Scores are clamped to ``[0, 1]``; output models carry ``source="registry"``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from services.common.contract import Candidate, CandidateStrength

from .lexicon import name_similarity, normalize_unit
from .types import Extraction

DEFAULT_THRESHOLD = 0.75
NAME_WEIGHT = 0.70
STRENGTH_WEIGHT = 0.30
# When one side has no usable strength, name similarity is scaled by this
# factor (uncertainty penalty) instead of pretending strength agrees.
UNVERIFIED_STRENGTH_FACTOR = 0.90
# Names below this similarity are not considered registered matches at all.
MIN_NAME_SIMILARITY = 0.55

# Canonical unit -> (family, factor to the family base unit).
_UNIT_TABLE: dict[str, tuple[str, float]] = {
    "mg": ("mass", 1.0),
    "mcg": ("mass", 0.001),
    "g": ("mass", 1000.0),
    "ml": ("volume", 1.0),
    "IU": ("iu", 1.0),
    "unit": ("unit", 1.0),
    "%": ("percent", 1.0),
}


@dataclass(frozen=True)
class _Query:
    name: str | None
    value: float | None
    unit: str | None


@dataclass(frozen=True)
class _CandidateInput:
    name: str
    value: float | None
    unit: str | None
    index: int

    @property
    def has_strength(self) -> bool:
        return self.value is not None or self.unit is not None


# --------------------------------------------------------------------------- #
# Input coercion (Extraction, dict, contract models are all accepted)
# --------------------------------------------------------------------------- #


def _coerce_name(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, Mapping):
        return _coerce_name(raw.get("value"))
    value = getattr(raw, "value", None)
    if value is None:
        return None
    return _coerce_name(value)


def _coerce_strength(raw: Any) -> tuple[float | None, str | None]:
    if raw is None:
        return None, None
    if isinstance(raw, str):
        match = re.fullmatch(r"\s*([0-9]+(?:[.,][0-9]+)?)\s*([A-Za-zµ%]+)\s*", raw)
        if not match:
            return None, None
        return float(match.group(1).replace(",", ".")), match.group(2)
    if isinstance(raw, Mapping):
        value, unit = raw.get("value"), raw.get("unit")
    elif isinstance(raw, (tuple, list)) and len(raw) == 2:
        value, unit = raw
    else:
        value, unit = getattr(raw, "value", None), getattr(raw, "unit", None)
    try:
        numeric = float(value) if value is not None else None
    except (TypeError, ValueError):
        numeric = None
    text = str(unit).strip() if unit is not None else None
    return numeric, (text or None)


def _coerce_fields(fields: Any) -> _Query:
    if fields is None:
        return _Query(None, None, None)
    if isinstance(fields, Extraction):
        value, unit = fields.strength.value, fields.strength.unit
        return _Query(fields.name.value, value, unit)
    if isinstance(fields, Mapping):
        name = _coerce_name(fields.get("name"))
        strength_raw = fields.get("strength")
        if strength_raw is None and ("strength_value" in fields or "strength_unit" in fields):
            strength_raw = {"value": fields.get("strength_value"), "unit": fields.get("strength_unit")}
        value, unit = _coerce_strength(strength_raw)
        return _Query(name, value, unit)
    name = _coerce_name(getattr(fields, "name", None))
    value, unit = _coerce_strength(getattr(fields, "strength", None))
    return _Query(name, value, unit)


def _coerce_candidate(raw: Any, index: int) -> _CandidateInput | None:
    if isinstance(raw, Mapping):
        name = _coerce_name(raw.get("name"))
        value, unit = _coerce_strength(raw.get("strength"))
    else:
        name = _coerce_name(getattr(raw, "name", None))
        value, unit = _coerce_strength(getattr(raw, "strength", None))
    if not name:
        return None
    return _CandidateInput(name=name, value=value, unit=unit, index=index)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _strength_points(
    query_value: float | None,
    query_unit: str | None,
    candidate_value: float | None,
    candidate_unit: str | None,
) -> float | None:
    """``1.0`` exact (after unit conversion), ``0.0`` mismatch, ``None`` unverifiable."""
    if query_value is None or query_unit is None or candidate_value is None or candidate_unit is None:
        return None
    query_unit = normalize_unit(query_unit)
    candidate_unit = normalize_unit(candidate_unit)
    if query_unit is None or candidate_unit is None:
        return None

    query_entry = _UNIT_TABLE.get(query_unit)
    candidate_entry = _UNIT_TABLE.get(candidate_unit)
    if query_entry is None or candidate_entry is None:
        # Unknown units: only exact spelling + value counts as agreement.
        same = query_unit == candidate_unit and math.isclose(query_value, candidate_value, rel_tol=1e-3)
        return 1.0 if same else 0.0

    query_family, query_factor = query_entry
    candidate_family, candidate_factor = candidate_entry
    if query_family != candidate_family:
        return 0.0
    return 1.0 if math.isclose(query_value * query_factor, candidate_value * candidate_factor, rel_tol=1e-3) else 0.0


def _output_strength(candidate: _CandidateInput) -> CandidateStrength | None:
    if not candidate.has_strength:
        return None
    unit = normalize_unit(candidate.unit) if candidate.unit is not None else None
    return CandidateStrength(value=candidate.value, unit=unit)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def match_candidates(
    fields: Extraction | Mapping[str, Any],
    candidates: Iterable[Any],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Candidate]:
    """Match extraction fields against registered candidates, best first.

    Args:
        fields: :class:`~services.ocr.types.Extraction` (usual case) or a
            mapping like ``{"name": ..., "strength": {"value": ..., "unit": ...}}``.
            ``name``/``strength`` may be plain values, contract field models, or
            ``FieldString``/``FieldStrength`` instances.
        candidates: iterable of registered candidates; mappings like
            ``{"name": "Metformin", "strength": {"value": 500, "unit": "mg"}}`` or
            contract ``Candidate`` models. Entries without a name are skipped.
        threshold: minimum score to keep (inclusive), default ``0.75``.

    Returns:
        Contract ``Candidate`` models sorted by descending score (input order
        breaks ties), each with ``source="registry"``. Returns ``[]`` when no
        name is available, when the candidate list is empty, or when every
        candidate scores below ``threshold``.

    Raises:
        ValueError: if ``threshold`` is outside ``[0, 1]``.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be within [0, 1]")
    query = _coerce_fields(fields)
    if query.name is None or candidates is None:
        return []

    scored: list[tuple[int, Candidate]] = []
    for index, raw_candidate in enumerate(candidates):
        candidate = _coerce_candidate(raw_candidate, index)
        if candidate is None:
            continue
        similarity = name_similarity(query.name, candidate.name)
        if similarity < MIN_NAME_SIMILARITY:
            continue
        strength_points = _strength_points(query.value, query.unit, candidate.value, candidate.unit)
        if strength_points is None:
            score = UNVERIFIED_STRENGTH_FACTOR * similarity
        else:
            score = NAME_WEIGHT * similarity + STRENGTH_WEIGHT * strength_points
        score = max(0.0, min(1.0, round(score, 6)))
        if score < threshold:
            continue
        scored.append(
            (
                index,
                Candidate(
                    name=candidate.name,
                    strength=_output_strength(candidate),
                    score=score,
                    source="registry",
                ),
            )
        )

    scored.sort(key=lambda item: (-item[1].score, item[0]))
    return [candidate for _, candidate in scored]


__all__ = ["DEFAULT_THRESHOLD", "match_candidates"]
