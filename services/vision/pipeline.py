"""`analyze_frame` — the import surface used by the API gateway.

CPU-only by default: decode/preprocess -> frame quality -> bottle detection ->
label localization -> camera guidance. The detector is chosen by `VisionConfig`;
when YOLO is requested but unavailable, the deterministic CPU heuristic takes
over, so this function never requires a GPU.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from services.common.contract import Bottle, FrameQuality, Label, Timing
from services.vision.config import VisionConfig
from services.vision.detector import BottleDetector, Detection, HeuristicBottleDetector, get_detector
from services.vision.label import locate_label
from services.vision.models import FrameInfo, VisionResult
from services.vision.preprocess import preprocess
from services.vision.quality import evaluate_quality

logger = logging.getLogger(__name__)

#: Below this fraction of the frame the label is considered too small to OCR.
DEFAULT_LABEL_MIN_AREA = 0.08
_ALL_GOOD_GUIDANCE = "Looks good - hold steady."


def _ms(start: float, end: float) -> float:
    return (end - start) * 1000.0


def derive_guidance(
    quality: FrameQuality,
    bottle: Bottle,
    label: Label,
    label_min_area: float = DEFAULT_LABEL_MIN_AREA,
) -> List[str]:
    """Ordered camera guidance: quality fixes first, then framing fixes."""
    guidance: List[str] = list(quality.guidance)

    if not bottle.detected:
        guidance.append("Center the bottle in the frame.")
    elif not label.detected or label.bbox is None:
        guidance.append("Point the camera at the label on the bottle.")
    elif label.bbox.w * label.bbox.h < label_min_area:
        guidance.append("Move closer until the label fills the frame.")

    if not guidance:
        guidance.append(_ALL_GOOD_GUIDANCE)
    return list(dict.fromkeys(guidance))


def _detect(detector: BottleDetector, image: np.ndarray) -> Tuple[Optional[Detection], str]:
    try:
        return detector.detect(image), detector.name
    except Exception:  # noqa: BLE001 - a detector failure must degrade, not crash the scan
        if detector.name == "heuristic":
            logger.exception("heuristic detector failed")
            return None, "heuristic"
        logger.exception("%s detector failed; falling back to CPU heuristic", detector.name)
        try:
            return HeuristicBottleDetector().detect(image), "heuristic"
        except Exception:  # noqa: BLE001
            logger.exception("heuristic fallback failed")
            return None, "none"


def analyze_frame(image_bytes: bytes, hints: Optional[Dict] = None) -> VisionResult:
    """Analyze one camera frame end-to-end.

    Args:
        image_bytes: JPEG/PNG bytes as received from the iOS client.
        hints: optional dict; recognized keys are the `VisionConfig` fields
            (`max_side`, `clahe`, `denoise`, `detector`, `model_path`, `device`).
            Unknown keys are ignored.

    Returns:
        `VisionResult` with quality scores in `[0,1]`, normalized bottle/label
        bboxes, ordered guidance strings and per-stage timing.

    Raises:
        ImageDecodeError: if the bytes cannot be decoded.
        TypeError: if `hints` is not a dict/None.
    """
    config = VisionConfig.from_hints(hints)
    stage_ms: Dict[str, float] = {}
    t_start = time.perf_counter()

    pre = preprocess(image_bytes, config)
    t_pre = time.perf_counter()
    stage_ms["preprocess"] = _ms(t_start, t_pre)

    quality = evaluate_quality(pre.image)
    t_quality = time.perf_counter()
    stage_ms["quality"] = _ms(t_pre, t_quality)

    detector = get_detector(config)
    detection, detector_name = _detect(detector, pre.image)
    t_detect = time.perf_counter()
    stage_ms["detect"] = _ms(t_quality, t_detect)

    bottle = Bottle(
        detected=detection is not None,
        confidence=detection.confidence if detection is not None else 0.0,
        bbox=detection.bbox if detection is not None else None,
    )
    label = locate_label(pre.image, bottle)
    t_label = time.perf_counter()
    stage_ms["label"] = _ms(t_detect, t_label)

    total_ms = _ms(t_start, t_label)
    return VisionResult(
        quality=quality,
        bottle=bottle,
        label=label,
        guidance=derive_guidance(quality, bottle, label),
        timing=Timing(
            total_ms=round(total_ms, 3),
            stages={name: round(value, 3) for name, value in stage_ms.items()},
        ),
        detector=detector_name,
        frame=FrameInfo(
            width=pre.width,
            height=pre.height,
            original_width=pre.original_width,
            original_height=pre.original_height,
            scale=round(pre.scale, 6),
            applied=list(pre.applied),
        ),
    )
