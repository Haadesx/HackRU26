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
