"""
Developers Blueprint — developer listing and detail pages.
Endpoints: devs.developers_redirect, devs.developers_city_alt, devs.developers_city, devs.developer_page
"""
import json
import logging

from flask import (Blueprint, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user
from sqlalchemy import text, func

from app import db

logger = logging.getLogger(__name__)

devs_bp = Blueprint('devs', __name__)


def _resolve_city_context(**kwargs):
    from app import resolve_city_context
    return resolve_city_context(**kwargs)


def _create_slug(name):
    from app import create_slug
    return create_slug(name)


@devs_bp.route('/developers')
def developers_redirect():
    """Redirect /developers to city-slug URL /<city_slug>/zastrojshchiki"""
    city = _resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city'),
        default_if_none=True
    )
    city_slug = city.slug if city else 'krasnodar'
    return redirect(url_for('devs.developers_city', city_slug=city_slug), 301)


@devs_bp.route('/<city_slug>/developers')
def developers_city_en(city_slug):
    """English /developers alias → canonical /<city_slug>/zastrojshchiki"""
    return redirect(url_for('devs.developers_city', city_slug=city_slug), 301)


@devs_bp.route('/<city_slug>/zastroyshchiki')
def developers_city_alt(city_slug):
    """Alternate transliteration redirect → canonical /<city_slug>/zastrojshchiki"""
    return redirect(url_for('devs.developers_city', city_slug=city_slug), 301)


@devs_bp.route('/<city_slug>/zastrojshchiki')
def developers_city(city_slug):
    """Developers listing page with city-slug URL for SEO"""
    try:
        current_city = _resolve_city_context(
            city_slug=city_slug,
            default_if_none=True
        )
        
        logger.info(f"[/developers] Loading developers for city: {current_city.name if current_city else 'All (no filter)'}")
        
        from models import Developer, ResidentialComplex, Property
        from services.dadata_client import DaDataClient
        from sqlalchemy import func
        
        # Получаем застройщиков из базы данных с статистикой
        # Фильтруем по городу, если город выбран
        query = db.session.query(Developer, 
                            func.count(ResidentialComplex.id).label('complexes_count'),
                            func.count(Property.id).label('properties_count'))
        query = query.filter(Developer.is_active == True)
        
        if current_city:
            # Фильтруем только те ЖК и объекты, которые принадлежат текущему городу
            query = query.outerjoin(ResidentialComplex, 
                                   (Developer.id == ResidentialComplex.developer_id) & 
                                   (ResidentialComplex.city_id == current_city.id))
            # Property связан с Developer через ResidentialComplex, не напрямую
            query = query.outerjoin(Property, 
                                   (ResidentialComplex.id == Property.complex_id) & 
                                   (Property.city_id == current_city.id))
        else:
            query = query.outerjoin(ResidentialComplex, Developer.id == ResidentialComplex.developer_id)
            # Property связан с Developer через ResidentialComplex
            query = query.outerjoin(Property, ResidentialComplex.id == Property.complex_id)
        
        # Показываем застройщиков у которых есть ЖК в городе (даже если квартир пока 0)
        query = query.group_by(Developer.id)
        if current_city:
            query = query.having(func.count(ResidentialComplex.id) > 0)
        
        developers_list = query.order_by(func.count(Property.id).desc(), func.count(ResidentialComplex.id).desc()).all()
        
        # Формируем список застройщиков с данными
        developers_data = []
        for developer, complexes_count, properties_count in developers_list:
            developer_dict = {
                'id': developer.id,
                'name': developer.name,
                'slug': developer.slug,
                'description': developer.description or f"Застройщик {developer.name}",
                'logo_url': developer.logo_url or None,
                'website': developer.website,
                'phone': developer.phone,
                'email': developer.email,
                'address': developer.address,
                'complexes_count': complexes_count,
                'properties_count': properties_count,
                'established_year': developer.established_year,
                'founded_year': developer.founded_year or developer.established_year,
                'completed_projects': developer.completed_projects or 0,
                'under_construction': developer.under_construction or 0,
                # Нужные поля для шаблона
                'max_cashback': 10,  # По умолчанию 10%
                'max_cashback_percent': 10,
                # Статистика для отображения
                'stats': {
                    'total_projects': complexes_count,
                    'total_apartments': properties_count,
                    'avg_price': None  # Добавим позже
                }
            }
            
            # ✅ MIGRATED: Get statistics using ORM Property model
            from sqlalchemy import func
            # Фильтруем статистику по текущему городу
            # Property связан с Developer через ResidentialComplex
            stats_query = db.session.query(
                func.count(Property.id).label('total_properties'),
                func.avg(Property.price).label('avg_price'),
                func.min(Property.price).label('min_price'),
                func.max(Property.price).label('max_price'),
                func.count(func.distinct(Property.complex_id)).label('total_complexes')
            ).join(
                ResidentialComplex, Property.complex_id == ResidentialComplex.id
            ).filter(
                ResidentialComplex.developer_id == developer.id,
                Property.is_active == True
            )
            
            if current_city:
                stats_query = stats_query.filter(Property.city_id == current_city.id)
            
            stats_result = stats_query.first()
            
            if stats_result and stats_result.total_properties:
                total_props, avg_price, min_price, max_price, total_complexes = stats_result
                developer_dict['properties_count'] = total_props or properties_count
                developer_dict['complexes_count'] = total_complexes or complexes_count
                developer_dict['stats'] = {
                    'total_projects': total_complexes or complexes_count,
                    'total_apartments': total_props or properties_count,
                    'avg_price': int(avg_price) if avg_price else None,
                    'min_price': int(min_price) if min_price else None,
                    'max_price': int(max_price) if max_price else None
                }
            else:
                # Fallback to basic database stats
                developer_dict['stats'] = {
                    'total_projects': complexes_count,
                    'total_apartments': properties_count,
                    'avg_price': None
                }
            
            developers_data.append(developer_dict)
        
        logger.info(f"[/developers] Returning {len(developers_data)} developers (city={current_city.name if current_city else 'all'})")
        
        # Получаем общую статистику для страницы (по городу если выбран)
        if current_city:
            # Статистика по текущему городу
            total_developers = len(developers_data)  # Количество застройщиков с объектами в городе
            total_complexes = db.session.query(ResidentialComplex).filter(
                ResidentialComplex.city_id == current_city.id
            ).count()
            # Берем количество довольных клиентов пропорционально
            satisfied_clients = max(50, total_developers * 10)
        else:
            # Статистика по всей базе
            total_developers = db.session.query(Developer).count()
            total_complexes = db.session.query(ResidentialComplex).count()
            satisfied_clients = 500  # Берем значение с about.html
        
        return render_template('developers.html', 
                             developers=developers_data,
                             current_city=current_city,
                             total_developers=total_developers,
                             total_complexes=total_complexes,
                             satisfied_clients=satisfied_clients)
        
    except Exception as e:
        print(f"Error loading developers: {e}")
        current_city = _resolve_city_context()
        return render_template('developers.html', developers=[], current_city=current_city)

@devs_bp.route('/developer/<developer_slug>')  
def developer_page(developer_slug):
    """Individual developer page by slug"""
    try:
        # Transliteration mapping for finding Cyrillic slugs from Latin input
        translit_map = str.maketrans('abcdefghijklmnopqrstuvwxyz', 'абцдефгхийклмнопкрствухызгк-неометрия'[:26])
        
        # Create variations of the developer name to search for
        developer_name_from_slug = developer_slug.replace('-', ' ')
        
        # Try to find developer in database using multiple search strategies
        # First try exact match with original slug
        developer = db.session.execute(
            text("""
            SELECT * FROM developers WHERE 
            LOWER(slug) = LOWER(:slug)
            OR LOWER(name) LIKE LOWER(:name_pattern)
            OR LOWER(REPLACE(name, ' ', '-')) = LOWER(:slug)
            LIMIT 1
            """),
            {
                "slug": developer_slug, 
                "name_pattern": f"%{developer_name_from_slug}%"
            }
        ).fetchone()
        
        # If not found, try searching by name matching (case insensitive)
        if not developer:
            # Try all developers and match by similarity
            all_devs = db.session.execute(text("SELECT * FROM developers")).fetchall()
            for dev in all_devs:
                dev_slug = dev.slug.lower() if dev.slug else ''
                dev_name = dev.name.lower().replace(' ', '-').replace('гк', 'gk')
                dev_name = dev_name.replace('неометрия', 'neometriya')
                
                if developer_slug.lower() in [dev_slug, dev_name]:
                    developer = dev
                    break
        
        if not developer:
            print(f"Developer not found in database: {developer_slug}")
            return redirect(url_for('devs.developers_redirect'))
        
        # Convert row to dict-like object for template
        developer_dict = dict(developer._mapping)
        
        # ✅ MIGRATED: Get developer's complexes from normalized tables
        from models import ResidentialComplex
        developer_complexes_orm = (
            db.session.query(ResidentialComplex)
            .filter(ResidentialComplex.developer_id == developer.id)
            .all()
        )
        
        # Get property statistics for each complex using PropertyRepository
        from repositories.property_repository import PropertyRepository
        developer_complexes_query = []
        for complex_orm in developer_complexes_orm:
            # Get properties for this complex
            complex_properties = PropertyRepository.get_by_complex_id(complex_orm.id, limit=10000)
            
            # Calculate statistics
            if complex_properties:
                min_price = min(p.price for p in complex_properties if p.price)
                max_price = max(p.price for p in complex_properties if p.price)
                avg_price = sum(p.price for p in complex_properties if p.price) / len(complex_properties)
                
                # Get unique buildings count
                buildings = set(p.complex_building_name for p in complex_properties if p.complex_building_name)
                buildings_count = len(buildings)
                
                # Get photos: prefer complex JK gallery (real exterior photos) over property gallery
                main_image = 'https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800'
                images = [main_image]
                # First try complex-level gallery (scraped from JK CIAN page — exterior photos)
                if complex_orm.gallery_images:
                    try:
                        jk_gallery = json.loads(complex_orm.gallery_images)
                        if jk_gallery and isinstance(jk_gallery, list) and len(jk_gallery) > 0:
                            images = jk_gallery[:10]
                            main_image = complex_orm.main_image or jk_gallery[0]
                    except:
                        pass
                # Fall back to property gallery only if JK gallery is empty
                if images == [main_image] and complex_properties[0].gallery_images:
                    try:
                        photos_list = json.loads(complex_properties[0].gallery_images)
                        if photos_list and isinstance(photos_list, list):
                            images = photos_list
                            main_image = photos_list[0]
                    except:
                        pass
                # Also use main_image from complex if available and not already set
                if complex_orm.main_image and main_image == 'https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800':
                    main_image = complex_orm.main_image

                # Get city slug for correct URL routing
                _city_row = db.session.execute(
                    text("SELECT slug FROM cities WHERE id = :city_id"),
                    {"city_id": complex_orm.city_id}
                ).fetchone()
                _city_slug = _city_row[0] if _city_row else 'krasnodar'
                _complex_slug = complex_orm.slug or _create_slug(complex_orm.name)

                # Get address from properties (fallback to complex address)
                property_address = complex_properties[0].address if complex_properties and complex_properties[0].address else None

                # Resolve district name: prefer DB district, then property parsed_district
                _district_name = ''
                if complex_orm.district_id:
                    _dr = db.session.execute(
                        text("SELECT name FROM districts WHERE id = :did"),
                        {'did': complex_orm.district_id}
                    ).fetchone()
                    if _dr:
                        _district_name = _dr[0]
                if not _district_name:
                    # Try first property's parsed_district or district relationship
                    for _p in complex_properties[:10]:
                        if hasattr(_p, 'district') and _p.district:
                            _district_name = _p.district.name
                            break
                        if hasattr(_p, 'parsed_district') and _p.parsed_district:
                            _district_name = _p.parsed_district
                            break

                # Create complex data structure
                complex_data = type('obj', (object,), {
                    'name': complex_orm.name,
                    'id': complex_orm.id,
                    'slug': _complex_slug,
                    'city_slug': _city_slug,
                    'district': _district_name,
                    'location': property_address or complex_orm.address or 'Адрес не указан',
                    'apartments_count': len(complex_properties),
                    'buildings_count': buildings_count or 1,
                    'min_price': int(min_price),
                    'max_price': int(max_price),
                    'avg_price': int(avg_price),
                    'lat': complex_properties[0].latitude if complex_properties[0].latitude else None,
                    'lng': complex_properties[0].longitude if complex_properties[0].longitude else None,
                    'sales_address': property_address or complex_orm.address,
                    'images': images,
                    'image': main_image,
                    'completion_date': f"{complex_orm.end_build_quarter} кв. {complex_orm.end_build_year}" if complex_orm.end_build_quarter and complex_orm.end_build_year else 'Сдан',
                    'real_price_from': int(min_price),
                    'room_types_count': len(set(p.rooms for p in complex_properties)),
                    '_mapping': {
                        'name': complex_orm.name,
                        'id': complex_orm.id,
                        'slug': _complex_slug,
                        'city_slug': _city_slug,
                        'district': _district_name,
                        'location': property_address or complex_orm.address or 'Адрес не указан',
                        'apartments_count': len(complex_properties),
                        'buildings_count': buildings_count or 1,
                        'min_price': int(min_price),
                        'max_price': int(max_price),
                        'avg_price': int(avg_price),
                        'lat': complex_properties[0].latitude if complex_properties[0].latitude else None,
                        'lng': complex_properties[0].longitude if complex_properties[0].longitude else None,
                        'sales_address': property_address or complex_orm.address,
                        'images': images,
                        'image': main_image,
                        'completion_date': f"{complex_orm.end_build_quarter} кв. {complex_orm.end_build_year}" if complex_orm.end_build_quarter and complex_orm.end_build_year else 'Сдан',
                        'real_price_from': int(min_price),
                        'room_types_count': len(set(p.rooms for p in complex_properties))
                    }
                })()
                developer_complexes_query.append(complex_data)
        
        # Sort by apartments_count descending
        developer_complexes_query = sorted(developer_complexes_query, key=lambda x: x.apartments_count, reverse=True)
        
        developer_complexes = []
        for complex_row in developer_complexes_query:
            complex_dict = dict(complex_row._mapping)
            
            # ✅ MIGRATED: Get room distribution from PropertyRepository
            # Get all properties for this complex from the developer_complexes_query data
            complex_name = complex_dict['name']
            matching_complex = next((c for c in developer_complexes_orm if c.name == complex_name), None)
            
            room_distribution_query = []
            if matching_complex:
                complex_props = PropertyRepository.get_by_complex_id(matching_complex.id, limit=10000)
                
                # Group by rooms
                from collections import defaultdict
                room_groups = defaultdict(list)
                for p in complex_props:
                    room_groups[p.rooms].append(p)

                # Normalize None → 0 (студии без явного указания комнат)
                if None in room_groups:
                    room_groups[0].extend(room_groups.pop(None))

                # Create room distribution data
                for rooms, props in sorted(room_groups.items(), key=lambda x: x[0] if x[0] is not None else 0):
                    room_type = 'Студия' if rooms == 0 else f'{rooms}-комн.'
                    room_data = type('obj', (object,), {
                        'room_type': room_type,
                        'count': len(props),
                        'price_from': min(p.price for p in props if p.price),
                        'price_to': max(p.price for p in props if p.price),
                        'area_from': min(p.area for p in props if p.area),
                        'area_to': max(p.area for p in props if p.area),
                        '_mapping': {
                            'room_type': room_type,
                            'count': len(props),
                            'price_from': min(p.price for p in props if p.price),
                            'price_to': max(p.price for p in props if p.price),
                            'area_from': min(p.area for p in props if p.area),
                            'area_to': max(p.area for p in props if p.area)
                        }
                    })()
                    room_distribution_query.append(room_data)
            
            # Формируем данные о комнатности
            real_room_distribution = {}
            room_details = {}
            
            for room_row in room_distribution_query:
                room_data = dict(room_row._mapping)
                room_type = room_data['room_type']
                real_room_distribution[room_type] = room_data['count']
                room_details[room_type] = {
                    'price_from': room_data['price_from'],
                    'price_to': room_data['price_to'],
                    'area_from': room_data['area_from'],
                    'area_to': room_data['area_to']
                }
            
            complex_dict['real_room_distribution'] = real_room_distribution
            complex_dict['room_details'] = room_details
            developer_complexes.append(complex_dict)
        
        # ✅ MIGRATED: Get developer's properties from normalized tables
        # Get real count separately (no limit) for display
        from models import Property as PropertyModel
        developer_properties_total_count = PropertyModel.query.filter_by(
            developer_id=developer.id, is_active=True
        ).count()

        # Load only a reasonable batch for display (performance)
        developer_properties_orm = PropertyRepository.get_all_active(
            limit=200,
            filters={'developer_id': developer.id},
            sort_by='price',
            sort_order='asc'
        )
        
        # Convert to old format for backward compatibility
        developer_properties = []
        for prop in developer_properties_orm:
            complex_obj = prop.residential_complex
            district_obj = prop.district
            
            # Format floor display properly: "X этаж из Y" or "Этаж не указан"
            if prop.floor and prop.total_floors:
                floor_display = f"{prop.floor} этаж из {prop.total_floors}"
            elif prop.total_floors:
                floor_display = f"Этаж не указан из {prop.total_floors}"
            else:
                floor_display = "Этаж не указан"
            
            # Extract main image from property gallery
            _main_image = prop.main_image
            if not _main_image and prop.gallery_images:
                try:
                    _imgs = json.loads(prop.gallery_images) if isinstance(prop.gallery_images, str) else prop.gallery_images
                    _main_image = _imgs[0] if _imgs and isinstance(_imgs, list) else None
                except Exception:
                    pass

            prop_dict = {
                'inner_id': prop.inner_id,
                'price': prop.price,
                'object_area': prop.area,
                'object_rooms': prop.rooms,
                'object_min_floor': prop.floor,
                'object_max_floor': prop.total_floors,
                'floor_display': floor_display,
                'complex_name': complex_obj.name if complex_obj else '',
                'developer_name': developer.name,
                'address_display_name': prop.address,
                'parsed_district': district_obj.name if district_obj else '',
                'photos': prop.gallery_images or '[]',
                'main_image': _main_image,
            }
            developer_properties.append(prop_dict)
        
        properties_count = developer_properties_total_count
        min_price = min([p['price'] for p in developer_properties if p['price']]) if developer_properties else 0
        
        # Parse features, infrastructure, and advantages if they exist
        import json as json_lib
        features = []
        infrastructure = []
        advantages = []
        
        if developer_dict.get('features'):
            try:
                features = json_lib.loads(developer_dict['features'])
            except:
                features = []
        
        if developer_dict.get('infrastructure'):
            try:
                infrastructure = json_lib.loads(developer_dict['infrastructure'])
            except:
                infrastructure = []
        
        if developer_dict.get('advantages'):
            try:
                advantages = json_lib.loads(developer_dict['advantages'])
            except:
                advantages = []
        
        # ✅ MIGRATED: Get statistics from normalized tables (properties + residential_complexes)
        from models import Property
        from sqlalchemy import func
        
        developer_stats = db.session.query(
            func.count(Property.id).label('total_properties'),
            func.avg(Property.price).label('avg_price'),
            func.min(Property.price).label('min_price'),
            func.max(Property.price).label('max_price'),
            func.count(func.distinct(Property.complex_id)).label('total_complexes')
        ).filter(
            Property.developer_id == developer.id,
            Property.is_active == True
        ).first()
        
        # Update statistics with real data from properties table
        if developer_stats and developer_stats.total_properties:
            developer_dict['properties_count'] = developer_stats.total_properties
            developer_dict['complexes_count'] = developer_stats.total_complexes
            developer_dict['min_price'] = int(developer_stats.min_price) if developer_stats.min_price else 12000000
            developer_dict['max_price'] = int(developer_stats.max_price) if developer_stats.max_price else 0
            developer_dict['avg_price'] = int(developer_stats.avg_price) if developer_stats.avg_price else 0
            print(f"DEBUG: Normalized stats for {developer.name}: min_price={developer_stats.min_price}, total_props={developer_stats.total_properties}")
        else:
            print(f"DEBUG: No properties found for {developer.name}")
        
        # Добавляем дефолтные значения для полей, которые могут отсутствовать
        developer_dict['total_projects'] = developer_dict.get('completed_projects', 0) or developer_dict.get('complexes_count', 0)
        developer_dict['rating'] = developer_dict.get('rating') or 4.2
        developer_dict['founded_year'] = developer_dict.get('founded_year') or developer_dict.get('established_year') or 2015

        # Реальные статы из таблицы residential_complexes
        from datetime import date as _date
        _this_year = _date.today().year
        _founded = developer_dict.get('founded_year') or developer_dict.get('established_year')
        developer_dict['years_on_market'] = (_this_year - int(_founded)) if _founded else None

        from models import ResidentialComplex as _RC
        _all_rc = _RC.query.filter_by(developer_id=developer.id).all()
        _active_rc  = [c for c in _all_rc if c.end_build_year and c.end_build_year >= _this_year]
        _done_rc    = [c for c in _all_rc if c.end_build_year and c.end_build_year < _this_year]
        # Суммируем корпуса (buildings_count) для строящихся
        _building_homes = sum((c.buildings_count or 1) for c in _active_rc)
        developer_dict['active_complexes_count']      = len(_active_rc) or developer_dict.get('complexes_count', 0)
        developer_dict['completed_complexes_count']   = len(_done_rc) or developer_dict.get('completed_projects', 0)
        developer_dict['under_construction_buildings'] = _building_homes or developer_dict.get('under_construction', 0)
        developer_dict['detailed_description'] = developer_dict.get('description') or 'Надёжный застройщик с многолетним опытом строительства качественного жилья в регионе.'
        developer_dict['description'] = developer_dict.get('description') or developer_dict['detailed_description']
        developer_dict['logo'] = developer_dict.get('logo_url')  # Add logo field
        developer_dict['short_name'] = developer_dict.get('name', '')[:2].upper()  # First 2 letters for fallback logo
        
        # Use advantages from DB if exists, otherwise use defaults
        if not advantages:
            advantages = [
                'Собственное строительство без субподряда',
                'Сдача объектов точно в срок', 
                'Качественные материалы и технологии',
                'Полный пакет документов и сервисов'
            ]
        developer_dict['advantages'] = advantages
        
        current_city = _resolve_city_context()
        city_slug = current_city.slug if current_city else 'krasnodar'
        return render_template('developer_detail.html', 
                             developer=developer_dict,
                             developer_name=developer_dict['name'],
                             complexes=developer_complexes,
                             apartments=developer_properties,
                             total_properties=properties_count,
                             min_price=min_price,
                             features=features,
                             infrastructure=infrastructure,
                             current_city=current_city,
                             city_slug=city_slug)
        
    except Exception as e:
        print(f"Error loading developer page for {developer_slug}: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('devs.developers_redirect'))
