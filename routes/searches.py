"""
Searches & Collections Blueprint — collection views, manager searches,
user saved searches, alert settings, book-appointment, cities/districts API.
Routes: /collections, /collection/*, /manager/collections/*, /api/manager/collection/*,
        /api/manager/saved-searches, /api/manager/send-search, /book-appointment,
        /api/manager/client/*/send-credentials, /api/request-payout, /api/change-city,
        /api/cities, /api/districts/*, /api/searches, /api/user/saved-searches/*,
        /api/user/alert-settings, /api/user/unsubscribe/*, /api/searches/*
"""
import json
import logging
import os
from datetime import datetime

from flask import (Blueprint, jsonify, request, current_app, send_file,
                   render_template, redirect, url_for, session)
from flask_login import current_user, login_required

from app import db, csrf

logger = logging.getLogger(__name__)

searches_bp = Blueprint('searches', __name__)

from app import manager_required, require_json_csrf

# Collection routes for clients
@searches_bp.route('/collections', endpoint='client_collections')
@login_required
def client_collections():
    """Show all collections assigned to current user"""
    from models import Collection
    collections = Collection.query.filter_by(assigned_to_user_id=current_user.id).order_by(Collection.created_at.desc()).all()
    return render_template('auth/client_collections.html', collections=collections)

@searches_bp.route('/collection/<int:collection_id>', endpoint='view_collection')
@login_required
def view_collection(collection_id):
    """View specific collection details"""
    from models import Collection
    collection = Collection.query.filter_by(id=collection_id, assigned_to_user_id=current_user.id).first()
    if not collection:
        flash('Подборка не найдена', 'error')
        return redirect(url_for('client_collections'))
    
    # Mark as viewed
    if collection.status == 'Отправлена':
        collection.status = 'Просмотрена'
        collection.viewed_at = datetime.utcnow()
        db.session.commit()
    
    return render_template('auth/view_collection.html', collection=collection)

@searches_bp.route('/collection/<int:collection_id>/mark-viewed', methods=['POST'])
@login_required
def mark_collection_viewed(collection_id):
    """Mark collection as viewed"""
    from models import Collection
    collection = Collection.query.filter_by(id=collection_id, assigned_to_user_id=current_user.id).first()
    if collection and collection.status == 'Отправлена':
        collection.status = 'Просмотрена'
        collection.viewed_at = datetime.utcnow()
        db.session.commit()
    return jsonify({'success': True})

# Manager collection routes
@searches_bp.route('/manager/collections/new', methods=['POST'])
@manager_required
def save_collection():
    """Save new collection"""
    from models import Collection, CollectionProperty, Manager
    
    current_manager = current_user
    
    title = request.form.get('title')
    description = request.form.get('description', '')
    assigned_to_user_id = request.form.get('assigned_to_user_id')
    tags = request.form.get('tags', '')
    action = request.form.get('action')
    property_ids = request.form.getlist('property_ids[]')
    property_notes = request.form.getlist('property_notes[]')
    
    if not title or not assigned_to_user_id:
        flash('Заполните обязательные поля', 'error')
        return render_template('manager/create_collection.html', manager=current_manager)
    
    try:
        # Create collection
        collection = Collection(
            title=title,
            description=description,
            created_by_manager_id=current_manager.id,
            assigned_to_user_id=int(assigned_to_user_id),
            tags=tags,
            status='Отправлена' if action == 'send' else 'Черновик',
            sent_at=datetime.utcnow() if action == 'send' else None
        )
        
        db.session.add(collection)
        db.session.flush()  # Get collection ID
        
        # Add properties to collection
        import json
        with open('data/properties.json', 'r', encoding='utf-8') as f:
            properties_data = json.load(f)
        
        properties_dict = {prop['id']: prop for prop in properties_data}
        
        for i, prop_id in enumerate(property_ids):
            if prop_id in properties_dict:
                prop_data = properties_dict[prop_id]
                note = property_notes[i] if i < len(property_notes) else ''
                
                # DUAL WRITE: Resolve property to get both IDs
                property_obj, canonical_id = resolve_property_by_identifier(prop_id)
                if not property_obj:
                    continue  # Skip properties that don't exist in database
                
                collection_property = CollectionProperty(
                    collection_id=collection.id,
                    property_id=str(property_obj.id),  # Old: database ID
                    property_inner_id=property_obj.inner_id,  # NEW: canonical inner_id
                    property_name=prop_data['title'],
                    property_price=prop_data['price'],
                    complex_name=prop_data.get('residential_complex', ''),
                    property_type=f"{prop_data['rooms']}-комн",
                    property_size=prop_data.get('area'),
                    manager_note=note,
                    order_index=i
                )
                db.session.add(collection_property)
        
        db.session.commit()
        
        action_text = 'отправлена клиенту' if action == 'send' else 'сохранена как черновик'
        flash(f'Подборка "{title}" успешно {action_text}', 'success')
        return redirect(url_for('mgr.manager_collections'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при сохранении подборки: {str(e)}', 'error')
        return render_template('manager/create_collection.html', manager=current_manager)

@searches_bp.route('/api/manager/collection/<int:collection_id>/send', methods=['POST'])
@manager_required
def api_send_collection(collection_id):
    """Send collection to client"""
    from models import Collection
    
    current_manager = current_user
    collection = Collection.query.filter_by(id=collection_id, created_by_manager_id=current_manager.id).first()
    
    if not collection:
        return jsonify({'success': False, 'error': 'Подборка не найдена'}), 404
    
    if not collection.assigned_to_user_id:
        return jsonify({'success': False, 'error': 'Клиент не назначен'}), 400
    
    try:
        collection.status = 'Отправлена'
        collection.sent_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/manager/collection/<int:collection_id>/delete', methods=['DELETE'])
@manager_required 
def api_delete_collection(collection_id):
    """Delete collection"""
    from models import Collection
    
    current_manager = current_user
    collection = Collection.query.filter_by(id=collection_id, created_by_manager_id=current_manager.id).first()
    
    if not collection:
        return jsonify({'success': False, 'error': 'Подборка не найдена'}), 404
    
    try:
        db.session.delete(collection)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

# Manager Saved Searches API routes
@searches_bp.route('/api/manager/saved-searches')
@manager_required
def get_manager_saved_searches():
    """Get manager's saved searches"""
    from models import ManagerSavedSearch
    
    current_manager = current_user
    try:
        searches = ManagerSavedSearch.query.filter_by(manager_id=current_manager.id).order_by(ManagerSavedSearch.last_used.desc()).all()
        searches_list = [search.to_dict() for search in searches]
        
        return jsonify({
            'success': True,
            'searches': searches_list,
            'count': len(searches_list)
        })
    except Exception as e:
        print(f"Error loading manager saved searches: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/manager/saved-searches', methods=['POST'])
@manager_required
@csrf.exempt  # Temporarily disabled for debugging
def create_manager_saved_search():
    """Create a new saved search for manager"""
    from models import ManagerSavedSearch
    import json
    
    print(f"DEBUG: ===== create_manager_saved_search API CALLED =====")
    print(f"DEBUG: Method: {request.method}")
    print(f"DEBUG: Path: {request.path}")
    # Log safe headers only (no cookies/tokens)
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in ['cookie', 'authorization']}
    print(f"DEBUG: Headers: {safe_headers}")
    
    current_manager = current_user
    print(f"DEBUG: Manager ID: {current_manager.id}")
    
    data = request.get_json()
    print(f"DEBUG: Raw request JSON: {data}")
    print(f"DEBUG: JSON type: {type(data)}")
    
    try:
        # Extract filters from the request
        filters = data.get('filters', {})
        print(f"DEBUG: Creating manager search with filters: {filters}")
        print(f"DEBUG: Full request data: {data}")
        print(f"DEBUG: Filters type: {type(filters)}")
        print(f"DEBUG: Filters empty check: {bool(filters)}")
        
        # Test if filters is actually empty - force some test data if needed
        if not filters or not any(filters.values()):
            print("DEBUG: Filters are empty, checking raw JSON...")
            raw_json = request.get_data(as_text=True)
            print(f"DEBUG: Raw request body: {raw_json}")
        
        filters_json = json.dumps(filters) if filters else None
        print(f"DEBUG: Filters JSON: {filters_json}")
        
        # Create new search
        search = ManagerSavedSearch(
            manager_id=current_manager.id,
            name=data.get('name'),
            description=data.get('description'),
            search_type=data.get('search_type', 'properties'),
            additional_filters=filters_json,
            is_template=data.get('is_template', False)
        )
        
        db.session.add(search)
        db.session.commit()
        print(f"DEBUG: Saved search with ID: {search.id}, additional_filters: {search.additional_filters}")
        
        # Verify the saved data
        db.session.refresh(search)
        print(f"DEBUG: Refreshed search additional_filters: {search.additional_filters}")
        
        return jsonify({
            'success': True,
            'search': search.to_dict(),
            'message': 'Поиск успешно сохранён'
        })
    except Exception as e:
        db.session.rollback()
        print(f"Error creating manager saved search: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/manager/send-search', methods=['POST'])
@manager_required
@csrf.exempt  # Temporarily disabled for debugging
def send_search_to_client():
    """Send manager's saved search to a client"""
    from models import ManagerSavedSearch, SentSearch, User, SavedSearch, UserNotification
    from email_service import send_notification
    import json
    
    current_manager = current_user
    data = request.get_json()
    
    try:
        search_id = data.get('search_id')
        client_id = data.get('client_id')
        message = data.get('message', '')
        
        # Get manager search
        manager_search = ManagerSavedSearch.query.filter_by(id=search_id, manager_id=current_manager.id).first()
        if not manager_search:
            return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
            
        # Get client
        client = User.query.get(client_id)
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
            
        # Create SavedSearch for client (copy ALL fields from manager search)
        # Parse additional_filters JSON to extract individual filter fields
        parsed_filters = {}
        if manager_search.additional_filters:
            try:
                parsed_filters = json.loads(manager_search.additional_filters)
            except (json.JSONDecodeError, TypeError):
                parsed_filters = {}
        
        # Extract values: prefer dedicated columns, fall back to additional_filters JSON
        def get_filter(field, json_keys=None, cast_type=None):
            val = getattr(manager_search, field, None)
            if val is not None:
                return val
            if json_keys:
                for key in json_keys:
                    v = parsed_filters.get(key)
                    if v is not None and v != '' and v != []:
                        if cast_type:
                            try:
                                return cast_type(v)
                            except (ValueError, TypeError):
                                pass
                        return v
            return None
        
        # Get rooms/property_type from filters
        rooms = parsed_filters.get('rooms', [])
        rooms_str = None
        if rooms:
            if isinstance(rooms, list):
                rooms_str = ','.join(str(r) for r in rooms)
            else:
                rooms_str = str(rooms)
        
        client_search = SavedSearch(
            user_id=client_id,
            name=f"От менеджера: {manager_search.name}",
            description=f"{manager_search.description or ''}\n\n{message}".strip(),
            search_type=manager_search.search_type or 'properties',
            location=get_filter('location', ['location', 'district']),
            property_type=rooms_str or get_filter('property_type', ['property_type']),
            price_min=get_filter('price_min', ['price_min', 'priceMin'], int),
            price_max=get_filter('price_max', ['price_max', 'priceMax'], int),
            size_min=get_filter('size_min', ['size_min', 'areaMin', 'area_min'], float),
            size_max=get_filter('size_max', ['size_max', 'areaMax', 'area_max'], float),
            developer=get_filter('developer', ['developer', 'developers']),
            complex_name=get_filter('complex_name', ['complex_name', 'residential_complex']),
            floor_min=get_filter('floor_min', ['floor_min', 'floorMin'], int),
            floor_max=get_filter('floor_max', ['floor_max', 'floorMax'], int),
            cashback_min=get_filter('cashback_min', ['cashback_min'], int),
            additional_filters=manager_search.additional_filters,
            notify_new_matches=True
        )
        
        db.session.add(client_search)
        db.session.flush()  # Get the ID before final commit
        
        # Create sent search record
        sent_search = SentSearch(
            manager_id=current_manager.id,
            client_id=client_id,
            manager_search_id=search_id,
            name=manager_search.name,
            description=manager_search.description,
            additional_filters=manager_search.additional_filters,
            status='sent'
        )
        
        db.session.add(sent_search)
        db.session.flush()  # Get sent_search ID
        
        # Note: client_search is now created and linked via sent_search record
        
        # Update usage count
        manager_search.usage_count = (manager_search.usage_count or 0) + 1
        manager_search.last_used = datetime.utcnow()
        
        # Create notification for client
        notification = UserNotification(
            user_id=client_id,
            title="Новый поиск от менеджера",
            message=f"Ваш менеджер отправил вам поиск: {manager_search.name}",
            notification_type='info',
            icon='fas fa-search',
            action_url='/dashboard'
        )
        
        db.session.add(notification)
        
        # Логируем отправку поиска
        from models import UserActivity
        UserActivity.log_activity(
            user_id=client_id,
            activity_type='search_received',
            description=f'Получен новый поиск от менеджера: {manager_search.name}'
        )
        
        db.session.commit()
        
        # Send email notification
        try:
            send_notification(
                client.email,
                f"Новый поиск от менеджера: {manager_search.name}",
                f"Ваш менеджер отправил вам новый поиск недвижимости.\n\n"
                f"Название: {manager_search.name}\n"
                f"Описание: {manager_search.description or 'Без описания'}\n\n"
                f"{message}\n\n"
                f"Войдите в личный кабинет для просмотра: https://{request.host}/dashboard",
                user_id=client_id,
                notification_type='search_received'
            )
        except Exception as e:
            print(f"Error sending email notification: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Поиск успешно отправлен клиенту'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error sending search to client: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/manager/saved-search/<int:search_id>', methods=['DELETE'])
@manager_required
@csrf.exempt
def delete_manager_saved_search(search_id):
    """Delete manager's saved search"""
    from models import ManagerSavedSearch
    
    current_manager = current_user
    
    try:
        search = ManagerSavedSearch.query.filter_by(id=search_id, manager_id=current_manager.id).first()
        if not search:
            return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
            
        db.session.delete(search)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Поиск удалён'})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting manager saved search: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

# Developer appointment routes
@searches_bp.route('/book-appointment', methods=['GET', 'POST'], endpoint='book_appointment')
@login_required
def book_appointment():
    """Book appointment with developer"""
    if request.method == 'POST':
        from models import DeveloperAppointment, BalanceTransaction
        from datetime import datetime
        
        property_id = request.form.get('property_id')
        developer_name = request.form.get('developer_name')
        complex_name = request.form.get('complex_name')
        appointment_date = request.form.get('appointment_date')
        appointment_time = request.form.get('appointment_time')
        client_name = request.form.get('client_name')
        client_phone = request.form.get('client_phone')
        notes = request.form.get('notes', '')
        
        try:
            appointment = DeveloperAppointment(
                user_id=current_user.id,
                property_id=property_id,
                developer_name=developer_name,
                complex_name=complex_name,
                appointment_date=datetime.strptime(appointment_date, '%Y-%m-%d'),
                appointment_time=appointment_time,
                client_name=client_name,
                client_phone=client_phone,
                notes=notes
            )
            
            db.session.add(appointment)
            db.session.commit()
            
            flash('Запись к застройщику успешно создана! Менеджер свяжется с вами для подтверждения.', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при создании записи. Попробуйте еще раз.', 'error')
    
    # Get property data if property_id provided
    property_data = None
    property_id = request.args.get('property_id')
    if property_id:
        properties = load_properties()
        for prop in properties:
            if str(prop.get('id')) == property_id:
                property_data = prop
                break
    
    return render_template('book_appointment.html', property_data=property_data)

@searches_bp.route('/api/manager/client/<int:client_id>/send-credentials', methods=['POST'])
@manager_required
def api_send_client_credentials(client_id):
    import secrets
    import string
    from werkzeug.security import generate_password_hash

    try:
        current_manager = current_user
        data = request.get_json() or {}
        method = data.get('method', 'email')

        user = User.query.get(client_id)
        if not user:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404

        if user.assigned_manager_id != current_manager.id:
            role = current_manager.org_role
            can_all = role.can_view_all_deals if role else False
            if not can_all:
                return jsonify({'success': False, 'error': 'Нет доступа к этому клиенту'}), 403

        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))

        login_url = f"{request.url_root.rstrip('/')}/login"
        manager_name = current_manager.full_name or 'Ваш менеджер'
        client_name = user.full_name or 'Уважаемый клиент'
        email_login = user.email or ''
        phone_login = user.phone or ''
        login_identifier = email_login or phone_login

        sent = False
        error_msg = ''

        if method == 'email':
            if not user.email:
                return jsonify({'success': False, 'error': 'У клиента не указан email'}), 400
            try:
                from email_service import send_email
                subject = "Данные для входа в личный кабинет InBack.ru"
                sent = send_email(
                    to_email=user.email,
                    subject=subject,
                    template_name='emails/credentials.html',
                    client_name=client_name,
                    email_login=email_login,
                    temp_password=temp_password,
                    login_url=login_url,
                    manager_name=manager_name
                )
                if not sent:
                    error_msg = 'Не удалось отправить email'
            except Exception as e:
                print(f"Error sending credentials email: {e}")
                error_msg = f'Ошибка отправки email: {str(e)}'

        elif method == 'sms':
            if not user.phone:
                return jsonify({'success': False, 'error': 'У клиента не указан телефон'}), 400
            try:
                from sms_service import sms_service
                sms_message = f"InBack.ru - Ваши данные для входа:\nЛогин: {login_identifier}\nПароль: {temp_password}\nВход: {login_url}"
                sms_result = sms_service.send_sms(user.phone, sms_message)
                sent = sms_result.get('success', False)
                if not sent:
                    error_msg = sms_result.get('message', 'Не удалось отправить SMS')
            except Exception as e:
                print(f"Error sending credentials SMS: {e}")
                error_msg = f'Ошибка отправки SMS: {str(e)}'
        else:
            return jsonify({'success': False, 'error': 'Неверный метод отправки'}), 400

        if sent:
            user.set_password(temp_password)
            user.must_change_password = True
            db.session.commit()
            method_label = 'email' if method == 'email' else 'SMS'
            return jsonify({
                'success': True,
                'message': f'Данные для входа отправлены клиенту через {method_label}'
            })
        else:
            return jsonify({
                'success': False,
                'error': error_msg or 'Не удалось отправить данные. Пароль не был изменён.'
            }), 500

    except Exception as e:
        db.session.rollback()
        print(f"Error in send_client_credentials: {e}")
        return jsonify({'success': False, 'error': f'Ошибка сервера: {str(e)}'}), 500


@searches_bp.route('/api/manager/add-client-old', methods=['POST'])
@manager_required
def add_client():
    """Add new client (old version - deprecated)"""
    from models import User
    import re
    from werkzeug.security import generate_password_hash
    import secrets
    
    data = request.get_json()
    first_name = data.get('first_name')
    last_name = data.get('last_name') 
    email = data.get('email')
    phone = data.get('phone')
    
    if not all([first_name, last_name, email]):
        return jsonify({'success': False, 'error': 'Заполните все обязательные поля'}), 400
    
    # Check if user exists by email
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({'success': False, 'error': 'Пользователь с таким email уже существует'}), 400
    
    # Check if phone already exists (normalized comparison like registration)
    if phone:
        from sqlalchemy import func as sqlfunc
        phone_digits = re.sub(r'[^0-9]', '', phone) if phone else ''
        if phone_digits:
            existing_phone_user = User.query.filter(
                sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits
            ).first()
            if existing_phone_user:
                return jsonify({'success': False, 'error': 'Пользователь с таким номером телефона уже существует'}), 400
    
    try:
        # Generate user ID and password
        user_id = secrets.token_hex(4).upper()
        password = 'demo123'  # Default password
        password_hash = generate_password_hash(password)
        
        current_manager = current_user
        
        user = User(
            is_verified=True,  # Auto-verify
            first_name=_capitalize_name(first_name),
            last_name=_capitalize_name(last_name),
            email=email,
            phone=phone,
            password_hash=password_hash,
            user_id=user_id,
            assigned_manager_id=current_manager.id,
            client_status='Новый'
        )
        
        db.session.add(user)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'full_name': user.full_name,
                'email': user.email,
                'phone': user.phone,
                'user_id': user.user_id,
                'password': password,
                'client_status': user.client_status
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/request-payout', methods=['POST'])
@login_required
def api_request_payout():
    """Request cashback payout"""
    from models import User, CashbackPayout
    from datetime import datetime
    
    try:
        user_id = current_user.id
        
        # Check if user has available cashback
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'Пользователь не найден'})
        
        # For demo purposes, assume available cashback of 125,000
        available_cashback = 125000
        
        if available_cashback <= 0:
            return jsonify({'success': False, 'error': 'Нет доступного кешбека для выплаты'})
        
        # Create payout request
        payout = CashbackPayout(
            user_id=user_id,
            amount=available_cashback,
            status='Запрошена',
            requested_at=datetime.utcnow()
        )
        
        db.session.add(payout)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Запрос на выплату успешно отправлен',
            'amount': available_cashback
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


# City management API endpoints
@searches_bp.route('/api/change-city', methods=['POST'])
def change_city():
    """API endpoint to change current city"""
    try:
        from models import City
        
        data = request.get_json()
        city_slug = data.get('city_slug')
        city_name = data.get('city_name')
        
        if not city_slug:
            return jsonify({'success': False, 'message': 'Missing city data'})
        
        # Validate city exists in database
        city = City.query.filter_by(slug=city_slug, is_active=True).first()
        if not city:
            return jsonify({'success': False, 'message': 'City not found or inactive'})
        
        # Store city data in session
        session['city_id'] = city.id
        session['city_slug'] = city.slug
        session['city_name'] = city.name
        # Keep backward compatibility with old session keys
        session['current_city'] = city.name
        session['current_city_slug'] = city.slug
        
        return jsonify({
            'success': True,
            'message': f'City changed to {city.name}',
            'city': {
                'id': city.id,
                'name': city.name,
                'slug': city.slug
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': 'Error changing city'})


@searches_bp.route('/api/cities')
def get_cities():
    """Get available cities with property counts, hide cities without properties"""
    try:
        from models import City, Property
        from sqlalchemy import func
        
        # Get cities with property counts
        cities_with_counts = db.session.query(
            City,
            func.count(Property.id).label('property_count')
        ).outerjoin(
            Property, 
            (Property.city_id == City.id) & (Property.is_active == True)
        ).filter(
            City.is_active == True
        ).group_by(
            City.id
        ).order_by(
            func.count(Property.id).desc()
        ).all()
        
        logging.debug(f"Found {len(cities_with_counts)} cities in database")
        
        cities_data = []
        for city, property_count in cities_with_counts:
            # Skip cities without properties (but always include default city)
            if property_count == 0 and not city.is_default:
                logging.debug(f"Skipping city {city.name} - no properties")
                continue
                
            cities_data.append({
                'id': city.id,
                'name': city.name,
                'slug': city.slug,
                'is_default': city.is_default,
                'address_position_lat': city.latitude,
                'address_position_lon': city.longitude,
                'zoom_level': city.zoom_level,
                'property_count': property_count
            })
            
            logging.debug(f"Added city: {city.name} (id={city.id}, properties={property_count})")
        logging.debug(f"Returning {len(cities_data)} cities to client")
        return jsonify({'cities': cities_data})
        
    except Exception as e:
        logging.error(f"Error fetching cities: {str(e)}", exc_info=True)
        # Fallback data if database not set up yet
        return jsonify({
            'cities': [
                {
                    'id': 1,
                    'name': 'Краснодар',
                    'slug': 'krasnodar',
                    'is_default': True,
                    'address_position_lat': 45.0355,
                    'address_position_lon': 38.9753,
                    'zoom_level': 12
                }
            ]
        })



@searches_bp.route('/api/districts/<int:city_id>')
def get_districts_by_city(city_id):
    """Get all districts for a specific city — returns id, name, slug, type, rc_count."""
    try:
        from models import District, ResidentialComplex
        from sqlalchemy import func as _func

        rows = (
            db.session.query(
                District.id,
                District.name,
                District.slug,
                District.district_type,
                _func.count(ResidentialComplex.id).label('rc_count'),
            )
            .outerjoin(
                ResidentialComplex,
                (ResidentialComplex.district_id == District.id)
                & (ResidentialComplex.is_active == True),
            )
            .filter(District.city_id == city_id)
            .group_by(District.id, District.name, District.slug, District.district_type)
            .having(_func.count(ResidentialComplex.id) > 0)
            .order_by(District.district_type, District.name)
            .all()
        )

        _type_label = {
            'okrug': 'Округ',
            'microrayon': 'Микрорайон',
            'settlement': 'Посёлок',
            'admin': 'Район',
            'micro': 'Микрорайон',
        }

        districts_list = [
            {
                'id': r.id,
                'name': r.name,
                'slug': r.slug,
                'type': r.district_type or 'micro',
                'type_label': _type_label.get(r.district_type or 'micro', 'Район'),
                'rc_count': r.rc_count or 0,
            }
            for r in rows
        ]

        logging.debug(f"✅ Found {len(districts_list)} districts for city {city_id}")
        return jsonify({'success': True, 'count': len(districts_list), 'districts': districts_list})

    except Exception as e:
        logging.error(f"❌ Error fetching districts for city {city_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'districts': [], 'count': 0, 'error': str(e)}), 500


@searches_bp.route('/api/streets')
def get_streets():
    """Search streets for a city from DB, with DaData fallback.
    Params: city_id (required), q (search query, optional), limit (default 20).
    Returns: [{id, name, slug, district_id, prop_count}]
    """
    try:
        from models import Street, Property as _Prop

        city_id = request.args.get('city_id', type=int)
        q = (request.args.get('q') or '').strip()
        limit = min(int(request.args.get('limit', 20)), 50)

        if not city_id:
            return jsonify({'success': False, 'streets': [], 'error': 'city_id required'}), 400

        from sqlalchemy import func as _func

        base_filter = [Street.city_id == city_id]
        if q and len(q) >= 2:
            base_filter.append(Street.name.ilike(f'%{q}%'))

        rows = (
            db.session.query(
                Street.id,
                Street.name,
                Street.slug,
                Street.district_id,
                _func.count(_Prop.id).label('prop_count'),
            )
            .outerjoin(
                _Prop,
                (_Prop.parsed_street.ilike(Street.name)) & (_Prop.is_active == True),
            )
            .filter(*base_filter)
            .group_by(Street.id, Street.name, Street.slug, Street.district_id)
            .order_by(_func.count(_Prop.id).desc(), Street.name)
            .limit(limit)
            .all()
        )

        streets_list = [
            {
                'id': r.id,
                'name': r.name,
                'slug': r.slug,
                'district_id': r.district_id,
                'prop_count': r.prop_count or 0,
            }
            for r in rows
        ]

        # DaData fallback if DB returned nothing and a query was given
        if not streets_list and q and len(q) >= 2:
            try:
                from services.dadata_client import DaDataClient
                _dd = DaDataClient()
                if _dd.is_available():
                    from models import City as _City
                    _city_obj = _City.query.get(city_id)
                    _city_slug = _city_obj.slug if _city_obj else None
                    _dd_results = _dd.suggest_streets(q, city=_city_obj.name if _city_obj else None, count=10)
                    for _r in _dd_results:
                        _st_name = _r.get('street') or _r.get('value') or ''
                        if _st_name and not any(s['name'] == _st_name for s in streets_list):
                            streets_list.append({
                                'id': None,
                                'name': _st_name,
                                'slug': None,
                                'district_id': None,
                                'prop_count': 0,
                                'source': 'dadata',
                            })
            except Exception:
                pass

        return jsonify({'success': True, 'count': len(streets_list), 'streets': streets_list})

    except Exception as e:
        logging.error(f"❌ Error fetching streets: {e}", exc_info=True)
        return jsonify({'success': False, 'streets': [], 'error': str(e)}), 500

        
def init_cities():
    """Initialize default cities in database"""
    try:
        from models import City
        
        # Check if cities already exist
        if City.query.count() == 0:
            cities_data = [
                {
                    'name': 'Краснодар',
                    'slug': 'krasnodar',
                    'is_active': True,
                    'is_default': True,
                    'phone': '8 (862) 266-62-16',
                    'email': 'krasnodar@inback.ru',
                    'address': 'г. Краснодар, ул. Красная, 32',
                    'address_position_lat': 45.0355,
                    'address_position_lon': 38.9753,
                    'zoom_level': 12,
                    'description': 'Кэшбек за новостройки в Краснодаре',
                    'meta_title': 'Кэшбек за новостройки в Краснодаре | InBack.ru',
                    'meta_description': 'Получите до 10% кэшбека при покупке новостройки в Краснодаре. Проверенные застройщики, юридическое сопровождение.'
                },
                {
                    'name': 'Москва',
                    'slug': 'moscow',
                    'is_active': False,
                    'is_default': False,
                    'phone': '8 (862) 266-62-16',
                    'email': 'moscow@inback.ru',
                    'address': 'г. Москва, ул. Тверская, 1',
                    'address_position_lat': 55.7558,
                    'address_position_lon': 37.6176,
                    'zoom_level': 11,
                    'description': 'Кэшбек за новостройки в Москве (скоро)',
                    'meta_title': 'Кэшбек за новостройки в Москве | InBack.ru',
                    'meta_description': 'Скоро: кэшбек сервис для покупки новостроек в Москве.'
                },
                {
                    'name': 'Санкт-Петербург',
                    'slug': 'spb',
                    'is_active': False,
                    'is_default': False,
                    'phone': '8 (862) 266-62-16',
                    'email': 'spb@inback.ru',
                    'address': 'г. Санкт-Петербург, Невский пр., 1',
                    'address_position_lat': 59.9311,
                    'address_position_lon': 30.3609,
                    'zoom_level': 11,
                    'description': 'Кэшбек за новостройки в Санкт-Петербурге (скоро)',
                    'meta_title': 'Кэшбек за новостройки в СПб | InBack.ru',
                    'meta_description': 'Скоро: кэшбек сервис для покупки новостроек в Санкт-Петербурге.'
                },
                {
                    'name': 'Сочи',
                    'slug': 'sochi',
                    'is_active': False,
                    'is_default': False,
                    'phone': '8 (862) 266-62-16',
                    'email': 'sochi@inback.ru',
                    'address': 'г. Сочи, ул. Курортный пр., 1',
                    'address_position_lat': 43.6028,
                    'address_position_lon': 39.7342,
                    'zoom_level': 12,
                    'description': 'Кэшбек за новостройки в Сочи (скоро)',
                    'meta_title': 'Кэшбек за новостройки в Сочи | InBack.ru',
                    'meta_description': 'Скоро: кэшбек сервис для покупки новостроек в Сочи.'
                }
            ]
            
            for city_data in cities_data:
                city = City(**city_data)
                db.session.add(city)
            
            db.session.commit()
            print("Cities initialized successfully")
            
    except Exception as e:
        print(f"Error initializing cities: {e}")

# Legacy API route removed - using Blueprint version instead

@searches_bp.route('/api/searches', methods=['POST'])
def save_search():
    """Save user search parameters with manager-to-client sharing functionality"""
    from models import SavedSearch, User
    data = request.get_json()
    
    # Check authentication using helper function
    auth_info = check_api_authentication()
    if not auth_info:
        return jsonify({'success': False, 'error': 'Не авторизован'}), 401
    
    user_id = auth_info['user_id']
    user_role = auth_info['type']
    current_logged_user = auth_info['user']
    
    try:
        client_email = data.get('client_email')  # For managers
        
        print(f"DEBUG: Saving search with raw data: {data}")
        
        # Create filter object from submitted data
        filters = {}
        
        # Check if filters are nested in 'filters' object
        filter_data = data.get('filters', {}) if 'filters' in data else data
        
        # Extract filters from the data (new format)
        if 'rooms' in filter_data and filter_data['rooms']:
            if isinstance(filter_data['rooms'], list):
                room_list = [r for r in filter_data['rooms'] if r]  # Remove empty strings
                if room_list:
                    filters['rooms'] = room_list
            elif filter_data['rooms']:
                filters['rooms'] = [filter_data['rooms']]
                
        if 'districts' in filter_data and filter_data['districts']:
            if isinstance(filter_data['districts'], list):
                district_list = [d for d in filter_data['districts'] if d]  # Remove empty strings
                if district_list:
                    filters['districts'] = district_list
            elif filter_data['districts']:
                filters['districts'] = [filter_data['districts']]
                
        if 'developers' in filter_data and filter_data['developers']:
            if isinstance(filter_data['developers'], list):
                developer_list = [d for d in filter_data['developers'] if d]  # Remove empty strings
                if developer_list:
                    filters['developers'] = developer_list
            elif filter_data['developers']:
                filters['developers'] = [filter_data['developers']]
                
        if 'completion' in filter_data and filter_data['completion']:
            if isinstance(filter_data['completion'], list):
                completion_list = [c for c in filter_data['completion'] if c]  # Remove empty strings
                if completion_list:
                    filters['completion'] = completion_list
            elif filter_data['completion']:
                filters['completion'] = [filter_data['completion']]
                
        if 'priceFrom' in filter_data and filter_data['priceFrom'] and str(filter_data['priceFrom']) not in ['0', '']:
            filters['priceFrom'] = str(filter_data['priceFrom'])
        if 'priceTo' in filter_data and filter_data['priceTo'] and str(filter_data['priceTo']) not in ['0', '']:
            filters['priceTo'] = str(filter_data['priceTo'])
        if 'areaFrom' in filter_data and filter_data['areaFrom'] and str(filter_data['areaFrom']) not in ['0', '']:
            filters['areaFrom'] = str(filter_data['areaFrom'])
        if 'areaTo' in filter_data and filter_data['areaTo'] and str(filter_data['areaTo']) not in ['0', '']:
            filters['areaTo'] = str(filter_data['areaTo'])
            
        print(f"DEBUG: Extracted filters from {filter_data}: {filters}")

        # Create search with new format
        search = SavedSearch(
            user_id=user_id,
            name=data['name'],
            description=data.get('description'),
            search_type='properties',
            additional_filters=json.dumps(filters),
            notify_new_matches=data.get('notify_new_matches', True)
        )

        # Also save in legacy format for backwards compatibility
        if 'rooms' in data and data['rooms']:
            if isinstance(data['rooms'], list) and len(data['rooms']) > 0:
                search.property_type = data['rooms'][0]  # Use first room type
            else:
                search.property_type = data['rooms']
        if 'priceTo' in data and data['priceTo']:
            try:
                search.price_max = int(float(data['priceTo']) * 1000000)  # Convert millions to rubles
            except (ValueError, TypeError):
                pass
        if 'priceFrom' in data and data['priceFrom']:
            try:
                search.price_min = int(float(data['priceFrom']) * 1000000)  # Convert millions to rubles
            except (ValueError, TypeError):
                pass
        
        db.session.add(search)
        db.session.commit()
        
        # If manager specified client email, send search to client  
        if user_role == 'manager' and client_email:
            try:
                # Check if client exists
                client = User.query.filter_by(email=client_email).first()
                
                # If client exists, also save search to their account
                if client:
                    client_search = SavedSearch(
                        user_id=client.id,
                        name=data['name'] + ' (от менеджера)',
                        description=data.get('description'),
                        search_type='properties',
                        location=data.get('location'),
                        property_type=data.get('property_type'),
                        price_min=data.get('price_min'),
                        price_max=data.get('price_max'),
                        size_min=data.get('size_min'),
                        size_max=data.get('size_max'),
                        developer=data.get('developer'),
                        complex_name=data.get('complex_name'),
                        floor_min=data.get('floor_min'),
                        floor_max=data.get('floor_max'),
                        additional_filters=json.dumps(filters),
                        notify_new_matches=True
                    )
                    db.session.add(client_search)
                    db.session.commit()
                
                # Prepare search URL for client properties page  
                search_params = []
                
                # Convert manager filter format to client filter format
                if data.get('location'):
                    search_params.append(f"district={data['location']}")
                if data.get('developer'):
                    search_params.append(f"developer={data['developer']}")
                if data.get('property_type'):
                    search_params.append(f"rooms={data['property_type']}")
                if data.get('complex_name'):
                    search_params.append(f"complex={data['complex_name']}")
                if data.get('price_min'):
                    search_params.append(f"priceFrom={data['price_min'] / 1000000}")
                if data.get('price_max'):
                    search_params.append(f"priceTo={data['price_max'] / 1000000}")
                if data.get('size_min'):
                    search_params.append(f"areaFrom={data['size_min']}")
                if data.get('size_max'):
                    search_params.append(f"areaTo={data['size_max']}")
                
                search_url = f"{request.url_root}properties"
                if search_params:
                    search_url += "?" + "&".join(search_params)
                
                # Email content for client
                subject = f"Подборка недвижимости: {data['name']}"
                
                # Generate filter description for email
                filter_descriptions = []
                if data.get('property_type'):
                    filter_descriptions.append(f"Тип: {data['property_type']}")
                if data.get('location'):
                    filter_descriptions.append(f"Район: {data['location']}")
                if data.get('developer'):
                    filter_descriptions.append(f"Застройщик: {data['developer']}")
                if data.get('price_min') or data.get('price_max'):
                    price_min = f"{(data.get('price_min', 0) / 1000000):.1f}" if data.get('price_min') else "0"
                    price_max = f"{(data.get('price_max', 0) / 1000000):.1f}" if data.get('price_max') else "∞"
                    filter_descriptions.append(f"Цена: {price_min}-{price_max} млн ₽")
                if data.get('size_min') or data.get('size_max'):
                    area_min = str(data.get('size_min', 0)) if data.get('size_min') else "0"
                    area_max = str(data.get('size_max', 0)) if data.get('size_max') else "∞"
                    filter_descriptions.append(f"Площадь: {area_min}-{area_max} м²")
                
                filter_text = "<br>".join([f"• {desc}" for desc in filter_descriptions])
                
                html_content = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #0088CC;">Подборка недвижимости от InBack</h2>
                    
                    <p>Здравствуйте!</p>
                    
                    <p>Менеджер <strong>{current_user.full_name or current_user.username}</strong> подготовил для вас персональную подборку недвижимости.</p>
                    
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="margin: 0 0 15px 0; color: #333;">Параметры поиска: {data['name']}</h3>
                        <div style="color: #666; line-height: 1.6;">
                            {filter_text}
                        </div>
                    </div>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{search_url}" style="display: inline-block; background: #0088CC; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-weight: bold;">
                            Посмотреть подборку
                        </a>
                    </div>
                    
                    <p style="color: #666; font-size: 14px;">
                        Если у вас есть вопросы, свяжитесь с вашим менеджером:<br>
                        <strong>{current_logged_user.full_name if hasattr(current_logged_user, 'full_name') else current_logged_user.email}</strong><br>
                        Email: {current_logged_user.email}
                    </p>
                    
                    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                    <p style="color: #999; font-size: 12px; text-align: center;">
                        InBack - ваш надежный партнер в поиске недвижимости
                    </p>
                </div>
                """
                
                # Send email using existing email service
                from email_service import send_email
                email_sent = send_email(
                    to_email=client_email,
                    subject=subject,
                    html_content=html_content,
                    template_name='collection'
                )
                
                if email_sent:
                    return jsonify({
                        'success': True, 
                        'search_id': search.id, 
                        'search': search.to_dict(),
                        'message': f'Поиск сохранен и отправлен клиенту на {client_email}',
                        'email_sent': True
                    })
                else:
                    return jsonify({
                        'success': True, 
                        'search_id': search.id, 
                        'search': search.to_dict(),
                        'message': 'Поиск сохранен, но не удалось отправить email клиенту',
                        'email_sent': False
                    })
                    
            except Exception as email_error:
                # Still return success for saved search even if email fails
                print(f"Email sending error: {email_error}")
                return jsonify({
                    'success': True, 
                    'search_id': search.id, 
                    'search': search.to_dict(),
                    'message': 'Поиск сохранен, но произошла ошибка при отправке email',
                    'email_sent': False,
                    'email_error': str(email_error)
                })
        
        return jsonify({'success': True, 'search_id': search.id, 'search': search.to_dict()})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

def check_api_authentication():
    """Helper function to check API authentication for both users and managers"""
    # Check if manager is logged in
    if 'manager_id' in session:
        from models import Manager
        manager = Manager.query.get(session['manager_id'])
        if manager:
            return {'type': 'manager', 'user_id': manager.id, 'user': manager}
    
    # Check if regular user is logged in  
    if current_user and hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        return {'type': 'user', 'user_id': current_user.id, 'user': current_user}
    
    # Also check session for user_id (alternative authentication method)
    if 'user_id' in session:
        from models import User
        user = User.query.get(session['user_id'])
        if user:
            return {'type': 'user', 'user_id': user.id, 'user': user}
    
    return None

@searches_bp.route('/api/searches', methods=['GET', 'POST'])
@csrf.exempt
def saved_searches_endpoint():
    """Get or create user's saved searches"""
    from models import SavedSearch
    
    # Check authentication using helper function
    auth_info = check_api_authentication()
    if not auth_info:
        return jsonify({'success': False, 'error': 'Не авторизован'}), 401
    
    if request.method == 'GET':
        # Get saved searches for the authenticated user (manager or regular user) 
        searches = SavedSearch.query.filter_by(user_id=auth_info['user_id']).order_by(SavedSearch.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'searches': [search.to_dict() for search in searches]
        })
    
    elif request.method == 'POST':
        # Create new saved search
        data = request.get_json()
        name = data.get('name')
        description = data.get('description', '')
        notify_new_matches = data.get('notify_new_matches', False)
        search_type = data.get('search_type', 'properties')
        
        if not name:
            return jsonify({'success': False, 'error': 'Название поиска обязательно'}), 400
        
        try:
            # Extract search parameters (exclude metadata fields)
            exclude_fields = {'name', 'description', 'notify_new_matches', 'search_type'}
            search_params = {k: v for k, v in data.items() if k not in exclude_fields and v}
            
            search = SavedSearch()
            search.name = name
            search.description = description
            search.notify_new_matches = notify_new_matches
            search.search_type = search_type
            search.user_id = auth_info['user_id']
            search.created_at = datetime.utcnow()
            
            # Store search parameters as additional_filters JSON
            search.additional_filters = json.dumps(search_params)
            
            # Also set individual fields if they exist in the model
            for key, value in search_params.items():
                if hasattr(search, key):
                    setattr(search, key, value)
            
            db.session.add(search)
            db.session.commit()
            
            return jsonify({'success': True, 'search_id': search.id, 'message': 'Поиск сохранен'})
        except Exception as e:
            db.session.rollback()
            print(f"Error saving search: {e}")
            return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/user/saved-searches')
@login_required
def get_user_saved_searches():
    """Get user's saved searches"""
    from models import SavedSearch
    
    try:
        searches = SavedSearch.query.filter_by(user_id=current_user.id)\
            .order_by(SavedSearch.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'searches': [search.to_dict() for search in searches]
        })
    except Exception as e:
        print(f"Error loading user saved searches: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/user/saved-searches', methods=['POST'])
@login_required
@csrf.exempt
def create_user_saved_search():
    """Create a new saved search for user"""
    from models import SavedSearch
    import json
    
    data = request.get_json()
    
    try:
        filters = data.get('filters', {})
        
        if not filters:
            filter_keys = ['rooms', 'districts', 'developers', 'completion', 'object_classes', 
                          'renovation', 'features', 'building_released', 'floor_options',
                          'regions', 'cities',
                          'price_min', 'price_max', 'area_min', 'area_max', 
                          'floor_min', 'floor_max', 'building_floors_min', 'building_floors_max',
                          'priceFrom', 'priceTo', 'areaFrom', 'areaTo', 'floorFrom', 'floorTo',
                          'property_type', 'search_url']
            filters = {k: v for k, v in data.items() if k in filter_keys and v}
        
        search_url = data.get('search_url') or filters.get('search_url', '')
        if search_url:
            filters['search_url'] = search_url
        
        filters_json = json.dumps(filters) if filters else None
        print(f"DEBUG create_user_saved_search: search_url={search_url}")
        
        # Get current city from session or data
        city_id = data.get('city_id') or session.get('city_id') or 1  # Default to city 1 (Sochi)
        
        notify = data.get('notify_new_matches', False)

        search = SavedSearch(
            user_id=current_user.id,
            city_id=city_id,
            name=data.get('name'),
            description=data.get('description'),
            search_type=data.get('search_type', 'properties'),
            additional_filters=filters_json,
            notify_new_matches=notify,
            # Подключаем к системе оповещений AlertService
            alert_enabled=notify,
            alert_frequency='instant' if notify else None,
        )

        # Заполняем legacy-поля для совместимости с _property_matches_search
        # Цена
        for price_key in ('price_min', 'priceFrom'):
            v = filters.get(price_key) or data.get(price_key)
            if v:
                try:
                    pv = float(v)
                    search.price_min = int(pv * 1_000_000) if pv < 1000 else int(pv)
                except (ValueError, TypeError):
                    pass
                break
        for price_key in ('price_max', 'priceTo'):
            v = filters.get(price_key) or data.get(price_key)
            if v:
                try:
                    pv = float(v)
                    search.price_max = int(pv * 1_000_000) if pv < 1000 else int(pv)
                except (ValueError, TypeError):
                    pass
                break
        # Площадь
        for area_key in ('area_min', 'areaFrom'):
            v = filters.get(area_key) or data.get(area_key)
            if v:
                try: search.size_min = float(v)
                except (ValueError, TypeError): pass
                break
        for area_key in ('area_max', 'areaTo'):
            v = filters.get(area_key) or data.get(area_key)
            if v:
                try: search.size_max = float(v)
                except (ValueError, TypeError): pass
                break
        # Комнатность → property_type (все выбранные, через запятую)
        rooms = filters.get('rooms') or data.get('rooms')
        if rooms:
            if isinstance(rooms, list):
                search.property_type = ','.join(str(r) for r in rooms if r != '')
            elif rooms:
                search.property_type = str(rooms)

        db.session.add(search)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'search': search.to_dict(),
            'message': 'Поиск успешно сохранён'
        })
    except Exception as e:
        db.session.rollback()
        print(f"Error creating user saved search: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/user/saved-searches/<int:search_id>', methods=['DELETE'])
@login_required
@csrf.exempt
def delete_user_saved_search(search_id):
    """Delete user's saved search"""
    from models import SavedSearch
    
    try:
        search = SavedSearch.query.filter_by(id=search_id, user_id=current_user.id).first()
        
        if not search:
            return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
        
        db.session.delete(search)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Поиск успешно удалён'
        })
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting user saved search: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


@searches_bp.route('/api/searches/<int:search_id>/apply', methods=['POST'])
@login_required
def apply_saved_search(search_id):
    """Apply saved search - returns filters for redirect"""
    from models import SavedSearch
    import json
    from datetime import datetime
    
    try:
        search = SavedSearch.query.filter_by(id=search_id, user_id=current_user.id).first()
        if not search:
            return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
        
        # Get filters from the saved search (using additional_filters field)
        filters = {}
        if search.additional_filters:
            try:
                filters = json.loads(search.additional_filters) if isinstance(search.additional_filters, str) else search.additional_filters
            except:
                filters = {}
        
        # Ensure property_type is captured
        if search.property_type and 'property_type' not in filters:
            filters['property_type'] = search.property_type
        elif 'property_type' not in filters:
            # Fallback to a default or check search_url if exists
            pass
            
        # Standardize object_classes vs object_class
        if 'object_class' in filters and 'object_classes' not in filters:
            filters['object_classes'] = filters['object_class']
            
        # Update last_used timestamp
        search.last_used = datetime.utcnow()
        db.session.commit()
        
        # Get city from saved search or filters (handle legacy nested data including lists)
        city_slug = 'sochi'  # default
        if search.city_id:
            from models import City
            city_obj = City.query.get(search.city_id)
            if city_obj:
                city_slug = city_obj.slug
        elif filters.get('city'):
            city_value = filters.get('city')
            if isinstance(city_value, list) and len(city_value) > 0:
                first_item = city_value[0]
                if isinstance(first_item, dict):
                    city_slug = first_item.get('slug') or first_item.get('name') or 'sochi'
                elif isinstance(first_item, str):
                    city_slug = first_item
            elif isinstance(city_value, dict):
                city_slug = city_value.get('slug') or city_value.get('name') or 'sochi'
            elif isinstance(city_value, str):
                city_slug = city_value
        
        search_url = filters.get('search_url', '')
        
        # Ensure array parameters are lists
        for key in ['rooms', 'districts', 'developers', 'object_classes', 'renovation', 'features']:
            if key in filters and not isinstance(filters[key], list):
                filters[key] = [filters[key]]
        
        return jsonify({
            'success': True,
            'filters': filters,
            'city': city_slug,
            'search_url': search_url
        })
    except Exception as e:
        print(f"Error applying saved search: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400
@searches_bp.route('/api/user/saved-searches/<int:search_id>/toggle-alert', methods=['POST'])
@login_required
def toggle_saved_search_alert(search_id):
    """Toggle notify_new_matches for a saved search"""
    from models import SavedSearch
    try:
        search = SavedSearch.query.filter_by(id=search_id, user_id=current_user.id).first()
        if not search:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        data = request.get_json(silent=True) or {}
        new_val = data.get('notify_new_matches', not bool(search.notify_new_matches))
        search.notify_new_matches = bool(new_val)
        search.alert_enabled = bool(new_val)
        db.session.commit()
        return jsonify({'success': True, 'notify_new_matches': search.notify_new_matches})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@searches_bp.route('/api/user/saved-searches/count')
@login_required
def get_user_saved_searches_count():
    """Get count of user's saved searches"""
    from models import SavedSearch
    
    try:
        count = SavedSearch.query.filter_by(user_id=current_user.id).count()
        return jsonify({
            'success': True,
            'count': count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ==========================================
# USER NOTIFICATION SETTINGS API ENDPOINTS
# ==========================================

@searches_bp.route('/api/user/alert-settings', methods=['GET'])
@login_required
def get_user_alert_settings():
    """Get all user's saved searches with alert settings"""
    from models import SavedSearch, PropertyAlert
    
    searches = db.session.query(SavedSearch)\
        .filter_by(user_id=current_user.id)\
        .order_by(SavedSearch.last_used.desc())\
        .all()
    
    # Enrich each search with alert count
    result = []
    for search in searches:
        search_dict = search.to_dict()
        alert_count = db.session.query(PropertyAlert)\
            .filter_by(saved_search_id=search.id)\
            .count()
        search_dict['alert_count'] = alert_count
        result.append(search_dict)
    
    return jsonify({'success': True, 'searches': result})

@searches_bp.route('/api/user/alert-settings', methods=['POST'])
@login_required
@require_json_csrf
def update_user_alert_settings():
    """Update alert settings for a specific saved search"""
    data = request.get_json()
    search_id = data.get('search_id')
    
    if not search_id:
        return jsonify({'success': False, 'error': 'search_id required'}), 400
    
    search = db.session.query(SavedSearch)\
        .filter_by(id=search_id, user_id=current_user.id)\
        .first()
    
    if not search:
        return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
    
    # Update fields
    if 'alert_enabled' in data:
        search.alert_enabled = bool(data['alert_enabled'])
    
    if 'alert_frequency' in data:
        freq = data['alert_frequency']
        if freq not in ['instant', 'daily', 'weekly', 'never']:
            return jsonify({'success': False, 'error': 'Invalid frequency'}), 400
        search.alert_frequency = freq
    
    if 'alert_channels' in data:
        channels = data['alert_channels']
        if not isinstance(channels, list):
            return jsonify({'success': False, 'error': 'Channels must be array'}), 400
        import json
        search.alert_channels = json.dumps(channels)
    
    db.session.commit()
    return jsonify({'success': True, 'search': search.to_dict()})

@searches_bp.route('/api/user/unsubscribe/<token>', methods=['GET'])
def unsubscribe_from_alerts(token):
    """Unsubscribe from alerts using token"""
    import jwt
    from models import SavedSearch
    
    try:
        payload = jwt.decode(token, current_app.secret_key, algorithms=['HS256'])
        user_id = payload.get('user_id')
        search_id = payload.get('search_id')
        
        search = db.session.query(SavedSearch)\
            .filter_by(id=search_id, user_id=user_id)\
            .first()
        
        if search:
            search.alert_enabled = False
            db.session.commit()
            return render_template('unsubscribe_success.html', search_name=search.name)
        
        return render_template('unsubscribe_error.html', error='Поиск не найден'), 404
        
    except Exception as e:
        return render_template('unsubscribe_error.html', error='Недействительная ссылка'), 400



@searches_bp.route('/api/user/alert-history', methods=['GET'])
@login_required
def get_alert_history():
    """Get user's alert history with pagination"""
    try:
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))
        
        # Ensure limits are reasonable
        limit = min(limit, 100)
        offset = max(offset, 0)
        
        history_data = AlertService.get_alert_history(
            user_id=current_user.id,
            limit=limit,
            offset=offset
        )
        
        # Enrich with property details
        from models import Property
        for alert in history_data['alerts']:
            property = Property.query.get(alert.get('property_id'))
            if property:
                alert['property'] = {
                    'title': property.title,
                    'rooms': property.rooms,
                    'area': property.area,
                    'price': property.price,
                    'main_image': property.main_image,
                    'complex_name': property.residential_complex.name if property.residential_complex else None
                }
        
        return jsonify({
            'success': True,
            **history_data
        })
        
    except Exception as e:
        logger.error(f"Error getting alert history: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@login_required 
def get_saved_search(search_id):
    """Get saved search by ID - supports both user searches and manager shared searches"""
    try:
        from models import SavedSearch, SentSearch
        
        # First try user's own saved search
        search = SavedSearch.query.filter_by(id=search_id, user_id=current_user.id).first()
        
        # If not found, try manager shared search via SentSearch table
        if not search:
            sent_search = SentSearch.query.filter_by(
                client_id=current_user.id
            ).join(SavedSearch, SentSearch.manager_search_id == SavedSearch.id).filter(
                SavedSearch.id == search_id
            ).first()
            
            if sent_search:
                search = SavedSearch.query.get(search_id)
                # Use the additional_filters from sent_search if available
                if sent_search.additional_filters:
                    search._temp_filters = sent_search.additional_filters
        
        # If still not found, check if it's a global search available to all users
        if not search:
            search = SavedSearch.query.get(search_id)
            if search and not search.user_id:  # Global searches have no user_id
                pass  # Allow access
            else:
                search = None
        
        if not search:
            return jsonify({'success': False, 'error': 'Поиск не найден'})
        
        # Parse filters - check for temp filters from sent search first
        filters = {}
        if hasattr(search, '_temp_filters') and search._temp_filters:
            try:
                filters = json.loads(search._temp_filters)
            except:
                filters = {}
        elif search.additional_filters:
            try:
                filters = json.loads(search.additional_filters)
            except:
                filters = {}
        
        return jsonify({
            'success': True,
            'id': search.id,
            'name': search.name,
            'description': search.description,
            'search_filters': filters,
            'created_at': search.created_at.isoformat() if search.created_at else None
        })
        
    except Exception as e:
        print(f"Error getting saved search: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'})

@searches_bp.route('/api/searches/<int:search_id>', methods=['DELETE'])
@csrf.exempt
def delete_saved_search(search_id):
    """Delete saved search"""
    from models import SavedSearch
    
    # Check authentication using helper function
    auth_info = check_api_authentication()
    if not auth_info:
        return jsonify({'success': False, 'error': 'Не авторизован'}), 401
    
    user_id = auth_info['user_id']
    
    search = SavedSearch.query.filter_by(id=search_id, user_id=user_id).first()
    
    if not search:
        return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
    
    try:
        db.session.delete(search)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/manager/send-property', methods=['POST'])
@login_required
def send_property_to_client_endpoint():
    """Send property search to client"""
    if current_user.role != 'manager':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        client_id = data.get('client_id')
        search_id = data.get('search_id')
        message = data.get('message', '')
        
        if not client_id or not search_id:
            return jsonify({'success': False, 'error': 'Client ID and Search ID are required'}), 400
        
        # Verify client exists and is a buyer
        client = User.query.filter_by(id=client_id, role='buyer').first()
        if not client:
            return jsonify({'success': False, 'error': 'Client not found'}), 404
        
        # Verify search exists and belongs to manager
        search = SavedSearch.query.filter_by(id=search_id, user_id=current_user.id).first()
        if not search:
            return jsonify({'success': False, 'error': 'Search not found'}), 404
        
        # Create recommendation record
        from models import ClientPropertyRecommendation
        recommendation = ClientPropertyRecommendation(
            manager_id=current_user.id,
            client_id=client_id,
            search_id=search_id,
            message=message
        )
        
        db.session.add(recommendation)
        db.session.commit()
        
        # Send notification to client (email)
        try:
            subject = f"Подборка квартир от {current_user.full_name}"
            text_message = f"""
Здравствуйте, {client.full_name}!

Ваш менеджер {current_user.full_name} подготовил для вас подборку квартир: {search.name}

{message if message else ''}

Перейдите в личный кабинет на сайте InBack.ru, чтобы посмотреть подборку.

С уважением,
Команда InBack.ru
            """
            
            from email_service import send_email
            send_email(
                to_email=client.email,
                subject=subject,
                text_content=text_message.strip(),
                template_name='recommendation'
            )
        except Exception as e:
            current_app.logger.warning(f"Failed to send email notification: {str(e)}")
        
        return jsonify({
            'success': True,
            'message': 'Property recommendation sent successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

# Property API routes for manager search
@searches_bp.route('/api/search/properties')
def search_properties_api():
    """Search properties for manager collection creation using normalized tables"""
    from repositories.property_repository import PropertyRepository
    
    try:
        district = request.args.get('district')
        developer = request.args.get('developer') 
        rooms = request.args.get('rooms')
        prop_type = request.args.get('type')
        price_min = request.args.get('price_min')
        price_max = request.args.get('price_max')
        area_min = request.args.get('area_min')
        
        filters = {}
        if price_min:
            filters['min_price'] = int(price_min)
        if price_max:
            filters['max_price'] = int(price_max)
        if area_min:
            filters['min_area'] = float(area_min)
        if rooms and rooms.isdigit():
            filters['rooms'] = [int(rooms)]
        if prop_type:
            filters['deal_type'] = prop_type
        
        properties = PropertyRepository.get_all_active(filters=filters, limit=100)
        
        filtered_properties = []
        for prop in properties:
            complex_obj = prop.residential_complex
            developer_obj = prop.developer
            
            district_name = complex_obj.district if complex_obj else ''
            developer_name = developer_obj.name if developer_obj else ''
            
            if district and district_name.lower() != district.lower():
                continue
            if developer and developer_name.lower() != developer.lower():
                continue
            if prop_type and prop.deal_type and prop.deal_type.lower() != prop_type.lower():
                continue
            
            price = prop.price or 0
            cashback_rate = complex_obj.cashback_rate if complex_obj and complex_obj.cashback_rate else 5.0
            cashback = int(price * cashback_rate / 100)
            
            filtered_properties.append({
                'id': prop.inner_id or prop.id,
                'complex_name': complex_obj.name if complex_obj else '',
                'district': district_name,
                'developer': developer_name,
                'rooms': prop.rooms or 0,
                'price': price,
                'cashback': cashback,
                'area': prop.area or 0,
                'floor': f"{prop.floor}/{prop.total_floors}" if prop.floor and prop.total_floors else '',
                'type': prop.deal_type or 'Первичка'
            })
        
        filtered_properties = filtered_properties[:20]
        
        return jsonify({
            'success': True,
            'properties': filtered_properties
        })
    except Exception as e:
        print(f"Error searching properties: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/search/apartments')
def search_apartments_api():
    """Search apartments with full filtering using normalized tables"""
    from repositories.property_repository import PropertyRepository, ResidentialComplexRepository
    
    try:
        district = request.args.get('district')
        developer = request.args.get('developer') 
        rooms = request.args.get('rooms')
        complex_id = request.args.get('complex')
        price_min = request.args.get('price_min')
        price_max = request.args.get('price_max')
        area_min = request.args.get('area_min')
        area_max = request.args.get('area_max')
        floor_min = request.args.get('floor_min')
        floor_max = request.args.get('floor_max')
        status = request.args.get('status')
        finishing = request.args.get('finishing')
        
        filters = {}
        if price_min:
            filters['min_price'] = int(price_min)
        if price_max:
            filters['max_price'] = int(price_max)
        if area_min:
            filters['min_area'] = float(area_min)
        if area_max:
            filters['max_area'] = float(area_max)
        if complex_id:
            filters['complex_id'] = int(complex_id)
        if rooms and rooms != 'студия':
            if rooms.isdigit():
                filters['rooms'] = [int(rooms)]
        
        properties = PropertyRepository.get_all_active(filters=filters, limit=200)
        
        filtered_apartments = []
        for prop in properties:
            complex_obj = prop.residential_complex
            developer_obj = prop.developer
            
            district_name = complex_obj.district if complex_obj else ''
            developer_name = developer_obj.name if developer_obj else ''
            
            if district and district_name.lower() != district.lower():
                continue
            if developer and developer_name.lower() != developer.lower():
                continue
            
            if rooms == 'студия' and prop.rooms != 0:
                continue
            
            prop_floor = prop.floor if prop.floor else 0
            if floor_min and prop_floor < int(floor_min):
                continue
            if floor_max and prop_floor > int(floor_max):
                continue
            
            price = prop.price or 0
            cashback_rate = complex_obj.cashback_rate if complex_obj and complex_obj.cashback_rate else 5.0
            cashback = int(price * cashback_rate / 100)
            
            photos_list = []
            if prop.gallery_images:
                try:
                    if isinstance(prop.gallery_images, list):
                        photos_list = prop.gallery_images
                    elif isinstance(prop.gallery_images, str):
                        photos_list = json.loads(prop.gallery_images)
                except:
                    pass
            
            filtered_apartments.append({
                'id': prop.inner_id or prop.id,
                'complex_name': complex_obj.name if complex_obj else '',
                'complex_id': prop.complex_id,
                'district': district_name,
                'developer': developer_name,
                'rooms': 'студия' if prop.rooms == 0 else prop.rooms,
                'price': price,
                'cashback': cashback,
                'area': prop.area or 0,
                'floor': prop.floor if prop.floor else '',
                'max_floor': prop.total_floors if prop.total_floors else '',
                'type': 'студия' if prop.rooms == 0 else f'{prop.rooms}-комн',
                'status': 'сдан',
                'finishing': prop.renovation_type or '',
                'images': photos_list,
                'description': prop.description or '',
                'features': []
            })
        
        filtered_apartments.sort(key=lambda x: x['price'])
        filtered_apartments = filtered_apartments[:50]
        
        complexes = ResidentialComplexRepository.get_all_active() if not city_id_filter else [
            c for c in ResidentialComplexRepository.get_all_active() 
            if c.city_id == city_id_filter
        ]
        complexes_data = {c.id: {'name': c.name, 'district': c.district} for c in complexes}
        
        return jsonify({
            'success': True,
            'apartments': filtered_apartments,
            'complexes': complexes_data
        })
    except Exception as e:
        print(f"Error searching apartments: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@searches_bp.route('/api/complexes')
def get_complexes_api():
    """Get list of residential complexes for filter"""
    try:
        with open('data/residential_complexes.json', 'r', encoding='utf-8') as f:
            complexes_data = json.load(f)
        
        complexes_list = [
            {'id': complex_item.get('id'), 'name': complex_item.get('name', '')}
            for complex_item in complexes_data
        ]
        
        return jsonify({
            'success': True,
            'complexes': complexes_list
        })
    except Exception as e:
        print(f"Error loading complexes: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@csrf.exempt
@searches_bp.route('/api/properties/<property_id>')

@searches_bp.route('/api/properties/find-similar/<property_id>', methods=['GET'])
@login_required
def find_similar_properties(property_id):
    """Find similar properties for a given property (inner_id or database id)
    
    Returns similar properties based on:
    - Same city
    - Same number of rooms
    - Similar area (±15%)
    - Similar price (±20%)
    - Preferably same developer
    
    Usage:
        GET /api/properties/find-similar/1999611557?limit=10
    """
    from services.property_matcher import PropertyMatcher
    from models import Property
    
    try:
        # Конвертируем inner_id в database id
        property_obj = Property.query.filter_by(inner_id=str(property_id)).first()
        
        if not property_obj:
            # Try as database ID if inner_id lookup fails
            try:
                property_obj = Property.query.get(int(property_id))
            except (ValueError, TypeError):
                pass
        
        if not property_obj:
            return jsonify({
                'success': False,
                'error': 'Property not found'
            }), 404
        
        # Get limit from query params
        limit = request.args.get('limit', 10, type=int)
        limit = min(max(1, limit), 50)  # Clamp between 1 and 50
        
        # Find similar properties
        similar = PropertyMatcher.find_similar_properties(
            property_id=property_obj.id,
            limit=limit,
            city_id=property_obj.city_id
        )
        
        return jsonify({
            'success': True,
            'similar_properties': similar,
            'count': len(similar),
            'original_property': {
                'id': property_obj.id,
                'inner_id': property_obj.inner_id,
                'rooms': property_obj.rooms,
                'area': property_obj.area,
                'price': property_obj.price
            }
        })
    
    except Exception as e:
        print(f"Error finding similar properties: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@searches_bp.route('/api/complexes/filter', methods=['POST'])
@csrf.exempt
def filter_complexes_by_apartments():
    """Filter residential complexes based on apartment parameters"""
    from models import Property
    from repositories.property_repository import PropertyRepository, ResidentialComplexRepository
    
    try:
        filters = request.json or {}
        
        # Extract filters
        rooms = filters.get('rooms', [])  # e.g., ["1-комн", "2-комн"]
        price_from = filters.get('priceFrom')  # В млн
        price_to = filters.get('priceTo')  # В млн
        developers = filters.get('developers', [])
        completion = filters.get('completion', [])
        housing_class = filters.get('housingClass', [])
        area_from = filters.get('areaFrom')
        area_to = filters.get('areaTo')
        city_id = filters.get('city_id')
        
        # Получаем все комплексы с координатами (фильтруем по городу если задан)
        complexes_data = ResidentialComplexRepository.get_with_coordinates(city_id=city_id)
        property_stats = PropertyRepository.get_all_property_stats(city_id=city_id)
        
        filtered_complex_ids = set()
        
        # Если есть фильтр по комнатам, цене или площади - ищем через квартиры
        if rooms or price_from or price_to or area_from or area_to:
            # Строим SQL запрос для поиска квартир (только активные)
            query = Property.query.filter(Property.is_active == True)
            
            # Фильтр по городу
            if city_id:
                query = query.filter(Property.city_id == city_id)
            
            # Фильтр по комнатам
            if rooms:
                # Преобразуем "2-комн" -> 2
                room_numbers = []
                for r in rooms:
                    if 'студия' in r.lower():
                        room_numbers.append(0)
                    else:
                        try:
                            room_numbers.append(int(r.split('-')[0]))
                        except:
                            pass
                if room_numbers:
                    query = query.filter(Property.rooms.in_(room_numbers))
            
            # Фильтр по цене (млн рублей)
            if price_from:
                query = query.filter(Property.price >= price_from * 1000000)
            if price_to:
                query = query.filter(Property.price <= price_to * 1000000)
            
            # Фильтр по площади
            if area_from:
                query = query.filter(Property.area >= area_from)
            if area_to:
                query = query.filter(Property.area <= area_to)
            
            # Получаем ID комплексов с подходящими квартирами
            matching_properties = query.with_entities(Property.complex_id).distinct().all()
            filtered_complex_ids = {p.complex_id for p in matching_properties if p.complex_id}
        
        # Формируем результаты
        residential_complexes = []
        current_year = datetime.now().year
        
        for row in complexes_data:
            complex_id = row.id
            
            # Пропускаем если нужна фильтрация по квартирам и комплекс не подходит
            if (rooms or price_from or price_to or area_from or area_to) and complex_id not in filtered_complex_ids:
                continue
            
            stats = property_stats.get(complex_id, {})
            
            # Пропускаем комплексы без квартир
            if not stats or stats.get('total_count', 0) == 0:
                continue
            
            # Фильтр по застройщику
            if developers and row.developer_name not in developers:
                continue
            
            # Фильтр по классу жилья
            if housing_class and row.object_class_display_name and row.object_class_display_name not in housing_class:
                continue
            
            # Статус и дата сдачи
            end_build_year = row.end_build_year
            end_build_quarter = row.end_build_quarter
            status = 'Не указан'
            completion_date = 'Не указан'
            
            if end_build_year:
                if end_build_year <= current_year:
                    status = 'Сдан'
                else:
                    status = 'Строится'
                if end_build_quarter:
                    completion_date = f"{end_build_quarter} кв. {end_build_year}"
                else:
                    completion_date = str(end_build_year)
            
            # Фильтр по сдаче/статусу
            if completion:
                match_found = False
                for filter_val in completion:
                    if filter_val == 'Сдан' and status == 'Сдан':
                        match_found = True
                        break
                    elif completion_date and filter_val in completion_date:
                        match_found = True
                        break
                if not match_found:
                    continue
            
            # Добавляем комплекс в результаты
            residential_complexes.append({
                'id': complex_id,
                'name': row.name or '',
                'developer': row.developer_name or '',
                'address': '',  # Not in get_with_coordinates()
                'district': 'Краснодарский край',
                'apartments_count': stats.get('total_count', 0),
                'price_from': int(stats.get('min_price', 0)),
                'coordinates': {
                    'lat': float(row.latitude),
                    'lng': float(row.longitude)
                } if row.latitude and row.longitude else None,
                'completion_date': completion_date,
                'status': status,
                'cashback_percent': float(row.cashback_rate or 3.5),
                'main_image': row.main_image or '/static/images/no-photo.svg',
                'description': f'Жилой комплекс {row.name}',
                'object_class': row.object_class_display_name or 'Комфорт',
                'housing_class': row.object_class_display_name or 'Комфорт',
                'max_floors': 0,
                'url': f'/zk/{row.slug}' if row.slug else '#',
                'type': 'complex'
            })
        
        print(f"✅ Filtered {len(residential_complexes)} complexes (from {len(complexes_data)} total)")
        
        return jsonify({
            'success': True,
            'complexes': residential_complexes,
            'total': len(residential_complexes)
        })
        
    except Exception as e:
        print(f"❌ Error filtering complexes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400
def get_property_details(property_id):
    """Get detailed property information using normalized tables"""
    from repositories.property_repository import PropertyRepository
    
    try:
        prop = PropertyRepository.get_by_id(property_id)
        
        if not prop:
            return jsonify({'success': False, 'error': 'Property not found'}), 404
        
        complex_obj = prop.residential_complex
        developer_obj = prop.developer
        
        price = prop.price or 0
        cashback_rate = complex_obj.cashback_rate if complex_obj and complex_obj.cashback_rate else 5.0
        cashback = int(price * cashback_rate / 100)
        
        property_info = {
            'id': prop.inner_id or prop.id,
            'complex_name': complex_obj.name if complex_obj else '',
            'district': complex_obj.district if complex_obj else '',
            'developer': developer_obj.name if developer_obj else '',
            'rooms': prop.rooms or 0,
            'price': price,
            'cashback': cashback,
            'area': prop.area or 0,
            'floor': f"{prop.floor}/{prop.total_floors}" if prop.floor and prop.total_floors else '',
            'type': prop.deal_type or 'Первичка',
            'description': prop.description or '',
            'features': []
        }
        
        return jsonify({
            'success': True,
            'property': property_info
        })
    except Exception as e:
        print(f"Error getting property details: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

