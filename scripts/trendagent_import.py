#!/usr/bin/env python3
"""
ИМПОРТЁР ДАННЫХ ИЗ TRENDAGENT API
Загружает застройщиков, ЖК, корпуса (с геометрией), ценовые сводки и
индивидуальные квартиры (шахматка) в нашу базу данных.

Использование:
    python3 scripts/trendagent_import.py --city krasnodar
    python3 scripts/trendagent_import.py --city krasnodar --limit 10
    python3 scripts/trendagent_import.py --city krasnodar --complex-id 619f7c88d625d0b5aa7d3c61
    python3 scripts/trendagent_import.py --city krasnodar --dry-run
    python3 scripts/trendagent_import.py --city krasnodar --apartments
    python3 scripts/trendagent_import.py --city krasnodar --complex-id 619f7c88d625d0b5aa7d3c61 --apartments

Что импортируется:
    ✅ Застройщики (Developer)
    ✅ Жилые комплексы (ResidentialComplex) — описание, фото, видео, координаты, геометрия
    ✅ Корпуса (Building) — геометрия полигонов, даты сдачи
    ✅ Ценовые сводки (Property) — мин-цены по типам комнат из apartmentsMinPrices
    ✅ Индивидуальные квартиры (Property) — реальные лоты через --apartments флаг

API:
    Auth:    https://auth.trendagent.ru/login  GET ?phone=&password= → data.token (JWT)
    Blocks:  https://api.trendagent.ru/v4_29/blocks/search/ GET ?show_type=list&city={mongoId}
    Detail:  https://api.trendagent.ru/v4_29/blocks/{id}/
    AptApi:  https://apartment-api.trendagent.ru/v4_29/blocks/{id}/  (gallery, prices)
    Unified: https://api.trendagent.ru/v4_29/blocks/{id}/unified/   (buildings + geometry)
    Apts:    https://api.trendagent.ru/v4_29/apartments/search/ GET ?building={id}&city={id}&count=N&offset=N
"""

import os
import sys
import json
import logging
import argparse
import time
import re
from html.parser import HTMLParser
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple


# ── HTML stripping ──────────────────────────────────────────────────
class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: List[str] = []
    def handle_data(self, data):
        self._parts.append(data)
    def get_text(self) -> str:
        return " ".join(self._parts).strip()

def strip_html(text: str) -> str:
    """Removes HTML tags and normalises whitespace/entities."""
    if not text:
        return ""
    # Replace block-level tags with newlines
    text = re.sub(r'<br\s*/?>|</p>|</div>|</li>|</h[1-6]>', '\n', text, flags=re.IGNORECASE)
    s = _HTMLStripper()
    try:
        s.feed(text)
        result = s.get_text()
    except Exception:
        result = re.sub(r'<[^>]+>', '', text)
    # Normalise whitespace
    result = re.sub(r'[ \t]+', ' ', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Developer, ResidentialComplex, Building, Property, City

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("trendagent_import.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────────────────────────

AUTH_URL    = "https://auth.trendagent.ru/login"
API_BASE    = "https://api.trendagent.ru/v4_29"
APT_API     = "https://apartment-api.trendagent.ru/v4_29"
CDN_IMG     = "https://selcdn.trendagent.ru/images/"   # prefixed to gallery src paths

# MongoDB ObjectID для каждого города в Trendagent
# Krasnodar подтверждён; остальные нужно верифицировать при первом запуске
CITY_MONGO_IDS: Dict[str, str] = {
    "krasnodar":     "604b5243f9760700074ac345",
    "sochi":         "604b5249f9760700074ac348",
    "novorossiysk":  "604b524cf9760700074ac34a",
    "anapa":         "604b524ff9760700074ac34c",
    "gelendzhik":    "604b5252f9760700074ac34e",
    "maykop":        "604b5255f9760700074ac350",
    "krasnodar-kray":"604b5243f9760700074ac345",  # fallback
}

# Географические ограничивающие прямоугольники для фильтрации объектов
# Исключает дальние объекты Краснодарского края (Тихорецк, Суворов ГК и т.п.)
CITY_BBOX: Dict[str, Dict[str, float]] = {
    "krasnodar":    {"lat_min": 44.84, "lat_max": 45.18, "lng_min": 38.73, "lng_max": 39.38},
    "sochi":        {"lat_min": 43.22, "lat_max": 44.08, "lng_min": 39.38, "lng_max": 40.60},
    "novorossiysk": {"lat_min": 44.55, "lat_max": 44.92, "lng_min": 37.48, "lng_max": 38.10},
    "anapa":        {"lat_min": 44.70, "lat_max": 45.14, "lng_min": 37.02, "lng_max": 37.72},
    "gelendzhik":   {"lat_min": 44.35, "lat_max": 44.75, "lng_min": 37.78, "lng_max": 38.65},
    "maykop":       {"lat_min": 44.44, "lat_max": 44.78, "lng_min": 39.82, "lng_max": 40.35},
}

# Типы комнат Trendagent → русские названия
ROOM_TYPE_NAMES = {
    0:  "Студия",
    1:  "1-комн.",
    2:  "2-комн.",
    3:  "3-комн.",
    4:  "4-комн.",
    5:  "5-комн.",
    22: "Евро-2",
    23: "Евро-3",
    24: "Евро-4",
    60: "Апартаменты",
}


# ─────────────────────────────────────────────────────────────────
# КЛИЕНТ TRENDAGENT API
# ─────────────────────────────────────────────────────────────────

class TrendagentClient:
    def __init__(self, phone: str, password: str):
        self.phone    = phone
        self.password = password
        self.token: Optional[str] = None
        self.session  = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "application/json",
            "Referer":    "https://krasnodar.trendagent.ru/",
        })

    def login(self) -> bool:
        """Авторизация. Токен лежит в response.data.token (JWT Bearer)."""
        try:
            r = self.session.get(
                AUTH_URL,
                params={"phone": self.phone, "password": self.password},
                timeout=20,
            )
            r.raise_for_status()
            payload = r.json()
            token = payload.get("data", {}).get("token")
            if not token:
                logger.error(f"❌ Ошибка авторизации, ответ: {payload}")
                return False
            self.token = token
            self.session.headers["Authorization"] = f"Bearer {token}"
            logger.info(f"✅ Авторизован (токен {len(token)} символов)")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка авторизации: {e}")
            return False

    def _get(self, url: str, params: dict = None, retries: int = 3) -> Optional[Any]:
        """GET с Bearer-токеном и retry при 429/401/5xx."""
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params or {}, timeout=25)
                if r.status_code == 200:
                    ct = r.headers.get("Content-Type", "")
                    return r.json() if "json" in ct else r.text
                elif r.status_code == 429:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"Rate-limit, ожидание {wait}с …")
                    time.sleep(wait)
                elif r.status_code == 401:
                    logger.warning("Токен истёк, повторная авторизация …")
                    if self.login():
                        continue
                    return None
                elif r.status_code in (500, 502, 503):
                    logger.warning(f"HTTP {r.status_code} для {url}, попытка {attempt+1}/{retries}")
                    time.sleep(2 ** attempt)
                else:
                    logger.debug(f"HTTP {r.status_code} для {url}")
                    return None
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout {url}, попытка {attempt+1}/{retries}")
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Ошибка запроса {url}: {e}")
                time.sleep(1)
        return None

    # ── Listing ──────────────────────────────────────────────────

    def get_blocks_page(self, city_mongo_id: str, offset: int = 0, count: int = 50) -> Optional[Dict]:
        """Страница ЖК. Возвращает dict с blocksCount и results."""
        data = self._get(
            f"{API_BASE}/blocks/search/",
            params={"show_type": "list", "city": city_mongo_id,
                    "count": count, "offset": offset},
        )
        if isinstance(data, dict):
            return data.get("data")
        return None

    def get_all_blocks(self, city_mongo_id: str) -> List[Dict]:
        """Все ЖК города постранично."""
        blocks: List[Dict] = []
        count  = 40   # API реально возвращает max 40 за раз
        offset = 0
        total  = None
        while True:
            page = self.get_blocks_page(city_mongo_id, offset, count)
            if not page:
                break
            items = page.get("results", [])
            if not items:
                break
            if total is None:
                total = page.get("blocksCount", 0)
            blocks.extend(items)
            offset += len(items)
            logger.info(f"  Загружено ЖК: {len(blocks)} / {total or '?'}")
            # Проверяем что загрузили всё
            if total and len(blocks) >= total:
                break
            if len(items) < count:
                # Меньше страницы — возможно конец, но проверим ещё раз
                break
            time.sleep(0.3)
        return blocks

    # ── Block detail ─────────────────────────────────────────────

    def get_block_detail(self, block_id: str) -> Optional[Dict]:
        """Детальные данные ЖК с основного API."""
        raw = self._get(f"{API_BASE}/blocks/{block_id}/")
        if isinstance(raw, dict):
            return raw.get("data") or raw
        return None

    def get_block_apt_api(self, block_id: str) -> Optional[Dict]:
        """Детальные данные ЖК с apartment-api (галерея, мин-цены по комнатам)."""
        raw = self._get(f"{APT_API}/blocks/{block_id}/")
        return raw if isinstance(raw, dict) else None

    def get_block_unified(self, block_id: str) -> Optional[Dict]:
        """Корпуса + геометрия полигонов."""
        raw = self._get(f"{API_BASE}/blocks/{block_id}/unified/")
        if isinstance(raw, dict):
            return raw.get("data") or raw
        return None

    # ── Individual apartments ─────────────────────────────────────

    def get_apartments_for_building(self, ta_building_id: str, city_mongo_id: str,
                                    count: int = 100) -> List[Dict]:
        """
        Все квартиры одного корпуса.
        endpoint: GET api.trendagent.ru/v4_29/apartments/search/
                  ?building={ta_building_id}&city={city_mongo_id}&count=N&offset=N
        Возвращает список квартир.
        """
        apartments: List[Dict] = []
        offset = 0
        total  = None
        while True:
            raw = self._get(
                f"{API_BASE}/apartments/search/",
                params={
                    "building": ta_building_id,
                    "city":     city_mongo_id,
                    "count":    count,
                    "offset":   offset,
                    "lang":     "ru",
                },
            )
            if not isinstance(raw, dict):
                break
            data = raw.get("data") or {}
            if not isinstance(data, dict):
                break
            page_items = data.get("list") or []
            if total is None:
                total = safe_int(data.get("apartmentsCount")) or 0
            if not page_items:
                break
            apartments.extend(page_items)
            offset += len(page_items)
            if total and offset >= total:
                break
            if len(page_items) < count:
                break
            time.sleep(0.2)
        return apartments

    def get_apartments_for_block(self, ta_block_id: str, city_mongo_id: str,
                                  count: int = 100) -> List[Dict]:
        """
        Все квартиры ЖК (без фильтра по корпусу) — для поблочного импорта
        когда ta_building_id неизвестен.
        """
        # Используем building_ids из блоков — метод только как fallback,
        # предпочтителен per-building через get_apartments_for_building.
        # Здесь просто проверяем count с block фильтром (не работает) ->
        # корректный fallback: загрузить без фильтра корпуса не можем,
        # поэтому возвращаем пустой список.
        return []

    # ── Discover city MongoID ────────────────────────────────────

    def discover_city_id(self, city_slug: str) -> Optional[str]:
        """Автоопределение MongoID города по первому ЖК с нужным city.guid."""
        known = CITY_MONGO_IDS.get(city_slug)
        if known:
            return known
        # Берём любой ЖК и читаем его city._id
        page = self.get_blocks_page(CITY_MONGO_IDS["krasnodar"], 0, 1)
        if page:
            for b in page.get("results", []):
                city_obj = b.get("city") or {}
                if isinstance(city_obj, dict) and city_obj.get("guid") == city_slug:
                    return city_obj.get("_id")
        return None


# ─────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────────

def safe_int(val, default=None):
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def safe_float(val, default=None):
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def make_cdn_url(src: str) -> str:
    """Преобразует относительный src в полный CDN URL."""
    if not src:
        return ""
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("/"):
        return "https://selcdn.trendagent.ru" + src
    return CDN_IMG + src

def make_gallery_json(raw_gallery: list) -> Optional[str]:
    """Список объектов галереи → JSON-массив полных URL."""
    urls = []
    for item in raw_gallery or []:
        if isinstance(item, dict):
            src = item.get("src") or item.get("url") or item.get("image") or item.get("original") or ""
        elif isinstance(item, str):
            src = item
        else:
            continue
        url = make_cdn_url(src)
        if url:
            urls.append(url)
    return json.dumps(urls, ensure_ascii=False) if urls else None

def parse_deadline_iso(deadline_str: str) -> Tuple[Optional[int], Optional[int]]:
    """'2024-12-31T12:00:00.000Z' или '4 кв. 2024' → (year, quarter)"""
    if not deadline_str:
        return None, None
    # ISO datetime
    m = re.match(r"(\d{4})-(\d{2})-", str(deadline_str))
    if m:
        year  = int(m.group(1))
        month = int(m.group(2))
        quarter = (month - 1) // 3 + 1
        return year, quarter
    # Текстовый формат '4 кв. 2024'
    m2 = re.search(r"(\d)\s*кв[\.\s]?\s*(\d{4})", str(deadline_str))
    if m2:
        return int(m2.group(2)), int(m2.group(1))
    m3 = re.search(r"(\d{4})", str(deadline_str))
    if m3:
        return int(m3.group(1)), None
    return None, None

def polygon_to_geometry(geometry: dict) -> Optional[str]:
    """GeoJSON Polygon → наш формат 'lat,lng;lat,lng;…'"""
    if not geometry or not isinstance(geometry, dict):
        return None
    try:
        coords = geometry.get("coordinates", [])
        if not coords:
            return None
        ring = coords[0]
        parts = [f"{pt[1]},{pt[0]}" for pt in ring if len(pt) >= 2]
        return ";".join(parts) if parts else None
    except Exception:
        return None

def _convex_hull(points: list) -> list:
    """Graham scan convex hull для [(lat,lng), …]."""
    if len(points) < 3:
        return points

    def cross(O, A, B):
        return (A[0]-O[0])*(B[1]-O[1]) - (A[1]-O[1])*(B[0]-O[0])

    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]

def _try_get_attr(obj, *attrs, default=None):
    for a in attrs:
        v = obj.get(a) if isinstance(obj, dict) else getattr(obj, a, None)
        if v is not None:
            return v
    return default

_TRANSLIT = {
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh","з":"z",
    "и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r",
    "с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"sch",
    "ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
}
_TRANSLIT.update({k.upper(): v.capitalize() for k, v in _TRANSLIT.items()})

def make_slug(text: str) -> str:
    """Транслитерация + slug."""
    s = "".join(_TRANSLIT.get(c, c) for c in text)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "item"


def _unique_slug(base: str, model, city_id: int = None, slug_field: str = "slug") -> str:
    slug = base[:190]
    counter = 2
    while True:
        q = model.query.filter(getattr(model, slug_field) == slug)
        if city_id is not None and hasattr(model, "city_id"):
            q = q.filter(model.city_id == city_id)
        if not q.first():
            return slug
        slug = f"{base[:185]}-{counter}"
        counter += 1


# ─────────────────────────────────────────────────────────────────
# ИМПОРТ ЗАСТРОЙЩИКА
# ─────────────────────────────────────────────────────────────────

def upsert_developer(builder: dict) -> Optional[Developer]:
    if not builder or not isinstance(builder, dict):
        return None
    name = (builder.get("name") or "").strip()
    if not name:
        return None

    ta_id      = str(builder.get("id") or builder.get("_id") or builder.get("crm_id") or "")
    ext_id     = f"trendagent_{ta_id}" if ta_id else None

    dev = None
    if ext_id:
        dev = Developer.query.filter_by(external_id=ext_id).first()
    if not dev:
        dev = Developer.query.filter_by(name=name).first()

    if not dev:
        base_slug = make_slug(name)
        slug      = _unique_slug(base_slug, Developer)
        dev = Developer(name=name, slug=slug)
        db.session.add(dev)
        logger.info(f"  ➕ Застройщик: {name}")
    else:
        logger.debug(f"  ↻ Застройщик: {name}")

    if ext_id:
        dev.external_id = ext_id

    # Logo
    logo = _try_get_attr(builder, "logo", "logo_url", "image")
    if isinstance(logo, dict):
        logo = logo.get("url") or logo.get("src") or logo.get("image") or ""
    if logo:
        dev.logo_url = make_cdn_url(logo)

    for field in ("description", "phone", "site", "website"):
        val = builder.get(field)
        if val:
            attr = "website" if field in ("site", "website") else field
            if hasattr(dev, attr):
                setattr(dev, attr, str(val)[:500])

    if hasattr(dev, "is_active"):
        dev.is_active = True
    if hasattr(dev, "parsed_at"):
        dev.parsed_at = datetime.utcnow()
    if hasattr(dev, "parsing_status"):
        dev.parsing_status = "success"

    try:
        db.session.flush()
    except Exception as e:
        db.session.rollback()
        logger.error(f"  ❌ Застройщик {name}: {e}")
        return None
    return dev


# ─────────────────────────────────────────────────────────────────
# ИМПОРТ ЖК
# ─────────────────────────────────────────────────────────────────

def upsert_complex(block: dict, apt_block: Optional[dict],
                   unified: Optional[dict],
                   city: City, developer: Optional[Developer]) -> Optional[ResidentialComplex]:
    """
    block     — данные от api.trendagent.ru/v4_29/blocks/{id}/
    apt_block — данные от apartment-api.trendagent.ru/v4_29/blocks/{id}/  (галерея, цены)
    unified   — данные от api.trendagent.ru/v4_29/blocks/{id}/unified/    (здания, геометрия)

    Захватывает ВСЕ доступные поля TrendAgent API:
    - Базовые: id, name, address, lat/lng, description
    - Медиа: gallery (renderer), videos, pano_url, interactive_plan_url
    - Характеристики: level_type, building_type, facade_type, finishing, contract_type
    - Локация: location (район/микрорайон TA), district
    - Финансы: minPrice, payment_types, is_mortgage_available
    - Паспорт: passport (все характеристики одним блоком), view_places
    - Инфраструктура: is_with_gym, is_with_garden, parking_count, commerce_count
    - Сроки: deadlines, delivery_schedule
    - Квартиры: apartCount, roomsType, apartmentsMinPrices
    - Флаги: exclusive
    """
    name = (block.get("name") or "").strip()
    if not name:
        ta_id_dbg = block.get("id") or block.get("_id") or "?"
        logger.warning(f"    ⚠️ ЖК пропущен — нет имени (id={ta_id_dbg}, keys={list(block.keys())[:8]})")
        return None

    ta_id   = str(block.get("id") or block.get("_id") or "")
    ta_guid = block.get("guid") or block.get("alias") or ""
    if isinstance(ta_guid, list):
        ta_guid = ta_guid[0] if ta_guid else ""

    # Поиск существующего
    rc = None
    if ta_id:
        rc = ResidentialComplex.query.filter_by(complex_id=ta_id, city_id=city.id).first()
    if not rc and ta_id:
        rc = ResidentialComplex.query.filter_by(complex_id=ta_id).first()
    if not rc:
        rc = ResidentialComplex.query.filter_by(name=name, city_id=city.id).first()

    is_new = rc is None
    if is_new:
        base_slug = make_slug(name)
        slug = _unique_slug(base_slug, ResidentialComplex, city.id)
        rc = ResidentialComplex(name=name, slug=slug, city_id=city.id)
        db.session.add(rc)
        logger.info(f"    ➕ ЖК: {name}")
    else:
        logger.debug(f"    ↻ ЖК: {name}")

    # Объединяем источники: unified имеет приоритет для расширенных полей
    u = unified or {}

    # ── Базовые поля ──
    rc.complex_id = ta_id or rc.complex_id
    if developer:
        rc.developer_id = developer.id

    # Адрес
    address_raw = block.get("address") or u.get("address") or ""
    if isinstance(address_raw, str) and address_raw:
        rc.address = address_raw
    elif isinstance(address_raw, dict):
        parts = [address_raw.get("street"), address_raw.get("house")]
        rc.address = ", ".join(p for p in parts if p) or rc.address

    # Координаты
    lat = safe_float(block.get("latitude"))
    lng = safe_float(block.get("longitude"))
    if not lat:
        geom = u.get("geometry", {})
        if geom.get("type") == "Point":
            coords = geom.get("coordinates", [])
            if len(coords) >= 2:
                lng, lat = coords[0], coords[1]
    if lat and lng:
        rc.latitude  = lat
        rc.longitude = lng

    # ── Описание (очищаем HTML) ──
    desc = u.get("description") or block.get("description") or ""
    if desc:
        rc.description = strip_html(desc) if desc else ""

    # Преимущества / advantage
    advantage = u.get("advantage") or block.get("advantage") or ""
    if advantage and hasattr(rc, "advantages"):
        adv_str = advantage if isinstance(advantage, str) else json.dumps(advantage, ensure_ascii=False)
        rc.advantages = strip_html(adv_str)

    # ── Тип здания / стены ──
    bt = block.get("building_type") or u.get("building_type")
    if bt:
        if isinstance(bt, str) and hasattr(rc, "wall_material"):
            rc.wall_material = bt
        elif isinstance(bt, dict) and hasattr(rc, "wall_material"):
            rc.wall_material = bt.get("name") or rc.wall_material

    # ── Тип фасада ──
    ft = block.get("facade_type") or u.get("facade_type")
    if ft:
        if isinstance(ft, str) and hasattr(rc, "facade_type"):
            rc.facade_type = ft
        elif isinstance(ft, dict) and hasattr(rc, "facade_type"):
            rc.facade_type = ft.get("name") or rc.facade_type

    # ── Отделка ──
    fin = block.get("finishing") or u.get("finishing")
    if fin and hasattr(rc, "finishing_type"):
        if isinstance(fin, str):
            rc.finishing_type = fin
        elif isinstance(fin, list):
            rc.finishing_type = ", ".join(fin)
        elif isinstance(fin, dict):
            rc.finishing_type = fin.get("name") or rc.finishing_type

    # ── Тип договора ──
    ct = block.get("contract_type") or u.get("contract_type")
    if ct and hasattr(rc, "contract_type"):
        rc.contract_type = ct if isinstance(ct, str) else (ct.get("name") if isinstance(ct, dict) else str(ct))

    # ── Класс ЖК (level_type) ──
    level_raw = u.get("level_type") or block.get("level_type")
    if level_raw:
        if isinstance(level_raw, dict):
            lt_name = level_raw.get("name") or ""
        else:
            lt_name = str(level_raw)
        if lt_name:
            if hasattr(rc, "ta_level_type"):
                rc.ta_level_type = lt_name
            if hasattr(rc, "object_class_display_name") and not rc.object_class_display_name:
                rc.object_class_display_name = lt_name

    # ── Локация (район/микрорайон TA) ──
    loc_raw = u.get("location") or block.get("location")
    if loc_raw:
        if isinstance(loc_raw, list) and loc_raw:
            loc_raw = loc_raw[0]
        if isinstance(loc_raw, dict):
            loc_name = loc_raw.get("name") or ""
            loc_guid = loc_raw.get("guid") or ""
            if loc_name and hasattr(rc, "ta_location_name"):
                rc.ta_location_name = loc_name
            if loc_guid and hasattr(rc, "ta_location_guid"):
                rc.ta_location_guid = loc_guid

    # ── Панорама ──
    pano = u.get("pano_url") or block.get("pano_url") or ""
    if pano and hasattr(rc, "pano_url"):
        rc.pano_url = pano

    # ── Интерактивный план ──
    iplan = u.get("interactive_plan") or block.get("interactive_plan")
    if isinstance(iplan, dict) and hasattr(rc, "interactive_plan_url"):
        fpath = iplan.get("path", "") + iplan.get("file_name", "")
        if fpath:
            rc.interactive_plan_url = f"https://selcdn.trendagent.ru/images/{fpath}"

    # ── Галерея — используем renderer из unified (более полный с alt/title) ──
    # renderer: [{priority, file_name, path, title, alt, description}]
    gallery_raw = []
    renderer = u.get("renderer") or []
    if renderer and isinstance(renderer, list):
        for ritem in sorted(renderer, key=lambda x: x.get("priority", 999)):
            path = ritem.get("path", "")
            fname = ritem.get("file_name", "")
            if path and fname:
                gallery_raw.append({"src": f"https://selcdn.trendagent.ru/images/{path}{fname}"})
    if not gallery_raw:
        gallery_raw = (apt_block or {}).get("gallery") or block.get("gallery") or []
    if not isinstance(gallery_raw, list):
        gallery_raw = []
    gallery_json = make_gallery_json(gallery_raw)
    if gallery_json and hasattr(rc, "gallery_images"):
        rc.gallery_images = gallery_json
        try:
            first_img = json.loads(gallery_json)
            if first_img and hasattr(rc, "main_image") and not rc.main_image:
                rc.main_image = first_img[0]
        except Exception:
            pass

    # ── Видео ──
    videos_raw = block.get("videos") or u.get("videos") or []
    if videos_raw and isinstance(videos_raw, list) and hasattr(rc, "videos"):
        video_list = []
        for v in videos_raw:
            if isinstance(v, dict):
                vurl = v.get("url") or v.get("video_url") or ""
            elif isinstance(v, str):
                vurl = v
            else:
                continue
            if vurl:
                vtype = "youtube" if ("youtube" in vurl or "youtu.be" in vurl) else "video"
                video_list.append({"type": vtype, "url": vurl, "title": v.get("title", "") if isinstance(v, dict) else ""})
        if video_list:
            rc.videos = json.dumps(video_list, ensure_ascii=False)

    # ── Минимальная цена ──
    min_price = safe_int(block.get("minPrice") or (apt_block or {}).get("minPrice"))
    if min_price and hasattr(rc, "ta_min_price"):
        rc.ta_min_price = min_price

    # ── Флаги ипотеки/оплаты ──
    if block.get("is_mortgage_apart") is not None and hasattr(rc, "is_mortgage_available"):
        rc.is_mortgage_available = bool(block["is_mortgage_apart"])

    # ── Типы оплаты ──
    pay_types = block.get("payment_types") or (apt_block or {}).get("payment_types") or []
    if pay_types and isinstance(pay_types, list) and hasattr(rc, "ta_payment_types"):
        rc.ta_payment_types = json.dumps(pay_types, ensure_ascii=False)

    # ── Эксклюзивность ──
    excl = u.get("exclusive") if u.get("exclusive") is not None else block.get("exclusive")
    if excl is not None and hasattr(rc, "is_exclusive"):
        rc.is_exclusive = bool(excl)

    # ── Инфраструктура (бассейн/фитнес/сад) ──
    if u.get("is_with_gym") is not None and hasattr(rc, "has_gym"):
        rc.has_gym = bool(u["is_with_gym"])
    if u.get("is_with_garden") is not None and hasattr(rc, "has_garden"):
        rc.has_garden = bool(u["is_with_garden"])

    # ── Инфраструктура (текстовая) ──
    infra = u.get("infrastructure") or block.get("infrastructure") or ""
    if infra and hasattr(rc, "infrastructure"):
        rc.infrastructure = json.dumps(infra, ensure_ascii=False) if isinstance(infra, list) else str(infra)

    # ── Паркинг и коммерция ──
    if u.get("parking_count") is not None and hasattr(rc, "parking_count"):
        rc.parking_count = safe_int(u["parking_count"])
    if u.get("commerce_count") is not None and hasattr(rc, "commerce_count"):
        rc.commerce_count = safe_int(u["commerce_count"])

    # ── Паспорт ЖК (готовые характеристики) ──
    passport = u.get("passport") or {}
    if passport and isinstance(passport, dict) and hasattr(rc, "ta_passport"):
        rc.ta_passport = json.dumps(passport, ensure_ascii=False)
        # Видовые квартиры
        view = passport.get("view_places", {})
        if isinstance(view, dict) and view.get("value") and hasattr(rc, "view_places"):
            rc.view_places = view["value"][:300]
        # Паркинг
        parking_p = passport.get("parking", {})
        if isinstance(parking_p, dict) and parking_p.get("value") and hasattr(rc, "parking_features"):
            rc.parking_features = parking_p["value"]
        # Лифт
        elevator_p = passport.get("elevator", {})
        if isinstance(elevator_p, dict) and elevator_p.get("value") and hasattr(rc, "lifts_range"):
            rc.lifts_range = elevator_p["value"][:50]
        # ── Новые поля из паспорта ──
        if hasattr(rc, "ta_sales_start_display"):
            ss_p = passport.get("sales_start_at", {})
            if isinstance(ss_p, dict) and ss_p.get("value"):
                rc.ta_sales_start_display = str(ss_p["value"])[:200]
        if hasattr(rc, "ta_deadline_key_display"):
            dk_p = passport.get("deadline_key", {})
            if isinstance(dk_p, dict) and dk_p.get("value"):
                rc.ta_deadline_key_display = str(dk_p["value"])[:200]
        if hasattr(rc, "ta_escrow"):
            esc_p = passport.get("escrow", {})
            if isinstance(esc_p, dict) and esc_p.get("value"):
                val = str(esc_p["value"]).strip().lower()
                rc.ta_escrow = val not in ("нет", "no", "false", "0", "")

    # ── Типы комнат в ЖК ──
    rooms_types = block.get("roomsType") or (apt_block or {}).get("roomsType") or []
    if rooms_types and isinstance(rooms_types, list) and hasattr(rc, "ta_rooms_types"):
        rc.ta_rooms_types = json.dumps(rooms_types, ensure_ascii=False)

    # ── Сроки сдачи ──
    deadlines_raw = block.get("deadlines") or (apt_block or {}).get("deadlines") or []
    if deadlines_raw and isinstance(deadlines_raw, list):
        delivery = []
        for dl in deadlines_raw:
            if not isinstance(dl, dict):
                continue
            dl_str = dl.get("deadline") or dl.get("deadline_key") or ""
            year, quarter = parse_deadline_iso(dl_str)
            if year:
                bnames = [b.get("name", "") for b in dl.get("buildings", []) if isinstance(b, dict)]
                delivery.append({"line": dl.get("line"), "buildings": bnames,
                                  "year": year, "quarter": quarter})
                if hasattr(rc, "end_build_year") and (not rc.end_build_year or year > rc.end_build_year):
                    rc.end_build_year    = year
                    rc.end_build_quarter = quarter
        if delivery and hasattr(rc, "delivery_schedule"):
            rc.delivery_schedule = json.dumps(delivery, ensure_ascii=False)
    elif isinstance(block.get("deadline"), str):
        year, quarter = parse_deadline_iso(block["deadline"])
        if year and hasattr(rc, "end_build_year"):
            rc.end_build_year    = year
            rc.end_build_quarter = quarter

    # ── Данные из unified ──
    if unified:
        if unified.get("infrastructure") and hasattr(rc, "infrastructure"):
            inf = unified["infrastructure"]
            rc.infrastructure = json.dumps(inf, ensure_ascii=False) if isinstance(inf, list) else str(inf)
        if unified.get("parking_count") is not None and hasattr(rc, "parking_count"):
            rc.parking_count = safe_int(unified["parking_count"])

    # ── Количество квартир (из listing) ──
    apart_count = safe_int(block.get("apartCount") or block.get("apart_count"))
    if apart_count and hasattr(rc, "apartments_count"):
        rc.apartments_count = apart_count

    # ── TrendAgent v2: новые расширенные поля ──

    # CRM ID и GUID
    if hasattr(rc, "ta_crm_id") and block.get("crm_id"):
        rc.ta_crm_id = safe_int(block["crm_id"])
    if hasattr(rc, "ta_guid"):
        _guid = block.get("guid") or u.get("guid") or ""
        if _guid:
            rc.ta_guid = str(_guid)[:200]

    # Статус ЖК
    if hasattr(rc, "ta_status") and block.get("status") is not None:
        rc.ta_status = safe_int(block["status"])

    # Список алиасов (псевдонимов)
    aliases_raw = block.get("alias") or []
    if aliases_raw and isinstance(aliases_raw, list) and hasattr(rc, "ta_aliases"):
        rc.ta_aliases = json.dumps(aliases_raw, ensure_ascii=False)

    # Текст преимуществ (advantage)
    advantage = u.get("advantage") or block.get("advantage") or ""
    if advantage and hasattr(rc, "ta_advantage"):
        rc.ta_advantage = str(advantage)

    # Метро / точки доступности
    subways_raw = u.get("subways") or block.get("subways") or []
    if isinstance(subways_raw, list) and hasattr(rc, "ta_subways"):
        rc.ta_subways = json.dumps(subways_raw, ensure_ascii=False)
        if subways_raw and hasattr(rc, "ta_point_metro_time"):
            # Ближайшая станция
            nearest = min((s.get("distance_time") or 999 for s in subways_raw
                           if isinstance(s, dict)), default=None)
            if nearest and nearest < 999:
                rc.ta_point_metro_time = nearest

    # Расстояния до ключевых точек (центр города, парки и т.д.)
    pt_dist = u.get("point_distance") or block.get("point_distance") or []
    if isinstance(pt_dist, list) and pt_dist and hasattr(rc, "ta_point_distances"):
        rc.ta_point_distances = json.dumps(pt_dist, ensure_ascii=False)

    # Молельная комната
    if u.get("is_with_prayer_room") is not None and hasattr(rc, "is_with_prayer_room"):
        rc.is_with_prayer_room = bool(u["is_with_prayer_room"])

    # Генпланы / планировочные схемы (plan)
    plan_raw = u.get("plan") or block.get("plan") or []
    if plan_raw and isinstance(plan_raw, list) and hasattr(rc, "ta_plan_images"):
        plan_imgs = []
        for pl in plan_raw:
            if isinstance(pl, dict):
                p_path  = pl.get("path", "") or ""
                p_fname = pl.get("file_name", "") or ""
                if p_path and p_fname:
                    plan_imgs.append({
                        "src":   f"https://selcdn.trendagent.ru/images/{p_path}{p_fname}",
                        "title": pl.get("title", "") or "",
                        "alt":   pl.get("alt", "") or "",
                    })
        if plan_imgs:
            rc.ta_plan_images = json.dumps(plan_imgs, ensure_ascii=False)

    # Renderer — полный JSON со всеми title/alt/description (галерея ЖК)
    renderer_raw = u.get("renderer") or []
    if renderer_raw and isinstance(renderer_raw, list) and hasattr(rc, "ta_renderer_json"):
        rc.ta_renderer_json = json.dumps(renderer_raw, ensure_ascii=False)

    # ── Вознаграждение агенту (уровень ЖК) ──
    # TA хранит в reward двух форматах:
    #   block list API: [{"view": 1, "label": "4.5-6.5%"}]  ← список
    #   block detail / apartment: {"label": "4.5-6.5%"}      ← словарь
    def _extract_reward_label(reward_raw):
        """Извлекает строку-метку вознаграждения из любого формата."""
        if not reward_raw:
            return None
        if isinstance(reward_raw, str):
            return reward_raw.strip() or None
        if isinstance(reward_raw, dict):
            return (reward_raw.get("label") or "").strip() or None
        if isinstance(reward_raw, list):
            for item in reward_raw:
                lbl = _extract_reward_label(item)
                if lbl:
                    return lbl
        return None

    reward_rc = (
        u.get("reward") if u else None
        or block.get("reward")
        or ((apt_block or {}).get("reward"))
    )
    _rw_label_from_api = _extract_reward_label(reward_rc)
    if _rw_label_from_api and hasattr(rc, "ta_reward_label"):
        rc.ta_reward_label = _rw_label_from_api[:100]

    # ── Авторасчёт кэшбека InBack: 40% от вознаграждения агенту ──
    # Формат ta_reward_label: "4.5-6.5%" или "5%" → берём минимум диапазона
    _rw_label = getattr(rc, "ta_reward_label", None) or ""
    if _rw_label:
        import re as _re2
        _nums = [float(x) for x in _re2.findall(r"\d+(?:\.\d+)?", _rw_label)]
        if _nums:
            _agent_pct = min(_nums)                          # берём минимум диапазона
            _inback_pct = round(_agent_pct * 0.40, 2)       # 40% от вознаграждения агенту
            _inback_pct = max(1.0, min(10.0, _inback_pct))  # ограничиваем 1%..10%
            current_cb = getattr(rc, "cashback_rate", None)
            # Обновляем если не задано, или стоит дефолтное значение (5.0)
            if not current_cb or current_cb <= 0 or abs(current_cb - 5.0) < 0.01:
                rc.cashback_rate = _inback_pct
                logger.info(
                    f"    💎 Кэшбек InBack «{getattr(rc,'name','?')}»: "
                    f"агент {_agent_pct}% → InBack {_inback_pct}%"
                )

    # ── Аэропанорама (видео с дрона) ──
    aerial = (
        u.get("aerial_panorama_url")
        or block.get("aerial_panorama_url")
        or u.get("aerialPanoramaUrl")
        or block.get("aerialPanoramaUrl")
        or (apt_block or {}).get("aerial_panorama_url")
        or ""
    )
    # Также проверяем вложенные объекты (иногда это dict с path+file_name)
    if not aerial:
        aerial_obj = u.get("aerial_panorama") or block.get("aerial_panorama") or {}
        if isinstance(aerial_obj, dict):
            ap_path  = aerial_obj.get("path", "") or ""
            ap_fname = aerial_obj.get("file_name", "") or ""
            if ap_path and ap_fname:
                aerial = f"https://selcdn.trendagent.ru/images/{ap_path}{ap_fname}"
            else:
                aerial = aerial_obj.get("url") or aerial_obj.get("src") or ""
    if aerial and hasattr(rc, "ta_aerial_panorama_url"):
        rc.ta_aerial_panorama_url = str(aerial)[:500]

    # ── Статус ──
    rc.is_active  = True
    rc.updated_at = datetime.utcnow()
    _now_rc = datetime.utcnow()
    if hasattr(rc, "parsed_at"):
        rc.parsed_at = _now_rc
    if hasattr(rc, "ta_scraped_at"):
        rc.ta_scraped_at = _now_rc
    if hasattr(rc, "parsing_status"):
        rc.parsing_status = "success"

    try:
        db.session.flush()
    except Exception as e:
        db.session.rollback()
        logger.error(f"    ❌ ЖК {name}: {e}")
        return None
    return rc


# ─────────────────────────────────────────────────────────────────
# ИМПОРТ КОРПУСОВ
# ─────────────────────────────────────────────────────────────────

def upsert_buildings(unified: Optional[dict], rc: ResidentialComplex) -> Dict[str, Building]:
    """
    Корпуса из unified. Возвращает {ta_building_id: Building}.
    Захватывает ВСЕ доступные поля корпуса TrendAgent:
    - Базовые: id, name, number, queue
    - Даты: deadline, deadline_key, sales_start_at
    - Строительство: floors, building_type, facade_type, elevator
    - Отделка: finishing
    - Финансы: escrow, payment_types, is_mortgage, is_installment, is_subsidy, is_mortgage_military
    - Договор: contract_types
    - Паркинг: parking
    - Флаги: is_exclusive, deadline_over_check, is_unsafe, has_accreditation, has_green_mortgage
    - Адрес: address
    - Статистика: apartments_count (apartCount)
    - Геометрия: building polygon
    """
    buildings_map: Dict[str, Building] = {}
    if not unified:
        return buildings_map

    raw_buildings = unified.get("buildings") or []
    all_poly_points: List[Tuple[float, float]] = []

    for b in raw_buildings:
        if not isinstance(b, dict):
            continue
        ta_bid  = str(b.get("_id") or b.get("id") or "")
        bname   = str(b.get("name") or b.get("number") or "").strip()
        if not bname:
            continue

        display_name = f"Корпус {bname}" if re.match(r"^\d", bname) else f"Литер {bname}"

        bld = None
        if ta_bid:
            bld = Building.query.filter_by(building_id=ta_bid, complex_id=rc.id).first()
        if not bld:
            bld = Building.query.filter_by(name=display_name, complex_id=rc.id).first()
        if not bld:
            bld = Building(
                name       = display_name,
                slug       = make_slug(display_name),
                complex_id = rc.id,
            )
            db.session.add(bld)
            logger.debug(f"      ➕ {display_name}")

        if ta_bid:
            bld.building_id = ta_bid
        if hasattr(bld, "building_name"):
            bld.building_name = bname

        # ── Очередь строительства ──
        q = safe_int(b.get("queue") or b.get("phase") or b.get("turn"))
        if q and hasattr(bld, "queue"):
            bld.queue = q

        # ── Дата сдачи ──
        dl_str = b.get("deadline") or b.get("deadline_key") or ""
        year, quarter = parse_deadline_iso(dl_str)
        if year:
            if hasattr(bld, "end_build_year"):
                bld.end_build_year    = year
            if hasattr(bld, "end_build_quarter"):
                bld.end_build_quarter = quarter
        # Дата передачи ключей как DateTime
        dk_str = b.get("deadline_key") or b.get("key_date") or ""
        if dk_str and hasattr(bld, "deadline_key"):
            try:
                bld.deadline_key = datetime.fromisoformat(dk_str[:19])
            except Exception:
                pass
        if hasattr(bld, "released"):
            bld.released = bool(b.get("deadline_over_check") or b.get("is_delivered") or False)

        # ── Старт продаж ──
        ss_str = b.get("sales_start_at") or b.get("sales_start") or ""
        if ss_str and hasattr(bld, "sales_start_at"):
            try:
                bld.sales_start_at = datetime.fromisoformat(ss_str[:19])
            except Exception:
                pass

        # ── Этажи и квартиры ──
        floors = safe_int(b.get("floors") or b.get("total_floors") or b.get("floors_count"))
        if floors and hasattr(bld, "total_floors"):
            bld.total_floors = floors
        apts = safe_int(b.get("apartCount") or b.get("apartments_count") or b.get("total_apartments"))
        if apts and hasattr(bld, "total_apartments"):
            bld.total_apartments = apts

        # ── Тип здания ──
        bt = b.get("building_type")
        if bt and hasattr(bld, "building_type_name"):
            if isinstance(bt, str):
                bld.building_type_name = bt
            elif isinstance(bt, dict):
                bld.building_type_name = bt.get("name") or bld.building_type_name
            # Also update wall_material on RC if not set
            if rc and hasattr(rc, "wall_material") and not rc.wall_material:
                rc.wall_material = bld.building_type_name

        # ── Тип фасада ──
        ft = b.get("facade_type")
        if ft and hasattr(bld, "facade_type_name"):
            if isinstance(ft, str):
                bld.facade_type_name = ft
            elif isinstance(ft, dict):
                bld.facade_type_name = ft.get("name") or bld.facade_type_name

        # ── Лифт ──
        elev = b.get("elevator") or b.get("elevator_type")
        if elev and hasattr(bld, "elevator_type"):
            if isinstance(elev, str):
                bld.elevator_type = elev
            elif isinstance(elev, dict):
                bld.elevator_type = elev.get("name") or bld.elevator_type
            elif isinstance(elev, list):
                bld.elevator_type = ", ".join(
                    e.get("name", str(e)) if isinstance(e, dict) else str(e) for e in elev
                )[:100]

        # ── Отделка ──
        fin = b.get("finishing") or b.get("finishings") or []
        if fin and hasattr(bld, "finishing_types"):
            if isinstance(fin, str):
                bld.finishing_types = json.dumps([fin], ensure_ascii=False)
            elif isinstance(fin, list):
                names = [f.get("name", str(f)) if isinstance(f, dict) else str(f) for f in fin]
                bld.finishing_types = json.dumps(names, ensure_ascii=False)
            elif isinstance(fin, dict):
                bld.finishing_types = json.dumps([fin.get("name", str(fin))], ensure_ascii=False)

        # ── Паркинг ──
        pkgs = b.get("parking") or b.get("parking_types") or []
        if pkgs and hasattr(bld, "parking_types"):
            if isinstance(pkgs, list):
                names = [p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in pkgs]
                bld.parking_types = json.dumps(names, ensure_ascii=False)
            elif isinstance(pkgs, str):
                bld.parking_types = json.dumps([pkgs], ensure_ascii=False)

        # ── Тип договора ──
        cts = b.get("contract_type") or b.get("contract_types") or []
        if cts and hasattr(bld, "contract_types"):
            if isinstance(cts, list):
                names = [c.get("name", str(c)) if isinstance(c, dict) else str(c) for c in cts]
                bld.contract_types = json.dumps(names, ensure_ascii=False)
            elif isinstance(cts, str):
                bld.contract_types = json.dumps([cts], ensure_ascii=False)
            elif isinstance(cts, dict):
                bld.contract_types = json.dumps([cts.get("name", str(cts))], ensure_ascii=False)

        # ── Типы оплаты ──
        pts = b.get("payment_types") or []
        if pts and isinstance(pts, list) and hasattr(bld, "ta_payment_types"):
            bld.ta_payment_types = json.dumps(pts, ensure_ascii=False)

        # ── Флаги ─────────────────────────────────────────────────
        if b.get("escrow") is not None and hasattr(bld, "escrow"):
            bld.escrow = bool(b["escrow"])

        # Ипотека/рассрочка — ищем в payment_types или явных полях
        has_mortgage   = b.get("is_mortgage") or b.get("has_mortgage")
        has_installm   = b.get("is_installment") or b.get("has_installment")
        has_subsidy    = b.get("is_subsidy") or b.get("has_subsidy")
        has_milit      = b.get("is_mortgage_military") or b.get("has_mortgage_military")
        # Также можно вывести из payment_types строк
        if isinstance(pts, list):
            pt_lower = [p.lower() if isinstance(p, str) else "" for p in pts]
            if has_mortgage is None:
                has_mortgage = any("ипотека" in p for p in pt_lower)
            if has_installm is None:
                has_installm = any("рассрочка" in p for p in pt_lower)
            if has_subsidy is None:
                has_subsidy  = any("субсиди" in p for p in pt_lower)
            if has_milit is None:
                has_milit    = any("военн" in p for p in pt_lower)
        if has_mortgage  is not None and hasattr(bld, "has_mortgage"):
            bld.has_mortgage = bool(has_mortgage)
        if has_installm  is not None and hasattr(bld, "has_installment"):
            bld.has_installment = bool(has_installm)
        if has_subsidy   is not None and hasattr(bld, "has_subsidy"):
            bld.has_subsidy = bool(has_subsidy)
        if has_milit     is not None and hasattr(bld, "has_mortgage_military"):
            bld.has_mortgage_military = bool(has_milit)

        excl = b.get("exclusive") or b.get("is_exclusive")
        if excl is not None and hasattr(bld, "is_exclusive"):
            bld.is_exclusive = bool(excl)

        if b.get("is_unsafe") is not None and hasattr(bld, "is_unsafe"):
            bld.is_unsafe = bool(b["is_unsafe"])
        if b.get("is_accredited") is not None and hasattr(bld, "has_accreditation"):
            bld.has_accreditation = bool(b["is_accredited"])
        if b.get("is_green_mortgage") is not None and hasattr(bld, "has_green_mortgage"):
            bld.has_green_mortgage = bool(b["is_green_mortgage"])

        # ── Адрес корпуса ──
        baddr = b.get("address") or ""
        if baddr and hasattr(bld, "address_street"):
            if isinstance(baddr, str):
                bld.address_street = baddr[:300]
            elif isinstance(baddr, dict):
                parts = [baddr.get("street"), baddr.get("house")]
                bld.address_street = ", ".join(p for p in parts if p)[:300]

        # ── Геометрия полигона ──
        geom = b.get("geometry")
        if geom and isinstance(geom, dict):
            for ring in geom.get("coordinates", []):
                for pt in ring:
                    if len(pt) >= 2:
                        all_poly_points.append((pt[1], pt[0]))  # lat, lng
            poly_str = polygon_to_geometry(geom)
            if poly_str:
                if hasattr(bld, "boundary_geometry"):
                    bld.boundary_geometry = poly_str
                elif hasattr(bld, "geometry"):
                    bld.geometry = poly_str

        # ── Количество квартир в корпусе ──
        apt_cnt_b = safe_int(b.get("apartment_count") or b.get("apartCount"))
        if apt_cnt_b and hasattr(bld, "apartment_count"):
            bld.apartment_count = apt_cnt_b
        if apt_cnt_b and hasattr(bld, "total_apartments") and not bld.total_apartments:
            bld.total_apartments = apt_cnt_b

        # ── Банки-эскроу ──
        banks = b.get("escrow_banks") or []
        if isinstance(banks, list) and hasattr(bld, "escrow_banks"):
            if banks:
                names_b = [bb.get("name", str(bb)) if isinstance(bb, dict) else str(bb) for bb in banks]
                bld.escrow_banks = json.dumps(names_b, ensure_ascii=False)

        # ── Разрешение на строительство ──
        permit = b.get("trakheesi_permit") or {}
        if isinstance(permit, dict) and permit and hasattr(bld, "ta_permit"):
            bld.ta_permit = str(permit.get("number") or permit.get("permit") or "")[:200]
        elif isinstance(permit, str) and permit and hasattr(bld, "ta_permit"):
            bld.ta_permit = permit[:200]

        # ── Бассейн ──
        if b.get("is_with_pool") is not None and hasattr(bld, "is_with_pool"):
            bld.is_with_pool = bool(b["is_with_pool"])
        pool_t = b.get("pool_types") or []
        if isinstance(pool_t, list) and pool_t and hasattr(bld, "pool_types"):
            bld.pool_types = json.dumps([p.get("name", str(p)) if isinstance(p, dict) else str(p)
                                          for p in pool_t], ensure_ascii=False)

        # ── Безопасность / охрана ──
        saf = b.get("safety_types") or []
        if isinstance(saf, list) and saf and hasattr(bld, "safety_types"):
            bld.safety_types = json.dumps([s.get("name", str(s)) if isinstance(s, dict) else str(s)
                                            for s in saf], ensure_ascii=False)

        # ── Субсидия ──
        if b.get("subsidy") is not None and hasattr(bld, "subsidy"):
            bld.subsidy = bool(b["subsidy"])

        # ── Тип даты передачи ключей ──
        dkt = safe_int(b.get("deadline_key_type"))
        if dkt is not None and hasattr(bld, "deadline_key_type"):
            bld.deadline_key_type = dkt

        # ── Renderer корпуса (рендеры) ──
        b_renderer = b.get("renderer") or []
        if isinstance(b_renderer, list) and b_renderer and hasattr(bld, "ta_renderer"):
            bld.ta_renderer = json.dumps(b_renderer, ensure_ascii=False)

        # ── Интерактивная геометрия ──
        i_geom = b.get("interactive_geometry") or {}
        if isinstance(i_geom, dict) and i_geom and hasattr(bld, "ta_interactive_geometry"):
            bld.ta_interactive_geometry = json.dumps(i_geom, ensure_ascii=False)

        # ── Тип оплаты — payments list из поля payment ──
        pay_list = b.get("payment") or []
        if isinstance(pay_list, list) and pay_list and hasattr(bld, "ta_payment_types"):
            bld.ta_payment_types = json.dumps(pay_list, ensure_ascii=False)

        if hasattr(bld, "ta_scraped_at"):
            bld.ta_scraped_at = datetime.utcnow()
        if hasattr(bld, "updated_at"):
            bld.updated_at = datetime.utcnow()

        try:
            db.session.flush()
            buildings_map[ta_bid] = bld
        except Exception as e:
            db.session.rollback()
            logger.warning(f"      ⚠️ {display_name}: {e}")

    # Convex hull ЖК из полигонов всех корпусов
    if all_poly_points and hasattr(rc, "boundary_geometry"):
        hull = _convex_hull(all_poly_points)
        if hull:
            rc.boundary_geometry = ";".join(f"{lat},{lng}" for lat, lng in hull)

    if hasattr(rc, "buildings_count"):
        rc.buildings_count = len(buildings_map)

    return buildings_map


# ─────────────────────────────────────────────────────────────────
# ЦЕНОВЫЕ СВОДКИ ИЗ apartmentsMinPrices
# ─────────────────────────────────────────────────────────────────

def upsert_price_summaries(apt_block: Optional[dict], rc: ResidentialComplex,
                           buildings_map: Dict[str, Building], city: City) -> int:
    """
    Создаёт/обновляет Property-записи из apartmentsMinPrices.
    Каждая запись = минимальная цена по конкретному типу комнат в конкретном КОРПУСЕ.

    Алгоритм:
    1. Из apt_block["deadlines"] строим маппинг {line → [ta_building_id, ...]}
       (каждая очередь содержит список MongoDB ID корпусов с именами)
    2. Из apartmentsMinPrices каждая запись имеет line+rooms+price+area
    3. Для каждой записи находим корпуса по line, создаём
       Property per (корпус × тип_комнат) со ссылкой building_id

    ПРИМЕЧАНИЕ: Индивидуальные лоты (шахматка) требуют тарифного доступа к apartment-api.
    Здесь — агрегаты min-цены по типу комнат в каждом корпусе.
    """
    if not apt_block:
        return 0

    min_prices = apt_block.get("apartmentsMinPrices") or {}
    if not min_prices or not isinstance(min_prices, dict):
        return 0

    saved = 0
    now   = datetime.utcnow()
    city_slug_for_url = getattr(city, "slug", "krasnodar")
    rc_guid = apt_block.get("guid") or apt_block.get("alias") or rc.complex_id

    # ── Шаг 1: Строим маппинг line → список (ta_building_id, building_name, deadline_over) ──
    # apt_block["deadlines"] = [{buildings: [{name, _id}], line, deadline, deadline_over_check}]
    line_to_buildings: Dict[int, List[dict]] = {}
    for dl in (apt_block.get("deadlines") or []):
        if not isinstance(dl, dict):
            continue
        line_num = safe_int(dl.get("line"))
        if line_num is None:
            continue
        over = bool(dl.get("deadline_over_check", False))
        deadline_str = dl.get("deadline", "")
        yr, qr = parse_deadline_iso(deadline_str)
        for b in (dl.get("buildings") or []):
            if not isinstance(b, dict):
                continue
            ta_bid = str(b.get("_id") or b.get("id") or "")
            bname  = str(b.get("name") or "")
            if ta_bid and bname:
                line_to_buildings.setdefault(line_num, []).append({
                    "ta_bid": ta_bid,
                    "bname":  bname,
                    "over":   over,
                    "year":   yr,
                    "quarter": qr,
                })
    logger.debug(f"    line→buildings маппинг: {len(line_to_buildings)} очередей")

    # ── Шаг 2: Разбираем все записи apartmentsMinPrices ──
    # Ключ корпус-сводки: (ta_building_id, rooms_code)
    # Берём МИНИМАЛЬНУЮ цену (наиболее раннюю сдачу) если одна группа попадает в несколько корпусов
    flat_summaries: Dict[Tuple, dict] = {}

    for corp_key, price_list in min_prices.items():
        if not isinstance(price_list, list):
            continue
        for entry in price_list:
            if not isinstance(entry, dict):
                continue

            rooms     = safe_int(entry.get("rooms"))
            line      = safe_int(entry.get("line"))
            price     = safe_int(entry.get("price") or entry.get("minPrice"))
            priv_area_raw = entry.get("privArea") or entry.get("priv_area")
            min_area  = None
            if priv_area_raw is not None:
                try:
                    min_area = float(priv_area_raw)
                except (TypeError, ValueError):
                    pass
            deadline_str  = entry.get("deadline", "")
            year, quarter = parse_deadline_iso(deadline_str)
            is_delivered  = bool(entry.get("deadline_over_check") or entry.get("is_delivered") or False)
            rooms_base    = safe_int(entry.get("roomsBase"))

            if rooms is None or not price:
                continue

            # Находим корпуса для этой очереди
            matched_buildings = line_to_buildings.get(line or 0, [])
            if not matched_buildings and line_to_buildings:
                # Если маппинг по line не нашёл, берём ВСЕ корпуса (fallback)
                if len(line_to_buildings) == 1:
                    matched_buildings = list(line_to_buildings.values())[0]

            if matched_buildings:
                for bld_info in matched_buildings:
                    ta_bid = bld_info["ta_bid"]
                    key    = (ta_bid, rooms)
                    existing = flat_summaries.get(key)
                    # Предпочитаем более дешёвую цену
                    if not existing or price < existing["price"]:
                        flat_summaries[key] = {
                            "rooms":        rooms,
                            "rooms_base":   rooms_base,
                            "ta_bid":       ta_bid,
                            "bname":        bld_info["bname"],
                            "price":        price,
                            "min_area":     min_area,
                            "year":         year or bld_info.get("year"),
                            "quarter":      quarter or bld_info.get("quarter"),
                            "is_delivered": is_delivered or bld_info.get("over", False),
                            "line":         line,
                        }
            else:
                # Нет маппинга корпусов — создаём запись без привязки к корпусу
                key = (f"nobd_l{line}", rooms)
                existing = flat_summaries.get(key)
                if not existing or price < existing["price"]:
                    flat_summaries[key] = {
                        "rooms": rooms, "rooms_base": rooms_base,
                        "ta_bid": None, "bname": None,
                        "price": price, "min_area": min_area,
                        "year": year, "quarter": quarter,
                        "is_delivered": is_delivered, "line": line,
                    }

    logger.debug(f"    Итого ценовых пар (корпус×тип): {len(flat_summaries)}")

    # ── Шаг 3: Создаём/обновляем Property записи ──
    def _make_prop(ext_id: str, title: str) -> Property:
        p = Property.query.filter_by(external_id=ext_id).first()
        if p is None:
            slug = _unique_slug(make_slug(title), Property, city.id)
            p = Property(title=title, slug=slug, city_id=city.id)
            db.session.add(p)
        return p

    for key, agg in flat_summaries.items():
        rooms_code   = agg["rooms"]
        rooms_base   = agg.get("rooms_base")
        ta_bid       = agg.get("ta_bid")
        bname        = agg.get("bname")
        price        = agg["price"]
        min_area     = agg.get("min_area")
        year         = agg.get("year")
        quarter      = agg.get("quarter")
        is_delivered = agg.get("is_delivered", False)

        rooms_name = ROOM_TYPE_NAMES.get(rooms_code, f"{rooms_code}-комн.")

        # Ищем наш Building по ta_bid
        bld: Optional[Building] = buildings_map.get(ta_bid) if ta_bid else None

        # Формируем заголовок
        bld_display = bld.name if bld else (f"Корпус {bname}" if bname else "")
        title = f"{rooms_name} в {rc.name}"
        if bld_display:
            title += f" ({bld_display})"
        if year:
            title += f", {quarter} кв. {year}" if quarter else f", {year}"

        # external_id: привязан к конкретному корпусу и типу комнат
        if ta_bid:
            ext_id = f"ta_bld_{ta_bid}_r{rooms_code}"
        else:
            ext_id = f"ta_rc_{rc.complex_id}_l{agg.get('line')}_r{rooms_code}"

        prop = _make_prop(ext_id, title)

        # ── Основные поля ──
        prop.external_id   = ext_id
        prop.complex_id    = rc.id
        prop.developer_id  = rc.developer_id
        prop.city_id       = city.id
        prop.price         = price
        prop.rooms         = rooms_code if rooms_code <= 5 else None
        prop.address       = rc.address
        prop.latitude      = rc.latitude
        prop.longitude     = rc.longitude
        prop.is_active     = True
        prop.title         = title

        # ── Привязка к корпусу ──
        if bld and hasattr(prop, "building_id"):
            prop.building_id = bld.id
        if bld_display and hasattr(prop, "complex_building_name"):
            prop.complex_building_name = bld_display

        # ── Площадь ──
        if min_area and hasattr(prop, "area"):
            prop.area = min_area

        # ── Цена за м² ──
        if min_area and price and hasattr(prop, "price_per_sqm"):
            prop.price_per_sqm = int(price / min_area)

        # ── Этажность корпуса → свойство ──
        if bld and hasattr(prop, "total_floors") and bld.total_floors:
            prop.total_floors = bld.total_floors

        # ── Отделка / тип здания из корпуса ──
        if bld and hasattr(prop, "building_type") and bld.building_type_name:
            prop.building_type = bld.building_type_name
        if bld and hasattr(prop, "renovation_type") and bld.finishing_types:
            try:
                fins = json.loads(bld.finishing_types)
                if fins:
                    prop.renovation_type = fins[0]
            except Exception:
                pass

        # ── Сдача ──
        if is_delivered and hasattr(prop, "status"):
            prop.status = "Сдан"
        if year and hasattr(prop, "end_build_year"):
            prop.end_build_year    = year
            prop.end_build_quarter = quarter

        # ── Тип объекта ──
        if rooms_code == 0:
            pt = "Студия"
        elif rooms_code == 60:
            pt = "Апартаменты"
        else:
            pt = "Квартира"
        if hasattr(prop, "property_type"):
            prop.property_type = pt

        # ── Источник ──
        if hasattr(prop, "scraped_at"):
            prop.scraped_at = now
        if hasattr(prop, "last_seen_at"):
            prop.last_seen_at = now
        if hasattr(prop, "source_url"):
            prop.source_url = (
                f"https://{city_slug_for_url}.trendagent.ru/residential-complexes/{rc_guid}/"
            )

        # ── Медиа из ЖК ──
        if rc.main_image and hasattr(prop, "main_image") and not prop.main_image:
            prop.main_image = rc.main_image
        if rc.description and hasattr(prop, "description") and not prop.description:
            prop.description = rc.description[:500]

        try:
            db.session.flush()
            saved += 1
        except Exception as e:
            db.session.rollback()
            logger.warning(f"      ⚠️ Квартира {title[:40]}: {e}")

    return saved


# ─────────────────────────────────────────────────────────────────
# ИНДИВИДУАЛЬНЫЕ КВАРТИРЫ (ШАХМАТКА)
# ─────────────────────────────────────────────────────────────────

ROOM_CODES_TO_INT = {
    0:  0,   # студия
    1:  1,
    2:  2,
    3:  3,
    4:  4,
    5:  5,
    22: 2,   # евро-2 → 2
    23: 3,   # евро-3 → 3
    24: 4,   # евро-4 → 4
    60: None,  # апартаменты (rooms=None)
}

CDN_IMAGES = "https://selcdn.trendagent.ru/images/"


def _apt_plan_url(plan: dict) -> Optional[str]:
    """plan = {'path': 'k/u/', 'file_name': 'abc.png'} → CDN URL"""
    if not isinstance(plan, dict):
        return None
    path  = plan.get("path", "")
    fname = plan.get("file_name", "")
    if path and fname:
        return f"{CDN_IMAGES}{path}{fname}"
    return None


def upsert_apartments(client: "TrendagentClient",
                      rc: ResidentialComplex,
                      buildings_map: Dict[str, "Building"],
                      city: City,
                      city_mongo_id: str,
                      delete_summaries: bool = False) -> int:
    """
    Импортирует индивидуальные квартиры из шахматки для всех корпусов ЖК.

    Алгоритм:
      1. Для каждого ta_building_id из buildings_map запрашиваем
         api.trendagent.ru/v4_29/apartments/search/?building={id}&city={id}
      2. Каждая квартира → Property с external_id='ta_apt_{_id}'.
      3. Если delete_summaries=True — сначала деактивирует старые
         ценовые-сводки этого ЖК (external_id начинается с 'ta_bld_' / 'ta_rc_').

    Возвращает количество сохранённых квартир.
    """
    if not buildings_map:
        logger.warning(f"    ⚠️  Нет корпусов для импорта квартир ЖК {rc.name}")
        return 0

    now              = datetime.utcnow()
    city_slug_url    = getattr(city, "slug", "krasnodar")
    rc_guid          = rc.complex_id or rc.slug
    total_saved      = 0
    seen_ext_ids     = set()   # для отслеживания продаж

    # Опционально: деактивируем старые ценовые сводки этого ЖК
    if delete_summaries:
        old = Property.query.filter(
            Property.complex_id == rc.id,
            Property.external_id.like("ta_bld_%"),
        ).all()
        old2 = Property.query.filter(
            Property.complex_id == rc.id,
            Property.external_id.like("ta_rc_%"),
        ).all()
        for p in old + old2:
            p.is_active = False
        if old or old2:
            logger.info(f"    🗑  Деактивировано сводок: {len(old)+len(old2)}")
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()

    for ta_bid, bld in buildings_map.items():
        if not ta_bid:
            continue

        apts = client.get_apartments_for_building(ta_bid, city_mongo_id)
        if not apts:
            logger.debug(f"      Корпус {bld.name}: квартир нет")
            continue

        logger.info(f"      Корпус {bld.name}: {len(apts)} квартир")
        bld_saved = 0

        for apt in apts:
            if not isinstance(apt, dict):
                continue

            ta_apt_id = str(apt.get("_id") or "")
            if not ta_apt_id:
                continue

            ext_id = f"ta_apt_{ta_apt_id}"
            price  = safe_int(apt.get("price"))
            if not price:
                continue

            # ── rooms ──────────────────────────────────────────────
            room_obj  = apt.get("room") or {}
            rooms_crm = safe_int(room_obj.get("crm_id") if isinstance(room_obj, dict) else None)
            rooms_int = ROOM_CODES_TO_INT.get(rooms_crm, rooms_crm)
            room_name = room_obj.get("name_one") or room_obj.get("name") or \
                        (ROOM_TYPE_NAMES.get(rooms_crm, f"{rooms_crm}-комн.") if rooms_crm is not None else "")

            # ── площадь ────────────────────────────────────────────
            area_actual= safe_float(apt.get("area"))          # фактическая S
            area_given_v = safe_float(apt.get("area_given"))  # S приведенная (включает балконы)
            area       = area_given_v or area_actual          # для цена/м² используем приведенную
            area_kitch = safe_float(apt.get("area_kitchen"))

            # ── этаж ───────────────────────────────────────────────
            floor       = safe_int(apt.get("floor"))
            total_floors= safe_int(apt.get("floors")) or (bld.total_floors if hasattr(bld, "total_floors") else None)

            # ── дата сдачи ─────────────────────────────────────────
            dl_str      = apt.get("deadline") or ""
            year, qtr   = parse_deadline_iso(dl_str)
            is_delivered= bool(apt.get("deadline_over_check") or False)

            # ── отделка ────────────────────────────────────────────
            fin_obj     = apt.get("finishing") or {}
            fin_name    = fin_obj.get("name") if isinstance(fin_obj, dict) else str(fin_obj or "")

            # ── план квартиры ──────────────────────────────────────
            plan_url    = _apt_plan_url(apt.get("plan"))

            # ── статус ─────────────────────────────────────────────
            status_obj   = apt.get("status") or {}
            status_name  = status_obj.get("name") if isinstance(status_obj, dict) else "Свободная"
            status_crm_v = safe_int(status_obj.get("crm_id") if isinstance(status_obj, dict) else None)
            # TA status crm_id: 1=Свободная, 2=Забронирована, 3=Продана, 4=Реализована
            is_apt_sold  = status_crm_v in (3, 4)

            # ── заголовок ──────────────────────────────────────────
            apt_num = str(apt.get("number") or apt.get("crm_id") or "")
            title_parts = [room_name, f"№{apt_num}" if apt_num else ""]
            if floor:
                title_parts.append(f"{floor} эт.")
            title_parts.append(f"в {rc.name}")
            if bld.name:
                title_parts.append(f"({bld.name})")
            title = " ".join(p for p in title_parts if p)

            # ── поиск / создание Property ──────────────────────────
            prop = Property.query.filter_by(external_id=ext_id).first()
            is_new = prop is None
            if is_new:
                slug = _unique_slug(make_slug(title), Property, city.id)
                prop = Property(title=title, slug=slug, city_id=city.id)
                db.session.add(prop)

            old_price   = prop.price if not is_new else None
            was_active  = prop.is_active if not is_new else True
            seen_ext_ids.add(ext_id)

            if not is_new and not was_active and not is_apt_sold:
                logger.info(f"        🔄 Реактивирована квартира: {ext_id}")
            if is_apt_sold:
                logger.debug(f"        🏷 Продана в API (status_crm={status_crm_v}): {ext_id}")

            # ── заполняем поля ─────────────────────────────────────
            prop.external_id   = ext_id
            prop.complex_id    = rc.id
            prop.developer_id  = rc.developer_id
            prop.city_id       = city.id
            prop.price         = price
            prop.is_active     = not is_apt_sold
            prop.title         = title
            prop.address       = rc.address
            prop.latitude      = rc.latitude
            prop.longitude     = rc.longitude

            if hasattr(prop, "building_id") and bld:
                prop.building_id = bld.id
            if hasattr(prop, "complex_building_name"):
                prop.complex_building_name = bld.name or ""

            if rooms_int is not None and hasattr(prop, "rooms"):
                prop.rooms = rooms_int
            if hasattr(prop, "floor"):
                prop.floor = floor
            if total_floors and hasattr(prop, "total_floors"):
                prop.total_floors = total_floors
            if area and hasattr(prop, "area"):
                prop.area = area
            if area_kitch and hasattr(prop, "kitchen_area"):
                prop.kitchen_area = area_kitch
            if area and price and hasattr(prop, "price_per_sqm"):
                prop.price_per_sqm = int(price / area)
            if apt_num and hasattr(prop, "apartment_number"):
                prop.apartment_number = apt_num

            # Отделка
            if fin_name and hasattr(prop, "renovation_type"):
                prop.renovation_type = fin_name

            # Тип объекта
            if rooms_crm == 0:
                pt = "Студия"
            elif rooms_crm == 60:
                pt = "Апартаменты"
            else:
                pt = "Квартира"
            if hasattr(prop, "property_type"):
                prop.property_type = pt

            # Статус / сдача
            if is_delivered and hasattr(prop, "status"):
                prop.status = "Сдан"
            elif status_name and hasattr(prop, "status"):
                prop.status = status_name
            if year and hasattr(prop, "end_build_year"):
                prop.end_build_year    = year
                prop.end_build_quarter = qtr

            # Этажность корпуса
            if total_floors and hasattr(prop, "total_floors"):
                prop.total_floors = total_floors

            # Изображение планировки
            if plan_url and hasattr(prop, "floor_plan_image"):
                prop.floor_plan_image = plan_url
            if plan_url and hasattr(prop, "main_image") and not prop.main_image:
                prop.main_image = plan_url
            if rc.main_image and hasattr(prop, "main_image") and not prop.main_image:
                prop.main_image = rc.main_image

            # Описание из ЖК
            if rc.description and hasattr(prop, "description") and not prop.description:
                prop.description = rc.description[:500]

            # Источник
            if hasattr(prop, "scraped_at"):
                prop.scraped_at = now
            if hasattr(prop, "last_seen_at"):
                prop.last_seen_at = now
            if hasattr(prop, "source_url"):
                prop.source_url = (
                    f"https://{city_slug_url}.trendagent.ru/object/{rc_guid}/flat/{ta_apt_id}"
                )

            # ── TrendAgent v2: новые поля шахматки ──
            if apt.get("is_suite") is not None and hasattr(prop, "is_suite"):
                prop.is_suite = bool(apt["is_suite"])
            if apt.get("view") is not None and hasattr(prop, "ta_view_type"):
                vt = safe_int(apt["view"])
                prop.ta_view_type = vt
                _VIEW_TYPE_MAP = {
                    1: 'Во двор',
                    2: 'На улицу',
                    3: 'Панорамный',
                    4: 'На две стороны',
                    5: 'На парк',
                    6: 'На набережную',
                }
                if vt and hasattr(prop, "view_from_window") and not prop.view_from_window:
                    prop.view_from_window = _VIEW_TYPE_MAP.get(vt)
            vp = apt.get("view_places")
            if isinstance(vp, list) and hasattr(prop, "ta_view_places"):
                prop.ta_view_places = json.dumps(vp, ensure_ascii=False)
            reward_raw = apt.get("reward") or {}
            if isinstance(reward_raw, dict) and reward_raw.get("label") and hasattr(prop, "ta_reward_label"):
                prop.ta_reward_label = str(reward_raw["label"])[:50]
            fin_main = apt.get("finishing_main") or []
            if isinstance(fin_main, list) and fin_main and hasattr(prop, "ta_finishing_main"):
                prop.ta_finishing_main = json.dumps(
                    [{"name": f.get("name"), "name_short": f.get("name_short"), "crm_id": f.get("crm_id")}
                     for f in fin_main if isinstance(f, dict)], ensure_ascii=False)
            fin_add = apt.get("finishing_additional") or []
            if isinstance(fin_add, list) and fin_add and hasattr(prop, "ta_finishing_additional"):
                prop.ta_finishing_additional = json.dumps(
                    [{"name": f.get("name"), "name_short": f.get("name_short"), "crm_id": f.get("crm_id")}
                     for f in fin_add if isinstance(f, dict)], ensure_ascii=False)
            if apt.get("crm_id") and hasattr(prop, "ta_crm_id"):
                prop.ta_crm_id = str(apt["crm_id"])[:50]
            north = safe_float(apt.get("north"))
            if north is not None and hasattr(prop, "ta_north"):
                prop.ta_north = north
            status_crm = safe_int((apt.get("status") or {}).get("crm_id"))
            if status_crm is not None and hasattr(prop, "ta_status_crm_id"):
                prop.ta_status_crm_id = status_crm
            if apt.get("exclusive") is not None and hasattr(prop, "ta_exclusive"):
                prop.ta_exclusive = bool(apt["exclusive"])
            block_guid = apt.get("block_guid") or ""
            if block_guid and hasattr(prop, "ta_block_guid"):
                prop.ta_block_guid = block_guid[:200]

            # ── Новые поля квартиры v3 ──────────────────────────────

            # Приведённая площадь (S приведённая — для расчёта цены, включает балкон/лоджию)
            if area_given_v and hasattr(prop, "area_given"):
                prop.area_given = area_given_v

            # Высота потолков (float, напр. 2.74)
            ceil_h = safe_float(apt.get("ceiling_height"))
            if ceil_h and hasattr(prop, "ceiling_height"):
                prop.ceiling_height = ceil_h

            # Тип балкона — TA даёт объект {"name": "Лоджия", "crm_id": ...} или строку
            balcony_raw = apt.get("balcony") or apt.get("balcony_type")
            if balcony_raw:
                if isinstance(balcony_raw, dict):
                    bname = balcony_raw.get("name") or balcony_raw.get("value") or ""
                else:
                    bname = str(balcony_raw)
                if bname and hasattr(prop, "balcony_type"):
                    prop.balcony_type = bname[:50]

            # Тип окон — TA даёт объект {"name": "Увеличенные", ...} или строку
            window_raw = apt.get("window") or apt.get("windows") or apt.get("window_type")
            if window_raw:
                if isinstance(window_raw, dict):
                    wname = window_raw.get("name") or window_raw.get("value") or ""
                else:
                    wname = str(window_raw)
                if wname and hasattr(prop, "window_type"):
                    prop.window_type = wname[:50]

            # Цена при 100% оплате
            pf = safe_int(
                apt.get("price_full_payment")
                or apt.get("price_100")
                or apt.get("price_100_payment")
            )
            if pf and hasattr(prop, "price_full_payment"):
                prop.price_full_payment = pf

            # Стартовая цена (цена на момент начала продаж)
            sp = safe_int(apt.get("start_price") or apt.get("price_start"))
            if sp and hasattr(prop, "ta_start_price"):
                prop.ta_start_price = sp

            # Стартовая цена за м²
            sp_sqm = safe_int(
                apt.get("start_price_sqm")
                or apt.get("start_price_per_sqm")
                or apt.get("start_price_m2")
            )
            if sp_sqm and hasattr(prop, "ta_start_price_sqm"):
                prop.ta_start_price_sqm = sp_sqm

            # Эксклюзивность (backward-compat)
            if apt.get("exclusive") and hasattr(prop, "is_exclusive"):
                prop.is_exclusive = True

            # ── Подъезд / секция (section) ──────────────────────────
            # TrendAgent может хранить подъезд в разных полях:
            # "section": {"_id": "...", "number": 2, "name": "Секция 2"}  ← самый частый
            # "section_number": 2
            # "entrance": {"number": 2} / "entrance": 2
            # "building_section": 2
            def _extract_section(d):
                for key in ("section", "entrance", "building_section", "section_number", "entrance_number"):
                    val = d.get(key)
                    if val is None:
                        continue
                    if isinstance(val, dict):
                        # {"number": N, "name": "..."} — берём number, fallback на name
                        num = val.get("number")
                        if num is not None:          # 0 тоже валидный номер
                            return str(int(num)) if isinstance(num, (int, float)) else str(num).strip()
                        nm = val.get("name") or val.get("value") or ""
                        if nm:
                            return str(nm).strip()
                    elif isinstance(val, (int, float)):
                        return str(int(val))
                    elif isinstance(val, str) and val.strip():
                        return val.strip()
                return ""

            section_str = _extract_section(apt)
            if section_str and hasattr(prop, "entrance_number"):
                prop.entrance_number = section_str[:20]

            # Дебаг: первый раз показываем структуру ответа API
            if is_new and bld_saved == 0 and total_saved == 0:
                sample_keys = sorted(apt.keys())
                logger.debug(f"        🔑 API apt keys: {sample_keys}")
                for dk in (
                    "section", "entrance", "building_section", "section_number", "status",
                    # v3 новые поля — проверяем имена ключей в реальном API
                    "balcony", "balcony_type", "window", "windows", "window_type",
                    "ceiling_height", "price_full_payment", "price_100", "price_100_payment",
                    "start_price", "price_start", "start_price_sqm", "start_price_per_sqm",
                    "area_given", "reward",
                ):
                    val = apt.get(dk)
                    if val is not None:
                        logger.info(f"        🔍 {dk}={val!r}")
                    else:
                        logger.debug(f"        🔍 {dk}=<absent>")

            # ── трекинг изменения цены ──────────────────────────────
            if old_price is not None and old_price != price:
                try:
                    from models import PriceHistory
                    ppc = round((price - old_price) / old_price * 100, 2)
                    ph = PriceHistory(
                        complex_id=rc.id,
                        record_type='property',
                        price=price,
                        price_per_sqm=int(price / area) if area else None,
                        price_change_percent=ppc,
                        recorded_at=now,
                        month=now.month,
                        year=now.year,
                    )
                    db.session.add(ph)
                    logger.debug(
                        f"        💰 Цена: {old_price:,} → {price:,} ₽ ({ppc:+.1f}%)"
                    )
                except Exception:
                    pass

            try:
                db.session.flush()
                # Теперь prop.id известен — привязываем историю цен к property
                if old_price is not None and old_price != price:
                    try:
                        ph.property_id = prop.id
                    except Exception:
                        pass
                bld_saved += 1
                total_saved += 1
            except Exception as e:
                db.session.rollback()
                logger.warning(f"        ⚠️ Квартира {ta_apt_id}: {e}")

        if bld_saved:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"      ❌ Commit корпус {bld.name}: {e}")

    # ── Отмечаем пропавшие квартиры как проданные ────────────────
    if seen_ext_ids:
        try:
            existing_active = Property.query.filter(
                Property.complex_id == rc.id,
                Property.external_id.like('ta_apt_%'),
                Property.is_active == True,
            ).all()
            sold_count = 0
            for _p in existing_active:
                if _p.external_id not in seen_ext_ids:
                    _p.is_active = False
                    sold_count += 1
            if sold_count:
                db.session.commit()
                logger.info(f"    🏷 Отмечено проданными: {sold_count} квартир (не вернул API)")
        except Exception as _se:
            db.session.rollback()
            logger.warning(f"    ⚠️ Ошибка отметки проданных: {_se}")

    # ── Обновляем агрегаты ЖК из загруженных квартир ──
    if total_saved:
        try:
            from sqlalchemy import text as _sql_text
            with db.engine.connect() as _conn:
                _conn.execute(_sql_text("""
                    UPDATE residential_complexes rc
                    SET
                        ta_min_area  = sub.min_area,
                        ta_max_area  = sub.max_area,
                        ta_min_floor = sub.min_floor,
                        ta_max_floor = sub.max_floor,
                        ta_min_price = COALESCE(ta_min_price, sub.min_price)
                    FROM (
                        SELECT
                            MIN(area)  AS min_area,
                            MAX(area)  AS max_area,
                            MIN(floor) AS min_floor,
                            MAX(floor) AS max_floor,
                            MIN(price) AS min_price
                        FROM properties
                        WHERE complex_id = :rc_id
                          AND is_active = TRUE
                          AND external_id LIKE 'ta_apt_%%'
                    ) sub
                    WHERE rc.id = :rc_id
                """), {"rc_id": rc.id})
                _conn.commit()
            logger.info(f"    📊 Агрегаты ЖК обновлены (area/floor/price)")
        except Exception as e:
            logger.warning(f"    ⚠️ Агрегаты ЖК: {e}")

    return total_saved


# ─────────────────────────────────────────────────────────────────
# ГЛАВНЫЙ ИМПОРТ
# ─────────────────────────────────────────────────────────────────

def _bbox_check(block_data: dict, apt_block_data: dict, bbox: dict) -> Optional[bool]:
    """Проверяет, что ЖК находится в пределах bbox города.
    Возвращает True если в bbox, False если вне, None если нет координат.
    """
    lat = lng = None
    # Пробуем несколько источников координат
    for src in (apt_block_data, block_data):
        if not isinstance(src, dict):
            continue
        for lat_key in ("lat", "latitude", "gps_lat", "location_lat"):
            for lng_key in ("lon", "lng", "longitude", "gps_lng", "gps_lon", "location_lng"):
                if src.get(lat_key) and src.get(lng_key):
                    lat = safe_float(src[lat_key])
                    lng = safe_float(src[lng_key])
                    break
            if lat and lng:
                break
        # Попробуем вложенные location/gps объекты
        for loc_key in ("location", "gps", "coordinates"):
            loc = src.get(loc_key)
            if isinstance(loc, dict):
                lat = safe_float(loc.get("lat") or loc.get("latitude"))
                lng = safe_float(loc.get("lon") or loc.get("lng") or loc.get("longitude"))
                if lat and lng:
                    break
        if lat and lng:
            break
    if not lat or not lng:
        return None
    return (bbox["lat_min"] <= lat <= bbox["lat_max"] and
            bbox["lng_min"] <= lng <= bbox["lng_max"])


def import_city(client: TrendagentClient, city_slug: str, limit: int = 0,
                offset: int = 0, specific_block_id: str = None, dry_run: bool = False,
                import_apartments: bool = False, delete_summaries: bool = False,
                geo_filter: bool = False):
    """Основной импорт одного города.
    
    geo_filter=True — пропускает ЖК, координаты которых выходят за bbox города
    (исключает Тихорецк, Суворов ГК и т.п. из импорта Краснодара).
    """

    with app.app_context():
        # Находим наш City
        city = City.query.filter_by(slug=city_slug).first()
        if not city:
            name_map = {
                "krasnodar":    "Краснодар",
                "sochi":        "Сочи",
                "anapa":        "Анапа",
                "novorossiysk": "Новороссийск",
                "gelendzhik":   "Геленджик",
                "maykop":       "Майкоп",
            }
            cname = name_map.get(city_slug)
            if cname:
                city = City.query.filter(City.name.ilike(cname)).first()
        if not city:
            logger.error(f"❌ Город не найден в БД: {city_slug}")
            return

        mongo_id = CITY_MONGO_IDS.get(city_slug)
        if not mongo_id:
            logger.error(f"❌ Нет MongoDB ObjectID для города: {city_slug}")
            logger.info("   Добавьте ID в словарь CITY_MONGO_IDS скрипта")
            return

        logger.info(f"🏙️  Импорт: {city.name} (MongoID: {mongo_id})")

        # ── Формируем список block_id ──────────────────────────────
        if specific_block_id:
            block_ids  = [specific_block_id]
            blocks_idx = {}
        else:
            logger.info("📋 Загрузка списка ЖК …")
            all_blocks = client.get_all_blocks(mongo_id)
            if not all_blocks:
                logger.error("❌ Не удалось загрузить список ЖК")
                return
            logger.info(f"✅ Найдено ЖК: {len(all_blocks)}")
            if offset:
                all_blocks = all_blocks[offset:]
            if limit:
                all_blocks = all_blocks[:limit]
            block_ids  = [str(b.get("_id") or b.get("id") or "") for b in all_blocks if b.get("_id") or b.get("id")]
            blocks_idx = {bid: b for bid, b in zip(block_ids, all_blocks)}

        stats = dict(developers=0, complexes_new=0, complexes_upd=0,
                     buildings=0, price_records=0, apartments=0, errors=0)

        for idx, bid in enumerate(block_ids, 1):
            if not bid:
                continue
            logger.info(f"\n[{idx}/{len(block_ids)}] block_id={bid}")

            if dry_run:
                logger.info("  (dry-run, пропуск)")
                continue

            try:
                # ── 1. Block detail (основной API) ──────────────────
                block = client.get_block_detail(bid)
                if not block:
                    block = blocks_idx.get(bid, {})
                if not block:
                    logger.warning(f"  ⚠️  Пустой ответ для {bid}")
                    stats["errors"] += 1
                    continue

                # ── 2. Block detail (apartment-api) — галерея, цены ─
                time.sleep(0.2)
                apt_block = client.get_block_apt_api(bid)

                # ── 3. Unified — корпуса + геометрия ──────────────
                time.sleep(0.2)
                unified = client.get_block_unified(bid)

                # ── 3a. Геофильтр: пропускаем объекты вне города ───
                if geo_filter:
                    bbox = CITY_BBOX.get(city_slug)
                    if bbox:
                        in_city = _bbox_check(block, apt_block, bbox)
                        if in_city is False:
                            rc_name_hint = block.get("name") or bid
                            logger.info(f"  🗺️  Пропущен (вне bbox города): {rc_name_hint}")
                            stats.setdefault("geo_filtered", 0)
                            stats["geo_filtered"] += 1
                            continue
                        elif in_city is None:
                            logger.debug(f"  🗺️  Нет координат для геофильтра: {bid}")

                # ── 4. Застройщик ──────────────────────────────────
                builder_raw = block.get("builder") or block.get("developer") or {}
                if apt_block and apt_block.get("builder"):
                    builder_raw = apt_block["builder"]  # apt_block даёт больше полей
                developer = upsert_developer(builder_raw)

                # ── 5. ЖК ─────────────────────────────────────────
                rc = upsert_complex(block, apt_block, unified, city, developer)
                if not rc:
                    stats["errors"] += 1
                    db.session.rollback()
                    continue
                if rc.id is None:
                    db.session.flush()

                # ── 5a. Fallback reward из данных списка ЖК ────────
                # block_detail может возвращать reward=null, а list API даёт
                # reward=[{"view":1,"label":"4.5-6.5%"}] — берём оттуда
                if not getattr(rc, "ta_reward_label", None) and hasattr(rc, "ta_reward_label"):
                    list_block = blocks_idx.get(bid, {})
                    list_reward = list_block.get("reward")
                    if list_reward:
                        _lb = None
                        if isinstance(list_reward, list):
                            for _item in list_reward:
                                if isinstance(_item, dict) and _item.get("label"):
                                    _lb = str(_item["label"]).strip()
                                    break
                        elif isinstance(list_reward, dict):
                            _lb = (list_reward.get("label") or "").strip() or None
                        elif isinstance(list_reward, str):
                            _lb = list_reward.strip() or None
                        if _lb:
                            rc.ta_reward_label = _lb[:100]
                            # Пересчитываем кэшбек
                            import re as _re_fb
                            _nums_fb = [float(x) for x in _re_fb.findall(r"\d+(?:\.\d+)?", _lb)]
                            if _nums_fb:
                                _ap = min(_nums_fb)
                                _ip = round(max(1.0, min(10.0, _ap * 0.40)), 2)
                                current_cb = getattr(rc, "cashback_rate", None)
                                if not current_cb or current_cb <= 0 or abs(current_cb - 5.0) < 0.01:
                                    rc.cashback_rate = _ip
                                    logger.info(
                                        f"    💎 Кэшбек (list fallback) «{rc.name}»: "
                                        f"агент {_ap}% → InBack {_ip}%"
                                    )

                # ── 6. Корпуса ─────────────────────────────────────
                buildings_map = upsert_buildings(unified, rc)
                stats["buildings"] += len(buildings_map)

                db.session.commit()
                logger.info(f"    Корпусов: {len(buildings_map)}")

                # ── 7. Квартиры (индивидуальные) или ценовые сводки ─
                if import_apartments and buildings_map:
                    n_apts = upsert_apartments(
                        client, rc, buildings_map, city, mongo_id,
                        delete_summaries=delete_summaries,
                    )
                    if n_apts:
                        stats["apartments"] += n_apts
                        logger.info(f"    ✅ Квартир импортировано: {n_apts}")
                        # ── Fallback reward/cashback из первой квартиры ──
                        # block_detail часто возвращает reward=null;
                        # квартиры всегда содержат ta_reward_label
                        if not getattr(rc, "ta_reward_label", None) and hasattr(rc, "ta_reward_label"):
                            from sqlalchemy import text as _sq_text
                            _apt_lbl = db.session.execute(
                                _sq_text(
                                    "SELECT ta_reward_label FROM properties "
                                    "WHERE complex_id=:cid AND ta_reward_label IS NOT NULL "
                                    "AND external_id LIKE 'ta_apt_%' LIMIT 1"
                                ),
                                {"cid": rc.id},
                            ).scalar()
                            if _apt_lbl:
                                rc.ta_reward_label = _apt_lbl
                                import re as _re_apt
                                _nums_a = [float(x) for x in _re_apt.findall(r"\d+(?:\.\d+)?", _apt_lbl)]
                                if _nums_a:
                                    _ap_a = min(_nums_a)
                                    _ip_a = round(max(1.0, min(10.0, _ap_a * 0.40)), 2)
                                    current_cb = getattr(rc, "cashback_rate", None)
                                    if not current_cb or current_cb <= 0 or abs(current_cb - 5.0) < 0.01:
                                        rc.cashback_rate = _ip_a
                                        logger.info(
                                            f"    💎 Кэшбек (apt fallback) «{rc.name}»: "
                                            f"агент {_ap_a}% → InBack {_ip_a}%"
                                        )
                                db.session.commit()
                    else:
                        # fallback на сводки если квартиры не получены
                        n_prices = upsert_price_summaries(apt_block, rc, buildings_map, city)
                        if n_prices:
                            db.session.commit()
                            stats["price_records"] += n_prices
                            logger.info(f"    Ценовые сводки (fallback): {n_prices}")
                else:
                    # ── 7a. Ценовые сводки из apartmentsMinPrices ──
                    n_prices = upsert_price_summaries(apt_block, rc, buildings_map, city)
                    if n_prices:
                        db.session.commit()
                        stats["price_records"] += n_prices
                        logger.info(f"    Ценовые сводки: {n_prices}")

            except Exception as e:
                db.session.rollback()
                logger.error(f"  ❌ Ошибка ЖК {bid}: {e}", exc_info=True)
                stats["errors"] += 1
                continue

            time.sleep(0.5)

        logger.info(f"""
╔══════════════════════════════════════════╗
  ИМПОРТ ЗАВЕРШЁН: {city.name}
  ЖК обработано:    {len(block_ids)}
  Корпусов:         {stats['buildings']}
  Ценовых записей:  {stats['price_records']}
  Квартир (шахм.):  {stats['apartments']}
  Ошибок:           {stats['errors']}
╚══════════════════════════════════════════╝
""")


# ─────────────────────────────────────────────────────────────────
# ТОЧКА ВХОДА
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Импорт данных Trendagent → наша БД")
    parser.add_argument("--city",             default="krasnodar",
                        help="Slug города: krasnodar, sochi, anapa … (по умолчанию: krasnodar)")
    parser.add_argument("--limit",            type=int, default=0,
                        help="Максимум ЖК (0 = все)")
    parser.add_argument("--offset",           type=int, default=0,
                        help="Пропустить первые N ЖК из списка")
    parser.add_argument("--complex-id",       default=None,
                        help="Конкретный block_id Trendagent (MongoDB ObjectID)")
    parser.add_argument("--dry-run",          action="store_true",
                        help="Только авторизация + подсчёт ЖК, без записи в БД")
    parser.add_argument("--apartments",       action="store_true",
                        help="Импортировать индивидуальные квартиры (шахматку) "
                             "вместо/вместе с ценовыми сводками. "
                             "Каждая квартира → отдельная Property с exact этажом/площадью.")
    parser.add_argument("--delete-summaries", action="store_true",
                        help="При --apartments деактивировать старые ценовые сводки ЖК "
                             "(external_id='ta_bld_*' / 'ta_rc_*') после загрузки реальных квартир.")
    parser.add_argument("--phone",            default=None, help="Телефон Trendagent")
    parser.add_argument("--password",         default=None, help="Пароль Trendagent")
    args = parser.parse_args()

    phone    = args.phone    or os.environ.get("TRENDAGENT_PHONE",    "")
    password = args.password or os.environ.get("TRENDAGENT_PASSWORD", "")

    if not phone or not password:
        print("❌ Нужны учётные данные Trendagent.")
        print("   Env-переменные: TRENDAGENT_PHONE, TRENDAGENT_PASSWORD")
        print("   Или флаги:      --phone, --password")
        sys.exit(1)

    client = TrendagentClient(phone, password)
    if not client.login():
        logger.error("Авторизация провалена")
        sys.exit(1)

    import_city(
        client,
        city_slug          = args.city,
        limit              = args.limit,
        offset             = args.offset,
        specific_block_id  = args.complex_id,
        dry_run            = args.dry_run,
        import_apartments  = args.apartments,
        delete_summaries   = args.delete_summaries,
    )
