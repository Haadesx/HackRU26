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
