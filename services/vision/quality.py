"""Frame-quality evaluation: blur, exposure and glare.

All outputs are deterministic scores in `[0, 1]` (1 = best) plus boolean flags
and user-facing camera guidance. Thresholds were calibrated on the synthetic
fixtures in `tests/fixtures/`; they are module constants so calibration is
explicit and reproducible.

Metrics (CPU, OpenCV):
- blur: variance of the Laplacian on the grayscale frame.
- exposure: mean luma plus clipping fractions at both ends of the histogram.
- glare: fraction of near-saturated pixels that form a sizeable blob (a lone
  clipped speck cannot trigger it); saturated highlights are usually specular.
"""
from __future__ import annotations

import cv2
import numpy as np

from services.common.contract import Blur, Exposure, FrameQuality, Glare
from services.vision.preprocess import to_gray

# --- blur ---
#: Laplacian variance below this fails the frame.
BLUR_MIN = 45.0
#: Score reaches 1.0 at this variance (soft saturation keeps the score smooth).
BLUR_GOOD = 220.0

# --- exposure ---
DARK_MEAN = 60.0  # mean luma below this is "too dark"
BRIGHT_MEAN = 200.0  # mean luma above this is "too bright"
DARK_CLIP_FRACTION = 0.45  # fraction of pixels <= 12
BRIGHT_CLIP_FRACTION = 0.35  # fraction of pixels >= 245

# --- glare ---
#: Near-saturated pixel (luma >= 250) considered specular glare.
GLARE_LEVEL = 250
#: Fraction of the frame that must be saturated before glare is flagged.
GLARE_FRACTION = 0.02
#: The saturated pixels must form one blob at least this fraction of the frame.
GLARE_BLOB_FRACTION = 0.012
#: Above this fraction of saturated pixels the frame is overexposed rather than
#: showing a localized specular highlight; the exposure term owns it.
GLARE_DOMINANT_FRACTION = 0.50


def _clip01(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _blur(gray: np.ndarray) -> tuple[float, bool]:
    # Contrast-normalize first so a correctly focused but dark frame is not
    # mistaken for a blurry one (underexposure is reported by the exposure term).
    normalized = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    variance = float(cv2.Laplacian(normalized, cv2.CV_64F).var())
    floor = BLUR_MIN * 0.5
    score = _clip01((variance - floor) / (BLUR_GOOD - floor))
    return round(score, 4), variance < BLUR_MIN


def _exposure(gray: np.ndarray) -> Exposure:
    total = float(gray.size)
    mean = float(gray.mean())
    dark_fraction = float(np.count_nonzero(gray <= 12)) / total
    bright_fraction = float(np.count_nonzero(gray >= 245)) / total

    # Full score inside the comfortable band [80, 180], tapering to 0 at 20 / 240.
    if mean < 80.0:
        band = _clip01((mean - 20.0) / 60.0)
    elif mean > 180.0:
        band = _clip01((240.0 - mean) / 60.0)
    else:
        band = 1.0
    clip_penalty = min(1.0, 2.0 * dark_fraction + 2.0 * bright_fraction)
    score = _clip01(band * (1.0 - 0.5 * clip_penalty))

    return Exposure(
        score=round(score, 4),
        too_dark=bool(mean < DARK_MEAN or dark_fraction > DARK_CLIP_FRACTION),
        too_bright=bool(mean > BRIGHT_MEAN or bright_fraction > BRIGHT_CLIP_FRACTION),
    )


def _glare(gray: np.ndarray) -> tuple[float, bool]:
    mask = (gray >= GLARE_LEVEL).astype(np.uint8)
    total = float(gray.size)
    fraction = float(np.count_nonzero(mask)) / total
    if fraction == 0.0:
        return 1.0, False

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    largest = float(stats[1:, cv2.CC_STAT_AREA].max()) / total if count > 1 else 0.0

    if fraction >= GLARE_DOMINANT_FRACTION:
        # Most of the frame is saturated: that is overexposure (already reported
        # by the exposure term), not a specular highlight on the label.
        return 1.0, False

    has_glare = fraction >= GLARE_FRACTION and largest >= GLARE_BLOB_FRACTION
    score = _clip01(1.0 - fraction / 0.25)
    return round(score, 4), bool(has_glare)


def evaluate_quality(rgb: np.ndarray) -> FrameQuality:
    """Score one analysis frame (uint8 RGB) and build camera guidance."""
    gray = to_gray(rgb)

    blur_score, is_blurry = _blur(gray)
    exposure = _exposure(gray)
    glare_score, has_glare = _glare(gray)

    score = _clip01(0.5 * blur_score + 0.25 * exposure.score + 0.25 * glare_score)
    acceptable = not (is_blurry or exposure.too_dark or exposure.too_bright or has_glare)

    guidance: list[str] = []
    if is_blurry:
        guidance.append("Hold the bottle steady and let the camera focus.")
    if exposure.too_dark:
        guidance.append("Move to a brighter spot or turn on more light.")
    if exposure.too_bright:
        guidance.append("Reduce direct light or step away from the bright source.")
    if has_glare:
        guidance.append("Tilt the bottle so glare moves off the label.")

    return FrameQuality(
        acceptable=acceptable,
        score=round(score, 4),
        blur=Blur(score=blur_score, is_blurry=is_blurry),
        exposure=exposure,
        glare=Glare(score=glare_score, has_glare=has_glare),
        guidance=guidance,
    )
