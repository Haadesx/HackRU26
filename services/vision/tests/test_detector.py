"""Bottle-detector tests: heuristic behavior, factory fallback, YOLO adapter."""
import numpy as np
import pytest

from services.common.contract import BBox
from services.vision.config import VisionConfig
from services.vision.detector import (
    DetectorUnavailable,
    HeuristicBottleDetector,
    NullDetector,
    YoloBottleDetector,
    get_detector,
)
from services.vision.preprocess import decode_image
from services.vision.tests.helpers import iou


def test_heuristic_detects_synthetic_bottle(load_bytes, labels):
    detection = HeuristicBottleDetector().detect(decode_image(load_bytes("sharp_bottle.png")))
    assert detection is not None
    assert detection.confidence > 0.5
    ground_truth = BBox(**labels["sharp_bottle.png"]["bottle_bbox"])
    assert iou(detection.bbox, ground_truth) >= 0.6


def test_heuristic_rejects_scene_without_bottle(load_bytes):
    assert HeuristicBottleDetector().detect(decode_image(load_bytes("no_bottle.png"))) is None


def test_factory_falls_back_to_heuristic_when_weights_missing():
    detector = get_detector(VisionConfig(detector="auto", model_path="/nonexistent/weights.pt"))
    assert isinstance(detector, HeuristicBottleDetector)


def test_factory_explicit_yolo_without_weights_falls_back():
    detector = get_detector(VisionConfig(detector="yolo"))
    assert isinstance(detector, HeuristicBottleDetector)


def test_factory_caches_and_selects_none():
    assert isinstance(get_detector(VisionConfig(detector="none")), NullDetector)
    assert get_detector(VisionConfig(detector="none")).detect(np.zeros((64, 64, 3), np.uint8)) is None


def test_yolo_adapter_raises_without_weights():
    with pytest.raises(DetectorUnavailable):
        YoloBottleDetector("/nonexistent/weights.pt")


def test_heuristic_detects_blurry_bottle_too(load_bytes):
    # Blur reduces confidence but a large foreground object is still located.
    detection = HeuristicBottleDetector().detect(decode_image(load_bytes("blurry_bottle.png")))
    assert detection is not None and detection.confidence > 0.3
