"""Structured per-dose quantity tests (contract v1.1 `instructions.dose`)."""

from __future__ import annotations

import pytest

from services.ocr.extract import extract_fields, parse_dose_quantity


def _dose(raw: str):
    extraction = extract_fields(raw)
    return extraction.dose_quantity, extraction.dose_unit, extraction.dose_confidence, extraction.dose_source


# --------------------------------------------------------------------------- #
# Numeric and decimal quantities
# --------------------------------------------------------------------------- #


def test_numeric_dose_quantity():
    extraction = extract_fields("Take 1 tablet by mouth twice daily")
    assert extraction.dose_quantity == 1.0
    assert extraction.dose_unit == "tablet"
    assert extraction.dose_confidence == pytest.approx(0.9)
    assert extraction.dose_source == "ocr"


def test_caps_uppercase_and_plural_normalized():
    assert _dose("Take 2 CAPSULES")[:2] == (2.0, "capsule")
    assert _dose("Take 2 caps")[:2] == (2.0, "capsule")


def test_decimal_quantity():
    assert _dose("Take 1.5 tablets")[:2] == (1.5, "tablet")


def test_volume_units():
    assert _dose("Take 5 ml by mouth")[:2] == (5.0, "ml")
    assert _dose("Take 2 tsp at bedtime")[:2] == (2.0, "tsp")


def test_dose_uses_dose_segment_not_strength():
    extraction = extract_fields("Metformin 500 mg Tablets\nTake 1 tablet by mouth once daily")
    assert extraction.strength.value == 500 and extraction.strength.unit == "mg"
    assert extraction.dose_quantity == 1.0
    assert extraction.dose_unit == "tablet"


# --------------------------------------------------------------------------- #
# Word and fraction quantities
# --------------------------------------------------------------------------- #


def test_half_tablet_word():
    assert _dose("Take half tablet")[:2] == (0.5, "tablet")
    assert _dose("Take half a tablet")[:2] == (0.5, "tablet")


def test_quarter_tablet_word():
    assert _dose("Take quarter tablet")[:2] == (0.25, "tablet")


def test_word_quantity_one_tablet():
    quantity, unit, confidence, source = _dose("Take one tablet by mouth")
    assert (quantity, unit) == (1.0, "tablet")
    assert confidence == pytest.approx(0.75)
    assert source == "ocr"


def test_word_quantity_one_and_a_half():
    assert _dose("Take one and a half tablets")[:2] == (1.5, "tablet")


def test_fraction_half_tablet():
    quantity, unit, confidence, _ = _dose("Take 1/2 tablet")
    assert (quantity, unit) == (0.5, "tablet")
    assert confidence == pytest.approx(0.85)


def test_fraction_one_and_a_half_tablets():
    assert _dose("Take 1 1/2 tablets")[:2] == (1.5, "tablet")


def test_unicode_fraction_half():
    assert _dose("Take \u00bd tablet")[:2] == (0.5, "tablet")


# --------------------------------------------------------------------------- #
# Ranges, package counts, absent doses, warnings
# --------------------------------------------------------------------------- #


def test_range_with_to_is_not_guessed():
    assert _dose("Take 1 to 2 tablets every 4 to 6 hours as needed") == (None, None, 0.0, "none")


def test_range_with_dash_is_not_guessed():
    assert _dose("Take 1-2 tablets every 4 to 6 hours") == (None, None, 0.0, "none")


def test_package_count_is_not_a_dose():
    assert _dose("90 tablets") == (None, None, 0.0, "none")
    assert _dose("30 capsules per bottle") == (None, None, 0.0, "none")
    assert _dose("Metformin 500 mg Tablets") == (None, None, 0.0, "none")


def test_warning_line_is_not_a_dose():
    assert _dose("Do not exceed 3 tablets in 24 hours") == (None, None, 0.0, "none")


def test_no_dose_stated_returns_none_shape():
    extraction = extract_fields("METFORMIN HYDROCHLORIDE 500 mg TABLETS")
    assert extraction.dose_contract() == {
        "quantity": None,
        "unit": None,
        "confidence": 0.0,
        "source": "none",
    }


def test_zero_quantity_is_rejected():
    assert _dose("Take 0 tablets") == (None, None, 0.0, "none")


# --------------------------------------------------------------------------- #
# Contract shape and regression
# --------------------------------------------------------------------------- #


def test_dose_contract_shape_matches_v1_1():
    extraction = extract_fields("Take 1 tablet by mouth twice daily")
    assert extraction.dose_contract() == {
        "quantity": 1.0,
        "unit": "tablet",
        "confidence": 0.9,
        "source": "ocr",
    }
    assert set(extraction.dose_contract()) == {"quantity", "unit", "confidence", "source"}
    assert extraction.instructions_contract()["dose"] == extraction.dose_contract()


def test_dose_confidence_and_quantity_are_schema_valid():
    for raw in ("Take 1 tablet", "Take half tablet", "Take 1/2 tablet", "90 tablets", "Take 1-2 tablets"):
        extraction = extract_fields(raw)
        assert 0.0 <= extraction.dose_confidence <= 1.0
        assert extraction.dose_quantity is None or extraction.dose_quantity > 0


def test_first_dose_segment_wins():
    extraction = extract_fields("Take 1 tablet in the morning. Take 2 tablets at night.")
    assert extraction.dose_quantity == 1.0
    assert extraction.dose_unit == "tablet"


def test_strength_extraction_untouched_by_dose_parsing():
    extraction = extract_fields("Metform1n 5O0mg Tablets\nTake 2 tablets by mouth once daily")
    assert extraction.name.value == "Metformin"
    assert (extraction.strength.value, extraction.strength.unit) == (500.0, "mg")
    assert "2" not in (extraction.strength.raw or "")
    assert (extraction.dose_quantity, extraction.dose_unit) == (2.0, "tablet")


def test_parse_dose_quantity_standalone():
    assert parse_dose_quantity("Take 2 tablets by mouth") == (2.0, "tablet", 0.9, "ocr")
    assert parse_dose_quantity("") == (None, None, 0.0, "none")
