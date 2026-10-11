# MedCheck (HackRU26) — Complete Development Status & Handoff

> **For ChatGPT and Hermes:** treat this file as ground truth for the MedCheck project as of
> the timestamp below. It is written to be self-contained — architecture, contracts,
> measured results, commands, limitations, and next steps. Ask for `docs/inference-medcheck.md`
> for the inference-only deep dive, `docs/client-integration.md` for the client flow,
> `services/api/HANDOFF.md` for API details, `docs/backend-urvi.md` for backend internals.
>
> **Last updated:** 2026-10-10 ~19:15 UTC · **Canonical branch:** `feat/integration`
> **Repo:** https://github.com/Haadesx/HackRU26 · **Owner/operator:** Varesh

---

## 0. TL;DR

MedCheck is a medication-label scanner for low-vision older adults. It is **three working
systems wired together end-to-end**:

```
React dashboard (Sinchana)  →  Flask/TimescaleDB backend + /hub (Urvi)  →  AI inference (Apollo/agents)
       :5199                          :8000/hub                                  :8300
```

- **Scans**: camera photo(s) → YOLO bottle detection → label OCR → structured fields → optional
  Qwen3-VL verification when identity is weak/mismatched. Long labels are captured across
  **3 rotated frames and fused**.
- **Backend** owns all medication authority: prescriptions (versioned), dose schedules/events,
  confirm/skip, missed-dose jobs, notifications (in-app/SMS/push), inventory, refills, adherence.
- **Dashboard** shows supply, today's doses, scan/verify/add flow, history, adherence, settings.
- Verified end-to-end on real photos and real data; **522 inference tests + 76 backend tests green**.

---

## 1. What MedCheck does (product)

1. Caregiver opens the dashboard; the patient's medications, stock and today's doses are shown.
2. **Add medication** → camera → photo of the bottle label (1–3 shots: start → rotate → end).
3. Inference returns nine fields with per-field confidence: `name, strength, dose_amount,
   schedule_times, quantity_start, refills_remaining, pharmacy_name, pharmacy_phone, prescriber`.
4. The caregiver confirms/corrects on the Verify screen → **Add** creates the medication
   (new prescription version), initializes stock, and generates dose events.
5. Daily loop: doses are taken and logged; missed doses alert caregivers; supply and refills are
   tracked; adherence is reported.

**Safety invariants (enforced in code):** a scan never records or implies ingestion; only an
explicit confirm records a dose; inference never authorizes dosing; every structured field keeps
`{value, confidence, source}` and raw text is preserved; strength (500 mg) is never confused with
quantity per dose (1 tablet); no fabricated names/strengths/instructions.

---

## 2. Architecture (final)

```
 iOS (Aparajita, not yet built)
        │
        ├──────────────────────────────┐
        ▼                              ▼
 React dashboard (Sinchana)      backend /api/v1 (JWT)
 :5199 · VITE_API_URL=:8000/hub   :8000 · prescriptions, doses, inventory,
        │                          refills, adherence, notifications, worker
        ▼
 /hub compatibility layer (Urvi) — dashboard contract, no auth, localhost only
        │  photo(s)                            ▲  state/read-write
        ▼                                      │
 inference gateway :8300 (Apollo/agents)       │
   vision (quality, YOLO11n ONNX bottle,       │
   label bbox, clipped detection)              │
   OCR (RapidOCR/ONNX + field extraction +     │
   candidate matcher + multi-frame fusion)     │
   VLM (Qwen3-VL-8B-FP8 via existing vLLM on   │
   the RTX 5090 rig, escalation only)          │
 flush── PostgreSQL 17 + TimescaleDB :5433 ────┘
```

- **Primary hub = backend `/hub`** (persists to Postgres, 15 tests, prefers inference v1.3
  `label_meta`). **Fallback hub = `tools/hub_adapter` (`:8500`)** — same contract, file-backed,
  needs no DB (`scripts/run_ui_demo.sh --adapter`).
- The home rig (`hermes-linux`, RTX 5090) already serves `Qwen/Qwen3-VL-8B-Instruct-FP8` under
  vLLM (Docker `echo-vllm`, Tailscale `:8100`). It is **shared** — never restarted, never a
  second VLM launched. GPU snapshot at handoff: **32,607 MiB total / 18,847 used / 13,242 free**.

---

## 3. Repository, branches, worktrees

| Branch | Purpose | Notes |
|---|---|---|
| **`feat/integration`** | **canonical** — everything merged | tip `7797c56` (docs) / `ed021d0` (hub merge) |
| `feat/inference-medcheck` | inference feature branch (Apollo) | M1–M10b, tools, docs |
| `feat/backend-urvi` | backend (Urvi) | 76 tests incl. `/hub` |
| `feat/frontend-ui` | dashboard (Sinchana), merged via PR #1 | React 18 + Vite + Tailwind |
| `feat/{vision-atlas,ocr-orion,vlm-juno,api-athena}` | worker branches (inside repo) | merged into inference branch |
| `main` | **intentionally untouched** (remote had no main; do not push it) | team decision pending |

One repo, one worktree per worker (`.worktrees/pi-1-vision` …), orchestrator merges and pushes.
Never force-pushed; no destructive resets. The remote has four branches; `main` is empty.

**Key commits:** contracts frozen `51569fd`; `.gitignore` model-package fix `179c4d6`; contract
v1.1 `3bdea53`; v1.2 multi-frame `600c52c`; v1.3 label_meta `9ccf613`/`c470a11`; M10/M10b OCR
spacing `70dac0f`/`615997f`; M5 YOLO `31c3634`; M7 endpoint `db94131`; Urvi's `/hub`
`35b8e50`/`e770889`; integration docs `7797c56`.

---

## 4. Inference subsystem (deep)

### 4.1 Services

| Service | Owner | What it does |
|---|---|---|
| `services/vision` | Atlas (PI-1) | decode/EXIF/resize, quality (blur/exposure/glare), **YOLO11n ONNX bottle detector** (heuristic fallback), label localization, `label_clipped` detection, camera guidance, `crop_label` |
| `services/ocr` | Orion (PI-2) | RapidOCR (PP-OCRv4 ONNX, no torch), verbatim text + boxes, name/strength/form/manufacturer extraction, instruction parsing, per-dose quantity/unit, pharmacy metadata, fuzzy **candidate matcher**, **multi-frame text fusion** |
| `services/vlm` | Juno (PI-3) | Qwen3-VL adapter (single + multi-image), reconciliation with source attribution, escalation policy, 24-image eval harness, GPU benchmark |
| `services/api` | Athena (PI-4) | FastAPI gateway (`:8300`), contract models, mock/real pipelines, `/v1/scan` + `/v1/scan/multi`, optional bearer auth, CORS, validation/timeouts |
| `services/common` | orchestrator | frozen contract models (pydantic) |

### 4.2 HTTP API (`:8300`)

- `GET /health`, `GET /ready`
- `POST /v1/scan` — multipart `image`, optional `client`, `mode` (`auto|mock|real`), `hints`
  (`{"known_candidates":[…]}`)
- `POST /v1/scan/multi` — 2–6 repeated `images`; per-frame report + **multi_frame** fusion
- Errors: 400 envelope, 413 oversize (12 MiB/image), 415 type, 504 timeout; domain failures
  return HTTP 200 with `status:"error"`.
- Optional `MEDCHECK_API_KEY` → `Authorization: Bearer …` on scans; `MEDCHECK_CORS_ORIGINS`.

### 4.3 Contract v1.3 (`contracts/v1/*.schema.json` + `services/common/contract.py`)

`ScanResponse`: `contract_version:"1.3.0"`, `request_id`, `status ∈ ok|needs_rescan|uncertain|
no_medication_found|error`, `mode ∈ mock|real`, `frame_quality{acceptable,score,blur,exposure,
glare,guidance[]}`, `bottle{detected,confidence,bbox?}`, `label{detected,confidence,bbox?,text}`,
`medication{name,strength,form,manufacturer}` each `{value,confidence,source}`,
`instructions{raw_text, parsed[], dose{quantity,unit,confidence,source}}` (v1.1),
`label_meta{quantity_start,refills_remaining,pharmacy_name,pharmacy_phone,prescriber,
schedule_times}` (v1.3), `candidates[]`, `interpretation{available,summary,source,model}`,
`uncertainty{level,reasons[],rescan_required}`, `timing{total_ms,stages{}}`,
`capture{frames_requested,frames_used,fusion,per_frame[]}` (v1.2),
`safety{disclaimer,ingestion_not_inferred:true,backend_authoritative:true}`, `error`.

Versioning: additive fields bump minor; breaking changes need `vN/`. v1 consumers ignore unknown
optional fields. All bboxes normalized `[0,1]`.

### 4.4 Multi-frame capture (long labels)

The client captures 2–6 overlapping frames while rotating. Each frame runs the full pipeline;
frames failing quality are reported (`needs_rescan`) and skipped. Fusion is **text-level**:
highest-confidence non-null fields, unioned instruction lines deduped, per-frame raw text kept
verbatim (`--- frame N ---`), conflicts surfaced as reasons (never silently averaged). Clipped
labels produce the prompt *“Label is cut off — rotate the bottle or step back, then capture
again.”* If identity stays weak/mismatched, the **VLM sees all frames at once**.

### 4.5 Models & config (env names only; secrets never in git)

- `MEDCHECK_YOLO_MODEL=models/yolo11n.onnx` (COCO bottle class; ONNX Runtime, cached session,
  no torch), `MEDCHECK_YOLO_CONF` (threshold)
- OCR: RapidOCR/ONNX, in-wheel PP-OCRv4; small crops are upscaled before recognition; degenerate
  text (e.g. `日`) is treated as unread
- `MEDCHECK_API_MODE`, `MEDCHECK_VLM_ENABLED`, `MEDCHECK_VLM_BASE_URL`, `MEDCHECK_VLM_MODEL`,
  `MEDCHECK_VLM_API_KEY` (in `~/.medcheck/vllm.env`, mode 600), `MEDCHECK_SCAN_TIMEOUT_S`,
  `MEDCHECK_SAVE_SCANS`
- Model weights live in `/models` (gitignored): `scripts/download_models.sh` (yolo11n.onnx,
  sha256 `634279b4…`)

### 4.6 Measured results (all executed, not estimates)

| Metric | Value |
|---|---|
| Inference tests (final) | **522 passed** (vision 118 · ocr 164 · vlm 134 · api 102 · integration 4) |
| OCR extraction (synthetic) | 33/33 name/strength/form; e2e rendered images 8/8 |
| 24-image eval | OCR-only macro F1 **0.99**, VLM-only **1.0**, hybrid **0.99**; escalation ~0 % on the clean set under M3 defaults |
| Clean real scan (OCR-first) | **541 ms** total (OCR ~423 ms), **zero VLM calls** |
| Escalated scan | VLM stage **~1.70 s** (2.4 s on a large real photo) |
| Blurry frame | `needs_rescan` in **19.5 ms** with guidance |
| Live vision pass | **~20 ms** warm (up to ~145–160 ms with YOLO on a real photo frame) |
| Real-photo bottle (YOLO) | heuristic 0/3 detections → **YOLO 0.51** on the clearest real photo |
| Concurrency (VLM off) | 8 simultaneous scans ≈ **2.1 s wall** (~3.8/s), no errors |
| VRAM across real calls | 18,383 used / 13,706 free — **unchanged**; rig vLLM never restarted |
| Contract validation | 4/4 examples (schema + pydantic) |
| Backend tests | **76 passed** (incl. 15 `/hub`) |

---

## 5. Backend (Urvi) — what exists and the integration

**Stack:** Flask 3.1 + flask-smorest, JWT/argon2, SQLAlchemy 2 + Alembic, PostgreSQL 17 +
TimescaleDB 2.30.2 (Docker, `:5433`), APScheduler worker, Twilio/FCM channels, OpenFDA NDC
lookup. 17 domain tables + `hub_*` tables (migration `0003`).

**Features:** auth, caregiver links, prescriptions (draft → scheduled → active, versioned,
supersede), dose windows/schedules (DST-safe, idempotent generation), dose events with
confirm/skip/late rules, missed-dose job + alerts, notifications (in-app/SMS/push), inventory +
refills, adherence (local-day buckets), vision observation ingest with fuzzy matching.

**`/hub` compatibility layer** (Sinchana's contract, no auth, `HUB_ENABLED=true`, localhost only):
`GET /health`, `GET /state`, `POST /medications/{id}/doses|remind|counts|refill`, `PATCH|DELETE
/medications/{id}`, `POST /scans` (photo), `POST /scans/{id}/photos`, `GET|DELETE /scans/{id}`,
`POST /scans/{id}/complete`, `GET /adherence`, `PUT /settings`, `GET /export`, `DELETE /data`,
`POST /demo/advance|reset`. It calls inference with the patient's tracked meds as hints and
prefers `label_meta` over its own regex fallback.

**Verified live by the orchestrator:** migrate + her 15 hub tests pass; photo → **9/9 fields**
from real inference; second photo → multi-frame; complete → new medication persisted (+ duplicate
refusal “already being tracked”); UI pointed at `/hub` with CORS from `:5199`.

---

## 6. Web dashboard (Sinchana)

React 18 + Vite 5 + Tailwind + React Router. Pages: Home (supply bottles, today's doses,
caregiver texts), Scan (camera + verify + added), History, Settings. Contract docs:
`frontend/docs/api-contract.md` + `frontend/docs/inference-contract.md` + fixtures.
Run: `cd frontend && npm install && npm run dev` with `VITE_API_URL` (or `.env.local`).
Headless-Chrome verification: Home renders patient “Ada”, caregiver “Cara”, three medications
with live stock and today's doses, badge “Connected to Ada's hub”.

---

## 7. Local test console (no iOS needed)

`scripts/local_scan.sh --daemon` → **http://127.0.0.1:8400**
- upload / webcam capture; **live mode** (~4 fps quality+bottle+label guidance with boxes and
  auto-scan); **Long label (3-frame rotation)** mode with thumbnails and fused result;
  raw JSON; scan bundles saved to `~/.medcheck/scans/` (single + all multi frames) for debugging.
- `MEDCHECK_YOLO_MODEL` is auto-enabled when `models/yolo11n.onnx` exists.

## 8. Voice (ElevenLabs)

Root `.env` (mode 600, gitignored) holds `ELEVENLABS_API_KEY` (verified: 21 voices) +
`ELEVENLABS_VOICE_ID`/`_MODEL_ID`; `.env.example` files document names.
`scripts/tts_smoke.py` synthesises real cloud audio (sample: “Rosa, it's time for your
Metformin. Take one tablet with breakfast.” → 71.5 KiB in **1.29 s**, voice *Sarah*).
Planned: Twilio `<Say>`/`<Play>` for reminders (backend).

---

## 9. How to run everything (verified)

```bash
# One command, whole stack (backend /hub + inference + UI):
scripts/run_ui_demo.sh                  # UI http://127.0.0.1:5199
scripts/run_ui_demo.sh --adapter        # use the file-backed fallback hub instead
scripts/run_ui_demo.sh --stop

# Inference only
scripts/setup_full_env.sh               # .venv-full (Python 3.11)
.venv-full/bin/python -m pytest services tests/integration -q      # 522 passed
MEDCHECK_API_MODE=real .venv-full/bin/uvicorn services.api.main:app --port 8300

# Local camera console (live + long-label)
scripts/local_scan.sh --daemon          # :8400

# Backend alone
cd backend && docker compose up -d db && FLASK_APP=wsgi:app python -m flask db upgrade
SEED_PASSWORD=… python scripts/seed.py
HUB_ENABLED=true CORS_ORIGINS='*' gunicorn -b 127.0.0.1:8000 wsgi:app

# Rig / GPU (read-only)
scripts/gpu_probe.sh ; scripts/download_models.sh ; scripts/tts_smoke.py --play
```

**Demo data:** patient `demo.patient@example.com`, password from `SEED_PASSWORD`
(`medcheck-demo-password` locally), caregiver `demo.caregiver@example.com`; a reset is
`docker compose down -v && up -d db && flask db upgrade && seed`.

---

## 10. Verification ledger (who proved what)

- **Contracts:** 4/4 examples schema+pydantic; version bumps keep old tests green.
- **Vision:** 118 tests; noise regression found by the merged suite and fixed; real-photo
  clipped-guard + YOLO checks on Varesh's own scans.
- **OCR:** 164 tests; crop-path spacing + degenerate-text fixes; label_meta extraction; fusion
  verified on overlapping long-label crops.
- **VLM:** 134 tests; 24-image eval; live escalation 541 ms → 1.7 s only when needed; VRAM flat.
- **API:** 102 tests; mock + real; multi-frame endpoint; auth/CORS; live smoke.
- **Integration:** 4 orchestrator tests incl. backend-fit; 522 total.
- **Backend:** 76 tests (15 hub) run independently by the orchestrator; live flows verified.
- **Dashboard:** headless render with real data; CORS verified from its origin.
- **Console/tools:** live + long-label flows exercised on synthetic crops and real photos.

---

## 11. Known limitations & gaps (honest)

1. **Real-photo accuracy is not yet measured** against a labeled real dataset (tests/eval are
   synthetic). Real labels exposed OCR word-spacing and glyph issues that were fixed, but label
   diversity (curved, low light, glare) is untested at scale.
2. **`/hub` has no authentication** and is localhost-only by design; it must never be exposed.
   iOS over the LAN/Tailscale would need token auth and HTTPS (browser camera requires
   `localhost` or HTTPS).
3. **iOS app** does not exist yet (Aparajita still building); contracts are ready for it.
4. **Bottle detection** is COCO “bottle” (YOLO11n); a medication-specific detector would improve
   recall (some real photos still yield no bottle box; label OCR still works).
5. **VLM latency on large photos** (≈2.4 s) — no downscale before sending.
6. **Alerts/events/reminders** are served by the backend, but the dashboard's event feed is
   minimal; wearable integration is future.
7. **No deployment/hosting**; everything is local demo (Mac + home rig).
8. `main` is still empty on the remote; no PR from `feat/integration` yet.

---

## 12. Next capabilities (recommended, prioritized)

1. **Real-photo accuracy harness** — collect ~50–100 consenting/redacted real labels, measure
   per-field precision/recall and latency, tune OCR/VLM thresholds and prompts. Highest value:
   it converts our synthetic numbers into defensible accuracy.
2. **Real-time guidance in the product UI** — a light endpoint (`/v1/frame-quality`) or
   WebSocket using the ~20 ms vision path so the dashboard/iOS shows live “hold steady / move
   closer / rotate” before capture (the console already proves the UX).
3. **Guided multi-frame capture in the product UI** — step 1/2/3 prompts + clipped-label hints
   (inference already returns them) so long labels work without the console.
4. **Auth/TLS for `/hub` (or `/api/v1` bridging)** — token in the hub + HTTPS via reverse proxy
   or uvicorn certs, so a phone on Tailscale can use it safely.
5. **VLM efficiency** — downscale images before the VLM call (target <1 s), and cache the ONNX
   sessions/prefix; optionally run OCR/YOLO on the rig GPU when the Mac is slow.
6. **Voice reminders** — wire ElevenLabs into the backend reminder job (Twilio `<Say>`/`<Play>`),
   finishing the low-vision loop.
7. **Medication-specific detection** — fine-tune/replace the YOLO bottle class with a
   medication-bottle model; add a tray/pill-counter capability if the wearable needs it.
8. **Metrics/observability** — expose latency percentiles, escalation rate and per-stage timing
   (we already emit `timing.stages`) for the demo dashboard and error triage.
9. **Demo resilience** — precomputed scan fallbacks for no-network demos; health badges in the
   UI; deterministic seed reset button.
10. **`main` + PR hygiene** — once the team agrees, open a PR from `feat/integration` and make it
    the default branch; tag a demo release.

---

## 13. Condensed timeline

1. Environment identified (upstream Pi 1.1.0 + October Bus; 5 agent terminals; orchestrator
   terminal bus-restricted → `octoberctl` dispatch + transcript-inbound).
2. Repo + contracts frozen; four worker worktrees; AGENTS.md ownership/safety rules.
3. M1 mock API → M2 real OCR-first pipeline + matcher + vision/OCR handoff → M3 escalation
   efficiency + reconciliation → M4 contract v1.1 `dose` + backend fit → M5 ONNX YOLO → M6
   auth/CORS → M7 multi-frame capture (v1.2) → M8 real-photo quality fixes → M9 label_meta
   (v1.3) → M10/M10b crop spacing + display normalization.
4. Local console built (daemon, live mode, long-label rotation, debug bundles, TTS).
5. Cross-team: verified Urvi's backend, found & fixed the `.gitignore` models blocker; her
   `/hub` layer merged; UI pointed at it; full stack verified with a headless render.
6. All 9 original gates complete; 522 inference + 76 backend tests green.

---

## 14. Glossary

- **Hub** — the API the dashboard talks to (`/hub` on the backend; or the fallback adapter).
- **OCR-first** — read with OCR, escalate to the VLM only on weak/mismatched identity.
- **Escalation** — invoking Qwen3-VL when identity fields are weak or registry-mismatched.
- **Multi-frame fusion** — fusing text from 2–6 rotated frames into one result (v1.2).
- **label_meta** — pharmacy-label fields (QTY, refills, pharmacy, prescriber, schedule) (v1.3).
- **Clipped** — label runs off the frame edge → “rotate the bottle” guidance.
- **Gateway / console / adapter** — inference `:8300` / dev console `:8400` / fallback hub `:8500`.
