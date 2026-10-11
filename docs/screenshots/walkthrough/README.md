# Final demo walkthrough (recorded 2026-10-11, pre-submission freeze)

Artifacts produced by `tools/ui_capture/walkthrough.mjs` against the real stack
(React :5199 → Flask `/hub` :8000 → TimescaleDB :5433 → inference :8300).

| File | Step |
|---|---|
| `01-home.png` | Dashboard (Home) |
| `02-scan-page.png` | Scan entry page |
| `03-verify-due-now.png` | After pressing **“Log this dose now”** — shows the confirmation text |
| `04-home-after-log.png` | Home reflects the logged dose (“Taken 12:02 AM, logged by you”) |
| `05-verify-wrong-medication.png` | Untracked bottle → warning state |
| `06-verify-strength-mismatch.png` | 20 mg bottle vs 10 mg prescription → danger state |
| `07-verify-uncertain.png` | Strength read at `unsure` → uncertain, no action offered |
| `08-verify-capsule-copy.png` | Capsule label → capsule-aware copy |
| `demo-walkthrough.webm` / `.mp4` | Full recording of the 8-step run, 1440×900 |

Notes:
- The run used one **disposable fixture** (`Furosemide 40 mg`, slot at the run time) so the
  explicit confirmation could be demonstrated without touching the demo patient's real
  medications; it was stopped and its rows removed immediately afterwards (the recorded
  screenshots still show it, as they must — see the handoff, “demo walkthrough”).
- 0 browser console errors; no horizontal overflow.
- The scan itself never records a dose: only the button press did, and the scan page states so.
