# OCR vs Qwen3-VL evaluation — synthetic label set

Owner: PI-3 Juno. Date: 2026-10-10 (UTC). Branch `feat/vlm-juno`.

Measured on the existing shared vLLM service (`Qwen/Qwen3-VL-8B-Instruct-FP8`,
`http://ai-rig.tail6d5242.ts.net:8100/v1`). The service was never restarted, and
no second model was launched. All requests were sequential; the run stayed inside
the orchestrator-granted 120-image window (40 VLM calls total: 2 smoke + 26 eval
+ 12 benchmark).

Raw results: [`eval/results.json`](eval/results.json),
[`benchmarks/results.json`](benchmarks/results.json).

## Setup

- **Dataset** — 24 synthetic label images with committed ground truth
  (`dataset/ground_truth.json`): 16 clean plus blur ×2, dark, glare, tilt ×2,
  small_text, low_contrast. Explicitly synthetic labels; no real patient data.
- **OCR baseline** — local Tesseract 5.5.2 plus a line-based field parser
  (`eval/engines.py`). This is a reproducible stand-in for PI-2's OCR stack, not
  the product extractor.
- **VLM** — `Qwen3VLClient` (`client.py`), temperature 0, retries off.
- **Modes** — `ocr_only`, `vlm_only`, and `ocr_first_vlm` (OCR first, VLM only
  when `should_use_vlm()` fires, then `reconcile_fields()` merges both reads).
- **Metrics** — per-field precision/recall/F1; a field counts as correct only on
  normalized exact match (numeric strength, unit aliases µg→mcg). Instructions
  count as correct at token F1 ≥ 0.8. Latency is wall-clock, Mac → Tailscale →
  rig, and therefore includes network time.

## Results (24 images)

| Field | OCR-only F1 | VLM-only F1 | OCR-first + VLM-on-uncertainty F1 |
|---|---|---|---|
| name | 0.958 | 1.0 | 0.958 |
| strength_value | 1.0 | 1.0 | 1.0 |
| strength_unit | 1.0 | 1.0 | 1.0 |
| form | 1.0 | 1.0 | 1.0 |
| manufacturer | 0.979 | 1.0 | 1.0 |
| instructions | 1.0 | 1.0 | 1.0 |
| **macro F1** | **0.99** | **1.0** | **0.993** |

| Mode | VLM calls | VLM invocation rate |
|---|---|---|
| ocr_only | 0 | 0% |
| vlm_only | 24 | 100% |
| ocr_first_vlm | 2 | 8.3% |

OCR error detail:

- `img_001` (clean): name read as **Metformin HCI** instead of `Metformin HCl`
  at 0.87 confidence — the classic `l`/`I` confusion. The gate did not fire
  because 0.87 clears the 0.75 threshold, so the error survives OCR-first.
- One degraded frame dropped the manufacturer line; both gate hits
  (`img_017` blur, `img_023` tilt) came from weak non-critical fields, and the
  VLM restored the missing manufacturer.

## GPU benchmark (12 images, sequential)

| p50 | p90 | mean | Throughput | VRAM before | VRAM after |
|---|---|---|---|---|---|
| 1584.8 ms | 1683.6 ms | 1593.1 ms | 0.63 img/s | 17,659–18,383 / 32,607 MiB used | 18,383 / 32,607 MiB used |

VRAM headroom stayed at ≈13.7 GiB free; no process was started or restarted.
OCR baseline latency in the same run: p50 270.6 ms, p90 278.5 ms.

## Findings

1. **The VLM read every field correctly** on this controlled set (144/144 field
   matches across 24 images, including blur, dark, glare, tilt, small text, and
   low contrast).
2. **The OCR baseline is already strong on crisp synthetic print** (0.99 macro
   F1). Its residual errors are exactly the ones confidence alone cannot catch:
   a plausible misread (`HCl` → `HCI`) and a dropped line on a degraded frame.
3. **OCR-first worked as designed for missing data, not for confident errors.**
   Two escalations (8.3%) recovered the dropped manufacturer at a cost of
   ≈1.6 s each. The name miss survived because raw OCR confidence was
   misleadingly high.
4. **Cost** — VLM-only costs ≈1.87 s per scan versus ≈0.27 s for OCR-only.
   OCR-first averages ≈0.40 s per scan at the measured 8.3% escalation rate.
   Paying the full VLM price on every scan for +1% macro F1 on this set is not
   justified on quality grounds alone.

## Recommendation

**Keep OCR-first. Do not call the VLM on every scan.** Invoke it when:

1. the existing uncertainty gate fires (missing or low-confidence critical
   field, level `medium`/`high`), **or**
2. **validation fails** — the read name or strength does not plausibly match the
   candidate/registry list. This is the missing signal: it catches
   `Metformin HCI` even though the OCR was confident. Adding it should recover
   the last synthetic error at a ≈12.5% escalation rate (3/24);
3. never instead of a rescan: when frame quality is unacceptable, ask for a new
   photo first (`rescan_required` short-circuits the gate).

Re-run this evaluation once PI-2's real OCR/extraction stack and PI-4's
candidate matching are integrated, and again on real (non-synthetic) label
photos; the numbers above are a controlled upper bound for clean print.

### Integration contract (Milestone 2)

The API should compute the candidate mismatch and pass it through `config`,
because the frozen v1 uncertainty block has no field for it:

```python
from services.vlm import should_use_vlm, uncertainty_from_fields

uncertainty = uncertainty_from_fields(ocr_fields)
uncertainty["frame_score"] = frame_quality.score      # from PI-1 vision

escalate = should_use_vlm(
    uncertainty,
    config={
        "min_field_confidence": 0.75,        # tunable (default)
        "min_frame_score": 0.45,             # tunable; None disables (default)
        "candidate_mismatch": not matched,   # runtime signal from the matcher
    },
)
```

| config key | type | default | meaning |
|---|---|---|---|
| `min_field_confidence` | float | 0.75 | weak-field threshold on critical fields |
| `candidate_mismatch` | bool | False | no plausible registry/candidate match for the read name or strength → escalate even at high OCR confidence (fixes the `Metformin HCI` @ 0.87 case) |
| `min_frame_score` | float or None | None | escalate when `uncertainty.frame_score` (or `frame_quality.score`) is below this |
| `invoke_on_rescan` | bool | False | force a VLM call even when a rescan was requested |

**Candidate matcher (recommended trigger):** PI-2 Orion's matcher
(`services/ocr/matcher.py` per the integration plan; today's name
canonicalization lives in `services/ocr/lexicon.match_drug_name`, surfaced via
`services/ocr/extract.find_name`). The API calls it with the OCR name and the
registered candidates, then passes `candidate_mismatch=True` when nothing
plausible matches. `rescan_required` still short-circuits first: retake the
photo before spending a VLM call.

## Reproduce

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r services/vlm/requirements.txt
.venv/bin/python -m services.vlm.dataset.generate          # deterministic
.venv/bin/pytest services/vlm/tests -q                     # 79 tests, no GPU
.venv/bin/python -m services.vlm.eval.run_eval \
    --env-file ~/.medcheck/vllm.env --ssh-host hermes-linux \
    --out services/vlm/eval/results.json --md
MEDCHECK_GPU_WINDOW_OK=1 .venv/bin/python -m services.vlm.benchmarks.gpu_bench \
    --env-file ~/.medcheck/vllm.env --ssh-host hermes-linux --images 12 \
    --out services/vlm/benchmarks/results.json
```

## Limits

- Synthetic, neatly printed labels; real-world capture will be harder.
- The OCR column is the local Tesseract baseline, not PI-2's production stack.
- n = 24 images, single run, one rig state; latency includes narrow network
  variance (Mac → Tailscale → rig).
- Sequential requests only; no batching or concurrency was explored.
