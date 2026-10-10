# MedCheck Local Test Console

A tiny local harness to exercise the **real inference engine** from a Mac without the
iOS app. It serves a single page where you can upload a photo or capture one with the
Mac camera, then shows the structured `ScanResponse` (status, fields with confidence and
source, candidates, guidance, timing) with bottle/label boxes drawn on the image.

```
scripts/local_scan.sh --daemon   # start in background (survives terminal close) ← recommended
scripts/local_scan.sh            # real mode + VLM fallback, foreground (Ctrl-C stops)
scripts/local_scan.sh --no-vlm   # real OCR-first only (no rig calls)
scripts/local_scan.sh --mock     # mock pipeline
scripts/local_scan.sh --status   # is it running?
scripts/local_scan.sh --stop     # stop the daemon instance
```

Daemon mode keeps the API + console alive after the terminal/tool session ends (logs in
`$TMPDIR/medcheck-local-scan/`). Then open <http://127.0.0.1:8400>.

## Live mode (real-time)

Click **Start camera → Start live mode** and point it at a bottle. Every ~250 ms the page
sends a small frame to `/api/live`, which runs the vision stack only (~20 ms after warmup)
and paints live boxes:

- status line: `quality 92% ✓ · bottle 0% ✗ · label 88% ✓ · <camera guidance>`
- when quality is acceptable **and** a label is found for 2 consecutive frames, it
auto-scans (full OCR → registry → VLM only if needed) and fills the result panel
- auto-scan is throttled to one full scan every ~6 s so the VLM path cannot be spammed

## Debug scan bundles

Every scan is saved locally (image + response JSON) under `~/.medcheck/scans/` (last 40,
auto-rotated) and listed at <http://127.0.0.1:8400/api/scans>. Disable with
`MEDCHECK_SAVE_SCANS=0`. Nothing leaves the machine.

## How it works

```
browser ──POST /api/scan──▶ tools/local_scan/server.py ──POST :8300/v1/scan──▶ FastAPI
   ▲                              (stdlib proxy, no CORS,                  (vision→OCR→
   └──────── JSON ScanResponse ─── images forwarded in memory) ───────────── registry→VLM)
```

- `tools/local_scan/server.py` — stdlib `ThreadingHTTPServer`; serves `index.html`,
  proxies `/api/health`, `/api/ready`, `/api/scan`, and runs the vision-only `/api/live`
  fast path in-process (imports `services.vision`; needs `.venv-full`).
- `tools/local_scan/index.html` — vanilla JS UI: file upload, `getUserMedia` webcam
  capture, live mode with auto-scan, bbox overlay, field/confidence rendering, raw JSON.
- Requires the combined env from `scripts/setup_full_env.sh` (`.venv-full`) and, for
  real mode, the API key in `~/.medcheck/vllm.env` (mode 600, never committed).

## Notes

- Camera capture needs `localhost` (allowed by browsers) — no TLS required.
- Real-mode clean labels return in ~0.5 s (OCR only). Weak or registry-mismatched reads
  escalate to the shared Qwen3-VL on `hermes-linux` (~+1.7 s). This is by design.
- Informational only — not medical advice. Inference never infers ingestion and never
  authorizes dosing.
