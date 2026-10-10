"""ONNX YOLO backend tests.

Pure pre/post-processing is unit-tested with synthetic tensors and a stubbed
session (no model file, no onnxruntime needed for most tests). One integration
test runs the real `models/yolo11n.onnx` when it is present and is skipped
otherwise; set `MEDCHECK_YOLO_MODEL_TEST` to point at a model elsewhere.
"""
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import numpy as np
import pytest

from services.common.contract import BBox
from services.vision.config import DEFAULT_YOLO_CONF, YOLO_CONF_ENV, VisionConfig, yolo_confidence_threshold
from services.vision.detector import (
    DetectorUnavailable,
    HeuristicBottleDetector,
    OnnxBottleDetector,
    decode_yolo_output,
    letterbox,
    unletterbox_box,
)
from services.vision.pipeline import analyze_frame

REPO_ROOT = Path(__file__).resolve().parents[3]
BOTTLE_CLASS = 39


class StubSession:
    """Minimal InferenceSession stand-in: records feeds, returns a fixed output."""

    def __init__(self, output: np.ndarray, input_name: str = "images") -> None:
        self.output = output
        self.input_name = input_name
        self.feeds = []

    def get_inputs(self):
        return [SimpleNamespace(name=self.input_name)]

    def run(self, output_names, feed):
        self.feeds.append(feed)
        return [self.output]


def _anchor(cx: float, cy: float, w: float, h: float, bottle_score: float, objectness: Optional[float] = None) -> dict:
    anchor = {"box": (cx, cy, w, h), "bottle_score": bottle_score}
    if objectness is not None:
        anchor["objectness"] = objectness
    return anchor


def _output(anchors, classes: int = 80, with_objectness: bool = False) -> np.ndarray:
    """Build a channels-first `(1, 4+classes[*+1], anchors)` YOLO-style output."""
    channels = 4 + (1 if with_objectness else 0) + classes
    out = np.zeros((1, channels, len(anchors)), dtype=np.float32)
    for index, anchor in enumerate(anchors):
        out[0, :4, index] = anchor["box"]
        base = 4
        if with_objectness:
            out[0, 4, index] = anchor["objectness"]
            base = 5
        out[0, base + BOTTLE_CLASS, index] = anchor["bottle_score"]
    return out


# --- letterbox ---


def test_letterbox_square_has_no_padding():
    rgb = np.full((320, 320, 3), 255, dtype=np.uint8)
    tensor, gain, pad = letterbox(rgb)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert gain == pytest.approx(2.0)
    assert pad == (0.0, 0.0)
    assert 0.0 <= tensor.min() and tensor.max() <= 1.0


def test_letterbox_landscape_pads_top_and_bottom():
    rgb = np.full((480, 640, 3), 200, dtype=np.uint8)
    tensor, gain, (pad_x, pad_y) = letterbox(rgb)
    assert gain == pytest.approx(1.0)
    assert (pad_x, pad_y) == (0.0, 80.0)
    assert tensor[0, 0, 5, 300] == pytest.approx(114 / 255.0, abs=1e-6)  # padding
    assert tensor[0, 0, 320, 300] == pytest.approx(200 / 255.0, abs=1e-6)  # image row


def test_letterbox_portrait_pads_left_and_right():
    rgb = np.full((640, 480, 3), 100, dtype=np.uint8)
    tensor, gain, (pad_x, pad_y) = letterbox(rgb)
    assert gain == pytest.approx(1.0)
    assert (pad_x, pad_y) == (80.0, 0.0)
    assert tensor[0, 0, 300, 5] == pytest.approx(114 / 255.0, abs=1e-6)
    assert tensor[0, 0, 300, 320] == pytest.approx(100 / 255.0, abs=1e-6)


def test_letterbox_rejects_empty_image():
    with pytest.raises(ValueError):
        letterbox(np.zeros((0, 10, 3), dtype=np.uint8))


# --- output decoding ---


def test_decode_filters_by_confidence():
    out = _output([_anchor(320, 320, 100, 100, 0.9), _anchor(100, 100, 50, 50, 0.2)])
    boxes = decode_yolo_output(out, conf_threshold=0.25)
    assert len(boxes) == 1
    assert boxes[0][4] == pytest.approx(0.9)


def test_decode_applies_nms_to_overlapping_boxes():
    out = _output(
        [
            _anchor(300, 300, 200, 200, 0.9),
            _anchor(305, 305, 200, 200, 0.8),  # ~0.9 IoU with the first -> suppressed
            _anchor(100, 100, 60, 60, 0.7),  # disjoint -> kept
        ]
    )
    boxes = decode_yolo_output(out, conf_threshold=0.25, iou_threshold=0.45)
    assert [round(box[4], 2) for box in boxes] == [0.9, 0.7]


def test_decode_supports_anchors_first_layout():
    channels_first = _output([_anchor(320, 320, 100, 100, 0.8)])
    anchors_first = np.transpose(channels_first, (0, 2, 1))
    boxes = decode_yolo_output(anchors_first, conf_threshold=0.25)
    assert len(boxes) == 1 and boxes[0][4] == pytest.approx(0.8)


def test_decode_multiplies_objectness_for_v5_layout():
    out = _output([_anchor(320, 320, 100, 100, 0.8, objectness=0.5)], with_objectness=True)
    boxes = decode_yolo_output(out, conf_threshold=0.25)
    assert boxes[0][4] == pytest.approx(0.4)


def test_decode_rejects_bad_shape():
    with pytest.raises(ValueError):
        decode_yolo_output(np.zeros((1, 10, 10), dtype=np.float32), conf_threshold=0.25)


def test_decode_converts_cxcywh_to_xyxy():
    out = _output([_anchor(300, 200, 100, 50, 0.9)])
    x1, y1, x2, y2, _ = decode_yolo_output(out, conf_threshold=0.25)[0]
    assert (x1, y1, x2, y2) == (250.0, 175.0, 350.0, 225.0)


# --- letterbox -> frame mapping ---


def test_unletterbox_maps_to_normalized_frame():
    bbox = unletterbox_box((220.0, 120.0, 420.0, 520.0), 1.0, (0.0, 80.0), 640, 480)
    assert bbox is not None
    assert (bbox.x, bbox.y, bbox.w, bbox.h) == (0.34375, 0.083333, 0.3125, 0.833333)


def test_unletterbox_clips_to_frame_and_rejects_degenerate():
    clipped = unletterbox_box((-10.0, -10.0, 50.0, 50.0), 1.0, (0.0, 0.0), 100, 100)
    assert clipped is not None and clipped.x == 0.0 and clipped.y == 0.0
    assert unletterbox_box((-100.0, -100.0, -50.0, -50.0), 1.0, (0.0, 0.0), 100, 100) is None


# --- detector with injected session ---


def test_detector_with_stub_session_maps_best_box():
    out = _output([_anchor(320, 320, 200, 400, 0.9), _anchor(100, 100, 50, 50, 0.6)])
    session = StubSession(out)
    detector = OnnxBottleDetector("stub.onnx", session=session)
    assert detector.name == "yolo"

    rgb = np.full((480, 640, 3), 200, dtype=np.uint8)
    detection = detector.detect(rgb)
    assert detection is not None
    assert detection.confidence == pytest.approx(0.9)
    assert detection.bbox.x == pytest.approx(0.34375)
    assert detection.bbox.w == pytest.approx(0.3125)
    assert session.feeds[0]["images"].shape == (1, 3, 640, 640)


def test_detector_returns_none_when_below_confidence():
    out = _output([_anchor(320, 320, 200, 400, 0.1)])
    detector = OnnxBottleDetector("stub.onnx", session=StubSession(out))
    assert detector.detect(np.zeros((100, 100, 3), dtype=np.uint8)) is None


def test_detector_reads_confidence_from_env(monkeypatch):
    monkeypatch.setenv(YOLO_CONF_ENV, "0.95")
    out = _output([_anchor(320, 320, 200, 400, 0.9)])
    detector = OnnxBottleDetector("stub.onnx", session=StubSession(out))
    assert detector.detect(np.full((640, 640, 3), 128, dtype=np.uint8)) is None


def test_confidence_threshold_env_parsing(monkeypatch):
    monkeypatch.setenv(YOLO_CONF_ENV, "0.5")
    assert yolo_confidence_threshold() == 0.5
    for invalid in ("not-a-number", "0", "-1", "5"):
        monkeypatch.setenv(YOLO_CONF_ENV, invalid)
        assert yolo_confidence_threshold() == DEFAULT_YOLO_CONF
    monkeypatch.delenv(YOLO_CONF_ENV)
    assert yolo_confidence_threshold() == DEFAULT_YOLO_CONF


def test_onnx_detector_raises_without_model_file():
    with pytest.raises(DetectorUnavailable):
        OnnxBottleDetector("/nonexistent/weights.onnx")


# --- factory selection / fallback ---


def test_factory_selects_onnx_backend_for_onnx_path(monkeypatch, tmp_path):
    model = tmp_path / "weights.onnx"
    model.write_bytes(b"stub")
    stub = StubSession(_output([_anchor(320, 320, 100, 100, 0.9)]))
    monkeypatch.setattr("services.vision.detector._get_onnx_session", lambda path: stub)

    from services.vision.detector import get_detector

    detector = get_detector(VisionConfig(detector="auto", model_path=str(model)))
    assert isinstance(detector, OnnxBottleDetector)
    assert detector.detect(np.full((640, 640, 3), 128, dtype=np.uint8)) is not None


def test_factory_falls_back_to_heuristic_for_missing_onnx():
    from services.vision.detector import get_detector

    detector = get_detector(VisionConfig(detector="auto", model_path="/nonexistent/weights.onnx"))
    assert isinstance(detector, HeuristicBottleDetector)


def test_corrupt_onnx_model_degrades_to_heuristic(tmp_path, load_bytes):
    bad_model = tmp_path / "corrupt.onnx"
    bad_model.write_bytes(b"this is not an onnx graph")
    result = analyze_frame(load_bytes("sharp_bottle.png"), {"model_path": str(bad_model)})
    assert result.detector == "heuristic"
    assert result.bottle.detected  # heuristic still works on the synthetic bottle


# --- real model (integration; skipped when the gitignored model is absent) ---


def _real_model_path() -> Optional[Path]:
    for candidate in (os.environ.get("MEDCHECK_YOLO_MODEL_TEST"), str(REPO_ROOT / "models" / "yolo11n.onnx")):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


REAL_MODEL_PATH = _real_model_path()


@pytest.mark.skipif(REAL_MODEL_PATH is None, reason="models/yolo11n.onnx not present (gitignored)")
def test_real_onnx_model_pipeline(load_bytes):
    assert REAL_MODEL_PATH is not None
    result = analyze_frame(load_bytes("sharp_bottle.png"), {"model_path": str(REAL_MODEL_PATH)})
    assert result.detector == "yolo"
    assert 0.0 <= result.bottle.confidence <= 1.0
    if result.bottle.detected:
        bbox = result.bottle.bbox
        assert bbox is not None
        assert 0.0 <= bbox.x <= 1.0 and 0.0 <= bbox.y <= 1.0
        assert 0.0 < bbox.w <= 1.0 and 0.0 < bbox.h <= 1.0
        assert bbox.x + bbox.w <= 1.0 + 1e-6
        assert bbox.y + bbox.h <= 1.0 + 1e-6


@pytest.mark.skipif(REAL_MODEL_PATH is None, reason="models/yolo11n.onnx not present (gitignored)")
def test_real_onnx_model_detector_direct(load_bytes):
    from services.vision.preprocess import decode_image

    detector = OnnxBottleDetector(str(REAL_MODEL_PATH))
    detection = detector.detect(decode_image(load_bytes("sharp_bottle.png")))
    if detection is not None:
        assert isinstance(detection.bbox, BBox)
        assert 0.0 < detection.confidence <= 1.0


@pytest.mark.skipif(REAL_MODEL_PATH is None, reason="models/yolo11n.onnx not present (gitignored)")
def test_real_onnx_session_is_cached_per_process():
    first = OnnxBottleDetector(str(REAL_MODEL_PATH))
    second = OnnxBottleDetector(str(REAL_MODEL_PATH))
    assert first._session is second._session
