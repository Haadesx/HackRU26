"""Label localization.

Two paths:

1. **Bottle present** — the label is the largest bright, low-chroma region below
   the cap inside the bottle bbox (white/cream paper against colored plastic).
   Falls back to a conservative centered band with low confidence when no region
   qualifies, so the OCR stage still receives a crop.
2. **No bottle detected** — a frame-level search for a large bright, low-chroma
   region with text-like dark pixels, which handles flat label close-ups. The
   confidence is capped because there is no bottle anchor.

All output boxes are normalized `[0,1]` frame coordinates.
"""
from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np

from services.common.contract import BBox, Bottle, Label
from services.vision.preprocess import crop_normalized, to_gray

#: Search-window thresholds, relative to the bottle ROI.
MIN_REGION_FRACTION = 0.02
MAX_REGION_FRACTION = 0.85
MIN_FILL = 0.35
MIN_ASPECT = 0.30  # width / height
MAX_ASPECT = 2.20
MIN_CENTER_Y = 0.15  # labels sit below the cap; reject top background strips

#: Frame-level fallback (no bottle): a flat label may fill most of the frame.
#: The brightness gate adapts to the frame (percentile-based) so dim-but-readable
#: documents are found; a floor keeps mask fragmentation impossible.
FRAME_MAX_REGION_FRACTION = 0.98
FRAME_BRIGHTNESS_PERCENTILE = 60.0
FRAME_BRIGHTNESS_MARGIN = 5.0
FRAME_MIN_BRIGHTNESS = 60.0
#: The blur-scale structure gate below is the real noise discriminator; the raw
#: dark/edge gates are coarse text hints and must stay loose enough for sparse
#: text on a large cut-off label crop.
FRAME_MIN_DARK_FRACTION = 0.002  # must contain some dark text-like pixels
FRAME_MAX_DARK_FRACTION = 0.30
FRAME_MIN_EDGE_DENSITY = 0.001
FRAME_CONFIDENCE_CAP = 0.60

#: Brightness / chroma gates in CIELAB (OpenCV encoding: L in [0,255], a/b centered at 128).
LAB_BRIGHTNESS = 165
LAB_CHROMA = 32
#: Noise immunity for the frame-level fallback: raw dark/edge gates pass on dense
#: sensor noise (every pixel is an edge and many are dark). After a Gaussian
#: blur, noise flattens to a nearly constant field while text strokes survive as
#: pixels well below the region median. `dark_evidence` is the fraction of such
#: pixels; it is ~0 for pure noise and a few percent for text.
EVIDENCE_BLUR_SIGMA = 3.0
EVIDENCE_DARK_OFFSET = 30.0
FRAME_MIN_DARK_EVIDENCE = 0.0025
#: Dark pixel threshold for the text-evidence check.
TEXT_DARK_LEVEL = 80

FALLBACK_CONFIDENCE = 0.25


def _clip01(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _clamp_bbox(x: float, y: float, w: float, h: float) -> BBox:
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    w = min(max(w, 0.0), 1.0 - x)
    h = min(max(h, 0.0), 1.0 - y)
    return BBox(x=round(x, 6), y=round(y, 6), w=round(w, 6), h=round(h, 6))


def _search_region(
    roi: np.ndarray,
    *,
    max_region_fraction: float = MAX_REGION_FRACTION,
    min_center_y: float = MIN_CENTER_Y,
    brightness: float = LAB_BRIGHTNESS,
) -> Optional[Tuple[int, int, int, int, float]]:
    """Largest plausible label region in ROI pixel coords: (x, y, w, h, area)."""
    rh, rw = roi.shape[:2]
    lab = cv2.cvtColor(roi, cv2.COLOR_RGB2LAB)
    l_ch = lab[:, :, 0].astype(np.int16)
    a_ch = lab[:, :, 1].astype(np.int16) - 128
    b_ch = lab[:, :, 2].astype(np.int16) - 128
    chroma = np.sqrt(a_ch.astype(np.float32) ** 2 + b_ch.astype(np.float32) ** 2)

    # No morphological closing here: a close wide enough to merge text gaps also
    # bridges thin dark label borders, fusing the page with its margin into a
    # useless full-frame component. The bright paper stays connected around text.
    mask = ((l_ch >= brightness) & (chroma <= LAB_CHROMA)).astype(np.uint8)

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    roi_area = float(rw * rh)
    best = None
    for i in range(1, count):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        fraction = area / roi_area
        if not (MIN_REGION_FRACTION <= fraction <= max_region_fraction):
            continue
        if (y + bh / 2.0) < min_center_y * rh and bh < 0.5 * rh:
            continue
        aspect = bw / float(max(1, bh))
        if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
            continue
        if area / float(max(1, bw * bh)) < MIN_FILL:
            continue
        if best is None or area > best[4]:
            best = (x, y, bw, bh, area)
    return best


def locate_label_region(rgb: np.ndarray) -> Optional[Tuple[BBox, float]]:
    """Best-effort label region for frames where no bottle was detected.

    The brightness gate adapts to the frame so a dim but readable document is
    still found; the dark-pixel/edge gates reject plain bright surfaces.
    """
    luminance = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[:, :, 0]
    brightness = max(
        FRAME_MIN_BRIGHTNESS,
        float(np.percentile(luminance, FRAME_BRIGHTNESS_PERCENTILE)) - FRAME_BRIGHTNESS_MARGIN,
    )
    found = _search_region(
        rgb,
        max_region_fraction=FRAME_MAX_REGION_FRACTION,
        min_center_y=0.0,
        brightness=brightness,
    )
    if found is None:
        return None
    x, y, w, h, area = found
    gray = to_gray(rgb[y : y + h, x : x + w])
    dark_fraction = float(np.count_nonzero(gray <= TEXT_DARK_LEVEL)) / gray.size
    if not (FRAME_MIN_DARK_FRACTION <= dark_fraction <= FRAME_MAX_DARK_FRACTION):
        return None
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / edges.size
    if edge_density < FRAME_MIN_EDGE_DENSITY:
        return None

    # Cheap raw gates above pass on noise; require real structure at the blur scale.
    evidence = cv2.GaussianBlur(gray, (0, 0), EVIDENCE_BLUR_SIGMA)
    evidence_threshold = float(np.percentile(evidence, 50)) - EVIDENCE_DARK_OFFSET
    dark_evidence = float(np.count_nonzero(evidence <= evidence_threshold)) / evidence.size
    if dark_evidence < FRAME_MIN_DARK_EVIDENCE:
        return None

    frame_h, frame_w = rgb.shape[:2]
    bbox = _clamp_bbox(x / frame_w, y / frame_h, w / frame_w, h / frame_h)
    coverage = area / float(frame_w * frame_h)
    confidence = min(FRAME_CONFIDENCE_CAP, 0.35 + 0.25 * coverage + min(edge_density, 0.05))
    return bbox, round(confidence, 4)


def locate_label(rgb: np.ndarray, bottle: Bottle) -> Label:
    """Locate the label region on a detected bottle, or frame-level without one."""
    if not bottle.detected or bottle.bbox is None:
        region = locate_label_region(rgb)
        if region is None:
            return Label(detected=False, confidence=0.0, bbox=None, text=None)
        bbox, confidence = region
        return Label(detected=True, confidence=confidence, bbox=bbox, text=None)

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
