# MedCheck Task Board & Integration Log

Owner: **ORCHESTRATOR (Apollo)**. Updated at every gate. Workers report via Bus; only
the orchestrator edits this file.

Legend: `TODO` / `WIP` / `BLOCKED` / `DONE` / `MERGED`
Branch: `main` is integration-only. Date line uses UTC.

## Team

| Agent | Role | Branch | Worktree | Terminal node |
|---|---|---|---|---|
| Apollo | Orchestrator / integration | `main` | repo root | `term-mv2rzwwy-f` |
| Atlas | PI-1 VISION | `feat/vision-atlas` | `.worktrees/pi-1-vision` | `term-mv2s2l67-g` |
| Orion | PI-2 OCR | `feat/ocr-orion` | `.worktrees/pi-2-ocr` | `term-mv2s36el-h` |
| Juno | PI-3 VLM | `feat/vlm-juno` | `.worktrees/pi-3-vlm` | `term-mv2s5dfg-k` |
| Athena | PI-4 API | `feat/api-athena` | `.worktrees/pi-4-api` | `term-mv2s69eu-p` |

## Gates

| Gate | Description | Status |
|---|---|---|
| G1 | Harness/Oct-Bus identification, repo init, frozen contracts | WIP |
| G2 | Worktrees + dispatch all four workers | TODO |
| G3 | Mock FastAPI scan endpoint live on :8300 | TODO |
| G4 | Real OCR integrated, structured extraction verified | TODO |
| G5 | Bottle detection + frame guidance integrated | TODO |
| G6 | Qwen3-VL benchmarked + integrated where beneficial | TODO |
| G7 | Full integration tests + GPU measurements | TODO |
| G8 | Mac→home-rig inference through approved private connection (Tailscale/SSH) | TODO |
| G9 | Stable contract delivered to iOS/backend | TODO |

## Dispatch log

- 2026-10-10 — Environment identified: upstream **Pi 1.1.0** (not an October Pi fork);
  October Desktop harness is OpenCode-derived `0.87.1-october.3`. Pi talks to October
  via the auto-generated `~/.pi/agent/extensions/october-bus.ts` + `october-bus-static`
  Bus MCP. Four worker agent-terminals verified live; Apollo terminal is a `user-shell`
  terminal (bus mutating tools refused: `unactivated-terminal`), so outbound dispatch
  uses October's sanctioned `octoberctl terminal input`; inbound uses the native Bus
  wake path. Loop verified end-to-end with Atlas.

## Notes

- Existing vLLM Qwen3-VL on `hermes-linux` was up at kickoff: 32,607 MiB total,
  17,659 MiB used, 14,430 MiB free. Treat it as shared; never restart it.
- One intrusive GPU experiment at a time, granted by the orchestrator.
