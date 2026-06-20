#!/usr/bin/env python3
"""
scripts/assign_district_ids.py

Point-in-polygon assignment of district_id to properties.

Usage:
    python scripts/assign_district_ids.py [--city-id 1] [--batch 1000] [--all]

Geometry format stored in districts.geometry: "lat,lng;lat,lng;..."
Uses the ray-casting algorithm for point-in-polygon test.
"""

import os
import sys
import time
import logging
import argparse
from math import sqrt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def point_in_polygon(lat, lng, polygon_points):
    """
    Ray-casting algorithm: checks if point (lat, lng) is inside polygon.
    polygon_points: list of (lat, lng) tuples (closed or open ring).
    Returns True if inside.
    """
    n = len(polygon_points)
    inside = False
    x, y = lng, lat
    j = n - 1
    for i in range(n):
        xi, yi = polygon_points[i][1], polygon_points[i][0]
        xj, yj = polygon_points[j][1], polygon_points[j][0]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def parse_geometry(geometry_str):
    """
    Parse "lat,lng;lat,lng;..." into list of (lat, lng) tuples.
    Returns None if parsing fails.
    """
    if not geometry_str:
        return None
    try:
        points = []
        for pair in geometry_str.strip().split(';'):
            pair = pair.strip()
            if not pair:
                continue
            parts = pair.split(',')
            if len(parts) >= 2:
                lat = float(parts[0].strip())
                lng = float(parts[1].strip())
                points.append((lat, lng))
        return points if len(points) >= 3 else None
    except (ValueError, IndexError):
        return None


def get_bounding_box(points):
    """Get bounding box (min_lat, max_lat, min_lng, max_lng) for quick pre-filter."""
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return min(lats), max(lats), min(lngs), max(lngs)


def haversine_approx(lat1, lng1, lat2, lng2):
    """Approximate distance in degrees squared (fast, no trig)."""
    dlat = lat1 - lat2
    dlng = lng1 - lng2
    return dlat * dlat + dlng * dlng


def assign_districts(city_id=1, batch_size=1000, only_unlinked=True):
    """
    Main function: assigns district_id and parsed_district to properties.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        district_filter = ''
        if only_unlinked:
            district_filter = 'AND district_id IS NULL'

        log.info(f"Loading districts for city_id={city_id}...")
        rows = session.execute(text(
            "SELECT id, name, geometry FROM districts WHERE city_id = :cid AND geometry IS NOT NULL AND geometry != ''"
        ), {'cid': city_id}).fetchall()

        if not rows:
            log.error(f"No districts with geometry found for city_id={city_id}")
            return 0

        districts = []
        for row in rows:
            points = parse_geometry(row.geometry)
            if not points:
                log.warning(f"  Skipping district '{row.name}' — invalid geometry")
                continue
            bb = get_bounding_box(points)
            min_lat, max_lat, min_lng, max_lng = bb
            bbox_area = (max_lat - min_lat) * (max_lng - min_lng)
            districts.append({
                'id': row.id,
                'name': row.name,
                'points': points,
                'bbox': bb,
                'bbox_area': bbox_area,
            })

        # Sort by bbox area ascending — specific/small districts checked first
        # This ensures a property in "Центральный" isn't hijacked by a city-spanning bbox
        districts.sort(key=lambda d: d['bbox_area'])

        # Skip districts whose bbox is city-wide (bad geometry data)
        # City bbox for Krasnodar is roughly 0.076 sq.deg; use 0.04 as threshold
        MAX_BBOX_AREA = 0.04
        skipped = [d for d in districts if d['bbox_area'] > MAX_BBOX_AREA]
        districts = [d for d in districts if d['bbox_area'] <= MAX_BBOX_AREA]
        if skipped:
            log.warning(f"Skipping {len(skipped)} districts with city-wide bbox (geometry needs fix): "
                        f"{', '.join(d['name'] for d in skipped)}")

        log.info(f"Loaded {len(districts)} districts with valid geometry (sorted by bbox area)")
        for d in districts[:5]:
            log.info(f"  Smallest: {d['name']} area={d['bbox_area']:.6f}")
        if districts:
            log.info(f"  Largest used: {districts[-1]['name']} area={districts[-1]['bbox_area']:.6f}")

        coord_filter = "AND latitude IS NOT NULL AND longitude IS NOT NULL"
        count_q = session.execute(text(
            f"SELECT COUNT(*) FROM properties WHERE city_id = :cid {coord_filter} {district_filter}"
        ), {'cid': city_id}).scalar()
        log.info(f"Properties to process: {count_q}")

        if count_q == 0:
            log.info("Nothing to process.")
            return 0

        last_id = 0
        total_assigned = 0
        total_processed = 0

        while True:
            props = session.execute(text(
                f"""SELECT id, latitude, longitude
                    FROM properties
                    WHERE city_id = :cid {coord_filter} AND id > :last_id {district_filter}
                    ORDER BY id
                    LIMIT :lim"""
            ), {'cid': city_id, 'lim': batch_size, 'last_id': last_id}).fetchall()

            if not props:
                break

            updates = []
            for prop in props:
                lat, lng = float(prop.latitude), float(prop.longitude)
                matched = None

                for dist in districts:
                    min_lat, max_lat, min_lng, max_lng = dist['bbox']
                    if not (min_lat <= lat <= max_lat and min_lng <= lng <= max_lng):
                        continue
                    if point_in_polygon(lat, lng, dist['points']):
                        matched = dist
                        break

                if matched:
                    updates.append({'prop_id': prop.id, 'dist_id': matched['id'], 'dist_name': matched['name']})

            if updates:
                for u in updates:
                    session.execute(text(
                        "UPDATE properties SET district_id = :did, parsed_district = :dname WHERE id = :pid"
                    ), {'did': u['dist_id'], 'dname': u['dist_name'], 'pid': u['prop_id']})
                session.commit()
                total_assigned += len(updates)

            last_id = props[-1].id
            total_processed += len(props)

            log.info(f"  Processed {total_processed}/{count_q} — assigned so far: {total_assigned}")

        log.info(f"Done. Assigned district to {total_assigned}/{total_processed} properties.")
        return total_assigned

    except Exception as e:
        session.rollback()
        log.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        session.close()


def assign_streets(city_id=1, batch_size=500, only_unlinked=True):
    """
    Assigns parsed_street to properties by finding the nearest street
    within a max distance threshold (~500m ~= 0.005 degrees).
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        street_filter = ''
        if only_unlinked:
            street_filter = 'AND parsed_street IS NULL'

        log.info(f"Loading streets for city_id={city_id}...")
        rows = session.execute(text(
            "SELECT id, name, latitude, longitude FROM streets WHERE city_id = :cid AND latitude IS NOT NULL AND longitude IS NOT NULL"
        ), {'cid': city_id}).fetchall()

        if not rows:
            log.warning(f"No streets with coordinates for city_id={city_id}")
            return 0

        streets = [{'id': r.id, 'name': r.name, 'lat': float(r.latitude), 'lng': float(r.longitude)} for r in rows]
        log.info(f"Loaded {len(streets)} streets")

        MAX_DIST_SQ = 0.005 ** 2

        coord_filter = "AND latitude IS NOT NULL AND longitude IS NOT NULL"
        count_q = session.execute(text(
            f"SELECT COUNT(*) FROM properties WHERE city_id = :cid {coord_filter} {street_filter}"
        ), {'cid': city_id}).scalar()
        log.info(f"Properties to match streets: {count_q}")

        if count_q == 0:
            return 0

        last_id = 0
        total_assigned = 0

        while True:
            props = session.execute(text(
                f"""SELECT id, latitude, longitude
                    FROM properties
                    WHERE city_id = :cid {coord_filter} AND id > :last_id {street_filter}
                    ORDER BY id
                    LIMIT :lim"""
            ), {'cid': city_id, 'lim': batch_size, 'last_id': last_id}).fetchall()

            if not props:
                break

            updates = []
            for prop in props:
                lat, lng = float(prop.latitude), float(prop.longitude)
                best = None
                best_dist = MAX_DIST_SQ

                for s in streets:
                    d = haversine_approx(lat, lng, s['lat'], s['lng'])
                    if d < best_dist:
                        best_dist = d
                        best = s

                if best:
                    updates.append({'prop_id': prop.id, 'street_name': best['name']})

            if updates:
                for u in updates:
                    session.execute(text(
                        "UPDATE properties SET parsed_street = :sname WHERE id = :pid"
                    ), {'sname': u['street_name'], 'pid': u['prop_id']})
                session.commit()
                total_assigned += len(updates)

            last_id = props[-1].id
            log.info(f"  Streets matched so far: {total_assigned}")

        log.info(f"Streets: matched {total_assigned} properties")
        return total_assigned

    except Exception as e:
        session.rollback()
        log.error(f"Street assignment error: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description='Assign district_id and parsed_street to properties via point-in-polygon')
    parser.add_argument('--city-id', type=int, default=1, help='City ID to process (default: 1=Krasnodar)')
    parser.add_argument('--batch', type=int, default=1000, help='Batch size for DB updates')
    parser.add_argument('--all', action='store_true', dest='all_props',
                        help='Re-assign even already-linked properties')
    parser.add_argument('--no-streets', action='store_true', help='Skip parsed_street assignment')
    parser.add_argument('--streets-only', action='store_true', help='Only assign streets, skip districts')
    args = parser.parse_args()

    only_unlinked = not args.all_props

    if not args.streets_only:
        log.info("=== District assignment ===")
        assigned = assign_districts(
            city_id=args.city_id,
            batch_size=args.batch,
            only_unlinked=only_unlinked
        )
        log.info(f"Districts assigned: {assigned}")

    # parsed_street is always run by default (use --no-streets to skip)
    if not args.no_streets:
        log.info("=== Street assignment ===")
        assigned_s = assign_streets(
            city_id=args.city_id,
            batch_size=500,
            only_unlinked=only_unlinked
        )
        log.info(f"Streets assigned: {assigned_s}")


if __name__ == '__main__':
    main()
