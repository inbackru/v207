---
name: District ZhK SEO routes
description: /<city_slug>/zhilye-kompleksy/<district_slug> route — how it works, Jinja2 pitfalls, sitemap
---

## Route
`routes/complexes.py` — `/<city_slug>/zhilye-kompleksy/<district_slug>` added after the city-only route.
Passes: `current_district`, `district_gen` (genitive), `district_prep` (prepositional) — computed in Python via `_district_cases()` helper (top of file, lines ~71-114).

## Jinja2 rule (critical)
`{% block %}` directives CANNOT be inside `{% if %}`. Always put `{% if %}` INSIDE the block:
```
{% block title %}{% if current_district %}...{% else %}...{% endif %}{% endblock %}
```
NOT:
```
{% if current_district %}{% block title %}...{% endblock %}{% else %}{% block title %}...{% endblock %}{% endif %}
```

## Mini-map
- `window.currentDistrictId` set in `extra_head` block from route context
- JS builds URL: `/api/mini-map/complexes?city_id=X&district_id=Y` when district present
- API returns `{ success, coordinates: [{id, name, lat, lng}], count }` — key is `coordinates` not `complexes`

## Sitemap
`sitemap-seo-ext.xml` endpoint queries districts with ≥1 active RC and generates entries at priority 0.82, changefreq weekly.

**Why:** These district pages get unique title/description/canonical/FAQ per district for SEO — Google treats them as separate indexed pages.
