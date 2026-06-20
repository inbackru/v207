"""
Shared CIAN address parser used by:
  - services/parser_import_service.py   (auto-parse on ЖК create/update)
  - scripts/import_parser_data.py       (bulk import from Excel/parser)

Splits CIAN-format address into 6 structured components:
  addr_region           — Краснодарский край, Курская область, Республика ...
  addr_city             — Краснодар, Сочи, Майкоп, Курск ...
  address_city_district — Адлер жилрайон, Прикубанский округ, Фестивальный мкр (if 2 мкр)
  address_quarter       — Курортный Городок мкр, Солнечный мкр, Пашковский жилмассив ...
  addr_street           — улица Агрономическая, проспект Чекистов ...
  addr_house            — 13/9, 87к1, 2/1 ...
"""

import re

STREET_WORDS = {
    "улица", "ул.", "проспект", "пр-т", "пр.", "переулок", "пер.",
    "набережная", "бульвар", "шоссе", "проезд", "тупик", "аллея",
    "дорога", "трасса", "линия", "квартал"
}

STREET_SUFFIX_RE = re.compile(
    r"(улица|проспект|переулок|набережная|бульвар|шоссе|проезд|тупик|аллея|дорога|трасса)$",
    re.IGNORECASE
)

# микрорайон-level markers
MICRO_WORDS = {"мкр", "микрорайон", "жилмассив", "жк", "кв-л", "кп"}

# district-level markers (higher than мкр) — checked BEFORE admin_district
# so "жилрайон" (ends with "район") is NOT mis-classified as admin_district
DISTRICT_WORDS = {"жилрайон", "округ"}

REGION_WORDS = {"край", "область", "республика", "автономный"}

SETTLEMENT_WORDS = {"пгт", "с.", "аул", "пос.", "рп", "село", "деревня",
                    "пгт.", "пос", "поселок", "посёлок"}

SKIP_TOKENS = {"россия", "рф"}

KNOWN_CITIES = {
    "краснодар", "сочи", "майкоп", "курск", "владикавказ",
    "ростов-на-дону", "ставрополь", "новороссийск", "армавир", "анапа",
    "туапсе", "геленджик", "новочеркасск", "таганрог",
}


def _token_type(part: str) -> str:
    p = part.strip()
    pl = p.lower()
    words_l = set(re.split(r"[\s\-]+", pl))

    if pl in SKIP_TOKENS:
        return "skip"

    if words_l & REGION_WORDS:
        if "городской" in words_l and "округ" in words_l:
            return "city_suffix"
        return "region"

    # district check BEFORE admin_district so "жилрайон" is caught here
    if words_l & DISTRICT_WORDS:
        return "district"

    # requires a SPACE before "район" so "жилрайон" is not matched
    if re.search(r"\sрайон(а)?$", pl):
        return "admin_district"

    if words_l & SETTLEMENT_WORDS or re.search(
        r"\bпгт\.?\b|\bс\.\b|\bаул\b|\bпоселок\b|\bпосёлок\b", pl
    ):
        return "settlement"

    if words_l & MICRO_WORDS:
        return "micro"

    first_word = pl.split()[0] if pl.split() else ""
    if first_word in STREET_WORDS or STREET_SUFFIX_RE.search(p):
        return "street"

    if re.match(r"^\d", p) and len(p) <= 10:
        return "house"

    if pl in KNOWN_CITIES:
        return "city"

    return "unknown"


def _house_candidate(part: str) -> bool:
    return bool(re.match(r"^\d[\d/кcсКС.литЛИТ ]+$", part.strip()))


def parse_cian_address(raw: str) -> dict:
    """
    Parse a CIAN-format address string into structured components.

    Returns a dict with keys:
        addr_region, addr_city, address_city_district,
        address_quarter, addr_street, addr_house
    All values are str or None.

    Examples:
        "Сочи, Адлер жилрайон, Курортный Городок мкр"
            → city=Сочи, district=Адлер жилрайон, quarter=Курортный Городок мкр

        "Краснодар, Фестивальный мкр, Солнечный мкр, улица Казбекская"
            → city=Краснодар, district=Фестивальный мкр, quarter=Солнечный мкр, street=улица Казбекская

        "Краснодар, Горхутор мкр, улица Агрономическая"
            → city=Краснодар, quarter=Горхутор мкр, street=улица Агрономическая

        "Курская область, Курск, улица Черняховского, 52А"
            → region=Курская область, city=Курск, street=улица Черняховского, house=52А

        "Тахтамукайский район, Яблоновский пгт, улица Шоссейная, 70/1"
            → region=Тахтамукайский район, city=Яблоновский пгт, street=улица Шоссейная, house=70/1
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

    # Expand "Сочи городской округ" → "Сочи"
    expanded = []
    for p in parts:
        if "городской округ" in p.lower():
            city_part = re.sub(r"\s*городской\s+округ\s*", "", p, flags=re.IGNORECASE).strip()
            if city_part:
                expanded.append(city_part)
        else:
            expanded.append(p)
    parts = expanded

    types = [_token_type(p) for p in parts]

    # First pass: fill region and city from the leading parts
    i = 0
    while i < len(parts):
        t = types[i]
        p = parts[i]

        if t == "skip":
            i += 1
            continue

        if t == "region" and result["addr_region"] is None:
            result["addr_region"] = p
            i += 1
            continue

        if t == "admin_district":
            if result["addr_region"] is None:
                result["addr_region"] = p
            # whether we consumed it as region or skipped, keep scanning
            i += 1
            continue

        if t in ("city", "unknown") and result["addr_city"] is None:
            result["addr_city"] = p
            i += 1
            continue

        if t == "settlement" and result["addr_city"] is None:
            result["addr_city"] = p
            i += 1
            continue

        if t == "city_suffix":
            i += 1
            continue

        break  # reached district/micro/street territory

    rest = parts[i:]
    rest_types = types[i:]

    micro_indices = [j for j, t in enumerate(rest_types) if t == "micro"]
    district_indices = [j for j, t in enumerate(rest_types) if t == "district"]
    street_indices = [j for j, t in enumerate(rest_types) if t == "street"]

    if district_indices:
        result["address_city_district"] = rest[district_indices[0]]
        if micro_indices:
            result["address_quarter"] = rest[micro_indices[0]]
    elif len(micro_indices) >= 2:
        result["address_city_district"] = rest[micro_indices[0]]
        result["address_quarter"] = rest[micro_indices[1]]
    elif len(micro_indices) == 1:
        result["address_quarter"] = rest[micro_indices[0]]

    if street_indices:
        result["addr_street"] = rest[street_indices[-1]]
        house_idx = street_indices[-1] + 1
        if house_idx < len(rest):
            candidate = rest[house_idx]
            if _house_candidate(candidate) or rest_types[house_idx] == "house":
                result["addr_house"] = candidate

    return result


def apply_parsed_address(obj, address: str) -> None:
    """
    Parse CIAN address and set all parsed fields on a SQLAlchemy model instance.
    Usage:
        from utils.address_parser import apply_parsed_address
        apply_parsed_address(complex_obj, complex_obj.address)
    """
    if not address:
        return
    parsed = parse_cian_address(address)
    for field, value in parsed.items():
        if hasattr(obj, field) and value is not None:
            setattr(obj, field, value)
