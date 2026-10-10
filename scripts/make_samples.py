#!/usr/bin/env python3
"""Regenerate the synthetic sample labels (reproducible; no real patient data).

Usage: .venv-full/bin/python scripts/make_samples.py
Outputs: samples/*.png  (sharp, blurry, dark, long-label thirds)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"
FONT = "/System/Library/Fonts/Helvetica.ttc"


def font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def base_label(name: str, strength: str, form: str, instruction: str, *, qty: str = "30",
               refills: str = "2", pharmacy: str = "Demo Pharmacy", phone: str = "(555) 010-2030",
               prescriber: str = "Dr. A. Demo", w: int = 900, h: int = 740) -> Image.Image:
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, w - 20, h - 20], outline="black", width=3)
    d.text((60, 60), f"{name} {strength}", font=font(54), fill="black")
    d.text((60, 140), f"{form}  |  Rx only", font=font(38), fill="black")
    d.text((60, 220), instruction, font=font(36), fill="black")
    d.text((60, 330), f"QTY {qty}", font=font(40), fill="black")
    d.text((60, 400), f"Refills: {refills}", font=font(38), fill="black")
    d.text((60, 470), f"{pharmacy}", font=font(34), fill="black")
    d.text((60, 525), f"Tel: {phone}", font=font(32), fill="black")
    d.text((60, 585), f"Prescriber: {prescriber}", font=font(32), fill="black")
    d.text((60, 660), "SYNTHETIC TEST LABEL - NOT FOR MEDICAL USE", font=font(24), fill="gray")
    return img


def long_label() -> Image.Image:
    w, h = 1800, 1200
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, w - 20, h - 20], outline="black", width=4)
    d.text((70, 70), "HYDROCHLOROTHIAZIDE 25 mg TABLETS", font=font(54), fill="black")
    d.text((70, 180), "Take 1 tablet by mouth once daily in the morning.", font=font(40), fill="black")
    d.text((70, 300), "Swallow whole with a glass of water.", font=font(40), fill="black")
    d.text((70, 420), "WARNING: Do not take if pregnant or breastfeeding.", font=font(40), fill="black")
    d.text((70, 540), "Keep out of reach of children. Store below 30C.", font=font(40), fill="black")
    d.text((70, 660), "QTY 30", font=font(44), fill="black")
    d.text((70, 740), "Refills: 1", font=font(40), fill="black")
    d.text((70, 820), "Demo Pharmacy  Tel: (555) 010-2030", font=font(34), fill="black")
    d.text((70, 890), "Prescriber: Dr. A. Demo", font=font(34), fill="black")
    d.text((70, 980), "Rx only - synthetic test label", font=font(30), fill="gray")
    return img


def save_degraded(img: Image.Image, name: str) -> None:
    img.save(OUT / f"{name}.png")
    img.filter(ImageFilter.GaussianBlur(6)).save(OUT / f"{name}_blurry.png")
    from PIL import ImageEnhance

    ImageEnhance.Brightness(img).enhance(0.35).save(OUT / f"{name}_dark.png")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    metformin = base_label("METFORMIN HCl", "500 mg", "TABLETS",
                           "Take 1 tablet by mouth twice daily with meals.")
    save_degraded(metformin, "label_metformin")
    lisinopril = base_label("LISINOPRIL", "10 mg", "TABLETS", "Take 1 tablet by mouth once daily.",
                            qty="90", refills="3", pharmacy="Sample Rx", phone="(555) 010-4040",
                            prescriber="Dr. B. Sample")
    save_degraded(lisinopril, "label_lisinopril")

    long = long_label()
    long.save(OUT / "long_label_full.png")
    for name, x0, x1 in (("left", 0, 900), ("middle", 450, 1350), ("right", 900, 1800)):
        long.crop((x0, 0, x1, 1200)).save(OUT / f"long_label_{name}.png")

    print("wrote samples to", OUT)


if __name__ == "__main__":
    main()
