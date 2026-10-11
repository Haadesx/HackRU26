# Real-photo evidence & interval safety — PI-2 OCR (Orion)

Date: 2026-10-10 · Branch: `feat/ocr-real-evidence` @ `fd4026f` (`origin/feat/integration`)
Environment: macOS arm64, CPU-only inference, live FastAPI in **real mode** on
`127.0.0.1:8300` with VLM escalation enabled (Qwen3-VL endpoint reachable at run time).

> Privacy: the operator's real captures were read directly from the local cache
> (`~/.medcheck/scans/*.png`). **No capture images, OCR text, medication names, or
> patient identifiers from those photos are reproduced or committed here.** Real
> frames are listed only as anonymized IDs R01–R11. Synthetic samples are named
> because they are generated fixtures (`scripts/make_samples.py`).

## Method

| Item | Definition used |
|---|---|
| Endpoint | `POST /v1/scan` (single frame) and `POST /v1/scan/multi` (bundles), `client=test`, `mode=real` |
| Code under test | `fd4026f` (integration HEAD; includes OCR `615997f`) |
| Fields filled | count of non-null values (`source != "none"`) among the nine hub fields: `name, strength, dose_amount, schedule_times, quantity_start, refills_remaining, pharmacy_name, pharmacy_phone, prescriber`. The brief's "8 tracked fields" is measured here as this strict nine-field superset; per-image `filled` is shown as `n/9`. |
| VLM used | `timing.stages.vlm > 0` **or** `interpretation.available == true` (`source="vlm"`) |
| `total_ms` | `timing.total_ms` from the response, verbatim |
| Real images | 11 PNG frames from the operator's local cache (2 × 3-frame capture bundles + 5 single captures), one session, no ground truth |

Port note: an integration-worktree instance (`HEAD fd4026f`, only docs/scripts
modified) was already listening on `:8300`, so the recorded evidence uses it. A second
real-mode instance started from this evidence worktree on `:8302` cross-checked the two
interval cases with identical dose/schedule blocks.

## Aggregates

| Group | n | Status counts | Fields filled (mean) | Fields filled (total) | VLM used | Mean total ms |
|---|---|---|---|---|---|---|
| Real photos | 11 | `uncertain` 11, `needs_rescan` 0, `ok` 0, `no_medication_found` 0 | 3.09 / 9 | 34 / 99 | 9 / 11 | 2548.5 |
| Synthetic samples | 17 | `uncertain` 15, `needs_rescan` 2 | 5.88 / 9 | 100 / 153 | 2 / 17 | 1236.4 |
| Multi-frame bundles (3 frames each) | 2 | `uncertain` 2 | 9.00 / 9 | 18 / 18 | 0 / 2 | mean 5248.6 |

## Real captures per frame (anonymized)

| ID | Status | Fields | VLM used | total ms |
|---|---|---|---|---|
| R01 | uncertain | 1/9 | yes | 2373 |
| R02 | uncertain | 1/9 | yes | 2261 |
| R03 | uncertain | 2/9 | yes | 2260 |
| R04 | uncertain | 2/9 | yes | 2786 |
| R05 | uncertain | 2/9 | yes | 4526 |
| R06 | uncertain | 9/9 | no | 815 |
| R07 | uncertain | 3/9 | yes | 2966 |
| R08 | uncertain | 1/9 | yes | 2064 |
| R09 | uncertain | 9/9 | no | 917 |
| R10 | uncertain | 3/9 | yes | 4109 |
| R11 | uncertain | 1/9 | yes | 2959 |

R06–R11 are the six frames of the two 3-frame bundles (first frames R06/R09 were
captured full-label and read 9/9 without VLM; middle/right frames R07/R08/R10/R11
read 3/9–1/9 and escalated).

## Synthetic samples per image

| ID | File | Status | Fields | VLM used | total ms |
|---|---|---|---|---|---|
| S01 | `label_amoxicillin_interval.png` | uncertain | 6/9 | no | 731 |
| S02 | `label_furosemide_noform.png` | uncertain | 6/9 | no | 545 |
| S03 | `label_lisinopril.png` | uncertain | 9/9 | no | 792 |
| S04 | `label_lisinopril20.png` | uncertain | 7/9 | no | 673 |
| S05 | `label_lisinopril_blurry.png` | **needs_rescan** | 0/9 | no | 201 |
| S06 | `label_lisinopril_dark.png` | uncertain | 9/9 | no | 1027 |
| S07 | `label_metformin.png` | uncertain | 9/9 | no | 1119 |
| S08 | `label_metformin_blurry.png` | **needs_rescan** | 0/9 | no | 190 |
| S09 | `label_metformin_dark.png` | uncertain | 9/9 | no | 1348 |
| S10 | `label_metformin_degraded.png` | uncertain | 4/9 | no | 761 |
| S11 | `label_pantoprazole.png` | uncertain | 7/9 | no | 964 |
| S12 | `label_spironolactone_noform.png` | uncertain | 6/9 | no | 1426 |
| S13 | `label_tamsulosin_noform.png` | uncertain | 6/9 | no | 1034 |
| S14 | `long_label_full.png` | uncertain | 9/9 | no | 2565 |
| S15 | `long_label_left.png` | uncertain | 9/9 | no | 1526 |
| S16 | `long_label_middle.png` | uncertain | 3/9 | yes | 3887 |
| S17 | `long_label_right.png` | uncertain | 1/9 | yes | 2228 |

## Multi-frame bundles

| Bundle | Status | Fields | Frames used | VLM | total ms | Per-frame capture |
|---|---|---|---|---|---|---|
| 3-frame capture A | uncertain | 9/9 | 3/3 (`fusion=multi_frame`) | no | 7541 | all frames `accepted`, `clipped=true` |
| 3-frame capture B | uncertain | 9/9 | 3/3 (`fusion=multi_frame`) | no | 2956 | all frames `accepted`, `clipped=true` |

Fusion turns six individually partial/complete reads into 9/9 in both bundles; no VLM
call was needed on the fused result.

## Interval safety proof (live API, real mode)

Commands (identical for both samples; output piped through `python3 -m json.tool`):

```bash
curl -s -F "image=@samples/label_amoxicillin_interval.png" \
     -F "mode=real" -F "client=test" \
     http://127.0.0.1:8300/v1/scan | python3 -m json.tool

curl -s -F "image=@samples/label_metformin.png" \
     -F "mode=real" -F "client=test" \
     http://127.0.0.1:8300/v1/scan | python3 -m json.tool
```

Observed excerpts (abridged to the fields under test):

```json
// samples/label_amoxicillin_interval.png  (interval wording; schedule must stay null)
{
  "status": "uncertain",
  "mode": "real",
  "instructions": { "dose": { "quantity": 1.0, "unit": "capsule", "confidence": 0.9, "source": "ocr" } },
  "label_meta": { "schedule_times": { "value": null, "confidence": 0.0, "source": "none" } },
  "timing": { "total_ms": 578.75 },
  "uncertainty": { "level": "medium", "reasons": ["missing:manufacturer"], "rescan_required": false }
}
```

```json
// samples/label_metformin.png  (twice-daily wording; schedule derived at low confidence)
{
  "status": "uncertain",
  "mode": "real",
  "instructions": { "dose": { "quantity": 1.0, "unit": "tablet", "confidence": 0.9, "source": "ocr" } },
  "label_meta": { "schedule_times": { "value": "08:00, 20:00", "confidence": 0.72, "source": "ocr" } },
  "timing": { "total_ms": 693.342 },
  "uncertainty": { "level": "medium", "reasons": ["missing:manufacturer"], "rescan_required": false }
}
```

| Check | Result |
|---|---|
| Interval sample: `instructions.dose` present (1 capsule, 0.9, `ocr`) | PASS |
| Interval sample: `label_meta.schedule_times` null / 0.0 / `none` — no invented times | PASS |
| Twice-daily sample: `label_meta.schedule_times` = `"08:00, 20:00"` (0.72, `ocr`) | PASS |
| Cross-check from the evidence-worktree instance on `:8302` | identical dose/schedule blocks (1971.8 ms / 570.3 ms) |

## Findings (no identities)

1. **Garbage OCR did not become `needs_rescan` on real photos.** Two of eleven real
   frames returned a single non-ASCII OCR glyph at ~0.9 line confidence
   (`label.detected=true`), and the pipeline reported `status:"uncertain"` with
   `label_text_unreadable` in `uncertainty.reasons` plus VLM escalation — never
   `needs_rescan`. Failure mode: small/distant label box, detector confident, recognizer
   collapses to one glyph. Clients must treat `uncertainty.reasons`/`rescan_required` as
   the source of truth, not the presence of label text.
2. **VLM escalation carried the real-photo session.** VLM was used on 9/11 real frames;
   without it only the two full-label first frames carried complete data. The three
   garbled-but-non-degenerate single captures recovered identity through VLM.
3. **Multi-frame fusion is the strongest real-photo path.** Both 3-frame bundles fused
   to 9/9 even though their middle/right frames alone produced 1–3 fields; all frames
   were flagged `clipped=true` with rotate guidance, so the capture UX is doing its job.
4. **Synthetic degraded frames behave correctly.** Both blurry variants returned
   `needs_rescan` with 0/9 fields; dark variants still read 9/9; the degraded variant
   returned `uncertain` with 4/9.
5. **No `ok` status was observed anywhere** (real or synthetic). The dominant reason is
   `missing:manufacturer` (many labels do not print it), which keeps `uncertainty.level`
   at medium/high even when all nine hub fields are filled. Status semantics are
   therefore stricter than the field-fill count suggests; both numbers are reported
   above.

## Limitations

- 11 real frames from a single operator session; no ground-truth transcript, so field
  counts measure fill, not correctness.
- VLM availability (home-rig endpoint) affects real-photo results; a run without VLM
  would score lower on partial frames.
- Single run, local CPU; latency numbers include VLM calls when escalation triggered.

## Reproduction

1. `bash scripts/setup_full_env.sh`
2. `set -a; . ~/.medcheck/vllm.env; set +a`
3. `MEDCHECK_API_MODE=real MEDCHECK_VLM_ENABLED=1 .venv-full/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8300`
4. `curl -s http://127.0.0.1:8300/ready` → `{"ready":true,"mode":"real","components":{...,"vlm":"enabled"}}`
5. Re-run the two curl commands in the interval-safety section; iterate `samples/*.png`
   and (locally only) `~/.medcheck/scans/*.png` with `POST /v1/scan`.
