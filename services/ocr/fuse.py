"""Multi-frame label text fusion (contract v1.2, ``POST /v1/scan/multi``).

Combines per-frame :class:`~services.ocr.types.Extraction` results from
overlapping crops of a label that is larger than one camera frame into a single
Extraction. Nothing is invented:

* structured fields are copied from a source frame (highest confidence wins);
* instruction items are verbatim substrings of some frame's raw text;
* conflicting high-confidence values are reported in ``conflicts``;
* ``raw_text`` keeps every frame's text verbatim, separated by explicit markers.

Public API::

    fuse_extractions(extractions) -> FusionResult
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Sequence

from .lexicon import normalize_unit
from .types import (
    Extraction,
    FieldStrength,
    InstructionItem,
    absent_strength,
    absent_string,
)

# A competing value only counts as a conflict at or above this confidence.
CONFIDENCE_FLOOR = 0.5

# Deterministic conflict-reporting order.
_FIELD_ORDER = ("name", "strength", "form", "manufacturer", "dose")


@dataclass
class FusionResult:
    """Result of fusing per-frame extractions.

    Attributes:
        extraction: fused Extraction (all values copied from source frames).
        frames_used: number of frames fused (equals ``len(extractions)``).
        conflicts: e.g. ``["name_conflict", "dose_conflict"]``.
        per_frame_confidence: mean confidence of each frame's present structured
            fields, in input frame order.
    """

    extraction: Extraction
    frames_used: int
    conflicts: list[str]
    per_frame_confidence: list[float]


def extraction_confidence(extraction: Extraction) -> float:
    """Mean confidence of present structured fields (0.0 when none are present)."""
    scores: list[float] = []
    for field in (extraction.name, extraction.strength, extraction.form, extraction.manufacturer):
        if field.value is not None and field.source != "none":
            scores.append(float(field.confidence))
    if extraction.dose_quantity is not None and extraction.dose_source != "none":
        scores.append(float(extraction.dose_confidence))
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def _normalized_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def _alnum_key(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _string_field_key(field: Any) -> str:
    return _alnum_key(str(field.value))


def _strength_key(field: FieldStrength) -> tuple[float, str | None]:
    return (round(float(field.value), 6), normalize_unit(field.unit))


def _pick(
    candidates: list[tuple[int, Any]],
    key_func: Callable[[Any], Any],
    conflicts: list[str],
    field_name: str,
) -> Any | None:
    """Highest-confidence non-null value; conflict when distinct values >= floor."""
    present = [(index, field) for index, field in candidates if field is not None and field.value is not None]
    if not present:
        return None
    significant = {
        key_func(field)
        for _, field in present
        if float(field.confidence) >= CONFIDENCE_FLOOR
    }
    if len(significant) > 1:
        conflicts.append(f"{field_name}_conflict")
    # Highest confidence wins; ties keep the earliest frame.
    return max(present, key=lambda item: (float(item[1].confidence), -item[0]))[1]


def _fuse_dose(extractions: list[Extraction], conflicts: list[str]) -> Extraction | None:
    present = [(index, extraction) for index, extraction in enumerate(extractions) if extraction.dose_quantity is not None]
    if not present:
        return None
    distinct = {
        (round(float(extraction.dose_quantity), 6), normalize_unit(extraction.dose_unit))
        for _, extraction in present
    }
    if len(distinct) > 1:
        conflicts.append("dose_conflict")
    return max(present, key=lambda item: (float(item[1].dose_confidence), -item[0]))[1]


def _fuse_instructions(extractions: list[Extraction], per_frame_confidence: list[float]) -> list[InstructionItem]:
    """Union of parsed items, deduped by normalized text, first-seen order.

    The kept verbatim text is the occurrence from the highest-confidence frame
    (ties keep the first frame).
    """
    fused: list[InstructionItem] = []
    best_confidence: list[float] = []
    index_by_key: dict[str, int] = {}
    for frame_index, extraction in enumerate(extractions):
        frame_confidence = per_frame_confidence[frame_index]
        for item in extraction.instructions:
            key = _normalized_text_key(item.text)
            if not key:
                continue
            existing = index_by_key.get(key)
            if existing is None:
                index_by_key[key] = len(fused)
                fused.append(item)
                best_confidence.append(frame_confidence)
            elif frame_confidence > best_confidence[existing]:
                fused[existing] = item
                best_confidence[existing] = frame_confidence
    return fused


def _fuse_raw_text(extractions: list[Extraction]) -> str:
    fused = extractions[0].raw_text or ""
    for index, extraction in enumerate(extractions[1:], start=2):
        fused += f"\n--- frame {index} ---\n" + (extraction.raw_text or "")
    return fused


def fuse_extractions(extractions: Sequence[Extraction]) -> FusionResult:
    """Fuse per-frame extractions into one Extraction.

    Args:
        extractions: per-frame results in capture order. Must not be empty.

    Returns:
        :class:`FusionResult` with the fused extraction, ``frames_used``,
        conflict reasons, and per-frame confidence.

    Raises:
        ValueError: when ``extractions`` is empty.
    """
    frames = list(extractions)
    if not frames:
        raise ValueError("fuse_extractions requires at least one frame")

    per_frame = [extraction_confidence(extraction) for extraction in frames]
    conflicts: list[str] = []

    if len(frames) == 1:
        single = replace(frames[0], instructions=list(frames[0].instructions))
        return FusionResult(
            extraction=single,
            frames_used=1,
            conflicts=[],
            per_frame_confidence=per_frame,
        )

    name_field = _pick([(i, e.name) for i, e in enumerate(frames)], _string_field_key, conflicts, "name")
    strength_field = _pick([(i, e.strength) for i, e in enumerate(frames)], _strength_key, conflicts, "strength")
    form_field = _pick([(i, e.form) for i, e in enumerate(frames)], _string_field_key, conflicts, "form")
    manufacturer_field = _pick(
        [(i, e.manufacturer) for i, e in enumerate(frames)], _string_field_key, conflicts, "manufacturer"
    )
    dose_frame = _fuse_dose(frames, conflicts)
    instructions = _fuse_instructions(frames, per_frame)

    if strength_field is not None:
        strength_field = FieldStrength(
            value=strength_field.value,
            unit=normalize_unit(strength_field.unit),
            confidence=strength_field.confidence,
            source=strength_field.source,
            raw=strength_field.raw,
        )

    if dose_frame is None:
        dose_quantity, dose_unit, dose_confidence, dose_source = None, None, 0.0, "none"
    else:
        dose_quantity = float(dose_frame.dose_quantity)
        dose_unit = normalize_unit(dose_frame.dose_unit)
        dose_confidence = float(dose_frame.dose_confidence)
        dose_source = dose_frame.dose_source

    fused = Extraction(
        raw_text=_fuse_raw_text(frames),
        name=name_field if name_field is not None else absent_string(),
        strength=strength_field if strength_field is not None else absent_strength(),
        form=form_field if form_field is not None else absent_string(),
        manufacturer=manufacturer_field if manufacturer_field is not None else absent_string(),
        instructions=instructions,
        dose_quantity=dose_quantity,
        dose_unit=dose_unit,
        dose_confidence=dose_confidence,
        dose_source=dose_source,
    )
    conflicts.sort(key=lambda name: _FIELD_ORDER.index(name.removesuffix("_conflict")))
    return FusionResult(
        extraction=fused,
        frames_used=len(frames),
        conflicts=conflicts,
        per_frame_confidence=per_frame,
    )


__all__ = ["CONFIDENCE_FLOOR", "FusionResult", "extraction_confidence", "fuse_extractions"]
