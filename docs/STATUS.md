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
| G3 | Mock FastAPI scan endpoint live on :8300 | DONE + MERGED (`2ba5a12`), re-verified |
| G4 | Real OCR integrated, structured extraction verified | DONE: real pipeline merged (`b6bbbef`); live sharp scan extracted Metformin 500 mg |
| G5 | Bottle detection + frame guidance integrated | DONE: vision merged (`5b60648`); live blurry scan → needs_rescan + guidance in 19.5 ms |
| G6 | Qwen3-VL benchmarked + integrated where beneficial | DONE for pipeline: live real VLM call 1745 ms, VRAM unchanged; tuning items in doc §K |
| G7 | Full integration tests + GPU measurements | DONE (core): **277/277 merged tests**; VRAM measured (13,706 MiB free, unchanged); concurrency profile TODO |
| G8 | Mac→home-rig inference through approved private connection | CORE VERIFIED: Mac→Tailscale→rig vLLM through the live API; final hardening TODO |
| G9 | Stable contract delivered to iOS/backend | Contract frozen + pushed; handoff package/correctness review TODO |

## Worker milestone 1 — delivered (2026-10-10, worker-reported)

| Branch | HEAD | Tests (worker) | Notes |
|---|---|---|---|
| `feat/vision-atlas` | `ae1c3a8` | 76 passed | noise-immunity gate added; merged into integration |
| `feat/ocr-orion` | `09c41d3` | 52 passed | candidate matcher + Extraction-shape fix |
| `feat/vlm-juno` | `338759d` | 91 passed | escalation triggers + client_from_env |
| `feat/api-athena` | `7200f0c` | 56 passed | real OCR-first pipeline + EXIF regression |

## Dispatch log (append-only, board level)

- 2026-10-10 — G1/G2 done; all four assignments dispatched via `octoberctl terminal input`
  (Apollo terminal is `user-shell` on the Bus; see `docs/inference-medcheck.md` §H.2).
- 2026-10-10 — All four milestone-1 reports queued to Apollo; orchestrator scope review
  clean; re-verification and merge into `feat/inference-medcheck` in progress.
- 2026-10-10 — Documentation system adopted (standing rule in `AGENTS.md` §0):
  `docs/inference-medcheck.md` maintained by the orchestrator; workers include `DOC:`
  blocks in reports.
- 2026-10-10 — `feat/inference-medcheck` pushed to `origin` (branch only; `main` remains
  untouched). Milestone 1 merged + verified (42 tests green, live smoke OK).
- 2026-10-10 — Milestone 2 dispatched: Athena wires the real Vision→OCR pipeline
  (+VLM behind flags, matcher pending Orion); Orion builds the registered-candidate
  matcher; Atlas adds `crop_label`/CLI demo/detector env docs; Juno extends escalation
  triggers + `client_from_env()` (no GPU).
- 2026-10-10 — Wake delivery verified: worker nodes receive `october-bus-wake`
  end-to-end (Orion, receipt `9b300f77-…`); Apollo's user-shell terminal is refused at
  the hook admission layer (`{"ok":false,"stale":true}`) — root cause proven in
  October core. Orchestrator inbound = transcripts + `bus peers`; outbound = pty input.
- 2026-10-10 — Milestone 2 merged (`b6bbbef`/`a49afd0`/`5b60648`/`91a5c83`); vision
  noise regression fixed (`ae1c3a8`); merged suite **277 passed / 0 failed**. Real-mode
  live acceptance: OCR-first + real VLM end-to-end (2272 ms total, VLM 1745 ms, VRAM
  unchanged 13,706 MiB free); blurry gate 19.5 ms → needs_rescan; matcher verified live
  with hints (match 1.0 / mismatch empty).
