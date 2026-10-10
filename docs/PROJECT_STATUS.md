# HackRU26 · MedCheck — Complete Development Status (LLM Context File)

> **How to use:** paste this whole file into ChatGPT (or any LLM) as context and say:
> *"This is the current state of our project. Keep it as ground truth; help me continue from
> here."* It is written to be self-contained — architecture, contracts, commands,
> verified numbers, open issues. Maintained by the inference orchestrator (Apollo) and
> refreshed at every milestone.
>
> **Last updated:** 2026-10-10 ~17:35 UTC · **Repo:** https://github.com/Haadesx/HackRU26
> **Integration branch:** `feat/inference-medcheck` (main is intentionally untouched)

---

## 1. Product

**MedCheck** (HackRU 2026) — scan a medication bottle with a phone/webcam, read the label,
and manage the medication safely:

1. camera → **inference** reads the label (vision → OCR → optional VLM)
2. structured result (name, strength, form, instructions, uncertainty) with a safety block
3. clients pass the result to the **backend**, which owns prescriptions, dose schedules,
   reminders, inventory, refills, adherence — and only the backend/user can confirm a dose
4. **iOS app** (camera UI) and **web UI** consume both

**Non-negotiable safety rules (enforced in code + contracts):**
- A scan **never** records or implies ingestion; carrying/opening a bottle is not proof.
- Inference never authorizes dosing; the backend owns schedule/dose/inventory authority.
- Every structured field carries `confidence` + `source` (`ocr|vlm|registry|none`) and raw
  source text is preserved verbatim. No fabricated drug names/strengths/instructions.
- Tablet **strength** (e.g. 500 mg) is never confused with **quantity per dose** (e.g. “1 tablet”).

---

## 2. Team, branches, repository

| Who | Component | Branch | Status |
|---|---|---|---|
| Varesh (owner/operator) | coordination, testing | — | present |
| Sinchana | Web UI | `feat/ui-sinchana` | **not pushed yet** |
| Aparajita | iOS app | `feat/ios-aparajita` | **not pushed yet** (frontend in development) |
| Urvi | Backend + DB | `feat/backend-urvi` | pushed `85fc33f`; **blocked: missing `app/models` package** (see §7) |
| Inference subteam | AI inference subsystem | `feat/inference-medcheck` | complete M1–M4, M5 in flight |

**Inference subteam = 5 coding agents** running in October Desktop (Pi harness, October
Bus for coordination):
- **Apollo** — orchestrator / integration / docs (terminal `term-mv2rzwwy-f`)
- **Atlas** — PI-1 Vision (`.worktrees/pi-1-vision`, branch `feat/vision-atlas`)
- **Orion** — PI-2 OCR (`.worktrees/pi-2-ocr`, `feat/ocr-orion`)
- **Juno** — PI-3 VLM (`.worktrees/pi-3-vlm`, `feat/vlm-juno`)
- **Athena** — PI-4 API (`.worktrees/pi-4-api`, `feat/api-athena`)

**Git facts:** one repo, one worktree per worker; only the orchestrator merges into the
integration branch and pushes. Nothing has been merged into `main`, and no force-push ever.
Remote currently has exactly two branches: `feat/inference-medcheck` and `feat/backend-urvi`.

**Key commits (integration branch):** contract freeze `51569fd` → real pipeline merges
`b6bbbef`/`a49afd0`/`5b60648`/`91a5c83` → noise fix `34480c3` → M3 merges `fc5ff80`,
`4d0d32c` → contract v1.1 `3bdea53` → M4 merges `f284f3b`, `aa3ccd3`.
Latest push: `362a2b0`-series (M4 docs). Worker tips: Atlas `ae1c3a8`, Orion `cb31f7e`,
Juno `16ca2dd`, Athena `2e53239`.

---

## 3. System architecture (current)

```
                 ┌────────────────────── iOS (Aparajita) / Web UI (Sinchana) ──────────────────────┐
                 │  camera frame                                                                     │
                 ▼                                                                                   │
   POST :8300/v1/scan (multipart image)                                                              │
                 │                                                                                   │
        ┌────────▼─────────┐   services/vision    quality (blur/exposure/glare) + guidance,        │
        │ Inference gateway│   (PI-1 Atlas)       bottle detect (heuristic | YOLO ONNX |        │
        │ FastAPI :8300    │                      ultralytics), label bbox, crop_label(),           │
        │ (PI-4 Athena)    │                      real-time /api/live path (~20 ms)                  │
        └────────┬─────────┘                                                                         │
                 │  services/ocr (PI-2 Orion): RapidOCR/ONNX → raw text + boxes →                 │
                 │  name/strength/form/instructions + v1.1 dose {quantity,unit} +                 │
                 │  registered-candidate matcher (fuzzy, score in [0,1])                          │
                 │  services/vlm (PI-3 Juno): Qwen3-VL via existing vLLM on the home rig,          │
                 │  escalation only when identity-critical fields are weak/mismatched              │
                 ▼                                                                                   │
   ScanResponse (contract v1.1, JSON)  ────────────────────────────────────────────────────────────┘
                 │
                 ▼  client maps: drug_name ← medication.name.value ; strength ← {value,unit} ;
                    quantity ← instructions.dose.quantity (fallback 1) ; event_id client-generated
   POST :<backend>/api/v1/scans   (Urvi: Flask + Postgres/TimescaleDB)
                 → matches to a due dose (never changes status), returns match/timing/quantity_check
   POST /api/v1/doses/{id}/confirm  → the ONLY thing that records a dose (tap-to-confirm)
```

---

## 4. Inference subsystem (built, tested, live-verified)

**Layout:** `services/{common,vision,ocr,vlm,api}` + `contracts/v1` + `samples/` +
`scripts/` + `tools/local_scan/` + `tests/integration/`.

### 4.1 HTTP API (port 8300, FastAPI)
- `GET /health` → `{status, service:"medcheck-inference", version, uptime_s}`
- `GET /ready` → `200 {ready, mode, components{vision,ocr,pipeline,vlm}}` or `503`
- `POST /v1/scan` multipart: `image` (JPEG/PNG ≤12 MiB), optional `client`, `mode`
  (`auto|mock|real`), `hints` (JSON string, e.g. `{"known_candidates":[{"name":"Metformin","strength":{"value":500,"unit":"mg"}}]}`)
- Errors: 400 bad request envelope, 413 too large, 415 unsupported media, 504 timeout;
  domain failures return HTTP 200 with `status:"error"` + `error{code,message}`.

### 4.2 Contract v1.1 (frozen; additive over v1.0)
`ScanResponse` fields (all present): `contract_version:"1.2.0"`, `request_id`,
`status ∈ ok|needs_rescan|uncertain|no_medication_found|error`, `mode ∈ mock|real`,
`frame_quality{acceptable,score,blur,exposure,glare,guidance[]}`,
`bottle{detected,confidence,bbox?}`, `label{detected,confidence,bbox?,text}`,
`medication{name,strength,form,manufacturer}` each `{value,confidence,source}`,
`instructions{raw_text, parsed[{kind∈dose|frequency|route|duration|warning|other,text}],
dose{quantity>0|null,unit,confidence,source}}` (**v1.1, additive**),
`candidates[{name,strength?,score,source}]`,
`interpretation{available,summary?,source:"vlm"?,model?}`,
`uncertainty{level∈low|medium|high,reasons[],rescan_required}`,
`timing{total_ms,stages{}}`, `capture{frames_requested,frames_used,fusion,per_frame[]}`
(v1.2, multi-frame label capture; optional),
`safety{disclaimer,ingestion_not_inferred:true,backend_authoritative:true}`, `error|null`.
BBoxes normalized `[0,1]`. JSON schemas: `contracts/v1/*.schema.json`; pydantic mirror:
`services/common/contract.py`. Versioning: additive → minor bump; breaking → new `vN/`.

### 4.3 Measured results (all verified, not reported by others)
- Unit/integration tests on merged tree: **349 passed / 0 failed** (vision 99 · ocr 75 ·
  vlm 104 · api 62 · integration 2 + backend-fit).
- OCR accuracy on synthetic set: extraction 33/33 name/strength/form; end-to-end rendered
  images 8/8; macro F1 OCR-only **0.99**; 24-image eval: VLM-only 1.0, hybrid 0.99.
- Latency (Mac CPU, real mode): clean scan **~0.54 s** (OCR dominant ~0.4 s, **zero VLM
  calls**); candidate-mismatch scan → VLM **~1.7 s** (Qwen/Qwen3-VL-8B-Instruct-FP8);
  blurry → `needs_rescan` in **~20 ms**; live vision-only pass **~20 ms** after warmup.
- Concurrency: 8 simultaneous real scans ≈ **2.1 s wall** (~3.8 scans/s), no errors.
- GPU: existing rig vLLM **18,383 MiB used / 13,706 MiB free — unchanged** across every
  call; the service was never restarted. Rig also runs Ollama, Postgres, Mongo, echo services.
- Wake/bus: worker agents receive October-bus wakes end-to-end; the orchestrator terminal
  is a `user-shell` terminal and is refused at October's hook-admission layer
  (`{"ok":false,"stale":true}`) — orchestrator outbound uses `octoberctl terminal input`
  and inbound reads worker transcripts (works reliably).

### 4.4 Local test console (works without iOS)
`scripts/local_scan.sh --daemon` → UI at **http://127.0.0.1:8400** (real engine; `--no-vlm`,
`--mock`, `--stop`, `--status`). Features: upload/webcam capture, **live mode** (continuous
~4 fps quality+bottle+label guidance with boxes, auto-scan when readable, 6 s throttle),
raw JSON, debug bundles saved to `~/.medcheck/scans/` (image+response, last 40; never
committed). Also `scripts/scan_demo.sh`, `scripts/gpu_probe.sh`,
`scripts/validate_contract.py`, `scripts/setup_full_env.sh` (builds `.venv-full`).

### 4.5 Real-photo findings (important)
Testing with real medication photos (kept local, not committed) showed:
- the CPU color/edge bottle heuristic **fails on real photos** (0/3 detections);
- OCR/label detection still works (full-frame), VLM rescues weak fields;
- **YOLO11n ONNX (COCO class `bottle`)** detected a real bottle at conf 0.485 where the
  heuristic found nothing, at ~60 ms CPU — **M5 integrated it** as the default detector
  backend (`MEDCHECK_YOLO_MODEL=models/yolo11n.onnx`, onnxruntime, no torch, heuristic
  fallback; `MEDCHECK_YOLO_CONF` threshold). The local console auto-enables it when
  `models/yolo11n.onnx` exists (`scripts/download_models.sh`, sha256 `634279b4…`);
  verified through `/api/live` and full scans (bottle 0.51, warm live pass 145–160 ms).

---

## 5. Backend (Urvi) — integration contract

`feat/backend-urvi` @ `85fc33f`: Flask 3.1 + flask-smorest, `/api/v1`, JWT/argon2,
PostgreSQL 17 + **TimescaleDB** (hypertables `vision_observations`, `dose_outcomes`;
adherence aggregate), 17 tables + Alembic migrations, prescriptions (draft→active,
versioned), dose schedules/windows, dose events, scan ingest with fuzzy matching,
tap-to-confirm, missed-dose jobs, notifications (in-app/SMS/web-push), inventory, refills,
adherence. Docs: `docs/backend-urvi.md`, `db.md`.

**Scan ingest:** `POST /api/v1/scans` (JWT) body
`{event_id, user_id, drug_name, strength?{value,unit}, quantity, timestamp}` → response
`{match_status, dose_event, timing, quantity_check, candidates, safety{ingestion_not_inferred:true,...}}`.
Idempotent on `event_id`; a scan never changes dose status.
**Client mapping from inference:** `drug_name ← medication.name.value`,
`strength ← medication.strength`, `quantity ← instructions.dose.quantity` (v1.1) with
fallback 1 only when the label states none, `timestamp` client-side, `event_id` UUID.
Orchestrator test `tests/integration/test_backend_fit.py` proves this mapping (green).

---

## 6. Web UI / iOS status

- No branches pushed yet for `feat/ui-sinchana` or `feat/ios-aparajita`.
- They should start against **contract v1.1** (`contracts/` + `services/api/HANDOFF.md`),
  and can develop UI against `mode:mock` immediately.
- iOS is blocked on frontend progress (per Varesh); local console covers camera testing in
  the meantime.

---

## 7. Current blockers / open decisions

1. **Urvi's branch is missing `backend/app/models/`** — silently excluded by an
   over-broad `.gitignore` rule (`models/`, meant for ML weights) from an earlier
   inference commit. Fresh checkout → `ModuleNotFoundError: app.models`; her tests can't
   run. **Fixed on our side** (`179c4d6`: `/models/` anchored). She must:
   `git fetch && git merge origin/feat/inference-medcheck && git add backend/app/models && commit && push`.
2. **Auth/TLS** for the inference gateway: none yet (localhost only). Needed before iOS
   device → Mac/rig traffic beyond local testing.
3. **Candidate registry source**: inference matcher consumes `hints.known_candidates`;
   long-term the backend/user's medication list should feed it.
4. **Multi-frame capture (M7, in flight)** — long labels read across rotated frames:
   contract v1.2 `capture` block + `POST /v1/scan/multi` frozen (`600c52c`); Orion text
   fusion, Atlas clipped-label guidance, Athena endpoint, Juno multi-image VLM; console
   long-label UI built (activates when the endpoint lands).
5. **YOLO recall** — real-photo recall is partial (1 strong, 1 weak, 1 none in the
   sample set); heuristic/flat-label fallbacks stay. Threshold configurable.
5. **VLM cost**: escalation triggers were tuned in M3 (identity-critical fields only);
   registry-mismatch still escalates by design (~1.7 s).

---

## 8. How to run (verified commands)

```bash
# 1. Full environment + test suite
scripts/setup_full_env.sh                       # creates .venv-full (Python 3.11)
.venv-full/bin/python -m pytest services tests/integration -q     # → 349 passed
scripts/download_models.sh                      # YOLO11n ONNX (gitignored weights)
scripts/local_scan.sh --daemon                  # console auto-enables YOLO when present

# 2. Local camera/label test console (no iOS needed)
scripts/local_scan.sh --daemon                  # → http://127.0.0.1:8400
scripts/local_scan.sh --status | --stop

# 3. API only
MEDCHECK_API_MODE=real .venv-full/bin/uvicorn services.api.main:app --port 8300
curl -s -F "image=@samples/label_metformin.png" -F "mode=real" localhost:8300/v1/scan

# 4. Contract check
.venv-full/bin/python scripts/validate_contract.py

# 5. Rig / GPU probe (read-only; Tailscale host `ai-rig`)
scripts/gpu_probe.sh
```

Environment names (values live in `~/.medcheck/vllm.env`, mode 600 — never committed):
`MEDCHECK_API_MODE`, `MEDCHECK_VLM_ENABLED`, `MEDCHECK_VLM_BASE_URL`,
`MEDCHECK_VLM_MODEL`, `MEDCHECK_VLM_API_KEY`, `MEDCHECK_YOLO_MODEL`,
`MEDCHECK_YOLO_CONF`, `MEDCHECK_SCAN_TIMEOUT_S`, `MEDCHECK_SAVE_SCANS`.
Hardware: dev = Apple-silicon Mac (CPU inference); rig = Ubuntu + RTX 5090 (32 GB, ~14 GB
free) at `hermes-linux` (Tailscale `ai-rig.tail6d5242.ts.net`), serving the existing
`Qwen/Qwen3-VL-8B-Instruct-FP8` (vLLM, Docker container `echo-vllm`, tailnet :8100).
Do not restart rig services or install drivers; one intrusive GPU job at a time.

---

## 9. Condensed development log

1. **Env identified**: upstream Pi 1.1.0 under October Desktop (October Bus extension +
   `october-bus-static` MCP); 5 agent terminals; workers activated, orchestrator terminal
   restricted by October's hook admission (documented workaround).
2. **Repo + contracts** frozen (`51569fd`), 4 worktrees, AGENTS.md rules (ownership,
   safety, GPU, reporting, docs).
3. **M1**: vision (quality/detect/label), OCR (RapidOCR + extraction), VLM (adapter +
   eval + benchmark), API (mock gateway) — all merged + independently re-verified.
4. **M2**: real OCR-first pipeline in the API, candidate matcher, vision-OCR handoff,
   escalation triggers; cross-service noise regression found by the merged suite and
   fixed (vision false-positive on Gaussian noise).
5. **M3**: escalation efficiency (clean scans no longer call the VLM), reconcile
   normalization, HANDOFF; live verification: 541 ms clean / 1696 ms VLM-on-mismatch.
6. **Contract v1.1** (additive `instructions.dose`) + **M4** (Orion extraction, Athena
   bridge) → backend-fit test green; suite 326/326.
7. **Cross-team**: verified Urvi's backend (clean merge, contract-aligned, TimescaleDB
   healthy) and caught the `.gitignore` models-package blocker; fixed on our side.
8. **Local console** built (daemon, live mode, debug bundles); real-photo testing by
   Varesh exposed the bottle-detection gap → **M5 YOLO ONNX integrated and enabled**
   (real bottle 0.51 via `analyze_frame`/`/api/live`; suite 349/349).
9. **M6 done** (network readiness: optional bearer auth + CORS + bind/TLS docs; suite 355).
10. **Contract v1.2 + M7 dispatched** (multi-frame label capture: capture block +
    `/v1/scan/multi`; fusion, clipped-label guidance, endpoint, multi-image VLM; console
    long-label UI built). Contract `600c52c`; suite 358/358 before M7 merges.

---

## 10. Glossary

- **October Desktop / October Bus / `octoberctl`** — the multi-agent environment; bus
  messages, tasks, terminals; `octoberctl terminal input --id … --epoch … --data …` is
  used by the orchestrator to dispatch work into worker terminals.
- **PI-1…PI-4** — the four worker agents and their service ownership.
- **OCR-first** — read the label with OCR, only escalate to the VLM when identity is weak
  or mismatched (cost/latency control).
- **Escalation** — the VLM (Qwen3-VL) is invoked only for weak/mismatched identity fields.
- **Debug bundle** — saved local scan (image + response JSON) used to debug real photos.
