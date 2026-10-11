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

# Guard the signal: `not matched` alone is True on every no-hints scan because
# the matcher returns [] for an empty candidate list. Only claim a mismatch when
# the caller supplied a registry AND the read has an identity field.
registered_candidates = known_candidates_from_request(hints)
has_identity = extraction.name.value is not None or extraction.strength.value is not None
matched = (
    match_candidates(extraction, registered_candidates, threshold=0.75)
    if registered_candidates and has_identity
    else []
)
candidate_mismatch = bool(registered_candidates) and has_identity and not matched

uncertainty = uncertainty_from_fields(ocr_fields)
uncertainty["frame_score"] = frame_quality.score      # from PI-1 vision

escalate = should_use_vlm(
    uncertainty,
    config={
        "min_field_confidence": 0.75,                  # tunable (default)
        "escalation_fields": ("name", "strength_value"),  # default
        "min_frame_score": 0.45,                       # tunable; None disables (default)
        "candidate_mismatch": candidate_mismatch,      # registry present, no plausible match
    },
)
```

`candidate_mismatch=True` means: a registry was supplied, an identity field was read,
and nothing scored at or above the match threshold. Without the registry/identity
guard, a literal `not matched` escalates every scan without hints.

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

**Degenerate OCR replacement (M8).** For `instructions` (primary) and `name`
(secondary), an OCR value with fewer than `degenerate_min_alpha` ASCII letters
(default 8, e.g. a single glyph read at 0.90) is replaced by a readable VLM value
(≥ 8 ASCII letters) regardless of the confidence margin. The conflict carries
`kind="degenerate"` and surfaces as `ocr_vlm_degenerate:<field>` with both values
preserved. Two readable values that genuinely disagree keep the margin rule; an
empty side keeps the missing-field path. Fields and threshold are configurable
(`degenerate_fields`, `degenerate_min_alpha`), and the rule applies unchanged to
single-frame and multi-frame reconciliation.

### Multi-frame escalation (Milestone 7)

When the app captures several frames of the same long or rotated label, OCR fuses
them into one read. If fusion still leaves identity weak or the frames disagree,
the VLM should see **all frames in one request** — not one call per frame.

**Client** — `Qwen3VLClient.interpret_multi(images, ocr_text=None, question=None)`
sends one OpenAI-style `image_url` part per frame plus a fusion-aware prompt, with
the same lenient parsing, timeouts and retries-off behaviour as `interpret()`
(which is unchanged). Requests are capped at `max_frames`
(`MEDCHECK_VLM_MAX_FRAMES`, default 6); an empty list, an unsupported image, or
too many frames raise `VlmImageError`, and service failures return
`available=False`.

**Gate** — `should_use_vlm_multi(uncertainty, config)`:

1. `rescan_required` short-circuits first (retaking beats even a conflict);
2. `fusion_conflicts` escalates — a truthy bool, or a non-empty list of
   disagreeing canonical field names such as `["name"]`; the signal may also be
   passed in `config`;
3. otherwise identical to `should_use_vlm` — weak/missing escalation fields,
   `candidate_mismatch`, low `min_frame_score`, level `high`.

Extra `uncertainty` keys for multi-frame calls: `frames` (int, how many were
fused) and `fusion_conflicts`.

**When the API should call it:** only for multi-frame captures
(`capture.fusion == "multi_frame"`) where the gate above fires. A multi-frame scan
with agreeing frames and confident identity does not spend a VLM call, and
single-frame scans keep using `should_use_vlm` + `interpret` unchanged.

**Real smoke (2026-10-10, 3 sequential calls in the granted window):**
`samples/long_label_{left,middle,right,full}.png`.

| Call | Frames | Latency | Result |
|---|---|---|---|
| `interpret(left)` | 1 | 2036.3 ms | name/strength/manufacturer/instructions read |
| `interpret_multi(left, middle, right)` | 3 | 1836.6 ms | same identity, fused in one request |
| `interpret(full)` | 1 | 2235.8 ms | same identity |

All three returned `available=true` with no errors. VRAM 18,773 → 18,847 MiB used
of 32,607 (13.2 GiB free); `echo-vllm` was not touched. Caveat: on these particular
crops one frame already carried the pharmacy fields, so the smoke proves the
multi-image wire format end-to-end rather than a quality win; the target case is
frames that each miss different fields, which is what the gate exists to catch.

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

## Verification-flow QA (2026-10-10)

QA of the hub verification flow: are any zero-confidence inference defaults
reaching scan responses? Six synthetic labels were scanned sequentially through
the running gateway on `:8300` in `mode=real` with hub-style hints
(`{"known_candidates": [tracked med], "locale": "en-US"}`, `client=test`).
No VLM was invoked on these six: identity was confident and matched the tracked
candidate, and optional fields (form, manufacturer) do not escalate under the M3
policy.

| Sample | status | `medication.form` (value/conf/source) | dose (conf/source) | interp.available | wall | VLM |
|---|---|---|---|---|---|---|
| `label_metformin.png` | uncertain | tablet / 0.75 / ocr | 0.9 / ocr | false | 924.1 ms | 0 ms |
| `label_lisinopril.png` | uncertain | tablet / 0.75 / ocr | 0.9 / ocr | false | 855.9 ms | 0 ms |
| `label_furosemide_noform.png` | uncertain | **absent (None)** | 0.0 / none | false | 733.1 ms | 0 ms |
| `label_amoxicillin_interval.png` | uncertain | capsule / 0.9 / ocr | 0.9 / ocr | false | 879.5 ms | 0 ms |
| `label_pantoprazole.png` | uncertain | tablet / 0.75 / ocr | 0.9 / ocr | false | 654.0 ms | 0 ms |
| `label_metformin_blurry.png` | needs_rescan | absent (None) | none | false | 171.2 ms | — |

Result: **no zero-confidence form or name reached any response**; the formless
label returned `form: None` (not `tablet @ 0.0`); the blurry frame short-circuited
to `needs_rescan` before OCR/VLM.

**Guard probe.** Because none of the six invoked the VLM, the reconcile guard was
exercised with a deliberate mismatch: scanning the formless furosemide label with
`known_candidates` for a different medication forces `candidate_mismatch` → VLM.
On the shared `:8300` process the response still contained
`form: {value: "tablet", confidence: 0.0, source: "vlm"}`. Root cause: the
gateway process started 20:50, while the guard landed in `3369b10` at 21:40 — the
running interpreter predates the fix. A throwaway instance of this branch
(`:8310`, same vLLM, stopped afterwards) with the same forced-VLM probe returned
`form: None`, `interpretation.available: true`, `vlm 1675.7 ms`, and no
zero-confidence non-null value anywhere in the response. VRAM stayed at
18,847–18,895 / 32,607 MiB used; `echo-vllm` was never touched.

**Guard rationale.** A zero-confidence VLM value is not evidence: the model often
emits a schema default (e.g. `form="tablet"`) for a field the label never
states. `reconcile_fields` drops VLM-only values with `confidence <= 0`, so the
gateway never presents a guess as a read; real conflicts between readable values
still resolve through the margin rule with source attribution.

**Action for the shared gateway:** restart `:8300` so it loads `3369b10`+, then
re-run the forced-VLM probe. Mocked suites on this branch: `pytest services/vlm`
→ 135 passed; the guard does not change `should_use_vlm`/`should_use_vlm_multi`
behaviour (`escalation_fields` and fusion triggers untouched).
