# MedCheck API Gateway — Handoff (PI-4 Athena)

Status: **Gates 3–4 done — mock + real OCR-first pipeline, contract v1.1 with
`instructions.dose`, backend bridge documented.** Branch: `feat/api-athena` ·
Worktree: `.worktrees/pi-4-api`

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
.venv/bin/python -m pytest services/api -q          # 100 passed
.venv/bin/python -m pytest services tests/integration -q   # 458 passed, 3 skipped (merged tree)
```

OpenAPI docs: `http://localhost:8300/docs`.

## Endpoints (frozen v1)

| Endpoint | Success | Transport errors |
|---|---|---|
| `GET /health` | `200 {"status":"ok","service":"medcheck-inference","version","uptime_s"}` | — |
| `GET /ready` | `200 {"ready":true,"mode":"mock|real","components":{...}}` | `503` when `MEDCHECK_API_MODE=real` and vision/OCR specs are missing |
| `POST /v1/scan` | `200` `ScanResponse` (also for domain `status:"error"`) | `400/413/415/503/504` error envelope |
| `POST /v1/scan/multi` | `200` `ScanResponse` with v1.2 `capture` block | `400` (frame count), `401`, `413/415/503/504` |

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

Real mode (Vision → OCR → matcher → optional VLM):

```bash
MEDCHECK_API_MODE=real .venv/bin/uvicorn services.api.main:app --host 0.0.0.0 --port 8300

# no hints — OCR-first; VLM only if identity is weak/mismatched
curl -s -X POST localhost:8300/v1/scan \
  -F "image=@samples/label_metformin.png;type=image/png" \
  -F "client=ios" -F "mode=real"

# with registered candidates — matcher fills candidates[] (score 1.0); a match suppresses the VLM
curl -s -X POST localhost:8300/v1/scan \
  -F "image=@samples/label_metformin.png;type=image/png" \
  -F "client=ios" -F "mode=real" \
  -F 'hints={"known_candidates":[{"name":"Metformin","strength":{"value":500,"unit":"mg"}}]}'
```

Verified response shapes and measured timings: see “Verified real-mode examples and
measurements” below.

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `MEDCHECK_API_MODE` | `mock` | default for `mode=auto`; `real` requires vision/OCR installed |
| `MEDCHECK_SCAN_TIMEOUT_S` | `15` | per-scan budget; exceeding returns `504 SCAN_TIMEOUT` |
| `MEDCHECK_API_KEY` | unset (auth off) | when set, `POST /v1/scan` requires `Authorization: Bearer <key>`; `/health` and `/ready` stay open |
| `MEDCHECK_CORS_ORIGINS` | unset (CORS off) | comma-separated browser origins for `CORSMiddleware`; `*` local dev only; restart to apply |
| `MEDCHECK_VLM_ENABLED` | unset (off) | opt-in for the PI-3 VLM fallback; only called when `should_use_vlm()` also says yes |
| `MEDCHECK_VLM_BASE_URL` / `MEDCHECK_VLM_MODEL` / `MEDCHECK_VLM_API_KEY` | — | existing rig vLLM endpoint (see docs §D.3); never committed |

## Real mode behavior (Milestone 2 + M3 escalation)

`mode=real` (or `mode=auto` with `MEDCHECK_API_MODE=real`) composes, in-process:

1. **PI-1 Vision** `analyze_frame(image)` → frame quality + bottle/label bboxes.
2. If `frame_quality.acceptable=false` → **`needs_rescan`**, guidance returned,
   OCR is skipped (no label text, no medication fields).
3. **PI-2 OCR** `read_text(...)` on the label crop, falling back to the full
   frame; raw text preserved verbatim; `extract_fields(...)` → `medication` /
   `instructions` (all sources `ocr`).
4. **PI-2 matcher**: `match_candidates(extraction, hints.known_candidates,
   threshold=0.75)` fills `candidates[]` (source `registry`); below-threshold
   matches are dropped. No hints / no identity read → `candidates: []`.
5. **PI-3 VLM** (optional, M3 escalation policy — PI-3 contract in
   `services/vlm/EVAL.md`): called only when `MEDCHECK_VLM_ENABLED=1` AND
   `should_use_vlm(uncertainty, config)` says so, where config =
   `{"min_field_confidence": 0.75, "escalation_fields": ("name","strength_value"),
   "min_frame_score": 0.45, "candidate_mismatch": bool}` and
   `uncertainty["frame_score"] = frame_quality.score`. `candidate_mismatch` is
   True when hints supplied registered candidates, OCR read a name/strength, and
   the matcher returned no match; level `high` still always escalates; missing
   optional fields (e.g. manufacturer) alone must NOT cost a VLM call. Results are
   merged via `reconcile_fields` with per-field source attribution; a VLM failure
   degrades to the OCR read (`vlm_unavailable` reason).

Status mapping: `ok` (level low), `uncertain` (medium/high without rescan),
`needs_rescan` (frame unacceptable), `no_medication_found` (no bottle/label and no
readable name/strength), `error` (e.g. `INVALID_IMAGE`, `OCR_UNAVAILABLE`; HTTP
200 domain envelope). Request `hints.known_candidates` bias OCR (`name`,
`lexicon`, strength) and are passed to the matcher; they never become field values.

## Verified real-mode examples and measurements

`GET /ready` with `MEDCHECK_API_MODE=real` (merged branch):

```json
{"ready":true,"mode":"real","components":{"vision":"ready","ocr":"ready","pipeline":"real","vlm":"disabled"},"reasons":[]}
```

Measured on the merged branch against the shared rig vLLM
(`Qwen/Qwen3-VL-8B-Instruct-FP8`, orchestrator live verification):

| Path | Result | Timing |
|---|---|---|
| `samples/label_metformin.png`, VLM escalated | Metformin 500 mg (name 0.95 / strength 1.0) + VLM summary/form | total 2272 ms (OCR 411 ms, VLM 1745 ms) |
| `samples/label_metformin_blurry.png` | `needs_rescan` + guidance, OCR skipped | 19.5 ms |
| matched hints (`known_candidates`) | `candidates` score 1.0, VLM not called | — |
| mismatched hints | matcher drops candidate → `candidate_mismatch` → VLM verifies | — |

**VRAM:** the VLM call reuses the already-resident shared Qwen3-VL service; no
additional VRAM is allocated (RTX 5090 32 GB stays ≈18.4 GiB used / ≈13.7 GiB
free, no growth observed). The gateway never launches a model.

**iOS/backend field ownership:** see `docs/inference-medcheck.md` §E.1
(`ScanResponse` field table) and §H.1 (client integration notes). The gateway
always returns `contract_version:"1.3.0"` with `{value, confidence, source}` per
field, the mandatory `safety` block, the v1.2 `capture` block on multi-frame
responses, and the v1.3 `label_meta` block (see below).

## Multi-frame capture — `POST /v1/scan/multi` (contract v1.2)

Read one long label from 2–6 photos instead of one (a 3-frame left/center/right
sweep is the intended workflow). Multipart fields:

| Part | Required | Notes |
|---|---|---|
| `images` | yes, repeated 2–6× | JPEG/PNG, max 12 MiB each, same rules as `/v1/scan` |
| `client` / `mode` / `hints` | no | identical semantics to `/v1/scan`; bearer auth applies |

```bash
curl -s -X POST localhost:8300/v1/scan/multi \
  -F "images=@samples/long_label_left.png;type=image/png" \
  -F "images=@samples/long_label_middle.png;type=image/png" \
  -F "images=@samples/long_label_right.png;type=image/png" \
  -F "client=ios" -F "mode=real"
```

Per-frame path & fusion:

1. Every frame runs the normal real pipeline frame path (quality → OCR →
   extraction). Frames that fail quality (`needs_rescan`), have no localized
   label (`no_medication_found`), or error are reported in
   `capture.per_frame` and **not fused**.
2. Accepted frames' `Extraction`s are fused by PI-2's
   `services/ocr/fuse.py::fuse_extractions` (highest-confidence non-null field,
   instruction union, dose carried over; conflicts surfaced as
   `name_conflict`/`strength_conflict`/… in `uncertainty.reasons`). A
   conservative API-side fallback keeps the endpoint working on older branches.
3. `medication` / `instructions` (incl. `dose`) come from the fused extraction;
   VLM escalation (M3 policy) runs once on the fused result.

Response `capture` block:

```json
{"frames_requested": 3, "frames_used": 2, "fusion": "multi_frame",
 "per_frame": [{"index": 0, "status": "accepted", "label_detected": true,
                "label_confidence": 0.59, "clipped": true,
                "guidance": ["Looks good - hold steady."]}, ...]}
```

`uncertainty.reasons` gains `fused_from_<N>_frames` when N>1 plus fusion
conflicts. No frames accepted → `needs_rescan` (or `no_medication_found` when the
frames passed quality but no label was found), mirroring single-scan semantics.
Mock mode is deterministic per frame and always emits `capture`
(`fusion:"multi_frame"`).

### Client rotation-capture recipe (3 frames)

1. Hold the bottle so the label spans the frame; start with the **left** third
   visible, then **center**, then **right** — each frame overlapping the previous
   by ~20–30 % so text is never only in one frame.
2. Wait for a good frame each time (sharp, not too dark/bright, no glare);
   `capture.per_frame[i].guidance` tells the user what to fix per shot.
3. Keep the whole label edge-to-edge: frames where the label region touches the
   frame edge report `clipped:true` — that is expected for a sweep, but avoid
   text actually cut off.
4. `frames_used` tells the client how many shots contributed; if it is below
   the number sent, show the per-frame guidance and let the user retake the
   failed frame.

## Label metadata + web hub mapping (contract v1.3)

`label_meta` is an additive optional block with six `field_string` entries
(`{value: string|null, confidence, source}`): `quantity_start`,
`refills_remaining`, `pharmacy_name`, `pharmacy_phone`, `prescriber`, and
`schedule_times`. Values are strings exactly as read, except `schedule_times`
which is derived from the label wording (`"twice daily"` → `"08:00, 20:00"`)
and therefore carries lower confidence. Missing values stay `null` with
`source:"none"` — never fabricated. The real pipeline prefers PI-2's
`Extraction.label_meta_contract()` (temporary bridge until it lands); mock
fixtures carry synthetic values consistent with their labels.

Web hub (Sinchana's UI) mapping — missing values arrive as `null`/0 confidence
so the hub can render its "missing" state:

| Hub field | ScanResponse source | Missing |
|---|---|---|
| `name` | `medication.name.value` | `null` |
| `strength` | `f"{strength.value} {strength.unit}"` | `null` |
| `dose_amount` | `instructions.dose.quantity` | `null` (client may fall back to 1) |
| `schedule_times` | `label_meta.schedule_times.value` | `null` |
| `quantity_start` | `label_meta.quantity_start.value` | `null` |
| `refills_remaining` | `label_meta.refills_remaining.value` | `null` |
| `pharmacy_name` | `label_meta.pharmacy_name.value` | `null` |
| `pharmacy_phone` | `label_meta.pharmacy_phone.value` | `null` |
| `prescriber` | `label_meta.prescriber.value` | `null` |

Example real scan (`samples/label_metformin.png`): quantity_start `"30"`,
refills_remaining `"2"`, pharmacy_name `"Demo Pharmacy"`, pharmacy_phone
`"(555) 010-2030"`, prescriber `"Dr. A. Demo"`, schedule_times `"08:00, 20:00"`.

## Backend bridge — contract v1.3 (Urvi's `POST /api/v1/scans`)

Contract **1.3.0** is additive over 1.2.0: the `label_meta` block (plus 1.2.0's
multi-frame `capture` / `POST /v1/scan/multi`, and 1.1.0's `instructions.dose`
`{quantity (number>0|null), unit (string|null), confidence, source}`).
It is the per-dose quantity as written on the label ("Take 1 tablet" → `1`,
`"tablet"`), **never** a package count, and is omitted/null when absent or
ambiguous. A `dose` object with `source:"none"` (quantity and unit null) means
"the v1.1 pipeline ran and no dose was clearly stated" — clients must treat it
exactly like an absent dose and **never** send its null/0 as the backend
quantity (use the fallback `1`). The real pipeline prefers PI-2's `Extraction.dose_contract()` (with a
temporary, quantity-safe bridge until that ships); mock fixtures carry synthetic
dose blocks so iOS can develop against v1.1.

Client mapping for the backend ingest schema:

| Backend field | ScanResponse source | Fallback / notes |
|---|---|---|
| `event_id` | client-generated UUID | idempotency key; generate once per submission |
| `user_id` | client/session | — |
| `drug_name` | `medication.name.value` | required by backend |
| `strength` | `medication.strength` `{value, unit}` | `null` when not read |
| `quantity` | `instructions.dose.quantity` | client default `1` when absent — never from package size |
| `timestamp` | client-side UTC ISO-8601 (`...Z`) | client event time |

Verified by `tests/integration/test_backend_fit.py`: a real scan of
`samples/label_metformin.png` yields `dose {1, "tablet", ~0.96, "ocr"}` and the
mapped payload passes the backend's presence/type checks.

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
| 401 | `UNAUTHORIZED` | `MEDCHECK_API_KEY` set and bearer token missing/invalid |
| 504 | `SCAN_TIMEOUT` | scan exceeded the budget |

Domain failures stay **HTTP 200** with `status:"error"` in the `ScanResponse`
(e.g. `INVALID_IMAGE` when bytes cannot be decoded, `OCR_UNAVAILABLE` when the
RapidOCR backend is missing).

## Network access, auth, CORS and TLS

### Bind for device testing

Local dev default: `--host 127.0.0.1`. For iOS/web devices on the same Tailnet:

```bash
MEDCHECK_API_MODE=real .venv/bin/uvicorn services.api.main:app --host 0.0.0.0 --port 8300
# reachable at http://<tailscale-host>:8300 (e.g. http://ai-rig.<tailnet>.ts.net:8300)
```

Only expose the gateway on trusted networks — the local dev build has no TLS.

### Optional bearer auth (`MEDCHECK_API_KEY`)

- When set, `POST /v1/scan` requires `Authorization: Bearer <key>` on every
  request. Comparison is constant-time (`hmac.compare_digest`); missing/wrong
  tokens return `401` with the standard envelope (`code: UNAUTHORIZED`).
- `GET /health` and `GET /ready` stay open for probes and load balancers.
- Unset (default) = local development, behaviour unchanged. Never commit the key
  value; set it in the shell or a secret manager on the host.

### CORS for the web UI (`MEDCHECK_CORS_ORIGINS`)

- Comma-separated allow-list, e.g.
  `MEDCHECK_CORS_ORIGINS=http://localhost:5173,https://medcheck.example`.
- Enables `CORSMiddleware` on the API routes with `GET/POST/OPTIONS` and
  `Authorization`/`Content-Type` request headers.
- `*` is acceptable **only** for local development (any website could then call a
  keyless gateway); prefer explicit origins anywhere else.
- Read at startup — restart the gateway after changing it.

### TLS (documented, not terminated by the app)

Two hardening options:

1. **Direct TLS** — point uvicorn at a certificate:
   `uvicorn services.api.main:app --host 0.0.0.0 --port 8300 \
   --ssl-keyfile /path/key.pem --ssl-certfile /path/cert.pem`
2. **Reverse proxy** — terminate TLS in nginx/Caddy/ALB and forward to
   `127.0.0.1:8300`; keep uvicorn bound to loopback in that setup.

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

1. Send `mode=auto`; it maps to the service mode (`MEDCHECK_API_MODE`, default
   `mock`; set `real` for live inference). Explicit `mode=real` per request works too.
2. Enforce 12 MiB client-side before upload; JPEG/PNG only.
3. Treat `status:"needs_rescan"` as a retake prompt and surface
   `frame_quality.guidance` verbatim (ordered, user-facing).
4. Always render the `safety.disclaimer`; never imply ingestion — holding a bottle
   is not proof of ingestion.
5. Backend remains authoritative for schedules, dose history, and inventory;
   inference only reads labels.
6. Ignore unknown optional fields (v1 additive-compatibility rule).

## Verification

- `pytest services/api -q` → **100 passed** (endpoint behavior, transport limits,
  JSON Schema conformance of HTTP payloads and all `contracts/examples/*.json`,
  mock determinism, real pipeline on `samples/` (dark/sharp/blurry), EXIF-safe
  decode, no-medication and invalid-image paths, matcher seam, M3 escalation
  matrix via `httpx.MockTransport`, v1.1 dose real/mock/omission + bridge units,
  optional bearer auth and CORS, multi-frame capture/fusion/transport tests,
  v1.3 label_meta real/bridge/missing-state tests).
- `pytest services tests/integration -q` → **458 passed, 3 skipped** in the merged
  worktree (skips are model-dependent ONNX tests), including Urvi's backend-fit
  mapping (`tests/integration/test_backend_fit.py`).
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
