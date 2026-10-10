"""Label-localization tests."""
import numpy as np

from services.common.contract import BBox, Bottle
from services.vision.detector import HeuristicBottleDetector
from services.vision.label import FALLBACK_CONFIDENCE, locate_label
from services.vision.preprocess import decode_image
from services.vision.tests.helpers import bbox_inside, iou


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
