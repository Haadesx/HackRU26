# MedCheck API Gateway — Handoff (PI-4 Athena)

Status: **Gate 3 (mock) accepted; Milestone 2 done — real OCR-first pipeline wired
behind the same seam.** Branch: `feat/api-athena` · Worktree: `.worktrees/pi-4-api`

## Run

```bash
cd .worktrees/pi-4-api
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r services/api/requirements.txt   # includes OCR stack for real mode
.venv/bin/python -m uvicorn services.api.main:app --host 0.0.0.0 --port 8300

# real mode (Vision + OCR compose in-process; VLM still off by default)
MEDCHECK_API_MODE=real .venv/bin/python -m uvicorn services.api.main:app --host 0.0.0.0 --port 8300
```

Tests:

```bash
.venv/bin/python -m pytest services/api -q          # 54 passed
.venv/bin/python -m pytest services tests/integration -q   # 206 passed (merged tree)
```

OpenAPI docs: `http://localhost:8300/docs`.

## Endpoints (frozen v1)

| Endpoint | Success | Transport errors |
|---|---|---|
| `GET /health` | `200 {"status":"ok","service":"medcheck-inference","version","uptime_s"}` | — |
| `GET /ready` | `200 {"ready":true,"mode":"mock|real","components":{...}}` | `503` when `MEDCHECK_API_MODE=real` and vision/OCR specs are missing |
| `POST /v1/scan` | `200` `ScanResponse` (also for domain `status:"error"`) | `400/413/415/503/504` error envelope |

`POST /v1/scan` is `multipart/form-data`:

| Part | Required | Notes |
|---|---|---|
| `image` | yes | `image/jpeg` or `image/png`, max **12 MiB** (magic bytes checked) |
| `client` | no | `ios \| backend \| test \| unknown` (default `unknown`) |
| `mode` | no | `auto \| mock \| real` (default `auto`; auto = service mode) |
| `hints` | no | JSON object string, e.g. `{"known_candidates":[{"name":"Metformin"}],"locale":"en-US"}` |

Every scan response carries `X-Request-ID` (also `request_id` in the body).

## Curl examples

```bash
curl -s localhost:8300/health
# {"status":"ok","service":"medcheck-inference","version":"0.1.0","uptime_s":3.21}

curl -s localhost:8300/ready
# {"ready":true,"mode":"mock","components":{"pipeline":"mock","vision":"not_wired","ocr":"not_wired","vlm":"not_wired"},"reasons":[]}

curl -s -X POST localhost:8300/v1/scan \
  -F "image=@/tmp/label.png;type=image/png" \
  -F "client=ios" -F "mode=mock" \
  -F 'hints={"locale":"en-US"}'
# → 200 ScanResponse (status ok / needs_rescan / uncertain / no_medication_found / error)
```

Real mode (Vision → OCR, VLM off by default):

```bash
MEDCHECK_API_MODE=real .venv/bin/uvicorn services.api.main:app --host 0.0.0.0 --port 8300
curl -s -X POST localhost:8300/v1/scan \
  -F "image=@samples/label_metformin_dark.png;type=image/png" \
  -F "client=ios" -F "mode=real"
# → mode:"real", medication.name {value:"Metformin", source:"ocr"}, label.text = verbatim OCR
```

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `MEDCHECK_API_MODE` | `mock` | default for `mode=auto`; `real` requires vision/OCR installed |
| `MEDCHECK_SCAN_TIMEOUT_S` | `15` | per-scan budget; exceeding returns `504 SCAN_TIMEOUT` |
| `MEDCHECK_VLM_ENABLED` | unset (off) | opt-in for the PI-3 VLM fallback; only called when `should_use_vlm()` also says yes |
| `MEDCHECK_VLM_BASE_URL` / `MEDCHECK_VLM_MODEL` / `MEDCHECK_VLM_API_KEY` | — | existing rig vLLM endpoint (see docs §D.3); never committed |

## Real mode behavior (Milestone 2)

`mode=real` (or `mode=auto` with `MEDCHECK_API_MODE=real`) composes, in-process:

1. **PI-1 Vision** `analyze_frame(image)` → frame quality + bottle/label bboxes.
2. If `frame_quality.acceptable=false` → **`needs_rescan`**, guidance returned,
   OCR is skipped (no label text, no medication fields).
3. **PI-2 OCR** `read_text(...)` on the label crop, falling back to the full
   frame; raw text preserved verbatim; `extract_fields(...)` → `medication` /
   `instructions` (all sources `ocr`).
4. **PI-2 matcher** (lazy): if `services.ocr.matcher.match_candidates(fields,
   known_candidates, threshold=0.75)` exists it fills `candidates[]`; until it
   lands, `candidates: []`.
5. **PI-3 VLM** (optional): called only when `MEDCHECK_VLM_ENABLED` is set **and**
   `should_use_vlm(uncertainty)` escalates. Results are merged via
   `reconcile_fields` with per-field source attribution; a VLM failure degrades to
   the OCR read (`vlm_unavailable` reason).

Status mapping: `ok` (level low), `uncertain` (medium/high without rescan),
`needs_rescan` (frame unacceptable), `no_medication_found` (no bottle/label and no
readable name/strength), `error` (e.g. `INVALID_IMAGE`, `OCR_UNAVAILABLE`; HTTP
200 domain envelope). Request `hints.known_candidates` bias OCR (`name`,
`lexicon`, strength) and are passed to the matcher; they never become field values.

## Transport error envelope

```json
{"error": {"code": "PAYLOAD_TOO_LARGE", "message": "...", "detail": null}, "request_id": "req-..."}
```

| HTTP | Code | Trigger |
|---|---|---|
| 400 | `INVALID_REQUEST` | missing/malformed multipart part |
| 400 | `INVALID_MODE` / `INVALID_CLIENT` / `INVALID_HINTS` / `EMPTY_IMAGE` | semantic form errors |
| 413 | `PAYLOAD_TOO_LARGE` | image > 12 MiB |
| 415 | `UNSUPPORTED_IMAGE_TYPE` | content-type not JPEG/PNG |
| 503 | `REAL_PIPELINE_UNAVAILABLE` | `mode=real` but vision/OCR deps are not installed |
| 504 | `SCAN_TIMEOUT` | scan exceeded the budget |

Domain failures stay **HTTP 200** with `status:"error"` in the `ScanResponse`
(e.g. `INVALID_IMAGE` when bytes cannot be decoded, `OCR_UNAVAILABLE` when the
RapidOCR backend is missing).

## Mock behavior

- Deterministic: `request_key = sha256(image bytes, client, canonical hints)` selects
  one fixture from `services/api/fixtures.py` (`FIXTURES`). Same request → same result.
- Fixture set: `metformin_ok`, `amoxicillin_ok`, `ibuprofen_uncertain`,
  `blurry_rescan` (→ `needs_rescan`), `no_bottle` (→ `no_medication_found`).
- All fixtures are synthetic. Mock never fabricates a medication name outside the
  fixture set and never claims real inference (`mode:"mock"`, VLM `available:false`).
- Every response includes the mandatory `safety` block
  (`disclaimer`, `ingestion_not_inferred:true`, `backend_authoritative:true`).

## Pipeline seam

`services/api/pipeline.py`:

- `ScanContext` — request_id, image bytes, content_type, client, requested_mode, hints.
- `ScanPipeline` protocol — `mode` + `async scan(ctx) -> ScanResponse`.
- `MockPipeline` — deterministic fixture pipeline (default).
- `RealScanPipeline` (`services/api/real_pipeline.py`) — Vision → OCR → matcher →
  optional VLM; heavy imports loaded lazily so mock mode stays dependency-light.
- `get_pipeline(resolved_mode)` — returns mock or real; raises
  `PipelineUnavailable` when real deps are missing (→ HTTP 503).
- `real_pipeline_available()` / `real_component_status()` — spec-based readiness
  without importing numpy/cv2/rapidocr (used by `/ready`).
- `vlm_enabled()` — `MEDCHECK_VLM_ENABLED` flag parsing.
- `to_contract_json(response)` — serializer that keeps output valid against
  `contracts/v1/scan_response.schema.json` (omits null optional objects, keeps
  required-but-nullable keys).

## iOS / backend integration notes

1. Send `mode=auto`; the gateway uses mock until real components are wired.
2. Enforce 12 MiB client-side before upload; JPEG/PNG only.
3. Treat `status:"needs_rescan"` as a retake prompt and surface
   `frame_quality.guidance` verbatim (ordered, user-facing).
4. Always render the `safety.disclaimer`; never imply ingestion — holding a bottle
   is not proof of ingestion.
5. Backend remains authoritative for schedules, dose history, and inventory;
   inference only reads labels.
6. Ignore unknown optional fields (v1 additive-compatibility rule).

## Verification

- `pytest services/api -q` → **54 passed** (endpoint behavior, transport limits,
  JSON Schema conformance of HTTP payloads and all `contracts/examples/*.json`,
  mock determinism, real pipeline on `samples/` (dark/sharp/blurry), no-medication
  and invalid-image paths, matcher seam, VLM escalation via `httpx.MockTransport`).
- `pytest services tests/integration -q` → **206 passed** in the merged worktree.
- Live demo on port 8300: mock + real `/v1/scan`, `/ready` real components (see report).

## Known integration notes

- Flat synthetic labels: initial vision calibration flagged
  `samples/label_metformin.png` as `too_bright`/glare. Atlas fixed this on
  `feat/vision-atlas` (d048749, fda2a75): readable-bright frames and adaptive
  label search make all three good samples acceptable and label-detected. After
  that merge, real mode reads them end-to-end; the API gate on
  `quality.acceptable` is unchanged and covered by a calibration-agnostic test.
- `label.detected=false` with `label.text` populated is valid: OCR falls back to
  the full frame when no label region is localized.
- Matcher input: `RealScanPipeline` passes the PI-2 `Extraction` object (not the
  wrapped canonical dict) to `match_candidates`, so strength participates in
  scoring (name-only 0.9× vs name+strength 1.0).
