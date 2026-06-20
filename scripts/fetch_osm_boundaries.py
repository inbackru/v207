#!/usr/bin/env python3
"""
scripts/fetch_osm_boundaries.py

Fetch real administrative district boundaries and street data from OpenStreetMap
via the public Overpass API for all 8 cities in the Krasnodar region.

Usage:
    python scripts/fetch_osm_boundaries.py --city krasnodar
    python scripts/fetch_osm_boundaries.py --city sochi
    python scripts/fetch_osm_boundaries.py --all
    python scripts/fetch_osm_boundaries.py --all --streets
    python scripts/fetch_osm_boundaries.py --city krasnodar --enrich-only

Data format stored in DB:
  districts.geometry  : "lat,lng;lat,lng;..." (polygon ring)
  streets.geometry    : "lat,lng;lat,lng;..."  (polyline)
"""

import os
import sys
import re
import time
import logging
import argparse
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
OVERPASS_TIMEOUT = 120
REQUEST_DELAY = 1.5
MAX_RETRIES = 3

CITY_CONFIGS = {
    'krasnodar': {
        'id': 1,
        'name': 'Краснодар',
        'bbox': (44.82, 38.60, 45.25, 39.35),
        'osm_city_id': 396180,
    },
    'sochi': {
        'id': 2,
        'name': 'Сочи',
        'bbox': (43.30, 39.55, 44.05, 40.35),
        'osm_city_id': 366455,
    },
    'anapa': {
        'id': 3,
        'name': 'Анапа',
        'bbox': (44.70, 37.05, 45.12, 37.75),
        'osm_city_id': None,
    },
    'gelendzhik': {
        'id': 4,
        'name': 'Геленджик',
        'bbox': (44.40, 37.78, 44.82, 38.45),
        'osm_city_id': None,
    },
    'novorossiysk': {
        'id': 5,
        'name': 'Новороссийск',
        'bbox': (44.58, 37.50, 44.95, 38.05),
        'osm_city_id': None,
    },
    'armavir': {
        'id': 6,
        'name': 'Армавир',
        'bbox': (44.85, 40.90, 45.12, 41.35),
        'osm_city_id': None,
    },
    'tuapse': {
        'id': 7,
        'name': 'Туапсе',
        'bbox': (43.92, 38.85, 44.28, 39.30),
        'osm_city_id': None,
    },
    'maykop': {
        'id': 8,
        'name': 'Майкоп',
        'bbox': (44.47, 39.90, 44.78, 40.35),
        'osm_city_id': None,
    },
    'kursk': {
        'id': 9,
        'name': 'Курск',
        'bbox': (51.68, 36.08, 51.82, 36.32),
        'osm_city_id': None,
    },
}

RU_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def transliterate(text):
    """Convert Russian text to URL-safe slug."""
    result = []
    for ch in text.lower():
        result.append(RU_TRANSLIT.get(ch, ch))
    slug = ''.join(result)
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


def make_unique_slug(base_slug, existing_slugs):
    """Ensure slug is unique by appending a counter."""
    if base_slug not in existing_slugs:
        return base_slug
    counter = 2
    while f"{base_slug}-{counter}" in existing_slugs:
        counter += 1
    return f"{base_slug}-{counter}"


def overpass_request(query, retries=MAX_RETRIES):
    """POST to Overpass API with retry and backoff."""
    for attempt in range(retries):
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={'data': query},
                timeout=OVERPASS_TIMEOUT,
                headers={'User-Agent': 'InBackRealEstate/1.0 (krasnodar-realestate)'}
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = 10 * (attempt + 1)
                log.warning(f"  429 Too Many Requests — waiting {wait}s")
                time.sleep(wait)
            else:
                log.warning(f"  HTTP {resp.status_code} on attempt {attempt + 1}")
                time.sleep(3 * (attempt + 1))
        except requests.exceptions.Timeout:
            log.warning(f"  Timeout on attempt {attempt + 1}/{retries}")
            time.sleep(5 * (attempt + 1))
        except Exception as e:
            log.warning(f"  Request error on attempt {attempt + 1}: {e}")
            time.sleep(3)
    log.error("  All Overpass retries exhausted")
    return None


def parse_way_geometry(way_id, nodes_map):
    """Build lat,lng;... string from a way's node references."""
    if way_id not in nodes_map:
        return None
    coords = []
    for nd in nodes_map[way_id]:
        n = nd
        if isinstance(n, dict) and 'lat' in n:
            coords.append(f"{n['lat']},{n['lon']}")
    return ';'.join(coords) if len(coords) >= 3 else None


def compute_centroid(geometry_str):
    """Compute centroid lat,lng from a geometry string."""
    try:
        points = []
        for pair in geometry_str.split(';'):
            parts = pair.strip().split(',')
            if len(parts) >= 2:
                points.append((float(parts[0]), float(parts[1])))
        if not points:
            return None, None
        lat = sum(p[0] for p in points) / len(points)
        lng = sum(p[1] for p in points) / len(points)
        return round(lat, 6), round(lng, 6)
    except Exception:
        return None, None


def parse_relation_polygon(relation_id, ways_geom, members):
    """
    Assemble outer rings of an OSM relation into a polygon string.
    Returns the largest outer ring as lat,lng;... string.
    """
    outer_ways = [m['ref'] for m in members if m.get('type') == 'way' and m.get('role') == 'outer']
    if not outer_ways:
        outer_ways = [m['ref'] for m in members if m.get('type') == 'way']

    rings = []
    for way_ref in outer_ways:
        coords = ways_geom.get(way_ref)
        if coords and len(coords) >= 3:
            rings.append(coords)

    if not rings:
        return None

    largest = max(rings, key=lambda r: len(r))
    return ';'.join(f"{lat},{lng}" for lat, lng in largest)


def fetch_districts_for_city(city_slug, city_config):
    """
    Fetch district/neighbourhood polygons from Overpass for a city.
    Returns list of dicts: {osm_id, name, geometry, lat, lng, district_type}
    """
    lat_min, lon_min, lat_max, lon_max = city_config['bbox']
    bbox_str = f"{lat_min},{lon_min},{lat_max},{lon_max}"

    log.info(f"  Querying Overpass for districts in {city_config['name']}...")

    query = f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  relation["boundary"="administrative"]["admin_level"~"^(7|8|9|10)$"](bbox:{bbox_str});
  way["place"~"^(suburb|quarter|neighbourhood|residential)$"]["name"](bbox:{bbox_str});
  relation["place"~"^(suburb|quarter|neighbourhood)$"]["name"](bbox:{bbox_str});
);
out body;
>;
out skel qt;
"""

    data = overpass_request(query)
    if not data:
        return []

    elements = data.get('elements', [])

    node_coords = {}
    way_nodes = {}
    way_geom = {}
    relations = []
    ways_with_place = []

    for el in elements:
        etype = el.get('type')
        if etype == 'node':
            node_coords[el['id']] = (el.get('lat', 0), el.get('lon', 0))
        elif etype == 'way':
            way_nodes[el['id']] = el.get('nodes', [])
            if el.get('tags'):
                ways_with_place.append(el)
        elif etype == 'relation':
            relations.append(el)

    for wid, nids in way_nodes.items():
        coords = []
        for nid in nids:
            if nid in node_coords:
                coords.append(node_coords[nid])
        if coords:
            way_geom[wid] = coords

    results = []

    CYRILLIC_RE = re.compile(r'[а-яёА-ЯЁ]')

    for rel in relations:
        tags = rel.get('tags', {})
        name = tags.get('name:ru') or tags.get('name') or ''
        if not name or len(name) < 2:
            continue
        # Skip non-Russian names — avoids importing Arabic/Turkish/etc. OSM data
        if not CYRILLIC_RE.search(name):
            continue

        admin_level = tags.get('admin_level', '')
        place_tag = tags.get('place', '')

        if admin_level in ('8',) and not place_tag:
            continue

        members = rel.get('members', [])
        geom = parse_relation_polygon(rel['id'], way_geom, members)
        if not geom:
            continue

        lat, lng = compute_centroid(geom)
        dtype = 'admin' if admin_level in ('7', '8', '9') else 'micro'

        results.append({
            'osm_id': rel['id'],
            'name': name,
            'geometry': geom,
            'lat': lat,
            'lng': lng,
            'district_type': dtype,
        })

    for way in ways_with_place:
        tags = way.get('tags', {})
        name = tags.get('name:ru') or tags.get('name') or ''
        if not name or len(name) < 2:
            continue
        if not CYRILLIC_RE.search(name):
            continue
        if way['id'] not in way_geom:
            continue
        coords = way_geom[way['id']]
        geom = ';'.join(f"{lat},{lng}" for lat, lng in coords)
        if len(coords) < 3:
            continue
        lat, lng = compute_centroid(geom)
        results.append({
            'osm_id': way['id'],
            'name': name,
            'geometry': geom,
            'lat': lat,
            'lng': lng,
            'district_type': 'micro',
        })

    log.info(f"  Found {len(results)} district candidates from Overpass")
    return results


def fetch_streets_for_city(city_slug, city_config, limit=500):
    """
    Fetch named streets from Overpass for a city.
    Returns list of dicts: {osm_id, name, geometry, lat, lng, street_type}
    """
    lat_min, lon_min, lat_max, lon_max = city_config['bbox']
    bbox_str = f"{lat_min},{lon_min},{lat_max},{lon_max}"

    log.info(f"  Querying Overpass for streets in {city_config['name']}...")

    query = f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
way["highway"~"^(primary|secondary|tertiary|residential|unclassified|living_street)$"]["name"](bbox:{bbox_str});
out body;
>;
out skel qt;
"""

    data = overpass_request(query)
    if not data:
        return []

    elements = data.get('elements', [])
    node_coords = {}
    ways = []

    for el in elements:
        if el['type'] == 'node':
            node_coords[el['id']] = (el.get('lat', 0), el.get('lon', 0))
        elif el['type'] == 'way':
            ways.append(el)

    street_by_name = {}
    for way in ways:
        tags = way.get('tags', {})
        name = tags.get('name:ru') or tags.get('name') or ''
        if not name or len(name) < 2:
            continue

        nids = way.get('nodes', [])
        coords = [node_coords[n] for n in nids if n in node_coords]
        if len(coords) < 2:
            continue

        if name not in street_by_name:
            street_by_name[name] = {
                'osm_id': way['id'],
                'name': name,
                'coords': coords,
                'highway': tags.get('highway', ''),
            }
        else:
            existing = street_by_name[name]['coords']
            if len(coords) > len(existing):
                street_by_name[name]['coords'] = coords
                street_by_name[name]['osm_id'] = way['id']

    results = []
    for name, data_s in list(street_by_name.items())[:limit]:
        coords = data_s['coords']
        geom = ';'.join(f"{lat},{lng}" for lat, lng in coords)
        mid_idx = len(coords) // 2
        lat = coords[mid_idx][0]
        lng = coords[mid_idx][1]

        highway = data_s['highway']
        if highway in ('primary', 'secondary'):
            stype = 'проспект'
        elif highway == 'residential':
            stype = 'улица'
        else:
            stype = 'улица'

        results.append({
            'osm_id': data_s['osm_id'],
            'name': name,
            'geometry': geom,
            'lat': round(lat, 6),
            'lng': round(lng, 6),
            'street_type': stype,
        })

    log.info(f"  Found {len(results)} unique streets from Overpass")
    return results


def upsert_districts(session, city_id, city_name, districts_data, text):
    """Upsert districts into DB. Returns (inserted, updated) counts."""
    from sqlalchemy import func

    existing_by_osm = {}
    existing_by_name = {}
    existing_slugs = set()

    rows = session.execute(text(
        "SELECT id, name, slug, osm_id FROM districts WHERE city_id = :cid"
    ), {'cid': city_id}).fetchall()

    for row in rows:
        existing_slugs.add(row.slug)
        existing_by_name[row.name.lower()] = row.id
        if row.osm_id:
            existing_by_osm[row.osm_id] = row.id

    inserted = 0
    updated = 0

    for dist in districts_data:
        osm_id = dist['osm_id']
        name = dist['name']
        geometry = dist['geometry']
        lat = dist['lat']
        lng = dist['lng']
        dtype = dist.get('district_type', 'micro')

        if osm_id in existing_by_osm:
            did = existing_by_osm[osm_id]
            session.execute(text("""
                UPDATE districts
                SET geometry = :geom, geometry_source = 'osm',
                    latitude = COALESCE(latitude, :lat),
                    longitude = COALESCE(longitude, :lng),
                    updated_at = NOW()
                WHERE id = :did
            """), {'geom': geometry, 'lat': lat, 'lng': lng, 'did': did})
            updated += 1
            continue

        if name.lower() in existing_by_name:
            did = existing_by_name[name.lower()]
            session.execute(text("""
                UPDATE districts
                SET geometry = :geom, geometry_source = 'osm',
                    osm_id = :oid,
                    latitude = COALESCE(latitude, :lat),
                    longitude = COALESCE(longitude, :lng),
                    updated_at = NOW()
                WHERE id = :did
            """), {'geom': geometry, 'oid': osm_id, 'lat': lat, 'lng': lng, 'did': did})
            updated += 1
            existing_by_osm[osm_id] = did
            continue

        slug = make_unique_slug(transliterate(name), existing_slugs)
        existing_slugs.add(slug)

        session.execute(text("""
            INSERT INTO districts
                (name, slug, city_id, geometry, geometry_source, osm_id,
                 latitude, longitude, district_type, created_at, updated_at)
            VALUES
                (:name, :slug, :cid, :geom, 'osm', :oid,
                 :lat, :lng, :dtype, NOW(), NOW())
            ON CONFLICT (city_id, slug) DO UPDATE SET
                geometry = EXCLUDED.geometry,
                geometry_source = 'osm',
                osm_id = EXCLUDED.osm_id,
                latitude = COALESCE(districts.latitude, EXCLUDED.latitude),
                longitude = COALESCE(districts.longitude, EXCLUDED.longitude),
                updated_at = NOW()
        """), {
            'name': name, 'slug': slug, 'cid': city_id, 'geom': geometry,
            'oid': osm_id, 'lat': lat, 'lng': lng, 'dtype': dtype
        })
        existing_by_osm[osm_id] = None
        existing_by_name[name.lower()] = None
        inserted += 1

    session.commit()
    return inserted, updated


def upsert_streets(session, city_id, streets_data, text):
    """Upsert streets into DB. Returns (inserted, updated) counts."""
    existing_by_osm = {}
    existing_by_name = {}
    existing_slugs = set()

    rows = session.execute(text(
        "SELECT id, name, slug, osm_id FROM streets WHERE city_id = :cid"
    ), {'cid': city_id}).fetchall()

    for row in rows:
        existing_slugs.add(row.slug)
        existing_by_name[row.name.lower()] = row.id
        if row.osm_id:
            existing_by_osm[row.osm_id] = row.id

    inserted = 0
    updated = 0

    for street in streets_data:
        osm_id = street['osm_id']
        name = street['name']
        geometry = street['geometry']
        lat = street['lat']
        lng = street['lng']
        stype = street.get('street_type', 'улица')

        if osm_id in existing_by_osm:
            did = existing_by_osm[osm_id]
            session.execute(text("""
                UPDATE streets
                SET geometry = :geom, geometry_source = 'osm',
                    latitude = COALESCE(latitude, :lat),
                    longitude = COALESCE(longitude, :lng),
                    updated_at = NOW()
                WHERE id = :did
            """), {'geom': geometry, 'lat': lat, 'lng': lng, 'did': did})
            updated += 1
            continue

        if name.lower() in existing_by_name:
            did = existing_by_name[name.lower()]
            session.execute(text("""
                UPDATE streets
                SET geometry = :geom, geometry_source = 'osm',
                    osm_id = :oid,
                    latitude = COALESCE(latitude, :lat),
                    longitude = COALESCE(longitude, :lng),
                    updated_at = NOW()
                WHERE id = :did
            """), {'geom': geometry, 'oid': osm_id, 'lat': lat, 'lng': lng, 'did': did})
            updated += 1
            existing_by_osm[osm_id] = did
            continue

        slug_base = transliterate(name)
        slug = make_unique_slug(slug_base, existing_slugs)
        existing_slugs.add(slug)

        session.execute(text("""
            INSERT INTO streets
                (name, slug, city_id, geometry, geometry_source, osm_id,
                 latitude, longitude, street_type, created_at, updated_at)
            VALUES
                (:name, :slug, :cid, :geom, 'osm', :oid,
                 :lat, :lng, :stype, NOW(), NOW())
            ON CONFLICT (city_id, slug) DO UPDATE SET
                geometry = EXCLUDED.geometry,
                geometry_source = 'osm',
                osm_id = EXCLUDED.osm_id,
                latitude = COALESCE(streets.latitude, EXCLUDED.latitude),
                longitude = COALESCE(streets.longitude, EXCLUDED.longitude),
                updated_at = NOW()
        """), {
            'name': name, 'slug': slug, 'cid': city_id, 'geom': geometry,
            'oid': osm_id, 'lat': lat, 'lng': lng, 'stype': stype
        })
        existing_by_osm[osm_id] = None
        existing_by_name[name.lower()] = None
        inserted += 1

    session.commit()
    return inserted, updated


def process_city(city_slug, include_streets=True, enrich_only=False):
    """Process a single city: fetch + upsert districts and streets."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)

    city_config = CITY_CONFIGS.get(city_slug)
    if not city_config:
        log.error(f"Unknown city slug: {city_slug}")
        return

    city_id = city_config['id']
    city_name = city_config['name']

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        log.info(f"\n{'='*60}")
        log.info(f"Processing city: {city_name} (id={city_id})")
        log.info(f"{'='*60}")

        districts_data = fetch_districts_for_city(city_slug, city_config)
        time.sleep(REQUEST_DELAY)

        if districts_data:
            ins, upd = upsert_districts(session, city_id, city_name, districts_data, text)
            log.info(f"  Districts: {ins} inserted, {upd} updated")
        else:
            log.warning(f"  No districts found for {city_name}")

        if include_streets and not enrich_only:
            streets_check = session.execute(text(
                "SELECT COUNT(*) FROM streets WHERE city_id = :cid"
            ), {'cid': city_id}).scalar()

            if city_slug == 'krasnodar':
                log.info(f"  Skipping streets for Krasnodar (already has {streets_check} streets)")
            else:
                log.info(f"  Fetching streets for {city_name} (currently {streets_check} streets)...")
                time.sleep(REQUEST_DELAY)
                streets_data = fetch_streets_for_city(city_slug, city_config)
                if streets_data:
                    ins_s, upd_s = upsert_streets(session, city_id, streets_data, text)
                    log.info(f"  Streets: {ins_s} inserted, {upd_s} updated")
                else:
                    log.warning(f"  No streets found for {city_name}")

        dist_count = session.execute(text(
            "SELECT COUNT(*) FROM districts WHERE city_id = :cid"
        ), {'cid': city_id}).scalar()
        street_count = session.execute(text(
            "SELECT COUNT(*) FROM streets WHERE city_id = :cid"
        ), {'cid': city_id}).scalar()
        log.info(f"  Final: {dist_count} districts, {street_count} streets")

    except Exception as e:
        session.rollback()
        log.error(f"Error processing {city_name}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


def validate_results():
    """Print summary of district/street counts per city."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    database_url = os.environ.get('DATABASE_URL')
    engine = create_engine(database_url)
    session = sessionmaker(bind=engine)()

    try:
        print("\n" + "=" * 60)
        print("VALIDATION — Districts & Streets per city:")
        print("=" * 60)
        rows = session.execute(text("""
            SELECT c.name, c.id,
                   COUNT(DISTINCT d.id) AS districts,
                   COUNT(DISTINCT s.id) AS streets
            FROM cities c
            LEFT JOIN districts d ON d.city_id = c.id
            LEFT JOIN streets s ON s.city_id = c.id
            GROUP BY c.id, c.name
            ORDER BY c.id
        """)).fetchall()
        for r in rows:
            status = "✅" if r.districts > 0 else "❌"
            print(f"  {status} {r.name:<16} districts={r.districts:<4} streets={r.streets}")
        print("=" * 60)
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description='Fetch OSM district/street boundaries for Krasnodar region cities'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--city', choices=list(CITY_CONFIGS.keys()),
                       help='Process a single city by slug')
    group.add_argument('--all', action='store_true', help='Process all 8 cities')
    parser.add_argument('--streets', action='store_true', default=True,
                        help='Also fetch streets (default: True)')
    parser.add_argument('--no-streets', action='store_true',
                        help='Skip street fetching')
    parser.add_argument('--enrich-only', action='store_true',
                        help='Only enrich existing districts, do not insert new ones')
    parser.add_argument('--validate', action='store_true',
                        help='Show validation summary after processing')
    args = parser.parse_args()

    include_streets = not args.no_streets

    if args.all:
        cities = list(CITY_CONFIGS.keys())
    else:
        cities = [args.city]

    for i, city_slug in enumerate(cities):
        process_city(
            city_slug,
            include_streets=include_streets,
            enrich_only=args.enrich_only
        )
        if i < len(cities) - 1:
            log.info(f"  Waiting {REQUEST_DELAY * 2}s before next city...")
            time.sleep(REQUEST_DELAY * 2)

    if args.validate or args.all:
        validate_results()


if __name__ == '__main__':
    main()
