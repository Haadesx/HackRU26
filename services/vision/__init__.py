"""MedCheck vision service — PI-1 VISION (owner: Atlas, branch `feat/vision-atlas`).

Public surface used by the API gateway:

    from services.vision import analyze_frame

    result = analyze_frame(image_bytes, hints={"max_side": 1280})
    result.quality.acceptable   # bool
    result.bottle               # detected / confidence / normalized bbox
    result.label                # detected / confidence / normalized bbox
    result.guidance             # ordered camera guidance strings
    result.timing.total_ms

CPU-only: no GPU or model file is required; YOLO is used only when weights are
configured and the optional `ultralytics` dependency is installed.
"""
from services.vision.config import VisionConfig
from services.vision.detector import (
    BottleDetector,
    Detection,
    DetectorUnavailable,
    HeuristicBottleDetector,
    YoloBottleDetector,
    get_detector,
)
from services.vision.label import locate_label
from services.vision.models import FrameInfo, VisionResult
from services.vision.pipeline import analyze_frame, derive_guidance
from services.vision.preprocess import ImageDecodeError, crop_normalized, decode_image, enhance_for_ocr, preprocess
from services.vision.quality import evaluate_quality

__all__ = [
    "analyze_frame",
    "derive_guidance",
    "evaluate_quality",
    "preprocess",
    "decode_image",
    "crop_normalized",
    "enhance_for_ocr",
    "ImageDecodeError",
    "VisionConfig",
    "VisionResult",
    "FrameInfo",
    "Detection",
    "BottleDetector",
    "HeuristicBottleDetector",
    "YoloBottleDetector",
    "DetectorUnavailable",
    "get_detector",
    "locate_label",
]
