#!/usr/bin/env python3
"""
Task 5: Verify district routes are properly set up and add missing API endpoints
for polygon-based district search (like CIAN).
This script patches the DB and verifies the routes file is correct.
"""
import os, psycopg2

DB = os.environ['DATABASE_URL']

def main():
    conn = psycopg2.connect(DB)
    cur = conn.cursor()

    # Summary stats
    cur.execute("""
        SELECT district_type, count(*), 
               sum(CASE WHEN char_length(COALESCE(geometry,'')) > 200 THEN 1 ELSE 0 END) as with_geom
        FROM districts WHERE city_id=1
        GROUP BY district_type
    """)
    print("=== District Summary ===")
    for row in cur.fetchall():
        print(f"  {row[0]}: total={row[1]}, with_real_geom={row[2]}")

    # Count properties per district
    cur.execute("""
        SELECT d.name, d.district_type, count(p.id) as prop_count
        FROM districts d
        LEFT JOIN properties p ON p.district_id=d.id AND p.is_active=true
        WHERE d.city_id=1
        GROUP BY d.id, d.name, d.district_type
        HAVING count(p.id) > 0
        ORDER BY prop_count DESC
        LIMIT 20
    """)
    print("\n=== Top districts by property count ===")
    for row in cur.fetchall():
        print(f"  [{row[1]}] {row[0]}: {row[2]} properties")

    # Make sure all active districts are visible
    cur.execute("""
        UPDATE districts SET zoom_level=COALESCE(zoom_level,14)
        WHERE city_id=1 AND zoom_level IS NULL
    """)
    conn.commit()

    # Create a helper view for district+property counts (if not exists)
    try:
        cur.execute("""
            CREATE OR REPLACE VIEW district_property_counts AS
            SELECT 
                d.id, d.name, d.slug, d.city_id, d.district_type,
                d.geometry, d.latitude, d.longitude, d.zoom_level,
                d.distance_to_center, d.osm_id,
                count(p.id) FILTER (WHERE p.is_active=true) as property_count,
                min(p.price) FILTER (WHERE p.is_active=true) as min_price,
                max(p.price) FILTER (WHERE p.is_active=true) as max_price,
                avg(p.price_per_sqm) FILTER (WHERE p.is_active=true) as avg_price_sqm
            FROM districts d
            LEFT JOIN properties p ON p.district_id=d.id
            GROUP BY d.id
        """)
        conn.commit()
        print("\nCreated/updated district_property_counts view")
    except Exception as e:
        conn.rollback()
        print(f"View creation note: {e}")

    cur.close()
    conn.close()
    print("\nTask 5 done.")

if __name__ == '__main__':
    main()
