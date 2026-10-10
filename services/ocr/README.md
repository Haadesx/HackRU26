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

---

## Implementation notes (PI-2 Orion)

Stack: `rapidocr-onnxruntime==1.4.4` on ONNX Runtime, CPU-only, models bundled —
see [`DECISION.md`](DECISION.md).

### Layout

```
services/ocr/
  engine.py      read_text(image, bbox=None, *, channel_order="bgr") -> OcrResult
  extract.py     extract_fields(raw_text, hints=None) -> Extraction
                 parse_instructions(raw_text) -> list[InstructionItem]
  matcher.py     match_candidates(fields, candidates, *, threshold=0.75) -> list[Candidate]
  types.py       BBox / OcrResult / FieldString / FieldStrength / Extraction (contract v1 shaped)
  lexicon.py     standard generic names, salts, dosage forms, units, OCR-confusion matching
  fixtures/synthetic_labels.json   33 labeled synthetic lines (clean + noisy + multi-line)
  tests/         field extraction, instruction parsing, accuracy table, matcher, end-to-end OCR
  artifacts/     generated accuracy tables (also echoed by pytest at session end)
```

### Run

```bash
uv venv .venv --python 3.11
uv pip install -r services/ocr/requirements.txt
.venv/bin/python -m pytest services/ocr -q
```

Latest results: **133 passed**; synthetic-set field accuracy 33/33 for name,
strength and form (precision = recall = 1.000); end-to-end through rendered
images 8/8 name, 8/8 strength, 8/8 form.

### Pharmacy-label metadata (contract v1.3)

`Extraction.label_meta_contract()` returns `label_meta` with
`quantity_start`, `refills_remaining`, `pharmacy_name`, `pharmacy_phone`,
`prescriber`, `schedule_times`, each a `{value, confidence, source}` field.

- `quantity_start`: `QTY`/`Quantity` + digits verbatim (`QTY 30` -> `"30"`);
  digit/letter noise such as `QTY 3O` is not guessed (absent).
- `refills_remaining`: `Refills: 2` -> `"2"`; `No refills` -> `"0"`.
- `pharmacy_name`: labeled `Pharmacy: X`, a line containing "Pharmacy", or the
  positional fallback of the line above a `Tel:` line (`Sample Rx`, conf 0.6).
- `pharmacy_phone`: labeled `Tel:`/`Phone:`/`Ph:` (conf 0.85) or a generic
  `(555) 010-2030` pattern (conf 0.6).
- `prescriber`: `Prescriber: ...` (conf 0.85) or a `Dr. ...` line (conf 0.7).
- `schedule_times`: **derived** from the parsed frequency at base x 0.8
  (conf `0.72`): once daily -> `08:00`; twice -> `08:00, 20:00`; three times ->
  `08:00, 14:00, 20:00`; bedtime -> `20:00`. Weekly, every-N-hours,
  every-other-day and PRN stay `None` (never guessed).
- All values except the derived `schedule_times` are verbatim substrings of the
  recognized text; missing fields use the none shape.
- Multi-frame fusion merges `label_meta` by highest confidence.

### Real-photo quality (M8)

Small/distant labels (Varesh's real scan returned a lone `日` at conf 0.90):

- **Bbox-crop upscaling:** when OCR runs on a bbox crop whose long side is
  < `engine.MIN_CROP_LONG_SIDE` (1000 px), the crop is upscaled with Lanczos
  (capped at ×4) plus a mild CLAHE contrast lift, then recognized. Line boxes are
  divided by the actual scale before mapping back to full-frame normalized
  coordinates. The no-bbox full-frame path is unchanged.
- **Degenerate-text sanity:** text with no ASCII letters or fewer than three
  alphabetic characters total (`日`, `||`, punctuation-only) is treated as unread.
  `OcrResult.raw_text` stays verbatim and `OcrResult.readable` is `False`, but
  `OcrResult.confidence` returns `0.0` and `extract_fields`/`parse_instructions`
  return empty results — no junk `other` instruction items.

Verified: a 25 %-downscaled `samples/long_label_full.png` (450×300) run through
`read_text(..., bbox=full)` still recovers `HYDROCHLOROTHIAZIDE 25 mg` with all
boxes inside `[0, 1]`; `extract_fields("日")` and `parse_instructions("日")`
return empty.

### Multi-frame fusion (contract v1.2)

`fuse_extractions(extractions) -> FusionResult(extraction, frames_used,
conflicts, per_frame_confidence)` combines overlapping per-frame `Extraction`s
from a label larger than one camera frame (`POST /v1/scan/multi`).

- name/strength/form/manufacturer: highest-confidence non-null wins; distinct
  values at confidence >= 0.5 append `<field>_conflict` to `conflicts`
  (strength compared as normalized `(value, unit)`).
- dose: highest-confidence non-null `quantity+unit`; distinct pairs append
  `dose_conflict`. A missing dose in another frame is not a conflict.
- instructions: union of parsed items deduped by lowercased/space-collapsed
  text, first-seen order; the kept verbatim text comes from the
  highest-confidence frame (ties keep the first).
- `raw_text`: each frame's text verbatim, joined by `\n--- frame N ---\n` markers.
- empty input raises `ValueError`; a single frame passes through with
  `frames_used=1` and no markers.
- every output value and instruction text is copied from a source frame — fusion
  never fabricates text.

Verified on `samples/long_label_{left,middle,right}.png`: fused name
Hydrochlorothiazide (0.95), strength 25 mg, form tablet, dose 1 tablet,
instructions containing the morning/water/warning content, no conflicts.

### Structured per-dose quantity (contract v1.1)

`Extraction` carries `dose_quantity`, `dose_unit`, `dose_confidence`, `dose_source`;
`dose_contract()` returns the frozen `instructions.dose` shape
`{quantity, unit, confidence, source}`, also embedded as
`instructions_contract()["dose"]` for direct API composition.

- Parsed only from dose segments (a `dose` instruction item, or a word/fraction
  quantity such as `half tablet`). Warning text is skipped.
- Units are normalized to lowercase singular (`CAPSULES` -> `capsule`, `caps` ->
  `capsule`); volumes (`ml`, `tsp`, `tbsp`) are supported.
- Word/fraction quantities are supported: `half`/`quarter`/`one`..`six`,
  `one and a half`, `1/2`, `1 1/2`, `½`.
- Ambiguous ranges (`1 to 2 tablets`, `1-2 tablets`) yield `quantity=None` — never
  a guessed number. Package counts (`90 tablets`, `30 capsules per bottle`) are
  never doses.
- No dose stated -> `{quantity: null, unit: null, confidence: 0.0, source: "none"}`.
- Confidence: numeric `0.9`, fraction `0.85`, word `0.75`.

### Registered-candidate matching

`match_candidates(fields, candidates, *, threshold=0.75)` matches an `Extraction`
(or a `{name, strength}` dict) against caller-supplied registered candidates and
returns `services.common.contract.Candidate` models, best first, `source="registry"`.

- Score = `0.70 * name_similarity + 0.30 * strength_points` when both sides carry
  a strength; name similarity is scaled by `0.90` when strength cannot be compared.
- Name similarity handles case, spacing, glued tokens, and OCR confusions
  (`Metform1n`, `L1SINOPRIL`); names below `0.55` are not considered matches.
- Strength points are `1.0` only for an exact match after unit conversion
  (`mg`/`mcg`/`g` mass, `ml`, `IU`, `%`); a mismatch scores `0.0`, which drops an
  otherwise exact name below the default threshold.
- Candidates are only ever the input list; the matcher never invents or looks up
  a name. Below-threshold candidates are omitted.
- `fields` coercion accepts an `Extraction`, `{"name", "strength": {"value","unit"}}`,
  or the flat API shape `{"name", "strength_value", "strength_unit", ...}` (explicit
  `strength` wins when both are present).

### Safety behavior

- Raw text is preserved verbatim; every instruction item is a substring of the source.
- Names are canonicalized only against the lexicon (`Metform1n` -> `Metformin`,
  `L1SINOPRIL` -> `Lisinopril`). Unknown tokens fall back to the verbatim source
  token at confidence <= 0.5; names are never invented. `FieldString.raw` keeps
  the original substring.
- **Strength** (`mg`, `mcg`, `g`, `ml`, `IU`, `%`) is never taken from quantity
  per dose (`Take 2 tablets`) or package counts (`30 tablets`); the dose count is
  reported as a `dose` instruction item instead.
- Missing fields are contract-valid `{value: null, confidence: 0.0, source: "none"}`.
- `hints` only bias matching (name/lexicon/strength); they never become values.

### Contract mapping

- `Extraction.medication_contract()` -> `medication{name,strength,form,manufacturer}`
- `Extraction.instructions_contract()` -> `instructions{raw_text,parsed[]}`

The API service (`services/api`) owns composing these into `ScanResponse`.
