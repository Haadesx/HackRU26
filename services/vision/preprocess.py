"""Deterministic, CPU-only image decoding and preprocessing.

Order: decode (EXIF orientation applied) -> resize (never upscale) -> optional
denoise -> optional CLAHE. All steps are deterministic for a given input, so the
same photo bytes always yield the same analysis frame.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageOps

from services.common.contract import BBox
from services.vision.config import VisionConfig


class ImageDecodeError(ValueError):
    """Raised when `image_bytes` cannot be decoded as a still image."""


@dataclass
class Preprocessed:
    image: np.ndarray  # uint8 RGB, EXIF orientation applied
    original_width: int
    original_height: int
    width: int
    height: int
    scale: float  # analysis width / original width
    applied: List[str] = field(default_factory=list)


def decode_image(image_bytes: bytes) -> np.ndarray:
    """Decode PNG/JPEG/BMP/WebP bytes to a uint8 RGB array with EXIF rotation applied."""
    if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
        raise TypeError("image_bytes must be bytes-like")
    data = bytes(image_bytes)
    if not data:
        raise ImageDecodeError("empty image bytes")

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            oriented = ImageOps.exif_transpose(im)
            if oriented.mode != "RGB":
                oriented = oriented.convert("RGB")
            return np.array(oriented, dtype=np.uint8, copy=True)
    except Exception:
        # Fall through to OpenCV for formats Pillow refuses (e.g. some BMP variants).
        pass

    arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise ImageDecodeError("could not decode image bytes (unsupported or corrupt image)")
    return cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)


def to_gray(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim == 2:
        return rgb
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError(f"expected an (H, W, 3) RGB image, got shape {rgb.shape}")
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def resize_for_analysis(rgb: np.ndarray, max_side: int) -> Tuple[np.ndarray, float, bool]:
    """Downscale so the longest side is <= max_side. Never upscales."""
    h, w = rgb.shape[:2]
    if max(h, w) <= max_side:
        return rgb, 1.0, False
    scale = max_side / float(max(h, w))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    out = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return out, out.shape[1] / float(w), True


def apply_clahe(rgb: np.ndarray, clip_limit: float = 2.0, grid: Tuple[int, int] = (8, 8)) -> np.ndarray:
    """Contrast-limited adaptive histogram equalization on the LAB luminance channel."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=grid)
    return cv2.cvtColor(cv2.merge((clahe.apply(l_ch), a_ch, b_ch)), cv2.COLOR_LAB2RGB)


def apply_denoise(rgb: np.ndarray, strength: int = 5) -> np.ndarray:
    """Light non-local-means denoise (CPU). Disabled by default because it is slow."""
    return cv2.fastNlMeansDenoisingColored(rgb, None, strength, strength, 7, 21)


def enhance_for_ocr(rgb: np.ndarray) -> np.ndarray:
    """Grayscale + CLAHE variant of a (label) crop, useful for the OCR stage."""
    gray = to_gray(rgb)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def crop_normalized(rgb: np.ndarray, bbox: BBox) -> np.ndarray:
    """Crop a normalized bbox out of an RGB frame (clamped to the frame)."""
    h, w = rgb.shape[:2]
    x0 = int(np.floor(bbox.x * w))
    y0 = int(np.floor(bbox.y * h))
    x1 = int(np.ceil((bbox.x + bbox.w) * w))
    y1 = int(np.ceil((bbox.y + bbox.h) * h))
    x0 = max(0, min(x0, w - 1))
    y0 = max(0, min(y0, h - 1))
    x1 = max(x0 + 1, min(x1, w))
    y1 = max(y0 + 1, min(y1, h))
    return rgb[y0:y1, x0:x1]


def preprocess(image_bytes: bytes, config: Optional[VisionConfig] = None) -> Preprocessed:
    cfg = config or VisionConfig()
    rgb = decode_image(image_bytes)
    orig_h, orig_w = rgb.shape[:2]

    applied = ["decode", "exif_orientation"]
    img, scale, resized = resize_for_analysis(rgb, cfg.max_side)
    if resized:
        applied.append("resize")
    if cfg.denoise:
        img = apply_denoise(img)
        applied.append("denoise")
    if cfg.clahe:
        img = apply_clahe(img)
        applied.append("clahe")

    h, w = img.shape[:2]
    return Preprocessed(
        image=img,
        original_width=orig_w,
        original_height=orig_h,
        width=w,
        height=h,
        scale=w / float(orig_w),
        applied=applied,
    )
