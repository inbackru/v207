---
name: Okrug PIP architecture
description: How okrug-level property counts and filtering work via okrug_district_id on residential_complexes
---

## Rule
`residential_complexes.okrug_district_id` is populated by PIP (point-in-polygon) against okrug-type district polygons. Use this column — not `properties.district_id` — for aggregated okrug-level counts and filtering.

**Why:** Properties are assigned to their most specific district (microrayon), not to the parent okrug. A complex like "Гарантия на Обрывной" belongs to a microrayon, but geographically sits in Центральный. Without `okrug_district_id`, filtering by okrug only returned 1166 properties instead of the correct 2339.

**How to apply:**
1. `models.py` — `ResidentialComplex` has `district_id` (microrayon-level FK) AND `okrug_district_id` (okrug-level FK). Both point to `districts.id`, so SQLAlchemy relationships MUST specify `foreign_keys=[field]` or ORM init will crash with "multiple FK paths" error.
2. `repositories/property_repository.py` — `_build_district_geo_condition()` ORs `okrug_district_id` for okrug-type districts. `district_id_in` filter also ORs `okrug_district_id` for any IDs that belong to okrug-type districts.
3. `routes/properties.py` — `city_okrugs` is now computed by joining `properties → residential_complexes → okrug_district_id`, giving accurate aggregated counts.
4. `templates/properties.html` — Okrug chips section replaced from hardcoded dict to `city_okrugs` server variable (dynamic, uses `okrug.props_count`).

## Re-running PIP
If new RCs are added, run a Python script that:
- Loads all okrug polygons from `districts WHERE district_type='okrug' AND id != 6`
- For each active RC with lat/lng, ray-cast PIP against city's okrug polygons
- UPDATE `residential_complexes SET okrug_district_id = matched_id`

Krasnodar okrugs: Прикубанский(id=10), Карасунский(id=9), Западный(id=28), Центральный(id=7). Exclude id=6 (Краснодарский край, region-wide polygon).
