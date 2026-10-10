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

Latest results: **93 passed**; synthetic-set field accuracy 33/33 for name,
strength and form (precision = recall = 1.000); end-to-end through rendered
images 8/8 name, 8/8 strength, 8/8 form.

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
