"""
SEO Blueprint — sitemap.xml, robots.txt, RSS feed, Google verification.

Sitemap hierarchy:
  /sitemap.xml            → alias for sitemap-index.xml (entry point for all bots)
  /sitemap-index.xml      → sitemap index (lists all sub-sitemaps)
  /sitemap-static.xml     → static pages + city landing pages + mortgage slugs
  /sitemap-programmatic.xml → all SEO filter slugs × active cities (with image support)
  /sitemap-seo-ext.xml    → district + developer SEO pages
  /sitemap-complexes.xml  → residential complex pages
  /sitemap-blog.xml       → blog posts
  /sitemap-properties-N.xml → paginated property pages (10 000 per file)
  /sitemap-images.xml     → image sitemap for RC galleries
"""
import json as _json_img
from datetime import datetime, timedelta

from flask import Blueprint, abort, jsonify, request, current_app

from app import db, cache, CANONICAL_BASE_URL

seo_bp = Blueprint('seo', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xml_response(lines):
    r = current_app.response_class(
        response='\n'.join(lines), status=200, mimetype='application/xml'
    )
    r.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return r


def _url_entry(loc, lastmod, changefreq, priority, image_loc=None, image_title=None):
    lines = ['  <url>', f'    <loc>{loc}</loc>',
             f'    <lastmod>{lastmod}</lastmod>',
             f'    <changefreq>{changefreq}</changefreq>',
             f'    <priority>{priority}</priority>']
    if image_loc:
        lines += ['    <image:image>',
                  f'      <image:loc>{image_loc}</image:loc>']
        if image_title:
            lines.append(f'      <image:title>{image_title[:100]}</image:title>')
        lines.append('    </image:image>')
    lines.append('  </url>')
    return lines


def _proxy_image(img, base_url):
    """Convert cdn-cian.ru URLs to /api/img-proxy proxy; leave others as-is."""
    import base64 as _b64
    if not img:
        return None
    if 'cdn-cian.ru/' in img:
        path = img.split('cdn-cian.ru/', 1)[1]
        tok = _b64.urlsafe_b64encode(path.encode()).decode().rstrip('=')
        return f'{base_url}/api/img-proxy?t={tok}'
    if img.startswith('/'):
        return base_url + img
    if img.startswith('http'):
        return img
    return None


def _slug_priority(slug):
    """Return (priority, changefreq) for a given SEO slug.

    Tier A 0.82 – High search-volume transactional pages
    Tier B 0.75 – Standard filter combinations  
    Tier C 0.65 – Long-tail / niche combinations
    """
    HIGH = {
        'novostrojki-v-ipoteku', 'novostrojki-s-semeynoj-ipotekoj',
        'novostrojki-do-5-mln', 'novostrojki-do-6-mln', 'novostrojki-do-8-mln',
        'novostrojki-do-10-mln', 'novostrojki-do-12-mln',
        'novostrojki-studiyo', 'novostrojki-1-komnatnye',
        'novostrojki-2-komnatnye', 'novostrojki-3-komnatnye',
        'novostrojki-s-otdelkoy', 'novostrojki-komfort-klass',
        'novostrojki-biznes-klass',
        '1-komnatnye-do-5-mln', '2-komnatnye-do-8-mln',
        '1-komnatnye-v-ipoteku', '2-komnatnye-v-ipoteku', '3-komnatnye-v-ipoteku',
        'studii-do-3-mln', 'studii-v-ipoteku',
        'kupit-studiu-v-novostroyke', 'kupit-dvushku-v-novostroyke',
        'kupit-treshku-v-novostroyke', 'kupit-odnushku-v-novostroyke',
        '1-komnatnye-do-4-mln', '2-komnatnye-do-6-mln', '3-komnatnye-do-10-mln',
        'novostrojki-s-parkingom', 'evro-2-komnatnye',
        # Микрорайоны Краснодара — Wordstat 2025
        'kvartiry-v-ymr', 'kvartiry-v-pobede', 'kvartiry-v-vostochno-kruglikovskom',
        'kvartiry-v-cheremusikah', 'kvartiry-v-rossiyskom', 'kvartiry-v-muzykalnom',
        'kvartiry-v-fmr', 'kvartiry-v-kmr', 'kvartiry-v-znamienskom',
        'kvartiry-v-komsomoliskom',
        # ЖК Краснодара — высокочастотные
        'zk-samolet-krasnodar', 'kupit-kvartiru-v-samolete',
        'zk-dostoyanie-krasnodar', 'zk-panorama-krasnodar',
        'kupit-kvartiru-v-parke-galickogo',
        # Вторичка — intent-перехват (6275+ запросов)
        'vtorichka-ili-novostrojka', 'kupit-kvartiru-vtorichka',
        # Комнаты × новые микрорайоны
        '1-komnatnye-v-ymr', '2-komnatnye-v-ymr',
        '1-komnatnye-v-pobede', '2-komnatnye-v-pobede',
        '1-komnatnye-v-muzykalnom-rajone', '2-komnatnye-v-muzykalnom-rajone',
        # Новые 2026 — транзакционные запросы (добавлено)
        '1-komnatnye-voennaya-ipoteka', '2-komnatnye-voennaya-ipoteka',
        '3-komnatnye-voennaya-ipoteka', 'studii-voennaya-ipoteka',
        'voennaya-ipoteka', 'voennaya-ipoteka-2026',
        '1-komnatnye-s-otdelkoy-do-5-mln', '2-komnatnye-s-otdelkoy-do-8-mln',
        '3-komnatnye-s-otdelkoy-do-15-mln', 'studii-s-otdelkoy-do-4-mln',
        'dolevoe-stroitelstvo', 'kvartiry-po-ddu', 'kupit-kvartiru-po-ddu',
        'kvartiry-po-eskrou', 'escrow-schet-novostrojki',
        'semeynaya-ipoteka-v-novostroyke', 'semeynaya-ipoteka-do-15-mln',
        'novostrojki-bez-pervogo-vznosa', 'ipoteka-bez-pervogo-vznosa-2026',
        'materinskiy-kapital-na-kvartiru', '4-komnatnye-materinskiy-kapital',
        'kvartiry-s-matkapitalom-2026',
        'it-ipoteka-bez-pervogo-vznosa', 'it-ipoteka-do-12-mln', 'it-ipoteka-komfort-klass',
        'investicii-v-novostrojki-2026', 'investicii-v-studii',
        'studii-dlya-sdachi-v-arendu', 'nedvizhimost-dlya-sdachi',
        'kvartiry-pod-sdachu-posutochno',
        'novostrojki-ot-3-5-mln', 'novostrojki-ot-4-mln',
        'novostrojki-ot-6-mln', 'novostrojki-ot-7-mln',
        'studii-v-sochi',
        'novostrojki-krasnodarskiy-kray',
        'kvartiry-v-sochi-v-rassrochku',
        'novostrojki-s-aktsiyami-2026', 'novostrojki-starti-prodazh-2026',
        'semejnye-kvartiry-s-detskim-sadom',
        'kvartiry-bez-pereplaty',
    }
    NICHE = {
        'penthouse-novostrojki', 'novostrojki-vysotki',
        'novostrojki-s-vidovymi-kvartirami', 'kvartiry-s-terrasoj',
        'novostrojki-s-basseinom', 'novostrojki-s-konciergem',
        'novostrojki-ot-100-kvm', 'novostrojki-70-100-kvm',
        'novostrojki-ot-10-do-20-mln',
        'kvartiry-s-dvumya-sanuzlami', 'kvartiry-s-garderobom',
        'apartamenty-v-novostroyke', 'kottedzhi-v-novostroyke',
        'taunhauzy-v-novostroyke',
        'novostrojki-v-armavire', 'novostrojki-v-gelendzhike',
        'novostrojki-v-novorossiyske', 'novostrojki-v-anape',
        'novostrojki-v-lazarevskom-rajone', 'novostrojki-v-adlerskom-rajone',
        '1-komnatnye-sdacha-2030', '2-komnatnye-sdacha-2030',
        '3-komnatnye-sdacha-2030', '4-komnatnye-sdacha-2030', 'studii-sdacha-2030',
        'semeynaya-ipoteka-2027',
        'kvartiry-s-bolshim-metrajom', 'kvartiry-s-kuhney-gostinej',
        'kvartiry-s-masterom-spalnej',
        'voennaya-ipoteka-s-otdelkoy',
        'kvartiry-bez-pereplaty',
    }
    if slug in HIGH:
        return '0.82', 'weekly'
    if slug in NICHE:
        return '0.65', 'monthly'
    return '0.72', 'weekly'


# ---------------------------------------------------------------------------
# /sitemap.xml  — canonical entry point (works as index for bots)
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def sitemap():
    """Main sitemap — serves a sitemap index so all bots find everything."""
    try:
        from models import Property as _Prop
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')

        prop_count = _Prop.query.filter_by(is_active=True).count()
        props_per_page = 10000
        prop_pages = max(1, (prop_count + props_per_page - 1) // props_per_page)

        # All sub-sitemaps — ordered by SEO importance for faster discovery
        sub_sitemaps = [
            'sitemap-new-slugs.xml',      # NEW 2026-06: 63 new route-only pages (fastest discovery)
            'sitemap-programmatic.xml',   # SEO filter pages — full set × cities
            'sitemap-static.xml',
            'sitemap-seo-ext.xml',        # districts + developers
            'sitemap-complexes.xml',
            'sitemap-blog.xml',
            'sitemap-images.xml',
            'sitemap-districts.xml',
            'sitemap-streets.xml',
        ]

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<!-- InBack Sitemap Index | Generated: {today} | Properties: {prop_count} -->',
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]

        for slug in sub_sitemaps:
            lines += ['  <sitemap>', f'    <loc>{base_url}/{slug}</loc>',
                      f'    <lastmod>{today}</lastmod>', '  </sitemap>']

        for page in range(1, prop_pages + 1):
            lines += ['  <sitemap>',
                      f'    <loc>{base_url}/sitemap-properties-{page}.xml</loc>',
                      f'    <lastmod>{today}</lastmod>', '  </sitemap>']

        lines.append('</sitemapindex>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'sitemap.xml error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-index.xml  — same as /sitemap.xml (kept for backward compatibility)
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-index.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def sitemap_index_xml():
    """Sitemap Index — alias, same content as /sitemap.xml."""
    return sitemap()


# ---------------------------------------------------------------------------
# /sitemap-programmatic.xml  — SEO filter slugs × active cities (MAIN)
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-programmatic.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def sitemap_programmatic_xml():
    """Programmatic SEO landing pages — all filter slugs × active cities.
    Respects city_ids per slug. Includes image:image for OG images.
    Priority is tiered: High 0.82 / Mid 0.72 / Niche 0.65.
    """
    try:
        from models import City, ResidentialComplex
        from routes.seo_city import _SEO_NOVOSTROJKI_SLUGS
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')

        cities = City.query.filter_by(is_active=True).all()

        # Pre-fetch first RC image per city (for image:image tags)
        city_image_map = {}
        try:
            city_ids = [c.id for c in cities]
            rc_imgs = (ResidentialComplex.query
                       .filter(ResidentialComplex.city_id.in_(city_ids),
                               ResidentialComplex.is_active == True,
                               ResidentialComplex.main_image.isnot(None),
                               ResidentialComplex.main_image != '')
                       .with_entities(ResidentialComplex.city_id, ResidentialComplex.main_image)
                       .distinct(ResidentialComplex.city_id)
                       .all())
            for row in rc_imgs:
                city_image_map[row.city_id] = _proxy_image(row.main_image, base_url)
        except Exception:
            pass

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
            '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
        ]

        for filter_slug, cfg in _SEO_NOVOSTROJKI_SLUGS.items():
            allowed_city_ids = cfg.get('city_ids', [])
            target_cities = (
                [c for c in cities if c.id in allowed_city_ids]
                if allowed_city_ids else cities
            )
            priority, changefreq = _slug_priority(filter_slug)
            for city in target_cities:
                loc = f'{base_url}/{city.slug}/{filter_slug}'
                img_url = city_image_map.get(city.id)
                # Build H1 title for image caption (strip {prep}/{gen} placeholders)
                raw_h1 = cfg.get('h1', cfg.get('title', ''))
                prep = city.name_prepositional or city.name
                gen_form = city.name_genitive or city.name
                img_title = (raw_h1.replace('{prep}', prep)
                                   .replace('{gen}', gen_form)
                                   .replace(' | InBack', '').strip())
                lines += _url_entry(
                    loc, today, changefreq, priority,
                    image_loc=img_url, image_title=img_title if img_url else None
                )

        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'sitemap-programmatic.xml error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-seo-ext.xml  — districts + developers (companion to programmatic)
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-seo-ext.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def sitemap_seo_ext_xml():
    """SEO extension sitemap: district pages + developer city landing pages."""
    try:
        from models import City
        from routes.seo_city import _DISTRICT_MAP
        from sqlalchemy import text as _txt
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')

        cities = City.query.filter_by(is_active=True).all()
        city_map = {c.id: c.slug for c in cities}

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]

        # District SEO pages (novostrojki-v-<district>-rajone)
        for district_prep, dinfo in _DISTRICT_MAP.items():
            allowed = dinfo.get('city_ids', [])
            target = [c for c in cities if (not allowed or c.id in allowed)]
            for city in target:
                loc = f'{base_url}/{city.slug}/novostrojki-v-{district_prep}-rajone'
                lines += _url_entry(loc, today, 'weekly', '0.75')

        # District ZhK pages (/<city_slug>/zhilye-kompleksy/<district_slug>)
        try:
            dist_rows = db.session.execute(_txt('''
                SELECT d.slug AS dslug, d.city_id
                FROM districts d
                JOIN residential_complexes rc ON rc.district_id = d.id AND rc.is_active = TRUE
                WHERE d.slug IS NOT NULL AND length(d.slug) > 0
                GROUP BY d.slug, d.city_id
                HAVING count(rc.id) > 0
                ORDER BY d.city_id, count(rc.id) DESC
            ''')).fetchall()
            for row in dist_rows:
                cs = city_map.get(row.city_id)
                if cs:
                    loc = f'{base_url}/{cs}/zhilye-kompleksy/{row.dslug}'
                    lines += _url_entry(loc, today, 'weekly', '0.82')
        except Exception:
            pass

        # Developer SEO pages (novostrojki-ot-<dev_slug>)
        try:
            dev_rows = db.session.execute(_txt('''
                SELECT DISTINCT d.slug AS dev_slug, rc.city_id
                FROM developers d
                JOIN residential_complexes rc ON rc.developer_id = d.id
                JOIN properties p ON p.complex_id = rc.id AND p.is_active = true
                WHERE d.slug IS NOT NULL AND length(d.slug) > 0 AND d.is_active = true
                GROUP BY d.slug, rc.city_id
                HAVING count(p.id) > 20
                ORDER BY count(p.id) DESC
            ''')).fetchall()
            for row in dev_rows:
                cs = city_map.get(row.city_id)
                if cs:
                    loc = f'{base_url}/{cs}/novostrojki-ot-{row.dev_slug}'
                    lines += _url_entry(loc, today, 'weekly', '0.72')
        except Exception:
            pass

        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'sitemap-seo-ext.xml error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-seo.xml  — legacy alias → seo-ext
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-seo.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def sitemap_seo_xml():
    """Legacy alias — redirects to sitemap-seo-ext.xml content."""
    return sitemap_seo_ext_xml()


# ---------------------------------------------------------------------------
# /sitemap-static.xml
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-static.xml', strict_slashes=False)
@cache.cached(timeout=7200)
def sitemap_static_xml():
    """Static pages sitemap (home, about, city hubs, mortgage pages, developers)."""
    try:
        from models import City, Developer
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')
        cities = City.query.filter_by(is_active=True).all()

        urls = [
            {'loc': base_url + '/',                        'priority': '1.0',  'changefreq': 'daily'},
            {'loc': base_url + '/properties',              'priority': '0.9',  'changefreq': 'daily'},
            {'loc': base_url + '/residential-complexes',   'priority': '0.9',  'changefreq': 'daily'},
            {'loc': base_url + '/map',                     'priority': '0.8',  'changefreq': 'daily'},
            {'loc': base_url + '/about',                   'priority': '0.7',  'changefreq': 'monthly'},
            {'loc': base_url + '/how-it-works',            'priority': '0.75', 'changefreq': 'monthly'},
            {'loc': base_url + '/blog',                    'priority': '0.8',  'changefreq': 'weekly'},
            {'loc': base_url + '/cashback-calculator',     'priority': '0.75', 'changefreq': 'monthly'},
            {'loc': base_url + '/slovar-nedvizhimosti',   'priority': '0.75', 'changefreq': 'monthly'},
            {'loc': base_url + '/developers',              'priority': '0.7',  'changefreq': 'weekly'},
            {'loc': base_url + '/contacts',                'priority': '0.6',  'changefreq': 'monthly'},
            {'loc': base_url + '/insurance',               'priority': '0.6',  'changefreq': 'monthly'},
            {'loc': base_url + '/appraisal',               'priority': '0.6',  'changefreq': 'monthly'},
            {'loc': base_url + '/careers',                 'priority': '0.5',  'changefreq': 'monthly'},
            {'loc': base_url + '/cashback-terms',          'priority': '0.5',  'changefreq': 'monthly'},
        ]

        _mortgage_slugs = [
            'ipoteka', 'semejnaya-ipoteka', 'it-ipoteka',
            'voennaya-ipoteka', 'ipoteka-ot-zastrojshchika',
            'materinsky-kapital', 'nalogovyj-vychet', 'strahovanie',
        ]

        for city in cities:
            urls.append({'loc': f"{base_url}/{city.slug}",                     'priority': '0.95', 'changefreq': 'daily'})
            urls.append({'loc': f"{base_url}/{city.slug}/novostrojki",          'priority': '0.9',  'changefreq': 'daily'})
            urls.append({'loc': f"{base_url}/{city.slug}/zhilye-kompleksy",     'priority': '0.9',  'changefreq': 'daily'})
            urls.append({'loc': f"{base_url}/{city.slug}/zastrojshchiki",       'priority': '0.8',  'changefreq': 'weekly'})
            urls.append({'loc': f"{base_url}/{city.slug}/cashback-kvartiry",    'priority': '0.75', 'changefreq': 'monthly'})
            urls.append({'loc': f"{base_url}/{city.slug}/kontakty",             'priority': '0.6',  'changefreq': 'monthly'})
            urls.append({'loc': f"{base_url}/{city.slug}/slovar-nedvizhimosti", 'priority': '0.7',  'changefreq': 'monthly'})
            for ms in _mortgage_slugs:
                urls.append({'loc': f"{base_url}/{city.slug}/{ms}", 'priority': '0.72', 'changefreq': 'monthly'})

        # Developer profile pages
        try:
            devs = Developer.query.filter(
                Developer.slug.isnot(None), Developer.slug != '', Developer.is_active == True
            ).with_entities(Developer.slug, Developer.updated_at).all()
            for dev in devs:
                lastmod_d = dev.updated_at.strftime('%Y-%m-%d') if getattr(dev, 'updated_at', None) else today
                urls.append({'loc': f"{base_url}/developer/{dev.slug}", 'priority': '0.65',
                             'changefreq': 'monthly', 'lastmod': lastmod_d})
        except Exception:
            pass

        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for u in urls:
            lines += ['  <url>', f'    <loc>{u["loc"]}</loc>',
                      f'    <lastmod>{u.get("lastmod", today)}</lastmod>',
                      f'    <changefreq>{u["changefreq"]}</changefreq>',
                      f'    <priority>{u["priority"]}</priority>', '  </url>']
        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'Sitemap static error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-complexes.xml
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-complexes.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def sitemap_complexes_xml():
    """Residential complexes sitemap."""
    try:
        from models import ResidentialComplex, City
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')

        complexes = ResidentialComplex.query.filter_by(is_active=True).outerjoin(
            City, ResidentialComplex.city_id == City.id
        ).with_entities(
            ResidentialComplex.slug, ResidentialComplex.name,
            ResidentialComplex.updated_at, City.slug.label('city_slug')
        ).all()

        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for c in complexes:
            lastmod = c.updated_at.strftime('%Y-%m-%d') if c.updated_at else today
            slug = c.slug or (c.name or '').lower().replace(' ', '-')
            city_prefix = c.city_slug or 'krasnodar'
            lines += _url_entry(f'{base_url}/{city_prefix}/zk/{slug}', lastmod, 'weekly', '0.8')
            if slug:
                lines += _url_entry(f'{base_url}/zk-{slug}', lastmod, 'weekly', '0.7')
        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'Sitemap complexes error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-blog.xml
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-blog.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def sitemap_blog_xml():
    """Blog posts sitemap."""
    try:
        from models import BlogPost
        base_url = CANONICAL_BASE_URL
        cutoff_recent = datetime.utcnow() - timedelta(days=90)

        posts = BlogPost.query.filter_by(status='published').with_entities(
            BlogPost.slug, BlogPost.updated_at, BlogPost.published_at
        ).order_by(BlogPost.published_at.desc()).all()

        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for p in posts:
            pub_dt = p.published_at or datetime.utcnow()
            lastmod = (p.updated_at or pub_dt).strftime('%Y-%m-%d')
            # Recent posts: weekly + 0.8; older posts: monthly + 0.7
            if pub_dt >= cutoff_recent:
                changefreq, priority = 'weekly', '0.8'
            else:
                changefreq, priority = 'monthly', '0.7'
            lines += _url_entry(f'{base_url}/blog/{p.slug}', lastmod, changefreq, priority)
        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'Sitemap blog error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-properties-<page>.xml
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-properties-<int:page>.xml')
@cache.cached(timeout=3600, key_prefix=lambda: f'sitemap_props_{request.view_args.get("page", 1)}')
def sitemap_properties_paged(page):
    """Paginated property sitemap — 10,000 URLs per file."""
    try:
        from models import Property as PropertyModel, City
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')
        per_page = 10000
        offset = (page - 1) * per_page

        properties = (PropertyModel.query
                      .filter(PropertyModel.is_active == True, PropertyModel.inner_id.isnot(None))
                      .with_entities(PropertyModel.inner_id, PropertyModel.updated_at, PropertyModel.city_id)
                      .order_by(PropertyModel.id)
                      .offset(offset).limit(per_page).all())

        if not properties and page > 1:
            abort(404)

        cities = {c.id: c.slug for c in City.query.filter_by(is_active=True).all()}

        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for prop in properties:
            city_slug = cities.get(prop.city_id, 'krasnodar')
            lastmod = prop.updated_at.strftime('%Y-%m-%d') if prop.updated_at else today
            lines += _url_entry(
                f'{base_url}/{city_slug}/object/{prop.inner_id}',
                lastmod, 'weekly', '0.7'
            )
        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'Sitemap properties page {page} error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-districts.xml
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-districts.xml', strict_slashes=False)
@cache.cached(timeout=7200)
def sitemap_districts_xml():
    """Districts sitemap for local SEO."""
    try:
        from models import District, City
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')

        cities = {c.id: c.slug for c in City.query.filter_by(is_active=True).all()}
        districts = District.query.filter(
            District.slug.isnot(None), District.slug != ''
        ).with_entities(District.slug, District.city_id).all()

        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        seen = set()
        for d in districts:
            city_slug = cities.get(d.city_id)
            if not city_slug:
                continue
            key = f'{city_slug}/{d.slug}'
            if key in seen:
                continue
            seen.add(key)
            lines += _url_entry(f'{base_url}/{city_slug}/rayon/{d.slug}',    today, 'weekly', '0.65')
            lines += _url_entry(f'{base_url}/{city_slug}/novostrojki-v-{d.slug}', today, 'weekly', '0.70')
        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'Sitemap districts error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-streets.xml
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-streets.xml', strict_slashes=False)
@cache.cached(timeout=7200)
def sitemap_streets_xml():
    """Streets sitemap — canonical /<city_slug>/ulitsa/<street_slug> URLs."""
    try:
        from models import Street, City
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')

        cities = {c.id: c.slug for c in City.query.filter_by(is_active=True).all()}
        streets = Street.query.filter(
            Street.slug.isnot(None), Street.slug != ''
        ).with_entities(Street.slug, Street.city_id).limit(50000).all()

        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        seen = set()
        for s in streets:
            city_slug = cities.get(s.city_id)
            if not city_slug:
                continue
            key = f'{city_slug}/{s.slug}'
            if key in seen:
                continue
            seen.add(key)
            lines += _url_entry(
                f'{base_url}/{city_slug}/ulitsa/{s.slug}',
                today, 'monthly', '0.5'
            )
        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'Sitemap streets error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-images.xml
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-images.xml')
@cache.cached(timeout=3600)
def sitemap_images():
    """Image sitemap for Google Image Search and Yandex Images."""
    try:
        from models import Property as PropertyModel, ResidentialComplex, City
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')
        cities = City.query.filter_by(is_active=True).all()
        city_slugs = {c.id: c.slug for c in cities}

        xml = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
            '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
        ]

        props = PropertyModel.query.filter(
            PropertyModel.is_active == True, PropertyModel.main_image != None
        ).with_entities(
            PropertyModel.inner_id, PropertyModel.id, PropertyModel.city_id,
            PropertyModel.main_image, PropertyModel.title, PropertyModel.rooms
        ).limit(20000).all()

        for p in props:
            prop_key = p.inner_id or str(p.id)
            if not prop_key or p.city_id not in city_slugs:
                continue
            photo = _proxy_image(p.main_image, base_url)
            if not photo:
                continue
            rooms_label = 'Студия' if p.rooms == 0 else f'{p.rooms}-комнатная'
            title = p.title or f'{rooms_label} квартира'
            xml += ['  <url>',
                    f'    <loc>{base_url}/{city_slugs[p.city_id]}/object/{prop_key}</loc>',
                    '    <image:image>',
                    f'      <image:loc>{photo}</image:loc>',
                    f'      <image:title>{title[:100]}</image:title>',
                    '    </image:image>',
                    '  </url>']

        complexes = ResidentialComplex.query.filter(
            ResidentialComplex.is_active == True, ResidentialComplex.main_image != None
        ).with_entities(
            ResidentialComplex.id, ResidentialComplex.slug, ResidentialComplex.name,
            ResidentialComplex.city_id, ResidentialComplex.main_image,
            ResidentialComplex.gallery_images
        ).limit(5000).all()

        for cx in complexes:
            if not cx.city_id or cx.city_id not in city_slugs:
                continue
            slug = cx.slug or str(cx.id)
            cx_title = cx.name if cx.name.startswith('ЖК') else f'ЖК {cx.name}'
            cx_photos = []
            main = _proxy_image(cx.main_image, base_url)
            if main:
                cx_photos.append(main)
            if cx.gallery_images:
                try:
                    gallery = (_json_img.loads(cx.gallery_images)
                               if isinstance(cx.gallery_images, str) else cx.gallery_images)
                    for g in (gallery or [])[:8]:
                        prox = _proxy_image(g, base_url)
                        if prox and prox not in cx_photos:
                            cx_photos.append(prox)
                            if len(cx_photos) >= 5:
                                break
                except Exception:
                    pass
            if not cx_photos:
                continue
            xml.append('  <url>')
            xml.append(f'    <loc>{base_url}/{city_slugs[cx.city_id]}/zk/{slug}</loc>')
            for i, photo in enumerate(cx_photos):
                img_title = cx_title if i == 0 else f'{cx_title} — фото {i + 1}'
                xml += ['    <image:image>',
                        f'      <image:loc>{photo}</image:loc>',
                        f'      <image:title>{img_title[:100]}</image:title>',
                        '    </image:image>']
            xml.append('  </url>')

        xml.append('</urlset>')
        return _xml_response(xml)
    except Exception as e:
        current_app.logger.error(f'Image sitemap error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# /sitemap-stats  (debug)
# ---------------------------------------------------------------------------

@seo_bp.route('/sitemap-stats')
def sitemap_stats():
    """Debug: sitemap URL count statistics."""
    if not current_app.debug:
        abort(404)
    try:
        from models import Property as PropertyModel, ResidentialComplex, BlogPost, City
        from routes.seo_city import _SEO_NOVOSTROJKI_SLUGS, _DISTRICT_MAP

        cities = City.query.filter_by(is_active=True).all()
        prop_count = PropertyModel.query.filter_by(is_active=True).count()
        rc_count = ResidentialComplex.query.filter_by(is_active=True).count()
        blog_count = BlogPost.query.filter_by(status='published').count()
        slug_count = len(_SEO_NOVOSTROJKI_SLUGS)
        district_count = len(_DISTRICT_MAP)
        programmatic_count = sum(
            len([c for c in cities if (not cfg.get('city_ids') or c.id in cfg['city_ids'])])
            for cfg in _SEO_NOVOSTROJKI_SLUGS.values()
        )
        district_seo_count = sum(
            len([c for c in cities if (not dv.get('city_ids') or c.id in dv['city_ids'])])
            for dv in _DISTRICT_MAP.values()
        )

        return jsonify({
            'cities': len(cities),
            'properties': prop_count,
            'complexes': rc_count,
            'blog_posts': blog_count,
            'seo_slugs': slug_count,
            'districts': district_count,
            'programmatic_urls': programmatic_count,
            'district_seo_urls': district_seo_count,
            'total_seo_pages': programmatic_count + district_seo_count,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# /sitemap-new-slugs.xml  — focused sitemap for route-only (non-dict) slugs
# Added 2026-06: 63 new SEO pages not yet in _SEO_NOVOSTROJKI_SLUGS dict
# ---------------------------------------------------------------------------

# Exact list of route-registered slugs that have NO entry in _SEO_NOVOSTROJKI_SLUGS.
# These have @seo_city_bp.route decorators so they are live pages, but the
# programmatic sitemap only iterates the dict — so they'd be missed otherwise.
_NEW_ROUTE_SLUGS = [
    '1-komnatnye-s-otdelkoy-do-5-mln', '1-komnatnye-sdacha-2030',
    '1-komnatnye-voennaya-ipoteka', '2-komnatnye-s-otdelkoy-do-8-mln',
    '2-komnatnye-sdacha-2030', '2-komnatnye-voennaya-ipoteka',
    '3-komnatnye-s-otdelkoy-do-15-mln', '3-komnatnye-sdacha-2030',
    '3-komnatnye-voennaya-ipoteka', '4-komnatnye-materinskiy-kapital',
    '4-komnatnye-sdacha-2030', 'apartamenty-v-novostroyke',
    'dolevoe-stroitelstvo', 'escrow-schet-novostrojki',
    'investicii-v-novostrojki-2026', 'investicii-v-studii',
    'ipoteka-bez-pervogo-vznosa-2026', 'it-ipoteka-bez-pervogo-vznosa',
    'it-ipoteka-do-12-mln', 'it-ipoteka-komfort-klass',
    'kottedzhi-v-novostroyke', 'kupit-kvartiru-po-ddu',
    'kvartiry-bez-pereplaty', 'kvartiry-po-ddu', 'kvartiry-po-eskrou',
    'kvartiry-pod-sdachu-posutochno', 'kvartiry-s-bolshim-metrajom',
    'kvartiry-s-dvumya-sanuzlami', 'kvartiry-s-garderobom',
    'kvartiry-s-kuhney-gostinej', 'kvartiry-s-masterom-spalnej',
    'kvartiry-s-matkapitalom-2026', 'kvartiry-v-sochi-v-rassrochku',
    'materinskiy-kapital-na-kvartiru', 'nedvizhimost-dlya-sdachi',
    'novostrojki-bez-pervogo-vznosa', 'novostrojki-krasnodarskiy-kray',
    'novostrojki-ot-3-5-mln', 'novostrojki-ot-4-mln',
    'novostrojki-ot-6-mln', 'novostrojki-ot-7-mln',
    'novostrojki-s-aktsiyami-2026', 'novostrojki-starti-prodazh-2026',
    'novostrojki-v-adlerskom-rajone', 'novostrojki-v-anape',
    'novostrojki-v-armavire', 'novostrojki-v-gelendzhike',
    'novostrojki-v-lazarevskom-rajone', 'novostrojki-v-novorossiyske',
    'semejnye-kvartiry-s-detskim-sadom', 'semeynaya-ipoteka-2027',
    'semeynaya-ipoteka-do-15-mln', 'semeynaya-ipoteka-v-novostroyke',
    'studii-dlya-sdachi-v-arendu', 'studii-s-otdelkoy-do-4-mln',
    'studii-sdacha-2030', 'studii-v-sochi', 'studii-voennaya-ipoteka',
    'taunhauzy-v-novostroyke', 'voennaya-ipoteka',
    'voennaya-ipoteka-2026', 'voennaya-ipoteka-s-otdelkoy',
    # Specialty Краснодарский край
    'novostrojki-v-rajone-gidrostroya',
]

_CITY_SCOPE_OVERRIDES = {
    'novostrojki-v-adlerskom-rajone': [2],   # Sochi only
    'novostrojki-v-lazarevskom-rajone': [2],
    'kvartiry-v-sochi-v-rassrochku': [2],
    'studii-v-sochi': [2],
    'novostrojki-v-anape': [],
    'novostrojki-v-armavire': [],
    'novostrojki-v-gelendzhike': [],
    'novostrojki-v-novorossiyske': [],
}


@seo_bp.route('/sitemap-new-slugs.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def sitemap_new_slugs_xml():
    """Focused sitemap for the ~63 new SEO pages added in June 2026.
    These have route decorators in seo_city_bp but no entry in _SEO_NOVOSTROJKI_SLUGS,
    so they're missing from sitemap-programmatic.xml.
    """
    try:
        from models import City, ResidentialComplex
        base_url = CANONICAL_BASE_URL
        today = datetime.utcnow().strftime('%Y-%m-%d')

        cities = City.query.filter_by(is_active=True).all()

        # Pre-fetch city images for image:image tags
        city_image_map = {}
        try:
            rc_imgs = (ResidentialComplex.query
                       .filter(ResidentialComplex.city_id.in_([c.id for c in cities]),
                               ResidentialComplex.is_active == True,
                               ResidentialComplex.main_image.isnot(None),
                               ResidentialComplex.main_image != '')
                       .with_entities(ResidentialComplex.city_id, ResidentialComplex.main_image)
                       .distinct(ResidentialComplex.city_id)
                       .all())
            for row in rc_imgs:
                city_image_map[row.city_id] = _proxy_image(row.main_image, base_url)
        except Exception:
            pass

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<!-- InBack New SEO Slugs Sitemap | {today} | {len(_NEW_ROUTE_SLUGS)} slugs -->',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
            '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
        ]

        for slug in _NEW_ROUTE_SLUGS:
            allowed = _CITY_SCOPE_OVERRIDES.get(slug, None)
            if allowed is not None:
                target_cities = [c for c in cities if c.id in allowed] if allowed else cities
            else:
                target_cities = cities

            priority, changefreq = _slug_priority(slug)

            for city in target_cities:
                loc = f'{base_url}/{city.slug}/{slug}'
                img_url = city_image_map.get(city.id)
                lines += _url_entry(
                    loc, today, changefreq, priority,
                    image_loc=img_url,
                    image_title=f'Новостройки {city.name} — {slug.replace("-", " ")} | InBack' if img_url else None,
                )

        lines.append('</urlset>')
        return _xml_response(lines)
    except Exception as e:
        current_app.logger.error(f'sitemap-new-slugs.xml error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# Admin: clear sitemap cache
# ---------------------------------------------------------------------------

@seo_bp.route('/admin/sitemap/clear-cache', methods=['POST'])
def sitemap_clear_cache():
    """Admin endpoint to invalidate all sitemap caches."""
    from flask_login import current_user
    try:
        from models import Admin as _Admin
        if not (current_user.is_authenticated and
                isinstance(current_user._get_current_object(), _Admin)):
            abort(403)
    except Exception:
        abort(403)
    try:
        cache.clear()
        return jsonify({'ok': True, 'message': 'All caches cleared'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Google verification
# ---------------------------------------------------------------------------

@seo_bp.route('/google873bf5c5df6b6710.html')
def google_verification():
    """Google Search Console verification file."""
    return 'google-site-verification: google873bf5c5df6b6710.html'


# ---------------------------------------------------------------------------
# Blog RSS feed
# ---------------------------------------------------------------------------

@seo_bp.route('/blog/rss.xml', strict_slashes=False)
@cache.cached(timeout=3600)
def blog_rss_feed():
    """RSS 2.0 feed for blog posts."""
    try:
        from models import BlogPost
        base_url = CANONICAL_BASE_URL
        posts = BlogPost.query.filter_by(status='published').order_by(
            BlogPost.published_at.desc()
        ).limit(20).all()

        def _esc(s):
            if not s:
                return ''
            return (s.replace('&', '&amp;').replace('<', '&lt;')
                    .replace('>', '&gt;').replace('"', '&quot;'))

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
            '  <channel>',
            '    <title>InBack.ru — блог о недвижимости и кэшбеке</title>',
            f'    <link>{base_url}/blog</link>',
            '    <description>Полезные статьи о покупке новостроек, ипотеке и кэшбеке в Краснодаре и Сочи</description>',
            '    <language>ru</language>',
            f'    <atom:link href="{base_url}/blog/rss.xml" rel="self" type="application/rss+xml"/>',
            f'    <lastBuildDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</lastBuildDate>',
        ]
        for p in posts:
            pub_date = (p.published_at or p.created_at or datetime.utcnow()).strftime('%a, %d %b %Y %H:%M:%S +0000')
            post_url = f'{base_url}/blog/{p.slug}'
            lines += ['    <item>',
                      f'      <title>{_esc(p.title)}</title>',
                      f'      <link>{post_url}</link>',
                      f'      <guid isPermaLink="true">{post_url}</guid>',
                      f'      <pubDate>{pub_date}</pubDate>',
                      f'      <description>{_esc((p.excerpt or p.content or "")[:300])}</description>',
                      '    </item>']
        lines += ['  </channel>', '</rss>']

        r = current_app.response_class(response='\n'.join(lines), status=200, mimetype='application/rss+xml')
        r.headers['Content-Type'] = 'application/rss+xml; charset=utf-8'
        return r
    except Exception as e:
        current_app.logger.error(f'RSS feed error: {e}')
        abort(500)


# ---------------------------------------------------------------------------
# IndexNow key verification file  — /<key>.txt  (required by IndexNow protocol)
# ---------------------------------------------------------------------------

@seo_bp.route('/<string:key_file>.txt')
def indexnow_key_file(key_file):
    """Serve IndexNow key verification file at /<INDEXNOW_KEY>.txt"""
    import os as _os
    indexnow_key = _os.environ.get('INDEXNOW_KEY', '')
    if not indexnow_key or key_file != indexnow_key:
        abort(404)
    return current_app.response_class(
        response=indexnow_key, status=200, mimetype='text/plain'
    )


# ---------------------------------------------------------------------------
# Robots.txt (dynamic — supersedes static/robots.txt)
# ---------------------------------------------------------------------------

@seo_bp.route('/robots.txt')
def robots_txt():
    """Robots.txt — explicitly lists ALL sub-sitemaps for faster Googlebot/Yandex discovery."""
    base_url = CANONICAL_BASE_URL
    content = f"""User-agent: *
Allow: /

# Закрытые разделы (не для индексации)
Disallow: /admin/
Disallow: /manager/
Disallow: /auth/
Disallow: /p_/
Disallow: /uploads/
Disallow: /static/temp/
Disallow: /login
Disallow: /register
Disallow: /logout
Disallow: /invite/
Disallow: /wallet
Disallow: /profile/
Disallow: /api/
Disallow: /debug/
Disallow: /partner/

# Низкоценные URL-параметры — экономия crawl budget
Disallow: /*?price_min=
Disallow: /*?price_max=
Disallow: /*?price_sqm_min=
Disallow: /*?price_sqm_max=
Disallow: /*?area_min=
Disallow: /*?area_max=
Disallow: /*?completion=
Disallow: /*?building_status=
Disallow: /*?print=
Disallow: /*?floor_min=
Disallow: /*?floor_max=
Disallow: /*?sort=
Disallow: /*?view=
Disallow: /*?tab=
Disallow: /*?modal=

# Технические страницы
Disallow: /*?*replit*

# Разрешаем важные статические ресурсы
Allow: /static/css/
Allow: /static/js/
Allow: /static/images/
Allow: /static/webfonts/

# ── Карты сайта (перечислены все — для быстрого обхода) ──────────────────────
Sitemap: {base_url}/sitemap.xml
Sitemap: {base_url}/sitemap-new-slugs.xml
Sitemap: {base_url}/sitemap-programmatic.xml
Sitemap: {base_url}/sitemap-static.xml
Sitemap: {base_url}/sitemap-seo-ext.xml
Sitemap: {base_url}/sitemap-complexes.xml
Sitemap: {base_url}/sitemap-blog.xml
Sitemap: {base_url}/sitemap-images.xml
Sitemap: {base_url}/sitemap-districts.xml
Sitemap: {base_url}/sitemap-streets.xml

# --- Googlebot ---
User-agent: Googlebot
Crawl-delay: 1

# --- Yandex ---
User-agent: Yandex
Crawl-delay: 1
Host: inback.ru
Clean-param: utm_source&utm_medium&utm_campaign&utm_term&utm_content&yclid&gclid&fbclid&ref&from&_openstat

# --- Bing ---
User-agent: Bingbot
Crawl-delay: 2

# --- Блокировка агрессивных SEO-ботов (экономия трафика) ---
User-agent: SemrushBot
Disallow: /

User-agent: AhrefsBot
Disallow: /

User-agent: MJ12bot
Disallow: /

User-agent: DotBot
Disallow: /

User-agent: PetalBot
Disallow: /

User-agent: Bytespider
Disallow: /

User-agent: GPTBot
Disallow: /

User-agent: CCBot
Disallow: /

User-agent: anthropic-ai
Disallow: /"""

    return current_app.response_class(response=content, status=200, mimetype='text/plain')
