"""
Парсер новостроек Краснодара v2
Структура: Застройщик → ЖК → Литера (complex_building_name) → Квартиры
Region: 4820 = Краснодар-город (только город, не вся область)
Фильтр: from_developer=True (только первичка, без вторички)
"""

import sys, os, time, json, re, requests
import psycopg2
from datetime import datetime
from unidecode import unidecode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.property_utils import sanitize_property_title

CITY_ID = 1            # Краснодар в нашей БД
CIAN_REGION_ID = 4820  # Краснодар-город в CIAN (не 4584=весь край)
TOTAL_PAGES = 20       # 20 страниц × 28 = ~560 объявлений от застройщиков

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
    'Content-Type': 'application/json',
    'Origin': 'https://krasnodar.cian.ru',
    'Referer': 'https://krasnodar.cian.ru/novostroyki/',
})


def slug_from_name(name: str) -> str:
    s = unidecode(name).lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')[:100]


def fetch_page(page_num: int):
    """Получить страницу квартир от застройщиков в Краснодаре."""
    payload = {
        'jsonQuery': {
            '_type': 'flatsale',
            'engine_version': {'type': 'term', 'value': 2},
            'region': {'type': 'terms', 'value': [CIAN_REGION_ID]},
            'newobject': {'type': 'term', 'value': True},
            'from_developer': {'type': 'term', 'value': True},
            'page': {'type': 'term', 'value': page_num},
        }
    }
    try:
        r = SESSION.post(
            'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
            json=payload, timeout=20
        )
        if r.status_code == 200:
            return r.json().get('data', {})
        print(f'  ⚠️  Страница {page_num}: HTTP {r.status_code}')
    except Exception as e:
        print(f'  ❌ Страница {page_num}: {e}')
    return None


def fetch_jk_page(jk_url: str) -> dict:
    """Попытаться получить данные ЖК с его страницы (описание, фото, застройщик)."""
    if not jk_url:
        return {}
    try:
        r = SESSION.get(jk_url, timeout=15)
        if r.status_code != 200:
            return {}
        text = r.text

        result = {}

        # Описание ЖК из JSON-LD Product
        desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.){20,2000})"', text)
        if desc_match:
            raw = desc_match.group(1).replace('\\n', '\n').replace('\\"', '"')
            # Убираем HTML-сущности
            raw = raw.replace('&laquo;', '«').replace('&raquo;', '»')
            raw = raw.replace('&ndash;', '–').replace('&mdash;', '—')
            raw = raw.replace('&nbsp;', ' ').replace('&amp;', '&')
            raw = raw.replace('&#171;', '«').replace('&#187;', '»')
            result['description'] = raw

        # Имя застройщика из meta/data
        dev_match = re.search(r'"developerName"\s*:\s*"([^"]+)"', text)
        if dev_match:
            result['developer_name'] = dev_match.group(1)

        # Все фото ЖК
        photos = list(dict.fromkeys(
            re.findall(r'https://images\.cdn-cian\.ru[^"\']+\.jpg', text)
        ))
        jk_photos = [p for p in photos if '-jk-' in p or 'newbuilding' in p]
        result['jk_photos'] = (jk_photos or photos)[:15]

        return result
    except Exception as e:
        return {}


def parse_offer(offer: dict) -> dict:
    """Извлечь структурированные данные из объявления CIAN."""
    nb = offer.get('newbuilding') or {}
    geo = offer.get('geo') or {}
    bargain = offer.get('bargainTerms') or {}
    building = offer.get('building') or {}
    house = nb.get('house') or {}
    user = offer.get('user') or {}
    decoration = offer.get('decoration') or {}

    # Координаты
    coords = geo.get('coordinates') or {}

    # Адрес: убираем регион/город, оставляем район+улицу+дом
    addr_parts = [
        a['shortName'] for a in geo.get('address', [])
        if a.get('shortName') and a.get('type') not in ('location',)
    ]
    address = ', '.join(addr_parts) if addr_parts else ''

    # Район
    district = next(
        (a['name'] for a in geo.get('address', []) if a.get('type') == 'district'), ''
    )

    # Фото квартиры (до 15)
    photos = [p['fullUrl'] for p in offer.get('photos', []) if p.get('fullUrl')][:15]

    # Отделка
    dec_type = decoration.get('type', '') if isinstance(decoration, dict) else ''
    renovation_map = {
        'fine': 'Чистовая', 'rough': 'Черновая', 'design': 'Дизайнерский',
        'white_box': 'White Box', 'pre_finishing': 'Предчистовая',
        'without': 'Без отделки', '': 'Без отделки'
    }
    renovation = renovation_map.get(dec_type, dec_type or 'Без отделки')

    # Срок сдачи: сначала из литеры (house), потом из здания
    finish = house.get('finishDate') or building.get('deadline') or {}
    finish_year = finish.get('year')
    finish_q = finish.get('quarter')

    # Цена
    price = int(bargain.get('priceRur') or bargain.get('price') or 0)
    total_area = float(offer.get('totalArea') or 0)
    price_sqm = int(price / total_area) if total_area > 0 and price > 0 else 0

    return {
        # Квартира
        'cian_id': str(offer.get('cianId') or offer.get('id', '')),
        'rooms': int(offer.get('roomsCount') or 0),
        'area': total_area,
        'living_area': float(offer.get('livingArea') or 0) or None,
        'kitchen_area': float(offer.get('kitchenArea') or 0) or None,
        'floor': int(offer.get('floorNumber') or 1),
        'total_floors': int(building.get('floorsCount') or 1),
        'price': price,
        'price_sqm': price_sqm,
        'renovation': renovation,
        'images': photos,
        'image': photos[0] if photos else '',
        'address': address,
        'lat': coords.get('lat'),
        'lng': coords.get('lng'),
        'source_url': offer.get('fullUrl', '')[:300],
        'is_apartment': bool(offer.get('isApartments')),
        'finish_year': finish_year,
        'finish_quarter': finish_q,
        'district': district,

        # ЖК
        'jk_cian_id': nb.get('id'),
        'jk_name': nb.get('name', ''),
        'jk_url': offer.get('jkUrl', ''),
        'is_premium': nb.get('isPremium', False),

        # Литера (корпус/секция)
        'liter_name': house.get('name', ''),
        'liter_cian_id': house.get('id'),
        'liter_finished': bool(house.get('isFinished')),
        'section': house.get('section', ''),

        # Застройщик
        'builder_ids': offer.get('buildersIds', []) or [],
        'developer_name': (
            user.get('agencyName') or user.get('companyName') or ''
        ).strip(),

        # Технические параметры здания
        'wall_material': building.get('materialType', '') or '',
        'building_class': building.get('classType', '') or '',
    }


def get_or_create_developer(cur, name: str) -> int | None:
    if not name:
        return None
    cur.execute("SELECT id FROM developers WHERE LOWER(name) = LOWER(%s)", (name,))
    row = cur.fetchone()
    if row:
        return row[0]

    slug = slug_from_name(name)
    base = slug
    i = 0
    while True:
        cur.execute("SELECT id FROM developers WHERE slug = %s", (slug,))
        if not cur.fetchone():
            break
        i += 1
        slug = f"{base}-{i}"

    cur.execute(
        "INSERT INTO developers (name, slug, created_at, updated_at) VALUES (%s, %s, %s, %s) RETURNING id",
        (name[:200], slug, datetime.now(), datetime.now())
    )
    dev_id = cur.fetchone()[0]
    print(f"    🏢 Застройщик: {name} (id={dev_id})")
    return dev_id


def get_or_create_complex(cur, apt: dict, developer_id: int | None) -> int | None:
    jk_name = apt['jk_name']
    jk_cian_id = apt['jk_cian_id']
    if not jk_name:
        return None

    # Поиск по cian ID
    if jk_cian_id:
        cur.execute("SELECT id FROM residential_complexes WHERE complex_id = %s", (str(jk_cian_id),))
        row = cur.fetchone()
        if row:
            return row[0]

    # Поиск по имени + город
    cur.execute(
        "SELECT id FROM residential_complexes WHERE LOWER(name) = LOWER(%s) AND city_id = %s",
        (jk_name, CITY_ID)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    # Создаём новый ЖК
    slug = slug_from_name(jk_name)
    base = slug
    i = 0
    while True:
        cur.execute("SELECT id FROM residential_complexes WHERE slug = %s AND city_id = %s", (slug, CITY_ID))
        if not cur.fetchone():
            break
        i += 1
        slug = f"{base}-{i}"

    images = json.dumps(apt['images'], ensure_ascii=False)

    cur.execute("""
        INSERT INTO residential_complexes
          (name, slug, developer_id, city_id, complex_id, cashback_rate,
           main_image, gallery_images, latitude, longitude,
           wall_material, is_active, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        jk_name[:100], slug, developer_id, CITY_ID,
        str(jk_cian_id) if jk_cian_id else None,
        0.0,
        apt['image'][:500] if apt['image'] else '',
        images,
        apt['lat'], apt['lng'],
        apt['wall_material'][:100] if apt['wall_material'] else '',
        True,
        datetime.now(), datetime.now(),
    ))
    jk_id = cur.fetchone()[0]
    print(f"    🏗  ЖК: {jk_name} (id={jk_id})")
    return jk_id


def enrich_complex(cur, jk_db_id: int, jk_url: str, jk_name: str):
    """Обогатить ЖК данными с его страницы (описание, доп. фото, застройщик)."""
    if not jk_url:
        return
    data = fetch_jk_page(jk_url)
    if not data:
        return

    updates = []
    values = []

    if data.get('description'):
        updates.append("description = %s")
        values.append(data['description'][:2000])

    if data.get('jk_photos'):
        updates.append("gallery_images = %s")
        values.append(json.dumps(data['jk_photos'], ensure_ascii=False))
        updates.append("main_image = %s")
        values.append(data['jk_photos'][0][:500])

    if updates:
        values.append(jk_db_id)
        cur.execute(
            f"UPDATE residential_complexes SET {', '.join(updates)} WHERE id = %s",
            values
        )


def save_to_db(all_apts: list) -> int:
    """Сохранить все квартиры по структуре: Застройщик → ЖК → Квартиры.
    Стратегия:
    1. Создаём всех застройщиков (одна транзакция)
    2. Создаём все ЖК (одна транзакция)
    3. Вставляем квартиры с ON CONFLICT DO NOTHING (по inner_id)
    """
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        database=os.environ.get('PGDATABASE', 'heliumdb'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', ''),
    )
    conn.autocommit = False
    cur = conn.cursor()

    print(f"\n💾 Загружаем кэш существующих данных...")

    # Предзагрузка кэшей
    cur.execute("SELECT source_url FROM properties WHERE source_url IS NOT NULL")
    existing_urls = {row[0] for row in cur.fetchall()}

    cur.execute("SELECT inner_id FROM properties WHERE inner_id IS NOT NULL")
    existing_inner_ids = {row[0] for row in cur.fetchall()}

    cur.execute("SELECT complex_id, id FROM residential_complexes WHERE complex_id IS NOT NULL")
    jk_cache = {row[0]: row[1] for row in cur.fetchall()}  # cian_id_str → db_id

    cur.execute("SELECT LOWER(name), id FROM developers")
    dev_cache = {row[0]: row[1] for row in cur.fetchall()}

    print(f"  Кэш: {len(existing_urls)} URL, {len(existing_inner_ids)} inner_ids, "
          f"{len(jk_cache)} ЖК, {len(dev_cache)} застройщиков")

    now = datetime.now()

    # ── ШАГ 1: создаём всех застройщиков ──────────────────────────────────────
    print(f"\n🏢 Шаг 1: Застройщики...")
    dev_names = {a['developer_name'] for a in all_apts if a['developer_name']}
    for name in sorted(dev_names):
        key = name.lower()
        if key not in dev_cache:
            try:
                dev_id = get_or_create_developer(cur, name)
                if dev_id:
                    dev_cache[key] = dev_id
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"  ⚠️  Застройщик '{name}': {e}")

    # Перезагружаем кэш застройщиков после вставок
    cur.execute("SELECT LOWER(name), id FROM developers")
    dev_cache = {row[0]: row[1] for row in cur.fetchall()}

    # ── ШАГ 2: создаём все ЖК ─────────────────────────────────────────────────
    print(f"\n🏗  Шаг 2: Жилые комплексы...")
    # Для каждого уникального ЖК берём первое объявление как источник данных
    seen_jk = {}
    for apt in all_apts:
        jk_id = apt['jk_cian_id']
        if jk_id and str(jk_id) not in jk_cache and jk_id not in seen_jk:
            seen_jk[jk_id] = apt

    for jk_cian_id, apt in seen_jk.items():
        developer_id = dev_cache.get((apt['developer_name'] or '').lower())
        try:
            jk_db_id = get_or_create_complex(cur, apt, developer_id)
            if jk_db_id:
                jk_cache[str(jk_cian_id)] = jk_db_id
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  ⚠️  ЖК '{apt['jk_name']}': {e}")

    # Перезагружаем кэш ЖК
    cur.execute("SELECT complex_id, id FROM residential_complexes WHERE complex_id IS NOT NULL")
    jk_cache = {row[0]: row[1] for row in cur.fetchall()}

    # ── ШАГ 3: вставляем квартиры ─────────────────────────────────────────────
    print(f"\n🏠 Шаг 3: Квартиры...")
    added = 0
    skipped = 0

    for i, apt in enumerate(all_apts, 1):
        # Дедупликация
        if apt['source_url'] and apt['source_url'] in existing_urls:
            skipped += 1
            continue
        if apt['cian_id'] and apt['cian_id'] in existing_inner_ids:
            skipped += 1
            continue

        developer_id = dev_cache.get((apt['developer_name'] or '').lower())
        jk_cian = str(apt['jk_cian_id']) if apt['jk_cian_id'] else None
        complex_db_id = jk_cache.get(jk_cian) if jk_cian else None

        prop_slug = f"kv-{apt['cian_id']}"

        rooms = apt['rooms'] if apt['rooms'] is not None else 0
        rooms_label = {0: 'Студия', 1: '1-комн.', 2: '2-комн.', 3: '3-комн.'}.get(
            rooms, f"{rooms}-комн."
        )
        jk_part = f", ЖК {apt['jk_name']}" if apt['jk_name'] else ''
        liter_part = f", {apt['liter_name']}" if apt['liter_name'] else ''
        title = f"{rooms_label} {apt['area']:.1f} м²{jk_part}{liter_part}"

        try:
            cur.execute("""
                INSERT INTO properties
                  (title, slug, rooms, area, floor, total_floors,
                   price, price_per_sqm, complex_id, developer_id, city_id,
                   status, is_active, main_image, gallery_images,
                   address, latitude, longitude, source_url, inner_id,
                   scraped_at, created_at, updated_at,
                   property_type, parsed_city, parsed_district,
                   renovation_type, is_apartment, living_area, kitchen_area,
                   complex_building_name)
                VALUES
                  (%s,%s,%s,%s,%s,%s,
                   %s,%s,%s,%s,%s,
                   %s,%s,%s,%s,
                   %s,%s,%s,%s,%s,
                   %s,%s,%s,
                   %s,%s,%s,
                   %s,%s,%s,%s,
                   %s)
                ON CONFLICT (inner_id) DO NOTHING
            """, (
                sanitize_property_title(title, rooms=apt['rooms'], area=apt['area'], floor=apt['floor'], total_floors=apt['total_floors'])[:200], prop_slug[:200],
                apt['rooms'], apt['area'], apt['floor'], apt['total_floors'],
                apt['price'], apt['price_sqm'], complex_db_id, developer_id, CITY_ID,
                'available', True,
                apt['image'][:500] if apt['image'] else '',
                json.dumps(apt['images'], ensure_ascii=False),
                apt['address'][:300] if apt['address'] else '',
                apt['lat'], apt['lng'],
                apt['source_url'],
                apt['cian_id'],
                now, now, now,
                'Квартира', 'Краснодар',
                apt['district'][:100] if apt['district'] else '',
                apt['renovation'],
                apt['is_apartment'],
                apt['living_area'], apt['kitchen_area'],
                apt['liter_name'][:100] if apt['liter_name'] else '',
            ))
            added += 1
            existing_inner_ids.add(apt['cian_id'])
            if apt['source_url']:
                existing_urls.add(apt['source_url'])

        except Exception as e:
            conn.rollback()
            cur = conn.cursor()
            print(f"  ❌ Квартира {i}: {e}")
            skipped += 1
            continue

    conn.commit()
    cur.close()
    conn.close()
    print(f"  ✅ Добавлено: {added}, пропущено (дубли): {skipped}")
    return added


def run():
    print("=" * 60)
    print("🏗️  Парсер новостроек Краснодара v2")
    print("   Источник: CIAN, только Краснодар-город (4820)")
    print("   Только от застройщиков (первичка)")
    print("   Структура: Застройщик → ЖК → Литера → Квартиры")
    print("=" * 60)

    all_apts = []

    for page in range(1, TOTAL_PAGES + 1):
        print(f"\n📄 Страница {page}/{TOTAL_PAGES}...")
        data = fetch_page(page)
        if not data:
            print("  ⚠️  Нет данных, пропуск")
            continue

        offers = data.get('offersSerialized', [])
        total_count = data.get('aggregatedCount', '?')

        if page == 1:
            print(f"  📊 Всего объявлений от застройщиков: {total_count}")

        from_builder = 0
        for o in offers:
            nb = o.get('newbuilding') or {}
            if not nb.get('isFromBuilder') and not nb.get('isFromDeveloper') and not o.get('fromDeveloper'):
                continue  # вторичка просочилась — пропускаем
            apt = parse_offer(o)
            if apt['price'] <= 0 or apt['area'] <= 0:
                continue  # неполные данные
            if not apt['jk_name']:
                continue  # нет ЖК — пропускаем
            all_apts.append(apt)
            from_builder += 1

        print(f"  ✅ Квартир от застройщиков: {from_builder}/{len(offers)}")
        time.sleep(0.8)

    # Статистика
    jk_set = {a['jk_cian_id'] for a in all_apts if a['jk_cian_id']}
    dev_set = {a['developer_name'] for a in all_apts if a['developer_name']}
    lit_set = {a['liter_name'] for a in all_apts if a['liter_name']}
    print(f"\n{'='*60}")
    print(f"✅ Собрано квартир: {len(all_apts)}")
    print(f"✅ Уникальных ЖК: {len(jk_set)}")
    print(f"✅ Уникальных застройщиков: {len(dev_set)}")
    print(f"✅ Уникальных литер: {len(lit_set)}")

    if not all_apts:
        print("❌ Нет данных для сохранения!")
        return

    added = save_to_db(all_apts)

    # Итог
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        database=os.environ.get('PGDATABASE', 'heliumdb'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', ''),
    )
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM properties WHERE city_id=%s", (CITY_ID,))
    total_props = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM residential_complexes WHERE city_id=%s", (CITY_ID,))
    total_jk = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM developers", ())
    total_devs = cur.fetchone()[0]
    conn.close()

    print(f"\n{'='*60}")
    print(f"🎉 Готово! Добавлено квартир: {added}")
    print(f"\n📊 Итого в БД по Краснодару:")
    print(f"   Квартир: {total_props}")
    print(f"   ЖК: {total_jk}")
    print(f"   Застройщиков: {total_devs}")
    print("=" * 60)


if __name__ == '__main__':
    run()
