---
name: OSM district stitching cross-city jumps
description: Adjacent administrative districts share boundary ways; greedy stitch without a distance cap creates 6876m cross-city artifacts
---

**The rule:** `_stitch_ways` in `routes/admin.py` must use a `MAX_GAP_DEG` cap (currently `0.02` ≈ 2km) when picking the next way. If no remaining way connects within the cap, drop it — don't append.

**Why:** Kursk okrugs (Сеймский/Центральный/Железнодорожный) share outer ways along their common borders. The old fallback of "append the longest remaining segment" caused a 6876m diagonal jump from Центральный into Железнодорожный territory, producing a self-intersecting polygon visible as a concave notch.

**How to apply:**
- Any future city OSM import via admin panel uses `_stitch_ways`, so this cap is already in place.
- If a new district polygon shows a large cross-city diagonal on the map, check for shared boundary ways: re-fetch from Overpass with `out geom` and the stitch should now drop the offending segment automatically.
- Remaining jumps of 500–1100m in the result are normal (OSM boundaries follow rivers/roads with small gaps); only jumps >2000m are artifacts.
- To clean existing bad DB polygons: split at >2000m gaps, take the largest contiguous segment.
