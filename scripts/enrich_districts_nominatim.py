#!/usr/bin/env python3
"""
Обогащение поля parsed_district у объектов через Nominatim Reverse Geocoding.

Nominatim бесплатный, ограничение: 1 запрос/сек.
Для Краснодара возвращает city_district (напр. "Центральный округ").

Использование:
    python3 scripts/enrich_districts_nominatim.py --city 1 --limit 1000
    python3 scripts/enrich_districts_nominatim.py --city 1 --all
"""

import os
import sys
import time
import argparse
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Property, City

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/reverse'
HEADERS = {'User-Agent': 'InBack/1.0 real-estate platform (contact@inback.ru)'}
DELAY = 1.1  # Nominatim fair use: 1 req/sec


def reverse_geocode(lat, lon):
    """Получить район через Nominatim Reverse Geocoding."""
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={'lat': lat, 'lon': lon, 'format': 'json', 'addressdetails': 1},
            headers=HEADERS,
            timeout=10
        )
        if not resp.ok:
            print(f'  ⚠️  HTTP {resp.status_code}')
            return None
        data = resp.json()
        addr = data.get('address', {})
        district = (
            addr.get('city_district') or
            addr.get('suburb') or
            addr.get('quarter') or
            addr.get('neighbourhood') or
            addr.get('county')
        )
        return district
    except Exception as e:
        print(f'  ❌ Error: {e}')
        return None


def run(city_id, limit, skip_existing):
    with app.app_context():
        city = City.query.get(city_id)
        if not city:
            print(f'❌ Город с id={city_id} не найден')
            return

        print(f'🌍 Обогащение районов через Nominatim — {city.name}')

        query = Property.query.filter(
            Property.city_id == city_id,
            Property.is_active == True,
            Property.latitude.isnot(None),
            Property.longitude.isnot(None)
        )

        if skip_existing:
            query = query.filter(
                (Property.parsed_district == None) | (Property.parsed_district == '')
            )

        total = query.count()
        print(f'📊 Объектов для обработки: {total} (limit={limit})')

        properties = query.limit(limit).all()

        updated = 0
        skipped = 0
        errors = 0

        for i, prop in enumerate(properties, 1):
            district = reverse_geocode(prop.latitude, prop.longitude)

            if district:
                prop.parsed_district = district
                updated += 1
                print(f'  [{i}/{len(properties)}] #{prop.id} → {district!r}')
            else:
                skipped += 1
                if i % 50 == 0:
                    print(f'  [{i}/{len(properties)}] #{prop.id} → нет данных')

            if i % 100 == 0:
                db.session.commit()
                print(f'  💾 Сохранено {i} объектов...')

            time.sleep(DELAY)

        db.session.commit()
        print(f'\n✅ Готово: обновлено={updated}, пропущено={skipped}, ошибок={errors}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Enrich parsed_district via Nominatim')
    parser.add_argument('--city', type=int, default=1, help='City ID (default: 1 = Krasnodar)')
    parser.add_argument('--limit', type=int, default=500, help='Max properties to process')
    parser.add_argument('--all', action='store_true', help='Process all (limit=100000)')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing parsed_district')
    args = parser.parse_args()

    limit = 100000 if args.all else args.limit
    skip_existing = not args.overwrite

    run(args.city, limit, skip_existing)
