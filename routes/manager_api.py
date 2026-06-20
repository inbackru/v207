"""
Manager API Blueprint — JSON API endpoints for the manager dashboard, user dashboard,
favorites, collections, notifications, dashboard data, referrals, and searches.
Routes: /api/manager/*, /api/client/*, /api/favorites/*, /api/complexes/favorites/*,
        /api/dashboard/*, /api/notifications/*, /api/user/*, /dashboard
"""
import json
import logging
import os
import io
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, current_app, send_file, render_template, redirect, url_for, session
from flask_login import current_user, login_required
from sqlalchemy import text

from app import db, csrf, admin_required, get_districts_list, get_developers_list

logger = logging.getLogger(__name__)

mgr_api_bp = Blueprint('mgr_api', __name__)

# Decorator imported at module init — works because app is fully loaded before blueprint registers
from app import manager_required, require_json_csrf

@mgr_api_bp.route('/api/manager/favorites-properties')
@manager_required
def get_manager_favorite_properties():
    """Get properties with full characteristics for comparison"""
    try:
        # Check if specific IDs are requested for server-side filtering
        from flask import request
        requested_ids = request.args.get('ids', '')
        filter_ids_str = [id.strip() for id in requested_ids.split(',') if id.strip()] if requested_ids else []
        
        # ✅ MIGRATED: Load properties using repository (batch loading)
        import json
        
        try:
            from models import Property, ResidentialComplex, Developer, District
            from sqlalchemy.orm import joinedload
            
            properties_data = []
            
            # Load properties with eager loading of relationships
            query = Property.query.options(
                joinedload(Property.residential_complex),
                joinedload(Property.developer),
                joinedload(Property.district)
            )
            
            if filter_ids_str:
                # Filter by properties.id (primary key integer)
                filter_ids_int = [int(id) for id in filter_ids_str if id.isdigit()]
                query = query.filter(Property.id.in_(filter_ids_int[:10]))
            else:
                # Get all active properties (limited)
                query = query.filter(Property.status == 'available').limit(100)
            
            properties_orm = query.all()
            
            for prop in properties_orm:
                # Get photos
                photos_data = []
                if hasattr(prop, 'photos') and prop.photos:
                    try:
                        photos_data = json.loads(prop.photos) if isinstance(prop.photos, str) else prop.photos
                    except:
                        photos_data = []
                
                # Fallback to main_image or gallery_images
                if not photos_data:
                    if hasattr(prop, 'main_image') and prop.main_image:
                        photos_data = [prop.main_image]
                    elif hasattr(prop, 'gallery_images') and prop.gallery_images:
                        try:
                            gallery = json.loads(prop.gallery_images) if isinstance(prop.gallery_images, str) else prop.gallery_images
                            photos_data = gallery if isinstance(gallery, list) else []
                        except:
                            pass
                
                first_image = photos_data[0] if photos_data else '/static/images/no-photo.svg'
                
                # Format room text
                rooms_count = prop.rooms or 0
                area_value = prop.area or 0
                rooms_text = "Студия" if rooms_count == 0 else f"{rooms_count}"
                
                # Format property name
                if rooms_count == 0:
                    property_name = f"Студия, {area_value} м²"
                else:
                    property_name = f"{rooms_count} комн, {area_value} м²"
                
                # Calculate cashback
                complex_name = prop.residential_complex.name if prop.residential_complex else ''
                cashback_value = calculate_cashback(prop.price or 0, complex_name=complex_name)
                
                property_data = {
                    'property_id': str(prop.inner_id or ''),
                    'property_name': property_name,
                    'property_type': prop.residential_complex.object_class_display_name if prop.residential_complex else 'Квартира',
                    'property_size': float(prop.area or 0),
                    'property_price': int(prop.price or 0),
                    'complex_name': complex_name or '',
                    'developer_name': prop.developer.name if prop.developer else 'Не указан',
                    'property_image': first_image,
                    'property_url': f'/object/{prop.inner_id}' if prop.inner_id else None,
                    'district': prop.district.name if prop.district else '',
                    'address': prop.address or '',
                    'floor': str(prop.floor or ''),
                    'total_floors': str(prop.total_floors or ''),
                    'floors_total': str(prop.total_floors or ''),
                    'rooms': str(rooms_count),
                    'living_area': str(round(prop.living_area, 1)) if prop.living_area else '',
                    'kitchen_area': str(round(prop.kitchen_area, 1)) if prop.kitchen_area else '',
                    'price_per_sqm': int(prop.price_per_sqm or 0) if prop.price_per_sqm else 0,
                    'condition': prop.renovation_type or '',
                    'ceiling_height': '',
                    'furniture': '',
                    'balcony': '',
                    'view_from_windows': '',
                    'parking': '',
                    'metro_distance': '',
                    'year_built': str(prop.residential_complex.end_build_year or '') if prop.residential_complex else '',
                    'building_type': (prop.residential_complex.object_class_display_name if prop.residential_complex and prop.residential_complex.object_class_display_name else ''),
                    'decoration': prop.renovation_type or 'no_renovation',
                    'deal_type': prop.deal_type or 'sale',
                    'mortgage_available': 'Нет',
                    'added_at': 'Загружено из PostgreSQL',
                    'cashback_amount': cashback_value,
                    'cashback': cashback_value
                }
                properties_data.append(property_data)
            
            return jsonify({
                'success': True,
                'properties': properties_data,
                'count': len(properties_data)
            })
            
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/manager/favorites-complexes')
@manager_required
def get_manager_favorite_complexes():
    """Get manager's favorite complexes for comparison"""
    from models import ManagerFavoriteComplex
    
    try:
        current_manager = current_user
        
        # Get all favorite complexes for this manager
        favorites = ManagerFavoriteComplex.query.filter_by(
            manager_id=current_manager.id
        ).order_by(ManagerFavoriteComplex.created_at.desc()).all()
        
        complexes_data = []
        for fav in favorites:
            from models import ResidentialComplex
            rc = ResidentialComplex.query.filter_by(name=fav.complex_name).first()
            if not rc and fav.complex_id:
                try:
                    rc = ResidentialComplex.query.get(int(fav.complex_id))
                except:
                    pass
            
            def format_price(p):
                if not p: return 'По запросу'
                try:
                    return f"{int(p):,}".replace(',', ' ') + ' ₽'
                except:
                    return str(p)

            complexes_data.append({
                'id': fav.id,
                'complex_id': fav.complex_id,
                'complex_name': fav.complex_name,
                'developer_name': fav.developer_name,
                'complex_address': fav.complex_address,
                'district': fav.district,
                'min_price': fav.min_price,
                'max_price': fav.max_price,
                'min_price_formatted': format_price(fav.min_price),
                'max_price_formatted': format_price(fav.max_price),
                'complex_image': fav.complex_image,
                'complex_url': fav.complex_url,
                'added_at': fav.created_at.strftime('%d.%m.%Y %H:%M'),
                'object_class_display_name': fav.object_class_display_name,
                'total_buildings': rc.total_buildings if rc else '-',
                'total_apartments': rc.total_apartments if rc else '-',
            })
        
        return jsonify({
            'success': True,
            'complexes': complexes_data,
            'count': len(complexes_data)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def get_manager_sidebar_data(current_manager, active_page='dashboard'):
    from models import (ManagerFavoriteProperty, ManagerFavoriteComplex,
                        ManagerComparison, ComparisonComplex, ComparisonProperty,
                        Deal, User, Collection)
    total_clients = User.query.filter_by(assigned_manager_id=current_manager.id).count()
    presentations_count = Collection.query.filter_by(
        created_by_manager_id=current_manager.id,
        collection_type='presentation'
    ).count()
    deals_count = Deal.query.filter_by(manager_id=current_manager.id).count()
    manager_favorites_count = ManagerFavoriteProperty.query.filter_by(manager_id=current_manager.id).count()
    manager_complexes_count = ManagerFavoriteComplex.query.filter_by(manager_id=current_manager.id).count()
    manager_comparison_properties = db.session.query(ComparisonProperty).join(
        ManagerComparison, ComparisonProperty.manager_comparison_id == ManagerComparison.id
    ).filter(ManagerComparison.manager_id == current_manager.id).count()
    manager_comparison_complexes = ComparisonComplex.query.join(
        ManagerComparison, ComparisonComplex.manager_comparison_id == ManagerComparison.id
    ).filter(ManagerComparison.manager_id == current_manager.id).count()
    total_favorites = manager_favorites_count + manager_complexes_count
    total_comparison = manager_comparison_properties + manager_comparison_complexes
    dash_url = url_for('mgr.manager_dashboard')
    is_dashboard = (active_page == 'dashboard')
    sidebar_links = [
        {'label': 'На главную', 'href': '/', 'page': 'home', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"/></svg>'},
        {'label': 'Главная', 'href': url_for('mgr.manager_dashboard'), 'page': 'dashboard', 'active': active_page == 'dashboard', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M10 2L3 7v11h3v-6h8v6h3V7l-7-5z"/></svg>'},
        {'label': 'Поиск недвижимости', 'href': '/sochi/kvartiry', 'page': 'search', 'active': active_page == 'search', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>'},
        {'label': 'Клиенты', 'href': '#clients' if is_dashboard else dash_url + '#clients', 'page': 'clients', 'active': active_page == 'clients', 'badge': str(total_clients), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/></svg>'},
        {'label': 'Презентации', 'href': '#presentations' if is_dashboard else dash_url + '#presentations', 'page': 'presentations', 'active': active_page == 'presentations', 'badge': str(presentations_count), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z"/></svg>'},
        {'label': 'Сохраненные поиски', 'href': '#saved-searches' if is_dashboard else dash_url + '#saved-searches', 'page': 'saved-searches', 'active': active_page == 'saved-searches', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>'},
        {'label': 'Избранное', 'href': '#favorites' if is_dashboard else dash_url + '#favorites', 'page': 'favorites', 'active': active_page == 'favorites', 'badge': str(total_favorites), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M3.172 5.172a4 4 0 015.656 0L10 6.343l1.172-1.171a4 4 0 115.656 5.656L10 17.657l-6.828-6.829a4 4 0 010-5.656z" clip-rule="evenodd"/></svg>'},
        {'label': 'Сравнение', 'href': '#comparison' if is_dashboard else dash_url + '#comparison', 'page': 'comparison', 'active': active_page == 'comparison', 'badge': str(total_comparison), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>'},
        {'label': 'Чат', 'href': '#chat' if is_dashboard else dash_url + '#chat', 'page': 'chat', 'active': active_page == 'chat', 'icon': '<svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>'},
        {'label': 'Сделки', 'href': url_for('mgr.manager_deals_kanban'), 'page': 'deals', 'active': active_page == 'deals', 'badge': str(deals_count), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M6 2a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V7.414A2 2 0 0015.414 6L12 2.586A2 2 0 0010.586 2H6zm5 6a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V8z" clip-rule="evenodd"/></svg>'},
        {'label': 'Архив сделок', 'href': url_for('mgr.manager_deals_archive'), 'page': 'deals_archive', 'active': active_page == 'deals_archive', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M4 3a2 2 0 100 4h12a2 2 0 100-4H4z"/><path fill-rule="evenodd" d="M3 8h14v7a2 2 0 01-2 2H5a2 2 0 01-2-2V8zm5 3a1 1 0 011-1h2a1 1 0 110 2H9a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>'},
        {'label': 'Сотрудники', 'href': url_for('mgr.manager_employees'), 'page': 'employees', 'active': active_page == 'employees', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-3a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 15v3h-3zM4.75 12.094A5.973 5.973 0 004 15v3H1v-3a3 3 0 013.75-2.906z"/></svg>'},
    ]
    user_profile = {
        'name': f"{current_manager.first_name} {current_manager.last_name}".strip() or current_manager.email.split('@')[0],
        'role': current_manager.org_role.name if current_manager.org_role else ('РОП' if getattr(current_manager, 'is_rop', False) else 'Менеджер'),
        'initials': current_manager.first_name[0].upper() if current_manager.first_name else current_manager.email[0].upper(),
        'href': url_for('mgr.manager_profile'),
        'avatar': current_manager.profile_image if current_manager.profile_image else None,
    }
    return sidebar_links, user_profile


@mgr_api_bp.route('/api/manager/clients')
@manager_required
def get_manager_clients_unified():
    """Get ONLY assigned clients for this manager"""
    from models import User, SavedSearch
    current_manager = current_user
    
    try:
        print(f"DEBUG: Getting clients for manager {current_manager.id}")
        # Get ALL users assigned to this manager (regardless of role)
        clients = User.query.filter_by(assigned_manager_id=current_manager.id).all()
        print(f"DEBUG: Found {len(clients)} assigned clients for manager {current_manager.id}")
        clients_data = []
        
        for client in clients:
            # Get latest search as preference indicator
            latest_search = SavedSearch.query.filter_by(user_id=client.id).order_by(SavedSearch.last_used.desc()).first()
            
            client_data = {
                'id': client.id,
                'full_name': client.full_name,
                'email': client.email,
                'phone': client.phone or '',
                'profile_image': client.profile_image or '',
                'created_at': client.created_at.isoformat() if client.created_at else None,
                'search_preferences': None,
                'status': 'active'  # Default status
            }
            
            if latest_search:
                # Create readable search description
                prefs = []
                if latest_search.property_type:
                    prefs.append(latest_search.property_type)
                if latest_search.location:
                    prefs.append(f"район {latest_search.location}")
                if latest_search.price_min or latest_search.price_max:
                    price_range = []
                    if latest_search.price_min:
                        price_range.append(f"от {latest_search.price_min:,} ₽")
                    if latest_search.price_max:
                        price_range.append(f"до {latest_search.price_max:,} ₽")
                    prefs.append(" ".join(price_range))
                
                client_data['search_preferences'] = ", ".join(prefs) if prefs else "Поиск сохранен"
            
            clients_data.append(client_data)
        
        print(f"DEBUG: Returning {len(clients_data)} clients data")
        return jsonify({
            'success': True,
            'clients': clients_data
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/update_client_status', methods=['POST'])
@manager_required
def update_client_status():
    from models import User
    
    current_manager = current_user
    
    data = request.get_json()
    client_id = data.get('client_id')
    new_status = data.get('status')
    notes = data.get('notes', '')
    
    client = User.query.get(client_id)
    if not client or client.assigned_manager_id != current_manager.id:
        return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
    
    try:
        client.client_status = new_status
        if notes:
            client.client_notes = notes
        client.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/approve_cashback', methods=['POST'])
@manager_required
def approve_cashback():
    from models import CashbackApplication, Manager
    
    current_manager = current_user
    
    data = request.get_json()
    application_id = data.get('application_id')
    action = data.get('action')  # approve, reject
    manager_notes = data.get('manager_notes', '')
    
    application = CashbackApplication.query.get(application_id)
    if not application:
        return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
    
    # Check if client is assigned to this manager
    if application.user.assigned_manager_id != current_manager.id:
        return jsonify({'success': False, 'error': 'У вас нет доступа к этой заявке'}), 403
    
    try:
        if action == 'approve':
            # Check approval limits
            if current_manager and current_manager.max_cashback_approval and application.cashback_amount > current_manager.max_cashback_approval:
                return jsonify({
                    'success': False, 
                    'error': f'Сумма превышает ваш лимит на одобрение ({current_manager.max_cashback_approval:,} ₽)'
                }), 400
            
            application.status = 'Одобрена'
            application.approved_date = datetime.utcnow()
            application.approved_by_manager_id = current_manager.id
            
        elif action == 'reject':
            application.status = 'Отклонена'
        
        if manager_notes:
            application.manager_notes = manager_notes
        
        application.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/contact-requests')
@manager_required  
def get_manager_contact_requests():
    """Get contact manager applications for current manager"""
    try:
        from models import Application
        
        # Get all manager contact applications
        applications = Application.query.filter_by(
            application_type='manager_contact'
        ).order_by(Application.created_at.desc()).all()
        
        result = []
        for app in applications:
            result.append({
                'id': app.id,
                'contact_name': app.contact_name,
                'contact_email': app.contact_email,
                'contact_phone': app.contact_phone,
                'message': app.message,
                'preferred_contact_time': app.preferred_contact_time,
                'status': app.status,
                'created_at': app.created_at.isoformat() if app.created_at else None,
                'updated_at': app.updated_at.isoformat() if app.updated_at else None,
                # Property context if available
                'property_id': app.property_id,
                'property_type': app.property_type,
                'budget_min': app.budget_min,
                'budget_max': app.budget_max
            })
        
        return jsonify({
            'success': True,
            'applications': result,
            'total': len(result)
        })
        
    except Exception as e:
        print(f"Error getting manager contact requests: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/manager/applications')
@manager_required
def get_manager_applications():
    from models import CashbackApplication, User
    
    current_manager = current_user
    
    applications = CashbackApplication.query.join(User).filter(
        User.assigned_manager_id == current_manager.id,
        CashbackApplication.status == 'На рассмотрении'
    ).all()
    
    applications_data = []
    for app in applications:
        applications_data.append({
            'id': app.id,
            'client_name': app.user.full_name,
            'client_email': app.user.email,
            'property_name': app.property_name,
            'complex_name': app.complex_name,
            'cashback_amount': app.cashback_amount,
            'cashback_percent': app.cashback_percent,
            'application_date': app.application_date.strftime('%d.%m.%Y'),
            'status': app.status
        })
    
    return jsonify({'applications': applications_data})

@mgr_api_bp.route('/api/manager/documents')
@manager_required
def get_manager_documents():
    from models import Document, User
    
    current_manager = current_user
    
    documents = Document.query.join(User).filter(
        User.assigned_manager_id == current_manager.id,
        Document.status == 'На проверке'
    ).all()
    
    documents_data = []
    for doc in documents:
        documents_data.append({
            'id': doc.id,
            'client_name': doc.user.full_name,
            'client_email': doc.user.email,
            'document_type': doc.document_type or 'Не определен',
            'original_filename': doc.original_filename,
            'file_size': doc.file_size,
            'created_at': doc.created_at.strftime('%d.%m.%Y %H:%M'),
            'status': doc.status
        })
    
    return jsonify({'documents': documents_data})

@mgr_api_bp.route('/api/manager/document_action', methods=['POST'])
@manager_required
def manager_document_action():
    from models import Document, Manager
    
    current_manager = current_user
    
    data = request.get_json()
    document_id = data.get('document_id')
    action = data.get('action')  # approve, reject
    notes = data.get('notes', '')
    
    document = Document.query.get(document_id)
    
    if not document:
        return jsonify({'success': False, 'error': 'Документ не найден'}), 404
    
    # Check if client is assigned to this manager
    if document.user.assigned_manager_id != current_manager.id:
        return jsonify({'success': False, 'error': 'У вас нет доступа к этому документу'}), 403
    
    try:
        if action == 'approve':
            document.status = 'Проверен'
        elif action == 'reject':
            document.status = 'Отклонен'
        
        document.reviewed_by_manager_id = current_manager.id
        document.reviewed_at = datetime.utcnow()
        if notes:
            document.reviewer_notes = notes
        
        document.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/application_action', methods=['POST'])
@manager_required
def manager_application_action():
    from models import CashbackApplication, Manager, User
    
    current_manager = current_user
    
    data = request.get_json()
    application_id = data.get('application_id')
    action = data.get('action')  # approve, reject
    notes = data.get('notes', '')
    
    application = CashbackApplication.query.get(application_id)
    
    if not application:
        return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
    
    # Check if client is assigned to this manager
    if application.user.assigned_manager_id != current_manager.id:
        return jsonify({'success': False, 'error': 'У вас нет доступа к этой заявке'}), 403
    
    try:
        if action == 'approve':
            application.status = 'Одобрена'
            # Add cashback to user's balance
            user = application.user
            user.total_cashback = (user.total_cashback or 0) + application.cashback_amount
        elif action == 'reject':
            application.status = 'Отклонена'
        
        application.reviewed_by_manager_id = current_manager.id
        application.reviewed_at = datetime.utcnow()
        if notes:
            application.manager_notes = notes
        
        application.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/collections')
@manager_required
def get_manager_collections():
    from models import Collection, User
    
    current_manager = current_user
    
    collections = Collection.query.filter_by(created_by_manager_id=current_manager.id).all()
    
    collections_data = []
    for collection in collections:
        collections_data.append({
            'id': collection.id,
            'title': collection.title,
            'description': collection.description,
            'status': collection.status,
            'assigned_to_name': collection.assigned_to.full_name if collection.assigned_to else 'Не назначено',
            'assigned_to_id': collection.assigned_to_user_id,
            'properties_count': len(collection.properties),
            'created_at': collection.created_at.strftime('%d.%m.%Y'),
            'tags': collection.tags
        })
    
    return jsonify({'collections': collections_data})

@mgr_api_bp.route('/api/manager/collection/create', methods=['POST'])
@manager_required
def api_create_collection():
    from models import Collection, User
    
    current_manager = current_user
    
    data = request.get_json()
    title = data.get('title')
    description = data.get('description', '')
    assigned_to_user_id = data.get('assigned_to_user_id')
    tags = data.get('tags', '')
    
    if not title:
        return jsonify({'success': False, 'error': 'Название подборки обязательно'}), 400
    
    try:
        collection = Collection()
        collection.title = title
        collection.description = description
        collection.created_by_manager_id = current_manager.id
        collection.assigned_to_user_id = assigned_to_user_id if assigned_to_user_id else None
        collection.tags = tags
        collection.status = 'Черновик'
        
        db.session.add(collection)
        db.session.commit()
        
        return jsonify({'success': True, 'collection_id': collection.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/collection/<int:collection_id>/properties')
@manager_required
def get_collection_properties(collection_id):
    from models import Collection, CollectionProperty
    
    current_manager = current_user
    
    collection = Collection.query.filter_by(
        id=collection_id,
        created_by_manager_id=current_manager.id
    ).first()
    
    if not collection:
        return jsonify({'success': False, 'error': 'Подборка не найдена'}), 404
    
    properties_data = []
    for prop in collection.properties:
        properties_data.append({
            'id': prop.id,
            'property_id': prop.property_id,
            'property_name': prop.property_name,
            'property_price': prop.property_price,
            'complex_name': prop.complex_name,
            'property_type': prop.property_type,
            'property_size': prop.property_size,
            'manager_note': prop.manager_note,
            'order_index': prop.order_index
        })
    
    # Sort by order_index
    properties_data.sort(key=lambda x: x['order_index'])
    
    return jsonify({
        'collection': {
            'id': collection.id,
            'title': collection.title,
            'description': collection.description,
            'status': collection.status
        },
        'properties': properties_data
    })



@mgr_api_bp.route('/api/searches/save', methods=['POST'])
@login_required
def api_save_search():
    """Save a search with filters"""
    from models import SavedSearch
    
    data = request.get_json()
    name = data.get('name')
    filters = data.get('filters', {})
    
    if not name:
        return jsonify({'success': False, 'error': 'Название поиска обязательно'}), 400
    
    try:
        # Get city_id from request or session
        city_id = data.get('city_id') or session.get('city_id') or 1
        
        search = SavedSearch()
        search.name = name
        search.additional_filters = json.dumps(filters)
        search.user_id = current_user.id
        search.city_id = city_id
        search.created_at = datetime.utcnow()
        
        db.session.add(search)
        db.session.commit()
        
        return jsonify({'success': True, 'search_id': search.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/searches', methods=['POST'])
@manager_required
def api_manager_save_search():
    """Save a search for a manager"""
    from models import ManagerSavedSearch, Manager, SentSearch
    
    current_manager = current_user
    
    data = request.get_json()
    name = data.get('name')
    filters = data.get('filters', {})
    client_email = data.get('client_email', '')
    
    if not name:
        return jsonify({'success': False, 'error': 'Название поиска обязательно'}), 400
    
    try:
        # Create saved search
        search = ManagerSavedSearch()
        search.name = name
        search.additional_filters = json.dumps(filters)
        search.manager_id = current_manager.id
        search.created_at = datetime.utcnow()
        
        db.session.add(search)
        db.session.commit()
        
        # If client email provided, also create sent search record and send notification
        if client_email:
            sent_search = SentSearch()
            sent_search.saved_search_id = search.id
            sent_search.recipient_email = client_email
            sent_search.sent_at = datetime.utcnow()
            sent_search.manager_id = current_manager.id
            
            db.session.add(sent_search)
            db.session.commit()
            
            # Send notification to client
            manager_name = current_manager.name if current_manager else "Менеджер"
            
            try:
                send_notification(
                    recipient_email=client_email,
                    subject=f"Новый подбор недвижимости от {manager_name}",
                    message=f"Менеджер {manager_name} подготовил для вас персональный подбор недвижимости '{name}'. Посмотрите варианты на сайте InBack.ru",
                    notification_type='saved_search',
                    user_id=None,
                    manager_id=current_manager.id
                )
                return jsonify({'success': True, 'search_id': search.id, 'sent_to_client': True})
            except Exception as email_error:
                print(f"Failed to send email notification: {email_error}")
                return jsonify({'success': True, 'search_id': search.id, 'sent_to_client': False, 'email_error': str(email_error)})
        
        return jsonify({'success': True, 'search_id': search.id, 'sent_to_client': False})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/send_recommendation', methods=['POST'])
@manager_required
def api_manager_send_recommendation():
    """Send a recommendation (property or complex) to a client"""
    from models import Recommendation, Manager, User, RecommendationCategory
    from datetime import datetime
    
    current_manager = current_user
    
    data = request.get_json()
    title = data.get('title', '').strip()
    client_id = data.get('client_id')  # Now using client_id instead of email
    client_email = data.get('client_email', '').strip()
    recommendation_type = data.get('recommendation_type')  # 'property' or 'complex'
    item_id = data.get('item_id')
    item_name = data.get('item_name', '').strip()
    description = data.get('description', '').strip()
    manager_notes = data.get('manager_notes', '').strip()
    highlighted_features = data.get('highlighted_features', [])
    priority_level = data.get('priority_level', 'normal')
    category_id = data.get('category_id')  # New field for category
    category_name = data.get('category_name', '').strip()  # For creating new category
    
    # Debug logging (removing verbose logs for production)
    print(f"DEBUG: Recommendation sent - type={recommendation_type}, item_id={item_id}, client_id={client_id}")
    
    # Validation
    missing_fields = []
    if not title:
        missing_fields.append('заголовок')
    if not client_id:
        missing_fields.append('клиент')
    if not recommendation_type:
        missing_fields.append('тип рекомендации')
    if not item_id:
        missing_fields.append('ID объекта')
    if not item_name:
        missing_fields.append('название объекта')
    
    if missing_fields:
        return jsonify({'success': False, 'error': f'Заполните обязательные поля: {", ".join(missing_fields)}'}), 400
    
    if recommendation_type not in ['property', 'complex']:
        return jsonify({'success': False, 'error': 'Неверный тип рекомендации'}), 400
    
    try:
        # Find client by ID
        client = User.query.get(client_id)
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 400
        
        # Handle category
        category = None
        if category_id == 'new' and category_name:
            # Create new category
            category = RecommendationCategory(
                name=category_name,
                manager_id=current_manager.id,
                client_id=client_id
            )
            db.session.add(category)
            db.session.flush()  # To get the ID
        elif category_id and category_id != 'new':
            # Use existing category
            category = RecommendationCategory.query.filter_by(
                id=category_id,
                manager_id=current_manager.id,
                client_id=client_id,
                is_active=True
            ).first()
        
        # Create recommendation
        recommendation = Recommendation()
        recommendation.manager_id = current_manager.id
        recommendation.client_id = client.id
        recommendation.title = title
        recommendation.description = description
        recommendation.recommendation_type = recommendation_type
        recommendation.item_id = item_id
        recommendation.item_name = item_name
        recommendation.manager_notes = manager_notes
        recommendation.highlighted_features = json.dumps(highlighted_features) if highlighted_features else None
        recommendation.priority_level = priority_level
        recommendation.item_data = json.dumps(data.get('item_data', {}))  # Store full item details
        recommendation.category_id = category.id if category else None
        
        db.session.add(recommendation)
        
        # Update category statistics
        if category:
            category.recommendations_count += 1
            category.last_used = datetime.utcnow()
        
        db.session.commit()
        
        # Send notification to client
        manager = Manager.query.get(manager_id)
        manager_name = manager.name if manager else "Менеджер"
        
        try:
            # Get priority text for notifications
            priority_texts = {
                'urgent': 'Срочно',
                'high': 'Высокий', 
                'normal': 'Обычный'
            }
            priority_text = priority_texts.get(priority_level, 'Обычный')
            
            send_notification(
                recipient_email=client_email,
                subject=f"Новая рекомендация от {manager_name}",
                message=f"Менеджер {manager_name} рекомендует вам: {title}",
                notification_type='recommendation',
                user_id=client.id,
                manager_id=current_manager.id,
                title=title,
                item_id=item_id,
                item_name=item_name,
                description=description,
                manager_name=manager_name,
                priority_text=priority_text,
                recommendation_type=recommendation_type
            )
            return jsonify({'success': True, 'recommendation_id': recommendation.id, 'sent_to_client': True})
        except Exception as email_error:
            print(f"Failed to send email notification: {email_error}")
            return jsonify({'success': True, 'recommendation_id': recommendation.id, 'sent_to_client': False, 'email_error': str(email_error)})
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error creating recommendation: {str(e)}")
        print(f"Full traceback: {error_trace}")
        return jsonify({'success': False, 'error': str(e), 'traceback': error_trace}), 400

@mgr_api_bp.route('/api/manager/recommendations', methods=['GET'])
@manager_required
def api_manager_get_recommendations():
    """Get manager's sent recommendations with filters"""
    from models import Recommendation
    
    current_manager = current_user
    
    try:
        # Start with base query
        query = Recommendation.query.filter_by(manager_id=current_manager.id)
        
        # Apply filters from request params
        client_id = request.args.get('client_id')
        status = request.args.get('status')
        rec_type = request.args.get('type')
        priority = request.args.get('priority')
        
        if client_id:
            query = query.filter(Recommendation.client_id == client_id)
        if status:
            query = query.filter(Recommendation.status == status)
        if rec_type:
            query = query.filter(Recommendation.item_type == rec_type)
        if priority:
            query = query.filter(Recommendation.priority == priority)
        
        recommendations = query.order_by(Recommendation.sent_at.desc()).all()
        
        recommendations_data = []
        stats = {'sent': 0, 'viewed': 0, 'interested': 0, 'scheduled': 0}
        
        for rec in recommendations:
            rec_dict = rec.to_dict()
            rec_dict['client_email'] = rec.client.email
            rec_dict['client_name'] = rec.client.full_name
            recommendations_data.append(rec_dict)
            
            # Update stats
            stats['sent'] += 1
            if rec.status == 'viewed':
                stats['viewed'] += 1
            elif rec.status == 'interested':
                stats['interested'] += 1
            elif rec.status == 'scheduled_viewing':
                stats['scheduled'] += 1
        
        return jsonify({
            'success': True, 
            'recommendations': recommendations_data,
            'stats': stats
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/recommendations/<int:recommendation_id>', methods=['DELETE'])
@manager_required  
def api_manager_delete_recommendation(recommendation_id):
    """Delete a recommendation"""
    from models import Recommendation
    
    current_manager = current_user
    
    try:
        # Find recommendation that belongs to this manager
        recommendation = Recommendation.query.filter_by(
            id=recommendation_id, 
            manager_id=current_manager.id
        ).first()
        
        if not recommendation:
            return jsonify({'success': False, 'error': 'Рекомендация не найдена'}), 404
        
        db.session.delete(recommendation)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Рекомендация успешно удалена'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/manager/clients-list', methods=['GET'])
@manager_required
def api_manager_get_clients_list():
    """Get manager's clients for filters"""
    from models import User
    
    current_manager = current_user
    
    try:
        # Get clients assigned to this manager or all buyers
        clients = User.query.filter_by(role='buyer').order_by(User.full_name).all()
        
        clients_data = []
        for client in clients:
            clients_data.append({
                'id': client.id,
                'full_name': client.full_name or 'Без имени',
                'email': client.email
            })
        
        return jsonify({
            'success': True,
            'clients': clients_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/properties/search', methods=['POST'])
@login_required
def api_search_properties():
    """Search properties with filters from dashboard"""
    data = request.get_json()
    filters = data.get('filters', {})
    
    try:
        # Convert collection filters to property filters
        property_filters = {}
        
        if filters.get('priceFrom'):
            property_filters['price_min'] = filters['priceFrom']
        if filters.get('priceTo'):
            property_filters['price_max'] = filters['priceTo']
        if filters.get('rooms'):
            property_filters['rooms'] = filters['rooms']
        if filters.get('districts') and filters['districts']:
            property_filters['district'] = filters['districts'][0]
        if filters.get('developers') and filters['developers']:
            property_filters['developer'] = filters['developers'][0]
        if filters.get('areaFrom'):
            property_filters['area_min'] = filters['areaFrom']
        if filters.get('areaTo'):
            property_filters['area_max'] = filters['areaTo']
        
        # Get filtered properties
        filtered_properties = get_filtered_properties(property_filters)
        
        # Add cashback to each property
        for prop in filtered_properties:
            prop['cashback'] = calculate_cashback(
                prop['price'],
                complex_id=prop.get('complex_id'),
                complex_name=prop.get('residential_complex')
            )
        
        # Sort by price ascending
        filtered_properties = sort_properties(filtered_properties, 'price_asc')
        
        return jsonify({
            'success': True,
            'properties': filtered_properties[:50],  # Limit to 50 results
            'total_count': len(filtered_properties)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/send-property', methods=['POST'])
@manager_required
def api_send_property_to_client():
    """Send saved search results to client via email"""
    from models import SavedSearch, User, ClientPropertyRecommendation
    
    data = request.get_json()
    client_id = data.get('client_id')
    search_id = data.get('search_id')
    message = data.get('message', '')
    
    if not client_id or not search_id:
        return jsonify({'success': False, 'error': 'Клиент и поиск обязательны'}), 400
    
    try:
        # Get the search
        search = SavedSearch.query.get(search_id)
        if not search:
            return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
        
        # Get the client
        client = User.query.get(client_id)
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
        
        # Get search filters
        filters = json.loads(search.filters) if search.filters else {}
        
        # Filter properties based on search criteria
        properties = load_properties()
        filtered_properties = filter_properties(properties, filters)
        
        # Create recommendation record
        recommendation = ClientPropertyRecommendation()
        recommendation.client_id = client_id
        recommendation.manager_id = current_user.id
        recommendation.search_name = search.name
        recommendation.search_filters = search.filters
        recommendation.message = message
        recommendation.properties_count = len(filtered_properties)
        recommendation.sent_at = datetime.utcnow()
        
        db.session.add(recommendation)
        db.session.commit()
        
        # Send email with property recommendations
        send_property_email(client, search.name, filtered_properties, message)
        
        return jsonify({'success': True, 'properties_sent': len(filtered_properties)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

def filter_properties(properties, filters):
    """Filter properties based on search criteria"""
    filtered = []
    
    for prop in properties:
        # Price filter
        if filters.get('priceFrom'):
            try:
                if prop.get('price', 0) < int(filters['priceFrom']):
                    continue
            except (ValueError, TypeError):
                pass
        
        if filters.get('priceTo'):
            try:
                if prop.get('price', 0) > int(filters['priceTo']):
                    continue
            except (ValueError, TypeError):
                pass
        
        # Rooms filter
        if filters.get('rooms'):
            prop_rooms = str(prop.get('rooms', ''))
            if filters['rooms'] == 'studio' and prop_rooms != 'studio':
                continue
            elif filters['rooms'] != 'studio' and prop_rooms != str(filters['rooms']):
                continue
        
        # District filter
        if filters.get('districts') and len(filters['districts']) > 0:
            prop_district = prop.get('district', '')
            if prop_district not in filters['districts']:
                continue
        
        # Area filter
        if filters.get('areaFrom'):
            try:
                if prop.get('area', 0) < int(filters['areaFrom']):
                    continue
            except (ValueError, TypeError):
                pass
        
        if filters.get('areaTo'):
            try:
                if prop.get('area', 0) > int(filters['areaTo']):
                    continue
            except (ValueError, TypeError):
                pass
        
        # Developer filter
        if filters.get('developers') and len(filters['developers']) > 0:
            prop_developer = prop.get('developer', '')
            if prop_developer not in filters['developers']:
                continue
        
        filtered.append(prop)
    
    return filtered

def send_property_email(client, search_name, properties, message):
    """Send email with property recommendations"""
    try:
        subject = f"Новая подборка недвижимости: {search_name}"
        
        properties_html = ""
        for prop in properties[:10]:  # Limit to first 10 properties
            properties_html += f"""
            <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <h3 style="margin: 0 0 8px 0; color: #1f2937;">{prop.get('name', 'Без названия')}</h3>
                <p style="margin: 0 0 4px 0; color: #6b7280;">ЖК: {prop.get('complex_name', 'Не указан')}</p>
                <p style="margin: 0 0 4px 0; color: #6b7280;">Цена: {prop.get('price', 0):,} ₽</p>
                <p style="margin: 0 0 4px 0; color: #6b7280;">Площадь: {prop.get('area', 0)} м²</p>
                <p style="margin: 0 0 8px 0; color: #6b7280;">Комнат: {prop.get('rooms', 'Не указано')}</p>
                <a href="https://inback.ru/properties/{prop.get('id', '')}" style="color: #0088cc; text-decoration: none;">Подробнее →</a>
            </div>
            """
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #0088cc;">Персональная подборка недвижимости</h2>
                
                <p>Здравствуйте, {client.full_name}!</p>
                
                <p>Ваш менеджер подготовил для вас подборку недвижимости: <strong>{search_name}</strong></p>
                
                {f'<div style="background: #f3f4f6; padding: 16px; border-radius: 8px; margin: 16px 0;"><p style="margin: 0; font-style: italic;">"{message}"</p></div>' if message else ''}
                
                <h3>Найденные варианты ({len(properties)} объектов):</h3>
                
                {properties_html}
                
                {f'<p style="color: #6b7280;">И еще {len(properties) - 10} объектов в полном каталоге...</p>' if len(properties) > 10 else ''}
                
                <div style="margin-top: 32px; padding: 20px; background: #f9fafb; border-radius: 8px; text-align: center;">
                    <h3 style="margin: 0 0 8px 0;">Нужна консультация?</h3>
                    <p style="margin: 0 0 16px 0;">Свяжитесь с вашим персональным менеджером</p>
                    <a href="mailto:manager@inback.ru" style="background: #0088cc; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Написать менеджеру</a>
                </div>
                
                <div style="margin-top: 20px; text-align: center; color: #6b7280; font-size: 14px;">
                    <p>С уважением,<br>Команда InBack.ru</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return send_notification(
            client.email,
            subject,
            html_content,
            notification_type="property_recommendation",
            user_id=client.id
        )
    except Exception as e:
        print(f"Error sending property email: {e}")
        return False

@mgr_api_bp.route('/api/manager/collection/<int:collection_id>/add_property', methods=['POST'])
@manager_required
def add_property_to_collection(collection_id):
    from models import Collection, CollectionProperty
    import json
    
    current_manager = current_user
    
    data = request.get_json()
    property_id = data.get('property_id')
    manager_note = data.get('manager_note', '')
    
    collection = Collection.query.filter_by(
        id=collection_id,
        created_by_manager_id=current_manager.id
    ).first()
    
    if not collection:
        return jsonify({'success': False, 'error': 'Подборка не найдена'}), 404
    
    # Load property data from JSON
    try:
        with open('data/properties.json', 'r', encoding='utf-8') as f:
            properties_data = json.load(f)
        
        property_info = None
        for prop in properties_data:
            if str(prop['id']) == str(property_id):
                property_info = prop
                break
        
        if not property_info:
            return jsonify({'success': False, 'error': 'Квартира не найдена'}), 404
        
        # Check if property already in collection
        existing = CollectionProperty.query.filter_by(
            collection_id=collection_id,
            property_id=str(property_id)
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Квартира уже добавлена в подборку'}), 400
        
        # Get max order_index
        max_order = db.session.query(db.func.max(CollectionProperty.order_index)).filter_by(
            collection_id=collection_id
        ).scalar() or 0
        
        # DUAL WRITE: Get Property object to access both database ID and inner_id
        from models import Property as PropertyModel
        property_obj, canonical_id = resolve_property_by_identifier(property_id)
        if not property_obj:
            return jsonify({'success': False, 'error': 'Объект не найден в базе данных'}), 404
        
        collection_property = CollectionProperty()
        collection_property.collection_id = collection_id
        collection_property.property_id = str(property_obj.id)  # Old: database ID
        collection_property.property_inner_id = property_obj.inner_id  # NEW: canonical inner_id
        collection_property.property_name = property_info['title']
        collection_property.property_price = property_info['price']
        collection_property.complex_name = property_info.get('residential_complex', 'ЖК не указан')
        collection_property.property_type = f"{property_info['rooms']}-комн"
        collection_property.property_size = property_info['area']
        collection_property.manager_note = manager_note
        collection_property.order_index = max_order + 1
        
        db.session.add(collection_property)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/collection/<int:collection_id>/send', methods=['POST'])
@manager_required
def send_collection(collection_id):
    from models import Collection
    
    current_manager = current_user
    
    collection = Collection.query.filter_by(
        id=collection_id,
        created_by_manager_id=current_manager.id
    ).first()
    
    if not collection:
        return jsonify({'success': False, 'error': 'Подборка не найдена'}), 404
    
    if not collection.assigned_to_user_id:
        return jsonify({'success': False, 'error': 'Клиент не назначен'}), 400
    
    if len(collection.properties) == 0:
        return jsonify({'success': False, 'error': 'В подборке нет квартир'}), 400
    
    try:
        collection.status = 'Отправлена'
        collection.sent_at = datetime.utcnow()
        collection.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/properties/search')
@manager_required
def search_properties():
    """Search properties using normalized tables"""
    from repositories.property_repository import PropertyRepository
    
    query = request.args.get('q', '').lower()
    limit = int(request.args.get('limit', 20))
    
    try:
        properties = PropertyRepository.get_all_active(limit=limit * 3)
        
        filtered_properties = []
        for prop in properties:
            prop_type = f"{prop.rooms}-комн" if prop.rooms > 0 else "Студия"
            complex_name = prop.residential_complex.name if prop.residential_complex else 'ЖК не указан'
            developer_name = prop.developer.name if prop.developer else ''
            district_name = prop.residential_complex.district if prop.residential_complex else ''
            
            property_title = f"{prop.rooms}-комн {prop.area} м²" if prop.rooms > 0 else f"Студия {prop.area} м²"
            
            if (query in property_title.lower() or 
                query in complex_name.lower() or 
                query in prop_type.lower() or
                query in developer_name.lower() or
                query in district_name.lower()):
                
                photos_list = []
                if prop.gallery_images:
                    try:
                        if isinstance(prop.gallery_images, list):
                            photos_list = prop.gallery_images
                        elif isinstance(prop.gallery_images, str):
                            photos_list = json.loads(prop.gallery_images)
                    except:
                        pass
                
                main_image = prop.main_image or (photos_list[0] if photos_list else '/static/images/property-placeholder.jpg')
                
                filtered_properties.append({
                    'id': prop.inner_id or prop.id,
                    'title': property_title,
                    'price': prop.price or 0,
                    'complex': complex_name,
                    'type': prop_type,
                    'size': prop.area or 0,
                    'image': main_image
                })
            
            if len(filtered_properties) >= limit:
                break
        
        return jsonify({'properties': filtered_properties})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/client/collections')
@login_required
def get_client_collections():
    """Get collections assigned to current user"""
    from models import Collection, CollectionProperty
    from datetime import datetime
    
    user_id = current_user.id
    
    collections = Collection.query.filter_by(assigned_to_user_id=user_id).all()
    
    collections_data = []
    for collection in collections:
        properties_count = len(collection.properties)
        
        # Mark as viewed if not already
        if collection.status == 'Отправлена':
            collection.status = 'Просмотрена'
            collection.viewed_at = datetime.utcnow()
            db.session.commit()
        
        collections_data.append({
            'id': collection.id,
            'title': collection.title,
            'description': collection.description,
            'status': collection.status,
            'created_by_manager_name': collection.created_by.full_name,
            'properties_count': properties_count,
            'created_at': collection.created_at.strftime('%d.%m.%Y'),
            'sent_at': collection.sent_at.strftime('%d.%m.%Y %H:%M') if collection.sent_at else None,
            'tags': collection.tags
        })
    
    return jsonify({'success': True, 'collections': collections_data})

@mgr_api_bp.route('/api/client/collection/<int:collection_id>/properties')
@login_required
def get_client_collection_properties(collection_id):
    """Get properties in a collection for client view"""
    from models import Collection, CollectionProperty
    
    user_id = current_user.id
    
    collection = Collection.query.filter_by(
        id=collection_id,
        assigned_to_user_id=user_id
    ).first()
    
    if not collection:
        return jsonify({'success': False, 'error': 'Подборка не найдена'}), 404
    
    properties_data = []
    for prop in collection.properties:
        # Calculate potential cashback (example: 2% of price)
        cashback_percent = 2.0
        cashback_amount = int(prop.property_price * cashback_percent / 100)
        
        properties_data.append({
            'id': prop.id,
            'property_id': prop.property_id,
            'property_name': prop.property_name,
            'property_price': prop.property_price,
            'complex_name': prop.complex_name,
            'property_type': prop.property_type,
            'property_size': prop.property_size,
            'manager_note': prop.manager_note,
            'cashback_amount': cashback_amount,
            'cashback_percent': cashback_percent
        })
    
    # Sort by order_index
    properties_data.sort(key=lambda x: collection.properties[0].order_index if collection.properties else 0)
    
    return jsonify({
        'collection': {
            'id': collection.id,
            'title': collection.title,
            'description': collection.description,
            'status': collection.status,
            'manager_name': collection.created_by.full_name,
            'sent_at': collection.sent_at.strftime('%d.%m.%Y %H:%M') if collection.sent_at else None
        },
        'properties': properties_data
    })

@mgr_api_bp.route('/api/user/referrals')
@login_required
def get_user_referrals():
    from models import Referral
    try:
        if not current_user.referral_code:
            current_user.referral_code = current_user.generate_referral_code()
            db.session.commit()
        referrals = Referral.query.filter_by(referrer_id=current_user.id).order_by(Referral.created_at.desc()).all()
        # Только зачисленные бонусы считаются как заработанные
        total_earned = sum(r.bonus_amount for r in referrals if r.status == 'credited')
        total_pending = sum(r.bonus_amount for r in referrals if r.status == 'pending')
        return jsonify({
            'success': True,
            'referral_code': current_user.referral_code,
            'referral_link': f"{request.host_url.rstrip('/')}?ref={current_user.referral_code}",
            'total_referrals': len(referrals),
            'total_earned': float(total_earned),
            'total_pending': float(total_pending),
            'referrals': [{
                'id': r.id,
                'referred_name': (r.referred.full_name or 'Новый пользователь') if r.referred else 'Удалённый пользователь',
                'referred_phone': (r.referred.phone[:7] + '***' + r.referred.phone[-2:]) if r.referred and r.referred.phone else '',
                'bonus_amount': float(r.bonus_amount),
                'status': r.status,
                'credited_at': r.bonus_credited_at.strftime('%d.%m.%Y') if r.bonus_credited_at else None,
                'created_at': r.created_at.strftime('%d.%m.%Y')
            } for r in referrals]
        })
    except Exception as e:
        logging.error(f"Error in get_user_referrals: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# PARTNER SYSTEM ROUTES
# ============================================================================

@mgr_api_bp.route('/dashboard', endpoint='dashboard')
@login_required
def dashboard():
    """User dashboard - ИСПРАВЛЕНО: редиректит админов и менеджеров"""
    from models import Admin, Manager
    
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем тип пользователя
    # Админы и менеджеры НЕ должны попадать в пользовательский dashboard
    if isinstance(current_user._get_current_object(), Admin):
        return redirect(url_for('adm.admin_dashboard'))
    elif isinstance(current_user._get_current_object(), Manager):
        return redirect(url_for('mgr.manager_dashboard'))
    
    try:
        from models import CashbackApplication, FavoriteProperty, FavoriteComplex, Document, Collection, Recommendation, SentSearch, SavedSearch, UserActivity, Deal, UserBalance, BalanceTransaction
        
        # Ensure user balance exists
        try:
            user_balance = UserBalance.query.filter_by(user_id=current_user.id).first()
            if not user_balance:
                user_balance = UserBalance(user_id=current_user.id)
                db.session.add(user_balance)
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Database error ensuring balance for user {current_user.id}: {str(e)}")
            # Fallback for broken schema in some environments
            user_balance = type('obj', (object,), {
                'available_amount': Decimal('0.00'),
                'pending_amount': Decimal('0.00'),
                'total_earned': Decimal('0.00'),
                'total_withdrawn': Decimal('0.00'),
                'balance': Decimal('0.00'),
                'pending_balance': Decimal('0.00')
            })

        # Get user's data for dashboard
        cashback_apps = CashbackApplication.query.filter_by(user_id=current_user.id).all()
        favorites = FavoriteProperty.query.filter_by(user_id=current_user.id).all()
        complex_favorites = FavoriteComplex.query.filter_by(user_id=current_user.id).all()
        documents = Document.query.filter_by(user_id=current_user.id).all()
        collections = Collection.query.filter_by(assigned_to_user_id=current_user.id).order_by(Collection.created_at.desc()).all()
        
        # Get user's deals (сделки созданные менеджером для этого клиента)
        deals = Deal.query.filter_by(client_id=current_user.id).order_by(Deal.created_at.desc()).all()
        
        # Get recommendations from managers (exclude dismissed) with categories
        recommendations = Recommendation.query.filter(
            Recommendation.client_id == current_user.id,
            Recommendation.status != 'dismissed'
        ).options(db.joinedload(Recommendation.category)).order_by(Recommendation.created_at.desc()).all()
        
        # Get unique categories for the client (import here to avoid circular imports)
        from models import RecommendationCategory
        categories = RecommendationCategory.query.filter_by(client_id=current_user.id, is_active=True).all()
        
        # ОПТИМИЗАЦИЯ: Загружаем только нужные properties для recommendations из БД
        from models import Property, ResidentialComplex
        
        # Получаем ID нужных объектов
        property_ids = [rec.item_id for rec in recommendations if rec.recommendation_type == 'property' and rec.item_id]
        
        # Загружаем только нужные properties с JOIN (одним запросом!)
        properties_dict = {}
        if property_ids:
            properties_query = db.session.query(
                Property,
                ResidentialComplex.name.label('complex_name')
            ).outerjoin(
                ResidentialComplex, Property.complex_id == ResidentialComplex.id
            ).filter(
                Property.inner_id.in_(property_ids),
                Property.is_active == True
            ).all()
            
            for prop, complex_name in properties_query:
                properties_dict[prop.inner_id] = {
                    'id': str(prop.id),
                    'rooms': prop.rooms,
                    'area': prop.area,
                    'floor': prop.floor,
                    'total_floors': prop.total_floors,
                    'price': prop.price,
                    'main_image': prop.main_image,
                    'complex_name': complex_name,
                    'property_type': 'apartment',
                    'property_type_ru': 'Квартира'
                }
        
        # Enrich recommendations with property details
        for rec in recommendations:
            if rec.recommendation_type == 'property' and rec.item_id:
                try:
                    property_data = properties_dict.get(rec.item_id)
                    if property_data:
                        # Create a simple object to store property details
                        class PropertyDetails:
                            def __init__(self, data):
                                for key, value in data.items():
                                    setattr(self, key, value)
                                self.residential_complex = data.get('complex_name', 'Не указан')
                        
                        rec.property_details = PropertyDetails(property_data)
                        print(f"✅ Loaded property {rec.item_id}: {property_data.get('rooms')} комн, ЖК {property_data.get('complex_name')}")
                    else:
                        print(f"Property {rec.item_id} not found in database")
                        rec.property_details = None
                except Exception as e:
                    print(f"Error loading property details for recommendation {rec.id}: {e}")
                    rec.property_details = None
        
        # Get sent searches from managers
        sent_searches = SentSearch.query.filter_by(client_id=current_user.id).order_by(SentSearch.sent_at.desc()).all()
        
        # Get user's saved searches
        saved_searches = SavedSearch.query.filter_by(user_id=current_user.id).order_by(SavedSearch.created_at.desc()).all()
        
        # Calculate totals from DEALS (сделки от менеджеров - это реальные данные!)
        # Используем Decimal для точности!
        from decimal import Decimal
        
        # Выплаченный кешбек = сделки со статусом "completed"
        total_cashback = sum((deal.cashback_amount for deal in deals if deal.status in ('completed', 'successful')), Decimal('0'))
        
        # В обработке = сделки со статусами new, reserved, mortgage (все кроме completed и rejected)
        pending_cashback = sum((deal.cashback_amount for deal in deals if deal.status in ['new', 'reserved', 'mortgage']), Decimal('0'))
        
        # Количество активных сделок (все кроме completed и rejected)
        active_apps = len([deal for deal in deals if deal.status not in ['completed', 'successful', 'rejected']])
        
        # Также показываем количество заявок на кешбек (старая система)
        cashback_applications_count = len(cashback_apps)
        cashback_apps_pending = len([app for app in cashback_apps if app.status in ['На рассмотрении', 'Требуются документы']])
        
        # Get developer appointments
        from models import DeveloperAppointment, BalanceTransaction
        appointments = DeveloperAppointment.query.filter_by(user_id=current_user.id).order_by(DeveloperAppointment.appointment_date.desc()).limit(3).all()
        
        # Load data for manager filters
        districts = get_districts_list()
        developers = get_developers_list()
        
        # Get recent user activities
        recent_activities = UserActivity.get_recent_activities(current_user.id, limit=5)
        
        # Load balance data
        # ✅ ИСПРАВЛЕНО: Используем available_amount из UserBalance, а не общий balance
        user_balance_obj = UserBalance.query.filter_by(user_id=current_user.id).first()
        user_balance = float(user_balance_obj.available_amount) if user_balance_obj else 0
        balance_transactions = BalanceTransaction.query.filter_by(user_id=current_user.id).order_by(BalanceTransaction.created_at.desc()).limit(10).all()

        # Load comparison data (properties and complexes)
        from models import ComparisonProperty, ComparisonComplex, Property, UserComparison
        comparison_properties_count = db.session.query(ComparisonProperty).join(
            UserComparison, ComparisonProperty.user_comparison_id == UserComparison.id
        ).filter(UserComparison.user_id == current_user.id).count()
        
        comparison_complexes_count = db.session.query(ComparisonComplex).join(
            UserComparison, ComparisonComplex.user_comparison_id == UserComparison.id
        ).filter(UserComparison.user_id == current_user.id).count()
        
        total_comparison = comparison_properties_count + comparison_complexes_count
        
        # Load favorites with join to Property to exclude orphaned records
        favorites_with_properties = db.session.query(FavoriteProperty).join(
            Property, Property.inner_id == FavoriteProperty.property_id
        ).filter(
            FavoriteProperty.user_id == current_user.id,
            Property.is_active == True
        ).all()

        
        # Query complex favorites
        favorites_complexes = FavoriteComplex.query.filter_by(user_id=current_user.id).all()
        # Count collections (presentations) assigned to user
        collections_count = Collection.query.filter_by(assigned_to_user_id=current_user.id).count()

        # Sidebar links для покупателя
        sidebar_links = [
            {'label': 'Главная', 'href': '#dashboard', 'page': 'dashboard', 'active': True, 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"/></svg>'},
            {'label': 'Сделки', 'href': '#deals', 'page': 'deals', 'badge': str(len(deals)) if deals else '0', 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3z"/></svg>'},
            {'label': 'Рекомендации', 'href': '#recommendations', 'page': 'recommendations', 'badge': str(collections_count) if collections_count else '0', 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg>'},
            {'label': 'Баланс', 'href': '#balance', 'page': 'balance', 'badge': '{:,.0f}'.format(user_balance).replace(',', ' ') + ' ₽' if user_balance else '0 ₽', 'badge_color': 'balance', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M4 4a2 2 0 00-2 2v1h16V6a2 2 0 00-2-2H4z"/><path fill-rule="evenodd" d="M18 9H2v5a2 2 0 002 2h12a2 2 0 002-2V9zM4 13a1 1 0 011-1h1a1 1 0 110 2H5a1 1 0 01-1-1zm5-1a1 1 0 100 2h1a1 1 0 100-2H9z" clip-rule="evenodd"/></svg>'},
            {'label': 'Настройки', 'href': '#settings', 'page': 'settings', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd"/></svg>'}
        ]
        user_profile = {
            'name': current_user.full_name if (hasattr(current_user, 'full_name') and current_user.full_name) else (current_user.email.split('@')[0] if current_user.email and '@' in current_user.email else current_user.email[:15] if current_user.email else current_user.phone if hasattr(current_user, 'phone') and current_user.phone else 'Пользователь'), 
            'role': 'Покупатель', 
            'initials': current_user.full_name[0].upper() if (hasattr(current_user, 'full_name') and current_user.full_name) else (current_user.email[0].upper() if current_user.email else 'U'), 
            'href': url_for('auth.profile'), 
            'avatar': current_user.profile_image if hasattr(current_user, 'profile_image') and current_user.profile_image and 'randomuser.me' not in str(current_user.profile_image) else None
        }
        
        
        # Get assigned manager info for settings tab
        
        # Calculate profile completion percentage
        profile_fields = {
            'full_name': bool(current_user.full_name),
            'phone': bool(current_user.phone),
            'email': bool(current_user.email),
            'avatar': bool(current_user.profile_image and 'randomuser.me' not in (current_user.profile_image or '')),
            'date_of_birth': bool(getattr(current_user, 'date_of_birth', None)),
        }
        profile_completion = int(sum(profile_fields.values()) / len(profile_fields) * 100)
        profile_missing_fields = [k for k, v in profile_fields.items() if not v]
        
        assigned_manager = None
        mgr_is_online = False
        if current_user.assigned_manager_id:
            assigned_manager = Manager.query.get(current_user.assigned_manager_id)
            if assigned_manager:
                from models import ManagerCheckin
                from datetime import datetime, timedelta
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                checkin = ManagerCheckin.query.filter(
                    ManagerCheckin.manager_id == assigned_manager.id,
                    ManagerCheckin.check_in_time >= today_start
                ).order_by(ManagerCheckin.check_in_time.desc()).first()
                mgr_is_online = checkin is not None and checkin.check_out_time is None
        return render_template('auth/dashboard.html', 
                             cashback_applications=cashback_apps,
                             favorites=favorites,
                             complex_favorites=complex_favorites,
                             documents=documents,
                             collections=collections,
                             appointments=appointments,
                             recommendations=recommendations,
                             categories=categories,
                             sent_searches=sent_searches,
                             saved_searches=saved_searches,
                             deals=deals,
                             total_cashback=total_cashback,
                             pending_cashback=pending_cashback,
                             active_apps=active_apps,
                             districts=districts,
                             developers=developers,
                             recent_activities=recent_activities,
                             sidebar_links=sidebar_links,
                             user_profile=user_profile,
                             user_balance=user_balance,
                             balance=user_balance,
                             balance_transactions=balance_transactions,
                             assigned_manager=assigned_manager,
                             mgr_is_online=mgr_is_online,
                             profile_completion=profile_completion,
                             profile_missing_fields=profile_missing_fields)
    except Exception as e:
        print(f"Dashboard error: {str(e)}")
        import traceback
        traceback.print_exc()
        # Return basic dashboard on error
        districts = get_districts_list()
        developers = get_developers_list()
        
        return render_template('auth/dashboard.html', 
                             cashback_applications=[],
                             favorites=[],
                             complex_favorites=[],
                             documents=[],
                             collections=[],
                             appointments=[],
                             recommendations=[],
                             sent_searches=[],
                             saved_searches=[],
                             deals=[],
                             total_cashback=0,
                             pending_cashback=0,
                             active_apps=0,
                             districts=districts,
                             developers=developers,
                             recent_activities=[])



# ==========================================
# PASSWORD RESET ENDPOINTS
# ==========================================



@mgr_api_bp.route('/api/favorites/count', methods=['GET'])
def get_favorites_count():
    """Get count of user's favorites - works for both authenticated and guest users"""
    from models import FavoriteProperty, FavoriteComplex, Property
    from services.guest_session import get_guest_favorite_count
    
    try:
        if not current_user.is_authenticated:
            props_count, complexes_count = get_guest_favorite_count()
            return jsonify({
                'success': True,
                'properties_count': props_count,
                'complexes_count': complexes_count,
                'total_count': props_count + complexes_count
            })
        
        favorites = db.session.query(FavoriteProperty).filter_by(user_id=current_user.id).all()
        property_ids = [int(fav.property_id) for fav in favorites if fav.property_id and fav.property_id.isdigit()]
        
        properties_count = db.session.query(Property).filter(
            Property.id.in_(property_ids),
            Property.is_active == True
        ).count() if property_ids else 0
        
        complexes_count = FavoriteComplex.query.filter_by(user_id=current_user.id).count()
        
        return jsonify({
            'success': True,
            'properties_count': properties_count,
            'complexes_count': complexes_count,
            'total_count': properties_count + complexes_count
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/favorites/list', methods=['GET'])
def get_favorites_list():
    """Get user's favorite properties with full details - works for both authenticated and guest users
    
    ✅ UPDATED: Now shows ALL properties including sold ones with is_sold flag
    """
    from models import FavoriteProperty, Property, ResidentialComplex, Developer
    from services.property_matcher import PropertyMatcher
    from services.guest_session import get_guest_favorites
    from urllib.parse import urlencode
    
    try:
        if not current_user.is_authenticated:
            guest_fav_ids = get_guest_favorites()
            if not guest_fav_ids:
                return jsonify({'success': True, 'favorites': []})
            
            int_ids = []
            for fid in guest_fav_ids:
                try:
                    int_ids.append(int(fid))
                except (ValueError, TypeError):
                    pass
            
            if not int_ids:
                return jsonify({'success': True, 'favorites': []})
            
            properties_query = db.session.query(
                Property,
                ResidentialComplex.name.label('complex_name'),
                ResidentialComplex.cashback_rate,
                ResidentialComplex.main_image.label('complex_image'),
                Developer.name.label('developer_name')
            ).outerjoin(
                ResidentialComplex, Property.complex_id == ResidentialComplex.id
            ).outerjoin(
                Developer, Property.developer_id == Developer.id
            ).filter(Property.id.in_(int_ids)).all()
            
            favorites_list = []
            for prop, complex_name, cashback_rate, complex_image, developer_name in properties_query:
                rooms_text = f"{prop.rooms}-комн" if prop.rooms and prop.rooms > 0 else "Студия"
                favorites_list.append({
                    'id': str(prop.id),
                    'inner_id': prop.inner_id,
                    'title': f"{rooms_text}, {prop.area} м², {prop.floor}/{prop.total_floors} эт.",
                    'complex': complex_name or 'ЖК не указан',
                    'district': prop.address or 'Адрес не указан',
                    'price': prop.price or 0,
                    'image': complex_image or prop.main_image or '/static/images/no-photo.svg',
                    'cashback_rate': cashback_rate or 3.5,
                    'cashback_amount': int((prop.price or 0) * (cashback_rate or 3.5) / 100),
                    'developer': developer_name or 'Застройщик не указан',
                    'is_sold': not prop.is_active,
                    'status_label': 'ПРОДАН' if not prop.is_active else '',
                    'created_at': 'Недавно',
                    'viewed': False,
                    'similar_search_url': None
                })
            
            return jsonify({'success': True, 'favorites': favorites_list})
        
        favorites = db.session.query(FavoriteProperty).filter_by(user_id=current_user.id).order_by(FavoriteProperty.created_at.desc()).all()
        
        if not favorites:
            return jsonify({
                'success': True,
                'favorites': []
            })
        
        # ОПТИМИЗАЦИЯ: Получаем только нужные property_id
        property_ids = [int(fav.property_id) for fav in favorites if fav.property_id and fav.property_id.isdigit()]
        
        if not property_ids:
            return jsonify({
                'success': True,
                'favorites': []
            })
        
        # ОПТИМИЗАЦИЯ: Загружаем только нужные объекты с JOIN (одним запросом!)
        # ✅ ИЗМЕНЕНИЕ: Убрали фильтр Property.is_active == True чтобы показывать проданные объекты
        properties_query = db.session.query(
            Property,
            ResidentialComplex.name.label('complex_name'),
            ResidentialComplex.cashback_rate,
            ResidentialComplex.main_image.label('complex_image'),
            Developer.name.label('developer_name')
        ).outerjoin(
            ResidentialComplex, Property.complex_id == ResidentialComplex.id
        ).outerjoin(
            Developer, Property.developer_id == Developer.id
        ).filter(
            Property.id.in_(property_ids)
            # Показываем все объекты, включая проданные
        ).all()
        
        # Создаем словарь для быстрого поиска
        properties_dict = {}
        for prop, complex_name, cashback_rate, complex_image, developer_name in properties_query:
            # Определяем rooms текст
            rooms_text = f"{prop.rooms}-комн" if prop.rooms and prop.rooms > 0 else "Студия"
            
            properties_dict[prop.id] = {
                'id': str(prop.id),
                'inner_id': prop.inner_id,  # ✅ НОВОЕ ПОЛЕ: Добавили inner_id для ссылок
                'title': f"{rooms_text}, {prop.area} м², {prop.floor}/{prop.total_floors} эт.",
                'complex': complex_name or 'ЖК не указан',
                'district': prop.address or 'Адрес не указан',  # Полный адрес из БД
                'price': prop.price or 0,
                'image': complex_image or prop.main_image or '/static/images/no-photo.svg',
                'cashback_rate': cashback_rate or 3.5,
                'cashback_amount': int((prop.price or 0) * (cashback_rate or 3.5) / 100),
                'developer': developer_name or 'Застройщик не указан',
                'is_sold': not prop.is_active,  # ✅ НОВОЕ ПОЛЕ: Флаг проданного объекта
                'status_label': 'ПРОДАН' if not prop.is_active else '',  # ✅ НОВОЕ ПОЛЕ: Метка статуса
            }
        
        # Формируем финальный список избранного
        favorites_list = []
        for fav in favorites:
            if not fav.property_id:
                continue
                
            # Конвертируем property_id в int для поиска в словаре (ключи - integers)
            property_id_int = int(fav.property_id) if fav.property_id.isdigit() else None
            property_data = properties_dict.get(property_id_int) if property_id_int else None
            
            if property_data:
                # Добавляем временную метку из избранного
                property_data['created_at'] = fav.created_at.strftime('%d.%m.%Y в %H:%M') if fav.created_at else 'Недавно'
                property_data['viewed'] = fav.viewed if hasattr(fav, 'viewed') else False
                
                # ✅ НОВОЕ: Добавляем URL для поиска аналогов (только для проданных объектов)
                if property_data.get('is_sold'):
                    search_params = PropertyMatcher.get_property_search_params(property_id_int)
                    if search_params:
                        property_data['similar_search_url'] = f"/properties?{urlencode(search_params)}"
                    else:
                        property_data['similar_search_url'] = "/properties"
                else:
                    property_data['similar_search_url'] = None
                
                favorites_list.append(property_data)
            else:
                # ✅ ОБНОВЛЕНО: Fallback если объект не найден или удален
                favorites_list.append({
                    'id': fav.property_id,
                    'inner_id': fav.property_id,
                    'title': f'Объект #{fav.property_id}',
                    'complex': 'Объект не найден',
                    'district': 'Возможно, объект был удален',
                    'price': 0,
                    'image': '/static/images/no-photo.svg',
                    'cashback_amount': 0,
                    'created_at': fav.created_at.strftime('%d.%m.%Y в %H:%M') if fav.created_at else 'Недавно',
                    'viewed': False,
                    'is_sold': True,  # ✅ НОВОЕ
                    'status_label': 'УДАЛЕН',  # ✅ НОВОЕ
                    'similar_search_url': '/properties'  # ✅ НОВОЕ
                })
        
        return jsonify({
            'success': True,
            'favorites': favorites_list
        })
    
    except Exception as e:
        print(f"Error in get_favorites_list: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/favorites/mark-viewed/<property_id>', methods=['POST'])
@login_required
@csrf.exempt
def mark_favorite_viewed(property_id):
    """Mark favorite property as viewed (property_id can be database ID or inner_id)"""
    from models import FavoriteProperty, Property
    
    try:
        # Try to find favorite by property_id directly (database ID stored as string)
        favorite = FavoriteProperty.query.filter_by(
            user_id=current_user.id,
            property_id=str(property_id)
        ).first()
        
        # If not found, try by inner_id
        if not favorite:
            property_obj = Property.query.filter_by(inner_id=str(property_id)).first()
            if property_obj:
                favorite = FavoriteProperty.query.filter_by(
                    user_id=current_user.id,
                    property_id=str(property_obj.id)
                ).first()
        
        if favorite:
            favorite.viewed = True
            db.session.commit()
            print(f"✅ Marked property {property_id} as viewed for user {current_user.id}")
            return jsonify({'success': True})
        
        return jsonify({'success': False, 'error': 'Favorite not found'}), 404
    
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error marking property {property_id} as viewed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/complexes/favorites/mark-viewed/<complex_id>', methods=['POST'])
@login_required
@csrf.exempt
def mark_complex_favorite_viewed(complex_id):
    """Mark favorite complex as viewed (complex_id from frontend)"""
    from models import FavoriteComplex
    
    try:
        print(f"🔍 Looking for complex_id={complex_id} for user {current_user.id}")
        favorite = FavoriteComplex.query.filter_by(
            user_id=current_user.id,
            complex_id=str(complex_id)
        ).first()
        
        if not favorite:
            print(f"❌ Favorite complex {complex_id} not found for user {current_user.id}")
            return jsonify({'success': False, 'error': 'Favorite not found'}), 404
        
        print(f"📝 Before update: viewed={favorite.viewed}")
        favorite.viewed = True
        db.session.flush()
        print(f"📝 After flush: viewed={favorite.viewed}")
        db.session.commit()
        print(f"✅ Marked complex {complex_id} as viewed for user {current_user.id}")
        
        # Проверяем, что изменения сохранились
        db.session.refresh(favorite)
        print(f"✅ After refresh: viewed={favorite.viewed}")
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error marking complex {complex_id} as viewed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# Complex Favorites API
@mgr_api_bp.route('/api/complexes/favorites', methods=['POST'])
@login_required  
@csrf.exempt  # Disable CSRF for API endpoint
def add_complex_to_favorites():
    """Add residential complex to favorites"""
    from models import FavoriteComplex
    data = request.get_json()
    
    complex_id = data.get('complex_id')
    complex_name = data.get('complex_name', 'ЖК')
    
    if not complex_id:
        return jsonify({'success': False, 'error': 'complex_id is required'}), 400
    
    # Check if already in favorites
    existing = FavoriteComplex.query.filter_by(
        user_id=current_user.id,
        complex_id=str(complex_id)
    ).first()
    
    if existing:
        return jsonify({'success': False, 'error': 'Complex already in favorites'}), 400
    
    try:
        # Create favorite complex record
        favorite = FavoriteComplex(
            user_id=current_user.id,
            complex_id=str(complex_id),
            complex_name=complex_name,
            developer_name=data.get('developer_name', ''),
            complex_address=data.get('address', ''),
            district=data.get('district', ''),
            min_price=data.get('min_price'),
            max_price=data.get('max_price'),
            complex_image=data.get('image', ''),
            complex_url=data.get('url', ''),
            status=data.get('status', 'В продаже')
        )
        
        db.session.add(favorite)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'ЖК добавлен в избранное'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/complexes/favorites/<complex_id>', methods=['DELETE'])
@login_required
@csrf.exempt  # Disable CSRF for API endpoint
def remove_complex_from_favorites(complex_id):
    """Remove residential complex from favorites"""
    from models import FavoriteComplex
    
    favorite = FavoriteComplex.query.filter_by(
        user_id=current_user.id,
        complex_id=str(complex_id)
    ).first()
    
    if not favorite:
        return jsonify({'success': False, 'error': 'Complex not in favorites'}), 404
    
    try:
        db.session.delete(favorite)
        db.session.commit()
        return jsonify({'success': True, 'message': 'ЖК удален из избранного'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/complexes/favorites/toggle', methods=['POST'])
@csrf.exempt
def toggle_complex_favorite():
    """Toggle favorite status for residential complex - works for both authenticated and guest users"""
    from models import FavoriteComplex
    from services.guest_session import toggle_guest_favorite_complex
    data = request.get_json()
    complex_id = data.get('complex_id')
    
    if not complex_id:
        return jsonify({'success': False, 'error': 'complex_id is required'}), 400
    
    if not current_user.is_authenticated:
        action, is_fav = toggle_guest_favorite_complex(complex_id)
        return jsonify({'success': True, 'favorited': is_fav, 'message': 'ЖК добавлен в избранное' if is_fav else 'ЖК удален из избранного'})
    
    try:
        existing = FavoriteComplex.query.filter_by(
            user_id=current_user.id,
            complex_id=str(complex_id)
        ).first()
        
        if existing:
            # Remove from favorites
            db.session.delete(existing)
            db.session.commit()
            return jsonify({'success': True, 'favorited': False, 'message': 'ЖК удален из избранного'})
        else:
            # Add to favorites
            favorite = FavoriteComplex(
                user_id=current_user.id,
                complex_id=str(complex_id),
                complex_name=data.get('complex_name', 'ЖК'),
                developer_name=data.get('developer_name', ''),
                complex_address=data.get('address', ''),  # ✅ ИСПРАВЛЕНО: complex_address вместо address_display_name
                district=data.get('district', ''),
                min_price=data.get('min_price'),
                max_price=data.get('max_price'),
                complex_image=data.get('image', ''),
                complex_url=data.get('url', ''),
                status=data.get('status', 'В продаже')
            )
            
            db.session.add(favorite)
            db.session.commit()
            return jsonify({'success': True, 'favorited': True, 'message': 'ЖК добавлен в избранное'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/complexes/favorites/list', methods=['GET'])
def get_user_complex_favorites_list():
    """Get user's favorite complexes with full details from residential_complexes table"""
    from models import FavoriteComplex, ResidentialComplex, Developer, District
    from services.guest_session import get_guest_favorites
    
    try:
        if not current_user.is_authenticated:
            guest_complex_ids = list(session.get('guest_favorite_complexes', []))
            if not guest_complex_ids:
                return jsonify({'success': True, 'complexes': [], 'count': 0})
            # Load real complex data for guests (same as authenticated path)
            int_ids = []
            for cid in guest_complex_ids:
                try:
                    int_ids.append(int(cid))
                except Exception:
                    pass
            guest_complexes = []
            if int_ids:
                real_complexes = db.session.query(
                    ResidentialComplex.id,
                    ResidentialComplex.name,
                    ResidentialComplex.address,
                    ResidentialComplex.main_image,
                    ResidentialComplex.cashback_rate,
                    District.name.label('district_name'),
                    Developer.name.label('developer_name')
                ).outerjoin(District, ResidentialComplex.district_id == District.id)\
                 .outerjoin(Developer, ResidentialComplex.developer_id == Developer.id)\
                 .filter(ResidentialComplex.id.in_(int_ids)).all()
                prices_query = text("""
                    SELECT rc.id, MIN(p.price) as min_price, MAX(p.price) as max_price
                    FROM residential_complexes rc
                    LEFT JOIN properties p ON p.complex_id = rc.id AND p.is_active = true
                    WHERE rc.id = ANY(:complex_ids)
                    GROUP BY rc.id
                """)
                prices_result = db.session.execute(prices_query, {'complex_ids': int_ids})
                prices_dict = {row[0]: {'min_price': row[1] or 0, 'max_price': row[2] or 0} for row in prices_result}
                for rc in real_complexes:
                    p = prices_dict.get(rc.id, {})
                    guest_complexes.append({
                        'id': str(rc.id),
                        'name': rc.name or 'ЖК',
                        'address': rc.address or '',
                        'district': rc.district_name or '',
                        'developer': rc.developer_name or '',
                        'image': rc.main_image or '/static/images/no-photo.svg',
                        'cashback_rate': rc.cashback_rate or 5,
                        'min_price': p.get('min_price', 0),
                        'max_price': p.get('max_price', 0),
                        'url': f'/residential-complex/{rc.id}',
                        'status': 'В продаже',
                    })
            return jsonify({'success': True, 'complexes': guest_complexes, 'count': len(guest_complexes)})
        
        favorites = FavoriteComplex.query.filter_by(user_id=current_user.id).order_by(FavoriteComplex.created_at.desc()).all()
        
        # Собираем ID комплексов
        complex_ids_int = []
        for fav in favorites:
            try:
                complex_ids_int.append(int(fav.complex_id))
            except:
                continue
        
        # Batch-загрузка реальных данных из residential_complexes
        complexes_dict = {}
        if complex_ids_int:
            real_complexes = db.session.query(
                ResidentialComplex.id,
                ResidentialComplex.name,
                ResidentialComplex.address,
                ResidentialComplex.main_image,
                ResidentialComplex.cashback_rate,
                District.name.label('district_name'),
                Developer.name.label('developer_name')
            ).outerjoin(District, ResidentialComplex.district_id == District.id)\
             .outerjoin(Developer, ResidentialComplex.developer_id == Developer.id)\
             .filter(ResidentialComplex.id.in_(complex_ids_int)).all()
            
            for rc in real_complexes:
                complexes_dict[rc.id] = rc
        
        # Batch-загрузка цен и фото из properties для каждого ЖК
        prices_dict = {}
        if complex_ids_int:
            # Получаем min/max цены и фото для каждого ЖК
            prices_query = text("""
                SELECT 
                    rc.id,
                    MIN(p.price) as min_price,
                    MAX(p.price) as max_price,
                    COALESCE(rc.main_image, rc.gallery_images, MIN(p.gallery_images)) as photos
                FROM residential_complexes rc
                LEFT JOIN properties p ON p.complex_id = rc.id AND p.is_active = true
                WHERE rc.id = ANY(:complex_ids)
                GROUP BY rc.id, rc.main_image, rc.gallery_images
            """)
            
            prices_result = db.session.execute(prices_query, {'complex_ids': complex_ids_int})
            prices_dict = {row[0]: {'min_price': row[1] or 0, 'max_price': row[2] or 0, 'photos': row[3]} for row in prices_result}
        
        # Собираем данные для ответа
        complexes_data = []
        for fav in favorites:
            try:
                complex_id_int = int(fav.complex_id)
                rc = complexes_dict.get(complex_id_int)
                
                if rc:
                    # Получаем цены и фото из prices_dict
                    complex_prices = prices_dict.get(complex_id_int, {})
                    photos_data = complex_prices.get('photos', '')
                    
                    # Извлекаем первое фото из JSON массива
                    image_url = '/static/images/no-image.jpg'
                    if photos_data:
                        try:
                            photos_list = json.loads(photos_data) if isinstance(photos_data, str) else photos_data
                            if photos_list and isinstance(photos_list, list) and len(photos_list) > 0:
                                image_url = photos_list[0]
                        except (json.JSONDecodeError, TypeError):
                            if isinstance(photos_data, str) and photos_data.strip():
                                image_url = photos_data
                    
                    # Используем реальные данные из БД
                    complexes_data.append({
                        'id': str(complex_id_int),
                        'name': rc.name or 'ЖК',
                        'address': rc.address or '',
                        'district': rc.district_name or '',
                        'developer': rc.developer_name or '',
                        'image': image_url,
                        'cashback_rate': rc.cashback_rate or 5,
                        'min_price': complex_prices.get('min_price', 0),
                        'max_price': complex_prices.get('max_price', 0),
                        'url': f'/residential-complex/{complex_id_int}',
                        'status': 'В продаже',
                        'created_at': fav.created_at.strftime('%d.%m.%Y в %H:%M')
                    })
                else:
                    # Используем сохраненные данные если ЖК не найден
                    complexes_data.append({
                        'id': fav.complex_id,
                        'name': fav.complex_name or 'ЖК',
                        'address': fav.complex_address or 'Не указано',
                        'district': fav.district or 'Не указано',
                        'developer': fav.developer_name or 'Не указано',
                        'image': fav.complex_image or '',
                        'cashback_rate': 5,
                        'min_price': fav.min_price or 0,
                        'max_price': fav.max_price or 0,
                        'url': fav.complex_url or '',
                        'status': fav.status or 'В продаже',
                        'created_at': fav.created_at.strftime('%d.%m.%Y в %H:%M')
                    })
            except Exception as e:
                print(f"Error processing complex {fav.complex_id}: {e}")
                continue
        
        return jsonify({
            'success': True,
            'complexes': complexes_data
        })
    
    except Exception as e:
        print(f"Error in get_user_complex_favorites_list: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/favorites/clear-all', methods=['POST'])
@login_required  
@csrf.exempt  # Disable CSRF for API endpoint
def clear_all_favorites():
    """Clear all user's favorite properties"""
    from models import FavoriteProperty
    
    try:
        # Delete all favorites for current user
        deleted_count = db.session.query(FavoriteProperty).filter_by(user_id=current_user.id).delete()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Удалено {deleted_count} избранных квартир',
            'deleted_count': deleted_count
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/complexes/favorites/clear-all', methods=['POST'])
@login_required  
@csrf.exempt  # Disable CSRF for API endpoint
def clear_all_complex_favorites():
    """Clear all user's favorite complexes"""
    from models import FavoriteComplex
    
    try:
        # Delete all complex favorites for current user
        deleted_count = db.session.query(FavoriteComplex).filter_by(user_id=current_user.id).delete()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Удалено {deleted_count} избранных ЖК',
            'deleted_count': deleted_count
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/dashboard/data', methods=['GET'])
@login_required
def get_dashboard_data():
    """ОПТИМИЗИРОВАННЫЙ ENDPOINT: Получить все данные дашборда одним запросом"""
    from models import FavoriteProperty, FavoriteComplex, ComparisonProperty, ComparisonComplex, Recommendation, Collection, UserComparison
    
    try:
        # Все счетчики одним запросом к БД
        favorites_properties_count = FavoriteProperty.query.filter_by(user_id=current_user.id).count()
        favorites_complexes_count = FavoriteComplex.query.filter_by(user_id=current_user.id).count()
        comparison_properties_count = db.session.query(ComparisonProperty).join(
            UserComparison, ComparisonProperty.user_comparison_id == UserComparison.id
        ).filter(UserComparison.user_id == current_user.id).count()
        
        comparison_complexes_count = db.session.query(ComparisonComplex).join(
            UserComparison, ComparisonComplex.user_comparison_id == UserComparison.id
        ).filter(UserComparison.user_id == current_user.id).count()
        recommendations_count = Recommendation.query.filter(
            Recommendation.client_id == current_user.id,
            Recommendation.status != 'dismissed'
        ).count()
        collections_count = Collection.query.filter_by(assigned_to_user_id=current_user.id).count()
        
        return jsonify({
            'success': True,
            'favorites': {
                'properties': favorites_properties_count,
                'complexes': favorites_complexes_count,
                'total': favorites_properties_count + favorites_complexes_count
            },
            'comparison': {
                'properties': comparison_properties_count,
                'complexes': comparison_complexes_count,
                'total': comparison_properties_count + comparison_complexes_count
            },
            'recommendations': recommendations_count,
            'collections': collections_count
        })
    
    except Exception as e:
        print(f"Error in get_dashboard_data: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/notifications', methods=['GET'])
@login_required
def api_get_notifications():
    from models import Notification, UserNotification
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)

        notifs_1 = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(30).all()
        notifs_2 = UserNotification.query.filter_by(user_id=current_user.id).order_by(UserNotification.created_at.desc()).limit(30).all()

        all_notifs = []
        for n in notifs_1:
            all_notifs.append({
                'id': n.id,
                'source': 'notification',
                'title': n.title,
                'message': n.message,
                'type': n.type or 'info',
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                '_dt': n.created_at,
            })
        for n in notifs_2:
            all_notifs.append({
                'id': n.id,
                'source': 'user_notification',
                'title': n.title,
                'message': n.message,
                'type': n.notification_type or 'info',
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                'action_url': n.action_url,
                '_dt': n.created_at,
            })

        all_notifs.sort(key=lambda x: x['created_at'] or '', reverse=True)

        # Badge count: only recent (last 30 days) unread notifications
        unread_count = sum(
            1 for n in all_notifs
            if not n['is_read'] and n.get('_dt') and n['_dt'] >= cutoff
        )

        # Strip internal field before returning
        for n in all_notifs:
            n.pop('_dt', None)

        return jsonify({'success': True, 'notifications': all_notifs[:30], 'unread_count': unread_count})
    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return jsonify({'success': False, 'notifications': [], 'unread_count': 0})

@mgr_api_bp.route('/notifications', endpoint='notifications_page')
@login_required
def notifications_page():
    from models import Admin, Manager
    if isinstance(current_user._get_current_object(), Admin):
        return redirect(url_for('adm.admin_dashboard'))
    elif isinstance(current_user._get_current_object(), Manager):
        return redirect(url_for('mgr.manager_dashboard'))
    return render_template('notifications.html')


@mgr_api_bp.route('/api/notifications/mark-read', methods=['POST'])
@login_required
def api_mark_notifications_read():
    from models import Notification, UserNotification
    try:
        data = request.get_json() or {}
        notif_id = data.get('id')
        source = data.get('source')
        mark_all = data.get('all', False)

        if mark_all:
            Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
            UserNotification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True, 'read_at': datetime.utcnow()})
            db.session.commit()
            return jsonify({'success': True})

        if notif_id and source == 'notification':
            n = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first()
            if n:
                n.is_read = True
                db.session.commit()
        elif notif_id and source == 'user_notification':
            n = UserNotification.query.filter_by(id=notif_id, user_id=current_user.id).first()
            if n:
                n.is_read = True
                n.read_at = datetime.utcnow()
                db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        print(f"Error marking notification read: {e}")
        db.session.rollback()
        return jsonify({'success': False}), 500

@mgr_api_bp.route('/api/manager/notifications', methods=['GET'])
@manager_required
def api_get_manager_notifications():
    from models import ManagerNotification
    try:
        current_manager = current_user
        notifs = ManagerNotification.query.filter_by(
            manager_id=current_manager.id
        ).order_by(ManagerNotification.created_at.desc()).limit(30).all()
        
        notifications = []
        for n in notifs:
            action_url = ''
            if n.presentation_id:
                action_url = f'/manager/presentation/{n.presentation_id}'
            elif n.notification_type == 'task_reminder' and n.extra_data:
                try:
                    import json
                    extra = json.loads(n.extra_data)
                    if extra.get('deal_id'):
                        action_url = f'/manager/deals/{extra["deal_id"]}'
                except Exception:
                    pass
            notifications.append({
                'id': n.id,
                'source': 'manager_notification',
                'title': n.title,
                'message': n.message,
                'type': n.notification_type or 'info',
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                'action_url': action_url,
            })
        
        from datetime import timedelta
        cutoff_dt = datetime.utcnow() - timedelta(days=30)
        unread_count = sum(
            1 for n in notifs
            if not n.is_read and n.created_at and n.created_at >= cutoff_dt
        )
        return jsonify({'success': True, 'notifications': notifications, 'unread_count': unread_count})
    except Exception as e:
        print(f"Error fetching manager notifications: {e}")
        return jsonify({'success': False, 'notifications': [], 'unread_count': 0})

@mgr_api_bp.route('/api/manager/notifications/mark-read', methods=['POST'])
@manager_required
def api_mark_manager_notifications_read():
    from models import ManagerNotification
    try:
        current_manager = current_user
        data = request.get_json() or {}
        notif_id = data.get('id')
        mark_all = data.get('all', False)
        
        if mark_all:
            ManagerNotification.query.filter_by(
                manager_id=current_manager.id, is_read=False
            ).update({'is_read': True, 'read_at': datetime.utcnow()})
            db.session.commit()
            return jsonify({'success': True})
        
        if notif_id:
            n = ManagerNotification.query.filter_by(
                id=notif_id, manager_id=current_manager.id
            ).first()
            if n:
                n.is_read = True
                n.read_at = datetime.utcnow()
                db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error marking manager notification read: {e}")
        db.session.rollback()
        return jsonify({'success': False}), 500


@mgr_api_bp.route('/api/searches/stub-removed', methods=['GET'])
def get_saved_searches_stub_removed():
    """Удалена: заглушка заменена реальной реализацией /api/searches ниже"""
    return jsonify({'success': True, 'searches': []})


@mgr_api_bp.route('/api/complete-profile', methods=['POST'])
@login_required
@require_json_csrf
def complete_profile():
    """Complete user profile after SMS verification"""
    from models import User
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip()
        telegram = data.get('telegram', '').strip()
        
        # Validate required field
        if not full_name:
            return jsonify({'success': False, 'message': 'ФИО обязательно'}), 400
        
        # Update user profile
        current_user.full_name = _capitalize_name(full_name)
        
        if email:
            # Check if email already exists (for other users)
            existing_user = User.query.filter(
                User.email == email,
                User.id != current_user.id
            ).first()
            
            if existing_user:
                return jsonify({'success': False, 'message': 'Email уже используется'}), 400
            
            current_user.email = email
        
        if telegram:
            current_user.telegram = telegram
        
        # Mark profile as completed
        current_user.profile_completed = True
        
        db.session.commit()
        
        logger.info(f"✅ Profile completed for user {current_user.id}: {full_name}")
        
        return jsonify({
            'success': True,
            'message': 'Профиль успешно обновлен!'
        })
        
    except Exception as e:
        logger.error(f"❌ Error completing profile: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении профиля: {str(e)}'
        }), 500


@mgr_api_bp.route('/api/user/stats', methods=['GET'])
@login_required
def get_user_stats():
    """ЗАГЛУШКА: Статистика пользователя (пока не реализовано)"""
    return jsonify({
        'success': True,
        'views': 0,
        'favorites': 0,
        'applications': 0
    })

@mgr_api_bp.route('/api/favorites/all', methods=['GET'])
@login_required
def get_all_favorites():
    """ОПТИМИЗИРОВАННЫЙ: Получить ВСЕ избранное (квартиры + ЖК) одним запросом"""
    from models import FavoriteProperty, FavoriteComplex, Property, ResidentialComplex, Developer, District
    
    try:
        # Получаем избранные квартиры
        favorites = db.session.query(FavoriteProperty).filter_by(user_id=current_user.id).order_by(FavoriteProperty.created_at.desc()).all()
        
        properties_list = []
        if favorites:
            print(f"DEBUG /api/favorites/all: Found {len(favorites)} favorites for user {current_user.id}")
            # Конвертируем property_id в int (они хранятся как varchar в БД)
            property_ids = [int(fav.property_id) for fav in favorites if fav.property_id and fav.property_id.isdigit()]
            print(f"DEBUG: property_ids after conversion: {property_ids}")
            
            if property_ids:
                properties_query = db.session.query(
                    Property,
                    ResidentialComplex.name.label('complex_name'),
                    ResidentialComplex.cashback_rate,
                    ResidentialComplex.main_image.label('complex_image'),
                    Developer.name.label('developer_name')
                ).outerjoin(
                    ResidentialComplex, Property.complex_id == ResidentialComplex.id
                ).outerjoin(
                    Developer, Property.developer_id == Developer.id
                ).filter(
                    Property.id.in_(property_ids)  # ✅ Убрали is_active чтобы показывать проданные объекты
                ).all()
                print(f"DEBUG: properties_query returned {len(properties_query)} results")
                
                properties_dict = {}
                for prop, complex_name, cashback_rate, complex_image, developer_name in properties_query:
                    rooms_text = f"{prop.rooms}-комн" if prop.rooms and prop.rooms > 0 else "Студия"
                    properties_dict[prop.id] = {  # Ключ - prop.id (integer)
                        'id': str(prop.id),
                        'title': f"{rooms_text}, {prop.area} м², {prop.floor}/{prop.total_floors} эт.",
                        'complex': complex_name or 'ЖК не указан',
                        'district': prop.address or 'Адрес не указан',
                        'price': prop.price or 0,
                        'image': complex_image or prop.main_image or '/static/images/no-photo.svg',
                        'cashback_rate': cashback_rate or 3.5,
                        'cashback_amount': int((prop.price or 0) * (cashback_rate or 3.5) / 100),
                        'developer': developer_name or 'Застройщик не указан',
                        'is_sold': not prop.is_active,  # ✅ НОВОЕ ПОЛЕ: Флаг проданного объекта
                        'created_at': None,
                        'viewed': False
                    }
                
                for fav in favorites:
                    # Конвертируем property_id в int для поиска в словаре
                    property_id_int = int(fav.property_id) if fav.property_id and fav.property_id.isdigit() else None
                    if property_id_int and property_id_int in properties_dict:
                        prop_data = properties_dict[property_id_int]
                        prop_data['created_at'] = fav.created_at.strftime('%d.%m.%Y в %H:%M') if fav.created_at else 'Недавно'
                        prop_data['viewed'] = fav.viewed if hasattr(fav, 'viewed') else False
                        properties_list.append(prop_data)
        
        print(f"DEBUG: Final properties_list length: {len(properties_list)}")
        
        # Получаем избранные ЖК
        complex_favorites = FavoriteComplex.query.filter_by(user_id=current_user.id).order_by(FavoriteComplex.created_at.desc()).all()
        
        complexes_list = []
        if complex_favorites:
            complex_ids_int = []
            for fav in complex_favorites:
                try:
                    complex_ids_int.append(int(fav.complex_id))
                except:
                    continue
            
            if complex_ids_int:
                complexes_query = db.session.query(
                    ResidentialComplex.id,
                    ResidentialComplex.name,
                    ResidentialComplex.address,
                    ResidentialComplex.main_image,
                    ResidentialComplex.cashback_rate,
                    District.name.label('district_name'),
                    Developer.name.label('developer_name')
                ).outerjoin(District, ResidentialComplex.district_id == District.id)\
                 .outerjoin(Developer, ResidentialComplex.developer_id == Developer.id)\
                 .filter(ResidentialComplex.id.in_(complex_ids_int)).all()
                
                complexes_dict = {}
                for rc in complexes_query:
                    complexes_dict[rc.id] = rc
                
                # Получаем цены
                from sqlalchemy import text, func
                prices_query = text("""
                    SELECT 
                        complex_id,
                        MIN(price) as min_price,
                        MAX(price) as max_price,
                        MIN(main_image) as first_image
                    FROM properties 
                    WHERE complex_id = ANY(:complex_ids) AND is_active = true
                    GROUP BY complex_id
                """)
                prices_result = db.session.execute(prices_query, {"complex_ids": complex_ids_int})
                prices_dict = {row[0]: {'min_price': row[1], 'max_price': row[2], 'first_image': row[3]} for row in prices_result}
                
                for fav in complex_favorites:
                    try:
                        complex_id_int = int(fav.complex_id)
                        rc = complexes_dict.get(complex_id_int)
                        
                        if rc:
                            complex_prices = prices_dict.get(complex_id_int, {})
                            image_url = rc.main_image or complex_prices.get('first_image') or fav.complex_image or ''
                            
                            complexes_list.append({
                                'id': str(complex_id_int),
                                'name': rc.name or fav.complex_name or 'ЖК',
                                'address': rc.address or fav.complex_address or 'Не указано',
                                'district': rc.district_name or fav.district or 'Не указано',
                                'developer': rc.developer_name or fav.developer_name or 'Не указано',
                                'image': image_url,
                                'cashback_rate': rc.cashback_rate or 5,
                                'min_price': complex_prices.get('min_price', fav.min_price or 0),
                                'max_price': complex_prices.get('max_price', fav.max_price or 0),
                                'url': f'/residential-complex/{complex_id_int}',
                                'status': 'В продаже',
                                'created_at': fav.created_at.strftime('%d.%m.%Y в %H:%M'),
                                'viewed': fav.viewed if hasattr(fav, 'viewed') else False
                            })
                    except Exception as e:
                        print(f"Error processing complex {fav.complex_id}: {e}")
                        continue
        
        return jsonify({
            'success': True,
            'properties': properties_list,
            'complexes': complexes_list,
            'total': len(properties_list) + len(complexes_list)
        })
    
    except Exception as e:
        print(f"Error in get_all_favorites: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# Manager Favorites API - Properties
@mgr_api_bp.route('/api/manager/favorites', methods=['POST'])
@manager_required  
def manager_add_to_favorites():
    """Add property to manager's favorites"""
    from models import ManagerFavoriteProperty
    
    current_manager = current_user
    data = request.get_json()
    
    # Check if already in favorites
    existing = ManagerFavoriteProperty.query.filter_by(
        manager_id=current_manager.id,
        property_id=data.get('property_id')
    ).first()
    
    if existing:
        return jsonify({'success': False, 'error': 'Уже в избранном'})
    
    try:
        favorite = ManagerFavoriteProperty(
            manager_id=current_manager.id,
            property_id=data.get('property_id'),
            property_name=data.get('property_name', ''),
            property_type=data.get('property_type', ''),
            property_size=float(data.get('property_size', 0)),
            property_price=int(data.get('property_price', 0)),
            complex_name=data.get('complex_name', ''),
            developer_name=data.get('developer_name', ''),
            property_image=data.get('property_image'),
            property_url=data.get('property_url'),
            cashback_amount=int(data.get('cashback_amount', 0)),
            cashback_percent=float(data.get('cashback_percent', 0)),
            notes=data.get('notes', ''),
            recommended_for=data.get('recommended_for', '')
        )
        db.session.add(favorite)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Добавлено в избранное'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/favorites/<property_id>', methods=['DELETE'])
@manager_required
def manager_remove_from_favorites(property_id):
    """Remove property from manager's favorites"""
    from models import ManagerFavoriteProperty
    
    current_manager = current_user
    
    favorite = ManagerFavoriteProperty.query.filter_by(
        manager_id=current_manager.id,
        property_id=property_id
    ).first()
    
    if favorite:
        try:
            db.session.delete(favorite)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Удалено из избранного'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400
    
    return jsonify({'success': False, 'error': 'Объект не найден в избранном'}), 404

@mgr_api_bp.route('/api/manager/favorites/clear', methods=['DELETE'])
@manager_required
def manager_clear_all_favorites():
    """Clear all properties from manager's favorites"""
    from models import ManagerFavoriteProperty
    
    current_manager = current_user
    
    try:
        # Delete all favorites for this manager
        deleted_count = ManagerFavoriteProperty.query.filter_by(
            manager_id=current_manager.id
        ).delete()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Удалено {deleted_count} объектов из избранного',
            'deleted_count': deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/manager/favorites/toggle', methods=['POST'])
@manager_required
def manager_toggle_favorite():
    """Toggle favorite status for property"""
    from models import ManagerFavoriteProperty
    
    current_manager = current_user
    
    data = request.get_json()
    property_id = data.get('property_id')
    
    if not property_id:
        return jsonify({'success': False, 'error': 'property_id required'}), 400
    
    print(f"DEBUG: Manager favorites toggle called by manager {current_manager.id} for property {property_id}")
    
    # Check if already in favorites
    existing = ManagerFavoriteProperty.query.filter_by(
        manager_id=current_manager.id,
        property_id=property_id
    ).first()
    
    try:
        if existing:
            # Remove from favorites
            db.session.delete(existing)
            db.session.commit()
            return jsonify({'success': True, 'action': 'removed', 'is_favorite': False, 'message': 'Удалено из избранного'})
        else:
            # Add to favorites
            favorite = ManagerFavoriteProperty(
                manager_id=current_manager.id,
                property_id=property_id,
                property_name=data.get('property_name', ''),
                property_type=data.get('property_type', ''),
                property_size=float(data.get('property_size', 0)),
                property_price=int(data.get('property_price', 0)),
                complex_name=data.get('complex_name', ''),
                developer_name=data.get('developer_name', ''),
                property_image=data.get('property_image'),
                property_url=data.get('property_url'),
                cashback_amount=int(data.get('cashback_amount', 0)),
                cashback_percent=float(data.get('cashback_percent', 0)),
                notes=data.get('notes', ''),
                recommended_for=data.get('recommended_for', '')
            )
            db.session.add(favorite)
            db.session.commit()
            return jsonify({'success': True, 'action': 'added', 'is_favorite': True, 'message': 'Добавлено в избранное'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@mgr_api_bp.route('/api/manager/favorites/count', methods=['GET'])
@manager_required  
def manager_get_favorites_count():
    """Get count of manager's favorites"""
    from models import ManagerFavoriteProperty, ManagerFavoriteComplex
    
    current_manager = current_user
    
    try:
        # DEBUG: Log which tables we're querying
        print(f"🔍 DEBUG: /api/manager/favorites/count called - querying MANAGER tables for manager {current_manager.id}")
        
        properties_count = ManagerFavoriteProperty.query.filter_by(manager_id=current_manager.id).count()
        complexes_count = ManagerFavoriteComplex.query.filter_by(manager_id=current_manager.id).count()
        
        print(f"✅ Manager favorites count: {properties_count} properties, {complexes_count} complexes from MANAGER tables")
        
        return jsonify({
            'success': True,
            'properties_count': properties_count,
            'complexes_count': complexes_count,
            'total_count': properties_count + complexes_count
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Note: Manager Complex Favorites endpoints already exist below - no duplicates needed

@mgr_api_bp.route('/api/manager/favorites/list', methods=['GET'])
@manager_required  
def manager_get_favorites_list():
    """Get manager's favorite properties with full details"""
    from models import ManagerFavoriteProperty, Property, ResidentialComplex, Developer
    
    current_manager = current_user
    
    try:
        print(f"🔍 DEBUG: /api/manager/favorites/list called for manager {current_manager.id}")
        
        favorites = db.session.query(ManagerFavoriteProperty).filter_by(manager_id=current_manager.id).order_by(ManagerFavoriteProperty.created_at.desc()).all()
        print(f"✅ Found {len(favorites)} favorites in MANAGER_FAVORITE_PROPERTIES")
        
        if not favorites:
            return jsonify({'success': True, 'favorites': []})
        
        # Получаем id (serial) из manager_favorite_properties.property_id
        property_ids = [int(fav.property_id) for fav in favorites if fav.property_id]
        print(f"🔍 DEBUG: Looking for property IDs: {property_ids[:5]}...")
        
        if not property_ids:
            return jsonify({'success': True, 'favorites': []})
        
        # Загружаем свойства по properties.id (serial)!
        properties_query = db.session.query(
            Property,
            ResidentialComplex.name.label('complex_name'),
            ResidentialComplex.cashback_rate,
            ResidentialComplex.main_image.label('complex_image'),
            Developer.name.label('developer_name')
        ).outerjoin(
            ResidentialComplex, Property.complex_id == ResidentialComplex.id
        ).outerjoin(
            Developer, Property.developer_id == Developer.id
        ).filter(
            Property.id.in_(property_ids)  # ✅ Ищем по properties.id!
        ).all()
        
        print(f"🔍 DEBUG: SQL returned {len(properties_query)} properties")
        
        # Создаем словарь: ключ = properties.id
        properties_dict = {}
        for prop, complex_name, cashback_rate, complex_image, developer_name in properties_query:
            rooms_text = f"{prop.rooms}-комн" if prop.rooms and prop.rooms > 0 else "Студия"
            
            properties_dict[prop.id] = {  # ✅ Ключ = properties.id
                'id': str(prop.id),
                'inner_id': prop.inner_id,
                'title': f"{rooms_text}, {prop.area} м², {prop.floor}/{prop.total_floors} эт.",
                'complex': complex_name or 'ЖК не указан',
                'district': prop.address or 'Адрес не указан',
                'price': prop.price or 0,
                'image': complex_image or prop.main_image or '/static/images/no-photo.svg',
                'cashback_rate': cashback_rate or 3.5,
                'cashback_amount': int((prop.price or 0) * (cashback_rate or 3.5) / 100),
                'developer': developer_name or 'Застройщик не указан'
            }
        
        print(f"🔍 DEBUG: Created dict with {len(properties_dict)} entries")
        
        # Формируем финальный список
        favorites_list = []
        for fav in favorites:
            property_id_int = int(fav.property_id)
            property_data = properties_dict.get(property_id_int)  # ✅ Ищем по properties.id
            
            if property_data:
                property_data['created_at'] = fav.created_at.strftime('%d.%m.%Y в %H:%M') if fav.created_at else 'Недавно'
                favorites_list.append(property_data)
            else:
                print(f"⚠️ Property {fav.property_id} not found in database")
        
        print(f"✅ Returning {len(favorites_list)} favorites")
        
        return jsonify({
            'success': True,
            'favorites': favorites_list
        })
    
    except Exception as e:
        print(f"❌ ERROR in manager_get_favorites_list: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

    """Add residential complex to manager's favorites"""
    from models import ManagerFavoriteComplex
    
    current_manager = current_user
    data = request.get_json()
    
    complex_id = data.get('complex_id')
    complex_name = data.get('complex_name', 'ЖК')
    
    if not complex_id:
        return jsonify({'success': False, 'error': 'complex_id is required'}), 400
    
    # Check if already in favorites
    existing = ManagerFavoriteComplex.query.filter_by(
        manager_id=current_manager.id,
        complex_id=str(complex_id)
    ).first()
    
    if existing:
        return jsonify({'success': False, 'error': 'Complex already in favorites'}), 400
    
    try:
        # Create favorite complex record
        favorite = ManagerFavoriteComplex(
            manager_id=current_manager.id,
            complex_id=str(complex_id),
            complex_name=complex_name,
            developer_name=data.get('developer_name', ''),
            complex_address=data.get('address', ''),
            district=data.get('district', ''),
            min_price=data.get('min_price'),
            max_price=data.get('max_price'),
            complex_image=data.get('image', ''),
            complex_url=data.get('url', ''),
            status=data.get('status', 'В продаже'),
            object_class_display_name=data.get('object_class_display_name', ''),
            notes=data.get('notes', ''),
            recommended_for=data.get('recommended_for', '')
        )
        
        db.session.add(favorite)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'ЖК добавлен в избранное'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/manager/complexes/favorites/<complex_id>', methods=['DELETE'])
@manager_required
def manager_remove_complex_from_favorites(complex_id):
    """Remove residential complex from manager's favorites"""
    from models import ManagerFavoriteComplex
    
    current_manager = current_user
    
    favorite = ManagerFavoriteComplex.query.filter_by(
        manager_id=current_manager.id,
        complex_id=str(complex_id)
    ).first()
    
    if not favorite:
        return jsonify({'success': False, 'error': 'Complex not in favorites'}), 404
    
    try:
        db.session.delete(favorite)
        db.session.commit()
        return jsonify({'success': True, 'message': 'ЖК удален из избранного'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/manager/complexes/favorites/clear', methods=['DELETE'])
@manager_required
def manager_clear_all_complex_favorites():
    """Clear all complexes from manager's favorites"""
    from models import ManagerFavoriteComplex
    
    current_manager = current_user
    
    try:
        # Delete all complex favorites for this manager
        deleted_count = ManagerFavoriteComplex.query.filter_by(
            manager_id=current_manager.id
        ).delete()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Удалено {deleted_count} ЖК из избранного',
            'deleted_count': deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/manager/complexes/favorites/toggle', methods=['POST'])
@manager_required
def manager_toggle_complex_favorite():
    """Toggle favorite status for residential complex"""
    from models import ManagerFavoriteComplex
    
    current_manager = current_user
    
    data = request.get_json()
    complex_id = data.get('complex_id')
    
    if not complex_id:
        return jsonify({'success': False, 'error': 'complex_id is required'}), 400
    
    try:
        existing = ManagerFavoriteComplex.query.filter_by(
            manager_id=current_manager.id,
            complex_id=str(complex_id)
        ).first()
        
        if existing:
            # Remove from favorites
            db.session.delete(existing)
            db.session.commit()
            return jsonify({'success': True, 'favorited': False, 'message': 'ЖК удален из избранного'})
        else:
            # ✅ ИСПРАВЛЕНИЕ: Загружаем реальные данные ЖК из базы данных
            real_complex_name = 'ЖК без названия'
            real_developer_name = 'Застройщик не указан'
            real_address = 'Адрес не указан'
            real_district = 'Район не указан'
            real_min_price = 0
            real_max_price = 0
            real_image = '/static/images/no-photo.svg'
            real_status = 'В продаже'
            real_object_class = ''
            
            try:
                # ✅ MIGRATED: Загружаем данные из normalized schema по complex_id
                from sqlalchemy import text
                complex_query = text("""
                    SELECT 
                        rc.name as complex_name,
                        d.name as developer_name,
                        rc.address AS address_display_name,
                        dist.name AS address_locality_name,
                        MIN(p.price) as min_price,
                        MAX(p.price) as max_price,
                        (SELECT p2.gallery_images FROM properties p2 
                         WHERE p2.complex_id = rc.id 
                         AND p2.gallery_images IS NOT NULL 
                         ORDER BY p2.price DESC LIMIT 1) AS photos,
                        rc.object_class_display_name
                    FROM residential_complexes rc
                    LEFT JOIN developers d ON rc.developer_id = d.id
                    LEFT JOIN districts dist ON rc.district_id = dist.id
                    LEFT JOIN properties p ON p.complex_id = rc.id
                    WHERE rc.id = :complex_id
                    GROUP BY rc.name, d.name, rc.address, dist.name, rc.id
                    LIMIT 1
                """)
                
                result = db.session.execute(complex_query, {'complex_id': str(complex_id)})
                row = result.fetchone()
                
                if row:
                    real_complex_name = row[0] or real_complex_name
                    real_developer_name = row[1] or real_developer_name  
                    real_address = row[2] or real_address
                    real_district = row[3] or real_district
                    real_min_price = int(row[4]) if row[4] else 0
                    real_max_price = int(row[5]) if row[5] else 0
                    real_object_class = row[7] or real_object_class
                    
                    # Парсим фото из JSON
                    if row[6]:
                        try:
                            import json
                            photos = json.loads(row[6]) if isinstance(row[6], str) else row[6]
                            if photos and isinstance(photos, list) and len(photos) > 0:
                                real_image = photos[0]  # Первое фото как основное
                        except Exception as photo_error:
                            print(f"DEBUG: Error parsing photos for property {prop.property_id}: {photo_error}")
                    
                    # Определяем статус по году сдачи
                    from datetime import datetime
                    current_year = datetime.now().year
                    
                    try:
                        # ✅ MIGRATED: Запрос статуса из normalized schema
                        status_query = text("""
                            SELECT end_build_year AS complex_building_end_build_year
                            FROM residential_complexes 
                            WHERE id = :complex_id 
                            AND end_build_year IS NOT NULL
                            LIMIT 1
                        """)
                        status_result = db.session.execute(status_query, {'complex_id': str(complex_id)})
                        status_row = status_result.fetchone()
                        
                        if status_row and status_row[0]:
                            build_year = int(status_row[0])
                            real_status = 'Сдан' if build_year <= current_year else 'Строится'
                    except:
                        pass
                        
            except Exception as e:
                print(f"Error loading real complex data for {complex_id}: {e}")
                # Продолжаем с fallback значениями
                pass
            
            # Add to favorites with REAL DATA
            favorite = ManagerFavoriteComplex(
                manager_id=current_manager.id,
                complex_id=str(complex_id),
                complex_name=real_complex_name,
                developer_name=real_developer_name,
                complex_address=real_address,
                district=real_district,
                min_price=real_min_price,
                max_price=real_max_price,
                complex_image=real_image,
                complex_url=data.get('url', f'/zk/{complex_id}'),
                status=real_status,
                object_class_display_name=real_object_class,
                notes=data.get('notes', ''),
                recommended_for=data.get('recommended_for', '')
            )
            
            db.session.add(favorite)
            db.session.commit()
            return jsonify({'success': True, 'favorited': True, 'message': 'ЖК добавлен в избранное'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@mgr_api_bp.route('/api/manager/complexes/favorites/list', methods=['GET'])
@manager_required
def manager_get_complex_favorites_list():
    """Get manager's favorite complexes with full details"""
    from models import ManagerFavoriteComplex, ResidentialComplex, Developer, District
    from sqlalchemy.orm import joinedload, selectinload
    from sqlalchemy import or_
    
    current_manager = current_user
    
    try:
        # Загружаем избранное без broken relationship
        favorites = db.session.query(ManagerFavoriteComplex)\
            .filter_by(manager_id=current_manager.id)\
            .order_by(ManagerFavoriteComplex.created_at.desc()).all()
        
        # Собираем ID комплексов для batch-загрузки
        complex_ids_str = [fav.complex_id for fav in favorites if fav.complex_id]
        complex_ids_int = []
        for cid in complex_ids_str:
            try:
                complex_ids_int.append(int(cid))
            except (ValueError, TypeError):
                pass
        
        # BYPASSING broken favorites data - use direct ResidentialComplex lookup since FK is broken
        # Get complex names from ResidentialComplex table using favorites complex_id (if exists)
        complex_names = []
        for fav in favorites:
            if fav.complex_id:
                try:
                    complex_int_id = int(fav.complex_id)
                    rc = ResidentialComplex.query.get(complex_int_id)
                    if rc and rc.name:
                        complex_names.append(rc.name)
                except (ValueError, TypeError):
                    pass
        
        # Fallback: If no matches found, use all residential complexes for demo
        if not complex_names:
            all_complexes = ResidentialComplex.query.limit(10).all()
            complex_names = [rc.name for rc in all_complexes if rc.name]
        
        # ENSURE we include ALL favorite complex names even if not in excel_data
        # This prevents missing complexes in comparison
        for fav in favorites:
            if fav.complex_id:
                try:
                    complex_int_id = int(fav.complex_id)
                    rc = ResidentialComplex.query.get(complex_int_id)
                    if rc and rc.name and rc.name not in complex_names:
                        complex_names.append(rc.name)
                        print(f"DEBUG: Added missing favorite complex to search: {rc.name}")
                except (ValueError, TypeError):
                    pass
        excel_data = {}
        
        if complex_names:
            # SQL aggregation with proper expanding bind and name normalization
            from sqlalchemy import text, bindparam
            
            # Normalize names for matching
            normalized_names = tuple({n.strip().lower().replace('«','"').replace('»','"') 
                                    for n in complex_names if n})
            
            stmt = text("""
            SELECT 
                rc.name as complex_name,
                MIN(p.price) as min_price,
                MAX(p.price) as max_price,
                COUNT(p.id) as apartments_count,
                rc.address AS address_display_name,
                (SELECT p2.gallery_images FROM properties p2 
                 WHERE p2.complex_id = rc.id AND p2.gallery_images IS NOT NULL 
                 LIMIT 1) AS photos
            FROM residential_complexes rc
            LEFT JOIN properties p ON p.complex_id = rc.id
            WHERE lower(rc.name) IN :names
            GROUP BY rc.id, rc.name, rc.address
            """).bindparams(bindparam('names', expanding=True))
            
            result = db.session.execute(stmt, {'names': normalized_names})
            for row in result:
                # Store with original complex name for mapping
                for original_name in complex_names:
                    if original_name and original_name.strip().lower().replace('«','"').replace('»','"') == row.complex_name.lower():
                        excel_data[original_name] = {
                            'min_price': int(row.min_price) if row.min_price else 0,
                            'max_price': int(row.max_price) if row.max_price else 0,
                            'apartments_count': int(row.apartments_count) if row.apartments_count else 0,
                            'sample_address': row.address_display_name or '',
                            'photos': row.photos
                        }
                        break
            
            print(f"DEBUG: Searched {len(normalized_names)} names, found {len(excel_data)} matches")
            print(f"DEBUG: excel_data keys: {list(excel_data.keys())[:2]}")  # First 2 keys
        
        
        # Загружаем все комплексы сразу с joined данными  
        complexes_data = {}
        if complex_ids_str:
            complexes_query = db.session.query(ResidentialComplex)\
                .options(
                    joinedload(ResidentialComplex.developer), 
                    joinedload(ResidentialComplex.district),
                    selectinload(ResidentialComplex.buildings)
                )\
                .filter(or_(
                    ResidentialComplex.id.in_(complex_ids_int),
                    ResidentialComplex.complex_id.in_(complex_ids_str)
                ))
            
            for complex_data in complexes_query:
                complexes_data[str(complex_data.id)] = complex_data
                if complex_data.complex_id:
                    complexes_data[str(complex_data.complex_id)] = complex_data
        
        favorites_list = []
        for fav in favorites:
            # ✅ ИСПРАВЛЕНИЕ: Ищем данные по ResidentialComplex таблице и excel_properties
            real_complex_name = 'ЖК без названия'
            real_developer_name = 'Застройщик не указан'
            real_address = 'Адрес не указан'
            real_district = 'Район не указан'
            real_min_price = 0
            real_max_price = 0
            real_image = '/static/images/no-photo.svg'
            real_status = 'В продаже'
            real_apartments_count = 0
            real_buildings_count = 1
            real_delivery_date = 'Не указано'
            
                # ✅ ИСПРАВЛЕНИЕ: Используем тот же SQL что и /residential-complexes для поиска по динамическим ID
            try:
                complex_db = None
                print(f"DEBUG: Searching for complex with fav.complex_id: {fav.complex_id}")
                
                if fav.complex_id:
                    # Сначала пробуем найти в residential_complexes (для старых записей)
                    try:
                        complex_int_id = int(fav.complex_id)
                        complex_db = ResidentialComplex.query.get(complex_int_id)
                        print(f"DEBUG: Found by id {complex_int_id}: {complex_db.name if complex_db else 'None'}")
                    except (ValueError, TypeError):
                        pass
                
                if complex_db and complex_db.name:
                    # Найдено в residential_complexes - используем эти данные
                    real_complex_name = complex_db.name
                    real_developer_name = complex_db.developer.name if complex_db.developer else real_developer_name
                    real_district = complex_db.district.name if complex_db.district else real_district
                    # Адрес берем из sales_address или оставляем placeholder для последующей загрузки из excel_properties
                    real_address = complex_db.sales_address if hasattr(complex_db, 'sales_address') and complex_db.sales_address else real_address
                    real_image = complex_db.main_image if hasattr(complex_db, 'main_image') and complex_db.main_image else real_image
                    print(f"DEBUG: ✅ Using residential_complexes data: {real_complex_name}")
                else:
                    # ✅ MIGRATED: Complex not found in residential_complexes table
                    # With normalized schema, all complexes should exist in residential_complexes
                    # If not found, will use default values set above
                    print(f"DEBUG: ⚠️ Complex with ID {fav.complex_id} not found in residential_complexes")
                
                # ✅ MIGRATED: Дополнительный поиск данных в normalized schema по названию ЖК (всегда выполняется)
                if real_complex_name != 'ЖК без названия':
                    from sqlalchemy import text
                    excel_query = text("""
                        SELECT 
                            MIN(p.price) as min_price,
                            MAX(p.price) as max_price,
                            COUNT(p.id) as apartments_count,
                            COUNT(DISTINCT b.id) as buildings_count,
                            rc.end_build_year AS complex_building_end_build_year,
                            rc.end_build_quarter AS complex_building_end_build_quarter,
                            (SELECT p2.gallery_images FROM properties p2 
                             WHERE p2.complex_id = rc.id AND p2.gallery_images IS NOT NULL 
                             LIMIT 1) AS photos,
                            rc.address AS address_display_name,
                            dist.name AS address_locality_name,
                            d.name as developer_name
                        FROM residential_complexes rc
                        LEFT JOIN properties p ON p.complex_id = rc.id
                        LEFT JOIN buildings b ON b.complex_id = rc.id
                        LEFT JOIN developers d ON rc.developer_id = d.id
                        LEFT JOIN districts dist ON rc.district_id = dist.id
                        WHERE rc.name = :complex_name
                        GROUP BY rc.id, rc.end_build_year, rc.end_build_quarter, rc.address, dist.name, d.name
                        LIMIT 1
                    """)
                    
                    # Use exact match on complex name (no LIKE pattern needed)
                    print(f"DEBUG: Searching normalized schema for complex: {real_complex_name}")
                    result = db.session.execute(excel_query, {'complex_name': real_complex_name})
                    row = result.fetchone()
                    
                    print(f"DEBUG: Normalized schema query result - found: {row is not None}, has price: {row[0] if row else 'N/A'}")
                    if row:
                        print(f"DEBUG: Normalized data - address: {row[7]}, district: {row[8]}, developer: {row[9]}")
                    
                    if row and row[0]:  # Если найдены данные
                        real_min_price = int(row[0]) if row[0] else 0
                        real_max_price = int(row[1]) if row[1] else 0
                        real_apartments_count = int(row[2]) if row[2] else 0
                        # Determine real buildings count
                        real_buildings_count = max(int(row[3]) if row[3] else 1, 1)
                        
                        # FINAL OVERRIDE: Check if the residential_complexes table has a buildings_count field to override
                        if complex_db:
                            if hasattr(complex_db, 'buildings_count') and complex_db.buildings_count:
                                real_buildings_count = complex_db.buildings_count
                            elif hasattr(complex_db, 'total_buildings') and complex_db.total_buildings:
                                real_buildings_count = complex_db.total_buildings
                            elif hasattr(complex_db, 'buildings') and complex_db.buildings:
                                b_count = len(complex_db.buildings)
                                if b_count > 0:
                                    real_buildings_count = b_count
                        
                        # Парсим фото из JSON
                        if row[6]:
                            try:
                                import json
                                photos = json.loads(row[6]) if isinstance(row[6], str) else row[6]
                                if photos and isinstance(photos, list) and len(photos) > 0:
                                    # Берем фото ЖК, пропуская интерьеры квартир
                                    start_index = min(len(photos) // 4, 5) if len(photos) > 8 else 1
                                    real_image = photos[start_index] if len(photos) > start_index else photos[0]
                            except Exception as photo_error:
                                print(f"DEBUG: Error parsing photos for property {prop.property_id}: {photo_error}")
                        
                        # Fix price display and metadata
                        price_from_val = int(row[0]) if row[0] else 0
                        
                        complex_data = {
                            'id': row[4],
                            'name': row[5],
                            'price_from': price_from_val,
                            'min_price': price_from_val,
                            'real_price_from': price_from_val,
                            'apartments_count': real_apartments_count,
                            'buildings_count': real_buildings_count,
                            'photos': photos,
                            'address': row[7],
                            'district': row[8],
                            'developer': row[9]
                        }
                        
                        # Определяем статус и дату сдачи
                        if row[4] and row[5]:  # end_build_year и end_build_quarter
                            build_year = int(row[4])
                            build_quarter = int(row[5])
                            quarter_names = {1: 'I', 2: 'II', 3: 'III', 4: 'IV'}
                            quarter = quarter_names.get(build_quarter, build_quarter)
                            real_delivery_date = f"{quarter} кв. {build_year} г."
                            
                            from datetime import datetime
                            current_year = datetime.now().year
                            real_status = 'Сдан' if build_year <= current_year else 'Строится'
                        elif row[4]:  # только год
                            build_year = int(row[4])
                            real_delivery_date = f"{build_year} г."
                            from datetime import datetime
                            real_status = 'Сдан' if build_year <= datetime.now().year else 'Строится'
                                
            except Exception as e:
                print(f"Error loading complex data for {fav.complex_id}: {e}")
                pass
            
            # Ищем полные данные ЖК (ResidentialComplex)
            complex_data = complexes_data.get(str(fav.complex_id))
            
            # Безопасный способ создания slug с fallback
            try:
                url = f"/zk/{create_slug(real_complex_name)}" if real_complex_name and real_complex_name != 'ЖК без названия' else '#'
            except:
                url = '#'
            
            # ✅ Подтягиваем реальный кэшбек из ResidentialComplex или используем значение по умолчанию
            cashback_rate = 5.0
            real_cashback_rate = 5.0
            real_housing_class = 'Комфорт'
            if complex_data:
                real_cashback_rate = complex_data.cashback_rate if complex_data.cashback_rate else 5.0
                real_housing_class = complex_data.object_class_display_name if complex_data.object_class_display_name else 'Комфорт'
            
            # ✅ ИСПОЛЬЗУЕМ ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ - игнорируем старые placeholder
            favorites_list.append({
                'id': str(fav.complex_id),
                'name': real_complex_name,
                'developer': real_developer_name,
                'address': real_address,
                'district': real_housing_class,  # ✅ Показываем класс жилья вместо района
                'housing_class': real_housing_class,  # ✅ Класс жилья
                'min_price': real_min_price,
                'max_price': real_max_price,
                'apartments_count': real_apartments_count,
                'buildings_count': real_buildings_count,
                'image': real_image,
                'url': url,
                'status': real_status,
                'delivery_date': real_delivery_date,
                'notes': fav.notes or '',
                'recommended_for': fav.recommended_for or '',
                'created_at': fav.created_at.strftime('%d.%m.%Y в %H:%M') if fav.created_at else 'Недавно',
                'cashback_rate': real_cashback_rate  # ✅ Реальный кэшбек из базы данных
            })
        
        print(f"Found {len(favorites)} favorite complexes for manager {current_manager.id}")
        if favorites:
            print(f"First complex: {favorites_list[0]}")
        
        return jsonify({
            'success': True,
            'complexes': favorites_list,
            'favorite_complexes': favorites_list,  # добавить alias
            'favorites': favorites_list  # добавить alias
        })
    
    except Exception as e:
        print(f"Error loading favorite complexes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# User Management Routes


# ==================== MANAGER VIDEO, EMPLOYEES, REVIEWS & PUSH (extracted from app.py) ====================
@mgr_api_bp.route('/api/manager/complex/<int:complex_id>/video/add-link', methods=['POST'])
@admin_required
def add_complex_video_link(complex_id):
    """Добавить ссылку на видео для ЖК (только для менеджеров)"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        video_type = data.get('type', 'youtube')
        
        if not url or not title:
            return jsonify({'success': False, 'error': 'URL и название обязательны'}), 400
        
        # Получаем комплекс
        complex = ResidentialComplex.query.get(complex_id)
        if not complex:
            return jsonify({'success': False, 'error': 'Комплекс не найден'}), 404
        
        # Парсим существующие видео
        existing_videos = []
        if complex.videos:
            try:
                existing_videos = json.loads(complex.videos)
            except:
                existing_videos = []
        
        # Добавляем новое видео
        new_video = {
            'type': video_type,
            'url': url,
            'title': title
        }
        if description:
            new_video['description'] = description
        
        existing_videos.append(new_video)
        
        # Сохраняем
        complex.videos = json.dumps(existing_videos, ensure_ascii=False)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Видео успешно добавлено',
            'videos_count': len(existing_videos)
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error adding video link: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@mgr_api_bp.route('/api/manager/complex/<int:complex_id>/video/upload', methods=['POST'])
@admin_required
def upload_complex_video(complex_id):
    """Загрузить видео файл для ЖК (только для администраторов)"""
    current_app.logger.info(f"=== VIDEO UPLOAD START: complex_id={complex_id}")
    current_app.logger.info(f"=== request.files keys: {list(request.files.keys())}")
    
    try:
        import os
        from werkzeug.utils import secure_filename
        
        # Проверяем файл
        if 'video' not in request.files:
            current_app.logger.error("=== ERROR: 'video' not in request.files")
            return jsonify({'success': False, 'error': 'Файл не найден'}), 400
        
        file = request.files['video']
        current_app.logger.info(f"=== File received: {file.filename}")
        
        if file.filename == '':
            current_app.logger.error("=== ERROR: Empty filename")
            return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
        
        # Проверяем расширение
        allowed_extensions = {'mp4', 'webm', 'mov', 'avi'}
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        
        current_app.logger.info(f"=== File extension: {file_ext}")
        
        if file_ext not in allowed_extensions:
            current_app.logger.error(f"=== ERROR: Invalid extension {file_ext}")
            return jsonify({'success': False, 'error': 'Неподдерживаемый формат видео'}), 400
        
        # Получаем комплекс
        complex = ResidentialComplex.query.get(complex_id)
        if not complex:
            current_app.logger.error(f"=== ERROR: Complex {complex_id} not found")
            return jsonify({'success': False, 'error': 'Комплекс не найден'}), 404
        
        current_app.logger.info(f"=== Complex found: {complex.name}, slug: {complex.slug}")
        
        # Создаем уникальное имя файла
        import uuid
        unique_filename = f"{complex.slug}_{uuid.uuid4().hex[:8]}.{file_ext}"
        
        # Путь для сохранения
        upload_folder = 'static/uploads/complexes/videos'
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, unique_filename)
        
        current_app.logger.info(f"=== Saving file to: {file_path}")
        
        # Сохраняем файл
        file.save(file_path)
        
        # Обновляем БД
        relative_path = f"/{file_path}"
        complex.uploaded_video = relative_path
        db.session.commit()
        
        current_app.logger.info(f"=== VIDEO UPLOAD SUCCESS: {relative_path}")
        
        return jsonify({
            'success': True,
            'message': 'Видео успешно загружено',
            'video_path': relative_path
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"=== VIDEO UPLOAD EXCEPTION: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500
        print(f"Error uploading video: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@mgr_api_bp.route('/api/manager/complex/<int:complex_id>/video/delete', methods=['DELETE'])
@manager_required  
def delete_complex_video(complex_id):
    """Удалить видео (ссылку или файл) для ЖК"""
    try:
        data = request.get_json()
        video_index = data.get('video_index')  # Индекс видео в массиве videos
        delete_uploaded = data.get('delete_uploaded', False)  # Удалить загруженное видео
        
        complex = ResidentialComplex.query.get(complex_id)
        if not complex:
            return jsonify({'success': False, 'error': 'Комплекс не найден'}), 404
        
        if video_index is not None:
            # Удаляем видео из массива
            if complex.videos:
                try:
                    videos = json.loads(complex.videos)
                    if 0 <= video_index < len(videos):
                        videos.pop(video_index)
                        complex.videos = json.dumps(videos, ensure_ascii=False) if videos else None
                except:
                    return jsonify({'success': False, 'error': 'Ошибка парсинга видео'}), 400
        
        if delete_uploaded and complex.uploaded_video:
            # Удаляем файл с диска
            import os
            try:
                file_path = complex.uploaded_video.lstrip('/')
                if os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
            complex.uploaded_video = None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Видео успешно удалено'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting video: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===== BATCH GEOCODE FOR MINI MAP FIX =====
@mgr_api_bp.route('/api/mini-map/batch-geocode', methods=['GET'])
@csrf.exempt
def batch_geocode_for_minimap():
    """
    Batch geocode properties without coordinates
    Fixes mini-map showing only 6/106 properties
    """
    try:
        from models import Property
        from services.geocoding import get_geocoding_service
        
        props_no_coords = Property.query.filter(
            ((Property.latitude.is_(None)) | (Property.latitude == 0)) &
            ((Property.longitude.is_(None)) | (Property.longitude == 0))
        ).limit(50).all()  # Process 50 at a time
        
        if not props_no_coords:
            return jsonify({'success': True, 'geocoded': 0, 'message': 'All properties have coordinates'})
        
        geocoding_service = get_geocoding_service()
        geocoded = 0
        
        for prop in props_no_coords:
            if not prop.address:
                continue
            try:
                result = geocoding_service.forward_geocode(prop.address)
                if result and result.get('latitude') and result.get('longitude'):
                    prop.latitude = float(result['latitude'])
                    prop.longitude = float(result['longitude'])
                    geocoded += 1
            except:
                pass
        
        db.session.commit()
        return jsonify({'success': True, 'geocoded': geocoded, 'remaining': len(props_no_coords)})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mgr_api_bp.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    """API endpoint for changing password (including forced change after temp password)"""
    try:
        data = request.get_json()
        new_password = data.get('new_password', '').strip()
        confirm_password = data.get('confirm_password', '').strip()
        
        if not new_password or len(new_password) < 6:
            return jsonify({'success': False, 'message': 'Пароль должен содержать минимум 6 символов'}), 400
        
        if new_password != confirm_password:
            return jsonify({'success': False, 'message': 'Пароли не совпадают'}), 400
        
        # Update password
        current_user.set_password(new_password)
        current_user.must_change_password = False
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Пароль успешно изменён'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500


@mgr_api_bp.route('/api/manager/employees/<int:manager_id>/dismiss', methods=['POST'])
@manager_required
def api_dismiss_employee(manager_id):
    from models import Manager, Department, OrgRole
    current_manager = current_user
    role = current_manager.org_role
    can_view_all = role.can_view_all_deals if role else False
    can_view_dept = role.can_view_department_deals if role else False
    is_rop = getattr(current_manager, 'is_rop', False) or can_view_dept or can_view_all
    
    if not is_rop:
        return jsonify({'success': False, 'error': 'Нет прав на управление сотрудниками'}), 403
    
    if manager_id == current_manager.id:
        return jsonify({'success': False, 'error': 'Нельзя уволить самого себя'}), 400
    
    target = Manager.query.get(manager_id)
    if not target:
        return jsonify({'success': False, 'error': 'Сотрудник не найден'}), 404
    
    if not can_view_all:
        if current_manager.department_id:
            dept = Department.query.get(current_manager.department_id)
            dept_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
            if target.id not in dept_ids:
                return jsonify({'success': False, 'error': 'Сотрудник не в вашем отделе'}), 403
        else:
            return jsonify({'success': False, 'error': 'Вы не привязаны к отделу'}), 403
    
    reassign_to_id = request.json.get('reassign_to_id') if request.json else None
    
    from models import Deal
    active_deals = Deal.query.filter(
        Deal.manager_id == target.id,
        ~Deal.status.in_(['completed', 'successful', 'rejected', 'cancelled'])
    ).all()
    
    if active_deals and reassign_to_id:
        reassign_to = Manager.query.get(reassign_to_id)
        if not reassign_to or not reassign_to.is_active:
            return jsonify({'success': False, 'error': 'Менеджер для переназначения не найден или неактивен'}), 400
        for deal in active_deals:
            deal.manager_id = reassign_to_id
    elif active_deals and not reassign_to_id:
        return jsonify({
            'success': False,
            'error': 'У сотрудника есть активные сделки. Выберите менеджера для переназначения.',
            'active_deals_count': len(active_deals),
            'needs_reassignment': True
        }), 400
    
    target.is_active = False
    db.session.commit()
    
    msg = f'{target.full_name or target.email} уволен(а)'
    if active_deals and reassign_to_id:
        reassign_to = Manager.query.get(reassign_to_id)
        msg += f'. {len(active_deals)} сделок переданы {reassign_to.full_name}'
    return jsonify({'success': True, 'message': msg})


@mgr_api_bp.route('/api/manager/employee/<int:manager_id>/profile')
@manager_required
def api_employee_profile(manager_id):
    from models import Manager, Department, OrgRole, Deal, DealHistory, DealTask, User, ManagerCheckin
    from datetime import datetime, timedelta
    import pytz
    import traceback
    
    try:
        current_manager = current_user
        employee = Manager.query.get(manager_id)
        if not employee:
            return jsonify({'success': False, 'error': 'Сотрудник не найден'}), 404
        
        role = current_manager.org_role
        can_view_all = role.can_view_all_deals if role else False
        can_view_dept = role.can_view_department_deals if role else False
        
        if not can_view_all and employee.id != current_manager.id:
            if can_view_dept and current_manager.department_id:
                dept = Department.query.get(current_manager.department_id)
                dept_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
                if employee.id not in dept_ids:
                    return jsonify({'success': False, 'error': 'Нет доступа'}), 403
            elif not can_view_dept or not current_manager.department_id:
                return jsonify({'success': False, 'error': 'Нет доступа'}), 403
    
        emp_role = employee.org_role.name if employee.org_role else (employee.position or 'Менеджер')
        emp_department = employee.department.name if employee.department else None
    
        msk = pytz.timezone('Europe/Moscow')
        now_msk = datetime.now(msk)
        today_start = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
    
        checkin = ManagerCheckin.query.filter(
            ManagerCheckin.manager_id == employee.id,
            ManagerCheckin.check_in_time >= today_start.astimezone(pytz.utc).replace(tzinfo=None)
        ).order_by(ManagerCheckin.check_in_time.desc()).first()
        is_online = checkin is not None and checkin.check_out_time is None
    
        active_deals = Deal.query.filter(
            Deal.manager_id == employee.id,
            ~Deal.status.in_(['completed', 'successful', 'rejected', 'cancelled'])
        ).count()
        completed_deals = Deal.query.filter(
            Deal.manager_id == employee.id,
            Deal.status.in_(['completed', 'successful'])
        ).count()
        clients = User.query.filter_by(assigned_manager_id=employee.id).count()
        pending_tasks = DealTask.query.join(Deal).filter(
            Deal.manager_id == employee.id,
            DealTask.is_completed == False
        ).count()
    
        subordinates = []
        if employee.department_id:
            dept = Department.query.get(employee.department_id)
            if dept and dept.head_manager_id == employee.id:
                subs = Manager.query.filter(
                    Manager.department_id == employee.department_id,
                    Manager.id != employee.id,
                    Manager.is_active == True
                ).all()
                subordinates = [{'id': s.id, 'full_name': s.full_name, 'role': s.org_role.name if s.org_role else (s.position or 'Менеджер'), 'avatar': s.profile_image, 'initials': (s.first_name or '?')[0].upper()} for s in subs]
    
        supervisor = None
        if employee.department_id:
            dept = Department.query.get(employee.department_id)
            if dept and dept.head_manager_id and dept.head_manager_id != employee.id:
                sup = Manager.query.get(dept.head_manager_id)
                if sup:
                    supervisor = {'id': sup.id, 'full_name': sup.full_name, 'role': sup.org_role.name if sup.org_role else (sup.position or 'Руководитель'), 'avatar': sup.profile_image, 'initials': (sup.first_name or '?')[0].upper()}
    
        recent_activities = []
        week_ago = datetime.utcnow() - timedelta(days=7)
        histories = DealHistory.query.join(Deal).filter(
            Deal.manager_id == employee.id,
            DealHistory.created_at >= week_ago
        ).order_by(DealHistory.created_at.desc()).limit(10).all()
        msk_tz = pytz.timezone('Europe/Moscow')
        for h in histories:
            created_msk = pytz.utc.localize(h.created_at).astimezone(msk_tz) if h.created_at else None
            recent_activities.append({
                'action': h.action,
                'description': h.description,
                'created_at': created_msk.strftime('%d.%m.%Y %H:%M') if created_msk else ''
            })
    
        return jsonify({
                'success': True,
                'employee': {
                    'id': employee.id,
                    'full_name': employee.full_name,
                    'first_name': employee.first_name,
                    'last_name': employee.last_name,
                    'email': employee.email,
                    'phone': employee.phone,
                    'position': employee.position,
                    'avatar': employee.profile_image,
                    'initials': (employee.first_name or employee.email or '?')[0].upper(),
                    'role': emp_role,
                    'department': emp_department,
                    'is_online': is_online,
                    'stats': {
                        'active_deals': active_deals,
                        'completed_deals': completed_deals,
                        'clients': clients,
                        'pending_tasks': pending_tasks
                    },
                    'subordinates': subordinates,
                    'supervisor': supervisor,
                    'recent_activities': recent_activities
                }
            })
    except Exception as e:
        print(f"ERROR in api_employee_profile: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'Ошибка сервера: {str(e)}'}), 500


@mgr_api_bp.route('/api/user/notification-settings', methods=['POST'])
@login_required
def api_user_notification_settings():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data'}), 400

    allowed = ['email_notifications', 'telegram_notifications', 'notify_recommendations',
               'notify_saved_searches', 'notify_applications', 'notify_cashback',
               'notify_marketing', 'preferred_contact']

    for key in allowed:
        if key in data:
            if key == 'preferred_contact':
                if data[key] in ('email', 'phone', 'telegram', 'whatsapp', 'both'):
                    setattr(current_user, key, data[key])
            else:
                setattr(current_user, key, bool(data[key]))

    db.session.commit()
    return jsonify({'success': True})


@mgr_api_bp.route('/api/complex/<int:complex_id>/reviews')
def api_complex_reviews(complex_id):
    from models import ComplexReview
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 50)
    reviews = ComplexReview.query.filter_by(
        residential_complex_id=complex_id, status='approved'
    ).order_by(ComplexReview.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    result = []
    for r in reviews.items:
        result.append({
            'id': r.id,
            'author_name': r.author_name,
            'rating': r.rating,
            'title': r.title or '',
            'text': r.text,
            'pros': r.pros or '',
            'cons': r.cons or '',
            'is_resident': r.is_resident,
            'purchase_year': r.purchase_year,
            'created_at': r.created_at.strftime('%d.%m.%Y') if r.created_at else ''
        })
    avg_rating = db.session.query(db.func.avg(ComplexReview.rating)).filter_by(
        residential_complex_id=complex_id, status='approved'
    ).scalar()
    total_count = ComplexReview.query.filter_by(
        residential_complex_id=complex_id, status='approved'
    ).count()
    return jsonify({
        'reviews': result,
        'total': total_count,
        'avg_rating': round(float(avg_rating), 1) if avg_rating else 0,
        'page': page,
        'pages': reviews.pages
    })


@mgr_api_bp.route('/api/complex/<int:complex_id>/reviews/submit', methods=['POST'])
def api_submit_complex_review(complex_id):
    from models import ComplexReview, ResidentialComplex
    complex_obj = ResidentialComplex.query.get_or_404(complex_id)
    
    author_name = request.form.get('author_name', '').strip()
    author_email = request.form.get('author_email', '').strip()
    rating = request.form.get('rating', 0, type=int)
    title = request.form.get('title', '').strip()
    text = request.form.get('text', '').strip()
    pros = request.form.get('pros', '').strip()
    cons = request.form.get('cons', '').strip()
    is_resident = request.form.get('is_resident') == 'on'
    purchase_year = request.form.get('purchase_year', type=int)
    
    if not author_name or not text or rating < 1 or rating > 5:
        flash('Пожалуйста, заполните имя, текст отзыва и поставьте оценку.', 'error')
        return redirect(request.referrer or '/')
    
    if len(text) < 10:
        flash('Текст отзыва должен содержать минимум 10 символов.', 'error')
        return redirect(request.referrer or '/')
    
    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
        if not author_name:
            author_name = current_user.name or current_user.username or 'Пользователь'
    
    review = ComplexReview(
        residential_complex_id=complex_id,
        user_id=user_id,
        author_name=author_name,
        author_email=author_email,
        rating=rating,
        title=title,
        text=text,
        pros=pros,
        cons=cons,
        is_resident=is_resident,
        purchase_year=purchase_year,
        status='pending'
    )
    db.session.add(review)
    db.session.commit()
    
    flash('Спасибо за ваш отзыв! Он будет опубликован после проверки модератором.', 'success')
    return redirect(request.referrer or '/')


def _capitalize_name(name):
    """Capitalize each word in a name (works for Иванов, иванов, ИВАНОВ → Иванов)."""
    if not name:
        return name
    return ' '.join(w.capitalize() for w in str(name).strip().split())


@mgr_api_bp.route('/api/admin/push-stats')
@login_required
def api_admin_push_stats():
    """Return aggregated push subscription counts for admin dashboard."""
    from models import PushSubscription
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        total   = PushSubscription.query.filter_by(is_active=True).count()
        users   = PushSubscription.query.filter(PushSubscription.is_active == True, PushSubscription.user_id.isnot(None)).count()
        managers = PushSubscription.query.filter(PushSubscription.is_active == True, PushSubscription.manager_id.isnot(None)).count()
        guests  = PushSubscription.query.filter(PushSubscription.is_active == True, PushSubscription.user_id.is_(None), PushSubscription.manager_id.is_(None)).count()
        return jsonify({'total': total, 'users': users, 'managers': managers, 'guests': guests})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
