"""Bottle detection adapters.

- `OnnxBottleDetector` runs a YOLO ONNX export with ONNX Runtime on CPU (selected
  when `model_path` ends in `.onnx` or `MEDCHECK_YOLO_MODEL` does). One cached
  `InferenceSession` per process, lazy import, single intra-op thread so the OCR
  stage keeps CPU headroom. Any model/config error degrades to the heuristic.
- `YoloBottleDetector` wraps ultralytics YOLO weights (COCO `bottle` class, or a
  single-class custom model). Optional: neither weights nor the `ultralytics`
  package are bundled in git, and nothing is imported unless a `model_path` is
  configured. Uses CUDA when `torch.cuda.is_available()`, else CPU.
- `HeuristicBottleDetector` is the deterministic CPU fallback: foreground is
  segmented by color distance from the border background; if that fails, Canny
  contours are tried. Designed for a centered bottle on a dev Mac.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import cv2
import numpy as np

from services.common.contract import BBox
from services.vision.config import VisionConfig, yolo_confidence_threshold
from services.vision.preprocess import to_gray

logger = logging.getLogger(__name__)

MAX_DETECTION_SIDE = 640  # heuristic works on a downscaled copy for speed/scale stability

# ONNX backend constants.
ONNX_INPUT_SIZE = 640
ONNX_PAD_VALUE = 114
ONNX_NMS_IOU = 0.45
COCO_BOTTLE_ID = 39


class DetectorUnavailable(RuntimeError):
    """The optional detector backend (ultralytics / weights / CUDA) is unavailable."""


@dataclass(frozen=True)
class Detection:
    bbox: BBox
    confidence: float
    class_name: str = "bottle"


@runtime_checkable
class BottleDetector(Protocol):
    name: str

    def detect(self, rgb: np.ndarray) -> Optional[Detection]:  # pragma: no cover - protocol
        ...


def _normalized_bbox(x: int, y: int, w: int, h: int, img_w: int, img_h: int, padding: float = 0.0) -> BBox:
    x0 = max(0.0, x / img_w - padding)
    y0 = max(0.0, y / img_h - padding)
    x1 = min(1.0, (x + w) / img_w + padding)
    y1 = min(1.0, (y + h) / img_h + padding)
    return BBox(x=round(x0, 6), y=round(y0, 6), w=round(max(0.0, x1 - x0), 6), h=round(max(0.0, y1 - y0), 6))


def _clip01(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _iou(a: BBox, b: BBox) -> float:
    x0 = max(a.x, b.x)
    y0 = max(a.y, b.y)
    x1 = min(a.x + a.w, b.x + b.w)
    y1 = min(a.y + a.h, b.y + b.h)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a.w * a.h + b.w * b.h - intersection
    return intersection / union if union > 0 else 0.0


def _union_bbox(a: BBox, b: BBox) -> BBox:
    x0 = min(a.x, b.x)
    y0 = min(a.y, b.y)
    x1 = max(a.x + a.w, b.x + b.w)
    y1 = max(a.y + a.h, b.y + b.h)
    return BBox(x=round(x0, 6), y=round(y0, 6), w=round(x1 - x0, 6), h=round(y1 - y0, 6))


class NullDetector:
    """Detector that reports nothing; used with `detector="none"`."""

    name = "none"

    def detect(self, rgb: np.ndarray) -> Optional[Detection]:
        return None


class HeuristicBottleDetector:
    """CPU color/edge heuristic; no model file, no GPU, deterministic."""

    name = "heuristic"

    def __init__(self, max_side: int = MAX_DETECTION_SIDE) -> None:
        self.max_side = int(max_side)

    # -- helpers ---------------------------------------------------------
    def _downscale(self, rgb: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        longest = max(h, w)
        if longest <= self.max_side:
            return rgb
        scale = self.max_side / float(longest)
        return cv2.resize(rgb, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA)

    def _foreground_component(self, rgb: np.ndarray) -> Optional[Tuple[BBox, float]]:
        h, w = rgb.shape[:2]
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        band = max(2, int(round(0.04 * min(h, w))))
        border = np.concatenate(
            [
                lab[:band].reshape(-1, 3),
                lab[-band:].reshape(-1, 3),
                lab[:, :band].reshape(-1, 3),
                lab[:, -band:].reshape(-1, 3),
            ],
            axis=0,
        )
        background = np.median(border, axis=0)
        border_spread = float(np.median(np.linalg.norm(border - background, axis=1))) + 1e-6
        distance = np.linalg.norm(lab - background, axis=2)
        threshold = max(18.0, border_spread * 2.5)
        mask = (distance > threshold).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if count <= 1:
            return None
        idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, bw, bh, area = (int(v) for v in stats[idx])
        area_fraction = area / float(h * w)
        fill = area / float(max(1, bw * bh))
        aspect = bh / float(max(1, bw))
        if not (0.04 <= area_fraction <= 0.92) or fill < 0.35 or aspect > 6.0:
            return None
        confidence = _clip01(0.35 + 0.35 * min(area_fraction / 0.35, 1.0) + 0.25 * fill)
        confidence = min(confidence, 0.95)
        return _normalized_bbox(x, y, bw, bh, w, h, padding=0.01), round(confidence, 4)

    def _edge_contour(self, rgb: np.ndarray) -> Optional[Tuple[BBox, float]]:
        h, w = rgb.shape[:2]
        gray = to_gray(rgb)
        edges = cv2.Canny(gray, 50, 150)
        edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
        contours, _hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            area_fraction = (bw * bh) / float(h * w)
            contour_area = cv2.contourArea(contour)
            fill = contour_area / float(max(1, bw * bh))
            if not (0.05 <= area_fraction <= 0.90) or fill < 0.25:
                continue
            if bh < 0.9 * bw:  # bottles stand taller than they are wide
                continue
            if best is None or bw * bh > best[0]:
                best = (bw * bh, x, y, bw, bh)
        if best is None:
            return None
        _area, x, y, bw, bh = best
        return _normalized_bbox(x, y, bw, bh, w, h, padding=0.01), 0.45

    def detect(self, rgb: np.ndarray) -> Optional[Detection]:
        small = self._downscale(rgb)
        candidates = [
            candidate
            for candidate in (self._foreground_component(small), self._edge_contour(small))
            if candidate is not None
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            bbox, confidence = candidates[0]
        else:
            (bbox_a, confidence_a), (bbox_b, confidence_b) = candidates
            if _iou(bbox_a, bbox_b) >= 0.3:
                # Consistent candidates: the union is the better bottle extent.
                bbox = _union_bbox(bbox_a, bbox_b)
                confidence = min(max(confidence_a, confidence_b) + 0.05, 0.95)
            elif confidence_a >= confidence_b:
                bbox, confidence = bbox_a, confidence_a
            else:
                bbox, confidence = bbox_b, confidence_b
        return Detection(bbox=bbox, confidence=round(_clip01(confidence), 4), class_name="bottle")


class YoloBottleDetector:
    """Adapter around ultralytics YOLO. Import is lazy; failure is explicit."""

    name = "yolo"
    _COCO_BOTTLE_ID = 39
    _BOTTLE_NAMES = {"bottle"}

    def __init__(self, model_path: Optional[str], device: str = "auto", confidence_threshold: Optional[float] = None) -> None:
        if not model_path or not os.path.isfile(model_path):
            raise DetectorUnavailable(f"YOLO weights not found: {model_path!r} (set hints['model_path'])")
        try:
            from ultralytics import YOLO  # type: ignore import-not-found
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            raise DetectorUnavailable(f"ultralytics is not importable: {exc}") from exc

        self._device = self._resolve_device(device)
        self._confidence_threshold = float(
            confidence_threshold if confidence_threshold is not None else yolo_confidence_threshold()
        )
        try:
            self._model = YOLO(model_path)
        except Exception as exc:  # pragma: no cover - depends on weights
            raise DetectorUnavailable(f"could not load YOLO weights {model_path!r}: {exc}") from exc
        logger.info("YoloBottleDetector ready (device=%s, weights=%s)", self._device, model_path)

    @staticmethod
    def _resolve_device(requested: str) -> str:
        if requested == "cpu":
            return "cpu"
        try:
            import torch  # type: ignore import-not-found
        except Exception as exc:
            if requested == "cuda":
                raise DetectorUnavailable("device='cuda' requested but torch is not installed") from exc
            return "cpu"
        if requested == "cuda" and not torch.cuda.is_available():
            raise DetectorUnavailable("device='cuda' requested but CUDA is not available")
        return "cuda" if torch.cuda.is_available() else "cpu"

    def detect(self, rgb: np.ndarray) -> Optional[Detection]:
        h, w = rgb.shape[:2]
        results = self._model.predict(source=rgb, device=self._device, conf=self._confidence_threshold, verbose=False)
        if not results:
            return None
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return None
        names: Dict[int, str] = dict(getattr(result, "names", {}) or {})
        single_class = len(names) == 1

        best = None
        for box in boxes:
            cls_id = int(box.cls.item())
            name = str(names.get(cls_id, cls_id)).lower()
            if not single_class and name not in self._BOTTLE_NAMES and cls_id != self._COCO_BOTTLE_ID:
                continue
            confidence = float(box.conf.item())
            if best is None or confidence > best[0]:
                x0, y0, x1, y1 = (float(v) for v in box.xyxy[0].tolist())
                best = (confidence, x0, y0, x1, y1)
        if best is None:
            return None
        confidence, x0, y0, x1, y1 = best
        bbox = _normalized_bbox(int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)), w, h, padding=0.0)
        return Detection(bbox=bbox, confidence=round(_clip01(confidence), 4), class_name="bottle")


_DETECTOR_CACHE: Dict[Tuple[str, Optional[str], str], BottleDetector] = {}


# ---------------------------------------------------------------------------
# ONNX Runtime backend
# ---------------------------------------------------------------------------

_ONNX_SESSION_CACHE: Dict[str, Any] = {}


def _get_onnx_session(model_path: str) -> Any:
    """One cached CPU `InferenceSession` per process; intra-op threads capped at 1."""
    key = os.path.abspath(model_path)
    session = _ONNX_SESSION_CACHE.get(key)
    if session is not None:
        return session
    try:
        import onnxruntime as ort  # type: ignore import-not-found
    except Exception as exc:  # pragma: no cover - optional dependency
        raise DetectorUnavailable(f"onnxruntime is not importable: {exc}") from exc
    try:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1  # leave CPU for the OCR stage
        session = ort.InferenceSession(key, sess_options=options, providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise DetectorUnavailable(f"could not load ONNX model {model_path!r}: {exc}") from exc
    _ONNX_SESSION_CACHE[key] = session
    logger.info("ONNX InferenceSession ready (weights=%s)", model_path)
    return session


def letterbox(
    rgb: np.ndarray,
    size: int = ONNX_INPUT_SIZE,
    pad_value: int = ONNX_PAD_VALUE,
) -> Tuple[np.ndarray, float, Tuple[float, float]]:
    """Letterbox an RGB frame to a square canvas.

    Returns `(NCHW float32 tensor in 0..1, gain, (pad_x, pad_y))`; the gain and
    pad are needed to map predicted boxes back to frame coordinates.
    """
    h, w = rgb.shape[:2]
    if h <= 0 or w <= 0:
        raise ValueError("cannot letterbox an empty image")
    gain = min(size / float(w), size / float(h))
    new_w = max(1, int(round(w * gain)))
    new_h = max(1, int(round(h * gain)))
    resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), pad_value, dtype=np.uint8)
    pad_x = (size - new_w) / 2.0
    pad_y = (size - new_h) / 2.0
    left, top = int(round(pad_x)), int(round(pad_y))
    canvas[top : top + new_h, left : left + new_w] = resized
    tensor = np.ascontiguousarray(np.transpose(canvas.astype(np.float32) / 255.0, (2, 0, 1))[None, ...])
    return tensor, gain, (pad_x, pad_y)


def _nms_indices(boxes_xyxy: np.ndarray, scores: np.ndarray, iou_threshold: float) -> np.ndarray:
    if boxes_xyxy.shape[0] == 0:
        return np.empty(0, dtype=int)
    boxes_xywh = np.column_stack(
        (boxes_xyxy[:, 0], boxes_xyxy[:, 1], boxes_xyxy[:, 2] - boxes_xyxy[:, 0], boxes_xyxy[:, 3] - boxes_xyxy[:, 1])
    )
    raw = cv2.dnn.NMSBoxes(boxes_xywh.tolist(), scores.tolist(), 0.0, float(iou_threshold))
    if raw is None or len(raw) == 0:
        return np.empty(0, dtype=int)
    return np.array(raw).reshape(-1).astype(int)


def decode_yolo_output(
    output: np.ndarray,
    conf_threshold: float,
    iou_threshold: float = ONNX_NMS_IOU,
    class_id: int = COCO_BOTTLE_ID,
) -> List[Tuple[float, float, float, float, float]]:
    """Decode raw YOLO output into scored `(x1, y1, x2, y2, score)` boxes.

    Supports the v8/v11 `(4 + classes)` layout and the v5 `(4 + 1 + classes)`
    objectness layout, in either channel-first or anchors-first orientation.
    Boxes are in input (letterboxed) coordinates, filtered by class and
    confidence, then NMS'd.
    """
    pred = np.asarray(output, dtype=np.float32)
    while pred.ndim > 2 and pred.shape[0] == 1:
        pred = pred[0]
    if pred.ndim != 2:
        raise ValueError(f"unexpected YOLO output shape {getattr(output, 'shape', None)}")
    rows, cols = pred.shape
    if rows in (84, 85):
        pred = pred.T  # channels-first: (channels, anchors)
        channels = rows
    elif cols in (84, 85):
        channels = cols  # anchors-first: (anchors, channels)
    else:
        raise ValueError(f"unexpected YOLO channel layout {pred.shape}")
    if channels == 85:
        objectness = pred[:, 4]
        class_scores = pred[:, 5:]
    elif channels == 84:
        objectness = None
        class_scores = pred[:, 4:]
    else:
        raise ValueError(f"unexpected YOLO channel count {channels}")
    if not 0 <= class_id < class_scores.shape[1]:
        raise ValueError(f"class id {class_id} outside 0..{class_scores.shape[1] - 1}")

    scores = class_scores[:, class_id].astype(np.float32).copy()
    if objectness is not None:
        scores *= objectness
    keep = scores >= float(conf_threshold)
    if not np.any(keep):
        return []

    boxes = pred[keep, :4]
    scores = scores[keep]
    xyxy = np.column_stack(
        (
            boxes[:, 0] - boxes[:, 2] / 2.0,
            boxes[:, 1] - boxes[:, 3] / 2.0,
            boxes[:, 0] + boxes[:, 2] / 2.0,
            boxes[:, 1] + boxes[:, 3] / 2.0,
        )
    )
    selected = _nms_indices(xyxy, scores, iou_threshold)
    selected = selected[np.argsort(-scores[selected])]
    return [(float(xyxy[i, 0]), float(xyxy[i, 1]), float(xyxy[i, 2]), float(xyxy[i, 3]), float(scores[i])) for i in selected]


def unletterbox_box(
    xyxy: Tuple[float, float, float, float],
    gain: float,
    pad: Tuple[float, float],
    frame_w: int,
    frame_h: int,
) -> Optional[BBox]:
    """Map an input-space xyxy back to a normalized frame bbox (None if degenerate)."""
    x1 = (xyxy[0] - pad[0]) / gain
    y1 = (xyxy[1] - pad[1]) / gain
    x2 = (xyxy[2] - pad[0]) / gain
    y2 = (xyxy[3] - pad[1]) / gain
    x1 = min(max(x1, 0.0), float(frame_w))
    y1 = min(max(y1, 0.0), float(frame_h))
    x2 = min(max(x2, 0.0), float(frame_w))
    y2 = min(max(y2, 0.0), float(frame_h))
    if x2 - x1 <= 0.0 or y2 - y1 <= 0.0:
        return None
    return BBox(
        x=round(x1 / frame_w, 6),
        y=round(y1 / frame_h, 6),
        w=round((x2 - x1) / frame_w, 6),
        h=round((y2 - y1) / frame_h, 6),
    )


class OnnxBottleDetector:
    """YOLO ONNX Runtime backend: CPU-only, lazy import, single cached session."""

    name = "yolo"

    def __init__(
        self,
        model_path: Optional[str],
        *,
        confidence_threshold: Optional[float] = None,
        iou_threshold: float = ONNX_NMS_IOU,
        session: Any = None,
    ) -> None:
        if session is None:
            if not model_path or not os.path.isfile(model_path):
                raise DetectorUnavailable(
                    f"ONNX weights not found: {model_path!r} (set MEDCHECK_YOLO_MODEL or hints['model_path'])"
                )
            self._model_path = model_path
            session = _get_onnx_session(model_path)
        else:
            # Test seam: an injected session skips file checks and the onnxruntime import.
            self._model_path = model_path or "<injected-session>"
        try:
            self._input_name = session.get_inputs()[0].name
        except Exception as exc:
            raise DetectorUnavailable(f"invalid ONNX session: {exc}") from exc
        self._session = session
        self._confidence_threshold = float(
            confidence_threshold if confidence_threshold is not None else yolo_confidence_threshold()
        )
        self._iou_threshold = float(iou_threshold)

    @property
    def model_path(self) -> str:
        return self._model_path

    def detect(self, rgb: np.ndarray) -> Optional[Detection]:
        tensor, gain, pad = letterbox(rgb)
        outputs = self._session.run(None, {self._input_name: tensor})
        decoded = decode_yolo_output(outputs[0], self._confidence_threshold, self._iou_threshold)
        if not decoded:
            return None
        x1, y1, x2, y2, score = decoded[0]  # sorted by score, best first
        frame_h, frame_w = rgb.shape[:2]
        bbox = unletterbox_box((x1, y1, x2, y2), gain, pad, frame_w, frame_h)
        if bbox is None:
            return None
        return Detection(bbox=bbox, confidence=round(_clip01(score), 4), class_name="bottle")


def get_detector(config: VisionConfig) -> BottleDetector:
    """Build (and cache) the detector for a config, falling back to CPU heuristic."""
    if config.detector == "none":
        return NullDetector()

    key = (config.detector, config.model_path, config.device)
    cached = _DETECTOR_CACHE.get(key)
    if cached is not None:
        return cached

    if config.detector in ("auto", "yolo") and config.model_path:
        try:
            if config.model_path.lower().endswith(".onnx"):
                detector: BottleDetector = OnnxBottleDetector(config.model_path)
            else:
                detector = YoloBottleDetector(config.model_path, device=config.device)
            _DETECTOR_CACHE[key] = detector
            return detector
        except DetectorUnavailable as exc:
            logger.info("YOLO backend unavailable (%s); using CPU heuristic fallback", exc)

    detector = HeuristicBottleDetector()
    _DETECTOR_CACHE[key] = detector
    return detector
