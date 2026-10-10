# PI-4 API — `services/api/**` (owner: Athena)

Branch `feat/api-athena`, worktree `.worktrees/pi-4-api`.

**Priority: a working mock `/v1/scan` must exist first** (Gate 3). Real OCR/vision/VLM
are integrated later by wiring the other service modules behind the same contract.

## Deliverables

1. **FastAPI app** (`services/api/main.py`), runnable with
   `uvicorn services.api.main:app --host 0.0.0.0 --port 8300`.
2. **Endpoints** (frozen contract):
   - `GET /health`
   - `GET /ready` (200/503)
   - `POST /v1/scan` — multipart `image`, optional `client`, `mode`, `hints`
3. **Schemas** — import from `services.common.contract`; do not redefine the contract.
4. **Mock mode** — deterministic synthetic results keyed by request hash from a small
   synthetic fixture set. Must set `mode:"mock"`. Auto mode: use mock until real
   components are wired.
5. **Validation** — reject non-image content types, enforce 12 MiB max, 15 s timeout
   budget per scan, proper 4xx/5xx envelopes for transport errors.
6. **Wiring seam** — `services/api/pipeline.py` with a `ScanPipeline` protocol that can
   compose Vision → OCR → candidates → optional VLM later. Keep mock and real behind
   the same seam.
7. **Tests** — `pytest services/api` with httpx ASGI transport: health, ready, scan ok,
   scan needs_rescan, oversize rejection, schema round-trip against
   `contracts/examples/*.json`.
8. **Handoff doc** — `services/api/HANDOFF.md`: curl examples, env vars, run commands,
   error codes, and iOS/backend integration notes.

## Acceptance criteria

- `pytest services/api` green on Mac, no GPU, no network.
- Response validates against `contracts/v1/scan_response.schema.json`.
- `curl localhost:8300/health` and a mock `/v1/scan` demonstrated (paste output in report).
- Port 8300 only; do not bind other ports; do not start unrelated services.
- Report SHA + tests to Apollo via Bus.

## Rules

- Do not edit other services or `contracts/`.
- Only API-owned files under `services/api/**` plus `services/api/requirements.txt`.
