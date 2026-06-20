---
name: Belgorod data mismatch (Ivanovo import)
description: Belgorod city_id=10 has 90 RCs whose CIAN URLs all point to Ivanovo — wrong city was scraped
---

## State (as of 2026-06-18)
- city_id=10 (Белгород): 90 active RCs, 1299 active apartments
- ALL 90 RCs have CIAN URLs ending in `-ivanovo-i.cian.ru` — data imported from Ivanovo by mistake
- 0 developers (developer_id NULL for all)
- 0 districts
- 41 RCs without address, 49 without coordinates (latitude/longitude)
- 29 buildings linked to Belgorod RCs
- Enrichment cache: `scripts/.enrich_cache_city10.json` — phase=4, phase_1c_done=True, apt_data=0 keys, dev_page_cache=0 keys

## Root cause
The fix_jk_bulk.py scraper ran for city_id=10 but matched Ivanovo JKs (same names exist in both cities). The `_CITY_CONFIG` lacked Belgorod coordinate bounds to constrain the search.

## What's needed to fix
1. Clear or replace the cache: `scripts/.enrich_cache_city10.json`
2. Add Belgorod coordinate bounds to `_CITY_CONFIG` in fix_jk_bulk: lat 50.5–50.7, lon 36.5–36.7
3. Re-run fix_jk_bulk.py with `--city 10 --force` to rescrape correct Belgorod CIAN pages
4. Run district import for Belgorod (3 okrugs: Vostochny, Severny, Tsentralny)
5. Run geocoding to fill missing coordinates

**Why:** Data integrity — showing Ivanovo JKs under Belgorod would mislead users and harm SEO.
