"""
Streets Blueprint — streets listing and detail pages (multi-city).
Endpoints: streets, streets_city, street_detail, street_city_detail
"""
import math
import os
import re
import urllib.parse

from flask import (Blueprint, abort, redirect, render_template,
                   request, url_for)
from flask import current_app
from sqlalchemy import text, or_

from app import db

streets_bp = Blueprint('streets', __name__)


def _resolve_city_context(**kwargs):
    from app import resolve_city_context
    return resolve_city_context(**kwargs)


def _redirect_to_city_based(endpoint):
    from app import redirect_to_city_based as _r
    return _r(endpoint)


# ─── Streets listing ─────────────────────────────────────────────────────────

@streets_bp.route('/ulitsy')
@streets_bp.route('/streets')
def streets():
    """Redirect to city-based URL"""
    return _redirect_to_city_based('streets_city')


def _render_streets_page(current_city):
    """Render streets listing for the current city (any city)."""
    if not current_city:
        return render_template('streets.html', current_city=current_city, streets=[])

    streets_db = db.session.execute(text("""
        SELECT name, slug, district_id, city_id
        FROM streets
        WHERE city_id = :cid
        ORDER BY name
    """), {'cid': current_city.id}).fetchall()

    districts_db = db.session.execute(text("""
        SELECT id, name FROM districts WHERE city_id = :cid
    """), {'cid': current_city.id}).fetchall()
    districts_map = {d.id: d.name for d in districts_db}

    streets_data = []
    for street in streets_db:
        first_char = street.name[0].upper() if street.name else 'А'
        streets_data.append({
            'name': street.name,
            'slug': street.slug,
            'district': districts_map.get(street.district_id, ''),
            'letter': first_char,
            'properties_count': 0,
            'new_buildings': 0
        })

    return render_template('streets.html',
                           current_city=current_city,
                           streets=streets_data)


# ─── Canonical street URL: /<city_slug>/ulitsa/<street_slug> ─────────────────

@streets_bp.route('/<city_slug>/ulitsa/<path:street_slug>')
def street_city_detail(city_slug, street_slug):
    """Canonical multi-city street detail."""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        abort(404)
    return _render_street_detail(street_slug, current_city)


# ─── Legacy redirect /streets/<name> → /street/<slug> ────────────────────────

@streets_bp.route('/streets/<path:street_name>')
def streets_redirect(street_name):
    decoded_name = urllib.parse.unquote(street_name)
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    name = decoded_name.strip().lower()
    name = re.sub(r'[«»"\(\)\.,:;]', '', name)
    result = ''
    for char in name:
        result += translit_map.get(char, char)
    result = re.sub(r'\s+', '-', result)
    result = re.sub(r'-+', '-', result)
    slug = result.strip('-')
    return redirect(url_for('streets.street_detail', street_name=slug), code=301)


# ─── Legacy street detail /street/<slug> ─────────────────────────────────────

@streets_bp.route('/street/<path:street_name>')
def street_detail(street_name):
    """Individual street page — resolves city from session, redirects to canonical."""
    current_city = _resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )
    if current_city:
        return redirect(f'/{current_city.slug}/ulitsa/{street_name}', code=301)
    return _render_street_detail(street_name, current_city)


# ─── Core street renderer ─────────────────────────────────────────────────────

def _render_street_detail(street_slug, current_city):
    """Render street detail page for any city."""
    try:
        city_id = current_city.id if current_city else None
        city_center_lat = float(current_city.latitude) if (current_city and current_city.latitude) else 45.0448
        city_center_lng = float(current_city.longitude) if (current_city and current_city.longitude) else 38.9760

        # Try to find street by slug, optionally scoped to city
        if city_id:
            street_db = db.session.execute(text("""
                SELECT name, slug, latitude, longitude, zoom_level, geometry,
                       geometry_source, city_id
                FROM streets
                WHERE slug = :slug AND city_id = :cid
                LIMIT 1
            """), {'slug': street_slug, 'cid': city_id}).fetchone()
        else:
            street_db = None

        if not street_db:
            street_db = db.session.execute(text("""
                SELECT name, slug, latitude, longitude, zoom_level, geometry,
                       geometry_source, city_id
                FROM streets
                WHERE slug = :slug
                LIMIT 1
            """), {'slug': street_slug}).fetchone()

        if not street_db:
            abort(404)

        name_lower = street_db.name.lower()
        if 'проезд' in name_lower:
            street_type, street_type_nom = 'проезде', 'проезд'
        elif 'переулок' in name_lower or 'пер.' in name_lower:
            street_type, street_type_nom = 'переулке', 'переулок'
        elif 'бульвар' in name_lower:
            street_type, street_type_nom = 'бульваре', 'бульвар'
        elif 'площадь' in name_lower:
            street_type, street_type_nom = 'площади', 'площадь'
        elif 'шоссе' in name_lower:
            street_type, street_type_nom = 'шоссе', 'шоссе'
        elif 'проспект' in name_lower:
            street_type, street_type_nom = 'проспекте', 'проспект'
        else:
            street_type, street_type_nom = 'улице', 'улица'

        if street_db.latitude and street_db.longitude:
            s_lat = float(street_db.latitude)
            s_lng = float(street_db.longitude)
        else:
            s_lat, s_lng = city_center_lat, city_center_lng

        lat_diff = s_lat - city_center_lat
        lng_diff = s_lng - city_center_lng
        distance_to_center = round(math.sqrt(lat_diff**2 + lng_diff**2) * 111, 1)

        if distance_to_center < 3:
            location_zone = 'центре города'
        elif distance_to_center < 7:
            location_zone = 'средней зоне города'
        else:
            location_zone = 'отдалённой зоне города'

        city_name = current_city.name if current_city else 'Краснодаре'
        city_slug = current_city.slug if current_city else 'krasnodar'

        variation = ord(street_db.name[0].upper()) % 4 if street_db.name else 0
        advantages = [
            ['современными ЖК', 'развитой инфраструктурой', 'отличной транспортной доступностью'],
            ['проверенными застройщиками', 'высоким инвестиционным потенциалом', 'удобным расположением'],
            ['качественными новостройками', 'перспективным районом', 'близостью к центру'],
            ['надёжными девелоперами', 'комфортной средой', 'активным развитием района']
        ][variation]
        why_buy = [
            'выгодное расположение и хорошая транспортная доступность',
            'развитая инфраструктура и близость ко всем необходимым объектам',
            'перспективный район с высоким инвестиционным потенциалом',
            'комфортные условия для жизни и активное развитие территории'
        ][variation]

        canonical = f'/{city_slug}/ulitsa/{street_slug}'

        street = {
            'name': street_db.name,
            'slug': street_db.slug,
            'district': '',
            'description': f'{street_type_nom.capitalize()} {street_db.name} в {city_name}',
            'geometry': street_db.geometry,
            'geometry_source': street_db.geometry_source,
            'street_type': street_type,
            'street_type_nominative': street_type_nom,
            'distance_to_center': distance_to_center,
            'location_zone': location_zone,
            'advantages': advantages,
            'why_buy': why_buy,
            'canonical': canonical,
        }

        # Load properties from DB: geo-bbox first, then text fallback
        properties_on_street = []
        try:
            from models import Property
            from utils.geo import geometry_bbox

            seen_ids = set()
            geo_props = []

            # ── Geo bbox for streets (streets are linear, use ~400m buffer) ────
            geom = street_db.geometry if hasattr(street_db, 'geometry') else None
            if geom:
                bbox = geometry_bbox(geom)
                if bbox:
                    min_lat, min_lng, max_lat, max_lng = bbox
                    buf = 0.004  # ~400m buffer for streets
                    base_q = Property.query.filter(
                        Property.is_active == True,
                        Property.latitude >= min_lat - buf,
                        Property.latitude <= max_lat + buf,
                        Property.longitude >= min_lng - buf,
                        Property.longitude <= max_lng + buf,
                    )
                    if city_id:
                        base_q = base_q.filter(Property.city_id == city_id)
                    for p in base_q.limit(50).all():
                        seen_ids.add(p.id)
                        geo_props.append(p)

            # ── Text fallback for remaining ────────────────────────────────────
            text_q = Property.query.filter(
                Property.is_active == True,
                Property.parsed_street.ilike(f'%{street_db.name}%')
            )
            if city_id:
                text_q = text_q.filter(Property.city_id == city_id)
            for p in text_q.limit(20).all():
                if p.id not in seen_ids:
                    geo_props.append(p)

            geo_props.sort(key=lambda p: p.price or 0)

            properties_on_street = [
                {
                    'id': p.id,
                    'title': p.title or f'Квартира {p.rooms}к',
                    'address': p.address or '',
                    'price': p.price or 0,
                    'price_display': f'{int((p.price or 0) / 1_000_000):.1f} млн ₽' if p.price else '—',
                    'rooms': p.rooms,
                    'area': float(p.area or 0),
                }
                for p in geo_props[:20]
            ]
        except Exception:
            pass

        return render_template(
            'street_detail.html',
            current_city=current_city,
            street=street,
            coordinates={'lat': s_lat, 'lng': s_lng},
            properties=properties_on_street,
            canonical_url=canonical,
            title=f'{street_db.name} в {city_name} — новостройки с кэшбеком | InBack',
            yandex_api_key=os.environ.get('YANDEX_MAPS_API_KEY', '')
        )

    except Exception as e:
        current_app.logger.error(f"Error in street_detail for {street_slug}: {e}")
        abort(404)
