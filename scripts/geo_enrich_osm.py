"""
geo_enrich_osm.py — OSM Overpass geo enrichment (no API key needed).

Usage:
  python scripts/geo_enrich_osm.py districts          # Add districts for all cities
  python scripts/geo_enrich_osm.py streets            # Add streets for all cities
  python scripts/geo_enrich_osm.py polygons           # Fill FULL polygon geometry for all districts
  python scripts/geo_enrich_osm.py osm_ids            # Fill osm_id for existing records
  python scripts/geo_enrich_osm.py all                # Run all steps
  python scripts/geo_enrich_osm.py polygons sochi     # Single city
"""

import sys
import os
import time
import json
import re
import requests
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Config ────────────────────────────────────────────────────────────────────

DB_URL = os.environ.get("DATABASE_URL")
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/cgi/interpreter",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
RATE_SLEEP = 1.5          # seconds between API calls (OSM policy: 1/sec)
BATCH_SIZE = 50           # streets per DB insert batch

HEADERS = {"User-Agent": "InBack-RealEstate-Bot/1.0 (https://inback.ru)"}

# City OSM relations — pre-fetched OSM relation IDs for accurate boundary queries
# OSM relation IDs verified via Nominatim — area_id = 3600000000 + rel_id
CITY_OSM_RELATIONS = {
    "krasnodar":    7373058,
    "sochi":        1430508,
    "maykop":       3441283,
    "anapa":        1477115,
    "novorossiysk": 1477110,
    "gelendzhik":   2263494,
    "armavir":      3476238,
    "tuapse":       3532696,
}

# ── Transliteration (same table as utils/transliteration.py) ─────────────────

TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo',
    'ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m',
    'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u',
    'ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'sch',
    'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
}

def make_slug(name: str) -> str:
    if not name:
        return "unknown"
    s = name.lower()
    result = ""
    for ch in s:
        result += TRANSLIT.get(ch, ch)
    result = re.sub(r'[^a-z0-9]+', '-', result)
    return result.strip('-') or "unknown"


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_URL)


def get_cities(conn, slug_filter=None):
    cur = conn.cursor()
    if slug_filter:
        cur.execute("SELECT id, name, slug, latitude, longitude FROM cities WHERE slug=%s", (slug_filter,))
    else:
        cur.execute("SELECT id, name, slug, latitude, longitude FROM cities ORDER BY id")
    return cur.fetchall()


def existing_district_slugs(conn, city_id):
    cur = conn.cursor()
    cur.execute("SELECT slug FROM districts WHERE city_id=%s", (city_id,))
    return {r[0] for r in cur.fetchall()}


def existing_street_slugs(conn, city_id):
    cur = conn.cursor()
    cur.execute("SELECT slug FROM streets WHERE city_id=%s", (city_id,))
    return {r[0] for r in cur.fetchall()}


# ── OSM Overpass queries ──────────────────────────────────────────────────────

def overpass_query(query: str, timeout: int = 60) -> dict | None:
    for mirror in OVERPASS_MIRRORS:
        try:
            r = requests.post(mirror, data={"data": query},
                              headers=HEADERS, timeout=timeout + 30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"    [WARN] Overpass error on {mirror}: {e}")
            time.sleep(2)
    return None


def fetch_districts_osm(city_slug: str, city_lat: float, city_lon: float) -> list[dict]:
    """
    Fetch neighbourhoods / suburbs / admin boundaries (level 8-10) near the city.
    Returns list of dicts: {name, osm_id, osm_type, lat, lon, place_type}
    """
    rel_id = CITY_OSM_RELATIONS.get(city_slug)
    if rel_id:
        # area_id = 3600000000 + relation_id (OSM convention)
        area_id = 3600000000 + rel_id
        query = f"""
[out:json][timeout:60];
area({area_id})->.city;
(
  node(area.city)["place"~"^(neighbourhood|suburb|quarter|village|hamlet|town)$"]["name"];
  way(area.city)["place"~"^(neighbourhood|suburb|quarter|village|hamlet|town)$"]["name"];
  rel(area.city)["boundary"="administrative"]["admin_level"~"^(8|9|10)$"]["name"];
);
out center tags;
"""
    else:
        # Fallback: bounding box around city center ±0.15°
        lat, lon = city_lat, city_lon
        bbox = f"{lat-0.15},{lon-0.15},{lat+0.15},{lon+0.15}"
        query = f"""
[out:json][timeout:60];
(
  node({bbox})["place"~"^(neighbourhood|suburb|quarter)$"]["name"];
  way({bbox})["place"~"^(neighbourhood|suburb|quarter)$"]["name"];
);
out center tags;
"""
    data = overpass_query(query)
    if not data:
        return []

    results = []
    seen_names = set()
    for el in data.get("elements", []):
        name = (el.get("tags") or {}).get("name", "").strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        place_type = (el.get("tags") or {}).get("place", "neighbourhood")
        results.append({
            "name": name,
            "osm_id": el.get("id"),
            "osm_type": el.get("type"),
            "lat": lat,
            "lon": lon,
            "place_type": place_type,
        })
    return results


def fetch_streets_osm(city_slug: str, city_lat: float, city_lon: float) -> list[dict]:
    """
    Fetch named streets (ways with highway + name) within city bounds.
    Returns deduplicated list by name.
    """
    rel_id = CITY_OSM_RELATIONS.get(city_slug)
    if rel_id:
        area_id = 3600000000 + rel_id
        query = f"""
[out:json][timeout:120];
area({area_id})->.city;
way(area.city)["highway"~"^(primary|secondary|tertiary|residential|living_street|pedestrian|unclassified)$"]["name"];
out center tags qt;
"""
    else:
        lat, lon = city_lat, city_lon
        bbox = f"{lat-0.12},{lon-0.12},{lat+0.12},{lon+0.12}"
        query = f"""
[out:json][timeout:90];
way({bbox})["highway"~"^(primary|secondary|tertiary|residential|living_street|pedestrian|unclassified)$"]["name"];
out center tags qt;
"""
    data = overpass_query(query, timeout=130)
    if not data:
        return []

    seen = {}  # name -> dict (keep first occurrence with coords)
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name", "").strip()
        if not name:
            continue
        if name in seen:
            continue
        lat = (el.get("center") or {}).get("lat") or el.get("lat")
        lon = (el.get("center") or {}).get("lon") or el.get("lon")
        hw = tags.get("highway", "")
        # Infer street type from name suffix
        stype = None
        nm_lower = name.lower()
        for suffix, stype_val in [("улица","ulitsa"),("проспект","prospekt"),
                                   ("переулок","pereulok"),("бульвар","bulvar"),
                                   ("шоссе","shosse"),("набережная","naberezhnaya"),
                                   ("площадь","ploshchad"),("тупик","tupik"),
                                   ("проезд","proezd")]:
            if suffix in nm_lower:
                stype = stype_val; break
        seen[name] = {"name": name, "osm_id": el.get("id"), "lat": lat, "lon": lon,
                      "street_type": stype}
    return list(seen.values())


# ── Step 1: Districts ─────────────────────────────────────────────────────────

def enrich_districts(conn, city_slug_filter=None):
    cities = get_cities(conn, city_slug_filter)
    total_added = 0

    for city_id, city_name, city_slug, city_lat, city_lon in cities:
        print(f"\n[Districts] {city_name} (slug={city_slug})")
        time.sleep(RATE_SLEEP)
        districts = fetch_districts_osm(city_slug, city_lat, city_lon)
        print(f"  OSM returned {len(districts)} items")

        existing = existing_district_slugs(conn, city_id)
        cur = conn.cursor()
        added = 0

        for d in districts:
            slug = make_slug(d["name"])
            if not slug or slug in existing:
                continue
            existing.add(slug)
            cur.execute("""
                INSERT INTO districts (name, slug, city_id, district_type, latitude, longitude, osm_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT ON CONSTRAINT unique_district_slug_per_city DO NOTHING
            """, (
                d["name"], slug, city_id,
                "micro",    # default type
                d.get("lat"), d.get("lon"),
                d.get("osm_id"),
            ))
            added += 1

        conn.commit()
        total_added += added
        print(f"  ✅ Added {added} new districts for {city_name}")

    print(f"\n✅ Districts total added: {total_added}")


# ── Step 2: Streets ───────────────────────────────────────────────────────────

def enrich_streets(conn, city_slug_filter=None):
    cities = get_cities(conn, city_slug_filter)
    total_added = 0

    for city_id, city_name, city_slug, city_lat, city_lon in cities:
        print(f"\n[Streets] {city_name} (slug={city_slug})")
        time.sleep(RATE_SLEEP)
        streets = fetch_streets_osm(city_slug, city_lat, city_lon)
        print(f"  OSM returned {len(streets)} streets")
        if not streets:
            continue

        existing = existing_street_slugs(conn, city_id)
        cur = conn.cursor()
        added = 0
        batch = []

        for s in streets:
            slug = make_slug(s["name"])
            if not slug or slug in existing:
                continue
            existing.add(slug)
            batch.append((s["name"], slug, city_id, s.get("lat"), s.get("lon"),
                          s.get("street_type"), s.get("osm_id")))

            if len(batch) >= BATCH_SIZE:
                cur.executemany("""
                    INSERT INTO streets (name, slug, city_id, latitude, longitude, street_type, osm_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT ON CONSTRAINT unique_street_slug_per_city DO NOTHING
                """, batch)
                conn.commit()
                added += len(batch)
                batch = []

        if batch:
            cur.executemany("""
                INSERT INTO streets (name, slug, city_id, latitude, longitude, street_type, osm_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT ON CONSTRAINT unique_street_slug_per_city DO NOTHING
            """, batch)
            conn.commit()
            added += len(batch)

        total_added += added
        print(f"  ✅ Added {added} new streets for {city_name}")

    print(f"\n✅ Streets total added: {total_added}")


# ── Step 3: Fill OSM IDs for existing Krasnodar records via Nominatim ─────────

def fill_osm_ids_nominatim(conn, city_slug_filter=None):
    """Fill missing osm_id for districts and streets using OSM Nominatim."""
    cities = get_cities(conn, city_slug_filter)

    for city_id, city_name, city_slug, city_lat, city_lon in cities:
        # Districts without osm_id
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM districts WHERE city_id=%s AND osm_id IS NULL", (city_id,))
        districts = cur.fetchall()
        print(f"\n[OSM IDs] {city_name}: {len(districts)} districts need osm_id")

        for did, dname in districts[:30]:  # cap at 30 per city to avoid rate limits
            try:
                r = requests.get(NOMINATIM_URL, params={
                    "q": f"{dname}, {city_name}",
                    "format": "json", "limit": 1,
                    "countrycodes": "ru",
                }, headers=HEADERS, timeout=10)
                data = r.json()
                if data:
                    osm_id = data[0].get("osm_id")
                    lat = data[0].get("lat")
                    lon = data[0].get("lon")
                    cur.execute("UPDATE districts SET osm_id=%s, latitude=COALESCE(latitude,%s), longitude=COALESCE(longitude,%s) WHERE id=%s",
                                (osm_id, lat, lon, did))
                    conn.commit()
                time.sleep(RATE_SLEEP)
            except Exception as e:
                print(f"    [WARN] Nominatim error for {dname}: {e}")

        # Streets without osm_id (sample first 50)
        cur.execute("SELECT id, name FROM streets WHERE city_id=%s AND osm_id IS NULL LIMIT 50", (city_id,))
        streets = cur.fetchall()
        print(f"  {len(streets)} streets (sample) need osm_id")

        for sid, sname in streets:
            try:
                r = requests.get(NOMINATIM_URL, params={
                    "q": f"{sname}, {city_name}",
                    "format": "json", "limit": 1,
                    "countrycodes": "ru",
                    "featuretype": "street",
                }, headers=HEADERS, timeout=10)
                data = r.json()
                if data:
                    osm_id = data[0].get("osm_id")
                    cur.execute("UPDATE streets SET osm_id=%s WHERE id=%s", (osm_id, sid))
                    conn.commit()
                time.sleep(RATE_SLEEP)
            except Exception as e:
                print(f"    [WARN] Nominatim error for {sname}: {e}")

    print("\n✅ OSM IDs fill done")


# ── Step 3b: Full polygon geometry from OSM ───────────────────────────────────

def _assemble_ring(members, role="outer"):
    """Assemble an ordered coordinate ring from OSM relation members."""
    # Collect all ways with the given role
    ways = []
    for m in members:
        if m.get("role") == role and m.get("type") == "way":
            geom = m.get("geometry", [])
            if geom:
                ways.append([(g["lat"], g["lon"]) for g in geom])

    if not ways:
        return []

    # Greedy chain: join ways head-to-tail
    ring = list(ways[0])
    remaining = ways[1:]
    max_iters = len(remaining) * 2
    iters = 0
    while remaining and iters < max_iters:
        iters += 1
        joined = False
        for i, way in enumerate(remaining):
            if not way:
                remaining.pop(i); joined = True; break
            # Try to extend ring at the end
            if abs(ring[-1][0] - way[0][0]) < 1e-6 and abs(ring[-1][1] - way[0][1]) < 1e-6:
                ring.extend(way[1:])
                remaining.pop(i); joined = True; break
            if abs(ring[-1][0] - way[-1][0]) < 1e-6 and abs(ring[-1][1] - way[-1][1]) < 1e-6:
                ring.extend(reversed(way[:-1]))
                remaining.pop(i); joined = True; break
            # Try at the front
            if abs(ring[0][0] - way[-1][0]) < 1e-6 and abs(ring[0][1] - way[-1][1]) < 1e-6:
                ring = list(way[:-1]) + ring
                remaining.pop(i); joined = True; break
            if abs(ring[0][0] - way[0][0]) < 1e-6 and abs(ring[0][1] - way[0][1]) < 1e-6:
                ring = list(reversed(way[1:])) + ring
                remaining.pop(i); joined = True; break
        if not joined:
            # Append orphan ways as-is (may create gaps but preserves coverage)
            ring.extend(remaining.pop(0))

    return ring


def _simplify_ring(pts, max_pts=300):
    """Reduce polygon point count using Ramer-Douglas-Peucker-like step sampling."""
    if len(pts) <= max_pts:
        return pts
    step = len(pts) / max_pts
    return [pts[int(i * step)] for i in range(max_pts)]


def _parse_elements_to_polygons(elements):
    """Extract polygon geometry from a list of OSM Overpass elements."""
    results = []
    for el in elements:
        name = el.get("tags", {}).get("name", "").strip()
        if not name:
            continue

        pts = []
        el_type = el["type"]

        if el_type == "way":
            geom = el.get("geometry", [])
            pts = [(g["lat"], g["lon"]) for g in geom if "lat" in g]

        elif el_type == "relation":
            members = el.get("members", [])
            outer = _assemble_ring(members, "outer")
            if not outer:
                outer = _assemble_ring(members, "")
            pts = outer

        if len(pts) < 3:
            continue

        pts = _simplify_ring(pts, max_pts=400)
        center_lat = sum(p[0] for p in pts) / len(pts)
        center_lon = sum(p[1] for p in pts) / len(pts)
        geom_str = ";".join(f"{lat:.6f},{lon:.6f}" for lat, lon in pts)

        results.append({
            "name": name,
            "osm_id": el.get("id"),
            "osm_type": el_type,
            "geometry": geom_str,
            "lat": center_lat,
            "lon": center_lon,
            "point_count": len(pts),
        })
    return results


NOMINATIM_LOOKUP_URL = "https://nominatim.openstreetmap.org/lookup"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"


def _nominatim_polygon(osm_type: str, osm_id: int, name: str) -> list[tuple]:
    """
    Fetch full polygon from Nominatim for a specific OSM object.
    osm_type: 'R' (relation), 'W' (way), 'N' (node)
    Returns list of (lat, lon) points or empty list.
    """
    try:
        r = requests.get(NOMINATIM_LOOKUP_URL, params={
            "osm_ids": f"{osm_type}{osm_id}",
            "format": "json",
            "polygon_geojson": "1",
        }, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data:
            return []
        geojson = data[0].get("geojson", {})
        geo_type = geojson.get("type", "")
        coords = geojson.get("coordinates", [])

        pts = []
        if geo_type == "Polygon":
            # Outer ring: list of [lon, lat]
            for lon, lat in coords[0]:
                pts.append((lat, lon))
        elif geo_type == "MultiPolygon":
            # Largest outer ring
            rings = [ring[0] for ring in coords if ring]
            outer = max(rings, key=len) if rings else []
            for lon, lat in outer:
                pts.append((lat, lon))
        elif geo_type in ("LineString", "MultiLineString"):
            # Linear boundary — use as-is
            raw = coords if geo_type == "LineString" else coords[0]
            for lon, lat in raw:
                pts.append((lat, lon))
        return pts
    except Exception as e:
        return []


def _nominatim_search_polygon(name: str, city_name: str) -> tuple[int | None, str | None, list]:
    """Search Nominatim by name and return (osm_id, osm_type_char, pts)."""
    try:
        r = requests.get(NOMINATIM_SEARCH_URL, params={
            "q": f"{name}, {city_name}, Россия",
            "format": "json",
            "limit": "1",
            "polygon_geojson": "1",
            "countrycodes": "ru",
        }, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None, None, []
        hit = data[0]
        osm_id = hit.get("osm_id")
        osm_type_char = hit.get("osm_type", "")[:1].upper()  # R/W/N
        geojson = hit.get("geojson", {})
        geo_type = geojson.get("type", "")
        coords = geojson.get("coordinates", [])
        pts = []
        if geo_type == "Polygon":
            for lon, lat in coords[0]:
                pts.append((lat, lon))
        elif geo_type == "MultiPolygon":
            rings = [ring[0] for ring in coords if ring]
            outer = max(rings, key=len) if rings else []
            for lon, lat in outer:
                pts.append((lat, lon))
        return osm_id, osm_type_char, pts
    except Exception:
        return None, None, []


def fetch_polygons_osm(city_slug, city_lat, city_lon):
    """
    Fetch full polygon geometry for all named areas within a city.
    Strategy:
      1. Overpass: admin boundaries level 8-10 (manageable size)
      2. Nominatim lookup by osm_id (for districts that already have osm_id)
    Returns list of dicts: {name, osm_id, osm_type, geometry, lat, lon, point_count}
    """
    rel_id = CITY_OSM_RELATIONS.get(city_slug)
    if not rel_id:
        return []

    area_id = 3600000000 + rel_id
    all_results = []
    seen_ids = set()

    # ── Pass 1: Admin boundaries level 8-10 via Overpass ──────────────────────
    for level, label in [("8", "admin-8"), ("9", "admin-9"), ("10", "admin-10")]:
        time.sleep(RATE_SLEEP)
        query = f"""
[out:json][timeout:60];
area({area_id})->.city;
relation(area.city)["boundary"="administrative"]["admin_level"="{level}"]["name"];
out geom;
"""
        data = overpass_query(query, timeout=75)
        if data:
            els = data.get("elements", [])
            batch = _parse_elements_to_polygons(els)
            for item in batch:
                if item["osm_id"] not in seen_ids:
                    seen_ids.add(item["osm_id"])
                    all_results.append(item)
            print(f"    [{label}] {len(els)} elements → {len(batch)} polygons")
        else:
            print(f"    [{label}] skipped / timeout")

    return all_results


def fetch_polygons_nominatim(conn, city_id, city_name, city_slug):
    """
    Use Nominatim to fetch polygon geometry for each district in the DB.
    For districts with osm_id: use /lookup?osm_ids=R{id}&polygon_geojson=1
    For districts without osm_id: use /search?q=name,city&polygon_geojson=1
    Returns list of (district_id, geometry_str, lat, lon, osm_id)
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, osm_id
        FROM districts WHERE city_id=%s
        ORDER BY id
    """, (city_id,))
    rows = cur.fetchall()

    results = []
    for did, dname, d_osm_id in rows:
        pts = []
        new_osm_id = d_osm_id

        if d_osm_id:
            osm_type = "R"  # most district boundaries are relations
            pts = _nominatim_polygon(osm_type, d_osm_id, dname)
            if not pts:
                pts = _nominatim_polygon("W", d_osm_id, dname)

        if not pts:
            # Fall back to search
            found_id, found_type, pts = _nominatim_search_polygon(dname, city_name)
            if found_id:
                new_osm_id = found_id

        time.sleep(RATE_SLEEP)

        if len(pts) >= 3:
            pts = _simplify_ring(pts, max_pts=400)
            center_lat = sum(p[0] for p in pts) / len(pts)
            center_lon = sum(p[1] for p in pts) / len(pts)
            geom_str = ";".join(f"{lat:.6f},{lon:.6f}" for lat, lon in pts)
            results.append((did, geom_str, center_lat, center_lon, new_osm_id, dname, len(pts)))
        else:
            results.append((did, None, None, None, new_osm_id, dname, 0))

    return results


def _update_district_polygon(cur, conn, did, geom_str, lat, lon, osm_id):
    """Helper: update district geometry and centroid."""
    cur.execute("""
        UPDATE districts
        SET geometry=%s,
            latitude=COALESCE(latitude,%s),
            longitude=COALESCE(longitude,%s),
            osm_id=COALESCE(osm_id,%s),
            updated_at=NOW()
        WHERE id=%s
    """, (geom_str, lat, lon, osm_id, did))
    conn.commit()


def enrich_polygons(conn, city_slug_filter=None):
    """
    Two-pass polygon enrichment for all districts:
    Pass 1: Overpass admin_level 8/9/10 boundaries → match to existing districts by name/slug
    Pass 2: Nominatim lookup (polygon_geojson=1) for all districts that still lack geometry
    """
    cities = get_cities(conn, city_slug_filter)
    total_updated = 0

    for city_id, city_name, city_slug, city_lat, city_lon in cities:
        print(f"\n[Polygons] {city_name} (slug={city_slug})")
        cur = conn.cursor()
        updated = 0

        # ── Pass 1: Admin boundary polygons from Overpass ──────────────────────
        osm_polygons = fetch_polygons_osm(city_slug, city_lat, city_lon)
        print(f"  Pass 1 (Overpass admin): {len(osm_polygons)} polygons")

        if osm_polygons:
            cur.execute("SELECT id, name, slug FROM districts WHERE city_id=%s", (city_id,))
            by_slug = {row[2]: row[0] for row in cur.fetchall()}
            cur.execute("SELECT id, name, slug FROM districts WHERE city_id=%s", (city_id,))
            by_name = {row[1].lower(): row[0] for row in cur.fetchall()}

            for poly in osm_polygons:
                slug = make_slug(poly["name"])
                did = by_slug.get(slug) or by_name.get(poly["name"].lower())
                if did:
                    _update_district_polygon(cur, conn, did, poly["geometry"],
                                             poly["lat"], poly["lon"], poly["osm_id"])
                    updated += 1
                else:
                    # Insert new district from admin boundary
                    if slug:
                        cur.execute("""
                            INSERT INTO districts (name, slug, city_id, district_type,
                                latitude, longitude, geometry, osm_id, created_at, updated_at)
                            VALUES (%s,%s,%s,'admin',%s,%s,%s,%s,NOW(),NOW())
                            ON CONFLICT ON CONSTRAINT unique_district_slug_per_city DO UPDATE
                              SET geometry=EXCLUDED.geometry,
                                  osm_id=COALESCE(districts.osm_id,EXCLUDED.osm_id),
                                  updated_at=NOW()
                        """, (poly["name"], slug, city_id, poly["lat"], poly["lon"],
                              poly["geometry"], poly["osm_id"]))
                        conn.commit()
                        updated += 1

        # ── Pass 2: Nominatim polygon_geojson for remaining districts ─────────
        cur.execute("""
            SELECT id, name, osm_id FROM districts
            WHERE city_id=%s AND (geometry IS NULL OR length(geometry) < 30)
            ORDER BY id
        """, (city_id,))
        without_geom = cur.fetchall()
        print(f"  Pass 2 (Nominatim): {len(without_geom)} districts need geometry")

        for did, dname, d_osm_id in without_geom:
            pts = []
            found_osm_id = d_osm_id

            # Try by existing osm_id first
            if d_osm_id:
                pts = _nominatim_polygon("R", d_osm_id, dname)
                if not pts:
                    pts = _nominatim_polygon("W", d_osm_id, dname)

            # Search by name if not found
            if not pts:
                found_id, _, pts = _nominatim_search_polygon(dname, city_name)
                if found_id:
                    found_osm_id = found_id

            time.sleep(RATE_SLEEP)

            if len(pts) >= 3:
                pts = _simplify_ring(pts, max_pts=400)
                clat = sum(p[0] for p in pts) / len(pts)
                clon = sum(p[1] for p in pts) / len(pts)
                geom_str = ";".join(f"{lat:.6f},{lon:.6f}" for lat, lon in pts)
                _update_district_polygon(cur, conn, did, geom_str, clat, clon, found_osm_id)
                updated += 1
                print(f"    ✅ {dname}: {len(pts)} pts")
            else:
                print(f"    ⚠️  {dname}: no polygon found")

        print(f"  ✅ {city_name}: {updated} districts got polygon geometry")
        total_updated += updated

    print(f"\n✅ Polygons done: {total_updated} total updated")


# ── Step 4: Fix coordinates for Krasnodor districts missing lat/lon ───────────

def fix_missing_coords(conn, city_slug_filter="krasnodar"):
    cur = conn.cursor()
    cur.execute("""
        SELECT d.id, d.name, c.name as city_name
        FROM districts d JOIN cities c ON c.id=d.city_id
        WHERE (d.latitude IS NULL OR d.longitude IS NULL)
        AND (c.slug=%s OR %s IS NULL)
    """, (city_slug_filter, city_slug_filter if city_slug_filter else None))
    rows = cur.fetchall()
    print(f"[Fix coords] {len(rows)} districts missing coordinates")

    for did, dname, cname in rows:
        try:
            r = requests.get(NOMINATIM_URL, params={
                "q": f"{dname}, {cname}, Россия",
                "format": "json", "limit": 1,
            }, headers=HEADERS, timeout=10)
            data = r.json()
            if data:
                lat, lon = data[0].get("lat"), data[0].get("lon")
                cur.execute("UPDATE districts SET latitude=%s, longitude=%s WHERE id=%s",
                            (lat, lon, did))
                conn.commit()
                print(f"  ✅ {dname}: {lat}, {lon}")
            time.sleep(RATE_SLEEP)
        except Exception as e:
            print(f"  [WARN] {dname}: {e}")


# ── Step 5: Stats report ──────────────────────────────────────────────────────

def report(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT c.name,
          (SELECT count(*) FROM districts d WHERE d.city_id=c.id) as districts,
          (SELECT count(*) FROM districts d WHERE d.city_id=c.id AND d.latitude IS NOT NULL) as d_coords,
          (SELECT count(*) FROM districts d WHERE d.city_id=c.id AND d.osm_id IS NOT NULL) as d_osm,
          (SELECT count(*) FROM streets s WHERE s.city_id=c.id) as streets,
          (SELECT count(*) FROM streets s WHERE s.city_id=c.id AND s.latitude IS NOT NULL) as s_coords
        FROM cities c ORDER BY c.id
    """)
    rows = cur.fetchall()
    print(f"\n{'City':<15} {'Districts':>9} {'D.Coords':>9} {'D.OSM':>7} {'Streets':>8} {'S.Coords':>9}")
    print("-" * 65)
    for r in rows:
        print(f"{r[0]:<15} {r[1]:>9} {r[2]:>9} {r[3]:>7} {r[4]:>8} {r[5]:>9}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0]
    city_filter = args[1] if len(args) > 1 else None

    conn = get_conn()
    try:
        if cmd in ("districts", "all"):
            enrich_districts(conn, city_filter)
        if cmd in ("streets", "all"):
            enrich_streets(conn, city_filter)
        if cmd in ("polygons", "all"):
            enrich_polygons(conn, city_filter)
        if cmd in ("osm_ids",):
            fill_osm_ids_nominatim(conn, city_filter)
        if cmd in ("fix_coords",):
            fix_missing_coords(conn, city_filter)
        if cmd in ("report", "all"):
            report(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
