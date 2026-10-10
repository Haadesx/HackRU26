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
| G6 | Qwen3-VL benchmarked + integrated where beneficial | DONE: clean scans skip the VLM (541 ms); escalation only on weak/mismatched identity (VLM ~1.7 s) |
| G7 | Full integration tests + GPU measurements | DONE: **293/293**; VRAM measured; concurrency profile done |
| G8 | Mac→home-rig inference through approved private connection | DONE (core): Mac→Tailscale→rig vLLM through the live API, verified multiple times |
| G9 | Stable contract delivered to iOS/backend | READY: contract frozen + `HANDOFF.md` + examples; awaiting consumers (registry input, auth decision) |

## Worker milestones — delivered (2026-10-10)

| Branch | Tip | Tests (worker) | Notes |
|---|---|---|---|
| `feat/vision-atlas` | `ae1c3a8` | 76 passed | noise gate; merged (`5b60648`+`34480c3`) |
| `feat/ocr-orion` | `09c41d3` | 52 passed | matcher; merged (`a49afd0`) |
| `feat/vlm-juno` | `16ca2dd` | 104 passed | M3 fields+normalization; merged (`fc5ff80`) |
| `feat/api-athena` | `66d58b0` | 59 passed | M3 escalation wiring + HANDOFF; merged (`4d0d32c`) |

## Final verification (orchestrator)

- Fresh env full suite: **293 passed / 0 failed** (vision 76 · ocr 52 · vlm 104 · api 59 · integration 2).
- Real-mode live: clean scan 541 ms (no VLM call); candidate mismatch → VLM 1696 ms;
  blurry → needs_rescan 19.5 ms; VRAM 13,706 MiB free unchanged.
- All four worker branches scope-clean; integration branch pushed (`origin`), `main`
  untouched.

## Cross-team integration

- **Urvi `feat/backend-urvi` @ `85fc33f`** — verified 2026-10-10: clean merge into our
  branch (64 files, no conflicts), scan ingest contract-aligned, TimescaleDB healthy.
  **Blocker:** `backend/app/models/` was silently excluded from her push by our
  unanchored `.gitignore` rule `models/`; fixed in `179c4d6`. She must merge the fix,
  `git add backend/app/models`, and push. Tests: blocked until then (collection error).
  Open decision: backend requires numeric `quantity` in `POST /scans`; v1 ScanResponse
  has no structured dose quantity (only parsed text) — decide client default vs v1.1.

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
- 2026-10-10 — M3 dispatched (Athena: escalation config wiring + HANDOFF.md; Juno:
  identity-critical escalation fields + reconcile normalization). Reproducible combined
  env verified (`scripts/setup_full_env.sh` → 277/277). Concurrency: sequential p50
  745 ms; 8 concurrent scans ~2.1 s wall.
