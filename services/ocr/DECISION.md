# OCR Stack Decision — `services/ocr` (PI-2 / Orion)

Status: **ACCEPTED** · Scope: label OCR for MedCheck (CPU inference, macOS dev +
Linux rig) · Related: `services/ocr/requirements.txt`, `services/ocr/engine.py`

## Decision

Use **`rapidocr-onnxruntime==1.4.4`** (RapidOCR on ONNX Runtime) as the pinned,
isolated OCR stack.

Verified installed set (macOS arm64, Python 3.11.15):

| Package | Version | Measured footprint (site-packages) |
|---|---|---|
| rapidocr-onnxruntime | 1.4.4 | ~16 MB (includes PP-OCRv4 ONNX models) |
| onnxruntime | 1.31.0 | ~75 MB |
| opencv-python | 5.0.0.93 | ~119 MB (headless not required) |
| numpy | 2.4.6 | ~24 MB |
| pyclipper / shapely / pyyaml / six | 1.4.0 / 2.2.0 / 6.0.3 / 1.17.0 | small |
| pytest / pillow (tests only) | 9.1.1 / 12.3.0 | small |

License: Apache-2.0. No torch, no CUDA, no model download step.

## Comparison

| Criterion | rapidocr-onnxruntime ✅ | easyocr | paddleocr |
|---|---|---|---|
| Runtime | ONNX Runtime | PyTorch + torchvision | PaddlePaddle |
| Install weight | ~230 MB total deps | torch stack ≈ GBs; more on macOS | paddle wheel is large; macOS arm64 support historically inconsistent |
| Model acquisition | **bundled in the wheel** (`models/ch_PP-OCRv4_{det,rec}_infer.onnx`, `ch_ppocr_mobile_v2.0_cls_infer.onnx`) | downloads CRAFT + CRNN weights from the internet on first run (~100 MB) | downloads det/rec models on first run |
| Offline after setup | **yes** (verified) | only after first-run download and cache warm-up | only after first-run download and cache warm-up |
| CPU latency | ~0.25 s det + ~0.13 s rec for a 640×220 label on M-series | slower CPU detector/recognizer | comparable to easyocr CPU, heavier startup |
| Output granularity | line-level text + 4-point boxes + score | word/line boxes + score | line/word boxes + score |
| Dependency risk on macOS + Linux | low (wheels for both) | moderate (torch per-platform wheels) | high (paddle wheel availability/pins) |
| Extra features | sufficient: detection + recognition + angle classifier | 80+ languages | layout/table analysis in 3.x (not needed here) |
| License | Apache-2.0 | Apache-2.0 | Apache-2.0 |

## Why rapidocr-onnxruntime wins for MedCheck

1. **Offline requirement** — the task requires CPU inference with no network after
   setup. RapidOCR bundles its PP-OCRv4 models in the wheel; easyocr and paddleocr
   fetch weights at first use.
2. **Isolation** — no torch/paddle in the MedCheck environment. GPU policy
   (AGENTS.md §5) and the shared RTX 5090 remain untouched; OCR is CPU-only.
3. **Footprint and install speed** — installs cleanly on macOS arm64 now and has
   x86_64 Linux wheels for the rig; easyocr/paddleocr are an order of magnitude
   heavier to install.
4. **Sufficient accuracy for label lines** — measured on the synthetic set:
   extraction 33/33 name/strength/form (text layer) and 8/8 name, 8/8 strength,
   8/8 form end-to-end through rendered images.

## Considered alternatives (not installed by default)

- **easyocr** — strong accuracy and broad language coverage, but torch + first-run
  weight downloads break the offline-after-setup requirement. Documented fallback
  if the rig exposes a rapidocr incompatibility; it would live behind the same
  `services/ocr/engine.read_text` interface as a separate optional requirements file.
- **paddleocr** — richer layout/table tooling in 3.x, but the paddle wheel is heavy
  and macOS arm64 support is inconsistent; label OCR does not need those features.

## Consequences / risks and mitigations

| Risk | Mitigation |
|---|---|
| RapidOCR is line-level (no word boxes) | Contract needs `label.text` + a box; `OcrLine.bbox` covers it. `OcrLine.words` is reserved and empty until a backend provides word boxes. |
| OCR merges/splits words (`LEVOTHYROXINE100MCG`, `gTablets`, `100 r / mcg`) | Extractor handles glued tokens, cross-line unit joins, and mid-word letter runs; all covered by tests. Raw text stays verbatim. |
| Digit/letter confusions (`Metform1n`, `5O0mg`, `2OMG`) | Lexicon-assisted normalization only proves names present in the source; strength parsing maps confusable digits. Values keep `confidence` + `source: "ocr"`; `raw` keeps the verbatim substring. |
| Linux rig differences | ONNX Runtime ships Linux x86_64 wheels; install with the same `requirements.txt`. CPU-only, no GPU window required. |

## Reproduction

```bash
# in the worktree
uv venv .venv --python 3.11
uv pip install -r services/ocr/requirements.txt
.venv/bin/python -m pytest services/ocr -q          # 25 tests, accuracy tables printed
```

Offline check (no network used): `read_text` on a rendered label returned
`METFORMINHCL / 500mg / TABLETS`-style verbatim text with normalized boxes while the
venv's bundled models resolved from
`.venv/lib/python3.11/site-packages/rapidocr_onnxruntime/models/`.
