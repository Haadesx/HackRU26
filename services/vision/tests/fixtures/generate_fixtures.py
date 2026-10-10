"""Deterministic synthetic fixtures for the vision tests.

Regenerate with:
    .venv/bin/python -m services.vision.tests.fixtures.generate_fixtures

Images are small (480x640 PNG with low-frequency texture) and committed so the
test suite runs offline. Labels are fictional ("EXAMPLEX"); no real medication
names, no patient data.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

FIXTURE_DIR = Path(__file__).resolve().parent
WIDTH, HEIGHT = 480, 640

#: Ground-truth geometry in pixels, (x0, y0, x1, y1).
BOTTLE_RECT = (150, 85, 330, 560)  # includes cap and body
LABEL_RECT = (175, 270, 305, 465)

FONT = cv2.FONT_HERSHEY_SIMPLEX


def _background(rng: np.random.Generator) -> np.ndarray:
    # Smooth low-frequency texture: compresses well as PNG and keeps the
    # synthetic scene deterministic (no per-pixel noise).
    coarse = rng.integers(130, 200, size=(16, 12, 3), dtype=np.uint8)
    background = cv2.resize(coarse, (WIDTH, HEIGHT), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    return np.clip(background, 0, 255).astype(np.uint8)


def _draw_bottle(scene: np.ndarray) -> np.ndarray:
    # Cap with ridges.
    cv2.rectangle(scene, (208, 85), (272, 122), (186, 72, 58), -1)
    for x in range(210, 272, 8):
        cv2.line(scene, (x, 87), (x, 120), (150, 52, 44), 1)
    # Neck.
    cv2.rectangle(scene, (218, 118), (262, 175), (198, 146, 78), -1)
    # Body with a horizontal shading gradient and a dark outline.
    cv2.rectangle(scene, (150, 168), (330, 560), (206, 148, 72), -1)
    body = scene[168:560, 150:330].astype(np.float32)
    gradient = np.linspace(0.82, 1.14, body.shape[1], dtype=np.float32)
    body *= gradient[None, :, None]
    scene[168:560, 150:330] = np.clip(body, 0, 255).astype(np.uint8)
    cv2.rectangle(scene, (150, 168), (330, 560), (120, 84, 40), 2)
    # Label.
    lx0, ly0, lx1, ly1 = LABEL_RECT
    cv2.rectangle(scene, (lx0, ly0), (lx1, ly1), (242, 242, 238), -1)
    cv2.rectangle(scene, (lx0, ly0), (lx1, ly1), (168, 168, 164), 2)
    cv2.line(scene, (lx0 + 6, ly0 + 38), (lx1 - 6, ly0 + 38), (120, 120, 120), 1)
    cv2.putText(scene, "EXAMPLEX", (lx0 + 10, ly0 + 28), FONT, 0.52, (35, 35, 40), 1, cv2.LINE_AA)
    cv2.putText(scene, "500 mg", (lx0 + 10, ly0 + 70), FONT, 0.62, (35, 35, 40), 1, cv2.LINE_AA)
    cv2.putText(scene, "TAKE 1 TABLET", (lx0 + 10, ly0 + 125), FONT, 0.42, (45, 45, 50), 1, cv2.LINE_AA)
    cv2.putText(scene, "BY MOUTH DAILY", (lx0 + 10, ly0 + 150), FONT, 0.40, (45, 45, 50), 1, cv2.LINE_AA)
    cv2.putText(scene, "LOT E-0001", (lx0 + 10, ly0 + 178), FONT, 0.38, (45, 45, 50), 1, cv2.LINE_AA)
    return scene


def _sharp_scene(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return _draw_bottle(_background(rng))


def _with_glare(scene: np.ndarray) -> np.ndarray:
    layer = np.zeros_like(scene)
    cv2.ellipse(layer, (252, 330), (52, 88), 0, 0, 360, (255, 255, 255), -1)
    layer = cv2.GaussianBlur(layer, (0, 0), 8)
    out = np.maximum(scene, layer)
    cap_highlight = np.zeros_like(scene)
    cv2.ellipse(cap_highlight, (232, 100), (14, 9), 0, 0, 360, (250, 250, 250), -1)
    cap_highlight = cv2.GaussianBlur(cap_highlight, (0, 0), 3)
    return np.maximum(out, cap_highlight)


def _normalized(rect) -> dict:
    x0, y0, x1, y1 = rect
    return {
        "x": round(x0 / WIDTH, 6),
        "y": round(y0 / HEIGHT, 6),
        "w": round((x1 - x0) / WIDTH, 6),
        "h": round((y1 - y0) / HEIGHT, 6),
    }


def build_variants() -> dict:
    sharp = _sharp_scene()
    return {
        "sharp_bottle.png": sharp,
        "blurry_bottle.png": cv2.GaussianBlur(sharp, (0, 0), 4.0),
        "dark_bottle.png": np.clip(sharp.astype(np.float32) * 0.16, 0, 255).astype(np.uint8),
        "bright_bottle.png": np.clip(sharp.astype(np.float32) * 1.10 + 58.0, 0, 255).astype(np.uint8),
        "glare_bottle.png": _with_glare(sharp),
        "no_bottle.png": _background(np.random.default_rng(99)),
    }


def main() -> None:
    png_params = [cv2.IMWRITE_PNG_COMPRESSION, 9]
    labels = {}
    for name, image in build_variants().items():
        cv2.imwrite(str(FIXTURE_DIR / name), image, png_params)
        if name == "no_bottle.png":
            labels[name] = {"bottle_bbox": None, "label_bbox": None}
        else:
            labels[name] = {"bottle_bbox": _normalized(BOTTLE_RECT), "label_bbox": _normalized(LABEL_RECT)}
        print(f"wrote {name} ({image.shape[1]}x{image.shape[0]})")
    (FIXTURE_DIR / "labels.json").write_text(json.dumps(labels, indent=2, sort_keys=True) + "\n")
    print("wrote labels.json")


if __name__ == "__main__":
    main()
