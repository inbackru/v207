#!/usr/bin/env python3
"""
enrich_city_geo.py — Масштабируемый скрипт гео-обогащения для любого города.
Использование: python3 enrich_city_geo.py --city_id=2 --city_name="Сочи"

Шаги:
  1. Находит административные округа (admin_level 9-10) в bbox города через Overpass
  2. Загружает полигоны округов из OSM
  3. Находит микрорайоны (place=suburb/neighbourhood) в bbox города
  4. Загружает полигоны микрорайонов
  5. Запускает PIP: назначает каждый объект недвижимости наиболее точному району
"""
import argparse, os, sys, time, psycopg2, requests

DB = os.environ['DATABASE_URL']
OVERPASS = 'https://overpass-api.de/api/interpreter'
HEADERS = {'User-Agent': 'InBackGeoEnrich/1.0 (inback.ru)'}

PRIORITY_ORDER = """
    ORDER BY char_length(geometry) ASC
"""

EXCLUDE_OSM_IDS = {'7373058'}  # Краснодарский край (regional boundary)


def ovp_get(query, retries=3):
    """GET запрос к Overpass API с повторами."""
    for attempt in range(retries):
        try:
            r = requests.get(OVERPASS, params={'data': query}, headers=HEADERS, timeout=90)
            if r.status_code == 200:
                return r.json()
            print(f"  HTTP {r.status_code}, ожидаем {20*(attempt+1)}s...")
            time.sleep(20 * (attempt + 1))
        except Exception as e:
            print(f"  Ошибка: {e}, повтор...")
            time.sleep(10)
    return None


def stitch_ways(ways_nodes):
    """Сшиваем отрезки пути в замкнутое кольцо."""
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
    """Загружаем полигон OSM relation → строка 'lat,lng;...'"""
    q = f'[out:json][timeout:90];\nrelation({rel_id});\n(._;>;);\nout body;\n'
    data = ovp_get(q)
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
    ring = stitch_ways([ways[w] for w in rel_ways if w in ways])
    coords = [f"{nodes[n][0]},{nodes[n][1]}" for n in ring if n in nodes]
    if len(coords) < 4:
        return None
    return ';'.join(coords)


def fetch_way_polygon(way_id):
    """Загружаем полигон OSM way → строка 'lat,lng;...'"""
    q = f'[out:json][timeout:60];\nway({way_id});\n(._;>;);\nout body;\n'
    data = ovp_get(q)
    if not data:
        return None
    nodes = {}
    way_nodes = []
    for el in data.get('elements', []):
        if el['type'] == 'node':
            nodes[el['id']] = (el['lat'], el['lon'])
        elif el['type'] == 'way':
            way_nodes = el.get('nodes', [])
    coords = [f"{nodes[n][0]},{nodes[n][1]}" for n in way_nodes if n in nodes]
    if len(coords) < 4:
        return None
    return ';'.join(coords)


def get_city_bbox(conn, city_id):
    """Возвращает bbox города из свойств объектов."""
    cur = conn.cursor()
    cur.execute("""
        SELECT MIN(latitude), MAX(latitude), MIN(longitude), MAX(longitude)
        FROM properties
        WHERE city_id=%s AND latitude IS NOT NULL AND longitude IS NOT NULL
    """, (city_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        return None
    min_lat, max_lat, min_lng, max_lng = row
    buf = 0.05  # 5km buffer
    return (min_lat - buf, min_lng - buf, max_lat + buf, max_lng + buf)


def enrich_okruga(conn, city_id, bbox):
    """Шаг 1: обогащаем административные округа (admin_level 9-10)."""
    print("\n=== Шаг 1: Административные округа ===")
    min_lat, min_lng, max_lat, max_lng = bbox
    q = f'''[out:json][timeout:60];
relation["boundary"="administrative"]["admin_level"~"9|10"]({min_lat},{min_lng},{max_lat},{max_lng});
out body;
'''
    data = ovp_get(q)
    if not data:
        print("Не удалось загрузить округа")
        return

    cur = conn.cursor()
    for el in data.get('elements', []):
        if el['type'] != 'relation':
            continue
        osm_id = el['id']
        name = el.get('tags', {}).get('name', '')
        if not name:
            continue
        if str(osm_id) in EXCLUDE_OSM_IDS:
            print(f"  Пропускаем регион: {name}")
            continue

        # Проверяем существование района в БД
        cur.execute("SELECT id FROM districts WHERE city_id=%s AND (osm_id=%s OR name ILIKE %s)", 
                   (city_id, osm_id, f'%{name}%'))
        row = cur.fetchone()
        if not row:
            print(f"  {name} — не найден в БД, пропускаем")
            continue

        print(f"  Обогащаем: {name} (rel={osm_id})")
        geom = fetch_relation_polygon(osm_id)
        if geom:
            pts = len(geom.split(';'))
            cur.execute("""
                UPDATE districts SET geometry=%s, geometry_source='osm', osm_id=%s,
                    district_type='okrug', updated_at=NOW()
                WHERE id=%s
            """, (geom, osm_id, row[0]))
            conn.commit()
            print(f"    ✓ Сохранён: {pts} точек")
        time.sleep(1)


def enrich_mikrorayons(conn, city_id, bbox, progress_file=None):
    """Шаг 2: обогащаем микрорайоны (place=suburb/neighbourhood)."""
    import json
    print("\n=== Шаг 2: Микрорайоны ===")
    min_lat, min_lng, max_lat, max_lng = bbox

    # Загружаем прогресс
    done = set()
    if progress_file and os.path.exists(progress_file):
        with open(progress_file) as f:
            done = set(json.load(f).get('done', []))

    q = f'''[out:json][timeout:90];
(
  node["place"~"suburb|neighbourhood|quarter"]({min_lat},{min_lng},{max_lat},{max_lng});
  way["place"~"suburb|neighbourhood|quarter"]({min_lat},{min_lng},{max_lat},{max_lng});
  relation["place"~"suburb|neighbourhood|quarter"]({min_lat},{min_lng},{max_lat},{max_lng});
);
out body;
'''
    data = ovp_get(q)
    if not data:
        return

    places = [el for el in data.get('elements', []) if el.get('tags', {}).get('name')]
    print(f"Найдено {len(places)} мест. Уже готово: {len(done)}")

    cur = conn.cursor()
    for el in places:
        osm_id = el['id']
        el_type = el['type']
        if osm_id in done:
            continue
        name = el.get('tags', {}).get('name', '')
        if not name:
            done.add(osm_id)
            continue

        # Проверяем существование в БД
        cur.execute("SELECT id FROM districts WHERE city_id=%s AND (osm_id=%s OR name ILIKE %s)",
                   (city_id, osm_id, f'%{name}%'))
        row = cur.fetchone()
        if not row:
            done.add(osm_id)
            continue

        print(f"  [{osm_id}] {name} ({el_type})...", end=' ', flush=True)
        if el_type == 'node':
            done.add(osm_id)
            continue
        elif el_type == 'way':
            geom = fetch_way_polygon(osm_id)
        else:
            geom = fetch_relation_polygon(osm_id)

        if geom:
            pts = len(geom.split(';'))
            print(f"{pts} pts")
            cur.execute("""
                UPDATE districts SET geometry=%s, geometry_source='osm', osm_id=%s,
                    district_type='microrayon', updated_at=NOW()
                WHERE id=%s
            """, (geom, osm_id, row[0]))
            conn.commit()
        else:
            print("failed")

        done.add(osm_id)
        if progress_file:
            with open(progress_file, 'w') as f:
                json.dump({'done': list(done)}, f)
        time.sleep(1.5)


def run_pip(conn, city_id):
    """Шаг 3: Point-in-polygon — назначаем объекты наиболее точному району."""
    print("\n=== Шаг 3: PIP — назначение объектов районам ===")

    def parse_polygon(geom_str):
        pairs = []
        for p in geom_str.split(';'):
            if ',' in p:
                parts = p.split(',')
                pairs.append((float(parts[0]), float(parts[1])))
        return pairs

    def bbox(poly):
        lats = [p[0] for p in poly]
        lons = [p[1] for p in poly]
        return min(lats), max(lats), min(lons), max(lons)

    def pip(lat, lon, polygon):
        inside = False
        n = len(polygon)
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i][0], polygon[i][1]
            xj, yj = polygon[j][0], polygon[j][1]
            if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, district_type, geometry
        FROM districts
        WHERE city_id=%s AND geometry IS NOT NULL AND char_length(geometry) > 200
          AND COALESCE(osm_id::text, '') NOT IN ('7373058')
          AND name NOT ILIKE '%%край%%'
        ORDER BY char_length(geometry) ASC
    """, (city_id,))

    districts = []
    for row in cur.fetchall():
        poly = parse_polygon(row[3])
        if len(poly) >= 4:
            districts.append({'id': row[0], 'name': row[1], 'bbox': bbox(poly), 'polygon': poly})

    print(f"Загружено {len(districts)} районов с полигонами")

    cur.execute("SELECT COUNT(*) FROM properties WHERE city_id=%s AND latitude IS NOT NULL", (city_id,))
    total = cur.fetchone()[0]
    print(f"Объектов с координатами: {total}")

    batch, offset, assigned = 500, 0, 0
    while True:
        cur.execute("""
            SELECT id, latitude, longitude, district_id FROM properties
            WHERE city_id=%s AND latitude IS NOT NULL AND longitude IS NOT NULL
            ORDER BY id LIMIT %s OFFSET %s
        """, (city_id, batch, offset))
        rows = cur.fetchall()
        if not rows:
            break

        updates = []
        for prop_id, lat, lon, curr_did in rows:
            found_id = None
            for d in districts:
                bb = d['bbox']
                if bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]:
                    if pip(lat, lon, d['polygon']):
                        found_id = d['id']
                        break
            if found_id and found_id != curr_did:
                updates.append((found_id, prop_id))
                assigned += 1

        if updates:
            cur.executemany("UPDATE properties SET district_id=%s WHERE id=%s", updates)
            conn.commit()

        offset += batch
        if offset % 5000 == 0:
            print(f"  Прогресс: {offset}/{total}, назначено={assigned}")

    conn.commit()
    print(f"PIP завершён: {assigned} объектов назначено")


def main():
    parser = argparse.ArgumentParser(description='Гео-обогащение районов для города')
    parser.add_argument('--city_id', type=int, required=True)
    parser.add_argument('--city_name', type=str, default='')
    parser.add_argument('--steps', type=str, default='1,2,3',
                        help='Шаги для запуска: 1=округа,2=микрорайоны,3=PIP')
    args = parser.parse_args()

    steps = [int(s) for s in args.steps.split(',')]
    print(f"Обогащение города id={args.city_id} {args.city_name}")
    print(f"Шаги: {steps}")

    conn = psycopg2.connect(DB)
    bbox = get_city_bbox(conn, args.city_id)
    if not bbox:
        print("Не удалось определить bbox города — нет объектов с координатами")
        sys.exit(1)

    print(f"Bbox города: lat {bbox[0]:.3f}-{bbox[2]:.3f}, lng {bbox[1]:.3f}-{bbox[3]:.3f}")

    progress_file = f'/tmp/geo_enrich_city{args.city_id}_t2.json'

    if 1 in steps:
        enrich_okruga(conn, args.city_id, bbox)
    if 2 in steps:
        enrich_mikrorayons(conn, args.city_id, bbox, progress_file)
    if 3 in steps:
        run_pip(conn, args.city_id)

    conn.close()
    print("\nГотово!")


if __name__ == '__main__':
    main()
