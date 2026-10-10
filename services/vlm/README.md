# PI-3 VLM — `services/vlm/**` (owner: Juno)

Branch `feat/vlm-juno`, worktree `.worktrees/pi-3-vlm`.

The rig (`hermes-linux`) already serves **Qwen3-VL-8B-FP8 under vLLM** (≈17.6 GiB used,
≈14.4 GiB free as of kickoff). Reuse it. **Never launch another large VLM.**

## Deliverables

1. **Qwen3-VL adapter** — OpenAI-compatible client against the rig's vLLM endpoint.
   Config via env (`MEDCHECK_VLM_BASE_URL`, `MEDCHECK_VLM_MODEL`, `MEDCHECK_VLM_API_KEY`).
   Robust timeouts, retries off by default, image encoding, and OCR-prompt mode where
   the VLM *verifies/reads* the label text. Return structured output + raw text.
2. **Synthetic labeled test dataset** — generate ≥12 labeled bottle images
   (Pillow/HTML-render) with ground-truth name/strength/instructions stored as JSON.
   No real medication labels.
3. **OCR-vs-VLM evaluation** — on the synthetic set, measure per-field precision/recall
   and latency for: OCR-only, VLM-only, and OCR-first + VLM-on-uncertainty. Produce
   `services/vlm/EVAL.md` with the table and a clear recommendation of when the VLM
   should be invoked.
4. **Uncertainty reconciliation** — a function the API can call:
   `should_use_vlm(uncertainty, config) -> bool` and merging of OCR/VLM fields with
   source attribution.
5. **GPU benchmarks** — vLLM latency (p50/p90), images/sec, VRAM headroom. Run ONLY in
   an orchestrator-granted GPU window; check `nvidia-smi` before and after; never stop
   the existing service; do not install drivers or touch shared envs.

## Internal interface (preferred)

```python
# services/vlm/client.py
class Qwen3VLClient:
    def interpret(self, image_bytes: bytes, ocr_text: str | None, question: str) -> "VlmResult": ...
# VlmResult: {available, summary, fields: dict, raw_text, model, latency_ms}
# services/vlm/reconcile.py
def should_use_vlm(uncertainty: dict, config: dict | None = None) -> bool: ...
```

## Acceptance criteria

- Adapter unit-tested with a mocked HTTP server; evaluation script runnable end-to-end.
- EVAL.md with measured numbers and an explicit recommendation.
- No second VLM launched; VRAM logged.
- Report SHA + tests to Apollo via Bus.

## Implementation status

| Path | Contents |
|---|---|
| `client.py` | `Qwen3VLClient` OpenAI-compatible adapter + `client_from_env()` factory; env config, timeouts, retries off, OCR-verify prompt mode, lenient JSON parsing |
| `reconcile.py` | `should_use_vlm()` (`min_field_confidence`, `candidate_mismatch`, `min_frame_score` triggers), `uncertainty_from_fields()`, `reconcile_fields()` with source attribution and contract-shaped medication mapping |
| `dataset/` | 24 deterministic synthetic label images + `ground_truth.json` (regenerate: `python -m services.vlm.dataset.generate`) |
| `eval/` | OCR-vs-VLM runner, Tesseract baseline engine, metrics, `results.json`; summary in `EVAL.md` |
| `benchmarks/` | gated sequential GPU benchmark, `results.json` |
| `tests/` | 79 tests; mocked HTTP + local OCR only, no GPU |

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r services/vlm/requirements.txt
.venv/bin/pytest services/vlm/tests -q
.venv/bin/python -m services.vlm.eval.run_eval --env-file ~/.medcheck/vllm.env \
    --ssh-host hermes-linux --md
```

Measured results (2026-10-10, granted GPU window, 40 sequential calls): VLM-only 1.0
macro F1 on the synthetic set; OCR-first 0.993 at an 8.3% escalation rate; VLM p50
≈1.58 s, 0.63 img/s, ≈13.7 GiB VRAM headroom. Details and recommendation: [`EVAL.md`](EVAL.md).
