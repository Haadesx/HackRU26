"""Multi-frame label capture: `label_clipped` + cut-off guidance (contract v1.2)."""
from pathlib import Path

import pytest

from services.common.contract import BBox, Bottle, FrameQuality, Label
from services.vision import analyze_frame
from services.vision.pipeline import LABEL_CLIP_MARGIN, derive_guidance, is_label_clipped
from services.vision.tests.helpers import flat_label_frame, png_bytes

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLES = REPO_ROOT / "samples"
CLIP_GUIDANCE = "Label is cut off — rotate the bottle or step back, then capture again"


def _sample_bytes(name: str) -> bytes:
    path = SAMPLES / name
    if not path.is_file():
        pytest.skip(f"sample {name} not present")
    return path.read_bytes()


def _detected_label(**bbox_kwargs) -> Label:
    return Label(detected=True, confidence=0.8, bbox=BBox(**bbox_kwargs))


def test_long_label_left_is_clipped():
    result = analyze_frame(_sample_bytes("long_label_left.png"))
    assert result.label.detected and result.label_clipped
    assert result.guidance.count(CLIP_GUIDANCE) == 1


def test_long_label_middle_is_clipped():
    result = analyze_frame(_sample_bytes("long_label_middle.png"))
    assert result.label.detected and result.label_clipped
    assert result.guidance.count(CLIP_GUIDANCE) == 1


def test_long_label_right_is_clipped():
    result = analyze_frame(_sample_bytes("long_label_right.png"))
    assert result.label.detected and result.label_clipped
    assert result.guidance.count(CLIP_GUIDANCE) == 1


def test_centered_flat_label_is_not_clipped():
    result = analyze_frame(png_bytes(flat_label_frame()))
    assert result.label.detected
    assert result.label_clipped is False
    assert CLIP_GUIDANCE not in result.guidance


@pytest.mark.parametrize(
    "bbox",
    [
        {"x": 0.01, "y": 0.3, "w": 0.5, "h": 0.4},  # left edge within margin
        {"x": 0.3, "y": 0.005, "w": 0.5, "h": 0.4},  # top edge within margin
        {"x": 0.3, "y": 0.3, "w": 0.69, "h": 0.4},  # right edge within margin (x+w = 0.99)
        {"x": 0.3, "y": 0.3, "w": 0.5, "h": 0.69},  # bottom edge within margin (y+h = 0.99)
    ],
)
def test_near_edge_within_margin_is_clipped(bbox):
    assert is_label_clipped(_detected_label(**bbox)) is True


def test_just_outside_margin_is_not_clipped():
    bbox = BBox(x=LABEL_CLIP_MARGIN + 0.001, y=LABEL_CLIP_MARGIN + 0.001, w=0.5, h=0.5)
    assert bbox.x + bbox.w < 1.0 - LABEL_CLIP_MARGIN
    assert bbox.y + bbox.h < 1.0 - LABEL_CLIP_MARGIN
    assert is_label_clipped(_detected_label(**bbox.model_dump())) is False


def test_missing_bbox_is_not_clipped():
    assert is_label_clipped(Label(detected=True, confidence=0.9, bbox=None)) is False
    assert is_label_clipped(Label(detected=False, confidence=0.0, bbox=None)) is False
    assert is_label_clipped(Label(detected=False, confidence=0.0, bbox=BBox(x=0.0, y=0.0, w=1.0, h=1.0))) is False


def test_clip_guidance_is_deduplicated():
    quality = FrameQuality(acceptable=True, score=1.0, guidance=["Label is cut off at the edge; step back."])
    guidance = derive_guidance(
        quality,
        Bottle(detected=False, confidence=0.0),
        Label(detected=False, confidence=0.0),
        label_clipped=True,
    )
    assert sum("cut off" in text.lower() for text in guidance) == 1


def test_clip_guidance_comes_after_quality_guidance():
    quality = FrameQuality(acceptable=False, score=0.2, guidance=["Hold the bottle steady and let the camera focus."])
    guidance = derive_guidance(
        quality,
        Bottle(detected=False, confidence=0.0),
        Label(detected=True, confidence=0.6, bbox=BBox(x=0.0, y=0.1, w=0.9, h=0.8)),
        label_clipped=True,
    )
    assert guidance[0] == "Hold the bottle steady and let the camera focus."
    assert guidance[-1] == CLIP_GUIDANCE


def test_clip_guidance_absent_when_not_clipped():
    quality = FrameQuality(acceptable=True, score=1.0)
    guidance = derive_guidance(
        quality,
        Bottle(detected=False, confidence=0.0),
        Label(detected=False, confidence=0.0),
        label_clipped=False,
    )
    assert CLIP_GUIDANCE not in guidance
