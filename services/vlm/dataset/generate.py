"""Generate the synthetic labeled bottle-image dataset (no real medication labels).

Renders pharmacy-style cards with Pillow, deterministically, and writes
``ground_truth.json`` next to the images. Every label says SYNTHETIC.

Usage:
    .venv/bin/python -m services.vlm.dataset.generate --out services/vlm/dataset
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

WIDTH, HEIGHT = 700, 950
BANNER = "SYNTHETIC LABEL — NOT FOR DISPENSING"
FOOTER = "Informational only. Not medical advice."

# Synthetic medications: real generic names, invented label data. Never dispensed.
MEDICATIONS: List[Dict[str, Any]] = [
    {"name": "Metformin HCl", "strength_value": 500, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Acme Pharma", "instructions": "Take 1 tablet by mouth twice daily"},
    {"name": "Lisinopril", "strength_value": 10, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Bluepeak Labs", "instructions": "Take 1 tablet by mouth once daily"},
    {"name": "Atorvastatin Calcium", "strength_value": 20, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Northstar Generics", "instructions": "Take 1 tablet by mouth at bedtime"},
    {"name": "Levothyroxine Sodium", "strength_value": 50, "strength_unit": "mcg", "form": "Tablet",
     "manufacturer": "Vertexia Labs", "instructions": "Take 1 tablet by mouth each morning before food"},
    {"name": "Amoxicillin", "strength_value": 875, "strength_unit": "mg", "form": "Capsule",
     "manufacturer": "Acme Pharma", "instructions": "Take 1 capsule by mouth every 12 hours for 7 days"},
    {"name": "Omeprazole", "strength_value": 20, "strength_unit": "mg", "form": "Capsule",
     "manufacturer": "Bluepeak Labs", "instructions": "Take 1 capsule by mouth once daily before breakfast"},
    {"name": "Amlodipine Besylate", "strength_value": 5, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Northstar Generics", "instructions": "Take 1 tablet by mouth once daily"},
    {"name": "Sertraline HCl", "strength_value": 50, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Vertexia Labs", "instructions": "Take 1 tablet by mouth once daily in the morning"},
    {"name": "Metoprolol Succinate", "strength_value": 25, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Acme Pharma", "instructions": "Take 1 tablet by mouth once daily"},
    {"name": "Gabapentin", "strength_value": 300, "strength_unit": "mg", "form": "Capsule",
     "manufacturer": "Bluepeak Labs", "instructions": "Take 1 capsule by mouth three times daily"},
    {"name": "Hydrochlorothiazide", "strength_value": 12.5, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Northstar Generics", "instructions": "Take 1 tablet by mouth once daily in the morning"},
    {"name": "Montelukast Sodium", "strength_value": 10, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Vertexia Labs", "instructions": "Take 1 tablet by mouth once daily at bedtime"},
    {"name": "Losartan Potassium", "strength_value": 50, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Acme Pharma", "instructions": "Take 1 tablet by mouth once daily"},
    {"name": "Pantoprazole Sodium", "strength_value": 40, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Bluepeak Labs", "instructions": "Take 1 tablet by mouth once daily before breakfast"},
    {"name": "Escitalopram", "strength_value": 10, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Northstar Generics", "instructions": "Take 1 tablet by mouth once daily"},
    {"name": "Prednisone", "strength_value": 5, "strength_unit": "mg", "form": "Tablet",
     "manufacturer": "Vertexia Labs", "instructions": "Take 1 tablet by mouth once daily in the morning"},
]

# Degraded captures appended after the 16 clean ones (condition, medication index).
DEGRADED: List[Tuple[str, int]] = [
    ("blur", 1), ("dark", 2), ("glare", 4), ("tilt", 6),
    ("small_text", 8), ("low_contrast", 10), ("tilt", 12), ("blur", 14),
]

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_FONT_BOLD = (True, True, True, False)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path, is_bold in zip(_FONT_CANDIDATES, _FONT_BOLD):
        if is_bold != bold:
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # older Pillow
        return ImageFont.load_default()


def _center_text(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.ImageFont,
                 fill: Tuple[int, int, int] = (20, 20, 20)) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((WIDTH - (right - left)) / 2 - left, y - top), text, font=font, fill=fill)


def render_label(med: Dict[str, Any], condition: str, rx_number: str) -> Image.Image:
    """Render one synthetic label card; `condition` controls the degradation."""
    scale = 0.62 if condition == "small_text" else 1.0
    text_color = (135, 135, 135) if condition == "low_contrast" else (20, 20, 20)

    img = Image.new("RGB", (WIDTH, HEIGHT), (250, 250, 248))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((18, 18, WIDTH - 18, HEIGHT - 18), radius=24, outline=(40, 60, 90), width=3)

    # Top warning banner — every image is explicitly synthetic.
    draw.rectangle((18, 18, WIDTH - 18, 86), fill=(30, 45, 80))
    _center_text(draw, 42, BANNER, _font(int(24 * scale), bold=True), fill=(255, 255, 255))

    _center_text(draw, 110, "MEDCHECK PHARMACY", _font(int(30 * scale), bold=True), fill=(30, 45, 80))
    _center_text(draw, 152, f"Rx #: {rx_number}   SYNTHETIC PATIENT", _font(int(20 * scale)), text_color)

    _center_text(draw, 215, med["name"], _font(int(58 * scale), bold=True), text_color)
    _center_text(
        draw, 296,
        f"{med['strength_value']:g} {med['strength_unit']}",
        _font(int(54 * scale), bold=True), text_color,
    )
    _center_text(draw, 372, med["form"].upper(), _font(int(32 * scale), bold=True), text_color)

    draw.line((70, 430, WIDTH - 70, 430), fill=(150, 150, 150), width=2)
    _center_text(draw, 448, "TAKE:", _font(int(26 * scale), bold=True), fill=(30, 45, 80))
    wrapped = textwrap.wrap(med["instructions"], width=34 if scale == 1.0 else 52)
    y = 486
    for line in wrapped[:3]:
        _center_text(draw, y, line, _font(int(30 * scale)), text_color)
        y += int(42 * scale)

    y = 640
    for line in (f"MFR: {med['manufacturer']}", "QTY: 30    REFILLS: 2",
                 "LOT: SYN-2026-001    EXP: 2028-01"):
        _center_text(draw, y, line, _font(int(24 * scale)), text_color)
        y += int(36 * scale)

    _center_text(draw, HEIGHT - 100, FOOTER, _font(int(18 * scale)), fill=(110, 110, 110))
    _center_text(draw, HEIGHT - 72, "Synthetic test fixture - not a pharmacy product.",
                 _font(int(16 * scale)), fill=(110, 110, 110))

    return _apply_condition(img, condition)


def _apply_condition(img: Image.Image, condition: str) -> Image.Image:
    if condition == "clean":
        return img
    if condition == "blur":
        return img.filter(ImageFilter.GaussianBlur(radius=1.8))
    if condition == "dark":
        dark = ImageEnhance.Brightness(img).enhance(0.42)
        return ImageEnhance.Contrast(dark).enhance(0.9)
    if condition == "glare":
        out = img.copy()
        overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.ellipse((90, 240, WIDTH - 60, 430), fill=(255, 255, 255, 105))
        od.ellipse((30, 520, 420, 700), fill=(255, 255, 255, 70))
        return Image.alpha_composite(out.convert("RGBA"), overlay).convert("RGB")
    if condition == "tilt":
        return img.rotate(3.0, expand=False, fillcolor=(250, 250, 248), resample=Image.BICUBIC)
    if condition in ("small_text", "low_contrast"):
        return img
    raise ValueError(f"unknown condition: {condition}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_dataset(out_dir: Path, seed: int = 1337) -> Dict[str, Any]:
    """Render all images + ground_truth.json. Returns the manifest dict."""
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    entries: List[Dict[str, Any]] = []
    index = 0
    plan: List[Tuple[Dict[str, Any], str]] = [(med, "clean") for med in MEDICATIONS]
    plan += [(MEDICATIONS[med_index], condition) for condition, med_index in DEGRADED]

    for med, condition in plan:
        index += 1
        rng = random.Random(seed + index)
        rx = f"SYN-{rng.randint(100000, 999999)}"
        filename = f"img_{index:03d}_{condition}.png"
        path = images_dir / filename
        render_label(med, condition, rx).save(path, format="PNG", optimize=True)
        entries.append(
            {
                "id": f"img_{index:03d}",
                "file": f"images/{filename}",
                "condition": condition,
                "rx_number": rx,
                "ground_truth": {
                    "name": med["name"],
                    "strength_value": med["strength_value"],
                    "strength_unit": med["strength_unit"],
                    "form": med["form"],
                    "manufacturer": med["manufacturer"],
                    "instructions": med["instructions"],
                },
                "sha256": _sha256(path),
            }
        )

    manifest: Dict[str, Any] = {
        "version": 1,
        "name": "medcheck-synthetic-labels",
        "seed": seed,
        "note": "Fully synthetic test fixtures. No real medication labels or patient data.",
        "count": len(entries),
        "images": entries,
    }
    (out_dir / "ground_truth.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic labeled bottle images.")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--seed", type=int, default=1337)
    args = parser.parse_args(argv)
    manifest = build_dataset(args.out, seed=args.seed)
    print(f"wrote {manifest['count']} images + ground_truth.json to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
