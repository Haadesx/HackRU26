#!/usr/bin/env bash
# MedCheck local test console — one command, no iOS needed.
#
#   scripts/local_scan.sh              # real inference + VLM fallback enabled
#   scripts/local_scan.sh --no-vlm     # real OCR-first, no VLM calls
#   scripts/local_scan.sh --mock       # mock pipeline (UI/dev testing)
#   scripts/local_scan.sh --no-open    # do not open the browser
#
# Opens http://127.0.0.1:8400 — upload a photo or use the Mac camera.
# Ctrl-C stops both the API and the console.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE=real; VLM=1; OPEN=1
for arg in "$@"; do
  case "$arg" in
    --mock) MODE=mock ;;
    --no-vlm) VLM=0 ;;
    --no-open) OPEN=0 ;;
    *) echo "unknown flag: $arg"; exit 2 ;;
  esac
done

if [ ! -x .venv-full/bin/python ]; then
  echo "Combined env missing — run: scripts/setup_full_env.sh"
  exit 1
fi
if [ "$MODE" = "real" ] && [ -f "$HOME/.medcheck/vllm.env" ]; then
  set -a; . "$HOME/.medcheck/vllm.env"; set +a
fi

echo "Starting MedCheck API (mode=$MODE, vlm=$VLM) on :8300 …"
MEDCHECK_API_MODE="$MODE" MEDCHECK_VLM_ENABLED="$VLM" \
  .venv-full/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8300 --log-level warning &
API_PID=$!
MEDCHECK_API=http://127.0.0.1:8300 .venv-full/bin/python tools/local_scan/server.py &
UI_PID=$!

cleanup() { kill "$API_PID" "$UI_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8300/health >/dev/null 2>&1 && break; sleep 0.5; done
curl -s http://127.0.0.1:8300/ready || true; echo
[ "$OPEN" = 1 ] && open http://127.0.0.1:8400 2>/dev/null || true
echo "Console: http://127.0.0.1:8400   (Ctrl-C to stop)"
wait
