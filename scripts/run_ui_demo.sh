#!/usr/bin/env bash
# Run the full MedCheck demo stack: backend (TimescaleDB) + inference + hub adapter + web UI.
#
#   scripts/run_ui_demo.sh          # start everything (backend /hub is the primary hub)
#   scripts/run_ui_demo.sh --adapter  # use the orchestrator's file-backed adapter instead
#   scripts/run_ui_demo.sh --stop   # stop UI + hubs + backend gunicorn (DB stays up)
#
# Stack:  UI :5199  →  backend /hub :8000/hub  →  inference :8300
#         (`--adapter` instead routes the UI through the file-backed adapter :8500)
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_DIR="${TMPDIR:-/tmp}/medcheck-ui-demo"
mkdir -p "$RUN_DIR"
VENV_BACKEND=".worktrees/verify-urvi/backend/.venv"

stop_all() {
  for f in "$RUN_DIR/ui.pid" "$RUN_DIR/hub.pid" "$RUN_DIR/api.pid" "$RUN_DIR/backend.pid"; do
    [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true
  done
  pkill -f "tools.hub_adapter.app" 2>/dev/null || true
  pkill -f "vite.*--port 5199" 2>/dev/null || true
  pkill -f "gunicorn.*wsgi:app" 2>/dev/null || true
  rm -f "$RUN_DIR"/*.pid
  echo "stopped backend + hub adapter + UI (TimescaleDB container left running)"
}

[ "${1:-}" = "--stop" ] && { stop_all; exit 0; }
USE_ADAPTER=0
[ "${1:-}" = "--adapter" ] && USE_ADAPTER=1
HUB_URL="http://127.0.0.1:8000/hub"
[ "$USE_ADAPTER" = 1 ] && HUB_URL="http://127.0.0.1:8500"

[ -x .venv-full/bin/python ] || { echo "run scripts/setup_full_env.sh first"; exit 1; }
[ -d frontend/node_modules ] || { echo "frontend deps missing — run: (cd frontend && npm install)"; exit 1; }

# ── backend (:8000) — TimescaleDB in Docker (verification venv holds its deps)
if ! curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
  echo "starting backend on :8000 …"
  ( cd backend && docker compose up -d db >/dev/null 2>&1 )
  for _ in $(seq 1 40); do
    [ "$(docker inspect --format '{{.State.Health.Status}}' medcheck-backend-db 2>/dev/null)" = "healthy" ] && break
    sleep 1
  done
  if [ -x "$VENV_BACKEND/bin/python" ]; then
    ( cd backend && FLASK_APP=wsgi:app PYTHONPATH=. "../../$VENV_BACKEND/bin/python" -m flask db upgrade >/dev/null 2>&1 )
    if [ "$(docker exec medcheck-backend-db psql -U medcheck -d medcheck -tAc 'select count(*) from users' 2>/dev/null || echo 0)" = "0" ]; then
      ( cd backend && SEED_PASSWORD=medcheck-demo-password PYTHONPATH=. "../../$VENV_BACKEND/bin/python" scripts/seed.py >/dev/null 2>&1 )
      echo "seeded demo patient (demo.patient@example.com)"
    fi
    ( cd backend && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES HUB_ENABLED=true HUB_PATIENT_EMAIL=demo.patient@example.com HUB_INFERENCE_URL=http://127.0.0.1:8300 CORS_ORIGINS='*' PYTHONPATH=. nohup "../../$VENV_BACKEND/bin/gunicorn" -b 127.0.0.1:8000 --workers 1 --threads 4 wsgi:app >"$RUN_DIR/backend.log" 2>&1 & echo $! > "$RUN_DIR/backend.pid" )
    for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1 && break; sleep 0.5; done
  else
    echo "backend venv missing ($VENV_BACKEND) — install backend/requirements.txt first"
  fi
fi

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

# ── fallback hub adapter (:8500) — only with --adapter (no DB required)
if [ "$USE_ADAPTER" = 1 ] && ! curl -sf http://127.0.0.1:8500/health >/dev/null 2>&1; then
  echo "starting fallback hub adapter on :8500 (backend mode) …"
  HUB_MODE=backend nohup .venv-full/bin/uvicorn tools.hub_adapter.app:app --host 127.0.0.1 --port 8500 >"$RUN_DIR/hub.log" 2>&1 &
  echo $! > "$RUN_DIR/hub.pid"
  for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8500/health >/dev/null 2>&1 && break; sleep 0.5; done
fi

# ── web UI (:5199)
if ! curl -sf http://127.0.0.1:5199/ >/dev/null 2>&1; then
  echo "starting web UI on :5199 …"
  ( cd frontend && VITE_API_URL="$HUB_URL" nohup npm run dev -- --host 127.0.0.1 --port 5199 --strictPort >"$RUN_DIR/ui.log" 2>&1 & echo $! > "$RUN_DIR/ui.pid" )
  for _ in $(seq 1 60); do curl -sf http://127.0.0.1:5199/ >/dev/null 2>&1 && break; sleep 0.5; done
fi

echo
echo "MedCheck demo stack"
echo "  web UI        → http://127.0.0.1:5199   (camera scan, verify, add)"
echo "  hub           → $HUB_URL   ($([ "$USE_ADAPTER" = 1 ] && echo 'file-backed adapter' || echo "Urvi's backend /hub"))"
echo "  backend API   → http://127.0.0.1:8000/api/v1"
echo "  inference API → http://127.0.0.1:8300   ($(curl -s http://127.0.0.1:8300/ready 2>/dev/null || echo 'not ready'))"
echo "  logs          → $RUN_DIR"
echo "  stop          → scripts/run_ui_demo.sh --stop"
open http://127.0.0.1:5199 2>/dev/null || true
