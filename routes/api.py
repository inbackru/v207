"""
routes/api.py — JSON API & geocoding endpoints (extracted from app.py)

Covers:
  /api/search/suggestions
  /api/search/history/*
  /api/search/popular
  /api/developers
  /api/check-it-company
  /api/suggest-it-companies
  /api/detect-city
  /api/geocode/*
"""
import re as _re

import logging
import traceback

import requests as _requests

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import text, func

from app import csrf, db, require_json_csrf, search_global
from repositories.property_repository import PropertyRepository

logger = logging.getLogger(__name__)


def _get_dadata_client():
    from app import get_dadata_client as _gdc
    return _gdc()

def _get_geocoding_service():
    from app import get_geocoding_service as _ggs
    return _ggs()

def __set_city_in_session(city_id, city_slug):
    from app import set_city_in_session as _scis
    return _scis(city_id, city_slug)

bp = Blueprint('search_geo_api', __name__)

def _lazy_property_repo():
    from repositories import PropertyRepository as _PR
    return _PR

def _lazy_dev_model():
    from models import Developer as _Dev
    return _Dev

def _lazy_city_model():
    from models import City as _CityM
    return _CityM

def _get_popular_recommendations(city_id=None):
    """Return popular ЖК + room types for empty-query live search state."""
    from models import ResidentialComplex, Property as _Prop, City as _City
    results = []

    try:
        # ── 1. Room types with real counts ──────────────────────────────────
        room_labels = [
            (0,  'Студии',       'fas fa-home', '?rooms=0'),
            (1,  '1-комнатные',  'fas fa-home', '?rooms=1'),
            (2,  '2-комнатные',  'fas fa-home', '?rooms=2'),
            (3,  '3-комнатные',  'fas fa-home', '?rooms=3'),
        ]
        city_suffix = f'&city_id={city_id}' if city_id else ''
        for room_num, label, icon, url_suffix in room_labels:
            cnt_filters = {'rooms': [room_num]}
            if city_id:
                cnt_filters['city_id'] = city_id
            cnt = PropertyRepository.count_active(filters=cnt_filters)
            if cnt > 0:
                def _plural(n):
                    n = abs(n) % 100
                    if 11 <= n <= 14: return 'квартир'
                    d = n % 10
                    if d == 1: return 'квартира'
                    if 2 <= d <= 4: return 'квартиры'
                    return 'квартир'
                results.append({
                    'type': 'rooms',
                    'text': label,
                    'subtitle': f'{cnt} {_plural(cnt)}',
                    'icon': icon,
                    'url': url_suffix + city_suffix,
                })

        # ── 2. Top ЖК by property count ─────────────────────────────────────
        q = (db.session.query(
                ResidentialComplex.name,
                ResidentialComplex.slug,
                ResidentialComplex.main_image,
                func.count(_Prop.id).label('cnt')
             )
             .join(_Prop, _Prop.complex_id == ResidentialComplex.id, isouter=True)
             .filter(_Prop.is_active == True))
        if city_id:
            q = q.filter(ResidentialComplex.city_id == city_id)
        rows = (q.group_by(ResidentialComplex.id,
                           ResidentialComplex.name,
                           ResidentialComplex.slug,
                           ResidentialComplex.main_image)
                .order_by(func.count(_Prop.id).desc())
                .limit(5).all())

        city_slug = 'krasnodar'
        if city_id:
            _c = _City.query.get(city_id)
            if _c and _c.slug:
                city_slug = _c.slug

        for row in rows:
            if not row[0]:
                continue
            cnt = row[3] or 0
            if cnt == 0:
                continue
            def _p(n):
                n = abs(n) % 100
                if 11 <= n <= 14: return 'квартир'
                d = n % 10
                if d == 1: return 'квартира'
                if 2 <= d <= 4: return 'квартиры'
                return 'квартир'
            results.append({
                'type': 'complex',
                'text': row[0],
                'subtitle': f'ЖК · {cnt} {_p(cnt)} доступно',
                'icon': 'fas fa-building',
                'image_url': row[2] or '',
                'url': f'/{city_slug}/zk/{row[1]}' if row[1] else url_for('props.properties', residential_complex=row[0]),
            })
    except Exception as e:
        logger.warning(f'_get_popular_recommendations error: {e}')

    return jsonify(results)


@bp.route('/api/search/suggestions')
def search_suggestions():
    """API endpoint for search suggestions (autocomplete) - REAL DATABASE VERSION"""
    query = request.args.get('query', request.args.get('q', '')).lower().strip()

    # ✅ Get city context from URL parameter or session
    city_id = request.args.get('city_id', type=int)
    city_name_genitive = None
    if not city_id and 'city_id' in session:
        city_id = session['city_id']

    if not query or len(query) < 2:
        # Return popular recommendations for empty-state live search
        return _get_popular_recommendations(city_id)

    if city_id:
        from models import City
        city_obj = City.query.get(city_id)
        if city_obj:
            city_name_genitive = city_obj.name_genitive or city_obj.name
    
    suggestions = []
    

    def get_plural_form(count, singular, few, many):
        """Russian plural forms: 1 квартира, 2-4 квартиры, 5+ квартир"""
        count = abs(count) % 100
        if 11 <= count <= 14:
            return many
        last_digit = count % 10
        if last_digit == 1:
            return singular
        elif 2 <= last_digit <= 4:
            return few
        else:
            return many

    try:
        # 1. Search by room types (PRIORITY - user's main request)
        room_suggestions = {
            'студ': 'Студия',
            '1-к': '1-комнатная',
            '1-ком': '1-комнатная', 
            '1комн': '1-комнатная',
            '1к': '1-комнатная',
            '1 к': '1-комнатная',
            'одн': '1-комнатная',
            '2-к': '2-комнатная',
            '2-ком': '2-комнатная',
            '2комн': '2-комнатная',
            '2к': '2-комнатная',
            '2 к': '2-комнатная', 
            'двух': '2-комнатная',
            '3-к': '3-комнатная',
            '3-ком': '3-комнатная',
            '3комн': '3-комнатная',
            '3к': '3-комнатная',
            '3 к': '3-комнатная',
            'трех': '3-комнатная',
            'трёх': '3-комнатная',
            '4-к': '4-комнатная',
            '4-ком': '4-комнатная',
            '4комн': '4-комнатная',
            '4к': '4-комнатная',
            'четыр': '4-комнатная'
        }
        
        for pattern, room_type in room_suggestions.items():
            if pattern in query:
                # ✅ MIGRATED: Count properties by room type using PropertyRepository
                if 'студ' in pattern:
                    count = PropertyRepository.count_active(filters={'rooms': [0], 'city_id': city_id}) if city_id else PropertyRepository.count_active(filters={'rooms': [0]})
                else:
                    room_num = room_type.split('-')[0] if '-' in room_type else '1'
                    count = PropertyRepository.count_active(filters={'rooms': [int(room_num)], 'city_id': city_id}) if city_id else PropertyRepository.count_active(filters={'rooms': [int(room_num)]})
                
                # Создаем URL с тем же параметром что быстрые фильтры
                if 'студ' in pattern:
                    room_param = '0'
                else:
                    room_param = room_type.split('-')[0] if '-' in room_type else '1'
                
                
                # Build subtitle with correct city and plural form
                plural_form = get_plural_form(count, 'квартира', 'квартиры', 'квартир')
                if city_name_genitive:
                    subtitle = f'Найдено {count} {plural_form} для {city_name_genitive}'
                else:
                    subtitle = f'Найдено {count} {plural_form}'
                
                suggestions.append({
                    'type': 'rooms', 
                    'text': room_type,
                    'title': room_type,  # Добавляем title для совместимости
                    'subtitle': subtitle,
                    'url': url_for('props.properties', rooms=room_param)  # rooms=1 как быстрые фильтры
                })
        
        # ✅ NEW: Search by city name - high priority for city switching
        from models import City, Property as PropertyModel
        cities_query = (
            db.session.query(City.name, City.slug, func.count(PropertyModel.id).label('count'))
            .join(PropertyModel, PropertyModel.city_id == City.id, isouter=True)
            .filter(
                City.name.ilike(f'%{query}%'),
                PropertyModel.is_active == True
            )
            .group_by(City.id, City.name, City.slug)
            .having(func.count(PropertyModel.id) > 0)
            .order_by(func.count(PropertyModel.id).desc())
            .limit(5)
            .all()
        )
        
        for city_row in cities_query:
            city_name = city_row[0]
            city_slug = city_row[1]
            prop_count = city_row[2]
            if city_name and prop_count > 0:
                plural_form = get_plural_form(prop_count, 'квартира', 'квартиры', 'квартир')
                suggestions.append({
                    'type': 'city',
                    'text': city_name,
                    'subtitle': f'{prop_count} {plural_form}',
                    'url': url_for('props.properties_city', city_slug=city_slug) if city_slug else url_for('props.properties', city=city_name),
                    'icon': 'fas fa-city'
                })
        
        # ✅ MIGRATED: Search in residential complexes using ORM
        from models import ResidentialComplex, Property
        complexes_query = (
            db.session.query(
                ResidentialComplex.name,
                ResidentialComplex.slug,
                ResidentialComplex.main_image,
                func.count(Property.id).label('count'),
                ResidentialComplex.gallery_images
            )
            .join(Property, Property.complex_id == ResidentialComplex.id, isouter=True)
            .filter(
                ResidentialComplex.name.ilike(f'%{query}%'),
                ResidentialComplex.city_id == city_id,
                Property.is_active == True
            )
            .group_by(ResidentialComplex.id, ResidentialComplex.name, ResidentialComplex.slug, ResidentialComplex.main_image, ResidentialComplex.gallery_images)
            .order_by(func.count(Property.id).desc())
            .limit(5)
            .all()
        )

        # Determine city slug for complex URLs
        _city_slug_suggest = 'krasnodar'
        if city_id:
            from models import City as CityModel
            _city_obj = CityModel.query.get(city_id)
            if _city_obj and _city_obj.slug:
                _city_slug_suggest = _city_obj.slug

        def _pick_complex_image(main_image, gallery_images_raw):
            """Pick best image: main_image first, then first from gallery."""
            import json as _json
            if main_image:
                return main_image
            if gallery_images_raw:
                try:
                    imgs = _json.loads(gallery_images_raw) if isinstance(gallery_images_raw, str) else gallery_images_raw
                    if isinstance(imgs, list) and imgs:
                        return imgs[0]
                except Exception:
                    pass
            return ''

        for row in complexes_query:
            if row[0] and len(row[0]) > 2:  # Skip empty/short names
                _count = row[3]
                plural = 'квартира' if _count % 10 == 1 and _count % 100 != 11 else ('квартиры' if 2 <= _count % 10 <= 4 and _count % 100 not in range(11, 15) else 'квартир')
                suggestions.append({
                    'type': 'complex',
                    'text': row[0],
                    'subtitle': f'ЖК · {_count} {plural} доступно',
                    'url': f'/{_city_slug_suggest}/zk/{row[1]}' if row[1] else url_for('props.properties', residential_complex=row[0]),
                    'image_url': _pick_complex_image(row[2], row[4]),
                    'icon': 'fas fa-building'
                })
        
        # ✅ MIGRATED: Search in developers using ORM (with transliteration support)
        from models import Developer, ResidentialComplex as _RC2
        from sqlalchemy import or_ as _or

        def _ru_to_lat(text):
            """Transliterate Russian query to Latin for matching English developer names"""
            _map = {
                'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo',
                'ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m',
                'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u',
                'ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'sch',
                'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'
            }
            return ''.join(_map.get(c, c) for c in text.lower())

        def _lat_to_ru(text):
            """Approximate Latin → Russian transliteration for matching Cyrillic names"""
            _pairs = [
                ('yo','ё'),('yu','ю'),('ya','я'),('zh','ж'),('kh','х'),
                ('ts','ц'),('ch','ч'),('sh','ш'),('sch','щ'),
                ('a','а'),('b','б'),('v','в'),('g','г'),('d','д'),('e','е'),
                ('z','з'),('i','и'),('y','й'),('k','к'),('l','л'),('m','м'),
                ('n','н'),('o','о'),('p','п'),('r','р'),('s','с'),('t','т'),
                ('u','у'),('f','ф'),
            ]
            result = text.lower()
            for lat, ru in _pairs:
                result = result.replace(lat, ru)
            return result

        _query_lat = _ru_to_lat(query)
        _query_ru  = _lat_to_ru(query)

        _dev_filters = [Developer.name.ilike(f'%{query}%')]
        if _query_lat and _query_lat != query:
            _dev_filters.append(Developer.name.ilike(f'%{_query_lat}%'))
        if _query_ru and _query_ru != query:
            _dev_filters.append(Developer.name.ilike(f'%{_query_ru}%'))

        developers_query = (
            db.session.query(
                Developer.name,
                func.count(func.distinct(Property.id)).label('prop_count'),
                func.count(func.distinct(_RC2.id)).label('complex_count'),
                Developer.logo_url
            )
            .outerjoin(Property, (Property.developer_id == Developer.id) & (Property.city_id == city_id) & (Property.is_active == True))
            .outerjoin(_RC2, (_RC2.developer_id == Developer.id) & (_RC2.city_id == city_id) & (_RC2.is_active == True))
            .filter(_or(*_dev_filters))
            .group_by(Developer.name, Developer.logo_url)
            .order_by(func.count(func.distinct(Property.id)).desc())
            .limit(4)
            .all()
        )
        
        for row in developers_query:
            if row[0] and len(row[0]) > 2 and (row[1] or 0) > 0:
                prop_count = row[1] or 0
                complex_count = row[2] or 0
                dev_logo = row[3] or ''
                plural_kv = get_plural_form(prop_count, 'квартира', 'квартиры', 'квартир')
                jk_str = f' · {complex_count} ЖК' if complex_count > 0 else ''
                _dev_sug = {
                    'type': 'developer',
                    'text': row[0],
                    'subtitle': f'Застройщик{jk_str} · {prop_count} {plural_kv}',
                    'icon': 'fas fa-hard-hat',
                    'url': url_for('props.properties', developer=row[0])
                }
                if dev_logo:
                    _dev_sug['image_url'] = dev_logo
                suggestions.append(_dev_sug)
        
        # ── RC Address field suggestions: okrug + quarter ──────────────────────
        # These come directly from CIAN typed JSON — more reliable than the
        # districts table which has mixed data. Covers all cities uniformly.
        try:
            from models import ResidentialComplex as _RC_sug, District as _Dist_sug
            import re as _re_addr

            def _norm_dist_name(n):
                """Normalize district name for dedup: strip prefix/suffix like 'округ', 'район'."""
                n = (n or '').lower().strip()
                for pfx in ('округ ', 'район ', 'микрорайон ', 'мкр. ', 'мкр '):
                    if n.startswith(pfx):
                        n = n[len(pfx):].strip()
                        break
                for sfx in (' округ', ' район', ' мкр', ' жилрайон', ' жилмассив', ' жилой массив'):
                    if n.endswith(sfx):
                        n = n[:-len(sfx)].strip()
                        break
                return n

            _addr_q = _re_addr.sub(
                r'^(мкр\.?\s+|микрорайон\s+|р[-.]н\.?\s+|район\s+|округ\s+|жилрайон\s+|жр\s+)',
                '', query, flags=_re_addr.IGNORECASE
            ).strip()
            _addr_search = _addr_q if len(_addr_q) >= 2 else query

            _rc_addr_filters = [_RC_sug.is_active == True]
            if city_id:
                _rc_addr_filters.append(_RC_sug.city_id == city_id)

            # Pre-build district lookup: normalized_name -> (canonical_name, slug, district_type)
            _dist_lookup = {}
            try:
                _dlookup_q = _Dist_sug.query
                if city_id:
                    _dlookup_q = _dlookup_q.filter(_Dist_sug.city_id == city_id)
                for _dl in _dlookup_q.all():
                    _key = _norm_dist_name(_dl.name)
                    _dist_lookup[_key] = (_dl.name, _dl.slug, _dl.district_type or '')
            except Exception:
                pass

            # okrug suggestions
            _okrug_rows = (
                db.session.query(
                    _RC_sug.address_city_district,
                    _RC_sug.city_id,
                    func.count(_RC_sug.id).label('rc_cnt')
                )
                .filter(
                    *_rc_addr_filters,
                    _RC_sug.address_city_district.isnot(None),
                    _RC_sug.address_city_district.ilike(f'%{_addr_search}%')
                )
                .group_by(_RC_sug.address_city_district, _RC_sug.city_id)
                .order_by(func.count(_RC_sug.id).desc())
                .limit(4)
                .all()
            )
            # Track normalized names already added to avoid duplicates
            _added_norm_names = set(_norm_dist_name(s.get('text', '')) for s in suggestions if s.get('type') == 'district')
            for _okr in _okrug_rows:
                _okr_name = (_okr[0] or '').strip()
                if not _okr_name or len(_okr_name) < 3:
                    continue
                # Resolve to canonical district (normalize + FK lookup)
                _okr_norm = _norm_dist_name(_okr_name)
                _canon = _dist_lookup.get(_okr_norm)
                _display_name = _canon[0] if _canon else _okr_name
                _canon_norm = _norm_dist_name(_display_name)
                # Skip if already added (by normalized name)
                if _okr_norm in _added_norm_names or _canon_norm in _added_norm_names:
                    continue
                # Count properties via district_id FK if canonical district found
                _okr_d_type = _canon[2] if _canon else ''
                _okr_slug = _canon[1] if _canon else None
                if _okr_slug:
                    _okr_prop_cnt = (
                        db.session.query(func.count(Property.id))
                        .join(_Dist_sug, Property.district_id == _Dist_sug.id)
                        .filter(
                            Property.is_active == True,
                            _Dist_sug.slug == _okr_slug
                        )
                        .scalar() or 0
                    )
                else:
                    _okr_prop_cnt = 0
                _rc_cnt = _okr[2]
                _okr_plural = get_plural_form(_okr_prop_cnt, 'квартира', 'квартиры', 'квартир')
                _dtype_label = {'okrug': 'Округ', 'microrayon': 'Микрорайон', 'settlement': 'Поселение'}.get(_okr_d_type, 'Район')
                _okr_subtitle = f'{_dtype_label} · {_okr_prop_cnt} {_okr_plural}' if _okr_prop_cnt else f'{_dtype_label} · {_rc_cnt} ЖК'
                if _city_slug_suggest and _okr_slug:
                    _okr_url = url_for('props.properties_city', city_slug=_city_slug_suggest, districts=_okr_slug)
                elif _city_slug_suggest:
                    _okr_url = url_for('props.properties_city', city_slug=_city_slug_suggest, district=_display_name)
                else:
                    _okr_url = url_for('props.properties', district=_display_name)
                _added_norm_names.add(_okr_norm)
                _added_norm_names.add(_canon_norm)
                suggestions.append({
                    'type': 'district',
                    'district_type': _okr_d_type,
                    'text': _display_name,
                    'subtitle': _okr_subtitle,
                    'url': _okr_url,
                    'icon': 'fas fa-city'
                })

            # quarter/microrayon suggestions
            _quarter_rows = (
                db.session.query(
                    _RC_sug.address_quarter,
                    _RC_sug.city_id,
                    func.count(_RC_sug.id).label('rc_cnt')
                )
                .filter(
                    *_rc_addr_filters,
                    _RC_sug.address_quarter.isnot(None),
                    _RC_sug.address_quarter.ilike(f'%{_addr_search}%')
                )
                .group_by(_RC_sug.address_quarter, _RC_sug.city_id)
                .order_by(func.count(_RC_sug.id).desc())
                .limit(3)
                .all()
            )
            for _qr in _quarter_rows:
                _qr_name = (_qr[0] or '').strip()
                if not _qr_name or len(_qr_name) < 3:
                    continue
                _qr_norm = _norm_dist_name(_qr_name)
                if _qr_norm in _added_norm_names or any(s.get('text', '').lower() == _qr_name.lower() for s in suggestions):
                    continue
                _qr_prop_cnt = (
                    db.session.query(func.count(Property.id))
                    .filter(
                        Property.is_active == True,
                        Property.parsed_settlement.ilike(f'%{_qr_name}%')
                    )
                    .scalar() or 0
                )
                _qr_plural = get_plural_form(_qr_prop_cnt, 'квартира', 'квартиры', 'квартир')
                _qr_subtitle = f'Микрорайон · {_qr_prop_cnt} {_qr_plural}' if _qr_prop_cnt else f'Микрорайон · {_qr[2]} ЖК'
                if _city_slug_suggest:
                    _qr_url = url_for('props.properties_city', city_slug=_city_slug_suggest, district=_qr_name)
                else:
                    _qr_url = url_for('props.properties', district=_qr_name)
                suggestions.append({
                    'type': 'district',
                    'text': _qr_name,
                    'subtitle': _qr_subtitle,
                    'url': _qr_url,
                    'icon': 'fas fa-map-marker-alt'
                })

            # street suggestions from RC address fields
            _street_rows = (
                db.session.query(
                    _RC_sug.addr_street,
                    func.count(_RC_sug.id).label('rc_cnt')
                )
                .filter(
                    *_rc_addr_filters,
                    _RC_sug.addr_street.isnot(None),
                    _RC_sug.addr_street.ilike(f'%{_addr_search}%')
                )
                .group_by(_RC_sug.addr_street)
                .order_by(func.count(_RC_sug.id).desc())
                .limit(3)
                .all()
            )
            for _st in _street_rows:
                _st_name = (_st[0] or '').strip()
                if not _st_name or len(_st_name) < 3:
                    continue
                _already = any(s.get('text', '').lower() == _st_name.lower() for s in suggestions)
                if _already:
                    continue
                _st_prop_cnt = (
                    db.session.query(func.count(Property.id))
                    .filter(
                        Property.is_active == True,
                        Property.parsed_street.ilike(f'%{_st_name}%')
                    )
                    .scalar() or 0
                )
                _st_plural = get_plural_form(_st_prop_cnt, 'квартира', 'квартиры', 'квартир')
                _st_subtitle = f'Улица · {_st_prop_cnt} {_st_plural}' if _st_prop_cnt else f'Улица · {_st[1]} ЖК'
                if _city_slug_suggest:
                    _st_url = url_for('props.properties_city', city_slug=_city_slug_suggest, street=_st_name)
                else:
                    _st_url = url_for('props.properties', street=_st_name)
                suggestions.append({
                    'type': 'address',
                    'text': _st_name,
                    'subtitle': _st_subtitle,
                    'url': _st_url,
                    'icon': 'fas fa-road'
                })

            # ── Street table lookup (precise, city-filtered) ───────────────────
            try:
                from models import Street as _Street
                _st_tbl_filter = [
                    _Street.name.ilike(f'%{_addr_search}%'),
                ]
                if city_id:
                    _st_tbl_filter.append(_Street.city_id == city_id)
                _st_tbl_rows = (
                    db.session.query(
                        _Street.name,
                        _Street.slug,
                        func.count(Property.id).label('prop_cnt'),
                    )
                    .outerjoin(
                        Property,
                        (Property.parsed_street.ilike(_Street.name)) & (Property.is_active == True)
                    )
                    .filter(*_st_tbl_filter)
                    .group_by(_Street.name, _Street.slug)
                    .order_by(func.count(Property.id).desc(), _Street.name)
                    .limit(4)
                    .all()
                )
                for _sr in _st_tbl_rows:
                    _sr_name = (_sr[0] or '').strip()
                    if not _sr_name or len(_sr_name) < 4:
                        continue
                    _already2 = any(s.get('text', '').lower() == _sr_name.lower() for s in suggestions)
                    if _already2:
                        continue
                    _sr_cnt = _sr[2] or 0
                    _sr_plural = get_plural_form(_sr_cnt, 'квартира', 'квартиры', 'квартир')
                    _sr_subtitle = f'Улица · {_sr_cnt} {_sr_plural}' if _sr_cnt else 'Улица'
                    if _city_slug_suggest and _sr[1]:
                        _sr_url = url_for('props.properties_city', city_slug=_city_slug_suggest, street=_sr_name)
                    elif _city_slug_suggest:
                        _sr_url = url_for('props.properties_city', city_slug=_city_slug_suggest, street=_sr_name)
                    else:
                        _sr_url = url_for('props.properties', street=_sr_name)
                    suggestions.append({
                        'type': 'address',
                        'text': _sr_name,
                        'subtitle': _sr_subtitle,
                        'url': _sr_url,
                        'icon': 'fas fa-road'
                    })
            except Exception:
                pass

        except Exception as _e_addr:
            pass

        # ✅ MIGRATED: Search in districts using ORM with city filtering
        from models import District
        # Strip common Russian district prefixes before searching (e.g. "мкр Любимово" → "Любимово")
        import re as _re
        _district_query = _re.sub(
            r'^(мкр\.?\s+|микрорайон\s+|р[-.]н\.?\s+|район\s+|пос\.?\s+|посёлок\s+|поселок\s+|жк\s+)',
            '', query, flags=_re.IGNORECASE
        ).strip()
        _dist_search = _district_query if len(_district_query) >= 2 else query
        districts_filter = [
            District.name.ilike(f'%{_dist_search}%'),
            Property.is_active == True
        ]
        
        # ✅ Filter by current city if city_id is set
        if city_id:
            districts_filter.append(District.city_id == city_id)
        
        districts_query = (
            db.session.query(District.id, District.name, District.slug, District.district_type, func.count(Property.id).label('count'))
            .join(Property, Property.district_id == District.id, isouter=True)
            .filter(*districts_filter)
            .group_by(District.id, District.name, District.slug, District.district_type)
            .order_by(func.count(Property.id).desc())
            .limit(5)
            .all()
        )
        
        for row in districts_query:
            if row[1] and 'Краснодарский' not in row[1]:  # Skip generic region name
                clean_district = row[1].replace('Россия, ', '').replace('Краснодарский край, ', '')
                d_slug = row[2]
                d_type = row[3] or ''

                _dtype_prefix_map = {
                    'okrug': 'Округ',
                    'microrayon': 'Микрорайон',
                    'settlement': 'Поселение',
                    'admin': 'Район',
                }
                # Use canonical district name directly (no prefix prepending — badge shows type)
                display_text = clean_district

                _dtype_label_map = {
                    'okrug': 'Округ',
                    'microrayon': 'Микрорайон',
                    'settlement': 'Поселение',
                    'admin': 'Район города',
                }
                type_label = _dtype_label_map.get(d_type, 'Район города')
                _prop_count_d2 = row[4] or 0
                _plural_d2 = get_plural_form(_prop_count_d2, 'квартира', 'квартиры', 'квартир')
                _subtitle_d2 = f'{type_label} · {_prop_count_d2} {_plural_d2}' if _prop_count_d2 else type_label

                # Normalized dedup — catches "Прикубанский округ" == "Прикубанский"
                try:
                    _norm_fn = _norm_dist_name
                except NameError:
                    def _norm_fn(n):
                        n = (n or '').lower().strip()
                        for p in ('округ ', 'район ', 'микрорайон ', 'мкр. ', 'мкр '):
                            if n.startswith(p): n = n[len(p):].strip(); break
                        for s in (' округ', ' район', ' мкр', ' жилрайон'):
                            if n.endswith(s): n = n[:-len(s)].strip(); break
                        return n
                _norm_display = _norm_fn(display_text)
                already_added = any(_norm_fn(s.get('text', '')) == _norm_display for s in suggestions if s.get('type') == 'district')

                if not already_added:
                    if _city_slug_suggest and d_slug:
                        _dist_url = url_for('props.properties_city', city_slug=_city_slug_suggest, districts=d_slug)
                    elif _city_slug_suggest:
                        _dist_url = url_for('props.properties_city', city_slug=_city_slug_suggest, districts=clean_district)
                    else:
                        _dist_url = url_for('props.properties', districts=clean_district)
                    suggestions.append({
                        'type': 'district',
                        'district_type': d_type,
                        'text': display_text,
                        'subtitle': _subtitle_d2,
                        'url': _dist_url
                    })
        
        # Search by property types (квартира, пентхаус, таунхаус, дом)
        property_type_keywords = {
            'квартир': 'Квартира',
            'пентхаус': 'Пентхаус',
            'таунхаус': 'Таунхаус',
            'дом': 'Дом',
            'house': 'Дом',
            'townhouse': 'Таунхаус'
        }
        
        for keyword, prop_type in property_type_keywords.items():
            if keyword in query:
                # Count properties of this type
                try:
                    count_query = (
                        db.session.query(func.count(Property.id))
                        .filter(
                            Property.property_type.ilike(f'%{prop_type}%'),
                            Property.is_active == True
                        )
                    )
                    count = count_query.scalar() or 0
                    
                    if count > 0:  # Only show if there are results
                        suggestions.append({
                            'type': 'property_type',
                            'text': prop_type,
                            'subtitle': f'Найдено {count} объектов',
                            'url': url_for('props.properties', property_type=prop_type)
                        })
                except Exception as e:
                    print(f"Property type search error: {e}")
                    pass
        
        # ✅ Search by address/street in properties table (address field, city-filtered)
        try:
            from sqlalchemy import func as sql_func
            # Build city URL prefix for suggestions
            _city_slug_addr = None
            if city_id:
                from models import City as _CityA
                _ca = _CityA.query.get(city_id)
                if _ca and _ca.slug:
                    _city_slug_addr = _ca.slug

            # Extract a clean street name from full address (strip house number)
            import re as _re
            # Search in Property.address which stores full address like "ул. Западный обход, 65к1"
            addr_filter = [
                Property.is_active == True,
                Property.address.isnot(None),
                Property.address != '',
                Property.address.ilike(f'%{query}%')
            ]
            if city_id:
                addr_filter.append(Property.city_id == city_id)

            addr_results_raw = (
                db.session.query(Property.address, sql_func.count(Property.id).label('cnt'))
                .filter(*addr_filter)
                .group_by(Property.address)
                .order_by(sql_func.count(Property.id).desc())
                .limit(20)
                .all()
            )

            # Aggregate by street (strip house number)
            street_counts = {}
            for addr_row in addr_results_raw:
                full_addr = addr_row[0] or ''
                cnt = addr_row[1]
                # Extract street portion before the comma+number
                street_part = _re.split(r',\s*\d', full_addr)[0].strip()
                # Remove city prefix if present
                for prefix in ['Краснодар, ', 'Сочи, ', 'Россия, ', 'Краснодарский край, ']:
                    street_part = street_part.replace(prefix, '')
                street_part = street_part.strip()
                if street_part and len(street_part) > 3:
                    street_counts[street_part] = street_counts.get(street_part, 0) + cnt

            # Also search parsed_street if available
            ps_filter = [
                Property.is_active == True,
                Property.parsed_street.isnot(None),
                Property.parsed_street != '',
                Property.parsed_street.ilike(f'%{query}%')
            ]
            if city_id:
                ps_filter.append(Property.city_id == city_id)
            ps_results = (
                db.session.query(Property.parsed_street, sql_func.count(Property.id).label('cnt'))
                .filter(*ps_filter)
                .group_by(Property.parsed_street)
                .order_by(sql_func.count(Property.id).desc())
                .limit(5)
                .all()
            )
            for ps_row in ps_results:
                sn = (ps_row[0] or '').strip()
                if sn and len(sn) > 3:
                    street_counts[sn] = street_counts.get(sn, 0) + ps_row[1]

            # Sort by count and take top 5 unique streets
            sorted_streets = sorted(street_counts.items(), key=lambda x: -x[1])[:5]
            for street_name, prop_count in sorted_streets:
                _already_st = any(s.get('text', '').lower() == street_name.lower() for s in suggestions)
                if _already_st:
                    continue
                plural_form = get_plural_form(prop_count, 'квартира', 'квартиры', 'квартир')
                if _city_slug_addr:
                    search_url = url_for('props.properties_city', city_slug=_city_slug_addr, street=street_name)
                else:
                    search_url = url_for('props.properties', street=street_name)
                suggestions.append({
                    'type': 'address',
                    'text': street_name,
                    'subtitle': f'{prop_count} {plural_form}',
                    'url': search_url,
                    'icon': 'fas fa-map-marker-alt'
                })
        except Exception as e:
            print(f"Address search error: {e}")
            pass
        
        # DaData address suggestions (cities, streets, districts)
        dadata = _get_dadata_client()
        if dadata.is_available():
            try:
                dadata_suggestions = dadata.suggest_address(
                    query,
                    count=5,
                    # ✅ NO city_id filter - universal search for ALL cities (like Avito/Cian)
                )
                for item in dadata_suggestions:
                    addr_type = item['type']
                    item_data = item.get('data', {})

                    # Skip districts from DaData - we use local District table instead
                    if addr_type == 'district':
                        continue

                    # For streets/settlements: filter to current city only
                    if addr_type in ('street', 'settlement'):
                        item_city = (item_data.get('city') or item_data.get('settlement') or '').lower()
                        # If city_id is set, only show suggestions from current city
                        if city_id and _city_slug_suggest:
                            from models import City as _CityCheck
                            _cur_city = _CityCheck.query.get(city_id)
                            _cur_city_name = (_cur_city.name if _cur_city else '').lower()
                            if item_city and item_city != _cur_city_name:
                                continue  # Skip suggestions from other cities

                        # Extract just the street/settlement name (not "г Краснодар, ул ...")
                        street_with_type = item_data.get('street_with_type') or item_data.get('settlement_with_type') or ''
                        street_only = item_data.get('street') or item_data.get('settlement') or ''
                        search_term = street_with_type or street_only or item['text']

                        # Skip DaData street if a DB address suggestion already covers this street
                        # (DB address suggestions are more accurate with correct counts)
                        _already_in_addr = any(
                            s.get('type') == 'address' and street_only and street_only.lower() in s.get('text', '').lower()
                            for s in suggestions
                        )
                        if _already_in_addr:
                            continue

                        # Count only for specific streets (multi-word name = specific, single word = too broad)
                        _is_specific = len(street_only.split()) > 1
                        if _is_specific:
                            _dd_cnt_q = db.session.query(func.count(Property.id)).filter(
                                Property.is_active == True,
                                Property.address.ilike(f'%{street_only}%')
                            )
                            if city_id:
                                _dd_cnt_q = _dd_cnt_q.filter(Property.city_id == city_id)
                            _dd_cnt = _dd_cnt_q.scalar() or 0
                        else:
                            _dd_cnt = 0
                        _dd_plural = get_plural_form(_dd_cnt, 'квартира', 'квартиры', 'квартир')
                        _dd_subtitle = f'{_dd_cnt} {_dd_plural}' if _dd_cnt > 0 else ''

                        # For settlements: try to match to a local District first (use ?districts=slug)
                        _district_url = None
                        if addr_type == 'settlement' and street_only and city_id:
                            try:
                                from models import District as _DM_dd
                                _dd_dist = _DM_dd.query.filter(
                                    _DM_dd.city_id == city_id,
                                    _DM_dd.name.ilike(f'%{street_only}%')
                                ).first()
                                if _dd_dist and _dd_dist.slug and _city_slug_suggest:
                                    _district_url = url_for('props.properties_city',
                                                            city_slug=_city_slug_suggest,
                                                            districts=_dd_dist.slug)
                            except Exception:
                                pass

                        if _district_url:
                            _dadata_url = _district_url
                        elif addr_type == 'street' and search_term:
                            if _city_slug_suggest:
                                _dadata_url = url_for('props.properties_city', city_slug=_city_slug_suggest, street=search_term)
                            else:
                                _dadata_url = url_for('props.properties', street=search_term)
                        elif _city_slug_suggest:
                            _dadata_url = url_for('props.properties_city', city_slug=_city_slug_suggest, search=search_term)
                        else:
                            _dadata_url = url_for('props.properties', search=search_term)

                        suggestions.append({
                            'type': addr_type,
                            'text': item['text'],
                            'subtitle': _dd_subtitle,
                            'url': _dadata_url,
                            'source': 'dadata'
                        })
                        continue

                    # City type
                    if addr_type == 'city':
                        _dd_slug = (item_data.get('city', '') or '').lower()
                        from models import City as _CityM
                        _dd_city = _CityM.query.filter(_CityM.slug == _dd_slug).first() or \
                                   _CityM.query.filter(_CityM.name.ilike(f"%{_dd_slug}%")).first()
                        if _dd_city:
                            _dadata_url = url_for('props.properties_city', city_slug=_dd_city.slug)
                        elif _city_slug_suggest:
                            _dadata_url = url_for('props.properties_city', city_slug=_city_slug_suggest, search=item['text'])
                        else:
                            _dadata_url = url_for('props.properties', search=item['text'])
                        suggestions.append({
                            'type': addr_type,
                            'text': item['text'],
                            'subtitle': '',
                            'url': _dadata_url,
                            'source': 'dadata'
                        })
                        continue

                    # Other types
                    if _city_slug_suggest:
                        _dadata_url = url_for('props.properties_city', city_slug=_city_slug_suggest, search=item['text'])
                    else:
                        _dadata_url = url_for('props.properties', search=item['text'])
                    suggestions.append({
                        'type': addr_type,
                        'text': item['text'],
                        'subtitle': '',
                        'url': _dadata_url,
                        'source': 'dadata'
                    })
                current_app.logger.info(f"✅ DaData added {len(dadata_suggestions)} address suggestions")
            except Exception as e:
                current_app.logger.warning(f"DaData suggestions failed (fallback to DB): {e}")
        
        # Sort by relevance: rooms first, then items WITH property counts (by count desc), then no-count items
        import re as _re_sort
        def _suggestion_sort_key(s):
            stype = s.get('type', '')
            if stype in ('rooms', 'room_type'):
                return (0, 0, 0, 0)
            subtitle = s.get('subtitle', '')
            m = _re_sort.search(r'(\d+)', subtitle)
            count = int(m.group(1)) if m else 0
            # exact match bonus
            exact = 0 if s.get('text', '').lower().startswith(query) else 1
            # type priority: complex/developer/address > district > city > dadata
            type_order = (1 if stype in ('complex', 'developer', 'address') else
                          2 if stype == 'district' else
                          3 if stype == 'city' else 4)
            has_count = 0 if count > 0 else 1
            return (1, exact, has_count, -count)
        suggestions.sort(key=_suggestion_sort_key)
        
        # Deduplicate by (type, text) before returning
        seen_keys = set()
        unique_suggestions = []
        for s in suggestions:
            key = (s.get('type', ''), s.get('text', '').lower().strip())
            if key not in seen_keys:
                seen_keys.add(key)
                unique_suggestions.append(s)
        suggestions = unique_suggestions

        return jsonify(suggestions[:10])  # Return top 10 suggestions
        
    except Exception as e:
        current_app.logger.error(f"Error in search suggestions: {e}")
        return jsonify([])


@require_json_csrf
@bp.route('/api/search/history/save', methods=['POST'])
def save_search_history():
    """Save user's search query to history"""
    try:
        from models import SearchHistory, SearchAnalytics, Manager
        
        data = request.get_json() or {}
        query = data.get('query', '').strip()
        result_count = data.get('result_count', 0)
        
        if not query:
            return jsonify({'success': False, 'error': 'Query is required'}), 400
        
        # Determine user or manager using proper isinstance check
        user_id = None
        manager_id = None
        
        if current_user.is_authenticated:
            current_obj = current_user._get_current_object()
            if isinstance(current_obj, Manager):
                manager_id = current_user.id
            else:
                user_id = current_user.id
        
        # Only save history for authenticated users
        if user_id or manager_id:
            # Save to search history
            history_entry = SearchHistory(
                query=query,
                user_id=user_id,
                manager_id=manager_id,
                result_count=result_count
            )
            db.session.add(history_entry)
            
            # Record in analytics
            SearchAnalytics.record_search(query, result_count)
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Search saved to history'
            })
        else:
            # Unauthorized - require authentication for search history
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
    
    except Exception as e:
        current_app.logger.error(f"Error saving search history: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/search/history/list')
def get_search_history():
    """Get user's search history (last 20 searches)"""
    try:
        from models import SearchHistory, Manager
        
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'history': [], 'error': 'Not authenticated'}), 401
        
        # Determine if user or manager using proper isinstance check
        current_obj = current_user._get_current_object()
        if isinstance(current_obj, Manager):
            history = db.session.query(SearchHistory).filter_by(
                manager_id=current_user.id
            ).order_by(SearchHistory.created_at.desc()).limit(20).all()
        else:
            history = db.session.query(SearchHistory).filter_by(
                user_id=current_user.id
            ).order_by(SearchHistory.created_at.desc()).limit(20).all()
        
        return jsonify({
            'success': True,
            'history': [h.to_dict() for h in history]
        })
    
    except Exception as e:
        current_app.logger.error(f"Error getting search history: {e}")
        return jsonify({'success': False, 'history': [], 'error': str(e)}), 500


@bp.route('/api/search/popular')
def get_popular_searches():
    """Get popular search queries from real user data"""
    try:
        from models import SearchAnalytics
        
        limit = request.args.get('limit', default=10, type=int)
        limit = min(limit, 20)  # Cap at 20
        
        # Get popular searches from analytics
        popular = SearchAnalytics.get_popular_searches(limit=limit, min_results=1)
        
        # Format for frontend
        suggestions = []
        for analytics in popular:
            # Create room type button if it's a room search
            query = analytics.query
            icon = '🔥'
            
            # Detect room types for appropriate icons
            if any(word in query for word in ['студ', 'studio']):
                icon = '🏠'
            elif any(word in query for word in ['1', 'одн', 'один']):
                icon = '🏠'
            elif any(word in query for word in ['2', 'двух', 'два']):
                icon = '🏠'
            elif any(word in query for word in ['3', 'трех', 'три', 'трёх']):
                icon = '🏠'
            elif any(word in query for word in ['центр', 'цен']):
                icon = '📍'
            elif any(word in query for word in ['парк', 'сквер']):
                icon = '🌳'
            
            suggestions.append({
                'query': query,
                'icon': icon,
                'count': int(analytics.result_count_avg),
                'search_count': analytics.search_count
            })
        
        return jsonify({
            'success': True,
            'popular': suggestions
        })
    
    except Exception as e:
        current_app.logger.error(f"Error getting popular searches: {e}")
        return jsonify({'success': False, 'popular': []})
@bp.route('/api/developers')
def api_developers():
    """API endpoint to get developers filtered by city_id"""
    try:
        from models import Developer, ResidentialComplex, Property
        from sqlalchemy import func, distinct
        
        # Get optional city_id from query parameter
        city_id = request.args.get('city_id', type=int)
        
        # Use subquery approach for better performance
        if city_id:
            # Subquery to count properties per developer for a specific city
            property_count_subquery = (
                db.session.query(
                    Developer.id.label('dev_id'),
                    func.count(distinct(Property.id)).label('properties_count')
                )
                .join(ResidentialComplex, Developer.id == ResidentialComplex.developer_id)
                .join(Property, ResidentialComplex.id == Property.complex_id)
                .filter(Property.city_id == city_id)
                .filter(ResidentialComplex.city_id == city_id)
                .group_by(Developer.id)
                .having(func.count(distinct(Property.id)) > 0)
                .subquery()
            )
            
            # Main query joining developers with the subquery
            developers_list = (
                db.session.query(
                    Developer,
                    property_count_subquery.c.properties_count
                )
                .join(property_count_subquery, Developer.id == property_count_subquery.c.dev_id)
                .order_by(property_count_subquery.c.properties_count.desc())
                .all()
            )
        else:
            # All developers without city filter
            developers_list = (
                db.session.query(
                    Developer,
                    func.count(distinct(Property.id)).label('properties_count')
                )
                .outerjoin(ResidentialComplex, Developer.id == ResidentialComplex.developer_id)
                .outerjoin(Property, ResidentialComplex.id == Property.complex_id)
                .group_by(Developer.id)
                .order_by(func.count(distinct(Property.id)).desc())
                .all()
            )
        
        # Format response
        developers_data = []
        for developer, properties_count in developers_list:
            developers_data.append({
                'id': developer.id,
                'name': developer.name,
                'properties_count': int(properties_count) if properties_count else 0
            })
        
        return jsonify({'developers': developers_data})
        
    except Exception as e:
        current_app.logger.error(f"Error in /api/developers: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@bp.route('/api/check-it-company', methods=['POST'])
@csrf.exempt
def check_it_company():
    """Check if company is in IT companies list by INN or company name"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных для проверки'}), 400
            
        inn = data.get('inn', '').strip()
        company_name = data.get('company_name', '').strip()
        
        if not inn and not company_name:
            return jsonify({'error': 'Необходимо указать ИНН или название компании'}), 400
        
        # Поиск по ИНН
        if inn:
            try:
                inn_int = int(inn)
                company = db.session.execute(text("""
                    SELECT inn, name FROM it_companies 
                    WHERE inn = :inn LIMIT 1
                """), {'inn': inn_int}).fetchone()
                
                if company:
                    return jsonify({
                        'found': True,
                        'inn': company[0],
                        'company_name': company[1],
                        'message': 'Компания найдена в реестре ИТ-организаций'
                    })
            except ValueError:
                pass
        
        # Поиск по названию компании (частичное совпадение)
        if company_name:
            company = db.session.execute(text("""
                SELECT inn, name FROM it_companies 
                WHERE LOWER(name) LIKE LOWER(:company_name) 
                LIMIT 1
            """), {'company_name': f'%{company_name}%'}).fetchone()
            
            if company:
                return jsonify({
                    'found': True,
                    'inn': company[0],
                    'company_name': company[1],
                    'message': 'Компания найдена в реестре ИТ-организаций'
                })
        
        return jsonify({
            'found': False,
            'message': 'Компания не найдена в реестре ИТ-организаций. Проверьте правильность ИНН или названия компании.'
        })
        
    except Exception as e:
        print(f"Error checking IT company: {e}")
        return jsonify({'error': 'Ошибка при проверке компании'}), 500

@bp.route('/api/suggest-it-companies', methods=['POST'])
@csrf.exempt
def suggest_it_companies():
    """Get IT company suggestions for autocomplete"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip().lower()
        
        if len(query) < 2:
            return jsonify({'suggestions': []})
            
        # Search for companies matching the query
        suggestions = db.session.execute(text("""
            SELECT DISTINCT name FROM it_companies 
            WHERE LOWER(name) LIKE :query 
            ORDER BY name 
            LIMIT 10
        """), {'query': f'%{query}%'}).fetchall()
        
        return jsonify({
            'suggestions': [suggestion[0] for suggestion in suggestions]
        })
        
    except Exception as e:
        print(f"Error in suggest_it_companies: {str(e)}")
        return jsonify({'suggestions': []})

@bp.route('/api/detect-city', methods=['GET'])
@csrf.exempt
def detect_city():
    """Detect user's city by IP address and auto-set session['city_id']"""
    from models import City
    
    # Словарь для перевода транслита городов в русские названия
    city_translations = {
        'Krasnodar': 'Краснодар',
        'Moscow': 'Москва',
        'Saint Petersburg': 'Санкт-Петербург',
        'Novosibirsk': 'Новосибирск',
        'Yekaterinburg': 'Екатеринбург',
        'Nizhny Novgorod': 'Нижний Новгород',
        'Kazan': 'Казань',
        'Chelyabinsk': 'Челябинск',
        'Omsk': 'Омск',
        'Samara': 'Самара',
        'Rostov-on-Don': 'Ростов-на-Дону',
        'Ufa': 'Уфа',
        'Krasnoyarsk': 'Красноярск',
        'Voronezh': 'Воронеж',
        'Perm': 'Пермь',
        'Volgograd': 'Волгоград',
        'Saratov': 'Саратов',
        'Tyumen': 'Тюмень',
        'Tolyatti': 'Тольятти',
        'Izhevsk': 'Ижевск',
        'Barnaul': 'Барнаул',
        'Ulyanovsk': 'Ульяновск',
        'Irkutsk': 'Иркутск',
        'Khabarovsk': 'Хабаровск',
        'Yaroslavl': 'Ярославль',
        'Vladivostok': 'Владивосток',
        'Makhachkala': 'Махачкала',
        'Tomsk': 'Томск',
        'Orenburg': 'Оренбург',
        'Kemerovo': 'Кемерово',
        'Novokuznetsk': 'Новокузнецк',
        'Ryazan': 'Рязань',
        'Astrakhan': 'Астрахань',
        'Naberezhnye Chelny': 'Набережные Челны',
        'Penza': 'Пенза',
        'Lipetsk': 'Липецк',
        'Kirov': 'Киров',
        'Cheboksary': 'Чебоксары',
        'Kaliningrad': 'Калининград',
        'Tula': 'Тула',
        'Kursk': 'Курск',
        'Sochi': 'Сочи',
        'Stavropol': 'Ставрополь',
        'Ulan-Ude': 'Улан-Удэ',
        'Tver': 'Тверь',
        'Magnitogorsk': 'Магнитогорск',
        'Bryansk': 'Брянск',
        'Ivanovo': 'Иваново',
        'Belgorod': 'Белгород'
    }
    
    # Словарь для перевода регионов
    region_translations = {
        'Krasnodar Krai': 'Краснодарский край',
        'Krasnodar Territory': 'Краснодарский край',
        'Moscow': 'Москва',
        'Saint Petersburg': 'Санкт-Петербург',
        'Moscow Oblast': 'Московская область',
        'Sverdlovsk Oblast': 'Свердловская область',
        'Novosibirsk Oblast': 'Новосибирская область',
        'Rostov Oblast': 'Ростовская область',
        'Tatarstan': 'Республика Татарстан',
        'Bashkortostan': 'Республика Башкортостан',
        'Chelyabinsk Oblast': 'Челябинская область'
    }
    
    # Map of supported cities (in our database) to their Russian names
    supported_cities = {
        'Краснодар': 'krasnodar',
        'Сочи': 'sochi',
        'Анапа': 'anapa',
        'Геленджик': 'gelendzhik',
        'Новороссийск': 'novorossiysk',
        'Армавир': 'armavir',
        'Туапсе': 'tuapse',
        'Майкоп': 'maykop'
    }
    
    def _set_city_in_session(city_name):
        """Helper function to set city_id in session based on city name"""
        # Find city in database
        detected_city_slug = supported_cities.get(city_name)
        
        if detected_city_slug:
            # City is supported - find in database
            city_obj = City.query.filter_by(slug=detected_city_slug, is_active=True).first()
            if city_obj:
                session['city_id'] = city_obj.id
                print(f"✅ Auto-detected city: {city_obj.name} (ID: {city_obj.id})")
                return city_obj.id
        
        # If city not supported or not found, use default (Krasnodar)
        default_city = City.query.filter_by(slug='krasnodar', is_active=True).first()
        if default_city:
            session['city_id'] = default_city.id
            print(f"✅ Using default city: {default_city.name} (ID: {default_city.id})")
            return default_city.id
        
        return None
    
    try:
        # Get user's IP address from request
        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ',' in user_ip:
            user_ip = user_ip.split(',')[0].strip()
        
        # Skip localhost/private IPs
        if user_ip in ['127.0.0.1', 'localhost', '::1'] or user_ip.startswith('192.168.') or user_ip.startswith('10.'):
            city_name = 'Краснодар'
            city_id = _set_city_in_session(city_name)
            return jsonify({
                'success': True,
                'city': city_name,
                'region': 'Краснодарский край',
                'country': 'Россия',
                'detected': False,
                'city_id': city_id,
                'message': 'Локальный IP, используется город по умолчанию'
            })
        
        # Use ipwhois.io API (free, no API key required, 10,000 requests/month)
        api_url = f'http://ipwho.is/{user_ip}'
        response = _requests.get(api_url, timeout=3)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('success', False):
                city_en = data.get('city', 'Krasnodar')
                region_en = data.get('region', 'Krasnodar Krai')
                
                # Переводим город и регион на русский
                city = city_translations.get(city_en, city_en if not city_en else 'Краснодар')
                region = region_translations.get(region_en, region_en if not region_en else 'Краснодарский край')
                
                # Set city in session
                city_id = _set_city_in_session(city)
                
                return jsonify({
                    'success': True,
                    'city': city,
                    'region': region,
                    'country': 'Россия',
                    'detected': True if supported_cities.get(city) else False,
                    'city_id': city_id,
                    'ip': user_ip
                })
        
        # Fallback to default city
        city_name = 'Краснодар'
        city_id = _set_city_in_session(city_name)
        return jsonify({
            'success': True,
            'city': city_name,
            'region': 'Краснодарский край',
            'country': 'Россия',
            'detected': False,
            'city_id': city_id,
            'message': 'Не удалось определить город, используется город по умолчанию'
        })
        
    except Exception as e:
        print(f"Error detecting city: {e}")
        # Make sure to set default city on error too
        city_name = 'Краснодар'
        city_id = _set_city_in_session(city_name)
        return jsonify({
            'success': True,
            'city': city_name,
            'region': 'Краснодарский край',
            'country': 'Россия',
            'detected': False,
            'city_id': city_id,
            'error': str(e)
        })


# =============================================================================
# Geocoding API Endpoints
# =============================================================================

@bp.route('/api/geocode/autocomplete', methods=['GET'])
@csrf.exempt
def geocode_autocomplete():
    """
    Address autocomplete API endpoint
    Returns address suggestions as user types
    """
    query = request.args.get('query', '').strip()
    
    if not query or len(query) < 2:
        return jsonify({'suggestions': []})
    
    # Optional geolocation bias to Krasnodar
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    
    # Default to Krasnodar center if no coordinates provided
    if not lat or not lon:
        lat = 45.0355  # Krasnodar center
        lon = 38.9753
    
    try:
        geocoding_service = _get_geocoding_service()
        suggestions = geocoding_service.autocomplete(
            query=query,
            latitude=lat,
            longitude=lon,
            results=7
        )
        
        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'count': len(suggestions)
        })
        
    except Exception as e:
        current_app.logger.error(f"Autocomplete error: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'suggestions': []
        }), 500


@bp.route('/api/geocode/reverse', methods=['GET'])
@csrf.exempt
def geocode_reverse():
    """
    Reverse geocoding API endpoint
    Convert coordinates to address components
    """
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    
    if not lat or not lon:
        return jsonify({
            'success': False,
            'error': 'Latitude and longitude are required'
        }), 400
    
    try:
        geocoding_service = _get_geocoding_service()
        result = geocoding_service.enrich_property_address(lat, lon)
        
        if result:
            return jsonify({
                'success': True,
                'address': result
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Address not found'
            }), 404
            
    except Exception as e:
        current_app.logger.error(f"Reverse geocoding error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/geocode/forward', methods=['GET'])
@csrf.exempt
def geocode_forward():
    """
    Forward geocoding API endpoint
    Convert address to coordinates
    """
    address = request.args.get('address', '').strip()
    
    if not address:
        return jsonify({
            'success': False,
            'error': 'Address is required'
        }), 400
    
    try:
        geocoding_service = _get_geocoding_service()
        result = geocoding_service.forward_geocode(address)
        
        if result:
            return jsonify({
                'success': True,
                'result': result
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Coordinates not found'
            }), 404
            
    except Exception as e:
        current_app.logger.error(f"Forward geocoding error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500



@bp.route('/api/geocode/enrich-properties', methods=['POST'])
@login_required
def enrich_properties():
    """
    Admin endpoint to batch-enrich properties with parsed address components
    Updates properties that have coordinates but missing parsed address fields
    """
    # Only allow for admin users (you can add role check here)
    # if not current_user.is_admin:
    #     return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    limit = request.args.get('limit', type=int, default=50)
    
    try:
        from models import Property
        geocoding_service = _get_geocoding_service()
        
        # Find properties with coordinates but missing parsed address data
        properties = Property.query.filter(
            Property.latitude.isnot(None),
            Property.longitude.isnot(None),
            (Property.parsed_city.is_(None) | Property.parsed_district.is_(None))
        ).limit(limit).all()
        
        updated_count = 0
        errors = []
        
        for prop in properties:
            try:
                enriched = geocoding_service.enrich_property_address(
                    prop.latitude, 
                    prop.longitude
                )
                
                if enriched:
                    prop.parsed_city = enriched.get('parsed_city', '')
                    prop.parsed_district = enriched.get('parsed_district', '')
                    prop.parsed_street = enriched.get('parsed_street', '')
                    
                    # Update full address if missing
                    if not prop.address:
                        prop.address = enriched.get('full_address', '')
                    
                    updated_count += 1
                    
            except Exception as e:
                errors.append(f"Property {prop.id}: {str(e)}")
                current_app.logger.error(f"Error enriching property {prop.id}: {e}")
        
        db.session.commit()
        
        # Get service stats
        stats = geocoding_service.get_stats()
        
        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'total_checked': len(properties),
            'errors': errors,
            'geocoding_stats': stats
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Batch enrichment error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/geocode/stats', methods=['GET'])
def geocode_stats():
    """Get geocoding service statistics"""
    try:
        geocoding_service = _get_geocoding_service()
        stats = geocoding_service.get_stats()
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500



@bp.route('/api/search')
def api_search():
    """API endpoint for global search"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    
    results = search_global(query)
    return jsonify(results)

@bp.route('/search')
def search_results():
    """Search results page"""
    query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'all')  # all, residential_complex, district, developer, street
    
    results = []
    if query:
        results = search_global(query)
        
        # Filter by type if specified
        if search_type != 'all':
            results = [r for r in results if r['type'] == search_type]
    
    return render_template('search_results.html', 
                         query=query, 
                         results=results,
                         search_type=search_type)


@bp.route('/api/smart-search-suggestions')
def smart_search_suggestions():
    """API endpoint for search suggestions with intelligent keyword matching"""
    query = request.args.get('q', '').strip().lower()
    if not query or len(query) < 1:
        return jsonify({'suggestions': []})
    
    suggestions = []
    
    try:
        # Intelligent room type matching patterns
        room_patterns = {
            # Single room patterns
            ('1', '1-', '1-к', '1-ко', '1-ком', '1 к', '1 ко', '1 ком', 'одн', 'одно', 'однок', 'однокомн', 'однокомнат', 'однокомнатн', 'один', 'одной'): ('1-комнатная квартира', 'rooms', '1'),
            # Two room patterns  
            ('2', '2-', '2-к', '2-ко', '2-ком', '2 к', '2 ко', '2 ком', 'двух', 'двухк', 'двухком', 'двухкомн', 'двухкомнат', 'два', 'двой', 'двойн'): ('2-комнатная квартира', 'rooms', '2'),
            # Three room patterns
            ('3', '3-', '3-к', '3-ко', '3-ком', '3 к', '3 ко', '3 ком', 'трех', 'трёх', 'трехк', 'трёхк', 'трехком', 'трёхком', 'три', 'трой'): ('3-комнатная квартира', 'rooms', '3'),
            # Four room patterns
            ('4', '4-', '4-к', '4-ко', '4-ком', '4 к', '4 ко', '4 ком', 'четыр', 'четырех', 'четырёх', 'четырехк', 'четырёхк', 'четыре'): ('4-комнатная квартира', 'rooms', '4'),
            # Studio patterns
            ('студ', 'studio', 'студий', 'студия'): ('Студия', 'rooms', 'studio'),
        }
        
        # Check room type patterns first
        for patterns, (room_text, type_val, value) in room_patterns.items():
            for pattern in patterns:
                if query.startswith(pattern) or pattern in query:
                    suggestions.append({
                        'text': room_text,
                        'type': type_val,
                        'value': value,
                        'category': 'Тип квартиры'
                    })
                    break
        
        # Search in regional data first (regions and cities)
        from models import Region, City
        
        # Search regions
        regions = Region.query.filter(Region.name.ilike(f'%{query}%')).limit(5).all()
        for region in regions:
            suggestions.append({
                'text': region.name,
                'type': 'region',
                'value': region.slug,
                'category': 'Регион'
            })
        
        # Search cities
        cities = City.query.filter(City.name.ilike(f'%{query}%')).limit(5).all()
        for city in cities:
            suggestions.append({
                'text': f"{city.name} ({city.region.name if city.region else 'Неизвестный регион'})",
                'type': 'city',
                'value': city.slug,
                'category': 'Город'
            })

        # Search in database categories (districts, developers, complexes)
        cursor = db.session.execute(text("""
            SELECT name, category_type, slug 
            FROM search_categories 
            WHERE LOWER(name) LIKE :query 
            ORDER BY 
                CASE 
                    WHEN LOWER(name) LIKE :exact_start THEN 1
                    WHEN LOWER(name) LIKE :word_start THEN 2
                    ELSE 3
                END,
                LENGTH(name)
            LIMIT 10
        """), {
            'query': f'%{query}%',
            'exact_start': f'{query}%',
            'word_start': f'% {query}%'
        })
        
        category_names = {
            'district': 'Район',
            'developer': 'Застройщик', 
            'complex': 'ЖК',
            'rooms': 'Тип квартиры',
            'region': 'Регион',
            'city': 'Город'
        }
        
        for row in cursor:
            name, category_type, slug = row
            suggestions.append({
                'text': name,
                'type': category_type,
                'value': slug,
                'category': category_names.get(category_type, category_type.title())
            })
        
        # Remove duplicates while preserving order
        seen = set()
        unique_suggestions = []
        for s in suggestions:
            key = (s['text'], s['type'])
            if key not in seen:
                seen.add(key)
                unique_suggestions.append(s)
        
        return jsonify({'suggestions': unique_suggestions[:12]})
        
    except Exception as e:
        current_app.logger.error(f"Smart search error: {e}")
        return jsonify({'suggestions': []})

def init_search_data():
    """Initialize search data in database"""
    from models import District, Developer, ResidentialComplex, Street, RoomType
    
    # Districts
    districts_data = [
        ('Центральный', 'tsentralnyy'), ('Западный', 'zapadny'), 
        ('Карасунский', 'karasunsky'), ('Прикубанский', 'prikubansky'),
        ('Фестивальный', 'festivalny'), ('Юбилейный', 'yubileynyy'),
        ('Гидростроителей', 'gidrostroitelei'), ('Солнечный', 'solnechny'),
        ('Панорама', 'panorama'), ('Музыкальный', 'muzykalnyy')
    ]
    
    for name, slug in districts_data:
        if not District.query.filter_by(slug=slug).first():
            district = District(name=name, slug=slug)
            db.session.add(district)
    
    # Room types
    room_types_data = [
        ('Студия', 0), ('1-комнатная квартира', 1), 
        ('2-комнатная квартира', 2), ('3-комнатная квартира', 3), 
        ('4-комнатная квартира', 4), ('Пентхаус', 5)
    ]
    
    for name, rooms_count in room_types_data:
        if not RoomType.query.filter_by(name=name).first():
            room_type = RoomType(name=name, rooms_count=rooms_count)
            db.session.add(room_type)
    
    # Developers
    developers_data = [
        ('Краснодар Инвест', 'krasnodar-invest'),
        ('ЮгСтройИнвест', 'yugstroyinvest'),
        ('Флагман', 'flagman'),
        ('Солнечный город', 'solnechny-gorod'),
        ('Премьер', 'premier')
    ]
    
    for name, slug in developers_data:
        if not Developer.query.filter_by(slug=slug).first():
            developer = Developer(name=name, slug=slug)
            db.session.add(developer)
    
    # Residential complexes
    complexes_data = [
        ('Солнечный', 'solnechny', 1, 1),
        ('Панорама', 'panorama', 1, 2),
        ('Гармония', 'garmoniya', 2, 3),
        ('Европейский квартал', 'evropeyskiy-kvartal', 3, 1),
        ('Флагман', 'flagman', 4, 4)
    ]
    
    for name, slug, district_id, developer_id in complexes_data:
        if not ResidentialComplex.query.filter_by(slug=slug).first():
            complex = ResidentialComplex(name=name, slug=slug, district_id=district_id, developer_id=developer_id)
            db.session.add(complex)
    
    db.session.commit()


# ─── CIAN Image Proxy ─────────────────────────────────────────────────────────
from flask import Response, stream_with_context, abort as _abort
from urllib.parse import urlparse as _urlparse

# ── Image cache: memory (hot) + disk (persistent across restarts) ────────
import os as _os
import hashlib as _hashlib
import threading as _threading

_IMG_CACHE: dict = {}          # memory: cache_key → (content_type, bytes)
_IMG_CACHE_MAX = 2000          # max items in memory
_IMG_DISK_DIR  = '/tmp/inback_img_cache'
_IMG_FETCHING: set = set()     # keys currently being fetched in background
_os.makedirs(_IMG_DISK_DIR, exist_ok=True)

# ── Счётчики статистики прокси (сбрасываются при рестарте) ───────────────
_PROXY_STATS: dict = {
    'total': 0,       # все запросы к /api/img-proxy
    'mem_hits': 0,    # отдано из памяти
    'disk_hits': 0,   # отдано с диска
    'redirects': 0,   # редирект → ЦИАН (кэш-мисс)
}
import threading as _stats_lock_mod
_PROXY_STATS_LOCK = _stats_lock_mod.Lock()


def _img_disk_path(cache_key: str) -> str:
    h = _hashlib.sha256(cache_key.encode()).hexdigest()
    return _os.path.join(_IMG_DISK_DIR, h[:2], h + '.bin')


def _img_disk_read(cache_key: str):
    """Return (content_type, bytes) from disk or None."""
    path = _img_disk_path(cache_key)
    try:
        with open(path, 'rb') as f:
            ct_len = int.from_bytes(f.read(2), 'big')
            ct = f.read(ct_len).decode()
            data = f.read()
        return ct, data
    except Exception:
        return None


_IMG_DISK_WRITE_COUNTER = 0
_IMG_DISK_MAX_MB = 500  # Максимальный размер дискового кэша в МБ


def _img_disk_cleanup():
    """Delete oldest cache files if total size exceeds _IMG_DISK_MAX_MB."""
    try:
        all_files = []
        for root, _, files in _os.walk(_IMG_DISK_DIR):
            for fn in files:
                fp = _os.path.join(root, fn)
                try:
                    st = _os.stat(fp)
                    all_files.append((st.st_mtime, st.st_size, fp))
                except OSError:
                    pass
        total_bytes = sum(s for _, s, _ in all_files)
        max_bytes = _IMG_DISK_MAX_MB * 1024 * 1024
        if total_bytes <= max_bytes:
            return
        # Sort oldest first, delete until under limit
        all_files.sort()
        for mtime, size, fp in all_files:
            if total_bytes <= max_bytes * 0.8:  # Clean to 80% of limit
                break
            try:
                _os.remove(fp)
                total_bytes -= size
            except OSError:
                pass
        logger.info(f'🧹 Disk cache cleanup done; remaining ~{total_bytes // (1024*1024)} MB')
    except Exception as e:
        logger.debug(f'Disk cache cleanup error: {e}')


def _img_disk_write(cache_key: str, content_type: str, data: bytes):
    global _IMG_DISK_WRITE_COUNTER
    path = _img_disk_path(cache_key)
    try:
        _os.makedirs(_os.path.dirname(path), exist_ok=True)
        ct_b = content_type.encode()
        with open(path, 'wb') as f:
            f.write(len(ct_b).to_bytes(2, 'big'))
            f.write(ct_b)
            f.write(data)
        _IMG_DISK_WRITE_COUNTER += 1
        if _IMG_DISK_WRITE_COUNTER % 200 == 0:
            import threading as _thr
            _thr.Thread(target=_img_disk_cleanup, daemon=True).start()
    except Exception:
        pass


def _img_mem_put(cache_key: str, content_type: str, data: bytes):
    if len(_IMG_CACHE) >= _IMG_CACHE_MAX:
        oldest = next(iter(_IMG_CACHE))
        del _IMG_CACHE[oldest]
    _IMG_CACHE[cache_key] = (content_type, data)


def _img_fetch_and_cache(url: str, cache_key: str):
    """Background thread: fetch from CIAN, store in disk + memory."""
    import requests as _req
    try:
        r = _req.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://cian.ru/',
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
        }, timeout=15, verify=False)
        if r.status_code == 200:
            ct = r.headers.get('Content-Type', 'image/jpeg')
            data = r.content
            _img_disk_write(cache_key, ct, data)
            _img_mem_put(cache_key, ct, data)
    except Exception as e:
        logger.debug(f'bg img fetch failed for {url[:60]}: {e}')
    finally:
        _IMG_FETCHING.discard(cache_key)


_IMG_RESP_HEADERS = {
    'Cache-Control': 'public, max-age=604800',
    'X-Content-Type-Options': 'nosniff',
}


@bp.route('/api/img-proxy')
def img_proxy():
    """Proxy CIAN images. Token hides origin URL from HTML source.

    Strategy (fastest first):
      1. Memory cache  → serve instantly (~0ms)
      2. Disk cache    → serve from /tmp (~5ms), warm memory
      3. Not cached    → return 302 redirect to CIAN (browser fetches directly,
                         ~instant for Russian users) and kick off background
                         fetch to populate disk+memory for next request.
    CIAN URL is NEVER in HTML source — only the opaque /api/img-proxy?t=… token.
    """
    import base64 as _b64

    token = request.args.get('t', '').strip()
    url   = request.args.get('u', '').strip()
    cache_key = token or url

    # ── Decode token → real URL ───────────────────────────────────────────
    if token:
        try:
            pad = 4 - len(token) % 4
            if pad != 4:
                token += '=' * pad
            path = _b64.urlsafe_b64decode(token).decode('utf-8')
            url = f'https://images.cdn-cian.ru/{path}'
        except Exception:
            _abort(400)
    elif url:
        parsed = _urlparse(url)
        hostname = parsed.hostname or ''
        allowed = ('cian.ru', 'cdn-cian.ru', 'images.cdn-cian.ru',
                   'nashdom.ru', 'domclick.ru', 's3.amazonaws.com')
        if not any(hostname.endswith(d) for d in allowed):
            _abort(403)
    else:
        _abort(400)

    # ── Счётчик (total) ───────────────────────────────────────────────────
    with _PROXY_STATS_LOCK:
        _PROXY_STATS['total'] += 1

    # ── 1. Memory cache ───────────────────────────────────────────────────
    if cache_key in _IMG_CACHE:
        ct, data = _IMG_CACHE[cache_key]
        with _PROXY_STATS_LOCK:
            _PROXY_STATS['mem_hits'] += 1
        return Response(data, content_type=ct,
                        headers={**_IMG_RESP_HEADERS, 'X-Cache': 'MEM'})

    # ── 2. Disk cache ─────────────────────────────────────────────────────
    disk = _img_disk_read(cache_key)
    if disk:
        ct, data = disk
        _img_mem_put(cache_key, ct, data)  # warm memory
        with _PROXY_STATS_LOCK:
            _PROXY_STATS['disk_hits'] += 1
        return Response(data, content_type=ct,
                        headers={**_IMG_RESP_HEADERS, 'X-Cache': 'DISK'})

    # ── 3. Cache miss: redirect browser to CIAN directly (instant for RU
    #       users), and fetch+cache in background for next request ──────────
    with _PROXY_STATS_LOCK:
        _PROXY_STATS['redirects'] += 1
    if cache_key not in _IMG_FETCHING:
        _IMG_FETCHING.add(cache_key)
        t = _threading.Thread(target=_img_fetch_and_cache,
                              args=(url, cache_key), daemon=True)
        t.start()

    # Redirect — browser loads image directly from CIAN CDN at full speed.
    # 'no-referrer' prevents CIAN from seeing our domain as the referrer.
    return Response('', status=302, headers={
        'Location': url,
        'Referrer-Policy': 'no-referrer',
        'Cache-Control': 'no-store',
        'X-Cache': 'REDIRECT',
    })

