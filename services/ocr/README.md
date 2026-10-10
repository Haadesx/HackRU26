# PI-2 OCR — `services/ocr/**` (owner: Orion)

Branch `feat/ocr-orion`, worktree `.worktrees/pi-2-ocr`.

## Deliverables

1. **OCR dependency compatibility** — choose and pin an OCR stack that installs cleanly
   on macOS (dev) and Linux (rig). Evaluate `rapidocr-onnxruntime` (preferred: no torch,
   small download), `easyocr`, `paddleocr`, and note the decision + versions in
   `services/ocr/DECISION.md`. Keep it isolated in this package.
2. **OCR inference** — read a label crop (or full frame + bbox) into raw text with
   per-line/word boxes when available. Preserve raw text verbatim.
3. **Medication-name + strength extraction** —
   - `name`: e.g. "Metformin", "lisinopril"
   - `strength`: number + unit, e.g. `500 mg` (never confuse with quantity per dose)
   - `form`: tablet/capsule/solution when visible
   - keep `source="ocr"` and per-field confidence.
4. **Dosage-instruction parsing** — split raw text into `dose|frequency|route|duration|warning|other`
   items. Preserve `raw_text`. Never invent instructions that are not in the source text.
5. **Field-level accuracy tests** — a labeled synthetic set (≥20 lines) with expected
   name/strength; report precision/recall in test output.

## Internal interface (preferred)

```python
# services/ocr/engine.py
def read_text(image: "np.ndarray", bbox: "BBox|None" = None) -> "OcrResult": ...
# services/ocr/extract.py
def extract_fields(raw_text: str, hints: dict | None = None) -> "Extraction": ...
```

Both must work on macOS CPU with no network after setup.

## Acceptance criteria

- `pytest services/ocr` green; accuracy table printed for the synthetic set.
- Extraction tests cover: strength vs quantity-per-dose ambiguity, casing, OCR noise
  ("Metform1n", "5O0mg"), and multi-line labels.
- No fabricated drug names in fixtures beyond standard synthetic names.
- Report SHA + test output to Apollo via Bus.
