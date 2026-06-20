"""
Обогащение адресов сочинских ЖК через Nominatim reverse geocoding.

Для каждого ЖК с координатами:
  1. Делает reverse-геокодирование через Nominatim (бесплатно)
  2. Извлекает: регион, город, район, квартал/мкр, улицу
  3. Собирает полный CIAN-формат адреса: "Краснодарский край, Сочи, Адлерский, Кудепста, ул. Искры"
  4. Обновляет поля addr_region, addr_city, address_city_district, address_quarter, addr_street
     и (опционально с --update-address) поле address

Использование:
  python scripts/enrich_sochi_addresses_nominatim.py
  python scripts/enrich_sochi_addresses_nominatim.py --city-id 2
  python scripts/enrich_sochi_addresses_nominatim.py --force          # перезаписывает существующие значения
  python scripts/enrich_sochi_addresses_nominatim.py --update-address # также обновляет поле address
  python scripts/enrich_sochi_addresses_nominatim.py --dry-run        # только показывает результат, не пишет в БД
"""

import os
import sys
import time
import re
import argparse
import psycopg2
import psycopg2.extras
import requests

DATABASE_URL = os.environ.get("DATABASE_URL")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {
    "User-Agent": "InBack-RealEstate/1.0 (enrich@inback.ru)",
    "Accept-Language": "ru,en",
}
DELAY_SEC = 1.1  # Nominatim: не более 1 запроса в секунду

# Сопоставление суффиксов района → красивое имя для ЦИАН-формата
DISTRICT_CLEANUP = {
    r"адлер(?:ский)?\s*(?:район|жилрайон|округ)?": "Адлерский",
    r"хост(?:инский)?\s*(?:район|жилрайон|округ)?": "Хостинский",
    r"лазарев(?:ский)?\s*(?:район|жилрайон|округ)?": "Лазаревский",
    r"центральн(?:ый)?\s*(?:район|жилрайон|округ)?": "Центральный",
}


def clean_district(raw: str) -> str:
    """Нормализует название района: 'Адлерский район' → 'Адлерский'"""
    if not raw:
        return raw
    s = raw.strip()
    sl = s.lower()
    for pattern, replacement in DISTRICT_CLEANUP.items():
        if re.search(pattern, sl):
            return replacement
    # Убираем слова-паразиты
    s = re.sub(r"\s*(район|жилрайон|округ|городской\s+округ)\s*$", "", s, flags=re.IGNORECASE).strip()
    return s


def clean_street(raw: str) -> str:
    """'улица Искры' → 'ул. Искры' в стиле ЦИАН (опционально, оставляем полное имя)"""
    return raw.strip() if raw else raw


def reverse_geocode(lat: float, lon: float) -> dict | None:
    """Запрашивает Nominatim, возвращает словарь address или None."""
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "addressdetails": 1,
                "zoom": 18,
                "accept-language": "ru",
            },
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"    ⚠️  Nominatim HTTP {resp.status_code}")
            return None
        data = resp.json()
        return data.get("address", {})
    except Exception as e:
        print(f"    ⚠️  Nominatim error: {e}")
        return None


CITY_CLEANUP_RE = re.compile(
    r"^(?:городской\s+округ\s+|муниципальный\s+округ\s+|г\.\s*)", re.IGNORECASE
)

def clean_city(raw: str) -> str:
    """'городской округ Сочи' → 'Сочи', 'г. Краснодар' → 'Краснодар'"""
    if not raw:
        return raw
    return CITY_CLEANUP_RE.sub("", raw.strip()).strip()


def extract_fields(addr: dict) -> dict:
    """
    Из Nominatim address-словаря извлекает наши поля.

    Nominatim возвращает (для Сочи):
      state          → Краснодарский край
      city           → Сочи (или city_district, или town)
      city_district  → Адлерский район  (иногда suburb)
      suburb         → Кудепста
      neighbourhood  → (иногда мкр)
      road           → улица Искры
      house_number   → 66
    """
    result = dict(
        addr_region=None,
        addr_city=None,
        address_city_district=None,
        address_quarter=None,
        addr_street=None,
        addr_house=None,
    )

    # Регион
    result["addr_region"] = addr.get("state") or addr.get("region")

    # Город — пробуем несколько полей, чистим "городской округ X" → "X"
    raw_city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("municipality")
        or addr.get("county")
    )
    result["addr_city"] = clean_city(raw_city) if raw_city else None

    # Район в городе
    raw_district = addr.get("city_district") or addr.get("borough")
    if raw_district:
        result["address_city_district"] = clean_district(raw_district)

    # Квартал / мкр / посёлок
    result["address_quarter"] = (
        addr.get("suburb")
        or addr.get("neighbourhood")
        or addr.get("hamlet")
        or addr.get("village")
    )

    # Улица
    road = addr.get("road") or addr.get("pedestrian") or addr.get("path")
    if road:
        result["addr_street"] = clean_street(road)

    # Дом
    result["addr_house"] = addr.get("house_number")

    return result


def build_cian_address(fields: dict) -> str:
    """Собирает строку в формате ЦИАН: 'Краснодарский край, Сочи, Адлерский, Кудепста, ул. Искры'"""
    parts = []
    if fields.get("addr_region"):
        parts.append(fields["addr_region"])
    if fields.get("addr_city"):
        parts.append(fields["addr_city"])
    if fields.get("address_city_district"):
        parts.append(fields["address_city_district"])
    if fields.get("address_quarter"):
        parts.append(fields["address_quarter"])
    if fields.get("addr_street"):
        parts.append(fields["addr_street"])
    if fields.get("addr_house"):
        parts.append(fields["addr_house"])
    return ", ".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city-id", type=int, default=0,
                        help="city_id для обогащения (0 = авто-определить Сочи)")
    parser.add_argument("--force", action="store_true",
                        help="Перезаписывать уже заполненные поля")
    parser.add_argument("--update-address", action="store_true",
                        help="Также обновить поле address (CIAN-строка)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только показать результат, не писать в БД")
    parser.add_argument("--skip-has-district", action="store_true",
                        help="Пропустить ЖК у которых уже есть address_city_district")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Определяем city_id
    city_id = args.city_id
    if not city_id:
        cur.execute("SELECT id FROM cities WHERE name ILIKE '%сочи%' LIMIT 1")
        row = cur.fetchone()
        if not row:
            print("❌ Город Сочи не найден в БД. Укажите --city-id явно.")
            return
        city_id = row["id"]
        print(f"🏙️  Авто-определён город: id={city_id} (Сочи)")

    # Загружаем ЖК
    filter_district = "AND address_city_district IS NULL" if args.skip_has_district else ""
    cur.execute(f"""
        SELECT id, name, latitude, longitude,
               address, addr_region, addr_city,
               address_city_district, address_quarter,
               addr_street, addr_house
        FROM residential_complexes
        WHERE city_id = %s
          AND latitude IS NOT NULL
          AND longitude IS NOT NULL
          {filter_district}
        ORDER BY id
    """, (city_id,))
    rows = cur.fetchall()
    print(f"📋 Найдено ЖК: {len(rows)}")
    print(f"⚙️  Режим: {'FORCE (перезаписывать)' if args.force else 'FILL (только пустые)'}"
          f"{' + update address' if args.update_address else ''}"
          f"{' [DRY RUN]' if args.dry_run else ''}\n")

    update_cur = conn.cursor()
    updated = 0
    skipped = 0
    errors = 0

    for i, row in enumerate(rows, 1):
        rc_id = row["id"]
        name = row["name"]
        lat = row["latitude"]
        lon = row["longitude"]

        # Проверяем нужно ли обновлять
        already_has_all = (
            row["addr_region"] and
            row["address_city_district"] and
            row["addr_street"]
        )
        if already_has_all and not args.force:
            print(f"  [{i:3}/{len(rows)}] ✅ SKIP id={rc_id} «{name}» — все поля уже заполнены")
            skipped += 1
            continue

        print(f"  [{i:3}/{len(rows)}] 🔍 id={rc_id} «{name}» ({lat:.4f}, {lon:.4f})")

        # Запрос к Nominatim
        nom_addr = reverse_geocode(lat, lon)
        time.sleep(DELAY_SEC)

        if not nom_addr:
            print(f"          ⚠️  Нет ответа от Nominatim")
            errors += 1
            continue

        fields = extract_fields(nom_addr)
        cian_str = build_cian_address(fields)

        print(f"          📍 {cian_str}")
        print(f"          region={fields['addr_region']!r} city={fields['addr_city']!r} "
              f"district={fields['address_city_district']!r} "
              f"quarter={fields['address_quarter']!r} street={fields['addr_street']!r}")

        if args.dry_run:
            updated += 1
            continue

        # Строим SQL
        if args.force:
            set_parts = []
            set_vals = []
            for col in ("addr_region", "addr_city", "address_city_district",
                        "address_quarter", "addr_street", "addr_house"):
                if fields.get(col) is not None:
                    set_parts.append(f"{col} = %s")
                    set_vals.append(fields[col])
            if args.update_address and cian_str:
                set_parts.append("address = %s")
                set_vals.append(cian_str)
            if set_parts:
                update_cur.execute(
                    f"UPDATE residential_complexes SET {', '.join(set_parts)} WHERE id = %s",
                    set_vals + [rc_id]
                )
        else:
            # COALESCE — заполняем только пустые
            addr_val = cian_str if args.update_address and cian_str else None
            update_cur.execute("""
                UPDATE residential_complexes SET
                    addr_region           = COALESCE(addr_region,           %(addr_region)s),
                    addr_city             = COALESCE(addr_city,             %(addr_city)s),
                    address_city_district = COALESCE(address_city_district, %(address_city_district)s),
                    address_quarter       = COALESCE(address_quarter,       %(address_quarter)s),
                    addr_street           = COALESCE(addr_street,           %(addr_street)s),
                    addr_house            = COALESCE(addr_house,            %(addr_house)s),
                    address               = CASE WHEN %(addr_val)s IS NOT NULL
                                                 THEN COALESCE(address, %(addr_val)s)
                                                 ELSE address END
                WHERE id = %(id)s
            """, {**fields, "addr_val": addr_val, "id": rc_id})

        conn.commit()
        updated += 1

    print(f"\n{'─'*60}")
    print(f"✅ Обновлено: {updated}")
    print(f"⏭️  Пропущено (уже заполнены): {skipped}")
    print(f"❌ Ошибок: {errors}")

    # Статистика по Сочи
    cur.execute("""
        SELECT
          COUNT(*) FILTER (WHERE addr_region IS NOT NULL)           AS has_region,
          COUNT(*) FILTER (WHERE addr_city IS NOT NULL)             AS has_city,
          COUNT(*) FILTER (WHERE address_city_district IS NOT NULL) AS has_district,
          COUNT(*) FILTER (WHERE address_quarter IS NOT NULL)       AS has_quarter,
          COUNT(*) FILTER (WHERE addr_street IS NOT NULL)           AS has_street,
          COUNT(*)                                                   AS total
        FROM residential_complexes
        WHERE city_id = %s
    """, (city_id,))
    stats = cur.fetchone()
    print(f"\n── Покрытие после обогащения (city_id={city_id}) ──")
    for label, val in stats.items():
        print(f"  {label:30s}: {val}")

    cur.close()
    update_cur.close()
    conn.close()


if __name__ == "__main__":
    main()
