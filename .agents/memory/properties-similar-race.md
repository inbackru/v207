---
name: Properties page dead inline script block
description: Why resetAllFilters / _loadSimilarProps were broken on the novostrojki page and the chosen fix strategy
---

# Properties page: giant inline `<script>` never parses

`templates/properties.html` contains a giant inline `<script>` block (roughly lines
5424–10078, ~4650 lines) that **does not parse** — it has committed JS syntax errors
present in **all** git history back to the grafted root (not git-recoverable, HEAD
itself is corrupted). Confirmed via `node --check` on the extracted block, plus a
server probe that never fired and DOM markers that never executed.

Known syntax errors in that block: `currentPage = {{ page }}` rendered empty when
the route doesn't pass `page` (e.g. `routes/seo_city.py`); a broken `removeFilter`
(missing signature / `const url` / first `if`); a broken `applyFilters` (missing
header + fetch setup).

**Consequence:** every function defined ONLY in that block is `undefined` at runtime
(`resetAllFilters`, `_loadSimilarProps`, etc.). Callers guard with
`typeof X === 'function'` so they silently no-op. A `<script>` that fails to parse
contributes **no bindings at all** — so bare `foo()` references resolve to
`window.foo` set elsewhere, and the block's `window.X = X` tail reassignments never
run.

**Why:** the tail of the dead block reassigns `window.updatePropertiesList`,
`window.applyFiltersViaURL`, `window.triggerLiveSearch`, `window.filterProperties`
etc. "Fixing" the block to make it parse would activate those reassignments and
**override the working external/earlier-block versions** — this is the likely cause
of prior failed fix attempts.

**How to apply:** do NOT try to repair or activate that inline block. Define
replacement functions as `window.*` in an external JS file that loads on the page
(e.g. `static/js/properties-list-updater.js`). Source city context from
`<meta name="city-id">` (template line ~37) and `window.citySlug` (set ~line 1587,
both outside the dead block) — never from `window.currentCityId`/`citySlug`
assignments inside the dead block.

## Reset-all-filters: LIVE-SEARCH reset (no page reload)
**Why:** users expect CIAN/Avito-style instant reset, not a full reload. The old
"hard redirect" approach worked but reloaded the page. AJAX reset is reliable IF you
clear EVERY source `buildLiveParams` reads, in this order: (1) DOM — uncheck all
`input[data-filter-type]`, reset property_type radio to 'all', clear `[data-mob-filter]`
chips, clear price/area/floor/search inputs by id; (2) JS state —
`window.activeFilters` (holds residential_complex/developer), `window.seoPageFilters`,
`window.lockedDistrictSlug`/`lockedDistrictId`, `window._похожиеLoaded`; (3) URL —
`replaceState` to clean base path keeping only `city_id`.
`buildLiveParams` reads DOM-first → URL backup → activeFilters, so clearing all three
yields just `city_id`+`page=1` = all city objects. THEN call `window.applyFilters()`
(fallback `triggerLiveSearch`, then hard-redirect only inside catch).
Base path: segment[1] startsWith `novostrojki`→`/<citySlug>/novostrojki`,
`kvartiry`→`/<citySlug>/kvartiry`, else current pathname (drops query + SEO slug).
Property detail URL is `/object/<id>` (NOT `/<city>/properties/<id>`).

## Похожие (similar) latest-wins
`_loadSimilarProps` and the empty/results paths use a monotonic
`window._похожиеGen` counter + `AbortController` so a stale response can't render
over a newer state. The LIVE `window.triggerLiveSearch` (template ~line 13004) also
has a `window._liveSearchSeq` guard so a late results-response can't re-hide
похожие after an empty state.

## Похожие (similar) must be SMART + match main card design
The empty-state похожие block must reuse the main list's renderer and respect the
view toggle, and must be *relevant* to the user's search — not the cheapest-6
city-wide (old bug surfaced 6 studios all from one ЖК).

`_loadSimilarProps` (static/js/properties-list-updater.js):
- Sources active filters from `new URLSearchParams(location.search)` with fallback
  to `window.seoPageFilters` (SEO landing pages put filters there, not in URL) and
  `window.lockedDistrictSlug`/`lockedDistrictId`. Dimensions: rooms, renovation
  (отделка), object_classes, districts/district_id, price_min/max.
- Builds a **progressive-relaxation** list of `/api/properties/list` queries from
  tightest → broadest and fetches them **sequentially** (single AbortController +
  `_похожиеGen` guard) until one returns ≥4 diversified results; keeps the first
  non-empty meaningful result as a backup; the bare city-only fallback is used ONLY
  if no backup exists. Each attempt carries a human label used as the block subtitle.
- **Diversify**: max 2 per `residential_complex`/`complex_name`, then pick 6.
- **Render via the shared `window.renderPropertyCard(p, idx)`** (same as main list) —
  guarantees design parity because the main list renders from the SAME
  `/api/properties/list` endpoint, so every field renderPropertyCard needs
  (gallery, image, area, floor, total_floors, renovation_display_name,
  complex_object_class_display_name, cashback, residential_complex) is present.
- After rendering, re-init carousels/favorites/comparison and call
  `_applyPohozhieViewMode(window.currentViewMode||'grid')`.

**View toggle parity:** `_applyPohozhieViewMode(mode)` mirrors the template's
`switchToGridView`/`switchToListView` card-restyle logic but targets `#похожие-grid`.
Those two template fns are monkey-patched (wrapped, `_pohozhieWrapped` flag) so a
user toggle also restyles похожие. Wrapping runs at load + retries on
DOMContentLoaded/load (template defines them in an inline block that parses at
~10514–10601).

**Why:** users complained похожие was irrelevant; relaxation preserves комнатность
first, then отделка/район/цена, before ever falling back to generic city results.

## Похожие must be PRICE-LEVEL aware (never fall to cheapest)
**Why:** for high queries ("1-комн от 80млн", "2-комн от 333млн") the old relaxation
dropped the price floor to 0 + sorted price-asc → surfaced the CHEAPEST studios, the
opposite of intent. Premium/business buyers must see elite/business + nearby-price.
**How to apply (hasPrice branch of `_loadSimilarProps`):**
- Compute a `target`: `от X`→`X*1.1`, `до X`→`X*0.9`, range→midpoint.
- If user picked no class, INFER from target: ≥30M→[Премиум,Бизнес], ≥13M→[Бизнес,
  Премиум], ≥9.5M→[Бизнес,Комфорт], else [] (let comfort/econ through for low queries).
- Every relaxation attempt keeps a price BAND centered on target (±25/40/50/60%),
  NEVER floor=0; widen the band, don't remove it.
- Final safety-net (used ONLY when no backup exists, i.e. target is above all stock):
  NO floor + `sort:price-desc` → returns the priciest AVAILABLE objects. This handles
  impossible targets (333M) by showing the most premium stock instead of hiding.
- Client-side sort the pooled results by `|price-target|` (proximity) BEFORE diversify,
  so the closest-priced objects show first regardless of which attempt produced them.

## GOTCHA: API price ceiling ≠ raw excel_properties
`/api/properties/list` serves the **Property** model (is_active set), whose city-1 max
price is only **~82M** (ЖК Сердце Премиум 82M/73M, ЖК Патрики Бизнес 62-66M). The raw
`excel_properties` table has objects up to ~555M, but those are NOT in the served set.
Don't assume premium stock exists at arbitrary high prices — verify via the API, not
the excel table. This is why "от 333млн" has zero in-band matches and must fall to the
price-desc safety-net.
