"""
DaData-based address enrichment for residential complexes.

Strategy:
  For each RC:
    A) If the RC has property listings → take the most common property address
       (street + house from CIAN), send to DaData /clean/address.
    B) If no property listings → use RC coordinates for DaData /geolocate/address
       (reverse geocoding by lat/lng).

DaData field → DB field mapping:
  region                  → addr_region   ("Краснодарский" → "Краснодарский край")
  city                    → addr_city
  settlement (district)   → address_city_district  (when type = "внутригородской район")
  city_district (district)→ address_city_district  (fallback)
  settlement (locality)   → address_quarter         (when type = "село/поселок/мкр")
  street_with_type        → addr_street             (full normalized form e.g. "улица Искры")

Rate limit: 1 req / sec (free plan). Script sleeps 1.1s between calls.
"""

import os
import sys
import re
import time
import logging
import psycopg2
import requests
from collections import Counter

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)

DATABASE_URL  = os.environ.get('DATABASE_URL')
DADATA_TOKEN  = os.environ.get('DADATA_API_KEY')
DADATA_SECRET = os.environ.get('DADATA_SECRET_KEY')

CLEAN_URL    = 'https://cleaner.dadata.ru/api/v1/clean/address'
GEO_URL      = 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/geolocate/address'
CITY_ID      = 2  # Сочи

CLEAN_HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Token {DADATA_TOKEN}',
    'X-Secret': DADATA_SECRET,
}
GEO_HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Token {DADATA_TOKEN}',
}

# ─── House-number strip ────────────────────────────────────────────────────────
_HOUSE_RE = re.compile(
    r',?\s*\d+[\w/\\]*(?:\s*[кКcCсС]\s*\d+)*(?:\s*[сС]\s*\d+)?\s*$',
    re.IGNORECASE,
)

def strip_house(addr: str) -> str:
    cleaned = _HOUSE_RE.sub('', addr.strip()).rstrip(', ')
    return cleaned if cleaned else addr


def normalize_region(raw: str) -> str:
    """'Краснодарский' → 'Краснодарский край'"""
    if not raw:
        return ''
    r = raw.strip()
    if 'край' not in r.lower() and 'краснодарск' in r.lower():
        return r + ' край'
    return r


def clean_district(raw: str) -> str:
    """Remove 'внутригородской', 'район', trailing whitespace."""
    if not raw:
        return ''
    s = re.sub(r'\s*(внутригородской|внутригородский)\s*(район|р-н)?\s*', '', raw, flags=re.I)
    s = re.sub(r'\s*(район|р-н)\s*$', '', s, flags=re.I)
    return s.strip()


# ─── DaData clean (forward) ────────────────────────────────────────────────────
def dadata_clean(address: str) -> dict | None:
    """Clean a single address string via DaData /clean/address."""
    try:
        r = requests.post(CLEAN_URL, headers=CLEAN_HEADERS,
                          json=[address], timeout=15)
        if r.status_code == 200:
            results = r.json()
            return results[0] if results else None
        else:
            log.warning('DaData clean HTTP %d: %s', r.status_code, r.text[:200])
    except Exception as e:
        log.warning('DaData clean error: %s', e)
    return None


# ─── DaData geolocate (reverse) ───────────────────────────────────────────────
def dadata_geolocate(lat: float, lon: float) -> dict | None:
    """Reverse-geocode lat/lng via DaData /geolocate/address."""
    try:
        r = requests.post(GEO_URL, headers=GEO_HEADERS,
                          json={'lat': lat, 'lon': lon, 'radius_meters': 500},
                          timeout=15)
        if r.status_code == 200:
            suggestions = r.json().get('suggestions', [])
            if suggestions:
                return suggestions[0].get('data', {})
        else:
            log.warning('DaData geolocate HTTP %d: %s', r.status_code, r.text[:200])
    except Exception as e:
        log.warning('DaData geolocate error: %s', e)
    return None


# ─── Parse DaData response → our fields ───────────────────────────────────────
def parse_dadata(data: dict) -> dict:
    """
    Extract address hierarchy from DaData response (clean or geolocate).
    Returns dict with keys: region, city, district, quarter, street.
    """
    if not data:
        return {}

    region = normalize_region(data.get('region') or '')
    city   = data.get('city') or data.get('city_with_type') or ''

    # city_district field — "Хостинский район" etc.
    raw_cd = data.get('city_district') or ''
    cd_type = (data.get('city_district_type_full') or '').lower()

    # settlement field — can be a district OR a named locality (Раздольное, Лазаревское...)
    raw_st = data.get('settlement') or ''
    st_type = (data.get('settlement_type_full') or '').lower()

    district = ''
    quarter  = ''

    # Determine district:
    # - settlement whose type contains "район" = city district
    # - city_district field is always a district
    if raw_st and ('район' in st_type or 'внутригородской' in st_type):
        district = clean_district(raw_st)
    elif raw_cd and ('район' in cd_type or 'внутригородской' in cd_type):
        district = clean_district(raw_cd)
    elif raw_cd:
        district = clean_district(raw_cd)

    # Determine quarter (микрорайон / поселок / село):
    # - settlement whose type is NOT a district
    if raw_st and 'район' not in st_type and 'внутригородской' not in st_type:
        quarter = raw_st
    # Also check city_district when settlement was used as district
    if not quarter and raw_cd and district and raw_cd.lower() != district.lower():
        quarter = clean_district(raw_cd)

    # Street: prefer street_with_type (full form like "улица Искры")
    street = data.get('street_with_type') or data.get('street') or ''

    return {
        'region':   region,
        'city':     city,
        'district': district,
        'quarter':  quarter,
        'street':   street,
    }


# ─── Get best property address for RC ─────────────────────────────────────────
def get_rc_property_address(cur, rc_id: int) -> str | None:
    """Return most common property address for the given RC."""
    cur.execute("""
        SELECT address, COUNT(*) cnt
        FROM properties
        WHERE complex_id = %s AND address IS NOT NULL AND address != ''
        GROUP BY address
        ORDER BY cnt DESC
        LIMIT 1
    """, (rc_id,))
    row = cur.fetchone()
    return row[0] if row else None


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not DADATA_TOKEN:
        sys.exit('DADATA_API_KEY not set')
    if not DATABASE_URL:
        sys.exit('DATABASE_URL not set')

    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()

    cur.execute("""
        SELECT id, name, addr_region, addr_city,
               address_city_district, address_quarter, addr_street,
               latitude, longitude
        FROM residential_complexes
        WHERE city_id = %s
        ORDER BY id
    """, (CITY_ID,))
    rcs = cur.fetchall()
    log.info('Processing %d Sochi RCs via DaData …', len(rcs))

    updated = skipped = via_geo = 0

    for (rc_id, name, cur_region, cur_city,
         cur_district, cur_quarter, cur_street,
         lat, lng) in rcs:

        prop_addr = get_rc_property_address(cur, rc_id)

        if prop_addr:
            # Strategy A: clean property address
            query = f'{prop_addr}, Сочи, Краснодарский край'
            log.info('[%d] %s | clean: %s', rc_id, name, prop_addr)
            data = dadata_clean(query)
            time.sleep(1.1)

            parsed = parse_dadata(data) if data else {}
            source = 'clean'

        elif lat and lng:
            # Strategy B: reverse-geocode RC coordinates
            log.info('[%d] %s | geolocate: %.4f, %.4f', rc_id, name, lat, lng)
            geo_data = dadata_geolocate(float(lat), float(lng))
            time.sleep(1.1)

            parsed = parse_dadata(geo_data) if geo_data else {}
            source = 'geolocate'
            via_geo += 1

        else:
            log.warning('[%d] %s — no address or coordinates, skipping', rc_id, name)
            skipped += 1
            continue

        if not parsed:
            log.warning('[%d] %s — DaData returned nothing (%s)', rc_id, name, source)
            skipped += 1
            continue

        new_region   = parsed.get('region')   or cur_region   or 'Краснодарский край'
        new_city     = parsed.get('city')     or cur_city     or 'Сочи'
        # District: DaData is authoritative — use it; fall back to existing
        new_district = parsed.get('district') or cur_district or ''
        # Quarter: DaData only resolves named settlements (Раздольное, Лазаревское...).
        # If DaData has nothing, keep existing value from Nominatim forward-geocoding
        # (which correctly found Кудепста, Бытха etc.)
        new_quarter  = parsed.get('quarter')  or cur_quarter  or ''
        # Street: DaData returns abbreviated form ("ул Искры").
        # Keep existing full form from CIAN properties ("улица Искры") — do NOT overwrite.
        new_street   = cur_street or ''

        log.info('  → [%s] region=%r city=%r district=%r quarter=%r street=%r',
                 source, new_region, new_city, new_district, new_quarter, new_street)

        cur.execute("""
            UPDATE residential_complexes
            SET addr_region           = %s,
                addr_city             = %s,
                address_city_district = %s,
                address_quarter       = %s,
                addr_street           = %s,
                updated_at            = NOW()
            WHERE id = %s
        """, (new_region, new_city, new_district, new_quarter, new_street, rc_id))
        conn.commit()
        updated += 1

    log.info('Done. updated=%d via_geolocate=%d skipped=%d', updated, via_geo, skipped)
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
