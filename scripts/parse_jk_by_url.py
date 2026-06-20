"""
Парсер конкретного ЖК по URL ЦИАН
Использование:
  python scripts/parse_jk_by_url.py https://zhk-admiral-krasnodar-i.cian.ru/
  python scripts/parse_jk_by_url.py https://www.cian.ru/novostrojka-admiral-krasnodar-7046/

Что делает:
  1. Парсит страницу ЖК (фото, описание, застройщик, адрес, координаты)
  2. Ищет квартиры в этом ЖК через API ЦИАН
  3. Всё сохраняет / обновляет в БД
"""

import sys, os, re, json, time, requests
import psycopg2
from datetime import datetime
from html import unescape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.property_utils import sanitize_property_title

try:
    from unidecode import unidecode
except ImportError:
    def unidecode(s):
        return s.encode('ascii', 'ignore').decode()

CITY_ID = 1  # Краснодар по умолчанию

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
    'Content-Type': 'application/json',
})

# Proxy from env or settings file
_proxy_url = os.environ.get('ENRICH_PROXY', '')
if not _proxy_url:
    try:
        _sett_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.enrich_settings.json')
        with open(_sett_path) as _sf:
            _proxy_url = json.load(_sf).get('proxy_url', '')
    except Exception:
        pass
if _proxy_url:
    SESSION.proxies = {'http': _proxy_url, 'https': _proxy_url}
    print(f'🔀 Прокси: {_proxy_url[:40]}...')
SESSION.verify = False


def slug_from_name(name: str) -> str:
    s = unidecode(name).lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')[:100]


def clean_html(text: str) -> str:
    """Убрать HTML-теги и сущности из текста."""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def detect_city_from_url(url: str) -> int:
    """Попытаться определить город из URL."""
    city_map = {
        'krasnodar': 1,
        'sochi': 2,
        'novorossiysk': 3,
        'anapa': 4,
        'gelendzhik': 5,
        'armavir': 6,
        'краснодар': 1,
        'сочи': 2,
    }
    url_lower = url.lower()
    for keyword, city_id in city_map.items():
        if keyword in url_lower:
            return city_id
    return CITY_ID


def resolve_cian_jk_id(url: str) -> int | None:
    """Извлечь числовой ID ЖК из URL или со страницы."""
    # Прямой ID в URL: /novostrojka-name-12345/
    m = re.search(r'-(\d{4,8})/?$', url.rstrip('/'))
    if m:
        return int(m.group(1))
    # Получить со страницы
    try:
        r = SESSION.get(url, timeout=15)
        if r.status_code == 200:
            m = re.search(r'"newBuildingId"\s*:\s*(\d+)', r.text)
            if m:
                return int(m.group(1))
            m = re.search(r'"id"\s*:\s*(\d+).*?"type"\s*:\s*"newBuilding"', r.text)
            if m:
                return int(m.group(1))
    except Exception as e:
        print(f'  ⚠️  Не смогли получить JK ID: {e}')
    return None


def fetch_jk_page_data(url: str) -> dict:
    """Загрузить страницу ЖК и извлечь все данные."""
    print(f'  📄 Загружаем страницу ЖК: {url}')
    try:
        r = SESSION.get(url, timeout=20)
        if r.status_code != 200:
            print(f'  ⚠️  HTTP {r.status_code}')
            return {}
    except Exception as e:
        print(f'  ❌ Ошибка загрузки: {e}')
        return {}

    text = r.text
    result = {'source_url': url}

    # Название ЖК
    name_m = re.search(r'"name"\s*:\s*"([^"]{3,100})"', text)
    if name_m:
        result['name'] = name_m.group(1)
    else:
        title_m = re.search(r'<title>([^<]{5,150})</title>', text, re.IGNORECASE)
        if title_m:
            t = title_m.group(1).split('—')[0].split('|')[0].strip()
            result['name'] = t

    # Описание — берём самое длинное из всех найденных (первый match может быть короткой сноской)
    # Лимит снят (был 5000) — описания могут быть >5000 символов
    desc_candidates = re.findall(r'"description"\s*:\s*"((?:[^"\\]|\\.){30,})"', text)
    if desc_candidates:
        best_raw = max(desc_candidates, key=len)
        try:
            decoded = json.loads('"' + best_raw + '"')
        except Exception:
            decoded = best_raw.replace('\\n', '\n').replace('\\"', '"').replace('\\/', '/')
        cleaned = clean_html(decoded)
        # Skip review-note stubs (e.g. "Рейтинг основан на N отзывах")
        if cleaned and 'рейтинг основан' not in cleaned.lower():
            result['description'] = cleaned
        elif len(cleaned) > 60:
            result['description'] = cleaned

    # Застройщик — три уровня приоритета:
    # 1) Ссылка /zastroishchik-slug-ID/ + текст рядом с ней (самый надёжный)
    # 2) <title>: «ЖК» город, адрес ЗАСТРОЙЩИК
    # 3) JSON: developerName/builderName (может быть из рекламного блока)
    _STREET_TYPES = r'(?:улица|ул\.|проспект|пр\.|пр-кт|бульвар|бульв\.|б-р|' \
                    r'набережная|наб\.|шоссе|ш\.|площадь|пл\.|переулок|пер\.|' \
                    r'дорога|тупик|квартал|кв\.)'
    dev_name = None
    dev_cian_id = None

    # Шаг 1: /zastroishchik-slug-ID/ — ищем ссылку и текст внутри тега <a>
    zast_m = re.search(
        r'<a[^>]+/zastroishchik-[a-z0-9-]+-(\d+)/[^>]*>\s*([^<]{3,120}?)\s*</a>',
        text, re.IGNORECASE
    )
    if zast_m:
        dev_cian_id = int(zast_m.group(1))
        dev_name = zast_m.group(2).strip()
    else:
        # Fallback: просто ID из URL без текста тега
        zast_url = re.search(r'/zastroishchik-[a-z0-9-]+-(\d+)/', text)
        if zast_url:
            dev_cian_id = int(zast_url.group(1))

    if dev_cian_id:
        result['developer_cian_id'] = dev_cian_id

    # Шаг 2: title-based
    if not dev_name:
        title_m2 = re.search(r'<title>([^<]+)</title>', text, re.IGNORECASE)
        if title_m2:
            title_text = title_m2.group(1)
            title_clean = re.sub(r'^[\U0001F300-\U0001FFFF\s]+', '', title_text).strip()
            st_m = re.search(_STREET_TYPES + r'\s+([\w\s]+)$', title_clean, re.IGNORECASE)
            if st_m:
                dev_candidate = st_m.group(1).strip()
                if len(dev_candidate) > 3:
                    dev_name = dev_candidate

    # Шаг 3: JSON fallback
    if not dev_name:
        from collections import Counter
        all_dev_names = re.findall(r'"(?:developerName|builderName)"\s*:\s*"([^"]+)"', text)
        if all_dev_names:
            dev_name = Counter(all_dev_names).most_common(1)[0][0].strip()

    if dev_name:
        result['developer_name'] = dev_name

    # ID ЖК
    jk_id_m = re.search(r'"newBuildingId"\s*:\s*(\d+)', text)
    if jk_id_m:
        result['cian_id'] = int(jk_id_m.group(1))

    # Координаты
    lat_m = re.search(r'"lat(?:itude)?"\s*:\s*([\d.]+)', text)
    lng_m = re.search(r'"(?:lng|lon(?:gitude)?)"\s*:\s*([\d.]+)', text)
    if lat_m:
        result['lat'] = float(lat_m.group(1))
    if lng_m:
        result['lng'] = float(lng_m.group(1))

    # Адрес
    addr_m = re.search(r'"fullAddress"\s*:\s*"([^"]+)"', text)
    if addr_m:
        result['address'] = addr_m.group(1)
    else:
        addr_m2 = re.search(r'"address"\s*:\s*"([^"]{10,200})"', text)
        if addr_m2:
            result['address'] = addr_m2.group(1)

    # Класс жилья
    class_m = re.search(r'"houseClass(?:Name)?"\s*:\s*"([^"]+)"', text)
    if class_m:
        result['building_class'] = class_m.group(1)

    # Фото ЖК
    all_photos = list(dict.fromkeys(
        re.findall(r'https://images\.cdn-cian\.ru[^"\'\\]+\.jpg', text)
    ))
    jk_photos = [p for p in all_photos if '-jk-' in p or 'newbuilding' in p]
    result['photos'] = (jk_photos or all_photos)[:20]

    print(f'  ✅ Данные ЖК: name={result.get("name")}, застройщик={result.get("developer_name")}, '
          f'фото={len(result.get("photos", []))}, cian_id={result.get("cian_id")}')
    return result


def fetch_apartments_for_jk(jk_cian_id: int, city_region_id: int = 4820) -> list:
    """Загрузить квартиры в конкретном ЖК через CIAN API."""
    print(f'\n  🏠 Ищем квартиры для ЖК cian_id={jk_cian_id}...')
    all_apts = []

    for page in range(1, 50):
        payload = {
            'jsonQuery': {
                '_type': 'flatsale',
                'engine_version': {'type': 'term', 'value': 2},
                'region': {'type': 'terms', 'value': [city_region_id]},
                'newobject': {'type': 'term', 'value': True},
                'newbuilding': {'type': 'term', 'value': jk_cian_id},
                'page': {'type': 'term', 'value': page},
            }
        }
        try:
            r = SESSION.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json=payload, timeout=20
            )
            if r.status_code != 200:
                print(f'    ⚠️  Стр {page}: HTTP {r.status_code}')
                break
            data = r.json().get('data', {})
        except Exception as e:
            print(f'    ❌ Стр {page}: {e}')
            break

        offers = data.get('offersSerialized', [])
        if not offers:
            break

        if page == 1:
            total = data.get('aggregatedCount', '?')
            print(f'    📊 Квартир в ЖК на ЦИАН: {total}')

        for o in offers:
            apt = parse_apartment(o)
            if apt['price'] > 0 and apt['area'] > 0:
                all_apts.append(apt)

        print(f'    📄 Стр {page}: {len(offers)} оф., собрано квартир: {len(all_apts)}')
        time.sleep(0.5)

        # Если объявлений меньше страницы — конец
        if len(offers) < 28:
            break

    print(f'  ✅ Всего квартир собрано: {len(all_apts)}')
    return all_apts


def parse_apartment(offer: dict) -> dict:
    """Извлечь данные квартиры из объявления CIAN."""
    nb = offer.get('newbuilding') or {}
    geo = offer.get('geo') or {}
    bargain = offer.get('bargainTerms') or {}
    building = offer.get('building') or {}
    house = nb.get('house') or {}
    decoration = offer.get('decoration') or {}

    coords = geo.get('coordinates') or {}
    addr_parts = [
        a['shortName'] for a in geo.get('address', [])
        if a.get('shortName') and a.get('type') not in ('location',)
    ]
    address = ', '.join(addr_parts) if addr_parts else ''
    district = next(
        (a['name'] for a in geo.get('address', []) if a.get('type') == 'district'), ''
    )
    photos = [p['fullUrl'] for p in offer.get('photos', []) if p.get('fullUrl')][:15]

    dec_type = decoration.get('type', '') if isinstance(decoration, dict) else ''
    renovation_map = {
        'fine': 'Чистовая', 'rough': 'Черновая', 'design': 'Дизайнерский',
        'white_box': 'White Box', 'pre_finishing': 'Предчистовая',
        'without': 'Без отделки', '': 'Без отделки'
    }
    renovation = renovation_map.get(dec_type, dec_type or 'Без отделки')

    finish = house.get('finishDate') or building.get('deadline') or {}
    price = int(bargain.get('priceRur') or bargain.get('price') or 0)
    total_area = float(offer.get('totalArea') or 0)
    price_sqm = int(price / total_area) if total_area > 0 and price > 0 else 0
    rooms = int(offer.get('roomsCount') or 0)

    user = offer.get('user') or {}

    return {
        'cian_id': str(offer.get('cianId') or offer.get('id', '')),
        'rooms': rooms,
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
        'finish_year': finish.get('year'),
        'finish_quarter': finish.get('quarter'),
        'district': district,
        'jk_cian_id': nb.get('id'),
        'jk_name': nb.get('name', ''),
        'jk_url': offer.get('jkUrl', ''),
        'liter_name': house.get('name', ''),
        'developer_name': (user.get('agencyName') or user.get('companyName') or '').strip(),
        'wall_material': building.get('materialType', '') or '',
        'building_class': building.get('classType', '') or '',
    }


def db_connect():
    return psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        database=os.environ.get('PGDATABASE', 'heliumdb'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', ''),
    )


def get_or_create_developer(cur, name: str, dev_cache: dict, cian_id: int | None = None) -> int | None:
    if not name and not cian_id:
        return None

    # 1) Поиск по cian_id (external_id) — самый точный
    if cian_id:
        cur.execute("SELECT id FROM developers WHERE external_id = %s", (str(cian_id),))
        row = cur.fetchone()
        if row:
            if name:
                cur.execute("UPDATE developers SET name=%s, updated_at=%s WHERE id=%s AND (name IS NULL OR name='')",
                            (name[:200], datetime.now(), row[0]))
            if name:
                dev_cache[name.lower()] = row[0]
            return row[0]

    if not name:
        return None

    key = name.lower()
    if key in dev_cache:
        return dev_cache[key]

    # 2) Поиск по имени
    cur.execute("SELECT id FROM developers WHERE LOWER(name) = LOWER(%s)", (name,))
    row = cur.fetchone()
    if row:
        # Обновляем external_id если он ещё не был записан
        if cian_id:
            cur.execute("UPDATE developers SET external_id=%s, updated_at=%s WHERE id=%s AND (external_id IS NULL OR external_id='')",
                        (str(cian_id), datetime.now(), row[0]))
        dev_cache[key] = row[0]
        return row[0]

    # 3) Создаём нового застройщика
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
        "INSERT INTO developers (name, slug, external_id, created_at, updated_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (name[:200], slug, str(cian_id) if cian_id else None, datetime.now(), datetime.now())
    )
    dev_id = cur.fetchone()[0]
    dev_cache[key] = dev_id
    print(f'    🏢 Создан застройщик: {name} (id={dev_id}, cian_id={cian_id})')
    return dev_id


def save_or_update_complex(cur, jk_data: dict, developer_id: int | None, city_id: int) -> int | None:
    """Создать или обновить ЖК в БД. Возвращает DB id."""
    jk_name = jk_data.get('name', '')
    jk_cian_id = jk_data.get('cian_id')
    photos = jk_data.get('photos', [])
    description = jk_data.get('description', '')
    address = jk_data.get('address', '')
    lat = jk_data.get('lat')
    lng = jk_data.get('lng')

    if not jk_name:
        print('  ⚠️  Нет имени ЖК — пропускаем')
        return None

    # Поиск по cian_id
    db_id = None
    if jk_cian_id:
        cur.execute("SELECT id FROM residential_complexes WHERE complex_id = %s", (str(jk_cian_id),))
        row = cur.fetchone()
        if row:
            db_id = row[0]

    # Поиск по имени
    if not db_id:
        cur.execute(
            "SELECT id FROM residential_complexes WHERE LOWER(name) = LOWER(%s) AND city_id = %s",
            (jk_name, city_id)
        )
        row = cur.fetchone()
        if row:
            db_id = row[0]

    now = datetime.now()

    if db_id:
        # Обновляем существующий ЖК
        updates = ['updated_at = %s']
        vals = [now]

        if photos:
            updates.append('main_image = %s')
            vals.append(photos[0][:500])
            updates.append('gallery_images = %s')
            vals.append(json.dumps(photos, ensure_ascii=False))

        if description:
            updates.append('description = %s')
            vals.append(description[:3000])

        if address:
            updates.append('address = %s')
            vals.append(address[:300])

        if developer_id:
            updates.append('developer_id = %s')
            vals.append(developer_id)

        if lat:
            updates.append('latitude = %s')
            vals.append(lat)
        if lng:
            updates.append('longitude = %s')
            vals.append(lng)

        if jk_cian_id:
            updates.append('complex_id = %s')
            vals.append(str(jk_cian_id))

        vals.append(db_id)
        cur.execute(f"UPDATE residential_complexes SET {', '.join(updates)} WHERE id = %s", vals)
        print(f'  ✅ ЖК обновлён: {jk_name} (id={db_id})')
    else:
        # Создаём новый
        slug = slug_from_name(jk_name)
        base = slug
        i = 0
        while True:
            cur.execute("SELECT id FROM residential_complexes WHERE slug = %s AND city_id = %s", (slug, city_id))
            if not cur.fetchone():
                break
            i += 1
            slug = f"{base}-{i}"

        cur.execute("""
            INSERT INTO residential_complexes
              (name, slug, developer_id, city_id, complex_id, cashback_rate,
               main_image, gallery_images, description, address,
               latitude, longitude, is_active, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            jk_name[:100], slug, developer_id, city_id,
            str(jk_cian_id) if jk_cian_id else None,
            0.0,
            photos[0][:500] if photos else '',
            json.dumps(photos, ensure_ascii=False),
            description[:3000] if description else '',
            address[:300] if address else '',
            lat, lng,
            True, now, now,
        ))
        db_id = cur.fetchone()[0]
        print(f'  ✅ ЖК создан: {jk_name} (id={db_id})')

    return db_id


def save_apartments(cur, apts: list, complex_db_id: int, developer_id: int | None,
                    city_id: int, existing_ids: set, existing_urls: set) -> tuple[int, int]:
    """Сохранить квартиры. Возвращает (добавлено, пропущено)."""
    added = skipped = 0
    now = datetime.now()

    for apt in apts:
        if apt['cian_id'] and apt['cian_id'] in existing_ids:
            skipped += 1
            continue
        if apt['source_url'] and apt['source_url'] in existing_urls:
            skipped += 1
            continue

        rooms = apt['rooms'] if apt['rooms'] is not None else 0
        rooms_label = {0: 'Студия', 1: '1-комн.', 2: '2-комн.', 3: '3-комн.'}.get(
            rooms, f"{rooms}-комн."
        )
        liter_part = f", {apt['liter_name']}" if apt['liter_name'] else ''
        title = f"{rooms_label} {apt['area']:.1f} м²{liter_part}"
        slug = f"kv-{apt['cian_id']}"

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
                ON CONFLICT (inner_id) DO UPDATE SET
                  price = EXCLUDED.price,
                  price_per_sqm = EXCLUDED.price_per_sqm,
                  main_image = CASE WHEN EXCLUDED.main_image != '' THEN EXCLUDED.main_image ELSE properties.main_image END,
                  gallery_images = CASE WHEN EXCLUDED.gallery_images != '[]' THEN EXCLUDED.gallery_images ELSE properties.gallery_images END,
                  updated_at = EXCLUDED.updated_at
            """, (
                sanitize_property_title(title, rooms=apt['rooms'], area=apt['area'], floor=apt['floor'], total_floors=apt['total_floors'])[:200], slug[:200],
                rooms, apt['area'], apt['floor'], apt['total_floors'],
                apt['price'], apt['price_sqm'], complex_db_id, developer_id, city_id,
                'available', True,
                apt['image'][:500] if apt['image'] else '',
                json.dumps(apt['images'], ensure_ascii=False),
                apt['address'][:300] if apt['address'] else '',
                apt['lat'], apt['lng'],
                apt['source_url'], apt['cian_id'],
                now, now, now,
                'Квартира', 'Краснодар',
                apt['district'][:100] if apt['district'] else '',
                apt['renovation'],
                apt['is_apartment'],
                apt['living_area'], apt['kitchen_area'],
                apt['liter_name'][:100] if apt['liter_name'] else '',
            ))
            added += 1
            if apt['cian_id']:
                existing_ids.add(apt['cian_id'])
            if apt['source_url']:
                existing_urls.add(apt['source_url'])
        except Exception as e:
            print(f'    ❌ Квартира {apt["cian_id"]}: {e}')
            skipped += 1

    return added, skipped


def run(jk_url: str, city_id: int | None = None, cian_region_id: int = 4820):
    print('=' * 65)
    print(f'🏗️  Парсер ЖК по URL: {jk_url}')
    print('=' * 65)

    if city_id is None:
        city_id = detect_city_from_url(jk_url)

    # ── 1. Парсим страницу ЖК ────────────────────────────────────────
    print('\n📄 Шаг 1: Загружаем данные ЖК...')
    jk_data = fetch_jk_page_data(jk_url)
    if not jk_data:
        print('❌ Не удалось загрузить данные ЖК')
        return

    jk_cian_id = jk_data.get('cian_id') or resolve_cian_jk_id(jk_url)
    if not jk_cian_id:
        print('⚠️  Не удалось определить CIAN ID ЖК — квартиры не будем искать')

    # ── 2. Сохраняем ЖК и застройщика ───────────────────────────────
    print('\n💾 Шаг 2: Сохраняем ЖК в БД...')
    conn = db_connect()
    conn.autocommit = False
    cur = conn.cursor()

    dev_cache = {}
    cur.execute("SELECT LOWER(name), id FROM developers")
    for row in cur.fetchall():
        dev_cache[row[0]] = row[1]

    developer_id = get_or_create_developer(
        cur, jk_data.get('developer_name', ''), dev_cache,
        cian_id=jk_data.get('developer_cian_id')
    )
    jk_db_id = save_or_update_complex(cur, jk_data, developer_id, city_id)
    conn.commit()

    if not jk_db_id:
        print('❌ Не удалось создать/обновить ЖК')
        conn.close()
        return

    # ── 3. Ищем квартиры ─────────────────────────────────────────────
    apts = []
    if jk_cian_id:
        print(f'\n🏠 Шаг 3: Ищем квартиры в ЖК (cian_id={jk_cian_id})...')
        apts = fetch_apartments_for_jk(jk_cian_id, cian_region_id)
    else:
        print('\n⚠️  Шаг 3: CIAN ID ЖК не найден — пропускаем поиск квартир')

    # ── 4. Сохраняем квартиры ────────────────────────────────────────
    if apts:
        print(f'\n💾 Шаг 4: Сохраняем {len(apts)} квартир...')
        cur.execute("SELECT inner_id FROM properties WHERE inner_id IS NOT NULL")
        existing_ids = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT source_url FROM properties WHERE source_url IS NOT NULL")
        existing_urls = {row[0] for row in cur.fetchall()}

        added, skipped = save_apartments(
            cur, apts, jk_db_id, developer_id, city_id, existing_ids, existing_urls
        )
        conn.commit()
        print(f'  ✅ Добавлено: {added}, обновлено/пропущено: {skipped}')
    else:
        print('\nℹ️  Квартир не найдено (возможно ЖК завершён или нет активных продаж)')

    cur.close()
    conn.close()

    # ── Итог ─────────────────────────────────────────────────────────
    print(f'\n{"=" * 65}')
    print(f'🎉 Готово!')
    print(f'   ЖК: {jk_data.get("name")} (DB id={jk_db_id})')
    print(f'   Застройщик: {jk_data.get("developer_name") or "не найден"}')
    print(f'   Фото ЖК: {len(jk_data.get("photos", []))}')
    print(f'   Квартир добавлено: {len(apts)}')
    print('=' * 65)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Использование: python scripts/parse_jk_by_url.py <URL_ЖК_ЦИАН> [city_id]')
        print('Пример: python scripts/parse_jk_by_url.py https://zhk-admiral-krasnodar-i.cian.ru/')
        sys.exit(1)

    url = sys.argv[1]
    city = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run(url, city)
