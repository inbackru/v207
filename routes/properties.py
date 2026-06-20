"""
Properties Blueprint — property listing, detail, and redirect routes.

Endpoints: props.properties, props.property_detail, props.properties_city,
           props.property_detail_city, props.residential_complex_detail,
           props.developer_detail, props.property_pdf.
"""
import base64
import io
import json
import os
from datetime import datetime
from types import SimpleNamespace

import requests
from flask import (Blueprint, flash, make_response, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user
from PIL import Image

from app import db
from sqlalchemy import text
from models import ChatSettings

props_bp = Blueprint('props', __name__)


# ─── Lazy helpers ─────────────────────────────────────────────────────────────

def _resolve_property_by_identifier(identifier):
    from app import resolve_property_by_identifier
    return resolve_property_by_identifier(identifier)

def _get_city_slug_for_resource(*args, **kwargs):
    from app import get_city_slug_for_resource
    return get_city_slug_for_resource(*args, **kwargs)

def _get_redirect_city_slug():
    from app import get_redirect_city_slug
    return get_redirect_city_slug()

def _create_slug(name):
    from app import create_slug
    return create_slug(name)

def _resolve_city_context(**kwargs):
    from app import resolve_city_context
    return resolve_city_context(**kwargs)

def _calculate_cashback(*args, **kwargs):
    from app import calculate_cashback
    return calculate_cashback(*args, **kwargs)

def _get_property_by_id(pid):
    from app import get_property_by_id
    return get_property_by_id(pid)

def _load_residential_complexes():
    from app import load_residential_complexes
    return load_residential_complexes()

def _parse_plan_images_from_complex(rc):
    from routes.public_api import _parse_plan_images_from_complex as _fn
    return _fn(rc)

def _parse_nearby_places(nearby_json):
    from routes.public_api import _parse_nearby_places as _fn
    return _fn(nearby_json)

def _parse_nashdom_photos(complex_obj):
    from routes.public_api import _parse_nashdom_photos as _fn
    return _fn(complex_obj)

def _build_property_filters(request_args):
    from app import build_property_filters
    return build_property_filters(request_args)

def _get_canonical_base_url():
    from app import CANONICAL_BASE_URL
    return CANONICAL_BASE_URL

def _detect_city_from_query(query):
    from smart_search import smart_search as _sm
    return _sm.detect_city_from_query(query)


# ─── Legacy redirect routes ───────────────────────────────────────────────────

@props_bp.route('/novostrojki')
@props_bp.route('/kvartiry')
@props_bp.route('/properties')
def properties():
    """Legacy route — redirects to city-based URL"""
    from app import redirect_to_city_based
    return redirect_to_city_based('properties_city')


@props_bp.route('/property/<property_id>')
@props_bp.route('/object/<property_id>')
def property_detail(property_id):
    """Legacy route — redirects to city-based URL (supports inner_id and database ID)"""
    property_obj, resolved_id = _resolve_property_by_identifier(property_id)
    if property_obj:
        db_id = property_obj.id
    else:
        try:
            db_id = int(property_id)
        except (ValueError, TypeError):
            db_id = None

    city_slug = _get_city_slug_for_resource('property', resource_id=db_id) if db_id else None
    if not city_slug:
        city_slug = _get_redirect_city_slug()

    return redirect(
        url_for('props.property_detail_city', city_slug=city_slug,
                property_id=db_id or property_id),
        code=301,
    )


@props_bp.route('/residential_complex/<int:complex_id>')
@props_bp.route('/residential-complex/<int:complex_id>')
@props_bp.route('/residential-complex/<complex_name>')
@props_bp.route('/zk/<slug>')
def residential_complex_detail(complex_id=None, complex_name=None, slug=None):
    """Legacy route — redirects to city-based URL"""
    from models import ResidentialComplex
    from urllib.parse import unquote

    city_slug = None
    complex_slug = slug

    if complex_id:
        complex_obj = ResidentialComplex.query.get(complex_id)
        if complex_obj:
            city_slug = complex_obj.city.slug if complex_obj.city else None
            complex_slug = complex_obj.slug
    elif slug:
        city_slug = _get_city_slug_for_resource('complex', slug=slug)
    elif complex_name:
        decoded_name = unquote(complex_name)
        complex_obj = ResidentialComplex.query.filter(
            ResidentialComplex.name.ilike(decoded_name)
        ).first()
        if not complex_obj:
            generated_slug = _create_slug(decoded_name)
            complex_obj = ResidentialComplex.query.filter_by(slug=generated_slug).first()
        if not complex_obj:
            complex_obj = ResidentialComplex.query.filter(
                ResidentialComplex.name.ilike(f'%{decoded_name}%')
            ).first()
        if complex_obj:
            city_slug = complex_obj.city.slug if complex_obj.city else None
            complex_slug = complex_obj.slug or _create_slug(complex_obj.name)

    if not city_slug:
        city_slug = _get_redirect_city_slug()

    if not complex_slug:
        return redirect(url_for('complexes.residential_complexes_city', city_slug=city_slug), code=302)

    return redirect(
        url_for('complexes.residential_complex_by_slug_city', city_slug=city_slug, slug=complex_slug),
        code=301,
    )


# ─── Developer detail ─────────────────────────────────────────────────────────

@props_bp.route('/developer/<int:developer_id>')
def developer_detail(developer_id):
    """Individual developer page"""
    from models import Property

    current_city = _resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )

    try:
        with open('data/developers.json', 'r', encoding='utf-8') as f:
            developers_data = json.load(f)

        developer = next((d for d in developers_data if d['id'] == developer_id), None)
        if not developer:
            return "Застройщик не найден", 404

        for key, default in [
            ('total_apartments_sold', 150), ('projects_completed', 8),
            ('years_experience', 10), ('rating', 4.5),
            ('construction_technology', 'Монолитно-каркасная'),
            ('warranty_years', 5),
            ('advantages', ['Качественное строительство', 'Соблюдение сроков сдачи',
                            'Развитая инфраструктура', 'Выгодные условия покупки']),
        ]:
            developer.setdefault(key, default)

        complexes = _load_residential_complexes()
        developer_complexes = [
            c for c in complexes
            if c.get('developer_id') == developer_id or c.get('developer') == developer['name']
        ]

        developer_properties = Property.query.filter_by(developer_id=developer_id).limit(100).all()
        developer_properties = [
            {
                'inner_id': p.inner_id, 'price': p.price, 'area': p.area,
                'rooms': p.rooms, 'floor': p.floor, 'total_floors': p.total_floors,
                'address': p.address, 'developer': developer['name'],
            }
            for p in developer_properties
        ]

        return render_template('developer_detail.html',
                               developer=developer,
                               complexes=developer_complexes,
                               properties=developer_properties)
    except Exception as e:
        import traceback; traceback.print_exc()
        return f"Error 500: {str(e)}", 500


# ─── PDF helpers ──────────────────────────────────────────────────────────────

def _crop_watermark(image_url, crop_bottom_percent=8):
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content))
        width, height = img.size
        crop_height = int(height * (crop_bottom_percent / 100))
        return img.crop((0, 0, width, height - crop_height))
    except Exception as e:
        print(f"Error cropping watermark from {image_url}: {e}")
        return None


def _generate_qr_code(url):
    try:
        import qrcode
        qr = qrcode.QRCode(version=1,
                           error_correction=qrcode.constants.ERROR_CORRECT_L,
                           box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        qr_image.save(buf, format='PNG')
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"Error generating QR code: {e}")
        return None


# ─── PDF routes ───────────────────────────────────────────────────────────────

@props_bp.route('/object/<property_id>/pdf')
def property_pdf(property_id):
    """Property PDF card page with QR code"""
    from models import ResidentialComplex, City

    property_obj, resolved_id = _resolve_property_by_identifier(property_id)
    property_data = _get_property_by_id(property_obj.id) if property_obj else None

    if not property_data:
        return redirect(url_for('props.properties'))

    cashback = _calculate_cashback(property_data['price'],
                                   complex_name=property_data.get('complex_name'))
    property_data['cashback_amount'] = cashback

    try:
        if property_data.get('complex_name'):
            rc = ResidentialComplex.query.filter_by(name=property_data['complex_name']).first()
            property_data['cashback_percent'] = float(rc.cashback_rate) if rc and rc.cashback_rate else 5.0
        else:
            property_data['cashback_percent'] = 5.0
    except Exception:
        property_data['cashback_percent'] = 5.0

    current_date = datetime.now().strftime('%d.%m.%Y')

    custom_domain = os.environ.get('QR_DOMAIN')
    if custom_domain:
        custom_domain = custom_domain.rstrip('/')
        if not custom_domain.startswith(('http://', 'https://')):
            custom_domain = 'https://' + custom_domain
        object_url = custom_domain + url_for('props.property_detail', property_id=property_id)
    else:
        object_url = request.url_root.rstrip('/') + url_for('props.property_detail', property_id=property_id)

    qr_code_base64 = _generate_qr_code(object_url)
    property_data['name'] = property_data.get('title', 'Объект недвижимости')

    complex_layout_image = None
    try:
        if property_data.get('complex_name'):
            rc = ResidentialComplex.query.filter_by(name=property_data['complex_name']).first()
            if rc and rc.gallery_images:
                gallery = json.loads(rc.gallery_images)
                if gallery and isinstance(gallery, list):
                    complex_layout_image = gallery[0]
    except Exception:
        pass

    _pdf_plan = (property_data.get('layout_image')
                 or property_data.get('floor_plan_image')
                 or property_data.get('floor_plan')
                 or property_data.get('main_image'))
    if not _pdf_plan and property_data.get('complex_name'):
        try:
            rc = ResidentialComplex.query.filter_by(name=property_data['complex_name']).first()
            if rc:
                plan_imgs = _parse_plan_images_from_complex(rc)
                if plan_imgs:
                    _pdf_plan = plan_imgs[0]
        except Exception:
            pass

    property_images = {
        'photos': property_data.get('gallery', []),
        'floor_plan': _pdf_plan,
    }

    city_obj = None
    if property_data.get('city_id'):
        city_obj = City.query.get(property_data['city_id'])
    elif property_data.get('city_slug'):
        city_obj = City.query.filter_by(slug=property_data['city_slug']).first()

    return render_template('property_pdf.html',
                           property=property_data,
                           property_images=property_images,
                           presentation={'title': 'InBack.ru - Кэшбек при покупке недвижимости'},
                           cashback=cashback,
                           current_date=current_date,
                           qr_code=qr_code_base64,
                           object_url=object_url,
                           complex_layout_image=complex_layout_image,
                           current_city=city_obj)


def _fetch_image_as_b64(url: str, timeout: int = 10) -> str | None:
    """Fetch an external image URL and return it as a base64 string, or None on failure."""
    import base64
    if not url:
        return None
    try:
        import requests as _req
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.cian.ru/',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        }
        resp = _req.get(url, headers=headers, timeout=timeout, verify=False, stream=False)
        if resp.status_code == 200 and len(resp.content) > 500:
            return base64.b64encode(resp.content).decode('ascii')
        return None
    except Exception:
        return None


@props_bp.route('/object/<property_id>/pdf/download')
def property_pdf_download(property_id):
    """Generate and download property PDF using WeasyPrint with base64 images."""
    import logging
    import weasyprint
    from flask import make_response
    from models import Property, ResidentialComplex, City
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        prop = Property.query.filter(
            (Property.id == property_id) | (Property.inner_id == property_id)
        ).first()
        if not prop:
            return "Property not found", 404

        actual_id = str(prop.id)

        # ── Reuse the same data-building logic as the PDF view ──────────────
        property_data = _get_property_by_id(prop.id)
        if not property_data:
            return "Property not found", 404

        cashback = _calculate_cashback(property_data['price'],
                                       complex_name=property_data.get('complex_name'))
        property_data['cashback_amount'] = cashback
        try:
            if property_data.get('complex_name'):
                rc = ResidentialComplex.query.filter_by(name=property_data['complex_name']).first()
                property_data['cashback_percent'] = float(rc.cashback_rate) if rc and rc.cashback_rate else 5.0
            else:
                property_data['cashback_percent'] = 5.0
        except Exception:
            property_data['cashback_percent'] = 5.0

        current_date = datetime.now().strftime('%d.%m.%Y')

        custom_domain = os.environ.get('QR_DOMAIN')
        if custom_domain:
            custom_domain = custom_domain.rstrip('/')
            if not custom_domain.startswith(('http://', 'https://')):
                custom_domain = 'https://' + custom_domain
            object_url = custom_domain + url_for('props.property_detail', property_id=property_id)
        else:
            object_url = 'https://inback.ru' + url_for('props.property_detail', property_id=property_id)

        qr_code_base64 = _generate_qr_code(object_url)

        # ── Collect image URLs ───────────────────────────────────────────────
        gallery_urls = list(property_data.get('gallery') or [])
        if property_data.get('image') and property_data['image'] not in gallery_urls:
            gallery_urls.insert(0, property_data['image'])

        _pdf_plan_url = (property_data.get('layout_image')
                         or property_data.get('floor_plan_image')
                         or property_data.get('floor_plan'))
        if not _pdf_plan_url and property_data.get('complex_name'):
            try:
                rc = ResidentialComplex.query.filter_by(name=property_data['complex_name']).first()
                if rc:
                    plan_imgs = _parse_plan_images_from_complex(rc)
                    if plan_imgs:
                        _pdf_plan_url = plan_imgs[0]
            except Exception:
                pass

        # ── Parallel image fetch, capped at 7 photos + plan ────────────────
        # Limit to 7 gallery photos: 4 for hero grid + 3 for gallery section
        all_urls = gallery_urls[:7]
        plan_url = _pdf_plan_url

        images_b64 = []
        plan_b64 = None

        from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed
        fetch_jobs = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            for i, u in enumerate(all_urls):
                fetch_jobs[pool.submit(_fetch_image_as_b64, u)] = ('gallery', i)
            if plan_url:
                fetch_jobs[pool.submit(_fetch_image_as_b64, plan_url)] = ('plan', 0)

            gallery_results = {}
            for future in _as_completed(fetch_jobs, timeout=20):
                kind, idx = fetch_jobs[future]
                try:
                    result = future.result()
                except Exception:
                    result = None
                if kind == 'gallery':
                    gallery_results[idx] = result
                else:
                    plan_b64 = result

        for i in range(len(all_urls)):
            b64 = gallery_results.get(i)
            if b64:
                images_b64.append(b64)

        city_obj = None
        if property_data.get('city_id'):
            city_obj = City.query.get(property_data['city_id'])

        # ── Render the WeasyPrint-optimised template ─────────────────────────
        rendered_html = render_template(
            'property_pdf_print.html',
            property=property_data,
            images_b64=images_b64,
            plan_b64=plan_b64,
            current_date=current_date,
            qr_code=qr_code_base64,
            object_url=object_url,
            current_city=city_obj,
        )

        pdf_bytes = weasyprint.HTML(string=rendered_html).write_pdf()

        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = (
            f'attachment; filename=InBack_Property_{actual_id}.pdf'
        )
        return response
    except Exception as e:
        import traceback; traceback.print_exc()
        return f"Error generating PDF: {str(e)}", 500


# ─── City-based property listing ───────────────────────────────────────────
@props_bp.route('/<city_slug>/novostrojki')
@props_bp.route('/<city_slug>/kvartiry')
def properties_city(city_slug):
    """City-based properties listing page - SEO-friendly URL version"""
    # Resolve city context using city_slug from URL
    current_city = _resolve_city_context(city_slug=city_slug)
    
    # If city not found, redirect to default properties page
    if not current_city:
        flash('Город не найден. Показываем результаты для Краснодара.', 'warning')
        return redirect(url_for('props.properties'))
    
    # ✅ АВТОМАТИЧЕСКОЕ ПЕРЕКЛЮЧЕНИЕ ГОРОДА при поиске (как Avito/Cian)
    search_query = request.args.get('search', '').strip()
    if search_query:
        detected_city = _detect_city_from_query(search_query)
        if detected_city and detected_city['slug'] != city_slug:
            # Город в запросе отличается от города в URL - переключаем автоматически!
            print(f"🔄 Автопереключение: {city_slug} -> {detected_city['slug']} (search: {search_query})")
            # Убираем параметр search из редиректа - пользователь уже на странице нужного города
            redirect_args = {k: v for k, v in request.args.items() if k != 'search'}
            return redirect(url_for('props.properties_city', city_slug=detected_city['slug'], **redirect_args))
    
    
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
        import json
        from repositories.property_repository import PropertyRepository, ResidentialComplexRepository, DeveloperRepository
        from models import Developer, ResidentialComplex, Property
        from services.dadata_client import DaDataClient
        
        # Parse filters using existing function
        _, _, filters = _build_property_filters(request.args)
        print(f"🔍 DEBUG: URL параметры: {dict(request.args)}")
        print(f"🔍 DEBUG: Распарсенные фильтры: {filters}")

        # Map delivery_years SEO param → completion filter (alias for year-based SEO pages)
        _dyvars = request.args.getlist('delivery_years') or request.args.getlist('delivery_years[]')
        if _dyvars:
            _existing_completion = filters.get('completion') or []
            if isinstance(_existing_completion, str):
                _existing_completion = [_existing_completion]
            filters['completion'] = list(_existing_completion) + [str(y) for y in _dyvars]
            print(f"🗓️ delivery_years→completion merged: {filters['completion']}")

        # Handle complex_id parameter (links from ЖК detail page: ?complex_id=312&rooms=2)
        complex_id_from_url = request.args.get('complex_id')
        if complex_id_from_url and not filters.get('residential_complex'):
            try:
                from models import ResidentialComplex as _RCModel
                _rc = db.session.get(_RCModel, int(complex_id_from_url))
                if _rc:
                    filters['residential_complex'] = _rc.name
                    print(f"✅ complex_id={complex_id_from_url} → residential_complex='{_rc.name}'")
            except Exception as _e:
                print(f"⚠️ complex_id lookup failed: {_e}")
        
        # Pagination
        page = request.args.get('page', default=1, type=int)
        page = max(1, page)
        per_page = 20
        offset = (page - 1) * per_page
        
        # Sorting — empty / omitted = relevance (diverse results across different complexes)
        sort_type = request.args.get('sort', '').replace('_', '-')
        
        # Convert filters to Repository format
        repo_filters = {}
        if filters.get('price_min'):
            try:
                price_val = float(filters['price_min'])
                repo_filters['min_price'] = int(price_val * 1000000) if price_val < 1000 else int(price_val)
            except:
                pass
        if filters.get('price_max'):
            try:
                price_val = float(filters['price_max'])
                repo_filters['max_price'] = int(price_val * 1000000) if price_val < 1000 else int(price_val)
            except:
                pass
        if filters.get('price_sqm_min'):
            try:
                repo_filters['min_price_sqm'] = int(float(filters['price_sqm_min']))
            except:
                pass
        if filters.get('price_sqm_max'):
            try:
                repo_filters['max_price_sqm'] = int(float(filters['price_sqm_max']))
            except:
                pass
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
        if filters.get('rooms'):
            try:
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
                    print(f"✅ /properties_city: Rooms filter applied: {rooms_list}")
            except Exception as e:
                print(f"❌ /properties_city: Error processing rooms filter: {e}")
                pass
        
        # Developers filter
        if filters.get('developers'):
            repo_filters['developers'] = filters['developers']
        if filters.get('developer'):
            if 'developers' not in repo_filters:
                repo_filters['developers'] = []
            if filters['developer'] not in repo_filters['developers']:
                repo_filters['developers'].append(filters['developer'])
        
        # Districts filter — resolve slug/name → district_id for FK-based search
        if filters.get('districts'):
            district_names = filters['districts']
            if isinstance(district_names, str):
                district_names = [district_names]
            resolved_ids = []
            unresolved = []
            from models import District as _DM
            city_id_for_dist = current_city.id if current_city else None
            for dname in district_names:
                dname = dname.strip()
                if not dname:
                    continue
                # Try slug first, then name ILIKE
                q = _DM.query
                if city_id_for_dist:
                    q = q.filter_by(city_id=city_id_for_dist)
                dist_obj = q.filter_by(slug=dname).first()
                if not dist_obj:
                    dist_obj = q.filter(_DM.name.ilike(f'%{dname}%')).first()
                if dist_obj:
                    resolved_ids.append(dist_obj.id)
                else:
                    unresolved.append(dname)
            if resolved_ids:
                # Use district_id_in filter for precise FK-based lookup
                repo_filters['district_id_in'] = resolved_ids
            if unresolved:
                repo_filters['districts'] = unresolved
        
        # Residential complex filter
        if filters.get('residential_complex'):
            repo_filters['residential_complex'] = filters['residential_complex']

        # Quarter filter — try FK district path first, fall back to ILIKE on address fields
        if filters.get('quarter'):
            _qval = filters['quarter'].strip()
            from models import District as _DM_Q
            _dq_q = _DM_Q.query
            if current_city:
                _dq_q = _dq_q.filter_by(city_id=current_city.id)
            # 1. Exact name match
            _dist_q_obj = _dq_q.filter(db.func.lower(_DM_Q.name) == _qval.lower()).first()
            if not _dist_q_obj:
                # 2. Strip common type suffix and retry
                _qval_s = _qval.lower()
                for _sfx in (' округ', ' район', ' микрорайон', ' мкр', ' жилрайон'):
                    if _qval_s.endswith(_sfx):
                        _qval_s = _qval_s[:-len(_sfx)].strip()
                        break
                _dist_q_obj = _dq_q.filter(db.func.lower(_DM_Q.name) == _qval_s).first()
            if not _dist_q_obj:
                # 3. Partial name match
                _dist_q_obj = _dq_q.filter(_DM_Q.name.ilike(f'%{_qval}%')).first()

            if _dist_q_obj:
                # FK path — precise, uses district_id index (same as ?districts=slug)
                existing_ids = repo_filters.get('district_id_in', [])
                repo_filters['district_id_in'] = list(set(existing_ids) | {_dist_q_obj.id})
            else:
                # Fallback: complex_ids via ILIKE on RC address fields
                from models import ResidentialComplex as _RCM_Q
                _qids = [r.id for r in _RCM_Q.query.filter(
                    db.or_(
                        _RCM_Q.address_quarter.ilike(f'%{_qval}%'),
                        _RCM_Q.address_city_district.ilike(f'%{_qval}%')
                    ),
                    _RCM_Q.is_active == True
                ).all()]
                if _qids:
                    existing = set(repo_filters.get('complex_ids', []))
                    repo_filters['complex_ids'] = list(existing & set(_qids)) if existing else _qids
                else:
                    repo_filters['complex_ids'] = []

        # Street filter (addr_street + parsed_street) → complex_ids; supports multiple streets
        _street_vals = filters.get('streets') or ([filters['street']] if filters.get('street') else [])
        if _street_vals:
            from models import ResidentialComplex as _RCM_S
            from sqlalchemy import or_ as _or_s
            _sid_set = set()
            for _sv in _street_vals:
                _sv = _sv.strip()
                if not _sv:
                    continue
                _sids = [r.id for r in _RCM_S.query.filter(
                    _or_s(
                        _RCM_S.addr_street.ilike(f'%{_sv}%'),
                        _RCM_S.address.ilike(f'%{_sv}%'),
                    ),
                    _RCM_S.is_active == True
                ).all()]
                _sid_set.update(_sids)
            if _sid_set:
                existing = set(repo_filters.get('complex_ids', []))
                repo_filters['complex_ids'] = list(existing & _sid_set) if existing else list(_sid_set)
            else:
                repo_filters['complex_ids'] = []

        # Completion dates filter
        if filters.get('completion'):
            repo_filters['completion'] = filters['completion']
        
        # Floor range
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
        
        # Additional filters
        if filters.get('cashback_only'):
            repo_filters['cashback_only'] = True
        if filters.get('renovation'):
            repo_filters['renovation'] = filters['renovation']
        if filters.get('object_classes'):
            repo_filters['object_classes'] = filters['object_classes']
        if filters.get('building_types'):
            repo_filters['building_types'] = filters['building_types']
        if filters.get('floor_options'):
            repo_filters['floor_options'] = filters['floor_options']
        if filters.get('features'):
            repo_filters['features'] = filters['features']
        if filters.get('deal_type'):
            repo_filters['deal_type'] = filters['deal_type']
        if filters.get('building_released'):
            repo_filters['building_released'] = filters['building_released']
        if filters.get('bathroom_type'):
            repo_filters['bathroom_type'] = filters['bathroom_type']
        if filters.get('has_balcony'):
            repo_filters['has_balcony'] = filters['has_balcony']
        if filters.get('ceiling_height_min'):
            try:
                repo_filters['ceiling_height_min'] = float(filters['ceiling_height_min'])
            except (ValueError, TypeError):
                pass
        if filters.get('kitchen_area_min'):
            try:
                repo_filters['kitchen_area_min'] = float(filters['kitchen_area_min'])
            except (ValueError, TypeError):
                pass
        if filters.get('kitchen_area_max'):
            try:
                repo_filters['kitchen_area_max'] = float(filters['kitchen_area_max'])
            except (ValueError, TypeError):
                pass
        
        # ✅ CRITICAL: Property type filter
        if filters.get('property_type') and filters['property_type'] != 'all':
            property_type_map = {
                'apartments': 'Квартира',
                'houses': 'Дом',
                'townhouses': 'Таунхаус',
                'penthouses': 'Пентхаус',
                'apartments_commercial': 'Апартаменты'
            }
            mapped_type = property_type_map.get(filters['property_type'], filters['property_type'])
            repo_filters['property_type'] = mapped_type
            print(f"✅ /properties_city: Property type filter applied: {mapped_type}")
        
        # Search filter with smart matching
        if filters.get('search'):
            search_text = filters['search'].strip()
            search_applied = False
            
            if search_text:
                # Smart search: Try to match ResidentialComplex first
                complex_match = db.session.query(ResidentialComplex).filter(
                    ResidentialComplex.name.ilike(f'%{search_text}%')
                ).first()
                
                if complex_match:
                    repo_filters['residential_complex'] = complex_match.name
                    print(f"🏢 Smart search: Detected ЖК '{complex_match.name}' from query '{search_text}'")
                    search_applied = True
                
                # Try to match Developer
                if not search_applied:
                    developer_match = db.session.query(Developer).filter(
                        Developer.name.ilike(f'%{search_text}%')
                    ).first()
                    
                    if developer_match:
                        if 'developers' not in repo_filters:
                            repo_filters['developers'] = []
                        repo_filters['developers'].append(developer_match.name)
                        print(f"👔 Smart search: Detected застройщик '{developer_match.name}' from query '{search_text}'")
                        search_applied = True
                
                # If no smart match, use address/text search
                if not search_applied:
                    if any(prefix in search_text for prefix in ['г ', 'р-н ', 'ул', 'мкр', 'пер', 'улиц']):
                        tokens = DaDataClient.normalize_address_for_search(search_text)
                        if tokens:
                            import re
                            clean_tokens = []
                            for token in tokens:
                                cleaned = re.sub(r'^(улиц[аы]|ул\.?|просп(ект)?\.?|мкр\.?|пер\.?|г\.?|р-н)\s*', '', token, flags=re.IGNORECASE).strip()
                                if cleaned:
                                    clean_tokens.append(cleaned)
                            
                            if clean_tokens:
                                repo_filters['search'] = clean_tokens[-1]
                                print(f"🔍 Normalized search: '{search_text}' → '{clean_tokens[-1]}'")
                            else:
                                repo_filters['search'] = search_text
                        else:
                            repo_filters['search'] = search_text
                    else:
                        repo_filters['search'] = search_text
        
        # Parse sort_type — empty string = relevance (diverse across complexes)
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
        
        # Add city filter
        if current_city:
            repo_filters['city_id'] = current_city.id
            print(f"✅ /properties_city: Filtering by city: {current_city.name} (ID: {current_city.id})")
        
        # Get properties
        properties_list = PropertyRepository.get_all_active(
            limit=per_page,
            offset=offset,
            filters=repo_filters,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        total_properties = PropertyRepository.count_active(filters=repo_filters)
        
        # Convert to template format
        properties_data = []
        for prop in properties_list:
            try:
                complex_obj = prop.residential_complex
                developer_obj = prop.developer
                
                # Parse photos
                photos_list = []
                main_image = 'https://via.placeholder.com/400x300'
                
                if prop.main_image:
                    main_image = prop.main_image
                
                if prop.gallery_images:
                    try:
                        if isinstance(prop.gallery_images, list):
                            photos_list = prop.gallery_images
                        elif isinstance(prop.gallery_images, str):
                            photos_list = json.loads(prop.gallery_images)
                        
                        if photos_list and not prop.main_image:
                            main_image = photos_list[0]
                    except Exception as e:
                        print(f"Error parsing photos for property {prop.id}: {e}")
                
                # Calculate cashback
                cashback_rate = complex_obj.cashback_rate if complex_obj and complex_obj.cashback_rate else 3.5
                cashback_amount = int(prop.price * (cashback_rate / 100)) if prop.price else 0
                
                property_dict = {
                    'id': prop.id,
                    'price': prop.price or 0,
                    'price_formatted': prop.formatted_price,
                    'area': prop.area or 0,
                    'rooms': prop.rooms or 0,
                    'room_description': prop.room_description,
                    'floor': prop.floor if prop.floor is not None else 1,
                    'total_floors': prop.total_floors if prop.total_floors is not None else 1,
                    'address': prop.address or (complex_obj.address if complex_obj else ''),
                    'renovation': prop.renovation_type or 'no_renovation',
                    'renovation_display_name': PropertyRepository.get_renovation_display_name(prop.renovation_type),
                    'price_per_sqm': prop.price_per_sqm or (int(prop.price / prop.area) if prop.price and prop.area else 0),
                    'gallery': photos_list,
                    'image': main_image,
                    'latitude': prop.latitude or (complex_obj.latitude if complex_obj else None),
                    'longitude': prop.longitude or (complex_obj.longitude if complex_obj else None),
                    'complex_name': complex_obj.name if complex_obj else '',
                    'residential_complex': complex_obj.name if complex_obj else '',
                    'developer': developer_obj.name if developer_obj else '',
                    'developer_name': developer_obj.name if developer_obj else '',
                    'cashback_rate': cashback_rate,
                    'cashback': cashback_amount,
                    'cashback_available': True,
                    'district': prop.district.name if prop.district else '',
                    'city_name': prop.city.name if prop.city else '',
                    'region_name': prop.city.region.name if (prop.city and prop.city.region) else '',
                    'deal_type': prop.deal_type or 'sale',
                    'object_class': complex_obj.object_class_display_name if complex_obj else '',
                }
                
                properties_data.append(property_dict)
            except Exception as e:
                print(f"Error formatting property {prop.id}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # Pagination data
        total_pages = (total_properties + per_page - 1) // per_page if total_properties > 0 else 0
        pagination = SimpleNamespace(
            page=page,
            total_pages=total_pages,
            per_page=per_page,
            total=total_properties,
            has_prev=page > 1,
            has_next=page < total_pages,
            prev_num=page - 1 if page > 1 else None,
            next_num=page + 1 if page < total_pages else None
        )
        
        # Get developers and complexes for filters
        developers = DeveloperRepository.get_all_active()
        residential_complexes = ResidentialComplexRepository.get_all_active()
        
        # Get manager if logged in
        manager_data = None
        from models import Manager, Admin
        if current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager):
            manager = current_user._get_current_object()
            manager_data = {
                'id': manager.id,
                'name': manager.name,
                'phone': manager.phone,
                'email': manager.email,
                'photo': manager.profile_image
            }
        
        # Calculate max cashback
        max_cashback = 0
        if properties_data:
            for prop_dict in properties_data:
                if prop_dict.get('cashback'):
                    if prop_dict['cashback'] > max_cashback:
                        max_cashback = prop_dict['cashback']
        
        if max_cashback == 0 and residential_complexes:
            for rc in residential_complexes:
                if rc.cashback_rate:
                    estimated_cashback = int(15000000 * (rc.cashback_rate / 100))
                    if estimated_cashback > max_cashback:
                        max_cashback = estimated_cashback
        
        if max_cashback == 0:
            max_cashback = 500000
        
        # Get current manager
        current_manager = current_user._get_current_object() if (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)) else None
        
        # Generate canonical URL for SEO (always use production domain)
        canonical_url = _get_canonical_base_url() + url_for('props.properties_city', city_slug=city_slug)

        # ── Dynamic SEO meta based on active filters (CIAN/DomClick style) ──
        city_name = current_city.name if current_city else 'Краснодар'
        city_prep = current_city.name_prepositional if current_city else 'Краснодаре'
        city_gen  = current_city.name_genitive if current_city and hasattr(current_city, 'name_genitive') and current_city.name_genitive else (city_name + 'а')
        _rooms_map = {0: 'студии', 1: '1-комнатные квартиры', 2: '2-комнатные квартиры',
                      3: '3-комнатные квартиры', 4: '4-комнатные и более квартиры'}
        _rooms_acc = {0: 'студию', 1: '1-комнатную квартиру', 2: '2-комнатную квартиру',
                      3: '3-комнатную квартиру', 4: '4-комнатную квартиру'}
        _rooms_filter = [int(r) for r in (filters.get('rooms') or []) if str(r).lstrip('-').isdigit()]
        _rc   = filters.get('residential_complex', '').strip()
        # Resolve district slug/name to Russian display name for SEO
        from utils.district_phrase import format_district_phrase as _format_dist_phrase

        _dist_raw = (filters.get('district') or '') or (filters.get('districts', [None])[0] if filters.get('districts') else '')
        _dist = _dist_raw
        _dist_type = ''
        _dist_obj_found = None
        if _dist_raw:
            # Always try to resolve slug → Russian name + type (slug has no Cyrillic vowels)
            from models import District as _DM2
            _dist_obj_found = _DM2.query.filter_by(slug=_dist_raw).first()
            if not _dist_obj_found:
                # Also try exact name match (in case caller already passed Russian name)
                _dist_obj_found = _DM2.query.filter(_DM2.name.ilike(_dist_raw)).first()
            if _dist_obj_found:
                _dist = _dist_obj_found.name
                _dist_type = _dist_obj_found.district_type or ''
        # Full "в ..." phrase used in SEO h1/title/description
        _dist_phrase = _format_dist_phrase(_dist, _dist_type) if _dist else ''
        # Prepositional form alone (kept for backward compat — strip leading "в ")
        _dist_prep = _dist_phrase[2:] if _dist_phrase.startswith('в ') else _dist_phrase
        _total = f'{total_properties:,}'.replace(',', ' ')

        seo_title = seo_description = seo_h1 = seo_text = seo_keywords = None

        if _rc:
            seo_title       = f'Квартиры в ЖК {_rc}, {city_name}: цены, планировки, кэшбек | InBack'
            seo_description = (f'Купить квартиру в ЖК {_rc} в {city_prep}: {_total} вариантов с кэшбеком до 5% от InBack. '
                               f'Актуальные цены, планировки, ход строительства. Сэкономьте до 500 000 ₽.')
            seo_h1          = f'Квартиры в ЖК {_rc}'
            seo_text        = (f'Сравните {_total} вариантов квартир в ЖК {_rc} и получите кэшбек при покупке через InBack. '
                               f'Проверенный застройщик, юридическое сопровождение, возврат до 500 000 ₽.')
        elif len(_rooms_filter) == 1 and _dist:
            _r = _rooms_filter[0]
            _rn = _rooms_map.get(_r, 'квартиры')
            _ra = _rooms_acc.get(_r, 'квартиру')
            _dp = _dist_phrase or ('в ' + _dist)
            seo_title       = f'{_rn.capitalize()} {_dp}, {city_name}: {_total} вариантов | InBack'
            seo_description = (f'Купить {_ra} {_dp} ({city_name}): {_total} предложений в новостройках. '
                               f'Кэшбек до 5% от InBack. Актуальные цены от застройщика.')
            seo_h1          = f'{_rn.capitalize()} {_dp}'
        elif len(_rooms_filter) == 1:
            _r = _rooms_filter[0]
            _rn = _rooms_map.get(_r, 'квартиры')
            _ra = _rooms_acc.get(_r, 'квартиру')
            seo_title       = f'Купить {_ra} в новостройке {city_gen}: {_total} вариантов | InBack'
            seo_description = (f'{_rn.capitalize()} в новостройках {city_gen}: {_total} предложений с кэшбеком до 5% от InBack. '
                               f'Сравните цены, выберите планировку. Выгода до 500 000 ₽.')
            seo_h1          = f'{_rn.capitalize()} в новостройках {city_gen}'
        elif _dist:
            _dp = _dist_phrase or ('в ' + _dist)
            seo_title       = f'Новостройки {_dp}, {city_name}: {_total} квартир от застройщика | InBack'
            seo_description = (f'Купить квартиру в новостройке {_dp} ({city_name}): {_total} вариантов. '
                               f'Кэшбек до 5% при покупке через InBack. Актуальные цены и планировки.')
            seo_h1          = f'Новостройки {_dp}'
        elif len(_rooms_filter) > 1:
            _rnames = ' и '.join([_rooms_map.get(r, '') for r in sorted(_rooms_filter) if _rooms_map.get(r)])
            seo_title       = f'Купить квартиру в новостройке {city_gen}: {_total} вариантов | InBack'
            seo_description = (f'{_rnames.capitalize()} в новостройках {city_gen}: {_total} предложений с кэшбеком. '
                               f'Возврат до 500 000 ₽ при покупке через InBack.')
            seo_h1          = f'Квартиры в новостройках {city_gen}'

        # Extra SEO: developer filter (can combine with rooms)
        _dev_filter = ''
        if filters.get('developers') and isinstance(filters['developers'], list) and filters['developers']:
            _dev_filter = filters['developers'][0]
        elif filters.get('developer'):
            _dev_filter = filters['developer']
        if _dev_filter and not seo_title:
            if len(_rooms_filter) == 1:
                _r = _rooms_filter[0]
                _ra = _rooms_acc.get(_r, 'квартиру')
                seo_title       = f'Купить {_ra} от {_dev_filter} в {city_prep}: {_total} вариантов | InBack'
                seo_description = (f'{_ra.capitalize()} в новостройках застройщика {_dev_filter} в {city_prep}: {_total} предложений. '
                                   f'Кэшбек до 5% от InBack — возврат до 500 000 ₽.')
                seo_h1          = f'Квартиры от {_dev_filter} в {city_prep}'
            else:
                seo_title       = f'Новостройки от {_dev_filter} в {city_prep}: {_total} квартир | InBack'
                seo_description = (f'Купить квартиру от застройщика {_dev_filter} в {city_prep}: {_total} вариантов с кэшбеком до 5%. '
                                   f'Актуальные цены, планировки, ход строительства.')
                seo_h1          = f'Новостройки от {_dev_filter}'
        elif _dev_filter and seo_title:
            # Patch existing title to include developer name
            seo_title = seo_title.replace(' | InBack', f' от {_dev_filter} | InBack')

        # Extra SEO: price range filter
        _price_max = repo_filters.get('max_price')
        _price_min = repo_filters.get('min_price')
        if (_price_max or _price_min) and not seo_title:
            if _price_max:
                _pmax_m = int(_price_max / 1_000_000)
                seo_title       = f'Квартиры в новостройках {city_gen} до {_pmax_m} млн ₽: {_total} вариантов | InBack'
                seo_description = (f'Новостройки {city_gen} до {_pmax_m} млн рублей: {_total} вариантов с кэшбеком. '
                                   f'Проверенные ЖК от застройщиков. Возврат до 500 000 ₽ через InBack.')
                seo_h1          = f'Квартиры до {_pmax_m} млн ₽ в {city_prep}'
            elif _price_min:
                _pmin_m = int(_price_min / 1_000_000)
                seo_title       = f'Квартиры в новостройках {city_gen} от {_pmin_m} млн ₽ | InBack'
                seo_description = (f'Новостройки {city_gen} от {_pmin_m} млн рублей: {_total} вариантов с кэшбеком до 5%. '
                                   f'Просторные квартиры комфорт- и бизнес-класса от застройщиков.')
                seo_h1          = f'Квартиры от {_pmin_m} млн ₽ в {city_prep}'

        # Quarter filter SEO (address_quarter / address_city_district)
        _quarter_filter = filters.get('quarter', '').strip()
        if _quarter_filter and not seo_title:
            # Detect district_type: if it matches an admin district → okrug/rayon, else settlement
            from models import ResidentialComplex as _RCQS
            _is_cd = db.session.query(_RCQS.id).filter(
                _RCQS.address_city_district.ilike(f'%{_quarter_filter}%'),
                _RCQS.is_active == True
            ).first() is not None
            _q_dtype = ('okrug' if (current_city and current_city.id == 1) else 'rayon') if _is_cd else 'microrayon'
            _q_phrase = _format_dist_phrase(_quarter_filter, _q_dtype)
            seo_title       = f'Новостройки {_q_phrase}, {city_name}: {_total} квартир от застройщика | InBack'
            seo_description = (f'Купить квартиру в новостройке {_q_phrase} ({city_name}): {_total} вариантов. '
                               f'Кэшбек до 5% (до 500 000 ₽) при покупке через InBack.')
            seo_h1          = f'Новостройки {_q_phrase}'

        # Street filter SEO (addr_street)
        _street_filter = filters.get('street', '').strip()
        if _street_filter and not seo_title:
            seo_title       = f'Квартиры на {_street_filter}, {city_name}: {_total} вариантов | InBack'
            seo_description = (f'Купить квартиру в новостройке на {_street_filter} ({city_name}): {_total} вариантов. '
                               f'Кэшбек до 5% (до 500 000 ₽) при покупке через InBack.')
            seo_h1          = f'Квартиры на {_street_filter}'

        # Extra SEO: search query
        _search_q = filters.get('search', '').strip()
        if _search_q and not seo_title and not _rc:
            seo_title       = f'Новостройки по запросу «{_search_q}» в {city_prep}: {_total} вариантов | InBack'
            seo_description = (f'Результаты поиска «{_search_q}» в новостройках {city_gen}: {_total} предложений. '
                               f'Кэшбек до 5% при покупке через InBack.')
            seo_h1          = f'Поиск: «{_search_q}»'

        # ── City-specific SEO for Black Sea coast cities ─────────────────────
        _BLACK_SEA_SEO = {
            'sochi': {
                'title': 'Новостройки Сочи {year}: купить квартиру с кэшбеком до 500 000 ₽ | InBack',
                'description': 'Новостройки в Сочи от застройщиков: {count} вариантов с кэшбеком до 5% (до 500 000 ₽). Курортная недвижимость, апартаменты у моря, инвестиции. Официальный возврат через InBack.',
                'h1': 'Новостройки в Сочи с кэшбеком',
                'keywords': 'новостройки Сочи, купить квартиру Сочи, новостройки Сочи 2026, апартаменты Сочи от застройщика, квартиры у моря Сочи, инвестиции в недвижимость Сочи, кэшбек новостройки Сочи',
            },
            'anapa': {
                'title': 'Новостройки Анапы {year}: купить квартиру с кэшбеком | InBack',
                'description': 'Новостройки в Анапе от застройщиков: квартиры и апартаменты у Чёрного моря с кэшбеком до 5% от InBack. Климатический курорт, детские объекты, ипотека. Официальный возврат до 500 000 ₽.',
                'h1': 'Новостройки в Анапе с кэшбеком',
                'keywords': 'новостройки Анапа, купить квартиру Анапа, новостройки Анапа 2026, квартиры у моря Анапа, апартаменты Анапа застройщик, кэшбек новостройки Анапа, недвижимость Анапа',
            },
            'novorossiysk': {
                'title': 'Новостройки Новороссийска {year}: квартиры от застройщика с кэшбеком | InBack',
                'description': 'Новостройки в Новороссийске: квартиры у моря от застройщиков с кэшбеком до 5% от InBack. Портовый город, развитая инфраструктура, доступные цены. Возврат до 500 000 ₽.',
                'h1': 'Новостройки в Новороссийске с кэшбеком',
                'keywords': 'новостройки Новороссийск, купить квартиру Новороссийск, квартиры Новороссийск застройщик, кэшбек новостройки Новороссийск, недвижимость Новороссийск',
            },
            'gelendzhik': {
                'title': 'Новостройки Геленджика {year}: купить квартиру у моря с кэшбеком | InBack',
                'description': 'Новостройки в Геленджике от застройщиков: квартиры и апартаменты на курорте с кэшбеком до 5% от InBack. Бухта, горы, чистый воздух. Инвестиции в курортную недвижимость.',
                'h1': 'Новостройки в Геленджике с кэшбеком',
                'keywords': 'новостройки Геленджик, купить квартиру Геленджик, апартаменты Геленджик застройщик, кэшбек новостройки Геленджик, недвижимость Геленджик у моря',
            },
            'tuapse': {
                'title': 'Новостройки Туапсе {year}: квартиры от застройщика с кэшбеком | InBack',
                'description': 'Новостройки в Туапсе: квартиры у Чёрного моря от застройщиков с кэшбеком до 5% от InBack. Удобное расположение между Сочи и Новороссийском. Возврат до 500 000 ₽.',
                'h1': 'Новостройки в Туапсе с кэшбеком',
                'keywords': 'новостройки Туапсе, купить квартиру Туапсе, квартиры Туапсе застройщик, кэшбек новостройки Туапсе, недвижимость Туапсе',
            },
            'krasnodar': {
                'title': 'Новостройки в Краснодаре {year}: купить квартиру от застройщика с кэшбеком | InBack',
                'description': 'Купить квартиру в новостройке Краснодара от застройщика. {count} вариантов с кэшбеком до 500 000 ₽. Актуальные цены {year}, ипотека от 3,5%, рассрочка. InBack — официальный возврат средств.',
                'h1': 'Новостройки в Краснодаре',
                'keywords': 'новостройки в краснодаре, квартира в новостройке краснодар, купить новостройку в краснодаре, купить квартиру в краснодаре новостройка, новостройки в краснодаре от застройщика, квартиры в краснодаре новостройки от застройщика, цена квартиры в новостройке в краснодаре, новостройки краснодара {year}',
            },
            'maykop': {
                'title': 'Новостройки Майкопа {year}: купить квартиру от застройщика с кэшбеком | InBack',
                'description': 'Квартиры в новостройках Майкопа от застройщиков. {count} вариантов с кэшбеком до 500 000 ₽. Актуальные цены {year}, ипотека, рассрочка. Официальный возврат через InBack.',
                'h1': 'Новостройки в Майкопе',
                'keywords': 'новостройки майкоп, купить квартиру майкоп, новостройки майкоп {year}, квартиры майкоп от застройщика, новостройки в майкопе от застройщика, кэшбек новостройки майкоп',
            },
            'armavir': {
                'title': 'Новостройки Армавира {year}: купить квартиру от застройщика | InBack',
                'description': 'Квартиры в новостройках Армавира от застройщиков. {count} вариантов с кэшбеком до 500 000 ₽. Актуальные цены {year}, ипотека, рассрочка. Официальный возврат через InBack.',
                'h1': 'Новостройки в Армавире',
                'keywords': 'новостройки армавир, купить квартиру армавир, новостройки армавир {year}, квартиры армавир от застройщика, кэшбек армавир',
            },
        }
        if not seo_title and city_slug in _BLACK_SEA_SEO:
            from datetime import date as _date_bsc
            _bsc = _BLACK_SEA_SEO[city_slug]
            _year_bsc = _date_bsc.today().year
            seo_title = _bsc['title'].replace('{year}', str(_year_bsc)).replace('{count}', _total)
            seo_description = _bsc['description'].replace('{year}', str(_year_bsc)).replace('{count}', _total)
            seo_h1 = _bsc['h1']
            seo_keywords = _bsc['keywords']
        # ── End Black Sea SEO ─────────────────────────────────────────────────

        # Fallback to defaults (already defined in template)
        # seo_title/description/h1 = None → template uses its default blocks
        # ── End dynamic SEO ──────────────────────────────────────────────────

        # ── ЖК мини-карточка: server-side prefetch ───────────────────────────
        jk_card_data = None
        if filters.get('residential_complex'):
            try:
                _rc_name = filters['residential_complex']
                _rc = ResidentialComplex.query.filter(
                    db.func.lower(ResidentialComplex.name) == _rc_name.lower(),
                    ResidentialComplex.is_active == True
                ).first()
                if not _rc:
                    _rc = ResidentialComplex.query.filter(
                        ResidentialComplex.name.ilike(f'%{_rc_name}%'),
                        ResidentialComplex.is_active == True
                    ).first()
                if _rc:
                    from datetime import date as _d2
                    _cur_y = _d2.today().year
                    _status = ('Сдан' if _rc.end_build_year and _rc.end_build_year < _cur_y
                               else ('Сдаётся в этом году' if _rc.end_build_year and _rc.end_build_year == _cur_y
                                     else 'Строится'))
                    _completion = None
                    if _rc.end_build_year:
                        _completion = (f'{_rc.end_build_quarter} кв. {_rc.end_build_year}'
                                       if _rc.end_build_quarter else str(_rc.end_build_year))
                    _dev_name = None
                    _dev_logo = None
                    if _rc.developer_id:
                        from models import Developer as _Dev
                        _dev = db.session.get(_Dev, _rc.developer_id)
                        if _dev:
                            _dev_name = _dev.name
                            _dev_logo = getattr(_dev, 'logo_url', None)
                    _image = _rc.main_image or ''
                    if not _image and _rc.gallery_images:
                        import json as _jj
                        try:
                            _imgs = _jj.loads(_rc.gallery_images)
                            _image = _imgs[0] if _imgs else ''
                        except Exception:
                            pass
                    _city_slug_jk = current_city.slug if current_city else 'krasnodar'
                    _room_rows = db.session.execute(text(
                        "SELECT COALESCE(rooms,0), COUNT(*), MIN(price) FROM properties "
                        "WHERE complex_id=:cid AND is_active=TRUE GROUP BY COALESCE(rooms,0) ORDER BY COALESCE(rooms,0)"
                    ), {'cid': _rc.id}).fetchall()
                    _room_stats = {}
                    _min_prices = {}
                    _total_jk = 0
                    for _rr in _room_rows:
                        _rk = int(_rr[0])
                        _room_stats[_rk] = int(_rr[1])
                        if _rr[2]:
                            _min_prices[_rk] = int(_rr[2])
                        _total_jk += int(_rr[1])
                    jk_card_data = {
                        'name': _rc.name,
                        'url': f'/{_city_slug_jk}/zk/{_rc.slug}' if _rc.slug else None,
                        'image': _image,
                        'status': _status,
                        'completion': _completion,
                        'housing_class': getattr(_rc, 'object_class_display_name', None) or '',
                        'developer_name': _dev_name,
                        'developer_logo': _dev_logo,
                        'total': _total_jk,
                        'room_stats': _room_stats,
                        'min_prices': _min_prices,
                    }
            except Exception as _e:
                print(f'JK card prefetch error: {_e}')
        # ── end ЖК prefetch ──────────────────────────────────────────────────

        # Fetch okrugs with live prop counts — use okrug_district_id for aggregated counts
        # so that properties assigned to sub-microrayons are also counted in the okrug.
        from models import District as _DistrictM, Property as _PropM, ResidentialComplex as _RCM
        from sqlalchemy import func as _sqlfunc
        # Count via okrug_district_id (populated by PIP), union with direct district_id matches
        _okrug_subq = (
            db.session.query(
                _RCM.okrug_district_id.label('did'),
                _sqlfunc.count(_PropM.id).label('cnt')
            )
            .join(_PropM, _PropM.complex_id == _RCM.id)
            .filter(_PropM.is_active == True, _RCM.okrug_district_id.isnot(None))
            .group_by(_RCM.okrug_district_id)
            .subquery()
        )
        _okrug_q = (
            db.session.query(_DistrictM, _sqlfunc.coalesce(_okrug_subq.c.cnt, 0).label('cnt'))
            .outerjoin(_okrug_subq, _DistrictM.id == _okrug_subq.c.did)
            .filter(_DistrictM.district_type == 'okrug')
        )
        if current_city:
            _okrug_q = _okrug_q.filter(_DistrictM.city_id == current_city.id)
        city_okrugs = [
            {'id': d.id, 'name': d.name, 'slug': d.slug, 'props_count': cnt}
            for d, cnt in _okrug_q.order_by(db.text('cnt DESC')).all()
            if d.name != 'Краснодарский край'
        ]

        # Fetch districts for "Районы города" SEO section + active filter districts
        seo_districts = []
        if current_city:
            try:
                _jk_prefixes_filter = (
                    'Жилой комплекс', 'ЖК ', 'ЖК«', 'ЖК"', 'СНТ ', 'ДНП ', 'Коттеджный'
                )
                _sd_q = _DistrictM.query.filter(
                    _DistrictM.city_id == current_city.id,
                    _DistrictM.slug.isnot(None),
                    _DistrictM.slug != '',
                    _DistrictM.name != 'Краснодарский край'
                ).order_by(_DistrictM.name).limit(200).all()
                seo_districts = [
                    {'name': d.name, 'slug': d.slug, 'type': d.district_type}
                    for d in _sd_q
                    if not any(d.name.startswith(p) for p in _jk_prefixes_filter)
                ]
                # Always include actively filtered districts (they may fall outside the limit)
                _active_dist_slugs = filters.get('districts') or []
                if _active_dist_slugs:
                    _existing_slugs = {d['slug'] for d in seo_districts}
                    _missing_slugs = [s for s in _active_dist_slugs if s not in _existing_slugs]
                    if _missing_slugs:
                        _extra = _DistrictM.query.filter(
                            _DistrictM.city_id == current_city.id,
                            _DistrictM.slug.in_(_missing_slugs)
                        ).all()
                        seo_districts += [{'name': d.name, 'slug': d.slug, 'type': d.district_type} for d in _extra]
            except Exception:
                seo_districts = []

        # Build guaranteed slug→info mapping for active district chips in template
        active_districts_info = {d['slug']: d for d in seo_districts}
        # Supplement from directly-resolved district object (covers edge cases)
        if _dist_obj_found and _dist_obj_found.slug not in active_districts_info:
            active_districts_info[_dist_obj_found.slug] = {
                'name': _dist_obj_found.name,
                'slug': _dist_obj_found.slug,
                'type': _dist_obj_found.district_type or '',
            }

        # OG image: first active RC with main_image for this city
        # NOTE: after_request hook in app.py rewrites cdn-cian.ru URLs to /api/img-proxy?t=TOKEN,
        # so we pre-convert CDN URLs to absolute proxy URLs ourselves to get absolute og:image.
        seo_og_image = None
        try:
            _og_rc = ResidentialComplex.query.filter(
                ResidentialComplex.city_id == current_city.id,
                ResidentialComplex.is_active == True,
                ResidentialComplex.main_image.isnot(None),
                ResidentialComplex.main_image != ''
            ).with_entities(ResidentialComplex.main_image).first()
            if _og_rc and _og_rc.main_image:
                _img = str(_og_rc.main_image)
                if 'cdn-cian.ru/' in _img:
                    import base64 as _b64
                    _path = _img.split('cdn-cian.ru/', 1)[1]
                    _tok = _b64.urlsafe_b64encode(_path.encode()).decode().rstrip('=')
                    seo_og_image = f'https://inback.ru/api/img-proxy?t={_tok}'
                elif _img.startswith('/'):
                    seo_og_image = f'https://inback.ru{_img}'
                else:
                    seo_og_image = _img
        except Exception:
            pass

        # Query distinct completion years for dynamic filter checkboxes
        available_years = []
        try:
            from sqlalchemy import func as _sqlfunc2
            _yr_q = db.session.query(
                _sqlfunc2.distinct(ResidentialComplex.end_build_year)
            ).filter(
                ResidentialComplex.end_build_year.isnot(None),
                ResidentialComplex.is_active == True
            )
            if current_city:
                _yr_q = _yr_q.filter(ResidentialComplex.city_id == current_city.id)
            from datetime import date as _date_yr
            _cur_yr = _date_yr.today().year
            available_years = sorted([y[0] for y in _yr_q.all() if y[0] and int(y[0]) >= _cur_yr])
        except Exception:
            available_years = [2025, 2026, 2027, 2028, 2029, 2030]

        response = make_response(render_template('properties.html',
                                 current_city=current_city,
                                 properties=properties_data,
                                 pagination=pagination,
                                 filters=filters,
                                 developers=developers,
                                 residential_complexes=residential_complexes,
                                 available_years=available_years,
                                 manager=manager_data,
                                 total_pages=total_pages,
                                 total_properties=total_properties,
                                 max_cashback=max_cashback,
                                 user_authenticated=current_user.is_authenticated,
                                 manager_authenticated=isinstance(current_user._get_current_object(), Manager) if current_user.is_authenticated else False,
                                 admin_authenticated=isinstance(current_user._get_current_object(), Admin) if current_user.is_authenticated else False,
                                 current_manager=current_manager,
                                 canonical_url=canonical_url,
                                 seo_title=seo_title,
                                 seo_description=seo_description,
                                 seo_h1=seo_h1,
                                 seo_text=seo_text,
                                 seo_keywords=seo_keywords,
                                 jk_card_data=jk_card_data,
                                 city_okrugs=city_okrugs,
                                 seo_districts=seo_districts,
                                 active_districts_info=active_districts_info,
                                 seo_og_image=seo_og_image,
                                 yandex_maps_api_key=os.environ.get('YANDEX_MAPS_API_KEY', ''),
                                 image_proxy_enabled=ChatSettings.get('image_proxy_enabled', '1') != '0'))
        
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
        
    except Exception as e:
        print(f"ERROR in /properties_city: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', 
                             error_code=500, 
                             error_message='Ошибка при загрузке страницы с квартирами',
                             current_city=current_city), 500



# ─── Redirect /properties/<id> → /object/<id> (fixes похожие card URLs) ────
@props_bp.route('/<city_slug>/properties/<int:property_id>')
def property_detail_city_redirect(city_slug, property_id):
    """Redirect old /properties/<id> URLs to canonical /object/<id>"""
    return redirect(url_for('props.property_detail_city', city_slug=city_slug, property_id=property_id), 301)


# ─── City-based property detail ────────────────────────────────────────────
@props_bp.route('/<city_slug>/object/<int:property_id>')
def property_detail_city(city_slug, property_id):
    """City-based individual property page - SEO-friendly URL version"""
    # Resolve city context using city_slug from URL
    current_city = _resolve_city_context(city_slug=city_slug)
    
    # If city not found, redirect to default page
    if not current_city:
        flash('Город не найден. Показываем результаты для Краснодара.', 'warning')
        return redirect(url_for('props.property_detail', property_id=property_id))
    
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
        import json
        from sqlalchemy import func
        from repositories.property_repository import PropertyRepository
        from models import Property, ResidentialComplex
        
        # Get property
        prop = PropertyRepository.get_by_id(property_id)
        
        if not prop:
            print(f"Property {property_id} not found")
            return redirect(url_for('props.properties_city', city_slug=city_slug))
        
        # Get related objects
        complex_obj = prop.residential_complex
        developer_obj = prop.developer
        
        # Parse photos
        images = []
        main_image = 'https://via.placeholder.com/400x300/f3f4f6/9ca3af?text=Фото+недоступно'
        
        if prop.main_image:
            main_image = prop.main_image
        
        if prop.gallery_images:
            try:
                if isinstance(prop.gallery_images, list):
                    images = prop.gallery_images
                elif isinstance(prop.gallery_images, str):
                    images = json.loads(prop.gallery_images)
                
                if images and not prop.main_image:
                    main_image = images[0]
            except Exception as e:
                print(f"Error parsing photos: {e}")
        
        # Create completion date
        completion_date = 'Уточняется'
        if complex_obj:
            if complex_obj.end_build_year and complex_obj.end_build_quarter:
                completion_date = f"{complex_obj.end_build_year} г., {complex_obj.end_build_quarter} кв."
            elif complex_obj.end_build_year:
                completion_date = f"{complex_obj.end_build_year} г."
        
        # Calculate cashback
        cashback_rate = complex_obj.cashback_rate if complex_obj and complex_obj.cashback_rate else 3.5
        cashback_amount = int(prop.price * (cashback_rate / 100)) if prop.price else 0
        
        # Parse complex infrastructure and amenities
        infrastructure_list = []
        advantages_list = []
        if complex_obj:
            if complex_obj.infrastructure:
                try:
                    if isinstance(complex_obj.infrastructure, str):
                        infrastructure_list = json.loads(complex_obj.infrastructure)
                    elif isinstance(complex_obj.infrastructure, list):
                        infrastructure_list = complex_obj.infrastructure
                except:
                    pass
            
            if complex_obj.amenities:
                try:
                    if isinstance(complex_obj.amenities, str):
                        advantages_list = json.loads(complex_obj.amenities)
                    elif isinstance(complex_obj.amenities, list):
                        advantages_list = complex_obj.amenities
                except:
                    pass
        
        # Build property data
        property_data = {
            'id': prop.inner_id or prop.id,
            'db_id': prop.id,
            'complex_id': complex_obj.id if complex_obj else None,
            'title': prop.title or (f"Студия {prop.area} м²" if prop.rooms == 0 else f"{prop.rooms}-комнатная квартира {prop.area} м²"),
            'description': prop.description or (complex_obj.description if complex_obj else None),
            'detailed_description': complex_obj.detailed_description if complex_obj else None,
            'price': prop.price or 0,
            'cashback_percent': cashback_rate,
            'gallery': images,
            'area': prop.area or 0,
            'living_area': round(prop.living_area, 1) if prop.living_area else None,
            'kitchen_area': round(prop.kitchen_area, 1) if prop.kitchen_area else None,
            'rooms': prop.rooms or 0,
            'floor': prop.floor if prop.floor is not None else 1,
            'total_floors': prop.total_floors if prop.total_floors is not None else 1,
            'address': prop.address or (complex_obj.address if complex_obj else 'Адрес уточняется'),
            'full_address': prop.address or (complex_obj.address if complex_obj else 'Адрес уточняется'),
            'short_address': prop.address or (complex_obj.address if complex_obj else 'Адрес уточняется'),
            'locality_name': prop.district.name if prop.district else (complex_obj.district.name if complex_obj and complex_obj.district else (current_city.name if current_city else '')),
            'district': prop.district.name if prop.district else (complex_obj.district.name if complex_obj and complex_obj.district else ''),
            'city_name': prop.city.name if prop.city else (current_city.name if current_city else ''),
            'region_name': prop.city.region.name if (prop.city and prop.city.region) else '',
            'district_name': prop.district.name if prop.district else '',
            'developer': developer_obj.name if developer_obj else 'Не указан',
            'complex_name': complex_obj.name if complex_obj else 'Не указан',
            'building_name': prop.complex_building_name or 'Корпус 1',
            'building_released': True,
            'renovation_type': PropertyRepository.get_renovation_display_name(prop.renovation_type),
            'finishing': PropertyRepository.get_renovation_display_name(prop.renovation_type),
            'completion_date': completion_date,
            'mortgage_rate': '3.5%',
            'square_price': prop.price_per_sqm or (int(prop.price / prop.area) if prop.price and prop.area else 0),
            'mortgage_payment': prop.mortgage_price or 0,
            'class_type': complex_obj.object_class_display_name if complex_obj else 'Комфорт',
            'cashback_amount': cashback_amount,
            'images': images,
            'image': main_image,
            'latitude': prop.latitude or (complex_obj.latitude if complex_obj else None),
            'longitude': prop.longitude or (complex_obj.longitude if complex_obj else None),
            'address_position_lat': prop.latitude or (complex_obj.latitude if complex_obj else None),
            'address_position_lon': prop.longitude or (complex_obj.longitude if complex_obj else None),
            'infrastructure': infrastructure_list,
            'advantages': advantages_list,
            'complex_total_apartments': Property.query.filter_by(complex_id=complex_obj.id, is_active=True).count() if complex_obj else 0,
            'distance_to_center': float(complex_obj.distance_to_center) if complex_obj and complex_obj.distance_to_center else None,
            'nearby_places': _parse_nearby_places(complex_obj.nearby if complex_obj else None),
            'nearby_json': (complex_obj.nearby if complex_obj and complex_obj.nearby else 'null'),
            # ── Планировка квартиры (схематичный чертёж) ──
            'layout_image': prop.plan_image or None,
            # ── План этажа (расположение квартиры на этаже) ──
            'floor_plan_image': getattr(prop, 'floor_plan_image', None),
            # ── Планировки ЖК (из layout_images комплекса) ──
            'plan_images': (lambda: _parse_plan_images_from_complex(complex_obj))(),
            # ── TrendAgent расширенные поля квартиры ──
            'ceiling_height': prop.ceiling_height,
            'has_balcony': prop.has_balcony,
            'balcony_type': prop.balcony_type,         # Лоджия / Балкон / Терраса
            'window_type': prop.window_type,           # Увеличенные / Стандартные
            'area_given': prop.area_given,             # Приведённая площадь
            'price_full_payment': prop.price_full_payment,  # Цена при 100% оплате
            'ta_start_price': prop.ta_start_price,     # Стартовая цена
            'ta_start_price_sqm': prop.ta_start_price_sqm,  # Стартовая цена за м²
            'bathroom_type': prop.bathroom_type,       # Санузел
            'view': prop.view_from_window,             # Вид из окна
            'renovation_display_name': PropertyRepository.get_renovation_display_name(prop.renovation_type),
            'deal_type': prop.deal_type,
            'complex_slug': complex_obj.slug if complex_obj else None,
            'entrance_number': prop.entrance_number,
        }
        
        # Get similar apartments
        similar_apartments = []
        if complex_obj:
            similar_props = PropertyRepository.get_by_complex_id(
                complex_obj.id,
                limit=6,
                sort_by='price',
                sort_order='asc'
            )
            
            for similar_prop in similar_props:
                if similar_prop.id != prop.id:
                    similar_main_image = 'https://via.placeholder.com/400x300'
                    if similar_prop.main_image:
                        similar_main_image = similar_prop.main_image
                    elif similar_prop.gallery_images:
                        try:
                            if isinstance(similar_prop.gallery_images, list):
                                similar_main_image = similar_prop.gallery_images[0] if similar_prop.gallery_images else similar_main_image
                            elif isinstance(similar_prop.gallery_images, str):
                                photos = json.loads(similar_prop.gallery_images)
                                similar_main_image = photos[0] if photos else similar_main_image
                        except:
                            pass
                    
                    
                    # Calculate cashback for similar apartment
                    similar_cashback = int(similar_prop.price * (cashback_rate / 100)) if similar_prop.price else 0
                    similar_apartments.append({
                        'id': similar_prop.inner_id or similar_prop.id,
                        'rooms': similar_prop.rooms or 0,
                        'area': similar_prop.area or 0,
                        'price': similar_prop.price or 0,
                        'floor': similar_prop.floor if similar_prop.floor is not None else 1,
                        'total_floors': similar_prop.total_floors if similar_prop.total_floors is not None else 1,
                        'image': similar_main_image,
                        'url': f'/{city_slug}/object/{similar_prop.inner_id or similar_prop.id}',
                        'cashback': similar_cashback
                    })
        
        # Get complex info
        complex_info = None
        if complex_obj:
            # Prefer clean nashdom photos; fall back to CIAN gallery
            complex_photos = _parse_nashdom_photos(complex_obj)
            if not complex_photos and complex_obj.gallery_images:
                try:
                    if isinstance(complex_obj.gallery_images, list):
                        complex_photos = complex_obj.gallery_images
                    elif isinstance(complex_obj.gallery_images, str):
                        complex_photos = json.loads(complex_obj.gallery_images)
                except:
                    pass
            # Parse layout images for complex
            complex_layout_imgs = _parse_plan_images_from_complex(complex_obj)
            # Статистика ЖК
            total_apartments = Property.query.filter_by(complex_id=complex_obj.id, is_active=True).count()
            studios_count = Property.query.filter_by(complex_id=complex_obj.id, rooms=0, is_active=True).count()
            buildings_count_result = db.session.query(func.count(func.distinct(Property.complex_building_name))).filter(
                Property.complex_id == complex_obj.id,
                Property.is_active == True,
                Property.complex_building_name.isnot(None)
            ).scalar() or 1
            
            # Parse advantages / amenities from JSON fields
            try:
                complex_advantages = json.loads(complex_obj.advantages) if complex_obj.advantages and isinstance(complex_obj.advantages, str) else (complex_obj.advantages or [])
                if not isinstance(complex_advantages, list):
                    complex_advantages = []
            except Exception:
                complex_advantages = []
            try:
                complex_amenities = json.loads(complex_obj.amenities) if complex_obj.amenities and isinstance(complex_obj.amenities, str) else (complex_obj.amenities or [])
                if not isinstance(complex_amenities, list):
                    complex_amenities = []
            except Exception:
                complex_amenities = []
            try:
                complex_nearby = json.loads(complex_obj.nearby) if complex_obj.nearby and isinstance(complex_obj.nearby, str) else (complex_obj.nearby or {})
            except Exception:
                complex_nearby = {}

            complex_info = {
                'id': complex_obj.id,
                'name': complex_obj.name,
                'developer': developer_obj.name if developer_obj else 'Не указан',
                'address': complex_obj.address or 'Адрес уточняется',
                'description': complex_obj.description or 'Описание отсутствует',
                'images': complex_photos,
                'layout_images': complex_layout_imgs,
                'latitude': complex_obj.latitude,
                'longitude': complex_obj.longitude,
                'cashback_rate': complex_obj.cashback_rate or 0,
                'url': f'/{city_slug}/zk/{complex_obj.slug or _create_slug(complex_obj.name)}',
                'total_apartments': total_apartments,
                'studios_count': studios_count,
                'buildings_count': buildings_count_result,
                'finishing_variants': getattr(complex_obj, 'finishing_variants', None),
                # Extended ЖК data
                'object_class': complex_obj.object_class_display_name or '',
                'floors_min': complex_obj.floors_min,
                'floors_max': complex_obj.floors_max,
                'parking_type': complex_obj.parking_type or '',
                'finishing_type': complex_obj.finishing_type or '',
                'ceiling_height': complex_obj.ceiling_height or '',
                'wall_material': complex_obj.wall_material or '',
                'has_accreditation': bool(complex_obj.has_accreditation),
                'has_green_mortgage': bool(complex_obj.has_green_mortgage),
                'with_renovation': bool(complex_obj.with_renovation),
                'financing_sber': bool(complex_obj.financing_sber),
                'end_build_year': complex_obj.end_build_year,
                'end_build_quarter': complex_obj.end_build_quarter,
                'advantages': complex_advantages,
                'amenities': complex_amenities,
                'nearby': complex_nearby,
                'complex_slug': complex_obj.slug or _create_slug(complex_obj.name),
            }
        
        # Get manager for authenticated user
        manager_data = None
        if current_user.is_authenticated:
            from models import User, Manager
            # Check if current_user is a regular User (not Manager or Admin)
            current_obj = current_user._get_current_object()
            if isinstance(current_obj, User) and hasattr(current_obj, 'assigned_manager_id') and current_obj.assigned_manager_id:
                # Get assigned manager
                manager = Manager.query.get(current_obj.assigned_manager_id)
                if manager and manager.is_active:
                    manager_data = {
                        'id': manager.id,
                        'name': manager.full_name,
                        'phone': manager.phone,
                        'email': manager.email,
                        'photo': manager.profile_image
                    }
        # Generate canonical URL for SEO (always use production domain)
        canonical_url = _get_canonical_base_url() + url_for('props.property_detail_city', city_slug=city_slug, property_id=property_id)
        
        # Build developer info for template
        developer_info = None
        if developer_obj:
            developer_info = {
                'id': developer_obj.id,
                'name': developer_obj.name,
                'slug': developer_obj.slug,
                'logo_url': developer_obj.logo_url,
                'description': developer_obj.description,
                'total_complexes': developer_obj.total_complexes,
                'completed_projects': developer_obj.completed_projects,
                'founded_year': developer_obj.founded_year,
                'established_year': developer_obj.established_year,
                'website': developer_obj.website,
            }

        return render_template('property_detail.html',
                             current_city=current_city,
                             property=property_data,
                             complex_info=complex_info,
                             similar_apartments=similar_apartments,
                             manager=manager_data,
                             developer_info=developer_info,
                             canonical_url=canonical_url)
        
    except Exception as e:
        print(f"ERROR in /property_detail_city: {e}")
        import traceback
        traceback.print_exc()
        return f"Error 500: {str(e)}", 500


