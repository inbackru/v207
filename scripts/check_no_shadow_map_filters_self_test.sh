#!/usr/bin/env bash
# Self-test for scripts/check_no_shadow_map_filters.sh.
# Injects a deliberately-shadowing line into a temp copy of the tree and
# verifies the guard fails. Then verifies the real tree passes.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUARD="$ROOT/scripts/check_no_shadow_map_filters.sh"

echo "[1/2] Real tree should PASS:"
if bash "$GUARD" >/dev/null 2>&1; then
  echo "  ✓ guard passes on clean tree"
else
  echo "  ✗ guard FAILED on clean tree — unexpected" >&2
  exit 1
fi

echo "[2/2] Injected shadow should FAIL:"
TMPL="$ROOT/templates/properties.html"
BAK="$(mktemp)"
cp "$TMPL" "$BAK"
# Inject a shadow assignment of window.updateMapWithFilters into the template
# (canonical lives in properties_mini_map.js — this MUST trip the guard).
printf '\n<script>\nwindow.updateMapWithFilters = function(){};\n</script>\n' >> "$TMPL"

if bash "$GUARD" >/dev/null 2>&1; then
  echo "  ✗ guard PASSED with injected shadow — guard is broken" >&2
  cp "$BAK" "$TMPL"; rm -f "$BAK"
  exit 1
else
  echo "  ✓ guard correctly fails on injected shadow"
fi

cp "$BAK" "$TMPL"
rm -f "$BAK"
echo "Self-test OK"
