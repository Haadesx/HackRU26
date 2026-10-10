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
| PI-4 mock FastAPI gateway on :8300 | ✅ implemented, ✅ orchestrator-re-verified, ✅ MERGED | `feat/api-athena` @ `a855318` → merge `2ba5a12` |
| PI-2 OCR + extraction | ✅ implemented, ✅ orchestrator-re-verified, ✅ MERGED | `feat/ocr-orion` @ `987dd88` → merge `03eb5a7` |
| PI-1 Vision (quality/detect/label) | ✅ implemented, ✅ orchestrator-re-verified, ✅ MERGED | `feat/vision-atlas` @ `f55025c` → merge `2c4e3c7` |
| PI-3 VLM adapter + eval + benchmark | ✅ implemented, ✅ orchestrator-re-verified, ✅ measured eval, ✅ MERGED | `feat/vlm-juno` @ `9ac2305` → merge `4c5513f` |
| Real Vision→OCR→VLM wiring inside the API | ⏳ pending (seam exists: `services/api/pipeline.py`) | — |
| Full-system integration + acceptance | ⏳ pending | — |
| Pushing integration branch to `origin` | ⏳ pending | — |

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

### D.6 Potential conflicts with other components
- Port **8300** is reserved for this gateway (backend/UI must not bind it).
- `echo-vllm` is shared with other HackRU components; inference must not restart it.
- OCR pins (`numpy==2.4.6`, `opencv-python==5.0.0.93`) differ from vision's ranges
  (`numpy>=1.26,<3`, `opencv-python-headless`); they run in separate venvs here, but a
  combined rig environment must reconcile these before co-installing.

---

## E. APIs and data structures

### E.1 HTTP API (fixed contract, `contracts/v1`)

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/health` | — | `200 {"status":"ok","service":"medcheck-inference","version":str,"uptime_s":num}` |
| GET | `/ready` | — | `200 {"ready":true,"mode":"mock|real","components":{...}}` or `503 {"ready":false,...,"reasons":[...]}` |
| POST | `/v1/scan` | `multipart/form-data`: `image` (JPEG/PNG, ≤12 MiB, required), `client` (`ios|backend|test|unknown`), `mode` (`auto|mock|real`), `hints` (JSON string) | `200` `ScanResponse` (even for domain errors) ; transport errors: 400/413/415/504 |

`ScanResponse` top level (all fields required unless noted):
- `contract_version` = `"1.0.0"`, `request_id`, `status`
  (`ok|needs_rescan|uncertain|no_medication_found|error`), `mode` (`mock|real`)
- `frame_quality`: `acceptable`, `score`, `blur{score,is_blurry}`,
  `exposure{score,too_dark,too_bright}`, `glare{score,has_glare}`, `guidance[]`
- `bottle`: `detected`, `confidence`, `bbox{x,y,w,h}` (normalized 0–1)
- `label`: `detected`, `confidence`, `bbox?`, `text` (raw, verbatim)
- `medication`: `name{value,confidence,source}`, `strength{value,unit,confidence,source}`,
  `form{...}`, `manufacturer{...}`; `source ∈ ocr|vlm|registry|none`
- `instructions`: `raw_text`, `parsed[{kind ∈ dose|frequency|route|duration|warning|other, text}]`
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
├── scripts/                      validate_contract.py, scan_demo.sh, gpu_probe.sh
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

**Untested / not yet verified commands:**
- `MEDCHECK_API_MODE=real` behavior beyond the 503 path.
- End-to-end real pipeline (`POST /v1/scan` with `mode=real`) — wiring pending.
- Combined installation of OCR + vision deps in one environment (§D.6).

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
  **Inbound wake delivery into Apollo's session is still unverified** (reports were read
  from worker transcripts while queued — see §I/§K). Relaunching the orchestration
  terminal as an October *agent* terminal would restore native Bus tools.
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
| Live API smoke on merged tree | uvicorn :8300 + `scripts/scan_demo.sh` | health/ready 200; scan `uncertain` mock, schema-valid; port freed after | Orchestrator ✅ |
| October inbound wake to orchestrator | — | **not verified** (messages queued with unconfirmed receipts; reports were read from worker transcripts) | Orchestrator ❌ |

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

**2026-10-10** — **Orchestrator verification + integration.** Branch `feat/inference-medcheck`:
all four worker branches scope-reviewed (no out-of-scope files) and merged: `2ba5a12`
(api), `03eb5a7` (ocr), `2c4e3c7` (vision), `4c5513f` (vlm). Independent re-runs: vision 46
passed, ocr 25 passed (e2e 8/8), vlm 79 passed, api 40 passed; merged tree
`pytest services/api tests/integration` → **42 passed**; contract validation 3/3; live
uvicorn :8300 smoke (`scan_demo.sh`) schema-valid, port cleaned up.

**2026-10-10** — Milestone 2 dispatched to all workers: PI-4 real pipeline wiring
(seam `services/api/pipeline.py`, mock default kept), PI-2 registered-candidate matcher
(`services/ocr/matcher.py`, interface frozen by orchestrator), PI-1 `crop_label` + CLI
+d detector env docs, PI-3 escalation-trigger config + `client_from_env()` (no GPU).
Worker branches must merge `feat/inference-medcheck` before starting. GPU window held
open for one final end-to-end VLM pass.

**2026-10-10** — Branch `feat/inference-medcheck` created (per Varesh's documentation
instruction: never develop on/merge into `main`); `origin` added
(`https://github.com/Haadesx/HackRU26`). Remote verified **empty** (`isEmpty: true`,
`ls-remote` → no heads) — safe to push a feature branch only; `main` intentionally left
untouched. This documentation file created.

---

## K. Known issues and outstanding work

1. **Orchestrator Bus identity** — Apollo's terminal cannot use mutating Bus tools; pty
   dispatch works. Fix (optional, needs Varesh): relaunch the orchestration terminal as an
   October agent terminal, or accept the current channel.
2. **Inbound wake unverified** — worker reports queue to Apollo but delivery into the
   orchestration session has not been observed; workaround: read worker transcripts /
   rely on pre-prompt pulls. Must be verified before claiming peer messaging is complete.
3. **Real pipeline wiring** — `services/api/pipeline.py` seam is mock-only. Next: compose
   Vision → OCR → candidate match → (optional) VLM with uncertainty reconciliation, then
   re-run contract + integration tests.
4. **Candidate/registry matching** — not implemented yet as a service: read text is
   matched only conceptually (`candidates[]` documented). Needs a registry input (from
   backbone/backend) and a matcher with escalation trigger (see Juno's finding).
5. **Remote push pending** — `feat/inference-medcheck` not yet pushed; only feature
   branches will be pushed; `main` must be initialized by the team/authorized owner.
6. **Dependency reconciliation** for a combined rig install (numpy/opencv pins differ;
   rig Python 3.14 vs service venv 3.11; no `uv` on rig).
7. **Auth/TLS** — gateway has none (dev/local). Flag before any non-local exposure.
8. **Unrun acceptance paths** — `mode=real`, 12 MiB boundary on a real device, iOS
   multipart interoperability, and Mac→rig end-to-end scan timing (Gate 7/8).
