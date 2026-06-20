"""
Скрипт обогащения УТП из сайтов застройщиков.
Использование:
  python3 scripts/enrich_utp_from_sites.py --complex_id 338
  python3 scripts/enrich_utp_from_sites.py --all
  python3 scripts/enrich_utp_from_sites.py --list    # показать список комплексов
"""
import sys, os, json, re, argparse, time, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# ── URL mapping: complex_id → developer site ──────────────────────────────────
COMPLEX_SOURCES = {
    326: {"name": "Самолет",               "url": "https://dogma.ru/projects/samolet"},
    210: {"name": "Народные Кварталы",     "url": "https://narodnye-kvartaly.ru/"},
    207: {"name": "Дом 101",               "url": "https://gk-nvm.ru/obekty/zhk-dom-101"},
    338: {"name": "Первое место",          "url": "https://tochno.life/krasnodar/pervoe-mesto/kvartiri/",
          "video": "https://tochno.life/file/complexesVideo/1636/1762752349804.mp4"},
    208: {"name": "Форма",                 "url": "https://gk-nvm.ru/obekty/forma"},
    322: {"name": "Парк Победы - 2",       "url": "https://park-pobedy.dogma.ru/"},
    323: {"name": "ДОГМА ПАРК",            "url": "https://dogma.ru/projects/dogma-park"},
    231: {"name": "Образцово",             "url": "https://incitystroy.ru/projects/obrazcovo",
          "video": "https://incitystroy.ru/storage/e2/ee/621/e2eede113ba01f962a04b78a1c0d6da51a8a6aa8.mp4"},
    337: {"name": "Родные Просторы",       "url": "https://tochno.life/krasnodar/rodnye-prostory/kvartiri/",
          "video": "https://tochno.life/file/complexesVideo/71/1744008288374.mp4"},
    228: {"name": "Рекорд",                "url": "https://dogma.ru/projects/record2"},
    219: {"name": "Теплые края",           "url": "https://xn--80ajpctjj8ewbm.xn--p1ai/"},
    315: {"name": "Патрики",               "url": "https://tochno.life/krasnodar/patriki/kvartiri/",
          "video": "https://tochno.life/file/complexesVideo/1134/1747820521120.mp4"},
    233: {"name": "Иначе",                 "url": "https://xn--80akhu5c.xn--p1ai/"},
    280: {"name": "Зеленая территория",    "url": "https://ztkrd.ru/"},
    221: {"name": "БОТАНИКА",             "url": "https://usi-botanica.ru/"},
    290: {"name": "Смородина",             "url": "https://avadom.ru/objects/smorodina/"},
    229: {"name": "Архитектор",            "url": "https://kvartal-architect.ru/"},
    214: {"name": "Грейд",                 "url": "https://dogma.ru/projects/grade"},
    222: {"name": "Все свои Vip",          "url": "https://vsesvoivip.ru/"},
    232: {"name": "Коллекция",             "url": "https://gk-nvm.ru/obekty/collection"},
    297: {"name": "Лето",                  "url": "https://darstroy-yug.ru/projects/zhk-leto/"},
    303: {"name": "Парк у дома",           "url": "https://vkbn.ru/projects/park-u-doma/"},
    289: {"name": "Огурцы",                "url": "https://jkogurcy.ru/"},
    224: {"name": "Фонтаны",              "url": "https://sskuban.ru/fontany"},
    278: {"name": "Друзья",               "url": "https://xn----htbegm2bv7e1a.xn--p1ai/"},
    299: {"name": "Отражение",            "url": "https://xn----htbegm2bv7e1a.xn--p1ai/"},
    225: {"name": "Новая Елизаветка",     "url": "https://incitystroy.ru/projects/elizavetka"},
    291: {"name": "ЮГГЕ",                  "url": "https://yugge.ru/"},
    # Grinн Apple — добавить вручную ID когда будет в БД
}

# ── Scrapers ──────────────────────────────────────────────────────────────────
def _headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }

def fetch_html(url, timeout=15):
    import requests
    try:
        r = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or 'utf-8'
        return r.text
    except Exception as e:
        log.warning(f"Fetch failed {url}: {e}")
        return None

def parse_tochno_life(html, url):
    """tochno.life — «Преимущества» секция"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    features = []
    # Look for advantage/feature blocks
    for section in soup.find_all(['section', 'div'], class_=re.compile(r'advantage|feature|benefit|utp|plus', re.I)):
        items = section.find_all(['li', 'div', 'article'], recursive=False)
        if not items:
            items = section.find_all(['li', 'div', 'article'])
        for item in items[:12]:
            img_tag = item.find('img')
            title_tag = item.find(['h3', 'h4', 'strong', 'p', 'span'], class_=re.compile(r'title|name|head|label', re.I))
            if not title_tag:
                title_tag = item.find(['h3', 'h4', 'strong'])
            desc_tag = item.find('p')
            if title_tag and title_tag.get_text(strip=True):
                img_url = ''
                if img_tag:
                    img_url = img_tag.get('src') or img_tag.get('data-src') or ''
                    if img_url and img_url.startswith('/'):
                        from urllib.parse import urlparse
                        p = urlparse(url)
                        img_url = f"{p.scheme}://{p.netloc}{img_url}"
                name = title_tag.get_text(strip=True)[:80]
                desc = ''
                if desc_tag and desc_tag != title_tag:
                    desc = desc_tag.get_text(strip=True)[:300]
                if name and len(name) > 2:
                    features.append({"name": name, "image": img_url, "description": desc})
    return features

def parse_dogma(html, url):
    """dogma.ru — секция с карточками проекта"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    features = []
    for block in soup.find_all(['div', 'article'], class_=re.compile(r'advantage|benefit|feature|card|item', re.I)):
        items = block.find_all(['li', 'div', 'article'], recursive=False) or [block]
        for item in items[:12]:
            img_tag = item.find('img')
            title_tag = item.find(['h2', 'h3', 'h4', 'strong', 'span'], class_=re.compile(r'title|name|header', re.I)) or item.find(['h2','h3','h4','strong'])
            desc_tag = item.find('p')
            if title_tag:
                name = title_tag.get_text(strip=True)[:80]
                img_url = ''
                if img_tag:
                    img_url = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src') or ''
                    if img_url and img_url.startswith('/'):
                        from urllib.parse import urlparse
                        p = urlparse(url)
                        img_url = f"{p.scheme}://{p.netloc}{img_url}"
                desc = ''
                if desc_tag and desc_tag != title_tag:
                    desc = desc_tag.get_text(strip=True)[:300]
                if name and len(name) > 2:
                    features.append({"name": name, "image": img_url, "description": desc})
    return features

def parse_generic(html, url):
    """Generic parser — ищет секции с заголовками типа Преимущества/Особенности/УТП"""
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse
    soup = BeautifulSoup(html, 'html.parser')
    features = []
    base = urlparse(url)

    # Find sections headed by keywords
    keywords = ['преимущества', 'особенности', 'уникальность', 'почему', 'инфраструктур', 'advantage', 'features', 'benefits']
    target_section = None
    for tag in soup.find_all(['h1','h2','h3','h4','section']):
        txt = tag.get_text(strip=True).lower()
        if any(k in txt for k in keywords):
            target_section = tag.find_parent(['section','div']) or tag.find_next_sibling()
            if target_section:
                break

    container = target_section or soup.body or soup
    # Collect items with image + text pairs
    seen = set()
    for item in (container.find_all(['li', 'article']) or container.find_all('div', class_=re.compile(r'item|card|feature|advantage|block', re.I)))[:16]:
        img = item.find('img')
        title = item.find(['h2','h3','h4','strong','b'])
        if not title:
            spans = item.find_all('span')
            title = spans[0] if spans else None
        p = item.find('p')
        if not title:
            continue
        name = title.get_text(strip=True)[:80]
        if not name or name in seen or len(name) < 3:
            continue
        seen.add(name)
        img_url = ''
        if img:
            img_url = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or ''
            if img_url and not img_url.startswith('http'):
                img_url = f"{base.scheme}://{base.netloc}{img_url}" if img_url.startswith('/') else ''
        desc = ''
        if p and p != title:
            desc = p.get_text(strip=True)[:300]
        features.append({"name": name, "image": img_url, "description": desc})
    return features

def scrape_features(url):
    """Scrape features from developer site"""
    html = fetch_html(url)
    if not html:
        return []
    host = url.split('/')[2].lower()
    if 'tochno.life' in host:
        features = parse_tochno_life(html, url)
    elif 'dogma.ru' in host:
        features = parse_dogma(html, url)
    else:
        features = parse_generic(html, url)
    # Deduplicate by name
    seen = set()
    result = []
    for f in features:
        if f['name'] not in seen and f['name']:
            seen.add(f['name'])
            result.append(f)
    return result[:12]  # max 12 UTPs

# ── DB update ─────────────────────────────────────────────────────────────────
def update_complex(complex_id, source, dry_run=False):
    from app import app, db
    from sqlalchemy import text

    url = source['url']
    log.info(f"Processing {source['name']} (id={complex_id}): {url}")

    features = scrape_features(url)
    log.info(f"  Found {len(features)} features")

    if not features:
        log.warning(f"  No features found for {source['name']}")
        return False

    with app.app_context():
        if dry_run:
            log.info(f"  DRY RUN — would save: {json.dumps(features, ensure_ascii=False, indent=2)}")
            return True

        # Merge with existing features (keep existing if scrape fails to improve)
        existing = db.session.execute(
            text('SELECT complex_features FROM residential_complexes WHERE id=:id'), {'id': complex_id}
        ).fetchone()
        existing_features = []
        if existing and existing[0]:
            try:
                existing_features = json.loads(existing[0]) if isinstance(existing[0], str) else existing[0]
            except Exception:
                pass

        # If we found more features, use new; otherwise keep existing
        final_features = features if len(features) >= len(existing_features) else existing_features

        db.session.execute(
            text('UPDATE residential_complexes SET complex_features=:f WHERE id=:id'),
            {'f': json.dumps(final_features, ensure_ascii=False), 'id': complex_id}
        )

        # Add video if provided in source
        if source.get('video'):
            vid_row = db.session.execute(
                text('SELECT videos FROM residential_complexes WHERE id=:id'), {'id': complex_id}
            ).fetchone()
            existing_vids = json.loads(vid_row[0]) if vid_row and vid_row[0] else []
            existing_urls = {v.get('url') for v in existing_vids}
            if source['video'] not in existing_urls:
                existing_vids.append({'type': 'direct', 'url': source['video'], 'title': f'{source["name"]} — видео'})
                db.session.execute(
                    text('UPDATE residential_complexes SET videos=:v WHERE id=:id'),
                    {'v': json.dumps(existing_vids, ensure_ascii=False), 'id': complex_id}
                )

        db.session.commit()
        log.info(f"  ✓ Saved {len(final_features)} features for {source['name']}")
    return True

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Enrich UTP features from developer websites')
    parser.add_argument('--complex_id', type=int, help='Enrich specific complex by ID')
    parser.add_argument('--all', action='store_true', help='Enrich all complexes in mapping')
    parser.add_argument('--list', action='store_true', help='List all complexes in mapping')
    parser.add_argument('--dry_run', action='store_true', help='Print results without saving to DB')
    parser.add_argument('--delay', type=float, default=3.0, help='Delay between requests (default 3s)')
    args = parser.parse_args()

    if args.list:
        print(f"\n{'ID':>6}  {'Название':<35} {'URL'}")
        print('-' * 90)
        for cid, src in sorted(COMPLEX_SOURCES.items(), key=lambda x: x[1]['name']):
            print(f"{cid:>6}  {src['name']:<35} {src['url']}")
        print(f"\nВсего: {len(COMPLEX_SOURCES)} комплексов")
        return

    if args.complex_id:
        if args.complex_id not in COMPLEX_SOURCES:
            log.error(f"complex_id={args.complex_id} не найден в маппинге. Используй --list для списка.")
            sys.exit(1)
        update_complex(args.complex_id, COMPLEX_SOURCES[args.complex_id], dry_run=args.dry_run)

    elif args.all:
        ok, fail = 0, 0
        for cid, src in sorted(COMPLEX_SOURCES.items()):
            try:
                result = update_complex(cid, src, dry_run=args.dry_run)
                if result:
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                log.error(f"Error for {src['name']}: {e}")
                fail += 1
            if not args.dry_run:
                time.sleep(args.delay)
        log.info(f"\nГотово: {ok} успешно, {fail} с ошибками")
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
