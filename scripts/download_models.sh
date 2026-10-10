#!/usr/bin/env bash
# Download ONNX model weights used by the inference stack (kept out of git).
# Currently: YOLO11n (COCO) for real-photo bottle detection (~11 MB).
#
# Usage: scripts/download_models.sh [--force]
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models

URL="https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.onnx"
OUT="models/yolo11n.onnx"

if [ -f "$OUT" ] && [ "${1:-}" != "--force" ]; then
  echo "present: $OUT ($(du -h "$OUT" | cut -f1))"
  echo "sha256:  $(shasum -a 256 "$OUT" | cut -d' ' -f1)"
  exit 0
fi

echo "downloading $URL"
curl -sL --max-time 300 -o "$OUT" "$URL"
if [ ! -f "$OUT" ] || [ "$(wc -c < "$OUT")" -lt 1000000 ]; then
  rm -f "$OUT"
  echo "download failed (asset missing or network blocked)" >&2
  exit 1
fi
echo "downloaded: $OUT ($(du -h "$OUT" | cut -f1))"
echo "sha256:     $(shasum -a 256 "$OUT" | cut -d' ' -f1)"
echo
echo "The local console auto-enables it; for the API alone set:"
echo "  MEDCHECK_YOLO_MODEL=models/yolo11n.onnx"
