#!/usr/bin/env bash
# Reproducible release manifest: commit, artifact hashes, timestamps.
#
#   scripts/release_manifest.sh                 # writes docs/RELEASE_MANIFEST.md
#   scripts/release_manifest.sh --check         # prints the manifest without writing
#
# The manifest is a factual record (SHA-256 of tracked artifacts + git state). It is not a
# license, and a signed tag does not by itself establish legal ownership.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="docs/RELEASE_MANIFEST.md"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

COMMIT=$(git rev-parse HEAD)
SHORT=$(git rev-parse --short HEAD)
BRANCH=$(git branch --show-current)
UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "none")
DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')

ARTIFACTS=(
  contracts/v1/scan_request.schema.json
  contracts/v1/scan_response.schema.json
  contracts/examples/ok_response.json
  contracts/examples/needs_rescan_response.json
  contracts/examples/error_response.json
  contracts/examples/multi_frame_response.json
  contracts/README.md
  services/common/contract.py
  services/api/HANDOFF.md
  services/vlm/EVAL.md
  services/ocr/DECISION.md
  backend/app/hub/labels.py
  backend/app/hub/routes.py
  backend/migrations/versions/0004_hub_scan_form.py
  frontend/docs/api-contract.md
  frontend/docs/inference-contract.md
  docs/PROJECT_STATUS.md
  docs/ORCHESTRATOR_HANDOFF.md
  docs/PROJECT_PROVENANCE.md
  docs/OWNERSHIP_PROPOSAL.md
  scripts/download_models.sh
  scripts/run_ui_demo.sh
)

{
  echo "# MedCheck Release Manifest"
  echo
  echo "Generated: \`$DATE\` by \`scripts/release_manifest.sh\` (regenerate after every release)."
  echo
  echo "| Field | Value |"
  echo "|---|---|"
  echo "| Integration branch | \`$BRANCH\` |"
  echo "| Commit | \`$COMMIT\` (\`$SHORT\`) |"
  echo "| Upstream | \`$UPSTREAM\` |"
  echo "| Working tree | \`$DIRTY\` uncommitted change(s) |"
  echo "| Python (inference env) | 3.11 (uv-managed \`.venv-full\`) |"
  echo "| Python (backend) | 3.11+ (see backend/requirements.txt) |"
  echo "| Node | see frontend/package-lock.json |"
  echo
  echo "## Artifact hashes (SHA-256)"
  echo
  echo "| Artifact | SHA-256 |"
  echo "|---|---|"
  for f in "${ARTIFACTS[@]}"; do
    if [ -f "$f" ]; then
      echo "| \`$f\` | \`$(shasum -a 256 "$f" | cut -d' ' -f1)\` |"
    else
      echo "| \`$f\` | (absent) |"
    fi
  done
  echo
  echo "## Model weights (not in git; downloaded by scripts/download_models.sh)"
  echo
  if [ -f models/yolo11n.onnx ]; then
    echo "- \`models/yolo11n.onnx\` — SHA-256 \`$(shasum -a 256 models/yolo11n.onnx | cut -d' ' -f1)\`"
    echo "  (Ultralytics YOLO11n ONNX; **AGPL-3.0** unless an Ultralytics enterprise license is held)"
  else
    echo "- \`models/yolo11n.onnx\` — not present in this checkout"
  fi
  echo "- Qwen3-VL-8B-Instruct-FP8 — served by the shared rig (\`echo-vllm\`); not a project artifact."
  echo
  echo "## Reproduce"
  echo
  echo '```bash'
  echo "git checkout $SHORT && git status --porcelain   # expect empty"
  echo "scripts/setup_full_env.sh"
  echo ".venv-full/bin/python -m pytest services tests/integration -q   # 523 passed"
  echo "cd backend && PYTHONPATH=. <venv>/python -m pytest -q           # 81 passed"
  echo "cd frontend && npm ci && npm run build"
  echo '```'
  echo
  echo "> A commit SHA and hashes above are factual build records. They do not by themselves"
  echo "> grant or evidence legal ownership; see docs/PROJECT_PROVENANCE.md and"
  echo "> docs/OWNERSHIP_PROPOSAL.md."
} > /tmp/release_manifest.md

if [ "$CHECK" = 1 ]; then
  cat /tmp/release_manifest.md
else
  mv /tmp/release_manifest.md "$OUT"
  echo "wrote $OUT for $SHORT ($DIRTY uncommitted change(s))"
fi
