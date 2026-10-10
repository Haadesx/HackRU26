"""Bottle detection adapters.

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
from typing import Dict, Optional, Protocol, Tuple, runtime_checkable

import cv2
import numpy as np

from services.common.contract import BBox
from services.vision.config import VisionConfig
from services.vision.preprocess import to_gray

logger = logging.getLogger(__name__)

MAX_DETECTION_SIDE = 640  # heuristic works on a downscaled copy for speed/scale stability


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

    def __init__(self, model_path: Optional[str], device: str = "auto", confidence_threshold: float = 0.25) -> None:
        if not model_path or not os.path.isfile(model_path):
            raise DetectorUnavailable(f"YOLO weights not found: {model_path!r} (set hints['model_path'])")
        try:
            from ultralytics import YOLO  # type: ignore import-not-found
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            raise DetectorUnavailable(f"ultralytics is not importable: {exc}") from exc

        self._device = self._resolve_device(device)
        self._confidence_threshold = float(confidence_threshold)
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
            detector: BottleDetector = YoloBottleDetector(config.model_path, device=config.device)
            _DETECTOR_CACHE[key] = detector
            return detector
        except DetectorUnavailable as exc:
            logger.info("YOLO unavailable (%s); using CPU heuristic fallback", exc)

    detector = HeuristicBottleDetector()
    _DETECTOR_CACHE[key] = detector
    return detector
