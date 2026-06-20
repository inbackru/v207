---
name: Relevance sort two-phase implementation
description: How the CIAN/Domclick-style diverse relevance sort works in PropertyRepository, and critical bugs to avoid
---

## The rule
`sort_by='relevance'` in `PropertyRepository.get_all_active()` uses a two-phase approach with `DISTINCT ON` for Phase 2. Both `routes/properties.py` and `routes/public_api.py` default to `sort=''` → parsed as `sort_by='relevance'`.

## Phase 1 — which complexes, in what order
- Wrap the existing filtered query (with all JOINs and filters) as a subquery via `query.with_entities(Property.id, Property.complex_id).subquery()`
- Count properties per complex in an outer query (no joinedloads, no explicit JOINs in outer query)
- Order by count DESC, LIMIT 100–500 → `ordered_cids` list

**Why subquery approach:** `query.with_entities(...).group_by().order_by()` directly on a query that has explicit `.join()` calls caused only 2 complexes to be returned. Wrapping as subquery first isolates the grouping from the ORM JOINs.

**Why not `query.whereclause`:** If search filters reference joined table columns (ResidentialComplex.name ILIKE), extracting `whereclause` and applying to a plain query fails with "missing FROM-clause entry". Subquery approach is safe.

## Phase 2 — best property per complex per depth
- `max_depth_needed = (offset + limit) // max(1, len(ordered_cids)) + 2`
- Loop `for _depth in range(max_depth_needed)`: use `DISTINCT ON (complex_id)` via `.distinct(Property.complex_id)` to get exactly one best property per complex per pass; exclude previously-seen IDs

**Critical bug avoided:** `ORDER BY complex_id ASC LIMIT (max_depth * N)` monopolizes all rows from complexes with the smallest IDs. E.g. complex_id=32 with 100 props fills the entire LIMIT before higher-ID complexes get any rows. `DISTINCT ON` is the correct fix.

**Why not filter-after-limit:** SQLAlchemy raises "Query.filter() called on query with LIMIT/OFFSET already applied." Always call `.filter()` before `.limit()`.

## Round-robin
After Phase 2 fills `by_complex` dict: iterate depth 0..max_depth, for each depth iterate `ordered_cids` and append that complex's depth-th property. Slice `diversified[offset:offset+limit]` for pagination.

## SEO pages
`routes/seo_city.py` intentionally keeps `price-asc` default for SEO-specific sort params — do not change.
