# MedCheck Local Test Console

A tiny local harness to exercise the **real inference engine** from a Mac without the
iOS app. It serves a single page where you can upload a photo or capture one with the
Mac camera, then shows the structured `ScanResponse` (status, fields with confidence and
source, candidates, guidance, timing) with bottle/label boxes drawn on the image.

```
scripts/local_scan.sh          # real mode + VLM fallback (uses ~/.medcheck/vllm.env)
scripts/local_scan.sh --no-vlm # real OCR-first only (no rig calls)
scripts/local_scan.sh --mock   # mock pipeline
```

Then open <http://127.0.0.1:8400> (the script opens it for you). Ctrl-C stops both
processes.

## How it works

```
browser ──POST /api/scan──▶ tools/local_scan/server.py ──POST :8300/v1/scan──▶ FastAPI
   ▲                              (stdlib proxy, no CORS,                  (vision→OCR→
   └──────── JSON ScanResponse ─── images forwarded in memory) ───────────── registry→VLM)
```

- `tools/local_scan/server.py` — stdlib `ThreadingHTTPServer`; serves `index.html`,
  proxies `/api/health`, `/api/ready`, `/api/scan`. Nothing is written to disk.
- `tools/local_scan/index.html` — vanilla JS UI: file upload, `getUserMedia` webcam
  capture, bbox overlay, field/confidence rendering, raw JSON.
- Requires the combined env from `scripts/setup_full_env.sh` (`.venv-full`) and, for
  real mode, the API key in `~/.medcheck/vllm.env` (mode 600, never committed).

## Notes

- Camera capture needs `localhost` (allowed by browsers) — no TLS required.
- Real-mode clean labels return in ~0.5 s (OCR only). Weak or registry-mismatched reads
  escalate to the shared Qwen3-VL on `hermes-linux` (~+1.7 s). This is by design.
- Informational only — not medical advice. Inference never infers ingestion and never
  authorizes dosing.
