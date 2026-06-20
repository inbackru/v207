"""
Forward-geocoding enrichment for residential complex addresses.

Strategy:
  1. For each Sochi RC, get the most common street address from its properties
     (these were scraped from CIAN and are reliable).
  2. Forward-geocode that street address through Nominatim to get the full
     administrative hierarchy: region → city → city_district (okrug) → quarter (мкр).
  3. Update residential_complexes.addr_region, addr_city, address_city_district,
     address_quarter with the authoritative data.
  4. Keep addr_street from CIAN (most common from properties), NOT from Nominatim.

Why forward geocoding is better than reverse:
  - RC centroid coordinates may land in the "wrong" OSM area (e.g. Адлер instead of Кудепста).
  - The street address from CIAN is always in the correct micro-district.
  - Nominatim forward lookup on "улица Искры, Сочи" finds the exact street and
    returns its correct suburb/quarter.
"""

import os
import sys
import time
import re
import logging
import psycopg2
import requests
from collections import Counter

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
HEADERS = {'User-Agent': 'InBack-RealEstate-Geocoder/1.0 (contact@inback.ru)'}
CITY_ID = 2  # Сочи

# ─── Strip house number from address ──────────────────────────────────────────
_HOUSE_RE = re.compile(
    r',?\s*(\d+[\w/\\]*(?:\s*[кKcс]\d+)?(?:\s*с\d+)?)\s*$',
    re.IGNORECASE,
)

def strip_house(addr: str) -> str:
    """Remove house/building suffix: 'улица Искры, 66/9к1' → 'улица Искры'."""
    if not addr:
        return addr
    cleaned = _HOUSE_RE.sub('', addr.strip()).rstrip(', ')
    return cleaned if cleaned else addr


def forward_geocode(street: str, city: str = 'Сочи') -> dict | None:
    """
    Forward-geocode 'street, city' via Nominatim.
    Returns raw address dict or None on failure.
    """
    query = f'{street}, {city}, Краснодарский край, Россия'
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={
                'q': query,
                'format': 'jsonv2',
                'addressdetails': 1,
                'limit': 1,
                'accept-language': 'ru',
            },
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        results = r.json()
        if results:
            return results[0].get('address', {})
    except Exception as e:
        log.warning('Nominatim error for %r: %s', query, e)
    return None


def extract_hierarchy(nom_addr: dict) -> tuple[str, str, str, str]:
    """
    Extract (region, city, okrug, quarter) from Nominatim address dict.

    Nominatim keys used (in order of preference):
      region        → state
      city          → city | town | village (pick Сочи-level)
      okrug         → city_district
      quarter/мкр   → suburb | quarter | neighbourhood | village (when != city)
    """
    region = nom_addr.get('state') or ''
    city = (nom_addr.get('city')
            or nom_addr.get('town')
            or nom_addr.get('municipality')
            or '')
    okrug = nom_addr.get('city_district') or ''
    # Strip trailing "район" / "Р-Н" suffixes for clean storage
    okrug = re.sub(r'\s+(район|р-н|r-n)$', '', okrug, flags=re.I).strip()

    # Quarter: prefer suburb > quarter > neighbourhood > village (if != city)
    quarter_candidates = [
        nom_addr.get('suburb'),
        nom_addr.get('quarter'),
        nom_addr.get('neighbourhood'),
        nom_addr.get('village'),
        nom_addr.get('hamlet'),
        nom_addr.get('town'),
    ]
    quarter = next(
        (q for q in quarter_candidates
         if q and q.lower() not in (city.lower(), okrug.lower(), '')),
        ''
    )

    return region, city, okrug, quarter


def get_rc_street_from_properties(cur, rc_id: int) -> str | None:
    """
    Get the most common street (stripped of house number) from RC's properties.
    """
    cur.execute("""
        SELECT address, COUNT(*) cnt
        FROM properties
        WHERE complex_id = %s AND address IS NOT NULL AND address != ''
        GROUP BY address
        ORDER BY cnt DESC
        LIMIT 20
    """, (rc_id,))
    rows = cur.fetchall()
    if not rows:
        return None

    # Strip house numbers and count street frequencies
    street_counter: Counter = Counter()
    for addr, cnt in rows:
        street = strip_house(addr)
        if street:
            street_counter[street] += cnt

    if not street_counter:
        return None
    return street_counter.most_common(1)[0][0]


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Fetch all Sochi RCs
    cur.execute("""
        SELECT id, name, complex_id,
               addr_region, addr_city, address_city_district, address_quarter, addr_street
        FROM residential_complexes
        WHERE city_id = %s AND is_active = true
        ORDER BY id
    """, (CITY_ID,))
    rcs = cur.fetchall()
    log.info('Found %d active Sochi RCs', len(rcs))

    updated = 0
    skipped = 0
    failed = 0

    for rc_id, name, cian_id, addr_region, addr_city, addr_district, addr_quarter, addr_street in rcs:
        # Get the canonical street from properties
        street = get_rc_street_from_properties(cur, rc_id)
        if not street:
            log.warning('[%d] %s — no property addresses, skipping', rc_id, name)
            skipped += 1
            continue

        log.info('[%d] %s | street: %s', rc_id, name, street)

        # Forward-geocode the street in Сочи
        nom = forward_geocode(street)
        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec

        if not nom:
            log.warning('[%d] %s — Nominatim returned nothing', rc_id, name)
            failed += 1
            continue

        region, city, okrug, quarter = extract_hierarchy(nom)

        log.info('  → region=%r city=%r okrug=%r quarter=%r',
                 region, city, okrug, quarter)

        # Only update fields that Nominatim found; keep existing if empty
        new_region  = region  or addr_region  or 'Краснодарский край'
        new_city    = city    or addr_city    or 'Сочи'
        new_okrug   = okrug   or addr_district or ''
        new_quarter = quarter or addr_quarter or ''
        new_street  = street  # always take from CIAN properties

        cur.execute("""
            UPDATE residential_complexes
            SET addr_region           = %s,
                addr_city             = %s,
                address_city_district = %s,
                address_quarter       = %s,
                addr_street           = %s,
                updated_at            = NOW()
            WHERE id = %s
        """, (new_region, new_city, new_okrug, new_quarter, new_street, rc_id))
        conn.commit()
        updated += 1

    log.info('Done. updated=%d skipped=%d failed=%d', updated, skipped, failed)
    cur.close()
    conn.close()


if __name__ == '__main__':
    if not DATABASE_URL:
        sys.exit('DATABASE_URL not set')
    main()
