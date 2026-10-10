"""Small test helpers."""
from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image

from services.common.contract import BBox


def iou(a: BBox, b: BBox) -> float:
    """Intersection-over-union of two normalized bboxes."""
    x0 = max(a.x, b.x)
    y0 = max(a.y, b.y)
    x1 = min(a.x + a.w, b.x + b.w)
    y1 = min(a.y + a.h, b.y + b.h)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a.w * a.h + b.w * b.h - intersection
    return intersection / union if union > 0 else 0.0


def bbox_inside(inner: BBox, outer: BBox, tolerance: float = 1e-6) -> bool:
    return (
        inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.x + inner.w <= outer.x + outer.w + tolerance
        and inner.y + inner.h <= outer.y + outer.h + tolerance
    )


def png_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


def noise_frame(sigma: int = 40, size: tuple[int, int] = (320, 320)) -> np.ndarray:
    """Pure Gaussian sensor noise frame (no label, no structure)."""
    return np.array(Image.effect_noise(size, sigma).convert("RGB"))


def flat_label_frame(width: int = 320, height: int = 220, page: int = 190) -> np.ndarray:
    """Synthetic flat label close-up (bright page, dark border and text)."""
    frame = np.full((height, width, 3), page, dtype=np.uint8)
    cv2.rectangle(frame, (5, 5), (width - 6, height - 6), (20, 20, 20), 3)
    cv2.putText(frame, "EXAMPLEX 500 mg", (32, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (25, 25, 25), 2, cv2.LINE_AA)
    cv2.putText(frame, "Take 1 tablet by mouth daily", (32, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (25, 25, 25), 1, cv2.LINE_AA)
    cv2.putText(frame, "LOT E-0001", (32, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (25, 25, 25), 1, cv2.LINE_AA)
    return frame
