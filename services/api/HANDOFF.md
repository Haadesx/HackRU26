# MedCheck API Gateway — Handoff (PI-4 Athena)

Status: **Gate 3 complete — mock mode working on port 8300.**
Branch: `feat/api-athena` · Worktree: `.worktrees/pi-4-api` · Owner: PI-4 Athena

## Run

```bash
cd .worktrees/pi-4-api
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r services/api/requirements.txt   # or: fastapi uvicorn python-multipart pydantic pytest httpx jsonschema
.venv/bin/python -m uvicorn services.api.main:app --host 0.0.0.0 --port 8300
```

Tests:

```bash
.venv/bin/python -m pytest services/api -q
```

OpenAPI docs: `http://localhost:8300/docs`.

## Endpoints (frozen v1)

| Endpoint | Success | Transport errors |
|---|---|---|
| `GET /health` | `200 {"status":"ok","service":"medcheck-inference","version","uptime_s"}` | — |
| `GET /ready` | `200 {"ready":true,"mode":"mock","components":{...}}` | `503` when `MEDCHECK_API_MODE=real` and no real pipeline is wired |
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

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `MEDCHECK_API_MODE` | `mock` | default for `mode=auto`; `real` makes `/ready` return 503 until Vision/OCR/VLM are wired |
| `MEDCHECK_SCAN_TIMEOUT_S` | `15` | per-scan budget; exceeding returns `504 SCAN_TIMEOUT` |

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
| 503 | `REAL_PIPELINE_UNAVAILABLE` | `mode=real` (or `MEDCHECK_API_MODE=real`) before wiring |
| 504 | `SCAN_TIMEOUT` | scan exceeded the budget |

Domain failures stay **HTTP 200** with `status:"error"` in the `ScanResponse`
(e.g. `INVALID_IMAGE` when magic bytes do not match the declared type).

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
- `MockPipeline` — current implementation.
- `get_pipeline(resolved_mode)` — returns mock, raises `PipelineUnavailable` for real.
- `to_contract_json(response)` — serializer that keeps output valid against
  `contracts/v1/scan_response.schema.json` (omits null optional objects, keeps
  required-but-nullable keys).

**Wiring real mode later:** implement a `RealPipeline` composing Vision → OCR →
candidate matching → optional VLM, return it from `get_pipeline("real")`, and
flip `/ready` components. The HTTP surface, schemas, and tests do not change.

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

- `pytest services/api -q` → **40 passed** (endpoint behavior, transport limits,
  JSON Schema conformance of HTTP payloads and all `contracts/examples/*.json`,
  pydantic mirror round-trip, determinism, safety block).
- Live demo on port 8300: `/health`, `/ready`, mock `/v1/scan` (see report).
