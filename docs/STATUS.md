# MedCheck Task Board (live)

Owner: **ORCHESTRATOR (Apollo)**. Technical details live in
**`docs/inference-medcheck.md`** (single source of truth). This file is the board only:
gates, dispatch, and status. Legend: `TODO` / `WIP` / `BLOCKED` / `DONE` / `MERGED`.

## Integration branch

`feat/inference-medcheck` (never `main`). Remote `origin` =
`https://github.com/Haadesx/HackRU26` (was empty at 2026-10-10; `main` intentionally
untouched). Push only feature branches.

## Team

| Agent | Role | Branch | Worktree | Terminal node |
|---|---|---|---|---|
| Apollo | Orchestrator / integration / docs | `feat/inference-medcheck` | repo root | `term-mv2rzwwy-f` |
| Atlas | PI-1 VISION | `feat/vision-atlas` | `.worktrees/pi-1-vision` | `term-mv2s2l67-g` |
| Orion | PI-2 OCR | `feat/ocr-orion` | `.worktrees/pi-2-ocr` | `term-mv2s36el-h` |
| Juno | PI-3 VLM | `feat/vlm-juno` | `.worktrees/pi-3-vlm` | `term-mv2s5dfg-k` |
| Athena | PI-4 API | `feat/api-athena` | `.worktrees/pi-4-api` | `term-mv2s69eu-p` |

## Gates

| Gate | Description | Status |
|---|---|---|
| G1 | Harness/Oct-Bus identification, repo init, frozen contracts | DONE (`51569fd`) |
| G2 | Worktrees + dispatch all four workers | DONE |
| G3 | Mock FastAPI scan endpoint live on :8300 | DELIVERED by Athena (`a855318`); orchestrator re-verify + merge WIP |
| G4 | Real OCR integrated, structured extraction verified | OCR module delivered (`987dd88`); API wiring TODO |
| G5 | Bottle detection + frame guidance integrated | Vision module delivered (`f55025c`); API wiring TODO |
| G6 | Qwen3-VL benchmarked + integrated where beneficial | Benchmarked (hybrid F1 0.993, p50 1.58 s); API wiring TODO |
| G7 | Full integration tests + GPU measurements | TODO |
| G8 | Mac→home-rig inference through approved private connection | vLLM `/v1/models` from Mac verified; end-to-end scan TODO |
| G9 | Stable contract delivered to iOS/backend | Contract frozen; handoff package TODO |

## Worker milestone 1 — delivered (2026-10-10, worker-reported)

| Branch | HEAD | Tests (worker) | Notes |
|---|---|---|---|
| `feat/vision-atlas` | `f55025c` | 46 passed | quality/detect/label, CPU fallback |
| `feat/ocr-orion` | `987dd88` | 25 passed | RapidOCR; 33/33 extraction, 8/8 e2e |
| `feat/vlm-juno` | `9ac2305` | 79 passed | 24-img eval; hybrid F1 0.993; escalation 8.3 % |
| `feat/api-athena` | `a855318` | 40 passed | mock gateway :8300; live smoke OK |

## Dispatch log (append-only, board level)

- 2026-10-10 — G1/G2 done; all four assignments dispatched via `octoberctl terminal input`
  (Apollo terminal is `user-shell` on the Bus; see `docs/inference-medcheck.md` §H.2).
- 2026-10-10 — All four milestone-1 reports queued to Apollo; orchestrator scope review
  clean; re-verification and merge into `feat/inference-medcheck` in progress.
- 2026-10-10 — Documentation system adopted (standing rule in `AGENTS.md` §0):
  `docs/inference-medcheck.md` maintained by the orchestrator; workers include `DOC:`
  blocks in reports.
