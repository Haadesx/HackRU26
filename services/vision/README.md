# PI-1 VISION — `services/vision/**` (owner: Atlas)

Branch `feat/vision-atlas`, worktree `.worktrees/pi-1-vision`.

## Deliverables

1. **Image preprocessing** — decode JPEG/PNG bytes, EXIF orientation fix, resize policy,
   optional CLAHE/denoise. Deterministic, CPU-only by default.
2. **Frame-quality evaluation** — blur (variance-of-Laplacian), exposure (luma
   histogram), glare (saturated-pixel ratio). Output `usable`, scores in `[0,1]`,
   and human camera guidance strings (e.g. "Hold the bottle steady").
3. **Bottle detection** — YOLO-class detector behind an adapter interface. Must run
   without CUDA on a dev Mac (fallback: color/edge heuristic detector) and use CUDA
   when available. Provide `model_path` config; never bundle weights in git.
4. **Label localization** — bbox of the label region on the detected bottle.
5. **Camera guidance** — derive from quality + detection + label size.

## Internal interface (preferred; adjust via Bus request)

```python
# services/vision/pipeline.py
def analyze_frame(image_bytes: bytes, hints: dict | None = None) -> "VisionResult": ...
# VisionResult (pydantic): quality: FrameQuality-ish dict, bottle: {detected, confidence, bbox},
# label: {detected, confidence, bbox}, guidance: list[str], timing: dict
```

## Acceptance criteria

- `pytest services/vision` green on Mac CPU, no network.
- Synthetic fixtures under `services/vision/tests/fixtures/` (generated, small).
- Blurry/dark frames produce `acceptable=False` + guidance; sharp frames pass.
- `analyze_frame` is import-callable by the API with no GPU present.
- Report SHA + test output to Apollo via Bus.

## Rules

- Do not edit `services/api`, `services/ocr`, `services/vlm`, or `contracts/`.
- No real drug labels; use synthetic images you generate.

## Implemented surface (feat/vision-atlas)

```python
from services.vision import analyze_frame

result = analyze_frame(jpeg_bytes, hints={"max_side": 1280, "detector": "auto"})
```

- `result.quality` — `FrameQuality`: `acceptable`, `score`, `blur`/`exposure`/`glare`
  sub-scores in `[0,1]`, quality-only `guidance`.
- `result.bottle` — `Bottle`: `detected`, `confidence`, normalized `bbox`.
- `result.label` — `Label`: `detected`, `confidence`, normalized `bbox`.
- `result.guidance` — ordered camera guidance (quality fixes first, then framing).
- `result.timing` — `total_ms` plus per-stage `stages` (`preprocess`, `quality`, `detect`, `label`).
- `result.detector` — detector actually used (`yolo` or `heuristic`).

Recognized `hints`: `max_side`, `clahe`, `denoise`, `detector`
(`auto|heuristic|yolo|none`), `model_path`, `device` (`auto|cpu|cuda`). Unknown
keys are ignored so the API can pass extra metadata. No GPU is required on any path.

### Vision → OCR handoff

`analyze_frame` returns the normalized label bbox; the crop helpers turn it into
something the OCR stage can read directly:

```python
from services.vision import analyze_frame, crop_label, crop_label_array

result = analyze_frame(frame_bytes, hints)
if result.label.detected and result.label.bbox is not None:
    jpeg_bytes = crop_label(frame_bytes, result.label.bbox)                # transport / storage
    crop_bgr = crop_label_array(frame_bytes, result.label.bbox, channel_order="bgr")
    # Orion's engine: services.ocr.engine.read_text(crop_bgr)
```

- `crop_label(image_bytes, bbox, *, fmt="jpeg"|"png", quality=95, pad=0.01) -> bytes`
  decodes the original frame EXIF-safe at full resolution, clamps the box to the
  frame and encodes JPEG (default) or PNG bytes.
- `crop_label_array(image_bytes, bbox, *, channel_order="rgb"|"bgr", pad=0.01) -> np.ndarray`
  is the same crop for direct in-process OCR calls (`bgr` matches
  `services.ocr.engine.read_text`'s default).
- Prefer decoding once and calling `ocr.read_text(frame, bbox)` directly? Decode
  with `services.vision.decode_image(image_bytes)` so EXIF orientation matches the
  frame `analyze_frame` measured; a bbox is normalized against the **displayed**
  orientation, so decoding with a non-EXIF-aware decoder shifts the crop on
  rotated photos. `crop_label`/`crop_label_array` already handle this for you.
- `bbox` accepts a contract `BBox`, a `{"x","y","w","h"}` dict, a 4-tuple/list or
  an ndarray. Empty, non-finite or off-frame boxes raise `ValueError`; unsupported
  types raise `TypeError`.
- When no bottle is detected, `locate_label` falls back to a frame-level search
  (large bright low-chroma region with text-like dark edges), so flat label
  close-ups such as `samples/label_metformin.png` still produce a crop. The
  brightness gate adapts to the frame, so dim-but-readable documents (e.g.
  `samples/label_metformin_dark.png`) are found too. That path is capped at
  confidence `0.60` because it has no bottle anchor. A blur-scale structure gate
  (fraction of pixels well below the region median after a Gaussian blur) keeps
  pure sensor noise from being mistaken for a label.

Quality semantics worth knowing for integration:

- **Bright-but-readable is acceptable.** A frame whose highlights clip but that
  still contains dark content (text) and spans a wide tonal range — a well-lit
  white label close-up — is *not* flagged `too_bright`. Clipping only counts as
  overexposure when the content is lost (e.g. a blank blown-white frame).
- **Dominant saturation is exposure, not glare.** When most of the frame is
  near-saturated there is no localized specular highlight to tilt away from; the
  exposure term reports it instead.
- The `acceptable` flag is a camera-guidance signal. Readable flat labels pass;
  blurry or genuinely overexposed frames fail with guidance strings.

### Detector configuration (environment)

| Env var | Meaning |
|---|---|
| `MEDCHECK_YOLO_MODEL` | Path to YOLO weights. `.onnx` → ONNX Runtime CPU backend; `.pt` → ultralytics backend; used as the default `model_path` when hints do not set one. Unset or missing file => deterministic CPU heuristic fallback. |
| `MEDCHECK_YOLO_CONF` | Confidence threshold for both YOLO backends, default `0.25`. Invalid values fall back to the default. |

`ultralytics` (and its torch dependency) is imported lazily **only** when a
`.pt` weights path is actually configured; `import services.vision` never imports
torch, so the dev Mac stays torch-free when `MEDCHECK_YOLO_MODEL` is unset. When
the path is set and CUDA is available the `.pt` adapter uses the GPU, otherwise CPU.

### ONNX YOLO backend (recommended for real photos)

An `.onnx` model runs through ONNX Runtime on CPU — no torch needed, and it
finds bottles the color/edge heuristic misses on real photos.

```bash
export MEDCHECK_YOLO_MODEL=models/yolo11n.onnx   # or pass hints['model_path']
export MEDCHECK_YOLO_CONF=0.25                  # optional
python -m services.vision.demo path/to/photo.jpg
```

- **Weights:** Ultralytics YOLO11n, COCO-pretrained — `yolo11n.pt` (5.4 MB) from
  <https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt>,
  exported locally with `yolo export model=yolo11n.pt format=onnx simplify=True`
  → `yolo11n.onnx` (~10.9 MB fp32, output `(1, 84, anchors)`, no embedded NMS).
  The file is gitignored; never commit weights.
- **Preprocessing:** letterbox to 640×640 (pad 114), RGB, scaled to `0..1`, NCHW.
- **Postprocessing:** COCO class 39 (`bottle`), score ≥ `MEDCHECK_YOLO_CONF`
  (default 0.25), NMS IoU 0.45, boxes clipped and mapped back to normalized
  `[0,1]` frame coordinates.
- **Runtime:** `onnxruntime` CPU, one cached `InferenceSession` per process,
  `intra_op_num_threads=1` so OCR keeps CPU headroom; lazy import (ONNX Runtime
  is never imported unless a `.onnx` model is configured). Any load/run error
  degrades to the heuristic with `detector="heuristic"`.

### CLI demo

```bash
python -m services.vision.demo samples/label_metformin.png
python -m services.vision.demo path/to/frame.jpg --detector heuristic --indent 0
```

Prints a JSON summary (frame, quality, bottle, label, guidance, timing) and exits
`1` with a JSON error on stderr for unreadable/undecodable inputs.

```bash
uv pip install -p .venv -r services/vision/requirements-dev.txt
.venv/bin/python -m pytest services/vision
# Regenerate committed synthetic fixtures:
.venv/bin/python -m services.vision.tests.fixtures.generate_fixtures
```
