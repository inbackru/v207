#!/usr/bin/env bash
# Guard against shadow-baging window.* map-filter functions.
#
# Canonical assignment locations (per-symbol allowlist):
#   window.updateMapWithFilters       → static/js/properties_mini_map.js  ONLY
#   window.applyMapAdvancedFilters    → templates/properties.html         ONLY
#   window.resetMapAdvancedFilters    → templates/properties.html         ONLY
#   window.fetchAndUpdateFilteredCount→ templates/properties.html         ONLY
#
# Any other file (or duplicate assignment in the canonical file) re-shadows
# the canonical impl and silently breaks the unified live-preview pipeline
# (see Task #7 round-5 fix). This check fails CI if that happens.
#
# Self-test: see scripts/check_no_shadow_map_filters_self_test.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Pattern: window.<name> = <something-that-isn't-equals>
# The trailing [^=] excludes `=== 'function'` typeof checks.
#
# symbol|canonical-relative-path
SPECS=(
  "updateMapWithFilters|static/js/properties_mini_map.js"
  "applyMapAdvancedFilters|templates/properties.html"
  "resetMapAdvancedFilters|templates/properties.html"
  "fetchAndUpdateFilteredCount|templates/properties.html"
  "syncMapFiltersToUi|templates/properties.html"
  "_paintAllMapChips|templates/properties.html"
)

FAIL=0

for spec in "${SPECS[@]}"; do
  name="${spec%%|*}"
  canonical="${spec##*|}"
  # Anchor to start-of-line (modulo whitespace) so comments/docstrings
  # that mention `window.X = ...` inline don't trip the guard.
  pat="^[[:space:]]*window\.${name}[[:space:]]*=[^=]"

  # 1) Any assignment outside the canonical file is a shadow violation.
  matches=$(grep -RInE "$pat" \
    --include='*.html' --include='*.js' \
    "$ROOT/templates" "$ROOT/static/js" 2>/dev/null || true)

  while IFS= read -r line; do
    [ -z "$line" ] && continue
    fpath="${line%%:*}"
    rel="${fpath#$ROOT/}"
    if [ "$rel" != "$canonical" ]; then
      echo "✗ SHADOW: window.${name} must only be assigned in ${canonical}" >&2
      echo "          found in: $line" >&2
      FAIL=1
    fi
  done <<<"$matches"

  # 2) Canonical file must contain exactly ONE assignment for this symbol.
  count=$(grep -cE "$pat" "$ROOT/$canonical" 2>/dev/null || true)
  if [ "$count" -ne 1 ]; then
    echo "✗ window.${name} must have exactly 1 assignment in ${canonical} (found: $count)" >&2
    FAIL=1
  fi
done

if [ $FAIL -eq 0 ]; then
  echo "✓ No shadow map-filter assignments"
fi

exit $FAIL
