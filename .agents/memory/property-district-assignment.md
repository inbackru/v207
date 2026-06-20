---
name: Property district assignment
description: How properties get assigned to districts; why district geometry bboxes don't work for spatial filtering
---

# Property → District Assignment

## The rule
All 50,024 active Krasnodar properties have `latitude`/`longitude` set but `district_id=NULL`. District geometry stored in DB is NOT aligned with actual property coordinates (bboxes are wrong/placeholder data). Use nearest-centroid assignment instead.

**Why:** District geometry was imported with wrong coordinates (e.g. Karasunsky has a 50m² polygon instead of a several-km² polygon). Only the district `latitude`/`longitude` centroids are reliable.

**How to apply:**
- On every fresh DB restore, run the nearest-centroid bulk assignment (Python script or via `/admin/geo/assign-districts` POST endpoint)
- After assignment: district_id FK query works — Kalinino gets ~17K properties, Prikubansky ~6.7K, etc.
- Admin endpoints added: `POST /admin/geo/assign-districts` and `POST /admin/geo/enrich-yandex`
- `utils/geo.py` contains: `parse_geometry`, `geometry_bbox`, `point_in_geometry`, `yandex_geocode`, `enrich_streets_with_yandex`, `enrich_districts_with_yandex`
- Sitemap SEO import fix: `from routes.seo_city import _SEO_NOVOSTROJKI_SLUGS, _DISTRICT_MAP` (not from `app`)

## Street geometry format
Street geometry uses `lat,lng;lat,lng;...` semicolon separator. Some rows have trailing `#`. Use `parse_geometry()` from `utils/geo.py` which handles both.
77 streets had missing lat/lng — computed from geometry centroid and updated in DB.
