#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер новостроек Краснодара через CIAN API
Реальные данные — без фейка.
"""

import sys
import os
import json
import time
import re
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CITY_ID = 1  # Краснодар в нашей БД
KRASNODAR_REGION_ID = 4774  # ID Краснодарского края в CIAN
KRASNODAR_CITY_ID_CIAN = 4584  # ID города Краснодар в CIAN (4998 = Сочи, 4774 = весь край)

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
    'Content-Type': 'application/json',
    'Origin': 'https://www.cian.ru',
    'Referer': 'https://www.cian.ru/',
})


def fetch_cian_newbuildings(page=1):
    """Получает список новостроек Краснодара через CIAN search API"""
    url = "https://api.cian.ru/search-offers/v2/search-offers-desktop/"
    payload = {
        "jsonQuery": {
            "_type": "flatsale",
            "engine_version": {"type": "term", "value": 2},
            "region": {"type": "terms", "value": [KRASNODAR_CITY_ID_CIAN]},
            "newobject": {"type": "term", "value": True},
            "page": {"type": "term", "value": page},
            "room": {"type": "terms", "value": [1, 2, 3, 4, 9]}
        }
    }
    try:
        resp = SESSION.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        print(f"  CIAN вернул статус {resp.status_code}")
        return None
    except Exception as e:
        print(f"  Ошибка запроса CIAN: {e}")
        return None


def fetch_domclick_complexes():
    """Получает ЖК из Domclick через их публичный sitemap/API"""
    url = "https://domclick.ru/sitemap/novostrojki_krasnodar.xml"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/xml,application/xml',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception as e:
        print(f"  Domclick sitemap ошибка: {e}")
        return None


def slug_from_name(name):
    """Транслитерация русского имени в slug"""
    TRANSLIT = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh',
        'з':'z','и':'i','й':'j','к':'k','л':'l','м':'m','н':'n','о':'o',
        'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'c',
        'ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    }
    result = name.lower()
    out = []
    for ch in result:
        out.append(TRANSLIT.get(ch, ch))
    result = ''.join(out)
    result = re.sub(r'[^a-z0-9\s-]', '', result)
    result = re.sub(r'[\s_]+', '-', result)
    result = result.strip('-')
    return result or 'complex'


def save_to_db(complexes, properties):
    """Сохраняет данные в PostgreSQL"""
    import psycopg2

    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'helium'),
        port=os.environ.get('PGPORT', 5432),
        dbname=os.environ.get('PGDATABASE', 'heliumdb'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', '')
    )
    cur = conn.cursor()

    complex_id_map = {}

    for c in complexes:
        slug = slug_from_name(c['name'])
        # Уникальный slug если уже есть
        cur.execute("SELECT id FROM residential_complexes WHERE slug=%s", (slug,))
        exists = cur.fetchone()
        if exists:
            complex_id_map[c['cian_id']] = exists[0]
            print(f"  ✅ ЖК уже есть: {c['name']} (id={exists[0]})")
            continue

        cur.execute("""
            INSERT INTO residential_complexes
              (name, slug, cashback_rate, is_active, created_at, updated_at,
               address, latitude, longitude, main_image, description,
               buildings_count, city_id, address_city_district, address_quarter)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            c['name'][:100], slug, 3.0, True,
            datetime.now(), datetime.now(),
            c.get('address', '')[:300] if c.get('address') else '',
            c.get('lat'), c.get('lon'),
            c.get('image', '')[:500] if c.get('image') else '',
            c.get('description', ''),
            c.get('buildings_count', 1),
            CITY_ID,
            c.get('address_city_district', '')[:149] if c.get('address_city_district') else None,
            c.get('address_quarter', '')[:149] if c.get('address_quarter') else None,
        ))
        row = cur.fetchone()
        new_id = row[0]
        complex_id_map[c['cian_id']] = new_id
        print(f"  ➕ Добавлен ЖК: {c['name']} (id={new_id})")

    conn.commit()

    props_added = 0
    for p in properties:
        # Проверка дублей по source_url или inner_id
        if p.get('source_url'):
            cur.execute("SELECT id FROM properties WHERE source_url=%s", (p['source_url'],))
            if cur.fetchone():
                continue

        complex_db_id = complex_id_map.get(p.get('cian_complex_id'))

        # Генерируем уникальный slug с суффиксом если нужно
        base_slug = slug_from_name(p['title'])[:190]
        prop_slug = base_slug
        counter = 0
        while True:
            cur.execute("SELECT id FROM properties WHERE city_id=%s AND slug=%s", (CITY_ID, prop_slug))
            if not cur.fetchone():
                break
            counter += 1
            prop_slug = f"{base_slug}-{counter}"

        cur.execute("""
            INSERT INTO properties
              (title, slug, rooms, area, floor, total_floors, price, price_per_sqm,
               complex_id, city_id, status, is_active,
               main_image, gallery_images,
               address, latitude, longitude,
               source_url, inner_id, scraped_at, created_at, updated_at,
               property_type, parsed_city, parsed_district,
               renovation_type, is_apartment, living_area, kitchen_area)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s)
        """, (
            p['title'][:200], prop_slug[:200],
            p.get('rooms', 0), p.get('area', 0),
            p.get('floor', 1), p.get('total_floors', 1),
            p.get('price', 0), p.get('price_per_sqm', 0),
            complex_db_id, CITY_ID, 'available', True,
            p.get('image', '')[:300] if p.get('image') else '',
            json.dumps(p.get('images', []), ensure_ascii=False),
            p.get('address', '')[:300] if p.get('address') else '',
            p.get('lat'), p.get('lon'),
            p.get('source_url', '')[:300] if p.get('source_url') else '',
            str(p.get('inner_id', '')),
            datetime.now(), datetime.now(), datetime.now(),
            'Квартира', 'Краснодар',
            p.get('district', ''),
            p.get('renovation', ''),
            False,
            p.get('living_area'), p.get('kitchen_area')
        ))
        props_added += 1

    conn.commit()
    cur.close()
    conn.close()
    return props_added


def safe_float(val):
    """Безопасное преобразование в float"""
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def safe_int(val):
    """Безопасное преобразование в int"""
    try:
        return int(val) if val is not None else 0
    except (TypeError, ValueError):
        return 0


def parse_cian_offer(offer):
    """Извлекает нужные поля из объекта CIAN offer"""
    try:
        geo = offer.get('geo', {})
        address_parts = geo.get('address', [])
        address_str = ', '.join(
            a.get('fullName', a.get('name', ''))
            for a in address_parts
            if a.get('type') not in ['country', 'region']
        )

        coords = geo.get('coordinates', {})
        lat = coords.get('lat')
        lon = coords.get('lng')

        rooms = safe_int(offer.get('roomsCount', 0))
        # Студия — 0 комнат
        short_info = offer.get('formattedShortInfo', '')
        if 'студ' in short_info.lower() or rooms == 0:
            rooms = 0
        title_rooms = 'Студия' if rooms == 0 else f'{rooms}-комн'

        area = safe_float(offer.get('totalArea', 0))
        floor = safe_int(offer.get('floorNumber', 1))
        building = offer.get('building', {}) or {}
        total_floors = safe_int(building.get('floorsCount') or floor)
        if total_floors < floor:
            total_floors = floor

        price = safe_int((offer.get('bargainTerms') or {}).get('price', 0))
        price_per_sqm = int(price / area) if area > 0 and price > 0 else 0

        photos = offer.get('photos', []) or []
        main_image = photos[0].get('fullUrl', '') if photos else ''
        all_images = [p.get('fullUrl', '') for p in photos[:10] if p.get('fullUrl')]

        cian_id = offer.get('id') or offer.get('externalId', '')
        source_url = f"https://www.cian.ru/sale/flat/{cian_id}/" if cian_id else ''

        newbuilding = offer.get('newbuilding', {}) or {}
        complex_name = newbuilding.get('name', '')
        cian_complex_id = newbuilding.get('id')

        renovation_map = {
            'cosmetic': 'косметический',
            'euro': 'евроремонт',
            'design': 'дизайнерский',
            'without': 'без ремонта',
            'rough': 'черновая',
            'fine': 'чистовая',
            'pre_clean': 'предчистовая',
        }
        renovation = renovation_map.get(offer.get('repair', ''), offer.get('repair', '') or '')

        district = ''
        okrug_name = ''
        microrayon_name = ''
        for a in address_parts:
            t = a.get('type', '')
            name = a.get('name', '') or a.get('fullName', '') or ''
            if not name:
                continue
            if t == 'okrug':
                okrug_name = name
            elif t in ('district', 'raion', 'quarter'):
                nl = name.lower()
                if any(kw in nl for kw in ('округ', 'okrug')):
                    if not okrug_name:
                        okrug_name = name
                else:
                    if not microrayon_name:
                        microrayon_name = name
        district = okrug_name or microrayon_name

        area_fmt = f"{area:.0f}" if area > 0 else "?"
        title = f"{title_rooms}, {area_fmt} м², {floor}/{total_floors} эт."

        living_area = safe_float(offer.get('livingArea')) or None
        kitchen_area = safe_float(offer.get('kitchenArea')) or None

        return {
            'title': title,
            'rooms': rooms,
            'area': area,
            'floor': floor,
            'total_floors': total_floors,
            'price': price,
            'price_per_sqm': price_per_sqm,
            'address': address_str,
            'lat': lat,
            'lon': lon,
            'image': main_image,
            'images': all_images,
            'source_url': source_url,
            'inner_id': cian_id,
            'renovation': renovation,
            'district': district,
            'address_city_district': okrug_name,
            'address_quarter': microrayon_name,
            'living_area': living_area,
            'kitchen_area': kitchen_area,
            'cian_complex_id': cian_complex_id,
            'complex_name': complex_name,
        }
    except Exception as e:
        import traceback
        print(f"  ⚠️ Ошибка парсинга объявления: {e}")
        traceback.print_exc()
        return None


def parse_cian_complex(offer):
    """Извлекает данные ЖК из offer"""
    nb = offer.get('newbuilding', {})
    if not nb or not nb.get('id'):
        return None

    geo = offer.get('geo', {})
    coords = geo.get('coordinates', {})

    photos = nb.get('images', [])
    main_image = photos[0].get('fullUrl', '') if photos else ''

    address_parts = geo.get('address', [])
    address_str = ', '.join(
        a.get('fullName', a.get('name', ''))
        for a in address_parts
        if a.get('type') not in ['country', 'region']
    )

    # Extract full geo hierarchy (okrug + microrayon)
    okrug_name = ''
    microrayon_name = ''
    for a in address_parts:
        t = a.get('type', '')
        name = a.get('name', '') or a.get('fullName', '') or ''
        if not name:
            continue
        if t == 'okrug':
            okrug_name = name
        elif t in ('district', 'raion', 'quarter'):
            nl = name.lower()
            if any(kw in nl for kw in ('округ', 'okrug')):
                if not okrug_name:
                    okrug_name = name
            else:
                if not microrayon_name:
                    microrayon_name = name

    return {
        'cian_id': nb.get('id'),
        'name': nb.get('name', 'ЖК Краснодар'),
        'address': address_str,
        'lat': coords.get('lat'),
        'lon': coords.get('lng'),
        'image': main_image,
        'description': nb.get('description', ''),
        'buildings_count': nb.get('housesCount', 1),
        'address_city_district': okrug_name,
        'address_quarter': microrayon_name,
    }


def run():
    print("=" * 60)
    print("🏗️  Парсер новостроек Краснодара (CIAN)")
    print("=" * 60)

    all_properties = []
    complexes_map = {}
    total_pages = 15

    for page in range(1, total_pages + 1):
        print(f"\n📄 Страница {page}/{total_pages}...")
        data = fetch_cian_newbuildings(page)

        if not data:
            print(f"  ⛔ Нет данных на странице {page}, останавливаемся")
            break

        offers = data.get('data', {}).get('offersSerialized', [])
        if not offers:
            offers = data.get('offersSerialized', [])

        if not offers:
            print(f"  ⛔ Пустой ответ — CIAN заблокировал. Страниц собрано: {page - 1}")
            break

        print(f"  📦 Объявлений на странице: {len(offers)}")

        for offer in offers:
            prop = parse_cian_offer(offer)
            if prop:
                all_properties.append(prop)

            c = parse_cian_complex(offer)
            if c and c['cian_id'] not in complexes_map:
                complexes_map[c['cian_id']] = c

        time.sleep(1.5)

    print(f"\n✅ Всего собрано объявлений: {len(all_properties)}")
    print(f"✅ Уникальных ЖК: {len(complexes_map)}")

    if not all_properties:
        print("\n⚠️  CIAN не вернул данные. Пробуем резервный источник...")
        run_fallback()
        return

    complexes_list = list(complexes_map.values())
    print(f"\n💾 Сохраняем в базу данных...")
    added = save_to_db(complexes_list, all_properties)
    print(f"\n🎉 Готово! Добавлено объектов: {added}")
    print_stats()


def run_fallback():
    """Резервный метод — используем Selenium с реальным Chromium"""
    print("\n🌐 Запуск Selenium-парсера...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        import json as json_lib

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.binary_location = "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium"

        service = Service("/nix/store/8zj50jw4w0hby47167kqqsaqw4mm5bkd-chromedriver-unwrapped-138.0.7204.100/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=opts)

        all_properties = []
        complexes_map = {}

        # Перехватываем XHR-ответы от CIAN через CDP
        driver.execute_cdp_cmd("Network.enable", {})

        captured = []

        def log_request(response_body):
            captured.append(response_body)

        # Открываем страницу поиска CIAN для Краснодара
        url = "https://www.cian.ru/sale/flat/krasnodar/?newobject=1"
        print(f"  🌐 Открываем: {url}")
        driver.get(url)
        time.sleep(5)

        # Получаем JSON данные через JavaScript из window.__initialData__
        try:
            page_source = driver.execute_script("""
                for (var key in window) {
                    if (key.includes('initial') || key.includes('data') || key.includes('state')) {
                        try {
                            var val = window[key];
                            if (val && typeof val === 'object' && val.offers) {
                                return JSON.stringify(val);
                            }
                        } catch(e) {}
                    }
                }
                return null;
            """)
            if page_source:
                data = json_lib.loads(page_source)
                print(f"  ✅ Получены данные через window state")
        except Exception as e:
            print(f"  ⚠️ Не удалось извлечь через JS: {e}")

        # Парсим карточки прямо с HTML страницы
        try:
            from selenium.webdriver.common.by import By
            cards = driver.find_elements(By.CSS_SELECTOR, '[data-name="OffersSerpSnippet"], article[data-testid]')
            print(f"  📦 Найдено карточек: {len(cards)}")

            for card in cards:
                try:
                    # Название ЖК
                    complex_el = card.find_elements(By.CSS_SELECTOR, '[data-name="NewbuildingName"], .newbuilding-name')
                    complex_name = complex_el[0].text if complex_el else ''

                    # Цена
                    price_el = card.find_elements(By.CSS_SELECTOR, '[data-name="Price"], .price')
                    price_text = price_el[0].text if price_el else '0'
                    price = int(re.sub(r'[^\d]', '', price_text) or '0')

                    # Параметры квартиры
                    title_el = card.find_elements(By.CSS_SELECTOR, 'h3, [data-name="TitleComponent"]')
                    title = title_el[0].text if title_el else f'Квартира {len(all_properties) + 1}'

                    # Адрес
                    addr_el = card.find_elements(By.CSS_SELECTOR, '[data-name="Geo"], .address')
                    address = addr_el[0].text if addr_el else 'Краснодар'

                    # Ссылка
                    link_el = card.find_elements(By.CSS_SELECTOR, 'a[href*="/flat/"]')
                    source_url = link_el[0].get_attribute('href') if link_el else ''
                    inner_id = re.search(r'/flat/(\d+)/', source_url).group(1) if source_url else str(len(all_properties))

                    # Фото
                    img_el = card.find_elements(By.CSS_SELECTOR, 'img[src*="cian"]')
                    image = img_el[0].get_attribute('src') if img_el else ''

                    # Парсим параметры из заголовка
                    rooms = 0
                    area = 40.0
                    floor = 1
                    total_floors = 10
                    m = re.search(r'(\d+)-комн', title.lower())
                    if m:
                        rooms = int(m.group(1))
                    elif 'студ' in title.lower():
                        rooms = 0
                    m_area = re.search(r'([\d.,]+)\s*м', title)
                    if m_area:
                        area = float(m_area.group(1).replace(',', '.'))
                    m_floor = re.search(r'(\d+)/(\d+)\s*эт', title)
                    if m_floor:
                        floor = int(m_floor.group(1))
                        total_floors = int(m_floor.group(2))

                    price_per_sqm = int(price / area) if area and price else 0
                    title_clean = f"{'Студия' if rooms == 0 else f'{rooms}-комн'}, {area:.0f} м², {floor}/{total_floors} эт."

                    all_properties.append({
                        'title': title_clean,
                        'rooms': rooms,
                        'area': area,
                        'floor': floor,
                        'total_floors': total_floors,
                        'price': price,
                        'price_per_sqm': price_per_sqm,
                        'address': address,
                        'lat': None, 'lon': None,
                        'image': image,
                        'images': [image] if image else [],
                        'source_url': source_url,
                        'inner_id': inner_id,
                        'renovation': '',
                        'district': '',
                        'living_area': None,
                        'kitchen_area': None,
                        'cian_complex_id': complex_name,
                        'complex_name': complex_name,
                    })

                    if complex_name and complex_name not in complexes_map:
                        complexes_map[complex_name] = {
                            'cian_id': complex_name,
                            'name': complex_name,
                            'address': address,
                            'lat': None, 'lon': None,
                            'image': '',
                            'description': '',
                            'buildings_count': 1,
                        }

                except Exception as e:
                    print(f"    ⚠️ Ошибка парсинга карточки: {e}")
                    continue

        except Exception as e:
            print(f"  ⚠️ Ошибка парсинга карточек: {e}")

        driver.quit()

        print(f"\n✅ Selenium: собрано {len(all_properties)} объявлений, {len(complexes_map)} ЖК")

        if all_properties:
            added = save_to_db(list(complexes_map.values()), all_properties)
            print(f"🎉 Добавлено в БД: {added}")
            print_stats()
        else:
            print("⚠️ Данных не получено. Попробуйте запустить с реальным браузером.")

    except Exception as e:
        import traceback
        print(f"❌ Ошибка Selenium: {e}")
        traceback.print_exc()


def print_stats():
    """Выводит статистику по БД"""
    import psycopg2
    try:
        conn = psycopg2.connect(
            host=os.environ.get('PGHOST', 'helium'),
            port=os.environ.get('PGPORT', 5432),
            dbname=os.environ.get('PGDATABASE', 'heliumdb'),
            user=os.environ.get('PGUSER', 'postgres'),
            password=os.environ.get('PGPASSWORD', '')
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM properties WHERE city_id=%s", (CITY_ID,))
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM residential_complexes WHERE id IN (SELECT DISTINCT complex_id FROM properties WHERE city_id=%s AND complex_id IS NOT NULL)", (CITY_ID,))
        complexes = cur.fetchone()[0]
        print(f"\n📊 Итого в БД по Краснодару:")
        print(f"   Объектов: {total}")
        print(f"   ЖК: {complexes}")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Ошибка статистики: {e}")


if __name__ == '__main__':
    run()
