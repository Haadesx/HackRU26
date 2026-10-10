"""Small test helpers."""
from __future__ import annotations

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
