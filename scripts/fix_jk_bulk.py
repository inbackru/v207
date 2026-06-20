"""
fix_jk_bulk.py — массовое обогащение ЖК данными с CIAN.
Берёт все ЖК у которых нет фото / координат / адреса / застройщика
и скрапит их CIAN-страницы.

Запуск:
    python scripts/fix_jk_bulk.py [--city 1] [--limit 50] [--id 370,454]
    python scripts/fix_jk_bulk.py --force   # перезаписать даже имеющиеся данные
"""
import sys, os, re, json, time, html as html_lib, argparse
from datetime import datetime

import psycopg2
import requests
import urllib3
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from enrich_complexes import (
    _safe_decode, _strip_html, _parse_about_description,
    _parse_logo_url, _parse_finishing_variants,
    _CIAN_DOMAIN_TO_CITY_ID,
)
from parse_jk_by_url import get_or_create_developer, slug_from_name


# ─── Настройки ───────────────────────────────────────────────────────────────
_DIR       = os.path.dirname(os.path.abspath(__file__))
SETTINGS   = json.load(open(os.path.join(_DIR, '.enrich_settings.json'))) \
             if os.path.exists(os.path.join(_DIR, '.enrich_settings.json')) else {}
_RAW_PROXY_URL  = SETTINGS.get('proxy_url', '')
REQ_DELAY       = float(SETTINGS.get('delay_between_requests', 2.0))
SESSION_TTL     = 240  # пересоздавать сессию каждые 4 мин (новый IP ротации)

def _check_proxy(proxy_url: str, timeout: int = 6) -> bool:
    """Быстрая проверка: отвечает ли прокси за timeout секунд."""
    if not proxy_url:
        return False
    try:
        r = requests.get(
            'https://cian.ru/',
            proxies={'http': proxy_url, 'https': proxy_url},
            timeout=timeout, verify=False, allow_redirects=False
        )
        return r.status_code < 500
    except Exception:
        return False

# Проверяем прокси при старте — если недоступен, отключаем
if _RAW_PROXY_URL:
    _proxy_ok = _check_proxy(_RAW_PROXY_URL, timeout=8)
    PROXY_URL = _RAW_PROXY_URL if _proxy_ok else ''
    if _proxy_ok:
        print(f'🔀 Прокси: {_RAW_PROXY_URL.split("@")[-1]} (ротация каждые {SESSION_TTL}с)')
    else:
        print(f'⚠️  Прокси недоступен ({_RAW_PROXY_URL.split("@")[-1]}) — работаем напрямую')
else:
    PROXY_URL = ''
    print('ℹ️  Прокси не настроен — прямой доступ')
ANTICAPTCHA_KEY = (os.environ.get('ENRICH_ANTICAPTCHA', '').strip()
                   or SETTINGS.get('anticaptcha_key', '').strip())

# Конфиг городов
_CITY_CONFIG: dict = {}
try:
    with open(os.path.join(_DIR, 'city_config.json'), encoding='utf-8') as _cf:
        _CITY_CONFIG = json.load(_cf)
except Exception:
    pass


def _city_id_from_jk_url(url: str, default: int) -> int:
    """Определяет city_id из URL страницы ЖК на ЦИАН.

    Поддерживаемые форматы:
      https://zhk-SLUG-krasnodar-i.cian.ru/   → city_id=1
      https://zhk-SLUG-maykop-i.cian.ru/       → city_id=8
      https://krasnodar.cian.ru/...             → city_id=1  (поддомен квартиры)
      https://www.cian.ru/zhilye-kompleksy/...  → default    (нет признака города)
    """
    if not url:
        return default
    # Формат ЖК: zhk-SLUG-CITY-i.cian.ru или zhk-SLUG-CITY.cian.ru
    m = re.match(r'https?://zhk-(.+?)-i\.cian\.ru', url)
    if m:
        slug_parts = m.group(1).rsplit('-', 1)
        city_slug = slug_parts[-1].lower()
        if city_slug in _CIAN_DOMAIN_TO_CITY_ID:
            return _CIAN_DOMAIN_TO_CITY_ID[city_slug]
    # Формат поддомена квартиры: krasnodar.cian.ru
    m2 = re.match(r'https?://([^.]+)\.cian\.ru', url)
    if m2:
        subdomain = m2.group(1).lower()
        if subdomain in _CIAN_DOMAIN_TO_CITY_ID:
            return _CIAN_DOMAIN_TO_CITY_ID[subdomain]
    return default


def _load_jk_cache(city_id: int) -> dict:
    """Загружает кэш Phase 1 для нужного города (per-city + fallback к общему)."""
    for fname in (f'.enrich_cache_city{city_id}.json', '.enrich_cache.json'):
        path = os.path.join(_DIR, fname)
        if os.path.exists(path):
            try:
                return json.load(open(path)).get('jk_search_data', {})
            except Exception:
                pass
    return {}


# Кэш загружается в main() после парсинга --city; пока пустой
_JK_CACHE: dict = {}

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
}

_sess: requests.Session | None = None
_session_created_at = 0.0

if ANTICAPTCHA_KEY:
    print(f'🔐 Anti-Captcha: ключ установлен ({ANTICAPTCHA_KEY[:6]}...)')


def _solve_anticaptcha(page_url: str, sitekey: str = None) -> str | None:
    """Решает reCAPTCHA v2 через anti-captcha.com. Возвращает token или None."""
    if not ANTICAPTCHA_KEY:
        return None
    try:
        import urllib.request as _urlreq
        _sitekey = sitekey or ''
        _api = ''

        body = json.dumps({
            'clientKey': ANTICAPTCHA_KEY,
            'task': {
                'type': 'RecaptchaV2TaskProxyless',
                'websiteURL': page_url,
                'websiteKey': _sitekey,
            },
        }).encode()
        req = _urlreq.Request(f'{_api}/createTask', data=body,
                              headers={'Content-Type': 'application/json'})
        with _urlreq.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        if data.get('errorId', 1) != 0:
            print(f'    ⚠️  anti-captcha createTask: {data.get("errorDescription")}')
            return None
        task_id = data['taskId']
        print(f'    🔐 anti-captcha: задача #{task_id}, ждём решения...')

        result_body = json.dumps({'clientKey': ANTICAPTCHA_KEY, 'taskId': task_id}).encode()
        for i in range(24):
            time.sleep(5)
            req2 = _urlreq.Request(f'{_api}/getTaskResult', data=result_body,
                                   headers={'Content-Type': 'application/json'})
            with _urlreq.urlopen(req2, timeout=20) as r:
                res = json.loads(r.read())
            if res.get('errorId', 0) != 0:
                print(f'    ⚠️  anti-captcha error: {res.get("errorDescription")}')
                return None
            if res.get('status') == 'ready':
                token = res.get('solution', {}).get('gRecaptchaResponse')
                if token:
                    print(f'    ✅ anti-captcha: решена (попытка {i+1})')
                    return token
        print('    ⚠️  anti-captcha timeout (120s)')
        return None
    except Exception as e:
        print(f'    ⚠️  anti-captcha exception: {e}')
        return None


def _get_session() -> requests.Session:
    global _sess, _session_created_at
    now = time.time()
    if _sess is None or (now - _session_created_at) > SESSION_TTL:
        if _sess:
            try: _sess.close()
            except: pass
        s = requests.Session()
        s.headers.update(_HEADERS)
        s.verify = False
        if PROXY_URL:
            s.proxies = {'http': PROXY_URL, 'https': PROXY_URL}
        _sess = s
        _session_created_at = now
        print('  🔄 Новая сессия (ротация IP прокси)')
    return _sess


def _fetch(url: str, timeout: int = 25) -> tuple[str, str] | tuple[None, None]:
    """Загрузить страницу. Возвращает (html, actual_url) или (None, None).
    При ProxyError — автоматически пробует прямое подключение без прокси.
    При капче — пытается решить через anti-captcha.com."""
    global _sess
    _proxy_failed_count = 0
    for attempt in range(4):
        try:
            sess = _get_session()
            # Fallback: если прокси уже падал 2+ раз подряд — пробуем без прокси
            if _proxy_failed_count >= 2 and PROXY_URL and sess.proxies:
                print(f'    ℹ️  Прокси недоступен — пробуем прямой доступ (попытка {attempt+1})')
                sess = requests.Session()
                sess.headers.update(_HEADERS)
                sess.verify = False
            resp = sess.get(url, timeout=timeout, allow_redirects=True)
            resp.encoding = 'utf-8'
            actual_url = resp.url  # URL после всех редиректов

            # Капча / блокировка
            is_captcha = ('showcaptcha' in actual_url or resp.status_code == 403
                          or (resp.status_code == 200
                              and 'showcaptcha' in resp.text[:500].lower()))
            if is_captcha:
                print(f'    ⚠️  Капча обнаружена (попытка {attempt+1}): {actual_url[:80]}')
                _sess = None  # сменить IP
                if ANTICAPTCHA_KEY:
                    token = _solve_anticaptcha(url)
                    if token:
                        sess = _get_session()
                        sess.cookies.set('g-recaptcha-response', token)
                        continue
                time.sleep(5 * (attempt + 1))
                continue

            if resp.status_code == 404:
                print(f'    ⚠️  404: {url}')
                return None, None

            if resp.status_code == 200 and len(resp.text) > 5000:
                _proxy_failed_count = 0  # сброс счётчика при успехе
                return resp.text, actual_url

            print(f'    ⚠️  HTTP {resp.status_code}, len={len(resp.text)} (попытка {attempt+1})')
        except requests.exceptions.ProxyError:
            _proxy_failed_count += 1
            print(f'    ⚠️  ProxyError (попытка {attempt+1}, сбоев прокси: {_proxy_failed_count})')
            _sess = None
        except Exception as e:
            print(f'    ⚠️  {type(e).__name__}: {e} (попытка {attempt+1})')
        time.sleep(2.5 * (attempt + 1))
    return None, None


# ─── Извлечение данных со страницы ───────────────────────────────────────────

_CITY_SFXS = re.compile(
    r'-(krasnodar|maykop|sochi|anapa|gelendzhik|novorossiysk|armavir|'
    r'adygeysk|stavropol|rostov|volgograd|moscow|spb|kursk|voronezh|'
    r'belgorod|lipetsk|tambov|orel|bryansk|tula|kaluga|smolensk|'
    r'ekaterinburg|chelyabinsk|ufa|kazan|samara|saratov|perm|'
    r'nizhniy-novgorod|novosibirsk|omsk|krasnoyarsk|irkutsk|tyumen|'
    r'krasnodar-kray)$'
)


def _extract_photos(text: str, jk_url: str) -> list[str]:
    """Именованные -jk- фото с CDN CIAN (поддерживает 1–4 уровня субдиректорий).

    Логика:
    1. Сначала пробуем slug-фильтр — берём только фото именно этого ЖК.
    2. Если 0 — fallback: берём первые N уникальных -jk- фото со страницы
       (на странице конкретного ЖК в начале страницы лежат именно его фото).
    """
    slug_m = re.search(r'zhk-(.+?)-i\.cian\.ru', jk_url)
    jk_slug_full = slug_m.group(1).lower() if slug_m else ''
    jk_slug_key  = _CITY_SFXS.sub('', jk_slug_full).replace('-', '')

    def slug_ok(img: str) -> bool:
        low = re.sub(r'[^a-z0-9]', '', img.lower())
        return bool(jk_slug_key) and jk_slug_key in low

    raw = re.findall(
        r'images\.cdn-cian\.ru/images/(?:[0-9]+/)*'
        r'[a-zA-Z0-9_-]+-jk-[0-9]+-[0-9]+\.jpg',
        text
    )

    def normalise(img: str) -> str:
        base = re.sub(r'-[0-9]+\.jpg$', '-1.jpg', img)
        return 'https://' + base

    # ── Шаг 1: строгий slug-фильтр ────────────────────────────────────────────
    photos, seen = [], set()
    for img in raw:
        if not slug_ok(img):
            continue
        full = normalise(img)
        if full not in seen:
            seen.add(full)
            photos.append(full)

    # ── Шаг 2: fallback — первые unique -jk- фото из верхней части страницы ──
    if not photos:
        # Ищем только в первых ~400 KB HTML (галерея ЖК всегда в начале)
        for img in raw[:80]:
            full = normalise(img)
            if full not in seen:
                seen.add(full)
                photos.append(full)
            if len(photos) >= 10:
                break

    return photos[:30]


# Bounds берём из city_config.json для конкретного города; fallback — вся Россия
def _get_coord_bounds(city_id: int) -> tuple[float, float, float, float]:
    cfg = _CITY_CONFIG.get(str(city_id), {})
    return (
        float(cfg.get('lat_min', 40.0)),
        float(cfg.get('lat_max', 80.0)),
        float(cfg.get('lon_min', 19.0)),
        float(cfg.get('lon_max', 190.0)),
    )

_LAT_MIN, _LAT_MAX, _LON_MIN, _LON_MAX = _get_coord_bounds(1)   # обновляется в main()

_CIAN_FAKE_COORD = (44.609139, 37.6213)  # CIAN placeholder для «координаты неизвестны»


def _extract_coords(text: str) -> tuple[float | None, float | None]:
    """Координаты ЖК, строго в границах Краснодарского края/Адыгеи.
    Приоритет: вложенный объект \"coordinates\":{\"lat\":...} — самый надёжный из CIAN."""
    def _in_range(lat, lon):
        if abs(lat - _CIAN_FAKE_COORD[0]) < 0.001 and abs(lon - _CIAN_FAKE_COORD[1]) < 0.001:
            return False  # CIAN-заглушка «координаты неизвестны»
        return _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX

    # 1. Предпочитаем вложенный geo-объект {"lat":XX,"lng":YY} — максимально точно
    for m in re.finditer(
        r'"(?:coordinates|geoPoint|point|geo)"\s*:\s*\{[^}]*?"lat(?:itude)?"\s*:\s*([\d.]+)[^}]*?"(?:lng|lon(?:gitude)?)"\s*:\s*([\d.]+)',
        text
    ):
        lat, lon = float(m.group(1)), float(m.group(2))
        if _in_range(lat, lon):
            return lat, lon

    # 2. Пара на одной строке: latitude=XX&longitude=YY (URL-encoded в атрибутах)
    for m in re.finditer(
        r'lat(?:itude)?[=:]([0-9.]+)[^0-9.]{1,20}?lon(?:gitude)?[=:]([0-9.]+)',
        text
    ):
        lat, lon = float(m.group(1)), float(m.group(2))
        if _in_range(lat, lon):
            return lat, lon

    # 3. Fallback: все вхождения "lat":... и "lng":... по отдельности (только в диапазоне)
    lats = [float(x) for x in re.findall(r'"lat(?:itude)?"\s*:\s*([\d.]+)', text)
            if _LAT_MIN <= float(x) <= _LAT_MAX]
    lons = [float(x) for x in re.findall(r'"(?:lng|lon(?:gitude)?)"\s*:\s*([\d.]+)', text)
            if _LON_MIN <= float(x) <= _LON_MAX]
    return (lats[0] if lats else None, lons[0] if lons else None)


def _extract_description(text: str) -> str | None:
    """
    Описание ЖК. Приоритет:
    1. data-testid="AboutDescription" — официальный HTML-блок
    2. JSON-поля "description" / "about" с unicode-escapes (\u003C → <)
    3. Параграфы HTML вокруг 'AboutSection'
    """
    about = _parse_about_description(text)
    if about and len(about) > 80:
        return about[:6000]

    for pat in [
        r'"description"\s*:\s*"((?:[^"\\]|\\.){100,}?)"(?=[,}\]])',
        r'"about"\s*:\s*"((?:[^"\\]|\\.){100,}?)"(?=[,}\]])',
        r'"longDescription"\s*:\s*"((?:[^"\\]|\\.){100,}?)"(?=[,}\]])',
    ]:
        for raw in re.findall(pat, text, re.DOTALL):
            decoded = _safe_decode(raw)  # декодирует \u003C, убирает HTML-теги
            if (len(decoded) > 100
                    and re.search(r'[а-яА-Я]', decoded)
                    and 'Информация от официального' not in decoded
                    and 'Рейтинг основан' not in decoded
                    and not decoded.startswith('✅')):
                # Дополнительная очистка HTML-энтити
                decoded = html_lib.unescape(decoded)
                return decoded[:6000]

    # HTML-параграфы
    for anchor in ['AboutDescription', 'AboutSection', 'about-section', 'jk-about']:
        idx = text.find(anchor)
        if idx < 0:
            continue
        chunk = text[idx: idx + 8000]
        paras = [_strip_html(p) for p in re.findall(r'<p[^>]*>(.*?)</p>', chunk, re.DOTALL)]
        paras = [p for p in paras if len(p) > 30]
        if paras:
            return '\n\n'.join(paras[:10])[:6000]
    return None


def _extract_developer_info(text: str) -> dict:
    result = {}
    m = re.search(r'"developerName"\s*:\s*"([^"]{2,150})"', text)
    if m:
        result['name'] = _safe_decode(m.group(1))
    m2 = re.search(r'"developerId"\s*:\s*([0-9]+)', text)
    if m2:
        result['cian_id'] = int(m2.group(1))
    m3 = re.search(r'cian\.ru/(zastroishchik-[a-z0-9-]+-[0-9]+)', text)
    if m3:
        result['url'] = 'https://cian.ru/' + m3.group(1)
    logo = _parse_logo_url(text)
    if logo:
        result['logo'] = logo
    return result


# Navigation elements to skip when building address from fullName components.
# These are top-level country/region names that appear as nav breadcrumbs on every CIAN page.
_ADDR_SKIP = {
    'россия', 'краснодарский край', 'республика адыгея', 'ставропольский край',
    'ростовская область', 'москва', 'санкт-петербург', 'краснодар', 'сочи',
    'республика алтай', 'алтайский край', 'новосибирск', 'новосибирская область',
    # Additional regions/cities we now support
    'курская область', 'белгородская область', 'воронежская область',
    'тульская область', 'орловская область', 'брянская область',
    'курск', 'белгород', 'воронеж', 'тула', 'орёл', 'орел', 'брянск',
    'майкоп', 'республика адыгея',
}

def _extract_address(text: str) -> str | None:
    """Адрес ЖК — ищем fullAddress или собираем из fullName-компонентов страницы ЖК.

    Работает для всех регионов (не только Краснодар).
    fullAddress на CIAN-странице всегда относится к конкретному ЖК.
    """
    # Берём первый fullAddress — он всегда привязан к текущему ЖК на CIAN
    m = re.search(r'"fullAddress"\s*:\s*"([^"]{5,250})"', text)
    if m:
        addr = _safe_decode(m.group(1))
        if addr and len(addr) > 5:
            return addr

    # Из fullName-компонентов: берём только первое вхождение (до первого повтора)
    raw_parts = re.findall(r'"fullName"\s*:\s*"([^"]{3,120})"', text)
    parts, seen = [], set()
    for p in raw_parts[:20]:   # первые 20 — обычно данные текущей страницы
        d = _safe_decode(p)
        key = d.lower().strip()
        if key in _ADDR_SKIP or d in seen:
            continue
        seen.add(d)
        parts.append(d)
        # Стоп как только встретили второй город — это уже навигация
        if len(parts) >= 4:
            break
    if parts:
        return ', '.join(parts)
    return None


def _extract_geo_components(text: str) -> dict:
    """Извлекает структурированные компоненты адреса из JSON страницы CIAN.

    CIAN вставляет в страницу JSON с типизированными адресными элементами:
      {"type":"region","name":"Краснодарский край","fullName":"Краснодарский край"}
      {"type":"city",  "name":"Краснодар",         "fullName":"Краснодар"}
      {"type":"okrug", "name":"Центральный",        "fullName":"Центральный округ"}
      {"type":"district","name":"Черемушки",        "fullName":"Черемушки мкр"}
      {"type":"street","name":"Обрывная",           "fullName":"улица Обрывная"}
      {"type":"house", "name":"5"}

    Возвращает dict с ключами:
      addr_region, addr_city, address_city_district,
      address_quarter, addr_street, addr_house
    """
    result: dict = {}
    if not text:
        return result

    # Ищем блоки: "type":"X" + ближайший "fullName"/"name" в той же JSON-записи
    # Допускаем до 400 символов между type и name (дополнительные поля id, url и т.п.)
    pattern = re.compile(
        r'"type"\s*:\s*"(region|city|okrug|district|raion|quarter|street|house)"'
        r'(?:[^}]{0,400}?)"(?:fullName|name)"\s*:\s*"([^"]{1,250})"',
        re.DOTALL
    )

    for m in pattern.finditer(text):
        t = m.group(1)
        name = _safe_decode(m.group(2)).strip()
        if not name:
            continue

        nl = name.lower()
        if t == 'region' and 'addr_region' not in result:
            result['addr_region'] = name
        elif t == 'city' and 'addr_city' not in result:
            # Skip generic "городской округ" noise values
            if 'городской округ' not in nl:
                result['addr_city'] = name
        elif t == 'okrug' and 'address_city_district' not in result:
            result['address_city_district'] = name
        elif t in ('district', 'raion', 'quarter'):
            # CIAN sometimes labels okrug-level entries as type=district
            if 'округ' in nl or 'okrug' in nl:
                if 'address_city_district' not in result:
                    result['address_city_district'] = name
            else:
                if 'address_quarter' not in result:
                    result['address_quarter'] = name
        elif t == 'street' and 'addr_street' not in result:
            result['addr_street'] = name
        elif t == 'house' and 'addr_house' not in result:
            result['addr_house'] = name

    return result


def _build_address_from_components(c: dict, fallback: str | None = None) -> str | None:
    """Строит полную адресную строку в стиле CIAN из структурированных компонентов."""
    parts = []
    for key in ('addr_region', 'addr_city', 'address_city_district',
                 'address_quarter', 'addr_street', 'addr_house'):
        v = c.get(key)
        if v:
            parts.append(v)
    if len(parts) >= 2:
        return ', '.join(parts)
    return fallback


# ─── Обработка одного ЖК ─────────────────────────────────────────────────────

def process_jk(cur, conn, rc_id: int, rc_name: str, rc_slug: str,
               cian_id: int | None, dev_cache: dict, force: bool = False,
               expected_city_id: int = 1) -> dict:
    result = {'rc_id': rc_id, 'name': rc_name, 'status': 'skip'}

    # ── 1. Данные из Phase-1 кэша ──────────────────────────────────────────────
    cache_key  = str(cian_id) if cian_id else ''
    cache_data = _JK_CACHE.get(cache_key, {})
    cache_url  = cache_data.get('jk_url', '')

    # Список URL для попытки (порядок важен — первый успешный побеждает)
    _city_sfxs = ['krasnodar', 'sochi', 'anapa', 'gelendzhik', 'novorossiysk',
                  'maykop', 'armavir', 'krasnodar-kray',
                  'kursk', 'voronezh', 'belgorod', 'lipetsk', 'tambov',
                  'orel', 'bryansk', 'tula', 'kaluga', 'smolensk',
                  'rostov', 'stavropol', 'volgograd', 'samara', 'saratov',
                  'ekaterinburg', 'ufa', 'kazan', 'perm', 'nizhniy-novgorod',
                  'novosibirsk', 'omsk', 'krasnoyarsk', 'tyumen', 'spb', 'moscow']
    urls_to_try: list[str] = []
    if cache_url:
        urls_to_try.append(cache_url)
    if rc_slug:
        # С городским суффиксом (нужен для большинства краснодарских ЖК)
        for city in _city_sfxs:
            candidate = f'https://zhk-{rc_slug}-{city}-i.cian.ru/'
            if candidate not in urls_to_try:
                urls_to_try.append(candidate)
        # Слаг без дефисов (напр. instepsiti вместо instep-siti)
        rc_slug_nodash = rc_slug.replace('-', '')
        if rc_slug_nodash != rc_slug:
            for city in _city_sfxs:
                candidate_nd = f'https://zhk-{rc_slug_nodash}-{city}-i.cian.ru/'
                if candidate_nd not in urls_to_try:
                    urls_to_try.append(candidate_nd)
            bare_nd = f'https://zhk-{rc_slug_nodash}-i.cian.ru/'
            if bare_nd not in urls_to_try:
                urls_to_try.append(bare_nd)
        # Без суффикса — запасной вариант
        bare = f'https://zhk-{rc_slug}-i.cian.ru/'
        if bare not in urls_to_try:
            urls_to_try.append(bare)
    # Редирект CIAN по ID — работает для всех, последний шанс
    if cian_id:
        cian_redirect = f'https://www.cian.ru/zhilye-kompleksy/{cian_id}/'
        if cian_redirect not in urls_to_try:
            urls_to_try.append(cian_redirect)

    # ── 2. Загрузка страницы ЖК ───────────────────────────────────────────────
    text = None
    final_url = ''
    for url in urls_to_try:
        t, actual_url = _fetch(url)
        if t and len(t) > 8000:
            # Пропускаем soft-block страницы, которые прошли мимо _fetch()
            # (ЦИАН иногда возвращает 200 OK с капча-страницей)
            _soft_block = (
                'Доступ к этой странице ограничен' in t[:3000] or
                'Подтвердите, что вы не робот' in t[:3000] or
                'Сервис временно недоступен' in t[:2000] or
                'recaptcha' in t[:1500].lower()
            )
            if _soft_block:
                time.sleep(REQ_DELAY)
                continue
            # Убеждаемся что это страница ЖК, а не главная/поиск
            if 'zhk-' in (actual_url or url).lower() or 'newbuilding' in t[:2000].lower() or 'ЖК' in t[:3000]:
                text = t
                final_url = actual_url or url  # используем URL после редиректа
                break
        time.sleep(REQ_DELAY * 0.5)

    # ── 2б. Валидация города по итоговому URL ──────────────────────────────────
    # Определяем city_id из final_url и сравниваем с ожидаемым.
    # Если не совпадает — обновляем residential_complexes.city_id в БД и логируем.
    # ВАЖНО: обновляем city_id ТОЛЬКО если страница содержит реальные данные ЖК
    # (цены, площади, квартиры) — это гарантирует, что мы не обновили city_id по
    # капча-странице или по URL-кандидату без реального контента.
    if final_url and text:
        _has_rc_content = (
            '₽' in text or 'руб' in text[:6000] or
            'м²' in text or 'кв.м' in text[:6000] or
            'квартир' in text[:5000].lower() or
            'новостройк' in text[:5000].lower()
        )
        if _has_rc_content:
            detected_city = _city_id_from_jk_url(final_url, default=expected_city_id)
            if detected_city != expected_city_id:
                city_names = {str(k): v.get('name', f'city{k}')
                              for k, v in _CITY_CONFIG.items()}
                expected_name = city_names.get(str(expected_city_id), str(expected_city_id))
                detected_name = city_names.get(str(detected_city), str(detected_city))
                print(f'  ⚠️  Город из URL: {detected_name} (id={detected_city}), '
                      f'ожидался: {expected_name} (id={expected_city_id}) — '
                      f'обновляю city_id в БД')
                cur.execute(
                    "UPDATE residential_complexes SET city_id=%s WHERE id=%s",
                    (detected_city, rc_id)
                )
                conn.commit()
        else:
            print(f'  ℹ️  city_id не обновляю (страница не содержит данных ЖК — вероятно, soft-block)')

    # ── 3. Извлечение данных ──────────────────────────────────────────────────
    # Фото: только из страницы
    photos: list[str] = []
    if text:
        photos = _extract_photos(text, final_url)

    # Координаты: сначала страница, потом кэш (там нет coords — заглушка)
    lat = lon = None
    if text:
        lat, lon = _extract_coords(text)

    # Описание: из страницы
    desc: str | None = None
    if text:
        desc = _extract_description(text)

    # Адрес: страница → кэш
    addr: str | None = None
    geo_components: dict = {}
    if text:
        addr = _extract_address(text)
        geo_components = _extract_geo_components(text)
        # Если fullAddress не найден — собираем из типизированных компонентов
        if not addr and geo_components:
            addr = _build_address_from_components(geo_components)
    if not addr and cache_data.get('address'):
        addr = cache_data['address']

    # Материал стен: страница → кэш
    material: str | None = None
    if text:
        m = re.search(r'"materialType"\s*:\s*"([^"]{3,80})"', text)
        if not m:
            m = re.search(r'"materials"\s*:\s*\["([^"]{3,80})"', text)
        material = _safe_decode(m.group(1)) if m else None
    if not material and cache_data.get('wall_material'):
        material = cache_data['wall_material']

    # Высота потолков: страница → кэш (поддержка диапазонов "2,7-2,72 м")
    ceiling_h: str | None = None
    if text:
        for _ch_pat in [
            # Диапазон строкой: "ceilingHeight":"2,7-2,72" или "2.7-2.72"
            r'"ceilingHeight"\s*:\s*"([0-9]+[.,][0-9]+\s*[–\-]\s*[0-9]+[.,][0-9]+)"',
            r'"heightCeiling"\s*:\s*"([0-9]+[.,][0-9]+\s*[–\-]\s*[0-9]+[.,][0-9]+)"',
            # Одно число строкой
            r'"ceilingHeight"\s*:\s*"?([0-9]+[.,][0-9]+)"?',
            r'"heightCeiling"\s*:\s*"?([0-9]+[.,][0-9]+)"?',
            # Диапазон в тексте страницы
            r'[Пп]отолки[^0-9]{0,30}([0-9]+[.,][0-9]+\s*[–\-]\s*[0-9]+[.,][0-9]+)\s*м',
            r'высота потолков[^0-9]{0,30}([0-9]+[.,][0-9]+\s*[–\-]?\s*[0-9]*[.,]?[0-9]*)\s*м',
            r'потолки[^0-9]{0,20}([0-9]+[.,][0-9]+)\s*м',
        ]:
            _ch_m = re.search(_ch_pat, text, re.I)
            if _ch_m:
                raw = _ch_m.group(1).strip()
                # Нормализуем разделитель к "–"
                raw = re.sub(r'\s*-\s*', '–', raw)
                ceiling_h = raw + ' м'
                break
    if not ceiling_h and cache_data.get('ceiling_height'):
        ceiling_h = str(cache_data['ceiling_height'])

    # Тип парковки: страница → кэш
    parking: str | None = None
    if text:
        for _pk_pat in [
            r'"parkingType"\s*:\s*"([^"]{3,80})"',
            r'"parking"\s*:\s*"([^"]{3,80})"',
            r'"parking"\s*:\s*\[.*?"name"\s*:\s*"([^"]{3,80})"',
        ]:
            _pk_m = re.search(_pk_pat, text, re.I | re.DOTALL)
            if _pk_m:
                parking = _safe_decode(_pk_m.group(1))
                break
        # Human-readable fallback
        if not parking:
            if re.search(r'подземн[а-я]+\s+парк', text, re.I):
                parking = 'Подземная'
            elif re.search(r'многоуровн[а-я]+\s+парк', text, re.I):
                parking = 'Многоуровневая'
            elif re.search(r'гостевая\s+парк|парковк[а-я]+.*гост', text, re.I):
                parking = 'Гостевая'
    if not parking and cache_data.get('parking_type'):
        parking = cache_data['parking_type']

    # Охрана / Security: страница → кэш
    security: str | None = None
    has_concierge: bool | None = None
    if text:
        sec_parts = []
        for _sp in [
            (r'"concierge"\s*:\s*true',           'Консьерж'),
            (r'"closedArea"\s*:\s*true',           'Закрытая территория'),
            (r'"securityPost"\s*:\s*true',         'Пост охраны'),
            (r'"videoSurveillance"\s*:\s*true',    'Видеонаблюдение'),
            (r'"intercom"\s*:\s*true',             'Домофон'),
        ]:
            if re.search(_sp[0], text, re.I):
                sec_parts.append(_sp[1])
        # Текстовые варианты
        if not sec_parts:
            for _sp in [
                (r'консьерж',          'Консьерж'),
                (r'видеонаблюдени',    'Видеонаблюдение'),
                (r'закрыт[а-я]+\s+тер', 'Закрытая территория'),
                (r'охран[а-я]+\s+пост|пост\s+охран', 'Пост охраны'),
                (r'домофон',           'Домофон'),
            ]:
                if re.search(_sp[0], text, re.I):
                    sec_parts.append(_sp[1])
        if sec_parts:
            security = ', '.join(sec_parts)
            has_concierge = 'Консьерж' in sec_parts
    if not security and cache_data.get('security_type'):
        security = cache_data['security_type']

    # Количество лифтов: страница → кэш
    lifts: int | None = None
    if text:
        for _lp in [
            r'"liftsCount"\s*:\s*([0-9]+)',
            r'"elevatorCount"\s*:\s*([0-9]+)',
            r'"lifts"\s*:\s*([0-9]+)',
            r'лифт[а-я]*\s*[—\-:]\s*([0-9]+)',
            r'([0-9]+)\s+лифт',
        ]:
            _lm = re.search(_lp, text, re.I)
            if _lm:
                try:
                    lifts = int(_lm.group(1))
                    if lifts > 50:  # санитарный лимит
                        lifts = None
                    else:
                        break
                except (ValueError, IndexError):
                    pass
    if lifts is None and cache_data.get('lifts_count'):
        try:
            lifts = int(cache_data['lifts_count'])
        except (ValueError, TypeError):
            pass

    # Диапазон лифтов ("от 2 до 10"): страница → кэш
    lifts_range: str | None = None
    if text:
        for _lrp in [
            r'"liftsCount"\s*:\s*"([^"]{3,30})"',      # строка в JSON
            r'(от\s+\d+\s+до\s+\d+)\s*лифт',
            r'лифт[а-я]*\s*[:\-—]\s*(от\s+\d+\s+до\s+\d+)',
            r'([0-9]+\s*[–\-]\s*[0-9]+)\s*лифт',
        ]:
            _lrm = re.search(_lrp, text, re.I)
            if _lrm:
                lifts_range = _lrm.group(1).strip()
                break

    # Этажность (floors_min / floors_max): страница
    floors_min_val: int | None = None
    floors_max_val: int | None = None
    if text:
        for _fp in [
            (r'"minFloor"\s*:\s*([0-9]+)',  'min'),
            (r'"maxFloor"\s*:\s*([0-9]+)',  'max'),
            (r'"floorsMin"\s*:\s*([0-9]+)', 'min'),
            (r'"floorsMax"\s*:\s*([0-9]+)', 'max'),
        ]:
            _fm = re.search(_fp[0], text, re.I)
            if _fm:
                try:
                    v = int(_fm.group(1))
                    if _fp[1] == 'min': floors_min_val = v
                    else:               floors_max_val = v
                except (ValueError, IndexError):
                    pass
        # Если только одно значение этажности
        if not floors_max_val:
            _fxm = re.search(r'"floors"\s*:\s*([0-9]+)', text)
            if _fxm:
                try: floors_max_val = int(_fxm.group(1))
                except: pass

    # Диапазон сдачи ("2021-2026"): страница → кэш
    delivery_range: str | None = None
    if text:
        # CIAN часто хранит earliest/latest deliveryYear
        _dry = re.search(
            r'"deliveryYearFrom"\s*:\s*([0-9]{4}).*?"deliveryYearTo"\s*:\s*([0-9]{4})',
            text, re.DOTALL
        )
        if _dry and _dry.group(1) != _dry.group(2):
            delivery_range = f"{_dry.group(1)}–{_dry.group(2)}"
        elif _dry:
            delivery_range = _dry.group(1)
        else:
            # Из общего диапазона дат
            _dry2 = re.search(
                r'"deliveryYears?"\s*:\s*\[([0-9]{4})[^\]]*,?[^\]]*([0-9]{4})?\]',
                text
            )
            if _dry2:
                y1, y2 = _dry2.group(1), _dry2.group(2)
                delivery_range = f"{y1}–{y2}" if y2 and y2 != y1 else y1

    # Объекты на территории ЖК: страница → кэш
    territory_amenities: list[str] = []
    if text:
        _territory_map = [
            (r'"school"\s*:\s*true',             'Школа'),
            (r'"kindergarten"\s*:\s*true',        'Детский сад'),
            (r'"childrenGround"\s*:\s*true',      'Детские площадки'),
            (r'"sportsGround"\s*:\s*true',        'Спортивные площадки'),
            (r'"restAreas"\s*:\s*true',           'Места для отдыха'),
            (r'"dogWalkingAreas"\s*:\s*true',     'Площадки для выгула собак'),
            (r'"supermarket"\s*:\s*true',         'Супермаркет'),
            (r'"fitnessCenter"\s*:\s*true',       'Фитнес-центр'),
            (r'"commercialAreas"\s*:\s*true',     'Коммерческие помещения'),
            (r'"swimmingPool"\s*:\s*true',        'Бассейн'),
            (r'"sauna"\s*:\s*true',               'Сауна'),
            (r'"spa"\s*:\s*true',                 'СПА'),
            (r'"coworking"\s*:\s*true',           'Коворкинг'),
            (r'"pharmacy"\s*:\s*true',            'Аптека'),
            (r'"polyclinic"\s*:\s*true',          'Поликлиника'),
            (r'"cafe"\s*:\s*true',                'Кафе/ресторан'),
            (r'"shoppingCenter"\s*:\s*true',      'Торговый центр'),
        ]
        for pat, label in _territory_map:
            if re.search(pat, text, re.I):
                territory_amenities.append(label)
        # Fallback: текстовые ключевые слова если JSON не нашёлся
        if not territory_amenities:
            _text_amenities = [
                (r'\bшкол[а-я]',                     'Школа'),
                (r'детск[а-я]+\s+сад',               'Детский сад'),
                (r'детск[а-я]+\s+площадк',           'Детские площадки'),
                (r'спортивн[а-я]+\s+площадк',        'Спортивные площадки'),
                (r'фитнес[- ]центр',                  'Фитнес-центр'),
                (r'супермаркет|продуктовый',          'Супермаркет'),
                (r'площадк[а-я]+\s+для\s+выгул',     'Площадки для выгула собак'),
            ]
            for pat, label in _text_amenities:
                if re.search(pat, text, re.I):
                    territory_amenities.append(label)

    # Парковка (список типов): страница → кэш
    parking_features: list[str] = []
    if text:
        _parking_map = [
            (r'"underground"\s*:\s*true|подземн[а-я]+\s+парк',     'Подземная'),
            (r'"guest"\s*:\s*true|гостевая\s+парк',                 'Гостевая'),
            (r'"multilevel"\s*:\s*true|многоуровн[а-я]+\s+парк',    'Многоуровневая'),
            (r'"openParking"\s*:\s*true|открытая\s+парк',           'Открытая'),
            (r'"garageParking"\s*:\s*true|гараж',                   'Гараж'),
            (r'"rooftopParking"\s*:\s*true',                        'Кровельная'),
        ]
        for pat, label in _parking_map:
            if re.search(pat, text, re.I):
                parking_features.append(label)

    # Безопасность (полный список): страница → кэш
    security_features: list[str] = []
    if text:
        _sec_map = [
            (r'"closedArea"\s*:\s*true|"fencedTerritory"\s*:\s*true|огороженный\s+периметр',
             'Огороженный периметр'),
            (r'"videoSurveillance"\s*:\s*true|видеонаблюдени',
             'Видеонаблюдение'),
            (r'"concierge"\s*:\s*true|консьерж',
             'Консьерж'),
            (r'"securityPost"\s*:\s*true|пост\s+охран',
             'Пост охраны'),
            (r'"roundTheClock"\s*:\s*true|"securityRoundTheClock"\s*:\s*true|круглосуточная\s+охрана',
             'Круглосуточная охрана'),
            (r'"fireAlarm"\s*:\s*true|противопожарная',
             'Противопожарная система'),
            (r'"intercom"\s*:\s*true|домофон',
             'Домофон'),
            (r'"accessControl"\s*:\s*true|контроль\s+доступа',
             'Контроль доступа'),
            (r'"cctv"\s*:\s*true',
             'Камеры наблюдения'),
            (r'"protectedArea"\s*:\s*true',
             'Охраняемая территория'),
        ]
        for pat, label in _sec_map:
            if re.search(pat, text, re.I):
                security_features.append(label)
        # Обновляем has_concierge из нового списка
        if security_features and has_concierge is None:
            has_concierge = 'Консьерж' in security_features

    # Отделка (finishing_type): из JSON CIAN decorations
    finishing_type_val: str | None = None
    if text:
        _dec_names: list[str] = []
        for _dm in re.finditer(
            r'"decorations?"\s*:\s*\[([^\]]{0,300})\]', text, re.I | re.DOTALL
        ):
            _dec_block = _dm.group(1)
            for _dn in re.finditer(r'"name"\s*:\s*"([^"]{2,60})"', _dec_block):
                v = _safe_decode(_dn.group(1))
                if v and v not in _dec_names:
                    _dec_names.append(v)
        if not _dec_names:
            # Ищем слова-маркеры
            _dec_kw = [
                (r'чистовая\s+отделка|с\s+отделкой',         'Чистовая'),
                (r'предчистовая|pre-?finish',                  'Предчистовая'),
                (r'без\s+отделки|без\s+ремонта',               'Без отделки'),
                (r'white\s*box|white-box',                     'White box'),
            ]
            for pat, label in _dec_kw:
                if re.search(pat, text, re.I):
                    _dec_names.append(label)
        if _dec_names:
            finishing_type_val = ', '.join(_dec_names)

    # Сдача корпусов (delivery_schedule): парсим поаккордно из JSON CIAN
    delivery_schedule: list[dict] = []
    if text:
        # CIAN stores per-house data in JSON: houseId, name, deliveryDate
        for _hm in re.finditer(
            r'"houseId"\s*:\s*(\d+)'
            r'(?:(?!"houseId").){0,2000}'
            r'"deliveryDate"\s*:\s*\{[^}]*"quarter"\s*:\s*([1-4])[^}]*"year"\s*:\s*(\d{4})',
            text, re.DOTALL
        ):
            _hid = _hm.group(1)
            _hq  = int(_hm.group(2))
            _hy  = int(_hm.group(3))
            # Пытаемся найти имя корпуса рядом
            _hname_m = re.search(
                rf'"houseId"\s*:\s*{_hid}[^{{}}]{{0,300}}"houseName"\s*:\s*"([^"]+)"',
                text, re.DOTALL
            )
            _hname = _safe_decode(_hname_m.group(1)) if _hname_m else f'Корпус {_hid}'
            entry = {'id': _hid, 'name': _hname, 'quarter': _hq, 'year': _hy}
            if entry not in delivery_schedule:
                delivery_schedule.append(entry)
        # Лимит: 100 корпусов
        delivery_schedule = delivery_schedule[:100]

    # Планировки ЖК (layout_images): ищем изображения планировок
    layout_imgs: list[str] = []
    if text:
        # CIAN хранит планировки квартир в JSON-данных страницы ЖК
        _ly_raw = re.findall(
            r'images\.cdn-cian\.ru/images/(?:[0-9]+/)*[a-zA-Z0-9_-]+-(?:plan|layout|floor)[a-zA-Z0-9_-]*-[0-9]+-[0-9]+\.jpg',
            text
        )
        if not _ly_raw:
            # Более широкий поиск планировок по ключевым словам контекста
            for _ly_m in re.finditer(
                r'"(?:planImage|layoutImage|floorPlan(?:Img|Image|Url)?|flatPlan)"\s*:\s*"(https?://[^"]+\.(?:jpg|png|webp))"',
                text, re.I
            ):
                layout_imgs.append(_ly_m.group(1))
                if len(layout_imgs) >= 10:
                    break
        else:
            seen_ly = set()
            for img in _ly_raw:
                full = 'https://' + re.sub(r'-[0-9]+\.jpg$', '-1.jpg', img)
                if full not in seen_ly:
                    seen_ly.add(full)
                    layout_imgs.append(full)
                if len(layout_imgs) >= 10:
                    break

    # Видео ЖК (videos): YouTube / RuTube ссылки со страницы CIAN
    videos_list: list[dict] = []
    if text:
        # YouTube: стандартные watch?v= и /embed/, shorts
        for _yt in re.finditer(
            r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})',
            text, re.I
        ):
            vid_id = _yt.group(1)
            url_yt = f'https://www.youtube.com/watch?v={vid_id}'
            if not any(v.get('url') == url_yt for v in videos_list):
                videos_list.append({'type': 'youtube', 'url': url_yt, 'title': ''})
        # RuTube: /video/<id>/ и /embed/<id>/
        for _rt in re.finditer(
            r'rutube\.ru/(?:video|embed)/([a-zA-Z0-9]{32})',
            text, re.I
        ):
            vid_id = _rt.group(1)
            url_rt = f'https://rutube.ru/video/{vid_id}/'
            if not any(v.get('url') == url_rt for v in videos_list):
                videos_list.append({'type': 'rutube', 'url': url_rt, 'title': ''})
        # VK video: vk.com/video-XXXXXXXX_YYYYY
        for _vk in re.finditer(
            r'vk\.com/video(-?\d+_\d+)',
            text, re.I
        ):
            url_vk = f'https://vk.com/video{_vk.group(1)}'
            if not any(v.get('url') == url_vk for v in videos_list):
                videos_list.append({'type': 'vk', 'url': url_vk, 'title': ''})
        videos_list = videos_list[:5]

    # Особенности / преимущества ЖК (advantages): текстовые блоки со страницы CIAN
    advantages_list: list[dict] = []
    if text:
        # CIAN хранит advantages/UTP в JSON: "advantages":[{"title":"...","description":"..."}]
        _adv_block = re.search(r'"advantages"\s*:\s*(\[[^\]]{0,4000}\])', text, re.DOTALL)
        if _adv_block:
            try:
                _adv_raw = json.loads(_adv_block.group(1))
                for _item in _adv_raw[:10]:
                    if isinstance(_item, dict):
                        title = _safe_decode(_item.get('title', '') or _item.get('name', ''))
                        desc  = _safe_decode(_item.get('description', '') or _item.get('text', ''))
                        if title:
                            advantages_list.append({'title': title, 'description': desc})
            except Exception:
                pass
        if not advantages_list:
            # Fallback: ищем "features":[...] или "benefits":[...]
            for _fb_key in ('features', 'benefits', 'highlights', 'uniquePropositions'):
                _fb = re.search(
                    rf'"{_fb_key}"\s*:\s*(\[[^\]{{}}]{{0,3000}}\])', text, re.DOTALL
                )
                if _fb:
                    try:
                        _fb_raw = json.loads(_fb.group(1))
                        for _item in _fb_raw[:10]:
                            if isinstance(_item, dict):
                                title = _safe_decode(_item.get('title','') or _item.get('name','') or _item.get('text',''))
                                if title:
                                    advantages_list.append({'title': title, 'description': ''})
                            elif isinstance(_item, str) and _item.strip():
                                advantages_list.append({'title': _safe_decode(_item), 'description': ''})
                        if advantages_list:
                            break
                    except Exception:
                        pass

    # Класс объекта: страница → кэш
    obj_cls: str | None = None
    if text:
        m2 = re.search(r'"newbuildingClass"\s*:\s*"([^"]{2,40})"', text)
        obj_cls = _safe_decode(m2.group(1)) if m2 else None
    if not obj_cls and cache_data.get('object_class'):
        obj_cls = cache_data['object_class']

    # Сроки сдачи: страница → кэш
    end_yr = end_q = None
    if text:
        for pat in [r'([1-4])\s*кв[^0-9]*([0-9]{4})',
                    r'"deliveryDate"\s*:\s*"([^"]+)"']:
            fm = re.search(pat, text)
            if fm:
                try:
                    end_yr = int(fm.group(2)); end_q = int(fm.group(1))
                except: pass
                break
    if not end_yr and cache_data.get('end_build_year'):
        end_yr = cache_data['end_build_year']
        end_q  = cache_data.get('end_build_quarter')

    # Логотип + варианты отделки
    logo   = _parse_logo_url(text) if text else None
    finish = _parse_finishing_variants(text) if text else None

    # Количество корпусов: из houseId на странице → fallback на distinct имена в properties
    buildings_count: int | None = None
    if text:
        # Шаг 1: считаем уникальные houseId — самый надёжный источник
        house_ids = list(dict.fromkeys(re.findall(r'"houseId"\s*:\s*(\d+)', text)))
        if house_ids:
            buildings_count = len(house_ids)
        else:
            # Шаг 2: поле buildingsCount в JSON страницы
            bc_m = re.search(r'"buildingsCount"\s*:\s*([0-9]+)', text)
            if bc_m:
                buildings_count = int(bc_m.group(1))
    if not buildings_count:
        # Шаг 3: COUNT DISTINCT из таблицы свойств
        cur.execute(
            "SELECT COUNT(DISTINCT complex_building_name) FROM properties "
            "WHERE complex_id=%s AND is_active=TRUE "
            "AND complex_building_name IS NOT NULL AND complex_building_name!=''",
            (rc_id,)
        )
        _db_cnt = (cur.fetchone() or [0])[0]
        if _db_cnt and _db_cnt > 0:
            buildings_count = _db_cnt

    # ── 4. Застройщик ─────────────────────────────────────────────────────────
    # Приоритет: страница → кэш (dev_name + builder_id)
    dev_info: dict = {}
    if text:
        dev_info = _extract_developer_info(text)
    if not dev_info.get('name') and cache_data.get('dev_name'):
        dev_info['name']    = cache_data['dev_name']
        dev_info['cian_id'] = cache_data.get('builder_id')
    if not dev_info.get('url') and cache_data.get('dev_profile_uri'):
        dev_info['url'] = cache_data['dev_profile_uri']

    _SKIP_DEVELOPER_NAMES = {'циан', 'cian', 'циан.ру', 'cian.ru', 'циан агентство', 'portal'}
    developer_id: int | None = None
    _dev_name_raw = (dev_info.get('name') or '').strip().lower()
    if _dev_name_raw in _SKIP_DEVELOPER_NAMES:
        dev_info = {}
    if dev_info.get('name') or dev_info.get('cian_id'):
        developer_id = get_or_create_developer(
            cur,
            name=dev_info.get('name', ''),
            dev_cache=dev_cache,
            cian_id=dev_info.get('cian_id'),
        )
        if developer_id and dev_info.get('url'):
            cur.execute(
                "UPDATE developers SET source_url=%s, updated_at=NOW() "
                "WHERE id=%s AND (source_url IS NULL OR source_url='')",
                (dev_info['url'], developer_id)
            )
        if developer_id and dev_info.get('logo'):
            cur.execute(
                "UPDATE developers SET logo_url=%s, updated_at=NOW() "
                "WHERE id=%s AND (logo_url IS NULL OR logo_url='')",
                (dev_info['logo'], developer_id)
            )

    # ── 5. UPDATE БД ─────────────────────────────────────────────────────────
    # Получаем текущие значения чтобы не затирать имеющиеся данные
    cur.execute("""
        SELECT main_image, latitude, longitude, address, developer_id, description
        FROM residential_complexes WHERE id=%s
    """, (rc_id,))
    cur_row = cur.fetchone() or (None,)*6
    cur_photo, cur_lat, cur_lon, cur_addr, cur_dev_id, cur_desc = cur_row

    fields, values = [], []

    def add(col, val):
        if val is not None:
            fields.append(col); values.append(val)

    # Фото: записываем всегда если нашли (качество данных важнее)
    if photos:
        add('main_image', photos[0][:499])
        add('gallery_images', json.dumps(photos[:20], ensure_ascii=False))
    # Координаты: только если ещё нет (или force)
    if lat and (force or not cur_lat):   add('latitude',  lat)
    if lon and (force or not cur_lon):   add('longitude', lon)
    # Описание: перезаписываем только если новое длиннее
    if desc and (force or not cur_desc or len(desc) > len(cur_desc or '')):
        add('description', desc[:4999])
    # Адрес: только если ещё нет
    if addr and (force or not cur_addr): add('address', addr[:299])
    # Структурированные компоненты адреса из geo-иерархии CIAN
    # (всегда перезаписываем если нашли — это более точные данные из самого CIAN)
    if geo_components.get('addr_region'):
        add('addr_region', geo_components['addr_region'][:99])
    if geo_components.get('addr_city'):
        add('addr_city', geo_components['addr_city'][:99])
    if geo_components.get('address_city_district'):
        add('address_city_district', geo_components['address_city_district'][:149])
    if geo_components.get('address_quarter'):
        add('address_quarter', geo_components['address_quarter'][:149])
    if geo_components.get('addr_street'):
        add('addr_street', geo_components['addr_street'][:149])
    if geo_components.get('addr_house'):
        add('addr_house', geo_components['addr_house'][:49])
    if material: add('wall_material', material[:99])
    if obj_cls:  add('object_class_display_name', obj_cls[:49])
    if end_yr:   add('end_build_year', end_yr)
    if end_q:    add('end_build_quarter', end_q)
    if logo:     add('logo_url', logo[:499])
    if finish:   add('finishing_variants', finish[:1999])
    if buildings_count: add('buildings_count', buildings_count)
    if ceiling_h: add('ceiling_height', ceiling_h[:49])
    if parking:   add('parking_type', parking[:99])
    if security:  add('security_type', security[:199])
    if has_concierge is not None: add('has_concierge', has_concierge)
    if lifts is not None: add('lifts_count', lifts)
    # ── Новые расширенные характеристики ─────────────────────────────────────
    if lifts_range:     add('lifts_range', lifts_range[:49])
    if floors_min_val:  add('floors_min', floors_min_val)
    if floors_max_val:  add('floors_max', floors_max_val)
    if delivery_range:  add('delivery_range', delivery_range[:49])
    if finishing_type_val: add('finishing_type', finishing_type_val[:99])
    if territory_amenities:
        add('territory_amenities', json.dumps(territory_amenities, ensure_ascii=False))
    if parking_features:
        add('parking_features', json.dumps(parking_features, ensure_ascii=False))
    if security_features:
        add('security_features', json.dumps(security_features, ensure_ascii=False))
    if delivery_schedule:
        add('delivery_schedule', json.dumps(delivery_schedule, ensure_ascii=False))
    if layout_imgs:
        add('layout_images', json.dumps(layout_imgs[:10], ensure_ascii=False))
    # Видео: добавляем новые, не стираем уже имеющиеся
    if videos_list:
        try:
            cur.execute("SELECT videos FROM residential_complexes WHERE id=%s", (rc_id,))
            _ex_row = cur.fetchone()
            _ex_vids = json.loads(_ex_row[0]) if (_ex_row and _ex_row[0]) else []
            _ex_urls = {v.get('url') for v in _ex_vids if isinstance(v, dict)}
            _new_vids = [v for v in videos_list if v.get('url') not in _ex_urls]
            if _new_vids:
                add('videos', json.dumps(_ex_vids + _new_vids, ensure_ascii=False))
        except Exception:
            add('videos', json.dumps(videos_list, ensure_ascii=False))
    # Особенности / преимущества: записываем если нашли
    if advantages_list:
        add('advantages', json.dumps(advantages_list, ensure_ascii=False))
    # Застройщик: не перезаписываем если уже привязан (кроме force)
    if developer_id and (force or not cur_dev_id):
        add('developer_id', developer_id)
    if cian_id:  add('complex_id', cian_id)
    add('updated_at', datetime.now())

    if fields:
        sql = (
            f"UPDATE residential_complexes "
            f"SET {', '.join(f + '=%s' for f in fields)} "
            f"WHERE id=%s"
        )
        cur.execute(sql, values + [rc_id])
        conn.commit()

    fetched = text is not None
    result.update({
        'status':             'ok',
        'fetched':            fetched,
        'from_cache':         bool(cache_data),
        'photos':             len(photos),
        'lat':                lat,
        'lon':                lon,
        'desc_len':           len(desc) if desc else 0,
        'addr':               addr,
        'district':           geo_components.get('address_city_district'),
        'quarter':            geo_components.get('address_quarter'),
        'developer':          dev_info.get('name'),
        'developer_id':       developer_id,
        'fields':             len(fields),
        # Новые расширенные характеристики
        'lifts_range':        lifts_range,
        'floors_min':         floors_min_val,
        'floors_max':         floors_max_val,
        'delivery_range':     delivery_range,
        'finishing_type':     finishing_type_val,
        'territory_count':    len(territory_amenities),
        'parking_count':      len(parking_features),
        'security_count':     len(security_features),
        'buildings_sched':    len(delivery_schedule),
        'videos_found':       len(videos_list),
        'advantages_found':   len(advantages_list),
    })
    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Bulk JK enrichment from CIAN')
    ap.add_argument('--city',  type=int, default=1)
    ap.add_argument('--limit', type=int, default=0, help='0 = все')
    ap.add_argument('--id',    type=str, default='', help='rc IDs через запятую')
    ap.add_argument('--force', action='store_true',
                    help='обновить даже ЖК у которых уже есть данные')
    args = ap.parse_args()

    # Загружаем глобальный кэш Phase-1 для нужного города
    global _JK_CACHE
    _JK_CACHE = _load_jk_cache(args.city)

    # Имя города из конфига + обновляем координатные bounds для этого города
    city_cfg  = _CITY_CONFIG.get(str(args.city), {})
    city_name = city_cfg.get('name', f'city_id={args.city}')
    global _LAT_MIN, _LAT_MAX, _LON_MIN, _LON_MAX
    _LAT_MIN, _LAT_MAX, _LON_MIN, _LON_MAX = _get_coord_bounds(args.city)
    print(f'🏙️  Город: {city_name} | cache JKs: {len(_JK_CACHE)}')

    conn = psycopg2.connect(
        host=os.environ.get('PGHOST'),
        database=os.environ.get('PGDATABASE'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', ''),
    )
    cur = conn.cursor()
    dev_cache: dict = {}

    # ── Целевой список ЖК ─────────────────────────────────────────────────────
    if args.id:
        ids = [int(x) for x in args.id.split(',')]
        # city_id фильтр включён чтобы не обрабатывать ЖК чужого города.
        # Если нужно обработать ЖК вне текущего города — используй --force без --id,
        # или убедись что ЖК действительно принадлежит нужному городу.
        cur.execute("""
            SELECT rc.id, rc.name, rc.slug, rc.complex_id
            FROM residential_complexes rc
            WHERE rc.id = ANY(%s) AND rc.city_id = %s
            ORDER BY rc.name
        """, (ids, args.city))
        # Предупреждение если какие-то ID не попали в выборку (чужой город)
        fetched_ids = {row[0] for row in cur.fetchall()}
        missed = set(ids) - fetched_ids
        if missed:
            print(f'⚠️  ЖК {sorted(missed)} не принадлежат city_id={args.city} '
                  f'— пропущены. Запустите без --city или проверьте city_id ЖК.')
        cur.execute("""
            SELECT rc.id, rc.name, rc.slug, rc.complex_id
            FROM residential_complexes rc
            WHERE rc.id = ANY(%s) AND rc.city_id = %s
            ORDER BY rc.name
        """, (ids, args.city))
    elif args.force:
        q = """
            SELECT rc.id, rc.name, rc.slug, rc.complex_id
            FROM residential_complexes rc
            WHERE rc.city_id = %s AND rc.is_active = TRUE AND rc.complex_id IS NOT NULL
            ORDER BY rc.name
        """
        cur.execute(q + (f" LIMIT {args.limit}" if args.limit else ''), (args.city,))
    else:
        q = """
            SELECT rc.id, rc.name, rc.slug, rc.complex_id
            FROM residential_complexes rc
            WHERE rc.city_id = %s
              AND rc.is_active = TRUE
              AND rc.complex_id IS NOT NULL
              AND (rc.main_image IS NULL
                   OR rc.latitude        IS NULL
                   OR rc.address         IS NULL
                   OR rc.developer_id    IS NULL
                   OR rc.description     IS NULL
                   OR rc.delivery_range  IS NULL
                   OR rc.layout_images   IS NULL
                   OR rc.layout_images   = '[]'
                   OR rc.territory_amenities IS NULL
                   OR rc.territory_amenities = '[]'
                   OR rc.parking_features    IS NULL
                   OR rc.parking_features    = '[]'
                   OR rc.security_features   IS NULL
                   OR rc.security_features   = '[]')
            ORDER BY rc.main_image NULLS FIRST, rc.name
        """
        cur.execute(q + (f" LIMIT {args.limit}" if args.limit else ''), (args.city,))

    rows = cur.fetchall()
    total = len(rows)
    print(f'\n🔍 ЖК для обработки: {total}\n{"═"*60}')
    if not total:
        print('Нет ЖК с недостающими данными — всё уже заполнено!')
        return

    ok = fail = skip = 0
    t0 = time.time()

    for i, (rc_id, rc_name, slug, cian_id) in enumerate(rows, 1):
        elapsed = time.time() - t0
        eta_s   = (elapsed / i) * (total - i) if i > 1 else 0
        print(f'\n[{i}/{total}] {rc_name} (id={rc_id}, cian={cian_id}) '
              f'| ETA {eta_s/60:.0f}м{eta_s%60:.0f}с')

        try:
            res = process_jk(cur, conn, rc_id, rc_name, slug or '',
                             cian_id, dev_cache, force=args.force,
                             expected_city_id=args.city)
        except Exception as e:
            import traceback; traceback.print_exc()
            conn.rollback()
            res = {'status': 'error', 'error': str(e)}

        if res['status'] == 'ok':
            ok += 1
            icon = '✅' if res['fetched'] else '📦'
            lat_str  = f'{res["lat"]:.4f}' if res["lat"] else '—'
            addr_str = str(res["addr"])[:40] if res["addr"] else '—'
            dist_str = res.get("district") or '—'
            qrt_str  = res.get("quarter")  or '—'
            print(f'  {icon} фото={res["photos"]}  lat={lat_str}  '
                  f'addr={addr_str}\n'
                  f'      округ={dist_str}  мкр={qrt_str}  '
                  f'dev={res["developer"] or "—"}  '
                  f'desc={res["desc_len"]}c  ({res["fields"]} полей)')
        elif res['status'] in ('fetch_failed', 'error'):
            fail += 1
            print(f'  ❌ {res.get("error", "fetch failed")}')
        else:
            skip += 1

        time.sleep(REQ_DELAY)

    conn.close()
    elapsed_total = time.time() - t0
    print(f'\n{"═"*60}')
    print(f'Итого: ✅{ok}  ❌{fail}  ⏭️{skip}  из {total} ЖК  '
          f'за {elapsed_total/60:.1f} мин')


if __name__ == '__main__':
    main()
