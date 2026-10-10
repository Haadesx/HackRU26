"""Label-localization tests."""
import cv2
import numpy as np
import pytest

from services.common.contract import BBox, Bottle
from services.vision.detector import HeuristicBottleDetector
from services.vision.label import FALLBACK_CONFIDENCE, locate_label
from services.vision.preprocess import decode_image
from services.vision.tests.helpers import bbox_inside, flat_label_frame, iou, noise_frame


def test_label_localized_on_detected_bottle(load_bytes, labels):
    rgb = decode_image(load_bytes("sharp_bottle.png"))
    detection = HeuristicBottleDetector().detect(rgb)
    assert detection is not None
    bottle = Bottle(detected=True, confidence=detection.confidence, bbox=detection.bbox)

    label = locate_label(rgb, bottle)
    assert label.detected and label.bbox is not None
    assert label.confidence > 0.5
    ground_truth = BBox(**labels["sharp_bottle.png"]["label_bbox"])
    assert iou(label.bbox, ground_truth) >= 0.4
    assert bbox_inside(label.bbox, bottle.bbox)


def test_no_bottle_means_no_label(load_bytes):
    rgb = decode_image(load_bytes("no_bottle.png"))
    label = locate_label(rgb, Bottle(detected=False, confidence=0.0))
    assert not label.detected
    assert label.bbox is None


def test_fallback_band_when_no_bright_region():
    rgb = np.full((200, 200, 3), 12, dtype=np.uint8)
    bottle = Bottle(detected=True, confidence=0.5, bbox=BBox(x=0.1, y=0.1, w=0.6, h=0.7))
    label = locate_label(rgb, bottle)
    assert label.detected and label.bbox is not None
    assert label.confidence == FALLBACK_CONFIDENCE
    assert bbox_inside(label.bbox, bottle.bbox)


# --- frame-level fallback (flat label close-ups, no bottle) ---


def test_frame_level_label_found_without_bottle():
    label = locate_label(flat_label_frame(), Bottle(detected=False, confidence=0.0))
    assert label.detected and label.bbox is not None
    assert 0.4 <= label.confidence <= 0.6  # capped: no bottle anchor
    assert label.bbox.w > 0.5 and label.bbox.h > 0.5


def test_frame_level_label_found_in_dim_but_readable_frame():
    # Adaptive brightness: a dim page with intact black text still yields a crop.
    label = locate_label(flat_label_frame(page=100), Bottle(detected=False, confidence=0.0))
    assert label.detected and label.bbox is not None


def test_frame_level_label_requires_text_evidence():
    frame = np.full((240, 360, 3), 190, dtype=np.uint8)
    cv2.rectangle(frame, (8, 8), (351, 231), (20, 20, 20), 3)  # bright page, no text
    assert not locate_label(frame, Bottle(detected=False, confidence=0.0)).detected


def test_frame_level_label_rejects_featureless_frame():
    blank = np.full((220, 320, 3), 190, dtype=np.uint8)
    assert not locate_label(blank, Bottle(detected=False, confidence=0.0)).detected


@pytest.mark.parametrize("sigma", [25, 40, 60])
def test_frame_level_label_rejects_pure_noise(sigma):
    # Raw dark/edge gates pass on dense noise; the blur-scale structure gate must reject it.
    assert not locate_label(noise_frame(sigma), Bottle(detected=False, confidence=0.0)).detected
