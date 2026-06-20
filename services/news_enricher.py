"""
News Enricher Service — scrapes full real estate articles from working sources,
uniqualizes content, fills SEO fields, saves to BlogPost.

Strategy:
  - SCRAPER sources: crawl article listing page → extract URLs → scrape each page
  - RSS sources: parse RSS → for each item, scrape the full article page
               (or use <content:encoded> if the feed includes full HTML)

Works without OpenAI (smart mode) or with it (openai mode).

Verified working sources (June 2026):
  IRN.ru        — scraper, post-view-body container, 20+ articles
  БН.ру         — scraper, bn-article__text container
  РИА Недвижимость — RSS 100 items, article__text div blocks
  Ведомости     — RSS 200 items, proper <p> tags in article pages
  ТАСС          — RSS 99 items, article text in <p> tags
"""
import os
import re
import json
import ssl
import hashlib
import logging
import datetime
import random
import time
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────
_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _fetch(url: str, timeout: int = 12) -> str:
    """Fetch URL, return decoded text or '' on error."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            raw = r.read()
            enc = r.headers.get_content_charset('utf-8')
            return raw.decode(enc, errors='ignore')
    except Exception as e:
        logger.debug(f'fetch error {url}: {e}')
        return ''


# ─────────────────────────────────────────────────────────────
# Source definitions
# ─────────────────────────────────────────────────────────────
# type: 'scraper' = crawl listing page for article links
#       'rss'     = parse RSS feed for article links
#
# article_selector:
#   'div.CLASS'  → look for <div class="...CLASS..."> container, then <p> inside
#   'div_each.CLASS' → each matching div IS a paragraph (e.g. RIA article__text)
#   'p'          → extract all <p> tags (generic fallback)

RSS_SOURCES = [
    {
        'name': 'IRN.ru — Новости',
        'type': 'scraper',
        'listing_urls': [
            'https://www.irn.ru/news/',
            'https://www.irn.ru/news/?page=2',
        ],
        'base_url': 'https://www.irn.ru',
        'link_pattern': r'/news/\d+[-\w]+\.html',
        'article_selector': 'div.post-view-body',
        'category': 'Новости рынка',
        'status': 'active',
    },
    {
        'name': 'IRN.ru — Аналитика',
        'type': 'scraper',
        'listing_urls': [
            'https://www.irn.ru/articles/',
        ],
        'base_url': 'https://www.irn.ru',
        'link_pattern': r'/articles/\d+[-\w]+\.html',
        'article_selector': 'div.post-view-body',
        'category': 'Аналитика рынка',
        'status': 'active',
    },
    {
        'name': 'БН.ру — Газета',
        'type': 'scraper',
        'listing_urls': [
            'https://www.bn.ru/gazeta/articles/',
            'https://www.bn.ru/gazeta/articles/page/2/',
        ],
        'base_url': 'https://www.bn.ru',
        'link_pattern': r'/gazeta/articles/(\d+)/',
        'link_prefix': 'https://www.bn.ru/gazeta/articles/{}/|id',
        'article_selector': 'p',
        'category': 'Рынок недвижимости',
        'status': 'active',
    },
    {
        'name': 'РИА Недвижимость',
        'type': 'rss',
        'rss_url': 'https://realty.ria.ru/export/rss2/archive/index.xml',
        'base_url': 'https://realty.ria.ru',
        # RIA uses div.article__text blocks — each div IS one paragraph
        'article_selector': 'div_each.article__text',
        'category': 'Новости рынка',
        'status': 'active',
    },
    {
        'name': 'Ведомости — Недвижимость',
        'type': 'rss',
        'rss_url': 'https://www.vedomosti.ru/rss/rubric/realty',
        'base_url': 'https://www.vedomosti.ru',
        'article_selector': 'p',
        'category': 'Новости рынка',
        'status': 'active',
    },
    {
        'name': 'ТАСС — Недвижимость',
        'type': 'rss',
        'rss_url': 'https://tass.ru/rss/v2.xml',
        'base_url': 'https://tass.ru',
        # Filter only nedvizhimost section links
        'rss_filter_url': 'tass.ru/nedvizhimost',
        'article_selector': 'p',
        'category': 'Новости рынка',
        'status': 'active',
    },
    # ── Telegram public channels (parsed via t.me/s/CHANNEL)
    {
        'name': 'Telegram: Недвижимость 2024',
        'type': 'telegram',
        'tg_channel': 'nedvizhimost2024',
        'category': 'Новости рынка',
        'status': 'active',
    },
    {
        'name': 'Telegram: Новостройки Москвы',
        'type': 'telegram',
        'tg_channel': 'msk_novostroyki',
        'category': 'Новости рынка',
        'status': 'active',
    },
]

# ─────────────────────────────────────────────────────────────
# Relevance filtering
# ─────────────────────────────────────────────────────────────
REAL_ESTATE_KEYWORDS = [
    'недвижимость', 'квартир', 'новостройк', 'ипотек', 'жилье', 'жильё',
    'застройщик', 'жилой комплекс', 'жк', 'кредит', 'ставк', 'покупк',
    'продаж', 'аренд', 'краснодар', 'сочи', 'кубань', 'инвестиц',
    'льготн', 'семейн', 'эскроу', 'жилищ', 'стройк',
    'девелопер', 'площадь', 'объект', 'рынок жилья', 'дом.рф',
    'строительств', 'минстро', 'рассрочк', 'ключевая ставк',
]

_SKIP_STARTS = (
    'Подписаться', 'Читайте также', 'Подпишитесь', 'Реклама',
    'Теги:', 'Поделиться', 'Комментари', 'Все права', 'По материалам',
    'Источник:', 'Редакция', 'Предыдущая', 'Следующая', 'Материал подготовлен',
    'МОСКВА, ', 'Санкт-Петербург, ',
)

# Dateline pattern: "СОЧИ, 18 июн - РИА Недвижимость. Текст..."
# Also: "Москва, 18 июня /РИА/" or "МОСКВА, 18 июня - ТАСС."
_DATELINE_RE = re.compile(
    r'^[А-ЯЁ][А-ЯЁа-яёa-z\-]+,?\s+\d{1,2}\s+\w{3,4}\.?\s*[-–—/]',
    re.IGNORECASE
)

_SKIP_CONTAINS = (
    '© РИА', '© ТАСС', '© Интерфакс', 'irn.ru', 'ria.ru', 'tass.ru',
    'При использовании материалов', 'Перепечатка', 'realty.ria.ru',
    'All rights reserved', 'РИА Новости',
)


def _is_relevant(text: str) -> bool:
    tl = text.lower()
    return any(kw in tl for kw in REAL_ESTATE_KEYWORDS)


def _clean_paragraph(raw: str) -> str:
    """Strip HTML tags, entities, extra whitespace from a paragraph."""
    t = re.sub(r'<[^>]+>', '', raw)
    t = re.sub(r'&nbsp;', ' ', t)
    t = re.sub(r'&mdash;', '—', t)
    t = re.sub(r'&laquo;', '«', t)
    t = re.sub(r'&raquo;', '»', t)
    t = re.sub(r'&[a-z#0-9]+;', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    # Strip dateline prefix: "СОЧИ, 18 июн - РИА Недвижимость. " or "МОСКВА, 18 июня /ТАСС/ - "
    t = re.sub(
        r'^[А-ЯЁ][А-ЯЁа-яё\-]+,?\s+\d{1,2}\s+\w{3,4}\.?\s*[-–—/][^.]{0,60}[./]\s*',
        '', t
    ).strip()
    return t


_TG_ARROW_RE = re.compile(r'[↑↓←→⬆⬇➡⬅▲▼🔝🔻🔺]')
_TG_EMOJI_RE = re.compile(r'[\U0001F000-\U0001FFFF\u2600-\u27FF\u2B00-\u2BFF]')


def _is_tg_decorator(para: str) -> bool:
    """True if text is a Telegram channel decorator: MAX↓, emoji-only lines, etc."""
    stripped = para.strip()
    if not stripped:
        return True
    # Short line (<50 chars) containing directional arrows → CTA / divider
    if len(stripped) < 50 and _TG_ARROW_RE.search(stripped):
        return True
    # Mostly emoji with almost no real letters
    no_emoji = _TG_EMOJI_RE.sub('', stripped).strip()
    if len(no_emoji) < len(stripped) * 0.35 and len(stripped) < 80:
        return True
    # ALL CAPS short lines = channel name / header banner
    alnum = re.sub(r'[^A-ZА-ЯЁ]', '', stripped)
    if alnum and alnum == re.sub(r'[^A-Za-zА-ЯЁа-яё]', '', stripped).upper() and len(stripped) < 40:
        return True
    return False


def _is_garbage(para: str) -> bool:
    """True if paragraph is navigation/copyright/attribution noise."""
    if len(para) < 60:
        return True
    if any(para.startswith(s) for s in _SKIP_STARTS):
        return True
    if any(s in para for s in _SKIP_CONTAINS):
        return True
    if re.match(r'^\d+\s+\(\d+\s+сегодня\)', para):
        return True
    # Navigation menus: long text with very few spaces (words concatenated)
    space_ratio = para.count(' ') / max(len(para), 1)
    if space_ratio < 0.04:
        return True
    # Dateline bylines: "СОЧИ, 18 июн - РИА Недвижимость. Текст..."
    # Strip the dateline prefix if present, keep the rest
    if _DATELINE_RE.match(para):
        # Remove just the dateline header (up to first ". " or ". ")
        stripped = re.sub(r'^[^.]+\.\s*', '', para, count=1).strip()
        if len(stripped) < 60:
            return True
    return False


# ─────────────────────────────────────────────────────────────
# Article link discovery
# ─────────────────────────────────────────────────────────────
def _get_scraper_links(source: dict, limit: int = 20) -> list:
    """Scrape listing page(s) and return absolute article URLs."""
    pattern = source['link_pattern']
    base = source['base_url'].rstrip('/')
    listing_urls = source.get('listing_urls') or [source.get('listing_url', '')]
    seen = set()
    urls = []

    for listing_url in listing_urls:
        html = _fetch(listing_url)
        if not html:
            continue
        found = re.findall(pattern, html)
        for p in found:
            if source.get('link_prefix') and '|id' in source['link_prefix']:
                tpl = source['link_prefix'].replace('|id', '')
                url = tpl.format(p)
            elif p.startswith('http'):
                url = p
            else:
                url = base + p
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= limit:
                break
        if len(urls) >= limit:
            break

    return urls


def _get_rss_links(source: dict, limit: int = 20) -> list:
    """
    Parse RSS feed and return list of {url, title, description, pre_content} dicts.
    pre_content is populated from <content:encoded> if available (avoids extra HTTP fetch).
    Supports optional rss_filter_url to only include items whose link matches a substring.
    """
    raw = _fetch(source['rss_url'])
    if not raw:
        return []

    url_filter = source.get('rss_filter_url', '')
    items = []

    # Try XML parsing first
    try:
        root = ET.fromstring(raw)
        channel = root.find('channel') or root
        ns_content = 'http://purl.org/rss/1.0/modules/content/'

        for item in channel.findall('item'):
            def txt(tag, _i=item):
                el = _i.find(tag)
                return (el.text or '').strip() if el is not None else ''

            link = txt('link') or txt('guid')
            title = txt('title')
            desc = re.sub(r'<[^>]+>', '', txt('description'))[:600].strip()

            # <content:encoded> — full HTML if present
            ce_el = item.find(f'{{{ns_content}}}encoded')
            pre_content = (ce_el.text or '').strip() if ce_el is not None else ''

            if not link or not title:
                continue
            if url_filter and url_filter not in link:
                continue

            items.append({
                'url': link,
                'title': title,
                'description': desc,
                'pre_content': pre_content,
            })

    except Exception:
        # Fallback: pure regex (handles malformed XML and CDATA)
        for m in re.finditer(r'<item[^>]*>([\s\S]*?)</item>', raw):
            block = m.group(1)

            link_m = re.search(r'<link[^>]*>([^<]+)</link>', block)
            title_m = re.search(r'<title[^>]*><!\[CDATA\[(.*?)\]\]>', block, re.DOTALL)
            if not title_m:
                title_m = re.search(r'<title[^>]*>(.*?)</title>', block, re.DOTALL)
            desc_m = re.search(r'<description[^>]*><!\[CDATA\[(.*?)\]\]>', block, re.DOTALL)
            if not desc_m:
                desc_m = re.search(r'<description[^>]*>(.*?)</description>', block, re.DOTALL)
            ce_m = re.search(r'<content:encoded[^>]*><!\[CDATA\[([\s\S]*?)\]\]>', block)

            if not link_m or not title_m:
                continue
            link = link_m.group(1).strip()
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
            desc = re.sub(r'<[^>]+>', '', desc_m.group(1) if desc_m else '').strip()[:600]
            pre_content = ce_m.group(1).strip() if ce_m else ''

            if url_filter and url_filter not in link:
                continue

            items.append({
                'url': link,
                'title': title,
                'description': desc,
                'pre_content': pre_content,
            })

    return items[:limit]


# ─────────────────────────────────────────────────────────────
# Full article extraction — site-aware selectors
# ─────────────────────────────────────────────────────────────

def _extract_paragraphs_from_html(html: str, selector: str = '') -> list:
    """
    Extract clean text paragraphs from HTML.

    Selector modes:
      'div.CLASS'       → find container div by class, extract <p> tags inside it
      'div_each.CLASS'  → each matching div IS a paragraph (e.g. RIA article__text)
      'p'               → generic: extract all <p> tags (with article-body narrowing)
      ''                → auto: try container then fallback to <p>
    """
    paragraphs = []

    # Strip obviously noisy blocks
    clean = re.sub(
        r'<(script|style|nav|header|footer|aside|form|noscript|figure)[^>]*>[\s\S]*?</\1>',
        '', html, flags=re.IGNORECASE
    )

    # ── Mode: each matching div is a paragraph ────────────────────────
    if selector.startswith('div_each.'):
        cls_name = selector[9:]  # e.g. 'article__text'
        div_blocks = re.findall(
            r'<div[^>]*class=["\'][^"\']*' + re.escape(cls_name) + r'[^"\']*["\'][^>]*>'
            r'([\s\S]*?)'
            r'(?=<div[^>]*class=["\']|</section|</article|</main)',
            clean, re.IGNORECASE
        )
        for block in div_blocks:
            t = _clean_paragraph(block)
            if len(t) >= 60 and not _is_garbage(t):
                paragraphs.append(t)
        # Deduplicate and return early
        return _dedup(paragraphs)

    # ── Mode: container div → extract <p> tags inside ─────────────────
    if selector.startswith('div.'):
        cls_name = selector[4:]  # e.g. 'post-view-body'
        # Greedy match: find the div and take content until a clear boundary
        m = re.search(
            r'<div[^>]*class=["\'][^"\']*' + re.escape(cls_name) + r'[^"\']*["\'][^>]*>'
            r'([\s\S]+)',
            clean, re.IGNORECASE
        )
        if m:
            inner = m.group(1)
            # Stop at next major container
            inner = re.split(
                r'<(?:div|section|aside)[^>]*class=["\'][^"\']*(?:footer|sidebar|related|comment|adv|banner|after|below)[^"\']*["\']',
                inner, maxsplit=1, flags=re.IGNORECASE
            )[0]
            p_tags = re.findall(r'<p[^>]*>([\s\S]*?)</p>', inner, re.IGNORECASE)
            for raw_p in p_tags:
                t = _clean_paragraph(raw_p)
                if len(t) >= 60 and not _is_garbage(t):
                    paragraphs.append(t)

        if paragraphs:
            return _dedup(paragraphs)
        # fallthrough to generic if selector matched nothing

    # ── Mode: generic <p> extraction ──────────────────────────────────
    body_html = clean

    # Try to narrow down to a known article container first
    for art_pattern in [
        r'<article[^>]*>([\s\S]+?)</article>',
        r'<div[^>]*itemprop=["\']articleBody["\'][^>]*>([\s\S]+?)</div>',
        r'<div[^>]*class=["\'][^"\']*(?:article[_-]?body|post[_-]?content|entry[_-]?content|material[_-]?text)[^"\']*["\'][^>]*>([\s\S]+?)</div>',
    ]:
        matches = re.findall(art_pattern, clean, re.IGNORECASE)
        if matches:
            candidate = max(matches, key=len)
            if len(candidate) > 400:
                body_html = candidate
                break

    p_tags = re.findall(r'<p[^>]*>([\s\S]*?)</p>', body_html, re.IGNORECASE)
    for raw_p in p_tags:
        t = _clean_paragraph(raw_p)
        if len(t) >= 60 and not _is_garbage(t):
            paragraphs.append(t)

    return _dedup(paragraphs)


def _dedup(paras: list) -> list:
    """Remove duplicate paragraphs (by first 60 chars)."""
    seen = set()
    out = []
    for p in paras:
        key = p[:60]
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _extract_article(url: str, hint_title: str = '', hint_desc: str = '',
                     selector: str = '', pre_content: str = '') -> dict:
    """
    Fetch article page (or use pre_content from RSS <content:encoded>),
    extract title + body paragraphs.
    Returns {'title': str, 'paragraphs': [str], 'full_text': str}
    """
    # If RSS already gave us full HTML — use it, skip the HTTP fetch
    if pre_content and len(pre_content) > 300:
        html = pre_content
    else:
        html = _fetch(url)

    if not html:
        return {'title': hint_title, 'paragraphs': [], 'full_text': hint_desc}

    # Extract title from <h1>
    title = hint_title
    h1 = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', html, re.IGNORECASE)
    if h1:
        t = _clean_paragraph(h1.group(1))
        if len(t) > 10:
            title = t

    # Extract paragraphs using site-aware selector
    paragraphs = _extract_paragraphs_from_html(html, selector)

    # Fallback: generic <p> extraction on full page
    if not paragraphs:
        paragraphs = _extract_paragraphs_from_html(html, 'p')

    # Meta description as final fallback
    meta_desc = ''
    md = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE
    )
    if not md:
        md = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
            html, re.IGNORECASE
        )
    if md:
        meta_desc = md.group(1).strip()

    full_text = '\n\n'.join(paragraphs)
    if not full_text:
        full_text = hint_desc or meta_desc

    return {
        'title': title or hint_title,
        'paragraphs': paragraphs,
        'full_text': full_text,
    }


# ─────────────────────────────────────────────────────────────
# Telegram public channel parser
# ─────────────────────────────────────────────────────────────
def _get_telegram_posts(source: dict, limit: int = 20) -> list:
    """
    Fetch posts from a public Telegram channel via t.me/s/CHANNEL_NAME.
    Returns list of {url, title, description, pre_content} dicts.
    The t.me/s/ URL renders a static web preview of recent channel posts.
    """
    channel = source.get('tg_channel', '').strip().lstrip('@')
    if not channel:
        return []

    url = f'https://t.me/s/{channel}'
    html = _fetch(url)
    if not html:
        logger.debug(f'Telegram: failed to fetch {url}')
        return []

    items = []
    # Each post is wrapped in <div class="tgme_widget_message_wrap ...">
    # The message text is in <div class="tgme_widget_message_text ...">
    post_blocks = re.findall(
        r'<div[^>]*class=["\'][^"\']*tgme_widget_message_wrap[^"\']*["\'][^>]*>'
        r'([\s\S]*?)'
        r'(?=<div[^>]*class=["\'][^"\']*tgme_widget_message_wrap|$)',
        html
    )

    for block in post_blocks:
        # Extract message URL (for dedup and attribution)
        url_m = re.search(r'href=["\']https://t\.me/' + re.escape(channel) + r'/(\d+)["\']', block)
        if not url_m:
            continue
        post_url = f'https://t.me/{channel}/{url_m.group(1)}'

        # Extract text content
        text_m = re.search(
            r'<div[^>]*class=["\'][^"\']*tgme_widget_message_text[^"\']*["\'][^>]*>'
            r'([\s\S]*?)</div>',
            block
        )
        if not text_m:
            continue

        raw_html = text_m.group(1)

        # Convert <br><br> → paragraph separator, single <br> → line break
        raw_html = re.sub(r'<br\s*/?>\s*<br\s*/?>', '\n\n', raw_html)
        raw_html = re.sub(r'<br\s*/?>', '\n', raw_html)

        # Split into paragraph fragments by double newline
        frag_blocks = [f.strip() for f in raw_html.split('\n\n') if f.strip()]
        if not frag_blocks:
            frag_blocks = [raw_html]

        clean_paras = []
        for frag in frag_blocks:
            # Sub-lines inside a fragment (single \n) → clean each, then join
            sub_lines = [_clean_paragraph(line) for line in frag.split('\n') if line.strip()]
            para = ' '.join(l for l in sub_lines if l)
            if not para:
                continue
            if _is_tg_decorator(para):
                continue
            if _is_garbage(para):
                continue
            clean_paras.append(para)

        if not clean_paras:
            continue

        full_text = '\n\n'.join(clean_paras)
        if len(full_text) < 80:
            continue

        # Use first sentence as title
        title_m = re.match(r'([^.!?\n]{20,120}[.!?])', clean_paras[0])
        title = title_m.group(1).strip() if title_m else clean_paras[0][:100].strip()

        if _is_relevant(full_text):
            items.append({
                'url': post_url,
                'title': title,
                'description': full_text[:600],
                'pre_content': ''.join(f'<p>{p}</p>' for p in clean_paras),
                'paragraphs': clean_paras,   # pre-parsed, skip re-fetch
                'full_text': full_text,
            })

        if len(items) >= limit:
            break

    logger.debug(f'Telegram @{channel}: found {len(items)} relevant posts')
    return items


# ─────────────────────────────────────────────────────────────
# Source health check
# ─────────────────────────────────────────────────────────────
def check_sources_status() -> list:
    """Quick health check for all sources. Returns list with status dicts."""
    results = []
    for src in RSS_SOURCES:
        try:
            if src['type'] == 'scraper':
                links = _get_scraper_links(src, limit=5)
                ok = len(links) > 0
                count = len(links)
            elif src['type'] == 'telegram':
                items = _get_telegram_posts(src, limit=5)
                ok = len(items) > 0
                count = len(items)
            else:
                items = _get_rss_links(src, limit=5)
                ok = len(items) > 0
                count = len(items)
        except Exception as e:
            ok = False
            count = 0
            logger.warning(f'Health check failed for {src["name"]}: {e}')

        if src['type'] == 'scraper':
            display_url = src.get('listing_urls', [src.get('listing_url', '')])[0]
        elif src['type'] == 'telegram':
            display_url = f'https://t.me/s/{src.get("tg_channel", "")}'
        else:
            display_url = src.get('rss_url', '')
        results.append({**src, 'ok': ok, 'count': count, 'url': display_url})
    return results


# ─────────────────────────────────────────────────────────────
# Uniqualization — synonym substitution
# ─────────────────────────────────────────────────────────────
_SYNONYMS = {
    'рынок недвижимости': ['сфера недвижимости', 'отрасль недвижимости', 'рынок жилья'],
    'квартира': ['жилплощадь', 'апартаменты', 'жилое помещение'],
    'покупка': ['приобретение', 'покупка', 'сделка'],
    'покупатель': ['приобретатель', 'покупатель жилья', 'клиент'],
    'застройщик': ['девелопер', 'строительная компания', 'застройщик'],
    'строительство': ['возведение', 'строительство', 'стройка'],
    'новостройка': ['новострой', 'строящийся объект', 'первичное жильё'],
    'ипотека': ['жилищный кредит', 'ипотечный кредит', 'ипотека'],
    'процентная ставка': ['ставка кредитования', 'кредитная ставка', 'процент'],
    'снизился': ['сократился', 'уменьшился', 'упал'],
    'вырос': ['увеличился', 'поднялся', 'возрос'],
    'эксперт': ['специалист', 'аналитик', 'профессионал'],
    'по данным': ['согласно данным', 'как показывают данные', 'по информации'],
    'отметил': ['подчеркнул', 'отметил', 'указал'],
    'сообщил': ['рассказал', 'пояснил', 'заявил'],
    'считает': ['полагает', 'считает', 'убеждён'],
}


def _smart_uniqualize(paragraphs: list, title: str) -> list:
    """
    Light synonym substitution on real article paragraphs.
    Preserves facts, numbers, quotes — only replaces common verbs/nouns.
    """
    random.seed(hash(title) % 99991)
    result = []
    for para in paragraphs:
        text = para
        applied = 0
        for original, variants in _SYNONYMS.items():
            if applied >= 3:
                break
            if original.lower() in text.lower():
                replacement = random.choice(variants)
                if replacement.lower() != original.lower():
                    text = re.sub(re.escape(original), replacement, text, count=1, flags=re.IGNORECASE)
                    applied += 1
        result.append(text)
    return result


def _build_article_html(title: str, paragraphs: list, source_name: str, source_url: str) -> str:
    """Build full HTML article from scraped paragraphs with InBack promo blocks."""
    random.seed(hash(title) % 99991)

    _INBACK_BLOCKS = [
        '''<div style="background:#eff6ff;border-left:4px solid #2563eb;padding:20px 24px;border-radius:8px;margin:28px 0">
<h3 style="margin:0 0 8px;color:#1e40af;font-size:16px">💰 Покупайте новостройку с кэшбеком до 500&nbsp;000&nbsp;₽</h3>
<p style="margin:0;color:#374151;line-height:1.6">Сервис <strong>InBack</strong> возвращает до 4% стоимости квартиры деньгами на банковский счёт.
Работаем с застройщиками по всей России. Бесплатный подбор, помощь с ипотекой и юридическое сопровождение сделки.</p>
</div>''',

        '''<div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:20px 24px;border-radius:8px;margin:28px 0">
<h3 style="margin:0 0 8px;color:#15803d;font-size:16px">🏠 InBack: экономия при покупке новостройки</h3>
<p style="margin:0;color:#374151;line-height:1.6">При покупке квартиры в новостройке через <strong>InBack</strong>
вы получаете кэшбек до <strong>500&nbsp;000&nbsp;₽</strong> после сделки.
Платформа работает с ведущими застройщиками России — без доплат и скрытых условий.</p>
</div>''',

        '''<div style="background:#fefce8;border-left:4px solid #ca8a04;padding:20px 24px;border-radius:8px;margin:28px 0">
<h3 style="margin:0 0 8px;color:#92400e;font-size:16px">📊 Как сэкономить на покупке квартиры</h3>
<p style="margin:0;color:#374151;line-height:1.6">Воспользуйтесь сервисом <strong>InBack</strong>: выберите жильё у проверенного застройщика
и получите кэшбек до 4% от стоимости квартиры. Деньги поступают на счёт после регистрации договора.
Сервис работает по всей России.</p>
</div>''',
    ]

    _MARKET_CONTEXT_BLOCKS = [
        '<h3>Ситуация на рынке первичной недвижимости</h3><p>Описанные тенденции отражают общероссийские процессы: рынок новостроек адаптируется к изменению ипотечных условий, а застройщики ищут новые инструменты привлечения покупателей. Спрос на первичное жильё сохраняет устойчивость в городах с активным строительством.</p>',
        '<h3>Российский рынок новостроек</h3><p>Приведённые данные характерны для большинства крупных региональных рынков России. Покупатели всё тщательнее анализируют предложения, сравнивают условия застройщиков и ищут способы снизить итоговую стоимость покупки — в том числе через кэшбек-сервисы.</p>',
        '<h3>Тренды рынка недвижимости</h3><p>Аналитики фиксируют: покупатели стали более осознанно подходить к выбору жилья. Растёт доля сделок с использованием cashback-инструментов и специальных программ от застройщиков. Эксперты рекомендуют тщательно сравнивать предложения на рынке перед принятием решения о покупке.</p>',
    ]

    _CONCLUSIONS = [
        '<h3>Выводы</h3><p>Эксперты рекомендуют внимательно следить за изменениями рыночной конъюнктуры и не откладывать решение жилищного вопроса. При выборе квартиры важно сравнивать несколько объектов, изучать репутацию застройщика и просчитывать все варианты финансирования.</p>',
        '<h3>Итог</h3><p>Рынок недвижимости реагирует на экономические изменения, но базовый спрос на качественное жильё остаётся стабильным. Аналитики рекомендуют ориентироваться на долгосрочные тренды, а не на краткосрочные колебания — для тех, кто приобретает жильё для жизни, а не спекуляции, текущий момент вполне приемлем.</p>',
    ]

    parts = [f'<h2>{title}</h2>']

    insert_after = max(2, len(paragraphs) * 6 // 10)
    for i, para in enumerate(paragraphs):
        parts.append(f'<p>{para}</p>')
        if i == insert_after - 1:
            parts.append(random.choice(_INBACK_BLOCKS))

    if len(paragraphs) <= insert_after:
        parts.append(random.choice(_INBACK_BLOCKS))

    parts.append(random.choice(_MARKET_CONTEXT_BLOCKS))
    parts.append(random.choice(_CONCLUSIONS))

    return '\n'.join(parts)


# ─────────────────────────────────────────────────────────────
# OpenAI uniqualization (premium, optional)
# ─────────────────────────────────────────────────────────────
def _openai_rewrite(title: str, full_text: str) -> dict | None:
    """Full rewrite via OpenAI GPT-4o-mini. Returns dict or None on failure."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None
    try:
        import json as _json
        body = _json.dumps({
            'model': 'gpt-4o-mini',
            'messages': [{
                'role': 'user',
                'content': (
                    'Ты — SEO-копирайтер сайта InBack.ru (сервис покупки новостроек с кэшбеком до 500 000 ₽, работает по всей России). '
                    'Перепиши следующую статью о недвижимости:\n\n'
                    f'ЗАГОЛОВОК: {title}\n\n'
                    f'ТЕКСТ:\n{full_text[:3000]}\n\n'
                    'Требования:\n'
                    '1. Новый уникальный заголовок (не копировать исходный)\n'
                    '2. Полная статья в HTML (h3, p): сохрани все факты и цифры\n'
                    '3. Вставь один рекламный блок про InBack (кэшбек до 500 000 ₽ при покупке новостройки, по всей России)\n'
                    '4. SEO описание до 155 символов\n'
                    '5. Ключевые слова (10-15 через запятую, связанные с темой статьи)\n'
                    '6. Краткое описание (excerpt, 1-2 предложения)\n\n'
                    'Ответь ТОЛЬКО в JSON без markdown:\n'
                    '{"title":"...","content":"...HTML...","excerpt":"...","seo_description":"...","keywords":"..."}'
                ),
            }],
            'max_tokens': 2500,
            'temperature': 0.7,
        }).encode()
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=body,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=45, context=_ssl_ctx()) as resp:
            data = _json.loads(resp.read())
        text = data['choices'][0]['message']['content']
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
        return _json.loads(text)
    except Exception as e:
        logger.warning(f'OpenAI rewrite failed: {e}')
        return None


# ─────────────────────────────────────────────────────────────
# SEO field generation
# ─────────────────────────────────────────────────────────────
_SEO_TOPIC_KW = {
    'ипотека': ['ипотека', 'ипотечный кредит', 'льготная ипотека', 'семейная ипотека', 'ставка ипотеки'],
    'застройщик': ['застройщик', 'девелопер', 'ДДУ', 'эскроу', 'проектное финансирование'],
    'новостройка': ['новостройка', 'первичное жильё', 'жилой комплекс', 'ЖК', 'строящееся жильё'],
    'рассрочка': ['рассрочка', 'рассрочка на квартиру', 'альтернатива ипотеке'],
    'аренда': ['аренда квартиры', 'арендный рынок', 'снять квартиру'],
    'default': ['недвижимость', 'покупка квартиры', 'рынок жилья'],
}


def _detect_topic(text: str) -> str:
    tl = text.lower()
    if any(w in tl for w in ['ипотек', 'ставк', 'льготн', 'семейн', 'кредит']):
        return 'ипотека'
    if any(w in tl for w in ['застройщик', 'девелопер', 'минстро', 'дом.рф', 'рассрочк']):
        return 'застройщик'
    if any(w in tl for w in ['новостройк', 'жк ', 'жилой комплекс']):
        return 'новостройка'
    if 'рассрочк' in tl:
        return 'рассрочка'
    return 'default'


def _seo_keywords(title: str, full_text: str) -> str:
    topic = _detect_topic(title + ' ' + full_text)
    kw = set(_SEO_TOPIC_KW.get(topic, _SEO_TOPIC_KW['default']))
    kw.update(['InBack', 'кэшбек', 'новостройки России', 'покупка квартиры', 'кэшбек при покупке'])
    for word in title.split():
        if len(word) > 5 and word[0].isupper():
            kw.add(word.strip('.,"-'))
    return ', '.join(sorted(kw))[:500]


def _seo_description(title: str, first_para: str) -> str:
    base = first_para[:100].rstrip() if first_para else title[:80]
    suffix = ' — читайте на InBack, сервис покупки новостроек с кэшбеком до 500 000 ₽.'
    return (base + suffix)[:155]


# ─────────────────────────────────────────────────────────────
# Slug helper
# ─────────────────────────────────────────────────────────────
def _make_slug(title: str, url: str) -> str:
    tr = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    s = title.lower()
    s = ''.join(tr.get(c, c) for c in s)
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:60]
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f'{s}-{url_hash}'


# ─────────────────────────────────────────────────────────────
# Main enrichment entry point
# ─────────────────────────────────────────────────────────────
def run_enrichment(
    admin_id: int,
    sources: list = None,
    uniqualize: bool = True,
    uniqualize_mode: str = 'smart',
    status: str = 'draft',
    limit_per_source: int = 5,
) -> dict:
    """
    Collect articles, scrape full text, uniqualize, save as BlogPost.
    Returns: {fetched, relevant, saved, skipped, errors, saved_titles}
    """
    from app import db
    from models import BlogPost, Category

    if sources is None:
        sources = RSS_SOURCES

    stats = {
        'fetched': 0, 'relevant': 0, 'saved': 0,
        'skipped': 0, 'errors': 0, 'saved_titles': [],
    }
    now = datetime.datetime.utcnow()

    # Auto-create "Новости рынка" category if it doesn't exist
    cat = Category.query.filter(Category.name == 'Новости рынка').first()
    if not cat:
        cat = Category.query.filter(Category.name.ilike('%новост%')).first()
    if not cat:
        try:
            cat = Category(
                name='Новости рынка',
                slug='novosti-rynka',
                description='Новости и аналитика рынка недвижимости России',
                is_active=True,
                sort_order=1,
            )
            db.session.add(cat)
            db.session.commit()
            logger.info('✅ Создана категория "Новости рынка"')
        except Exception:
            db.session.rollback()
            cat = Category.query.first()

    for source in sources:
        selector = source.get('article_selector', '')

        # ── Step 1: collect article items ──────────────────────────────
        if source.get('type') == 'scraper':
            urls = _get_scraper_links(source, limit=limit_per_source * 3)
            items = [{'url': u, 'title': '', 'description': '', 'pre_content': ''} for u in urls]
        elif source.get('type') == 'telegram':
            items = _get_telegram_posts(source, limit=limit_per_source * 3)
        else:
            items = _get_rss_links(source, limit=limit_per_source * 3)

        stats['fetched'] += len(items)
        saved_this_source = 0

        for item in items:
            if saved_this_source >= limit_per_source:
                break

            url = item['url']
            hint_title = item.get('title', '')
            hint_desc = item.get('description', '')
            pre_content = item.get('pre_content', '')

            # Quick relevance pre-filter from RSS hint
            if hint_title or hint_desc:
                if not _is_relevant(hint_title + ' ' + hint_desc):
                    stats['skipped'] += 1
                    continue

            # Dedup by URL hash
            slug = _make_slug(hint_title or url, url)
            if BlogPost.query.filter_by(slug=slug).first():
                stats['skipped'] += 1
                continue
            if BlogPost.query.filter(BlogPost.tags.contains(url[:60])).first():
                stats['skipped'] += 1
                continue

            try:
                # ── Step 2: fetch full article ──────────────────────────
                time.sleep(0.4)  # polite delay

                # Telegram items carry pre-parsed paragraphs — skip re-fetch
                if item.get('paragraphs'):
                    paragraphs = item['paragraphs']
                    full_text = item.get('full_text', '\n\n'.join(paragraphs))
                    title = hint_title or 'Новость о недвижимости'
                else:
                    article = _extract_article(url, hint_title, hint_desc, selector, pre_content)
                    paragraphs = article['paragraphs']
                    title = article['title'] or hint_title or 'Новость о недвижимости'
                    full_text = article['full_text']

                # Relevance check on full content
                if not _is_relevant(title + ' ' + full_text):
                    stats['skipped'] += 1
                    continue
                stats['relevant'] += 1

                # Need at least some real content
                if len(full_text) < 150 and not hint_desc:
                    logger.debug(f'Skipping {url}: too little content ({len(full_text)}c)')
                    stats['skipped'] += 1
                    continue

                # If paragraphs are empty but full_text exists, split by double-newline
                if not paragraphs and full_text:
                    paragraphs = [s.strip() for s in full_text.split('\n\n') if len(s.strip()) >= 60]
                    if not paragraphs:
                        paragraphs = [full_text]

                # Recalculate slug from real title
                slug = _make_slug(title, url)
                if BlogPost.query.filter_by(slug=slug).first():
                    stats['skipped'] += 1
                    continue

                # ── Step 3: uniqualize ──────────────────────────────────
                final_title = title
                content_html = ''
                excerpt = ''
                keywords = ''
                seo_desc = ''

                if uniqualize_mode == 'openai':
                    result = _openai_rewrite(title, full_text)
                    if result:
                        final_title = result.get('title', title)
                        content_html = result.get('content', '')
                        excerpt = result.get('excerpt', '')
                        keywords = result.get('keywords', '')
                        seo_desc = result.get('seo_description', '')
                    else:
                        uniqualize_mode = 'smart'  # fallback

                if uniqualize_mode == 'smart' and not content_html:
                    rewritten = _smart_uniqualize(paragraphs, title)
                    content_html = _build_article_html(title, rewritten, source.get('name', ''), url)
                    excerpt = paragraphs[0][:300] if paragraphs else full_text[:300]
                    keywords = _seo_keywords(title, full_text)
                    seo_desc = _seo_description(title, paragraphs[0] if paragraphs else full_text)

                elif uniqualize_mode == 'none' and not content_html:
                    content_html = _build_article_html(title, paragraphs or [full_text], source.get('name', ''), url)
                    excerpt = paragraphs[0][:300] if paragraphs else full_text[:300]
                    keywords = _seo_keywords(title, full_text)
                    seo_desc = _seo_description(title, paragraphs[0] if paragraphs else full_text)

                if not excerpt:
                    clean_txt = re.sub(r'<[^>]+>', '', content_html)
                    excerpt = clean_txt[:300].strip()

                # ── Step 4: save ────────────────────────────────────────
                post = BlogPost(
                    title=final_title,
                    slug=slug,
                    content=content_html,
                    excerpt=excerpt,
                    meta_title=(final_title[:195] + ' | InBack'),
                    meta_description=seo_desc,
                    meta_keywords=keywords,
                    category=source.get('category', 'Новости рынка'),
                    category_id=cat.id if cat else None,
                    tags=json.dumps([url]),
                    status=status,
                    author_id=admin_id,
                    created_at=now,
                    published_at=now if status == 'published' else None,
                )
                db.session.add(post)
                db.session.commit()
                stats['saved'] += 1
                saved_this_source += 1
                stats['saved_titles'].append(final_title[:80])
                logger.info(f'✅ Saved: "{final_title[:60]}" ({len(paragraphs)} paras from {source["name"]})')

            except Exception as e:
                db.session.rollback()
                logger.error(f'Error saving "{hint_title or url}": {e}')
                stats['errors'] += 1

    return stats
