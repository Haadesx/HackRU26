#!/usr/bin/env bash
# Run the full MedCheck demo stack: inference API + hub adapter + web UI.
#
#   scripts/run_ui_demo.sh          # start everything, print URLs
#   scripts/run_ui_demo.sh --stop   # stop hub adapter + UI (leaves the API/console)
#
# Stack:  inference :8300  →  hub adapter :8500  →  web UI :5199
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_DIR="${TMPDIR:-/tmp}/medcheck-ui-demo"
mkdir -p "$RUN_DIR"

stop_all() {
  for f in "$RUN_DIR/ui.pid" "$RUN_DIR/hub.pid"; do
    [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true
  done
  pkill -f "tools.hub_adapter.app" 2>/dev/null || true
  pkill -f "vite.*--port 5199" 2>/dev/null || true
  rm -f "$RUN_DIR"/*.pid
  echo "stopped hub adapter + UI (inference API left running)"
}

[ "${1:-}" = "--stop" ] && { stop_all; exit 0; }

[ -x .venv-full/bin/python ] || { echo "run scripts/setup_full_env.sh first"; exit 1; }
[ -d frontend/node_modules ] || { echo "frontend deps missing — run: (cd frontend && npm install)"; exit 1; }

# ── inference API (:8300) — reuse the console daemon if it is up
if ! curl -sf http://127.0.0.1:8300/health >/dev/null 2>&1; then
  echo "starting inference API on :8300 …"
  [ -f "$HOME/.medcheck/vllm.env" ] && { set -a; . "$HOME/.medcheck/vllm.env"; set +a; }
  YOLO=""
  [ -f models/yolo11n.onnx ] && YOLO="models/yolo11n.onnx"
  MEDCHECK_API_MODE=real MEDCHECK_VLM_ENABLED=1 MEDCHECK_YOLO_MODEL="$YOLO" \
    nohup .venv-full/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8300 >"$RUN_DIR/api.log" 2>&1 &
  echo $! > "$RUN_DIR/api.pid"
  for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8300/health >/dev/null 2>&1 && break; sleep 0.5; done
fi

# ── hub adapter (:8500) — the UI's contract, backed by real inference
if ! curl -sf http://127.0.0.1:8500/health >/dev/null 2>&1; then
  echo "starting hub adapter on :8500 …"
  nohup .venv-full/bin/uvicorn tools.hub_adapter.app:app --host 127.0.0.1 --port 8500 >"$RUN_DIR/hub.log" 2>&1 &
  echo $! > "$RUN_DIR/hub.pid"
  for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8500/health >/dev/null 2>&1 && break; sleep 0.5; done
fi

# ── web UI (:5199)
if ! curl -sf http://127.0.0.1:5199/ >/dev/null 2>&1; then
  echo "starting web UI on :5199 …"
  ( cd frontend && VITE_API_URL=http://127.0.0.1:8500 nohup npm run dev -- --host 127.0.0.1 --port 5199 --strictPort >"$RUN_DIR/ui.log" 2>&1 & echo $! > "$RUN_DIR/ui.pid" )
  for _ in $(seq 1 60); do curl -sf http://127.0.0.1:5199/ >/dev/null 2>&1 && break; sleep 0.5; done
fi

echo
echo "MedCheck demo stack"
echo "  web UI        → http://127.0.0.1:5199   (camera scan, verify, add)"
echo "  hub adapter   → http://127.0.0.1:8500   (UI contract → real inference)"
echo "  inference API → http://127.0.0.1:8300   ($(curl -s http://127.0.0.1:8300/ready 2>/dev/null || echo 'not ready'))"
echo "  logs          → $RUN_DIR"
echo "  stop          → scripts/run_ui_demo.sh --stop"
open http://127.0.0.1:5199 2>/dev/null || true
