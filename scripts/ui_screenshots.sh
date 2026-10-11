#!/usr/bin/env bash
# Capture dashboard screenshots at desktop + laptop + mobile widths for review.
#
#   scripts/ui_screenshots.sh <base_url> <out_prefix> [routes...]
#   scripts/ui_screenshots.sh http://127.0.0.1:5299 after "/" "/scan" "/settings"
#
# Uses Brave via playwright-core (no bundled browsers, no Chrome). Writes PNGs to
# docs/screenshots/ui/ and prints per-page verification: console errors, horizontal
# scroll, skip-link presence, h1, and a text digest.
set -euo pipefail
cd "$(dirname "$0")/.."

TOOL_DIR="tools/ui_capture"
if [ ! -d "$TOOL_DIR/node_modules/playwright-core" ]; then
  echo "installing capture deps (playwright-core, no browser download)…"
  ( cd "$TOOL_DIR" && npm install --silent )
fi
exec node "$TOOL_DIR/capture.mjs" "$@"
