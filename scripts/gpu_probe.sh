#!/usr/bin/env bash
# Gate 7 resource probe: GPU state + existing vLLM health on hermes-linux (read-only).
set -euo pipefail
echo "== local time =="; date -u +"%Y-%m-%dT%H:%M:%SZ"
echo "== rig GPU =="
ssh -o BatchMode=yes -o ConnectTimeout=6 hermes-linux \
  'nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader; echo "--- compute apps ---"; nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader | head'
echo "== existing vLLM model list (auth from ~/.medcheck/vllm.env) =="
set -a; . "$HOME/.medcheck/vllm.env"; set +a
curl -s -m 8 -H "Authorization: Bearer $MEDCHECK_VLM_API_KEY" \
  "$MEDCHECK_VLM_BASE_URL/models" | python3 -c "import json,sys; d=json.load(sys.stdin); print([m['id'] for m in d.get('data',[])])"
echo "== api health (if running) =="
curl -s -m 3 http://127.0.0.1:8300/health || echo "(api not running)"
echo
