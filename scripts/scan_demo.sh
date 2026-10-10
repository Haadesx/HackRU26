#!/usr/bin/env bash
# MedCheck API smoke demo (Gate 3+). Usage: scripts/scan_demo.sh [base_url]
set -euo pipefail
BASE="${1:-http://127.0.0.1:8300}"
IMG="${2:-samples/label_metformin.png}"
echo "== GET $BASE/health"; curl -s "$BASE/health"; echo
echo "== GET $BASE/ready"; curl -s "$BASE/ready"; echo
echo "== POST $BASE/v1/scan (mode=mock, $IMG)"
curl -s -F "image=@${IMG}" -F "mode=mock" -F "client=test" "$BASE/v1/scan" | python3 -m json.tool | head -60
