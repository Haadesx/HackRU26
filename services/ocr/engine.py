"""OCR engine for MedCheck (PI-2 / Orion).

Pinned backend: ``rapidocr-onnxruntime`` (ONNX Runtime, offline PP-OCRv4 models).
See ``services/ocr/DECISION.md`` for the stack decision.

Public API::

    read_text(image, bbox=None) -> OcrResult

``image`` may be a BGR/RGB numpy array, a path readable by OpenCV, or a PIL image.
``bbox`` (normalized, contract v1) crops the frame first; returned boxes are
re-mapped to normalized coordinates of the FULL input frame. Raw text is never
cleaned or corrected here.
"""

from __future__ import annotations

import importlib.util
import os
import time
from typing import Any, Sequence

import numpy as np

from .types import BBox, OcrLine, OcrResult, has_readable_content

BACKEND_NAME = "rapidocr-onnxruntime"
_ENGINE: Any = None

# Bbox crops whose long side is smaller than this are upscaled before
# recognition. RapidOCR's detector already rescales internally
# (limit_side_len=736, limit_type=min), so upscaling crops near that size is
# redundant and can disturb word spacing; below it, Lanczos helps small/distant
# labels without merging words.
MIN_CROP_LONG_SIDE = 700
MAX_CROP_UPSCALE = 4.0


class OcrUnavailableError(RuntimeError):
    """Raised when the OCR backend is not installed."""


def is_available() -> bool:
    """True when the pinned OCR backend can be imported."""
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def _load_engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        if not is_available():
            raise OcrUnavailableError(
                "rapidocr-onnxruntime is not installed. "
                "Run: uv venv .venv --python 3.11 && uv pip install -r services/ocr/requirements.txt"
            )
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _coerce_bbox(bbox: Any) -> BBox | None:
    if bbox is None or isinstance(bbox, BBox):
        return bbox
    if isinstance(bbox, Sequence) and len(bbox) == 4:
        return BBox(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    raise TypeError("bbox must be a services.ocr.types.BBox or an (x, y, w, h) sequence")


def _to_bgr_array(image: Any, channel_order: str = "bgr") -> np.ndarray:
    """Normalize any supported input to a contiguous HxWx3 BGR uint8 array."""
    if isinstance(image, np.ndarray):
        arr = image
        if arr.ndim == 3 and channel_order.lower() == "rgb":
            arr = arr[:, :, ::-1]
    elif isinstance(image, (str, os.PathLike)):
        import cv2

        arr = cv2.imread(str(image))
        if arr is None:
            raise ValueError(f"could not read image: {image!r}")
    elif hasattr(image, "convert"):  # PIL.Image
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1]
    else:
        arr = np.asarray(image)
        if arr.ndim == 3 and channel_order.lower() == "rgb":
            arr = arr[:, :, ::-1]
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise ValueError("image must be HxW or HxWx3")
    return np.ascontiguousarray(arr[:, :, :3])


def _normalize_backend_output(output: Any) -> list[tuple[Any, str, float | None]]:
    """Convert RapidOCR output variants to ``[(points, text, score), ...]``."""
    result = output[0] if isinstance(output, tuple) else output
    if result is None:
        return []
    items: list[tuple[Any, str, float | None]] = []
    if hasattr(result, "boxes"):  # newer object-style API
        boxes = getattr(result, "boxes", None) or []
        texts = getattr(result, "txts", None) or []
        scores = getattr(result, "scores", None) or []
        for index, points in enumerate(boxes):
            text = texts[index] if index < len(texts) else ""
            score = scores[index] if index < len(scores) else None
            items.append((points, str(text), float(score) if score is not None else None))
        return items
    for entry in result:  # classic list API: [points, text, score]
        if not entry:
            continue
        points = entry[0]
        text = str(entry[1]) if len(entry) > 1 and entry[1] is not None else ""
        score = entry[2] if len(entry) > 2 else None
        items.append((points, text, float(score) if score is not None else None))
    return items


def _prepare_crop(crop: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Upscale a small bbox crop; returns ``(image, scale_x, scale_y)``.

    Crops whose long side is already >= :data:`MIN_CROP_LONG_SIDE` are returned
    unchanged so the full-size path keeps its previous behavior.

    Lanczos upscaling alone is used: contrast enhancement (CLAHE) was measured to
    merge word spacing on synthetic pharmacy labels ("Take1 tabletbymouth..."),
    which breaks cadence parsing and pharmacy-name extraction. Crops at or above
    RapidOCR's internal detector limit (limit_side_len=736) read natively and are
    returned unchanged.
    """
    height, width = crop.shape[:2]
    long_side = max(height, width)
    if long_side <= 0 or long_side >= MIN_CROP_LONG_SIDE:
        return crop, 1.0, 1.0
    scale = min(MAX_CROP_UPSCALE, MIN_CROP_LONG_SIDE / long_side)
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    import cv2

    resized = cv2.resize(crop, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
    return resized, new_width / width, new_height / height


def read_text(
    image: Any,
    bbox: BBox | Sequence[float] | None = None,
    *,
    channel_order: str = "bgr",
    engine: Any = None,
) -> OcrResult:
    """Run OCR and return raw text with per-line boxes.

    Args:
        image: BGR numpy array (OpenCV default), RGB array with
            ``channel_order="rgb"``, image path, or PIL image.
        bbox: optional normalized crop; results are mapped back to the full frame.
        channel_order: channel order for numpy inputs (``"bgr"`` or ``"rgb"``).
        engine: pre-built backend instance (tests); otherwise a cached RapidOCR.

    Returns:
        :class:`OcrResult` whose ``raw_text`` is the verbatim ``"\\n"`` join of
        recognized line texts. ``lines`` carry normalized line boxes; word boxes
        are empty because the pinned backend is line-level only.
    """
    crop_box = _coerce_bbox(bbox)
    arr = _to_bgr_array(image, channel_order=channel_order)
    full_h, full_w = arr.shape[:2]
    offset_x = offset_y = 0
    scale_x = scale_y = 1.0
    if crop_box is not None:
        x1, y1, x2, y2 = crop_box.to_pixels(full_w, full_h)
        if x2 - x1 < 2 or y2 - y1 < 2:
            raise ValueError("bbox crop is too small for OCR")
        arr = arr[y1:y2, x1:x2]
        arr, scale_x, scale_y = _prepare_crop(arr)
        offset_x, offset_y = x1, y1

    ocr = engine if engine is not None else _load_engine()
    started = time.perf_counter()
    output = ocr(arr)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    lines: list[OcrLine] = []
    for points, text, score in _normalize_backend_output(output):
        if not text:
            continue
        line_bbox = None
        if points is not None and len(points) >= 2:
            # Recognition ran on the (possibly upscaled) crop: map back to the
            # full frame before normalizing.
            mapped = [(float(p[0]) / scale_x, float(p[1]) / scale_y) for p in points]
            line_bbox = BBox.from_points(mapped, full_w, full_h, offset_x, offset_y)
        lines.append(
            OcrLine(
                text=text,
                confidence=score if score is not None else 0.5,
                bbox=line_bbox,
                words=(),  # RapidOCR returns line-level boxes only.
            )
        )
    return OcrResult(
        raw_text="\n".join(line.text for line in lines),
        lines=lines,
        engine=BACKEND_NAME,
        elapsed_ms=round(elapsed_ms, 2),
        image_size=(full_w, full_h),
    )
