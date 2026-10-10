# MedCheck Inference

AI inference subsystem for MedCheck: real-time medication-bottle detection, frame-quality
guidance, label OCR, structured medication extraction, optional Qwen3-VL interpretation,
uncertainty/rescan handling, and a FastAPI gateway on **port 8300**.

Architecture: **OCR-first with optional existing VLM fallback.**
The home rig (`hermes-linux`, RTX 5090) already serves Qwen3-VL-8B-FP8 under vLLM; we reuse
it and never launch a second large VLM.

## Layout

```
contracts/        frozen v1 request/response schemas + examples (orchestrator)
services/common/  shared pydantic contract models (orchestrator)
services/vision/  PI-1 Atlas   — preprocessing, YOLO detection, quality, guidance
services/ocr/     PI-2 Orion   — OCR stack, text/field extraction, accuracy tests
services/vlm/     PI-3 Juno    — Qwen3-VL adapter, synthetic eval set, benchmarks
services/api/     PI-4 Athena  — FastAPI gateway, schemas, mock, tests, handoff
docs/STATUS.md    live task board + integration log (orchestrator)
AGENTS.md         shared operating rules (read before coding)
```

## Multi-agent workflow

Five agents (Apollo orchestrating Atlas, Orion, Juno, Athena) each work in a Git worktree
on their own branch. The orchestrator merges reviewed, tested commits into `main`.
See `AGENTS.md` for rules, reporting format, and GPU scheduling.

## Quick start (API, mock mode)

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -e ".[api,dev]"
.venv/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8300
curl -s localhost:8300/health
curl -s -F "image=@sample.jpg" -F "mode=mock" localhost:8300/v1/scan
```

## Safety

Informational only. Not medical advice. Inference reads labels; the backend owns
schedules, dose history, inventory, and prescription authority. Never infer ingestion.
