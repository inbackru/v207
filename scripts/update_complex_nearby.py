#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Populate ResidentialComplex.nearby field with real POI data from Overpass API.
Format stored:
{
  "transport":  [{"type": ..., "type_display": ..., "name": ..., "distance": <meters>, "coordinates": [lat, lng]}, ...],
  "shopping":   [...],
  "education":  [...],
  "healthcare": [...],
  "sport":      [...],
  "leisure":    [...],
  "updated_at": "ISO8601"
}
"""

import os, sys, json, time, logging
from datetime import datetime, timezone
from math import radians, cos, sin, asin, sqrt

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RADIUS = int(os.environ.get('NEARBY_RADIUS', 1500))
DELAY  = float(os.environ.get('NEARBY_DELAY', 1.5))

# Proxy support: set via NEARBY_PROXY / HTTP_PROXY / HTTPS_PROXY env vars
_proxy_url = os.environ.get('NEARBY_PROXY') or os.environ.get('HTTP_PROXY') or ''
PROXIES = {'http': _proxy_url, 'https': _proxy_url} if _proxy_url else None
if PROXIES:
    log.info(f'🔀 Using proxy: {_proxy_url}')


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in metres between two points."""
    R = 6371000
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return round(2*R*asin(sqrt(a)))


AMENITY_MAP = {
    # transport
    'bus_stop':     ('transport', 'Остановка автобуса'),
    'tram_stop':    ('transport', 'Остановка трамвая'),
    'subway_entrance': ('transport', 'Метро'),
    # education
    'school':       ('education', 'Школа'),
    'kindergarten': ('education', 'Детский сад'),
    'university':   ('education', 'Университет'),
    'college':      ('education', 'Колледж'),
    # healthcare
    'hospital':     ('healthcare', 'Больница'),
    'clinic':       ('healthcare', 'Поликлиника'),
    'doctors':      ('healthcare', 'Врач'),
    'pharmacy':     ('healthcare', 'Аптека'),
    # leisure
    'cinema':       ('leisure', 'Кинотеатр'),
    'theatre':      ('leisure', 'Театр'),
    'restaurant':   ('leisure', 'Ресторан'),
    'cafe':         ('leisure', 'Кафе'),
}
SHOP_MAP = {
    'supermarket':    ('shopping', 'Супермаркет'),
    'convenience':    ('shopping', 'Магазин у дома'),
    'mall':           ('shopping', 'Торговый центр'),
    'department_store': ('shopping', 'Универмаг'),
    'clothes':        ('shopping', 'Одежда'),
    'bakery':         ('shopping', 'Пекарня'),
    'butcher':        ('shopping', 'Мясной магазин'),
    'greengrocer':    ('shopping', 'Овощи/фрукты'),
}
LEISURE_MAP = {
    'park':           ('leisure', 'Парк'),
    'garden':         ('leisure', 'Сад'),
    'sports_centre':  ('sport',   'Спорткомплекс'),
    'fitness_centre': ('sport',   'Фитнес'),
    'swimming_pool':  ('sport',   'Бассейн'),
    'stadium':        ('sport',   'Стадион'),
    'playground':     ('leisure', 'Детская площадка'),
}
HIGHWAY_MAP = {
    'bus_stop': ('transport', 'Остановка'),
}
RAILWAY_MAP = {
    'station':      ('transport', 'Ж/д станция'),
    'tram_stop':    ('transport', 'Остановка трамвая'),
    'subway_entrance': ('transport', 'Метро'),
    'halt':         ('transport', 'Остановка'),
}


def fetch_poi(lat, lng):
    query = f"""
[out:json][timeout:25];
(
  node["highway"="bus_stop"](around:{RADIUS},{lat},{lng});
  node["amenity"="school"](around:{RADIUS},{lat},{lng});
  node["amenity"="kindergarten"](around:{RADIUS},{lat},{lng});
  node["amenity"="university"](around:{RADIUS},{lat},{lng});
  node["amenity"="college"](around:{RADIUS},{lat},{lng});
  node["amenity"="hospital"](around:{RADIUS},{lat},{lng});
  node["amenity"="clinic"](around:{RADIUS},{lat},{lng});
  node["amenity"="pharmacy"](around:{RADIUS},{lat},{lng});
  node["amenity"="cinema"](around:{RADIUS},{lat},{lng});
  node["amenity"="theatre"](around:{RADIUS},{lat},{lng});
  node["amenity"="cafe"](around:{RADIUS},{lat},{lng});
  node["amenity"="restaurant"](around:{RADIUS},{lat},{lng});
  node["shop"="supermarket"](around:{RADIUS},{lat},{lng});
  node["shop"="convenience"](around:{RADIUS},{lat},{lng});
  node["shop"="mall"](around:{RADIUS},{lat},{lng});
  node["shop"="department_store"](around:{RADIUS},{lat},{lng});
  node["leisure"="park"](around:{RADIUS},{lat},{lng});
  node["leisure"="garden"](around:{RADIUS},{lat},{lng});
  node["leisure"="sports_centre"](around:{RADIUS},{lat},{lng});
  node["leisure"="fitness_centre"](around:{RADIUS},{lat},{lng});
  node["leisure"="swimming_pool"](around:{RADIUS},{lat},{lng});
  node["railway"="tram_stop"](around:{RADIUS},{lat},{lng});
  node["railway"="subway_entrance"](around:{RADIUS},{lat},{lng});
);
out center;
"""
    headers = {
        'User-Agent': 'InBack/1.0 (real estate platform; contact@inback.ru)',
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    kw = {'proxies': PROXIES} if PROXIES else {}
    resp = requests.post(OVERPASS_URL, data={'data': query}, headers=headers, timeout=35, **kw)
    if resp.status_code == 429:
        log.warning('Rate limited, sleeping 60s')
        time.sleep(60)
        resp = requests.post(OVERPASS_URL, data={'data': query}, headers=headers, timeout=35, **kw)
    resp.raise_for_status()
    return resp.json().get('elements', [])


def categorize(elements, lat, lng):
    cats = {c: [] for c in ('transport', 'shopping', 'education', 'healthcare', 'sport', 'leisure')}
    seen = set()

    for el in elements:
        if el.get('type') != 'node':
            continue
        poi_lat = el.get('lat') or (el.get('center') or {}).get('lat')
        poi_lng = el.get('lon') or (el.get('center') or {}).get('lon')
        if not poi_lat or not poi_lng:
            continue

        tags = el.get('tags', {})
        amenity = tags.get('amenity', '')
        shop    = tags.get('shop', '')
        leisure = tags.get('leisure', '')
        highway = tags.get('highway', '')
        railway = tags.get('railway', '')

        cat = None; display = None
        if amenity and amenity in AMENITY_MAP:
            cat, display = AMENITY_MAP[amenity]
        elif shop and shop in SHOP_MAP:
            cat, display = SHOP_MAP[shop]
        elif leisure and leisure in LEISURE_MAP:
            cat, display = LEISURE_MAP[leisure]
        elif highway and highway in HIGHWAY_MAP:
            cat, display = HIGHWAY_MAP[highway]
        elif railway and railway in RAILWAY_MAP:
            cat, display = RAILWAY_MAP[railway]

        if not cat:
            continue

        name = tags.get('name') or display
        dist = haversine_m(lat, lng, poi_lat, poi_lng)
        key  = (name.lower().strip(), cat)
        if key in seen:
            continue
        seen.add(key)

        cats[cat].append({
            'type':         amenity or shop or leisure or highway or railway,
            'type_display': display,
            'name':         name,
            'distance':     dist,
            'coordinates':  [poi_lat, poi_lng],
        })

    # Sort each category by distance, keep top items
    LIMITS = {'transport': 5, 'shopping': 5, 'education': 5, 'healthcare': 4, 'sport': 4, 'leisure': 4}
    for cat in cats:
        cats[cat].sort(key=lambda x: x['distance'])
        cats[cat] = cats[cat][:LIMITS.get(cat, 5)]

    cats['updated_at'] = datetime.now(timezone.utc).isoformat()
    return cats


def run(city_id=None, limit=None, only_missing=True):
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        log.error('DATABASE_URL not set'); sys.exit(1)

    engine  = create_engine(db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    where_parts = ['latitude IS NOT NULL', 'longitude IS NOT NULL']
    if only_missing:
        where_parts.append('nearby IS NULL')
    if city_id:
        where_parts.append(f'city_id = {int(city_id)}')

    sql = f"""
        SELECT id, name, latitude, longitude
        FROM residential_complexes
        WHERE {' AND '.join(where_parts)}
        ORDER BY id
        {'LIMIT ' + str(int(limit)) if limit else ''}
    """
    rows = session.execute(text(sql)).fetchall()
    log.info(f'Found {len(rows)} complexes to update')

    ok = err = 0
    for i, (cid, name, lat, lng) in enumerate(rows, 1):
        log.info(f'[{i}/{len(rows)}] {name} (id={cid})')
        try:
            elements = fetch_poi(float(lat), float(lng))
            data     = categorize(elements, float(lat), float(lng))
            counts   = {k: len(v) for k, v in data.items() if isinstance(v, list)}
            log.info(f'   → POI: {counts}')

            session.execute(text("""
                UPDATE residential_complexes
                SET nearby = :nearby, nearby_updated_at = NOW()
                WHERE id = :cid
            """), {'nearby': json.dumps(data, ensure_ascii=False), 'cid': cid})
            session.commit()
            ok += 1
        except Exception as e:
            log.warning(f'   ✗ {e}')
            session.rollback()
            err += 1

        if i < len(rows):
            time.sleep(DELAY)

    log.info(f'Done: {ok} updated, {err} errors')
    session.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--city', type=int, default=None)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--all', action='store_true', help='Re-fetch even if already populated')
    args = parser.parse_args()
    run(city_id=args.city, limit=args.limit, only_missing=not args.all)
