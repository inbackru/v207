"""
Complexes Blueprint — residential complex listing, detail, and map pages.
Endpoints: complexes.residential_complexes_city, complexes.residential_complex_by_slug_city,
           complexes.complexes_map
"""
import json
import logging
import os

from flask import (Blueprint, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user

from sqlalchemy import text
from app import db
from models import ChatSettings

logger = logging.getLogger(__name__)


def _get_canonical_base_url():
    from app import CANONICAL_BASE_URL
    return CANONICAL_BASE_URL

complexes_bp = Blueprint('complexes', __name__)

# Route-level cache for complex listing (shared state per process)
_complexes_route_cache = {}
_complexes_route_cache_ts = {}
COMPLEXES_ROUTE_CACHE_TIMEOUT = 300  # 5 minutes


def _resolve_city_context(**kwargs):
    from app import resolve_city_context
    return resolve_city_context(**kwargs)


def _create_slug(name):
    from app import create_slug
    return create_slug(name)


def _calculate_cashback(*args, **kwargs):
    from app import calculate_cashback
    return calculate_cashback(*args, **kwargs)


def _get_clean_complex_images(complex_obj, limit=30):
    from routes.public_api import _get_clean_complex_images as _fn
    return _fn(complex_obj, limit=limit)


def _parse_nearby_places(nearby_json):
    from routes.public_api import _parse_nearby_places as _fn
    return _fn(nearby_json)


def _extract_amenity_badges(nearby_json, max_visible=4):
    from routes.public_api import _extract_amenity_badges as _fn
    return _fn(nearby_json, max_visible=max_visible)


def _parse_plan_images_from_complex(complex_obj):
    from routes.public_api import _parse_plan_images_from_complex as _fn
    return _fn(complex_obj)


def _district_cases(name):
    """Returns (genitive, prepositional) forms of a Russian district/okrug name."""
    nouns = {
        'округ': ('округа', 'округе'),
        'район': ('района', 'районе'),
        'микрорайон': ('микрорайона', 'микрорайоне'),
        'квартал': ('квартала', 'квартале'),
        'посёлок': ('посёлка', 'посёлке'),
        'поселок': ('поселка', 'поселке'),
        'улица': ('улицы', 'улице'),
        'проспект': ('проспекта', 'проспекте'),
    }
    adj_suf = [
        # (suffix, gen_suffix, prep_suffix)  — ordered longest→shortest for correct matching
        ('ский', 'ского', 'ском'),
        ('зский', 'зского', 'зском'),
        ('ний', 'него', 'нем'),
        ('жный', 'жного', 'жном'),
        ('зный', 'зного', 'зном'),
        ('дный', 'дного', 'дном'),
        ('ный', 'ного', 'ном'),
        ('кий', 'кого', 'ком'),
        ('гий', 'гого', 'гом'),
        ('ий', 'его', 'ем'),
        ('ый', 'ого', 'ом'),
    ]

    def _inflect(word):
        low = word.lower()
        if low in nouns:
            return nouns[low]
        for suf, gsuf, psuf in adj_suf:
            if low.endswith(suf) and len(low) > len(suf):
                base = word[:len(word) - len(suf)]
                return base + gsuf, base + psuf
        return word, word

    gen_parts, prep_parts = [], []
    for part in name.split():
        g, p = _inflect(part)
        gen_parts.append(g)
        prep_parts.append(p)
    return ' '.join(gen_parts), ' '.join(prep_parts)


@complexes_bp.route('/<city_slug>/zk')
def residential_complexes_city_zk(city_slug):
    """Short /zk alias → canonical /<city_slug>/zhilye-kompleksy"""
    return redirect(url_for('complexes.residential_complexes_city', city_slug=city_slug), 301)


@complexes_bp.route('/<city_slug>/zhilye-kompleksy')
def residential_complexes_city(city_slug):
    """City-based residential complexes page - SEO-friendly URL version"""
    from repositories.property_repository import ResidentialComplexRepository, PropertyRepository, DeveloperRepository, DistrictRepository
    import json
    from datetime import datetime
    
    # Resolve city context using city_slug from URL
    current_city = _resolve_city_context(city_slug=city_slug)
    
    # If city not found, redirect to default page
    if not current_city:
        flash('Город не найден. Показываем результаты для Краснодара.', 'warning')
        return redirect(url_for('mortgage.residential_complexes'))
    
    # Only update session city if it changed or not set (preserve user's city choice)
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    
    # Save manager if provided in URL (for manager referral links)
    if 'manager_id' in request.args:
        try:
            manager_id = int(request.args.get('manager_id'))
            session['manager_id'] = manager_id
            print(f"✅ Manager {manager_id} saved to session from URL")
        except (ValueError, TypeError):
            pass
    
    try:
        import time as _rt
        global _complexes_route_cache, _complexes_route_cache_ts
        _route_cache_key = str(current_city.id)

        # Serve from route cache if fresh (avoids rebuilding complex dicts on every request)
        if (_route_cache_key in _complexes_route_cache and
                _rt.time() - _complexes_route_cache_ts.get(_route_cache_key, 0) < COMPLEXES_ROUTE_CACHE_TIMEOUT):
            complexes = _complexes_route_cache[_route_cache_key]
            print(f"✅ /zhilye-kompleksy ROUTE CACHE HIT for city_id={current_city.id}")
        else:
            # Filter complexes by city
            from models import ResidentialComplex
            all_complexes = (
                db.session.query(ResidentialComplex)
                .filter(ResidentialComplex.city_id == current_city.id)
                .filter(ResidentialComplex.is_active == True)
                .order_by(ResidentialComplex.name)
                .all()
            )
            # Preload apt counts for sort by popularity
            from sqlalchemy import text as _sort_text
            with db.engine.connect() as _sort_conn:
                _apt_rows = _sort_conn.execute(_sort_text(
                    "SELECT complex_id, count(*) as cnt FROM properties "
                    "WHERE city_id=:cid AND is_active=TRUE GROUP BY complex_id"
                ), {'cid': current_city.id}).fetchall()
            _apt_counts = {r[0]: r[1] for r in _apt_rows}
            print(f"✅ /residential-complexes_city: Filtering by city: {current_city.name} (ID: {current_city.id})")

            # Get property stats
            property_stats_by_complex = PropertyRepository.get_all_property_stats(city_id=current_city.id)

            # Current date for status
            current_year = datetime.now().year
            current_quarter = (datetime.now().month - 1) // 3 + 1

            complexes = []

            for complex_obj in all_complexes:
                stats = property_stats_by_complex.get(complex_obj.id, {})

                # Format completion date and determine status
                completion_date = 'Не указан'
                is_completed = False
                build_year = None

                if complex_obj.end_build_year and complex_obj.end_build_quarter:
                    build_year = int(complex_obj.end_build_year)
                    build_quarter = int(complex_obj.end_build_quarter)

                    if build_year < current_year:
                        is_completed = True
                    elif build_year == current_year and build_quarter < current_quarter:
                        is_completed = True
                    else:
                        is_completed = False

                    quarter_names = {1: 'I', 2: 'II', 3: 'III', 4: 'IV'}
                    quarter = quarter_names.get(build_quarter, build_quarter)
                    completion_date = f"{quarter} кв. {build_year} г."
                elif complex_obj.end_build_year:
                    build_year = int(complex_obj.end_build_year)
                    is_completed = build_year < current_year
                    completion_date = f"{build_year} г."

                # Get address and district
                # Don't duplicate city name if address already contains it
                full_address = complex_obj.address or 'Адрес не указан'

                # Only use city name as district if address doesn't contain it
                if current_city.name.lower() in full_address.lower() or f"г. {current_city.name}".lower() in full_address.lower():
                    district_name = ""  # Address already has city name
                else:
                    district_name = current_city.name

                if (not complex_obj.address or complex_obj.address == 'Адрес не указан') and stats.get('sample_address'):
                    full_address = stats['sample_address']
                    address_parts = full_address.split(',')
                    if len(address_parts) >= 3:
                        _candidate = address_parts[2].strip()
                        _district_keywords = ('район', 'округ', 'мкр', 'микрорайон', 'посёлок', 'поселок', 'квартал')
                        _fake_keywords = ('жк ', 'жилой комплекс', 'квартал бизнес', 'апарт')
                        _cl = _candidate.lower()
                        if (any(k in _cl for k in _district_keywords) and
                                not any(k in _cl for k in _fake_keywords)):
                            district_name = _candidate

                # Build complete images list for slider — main_image ALWAYS first
                images_list = []
                _img_seen = set()
                if complex_obj.main_image:
                    images_list.append(complex_obj.main_image)
                    _img_seen.add(complex_obj.main_image)
                if complex_obj.gallery_images:
                    try:
                        if isinstance(complex_obj.gallery_images, list):
                            _gallery = complex_obj.gallery_images
                        elif isinstance(complex_obj.gallery_images, str) and complex_obj.gallery_images:
                            _gallery = json.loads(complex_obj.gallery_images)
                        else:
                            _gallery = []
                        for _gimg in _gallery:
                            if _gimg and _gimg not in _img_seen:
                                images_list.append(_gimg)
                                _img_seen.add(_gimg)
                    except:
                        pass

                # Add default if still empty
                if not images_list:
                    images_list = ['/static/images/no-photo.svg']

                # Basic complex info
                complex_dict = {
                    'id': complex_obj.id,
                    'name': complex_obj.name,
                    'available_apartments': stats.get('total_count', 0),
                    'price_from': stats.get('min_price', 0) or 0,
                    'price_to': stats.get('max_price', 0) or 0,
                    'real_price_from': stats.get('min_price', 0) or 0,
                    'real_price_to': stats.get('max_price', 0) or 0,
                    'area_from': stats.get('min_area', 0) or 0,
                    'area_to': stats.get('max_area', 0) or 0,
                    'floor_from': stats.get('min_floor', 0) or 0,
                    'floor_to': stats.get('max_floor', 0) or 0,
                    'developer': complex_obj.developer.name if complex_obj.developer else 'Не указан',
                    'developer_id': complex_obj.developer_id,
                    'developer_name': complex_obj.developer.name if complex_obj.developer else 'Не указан',
                    'developer_logo': complex_obj.developer.logo_url if complex_obj.developer else None,
                    'address': full_address,
                    'district': complex_obj.district.name if complex_obj.district else district_name,
                    'district_name': complex_obj.district.name if complex_obj.district else district_name,
                    'district_id': complex_obj.district_id,
                    'city_name': complex_obj.city.name if complex_obj.city else (current_city.name if current_city else ''),
                    'region_name': (
                        complex_obj.addr_region or (
                            complex_obj.city.region.name
                            if (complex_obj.city and complex_obj.city.region
                                and complex_obj.city.region.name not in ('Россия', 'РФ', 'Russia'))
                            else ''
                        )
                    ),
                    'address_quarter': complex_obj.address_quarter or '',
                    'address_city_district': complex_obj.address_city_district or '',
                    'addr_street': complex_obj.addr_street or '',
                    'addr_house': complex_obj.addr_house or '',
                    'addr_region': complex_obj.addr_region or '',
                    'addr_city': complex_obj.addr_city or '',
                    'completion_date': completion_date,
                    'is_completed': is_completed,
                    'build_year': build_year,
                    'cashback_rate': complex_obj.cashback_rate or 0,
                    'object_class': complex_obj.object_class_display_name or 'Комфорт',
                    'latitude': complex_obj.latitude,
                    'longitude': complex_obj.longitude,
                    'main_image': complex_obj.main_image or '/static/images/no-photo.svg',
                    'gallery_images': complex_obj.gallery_images,
                    'images': images_list,
                    'image': images_list[0] if images_list else '/static/images/no-photo.svg',
                    'real_room_distribution': stats.get('room_distribution', {}),
                    'room_details': stats.get('room_details', {}),
                    'status': 'Сдан' if is_completed else 'Строится',
                    'description': complex_obj.description or (
                        f'{complex_obj.object_class_display_name or "Жилой"} комплекс'
                        + (f' от {complex_obj.developer.name}' if complex_obj.developer else '')
                        + (f'. {stats.get("total_count", 0)} квартир в продаже' if stats.get("total_count") else '')
                    ),
                    'location': full_address,
                    'buildings_count': stats.get('buildings_count', 0) or complex_obj.buildings_count or 1,
                    'completed_buildings': getattr(complex_obj, 'completed_buildings', 0) or 0,
                    'slug': complex_obj.slug or _create_slug(complex_obj.name),
                    'url': f'/{city_slug}/zk/{complex_obj.slug or _create_slug(complex_obj.name)}',
                }
                # Add real amenity badges from nearby data
                _nb_visible, _nb_rest = _extract_amenity_badges(complex_obj.nearby)
                complex_dict['nearby_badges'] = _nb_visible
                complex_dict['nearby_badges_rest'] = _nb_rest
                complex_dict['distance_to_center'] = float(complex_obj.distance_to_center) if complex_obj.distance_to_center else None

                complexes.append(complex_dict)

            # ── PIP: auto-assign district from DB district_id or geometry ──────────
            try:
                from models import District as _DistModel
                from utils.geo import point_in_geometry
                _type_order = {'microrayon': 0, 'settlement': 1, 'okrug': 2, 'district': 3}
                _skip_names = {current_city.name, current_city.name + ' край', 'Краснодарский край', 'Россия'}
                _city_dists = _DistModel.query.filter_by(city_id=current_city.id).filter(
                    _DistModel.geometry.isnot(None), _DistModel.geometry != ''
                ).all()
                # Sort: most specific type first, then by geometry size (smaller = more specific)
                _city_dists = [d for d in _city_dists if d.name not in _skip_names]
                _city_dists.sort(key=lambda d: (
                    _type_order.get(d.district_type, 5),
                    len(d.geometry) if d.geometry else 999999
                ))
                if _city_dists:
                    for _cplx in complexes:
                        # Use DB-assigned district_id if available
                        if _cplx.get('district_id') is not None:
                            _db_dist = next((d for d in _city_dists if d.id == _cplx['district_id']), None)
                            if _db_dist:
                                _cplx['district'] = _db_dist.name
                                _cplx['district_name'] = _db_dist.name
                            continue
                        lat = _cplx.get('latitude')
                        lon = _cplx.get('longitude')
                        if not lat or not lon:
                            continue
                        for _d in _city_dists:
                            try:
                                if point_in_geometry(float(lat), float(lon), _d.geometry):
                                    _cplx['district_id'] = _d.id
                                    _cplx['district_name'] = _d.name
                                    _cplx['district'] = _d.name
                                    break
                            except Exception:
                                pass
            except Exception as _pip_err:
                current_app.logger.warning(f'RC district PIP failed: {_pip_err}')

            # Sort by popularity: complexes with most active apartments first, empty ones at bottom
            complexes.sort(key=lambda x: (
                0 if x.get('available_apartments', 0) > 0 else 1,
                -x.get('available_apartments', 0),
                x.get('name', '')
            ))

            # Save built list to route cache
            _complexes_route_cache[_route_cache_key] = complexes
            _complexes_route_cache_ts[_route_cache_key] = _rt.time()

        # The map is loaded client-side via /api/residential-complexes-map.
        # We no longer need to embed 500 properties server-side (avoided N+1 queries).
        properties = []
        
        # Use complexes list for residential_complexes (they contain the same data)
        # FIXED: Just copy complexes list instead of rebuilding it - avoids duplication and ensures consistency
        residential_complexes = complexes.copy()
        
        # Filter options (derived from complexes, not properties)
        developers_filter = request.args.get('developers', '')
        all_districts = sorted(list(set(c.get('district', '') for c in complexes if c.get('district'))))
        all_developers = sorted(list(set(c.get('developer', '') for c in complexes if c.get('developer'))))
        all_complexes_list = sorted(list(set(c.get('name', '') for c in complexes if c.get('name'))))

        # Fetch real district objects for the district filter UI
        from models import District as _Dist
        _dist_q = _Dist.query.filter(
            _Dist.city_id == current_city.id,
            _Dist.slug.isnot(None),
            _Dist.name != 'Краснодарский край'
        ).order_by(_Dist.district_type, _Dist.name).all()
        districts_for_template = [{'id': d.id, 'name': d.name, 'slug': d.slug, 'type': d.district_type} for d in _dist_q]

        filters = {
            'rooms': request.args.getlist('rooms'),
            'price_min': request.args.get('price_min', ''),
            'price_max': request.args.get('price_max', ''),
            'district': request.args.get('district', ''),
            'developer': request.args.get('developer', ''),
            'developers': developers_filter,
            'residential_complex': request.args.get('residential_complex', ''),
        }
        # Generate canonical URL for SEO (always use production domain)
        canonical_url = _get_canonical_base_url() + url_for('complexes.residential_complexes_city', city_slug=city_slug)
        # Slim version for JS (map + sidebar) — excludes heavy fields like description & full gallery
        complexes_for_map = [
            {
                'id': c['id'],
                'name': c['name'],
                'slug': c['slug'],
                'url': c['url'],
                'image': c['image'],
                'images': c['images'][:3] if c.get('images') else [],
                'latitude': c['latitude'],
                'longitude': c['longitude'],
                'status': c['status'],
                'completion_date': c['completion_date'],
                'is_completed': c['is_completed'],
                'developer': c['developer'],
                'developer_name': c['developer_name'],
                'address': c['address'],
                'district': c['district'],
                'district_id': c.get('district_id'),
                'district_name': c.get('district_name') or c.get('district') or '',
                'city_name': c.get('city_name', ''),
                'region_name': c.get('region_name', ''),
                'address_city_district': c.get('address_city_district', ''),
                'address_quarter': c.get('address_quarter', ''),
                'addr_street': c.get('addr_street', ''),
                'addr_house': c.get('addr_house', ''),
                'addr_region': c.get('addr_region', ''),
                'addr_city': c.get('addr_city', ''),
                'price_from': c['price_from'],
                'price_to': c['price_to'],
                'real_price_from': c['real_price_from'],
                'available_apartments': c['available_apartments'],
                'apartments_count': c['available_apartments'],
                'cashback_rate': c['cashback_rate'],
                'object_class': c['object_class'],
                'buildings_count': c['buildings_count'],
                'developer_logo': c.get('developer_logo'),
                'real_room_distribution': c['real_room_distribution'],
                'room_details': c.get('room_details', {}),
                'available_rooms': list(c['real_room_distribution'].keys()) if c.get('real_room_distribution') else [],
                'description': (c.get('description') or '')[:200],
                'location': c.get('location') or c['address'],
                'build_year': c['build_year'],
                'completion_year': c['build_year'],
                'max_floors': c.get('max_floors') or c.get('floors') or c.get('floors_count'),
                'housing_class': c.get('object_class', ''),
                'nearby_badges': c.get('nearby_badges', []),
                'nearby_badges_rest': c.get('nearby_badges_rest', 0),
                'distance_to_center': c.get('distance_to_center'),
            }
            for c in complexes
        ]

        # Extract available completion years from loaded complexes for dynamic filter
        all_years = sorted({
            int(c['build_year'])
            for c in complexes
            if c.get('build_year') and str(c['build_year']).isdigit() and 2020 <= int(c['build_year']) <= 2035
        })
        if not all_years:
            import datetime
            cur_year = datetime.datetime.now().year
            all_years = list(range(cur_year, cur_year + 4))

        return render_template('residential_complexes.html',
                             current_city=current_city,
                             complexes=complexes,
                             complexes_for_map=complexes_for_map,
                             properties=properties,
                             residential_complexes=residential_complexes,
                             all_districts=all_districts,
                             districts=districts_for_template,
                             all_developers=all_developers,
                             all_complexes=all_complexes_list,
                             filters=filters,
                             canonical_url=canonical_url,
                             all_years=all_years,
                             yandex_maps_api_key=os.environ.get('YANDEX_MAPS_API_KEY', ''))
                             
    except Exception as e:
        print(f"ERROR in /residential-complexes_city: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html',
                             error_code=500,
                             error_message='Ошибка при загрузке страницы ЖК',
                             current_city=current_city), 500


@complexes_bp.route('/<city_slug>/zhilye-kompleksy/<district_slug>')
def residential_complexes_district(city_slug, district_slug):
    """District/okrug-specific residential complexes page with unique SEO."""
    from repositories.property_repository import PropertyRepository
    from models import District, ResidentialComplex
    import json
    from datetime import datetime

    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        flash('Город не найден.', 'warning')
        return redirect(url_for('mortgage.residential_complexes'))

    current_district = District.query.filter_by(
        slug=district_slug, city_id=current_city.id
    ).first()
    if not current_district:
        return redirect(
            url_for('complexes.residential_complexes_city', city_slug=city_slug), 301
        )

    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug

    try:
        import time as _rt
        global _complexes_route_cache, _complexes_route_cache_ts
        _route_cache_key = str(current_city.id)

        # Reuse city-level cache (built by the city route) — or build it here
        if (_route_cache_key in _complexes_route_cache and
                _rt.time() - _complexes_route_cache_ts.get(_route_cache_key, 0) < COMPLEXES_ROUTE_CACHE_TIMEOUT):
            all_city_complexes = _complexes_route_cache[_route_cache_key]
        else:
            # Cache cold: load all city complexes fresh (same logic as city route)
            all_complexes_raw = (
                db.session.query(ResidentialComplex)
                .filter(ResidentialComplex.city_id == current_city.id)
                .filter(ResidentialComplex.is_active == True)
                .order_by(ResidentialComplex.name)
                .all()
            )
            from sqlalchemy import text as _sort_text
            with db.engine.connect() as _sort_conn:
                _apt_rows = _sort_conn.execute(_sort_text(
                    "SELECT complex_id, count(*) as cnt FROM properties "
                    "WHERE city_id=:cid AND is_active=TRUE GROUP BY complex_id"
                ), {'cid': current_city.id}).fetchall()
            _apt_counts = {r[0]: r[1] for r in _apt_rows}
            property_stats_by_complex = PropertyRepository.get_all_property_stats(city_id=current_city.id)
            current_year = datetime.now().year
            current_quarter = (datetime.now().month - 1) // 3 + 1
            all_city_complexes = []
            for complex_obj in all_complexes_raw:
                stats = property_stats_by_complex.get(complex_obj.id, {})
                completion_date = 'Не указан'
                is_completed = False
                build_year = None
                if complex_obj.end_build_year and complex_obj.end_build_quarter:
                    build_year = int(complex_obj.end_build_year)
                    build_quarter = int(complex_obj.end_build_quarter)
                    is_completed = build_year < current_year or (build_year == current_year and build_quarter < current_quarter)
                    quarter_names = {1: 'I', 2: 'II', 3: 'III', 4: 'IV'}
                    completion_date = f"{quarter_names.get(build_quarter, build_quarter)} кв. {build_year} г."
                elif complex_obj.end_build_year:
                    build_year = int(complex_obj.end_build_year)
                    is_completed = build_year < current_year
                    completion_date = f"{build_year} г."
                full_address = complex_obj.address or 'Адрес не указан'
                images_list = []
                _img_seen = set()
                if complex_obj.main_image:
                    images_list.append(complex_obj.main_image)
                    _img_seen.add(complex_obj.main_image)
                if complex_obj.gallery_images:
                    try:
                        _gallery = complex_obj.gallery_images if isinstance(complex_obj.gallery_images, list) else json.loads(complex_obj.gallery_images)
                        for _gimg in _gallery:
                            if _gimg and _gimg not in _img_seen:
                                images_list.append(_gimg)
                                _img_seen.add(_gimg)
                    except Exception:
                        pass
                if not images_list:
                    images_list = ['/static/images/no-photo.svg']
                district_name = complex_obj.district.name if complex_obj.district else current_city.name
                _nb_visible, _nb_rest = _extract_amenity_badges(complex_obj.nearby)
                cplx = {
                    'id': complex_obj.id,
                    'name': complex_obj.name,
                    'available_apartments': stats.get('total_count', 0),
                    'price_from': stats.get('min_price', 0) or 0,
                    'price_to': stats.get('max_price', 0) or 0,
                    'real_price_from': stats.get('min_price', 0) or 0,
                    'real_price_to': stats.get('max_price', 0) or 0,
                    'area_from': stats.get('min_area', 0) or 0,
                    'area_to': stats.get('max_area', 0) or 0,
                    'floor_from': stats.get('min_floor', 0) or 0,
                    'floor_to': stats.get('max_floor', 0) or 0,
                    'developer': complex_obj.developer.name if complex_obj.developer else 'Не указан',
                    'developer_id': complex_obj.developer_id,
                    'developer_name': complex_obj.developer.name if complex_obj.developer else 'Не указан',
                    'developer_logo': complex_obj.developer.logo_url if complex_obj.developer else None,
                    'address': full_address,
                    'district': district_name,
                    'district_name': district_name,
                    'district_id': complex_obj.district_id,
                    'city_name': current_city.name,
                    'region_name': complex_obj.addr_region or '',
                    'address_quarter': complex_obj.address_quarter or '',
                    'address_city_district': complex_obj.address_city_district or '',
                    'addr_street': complex_obj.addr_street or '',
                    'addr_house': complex_obj.addr_house or '',
                    'addr_region': complex_obj.addr_region or '',
                    'addr_city': complex_obj.addr_city or '',
                    'completion_date': completion_date,
                    'is_completed': is_completed,
                    'build_year': build_year,
                    'cashback_rate': complex_obj.cashback_rate or 0,
                    'object_class': complex_obj.object_class_display_name or 'Комфорт',
                    'latitude': complex_obj.latitude,
                    'longitude': complex_obj.longitude,
                    'main_image': complex_obj.main_image or '/static/images/no-photo.svg',
                    'gallery_images': complex_obj.gallery_images,
                    'images': images_list,
                    'image': images_list[0] if images_list else '/static/images/no-photo.svg',
                    'real_room_distribution': stats.get('room_distribution', {}),
                    'room_details': stats.get('room_details', {}),
                    'status': 'Сдан' if is_completed else 'Строится',
                    'description': complex_obj.description or f'{complex_obj.object_class_display_name or "Жилой"} комплекс',
                    'location': full_address,
                    'buildings_count': stats.get('buildings_count', 0) or complex_obj.buildings_count or 1,
                    'completed_buildings': getattr(complex_obj, 'completed_buildings', 0) or 0,
                    'slug': complex_obj.slug or _create_slug(complex_obj.name),
                    'url': f'/{city_slug}/zk/{complex_obj.slug or _create_slug(complex_obj.name)}',
                    'nearby_badges': _nb_visible,
                    'nearby_badges_rest': _nb_rest,
                    'distance_to_center': float(complex_obj.distance_to_center) if complex_obj.distance_to_center else None,
                }
                all_city_complexes.append(cplx)
            _complexes_route_cache[_route_cache_key] = all_city_complexes
            _complexes_route_cache_ts[_route_cache_key] = _rt.time()

        # Filter to this district only
        complexes = [c for c in all_city_complexes if c.get('district_id') == current_district.id]

        # Compute Russian genitive & prepositional forms for district name
        district_gen, district_prep = _district_cases(current_district.name)

        # Canonical URL for this district page
        canonical_url = (
            _get_canonical_base_url()
            + url_for('complexes.residential_complexes_district',
                      city_slug=city_slug, district_slug=district_slug)
        )

        # Districts list for sidebar filter (same city)
        from models import District as _Dist
        _dist_q = _Dist.query.filter(
            _Dist.city_id == current_city.id,
            _Dist.slug.isnot(None),
            _Dist.name != 'Краснодарский край'
        ).order_by(_Dist.district_type, _Dist.name).all()
        districts_for_template = [
            {'id': d.id, 'name': d.name, 'slug': d.slug, 'type': d.district_type}
            for d in _dist_q
        ]

        complexes_for_map = [
            {
                'id': c['id'], 'name': c['name'], 'slug': c['slug'], 'url': c['url'],
                'image': c['image'], 'images': c['images'][:3] if c.get('images') else [],
                'latitude': c['latitude'], 'longitude': c['longitude'],
                'status': c['status'], 'completion_date': c['completion_date'],
                'is_completed': c['is_completed'], 'developer': c['developer'],
                'developer_name': c['developer_name'], 'address': c['address'],
                'district': c['district'], 'district_id': c.get('district_id'),
                'district_name': c.get('district_name') or c.get('district') or '',
                'city_name': c.get('city_name', ''), 'region_name': c.get('region_name', ''),
                'address_city_district': c.get('address_city_district', ''),
                'address_quarter': c.get('address_quarter', ''),
                'addr_street': c.get('addr_street', ''), 'addr_house': c.get('addr_house', ''),
                'addr_region': c.get('addr_region', ''), 'addr_city': c.get('addr_city', ''),
                'price_from': c['price_from'], 'price_to': c['price_to'],
                'real_price_from': c['real_price_from'],
                'available_apartments': c['available_apartments'],
                'apartments_count': c['available_apartments'],
                'cashback_rate': c['cashback_rate'], 'object_class': c['object_class'],
                'buildings_count': c['buildings_count'], 'developer_logo': c.get('developer_logo'),
                'real_room_distribution': c['real_room_distribution'],
                'room_details': c.get('room_details', {}),
                'available_rooms': list(c['real_room_distribution'].keys()) if c.get('real_room_distribution') else [],
                'description': (c.get('description') or '')[:200],
                'location': c.get('location') or c['address'],
                'build_year': c['build_year'], 'completion_year': c['build_year'],
                'max_floors': c.get('max_floors'),
                'housing_class': c.get('object_class', ''),
                'nearby_badges': c.get('nearby_badges', []),
                'nearby_badges_rest': c.get('nearby_badges_rest', 0),
                'distance_to_center': c.get('distance_to_center'),
            }
            for c in complexes
        ]

        import datetime as _dt
        all_years = sorted({
            int(c['build_year']) for c in complexes
            if c.get('build_year') and str(c['build_year']).isdigit()
            and 2020 <= int(c['build_year']) <= 2035
        })
        if not all_years:
            cur_year = _dt.datetime.now().year
            all_years = list(range(cur_year, cur_year + 4))

        all_districts = sorted(list(set(c.get('district', '') for c in complexes if c.get('district'))))
        all_developers = sorted(list(set(c.get('developer', '') for c in complexes if c.get('developer'))))
        all_complexes_list = sorted(list(set(c.get('name', '') for c in complexes if c.get('name'))))

        filters = {
            'rooms': request.args.getlist('rooms'),
            'price_min': request.args.get('price_min', ''),
            'price_max': request.args.get('price_max', ''),
            'district': current_district.id,
            'developer': request.args.get('developer', ''),
            'developers': '',
            'residential_complex': '',
        }

        return render_template(
            'residential_complexes.html',
            current_city=current_city,
            current_district=current_district,
            district_gen=district_gen,
            district_prep=district_prep,
            complexes=complexes,
            complexes_for_map=complexes_for_map,
            properties=[],
            residential_complexes=complexes,
            all_districts=all_districts,
            districts=districts_for_template,
            all_developers=all_developers,
            all_complexes=all_complexes_list,
            filters=filters,
            canonical_url=canonical_url,
            all_years=all_years,
            yandex_maps_api_key=os.environ.get('YANDEX_MAPS_API_KEY', ''),
        )

    except Exception as e:
        print(f"ERROR in /zhilye-kompleksy/<district_slug>: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html',
                               error_code=500,
                               error_message='Ошибка при загрузке страницы ЖК района',
                               current_city=current_city), 500


@complexes_bp.route('/<city_slug>/zk/<slug>')
def residential_complex_by_slug_city(city_slug, slug):
    """City-based residential complex detail page - SEO-friendly URL version - FULL IMPLEMENTATION"""
    # Resolve city context using city_slug from URL
    current_city = _resolve_city_context(city_slug=city_slug)
    
    # If city not found, use default
    if not current_city:
        flash('Город не найден. Показываем результаты для Краснодара.', 'warning')
        current_city = _resolve_city_context()  # Get default city
    
    # Store city in session
    if current_city:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    
    try:
        from repositories.property_repository import PropertyRepository, ResidentialComplexRepository
        from models import ResidentialComplex, Offer, MarketingMaterial, Manager, Admin
        
        # === STEP 1: Get ResidentialComplex by slug ===
        complex = None
        
        # Try exact slug match first
        complex = ResidentialComplexRepository.get_by_slug(slug)
        
        # If not found, try matching with create_slug() for transliteration support
        if not complex:
            all_complexes = ResidentialComplexRepository.get_all_active(limit=100)
            for c in all_complexes:
                if _create_slug(c.name) == slug:
                    complex = c
                    break
        
        # If not found, redirect to properties page
        if not complex:
            print(f"Complex {slug} not found in residential_complexes table")
            return redirect(url_for('complexes.residential_complexes_city', city_slug=city_slug))
        
        # Convert ORM object to dict for template compatibility
        complex_data = {
            'id': complex.id,
            'name': complex.name,
            'slug': complex.slug,
            'complex_type': complex.complex_type or 'residential',
            'description': complex.description,
            'cashback_rate': complex.cashback_rate,
            'cashback_percent': complex.cashback_rate,  # Alias for template
            'developer_id': complex.developer_id,
            'developer_name': complex.developer.name if complex.developer else 'Не указан',
            'developer_id': complex.developer.id if complex.developer else None,
            'object_class': complex.object_class_display_name or 'Комфорт',
            'developer': complex.developer.name if complex.developer else 'Не указан',
            'developer_description': complex.developer.description if complex.developer else 'Застройщик с многолетним опытом работы на рынке недвижимости.',
            'developer_slug': complex.developer.slug if complex.developer else None,
            'developer_website': complex.developer.website if complex.developer else None,
            'object_class_display_name': complex.object_class_display_name or 'Комфорт',
            'sales_address': complex.sales_address,
            'district': complex.district.name if complex.district else '',
            'district_name': complex.district.name if complex.district else None,
            'district_slug': complex.district.slug if complex.district else None,
            'district_type': complex.district.district_type if complex.district else None,
            # address_city_district = okrug (Прикубанский, Карасунский…)
            # address_quarter       = microrayon (Самолёт, Черемушки…)
            'address_city_district': complex.address_city_district or '',
            'address_quarter': complex.address_quarter or '',
            'addr_street': complex.addr_street or '',
            'addr_house': complex.addr_house or '',
            'addr_region': complex.addr_region or '',
            'addr_city': complex.addr_city or '',
            'city_name': complex.city.name if complex.city else (current_city.name if current_city else 'Краснодар'),
            'region_name': (
                complex.addr_region or (
                    complex.city.region.name
                    if (complex.city and complex.city.region
                        and complex.city.region.name not in ('Россия', 'РФ', 'Russia'))
                    else ''
                )
            ),
            'start_build_year': complex.start_build_year,
            'start_build_quarter': complex.start_build_quarter,
            'end_build_year': complex.end_build_year,
            'end_build_quarter': complex.end_build_quarter,
            'latitude': complex.latitude,
            'longitude': complex.longitude,
            'main_image': complex.main_image,
            'gallery_images': complex.gallery_images,
            'gallery_images': complex.gallery_images,
            'videos': complex.videos,
            'uploaded_video': complex.uploaded_video,
            'nearby': complex.nearby,
            'detailed_description': complex.detailed_description,
            'advantages': complex.advantages,
            'ceiling_height': complex.ceiling_height,
            'finishing_type': getattr(complex, 'finishing_type', None),
            'parking_type': getattr(complex, 'parking_type', None),
            'floors_min': getattr(complex, 'floors_min', None),
            'floors_max': getattr(complex, 'floors_max', None),
            'wall_material': getattr(complex, 'wall_material', None),
            'logo_url': getattr(complex, 'logo_url', None),
            'finishing_variants': getattr(complex, 'finishing_variants', None),
            'infrastructure': getattr(complex, 'infrastructure', None),
            'construction_progress_images': complex.construction_progress_images,
            'construction_photos_updated_at': complex.construction_photos_updated_at,
            'location': complex.sales_address or complex.district.name if complex.district else '',
            'territory_amenities': getattr(complex, 'territory_amenities', None),
            'parking_features': getattr(complex, 'parking_features', None),
            'security_features': getattr(complex, 'security_features', None),
            'lifts_range': getattr(complex, 'lifts_range', None),
            'lifts_count': getattr(complex, 'lifts_count', None),
            'has_concierge': getattr(complex, 'has_concierge', False),
            # TrendAgent enriched fields
            'ta_level_type':          getattr(complex, 'ta_level_type', None),
            'ta_reward_label':        getattr(complex, 'ta_reward_label', None),
            'ta_escrow':              getattr(complex, 'ta_escrow', None),
            'contract_type':          getattr(complex, 'contract_type', None),
            'pano_url':               getattr(complex, 'pano_url', None),
            'ta_aerial_panorama_url': getattr(complex, 'ta_aerial_panorama_url', None),
            'ta_passport':            getattr(complex, 'ta_passport', None),
            'ta_min_area':            getattr(complex, 'ta_min_area', None),
            'ta_max_area':            getattr(complex, 'ta_max_area', None),
            'ta_sales_start_display':   getattr(complex, 'ta_sales_start_display', None),
            'ta_deadline_key_display':  getattr(complex, 'ta_deadline_key_display', None),
            'view_places':              getattr(complex, 'view_places', None),
            'ta_payment_types':         getattr(complex, 'ta_payment_types', None),
            'interactive_plan_url':     getattr(complex, 'interactive_plan_url', None),
            'complex_start_year':       getattr(complex, 'complex_start_year', None),
            'complex_start_quarter':    getattr(complex, 'complex_start_quarter', None),
        }
        
        # Supplemental direct SQL for fields that may not be in ORM cache
        try:
            _extra = db.session.execute(text(
                "SELECT finishing_type, parking_type, floors_min, floors_max, "
                "wall_material, logo_url, finishing_variants, detailed_description, "
                "infrastructure, construction_progress_images, complex_features, "
                "territory_amenities, parking_features, security_features, "
                "lifts_range, lifts_count, has_concierge "
                "FROM residential_complexes WHERE id = :rc_id"
            ), {'rc_id': complex.id}).fetchone()
            if _extra:
                if not complex_data.get('finishing_type') and _extra[0]:
                    complex_data['finishing_type'] = _extra[0]
                if not complex_data.get('parking_type') and _extra[1]:
                    complex_data['parking_type'] = _extra[1]
                if not complex_data.get('floors_min') and _extra[2]:
                    complex_data['floors_min'] = _extra[2]
                if not complex_data.get('floors_max') and _extra[3]:
                    complex_data['floors_max'] = _extra[3]
                if not complex_data.get('wall_material') and _extra[4]:
                    complex_data['wall_material'] = _extra[4]
                if not complex_data.get('logo_url') and _extra[5]:
                    complex_data['logo_url'] = _extra[5]
                if not complex_data.get('finishing_variants') and _extra[6]:
                    complex_data['finishing_variants'] = _extra[6]
                if not complex_data.get('detailed_description') and _extra[7]:
                    complex_data['detailed_description'] = _extra[7]
                if not complex_data.get('infrastructure') and _extra[8]:
                    complex_data['infrastructure'] = _extra[8]
                if not complex_data.get('construction_progress_images') and _extra[9]:
                    complex_data['construction_progress_images'] = _extra[9]
                if not complex_data.get('complex_features') and _extra[10]:
                    complex_data['complex_features'] = _extra[10]
                # New amenity fields — always overwrite if present in DB
                if _extra[11] is not None:
                    complex_data['territory_amenities'] = _extra[11]
                if _extra[12] is not None:
                    complex_data['parking_features'] = _extra[12]
                if _extra[13] is not None:
                    complex_data['security_features'] = _extra[13]
                if _extra[14] is not None:
                    complex_data['lifts_range'] = _extra[14]
                if _extra[15] is not None:
                    complex_data['lifts_count'] = _extra[15]
                if _extra[16] is not None:
                    complex_data['has_concierge'] = _extra[16]
        except Exception as _e:
            print(f"[extra fields SQL error] {_e}")
        
        # === STEP 2: Stats via SQL aggregation (fast, no ORM hydration) ===
        from models import Property as _PropModel
        _agg = db.session.query(
            db.func.count(_PropModel.id),
            db.func.min(_PropModel.price),
            db.func.max(_PropModel.price),
            db.func.min(_PropModel.area),
            db.func.max(_PropModel.area),
            db.func.min(_PropModel.floor),
            db.func.max(_PropModel.total_floors),
            db.func.count(db.func.distinct(_PropModel.complex_building_name)),
            db.func.min(_PropModel.latitude),
            db.func.min(_PropModel.longitude),
        ).filter(_PropModel.complex_id == complex.id, _PropModel.is_active == True).one()
        _real_count = int(_agg[0] or 0)

        # Lightweight list for display (limit 500 — enough for UI table/grid)
        properties = PropertyRepository.get_by_complex_id(complex.id, limit=500, sort_by='price', sort_order='asc')

        # Lightweight chess board data (raw SQL — only 6 fields, no ORM overhead)
        try:
            db.session.rollback()
            _chess_rows = db.session.execute(text(
                "SELECT inner_id, rooms, area, price, floor, "
                "COALESCE(complex_building_name,'Основной корпус') as bld, "
                "COALESCE(plan_image, main_image) as img, is_active, "
                "COALESCE(entrance_number,'') as entrance, "
                "COALESCE(apartment_number,'') as apt_num, "
                "id as db_id, "
                "total_floors "
                "FROM properties WHERE complex_id=:cid "
                "ORDER BY is_active DESC, price ASC LIMIT 20000"
            ), {'cid': complex.id}).fetchall()
            _chess_data = [
                {'id': r[0], 'object_rooms': int(r[1]) if r[1] is not None else 0,
                 'object_area': float(r[2] or 0),
                 'price': int(r[3] or 0), 'floor': int(r[4]) if r[4] else None,
                 'complex_building_name': r[5],
                 'plan_image': r[6] or '', 'is_sold': not bool(r[7]),
                 'entrance_number': r[8] or '', 'apartment_number': r[9] or '',
                 'db_id': int(r[10]) if r[10] else None,
                 'total_floors': int(r[11]) if r[11] else None}
                for r in _chess_rows
            ]
        except Exception as _chess_err:
            print(f"[chess SQL error] {_chess_err}")
            db.session.rollback()
            _chess_data = []

        # SQL rooms summary — real counts (not limited to 500 ORM objects)
        try:
            db.session.rollback()
            _rooms_agg = db.session.execute(text(
                "SELECT COALESCE(rooms,0), COUNT(*), MIN(area), MIN(price), MAX(price) "
                "FROM properties WHERE complex_id=:cid AND is_active=TRUE "
                "GROUP BY COALESCE(rooms,0) ORDER BY COALESCE(rooms,0)"
            ), {'cid': complex.id}).fetchall()
        except Exception as _rooms_err:
            print(f"[rooms agg SQL error] {_rooms_err}")
            db.session.rollback()
            _rooms_agg = []
        _rooms_label = {0: 'Студии', 1: '1-комнатные', 2: '2-комнатные', 3: '3-комнатные', 4: '4+ комнатные'}
        _rooms_key  = {0: '0', 1: '1', 2: '2', 3: '3', 4: '4'}
        rooms_sql_summary = []
        for _r in _rooms_agg:
            _rnum = int(_r[0])
            rooms_sql_summary.append({
                'rooms': _rnum,
                'rooms_key': _rooms_key.get(_rnum, str(_rnum)),
                'label': _rooms_label.get(_rnum, f'{_rnum}-комн.'),
                'count': int(_r[1]),
                'min_area': float(_r[2] or 0),
                'min_price': int(_r[3] or 0),
                'max_price': int(_r[4] or 0),
                'examples': [],
            })
        if not properties and _real_count == 0:
            print(f"No properties found for complex {complex.name}")
            complex_data['apartments_count'] = 0
            complex_data['total_apartments'] = 0
            complex_data['price_from'] = 0
            complex_data['price_to'] = 0
            complex_data['min_price'] = 0
            complex_data['max_price'] = 0
            complex_data['buildings_count'] = 0
            complex_data['coordinates'] = [complex.latitude or 45.0355, complex.longitude or 38.9753]
            complex_data['total_floors_in_complex'] = 25
            _no_prop_images = _get_clean_complex_images(complex, limit=30)
            if not _no_prop_images and complex.main_image:
                _no_prop_images = [complex.main_image]
            complex_data['images'] = _no_prop_images
            complex_data['image'] = _no_prop_images[0] if _no_prop_images else '/static/images/no-photo.svg'
        else:
            # Use SQL aggregation results for stats
            complex_data['apartments_count'] = _real_count
            complex_data['total_apartments'] = _real_count
            complex_data['price_from'] = int(_agg[1] or 0)
            complex_data['price_to'] = int(_agg[2] or 0)
            complex_data['min_price'] = complex_data['price_from']
            complex_data['max_price'] = complex_data['price_to']
            complex_data['real_price_from'] = complex_data['price_from']
            complex_data['real_price_to'] = complex_data['price_to']
            complex_data['real_area_from'] = float(_agg[3] or 0)
            complex_data['real_area_to'] = float(_agg[4] or 0)
            complex_data['real_floors_min'] = int(_agg[5] or 1)
            complex_data['real_floors_max'] = int(_agg[6] or 25)
            complex_data['total_floors_in_complex'] = complex_data['real_floors_max']
            complex_data['buildings_count'] = max(int(_agg[7] or 1), 1)

            # Set full address from sales_address or first property address
            complex_data['full_address'] = complex.sales_address or (properties[0].address if properties else '')

            # Set coordinates
            if complex.latitude and complex.longitude:
                complex_data['coordinates'] = [float(complex.latitude), float(complex.longitude)]
            elif properties and properties[0].latitude and properties[0].longitude:
                complex_data['coordinates'] = [float(properties[0].latitude), float(properties[0].longitude)]
            elif _agg[8] and _agg[9]:
                complex_data['coordinates'] = [float(_agg[8]), float(_agg[9])]
            else:
                complex_data['coordinates'] = [45.0355, 38.9753]

            # Get clean ЖК images (watermark-free exterior shots only)
            clean_images = _get_clean_complex_images(complex, limit=30)
            if not clean_images and complex.main_image:
                clean_images = [complex.main_image]
            complex_data['images'] = clean_images
            complex_data['image'] = clean_images[0] if clean_images else '/static/images/no-photo.svg'

            print(f"Loaded stats for {complex.name}: {_real_count} total, {len(properties)} shown, price {complex_data['price_from']}–{complex_data['price_to']}")
        
        # === STEP 3: Convert properties to template-compatible format ===
        complex_properties = []
        cashback_rate_decimal = complex_data.get('cashback_percent', 5.0) / 100.0
        
        for prop in properties:
            # Convert ORM Property object to dict for template
            prop_dict = {
                'id': prop.inner_id or prop.id,  # Use inner_id for compatibility
                'inner_id': prop.inner_id or prop.id,
                'price': prop.price or 0,
                'cashback_amount': int(prop.price * cashback_rate_decimal) if prop.price else 0,
                'complex_id': complex.id,
                'residential_complex': complex.name,
                'object_rooms': prop.rooms or 0,
                'object_area': prop.area or 0,
                'object_min_floor': prop.floor or 1,
                'floor': prop.floor or 1,
                'total_floors': prop.total_floors or complex_data['total_floors_in_complex'],
                'address': prop.address or '',
                'address_short_display_name': prop.address or '',
                'complex_building_name': prop.complex_building_name or 'Основной корпус',
                'property_type': 'Квартира',
                'deal_type': prop.deal_type or 'sale',
                'renovation_type': prop.renovation_type
            }
            
            # Format title
            rooms = prop.rooms or 0
            if rooms == 0:
                room_type = "Студия"
            else:
                room_type = f"{rooms}-комнатная квартира"
            
            apartment_floor = prop.floor or 1
            total_floors = prop.total_floors or complex_data['total_floors_in_complex']
            prop_dict['title'] = f"{room_type}, {prop.area or 0} м², {apartment_floor}/{total_floors} эт."
            prop_dict['type'] = f"{rooms}-комн" if rooms > 0 else "Студия"
            prop_dict['apartment_floor'] = apartment_floor
            prop_dict['total_floors_in_complex'] = total_floors
            
            # Parse gallery images
            try:
                import json
                if prop.gallery_images:
                    if isinstance(prop.gallery_images, str):
                        photos_list = json.loads(prop.gallery_images)
                    else:
                        photos_list = prop.gallery_images
                else:
                    photos_list = []
                
                prop_dict['image'] = photos_list[0] if photos_list else (prop.main_image or 'https://via.placeholder.com/400x300/0088CC/FFFFFF?text=Квартира')
                prop_dict['photos_list'] = photos_list
            except Exception as e:
                print(f"Error parsing photos for property {prop.id}: {e}")
                prop_dict['image'] = prop.main_image or 'https://via.placeholder.com/400x300/0088CC/FFFFFF?text=Квартира'
                prop_dict['photos_list'] = []
            
            complex_properties.append(prop_dict)
        
        # === STEP 4: Calculate room statistics ===
        properties_by_rooms = {}
        room_stats = {}
        for prop in complex_properties:
            rooms = prop.get('object_rooms', 0)
            room_key = 'Студия' if rooms == 0 else f'{rooms}-комн'
            
            if room_key not in properties_by_rooms:
                properties_by_rooms[room_key] = []
                room_stats[room_key] = {
                    'count': 0,
                    'prices': [],
                    'areas': [],
                    'price_from': 0,
                    'price_to': 0,
                    'area_from': 0,
                    'area_to': 0
                }
            
            properties_by_rooms[room_key].append(prop)
            room_stats[room_key]['count'] += 1
            if prop.get('price'):
                room_stats[room_key]['prices'].append(prop['price'])
            if prop.get('object_area'):
                room_stats[room_key]['areas'].append(prop['object_area'])
        
        # Calculate min/max for each room type
        for room_key, stats in room_stats.items():
            if stats['prices']:
                stats['price_from'] = min(stats['prices'])
                stats['price_to'] = max(stats['prices'])
            else:
                stats['price_from'] = 0
                stats['price_to'] = 0
            
            if stats['areas']:
                stats['area_from'] = min(stats['areas'])
                stats['area_to'] = max(stats['areas'])
            else:
                stats['area_from'] = 0
                stats['area_to'] = 0
        
        complex_data['room_stats'] = room_stats

        # Attach up to 5 example apartments (dicts) to rooms_sql_summary
        # Query DB directly per room type to avoid missing rooms due to 500-prop limit
        _total_floors_fallback = complex_data.get('total_floors_in_complex', 25)
        try:
            db.session.rollback()
        except Exception:
            pass
        for _rs in rooms_sql_summary:
            try:
                _ex_rows = db.session.execute(text(
                    "SELECT id, title, price, area, floor, total_floors, "
                    "complex_building_name "
                    "FROM properties WHERE complex_id=:cid AND COALESCE(rooms,0)=:r "
                    "AND is_active=TRUE AND price IS NOT NULL ORDER BY price ASC LIMIT 5"
                ), {'cid': complex.id, 'r': _rs['rooms']}).fetchall()
                for _row in _ex_rows:
                    _rs['examples'].append({
                        'id': _row[0], 'inner_id': _row[0],
                        'title': _row[1] or '',
                        'price': float(_row[2]) if _row[2] else 0,
                        'object_area': float(_row[3]) if _row[3] else 0,
                        'apartment_floor': _row[4],
                        'object_min_floor': _row[4],
                        'total_floors': _row[5] or _total_floors_fallback,
                        'total_floors_in_complex': _total_floors_fallback,
                        'complex_building_name': _row[6],
                        'object_rooms': _rs['rooms'],
                    })
            except Exception as _ex_err:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                # fallback: search already-loaded complex_properties
                for _pd in complex_properties:
                    if _pd.get('object_rooms', 0) == _rs['rooms'] and len(_rs['examples']) < 5:
                        _rs['examples'].append(_pd)

        # === STEP 5: Group properties by complex_building_name ===
        properties_by_building_unsorted = {}
        for prop in complex_properties:
            building_name = prop.get('complex_building_name') or 'Основной корпус'
            if not building_name or building_name.strip() == '':
                building_name = 'Основной корпус'
            
            if building_name not in properties_by_building_unsorted:
                properties_by_building_unsorted[building_name] = []
            properties_by_building_unsorted[building_name].append(prop)
        
        # Sort buildings
        def sort_buildings(building_name):
            import re
            if not building_name or building_name == 'Основной корпус':
                return (999, building_name)
            match = re.search(r'(\d+)', building_name)
            if match:
                return (int(match.group(1)), building_name)
            return (999, building_name)
        
        properties_by_building = {}
        sorted_building_names = sorted(properties_by_building_unsorted.keys(), key=sort_buildings)
        for building_name in sorted_building_names:
            properties_by_building[building_name] = properties_by_building_unsorted[building_name]
        
        # === STEP 5.5: Create buildings dict with stats for template ===
        import datetime as _dt_mod

        # Real per-building counts from DB (properties list is limited to 500)
        try:
            db.session.rollback()
            _bld_sql = db.session.execute(text(
                "SELECT COALESCE(complex_building_name,'Основной корпус') AS bld, "
                "COUNT(*) AS cnt, MIN(price) AS pmin, MAX(total_floors) AS floors "
                "FROM properties WHERE complex_id=:cid AND is_active=TRUE "
                "GROUP BY COALESCE(complex_building_name,'Основной корпус')"
            ), {'cid': complex.id}).fetchall()
            _bld_real = {r[0]: {'count': int(r[1]), 'price_from': int(r[2] or 0), 'total_floors': r[3]}
                         for r in _bld_sql}
        except Exception as _bld_err:
            print(f"[building stats SQL error] {_bld_err}")
            db.session.rollback()
            _bld_real = {}

        # Pull per-corpus delivery dates directly from buildings table (authoritative source)
        try:
            db.session.rollback()
            _corpus_dates = db.session.execute(text(
                "SELECT COALESCE(building_name,'Основной корпус') AS bname, "
                "end_build_year, end_build_quarter, "
                "total_floors, total_apartments, released "
                "FROM buildings WHERE complex_id=:cid ORDER BY end_build_year, end_build_quarter"
            ), {'cid': complex.id}).fetchall()
            _corpus_dates_map = {}
            for _r in _corpus_dates:
                _corpus_dates_map[_r[0]] = {
                    'end_build_year': _r[1], 'end_build_quarter': _r[2],
                    'start_build_year': None, 'start_build_quarter': None,
                    'total_floors': _r[3], 'total_apartments': _r[4], 'released': _r[5]
                }
        except Exception as _cd_err:
            print(f"[corpus dates SQL error] {_cd_err}")
            db.session.rollback()
            _corpus_dates_map = {}

        buildings_dict = {}
        for building_name, building_props in properties_by_building.items():
            if not building_props:
                continue
            
            # Calculate building stats from properties
            building_prices = [p.get('price', 0) for p in building_props if p.get('price')]
            building_areas = [p.get('area', 0) for p in building_props if p.get('area')]
            
            # Get building years/quarters — prefer buildings table (authoritative) over properties
            first_prop = building_props[0]
            _cdate = _corpus_dates_map.get(building_name, {})
            end_build_year = _cdate.get('end_build_year') or first_prop.get('end_build_year') or complex_data.get('end_build_year')
            end_build_quarter = _cdate.get('end_build_quarter') or first_prop.get('end_build_quarter') or complex_data.get('end_build_quarter')
            start_build_year = _cdate.get('start_build_year') or first_prop.get('start_build_year') or complex_data.get('start_build_year')
            start_build_quarter = _cdate.get('start_build_quarter') or first_prop.get('start_build_quarter') or complex_data.get('start_build_quarter')
            
            # Determine building status based on completion date
            import datetime
            current_year = datetime.datetime.now().year
            current_quarter = (datetime.datetime.now().month - 1) // 3 + 1
            
            building_status = 'В процессе строительства'
            if end_build_year and end_build_quarter:
                try:
                    if int(end_build_year) < current_year or (int(end_build_year) == current_year and int(end_build_quarter) <= current_quarter):
                        building_status = 'Сдан'
                except (ValueError, TypeError):
                    pass
            
            # Get total_floors from properties in this building
            total_floors_list = [p.get('total_floors') or p.get('object_max_floor') for p in building_props if p.get('total_floors') or p.get('object_max_floor')]
            max_total_floors = max(total_floors_list) if total_floors_list else None
            
            # Use real DB count (building_props is limited to 500 total)
            _bld_info = _bld_real.get(building_name, {})
            real_apt_count = _bld_info.get('count') or len(building_props)
            real_price_from = _bld_info.get('price_from') or (int(min(building_prices)) if building_prices else 0)
            real_floors = _bld_info.get('total_floors') or max_total_floors

            # Create building info dict
            buildings_dict[building_name] = {
                'apartments_count': real_apt_count,
                'price_from': real_price_from,
                'price_to': int(max(building_prices)) if building_prices else 0,
                'area_from': int(min(building_areas)) if building_areas else 0,
                'area_to': int(max(building_areas)) if building_areas else 0,
                'end_build_year': end_build_year,
                'end_build_quarter': end_build_quarter,
                'start_build_year': start_build_year,
                'start_build_quarter': start_build_quarter,
                'building_status': building_status,
                'total_floors': _cdate.get('total_floors') or real_floors,
                'released': _cdate.get('released') or False,
            }
        
        # Add buildings that exist in DB but got 0 examples in the 500-property sample
        for _bname, _bdata in _bld_real.items():
            if _bname not in buildings_dict:
                buildings_dict[_bname] = {
                    'apartments_count': _bdata['count'],
                    'price_from': _bdata['price_from'],
                    'price_to': 0,
                    'area_from': 0,
                    'area_to': 0,
                    'end_build_year': complex_data.get('end_build_year'),
                    'end_build_quarter': complex_data.get('end_build_quarter'),
                    'start_build_year': complex_data.get('start_build_year'),
                    'start_build_quarter': complex_data.get('start_build_quarter'),
                    'building_status': 'Сдан' if (
                        complex_data.get('end_build_year') and
                        int(complex_data['end_build_year']) <= _dt_mod.datetime.now().year
                    ) else 'В процессе строительства',
                    'total_floors': _bdata.get('total_floors'),
                }

        # Re-sort buildings_dict by name
        import re as _re_bld
        def _sort_bld_key(n):
            m = _re_bld.search(r'(\d+)', n)
            return (int(m.group(1)), n) if m else (999, n)
        buildings_dict = dict(sorted(buildings_dict.items(), key=lambda x: _sort_bld_key(x[0])))

        # Add buildings dict to complex_data for template
        complex_data['buildings'] = buildings_dict
        complex_data['current_year'] = _dt_mod.datetime.now().year
        complex_data['current_quarter'] = (_dt_mod.datetime.now().month - 1) // 3 + 1

        # === STEP 5.6: Building plan — TA-enriched building objects ===
        try:
            from models import Building as _BldModel
            _bld_objs = _BldModel.query.filter_by(complex_id=complex.id).order_by(_BldModel.name).all()
            ta_buildings_list = []
            for _b in _bld_objs:
                import json as _json2
                _fin_list = []
                try:
                    if _b.finishing_types:
                        _fin_list = _json2.loads(_b.finishing_types) if isinstance(_b.finishing_types, str) else (_b.finishing_types or [])
                except Exception:
                    pass
                ta_buildings_list.append({
                    'id':                   _b.id,
                    'name':                 _b.name,
                    'queue':                _b.queue,
                    'total_floors':         _b.total_floors,
                    'total_apartments':     _b.total_apartments or _b.apartment_count,
                    'end_build_year':       _b.end_build_year,
                    'end_build_quarter':    _b.end_build_quarter,
                    'released':             _b.released,
                    'escrow':               _b.escrow,
                    'building_type':        _b.building_type_name,
                    'facade_type':          _b.facade_type_name,
                    'elevator_type':        _b.elevator_type,
                    'contract_types':       _b.contract_types,
                    'finishing_types':      _fin_list,
                    'sales_start_at':       _b.sales_start_at.strftime('%m.%Y') if _b.sales_start_at else None,
                    'boundary_geometry':    _b.boundary_geometry,
                    'has_interactive':      bool(_b.ta_interactive_geometry),
                    'interactive_geometry': _b.ta_interactive_geometry,
                    'ta_renderer':          _b.ta_renderer,
                })
            complex_data['ta_buildings_list'] = ta_buildings_list
        except Exception as _bld_ex:
            complex_data['ta_buildings_list'] = []
            print(f"[ta_buildings_list error] {_bld_ex}")
        
        # === STEP 6: Find similar complexes (smart scoring by city+class+price+district) ===
        similar_complexes = []
        try:
            # Must be same city — never mix Krasnodar with Sochi
            candidates = (
                db.session.query(ResidentialComplex)
                .filter(
                    ResidentialComplex.id != complex.id,
                    ResidentialComplex.is_active == True,
                    ResidentialComplex.city_id == complex.city_id
                )
                .all()
            )

            # Get city slug for URL building
            _sim_city_row = db.session.execute(
                text("SELECT slug FROM cities WHERE id = :cid"), {"cid": complex.city_id}
            ).fetchone()
            _sim_city_slug = _sim_city_row[0] if _sim_city_row else 'krasnodar'

            # Current complex reference values for scoring
            stats_by_complex = PropertyRepository.get_all_property_stats()
            cur_stats = stats_by_complex.get(complex.id, {})
            cur_min_price = cur_stats.get('min_price') or 0
            cur_class = (complex.object_class_display_name or '').lower()
            cur_district_id = complex.district_id

            scored = []
            for other in candidates:
                score = 0
                other_stats = stats_by_complex.get(other.id, {})
                other_min = other_stats.get('min_price') or 0

                # +3: same object class
                if (other.object_class_display_name or '').lower() == cur_class:
                    score += 3
                # +2: similar price (within 50% of current min price)
                if cur_min_price and other_min:
                    ratio = other_min / cur_min_price
                    if 0.5 <= ratio <= 1.5:
                        score += 2
                # +2: same district
                if cur_district_id and other.district_id == cur_district_id:
                    score += 2
                # +1: same developer
                if complex.developer_id and other.developer_id == complex.developer_id:
                    score += 1
                # Skip if no apartments
                if not other_stats.get('total_count') and not other_stats.get('total_properties') and not other_stats.get('count'):
                    continue
                scored.append((score, other, other_stats))

            # Sort by score desc, then by apartments count desc as tiebreaker
            scored.sort(key=lambda x: (x[0], x[2].get('total_count', x[2].get('count', 0))), reverse=True)

            for _score, other_complex, stats in scored[:3]:
                _apt_count = stats.get('total_count', stats.get('total_properties', stats.get('count', 0)))
                all_images = []
                image_url = other_complex.main_image
                if image_url:
                    all_images.append(image_url)
                if other_complex.gallery_images:
                    try:
                        gallery = json.loads(other_complex.gallery_images) if isinstance(other_complex.gallery_images, str) else []
                        for gimg in gallery[:5]:
                            if gimg and gimg not in all_images:
                                all_images.append(gimg)
                        if not image_url and gallery:
                            image_url = gallery[0]
                    except:
                        pass
                if not image_url:
                    image_url = 'https://via.placeholder.com/400x300/0088CC/FFFFFF?text=' + quote(other_complex.name[:20])
                    all_images = [image_url]

                similar_complexes.append({
                    'id': other_complex.id,
                    'name': other_complex.name,
                    'slug': other_complex.slug,
                    'developer': other_complex.developer.name if other_complex.developer else 'Не указан',
                    'district': other_complex.district.name if other_complex.district else '',
                    'location': other_complex.sales_address or other_complex.address or (other_complex.district.name if other_complex.district else ''),
                    'price_from': stats.get('min_price', 0),
                    'total_apartments': _apt_count,
                    'apartments_count': _apt_count,
                    'object_class': other_complex.object_class_display_name or 'Комфорт',
                    'image': image_url,
                    'images': all_images,
                    'completion_date': (
                        f"{other_complex.end_build_quarter} кв. {other_complex.end_build_year}"
                        if other_complex.end_build_quarter and other_complex.end_build_year
                        else 'Сдан'
                    ),
                    'cashback_percent': other_complex.cashback_rate or 0,
                    'url': f'/{_sim_city_slug}/zk/{other_complex.slug}'
                })

        except Exception as e:
            print(f"Error finding similar complexes: {e}")
            import traceback
            traceback.print_exc()
            similar_complexes = []
        
        # === STEP 7: Load active offers and marketing materials ===
        offers_objects = Offer.query.filter_by(
            residential_complex_id=complex.id, 
            is_active=True
        ).order_by(Offer.sort_order).all()
        
        offers = []
        for offer in offers_objects:
            offers.append({
                'id': offer.id,
                'title': offer.title,
                'description': offer.description or '',
                'image_url': offer.image_url,
                'is_active': offer.is_active,
                'sort_order': offer.sort_order
            })
        
        materials = MarketingMaterial.query.filter_by(
            residential_complex_id=complex.id,
            is_active=True
        ).order_by(MarketingMaterial.sort_order, MarketingMaterial.created_at.desc()).all()
        
        # Check if user is a manager or admin
        is_manager = isinstance(current_user._get_current_object(), Manager) if current_user.is_authenticated else False
        is_admin = isinstance(current_user._get_current_object(), Admin) if current_user.is_authenticated else False
        
        # === STEP 8: Load approved reviews ===
        from models import ComplexReview
        approved_reviews = ComplexReview.query.filter_by(
            residential_complex_id=complex.id, status='approved'
        ).order_by(ComplexReview.created_at.desc()).limit(20).all()
        avg_rating = db.session.query(db.func.avg(ComplexReview.rating)).filter_by(
            residential_complex_id=complex.id, status='approved'
        ).scalar()
        reviews_count = ComplexReview.query.filter_by(
            residential_complex_id=complex.id, status='approved'
        ).count()

        # === STEP 9: Chess board data (already computed via raw SQL in Step 2) ===
        try:
            chess_properties = _chess_data
        except NameError:
            chess_properties = []

        # === STEP 10: Telegram promotions (горячие акции из TG-группы) ===
        try:
            from models import TelegramPromotion
            tg_promos_raw = TelegramPromotion.query.filter(
                TelegramPromotion.is_active == True,
                db.or_(
                    TelegramPromotion.residential_complex_id == complex.id,
                    db.and_(
                        TelegramPromotion.developer_id == complex.developer_id,
                        TelegramPromotion.developer_id.isnot(None),
                        TelegramPromotion.residential_complex_id.is_(None)
                    )
                )
            ).order_by(TelegramPromotion.posted_at.desc()).limit(30).all()
            tg_promotions = []
            for p in tg_promos_raw:
                photos = p.get_photos()
                tg_promotions.append({
                    'id': p.id,
                    'title': p.title or p.tg_thread_title or 'Акция',
                    'description': p.description or '',
                    'raw_text': p.raw_text or '',
                    'photos': photos,
                    'first_photo': photos[0] if photos else None,
                    'thread_title': p.tg_thread_title or '',
                    'posted_at': p.posted_at.strftime('%d.%m.%Y') if p.posted_at else '',
                    'posted_at_full': p.posted_at.strftime('%d.%m.%Y %H:%M') if p.posted_at else '',
                })
        except Exception as _tg_err:
            tg_promotions = []

        from models import ChatSettings as _CS
        _proxy_val = _CS.get('image_proxy_enabled', '1')
        _proxy_enabled = _proxy_val == '1'

        return render_template('residential_complex_detail.html', 
                             current_city=current_city,
                             complex=complex_data,
                             properties=complex_properties,
                             chess_properties=chess_properties,
                             properties_by_rooms=properties_by_rooms,
                             properties_by_building=properties_by_building,
                             rooms_sql_summary=rooms_sql_summary,
                             similar_complexes=similar_complexes,
                             developer_info=complex.developer if complex.developer else None,
                             offers=offers,
                             materials=materials,
                             manager_authenticated=is_manager,
                             admin_authenticated=is_admin,
                             complex_reviews=approved_reviews,
                             reviews_avg_rating=round(float(avg_rating), 1) if avg_rating else 0,
                             reviews_count=reviews_count,
                             complex_id_for_reviews=complex.id,
                             tg_promotions=tg_promotions,
                             image_proxy_enabled=_proxy_enabled)
                             
    except Exception as e:
        print(f"ERROR in /residential_complex_by_slug_city: {e}")
        import traceback
        traceback.print_exc()
        return f"Error 500: {str(e)}", 500

@complexes_bp.route('/complexes-map')
def complexes_map():
    """Карта жилых комплексов"""
    try:
        # ✅ MIGRATED: Load residential complexes with coordinates using repository
        complexes_data = ResidentialComplexRepository.get_with_coordinates()
        property_stats = PropertyRepository.get_all_property_stats()
        
        residential_complexes = []
        import datetime as _dt_now
        current_year = _dt_now.datetime.now().year
        
        for row in complexes_data:
            complex_id = row.id
            stats = property_stats.get(complex_id, {})
            
            # Skip complexes without properties
            if not stats or stats.get('total_count', 0) == 0:
                continue
            
            # Determine status based on completion year - get from repository
            end_build_year = row.end_build_year
            end_build_quarter = row.end_build_quarter
            object_class_name = row.object_class_display_name
            status = 'Не указан'
            completion_date = 'Не указан'
            
            # Calculate status and completion date
            
            if end_build_year:
                if end_build_year <= current_year:
                    status = 'Сдан'
                else:
                    status = 'Строится'
                
                if end_build_quarter:
                    completion_date = f"{end_build_quarter} кв. {end_build_year}"
                else:
                    completion_date = f"{end_build_year} год"
            
            complex_data = {
                'id': complex_id,
                'name': row.name or '',
                'developer': row.developer_name or 'Не указан',
                'address': '',  # Not in get_with_coordinates()
                'district': 'Краснодарский край',
                'apartments_count': stats.get('total_count', 0),
                'price_from': int(stats.get('min_price', 0)),
                'coordinates': {
                    'lat': float(row.latitude) if row.latitude else 45.0448,
                    'lng': float(row.longitude) if row.longitude else 38.9760
                },
                'completion_date': completion_date,
                'status': status,
                'cashback_percent': float(row.cashback_rate) if row.cashback_rate else 0,
                'main_image': row.main_image or '/static/images/no-photo.svg',
                'description': f"Жилой комплекс {row.name or ''}",
                'object_class': object_class_name or 'Комфорт',
                'housing_class': object_class_name or 'Комфорт',
                'max_floors': 0,
                'url': f'/zk/{row.slug}' if row.slug else f'/residential-complex/{complex_id}',
                'type': 'complex'
            }
            residential_complexes.append(complex_data)
        
        # Фильтры для интерфейса
        all_districts = sorted(list(set(complex.get('district', 'Не указан') for complex in residential_complexes)))
        all_developers = sorted(list(set(complex.get('developer', 'Не указан') for complex in residential_complexes)))
        all_statuses = ['Все', 'Сдан', 'Строится']
        
        print(f"DEBUG: Found {len(residential_complexes)} complexes for map")
        if residential_complexes:
            print(f"DEBUG: First complex: {residential_complexes[0]}")
        
        _proxy_val = ChatSettings.get('image_proxy_enabled', '1')
        _proxy_enabled = _proxy_val == '1'
        return render_template('complexes_map.html', 
                             residential_complexes=residential_complexes,
                             all_districts=all_districts,
                             all_developers=all_developers,
                             all_statuses=all_statuses,
                             city_id=1,
                             image_proxy_enabled=_proxy_enabled)
                             
    except Exception as e:
        print(f"ERROR in complexes-map route: {e}")
        import traceback
        traceback.print_exc()
        return f"Error 500: {str(e)}", 500


# ─────────────────────────────────────────────────────────────────────────────
# AMP route — /amp/<city_slug>/zhilye-kompleksy/<slug>
# ─────────────────────────────────────────────────────────────────────────────

@complexes_bp.route('/amp/<city_slug>/zhilye-kompleksy/<slug>')
def complex_amp(city_slug, slug):
    """AMP-version of residential complex card page."""
    from models import ResidentialComplex, Property, City
    from sqlalchemy import func

    city = City.query.filter_by(slug=city_slug, is_active=True).first()
    if not city:
        from flask import abort
        abort(404)

    complex_obj = ResidentialComplex.query.filter_by(
        slug=slug, city_id=city.id, is_active=True
    ).first()
    if not complex_obj:
        from flask import abort
        abort(404)

    # Aggregate property data
    agg = db.session.query(
        func.min(Property.price).label('min_price'),
        func.count(Property.id).label('cnt'),
    ).filter(
        Property.complex_id == complex_obj.id,
        Property.is_active == True,
    ).first()

    min_price = int(agg.min_price) if agg and agg.min_price else None
    available_count = int(agg.cnt) if agg and agg.cnt else 0

    # OG image
    og_image = None
    try:
        imgs = complex_obj.gallery_images
        if isinstance(imgs, str):
            import json as _json
            imgs = _json.loads(imgs)
        if imgs and isinstance(imgs, list):
            og_image = imgs[0]
    except Exception:
        pass
    if not og_image:
        og_image = complex_obj.main_image or ''

    # Ensure absolute URL
    if og_image and og_image.startswith('/'):
        og_image = 'https://inback.ru' + og_image

    return render_template(
        'amp/complex_amp.html',
        complex=complex_obj,
        city_slug=city_slug,
        city_name=city.name,
        min_price=min_price,
        available_count=available_count,
        og_image=og_image,
    )

