# OCR vs Qwen3-VL evaluation — synthetic label set

Owner: PI-3 Juno. Date: 2026-10-10 (UTC). Branch `feat/vlm-juno`.

Measured on the existing shared vLLM service (`Qwen/Qwen3-VL-8B-Instruct-FP8`,
`http://ai-rig.tail6d5242.ts.net:8100/v1`). The service was never restarted, and
no second model was launched. All requests were sequential; VLM calls stayed
inside the orchestrator-granted budget (40 calls in the first window: 2 smoke +
26 eval + 12 benchmark; plus 24 calls for the Milestone-3 re-run below).

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
| manufacturer | 0.979 | 1.0 | 0.979 |
| instructions | 1.0 | 1.0 | 1.0 |
| **macro F1** | **0.99** | **1.0** | **0.99** |

| Mode | VLM calls | VLM invocation rate |
|---|---|---|
| ocr_only | 0 | 0% |
| vlm_only | 24 | 100% |
| ocr_first_vlm | 0 | 0% |

Milestone-3 defaults (`escalation_fields=("name","strength_value")`) mean a
missing optional field never escalates, so this re-run made no OCR-first VLM
calls. The earlier Milestone-2 run (optional fields still escalated) is kept for
comparison: 8.3% escalation and 0.993 hybrid macro F1.

OCR error detail:

- `img_001` (clean): name read as **Metformin HCI** instead of `Metformin HCl`
  at 0.87 confidence — the classic `l`/`I` confusion. The gate did not fire
  because 0.87 clears the 0.75 threshold, so the error survives OCR-first. The
  candidate matcher signal (`candidate_mismatch=True`) is the intended fix.
- One degraded frame dropped the manufacturer line. Under M3 defaults this does
  not escalate; with the M2-era rule it did, and the VLM restored it.

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
3. **OCR-first now follows the Milestone-3 escalation policy.** Missing optional
   fields (manufacturer, form, instructions) never trigger the VLM, so the re-run
   escalated 0/24 times and hybrid output equals the OCR baseline. The recoverable
   manufacturer miss is left for the candidate matcher (or the next scan), which
   is the cheaper place to fix it.
4. **Cost** — VLM-only costs ≈1.53 s per scan (p50 1525.1 ms) versus ≈0.28 s for
   OCR-only (p50 278.1 ms). OCR-first at a 0% escalation rate costs the same as
   OCR-only and still improves once `candidate_mismatch` is wired for the
   confidence-blind reads. Paying the full VLM price on every scan for +1% macro
   F1 on this set is not justified on quality grounds alone.

## Recommendation

**Keep OCR-first. Do not call the VLM on every scan.** Invoke it when:

1. an escalation field (`name`, `strength_value` by default) is missing or weak
   in the OCR read, **or**
2. **candidate matching fails** — the read name or strength does not plausibly
   match the candidate/registry list. This is the signal that catches
   `Metformin HCI` even though the OCR was confident, and the API must pass it as
   `candidate_mismatch=True`; **or**
3. never instead of a rescan: when frame quality is unacceptable, ask for a new
   photo first (`rescan_required` short-circuits the gate).

Optional fields never escalate by themselves: a missing manufacturer or form is
recorded in `uncertainty.reasons` but does not spend a VLM call.

Re-run this evaluation once PI-2's real OCR/extraction stack and PI-4's
candidate matching are integrated, and again on real (non-synthetic) label
photos; the numbers above are a controlled upper bound for clean print.

### Integration contract (Milestone 3)

The API computes the candidate mismatch and passes it through `config`, because
the frozen v1 uncertainty block has no field for it:

```python
from services.ocr.matcher import match_candidates
from services.vlm import should_use_vlm, uncertainty_from_fields

matched = match_candidates(extraction, registered_candidates, threshold=0.75)

uncertainty = uncertainty_from_fields(ocr_fields)
uncertainty["frame_score"] = frame_quality.score      # from PI-1 vision

escalate = should_use_vlm(
    uncertainty,
    config={
        "min_field_confidence": 0.75,                  # tunable (default)
        "escalation_fields": ("name", "strength_value"),  # default
        "min_frame_score": 0.45,                       # tunable; None disables (default)
        "candidate_mismatch": not matched,             # runtime signal from the matcher
    },
)
```

| config key | type | default | meaning |
|---|---|---|---|
| `min_field_confidence` | float | 0.75 | weak-field threshold on escalation fields |
| `escalation_fields` | sequence | `("name", "strength_value")` | only missing/weak fields in this set escalate; optional fields never escalate alone. `critical_fields` is accepted as the Milestone-2 alias |
| `candidate_mismatch` | bool | False | no plausible registry/candidate match for the read name or strength → escalate even at high OCR confidence (fixes the `Metformin HCI` @ 0.87 case) |
| `min_frame_score` | float or None | None | escalate when `uncertainty.frame_score` (or `frame_quality.score`) is below this |
| `invoke_on_rescan` | bool | False | force a VLM call even when a rescan was requested |

Gate semantics: `rescan_required` short-circuits first; then `candidate_mismatch`;
then the frame-score check; then `level == "high"` always escalates, while
`medium`/`low` escalate only on missing/weak escalation fields (no per-field
evidence at all escalates conservatively).

**Candidate matcher (recommended trigger):** PI-2 Orion's live matcher
`services/ocr/matcher.py::match_candidates(extraction, candidates, threshold=0.75)`
returns contract `Candidate` models, best first; an empty list means no plausible
match → pass `candidate_mismatch=True`. Fallback for lexicon-only matching:
`services/ocr/lexicon.match_drug_name`, surfaced via `extract.find_name`.

**Reconciliation equivalence rules** — `reconcile_fields` treats these as
normalization noise, not conflicts:

- case/whitespace folding;
- numeric strength equality and unit aliases (`µg`/`ug` = `mcg`, `MG` = `mg`,
  plurals as in `milligrams`);
- dosage-form plurals (`TABLETS` = `Tablet`);
- names/manufacturers where one value is a leading-token variant of the other
  (`Metformin` = `Metformin HCl`, salt/suffix rule); the more specific value is
  kept;
- instructions compared as parsed items via PI-2's
  `services/ocr/extract.parse_instructions` (lazy import, sentence-split
  fallback), so whitespace/punctuation differences are not conflicts.

Everything else is a **real conflict**: both raw values and both confidences are
preserved in `ReconcileResult.conflicts`, and every conflict records the
resolution reason (confidence margin or fallback rule) in `Conflict.reason`.
The resolution is never silent.

## Reproduce

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r services/vlm/requirements.txt
.venv/bin/python -m services.vlm.dataset.generate          # deterministic
.venv/bin/pytest services/vlm/tests -q                     # 104 tests, no GPU
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
