"""End-to-end `analyze_frame` acceptance tests."""
import io

import cv2
import numpy as np
import pytest
from PIL import Image

from services.common.contract import BBox, Bottle, FrameQuality, Label
from services.vision.pipeline import analyze_frame, derive_guidance
from services.vision.preprocess import ImageDecodeError
from services.vision.tests.helpers import flat_label_frame, noise_frame, png_bytes


def test_sharp_frame_passes_end_to_end(load_bytes):
    result = analyze_frame(load_bytes("sharp_bottle.png"))
    assert result.quality.acceptable
    assert result.bottle.detected and result.bottle.bbox is not None
    assert result.bottle.confidence > 0.5
    assert result.label.detected and result.label.bbox is not None
    assert result.guidance
    assert result.detector == "heuristic"
    assert result.timing.total_ms >= 0
    assert set(result.timing.stages) == {"preprocess", "quality", "detect", "label"}
    assert result.frame.width == 480 and result.frame.height == 640


def test_analyze_frame_accepts_jpeg(load_bytes):
    with Image.open(io.BytesIO(load_bytes("sharp_bottle.png"))) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=95)
    result = analyze_frame(buffer.getvalue())
    assert result.quality.acceptable
    assert result.bottle.detected


def test_blurry_frame_fails_with_guidance(load_bytes):
    result = analyze_frame(load_bytes("blurry_bottle.png"))
    assert not result.quality.acceptable
    assert result.quality.blur is not None and result.quality.blur.is_blurry
    assert any("steady" in text.lower() for text in result.guidance)


def test_dark_frame_fails_with_guidance(load_bytes):
    result = analyze_frame(load_bytes("dark_bottle.png"))
    assert not result.quality.acceptable
    assert result.quality.exposure is not None and result.quality.exposure.too_dark
    assert any("light" in text.lower() or "brighter" in text.lower() for text in result.guidance)


def test_glare_frame_fails_with_guidance(load_bytes):
    result = analyze_frame(load_bytes("glare_bottle.png"))
    assert not result.quality.acceptable
    assert result.quality.glare is not None and result.quality.glare.has_glare
    assert any("glare" in text.lower() for text in result.guidance)


def test_scene_without_bottle_gives_framing_guidance(load_bytes):
    result = analyze_frame(load_bytes("no_bottle.png"))
    assert not result.bottle.detected
    assert result.bottle.bbox is None
    assert any("center the bottle" in text.lower() for text in result.guidance)


def test_flat_label_close_up_still_yields_a_label_region():
    result = analyze_frame(png_bytes(flat_label_frame()))
    assert not result.bottle.detected
    assert result.label.detected and result.label.bbox is not None
    # The label is already found; do not tell the user to center a bottle.
    assert all("center the bottle" not in text.lower() for text in result.guidance)


def test_blurry_flat_label_close_up_fails_quality():
    blurred = cv2.GaussianBlur(flat_label_frame(), (0, 0), 4.0)
    result = analyze_frame(png_bytes(blurred))
    assert not result.quality.acceptable
    assert any("steady" in text.lower() for text in result.guidance)


@pytest.mark.parametrize("sigma", [25, 40, 60])
def test_pure_noise_frame_reports_no_medication(sigma):
    # Regression: noise must not be mistaken for a label, or the API returns
    # "uncertain" instead of "no_medication_found".
    result = analyze_frame(png_bytes(noise_frame(sigma)))
    assert not result.bottle.detected
    assert not result.label.detected
    assert result.label.bbox is None


def test_invalid_bytes_raise(load_bytes):
    with pytest.raises(ImageDecodeError):
        analyze_frame(b"not an image at all")


def test_hints_override_config(load_bytes):
    result = analyze_frame(load_bytes("sharp_bottle.png"), {"max_side": 320})
    assert max(result.frame.width, result.frame.height) == 320
    assert result.frame.original_width == 480 and result.frame.original_height == 640
    assert "resize" in result.frame.applied


def test_unknown_hints_are_ignored(load_bytes):
    result = analyze_frame(load_bytes("sharp_bottle.png"), {"definitely_not_a_setting": 42})
    assert result.bottle.detected


def test_bottle_and_label_boxes_are_normalized(load_bytes):
    result = analyze_frame(load_bytes("sharp_bottle.png"))
    for bbox in (result.bottle.bbox, result.label.bbox):
        assert bbox is not None
        assert 0.0 <= bbox.x <= 1.0 and 0.0 <= bbox.y <= 1.0
        assert 0.0 < bbox.w <= 1.0 and 0.0 < bbox.h <= 1.0
        assert bbox.x + bbox.w <= 1.0 + 1e-6
        assert bbox.y + bbox.h <= 1.0 + 1e-6


def _good_quality() -> FrameQuality:
    return FrameQuality(acceptable=True, score=1.0)


def test_derive_guidance_for_small_label():
    quality = _good_quality()
    bottle = Bottle(detected=True, confidence=0.9, bbox=BBox(x=0.2, y=0.2, w=0.6, h=0.6))
    label = Label(detected=True, confidence=0.9, bbox=BBox(x=0.3, y=0.3, w=0.1, h=0.1))
    guidance = derive_guidance(quality, bottle, label)
    assert any("closer" in text.lower() for text in guidance)


def test_derive_guidance_all_good():
    quality = _good_quality()
    bottle = Bottle(detected=True, confidence=0.9, bbox=BBox(x=0.2, y=0.2, w=0.6, h=0.6))
    label = Label(detected=True, confidence=0.9, bbox=BBox(x=0.3, y=0.3, w=0.3, h=0.3))
    assert derive_guidance(quality, bottle, label) == ["Looks good - hold steady."]


def test_derive_guidance_centers_missing_bottle():
    guidance = derive_guidance(_good_quality(), Bottle(detected=False, confidence=0.0), Label(detected=False, confidence=0.0))
    assert any("center the bottle" in text.lower() for text in guidance)
