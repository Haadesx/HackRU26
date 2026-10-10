"""Field extraction tests: noise, casing, ambiguity, multi-line labels."""

from __future__ import annotations

from services.ocr.extract import extract_fields, find_strengths


def test_strength_not_confused_with_quantity_per_dose():
    raw = "Lisinopril 10 mg Tablets\nTAKE 2 TABLETS BY MOUTH ONCE DAILY"
    ext = extract_fields(raw)
    assert ext.strength.value == 10
    assert ext.strength.unit == "mg"
    assert "2" not in (ext.strength.raw or "")
    dose_items = [item for item in ext.instructions if item.kind == "dose"]
    assert any("2 TABLETS" in item.text.upper() for item in dose_items)


def test_quantity_only_yields_no_strength():
    raw = "Take 1-2 tablets every 4 to 6 hours as needed"
    ext = extract_fields(raw)
    assert ext.strength.value is None
    assert ext.strength.source == "none"
    assert any(item.kind == "dose" for item in ext.instructions)
    assert any(item.kind == "frequency" for item in ext.instructions)


def test_ocr_noise_metform1n_and_5o0mg():
    ext = extract_fields("Metform1n 5O0mg Tablets")
    assert ext.name.value == "Metformin"
    assert ext.name.raw == "Metform1n"  # verbatim source preserved
    assert ext.name.source == "ocr"
    assert ext.strength.value == 500
    assert ext.strength.unit == "mg"
    assert ext.strength.raw == "5O0mg"
    assert ext.form.value == "tablet"


def test_ocr_noise_l1sinopril_uppercase():
    ext = extract_fields("L1SINOPRIL 10 MG TABLETS")
    assert ext.name.value == "Lisinopril"
    assert ext.strength.value == 10
    assert ext.strength.unit == "mg"
    assert ext.form.value == "tablet"


def test_casing_lowercase_and_mixed():
    ext = extract_fields("at0rvastatin 2O mg tablets")
    assert ext.name.value == "Atorvastatin"
    assert ext.strength.value == 20
    assert ext.strength.unit == "mg"
    assert ext.form.value == "tablet"


def test_multiline_label_fields():
    raw = "METFORMIN HYDROCHLORIDE\n500 MG\nTABLETS"
    ext = extract_fields(raw)
    assert ext.name.value == "Metformin"
    assert ext.strength.value == 500
    assert ext.strength.unit == "mg"
    assert ext.form.value == "tablet"
    assert ext.raw_text == raw  # verbatim


def test_strength_before_name():
    ext = extract_fields("500 mg METFORMIN TABLETS")
    assert ext.name.value == "Metformin"
    assert ext.strength.value == 500
    assert ext.form.value == "tablet"


def test_unit_without_space():
    ext = extract_fields("LEVOTHYROXINE 100MCG TABLETS")
    assert ext.strength.value == 100
    assert ext.strength.unit == "mcg"


def test_unknown_name_uses_verbatim_fallback_not_fabrication():
    raw = "ZzzQuil 25 mg Tablets"
    ext = extract_fields(raw)
    assert ext.name.value == "ZzzQuil"
    assert ext.name.value in raw  # never invented
    assert ext.name.confidence <= 0.5
    assert ext.name.normalized is False


def test_no_name_returns_absent_field():
    ext = extract_fields("500 mg TABLETS")
    assert ext.name.value is None
    assert ext.name.source == "none"
    assert ext.strength.value == 500


def test_find_strengths_excludes_dose_counts():
    matches = find_strengths("Take 2 tablets by mouth; strength 500 mg")
    assert [(m.value, m.unit) for m in matches] == [(500, "mg")]


def test_contract_fragments_are_schema_shaped():
    ext = extract_fields("Metformin 500 mg Tablets")
    medication = ext.medication_contract()
    assert set(medication) == {"name", "strength", "form", "manufacturer"}
    assert medication["name"] == {"value": "Metformin", "confidence": ext.name.confidence, "source": "ocr"}
    assert set(medication["strength"]) == {"value", "unit", "confidence", "source"}
    assert medication["strength"]["source"] == "ocr"

    instructions = ext.instructions_contract()
    assert instructions["raw_text"] == ext.raw_text
    for item in instructions["parsed"]:
        assert set(item) == {"kind", "text"}
        assert item["text"] in ext.raw_text  # verbatim substring


def test_hint_biases_but_never_fabricates():
    raw = "Metformin 500 mg Tablets"
    with_hint = extract_fields(raw, hints={"name": "Metformin"})
    assert with_hint.name.value == "Metformin"
    without_hint_in_text = extract_fields("500 mg Tablets", hints={"name": "Metformin"})
    assert without_hint_in_text.name.value is None  # hint is not a source of value
