#!/usr/bin/env python3
"""
Task 2: Enrich Krasnodar microrayons with real OSM polygons.
- Processes one relation at a time with progress file (safe to restart)
- Saves progress after each success
"""
import os, json, time, re, requests, psycopg2

DB = os.environ['DATABASE_URL']
OVERPASS = "https://overpass-api.de/api/interpreter"
HEADERS = {'User-Agent': 'InBackGeoEnrich/1.0 (inback.ru)'}
PROGRESS_FILE = "/tmp/geo_t2_progress.json"

def overpass_get(q, retries=3):
    for i in range(retries):
        try:
            r = requests.get(OVERPASS, params={"data": q}, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                return r.json()
            elif r.status_code in (429, 504):
                wait = 20 * (i + 1)
                print(f"    HTTP {r.status_code}, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    HTTP {r.status_code}")
        except Exception as e:
            print(f"    Error: {e}")
        time.sleep(5 * (i + 1))
    return None

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

def fetch_single_polygon(osm_id, osm_type):
    if osm_type == 'relation':
        q = f"[out:json][timeout:55];\nrelation({osm_id});\n(._;>;);\nout body;\n"
    else:
        q = f"[out:json][timeout:55];\nway({osm_id});\n(._;>;);\nout body;\n"

    data = overpass_get(q)
    if not data:
        return None

    nodes, ways, rel_ways = {}, {}, []
    for el in data.get('elements', []):
        if el['type'] == 'node':
            nodes[el['id']] = (el['lat'], el['lon'])
        elif el['type'] == 'way':
            ways[el['id']] = el.get('nodes', [])
        elif el['type'] == 'relation' and el['id'] == osm_id:
            for m in el.get('members', []):
                if m['type'] == 'way' and m.get('role', 'outer') in ('outer', ''):
                    rel_ways.append(m['ref'])

    if osm_type == 'way':
        way_nodes = list(ways.values())[0] if ways else []
        coords = [f"{nodes[n][0]},{nodes[n][1]}" for n in way_nodes if n in nodes]
        return ";".join(coords) if len(coords) > 3 else None

    if not rel_ways:
        rel_ways = list(ways.keys())
    ways_nodes = [ways[wid] for wid in rel_ways if wid in ways]
    ring = stitch_ways(ways_nodes)
    coords = [f"{nodes[n][0]},{nodes[n][1]}" for n in ring if n in nodes]
    return ";".join(coords) if len(coords) > 3 else None

def transliterate(name):
    t = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
         'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
         'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
         'щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',' ':'-'}
    return re.sub(r'-+', '-', ''.join(t.get(c, c) for c in name.lower())).strip('-')

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {'done': []}

def save_progress(p):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(p, f)

def main():
    progress = load_progress()
    done_ids = set(progress['done'])

    # Step 1: Fetch place list (fast query, no geometry)
    print("Fetching microrayon list from Overpass...")
    q = """
[out:json][timeout:60];
(
  relation["place"~"suburb|quarter"]["name"](45.0,38.7,45.2,39.2);
  way["place"~"suburb|quarter"]["name"](45.0,38.7,45.2,39.2);
  relation["landuse"="residential"]["name"]["name"!~"^$"](45.0,38.7,45.2,39.2);
);
out body;
"""
    data = overpass_get(q)
    if not data:
        print("ERROR: Could not fetch place list")
        return

    places = []
    for el in data.get('elements', []):
        name = el.get('tags', {}).get('name', '').strip()
        if name and len(name) > 1:
            places.append({
                'osm_id': el['id'],
                'osm_type': el['type'],
                'name': name,
            })

    print(f"Found {len(places)} places. Already done: {len(done_ids)}")

    # Step 2: Load DB districts for matching
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, name, osm_id FROM districts WHERE city_id=1")
    db_rows = cur.fetchall()
    db_by_name = {r[1].lower(): r[0] for r in db_rows}
    db_by_osm = {r[2]: r[0] for r in db_rows if r[2]}

    updated = inserted = skipped = 0

    # Step 3: Process one at a time
    for place in places:
        osm_id = place['osm_id']
        name = place['name']
        osm_type = place['osm_type']

        if osm_id in done_ids:
            skipped += 1
            continue

        print(f"  [{osm_id}] {name} ({osm_type})... ", end='', flush=True)

        geom = fetch_single_polygon(osm_id, osm_type)

        if not geom or len(geom.split(';')) < 4:
            print("no geom")
            done_ids.add(osm_id)
            save_progress({'done': list(done_ids)})
            time.sleep(2)
            continue

        pts = len(geom.split(';'))
        print(f"{pts} pts")

        # Compute centroid
        try:
            pairs = [p.split(',') for p in geom.split(';')]
            clat = sum(float(p[0]) for p in pairs) / len(pairs)
            clon = sum(float(p[1]) for p in pairs) / len(pairs)
        except:
            clat, clon = 45.04, 38.97

        dist_id = db_by_osm.get(osm_id) or db_by_name.get(name.lower())

        if dist_id:
            cur.execute("""
                UPDATE districts SET geometry=%s, geometry_source='osm',
                osm_id=%s, district_type=COALESCE(NULLIF(district_type,''),'microrayon'),
                latitude=COALESCE(latitude,%s), longitude=COALESCE(longitude,%s),
                updated_at=NOW() WHERE id=%s
            """, (geom, osm_id, clat, clon, dist_id))
            updated += 1
        else:
            slug = transliterate(name)[:80] or f"mr-{osm_id}"
            try:
                cur.execute("""
                    INSERT INTO districts (name, slug, city_id, district_type, geometry,
                    geometry_source, osm_id, latitude, longitude, created_at, updated_at)
                    VALUES (%s, %s, 1, 'microrayon', %s, 'osm', %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (city_id, slug) DO UPDATE SET
                    geometry=EXCLUDED.geometry, osm_id=EXCLUDED.osm_id,
                    geometry_source='osm', district_type='microrayon',
                    latitude=COALESCE(districts.latitude,EXCLUDED.latitude),
                    longitude=COALESCE(districts.longitude,EXCLUDED.longitude)
                """, (name, slug, geom, osm_id, clat, clon))
                db_by_name[name.lower()] = True
                inserted += 1
            except Exception as e:
                print(f"    Insert error: {e}")
                conn.rollback()
                done_ids.add(osm_id)
                save_progress({'done': list(done_ids)})
                time.sleep(2)
                continue

        conn.commit()
        done_ids.add(osm_id)
        save_progress({'done': list(done_ids)})
        time.sleep(2.5)  # Respect Overpass rate limits

    cur.close()
    conn.close()
    print(f"\nTask 2 done: {updated} updated, {inserted} inserted, {skipped} skipped.")

if __name__ == '__main__':
    main()
