---
name: Belgorod enrichment config
description: Correct CIAN region ID for Belgorod, what was wrong, and recovery steps
---

## The rule
`cian_region_id` for Белгородская область in `scripts/city_config.json` MUST be **4590**.

**Why:** 4570 was set instead — that's Ивановская область. enrich_complexes.py uses `cian_region_id` directly as the CIAN API `region` filter: `'region': {'type': 'terms', 'value': [CIAN_REGION_ID]}`. So all 90 RCs and 1299 properties got Ivanovo coordinates (lat≈57, lon≈41) instead of Belgorod (lat≈50.59, lon≈36.59).

## Current state (after fix, June 2026)
- `scripts/city_config.json` entry for `"10"`: `cian_region_id=4590` ✅
- Belgorod bounds: `lat_min=50.47, lat_max=50.72, lon_min=36.35, lon_max=36.85` ✅
- City record (`cities.id=10`): `is_active=True, zoom_level=12, is_default=False` ✅
- All 90 Ivanovo-data RCs and 1299 properties deactivated (`is_active=False`) — they remain in DB but are hidden
- Belgorod now has 0 active properties → will NOT appear in city switcher dropdown until re-enriched

## How to apply
- After any re-enrichment: verify RC coordinates land in Belgorod bbox (lat 50.47–50.72, lon 36.35–36.85)
- The city switcher (`/api/cities`) hides cities with `property_count=0 AND NOT is_default` — Belgorod needs at least 1 active property to appear in nav

## Kursk bounds fix
Also fixed in same pass: `city_id=9` (Курск) had `lat_min=40, lat_max=80, lon_min=19, lon_max=190` (entire country). Corrected to `lat_min=51.55, lat_max=51.90, lon_min=35.90, lon_max=36.45`.

## City switcher architecture
- `loadCitiesDropdown()` in `templates/header.html` calls `/api/cities` (route in `routes/searches.py`)
- `/api/cities` hides cities with 0 active properties unless `is_default=True`
- `changeCity(slug, name)` POSTs to `/api/change-city`, stores city in session, then redirects by replacing first URL path segment with new city slug
- CSRF token is read from `<meta name="csrf-token">` in `templates/base.html` line 11
