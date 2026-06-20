---
name: District SEO phrase generation
description: How "в ..." phrases are generated for district SEO titles/h1, covering adjective names vs noun names with district_type.
---

## Rule
In `routes/properties.py` the `_format_dist_phrase(name, district_type)` helper returns the full "в ..." phrase:
- Adjective name (ends in -ский/-цкий/-ный/-ый/-ой/-ий): returns "в {prepositional(name)}" e.g. "в Центральном", "в Прикубанском"
- Noun name: returns "{type_prep} {name}" e.g. "в микрорайоне Горхутор", "в округе X"

`_DIST_TYPE_PREP` maps: microrayon→"в микрорайоне", okrug→"в округе", district→"в районе", settlement→"в посёлке"

Variable `_dist_phrase` holds the full phrase. Use it (not `_dist` or `_dist_prep`) in seo_h1/seo_title/seo_description.

**Why:** Russian grammar requires prepositional case for adjective-based district names but "в {type} {name}" (nominative) for noun-based names. A single `_dist_prep` variable was insufficient.

## JS chip district name resolution
- JS chips (`property-filters.js` line 349) resolve district slug to Russian name via:
  1. `data-district-name` attribute on input element (okrugs filter panel)
  2. `window.districtNamesMap[slug]` — populated in `properties.html` from `seo_districts` + `active_districts_info`
  3. Fallback: slug with hyphens replaced by spaces

- `window.districtNamesMap` is emitted in properties.html near `window.seoPageFilters` from all `seo_districts` entries + `active_districts_info`.
- `active_districts_info` is a Python dict `{slug: {name, slug, type}}` built in `routes/properties.py` after `seo_districts` and passed to template.

**Why:** microrayon districts are NOT in the `data-district-name` input elements (only okrugs are), so the old code fell back to the raw slug. The `districtNamesMap` fixes this universally for all district types.

## Coordinate cleanup
- Bad coordinates (outside Krasnodar bbox: lng<36 or lng>41.5, lat<43 or lat>46.5) must be NULLed in BOTH `properties` AND `residential_complexes` tables.
- The fullscreen map uses `residential_complexes.latitude/longitude` for cluster centers — leaving RC coords intact while NULLing property coords still causes map zoom-out.
- Used SQL: `UPDATE residential_complexes SET latitude=NULL, longitude=NULL WHERE city_id=1 AND latitude IS NOT NULL AND (longitude>41.5 OR longitude<36.0 OR latitude>46.5 OR latitude<43.0)`
