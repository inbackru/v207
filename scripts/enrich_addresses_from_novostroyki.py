"""
Дополняет адреса ЖК (address_city_district, address_quarter, addr_street, addr_city)
напрямую из CIAN newobject API — это именно то что показывается на карточках /novostroyki/.

Каждая карточка ЖК на странице /novostroyki/ содержит полную гео-иерархию:
  Краснодарский край → Краснодар → Прикубанский округ → Горхутор мкр → ул. Агрономическая

Реиспользует SESSION, прокси и helper-функции из enrich_complexes.py.
Переменные окружения (опционально): ENRICH_PROXY_URL, ENRICH_ANTICAPTCHA

Запуск:
  python scripts/enrich_addresses_from_novostroyki.py [--city-id 1] [--force] [--dry-run]

  --city-id N  только один город (default: все города из city_config.json)
  --force      перезаписать существующие значения
  --dry-run    не писать в БД, только вывести что нашли
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Импортируем SESSION и helpers из основного скрапера
# Это даёт нам прокси, anti-captcha и ротацию сессий бесплатно
from scripts.enrich_complexes import (
    SESSION,
    REQUEST_DELAY,
    _extract_geo_hierarchy,
    _build_address,
    rotate_session_if_needed,
    _anticaptcha_backoff,
)

from app import app, db
from models import ResidentialComplex

# ── Конфигурация городов ───────────────────────────────────────────────────────

_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'city_config.json')
with open(_CFG_FILE) as _f:
    CITY_CONFIG = json.load(_f)

# ── CIAN API — листинг ЖК (/novostroyki/) ─────────────────────────────────────

def fetch_newobject_page_for_region(cian_region_id: int, page_num: int) -> list:
    """Запрашивает одну страницу ЖК через _type:newobject для заданного региона."""
    query = {
        '_type': 'newobject',
        'engine_version': {'type': 'term', 'value': 2},
        'region': {'type': 'terms', 'value': [cian_region_id]},
        'page': {'type': 'term', 'value': page_num},
    }
    for attempt in range(4):
        try:
            r = SESSION.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json={'jsonQuery': query},
                timeout=30,
            )
            if r.status_code == 200:
                offers = r.json().get('data', {}).get('offersSerialized', [])
                return offers if offers is not None else []
            if r.status_code in (429, 403, 302):
                rotate_session_if_needed(force=True)
                _anticaptcha_backoff(attempt, 'https://www.cian.ru/novostrojki/')
                continue
            print(f'    ⚠️  HTTP {r.status_code} на стр.{page_num}')
            time.sleep(5)
        except Exception as e:
            print(f'    ⚠️  стр.{page_num} попытка {attempt+1}: {e}')
            rotate_session_if_needed(force=True)
            time.sleep(5 + attempt * 5)
    return []


def collect_jk_addresses_from_cian(cian_region_id: int) -> dict:
    """
    Собирает адреса всех ЖК через _type:newobject API (страница /novostroyki/).
    Возвращает dict: {cian_jk_id_str: {okrug, micro, city, street, full_address}}
    """
    result = {}
    print(f'  📡 Сбор ЖК из CIAN novostroyki API (region={cian_region_id})...')

    for pg in range(1, 50):
        offers = fetch_newobject_page_for_region(cian_region_id, pg)
        if not offers:
            if pg > 1:
                print(f'    стр.{pg}: пусто — стоп ({len(result)} ЖК собрано)')
            else:
                print(f'    стр.1: нет данных (блокировка CIAN или регион пуст)')
            break

        new_on_page = 0
        for o in offers:
            nb = o.get('newbuilding') or {}
            jk_id = nb.get('id') or o.get('id')
            if not jk_id:
                continue
            jk_id_str = str(jk_id)
            if jk_id_str in result:
                continue

            geo = o.get('geo') or {}
            _okrug, _micro = _extract_geo_hierarchy(geo)
            _full_addr = _build_address(geo)

            # Извлекаем city и street из geo.address напрямую
            _city = _street = None
            for _part in (geo.get('address') or []):
                _t = (_part.get('type') or '').lower()
                _n = _part.get('name') or _part.get('fullName') or ''
                if _t == 'city' and not _city:
                    _city = _n
                elif _t == 'street' and not _street:
                    _street = _n

            result[jk_id_str] = {
                'jk_name':   nb.get('name') or o.get('name'),
                'okrug':     _okrug,
                'micro':     _micro,
                'city':      _city,
                'street':    _street,
                'full_addr': _full_addr,
            }
            new_on_page += 1

        print(f'    стр.{pg}: {len(offers)} офферов, +{new_on_page} новых ЖК (итого: {len(result)})')
        time.sleep(REQUEST_DELAY)

    return result


# ── Обновление БД ─────────────────────────────────────────────────────────────

def enrich_city_addresses(city_id: int, cian_region_id: int,
                          force: bool, dry_run: bool) -> dict:
    print(f'\n🏙️  Город city_id={city_id} (cian_region={cian_region_id})')

    cian_data = collect_jk_addresses_from_cian(cian_region_id)
    if not cian_data:
        print('  ❌ CIAN не вернул данные. Пропускаем.')
        return {'updated': 0, 'skipped': 0, 'no_match': 0, 'cian_total': 0, 'db_total': 0}

    with app.app_context():
        rcs = (
            db.session.query(ResidentialComplex)
            .filter(
                ResidentialComplex.city_id == city_id,
                ResidentialComplex.complex_id.isnot(None),
                ResidentialComplex.is_active == True,
            )
            .all()
        )

        updated = skipped = no_match = 0
        for rc in rcs:
            cid = str(rc.complex_id)
            info = cian_data.get(cid)
            if not info:
                no_match += 1
                continue

            changed = False

            def _set(field, val):
                nonlocal changed
                if not val:
                    return
                cur_val = getattr(rc, field, None)
                if force or not cur_val:
                    if cur_val != val:
                        if not dry_run:
                            setattr(rc, field, val)
                        changed = True

            _set('address_city_district', info['okrug'])
            _set('address_quarter',       info['micro'])
            _set('addr_city',             info['city'])
            _set('addr_street',           info['street'])

            if changed:
                if dry_run:
                    print(f'    [dry-run] {rc.name}: okrug={info["okrug"]!r} '
                          f'micro={info["micro"]!r} city={info["city"]!r} '
                          f'street={info["street"]!r}')
                updated += 1
            else:
                skipped += 1

        if not dry_run:
            db.session.commit()

        stats = {
            'updated': updated, 'skipped': skipped,
            'no_match': no_match,
            'cian_total': len(cian_data), 'db_total': len(rcs),
        }
        print(f'\n  ✅ city_id={city_id}: обновлено={updated}, '
              f'уже заполнено={skipped}, нет в CIAN={no_match}')
        print(f'     CIAN вернул {len(cian_data)} ЖК, в нашей БД {len(rcs)} активных ЖК')
        return stats


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Заполняет адреса ЖК из CIAN novostroyki API'
    )
    parser.add_argument('--city-id', type=int, default=None,
                        help='ID города (default: все города из city_config.json)')
    parser.add_argument('--force', action='store_true',
                        help='Перезаписать существующие значения')
    parser.add_argument('--dry-run', action='store_true',
                        help='Не писать в БД — только показать что нашли')
    args = parser.parse_args()

    if args.dry_run:
        print('⚠️  DRY-RUN режим — изменения в БД не сохраняются')

    if args.city_id:
        cfg = CITY_CONFIG.get(str(args.city_id))
        if not cfg:
            print(f'❌ city_id={args.city_id} не найден в city_config.json')
            sys.exit(1)
        enrich_city_addresses(
            city_id=args.city_id,
            cian_region_id=cfg['cian_region_id'],
            force=args.force,
            dry_run=args.dry_run,
        )
    else:
        for city_id_str, cfg in CITY_CONFIG.items():
            enrich_city_addresses(
                city_id=int(city_id_str),
                cian_region_id=cfg['cian_region_id'],
                force=args.force,
                dry_run=args.dry_run,
            )


if __name__ == '__main__':
    main()
