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
from services.vision.config import VisionConfig, YOLO_CONF_ENV, YOLO_MODEL_ENV, yolo_confidence_threshold
from services.vision.detector import (
    BottleDetector,
    Detection,
    DetectorUnavailable,
    HeuristicBottleDetector,
    OnnxBottleDetector,
    YoloBottleDetector,
    get_detector,
)
from services.vision.label import locate_label, locate_label_region
from services.vision.models import FrameInfo, VisionResult
from services.vision.pipeline import analyze_frame, derive_guidance
from services.vision.preprocess import (
    ImageDecodeError,
    crop_label,
    crop_label_array,
    crop_normalized,
    decode_image,
    enhance_for_ocr,
    preprocess,
)
from services.vision.quality import evaluate_quality

__all__ = [
    "analyze_frame",
    "derive_guidance",
    "evaluate_quality",
    "preprocess",
    "decode_image",
    "crop_normalized",
    "crop_label",
    "crop_label_array",
    "enhance_for_ocr",
    "ImageDecodeError",
    "VisionConfig",
    "YOLO_MODEL_ENV",
    "YOLO_CONF_ENV",
    "yolo_confidence_threshold",
    "VisionResult",
    "FrameInfo",
    "Detection",
    "BottleDetector",
    "HeuristicBottleDetector",
    "OnnxBottleDetector",
    "YoloBottleDetector",
    "DetectorUnavailable",
    "get_detector",
    "locate_label",
    "locate_label_region",
]
