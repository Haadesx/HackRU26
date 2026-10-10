# Client Integration Guide — iOS, Web UI, Backend

Who this is for: **Aparajita (iOS)**, **Sinchana (Web UI)**, **Urvi (backend)**, and anyone
wiring the MedCheck pieces together. It describes the *flow across components*; API details
live in `contracts/README.md` + `services/api/HANDOFF.md` + `docs/backend-urvi.md`.

## Topology

| Service | Where | Base URL (dev) |
|---|---|---|
| Inference gateway (FastAPI) | Mac, port **8300** | `http://127.0.0.1:8300` · devices: `http://<mac-tailscale-ip>:8300` |
| Backend API (Flask) | Mac, port **8000** | `http://127.0.0.1:8000/api/v1` |
| Home rig vLLM (only the gateway talks to it) | `hermes-linux` via Tailscale | `:8100` — never called by clients |

```
iOS / Web ──image──▶ :8300/v1/scan ──▶ ScanResponse (contract v1.1)
   │                                        │
   └──────────── map fields ────────────────┘
        POST :8000/api/v1/scans  {event_id,user_id,drug_name,strength,quantity,timestamp}
                │
                └─▶ match_status, dose_event, timing, quantity_check, candidates
        POST /api/v1/doses/{dose_id}/confirm   ← the ONLY call that records a dose
```

## 1. Scan

`POST {inference}/v1/scan` — `multipart/form-data`:
`image` (JPEG/PNG ≤ 12 MiB), optional `client` (`ios|backend|test`), `mode`
(`auto|mock|real`), `hints` (JSON string).

```bash
curl -s -F "image=@bottle.jpg" -F "mode=real" -F "client=ios" http://127.0.0.1:8300/v1/scan
```

**Use `mode:"mock"` while building UI** — deterministic, no models, same shape.

The response is `ScanResponse` (v1.1). Show at least: `status`, `medication.name/strength`
with confidence, `frame_quality.guidance` when `needs_rescan`, and the mandatory
`safety.disclaimer`.

| `status` | UI behaviour |
|---|---|
| `ok` | Show fields; proceed to backend |
| `uncertain` | Show fields with uncertainty cues; proceed (backend match may clarify) |
| `needs_rescan` | Show `frame_quality.guidance`, offer retake; do not call backend |
| `no_medication_found` | Ask user to reframe; do not call backend |
| `error` | Show `error.message`; allow retry |

Safety rules for every UI: never imply ingestion from a scan; never present dosing advice;
`confirm` is always an explicit user action.

## 2. Capture tips (from the real-time path)

The gateway’s fast path is `POST /v1/scan` only — for *live guidance* the local test console
uses a vision-only pass (~20 ms + YOLO ≈ 145 ms on CPU). iOS can approximate this by
scanning at a low rate (1–2 fps) while the user frames the bottle and stopping on the first
`ok`/`uncertain`, or wait for a dedicated `/v1/frame-quality` endpoint (not built yet).

Bottle detection uses ONNX YOLO11n (COCO bottle class) when `MEDCHECK_YOLO_MODEL` is set;
otherwise a CPU heuristic. Both are best-effort; label OCR works on full frames too.

## 2b. Long labels — rotation-assisted multi-frame capture (v1.2)

When the label is larger than the frame, ask the user to capture **3 overlapping frames**
while rotating (start → middle → end) and send them together:

```bash
curl -s -X POST \
  -F "images=@frame1.png" -F "images=@frame2.png" -F "images=@frame3.png" \
  -F "mode=real" -F "client=ios" \
  ${INFERENCE:-http://127.0.0.1:8300}/v1/scan/multi
```

Rules:
- 2–6 images, each JPEG/PNG ≤ 12 MiB; **overlap ~30 %** between neighbours.
- Each frame must pass quality; frames that fail are reported in
  `capture.per_frame[].status` (`needs_rescan`) and skipped, but the others are still read.
- `capture.fusion == "multi_frame"`, `capture.frames_used` tells you how many contributed.
- `capture.per_frame[].clipped == true` means the label ran off that frame — prompt the
  user to rotate further for the next shot.
- Fusion is field-level (best confidence wins; instruction lines are unioned; raw text is
  kept verbatim per frame), so partial reads combine safely and nothing is invented.
- If `uncertainty.level` is still high after fusion, the gateway may escalate to the VLM
  with **all frames** (multi-image) before answering.
- Guidance strings for capture UX come from `frame_quality.guidance` (e.g. “Label is cut
  off — rotate the bottle or step back, then capture again”).

## 3. Map the scan to the backend ingest

`POST {backend}/api/v1/scans` (JWT) body:

| Backend field | From inference | Notes |
|---|---|---|
| `event_id` | client-generated **UUIDv4** | idempotent — reuse the same UUID on retry |
| `user_id` | from backend `GET /me` | patient’s UUID |
| `drug_name` | `medication.name.value` | **skip the call if null** (no name = nothing to match) |
| `strength` | `medication.strength` → `{value, unit}` | `null` allowed |
| `quantity` | `instructions.dose.quantity` (v1.1) | fallback `1` only when the label states none |
| `timestamp` | client `now` in UTC `…Z` | future timestamps are rejected |

Proven mapping + test: `tests/integration/test_backend_fit.py`;
runnable end-to-end: `.venv-full/bin/python scripts/e2e_scan_to_backend.py --dry-run`.

**Never** send a scan when `status` is `needs_rescan`, `no_medication_found`, or `error`.

## 3b. Web UI (Sinchana) hub contract — mapping & open decision

The web app (`frontend/`, merged into `feat/inference-medcheck`) never calls models
directly. It expects a **hub** at `VITE_API_URL` (default `http://localhost:8000`; mock data
when unset) with `GET /state`, `POST /scans` (multipart `photo`), `POST /scans/{id}/photos`
(extra photos, merged), `POST /scans/{id}/complete`, `GET /adherence`, `PUT /settings`, …
(see `frontend/docs/api-contract.md`).

Its nine scan fields map to contract v1.3 like this:

| UI field | From inference | Notes |
|---|---|---|
| `name` | `medication.name.value` | |
| `strength` | `medication.strength` | format `"<value> <unit>"` (e.g. `"25 mg"`) |
| `dose_amount` | `instructions.dose.quantity` | string (`"1"`) |
| `schedule_times` | `label_meta.schedule_times` | derived `"08:00"` / `"08:00, 20:00"`, lower confidence |
| `quantity_start` | `label_meta.quantity_start` | QTY as printed |
| `refills_remaining` | `label_meta.refills_remaining` | `"No refills"` → `"0"` |
| `pharmacy_name` / `pharmacy_phone` | `label_meta.*` | |
| `prescriber` | `label_meta.prescriber` | |
| (any missing) | value `null`, confidence `0` | UI shows its `missing` state and asks the caregiver |

Multi-photo merging (“keep the highest-confidence value per field”) is exactly what our
`POST /v1/scan/multi` fusion does; a hub can either call `/v1/scan/multi` once or call
`/v1/scan` per photo and merge with the same rule.

**Open decision for the team — who calls inference?**

- *Sinchana’s model:* the **hub** (backend) calls inference server-to-server; clients only
talk to the hub. One client API, one auth model, model endpoints stay internal.
- *Urvi’s current model:* **clients** call inference directly and POST the result to
  `/api/v1/scans` (JWT).

Recommendation: **hub-proxied inference** (backend calls `:8300` internally, maps to the
table above, and keeps serving `/api/v1` to iOS/Web). That removes client CORS/auth
concerns for the model, keeps the vLLM key server-side, and gives the UI its nine fields.
Decision needed from Urvi + Sinchana before implementing the proxy.

## 4. Confirm (only after the user takes the dose)

`POST {backend}/api/v1/doses/{dose_id}/confirm` with `{observation_event_id, quantity_taken?}`.
A scan alone never changes dose status; `match_status` values are
`matched | ambiguous | no_match | not_due` (see `docs/backend-urvi.md`).

## 5. Registered candidates (hints)

To help inference choose between the patient’s medications, pass the backend’s medication
list as `hints`:

```json
{"known_candidates":[{"name":"Metformin","strength":{"value":500,"unit":"mg"}},
                     {"name":"Lisinopril","strength":{"value":10,"unit":"mg"}}]}
```

Behaviour: a candidate matched at ≥ 0.75 is returned in `candidates[]` with
`source:"registry"`; a confident label that matches **no** candidate escalates to the VLM
(by design) and is surfaced in `uncertainty.reasons`.

## 6. Auth

- **Backend:** JWT — `POST /auth/login {email,password}` → `access_token`; send
  `Authorization: Bearer …`; refresh via `/auth/refresh`.
- **Inference gateway:** none by default. When `MEDCHECK_API_KEY` is set (M6), `/v1/scan`
  requires `Authorization: Bearer <key>`; `/health` and `/ready` stay open.
- **CORS (web UI):** set `MEDCHECK_CORS_ORIGINS` on the gateway (M6). `*` is local-dev only.
- Device testing: bind the gateway to `0.0.0.0` and reach the Mac over Tailscale
  (`http://<mac-tailscale-ip>:8300`). For anything non-local, put TLS in front (uvicorn
  `--ssl-keyfile/--ssl-certfile` or a reverse proxy).

## 7. Error handling

| Layer | Signal | Handling |
|---|---|---|
| Gateway | `4xx` | bad/oversized/unsupported image — show a retake message |
| Gateway | `200` + `status:"error"` | domain failure; show `error.message`, offer retry |
| Gateway | `504` | scan timeout — retry once, then ask for a closer/steadier shot |
| Backend | `401` | refresh token, else re-login |
| Backend | `403` / `404` | wrong patient / unknown dose — do not retry |
| Backend | `400` | validation (future timestamp, unknown fields) — fix payload, do not retry blindly |

## 8. Reporting a scan bug

Send `request_id` from the response, plus (if you scanned through the local console) the
saved debug bundle in `~/.medcheck/scans/` (image + response JSON, last 40). That lets the
inference team reproduce the exact frame and pipeline result.
