#!/usr/bin/env python3
"""
enrich_geo_full.py — Full OSM geo enrichment with REAL polygon boundaries.

Fetches from OpenStreetMap (no API key needed):
  1. Administrative okrugs (admin_level=9) with proper ring stitching
  2. Microdistricts (place=suburb/quarter/neighbourhood) with polygons
  3. Streets with full polyline geometry
  4. Re-assigns properties to districts using point-in-polygon

Usage:
  python scripts/enrich_geo_full.py krasnodar              # All steps
  python scripts/enrich_geo_full.py krasnodar --okrugs     # Only admin okrugs
  python scripts/enrich_geo_full.py krasnodar --districts  # Only microdistricts
  python scripts/enrich_geo_full.py krasnodar --streets    # Only streets
  python scripts/enrich_geo_full.py krasnodar --assign     # Re-assign properties
  python scripts/enrich_geo_full.py all                    # All cities
"""

import sys
import os
import re
import time
import math
import argparse
import logging
import psycopg2
import psycopg2.extras
import requests
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL")

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/cgi/interpreter",
]

HEADERS = {"User-Agent": "InBack-RealEstate-Bot/1.0 (https://inback.ru)"}
RATE_SLEEP = 2.0

# City OSM area IDs (area_id = 3600000000 + osm_relation_id)
CITY_CONFIG = {
    "krasnodar":    {"city_id": 1, "name": "Краснодар",     "area_id": 3607373058, "admin_levels": [9]},
    "sochi":        {"city_id": 2, "name": "Сочи",          "area_id": 3601430508, "admin_levels": [7, 8]},
    "anapa":        {"city_id": 3, "name": "Анапа",         "area_id": 3601477115, "admin_levels": [8, 9]},
    "gelendzhik":   {"city_id": 4, "name": "Геленджик",     "area_id": 3602263494, "admin_levels": [8]},
    "novorossiysk": {"city_id": 5, "name": "Новороссийск",  "area_id": 3601477110, "admin_levels": [8, 9]},
    "armavir":      {"city_id": 6, "name": "Армавир",       "area_id": 3603476238, "admin_levels": [8]},
    "tuapse":       {"city_id": 7, "name": "Туапсе",        "area_id": 3603532696, "admin_levels": [8]},
    "maykop":       {"city_id": 8, "name": "Майкоп",        "area_id": 3603441283, "admin_levels": [8]},
}

RU_TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo',
    'ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m',
    'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u',
    'ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch',
    'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
}
CYRILLIC_RE = re.compile(r'[а-яёА-ЯЁ]')


def slugify(name: str) -> str:
    s = name.lower()
    out = ""
    for ch in s:
        out += RU_TRANSLIT.get(ch, ch)
    out = re.sub(r'[^a-z0-9]+', '-', out)
    return out.strip('-') or "unknown"


def unique_slug(base, existing):
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


# ─── Overpass ────────────────────────────────────────────────────────────────

def overpass_query(query: str, timeout: int = 90) -> dict | None:
    for mirror in OVERPASS_MIRRORS:
        try:
            r = requests.post(mirror, data={"data": query},
                              headers=HEADERS, timeout=timeout + 20)
            if r.status_code == 429:
                log.warning(f"429 from {mirror}, waiting 15s")
                time.sleep(15)
                continue
            if r.status_code == 200 and r.text.strip():
                return r.json()
            log.warning(f"  {mirror}: HTTP {r.status_code}, len={len(r.text)}")
        except Exception as e:
            log.warning(f"  {mirror}: {e}")
        time.sleep(3)
    return None


# ─── Ring stitching ──────────────────────────────────────────────────────────

def stitch_ways_into_ring(ways_coords: list) -> list:
    """
    Connect multiple OSM ways (each a list of (lat, lng)) into a closed polygon ring.
    Uses greedy nearest-endpoint algorithm.
    """
    if not ways_coords:
        return []
    if len(ways_coords) == 1:
        ring = list(ways_coords[0])
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        return ring

    result = list(ways_coords[0])
    remaining = [list(w) for w in ways_coords[1:]]

    max_iter = len(remaining) * 2 + 2
    while remaining and max_iter > 0:
        max_iter -= 1
        last = result[-1]

        best_idx = -1
        best_forward = True
        best_dist = float('inf')

        for i, way in enumerate(remaining):
            if not way:
                continue
            d_fwd = (last[0] - way[0][0])**2 + (last[1] - way[0][1])**2
            d_rev = (last[0] - way[-1][0])**2 + (last[1] - way[-1][1])**2
            if d_fwd < best_dist:
                best_dist = d_fwd
                best_idx = i
                best_forward = True
            if d_rev < best_dist:
                best_dist = d_rev
                best_idx = i
                best_forward = False

        if best_idx == -1:
            break

        way = remaining.pop(best_idx)
        if not best_forward:
            way = list(reversed(way))

        # Skip duplicate first point
        start = 1 if result and result[-1][0] == way[0][0] and result[-1][1] == way[0][1] else 0
        result.extend(way[start:])

    # Close the ring
    if result and (result[0][0] != result[-1][0] or result[0][1] != result[-1][1]):
        result.append(result[0])

    return result


def extract_ring_from_members(members: list) -> list:
    """Extract and stitch outer way geometries from OSM relation members."""
    outer_ways = [m for m in members if m.get('role') == 'outer' and m.get('type') == 'way']
    if not outer_ways:
        outer_ways = [m for m in members if m.get('type') == 'way']

    ways_coords = []
    for m in outer_ways:
        geom = m.get('geometry', [])
        if len(geom) >= 2:
            coords = [(pt['lat'], pt['lon']) for pt in geom if 'lat' in pt]
            if coords:
                ways_coords.append(coords)

    if not ways_coords:
        return []

    return stitch_ways_into_ring(ways_coords)


def ring_to_geom_str(ring: list) -> str:
    """Convert list of (lat, lng) to 'lat,lng;lat,lng;...' string."""
    return ';'.join(f"{lat},{lng}" for lat, lng in ring)


def compute_centroid(ring: list) -> tuple:
    if not ring:
        return None, None
    lat = sum(p[0] for p in ring) / len(ring)
    lng = sum(p[1] for p in ring) / len(ring)
    return round(lat, 6), round(lng, 6)


def polygon_area_m2(ring: list) -> float:
    """Estimate polygon area in m² using Shoelace formula with rough lat/lng scaling."""
    if len(ring) < 3:
        return 0.0
    lat_scale = 111320.0
    n = len(ring)
    area = 0.0
    for i in range(n - 1):
        y0 = ring[i][0] * lat_scale
        x0 = ring[i][1] * lat_scale * math.cos(math.radians(ring[i][0]))
        y1 = ring[i+1][0] * lat_scale
        x1 = ring[i+1][1] * lat_scale * math.cos(math.radians(ring[i+1][0]))
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


# ─── Point-in-polygon ────────────────────────────────────────────────────────

def point_in_ring(lat: float, lng: float, ring: list) -> bool:
    """Ray-casting algorithm for point-in-polygon."""
    if len(ring) < 3:
        return False
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i][0], ring[i][1]
        yj, xj = ring[j][0], ring[j][1]
        if ((yi > lng) != (yj > lng)) and (lat < (xj - xi) * (lng - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


# ─── DB helpers ──────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_URL)


def parse_geom_str(geom_str: str) -> list:
    """Parse 'lat,lng;lat,lng;...' into list of (lat, lng) tuples."""
    if not geom_str:
        return []
    pts = []
    for part in re.split(r'[;#]+', geom_str):
        part = part.strip()
        if not part:
            continue
        coords = part.split(',')
        if len(coords) == 2:
            try:
                pts.append((float(coords[0]), float(coords[1])))
            except ValueError:
                pass
    return pts


# ─── Step 1: Fetch admin okrugs ──────────────────────────────────────────────

def fetch_admin_okrugs(city_slug: str, cfg: dict) -> list:
    """Fetch admin boundary polygons (admin_level specified in cfg) from Overpass."""
    area_id = cfg['area_id']
    admin_levels = cfg['admin_levels']
    level_filter = '|'.join(str(l) for l in admin_levels)

    log.info(f"Fetching admin_level={admin_levels} boundaries for {cfg['name']}...")

    query = f"""[out:json][timeout:90];
area({area_id})->.city;
relation(area.city)["boundary"="administrative"]["admin_level"~"^({level_filter})$"]["name"];
out body geom;"""

    data = overpass_query(query, timeout=90)
    if not data:
        return []

    results = []
    for el in data.get('elements', []):
        tags = el.get('tags', {})
        name = tags.get('name:ru') or tags.get('name', '')
        if not name or not CYRILLIC_RE.search(name):
            continue

        admin_level = int(tags.get('admin_level', 0))
        members = el.get('members', [])
        ring = extract_ring_from_members(members)

        if len(ring) < 4:
            log.warning(f"  Skipping {name}: only {len(ring)} polygon points")
            continue

        geom_str = ring_to_geom_str(ring)
        lat, lng = compute_centroid(ring)
        area = polygon_area_m2(ring)

        results.append({
            'osm_id': el['id'],
            'name': name,
            'geometry': geom_str,
            'lat': lat,
            'lng': lng,
            'admin_level': admin_level,
            'district_type': 'admin',
            'place_type': f'admin_{admin_level}',
            'polygon_pts': len(ring),
            'area_m2': area,
        })
        log.info(f"  ✅ {name}: {len(ring)} pts, area={area/1e6:.1f}km²")

    return results


# ─── Step 2: Fetch microdistricts (place=suburb/quarter/neighbourhood) ───────

def fetch_microdistricts(city_slug: str, cfg: dict) -> list:
    """Fetch suburb/quarter/neighbourhood polygons from Overpass."""
    area_id = cfg['area_id']
    log.info(f"Fetching microdistricts for {cfg['name']}...")

    query = f"""[out:json][timeout:90];
area({area_id})->.city;
(
  relation(area.city)["place"~"^(suburb|quarter|neighbourhood|town|village|hamlet)$"]["name"];
  way(area.city)["place"~"^(suburb|quarter|neighbourhood)$"]["name"];
);
out body geom;"""

    data = overpass_query(query, timeout=90)
    if not data:
        return []

    results = []
    SKIP_NAMES = {'снт', 'жк', 'жилой', 'садовод', 'огород', 'дача', 'коттедж', 'агрофирм'}

    for el in data.get('elements', []):
        tags = el.get('tags', {})
        name = tags.get('name:ru') or tags.get('name', '')
        if not name or not CYRILLIC_RE.search(name) or len(name) < 2:
            continue

        # Skip SNT, garden coops, etc.
        low = name.lower()
        if any(sk in low for sk in SKIP_NAMES):
            continue
        if re.search(r'(?:снт|сот|кт)\s*[«№"#]', low):
            continue

        place_type = tags.get('place', 'suburb')
        etype = el.get('type')

        if etype == 'relation':
            members = el.get('members', [])
            ring = extract_ring_from_members(members)
        elif etype == 'way':
            geom_pts = el.get('geometry', [])
            ring = [(pt['lat'], pt['lon']) for pt in geom_pts if 'lat' in pt]
        else:
            continue

        if len(ring) < 4:
            continue

        geom_str = ring_to_geom_str(ring)
        lat, lng = compute_centroid(ring)
        area = polygon_area_m2(ring)

        # Skip tiny polygons (< 0.01 km² = 10,000 m²) — probably errors
        if area < 10_000:
            continue

        results.append({
            'osm_id': el['id'],
            'name': name,
            'geometry': geom_str,
            'lat': lat,
            'lng': lng,
            'admin_level': None,
            'district_type': 'micro',
            'place_type': place_type,
            'polygon_pts': len(ring),
            'area_m2': area,
        })

    log.info(f"  Found {len(results)} microdistricts with valid polygons")
    return results


# ─── Step 3: Fetch streets ────────────────────────────────────────────────────

def fetch_streets(city_slug: str, cfg: dict) -> list:
    """Fetch named street ways with full polyline geometry."""
    area_id = cfg['area_id']
    log.info(f"Fetching streets for {cfg['name']}...")

    query = f"""[out:json][timeout:120];
area({area_id})->.city;
way(area.city)["highway"~"^(primary|secondary|tertiary|residential|living_street|pedestrian|unclassified|trunk|service)$"]["name"];
out body geom;"""

    data = overpass_query(query, timeout=120)
    if not data:
        return []

    # Aggregate by name (combine segments of the same street)
    street_map = {}
    for el in data.get('elements', []):
        if el.get('type') != 'way':
            continue
        tags = el.get('tags', {})
        name = tags.get('name:ru') or tags.get('name', '')
        if not name or not CYRILLIC_RE.search(name):
            continue

        geom_pts = el.get('geometry', [])
        coords = [(pt['lat'], pt['lon']) for pt in geom_pts if 'lat' in pt]
        if len(coords) < 2:
            continue

        if name not in street_map:
            street_map[name] = {
                'osm_id': el['id'],
                'name': name,
                'segments': [coords],
                'highway': tags.get('highway', ''),
            }
        else:
            street_map[name]['segments'].append(coords)

    results = []
    for name, data_s in street_map.items():
        # Merge all segments into one polyline
        all_pts = []
        for seg in data_s['segments']:
            all_pts.extend(seg)

        if len(all_pts) < 2:
            continue

        geom_str = ';'.join(f"{lat},{lng}" for lat, lng in all_pts)
        mid = all_pts[len(all_pts) // 2]

        results.append({
            'osm_id': data_s['osm_id'],
            'name': name,
            'geometry': geom_str,
            'lat': round(mid[0], 6),
            'lng': round(mid[1], 6),
            'highway': data_s['highway'],
        })

    log.info(f"  Found {len(results)} unique streets")
    return results


# ─── Step 4: Upsert districts into DB ────────────────────────────────────────

def upsert_districts(conn, city_id: int, districts: list, label: str = "districts"):
    cur = conn.cursor()

    # Load existing
    cur.execute("SELECT id, name, slug, osm_id FROM districts WHERE city_id=%s", (city_id,))
    existing_by_osm = {}
    existing_by_name = {}
    existing_slugs = set()
    for did, dname, dslug, dosm in cur.fetchall():
        existing_slugs.add(dslug)
        existing_by_name[dname.lower()] = did
        if dosm:
            existing_by_osm[dosm] = did

    inserted = updated = 0

    for d in districts:
        osm_id = d.get('osm_id')
        name = d['name']
        geom = d.get('geometry', '')
        lat = d.get('lat')
        lng = d.get('lng')
        admin_level = d.get('admin_level')
        dtype = d.get('district_type', 'micro')
        place_type = d.get('place_type', 'suburb')
        poly_pts = d.get('polygon_pts', 0)
        area_m2 = d.get('area_m2', 0)

        if osm_id and osm_id in existing_by_osm:
            did = existing_by_osm[osm_id]
            cur.execute("""
                UPDATE districts SET geometry=%s, geometry_source='osm_polygon',
                    latitude=COALESCE(latitude, %s), longitude=COALESCE(longitude, %s),
                    admin_level=%s, place_type=%s, polygon_pts=%s, area_m2=%s,
                    updated_at=NOW()
                WHERE id=%s
            """, (geom, lat, lng, admin_level, place_type, poly_pts, area_m2, did))
            updated += 1
            continue

        if name.lower() in existing_by_name:
            did = existing_by_name[name.lower()]
            cur.execute("""
                UPDATE districts SET geometry=%s, geometry_source='osm_polygon',
                    latitude=COALESCE(latitude, %s), longitude=COALESCE(longitude, %s),
                    osm_id=COALESCE(osm_id, %s), admin_level=%s, place_type=%s,
                    polygon_pts=%s, area_m2=%s, updated_at=NOW()
                WHERE id=%s
            """, (geom, lat, lng, osm_id, admin_level, place_type, poly_pts, area_m2, did))
            updated += 1
            continue

        # Insert new
        slug = unique_slug(slugify(name), existing_slugs)
        existing_slugs.add(slug)
        cur.execute("""
            INSERT INTO districts (name, slug, city_id, district_type, place_type,
                latitude, longitude, osm_id, geometry, geometry_source,
                admin_level, polygon_pts, area_m2, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'osm_polygon',%s,%s,%s,NOW(),NOW())
            ON CONFLICT ON CONSTRAINT unique_district_slug_per_city DO NOTHING
        """, (name, slug, city_id, dtype, place_type, lat, lng,
              osm_id, geom, admin_level, poly_pts, area_m2))
        if cur.rowcount > 0:
            existing_by_name[name.lower()] = cur.lastrowid or 0
            inserted += 1

    conn.commit()
    log.info(f"  {label}: inserted={inserted}, updated={updated}")
    return inserted, updated


# ─── Step 5: Upsert streets ──────────────────────────────────────────────────

def upsert_streets(conn, city_id: int, streets: list):
    cur = conn.cursor()

    cur.execute("SELECT id, name, slug, osm_id FROM streets WHERE city_id=%s", (city_id,))
    existing_by_osm = {}
    existing_by_name = {}
    existing_slugs = set()
    for sid, sname, sslug, sosm in cur.fetchall():
        existing_slugs.add(sslug)
        existing_by_name[sname.lower()] = sid
        if sosm:
            existing_by_osm[sosm] = sid

    inserted = updated = 0

    for s in streets:
        osm_id = s.get('osm_id')
        name = s['name']
        geom = s.get('geometry', '')
        lat = s.get('lat')
        lng = s.get('lng')

        if osm_id and osm_id in existing_by_osm:
            sid = existing_by_osm[osm_id]
            cur.execute("""
                UPDATE streets SET geometry=%s, geometry_source='osm',
                    latitude=COALESCE(latitude, %s), longitude=COALESCE(longitude, %s),
                    updated_at=NOW()
                WHERE id=%s
            """, (geom, lat, lng, sid))
            updated += 1
            continue

        if name.lower() in existing_by_name:
            sid = existing_by_name[name.lower()]
            cur.execute("""
                UPDATE streets SET geometry=%s, geometry_source='osm',
                    latitude=COALESCE(latitude, %s), longitude=COALESCE(longitude, %s),
                    osm_id=COALESCE(osm_id, %s), updated_at=NOW()
                WHERE id=%s
            """, (geom, lat, lng, osm_id, sid))
            updated += 1
            continue

        slug = unique_slug(slugify(name), existing_slugs)
        existing_slugs.add(slug)
        cur.execute("""
            INSERT INTO streets (name, slug, city_id, latitude, longitude,
                osm_id, geometry, geometry_source, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'osm',NOW(),NOW())
            ON CONFLICT ON CONSTRAINT unique_street_slug_per_city DO NOTHING
        """, (name, slug, city_id, lat, lng, osm_id, geom))
        if cur.rowcount > 0:
            inserted += 1

    conn.commit()
    log.info(f"  Streets: inserted={inserted}, updated={updated}")
    return inserted, updated


# ─── Step 6: Link districts hierarchy (parent_district_id) ──────────────────

def link_district_hierarchy(conn, city_id: int):
    """
    For each microdistrict, find the admin okrug (admin_level set) that CONTAINS it
    and set parent_district_id.
    """
    cur = conn.cursor()
    log.info("Linking district hierarchy (parent_district_id)...")

    # Load all districts for this city
    cur.execute("""
        SELECT id, name, admin_level, latitude, longitude, geometry
        FROM districts WHERE city_id=%s
    """, (city_id,))
    all_districts = cur.fetchall()

    # Separate okrugs and microdistricts
    okrugs = [(r[0], r[1], r[2], r[3], r[4], parse_geom_str(r[5]))
              for r in all_districts if r[2] is not None]
    micros = [(r[0], r[1], r[2], r[3], r[4], parse_geom_str(r[5]))
              for r in all_districts if r[2] is None]

    if not okrugs:
        log.warning("  No admin okrugs found — skipping hierarchy")
        return 0

    updates = 0
    for mid, mname, _, mlat, mlng, mring in micros:
        if mlat is None or mlng is None:
            continue
        # Find which okrug contains this microdistrict's centroid
        for oid, oname, olevel, olat, olng, oring in okrugs:
            if len(oring) >= 3 and point_in_ring(float(mlat), float(mlng), oring):
                cur.execute(
                    "UPDATE districts SET parent_district_id=%s WHERE id=%s AND parent_district_id IS NULL",
                    (oid, mid)
                )
                if cur.rowcount > 0:
                    updates += 1
                break

    conn.commit()
    log.info(f"  Linked {updates} microdistricts to parent okrugs")
    return updates


# ─── Step 7: Property → district assignment using real polygons ──────────────

def assign_properties_polygon(conn, city_id: int):
    """
    Assign each property to its most specific (smallest) district that contains it.
    Uses real point-in-polygon with full OSM polygon data.
    """
    cur = conn.cursor()
    log.info(f"Assigning properties for city_id={city_id} using point-in-polygon...")

    # Load all districts with polygons, ordered by area (smallest first = most specific)
    cur.execute("""
        SELECT id, name, latitude, longitude, geometry, area_m2
        FROM districts
        WHERE city_id=%s AND geometry IS NOT NULL AND geometry != ''
        ORDER BY COALESCE(area_m2, 1e12) ASC
    """, (city_id,))
    districts = []
    for did, dname, dlat, dlng, dgeom, darea in cur.fetchall():
        ring = parse_geom_str(dgeom)
        if len(ring) >= 4:
            districts.append({
                'id': did, 'name': dname, 'ring': ring,
                'lat': dlat, 'lng': dlng, 'area': darea or 1e12,
            })

    log.info(f"  Loaded {len(districts)} district polygons")

    if not districts:
        log.warning("  No district polygons — falling back to nearest centroid")
        return _assign_nearest_centroid(conn, city_id)

    # Compute bbox for each district for fast pre-filtering
    for d in districts:
        lats = [p[0] for p in d['ring']]
        lngs = [p[1] for p in d['ring']]
        d['bbox'] = (min(lats), min(lngs), max(lats), max(lngs))

    # Load all active properties for this city in batches
    cur.execute("""
        SELECT id, latitude, longitude FROM properties
        WHERE is_active=true AND city_id=%s
          AND latitude IS NOT NULL AND longitude IS NOT NULL
    """, (city_id,))
    props = cur.fetchall()
    log.info(f"  Processing {len(props)} properties...")

    updates = []
    no_match = 0
    for pid, plat, plng in props:
        plat, plng = float(plat), float(plng)
        matched = None
        best_area = float('inf')

        for d in districts:
            bbox = d['bbox']
            # Quick bbox check first
            if not (bbox[0] <= plat <= bbox[2] and bbox[1] <= plng <= bbox[3]):
                continue
            # Real point-in-polygon
            if point_in_ring(plat, plng, d['ring']):
                if d['area'] < best_area:
                    best_area = d['area']
                    matched = d['id']

        if matched is not None:
            updates.append({'did': matched, 'pid': pid})
        else:
            no_match += 1

    log.info(f"  Matched: {len(updates)}, No match: {no_match}")

    # Bulk update in batches
    psycopg2.extras.execute_batch(
        cur,
        "UPDATE properties SET district_id=%s WHERE id=%s",
        [(u['did'], u['pid']) for u in updates],
        page_size=2000
    )
    conn.commit()

    # For unmatched properties, use nearest centroid
    if no_match > 0:
        log.info(f"  Assigning {no_match} unmatched properties via nearest centroid...")
        _assign_nearest_centroid_unmatched(conn, city_id)

    return len(updates)


def _assign_nearest_centroid(conn, city_id: int):
    """Fallback: assign all properties to nearest district centroid."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, latitude, longitude FROM districts WHERE city_id=%s AND latitude IS NOT NULL",
        (city_id,)
    )
    dists = [(r[0], float(r[1]), float(r[2])) for r in cur.fetchall()]
    if not dists:
        return 0

    cur.execute(
        "SELECT id, latitude, longitude FROM properties WHERE is_active=true AND city_id=%s AND latitude IS NOT NULL",
        (city_id,)
    )
    props = cur.fetchall()

    updates = []
    for pid, plat, plng in props:
        plat, plng = float(plat), float(plng)
        best = min(dists, key=lambda d: (plat-d[1])**2 + (plng-d[2])**2)
        updates.append((best[0], pid))

    psycopg2.extras.execute_batch(cur,
        "UPDATE properties SET district_id=%s WHERE id=%s", updates, page_size=2000)
    conn.commit()
    log.info(f"  Assigned {len(updates)} via nearest centroid")
    return len(updates)


def _assign_nearest_centroid_unmatched(conn, city_id: int):
    """Assign properties with no polygon match to nearest district centroid."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, latitude, longitude FROM districts WHERE city_id=%s AND latitude IS NOT NULL",
        (city_id,)
    )
    dists = [(r[0], float(r[1]), float(r[2])) for r in cur.fetchall()]
    if not dists:
        return

    cur.execute(
        "SELECT id, latitude, longitude FROM properties WHERE is_active=true AND city_id=%s AND latitude IS NOT NULL AND district_id IS NULL",
        (city_id,)
    )
    props = cur.fetchall()

    if not props:
        return

    updates = []
    for pid, plat, plng in props:
        plat, plng = float(plat), float(plng)
        best = min(dists, key=lambda d: (plat-d[1])**2 + (plng-d[2])**2)
        updates.append((best[0], pid))

    psycopg2.extras.execute_batch(cur,
        "UPDATE properties SET district_id=%s WHERE id=%s", updates, page_size=2000)
    conn.commit()
    log.info(f"  Assigned {len(updates)} unmatched via nearest centroid")


# ─── Step 8: Link streets to districts ────────────────────────────────────────

def link_streets_to_districts(conn, city_id: int):
    """Assign each street to the district whose polygon contains the street midpoint."""
    cur = conn.cursor()
    log.info(f"Linking streets to districts for city_id={city_id}...")

    cur.execute("""
        SELECT id, latitude, longitude, geometry FROM districts
        WHERE city_id=%s AND geometry IS NOT NULL AND geometry != ''
        ORDER BY COALESCE(area_m2, 1e12) ASC
    """, (city_id,))
    districts = []
    for did, dlat, dlng, dgeom in cur.fetchall():
        ring = parse_geom_str(dgeom)
        if len(ring) >= 4:
            lats = [p[0] for p in ring]
            lngs = [p[1] for p in ring]
            districts.append({
                'id': did, 'ring': ring,
                'bbox': (min(lats), min(lngs), max(lats), max(lngs)),
            })

    cur.execute(
        "SELECT id, latitude, longitude FROM streets WHERE city_id=%s AND latitude IS NOT NULL",
        (city_id,)
    )
    streets = cur.fetchall()
    log.info(f"  {len(streets)} streets, {len(districts)} district polygons")

    updates = []
    for sid, slat, slng in streets:
        slat, slng = float(slat), float(slng)
        matched = None
        for d in districts:
            b = d['bbox']
            if b[0] <= slat <= b[2] and b[1] <= slng <= b[3]:
                if point_in_ring(slat, slng, d['ring']):
                    matched = d['id']
                    break
        if matched:
            updates.append((matched, sid))

    psycopg2.extras.execute_batch(cur,
        "UPDATE streets SET district_id=%s WHERE id=%s", updates, page_size=2000)
    conn.commit()
    log.info(f"  Linked {len(updates)}/{len(streets)} streets to districts")
    return len(updates)


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_city(city_slug: str, args):
    cfg = CITY_CONFIG.get(city_slug)
    if not cfg:
        log.error(f"Unknown city: {city_slug}")
        sys.exit(1)

    city_id = cfg['city_id']
    conn = get_conn()

    try:
        if args.okrugs or args.all:
            log.info(f"\n{'='*60}")
            log.info(f"Step 1: Admin okrugs for {cfg['name']}")
            okrugs = fetch_admin_okrugs(city_slug, cfg)
            if okrugs:
                upsert_districts(conn, city_id, okrugs, "okrugs")
            else:
                log.warning("  No okrugs found")
            time.sleep(RATE_SLEEP)

        if args.districts or args.all:
            log.info(f"\n{'='*60}")
            log.info(f"Step 2: Microdistricts for {cfg['name']}")
            micros = fetch_microdistricts(city_slug, cfg)
            if micros:
                upsert_districts(conn, city_id, micros, "microdistricts")
            else:
                log.warning("  No microdistricts found")
            time.sleep(RATE_SLEEP)

        if args.streets or args.all:
            log.info(f"\n{'='*60}")
            log.info(f"Step 3: Streets for {cfg['name']}")
            streets = fetch_streets(city_slug, cfg)
            if streets:
                upsert_streets(conn, city_id, streets)
            time.sleep(RATE_SLEEP)

        if args.hierarchy or args.all:
            log.info(f"\n{'='*60}")
            log.info(f"Step 4: Linking hierarchy for {cfg['name']}")
            link_district_hierarchy(conn, city_id)

        if args.assign or args.all:
            log.info(f"\n{'='*60}")
            log.info(f"Step 5: Property assignment for {cfg['name']}")
            assign_properties_polygon(conn, city_id)

        if args.link_streets or args.all:
            log.info(f"\n{'='*60}")
            log.info(f"Step 6: Linking streets to districts for {cfg['name']}")
            link_streets_to_districts(conn, city_id)

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Full OSM geo enrichment for InBack")
    parser.add_argument("city", help="City slug (e.g. krasnodar) or 'all'")
    parser.add_argument("--okrugs",       action="store_true", help="Fetch admin okrugs")
    parser.add_argument("--districts",    action="store_true", help="Fetch microdistricts")
    parser.add_argument("--streets",      action="store_true", help="Fetch streets")
    parser.add_argument("--hierarchy",    action="store_true", help="Link district hierarchy")
    parser.add_argument("--assign",       action="store_true", help="Assign properties to districts")
    parser.add_argument("--link-streets", action="store_true", dest="link_streets",
                        help="Link streets to districts")
    parser.add_argument("--all",          action="store_true", help="Run all steps")
    args = parser.parse_args()

    # If no specific step chosen, run all
    if not any([args.okrugs, args.districts, args.streets,
                args.hierarchy, args.assign, args.link_streets, args.all]):
        args.all = True

    if args.city == "all":
        for slug in CITY_CONFIG:
            log.info(f"\n{'#'*70}")
            log.info(f"Processing city: {slug}")
            run_city(slug, args)
            time.sleep(RATE_SLEEP * 3)
    else:
        run_city(args.city, args)

    log.info("\n✅ Done!")


if __name__ == "__main__":
    main()
