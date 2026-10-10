#!/usr/bin/env bash
# MedCheck local test console — one command, no iOS needed.
#
#   scripts/local_scan.sh --daemon     # start in background (survives terminal close), prints URL
#   scripts/local_scan.sh              # start in foreground (Ctrl-C stops)
#   scripts/local_scan.sh --stop       # stop a daemon instance
#   scripts/local_scan.sh --status     # is it running?
#
# Flags: --no-vlm  (real OCR only)   --mock  (mock pipeline)   --no-open  (don't open browser)
#
# UI: http://127.0.0.1:8400  ·  API: http://127.0.0.1:8300
set -euo pipefail
cd "$(dirname "$0")/.."

MODE=real; VLM=1; OPEN=1; DAEMON=0
RUN_DIR="${TMPDIR:-/tmp}/medcheck-local-scan"
PID_API="$RUN_DIR/api.pid"; PID_UI="$RUN_DIR/ui.pid"
LOG_API="$RUN_DIR/api.log"; LOG_UI="$RUN_DIR/ui.log"

for arg in "$@"; do
  case "$arg" in
    --mock) MODE=mock ;;
    --no-vlm) VLM=0 ;;
    --no-open) OPEN=0 ;;
    --daemon|-d) DAEMON=1 ;;
    --stop)
      for f in "$PID_UI" "$PID_API"; do
        [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true
      done
      pkill -f "tools/local_scan/server.py" 2>/dev/null || true
      pkill -f "uvicorn services.api.main:app" 2>/dev/null || true
      rm -f "$PID_API" "$PID_UI"
      echo "stopped (if it was running)"; exit 0 ;;
    --status)
      ok=0
      curl -sf http://127.0.0.1:8400/ >/dev/null 2>&1 && { echo "console: RUNNING (http://127.0.0.1:8400)"; ok=1; }
      curl -sf http://127.0.0.1:8300/health >/dev/null 2>&1 && echo "api: RUNNING" || true
      [ "$ok" = 1 ] || echo "console: not running"
      exit 0 ;;
    *) echo "unknown flag: $arg"; exit 2 ;;
  esac
done

if [ ! -x .venv-full/bin/python ]; then
  echo "Combined env missing — run: scripts/setup_full_env.sh"; exit 1
fi
if lsof -ti :8400 >/dev/null 2>&1 && [ "$DAEMON" = 1 ]; then
  echo "Already running → http://127.0.0.1:8400  (use --stop to stop)"; exit 0
fi
if lsof -ti :8300 >/dev/null 2>&1; then
  echo "Port 8300 is already in use by another process:"; lsof -nP -iTCP:8300 | head -4
  echo "Stop it or use --stop for a previous MedCheck instance."; exit 1
fi
if [ "$MODE" = "real" ] && [ -f "$HOME/.medcheck/vllm.env" ]; then
  set -a; . "$HOME/.medcheck/vllm.env"; set +a
fi

# Use the ONNX YOLO detector when its weights are present (scripts/download_models.sh).
if [ -z "${MEDCHECK_YOLO_MODEL:-}" ] && [ -f "models/yolo11n.onnx" ]; then
  export MEDCHECK_YOLO_MODEL="models/yolo11n.onnx"
fi

start_api() {
  MEDCHECK_API_MODE="$MODE" MEDCHECK_VLM_ENABLED="$VLM" \
    .venv-full/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8300 --log-level warning "$@"
}
start_ui() {
  MEDCHECK_API=http://127.0.0.1:8300 .venv-full/bin/python tools/local_scan/server.py "$@"
}

if [ "$DAEMON" = 1 ]; then
  export MODE VLM MEDCHECK_YOLO_MODEL   # daemon children are separate shells — export these
  mkdir -p "$RUN_DIR"
  nohup bash -c "$(declare -f start_api); start_api" >"$LOG_API" 2>&1 &
  echo $! > "$PID_API"
  nohup bash -c "$(declare -f start_ui); start_ui" >"$LOG_UI" 2>&1 &
  echo $! > "$PID_UI"
  for _ in $(seq 1 60); do curl -sf http://127.0.0.1:8400/ >/dev/null 2>&1 && break; sleep 0.5; done
  if curl -sf http://127.0.0.1:8400/ >/dev/null 2>&1; then
    ready=$(curl -s http://127.0.0.1:8300/ready || true)
    echo "MedCheck console running → http://127.0.0.1:8400"
    echo "  api: $ready"
    echo "  logs: $LOG_API  ·  $LOG_UI"
    echo "  stop: scripts/local_scan.sh --stop"
    [ "$OPEN" = 1 ] && open http://127.0.0.1:8400 2>/dev/null || true
    exit 0
  fi
  echo "Failed to start. Logs:"; tail -20 "$LOG_API" "$LOG_UI" 2>/dev/null; exit 1
fi

# foreground mode
echo "Starting MedCheck API (mode=$MODE, vlm=$VLM) on :8300 …"
start_api &
API_PID=$!
start_ui &
UI_PID=$!
cleanup() { kill "$API_PID" "$UI_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8300/health >/dev/null 2>&1 && break; sleep 0.5; done
curl -s http://127.0.0.1:8300/ready || true; echo
[ "$OPEN" = 1 ] && open http://127.0.0.1:8400 2>/dev/null || true
echo "Console: http://127.0.0.1:8400   (Ctrl-C to stop)"
wait
