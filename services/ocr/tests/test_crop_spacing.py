"""M10: crop-path spacing regression + glue-tolerant cadence detection."""

from __future__ import annotations

import numpy as np
import pytest

from services.ocr.engine import _prepare_crop, read_text
from services.ocr.extract import extract_fields
from services.ocr.types import BBox

METFORMIN_PATH = "samples/label_metformin.png"
# The exact label bbox from Varesh's real-scan report / API crop path.
METFORMIN_BBOX = BBox(x=0.0256, y=0.0311, w=0.95, h=0.9392)


def _require_ocr():
    pytest.importorskip("rapidocr_onnxruntime")


# --------------------------------------------------------------------------- #
# Crop path regression (the M10 bug)
# --------------------------------------------------------------------------- #


def test_crop_path_preserves_spacing_and_schedule():
    _require_ocr()
    result = read_text(METFORMIN_PATH, bbox=METFORMIN_BBOX)
    extraction = extract_fields(result.raw_text)

    instruction_texts = [
        item.text for item in extraction.instructions if item.kind in {"dose", "route", "frequency"}
    ]
    spacing_ok = any(" " in text for text in instruction_texts)
    schedule = extraction.label_meta["schedule_times"].value

    assert spacing_ok or schedule == "08:00, 20:00", result.raw_text
    assert schedule == "08:00, 20:00", result.raw_text
    assert extraction.dose_quantity == 1.0


def test_crop_path_pharmacy_name_spacing_or_normalized():
    _require_ocr()
    extraction = extract_fields(read_text(METFORMIN_PATH, bbox=METFORMIN_BBOX).raw_text)
    pharmacy = extraction.label_meta["pharmacy_name"].value
    assert pharmacy is not None
    assert " " in pharmacy or "".join(pharmacy.split()).casefold() == "demopharmacy"


def test_crop_path_keeps_quantity_and_refills_separated():
    _require_ocr()
    extraction = extract_fields(read_text(METFORMIN_PATH, bbox=METFORMIN_BBOX).raw_text)
    assert extraction.label_meta["quantity_start"].value == "30"
    assert extraction.label_meta["refills_remaining"].value == "2"


@pytest.mark.parametrize(("part", "expected"), [("left", "08:00"), ("middle", "08:00"), ("right", None)])
def test_long_label_thirds_crop_path_cadence(part, expected):
    _require_ocr()
    from PIL import Image

    image = np.asarray(Image.open(f"samples/long_label_{part}.png").convert("RGB"))
    extraction = extract_fields(read_text(image, bbox=BBox(0, 0, 1, 1), channel_order="rgb").raw_text)
    assert extraction.label_meta["schedule_times"].value == expected


def test_downscaled_crop_keeps_spacing_or_resolves_cadence():
    _require_ocr()
    from PIL import Image

    image = Image.open("samples/long_label_full.png").convert("RGB")
    small = np.asarray(image.resize((image.width // 3, image.height // 3), Image.LANCZOS))
    result = read_text(small, bbox=BBox(0, 0, 1, 1), channel_order="rgb")
    extraction = extract_fields(result.raw_text)

    assert extraction.name.value == "Hydrochlorothiazide"
    instruction_texts = [
        item.text for item in extraction.instructions if item.kind in {"dose", "route", "frequency"}
    ]
    spacing_ok = any(" " in text for text in instruction_texts)
    schedule = extraction.label_meta["schedule_times"].value
    assert spacing_ok or schedule == "08:00"
    assert schedule == "08:00", result.raw_text


def test_prepare_crop_uses_lanczos_only_without_contrast_enhancement():
    import cv2

    gradient = np.tile(np.arange(200, dtype=np.uint8), (100, 1))[:, :, None].repeat(3, axis=2)
    prepared, _, _ = _prepare_crop(gradient)
    expected = cv2.resize(
        gradient,
        (prepared.shape[1], prepared.shape[0]),
        interpolation=cv2.INTER_LANCZOS4,
    )
    assert np.array_equal(prepared, expected)


# --------------------------------------------------------------------------- #
# Glue-tolerant cadence patterns
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Take 1 tablet by mouth twice daily", "08:00, 20:00"),
        ("Take1tabletbymouthtwicedaily", "08:00, 20:00"),
        ("Take 1 tablet by mouth once daily", "08:00"),
        ("Take1tabletbymouthoncedaily", "08:00"),
        ("Take 1 tablet three times daily", "08:00, 14:00, 20:00"),
        ("Take1tabletthreetimesdaily", "08:00, 14:00, 20:00"),
        ("Take 1 tablet at bedtime", "20:00"),
        ("Take1tabletatbedtime", "20:00"),
    ],
)
def test_glued_cadence_still_resolves(raw, expected):
    assert extract_fields(raw).label_meta["schedule_times"].value == expected


@pytest.mark.parametrize(
    "raw",
    [
        "Take 1 tablet once weekly",
        "Take1tabletonceweekly",
        "Take 1 tablet every other day",
        "Take1tableteveryotherday",
        "Take 1 tablet every 12 hours",
        "Take1tabletevery12hours",
        "Take 1 tablet as needed",
        "Take1tabletasneeded",
    ],
)
def test_glued_unsupported_cadence_stays_none(raw):
    assert extract_fields(raw).label_meta["schedule_times"].value is None
