---
name: Properties filter chips JS pitfalls
description: Why active filter chips on /krasnodar/novostrojki silently broke in live mode — global collision, hardcoded cache-buster, URL+DOM union rules.
---

# Active filter chips (синие бейджи) on templates/properties.html

The chips are rendered by `window.updateActiveFiltersDisplay` / `window.removeFilter` in
`static/js/property-filters.js`. Three non-obvious traps cost real time here.

## 1. Global-function collision via script load order
`properties_mini_map.js` had a top-level `function updateActiveFiltersDisplay()` that, because
it loads AFTER `property-filters.js`, silently overwrote the real `window.updateActiveFiltersDisplay`.
The map version only touches `#mapActiveFilters` and returns early on the main page → chips never
updated in live mode (worked on reload only because Jinja renders them server-side).
**Fix/rule:** the map helper is now `_updateMapActiveFiltersDisplay()`. Never declare a bare
top-level `function updateActiveFiltersDisplay` (or any name that matches a global owned by another
file) — later-loaded files win and the collision is invisible.

## 2. Hardcoded cache-buster = stale JS in the browser
Some `<script src>` tags in `templates/properties.html` carry a **hardcoded** version query string
(it was `?v=20260616b`). Editing the referenced JS file has ZERO effect in the browser until that
string changes — you debug the OLD file forever.
**Why:** the literal version pins the cached asset.
**How to apply:** when actively debugging a JS file referenced this way, switch its tag to a random
buster `?v={{ range(1000, 99999) | random }}` (the mini-map tag now uses this). For production a
deterministic mtime/hash buster is preferable, but never leave a stale literal during JS work.

## 3. Chips read URL+DOM union; removeFilter must clear all three sources
- Display reads filters as the **union of URL params and checked DOM inputs**. Live mode needs DOM
  (URL not yet updated at click time); reload needs URL. Drop either source and one mode breaks.
- `removeFilter` must delete from the **URL**, uncheck/clear the **DOM**, AND `delete
  window.activeFilters[base]` — `developer` and `residential_complex` are sourced from
  `window.activeFilters` inside `buildLiveParams`, so skipping that makes the filter re-appear on the
  next `triggerLiveSearch`.
- The × button works even with the URL-fallback in `buildLiveParams` because `removeFilter` deletes
  from the URL *before* calling `triggerLiveSearch` (which snapshots the URL after deletion). A
  **manual** checkbox uncheck (no ×) can still re-add via that fallback — known lower-priority edge
  case, left as-is to avoid dropping URL filters that have no matching checkbox.
- Value-aware labels: `building_released` must map `true→Дом сдан`, `false→Строится` and pass the
  value to the chip (so × removes the right one); object_classes/renovation/floor_options use label
  maps with raw value as fallback.
- Chip labels are injected via innerHTML — HTML-escape every label and the onclick attr (`escH`),
  since search/developer/residential_complex/district values come from URL/DOM (DOM XSS otherwise).
