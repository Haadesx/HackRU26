"""Label localization inside a detected bottle.

The label is the largest bright, low-chroma region below the cap: white/cream
paper against colored plastic. If no region qualifies (unusual lighting, wrapped
label, transparent bottle), a conservative centered band of the bottle is
returned with low confidence so the OCR stage still receives a crop. All output
boxes are normalized `[0,1]` frame coordinates.
"""
from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np

from services.common.contract import BBox, Bottle, Label
from services.vision.preprocess import crop_normalized

#: Search-window thresholds, relative to the bottle ROI.
MIN_REGION_FRACTION = 0.02
MAX_REGION_FRACTION = 0.85
MIN_FILL = 0.35
MIN_ASPECT = 0.30  # width / height
MAX_ASPECT = 2.20
MIN_CENTER_Y = 0.15  # labels sit below the cap; reject top background strips

#: Brightness / chroma gates in CIELAB (OpenCV encoding: L in [0,255], a/b centered at 128).
LAB_BRIGHTNESS = 165
LAB_CHROMA = 32
CLOSE_KERNEL = 21

FALLBACK_CONFIDENCE = 0.25


def _clip01(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _clamp_bbox(x: float, y: float, w: float, h: float) -> BBox:
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    w = min(max(w, 0.0), 1.0 - x)
    h = min(max(h, 0.0), 1.0 - y)
    return BBox(x=round(x, 6), y=round(y, 6), w=round(w, 6), h=round(h, 6))


def _search_region(roi: np.ndarray) -> Optional[Tuple[int, int, int, int, float]]:
    """Largest plausible label region in ROI pixel coords: (x, y, w, h, area)."""
    rh, rw = roi.shape[:2]
    lab = cv2.cvtColor(roi, cv2.COLOR_RGB2LAB)
    l_ch = lab[:, :, 0].astype(np.int16)
    a_ch = lab[:, :, 1].astype(np.int16) - 128
    b_ch = lab[:, :, 2].astype(np.int16) - 128
    chroma = np.sqrt(a_ch.astype(np.float32) ** 2 + b_ch.astype(np.float32) ** 2)

    mask = ((l_ch >= LAB_BRIGHTNESS) & (chroma <= LAB_CHROMA)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((CLOSE_KERNEL, CLOSE_KERNEL), np.uint8))

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    roi_area = float(rw * rh)
    best = None
    for i in range(1, count):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        fraction = area / roi_area
        if not (MIN_REGION_FRACTION <= fraction <= MAX_REGION_FRACTION):
            continue
        if (y + bh / 2.0) < MIN_CENTER_Y * rh and bh < 0.5 * rh:
            continue
        aspect = bw / float(max(1, bh))
        if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
            continue
        if area / float(max(1, bw * bh)) < MIN_FILL:
            continue
        if best is None or area > best[4]:
            best = (x, y, bw, bh, area)
    return best


def locate_label(rgb: np.ndarray, bottle: Bottle) -> Label:
    """Locate the label region on an already-detected bottle."""
    if not bottle.detected or bottle.bbox is None:
        return Label(detected=False, confidence=0.0, bbox=None, text=None)

    frame_h, frame_w = rgb.shape[:2]
    roi = crop_normalized(rgb, bottle.bbox)
    if roi.shape[0] < 8 or roi.shape[1] < 8:
        roi = None

    if roi is not None:
        found = _search_region(roi)
        if found is not None:
            x, y, bw, bh, area = found
            rh, rw = roi.shape[:2]
            pad = 0.01  # of full frame, keeps text near the label edge
            x0 = max(bottle.bbox.x, bottle.bbox.x + x / frame_w - pad)
            y0 = max(bottle.bbox.y, bottle.bbox.y + y / frame_h - pad)
            x1 = min(bottle.bbox.x + bottle.bbox.w, bottle.bbox.x + (x + bw) / frame_w + pad)
            y1 = min(bottle.bbox.y + bottle.bbox.h, bottle.bbox.y + (y + bh) / frame_h + pad)
            bbox = _clamp_bbox(x0, y0, x1 - x0, y1 - y0)
            coverage = min(1.0, area / float(rw * rh))
            confidence = min(0.95, 0.5 + 0.45 * coverage)
            return Label(detected=True, confidence=round(confidence, 4), bbox=bbox, text=None)

    # Conservative fallback: lower-middle band of the bottle.
    bx = bottle.bbox
    w = min(bx.w * 0.72, 1.0)
    h = min(bx.h * 0.42, 1.0)
    x = min(max(bx.x + (bx.w - w) / 2.0, 0.0), 1.0 - w)
    y = min(max(bx.y + bx.h * 0.32, 0.0), 1.0 - h)
    return Label(detected=True, confidence=FALLBACK_CONFIDENCE, bbox=_clamp_bbox(x, y, w, h), text=None)
