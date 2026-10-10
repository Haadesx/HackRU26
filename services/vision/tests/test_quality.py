"""Frame-quality tests on the synthetic fixtures."""
import numpy as np
import pytest

from services.vision.preprocess import decode_image
from services.vision.quality import evaluate_quality
from services.vision.tests.helpers import flat_label_frame


def _quality(load_bytes, name: str):
    return evaluate_quality(decode_image(load_bytes(name)))


def test_sharp_frame_is_acceptable(load_bytes):
    quality = _quality(load_bytes, "sharp_bottle.png")
    assert quality.acceptable
    assert quality.score >= 0.6
    assert quality.blur is not None and not quality.blur.is_blurry
    assert quality.exposure is not None
    assert not quality.exposure.too_dark and not quality.exposure.too_bright
    assert quality.glare is not None and not quality.glare.has_glare
    assert quality.guidance == []


def test_blurry_frame_fails_with_guidance(load_bytes):
    sharp = _quality(load_bytes, "sharp_bottle.png")
    blurry = _quality(load_bytes, "blurry_bottle.png")
    assert not blurry.acceptable
    assert blurry.blur is not None and blurry.blur.is_blurry
    assert blurry.blur.score < sharp.blur.score
    assert any("steady" in text.lower() for text in blurry.guidance)


def test_dark_frame_fails_with_light_guidance(load_bytes):
    quality = _quality(load_bytes, "dark_bottle.png")
    assert not quality.acceptable
    assert quality.exposure is not None and quality.exposure.too_dark
    # Contrast normalization must keep a dark-but-sharp frame out of the blur bucket.
    assert quality.blur is not None and not quality.blur.is_blurry
    assert any("light" in text.lower() or "brighter" in text.lower() for text in quality.guidance)


def test_bright_frame_fails_with_light_guidance(load_bytes):
    quality = _quality(load_bytes, "bright_bottle.png")
    assert not quality.acceptable
    assert quality.exposure is not None and quality.exposure.too_bright
    assert any("light" in text.lower() for text in quality.guidance)


def test_glare_frame_fails_with_glare_guidance(load_bytes):
    quality = _quality(load_bytes, "glare_bottle.png")
    assert not quality.acceptable
    assert quality.glare is not None and quality.glare.has_glare
    assert quality.glare.score < 1.0
    assert any("glare" in text.lower() for text in quality.guidance)


def test_dominant_white_surface_is_not_reported_as_glare():
    # A mostly-saturated frame is overexposure, not a specular highlight.
    frame = np.full((120, 120, 3), 255, dtype=np.uint8)
    quality = evaluate_quality(frame)
    assert quality.glare is not None and not quality.glare.has_glare
    assert quality.exposure is not None and quality.exposure.too_bright


def test_bright_label_with_intact_text_is_readable_not_overexposed():
    # White paper + black text spans the full range: bright, but nothing is lost.
    quality = evaluate_quality(flat_label_frame(page=252))
    assert quality.exposure is not None and not quality.exposure.too_bright
    assert quality.acceptable
    assert not any("light" in text.lower() for text in quality.guidance)


@pytest.mark.parametrize(
    "name",
    ["sharp_bottle.png", "blurry_bottle.png", "dark_bottle.png", "bright_bottle.png", "glare_bottle.png", "no_bottle.png"],
)
def test_all_scores_stay_in_unit_range(load_bytes, name):
    quality = _quality(load_bytes, name)
    scores = [
        quality.score,
        quality.blur.score if quality.blur else 1.0,
        quality.exposure.score if quality.exposure else 1.0,
        quality.glare.score if quality.glare else 1.0,
    ]
    assert all(0.0 <= score <= 1.0 for score in scores)
