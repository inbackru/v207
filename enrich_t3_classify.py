#!/usr/bin/env python3
"""
Task 3: Classify districts by type and compute centroids/metadata.
Sets district_type = 'okrug' | 'microrayon' | 'settlement'
"""
import os, psycopg2, math

DB = os.environ['DATABASE_URL']

OKRUGA = ['центральный', 'прикубанский', 'карасунский', 'западный округ',
          'западный (административный)', 'краснодарский край']

SETTLEMENTS = ['яблоновский', 'старокорсунская', 'покровка', 'новознаменский',
               'калинино', 'пашковский', 'репино', 'северный']

def classify_name(name: str) -> str:
    n = name.lower()
    if any(k in n for k in OKRUGA) or 'округ' in n:
        return 'okrug'
    if any(k in n for k in SETTLEMENTS):
        return 'settlement'
    return 'microrayon'

def compute_centroid(geom: str):
    try:
        pairs = [p.split(',') for p in geom.split(';') if ',' in p]
        if not pairs:
            return None, None
        lats = [float(p[0]) for p in pairs]
        lons = [float(p[1]) for p in pairs]
        return sum(lats)/len(lats), sum(lons)/len(lons)
    except:
        return None, None

def compute_distance_to_center(lat, lon, center_lat=45.0448, center_lon=38.9760):
    """Distance from point to Krasnodar center in km."""
    if not lat or not lon:
        return None
    R = 6371.0
    dlat = math.radians(lat - center_lat)
    dlon = math.radians(lon - center_lon)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(center_lat)) * math.cos(math.radians(lat)) * math.sin(dlon/2)**2
    return round(R * 2 * math.asin(math.sqrt(a)), 2)

def main():
    conn = psycopg2.connect(DB)
    cur = conn.cursor()

    cur.execute("SELECT id, name, geometry, latitude, longitude, district_type FROM districts WHERE city_id=1")
    rows = cur.fetchall()
    print(f"Processing {len(rows)} districts...")

    updated = 0
    for dist_id, name, geom, lat, lon, current_type in rows:
        new_type = classify_name(name)

        # Override if already set by enrichment scripts
        if current_type in ('okrug', 'microrayon', 'settlement'):
            new_type = current_type

        # Compute centroid if missing
        new_lat, new_lon = lat, lon
        if geom and (not lat or not lon):
            new_lat, new_lon = compute_centroid(geom)

        dist = compute_distance_to_center(new_lat, new_lon)

        cur.execute("""
            UPDATE districts SET
                district_type = %s,
                latitude = COALESCE(latitude, %s),
                longitude = COALESCE(longitude, %s),
                distance_to_center = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (new_type, new_lat, new_lon, dist, dist_id))
        updated += 1

        if updated % 20 == 0:
            conn.commit()

    conn.commit()

    # Summary
    cur.execute("SELECT district_type, count(*) FROM districts WHERE city_id=1 GROUP BY district_type")
    print("\nClassification summary:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

    # Set zoom level by type
    cur.execute("UPDATE districts SET zoom_level=12 WHERE district_type='okrug' AND zoom_level IS NULL")
    cur.execute("UPDATE districts SET zoom_level=14 WHERE district_type='microrayon' AND zoom_level IS NULL")
    cur.execute("UPDATE districts SET zoom_level=13 WHERE district_type='settlement' AND zoom_level IS NULL")
    conn.commit()

    cur.close()
    conn.close()
    print(f"\nTask 3 done: {updated} districts classified.")

if __name__ == '__main__':
    main()
