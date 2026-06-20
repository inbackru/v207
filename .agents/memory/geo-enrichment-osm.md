---
name: OSM Geo Enrichment
description: Results and approach for OSM-based district/street enrichment for all 8 InBack cities
---

## OSM Relation IDs (verified via Nominatim)
- Краснодар=7373058, Сочи=1430508, Майкоп=3441283, Анапа=1477115
- Новороссийск=1477110, Геленджик=2263494, Армавир=3476238, Туапсе=3532696
- area_id formula for Overpass: `3600000000 + relation_id`

## Script: `scripts/geo_enrich_osm.py`
Commands: `districts [city_slug]`, `streets [city_slug]`, `osm_ids`, `all`
Rate limit: 1.2s sleep between requests; 429 errors → wait 15s and retry separately.

## Enrichment Results (June 2026)
- **260 total districts** across all 8 cities (83 Krasnodor, 133 Sochi, 20 Novorossiysk, 18 Anapa, 10 Gelendzhik, 4 Maykop, 4 Armavir, 3 Tuapse)
- **6,307 total streets** with OSM IDs (4,707 with osm_id)
- **61,558 properties** linked to districts (97% Krasnodor, 100% Sochi, 100% Maykop)
- **6,229 streets** linked to nearest district

## District Geometry
- Format stored in `districts.geometry`: `"lat,lon;lat,lon;..."` (rectangular bbox, 4 corners)
- Only 53 Krasnodor districts have bbox geometry (from pre-existing data)
- Other cities' districts have only lat/lon centroid — no polygon
- **Property→district linking**: bbox containment (SQL) for Krasnodor, nearest centroid for Sochi/Maykop

## API Added
- `GET /api/district/boundaries/<district_slug>` → returns `{success, boundaries: GeoJSON Polygon}`
- Converts stored `lat,lon;...` geometry to GeoJSON `[lon,lat]` pairs (note coordinate swap!)
- Returns 404 if no geometry; districts without geometry fall back to Yandex geocoding in JS

## District Cleanup
- Removed 72 ЖК/residential complex names from districts table (they were OSM misclassifications)
- Filter: `name ILIKE 'жк %' OR 'жилой комплекс%' OR 'агрофирма%' OR '%отделение совхоза%'`

## Known Gaps
- Anapa, Gelendzhik, Novorossiysk, Armavir, Tuapse have 0 active properties (no DB data yet)
- Krasnodor legacy 1,600 streets have no osm_id (new 1,661 OSM streets were added separately)
- Maykop is city_id=8 (NOT city_id=3 — cities are not in alphabetical ID order)

**Why:** OSM Overpass is the only free, no-API-key source for district/street geo data in Russia.
**How to apply:** Run script per city when new cities are added; use `area_id = 3600000000 + rel_id`.
