# MedCheck Inference Subsystem — Technical Documentation

- **Component:** MedCheck AI inference subsystem (HackRU 2026 / HackRU26)
- **Developer / team:** inference subteam — **Apollo** (orchestrator/integration) with worker
  agents **Atlas** (PI-1 Vision), **Orion** (PI-2 OCR), **Juno** (PI-3 VLM),
  **Athena** (PI-4 API), directed by **Varesh** (human owner).
- **Integration branch:** `feat/inference-medcheck` (never `main`)
- **Remote:** `https://github.com/Haadesx/HackRU26` (`origin`; repo was empty at first push)
- **Doc rule:** maintained continuously; update in the same task as any code/config change.
- **Status:** inference modules individually complete & tested on feature branches; the
  orchestrator is merging them into the integration branch (see §J for the live log).

> Interface note: this document describes the inference subsystem only. The companion
> HackRU26 components — Web UI (Sinchana), iOS app (Aparajita), Backend + DB (Urvi) — are
> documented by their own owners in `docs/ui-sinchana.md`, `docs/ios-aparajita.md`,
> `docs/backend-urvi.md`. Nothing in those files is modified here.

---

## A. Component overview

**What it does.** Given a photo of a medication bottle, MedCheck inference:

1. evaluates camera-frame quality and emits real-time capture guidance,
2. detects the bottle and localizes the label,
3. reads the label text (OCR) and extracts structured medication fields,
4. matches read text against registered candidates,
5. optionally escalates uncertain reads to the existing Qwen3-VL model,
6. returns a fully structured, source-attributed, uncertainty-aware response with a
   mandatory safety block.

**Architecture (decided, frozen):** **OCR-first with optional existing-VLM fallback.**
The existing model is `Qwen/Qwen3-VL-8B-Instruct-FP8` served by vLLM on the home rig.
No second VLM is launched.

**Responsibilities.** Inference only. The backend (Urvi) owns schedules, dose history,
inventory, and prescription authority. Inference never authorizes consumption and never
treats holding/opening a bottle as ingestion.

**Technologies.** Python 3.11 (uv-managed venvs), pydantic v2 contract models,
OpenCV/Pillow/numpy (vision), RapidOCR + ONNX Runtime (OCR), httpx (VLM client),
FastAPI + uvicorn (gateway), pytest (tests), Git worktrees (agent isolation),
October Bus (agent coordination; see §H).

**Current implementation status.**

| Part | Status | Branch / commit |
|---|---|---|
| Frozen v1 contract (schemas + pydantic mirror) | ✅ implemented, ✅ validated | `feat/inference-medcheck` |
| PI-4 API: mock + real OCR-first pipeline + **M3 escalation wiring** | ✅ implemented, ✅ orchestrator-verified, ✅ MERGED | `feat/api-athena` → merges `b6bbbef`, `4d0d32c` |
| PI-2 OCR + extraction + **candidate matcher** | ✅ implemented, ✅ orchestrator-verified, ✅ MERGED | `feat/ocr-orion` `09c41d3` → merge `a49afd0` |
| PI-1 Vision: quality/detect/label + **crop_label handoff** | ✅ implemented, ✅ orchestrator-verified, ✅ MERGED + noise regression **fixed** (`ae1c3a8`) | `feat/vision-atlas` → merges `5b60648` + `ae1c3a8` |
| PI-3 VLM adapter + eval + **escalation triggers + normalization** | ✅ implemented, ✅ orchestrator-verified, ✅ MERGED | `feat/vlm-juno` → merges `91a5c83`, `fc5ff80` |
| Real-mode end-to-end (Mac→Tailscale→rig vLLM through the API) | ✅ **verified** (2026-10-10): VLM stage 1745 ms, VRAM unchanged | `feat/inference-medcheck` |
| Full-system acceptance on merged tree | ✅ **293 passed / 0 failed** (fresh env, M3 merged) | `feat/inference-medcheck` |

---

## B. Everything implemented

### B.1 Orchestrator (repo root, this branch)

- **Repo skeleton** with strict per-service ownership (`AGENTS.md`).
- **Frozen v1 contract**: `contracts/v1/scan_request.schema.json`,
  `contracts/v1/scan_response.schema.json`, examples, and the pydantic mirror
  `services/common/contract.py`. Validated 3/3 examples against both schema and models.
- **Synthetic test labels** (no real medication data): `samples/label_metformin.png`,
  `label_lisinopril.png`, plus blurry/dark degraded variants (Pillow-generated).
- **Tooling**: `scripts/validate_contract.py` (schema+pydantic check),
  `scripts/scan_demo.sh` (health/ready/scan smoke), `scripts/gpu_probe.sh`
  (read-only rig + vLLM check).
- **Integration harness**: `tests/integration/test_api_contract.py` (ASGI in-process:
  health/ready/scan contract validation, non-image rejection, oversize rejection).
- **October Bus integration** verified and used for all five agents (details §H).

### B.2 PI-1 Vision (`services/vision/**`, Atlas, HEAD `f55025c`)

Implemented:
- `preprocess.py` — Pillow decode, EXIF orientation, resize policy (never upscales),
  optional CLAHE/denoise, `enhance_for_ocr` helper.
- `quality.py` — contrast-normalized variance-of-Laplacian blur, luma/clipping exposure,
  saturated-blob glare; scores in `[0,1]`, `acceptable` flag, ordered guidance strings.
- `detector.py` — `YoloBottleDetector` adapter (ultralytics, CUDA only if torch reports a
  GPU, `model_path` config) with a deterministic **CPU color/edge heuristic fallback**;
  failures degrade gracefully instead of crashing.
- `label.py` — bright low-chroma region localization inside bottle bbox w/ low-confidence
  fallback band.
- `pipeline.py` — public `analyze_frame(image_bytes, hints) -> VisionResult` (quality,
  bottle, label, guidance, timing, detector info).
- Tests: 46 (worker-reported green, 0.60 s, offline, Mac CPU, no torch).

Calibration from synthetic fixtures (worker-reported): sharp frame quality `1.0`,
bottle IoU `0.868`, label IoU `0.843`; blurry/dark/bright/glare fail with guidance.

### B.3 PI-2 OCR (`services/ocr/**`, Orion, HEAD `987dd88`)

Implemented:
- **Stack decision** documented in `services/ocr/DECISION.md`: `rapidocr-onnxruntime==1.4.4`
  + ONNX Runtime (PP-OCRv4 ONNX models in-wheel, no torch, CPU-only, offline after
  install). Alternatives considered: easyocr, paddleocr.
- `engine.py` — `read_text(image, bbox=None)` → verbatim `raw_text` + normalized
  contract-v1 line boxes; bbox crop re-mapped to full-frame coordinates.
- `extract.py` — name / strength / form / manufacturer with per-field confidence +
  `source:"ocr"`; contract-shaped `medication_contract()` / `instructions_contract()`.
- `parse_instructions()` — `dose|frequency|route|duration|warning|other`, each item a
  verbatim substring; package counts never treated as doses.
- **Safety behavior**: unknown tokens returned verbatim with ≤0.5 confidence (never
  fabricated); strength (`mg/mcg/g/ml/IU/%`) never taken from “Take 2 tablets”.
- Tests: 25 (worker-reported green) incl. 33-line extraction set precision = recall =
  1.000 and end-to-end rendered-images OCR 8/8 name, 8/8 strength, 8/8 form, including
  OCR noise cases (`Metform1n 5O0mg`, `L1SINOPRIL`, glued names).

### B.4 PI-3 VLM (`services/vlm/**`, Juno, HEAD `9ac2305`)

Implemented:
- `client.py` — `Qwen3VLClient`, OpenAI-compatible adapter for the existing rig vLLM
  (env-configured base URL/model/key, timeouts, retries off by default, OCR-verify
  prompt mode, lenient JSON parsing).
- `reconcile.py` — `should_use_vlm()` + `reconcile_fields()` with source attribution.
- Synthetic dataset: `dataset/` — 24 generated labeled images + `ground_truth.json`.
- Eval harness: `eval/` (engines: OCR-only, VLM-only, OCR-first+VLM-on-uncertainty;
  metrics; `run_eval.py`), local Tesseract baseline.
- Benchmarks: `benchmarks/gpu_bench.py` + `results.json`.
- **Measured results** (`EVAL.md`, 24 images, 40 sequential calls within the granted
  120-call window; service never restarted):
  - macro F1 — OCR-only **0.99**, VLM-only **1.0**, OCR-first + VLM-on-uncertainty **0.993**
  - escalation rate **8.3 %**; VLM p50 **1584.8 ms**, p90 **1683.6 ms**, **0.63 img/s**
  - VRAM: 18,383 / 32,607 MiB used → 13,706 MiB free; no VRAM growth observed
  - finding: the single surviving OCR error (`Metformin HCI` @0.87) is confidence-blind
    → recommendation: add registry/candidate-match validation as escalation trigger
- Tests: 79 (worker-reported green; mocked HTTP + local OCR, no GPU).

### B.5 PI-4 API (`services/api/**`, Athena, HEAD `a855318`)

Implemented:
- `main.py` — FastAPI app: `GET /health`, `GET /ready` (200 in mock mode; 503 when
  `MEDCHECK_API_MODE=real` and components unavailable), `POST /v1/scan` (multipart
  `image` + optional `client`, `mode`, `hints`).
- Contract enforcement: JPEG/PNG content-type + magic gate → 415; 12 MiB → 413; bad
  hints/mode/client → 400 envelope; 15 s scan budget → 504; domain `INVALID_IMAGE`
  stays HTTP 200 with `status:"error"`.
- Mock mode: deterministic fixture selection via `sha256(image, client, hints)` across 5
  synthetic fixtures; always `mode:"mock"`; mandatory safety block; no fabricated drug
  names.
- `pipeline.py` — `ScanPipeline` protocol + `ScanContext` + `get_pipeline()` seam ready
  for real Vision→OCR→VLM wiring.
- `fixtures.py` — synthetic mock fixtures. `HANDOFF.md` — curl/env/error-code handoff doc.
- Tests: 40 (worker-reported green, includes JSON Schema validation of every HTTP payload
  and all contract examples). Worker also ran the orchestrator integration harness
  (2 passed) against an isolated copy.

**Mock / placeholder functionality:** the API currently serves only mock results in
practice; real component wiring is the next integration step (§K).

---

## C. Design and architectural decisions

| # | Decision | Rationale | Alternatives / notes |
|---|---|---|---|
| C1 | OCR-first, optional VLM fallback | Fast, cheap, deterministic reads; VLM reserved for uncertainty; existing rig VLM is shared | VLM-everything rejected: latency (≈1.6 s/call measured) + cost |
| C2 | One repo, five worktrees, per-service ownership | Parallel agents without file conflicts; reviewable merges | Single branch per agent rejected (conflicts); mono-worktree rejected |
| C3 | Contract frozen **before** implementation (JSON Schema + pydantic mirror) | Every service codes against one interface; iOS/backend can integrate without reading internals | Freeform dicts rejected (drift) |
| C4 | `contracts/**` + `services/common/**` are orchestrator-owned | Single change authority, versioned changes | Per-service schemas rejected |
| C5 | Structured fields carry `confidence` + `source`; raw text preserved verbatim | Safety + traceability; never fabricate | Cleaned text rejected |
| C6 | Mandatory `safety` block with `ingestion_not_inferred`/`backend_authoritative` = true | Medication safety invariant | — |
| C7 | Mock API first, real pipeline behind a seam (`ScanPipeline`) | Gate 3 unblocked iOS/backend immediately; swap without contract change | Waiting for real models rejected |
| C8 | Reuse existing vLLM (`echo-vllm`, Qwen3-VL-8B-FP8); never launch another VLM | GPU is shared (32 GB; 17-18 GiB already used); user directive | New vLLM rejected; local torch VLM rejected |
| C9 | Python 3.11 venvs per worktree via `uv`; system Python untouched | Reproducible, isolated; macOS dev + Linux rig | System Python rejected; conda not used |
| C10 | YOLO adapter with CPU heuristic fallback | Mac dev boxes have no GPU/torch; pipeline must run anywhere | torch-everywhere rejected |
| C11 | RapidOCR/ONNX for OCR | No torch, in-wheel PP-OCRv4, offline, works both platforms | easyocr/paddleocr heavier (see DECISION.md) |
| C12 | Deterministic mock selection by request hash | Reproducible tests; no random behavior | Random fixtures rejected |
| C13 | Integration branch = `feat/inference-medcheck` (per docs instruction, nothing lands on `main`) | Team `main` stays untouched until authorized | Direct-to-main rejected |
| C14 | Orchestrator dispatch over the sanctioned `octoberctl terminal input` because the orchestrator terminal is `user-shell` on the October Bus (mutating bus tools refused: `unactivated-terminal`) | October itself gates this; no invented layers; fixable by relaunching the terminal as an agent terminal | Editing October state rejected; Bus MCP `message_peer` unavailable to this terminal |
| C15 | Medication safety invariants are repository rules (`AGENTS.md`) | Non-negotiable product constraint | — |

Superseded decisions are preserved in §J (chronological log).

**Assumptions / limitations:**
- The rig vLLM is assumed to stay available at the recorded endpoint; tests must not
  require it (mock HTTP server used in unit tests).
- `MEDCHECK_API_MODE=real` is expected to return 503 until real wiring exists — by design.
- The October Bus inbound wake to the orchestrator terminal is **not yet verified** (see §I/§K).

---

## D. Dependencies and environment

### D.1 Orchestrator tooling (repo root `.venv`, local only; not required by the product)
- Python **3.11.15** (created with `uv venv .venv --python 3.11`)
- `pydantic` **2.14.0**, `jsonschema` **4.26.0**, `pillow` **12.3.0**
- Root `pyproject.toml`: requires-python `>=3.9`; core dep `pydantic>=2.6,<3`;
  extras: `api` (`fastapi>=0.110`, `uvicorn[standard]>=0.29`, `python-multipart>=0.0.9`),
  `dev` (`pytest>=8`, `httpx>=0.27`)

### D.2 Per-service requirements (owned by each service)

| Service | File | Pins (declared) |
|---|---|---|
| Vision | `services/vision/requirements.txt` | `numpy>=1.26,<3`, `opencv-python-headless>=4.9,<5`, `Pillow>=10.2,<12`, `pydantic>=2.6,<3` (+ optional `ultralytics` GPU path, dev file separate) |
| OCR | `services/ocr/requirements.txt` | `rapidocr-onnxruntime==1.4.4`, `onnxruntime==1.31.0`, `numpy==2.4.6`, `opencv-python==5.0.0.93`, `pyclipper==1.4.0`, `shapely==2.2.0`, `six==1.17.0`, `pyyaml==6.0.3`; tests: `pytest==9.1.1`, `pillow==12.3.0`; pinned transitives listed in file |
| VLM | `services/vlm/requirements.txt` | `pydantic>=2.6,<3`, `httpx>=0.27`, `pillow>=10`, `pytesseract>=0.3.10`, `pytest>=8` |
| API | `services/api/requirements.txt` | `fastapi>=0.110`, `uvicorn[standard]>=0.29`, `python-multipart>=0.0.9`, `pydantic>=2.6,<3`, `pytest>=8`, `httpx>=0.27`, `jsonschema>=4.21` |

### D.3 Environment variables (names only — values never documented/committed)

| Name | Purpose |
|---|---|
| `MEDCHECK_API_MODE` | `mock` (default) or `real` (503 until real components are wired) |
| `MEDCHECK_VLM_BASE_URL` | OpenAI-compatible vLLM base, e.g. `http://ai-rig.<tailnet>:8100/v1` |
| `MEDCHECK_VLM_MODEL` | `Qwen/Qwen3-VL-8B-Instruct-FP8` |
| `MEDCHECK_VLM_API_KEY` | Bearer token for the existing vLLM (stored only in `~/.medcheck/vllm.env`, mode 600, Mac + rig) |
| `OCTOBER_BUS_*` | Injected by October Desktop for all five agents (bus coordination) |

### D.4 External services / hardware
- **Home rig `hermes-linux`** (Ubuntu, RTX 5090 32 GB, Tailscale host `ai-rig.tail6d5242.ts.net`)
  - Docker container **`echo-vllm`** → tailnet `:8100` → Qwen3-VL-8B-FP8 under vLLM
    (max_model_len 16384). GPU at kickoff: 32,607 MiB total / 17,659 used / 14,430 free.
  - Also running: Ollama (`:11434`), `echo-mongo` (`:27018`), `echo-postgres` (`:5433`),
    and other echo/router/bridge services — **must not be stopped or restarted**.
- Python on the rig: **3.14.4**, no `uv` installed (rig-side scripts must account for this).

### D.5 Platform requirements
- macOS (dev): Python 3.11 via `uv`; no GPU needed for any test; `tesseract` binary needed
  only for the optional VLM eval baseline.
- Linux (rig): GPU optional; existing vLLM is HTTP-only from our side.

### D.6 Dependency reconciliation (verified 2026-10-10)
- `scripts/setup_full_env.sh` installs the union of all four services into `.venv-full`
  and the **full suite passes (277/277, 12 s)**: `numpy==2.4.6`,
  `opencv-python==5.0.0.93` (headless variant not required at runtime),
  `pillow==12.3.0`, `rapidocr-onnxruntime==1.4.4`, `onnxruntime==1.31.0`,
  `pyclipper==1.4.0`, `shapely==2.2.0`, `six==1.17.0`, `pyyaml==6.0.3`,
  `pytesseract>=0.3.10`, plus api/dev extras.
- `pytesseract` additionally needs the **`tesseract` binary** for the VLM eval baseline
  tests (`brew install tesseract` on macOS).
- Port **8300** reserved for this gateway; `echo-vllm` is shared and must not be
  restarted; rig Python is 3.14 with no `uv` (rig-side scripts must be stdlib-only or
  create their own env).

---

## E. APIs and data structures

### E.1 HTTP API (fixed contract, `contracts/v1`)

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/health` | — | `200 {"status":"ok","service":"medcheck-inference","version":str,"uptime_s":num}` |
| GET | `/ready` | — | `200 {"ready":true,"mode":"mock|real","components":{...}}` or `503 {"ready":false,...,"reasons":[...]}` |
| POST | `/v1/scan` | `multipart/form-data`: `image` (JPEG/PNG, ≤12 MiB, required), `client` (`ios|backend|test|unknown`), `mode` (`auto|mock|real`), `hints` (JSON string) | `200` `ScanResponse` (even for domain errors) ; transport errors: 400/413/415/504 |

`ScanResponse` top level (all fields required unless noted):
- `contract_version` = `"1.1.0"`, `request_id`, `status`
  (`ok|needs_rescan|uncertain|no_medication_found|error`), `mode` (`mock|real`)
- `frame_quality`: `acceptable`, `score`, `blur{score,is_blurry}`,
  `exposure{score,too_dark,too_bright}`, `glare{score,has_glare}`, `guidance[]`
- `bottle`: `detected`, `confidence`, `bbox{x,y,w,h}` (normalized 0–1)
- `label`: `detected`, `confidence`, `bbox?`, `text` (raw, verbatim)
- `medication`: `name{value,confidence,source}`, `strength{value,unit,confidence,source}`,
  `form{...}`, `manufacturer{...}`; `source ∈ ocr|vlm|registry|none`
- `instructions`: `raw_text`, `parsed[{kind ∈ dose|frequency|route|duration|warning|other, text}]`,
  **`dose`** (v1.1 additive) `{quantity>0|null, unit|null, confidence, source}` — the
  per-dose amount as written on the label, never a package count
- `candidates[]`: `{name, strength?{value,unit}, score, source ∈ registry|ocr|vlm}`
- `interpretation`: `{available, summary?, source?:"vlm", model?}`
- `uncertainty`: `{level ∈ low|medium|high, reasons[], rescan_required}`
- `timing`: `{total_ms, stages{name: ms}}`
- `safety`: `{disclaimer, ingestion_not_inferred=true, backend_authoritative=true}`
- `error`: `{code, message, detail} | null`

Error codes seen in implementation: `INVALID_IMAGE`, `INVALID_REQUEST` (400 envelope),
`PAYLOAD_TOO_LARGE` (413), `UNSUPPORTED_MEDIA_TYPE` (415), `SCAN_TIMEOUT` (504).
Status semantics: `needs_rescan` ⇒ retake photo; `uncertain` ⇒ usable but low-confidence;
`error` still returns a full schema-valid envelope.

### E.2 Internal Python interfaces (implemented)

```python
# services/vision/pipeline.py
analyze_frame(image_bytes: bytes, hints: dict | None = None) -> VisionResult
# quality / bottle / label / guidance / timing / detector

# services/ocr/engine.py
read_text(image: np.ndarray, bbox: BBox | None = None) -> OcrResult
# services/ocr/extract.py
extract_fields(raw_text: str, hints: dict | None = None) -> Extraction
#   .medication_contract(), .instructions_contract()  -> contract-shaped fragments

# services/vlm/client.py
Qwen3VLClient(...).interpret(image_bytes, ocr_text, question) -> VlmResult
# services/vlm/reconcile.py
should_use_vlm(uncertainty: dict, config: dict | None = None) -> bool
reconcile_fields(...) -> merged fields with source attribution

# services/api/pipeline.py  (integration seam, mock implemented)
class ScanPipeline(Protocol): ...
get_pipeline() -> ScanPipeline
```

### E.3 Shared models
`services/common/contract.py` (pydantic v2, frozen): `ScanResponse`, `HealthResponse`,
`ReadyResponse`, `BBox`, `FieldString`, `FieldStrength`, `FrameQuality`, `Bottle`,
`Label`, `Medication`, `Instructions`, `Candidate`, `Interpretation`, `Uncertainty`,
`Timing`, `Safety`, `ErrorInfo`, `CONTRACT_VERSION`, `SAFETY_DISCLAIMER`.

### E.4 Breaking-interface policy
Additive optional fields → minor bump (`1.1.0`); breaking changes → new `vN/` directory.
v1 consumers must ignore unknown optional fields. All changes require orchestrator approval.

---

## F. File and folder structure

```
HackRU26/
├── AGENTS.md                     shared agent rules (ownership, safety, reporting)
├── README.md                     project overview + quick start
├── pyproject.toml                root project metadata (orchestrator)
├── contracts/                    FROZEN v1 contract + examples (orchestrator)
│   ├── README.md  v1/scan_request.schema.json  v1/scan_response.schema.json
│   └── examples/{ok,needs_rescan,error}_response.json
├── services/
│   ├── common/contract.py        pydantic mirror of the contract (orchestrator)
│   ├── vision/                   PI-1 (Atlas): preprocess/quality/detector/label/pipeline
│   ├── ocr/                      PI-2 (Orion): engine/extract/lexicon/types + DECISION.md
│   ├── vlm/                      PI-3 (Juno): client/reconcile/dataset/eval/benchmarks + EVAL.md
│   └── api/                      PI-4 (Athena): main/pipeline/fixtures + HANDOFF.md
├── samples/                      synthetic label images (sharp/blurry/dark)
├── scripts/                      validate_contract.py, scan_demo.sh, gpu_probe.sh,
│                                 setup_full_env.sh, local_scan.sh
├── tools/local_scan/             local test console (stdlib proxy + browser UI + README)
├── tests/integration/            orchestrator ASGI contract tests
├── docs/
│   ├── STATUS.md                 live task board + gate log (orchestrator)
│   └── inference-medcheck.md     THIS FILE — component source of truth
└── .worktrees/                   pi-1-vision · pi-2-ocr · pi-3-vlm · pi-4-api (gitignored)
```

Entrypoints: `services.api.main:app` (uvicorn). Config locations: per-service
`requirements.txt`; env vars only (no committed config secrets). Generated/runtime assets:
Ocr artifacts (`services/ocr/artifacts/`), VLM dataset images and eval results
(`services/vlm/dataset/`, `services/vlm/eval/results.json`, `benchmarks/results.json`) —
committed as small text/PNG artifacts or regenerable.

---

## G. Setup and execution

**Verified commands (executed by orchestrator unless noted):**

```bash
# 1. Orchestrator environment + contract validation
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python "pydantic>=2.6" jsonschema
.venv/bin/python scripts/validate_contract.py          # → 3/3 examples valid

# 2. API (mock mode) — worker-verified; orchestrator re-run pending this merge
uv venv .venv --python 3.11                                            # (in the worktree)
uv pip install --python .venv/bin/python -r services/api/requirements.txt
.venv/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8300
scripts/scan_demo.sh

# 3. Per-service tests (each in its own worktree venv)
.venv/bin/python -m pytest services/vision -q     # worker: 46 passed
.venv/bin/python -m pytest services/ocr -q        # worker: 25 passed
.venv/bin/python -m pytest services/vlm -q        # worker: 79 passed
.venv/bin/python -m pytest services/api -q        # worker: 40 passed

# 4. Rig / GPU probe (read-only)
scripts/gpu_probe.sh
```

**Additional verified commands (2026-10-10):**

```bash
# Combined environment + full suite (fresh env, 277 passed / 12 s)
scripts/setup_full_env.sh
.venv-full/bin/python -m pytest services tests/integration -q

# Local test console (no iOS app needed) — upload/webcam → real engine
scripts/local_scan.sh --daemon   # background, survives terminal close; prints URL
scripts/local_scan.sh --status   # / --stop
# → http://127.0.0.1:8400

# Real mode live (see §I for measured results)
MEDCHECK_API_MODE=real MEDCHECK_VLM_ENABLED=1 .venv-full/bin/uvicorn services.api.main:app --port 8300
```

**Still unverified:** iOS multipart interoperability on a real device; sustained
multi-user load; any Windows environment.

---

## H. Integration-relevant information

### H.1 For iOS (Aparajita) and Backend (Urvi)
- Call `POST http://<host>:8300/v1/scan` as `multipart/form-data` with part name `image`
  (JPEG/PNG ≤ 12 MiB). Optional `client=ios|backend`, `mode=auto|mock|real`,
  `hints` JSON string.
- Parse the `ScanResponse` (all field names/types in §E.1). Treat `status` as the primary
  driver: `needs_rescan` → show `frame_quality.guidance`; `uncertain` → present with
  uncertainty cues; `error` → show `error.message`.
- Always display `safety.disclaimer`; never treat a scan as proof of ingestion; do not
  take dosing actions from inference output — the backend owns schedules/authority.
- Auth: **none implemented** (local/dev gateway). Do not assume TLS or tokens.
- Mock mode is safe for UI development now; responses are deterministic per request hash.

### H.2 For other inference work / future sessions
- **Frozen interfaces**: `contracts/**`, `services/common/contract.py`. Change process:
  request → orchestrator approval → version bump + doc update.
- **Ownership**: `services/vision` → Atlas; `services/ocr` → Orion; `services/vlm` →
  Juno; `services/api` → Athena; everything else → orchestrator.
- **Branching**: integrate via `feat/inference-medcheck`; never commit to `main`; the
  remote started empty and only feature branches are pushed.
- **GPU**: one intrusive experiment at a time (orchestrator-granted); reuse `echo-vllm`;
  never restart rig services.
- **October Bus specifics (verified)**: five agents on one canvas; worker bindings are
  activated (`principal: user-terminal`, `harness: pi`, `adapter-ready`). The orchestrator
  terminal is a `user-shell` terminal and is refused mutating Bus tools
  (`unactivated-terminal`) — dispatch currently uses `octoberctl terminal input`
  (`--id <node> --epoch <epoch> --data "<text>\r"`), inbound uses the peer `message_peer`
  path. Full loop: pty-dispatch → worker executes → `message_peer` queued to Apollo.
  **Inbound wake delivery is asymmetric and now verified** (2026-10-10): worker terminals
  (October agent terminals, `harness: pi`) receive wakes end-to-end — Orion recorded an
  `october-bus-wake` custom message with receipt `9b300f77-…` (19:45:01Z) carrying
  Athena's matcher-interface request plus Juno's M2 summary. The **orchestrator terminal
  cannot receive wakes**: it is a `user-shell` terminal (`manualTerminal: true`), and for
  such bindings October runs `admitMcp` on *every* hook route; Apollo's admission is
  refused (`foreground-not-agent`, `inputOwner: "shell"`, `harness: "unknown"`), so
  `/hook/wake` returns `{"ok":false,"stale":true}` and `/hook/pre-prompt` returns empty —
  by design. Relaunching the orchestration terminal as an October *agent* terminal (and
  resuming this Pi session there) would restore native Bus tools + wake delivery.
  Current orchestrator inbound = worker session transcripts + `bus peers` status
  summaries; outbound = `octoberctl terminal input`.
- **Environment variables** the other components may set/need: §D.3. Secrets never in repo;
  vLLM key lives only in `~/.medcheck/vllm.env` (mode 600).

### H.3 Naming conventions
JSON: `snake_case`; enums lowercase snake; timings `*_ms`; normalized bboxes `[0,1]`;
every extracted field carries `{value, confidence, source}`.

---

## I. Testing and verification

| Test | Command | Result | Verified by |
|---|---|---|---|
| Contract examples vs schema+pydantic | `.venv/bin/python scripts/validate_contract.py` | **3/3 valid** | Orchestrator ✅ |
| Synthetic label generation + render check | Pillow script + visual read | **OK** | Orchestrator ✅ |
| Rig reachability + GPU state | `ssh hermes-linux nvidia-smi` | 32,607 MiB total, 17,659 used, 14,430 free | Orchestrator ✅ |
| Existing vLLM models endpoint (Mac→Tailscale) | `GET $MEDCHECK_VLM_BASE_URL/models` | `Qwen/Qwen3-VL-8B-Instruct-FP8` | Orchestrator ✅ |
| Vision unit tests | `pytest services/vision -q` | 46 passed (0.66 s) | Atlas + orchestrator re-run ✅ |
| OCR unit + accuracy tests | `pytest services/ocr -q` | 25 passed (3.20 s); e2e 8/8 name/strength/form | Orion + orchestrator re-run ✅ |
| VLM unit tests | `pytest services/vlm -q` | 79 passed (2.02 s) | Juno + orchestrator re-run ✅ |
| VLM measured eval | `services/vlm/eval/run_eval.py` on 24 images | OCR 0.99 / VLM 1.0 / hybrid 0.993 macro F1; escalation 8.3 %; p50 1584.8 ms | Juno ✅ (measured) |
| API tests | `pytest services/api -q` | 40 passed (worker) / 40 passed on merged tree | Athena + orchestrator re-run ✅ |
| Orchestrator integration harness (merged tree) | `.venv/bin/pytest services/api tests/integration -q` | **42 passed** (40 API + 2 integration) | Orchestrator ✅ |
| Live API smoke on merged tree (mock) | uvicorn :8300 + `scripts/scan_demo.sh` | health/ready 200; scan `uncertain` mock, schema-valid; port freed after | Orchestrator ✅ |
| **Merged full suite (M2 + noise fix)** | `.worktrees/pi-4-api/.venv/bin/python -m pytest services tests/integration` | **277 passed / 0 failed** | Orchestrator ✅ |
| **Matcher live (hints)** | real-mode curl with `known_candidates` | matching → `candidates:[{Metformin,500 mg,score 1.0,source registry}]`; mismatched → `[]` | Orchestrator ✅ |
| **Real-mode live: /ready** | `MEDCHECK_API_MODE=real` uvicorn :8300 | `{"ready":true,"mode":"real","components":{"vision":"ready","ocr":"ready","pipeline":"real"}}` | Orchestrator ✅ |
| **Real-mode live: sharp scan + real VLM** | curl multipart → real pipeline, `MEDCHECK_VLM_ENABLED=1` | status `uncertain`; Metformin 500 mg OCR (0.95/1.0); VLM summary + `form` from VLM; VLM stage **1745 ms**, total 2272 ms; conflicts preserved with both values | Orchestrator ✅ |
| **Real-mode live: blurry scan** | curl blurry sample | `needs_rescan` in **19.5 ms**, 3 guidance strings, no OCR/VLM | Orchestrator ✅ |
| **GPU/VRAM during real VLM call** | nvidia-smi before/after | 18,383 MiB used / 13,706 free — **unchanged**, shared vLLM never restarted | Orchestrator ✅ |
| **Fresh combined env (reproducibility)** | `scripts/setup_full_env.sh` then `.venv-full/bin/python -m pytest services tests/integration -q` | **277 passed** in 12.03 s from a clean env | Orchestrator ✅ |
| **Concurrency profile (real mode, VLM off, Mac CPU)** | 8 sequential + 8 concurrent scans | sequential p50 **745 ms**, p90 1554 ms; 8 concurrent all OK in **~2.1 s wall** (~3.8 scans/s), no errors | Orchestrator ✅ |
| **M3 escalation efficiency (live)** | real mode + VLM enabled: clean scan | **541.6 ms, `stages.vlm=0.0`, `interpretation.available=false`** — no rig call on clean reads | Orchestrator ✅ |
| **M3 escalation trigger (live)** | same, registered candidate mismatch | VLM fires (**1696 ms** stage, total 1946 ms), `interpretation.available=true`, candidates `[]`, conflict reason carries rationale | Orchestrator ✅ |
| **M3 reconciliation normalization** | clean-scan uncertainty reasons | `['missing:manufacturer']` only — case-only `ocr_vlm_conflict` noise gone | Orchestrator ✅ |
| October wake delivery (worker nodes) | session JSONL `customType=october-bus-wake` + receipt; single `/hook/wake` probes | ✅ **verified end-to-end**: Orion received Athena's request as a wake (receipt `9b300f77-6…`, 19:45:01Z) and Juno's M2 summary in the same batch | Orchestrator ✅ |
| October wake delivery (orchestrator node) | same probe against Apollo's hook credentials | ❌ **blocked by design**: `{"ok":false,"stale":true}`; root cause proven in `october-core.js` (manual-terminal hook admission) + `core-runtime.log` (`foreground-not-agent`, `inputOwner:shell`); 0 custom messages ever delivered | Orchestrator ✅ (root cause proven) |

Known bugs / limitations:
- `Metformin HCI` OCR error is confidence-blind (0.87) — VLM escalation would not trigger;
  recommend registry/candidate-match checks (Juno, documented in `services/vlm/EVAL.md`).
- Orchestrator Bus principal restriction (§H.2).
- `ffmpeg` on the dev Mac lacks the `drawtext` filter — synthetic labels are generated
  with Pillow instead.

---

## J. Chronological change log (append-only)

**2026-10-10** — Environment identified and validated. Upstream **Pi 1.1.0** running under
October Desktop (core artifacts `1.0.55-f81a6bd00b7fe8a2`); October's own harness is
OpenCode-derived `0.87.1-october.3`. Pi integration = auto-generated
`~/.pi/agent/extensions/october-bus.ts` + `october-bus-static` Bus MCP + `OCTOBER_BUS_*`
env. Five terminals confirmed live (Apollo, Atlas, Orion, Juno, Athena); worker bindings
activated in October core; Apollo terminal is `user-shell` (mutating Bus tools refused).
No settings/sessions modified.

**2026-10-10** — Repo initialized at `/Volumes/Auxilary/Side_Projects/HackRU26`.
Commit `51569fd` — contracts v1 frozen (schemas + examples + pydantic mirror), AGENTS.md,
per-service READMEs with ownership, docs/STATUS.md, .gitignore. Four worktrees created:
`pi-1-vision`/`feat/vision-atlas`, `pi-2-ocr`/`feat/ocr-orion`, `pi-3-vlm`/`feat/vlm-juno`,
`pi-4-api`/`feat/api-athena`.

**2026-10-10** — Commit `4886c26` — contract validation script + recorded rig/vLLM facts.
Locally verified: 3/3 contract examples valid; rig reachable; existing vLLM
(`echo-vllm`, tailnet `:8100`, Qwen3-VL-8B-FP8) listable from the Mac; credentials stored
outside git (`~/.medcheck/vllm.env`, mode 600).

**2026-10-10** — Commit `cec0294` — synthetic labels (`samples/`) + `scripts/scan_demo.sh`.
Commit `3b10ca6` — integration harness `tests/integration/test_api_contract.py` +
`scripts/gpu_probe.sh`. Commit `f896fab` — status board update.

**2026-10-10** — Assignments dispatched to all four workers via `octoberctl terminal input`
with acceptance criteria; handshake round-trip verified with Atlas (`message_peer` →
queued to Apollo). Bounded GPU window granted to PI-3 (existing service only, ≤120
sequential calls, no restarts).

**2026-10-10** — **All four first milestones delivered** (worker-reported):
- `feat/vision-atlas` `9d0b593` + `f55025c` — vision pipeline, 46 tests.
- `feat/ocr-orion` `987dd88` — RapidOCR stack + extraction, 25 tests, 33/33 extraction,
  8/8 e2e.
- `feat/vlm-juno` `c4b3688` + `b475ea8` + `9ac2305` — adapter, 24-image dataset, eval,
  measured benchmark (hybrid F1 0.993, escalation 8.3 %, p50 1584.8 ms, VRAM headroom
  13,706 MiB), 79 tests.
- `feat/api-athena` `a855318` — mock FastAPI gateway on :8300, 40 tests, live smoke OK.
All branches scope-clean (only `services/<own>/**`). Reports queued to Apollo via
`message_peer`; read from transcripts pending inbound-wake verification.

### H.4 Backend ingest contract (Urvi, `feat/backend-urvi`, verified 2026-10-10)

`POST /api/v1/scans` (JWT, `flask-smorest`): request
`{event_id, user_id, drug_name, strength?{value,unit}, quantity, timestamp}` → response
`{match_status, observation_event_id, observed_at, replayed, medication, dose_event,
 timing, quantity_check, scanned_quantity, expected_quantity, next_dose, candidates, safety}`.

Client mapping from our ScanResponse: `medication.name.value → drug_name`,
`medication.strength → strength` (backend also accepts `"500 mg"` strings),
`request timestamp → timestamp`; `event_id` is client-generated (idempotent).

- The backend never records a dose from a scan (`safety.ingestion_not_inferred`); only
  `POST /doses/{id}/confirm` changes status — aligned with our safety rule.
- **Gap resolved via v1.1:** `quantity` is required by `POST /scans`, and ScanResponse
  now carries `instructions.dose.quantity`/`unit` (additive minor bump, 2026-10-10).
  Client mapping documented in `tests/integration/test_backend_fit.py`; fallback `1`
  only when the label does not state a per-dose amount (never from package size).

| **Backend-fit (contract v1.1)** | `pytest tests/integration/test_backend_fit.py` | mock mapping passes; real-scan `instructions.dose` assertion **expected red until M4 merges** (Orion extraction + Athena pass-through) | Orchestrator ⏳ |

**2026-10-10** — **Contract v1.1 + backend fit (M4).** Added additive
`instructions.dose {quantity, unit, confidence, source}` to the frozen contract (minor
bump, v1 consumers ignore it) so Urvi's `POST /api/v1/scans` gets a real numeric
quantity from the label instead of a client guess. Schema, pydantic model, examples,
version assertions and the contract changelog updated (`3bdea53`). Orchestrator
backend-fit test added (`tests/integration/test_backend_fit.py`, maps a real
ScanResponse to Urvi's ScanSchema payload). M4 dispatched: Orion extracts
`dose_quantity`/`dose_unit`/`dose_contract()` from the dose instruction (ranges →
null, package counts never treated as doses); Athena wires `instructions.dose` into the
real + mock pipelines and documents the backend mapping in `HANDOFF.md`. Juno's
re-run eval (M3 defaults) is recorded in `services/vlm/EVAL.md`.

**2026-10-10** — **Cross-team verification: Urvi's backend (`feat/backend-urvi` @ `85fc33f`).**
Verified: history branches from our `e0fe570`; 64 new files all under `backend/`,
`.kiro/` and root docs — **dry-run merge into integration is clean (no conflicts)**;
scan ingest matches the inference contract (`strength {value,unit}`, idempotent
`event_id`, `safety.ingestion_not_inferred`, scans never record doses); TimescaleDB
container starts healthy and migrations/17-table schema are present.
**BLOCKER FOUND (ours, fixed):** the entire `backend/app/models/` package was missing
from her push because our `.gitignore` rule `models/` was unanchored and silently
matched `backend/app/models/` (fresh checkout → `ModuleNotFoundError: app.models`;
all her tests fail at collection). Fixed on integration branch `179c4d6` (`/models/`
anchored to repo root; root ML weights still ignored). **Urvi must merge/cherry-pick
that fix, `git add backend/app/models`, and push.** Audit confirmed no other module is
affected (only `app.models` / `app.models.enums` unresolved).

**2026-10-10** — **Local console live mode + scan bundles.** Added `/api/live`
(vision-only fast pass, **~20 ms** per 960 px frame after warmup; quality + bottle +
label + guidance) and a UI live mode: continuous boxes/guidance at ~4 fps, auto-scan when
quality is acceptable and the label is stable for 2 frames (throttled to 1 full scan /
6 s), live overlay over the video. Scans now saved as debug bundles (image + response
JSON) in `~/.medcheck/scans/` (last 40, rotatable; `MEDCHECK_SAVE_SCANS=0` disables),
listable at `/api/scans`. UI switched to raw `image/*` uploads with query params; the
proxy builds the multipart for the API (multipart passthrough still supported for curl).
Verified: 5 live calls (277 ms cold, then 19–22 ms), raw scan path 559 ms with matcher
score 1.0, bundle saved and listed. Media note: Varesh's real bottle scan worked in the
console; live mode is the next iteration toward the iOS camera experience.

**2026-10-10** — **Local console daemon mode + fix.** Varesh's first attempt found the
console down (foreground process died with its shell). Added `--daemon` (nohup, PID
files, logs in `$TMPDIR/medcheck-local-scan/`), `--status`, `--stop`, port-conflict
handling. Fixed a daemon bug where `MODE`/`VLM` were not exported, silently starting
mock mode. Re-verified end-to-end through the console proxy: page 200; clean scan with
matching candidate → Metformin 500 mg, score 1.0, **no VLM** (vlm stage 0.0, 692 ms);
mismatched registry → real Qwen3-VL call (1721 ms stage). Console left running for
Varesh at `http://127.0.0.1:8400`.

**2026-10-10** — **Local test console delivered** (`tools/local_scan/`): stdlib proxy +
browser UI (upload, webcam capture, bbox overlay, field/confidence rendering, raw JSON)
launched with `scripts/local_scan.sh` on `http://127.0.0.1:8400`. Verified end-to-end:
page 200, `/api/ready` proxy, multipart scan through the proxy → real pipeline
(Metformin 0.95, label bbox, 513 ms); ports cleaned up after. JS syntax-checked with
`node --check`. Lets Varesh exercise the engine from his Mac while the iOS app is still
in frontend development.

**2026-10-10** — **Milestone 3 merged and verified.** Juno (`9e13a4f`, `16ca2dd`) +
Athena (`6ec5c0b`, `66d58b0`, `c9a8a4a`) → merges `fc5ff80`, `4d0d32c`. Fresh-env full
suite: **293 passed / 0 failed**. Live escalation behaviour verified: clean scan
**541.6 ms** with `stages.vlm=0.0` and no interpretation (no rig call); registered
candidate mismatch escalates (VLM **1696 ms**, total 1946 ms, interpretation from
Qwen3-VL); case-only conflicts removed, real conflicts carry rationale; VRAM unchanged
(18,383 used / 13,706 free). `services/api/HANDOFF.md` expanded for iOS/backend.

**2026-10-10** — **Reproducibility + performance.** `scripts/setup_full_env.sh` added
(union env `.venv-full`) and verified from scratch: full suite **277 passed / 12.03 s**.
Concurrency profile (real mode, VLM off, Mac CPU): sequential p50 745 ms / p90 1554 ms;
8 concurrent scans complete in ~2.1 s wall (~3.8 scans/s), no errors. Milestone 3
dispatched: Athena wires `candidate_mismatch` + escalation config and finalizes
`HANDOFF.md`; Juno restricts escalation to identity-critical fields and normalizes
reconcile comparisons (with optional re-run of the 24-image eval).

**2026-10-10** — **Noise regression fixed and merged** (`ae1c3a8`, blur-scale structure
gate). Merged full suite: **277 passed / 0 failed**. Live matcher verification with
hints: matching candidate → `{Metformin, 500 mg, score 1.0, source registry}`;
mismatched candidate → `[]` while OCR still reads Metformin. Escalation tuning +
reconcile normalization identified as M3 items (§K items 5–6).

**2026-10-10** — **Milestone 2 delivered, merged, and real-mode acceptance run.** Worker tips
verified independently (vision 70, ocr 52, vlm 91, api 56 tests) then merged: `b6bbbef`
(api real pipeline + EXIF regression), `a49afd0` (ocr matcher + Extraction-shape fix),
`5b60648` (vision crop_label handoff + calibration), `91a5c83` (vlm escalation triggers +
`client_from_env`). Merged full suite: **270 passed, 1 failed** — pure-noise image now
passes vision's frame-level label fallback (`label.detected=True`, conf 0.5053), so the
API's real pipeline returns `uncertain` instead of `no_medication_found`; regression fix
dispatched to Atlas (noise-immunity gate).
**Real-mode end-to-end acceptance (orchestrator):** live API :8300 in `mode=real` with
`MEDCHECK_VLM_ENABLED=1` and the existing rig vLLM — sharp synthetic label → Metformin
500 mg from OCR (0.95/1.0), VLM summary + `form` from `Qwen/Qwen3-VL-8B-Instruct-FP8`,
stages preprocess 7.8 / quality 8.6 / detect 87.9 / ocr 411.2 / vlm **1745.3 ms**,
total 2272 ms; conflicts preserved with both values; blurry sample → `needs_rescan` in
19.5 ms; VRAM 18,383 used / 13,706 free unchanged across the call; server stopped, port
freed. Mac→Tailscale→rig path verified through the actual API (Gate 8 core).

**2026-10-10** — Branch `feat/inference-medcheck` created (per Varesh's documentation
instruction: never develop on/merge into `main`); `origin` added
(`https://github.com/Haadesx/HackRU26`). Remote verified **empty** (`isEmpty: true`,
`ls-remote` → no heads) — safe to push a feature branch only; `main` intentionally left
untouched. This documentation file created.

**2026-10-10** — **Orchestrator verification + integration.** Branch `feat/inference-medcheck`:
all four worker branches scope-reviewed (no out-of-scope files) and merged: `2ba5a12`
(api), `03eb5a7` (ocr), `2c4e3c7` (vision), `4c5513f` (vlm). Independent re-runs: vision 46
passed, ocr 25 passed (e2e 8/8), vlm 79 passed, api 40 passed; merged tree
`pytest services/api tests/integration` → **42 passed**; contract validation 3/3; live
uvicorn :8300 smoke (`scan_demo.sh`) schema-valid, port cleaned up. Branch pushed to
`origin` (`e0fe570`); `main` untouched.

**2026-10-10** — Milestone 2 dispatched to all workers: PI-4 real pipeline wiring
(seam `services/api/pipeline.py`, mock default kept), PI-2 registered-candidate matcher
(`services/ocr/matcher.py`, interface frozen by orchestrator), PI-1 `crop_label` + CLI
+detector env docs, PI-3 escalation-trigger config + `client_from_env()` (no GPU).
Worker branches must merge `feat/inference-medcheck` before starting. GPU window held
open for one final end-to-end VLM pass.

**2026-10-10** — **Wake-delivery verification (hypothesis → proof).** Method: (1) session
JSONL ground truth (`custom_message` with `customType=october-bus-wake` + receipt),
(2) single `POST /hook/wake` probe with the node's own hook credentials (never retried —
bus semantics), (3) ack/turn-trigger observation. Results: **worker wakes verified**
(Orion receipt `9b300f77-6…` at 19:45:01Z carrying Athena's matcher-interface request and
Juno's M2 summary); **orchestrator node probe** returned `{"ok":false,"stale":true}` and
the root cause was located in `october-core.js`: for `manualTerminal` bindings every hook
route runs `admitMcp`, which for a `user-shell` terminal is refused
(`foreground-not-agent`, `inputOwner:"shell"`). Apollo session has 0 custom messages
(0 pre-prompt, 0 wake). Outbound pty dispatch and worker wake reception remain fully
functional.

---

## K. Known issues and outstanding work

1. **Orchestrator Bus identity** — Apollo's terminal cannot use mutating Bus tools; pty
   dispatch works. Fix (optional, needs Varesh): relaunch the orchestration terminal as an
   October agent terminal, or accept the current channel.
2. **Orchestrator wake delivery is blocked by design (verified root cause)** — Apollo's
   terminal is `user-shell`/`manualTerminal`, so every hook route runs `admitMcp` and is
   refused (`foreground-not-agent`); `/hook/wake` → `{"ok":false,"stale":true}`. Worker
   terminals (agent-launched) receive wakes normally. Workarounds in use: outbound
   `octoberctl terminal input`; inbound worker transcripts + `bus peers` summaries.
   Permanent fix (Varesh/Desktop action): run the orchestrator in an October **agent**
   terminal and resume this Pi session (`pi --continue`). This also restores native
   `message_peer` for the orchestrator.
3. **Noise false-positive label — FIXED** — `ae1c3a8` (blur-scale structure gate in the
   frame-level fallback) merged; Gaussian noise (sigma 25/40/60) rejected, flat label
   unchanged (conf 0.5808, same bbox); merged suite **277/277**.
4. **Candidate/registry matching** — matcher implemented (`services/ocr/matcher.py`,
   `match_candidates`, threshold 0.75) and wired into the API; `candidate_mismatch` now
   drives escalation (M3, verified live). Remaining integration input: the candidate
   registry itself is backend-owned — the API accepts it via `hints.known_candidates`
   until a dedicated endpoint/source is agreed with Urvi.
5. **Auth/TLS** — gateway has none (dev/local). Must be decided before any non-local
   exposure (iOS device testing will need it; the Mac-local tester runs on localhost).
6. **On-device iOS validation** — blocked on the iOS app (Aparajita); contract and
   `services/api/HANDOFF.md` are ready for integration.
5. **Remote state** — `feat/inference-medcheck` is pushed (`origin`, `e0fe570`+); `main`
   remains empty/untouched intentionally. The team (or Varesh) should initialize `main`
   or PR this branch when ready.
6. **Dependency reconciliation** for a combined rig install (numpy/opencv pins differ;
   rig Python 3.14 vs service venv 3.11; no `uv` on rig).
7. **Auth/TLS** — gateway has none (dev/local). Flag before any non-local exposure.
8. **Unrun acceptance paths** — 12 MiB boundary on a real device, iOS multipart
   interoperability, and a full concurrency/latency profile under multiple simultaneous
   scans.
