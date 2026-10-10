# MedCheck Inference Contracts — v1 (FROZEN)

Owner: **ORCHESTRATOR (Apollo)**. Change process: Bus request → orchestrator approval →
version bump in `contracts/` + `services/common/contract.py` + CHANGELOG entry.

## Files

| File | Purpose |
|---|---|
| `v1/scan_request.schema.json` | `POST /v1/scan` multipart request parts |
| `v1/scan_response.schema.json` | Full `ScanResponse` JSON contract |
| `examples/ok_response.json` | Realistic `status:"ok"` payload |
| `examples/needs_rescan_response.json` | Blurry-frame payload |
| `examples/error_response.json` | Error envelope |

## Endpoints (frozen)

- `GET /health` → `200 {"status":"ok","service":"medcheck-inference","version":"x.y.z","uptime_s":n}`
- `GET /ready` → `200 {"ready":true,"mode":"mock|real","components":{...}}` or `503`
  `{"ready":false,"reasons":[...]}`
- `POST /v1/scan` → `200` `ScanResponse` (even for `status:"error"` domain errors) or
  `4xx/5xx` only for transport-level failures (bad multipart, payload too large).

## Rules

1. Every structured field carries `confidence` + `source` (`ocr|vlm|registry|none`).
2. Raw source text (`label.text`, `instructions.raw_text`) is preserved verbatim.
3. `safety` block is mandatory on every response; `ingestion_not_inferred` and
   `backend_authoritative` are always `true`.
4. `status` semantics:
   - `ok` — usable read, uncertainty `low`.
   - `needs_rescan` — retake photo; `frame_quality.acceptable=false` and/or
     `uncertainty.rescan_required=true`.
   - `uncertain` — usable but low-confidence fields; still return best-effort data.
   - `no_medication_found` — no bottle/label located.
   - `error` — pipeline failure; `error` object populated.
5. Mock mode must set `mode:"mock"` and must never fabricate a drug name that is not
   present in its synthetic fixture set.
6. Coordinates are normalized `[0,1]` floats relative to the full frame.

## Versioning

`contract_version` is included in every response. Additive optional fields bump the
minor version (`1.1.0`); breaking changes bump the major version and require a new
`vN/` directory. v1 consumers must ignore unknown optional fields.

**Changelog**

- `1.1.0` (2026-10-10) — additive: `instructions.dose` (`{quantity, unit, confidence,
  source}`), the structured per-dose quantity as written on the label. Added so the
  backend's `POST /api/v1/scans` gets a real numeric quantity from inference instead of
  clients guessing. Absent/`null` when the label does not clearly state a per-dose
  quantity; never a package count.
- `1.0.0` — initial frozen contract.
