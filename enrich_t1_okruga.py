#!/usr/bin/env python3
"""
Task 1: Enrich administrative okruga of Krasnodar with real OSM polygons.
Uses Nominatim to find OSM IDs, then Overpass for geometry.
"""
import os, time, requests, psycopg2

DB = os.environ['DATABASE_URL']
OVERPASS = "https://overpass-api.de/api/interpreter"
HEADERS = {'User-Agent': 'InBackGeoEnrich/1.0 (inback.ru)'}

def overpass_get(q, retries=3):
    for i in range(retries):
        try:
            r = requests.get(OVERPASS, params={"data": q}, headers=HEADERS, timeout=90)
            if r.status_code == 200:
                return r.json()
            print(f"  HTTP {r.status_code}")
        except Exception as e:
            print(f"  Attempt {i+1} failed: {e}")
        time.sleep(6 * (i + 1))
    return None

def nominatim_search(query):
    r = requests.get('https://nominatim.openstreetmap.org/search', params={
        'q': query, 'format': 'json', 'limit': 3, 'countrycodes': 'ru'
    }, headers=HEADERS, timeout=15)
    if r.status_code == 200:
        return r.json()
    return []

def stitch_ways(ways_nodes):
    if not ways_nodes:
        return []
    remaining = [list(w) for w in ways_nodes]
    ring = list(remaining.pop(0))
    for _ in range(len(remaining) * 4 + 10):
        if not remaining:
            break
        matched = False
        for i, way in enumerate(remaining):
            if ring[-1] == way[0]:
                ring.extend(way[1:]); remaining.pop(i); matched = True; break
            elif ring[-1] == way[-1]:
                ring.extend(reversed(way[:-1])); remaining.pop(i); matched = True; break
            elif ring[0] == way[-1]:
                ring = way + ring[1:]; remaining.pop(i); matched = True; break
            elif ring[0] == way[0]:
                ring = list(reversed(way)) + ring[1:]; remaining.pop(i); matched = True; break
        if not matched:
            ring.extend(remaining.pop(0))
    return ring

def fetch_relation_polygon(rel_id):
    q = f"[out:json][timeout:90];\nrelation({rel_id});\n(._;>;);\nout body;\n"
    data = overpass_get(q)
    if not data:
        return None

    nodes, ways, rel_ways = {}, {}, []
    for el in data.get('elements', []):
        if el['type'] == 'node':
            nodes[el['id']] = (el['lat'], el['lon'])
        elif el['type'] == 'way':
            ways[el['id']] = el.get('nodes', [])
        elif el['type'] == 'relation':
            for m in el.get('members', []):
                if m['type'] == 'way' and m.get('role', 'outer') in ('outer', ''):
                    rel_ways.append(m['ref'])

    if not rel_ways:
        rel_ways = list(ways.keys())

    ways_nodes = [ways[wid] for wid in rel_ways if wid in ways]
    ring = stitch_ways(ways_nodes)

    coords = [f"{nodes[n][0]},{nodes[n][1]}" for n in ring if n in nodes]
    return ";".join(coords) if len(coords) > 3 else None

KRASNODAR_OKRUGA = [
    ("Центральный округ", "Центральный", ["центральный"]),
    ("Прикубанский округ Краснодар", "Прикубанский", ["прикубанский"]),
    ("Карасунский округ Краснодар", "Карасунский", ["карасунский"]),
    ("Западный округ Краснодар", "Западный округ", ["западный округ", "западный"]),
]

def main():
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    updated = 0

    for nominatim_q, db_name, name_variants in KRASNODAR_OKRUGA:
        print(f"\n--- Processing: {db_name} ---")

        # Find in DB
        dist_id = None
        for variant in name_variants:
            cur.execute("SELECT id FROM districts WHERE city_id=1 AND LOWER(name) LIKE %s LIMIT 1",
                        (f"%{variant}%",))
            row = cur.fetchone()
            if row:
                dist_id = row[0]
                break

        # Find OSM relation ID via Nominatim
        results = nominatim_search(nominatim_q)
        rel_id = None
        for res in results:
            if res.get('osm_type') == 'relation':
                rel_id = int(res['osm_id'])
                print(f"  Found OSM relation {rel_id}: {res.get('display_name','')[:80]}")
                break

        if not rel_id:
            print(f"  WARN: No OSM relation found for '{nominatim_q}'")
            continue

        time.sleep(1.5)  # Nominatim rate limit

        print(f"  Fetching polygon (rel={rel_id})...")
        geom = fetch_relation_polygon(rel_id)

        if not geom:
            print(f"  WARN: No geometry returned")
            continue

        pts = len(geom.split(';'))
        print(f"  Got {pts} polygon points")

        if dist_id:
            cur.execute("""
                UPDATE districts SET geometry=%s, geometry_source='osm',
                osm_id=%s, district_type='okrug', updated_at=NOW()
                WHERE id=%s
            """, (geom, rel_id, dist_id))
            print(f"  Updated district id={dist_id}")
        else:
            slug = f"okrug-{db_name.lower().replace(' ', '-')}"
            try:
                pairs = [p.split(',') for p in geom.split(';')]
                clat = sum(float(p[0]) for p in pairs) / len(pairs)
                clon = sum(float(p[1]) for p in pairs) / len(pairs)
            except:
                clat, clon = 45.04, 38.97
            cur.execute("""
                INSERT INTO districts (name, slug, city_id, district_type, geometry,
                geometry_source, osm_id, latitude, longitude, created_at, updated_at)
                VALUES (%s, %s, 1, 'okrug', %s, 'osm', %s, %s, %s, NOW(), NOW())
                ON CONFLICT (city_id, slug) DO UPDATE SET
                geometry=EXCLUDED.geometry, osm_id=EXCLUDED.osm_id,
                geometry_source='osm', district_type='okrug'
            """, (db_name, slug, geom, rel_id, clat, clon))
            print(f"  Inserted new okrug '{db_name}'")

        conn.commit()
        updated += 1
        time.sleep(3)

    # Also fetch Krasnodar city boundary
    print("\n--- Processing: City boundary (Краснодар) ---")
    results = nominatim_search("Краснодар городской округ")
    for res in results:
        if res.get('osm_type') == 'relation':
            rel_id = int(res['osm_id'])
            print(f"  City relation: {rel_id}")
            time.sleep(1.5)
            geom = fetch_relation_polygon(rel_id)
            if geom:
                pts = len(geom.split(';'))
                print(f"  City boundary: {pts} points")
                cur.execute("""
                    UPDATE districts SET geometry=%s, geometry_source='osm', osm_id=%s, updated_at=NOW()
                    WHERE city_id=1 AND name ILIKE %s
                """, (geom, rel_id, '%краснодарский край%'))
                conn.commit()
            break

    cur.close()
    conn.close()
    print(f"\nTask 1 done: {updated} okruga updated.")

if __name__ == '__main__':
    main()
