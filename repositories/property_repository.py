"""
Property Repository - Professional data access layer
Чистая работа с normalized таблицами: Developer → ResidentialComplex → Property
"""

import json
import hashlib
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload
from models import Property, ResidentialComplex, Developer, District
from app import db, cache


def _parse_geometry_bbox(geometry_str, buffer=0.008):
    """Parse district geometry polygon string → bounding box with buffer.
    
    geometry format: 'lat,lng;lat,lng;...'
    buffer: degrees of padding (~800m default) to avoid edge exclusions.
    Returns (min_lat, max_lat, min_lng, max_lng) or None.
    """
    if not geometry_str:
        return None
    try:
        pts = [p.split(',') for p in geometry_str.split(';') if ',' in p]
        if len(pts) < 3:
            return None
        lats = [float(p[0]) for p in pts]
        lngs = [float(p[1]) for p in pts]
        return (min(lats) - buffer, max(lats) + buffer,
                min(lngs) - buffer, max(lngs) + buffer)
    except Exception:
        return None


def _build_district_geo_condition(district):
    """Build SQLAlchemy filter condition for a single District object.

    For okrug-type districts: match by district_id OR by the RC's okrug_district_id
    (populated via PIP). This captures all properties in the okrug regardless of
    whether they're assigned to a sub-microrayon.
    For microrayon/settlement/micro districts: match by district_id FK only.
    """
    if district.district_type == 'okrug':
        return or_(
            Property.district_id == district.id,
            ResidentialComplex.okrug_district_id == district.id,
        )
    return Property.district_id == district.id


class PropertyRepository:
    """Repository для работы с квартирами через normalized структуру"""
    
    # Mapping для renovation_type → человекочитаемое название
    RENOVATION_DISPLAY_NAMES = {
        'no_renovation': 'Без отделки',
        'fine_finish': 'Чистовая',
        'rough_finish': 'Черновая',
        'pre_finish': 'Предчистовая',
        'turnkey': 'Под ключ',
        'with_renovation': 'С отделкой',
        'design_repair': 'Дизайнерский ремонт',
        # Прямые русские значения (хранятся в БД)
        'Чистовая': 'Чистовая',
        'Черновая': 'Черновая',
        'Без отделки': 'Без отделки',
        'Предчистовая': 'Предчистовая',
        'Под ключ': 'Под ключ',
        'С отделкой': 'С отделкой',
        'Дизайнерский ремонт': 'Дизайнерский ремонт',
        None: 'Без отделки'
    }

    # Маппинг фронтенд-кодов → значения в БД (renovation_type хранится как кириллица)
    RENOVATION_CODE_TO_DB = {
        'no_renovation': ['Без отделки'],
        'fine_finish': ['Чистовая'],
        'rough_finish': ['Черновая'],
        'pre_finish': ['Предчистовая'],
        'turnkey': ['Под ключ'],
        'with_renovation': ['С отделкой', 'Чистовая', 'Под ключ'],
        'design_repair': ['Дизайнерский ремонт'],
    }

    @staticmethod
    def _resolve_renovation_db_values(renovation_codes):
        """Конвертирует фронтенд-коды отделки в значения, хранящиеся в БД.
        Если значение уже кириллическое — передаётся как есть."""
        db_values = []
        for code in renovation_codes:
            mapped = PropertyRepository.RENOVATION_CODE_TO_DB.get(code)
            if mapped:
                db_values.extend(mapped)
            else:
                db_values.append(code)
        return list(set(db_values))
    
    @staticmethod
    def _make_cache_key_for_filters(filters=None):
        """Create cache key from filters dict for memoization"""
        if not filters:
            return 'count_active_no_filters'
        filter_str = json.dumps(filters, sort_keys=True, default=str)
        filter_hash = hashlib.md5(filter_str.encode()).hexdigest()
        return f'count_active_{filter_hash}'
    
    @staticmethod
    def _make_stats_cache_key(city_id=None):
        """Create cache key for property stats"""
        if city_id:
            return f'property_stats_city_{city_id}'
        return 'property_stats_all'
    
    @staticmethod
    def get_renovation_display_name(renovation_type):
        """Преобразовать renovation_type в человекочитаемое название"""
        return PropertyRepository.RENOVATION_DISPLAY_NAMES.get(renovation_type, 'Без отделки')
    
    @staticmethod
    def get_base_query():
        """
        Базовый query с JOIN всех связанных таблиц
        Использовать во всех запросах для consistency
        """
        return (
            db.session.query(Property)
            .join(ResidentialComplex, Property.complex_id == ResidentialComplex.id, isouter=True)
            .join(Developer, Property.developer_id == Developer.id, isouter=True)
            .join(District, Property.district_id == District.id, isouter=True)
            .options(
                joinedload(Property.residential_complex),
                joinedload(Property.developer),
                joinedload(Property.district)
            )
        )
    
    @staticmethod
    def get_all_active(limit=50, offset=0, filters=None, sort_by='price', sort_order='asc'):
        """
        Получить все активные квартиры с фильтрами - ПОЛНАЯ ПОДДЕРЖКА build_property_filters()
        
        Args:
            limit: Лимит записей
            offset: Смещение для пагинации
            filters: Dict с фильтрами {
                # Price and area
                'min_price': int, 'max_price': int,
                'min_area': float, 'max_area': float,
                
                # Rooms
                'rooms': list[int],
                
                # Floor filters
                'floor_min': int, 'floor_max': int,
                'floor_options': list[str],  # ['not_first', 'not_last']
                
                # Relations
                'complex_id': int,
                'developer_id': int,
                'developer': str,  # by name
                'developers': list[str],  # multiple developers by name
                'district': str,  # by name
                'districts': list[str],  # multiple districts by name
                'residential_complex': str,  # by name
                'building': str,  # building name
                
                # Building characteristics
                'building_types': list[str],
                'building_floors_min': int,
                'building_floors_max': int,
                
                # Completion dates
                'build_year_min': int,
                'build_year_max': int,
                'delivery_years': list[int],
                
                # Features
                'cashback_only': bool,
                'renovation': list[str],
                'object_classes': list[str],
                
                # Other
                'deal_type': str,
                'search': str  # search query
            }
            sort_by: str - Поле для сортировки ('price', 'area', 'date')
            sort_order: str - Порядок ('asc', 'desc')
        
        Returns:
            List[Property]: Список квартир с подгруженными связями
        """
        query = PropertyRepository.get_base_query()
        query = query.filter(Property.is_active == True)
        
        if filters:
            # Price filters
            if filters.get('min_price'):
                query = query.filter(Property.price >= filters['min_price'])
            if filters.get('max_price'):
                query = query.filter(Property.price <= filters['max_price'])
            # Price per sqm filters
            if filters.get('min_price_sqm'):
                query = query.filter(Property.price_per_sqm >= filters['min_price_sqm'])
            if filters.get('max_price_sqm'):
                query = query.filter(Property.price_per_sqm <= filters['max_price_sqm'])
            
            # Area filters
            if filters.get('min_area'):
                query = query.filter(Property.area >= filters['min_area'])
            if filters.get('max_area'):
                query = query.filter(Property.area <= filters['max_area'])
            
            # Rooms filter
            if filters.get('rooms'):
                # Handle both int and string room values
                room_values = []
                for r in filters['rooms']:
                    try:
                        room_values.append(int(r))
                    except (ValueError, TypeError):
                        pass
                if room_values:
                    query = query.filter(Property.rooms.in_(room_values))
            
            # Floor filters
            if filters.get('floor_min'):
                query = query.filter(Property.floor >= filters['floor_min'])
            if filters.get('floor_max'):
                query = query.filter(Property.floor <= filters['floor_max'])
            
            # Floor options (not first/not last)
            if filters.get('floor_options'):
                for option in filters['floor_options']:
                    if option == 'not_first':
                        query = query.filter(Property.floor > 1)
                    elif option == 'not_last':
                        # Not on last floor: floor < total_floors
                        query = query.filter(Property.floor < Property.total_floors)
            
            # Complex filters
            if filters.get('complex_id'):
                query = query.filter(Property.complex_id == filters['complex_id'])

            if filters.get('complex_ids'):
                _cids = [int(c) for c in filters['complex_ids'] if str(c).isdigit() or isinstance(c, int)]
                if _cids:
                    query = query.filter(Property.complex_id.in_(_cids))
            
            if filters.get('residential_complex'):
                query = query.filter(ResidentialComplex.name == filters['residential_complex'])
            
            # Developer filters
            if filters.get('developer_id'):
                query = query.filter(Property.developer_id == filters['developer_id'])
            
            if filters.get('developer'):
                dev_val = filters['developer']
                query = query.filter(or_(Developer.name == dev_val, Developer.slug == dev_val))
            
            if filters.get('developers'):
                # Filter by developer IDs or names
                developer_ids = []
                developer_names = []
                developer_slugs = []
                for dev_value in filters['developers']:
                    if isinstance(dev_value, str) and dev_value.strip():
                        # Check if it's numeric ID or text name/slug
                        if dev_value.strip().isdigit():
                            developer_ids.append(int(dev_value.strip()))
                        else:
                            developer_names.append(dev_value.strip())
                            developer_slugs.append(dev_value.strip())
                    elif isinstance(dev_value, int):
                        developer_ids.append(dev_value)
                
                # Apply filters — match by ID, name, or slug
                conditions = []
                if developer_ids:
                    conditions.append(Property.developer_id.in_(developer_ids))
                if developer_names:
                    conditions.append(Developer.name.in_(developer_names))
                if developer_slugs:
                    conditions.append(Developer.slug.in_(developer_slugs))
                
                if conditions:
                    query = query.filter(or_(*conditions))
            
            # City filtering
            if filters.get('city_id'):
                query = query.filter(Property.city_id == filters['city_id'])
            
            # District FK filter — precise, uses index (preferred when district_id is set)
            if filters.get('district_id'):
                _did = filters['district_id']
                district_name_fb = filters.get('district', '')
                if district_name_fb:
                    # FK-linked rows + LIKE fallback for rows still missing district_id
                    query = query.filter(
                        or_(
                            Property.district_id == _did,
                            and_(
                                Property.district_id == None,
                                or_(
                                    and_(District.name.isnot(None), District.name.ilike(f'%{district_name_fb}%')),
                                    and_(Property.parsed_district.isnot(None), Property.parsed_district.ilike(f'%{district_name_fb}%'))
                                )
                            )
                        )
                    )
                else:
                    query = query.filter(Property.district_id == _did)

            # District name filters — LIKE fallback (used when no district_id resolved)
            elif filters.get('district'):
                district_name = filters['district'].strip() if filters['district'] else ''
                # Ignore empty district names to prevent matching everything
                if district_name:
                    query = query.filter(
                        or_(
                            and_(District.name.isnot(None), District.name.ilike(f'%{district_name}%')),
                            and_(Property.parsed_district.isnot(None), Property.parsed_district.ilike(f'%{district_name}%')),
                            and_(Property.parsed_settlement.isnot(None), Property.parsed_settlement.ilike(f'%{district_name}%')),
                            and_(Property.parsed_area.isnot(None), Property.parsed_area.ilike(f'%{district_name}%')),
                            and_(ResidentialComplex.address_city_district.isnot(None), ResidentialComplex.address_city_district.ilike(f'%{district_name}%')),
                            and_(ResidentialComplex.address_quarter.isnot(None), ResidentialComplex.address_quarter.ilike(f'%{district_name}%'))
                        )
                    )
            
            # district_id_in — FK-based multi-district filter (preferred, precise)
            if filters.get('district_id_in'):
                _dids = [int(d) for d in filters['district_id_in'] if str(d).isdigit() or isinstance(d, int)]
                if _dids:
                    # For okrug districts also match via okrug_district_id on RC
                    try:
                        from models import District as _District
                        _okrug_ids = [d.id for d in _District.query.filter(
                            _District.id.in_(_dids), _District.district_type == 'okrug'
                        ).all()]
                        _micro_ids = [d for d in _dids if d not in _okrug_ids]
                        _conds_did = []
                        if _micro_ids:
                            _conds_did.append(Property.district_id.in_(_micro_ids))
                        if _okrug_ids:
                            _conds_did.append(Property.district_id.in_(_okrug_ids))
                            _conds_did.append(ResidentialComplex.okrug_district_id.in_(_okrug_ids))
                        if _conds_did:
                            query = query.filter(or_(*_conds_did))
                    except Exception:
                        query = query.filter(Property.district_id.in_(_dids))
            elif filters.get('districts'):
                # Resolve slugs → District objects with geometry, build geo-precise conditions.
                # _build_district_geo_condition() priority:
                #   1. For okrugs: district_id OR okrug_district_id (RC PIP)
                #   2. For microrayons: district_id FK
                _slugs = [s.strip() for s in filters['districts'] if s and str(s).strip()]
                district_conditions = []
                _unresolved = []
                if _slugs:
                    try:
                        _slug_rows = District.query.filter(District.slug.in_(_slugs)).all()
                        _matched_slugs = {d.slug for d in _slug_rows}
                        _unresolved = [s for s in _slugs if s not in _matched_slugs]
                        for _d in _slug_rows:
                            cond = _build_district_geo_condition(_d)
                            if cond is not None:
                                district_conditions.append(cond)
                    except Exception:
                        _unresolved = _slugs

                for district_name in _unresolved:
                    district_conditions.append(
                        or_(
                            and_(Property.parsed_district.isnot(None), Property.parsed_district.ilike(f'%{district_name}%')),
                            and_(Property.address.isnot(None), Property.address.ilike(f'%{district_name}%')),
                            and_(ResidentialComplex.address_city_district.isnot(None), ResidentialComplex.address_city_district.ilike(f'%{district_name}%')),
                            and_(ResidentialComplex.address_quarter.isnot(None), ResidentialComplex.address_quarter.ilike(f'%{district_name}%'))
                        )
                    )
                if district_conditions:
                    query = query.filter(or_(*district_conditions))
            
            # Building name filter
            if filters.get('building'):
                query = query.filter(Property.complex_building_name == filters['building'])
            
            # Building floors range
            if filters.get('building_floors_min'):
                query = query.filter(Property.total_floors >= filters['building_floors_min'])
            if filters.get('building_floors_max'):
                query = query.filter(Property.total_floors <= filters['building_floors_max'])
            
            # Building types filter (if we had building_type field)
            if filters.get('building_types'):
                query = query.filter(Property.building_type.in_(filters['building_types']))
            
            # Delivery/completion years (через ResidentialComplex.end_build_year)
            if filters.get('build_year_min'):
                query = query.filter(ResidentialComplex.end_build_year >= filters['build_year_min'])
            if filters.get('build_year_max'):
                query = query.filter(ResidentialComplex.end_build_year <= filters['build_year_max'])
            if filters.get('delivery_years'):
                # Filter by list of years
                query = query.filter(ResidentialComplex.end_build_year.in_(filters['delivery_years']))
            if filters.get('completion'):
                # API sends 'completion' key (from frontend), count_active already handles this
                completion_years = []
                for year_str in filters['completion']:
                    try:
                        completion_years.append(int(year_str))
                    except (ValueError, TypeError):
                        pass
                if completion_years:
                    query = query.filter(ResidentialComplex.end_build_year.in_(completion_years))
            
            # Cashback filter
            if filters.get('cashback_only'):
                query = query.filter(ResidentialComplex.cashback_rate > 0)
            
            # Renovation types (коды с фронтенда → кириллические значения в БД)
            if filters.get('renovation'):
                db_renovation = PropertyRepository._resolve_renovation_db_values(filters['renovation'])
                if db_renovation:
                    query = query.filter(Property.renovation_type.in_(db_renovation))
            
            # Object classes (через ResidentialComplex.object_class_display_name)
            if filters.get('object_classes'):
                query = query.filter(ResidentialComplex.object_class_display_name.in_(filters['object_classes']))
            
            # Building released filter (сданный/строительство)
            if filters.get('building_released'):
                from datetime import datetime
                current_year = datetime.now().year
                
                # Build conditions for each status
                release_conditions = []
                for status in filters['building_released']:
                    # Support both true/false (from HTML checkboxes) and Russian strings
                    if status in ['true', 'True', 'сданный']:
                        # Already completed: end_build_year <= current_year
                        release_conditions.append(ResidentialComplex.end_build_year <= current_year)
                    elif status in ['false', 'False', 'в строительстве']:
                        # Under construction: end_build_year > current_year
                        release_conditions.append(ResidentialComplex.end_build_year > current_year)
                
                # Apply OR condition if multiple statuses selected
                if release_conditions:
                    query = query.filter(or_(*release_conditions))
            
            # Deal type
            if filters.get('deal_type'):
                query = query.filter(Property.deal_type == filters['deal_type'])
            
            # Property type (apartments/houses/townhouses/penthouses/apartments_commercial)
            if filters.get('property_type') and filters['property_type'] != 'all':
                query = query.filter(Property.property_type == filters['property_type'])

            # Санузел (bathroom_type)
            if filters.get('bathroom_type'):
                bathroom_conditions = []
                for bt in filters['bathroom_type']:
                    if bt == 'combined':
                        bathroom_conditions.append(Property.bathroom_type.ilike('%совмещ%'))
                    elif bt == 'separate':
                        bathroom_conditions.append(Property.bathroom_type.ilike('%раздельн%'))
                if bathroom_conditions:
                    query = query.filter(or_(*bathroom_conditions))

            # Балкон / лоджия
            if filters.get('has_balcony'):
                if 'true' in filters['has_balcony'] or True in filters['has_balcony']:
                    query = query.filter(Property.has_balcony == True)

            # Высота потолков (мин)
            if filters.get('ceiling_height_min'):
                query = query.filter(Property.ceiling_height >= filters['ceiling_height_min'])

            # Площадь кухни
            if filters.get('kitchen_area_min'):
                query = query.filter(Property.kitchen_area >= filters['kitchen_area_min'])
            if filters.get('kitchen_area_max'):
                query = query.filter(Property.kitchen_area <= filters['kitchen_area_max'])

            # Search query (search in title, address, complex name, geocoded fields)
            if filters.get('search'):
                # Стоп-слова которые не несут смысловой нагрузки для поиска
                stop_words = {'улица', 'ул', 'район', 'р-н', 'город', 'г', 'жк', 'жилой', 'комплекс', 'дом', 'д', 'корпус', 'к', 'строение', 'стр', 'литер', 'лит'}
                
                # Разбить на слова, убрать стоп-слова и короткие слова
                raw_words = filters['search'].replace('"', '').replace("'", '').split()
                search_words = [w for w in raw_words if w.lower() not in stop_words and len(w) > 1]
                
                if search_words:
                    # Создаём фильтр: каждое слово должно присутствовать хотя бы в одном из полей
                    for word in search_words:
                        search_term = f"%{word}%"
                        query = query.filter(
                            or_(
                                Property.title.ilike(search_term),
                                Property.address.ilike(search_term),
                                ResidentialComplex.name.ilike(search_term),
                                Developer.name.ilike(search_term),
                                District.name.ilike(search_term),
                                Property.parsed_city.ilike(search_term),
                                Property.parsed_district.ilike(search_term),
                                Property.parsed_street.ilike(search_term),
                                Property.parsed_area.ilike(search_term),
                                Property.parsed_settlement.ilike(search_term),
                                Property.parsed_house.ilike(search_term),
                                Property.parsed_block.ilike(search_term)
                            )
                        )

            # ── Гео-фильтры по координатам ЖК (как DomClick/CIAN) ──────────────
            # geo_bbox: фильтр по bounding box координат ЖК
            # rc_name_keyword: фильтр по ключевому слову в названии ЖК
            # Если заданы оба — применяется OR (попадает в bbox ИЛИ название совпадает)
            _geo_bbox = filters.get('geo_bbox')
            _rc_keyword = filters.get('rc_name_keyword')
            if _geo_bbox or _rc_keyword:
                geo_conditions = []
                if _geo_bbox:
                    lat_min = _geo_bbox.get('lat_min')
                    lat_max = _geo_bbox.get('lat_max')
                    lon_min = _geo_bbox.get('lon_min')
                    lon_max = _geo_bbox.get('lon_max')
                    if lat_min is not None and lat_max is not None and lon_min is not None and lon_max is not None:
                        geo_conditions.append(
                            and_(
                                ResidentialComplex.latitude.isnot(None),
                                ResidentialComplex.longitude.isnot(None),
                                ResidentialComplex.latitude.between(lat_min, lat_max),
                                ResidentialComplex.longitude.between(lon_min, lon_max)
                            )
                        )
                if _rc_keyword and str(_rc_keyword).strip():
                    geo_conditions.append(
                        ResidentialComplex.name.ilike(f'%{_rc_keyword.strip()}%')
                    )
                if geo_conditions:
                    query = query.filter(or_(*geo_conditions))

        # Apply sorting
        if sort_by == 'relevance':
            # Relevance sort: diverse results across different complexes (CIAN/Domclick style).
            # Two-phase approach:
            #   Phase 1 — get distinct complex_ids ordered by property count (most active first).
            #   Phase 2 — for each complex fetch its best properties (with photo > price).
            #   Then round-robin interleave: 1st from each complex, then 2nd, etc.
            from sqlalchemy import case as sa_case, func as sq_func
            from collections import defaultdict, OrderedDict

            # Phase 1: which complexes, in what order?
            # Wrap the existing filtered query as a subquery that yields (id, complex_id).
            # All JOINs in get_base_query() are OUTER and many-to-one, so no row duplication.
            # Then count by complex_id in an outer query — avoids cartesian-product issues.
            need_complexes = min(500, max(100, (offset + limit) * 3))
            filtered_subq = query.with_entities(Property.id, Property.complex_id).subquery()
            cid_rows = (
                db.session.query(filtered_subq.c.complex_id, sq_func.count('*').label('cnt'))
                .group_by(filtered_subq.c.complex_id)
                .order_by(sq_func.count('*').desc())
                .limit(need_complexes)
                .all()
            )
            if not cid_rows:
                return []
            ordered_cids = [row.complex_id for row in cid_rows]

            # Phase 2: fetch best properties per complex.
            # How many per complex do we need for the requested page?
            max_depth_needed = (offset + limit) // max(1, len(ordered_cids)) + 2
            photo_quality = sa_case((Property.main_image.isnot(None), 0), else_=1)

            # Phase 2: Get exactly max_depth_needed best properties per complex.
            # Problem with simple ORDER BY complex_id LIMIT N: complexes with low IDs
            # monopolize all rows before higher-ID complexes get any.
            # Fix: use DISTINCT ON (complex_id) to get exactly 1 best property per complex
            # per pass, then exclude those IDs and repeat for depth > 1.
            by_complex = defaultdict(list)
            excluded_ids = set()
            base_q = query.filter(Property.complex_id.in_(ordered_cids))
            for _depth in range(max_depth_needed):
                depth_q = base_q.order_by(
                    Property.complex_id.asc(), photo_quality.asc(), Property.price.asc()
                ).distinct(Property.complex_id)
                if excluded_ids:
                    depth_q = depth_q.filter(Property.id.notin_(list(excluded_ids)))
                depth_rows = depth_q.all()
                if not depth_rows:
                    break
                for p in depth_rows:
                    cid = p.complex_id or -1
                    by_complex[cid].append(p)
                    excluded_ids.add(p.id)

            # Round-robin interleave in order of complex popularity
            diversified = []
            max_depth = max((len(v) for v in by_complex.values()), default=0)
            for depth in range(max_depth):
                for cid in ordered_cids:
                    bucket = by_complex.get(cid, [])
                    if depth < len(bucket):
                        diversified.append(bucket[depth])

            return diversified[offset: offset + limit]

        elif sort_by == 'price':
            query = query.order_by(Property.price.desc() if sort_order == 'desc' else Property.price.asc())
        elif sort_by == 'area':
            query = query.order_by(Property.area.desc() if sort_order == 'desc' else Property.area.asc())
        elif sort_by == 'date':
            query = query.order_by(Property.created_at.desc() if sort_order == 'desc' else Property.created_at.asc())
        elif sort_by == 'cashback':
            query = query.outerjoin(ResidentialComplex, Property.complex_id == ResidentialComplex.id)
            cashback_col = Property.price * func.coalesce(ResidentialComplex.cashback_rate, 3.5) / 100
            query = query.order_by(cashback_col.desc() if sort_order == 'desc' else cashback_col.asc())
        else:
            query = query.order_by(Property.price.asc())

        return query.offset(offset).limit(limit).all()
    
    @staticmethod
    def count_active(filters=None):
        """Подсчет активных квартир с фильтрами - ПОЛНАЯ ПОДДЕРЖКА build_property_filters() + кэширование 5 минут"""
        # Try to get from cache first
        cache_key = PropertyRepository._make_cache_key_for_filters(filters)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            print(f"✅ REPO count_active CACHE HIT for filters={filters}")
            return cached_result
        
        print(f"🔍 REPO count_active CACHE MISS for filters={filters}")
        # Need to join tables for filter support
        query = (
            db.session.query(func.count(Property.id))
            .join(ResidentialComplex, Property.complex_id == ResidentialComplex.id, isouter=True)
            .join(Developer, Property.developer_id == Developer.id, isouter=True)
            .join(District, Property.district_id == District.id, isouter=True)
            .filter(Property.is_active == True)
        )
        
        if filters:
            # Price filters
            if filters.get('min_price'):
                query = query.filter(Property.price >= filters['min_price'])
            if filters.get('max_price'):
                query = query.filter(Property.price <= filters['max_price'])
            # Price per sqm filters
            if filters.get('min_price_sqm'):
                query = query.filter(Property.price_per_sqm >= filters['min_price_sqm'])
            if filters.get('max_price_sqm'):
                query = query.filter(Property.price_per_sqm <= filters['max_price_sqm'])
            
            # Area filters
            if filters.get('min_area'):
                query = query.filter(Property.area >= filters['min_area'])
            if filters.get('max_area'):
                query = query.filter(Property.area <= filters['max_area'])
            
            # Rooms
            if filters.get('rooms'):
                room_values = []
                for r in filters['rooms']:
                    try:
                        room_values.append(int(r))
                    except (ValueError, TypeError):
                        pass
                if room_values:
                    query = query.filter(Property.rooms.in_(room_values))
            
            # Floor filters
            if filters.get('floor_min'):
                query = query.filter(Property.floor >= filters['floor_min'])
            if filters.get('floor_max'):
                query = query.filter(Property.floor <= filters['floor_max'])
            if filters.get('floor_options'):
                for option in filters['floor_options']:
                    if option == 'not_first':
                        query = query.filter(Property.floor > 1)
                    elif option == 'not_last':
                        query = query.filter(Property.floor < Property.total_floors)
                    elif option == 'last':
                        query = query.filter(Property.floor == Property.total_floors)
            
            # Complex/Developer/District filters
            if filters.get('complex_id'):
                query = query.filter(Property.complex_id == filters['complex_id'])
            if filters.get('complex_ids'):
                _cids2 = [int(c) for c in filters['complex_ids'] if str(c).isdigit() or isinstance(c, int)]
                if _cids2:
                    query = query.filter(Property.complex_id.in_(_cids2))
            if filters.get('residential_complex'):
                query = query.filter(ResidentialComplex.name == filters['residential_complex'])
            if filters.get('developer_id'):
                query = query.filter(Property.developer_id == filters['developer_id'])
            if filters.get('developer'):
                dev_val = filters['developer']
                query = query.filter(or_(Developer.name == dev_val, Developer.slug == dev_val))
            if filters.get('developers'):
                # Filter by developer IDs or names
                developer_ids = []
                developer_names = []
                developer_slugs = []
                for dev_value in filters['developers']:
                    if isinstance(dev_value, str) and dev_value.strip():
                        # Check if it's numeric ID or text name/slug
                        if dev_value.strip().isdigit():
                            developer_ids.append(int(dev_value.strip()))
                        else:
                            developer_names.append(dev_value.strip())
                            developer_slugs.append(dev_value.strip())
                    elif isinstance(dev_value, int):
                        developer_ids.append(dev_value)
                
                # Apply filters — match by ID, name, or slug
                conditions = []
                if developer_ids:
                    conditions.append(Property.developer_id.in_(developer_ids))
                if developer_names:
                    conditions.append(Developer.name.in_(developer_names))
                if developer_slugs:
                    conditions.append(Developer.slug.in_(developer_slugs))
                
                if conditions:
                    query = query.filter(or_(*conditions))
            
            # District FK filter — precise, uses index
            if filters.get('district_id'):
                _did = filters['district_id']
                district_name_fb = filters.get('district', '')
                if district_name_fb:
                    query = query.filter(
                        or_(
                            Property.district_id == _did,
                            and_(
                                Property.district_id == None,
                                or_(
                                    and_(District.name.isnot(None), District.name.ilike(f'%{district_name_fb}%')),
                                    and_(Property.parsed_district.isnot(None), Property.parsed_district.ilike(f'%{district_name_fb}%'))
                                )
                            )
                        )
                    )
                else:
                    query = query.filter(Property.district_id == _did)

            # District name filters — LIKE fallback
            elif filters.get('district'):
                district_name = filters['district'].strip() if filters['district'] else ''
                if district_name:
                    query = query.filter(
                        or_(
                            and_(District.name.isnot(None), District.name.ilike(f'%{district_name}%')),
                            and_(Property.parsed_district.isnot(None), Property.parsed_district.ilike(f'%{district_name}%')),
                            and_(Property.parsed_settlement.isnot(None), Property.parsed_settlement.ilike(f'%{district_name}%')),
                            and_(Property.parsed_area.isnot(None), Property.parsed_area.ilike(f'%{district_name}%')),
                            and_(ResidentialComplex.address_city_district.isnot(None), ResidentialComplex.address_city_district.ilike(f'%{district_name}%')),
                            and_(ResidentialComplex.address_quarter.isnot(None), ResidentialComplex.address_quarter.ilike(f'%{district_name}%'))
                        )
                    )
            # property_ids — explicit list of IDs (used by geo-PIP district pages)
            if filters.get('property_ids'):
                _pids2 = [int(p) for p in filters['property_ids'] if str(p).isdigit() or isinstance(p, int)]
                if _pids2:
                    query = query.filter(Property.id.in_(_pids2))

            # district_id_in — FK-based multi-district filter (preferred, precise)
            if filters.get('district_id_in'):
                _dids = [int(d) for d in filters['district_id_in'] if str(d).isdigit() or isinstance(d, int)]
                if _dids:
                    try:
                        from models import District as _District
                        _okrug_ids = [d.id for d in _District.query.filter(
                            _District.id.in_(_dids), _District.district_type == 'okrug'
                        ).all()]
                        _micro_ids = [d for d in _dids if d not in _okrug_ids]
                        _conds_did = []
                        if _micro_ids:
                            _conds_did.append(Property.district_id.in_(_micro_ids))
                        if _okrug_ids:
                            _conds_did.append(Property.district_id.in_(_okrug_ids))
                            _conds_did.append(ResidentialComplex.okrug_district_id.in_(_okrug_ids))
                        if _conds_did:
                            query = query.filter(or_(*_conds_did))
                    except Exception:
                        query = query.filter(Property.district_id.in_(_dids))
            elif filters.get('districts'):
                # Same geo-precise logic as get_all_active: use okrug_district_id for okrugs.
                _slugs_c = [s.strip() for s in filters['districts'] if s and str(s).strip()]
                _dconds_c = []
                _unresolved_c = []
                if _slugs_c:
                    try:
                        _slug_rows_c = District.query.filter(District.slug.in_(_slugs_c)).all()
                        _matched_slugs_c = {d.slug for d in _slug_rows_c}
                        _unresolved_c = [s for s in _slugs_c if s not in _matched_slugs_c]
                        for _d in _slug_rows_c:
                            cond = _build_district_geo_condition(_d)
                            if cond is not None:
                                _dconds_c.append(cond)
                    except Exception:
                        _unresolved_c = _slugs_c
                for _dn in _unresolved_c:
                    _dconds_c.append(
                        or_(
                            and_(Property.parsed_district.isnot(None), Property.parsed_district.ilike(f'%{_dn}%')),
                            and_(ResidentialComplex.address_city_district.isnot(None), ResidentialComplex.address_city_district.ilike(f'%{_dn}%')),
                            and_(ResidentialComplex.address_quarter.isnot(None), ResidentialComplex.address_quarter.ilike(f'%{_dn}%'))
                        )
                    )
                if _dconds_c:
                    query = query.filter(or_(*_dconds_c))
            
            # Building filters
            if filters.get('building'):
                query = query.filter(Property.complex_building_name == filters['building'])
            if filters.get('building_floors_min'):
                query = query.filter(Property.total_floors >= filters['building_floors_min'])
            if filters.get('building_floors_max'):
                query = query.filter(Property.total_floors <= filters['building_floors_max'])
            if filters.get('building_types'):
                query = query.filter(Property.building_type.in_(filters['building_types']))
            
            # Delivery/completion years (через ResidentialComplex.end_build_year)
            if filters.get('build_year_min'):
                query = query.filter(ResidentialComplex.end_build_year >= filters['build_year_min'])
            if filters.get('build_year_max'):
                query = query.filter(ResidentialComplex.end_build_year <= filters['build_year_max'])
            if filters.get('delivery_years'):
                query = query.filter(ResidentialComplex.end_build_year.in_(filters['delivery_years']))
            
            # Features
            if filters.get('cashback_only'):
                query = query.filter(ResidentialComplex.cashback_rate > 0)
            if filters.get('renovation'):
                db_renovation = PropertyRepository._resolve_renovation_db_values(filters['renovation'])
                if db_renovation:
                    query = query.filter(Property.renovation_type.in_(db_renovation))
            if filters.get('object_classes'):
                query = query.filter(ResidentialComplex.object_class_display_name.in_(filters['object_classes']))
            
            # Ипотека и финансы (новые фильтры)
            if filters.get('features'):
                for feature in filters['features']:
                    if feature == 'accreditation':
                        query = query.filter(ResidentialComplex.has_accreditation == True)
                    elif feature == 'green_mortgage':
                        query = query.filter(ResidentialComplex.has_green_mortgage == True)
            
            # Срок сдачи (completion years: 2024, 2025, 2026, etc.)
            if filters.get('completion'):
                completion_years = []
                for year_str in filters['completion']:
                    try:
                        completion_years.append(int(year_str))
                    except (ValueError, TypeError):
                        pass
                if completion_years:
                    query = query.filter(ResidentialComplex.end_build_year.in_(completion_years))
            
            # Building released filter (сданный/строительство)
            if filters.get('building_released'):
                from datetime import datetime
                current_year = datetime.now().year
                
                release_conditions = []
                for status in filters['building_released']:
                    # Support both true/false (from HTML checkboxes) and Russian strings
                    if status in ['true', 'True', 'сданный']:
                        release_conditions.append(ResidentialComplex.end_build_year <= current_year)
                    elif status in ['false', 'False', 'в строительстве']:
                        release_conditions.append(ResidentialComplex.end_build_year > current_year)
                
                if release_conditions:
                    query = query.filter(or_(*release_conditions))
            
            if filters.get('deal_type'):
                query = query.filter(Property.deal_type == filters['deal_type'])
            
            # Property type (apartments/houses/townhouses/penthouses/apartments_commercial)
            if filters.get('property_type') and filters['property_type'] != 'all':
                query = query.filter(Property.property_type == filters['property_type'])

            # Санузел (bathroom_type)
            if filters.get('bathroom_type'):
                bathroom_conditions = []
                for bt in filters['bathroom_type']:
                    if bt == 'combined':
                        bathroom_conditions.append(Property.bathroom_type.ilike('%совмещ%'))
                    elif bt == 'separate':
                        bathroom_conditions.append(Property.bathroom_type.ilike('%раздельн%'))
                if bathroom_conditions:
                    query = query.filter(or_(*bathroom_conditions))

            # Балкон / лоджия
            if filters.get('has_balcony'):
                if 'true' in filters['has_balcony'] or True in filters['has_balcony']:
                    query = query.filter(Property.has_balcony == True)

            # Высота потолков (мин)
            if filters.get('ceiling_height_min'):
                query = query.filter(Property.ceiling_height >= filters['ceiling_height_min'])

            # Площадь кухни
            if filters.get('kitchen_area_min'):
                query = query.filter(Property.kitchen_area >= filters['kitchen_area_min'])
            if filters.get('kitchen_area_max'):
                query = query.filter(Property.kitchen_area <= filters['kitchen_area_max'])

            # Search
            if filters.get('search'):
                # Стоп-слова которые не несут смысловой нагрузки для поиска
                stop_words = {'улица', 'ул', 'район', 'р-н', 'город', 'г', 'жк', 'жилой', 'комплекс', 'дом', 'д', 'корпус', 'к', 'строение', 'стр', 'литер', 'лит'}
                
                # Разбить на слова, убрать стоп-слова и короткие слова
                raw_words = filters['search'].replace('"', '').replace("'", '').split()
                search_words = [w for w in raw_words if w.lower() not in stop_words and len(w) > 1]
                
                if search_words:
                    for word in search_words:
                        search_term = f"%{word}%"
                        query = query.filter(
                            or_(
                                Property.title.ilike(search_term),
                                Property.address.ilike(search_term),
                                ResidentialComplex.name.ilike(search_term),
                                Developer.name.ilike(search_term),
                                District.name.ilike(search_term),
                                Property.parsed_city.ilike(search_term),
                                Property.parsed_district.ilike(search_term),
                                Property.parsed_street.ilike(search_term),
                                Property.parsed_area.ilike(search_term),
                                Property.parsed_settlement.ilike(search_term),
                                Property.parsed_house.ilike(search_term),
                                Property.parsed_block.ilike(search_term)
                            )
                        )
            
            # District ID direct filter (precise FK match)
            if filters.get('district_id'):
                query = query.filter(Property.district_id == filters['district_id'])

            # ⚠️ CRITICAL FIX: City filtering
            if filters.get('city_id'):
                query = query.filter(Property.city_id == filters['city_id'])

            # ── Гео-фильтры по координатам ЖК (как DomClick/CIAN) ──────────────
            _geo_bbox = filters.get('geo_bbox')
            _rc_keyword = filters.get('rc_name_keyword')
            if _geo_bbox or _rc_keyword:
                geo_conditions = []
                if _geo_bbox:
                    lat_min = _geo_bbox.get('lat_min')
                    lat_max = _geo_bbox.get('lat_max')
                    lon_min = _geo_bbox.get('lon_min')
                    lon_max = _geo_bbox.get('lon_max')
                    if lat_min is not None and lat_max is not None and lon_min is not None and lon_max is not None:
                        geo_conditions.append(
                            and_(
                                ResidentialComplex.latitude.isnot(None),
                                ResidentialComplex.longitude.isnot(None),
                                ResidentialComplex.latitude.between(lat_min, lat_max),
                                ResidentialComplex.longitude.between(lon_min, lon_max)
                            )
                        )
                if _rc_keyword and str(_rc_keyword).strip():
                    geo_conditions.append(
                        ResidentialComplex.name.ilike(f'%{_rc_keyword.strip()}%')
                    )
                if geo_conditions:
                    query = query.filter(or_(*geo_conditions))
        
        # Execute query and cache result
        result = query.scalar()
        cache.set(cache_key, result, timeout=300)  # Cache for 5 minutes
        return result
    
    @staticmethod
    def get_filtered_count(**filters):
        """Алиас для count_active - для совместимости с API endpoint"""
        return PropertyRepository.count_active(filters=filters)


    @staticmethod
    def get_by_id(property_id):
        """Получить квартиру по ID с подгруженными связями"""
        return PropertyRepository.get_base_query().filter(Property.id == property_id).first()
    
    @staticmethod
    def get_by_ids_batch(property_ids):
        """
        Batch load properties by IDs in a single query with all relations preloaded
        Returns dict {property_id: Property} for fast lookup
        
        Args:
            property_ids: List of property IDs to load
        
        Returns:
            dict: {property_id: Property object with relations loaded}
        """
        if not property_ids:
            return {}
        
        # Use base query which includes all joins and eager loading
        properties = (
            PropertyRepository.get_base_query()
            .filter(Property.id.in_(property_ids))
            .all()
        )
        
        # Return as dict for fast lookups
        return {prop.id: prop for prop in properties}
    
    @staticmethod
    def get_by_inner_id(inner_id):
        """Получить квартиру по legacy inner_id (для обратной совместимости)"""
        return PropertyRepository.get_base_query().filter(Property.inner_id == str(inner_id)).first()
    
    @staticmethod
    def get_by_inner_ids(inner_ids):
        """
        Batch load properties by inner_ids (для обратной совместимости с legacy данными)
        Returns dict {inner_id: Property} for fast lookup
        """
        if not inner_ids:
            return {}
        
        # Convert all to strings
        inner_ids_str = [str(iid) for iid in inner_ids]
        
        properties = (
            PropertyRepository.get_base_query()
            .filter(Property.inner_id.in_(inner_ids_str))
            .all()
        )
        
        # Return as dict for fast lookups
        return {str(prop.inner_id): prop for prop in properties}
    
    @staticmethod
    def get_price_range():
        """Получить мин/макс цены"""
        result = db.session.query(
            func.min(Property.price),
            func.max(Property.price)
        ).filter(Property.is_active == True).first()
        
        return {
            'min_price': result[0] or 0,
            'max_price': result[1] or 0
        }
    
    @staticmethod
    def get_properties_with_coordinates():
        """Получить все квартиры с координатами для карты"""
        from models import Developer
        return (
            db.session.query(
                Property.id,
                Property.inner_id,
                Property.title,
                Property.price,
                Property.rooms,
                Property.area,
                Property.floor,
                Property.total_floors,
                Property.main_image,
                Property.gallery_images,
                Property.latitude,
                Property.longitude,
                ResidentialComplex.name.label('complex_name'),
                ResidentialComplex.cashback_rate,
                Developer.name.label('developer_name')
            )
            .join(ResidentialComplex, Property.complex_id == ResidentialComplex.id)
            .outerjoin(Developer, ResidentialComplex.developer_id == Developer.id)
            .filter(
                Property.is_active == True,
                Property.latitude.isnot(None),
                Property.longitude.isnot(None)
            )
            .all()
        )
    
    @staticmethod
    def get_featured_properties(limit=6):
        """Получить избранные/рекомендуемые квартиры"""
        return (
            PropertyRepository.get_base_query()
            .filter(Property.is_active == True)
            .order_by(Property.price.desc())
            .limit(limit)
            .all()
        )
    
    @staticmethod
    def get_by_complex_id(complex_id, limit=50, sort_by='price', sort_order='desc'):
        """Получить квартиры по ID ЖК с сортировкой"""
        query = PropertyRepository.get_base_query().filter(Property.complex_id == complex_id, Property.is_active == True)
        
        # Apply sorting
        if sort_by == 'price':
            query = query.order_by(Property.price.desc() if sort_order == 'desc' else Property.price.asc())
        elif sort_by == 'area':
            query = query.order_by(Property.area.desc() if sort_order == 'desc' else Property.area.asc())
        
        return query.limit(limit).all()
    
    @staticmethod
    def get_all_property_stats(city_id=None):
        """
        Получить статистику квартир для всех ЖК одним запросом (избегает N+1) + кэширование 5 минут
        
        Args:
            city_id: Optional integer - filter properties by city_id
        
        Returns:
            dict: {complex_id: {stats}} - statistics for each complex
        """
        # Try to get from cache first
        cache_key = PropertyRepository._make_stats_cache_key(city_id)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            print(f"✅ REPO get_all_property_stats CACHE HIT for city_id={city_id}")
            return cached_result
        
        print(f"🔍 REPO get_all_property_stats CACHE MISS for city_id={city_id}")
        # Основная статистика (цены, площади, адреса)
        stats_query = db.session.query(
            Property.complex_id,
            func.count(Property.id).label('total'),
            func.min(Property.price).label('min_price'),
            func.max(Property.price).label('max_price'),
            func.avg(Property.price).label('avg_price'),
            func.min(Property.area).label('min_area'),
            func.max(Property.area).label('max_area'),
            func.max(Property.address).label('sample_address')
        ).filter(Property.is_active == True)
        
        # Add city filter if provided
        if city_id:
            stats_query = stats_query.join(
                ResidentialComplex, Property.complex_id == ResidentialComplex.id
            ).filter(ResidentialComplex.city_id == city_id)
        
        stats_query = stats_query.group_by(Property.complex_id).all()
        
        # Подсчет уникальных корпусов по complex_building_name для каждого ЖК
        buildings_query = db.session.query(
            Property.complex_id,
            func.count(func.distinct(Property.complex_building_name)).label('buildings_count')
        ).filter(
            Property.is_active == True,
            Property.complex_building_name.isnot(None)
        )
        
        # Add city filter if provided
        if city_id:
            buildings_query = buildings_query.join(
                ResidentialComplex, Property.complex_id == ResidentialComplex.id
            ).filter(ResidentialComplex.city_id == city_id)
        
        buildings_query = buildings_query.group_by(Property.complex_id).all()
        
        buildings_dict = {row.complex_id: max(row.buildings_count, 1) for row in buildings_query}
        
        # Получаем первое фото из свойств для каждого ЖК (fallback если у ЖК нет собственных фото)
        photos_query = db.session.query(
            Property.complex_id,
            func.min(Property.gallery_images).label('sample_photos')
        ).filter(
            Property.is_active == True,
            Property.gallery_images.isnot(None),
            Property.gallery_images != '[]'
        )
        
        # Add city filter if provided
        if city_id:
            photos_query = photos_query.join(
                ResidentialComplex, Property.complex_id == ResidentialComplex.id
            ).filter(ResidentialComplex.city_id == city_id)
        
        photos_query = photos_query.group_by(Property.complex_id).all()
        
        photos_dict = {}
        for row in photos_query:
            try:
                photos_raw = json.loads(row.sample_photos) if isinstance(row.sample_photos, str) else row.sample_photos
                if photos_raw and isinstance(photos_raw, list) and len(photos_raw) > 1:
                    # Пропускаем первое фото (индекс 0), берем со 2-го по 4-е (индексы 1,2,3)
                    photos_dict[row.complex_id] = photos_raw[1:4]
            except:
                pass
        
        stats_dict = {}
        for row in stats_query:
            stats_dict[row.complex_id] = {
                'total_count': row.total or 0,
                'total_properties': row.total or 0,
                'min_price': int(row.min_price) if row.min_price else 0,
                'max_price': int(row.max_price) if row.max_price else 0,
                'avg_price': int(row.avg_price) if row.avg_price else 0,
                'min_area': float(row.min_area) if row.min_area else 0,
                'max_area': float(row.max_area) if row.max_area else 0,
                'sample_address': row.sample_address if hasattr(row, 'sample_address') else None,
                'buildings_count': buildings_dict.get(row.complex_id, 1),  # Default 1 if no buildings
                'sample_photos': photos_dict.get(row.complex_id, []),  # Photos from properties
                'room_distribution': {},
                'room_details': {}  # Детальная статистика по типам комнат
            }
        
        # Детальная статистика по комнатам для каждого ЖК (с ценами и площадями)
        room_query = db.session.query(
            Property.complex_id,
            Property.rooms,
            func.count(Property.id).label('count'),
            func.min(Property.price).label('min_price'),
            func.max(Property.price).label('max_price'),
            func.min(Property.area).label('min_area'),
            func.max(Property.area).label('max_area')
        ).filter(Property.is_active == True)
        
        # Add city filter if provided
        if city_id:
            room_query = room_query.join(
                ResidentialComplex, Property.complex_id == ResidentialComplex.id
            ).filter(ResidentialComplex.city_id == city_id)
        
        room_query = room_query.group_by(Property.complex_id, Property.rooms).all()
        
        # Добавляем room distribution и room_details к статистике
        for row in room_query:
            complex_id = row.complex_id
            rooms = row.rooms or 0
            count = row.count
            
            if complex_id in stats_dict:
                room_type = f"{rooms}-комн" if rooms and rooms > 0 else "Студия"
                
                # Простой подсчет количества
                stats_dict[complex_id]['room_distribution'][room_type] = count
                
                # Детальная статистика с ценами и площадями
                stats_dict[complex_id]['room_details'][room_type] = {
                    'count': count,
                    'price_from': int(row.min_price) if row.min_price else 0,
                    'price_to': int(row.max_price) if row.max_price else 0,
                    'area_from': round(float(row.min_area), 1) if row.min_area else 0,
                    'area_to': round(float(row.max_area), 1) if row.max_area else 0
                }
        
        # Cache the result for 5 minutes
        cache.set(cache_key, stats_dict, timeout=300)
        return stats_dict
    
    @staticmethod
    def get_filtered_property_stats(price_min=None, price_max=None, rooms=None, area_min=None, area_max=None):
        """Получить статистику квартир для ЖК с учетом фильтров (избегает N+1)"""
        import json
        
        # Базовый фильтр
        base_filter = Property.is_active == True
        
        # Построение дополнительных фильтров
        filters = [base_filter]
        
        if price_min:
            filters.append(Property.price >= price_min)
        if price_max:
            filters.append(Property.price <= price_max)
        if rooms and len(rooms) > 0:
            filters.append(Property.rooms.in_(rooms))
        if area_min:
            filters.append(Property.area >= area_min)
        if area_max:
            filters.append(Property.area <= area_max)
        
        # Основная статистика (цены, площади, адреса)
        stats_query = (
            db.session.query(
                Property.complex_id,
                func.count(Property.id).label('total'),
                func.min(Property.price).label('min_price'),
                func.max(Property.price).label('max_price'),
                func.avg(Property.price).label('avg_price'),
                func.min(Property.area).label('min_area'),
                func.max(Property.area).label('max_area'),
                func.max(Property.address).label('sample_address')
            )
            .filter(*filters)
            .group_by(Property.complex_id)
            .all()
        )
        
        # Подсчет уникальных корпусов по complex_building_name для каждого ЖК
        buildings_query = (
            db.session.query(
                Property.complex_id,
                func.count(func.distinct(Property.complex_building_name)).label('buildings_count')
            )
            .filter(
                *filters,
                Property.complex_building_name.isnot(None)
            )
            .group_by(Property.complex_id)
            .all()
        )
        
        buildings_dict = {row.complex_id: max(row.buildings_count, 1) for row in buildings_query}
        
        # Получаем первое фото из свойств для каждого ЖК (fallback если у ЖК нет собственных фото)
        photos_query = (
            db.session.query(
                Property.complex_id,
                func.min(Property.gallery_images).label('sample_photos')
            )
            .filter(
                *filters,
                Property.gallery_images.isnot(None),
                Property.gallery_images != '[]'
            )
            .group_by(Property.complex_id)
            .all()
        )
        
        photos_dict = {}
        for row in photos_query:
            try:
                photos_raw = json.loads(row.sample_photos) if isinstance(row.sample_photos, str) else row.sample_photos
                if photos_raw and isinstance(photos_raw, list) and len(photos_raw) > 1:
                    # Пропускаем первое фото (индекс 0), берем со 2-го по 4-е (индексы 1,2,3)
                    photos_dict[row.complex_id] = photos_raw[1:4]
            except:
                pass
        
        stats_dict = {}
        for row in stats_query:
            stats_dict[row.complex_id] = {
                'total_count': row.total or 0,
                'total_properties': row.total or 0,
                'min_price': int(row.min_price) if row.min_price else 0,
                'max_price': int(row.max_price) if row.max_price else 0,
                'avg_price': int(row.avg_price) if row.avg_price else 0,
                'min_area': float(row.min_area) if row.min_area else 0,
                'max_area': float(row.max_area) if row.max_area else 0,
                'sample_address': row.sample_address if hasattr(row, 'sample_address') else None,
                'buildings_count': buildings_dict.get(row.complex_id, 1),  # Default 1 if no buildings
                'sample_photos': photos_dict.get(row.complex_id, []),  # Photos from properties
                'room_distribution': {},
                'room_details': {}  # Детальная статистика по типам комнат
            }
        
        # Детальная статистика по комнатам для каждого ЖК (с ценами и площадями)
        room_query = (
            db.session.query(
                Property.complex_id,
                Property.rooms,
                func.count(Property.id).label('count'),
                func.min(Property.price).label('min_price'),
                func.max(Property.price).label('max_price'),
                func.min(Property.area).label('min_area'),
                func.max(Property.area).label('max_area')
            )
            .filter(*filters)
            .group_by(Property.complex_id, Property.rooms)
            .all()
        )
        
        # Добавляем room distribution и room_details к статистике
        for row in room_query:
            complex_id = row.complex_id
            rooms = row.rooms or 0
            count = row.count
            
            if complex_id in stats_dict:
                room_type = f"{rooms}-комн" if rooms and rooms > 0 else "Студия"
                
                # Простой подсчет количества
                stats_dict[complex_id]['room_distribution'][room_type] = count
                
                # Детальная статистика с ценами и площадями
                stats_dict[complex_id]['room_details'][room_type] = {
                    'count': count,
                    'price_from': int(row.min_price) if row.min_price else 0,
                    'price_to': int(row.max_price) if row.max_price else 0,
                    'area_from': round(float(row.min_area), 1) if row.min_area else 0,
                    'area_to': round(float(row.max_area), 1) if row.max_area else 0
                }
        
        return stats_dict


class ResidentialComplexRepository:
    """Repository для работы с жилыми комплексами"""
    
    @staticmethod
    def get_base_query():
        """Базовый query с JOIN застройщика и района (без joinedload → N+1 SELECT на каждый .district.name)"""
        return (
            db.session.query(ResidentialComplex)
            .join(Developer, ResidentialComplex.developer_id == Developer.id, isouter=True)
            .options(
                joinedload(ResidentialComplex.developer),
                joinedload(ResidentialComplex.district),
            )
        )
    
    @staticmethod
    def get_all_active(limit=50, offset=0, city_id=None):
        """
        Получить все активные ЖК
        
        Args:
            limit: Максимальное количество ЖК
            offset: Смещение для пагинации
            city_id: Опциональный ID города для фильтрации
        """
        query = (
            ResidentialComplexRepository.get_base_query()
            .filter(ResidentialComplex.is_active == True)
        )
        
        # Add city filter if provided
        if city_id:
            query = query.filter(ResidentialComplex.city_id == city_id)
        
        return query.offset(offset).limit(limit).all()
    
    @staticmethod
    def get_by_id(complex_id):
        """Получить ЖК по ID"""
        return ResidentialComplexRepository.get_base_query().filter(ResidentialComplex.id == complex_id).first()
    
    @staticmethod
    def get_by_slug(slug):
        """Получить ЖК по slug"""
        return ResidentialComplexRepository.get_base_query().filter(ResidentialComplex.slug == slug).first()
    
    @staticmethod
    def count_active():
        """Подсчет активных ЖК"""
        return db.session.query(func.count(ResidentialComplex.id)).filter(ResidentialComplex.is_active == True).scalar()
    
    @staticmethod
    def get_with_coordinates(city_id=None):
        """Получить ЖК с координатами для карты"""
        q = (
            db.session.query(
                ResidentialComplex.id,
                ResidentialComplex.name,
                ResidentialComplex.slug,
                ResidentialComplex.latitude,
                ResidentialComplex.longitude,
                ResidentialComplex.cashback_rate,
                ResidentialComplex.main_image,
                ResidentialComplex.end_build_year,
                ResidentialComplex.end_build_quarter,
                ResidentialComplex.object_class_display_name,
                Developer.name.label('developer_name')
            )
            .join(Developer, ResidentialComplex.developer_id == Developer.id, isouter=True)
            .filter(
                ResidentialComplex.is_active == True,
                ResidentialComplex.latitude.isnot(None),
                ResidentialComplex.longitude.isnot(None)
            )
        )
        if city_id:
            q = q.filter(ResidentialComplex.city_id == city_id)
        return q.all()
    
    @staticmethod
    def get_property_stats(complex_id):
        """Получить статистику квартир в ЖК"""
        stats = (
            db.session.query(
                func.count(Property.id).label('total'),
                func.min(Property.price).label('min_price'),
                func.max(Property.price).label('max_price'),
                func.avg(Property.price).label('avg_price')
            )
            .filter(
                Property.complex_id == complex_id,
                Property.is_active == True
            )
            .first()
        )
        
        return {
            'total_properties': stats.total or 0,
            'min_price': int(stats.min_price) if stats.min_price else 0,
            'max_price': int(stats.max_price) if stats.max_price else 0,
            'avg_price': int(stats.avg_price) if stats.avg_price else 0
        }
    


class DeveloperRepository:
    """Repository для работы с застройщиками"""
    
    @staticmethod
    def get_all_active():
        """Получить всех активных застройщиков"""
        return Developer.query.filter_by(is_active=True).all()
    
    @staticmethod
    def get_by_id(developer_id):
        """Получить застройщика по ID"""
        return Developer.query.filter_by(id=developer_id).first()
    
    @staticmethod
    def get_by_slug(slug):
        """Получить застройщика по slug"""
        return Developer.query.filter_by(slug=slug).first()
    
    @staticmethod
    def get_with_stats():
        """Получить застройщиков со статистикой ЖК и квартир"""
        return (
            db.session.query(
                Developer,
                func.count(ResidentialComplex.id.distinct()).label('complexes_count'),
                func.count(Property.id).label('properties_count')
            )
            .outerjoin(ResidentialComplex, Developer.id == ResidentialComplex.developer_id)
            .outerjoin(Property, Developer.id == Property.developer_id)
            .filter(Developer.is_active == True)
            .group_by(Developer.id)
            .all()
        )

class DistrictRepository:
    """Repository для работы с районами"""
    
    @staticmethod
    def get_all_active():
        """Получить все районы"""
        return District.query.order_by(District.name).all()
    
    @staticmethod
    def get_by_id(district_id):
        """Получить район по ID"""
        return District.query.filter_by(id=district_id).first()
    
    @staticmethod
    def get_by_slug(slug):
        """Получить район по slug"""
        return District.query.filter_by(slug=slug).first()
