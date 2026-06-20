#!/usr/bin/env python3
"""
Task 4: Point-in-polygon - assign properties to correct districts.
Uses ray casting algorithm to check if property lat/lng is inside district polygon.
Runs in batches to avoid memory/timeout issues.
"""
import os, psycopg2

DB = os.environ['DATABASE_URL']

def parse_polygon(geom_str: str):
    """Parse 'lat,lng;lat,lng;...' into list of (lat, lon) tuples."""
    try:
        pairs = []
        for p in geom_str.split(';'):
            if ',' in p:
                parts = p.split(',')
                pairs.append((float(parts[0]), float(parts[1])))
        return pairs
    except:
        return []

def point_in_polygon(lat, lon, polygon):
    """Ray casting algorithm for point-in-polygon test."""
    if len(polygon) < 3:
        return False
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

def bbox(polygon):
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    return min(lats), max(lats), min(lons), max(lons)

def main():
    conn = psycopg2.connect(DB)
    cur = conn.cursor()

    # Load all districts with real geometry (at least 100 chars = real polygon)
    # Exclude regional/country-level boundaries (very large polygons that cover
    # the whole city, e.g. "Краснодарский край" osm_id=7373058).
    # ORDER: smallest polygon first → most specific match wins on first break.
    cur.execute("""
        SELECT id, name, district_type, geometry
        FROM districts
        WHERE city_id=1
          AND geometry IS NOT NULL
          AND char_length(geometry) > 200
          AND COALESCE(osm_id::text,'') NOT IN ('7373058')
          AND name NOT ILIKE '%краснодарский край%'
          AND name NOT ILIKE '%krasnodar krai%'
        ORDER BY char_length(geometry) ASC
    """)
    districts = []
    for row in cur.fetchall():
        poly = parse_polygon(row[3])
        if len(poly) >= 4:
            bb = bbox(poly)
            districts.append({
                'id': row[0], 'name': row[1], 'type': row[2],
                'polygon': poly, 'bbox': bb
            })

    print(f"Loaded {len(districts)} districts with valid geometry")

    # Count properties needing assignment
    cur.execute("SELECT COUNT(*) FROM properties WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND city_id=1")
    total = cur.fetchone()[0]
    print(f"Total Krasnodar properties with coords: {total}")

    # Process in batches
    batch_size = 500
    offset = 0
    assigned = 0
    skipped = 0

    while True:
        cur.execute("""
            SELECT id, latitude, longitude, district_id
            FROM properties
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND city_id=1
            ORDER BY id
            LIMIT %s OFFSET %s
        """, (batch_size, offset))
        rows = cur.fetchall()
        if not rows:
            break

        updates = []
        for prop_id, lat, lon, current_district_id in rows:
            if not lat or not lon:
                skipped += 1
                continue

            # Check bounding box first, then full PIP.
            # Districts are ordered microrayon→settlement→okrug so the first
            # match is always the most specific. Break immediately on first hit.
            found_id = None
            for d in districts:
                bb = d['bbox']
                if bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]:
                    if point_in_polygon(lat, lon, d['polygon']):
                        found_id = d['id']
                        break  # most-specific match wins

            if found_id is None:
                # No polygon covers this property — clear stale assignment
                if current_district_id is not None:
                    pass  # keep existing; do not clear
            elif found_id != current_district_id:
                updates.append((found_id, prop_id))
                assigned += 1

        if updates:
            cur.executemany("UPDATE properties SET district_id=%s WHERE id=%s", updates)
            conn.commit()

        offset += batch_size
        if offset % 5000 == 0:
            print(f"  Progress: {offset}/{total}, assigned={assigned}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nTask 4 done: {assigned} properties assigned to districts, {skipped} skipped.")

if __name__ == '__main__':
    main()
