"""Multi-frame fusion tests (contract v1.2): synthetic frames + real samples."""

from __future__ import annotations

import pytest

from services.ocr.fuse import FusionResult, extraction_confidence, fuse_extractions
from services.ocr.types import Extraction, FieldString, FieldStrength, InstructionItem


def _frame(
    raw: str = "",
    name: str | None = None,
    name_conf: float = 0.95,
    strength: tuple[float, str] | None = None,
    strength_conf: float = 0.9,
    form: str | None = None,
    form_conf: float = 0.9,
    manufacturer: str | None = None,
    mfr_conf: float = 0.6,
    instructions: tuple[tuple[str, str], ...] = (),
    dose: tuple[float, str] | None = None,
    dose_conf: float = 0.0,
) -> Extraction:
    return Extraction(
        raw_text=raw,
        name=FieldString(value=name, confidence=name_conf if name else 0.0, source="ocr" if name else "none"),
        strength=FieldStrength(
            value=strength[0] if strength else None,
            unit=strength[1] if strength else None,
            confidence=strength_conf if strength else 0.0,
            source="ocr" if strength else "none",
        ),
        form=FieldString(value=form, confidence=form_conf if form else 0.0, source="ocr" if form else "none"),
        manufacturer=FieldString(
            value=manufacturer, confidence=mfr_conf if manufacturer else 0.0, source="ocr" if manufacturer else "none"
        ),
        instructions=[InstructionItem(kind=kind, text=text) for kind, text in instructions],
        dose_quantity=dose[0] if dose else None,
        dose_unit=dose[1] if dose else None,
        dose_confidence=dose_conf if dose else 0.0,
        dose_source="ocr" if dose else "none",
    )


# --------------------------------------------------------------------------- #
# Empty / single
# --------------------------------------------------------------------------- #


def test_empty_list_raises_value_error():
    with pytest.raises(ValueError):
        fuse_extractions([])


def test_single_frame_is_passthrough():
    frame = _frame(raw="Hydrochlorothiazide 25 mg Tablets", name="Hydrochlorothiazide", strength=(25, "mg"), form="tablet")
    result = fuse_extractions([frame])
    assert isinstance(result, FusionResult)
    assert result.frames_used == 1
    assert result.conflicts == []
    assert len(result.per_frame_confidence) == 1
    assert result.extraction.raw_text == frame.raw_text  # no frame markers
    assert result.extraction.name.value == "Hydrochlorothiazide"
    assert result.extraction.strength.value == 25
    assert result.extraction.instructions == frame.instructions


# --------------------------------------------------------------------------- #
# Field fusion and conflicts
# --------------------------------------------------------------------------- #


def test_name_highest_confidence_wins():
    low = _frame(name="Metformin", name_conf=0.5)
    high = _frame(name="Metformin", name_conf=0.95)
    result = fuse_extractions([low, high])
    assert result.extraction.name.value == "Metformin"
    assert result.extraction.name.confidence == pytest.approx(0.95)
    assert result.conflicts == []


def test_name_conflict_reported_and_higher_kept():
    first = _frame(name="Metformin", name_conf=0.9)
    second = _frame(name="Glipizide", name_conf=0.8)
    result = fuse_extractions([first, second])
    assert result.extraction.name.value == "Metformin"
    assert "name_conflict" in result.conflicts


def test_low_confidence_differing_name_is_not_a_conflict():
    strong = _frame(name="Hydrochlorothiazide", name_conf=0.95)
    weak = _frame(name="OTHIAZIDE", name_conf=0.3)
    result = fuse_extractions([strong, weak])
    assert result.extraction.name.value == "Hydrochlorothiazide"
    assert result.conflicts == []


def test_strength_normalized_comparison_avoids_false_conflict():
    first = _frame(strength=(500, "MG"), strength_conf=0.9)
    second = _frame(strength=(500, "mg"), strength_conf=0.85)
    result = fuse_extractions([first, second])
    assert (result.extraction.strength.value, result.extraction.strength.unit) == (500.0, "mg")
    assert result.conflicts == []


def test_strength_conflict_reported():
    first = _frame(strength=(25, "mg"), strength_conf=0.9)
    second = _frame(strength=(50, "mg"), strength_conf=0.9)
    result = fuse_extractions([first, second])
    assert result.extraction.strength.value == 25.0  # tie -> earliest frame
    assert "strength_conflict" in result.conflicts


def test_form_conflict_reported():
    first = _frame(form="tablet", form_conf=0.9)
    second = _frame(form="capsule", form_conf=0.8)
    result = fuse_extractions([first, second])
    assert result.extraction.form.value == "tablet"
    assert "form_conflict" in result.conflicts


def test_manufacturer_highest_confidence_and_conflict():
    first = _frame(manufacturer="DemoPharma Ltd.", mfr_conf=0.6)
    second = _frame(manufacturer="OtherPharma Inc.", mfr_conf=0.7)
    result = fuse_extractions([first, second])
    assert result.extraction.manufacturer.value == "OtherPharma Inc."
    assert "manufacturer_conflict" in result.conflicts


# --------------------------------------------------------------------------- #
# Instructions
# --------------------------------------------------------------------------- #


def test_instructions_union_deduped_by_normalized_text():
    first = _frame(instructions=(("dose", "Take 1 tablet by mouth"),))
    second = _frame(instructions=(("dose", "take  1 TABLET by mouth"), ("route", "by mouth")))
    result = fuse_extractions([first, second])
    texts = [item.text for item in result.extraction.instructions]
    assert texts == ["Take 1 tablet by mouth", "by mouth"]
    assert len(result.extraction.instructions) == 2  # case/spacing duplicates collapse


def test_instruction_text_kept_from_higher_confidence_frame():
    low = _frame(name="Metformin", name_conf=0.6, instructions=(("dose", "take 1 tablet"),))
    high = _frame(name="Metformin", name_conf=0.95, instructions=(("dose", "TAKE 1 TABLET"),))
    result = fuse_extractions([low, high])
    assert len(result.extraction.instructions) == 1
    assert result.extraction.instructions[0].text == "TAKE 1 TABLET"


def test_instructions_first_seen_order_across_frames():
    first = _frame(instructions=(("dose", "Take 1 tablet"), ("frequency", "once daily")))
    second = _frame(instructions=(("frequency", "once daily"), ("duration", "for 7 days")))
    result = fuse_extractions([first, second])
    assert [item.text for item in result.extraction.instructions] == ["Take 1 tablet", "once daily", "for 7 days"]


# --------------------------------------------------------------------------- #
# Dose, raw text, per-frame confidence, fabrication guard
# --------------------------------------------------------------------------- #


def test_dose_highest_confidence_wins_and_conflict_reported():
    first = _frame(dose=(1.0, "tablet"), dose_conf=0.9)
    second = _frame(dose=(2.0, "tablet"), dose_conf=0.8)
    result = fuse_extractions([first, second])
    assert (result.extraction.dose_quantity, result.extraction.dose_unit) == (1.0, "tablet")
    assert result.extraction.dose_confidence == pytest.approx(0.9)
    assert "dose_conflict" in result.conflicts


def test_missing_dose_in_other_frames_is_not_a_conflict():
    with_dose = _frame(dose=(1.0, "tablet"), dose_conf=0.9)
    without = _frame()
    result = fuse_extractions([without, with_dose])
    assert (result.extraction.dose_quantity, result.extraction.dose_unit) == (1.0, "tablet")
    assert result.conflicts == []


def test_raw_text_frames_joined_verbatim_with_markers():
    frames = [_frame(raw="AAA"), _frame(raw="BBB"), _frame(raw="CCC")]
    result = fuse_extractions(frames)
    assert result.extraction.raw_text == "AAA\n--- frame 2 ---\nBBB\n--- frame 3 ---\nCCC"


def test_per_frame_confidence_is_mean_of_present_fields():
    frame = _frame(name="Metformin", name_conf=0.9, strength=(500, "mg"), strength_conf=0.8, form="tablet", form_conf=0.7)
    result = fuse_extractions([frame, _frame()])
    assert result.per_frame_confidence[0] == pytest.approx(0.8)
    assert result.per_frame_confidence[1] == pytest.approx(0.0)
    assert extraction_confidence(frame) == pytest.approx(0.8)


def test_fusion_never_fabricates_text():
    raws = ["Metformin\nTake 1 tablet by mouth once daily in the morning.", "Swallow whole with a glass of water."]
    frames = [
        _frame(raw=raws[0], name="Metformin", instructions=(("dose", "Take 1 tablet"), ("frequency", "once daily"))),
        _frame(raw=raws[1], instructions=(("warning", "Swallow whole with a glass of water."),)),
    ]
    result = fuse_extractions(frames)
    for item in result.extraction.instructions:
        assert any(item.text in raw for raw in raws)
    name = result.extraction.name.value or ""
    assert any(name.casefold() in raw.casefold() for raw in raws)


# --------------------------------------------------------------------------- #
# Real long-label thirds (backend-fit evidence)
# --------------------------------------------------------------------------- #


def test_fuse_real_long_label_thirds():
    pytest.importorskip("rapidocr_onnxruntime")
    from services.ocr.engine import read_text
    from services.ocr.extract import extract_fields

    frames = [
        extract_fields(read_text(f"samples/long_label_{part}.png").raw_text)
        for part in ("left", "middle", "right")
    ]
    result = fuse_extractions(frames)
    extraction = result.extraction

    assert result.frames_used == 3
    assert extraction.name.value == "Hydrochlorothiazide"
    assert (extraction.strength.value, extraction.strength.unit) == (25.0, "mg")
    assert (extraction.dose_quantity, extraction.dose_unit) == (1.0, "tablet")
    assert extraction.form.value == "tablet"
    assert result.conflicts == []

    texts = [item.text.casefold() for item in extraction.instructions]
    assert any("morning" in text for text in texts), texts
    assert any("water" in text for text in texts), texts
    assert any(item.kind == "warning" for item in extraction.instructions)

    raws = [frame.raw_text for frame in frames]
    for item in extraction.instructions:
        assert any(item.text in raw for raw in raws)
