#!/usr/bin/env bash
# Reproducible combined MedCheck environment (all four services + tests).
# Creates .venv-full at the repo root. Verified 2026-10-10 on macOS arm64.
set -euo pipefail
cd "$(dirname "$0")/.."
uv venv .venv-full --python 3.11
uv pip install --python .venv-full/bin/python \
  "pydantic>=2.6,<3" "jsonschema>=4.21" \
  "fastapi>=0.110" "uvicorn[standard]>=0.29" "python-multipart>=0.0.9" \
  "httpx>=0.27" "pytest>=8" \
  "numpy==2.4.6" "opencv-python==5.0.0.93" "pillow==12.3.0" \
  "rapidocr-onnxruntime==1.4.4" "onnxruntime==1.31.0" \
  "pyclipper==1.4.0" "shapely==2.2.0" "six==1.17.0" "pyyaml==6.0.3" \
  "pytesseract>=0.3.10"   # VLM eval baseline; needs the `tesseract` binary (brew install tesseract)
echo
echo "Run the full suite:"
echo "  .venv-full/bin/python -m pytest services tests/integration -q"
echo "Run the API (real mode):"
echo "  MEDCHECK_API_MODE=real .venv-full/bin/uvicorn services.api.main:app --port 8300"
