"""Preprocessing tests: decode, EXIF, resize policy, enhancements."""
import io

import cv2
import numpy as np
import pytest
from PIL import Image

from services.common.contract import BBox
from services.vision.config import VisionConfig
from services.vision.preprocess import (
    ImageDecodeError,
    Preprocessed,
    crop_normalized,
    decode_image,
    enhance_for_ocr,
    preprocess,
    resize_for_analysis,
)


def _png_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


def test_decode_png_bytes(load_bytes):
    rgb = decode_image(load_bytes("sharp_bottle.png"))
    assert rgb.dtype == np.uint8
    assert rgb.shape == (640, 480, 3)


def test_invalid_bytes_raise():
    with pytest.raises(ImageDecodeError):
        decode_image(b"definitely not an image")


def test_empty_bytes_raise():
    with pytest.raises(ImageDecodeError):
        decode_image(b"")


def test_non_bytes_raise_type_error():
    with pytest.raises(TypeError):
        decode_image("not bytes")  # type: ignore[arg-type]


def test_resize_policy_never_upscales():
    small = np.zeros((100, 200, 3), dtype=np.uint8)
    out, scale, resized = resize_for_analysis(small, max_side=1000)
    assert not resized
    assert scale == 1.0
    assert out.shape[:2] == (100, 200)


def test_resize_policy_downscales_longest_side():
    big = np.zeros((900, 1600, 3), dtype=np.uint8)
    out, scale, resized = resize_for_analysis(big, max_side=800)
    assert resized
    assert out.shape[:2] == (450, 800)
    assert abs(scale - 0.5) < 1e-9


def test_preprocess_keeps_small_frames(load_bytes):
    pre = preprocess(load_bytes("sharp_bottle.png"))
    assert isinstance(pre, Preprocessed)
    assert (pre.width, pre.height) == (480, 640)
    assert (pre.original_width, pre.original_height) == (480, 640)
    assert pre.scale == 1.0
    assert pre.applied[:2] == ["decode", "exif_orientation"]
    assert "resize" not in pre.applied


def test_preprocess_downscales_large_frames(load_bytes):
    rgb = decode_image(load_bytes("sharp_bottle.png"))
    big = cv2.resize(rgb, (960, 1280), interpolation=cv2.INTER_CUBIC)
    pre = preprocess(_png_bytes(big), VisionConfig(max_side=640))
    assert (pre.width, pre.height) == (480, 640)
    assert (pre.original_width, pre.original_height) == (960, 1280)
    assert "resize" in pre.applied


def test_optional_enhancements_recorded(load_bytes):
    pre = preprocess(load_bytes("sharp_bottle.png"), VisionConfig(clahe=True, denoise=True))
    assert "clahe" in pre.applied and "denoise" in pre.applied


def test_exif_orientation_is_applied():
    # Stored as 300x120 landscape with EXIF orientation 6 -> displayed 120x300.
    array = np.zeros((120, 300, 3), dtype=np.uint8)
    array[:, :, 0] = 200
    image = Image.fromarray(array)
    exif = image.getexif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)

    rgb = decode_image(buffer.getvalue())
    assert rgb.shape == (300, 120, 3)


def test_crop_normalized_shape(load_bytes):
    rgb = decode_image(load_bytes("sharp_bottle.png"))
    crop = crop_normalized(rgb, BBox(x=0.25, y=0.5, w=0.5, h=0.25))
    assert crop.shape == (160, 240, 3)


def test_enhance_for_ocr_returns_gray(load_bytes):
    rgb = decode_image(load_bytes("sharp_bottle.png"))
    enhanced = enhance_for_ocr(rgb)
    assert enhanced.shape == rgb.shape[:2]
    assert enhanced.dtype == np.uint8
    assert enhanced.ndim == 2
