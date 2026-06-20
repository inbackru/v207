import os
import nearby_places
import json
import logging
import requests
import traceback

from types import SimpleNamespace
# Configure logging for debugging PDF generation
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, abort, Blueprint, send_from_directory, send_file, make_response, g
from sqlalchemy import text, func
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect, validate_csrf
from werkzeug.exceptions import BadRequest

# Configure CSRF protection - ENABLED for security

# Import smart search
from smart_search import smart_search
import math
from urllib.parse import unquote, quote
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
import secrets
import threading
import time
import atexit
import glob
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
from email_service import send_notification, send_email
from services.geocoding import get_geocoding_service
from services.dadata_client import get_dadata_client
from flask_caching import Cache
from flask_compress import Compress
from services.alert_service import AlertService
import qrcode
from seo_redirects import get_redirect_city_slug, redirect_to_city_based, get_city_slug_for_resource
import io
import base64
from PIL import Image

# Models and repositories will be imported after db initialization to avoid circular imports


# Import unified transliteration functions
from utils.transliteration import create_slug, create_complex_slug, create_developer_slug
def parse_address_components(address_display_name):
    """
    ИСПРАВЛЕННАЯ ФУНКЦИЯ: Парсит адрес в формате: Россия, Краснодарский край, Сочи, Кудепста м-н, Искры, 88 лит7
    Возвращает словарь с компонентами адреса
    """
    # ПОЛНАЯ ИНИЦИАЛИЗАЦИЯ РЕЗУЛЬТАТА
    result = {
        'country': None,
        'region': None, 
        'city': None,
        'district': None,
        'street': None,
        'house_number': None
    }
    
    if not address_display_name:
        return result
    
    # РАЗБИВАЕМ АДРЕС ПО ЗАПЯТЫМ
    parts = [part.strip() for part in address_display_name.split(',')]
    
    # ПРЯМОЕ ЗАПОЛНЕНИЕ ОСНОВНЫХ ЧАСТЕЙ
    if len(parts) >= 1:
        result['country'] = parts[0]  # Россия
        
    if len(parts) >= 2:
        result['region'] = parts[1]   # Краснодарский край
        
    if len(parts) >= 3:
        result['city'] = parts[2]     # Сочи
        
    # ОБРАБАТЫВАЕМ ОСТАВШИЕСЯ ЧАСТИ (район, улица, дом)
    if len(parts) >= 4:
        remaining_parts = parts[3:]  # ['Дагомыс', 'Российская', '26г стр']
        
        if len(remaining_parts) == 1:
            # Одна часть: может быть район или улица
            part = remaining_parts[0]
            if any(marker in part for marker in ['м-н', 'микрорайон', 'ЖК', 'жилой комплекс']):
                result['district'] = part
            else:
                result['street'] = part
                
        elif len(remaining_parts) == 2:
            # Две части: район+улица или улица+дом
            first_part, second_part = remaining_parts[0], remaining_parts[1]
            
            if any(marker in first_part for marker in ['м-н', 'микрорайон']):
                result['district'] = first_part
                result['street'] = second_part
            else:
                result['street'] = first_part
                result['house_number'] = second_part
                
        elif len(remaining_parts) == 3:
            # Три части: район, улица, дом
            result['district'] = remaining_parts[0]
            result['street'] = remaining_parts[1]
            result['house_number'] = remaining_parts[2]
            
        elif len(remaining_parts) >= 4:
            # Больше трех частей: район, улица, дом (остальное объединяем в дом)
            result['district'] = remaining_parts[0]
            result['street'] = remaining_parts[1]
            result['house_number'] = ', '.join(remaining_parts[2:])
    
    return result

def resolve_city_context(city_id=None, city_slug=None, default_if_none=True):
    """
    Resolve city context with priority order.
    
    Priority order:
        1. city_id parameter (explicit override)
        2. city_slug parameter (explicit override)
        3. session['city_id'] (user's selected city)
        4. default city (fallback if default_if_none=True)
    
    Args:
        city_id: Integer city ID
        city_slug: String city slug (e.g., 'krasnodar', 'sochi')
        default_if_none: If True, return default city when no params provided
        
    Returns:
        City: City model instance (NOT dict) with attributes: id, name, slug
        None: If city not found and default_if_none is False
        
    Examples:
        resolve_city_context(city_id=1) -> City(id=1, name='Краснодар', ...)
        resolve_city_context(city_slug='sochi') -> City(id=2, name='Сочи', ...)
        resolve_city_context() -> City from session or default (Краснодар)
    """
    from models import City
    
    city = None
    
    # Try to find city by ID
    if city_id:
        try:
            city = City.query.filter_by(id=int(city_id), is_active=True).first()
        except (ValueError, TypeError):
            pass
    
    # Try to find city by slug
    if not city and city_slug:
        city = City.query.filter_by(slug=city_slug, is_active=True).first()
    
    # Try session (user's selected city)
    if not city and 'city_id' in session:
        try:
            city = City.query.filter_by(id=session['city_id'], is_active=True).first()
        except (KeyError, ValueError, TypeError):
            pass
    
    # Fallback to default city if requested
    if not city and default_if_none:
        city = City.query.filter_by(is_default=True, is_active=True).first()
    
    # Return City model directly (NOT dict)
    return city

# DEPRECATED: Legacy function for excel_properties table - not used with normalized Property model
# def update_parsed_addresses():
#     """
#     DEPRECATED: Обновляет ВСЕ поля parsed_* для всех записей в базе данных
#     на основе address_display_name
#     
#     NOTE: This function is no longer used with the normalized Property model.
#     Address parsing is handled directly in Property model fields.
#     """
#     pass

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# Create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# PWA Push Notifications — VAPID keys (generate once, store in env)
app.config['VAPID_PUBLIC_KEY']  = os.environ.get('VAPID_PUBLIC_KEY',  'BGfIV-CV2dR_VC64j20pPWwaqnlJEuB2sv-9sy__gScPQX1G-O9bGl98k72Mv50HWUOv3c4zjnAZbnX_ZbSMJ_k')
app.config['VAPID_PRIVATE_KEY'] = os.environ.get('VAPID_PRIVATE_KEY', '2ru13vmOlxSnoUDR7apBbnSOFdwPDv_DacLGwG0yfqg')
app.config['VAPID_CLAIMS']      = {'sub': 'mailto:admin@inback.ru'}

# SEO: Production canonical base URL (always HTTPS)
CANONICAL_BASE_URL = 'https://inback.ru'

# Initialize CSRF protection after app creation - ENABLED FOR SECURITY
csrf = CSRFProtect(app)

# CSRF configuration (object defined at top of file)
app.config['WTF_CSRF_TIME_LIMIT'] = None  # No expiry - tokens valid for entire session
app.config['WTF_CSRF_SSL_STRICT'] = False  # Allow non-HTTPS for development

# ==========================================
# SENTRY ERROR TRACKING
# ==========================================
_SENTRY_DSN = os.environ.get('SENTRY_DSN')
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            integrations=[FlaskIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=0.1,      # 10% трейсов производительности
            profiles_sample_rate=0.05,   # 5% профилировщик
            send_default_pii=False,      # не отправлять персданные
            environment=os.environ.get('FLASK_ENV', 'production'),
        )
        print("✅ Sentry error tracking initialized")
    except Exception as _sentry_err:
        print(f"⚠️  Sentry init failed: {_sentry_err}")
else:
    print("ℹ️  Sentry disabled (SENTRY_DSN not set)")

# ==========================================
# COMPREHENSIVE SECURITY CONFIGURATION  
# ==========================================
# Initialize advanced security features:
# - Rate Limiting (DDoS protection)
# - Security Headers (XSS, Clickjacking protection)
# - Content Security Policy
# - Additional hardening measures
try:
    from security_config import init_security
    limiter, talisman = init_security(app)
    print("✅ Advanced security features initialized successfully")
except Exception as e:
    print(f"⚠️  Warning: Could not initialize advanced security: {e}")
    limiter = None
    talisman = None
# ИСПРАВЛЕНО (22.10.2025): Добавляем hasattr в Jinja2 для проверки типов пользователей
app.jinja_env.globals['hasattr'] = hasattr

# url_for alias map — routes moved from app.py to blueprints keep backward-compat endpoint names
_ENDPOINT_ALIASES = {
    'security': 'admin_api.security',
    'careers': 'admin_api.careers',
    'dashboard': 'mgr_api.dashboard',
    'view_collection': 'searches.view_collection',
    'client_collections': 'searches.client_collections',
    'book_appointment': 'searches.book_appointment',
    # public_api blueprint aliases (moved from app.py)
    'index': 'public_api.index',
    'api_property_detail': 'public_api.api_property_detail',
    'api_property_request_cashback': 'public_api.api_property_request_cashback',
    'api_property_request_online_showing': 'public_api.api_property_request_online_showing',
    'api_properties_batch': 'public_api.api_properties_batch',
    'api_residential_complexes': 'public_api.api_residential_complexes',
    'api_hero_complexes': 'public_api.api_hero_complexes',
    'api_residential_complexes_full': 'public_api.api_residential_complexes_full',
    'api_calculate_cashback': 'public_api.api_calculate_cashback',
    'api_apply_cashback': 'public_api.api_apply_cashback',
    'image_proxy': 'public_api.image_proxy',
    'cian_logo_proxy': 'public_api.cian_logo_proxy',
    'api_map_suggest': 'public_api.api_map_suggest',
    'api_properties': 'public_api.api_properties',
    'api_map_properties': 'public_api.api_map_properties',
    'api_properties_list': 'public_api.api_properties_list',
    'api_properties_count': 'public_api.api_properties_count',
    'api_residential_complexes_map': 'public_api.api_residential_complexes_map',
    'api_complex': 'public_api.api_complex',
    'api_complex_mini_card': 'public_api.api_complex_mini_card',
    'api_price_history_complex': 'public_api.api_price_history_complex',
    'api_price_history_property': 'public_api.api_price_history_property',
    'api_complexes_batch': 'public_api.api_complexes_batch',
    'api_mini_map_properties': 'public_api.api_mini_map_properties',
    'api_map_properties_aggregated': 'public_api.api_map_properties_aggregated',
    'api_map_properties_at_point': 'public_api.api_map_properties_at_point',
    'api_properties_polygon': 'public_api.api_properties_polygon',
    'api_properties_polygon_aggregated': 'public_api.api_properties_polygon_aggregated',
    'api_mini_map_complexes': 'public_api.api_mini_map_complexes',
    'download_property_pdf': 'public_api.download_property_pdf',
    'quiz_registration': 'public_api.quiz_registration',
    'callback_request_page': 'public_api.callback_request_page',
    'property_selection': 'public_api.property_selection',
    'switch_to_client': 'public_api.switch_to_client',
    'set_demo_password': 'public_api.set_demo_password',
    'set_managers_passwords': 'public_api.set_managers_passwords',
    # city_pages blueprint aliases
    'about_city': 'city_pages.about_city',
    'appraisal_city': 'city_pages.appraisal_city',
    'cashback_kvartiry_city': 'city_pages.cashback_kvartiry_city',
    'cashback_terms_city': 'city_pages.cashback_terms_city',
    'comparison_city': 'city_pages.comparison_city',
    'contacts_city': 'city_pages.contacts_city',
    'developer_mortgage_city': 'city_pages.developer_mortgage_city',
    'family_mortgage_city': 'city_pages.family_mortgage_city',
    'favorites_city': 'city_pages.favorites_city',
    'how_it_works_city': 'city_pages.how_it_works_city',
    'insurance_city': 'city_pages.insurance_city',
    'ipoteka_city': 'city_pages.ipoteka_city',
    'it_mortgage_city': 'city_pages.it_mortgage_city',
    'map_city': 'city_pages.map_city',
    'maternal_capital_city': 'city_pages.maternal_capital_city',
    'military_mortgage_city': 'city_pages.military_mortgage_city',
    'reviews_city': 'city_pages.reviews_city',
    'security_city': 'city_pages.security_city',
    'streets_city': 'city_pages.streets_city',
    'tax_deduction_city': 'city_pages.tax_deduction_city',
    # props blueprint aliases
    'properties_city': 'props.properties_city',
    'properties': 'props.properties',
    'property_detail_city': 'props.property_detail_city',
    # complexes blueprint aliases
    'residential_complex_by_slug_city': 'complexes.residential_complex_by_slug_city',
    'residential_complexes_city': 'complexes.residential_complexes_city',
    # blog blueprint aliases
    'blog_city': 'blog.blog_city',
    'blog_post': 'blog.blog_post',
    # devs blueprint aliases
    'developers_city': 'devs.developers_city',
    # main blueprint aliases
    'about': 'main.about',
    'contacts': 'main.contacts',
    'how_it_works': 'main.how_it_works',
    'reviews': 'main.reviews',
    'comparison': 'main.comparison',
    'favorites': 'main.favorites',
    'wallet': 'main.wallet',
    'referral_landing': 'main.referral_landing',
    'thank_you': 'main.thank_you',
    # search/api blueprint aliases
    'search_results': 'search_geo_api.search_results',
    # districts blueprint aliases
    'districts': 'districts.districts',
    'district_detail': 'districts.district_detail',
    # jobs blueprint aliases
    'job_detail': 'jobs.job_detail',
    'submit_job_application': 'jobs.submit_job_application',
    # favorites/presentations blueprint aliases
    'view_presentation': 'favorites.view_presentation',
    # auth blueprint aliases
    'upload_user_avatar': 'auth.upload_user_avatar',
}

_original_url_for = app.jinja_env.globals['url_for']

def _aliased_url_for(endpoint, **values):
    endpoint = _ENDPOINT_ALIASES.get(endpoint, endpoint)
    return _original_url_for(endpoint, **values)

app.jinja_env.globals['url_for'] = _aliased_url_for

# Also patch Flask's Python-level url_for so blueprint Python code works too
import flask as _flask
_flask_original_url_for = _flask.url_for

def _flask_aliased_url_for(endpoint, **values):
    endpoint = _ENDPOINT_ALIASES.get(endpoint, endpoint)
    return _flask_original_url_for(endpoint, **values)

_flask.url_for = _flask_aliased_url_for

# Patch the url_for in flask.helpers (what 'from flask import url_for' imports)
import flask.helpers as _flask_helpers
_flask_helpers.url_for = _flask_aliased_url_for

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

@app.errorhandler(Exception)
def handle_exception(e):
    db.session.rollback()
    return render_template('errors/500.html'), 500

# Add CSRF token to template context - ENABLED
@app.context_processor
def inject_csrf_token():
    from flask_wtf.csrf import generate_csrf
    return dict(csrf_token=generate_csrf)

@app.context_processor
def inject_admin_user():
    try:
        from models import Admin
        if current_user and current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin):
            return {'admin': current_user}
    except Exception:
        pass
    return {}

def validate_json_csrf():
    """Validate CSRF token for JSON requests"""
    try:
        # For JSON requests, check both header and JSON payload
        token = request.headers.get('X-CSRFToken')
        print(f"🔒 CSRF CHECK: Header token: {token[:20] if token else 'MISSING'}...")
        
        if not token and request.is_json:
            data = request.get_json()
            token = data.get('csrf_token') if data else None
            print(f"🔒 CSRF CHECK: JSON token: {token[:20] if token else 'MISSING'}...")
        
        if not token:
            print("❌ CSRF CHECK: No token found in header or JSON")
            return False
        
        validate_csrf(token)
        print("✅ CSRF CHECK: Token validated successfully")
        return True
    except Exception as e:
        print(f"❌ CSRF CHECK: Validation failed with error: {e}")
        return False

def require_json_csrf(f):
    """Decorator to require CSRF protection for JSON endpoints"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check CSRF for all dangerous HTTP methods with JSON content
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE'] and request.is_json:
            if not validate_json_csrf():
                return jsonify({'success': False, 'error': 'CSRF token missing or invalid'}), 400
        return f(*args, **kwargs)
    return decorated_function

# Русские названия месяцев для локализации
RUSSIAN_MONTHS = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
    5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
    9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
}

@app.template_filter('russian_date')
def russian_date_filter(date_value):
    """Форматирует дату на русском языке"""
    if not date_value:
        return 'Недавно'
    
    if isinstance(date_value, str):
        return date_value
    
    day = date_value.day
    month = RUSSIAN_MONTHS.get(date_value.month, date_value.strftime('%B'))
    year = date_value.year
    
    return f"{day} {month} {year}"

@app.template_filter('msk_time')
def msk_time_filter(utc_datetime, format='%d.%m.%Y в %H:%M'):
    """Конвертирует UTC время в московское (MSK = UTC+3) и форматирует"""
    if not utc_datetime:
        return 'Недавно'
    
    if isinstance(utc_datetime, str):
        return utc_datetime
    
    from datetime import timedelta
    # Конвертируем UTC в MSK (UTC+3)
    msk_datetime = utc_datetime + timedelta(hours=3)
    return msk_datetime.strftime(format)

# Кэш файловой системы — работает корректно при нескольких Gunicorn-воркерах
# (CACHE_TYPE='simple' хранит данные в памяти процесса и не разделяется между воркерами)
_FLASK_CACHE_DIR = os.environ.get('FLASK_CACHE_DIR', '/tmp/flask_cache')
os.makedirs(_FLASK_CACHE_DIR, exist_ok=True)
app.config['CACHE_TYPE'] = 'FileSystemCache'
app.config['CACHE_DIR'] = _FLASK_CACHE_DIR
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 минут
app.config['CACHE_THRESHOLD'] = 2000       # макс. ключей на диске
cache = Cache(app)
# Включаем Gzip сжатие для всех ответов (HTML, CSS, JS, XML)
compress = Compress()
compress.init_app(app)
app.config["COMPRESS_MIMETYPES"] = ["text/html", "text/css", "text/xml", "application/json", "application/javascript", "application/xml+rss", "application/atom+xml", "image/svg+xml"]

# Always reload Jinja2 templates from disk (prevents stale cache in gunicorn workers)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# Session configuration for Replit iframe environment
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 30  # 30 days
app.config['WTF_CSRF_TIME_LIMIT'] = None  # No expiry - tokens valid for entire session
app.config['WTF_CSRF_SSL_STRICT'] = False  # Allow development over HTTP
app.config['SESSION_PERMANENT'] = True  # Make sessions permanent by default

# Enable permanent sessions by default
from datetime import timedelta
app.permanent_session_lifetime = timedelta(days=30)

# Configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///properties.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Configure file uploads
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Add route for uploaded files

# ========================================
# HELPER: Smart Property ID Resolution
# ========================================
def resolve_property_by_identifier(identifier):
    """
    Resolve property by identifier - handles both inner_id (string) and database ID (int).
    
    This is needed because:
    - JavaScript sends inner_id in URLs (e.g., "1999611557")
    - CollectionProperty.property_id contains MIXED types (old: database IDs, new: inner_ids)
    
    Returns:
        tuple: (Property object, canonical_identifier_for_collection_property)
        Returns (None, None) if not found
    
    Usage:
        property_obj, canonical_id = resolve_property_by_identifier(property_id)
        if not property_obj:
            return error_response()
    """
    from models import Property as PropertyModel
    
    # Try as inner_id first (most common case from frontend)
    property_obj = PropertyModel.query.filter_by(inner_id=str(identifier)).first()
    if property_obj:
        print(f"DEBUG: ✅ Found property by inner_id: {identifier}")
        return property_obj, str(property_obj.inner_id)
    
    # If not found, try as database ID (legacy data)
    try:
        db_id = int(identifier)
        property_obj = PropertyModel.query.get(db_id)
        if property_obj:
            print(f"DEBUG: ✅ Found property by database ID: {db_id} (inner_id: {property_obj.inner_id})")
            return property_obj, str(property_obj.inner_id)
    except (ValueError, TypeError):
        pass
    
    print(f"DEBUG: ❌ Property not found: {identifier} (tried inner_id and database ID)")
    return None, None

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Initialize the app with the extension
db.init_app(app)

# Import and register all models with SQLAlchemy after db initialization
with app.app_context():
    # Import all models explicitly to ensure they are registered with SQLAlchemy
    from models import (User, Manager, SavedSearch, SentSearch, PropertyAlert, BlogPost, BlogArticle, Category, 
                       Developer, ResidentialComplex, CashbackRecord, 
                       Application, Favorite, Notification, District, Street, RoomType, 
                       Admin, City, Region, Offer, MarketingMaterial, ManagerCheckin, Referral,
                       Partner, PartnerReferral, PartnerWithdrawal)
    try:
        db.create_all()
        print("Database tables created successfully!")
    except Exception as e:
        print(f"Note: db.create_all() encountered: {e}")
        db.session.rollback()

    # ── pg_trgm GIN-индексы для ILIKE-поиска ──────────────────────────────
    # Ускоряет OR ILIKE '%word%' по 8+ столбцам с 50 тыс. строк до <10 мс.
    # Безопасно: CONCURRENTLY + IF NOT EXISTS; пропускается на SQLite.
    try:
        from sqlalchemy import text as _trgm_text
        db.session.execute(_trgm_text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        _trgm_indexes = [
            # properties
            ("idx_prop_address_trgm",         "properties",            "address"),
            ("idx_prop_parsed_district_trgm",  "properties",            "parsed_district"),
            ("idx_prop_parsed_settlement_trgm","properties",            "parsed_settlement"),
            ("idx_prop_parsed_area_trgm",      "properties",            "parsed_area"),
            ("idx_prop_parsed_street_trgm",    "properties",            "parsed_street"),
            ("idx_prop_title_trgm",            "properties",            "title"),
            ("idx_prop_parsed_city_trgm",      "properties",            "parsed_city"),
            # residential_complexes
            ("idx_rc_name_trgm",               "residential_complexes", "name"),
            ("idx_rc_addr_district_trgm",      "residential_complexes", "address_city_district"),
            ("idx_rc_addr_quarter_trgm",       "residential_complexes", "address_quarter"),
            # developers / districts
            ("idx_dev_name_trgm",              "developers",            "name"),
            ("idx_dist_name_trgm",             "districts",             "name"),
        ]
        for idx_name, tbl, col in _trgm_indexes:
            try:
                db.session.execute(_trgm_text(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name} "
                    f"ON {tbl} USING GIN ({col} gin_trgm_ops)"
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()
        print("✅ pg_trgm GIN indexes verified/created")
    except Exception as _trgm_err:
        db.session.rollback()
        print(f"ℹ️  pg_trgm indexes skipped (SQLite or no superuser): {_trgm_err}")
    # ── конец pg_trgm ──────────────────────────────────────────────────────

    # Синхронизируем состояние прокси из DB → /tmp при каждом старте
    try:
        from models import ChatSettings as _CS
        _proxy_val = _CS.get('image_proxy_enabled', '1')
        _flag = '/tmp/image_proxy_disabled'
        if _proxy_val == '0':
            open(_flag, 'w').close()
        elif os.path.exists(_flag):
            os.remove(_flag)
    except Exception:
        pass
    # Add file attachment columns to chat_messages if not present
    try:
        from sqlalchemy import text as _sql_text
        with db.engine.connect() as _conn:
            _conn.execute(_sql_text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_url VARCHAR(500)"))
            _conn.execute(_sql_text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)"))
            _conn.execute(_sql_text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_type VARCHAR(50)"))
            _conn.commit()
    except Exception as _e:
        print(f"Chat file columns migration note: {_e}")
    # Add overlay_opacity to promo_banners if not present
    try:
        from sqlalchemy import text as _sql_text
        with db.engine.connect() as _conn:
            _conn.execute(_sql_text("ALTER TABLE promo_banners ADD COLUMN IF NOT EXISTS overlay_opacity FLOAT DEFAULT 0"))
            _conn.commit()
    except Exception as _e:
        print(f"Promo banners overlay_opacity migration note: {_e}")

    # TrendAgent extended fields migration — residential_complexes
    try:
        from sqlalchemy import text as _sql_text
        _rc_cols = [
            "apartments_count INTEGER",
            "parking_count INTEGER",
            "commerce_count INTEGER",
            "pano_url VARCHAR(500)",
            "ta_level_type VARCHAR(100)",
            "ta_location_name VARCHAR(200)",
            "ta_location_guid VARCHAR(200)",
            "facade_type VARCHAR(100)",
            "contract_type VARCHAR(100)",
            "ta_payment_types TEXT",
            "is_exclusive BOOLEAN",
            "is_mortgage_available BOOLEAN",
            "view_places VARCHAR(300)",
            "interactive_plan_url VARCHAR(500)",
            "has_gym BOOLEAN",
            "has_garden BOOLEAN",
            "ta_rooms_types TEXT",
            "ta_passport TEXT",
            "ta_min_price INTEGER",
            # v2 fields
            "ta_crm_id BIGINT",
            "ta_guid VARCHAR(200)",
            "ta_advantage TEXT",
            "ta_subways TEXT",
            "ta_point_distances TEXT",
            "ta_status INTEGER",
            "ta_aliases TEXT",
            "is_with_prayer_room BOOLEAN",
            "ta_plan_images TEXT",
            "ta_sales_start_display VARCHAR(200)",
            "ta_escrow BOOLEAN",
            "ta_deadline_key_display VARCHAR(200)",
            "ta_renderer_json TEXT",
            "ta_point_metro_time INTEGER",
            "ta_min_area FLOAT",
            "ta_max_area FLOAT",
            "ta_min_floor INTEGER",
            "ta_max_floor INTEGER",
            "ta_scraped_at TIMESTAMP",
            "parsed_at TIMESTAMP",
            "parsing_status VARCHAR(50)",
        ]
        with db.engine.connect() as _conn:
            for _col_def in _rc_cols:
                _conn.execute(_sql_text(f"ALTER TABLE residential_complexes ADD COLUMN IF NOT EXISTS {_col_def}"))
            _conn.commit()
        print("✅ TrendAgent RC columns migrated")
    except Exception as _e:
        print(f"TrendAgent RC columns migration note: {_e}")

    # TrendAgent extended fields migration — buildings
    try:
        from sqlalchemy import text as _sql_text
        _bld_cols = [
            "deadline_key TIMESTAMP",
            "sales_start_at TIMESTAMP",
            "queue INTEGER",
            "building_type_name VARCHAR(100)",
            "facade_type_name VARCHAR(100)",
            "elevator_type VARCHAR(100)",
            "address_street VARCHAR(300)",
            "escrow BOOLEAN",
            "has_mortgage BOOLEAN",
            "has_installment BOOLEAN",
            "has_subsidy BOOLEAN",
            "has_mortgage_military BOOLEAN",
            "is_exclusive BOOLEAN",
            "parking_types TEXT",
            "finishing_types TEXT",
            "contract_types TEXT",
            "ta_payment_types TEXT",
            # v2 fields
            "escrow_banks TEXT",
            "ta_permit VARCHAR(200)",
            "apartment_count INTEGER",
            "is_with_pool BOOLEAN",
            "pool_types TEXT",
            "safety_types TEXT",
            "deadline_key_type INTEGER",
            "subsidy BOOLEAN",
            "ta_renderer TEXT",
            "ta_interactive_geometry TEXT",
            "ta_scraped_at TIMESTAMP",
            "boundary_geometry TEXT",
        ]
        with db.engine.connect() as _conn:
            for _col_def in _bld_cols:
                _conn.execute(_sql_text(f"ALTER TABLE buildings ADD COLUMN IF NOT EXISTS {_col_def}"))
            _conn.commit()
        print("✅ TrendAgent Building columns migrated")
    except Exception as _e:
        print(f"TrendAgent Building columns migration note: {_e}")

    # Fix ta_crm_id on residential_complexes: INTEGER → BIGINT
    try:
        from sqlalchemy import text as _sql_text
        with db.engine.connect() as _conn:
            _conn.execute(_sql_text(
                "ALTER TABLE residential_complexes ALTER COLUMN ta_crm_id TYPE BIGINT"
            ))
            _conn.commit()
        print("✅ ta_crm_id upgraded to BIGINT")
    except Exception as _e:
        if "already" not in str(_e).lower() and "bigint" not in str(_e).lower():
            print(f"ta_crm_id BIGINT migration note: {_e}")

    # TrendAgent apartment (шахматка) fields migration — properties
    try:
        from sqlalchemy import text as _sql_text
        _prop_cols = [
            "is_suite BOOLEAN",
            "ta_view_type INTEGER",
            "ta_view_places TEXT",
            "ta_reward_label VARCHAR(50)",
            "ta_finishing_main TEXT",
            "ta_finishing_additional TEXT",
            "ta_crm_id VARCHAR(50)",
            "ta_north FLOAT",
            "ta_status_crm_id INTEGER",
            "ta_exclusive BOOLEAN",
            "ta_block_guid VARCHAR(200)",
            "end_build_year INTEGER",
            "end_build_quarter INTEGER",
        ]
        with db.engine.connect() as _conn:
            for _col_def in _prop_cols:
                _conn.execute(_sql_text(f"ALTER TABLE properties ADD COLUMN IF NOT EXISTS {_col_def}"))
            _conn.commit()
        print("✅ TrendAgent Property (apartment) columns migrated")
    except Exception as _e:
        print(f"TrendAgent Property columns migration note: {_e}")

# Import repositories after db initialization to avoid circular imports
from repositories.property_repository import PropertyRepository, ResidentialComplexRepository, DeveloperRepository

# Import Manager and Admin for isinstance checks throughout the file
from models import Manager, Admin

# Add Jinja2 helper for creating slugs
@app.template_filter('slug')
def create_slug_filter(name):
    """Jinja2 filter for creating SEO-friendly slug from complex name"""
    return create_slug(name)

# Create API blueprint without login requirement
api_bp = Blueprint('api', __name__, url_prefix='/api')

# Debug endpoint removed for security - exposed session data

@api_bp.route('/properties/filter')
def api_properties_filter():
    """
    ✅ MIGRATED TO NORMALIZED TABLES (Property → ResidentialComplex → Developer)
    Unified API endpoint for filtering properties.
    Supports pagination, sorting, and returns properties with coordinates for map.
    
    Query parameters:
        - All filter parameters from build_property_filters()
        - page (int): Page number (default: 1)
        - per_page (int): Results per page (default: 20, max: 100)
        - sort (str): Sort type (price_asc, price_desc, area_asc, area_desc, date_desc)
    
    Returns:
        JSON with:
        - success (bool)
        - properties (list): Filtered properties with coordinates
        - total (int): Total count of filtered properties
        - page (int): Current page
        - per_page (int): Results per page
        - total_pages (int): Total pages
    """
    try:
        # Use unified filter function to parse request arguments
        where_conditions, params, filters_parsed = build_property_filters(request.args)
        
        # Convert build_property_filters() output to PropertyRepository filter format
        repo_filters = {
            'min_price': params.get('price_min'),
            'max_price': params.get('price_max'),
            'min_area': params.get('area_min'),
            'max_area': params.get('area_max'),
            'floor_min': params.get('floor_min'),
            'floor_max': params.get('floor_max'),
            'building_floors_min': params.get('building_floors_min'),
            'building_floors_max': params.get('building_floors_max'),
            'rooms': filters_parsed.get('rooms', []),
            'developer': filters_parsed.get('developer'),
            'developers': filters_parsed.get('developers', []),
            'district': filters_parsed.get('district'),
            'districts': filters_parsed.get('districts', []),
            'residential_complex': filters_parsed.get('residential_complex'),
            'building': filters_parsed.get('building'),
            'cashback_only': filters_parsed.get('cashback_only', False),
            'renovation': filters_parsed.get('renovation', []),
            'property_type': filters_parsed.get('property_type'),
            'object_classes': filters_parsed.get('object_classes', []),
            'building_types': filters_parsed.get('building_types', []),
            'floor_options': filters_parsed.get('floor_options', []),
            'deal_type': filters_parsed.get('deal_type'),
            'search': filters_parsed.get('search')
        }
        
        # Add city_id filter — accept from request args, then fall back to session
        city_id_arg = request.args.get('city_id', type=int)
        if city_id_arg:
            repo_filters['city_id'] = city_id_arg
        elif session.get('city_id'):
            repo_filters['city_id'] = session.get('city_id')

        # Resolve district slugs → IDs for FK-based filtering (same as properties_city route)
        raw_districts = repo_filters.get('districts', [])
        if raw_districts:
            from models import District as _DistModel
            resolved_ids = []
            unresolved_names = []
            _city_id_for_dist = repo_filters.get('city_id')
            for dval in raw_districts:
                dval = str(dval).strip()
                if not dval:
                    continue
                _dq = _DistModel.query
                if _city_id_for_dist:
                    _dq = _dq.filter_by(city_id=_city_id_for_dist)
                _dobj = _dq.filter_by(slug=dval).first()
                if not _dobj:
                    _dobj = _dq.filter(_DistModel.name.ilike(f'%{dval}%')).first()
                if _dobj:
                    resolved_ids.append(_dobj.id)
                else:
                    unresolved_names.append(dval)
            if resolved_ids:
                repo_filters['district_id_in'] = resolved_ids
                del repo_filters['districts']
            elif unresolved_names:
                repo_filters['districts'] = unresolved_names

        # Remove None values from filters
        repo_filters = {k: v for k, v in repo_filters.items() if v is not None and v != [] and v != ''}
        
        # Pagination parameters
        page = request.args.get('page', default=1, type=int)
        page = max(1, page)
        per_page = request.args.get('per_page', default=20, type=int)
        per_page = min(max(1, per_page), 10000)  # Limit to 10000 max (for map view)
        offset = (page - 1) * per_page
        
        # Sorting
        sort_type = request.args.get('sort', 'price_asc').replace('_', '-').replace('-', '_')
        sort_by = 'price'
        sort_order = 'asc'
        
        if sort_type == 'price_desc':
            sort_by, sort_order = 'price', 'desc'
        elif sort_type == 'price_asc':
            sort_by, sort_order = 'price', 'asc'
        elif sort_type == 'area_asc':
            sort_by, sort_order = 'area', 'asc'
        elif sort_type == 'area_desc':
            sort_by, sort_order = 'area', 'desc'
        elif sort_type == 'date_desc':
            sort_by, sort_order = 'date', 'desc'
        
        # Get total count using PropertyRepository
        total = PropertyRepository.count_active(filters=repo_filters)
        
        # Get properties using PropertyRepository
        properties_orm = PropertyRepository.get_all_active(
            limit=per_page,
            offset=offset,
            filters=repo_filters,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        # Format properties for JSON response (maintain backward compatibility)
        properties = []
        for prop in properties_orm:
            # Parse gallery images
            main_image = 'https://via.placeholder.com/400x300?text=No+Photo'
            gallery = [main_image]
            
            if prop.gallery_images:
                try:
                    photos_raw = json.loads(prop.gallery_images)
                    if photos_raw and isinstance(photos_raw, list) and len(photos_raw) > 0:
                        main_image = photos_raw[0]
                        gallery = photos_raw[:5]
                except:
                    pass
            elif prop.main_image:
                main_image = prop.main_image
                gallery = [main_image]
            
            # Format room type
            rooms = int(prop.rooms or 0)
            room_type = "Студия" if rooms == 0 else f"{rooms}-комн"
            
            # Format floor info
            floor = int(prop.floor or 1)
            total_floors = int(prop.total_floors or floor)
            floor_text = f"{floor}/{total_floors}"
            
            # Get cashback rate from residential complex
            cashback_rate = None
            if prop.residential_complex:
                cashback_rate = float(prop.residential_complex.cashback_rate) if prop.residential_complex.cashback_rate else None
            
            # Build property object
            prop_dict = {
                'id': prop.inner_id or str(prop.id),
                'price': int(prop.price or 0),
                'area': float(prop.area or 0),
                'rooms': rooms,
                'floor': floor,
                'total_floors': total_floors,
                'room_type': room_type,
                'floor': floor_text,
                'floor_min': floor,
                'floor_max': total_floors,
                'title': f"{room_type}, {prop.area} м²",
                'address': prop.address or '',
                'complex_name': prop.residential_complex.name if prop.residential_complex else '',
                'residential_complex': prop.residential_complex.name if prop.residential_complex else '',
                'developer': prop.developer.name if prop.developer else '',
                'district': prop.district.name if prop.district else '',
                'image': main_image,
                'gallery': gallery,
                'object_class': '',  # Can add if needed
                'renovation': PropertyRepository.get_renovation_display_name(prop.renovation_type),
                'cashback_rate': cashback_rate,
                'cashback_available': bool(cashback_rate and cashback_rate > 0),
                'url': f'/object/{prop.inner_id or prop.id}',
                # Coordinates for map
                'lat': float(prop.latitude) if prop.latitude else None,
                'lon': float(prop.longitude) if prop.longitude else None,
                'coordinates': {
                    'lat': float(prop.latitude) if prop.latitude else None,
                    'lng': float(prop.longitude) if prop.longitude else None
                } if prop.latitude and prop.longitude else None,
                'distance_to_center': float(prop.residential_complex.distance_to_center) if prop.residential_complex and prop.residential_complex.distance_to_center else None
            }
            
            properties.append(prop_dict)
        
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0
        
        return jsonify({
            'success': True,
            'properties': properties,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'filters_applied': filters_parsed
        })
        
    except Exception as e:
        print(f"❌ Error in /api/properties/filter: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'properties': [],
            'total': 0
        }), 500

@api_bp.route('/property/<int:property_id>/cashback')
def api_property_cashback(property_id):
    """✅ MIGRATED - Get cashback information using PropertyRepository"""
    try:
        # Get property using PropertyRepository
        prop = PropertyRepository.get_by_id(property_id)
        
        if not prop:
            return jsonify({'success': False, 'error': 'Property not found'})
        
        # Extract data from Property model
        price = int(prop.price or 0)
        rooms = int(prop.rooms or 0)
        complex_name = prop.residential_complex.name if prop.residential_complex else "Не указан"
        
        # Get cashback rate from ResidentialComplex
        cashback_percent = 0
        if prop.residential_complex and prop.residential_complex.cashback_rate:
            cashback_percent = float(prop.residential_complex.cashback_rate)
        
        # Calculate cashback amount
        cashback_amount = price * (cashback_percent / 100)
        
        # Format property name
        room_text = f"{rooms}-комнатная квартира" if rooms > 0 else "Студия"
        property_name = f"{room_text} в ЖК «{complex_name}»"
        
        return jsonify({
            'success': True,
            'property_id': property_id,
            'property_name': property_name,
            'property_price': price,
            'cashback_percent': cashback_percent,
            'cashback_amount': int(cashback_amount),
            'complex_name': complex_name,
            'rooms': rooms
        })
        
    except Exception as e:
        print(f"Error getting property cashback: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Server error'})

# Custom Jinja2 filters
def street_slug(street_name):
    """Convert street name to URL slug with transliteration"""
    import re
    
    # Transliteration mapping for Russian to Latin
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    
    # Clean the name
    name = str(street_name).strip().lower()
    # Remove extra characters
    name = re.sub(r'[«»"\(\)\.,:;]', '', name)
    
    # Transliterate
    result = ''
    for char in name:
        result += translit_map.get(char, char)
    
    # Replace spaces with hyphens and clean up
    result = re.sub(r'\s+', '-', result)
    result = re.sub(r'-+', '-', result)
    result = result.strip('-')
    
    return result

def number_format(value):
    """Format number with space separators"""
    try:
        if isinstance(value, str):
            value = int(value)
        return f"{value:,}".replace(',', ' ')
    except (ValueError, TypeError):
        return str(value)

@app.template_filter('developer_slug')
def developer_slug(developer_name):
    """Convert developer name to URL slug with transliteration"""
    import re
    if not developer_name:
        return ""
    
    # Transliteration mapping for Russian to Latin
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'YO',
        'Ж': 'ZH', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'KH', 'Ц': 'TS', 'Ч': 'CH', 'Ш': 'SH', 'Щ': 'SCH',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'YU', 'Я': 'YA'
    }
    
    # Remove extra spaces and clean
    name = str(developer_name).strip()
    # Remove quotes, parentheses, dots, commas
    name = re.sub(r'[«»"\(\)\.,:;]', '', name)  
    
    # Transliterate cyrillic to latin
    result = ''
    for char in name:
        result += translit_map.get(char, char)
    
    # Replace spaces with hyphens and clean up
    result = re.sub(r'\s+', '-', result)  # Replace spaces with hyphens
    result = re.sub(r'-+', '-', result)   # Replace multiple hyphens with single
    result = result.strip('-')  # Remove leading/trailing hyphens
    return result.lower()

@app.template_filter('from_json')
def from_json_filter(json_string):
    """Парсит JSON строку в объект Python"""
    if not json_string:
        return []
    try:
        if isinstance(json_string, str):
            return json.loads(json_string)
        return json_string
    except (json.JSONDecodeError, TypeError):
        return []

@app.template_filter('strip_phones')
def strip_phones_filter(text):
    """Убирает российские номера телефонов и HTML из текста описания"""
    import re
    if not text:
        return text
    # Remove complete HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove incomplete/truncated HTML tags at any position (e.g. "<span c" at end)
    text = re.sub(r'<\s*/?[a-zA-Z][^\s>]*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'<[^>]*$', '', text)
    # Remove phone patterns: +7..., 8-800-..., (xxx) xxx-xx-xx, etc.
    text = re.sub(r'(?:\+7|8)[\s\-\(]?\d{3}[\s\-\)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', '', text)
    text = re.sub(r'\b8\s*\(\s*\d{3}\s*\)\s*\d{3}[\s\-]\d{2}[\s\-]\d{2}\b', '', text)
    text = re.sub(r'\bтел\.?:?\s*[\d\s\-\(\)\+]{10,20}', '', text, flags=re.IGNORECASE)
    # Clean up leftover whitespace artifacts
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

@app.template_filter('format_number')
def format_number_filter(value):
    """Format number with space as thousands separator (Russian style): 500000 → 500 000"""
    try:
        return '{:,}'.format(int(value)).replace(',', ' ')
    except (ValueError, TypeError):
        return value

def _is_image_proxy_enabled():
    """Check image proxy setting: /tmp flag (fast) then DB fallback."""
    import os as _os
    if _os.path.exists('/tmp/image_proxy_disabled'):
        return False
    try:
        from models import ChatSettings as _CS
        return _CS.get('image_proxy_enabled', '1') != '0'
    except Exception:
        return True

@app.template_filter('crop_watermark')
def crop_watermark_filter(image_url, crop_percent=8):
    """
    Convert image URL to proxied URL with watermark cropped.
    Respects the admin image_proxy_enabled setting — returns original URL when disabled.
    Usage in template: {{ image_url | crop_watermark(10) }}
    """
    if not image_url:
        return image_url
    if image_url.startswith('/'):
        return image_url
    if not _is_image_proxy_enabled():
        return image_url
    import base64
    encoded = base64.urlsafe_b64encode(image_url.encode('utf-8')).decode('ascii')
    return f"/api/image-proxy?b={encoded}&crop={crop_percent}"

def format_room_display(rooms):
    """Format room count for display"""
    if rooms == 0:
        return "Студия"
    else:
        return f"{rooms}-комнатная квартира"

app.jinja_env.filters['street_slug'] = street_slug
app.jinja_env.filters['number_format'] = number_format
app.jinja_env.filters['developer_slug'] = developer_slug

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # type: ignore
login_manager.login_message = 'Войдите в аккаунт для доступа к этой странице.'
login_manager.login_message_category = 'info'
login_manager.session_protection = None
login_manager.remember_cookie_duration = timedelta(days=30)


@login_manager.unauthorized_handler
def handle_unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Не авторизован'}), 401
    return redirect(url_for('auth.login', next=request.url))


@login_manager.user_loader
def load_user(user_id):
    """Request-scoped caching to prevent repeated DB queries"""
    from models import User, Manager, Admin
    cache_key = f'_user_cache_{user_id}'
    if hasattr(g, cache_key):
        return getattr(g, cache_key)
    user = None
    if user_id.startswith('m_'):
        user = Manager.query.get(int(user_id[2:]))
    elif user_id.startswith('a_'):
        user = Admin.query.get(int(user_id[2:]))
    elif user_id.startswith('p_'):
        from models import Partner
        user = Partner.query.get(int(user_id[2:]))
    else:
        try:
            user = User.query.get(int(user_id))
        except (ValueError, TypeError):
            pass
    setattr(g, cache_key, user)
    return user




# Property data loading functions with cache
_properties_cache = None
_cache_timestamp = None
CACHE_TIMEOUT = 300  # 5 minutes

# Complexes map API cache (per city_id, 60s TTL)
_complexes_map_cache = {}
_complexes_map_cache_ts = {}
COMPLEXES_MAP_CACHE_TIMEOUT = 600  # 10 minutes

# Route-level cache for residential complexes page (per city_id)
_complexes_route_cache = {}
_complexes_route_cache_ts = {}
COMPLEXES_ROUTE_CACHE_TIMEOUT = 300  # 5 minutes


def invalidate_complexes_cache():
    """Invalidate all residential complex caches. Call after admin adds/updates/deletes RC or Property."""
    global _properties_cache, _cache_timestamp
    global _complexes_route_cache, _complexes_route_cache_ts
    global _complexes_map_cache, _complexes_map_cache_ts
    _properties_cache = None
    _cache_timestamp = None
    _complexes_route_cache.clear()
    _complexes_route_cache_ts.clear()
    _complexes_map_cache.clear()
    _complexes_map_cache_ts.clear()
    logging.getLogger(__name__).info("✅ Complexes cache invalidated")


def load_properties():
    """✅ MIGRATED TO NORMALIZED TABLES: Load properties from Property → ResidentialComplex → Developer"""
    global _properties_cache, _cache_timestamp
    import time
    
    # Check if we have valid cached data
    if (_properties_cache is not None and _cache_timestamp is not None and 
        time.time() - _cache_timestamp < CACHE_TIMEOUT):
        # Cache hit - fast path
        return _properties_cache
    
    # Ensure we have app context
    from flask import has_app_context
    if not has_app_context():
        with app.app_context():
            return load_properties()
    
    try:
        # ✅ MIGRATED: Load from normalized tables using PropertyRepository
        properties = PropertyRepository.get_all_active(
            limit=500,  # ⚡ OPTIMIZED: Reduced from 10000
            filters={'min_price': 1},  # price > 0
            sort_by='price',
            sort_order='asc'
        )
        
        excel_properties = properties
        
        if excel_properties and len(excel_properties) > 0:
            # ✅ MIGRATED: No need for max_floors query, data is in normalized tables
            
            # Convert Property ORM objects to dictionary format (backward compatibility)
            db_properties = []
            for prop in excel_properties:
                # Convert ORM object to dict-like structure
                # Property has relationships: residential_complex, developer, district
                complex_obj = prop.residential_complex
                developer_obj = prop.developer
                district_obj = prop.district
                
                prop_dict = {
                    'inner_id': prop.inner_id,
                    'complex_name': complex_obj.name if complex_obj else 'ЖК Без названия',
                    'developer_name': developer_obj.name if developer_obj else 'Не указан',
                    'object_rooms': prop.rooms,
                    'object_area': prop.area,
                    'price': prop.price,
                    'object_min_floor': prop.floor,
                    'object_max_floor': prop.total_floors,
                    'address_display_name': prop.address,
                    'address_position_lat': prop.latitude,
                    'address_position_lon': prop.longitude,
                    'address_locality_display_name': district_obj.name if district_obj else '',
                    'photos': prop.gallery_images or '[]',
                    'complex_object_class_display_name': complex_obj.object_class_display_name if complex_obj else '',
                    'renovation_type': prop.renovation_type,
                    'renovation_display_name': PropertyRepository.get_renovation_display_name(prop.renovation_type),
                    'complex_with_renovation': bool(prop.renovation_type),
                    'complex_building_end_build_year': complex_obj.end_build_year if complex_obj else None,
                    'complex_building_end_build_quarter': complex_obj.end_build_quarter if complex_obj else None,
                    'complex_building_name': prop.complex_building_name,
                    'address_subways': None,
                    'trade_in': False,  # Not in Property model yet
                    'deal_type': prop.deal_type,
                    'square_price': prop.price_per_sqm,
                    'mortgage_price': None,  # Not in Property model yet
                    'object_is_apartment': True,
                    'max_price': prop.price,
                    'min_price': prop.price,
                    'complex_has_green_mortgage': False,  # Not in Property model yet
                    'placement_type': '',  # Not in Property model yet
                    'description': prop.description,
                    'parsed_district': district_obj.name if district_obj else '',
                    'parsed_city': 'Краснодар',  # Default city
                    'city_id': prop.city_id,  # Multi-city support
                    'complex_id': prop.complex_id,
                    'complex_min_rate': complex_obj.cashback_rate if complex_obj else 0,
                    'distance_to_center': float(complex_obj.distance_to_center) if complex_obj and complex_obj.distance_to_center else None
                }
                
                # Parse photos field (JSON array format)
                photos_raw = prop_dict.get('photos', '')
                main_image = '/static/images/no-photo.svg'
                
                if photos_raw and photos_raw.strip():
                    try:
                        # Try to parse as JSON array first (current database format)
                        if photos_raw.startswith('[') and photos_raw.endswith(']'):
                            images = json.loads(photos_raw)
                            if images and isinstance(images, list) and len(images) > 0:
                                main_image = images[0].strip() if images[0] else '/static/images/no-photo.svg'
                        # Fallback: PostgreSQL array format {url1,url2,url3}
                        elif photos_raw.startswith('{') and photos_raw.endswith('}'):
                            images_str = photos_raw[1:-1]  # Remove braces
                            if images_str:
                                images = [img.strip().strip('"') for img in images_str.split(',') if img.strip()]
                                main_image = images[0] if images else '/static/images/no-photo.svg'
                        # Single image URL
                        else:
                            main_image = photos_raw.strip()
                    except (json.JSONDecodeError, ValueError, IndexError) as e:
                        print(f"Error parsing photos for property {prop_dict.get('inner_id')}: {e}")
                        main_image = '/static/images/no-photo.svg'
                
                # ✅ MIGRATED: Get total floors directly from Property object (already in normalized tables)
                complex_total_floors = prop_dict.get('object_max_floor', 1)
                
                # Format property data  
                rooms = prop_dict.get('object_rooms', 0)
                area = prop_dict.get('object_area', 0) 
                floor = prop_dict.get('object_min_floor') or '—'
                
                # Format floor display (handle None values)
                if floor != '—' and complex_total_floors and complex_total_floors != 1:
                    floor_display = f"{floor}/{complex_total_floors} эт."
                elif floor != '—':
                    floor_display = f"{floor} эт."
                else:
                    floor_display = "Этаж не указан"
                
                # Create title with proper format: "Студия, 23.40 м², 1/12 эт."
                if rooms == 0:
                    title = f"Студия, {area} м², {floor_display}"
                else:
                    title = f"{rooms}-комн, {area} м², {floor_display}"
                
                # Enhanced completion date from building data
                completion_date = 'Не указана'
                if prop_dict.get('complex_building_end_build_year') and prop_dict.get('complex_building_end_build_quarter'):
                    year = prop_dict.get('complex_building_end_build_year')
                    quarter = prop_dict.get('complex_building_end_build_quarter')
                    completion_date = f"{quarter} кв. {year} г."
                elif prop_dict.get('complex_building_end_build_year'):
                    year = prop_dict.get('complex_building_end_build_year')  
                    completion_date = f"{year} г."
                
                # Enhanced finishing information
                finishing = prop_dict.get('renovation_display_name') or prop_dict.get('renovation_type', 'Не указана')
                if prop_dict.get('complex_with_renovation'):
                    finishing = finishing if finishing != 'Не указана' else 'С отделкой'
                
                formatted_prop = {
                    'id': prop_dict.get('inner_id'),
                    'title': title,
                    'rooms': prop_dict.get('object_rooms', 0),
                    'area': prop_dict.get('object_area', 0),
                    'price': prop_dict.get('price', 0),
                    # Use database square_price if available, fallback to calculation
                    'price_per_sqm': prop_dict.get('square_price') or (int(prop_dict.get('price', 0) / prop_dict.get('object_area', 1)) if prop_dict.get('object_area', 0) > 0 else 0),
                    'floor': prop_dict.get('object_min_floor', 1),
                    'total_floors': complex_total_floors,
                    'address': prop_dict.get('address_display_name', ''),
                    'coordinates': {
                        'lat': float(prop_dict.get('address_position_lat') or 45.0448),
                        'lng': float(prop_dict.get('address_position_lon') or 38.9728)
                    },
                    'cashback': calculate_cashback(
                        prop_dict.get('price', 0),
                        complex_id=prop_dict.get('complex_id'),
                        complex_name=prop_dict.get('complex_name')
                    ),
                    'cashback_rate': float(prop_dict.get('complex_min_rate', 0)) if prop_dict.get('complex_min_rate') else 0,
                    'cashback_available': True,
                    'status': 'available',
                    'property_type': 'Квартира' if prop_dict.get('object_is_apartment', True) else 'Недвижимость',
                    'developer': prop_dict.get('developer_name', 'Не указан'),
                    'residential_complex': prop_dict.get('complex_name', 'ЖК Без названия'),
                    'district': prop_dict.get('parsed_district') or prop_dict.get('parsed_city') or prop_dict.get('address_locality_display_name', 'Район не указан'),
                    'main_image': main_image,
                    'url': f"/object/{prop_dict.get('inner_id')}",
                    'complex_name': prop_dict.get('complex_name', 'ЖК Без названия'),
                    'type': 'property',
                    # NEW ENHANCED FIELDS FROM DATABASE:
                    'finishing': finishing,
                    'renovation_type': prop_dict.get('renovation_type'),
                    'completion_date': completion_date,
                    'complex_class': prop_dict.get('complex_object_class_display_name', ''),
                    'building_name': prop_dict.get('complex_building_name', ''),
                    'nearest_metro': prop_dict.get('address_subways', ''),
                    'trade_in_available': bool(prop_dict.get('trade_in', False)),
                    'deal_type': prop_dict.get('deal_type', ''),
                    'mortgage_price': prop_dict.get('mortgage_price'),
                    'max_price': prop_dict.get('max_price'),
                    'min_price': prop_dict.get('min_price'),
                    'green_mortgage_available': bool(prop_dict.get('complex_has_green_mortgage', False)),
                    'placement_type': prop_dict.get('placement_type', ''),
                    'description': prop_dict.get('description', ''),
                    'complex_with_renovation': bool(prop_dict.get('complex_with_renovation', False))
                }
                db_properties.append(formatted_prop)
            
            # Successfully loaded properties from database
            # Cache the data
            _properties_cache = db_properties  
            _cache_timestamp = time.time()
            return db_properties
            
    except Exception as e:
        # Database error logged  
        print(f"CRITICAL: load_properties() database error: {e}")
        import traceback
        traceback.print_exc()
        pass
        
    # No fallback - only database data from now on
    # No properties found
    return []

def load_residential_complexes():
    """Load residential complexes from database enriched with statistics from excel_properties"""
    try:
        # First try to load from database
        from models import ResidentialComplex, Developer, District
        
        from sqlalchemy.orm import joinedload as _jl
        complexes = ResidentialComplex.query.options(
            _jl(ResidentialComplex.developer),
            _jl(ResidentialComplex.district),
        ).all()
        
        if complexes and len(complexes) > 0:
            # Convert database complexes to dictionary format
            db_complexes = []
            
            # Bulk query for available room types (optimize N+1)
            from collections import defaultdict
            rooms_by_complex = defaultdict(list)
            try:
                from models import Property
                
                # Helper function to convert room number to filter format
                def room_number_to_filter(rooms):
                    if rooms == 0:
                        return "студия"
                    elif rooms == 1:
                        return "1-комн"
                    elif rooms == 2:
                        return "2-комн"
                    elif rooms == 3:
                        return "3-комн"
                    elif rooms and rooms >= 4:
                        return "4+-комн"
                    return None
                
                bulk_rooms_query = db.session.query(
                    Property.complex_id,
                    Property.rooms
                ).filter(
                    Property.complex_id.in_([c.id for c in complexes]),
                    Property.is_active == True,
                    Property.rooms.isnot(None)
                ).distinct().all()
                
                for complex_id, room_number in bulk_rooms_query:
                    room_filter = room_number_to_filter(room_number)
                    if room_filter and room_filter not in rooms_by_complex[complex_id]:
                        rooms_by_complex[complex_id].append(room_filter)
                print(f"✅ Loaded room types for {len(rooms_by_complex)} complexes in bulk")
            except Exception as e:
                print(f"⚠️ Could not load room types in bulk: {e}")
                db.session.rollback()
            
            # FOR LOOP OUTSIDE except - process all complexes
            for complex in complexes:
                try:
                    from models import Property
                    stats_query = (
                        db.session.query(
                            func.min(Property.price).label('min_price'),
                            func.max(Property.price).label('max_price'),
                            func.count(Property.id).label('apartments_count')
                        )
                        .filter(Property.complex_id == complex.id, Property.is_active == True)
                        .first()
                    )
                    
                    min_price = stats_query.min_price if stats_query else None
                    max_price = stats_query.max_price if stats_query else None
                    apartments_count = int(stats_query.apartments_count) if stats_query and stats_query.apartments_count else 0
                    
                    # Use bulk query results
                    available_rooms = rooms_by_complex.get(complex.id, [])
                except Exception as e:
                    print(f"Warning: Could not load stats for complex {complex.id}: {e}")
                    db.session.rollback()  # Rollback failed transaction
                    min_price = None
                    max_price = None
                    apartments_count = 0
                    available_rooms = []
                
                complex_dict = {
                    'id': complex.id,
                    'name': complex.name,
                    'slug': complex.slug,
                    'complex_type': complex.complex_type or 'residential',
                    'district': complex.district.name if complex.district else 'Не указан',
                    'district_id': complex.district_id,
                    'developer': complex.developer.name if complex.developer else 'Не указан',
                    'developer_id': complex.developer_id,
                    'cashback_rate': complex.cashback_rate or 5.0,
                    'cashback_percent': complex.cashback_rate or 5.0,
                    'class': complex.object_class_display_name or 'Комфорт',
                    'description': f'ЖК от застройщика {complex.developer.name if complex.developer else "Не указан"}',
                    'start_year': complex.start_build_year,
                    'completion_year': complex.end_build_year,
                    'quarter': complex.end_build_quarter,
                    'features': {
                        'accreditation': complex.has_accreditation,
                        'green_mortgage': complex.has_green_mortgage,
                        'big_check': complex.has_big_check,
                        'with_renovation': complex.with_renovation,
                        'financing_sber': complex.financing_sber,
                    },
                    'phones': {
                        'complex': complex.complex_phone,
                        'sales': complex.sales_phone,
                    },
                    'sales_address': complex.sales_address,
                    'image': 'https://via.placeholder.com/800x600/0088CC/FFFFFF?text=' + complex.name.replace(' ', '+'),  # Placeholder for now
                    'address': complex.sales_address or 'Адрес уточняется',
                    'location': complex.sales_address or 'Краснодар',  # Add missing location field
                    # Add statistics from excel_properties
                    'min_price': min_price,
                    'available_apartments_count': apartments_count,
                    'total_apartments': apartments_count,
                    # Coordinates
                    'latitude': complex.latitude,
                    'longitude': complex.longitude,
                    'coordinates': {
                        'lat': complex.latitude if complex.latitude else 45.0448,
                        'lng': complex.longitude if complex.longitude else 38.9760
                    },
                    # Images
                    'city_id': complex.city_id,
                    'main_image': complex.main_image,
                    'gallery_images': complex.gallery_images,
                    # Status based on completion dates
                    'status': 'Сдан' if complex.end_build_year and complex.end_build_year <= 2024 else ('Строится' if complex.end_build_year else 'Планируется'),
                    # URL
                    'url': f'/residential-complex/{complex.slug}',
                    # Developer name
                    'developer_name': complex.developer.name if complex.developer else 'Не указан',
            'developer_id': complex.developer.id if complex.developer else None,
            'object_class': complex.object_class_display_name or 'Комфорт',
                    # Additional fields
                    'buildings_count': complex.buildings_count or 1,
                    'price_from': min_price,
                    'max_price': max_price,
                    'price_to': max_price,
                    'apartments_count': apartments_count,
                    'available_rooms': available_rooms,
                    'properties_count': apartments_count,
                }
                db_complexes.append(complex_dict)
            
            # Complexes loaded successfully
            print(f"✅ load_residential_complexes returning {len(db_complexes)} complexes")
            return db_complexes
            
    except Exception as e:
        # Error loading complexes
        print(f"Error in load_residential_complexes: {e}")
        import traceback
        traceback.print_exc()
    
    # No fallback - only database data from now on
    # No complexes found
    return []

def load_blog_articles():
    """Load blog articles from JSON file"""
    try:
        with open('data/blog_articles.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def load_blog_categories():
    """Load blog categories from JSON file"""
    try:
        with open('data/blog_categories.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def load_search_data():
    """Load search data from JSON file"""
    try:
        with open('data/search_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def load_streets():
    """Load streets from JSON file"""
    try:
        with open('data/streets.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def load_developers():
    """Load developers from residential complexes data"""
    try:
        complexes = load_residential_complexes()
        developers = {}
        
        for complex in complexes:
            dev_name = complex.get('developer', 'Неизвестный застройщик')
            if dev_name not in developers:
                developers[dev_name] = {
                    'name': dev_name,
                    'projects_count': 0,
                    'complexes': []
                }
            developers[dev_name]['projects_count'] += 1
            developers[dev_name]['complexes'].append(complex['name'])
        
        return list(developers.values())
    except Exception:
        return []

def search_global(query):
    """Global search across all types: ЖК, districts, developers, streets"""
    if not query or len(query.strip()) < 2:
        return []
    
    search_data = load_search_data()
    results = []
    query_lower = query.lower().strip()
    
    # Search through all categories
    for category in ['residential_complexes', 'districts', 'developers', 'streets']:
        items = search_data.get(category, [])
        for item in items:
            # Search in name and keywords
            name_match = query_lower in item['name'].lower()
            keyword_match = any(query_lower in keyword.lower() for keyword in item.get('keywords', []))
            
            if name_match or keyword_match:
                # Calculate relevance score
                score = 0
                if query_lower in item['name'].lower():
                    score += 10  # Higher score for name matches
                if query_lower == item['name'].lower():
                    score += 20  # Even higher for exact matches
                    
                result = {
                    'id': item['id'],
                    'name': item['name'],
                    'type': item['type'],
                    'url': item['url'],
                    'score': score
                }
                
                # Add additional context based on type
                if item['type'] == 'residential_complex':
                    result['district'] = item.get('district', '')
                    result['developer'] = item.get('developer', '')
                elif item['type'] == 'street':
                    result['district'] = item.get('district', '')
                    
                results.append(result)
    
    # Sort by relevance score (highest first)
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:10]  # Return top 10 results

def get_article_by_slug(slug):
    """Get a single article by slug"""
    articles = load_blog_articles()
    for article in articles:
        if article['slug'] == slug:
            return article
    return None

def search_articles(query, category=None):
    """Search articles by title, excerpt, content, and tags"""
    articles = load_blog_articles()
    if not query and not category:
        return articles
    
    filtered_articles = []
    for article in articles:
        # Filter by category if specified
        if category and article['category'].lower() != category.lower():
            continue
        
        # If no search query, return all articles in category
        if not query:
            filtered_articles.append(article)
            continue
        
        # Search in title, excerpt, content, and tags
        query_lower = query.lower()
        if (query_lower in article['title'].lower() or 
            query_lower in article['excerpt'].lower() or 
            query_lower in article['content'].lower() or 
            any(query_lower in tag.lower() for tag in article['tags'])):
            filtered_articles.append(article)
    
    return filtered_articles

def _extract_first_photo(photos_json):
    """Extract first photo from photos JSON string"""
    if not photos_json:
        return None
    
    try:
        import json
        if isinstance(photos_json, str):
            photos_list = json.loads(photos_json)
        else:
            photos_list = photos_json
            
        return photos_list[0] if photos_list and len(photos_list) > 0 else None
    except:
        return None

def calculate_cashback(price, complex_id=None, complex_name=None):
    """Calculate cashback amount based on property price and complex cashback rate"""
    if not price or price == 0:
        return 0
    
    try:
        from models import ResidentialComplex
        
        # If complex_id provided, use its cashback rate from database (backwards compatibility)
        if complex_id:
            complex_obj = ResidentialComplex.query.filter_by(id=str(complex_id)).first()
            if complex_obj and complex_obj.cashback_rate:
                rate = float(complex_obj.cashback_rate) / 100  # Convert percentage to decimal
                return int(price * rate)
        
        # If complex_name provided, look up by name
        if complex_name:
            complex_obj = ResidentialComplex.query.filter_by(name=complex_name).first()
            if complex_obj and complex_obj.cashback_rate:
                rate = float(complex_obj.cashback_rate) / 100  # Convert percentage to decimal
                return int(price * rate)
    except Exception as e:
        print(f"Error getting complex cashback rate: {e}")
    
    # Fallback to default 5% calculation if no complex found or error
    return int(price * 0.05)  # 5% default cashback

def get_property_by_id(property_id):
    """✅ MIGRATED TO NORMALIZED TABLES: Get property from Property → ResidentialComplex → Developer"""
    try:
        # ✅ MIGRATED: Use PropertyRepository to get property with all relationships
        prop = PropertyRepository.get_by_id(property_id)
        
        if not prop:
            return None
        
        # Extract related objects
        complex_obj = prop.residential_complex
        developer_obj = prop.developer
        district_obj = prop.district
        city_obj = prop.city  # Get city for fallback
        
        # Map to old variable names for backward compatibility
        inner_id = prop.inner_id
        price = prop.price
        area = prop.area
        rooms = prop.rooms
        min_floor = prop.floor
        max_floor = prop.total_floors
        address = prop.address
        renovation = PropertyRepository.get_renovation_display_name(prop.renovation_type)
        cashback_rate = complex_obj.cashback_rate if complex_obj else 0
        square_price = prop.price_per_sqm
        mortgage_price = None  # Not in Property model yet
        class_type = complex_obj.object_class_display_name if complex_obj else None
        photos = prop.gallery_images
        developer_name = developer_obj.name if developer_obj else None
        complex_name = complex_obj.name if complex_obj else None
        complex_end_year = complex_obj.end_build_year if complex_obj else None
        complex_end_quarter = complex_obj.end_build_quarter if complex_obj else None
        building_end_year = complex_obj.end_build_year if complex_obj else None
        building_end_quarter = complex_obj.end_build_quarter if complex_obj else None
        lat = getattr(prop, "latitude", None)
        lon = getattr(prop, "longitude", None)
        description = prop.description
        district_name = district_obj.name if district_obj else None
        
        # Parse photos JSON
        images = []
        floor_plan = None
        complex_photos = []
        
        try:
            if photos:
                photos_data = json.loads(photos)
                if isinstance(photos_data, list):
                    # If it's a simple list of photo URLs (like in this case)
                    images = photos_data
                    # Simple list — photos are gallery images, not floor plans
                    floor_plan = None  # No dedicated floor plan in simple gallery
                elif isinstance(photos_data, dict):
                    # Get apartment gallery photos from dict structure
                    images = photos_data.get('apartment_gallery', [])
                    # Get floor plan 
                    floor_plans = photos_data.get('floor_plans', [])
                    if floor_plans and len(floor_plans) > 0:
                        floor_plan = floor_plans[0]  # Take first floor plan
                    # Get complex photos
                    complex_photos = photos_data.get('complex_gallery', [])
        except Exception as e:
            print(f"Error parsing photos for property {property_id}: {e}")
            pass
        
        # Build completion date
        completion_date = 'Уточняется'
        if building_end_year and building_end_quarter:
            completion_date = f"{building_end_year} г., {building_end_quarter} кв."
        elif building_end_year:
            completion_date = f"{building_end_year} г."
        elif complex_end_year:
            completion_date = f"{complex_end_year} г."
        
        # Create property data structure matching PDF template expectations
        property_data = {
            'id': property_id,  # ✅ Database PK для корректного удаления
            'inner_id': inner_id,  # Внешний ID для справки
            'title': f"{'Студия' if rooms == 0 else f'{rooms}-к. квартира'}, {area} м²",
            'price': price or 0,
            'area': area or 0,
            'rooms': rooms or 0,
            'floor': min_floor or 1,
            'total_floors': max_floor or min_floor or 1,
            'address': address or (complex_obj.address if complex_obj and complex_obj.address else f"{city_obj.name if city_obj else 'Адрес не указан'}"),
            'developer': developer_name or 'Не указан',
            'residential_complex': complex_name or 'Не указан',
            'district': district_name or (city_obj.name if city_obj else 'Не указан'),
            'status': 'Свободна',
            'property_type': 'Студия' if rooms == 0 else 'Квартира',
            'renovation_type': renovation or 'Уточняется',
            'finishing': renovation or 'Предчистовая',
            'completion_date': completion_date,
            'cashback_rate': cashback_rate or 0,
            'mortgage_rate': f"{cashback_rate}%" if cashback_rate else '3.5%',
            'square_price': square_price,
            'mortgage_payment': mortgage_price,
            'class_type': class_type or 'Не указан',
            'description': description or '',
            'residential_complex_description': f"Современный жилой комплекс от застройщика {developer_name}" if developer_name else None,
            'mortgage_available': True,
            'installment_available': False,
            'cashback_available': True,
            # Photos for PDF
            'image': images[0] if images else None,  # Main photo
            'gallery': images,  # All apartment photos
            'floor_plan': floor_plan,  # Floor plan photo
            'layout_image': getattr(prop, 'plan_image', None) or floor_plan,  # For property_detail.html template
            'complex_photos': complex_photos,  # Complex photos
            # Additional fields expected by PDF template + comparison table
            'bathroom_type': getattr(prop, 'bathroom_type', None) or 'Совмещенный',
            'has_balcony': getattr(prop, 'has_balcony', None),
            'windows_type': 'Пластиковые',
            'elevators': '2 пассажирских',
            'parking_type': (complex_obj.parking_type if complex_obj else None) or 'Наземная',
            'developer_inn': 'ИНН не указан',
            'complex_name': complex_name,  # Add complex_name for cashback calculation
            # Rich comparison fields
            'living_area': getattr(prop, 'living_area', None),
            'kitchen_area': getattr(prop, 'kitchen_area', None),
            'building_type': getattr(complex_obj, 'wall_material', None) or getattr(complex_obj, 'building_type', None) or getattr(prop, 'building_type', None),
            'ceiling_height': getattr(complex_obj, 'ceiling_height', None) or getattr(prop, 'ceiling_height', None),
            'main_image': prop.main_image or (images[0] if images else None),
            'price_per_sqm': square_price,
            'renovation_display_name': renovation,
            'object_class_display': class_type,
        }
        
        return property_data
        
    except Exception as e:
        print(f"Error getting property {property_id}: {e}")
        return None

def get_filtered_properties(filters):
    """Filter properties based on criteria including regional filters"""
    properties = load_properties()
    filtered = []
    
    for prop in properties:
        # Keywords filter (для типов недвижимости, классов, материалов)
        if filters.get('keywords') and len(filters['keywords']) > 0:
            keywords_matched = False
            for keyword in filters['keywords']:
                keyword_lower = keyword.lower()
                
                # Check property type
                prop_type_lower = prop.get('property_type', 'Квартира').lower()
                if keyword_lower == 'дом' and prop_type_lower == 'дом':
                    keywords_matched = True
                    break
                elif keyword_lower == 'таунхаус' and prop_type_lower == 'таунхаус':
                    keywords_matched = True
                    break
                elif keyword_lower == 'пентхаус' and prop_type_lower == 'пентхаус':
                    keywords_matched = True
                    break
                elif keyword_lower == 'апартаменты' and prop_type_lower == 'апартаменты':
                    keywords_matched = True
                    break
                elif keyword_lower == 'студия' and (prop_type_lower == 'студия' or prop.get('rooms') == 0):
                    keywords_matched = True
                    break
                elif keyword_lower == 'квартира' and prop_type_lower == 'квартира':
                    keywords_matched = True
                    break
                
                # Check property class
                elif keyword_lower == prop.get('property_class', '').lower():
                    keywords_matched = True
                    break
                
                # Check wall material
                elif keyword_lower in prop.get('wall_material', '').lower():
                    keywords_matched = True
                    break
                
                # Check features
                elif any(keyword_lower in feature.lower() for feature in prop.get('features', [])):
                    keywords_matched = True
                    break
                
                # Check in property type as fallback  
                elif keyword_lower in (f"{prop.get('rooms', 0)}-комн" if prop.get('rooms', 0) > 0 else "студия").lower():
                    keywords_matched = True
                    break
                    
            if not keywords_matched:
                continue
        
        # Text search with improved room number matching and word-based search
        if filters.get('search'):
            search_term = filters['search'].lower()
            
            # Create multiple variations for room descriptions
            rooms = prop.get('rooms', 0)
            if rooms == 0:
                room_variations = ["студия", "studio"]
            else:
                room_variations = [
                    f"{rooms}-комн",
                    f"{rooms}-комнатная",
                    f"{rooms} комн",
                    f"{rooms} комнатная"
                ]
                
                # Add spelled out numbers for 1-3 rooms
                if rooms == 1:
                    room_variations.extend(["однокомнатная", "1-комнатная", "одна комната"])
                elif rooms == 2:
                    room_variations.extend(["двухкомнатная", "2-комнатная", "две комнаты"])
                elif rooms == 3:
                    room_variations.extend(["трехкомнатная", "3-комнатная", "три комнаты"])
            
            # Create searchable text with all variations
            property_title = f"{prop.get('rooms', 0)}-комн" if prop.get('rooms', 0) > 0 else "студия"
            searchable_text = f"{property_title} {' '.join(room_variations)} {prop.get('developer_name', prop.get('developer', ''))} {prop.get('address_locality_name', prop.get('district', ''))} {prop.get('complex_name', prop.get('residential_complex', ''))} {prop.get('location', '')} квартира".lower()
            
            # Split search term into words and check if all words are found
            search_words = search_term.split()
            match_found = True
            
            for word in search_words:
                if word not in searchable_text:
                    match_found = False
                    break
            
            if not match_found:
                continue
        
        # Rooms filter - handle both single value and array
        if filters.get('rooms'):
            rooms_filter = filters['rooms']
            # ✅ ИСПРАВЛЕНО: используем object_rooms вместо rooms
            property_rooms = prop.get('object_rooms', prop.get('rooms', 0))
            
            # Helper function to parse room filter value
            def parse_room_filter(room_value):
                """Convert room filter to integer: '2-комн' -> 2, 'студия' -> 0, '2' -> 2"""
                if not room_value:
                    return None
                room_str = str(room_value).lower().strip()
                
                # Handle special cases
                if room_str in ['студия', 'studio']:
                    return 0
                if room_str in ['4+-комн', '4+', '4+ комнат']:
                    return 4  # Will be handled as >= 4
                
                # Handle "X-комн" format
                if '-комн' in room_str:
                    try:
                        return int(room_str.split('-')[0])
                    except (ValueError, IndexError):
                        return None
                
                # Handle numeric string
                try:
                    return int(room_str)
                except (ValueError, TypeError):
                    return None
            
            # Handle array of rooms from saved searches
            if isinstance(rooms_filter, list):
                rooms_match = False
                for room_filter in rooms_filter:
                    room_num = parse_room_filter(room_filter)
                    if room_num is None:
                        continue
                    
                    # Special case for 4+ rooms
                    if str(room_filter).lower() in ['4+-комн', '4+', '4+ комнат']:
                        if property_rooms >= 4:
                            rooms_match = True
                            break
                    # Exact match
                    elif property_rooms == room_num:
                        rooms_match = True
                        break
                
                if not rooms_match:
                    continue
            else:
                # Handle single room value
                room_num = parse_room_filter(rooms_filter)
                if room_num is None:
                    continue
                    
                # Special case for 4+ rooms
                if str(rooms_filter).lower() in ['4+-комн', '4+', '4+ комнат']:
                    if property_rooms < 4:
                        continue
                # Exact match
                elif property_rooms != room_num:
                    continue
        
        # Price filter - handle both raw rubles and millions
        if filters.get('price_min') and filters['price_min']:
            try:
                min_price = int(filters['price_min'])
                # If value is small, assume it's in millions
                if min_price < 1000:
                    min_price = min_price * 1000000
                if prop['price'] < min_price:
                    continue
            except (ValueError, TypeError):
                pass
        if filters.get('price_max') and filters['price_max']:
            try:
                max_price = int(filters['price_max'])
                # If value is small, assume it's in millions
                if max_price < 1000:
                    max_price = max_price * 1000000
                if prop['price'] > max_price:
                    continue
            except (ValueError, TypeError):
                pass
        
        # District filter
        if filters.get('district') and prop['district'] != filters['district']:
            continue
        
        # Developer filter
        if filters.get('developer') and prop['developer'] != filters['developer']:
            continue
        
        # Residential complex filter
        if filters.get('residential_complex'):
            residential_complex = filters['residential_complex'].lower()
            prop_complex = prop.get('complex_name', '').lower()
            if residential_complex not in prop_complex:
                continue
        
        # Street filter
        if filters.get('street'):
            street = filters['street'].lower()
            prop_location = prop.get('location', '').lower()
            prop_address = prop.get('full_address', '').lower()
            if street not in prop_location and street not in prop_address:
                continue
        
        # Mortgage filter
        if filters.get('mortgage') and not prop.get('mortgage_available', False):
            continue
        
        filtered.append(prop)
    
    return filtered

def build_property_filters(request_args):
    """
    Unified property filtering function for /properties and /map routes.
    
    Args:
        request_args: Flask request.args object
        
    Returns:
        tuple: (where_conditions, params, filters_dict)
            - where_conditions: list of SQL WHERE clause strings
            - params: dict of parameterized values for SQL query
            - filters_dict: dict of parsed filter values for template/debugging
    """
    from datetime import datetime
    
    # Parse all filter parameters (унифицируем названия)
    filters = {}
    
    # Price filters (поддержка всех форматов: price_min, priceFrom, price_from)
    filters['price_min'] = request_args.get('price_min', request_args.get('priceFrom', request_args.get('price_from', '')))
    filters['price_max'] = request_args.get('price_max', request_args.get('priceTo', request_args.get('price_to', '')))
    
    # Price per m² filters (тыс. руб/м²)
    filters['price_sqm_min'] = request_args.get('price_sqm_min', request_args.get('priceSqmFrom', ''))
    filters['price_sqm_max'] = request_args.get('price_sqm_max', request_args.get('priceSqmTo', ''))
    
    # Area filters (поддержка всех форматов)
    filters['area_min'] = request_args.get('area_min', request_args.get('areaFrom', request_args.get('area_from', '')))
    filters['area_max'] = request_args.get('area_max', request_args.get('areaTo', request_args.get('area_to', '')))
    
    # Floor filters (поддержка всех форматов)
    filters['floor_min'] = request_args.get('floor_min', request_args.get('floorFrom', request_args.get('floor_from', '')))
    filters['floor_max'] = request_args.get('floor_max', request_args.get('floorTo', request_args.get('floor_to', '')))
    
    # Rooms filter (может прийти как "1,2,3" или как массив rooms=1&rooms=2 или rooms[]=1)
    # Сначала пробуем getlist для поддержки rooms=1&rooms=2 и rooms[]=1
    rooms_list = request_args.getlist("rooms[]") or request_args.getlist("rooms")
    if rooms_list:
        # Если есть элементы с запятой - разбить их
        all_rooms = []
        for r in rooms_list:
            if isinstance(r, str) and "," in r:
                all_rooms.extend(r.split(","))
            else:
                all_rooms.append(r)
        filters["rooms"] = [str(r).strip() for r in all_rooms if str(r).strip()]
        import logging
        logging.debug(f'DEBUG: Parsed rooms: {filters["rooms"]}')
    else:
        filters["rooms"] = []
    
    # Multi-select filters — accept both singular ?district= and plural ?districts=
    _districts_multi = request_args.getlist('districts') or request_args.getlist('districts[]') or []
    _districts_single = request_args.getlist('district') or []
    _all_d = _districts_multi + [d for d in _districts_single if d not in _districts_multi]
    filters['districts'] = _all_d
    filters['developers'] = request_args.getlist('developers') or request_args.getlist('developers[]') or []
    
    # Support developer_id parameter (single developer by ID)
    developer_id = request_args.get('developer_id', '')
    if developer_id and developer_id not in filters['developers']:
        filters['developers'].append(developer_id)
    filters['completion'] = request_args.getlist('completion') or request_args.getlist('completion[]') or []
    filters['building_types'] = request_args.getlist('building_types') or request_args.getlist('building_types[]') or []
    filters['delivery_years'] = request_args.getlist('delivery_years') or []
    filters['features'] = request_args.getlist('features') or request_args.getlist('features[]') or []
    # Object classes filter (может прийти как список object_classes[]=X&object_classes[]=Y или как "Бизнес,Комфорт")
    object_classes_list = request_args.getlist('object_classes[]') or request_args.getlist('object_classes') or request_args.getlist('object_class')
    if object_classes_list:
        filters['object_classes'] = object_classes_list
    else:
        object_classes_param = request_args.get('object_class', '') or request_args.get('object_classes', '') or request_args.get('object_classes[]', '')
        if object_classes_param:
            filters['object_classes'] = object_classes_param.split(',') if ',' in object_classes_param else [object_classes_param]
        else:
            filters['object_classes'] = []
    filters['renovation'] = request_args.getlist('renovation') or request_args.getlist('renovation[]') or []
    filters['building_released'] = request_args.getlist('building_released') or request_args.getlist('building_released[]') or []
    filters['floor_options'] = request_args.getlist('floor_options') or request_args.getlist('floor_options[]') or []  # not_first, not_last
    
    # Boolean filters
    filters['cashback_only'] = request_args.get('cashback_only', '').lower() in ['true', '1', 'yes']
    
    # Single value filters
    filters['developer'] = request_args.get('developer', '')
    filters['district'] = request_args.get('district', '')
    filters['residential_complex'] = request_args.get('residential_complex', '')
    filters['building'] = request_args.get('building', '')
    
    # Building floors filters
    filters['building_floors_min'] = request_args.get('building_floors_min', request_args.get('maxFloorFrom', ''))
    filters['building_floors_max'] = request_args.get('building_floors_max', request_args.get('maxFloorTo', ''))
    
    # Build year filters
    filters['build_year_min'] = request_args.get('build_year_min', request_args.get('buildYearFrom', ''))
    filters['build_year_max'] = request_args.get('build_year_max', request_args.get('buildYearTo', ''))
    
    # Regional filters
    filters['regions'] = request_args.getlist('regions') or []
    filters['cities'] = request_args.getlist('cities') or []
    filters['city'] = request_args.get('city', '')
    filters['city_id'] = request_args.get('city_id', '')  # Support city_id parameter
    filters['city'] = request_args.get('city', '')
    
    # Search query
    # Property type filter
    filters['property_type'] = request_args.get('property_type', '')
    # Search query (поддержка обоих параметров: 'q' и 'search')
    filters['search'] = request_args.get('q', request_args.get('search', ''))

    # Address-based filters: quarter and street (supports multiple ?street=X&street=Y)
    filters['quarter'] = request_args.get('quarter', '').strip()
    _streets_multi = [s.strip() for s in (request_args.getlist('street') or request_args.getlist('street[]') or []) if s.strip()]
    filters['streets'] = _streets_multi
    filters['street'] = _streets_multi[0] if _streets_multi else request_args.get('street', '').strip()

    # ── Новые фильтры (санузел, балкон, высота потолков, кухня) ──────────
    filters['bathroom_type'] = request_args.getlist('bathroom_type') or request_args.getlist('bathroom_type[]') or []
    filters['has_balcony'] = request_args.getlist('has_balcony') or request_args.getlist('has_balcony[]') or []
    filters['ceiling_height_min'] = request_args.get('ceiling_height_min', '').strip()
    filters['kitchen_area_min'] = request_args.get('kitchen_area_min', '').strip()
    filters['kitchen_area_max'] = request_args.get('kitchen_area_max', '').strip()
    
    # Auto-detect room filters from search queries (for mobile/direct URL access)
    if filters['search']:
        import re
        search_lower = filters['search'].lower().strip()
        
        # Studio patterns: "студия", "studio"
        if re.search(r'\bстуди[яюи]\b', search_lower):
            if '0' not in filters['rooms']:
                filters['rooms'].append('0')
        
        # 1 room patterns: "1 комн", "1комн", "1к", "1-комн", "однокомн"
        if re.search(r'\b1[\s\-]?к(омн(атная|ат)?)?\b|\bодно[\s\-]?комн', search_lower):
            if '1' not in filters['rooms']:
                filters['rooms'].append('1')
        
        # 2 room patterns: "2 комн", "2комн", "2к", "2-комн", "двухкомн"
        if re.search(r'\b2[\s\-]?к(омн(атная|ат)?)?\b|\bдвух[\s\-]?комн', search_lower):
            if '2' not in filters['rooms']:
                filters['rooms'].append('2')
        
        # 3 room patterns: "3 комн", "3комн", "3к", "трехкомн"
        if re.search(r'\b3[\s\-]?к(омн(атная|ат)?)?\b|\bтр[её]х[\s\-]?комн', search_lower):
            if '3' not in filters['rooms']:
                filters['rooms'].append('3')
        
        # 4 room patterns: "4 комн", "4комн", "4к", "четырехкомн"
        if re.search(r'\b4[\s\-]?к(омн(атная|ат)?)?\b|\bчетыр[её]х[\s\-]?комн', search_lower):
            if '4' not in filters['rooms']:
                filters['rooms'].append('4')
    
    # 🔥 FIX: Clear search parameter if it was a pure room query
    # to avoid conflicting text search that returns 0 results
    if filters['rooms'] and filters['search']:
        import re
        search_lower = filters['search'].lower().strip()
        # Patterns for pure room queries (only room number, nothing else)
        room_only_patterns = [
            r'^\s*студи[яюи]\s*$',  # Just "студия"
            r'^\s*\d+[\s\-]?к(омн(атная|ат)?)?\s*$',  # Just "1к", "2 комн", etc.
            r'^\s*(одно|дву[хт]|тр[её]х|четыр[её]х)[\s\-]?комн(атная|ат)?\s*$'  # Just "однокомн", etc.
        ]
        if any(re.search(pattern, search_lower) for pattern in room_only_patterns):
            filters['search'] = ''  # Clear search to avoid text search interference
            print(f"✅ Cleared search parameter after detecting pure room query: '{search_lower}'")
    
    # Build SQL WHERE conditions and parameters
    where_conditions = []
    params = {}
    
    # Price filters (пользователь вводит в миллионах)
    if filters.get('price_min'):
        try:
            params['price_min'] = float(filters['price_min']) * 1000000
            where_conditions.append('price >= :price_min')
        except:
            pass
    
    if filters.get('price_max'):
        try:
            params['price_max'] = float(filters['price_max']) * 1000000
            where_conditions.append('price <= :price_max')
        except:
            pass
    
    # Area filters
    if filters.get('area_min'):
        try:
            params['area_min'] = float(filters['area_min'])
            where_conditions.append('object_area >= :area_min')
        except:
            pass
    
    if filters.get('area_max'):
        try:
            params['area_max'] = float(filters['area_max'])
            where_conditions.append('object_area <= :area_max')
        except:
            pass
    
    # Floor filters
    if filters.get('floor_min'):
        try:
            params['floor_min'] = int(filters['floor_min'])
            where_conditions.append('object_min_floor >= :floor_min')
        except:
            pass
    
    if filters.get('floor_max'):
        try:
            params['floor_max'] = int(filters['floor_max'])
            where_conditions.append('object_min_floor <= :floor_max')
        except:
            pass
    
    # Floor options (не первый/не последний этаж)
    if filters.get('floor_options'):
        floor_option_conditions = []
        for option in filters['floor_options']:
            if option == 'not_first':
                floor_option_conditions.append('object_min_floor > 1')
            elif option == 'not_last':
                # Not on last floor: floor < total_floors
                floor_option_conditions.append('object_min_floor < object_max_floor')
            elif option == 'last':
                # Last floor: floor == total_floors
                floor_option_conditions.append('object_min_floor = object_max_floor')
        
        if floor_option_conditions:
            where_conditions.append(f"({' AND '.join(floor_option_conditions)})")
    
    # Cashback only filter (только объекты с кешбеком)
    if filters.get('cashback_only'):
        where_conditions.append('(min_rate > 0 AND min_rate IS NOT NULL)')
    
    # Rooms filter - support various formats
    if filters.get('rooms'):
        room_conditions = []
        for room_filter in filters['rooms']:
            if isinstance(room_filter, str):
                normalized = room_filter.lower().strip()
                if normalized in ['студия', '0', 'studio']:
                    room_conditions.append('object_rooms = 0')
                elif normalized.endswith('-комн'):
                    try:
                        room_num = int(normalized.split('-')[0])
                        room_conditions.append(f'object_rooms = {room_num}')
                    except:
                        pass
                elif normalized in ['4+', '4+-комн']:
                    room_conditions.append('object_rooms >= 4')
                elif normalized.isdigit():
                    room_conditions.append(f'object_rooms = {int(normalized)}')
        
        if room_conditions:
            where_conditions.append(f"({' OR '.join(room_conditions)})")
    
    # Building types filter (этажность дома)
    if filters.get('building_types'):
        building_conditions = []
        for building_type in filters['building_types']:
            if building_type == 'малоэтажный':
                building_conditions.append('object_max_floor <= 5')
            elif building_type == 'среднеэтажный':
                building_conditions.append('(object_max_floor >= 6 AND object_max_floor <= 12)')
            elif building_type == 'многоэтажный':
                building_conditions.append('object_max_floor >= 13')
        
        if building_conditions:
            where_conditions.append(f"({' OR '.join(building_conditions)})")
    
    # Districts filter (array)
    if filters.get('districts'):
        district_conditions = []
        for idx, district in enumerate(filters['districts']):
            param_name = f'district_{idx}'
            params[param_name] = f'%{district.lower()}%'
            district_conditions.append(f'LOWER(address_locality_name) LIKE :{param_name}')
        
        if district_conditions:
            where_conditions.append(f"({' OR '.join(district_conditions)})")
    
    # Single district filter
    if filters.get('district'):
        params['district'] = f'%{filters["district"].lower()}%'
        where_conditions.append('LOWER(address_locality_name) LIKE :district')
    
    # Developers filter (array)
    if filters.get('developers'):
        developer_conditions = []
        for idx, developer in enumerate(filters['developers']):
            param_name = f'developer_{idx}'
            params[param_name] = f'%{developer.lower()}%'
            developer_conditions.append(f'LOWER(developer_name) LIKE :{param_name}')
        
        if developer_conditions:
            where_conditions.append(f"({' OR '.join(developer_conditions)})")
    
    # Single developer filter
    if filters.get('developer'):
        params['developer'] = f'%{filters["developer"].lower()}%'
        where_conditions.append('LOWER(developer_name) LIKE :developer')
    
    # Residential complex filter
    if filters.get('residential_complex'):
        params['complex'] = f'%{filters["residential_complex"].lower()}%'
        where_conditions.append('LOWER(complex_name) LIKE :complex')
    
    # Building filter
    if filters.get('building'):
        params['building'] = f'%{filters["building"].lower()}%'
        where_conditions.append('LOWER(complex_building_name) LIKE :building')
    
    # Completion year filters
    if filters.get('completion') or filters.get('delivery_years'):
        years = filters.get('completion') or filters.get('delivery_years')
        year_conditions = []
        for year in years:
            if year != 'Сдан':
                try:
                    # Convert string to integer for proper SQL comparison
                    year_int = int(year)
                    year_conditions.append(f'complex_building_end_build_year = {year_int}')
                except (ValueError, TypeError):
                    pass
        
        if year_conditions:
            where_conditions.append(f"({' OR '.join(year_conditions)})")
    
    # Object classes filter
    if filters.get('object_classes'):
        class_conditions = []
        for idx, obj_class in enumerate(filters['object_classes']):
            param_name = f'class_{idx}'
            params[param_name] = f'%{obj_class.lower()}%'
            class_conditions.append(f'LOWER(complex_object_class_display_name) LIKE :{param_name}')
        
        if class_conditions:
            where_conditions.append(f"({' OR '.join(class_conditions)})")
    
    # Renovation filter
    if filters.get('renovation'):
        renovation_conditions = []
        for idx, renovation in enumerate(filters['renovation']):
            param_name = f'renovation_{idx}'
            params[param_name] = f'%{renovation.lower()}%'
            renovation_conditions.append(f'LOWER(renovation_display_name) LIKE :{param_name}')
        
        if renovation_conditions:
            where_conditions.append(f"({' OR '.join(renovation_conditions)})")
    
    # Features filter
    if filters.get('features'):
        feature_conditions = []
        for feature in filters['features']:
            if feature == 'accreditation':
                # Filter by bank accreditation
                feature_conditions.append('complex_has_accreditation = true')
            elif feature == 'green_mortgage':
                # Filter by green mortgage availability
                feature_conditions.append('complex_has_green_mortgage = true')
            else:
                # For other features, search in description
                idx = len(params)
                param_name = f'feature_{idx}'
                params[param_name] = f'%{feature.lower()}%'
                feature_conditions.append(f'LOWER(description) LIKE :{param_name}')
        
        if feature_conditions:
            where_conditions.append(f"({' OR '.join(feature_conditions)})")
    
    # Building released filter (сдан/не сдан)
    if filters.get('building_released'):
        released_conditions = []
        now = datetime.now()
        current_year = now.year
        current_quarter = (now.month - 1) // 3 + 1
        
        for status in filters['building_released']:
            if status.lower() in ['сдан', 'delivered', 'ready']:
                released_conditions.append(f'''(
                    complex_end_build_year < {current_year} OR 
                    (complex_end_build_year = {current_year} AND 
                     (complex_end_build_quarter IS NULL OR complex_end_build_quarter < {current_quarter})) OR
                    complex_building_end_build_year < {current_year} OR
                    (complex_building_end_build_year = {current_year} AND 
                     (complex_building_end_build_quarter IS NULL OR complex_building_end_build_quarter < {current_quarter}))
                )''')
            elif status.lower() in ['строится', 'under_construction', 'building']:
                released_conditions.append(f'''(
                    complex_end_build_year > {current_year} OR
                    (complex_end_build_year = {current_year} AND 
                     (complex_end_build_quarter IS NULL OR complex_end_build_quarter >= {current_quarter})) OR
                    complex_building_end_build_year > {current_year} OR
                    (complex_building_end_build_year = {current_year} AND 
                     (complex_building_end_build_quarter IS NULL OR complex_building_end_build_quarter >= {current_quarter}))
                )''')
        
        if released_conditions:
            where_conditions.append(f"({' OR '.join(released_conditions)})")
    
    # Building floors filters
    if filters.get('building_floors_min'):
        try:
            params['building_floors_min'] = int(filters['building_floors_min'])
            where_conditions.append('object_max_floor >= :building_floors_min')
        except:
            pass
    
    if filters.get('building_floors_max'):
        try:
            params['building_floors_max'] = int(filters['building_floors_max'])
            where_conditions.append('object_max_floor <= :building_floors_max')
        except:
            pass
    
    # Build year filters
    if filters.get('build_year_min'):
        try:
            params['build_year_min'] = int(filters['build_year_min'])
            where_conditions.append('(complex_end_build_year >= :build_year_min OR complex_building_end_build_year >= :build_year_min)')
        except:
            pass
    
    if filters.get('build_year_max'):
        try:
            params['build_year_max'] = int(filters['build_year_max'])
            where_conditions.append('(complex_end_build_year <= :build_year_max OR complex_building_end_build_year <= :build_year_max)')
        except:
            pass
    
    # Regional filters
    regional_conditions = []
    
    if filters.get('regions'):
        for idx, region in enumerate(filters['regions']):
            param_name = f'region_{idx}'
            params[param_name] = f'%{region.lower()}%'
            regional_conditions.append(f'LOWER(address_display_name) LIKE :{param_name}')
    
    if filters.get('region'):
        params['region'] = f'%{filters["region"].lower()}%'
        regional_conditions.append('LOWER(address_display_name) LIKE :region')
    
    # City filtering - use city_id instead of inefficient LIKE on address_display_name
    city_context = resolve_city_context(city_id=filters.get('city_id'), city_slug=filters.get('city'))
    if city_context:
        filters['city_id'] = city_context.id
        filters['city_name'] = city_context.name
        params['city_id'] = city_context.id
        where_conditions.append('city_id = :city_id')
    
    if regional_conditions:
        where_conditions.append(f"({' OR '.join(regional_conditions)})")
    
    # Search filter (multiple fields including address/street)
    if filters.get('search'):
        params['search'] = f'%{filters["search"].lower()}%'
        where_conditions.append('''(
            LOWER(address_display_name) LIKE :search OR
            LOWER(developer_name) LIKE :search OR
            LOWER(complex_name) LIKE :search OR
            LOWER(address_locality_name) LIKE :search OR
            LOWER(complex_building_name) LIKE :search OR
            LOWER(COALESCE(parsed_street, \'\')) LIKE :search OR
            LOWER(COALESCE(address, \'\')) LIKE :search
        )''')
    
    return where_conditions, params, filters

def get_developers_list():
    """⚡ OPTIMIZED: Get list of unique developers from database"""
    from models import Developer
    developers = Developer.query.filter(Developer.name != None, Developer.name != '').all()
    # Deduplicate names using dict, then create dict objects for template
    unique_names = {}
    for d in developers:
        if d.name and d.name not in unique_names:
            unique_names[d.name] = {
                'id': d.id,
                'name': d.name,
                'slug': d.slug if hasattr(d, 'slug') and d.slug else d.name.lower().replace(' ', '-')
            }
    return sorted(unique_names.values(), key=lambda x: x['name'])

def get_districts_list():
    """⚡ OPTIMIZED: Get list of unique districts from database"""
    from models import District
    districts = District.query.filter(District.name != None, District.name != '').all()
    # Deduplicate names using dict, then create dict objects for template
    unique_names = {}
    for d in districts:
        if d.name and d.name not in unique_names:
            unique_names[d.name] = {
                'id': d.id,
                'name': d.name,
                'slug': d.slug if hasattr(d, 'slug') and d.slug else d.name.lower().replace(' ', '-')
            }
    return sorted(unique_names.values(), key=lambda x: x['name'])

def sort_properties(properties, sort_type):
    """Sort properties by specified criteria with None safety"""
    if sort_type == 'price_asc':
        return sorted(properties, key=lambda x: x.get('price') or 0)
    elif sort_type == 'price_desc':
        return sorted(properties, key=lambda x: x.get('price') or 0, reverse=True)
    elif sort_type == 'cashback_desc':
        return sorted(properties, key=lambda x: calculate_cashback(x.get('price') or 0), reverse=True)
    elif sort_type == 'area_asc':
        return sorted(properties, key=lambda x: x.get('area') or 0)
    elif sort_type == 'area_desc':
        return sorted(properties, key=lambda x: x.get('area') or 0, reverse=True)
    else:
        return properties

def get_similar_properties(property_id, district, limit=3):
    """Get similar properties in the same district"""
    properties = load_properties()
    similar = []
    
    for prop in properties:
        if str(prop['id']) != str(property_id) and prop['district'] == district:
            similar.append(prop)
            if len(similar) >= limit:
                break
    
    return similar


# ✅ КРИТИЧНО: Отключаем кэширование HTML для правильной загрузки обновлений
@app.after_request
def add_security_headers(response):
    """Add security and no-cache headers"""
    # HSTS: Force HTTPS for 1 year (31536000 seconds)
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # X-Frame-Options removed to allow Replit preview iframe embedding
    
    # XSS Protection (legacy but still useful for older browsers)
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Referrer policy for privacy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Content Security Policy (basic, can be enhanced later)
    response.headers['Permissions-Policy'] = 'geolocation=(self), microphone=(), camera=(self)'
    
    # No-cache headers for HTML pages to prevent stale content
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

    # ── Универсальная замена ЦИАН-ссылок на прокси (непрозрачный токен) ─────
    # Покрывает: все HTML-страницы (шаблоны) + все JSON API-ответы (карточки)
    # Браузер видит только /api/img-proxy?t=<base64> — домен ЦИАН не виден
    # Отключается через /tmp/image_proxy_disabled (кнопка в админке → Энричмент)
    import os as _os
    if not _os.path.exists('/tmp/image_proxy_disabled'):
        ct = response.content_type or ''
        if ('text/html' in ct or 'application/json' in ct) and not response.direct_passthrough:
            try:
                raw = response.get_data(as_text=True)
                _CIAN_PREFIX = 'https://images.cdn-cian.ru/'
                if _CIAN_PREFIX in raw:
                    import re as _re, base64 as _b64
                    def _encode_cian(m):
                        path = m.group(1)
                        token = _b64.urlsafe_b64encode(path.encode()).decode().rstrip('=')
                        return f'/api/img-proxy?t={token}'
                    raw = _re.sub(
                        r'https://images\.cdn-cian\.ru/([^\s"\'>\)\]\\]+)',
                        _encode_cian, raw
                    )
                    response.set_data(raw)
            except Exception:
                pass

    return response



def manager_required(f):
    """Decorator to require manager authentication"""
    from functools import wraps
    from models import Manager
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_ajax = (request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
                   request.content_type == 'application/json' or
                   request.path.startswith('/api/'))
        if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
            if is_ajax:
                return jsonify({'success': False, 'error': 'Authentication required'}), 401
            return redirect(url_for('mgr.manager_login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to require admin authentication"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from models import Admin
        if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Admin):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Требуется авторизация администратора'}), 403
            return redirect(url_for('adm.admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ── PWA Routes ────────────────────────────────────────────────────────────────
from routes.api import bp as search_geo_bp
app.register_blueprint(search_geo_bp)

# Register City Pages blueprint (/<city_slug>/ipoteka, /about, /contacts, etc.)
from routes.city_pages import bp as city_pages_bp
app.register_blueprint(city_pages_bp)

# Register API blueprint
app.register_blueprint(api_bp)

# Register Main blueprint (wallet, about, contacts, referral, comparison, favorites, thank-you)
from routes.main import main_bp
app.register_blueprint(main_bp)

# Register SEO City blueprint (/<city_slug>/novostrojki-X programmatic SEO pages)
from routes.seo_city import seo_city_bp
app.register_blueprint(seo_city_bp)

# Register Streets blueprint (streets listing and street detail pages)
from routes.streets import streets_bp
app.register_blueprint(streets_bp)

# Register Mortgage blueprint (mortgage/finance redirect pages, sitemap, insurance form)
from routes.mortgage import mortgage_bp
app.register_blueprint(mortgage_bp)

# Register SEO blueprint (sitemap, robots.txt, RSS)
from routes.seo import seo_bp
app.register_blueprint(seo_bp)

# Register PWA blueprint (manifest, sw.js, push notifications)
from routes.pwa import pwa_bp
app.register_blueprint(pwa_bp)

# Register Blog blueprint (blog, news, blog_post, blog_city, etc.)
from routes.blog import blog_bp
app.register_blueprint(blog_bp)

# Register Properties blueprint (legacy redirects, developer detail, PDF)
from routes.properties import props_bp
app.register_blueprint(props_bp)

# Register Manager blueprint (manager portal: login, dashboard, deals, etc.)
from routes.manager import manager_bp
app.register_blueprint(manager_bp)

# Register Admin blueprint (admin panel: /admin/* routes)
from routes.admin import admin_bp
app.register_blueprint(admin_bp)

# Register Partner blueprint (/partner/* routes)
from routes.partner import partner_bp
app.register_blueprint(partner_bp)

# Import push helpers that are still used by chat routes in this file
from push_service import send_chat_push_to_user, send_web_push  # noqa: F401

# Register Social Auth blueprint
from social_auth import social_auth, social_auth_available
app.config['TELEGRAM_BOT_USERNAME'] = os.environ.get('TELEGRAM_BOT_USERNAME', 'InBackBot')
app.register_blueprint(social_auth)

# Register Legal blueprint (privacy, legal, consent, data-processing pages)
from routes.legal import bp as legal_bp
app.register_blueprint(legal_bp)

# Register Auth blueprint (login, register, verify, etc.)
from routes.auth import bp as auth_bp
app.register_blueprint(auth_bp)

# Register Districts blueprint (district listing and detail pages)
from routes.districts import bp as districts_bp
app.register_blueprint(districts_bp)

# Register Applications blueprint (callbacks, bookings, cashback, presentations, docs)
from routes.applications import bp as applications_bp
app.register_blueprint(applications_bp)

# Register Favorites blueprint (user + manager favorites, collections)
from routes.favorites import bp as favorites_bp
app.register_blueprint(favorites_bp)

from routes.developers import devs_bp
app.register_blueprint(devs_bp)

from routes.complexes import complexes_bp
app.register_blueprint(complexes_bp)

from routes.seo_zk import seo_zk_bp
app.register_blueprint(seo_zk_bp)

from routes.deals import deals_bp
app.register_blueprint(deals_bp)

from routes.chat import chat_bp
app.register_blueprint(chat_bp)

from routes.manager_api import mgr_api_bp
app.register_blueprint(mgr_api_bp)

from routes.admin_api import admin_api_bp
app.register_blueprint(admin_api_bp)

from routes.searches import searches_bp
app.register_blueprint(searches_bp)

from routes.presentations import presentations_bp
app.register_blueprint(presentations_bp)

from routes.public_api import public_api_bp
app.register_blueprint(public_api_bp)

from routes.comparison import comparison_bp
app.register_blueprint(comparison_bp)

from routes.jobs import jobs_bp
app.register_blueprint(jobs_bp)

from routes.smart_search_api import smart_search_api_bp
app.register_blueprint(smart_search_api_bp)



@app.context_processor
def inject_social_auth():
    return {'social_auth_available': social_auth_available()}

# Smart Search API Endpoints
def _send_enrich_report_tg(added: int, updated: int, vanished: int, stale: int,
                            mode: str = 'full', error: str = None):
    """Send enrichment + cleanup summary to Telegram admin chat."""
    import re as _re
    import requests as _req
    from datetime import datetime as _dt

    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        logger.warning('⚠️  Telegram report skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set')
        return

    now = _dt.now().strftime('%d.%m.%Y %H:%M')
    total_cleaned = vanished + stale

    if error:
        icon = '❌'
        status_line = f'<b>Обогащение завершилось с ошибкой</b>\n<code>{error[:200]}</code>'
    elif mode == 'prices':
        icon = '⚡'
        status_line = '<b>Обновление цен завершено</b>'
    else:
        icon = '✅'
        status_line = '<b>Полное обогащение завершено</b>'

    lines = [
        f'{icon} <b>InBack — Отчёт обогатителя</b>',
        f'🕒 {now}',
        '',
        status_line,
        '',
        '📥 <b>Добавлено / обновлено:</b>',
        f'   ➕ Новых объектов:    <b>{added:,}</b>',
        f'   🔄 Обновлено цен:     <b>{updated:,}</b>',
    ]

    if mode == 'full':
        lines += [
            '',
            '🧹 <b>Авто-очистка:</b>',
            f'   👻 Пропавших с ЦИАН:      <b>{vanished:,}</b>',
            f'   🕰️ Устаревших (60+ дней): <b>{stale:,}</b>',
            f'   🗑️ Итого деактивировано:  <b>{total_cleaned:,}</b>',
        ]

    message = '\n'.join(lines)
    try:
        _req.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=10
        )
        logger.info('📬 Telegram enrichment report sent')
    except Exception as _e:
        logger.warning(f'⚠️  Telegram report send failed: {_e}')

def _get_city_presets():
    return {str(cid): {'cian_region_id': cfg['cian_region_id'], 'city_id': cid, 'label': cfg['name']}
            for cid, cfg in CITY_CONFIG_ALL.items()}

def _load_enrich_settings():
    defaults = {
        'city_preset': 'krasnodar',
        'total_pages': 15, 'cian_region_id': 4820, 'city_id': 1,
        'request_delay': 0.5, 'schedule_hour': 2, 'schedule_minute': 0,
        'schedule_day_of_week': 6,
        'schedule_days': [6],
        'proxy_url': '',
        'proxy_rotate_seconds': 270,
        'anticaptcha_key': '',
        'use_vpn': False,
        'create_new_jk': True, 'reset_on_run': True,
    }
    try:
        if os.path.exists(ENRICH_SETTINGS_FILE):
            with open(ENRICH_SETTINGS_FILE) as f:
                s = json.load(f)
            defaults.update(s)
    except Exception:
        pass
    return defaults

def _save_enrich_settings(data):
    preset = str(data.get('city_preset', '1'))
    presets = _get_city_presets()
    city_info = presets.get(preset, presets.get('1', {'cian_region_id': 4820, 'city_id': 1}))
    typed = {
        'city_preset': preset,
        'total_pages': int(data.get('total_pages', 15)),
        'cian_region_id': city_info['cian_region_id'],
        'city_id': city_info['city_id'],
        'request_delay': float(data.get('request_delay', 0.5)),
        'schedule_hour': int(data.get('schedule_hour', 2)),
        'schedule_minute': int(data.get('schedule_minute', 0)),
        'schedule_day_of_week': int(data.get('schedule_day_of_week', 6)),
        'schedule_days': [int(d) for d in (data.get('schedule_days') or [data.get('schedule_day_of_week', 6)]) if str(d).isdigit()],
        'proxy_url': str(data.get('proxy_url', '')).strip(),
        'proxy_rotate_seconds': int(data.get('proxy_rotate_seconds', 270)),
        'anticaptcha_key': str(data.get('anticaptcha_key', '')).strip(),
        'use_vpn': bool(data.get('use_vpn', False)),
        'create_new_jk': bool(data.get('create_new_jk', True)),
        'reset_on_run': bool(data.get('reset_on_run', True)),
    }
    with open(ENRICH_SETTINGS_FILE, 'w') as f:
        json.dump(typed, f, ensure_ascii=False, indent=2)
    return typed

def _enrich_cache_info():
    try:
        if os.path.exists(ENRICH_CACHE_FILE):
            with open(ENRICH_CACHE_FILE) as f:
                c = json.load(f)
            jk_total = len(c.get('jk_search_data', {}))
            jk_done  = len(c.get('jk_apts_fetched', []))
            return {
                'phase': c.get('phase', 0),
                'jk_count': jk_total,
                'jk_done':  jk_done,
                'jk_urls': len(c.get('unique_jk_urls', {})),
                'dev_pages': len(c.get('dev_page_cache', {})),
                'apt_count': len(c.get('apt_data', {})),
            }
    except Exception:
        pass
    return {'phase': 0, 'jk_count': 0, 'jk_urls': 0, 'dev_pages': 0}

def _enrich_is_running():
    global _enrich_proc
    if _enrich_proc is not None and _enrich_proc.poll() is None:
        return True
    # Also check by pid file
    pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts', '.enrich_pid')
    try:
        if os.path.exists(pid_file):
            with open(pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
    except Exception:
        pass
    return False

def _load_city_config_all():
    """Load city config from city_config.json — single source of truth."""
    import json as _j
    _cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts', 'city_config.json')
    try:
        with open(_cfg_path, encoding='utf-8') as _f:
            _raw = _j.load(_f)
        return {
            int(k): {
                'name':           v.get('name', f'City {k}'),
                'cian_region_id': v.get('cian_region_id', 0),
                'total_pages':    v.get('total_pages', 30),
                'slug':           v.get('slug', ''),
                'lat':            v.get('lat', 0),
                'lon':            v.get('lon', 0),
            }
            for k, v in _raw.items()
        }
    except Exception:
        # Fallback to minimal hardcoded list if file is missing
        return {
            1: {'name': 'Краснодар',    'cian_region_id': 4820, 'total_pages': 54, 'slug': 'krasnodar'},
            2: {'name': 'Сочи',         'cian_region_id': 4998, 'total_pages': 40, 'slug': 'sochi'},
        }

CITY_CONFIG_ALL = _load_city_config_all()

def _city_log_file(city_id):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts', f'.city_{city_id}.log')

def _city_is_running(city_id):
    global _city_procs
    proc = _city_procs.get(city_id)
    if proc is None:
        return False
    return proc.poll() is None


def _nashdom_is_running(city_id):
    import subprocess
    try:
        out = subprocess.check_output(
            ['pgrep', '-f', f'nashdom_scraper.py.*--city.*{city_id}'],
            stderr=subprocess.DEVNULL
        )
        return bool(out.strip())
    except Exception:
        return False


def get_or_create_region(region_name):
    """Получить или создать регион в базе данных"""
    if not region_name:
        return None
        
    from models import Region
    
    # Ищем существующий регион
    region = Region.query.filter_by(name=region_name).first()
    
    if not region:
        # Создаем новый регион
        slug = region_name.lower().replace(' ', '-').replace('ский', '').replace('край', 'krai')
        region = Region(
            name=region_name,
            slug=slug,
            is_active=True,
            is_default=(region_name == 'Краснодарский край')  # Краснодарский край по умолчанию
        )
        db.session.add(region)
        try:
            db.session.commit()
            print(f"Created new region: {region_name}")
        except Exception as e:
            db.session.rollback()
            print(f"Error creating region {region_name}: {e}")
            return None
    
    return region

def get_or_create_city(city_name, region):
    """Получить или создать город в регионе"""
    if not city_name or not region:
        return None
        
    from models import City
    
    # Ищем существующий город в этом регионе
    city = City.query.filter_by(name=city_name, region_id=region.id).first()
    
    if not city:
        # Создаем новый город
        slug = city_name.lower().replace(' ', '-')
        city = City(
            name=city_name,
            slug=slug,
            region_id=region.id,
            is_active=True,
            is_default=(city_name == 'Краснодар')  # Краснодар по умолчанию
        )
        db.session.add(city)
        try:
            db.session.commit()
            print(f"Created new city: {city_name} in {region.name}")
        except Exception as e:
            db.session.rollback()
            print(f"Error creating city {city_name}: {e}")
            return None
    
    return city

def update_properties_with_regions():
    """Обновить все объекты недвижимости с региональной привязкой"""
    
    # ✅ MIGRATED: Use normalized Property model
    properties = Property.query.all()
    updated_count = 0
    
    print(f"Updating {len(properties)} properties with regional data...")
    
    for prop in properties:
        if prop.address_display_name:
            # Парсим адрес
            address_parts = parse_address_components(prop.address_display_name)
            
            # Обновляем парсеные поля
            prop.parsed_region = address_parts['region']
            prop.parsed_city = address_parts['city'] 
            prop.parsed_district = address_parts['district']
            
            # Создаем/находим регион и город
            if address_parts['region']:
                region = get_or_create_region(address_parts['region'])
                if region:
                    prop.region_id = region.id
                    
                    if address_parts['city']:
                        city = get_or_create_city(address_parts['city'], region)
                        if city:
                            prop.city_id = city.id
            
            updated_count += 1
            
            # Сохраняем по частям для избежания таймаутов
            if updated_count % 50 == 0:
                try:
                    db.session.commit()
                    print(f"Updated {updated_count} properties...")
                except Exception as e:
                    print(f"Error committing batch: {str(e)}")
                    db.session.rollback()
    
    # Финальный коммит
    try:
        db.session.commit()
        print(f"✅ Successfully updated {updated_count} properties with regional data")
    except Exception as e:
        print(f"Error in final commit: {str(e)}")
        db.session.rollback()
    
    return updated_count


# ==================== VIDEO MANAGEMENT API ====================
@app.context_processor
def inject_chat_widget_settings():
    """Provide chat widget settings to all templates."""
    try:
        from models import ChatSettings
        return {'chat_widget': {
            'chat_enabled': ChatSettings.get('chat_enabled', 'true'),
            'response_time': ChatSettings.get('response_time', 'в течение 5 минут'),
            'proactive_message': ChatSettings.get('proactive_message', 'Привет! 👋 Есть вопросы по недвижимости?'),
            'trigger_delay': ChatSettings.get('trigger_delay', '15'),
            'exit_intent': ChatSettings.get('exit_intent', 'true'),
            'offline_form': ChatSettings.get('offline_form', 'true'),
            'telegram_url': ChatSettings.get('telegram_url', ''),
            'whatsapp_url': ChatSettings.get('whatsapp_url', ''),
            'vk_url': ChatSettings.get('vk_url', ''),
            'phone_url': ChatSettings.get('phone_url', ''),
            'chat_phone': ChatSettings.get('chat_phone', '8 (862) 266-62-16'),
            'work_hours_start': ChatSettings.get('work_hours_start', '09:00'),
            'work_hours_end': ChatSettings.get('work_hours_end', '20:00'),
            'work_days': ChatSettings.get('work_days', '1,2,3,4,5,6,7'),
            'sound_enabled': ChatSettings.get('sound_enabled', 'true'),
            'auto_open_delay': ChatSettings.get('auto_open_delay', '0'),
            'welcome_message': ChatSettings.get('welcome_message', ''),
            'offline_message': ChatSettings.get('offline_message', ''),
        }}
    except Exception:
        return {'chat_widget': {
            'chat_enabled': 'true', 'response_time': 'в течение 5 минут',
            'proactive_message': 'Привет! 👋 Есть вопросы по недвижимости?',
            'trigger_delay': '15', 'exit_intent': 'true', 'offline_form': 'true',
            'telegram_url': '', 'whatsapp_url': '', 'vk_url': '', 'phone_url': '',
            'chat_phone': '8 (862) 266-62-16', 'work_hours_start': '09:00',
            'work_hours_end': '20:00', 'work_days': '1,2,3,4,5,6,7',
            'sound_enabled': 'true', 'auto_open_delay': '0',
            'welcome_message': '', 'offline_message': '',
        }}


@app.context_processor
def inject_promo_banner():
    try:
        from models import PromoBanner
        banner = PromoBanner.query.filter_by(is_active=True, placement='header').order_by(PromoBanner.sort_order).first()
        listing_banners = PromoBanner.query.filter_by(is_active=True, placement='listing').order_by(PromoBanner.sort_order).all()
        return {'active_banner': banner, 'listing_banners': listing_banners}
    except Exception:
        return {'active_banner': None, 'listing_banners': []}

