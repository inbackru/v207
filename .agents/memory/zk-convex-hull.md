---
name: ZK complex boundary convex hull rendering
description: boundary_geometry stores individual building footprints (pipe-separated); JS must compute convex hull, not draw each polygon separately
---

**The rule:** The `/api/complex/<id>/osm-boundary` endpoint returns `boundary_geometry` as `|`-separated polygon strings (each polygon = `;`-separated `lat,lon` pairs). These are individual OSM building footprints, not a site boundary.

**Why:** Rendering each building outline separately (old approach: top 8 by area) shows a fragmented set of rectangles. CIAN shows a single clean convex hull encompassing the whole development site.

**How to apply:**
- In `templates/residential_complex_detail.html`, the map JS uses `_convexHull()` (Andrew's monotone chain) on ALL points from ALL polygons within 550m of the complex centre.
- The result is ONE `ymaps.Polygon` with `fillOpacity:0.08`, `strokeWidth:2.5`.
- The old `complexCircle` (150m radius) is removed once the hull is computed.
- `MAX_DIST_KM = 0.55` filters out stray points from neighbouring complexes.
- If a complex spans >550m, increase `MAX_DIST_KM` accordingly.
