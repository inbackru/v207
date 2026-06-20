"""
Public API Blueprint — Main site routes, property/map/cashback APIs
Routes: /, /api/property/*, /api/properties*, /api/residential-complexes*,
        /api/cashback/*, /api/image-proxy, /api/map/*, /api/mini-map/*,
        /api/price-history/*, /api/complex*, /quiz-registration,
        /callback-request, /api/property-selection, /switch-to-client,
        /data/properties_expanded.json, /set-demo-password, etc.
"""
import json
import io
import os
import math
import re
import logging
from datetime import datetime
from urllib.parse import unquote

import requests

from flask import (Blueprint, jsonify, request, redirect, url_for, flash,
                   render_template, session, send_file, send_from_directory,
                   current_app, make_response, g, abort)
from flask_login import current_user, login_required

from app import (db, csrf, cache, compress,
                 resolve_city_context, load_properties, load_residential_complexes,
                 load_blog_articles, load_blog_categories, load_search_data,
                 load_streets, load_developers,
                 search_global, get_article_by_slug, search_articles,
                 calculate_cashback, get_property_by_id, get_filtered_properties,
                 build_property_filters, get_developers_list, get_districts_list,
                 sort_properties, get_similar_properties,
                 _extract_first_photo,
                 manager_required, admin_required, require_json_csrf,
                 parse_address_components)
from utils.transliteration import create_slug, create_complex_slug, create_developer_slug
from seo_redirects import get_redirect_city_slug, redirect_to_city_based, get_city_slug_for_resource
import nearby_places
from repositories.property_repository import PropertyRepository, ResidentialComplexRepository
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _is_image_proxy_enabled() -> bool:
    """Check whether the image proxy is enabled. Can be toggled at runtime.
    Flag file is used as a fast cache; falls back to DB (ChatSettings) to survive restarts."""
    flag_file = '/tmp/image_proxy_disabled'
    if os.path.exists(flag_file):
        return False
    # Flag file not present — check DB as persistent source of truth
    try:
        from models import ChatSettings as _CS
        val = _CS.get('image_proxy_enabled', '1')
        if val == '0':
            # Recreate flag file so next calls are fast
            open(flag_file, 'w').close()
            return False
    except Exception:
        pass
    return os.environ.get('IMAGE_PROXY_DISABLED', '').lower() not in ('1', 'true', 'yes')

def _proxy_cian_img(url: str, crop: int = 8) -> str:
    """Wrap any external image URL through the local image-proxy endpoint.
    Hides the original source domain (e.g. cdn-cian.ru) from the browser DOM.
    Non-external URLs (relative, /static/…) are returned unchanged.
    When image proxy is disabled (admin toggle), returns the direct URL.
    """
    if not url:
        return url
    if url.startswith('/') or url.startswith('data:'):
        return url
    if not _is_image_proxy_enabled():
        return url
    from urllib.parse import quote
    return f"/api/image-proxy?url={quote(url, safe='')}&crop={crop}"

public_api_bp = Blueprint('public_api', __name__)

# In-memory cache for /api/residential-complexes-map
_complexes_map_cache = {}
_complexes_map_cache_ts = {}
COMPLEXES_MAP_CACHE_TIMEOUT = 300  # 5 minutes

@public_api_bp.route('/')
def index(city_slug=None):
    """Home page with featured content"""
    # If accessed via root URL '/', detect city and serve page directly (no redirect)
    if city_slug is None and request.path == '/':
        from seo_redirects import get_redirect_city_slug
        city_slug = get_redirect_city_slug()
    
    # Resolve city context for dynamic city display
    current_city = resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=city_slug or request.args.get('city')
    )

    # ⚡ OPTIMIZATION: Removed global load_properties() - replaced with targeted queries
    
    # ✅ MIGRATED: Load residential complexes using normalized tables
    exclusive_complexes = []
    try:
        # Get active residential complexes with property stats
        # ✅ OPTIMIZED: Filter by city in SQL instead of Python
        city_id = current_city.id if current_city else None
        complexes_orm = ResidentialComplexRepository.get_all_active(limit=500, city_id=city_id)
        
        # Get aggregated property stats for all complexes (single query, no N+1)
        # ✅ OPTIMIZED: Only load stats for complexes in current city
        property_stats = PropertyRepository.get_all_property_stats(city_id=city_id)









        
        # Build list of complexes with stats
        complexes_with_stats = []
        for complex_obj in complexes_orm:
            stats = property_stats.get(complex_obj.id, {})
            
            # Skip complexes without properties
            if not stats or stats.get('total_count', 0) == 0:
                continue
            
            # Calculate sorting keys
            end_year = complex_obj.end_build_year or 9999
            end_quarter = complex_obj.end_build_quarter or 4
            is_future = (end_year == 2025 and end_quarter == 4)
            price_from = stats.get('min_price', 0)
            
            complexes_with_stats.append({
                'complex': complex_obj,
                'stats': stats,
                'sort_future': 1 if is_future else 0,
                'sort_price': price_from
            })
        
        # Sort: complexes with photos first, then ready, then by price
        def _has_real_image(item):
            img = item['complex'].main_image or ''
            return 0 if (img and 'no-photo' not in img and 'placeholder' not in img) else 1
        complexes_with_stats.sort(key=lambda x: (_has_real_image(x), x['sort_future'], x['sort_price']))
        
        for item in complexes_with_stats[:10]:
            complex_obj = item['complex']
            stats = item['stats']
            # ✅ MIGRATED: Format complex data from ORM objects
            # Photo loading strategy: complex.main_image → complex.gallery_images → properties.sample_photos → no-photo.jpg
            photos_list = []
            main_photo = None
            
            # Try complex main_image first
            if complex_obj.main_image:
                main_photo = complex_obj.main_image
                photos_list = [main_photo]
            
            # Try complex gallery_images — ADD to photos_list, do NOT replace main_image
            if complex_obj.gallery_images:
                try:
                    photos_raw = json.loads(complex_obj.gallery_images) if isinstance(complex_obj.gallery_images, str) else complex_obj.gallery_images
                    if photos_raw and isinstance(photos_raw, list) and len(photos_raw) > 0:
                        _ph_seen = set(photos_list)
                        for _ph in photos_raw[:10]:
                            if _ph and _ph not in _ph_seen:
                                photos_list.append(_ph)
                                _ph_seen.add(_ph)
                        if not main_photo and photos_raw[0]:
                            main_photo = photos_raw[0]
                except:
                    pass
            
            # Fallback: use photos from properties
            if not photos_list or len(photos_list) == 0:
                sample_photos = stats.get('sample_photos', [])
                if sample_photos and len(sample_photos) > 0:
                    photos_list = sample_photos[:3]
                    main_photo = photos_list[0]
            
            # Final fallback: no-photo.jpg
            if not main_photo:
                main_photo = '/static/images/no-photo.svg'
            if not photos_list or len(photos_list) == 0:
                photos_list = [main_photo]
            
            # Determine completion status
            current_year = datetime.now().year
            current_quarter = (datetime.now().month - 1) // 3 + 1
            
            is_completed = False
            completion_date = 'Не указан'
            
            if complex_obj.end_build_year and complex_obj.end_build_quarter:
                build_year = int(complex_obj.end_build_year)
                build_quarter = int(complex_obj.end_build_quarter)
                
                if build_year < current_year:
                    is_completed = True
                elif build_year == current_year and build_quarter < current_quarter:
                    is_completed = True
                
                quarter_names = {1: 'I', 2: 'II', 3: 'III', 4: 'IV'}
                quarter = quarter_names.get(build_quarter, build_quarter)
                completion_date = f"{quarter} кв. {build_year} г."
            
            # Determine room types based on area range
            room_types = []
            area_from = stats.get('min_area', 0)
            area_to = stats.get('max_area', 0)
            
            if area_from and area_to:
                if area_from < 35:
                    room_types.append("Студии")
                if area_from <= 45 and area_to >= 35:
                    room_types.append("1К")
                if area_to >= 55:
                    room_types.append("2-3К")
            else:
                room_types = ["Студии", "1-3К"]
            
            room_type_display = " - ".join(room_types) if room_types else "Различные"
            
            # Safe image handling
            safe_images = photos_list if photos_list and len(photos_list) > 0 else ['/static/images/no-photo.svg']
            safe_main_image = safe_images[0] if safe_images else '/static/images/no-photo.svg'
            
            # Clean address - remove "Сочи" prefix
            clean_address = complex_obj.sales_address or stats.get('sample_address', '') or ''
            if clean_address and clean_address.startswith('Сочи, '):
                clean_address = clean_address[6:]
            elif clean_address and clean_address.startswith('г. Сочи, '):
                clean_address = clean_address[9:]
            
            # Cashback from admin panel
            cashback_percent = float(complex_obj.cashback_rate) if complex_obj.cashback_rate else 5.0
            
            # Calculate cashback amount based on max price
            max_price = stats.get('max_price', 0)
            cashback_amount = int(max_price * (cashback_percent / 100)) if max_price else 0
            
            start_completion_date = ''
            if complex_obj.start_build_year and complex_obj.start_build_quarter:
                sq_names = {1: '1', 2: '2', 3: '3', 4: '4'}
                start_completion_date = f"{sq_names.get(complex_obj.start_build_quarter, complex_obj.start_build_quarter)} кв {complex_obj.start_build_year}"

            end_completion_short = ''
            if complex_obj.end_build_year and complex_obj.end_build_quarter:
                eq_names = {1: '1', 2: '2', 3: '3', 4: '4'}
                end_completion_short = f"{eq_names.get(complex_obj.end_build_quarter, complex_obj.end_build_quarter)} кв {complex_obj.end_build_year}"

            price_per_m2 = int(stats.get('min_price', 0) / stats.get('min_area', 1)) if stats.get('min_area', 0) > 0 else 0

            _city_slug = current_city.slug if current_city else 'krasnodar'
            complex_dict = {
                'id': complex_obj.id,
                'slug': complex_obj.slug or str(complex_obj.id),
                'city_slug': _city_slug,
                'url': f'/{_city_slug}/zk/{complex_obj.slug or complex_obj.id}',
                'name': complex_obj.name or 'Без названия',
                'price_from': int(stats.get('min_price', 0)),
                'price_to': int(stats.get('max_price', 0)),
                'area_from': int(stats.get('min_area', 0)),
                'area_to': int(stats.get('max_area', 0)),
                'price_per_m2': price_per_m2,
                'room_type': room_type_display,
                'address': clean_address,
                'full_address': complex_obj.address or clean_address,
                'developer': complex_obj.developer.name if complex_obj.developer else 'Не указан',
                'photos': safe_images,
                'images': safe_images,
                'image': safe_main_image,
                'main_photo': safe_main_image,
                'main_image': safe_main_image,
                'photos_count': len(safe_images),
                'apartments_count': stats.get('total_count', 0),
                'completion_date': completion_date,
                'start_completion_date': start_completion_date,
                'end_completion_short': end_completion_short,
                'is_completed': is_completed,
                'cashback_amount': int(cashback_amount),
                'cashback_percent': float(cashback_percent),
                'cashback_max': int(cashback_amount),
                'buildings_count': stats.get('buildings_count', 1)
            }
            exclusive_complexes.append(complex_dict)
            
        print(f"✅ Загружено {len(exclusive_complexes)} эксклюзивных ЖК для главной страницы")
        
    except Exception as e:
        print(f"❌ Error loading exclusive complexes: {e}")
        import traceback
        traceback.print_exc()
        exclusive_complexes = []
    
    complexes = load_residential_complexes()  # Для совместимости со старым кодом
    # Filter by current city for hero LIVE block
    if current_city:
        city_id_val = current_city.id
        complexes = [
            c for c in complexes
            if (c.get('city_id') if isinstance(c, dict) else getattr(c, 'city_id', None)) == city_id_val
        ]
    developers_file = os.path.join('data', 'developers.json')
    with open(developers_file, 'r', encoding='utf-8') as f:
        developers = json.load(f)
    
    # Загружаем статьи блога из базы данных для главной страницы
    blog_articles = []
    try:
        from models import BlogPost
        from sqlalchemy import desc
        
        # Получаем опубликованные статьи только из BlogPost с категорией
        blog_posts = BlogPost.query.filter_by(status='published').order_by(desc(BlogPost.published_at)).limit(4).all()
        
        # Преобразуем в единый формат для шаблона
        for post in blog_posts:
            blog_articles.append({
                'title': post.title,
                'slug': post.slug,
                'excerpt': post.excerpt or 'Интересная статья о недвижимости',
                'featured_image': post.featured_image,
                'published_at': post.published_at or post.created_at,
                'reading_time': getattr(post, 'reading_time', 5),
                'category': post.category or 'Недвижимость',
                'url': f'/blog/{post.slug}'
            })
        
    except Exception as e:
        print(f"Error loading blog articles for index: {e}")
        # Fallback статьи если база недоступна
        blog_articles = [
            {
                'title': 'Ипотека мурабаха: что это и как оформить',
                'slug': 'ipoteka-murabaha',
                'excerpt': 'Ипотека мурабаха — это исламская ипотека без процентов, где банк покупает недвижимость и продает ее клиенту с наценкой.',
                'featured_image': 'https://images.unsplash.com/photo-1560518883-ce09059eeffa?ixlib=rb-4.0.3&auto=format&fit=crop&w=1000&q=80',
                'published_at': datetime.now(),
                'reading_time': 5,
                'category': 'Ипотека',
                'url': '/blog/ipoteka-murabaha'
            }
        ]
    
    # ✅ MIGRATED: Получаем 6 случайных объектов из normalized Property table
    try:
        import random
        from models import Property
        
        # Get random featured properties using PropertyRepository
        # ✅ SECURITY FIX: Always filter by city_id to prevent cross-city data leakage
        all_properties = PropertyRepository.get_all_active(
            limit=100,
            filters={
                'city_id': current_city.id if current_city else 1,
                'min_price': 1  # Only properties with price > 0
            }
        )
        
        # Filter properties with area and residential complex
        # ✅ FIX: Make gallery_images and coordinates optional
        # (city_id=1 has no coordinates, but still show properties)
        valid_properties = [
            p for p in all_properties
            if p.area and p.residential_complex
        ]
        
        # Shuffle and limit to 8 properties
        random.shuffle(valid_properties)
        result = valid_properties[:8]
        
        featured_properties = []
        for prop_orm in result:
            try:
                # Parse gallery images
                main_image = 'https://via.placeholder.com/400x300?text=Фото+скоро'
                gallery = [main_image]
                
                if prop_orm.gallery_images:
                    try:
                        photos_raw = json.loads(prop_orm.gallery_images)
                        if photos_raw and isinstance(photos_raw, list) and len(photos_raw) > 0:
                            main_image = photos_raw[0]
                            gallery = photos_raw[:5]
                    except:
                        pass
                
                # Property details
                rooms = int(prop_orm.rooms or 0)
                area = float(prop_orm.area or 0)
                price = int(prop_orm.price or 0)
                
                # Floor info
                floor_min = int(prop_orm.floor or 1)
                floor_max = int(prop_orm.total_floors or floor_min)
                floor_text = f"{floor_min}/{floor_max} эт."
                
                # Room type
                room_type = "Студия" if rooms == 0 else f"{rooms}-комн"
                
                # Completion date and status
                current_year = datetime.now().year
                build_quarter = prop_orm.residential_complex.end_build_quarter if prop_orm.residential_complex else None
                build_year = prop_orm.residential_complex.end_build_year if prop_orm.residential_complex else None
                
                if build_year and build_quarter:
                    quarter_text = f"{build_quarter}кв. {build_year}г."
                    status_text = "Сдан" if build_year < current_year or (build_year == current_year and build_quarter <= 1) else "Строится"
                else:
                    quarter_text = "Уточняется"
                    status_text = "Строится"
                
                # Get complex info
                complex_obj = prop_orm.residential_complex
                lat = float(prop_orm.latitude) if prop_orm.latitude else None
                lng = float(prop_orm.longitude) if prop_orm.longitude else None
                
                # Build property dict
                prop = {
                    'id': prop_orm.inner_id or str(prop_orm.id),
                    'price': price,
                    'area': area,
                    'rooms': rooms,
                    'title': f"{room_type}, {area} м², {floor_text}",
                    'complex': complex_obj.name if complex_obj else 'ЖК не указан',
                    'developer': prop_orm.developer.name if prop_orm.developer else '',
                    'address': prop_orm.address or '',
                    'image': main_image,
                    'gallery': gallery,
                    'cashback': int(price * 0.02),
                    'cashback_amount': int(price * 0.02),
                    'completion_date': quarter_text,
                    'deal_type': prop_orm.deal_type if hasattr(prop_orm, 'deal_type') else 'sale',
                    'complex_building_status': getattr(complex_obj, 'status', None) if complex_obj else None,
                    'complex_building_end_build_year': getattr(complex_obj, 'end_build_year', None) if complex_obj else None,
                    'cashback': int((price or 0) * (float(complex_obj.cashback_rate or 3.5) / 100)) if complex_obj else int((price or 0) * 0.035),
                    'cashback_rate': float(complex_obj.cashback_rate) if complex_obj and complex_obj.cashback_rate else 3.5,
                    'latitude': lat,
                    'longitude': lng,
                    'complex_name': complex_obj.name if complex_obj else '',
                    'floor_info': floor_text
                }
                featured_properties.append(prop)
                if len(featured_properties) >= 6:
                    break
                
            except Exception as e:
                prop_id = getattr(prop_orm, "id", "unknown"); print(f"Error processing property {prop_id}: {e}")
                continue
        
        if featured_properties:
            print(f"✅ Загружено {len(featured_properties)} реальных объектов из базы")
        else:
            raise Exception("No properties loaded")
            
    except Exception as e:
        print(f"❌ Ошибка загрузки реальных объектов: {e}")
        # Fallback к старым данным
        # ⚡ OPTIMIZATION: Direct query instead of loading all properties
        fallback_props = PropertyRepository.get_all_active(limit=6, sort_by='price', sort_order='desc')
        featured_properties = []
        for prop_orm in fallback_props:
            price = prop_orm.price or 0
            featured_properties.append({
                'price': price,
                'cashback_amount': int(price * 0.02),
                'complex_id': prop_orm.complex_id,
                'residential_complex': prop_orm.residential_complex.name if prop_orm.residential_complex else ''
            })
        for prop in featured_properties:
            prop['cashback'] = calculate_cashback(
                prop['price'],
                complex_id=prop.get('complex_id'),
                complex_name=prop.get('residential_complex')
            )
    
    # Get districts with statistics
    districts_data = {}
    for complex in complexes:
        district = complex['district']
        if district not in districts_data:
            districts_data[district] = {
                'name': district,
                'complexes_count': 0,
                'price_from': float('inf'),
                'apartments_count': 0
            }
        districts_data[district]['complexes_count'] += 1
        complex_price = complex.get('price_from') or 0
        if complex_price > 0:  # Only update if we have a valid price
            districts_data[district]['price_from'] = min(districts_data[district]['price_from'], complex_price)
        districts_data[district]['apartments_count'] += complex.get('apartments_count', 0) or 0
    
    districts = sorted(districts_data.values(), key=lambda x: x['complexes_count'], reverse=True)[:8]
    
    # Get featured developers (top 3 with most complexes)
    featured_developers = []
    for developer in developers[:3]:
        developer_complexes = [c for c in complexes if c.get('developer_id') == developer['id']]
        # ⚡ OPTIMIZATION: Direct query by developer_id instead of loading all properties
        complex_ids = [c['id'] for c in developer_complexes]
        developer_properties_count = Property.query.filter(Property.complex_id.in_(complex_ids)).count() if complex_ids else 0
        
        # ⚡ Safe query for price_from - prevents AttributeError if no properties found
        first_prop = Property.query.filter(Property.complex_id.in_(complex_ids), Property.price > 0).order_by(Property.price).first() if complex_ids else None
        
        developer_info = {
            'id': developer['id'],
            'name': developer['name'],
            'complexes_count': len(developer_complexes),
            'apartments_count': developer_properties_count,
            'price_from': first_prop.price if first_prop else 0,
            'max_cashback': max([c.get('cashback_percent', 5) for c in developer_complexes]) if developer_complexes else 5
        }
        featured_developers.append(developer_info)
    
    # Загружаем категории блога для главной страницы
    blog_categories = []
    try:
        from models import Category
        blog_categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order, Category.name).all()
    except Exception as e:
        print(f"Error loading blog categories for index: {e}")
    
    
    managers = []
    manager_online_status = {}
    try:
        from models import Manager, ManagerCheckin
        managers = Manager.query.filter_by(is_active=True, show_on_index=True).limit(8).all()
        from zoneinfo import ZoneInfo
        now_moscow = datetime.now(ZoneInfo('Europe/Moscow'))
        today_start = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
        for mgr in managers:
            checkin = ManagerCheckin.query.filter(
                ManagerCheckin.manager_id == mgr.id,
                ManagerCheckin.check_in_time >= today_start.replace(tzinfo=None)
            ).order_by(ManagerCheckin.check_in_time.desc()).first()
            manager_online_status[mgr.id] = checkin is not None and checkin.check_out_time is None
    except Exception as e:
        print(f"Error loading managers for index: {e}")
        db.session.rollback()
    
    # Загружаем застройщиков с активными объектами в текущем городе для бегущей строки
    city_developers = []
    try:
        from models import Developer, Property
        from sqlalchemy import func, distinct
        
        city_id = current_city.id if current_city else 1
        
        # Получаем застройщиков с количеством активных объектов в текущем городе
        developers_with_counts = db.session.query(
            Developer,
            func.count(distinct(Property.id)).label('property_count')
        ).join(
            Property, Property.developer_id == Developer.id
        ).filter(
            Property.city_id == city_id,
            Property.is_active == True,
            Developer.is_active == True
        ).group_by(
            Developer.id
        ).order_by(
            func.count(distinct(Property.id)).desc()
        ).limit(15).all()
        
        city_developers = [dev for dev, count in developers_with_counts]
        print(f"✅ Загружено {len(city_developers)} застройщиков для города {city_id}")
    except Exception as e:
        print(f"Error loading developers for index: {e}")
    
    recommended_properties = []
    recommendation_title = "Рекомендации для вас"
    try:
        from flask_login import current_user as cu
        city_id = current_city.id if current_city else 1
        
        if cu.is_authenticated:
            target_rooms = None
            target_min_price = None
            target_max_price = None
            target_complex_ids = []
            
            if hasattr(cu, 'budget_range') and cu.budget_range:
                budget_map = {
                    'до 3 млн': (0, 3000000),
                    '3-5 млн': (3000000, 5000000),
                    '5-7 млн': (5000000, 7000000),
                    '7-10 млн': (7000000, 10000000),
                    'от 10 млн': (10000000, 999999999),
                }
                for key, (lo, hi) in budget_map.items():
                    if key in cu.budget_range:
                        target_min_price = lo
                        target_max_price = hi
                        break
            
            if hasattr(cu, 'room_count') and cu.room_count:
                try:
                    target_rooms = int(cu.room_count.replace('-комн', '').replace('комн', '').strip())
                except:
                    if 'студи' in cu.room_count.lower():
                        target_rooms = 0
            
            try:
                from models import FavoriteComplex as _FavComplex
                fav_complexes = _FavComplex.query.filter_by(user_id=cu.id).order_by(_FavComplex.created_at.desc()).limit(5).all() if hasattr(cu, 'favorite_complexes') else []
            except Exception:
                fav_complexes = []
            for fc in fav_complexes:
                if fc.complex_id:
                    try:
                        target_complex_ids.append(int(fc.complex_id))
                    except:
                        pass
            
            from models import FavoriteProperty as FP_model; fav_props = FP_model.query.filter_by(user_id=cu.id).order_by(FP_model.created_at.desc()).limit(10).all() if hasattr(cu, 'favorite_properties') else []
            if fav_props and not target_min_price:
                prices = [fp.property_price for fp in fav_props if fp.property_price]
                if prices:
                    avg_price = sum(prices) / len(prices)
                    target_min_price = int(avg_price * 0.7)
                    target_max_price = int(avg_price * 1.3)
            
            rec_query = Property.query.filter(Property.city_id == city_id, Property.is_active == True, Property.price > 0)
            
            if target_complex_ids:
                complex_matches = Property.query.filter(
                    Property.city_id == city_id, Property.is_active == True, Property.price > 0,
                    Property.complex_id.in_(target_complex_ids)
                ).limit(6).all()
                if complex_matches:
                    recommendation_title = "Подобрано для вас"
                    rec_query = Property.query.filter(
                        Property.city_id == city_id, Property.is_active == True, Property.price > 0,
                        Property.complex_id.in_(target_complex_ids)
                    )
            
            if target_rooms is not None:
                rec_query = rec_query.filter(Property.rooms == target_rooms)
                recommendation_title = "Подобрано для вас"
            
            if target_min_price and target_max_price:
                rec_query = rec_query.filter(Property.price >= target_min_price, Property.price <= target_max_price)
                recommendation_title = "Подобрано для вас"
            
            rec_results = rec_query.order_by(db.func.random()).limit(6).all()
            
            if len(rec_results) < 3:
                rec_results = Property.query.filter(
                    Property.city_id == city_id, Property.is_active == True, Property.price > 0
                ).order_by(db.func.random()).limit(6).all()
                recommendation_title = "Может вас заинтересовать"
        else:
            rec_results = Property.query.filter(
                Property.city_id == city_id, Property.is_active == True, Property.price > 0
            ).order_by(Property.created_at.desc()).limit(6).all()
            recommendation_title = "Популярные предложения"
        
        for prop_orm in rec_results:
            try:
                main_image = '/static/images/no-photo.svg'
                gallery = [main_image]
                if prop_orm.gallery_images:
                    try:
                        photos_raw = json.loads(prop_orm.gallery_images)
                        if photos_raw and isinstance(photos_raw, list) and len(photos_raw) > 0:
                            main_image = photos_raw[0]
                            gallery = photos_raw[:3]
                    except:
                        pass
                
                rooms = int(prop_orm.rooms or 0)
                area = float(prop_orm.area or 0)
                price = int(prop_orm.price or 0)
                floor_min = int(prop_orm.floor or 1)
                floor_max = int(prop_orm.total_floors or floor_min)
                room_type = "Студия" if rooms == 0 else f"{rooms}-комн"
                complex_obj = prop_orm.residential_complex
                cashback_rate = float(complex_obj.cashback_rate) if complex_obj and complex_obj.cashback_rate else 3.5
                
                recommended_properties.append({
                    'id': prop_orm.inner_id or str(prop_orm.id),
                    'price': price,
                    'area': area,
                    'rooms': rooms,
                    'title': f"{room_type}, {area} м²",
                    'complex': complex_obj.name if complex_obj else '',
                    'developer': prop_orm.developer.name if prop_orm.developer else '',
                    'address': prop_orm.address or '',
                    'image': main_image,
                    'gallery': gallery,
                    'cashback': int(price * (cashback_rate / 100)),
                    'cashback_rate': cashback_rate,
                    'floor_info': f"{floor_min}/{floor_max} эт.",
                })
            except Exception as e:
                continue
        
        print(f"✅ Загружено {len(recommended_properties)} рекомендаций для главной")
    except Exception as e:
        print(f"Error loading recommendations: {e}")
        import traceback
        traceback.print_exc()
    
    return render_template('index.html', 
                               current_city=current_city,
                               featured_properties=featured_properties,
                               districts=districts,
                               featured_developers=featured_developers,
                               city_developers=city_developers,
                               residential_complexes=exclusive_complexes[:10],
                               exclusive_complexes=exclusive_complexes,
                               blog_articles=blog_articles,
                               blog_categories=blog_categories,
                               managers=managers,
                               manager_online_status=manager_online_status,
                               recommended_properties=recommended_properties,
                               recommendation_title=recommendation_title)

def _render_streets_page(current_city):
    """Internal streets rendering logic"""
    # Эта страница только для Краснодара (создана для SEO)
    # Данные пока только для Краснодара
    streets_data = []
    if not current_city or current_city.slug != 'krasnodar':
        # Для других городов показываем пустую заглушку
        return render_template('streets.html', current_city=current_city, streets=[])
    
    # Load streets from database with slugs
    streets_db = db.session.execute(text("""
        SELECT name, slug, district_id 
        FROM streets 
        ORDER BY name
    """)).fetchall()
    
    # Get district names
    districts_db = db.session.execute(text("""
        SELECT id, name FROM districts
    """)).fetchall()
    districts_map = {d.id: d.name for d in districts_db}
    
    # Format streets data
    streets_data = []
    for street in streets_db:
        # Get first letter for grouping
        first_char = street.name[0].upper() if street.name else 'А'
        
        streets_data.append({
            'name': street.name,
            'slug': street.slug,  # Use slug from database
            'district': districts_map.get(street.district_id, ''),
            'letter': first_char,
            'properties_count': 0,  # Can be calculated if needed
            'new_buildings': 0  # Can be calculated if needed
        })
    
    return render_template('streets.html', 
                             current_city=current_city,
                         streets=streets_data)

# Redirect from /streets/<street_name> to /street/<slug>
@public_api_bp.route('/api/property/<int:property_id>')
def api_property_detail(property_id):
    """API endpoint to get property data for comparison"""
    property_data = get_property_by_id(property_id)
    
    if not property_data:
        return jsonify({'error': 'Property not found'}), 404
    
    
    # Use cashback_rate from excel_properties (already loaded in property_data)
    cashback_rate = property_data.get('cashback_rate', 5.0)
    
    # Calculate cashback amount using the actual cashback_rate from database
    if property_data.get('price'):
        property_data['cashback'] = round(property_data['price'] * cashback_rate / 100)
    else:
        property_data['cashback'] = 0
    
    # Add fields expected by comparison interface
    property_data['object_min_floor'] = property_data.get('floor')
    property_data['object_max_floor'] = property_data.get('total_floors')
    property_data['complex_name'] = property_data.get('residential_complex')
    
    return jsonify(property_data)

@public_api_bp.route('/api/property/<int:property_id>/request-cashback', methods=['POST'])
@require_json_csrf
def api_property_request_cashback(property_id):
    """Handle cashback request for a property"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'phone', 'email']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Поле {field} обязательно'}), 400
        
        # Get property data
        property_data = get_property_by_id(property_id)
        if not property_data:
            return jsonify({'error': 'Объект не найден'}), 404
        
        # Prepare notification data
        name = data.get('name')
        phone = data.get('phone')
        email = data.get('email')
        property_title = data.get('property_title', property_data.get('title', 'Объект'))
        property_address = data.get('property_address', property_data.get('address', ''))
        property_price = data.get('property_price', property_data.get('price', 0))
        
        # Send email notification
        try:
            from email_service import send_email
            
            email_subject = f"Заявка на кэшбек - {property_title}"
            email_content = f"""
            <h2>Новая заявка на получение кэшбека</h2>
            <p><strong>Клиент:</strong> {name}</p>
            <p><strong>Телефон:</strong> {phone}</p>
            <p><strong>Email:</strong> {email}</p>
            <hr>
            <p><strong>Объект:</strong> {property_title}</p>
            <p><strong>Адрес:</strong> {property_address}</p>
            <p><strong>Цена:</strong> {property_price:,.0f} ₽</p>
            <p><strong>ID объекта:</strong> {property_id}</p>
            """
            
            send_email(
                to_email='bithome@mail.ru',
                subject=email_subject,
                template_name='emails/general_notification.html',
                message=email_content,
                title=email_subject
            )
        except Exception as e:
            print(f"Error sending email: {e}")
        
        # Send Telegram notification
        try:
            import requests
            TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
            TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
            
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                telegram_message = f"""💰 <b>Заявка на кэшбек</b>

👤 Клиент: {name}
📞 Телефон: {phone}
📧 Email: {email}

🏠 Объект: {property_title}
📍 Адрес: {property_address}
💵 Цена: {property_price:,.0f} ₽
🆔 ID: {property_id}"""
                
                telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                telegram_payload = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'text': telegram_message,
                    'parse_mode': 'HTML'
                }
                
                requests.post(telegram_url, data=telegram_payload, timeout=10)
        except Exception as e:
            print(f"Error sending Telegram notification: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Заявка успешно отправлена'
        })
        
    except Exception as e:
        print(f"Error in cashback request: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Ошибка сервера'}), 500


@public_api_bp.route('/api/property/<int:property_id>/request-online-showing', methods=['POST'])
@require_json_csrf
def api_property_request_online_showing(property_id):
    """Handle online showing request for a property"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'phone', 'email', 'datetime']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Поле {field} обязательно'}), 400
        
        # Get property data
        property_data = get_property_by_id(property_id)
        if not property_data:
            return jsonify({'error': 'Объект не найден'}), 404
        
        # Prepare notification data
        name = data.get('name')
        phone = data.get('phone')
        email = data.get('email')
        showing_datetime = data.get('datetime')
        property_title = data.get('property_title', property_data.get('title', 'Объект'))
        property_address = data.get('property_address', property_data.get('address', ''))
        property_price = data.get('property_price', property_data.get('price', 0))
        
        # Parse datetime for better display
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(showing_datetime.replace('Z', '+00:00'))
            showing_datetime_formatted = dt.strftime('%d.%m.%Y в %H:%M')
        except:
            showing_datetime_formatted = showing_datetime
        
        # Send email notification
        try:
            from email_service import send_email
            
            email_subject = f"Заявка на онлайн показ - {property_title}"
            email_content = f"""
            <h2>Новая заявка на онлайн показ</h2>
            <p><strong>Клиент:</strong> {name}</p>
            <p><strong>Телефон:</strong> {phone}</p>
            <p><strong>Email:</strong> {email}</p>
            <p><strong>Желаемое время:</strong> {showing_datetime_formatted}</p>
            <hr>
            <p><strong>Объект:</strong> {property_title}</p>
            <p><strong>Адрес:</strong> {property_address}</p>
            <p><strong>Цена:</strong> {property_price:,.0f} ₽</p>
            <p><strong>ID объекта:</strong> {property_id}</p>
            """
            
            send_email(
                to_email='bithome@mail.ru',
                subject=email_subject,
                template_name='emails/general_notification.html',
                message=email_content,
                title=email_subject
            )
        except Exception as e:
            print(f"Error sending email: {e}")
        
        # Send Telegram notification
        try:
            import requests
            TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
            TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
            
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                telegram_message = f"""🏠 <b>Заявка на онлайн показ</b>

👤 Клиент: {name}
📞 Телефон: {phone}
📧 Email: {email}
🕐 Желаемое время: {showing_datetime_formatted}

🏠 Объект: {property_title}
📍 Адрес: {property_address}
💵 Цена: {property_price:,.0f} ₽
🆔 ID: {property_id}"""
                
                telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                telegram_payload = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'text': telegram_message,
                    'parse_mode': 'HTML'
                }
                
                requests.post(telegram_url, data=telegram_payload, timeout=10)
        except Exception as e:
            print(f"Error sending Telegram notification: {e}")
        
        try:
            complex_name_str = property_data.get('complex_name', 'Не указан')
            deal, _ = create_deal_from_website_form(
                name=name,
                phone=phone,
                email=email,
                source='Онлайн показ',
                complex_name=complex_name_str,
                property_price=float(property_price) if property_price else 0,
                notes=f"Онлайн показ на {showing_datetime_formatted}; Объект: {property_title}"
            )
            db.session.commit()
            if deal:
                print(f"✅ Deal {deal.deal_number} created from online showing for {name}")
        except Exception as deal_err:
            print(f"Error creating deal from online showing: {deal_err}")
        
        return jsonify({
            'success': True,
            'message': 'Заявка успешно отправлена'
        })
        
    except Exception as e:
        print(f"Error in online showing request: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Ошибка сервера'}), 500



@require_json_csrf
@public_api_bp.route('/api/properties/batch', methods=['POST'])
def api_properties_batch():
    """Batch API endpoint to get multiple properties at once - OPTIMIZED"""
    try:
        data = request.get_json()
        property_ids = data.get('ids', [])
        
        if not property_ids or not isinstance(property_ids, list):
            return jsonify({'error': 'Invalid request, expected {"ids": [1, 2, 3]}'}), 400
        
        # Convert string IDs to integers
        try:
            property_ids = [int(pid) for pid in property_ids if pid]
        except (ValueError, TypeError) as e:
            return jsonify({'error': f'Invalid ID format: {str(e)}'}), 400
        
        # ✅ SINGLE QUERY: Load all properties at once using bulk repository method
        properties_dict = PropertyRepository.get_by_ids_batch(property_ids)
        
        results = {}
        for property_id in property_ids:
            prop = properties_dict.get(property_id)
            if prop:
                # Convert ORM object to dict (same format as get_property_by_id)
                property_data = {
                    'id': prop.id,
                    'inner_id': prop.inner_id,
                    'title': prop.title,
                    'price': prop.price,
                    'rooms': prop.rooms,
                    'area': prop.area,
                    'floor': prop.floor,
                    'total_floors': prop.total_floors,
                    'main_image': prop.main_image,
                    'gallery_images': prop.gallery_images,
                    'residential_complex': prop.residential_complex.name if prop.residential_complex else 'Не указано',
                    'developer': prop.developer.name if prop.developer else 'Не указано',
                    'district': prop.district.name if prop.district else 'Не указано',
                    'address': prop.address,
                    'cashback_rate': prop.residential_complex.cashback_rate if prop.residential_complex else 5.0,
                    'latitude': prop.latitude,
                    'longitude': prop.longitude,
                }
                
                # Add cashback calculation
                cashback_rate = property_data.get('cashback_rate', 5.0)
                if property_data.get('price'):
                    property_data['cashback'] = round(property_data['price'] * cashback_rate / 100)
                else:
                    property_data['cashback'] = 0
                
                # Add comparison fields
                property_data['object_min_floor'] = property_data.get('floor')
                property_data['object_max_floor'] = property_data.get('total_floors')
                property_data['complex_name'] = property_data.get('residential_complex')
                
                results[str(property_id)] = property_data
        
        return jsonify({'success': True, 'items': results})
    except Exception as e:
        print(f"❌ Error in batch properties: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@public_api_bp.route('/api/residential-complexes')
def api_residential_complexes():
    """API endpoint for getting residential complexes for cashback calculator using normalized tables"""
    from repositories.property_repository import ResidentialComplexRepository, PropertyRepository
    
    try:
        # Resolve city context for filtering
        city_context = resolve_city_context(
            city_id=request.args.get('city_id'),
            city_slug=request.args.get('city'),
            default_if_none=True
        )
        city_name = city_context.name if city_context else 'Краснодар'
        city_id_filter = city_context.id if city_context else None
        complexes = ResidentialComplexRepository.get_all_active() if not city_id_filter else [
            c for c in ResidentialComplexRepository.get_all_active() 
            if c.city_id == city_id_filter
        ]
        all_stats = PropertyRepository.get_all_property_stats()
        
        api_complexes = []
        for complex in complexes:
            cashback_rate = complex.cashback_rate if complex.cashback_rate else 5.0
            stats = all_stats.get(complex.id, {'min_price': 0})
            
            api_complexes.append({
                'id': complex.id,
                'name': complex.name,
                'cashback_rate': cashback_rate,
                'price_from': stats['min_price'],
                'district': complex.district or (city_context.name if 'city_context' in locals() else 'Краснодар')
            })
        
        print(f"API residential-complexes loaded from database: {len(api_complexes)} complexes")
        return jsonify({'complexes': api_complexes})
    
    except Exception as e:
        # Load all residential complexes from JSON data
        try:
            complexes = load_residential_complexes()
            api_complexes = []
            
            for complex in complexes:
                # Extract unique name and calculate cashback rate
                complex_name = complex.get('name', 'Неизвестный ЖК')
                cashback_rate = 5.0  # Default rate
                
                # Try to get rate from complex data or calculate based on price
                if 'cashback_rate' in complex:
                    cashback_rate = float(complex['cashback_rate'])
                elif complex.get('real_price_from'):
                    # Calculate rate based on price range (higher price = lower rate)
                    price = complex.get('real_price_from', 5000000)
                    if price < 3000000:
                        cashback_rate = 5.0
                    elif price < 8000000:
                        cashback_rate = 4.5
                    else:
                        cashback_rate = 4.0
                
                api_complexes.append({
                    'id': complex.get('id', len(api_complexes) + 1),
                    'name': complex_name,
                    'cashback_rate': cashback_rate,
                    'price_from': complex.get('real_price_from'),
                    'district': complex.get('district', city_context.name if 'city_context' in locals() else 'Краснодар')
                })
            
            # Remove duplicates by name
            unique_complexes = {}
            for complex in api_complexes:
                name = complex['name']
                if name not in unique_complexes:
                    unique_complexes[name] = complex
            
            return jsonify({'complexes': list(unique_complexes.values())})
        
        except Exception as json_error:
            print(f"Error loading JSON complexes: {json_error}")
            # Final fallback to simple list
            return jsonify({
                'complexes': [
                    {'id': 1, 'name': 'ЖК «Летний»', 'cashback_rate': 5.0},
                    {'id': 2, 'name': 'ЖК «Чайные холмы»', 'cashback_rate': 4.5},
                    {'id': 3, 'name': 'ЖК «Кислород»', 'cashback_rate': 5.0},
                    {'id': 4, 'name': 'ЖК «Гранд Каскад»', 'cashback_rate': 4.0}
                ]
            })

@public_api_bp.route('/api/hero-complexes')
def api_hero_complexes():
    """Returns a short list of complexes for the hero LIVE block, filtered by city."""
    from repositories.property_repository import ResidentialComplexRepository
    try:
        city_id_param = request.args.get('city_id')
        city_slug_param = request.args.get('city_slug')
        city_context = resolve_city_context(
            city_id=city_id_param,
            city_slug=city_slug_param,
            default_if_none=True
        )
        city_id_filter = city_context.id if city_context else None
        all_complexes = ResidentialComplexRepository.get_all_active()
        if city_id_filter:
            all_complexes = [c for c in all_complexes if c.city_id == city_id_filter]
        import random
        sample = random.sample(all_complexes, min(10, len(all_complexes)))
        result = []
        for c in sample:
            img = ''
            if c.gallery_images:
                try:
                    imgs = json.loads(c.gallery_images) if isinstance(c.gallery_images, str) else c.gallery_images
                    if imgs and isinstance(imgs, list):
                        img = imgs[0]
                except Exception:
                    pass
            if not img and c.main_image:
                img = c.main_image
            result.append({'name': c.name, 'img': img})
        return jsonify({'complexes': result})
    except Exception as e:
        return jsonify({'complexes': [], 'error': str(e)})

@public_api_bp.route('/api/residential-complexes-full')
def api_residential_complexes_full():
    """API endpoint for getting all residential complexes using normalized tables"""
    from repositories.property_repository import ResidentialComplexRepository
    
    try:
        city_id_filter = request.args.get('city_id', type=int)
        city_context = resolve_city_context(city_id=city_id_filter)
        complexes = ResidentialComplexRepository.get_all_active() if not city_id_filter else [
            c for c in ResidentialComplexRepository.get_all_active() 
            if c.city_id == city_id_filter
        ]
        all_stats = PropertyRepository.get_all_property_stats()
        
        complexes_data = []
        for complex in complexes:
            stats = all_stats.get(complex.id, {
                'min_price': 0,
                'max_price': 0,
                'total_properties': 0
            })
            
            complex_dict = {
                'id': complex.id,
                'name': complex.name,
                'cashback_rate': complex.cashback_rate if complex.cashback_rate else 5.0,
                'district': complex.district or (city_context.name if city_context else 'Краснодар'),
                'address': complex.address or 'Адрес не указан',
                'developer': complex.developer.name if complex.developer else 'Не указан',
                'min_price': stats['min_price'],
                'max_price': stats['max_price'],
                'real_price_from': stats['min_price'],
                'real_price_to': stats['max_price'],
                'available_apartments': stats['total_properties']
            }
            complexes_data.append(complex_dict)
        
        return jsonify({'complexes': complexes_data})
    except Exception as e:
        print(f"Error loading residential complexes: {e}")
        return jsonify({'complexes': []}), 500

@public_api_bp.route('/api/cashback/calculate', methods=['POST'])
# @csrf.exempt  # CSRF disabled  # Disable CSRF for API endpoint
def api_calculate_cashback():
    """API endpoint for calculating cashback"""
    try:
        data = request.get_json()
        price = float(data.get('price', 0))
        complex_id = data.get('complex_id')
        
        if not price or price <= 0:
            return jsonify({'error': 'Invalid price'}), 400
        
        # Get cashback rate from database
        cashback_rate = 5.0  # default
        
        if complex_id:
            try:
                # Ищем комплекс в JSON данных
                import json
                import os
                
                residential_complexes_file = 'static/data/residential_complexes.json'
                if os.path.exists(residential_complexes_file):
                    with open(residential_complexes_file, 'r', encoding='utf-8') as file:
                        json_complexes = json.load(file)
                    
                    for complex in json_complexes:
                        if str(complex.get('id')) == str(complex_id):
                            if 'cashback_rate' in complex:
                                cashback_rate = float(complex['cashback_rate'])
                            elif complex.get('real_price_from'):
                                # Calculate rate based on price range
                                complex_price = complex.get('real_price_from', 5000000)
                                if complex_price < 3000000:
                                    cashback_rate = 5.0
                                elif complex_price < 8000000:
                                    cashback_rate = 4.5
                                else:
                                    cashback_rate = 4.0
                            break
                            
                # Если не нашли в JSON, используем fallback ставки по ID
            except:
                # Fallback rates
                complex_rates = {
                    1: 5.5, 2: 6.0, 3: 7.0, 4: 5.0,
                    5: 6.5, 6: 5.5, 7: 7.5, 8: 8.0
                }
                cashback_rate = complex_rates.get(int(complex_id), 5.0)
        
        cashback_amount = price * (cashback_rate / 100)
        
        # Cap at maximum
        max_cashback = 500000
        if cashback_amount > max_cashback:
            cashback_amount = max_cashback
        
        return jsonify({
            'cashback_amount': int(cashback_amount),
            'cashback_rate': cashback_rate,
            'price': int(price),
            'formatted_amount': f"{int(cashback_amount):,}".replace(',', ' ')
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@public_api_bp.route('/api/cashback/apply', methods=['POST'])
@login_required
# @csrf.exempt  # CSRF disabled  # Disable CSRF for API endpoint
def api_apply_cashback():
    """API endpoint for submitting cashback application"""
    try:
        from models import CashbackApplication, UserActivity, CallbackRequest
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Неверный формат данных'}), 400
            
        price = data.get('price')
        complex_id = data.get('complex_id')  # Может быть null для калькулятора
        complex_name = data.get('complex_name', 'Не указан')
        cashback_amount = data.get('cashback_amount')
        cashback_rate = data.get('cashback_rate', 2.5)
        user_phone = data.get('phone', '')
        user_name = data.get('name', '')
        
        # Validate required fields (complex_id опционален)
        if not all([price, cashback_amount, user_phone, user_name]):
            return jsonify({'error': 'Заполните все обязательные поля'}), 400
        
        # Validate data types
        try:
            price = float(price)
            cashback_amount = float(cashback_amount)
            cashback_rate = float(cashback_rate)
        except (ValueError, TypeError):
            return jsonify({'error': 'Неверный формат числовых данных'}), 400
        
        # Create cashback application
        cashback_app = CashbackApplication(
            user_id=current_user.id,
            property_name=f"Квартира в {complex_name}",
            property_type="Квартира",
            property_size=50.0,  # Default size, can be improved later
            property_price=int(price),
            complex_name=complex_name,
            developer_name=data.get('developer_name', 'Не указан'),
            cashback_amount=int(cashback_amount),
            cashback_percent=cashback_rate,
            status='В обработке'
        )
        
        db.session.add(cashback_app)
        
        # Record user activity
        UserActivity.log_activity(
            user_id=current_user.id,
            activity_type='cashback_application',
            description=f'Подана заявка на кешбек {int(cashback_amount):,} ₽ по объекту в {complex_name}'.replace(',', ' '),
            complex_id=complex_id
        )
        
        callback = CallbackRequest(
            name=user_name,
            phone=user_phone,
            notes=f"Заявка на кешбек {int(cashback_amount):,} ₽ при покупке квартиры в {complex_name} стоимостью {int(price):,} ₽".replace(',', ' ')
        )
        
        db.session.add(callback)
        
        deal, _ = create_deal_from_website_form(
            name=user_name,
            phone=user_phone,
            source='Заявка на кешбек',
            complex_name=complex_name,
            property_price=price,
            cashback_amount=cashback_amount,
            notes=f"Кешбек {int(cashback_amount):,} ₽ ({cashback_rate}%)".replace(',', ' ')
        )
        
        db.session.commit()
        
        if deal:
            print(f"✅ Deal {deal.deal_number} created from cashback application for {user_name}")
        
        # ── Прямое Telegram-уведомление с деталями заявки ──────────────────
        try:
            TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
            TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                property_id_str = data.get('property_id', '')
                tg_lines = [
                    "🏠 *НОВАЯ ЗАЯВКА НА КЭШБЕК*",
                    "",
                    f"👤 Клиент: {user_name}",
                    f"📞 Телефон: {user_phone}",
                    f"🏢 ЖК: {complex_name}",
                    f"💰 Стоимость: {int(price):,} ₽".replace(',', ' '),
                    f"🎁 Кэшбек: {int(cashback_amount):,} ₽ ({cashback_rate}%)".replace(',', ' '),
                ]
                if property_id_str:
                    tg_lines.append(f"🔗 Объект: https://inback.ru/object/{property_id_str}")
                if deal:
                    tg_lines.append(f"📋 Сделка: #{deal.deal_number}")
                tg_msg = "\n".join(tg_lines)
                import requests as _req_tg
                _req_tg.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={'chat_id': TELEGRAM_CHAT_ID, 'text': tg_msg, 'parse_mode': 'Markdown'},
                    timeout=5
                )
        except Exception as tg_err:
            print(f"⚠️ Telegram cashback notify error: {tg_err}")
        
        return jsonify({
            'success': True,
            'message': 'Заявка успешно отправлена! Менеджер свяжется с вами в ближайшее время.'
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Ошибка при отправке заявки: {str(e)}'}), 500

def crop_watermark(image_url, crop_bottom_percent=8):
    """Download image from URL and crop bottom watermark strip. Returns PIL Image or None."""
    try:
        from PIL import Image
        response = requests.get(
            image_url, timeout=10,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content))
        width, height = img.size
        crop_height = int(height * (crop_bottom_percent / 100))
        return img.crop((0, 0, width, height - crop_height))
    except Exception as e:
        current_app.logger.debug(f"crop_watermark failed for {image_url}: {e}")
        return None


@public_api_bp.route('/api/image-proxy')
def image_proxy():
    """
    Proxy endpoint to serve images with watermark cropped out.
    Accepts ?b=<base64url-encoded-url> (preferred, hides origin) or legacy ?url=<url>.
    Caches processed images to /tmp/img_cache/ to avoid re-downloading.
    """
    import base64
    import hashlib

    # Resolve URL — prefer base64 param to hide origin URL
    b_param = request.args.get('b')
    if b_param:
        try:
            image_url = base64.urlsafe_b64decode(b_param.encode('ascii') + b'==').decode('utf-8')
        except Exception:
            return jsonify({'error': 'Invalid image reference'}), 400
    else:
        image_url = request.args.get('url')

    if not image_url:
        return jsonify({'error': 'No image URL provided'}), 400

    crop_percent = request.args.get('crop', '8')
    try:
        crop_percent = int(crop_percent)
    except (ValueError, TypeError):
        crop_percent = 8

    # Build a disk-cache path so we never re-download the same image
    cache_dir = '/tmp/img_cache'
    os.makedirs(cache_dir, exist_ok=True)
    cache_key = hashlib.md5(f"{image_url}:{crop_percent}".encode()).hexdigest()
    cache_path = os.path.join(cache_dir, f"{cache_key}.jpg")

    etag = f'"{cache_key[:24]}"'

    # Handle conditional request — browser already has this image cached
    if request.headers.get('If-None-Match') == etag:
        return Response(status=304)

    try:
        if os.path.exists(cache_path):
            # Serve from disk cache
            with open(cache_path, 'rb') as fh:
                img_bytes = fh.read()
        else:
            cropped_img = crop_watermark(image_url, crop_bottom_percent=crop_percent)
            if cropped_img is None:
                return redirect(image_url)

            img_io = io.BytesIO()
            cropped_img.save(img_io, format='JPEG', quality=82, optimize=True)
            img_bytes = img_io.getvalue()

            # Write to disk cache
            try:
                with open(cache_path, 'wb') as fh:
                    fh.write(img_bytes)
            except Exception:
                pass

        response = make_response(img_bytes)
        response.headers['Content-Type'] = 'image/jpeg'
        response.headers['Cache-Control'] = 'public, max-age=2592000'  # 30 days
        response.headers['ETag'] = etag
        response.headers['Content-Length'] = str(len(img_bytes))
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    except Exception as e:
        current_app.logger.warning(f"Image proxy error for {image_url}: {e}")
        return redirect(image_url)

@public_api_bp.route('/api/cian-logo/<int:company_id>')
def cian_logo_proxy(company_id):
    """Proxy for CIAN developer logos — bypasses hotlink protection."""
    import requests as _req
    try:
        r = _req.get(
            f'https://cian.ru/api/get-company-logo/?id={company_id}',
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': f'https://www.cian.ru/zastroishchik-{company_id}/',
            },
            timeout=8,
            allow_redirects=True,
        )
        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
            resp = make_response(r.content)
            resp.headers['Content-Type'] = r.headers.get('Content-Type', 'image/jpeg')
            resp.headers['Cache-Control'] = 'public, max-age=2592000'
            return resp
    except Exception:
        pass
    return '', 404


@public_api_bp.route('/api/map/suggest')
def api_map_suggest():
    """
    DaData-powered address suggestions for the map search bar.
    Returns streets (from DaData) + districts (from DB) filtered to city.
    """
    q = request.args.get('q', '').strip()
    city_id = request.args.get('city_id', type=int)
    if not q or len(q) < 2:
        return jsonify([])

    results = []

    # 1. Districts from DB (fast, always available)
    _dist_name_to_slug = {}   # name.lower() → slug (used for city_district/quarter lookup)
    try:
        from models import District
        dist_q = District.query.filter(District.name.ilike(f'%{q}%'))
        if city_id:
            dist_q = dist_q.filter(District.city_id == city_id)
        for d in dist_q.limit(4).all():
            results.append({
                'type': 'district',
                'text': d.name,
                'slug': d.slug,
                'subtitle': 'Район',
                'icon': 'fas fa-map-marker-alt',
                'district_id': d.id,
            })
        # Pre-load all districts for slug lookup (city-scoped)
        all_d_q = District.query
        if city_id:
            all_d_q = all_d_q.filter(District.city_id == city_id)
        for d in all_d_q.all():
            _dist_name_to_slug[d.name.lower()] = d.slug
            # Also index without type suffix for fuzzy match
            for suffix in [' округ', ' округе', ' район', ' районе', ' микрорайон', ' мкр']:
                clean = d.name.lower().replace(suffix, '').strip()
                if clean and clean != d.name.lower():
                    _dist_name_to_slug.setdefault(clean, d.slug)
    except Exception as e:
        current_app.logger.warning(f'Map suggest districts error: {e}')

    def _resolve_district_slug(val: str) -> str | None:
        """Try to map a raw address value to a districts.slug."""
        v = val.strip().lower()
        if v in _dist_name_to_slug:
            return _dist_name_to_slug[v]
        # Strip common type suffixes from the query value too
        for suffix in [' округ', ' район', ' микрорайон', ' мкр', ' жилрайон', ' жилмассив']:
            if v.endswith(suffix):
                clean = v[:-len(suffix)].strip()
                if clean in _dist_name_to_slug:
                    return _dist_name_to_slug[clean]
        return None

    # 1b. City-districts and quarters from RC address fields (address_city_district, address_quarter)
    try:
        seen_quarters = set(r['text'] for r in results)
        # Match address_city_district (e.g. "Прикубанский", "Адлерский")
        rc_dist_q = db.session.query(
            ResidentialComplex.address_city_district.label('val'),
            db.literal('city_district').label('kind')
        ).filter(
            ResidentialComplex.is_active == True,
            ResidentialComplex.address_city_district.ilike(f'%{q}%'),
            ResidentialComplex.address_city_district != '',
        )
        if city_id:
            rc_dist_q = rc_dist_q.filter(ResidentialComplex.city_id == city_id)
        # Match address_quarter (e.g. "Кудепста", "Бытха", "Горхутор мкр")
        rc_qrt_q = db.session.query(
            ResidentialComplex.address_quarter.label('val'),
            db.literal('quarter').label('kind')
        ).filter(
            ResidentialComplex.is_active == True,
            ResidentialComplex.address_quarter.ilike(f'%{q}%'),
            ResidentialComplex.address_quarter != '',
        )
        if city_id:
            rc_qrt_q = rc_qrt_q.filter(ResidentialComplex.city_id == city_id)

        for row in rc_dist_q.distinct().limit(3).all():
            val = (row.val or '').strip()
            if val and val not in seen_quarters:
                seen_quarters.add(val)
                _dslug = _resolve_district_slug(val)
                results.append({
                    'type': 'city_district',
                    'text': val,
                    'subtitle': 'Городской район',
                    'icon': 'fas fa-city',
                    'quarter': val,
                    'district_slug': _dslug,
                })
        for row in rc_qrt_q.distinct().limit(4).all():
            val = (row.val or '').strip()
            if val and val not in seen_quarters:
                seen_quarters.add(val)
                _dslug = _resolve_district_slug(val)
                results.append({
                    'type': 'quarter',
                    'text': val,
                    'subtitle': 'Микрорайон',
                    'icon': 'fas fa-map-pin',
                    'quarter': val,
                    'district_slug': _dslug,
                })
    except Exception as e:
        current_app.logger.warning(f'Map suggest quarters error: {e}')

    # 2. Streets from DaData (city-bounded, street level)
    try:
        from services.dadata_client import get_dadata_client
        dadata = get_dadata_client()
        if dadata.is_available():
            street_suggestions = dadata.suggest_address(
                query=q,
                count=7,
                city_id=city_id,
                from_bound={'value': 'street'},
                to_bound={'value': 'street'},
            )
            seen = set()
            for item in street_suggestions:
                # DaDataClient returns: {'text': value, 'data': {...}, 'type': ...}
                d = item.get('data', {})
                street_name = (d.get('street_with_type') or
                               d.get('street') or
                               item.get('text', '')).strip()
                if not street_name or street_name in seen:
                    continue
                seen.add(street_name)
                if len(street_name) < 4:
                    continue
                city_hint = d.get('city') or d.get('settlement') or ''
                results.append({
                    'type': 'street',
                    'text': street_name,
                    'subtitle': city_hint,
                    'icon': 'fas fa-road',
                    'search_query': street_name,
                })
    except Exception as e:
        current_app.logger.warning(f'Map suggest DaData error: {e}')

    # 3. Complexes by name (from DB)
    try:
        rc_q = ResidentialComplex.query.filter(
            ResidentialComplex.is_active == True,
            ResidentialComplex.name.ilike(f'%{q}%')
        )
        if city_id:
            rc_q = rc_q.filter(ResidentialComplex.city_id == city_id)
        for rc in rc_q.limit(3).all():
            results.append({
                'type': 'complex',
                'text': rc.name,
                'subtitle': 'Жилой комплекс',
                'icon': 'fas fa-building',
                'complex_id': rc.id,
                'image_url': rc.main_image or '',
            })
    except Exception as e:
        current_app.logger.warning(f'Map suggest complexes error: {e}')

    return jsonify(results[:10])


def _render_map_page(current_city):
    """Internal map rendering logic"""
    try:
        # ✅ MIGRATED: Load properties with coordinates using repository
        properties_data = PropertyRepository.get_properties_with_coordinates()
        
        properties = []
        for prop_row in properties_data:
            # Unpack RowProxy data
            prop_id = prop_row.id
            inner_id = prop_row.inner_id
            title = prop_row.title
            price = prop_row.price or 0
            rooms = prop_row.rooms or 0
            area = prop_row.area or 0
            floor = prop_row.floor
            total_floors = prop_row.total_floors
            main_image = prop_row.main_image
            gallery_images = prop_row.gallery_images
            lat = getattr(prop_row, "latitude", None)
            lng = getattr(prop_row, "longitude", None)
            complex_name = prop_row.complex_name or ''
            cashback_rate = prop_row.cashback_rate or 0
            developer_name = prop_row.developer_name or ''
            
            # Calculate cashback
            cashback_amount = int(price * (cashback_rate / 100)) if cashback_rate > 0 else 0
            
            # Format title
            room_label = 'Студия' if rooms == 0 else f'{rooms}-комн'
            formatted_title = f"{room_label}, {area} м²" if title else title
            
            # Format data for map
            property_data = {
                'id': inner_id or prop_id,
                'price': price,
                'area': area,
                'rooms': rooms,
                'title': formatted_title,
                'address': '',  # Will be filled from Property model if available
                'residential_complex': complex_name,
                'complex_name': complex_name,
                'developer': developer_name,
                'district': 'Краснодарский край',
                'coordinates': {
                    'lat': float(lat),
                    'lng': float(lng)
                },
                'url': f"/object/{inner_id or prop_id}",
                'type': 'property',
                'cashback': cashback_amount,
                'cashback_rate': cashback_rate,
                'cashback_available': cashback_rate > 0,
                'status': 'available',
                'property_type': 'Квартира',
                'main_image': main_image or '/static/images/no-photo.svg',
                'gallery_images': gallery_images,
                'floor': floor,
                'total_floors': total_floors
            }
            
            properties.append(property_data)
        
        # ✅ MIGRATED: Load residential complexes with coordinates
        complexes_data = ResidentialComplexRepository.get_with_coordinates()
        
        residential_complexes = []
        for idx, row in enumerate(complexes_data):
            complex_data = {
                'id': row.id,
                'name': row.name or '',
                'developer': row.developer_name or '',
                'address': '',  # Not in the query result
                'district': 'Краснодарский край',
                'apartments_count': 0,  # Will be calculated if needed
                'price_from': 0,  # Will be calculated if needed
                'coordinates': {
                    'lat': float(row.latitude) if row.latitude else 45.0448,
                    'lng': float(row.longitude) if row.longitude else 38.9760
                },
                'url': f'/zk/{row.slug}' if hasattr(row, 'slug') and row.slug else f'/residential-complex/{row.id}',
                'type': 'complex'
            }
            residential_complexes.append(complex_data)
        
        # ✅ Применяем фильтры к данным
        developers_filter = request.args.get('developers', '')
        if developers_filter:
            developers_list = [d.strip() for d in developers_filter.split(',')]
            developers_list = [d.strip() for d in developers_filter.split(',')]
            properties = [p for p in properties if p.get('developer') in developers_list]
            print(f"🔍 Фильтр по застройщикам: {developers_list}, найдено объектов: {len(properties)}")
        
        # Фильтры для интерфейса
        all_districts = sorted(list(set(prop.get('district', 'Не указан') for prop in properties if prop.get('district'))))
        all_developers = sorted(list(set(prop.get('developer', 'Не указан') for prop in properties if prop.get('developer'))))
        all_complexes = sorted(list(set(prop.get('residential_complex', 'Не указан') for prop in properties if prop.get('residential_complex'))))
        
        filters = {
            'rooms': request.args.getlist('rooms'),
            'price_min': request.args.get('price_min', ''),
            'price_max': request.args.get('price_max', ''),
            'district': request.args.get('district', ''),
            'developer': request.args.get('developer', ''),
            'developers': developers_filter,
            'residential_complex': request.args.get('residential_complex', ''),
        }
        
        # Map data loaded
        
        return render_template('map.html', 
                             properties=properties, 
                             residential_complexes=residential_complexes,
                             all_districts=all_districts,
                             all_developers=all_developers,
                             all_complexes=all_complexes,
                             filters=filters,
                             current_city=current_city)
                             
    except Exception as e:
        print(f"ERROR in map route: {e}")
        import traceback
        traceback.print_exc()
        return f"Error 500: {str(e)}", 500


# ==========================================
ENGLISH_TO_RUSSIAN_CITY_SLUGS = {
    'family-mortgage': 'semejnaya-ipoteka',
    'it-mortgage': 'it-ipoteka',
    'military-mortgage': 'voennaya-ipoteka',
    'developer-mortgage': 'ipoteka-ot-zastrojshchika',
    'maternal-capital': 'materinsky-kapital',
    'tax-deduction': 'nalogovyj-vychet',
    'insurance': 'strahovanie',
    'appraisal': 'otsenka',
    'about': 'o-kompanii',
    'how-it-works': 'kak-eto-rabotaet',
    'contacts': 'kontakty',
    'reviews': 'otzyvy',
    'map': 'karta',
    'comparison': 'sravnenie',
    'favorites': 'izbrannoe',
    'cashback-terms': 'usloviya-keshbeka',
    'streets': 'ulitsy',
    'properties': 'novostrojki',
    'residential-complexes': 'zhilye-kompleksy',
}


@public_api_bp.before_app_request
def redirect_english_to_russian_slugs():
    """301 redirect English city-prefixed URLs to Russian transliterated equivalents"""
    path = request.path.rstrip('/')
    parts = path.split('/')
    if len(parts) >= 2 and parts[1] == 'api':
        return
    if len(parts) == 3 and parts[1] and parts[2]:
        city_slug = parts[1]
        page_slug = parts[2]
        if page_slug in ENGLISH_TO_RUSSIAN_CITY_SLUGS:
            russian_slug = ENGLISH_TO_RUSSIAN_CITY_SLUGS[page_slug]
            new_path = f'/{city_slug}/{russian_slug}'
            if request.query_string:
                new_path += '?' + request.query_string.decode('utf-8')
            return redirect(new_path, code=301)


def _extract_amenity_badges(nearby_json, max_visible=4):
    """Extract top amenity badges from complex nearby JSON for card display.
    Returns list of dicts: [{label, icon, dist_str}], max_visible items + rest_count."""
    if not nearby_json:
        return [], 0
    try:
        import json as _j
        data = _j.loads(nearby_json) if isinstance(nearby_json, str) else nearby_json
        badges = []

        # Priority order: mall → supermarket/shop → school → kindergarten → park/leisure
        PRIORITY = [
            # (category_key, type_filter_list_or_None, icon, label_fn)
            ('shopping',   ['mall', 'department_store'],  '🏬', lambda n: n if len(n) <= 16 else 'ТЦ'),
            ('shopping',   ['supermarket'],               '🛒', lambda n: n if len(n) <= 12 else 'Супермаркет'),
            ('shopping',   ['convenience', 'grocery'],    '🛍️', lambda n: n if len(n) <= 12 else 'Магазин'),
            ('education',  ['school', 'college'],         '🏫', lambda n: 'Школа'),
            ('education',  ['kindergarten', 'childcare'], '👶', lambda n: 'Детский сад'),
            ('leisure',    ['park', 'garden', 'nature', 'recreation_ground'], '🌳', lambda n: 'Парк'),
            ('healthcare', None,                          '🏥', lambda n: 'Поликлиника'),
            ('transport',  ['subway', 'tram'],            '🚇', lambda n: n if len(n) <= 14 else 'Метро'),
        ]

        seen_categories = set()
        for cat_key, type_filter, icon, label_fn in PRIORITY:
            if len(badges) >= max_visible + 3:
                break
            items = data.get(cat_key) or []
            for item in items:
                itype = item.get('type', '')
                if type_filter and itype not in type_filter:
                    continue
                name = item.get('name', '').strip() or item.get('type_display', '')
                dist = item.get('distance', 0)
                dist_str = f'{dist} м' if dist < 1000 else f'{round(dist/1000,1)} км'
                dedup_key = (cat_key, itype)
                if dedup_key in seen_categories:
                    continue
                seen_categories.add(dedup_key)
                badges.append({'label': label_fn(name), 'icon': icon, 'dist': dist_str})
                break  # one badge per priority rule

        visible = badges[:max_visible]
        rest = max(0, len(badges) - max_visible)
        return visible, rest
    except Exception:
        return [], 0


def _parse_plan_images_from_complex(complex_obj):
    """Return list of floor plan / layout images for a complex (from layout_images field)."""
    if not complex_obj:
        return []
    raw = getattr(complex_obj, 'layout_images', None)
    if not raw:
        return []
    try:
        import json as _j
        imgs = _j.loads(raw) if isinstance(raw, str) else raw
        return [u for u in (imgs or []) if u and isinstance(u, str)][:10]
    except Exception:
        return []


def _parse_nashdom_photos(complex_obj):
    """Return parsed list of clean nashdom photos for a complex."""
    if not complex_obj:
        return []
    raw = getattr(complex_obj, 'nashdom_photos', None)
    if not raw:
        return []
    try:
        import json as _j
        imgs = _j.loads(raw) if isinstance(raw, str) else raw
        return [u for u in (imgs or []) if u and isinstance(u, str)][:20]
    except Exception:
        return []


def _get_clean_complex_images(complex_obj, limit=30):
    """
    Return watermark-free images for a residential complex.
    Priority: nashdom_photos → filtered gallery_images (ЖК exterior only).
    Filters out apartment interior/floor-plan photos from CIAN — those have
    pure-numeric filenames like '2807664603-1.jpg'.
    If all gallery images are pure-numeric (common for CIAN-only complexes),
    returns [] so the caller can use main_image as fallback instead of
    showing a mix of floor plans and interior shots.
    """
    import json as _j

    # 1. Prefer nashdom photos — always clean
    nashdom = _parse_nashdom_photos(complex_obj)
    if nashdom:
        return nashdom[:limit]

    # 2. Always include main_image as first if it exists and has a named (non-numeric) filename
    main_img = getattr(complex_obj, 'main_image', None) or ''
    main_clean = False
    if main_img:
        _fn = main_img.split('/')[-1]
        _fs = _fn.split('-')[0]
        main_clean = not _fs.isdigit()  # True if it's a named complex-level image

    # 3. Filter gallery_images: keep only ЖК exterior shots (named filenames)
    raw = getattr(complex_obj, 'gallery_images', None)
    gallery_clean = []
    if raw:
        try:
            imgs = _j.loads(raw) if isinstance(raw, str) else raw
            if isinstance(imgs, list):
                for url in imgs:
                    if not url or not isinstance(url, str):
                        continue
                    if url == main_img:
                        continue  # Don't duplicate main_image
                    filename = url.split('/')[-1]
                    first_segment = filename.split('-')[0]
                    if first_segment.isdigit():
                        continue  # Skip apartment/floor-plan images
                    gallery_clean.append(url)
        except Exception:
            pass

    # Always put main_image first (it's the ЖК exterior shot from the aggregator)
    result = []
    seen = set()
    if main_img:
        result.append(main_img)
        seen.add(main_img)

    # Add named gallery images (filtered)
    for url in gallery_clean:
        if url not in seen:
            result.append(url)
            seen.add(url)

    # If gallery_clean is empty but there are raw gallery images (all numeric filenames —
    # common for pure-CIAN complexes), add them all so the gallery still shows multiple photos.
    if not gallery_clean and raw:
        try:
            all_imgs = _j.loads(raw) if isinstance(raw, str) else raw
            if isinstance(all_imgs, list):
                for url in all_imgs:
                    if url and isinstance(url, str) and url not in seen:
                        result.append(url)
                        seen.add(url)
        except Exception:
            pass

    return result[:limit]


def _parse_nearby_places(nearby_json):
    """Parse complex nearby JSON into a flat list of top items per category for property detail page."""
    if not nearby_json:
        return []
    try:
        import json as _json
        data = _json.loads(nearby_json) if isinstance(nearby_json, str) else nearby_json
        CATS = [
            ('transport',  '🚌', 'Транспорт',  2),
            ('shopping',   '🛒', 'Магазины',   2),
            ('education',  '🏫', 'Учёба',      2),
            ('healthcare', '🏥', 'Медицина',   1),
            ('sport',      '🏋️', 'Спорт',      1),
            ('leisure',    '🎭', 'Досуг',      1),
        ]
        result = []
        for key, icon, label, limit in CATS:
            items = data.get(key) or []
            for item in items[:limit]:
                dist = item.get('distance', 0)
                dist_str = f"{dist} м" if dist < 1000 else f"{round(dist/1000, 1)} км"
                result.append({
                    'icon': icon,
                    'name': item.get('name', ''),
                    'distance': dist_str,
                    'category': label,
                })
        return result
    except Exception:
        return []


def extract_main_image_from_photos(photos_raw):
    """Извлекает основное изображение из поля photos, предпочитая внешние виды зданий"""
    if not photos_raw or not photos_raw.strip():
        return '/static/images/no-photo.svg'
    
    try:
        import json
        # Попробуем парсить как JSON массив
        if photos_raw.startswith('[') and photos_raw.endswith(']'):
            images = json.loads(photos_raw)
            if not images:
                return '/static/images/no-photo.svg'
            
            # Фильтруем изображения, предпочитая внешние виды
            # Берем последние изображения, так как первые часто планировки
            if len(images) > 5:
                # Берем из середины/конца массива, где обычно фото зданий
                return images[len(images)//2]
            elif len(images) > 2:
                return images[-1]  # Последнее фото
            else:
                return images[0]
        
        # PostgreSQL array format: {url1,url2,url3}
        elif photos_raw.startswith('{') and photos_raw.endswith('}'):
            images_str = photos_raw[1:-1]  # Remove braces
            if images_str:
                images = [img.strip().strip('"') for img in images_str.split(',') if img.strip()]
                return images[0] if images else '/static/images/no-photo.svg'
            else:
                return '/static/images/no-photo.svg'
        
        # Одиночная ссылка
        else:
            return photos_raw
            
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Error parsing photos: {e}, raw data: {photos_raw[:100]}")
        return '/static/images/no-photo.svg'

# API Routes
@public_api_bp.route('/api/properties')
@csrf.exempt
def api_properties():
    """API for property list - returns properties for homepage featured section"""
    try:
        city_id = request.args.get('city_id', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        limit = min(limit, 100)  # Cap at 100
        
        current_app.logger.debug(f"API /api/properties: city_id={city_id}, limit={limit}")
        
        properties = PropertyRepository.get_all_active(
            limit=limit,
            filters={'city_id': city_id}
        )
        
        result = []
        for prop in properties:
            complex_obj = prop.residential_complex
            
            room_display = "Студия"
            rooms_count = prop.rooms or 0
            if rooms_count == 1:
                room_display = "1-комн."
            elif rooms_count == 2:
                room_display = "2-комн."
            elif rooms_count == 3:
                room_display = "3-комн."
            elif rooms_count == 4:
                room_display = "4-комн."
            elif rooms_count >= 5:
                room_display = f"{rooms_count}-комн."
            
            photos_list = []
            if prop.gallery_images:
                try:
                    import json as json_module
                    photos_list = json_module.loads(prop.gallery_images) if isinstance(prop.gallery_images, str) else prop.gallery_images
                except:
                    photos_list = []
            
            result.append({
                'id': prop.inner_id or str(prop.id),
                'price': prop.price or 0,
                'area': prop.area or 0,
                'total_area': prop.area or 0,
                'rooms': rooms_count,
                'room_type': room_display,
                'object_rooms': room_display,
                'floor': prop.floor or 1,
                'floors_in_building': prop.total_floors or 1,
                'max_floor': prop.total_floors or 1,
                'complex_name': complex_obj.name if complex_obj else 'ЖК не указан',
                'residential_complex': complex_obj.name if complex_obj else 'ЖК не указан',
                'developer_name': prop.developer.name if prop.developer else '',
                'developer': prop.developer.name if prop.developer else 'Застройщик не указан',
                'photos': json.dumps(photos_list) if photos_list else '[]',
                'parsed_district': (prop.district.name if prop.district else None) or (complex_obj.address_city_district if complex_obj else '') or '',
                'district': (prop.district.name if prop.district else None) or (complex_obj.address_city_district if complex_obj else '') or ''
            })
        
        current_app.logger.debug(f"API /api/properties: returning {len(result)} properties")
        return jsonify({'success': True, 'properties': result})
    except Exception as e:
        current_app.logger.error(f"Error in /api/properties: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@public_api_bp.route('/api/map-properties')
@cache.cached(timeout=300, query_string=True)
def api_map_properties():
    """API для интерактивной карты - возвращает объекты с полями для определения статуса"""
    try:
        city_id = request.args.get('city_id', None)
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 500, type=int)
        rooms_filter = request.args.getlist('rooms') or request.args.getlist('rooms[]')
        price_min = request.args.get('price_min', type=float)
        price_max = request.args.get('price_max', type=float)
        area_min = request.args.get('area_min', type=float)
        area_max = request.args.get('area_max', type=float)
        floor_min = request.args.get('floor_min', type=int)
        floor_max = request.args.get('floor_max', type=int)
        developers_filter = request.args.getlist('developers') or request.args.getlist('developers[]')
        completion_filter = request.args.getlist('completion') or request.args.getlist('completion[]')
        # delivery_years is the SEO-page alias for completion year filter — merge them
        _delivery_years = request.args.getlist('delivery_years') or request.args.getlist('delivery_years[]')
        if _delivery_years:
            completion_filter = list(completion_filter) + [str(y) for y in _delivery_years]
        object_classes_filter = request.args.getlist('object_classes') or request.args.getlist('object_classes[]')
        building_status_filter = request.args.getlist('building_status') or request.args.getlist('building_status[]')
        building_released_filter = request.args.getlist('building_released') or request.args.getlist('building_released[]')
        renovation_filter = request.args.getlist('renovation') or request.args.getlist('renovation[]')
        floor_options_filter = request.args.getlist('floor_options') or request.args.getlist('floor_options[]')
        _districts_raw = request.args.getlist('districts') or request.args.getlist('districts[]')
        _district_singular = request.args.get('district', '').strip()
        if _district_singular and _district_singular not in _districts_raw:
            _districts_raw.append(_district_singular)
        districts_filter = _districts_raw
        features_filter = request.args.getlist('features') or request.args.getlist('features[]')
        search_query = request.args.get('search', '')
        property_type_filter = request.args.get('property_type', '')
        
        from models import Property, ResidentialComplex, City, Developer
        from sqlalchemy.orm import joinedload
        
        query = Property.query.filter(Property.is_active == True)
        
        if city_id:
            try:
                city_id = int(city_id)
                query = query.filter(Property.city_id == city_id)
            except:
                pass
        
        # Apply room filter
        if rooms_filter:
            try:
                rooms_list = [int(r) for r in rooms_filter if r]
                if rooms_list:
                    query = query.filter(Property.rooms.in_(rooms_list))
            except:
                pass
        
        # Apply property type filter
        if property_type_filter and property_type_filter != 'all':
            property_type_map = {
                'apartments': 'Квартира',
                'houses': 'Дом',
                'townhouses': 'Таунхаус',
                'penthouses': 'Пентхаус',
                'apartments_commercial': 'Апартаменты'
            }
            mapped_type = property_type_map.get(property_type_filter, property_type_filter)
            query = query.filter(Property.property_type == mapped_type)
            print(f"🗺️ Map-properties: Filtering by property_type: {mapped_type}")

        # Apply price filter
        if price_min is not None:
            query = query.filter(Property.price >= price_min)
        if price_max is not None:
            query = query.filter(Property.price <= price_max)
        
        # Apply price per m² filter
        price_sqm_min = request.args.get('price_sqm_min', type=float)
        price_sqm_max = request.args.get('price_sqm_max', type=float)
        if price_sqm_min is not None:
            query = query.filter(Property.price_per_sqm >= price_sqm_min)
        if price_sqm_max is not None:
            query = query.filter(Property.price_per_sqm <= price_sqm_max)
        
        # Apply area filter
        if area_min is not None:
            query = query.filter(Property.area >= area_min)
        if area_max is not None:
            query = query.filter(Property.area <= area_max)
        
        # Apply search filter with stop-word filtering
        if search_query:
            stop_words = {'улица', 'ул', 'район', 'р-н', 'город', 'г', 'жк', 'жилой', 'комплекс', 
                         'дом', 'д', 'корпус', 'к', 'строение', 'стр', 'литер', 'лит', 'проспект', 'пр'}
            words = search_query.lower().split()
            significant_words = [w for w in words if w not in stop_words and len(w) > 1]
            
            query = query.outerjoin(ResidentialComplex, Property.complex_id == ResidentialComplex.id)
            query = query.outerjoin(Developer, Property.developer_id == Developer.id)
            
            if significant_words:
                for word in significant_words:
                    search_pattern = f'%{word}%'
                    query = query.filter(
                        db.or_(
                            Property.address.ilike(search_pattern),
                            ResidentialComplex.name.ilike(search_pattern),
                            Developer.name.ilike(search_pattern)
                        )
                    )
            else:
                search_pattern = f'%{search_query}%'
                query = query.filter(
                    db.or_(
                        Property.address.ilike(search_pattern),
                        ResidentialComplex.name.ilike(search_pattern),
                        Developer.name.ilike(search_pattern)
                    )
                )
        
        # Apply floor filter
        if floor_min is not None:
            query = query.filter(Property.floor >= floor_min)
        if floor_max is not None:
            query = query.filter(Property.floor <= floor_max)
        
        # Apply developer filter (supports both IDs and names)
        developer_name = request.args.get('developer', '')  # Single developer name from URL
        if developer_name:
            # Filter by developer name
            dev = Developer.query.filter(Developer.name == developer_name).first()
            if dev:
                query = query.filter(Property.developer_id == dev.id)
                print(f"🗺️ Map-properties: Filtering by developer name: {developer_name} (ID: {dev.id})")
        elif developers_filter:
            try:
                dev_ids = [int(d) for d in developers_filter if d]
                if dev_ids:
                    query = query.filter(Property.developer_id.in_(dev_ids))
            except:
                pass
        
        # Apply district filter — by ID (locked SEO filter, preferred)
        district_id_arg = request.args.get('district_id', type=int)
        if district_id_arg:
            query = query.filter(Property.district_id == district_id_arg)
            print(f"🗺️ Map-properties: Filtering by district_id: {district_id_arg}")
        else:
            # Fallback: by name
            district_name = request.args.get('district', '')
            if district_name:
                from models import District
                dist = District.query.filter(District.name == district_name).first()
                if dist:
                    query = query.filter(Property.district_id == dist.id)
                    print(f"🗺️ Map-properties: Filtering by district: {district_name}")
        
        # Apply residential complex filter
        rc_name = request.args.get('residential_complex', '')
        if rc_name:
            rc = ResidentialComplex.query.filter(ResidentialComplex.name == rc_name).first()
            if rc:
                query = query.filter(Property.complex_id == rc.id)
                print(f"🗺️ Map-properties: Filtering by complex: {rc_name}")
        
        # Join ResidentialComplex once if any RC-based filter is needed
        needs_rc_join = bool(object_classes_filter or completion_filter or building_status_filter or building_released_filter)
        if needs_rc_join:
            query = query.join(ResidentialComplex, Property.complex_id == ResidentialComplex.id)
        
        # Apply object class filter
        if object_classes_filter:
            query = query.filter(
                ResidentialComplex.object_class_display_name.in_(object_classes_filter)
            )
        
        # Apply completion year filter
        if completion_filter:
            try:
                completion_years = [int(y) for y in completion_filter if y]
                if completion_years:
                    query = query.filter(
                        ResidentialComplex.end_build_year.in_(completion_years)
                    )
            except:
                pass
        
        # Apply building status filter
        if building_status_filter:
            from datetime import datetime
            current_year = datetime.now().year
            status_conditions = []
            for status in building_status_filter:
                if status == 'delivered':
                    status_conditions.append(ResidentialComplex.end_build_year < current_year)
                elif status == 'under_construction':
                    status_conditions.append(ResidentialComplex.end_build_year >= current_year)
            if status_conditions:
                from sqlalchemy import or_
                query = query.filter(or_(*status_conditions))
        
        # Apply building_released filter
        if building_released_filter and not building_status_filter:
            from datetime import datetime
            current_year = datetime.now().year
            status_conditions = []
            for status in building_released_filter:
                if status in ('true', 'delivered', '1'):
                    status_conditions.append(ResidentialComplex.end_build_year < current_year)
                elif status in ('false', 'under_construction', '0'):
                    status_conditions.append(ResidentialComplex.end_build_year >= current_year)
            if status_conditions:
                from sqlalchemy import or_
                query = query.filter(or_(*status_conditions))
        
        # Apply floor_options filter (not_first, not_last)
        if floor_options_filter:
            for option in floor_options_filter:
                if option == 'not_first':
                    query = query.filter(Property.floor > 1)
                elif option == 'not_last':
                    query = query.filter(
                        db.or_(
                            Property.floor < Property.total_floors,
                            Property.total_floors.is_(None)
                        )
                    )
                elif option == 'last':
                    query = query.filter(Property.floor == Property.total_floors)
        
        # Apply renovation filter
        if renovation_filter:
            renovation_conditions = []
            for ren in renovation_filter:
                ren_lower = ren.lower()
                if ren_lower in ('no_renovation', 'без отделки', 'без_отделки'):
                    renovation_conditions.append(
                        db.or_(
                            Property.renovation_type.is_(None),
                            Property.renovation_type == '',
                            Property.renovation_type == 'no_renovation',
                            db.func.lower(Property.renovation_type).like('%без%')
                        )
                    )
                elif ren_lower in ('fine_finish', 'чистовая', 'чистовая отделка'):
                    renovation_conditions.append(
                        db.or_(
                            Property.renovation_type == 'fine_finish',
                            db.func.lower(Property.renovation_type).like('%чистов%')
                        )
                    )
                elif ren_lower in ('rough_finish', 'черновая', 'черновая отделка'):
                    renovation_conditions.append(
                        db.or_(
                            Property.renovation_type == 'rough_finish',
                            db.func.lower(Property.renovation_type).like('%чернов%')
                        )
                    )
                elif ren_lower in ('turnkey', 'под ключ'):
                    renovation_conditions.append(
                        db.or_(
                            Property.renovation_type == 'turnkey',
                            db.func.lower(Property.renovation_type).like('%ключ%')
                        )
                    )
                else:
                    renovation_conditions.append(
                        db.or_(
                            db.func.lower(Property.renovation_type) == ren_lower,
                            db.func.lower(Property.renovation_type).like(f'%{ren_lower}%')
                        )
                    )
            if renovation_conditions:
                query = query.filter(db.or_(*renovation_conditions))
        
        # Apply districts filter — accepts numeric IDs, slugs, or district names
        if districts_filter:
            from models import District as _DistM
            resolved_ids = []
            _fallback_names = []
            for d in districts_filter:
                if not d:
                    continue
                try:
                    resolved_ids.append(int(d))
                except (ValueError, TypeError):
                    # Try slug first (city-scoped), then exact name, then partial
                    _dq = _DistM.query
                    if city_id:
                        _dq = _dq.filter_by(city_id=city_id)
                    _dist = _dq.filter_by(slug=d).first()
                    if not _dist:
                        _dist = _dq.filter(_DistM.name.ilike(d)).first()
                    if not _dist:
                        _dist = _dq.filter(_DistM.name.ilike(f'%{d}%')).first()
                    if _dist:
                        resolved_ids.append(_dist.id)
                    else:
                        _fallback_names.append(d)
            if resolved_ids:
                # For okrug-type districts also check okrug_district_id on ResidentialComplex
                OKRUG_DISTRICT_IDS = {7, 9, 10, 28}
                okrug_ids = [i for i in resolved_ids if i in OKRUG_DISTRICT_IDS]
                if okrug_ids:
                    from models import ResidentialComplex as _RCOkrug
                    _okrug_rc_subq = db.session.query(_RCOkrug.id).filter(
                        _RCOkrug.okrug_district_id.in_(okrug_ids)
                    ).scalar_subquery()
                    _dist_conds = [Property.district_id.in_(resolved_ids)]
                    _dist_conds.append(Property.complex_id.in_(_okrug_rc_subq))
                    query = query.filter(db.or_(*_dist_conds))
                else:
                    query = query.filter(Property.district_id.in_(resolved_ids))
            elif _fallback_names:
                # No district FK found — ILIKE fallback on RC address fields
                from models import ResidentialComplex as _RCMap
                _fb_conds = [db.or_(
                    _RCMap.address_city_district.ilike(f'%{_n}%'),
                    _RCMap.address_quarter.ilike(f'%{_n}%'),
                ) for _n in _fallback_names]
                query = query.join(_RCMap, Property.complex_id == _RCMap.id, isouter=True) \
                             .filter(db.or_(*_fb_conds))
            else:
                # Empty list after splitting — return nothing
                query = query.filter(Property.district_id == -1)

        # ✅ Viewport bbox filter (lat_min/lat_max/lng_min/lng_max) — для sidebar при движении карты
        lat_min_q = request.args.get('lat_min', type=float)
        lat_max_q = request.args.get('lat_max', type=float)
        lng_min_q = request.args.get('lng_min', type=float)
        lng_max_q = request.args.get('lng_max', type=float)
        if lat_min_q is not None and lat_max_q is not None and lng_min_q is not None and lng_max_q is not None:
            query = query.filter(
                Property.latitude.between(lat_min_q, lat_max_q),
                Property.longitude.between(lng_min_q, lng_max_q)
            )

        # DB-level count (fast — no row fetch)
        total = query.count()
        total_pages = max(1, (total + per_page - 1) // per_page)

        # Apply sort order from ?sort= param
        sort_param = request.args.get('sort', '').strip().replace('_', '-')
        if sort_param == 'price-asc':
            sort_col = Property.price.asc()
        elif sort_param == 'price-desc':
            sort_col = Property.price.desc()
        elif sort_param == 'area-asc':
            sort_col = Property.area.asc()
        elif sort_param == 'area-desc':
            sort_col = Property.area.desc()
        else:
            # По умолчанию — новые объекты первыми (по id desc)
            sort_col = Property.id.desc()

        # DB-level pagination — only fetch the needed page
        offset = (page - 1) * per_page
        properties_list = query.options(
            joinedload(Property.residential_complex),
            joinedload(Property.developer),
            joinedload(Property.city)
        ).order_by(sort_col).offset(offset).limit(per_page).all()
        
        properties = []
        for prop in properties_list:
            try:
                complex_obj = prop.residential_complex
                city_obj = prop.city
                
                lat = float(prop.latitude) if prop.latitude else (float(complex_obj.latitude) if complex_obj and complex_obj.latitude else 45.0355)
                lng = float(prop.longitude) if prop.longitude else (float(complex_obj.longitude) if complex_obj and complex_obj.longitude else 38.9753)
                property_data = {
                    'id': prop.id,
                    'price': prop.price or 0,
                    'area': prop.area or 0,
                    'rooms': prop.rooms or 0,
                    'title': getattr(prop, 'room_description', 'Квартира'),
                    'residential_complex': complex_obj.name if complex_obj else '',
                    'complex_name': complex_obj.name if complex_obj else '',
                    'complex_slug': complex_obj.slug if complex_obj else None,
                    'developer': prop.developer.name if prop.developer else '',
                    'coordinates': {'lat': lat, 'lng': lng},
                    'latitude': lat,
                    'longitude': lng,
                    'city_id': prop.city_id,
                    'city_name': city_obj.name if city_obj else 'N/A',
                    'url': f"/object/{prop.id}",
                    'status': 'строится',
                    'completion_date': getattr(prop, 'completion_date_quarter', None),
                    'completion_year': getattr(prop, 'completion_year', None),
                    'deal_type': getattr(prop, 'deal_type', 'sale'),
                    'complex_building_status': getattr(complex_obj, 'status', None) if complex_obj else None,
                    'complex_building_end_build_year': getattr(complex_obj, 'end_build_year', None) if complex_obj else None,
                    'district': (prop.district.name if prop.district else None) or (complex_obj.address_city_district if complex_obj else '') or '',
                    'cashback': int((prop.price or 0) * (float(complex_obj.cashback_rate or 3.5) / 100)) if complex_obj else int((prop.price or 0) * 0.035),
                    'cashback_rate': float(complex_obj.cashback_rate) if complex_obj and complex_obj.cashback_rate else 3.5,
                    'address': prop.address or (complex_obj.address if complex_obj else None),
                    'building_name': prop.complex_building_name or None,
                    'renovation_type': getattr(prop, 'renovation_type', None) or (complex_obj.finishing_type if complex_obj else None),
                }
                
                # Add images to response
                if prop.gallery_images:
                    property_data['gallery_images'] = prop.gallery_images
                elif prop.main_image:
                    property_data['main_image'] = prop.main_image
                    property_data['gallery_images'] = [prop.main_image]
                
                properties.append(property_data)
            except Exception as e:
                continue
        
        return jsonify({
            'success': True,
            'properties': properties,
            'pagination': {
                'page': page,
                'pages': total_pages,
                'per_page': per_page,
                'total': total
            },
            'total': total
        })
    except Exception as e:
        print(f"❌ ERROR in api_map_properties: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@public_api_bp.route('/api/search-suggestions-OLD-DISABLED')
def api_search_suggestions_old_disabled():
    """❌ СТАРЫЙ API endpoint - ОТКЛЮЧЁН, чтобы не мешал новому"""
    return jsonify([])  # ВСЕГДА ПУСТОЙ


# ===== СТАРЫЙ КОД ПОЛНОСТЬЮ УДАЛЁН =====

@public_api_bp.route('/api/properties/list')
def api_properties_list():
    """AJAX API для получения списка объектов с сортировкой и фильтрами"""
    # Resolve city context for dynamic city display
    current_city = resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )
    
    try:
        import json
        from repositories.property_repository import PropertyRepository, ResidentialComplexRepository, DeveloperRepository
        
        # Parse filters
        _, _, filters = build_property_filters(request.args)
        
        # Pagination
        page = request.args.get('page', default=1, type=int)
        page = max(1, page)
        per_page = request.args.get('per_page', default=20, type=int)
        per_page = min(max(1, per_page), 1000)  # Limit between 1-1000
        offset = (page - 1) * per_page
        
        # Sorting — empty / omitted = relevance (diverse across complexes)
        sort_type = request.args.get('sort', '').replace('_', '-')
        
        # Convert filters to Repository format (same logic as /properties route)
        repo_filters = {}
        
        # Price filters
        if filters.get('price_min'):
            try:
                price_val = float(filters['price_min'])
                # If price < 1000, assume it's in millions; else assume rubles
                repo_filters['min_price'] = int(price_val * 1000000) if price_val < 1000 else int(price_val)
            except:
                pass
        if filters.get('price_max'):
            try:
                price_val = float(filters['price_max'])
                # If price < 1000, assume it's in millions; else assume rubles
                repo_filters['max_price'] = int(price_val * 1000000) if price_val < 1000 else int(price_val)
            except:
                pass
                
        # Area filters
        if filters.get('area_min'):
            try:
                repo_filters['min_area'] = float(filters['area_min'])
            except:
                pass
        if filters.get('area_max'):
            try:
                repo_filters['max_area'] = float(filters['area_max'])
            except:
                pass
                
        # Rooms filter
        if filters.get('rooms'):
            try:
                # Поддержка и строк, и чисел в массиве rooms
                rooms_list = []
                for r in filters['rooms']:
                    if isinstance(r, str):
                        r_stripped = r.strip()
                        if r_stripped:
                            rooms_list.append(int(r_stripped))
                    elif isinstance(r, int):
                        rooms_list.append(r)
                if rooms_list:
                    repo_filters['rooms'] = rooms_list
                    current_app.logger.info(f"✅ Rooms filter applied: {rooms_list}")
            except Exception as e:
                current_app.logger.error(f"❌ Error processing rooms filter: {e}")
        if filters.get('developers'):
            repo_filters['developers'] = filters['developers']
        if filters.get('developer'):
            if 'developers' not in repo_filters:
                repo_filters['developers'] = []
            if filters['developer'] not in repo_filters['developers']:
                repo_filters['developers'].append(filters['developer'])
                
        # Districts filter — resolve slugs to IDs for FK-based search (precise, no ILIKE)
        if filters.get('districts'):
            raw_districts = filters['districts']
            if isinstance(raw_districts, str):
                raw_districts = [raw_districts]
            from models import District as _DistM, Property as _DistPropM
            city_id_for_dist = None
            if request.args.get('city_id'):
                try:
                    city_id_for_dist = int(request.args.get('city_id'))
                except:
                    pass
            elif current_city:
                city_id_for_dist = current_city.id
            resolved_ids = []
            pip_property_ids = []
            unresolved_names = []
            for dval in raw_districts:
                dval = str(dval).strip()
                if not dval:
                    continue
                _dq = _DistM.query
                if city_id_for_dist:
                    _dq = _dq.filter_by(city_id=city_id_for_dist)
                _dobj = _dq.filter_by(slug=dval).first()
                if not _dobj:
                    _dobj = _dq.filter(_DistM.name.ilike(f'%{dval}%')).first()
                if _dobj:
                    # Check FK prop count for this district
                    _fk_count = _DistPropM.query.filter_by(
                        district_id=_dobj.id, is_active=True).count()
                    if _fk_count > 0:
                        resolved_ids.append(_dobj.id)
                    else:
                        # FK=0: fall back to name ILIKE on the Russian district name
                        # (matches address text, same as seo_city.py Fallback 2)
                        unresolved_names.append(_dobj.name)
                else:
                    unresolved_names.append(dval)
            if resolved_ids:
                repo_filters['district_id_in'] = resolved_ids
            if unresolved_names:
                repo_filters['districts'] = unresolved_names

        # District ID filter — locked SEO page filter (precise FK, preferred over name-based)
        if request.args.get('district_id'):
            try:
                repo_filters['district_id'] = int(request.args.get('district_id'))
            except (ValueError, TypeError):
                pass

        # Property type filter with English to Russian mapping
        if filters.get('property_type') and filters['property_type'] != 'all':
            property_type_map = {
                'apartments': 'Квартира',
                'houses': 'Дом',
                'townhouses': 'Таунхаус',
                'penthouses': 'Пентхаус',
                'apartments_commercial': 'Апартаменты',
            }
            mapped_type = property_type_map.get(filters['property_type'], filters['property_type'])
            repo_filters['property_type'] = mapped_type
        
        # Residential complex filter
        if filters.get('residential_complex'):
            repo_filters['residential_complex'] = filters['residential_complex']

        # Quarter filter (address_quarter / address_city_district) → complex_ids
        if filters.get('quarter'):
            _qval = filters['quarter']
            from models import ResidentialComplex as _RCM_QA
            _qids = [r.id for r in _RCM_QA.query.filter(
                db.or_(
                    _RCM_QA.address_quarter.like(f'%{_qval}%'),
                    _RCM_QA.address_city_district.like(f'%{_qval}%')
                ),
                _RCM_QA.is_active == True
            ).all()]
            existing = set(repo_filters.get('complex_ids', []))
            repo_filters['complex_ids'] = list(existing & set(_qids)) if existing else _qids

        # Street filter (addr_street + address) → complex_ids; supports multiple streets
        _street_vals_sa = filters.get('streets') or ([filters['street']] if filters.get('street') else [])
        if _street_vals_sa:
            from models import ResidentialComplex as _RCM_SA
            from sqlalchemy import or_ as _or_sa
            _sid_set_sa = set()
            for _sv in _street_vals_sa:
                _sv = _sv.strip()
                if not _sv:
                    continue
                _sids = [r.id for r in _RCM_SA.query.filter(
                    _or_sa(
                        _RCM_SA.addr_street.ilike(f'%{_sv}%'),
                        _RCM_SA.address.ilike(f'%{_sv}%'),
                    ),
                    _RCM_SA.is_active == True
                ).all()]
                _sid_set_sa.update(_sids)
            existing = set(repo_filters.get('complex_ids', []))
            repo_filters['complex_ids'] = list(existing & _sid_set_sa) if existing else list(_sid_set_sa)

        # Floor filters
        if filters.get('floor_min'):
            try:
                repo_filters['floor_min'] = int(filters['floor_min'])
            except:
                pass
        if filters.get('floor_max'):
            try:
                repo_filters['floor_max'] = int(filters['floor_max'])
            except:
                pass
        
        
        # Object classes filter
        if filters.get('object_classes'):
            repo_filters['object_classes'] = filters['object_classes']
        
        # Renovation filter
        if filters.get('renovation'):
            repo_filters['renovation'] = filters['renovation']
        
        # Features filter
        if filters.get('features'):
            repo_filters['features'] = filters['features']
        
        # Building released filter
        if filters.get('building_released'):
            repo_filters['building_released'] = filters['building_released']
        
        # Completion filter (years)
        if filters.get('completion'):
            repo_filters['completion'] = filters['completion']
        
        # Floor options filter (not_first, not_last, last)
        if filters.get('floor_options'):
            repo_filters['floor_options'] = filters['floor_options']
        
        # Building floors range
        if filters.get('building_floors_min'):
            try:
                repo_filters['building_floors_min'] = int(filters['building_floors_min'])
            except:
                pass
        if filters.get('building_floors_max'):
            try:
                repo_filters['building_floors_max'] = int(filters['building_floors_max'])
            except:
                pass
        
        # Search filter
        search_text = filters.get('search', '').strip()
        if search_text:
            repo_filters['search'] = search_text
        
        # Parse sort_type — empty = relevance (diverse across complexes)
        if not sort_type:
            sort_by = 'relevance'
            sort_order = 'asc'
        else:
            sort_by = 'price'
            sort_order = 'asc'
            parts = sort_type.split('-')
            if len(parts) == 2:
                sort_by = parts[0]
                sort_order = parts[1]
        
        # Get properties with Repository
        
        # ✅ ADD: Include city_id from session/context
        if current_city:
            repo_filters['city_id'] = current_city.id
            print(f"✅ /properties: Filtering by city: {current_city.name} (ID: {current_city.id})")

        properties_list = PropertyRepository.get_all_active(
            limit=per_page,
            offset=offset,
            filters=repo_filters,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        total_properties = PropertyRepository.count_active(filters=repo_filters)
        
        # Convert to JSON format
        properties_data = []
        for prop in properties_list:
            try:
                complex_obj = prop.residential_complex
                developer_obj = prop.developer
                
                # Parse photos
                photos_list = []
                main_image = 'https://via.placeholder.com/400x300'
                
                if prop.main_image:
                    main_image = _proxy_cian_img(prop.main_image)
                
                if prop.gallery_images:
                    try:
                        if isinstance(prop.gallery_images, list):
                            photos_list = [_proxy_cian_img(u) for u in prop.gallery_images if u]
                        elif isinstance(prop.gallery_images, str):
                            raw_list = json.loads(prop.gallery_images)
                            photos_list = [_proxy_cian_img(u) for u in raw_list if u]
                        
                        if photos_list and not prop.main_image:
                            main_image = photos_list[0]
                    except:
                        pass
                
                # Calculate cashback
                cashback_rate = complex_obj.cashback_rate if complex_obj and complex_obj.cashback_rate else 3.5
                cashback_amount = int(prop.price * (cashback_rate / 100)) if prop.price else 0
                
                # Plan image: only use dedicated plan_image; do NOT fall back to main_image
                # (if null, frontend shows gallery images normally without "Планировка" badge)
                plan_image = _proxy_cian_img(prop.plan_image) if prop.plan_image else None

                property_dict = {
                    'id': prop.id,
                    'price': prop.price or 0,
                    'price_formatted': prop.formatted_price,
                    'area': prop.area or 0,
                    'rooms': prop.rooms or 0,
                    'room_description': prop.room_description,
                    'floor': prop.floor if prop.floor is not None else 1,
                    'total_floors': prop.total_floors if prop.total_floors is not None else 1,
                    'address': prop.address or (
                        ' '.join(filter(None, [complex_obj.addr_street, complex_obj.addr_house]))
                        if complex_obj and (complex_obj.addr_street or complex_obj.addr_house)
                        else ''
                    ),
                    'renovation': prop.renovation_type or 'no_renovation',
                    'renovation_display_name': PropertyRepository.get_renovation_display_name(prop.renovation_type),
                    'price_per_sqm': prop.price_per_sqm or (int(prop.price / prop.area) if prop.price and prop.area else 0),
                    'gallery': photos_list,
                    'image': main_image,
                    'plan_image': plan_image,
                    'living_area': round(float(prop.living_area), 1) if prop.living_area else None,
                    'kitchen_area': round(float(prop.kitchen_area), 1) if prop.kitchen_area else None,
                    'latitude': prop.latitude or (complex_obj.latitude if complex_obj else None),
                    'longitude': prop.longitude or (complex_obj.longitude if complex_obj else None),
                    'complex_name': complex_obj.name if complex_obj else '',
                    'residential_complex': complex_obj.name if complex_obj else '',
                    'developer': developer_obj.name if developer_obj else '',
                    'developer_name': developer_obj.name if developer_obj else '',
                    'cashback_rate': cashback_rate,
                    'cashback': cashback_amount,
                    'cashback_available': True,
                    'complex_object_class_display_name': complex_obj.object_class_display_name if complex_obj else 'Комфорт',
                    'deal_type': prop.deal_type or 'Первичка',
                    'description': prop.description or '',
                    'type': 'apartment',
                    'district': (prop.district.name if prop.district else None) or (complex_obj.district.name if complex_obj and complex_obj.district else None) or (complex_obj.address_city_district if complex_obj else '') or '',
                    'city_name': prop.city.name if prop.city else (current_city.name if current_city else ''),
                    'region_name': prop.city.region.name if (prop.city and prop.city.region) else '',
                    'mortgage_available': True,
                    'completion_date': f"{complex_obj.end_build_quarter} кв. {complex_obj.end_build_year}" if complex_obj and complex_obj.end_build_year else 'Уточняется',
                    'is_new': ((datetime.utcnow() - prop.created_at).days < 7) if prop.created_at else False,
                    'parsed_district': prop.parsed_district or (complex_obj.address_city_district if complex_obj else '') or '',
                    'parsed_settlement': prop.parsed_settlement or (complex_obj.address_quarter if complex_obj else '') or '',
                }
                properties_data.append(property_dict)
            except Exception as e:
                prop_id = getattr(prop_orm, "id", "unknown"); print(f"Error processing property {prop_id}: {e}")
                continue
        
        # Pagination info
        total_pages = (total_properties + per_page - 1) // per_page
        
        # ── Compute SEO H1 for AJAX mode (matches logic in routes/properties.py) ──
        city_name = current_city.name if current_city else 'Краснодар'
        city_prep = (current_city.name_prepositional if current_city and current_city.name_prepositional
                     else ('Краснодаре' if not current_city else city_name + 'е'))
        city_gen  = (current_city.name_genitive if current_city and current_city.name_genitive
                     else (city_name + 'а'))
        _rooms_map = {0: 'студии', 1: '1-комнатные квартиры', 2: '2-комнатные квартиры',
                      3: '3-комнатные квартиры', 4: '4-комнатные+ квартиры'}
        _rooms_filter = []
        if filters.get('rooms'):
            for r in filters['rooms']:
                try:
                    _rooms_filter.append(int(str(r).strip()))
                except:
                    pass
        _rc = (filters.get('residential_complex') or filters.get('rc_name') or '').strip()
        _dev_filter = ''
        if filters.get('developers') and isinstance(filters['developers'], list) and filters['developers']:
            _dev_filter = filters['developers'][0]
        elif filters.get('developer'):
            _dev_filter = filters['developer']
        seo_h1 = None
        if _rc:
            seo_h1 = f'Квартиры в ЖК {_rc}'
        elif len(_rooms_filter) == 1:
            _rn = _rooms_map.get(_rooms_filter[0], 'квартиры')
            seo_h1 = f'{_rn.capitalize()} в новостройках {city_gen}'
        elif len(_rooms_filter) > 1:
            seo_h1 = f'Квартиры в новостройках {city_gen}'
        if not seo_h1 and _dev_filter:
            seo_h1 = f'Новостройки от {_dev_filter}'
        if not seo_h1 and repo_filters.get('max_price'):
            _pmax_m = int(repo_filters['max_price'] / 1_000_000)
            seo_h1 = f'Квартиры до {_pmax_m} млн ₽ в {city_prep}'
        elif not seo_h1 and repo_filters.get('min_price'):
            _pmin_m = int(repo_filters['min_price'] / 1_000_000)
            seo_h1 = f'Квартиры от {_pmin_m} млн ₽ в {city_prep}'
        if not seo_h1:
            seo_h1 = f'Новостройки в {city_prep}'
        
        print(f"✅ API /api/properties/list: returned {len(properties_data)} properties, page {page}/{total_pages}, sort={sort_type}")
        
        return jsonify({
            'success': True,
            'properties': properties_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_properties,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages
            },
            'filters': filters,
            'sort': sort_type,
            'seo_h1': seo_h1
        })
        
    except Exception as e:
        print(f"ERROR in api_properties_list: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500



@public_api_bp.route('/api/properties/similar/<int:property_id>')
def api_properties_similar(property_id):
    """Похожие объекты для страницы детали: та же комнатность + город, цена ±30%.
    Возвращает до 8 объектов в том же формате, что /api/properties/list."""
    try:
        from repositories.property_repository import PropertyRepository
        from models import Property

        prop = Property.query.get(property_id)
        if not prop:
            return jsonify({'success': False, 'error': 'Property not found'}), 404

        city_id  = prop.city_id
        rooms    = prop.rooms        # None/0/1/2/3/4+
        price    = prop.price or 0

        repo_filters = {}
        if city_id:
            repo_filters['city_id'] = city_id
        if rooms is not None:
            repo_filters['rooms'] = [rooms]

        # Price ±30%
        if price > 0:
            repo_filters['min_price'] = int(price * 0.70)
            repo_filters['max_price'] = int(price * 1.30)

        candidates = PropertyRepository.get_all_active(
            limit=50, offset=0,
            filters=repo_filters,
            sort_by='price', sort_order='asc'
        )

        # Exclude self, pick 8 diversified by complex
        seen_complexes = {}
        result = []
        for p in candidates:
            if p.id == property_id:
                continue
            cid = p.complex_id or p.id
            seen_complexes[cid] = seen_complexes.get(cid, 0) + 1
            if seen_complexes[cid] > 2:
                continue
            result.append(p)
            if len(result) >= 8:
                break

        # If not enough, relax price constraint
        if len(result) < 4:
            fallback_filters = {'city_id': city_id} if city_id else {}
            if rooms is not None:
                fallback_filters['rooms'] = [rooms]
            extra = PropertyRepository.get_all_active(
                limit=20, offset=0,
                filters=fallback_filters,
                sort_by='price', sort_order='asc'
            )
            existing_ids = {p.id for p in result} | {property_id}
            for p in extra:
                if p.id not in existing_ids:
                    result.append(p)
                    existing_ids.add(p.id)
                if len(result) >= 8:
                    break

        # Serialize (same fields as /api/properties/list)
        data = []
        for p in result[:8]:
            try:
                complex_obj = p.residential_complex
                developer_obj = p.developer
                photos_list = []
                main_image = None
                if p.main_image:
                    main_image = _proxy_cian_img(p.main_image)
                if p.gallery_images:
                    try:
                        raw = p.gallery_images if isinstance(p.gallery_images, list) else json.loads(p.gallery_images)
                        photos_list = [_proxy_cian_img(u) for u in raw if u]
                        if photos_list and not main_image:
                            main_image = photos_list[0]
                    except Exception:
                        pass
                cashback_rate = complex_obj.cashback_rate if complex_obj and complex_obj.cashback_rate else 3.5
                cashback_amount = int(p.price * (cashback_rate / 100)) if p.price else 0
                mortgage_payment = getattr(p, 'mortgage_price', None) or 0
                data.append({
                    'id': p.id,
                    'price': p.price or 0,
                    'price_formatted': p.formatted_price,
                    'area': p.area or 0,
                    'rooms': p.rooms if p.rooms is not None else 0,
                    'floor': p.floor or 1,
                    'total_floors': p.total_floors or 1,
                    'address': p.address or (
                        ' '.join(filter(None, [complex_obj.addr_street, complex_obj.addr_house]))
                        if complex_obj and (complex_obj.addr_street or complex_obj.addr_house)
                        else ''
                    ),
                    'gallery': photos_list,
                    'image': main_image or 'https://via.placeholder.com/400x300',
                    'complex_name': complex_obj.name if complex_obj else '',
                    'residential_complex': complex_obj.name if complex_obj else '',
                    'developer': developer_obj.name if developer_obj else '',
                    'cashback': cashback_amount,
                    'cashback_rate': cashback_rate,
                    'mortgage_payment': mortgage_payment,
                    'completion_date': (f"{complex_obj.end_build_quarter} кв. {complex_obj.end_build_year}"
                                        if complex_obj and complex_obj.end_build_year else 'Уточняется'),
                    'district': (complex_obj.district.name if complex_obj and complex_obj.district else None) or (complex_obj.address_city_district if complex_obj else '') or '',
                    'city_id': city_id,
                    'city_slug': p.city.slug if p.city else 'krasnodar',
                    'city_name': p.city.name if p.city else '',
                    'parsed_district': p.parsed_district or (complex_obj.address_city_district if complex_obj else '') or '',
                    'parsed_settlement': p.parsed_settlement or (complex_obj.address_quarter if complex_obj else '') or '',
                })
            except Exception as e:
                continue

        return jsonify({'success': True, 'properties': data, 'total': len(data)})

    except Exception as e:
        logger.exception('api_properties_similar error')
        return jsonify({'success': False, 'error': str(e)}), 500


@public_api_bp.route('/api/properties/count')
def api_properties_count():
    """API endpoint для подсчета количества объектов с учетом фильтров (БЕЗ полной выборки данных)"""
    try:
        import json
        from repositories.property_repository import PropertyRepository
        
        # Parse filters using the same build_property_filters function
        _, _, filters = build_property_filters(request.args)
        
        # Convert filters to Repository format (same logic as /properties and /api/properties/list)
        repo_filters = {}
        
        # Price filters
        if filters.get('price_min'):
            try:
                price_val = float(filters['price_min'])
                # If price < 1000, assume it's in millions; else assume rubles
                repo_filters['min_price'] = int(price_val * 1000000) if price_val < 1000 else int(price_val)
            except:
                pass
        if filters.get('price_max'):
            try:
                price_val = float(filters['price_max'])
                # If price < 1000, assume it's in millions; else assume rubles
                repo_filters['max_price'] = int(price_val * 1000000) if price_val < 1000 else int(price_val)
            except:
                pass
                
        # Area filters
        if filters.get('area_min'):
            try:
                repo_filters['min_area'] = float(filters['area_min'])
            except:
                pass
        if filters.get('area_max'):
            try:
                repo_filters['max_area'] = float(filters['area_max'])
            except:
                pass
                
        # Rooms filter - ИСПРАВЛЕНО: безопасная обработка смешанных типов
        if filters.get('rooms'):
            try:
                room_values = []
                for r in filters['rooms']:
                    # Обрабатываем и строки и числа безопасно
                    if isinstance(r, str):
                        r_clean = r.strip()
                        if r_clean:
                            room_values.append(int(r_clean))
                    elif isinstance(r, int):
                        room_values.append(r)
                if room_values:
                    repo_filters['rooms'] = room_values
            except Exception as e:
                print(f"Warning: error parsing rooms filter: {e}")
                pass
        
        # Developers filter
        if filters.get('developers'):
            repo_filters['developers'] = filters['developers']
        if filters.get('developer'):
            if 'developers' not in repo_filters:
                repo_filters['developers'] = []
            if filters['developer'] not in repo_filters['developers']:
                repo_filters['developers'].append(filters['developer'])
                
        # Districts filter
        if filters.get('districts'):
            repo_filters['districts'] = filters['districts']
        
        # Residential complex filter
        if filters.get('residential_complex'):
            repo_filters['residential_complex'] = filters['residential_complex']
        
        # Floor filters
        if filters.get('floor_min'):
            try:
                repo_filters['floor_min'] = int(filters['floor_min'])
            except:
                pass
        if filters.get('floor_max'):
            try:
                repo_filters['floor_max'] = int(filters['floor_max'])
            except:
                pass
        
        # Object class filter
        if filters.get('object_classes'):
            repo_filters['object_classes'] = filters['object_classes']
        
        # Renovation filter
        if filters.get('renovation'):
            repo_filters['renovation'] = filters['renovation']
        
        # Features filter
        if filters.get('features'):
            repo_filters['features'] = filters['features']
        
        # Building released filter
        if filters.get('building_released'):
            repo_filters['building_released'] = filters['building_released']
        
        # Completion filter
        if filters.get('completion'):
            repo_filters['completion'] = filters['completion']
        
        # Floor options filter
        if filters.get('floor_options'):
            repo_filters['floor_options'] = filters['floor_options']
        if filters.get('features'):
            repo_filters['features'] = filters['features']
        
        # Building floors filters
        if filters.get('building_floors_min'):
            try:
                repo_filters['building_floors_min'] = int(filters['building_floors_min'])
            except:
                pass
        if filters.get('building_floors_max'):
            try:
                repo_filters['building_floors_max'] = int(filters['building_floors_max'])
            except:
                pass
        
        # Build year filters
        if filters.get('build_year_min'):
            try:
                repo_filters['build_year_min'] = int(filters['build_year_min'])
            except:
                pass
        if filters.get('build_year_max'):
            try:
                repo_filters['build_year_max'] = int(filters['build_year_max'])
            except:
                pass
        
        # Search query filter - support both 'q' and 'search' parameters
        search_query = request.args.get('q', request.args.get('search', '')).strip()
        if search_query:
            repo_filters['search'] = search_query
        elif filters.get('search'):
            repo_filters['search'] = filters['search']
        
        # ✅ КРИТИЧНО: City filter для правильного подсчета по городам
        if filters.get('city_id'):
            try:
                repo_filters['city_id'] = int(filters['city_id'])
            except (ValueError, TypeError):
                pass
        
        # Get total count from repository (optimized query - count only)
        total_count = PropertyRepository.get_filtered_count(**repo_filters)
        
        return jsonify({
            'success': True,
            'count': total_count,
            'filters': filters  # Return parsed filters for debugging
        })
        
    except Exception as e:
        print(f"Error in api_properties_count: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'count': 0}), 500

@public_api_bp.route('/api/residential-complexes-map')
def api_residential_complexes_map():
    """API endpoint for residential complexes with enhanced data for map"""
    import time as _time
    global _complexes_map_cache, _complexes_map_cache_ts
    # Get city_id from request args ONLY — no session fallback (fullscreen map needs all cities)
    city_id = request.args.get('city_id', type=int)
    cache_key = str(city_id or 'all')

    # Return cached response if fresh
    if (cache_key in _complexes_map_cache and cache_key in _complexes_map_cache_ts and
            _time.time() - _complexes_map_cache_ts[cache_key] < COMPLEXES_MAP_CACHE_TIMEOUT):
        return jsonify(_complexes_map_cache[cache_key])

    # Filter complexes by city_id (inline query - DO NOT modify load_residential_complexes())
    from models import ResidentialComplex, Property
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload
    # joinedload developer + district → eliminates N+1 (500 ЖК × 2 = 1000 lazy SELECTs)
    query = ResidentialComplex.query.options(
        joinedload(ResidentialComplex.developer),
        joinedload(ResidentialComplex.district),
    ).filter_by(is_active=True)
    if city_id:
        query = query.filter_by(city_id=city_id)
    
    complexes_db = query.all()
    
    # Get min/max prices for all complexes in one query
    price_stats = db.session.query(
        Property.complex_id,
        func.min(Property.price).label('min_price'),
        func.max(Property.price).label('max_price'),
        func.count(Property.id).label('count')
    ).filter(
        Property.is_active == True,
        Property.complex_id.isnot(None)
    ).group_by(Property.complex_id).all()
    
    price_map = {ps.complex_id: {'min': ps.min_price, 'max': ps.max_price, 'count': ps.count} for ps in price_stats}
    

    # Get room statistics for all complexes
    room_stats = db.session.query(
        Property.complex_id,
        Property.rooms,
        func.count(Property.id).label('count'),
        func.min(Property.price).label('min_price'),
        func.max(Property.price).label('max_price'),
        func.min(Property.area).label('min_area'),
        func.max(Property.area).label('max_area')
    ).filter(
        Property.is_active == True,
        Property.complex_id.isnot(None),
        Property.rooms.isnot(None)
    ).group_by(Property.complex_id, Property.rooms).all()
    
    # Build room_details map: {complex_id: {"Студия": {...}, "1-комн": {...}, ...}}
    room_map = {}
    for rs in room_stats:
        if rs.complex_id not in room_map:
            room_map[rs.complex_id] = {}
        # Map rooms number to Russian label
        if rs.rooms == 0:
            room_label = 'Студия'
        else:
            room_label = f'{rs.rooms}-комн'
        room_map[rs.complex_id][room_label] = {
            'count': rs.count,
            'min_price': rs.min_price,
            'max_price': rs.max_price,
            'min_area': float(rs.min_area) if rs.min_area else None,
            'max_area': float(rs.max_area) if rs.max_area else None
        }
    
    # Get sample gallery images from properties for each complex (one row per complex via DISTINCT ON)
    # PERF FIX: was loading all 52k rows; now loads only 1 row per complex (~329 rows)
    _photo_rows = db.session.execute(text("""
        SELECT DISTINCT ON (complex_id) complex_id, gallery_images
        FROM properties
        WHERE is_active = true
          AND complex_id IS NOT NULL
          AND gallery_images IS NOT NULL
          AND gallery_images != '[]'
        ORDER BY complex_id, id
    """)).fetchall()

    # Build gallery map: {complex_id: [photo1, photo2, ...]}
    gallery_map = {}
    for pp in _photo_rows:
        try:
            photos = json.loads(pp.gallery_images) if isinstance(pp.gallery_images, str) else pp.gallery_images
            if isinstance(photos, list):
                # Skip first photo (index 0) - it is usually a floor plan
                gallery_map[pp.complex_id] = [_proxy_cian_img(p) for p in photos[1:9] if p]
        except:
            pass
    
    # Convert to dict format for existing processing logic
    complexes = []
    for complex in complexes_db:
        stats = price_map.get(complex.id, {})
        # Proxy main_image
        _main_img = _proxy_cian_img(complex.main_image) if complex.main_image else None
        # Proxy gallery_images (stored as JSON string of external URLs)
        _gallery_proxied = []
        if complex.gallery_images:
            try:
                _raw = json.loads(complex.gallery_images) if isinstance(complex.gallery_images, str) else complex.gallery_images
                if isinstance(_raw, list):
                    _gallery_proxied = [_proxy_cian_img(u) for u in _raw if u]
            except:
                pass
        if not _gallery_proxied:
            _gallery_proxied = gallery_map.get(complex.id, [])
        complexes.append({
            'id': complex.id,
            'name': complex.name,
            'slug': complex.slug,
            'latitude': complex.latitude,
            'longitude': complex.longitude,
            'cashback_rate': complex.cashback_rate,
            'main_image': _main_img,
            'gallery_images': json.dumps(_gallery_proxied),
            'district': complex.district.name if complex.district else 'Не указан',
            'developer': complex.developer.name if complex.developer else 'Не указан',
            'developer_name': complex.developer.name if complex.developer else 'Не указан',
            'developer_id': complex.developer.id if complex.developer else None,
            'object_class': (getattr(complex, 'object_class_display_name', None) or getattr(complex, 'object_class', None) or 'Комфорт'),
            'address': complex.sales_address or complex.address or (complex.district.name + ', Краснодар' if complex.district else 'Краснодар'),
            'price_from': stats.get('min') or 0,
            'price_to': stats.get('max'),
            'available_apartments': stats.get('count', 0),
            'status': (
                'Сдан' if not complex.end_build_year or 
                (complex.end_build_year < 2026) or 
                (complex.end_build_year == 2026 and (complex.end_build_quarter or 1) <= 1)
                else f'{complex.end_build_quarter} кв. {complex.end_build_year}'
            ),
            'completion_year': complex.end_build_year,
            'completion_quarter': complex.end_build_quarter,
            'room_details': room_map.get(complex.id, {}),
        })
    
    # Pre-fetch buildings_count for ALL complexes in ONE query (avoid N+1)
    complex_ids = [c['id'] for c in complexes]
    buildings_count_map = {}
    if complex_ids:
        try:
            bc_rows = db.session.execute(text("""
                SELECT complex_id, COUNT(DISTINCT complex_building_name) as bc
                FROM properties
                WHERE is_active = true
                  AND complex_building_name IS NOT NULL
                  AND complex_id = ANY(:ids)
                GROUP BY complex_id
            """), {'ids': complex_ids}).fetchall()
            for row in bc_rows:
                buildings_count_map[row[0]] = row[1]
        except Exception:
            pass

    # Enhance complexes data for map
    for i, complex in enumerate(complexes):
        # Add coordinates using latitude/longitude if available — NO fake fallback
        if 'coordinates' not in complex:
            lat = complex.get('latitude')
            lng = complex.get('longitude')
            if lat and lng and float(lat) != 0 and float(lng) != 0:
                complex['coordinates'] = {'lat': float(lat), 'lng': float(lng)}
            # else: leave coordinates absent — JS will skip this complex for map markers

        complex['buildings_count'] = buildings_count_map.get(complex['id'], 1)
        if 'apartments_count' not in complex:
            complex['apartments_count'] = complex.get('available_apartments', 0)

    result = {"complexes": complexes, "total": len(complexes)}
    # Save to cache
    _complexes_map_cache[cache_key] = result
    _complexes_map_cache_ts[cache_key] = _time.time()
    return jsonify(result)

# Removed duplicate route - using api_property_detail instead

def _get_complex_data_normalized(complex_id):
    """
    Helper function to query complex data from normalized tables.
    Handles both residential_complexes.id and complex_id (legacy external ID).
    Returns tuple with result row and success boolean.
    """
    result = db.session.execute(text("""
        SELECT 
            rc.id,
            rc.name,
            MIN(p.price) as min_price,
            MAX(p.price) as max_price,
            COUNT(DISTINCT p.id) as apartments_count,
            COUNT(DISTINCT NULLIF(p.complex_building_name,'')) as buildings_count,
            d.name as developer_name,
            MIN(p.floor) as floors_min,
            MAX(p.total_floors) as floors_max,
            rc.end_build_year as completion_year,
            rc.end_build_quarter as completion_quarter,
            dis.name as district,
            COALESCE(MAX(p.address), rc.address) as address,
            rc.cashback_rate,
            COALESCE(rc.main_image, rc.gallery_images, MIN(p.gallery_images)) as photos,
            rc.object_class_display_name AS complex_object_class_display_name,
            rc.ceiling_height,
            rc.wall_material,
            rc.parking_type,
            rc.finishing_type
        FROM properties p
        JOIN residential_complexes rc ON p.complex_id = rc.id
        JOIN developers d ON p.developer_id = d.id
        LEFT JOIN districts dis ON rc.district_id = dis.id
        WHERE (rc.id = :complex_id OR rc.complex_id = :complex_id_str)
            AND p.is_active = true
        GROUP BY rc.id, rc.name, d.name, rc.end_build_year, rc.end_build_quarter, 
                 dis.name, rc.address, rc.cashback_rate, rc.gallery_images, 
                 rc.main_image, rc.object_class_display_name,
                 rc.ceiling_height, rc.wall_material, rc.parking_type, rc.finishing_type
        LIMIT 1
    """), {'complex_id': complex_id, 'complex_id_str': str(complex_id)}).fetchone()
    
    return result


@public_api_bp.route('/api/complex/<int:complex_id>')
def api_complex(complex_id):
    """API endpoint for single residential complex - MIGRATED TO NORMALIZED TABLES"""
    print(f"🔍 API /api/complex/{complex_id} called")
    
    try:
        # Query normalized tables (handles both rc.id and rc.complex_id)
        result = _get_complex_data_normalized(complex_id)
        
        if result:
            print(f"✅ Found complex {complex_id} in normalized tables: {result[1]}, apartments: {result[4]}, price: {result[2]}-{result[3]}")
            
            # Build completion date from year and quarter
            completion_date = 'Не указано'
            if result[9] and result[10]:  # year and quarter
                completion_date = f"{result[9]} г., {result[10]} кв."
            elif result[9]:  # only year
                completion_date = f"{result[9]} г."
            
            # ✅ Auto-calculate status based on completion date
            from datetime import datetime
            current_year = datetime.now().year
            current_quarter = (datetime.now().month - 1) // 3 + 1
            
            status = "Не указан"
            if result[9]:  # completion_year exists
                completion_year = int(result[9])
                if completion_year < current_year:
                    status = "Сдан"
                elif completion_year == current_year:
                    if result[10]:  # completion_quarter exists
                        completion_quarter = int(result[10])
                        if completion_quarter <= current_quarter:
                            status = "Сдан"
                        else:
                            status = "Строится"
                    else:
                        status = "Строится"
                else:
                    status = "Строится"
            
            # Extract first photo from photos array/string
            image_url = '/static/images/no-image.jpg'
            if result[14]:  # photos field
                try:
                    # Try parsing as JSON array
                    photos_data = json.loads(result[14])
                    if photos_data and isinstance(photos_data, list) and len(photos_data) > 0:
                        image_url = photos_data[0]
                except (json.JSONDecodeError, TypeError):
                    # If not JSON, treat as single image URL
                    if isinstance(result[14], str) and result[14].strip():
                        image_url = result[14]
            
            response_data = {
                'id': result[0],
                'name': result[1],
                'min_price': result[2],
                'price_from': result[2],
                'max_price': result[3],
                'price_to': result[3],
                'apartments_count': result[4],
                'properties_count': result[4],
                'buildings_count': result[5],
                'developer': result[6],
                'developer_name': result[6],
                'floors_min': result[7],
                'floors_max': result[8],
                'district': result[11] if len(result) > 11 else None,
                'district_name': result[11] if len(result) > 11 else None,
                'address': result[12] if len(result) > 12 else None,
                'cashback_rate': result[13] if len(result) > 13 else None,
                'housing_class': result[15] if len(result) > 15 else None,
                'object_class': result[15] if len(result) > 15 else None,
                'ceiling_height': result[16] if len(result) > 16 else None,
                'wall_material': result[17] if len(result) > 17 else None,
                'parking_type': result[18] if len(result) > 18 else None,
                'finishing_type': result[19] if len(result) > 19 else None,
                'status': status,
                'completion_date': completion_date,
                'image_url': image_url,
                'image': image_url,
                'main_image': image_url,
            }
            return jsonify(response_data)
        else:
            return jsonify({'error': 'Complex not found'}), 404
    except Exception as e:
        print(f'Error in /api/complex endpoint: {e}')
        return jsonify({'error': 'Internal server error'}), 500

@public_api_bp.route('/api/complex/<int:complex_id>/osm-boundary')
def api_complex_osm_boundary(complex_id):
    """Return per-corps coordinates for a residential complex from our DB.

    The JS client uses these coordinates to make targeted Overpass requests
    (around:80m per corps) and matches building polygons client-side.
    This avoids server-side HTTP timeouts and keeps Overpass queries precise.

    Response:
      {"ok": true, "corps": [
        {"name": "Литер 1", "lat": 44.9971, "lon": 39.0239, "count": 104},
        ...
      ]}
    """
    from models import ResidentialComplex
    from sqlalchemy import text as _text

    rc = ResidentialComplex.query.get_or_404(complex_id)

    # Try buildings table first (has stored boundary_geometry from TrendAgent)
    bld_rows = db.session.execute(_text("""
        SELECT b.name, b.boundary_geometry,
               AVG(p.latitude) AS lat, AVG(p.longitude) AS lon,
               COUNT(p.id) FILTER (WHERE p.is_active) AS cnt
        FROM buildings b
        LEFT JOIN properties p ON p.complex_id = b.complex_id
            AND p.complex_building_name = b.name
            AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL
        WHERE b.complex_id = :cid
        GROUP BY b.id, b.name, b.boundary_geometry
        ORDER BY b.name
    """), {'cid': complex_id}).fetchall()

    if bld_rows and any(r.lat or r.boundary_geometry for r in bld_rows):
        corps = []
        for r in bld_rows:
            entry = {
                'name':     r.name,
                'lat':      round(float(r.lat), 7) if r.lat else None,
                'lon':      round(float(r.lon), 7) if r.lon else None,
                'count':    int(r.cnt) if r.cnt else 0,
                'boundary': r.boundary_geometry or None,
            }
            corps.append(entry)
        # Filter out entries with no coords and no boundary
        corps = [c for c in corps if c['lat'] or c['boundary']]
        if corps:
            return jsonify({'ok': True, 'corps': corps})

    rows = db.session.execute(_text("""
        SELECT
            complex_building_name AS name,
            AVG(latitude)         AS lat,
            AVG(longitude)        AS lon,
            COUNT(*) FILTER (WHERE is_active) AS cnt
        FROM properties
        WHERE complex_id = :cid
          AND latitude  IS NOT NULL
          AND longitude IS NOT NULL
        GROUP BY complex_building_name
        HAVING COUNT(*) FILTER (WHERE is_active) > 0
        ORDER BY complex_building_name
    """), {'cid': complex_id}).fetchall()

    if rows:
        corps = [{'name': r.name, 'lat': round(float(r.lat), 7),
                  'lon': round(float(r.lon), 7), 'count': int(r.cnt),
                  'boundary': None}
                 for r in rows]
        return jsonify({'ok': True, 'corps': corps})

    # Fallback: no per-corps data, return complex centre
    if rc.latitude and rc.longitude:
        return jsonify({'ok': True, 'corps': [
            {'name': rc.name, 'lat': rc.latitude, 'lon': rc.longitude, 'count': 0}
        ]})
    return jsonify({'ok': False, 'error': 'no_coords'})


@public_api_bp.route('/api/complex/<int:complex_id>/chess')
def api_complex_chess(complex_id):
    """
    Шахматка квартир для конкретного корпуса.
    GET ?building_id=<int> (id из таблицы buildings)
    Возвращает:
      { ok, building: {id,name,total_floors,apartment_count},
        floors: { "24": [{apt}, ...], "23": [...], ... } }
    """
    building_id = request.args.get('building_id', type=int)
    if not building_id:
        # Return list of buildings for complex
        blds = db.session.execute(text("""
            SELECT id, name, total_floors, apartment_count,
                   end_build_year, end_build_quarter, released
            FROM buildings WHERE complex_id = :cid ORDER BY name
        """), {'cid': complex_id}).fetchall()
        buildings_list = []
        for b in blds:
            # Count apartments available in our properties table
            cnt = db.session.execute(text(
                "SELECT COUNT(*) FROM properties WHERE building_id=:bid AND is_active=true"
            ), {'bid': b.id}).scalar() or 0
            buildings_list.append({
                'id': b.id, 'name': b.name,
                'total_floors': b.total_floors,
                'apartment_count': cnt or b.apartment_count,
                'end_build_year': b.end_build_year,
                'end_build_quarter': b.end_build_quarter,
                'released': b.released,
            })
        return jsonify({'ok': True, 'buildings': buildings_list})

    # Verify building belongs to complex
    bld_row = db.session.execute(text("""
        SELECT id, name, total_floors, apartment_count, end_build_year, end_build_quarter, released
        FROM buildings WHERE id=:bid AND complex_id=:cid
    """), {'bid': building_id, 'cid': complex_id}).fetchone()
    if not bld_row:
        return jsonify({'ok': False, 'error': 'building_not_found'}), 404

    # Load all apartments for this building
    rows = db.session.execute(text("""
        SELECT
            id, slug, ta_crm_id, apartment_number, rooms, property_type,
            area, area_kitchen, floor, total_floors,
            price, price_per_sqm,
            status, ta_status_color, ta_status_border_color,
            floor_plan_image, renovation_type, view_from_window,
            ta_north, ta_reward_label, ta_finishing_main
        FROM properties
        WHERE building_id = :bid AND is_active = true
        ORDER BY floor ASC, ta_crm_id ASC NULLS LAST
    """), {'bid': building_id}).fetchall()

    # Group by floor
    floors_dict = {}
    for r in rows:
        f = r.floor or 0
        if f not in floors_dict:
            floors_dict[f] = []
        # Apartment number: ta_crm_id preferred, fallback apartment_number
        apt_num = int(r.ta_crm_id) if r.ta_crm_id else (r.apartment_number or 0)
        # Status color — use stored API color, fallback by status name
        color  = r.ta_status_color or _chess_status_color(r.status)
        border = r.ta_status_border_color or _chess_status_border(r.status)
        floors_dict[f].append({
            'id':         r.id,
            'slug':       r.slug or '',
            'number':     apt_num,
            'rooms':      r.rooms,
            'room_name':  r.property_type or _rooms_short(r.rooms),
            'area':       float(r.area) if r.area else None,
            'area_kitchen': float(r.area_kitchen) if r.area_kitchen else None,
            'floor':      f,
            'total_floors': r.total_floors or bld_row.total_floors,
            'price':      int(r.price) if r.price else None,
            'price_sqm':  int(r.price_per_sqm) if r.price_per_sqm else None,
            'status':     r.status or 'Свободная',
            'color':      color,
            'border':     border,
            'plan':       r.floor_plan_image or '',
            'renovation': r.renovation_type or '',
            'view':       r.view_from_window or '',
        })

    # Sort floors descending (top floor first for UI)
    floors_sorted = {str(k): floors_dict[k] for k in sorted(floors_dict.keys(), reverse=True)}

    return jsonify({
        'ok': True,
        'building': {
            'id': bld_row.id,
            'name': bld_row.name,
            'total_floors': bld_row.total_floors,
            'apartment_count': len(rows),
            'end_build_year': bld_row.end_build_year,
            'end_build_quarter': bld_row.end_build_quarter,
            'released': bld_row.released,
        },
        'floors': floors_sorted,
        'total': len(rows),
    })


def _chess_status_color(status: str) -> str:
    s = (status or '').lower()
    if 'своб' in s:     return '#dcfce7'
    if 'прод' in s:     return '#fee2e2'
    if 'брон' in s:     return '#fef3c7'
    if 'запрос' in s:   return '#e0f2fe'
    if 'резерв' in s:   return '#fef3c7'
    return '#f1f5f9'


def _chess_status_border(status: str) -> str:
    s = (status or '').lower()
    if 'своб' in s:     return '#16a34a'
    if 'прод' in s:     return '#dc2626'
    if 'брон' in s:     return '#d97706'
    if 'запрос' in s:   return '#0369a1'
    if 'резерв' in s:   return '#d97706'
    return '#cbd5e1'


def _rooms_short(rooms) -> str:
    if rooms is None: return '?'
    m = {0: 'Ст', 1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 22: '2Е', 23: '3Е', 24: '4Е', 60: 'Апт'}
    return m.get(int(rooms), str(rooms))


@public_api_bp.route('/api/complex-mini-card')
def api_complex_mini_card():
    """Лёгкий эндпоинт: мини-карточка ЖК по названию для страницы поиска квартир."""
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    try:
        rc = ResidentialComplex.query.filter(
            db.func.lower(ResidentialComplex.name) == name.lower(),
            ResidentialComplex.is_active == True
        ).first()
        if not rc:
            rc = ResidentialComplex.query.filter(
                ResidentialComplex.name.ilike(f'%{name}%'),
                ResidentialComplex.is_active == True
            ).first()
        if not rc:
            return jsonify({'found': False}), 404

        # Room stats per type (count + min price)
        room_rows = db.session.execute(text(
            "SELECT COALESCE(rooms,0), COUNT(*), MIN(price) FROM properties "
            "WHERE complex_id=:cid AND is_active=TRUE GROUP BY COALESCE(rooms,0) ORDER BY COALESCE(rooms,0)"
        ), {'cid': rc.id}).fetchall()
        room_stats = {}
        min_prices = {}
        total = 0
        for rr in room_rows:
            r_key = int(rr[0])
            room_stats[r_key] = int(rr[1])
            if rr[2]: min_prices[r_key] = int(rr[2])
            total += int(rr[1])

        dev_name = None
        dev_logo = None
        if rc.developer_id:
            from models import Developer
            dev = Developer.query.get(rc.developer_id)
            if dev:
                dev_name = dev.name
                dev_logo = dev.logo_url if hasattr(dev, 'logo_url') else None

        completion = None
        if rc.end_build_year:
            completion = f'{rc.end_build_quarter} кв. {rc.end_build_year}' if rc.end_build_quarter else str(rc.end_build_year)

        image = rc.main_image or ''
        if not image and rc.gallery_images:
            import json as _json
            try:
                imgs = _json.loads(rc.gallery_images)
                image = imgs[0] if imgs else ''
            except Exception:
                pass

        city_slug = 'krasnodar'
        if rc.city_id:
            from models import City
            city_obj = City.query.get(rc.city_id)
            if city_obj and city_obj.slug:
                city_slug = city_obj.slug

        # Derive status from end_build_year
        from datetime import date as _date
        cur_year = _date.today().year
        if rc.end_build_year and rc.end_build_year < cur_year:
            status_label = 'Сдан'
        elif rc.end_build_year and rc.end_build_year == cur_year:
            status_label = 'Сдаётся в этом году'
        else:
            status_label = 'Строится'

        return jsonify({
            'found': True,
            'id': rc.id,
            'name': rc.name,
            'slug': rc.slug,
            'url': f'/{city_slug}/zk/{rc.slug}' if rc.slug else None,
            'image': image,
            'developer_name': dev_name,
            'developer_logo': dev_logo,
            'status': status_label,
            'completion': completion,
            'housing_class': getattr(rc, 'object_class_display_name', None) or '',
            'total': total,
            'room_stats': room_stats,
            'min_prices': min_prices,
        })
    except Exception as e:
        print(f'Error in /api/complex-mini-card: {e}')
        return jsonify({'error': 'Internal server error'}), 500


def _get_complexes_batch_optimized(complex_ids):
    """
    Bulk query for multiple complexes from normalized tables - SINGLE QUERY.
    Returns dict mapping complex_id -> result tuple (same format as _get_complex_data_normalized).
    """
    if not complex_ids:
        return {}
    
    # Single bulk query using IN clause
    results = db.session.execute(text("""
        SELECT 
            rc.id,
            rc.name,
            MIN(p.price) as min_price,
            MAX(p.price) as max_price,
            COUNT(DISTINCT p.id) as apartments_count,
            COUNT(DISTINCT NULLIF(p.complex_building_name,'')) as buildings_count,
            d.name as developer_name,
            MIN(p.floor) as floors_min,
            MAX(p.total_floors) as floors_max,
            rc.end_build_year as completion_year,
            rc.end_build_quarter as completion_quarter,
            dis.name as district,
            COALESCE(MAX(p.address), rc.address) as address,
            rc.cashback_rate,
            COALESCE(rc.main_image, rc.gallery_images, MIN(p.gallery_images)) as photos,
            rc.object_class_display_name AS complex_object_class_display_name
        FROM properties p
        JOIN residential_complexes rc ON p.complex_id = rc.id
        JOIN developers d ON p.developer_id = d.id
        LEFT JOIN districts dis ON rc.district_id = dis.id
        WHERE (rc.id IN :complex_ids OR rc.complex_id::text = ANY(ARRAY[:complex_ids_str]))
            AND p.is_active = true
        GROUP BY rc.id, rc.name, d.name, rc.end_build_year, rc.end_build_quarter, 
                 dis.name, rc.address, rc.cashback_rate, rc.gallery_images, 
                 rc.main_image, rc.object_class_display_name
    """), {
        'complex_ids': tuple(complex_ids),
        'complex_ids_str': [str(cid) for cid in complex_ids]
    }).fetchall()
    
    # Build dict mapping id -> result tuple
    result_dict = {}
    for row in results:
        result_dict[row[0]] = row  # row[0] is rc.id
    
    return result_dict

@public_api_bp.route('/api/price-history/complex/<int:complex_id>')
def api_price_history_complex(complex_id):
    from models import PriceHistory, ResidentialComplex, Property
    from sqlalchemy import func as sqlfunc
    try:
        records = PriceHistory.query.filter_by(
            complex_id=complex_id,
            record_type='complex'
        ).order_by(PriceHistory.year.asc(), PriceHistory.month.asc()).all()

        months_ru = ['', 'янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

        data = []
        prev = None
        for r in records:
            change_pct = None
            if prev and prev.avg_price and r.avg_price and prev.avg_price > 0:
                change_pct = round((r.avg_price - prev.avg_price) / prev.avg_price * 100, 1)

            label = f"{months_ru[r.month]}\n{r.year}" if r.month else str(r.year)
            data.append({
                'label': label,
                'month': r.month,
                'year': r.year,
                'avg_price': r.avg_price,
                'avg_price_per_sqm': r.avg_price_per_sqm,
                'min_price': r.min_price,
                'max_price': r.max_price,
                'properties_count': r.properties_count,
                'price_change_percent': change_pct if change_pct is not None else r.price_change_percent
            })
            prev = r

        complex_obj = ResidentialComplex.query.get(complex_id)

        # If ≤ 1 data point, synthesize current snapshot + 5 synthetic past months
        # so Chart.js always has enough points to render a meaningful line
        if len(data) <= 1 and complex_obj:
            from datetime import date as _date
            props = Property.query.filter_by(
                complex_id=complex_id, is_active=True
            ).filter(Property.price.isnot(None)).all()

            if props:
                prices = [p.price for p in props if p.price]
                ppsm = [p.price_per_sqm for p in props if p.price_per_sqm]
                now = _date.today()
                avg_p = int(sum(prices) / len(prices)) if prices else None
                avg_psm = int(sum(ppsm) / len(ppsm)) if ppsm else None
                min_p = min(prices) if prices else None
                max_p = max(prices) if prices else None
                cnt = len(prices)

                # If no records at all, add the current snapshot as anchor
                if not data:
                    data.append({
                        'label': f"{months_ru[now.month]}\n{now.year}",
                        'month': now.month,
                        'year': now.year,
                        'avg_price': avg_p,
                        'avg_price_per_sqm': avg_psm,
                        'min_price': min_p,
                        'max_price': max_p,
                        'properties_count': cnt,
                        'price_change_percent': None,
                        'is_current': True,
                    })

                # Prepend 5 synthetic past months at the same price level
                # so the chart shows a flat baseline before the first real point.
                anchor = data[0]
                ay, am = anchor['year'], anchor['month']
                synthetic = []
                for i in range(5, 0, -1):
                    pm = am - i
                    py = ay
                    while pm <= 0:
                        pm += 12
                        py -= 1
                    synthetic.append({
                        'label': f"{months_ru[pm]}\n{py}",
                        'month': pm,
                        'year': py,
                        'avg_price': anchor.get('avg_price'),
                        'avg_price_per_sqm': anchor.get('avg_price_per_sqm'),
                        'min_price': anchor.get('min_price'),
                        'max_price': anchor.get('max_price'),
                        'properties_count': anchor.get('properties_count'),
                        'price_change_percent': None,
                        'is_synthetic': True,
                    })
                data = synthetic + data

        return jsonify({
            'success': True,
            'complex_name': complex_obj.name if complex_obj else '',
            'data': data,
            'total_records': len(data)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@public_api_bp.route('/api/price-history/property/<int:property_id>')
def api_price_history_property(property_id):
    from models import PriceHistory, Property
    try:
        records = PriceHistory.query.filter_by(
            property_id=property_id,
            record_type='property'
        ).order_by(PriceHistory.year.asc(), PriceHistory.month.asc()).all()

        months_ru = ['', 'янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

        data = []
        prev = None
        for r in records:
            change_pct = None
            if prev and prev.price and r.price and prev.price > 0:
                change_pct = round((r.price - prev.price) / prev.price * 100, 1)

            label = f"{months_ru[r.month]}\n{r.year}" if r.month else str(r.year)
            data.append({
                'label': label,
                'month': r.month,
                'year': r.year,
                'price': r.price,
                'price_per_sqm': r.price_per_sqm,
                'price_change_percent': change_pct if change_pct is not None else r.price_change_percent
            })
            prev = r

        # If ≤ 1 data point, synthesize current snapshot + 5 synthetic past months
        if len(data) <= 1:
            prop = Property.query.get(property_id)
            if prop and prop.price:
                from datetime import date as _date
                now = _date.today()
                psm = prop.price_per_sqm
                if not psm and prop.area and prop.area > 0:
                    psm = int(prop.price / prop.area)

                if not data:
                    data.append({
                        'label': f"{months_ru[now.month]}\n{now.year}",
                        'month': now.month,
                        'year': now.year,
                        'price': prop.price,
                        'price_per_sqm': psm,
                        'price_change_percent': None,
                        'is_current': True,
                    })

                anchor = data[0]
                ay, am = anchor['year'], anchor['month']
                synthetic = []
                for i in range(5, 0, -1):
                    pm = am - i
                    py = ay
                    while pm <= 0:
                        pm += 12
                        py -= 1
                    synthetic.append({
                        'label': f"{months_ru[pm]}\n{py}",
                        'month': pm,
                        'year': py,
                        'price': anchor.get('price'),
                        'price_per_sqm': anchor.get('price_per_sqm'),
                        'price_change_percent': None,
                        'is_synthetic': True,
                    })
                data = synthetic + data

        return jsonify({
            'success': True,
            'data': data,
            'total_records': len(data)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@public_api_bp.route('/api/complexes/batch', methods=['POST'])
def api_complexes_batch():
    """Batch API endpoint to get multiple complexes at once - OPTIMIZED"""
    try:
        data = request.get_json()
        complex_ids = data.get('ids', [])
        
        if not complex_ids or not isinstance(complex_ids, list):
            return jsonify({'error': 'Invalid request, expected {"ids": [1, 2, 3]}'}), 400
        
        # Convert string IDs to integers
        try:
            complex_ids = [int(cid) for cid in complex_ids if cid]
        except (ValueError, TypeError) as e:
            return jsonify({'error': f'Invalid ID format: {str(e)}'}), 400
        
        # ✅ SINGLE QUERY: Load all complexes at once using bulk helper function
        complexes_dict = _get_complexes_batch_optimized(complex_ids)
        
        results = {}
        for complex_id in complex_ids:
            result = complexes_dict.get(complex_id)
            if result:
                # Build completion date
                completion_date = 'Не указано'
                if result[9] and result[10]:
                    completion_date = f"{result[9]} г., {result[10]} кв."
                elif result[9]:
                    completion_date = f"{result[9]} г."
                
                # Extract image
                image_url = '/static/images/no-image.jpg'
                if result[14]:
                    try:
                        photos_data = json.loads(result[14])
                        if photos_data and isinstance(photos_data, list) and len(photos_data) > 0:
                            image_url = photos_data[0]
                    except (json.JSONDecodeError, TypeError):
                        if isinstance(result[14], str) and result[14].strip():
                            image_url = result[14]
                
                response_data = {
                    'id': result[0],
                    'name': result[1],
                    'min_price': result[2],
                    'price_from': result[2],
                    'max_price': result[3],
                    'price_to': result[3],
                    'apartments_count': result[4],
                    'properties_count': result[4],
                    'buildings_count': result[5],
                    'developer': result[6],
                    'developer_name': result[6],
                    'floors_min': result[7] if result[7] else 'Не указано',
                    'floors_max': result[8],
                    'completion_date': completion_date,
                    'district': result[11] or 'Не указано',
                    'address': result[12] or 'Не указано',
                    'cashback_rate': result[13] or 0,
                    'cashback_percent': result[13] or 0,
                    'object_class': result[15] or 'Не указано',
                    'status': 'В продаже',
                    'image': image_url,
                    'original_id': complex_id
                }
                results[str(complex_id)] = response_data
        
        return jsonify({'success': True, 'items': results})
    except Exception as e:
        print(f"❌ Error in batch complexes: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500




@public_api_bp.route('/api/mini-map/properties')
def api_mini_map_properties():
    """API endpoint for mini-map: return property coordinates with FILTER support"""
    from repositories.property_repository import PropertyRepository
    
    try:
        # Get city context from request params or session
        city_id = request.args.get('city_id', type=int)
        if not city_id and 'city_id' in session:
            city_id = session['city_id']
            print(f"🗺️ Mini-map API: Using city_id from session: {city_id}")
        elif city_id:
            print(f"🗺️ Mini-map API: Using city_id from request: {city_id}")
        else:
            print(f"⚠️ Mini-map API: No city_id, loading all properties")
        
        # Build filters - support all main filter types
        filters = {}
        if city_id:
            filters['city_id'] = city_id
        
        # ✅ CRITICAL: Apply same filters as property list
        if request.args.get('residential_complex'):
            filters['residential_complex'] = request.args.get('residential_complex')
            print(f"🗺️ Mini-map: Filtering by residential_complex: {filters['residential_complex']}")
        
        if request.args.get('developer'):
            filters['developer'] = request.args.get('developer')
            print(f"🗺️ Mini-map: Filtering by developer: {filters['developer']}")
        
        rooms_list = request.args.getlist('rooms') or request.args.getlist('rooms[]')
        if rooms_list:
            all_rooms = []
            for r in rooms_list:
                all_rooms.extend(r.split(','))
            filters['rooms'] = [int(r) for r in all_rooms if r.isdigit()]
            print(f"🗺️ Mini-map: Filtering by rooms: {filters['rooms']}")
        
        if request.args.get('price_min'):
            filters['price_min'] = request.args.get('price_min', type=int)
        if request.args.get('price_max'):
            filters['price_max'] = request.args.get('price_max', type=int)
        
        if request.args.get('area_min'):
            filters['area_min'] = request.args.get('area_min', type=float)
        if request.args.get('area_max'):
            filters['area_max'] = request.args.get('area_max', type=float)
        
        developers_list = request.args.getlist('developers') or request.args.getlist('developers[]')
        if developers_list:
            all_devs = []
            for d in developers_list:
                all_devs.extend(d.split(','))
            filters['developers'] = [x.strip() for x in all_devs if x.strip()]
        
        if request.args.get('search'):
            filters['search'] = request.args.get('search')
            print(f"🗺️ Mini-map: Filtering by search: {filters['search']}")
        
        # District ID filter — locked SEO page filter (precise FK)
        if request.args.get('district_id'):
            try:
                filters['district_id'] = int(request.args.get('district_id'))
                print(f"🗺️ Mini-map: Filtering by district_id: {filters['district_id']}")
            except (ValueError, TypeError):
                pass

        districts_list = request.args.getlist('districts') or request.args.getlist('districts[]')
        _dist_singular = request.args.get('district', '').strip()
        if _dist_singular and _dist_singular not in districts_list:
            districts_list.append(_dist_singular)
        if districts_list:
            all_dists = []
            for d in districts_list:
                all_dists.extend(d.split(','))
            slug_list = [x.strip() for x in all_dists if x.strip()]
            # Resolve slugs/names → district IDs for precise FK filter
            from models import District as _DistMM
            _dist_ids = []
            _slug_names = []
            for slug in slug_list:
                _d = _DistMM.query.filter_by(slug=slug).first()
                if not _d:
                    _d = _DistMM.query.filter(_DistMM.name.ilike(slug)).first()
                if not _d:
                    _d = _DistMM.query.filter(_DistMM.name.ilike(f'%{slug}%')).first()
                if _d:
                    _dist_ids.append(_d.id)
                else:
                    _slug_names.append(slug)
            if _dist_ids:
                filters['district_id_in'] = _dist_ids
            if _slug_names:
                # Truly unresolved — pass through for best-effort address matching
                filters['districts'] = _slug_names
        
        if request.args.get('property_type') and request.args.get('property_type') != 'all':
            property_type_map = {
                'apartments': 'Квартира',
                'houses': 'Дом', 
                'townhouses': 'Таунхаус',
                'penthouses': 'Пентхаус',
                'apartments_commercial': 'Апартаменты'
            }
            raw_type = request.args.get('property_type')
            filters['property_type'] = property_type_map.get(raw_type, raw_type)
        
        for list_key in ['completion', 'object_classes', 'renovation', 'features', 'building_released', 'floor_options', 'building_types']:
            vals = request.args.getlist(list_key) or request.args.getlist(list_key + '[]')
            if vals:
                all_vals = []
                for v in vals:
                    all_vals.extend(v.split(','))
                filters[list_key] = [x.strip() for x in all_vals if x.strip()]
        
        if request.args.get('floor_min'):
            filters['floor_min'] = request.args.get('floor_min')
        if request.args.get('floor_max'):
            filters['floor_max'] = request.args.get('floor_max')
        if request.args.get('building_floors_min'):
            filters['building_floors_min'] = request.args.get('building_floors_min')
        if request.args.get('building_floors_max'):
            filters['building_floors_max'] = request.args.get('building_floors_max')

        # Quarter / city-district filter (address_quarter or address_city_district from RC)
        _mm_qrt = request.args.get('quarter', '').strip()
        if _mm_qrt:
            filters['quarter'] = _mm_qrt

        active_filters = [k for k in filters.keys() if k != 'city_id']
        if active_filters:
            print(f"🗺️ Mini-map: Active filters: {active_filters}")
        
        # Get coordinates — honour optional limit param (mobile sends 300)
        req_limit = request.args.get('limit', type=int)
        coord_limit = min(req_limit, 2000) if req_limit and req_limit > 0 else 1000
        properties = PropertyRepository.get_all_active(limit=coord_limit, filters=filters)
        
        coordinates = []
        for prop in properties:
            lat = getattr(prop, "latitude", None)
            lng = getattr(prop, "longitude", None)
            
            if (not lat or not lng or lat == 0 or lng == 0) and prop.residential_complex:
                lat = prop.residential_complex.latitude
                lng = prop.residential_complex.longitude
            
            if lat and lng and lat != 0 and lng != 0:
                coordinates.append({
                    'lat': float(lat),
                    'lng': float(lng)
                })
        
        print(f"✅ Mini-map: Loaded {len(coordinates)} property coordinates (filters: {list(filters.keys())})")
        return jsonify({'success': True, 'coordinates': coordinates, 'count': len(coordinates)})
    except Exception as e:
        print(f"❌ Error in mini-map properties: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500



_AGG_MAP_CACHE = {}
_AGG_MAP_CACHE_TTL = 60

@public_api_bp.route('/api/map-properties/aggregated')
def api_map_properties_aggregated():
    """
    Fast aggregated endpoint for fullscreen map markers — groups apartments
    by coordinate point (building) like CIAN does. Returns one marker per
    unique (lat,lng) with count + price range + status, in a single SQL query.
    """
    from models import Property, ResidentialComplex
    from sqlalchemy import func, case
    import time as _t

    try:
        _cache_allowed_params = {'city_id', '_'}
        _incoming_params = set(request.args.keys())
        _is_cacheable = _incoming_params.issubset(_cache_allowed_params)
        _cache_key = None
        if _is_cacheable:
            _cache_key = ('agg', request.args.get('city_id') or session.get('city_id'))
            _hit = _AGG_MAP_CACHE.get(_cache_key)
            if _hit and (_t.time() - _hit[0]) < _AGG_MAP_CACHE_TTL:
                resp = jsonify(_hit[1])
                resp.headers['X-Cache'] = 'HIT'
                return resp
        if len(_AGG_MAP_CACHE) > 64:
            _AGG_MAP_CACHE.clear()
        # scope=all OR bbox provided → no city filter (user panned to another city)
        scope_all = request.args.get('scope') == 'all' or request.args.get('all_cities') == '1'
        explicit_city = request.args.get('city_id', type=int)
        bbox_provided = all(request.args.get(k) for k in ['lat_min', 'lat_max', 'lng_min', 'lng_max'])
        if scope_all or bbox_provided:
            city_id = explicit_city  # respect explicit city_id, but no session fallback
        else:
            city_id = explicit_city or session.get('city_id')

        # Coalesce property coordinates with complex coordinates as fallback
        lat_col = func.coalesce(Property.latitude, ResidentialComplex.latitude)
        lng_col = func.coalesce(Property.longitude, ResidentialComplex.longitude)
        # Round to 5 decimals so all apartments in the same building share a point
        lat_round = func.round(lat_col.cast(db.Numeric), 5)
        lng_round = func.round(lng_col.cast(db.Numeric), 5)

        # Group by COORDS + COMPLEX + BUILDING so each corpus is a separate point (CIAN-style)
        q = db.session.query(
            lat_round.label('lat'),
            lng_round.label('lng'),
            Property.complex_id.label('complex_id'),
            func.coalesce(Property.complex_building_name, '').label('building_name'),
            func.count(Property.id).label('count'),
            func.min(Property.price).label('min_price'),
            func.max(Property.price).label('max_price'),
            func.min(ResidentialComplex.name).label('complex_name'),
            func.min(ResidentialComplex.slug).label('complex_slug'),
            func.min(Property.address).label('address'),
            func.bool_or(func.lower(func.coalesce(Property.deal_type, '')).in_(['presale', 'первичка'])).label('has_presale'),
            func.min(ResidentialComplex.end_build_year).label('end_build_year'),
            func.min(ResidentialComplex.end_build_quarter).label('end_build_quarter'),
            func.min(ResidentialComplex.main_image).label('main_image'),
            func.min(ResidentialComplex.address_city_district).label('rc_district'),
            func.min(ResidentialComplex.address_quarter).label('rc_quarter'),
        ).outerjoin(ResidentialComplex, Property.complex_id == ResidentialComplex.id) \
         .filter(Property.is_active == True) \
         .filter(lat_col.isnot(None), lng_col.isnot(None)) \
         .filter(lat_col != 0, lng_col != 0)

        if city_id:
            q = q.filter(Property.city_id == city_id)

        # Viewport bbox filter — load only what's visible on screen (CIAN-style)
        lat_min = request.args.get('lat_min', type=float)
        lat_max = request.args.get('lat_max', type=float)
        lng_min = request.args.get('lng_min', type=float)
        lng_max = request.args.get('lng_max', type=float)
        if lat_min is not None and lat_max is not None and lng_min is not None and lng_max is not None:
            q = q.filter(lat_col.between(lat_min, lat_max), lng_col.between(lng_min, lng_max))

        # Optional filters (same set as the list page)
        rooms_list = request.args.getlist('rooms') or request.args.getlist('rooms[]')
        if rooms_list:
            all_rooms = []
            for r in rooms_list:
                all_rooms.extend(str(r).split(','))
            rooms_ints = [int(r) for r in all_rooms if str(r).isdigit()]
            if rooms_ints:
                q = q.filter(Property.rooms.in_(rooms_ints))

        if request.args.get('price_min'):
            q = q.filter(Property.price >= request.args.get('price_min', type=int))
        if request.args.get('price_max'):
            q = q.filter(Property.price <= request.args.get('price_max', type=int))
        if request.args.get('area_min'):
            q = q.filter(Property.area >= request.args.get('area_min', type=float))
        if request.args.get('area_max'):
            q = q.filter(Property.area <= request.args.get('area_max', type=float))
        if request.args.get('floor_min'):
            q = q.filter(Property.floor >= request.args.get('floor_min', type=int))
        if request.args.get('floor_max'):
            q = q.filter(Property.floor <= request.args.get('floor_max', type=int))

        if request.args.get('residential_complex'):
            rc = request.args.get('residential_complex')
            if str(rc).isdigit():
                q = q.filter(Property.complex_id == int(rc))
            else:
                q = q.filter(ResidentialComplex.slug == rc)

        if request.args.get('property_type') and request.args.get('property_type') != 'all':
            type_map = {
                'apartments': 'Квартира', 'houses': 'Дом',
                'townhouses': 'Таунхаус', 'penthouses': 'Пентхаус',
                'apartments_commercial': 'Апартаменты'
            }
            raw = request.args.get('property_type')
            q = q.filter(Property.property_type == type_map.get(raw, raw))

        # Completion year filter (chips: 2024/2025/2026/2027+)
        if request.args.get('completion'):
            completion_years = [y.strip() for y in request.args.get('completion').split(',') if y.strip()]
            if completion_years:
                yr_conds = []
                for yr in completion_years:
                    if yr == '2027+':
                        yr_conds.append(ResidentialComplex.end_build_year >= 2027)
                    elif yr.isdigit():
                        yr_conds.append(ResidentialComplex.end_build_year == int(yr))
                if yr_conds:
                    q = q.filter(db.or_(*yr_conds))

        # Building status filter: use end_build_year (same logic as PropertyRepository)
        if request.args.get('building_status'):
            from datetime import datetime as _dt
            _cur_year = _dt.now().year
            statuses = [s.strip() for s in request.args.get('building_status').split(',') if s.strip()]
            if statuses:
                st_conds = []
                for st in statuses:
                    if st == 'delivered':
                        st_conds.append(ResidentialComplex.end_build_year < _cur_year)
                    elif st == 'under_construction':
                        st_conds.append(db.or_(
                            ResidentialComplex.end_build_year >= _cur_year,
                            ResidentialComplex.end_build_year.is_(None)
                        ))
                if st_conds:
                    q = q.filter(db.or_(*st_conds))

        # Object class filter (field: object_class_display_name = "Комфорт"/"Бизнес"/etc)
        if request.args.get('object_classes'):
            classes_list = [c.strip() for c in request.args.get('object_classes').split(',') if c.strip()]
            if classes_list:
                q = q.filter(ResidentialComplex.object_class_display_name.in_(classes_list))

        # District FK filter — same resolution as mini-map and list endpoints
        _districts_list_agg = request.args.getlist('districts') or request.args.getlist('districts[]')
        _dist_singular_agg = request.args.get('district', '').strip()
        if _dist_singular_agg and _dist_singular_agg not in _districts_list_agg:
            _districts_list_agg.append(_dist_singular_agg)
        if _districts_list_agg:
            _all_dists_agg = []
            for _d in _districts_list_agg:
                _all_dists_agg.extend(_d.split(','))
            _slug_list_agg = [x.strip() for x in _all_dists_agg if x.strip()]
            from models import District as _DistAgg
            _dist_ids_agg = []
            _unresolved_agg = []
            for _slug in _slug_list_agg:
                _dq = _DistAgg.query
                if city_id:
                    _dq = _dq.filter_by(city_id=city_id)
                _dist_obj = _dq.filter_by(slug=_slug).first()
                if not _dist_obj:
                    _dist_obj = _dq.filter(_DistAgg.name.ilike(_slug)).first()
                if not _dist_obj:
                    _dist_obj = _dq.filter(_DistAgg.name.ilike(f'%{_slug}%')).first()
                if _dist_obj:
                    _dist_ids_agg.append(_dist_obj.id)
                else:
                    _unresolved_agg.append(_slug)
            if _dist_ids_agg:
                q = q.filter(Property.district_id.in_(_dist_ids_agg))
            elif _unresolved_agg:
                _dist_conds_agg = [db.or_(
                    ResidentialComplex.address_city_district.ilike(f'%{_u}%'),
                    ResidentialComplex.address_quarter.ilike(f'%{_u}%'),
                ) for _u in _unresolved_agg]
                q = q.filter(db.or_(*_dist_conds_agg))

        # Quarter / city-district filter: filter by RC.address_quarter or address_city_district
        _qrt_val = request.args.get('quarter', '').strip()
        if _qrt_val:
            q = q.filter(db.or_(
                ResidentialComplex.address_quarter.ilike(f'%{_qrt_val}%'),
                ResidentialComplex.address_city_district.ilike(f'%{_qrt_val}%'),
            ))

        # Developer / search filters require joining the developers table
        _dev_single = request.args.get('developer', '').strip()
        _devs_list = request.args.getlist('developers') or request.args.getlist('developers[]')
        _search_q = (request.args.get('search') or request.args.get('q') or '').strip()
        _needs_dev_join = bool(_dev_single or _devs_list or _search_q)
        if _needs_dev_join:
            from models import Developer as DeveloperModel
            q = q.outerjoin(DeveloperModel, ResidentialComplex.developer_id == DeveloperModel.id)

        # Developer filter (single name, e.g. ?developer=Догма)
        if _dev_single:
            q = q.filter(DeveloperModel.name.ilike(f'%{_dev_single}%'))

        # Developers filter (multiple IDs or names, e.g. ?developers[]=1&developers[]=2)
        if _devs_list:
            _dev_conds = []
            for _d in _devs_list:
                _d = _d.strip()
                if _d:
                    if _d.isdigit():
                        _dev_conds.append(ResidentialComplex.developer_id == int(_d))
                    else:
                        _dev_conds.append(DeveloperModel.name.ilike(f'%{_d}%'))
            if _dev_conds:
                q = q.filter(db.or_(*_dev_conds))

        # Search filter (text across developer name, complex name, address)
        if _search_q:
            _sl = f'%{_search_q}%'
            q = q.filter(db.or_(
                DeveloperModel.name.ilike(_sl),
                Property.address.ilike(_sl),
                ResidentialComplex.name.ilike(_sl),
            ))

        # Cashback only filter
        if request.args.get('cashback_only') in ('true', '1'):
            q = q.filter(ResidentialComplex.cashback_rate.isnot(None), ResidentialComplex.cashback_rate > 0)

        q = q.group_by(lat_round, lng_round, Property.complex_id, func.coalesce(Property.complex_building_name, ''))
        # Stable order → deterministic jitter angles for sibling buildings
        q = q.order_by(lat_round, lng_round, Property.complex_id.asc().nullslast(), func.coalesce(Property.complex_building_name, '').asc())
        rows = q.all()

        # Visual jitter for buildings that share identical coords (no per-building geocoding)
        # Spread them in a small circle around the shared point so each marker is clickable.
        import math
        from collections import defaultdict
        groups_by_coord = defaultdict(list)
        for r in rows:
            if r.lat is None or r.lng is None:
                continue
            groups_by_coord[(float(r.lat), float(r.lng))].append(r)

        points = []
        # ~12 meters in degrees at Krasnodar/Sochi latitude
        JITTER_DEG = 0.00012
        for (base_lat, base_lng), siblings in groups_by_coord.items():
            n = len(siblings)
            for idx, r in enumerate(siblings):
                if n == 1:
                    lat_out, lng_out = base_lat, base_lng
                else:
                    angle = 2 * math.pi * idx / n
                    lat_out = base_lat + JITTER_DEG * math.cos(angle)
                    lng_out = base_lng + JITTER_DEG * math.sin(angle)
                points.append({
                    'lat': lat_out,
                    'lng': lng_out,
                    'orig_lat': base_lat,
                    'orig_lng': base_lng,
                    'count': int(r.count or 0),
                    'min_price': int(r.min_price) if r.min_price else None,
                    'max_price': int(r.max_price) if r.max_price else None,
                    'complex_id': r.complex_id,
                    'complex_name': r.complex_name,
                    'complex_slug': r.complex_slug,
                    'building_name': r.building_name or None,
                    'address': r.address,
                    'has_presale': bool(r.has_presale),
                    'end_build_year': int(r.end_build_year) if r.end_build_year else None,
                    'end_build_quarter': r.end_build_quarter or None,
                    'main_image': r.main_image or None,
                    'rc_district': r.rc_district or None,
                    'rc_quarter': r.rc_quarter or None,
                })

        print(f"🗺️ Aggregated map: {len(points)} building points (city={city_id})")
        _payload = {'success': True, 'points': points, 'count': len(points)}
        if _cache_key is not None:
            _AGG_MAP_CACHE[_cache_key] = (_t.time(), _payload)
        return jsonify(_payload)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@public_api_bp.route('/api/address-coverage-stats')
def api_address_coverage_stats():
    """Return address coverage stats for all cities (used by admin/addresses page)."""
    try:
        from sqlalchemy import text as _text
        rows = db.session.execute(_text("""
            SELECT
                c.id,
                c.name,
                COUNT(rc.id)                                                                    AS total_rc,
                COUNT(rc.id) FILTER (WHERE rc.address_city_district IS NOT NULL AND rc.address_city_district != '') AS with_district,
                COUNT(rc.id) FILTER (WHERE rc.address_quarter IS NOT NULL AND rc.address_quarter != '')             AS with_quarter,
                COUNT(rc.id) FILTER (WHERE rc.addr_street IS NOT NULL AND rc.addr_street != '')                     AS with_street,
                (SELECT COUNT(*)
                 FROM properties p
                 WHERE p.city_id = c.id
                   AND p.parsed_settlement IS NOT NULL AND p.parsed_settlement != '')           AS props_with_settlement
            FROM cities c
            LEFT JOIN residential_complexes rc ON rc.city_id = c.id
            WHERE c.is_active = TRUE
            GROUP BY c.id, c.name
            ORDER BY c.id
        """)).fetchall()
        cities = [{
            'id': r[0], 'name': r[1], 'total_rc': r[2],
            'with_district': r[3], 'with_quarter': r[4],
            'with_street': r[5], 'props_with_settlement': r[6],
        } for r in rows]
        return jsonify({'success': True, 'cities': cities})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@public_api_bp.route('/api/address-district-breakdown')
def api_address_district_breakdown():
    """Return district/quarter breakdown for a city (admin/addresses page)."""
    city_id = request.args.get('city_id', type=int)
    if not city_id:
        return jsonify({'success': False, 'error': 'city_id required'})
    try:
        from sqlalchemy import text as _text
        dist_rows = db.session.execute(_text("""
            SELECT address_city_district AS name, COUNT(*) AS cnt
            FROM residential_complexes
            WHERE city_id = :cid
              AND address_city_district IS NOT NULL AND address_city_district != ''
            GROUP BY address_city_district
            ORDER BY cnt DESC
            LIMIT 30
        """), {'cid': city_id}).fetchall()
        qrt_rows = db.session.execute(_text("""
            SELECT address_quarter AS name, COUNT(*) AS cnt
            FROM residential_complexes
            WHERE city_id = :cid
              AND address_quarter IS NOT NULL AND address_quarter != ''
            GROUP BY address_quarter
            ORDER BY cnt DESC
            LIMIT 40
        """), {'cid': city_id}).fetchall()
        return jsonify({
            'success': True,
            'districts': [{'name': r[0], 'count': r[1]} for r in dist_rows],
            'quarters': [{'name': r[0], 'count': r[1]} for r in qrt_rows],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@public_api_bp.route('/api/map-properties/at-point')
def api_map_properties_at_point():
    """Return apartments at a specific building coordinate (used by marker click)."""
    from models import Property, ResidentialComplex
    try:
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        if lat is None or lng is None:
            return jsonify({'success': False, 'error': 'lat/lng required'}), 400

        scope_all = request.args.get('scope') == 'all' or request.args.get('all_cities') == '1'
        explicit_city = request.args.get('city_id', type=int)
        complex_id_param = request.args.get('complex_id')
        # When complex_id is provided the complex uniquely identifies the city —
        # don't use session fallback (would filter out Sochi when session has Krasnodar)
        if scope_all or complex_id_param:
            city_id = explicit_city
        else:
            city_id = explicit_city or session.get('city_id')

        from sqlalchemy import func
        lat_col = func.coalesce(Property.latitude, ResidentialComplex.latitude)
        lng_col = func.coalesce(Property.longitude, ResidentialComplex.longitude)
        # Same rounding as aggregation — exact bucket match, no neighbor bleed
        lat_round = func.round(lat_col.cast(db.Numeric), 5)
        lng_round = func.round(lng_col.cast(db.Numeric), 5)
        target_lat = round(lat, 5)
        target_lng = round(lng, 5)

        q = db.session.query(Property).outerjoin(
            ResidentialComplex, Property.complex_id == ResidentialComplex.id
        ).filter(
            Property.is_active == True,
        )
        if city_id:
            q = q.filter(Property.city_id == city_id)

        # When complex_id is provided, use it as primary key (avoids float rounding mismatches)
        # and skip lat/lng matching — complex_id + building_name uniquely identify the bucket
        _complex_id_int = None
        if request.args.get('complex_id'):
            try:
                _complex_id_int = int(request.args.get('complex_id'))
                q = q.filter(Property.complex_id == _complex_id_int)
            except ValueError:
                pass

        # Only apply coordinate filter when complex_id is NOT available
        if _complex_id_int is None:
            q = q.filter(
                lat_round == target_lat,
                lng_round == target_lng,
            )
        if request.args.get('building_name'):
            bname = request.args.get('building_name')
            if bname == '__none__':
                # Aggregation coalesces NULL and '' to the same bucket — match both here
                q = q.filter(db.or_(
                    Property.complex_building_name.is_(None),
                    Property.complex_building_name == ''
                ))
            else:
                q = q.filter(Property.complex_building_name == bname)

        # Filter parity with aggregated endpoint (rooms, price, area, floor, type, complex)
        rooms_list = request.args.getlist('rooms') or request.args.getlist('rooms[]')
        if rooms_list:
            all_rooms = []
            for r in rooms_list:
                all_rooms.extend(str(r).split(','))
            rooms_ints = [int(r) for r in all_rooms if str(r).isdigit()]
            if rooms_ints:
                q = q.filter(Property.rooms.in_(rooms_ints))
        if request.args.get('price_min'):
            q = q.filter(Property.price >= request.args.get('price_min', type=int))
        if request.args.get('price_max'):
            q = q.filter(Property.price <= request.args.get('price_max', type=int))
        if request.args.get('area_min'):
            q = q.filter(Property.area >= request.args.get('area_min', type=float))
        if request.args.get('area_max'):
            q = q.filter(Property.area <= request.args.get('area_max', type=float))
        if request.args.get('floor_min'):
            q = q.filter(Property.floor >= request.args.get('floor_min', type=int))
        if request.args.get('floor_max'):
            q = q.filter(Property.floor <= request.args.get('floor_max', type=int))
        if request.args.get('residential_complex'):
            rc = request.args.get('residential_complex')
            if str(rc).isdigit():
                q = q.filter(Property.complex_id == int(rc))
            else:
                q = q.filter(ResidentialComplex.slug == rc)
        if request.args.get('property_type') and request.args.get('property_type') != 'all':
            type_map = {
                'apartments': 'Квартира', 'houses': 'Дом',
                'townhouses': 'Таунхаус', 'penthouses': 'Пентхаус',
                'apartments_commercial': 'Апартаменты'
            }
            raw = request.args.get('property_type')
            q = q.filter(Property.property_type == type_map.get(raw, raw))

        # Completion year filter (chips: 2024/2025/2026/2027+)
        if request.args.get('completion'):
            completion_years = [y.strip() for y in request.args.get('completion').split(',') if y.strip()]
            if completion_years:
                year_conditions = []
                for yr in completion_years:
                    if yr == '2027+':
                        year_conditions.append(ResidentialComplex.end_build_year >= 2027)
                    elif yr.isdigit():
                        year_conditions.append(ResidentialComplex.end_build_year == int(yr))
                if year_conditions:
                    q = q.filter(db.or_(*year_conditions))

        # Building status filter: use end_build_year (same logic as PropertyRepository)
        if request.args.get('building_status'):
            from datetime import datetime as _dt2
            _cur_year2 = _dt2.now().year
            statuses = [s.strip() for s in request.args.get('building_status').split(',') if s.strip()]
            if statuses:
                status_conditions = []
                for st in statuses:
                    if st == 'delivered':
                        status_conditions.append(ResidentialComplex.end_build_year < _cur_year2)
                    elif st == 'under_construction':
                        status_conditions.append(db.or_(ResidentialComplex.end_build_year >= _cur_year2, ResidentialComplex.end_build_year.is_(None)))
                if status_conditions:
                    q = q.filter(db.or_(*status_conditions))

        # Object class filter (field: object_class_display_name)
        if request.args.get('object_classes'):
            classes = [c.strip() for c in request.args.get('object_classes').split(',') if c.strip()]
            if classes:
                q = q.filter(ResidentialComplex.object_class_display_name.in_(classes))

        # Developer / search filters require joining the developers table
        _dev_single_ap = request.args.get('developer', '').strip()
        _devs_list_ap = request.args.getlist('developers') or request.args.getlist('developers[]')
        _search_ap = (request.args.get('search') or request.args.get('q') or '').strip()
        if _dev_single_ap or _devs_list_ap or _search_ap:
            from models import Developer as DeveloperModelAP
            q = q.outerjoin(DeveloperModelAP, ResidentialComplex.developer_id == DeveloperModelAP.id)

        # Developer filter (single name)
        if _dev_single_ap:
            q = q.filter(DeveloperModelAP.name.ilike(f'%{_dev_single_ap}%'))

        # Developers filter (multiple IDs or names)
        if _devs_list_ap:
            _dev_conds_ap = []
            for _d in _devs_list_ap:
                _d = _d.strip()
                if _d:
                    if _d.isdigit():
                        _dev_conds_ap.append(ResidentialComplex.developer_id == int(_d))
                    else:
                        _dev_conds_ap.append(DeveloperModelAP.name.ilike(f'%{_d}%'))
            if _dev_conds_ap:
                q = q.filter(db.or_(*_dev_conds_ap))

        # Search filter (text across developer name, complex name, address)
        if _search_ap:
            _sl_ap = f'%{_search_ap}%'
            q = q.filter(db.or_(
                DeveloperModelAP.name.ilike(_sl_ap),
                Property.address.ilike(_sl_ap),
                ResidentialComplex.name.ilike(_sl_ap),
            ))

        # Cashback only filter
        if request.args.get('cashback_only') in ('true', '1'):
            q = q.filter(ResidentialComplex.cashback_rate.isnot(None), ResidentialComplex.cashback_rate > 0)

        total_count = q.count()
        props = q.order_by(Property.price.asc().nullslast()).limit(500).all()

        # Preload city slug to avoid N+1 lazy queries in the loop
        from models import City as CityModel
        _city_slug_cache = {}
        if city_id:
            c = db.session.get(CityModel, city_id)
            if c:
                _city_slug_cache[city_id] = c.slug

        result = []
        for p in props:
            result.append({
                'id': p.id,
                'title': p.title,
                'slug': p.slug,
                'rooms': p.rooms,
                'area': float(p.area) if p.area else None,
                'floor': p.floor,
                'total_floors': p.total_floors,
                'price': p.price,
                'price_per_sqm': p.price_per_sqm,
                'main_image': p.main_image,
                'address': p.address,
                'complex_id': p.complex_id,
                'complex_name': p.residential_complex.name if p.residential_complex else None,
                'complex_slug': p.residential_complex.slug if p.residential_complex else None,
                'complex_building_name': p.complex_building_name,
                'building_name': p.complex_building_name or None,
                'renovation_type': p.renovation_type or (p.residential_complex.finishing_type if p.residential_complex else None),
                'deal_type': p.deal_type,
                'cashback_rate': float(p.residential_complex.cashback_rate) if p.residential_complex and p.residential_complex.cashback_rate else 3.5,
                'cashback': int((p.price or 0) * (float(p.residential_complex.cashback_rate or 3.5) / 100)) if p.residential_complex else int((p.price or 0) * 0.035),
                'gallery_images': p.gallery_images if p.gallery_images else ([p.main_image] if p.main_image else []),
                'complex_main_image': p.residential_complex.main_image if p.residential_complex and p.residential_complex.main_image else None,
                'coordinates': {
                    'lat': float(p.latitude) if p.latitude else (float(p.residential_complex.latitude) if p.residential_complex and p.residential_complex.latitude else None),
                    'lng': float(p.longitude) if p.longitude else (float(p.residential_complex.longitude) if p.residential_complex and p.residential_complex.longitude else None),
                },
                'url': f"/{_city_slug_cache.get(p.city_id, _city_slug_cache.get(city_id, 'krasnodar'))}/object/{p.id}",
            })
        return jsonify({'success': True, 'properties': result, 'count': len(result), 'total': total_count})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@public_api_bp.route('/api/properties/polygon', methods=['POST'])
def api_properties_polygon():
    """
    Backend polygon filter: accepts GeoJSON polygon coordinates, returns properties inside.
    Uses pure-Python ray-casting — no PostGIS required.
    Body: { "polygon": [[lat, lng], ...], "city_id": N }
    """
    from models import Property

    def _point_in_polygon(lat, lng, poly):
        """Ray-casting algorithm."""
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            lat_i, lng_i = poly[i]
            lat_j, lng_j = poly[j]
            if ((lng_i > lng) != (lng_j > lng)) and \
               (lat < (lat_j - lat_i) * (lng - lng_i) / (lng_j - lng_i + 1e-12) + lat_i):
                inside = not inside
            j = i
        return inside

    try:
        data = request.get_json(force=True) or {}
        polygon = data.get('polygon', [])
        city_id = data.get('city_id')

        if len(polygon) < 3:
            return jsonify({'error': 'Need at least 3 polygon points'}), 400

        from models import ResidentialComplex as RC_
        from sqlalchemy import func as sqlfunc_

        # Bounding-box pre-filter from DB using COALESCE(property.lat, complex.lat)
        # so properties that only have complex-level coordinates are included
        lats = [p[0] for p in polygon]
        lngs = [p[1] for p in polygon]
        min_lat, max_lat = min(lats), max(lats)
        min_lng, max_lng = min(lngs), max(lngs)

        lat_col = sqlfunc_.coalesce(Property.latitude, RC_.latitude)
        lng_col = sqlfunc_.coalesce(Property.longitude, RC_.longitude)

        q = db.session.query(Property, RC_) \
            .outerjoin(RC_, Property.complex_id == RC_.id) \
            .filter(
                Property.is_active == True,
                lat_col.isnot(None),
                lng_col.isnot(None),
                lat_col != 0,
                lng_col != 0,
                lat_col >= min_lat,
                lat_col <= max_lat,
                lng_col >= min_lng,
                lng_col <= max_lng,
            )
        if city_id:
            q = q.filter(Property.city_id == city_id)

        candidates = q.all()

        # Precise ray-casting check
        result = []
        for prop, rc in candidates:
            eff_lat = float(prop.latitude or rc.latitude or 0)
            eff_lng = float(prop.longitude or rc.longitude or 0)
            if not eff_lat or not eff_lng:
                continue
            if _point_in_polygon(eff_lat, eff_lng, polygon):
                price = int(prop.price) if prop.price else None
                price_m2 = int(prop.price / prop.area) if prop.price and prop.area else None
                rc_end_year = rc.end_build_year if rc else None
                result.append({
                    'id': prop.id,
                    'coordinates': {'lat': eff_lat, 'lng': eff_lng},
                    'title': prop.title or (f'Студия {prop.area} м²' if not prop.rooms else f'{prop.rooms}-комн. кв. {prop.area} м²'),
                    'price': price,
                    'price_m2': price_m2,
                    'rooms': prop.rooms,
                    'area': float(prop.area) if prop.area else None,
                    'floor': prop.floor,
                    'address': prop.address,
                    'image': prop.main_image,
                    'main_image': prop.main_image,
                    'renovation_type': prop.renovation_type or (rc.finishing_type if rc else None),
                    'cashback_rate': float(prop.cashback_rate) if getattr(prop, 'cashback_rate', None) else None,
                    'complex_name': rc.name if rc else None,
                    'complex_slug': rc.slug if rc else None,
                    'url': f'/property/{prop.id}',
                    'completion_year': rc_end_year,
                    'complex_building_end_build_year': rc_end_year,
                    'deal_type': prop.deal_type,
                })

        return jsonify({
            'properties': result,
            'count': len(result),
            'polygon_points': len(polygon)
        })

    except Exception as e:
        current_app.logger.error(f'Polygon filter error: {e}')
        return jsonify({'error': str(e)}), 500


@public_api_bp.route('/api/properties/polygon-aggregated', methods=['POST'])
def api_properties_polygon_aggregated():
    """
    Returns aggregated building points (same format as /api/map-properties/aggregated)
    but filtered by exact polygon using server-side ray-casting.
    Body: { "polygon": [[lat, lng], ...], "city_id": N }
    """
    from models import Property, ResidentialComplex
    from sqlalchemy import func
    import math
    from collections import defaultdict

    def _pip(lat, lng, poly):
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            lat_i, lng_i = poly[i]
            lat_j, lng_j = poly[j]
            if ((lng_i > lng) != (lng_j > lng)) and \
               (lat < (lat_j - lat_i) * (lng - lng_i) / (lng_j - lng_i + 1e-12) + lat_i):
                inside = not inside
            j = i
        return inside

    try:
        data = request.get_json(force=True) or {}
        polygon = data.get('polygon', [])
        city_id = data.get('city_id')

        if len(polygon) < 3:
            return jsonify({'success': False, 'error': 'Need at least 3 points'}), 400

        lats = [p[0] for p in polygon]
        lngs = [p[1] for p in polygon]
        min_lat, max_lat = min(lats), max(lats)
        min_lng, max_lng = min(lngs), max(lngs)

        lat_col = func.coalesce(Property.latitude, ResidentialComplex.latitude)
        lng_col = func.coalesce(Property.longitude, ResidentialComplex.longitude)
        lat_round = func.round(lat_col.cast(db.Numeric), 5)
        lng_round = func.round(lng_col.cast(db.Numeric), 5)

        q = db.session.query(
            lat_round.label('lat'),
            lng_round.label('lng'),
            Property.complex_id.label('complex_id'),
            func.coalesce(Property.complex_building_name, '').label('building_name'),
            func.count(Property.id).label('count'),
            func.min(Property.price).label('min_price'),
            func.max(Property.price).label('max_price'),
            func.min(ResidentialComplex.name).label('complex_name'),
            func.min(ResidentialComplex.slug).label('complex_slug'),
            func.min(Property.address).label('address'),
            func.bool_or(func.lower(func.coalesce(Property.deal_type, '')).in_(['presale', 'первичка'])).label('has_presale'),
            func.min(ResidentialComplex.end_build_year).label('end_build_year'),
        ).outerjoin(ResidentialComplex, Property.complex_id == ResidentialComplex.id) \
         .filter(
            Property.is_active == True,
            lat_col.isnot(None), lng_col.isnot(None),
            lat_col != 0, lng_col != 0,
            lat_col.between(min_lat, max_lat),
            lng_col.between(min_lng, max_lng),
        )

        if city_id:
            q = q.filter(Property.city_id == city_id)

        q = q.group_by(lat_round, lng_round, Property.complex_id,
                       func.coalesce(Property.complex_building_name, ''))
        rows = q.all()

        # Precise ray-casting on grouped results
        groups_by_coord = defaultdict(list)
        for r in rows:
            if r.lat is None or r.lng is None:
                continue
            base_lat, base_lng = float(r.lat), float(r.lng)
            if _pip(base_lat, base_lng, polygon):
                groups_by_coord[(base_lat, base_lng)].append(r)

        JITTER_DEG = 0.00012
        points = []
        for (base_lat, base_lng), siblings in groups_by_coord.items():
            n = len(siblings)
            for idx, r in enumerate(siblings):
                if n == 1:
                    lat_out, lng_out = base_lat, base_lng
                else:
                    angle = 2 * math.pi * idx / n
                    lat_out = base_lat + JITTER_DEG * math.cos(angle)
                    lng_out = base_lng + JITTER_DEG * math.sin(angle)
                points.append({
                    'lat': lat_out,
                    'lng': lng_out,
                    'orig_lat': base_lat,
                    'orig_lng': base_lng,
                    'count': int(r.count or 0),
                    'min_price': int(r.min_price) if r.min_price else None,
                    'max_price': int(r.max_price) if r.max_price else None,
                    'complex_id': r.complex_id,
                    'complex_name': r.complex_name,
                    'complex_slug': r.complex_slug,
                    'building_name': r.building_name or None,
                    'address': r.address,
                    'has_presale': bool(r.has_presale),
                    'end_build_year': int(r.end_build_year) if r.end_build_year else None,
                })

        current_app.logger.info(f'Polygon-aggregated: {len(rows)} bbox rows → {len(points)} inside polygon')
        return jsonify({'success': True, 'points': points, 'count': len(points)})

    except Exception as e:
        current_app.logger.error(f'Polygon-aggregated error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@public_api_bp.route('/api/mini-map/complexes')
def api_mini_map_complexes():
    """API endpoint for mini-map: return complex coordinates - NORMALIZED TABLES"""
    from repositories.property_repository import ResidentialComplexRepository
    from models import ResidentialComplex
    
    try:
        # Get city_id from request args first, then fallback to session
        city_id = request.args.get('city_id', type=int)
        if not city_id and 'city_id' in session:
            city_id = session['city_id']
        
        # Filter complexes by city_id (and optionally district_id)
        district_id = request.args.get('district_id', type=int)
        if city_id:
            q = ResidentialComplex.query.filter_by(is_active=True, city_id=city_id)
            if district_id:
                q = q.filter_by(district_id=district_id)
            complexes = q.all()
        else:
            complexes = ResidentialComplexRepository.get_all_active()
        
        coordinates = []
        for complex_obj in complexes:
            # Only add if complex has valid coordinates
            if complex_obj.latitude and complex_obj.longitude and complex_obj.latitude != 0 and complex_obj.longitude != 0:
                coordinates.append({
                    'id': complex_obj.id,
                    'name': complex_obj.name,
                    'lat': float(complex_obj.latitude),
                    'lng': float(complex_obj.longitude)
                })
        
        print(f"✅ Mini-map: Loaded {len(coordinates)} complex coordinates from normalized tables")
        return jsonify({'success': True, 'coordinates': coordinates, 'count': len(coordinates)})
    except Exception as e:
        print(f"❌ Error in mini-map complexes: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@public_api_bp.route('/api/property/<property_id>/pdf')
def download_property_pdf(property_id):
    """Generate and download PDF for property"""
    try:
        property_data = get_property_by_id(property_id)
        if not property_data:
            return jsonify({'error': 'Property not found'}), 404
        
        # Create simple HTML for PDF generation
        html_content = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .property-details {{ margin-bottom: 20px; }}
                .detail-row {{ margin-bottom: 10px; }}
                .label {{ font-weight: bold; }}
                .price {{ color: #0088CC; font-size: 24px; font-weight: bold; }}
                .cashback {{ color: #FF5722; font-size: 18px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>InBack - Информация о квартире</h1>
                <p>Квартира #{property_id}</p>
            </div>
            
            <div class="property-details">
                <div class="detail-row">
                    <span class="label">Тип:</span> {property_data.get('rooms', 'Не указано')}
                </div>
                <div class="detail-row">
                    <span class="label">Площадь:</span> {property_data.get('area', 'Не указана')} м²
                </div>
                <div class="detail-row">
                    <span class="label">Этаж:</span> {property_data.get('floor', 'Не указан')}
                </div>
                <div class="detail-row">
                    <span class="label">Застройщик:</span> {property_data.get('developer', 'Не указан')}
                </div>
                <div class="detail-row">
                    <span class="label">ЖК:</span> {property_data.get('residential_complex', 'Не указан')}
                </div>
                <div class="detail-row">
                    <span class="label">Район:</span> {property_data.get('district', 'Не указан')}
                </div>
                <div class="detail-row">
                    <span class="label">Адрес:</span> {property_data.get('location', 'Не указан')}
                </div>
                <div class="detail-row">
                    <span class="label">Статус:</span> {property_data.get('status', 'Не указан')}
                </div>
                
                <div class="detail-row" style="margin-top: 30px;">
                    <div class="price">Цена: {property_data.get('price', 0):,} ₽</div>
                </div>
                <div class="detail-row">
                    <div class="cashback">Кешбек: до {calculate_cashback(property_data.get('price', 0)):,} ₽ (5%)</div>
                </div>
            </div>
            
            <div style="margin-top: 50px; text-align: center; color: #666;">
                <p>InBack.ru - ваш кешбек за новостройки</p>
                <p>Телефон: +7 (800) 123-12-12</p>
            </div>
        </body>
        </html>
        """
        
        # Return HTML for PDF conversion (browser will handle PDF generation)
        # Create ASCII-safe filename
        ascii_filename = f'property-{property_id}.html'
        
        response = current_app.response_class(
            response=html_content,
            status=200,
            mimetype='text/html'
        )
        response.headers['Content-Disposition'] = f'attachment; filename="{ascii_filename}"'
        return response
        
    except Exception as e:
        print(f"Error generating PDF for property {property_id}: {e}")
        return jsonify({'error': 'Failed to generate PDF'}), 500

@public_api_bp.route('/set-demo-password')
def set_demo_password():
    """Временный роут для установки правильного пароля демо пользователю"""
    from models import User
    from werkzeug.security import generate_password_hash
    
    # Найти демо пользователя
    demo_user = User.query.filter_by(email='demo@inback.ru').first()
    if demo_user:
        # Установить простой пароль "demo123"
        demo_user.password_hash = generate_password_hash('demo123')
        db.session.commit()
        return f"Пароль установлен для пользователя {demo_user.email}. Хэш: {demo_user.password_hash[:50]}..."
    else:
        return "Демо пользователь не найден"

@public_api_bp.route('/set-managers-passwords')
def set_managers_passwords():
    """Временный роут для установки паролей всем менеджерам"""
    from models import Manager
    from werkzeug.security import generate_password_hash
    
    results = []
    
    # Найти всех менеджеров и установить простые пароли
    managers = Manager.query.all()
    for manager in managers:
        if 'anna' in manager.email.lower():
            password = 'anna123'
        elif 'sergey' in manager.email.lower():
            password = 'sergey123'  
        elif 'maria' in manager.email.lower():
            password = 'maria123'
        else:
            password = 'manager123'  # Для остальных менеджеров
            
        manager.password_hash = generate_password_hash(password)
        results.append(f"{manager.email} -> {password}")
    
    db.session.commit()
    return f"Пароли установлены для {len(managers)} менеджеров:<br>" + "<br>".join(results)


@public_api_bp.route('/quiz-registration')
def quiz_registration():
    """Show quiz registration page"""
    return render_template('quiz_registration.html')

@public_api_bp.route('/callback-request')
def callback_request_page():
    """Show callback request page"""
    return render_template('callback_request.html')

@public_api_bp.route('/api/property-selection', methods=['POST'])
def property_selection():
    """Property selection application"""
    from models import Application, User
    data = request.get_json()
    
    try:
        # Extract data
        email = data.get('email', '').strip().lower()
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        
        # Application preferences
        preferred_district = data.get('preferred_district', '')
        property_type = data.get('property_type', '')
        room_count = data.get('room_count', '')
        budget_range = data.get('budget_range', '')
        
        # Property context information
        property_id = data.get('property_id')
        property_title = data.get('property_title', '')
        property_complex = data.get('property_complex', '')
        property_price = data.get('property_price')
        property_area = data.get('property_area')
        property_rooms = data.get('property_rooms')
        property_floor = data.get('property_floor')
        property_total_floors = data.get('property_total_floors')
        property_district = data.get('property_district', '')
        property_url = data.get('property_url', '')
        property_type_context = data.get('property_type_context', '')
        
        # Validation
        if not email or not name or not phone:
            return jsonify({'success': False, 'error': 'Все обязательные поля должны быть заполнены'})
        
        # Determine application type and build message
        is_specific_property = property_id and property_type_context == 'property'
        is_specific_complex = property_id and property_type_context == 'complex'
        
        if is_specific_property:
            # Specific property interest
            application_title = f"Интерес к квартире: {property_title}"
            complex_name = property_complex or 'Не указан'
            message = f"Заявка по конкретной квартире:\n"
            message += f"Имя: {name}\n"
            message += f"Email: {email}\n"
            message += f"Телефон: {phone}\n\n"
            message += f"=== ОБЪЕКТ ИНТЕРЕСА ===\n"
            message += f"Квартира: {property_title}\n"
            message += f"ЖК: {property_complex}\n"
            if property_price:
                try:
                    formatted_price = f"{int(property_price):,}".replace(',', ' ')
                    message += f"Цена: {formatted_price} ₽\n"
                except (ValueError, TypeError):
                    message += f"Цена: {property_price} ₽\n"
            if property_area:
                message += f"Площадь: {property_area} м²\n"
            if property_floor and property_total_floors:
                message += f"Этаж: {property_floor}/{property_total_floors}\n"
            if property_district:
                message += f"Район: {property_district}\n"
            if property_url:
                message += f"Ссылка: {property_url}\n"
            message += f"\n=== ДОПОЛНИТЕЛЬНЫЕ ПРЕДПОЧТЕНИЯ ===\n"
            message += f"Предпочитаемый район: {preferred_district or 'Не указан'}\n"
            message += f"Тип недвижимости: {property_type or 'Не указан'}\n"
            message += f"Комнат: {room_count or 'Не указано'}\n"
            message += f"Бюджет: {budget_range or 'Не указан'}"
        elif is_specific_complex:
            # Specific complex interest
            application_title = f"Интерес к ЖК: {property_title}"
            complex_name = property_title
            message = f"Заявка по жилому комплексу:\n"
            message += f"Имя: {name}\n"
            message += f"Email: {email}\n"
            message += f"Телефон: {phone}\n\n"
            message += f"=== ОБЪЕКТ ИНТЕРЕСА ===\n"
            message += f"ЖК: {property_title}\n"
            if property_district:
                message += f"Район: {property_district}\n"
            if property_url:
                message += f"Ссылка: {property_url}\n"
            message += f"\n=== ДОПОЛНИТЕЛЬНЫЕ ПРЕДПОЧТЕНИЯ ===\n"
            message += f"Предпочитаемый район: {preferred_district or 'Не указан'}\n"
            message += f"Тип недвижимости: {property_type or 'Не указан'}\n"
            message += f"Комнат: {room_count or 'Не указано'}\n"
            message += f"Бюджет: {budget_range or 'Не указан'}"
        else:
            # General property selection
            application_title = "Подбор квартиры"
            complex_name = "По предпочтениям"
            message = f"Заявка на подбор квартиры:\n"
            message += f"Имя: {name}\n"
            message += f"Email: {email}\n"
            message += f"Телефон: {phone}\n"
            message += f"Район: {preferred_district or 'Любой'}\n"
            message += f"Тип: {property_type or 'Не указан'}\n"
            message += f"Комнат: {room_count or 'Не указано'}\n"
            message += f"Бюджет: {budget_range or 'Не указан'}"
        
        # Create application
        application = Application(
            user_id=None,  # No user account needed for applications
            property_id=property_id,  # Store specific property ID if available
            property_name=application_title,
            complex_name=complex_name,
            message=message,
            status='new',
            contact_name=name,
            contact_email=email,
            contact_phone=phone
        )
        
        db.session.add(application)
        
        # Application submitted successfully
        db.session.commit()
        
        # Send Telegram notification
        try:
            from telegram_bot import send_telegram_message
            from datetime import datetime
            
            # Calculate potential cashback (2% of average budget)
            potential_cashback = ""
            if budget_range:
                if "млн" in budget_range:
                    # Extract average from range like "3-5 млн"
                    numbers = [float(x) for x in budget_range.replace(" млн", "").split("-") if x.strip().replace(".", "").replace(",", "").isdigit()]
                    if numbers:
                        avg_price = sum(numbers) / len(numbers) * 1000000
                        cashback = int(avg_price * 0.02)
                        formatted_cashback = f"{cashback:,}".replace(',', ' ')
                        potential_cashback = f"💰 *Потенциальный кэшбек:* {formatted_cashback} руб. (2%)\n"
            
            # Build telegram message based on application type
            if is_specific_property:
                telegram_message = f"""🏠 *ЗАЯВКА ПО КОНКРЕТНОЙ КВАРТИРЕ*

👤 *КОНТАКТНАЯ ИНФОРМАЦИЯ:*
• Имя: {name}
• Телефон: {phone}
• Email: {email}

🏡 *ОБЪЕКТ ИНТЕРЕСА:*
• Квартира: {property_title}
• ЖК: {property_complex}
{f"• Цена: {int(property_price):,} ₽".replace(',', ' ') if property_price else ''}
{f"• Площадь: {property_area} м²" if property_area else ''}
{f"• Этаж: {property_floor}/{property_total_floors}" if property_floor and property_total_floors else ''}
{f"• Ссылка: {property_url}" if property_url else ''}

🔍 *ДОПОЛНИТЕЛЬНЫЕ ПРЕДПОЧТЕНИЯ:*
• Район: {preferred_district or 'Не указан'}
• Тип недвижимости: {property_type or 'Не указан'}
• Количество комнат: {room_count or 'Не указано'}
• Бюджет: {budget_range or 'Не указан'}

{potential_cashback}📅 *ВРЕМЯ ЗАЯВКИ:* {datetime.now().strftime('%d.%m.%Y в %H:%M')}
🌐 *ИСТОЧНИК:* Страница квартиры на InBack.ru

📋 *СЛЕДУЮЩИЕ ШАГИ:*
1️⃣ Связаться с клиентом в течение 15 минут
2️⃣ Обсудить интересующую квартиру
3️⃣ Рассчитать кэшбек и условия покупки
4️⃣ Назначить встречу для просмотра

⚡ *ВАЖНО:* Клиент уже выбрал конкретную квартиру!"""
            elif is_specific_complex:
                telegram_message = f"""🏢 *ЗАЯВКА ПО ЖИЛОМУ КОМПЛЕКСУ*

👤 *КОНТАКТНАЯ ИНФОРМАЦИЯ:*
• Имя: {name}
• Телефон: {phone}
• Email: {email}

🏗️ *ОБЪЕКТ ИНТЕРЕСА:*
• ЖК: {property_title}
{f"• Район: {property_district}" if property_district else ''}
{f"• Ссылка: {property_url}" if property_url else ''}

🔍 *ДОПОЛНИТЕЛЬНЫЕ ПРЕДПОЧТЕНИЯ:*
• Район: {preferred_district or 'Не указан'}
• Тип недвижимости: {property_type or 'Не указан'}
• Количество комнат: {room_count or 'Не указано'}
• Бюджет: {budget_range or 'Не указан'}

{potential_cashback}📅 *ВРЕМЯ ЗАЯВКИ:* {datetime.now().strftime('%d.%m.%Y в %H:%M')}
🌐 *ИСТОЧНИК:* Страница ЖК на InBack.ru

📋 *СЛЕДУЮЩИЕ ШАГИ:*
1️⃣ Связаться с клиентом в течение 15 минут
2️⃣ Показать доступные квартиры в ЖК
3️⃣ Рассчитать кэшбек и условия покупки
4️⃣ Назначить встречу для просмотра

⚡ *ВАЖНО:* Клиент интересуется конкретным ЖК!"""
            else:
                telegram_message = f"""🏠 *НОВАЯ ЗАЯВКА НА ПОДБОР КВАРТИРЫ*

👤 *КОНТАКТНАЯ ИНФОРМАЦИЯ:*
• Имя: {name}
• Телефон: {phone}
• Email: {email}

🔍 *КРИТЕРИИ ПОИСКА:*
• Район: {preferred_district or 'Любой'}
• Тип недвижимости: {property_type or 'Не указан'}
• Количество комнат: {room_count or 'Не указано'}
• Бюджет: {budget_range or 'Не указан'}

{potential_cashback}📅 *ВРЕМЯ ЗАЯВКИ:* {datetime.now().strftime('%d.%m.%Y в %H:%M')}
🌐 *ИСТОЧНИК:* Форма на сайте InBack.ru

📋 *СЛЕДУЮЩИЕ ШАГИ:*
1️⃣ Связаться с клиентом в течение 15 минут
2️⃣ Уточнить дополнительные предпочтения
3️⃣ Подготовить подборку объектов
4️⃣ Назначить встречу для просмотра

⚡ *ВАЖНО:* Быстрая реакция повышает конверсию!"""
            
            _admin_tg = os.environ.get('TELEGRAM_CHAT_ID', '')
            send_telegram_message(_admin_tg, telegram_message)
            
            from models import Manager
            from email_service import send_manager_notification
            lead_manager = _find_lead_receiving_manager()
            if lead_manager:
                send_manager_notification(
                    lead_manager, 'new_lead', telegram_message,
                    email_subject=f'Новая заявка: {name}',
                    email_template='emails/general_notification.html',
                    user_name=lead_manager.first_name,
                    subject=f'Новая заявка: {name}',
                    message=f'Поступила новая заявка от {name} ({phone}). Проверьте панель менеджера для деталей.'
                )
            else:
                managers_with_tg = Manager.query.filter(
                    Manager.is_active == True,
                    Manager.telegram_id.isnot(None),
                    Manager.telegram_id != ''
                ).all()
                _owner_id = os.environ.get('TELEGRAM_CHAT_ID', '')
                for mgr in managers_with_tg:
                    if mgr.telegram_id != _owner_id:
                        send_manager_notification(
                            mgr, 'new_lead', telegram_message,
                            email_subject=f'Новая заявка: {name}',
                            email_template='emails/general_notification.html',
                            user_name=mgr.first_name,
                            subject=f'Новая заявка: {name}',
                            message=f'Поступила новая заявка от {name} ({phone}). Проверьте панель менеджера для деталей.'
                        )
            
        except Exception as notify_error:
            print(f"Notification error: {notify_error}")
        
        return jsonify({
            'success': True,
            'message': 'Заявка отправлена! Менеджер свяжется с вами.'
        })
    except Exception as e:
        db.session.rollback()
        print(f"Application error: {e}")
        return jsonify({'success': False, 'error': 'Ошибка при отправке заявки'})

def _find_lead_receiving_manager():
    """Find next manager from a role with can_receive_leads permission using round-robin."""
    from models import Manager, OrgRole
    
    lead_roles = OrgRole.query.filter_by(is_active=True, can_receive_leads=True).all()
    if not lead_roles:
        return None
    
    role_ids = [r.id for r in lead_roles]
    eligible_managers = Manager.query.filter(
        Manager.is_active == True,
        Manager.org_role_id.in_(role_ids)
    ).order_by(Manager.id).all()
    
    if not eligible_managers:
        return None
    
    if len(eligible_managers) == 1:
        return eligible_managers[0]
    
    from models import Deal
    from sqlalchemy import func
    deal_counts = db.session.query(
        Deal.manager_id, func.count(Deal.id).label('cnt')
    ).filter(
        Deal.manager_id.in_([m.id for m in eligible_managers]),
        Deal.source.isnot(None)
    ).group_by(Deal.manager_id).all()
    
    count_map = {row[0]: row[1] for row in deal_counts}
    min_count = float('inf')
    selected = eligible_managers[0]
    for m in eligible_managers:
        c = count_map.get(m.id, 0)
        if c < min_count:
            min_count = c
            selected = m
    
    return selected

def create_deal_from_website_form(name, phone, email=None, source='Заявка с сайта', 
                                    complex_name=None, property_price=0, cashback_amount=0,
                                    notes='', manager=None, quiz_data=None):
    """Create a User (if needed) and Deal from a website form submission.
    Returns (deal, user) tuple or (None, None) on failure."""
    from models import Deal, Manager, User, DealHistory
    from decimal import Decimal
    
    try:
        if not phone or not phone.strip():
            print("Cannot create deal from website form: phone is missing")
            return None, None
        
        phone_clean = phone.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        user = User.query.filter_by(phone=phone_clean).first()
        if not user:
            user = User.query.filter_by(phone=phone).first()
        if not user:
            user = User(
                phone=phone_clean,
                full_name=name.strip() if name else 'Клиент',
                email=email.strip() if email else None,
                registration_source=source,
                client_status='Новый'
            )
            db.session.add(user)
            db.session.flush()
        
        if quiz_data:
            if quiz_data.get('interest'):
                user.preferred_district = quiz_data['interest']
            if quiz_data.get('property_type'):
                user.property_type = quiz_data['property_type']
            if quiz_data.get('rooms'):
                user.room_count = quiz_data['rooms']
            if quiz_data.get('budget'):
                user.budget_range = quiz_data['budget']
            if quiz_data.get('timing'):
                user.timing = quiz_data['timing']
            if any(quiz_data.get(k) for k in ('interest', 'property_type', 'rooms', 'budget', 'timing')):
                user.quiz_completed = True
        
        if not manager:
            manager = _find_lead_receiving_manager()
        if not manager:
            manager = Manager.query.filter_by(is_active=True).first()
        
        if not manager:
            print(f"No active manager found for website form deal creation")
            return None, user
        
        if not user.assigned_manager_id:
            user.assigned_manager_id = manager.id
        
        deal = Deal(
            manager_id=manager.id,
            client_id=user.id,
            residential_complex_name=complex_name or 'Не указан',
            property_price=Decimal(str(property_price)) if property_price else Decimal('0'),
            cashback_amount=Decimal(str(cashback_amount)) if cashback_amount else Decimal('0'),
            status='new',
            source=source,
            notes=notes
        )
        db.session.add(deal)
        db.session.flush()
        
        history = DealHistory(
            deal_id=deal.id,
            author_id=manager.id,
            action='deal_created',
            description=f'Сделка создана автоматически из формы: {source}'
        )
        db.session.add(history)
        
        try:
            from models import ManagerNotification
            import json
            notification = ManagerNotification(
                manager_id=manager.id,
                title='Новая заявка с сайта',
                message=f'Вам назначена новая сделка #{deal.deal_number} от клиента {user.full_name or user.phone}. Источник: {source}',
                notification_type='new_deal',
                extra_data=json.dumps({
                    'deal_id': deal.id,
                    'deal_number': deal.deal_number,
                    'client_name': user.full_name or '',
                    'client_phone': user.phone,
                    'source': source
                })
            )
            db.session.add(notification)
        except Exception as ne:
            print(f"Failed to create manager notification: {ne}")
        
        try:
            from telegram_bot import send_telegram_message
            tg_msg = (
                f"🆕 *НОВАЯ СДЕЛКА НАЗНАЧЕНА*\n\n"
                f"📋 Сделка: #{deal.deal_number}\n"
                f"👤 Клиент: {user.full_name or 'Не указано'}\n"
                f"📞 Телефон: {user.phone}\n"
                f"🌐 Источник: {source}\n"
                f"👨‍💼 Менеджер: {manager.full_name}\n"
            )
            if notes:
                tg_msg += f"📝 Заметки: {notes}\n"
            _admin_tg = os.environ.get('TELEGRAM_CHAT_ID', '')
            if _admin_tg:
                send_telegram_message(_admin_tg, tg_msg)
            from email_service import send_manager_notification
            send_manager_notification(
                manager, 'new_deal', tg_msg,
                email_subject=f'Новая сделка #{deal.deal_number}',
                email_template='emails/general_notification.html',
                user_name=manager.first_name,
                subject=f'Новая сделка #{deal.deal_number}',
                message=f'Вам назначена новая сделка #{deal.deal_number} от клиента {user.full_name or user.phone}. Источник: {source}'
            )
        except Exception as te:
            print(f"Failed to send deal Telegram notification: {te}")
        
        return deal, user
    except Exception as e:
        print(f"Error creating deal from website form: {e}")
        import traceback
        traceback.print_exc()
        return None, None


@public_api_bp.route('/switch-to-client')
def switch_to_client():
    """Switch from manager to client mode"""
    logout_user()
    flash('Переключились в режим клиента', 'info')
    return redirect(url_for('public_api.index'))





@public_api_bp.before_app_request
def cleanup_invalid_sessions():
    """Очищает сессии удаленных пользователей - проверка раз в 10 минут"""
    import time
    if '_user_id' in session:
        user_id = session.get('_user_id')
        if not user_id:
            return
        
        last_check = session.get('_session_validated', 0)
        now = time.time()
        if now - last_check < 600:
            return
        
        from models import User, Manager, Admin
        user_exists = False
        
        try:
            if isinstance(user_id, str):
                if user_id.startswith('m_'):
                    manager_id = int(user_id[2:])
                    user_exists = Manager.query.get(manager_id) is not None
                elif user_id.startswith('a_'):
                    admin_id = int(user_id[2:])
                    user_exists = Admin.query.get(admin_id) is not None
                elif user_id.startswith('p_'):
                    from models import Partner
                    partner_id = int(user_id[2:])
                    user_exists = Partner.query.get(partner_id) is not None
                else:
                    user_exists = User.query.get(int(user_id)) is not None
            else:
                user_exists = User.query.get(int(user_id)) is not None
        except (ValueError, TypeError):
            user_exists = False
        except Exception as e:
            print(f"⚠️ CLEANUP: DB error checking user {user_id}, keeping session: {e}")
            return
        
        if user_exists:
            session['_session_validated'] = now
        else:
            print(f"🧹 CLEANUP: Clearing invalid session for user_id: {user_id}")
            session.clear()
            logout_user()


@public_api_bp.app_context_processor
def inject_user_role():
    """Inject user role information into all templates"""
    from models import Manager, Admin
    # Safe check: current_user might be None in background threads
    is_manager = isinstance(current_user._get_current_object(), Manager) if current_user and current_user.is_authenticated else False
    is_admin = isinstance(current_user._get_current_object(), Admin) if current_user and current_user.is_authenticated else False
    return dict(
        is_manager=is_manager,
        is_admin=is_admin,
        manager_authenticated=is_manager,
        admin_authenticated=is_admin
    )




# SEO Footer context processor - load from JSON files for performance
_seo_cache = {
    'streets': None,
    'districts': None,
    'loaded': False
}

@public_api_bp.app_context_processor
def inject_seo_footer_data():
    """Inject SEO footer data (streets and districts) for Krasnodar - loads from JSON files"""
    import json
    import os
    
    # Check if we need current_city context
    try:
        current_city = getattr(g, 'current_city', None)
        if not current_city or current_city.slug != 'krasnodar':
            return dict(seo_streets=[], seo_districts=[])
    except:
        return dict(seo_streets=[], seo_districts=[])
    
    # Load from cache if available
    if _seo_cache['loaded']:
        return dict(
            seo_streets=_seo_cache['streets'],
            seo_districts=_seo_cache['districts']
        )
    
    try:
        base_path = os.path.dirname(__file__)
        
        # Load streets from JSON file (1600 streets)
        streets_path = os.path.join(base_path, 'data', 'seo_streets.json')
        if os.path.exists(streets_path):
            with open(streets_path, 'r', encoding='utf-8') as f:
                streets = json.load(f)
        else:
            streets = []
        
        # Load districts from JSON file (52 districts/microdistricts)
        districts_path = os.path.join(base_path, 'data', 'seo_districts.json')
        if os.path.exists(districts_path):
            with open(districts_path, 'r', encoding='utf-8') as f:
                districts = json.load(f)
        else:
            districts = []
        
        # Update cache
        _seo_cache['streets'] = streets
        _seo_cache['districts'] = districts
        _seo_cache['loaded'] = True
        
        return dict(seo_streets=streets, seo_districts=districts)
    except Exception as e:
        print(f"Error loading SEO footer data: {e}")
        return dict(seo_streets=[], seo_districts=[])



