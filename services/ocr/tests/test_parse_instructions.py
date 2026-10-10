"""Dosage-instruction parser tests."""

from __future__ import annotations

from services.ocr.extract import parse_instructions


def _kinds(raw: str) -> list[str]:
    return [item.kind for item in parse_instructions(raw)]


def test_combined_sentence_splits_into_ordered_items():
    items = parse_instructions("Take 1 tablet by mouth twice daily for 7 days")
    assert [item.kind for item in items] == ["dose", "route", "frequency", "duration"]
    assert items[0].text == "Take 1 tablet"
    assert items[1].text == "by mouth"
    assert items[2].text == "twice daily"
    assert items[3].text == "for 7 days"


def test_quantity_range_and_as_needed():
    items = parse_instructions("Take 1-2 tablets every 4 to 6 hours as needed")
    kinds = [item.kind for item in items]
    assert "dose" in kinds
    dose = next(item for item in items if item.kind == "dose")
    assert dose.text == "Take 1-2 tablets"
    frequency = [item.text for item in items if item.kind == "frequency"]
    assert any("every 4 to 6 hours" in text for text in frequency)


def test_warning_lines_are_warning_kind():
    items = parse_instructions("Do not take with alcohol")
    assert len(items) == 1
    assert items[0].kind == "warning"
    assert items[0].text == "Do not take with alcohol"


def test_package_count_is_not_a_dose():
    items = parse_instructions("30 TABLETS")
    assert all(item.kind != "dose" for item in items)


def test_merged_ocr_words_still_parse():
    items = parse_instructions("TAKE1TABLETBYMOUTHTWICEDAILY")
    kinds = [item.kind for item in items]
    assert "dose" in kinds
    assert "frequency" in kinds
    dose = next(item for item in items if item.kind == "dose")
    assert dose.text == "TAKE1TABLET"


def test_multi_line_label_instruction_kinds():
    raw = (
        "LISINOPRIL 10 mg\n"
        "Take 1 tablet by mouth once daily\n"
        "Keep out of reach of children"
    )
    items = parse_instructions(raw)
    kinds = [item.kind for item in items]
    assert "dose" in kinds
    assert "route" in kinds
    assert "frequency" in kinds
    assert "warning" in kinds
    for item in items:
        assert item.text in raw  # verbatim substrings only


def test_every_item_text_is_verbatim():
    raw = "Take 2 capsules by mouth every 12 hours for 10 days. Do not exceed 3 capsules in 24 hours."
    items = parse_instructions(raw)
    assert items
    for item in items:
        assert item.text in raw
