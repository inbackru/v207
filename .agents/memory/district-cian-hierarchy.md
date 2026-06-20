---
name: District CIAN hierarchy
description: CIAN-style districts page architecture — type tabs, grouped sections, FK-based filtering
---

## How it works

`routes/districts.py → _render_districts()` passes three lists to the template:
- `okrugs` — `district_type = 'okrug'`
- `microrayons` — `district_type = 'microrayon'`
- `settlements` — `district_type = 'settlement'`

`templates/districts.html` shows:
- Sticky tab bar: "Все районы" / "Округа" / "Микрорайоны" / "Посёлки" with counts
- Grouped sections with color-coded left border (blue/green/amber)
- Card URLs → `/krasnodar/novostrojki?districts=<slug>` (not `/novostrojki-v-<slug>`)

## FK Filter chain

1. User clicks district suggestion or tab filter
2. `properties_city` route receives `districts=[slug]`
3. Resolves slug → `district_id` via `District.query.filter_by(slug=slug)`
4. Sets `repo_filters['district_id_in'] = [id]`
5. `PropertyRepository.get_all_active` + `count_active` apply `Property.district_id.in_(ids)`

**Why:** ILIKE district name matching was slow and missed properties assigned by FK. FK-based `district_id_in` is exact and uses index.

## Polygon fix pattern

- Geometry stored as `lat,lng;lat,lng;...` text (NOT PostGIS)
- PIP via `enrich_t4_pip.py` (standalone psycopg2, orders districts smallest polygon first)
- To fix a polygon: update `districts.geometry` with new point string, then re-run `enrich_t4_pip.py`
- Немецкая деревня (id=40) polygon extended 2026-06-12 to include Западный обход area (lat≥45.1120)
