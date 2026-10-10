"""Real-photo OCR quality: small-crop upscaling + degenerate-text sanity."""

from __future__ import annotations

import numpy as np
import pytest

from services.ocr.engine import MIN_CROP_LONG_SIDE, _prepare_crop, read_text
from services.ocr.extract import extract_fields, parse_instructions
from services.ocr.types import BBox, OcrLine, OcrResult, has_readable_content

SAMPLE = "samples/long_label_full.png"


# --------------------------------------------------------------------------- #
# Readable-content rule
# --------------------------------------------------------------------------- #


def test_has_readable_content_rules():
    assert has_readable_content("Take 1 tablet")
    assert has_readable_content("METFORMIN 500 mg")
    assert not has_readable_content("日")
    assert not has_readable_content("||")
    assert not has_readable_content("...")
    assert not has_readable_content("")
    assert not has_readable_content("   ")
    assert not has_readable_content("5 mg")  # fewer than 3 alphabetic characters


def test_ocr_result_confidence_zero_for_degenerate_glyph_and_text_stays_verbatim():
    result = OcrResult(raw_text="日", lines=[OcrLine(text="日", confidence=0.9)])
    assert result.confidence == 0.0
    assert result.readable is False
    assert result.raw_text == "日"  # never rewritten


def test_ocr_result_confidence_normal_for_readable_text():
    result = OcrResult(
        raw_text="Metformin 500 mg",
        lines=[OcrLine(text="Metformin 500 mg", confidence=0.8)],
    )
    assert result.confidence == pytest.approx(0.8)
    assert result.readable is True


# --------------------------------------------------------------------------- #
# Degenerate extraction
# --------------------------------------------------------------------------- #


def test_extract_fields_degenerate_glyph_returns_empty():
    extraction = extract_fields("日")
    assert extraction.name.value is None and extraction.name.source == "none"
    assert extraction.strength.value is None and extraction.strength.source == "none"
    assert extraction.form.value is None
    assert extraction.instructions == []  # no ('other', '日') junk item
    assert extraction.dose_quantity is None and extraction.dose_source == "none"


def test_extract_fields_degenerate_pipes_and_punctuation_returns_empty():
    for raw in ("||", "|", "...", "·--·", "日\n日"):
        extraction = extract_fields(raw)
        assert extraction.name.value is None, raw
        assert extraction.instructions == [], raw
        assert extraction.raw_text == raw  # verbatim preserved


def test_parse_instructions_degenerate_returns_empty_list():
    assert parse_instructions("日") == []
    assert parse_instructions("||") == []
    assert parse_instructions("...") == []


def test_readable_text_with_stray_glyph_still_parses():
    extraction = extract_fields("Take 1 tablet by mouth twice daily\n日")
    assert extraction.dose_quantity == 1.0
    assert extraction.dose_unit == "tablet"
    assert any(item.kind == "dose" for item in extraction.instructions)


# --------------------------------------------------------------------------- #
# Small-crop upscaling
# --------------------------------------------------------------------------- #


def test_prepare_crop_returns_large_crop_unchanged():
    crop = np.zeros((1200, 1800, 3), dtype=np.uint8)
    prepared, scale_x, scale_y = _prepare_crop(crop)
    assert prepared is crop
    assert (scale_x, scale_y) == (1.0, 1.0)


def test_prepare_crop_upscales_small_crops_to_target_long_side():
    crop = np.full((300, 450, 3), 255, dtype=np.uint8)
    prepared, scale_x, scale_y = _prepare_crop(crop)
    assert max(prepared.shape[:2]) == MIN_CROP_LONG_SIDE
    assert prepared.shape[1] == round(450 * MIN_CROP_LONG_SIDE / 450)
    assert scale_x == pytest.approx(MIN_CROP_LONG_SIDE / 450)
    assert scale_y == pytest.approx(scale_x, rel=0.01)


def test_prepare_crop_caps_upscale_factor():
    crop = np.full((10, 12, 3), 255, dtype=np.uint8)
    _, scale_x, _ = _prepare_crop(crop)
    assert scale_x <= 4.0 + 1e-9  # MAX_CROP_UPSCALE


def test_read_text_small_bbox_crop_recovers_text():
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image

    image = Image.open(SAMPLE).convert("RGB")
    small = image.resize((image.width // 4, image.height // 4), Image.LANCZOS)
    arr = np.asarray(small)
    assert max(arr.shape[:2]) == 450

    result = read_text(arr, bbox=BBox(0.0, 0.0, 1.0, 1.0), channel_order="rgb")
    assert result.readable is True
    assert result.confidence > 0.5
    assert "HYDROCHLOROTHIAZIDE" in result.raw_text.upper().replace(" ", "")

    extraction = extract_fields(result.raw_text)
    assert extraction.name.value == "Hydrochlorothiazide"
    assert (extraction.strength.value, extraction.strength.unit) == (25.0, "mg")


def test_read_text_small_crop_boxes_map_back_to_full_frame():
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image

    image = Image.open(SAMPLE).convert("RGB")
    small = image.resize((image.width // 4, image.height // 4), Image.LANCZOS)
    arr = np.asarray(small)
    result = read_text(arr, bbox=BBox(0.1, 0.05, 0.8, 0.6), channel_order="rgb")
    assert result.image_size == (arr.shape[1], arr.shape[0])
    assert result.lines
    for line in result.lines:
        assert line.bbox is not None
        assert 0.0 <= line.bbox.x <= 1.0
        assert 0.0 <= line.bbox.y <= 1.0
        assert line.bbox.x2 <= 1.0 + 1e-9
        assert line.bbox.y2 <= 1.0 + 1e-9
