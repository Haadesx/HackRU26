"""Registered-candidate matcher tests (>= 15 cases)."""

from __future__ import annotations

import json

import pytest

from services.common.contract import Candidate
from services.ocr.extract import extract_fields
from services.ocr.matcher import DEFAULT_THRESHOLD, match_candidates


def _fields(name: str | None, value: float | None = None, unit: str | None = None) -> dict:
    return {
        "name": name,
        "strength": ({"value": value, "unit": unit} if value is not None or unit is not None else None),
    }


def _cand(name: str, value: float | None = None, unit: str | None = None) -> dict:
    return {
        "name": name,
        "strength": ({"value": value, "unit": unit} if value is not None or unit is not None else None),
    }


# --------------------------------------------------------------------------- #
# Exact and shape
# --------------------------------------------------------------------------- #


def test_exact_match_scores_one_and_keeps_registry_name():
    results = match_candidates(_fields("Metformin", 500, "mg"), [_cand("Metformin", 500, "mg")])
    assert len(results) == 1
    assert isinstance(results[0], Candidate)
    assert results[0].name == "Metformin"
    assert results[0].score == pytest.approx(1.0)
    assert results[0].source == "registry"
    assert results[0].strength.value == 500
    assert results[0].strength.unit == "mg"


def test_output_is_contract_shaped_and_json_serializable():
    results = match_candidates(_fields("Lisinopril", 10, "mg"), [_cand("Lisinopril", 10, "mg")])
    payload = results[0].model_dump()
    assert set(payload) == {"name", "strength", "score", "source"}
    assert set(payload["strength"]) == {"value", "unit"}
    assert payload["source"] == "registry"
    assert json.loads(json.dumps(payload))["name"] == "Lisinopril"


def test_accepts_extraction_object_from_ocr_pipeline():
    extraction = extract_fields("Metform1n 5O0mg Tablets")
    results = match_candidates(extraction, [_cand("Metformin", 500, "mg")])
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0)


def test_accepts_string_strength_and_normalizes_output_unit():
    results = match_candidates(_fields("Metformin", 500, "MG"), [{"name": "Metformin", "strength": "500 mg"}])
    assert len(results) == 1
    assert results[0].strength.unit == "mg"
    assert results[0].score == pytest.approx(1.0)


def test_accepts_canonical_flat_field_dict_shape():
    """API-style fields dict {name, strength_value, strength_unit, form, ...}."""
    fields = {
        "name": "Metformin",
        "strength_value": 500,
        "strength_unit": "mg",
        "form": "tablet",
        "manufacturer": None,
        "instructions": {"raw_text": "Take 1 tablet", "parsed": []},
    }
    results = match_candidates(fields, [_cand("Metformin", 500, "mg")])
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0)
    # "strength" key wins when explicitly present; flat keys are the fallback.
    explicit = match_candidates(
        {"name": "Metformin", "strength": {"value": 250, "unit": "mg"}, "strength_value": 500, "strength_unit": "mg"},
        [_cand("Metformin", 500, "mg")],
    )
    assert explicit == []


# --------------------------------------------------------------------------- #
# OCR noise
# --------------------------------------------------------------------------- #


def test_ocr_noise_metform1n_and_5o0mg():
    results = match_candidates(
        _fields("Metform1n", 500, "mg"),
        [_cand("Metformin", 500, "mg"), _cand("Metoprolol", 500, "mg")],
    )
    assert [candidate.name for candidate in results] == ["Metformin"]
    assert results[0].score == pytest.approx(1.0)


def test_ocr_noise_l1sinopril():
    results = match_candidates(_fields("L1SINOPRIL", 10, "mg"), [_cand("Lisinopril", 10, "mg")])
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0)


def test_case_and_spacing_are_ignored():
    results = match_candidates(_fields("met formin", 500, "mg"), [_cand("METFORMIN", 500, "mg")])
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0)


def test_small_substitution_is_kept_but_ranked_lower():
    results = match_candidates(
        _fields("Metfarmin", 500, "mg"),
        [_cand("Metformin", 500, "mg")],
        threshold=0.5,
    )
    assert len(results) == 1
    assert 0.85 < results[0].score < 1.0


# --------------------------------------------------------------------------- #
# Strength semantics
# --------------------------------------------------------------------------- #


def test_strength_mismatch_is_dropped_at_default_threshold():
    results = match_candidates(_fields("Metformin", 1000, "mg"), [_cand("Metformin", 500, "mg")])
    assert results == []


def test_strength_mismatch_can_be_kept_with_lower_threshold():
    results = match_candidates(
        _fields("Metformin", 1000, "mg"), [_cand("Metformin", 500, "mg")], threshold=0.6
    )
    assert len(results) == 1
    assert results[0].score == pytest.approx(0.7)


def test_unit_conversion_mg_and_mcg():
    results = match_candidates(_fields("Levothyroxine", 0.5, "mg"), [_cand("Levothyroxine", 500, "mcg")])
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0)


def test_unit_conversion_g_and_mg():
    results = match_candidates(_fields("Amoxicillin", 1, "g"), [_cand("Amoxicillin", 1000, "mg")])
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0)


def test_unit_family_mismatch_is_dropped():
    results = match_candidates(_fields("Metformin", 500, "mg"), [_cand("Metformin", 500, "ml")])
    assert results == []


def test_percent_strength_matches():
    results = match_candidates(_fields("Solution", 5, "%"), [_cand("Solution", 5, "%")])
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0)


def test_missing_strength_on_either_side_matches_by_name():
    no_candidate_strength = match_candidates(_fields("Metformin", 500, "mg"), [_cand("Metformin")])
    no_query_strength = match_candidates(_fields("Metformin"), [_cand("Metformin", 500, "mg")])
    assert len(no_candidate_strength) == 1 and no_candidate_strength[0].score == pytest.approx(0.9)
    assert len(no_query_strength) == 1 and no_query_strength[0].score == pytest.approx(0.9)


# --------------------------------------------------------------------------- #
# Ordering, thresholds, empty / malformed inputs
# --------------------------------------------------------------------------- #


def test_ordering_best_first_and_stable_on_ties():
    candidates = [
        _cand("Metformin", 500, "mg"),
        _cand("Metformine", 500, "mg"),
        _cand("Metform1n", 500, "mg"),
    ]
    results = match_candidates(_fields("Metformin", 500, "mg"), candidates)
    assert [candidate.name for candidate in results] == ["Metformin", "Metform1n", "Metformine"]
    assert results[0].score >= results[1].score >= results[2].score


def test_threshold_is_inclusive():
    results = match_candidates(_fields("Metformin"), [_cand("Metformin", 500, "mg")], threshold=0.9)
    assert len(results) == 1
    assert results[0].score == pytest.approx(0.9)


def test_threshold_validation():
    with pytest.raises(ValueError):
        match_candidates(_fields("Metformin"), [], threshold=-0.1)
    with pytest.raises(ValueError):
        match_candidates(_fields("Metformin"), [], threshold=1.1)


def test_no_candidates_returns_empty():
    assert match_candidates(_fields("Metformin", 500, "mg"), []) == []


def test_empty_or_nameless_input_returns_empty():
    candidates = [_cand("Metformin", 500, "mg")]
    assert match_candidates(None, candidates) == []
    assert match_candidates({}, candidates) == []
    assert match_candidates(_fields(None, 500, "mg"), candidates) == []
    assert match_candidates(_fields("Metformin", 500, "mg"), None) == []


def test_malformed_candidates_are_skipped_without_raising():
    candidates = [None, 42, {"strength": {"value": 500, "unit": "mg"}}, {"name": None}, {"name": ""}]
    assert match_candidates(_fields("Metformin", 500, "mg"), candidates) == []


def test_unknown_candidate_names_are_never_invented():
    results = match_candidates(
        _fields("Metformin", 500, "mg"),
        [_cand("Ibuprofen", 500, "mg"), _cand("Lisinopril", 10, "mg")],
    )
    assert results == []


def test_result_names_are_always_subset_of_input_names():
    candidates = [_cand("Metformin", 500, "mg"), _cand("Metoprolol", 50, "mg"), _cand("Aspirin", 500, "mg")]
    results = match_candidates(_fields("Metform1n", 500, "mg"), candidates, threshold=0.5)
    assert results
    assert {candidate.name for candidate in results} <= {candidate["name"] for candidate in candidates}


def test_scores_are_within_unit_interval_for_a_matrix_of_inputs():
    names = ["Metformin", "Metform1n", "Metfarmin", "Metoprolol", "L1SINOPRIL"]
    units = [("500", "mg"), ("0.5", "g"), ("250", "mg"), ("10", "ml")]
    for name in names:
        for value, unit in units:
            results = match_candidates(
                _fields(name, float(value), unit),
                [_cand("Metformin", 500, "mg"), _cand("Lisinopril", 10, "mg")],
                threshold=0.0,
            )
            for candidate in results:
                assert 0.0 <= candidate.score <= 1.0
                assert candidate.source == "registry"


def test_accepts_direct_extraction_style_field_objects():
    from services.ocr.types import FieldString, FieldStrength

    fields = {
        "name": FieldString(value="Lisinopril", confidence=0.95, source="ocr"),
        "strength": FieldStrength(value=10, unit="mg", confidence=0.9, source="ocr"),
    }
    results = match_candidates(fields, [_cand("Lisinopril", 10, "mg")])
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0)


def test_default_threshold_value_is_frozen_interface():
    assert DEFAULT_THRESHOLD == 0.75
