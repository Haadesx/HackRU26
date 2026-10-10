"""Contract v1.3 `label_meta` extraction tests."""

from __future__ import annotations

import pytest

from services.common.contract import LabelMeta
from services.ocr.extract import extract_fields, parse_label_meta
from services.ocr.fuse import fuse_extractions
from services.ocr.types import LABEL_META_KEYS

FULL_LABEL = (
    "METFORMIN HCl 500 mg\n"
    "TABLETS | Rx only\n"
    "Take 1 tablet by mouth twice daily with meals.\n"
    "QTY 30\n"
    "Refills: 2\n"
    "Demo Pharmacy\n"
    "Tel: (555) 010-2030\n"
    "Prescriber: Dr. A. Demo\n"
    "SYNTHETIC TEST LABEL - NOT FOR MEDICAL USE"
)


def _meta(raw: str) -> dict:
    return extract_fields(raw).label_meta


# --------------------------------------------------------------------------- #
# Quantity / refills
# --------------------------------------------------------------------------- #


def test_quantity_start_extracted_verbatim():
    field = _meta("QTY 30")["quantity_start"]
    assert field.value == "30"
    assert field.confidence == pytest.approx(0.9)
    assert field.source == "ocr"


def test_quantity_variants_and_glued_spacing():
    assert _meta("Qty: 90")["quantity_start"].value == "90"
    assert _meta("QTY#30")["quantity_start"].value == "30"
    assert _meta("QTY30")["quantity_start"].value == "30"


def test_refills_extracted():
    field = _meta("Refills: 2")["refills_remaining"]
    assert field.value == "2"
    assert field.confidence == pytest.approx(0.9)


def test_no_refills_maps_to_zero():
    for raw in ("No refills", "NO REFILLS.", "no refill"):
        field = _meta(raw)["refills_remaining"]
        assert field.value == "0"
        assert field.source == "ocr"


def test_ocr_noise_quantity_is_not_guessed():
    # "3O" with letter O is OCR noise; never fabricate "30".
    field = _meta("QTY 3O")["quantity_start"]
    assert field.value is None and field.source == "none"


# --------------------------------------------------------------------------- #
# Pharmacy / phone / prescriber
# --------------------------------------------------------------------------- #


def test_pharmacy_name_from_line():
    field = _meta("Demo Pharmacy")["pharmacy_name"]
    assert field.value == "Demo Pharmacy"
    assert field.source == "ocr"


def test_pharmacy_name_labeled():
    assert _meta("Pharmacy: Sample Drug Store")["pharmacy_name"].value == "Sample Drug Store"


def test_pharmacy_name_and_phone_on_same_line():
    meta = _meta("Demo Pharmacy  Tel: (555) 010-2030")
    assert meta["pharmacy_name"].value == "Demo Pharmacy"
    assert meta["pharmacy_phone"].value == "(555) 010-2030"


def test_pharmacy_name_positional_fallback_above_phone_line():
    meta = _meta("Refills: 3\nSample Rx\nTel: (555) 010-4040")
    assert meta["pharmacy_name"].value == "Sample Rx"
    assert meta["pharmacy_name"].confidence == pytest.approx(0.6)


def test_positional_fallback_rejects_non_pharmacy_lines():
    # "TABLETS | Rx only" sits above the phone, but is clearly not a pharmacy name.
    meta = _meta("TABLETS | Rx only\nTel: (555) 010-2030")
    assert meta["pharmacy_name"].value is None


def test_phone_label_variants():
    assert _meta("Phone: 555-010-4040")["pharmacy_phone"].value == "555-010-4040"
    assert _meta("Call Ph: (555) 111-2222 today")["pharmacy_phone"].value == "(555) 111-2222"
    assert _meta("Tel:(555)010-2030")["pharmacy_phone"].value == "(555)010-2030"


def test_phone_generic_pattern_has_lower_confidence():
    field = _meta("Call (555) 999-8888 for questions")["pharmacy_phone"]
    assert field.value == "(555) 999-8888"
    assert field.confidence == pytest.approx(0.6)


def test_prescriber_labeled_and_dr_line():
    assert _meta("Prescriber: Dr. A. Demo")["prescriber"].value == "Dr. A. Demo"
    field = _meta("Dr. B. Sample")["prescriber"]
    assert field.value == "Dr. B. Sample"
    assert field.confidence == pytest.approx(0.7)


def test_prescriber_punctuation_spacing_is_normalized():
    # OCR on a crop can glue the punctuation: Prescriber:Dr.A.Demo
    field = _meta("Prescriber:Dr.A.Demo")["prescriber"]
    assert field.value == "Dr. A. Demo"
    assert field.confidence == pytest.approx(0.85)
    # Already-spaced input is unchanged.
    assert _meta("Prescriber: Dr. A. Demo")["prescriber"].value == "Dr. A. Demo"


def test_phone_format_is_unchanged_by_display_normalization():
    assert _meta("Phone: (555) 010-2030")["pharmacy_phone"].value == "(555) 010-2030"
    assert _meta("Phone: 555-010-2030")["pharmacy_phone"].value == "555-010-2030"


def test_display_normalization_preserves_decimal_points():
    from services.ocr.extract import _normalize_meta_spacing

    assert _normalize_meta_spacing("1.5 mg") == "1.5 mg"
    assert extract_fields("Take 1.5 tablets").dose_quantity == 1.5


def test_display_normalization_collapses_repeated_spaces():
    from services.ocr.extract import _normalize_meta_spacing

    assert _normalize_meta_spacing("Dr.  A.   Demo") == "Dr. A. Demo"


def test_display_normalization_does_not_touch_raw_text():
    raw = "Prescriber:Dr.A.Demo"
    extraction = extract_fields(raw)
    assert extraction.raw_text == raw
    assert extraction.label_meta["prescriber"].value == "Dr. A. Demo"


def test_display_normalization_st_john_pharmacy():
    assert _meta("St.John Pharmacy")["pharmacy_name"].value == "St. John Pharmacy"


# --------------------------------------------------------------------------- #
# Schedule derivation
# --------------------------------------------------------------------------- #


def test_schedule_once_daily():
    field = _meta("Take 1 tablet once daily")["schedule_times"]
    assert field.value == "08:00"
    assert field.confidence == pytest.approx(0.72)  # 0.9 base x 0.8
    assert field.source == "ocr"


def test_schedule_twice_daily():
    assert _meta("Take 1 tablet by mouth twice daily")["schedule_times"].value == "08:00, 20:00"


def test_schedule_three_times_daily():
    assert _meta("Take 1 tablet three times daily")["schedule_times"].value == "08:00, 14:00, 20:00"


def test_schedule_at_bedtime():
    assert _meta("Take 1 tablet at bedtime")["schedule_times"].value == "20:00"


def test_schedule_unknown_returns_none():
    for raw in ("Take 1 tablet once weekly", "Take 1 tablet every other day", "Take 1 tablet every 12 hours"):
        field = _meta(raw)["schedule_times"]
        assert field.value is None and field.source == "none", raw


def test_schedule_absent_without_frequency():
    field = extract_fields("METFORMIN HYDROCHLORIDE 500 mg TABLETS").label_meta["schedule_times"]
    assert field.value is None and field.confidence == 0.0 and field.source == "none"


# --------------------------------------------------------------------------- #
# Contract shape and no-invention guarantee
# --------------------------------------------------------------------------- #


def test_absent_fields_use_contract_none_shape():
    extraction = extract_fields("Metformin 500 mg Tablets")
    contract = extraction.label_meta_contract()
    assert tuple(contract) == LABEL_META_KEYS
    for key, field in contract.items():
        assert set(field) == {"value", "confidence", "source"}
        assert field["value"] is None
        assert field["confidence"] == 0.0
        assert field["source"] == "none", key


def test_label_meta_contract_validates_as_contract_model():
    meta = extract_fields(FULL_LABEL).label_meta_contract()
    model = LabelMeta.model_validate(meta)
    assert model.quantity_start.value == "30"
    assert model.refills_remaining.value == "2"
    assert model.pharmacy_name.value == "Demo Pharmacy"
    assert model.pharmacy_phone.value == "(555) 010-2030"
    assert model.prescriber.value == "Dr. A. Demo"
    assert model.schedule_times.value == "08:00, 20:00"


def test_every_meta_value_is_a_verbatim_substring_except_derived_schedule():
    extraction = extract_fields(FULL_LABEL)
    for key, field in extraction.label_meta.items():
        if key == "schedule_times":
            continue
        assert field.value is None or field.value in extraction.raw_text, key
    # schedule_times is derived (documented): times are not printed on the label.
    assert extraction.label_meta["schedule_times"].value == "08:00, 20:00"
    assert "08:00" not in extraction.raw_text
    assert extraction.label_meta["schedule_times"].confidence < 0.8


def test_full_label_extracts_all_six_fields():
    meta = extract_fields(FULL_LABEL).label_meta
    assert {key: field.value for key, field in meta.items()} == {
        "quantity_start": "30",
        "refills_remaining": "2",
        "pharmacy_name": "Demo Pharmacy",
        "pharmacy_phone": "(555) 010-2030",
        "prescriber": "Dr. A. Demo",
        "schedule_times": "08:00, 20:00",
    }


def test_degenerate_text_returns_absent_meta():
    extraction = extract_fields("日")
    assert all(field.value is None and field.source == "none" for field in extraction.label_meta.values())


def test_noise_resistance_around_meta_fields():
    raw = "Rx#12345  QTY 30  TAB\nRefills: 2\nDemo Pharmacy\nTel: (555) 010-2030\nPrescriber: Dr. A. Demo"
    meta = parse_label_meta(raw)
    assert meta["quantity_start"].value == "30"
    assert meta["refills_remaining"].value == "2"
    assert meta["pharmacy_name"].value == "Demo Pharmacy"
    assert meta["pharmacy_phone"].value == "(555) 010-2030"
    assert meta["prescriber"].value == "Dr. A. Demo"


# --------------------------------------------------------------------------- #
# Fusion keeps label_meta
# --------------------------------------------------------------------------- #


def test_fusion_fuses_label_meta_by_confidence():
    first = extract_fields("Demo Pharmacy\nTel: (555) 010-2030\nTake 1 tablet once daily")
    second = extract_fields("Pharmacy: Better Rx\nTake 1 tablet twice daily")
    result = fuse_extractions([first, second])
    assert result.extraction.label_meta["pharmacy_name"].value == "Better Rx"  # 0.8 > 0.75
    assert result.extraction.label_meta["schedule_times"].value == "08:00"  # only frame with a frequency


def test_single_frame_fusion_keeps_label_meta():
    frame = extract_fields(FULL_LABEL)
    result = fuse_extractions([frame])
    assert result.extraction.label_meta["quantity_start"].value == "30"
    assert result.extraction.label_meta["schedule_times"].value == "08:00, 20:00"


def test_real_sample_label_metformin_metadata():
    pytest.importorskip("rapidocr_onnxruntime")
    from services.ocr.engine import read_text

    result = read_text("samples/label_metformin.png")
    extraction = extract_fields(result.raw_text)
    meta = extraction.label_meta_contract()
    assert meta["quantity_start"]["value"] == "30"
    assert meta["refills_remaining"]["value"] == "2"
    assert meta["pharmacy_name"]["value"] == "Demo Pharmacy"
    assert meta["pharmacy_phone"]["value"] == "(555) 010-2030"
    assert meta["prescriber"]["value"].startswith("Dr.")
    assert meta["schedule_times"]["value"] == "08:00, 20:00"
