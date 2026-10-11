#!/usr/bin/env bash
# Capture dashboard screenshots at desktop + laptop + mobile widths for review.
#
#   scripts/ui_screenshots.sh <base_url> <out_prefix> [routes...]
#   scripts/ui_screenshots.sh http://127.0.0.1:5299 after
#
# Writes <out_prefix>-<route>-<size>.png into docs/screenshots/ui/.
# Uses isolated headless Chrome profiles so it never touches the user's browser session.
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${1:?usage: ui_screenshots.sh <base_url> <out_prefix> [routes...]}"
PREFIX="${2:?usage: ui_screenshots.sh <base_url> <out_prefix> [routes...]}"
shift 2
ROUTES=("${@:-/}")
[ ${#ROUTES[@]} -eq 0 ] && ROUTES=("/")

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT="docs/screenshots/ui"
mkdir -p "$OUT"

capture() { # route size name
  local route="$1" size="$2" name="$3"
  local profile="/tmp/chrome-medcheck-$name-$RANDOM"
  timeout 60 "$CHROME" --headless=new --disable-gpu --no-first-run \
    --user-data-dir="$profile" --hide-scrollbars --window-size="$size" \
    --virtual-time-budget=6000 --screenshot="$OUT/$PREFIX-$name.png" "$BASE$route" \
    >/dev/null 2>&1 || true
  rm -rf "$profile"
  printf "  %-34s %s\n" "$PREFIX-$name.png" "$(du -h "$OUT/$PREFIX-$name.png" 2>/dev/null | cut -f1 || echo MISSING)"
}

echo "capturing $BASE → $OUT/$PREFIX-*.png"
for route in "${ROUTES[@]}"; do
  slug=$(echo "$route" | sed 's|^/||; s|/$||; s|/|-|g'); [ -z "$slug" ] && slug="home"
  capture "$route" "1920,1080" "$slug-desktop"
  capture "$route" "1440,900"  "$slug-laptop"
  capture "$route" "390,844"   "$slug-mobile"
done
echo "done."
