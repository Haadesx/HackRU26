# MedCheck — Agent Operating Rules (shared by all five agents)

Read this file before touching any code. The orchestrator (Apollo) owns this repo's
integration branch and this file. Workers may propose edits via Bus message; do not
edit it silently.

## 0. Documentation (standing rule — Varesh, 2026-10-10)

- **`docs/inference-medcheck.md` is the single source of truth** for all technical work
  on this component. It must be updated in the SAME task as any feature, dependency,
  API/schema, config, architectural decision, bugfix, workaround, or benchmark change.
- The orchestrator owns the file. Workers must include a `DOC:` block in every milestone
  report with doc-ready bullets: feature, files, interfaces, dependency/version changes,
  tests + observed results, caveats/limitations.
- Never invent completed work; mark proposed / implemented / tested / blocked explicitly.
- Never put secrets (keys, tokens, passwords) in documentation — names/purposes only.
- Do not modify teammates' documentation files or unrelated components.
- `docs/STATUS.md` is the live task board (gates + dispatch log); the technical detail
  lives in `docs/inference-medcheck.md`.

## 1. Mission

Build MedCheck's AI inference subsystem: bottle detection, frame-quality guidance,
label OCR, structured medication extraction, optional Qwen3-VL interpretation,
candidate matching, uncertainty/rescan handling, a FastAPI gateway on port 8300,
and iOS/backend contracts. Architecture is **OCR-first with optional existing VLM
fallback**. Do not silently change this architecture.

## 2. Ownership map (do not edit another worker's module)

| Module                | Owner        | Git branch            | Worktree                        |
|-----------------------|--------------|-----------------------|---------------------------------|
| `services/vision/**`  | PI-1 Atlas   | `feat/vision-atlas`   | `.worktrees/pi-1-vision`        |
| `services/ocr/**`     | PI-2 Orion   | `feat/ocr-orion`      | `.worktrees/pi-2-ocr`           |
| `services/vlm/**`     | PI-3 Juno    | `feat/vlm-juno`       | `.worktrees/pi-3-vlm`           |
| `services/api/**`     | PI-4 Athena  | `feat/api-athena`     | `.worktrees/pi-4-api`           |
| `contracts/**`, `services/common/**`, `docs/**`, `scripts/**`, `tests/integration/**`, root files | ORCHESTRATOR Apollo | `feat/inference-medcheck` | repo root |

- **Integration branch is `feat/inference-medcheck`** (created 2026-10-10). Do not
  develop on or merge into `main`; `main` stays untouched for the team.
- Shared contract changes (`contracts/**`, `services/common/**`) require an
  orchestrator-approved Bus request **before** you code against a change.
- Keep the API gateway (`services/api`) the only place where service modules are composed.
- Never commit directly to `main`. Merge only tested commits via the orchestrator.

## 3. Git rules

- One repository, five worktrees. Work only inside your worktree.
- The integration branch is `feat/inference-medcheck`; `origin` is
  `https://github.com/Haadesx/HackRU26`. Push only your own feature branch when the
  orchestrator authorizes it; never push `main`.
- Commit small and often. Conventional prefix: `vision:`, `ocr:`, `vlm:`, `api:`, `contracts:`, `docs:`.
- Never `git reset --hard`, `git clean`, or force-push shared branches.
- Report the full commit SHA with every milestone.
- Do not merge another worker's branch yourself; the orchestrator integrates.

## 4. Python environment

- Use an isolated environment per worktree: `uv venv .venv --python 3.11` (or your
  service's `requirements.txt`), never modify system Python, never `pip install --user`.
- Service-specific dependencies live in `services/<your>/requirements.txt` (yours to edit).
- Root `pyproject.toml` is orchestrator-owned; propose changes via Bus.

## 5. GPU & shared infrastructure rules

- The home rig (`hermes-linux`, RTX 5090 32GB) already runs Qwen3-VL-8B-FP8 under
  vLLM (≈17.6 GiB used). **Do not launch another large VLM.**
- Only ONE worker may run intrusive GPU experiments at a time. Request a GPU window
  from the orchestrator; wait for an explicit grant before benchmarking.
- Before any GPU job: check free VRAM (`nvidia-smi`). Keep combined usage at or below
  ≈26–27 GiB. Never kill or restart `echo`, `router`, `bridge`, `Ollama`, or the
  running vLLM service without explicit user permission.
- Never install CUDA drivers or modify shared Python environments on the rig.
- Run GPU work in an isolated MedCheck environment (`/opt/medcheck` or `~/medcheck`).

## 6. Medication safety (non-negotiable)

- Never fabricate drug names, strengths, quantities, or instructions.
- Preserve raw OCR/VLM source text alongside every structured field; record
  `confidence` and `source` per field.
- Distinguish tablet **strength** (e.g. 500 mg) from prescribed **quantity per dose**.
- Holding or opening a bottle is never proof of ingestion; do not imply it.
- Never authorize consumption. The backend owns schedules, dose history, inventory,
  and prescription authority. Inference only *reads labels*.
- Use synthetic medication labels for all testing. No real patient data, ever.
- Every API scan response must carry the safety block (disclaimer, flags).

## 7. Reporting format (required for every milestone)

Use `message_peer` to Apollo (or plain text if asked) with:

REPORTING FORMAT (required — include the `DOC:` block always)

```
STATUS: <in_progress|blocked|done>
WORK: <what was completed>
FILES: <paths changed>
COMMIT: <full SHA or "none">
TESTS: <commands + observed results>
FAILURES: <failures/blockers, or "none">
RESOURCES: <CPU/GPU/VRAM if relevant>
DOC: <doc-ready bullets for docs/inference-medcheck.md: feature, interfaces,
      dependency/version changes, verified-vs-unverified, caveats>
NEXT: <remaining work>
```

## 8. Communication rules

- Peer messages are `[Name]:` lines. Keep them short and context-specific.
- Send task requests with acceptance criteria and expected artifacts.
- Acknowledge with the required report before starting the next milestone.
- Do not spawn duplicate agents or re-do another worker's assignment.
