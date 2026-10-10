"""End-to-end OCR inference tests on rendered synthetic labels.

These exercise the real pinned backend (RapidOCR / ONNX Runtime) on images
rendered from the synthetic fixture set: image -> raw text + boxes -> fields.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest

pytest.importorskip("rapidocr_onnxruntime")

from services.ocr.engine import BACKEND_NAME, is_available, read_text
from services.ocr.extract import extract_fields
from services.ocr.types import BBox

SERVICE_DIR = pathlib.Path(__file__).resolve().parents[1]
E2E_ARTIFACT_PATH = SERVICE_DIR / "artifacts" / "ocr_e2e_report.txt"

RENDER_IDS = ("L01", "L02", "L03", "L10", "L25", "L29", "L30", "L31")


def _render(lines: list[str]) -> np.ndarray:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=36)
    image = Image.new("RGB", (1000, 70 + 44 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    y = 26
    for line in lines:
        draw.text((28, y), line, font=font, fill=(15, 15, 15))
        y += 44
    return np.asarray(image)


def _norm(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def test_backend_available():
    assert is_available()
    assert BACKEND_NAME == "rapidocr-onnxruntime"


def test_read_text_is_verbatim_and_boxes_are_normalized():
    result = read_text(_render(["METFORMIN HCL", "500 mg TABLETS"]), channel_order="rgb")
    assert result.raw_text
    assert result.raw_text == "\n".join(line.text for line in result.lines)
    assert result.lines
    assert result.engine == BACKEND_NAME
    assert result.image_size == (1000, 158)
    for line in result.lines:
        assert line.bbox is not None
        bbox = line.bbox
        assert 0.0 <= bbox.x <= 1.0 and 0.0 <= bbox.y <= 1.0
        assert 0.0 <= bbox.x2 <= 1.0 + 1e-9 and 0.0 <= bbox.y2 <= 1.0 + 1e-9
        assert line.words == ()  # line-level backend


def test_bbox_crop_maps_boxes_back_to_full_frame():
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=30)
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.text((150, 130), "METFORMIN 500 mg TABLETS", font=font, fill=(0, 0, 0))
    arr = np.asarray(image)

    crop = BBox(x=100 / 900, y=90 / 300, w=700 / 900, h=120 / 300)
    result = read_text(arr, bbox=crop, channel_order="rgb")
    assert "METFORMIN" in result.raw_text.upper()
    for line in result.lines:
        assert line.bbox is not None
        assert line.bbox.x >= crop.x - 0.02
        assert line.bbox.x2 <= crop.x2 + 0.02
        assert line.bbox.y >= crop.y - 0.02
        assert line.bbox.y2 <= crop.y2 + 0.02


def test_end_to_end_field_accuracy_on_rendered_labels(synthetic_labels):
    by_id = {entry["id"]: entry for entry in synthetic_labels["labels"]}
    rows: list[str] = []
    name_hits = strength_hits = form_hits = 0

    for label_id in RENDER_IDS:
        entry = by_id[label_id]
        result = read_text(_render(entry["lines"]), channel_order="rgb")
        extraction = extract_fields(result.raw_text)
        expect = entry["expect"]

        name_ok = extraction.name.value is not None and _norm(extraction.name.value) == _norm(expect["name"])
        strength_ok = (
            extraction.strength.value == expect["strength_value"]
            and extraction.strength.unit == expect["strength_unit"]
        )
        form_ok = extraction.form.value == expect["form"]
        name_hits += int(name_ok)
        strength_hits += int(strength_ok)
        form_hits += int(form_ok)
        ocr_text = result.raw_text.replace("\n", " / ")
        rows.append(
            f"{label_id:<4} ocr={ocr_text[:52]:<52.52} "
            f"name={extraction.name.value or '-'} strength="
            f"{extraction.strength.value if extraction.strength.value is not None else '-'}"
            f"{extraction.strength.unit or ''} form={extraction.form.value or '-'}"
        )

    total = len(RENDER_IDS)
    report = "\n".join(
        [
            "MedCheck OCR — end-to-end accuracy on rendered synthetic labels",
            "pipeline: PIL render -> services/ocr/engine.read_text (RapidOCR) -> services/ocr/extract.extract_fields",
            f"labels: {total}",
            "",
            *rows,
            "-" * 96,
            f"name {name_hits}/{total}  strength {strength_hits}/{total}  form {form_hits}/{total}",
        ]
    )
    E2E_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    E2E_ARTIFACT_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)

    # Rendered synthetic labels are clean input; allow a small margin for OCR merges.
    assert name_hits >= total - 1, report
    assert strength_hits >= total - 1, report
    assert form_hits >= total - 2, report
