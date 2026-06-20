"""
Geo utilities: point-in-polygon, bounding box, and Yandex Geocoder enrichment.
"""
import re
import requests
import os
import logging

logger = logging.getLogger(__name__)

YANDEX_GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"


def parse_geometry(geometry_str):
    """
    Parse geometry string ('lat1,lng1;lat2,lng2;...') into list of (lat, lng) tuples.
    Handles trailing #, ;, and whitespace.
    """
    if not geometry_str:
        return []
    clean = geometry_str.rstrip('#').rstrip(';').strip()
    points = []
    for part in re.split(r'[;]+', clean):
        part = part.strip()
        if not part:
            continue
        coords = part.split(',')
        if len(coords) == 2:
            try:
                lat, lng = float(coords[0].strip()), float(coords[1].strip())
                points.append((lat, lng))
            except ValueError:
                pass
    return points


def geometry_centroid(geometry_str):
    """Return (lat, lng) centroid of geometry polygon."""
    points = parse_geometry(geometry_str)
    if not points:
        return None, None
    avg_lat = sum(p[0] for p in points) / len(points)
    avg_lng = sum(p[1] for p in points) / len(points)
    return avg_lat, avg_lng


def geometry_bbox(geometry_str):
    """Return (min_lat, min_lng, max_lat, max_lng) bounding box of geometry."""
    points = parse_geometry(geometry_str)
    if not points:
        return None
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return min(lats), min(lngs), max(lats), max(lngs)


def point_in_polygon(lat, lng, polygon_points):
    """
    Ray-casting algorithm: True if (lat, lng) is inside the polygon.
    polygon_points: list of (lat, lng) tuples.
    Casts a horizontal ray from (lat, lng) eastward and counts crossings.
    """
    if not polygon_points or len(polygon_points) < 3:
        return False
    n = len(polygon_points)
    inside = False
    j = n - 1
    for i in range(n):
        lat_i, lng_i = polygon_points[i]
        lat_j, lng_j = polygon_points[j]
        # Check if edge (i→j) crosses the horizontal ray at height `lat`
        if ((lat_i > lat) != (lat_j > lat)):
            # Longitude where the edge crosses the horizontal line at `lat`
            lng_cross = (lng_j - lng_i) * (lat - lat_i) / (lat_j - lat_i + 1e-12) + lng_i
            if lng < lng_cross:
                inside = not inside
        j = i
    return inside


def point_in_geometry(lat, lng, geometry_str):
    """Check if point (lat, lng) is inside geometry polygon string."""
    points = parse_geometry(geometry_str)
    if len(points) < 3:
        # For line geometries (streets), use bbox with a small buffer
        bbox = geometry_bbox(geometry_str)
        if not bbox:
            return False
        min_lat, min_lng, max_lat, max_lng = bbox
        buf = 0.003  # ~300m buffer for streets
        return (min_lat - buf <= lat <= max_lat + buf and
                min_lng - buf <= lng <= max_lng + buf)
    return point_in_polygon(lat, lng, points)


def bbox_filter_clause(geometry_str, lat_col='latitude', lng_col='longitude', buffer=0.0):
    """
    Return a SQL WHERE clause snippet for bbox filtering.
    buffer: degrees to expand bbox (use 0.003 ≈ 300m for streets)
    Returns (clause_str, params_dict) or (None, {}) if no geometry.
    """
    bbox = geometry_bbox(geometry_str)
    if not bbox:
        return None, {}
    min_lat, min_lng, max_lat, max_lng = bbox
    clause = (
        f"{lat_col} BETWEEN :bbox_min_lat AND :bbox_max_lat "
        f"AND {lng_col} BETWEEN :bbox_min_lng AND :bbox_max_lng"
    )
    params = {
        'bbox_min_lat': min_lat - buffer,
        'bbox_max_lat': max_lat + buffer,
        'bbox_min_lng': min_lng - buffer,
        'bbox_max_lng': max_lng + buffer,
    }
    return clause, params


def yandex_geocode(query, api_key=None):
    """
    Geocode a query string using Yandex Geocoder.
    Returns dict with: lat, lng, bbox (min_lat, min_lng, max_lat, max_lng), geometry_str
    """
    api_key = api_key or os.environ.get('YANDEX_MAPS_API_KEY')
    if not api_key:
        logger.warning("YANDEX_MAPS_API_KEY not set")
        return None
    try:
        resp = requests.get(YANDEX_GEOCODER_URL, params={
            'apikey': api_key,
            'geocode': query,
            'format': 'json',
            'results': 1,
            'lang': 'ru_RU',
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        features = data.get('response', {}).get('GeoObjectCollection', {}).get('featureMember', [])
        if not features:
            return None
        obj = features[0]['GeoObject']
        pos = obj['Point']['pos'].split()
        lng, lat = float(pos[0]), float(pos[1])
        # Bounding box
        env = obj.get('boundedBy', {}).get('Envelope', {})
        if env:
            ll = env.get('lowerCorner', '').split()
            ur = env.get('upperCorner', '').split()
            if len(ll) == 2 and len(ur) == 2:
                min_lng, min_lat = float(ll[0]), float(ll[1])
                max_lng, max_lat = float(ur[0]), float(ur[1])
                # Build a simple bbox polygon as geometry string
                geometry_str = (
                    f"{min_lat},{min_lng};{min_lat},{max_lng};"
                    f"{max_lat},{max_lng};{max_lat},{min_lng};{min_lat},{min_lng}"
                )
                return {'lat': lat, 'lng': lng,
                        'bbox': (min_lat, min_lng, max_lat, max_lng),
                        'geometry_str': geometry_str}
        return {'lat': lat, 'lng': lng, 'bbox': None, 'geometry_str': None}
    except Exception as e:
        logger.error(f"Yandex geocode error for '{query}': {e}")
        return None


def enrich_streets_with_yandex(city_name, limit=100):
    """
    Enrich streets missing geometry/lat-lng using Yandex Geocoder.
    Must be called inside Flask app context.
    Returns count of updated records.
    """
    import time
    from app import db
    from sqlalchemy import text

    api_key = os.environ.get('YANDEX_MAPS_API_KEY')
    if not api_key:
        return 0

    rows = db.session.execute(text("""
        SELECT id, name FROM streets
        WHERE (latitude IS NULL OR geometry IS NULL OR geometry = '')
        AND city_id = (SELECT id FROM cities WHERE name = :city LIMIT 1)
        LIMIT :lim
    """), {'city': city_name, 'lim': limit}).fetchall()

    updated = 0
    for row in rows:
        result = yandex_geocode(f"{city_name}, {row.name}", api_key)
        if result:
            db.session.execute(text("""
                UPDATE streets SET
                    latitude = :lat,
                    longitude = :lng,
                    geometry = COALESCE(NULLIF(geometry, ''), :geom),
                    geometry_source = 'yandex'
                WHERE id = :id
            """), {
                'lat': result['lat'], 'lng': result['lng'],
                'geom': result.get('geometry_str'), 'id': row.id
            })
            updated += 1
        time.sleep(0.1)  # respect rate limit

    db.session.commit()
    return updated


def enrich_districts_with_yandex(city_name):
    """
    Enrich districts missing geometry using Yandex Geocoder.
    Must be called inside Flask app context.
    """
    import time
    from app import db
    from sqlalchemy import text

    api_key = os.environ.get('YANDEX_MAPS_API_KEY')
    if not api_key:
        return 0

    rows = db.session.execute(text("""
        SELECT id, name FROM districts
        WHERE (geometry IS NULL OR geometry = '')
        AND city_id = (SELECT id FROM cities WHERE name = :city LIMIT 1)
    """), {'city': city_name}).fetchall()

    updated = 0
    for row in rows:
        result = yandex_geocode(f"{city_name}, {row.name}", api_key)
        if result:
            db.session.execute(text("""
                UPDATE districts SET
                    latitude = COALESCE(latitude, :lat),
                    longitude = COALESCE(longitude, :lng),
                    geometry = COALESCE(NULLIF(geometry, ''), :geom),
                    geometry_source = 'yandex'
                WHERE id = :id
            """), {
                'lat': result['lat'], 'lng': result['lng'],
                'geom': result.get('geometry_str'), 'id': row.id
            })
            updated += 1
        time.sleep(0.1)

    db.session.commit()
    return updated
