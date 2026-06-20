"""
Parse CIAN-format addresses in residential_complexes into structured components:
  addr_region       — Краснодарский край, Курская область, Республика ...
  addr_city         — Краснодар, Сочи, Майкоп, Курск ...
  address_city_district — Адлер жилрайон, Прикубанский округ, Фестивальный мкр (if 2 мкр)
  address_quarter   — Курортный Городок мкр, Солнечный мкр, Пашковский жилмассив ...
  addr_street       — улица Агрономическая, проспект Чекистов ...
  addr_house        — 13/9, 87к1, 2/1 ...

CIAN address formats observed in data:
  Город, X мкр, улица Y, дом             → city / quarter / street / house
  Город, X жилрайон, Y мкр               → city / district / quarter
  Город, X жилрайон, улица Y             → city / district / street
  Город, X округ, улица Y                → city / district / street
  Город, X мкр, Y мкр, улица Z          → city / district(1st мкр) / quarter(2nd мкр) / street
  Регион, Город, улица Y, дом            → region / city / street / house
  Регион, Город, X мкр, ЖК Y            → region / city / quarter / quarter-name
  X район, Посёлок пгт, улица Y         → region(район) / city(пгт) / street
  Город городской округ, пгт X, улица Y → city / settlement / street
"""

import os
import sys
import re
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")

# ── keyword sets ──────────────────────────────────────────────────────────────

STREET_WORDS = {
    "улица", "ул.", "проспект", "пр-т", "пр.", "переулок", "пер.",
    "набережная", "бульвар", "шоссе", "проезд", "тупик", "аллея",
    "дорога", "трасса", "линия", "квартал"
}

# Parts whose only keyword is one of these → street token (bare suffix)
STREET_SUFFIX_RE = re.compile(
    r"(улица|проспект|переулок|набережная|бульвар|шоссе|проезд|тупик|аллея|дорога|трасса)$",
    re.IGNORECASE
)

# Microdistrict markers
MICRO_WORDS = {"мкр", "мкр.", "микрорайон", "м-н", "жилмассив", "жк", "кв-л", "кп", "квартал"}

# District-level markers (higher than мкр)
DISTRICT_WORDS = {"жилрайон", "округ", "жилрайоне"}   # 'округ' but NOT 'городской округ'

# Region markers
REGION_WORDS = {"край", "область", "республика", "автономный"}

# Administrative-settlement words (not city proper)
SETTLEMENT_WORDS = {"пгт", "с.", "аул", "пос.", "рп", "село", "деревня",
                    "пгт.", "пос", "поселок", "посёлок"}

# Known country/noise tokens to skip
SKIP_TOKENS = {"россия", "рф"}

# Known cities — used to anchor the city field when no region precedes them
KNOWN_CITIES = {
    "краснодар", "сочи", "майкоп", "курск", "владикавказ",
    "ростов-на-дону", "ставрополь", "новороссийск", "армавир", "анапа",
    "туапсе", "геленджик", "новочеркасск", "таганрог",
    "белгород", "воронеж", "липецк", "тамбов", "орёл", "орел", "брянск",
    "тула", "калуга", "смоленск", "рязань", "тверь", "иваново",
    "ярославль", "кострома", "вологда", "архангельск", "мурманск",
    "петрозаводск", "псков", "великий новгород", "москва",
    "санкт-петербург", "екатеринбург", "казань", "уфа", "самара",
    "пермь", "нижний новгород", "волгоград", "саратов",
}

# Known okrug/district names by city (lower-case) — these are "unknown" tokens
# that CIAN emits as part of the address hierarchy without any keyword suffix.
# E.g. "Краснодар, Прикубанский, ул. X"  — "Прикубанский" has no keyword.
KNOWN_OKRUGS: dict[str, set] = {
    "краснодар": {
        "прикубанский", "центральный", "карасунский", "западный",
        "прикубанский округ", "центральный округ", "карасунский округ",
        "западный округ",
    },
    "сочи": {
        "адлерский", "хостинский", "лазаревский", "центральный",
        "адлер", "хоста", "лазаревское",
    },
    "белгород": {
        "восточный", "западный", "северный", "южный", "центральный",
        "белгородский район", "старооскольский", "губкинский",
        "волоконовский", "ракитянский", "прохоровский",
    },
    "майкоп": {
        "центральный", "северный", "южный",
    },
    "курск": {
        "центральный", "сеймский", "железнодорожный",
    },
}


# ── helpers ───────────────────────────────────────────────────────────────────

def token_type(part: str) -> str:
    """Classify a comma-separated address part."""
    p = part.strip()
    pl = p.lower()
    words_l = set(re.split(r"[\s\-]+", pl))

    # skip country
    if pl in SKIP_TOKENS:
        return "skip"

    # region: 'Краснодарский край', 'Курская область', 'Республика ...'
    if words_l & REGION_WORDS:
        # 'городской округ' — treat as city-suffix, not region
        if "городской" in words_l and "округ" in words_l:
            return "city_suffix"
        return "region"

    # district: жилрайон / округ (not городской) — check BEFORE admin_district
    # so 'жилрайон' (ends with 'район') doesn't get mis-classified below
    if words_l & DISTRICT_WORDS:
        return "district"

    # administrative district like 'Тахтамукайский район' — requires space before 'район'
    # so 'жилрайон' is NOT caught here (it's caught above as 'district')
    if re.search(r"\sрайон(а)?$", pl):
        return "admin_district"

    # settlement: пгт, аул, с. …
    if words_l & SETTLEMENT_WORDS or re.search(r"\bпгт\.?\b|\bс\.\b|\bаул\b|\bпоселок\b|\bпосёлок\b", pl):
        return "settlement"

    # microdistrict: мкр / микрорайон / жилмассив / ЖК / кв-л / КП
    if words_l & MICRO_WORDS:
        return "micro"

    # street: starts OR ends with street word/suffix
    # "ул. Народная" → first_word="ул." → street
    # "Народная ул." → last_word="ул." → street  (abbreviated form at end)
    split_words = pl.split()
    first_word = split_words[0] if split_words else ""
    last_word  = split_words[-1] if split_words else ""
    if first_word in STREET_WORDS or last_word in STREET_WORDS or STREET_SUFFIX_RE.search(p):
        return "street"

    # bare house-number heuristic: starts with digit, short, no letters typical of names
    if re.match(r"^\d", p) and len(p) <= 10:
        return "house"

    # known city
    if pl in KNOWN_CITIES:
        return "city"

    return "unknown"


def house_candidate(part: str) -> bool:
    """True if part looks like a house number (digits, slashes, letters)."""
    return bool(re.match(r"^\d[\d/кcсКС.литЛИТ ]+$", part.strip()))


def parse_address(raw: str):
    """
    Returns dict with keys:
      addr_region, addr_city, address_city_district,
      address_quarter, addr_street, addr_house
    All values are str or None.
    """
    result = dict(
        addr_region=None,
        addr_city=None,
        address_city_district=None,
        address_quarter=None,
        addr_street=None,
        addr_house=None,
    )

    if not raw or not raw.strip():
        return result

    parts = [p.strip() for p in raw.split(",") if p.strip()]

    # Special: handle 'Сочи городской округ, пгт X, ...'  — first part may contain
    # city + 'городской округ', split them
    expanded = []
    for p in parts:
        pl = p.lower()
        if "городской округ" in pl:
            # extract city name before 'городской округ'
            city_part = re.sub(r"\s*городской\s+округ\s*", "", p, flags=re.IGNORECASE).strip()
            if city_part:
                expanded.append(city_part)
        else:
            expanded.append(p)
    parts = expanded

    types = [token_type(p) for p in parts]

    # First pass: fill region and city
    i = 0
    while i < len(parts):
        t = types[i]
        p = parts[i]

        if t == "skip":
            i += 1
            continue

        if t == "region" and result["addr_region"] is None:
            # region may span multiple parts (e.g. 'Республика Северная Осетия - Алания')
            # but they're already in one comma-part from CIAN
            result["addr_region"] = p
            i += 1
            continue

        if t == "admin_district" and result["addr_region"] is None:
            result["addr_region"] = p
            i += 1
            continue

        if t in ("city", "unknown") and result["addr_city"] is None:
            # Accept as city if it's the first non-region/non-skip token
            result["addr_city"] = p
            i += 1
            continue

        if t == "settlement" and result["addr_city"] is None:
            result["addr_city"] = p
            i += 1
            continue

        if t == "city_suffix":
            # 'городской округ' suffix already stripped above, skip residual
            i += 1
            continue

        break  # reached district/micro/street territory

    # Remaining parts after city
    rest = parts[i:]
    rest_types = types[i:]

    # Re-classify "unknown" tokens using city context:
    # If city is known and token matches a known okrug for that city → "district"
    # Otherwise: unknown token BEFORE first street token → "pre_street_unknown"
    city_lower = (result["addr_city"] or "").lower()
    city_okrugs = KNOWN_OKRUGS.get(city_lower, set())
    first_street_j = next((j for j, t in enumerate(rest_types) if t == "street"), len(rest))

    refined_types = list(rest_types)
    for j, (p, t) in enumerate(zip(rest, rest_types)):
        if t == "unknown":
            pl = p.lower().strip()
            if pl in city_okrugs:
                refined_types[j] = "district"
            elif j < first_street_j:
                # Unknown token appears before any street — likely an okrug/quarter name
                # e.g. "Прикубанский", "Центральный", "Восточный" (no keyword suffix)
                refined_types[j] = "pre_street_unknown"

    # Count typed tokens in rest (using refined types)
    micro_indices    = [j for j, t in enumerate(refined_types) if t == "micro"]
    district_indices = [j for j, t in enumerate(refined_types) if t == "district"]
    unknown_pre      = [j for j, t in enumerate(refined_types) if t == "pre_street_unknown"]
    street_indices   = [j for j, t in enumerate(refined_types) if t == "street"]

    # ── Assign district ────────────────────────────────────────────────────────
    if district_indices:
        result["address_city_district"] = rest[district_indices[0]]
        if micro_indices:
            result["address_quarter"] = rest[micro_indices[0]]
        elif unknown_pre:
            # Unknown after explicit district → quarter
            result["address_quarter"] = rest[unknown_pre[0]]
    elif unknown_pre and not district_indices:
        # No explicit district keyword, but there's a pre-street unknown token
        # First → district, second (if any) → quarter
        result["address_city_district"] = rest[unknown_pre[0]]
        if len(unknown_pre) >= 2:
            result["address_quarter"] = rest[unknown_pre[1]]
        elif micro_indices:
            result["address_quarter"] = rest[micro_indices[0]]
    elif len(micro_indices) >= 2:
        # Two мкр tokens → first is district-level, second is quarter
        result["address_city_district"] = rest[micro_indices[0]]
        result["address_quarter"] = rest[micro_indices[1]]
    elif len(micro_indices) == 1:
        result["address_quarter"] = rest[micro_indices[0]]

    # ── Assign street ──────────────────────────────────────────────────────────
    if street_indices:
        # Take the LAST street token (sometimes there are two streets separated by comma)
        result["addr_street"] = rest[street_indices[-1]]

        # House: anything immediately after the last street token that looks like a number
        house_idx = street_indices[-1] + 1
        if house_idx < len(rest):
            candidate = rest[house_idx]
            if house_candidate(candidate) or refined_types[house_idx] == "house":
                result["addr_house"] = candidate

    # ── Post-filter: clear address_quarter if it looks like a ЖК name ────────
    # e.g. "Инстеп Сити ЖК" — has "жк" as suffix word but no real micro keyword
    if result.get("address_quarter"):
        q_words = set(result["address_quarter"].lower().split())
        has_real_micro = bool(q_words & {"мкр", "мкр.", "микрорайон", "м-н", "жилмассив", "кв-л", "квартал"})
        is_jk_suffix = "жк" in q_words and not has_real_micro
        if is_jk_suffix:
            result["address_quarter"] = None
    # Same filter for address_city_district
    if result.get("address_city_district"):
        d_words = set(result["address_city_district"].lower().split())
        has_real_micro = bool(d_words & {"мкр", "мкр.", "микрорайон", "м-н", "жилмассив", "кв-л", "квартал",
                                         "округ", "жилрайон", "район", "районе"})
        is_jk_suffix = "жк" in d_words and not has_real_micro
        if is_jk_suffix:
            result["address_city_district"] = None

    # ── Fallback: bare street+house with no region/city info ──────────────────
    # e.g. address = 'улица Гагарина, 148/4к2'  → no city info, leave None

    return result


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse as _ap
    parser = _ap.ArgumentParser(description='Parse CIAN addresses for residential complexes')
    parser.add_argument('--city', type=int, default=0, help='city_id to process (0 = all cities)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing values (instead of COALESCE fill-only-nulls)')
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if args.city:
        cur.execute("""
            SELECT id, address FROM residential_complexes
            WHERE address IS NOT NULL AND address != ''
              AND city_id = %s
            ORDER BY id
        """, (args.city,))
    else:
        cur.execute("""
            SELECT id, address FROM residential_complexes
            WHERE address IS NOT NULL AND address != ''
            ORDER BY id
        """)
    rows = cur.fetchall()
    city_label = f'city_id={args.city}' if args.city else 'все города'
    mode_label = 'FORCE (overwrite)' if args.force else 'COALESCE (fill nulls only)'
    print(f"Processing {len(rows)} complexes ({city_label}), mode={mode_label}...\n")

    update_cur = conn.cursor()
    updated = 0
    errors = 0

    for row in rows:
        rc_id = row["id"]
        raw = row["address"]
        try:
            parsed = parse_address(raw)
        except Exception as e:
            print(f"  [ERR] id={rc_id} raw='{raw}' → {e}")
            errors += 1
            continue

        if args.force:
            # --force: overwrite all fields that parse_address could determine.
            # Only set a field if parsed value is non-NULL (don't wipe authoritative CIAN data
            # with None just because the address string lacks that component).
            set_parts = []
            set_vals  = []
            for col in ('addr_region', 'addr_city', 'address_city_district',
                        'address_quarter', 'addr_street', 'addr_house'):
                if parsed.get(col) is not None:
                    set_parts.append(f"{col} = %s")
                    set_vals.append(parsed[col])
            if set_parts:
                update_cur.execute(
                    f"UPDATE residential_complexes SET {', '.join(set_parts)} WHERE id = %s",
                    set_vals + [rc_id]
                )
        else:
            # Default: COALESCE — keep existing authoritative CIAN-typed data, fill only NULLs.
            update_cur.execute("""
                UPDATE residential_complexes SET
                    addr_region           = COALESCE(addr_region,           %(addr_region)s),
                    addr_city             = COALESCE(addr_city,             %(addr_city)s),
                    address_city_district = COALESCE(address_city_district, %(address_city_district)s),
                    address_quarter       = COALESCE(address_quarter,       %(address_quarter)s),
                    addr_street           = COALESCE(addr_street,           %(addr_street)s),
                    addr_house            = COALESCE(addr_house,            %(addr_house)s)
                WHERE id = %(id)s
            """, {**parsed, "id": rc_id})
        updated += 1

    conn.commit()
    cur.close()
    update_cur.close()
    conn.close()

    print(f"\n✅ Updated: {updated}, Errors: {errors}")

    # ── quick sanity check ────────────────────────────────────────────────────
    conn2 = psycopg2.connect(DATABASE_URL)
    cur2 = conn2.cursor()
    cur2.execute("""
        SELECT
          COUNT(*) FILTER (WHERE addr_region IS NOT NULL)           AS has_region,
          COUNT(*) FILTER (WHERE addr_city IS NOT NULL)             AS has_city,
          COUNT(*) FILTER (WHERE address_city_district IS NOT NULL) AS has_district,
          COUNT(*) FILTER (WHERE address_quarter IS NOT NULL)       AS has_quarter,
          COUNT(*) FILTER (WHERE addr_street IS NOT NULL)           AS has_street,
          COUNT(*) FILTER (WHERE addr_house IS NOT NULL)            AS has_house,
          COUNT(*)                                                   AS total
        FROM residential_complexes
    """)
    stats = cur2.fetchone()
    labels = ["has_region","has_city","has_district","has_quarter","has_street","has_house","total"]
    print("\n── Fill-rate ──────────────────────────────────────────")
    for label, val in zip(labels, stats):
        print(f"  {label:30s}: {val}")
    cur2.close()
    conn2.close()


if __name__ == "__main__":
    main()
