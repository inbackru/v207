---
name: District SEO multi-city setup
description: How districts are assigned for non-Krasnodar cities, schema fixes, and the CIAN-style comparison page.
---

## Districts table schema fix
The `districts` model has `osm_id = db.Column(db.BigInteger)` but the restored backup DB was missing this column. Must add it before first use:
```sql
ALTER TABLE districts ADD COLUMN IF NOT EXISTS osm_id BIGINT;
```

## Coordinate bbox assignment (Sochi & Maykop)
Properties were assigned to districts using coordinate CASE logic in SQL UPDATE. See `routes/districts.py` `_render_districts()` for stats query pattern.

**Sochi (city_id=2, 7 districts):**
- Адлерский (id≈63): lat < 43.525
- Хостинский (id≈62): lat 43.50–43.59, lng 39.76–39.91
- Дагомыс (id≈66): lat 43.64–43.72, lng 39.59–39.66
- Лазаревский (id≈64): lat > 43.65, lng < 39.70
- Красная Поляна (id≈65): lng > 40.15
- Новые Сочи (id≈67): lat 43.62–43.67, lng 39.73–39.79
- Центральный (id≈61): remainder

**Maykop (city_id=8, 4 districts):**
- Северный: lat < 44.59, lng > 40.10
- Западный: lng < 40.07
- Восточный: lat > 44.62, lng > 40.08
- Центральный: remainder
- Note: exclude lat < 44.0 (those are Krasnodar misassigned properties)

## SEO routes
- `/<city_slug>/rayony` → `districts_city` in `routes/districts.py`
- `/<city_slug>/novostrojki-v-<district_slug>` → `district_seo_dynamic` in `routes/seo_city.py`
- Prefix slug matching (e.g. `festivaln` → `festivalny`) with 301 redirect is implemented in `district_seo_dynamic`
- Cross-city guard: if district belongs to different city, 301 redirect to correct city

## CIAN-style districts.html
Rebuilt `templates/districts.html` with:
- Real price stats (avg ₽/m², count, min price) from DB per district
- Price bar colored green/yellow/red by percentile
- Grid + Table views with JS toggle
- Sort by count / price asc / price desc
- Search filter

**Why:** Previous template had hardcoded placeholder stats ("5 schools", "10 shops"). Now uses real data from `_render_districts()` which runs an aggregation query.
