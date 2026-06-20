"""
Полный пайплайн: Застройщик → ЖК → Литер → Квартиры в литере.
Стратегия:
  1. Многозапросный поиск (6 групп по типу комнат × до 54 страниц)
     → собираем ВСЕ ЖК и ВСЕ квартиры по городу
  2. Скрапинг страниц каждого ЖК → CDN-фото, описание, литеры (корпуса)
  3. Скрапинг страниц застройщиков
  4. Запись в БД:
       residential_complexes — upsert ЖК
       buildings             — upsert литеры/корпуса
       properties            — upsert квартиры (по external_id = cianId)
       developers            — update данные застройщиков
"""

import html as html_lib
import os, re, sys, json, time, atexit, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.property_utils import sanitize_property_title
import warnings
import ssl
import requests
import urllib3
from requests.adapters import HTTPAdapter
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class _TLSAdapter(HTTPAdapter):
    """Адаптер с ослабленными SSL-настройками для работы через HTTP-прокси.
    Подавляет UNEXPECTED_EOF_WHILE_READING (OpenSSL 3.x + Python 3.11+)."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, 'OP_IGNORE_UNEXPECTED_EOF'):
            ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        kwargs['ssl_context'] = ctx
        super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, 'OP_IGNORE_UNEXPECTED_EOF'):
            ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        proxy_kwargs['ssl_context'] = ctx
        return super().proxy_manager_for(proxy, **proxy_kwargs)
import psycopg2
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CITY_ID        = int(os.environ.get('ENRICH_CITY_ID',     1))

# Загружаем конфиг городов — приоритет у env vars, потом city_config.json
_CITY_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'city_config.json')
_city_cfg: dict = {}
try:
    with open(_CITY_CFG_FILE) as _cf:
        _all_city_cfgs = json.load(_cf)
        _city_cfg = _all_city_cfgs.get(str(CITY_ID), {})
except Exception:
    _all_city_cfgs = {}

# Таблица: поддомен ЦИАН → db_city_id.
# Пример: 'maykop' → 8, 'krasnodar' → 1, 'sochi' → 2
# Строится автоматически из city_config.json — добавлять новые города достаточно там.
_CIAN_DOMAIN_TO_CITY_ID: dict = {}
for _cid, _cfg in _all_city_cfgs.items():
    _subdomain = (_cfg.get('name_en') or _cfg.get('slug', '')).lower().strip()
    if _subdomain:
        _CIAN_DOMAIN_TO_CITY_ID[_subdomain] = _cfg.get('db_city_id', int(_cid))


def _city_id_from_url(url: str, default: int = CITY_ID) -> int:
    """Определяет city_id по домену ЦИАН из source_url.

    Пример:
        'https://maykop.cian.ru/sale/flat/123/'  → 8
        'https://krasnodar.cian.ru/sale/flat/99/' → 1
        'https://sochi.cian.ru/...'               → 2
        None или нераспознанный домен             → default (CITY_ID текущего запуска)

    Это защищает от ситуации, когда обогатитель запускается для города 1 (Краснодар),
    но в ЖК попадают объявления с maykop.cian.ru — и они ошибочно получают city_id=1.
    """
    if not url:
        return default
    m = re.match(r'https?://([^.]+)\.cian\.ru', url)
    if not m:
        return default
    subdomain = m.group(1).lower()
    return _CIAN_DOMAIN_TO_CITY_ID.get(subdomain, default)


def ensure_city_in_db():
    """
    Убеждаемся, что город из city_config.json существует в таблице cities.
    Если нет — создаём регион (если нужно) и город автоматически.
    Возвращает db_city_id (int) — реальный id записи в cities.
    """
    import re as _re
    cfg = _all_city_cfgs.get(str(CITY_ID), {})
    db_city_id = cfg.get('db_city_id', CITY_ID)
    city_name  = cfg.get('name', f'Город {CITY_ID}')
    city_slug  = cfg.get('slug') or cfg.get('name_en', f'city-{CITY_ID}')
    lat        = cfg.get('lat') or None
    lon        = cfg.get('lon') or None
    region_name = cfg.get('region_name', 'Россия')
    region_slug = cfg.get('region_slug', 'russia')

    db_url = os.environ.get('DATABASE_URL', '')
    if not db_url:
        print('[ensure_city] DATABASE_URL не задан — пропускаем проверку')
        return db_city_id

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        cur = conn.cursor()

        # Проверяем: город уже есть?
        cur.execute("SELECT id FROM cities WHERE id = %s OR slug = %s LIMIT 1",
                    (db_city_id, city_slug))
        row = cur.fetchone()
        if row:
            actual_id = row[0]
            conn.close()
            return actual_id

        # Находим или создаём регион
        cur.execute("SELECT id FROM regions WHERE name = %s LIMIT 1", (region_name,))
        rrow = cur.fetchone()
        if rrow:
            region_id = rrow[0]
        else:
            print(f'[ensure_city] Создаём регион «{region_name}»')
            cur.execute("""
                INSERT INTO regions (name, slug, is_active, is_default, created_at, updated_at)
                VALUES (%s, %s, true, false, NOW(), NOW())
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """, (region_name, region_slug))
            region_id = cur.fetchone()[0]

        # Создаём город с явным id (чтобы совпадал с ключом в city_config.json)
        print(f'[ensure_city] Создаём город «{city_name}» (id={db_city_id}) в БД')
        cur.execute("""
            INSERT INTO cities (id, name, slug, region_id, is_active, is_default,
                                latitude, longitude, zoom_level, created_at, updated_at)
            VALUES (%s, %s, %s, %s, true, false,
                    %s, %s, 11, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
        """, (db_city_id, city_name, city_slug, region_id, lat, lon))

        # Обновляем sequence чтобы автоинкремент не конфликтовал
        cur.execute("SELECT setval('cities_id_seq', GREATEST((SELECT MAX(id) FROM cities), 1))")

        conn.commit()
        conn.close()
        print(f'[ensure_city] Город «{city_name}» создан успешно (id={db_city_id})')
        return db_city_id

    except Exception as e:
        print(f'[ensure_city] ОШИБКА: {e}')
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return db_city_id


# Запускаем при старте скрипта
ensure_city_in_db()

CIAN_REGION_ID = int(os.environ.get('ENRICH_REGION_ID',
                     _city_cfg.get('cian_region_id', 4820)))
TOTAL_PAGES    = int(os.environ.get('ENRICH_TOTAL_PAGES',
                     _city_cfg.get('total_pages', 54)))

# ── Bbox-ограничение города (используется для отклонения ЖК не из этого города) ──
CITY_LAT_MIN = float(os.environ.get('ENRICH_LAT_MIN', _city_cfg.get('lat_min', 40.0)))
CITY_LAT_MAX = float(os.environ.get('ENRICH_LAT_MAX', _city_cfg.get('lat_max', 80.0)))
CITY_LON_MIN = float(os.environ.get('ENRICH_LON_MIN', _city_cfg.get('lon_min', 19.0)))
CITY_LON_MAX = float(os.environ.get('ENRICH_LON_MAX', _city_cfg.get('lon_max', 190.0)))
_BBOX_IS_TIGHT = (CITY_LAT_MAX - CITY_LAT_MIN) < 5.0 and (CITY_LON_MAX - CITY_LON_MIN) < 5.0

def _city_bbox_ok(lat, lon):
    """True если координаты попадают в bbox города. None/0 → не отклонять."""
    if not lat or not lon:
        return True
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return True
    if abs(lat - 44.609139) < 0.001 and abs(lon - 37.6213) < 0.001:
        return False  # CIAN-заглушка «координаты неизвестны»
    if _BBOX_IS_TIGHT:
        return CITY_LAT_MIN <= lat <= CITY_LAT_MAX and CITY_LON_MIN <= lon <= CITY_LON_MAX
    return True  # широкий bbox → не фильтруем

CREATE_NEW_JK  = os.environ.get('ENRICH_CREATE_NEW', '1') != '0'
REQUEST_DELAY  = float(os.environ.get('ENRICH_DELAY', 0.3))
ANTICAPTCHA_KEY  = os.environ.get('ENRICH_ANTICAPTCHA', '').strip()
# Fallback: читаем ключ из файла настроек если env var не задан
_settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.enrich_settings.json')
try:
    with open(_settings_file) as _sf:
        _file_settings = json.load(_sf)
except Exception:
    _file_settings = {}

_USE_VPN_ENV = os.environ.get('ENRICH_USE_VPN', '')
if _USE_VPN_ENV:
    USE_VPN = _USE_VPN_ENV == '1'
else:
    USE_VPN = bool(_file_settings.get('use_vpn', False))

_PROXY_ENV = os.environ.get('ENRICH_PROXY', '').strip()
PROXY_URL = _PROXY_ENV if _PROXY_ENV else _file_settings.get('proxy_url', '').strip()

# Proxy pool — round-robin across multiple proxies
_PROXY_POOL = _file_settings.get('proxy_pool', [])
if _PROXY_POOL and not PROXY_URL:
    PROXY_URL = _PROXY_POOL[0]  # start with first
_proxy_pool_idx = 0
_proxy_pool_lock = None
try:
    import threading as _threading
    _proxy_pool_lock = _threading.Lock()
except Exception:
    pass

def _get_next_proxy():
    """Round-robin through proxy pool. Falls back to PROXY_URL if pool is empty."""
    global _proxy_pool_idx
    if not _PROXY_POOL:
        return PROXY_URL
    if _proxy_pool_lock:
        with _proxy_pool_lock:
            idx = _proxy_pool_idx % len(_PROXY_POOL)
            _proxy_pool_idx += 1
    else:
        idx = _proxy_pool_idx % len(_PROXY_POOL)
        _proxy_pool_idx += 1
    return _PROXY_POOL[idx]
if not ANTICAPTCHA_KEY:
    ANTICAPTCHA_KEY = _file_settings.get('anticaptcha_key', '').strip()
# 'full' — полный прогон (все фазы), 'prices' — только цены (Phase 1 + 4c + 4d, ~5 мин)
ENRICH_MODE    = os.environ.get('ENRICH_MODE', 'full')

# ── VPN (OpenVPN) ──────────────────────────────────────────────────────────────
_VPN_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vpn_config.ovpn')
_vpn_proc   = None

def _find_bin(name):
    """Ищет бинарник: сначала в PATH, затем в nix store."""
    import shutil, glob
    path = shutil.which(name)
    if path:
        return path
    # Nix-installed binaries не всегда в PATH при запуске workflow
    nix_matches = sorted(glob.glob(f'/nix/store/*{name}*/bin/{name}'))
    return nix_matches[-1] if nix_matches else None

def vpn_connect():
    """Запускает OpenVPN, ждёт появления tun0 (до 25 сек)."""
    global _vpn_proc
    if not USE_VPN:
        return
    if not os.path.exists(_VPN_CONFIG):
        print(f'⚠️  VPN: конфиг не найден ({_VPN_CONFIG}) — продолжаем без VPN')
        return
    ovpn_bin = _find_bin('openvpn')
    if not ovpn_bin:
        print('⚠️  VPN: openvpn не найден — пропускаем')
        return
    ip_bin = _find_bin('ip')
    try:
        _vpn_proc = subprocess.Popen(
            [ovpn_bin, '--config', _VPN_CONFIG,
             '--log', '/tmp/openvpn_enrich.log', '--verb', '1'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f'🔐 VPN: подключение (PID {_vpn_proc.pid})...')
        for i in range(25):
            time.sleep(1)
            if ip_bin:
                r = subprocess.run([ip_bin, 'link', 'show', 'tun0'],
                                   capture_output=True, text=True)
                if r.returncode == 0:
                    print(f'✅ VPN подключён (tun0 появился за {i+1}с)')
                    return
            else:
                # Проверяем по /proc/net/dev если ip не доступен
                try:
                    with open('/proc/net/dev') as f:
                        if 'tun0' in f.read():
                            print(f'✅ VPN подключён (tun0 в /proc/net/dev за {i+1}с)')
                            return
                except Exception:
                    pass
        print('⚠️  VPN: tun0 не появился за 25с — продолжаем без VPN')
    except Exception as e:
        print(f'⚠️  VPN connect error: {e}')

def vpn_disconnect():
    """Завершает процесс OpenVPN."""
    global _vpn_proc
    if _vpn_proc and _vpn_proc.poll() is None:
        try:
            _vpn_proc.terminate()
            _vpn_proc.wait(timeout=5)
            print('🔐 VPN отключён')
        except Exception as e:
            print(f'⚠️  VPN disconnect: {e}')
        _vpn_proc = None

atexit.register(vpn_disconnect)

# CIAN builder_id‑ы агрегаторов/агентств — НЕ застройщики, не привязываем к ЖК
# Все аккаунты «Магазин новостроек» и похожих агрегаторов (выявлены автоматически из данных CIAN)
AGGREGATOR_BUILDER_IDS = {
    3583,   # Магазин новостроек
    4138,   # Магазин новостроек
    4724,   # Магазин новостроек
    6490,   # Магазин новостроек  ← Зеленодар
    6860,   # Магазин новостроек
    8472,   # Магазин новостроек
    8476,   # Магазин новостроек
    8503,   # Магазин новостроек
    8529,   # Магазин новостроек  ← Левада
    8636,   # Магазин новостроек
    8886,   # Магазин новостроек
    9207,   # Магазин новостроек
    9228,   # Магазин новостроек
    9236,   # Магазин новостроек
    9260,   # Магазин новостроек
    9267,   # Магазин новостроек
    9280,   # Магазин новостроек
    9793,   # Магазин новостроек
    9893,   # Магазин новостроек
    10020,  # Магазин новостроек  ← Красная площадь
    14147,  # Магазин новостроек
    14675,  # Магазин новостроек
    15841,  # Магазин новостроек
    16344,  # Магазин новостроек
    17431,  # Магазин новостроек
    17902,  # Магазин новостроек
    18871,  # Магазин новостроек  ← К24
    19020,  # Магазин новостроек
    19495,  # Магазин новостроек
    19858,  # Магазин новостроек
}

# Room-type groups: union даёт максимальный охват ЖК
# CIAN ограничивает ~420 результатов на запрос → разбивка по комнатам
ROOM_FILTER_GROUPS = [
    (None,    'все'),
    ([0],     'студии'),
    ([1],     '1к'),
    ([2],     '2к'),
    ([3],     '3к'),
    ([4,5,6], '4к+'),
]

# Пул актуальных User-Agent'ов — ротируем при каждом пересоздании сессии
import random as _random
_UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0',
]


def _normalize_proxy_url(url: str) -> str:
    """Добавляет схему http:// к прокси URL если она отсутствует.
    Пример: 'user:pass@host:port' → 'http://user:pass@host:port'
    """
    if not url:
        return url
    if '://' not in url:
        return 'http://' + url
    return url


def _make_session() -> requests.Session:
    """Создаёт новую HTTP-сессию с заголовками и прокси.
    Вызывается при старте и при каждой смене IP прокси.
    Намеренно НЕ делает warmup-запрос — это исключает блокирующий сетевой вызов
    на уровне модуля и при каждой ротации сессии."""
    ua = _random.choice(_UA_POOL)
    city_slug = _city_cfg.get('slug', 'krasnodar')
    s = requests.Session()
    s.headers.update({
        'User-Agent': ua,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Content-Type': 'application/json',
        'Origin': f'https://{city_slug}.cian.ru',
        'Referer': f'https://{city_slug}.cian.ru/novostrojki/',
        'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
    })
    adapter = _TLSAdapter()
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    proxy = _normalize_proxy_url(PROXY_URL)
    if proxy:
        s.proxies = {'http': proxy, 'https': proxy}
        s.verify = False
    return s

SESSION = _make_session()
# Время последнего пересоздания сессии (для ротации IP)
_SESSION_CREATED_AT = time.time()
# Интервал ротации в секундах (читаем из настроек, по умолчанию 4.5 мин)
_PROXY_ROTATE_INTERVAL = float(_file_settings.get('proxy_rotate_seconds', 270))
_CHANGE_IP_URL = _file_settings.get('change_ip_url', '').strip()

def _call_change_ip() -> bool:
    """Запрашивает смену IP у провайдера прокси (iparchitect API).
    Возвращает True при успехе."""
    if not _CHANGE_IP_URL:
        return False
    try:
        import urllib.request as _urlreq
        with _urlreq.urlopen(_CHANGE_IP_URL, timeout=10) as r:
            body = r.read().decode('utf-8', errors='ignore').strip()
            print(f'  🌐 Смена IP прокси: {body[:80]}')
            time.sleep(3)  # ждём применения нового IP
            return True
    except Exception as e:
        print(f'  ⚠️  change_ip API ошибка: {e}')
        return False

def rotate_session_if_needed(force: bool = False) -> bool:
    """Пересоздаёт SESSION если прошёл интервал ротации прокси.
    При наличии change_ip_url сначала запрашивает смену IP у провайдера.
    Возвращает True если сессия была пересоздана."""
    global SESSION, _SESSION_CREATED_AT
    elapsed = time.time() - _SESSION_CREATED_AT
    if force or elapsed >= _PROXY_ROTATE_INTERVAL:
        # Запросить новый IP у провайдера перед пересозданием сессии
        _call_change_ip()
        try:
            SESSION.close()
        except Exception:
            pass
        SESSION = _make_session()
        _SESSION_CREATED_AT = time.time()
        if PROXY_URL:
            print(f'  🔄 Сессия пересоздана (прошло {elapsed:.0f}с) — новый IP прокси')
        return True
    return False

if PROXY_URL:
    print(f'🔀 Прокси: {PROXY_URL} (ротация каждые {_PROXY_ROTATE_INTERVAL:.0f}с)')
if _CHANGE_IP_URL:
    print(f'🌐 Change-IP API: настроен (автоматическая смена IP при ротации)')
if ANTICAPTCHA_KEY:
    print(f'🔐 Anti-Captcha: ключ установлен ({ANTICAPTCHA_KEY[:6]}...)')


def _is_captcha_response(resp) -> bool:
    """Определяет, является ли ответ капча-блокировкой (Cloudflare / CIAN)."""
    if resp.status_code in (403, 429):
        return True
    ct = resp.headers.get('content-type', '')
    if 'text/html' in ct:
        body = resp.text[:2000].lower()
        markers = ('just a moment', 'cf-browser-verification', 'cloudflare',
                   'captcha', '_cf_chl', 'challenge-form', 'attention required',
                   'showcaptcha')
        return any(m in body for m in markers)
    return False


_CIAN_SITEKEY_CACHE: str | None = None


def _extract_cian_sitekey(captcha_page_url: str = 'https://www.cian.ru/cian-captcha/') -> str | None:
    """Динамически вытаскивает reCAPTCHA sitekey со страницы капчи CIAN.
    Кэширует результат в модуле. Возвращает None если не нашёл."""
    global _CIAN_SITEKEY_CACHE
    if _CIAN_SITEKEY_CACHE:
        return _CIAN_SITEKEY_CACHE
    try:
        resp = SESSION.get(captcha_page_url, timeout=12, allow_redirects=True)
        html = resp.text
        # ищем data-sitekey="..." или k=... в URL grecaptcha
        m = re.search(r'data-sitekey=["\']([^"\']{20,})["\']', html)
        if not m:
            m = re.search(r'[?&]k=([A-Za-z0-9_-]{20,})', html)
        if m:
            key = m.group(1)
            print(f'  🔑 Найден sitekey CIAN: {key[:16]}...')
            _CIAN_SITEKEY_CACHE = key
            return key
    except Exception as e:
        print(f'  ⚠️  sitekey extract error: {e}')
    return None


def _solve_anticaptcha(page_url: str, sitekey: str = None) -> str | None:
    """Решает reCAPTCHA v2 через anti-captcha.com (нативный API).
    Sitekey берём динамически со страницы CIAN, не хардкодим.
    Возвращает g-recaptcha-response token или None при ошибке."""
    if not ANTICAPTCHA_KEY:
        return None
    try:
        import urllib.request

        # Пробуем вытащить sitekey динамически; fallback — известные ключи CIAN
        _sitekey = sitekey or _extract_cian_sitekey() or ''
        _api = ''

        # Шаг 1 — создать задачу
        create_body = json.dumps({
            'clientKey': ANTICAPTCHA_KEY,
            'task': {
                'type': 'RecaptchaV2TaskProxyless',
                'websiteURL': page_url,
                'websiteKey': _sitekey,
            },
        }).encode()
        req = urllib.request.Request(
            f'{_api}/createTask',
            data=create_body,
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        if data.get('errorId', 1) != 0:
            print(f'  ⚠️  anti-captcha createTask error: {data.get("errorDescription")}')
            return None
        task_id = data['taskId']
        print(f'  🔐 anti-captcha: задача #{task_id} создана, ждём решения...')

        # Шаг 2 — опрашивать результат (до 120 сек)
        result_body = json.dumps({'clientKey': ANTICAPTCHA_KEY, 'taskId': task_id}).encode()
        for attempt in range(24):
            time.sleep(5)
            req2 = urllib.request.Request(
                f'{_api}/getTaskResult',
                data=result_body,
                headers={'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req2, timeout=20) as r:
                res = json.loads(r.read())
            if res.get('errorId', 0) != 0:
                print(f'  ⚠️  anti-captcha error: {res.get("errorDescription")}')
                return None
            if res.get('status') == 'ready':
                token = res.get('solution', {}).get('gRecaptchaResponse')
                if token:
                    print(f'  ✅ anti-captcha: капча решена (попытка {attempt+1})')
                    return token
        print('  ⚠️  anti-captcha timeout (120s)')
        return None
    except Exception as e:
        print(f'  ⚠️  anti-captcha exception: {e}')
        return None


def _anticaptcha_backoff(attempt: int, url: str = '') -> None:
    """Умное ожидание после блокировки: с anti-captcha — решаем, без — просто ждём."""
    if ANTICAPTCHA_KEY and url:
        token = _solve_anticaptcha(url)
        if token:
            SESSION.cookies.set('g-recaptcha-response', token)
            return
    wait = min(60, 15 * (attempt + 1))
    print(f'  ⏳ Блокировка (попытка {attempt+1}): ждём {wait}с...')
    time.sleep(wait)


MATERIAL_MAP = {
    'monolithBrick': 'Монолит-кирпич',
    'monolith':      'Монолит',
    'brick':         'Кирпич',
    'panel':         'Панель',
    'block':         'Блок',
    'wood':          'Дерево',
    'stalin':        'Сталинка',
    'old':           'Старый фонд',
}
CLASS_MAP = {
    'econom':   'Эконом',
    'comfort':  'Комфорт',
    'comfort+': 'Комфорт+',
    'business': 'Бизнес',
    'elite':    'Элит',
    'standart': 'Стандарт',
    'premium':  'Премиум',
}
QUARTER_MAP = {
    'first': 1, 'second': 2, 'third': 3, 'fourth': 4,
}

RENOVATION_MAP = {
    'without':    'Без отделки',
    'rough':      'Черновая',
    'fine':       'Чистовая',
    'turnkey':    'Под ключ',
    'cosmetic':   'Косметический',
    'euro':       'Евроремонт',
    'finishing':  'Предчистовая',
    'prefinish':  'Предчистовая',
    'clean':      'Чистовая',
}


def _safe_decode(raw: str) -> str:
    try:
        decoded = json.loads('"' + raw.replace('"', '\\"') + '"')
    except Exception:
        try:
            decoded = raw.encode('latin-1').decode('utf-8')
        except Exception:
            decoded = raw
    decoded = re.sub(r'<[^>]+>', ' ', decoded)
    decoded = re.sub(r'\s+', ' ', decoded).strip()
    return decoded


def _strip_html(raw: str) -> str:
    text = re.sub(r'<[^>]+>', '', raw)
    text = html_lib.unescape(text)
    text = text.replace('\u00a0', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def _build_address(geo: dict) -> str | None:
    """Строит адресную строку из geo.address массива CIAN.
    Включает все уровни иерархии: регион, город, округ, микрорайон, улица, дом.
    """
    if not geo:
        return None
    parts = geo.get('address') or []
    # Полная иерархия CIAN: region → city → okrug → district/raion → street → house
    wanted = {'region', 'city', 'okrug', 'district', 'raion', 'quarter', 'street', 'house'}
    result = []
    for part in parts:
        if part.get('type') in wanted:
            name = part.get('fullName') or part.get('name') or ''
            if name and name not in result:
                result.append(name)
    return ', '.join(result) if result else None


def _extract_geo_hierarchy(geo: dict) -> tuple[str | None, str | None]:
    """
    Извлекает иерархию районов из geo.address массива CIAN.
    Возвращает (okrug_name, microrayon_name).

    CIAN geo.address типы в порядке убывания масштаба:
      region → city → okrug → district → raion → street → house
    Округ (okrug) — самый крупный внутригородской район.
    Микрорайон/квартал (district/raion) — более мелкий.
    """
    if not geo:
        return None, None
    parts = geo.get('address') or []

    okrug = None
    microrayon = None

    for part in parts:
        t = (part.get('type') or '').lower()
        name = part.get('name') or part.get('fullName') or ''
        if not name:
            continue
        if t == 'okrug':
            okrug = name
        elif t in ('district', 'raion', 'quarter'):
            # CIAN sometimes returns the okrug-level entry as type=district;
            # detect it by common suffixes. True okrugs are the bigger ones.
            nl = name.lower()
            if any(kw in nl for kw in ('округ', 'okrug')):
                if not okrug:
                    okrug = name
            else:
                if not microrayon:
                    microrayon = name

    return okrug or None, microrayon or None


def _parse_finish_status(status: str) -> tuple[int | None, int | None]:
    """
    Парсит строку 'Сдан в 4 кв. 2024' или 'Сдача во 2 кв. 2026'.
    Возвращает (year, quarter).
    """
    if not status:
        return None, None
    m = re.search(r'([1-4])\s*кв[^0-9]*([0-9]{4})', status)
    if m:
        return int(m.group(2)), int(m.group(1))
    m2 = re.search(r'([0-9]{4})', status)
    if m2:
        return int(m2.group(1)), None
    return None, None


def _to_float(v):
    """Безопасное приведение к float (строки тоже обрабатывает)."""
    if v is None:
        return None
    try:
        return float(v) or None
    except (TypeError, ValueError):
        return None


def _to_int(v):
    """Безопасное приведение к int."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ─── 1. Поиск: многозапросная стратегия ───────────────────────────────────────

def fetch_apartments_for_jk(jk_cian_id: int, page_num: int) -> list:
    """Запрашивает одну страницу квартир конкретного ЖК по его cian_id.
    Только квартиры от застройщика (from_developer=True).
    Без region-фильтра CIAN игнорирует newbuilding и возвращает всю Россию.
    С region CIAN хотя бы ограничивает город — затем фильтруем по ЖК клиентски."""
    query = {
        '_type': 'flatsale',
        'engine_version': {'type': 'term', 'value': 2},
        'region': {'type': 'terms', 'value': [CIAN_REGION_ID]},
        'newbuilding': {'type': 'term', 'value': jk_cian_id},
        'from_developer': {'type': 'term', 'value': True},
        'page': {'type': 'term', 'value': page_num},
    }
    for attempt in range(4):
        try:
            r = SESSION.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json={'jsonQuery': query}, timeout=25
            )
            if r.status_code in (429, 403):
                print(f'  ⏳ ЖК {jk_cian_id} стр.{page_num}: HTTP {r.status_code}')
                _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                continue
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    # Пустой/невалидный JSON — мягкая блокировка
                    print(f'  🔒 ЖК {jk_cian_id} стр.{page_num}: невалидный JSON (soft-block)')
                    _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                    continue
                d       = data.get('data') or {}
                offers  = d.get('offersSerialized', [])
                # CIAN использует offerCount (не totalCount — устаревшее поле)
                total   = d.get('offerCount') if d.get('offerCount') is not None else d.get('aggregatedCount')
                # Настоящий soft-block: CIAN вернул HTML-капчу вместо JSON — уже
                # обработано выше (невалидный JSON). Здесь дополнительно:
                # если offerCount == 0, но CIAN заполнил офферы "похожими" → это не блокировка,
                # это просто пустой результат для этого ЖК — возвращаем пустой список.
                if total == 0 or (total is None and offers):
                    # Проверяем: все офферы от чужих ЖК → пустой результат (не блок)
                    wrong = [o for o in offers
                             if (o.get('newbuilding') or {}).get('id') != jk_cian_id]
                    if len(wrong) == len(offers):
                        # Ноль квартир от застройщика в этом ЖК — просто пропускаем
                        return []
                # Фильтруем — оставляем только объявления этого ЖК
                return [o for o in offers
                        if (o.get('newbuilding') or {}).get('id') == jk_cian_id
                        or not (o.get('newbuilding') or {}).get('id')]
        except Exception as e:
            print(f'  ⚠️  ЖК {jk_cian_id} стр.{page_num} попытка {attempt+1}: {e}')
            time.sleep(5)
    return []


def collect_apartments_all_region(
    jk_data: dict,
    apt_data: dict,
    segments_done: set | None = None,
    cache_saver=None,
) -> tuple[int, set]:
    """
    Phase 1b (v2): собирает ВСЕ ~49 000 квартир Краснодара от застройщика
    через сегментацию по типу комнат × ценовому диапазону.

    Почему: CIAN API игнорирует фильтр newbuilding (per-JK) при отсутствии
    VPN/специального ключа. Единственный работающий фильтр — region (регион).
    Обход лимита в 54 страницы: разбиваем на room-группы × ценовые диапазоны,
    каждый сегмент умещается в 54 страниц × 28 офферов = 1512 офферов.

    segments_done — set строк-ключей вида 'rooms|price_from|price_to' для resume.
    cache_saver   — callback(apt_data, segments_done) для сохранения прогресса.
    Возвращает (total_new_apts, segments_done).
    """
    # Ценовые диапазоны: берём из city_config.json если заданы, иначе используем дефолт Краснодара/Сочи
    _cfg_price_splits = _city_cfg.get('price_splits')
    if _cfg_price_splits:
        PRICE_SPLITS = [tuple(p) for p in _cfg_price_splits]
    else:
        PRICE_SPLITS = [
            (None,        3_500_000),
            (3_500_000,   4_500_000),
            (4_500_000,   5_200_000),
            (5_200_000,   5_800_000),
            (5_800_000,   6_400_000),
            (6_400_000,   7_000_000),
            (7_000_000,   7_500_000),
            (7_500_000,   8_000_000),
            (8_000_000,   9_000_000),
            (9_000_000,  10_500_000),
            (10_500_000, 13_000_000),
            (13_000_000, 17_000_000),
            (17_000_000, 23_000_000),
            (23_000_000,  None),
        ]
    MAX_PER_SEGMENT = TOTAL_PAGES * 28  # 54 × 28 = 1512

    def _make_sub_splits(pmin, pmax):
        """Автоматически делит переполненный диапазон на ~5 равных частей."""
        lo = pmin or 0
        hi = pmax or 50_000_000
        step = max(200_000, round((hi - lo) / 5 / 100_000) * 100_000)
        result = []
        p = lo
        while p < hi:
            nxt = min(p + step, hi)
            result.append((p if p > 0 else None, nxt if nxt < hi else pmax))
            p = nxt
        return result

    if segments_done is None:
        segments_done = set()
    total_new = 0

    # Строим список сегментов: сначала пробуем room-группу целиком,
    # если > MAX_PER_SEGMENT — разбиваем по ценам (2 уровня)
    segments_to_run = []
    print(f'\n🏘️  Шаг 1b: Анализ сегментов (регион+тип+цена)...')
    for rooms, label in ROOM_FILTER_GROUPS:
        seg_key = f'{rooms}|None|None'
        if seg_key in segments_done:
            continue
        count = get_segment_offer_count(rooms=rooms)
        if count <= MAX_PER_SEGMENT:
            segments_to_run.append((rooms, None, None, label, count))
        else:
            # Уровень 1: ценовая сегментация
            for pmin, pmax in PRICE_SPLITS:
                sub_key = f'{rooms}|{pmin}|{pmax}'
                if sub_key in segments_done:
                    continue
                sub_count = get_segment_offer_count(rooms=rooms, price_from=pmin, price_to=pmax)
                pmin_m = f'{pmin//1_000_000}М' if pmin else '<'
                pmax_m = f'{pmax//1_000_000}М' if pmax else '+'
                sub_label = f'{label} {pmin_m}-{pmax_m}'
                if sub_count <= MAX_PER_SEGMENT:
                    segments_to_run.append((rooms, pmin, pmax, sub_label, sub_count))
                else:
                    # Уровень 2: автоматическое рекурсивное дробление переполненного диапазона
                    print(f'    ⚠️  {sub_label}: {sub_count} > {MAX_PER_SEGMENT}, дроблю дальше...')
                    for p2min, p2max in _make_sub_splits(pmin, pmax):
                        sub2_key = f'{rooms}|{p2min}|{p2max}'
                        if sub2_key in segments_done:
                            continue
                        sub2_count = get_segment_offer_count(rooms=rooms, price_from=p2min, price_to=p2max)
                        p2min_m = f'{p2min//1_000_000:.1f}М' if p2min else '<'
                        p2max_m = f'{p2max//1_000_000:.1f}М' if p2max else '+'
                        sub2_label = f'{label} {p2min_m}-{p2max_m}'
                        segments_to_run.append((rooms, p2min, p2max, sub2_label, sub2_count))
                        time.sleep(REQUEST_DELAY)
                time.sleep(REQUEST_DELAY)
        time.sleep(REQUEST_DELAY)

    total_segments = len(segments_to_run) + len(segments_done)
    done_count = len(segments_done)
    print(f'  Сегментов: {total_segments} всего, {done_count} уже готово, '
          f'{len(segments_to_run)} к обработке')

    for i, (rooms, pmin, pmax, label, expected) in enumerate(segments_to_run, 1):
        # Пересоздаём сессию перед каждым сегментом — подхватываем новый IP прокси
        rotate_session_if_needed()

        before = len(apt_data)
        pages_fetched = 0
        consecutive_errors = 0
        for pg in range(1, TOTAL_PAGES + 1):
            # Ротация внутри сегмента (если он длинный)
            rotate_session_if_needed()
            offers = fetch_page_for_segment(pg, rooms=rooms, price_from=pmin, price_to=pmax)
            if offers is None:
                # Сетевая ошибка — пропускаем страницу, не обрываем сегмент
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    print(f'  ⚠️  3 ошибки подряд на стр.{pg} — пропускаем остаток сегмента')
                    break
                continue
            consecutive_errors = 0
            if not offers:
                # Пустой ответ = реально конец пагинации
                break
            _extract_from_offers(offers, jk_data, apt_data)
            pages_fetched += 1
            time.sleep(REQUEST_DELAY)

        new_apts = len(apt_data) - before
        total_new += new_apts
        seg_key = f'{rooms}|{pmin}|{pmax}'
        segments_done.add(seg_key)

        pct = f'{new_apts/expected*100:.0f}%' if expected else '?'
        print(f'  [{i:2d}/{len(segments_to_run)}] {label:22} '
              f'+{new_apts:4d} кв ({pages_fetched}стр, ожид.{expected}, получ.{pct})')

        if cache_saver and i % 3 == 0:
            cache_saver(apt_data, segments_done)

    if cache_saver:
        cache_saver(apt_data, segments_done)

    print(f'\n  ✅ Phase 1b: +{total_new} новых квартир  |  '
          f'итого {len(apt_data)} уникальных')
    return total_new, segments_done


def collect_apartments_per_jk(
    jk_cian_ids: list,
    jk_data: dict,
    apt_data: dict,
    fetched_ids: set | None = None,
    cache_saver=None,
) -> tuple[int, set]:
    """
    УСТАРЕЛО: CIAN API игнорирует фильтр newbuilding без специального региона.
    Оставлено для совместимости с кэшем (cache['jk_apts_fetched']).
    В новом коде Phase 1b использует collect_apartments_all_region().
    """
    if fetched_ids is None:
        fetched_ids = set()
    print(f'\n⚠️  Per-JK сбор устарел (CIAN игнорирует newbuilding-фильтр). '
          f'Используем collect_apartments_all_region вместо него.')
    return 0, fetched_ids


def _build_region_query(page_num: int, rooms=None, price_from=None, price_to=None) -> dict:
    """Строит запрос ЦИАН: по региону + от застройщика + новостройки.
    Опционально: rooms (список типов), price_from/price_to (в рублях)."""
    query = {
        '_type': 'flatsale',
        'engine_version': {'type': 'term', 'value': 2},
        'region': {'type': 'terms', 'value': [CIAN_REGION_ID]},
        'newobject': {'type': 'term', 'value': True},
        'from_developer': {'type': 'term', 'value': True},
        'page': {'type': 'term', 'value': page_num},
    }
    if rooms:
        query['room'] = {'type': 'terms', 'value': rooms}
    if price_from is not None or price_to is not None:
        pval = {}
        if price_from is not None:
            pval['gte'] = int(price_from)
        if price_to is not None:
            pval['lte'] = int(price_to)
        query['price'] = {'type': 'range', 'value': pval}
    return query


def fetch_page_for_rooms(page_num: int, rooms: list | None):
    """Запрашивает одну страницу ЦИАН. rooms=None — все типы.
    Только квартиры от застройщика (from_developer=True).
    Возвращает list (может быть []) или None при сетевой ошибке."""
    query = _build_region_query(page_num, rooms=rooms)
    for attempt in range(4):
        try:
            r = SESSION.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json={'jsonQuery': query}, timeout=30
            )
            if r.status_code == 200:
                try:
                    return r.json().get('data', {}).get('offersSerialized', [])
                except ValueError:
                    print(f'  🔒 Страница {page_num} попытка {attempt+1}: пустой ответ (soft-block)')
                    rotate_session_if_needed(force=True)
                    _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                    continue
            if r.status_code in (429, 403):
                print(f'  ⏳ Страница {page_num}: ответ {r.status_code}')
                rotate_session_if_needed(force=True)
                _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                continue
            time.sleep(5 + attempt * 5)
        except Exception as e:
            print(f'  ⚠️  Страница {page_num} попытка {attempt+1}: {e}')
            rotate_session_if_needed(force=True)
            time.sleep(5 + attempt * 5)
    return None  # сетевая ошибка — не конец пагинации


def get_segment_offer_count(rooms=None, price_from=None, price_to=None) -> int:
    """Запрашивает offerCount для сегмента (rooms × price range) без загрузки офферов."""
    query = _build_region_query(1, rooms=rooms, price_from=price_from, price_to=price_to)
    for _attempt in range(3):
        try:
            r = SESSION.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json={'jsonQuery': query}, timeout=20
            )
            if r.status_code == 200:
                try:
                    d = r.json().get('data') or {}
                    return d.get('offerCount') or 0
                except ValueError:
                    rotate_session_if_needed(force=True)
                    time.sleep(10)
                    continue
        except Exception:
            time.sleep(5)
    return 0


def fetch_page_for_segment(page_num: int, rooms=None, price_from=None, price_to=None):
    """Запрашивает одну страницу ЦИАН для сегмента rooms × price range.
    Возвращает:
      list  — результаты (может быть пустым = конец пагинации)
      None  — сетевая/прокси ошибка (страница пропущена, не конец)
    """
    query = _build_region_query(page_num, rooms=rooms, price_from=price_from, price_to=price_to)
    for attempt in range(4):
        try:
            r = SESSION.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json={'jsonQuery': query}, timeout=30
            )
            if r.status_code == 200:
                try:
                    data = r.json().get('data', {})
                    offers = data.get('offersSerialized', [])
                    # Если CIAN вернул пустой список — реально конец страниц
                    return offers
                except ValueError:
                    print(f'  🔒 Сегмент стр.{page_num} попытка {attempt+1}: пустой ответ (soft-block)')
                    rotate_session_if_needed(force=True)
                    _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                    continue
            if r.status_code in (429, 403):
                rotate_session_if_needed(force=True)
                _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                continue
            # Другой HTTP статус — временная ошибка, пробуем ещё
            print(f'  ⚠️  Сегмент стр.{page_num} попытка {attempt+1}: HTTP {r.status_code}')
            time.sleep(5 + attempt * 5)
        except Exception as e:
            print(f'  ⚠️  Сегмент стр.{page_num} попытка {attempt+1}: {e}')
            rotate_session_if_needed(force=True)
            time.sleep(5 + attempt * 5)
    # Все 4 попытки исчерпаны — сетевая ошибка, НЕ конец пагинации
    return None


def _extract_from_offers(offers: list, jk_data: dict, apt_data: dict):
    """
    Извлекает данные ЖК и квартир из списка объявлений.
    jk_data[jk_cian_id] — агрегированные данные по ЖК.
    apt_data[cian_apt_id] — данные каждой квартиры.
    """
    for o in offers:
        nb = o.get('newbuilding') or {}
        # Get JK CIAN ID — try multiple sources
        jk_id = nb.get('id')
        if not jk_id:
            ct = o.get('newbuildingDynamicCalltracking') or {}
            jk_id = ct.get('newbuildingId')
        if not jk_id:
            continue

        # ─── JK-level data ────────────────────────────────────────────────────
        d = jk_data.setdefault(jk_id, {
            'jk_url': None, 'description': None, 'wall_material': None,
            'end_build_year': None, 'end_build_quarter': None,
            'object_class': None, 'photos': [], 'builder_id': None,
            'dev_profile_uri': None, 'dev_phone': None, 'dev_name': None,
            'jk_name': None, 'address': None,
            'address_city_district': None, 'address_quarter': None,
        })
        d['jk_name'] = d['jk_name'] or nb.get('name')
        if not d['jk_url']:
            d['jk_url'] = o.get('jkUrl')

        bids = o.get('buildersIds') or []
        if bids and not d['builder_id']:
            d['builder_id'] = bids[0]

        user = o.get('user') or {}
        if not d['dev_profile_uri'] and user.get('profileUri'):
            d['dev_profile_uri'] = user['profileUri']
        if not d['dev_name']:
            d['dev_name'] = user.get('agencyName') or user.get('companyName')
        if not d['dev_phone']:
            phones = user.get('phoneNumbers') or []
            if phones:
                p = phones[0]
                d['dev_phone'] = (p.get('countryCode') or '+7') + (p.get('number') or '')

        # НЕ берём описание из объявления квартиры — оно будет описанием квартиры,
        # а не ЖК. Описание ЖК берётся только со страницы самого ЖК (Фаза 2).

        bldg = o.get('building') or {}
        if not d['wall_material'] and bldg.get('materialType'):
            d['wall_material'] = MATERIAL_MAP.get(bldg['materialType'], bldg['materialType'])
        if not d['object_class'] and bldg.get('classType'):
            d['object_class'] = CLASS_MAP.get(bldg['classType'], bldg['classType'])
        deadline = bldg.get('deadline') or {}
        if deadline.get('year') and not d['end_build_year']:
            d['end_build_year'] = deadline['year']
            q = deadline.get('quarter')
            if q:
                d['end_build_quarter'] = QUARTER_MAP.get(q)

        for ph in o.get('photos') or []:
            url = ph.get('fullUrl') or ''
            tag = (ph.get('tag') or '').lower()
            # Exclude apartment floor plans from the JK-level photo pool
            if url and url not in d['photos'] and tag not in ('plan', 'layout', 'flatplan', 'flat-plan'):
                d['photos'].append(url)

        # ─── Apartment-level data ─────────────────────────────────────────────
        # Extract JK address from first apartment that has one
        cian_id = o.get('cianId') or o.get('id')
        if not cian_id:
            continue

        # Building name from factoids: {"type":"house","text":"Дом 1"}
        # CIAN uses several factoid types for building identification
        _BLDG_FACT_TYPES = {'house', 'section', 'queue', 'building', 'phase', 'corpus', 'enclave'}
        building_name = None
        for fact in (o.get('factoids') or []):
            if fact.get('type') in _BLDG_FACT_TYPES:
                building_name = (fact.get('text') or '').strip()
                break
        if not building_name:
            # Fallback: check building object houseName / enclosureName
            _bldg_obj = o.get('building') or {}
            building_name = (
                _bldg_obj.get('houseName') or _bldg_obj.get('enclosureName') or ''
            ).strip() or None

        # Photos: separate floor plan images from regular photos.
        # CIAN uses both 'tag' and 'type' fields on photos — check both.
        _PLAN_TAGS = {
            'plan', 'layout', 'flatplan', 'flat-plan', 'planir',
            'flat_plan', 'flat-schema', 'flatschema', 'schema', 'planimage',
            'apartment-plan', 'plan-apartment',
        }

        def _is_plan_photo(p: dict) -> bool:
            tag = (p.get('tag') or p.get('type') or '').lower()
            return tag in _PLAN_TAGS

        plan_img = next((
            p.get('fullUrl') for p in (o.get('photos') or [])
            if p.get('fullUrl') and _is_plan_photo(p)
        ), None)
        regular_photos = [
            p.get('fullUrl') for p in (o.get('photos') or [])
            if p.get('fullUrl') and not _is_plan_photo(p)
        ]
        main_img = regular_photos[0] if regular_photos else None
        gallery = regular_photos[1:20]

        # planLayouts — CIAN provides per-apartment floor plan schemas.
        # type "apart/flat/apartment" → планировка квартиры (apartment layout schema)
        # type "floor/storey"        → план этажа (floor-level plan showing apt location)
        # NOTE: CIAN batch search API often omits planLayouts or sends them typeless —
        # we try multiple field names and apply broad type sets + positional fallback.
        _APART_PLAN_TYPES = {
            'apart', 'flat', 'apartment', 'flatplan', 'plan',
            'flat_plan', 'schema', 'flatschema', 'layout', 'image',
        }
        _FLOOR_PLAN_TYPES = {
            'floor', 'storey', 'floor_plan', 'floorplan',
            'floor-plan', 'storey-plan', 'floorschema',
        }

        # Collect planLayouts from all CIAN field variants
        plan_layouts: list = list(o.get('planLayouts') or [])
        for _alt_key in ('layouts', 'planImages', 'layoutImages'):
            _alt = o.get(_alt_key)
            if _alt and isinstance(_alt, list):
                plan_layouts = plan_layouts + _alt

        # Also check single-object variants
        for _single_key in ('layout', 'planImage', 'planLayout'):
            _single = o.get(_single_key)
            if _single and isinstance(_single, dict):
                _url = _single.get('fullUrl') or _single.get('url', '')
                if _url:
                    plan_layouts = [_single] + plan_layouts
            elif _single and isinstance(_single, str) and _single.startswith('http'):
                if not plan_img:
                    plan_img = _single

        # Top-level floor plan field (some CIAN offer versions)
        _floor_direct = o.get('floorPlanImage') or o.get('floorPlan')
        if isinstance(_floor_direct, dict):
            _floor_direct = _floor_direct.get('fullUrl') or _floor_direct.get('url')

        def _pl_url(pl: dict) -> str:
            return pl.get('fullUrl') or pl.get('url') or pl.get('imageUrl') or ''

        plan_img_from_layouts = next(
            (_pl_url(pl) for pl in plan_layouts
             if _pl_url(pl) and (pl.get('type') or '').lower() in _APART_PLAN_TYPES),
            None
        )
        floor_plan_img = next(
            (_pl_url(pl) for pl in plan_layouts
             if _pl_url(pl) and (pl.get('type') or '').lower() in _FLOOR_PLAN_TYPES),
            None
        ) or (_floor_direct if isinstance(_floor_direct, str) and _floor_direct else None)

        # Positional fallback when types are absent:
        # 1 layout  → it's the apartment plan
        # 2 layouts → first = apartment plan, second = floor plan
        # 3+ layouts → first = apartment plan, rest might be floor plans
        if not plan_img_from_layouts and plan_layouts:
            first_url = _pl_url(plan_layouts[0])
            if first_url:
                plan_img_from_layouts = first_url
                if not floor_plan_img and len(plan_layouts) >= 2:
                    second_url = _pl_url(plan_layouts[1])
                    if second_url:
                        floor_plan_img = second_url

        # Merge: tag-based plan wins over planLayouts (tags are more reliable)
        plan_img = plan_img or plan_img_from_layouts

        price = (o.get('bargainTerms') or {}).get('price')
        try:
            area = float(o.get('totalArea') or 0) or None
        except (TypeError, ValueError):
            area = None
        try:
            price_int = int(price) if price else None
        except (TypeError, ValueError):
            price_int = None
        price = price_int
        price_per_sqm = round(price / area) if price and area else None

        # Address from geo
        geo = o.get('geo') or {}
        address = _build_address(geo)
        # Save address to JK dict (take the first non-empty one)
        if address and not d.get('address'):
            d['address'] = address

        # Extract full geo hierarchy (okrug + microrayon) directly from CIAN data
        _okrug, _micro = _extract_geo_hierarchy(geo)
        if _okrug and not d.get('address_city_district'):
            d['address_city_district'] = _okrug
        if _micro and not d.get('address_quarter'):
            d['address_quarter'] = _micro

        # Coords
        coords = geo.get('coordinates') or {}
        lat = coords.get('lat')
        lon = coords.get('lng')

        # Renovation
        raw_renov = (bldg.get('decoration') or o.get('decoration') or '')
        renovation = RENOVATION_MAP.get(raw_renov, raw_renov or None)

        # Title
        _rc = o.get('roomsCount')
        try:
            _rc = int(_rc) if _rc is not None else 0
        except (ValueError, TypeError):
            _rc = 0
        rooms_label = {0: 'Студия', 1: '1-комн', 2: '2-комн', 3: '3-комн',
                       4: '4-комн', 5: '5-комн', 6: '6-комн+'}.get(
            _rc, f'{_rc}-комн'
        )
        floor = _to_int(o.get('floorNumber'))
        total_fl = _to_int(bldg.get('floorsCount'))
        title = f'{rooms_label}, {area} м², {floor}/{total_fl} эт.' if area and floor else f'{rooms_label}'

        apt_data[str(cian_id)] = {
            'cian_id': str(cian_id),
            'jk_cian_id': jk_id,
            'jk_url': o.get('jkUrl'),
            'title': title,
            'rooms': o.get('roomsCount') or 0,
            'area': area,
            'living_area': _to_float(o.get('livingArea')),
            'kitchen_area': _to_float(o.get('kitchenArea')),
            'floor': floor,
            'total_floors': total_fl,
            'price': price,
            'price_per_sqm': price_per_sqm,
            'building_name': building_name,
            'plan_image': plan_img,
            'floor_plan_image': floor_plan_img,
            'source_url': o.get('fullUrl'),
            'main_image': main_img,
            'gallery_images': gallery,
            'address': address,
            'latitude': lat,
            'longitude': lon,
            'renovation_type': renovation,
            'is_apartment': o.get('isApartments', False),
            'has_balcony': bool(o.get('loggiasCount')),
            'description': (o.get('description') or '')[:2000],
            'property_type': 'Квартира',
        }


def fetch_building_all_pages(nb_id: int, house_id) -> list:
    """Phase 1c: Получает ВСЕ квартиры конкретного корпуса ЖК через geo.nb_house_key.
    Фильтр geo.nb_house_key РАБОТАЕТ и не игнорируется CIAN API (в отличие от newbuilding).
    nb_id — CIAN newBuildingId, house_id — CIAN houseId корпуса.
    Возвращает список offer-объектов со всех страниц (не более 54)."""
    house_key = f"{nb_id}_{house_id}"
    all_offers = []
    for page_num in range(1, 55):
        query = {
            '_type': 'flatsale',
            'engine_version': {'type': 'term', 'value': 2},
            'geo': {'type': 'geo', 'value': [{
                'type': 'nb_house_key',
                'key': house_key,
                'id': int(house_id),
                'newbuilding_id': int(nb_id),
            }]},
            'from_developer': {'type': 'term', 'value': True},
            'page': {'type': 'term', 'value': page_num},
        }
        success = False
        net_error = False
        for attempt in range(4):
            try:
                r = SESSION.post(
                    'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                    json={'jsonQuery': query}, timeout=30
                )
                if r.status_code == 200:
                    d = r.json().get('data') or {}
                    offers = d.get('offersSerialized', [])
                    if not offers:
                        return all_offers  # реальный конец пагинации
                    all_offers.extend(offers)
                    total = d.get('offerCount') or 0
                    if total > 0 and len(all_offers) >= total:
                        return all_offers
                    success = True
                    net_error = False
                    break
                elif r.status_code in (429, 403):
                    _anticaptcha_backoff(attempt, 'https://cian.ru/')
                    continue
                else:
                    time.sleep(5 + attempt * 5)
            except Exception as e:
                print(f'    ⚠️  корп {house_key} стр.{page_num}: {e}')
                rotate_session_if_needed(force=True)
                time.sleep(5 + attempt * 5)
                net_error = True
        if net_error:
            # Сетевая ошибка на этой странице — пропускаем её, НЕ обрываем корпус
            continue
        if not success:
            break
        time.sleep(REQUEST_DELAY)
    return all_offers


def fetch_page_newobjectsale(page_num: int):
    """Запрашивает одну страницу ЖК через тип newobjectsale.
    Используется как fallback для регионов где flatsale+newobject+from_developer = 0.
    Возвращает list (может быть []) или None при сетевой ошибке."""
    query = {
        '_type': 'newobjectsale',
        'engine_version': {'type': 'term', 'value': 2},
        'region': {'type': 'terms', 'value': [CIAN_REGION_ID]},
        'page': {'type': 'term', 'value': page_num},
    }
    for attempt in range(4):
        try:
            r = SESSION.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json={'jsonQuery': query}, timeout=30
            )
            if r.status_code == 200:
                try:
                    return r.json().get('data', {}).get('offersSerialized', [])
                except ValueError:
                    print(f'  🔒 newobjectsale стр.{page_num} попытка {attempt+1}: пустой ответ (soft-block)')
                    rotate_session_if_needed(force=True)
                    _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                    continue
            if r.status_code in (429, 403):
                rotate_session_if_needed(force=True)
                _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                continue
            time.sleep(5 + attempt * 5)
        except Exception as e:
            print(f'  ⚠️  newobjectsale стр.{page_num} попытка {attempt+1}: {e}')
            rotate_session_if_needed(force=True)
            time.sleep(5 + attempt * 5)
    return None  # сетевая ошибка


def collect_all_data_newobjectsale() -> tuple[dict, dict]:
    """
    Fallback-сбор для регионов где flatsale+newobject+from_developer = 0 офферов.
    Использует _type:newobjectsale — каждый оффер это целый ЖК, не квартира.
    Заполняет jk_data (URL + базовые поля), apt_data остаётся пустым.
    Шаг 2 (скрапинг страниц ЖК) подтянет описания/фото/детали из страниц ЖК.
    """
    from collections import defaultdict
    jk_data = defaultdict(lambda: {
        'jk_url': None, 'description': None, 'wall_material': None,
        'end_build_year': None, 'end_build_quarter': None, 'object_class': None,
        'photos': [], 'builder_id': None, 'dev_profile_uri': None,
        'dev_phone': None, 'dev_name': None, 'jk_name': None, 'address': None,
    })
    apt_data = {}

    print(f'\n📡 Шаг 1 (fallback): Сбор ЖК через newobjectsale '
          f'(до {TOTAL_PAGES} стр.)...')

    consec_err = 0
    for pg in range(1, TOTAL_PAGES + 1):
        offers = fetch_page_newobjectsale(pg)
        if offers is None:
            consec_err += 1
            if consec_err >= 3:
                print(f'  стр.{pg}: 3 ошибки подряд — стоп')
                break
            continue
        consec_err = 0
        if not offers:
            if pg > 1:
                print(f'  стр.{pg}: пусто — стоп')
            else:
                print(f'  стр.1: нет данных (блокировка или регион пуст)')
            break

        for o in offers:
            nb = o.get('newbuilding') or {}
            # For newobjectsale, the offer itself is the JK — try multiple ID sources
            jk_id = nb.get('id') or o.get('id')
            if not jk_id:
                continue

            d = jk_data[jk_id]
            d['jk_name'] = d['jk_name'] or nb.get('name') or o.get('name')
            if not d['jk_url']:
                _raw_url = (o.get('jkUrl') or nb.get('fullUrl')
                            or nb.get('siteUrl') or o.get('fullUrl'))
                if _raw_url:
                    # Strip CIAN tracking params (ionGuid, utm_* etc.) — they trigger
                    # captcha / a different page version when scraping
                    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
                    _STRIP_QP = {'ionGuid', 'mlSearchSessionGuid', 'sessionGuid',
                                 'from', 'utm_source', 'utm_medium',
                                 'utm_campaign', 'utm_content', 'utm_term'}
                    _p = urlparse(_raw_url)
                    _qs = {k: v for k, v in parse_qs(_p.query).items()
                           if k not in _STRIP_QP}
                    d['jk_url'] = urlunparse(_p._replace(query=urlencode(_qs, doseq=True)))

            bids = o.get('buildersIds') or []
            if bids and not d['builder_id']:
                d['builder_id'] = bids[0]

            user = o.get('user') or {}
            if not d['dev_name']:
                d['dev_name'] = user.get('agencyName') or user.get('companyName')
            if not d['dev_phone']:
                phones = user.get('phoneNumbers') or []
                if phones:
                    p = phones[0]
                    d['dev_phone'] = (p.get('countryCode') or '+7') + (p.get('number') or '')

            bldg = o.get('building') or {}
            if not d['wall_material'] and bldg.get('materialType'):
                d['wall_material'] = MATERIAL_MAP.get(bldg['materialType'], bldg['materialType'])
            if not d['object_class'] and bldg.get('classType'):
                d['object_class'] = CLASS_MAP.get(bldg['classType'], bldg['classType'])
            deadline = bldg.get('deadline') or {}
            if deadline.get('year') and not d['end_build_year']:
                d['end_build_year'] = deadline['year']
                q = deadline.get('quarter')
                if q:
                    d['end_build_quarter'] = QUARTER_MAP.get(q)

            for ph in o.get('photos') or []:
                url = ph.get('fullUrl') or ''
                tag = (ph.get('tag') or '').lower()
                if url and url not in d['photos'] and tag not in ('plan', 'layout', 'flatplan', 'flat-plan'):
                    d['photos'].append(url)

        print(f'  стр.{pg}: {len(offers)} ЖК найдено, итого: {len(jk_data)}')
        time.sleep(REQUEST_DELAY)

    print(f'\n  ✅ Fallback собрал: {len(jk_data)} ЖК (квартиры: 0 — используем скрапинг страниц ЖК)')
    return dict(jk_data), apt_data


def fetch_newobject_page(page_num: int) -> list:
    """Запрашивает одну страницу списка ЖК напрямую (тип newobject) — без привязки к квартирам."""
    query = {
        '_type': 'newobject',
        'engine_version': {'type': 'term', 'value': 2},
        'region': {'type': 'terms', 'value': [CIAN_REGION_ID]},
        'page': {'type': 'term', 'value': page_num},
    }
    for attempt in range(3):
        try:
            r = SESSION.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json={'jsonQuery': query}, timeout=25
            )
            if r.status_code == 200:
                return r.json().get('data', {}).get('offersSerialized', [])
            if r.status_code in (429, 403):
                _anticaptcha_backoff(attempt, 'https://cian.ru/novostrojki/')
                continue
        except Exception as e:
            time.sleep(3)
    return []


def collect_jk_urls_direct() -> dict:
    """
    Фаза 0 (дополнительная): Прямой поиск всех ЖК через newobject API.
    Находит ЖК которые могут быть не в результатах поиска квартир.
    Также извлекает полную гео-иерархию (okrug, micro, city, street) из карточек ЖК
    на странице /novostroyki/ — именно там CIAN показывает полный адрес.
    Возвращает dict: {jk_cian_id: {'jk_url': ..., 'jk_name': ..., 'builder_id': ...,
                                    'address_city_district': ..., 'address_quarter': ...,
                                    'addr_city': ..., 'addr_street': ...}}
    """
    jk_extra = {}
    for pg in range(1, 30):
        offers = fetch_newobject_page(pg)
        if not offers:
            if pg > 1:
                print(f'    стр.{pg}: пусто — стоп')
            break
        for o in offers:
            nb = o.get('newbuilding') or {}
            jk_id = nb.get('id')
            jk_url = _strip_tracking_params(o.get('jkUrl') or nb.get('fullUrl') or nb.get('siteUrl'))
            if jk_id and jk_url and jk_id not in jk_extra:
                bids = o.get('buildersIds') or []
                geo = o.get('geo') or {}
                _okrug, _micro = _extract_geo_hierarchy(geo)
                _address = _build_address(geo)
                # Extract city and street from geo.address directly
                _city = _street = None
                for _part in (geo.get('address') or []):
                    _t = (_part.get('type') or '').lower()
                    _n = _part.get('name') or _part.get('fullName') or ''
                    if _t == 'city' and not _city:
                        _city = _n
                    elif _t == 'street' and not _street:
                        _street = _n
                jk_extra[jk_id] = {
                    'jk_url':               jk_url,
                    'jk_name':              nb.get('name'),
                    'builder_id':           bids[0] if bids else None,
                    'address':              _address,
                    'address_city_district': _okrug,
                    'address_quarter':       _micro,
                    'addr_city':             _city,
                    'addr_street':           _street,
                }
        time.sleep(REQUEST_DELAY)
    return jk_extra


def collect_all_data() -> tuple[dict, dict]:
    """
    Многозапросная стратегия: 6 групп × до 54 страниц.
    Возвращает (jk_data, apt_data).
    """
    jk_data = defaultdict(lambda: {
        'jk_url': None, 'description': None, 'wall_material': None,
        'end_build_year': None, 'end_build_quarter': None, 'object_class': None,
        'photos': [], 'builder_id': None, 'dev_profile_uri': None,
        'dev_phone': None, 'dev_name': None, 'jk_name': None,
    })
    apt_data = {}

    print(f'\n📡 Шаг 1: Сбор данных из ЦИАН '
          f'(до {TOTAL_PAGES} стр. × {len(ROOM_FILTER_GROUPS)} групп)...')

    for rooms, label in ROOM_FILTER_GROUPS:
        before_jk = len(jk_data)
        before_apt = len(apt_data)
        print(f'  [{label:8}] начинаю...')
        consec_err = 0
        for pg in range(1, TOTAL_PAGES + 1):
            offers = fetch_page_for_rooms(pg, rooms)
            if offers is None:
                consec_err += 1
                if consec_err >= 3:
                    print(f'  [{label:8}] стр.{pg}: 3 ошибки подряд — стоп')
                    break
                continue
            consec_err = 0
            if not offers:
                if pg > 1:
                    print(f'  [{label:8}] стр.{pg}: пусто — стоп')
                else:
                    print(f'  [{label:8}] стр.1: пусто (блокировка или нет данных)')
                break
            _extract_from_offers(offers, jk_data, apt_data)
            if pg % 5 == 0 or pg == 1:
                print(f'  [{label:8}] стр.{pg}: офферов={len(offers)}, '
                      f'ЖК={len(jk_data)}, квартир={len(apt_data)}')
            time.sleep(REQUEST_DELAY)
        new_jk  = len(jk_data) - before_jk
        new_apt = len(apt_data) - before_apt
        print(f'  [{label:8}] ✅ +{new_jk:3d} ЖК  +{new_apt:4d} квартир '
              f'→ итого: {len(jk_data)} ЖК, {len(apt_data)} квартир')

    print(f'\n  ✅ Собрано: {len(jk_data)} ЖК, {len(apt_data)} квартир')
    return dict(jk_data), apt_data


# ─── 2. Скрапинг страниц ЖК ───────────────────────────────────────────────────

def _parse_about_description(text: str) -> str | None:
    idx = text.find('data-testid="AboutDescription"')
    if idx < 0:
        return None
    chunk = text[idx:idx + 6000]
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', chunk, re.DOTALL)
    cleaned = []
    for p in paragraphs:
        t = _strip_html(p)
        if t and len(t) > 5:
            cleaned.append(t)
    return '\n\n'.join(cleaned) if cleaned else None


def _parse_finishing_variants(text: str) -> str | None:
    idx = text.find('id="decorations"')
    if idx < 0:
        return None
    section = text[idx:idx + 15000]
    ul_m = re.search(r'<ul[^>]*>(.*?)</ul>', section, re.DOTALL)
    if not ul_m:
        return None
    ul_content = ul_m.group(1)
    li_items = re.findall(r'<li[^>]*>(.*?)</li>', ul_content, re.DOTALL)
    variants = []
    for item in li_items:
        title_m = re.search(r'<h3[^>]*>(.*?)</h3>', item, re.DOTALL)
        if not title_m:
            alt_m = re.search(r'<img[^>]+alt="([^"]+)"', item)
            if not alt_m:
                continue
            title = _strip_html(alt_m.group(1))
        else:
            title = _strip_html(title_m.group(1))
        if not title:
            continue
        img_m = re.search(r'<img[^>]+src="(https://[^"]+)"', item)
        image_url = img_m.group(1) if img_m else ''
        variants.append({'title': title, 'image_url': image_url})
    return json.dumps(variants, ensure_ascii=False) if variants else None


def _parse_logo_url(text: str) -> str | None:
    # 1. JSON "logoUrl" — точно соответствует застройщику
    logo_json = re.search(
        r'"logoUrl"\s*:\s*"[^"]*get-company-logo[^"]*[?&]id=([0-9]+)', text
    )
    if logo_json:
        return f'/api/cian-logo/{logo_json.group(1)}'

    # 2. Fallback: first get-company-logo mention
    m = re.search(r'get-company-logo[^"<>\s]{0,80}[?&]id=([0-9]+)', text)
    if m:
        return f'/api/cian-logo/{m.group(1)}'
    return None


def _parse_dev_cian_url(text: str) -> str | None:
    m = re.search(r'cian\.ru/(zastroishchik-[a-z0-9-]+-[0-9]+)', text)
    if m:
        return f'https://www.cian.ru/{m.group(1)}/'
    return None


def _parse_start_build(text: str) -> tuple[int | None, int | None]:
    m = re.search(
        r'(?:Начало строительства|startBuild)[^0-9]*([1-4])\s*кв[^0-9]*([0-9]{4})',
        text, re.IGNORECASE
    )
    if m:
        return int(m.group(2)), int(m.group(1))
    m2 = re.search(r'Начало строительства[^0-9]*([0-9]{4})', text)
    if m2:
        return int(m2.group(1)), None
    return None, None


def _extract_buildings_from_page(text: str) -> list[dict]:
    """
    Извлекает данные корпусов/литеров из конфига страницы ЖК.

    Проход 1: строгий regex для плоских JSON-объектов
      {"houseId":7674,"houseName":"Литер 1","finishStatus":"...", ...}
    Проход 2 (fallback): ищем все вхождения "houseId" в тексте и собираем данные
      из окна ±1000 символов — работает с вложенным/минифицированным JSON.
    """
    buildings = []
    seen_ids = set()

    # Find the big inline script (newbuilding-card config)
    inlines = re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL)
    nb_script = max(inlines, key=len) if inlines else text

    def _build_from_window(window: str, house_id: str, house_name: str) -> dict:
        finish_m = re.search(r'"finishStatus"\s*:\s*"([^"]*)"', window)
        finish_status = finish_m.group(1) if finish_m else None
        end_yr, end_q = _parse_finish_status(finish_status)
        count_m = re.search(r'"fromDeveloperPropsCount"\s*:\s*(\d+)', window)
        props_count = int(count_m.group(1)) if count_m else None
        floors_m = re.search(r'"floorsCount"\s*:\s*(\d+)', window)
        total_floors = int(floors_m.group(1)) if floors_m else None
        is_escrow_m = re.search(r'"isEscrow"\s*:\s*(true|false)', window)
        is_escrow = (is_escrow_m.group(1) == 'true') if is_escrow_m else None
        return {
            'building_id': house_id,
            'name': house_name,
            'building_name': house_name,
            'finish_status': finish_status,
            'end_build_year': end_yr,
            'end_build_quarter': end_q,
            'total_apartments': props_count,
            'total_floors': total_floors,
            'is_escrow': is_escrow,
        }

    # ── Проход 1: строгий — плоские объекты без вложенных {} ─────────────────
    house_pattern = re.compile(
        r'\{[^{}]*"houseId"\s*:\s*(\d+)[^{}]*"houseName"\s*:\s*"([^"]*)"[^{}]*\}',
        re.DOTALL
    )
    for m in house_pattern.finditer(nb_script):
        house_id = m.group(1)
        if house_id in seen_ids:
            continue
        seen_ids.add(house_id)
        buildings.append(_build_from_window(m.group(0), house_id, m.group(2)))

    # ── Проход 2: широкий — вложенный/минифицированный JSON ──────────────────
    # Срабатывает когда объект корпуса содержит вложенные {}, и Проход 1 не нашёл ничего.
    if not buildings:
        for hid_m in re.finditer(r'"houseId"\s*:\s*(\d+)', nb_script):
            house_id = hid_m.group(1)
            if house_id in seen_ids:
                continue
            seen_ids.add(house_id)
            # Окно ±1000 символов вокруг найденного houseId
            start = max(0, hid_m.start() - 200)
            end   = min(len(nb_script), hid_m.end() + 1200)
            window = nb_script[start:end]
            name_m = re.search(r'"houseName"\s*:\s*"([^"]*)"', window)
            house_name = name_m.group(1) if name_m else f'Корпус {house_id}'
            buildings.append(_build_from_window(window, house_id, house_name))

    return buildings


def _strip_tracking_params(url: str) -> str:
    """Удаляет CIAN-трекинговые параметры из URL (ionGuid, utm_*, from и др.)."""
    if not url:
        return url
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    _STRIP = {'ionGuid', 'mlSearchSessionGuid', 'from',
              'utm_source', 'utm_medium', 'utm_campaign',
              'utm_content', 'utm_term', 'sessionGuid'}
    p = urlparse(url)
    qs = {k: v for k, v in parse_qs(p.query).items() if k not in _STRIP}
    return urlunparse(p._replace(query=urlencode(qs, doseq=True)))


def scrape_jk_page(jk_url: str) -> dict:
    """Скрапить страницу ЖК — фото, описание, характеристики, логотип, литеры, застройщик."""
    if not jk_url:
        return {}
    # Strip tracking params — ionGuid can trigger captcha / different page version
    jk_url = _strip_tracking_params(jk_url)
    try:
        r = SESSION.get(jk_url, timeout=20, allow_redirects=True)
        if r.status_code != 200:
            return {}
    except Exception:
        return {}

    text = r.content.decode('utf-8', errors='replace')

    # Soft-block detection: CIAN returns a captcha / empty page with 200 status
    _is_block = (
        len(text) < 3000
        or 'captcha' in text.lower()
        or 'ddos' in text.lower()
        or ('cian.ru' not in text and 'циан' not in text.lower())
    )
    if _is_block:
        return {}

    result = {}

    # ── CDN-фото ЖК ───────────────────────────────────────────────────────────
    # URL вида: https://zhk-SLUG-i.cian.ru/ → slug = SLUG
    # Slug filter prevents picking up photos of similar JKs shown on the page.
    # CIAN sometimes uses a collapsed slug in image names (isay-park → isaypark),
    # so we match on both the full slug and a no-hyphen/no-city-suffix version.
    _CITY_SFXS = re.compile(
        r'-(krasnodar|maykop|sochi|anapa|gelendzhik|novorossiysk|armavir|adygeysk'
        r'|stavropol|rostov|volgograd|moscow|spb|starobzhegokayskoe.*)$'
    )
    jk_slug_full = None     # "isay-park-krasnodar"
    jk_slug_base = None     # "isay-park"  (city suffix removed)
    jk_slug_key  = None     # "isaypark"   (no hyphens)
    slug_m = re.search(r'zhk-(.+?)-i\.cian\.ru', jk_url)
    if slug_m:
        jk_slug_full = slug_m.group(1).lower()
        jk_slug_base = _CITY_SFXS.sub('', jk_slug_full)
        jk_slug_key  = jk_slug_base.replace('-', '')

    def _slug_ok(img_url: str) -> bool:
        """True если URL фото принадлежит текущему ЖК."""
        if not jk_slug_full:
            return True
        low = img_url.lower()
        low_nohyphen = low.replace('-', '').replace('/', '')
        if jk_slug_full in low:
            return True
        if jk_slug_base and jk_slug_base in low:
            return True
        if jk_slug_key and jk_slug_key in low_nohyphen:
            return True
        return False

    # Формат 1: именованный flat   images/name-jk-ID-N.jpg
    # Формат 2: именованный subdir images/AA/BBB/.../name-jk-ID-N.jpg  (новый ЦИАН, 1-4 уровня)
    raw_imgs_named = re.findall(
        r'images\.cdn-cian\.ru/images/(?:[0-9]+/)*'
        r'[a-zA-Z0-9_-]+-jk-[0-9]+-[0-9]+\.jpg',
        text
    )
    # Числовой формат (может включать планировки квартир — используем только как запасной)
    raw_imgs_num = re.findall(
        r'images\.cdn-cian\.ru/images/[0-9]+-[0-9]+\.jpg', text
    )
    jk_photos = []
    seen = set()
    # Приоритет — именованные (-jk-), фильтруем по slug ЖК
    for img in raw_imgs_named:
        if not _slug_ok(img):
            continue
        base = re.sub(r'-[0-9]+\.jpg$', '-1.jpg', img)
        full = 'https://' + base
        if full not in seen:
            seen.add(full)
            jk_photos.append(full)
    # Числовые используем только если именованных нет И их достаточно много
    # (мало числовых = скорее всего превью квартир/планировки, не фото ЖК)
    if not jk_photos and len(set(raw_imgs_num)) >= 6:
        for img in raw_imgs_num:
            base = re.sub(r'-[0-9]+\.jpg$', '-1.jpg', img)
            full = 'https://' + base
            if full not in seen:
                seen.add(full)
                jk_photos.append(full)
    result['jk_photos'] = jk_photos[:30]

    # ── Литеры/корпуса ────────────────────────────────────────────────────────
    buildings = _extract_buildings_from_page(text)
    if buildings:
        result['buildings'] = buildings
        # Derive buildings_count from the list — more reliable than the JSON field
        result.setdefault('buildings_count', len(buildings))

    # ── Характеристики через itemType ─────────────────────────────────────────
    items = re.findall(
        r'\{"title":"([^"]*)","value":"([^"]*)","itemType":"([^"]*)"\}', text
    )
    for title, value, itype in items:
        if itype == 'newbuildingClass' and value:
            result['object_class'] = value
        elif itype == 'materialType' and value:
            result['wall_material'] = value
        elif itype == 'ceilingHeight' and value:
            result['ceiling_height'] = value
        elif itype == 'decorations' and value:
            result['finishing_type'] = value
        elif itype == 'parking' and value:
            result['parking_type'] = value

    # ── Этажность ─────────────────────────────────────────────────────────────
    floors_m = re.search(r'Этажность[^0-9]*([0-9]+)[^0-9–-]*(?:[–-]\s*([0-9]+))?', text)
    if floors_m:
        f1 = int(floors_m.group(1))
        f2 = int(floors_m.group(2)) if floors_m.group(2) else f1
        result['floors_min'] = min(f1, f2)
        result['floors_max'] = max(f1, f2)

    # ── Описание ──────────────────────────────────────────────────────────────
    about = _parse_about_description(text)
    if about and len(about) > 100:
        result['detailed_description'] = about[:8000]
    if not result.get('detailed_description'):
        desc_candidates = re.findall(
            r'"description"\s*:\s*"((?:[^"\\]|\\.){80,5000})"', text
        )
        for raw_d in desc_candidates:
            decoded = _safe_decode(raw_d)
            if len(decoded) > 100 and re.search(r'[а-яА-Я]', decoded):
                result['description'] = decoded[:4000]
                break

    # ── Адрес ЖК из fullName на странице ЖК ──────────────────────────────────
    # ЦИАН встраивает адресные компоненты в JSON страницы в виде "fullName":"..."
    # Собираем их как запасной источник адреса (когда Phase 1 не даёт адреса)
    all_full_names = re.findall(r'"fullName"\s*:\s*"([^"]{3,120})"', text)
    if all_full_names:
        # Убираем дублирование, сохраняем порядок
        seen_fn = set()
        uniq_fn = []
        for fn in all_full_names:
            decoded_fn = _safe_decode(fn)
            if decoded_fn not in seen_fn:
                seen_fn.add(decoded_fn)
                uniq_fn.append(decoded_fn)
        # Пропускаем слишком широкие административные единицы
        _SKIP_FN = {'россия', 'краснодарский край', 'республика адыгея',
                    'ставропольский край', 'ростовская область',
                    'краевой округ', 'республика', 'адыгея'}
        addr_parts = [fn for fn in uniq_fn if fn.lower().strip() not in _SKIP_FN]
        if addr_parts:
            result['address_from_page'] = ', '.join(addr_parts[:4])

    # ── Варианты отделки ──────────────────────────────────────────────────────
    finishing_variants = _parse_finishing_variants(text)
    if finishing_variants:
        result['finishing_variants'] = finishing_variants

    # ── Координаты ЖК ─────────────────────────────────────────────────────────
    # Приоритет: вложенный geo-объект {"lat":X,"lng":Y} — самый надёжный из CIAN
    # Bounds берутся из env vars (установленных run_city.py) или из city_config.json,
    # fallback — вся Россия (40-80 / 19-190).
    _lat_min = float(os.environ.get('ENRICH_LAT_MIN', _city_cfg.get('lat_min', 40.0)))
    _lat_max = float(os.environ.get('ENRICH_LAT_MAX', _city_cfg.get('lat_max', 80.0)))
    _lon_min = float(os.environ.get('ENRICH_LON_MIN', _city_cfg.get('lon_min', 19.0)))
    _lon_max = float(os.environ.get('ENRICH_LON_MAX', _city_cfg.get('lon_max', 190.0)))

    def _in_range(lat, lon):
        if abs(lat - 44.609139) < 0.001 and abs(lon - 37.6213) < 0.001:
            return False  # CIAN-заглушка «координаты неизвестны»
        return _lat_min <= lat <= _lat_max and _lon_min <= lon <= _lon_max

    _coord_lat = _coord_lon = None
    # 1. Вложенный geo-объект
    for _m in re.finditer(
        r'"(?:coordinates|geoPoint|point|geo)"\s*:\s*\{[^}]*?"lat(?:itude)?"\s*:\s*([\d.]+)[^}]*?"(?:lng|lon(?:gitude)?)"\s*:\s*([\d.]+)',
        text
    ):
        _lat, _lon = float(_m.group(1)), float(_m.group(2))
        if _in_range(_lat, _lon):
            _coord_lat, _coord_lon = _lat, _lon
            break
    # 2. Пара lat=X&lon=Y
    if not _coord_lat:
        for _m in re.finditer(r'lat(?:itude)?[=:]([0-9.]+)[^0-9.]{1,20}?lon(?:gitude)?[=:]([0-9.]+)', text):
            _lat, _lon = float(_m.group(1)), float(_m.group(2))
            if _in_range(_lat, _lon):
                _coord_lat, _coord_lon = _lat, _lon
                break
    # 3. Fallback: по отдельности
    if not _coord_lat:
        _lats = [float(x) for x in re.findall(r'"lat(?:itude)?"\s*:\s*([\d.]+)', text) if _lat_min <= float(x) <= _lat_max]
        _lons = [float(x) for x in re.findall(r'"(?:lng|lon(?:gitude)?)"\s*:\s*([\d.]+)', text) if _lon_min <= float(x) <= _lon_max]
        if _lats and _lons:
            _coord_lat, _coord_lon = _lats[0], _lons[0]
    if _coord_lat and _coord_lon:
        result['latitude'] = _coord_lat
        result['longitude'] = _coord_lon

    # ── Логотип ───────────────────────────────────────────────────────────────
    logo_url = _parse_logo_url(text)
    if logo_url:
        result['logo_url'] = logo_url

    # ── Застройщик ЦИАН URL ───────────────────────────────────────────────────
    dev_cian_url = _parse_dev_cian_url(text)
    if dev_cian_url:
        result['dev_cian_url'] = dev_cian_url

    # ── Начало строительства ──────────────────────────────────────────────────
    start_yr, start_q = _parse_start_build(text)
    if start_yr:
        result['start_build_year'] = start_yr
    if start_q:
        result['start_build_quarter'] = start_q

    # ── Фото хода строительства ───────────────────────────────────────────────
    cp_idx = text.find('"constructionProgress"')
    if cp_idx >= 0:
        cp_chunk = text[cp_idx:cp_idx + 20000]
        raw_cp_urls = re.findall(
            r'"url"\s*:\s*"(https?:\\u002F\\u002F[^"]+?)"', cp_chunk
        )
        if not raw_cp_urls:
            raw_cp_urls = re.findall(
                r'"url"\s*:\s*"(https?://images\.cdn-cian\.ru/[^"]+?)"', cp_chunk
            )
        decoded_cp_urls = [u.replace('\\u002F', '/') for u in raw_cp_urls]
        seen_cp = set()
        cp_photos = []
        for u in decoded_cp_urls:
            if u not in seen_cp and 'thumbnail' not in u.lower():
                seen_cp.add(u)
                cp_photos.append(u)
        if cp_photos:
            result['construction_progress_images'] = json.dumps(
                cp_photos[:50], ensure_ascii=False
            )

    # ── Инфраструктура ────────────────────────────────────────────────────────
    infra_idx = text.find('Объекты на территории жилого комплекса')
    if infra_idx >= 0:
        infra_chunk = text[infra_idx:infra_idx + 4000]
        spans = re.findall(r'<span[^>]*>([^<]{3,60})</span>', infra_chunk)
        infra_items = [
            s.strip() for s in spans
            if re.search(r'[а-яА-Я]', s) and len(s.strip()) > 3
        ]
        if infra_items:
            result['infrastructure'] = json.dumps(
                [{'name': name, 'icon': 'building'} for name in infra_items],
                ensure_ascii=False
            )

    # ── Планировки квартир ────────────────────────────────────────────────────
    layout_imgs = []
    seen_layout = set()
    layout_chunk_idx = text.find('"planLayouts"')
    if layout_chunk_idx < 0:
        layout_chunk_idx = text.find('"layouts"')
    if layout_chunk_idx >= 0:
        layout_chunk = text[layout_chunk_idx:layout_chunk_idx + 30000]
        raw_layout_urls = re.findall(
            r'"(?:imageUrl|url|image|photo)"\s*:\s*"(https?:\\u002F\\u002F[^"]+?\.(?:jpg|png|webp))"',
            layout_chunk, re.IGNORECASE
        )
        if not raw_layout_urls:
            raw_layout_urls = re.findall(
                r'"(?:imageUrl|url|image|photo)"\s*:\s*"(https?://[^"]+?\.(?:jpg|png|webp))"',
                layout_chunk, re.IGNORECASE
            )
        for url in raw_layout_urls:
            url = url.replace('\\u002F', '/').replace('\\/', '/')
            if url not in seen_layout:
                seen_layout.add(url)
                layout_imgs.append(url)
    # Fallback: direct regex for layout/plan images in page
    if not layout_imgs:
        plan_urls = re.findall(
            r'https?://[^"\']*(?:plan|layout|planir)[^"\']*\.(?:jpg|png|webp)', text, re.IGNORECASE
        )
        for url in plan_urls:
            if url not in seen_layout:
                seen_layout.add(url)
                layout_imgs.append(url)
    if layout_imgs:
        result['layout_images'] = json.dumps(layout_imgs[:40], ensure_ascii=False)

    # ── Прочие поля ───────────────────────────────────────────────────────────
    for label, pat, conv in [
        ('end_build_year',  r'"endBuildYear"\s*:\s*([0-9]{4})',  int),
        ('buildings_count', r'"buildingsCount"\s*:\s*([0-9]+)',   int),
    ]:
        if label not in result:
            m = re.search(pat, text)
            if m:
                try:
                    result[label] = conv(m.group(1))
                except Exception:
                    pass

    return result


# ─── 3. Скрапинг страниц застройщиков ────────────────────────────────────────

LOGO_SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              'static', 'uploads', 'developer_logos')


def _download_logo(company_id: str) -> str | None:
    """Скачивает логотип застройщика с CIAN через текущую SESSION (прокси + анти-капча).
    Сохраняет в static/uploads/developer_logos/{company_id}.jpg
    Возвращает локальный URL или None при ошибке."""
    os.makedirs(LOGO_SAVE_DIR, exist_ok=True)
    local_path = os.path.join(LOGO_SAVE_DIR, f'{company_id}.jpg')
    if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
        return f'/static/uploads/developer_logos/{company_id}.jpg'
    logo_api_url = f'https://cian.ru/api/get-company-logo/?id={company_id}'
    dev_page_url = f'https://www.cian.ru/zastroishchik-{company_id}/'
    for attempt in range(3):
        try:
            r = SESSION.get(
                logo_api_url,
                timeout=10,
                allow_redirects=True,
                headers={'Referer': dev_page_url},
            )
            ct = r.headers.get('Content-Type', '')
            if r.status_code == 200 and 'image' in ct and len(r.content) > 500:
                with open(local_path, 'wb') as f:
                    f.write(r.content)
                return f'/static/uploads/developer_logos/{company_id}.jpg'
            # Капча или блокировка — решаем и повторяем
            if _is_captcha_response(r):
                print(f'  🔐 _download_logo: капча для {company_id}, решаем...')
                _anticaptcha_backoff(attempt, dev_page_url)
                continue
            # Реальный 404 — логотипа нет в CIAN
            if r.status_code == 404:
                return None
        except Exception:
            pass
        break
    return None


def scrape_developer_page(dev_url: str) -> dict:
    if not dev_url:
        return {}
    url = dev_url if dev_url.startswith('http') else f'https://www.cian.ru/{dev_url.strip("/")}/'
    try:
        r = SESSION.get(url, timeout=20, allow_redirects=True)
        if r.status_code != 200:
            return {}
    except Exception:
        return {}

    text = r.content.decode('utf-8', errors='replace')
    result = {'source_url': url}

    name_m = re.search(r'"name"\s*:\s*"([^"]{3,60})"', text)
    if name_m:
        result['name'] = name_m.group(1)

    # Извлекаем company_id из логотипа и сразу скачиваем через SESSION
    logo_json = re.search(
        r'"logoUrl"\s*:\s*"[^"]*get-company-logo[^"]*[?&]id=([0-9]+)', text
    )
    company_id = logo_json.group(1) if logo_json else None
    if not company_id:
        m_bid = re.search(r'get-company-logo[^"<>\s]{0,80}[?&]id=([0-9]+)', text)
        if m_bid:
            company_id = m_bid.group(1)
    if not company_id:
        m_src = re.search(r'-(\d+)/?$', url)
        if m_src:
            company_id = m_src.group(1)

    if company_id:
        local_logo = _download_logo(company_id)
        if local_logo:
            result['logo_url'] = local_logo
        else:
            result['logo_url'] = f'/api/cian-logo/{company_id}'
    if not result.get('logo_url'):
        for pat in [
            r'"logo"\s*:\s*"(https://[^"]+\.(?:png|jpg|webp)[^"]*)"',
            r'"logoUrl"\s*:\s*"(https://[^"]+\.(?:png|jpg|webp)[^"]*)"',
        ]:
            m = re.search(pat, text)
            if m:
                result['logo_url'] = m.group(1)
                break

    for pat in [r'"yearOfFoundation"\s*:\s*([0-9]{4})', r'"foundedYear"\s*:\s*([0-9]{4})']:
        m = re.search(pat, text)
        if m:
            try:
                result['founded_year'] = int(m.group(1))
            except Exception:
                pass
            break

    for label, pat, conv in [
        ('website',            r'"website"\s*:\s*"(https?://[^"]+)"',               str),
        ('inn',                r'"inn"\s*:\s*"([0-9]{10,12})"',                      str),
        ('full_name',          r'"fullName"\s*:\s*"([^"]{5,200})"',                  str),
        # Актуальные названия полей в JSON CIAN (2024-2025)
        ('completed_projects', r'"readyNewbuildings"\s*:\s*([0-9]+)',                 int),
        ('completed_projects', r'"completedNewbuildings"\s*:\s*([0-9]+)',             int),
        ('completed_projects', r'"completedProjects"\s*:\s*([0-9]+)',                 int),
        ('under_construction', r'"newBuildingsInProcess"\s*:\s*([0-9]+)',             int),
        ('under_construction', r'"activeNewbuildings"\s*:\s*([0-9]+)',                int),
        ('under_construction', r'"activeProjects"\s*:\s*([0-9]+)',                    int),
        # Дома (houses) как запасной вариант если нет newbuildings
        ('houses_completed',   r'"readyHouses"\s*:\s*([0-9]+)',                      int),
        ('houses_in_process',  r'"housesInProcess"\s*:\s*([0-9]+)',                  int),
    ]:
        if label in result:
            continue
        m = re.search(pat, text)
        if m:
            try:
                result[label] = conv(m.group(1))
            except Exception:
                result[label] = m.group(1)

    for start_word in ['Компания', 'Группа компаний', 'ГК «', 'СК «']:
        idx = text.find(start_word)
        if idx >= 0:
            chunk = text[idx:idx + 3000]
            d = _strip_html(chunk)
            if len(d) > 150 and re.search(r'[а-яА-Я]', d) and re.search(r'\d{4}', d):
                sentences = re.split(r'(?<=[.!?])\s+', d)
                desc = ''
                for s in sentences:
                    if len(desc) + len(s) > 2000:
                        break
                    desc += s + ' '
                result['description'] = desc.strip()[:4000]
                break

    if not result.get('description'):
        for pat in [
            r'"about"\s*:\s*"((?:[^"\\]|\\.){80,4000})"',
            r'"description"\s*:\s*"((?:[^"\\]|\\.){80,4000})"',
        ]:
            m = re.search(pat, text)
            if m:
                decoded = _safe_decode(m.group(1))
                if (len(decoded) > 80 and re.search(r'[а-яА-Я]', decoded)
                        and not decoded.startswith('✅')
                        and 'Информация от официального' not in decoded):
                    result['description'] = decoded[:4000]
                    break

    return result


# ─── 4. Обновление БД ────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    translit = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh',
        'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
        'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts',
        'ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'
    }
    slug = name.lower()
    slug = ''.join(translit.get(c, c) for c in slug)
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')[:80]


def update_complex_db(cur, rc_id: int, search_data: dict, page_data: dict):
    now = datetime.now()
    jk_photos = page_data.get('jk_photos', [])
    # Only use confirmed JK exterior photos (from Phase 2 page scraping).
    # apt_photos from search results contain apartment interiors & floor plans —
    # NEVER include them in the JK gallery to avoid polluting it with planировки.
    main_image = jk_photos[0] if jk_photos else None
    gallery = json.dumps(jk_photos[:20], ensure_ascii=False) if jk_photos else None

    _raw_desc    = page_data.get('description') or search_data.get('description')
    desc         = html_lib.unescape(_raw_desc).replace('\xa0', ' ').strip() if _raw_desc else None
    detailed     = page_data.get('detailed_description')
    material     = page_data.get('wall_material')     or search_data.get('wall_material')
    end_yr       = page_data.get('end_build_year')    or search_data.get('end_build_year')
    end_q        = page_data.get('end_build_quarter') or search_data.get('end_build_quarter')
    start_yr     = page_data.get('start_build_year')
    start_q      = page_data.get('start_build_quarter')
    obj_cls      = page_data.get('object_class')      or search_data.get('object_class')
    bldg_cnt     = page_data.get('buildings_count')
    # Fallback: count distinct building names from properties when page didn't supply the value
    if not bldg_cnt:
        cur.execute(
            "SELECT COUNT(DISTINCT complex_building_name) FROM properties "
            "WHERE complex_id=%s AND is_active=TRUE "
            "AND complex_building_name IS NOT NULL AND complex_building_name!=''",
            (rc_id,)
        )
        _db_bldg = (cur.fetchone() or [0])[0]
        if _db_bldg and _db_bldg > 0:
            bldg_cnt = _db_bldg
    ceil_h       = page_data.get('ceiling_height')
    finishing    = page_data.get('finishing_type')
    parking      = page_data.get('parking_type')
    fl_min       = page_data.get('floors_min')
    fl_max       = page_data.get('floors_max')
    logo_url     = page_data.get('logo_url')
    fin_variants  = page_data.get('finishing_variants')
    cp_images     = page_data.get('construction_progress_images')
    infra         = page_data.get('infrastructure')
    layout_images = page_data.get('layout_images')

    fields, values = [], []
    def add(col, val):
        if val is not None:
            fields.append(col); values.append(val)

    # Адрес: Phase 1 (из квартир) имеет приоритет, иначе Phase 2 (fullName со страницы ЖК)
    jk_address = search_data.get('address') or page_data.get('address_from_page')
    # Гео-иерархия: округ и микрорайон из CIAN geo.address
    geo_okrug  = search_data.get('address_city_district') or page_data.get('address_city_district')
    geo_micro  = search_data.get('address_quarter')       or page_data.get('address_quarter')
    # Город и улица из гео-иерархии newobject API (/novostroyki/ карточки)
    geo_city   = search_data.get('addr_city')   or page_data.get('addr_city')
    geo_street = search_data.get('addr_street') or page_data.get('addr_street')

    add('updated_at', now)
    add('is_active', True)
    if geo_okrug:  add('address_city_district', geo_okrug[:149])
    if geo_micro:  add('address_quarter', geo_micro[:149])
    if geo_city:   add('addr_city',   geo_city[:99])
    if geo_street: add('addr_street', geo_street[:299])
    if main_image:
        add('main_image', main_image[:499])
    elif not jk_photos and page_data:
        # Phase 2 успешно загрузил страницу ЖК, но именованных фото не нашёл —
        # очищаем потенциально устаревшую картинку-планировку из предыдущего прогона.
        # page_data пустой → страница не была загружена, оставляем как есть.
        fields.append('main_image')
        values.append(None)
    if gallery:      add('gallery_images', gallery)
    if jk_address:   add('address', jk_address[:299])
    lat = page_data.get('latitude') or search_data.get('latitude')
    lon = page_data.get('longitude') or search_data.get('longitude')
    if lat and lon:
        add('latitude', lat)
        add('longitude', lon)
    if desc:         add('description', desc[:4999])
    if detailed:     add('detailed_description', detailed[:7999])
    if material:     add('wall_material', material[:99])
    if end_yr:       add('end_build_year', end_yr)
    if end_q:        add('end_build_quarter', end_q)
    if start_yr:     add('start_build_year', start_yr)
    if start_q:      add('start_build_quarter', start_q)
    if obj_cls:      add('object_class_display_name', obj_cls[:99])
    if bldg_cnt:     add('buildings_count', bldg_cnt)
    if ceil_h:       add('ceiling_height', str(ceil_h)[:49])
    if finishing:    add('finishing_type', finishing[:99])
    if parking:      add('parking_type', parking[:99])
    if fl_min:       add('floors_min', fl_min)
    if fl_max:       add('floors_max', fl_max)
    if logo_url:     add('logo_url', logo_url[:399])
    if fin_variants: add('finishing_variants', fin_variants)
    if cp_images:     add('construction_progress_images', cp_images)
    if infra:         add('infrastructure', infra)
    if layout_images: add('layout_images', layout_images)
    feat = page_data.get('complex_features')
    if feat:          add('complex_features', feat)

    if fields:
        set_clause = ', '.join(f'{f} = %s' for f in fields)
        cur.execute(
            f'UPDATE residential_complexes SET {set_clause} WHERE id = %s',
            values + [rc_id]
        )


def update_developer_db(cur, dev_id: int, search_data: dict, page_data: dict, builder_id):
    now = datetime.now()
    fields, values = [], []
    def add(col, val):
        if val is not None:
            fields.append(col); values.append(val)

    add('updated_at', now)
    add('is_active', True)
    if builder_id:                    add('external_id', str(builder_id))
    if search_data.get('dev_phone'):  add('phone', search_data['dev_phone'][:19])
    if page_data.get('logo_url'):     add('logo_url', page_data['logo_url'][:299])
    if page_data.get('founded_year'):
        add('founded_year', page_data['founded_year'])
        add('established_year', page_data['founded_year'])
    if page_data.get('website'):      add('website', page_data['website'][:199])
    if page_data.get('inn'):          add('inn', page_data['inn'][:19])
    if page_data.get('description'):  add('description', page_data['description'][:4999])
    if page_data.get('full_name'):    add('full_name', page_data['full_name'][:299])
    if page_data.get('completed_projects'):
        add('completed_projects', page_data['completed_projects'])
        add('completed_complexes', page_data['completed_projects'])
    if page_data.get('under_construction'):
        add('under_construction', page_data['under_construction'])
        add('construction_complexes', page_data['under_construction'])
    if page_data.get('source_url'):   add('source_url', page_data['source_url'][:499])

    if fields:
        set_clause = ', '.join(f'{f} = %s' for f in fields)
        cur.execute(
            f'UPDATE developers SET {set_clause} WHERE id = %s',
            values + [dev_id]
        )


def _building_slug(rc_id: int, building_id) -> str:
    """Генерирует slug для корпуса: rc-<rc_id>-b-<building_id>."""
    bid = re.sub(r'[^a-z0-9]+', '-', str(building_id).lower()).strip('-')
    return f'rc-{rc_id}-b-{bid}'[:99]


def upsert_buildings(cur, rc_id: int, buildings: list[dict]):
    """Вставляет/обновляет корпуса/литеры ЖК в таблице buildings."""
    now = datetime.now()
    count = 0
    for b in buildings:
        building_id = b.get('building_id')
        if not building_id:
            continue
        slug = _building_slug(rc_id, building_id)
        cur.execute("""
            INSERT INTO buildings
                (complex_id, building_id, building_name, name, slug,
                 total_floors, total_apartments,
                 end_build_year, end_build_quarter, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (complex_id, building_id) DO UPDATE SET
                building_name    = EXCLUDED.building_name,
                name             = EXCLUDED.name,
                slug             = EXCLUDED.slug,
                total_floors     = COALESCE(EXCLUDED.total_floors, buildings.total_floors),
                total_apartments = COALESCE(EXCLUDED.total_apartments, buildings.total_apartments),
                end_build_year   = COALESCE(EXCLUDED.end_build_year, buildings.end_build_year),
                end_build_quarter= COALESCE(EXCLUDED.end_build_quarter, buildings.end_build_quarter),
                updated_at       = EXCLUDED.updated_at
        """, (
            rc_id,
            str(building_id),
            (b.get('building_name') or '')[:99],
            (b.get('name') or '')[:99],
            slug,
            b.get('total_floors'),
            b.get('total_apartments'),
            b.get('end_build_year'),
            b.get('end_build_quarter'),
            now, now,
        ))
        count += 1
    return count


def upsert_apartments(cur, apt_data: dict, rc_map: dict):
    """
    Вставляет/обновляет квартиры в таблице properties.
    Использует inner_id (unique constraint) как ключ дедупликации — туда пишем CIAN ID.
    rc_map: {str(cian_jk_id): (rc_id, developer_id)}

    Возвращает (inserted, updated, skipped, price_changes).
    price_changes — список (property_id, old_price, new_price, price_per_sqm, inner_id)
    для квартир у которых изменилась цена.

    Логика жизненного цикла:
    • Новый объект   → вставляется с is_active=TRUE, status='active'
    • Существующий   → обновляется, цена/площадь берётся с ЦИАН;
                       если ранее был помечен проданным — автоматически
                       реактивируется: is_active=TRUE, status='active',
                       sold_detected_at=NULL
    • Исчезнувший   → Phase 4d (mark_sold) ставит is_active=FALSE,
                       status='sold', sold_detected_at=NOW()
    """
    now = datetime.now()
    inserted = 0
    updated = 0
    skipped = 0
    price_changes = []  # (property_id, old_price, new_price, price_per_sqm, inner_id)

    # ── Шаг 0. Предзагружаем старые цены + is_active для всего батча ──────────
    inner_ids_batch = [str(c) for c in apt_data.keys()]
    old_price_map = {}  # inner_id -> {'id': ..., 'price': ..., 'was_active': ...}
    if inner_ids_batch:
        cur.execute("""
            SELECT inner_id, id, price, is_active
            FROM properties
            WHERE inner_id = ANY(%s::varchar[])
        """, (inner_ids_batch,))
        for row in cur.fetchall():
            old_price_map[str(row[0])] = {
                'id': row[1],
                'price': row[2],
                'was_active': row[3],
            }

    # ── Шаг 1. UPSERT каждой квартиры ─────────────────────────────────────────
    for cian_id, apt in apt_data.items():
        jk_cian_id = apt.get('jk_cian_id')
        if not jk_cian_id:
            skipped += 1
            continue

        rc_info = rc_map.get(str(jk_cian_id))
        if not rc_info:
            skipped += 1
            continue

        rc_id, dev_id = rc_info
        gallery_json = json.dumps(apt.get('gallery_images', []), ensure_ascii=False) if apt.get('gallery_images') else None

        slug = f'kv-{cian_id}'

        cur.execute("""
            INSERT INTO properties (
                inner_id, title, slug, rooms, area, living_area, kitchen_area,
                floor, total_floors, price, price_per_sqm,
                complex_id, developer_id, city_id,
                building_number, complex_building_name, plan_image, floor_plan_image,
                source_url, url,
                main_image, gallery_images,
                address, latitude, longitude,
                renovation_type, is_apartment, has_balcony,
                description, property_type, status, is_active,
                created_at, updated_at, last_seen_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,
                %s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,%s
            )
            ON CONFLICT (inner_id) DO UPDATE SET
                title                 = EXCLUDED.title,
                rooms                 = COALESCE(EXCLUDED.rooms,         properties.rooms),
                area                  = COALESCE(EXCLUDED.area,          properties.area),
                living_area           = COALESCE(EXCLUDED.living_area,   properties.living_area),
                kitchen_area          = COALESCE(EXCLUDED.kitchen_area,  properties.kitchen_area),
                floor                 = COALESCE(EXCLUDED.floor,         properties.floor),
                total_floors          = COALESCE(EXCLUDED.total_floors,  properties.total_floors),
                price                 = COALESCE(EXCLUDED.price,         properties.price),
                price_per_sqm         = COALESCE(EXCLUDED.price_per_sqm, properties.price_per_sqm),
                complex_id            = EXCLUDED.complex_id,
                city_id               = EXCLUDED.city_id,
                developer_id          = COALESCE(EXCLUDED.developer_id,  properties.developer_id),
                building_number       = COALESCE(EXCLUDED.building_number,       properties.building_number),
                complex_building_name = COALESCE(EXCLUDED.complex_building_name, properties.complex_building_name),
                plan_image            = COALESCE(EXCLUDED.plan_image,       properties.plan_image),
                floor_plan_image      = COALESCE(EXCLUDED.floor_plan_image, properties.floor_plan_image),
                main_image            = COALESCE(EXCLUDED.main_image,    properties.main_image),
                gallery_images        = COALESCE(EXCLUDED.gallery_images,properties.gallery_images),
                address               = COALESCE(EXCLUDED.address,       properties.address),
                latitude              = COALESCE(EXCLUDED.latitude,      properties.latitude),
                longitude             = COALESCE(EXCLUDED.longitude,     properties.longitude),
                renovation_type       = COALESCE(EXCLUDED.renovation_type, properties.renovation_type),
                source_url            = COALESCE(EXCLUDED.source_url,    properties.source_url),
                updated_at            = EXCLUDED.updated_at,
                last_seen_at          = EXCLUDED.last_seen_at,
                -- Реактивация: если объект был помечен проданным — возвращаем в продажу
                is_active             = TRUE,
                status                = 'active',
                sold_detected_at      = NULL
            RETURNING id, (xmax = 0) AS is_insert
        """, (
            cian_id,
            sanitize_property_title(
                apt.get('title'),
                rooms=apt.get('rooms'),
                area=apt.get('area'),
                floor=apt.get('floor'),
                total_floors=apt.get('total_floors'),
            )[:199],
            slug,
            apt.get('rooms'),
            apt.get('area'),
            apt.get('living_area'),
            apt.get('kitchen_area'),
            apt.get('floor'),
            apt.get('total_floors'),
            apt.get('price'),
            apt.get('price_per_sqm'),
            rc_id,
            dev_id,
            _city_id_from_url(apt.get('source_url'), CITY_ID),
            (apt.get('building_name') or '')[:99] or None,
            (apt.get('building_name') or '')[:99] or None,
            (apt.get('plan_image') or '')[:499] or None,
            (apt.get('floor_plan_image') or '')[:499] or None,
            (apt.get('source_url') or '')[:499] or None,
            (apt.get('source_url') or '')[:499] or None,
            (apt.get('main_image') or '')[:499] or None,
            gallery_json,
            (apt.get('address') or '')[:399] or None,
            apt.get('latitude'),
            apt.get('longitude'),
            (apt.get('renovation_type') or '')[:99] or None,
            apt.get('is_apartment', False),
            apt.get('has_balcony', False),
            (apt.get('description') or '')[:1999] or None,
            'Квартира',
            'active',
            True,
            now, now, now,
        ))
        row = cur.fetchone()
        if not row:
            skipped += 1
            continue

        prop_id  = row[0]
        is_insert = row[1]

        if is_insert:
            inserted += 1
        else:
            updated += 1
            # ── Обнаружение изменения цены ─────────────────────────────────
            old_info  = old_price_map.get(str(cian_id))
            new_price = apt.get('price')
            if old_info and new_price and old_info['price'] and new_price != old_info['price']:
                price_changes.append((
                    prop_id,
                    old_info['price'],
                    new_price,
                    apt.get('price_per_sqm'),
                    str(cian_id),
                ))
            # ── Лог реактивации ─────────────────────────────────────────────
            if old_info and not old_info['was_active']:
                print(f'    ♻️  Реактивирован (был продан): inner_id={cian_id}')

    return inserted, updated, skipped, price_changes


def record_price_history_batch(cur, conn, price_changes: list) -> int:
    """
    Записывает изменения цен в таблицу price_history.
    price_changes: список (property_id, old_price, new_price, price_per_sqm, inner_id)
    Возвращает количество записанных строк.
    """
    if not price_changes:
        return 0
    now = datetime.now()
    count = 0
    for prop_id, old_price, new_price, price_per_sqm, inner_id in price_changes:
        if not (old_price and new_price and old_price != new_price):
            continue
        try:
            change_pct = round((new_price - old_price) / old_price * 100, 2)
        except (ZeroDivisionError, TypeError):
            change_pct = None
        cur.execute("""
            INSERT INTO price_history
                (property_id, record_type, price, price_per_sqm,
                 price_change_percent, recorded_at, month, year)
            VALUES (%s, 'apartment', %s, %s, %s, %s, %s, %s)
        """, (prop_id, new_price, price_per_sqm, change_pct,
              now, now.month, now.year))
        count += 1
    if count:
        conn.commit()
        print(f'  📈 Записано изменений цен: {count} квартир')
    return count


def mark_sold(cur, conn, city_id: int, seen_ids: set) -> int:
    """
    Phase 4d: помечает исчезнувшие квартиры как проданные.
    Защита: если охват < 60% — операция пропускается (частичный скрап).

    Возвращает количество помеченных квартир (0 если порог не пройден).
    """
    if not seen_ids:
        return 0

    cur.execute("""
        SELECT inner_id FROM properties
        WHERE city_id = %s AND is_active = TRUE AND inner_id IS NOT NULL
    """, (city_id,))
    db_ids = {str(r[0]) for r in cur.fetchall()}
    sold_ids = db_ids - seen_ids

    coverage = len(seen_ids) / max(len(db_ids), 1)
    if coverage < 0.6:
        print(f'\n⚠️  Охват {coverage:.0%} ({len(seen_ids)} из {len(db_ids)}) — '
              f'пометка проданных пропущена (порог 60%)')
        return 0

    if not sold_ids:
        print(f'\n✅ Проданных/снятых не обнаружено ({len(seen_ids)} из {len(db_ids)} active)')
        return 0

    cur.execute("""
        UPDATE properties
        SET is_active        = FALSE,
            status           = 'sold',
            sold_detected_at = NOW(),
            updated_at       = NOW()
        WHERE city_id = %s AND inner_id = ANY(%s::varchar[])
    """, (city_id, list(sold_ids)))
    sold_count = cur.rowcount
    conn.commit()
    print(f'\n🔴 Помечено как проданные/снятые: {sold_count} квартир '
          f'(охват {coverage:.0%}, было active: {len(db_ids)})')
    return sold_count


def snapshot_complex_prices(cur, conn, city_id: int) -> int:
    """
    Записывает ежемесячный снапшот цен по каждому ЖК города в price_history.
    Запись создаётся только если для данного ЖК в текущем месяце/году её ещё нет.
    Возвращает количество новых записей.
    """
    now = datetime.now()
    m, y = now.month, now.year

    # Агрегируем по ЖК
    cur.execute("""
        SELECT complex_id,
               AVG(price)::bigint        AS avg_price,
               MIN(price)                AS min_price,
               MAX(price)                AS max_price,
               AVG(price_per_sqm)::int   AS avg_price_per_sqm,
               COUNT(*)                  AS properties_count
        FROM properties
        WHERE city_id = %s
          AND is_active = TRUE
          AND price IS NOT NULL
          AND complex_id IS NOT NULL
        GROUP BY complex_id
    """, (city_id,))
    rows = cur.fetchall()
    if not rows:
        return 0

    # Находим ЖК у которых снапшот за этот месяц уже есть
    complex_ids = [r[0] for r in rows]
    cur.execute("""
        SELECT DISTINCT complex_id FROM price_history
        WHERE record_type = 'complex'
          AND month = %s AND year = %s
          AND complex_id = ANY(%s)
    """, (m, y, complex_ids))
    already_snapped = {r[0] for r in cur.fetchall()}

    count = 0
    for row in rows:
        cid, avg_p, min_p, max_p, avg_psqm, cnt = row
        if cid in already_snapped:
            continue
        cur.execute("""
            INSERT INTO price_history
                (complex_id, record_type, avg_price, min_price, max_price,
                 avg_price_per_sqm, properties_count, recorded_at, month, year)
            VALUES (%s, 'complex', %s, %s, %s, %s, %s, %s, %s, %s)
        """, (cid, avg_p, min_p, max_p, avg_psqm, cnt, now, m, y))
        count += 1

    if count:
        conn.commit()
        print(f'  📊 Снапшот цен ЖК: {count} из {len(rows)} ЖК (месяц {m}/{y})')
    return count


def geocode_from_apartments(cur, conn) -> int:
    """
    Заполняет lat/lng у ЖК из средних координат их квартир.
    Квартиры уже содержат точные координаты из ЦИАН — бесплатно, без внешних API.
    Возвращает количество обновлённых ЖК.
    """
    cur.execute("""
        UPDATE residential_complexes rc
        SET
            latitude  = sub.avg_lat,
            longitude = sub.avg_lon
        FROM (
            SELECT
                p.complex_id,
                ROUND(AVG(p.latitude)::numeric,  7)::float AS avg_lat,
                ROUND(AVG(p.longitude)::numeric, 7)::float AS avg_lon
            FROM properties p
            WHERE p.latitude  IS NOT NULL
              AND p.longitude IS NOT NULL
              AND p.city_id   = %s
            GROUP BY p.complex_id
        ) sub
        WHERE rc.id       = sub.complex_id
          AND rc.city_id  = %s
          AND (rc.latitude IS NULL OR rc.longitude IS NULL)
    """, (CITY_ID, CITY_ID))
    updated = cur.rowcount
    conn.commit()
    print(f'  📍 Геокодировано ЖК: {updated} (из координат квартир)')
    return updated


def insert_new_complex(cur, jk_cian_id: int, sdata: dict, page_data: dict, city_id: int) -> int | None:
    """Вставляет новый ЖК в БД если его ещё нет. Возвращает id или None."""
    name = sdata.get('jk_name') or page_data.get('name')
    if not name:
        return None
    slug_base = _slugify(name)
    cur.execute('SELECT id FROM residential_complexes WHERE slug = %s', (slug_base,))
    if cur.fetchone():
        slug_base = f'{slug_base}-{jk_cian_id}'

    now = datetime.now()
    cur.execute("""
        INSERT INTO residential_complexes
            (name, slug, city_id, complex_id, is_active, cashback_rate, created_at, updated_at)
        VALUES (%s, %s, %s, %s, TRUE, 0, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING id
    """, (name[:199], slug_base, city_id, str(jk_cian_id), now, now))
    row = cur.fetchone()
    if row:
        print(f'  ➕ Новый ЖК: [{row[0]}] {name} (CIAN id={jk_cian_id})')
        return row[0]
    return None


# ─── Кэш ─────────────────────────────────────────────────────────────────────

_SCRIPTS_DIR   = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE     = os.path.join(_SCRIPTS_DIR, f'.enrich_cache_city{CITY_ID}.json')
# Обратная совместимость: если нет per-city файла — ищем старый общий кэш
_OLD_CACHE     = os.path.join(_SCRIPTS_DIR, '.enrich_cache.json')
if not os.path.exists(CACHE_FILE) and os.path.exists(_OLD_CACHE) and CITY_ID == 1:
    import shutil as _shutil
    _shutil.copy2(_OLD_CACHE, CACHE_FILE)
    print(f'📦 Кэш мигрирован: .enrich_cache.json → {os.path.basename(CACHE_FILE)}')
STOP_FLAG_FILE = os.path.join(_SCRIPTS_DIR, f'.enrich_stop_city{CITY_ID}')

# ── Авто-сброс кэша ──────────────────────────────────────────────────────────
# Сбрасываем если:
#   1. reset_on_run=true в .enrich_settings.json
#   2. ENRICH_RESET=1 задан через env (флаг --reset в run_city.py)
#   3. Кэш старше CACHE_MAX_AGE_DAYS дней (завершённый phase=4 считается устаревшим)
CACHE_MAX_AGE_DAYS = int(_file_settings.get('cache_max_age_days', 7))
_reset_on_run  = _file_settings.get('reset_on_run', False)
_reset_env     = os.environ.get('ENRICH_RESET', '').strip() in ('1', 'true', 'yes')

def _should_reset_cache() -> str | None:
    """Возвращает причину сброса кэша или None если сброс не нужен."""
    if _reset_env:
        return 'флаг --reset (ENRICH_RESET=1)'
    if _reset_on_run:
        return 'reset_on_run=true в настройках'
    if not os.path.exists(CACHE_FILE):
        return None
    import time as _time
    age_days = (_time.time() - os.path.getmtime(CACHE_FILE)) / 86400
    if age_days >= CACHE_MAX_AGE_DAYS:
        return f'кэш устарел ({age_days:.1f} д. ≥ {CACHE_MAX_AGE_DAYS} д.)'
    return None

_reset_reason = _should_reset_cache()
if _reset_reason and os.path.exists(CACHE_FILE):
    os.remove(CACHE_FILE)
    print(f'🔄 Кэш сброшен: {_reset_reason}')

def save_cache(data: dict):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}

def _check_stop() -> bool:
    """Вернуть True если найден стоп-флаг файл. Удаляет флаг после обнаружения."""
    if os.path.exists(STOP_FLAG_FILE):
        try:
            os.remove(STOP_FLAG_FILE)
        except Exception:
            pass
        print('\n🛑 Получен сигнал остановки — прерываю обработку.')
        return True
    return False


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    mode = ENRICH_MODE
    # Маркер: скрипт живой и main() достигнут. Позволяет диагностировать
    # ситуации когда subprocess стартует но падает до начала работы.
    print(f'🚀 enrich_complexes.py: main() запущен | mode={mode} | city_id={CITY_ID} | '
          f'proxy={"да" if PROXY_URL else "нет"} | pid={os.getpid()}', flush=True)
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'helium'),
        database=os.environ.get('PGDATABASE', 'heliumdb'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', 'password'),
    )
    conn.autocommit = False
    cur = conn.cursor()

    # VPN — подключаемся до первых запросов к ЦИАН
    vpn_connect()

    # ── РЕЖИМ: Быстрое обновление цен (~5 мин) ─────────────────────────────────
    if mode == 'prices':
        city_label = _city_cfg.get('name') or f'city_id={CITY_ID}'
        print(f'{"="*60}')
        print(f'⚡ Режим: Обновление цен | {city_label}')
        print(f'   Phase 1: поиск квартир → Phase 4c: цены → Phase 4d: проданные')
        print(f'{"="*60}')

        # Phase 1 only — собираем актуальные данные без кэша
        jk_search_data_int, apt_data_raw = collect_all_data()

        # Rebuild rc_map
        cur.execute("""
            SELECT rc.id, rc.complex_id, rc.developer_id
            FROM residential_complexes rc
            WHERE rc.city_id = %s AND rc.complex_id IS NOT NULL
        """, (CITY_ID,))
        rc_map = {row[1]: (row[0], row[2]) for row in cur.fetchall()}

        # Phase 4c — обновляем цены
        print(f'\n🏠 Обновление цен ({len(apt_data_raw)} квартир)...')
        apt_items = list(apt_data_raw.items())
        # Освобождаем исходный словарь — apt_items теперь содержит все данные
        import gc as _gc_prices
        del apt_data_raw
        _gc_prices.collect()
        total_inserted = total_updated = total_skipped = 0
        all_price_changes = []
        for i in range(0, len(apt_items), 500):
            batch = dict(apt_items[i:i+500])
            ins, upd, skip, pch = upsert_apartments(cur, batch, rc_map)
            total_inserted += ins; total_updated += upd; total_skipped += skip
            all_price_changes.extend(pch)
            conn.commit()
            pct = min(100, round((i + len(batch)) / max(len(apt_items), 1) * 100))
            print(f'  [{pct:3d}%] +{total_inserted} новых, ~{total_updated} обновлено')

        # Phase 4c.1 — фиксируем изменения цен в price_history
        record_price_history_batch(cur, conn, all_price_changes)

        # Phase 4d — помечаем проданные
        _seen_ids_prices = {str(k) for k, _ in apt_items}
        del apt_items
        _gc_prices.collect()
        mark_sold(cur, conn, CITY_ID, _seen_ids_prices)

        # Phase 4d.1 — ежемесячный снапшот цен по ЖК
        print(f'\n📊 Снапшот цен ЖК...')
        snapshot_complex_prices(cur, conn, CITY_ID)

        # Геокодинг — заполняем пустые координаты ЖК из квартир
        print(f'\n📍 Геокодинг ЖК...')
        geocode_from_apartments(cur, conn)

        conn.close()
        print(f'\n{"="*60}')
        print(f'⚡ Цены обновлены: +{total_inserted} новых, {total_updated} обновлено')
        print(f'{"="*60}')
        return

    # ── РЕЖИМ: Полный прогон ───────────────────────────────────────────────────
    # Ensure buildings table has unique constraint on (complex_id, building_id)
    cur.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'buildings_complex_building_unique'
          ) THEN
            ALTER TABLE buildings
              ADD CONSTRAINT buildings_complex_building_unique
              UNIQUE (complex_id, building_id);
          END IF;
        END $$;
    """)
    conn.commit()

    # Load all existing JKs with CIAN IDs
    cur.execute("""
        SELECT rc.id, rc.name, rc.complex_id, rc.developer_id
        FROM residential_complexes rc
        WHERE rc.city_id = %s AND rc.complex_id IS NOT NULL
        ORDER BY rc.id
    """, (CITY_ID,))
    db_complexes = {row[2]: row for row in cur.fetchall()}

    city_label = _city_cfg.get('name') or f'city_id={CITY_ID}'
    print(f'{"="*60}')
    print(f'🏗️  Пайплайн: {len(db_complexes)} ЖК в БД | {city_label}')
    print(f'{"="*60}')

    cache = load_cache()
    jk_search_data_raw = cache.get('jk_search_data', {})
    jk_search_data_int = {int(k): v for k, v in jk_search_data_raw.items()}
    apt_data_raw        = cache.get('apt_data', {})
    unique_jk_urls      = cache.get('unique_jk_urls', {})
    dev_page_cache      = cache.get('dev_page_cache', {})
    phase               = cache.get('phase', 1)
    # Трекинг всех ЦИАН-ID за весь прогон — для mark_sold без хранения всех квартир в RAM
    _all_1b_ids: set = set()

    # Guard: if cache has phase>1 but no actual data — it's a stale/corrupt cache, restart
    if phase > 1 and not jk_search_data_raw:
        print(f'  ⚠️  Кэш повреждён (phase={phase}, данных нет) — сбрасываем и запускаем сбор заново')
        phase = 1
        cache = {}
        unique_jk_urls = {}
        dev_page_cache = {}

    # ── Шаг 1: Поиск квартир и ЖК ─────────────────────────────────────────────
    if phase <= 1 and not jk_search_data_raw:
        print('  (Шаг 1: Нет кэша — запускаем поиск)')
        jk_search_data_int, apt_data_raw = collect_all_data()

        # Fallback: если flatsale+newobject+from_developer дал 0 ЖК —
        # используем newobjectsale (актуально для небольших регионов: Сочи, Геленджик и т.п.)
        if not jk_search_data_int:
            print(f'\n  ⚠️  flatsale-запрос дал 0 ЖК — пробуем fallback (newobjectsale)...')
            jk_search_data_int, apt_data_raw = collect_all_data_newobjectsale()
            if not jk_search_data_int:
                print(f'  ⚠️  Fallback тоже дал 0 — возможно блокировка или регион пуст.')

        jk_search_data_raw = {str(k): v for k, v in jk_search_data_int.items()}

        # ── Шаг 0: Прямой поиск ЖК через newobject API (расширяет покрытие 96→134+)
        print(f'\n🔭 Шаг 0: Дополнительный поиск ЖК (newobject)...')
        jk_extra = collect_jk_urls_direct()
        extra_added = 0
        for jk_id, extra_data in jk_extra.items():
            if jk_id not in jk_search_data_int:
                # ЖК есть в ЦИАН но не нашли через поиск квартир — добавляем
                jk_search_data_int[jk_id] = {
                    'jk_url':                extra_data['jk_url'],
                    'jk_name':               extra_data['jk_name'],
                    'builder_id':            extra_data['builder_id'],
                    'photos':                [],
                    'description':           None,
                    'wall_material':         None,
                    'end_build_year':        None,
                    'end_build_quarter':     None,
                    'object_class':          None,
                    'dev_profile_uri':       None,
                    'dev_phone':             None,
                    'dev_name':              None,
                    # Гео-иерархия из newobject API — полный адрес карточки /novostroyki/
                    'address':               extra_data.get('address'),
                    'address_city_district': extra_data.get('address_city_district'),
                    'address_quarter':       extra_data.get('address_quarter'),
                    'addr_city':             extra_data.get('addr_city'),
                    'addr_street':           extra_data.get('addr_street'),
                }
                jk_search_data_raw[str(jk_id)] = jk_search_data_int[jk_id]
                extra_added += 1
            else:
                # ЖК уже есть — дополняем гео-иерархию если ещё не заполнена
                existing = jk_search_data_int[jk_id]
                for geo_field in ('address_city_district', 'address_quarter',
                                  'addr_city', 'addr_street', 'address'):
                    if not existing.get(geo_field) and extra_data.get(geo_field):
                        existing[geo_field] = extra_data[geo_field]
        if extra_added:
            print(f'  ➕ Найдено дополнительных ЖК: {extra_added} (итого: {len(jk_search_data_int)})')
        else:
            print(f'  ✅ Все ЖК уже найдены через поиск квартир')

        cache = {
            'jk_search_data':   jk_search_data_raw,
            'apt_data':         {},   # Не кэшируем квартиры — экономия RAM/диска (пишем в БД напрямую)
            'unique_jk_urls':   {},
            'dev_page_cache':   {},
            'segments_fetched': [],   # Phase 1b progress (list of segment keys done)
            'phase': 1,               # stay at 1 so Phase 1b runs next
        }
        save_cache(cache)
        unique_jk_urls = {}
        dev_page_cache = {}
        phase = 1  # Phase 1b will advance to 2
    else:
        print(f'  (Шаг 1: Кэш — {len(jk_search_data_int)} ЖК, {len(apt_data_raw)} квартир)')

    # ── Шаг 1b: Сбор ВСЕХ квартир через сегментацию (регион × тип × цена) ────────
    # CIAN API игнорирует фильтр newbuilding без VPN — единственный работающий
    # фильтр это region. Обходим 54-страничный лимит через room × price сегменты.
    # phase == 1 → только что завершили Phase 1 или продолжаем Phase 1b после сбоя
    if phase == 1:
        # Поддержка обоих форматов кэша: новый segments_fetched + старый jk_apts_fetched
        segments_done = set(cache.get('segments_fetched') or [])

        # rc_map для промежуточной записи в БД
        rc_map_1b = {cid: (row[0], row[3]) for cid, row in db_complexes.items()}
        _1b_written: set = set()  # cian apt ids уже записанных в БД в этой фазе
        # _all_1b_ids уже инициализирован в main() — просто используем его здесь

        def _save_1b(apt_d, segs_done):
            """Сохраняет кэш + пишет новые квартиры прямо в БД (crash-safe).
            Создаёт новые ЖК на лету при первой встрече — так квартиры
            записываются в БД даже при прерванном прогоне (до Step 4b/4c).
            """
            nonlocal _1b_written, _all_1b_ids
            cache['apt_data']         = {}   # Не кэшируем квартиры — они пишутся в БД сразу
            cache['segments_fetched'] = list(segs_done)
            save_cache(cache)
            new_apts = {k: v for k, v in apt_d.items() if k not in _1b_written}
            if not new_apts:
                return
            try:
                # ── On-the-fly JK creation ──────────────────────────────────
                # Для квартир чьи ЖК ещё не в rc_map_1b — создаём ЖК сразу,
                # чтобы не терять квартиры при частичных прогонах.
                jk_ids_needed = {
                    str(apt.get('jk_cian_id'))
                    for apt in new_apts.values()
                    if apt.get('jk_cian_id') and str(apt.get('jk_cian_id')) not in rc_map_1b
                }
                jk_created_now = 0
                for jk_id_str in jk_ids_needed:
                    jk_id_int = int(jk_id_str)
                    sdata = jk_search_data_int.get(jk_id_int, {})
                    if not sdata.get('jk_name'):
                        continue  # нет имени — вставим позже в Step 4b
                    try:
                        new_rc_id = insert_new_complex(cur, jk_id_int, sdata, {}, CITY_ID)
                        if new_rc_id:
                            rc_map_1b[jk_id_str] = (new_rc_id, None)
                            jk_created_now += 1
                    except Exception as _e:
                        conn.rollback()
                        # Попробуем переиспользовать уже созданный slug
                        cur.execute(
                            "SELECT id FROM residential_complexes WHERE complex_id=%s LIMIT 1",
                            (jk_id_str,)
                        )
                        _row = cur.fetchone()
                        if _row:
                            rc_map_1b[jk_id_str] = (_row[0], None)
                if jk_created_now:
                    conn.commit()
                    print(f'  🆕 Создано новых ЖК в шаге 1b: {jk_created_now}')
                # ── Upsert apartments ───────────────────────────────────────
                ins, upd, _skip, _pch = upsert_apartments(cur, new_apts, rc_map_1b)
                conn.commit()
                _1b_written.update(new_apts.keys())
                _all_1b_ids.update(new_apts.keys())
                skipped_msg = f', пропущено:{_skip}' if _skip else ''
                print(f'  💾 Записано в БД: +{ins} новых, {upd} обновл.{skipped_msg} '
                      f'(в этом прогоне: {len(_1b_written)})')
                # ── Освобождаем RAM: удаляем записанные квартиры из словаря ──
                for _k in list(new_apts.keys()):
                    apt_d.pop(_k, None)
                import gc as _gc1b; _gc1b.collect()
            except Exception as e:
                conn.rollback()
                print(f'  ⚠️  Ошибка промежуточной записи: {e}')

        _, segments_done = collect_apartments_all_region(
            jk_search_data_int, apt_data_raw,
            segments_done=segments_done, cache_saver=_save_1b,
        )
        _save_1b(apt_data_raw, segments_done)

        cache['apt_data']         = {}   # Не кэшируем — квартиры уже в БД (экономия RAM)
        cache['segments_fetched'] = list(segments_done)
        cache['unique_jk_urls']   = {}
        cache['dev_page_cache']   = {}
        cache['phase']            = 2
        save_cache(cache)
        import gc as _gc_1b_end; _gc_1b_end.collect()
        unique_jk_urls = {}
        dev_page_cache = {}
        phase = 2

    # ── Шаг 2: Скрапинг страниц ЖК + литеры ──────────────────────────────────
    if phase <= 2:
        print(f'\n🌐 Шаг 2: Скрапинг страниц ЖК (+ литеры/корпуса/планировки)...')
        url_to_jk_ids = defaultdict(list)
        for jk_id, data in jk_search_data_int.items():
            url = data.get('jk_url')
            if url:
                url_to_jk_ids[url].append(jk_id)

        pending_urls = [u for u in url_to_jk_ids if u not in unique_jk_urls]
        print(f'  Осталось скрапить: {len(pending_urls)} (в кэше: {len(unique_jk_urls)})')

        # ── Pre-flight: проверяем что ЦИАН не блокирует наш IP ────────────────
        if pending_urls:
            _test_url = _strip_tracking_params(pending_urls[0])
            try:
                _r = SESSION.get(_test_url, timeout=15, allow_redirects=True)
                _body = _r.content.decode('utf-8', errors='replace')
                _blocked = (
                    len(_body) < 5000
                    or 'captcha' in _body.lower()
                    or ('cian.ru' not in _body and 'циан' not in _body.lower())
                )
                if _blocked:
                    print(f'\n  ❌ БЛОКИРОВКА ЦИАН: ваш IP заблокирован для веб-скрапинга!')
                    print(f'     Статус: {_r.status_code} | Длина ответа: {len(_body)} байт')
                    if 'captcha' in _body.lower():
                        print(f'     Причина: ЦИАН вернул страницу капчи')
                    print(f'\n  ┌─────────────────────────────────────────────────────────┐')
                    print(f'  │  Решения:                                               │')
                    print(f'  │  1. Запустите скрипт с локальной машины / VPS           │')
                    print(f'  │  2. Настройте прокси:                                   │')
                    print(f'  │     a) env: ENRICH_PROXY=http://user:pass@host:port     │')
                    print(f'  │     b) файл scripts/.enrich_settings.json:              │')
                    print(f'  │        {{"proxy_url": "http://user:pass@host:port"}}      │')
                    print(f'  └─────────────────────────────────────────────────────────┘')
                    print(f'\n  ⏭️  Шаг 2 пропущен. Квартиры будут пустыми до решения проблемы с IP.')
                    cache['phase'] = 3
                    save_cache(cache)
                    phase = 3
                    pending_urls = []
                else:
                    print(f'  ✅ Pre-flight OK: ЦИАН доступен для скрапинга')
            except Exception as _e:
                print(f'  ⚠️  Pre-flight не удался: {_e} — продолжаем попытку...')

        for url in pending_urls:
            if _check_stop():
                save_cache(cache)
                return
            rotate_session_if_needed()
            page_data = scrape_jk_page(url)
            # Только сохраняем в кэш если получили хоть какие-то данные.
            # Пустой {} (блокировка, сбой) не кэшируем — следующий запуск повторит.
            if page_data:
                unique_jk_urls[url] = page_data
            photos_count   = len(page_data.get('jk_photos', []))
            layouts_count  = len(json.loads(page_data['layout_images'])) if page_data.get('layout_images') else 0
            has_desc  = '✅' if page_data.get('detailed_description') else '—'
            bldgs     = len(page_data.get('buildings', []))
            ceil_h    = page_data.get('ceiling_height', '—')
            floors    = f"{page_data.get('floors_min','?')}-{page_data.get('floors_max','?')}"
            logo      = '✅' if page_data.get('logo_url') else '—'
            # Show last meaningful segment of the URL (after stripping tracking params)
            _url_display = url.rstrip('/').split('/')[-1] or url[-40:]
            _url_display = _url_display[:42]
            print(f'  {_url_display:42} | ф:{photos_count:2d} | п:{layouts_count:2d} | д:{has_desc} | '
                  f'лит:{bldgs:2d} | потолки:{ceil_h:10} | эт:{floors} | лого:{logo}')
            cache['unique_jk_urls'] = unique_jk_urls
            save_cache(cache)
            time.sleep(REQUEST_DELAY)

        cache['phase'] = 3
        save_cache(cache)
        phase = 3

    # ── Шаг 1c: Поголовный сбор квартир по корпусам (geo.nb_house_key) ─────────
    # Каждый корпус ЖК имеет houseId → фильтр geo.nb_house_key РАБОТАЕТ (в отличие от newbuilding).
    # Phase 2 уже скрапила страницы ЖК и получила building_id (houseId) для каждого корпуса.
    # Здесь мы для каждого (jk_cian_id, house_id) забираем ВСЕ квартиры (до 54 стр × 28 = 1512 шт).
    if phase <= 3 and not cache.get('phase_1c_done'):
        print(f'\n🏢 Шаг 1c: Поголовный сбор по корпусам...')

        # Строим карту: {jk_cian_id: [(house_id, expected_count), ...]}
        nb_to_houses: dict = {}
        for jk_cian_id, jk_info in jk_search_data_int.items():
            jk_url = jk_info.get('jk_url')
            if not jk_url:
                continue
            page_data = unique_jk_urls.get(jk_url, {})
            for b in page_data.get('buildings', []):
                hid   = b.get('building_id')
                total = b.get('total_apartments') or 0
                if hid and total > 0:
                    nb_to_houses.setdefault(jk_cian_id, []).append((hid, total))

        total_buildings  = sum(len(v) for v in nb_to_houses.values())
        total_expected   = sum(t for v in nb_to_houses.values() for _, t in v)
        print(f'  ЖК: {len(nb_to_houses)}, корпусов: {total_buildings}, '
              f'ожидается квартир: {total_expected:,}')

        rc_map_1c = {cid: (row[0], row[3]) for cid, row in db_complexes.items()}
        _1c_written: set = set()
        _1c_new = 0
        processed = 0

        houses_done = set(cache.get('phase_1c_houses_done', []))

        for jk_cian_id, houses in nb_to_houses.items():
            for house_id, expected in houses:
                house_key = f'{jk_cian_id}_{house_id}'
                if house_key in houses_done:
                    continue
                processed += 1

                if _check_stop():
                    cache['phase_1c_houses_done'] = list(houses_done)
                    save_cache(cache)
                    return

                rotate_session_if_needed()
                offers = fetch_building_all_pages(int(jk_cian_id), house_id)

                before = len(apt_data_raw)
                _extract_from_offers(offers, jk_search_data_int, apt_data_raw)
                gained = len(apt_data_raw) - before
                _1c_new += gained
                pct = round(len(offers) / expected * 100) if expected else 0
                print(f'  [{processed}/{total_buildings}] '
                      f'ЖК {jk_cian_id} корп {house_id}: '
                      f'+{gained} кв ({len(offers)} получ / {expected} ожид, {pct}%)')

                houses_done.add(house_key)

                # Периодически сохраняем в БД
                if processed % 15 == 0 or processed == total_buildings:
                    new_apts = {k: v for k, v in apt_data_raw.items() if k not in _1c_written}
                    if new_apts:
                        try:
                            ins, upd, _, _pch = upsert_apartments(cur, new_apts, rc_map_1c)
                            conn.commit()
                            _1c_written.update(new_apts.keys())
                            print(f'  💾 1c: +{ins} новых, {upd} обновл. '
                                  f'(итого в прогоне: {len(_1c_written)})')
                        except Exception as e:
                            conn.rollback()
                            print(f'  ⚠️  1c запись: {e}')
                    # Освобождаем RAM после записи в БД
                    for _k1c in list(new_apts.keys()):
                        apt_data_raw.pop(_k1c, None)
                    import gc as _gc1c; _gc1c.collect()
                    cache['apt_data'] = {}   # Не кэшируем — квартиры уже в БД
                    cache['phase_1c_houses_done'] = list(houses_done)
                    save_cache(cache)

        # Финальная запись
        new_apts = {k: v for k, v in apt_data_raw.items() if k not in _1c_written}
        if new_apts:
            try:
                ins, upd, _, _pch = upsert_apartments(cur, new_apts, rc_map_1c)
                conn.commit()
                _1c_written.update(new_apts.keys())
                print(f'  💾 1c финал: +{ins} новых, {upd} обновл.')
                for _k1c in list(new_apts.keys()):
                    apt_data_raw.pop(_k1c, None)
                import gc as _gc1c_fin; _gc1c_fin.collect()
            except Exception as e:
                conn.rollback()
                print(f'  ⚠️  1c финал: {e}')

        print(f'  ✅ Phase 1c завершена: {_1c_new} новых квартир из {total_buildings} корпусов')
        cache['phase_1c_done'] = True
        cache['apt_data'] = {}   # Не кэшируем — квартиры уже в БД
        save_cache(cache)

    # ── Шаг 3: Скрапинг страниц застройщиков ──────────────────────────────────
    if phase <= 3:
        print(f'\n👤 Шаг 3: Скрапинг застройщиков...')

        # Загружаем имена агрегаторских застройщиков из БД для перепривязки
        _agg_dev_ids: set = set()
        _cur_tmp = conn.cursor()
        _cur_tmp.execute("""
            SELECT DISTINCT d.id FROM developers d
            JOIN residential_complexes rc ON rc.developer_id = d.id
            WHERE d.name ILIKE '%%магазин%%' OR d.name ILIKE '%%циан%%'
               OR d.external_id::text = ANY(%s)
        """, ([str(x) for x in AGGREGATOR_BUILDER_IDS],))
        _agg_dev_ids = {r[0] for r in _cur_tmp.fetchall()}
        _cur_tmp.close()

        dev_to_url = {}
        for jk_cian_id_str, row in db_complexes.items():
            rc_id, rc_name, complex_id_str, dev_id = row
            if not dev_id:
                continue
            # Для агрегаторских застройщиков также берём реальный URL
            sdata = jk_search_data_int.get(int(jk_cian_id_str), {})
            jk_url = sdata.get('jk_url')
            if jk_url and jk_url in unique_jk_urls:
                dev_cian_url = unique_jk_urls[jk_url].get('dev_cian_url')
                if dev_cian_url:
                    if dev_id in _agg_dev_ids:
                        # Реальный застройщик — запишем отдельно
                        dev_to_url[f'_relink_{jk_cian_id_str}'] = dev_cian_url
                    elif dev_id not in dev_to_url:
                        dev_to_url[dev_id] = dev_cian_url
                        continue
            if dev_id not in _agg_dev_ids:
                profile_uri = sdata.get('dev_profile_uri')
                if profile_uri and dev_id not in dev_to_url:
                    dev_to_url[dev_id] = profile_uri

        # Только числовые ключи — реальные developer_id
        pending_devs = [(did, url) for did, url in dev_to_url.items()
                        if isinstance(did, int) and url not in dev_page_cache]
        print(f'  Застройщиков: {len(pending_devs)} (в кэше: {len(dev_page_cache)})')

        for dev_id, dev_url in pending_devs:
            if _check_stop():
                save_cache(cache)
                return
            rotate_session_if_needed()
            pdata = scrape_developer_page(dev_url)
            dev_page_cache[dev_url] = pdata
            print(f'  {dev_url[:55]:55} → '
                  f'лого: {"✅" if pdata.get("logo_url") else "—"}, '
                  f'основан: {pdata.get("founded_year", "—")}')
            cache['dev_page_cache'] = dev_page_cache
            save_cache(cache)
            time.sleep(REQUEST_DELAY)

        # Для ЖК с developer_id=NULL: собираем страницы застройщиков через JK-страницу
        # (нужно для агрегаторских ЖК, ЖК без builder_id, И не-агрегаторов без dev_name)
        no_dev_extra_urls: set = set()

        # Также скрапим реальных застройщиков для ЖК, привязанных к агрегаторам
        for k, url in dev_to_url.items():
            if isinstance(k, str) and k.startswith('_relink_') and url not in dev_page_cache:
                no_dev_extra_urls.add(url)

        for jk_cian_id_str, row in db_complexes.items():
            _, _, _, dev_id = row
            if dev_id:
                continue
            sdata = jk_search_data_int.get(int(jk_cian_id_str), {})
            builder_id = sdata.get('builder_id')
            # Не-агрегаторов С именем застройщика в данных CIAN — страница не нужна
            if builder_id and int(builder_id) not in AGGREGATOR_BUILDER_IDS:
                if sdata.get('dev_name'):  # имя есть — создадим по builder_id без скрапинга
                    continue
                # Имени нет — нужно скрапить страницу застройщика чтобы получить имя+лого
            jk_url = sdata.get('jk_url')
            if jk_url and jk_url in unique_jk_urls:
                dev_cian_url = unique_jk_urls[jk_url].get('dev_cian_url')
                if dev_cian_url and dev_cian_url not in dev_page_cache:
                    no_dev_extra_urls.add(dev_cian_url)

        if no_dev_extra_urls:
            print(f'  Дополнительно (ЖК без застройщика, агрегаторы): {len(no_dev_extra_urls)}')
            for dev_url in no_dev_extra_urls:
                if _check_stop():
                    save_cache(cache)
                    return
                pdata = scrape_developer_page(dev_url)
                dev_page_cache[dev_url] = pdata
                print(f'  {dev_url[:55]:55} → '
                      f'лого: {"✅" if pdata.get("logo_url") else "—"}, '
                      f'основан: {pdata.get("founded_year", "—")}')
                cache['dev_page_cache'] = dev_page_cache
                save_cache(cache)
                time.sleep(REQUEST_DELAY)

        cache['phase'] = 4
        save_cache(cache)
        phase = 4

    # ── Шаг 4: Обновление БД ──────────────────────────────────────────────────
    print(f'\n💾 Шаг 4: Обновление БД...')

    # Агрегаторские developer_id — нужны и в Phase 4 (независимо от того, шла ли Phase 3)
    if '_agg_dev_ids' not in dir():
        _agg_dev_ids: set = set()
        _cur_tmp4 = conn.cursor()
        _cur_tmp4.execute("""
            SELECT DISTINCT d.id FROM developers d
            JOIN residential_complexes rc ON rc.developer_id = d.id
            WHERE d.name ILIKE '%%магазин%%' OR d.name ILIKE '%%циан%%'
               OR d.external_id::text = ANY(%s)
        """, ([str(x) for x in AGGREGATOR_BUILDER_IDS],))
        _agg_dev_ids = {r[0] for r in _cur_tmp4.fetchall()}
        _cur_tmp4.close()

    # Build dev_to_url map for this phase
    dev_to_url = {}
    for jk_cian_id_str, row in db_complexes.items():
        rc_id, rc_name, complex_id_str, dev_id = row
        if not dev_id:
            continue
        sdata = jk_search_data_int.get(int(jk_cian_id_str), {})
        jk_url = sdata.get('jk_url')
        if jk_url and jk_url in unique_jk_urls:
            dev_cian_url = unique_jk_urls[jk_url].get('dev_cian_url')
            if dev_cian_url:
                if dev_id in _agg_dev_ids:
                    dev_to_url[f'_relink_{jk_cian_id_str}'] = dev_cian_url
                else:
                    dev_to_url[dev_id] = dev_cian_url
                continue
        if dev_id not in _agg_dev_ids:
            profile_uri = sdata.get('dev_profile_uri')
            if profile_uri:
                dev_to_url[dev_id] = profile_uri

    jk_ok = 0
    jk_new = 0
    dev_ok = 0
    bldg_ok = 0
    dev_done = set()

    # ── 4a. Обновление существующих ЖК + их литеров ───────────────────────────
    for jk_cian_id_str, row in db_complexes.items():
        rc_id, rc_name, complex_id_str, dev_id = row
        jk_cian_id = int(jk_cian_id_str)

        sdata     = jk_search_data_int.get(jk_cian_id, {})
        jk_url    = sdata.get('jk_url')
        page_data = unique_jk_urls.get(jk_url, {}) if jk_url else {}

        if not sdata and not page_data:
            print(f'  ⏭️  {rc_name}: нет данных CIAN')
            continue

        update_complex_db(cur, rc_id, sdata, page_data)
        jk_ok += 1

        # Upsert buildings/литеры for this JK
        buildings = page_data.get('buildings', [])
        if buildings:
            cnt = upsert_buildings(cur, rc_id, buildings)
            bldg_ok += cnt

        # Update developer — или перепривязать если текущий застройщик агрегатор
        if dev_id and dev_id not in _agg_dev_ids and dev_id not in dev_done:
            builder_id = sdata.get('builder_id')
            dev_url = dev_to_url.get(dev_id)
            dev_pdata = dev_page_cache.get(dev_url, {}) if dev_url else {}
            update_developer_db(cur, dev_id, sdata, dev_pdata, builder_id)
            dev_done.add(dev_id)
            dev_ok += 1

        elif dev_id and dev_id in _agg_dev_ids:
            # ── ЖК привязан к агрегатору — перепривязываем к реальному застройщику ──
            relink_url = dev_to_url.get(f'_relink_{jk_cian_id_str}')
            if relink_url:
                dev_pdata = dev_page_cache.get(relink_url, {})
                real_name = dev_pdata.get('full_name') or dev_pdata.get('name')
                if real_name:
                    dev_slug = _slugify(real_name)[:199]
                    m_bid = re.search(r'-(\d+)/?$', relink_url)
                    real_ext_id = m_bid.group(1) if m_bid else None
                    dev_logo = dev_pdata.get('logo_url')
                    cur.execute("""
                        INSERT INTO developers (name, slug, external_id, logo_url, source_url, is_active, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, TRUE, NOW(), NOW())
                        ON CONFLICT (slug) DO UPDATE SET
                            external_id=COALESCE(EXCLUDED.external_id, developers.external_id),
                            logo_url=COALESCE(EXCLUDED.logo_url, developers.logo_url),
                            updated_at=NOW()
                        RETURNING id
                    """, (real_name[:199], dev_slug, real_ext_id, dev_logo, relink_url[:499]))
                    real_dev_row = cur.fetchone()
                    if real_dev_row:
                        real_dev_id = real_dev_row[0]
                        cur.execute("UPDATE residential_complexes SET developer_id=%s WHERE id=%s", (real_dev_id, rc_id))
                        print(f'  🔀 {rc_name}: агрегатор → {real_name} (id={real_dev_id})')
                        dev_ok += 1

        elif not dev_id:
            # ── Привязываем застройщика к ЖК у которых developer_id=NULL ──────
            builder_id = sdata.get('builder_id')
            new_dev_id = None

            if builder_id and int(builder_id) not in AGGREGATOR_BUILDER_IDS:
                # Не-агрегатор: ищем по external_id
                cur.execute(
                    "SELECT id FROM developers WHERE external_id = %s LIMIT 1",
                    (str(builder_id),)
                )
                dev_row = cur.fetchone()
                if dev_row:
                    new_dev_id = dev_row[0]
                else:
                    # Создаём нового застройщика
                    dev_name = sdata.get('dev_name') or page_data.get('developer_name')
                    # Если имя не в данных поиска — пробуем из скрапленной страницы застройщика
                    dev_cian_url_nb = (unique_jk_urls.get(jk_url, {}).get('dev_cian_url') if jk_url else None)
                    dev_pdata_nb = dev_page_cache.get(dev_cian_url_nb, {}) if dev_cian_url_nb else {}
                    if not dev_name:
                        dev_name = dev_pdata_nb.get('full_name') or dev_pdata_nb.get('name')
                    if dev_name:
                        now_dt = datetime.now()
                        dev_slug = _slugify(dev_name)[:199]
                        dev_logo_nb = dev_pdata_nb.get('logo_url') or (unique_jk_urls.get(jk_url, {}).get('logo_url') if jk_url else None)
                        cur.execute("""
                            INSERT INTO developers
                                (name, slug, external_id, logo_url, is_active, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, TRUE, %s, %s)
                            ON CONFLICT (slug) DO UPDATE SET
                                external_id=EXCLUDED.external_id,
                                logo_url=COALESCE(EXCLUDED.logo_url, developers.logo_url)
                            RETURNING id
                        """, (dev_name[:199], dev_slug, str(builder_id), dev_logo_nb, now_dt, now_dt))
                        new_row = cur.fetchone()
                        if new_row:
                            new_dev_id = new_row[0]
                            print(f'  ➕ Застройщик "{dev_name}" создан id={new_dev_id} (builder={builder_id}) лого:{"✅" if dev_logo_nb else "—"}')
            else:
                # Агрегатор или нет builder_id — ищем реального застройщика
                # по dev_cian_url со страницы ЖК (скрапленной в Phase 2/3)
                if jk_url and jk_url in unique_jk_urls:
                    dev_cian_url = unique_jk_urls[jk_url].get('dev_cian_url')
                    if dev_cian_url:
                        dev_pdata = dev_page_cache.get(dev_cian_url, {})
                        dev_name = dev_pdata.get('full_name') or dev_pdata.get('name')
                        if dev_name:
                            cur.execute(
                                "SELECT id FROM developers WHERE source_url = %s OR name = %s LIMIT 1",
                                (dev_cian_url, dev_name)
                            )
                            dev_row = cur.fetchone()
                            if dev_row:
                                new_dev_id = dev_row[0]
                            else:
                                now_dt = datetime.now()
                                dev_slug2 = _slugify(dev_name)[:199]
                                cur.execute("""
                                    INSERT INTO developers
                                        (name, slug, source_url, is_active, created_at, updated_at)
                                    VALUES (%s, %s, %s, TRUE, %s, %s)
                                    ON CONFLICT (slug) DO UPDATE SET source_url=EXCLUDED.source_url RETURNING id
                                """, (dev_name[:199], dev_slug2, dev_cian_url[:499], now_dt, now_dt))
                                new_row = cur.fetchone()
                                if new_row:
                                    new_dev_id = new_row[0]
                                    print(f'  ➕ Застройщик "{dev_name}" создан (через ЖК-страницу, id={new_dev_id})')

            if new_dev_id:
                cur.execute(
                    "UPDATE residential_complexes SET developer_id=%s WHERE id=%s",
                    (new_dev_id, rc_id)
                )
                if new_dev_id not in dev_done:
                    dev_url = dev_to_url.get(new_dev_id)
                    dev_pdata = dev_page_cache.get(dev_url, {}) if dev_url else {}
                    update_developer_db(cur, new_dev_id, sdata, dev_pdata, builder_id)
                    dev_done.add(new_dev_id)
                    dev_ok += 1
                print(f'  🔗 {rc_name[:30]}: привязан застройщик id={new_dev_id}')

    # ── 4b. Вставка новых ЖК из CIAN ─────────────────────────────────────────
    known_cian_ids = set(str(k) for k in db_complexes.keys())
    new_jk_candidates = {
        jk_id: sdata for jk_id, sdata in jk_search_data_int.items()
        if str(jk_id) not in known_cian_ids and sdata.get('jk_name')
    }
    if new_jk_candidates and CREATE_NEW_JK:
        _total_new = len(new_jk_candidates)
        # Узнаём сколько уже было обработано в прошлом прогоне (для resume-сообщения)
        _already_done = len(db_complexes) - (len(db_complexes) - len(
            {k for k in db_complexes if k not in {str(j) for j in new_jk_candidates}}
        ))
        print(f'\n🆕 Новых ЖК (нет в БД): {_total_new}')
        _jk_idx = 0
        for jk_cian_id, sdata in new_jk_candidates.items():
            _jk_idx += 1
            jk_url    = sdata.get('jk_url')
            page_data = unique_jk_urls.get(jk_url, {}) if jk_url else {}
            rc_name = sdata.get('jk_name', '')

            # ── Bbox-guard: если координаты явно вне города — пропускаем ──
            _rc_lat = page_data.get('latitude') or sdata.get('latitude')
            _rc_lon = page_data.get('longitude') or sdata.get('longitude')
            if _rc_lat and _rc_lon and not _city_bbox_ok(_rc_lat, _rc_lon):
                print(f'  ⛔ Пропущен (вне bbox города lat={_rc_lat:.4f} lon={_rc_lon:.4f}): "{rc_name[:40]}"')
                continue

            new_rc_id = insert_new_complex(cur, jk_cian_id, sdata, page_data, CITY_ID)
            if new_rc_id:
                update_complex_db(cur, new_rc_id, sdata, page_data)
                jk_new += 1

                # Привязываем застройщика к новому ЖК (если не агрегатор)
                new_dev_id = None
                builder_id = sdata.get('builder_id')
                if builder_id and int(builder_id) not in AGGREGATOR_BUILDER_IDS:
                    builder_id_str = str(builder_id)
                    cur.execute(
                        "SELECT id FROM developers WHERE external_id = %s LIMIT 1",
                        (builder_id_str,)
                    )
                    dev_row = cur.fetchone()
                    if dev_row:
                        new_dev_id = dev_row[0]
                        cur.execute(
                            "UPDATE residential_complexes SET developer_id=%s WHERE id=%s",
                            (new_dev_id, new_rc_id)
                        )
                    else:
                        # Застройщика нет в БД — создаём
                        dev_name = sdata.get('dev_name')
                        jk_url_nd = sdata.get('jk_url')
                        dev_cian_url_nd = (unique_jk_urls.get(jk_url_nd, {}).get('dev_cian_url')
                                           if jk_url_nd else None)
                        dev_pdata_nd = dev_page_cache.get(dev_cian_url_nd, {}) if dev_cian_url_nd else {}
                        if not dev_name:
                            dev_name = dev_pdata_nd.get('full_name') or dev_pdata_nd.get('name')
                        if not dev_name:
                            dev_logo_nd = page_data.get('logo_url')
                            dev_name = page_data.get('developer_name')
                        else:
                            dev_logo_nd = dev_pdata_nd.get('logo_url') or page_data.get('logo_url')
                        if dev_name:
                            now_dt = datetime.now()
                            dev_slug_nd = _slugify(dev_name)[:199]
                            cur.execute("""
                                INSERT INTO developers
                                    (name, slug, external_id, logo_url, source_url,
                                     is_active, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s)
                                ON CONFLICT (slug) DO UPDATE SET
                                    external_id = COALESCE(EXCLUDED.external_id, developers.external_id),
                                    logo_url    = COALESCE(EXCLUDED.logo_url, developers.logo_url),
                                    updated_at  = EXCLUDED.updated_at
                                RETURNING id
                            """, (dev_name[:199], dev_slug_nd, builder_id_str,
                                  dev_logo_nd, dev_cian_url_nd, now_dt, now_dt))
                            nd_row = cur.fetchone()
                            if nd_row:
                                new_dev_id = nd_row[0]
                                cur.execute(
                                    "UPDATE residential_complexes SET developer_id=%s WHERE id=%s",
                                    (new_dev_id, new_rc_id)
                                )
                                print(f'  ➕ Застройщик "{dev_name}" создан id={new_dev_id} '
                                      f'(builder={builder_id}) лого:{"✅" if dev_logo_nd else "—"}')

                # Add to db_complexes so apartments can be linked
                db_complexes[str(jk_cian_id)] = (new_rc_id, rc_name, str(jk_cian_id), new_dev_id)
                # Upsert buildings for new JK too
                buildings = page_data.get('buildings', [])
                if buildings:
                    cnt = upsert_buildings(cur, new_rc_id, buildings)
                    bldg_ok += cnt

                # Коммитим каждый ЖК сразу — при падении и перезапуске
                # уже вставленные ЖК окажутся в db_complexes и будут пропущены
                conn.commit()
                print(f'  ✅ [{_jk_idx}/{_total_new}] ЖК "{rc_name[:40]}" (CIAN={jk_cian_id}) сохранён id={new_rc_id}')

    conn.commit()

    # ── 4c. Вставка квартир ───────────────────────────────────────────────────
    # apt_data_raw может быть пустым — квартиры уже записаны в БД через _save_1b
    # (экономия RAM: в Phase 1b они удаляются из словаря после каждого батча)
    _4c_count = len(apt_data_raw)
    if _4c_count > 0:
        print(f'\n🏠 Шаг 4c: Запись квартир в БД ({_4c_count} дополнительных)...')

        # Rebuild rc_map after possible new JK inserts
        cur.execute("""
            SELECT rc.id, rc.complex_id, rc.developer_id
            FROM residential_complexes rc
            WHERE rc.city_id = %s AND rc.complex_id IS NOT NULL
        """, (CITY_ID,))
        rc_map = {row[1]: (row[0], row[2]) for row in cur.fetchall()}

        # Upsert apartments in batches of 500 for progress reporting
        batch_size = 500
        apt_items_4c = list(apt_data_raw.items())
        total_inserted = total_updated = total_skipped = 0
        all_price_changes = []

        for i in range(0, len(apt_items_4c), batch_size):
            batch = dict(apt_items_4c[i:i+batch_size])
            ins, upd, skip, pch = upsert_apartments(cur, batch, rc_map)
            total_inserted += ins
            total_updated  += upd
            total_skipped  += skip
            all_price_changes.extend(pch)
            conn.commit()
            pct = min(100, round((i + len(batch)) / max(len(apt_items_4c), 1) * 100))
            print(f'  [{pct:3d}%] Квартир: +{total_inserted} новых, '
                  f'~{total_updated} обновлено, пропущено:{total_skipped}')

        # ── 4c.1 Фиксируем изменения цен в price_history ──────────────────────
        record_price_history_batch(cur, conn, all_price_changes)
    else:
        print(f'\n🏠 Шаг 4c: пропущен — квартиры уже записаны в БД через Phase 1b/1c')

    # ── 4d. Пометка проданных/снятых квартир ──────────────────────────────────
    # _all_1b_ids содержит все ЦИАН-ID собранные в Phase 1b (без хранения данных в RAM)
    # Добавляем любые оставшиеся в apt_data_raw (например из Phase 1c)
    _seen_for_mark_sold = _all_1b_ids | set(apt_data_raw.keys())
    mark_sold(cur, conn, CITY_ID, _seen_for_mark_sold)

    # ── 4d.1 Снапшот цен по ЖК (ежемесячный агрегат) ─────────────────────────
    print(f'\n📊 Снапшот цен ЖК...')
    snapshot_complex_prices(cur, conn, CITY_ID)

    # ── 4e. Геокодинг ЖК из координат квартир ─────────────────────────────────
    print(f'\n📍 Шаг 4e: Геокодинг ЖК...')
    geo_updated = geocode_from_apartments(cur, conn) or 0

    conn.close()

    # Total apartments in DB for this city
    # total_inserted/total_updated могут быть не определены если шаг 4c был пропущен
    if 'total_inserted' not in dir():
        total_inserted = total_updated = total_skipped = 0
    try:
        _stat_cur = conn_stat = None
        import psycopg2 as _pg2
        _db_url = os.environ.get('DATABASE_URL', '')
        conn_stat = _pg2.connect(_db_url)
        _stat_cur = conn_stat.cursor()
        _stat_cur.execute(
            "SELECT count(*) FROM properties p "
            "JOIN residential_complexes rc ON rc.id=p.complex_id "
            "WHERE rc.city_id=%s", (CITY_ID,))
        total_in_db = _stat_cur.fetchone()[0]
        conn_stat.close()
    except Exception:
        total_in_db = total_inserted + total_updated

    print(f'\n{"="*60}')
    print(f'✅ Готово!')
    print(f'   ЖК обновлено:  {jk_ok}')
    print(f'   ЖК новых:      {jk_new}')
    print(f'   Литеров:       {bldg_ok}')
    print(f'   Квартир в базе:{total_in_db} (новых:{total_inserted}, обновл:{total_updated})')
    print(f'   Застройщиков:  {dev_ok}')
    print(f'   Геокодировано: {geo_updated} ЖК')
    print(f'{"="*60}')

    # ── Пост-обработка: очистка устаревших объектов ───────────────────────────
    # Запускаем cleanup_vanished_properties после каждого полного скрапа.
    # Это дополнительный слой защиты помимо mark_sold() — удаляет объекты,
    # которые не появлялись в последних 7+ парсинговых запусках.
    try:
        import subprocess
        cleanup_script = os.path.join(os.path.dirname(__file__), 'cleanup_vanished_properties.py')
        if os.path.exists(cleanup_script):
            print(f'\n🧹 Запуск cleanup_vanished_properties (city_id={CITY_ID}, days=7)...')
            result = subprocess.run(
                ['python3', cleanup_script, '--city', str(CITY_ID), '--days', '7'],
                capture_output=True, text=True, timeout=300
            )
            if result.stdout:
                print(result.stdout)
            if result.returncode != 0 and result.stderr:
                print(f'⚠️  cleanup stderr: {result.stderr[:500]}')
    except Exception as _e:
        print(f'⚠️  Не удалось запустить cleanup_vanished_properties: {_e}')


if __name__ == '__main__':
    main()
