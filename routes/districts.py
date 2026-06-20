"""
routes/districts.py — District listing, canonical detail pages, and API (multi-city).
"""
import json
import os

from flask import (Blueprint, abort, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from sqlalchemy import or_, text

from app import db, resolve_city_context

bp = Blueprint('districts', __name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _infra_dict(d):
    infra = d.infrastructure_data or {}
    if isinstance(infra, str):
        try:
            infra = json.loads(infra)
        except Exception:
            infra = {}
    return {
        'education_count':  infra.get('education_count') or infra.get('schools'),
        'medical_count':    infra.get('medical_count')   or infra.get('hospitals'),
        'shopping_count':   infra.get('shopping_count')  or infra.get('shops'),
        'finance_count':    infra.get('finance_count')   or infra.get('banks'),
        'leisure_count':    infra.get('leisure_count')   or infra.get('parks'),
        'transport_count':  infra.get('transport_count') or infra.get('transport'),
        'distance_to_center': getattr(d, 'distance_to_center', None),
    }


def _district_to_dict(d):
    dtype = getattr(d, 'district_type', None) or 'okrug'
    type_labels = {
        'okrug': ('Округ', 'bg-blue-100 text-blue-700'),
        'microrayon': ('Микрорайон', 'bg-green-100 text-green-700'),
        'settlement': ('Посёлок', 'bg-amber-100 text-amber-700'),
    }
    label, badge_cls = type_labels.get(dtype, ('Район', 'bg-gray-100 text-gray-600'))
    return {
        'id':               d.id,
        'name':             d.name,
        'slug':             d.slug or d.name.lower().replace(' ', '-'),
        'city_id':          d.city_id,
        'district_type':    dtype,
        'type_label':       label,
        'type_badge_cls':   badge_cls,
        'description':      getattr(d, 'description', None) or f'Новостройки в районе {d.name} с кэшбеком до 500 000 ₽',
        'latitude':         float(d.latitude)  if d.latitude  else None,
        'longitude':        float(d.longitude) if d.longitude else None,
        'distance_to_center': getattr(d, 'distance_to_center', None),
        'infrastructure_data': _infra_dict(d),
        'geometry':         getattr(d, 'geometry', None),
    }


# ── Districts listing ─────────────────────────────────────────────────────────

@bp.route('/<city_slug>/rayony')
@bp.route('/<city_slug>/districts')
def districts_city(city_slug):
    """City-slug districts page."""
    current_city = resolve_city_context(city_slug=city_slug)
    return _render_districts(current_city)


@bp.route('/districts')
def districts():
    """Districts listing page — filters by current city."""
    current_city = resolve_city_context()
    return _render_districts(current_city)


def _render_districts(current_city):
    from models import District as DM, Property
    from sqlalchemy import func

    query = DM.query.filter(DM.name.isnot(None))
    if current_city:
        query = query.filter(DM.city_id == current_city.id)
    db_districts = query.order_by(DM.name).all()

    if not db_districts:
        return render_template('districts.html',
                               districts=[],
                               current_city=current_city,
                               yandex_api_key=os.environ.get('YANDEX_MAPS_API_KEY'))

    district_ids = [d.id for d in db_districts]
    stats_rows = db.session.query(
        Property.district_id,
        func.count(Property.id).label('props_count'),
        func.avg(Property.price_per_sqm).label('avg_price_sqm'),
        func.min(Property.price).label('min_price'),
        func.max(Property.price).label('max_price'),
        func.avg(Property.price).label('avg_price'),
    ).filter(
        Property.district_id.in_(district_ids),
        Property.is_active == True,
        Property.price > 0,
    ).group_by(Property.district_id).all()

    stats_by_id = {r.district_id: r for r in stats_rows}

    all_sqm = [int(stats_by_id[d.id].avg_price_sqm) for d in db_districts
               if d.id in stats_by_id and stats_by_id[d.id].avg_price_sqm]
    max_sqm = max(all_sqm) if all_sqm else 1
    min_sqm = min(all_sqm) if all_sqm else 0

    districts_list = []
    for d in db_districts:
        base = _district_to_dict(d)
        st = stats_by_id.get(d.id)
        base['props_count'] = int(st.props_count) if st else 0
        base['avg_price_sqm'] = int(st.avg_price_sqm) if st and st.avg_price_sqm else None
        base['min_price'] = int(st.min_price) if st and st.min_price else None
        base['max_price'] = int(st.max_price) if st and st.max_price else None
        base['avg_price'] = int(st.avg_price) if st and st.avg_price else None
        sqm = base['avg_price_sqm'] or 0
        base['price_bar_pct'] = int((sqm - min_sqm) / max(max_sqm - min_sqm, 1) * 100) if sqm else 0
        districts_list.append(base)

    # Sort: most popular first, then by name
    districts_list.sort(key=lambda x: (-x['props_count'], x['name']))

    # Filter out ЖК/СНТ entries that incorrectly ended up in the districts table
    _jk_prefixes = ('жилой комплекс', 'жк ', 'жк«', 'жк"', 'снт ', 'днп ', 'коттеджный')
    def _is_real_district(d):
        n = d['name'].lower()
        return not any(n.startswith(p) for p in _jk_prefixes)
    districts_list = [d for d in districts_list if _is_real_district(d)]

    # CIAN-style: group by type — active ones first
    okrugs      = [d for d in districts_list if d['district_type'] == 'okrug']
    microrayons = [d for d in districts_list if d['district_type'] == 'microrayon']
    settlements = [d for d in districts_list if d['district_type'] == 'settlement']

    return render_template('districts.html',
                           districts=districts_list,
                           okrugs=okrugs,
                           microrayons=microrayons,
                           settlements=settlements,
                           current_city=current_city,
                           max_price_sqm=max_sqm,
                           min_price_sqm=min_sqm,
                           yandex_api_key=os.environ.get('YANDEX_MAPS_API_KEY'))


# ── Canonical district detail: /<city_slug>/rayon/<district_slug> ─────────────

@bp.route('/<city_slug>/rayon/<district_slug>')
def district_city_detail(city_slug, district_slug):
    """Canonical multi-city district detail page."""
    current_city = resolve_city_context(city_slug=city_slug)
    if not current_city:
        abort(404)
    return _render_district_detail(district_slug, current_city, city_slug)


# ── CIAN-style SEO URL: /<city>/novostrojki-v-<district_slug> ─────────────────

@bp.route('/<city_slug>/novostrojki-v-<district_slug>')
def district_newbuilds(city_slug, district_slug):
    """CIAN-style URL: /krasnodar/novostrojki-v-tsentralnyy
    Renders the same district detail page as /rayon/<slug>.
    """
    current_city = resolve_city_context(city_slug=city_slug)
    if not current_city:
        abort(404)
    return _render_district_detail(district_slug, current_city, city_slug)


# ── API: search properties by district polygon ────────────────────────────────

@bp.route('/api/district/<district_slug>/properties')
def api_district_properties(district_slug):
    """CIAN-like: return all properties inside district polygon via PIP.
    Supports ?city_id=&limit=&offset= query params.
    Used by map/search to show objects inside a selected neighborhood.
    """
    from models import District as DM, Property
    from utils.geo import geometry_bbox, point_in_geometry

    city_id = request.args.get('city_id', type=int)
    limit   = min(request.args.get('limit', 100, type=int), 500)
    offset  = request.args.get('offset', 0, type=int)

    d = DM.query.filter_by(slug=district_slug).first()
    if not d:
        return jsonify({'error': 'District not found'}), 404

    # Fast path: use FK assignment
    fk_props = Property.query.filter(
        Property.is_active == True,
        Property.district_id == d.id,
    )
    if city_id:
        fk_props = fk_props.filter(Property.city_id == city_id)
    fk_list = fk_props.order_by(Property.price).all()

    # Geo PIP for properties in bbox that may be assigned elsewhere
    geo_extra = []
    seen = {p.id for p in fk_list}
    if d.geometry:
        bb = geometry_bbox(d.geometry)
        if bb:
            min_lat, min_lng, max_lat, max_lng = bb
            buf = 0.002
            q = Property.query.filter(
                Property.is_active == True,
                Property.latitude.between(min_lat - buf, max_lat + buf),
                Property.longitude.between(min_lng - buf, max_lng + buf),
            )
            if city_id:
                q = q.filter(Property.city_id == city_id)
            for p in q.limit(3000).all():
                if p.id not in seen and p.latitude and p.longitude:
                    if point_in_geometry(float(p.latitude), float(p.longitude), d.geometry):
                        geo_extra.append(p)
                        seen.add(p.id)

    all_props = fk_list + geo_extra
    total = len(all_props)
    page_props = all_props[offset:offset + limit]

    return jsonify({
        'district': d.name,
        'district_type': d.district_type,
        'total': total,
        'offset': offset,
        'limit': limit,
        'properties': [
            {
                'id': p.id,
                'title': p.title or '',
                'address': p.address or '',
                'price': p.price,
                'price_sqm': p.price_per_sqm,
                'rooms': p.rooms,
                'area': float(p.area or 0),
                'lat': float(p.latitude) if p.latitude else None,
                'lng': float(p.longitude) if p.longitude else None,
                'url': f'/{p.city.slug if p.city else "krasnodar"}/object/{p.id}',
            }
            for p in page_props
        ]
    })


# ── Legacy /district/<slug> → redirect to canonical ──────────────────────────

@bp.route('/district/tec')
def district_tec_redirect():
    return redirect(url_for('districts.district_detail', district='tets'), code=301)

@bp.route('/district/mkg')
def district_mkg_redirect():
    return redirect(url_for('districts.district_detail', district='mhg'), code=301)

@bp.route('/district/skhi')
def district_skhi_redirect():
    return redirect(url_for('districts.district_detail', district='shi'), code=301)


@bp.route('/district/<district>')
def district_detail(district):
    """Legacy URL — redirect to canonical /<city_slug>/rayon/<slug> if possible."""
    from models import District as DM
    current_city = resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )

    district_db = DM.query.filter_by(slug=district).first()
    if district_db:
        from models import City
        city = City.query.get(district_db.city_id)
        if city:
            return redirect(f'/{city.slug}/rayon/{district}', code=301)

    if current_city:
        return redirect(f'/{current_city.slug}/rayon/{district}', code=301)

    return redirect(f'/krasnodar/rayon/{district}', code=301)


# ── Core district detail renderer (used by both routes) ──────────────────────

def _normalize_district_slug(slug):
    """Return a list of fallback slugs to try when exact match fails."""
    candidates = [slug]
    # Strip common suffixes that appear in external links/maps
    for suffix in ('-okrug', '-rayon', '-mkr', '-mikrorayon', '-district', '-округ'):
        if slug.endswith(suffix):
            candidates.append(slug[: -len(suffix)])
    # Also try stripping trailing type words split by last dash
    parts = slug.rsplit('-', 1)
    if len(parts) == 2:
        candidates.append(parts[0])
    return candidates


def _render_district_detail(district_slug, current_city, city_slug):
    from models import District, Property, ResidentialComplex

    district_db = District.query.filter_by(
        slug=district_slug, city_id=current_city.id
    ).first()

    if not district_db:
        district_db = District.query.filter_by(slug=district_slug).first()

    # Fuzzy fallback: try normalized slugs and ILIKE prefix match
    if not district_db:
        for candidate in _normalize_district_slug(district_slug):
            if candidate == district_slug:
                continue
            district_db = District.query.filter_by(
                slug=candidate, city_id=current_city.id
            ).first()
            if district_db:
                # Redirect to canonical slug so URL stays clean
                return redirect(f'/{city_slug}/rayon/{district_db.slug}', code=301)

        # Last resort: ILIKE prefix on slug within the city
        prefix = district_slug[:6]
        district_db = District.query.filter(
            District.city_id == current_city.id,
            District.slug.ilike(f'{prefix}%')
        ).first()
        if district_db:
            return redirect(f'/{city_slug}/rayon/{district_db.slug}', code=301)

    if not district_db:
        abort(404)

    district_name = district_db.name

    try:
        from utils.geo import geometry_bbox, point_in_geometry

        # ── Step 1: properties assigned to this district by FK ─────────────────
        props_by_id = Property.query.filter(
            Property.is_active == True,
            Property.city_id == current_city.id,
            Property.district_id == district_db.id,
        ).order_by(Property.price).limit(100).all()

        seen_ids = {p.id for p in props_by_id}

        # ── Step 2: geo-polygon PIP — all properties in bbox, any assignment ─────
        # For microrayons: properties may already be assigned to parent okrug,
        # so we check ALL properties with coords inside the polygon (not just NULL).
        geo_props = []
        geom = district_db.geometry
        if geom:
            bbox = geometry_bbox(geom)
            if bbox:
                min_lat, min_lng, max_lat, max_lng = bbox
                buf = 0.002
                q = Property.query.filter(
                    Property.is_active == True,
                    Property.city_id == current_city.id,
                    Property.latitude >= min_lat - buf,
                    Property.latitude <= max_lat + buf,
                    Property.longitude >= min_lng - buf,
                    Property.longitude <= max_lng + buf,
                )
                # For large okruga limit candidates to avoid slow PIP on huge set
                is_okrug = getattr(district_db, 'district_type', '') == 'okrug'
                candidates = q.limit(2000 if is_okrug else 5000).all()
                for p in candidates:
                    if p.id not in seen_ids and p.latitude and p.longitude:
                        if point_in_geometry(float(p.latitude), float(p.longitude), geom):
                            geo_props.append(p)
                            seen_ids.add(p.id)

        # ── Step 3: text fallback for properties with no geo ──────────────────
        text_props = Property.query.filter(
            Property.is_active == True,
            Property.city_id == current_city.id,
            Property.district_id == None,
            Property.latitude == None,
            Property.address.ilike(f'%{district_name}%')
        ).limit(20).all()
        for p in text_props:
            if p.id not in seen_ids:
                geo_props.append(p)

        all_props = (props_by_id + geo_props)[:100]
        all_props.sort(key=lambda p: p.price or 0)

        district_properties_db = all_props

        district_properties = [
            {
                'id': p.id,
                'title': p.title or f'Квартира {p.rooms}к',
                'address': p.address or '',
                'price': p.price or 0,
                'price_display': f'{int((p.price or 0) / 1_000_000):.1f} млн ₽' if p.price else '—',
                'rooms': p.rooms,
                'area': float(p.area or 0),
                'floor': p.floor,
                'total_floors': p.total_floors,
                'district': p.parsed_district or getattr(p, 'district', '') or '',
                'cashback': int((p.price or 0) * 0.03),
                'main_image': p.main_image or '',
                'slug': getattr(p, 'slug', '') or '',
                'rc_name': getattr(p, 'residential_complex_name', '') or '',
            }
            for p in district_properties_db
        ]
    except Exception:
        district_properties = []

    try:
        district_complexes_db = ResidentialComplex.query.filter(
            ResidentialComplex.city_id == current_city.id,
            or_(
                ResidentialComplex.district == district_name,
                ResidentialComplex.address.ilike(f'%{district_name}%')
            )
        ).limit(20).all()
        district_complexes = [
            {
                'id': c.id,
                'name': c.name or '',
                'slug': c.slug or '',
                'address': c.address or '',
                'district': c.district or '',
                'object_class': c.object_class_display_name or 'Комфорт',
                'main_image': c.main_image or '/static/images/no-photo.svg',
            }
            for c in district_complexes_db
        ]
    except Exception:
        district_complexes = []

    infra = _infra_dict(district_db)
    canonical = f'/{city_slug}/rayon/{district_slug}'
    city_gen = getattr(current_city, 'name_genitive', None) or current_city.name

    district_data = {
        'name': district_name,
        'slug': district_slug,
        'city_id': current_city.id,
        'latitude': district_db.latitude,
        'longitude': district_db.longitude,
        'zoom_level': district_db.zoom_level or 13,
        'description': district_db.description,
        'seo_description': f'Новостройки в районе {district_name} {city_gen} с кэшбеком до 500 000 ₽. Актуальные предложения от застройщиков.',
        'distance_to_center': getattr(district_db, 'distance_to_center', None),
        'infrastructure_data': infra,
        'geometry': getattr(district_db, 'geometry', None),
        'geometry_source': getattr(district_db, 'geometry_source', None),
        'canonical': canonical,
    }

    # Sidebar: all districts of the current city
    from models import District as _DM
    try:
        _city_districts = _DM.query.filter_by(city_id=current_city.id).filter(
            _DM.slug.isnot(None), _DM.slug != ''
        ).order_by(_DM.name).all()
        city_districts = [{'name': d.name, 'slug': d.slug} for d in _city_districts]
    except Exception:
        city_districts = []

    return render_template(
        'district_detail.html',
        district=district_slug,
        district_name=district_name,
        district_data=district_data,
        properties=district_properties,
        complexes=district_complexes,
        current_city=current_city,
        city_slug=city_slug,
        city_districts=city_districts,
        canonical_url=canonical,
        yandex_api_key=os.environ.get('YANDEX_MAPS_API_KEY', '')
    )


# ── API: districts by city ────────────────────────────────────────────────────

@bp.route('/api/districts')
def api_districts():
    """Return districts for a given city_id (or current city)."""
    from models import District as DM
    city_id = request.args.get('city_id', type=int)
    if not city_id:
        current_city = resolve_city_context()
        city_id = current_city.id if current_city else None

    if not city_id:
        return jsonify({'error': 'city_id required'}), 400

    rows = DM.query.filter_by(city_id=city_id).filter(
        DM.name.isnot(None)
    ).order_by(DM.name).all()

    return jsonify([
        {'id': d.id, 'name': d.name, 'slug': d.slug,
         'lat': d.latitude, 'lng': d.longitude}
        for d in rows
    ])


@bp.route('/api/districts/heatmap')
def api_districts_heatmap():
    """Return district polygons with price statistics for Leaflet heatmap."""
    from models import District as DM, Property
    from sqlalchemy import func

    city_id = request.args.get('city_id', type=int)
    if not city_id:
        current_city = resolve_city_context()
        city_id = current_city.id if current_city else None

    if not city_id:
        return jsonify({'error': 'city_id required'}), 400

    # Get districts with geometry
    rows = DM.query.filter_by(city_id=city_id).filter(
        DM.name.isnot(None),
        DM.geometry.isnot(None)
    ).all()

    # Bulk-fetch price stats per district
    stats = db.session.query(
        Property.district_id,
        func.avg(Property.price_per_sqm).label('avg_sqm'),
        func.min(Property.price).label('min_price'),
        func.count(Property.id).label('cnt')
    ).filter(
        Property.is_active == True,
        Property.city_id == city_id,
        Property.district_id.isnot(None)
    ).group_by(Property.district_id).all()

    stats_map = {s.district_id: s for s in stats}

    # Compute price range for colour scaling
    sqm_vals = [s.avg_sqm for s in stats if s.avg_sqm and s.avg_sqm > 0]
    price_min_global = min(sqm_vals) if sqm_vals else 80000
    price_max_global = max(sqm_vals) if sqm_vals else 200000

    features = []
    for d in rows:
        if not d.geometry:
            continue

        # Parse "lat,lng;lat,lng;..." → [[lng, lat], ...]
        try:
            coords = []
            for pt in d.geometry.split(';'):
                pt = pt.strip()
                if not pt:
                    continue
                parts = pt.split(',')
                if len(parts) >= 2:
                    lat_v = float(parts[0])
                    lng_v = float(parts[1])
                    coords.append([lng_v, lat_v])
            if len(coords) < 3:
                continue
            # Close ring if needed
            if coords[0] != coords[-1]:
                coords.append(coords[0])
        except Exception:
            continue

        s = stats_map.get(d.id)
        avg_sqm = int(s.avg_sqm) if s and s.avg_sqm else None
        cnt = int(s.cnt) if s else 0
        min_price = int(s.min_price) if s and s.min_price else None

        # Normalise to 0–1 for colour
        if avg_sqm and price_max_global > price_min_global:
            t = (avg_sqm - price_min_global) / (price_max_global - price_min_global)
            t = max(0.0, min(1.0, t))
        else:
            t = None

        city_slug_str = getattr(d, 'city_slug', None)
        if not city_slug_str:
            from models import City
            city_obj = db.session.get(City, city_id)
            city_slug_str = city_obj.slug if city_obj else 'krasnodar'

        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [coords]
            },
            'properties': {
                'id': d.id,
                'name': d.name,
                'slug': d.slug,
                'url': f'/{city_slug_str}/novostrojki-v-{d.slug}',
                'avg_price_sqm': avg_sqm,
                'min_price': min_price,
                'props_count': cnt,
                'price_norm': round(t, 3) if t is not None else None,
                'price_min_global': int(price_min_global),
                'price_max_global': int(price_max_global),
            }
        })

    return jsonify({'type': 'FeatureCollection', 'features': features})


# ── API: district boundaries (GeoJSON) ────────────────────────────────────────

@bp.route('/api/district/boundaries/<district_slug>')
def api_district_boundaries(district_slug):
    """Return district geometry as GeoJSON for Yandex Maps overlay."""
    try:
        from models import District as DM
        d = DM.query.filter_by(slug=district_slug).first()
        if not d:
            return jsonify({'success': False, 'error': 'District not found'}), 404

        if not d.geometry:
            return jsonify({'success': False, 'error': 'No geometry for this district'}), 404

        # geometry stored as "lat,lon;lat,lon;..." convert to GeoJSON [lon,lat] pairs
        pts = []
        for pt in d.geometry.split(';'):
            pt = pt.strip()
            if not pt:
                continue
            parts = pt.split(',')
            if len(parts) >= 2:
                try:
                    lat, lon = float(parts[0]), float(parts[1])
                    pts.append([lon, lat])
                except ValueError:
                    continue

        if len(pts) < 3:
            return jsonify({'success': False, 'error': 'Insufficient geometry points'}), 404

        # Close the polygon ring if needed
        if pts[0] != pts[-1]:
            pts.append(pts[0])

        geojson = {
            'type': 'Polygon',
            'coordinates': [pts]
        }
        return jsonify({'success': True, 'boundaries': geojson,
                        'name': d.name, 'slug': d.slug,
                        'lat': d.latitude, 'lng': d.longitude})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── API: infrastructure ───────────────────────────────────────────────────────

@bp.route('/api/infrastructure')
def get_infrastructure():
    try:
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        radius = request.args.get('radius', 2000, type=int)
        if not lat or not lng:
            return jsonify({'error': 'Coordinates required'}), 400
        import sys, os as _os
        _scripts_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'scripts')
        if _scripts_path not in sys.path:
            sys.path.insert(0, _scripts_path)
        from infrastructure_api import get_poi_around_coordinates
        poi_data = get_poi_around_coordinates(lat, lng, radius)
        return jsonify(poi_data)
    except Exception as e:
        print(f"Error getting infrastructure data: {e}")
        return jsonify({'error': 'Failed to get infrastructure data'}), 500


# ── API: streets for a district ───────────────────────────────────────────────

@bp.route('/api/streets/district/<district_slug>')
def get_district_streets(district_slug):
    try:
        from models import Street, District
        district = District.query.filter_by(slug=district_slug).first()
        if not district:
            return jsonify({'error': 'District not found'}), 404
        streets = Street.query.filter_by(district_id=district.id).filter(
            Street.latitude.isnot(None),
            Street.longitude.isnot(None)
        ).all()
        return jsonify([
            {'id': s.id, 'name': s.name, 'slug': s.slug,
             'latitude': float(s.latitude), 'longitude': float(s.longitude),
             'description': s.description}
            for s in streets
        ])
    except Exception as e:
        print(f"Error getting district streets: {e}")
        return jsonify({'error': 'Failed to get district streets'}), 500
