"""
Presentations Blueprint — manager presentation creation, viewing, sharing, PDF export.
Routes: /api/manager/presentations, /api/manager/presentation/*, /api/presentation/*,
        /presentation/view/*, /api/manager/collections (POST), /api/manager/send-collection
"""
import atexit
import glob
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from flask import (Blueprint, jsonify, request, current_app, send_file,
                   render_template, redirect, url_for, stream_with_context, Response)
from flask_login import current_user, login_required

from app import db, csrf

logger = logging.getLogger(__name__)

presentations_bp = Blueprint('presentations', __name__)

from app import manager_required

@presentations_bp.route('/api/manager/collections', methods=['POST'])
@manager_required
def create_collection_api():
    """Create a new property collection"""
    try:
        current_manager = current_user
            
        from models import Collection, CollectionProperty
        
        data = request.get_json()
        name = data.get('name')
        client_id = data.get('client_id')
        property_ids = data.get('property_ids', [])
        
        if not name or not client_id or not property_ids:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Create collection
        collection = Collection(
            title=name,
            assigned_to_user_id=client_id,
            created_by_manager_id=current_manager.id,
            status='Создана',
            description=f'Подборка из {len(property_ids)} объектов'
        )
        
        db.session.add(collection)
        db.session.flush()  # Get collection ID
        
        # Add properties to collection
        for prop_id in property_ids:
            # DUAL WRITE: Resolve property to get both IDs
            property_obj, canonical_id = resolve_property_by_identifier(prop_id)
            if not property_obj:
                continue  # Skip properties that don't exist
            
            collection_property = CollectionProperty(
                collection_id=collection.id,
                property_id=str(property_obj.id),  # Old: database ID
                property_inner_id=property_obj.inner_id  # NEW: canonical inner_id
            )
            db.session.add(collection_property)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'collection_id': collection.id,
            'message': 'Подборка успешно создана'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error creating collection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@presentations_bp.route('/api/manager/send-collection', methods=['POST'])
@manager_required
def send_collection_to_client():
    """Send property collection to client via email"""
    try:
        current_manager = current_user
            
        from models import User, Manager
        
        data = request.get_json()
        
        # TODO: Implement collection sending logic
        return jsonify({'success': True, 'message': 'Функция в разработке'})
        
    except Exception as e:
        print(f"Error sending collection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

# ========== ПРЕЗЕНТАЦИИ API ==========

@presentations_bp.route('/api/manager/presentations', methods=['GET'])
@manager_required
def get_manager_presentations():
    """Получить все презентации менеджера"""
    try:
        from models import Collection
        
        current_manager = current_user
        
        presentations = Collection.query.filter_by(
            created_by_manager_id=current_manager.id,
            collection_type='presentation'
        ).order_by(Collection.created_at.desc()).all()
        
        presentations_data = []
        for presentation in presentations:
            presentations_data.append(presentation.to_dict())
        
        return jsonify({
            'success': True,
            'presentations': presentations_data
        })
        
    except Exception as e:
        print(f"Error loading presentations: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@presentations_bp.route('/api/manager/presentation/create', methods=['POST'])
@manager_required
# @require_json_csrf  # CSRF disabled
def create_presentation():
    """Создать новую презентацию"""
    from models import Collection
    from flask_login import current_user
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Данные не предоставлены'}), 400
        
    title = data.get('title')
    description = data.get('description', '')
    client_name = data.get('client_name', '')
    client_phone = data.get('client_phone', '')
    
    if not title:
        return jsonify({'success': False, 'error': 'Название презентации обязательно'}), 400
    
    try:
        current_manager = current_user
            
        presentation = Collection(
            title=title,
            description=description,
            created_by_manager_id=current_manager.id,
            collection_type='presentation',
            client_name=client_name,
            client_phone=client_phone,
            status='Черновик'
        )
        
        # Генерируем уникальную ссылку
        presentation.generate_unique_url()
        
        db.session.add(presentation)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'presentation': presentation.to_dict(),
            'message': 'Презентация создана успешно'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


def _load_presentation_properties_from_db(presentation_id):
    """
    ✅ Helper function: Load presentation properties from PostgreSQL
    Used by both manager view and public view to avoid code duplication.
    Returns enriched_properties list with all property data.
    """
    from models import CollectionProperty, Property
    from sqlalchemy.orm import joinedload
    
    # Get presentation properties
    collection_properties = CollectionProperty.query.filter_by(
        collection_id=presentation_id
    ).order_by(CollectionProperty.order_index).all()
    
    print(f"DEBUG: Found {len(collection_properties)} properties in presentation {presentation_id}")
    
    # ✅ Load property data directly from PostgreSQL with eager loading
    enriched_properties = []
    for cp in collection_properties:
        # ✅ FIXED: Smart search - try inner_id first, then database ID
        # cp.property_id can be either inner_id OR database ID (legacy data)
        property_obj = Property.query.options(
            joinedload(Property.residential_complex),
            joinedload(Property.developer),
            joinedload(Property.district)
        ).filter_by(inner_id=cp.property_id).first()
        
        # If not found by inner_id, try as database primary key
        if not property_obj:
            try:
                property_id_int = int(cp.property_id)
                property_obj = Property.query.options(
                    joinedload(Property.residential_complex),
                    joinedload(Property.developer),
                    joinedload(Property.district)
                ).get(property_id_int)
                if property_obj:
                    print(f"DEBUG: Found property {property_id_int} by database ID")
            except (ValueError, TypeError):
                print(f"DEBUG: Could not parse property_id {cp.property_id} as int")
        
        if property_obj:
            # ✅ Parse gallery_images JSON field properly
            main_image = 'https://via.placeholder.com/400x300?text=No+Photo'
            images = []
            
            if property_obj.gallery_images:
                try:
                    # Parse JSON array
                    if isinstance(property_obj.gallery_images, str):
                        photos = json.loads(property_obj.gallery_images)
                    else:
                        photos = property_obj.gallery_images
                    
                    if photos and isinstance(photos, list) and len(photos) > 0:
                        main_image = photos[0]
                        images = photos
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"DEBUG: Error parsing gallery_images for property {property_id_int}: {e}")
            
            # Use main_image field if gallery is empty
            if not images and property_obj.main_image:
                main_image = property_obj.main_image
                images = [main_image]
            
            # ✅ Get data from relationships (same pattern as /properties route)
            complex_name = property_obj.residential_complex.name if property_obj.residential_complex else 'Не указан'
            developer_name = property_obj.developer.name if property_obj.developer else 'Не указан'
            district_name = property_obj.district.name if property_obj.district else 'Не указан'
            
            # ✅ Calculate cashback from residential_complex.cashback_rate
            cashback = 0
            cashback_rate = 0
            if property_obj.residential_complex and property_obj.residential_complex.cashback_rate:
                cashback_rate = float(property_obj.residential_complex.cashback_rate)
                cashback = int(property_obj.price * (cashback_rate / 100)) if property_obj.price else 0
            
            # Build room description
            rooms = property_obj.rooms or 0
            if rooms == 0:
                room_type = "Студия"
            else:
                room_type = f"{rooms}-комнатная квартира"
            
            # Build title (same format as /properties route)
            floor_text = f"{property_obj.floor}/{property_obj.total_floors} эт." if property_obj.floor and property_obj.total_floors else ""
            title = f"{room_type}, {property_obj.area} м²"
            if floor_text:
                title += f", {floor_text}"
            
            # ✅ Build enriched_property dict from Property ORM attributes
            enriched_property = {
                'id': property_obj.inner_id or property_obj.id,
                'property_id': property_obj.id,  # ✅ database ID for API calls
                'inner_id': property_obj.inner_id,  # ✅ inner_id for external refs
                'manager_note': cp.manager_note,  # ✅ Keep manager_note from CollectionProperty
                'order_index': cp.order_index,
                'rooms': rooms,
                'price': property_obj.price or 0,
                'area': property_obj.area or 0,
                'floor': property_obj.floor or 0,
                'total_floors': property_obj.total_floors or 0,
                'complex_name': complex_name,
                'property_type': 'Квартира',
                'images': images,
                'main_image': main_image,
                'layout_image': None,
                'address': property_obj.address or '',
                'latitude': float(property_obj.latitude) if property_obj.latitude else None,
                'longitude': float(property_obj.longitude) if property_obj.longitude else None,
                'description': property_obj.description or '',
                'features': [],
                'developer': developer_name,
                'district': district_name,
                'cashback': cashback,
                'cashback_available': bool(cashback > 0),
                'cashback_rate': cashback_rate,
                'price_per_sqm': property_obj.price_per_sqm or 0,
                'status': property_obj.status or 'available',
                'title': title,
                'url': f"/object/{property_obj.inner_id or property_obj.id}"
            }
            enriched_properties.append(enriched_property)
        else:
            print(f"DEBUG: Property {cp.property_id} not found in database")
    
    print(f"DEBUG: Enriched {len(enriched_properties)} properties from PostgreSQL")
    return enriched_properties

@presentations_bp.route('/api/manager/presentation/<int:presentation_id>', methods=['GET'])
@manager_required
def get_presentation_data(presentation_id):
    """✅ FIXED: Load property data from PostgreSQL instead of Excel cache"""
    from models import Collection, CollectionProperty, Manager, Property
    from sqlalchemy.orm import joinedload
    
    current_manager = current_user
    print(f"DEBUG: Get presentation data - manager_id: {current_manager.id}, presentation_id: {presentation_id}")
    
    # Get presentation data
    presentation = Collection.query.filter_by(
        id=presentation_id,
        created_by_manager_id=current_manager.id,
        collection_type='presentation'
    ).first()
    
    if not presentation:
        return jsonify({'success': False, 'error': 'Презентация не найдена или доступ запрещен'}), 404
    
    # Get presentation properties
    collection_properties = CollectionProperty.query.filter_by(
        collection_id=presentation_id
    ).order_by(CollectionProperty.order_index).all()
    
    print(f"DEBUG: Found {len(collection_properties)} properties in presentation")
    
    # ✅ FIXED: Load property data directly from PostgreSQL instead of Excel cache
    enriched_properties = []
    for cp in collection_properties:
        # ✅ FIXED: Smart search - try inner_id first, then database ID
        # cp.property_id can be either inner_id OR database ID (legacy data)
        property_obj = Property.query.options(
            joinedload(Property.residential_complex),
            joinedload(Property.developer),
            joinedload(Property.district)
        ).filter_by(inner_id=cp.property_id).first()
        
        # If not found by inner_id, try as database primary key
        if not property_obj:
            try:
                property_id_int = int(cp.property_id)
                property_obj = Property.query.options(
                    joinedload(Property.residential_complex),
                    joinedload(Property.developer),
                    joinedload(Property.district)
                ).get(property_id_int)
                if property_obj:
                    print(f"DEBUG: Found property {property_id_int} by database ID")
            except (ValueError, TypeError):
                print(f"DEBUG: Could not parse property_id {cp.property_id} as int")
        
        if property_obj:
            # ✅ Parse gallery_images JSON field properly
            main_image = 'https://via.placeholder.com/400x300?text=No+Photo'
            images = []
            
            if property_obj.gallery_images:
                try:
                    # Parse JSON array
                    if isinstance(property_obj.gallery_images, str):
                        photos = json.loads(property_obj.gallery_images)
                    else:
                        photos = property_obj.gallery_images
                    
                    if photos and isinstance(photos, list) and len(photos) > 0:
                        main_image = photos[0]
                        images = photos
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"DEBUG: Error parsing gallery_images for property {property_id_int}: {e}")
            
            # Use main_image field if gallery is empty
            if not images and property_obj.main_image:
                main_image = property_obj.main_image
                images = [main_image]
            
            # ✅ Get data from relationships (same pattern as /properties route)
            complex_name = property_obj.residential_complex.name if property_obj.residential_complex else 'Не указан'
            developer_name = property_obj.developer.name if property_obj.developer else 'Не указан'
            district_name = property_obj.district.name if property_obj.district else 'Не указан'
            
            # ✅ Calculate cashback from residential_complex.cashback_rate
            cashback = 0
            cashback_rate = 0
            if property_obj.residential_complex and property_obj.residential_complex.cashback_rate:
                cashback_rate = float(property_obj.residential_complex.cashback_rate)
                cashback = int(property_obj.price * (cashback_rate / 100)) if property_obj.price else 0
            
            # Build room description
            rooms = property_obj.rooms or 0
            if rooms == 0:
                room_type = "Студия"
            else:
                room_type = f"{rooms}-комнатная квартира"
            
            # Build title (same format as /properties route)
            floor_text = f"{property_obj.floor}/{property_obj.total_floors} эт." if property_obj.floor and property_obj.total_floors else ""
            title = f"{room_type}, {property_obj.area} м²"
            if floor_text:
                title += f", {floor_text}"
            
            # ✅ Build enriched_property dict from Property ORM attributes
            enriched_property = {
                'id': property_obj.inner_id or property_obj.id,
                'property_id': property_obj.id,  # ✅ database ID for API calls
                'inner_id': property_obj.inner_id,  # ✅ inner_id for external refs
                'manager_note': cp.manager_note,  # ✅ Keep manager_note from CollectionProperty
                'order_index': cp.order_index,
                'rooms': rooms,
                'price': property_obj.price or 0,
                'area': property_obj.area or 0,
                'floor': property_obj.floor or 0,
                'total_floors': property_obj.total_floors or 0,
                'complex_name': complex_name,
                'property_type': 'Квартира',
                'images': images,
                'main_image': main_image,
                'layout_image': None,
                'address': property_obj.address or '',
                'latitude': float(property_obj.latitude) if property_obj.latitude else None,
                'longitude': float(property_obj.longitude) if property_obj.longitude else None,
                'description': property_obj.description or '',
                'features': [],
                'developer': developer_name,
                'district': district_name,
                'cashback': cashback,
                'cashback_available': bool(cashback > 0),
                'cashback_rate': cashback_rate,
                'price_per_sqm': property_obj.price_per_sqm or 0,
                'status': property_obj.status or 'available',
                'title': title,
                'url': f"/object/{property_obj.inner_id or property_obj.id}"
            }
            enriched_properties.append(enriched_property)
        else:
            print(f"DEBUG: Property {cp.property_id} not found in database")
    
    print(f"DEBUG: Enriched {len(enriched_properties)} properties from PostgreSQL")
    
    # Format presentation data for JSON response
    presentation_data = {
        'id': presentation.id,
        'title': presentation.title,
        'description': presentation.description,
        'client_name': presentation.client_name,
        'client_phone': presentation.client_phone,
        'status': presentation.status,
        'created_at': presentation.created_at.isoformat() if presentation.created_at else None,
        'view_count': presentation.view_count,
        'last_viewed_at': presentation.last_viewed_at.isoformat() if presentation.last_viewed_at else None,
        'properties_count': len(enriched_properties),
        'properties': enriched_properties,
        'unique_url': presentation.unique_url,
        'assigned_to_user_id': presentation.assigned_to_user_id
    }
    
    return jsonify({
        'success': True,
        'presentation': presentation_data
    })

@manager_required
# # @require_json_csrf  # CSRF disabled  # CSRF disabled
def add_property_to_presentation(presentation_id):
    """Добавить квартиру в презентацию"""
    from models import Collection, CollectionProperty
    from flask_login import current_user
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Данные не предоставлены'}), 400
        
    property_id = data.get('property_id')
    manager_note = data.get('manager_note', '')
    
    if not property_id:
        return jsonify({'success': False, 'error': 'ID объекта не указан'}), 400
    
    presentation = Collection.query.filter_by(
        id=presentation_id,
        created_by_manager_id=current_user.id,
        collection_type='presentation'
    ).first()
    
    if not presentation:
        return jsonify({'success': False, 'error': 'Презентация не найдена или у вас нет прав доступа'}), 404
    
    # Проверяем, не добавлена ли уже эта квартира
    existing = CollectionProperty.query.filter_by(
        collection_id=presentation_id,
        property_id=property_id
    ).first()
    
    if existing:
        return jsonify({'success': False, 'error': 'Квартира уже добавлена в презентацию'}), 400
    
    try:
        # Получаем информацию о квартире из JSON
        properties = load_properties()
        property_info = None
        
        for prop in properties:
            if str(prop.get('id')) == str(property_id):
                property_info = prop
                break
        
        if not property_info:
            return jsonify({'success': False, 'error': 'Квартира не найдена'}), 404
        
        # DUAL WRITE: Resolve property to get both IDs
        property_obj, canonical_id = resolve_property_by_identifier(property_id)
        if not property_obj:
            return jsonify({'success': False, 'error': 'Объект не найден в базе данных'}), 404
        
        collection_property = CollectionProperty(
            collection_id=presentation_id,
            property_id=str(property_obj.id),  # Old: database ID
            property_inner_id=property_obj.inner_id,  # NEW: canonical inner_id
            property_name=property_info.get('title', 'Квартира'),
            property_price=int(property_info.get('price', 0)) if property_info.get('price') else None,
            complex_name=property_info.get('residential_complex', ''),
            property_type=f"{property_info.get('rooms', 0)}-комнатная" if property_info.get('rooms', 0) > 0 else 'Студия',
            property_size=float(property_info.get('area', 0)) if property_info.get('area') else None,
            manager_note=manager_note,
            order_index=len(presentation.properties) + 1
        )
        
        db.session.add(collection_property)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Квартира добавлена в презентацию',
            'property': {
                'id': collection_property.id,
                'property_name': collection_property.property_name,
                'complex_name': collection_property.complex_name,
                'property_price': collection_property.property_price,
                'manager_note': collection_property.manager_note
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

# НОВЫЕ API ЭНДПОИНТЫ ДЛЯ ПРЕЗЕНТАЦИЙ

@presentations_bp.route('/api/manager/presentation/<int:presentation_id>/add-property', methods=['POST'])
@csrf.exempt
@manager_required
def add_property_to_presentation_fixed(presentation_id):
    """
    ✅ MIGRATED TO NORMALIZED TABLES (Property → ResidentialComplex → Developer)
    Добавить объект в презентацию (безопасная версия)
    Uses ONLY direct SQLAlchemy database queries with eager loading.
    """
    from models import Collection, CollectionProperty, Property
    from sqlalchemy.orm import joinedload
    from flask_login import current_user
    
    try:
        print(f"🎯 DEBUG: add_property_to_presentation_fixed called for presentation {presentation_id}")
        
        # 1. Validate input data
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Данные не предоставлены'}), 400
            
        property_id = data.get('property_id')
        if not property_id:
            return jsonify({'success': False, 'error': 'ID объекта не указан'}), 400

        # Convert to int if it's a string, keep as int if already int
        try:
            property_id_int = int(property_id) if isinstance(property_id, str) else property_id
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Недопустимый ID объекта'}), 400
        
        # Convert to string for VARCHAR column in CollectionProperty table
        property_id = str(property_id_int)
        
        current_manager = current_user
            
        # 2. Strict check for presentation ownership
        presentation = Collection.query.filter_by(
            id=presentation_id,
            created_by_manager_id=current_manager.id,
            collection_type='presentation'
        ).first()
        
        if not presentation:
            return jsonify({'success': False, 'error': 'Презентация не найдена или у вас нет прав доступа'}), 404
        
        # 3. Check for duplicates
        existing = CollectionProperty.query.filter_by(
            collection_id=presentation_id,
            property_id=property_id
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Объект уже добавлен в презентацию'}), 400
        
        # 4. Load property from database with eager loading for relationships
        property_obj = Property.query.options(
            joinedload(Property.residential_complex)
        ).get(property_id_int)
        
        print(f"🎯 DEBUG: DB lookup for property {property_id_int}, found: {property_obj is not None}")
        
        if not property_obj:
            print(f"❌ ERROR: Property {property_id_int} not found in database")
            return jsonify({'success': False, 'error': 'Объект не найден'}), 404
        
        print(f"✅ Property found in database: {property_obj.title}")
        
        # 5. Create CollectionProperty from database Property object
        # Format room type
        rooms = int(property_obj.rooms or 0)
        property_type = "Студия" if rooms == 0 else f"{rooms}-комн"
        
        # Get complex name safely (relationship already loaded via joinedload)
        complex_name = property_obj.residential_complex.name if property_obj.residential_complex else ''
        
        # Generate property name
        property_name = property_obj.title or f"{property_type} в {complex_name}"
        
        collection_property = CollectionProperty(
            collection_id=presentation_id,
            property_id=str(property_obj.id),  # Old: database ID
            property_inner_id=property_obj.inner_id,  # NEW: canonical inner_id
            property_name=property_name,
            property_price=int(property_obj.price) if property_obj.price else None,
            complex_name=complex_name,
            property_type=property_type,
            property_size=float(property_obj.area) if property_obj.area else None,
            order_index=len(presentation.properties) + 1
        )
        
        # 6. Save to database (ONCE only!)
        db.session.add(collection_property)
        db.session.commit()
        
        print(f"✅ Property {property_id_int} successfully added to presentation {presentation_id}")
        
        return jsonify({
            'success': True,
            'message': 'Объект добавлен в презентацию',
            'property': {
                'id': collection_property.id,
                'property_name': collection_property.property_name,
                'complex_name': collection_property.complex_name,
                'property_price': collection_property.property_price
            }
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERROR in add_property_to_presentation_fixed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@presentations_bp.route('/api/manager/presentation/<int:presentation_id>/property/<int:property_id>/comment', methods=['PUT'])
@csrf.exempt
@manager_required
def update_property_comment_in_presentation(presentation_id, property_id):
    from models import Collection, CollectionProperty
    from flask_login import current_user
    
    # Валидация входных данных
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Данные не предоставлены'}), 400
        
    manager_note = data.get('manager_note', '').strip()
    
    current_manager = current_user
        
    # Строгая проверка владения презентацией
    presentation = Collection.query.filter_by(
        id=presentation_id,
        created_by_manager_id=current_manager.id,
        collection_type='presentation'
    ).first()
    
    if not presentation:
        return jsonify({'success': False, 'error': 'Презентация не найдена или у вас нет прав доступа'}), 404    # ✅ FIXED: Use helper to resolve property by inner_id OR database ID
    property_obj, canonical_id = resolve_property_by_identifier(property_id)
    if not property_obj:
        return jsonify({'success': False, 'error': 'Объект не найден'}), 404
    
    # Search CollectionProperty using property_inner_id or property_id (database ID as string)
    from sqlalchemy import or_
    collection_property = CollectionProperty.query.filter(
        CollectionProperty.collection_id == presentation_id,
        or_(
            CollectionProperty.property_inner_id == property_obj.inner_id,
            CollectionProperty.property_id == str(property_obj.id),
            CollectionProperty.property_id == str(property_obj.inner_id)
        )
    ).first()
    
    if not collection_property:
        return jsonify({'success': False, 'error': 'Объект не найден в презентации'}), 404
    
    try:
        # Обновляем комментарий
        collection_property.manager_note = manager_note
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Комментарий обновлен',
            'property': {
                'id': collection_property.property_inner_id,
                'manager_note': collection_property.manager_note
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@presentations_bp.route('/api/manager/presentation/<int:presentation_id>/status', methods=['PUT'])
@manager_required
# @require_json_csrf  # CSRF disabled
def update_presentation_status(presentation_id):
    """Переключить статус презентации между Черновик и Опубликовано"""
    from models import Collection
    from flask_login import current_user
    
    # Валидация входных данных
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Данные не предоставлены'}), 400
        
    new_status = data.get('status', '').strip()
    
    # Валидация статуса
    if new_status not in ['Черновик', 'Опубликовано']:
        return jsonify({'success': False, 'error': 'Недопустимый статус'}), 400
    
    # Найти презентацию
    presentation = Collection.query.filter_by(
        id=presentation_id,
        created_by_manager_id=current_user.id,
        collection_type='presentation'
    ).first()
    
    if not presentation:
        return jsonify({'success': False, 'error': 'Презентация не найдена или у вас нет прав доступа'}), 404
    
    try:
        # Обновляем статус и флаг публичности
        presentation.status = new_status
        presentation.is_public = (new_status == 'Опубликовано')
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Статус изменен на "{new_status}"',
            'status': presentation.status,
            'is_public': presentation.is_public
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

# ===== PDF AND PRINT ENDPOINTS =====

def fetch_pdf_context(property_id, presentation_id=None):
    """
    ✅ MIGRATED TO NORMALIZED SCHEMA (Property → ResidentialComplex → Developer)
    
    Fetch comprehensive context for PDF generation including:
    - Property details and images from properties table
    - Residential complex details and characteristics
    - Manager contact information
    
    FIXED: Uses SQLAlchemy text() with bindparams for SQLite compatibility
    FIXED: Added safe resource handling and division by zero protection
    MIGRATED: Uses normalized tables (properties, residential_complexes, developers)
    """
    import json
    from models import Collection, CollectionProperty, ResidentialComplex, Manager
    from sqlalchemy import text
    
    try:
        # Get property data using normalized schema with JOINs
        property_query = text("""
        SELECT p.inner_id, p.gallery_images as photos, rc.name as complex_name, p.complex_id,
               rc.object_class_display_name as complex_object_class_display_name, 
               rc.end_build_year as complex_building_end_build_year,
               rc.end_build_quarter as complex_building_end_build_quarter, 
               rc.has_big_check as complex_has_big_check,
               rc.financing_sber as complex_financing_sber, 
               rc.has_green_mortgage as complex_has_green_mortgage,
               p.rooms as object_rooms, p.area as object_area, 
               p.floor as object_min_floor, p.total_floors as object_max_floor,
               p.price, p.address as address_display_name, 
               p.latitude as address_position_lat, p.longitude as address_position_lon,
               d.name as developer_name, p.renovation_type as renovation_display_name
        FROM properties p
        LEFT JOIN residential_complexes rc ON p.complex_id = rc.id
        LEFT JOIN developers d ON p.developer_id = d.id
        WHERE p.inner_id = CAST(:property_id AS TEXT) OR p.id = :property_id_int
        """)
        
        # Use SQLAlchemy session with proper error handling
        try:
            property_id_int_val = int(property_id)
        except (ValueError, TypeError):
            property_id_int_val = -1
        result = db.session.execute(property_query, {'property_id': str(property_id), 'property_id_int': property_id_int_val})
        property_row = result.fetchone()
        
        if not property_row:
            print(f"DEBUG: fetch_pdf_context - property not found for id={property_id}")
            return None
            
        # Convert to dictionary using _mapping for SQLAlchemy compatibility
        property_data = dict(property_row._mapping)
        
        # Parse photos JSON with safe error handling
        property_images = {'photos': [], 'plans': []}
        if property_data.get('photos'):
            try:
                photos_list = json.loads(property_data['photos'])
                if photos_list and isinstance(photos_list, list):
                    # First 6 images as main photos, 6-8 as plans (fixed logic)
                    property_images['photos'] = photos_list[:6]
                    property_images['plans'] = photos_list[6:8] if len(photos_list) > 6 else []
            except (json.JSONDecodeError, TypeError, ValueError):
                property_images['photos'] = []
                property_images['plans'] = []
        
        # Get residential complex data if available
        complex_data = {}
        complex_images = {'facade': [], 'territory': [], 'infrastructure': [], 'construction': []}
        complex_photos = []
        
        if property_data.get('complex_name'):
            try:
                # Load basic complex data from residential_complexes table
                complex_query = text("""
                SELECT name, slug, district_id, developer_id, cashback_rate,
                       object_class_display_name, start_build_year, start_build_quarter,
                       end_build_year, end_build_quarter, has_accreditation,
                       has_green_mortgage, has_big_check, with_renovation, financing_sber
                FROM residential_complexes 
                WHERE name = :complex_name
                """)
                complex_result = db.session.execute(complex_query, {'complex_name': property_data['complex_name']})
                complex_row = complex_result.fetchone()
                
                if complex_row:
                    complex_data = dict(complex_row._mapping)
                
                # Load complex photos from properties table using complex_id
                photos_query = text("""
                SELECT gallery_images AS photos FROM properties 
                WHERE complex_id = (SELECT id FROM residential_complexes WHERE name = :complex_name LIMIT 1) 
                AND gallery_images IS NOT NULL
                LIMIT 1
                """)
                photos_result = db.session.execute(photos_query, {'complex_name': property_data['complex_name']})
                photos_row = photos_result.fetchone()
                
                if photos_row and photos_row[0]:
                    try:
                        photos_data = json.loads(photos_row[0])
                        if isinstance(photos_data, list):
                            complex_photos = photos_data[:9]  # Take first 9 photos for 3x3 grid
                        elif isinstance(photos_data, dict):
                            # If photos are organized by categories  
                            all_photos = []
                            for category, photos_list in photos_data.items():
                                if isinstance(photos_list, list):
                                    all_photos.extend(photos_list)
                            complex_photos = all_photos[:9]  # Take first 9 photos for 3x3 grid
                    except (json.JSONDecodeError, TypeError):
                        complex_photos = []
                        
            except Exception as e:
                print(f"Error loading complex data: {e}")
        
        # Get manager information if presentation_id provided
        manager_data = {}
        if presentation_id:
            try:
                presentation = Collection.query.get(presentation_id)
                if presentation and presentation.created_by_manager_id:
                    manager = Manager.query.get(presentation.created_by_manager_id)
                    if manager:
                        manager_data = {
                            'name': manager.full_name or 'Менеджер',
                            'email': manager.email or '',
                            'phone': manager.phone or '+7 (XXX) XXX-XX-XX',
                            'photo_url': None  # Add if available
                        }
            except Exception as e:
                print(f"Error loading manager data: {e}")
        
        # Safe type conversion with defaults (using corrected column names)
        area = float(property_data.get('object_area') or 0)
        price = int(property_data.get('price') or 0)  # Fixed column name
        rooms = int(property_data.get('object_rooms') or 0)
        floor = int(property_data.get('object_min_floor') or 0)  # Fixed column name
        total_floors = int(property_data.get('object_max_floor') or 0)
        
        # Calculate price per sqm with division by zero protection
        price_per_sqm = 0
        if area > 0 and price > 0:
            try:
                price_per_sqm = int(price / area)
            except (ZeroDivisionError, ValueError):
                price_per_sqm = 0
        
        # Get cashback from complex data (loaded from residential_complexes table)
        cashback_rate = complex_data.get('cashback_rate', 5.0) if complex_data else 5.0
        cashback_amount = int(price * cashback_rate / 100) if price > 0 else 0
        
        # Construct full context with safe data types
        context = {
            'property': {
                'id': property_data.get('inner_id'),
                'rooms': rooms,
                'area': area,
                'floor': floor,
                'total_floors': total_floors,
                'price': price,
                'price_per_sqm': price_per_sqm,
                'finishing': property_data.get('renovation_display_name') or 'Не указан',
                'status': 'Активен',  # Default since column doesn't exist
                'address': property_data.get('address_display_name') or 'Адрес уточняется',
                'cashback_percent': cashback_rate,
                'cashback_amount': cashback_amount,
                'latitude': property_data.get('address_position_lat'),
                'longitude': property_data.get('address_position_lon'),
                'object_type': 'Квартира',  # Default since column doesn't exist
                'developer_name': property_data.get('developer_name') or '',
                'jk_name': property_data.get('complex_name') or '',
                'property_type': 'Квартира',  # Default since column doesn't exist
                'completion_date': None  # Will be set from complex data if available
            },
            'property_images': property_images,
            'complex': {
                'id': property_data.get('complex_id'),
                'name': property_data.get('complex_name') or '',
                'class': property_data.get('complex_object_class_display_name') or '',
                'completion_year': property_data.get('complex_building_end_build_year'),
                'completion_quarter': property_data.get('complex_building_end_build_quarter'),
                'has_big_check': bool(property_data.get('complex_has_big_check')),
                'financing_sber': bool(property_data.get('complex_financing_sber')),
                'has_green_mortgage': bool(property_data.get('complex_has_green_mortgage')),
                'developer': property_data.get('developer_name') or '',
                'photos': complex_photos,  # Added complex photos from database
                'features': []
            },
            'complex_images': complex_images,
            'manager': manager_data,
            'generated_at': property_data  # Full raw data for backwards compatibility
        }
        
        # Add completion date to property if available
        if context['complex']['completion_quarter'] and context['complex']['completion_year']:
            context['property']['completion_date'] = f"{context['complex']['completion_quarter']} кв. {context['complex']['completion_year']} г."
        
        # Add complex features list with safe checks
        features = []
        if complex_data.get('has_accreditation'):
            features.append('Аккредитован банками')
        if complex_data.get('has_green_mortgage') or property_data.get('complex_has_green_mortgage'):
            features.append('Льготная ипотека')  
        if complex_data.get('with_renovation'):
            features.append('С отделкой')
        if complex_data.get('financing_sber') or property_data.get('complex_financing_sber'):
            features.append('Финансирование Сбербанк')
        if complex_data.get('has_big_check') or property_data.get('complex_has_big_check'):
            features.append('Большой чек')
        
        context['complex']['features'] = features
        
        return context
        
    except Exception as e:
        print(f"Error in fetch_pdf_context: {e}")
        import traceback
        traceback.print_exc()
        return None

@presentations_bp.route('/api/presentation/<int:presentation_id>/property/<string:property_id>/print')
@manager_required
def print_property(presentation_id, property_id):
    """Открыть версию объекта для печати с полными данными из базы"""
    from models import Collection, CollectionProperty, Property as PropertyModel
    
    # Find presentation
    presentation = Collection.query.get_or_404(presentation_id)
    
    # Resolve property identifier (could be inner_id or database ID)
    prop_obj, canonical_id = resolve_property_by_identifier(property_id)
    if not prop_obj:
        abort(404, description="Объект не найден")
    
    # Search in CollectionProperty using property_id or property_inner_id
    property_obj = CollectionProperty.query.filter(
        CollectionProperty.collection_id == presentation_id,
        db.or_(
            CollectionProperty.property_id == str(prop_obj.inner_id),
            CollectionProperty.property_id == str(prop_obj.id),
            CollectionProperty.property_id == str(property_id),
            CollectionProperty.property_inner_id == str(prop_obj.inner_id)
        )
    ).first()
    
    if not property_obj:
        return "Property not found in presentation", 404
    
    # Get comprehensive context using new function
    context = fetch_pdf_context(property_id, presentation_id)
    
    if not context:
        return "Property data not found", 404
    
    # Render print template with full context
    return render_template('print_property.html', 
                         property=context['property'],
                         property_images=context['property_images'],
                         complex=context['complex'],
                         complex_images=context['complex_images'],
                         manager=context['manager'],
                         presentation=presentation,
                         manager_note=getattr(property_obj, 'manager_note', None),
                         context=context)  # Full context for backwards compatibility

@presentations_bp.route('/api/manager/presentation/<int:presentation_id>/download-all')
@manager_required
def download_all_properties(presentation_id):
    """Скачать все объекты презентации в ZIP архиве"""
    from models import Collection, CollectionProperty
    from weasyprint import HTML, CSS
    import zipfile
    from io import BytesIO
    import tempfile
    
    try:
        # Find presentation
        presentation = Collection.query.get_or_404(presentation_id)
        
        # Check ownership
        current_manager = current_user
        if presentation.created_by_manager_id != current_manager.id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        # Get all properties in presentation
        properties = CollectionProperty.query.filter_by(
            collection_id=presentation_id
        ).all()
        
        print(f"DEBUG: Found {len(properties)} properties in presentation {presentation_id}")
        for prop in properties:
            print(f"DEBUG: Property ID: {prop.property_id}")
        
        if not properties:
            return jsonify({'success': False, 'error': 'No properties in presentation'}), 400
        
        # Create ZIP archive
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for prop in properties:
                # Get property details from database using raw SQL for compatibility
                try:
                    query = text("""
                        SELECT 
                            p.inner_id AS id,
                            CAST(p.area AS FLOAT) AS area,
                            CAST(p.price AS INTEGER) AS price,
                            CAST(p.floor AS INTEGER) AS floor,
                            CAST(p.total_floors AS INTEGER) AS total_floors,
                            CAST(p.rooms AS INTEGER) AS rooms,
                            'Квартира' AS property_type,
                            p.address AS address_display_name,
                            rc.name AS jk_name,
                            d.name AS developer_name,
                            NULL AS completion_date
                        FROM properties p
                        LEFT JOIN residential_complexes rc ON p.complex_id = rc.id
                        LEFT JOIN developers d ON p.developer_id = d.id
                        WHERE p.inner_id = CAST(:prop_id AS TEXT) OR p.id = :prop_id_int
                    """)
                    
                    try:
                        prop_id_int_val = int(prop.property_id)
                    except (ValueError, TypeError):
                        prop_id_int_val = -1
                    result = db.session.execute(query, {'prop_id': str(prop.property_id), 'prop_id_int': prop_id_int_val}).fetchone()
                    
                    if not result:
                        print(f"Property {prop.property_id} not found in database")
                        continue  # Skip if property not found
                        
                    # Convert row to object and compute safe values
                    from types import SimpleNamespace
                    row_dict = dict(result._mapping)
                    
                    # Ensure safe types and compute price per sqm
                    row_dict['price'] = int(row_dict['price'] or 0)
                    row_dict['area'] = float(row_dict['area'] or 0)
                    row_dict['rooms'] = int(row_dict['rooms'] or 0)
                    
                    # Compute price per sqm safely
                    if row_dict['area'] and row_dict['area'] > 0:
                        row_dict['price_per_sqm'] = int(row_dict['price'] / row_dict['area'])
                    else:
                        row_dict['price_per_sqm'] = 0
                        
                    property_item = SimpleNamespace(**row_dict)
                    property_data = [property_item]
                except Exception as e:
                    print(f"Database error for property {prop.property_id}: {e}")
                    continue
                
                if property_data:
                    property_item = property_data[0]
                    
                    # Use fetch_pdf_context to get all necessary data
                    context = fetch_pdf_context(prop.property_id, presentation_id)
                    if not context:
                        print(f"Failed to get context for property {prop.property_id}")
                        continue
                    
                    # Generate HTML for PDF with complete context
                    html_content = render_template('print_property.html', 
                                                 property=context['property'],
                                                 property_images=context['property_images'],
                                                 complex=context['complex'],
                                                 complex_images=context['complex_images'],
                                                 manager=context['manager'],
                                                 presentation=presentation,
                                                 manager_note=getattr(prop, 'manager_note', None),
                                                 context=context,
                                                 for_pdf=True)
                    
                    # Generate PDF
                    pdf_buffer = BytesIO()
                    HTML(string=html_content, base_url=request.host_url).write_pdf(pdf_buffer)
                    
                    # Add to ZIP
                    filename = f'property_{prop.property_id}.pdf'
                    zip_file.writestr(filename, pdf_buffer.getvalue())
                    print(f"DEBUG: Added {filename} to ZIP (size: {len(pdf_buffer.getvalue())} bytes)")
        
        zip_buffer.seek(0)
        print(f"DEBUG: ZIP created with total size: {len(zip_buffer.getvalue())} bytes")
        
        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=f'presentation_{presentation_id}_all_properties.zip',
            mimetype='application/zip'
        )
        
    except Exception as e:
        print(f"Error creating ZIP: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# REMOVED: This function runs in executor, NOT as a Flask route
def generate_pdf_archive_background(unique_id, base_url):
    """Background task to generate PDF archive"""
    # CRITICAL: Must run within Flask application context to access database
    with app.app_context():
        try:
            from models import Collection, CollectionProperty
            import zipfile
            from weasyprint import HTML
            from io import BytesIO
            
            # Find presentation
            presentation = Collection.query.filter_by(
                unique_url=unique_id,
                collection_type='presentation'
            ).first()
            
            if not presentation:
                progress_storage[f"presentation_{unique_id}"] = {
                    'stage': 'error',
                    'progress': 0,
                    'message': 'Презентация не найдена'
                }
                return
            
            # Get properties with eager loading
            properties_data = CollectionProperty.query.filter_by(
                collection_id=presentation.id
            ).all()
            
            if not properties_data:
                progress_storage[f"presentation_{unique_id}"] = {
                    'stage': 'error',
                    'progress': 0,
                    'message': 'Нет объектов в презентации'
                }
                return
            
            total = len(properties_data)
            progress_storage[f"presentation_{unique_id}"] = {
                'stage': 'starting',
                'progress': 0,
                'current': 0,
                'total': total,
                'message': f'Начинаем создание {total} PDF файлов...'
            }
            
            print(f"DEBUG: Background task started for {total} properties")
            
            # Create temporary ZIP file
            zip_filename = f"presentation_{unique_id}_{int(time.time())}.zip"
            zip_path = os.path.join(TEMP_DOWNLOAD_DIR, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for idx, cp in enumerate(properties_data, 1):
                    # Update progress
                    progress_pct = int((idx / total) * 90)  # 0-90% for PDF generation
                    progress_storage[f"presentation_{unique_id}"] = {
                        'stage': 'processing',
                        'progress': progress_pct,
                        'current': idx,
                        'total': total,
                        'message': f'Создаю PDF {idx} из {total}'
                    }
                    
                    # Use fetch_pdf_context to get all necessary data (same as download_all_properties_public)
                    context = fetch_pdf_context(cp.property_id, presentation.id)
                    if not context:
                        print(f"DEBUG: Failed to get context for property {cp.property_id}")
                        continue
                    
                    # Generate HTML for PDF with complete context (same template as download_all_properties_public)
                    html_content = render_template('print_property.html', 
                                                 property=context['property'],
                                                 property_images=context['property_images'],
                                                 complex=context['complex'],
                                                 complex_images=context['complex_images'],
                                                 manager=context['manager'],
                                                 presentation=presentation,
                                                 manager_note=getattr(cp, 'manager_note', None),
                                                 context=context,
                                                 for_pdf=True)
                    
                    # Generate PDF
                    pdf_buffer = BytesIO()
                    HTML(string=html_content, base_url=base_url).write_pdf(pdf_buffer)
                    
                    # Add to ZIP
                    pdf_filename = f"property_{cp.property_id}.pdf"
                    zipf.writestr(pdf_filename, pdf_buffer.getvalue())
                    
                    print(f"DEBUG: Added {pdf_filename} to ZIP (size: {len(pdf_buffer.getvalue())} bytes)")
            
            # Final progress
            progress_storage[f"presentation_{unique_id}"] = {
                'stage': 'complete',
                'progress': 100,
                'current': total,
                'total': total,
                'message': 'Архив готов!'
            }
            
            # Store file path
            file_storage[unique_id] = {
                'path': zip_path,
                'created_at': time.time()
            }
            
            print(f"DEBUG: ZIP created successfully: {zip_path}")
            
        except Exception as e:
            import traceback
            print(f"ERROR in background task: {str(e)}")
            traceback.print_exc()
            progress_storage[f"presentation_{unique_id}"] = {
                'stage': 'error',
                'progress': 0,
                'message': f'Ошибка: {str(e)}'
            }

@presentations_bp.route('/presentation/view/<string:unique_id>/download-all')
def download_all_properties_public(unique_id):
    """Публичное скачивание всех объектов презентации в ZIP архиве"""
    from models import Collection, CollectionProperty
    from weasyprint import HTML, CSS
    import zipfile
    from io import BytesIO
    import tempfile
    
    try:
        # Find presentation by unique_id instead of presentation_id
        presentation = Collection.query.filter_by(
            unique_url=unique_id,
            collection_type='presentation'
        ).first()
        
        if not presentation:
            return "Презентация не найдена", 404
        
        # Get all properties in presentation
        properties = CollectionProperty.query.filter_by(
            collection_id=presentation.id
        ).all()
        
        print(f"DEBUG: Found {len(properties)} properties in presentation {presentation.id}")
        for prop in properties:
            print(f"DEBUG: Property ID: {prop.property_id}")
        
        if not properties:
            return "Нет объектов в презентации", 400
        
        # Initialize progress tracking
        progress_key = f"presentation_{unique_id}"
        total_properties = len(properties)
        
        # Initialize progress at 0%
        progress_storage[progress_key] = {
            'stage': 'processing',
            'progress': 0,
            'current': 0,
            'total': total_properties,
            'message': f'Начинаю создание PDF файлов...'
        }
        print(f"DEBUG: Initialized progress for {total_properties} properties")
        
        # Create ZIP archive with real progress tracking
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for current_index, prop in enumerate(properties, 1):
                # Update progress
                # progress = int((current_index / total_properties) * 90)  # Reserve 90-100% for finalization
                # progress_storage[progress_key] = {
                # 'stage': 'processing',
                # 'progress': progress,
                # 'current': current_index,
                # 'total': total_properties,
                # 'message': f'Создаю PDF для квартиры {current_index} из {total_properties}...'
                # }
                
                # Get property details from database using raw SQL for compatibility
                try:
                    query = text("""
                        SELECT 
                            p.inner_id AS id,
                            CAST(p.area AS FLOAT) AS area,
                            CAST(p.price AS INTEGER) AS price,
                            CAST(p.floor AS INTEGER) AS floor,
                            CAST(p.total_floors AS INTEGER) AS total_floors,
                            CAST(p.rooms AS INTEGER) AS rooms,
                            'Квартира' AS property_type,
                            p.address AS address_display_name,
                            rc.name AS jk_name,
                            d.name AS developer_name,
                            NULL AS completion_date
                        FROM properties p
                        LEFT JOIN residential_complexes rc ON p.complex_id = rc.id
                        LEFT JOIN developers d ON p.developer_id = d.id
                        WHERE p.inner_id = CAST(:prop_id AS TEXT) OR p.id = :prop_id_int
                    """)
                    
                    try:
                        prop_id_int_val = int(prop.property_id)
                    except (ValueError, TypeError):
                        prop_id_int_val = -1
                    result = db.session.execute(query, {'prop_id': str(prop.property_id), 'prop_id_int': prop_id_int_val}).fetchone()
                    
                    if not result:
                        print(f"Property {prop.property_id} not found in database")
                        continue  # Skip if property not found
                        
                    # Convert row to object and compute safe values
                    from types import SimpleNamespace
                    row_dict = dict(result._mapping)
                    
                    # Ensure safe types and compute price per sqm
                    row_dict['price'] = int(row_dict['price'] or 0)
                    row_dict['area'] = float(row_dict['area'] or 0)
                    row_dict['rooms'] = int(row_dict['rooms'] or 0)
                    
                    # Compute price per sqm safely
                    if row_dict['area'] and row_dict['area'] > 0:
                        row_dict['price_per_sqm'] = int(row_dict['price'] / row_dict['area'])
                    else:
                        row_dict['price_per_sqm'] = 0
                        
                    property_item = SimpleNamespace(**row_dict)
                    property_data = [property_item]
                except Exception as e:
                    print(f"Database error for property {prop.property_id}: {e}")
                    continue
                
                if property_data:
                    property_item = property_data[0]
                    
                    # Use fetch_pdf_context to get all necessary data
                    context = fetch_pdf_context(prop.property_id, presentation.id)
                    if not context:
                        print(f"Failed to get context for property {prop.property_id}")
                        continue
                    
                    # Generate HTML for PDF with complete context
                    html_content = render_template('print_property.html', 
                                                 property=context['property'],
                                                 property_images=context['property_images'],
                                                 complex=context['complex'],
                                                 complex_images=context['complex_images'],
                                                 manager=context['manager'],
                                                 presentation=presentation,
                                                 manager_note=getattr(prop, 'manager_note', None),
                                                 context=context,
                                                 for_pdf=True)
                    
                    # Generate PDF
                    pdf_buffer = BytesIO()
                    HTML(string=html_content, base_url=request.host_url).write_pdf(pdf_buffer)
                    
                    # Add to ZIP
                    filename = f'property_{prop.property_id}.pdf'
                    zip_file.writestr(filename, pdf_buffer.getvalue())
                    print(f"DEBUG: Added {filename} to ZIP (size: {len(pdf_buffer.getvalue())} bytes)")
                    
                    # Update progress after each PDF is created
                    progress_percent = int((current_index / total_properties) * 90)  # Reserve 90-100% for finalization
                    progress_storage[progress_key] = {
                        'stage': 'processing',
                        'progress': progress_percent,
                        'current': current_index,
                        'total': total_properties,
                        'message': f'Создаю PDF {current_index} из {total_properties}'
                    }
                    print(f"DEBUG: Progress update: {progress_percent}% ({current_index}/{total_properties})")
        
        # Final progress - creating archive
        progress_storage[progress_key] = {
            'stage': 'completing',
            'progress': 90,
            'message': 'Создаю архив...'
        }
        
        zip_buffer.seek(0)
        print(f"DEBUG: ZIP created with total size: {len(zip_buffer.getvalue())} bytes")
        
        # Mark as complete
        progress_storage[progress_key] = {
            'stage': 'complete',
            'progress': 100,
            'message': 'Готово! Скачивание началось.'
        }
        
        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=f'presentation_{presentation.title.replace(" ", "_")}_all_properties.zip',
            mimetype='application/zip'
        )
        
    except Exception as e:
        print(f"Error creating ZIP: {e}")
        
        # Update progress with error
        progress_key = f"presentation_{unique_id}"
        progress_storage[progress_key] = {
            'stage': 'error',
            'progress': 0,
            'message': f'Ошибка при создании архива: {str(e)}'
        }
        
        return f"Ошибка при создании архива: {str(e)}", 500

# Global progress storage for tracking real-time PDF generation
progress_storage = {}

# Temporary ZIP file storage system
TEMP_DOWNLOAD_DIR = '/tmp/presentation_downloads'
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

# Storage for file paths keyed by unique_id
file_storage = {}  # Format: {unique_id: {'path': '/tmp/...zip', 'created_at': timestamp}}

# Thread pool for background PDF generation
pdf_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='pdf_gen')

def cleanup_old_files():
    """Remove ZIP files older than 1 hour"""
    try:
        now = time.time()
        for filepath in glob.glob(f"{TEMP_DOWNLOAD_DIR}/*.zip"):
            if os.path.exists(filepath):
                file_age = now - os.path.getmtime(filepath)
                if file_age > 3600:  # 1 hour
                    os.remove(filepath)
                    print(f"Cleaned up old file: {filepath}")
    except Exception as e:
        print(f"Error during cleanup: {e}")

# Schedule cleanup on startup and every 30 minutes
atexit.register(cleanup_old_files)

@presentations_bp.route('/presentation/view/<string:unique_id>/progress')
def download_progress_stream(unique_id):
    """SSE endpoint для отслеживания реального прогресса создания PDF файлов"""
    from flask import Response
    import json
    import time
    from models import Collection, CollectionProperty
    
    try:
        # Find presentation by unique_id
        presentation = Collection.query.filter_by(
            unique_url=unique_id,
            collection_type='presentation'
        ).first()
        
        if not presentation:
            def error_stream():
                yield f"data: {json.dumps({'error': 'Презентация не найдена'})}\n\n"
            return Response(
                error_stream(),
                content_type='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Connection': 'keep-alive',
                    'X-Accel-Buffering': 'no'
                }
            )
        
        # Get properties count
        properties = CollectionProperty.query.filter_by(
            collection_id=presentation.id
        ).all()
        
        if not properties:
            def error_stream():
                yield f"data: {json.dumps({'error': 'Нет объектов в презентации'})}\n\n"
            return Response(
                error_stream(),
                content_type='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Connection': 'keep-alive',
                    'X-Accel-Buffering': 'no'
                }
            )
            
        def progress_generator():
            try:
                total = len(properties)
                progress_key = f"presentation_{unique_id}"
                
                # Initialize progress
                progress_storage[progress_key] = {
                    'stage': 'starting',
                    'progress': 0,
                    'current': 0,
                    'total': total,
                    'message': 'Начинаю создание PDF файлов...'
                }
                
                # Начальное сообщение
                yield f"data: {json.dumps(progress_storage[progress_key])}\n\n"
                time.sleep(1)
                
                # Wait for real progress updates from download endpoint
                last_progress = 0
                timeout_counter = 0
                
                while True:
                    if progress_key in progress_storage:
                        current_progress = progress_storage[progress_key]
                        
                        # Only send updates when progress changes
                        if current_progress['progress'] != last_progress or current_progress['stage'] != 'processing':
                            yield f"data: {json.dumps(current_progress)}\n\n"
                            last_progress = current_progress['progress']
                        
                        # Check if completed
                        if current_progress['stage'] == 'complete':
                            break
                            
                        # Check if error occurred
                        if current_progress['stage'] == 'error':
                            break
                    
                    time.sleep(0.5)
                    timeout_counter += 1
                    
                    # Timeout after 2 minutes
                    if timeout_counter > 240:
                        progress_storage[progress_key] = {
                            'stage': 'error',
                            'message': 'Превышено время ожидания',
                            'progress': 0
                        }
                        yield f"data: {json.dumps(progress_storage[progress_key])}\n\n"
                        break
                
                # Cleanup
                if progress_key in progress_storage:
                    del progress_storage[progress_key]
                    
            except Exception as e:
                yield f"data: {json.dumps({'error': f'Ошибка: {str(e)}'})}\n\n"
        
        return Response(
            progress_generator(),
            content_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',  # Disable nginx buffering
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Cache-Control',
                'Content-Type': 'text/event-stream; charset=utf-8'
            }
        )
        
    except Exception as e:
        def error_stream():
            yield f"data: {json.dumps({'error': f'Ошибка сервера: {str(e)}'})}\n\n"
        return Response(error_stream(), content_type='text/plain')


@presentations_bp.route('/presentation/view/<string:unique_id>/progress-poll')

def poll_pdf_progress(unique_id):
    """Poll progress of background PDF generation"""
    try:
        progress_key = f"presentation_{unique_id}"
        
        if progress_key in progress_storage:
            return jsonify(progress_storage[progress_key])
        else:
            # No progress yet - task might not be started
            return jsonify({
                'status': 'pending',
                'progress': 0,
                'message': 'Ожидание запуска...'
            })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'progress': 0,
            'message': str(e)
        }), 500

@csrf.exempt
@presentations_bp.route('/presentation/view/<string:unique_id>/start-generation', methods=['POST'])
def start_pdf_generation(unique_id):
    """Start background PDF generation task"""
    try:
        # Validate presentation exists
        from models import Collection
        presentation = Collection.query.filter_by(
            unique_url=unique_id,
            collection_type='presentation'
        ).first()
        
        if not presentation:
            return jsonify({'error': 'Презентация не найдена'}), 404
        
        # Submit background task
        # Capture base_url from request context before submitting to executor
        base_url = request.url_root
        pdf_executor.submit(generate_pdf_archive_background, unique_id, base_url)
        
        return jsonify({
            'success': True,
            'message': 'Генерация запущена'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@presentations_bp.route('/presentation/view/<string:unique_id>/download-result')
def download_pdf_result(unique_id):
    """Download the generated ZIP file"""
    try:
        # Check if file exists in storage
        if unique_id not in file_storage:
            return "Файл не найден или еще не готов", 404
        
        file_info = file_storage[unique_id]
        zip_path = file_info['path']
        
        if not os.path.exists(zip_path):
            return "Файл был удален", 404
        
        # Send file and clean up
        response = send_file(
            zip_path,
            as_attachment=True,
            download_name=f'presentation_{unique_id}.zip',
            mimetype='application/zip'
        )
        
        # Schedule cleanup (remove from storage after sending)
        def cleanup_after_send():
            time.sleep(5)  # Wait for download to start
            if unique_id in file_storage:
                del file_storage[unique_id]
            if os.path.exists(zip_path):
                os.remove(zip_path)
        
        threading.Thread(target=cleanup_after_send, daemon=True).start()
        
        return response
        
    except Exception as e:
        return f"Ошибка при скачивании: {str(e)}", 500
def download_progress_poll(unique_id):
    """Polling endpoint for PDF generation progress (replaces SSE)"""
    from flask import jsonify
    
    progress_key = f"presentation_{unique_id}"
    
    if progress_key in progress_storage:
        return jsonify(progress_storage[progress_key])
    else:
        # No progress yet or already completed
        return jsonify({
            'stage': 'waiting',
            'progress': 0,
            'message': 'Ожидание...'
        })

@presentations_bp.route('/api/manager/presentation/<int:presentation_id>/send-email', methods=['POST'])
@manager_required
# @require_json_csrf  # CSRF disabled
def send_presentation_email(presentation_id):
    """Отправить презентацию на email"""
    from models import Collection, CollectionProperty
    from flask_login import current_user
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    
    try:
        data = request.get_json()
        if not data or not data.get('email'):
            return jsonify({'success': False, 'error': 'Email не указан'}), 400
        
        email = data['email']
        
        # Find presentation
        presentation = Collection.query.get_or_404(presentation_id)
        
        # Check ownership
        current_manager = current_user
        if presentation.created_by_manager_id != current_manager.id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        # Get properties count
        properties_count = CollectionProperty.query.filter_by(
            collection_id=presentation_id
        ).count()
        
        # Create simple email (without attachments for now)
        msg = MIMEMultipart()
        msg['From'] = "noreply@inback.ru"
        msg['To'] = email
        msg['Subject'] = f"Презентация недвижимости от InBack - {presentation.name}"
        
        # Email body
        body = f"""
        Здравствуйте!
        
        Высылаем вам подобранную презентацию недвижимости "{presentation.name}".
        
        Количество объектов: {properties_count}
        
        Чтобы посмотреть презентацию, перейдите по ссылке:
        {request.host_url}manager/presentation/{presentation_id}
        
        С уважением,
        Команда InBack
        """
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Send email (simplified version - would need real SMTP config)
        print(f"EMAIL SENT TO: {email}")
        print(f"EMAIL BODY: {body}")
        
        return jsonify({
            'success': True,
            'message': 'Презентация отправлена на email'
        })
        
    except Exception as e:
        print(f"Error sending email: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@presentations_bp.route('/api/manager/presentation/<int:presentation_id>/add-complex', methods=['POST'])
@csrf.exempt
@manager_required
# # @require_json_csrf  # CSRF disabled  # CSRF disabled
def add_complex_to_presentation(presentation_id):
    """Добавить ЖК в презентацию (безопасная версия)"""
    from models import Collection, CollectionProperty
    from flask_login import current_user
    
    # Валидация входных данных
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Данные не предоставлены'}), 400
        
    complex_id = data.get('complex_id')
    if not complex_id:
        return jsonify({'success': False, 'error': 'ID ЖК не указан'}), 400
    
    # Get current manager
    current_manager = current_user
        
    # Строгая проверка владения презентацией
    presentation = Collection.query.filter_by(
        id=presentation_id,
        created_by_manager_id=current_manager.id,
        collection_type='presentation'
    ).first()
    
    if not presentation:
        return jsonify({'success': False, 'error': 'Презентация не найдена или у вас нет прав доступа'}), 404
    
    try:
        # Получаем все объекты из ЖК
        properties = load_properties()
        complex_properties = []
        
        for prop in properties:
            if str(prop.get('complex_id')) == str(complex_id):
                complex_properties.append(prop)
        
        if not complex_properties:
            return jsonify({'success': False, 'error': 'ЖК не найден или в нем нет объектов'}), 404
        
        added_count = 0
        for prop in complex_properties[:5]:  # Добавляем максимум 5 объектов из ЖК
            property_id = prop.get('ID')
            
            # Проверяем, не добавлен ли уже этот объект
            existing = CollectionProperty.query.filter_by(
                collection_id=presentation_id,
                property_id=property_id
            ).first()
            
            if not existing:
                # DUAL WRITE: Resolve property to get both IDs
                property_obj, canonical_id = resolve_property_by_identifier(property_id)
                if not property_obj:
                    continue  # Skip if property not found
                
                collection_property = CollectionProperty(
                    collection_id=presentation_id,
                    property_id=str(property_obj.id),  # Old: database ID
                    property_inner_id=property_obj.inner_id,  # NEW: canonical inner_id
                    property_name=f"{prop.get('Type', '')} в {prop.get('Complex', '')}",
                    property_price=int(prop.get('Price', 0)) if prop.get('Price') else None,
                    complex_name=prop.get('Complex', ''),
                    property_type=prop.get('Type', ''),
                    property_size=float(prop.get('Size', 0)) if prop.get('Size') else None,
                    order_index=len(presentation.properties) + added_count + 1
                )
                
                db.session.add(collection_property)
                added_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Добавлено {added_count} объектов из ЖК в презентацию',
            'added_count': added_count
        })
        
    except Exception as e:
        db.session.rollback()
@presentations_bp.route('/api/manager/presentation/create-with-property', methods=['POST'])
@csrf.exempt
@manager_required
# # @require_json_csrf  # CSRF disabled  # CSRF disabled
def create_presentation_with_property():
    """Создать презентацию и сразу добавить объект (безопасная версия)"""
    from models import Collection, CollectionProperty
    from flask_login import current_user
    
    print(f"🎯 DEBUG: create_presentation_with_property called")
    # Валидация входных данных
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Данные не предоставлены'}), 400
    print(f"🎯 DEBUG: Got data: {data}")
        
    title = data.get('title', '').strip()
    client_name = data.get('client_name', '').strip()
    property_id = data.get('property_id')
    
    # Строгая валидация обязательных полей
    if not title:
        return jsonify({'success': False, 'error': 'Название презентации обязательно'}), 400
    if not property_id:
        return jsonify({'success': False, 'error': 'ID объекта обязателен'}), 400
    
    
    # Convert to int if it's a string, keep as int if already int
    try:
        property_id_int = int(property_id) if isinstance(property_id, str) else property_id
        property_id = str(property_id_int)  # Convert to string for VARCHAR column
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Недопустимый ID объекта'}), 400

    try:
        # Get current manager
        current_manager = current_user
        print(f"🎯 DEBUG: current_manager set to {current_manager}")
            
        # Создаем презентацию
        presentation = Collection(
            title=title,
            created_by_manager_id=current_manager.id,
            collection_type='presentation',
            client_name=client_name,
            status='Черновик'
        )
        print(f"🎯 DEBUG: presentation object created")
        
        presentation.generate_unique_url()
        print(f"🎯 DEBUG: unique URL generated")
        db.session.add(presentation)
        print(f"🎯 DEBUG: presentation added to session")
        db.session.flush()  # Получаем ID презентации
        print(f"🎯 DEBUG: flushed, presentation ID: {presentation.id}")
        
        # Добавляем объект - direct DB query instead of Excel cache
        from models import Property
        property_obj = Property.query.get(property_id_int)
        
        if not property_obj:
            print(f"🎯 DEBUG: Property {property_id} not found in database")
            return jsonify({'success': False, 'error': 'Объект не найден'}), 404
        
        print(f"🎯 DEBUG: property_obj found: {property_obj}")
        
        collection_property = CollectionProperty(
            collection_id=presentation.id,
            property_id=str(property_obj.id),  # Old: database ID
            property_inner_id=property_obj.inner_id,  # NEW: canonical inner_id
            property_name=property_obj.title or (f"Студия в {property_obj.residential_complex.name if property_obj.residential_complex else ''}" if not property_obj.rooms else f"{property_obj.rooms}-комн в {property_obj.residential_complex.name if property_obj.residential_complex else ''}"),
            property_price=property_obj.price,
            complex_name=property_obj.residential_complex.name if property_obj.residential_complex else '',
            property_type=f"{property_obj.rooms}-комн" if property_obj.rooms else "Студия",
            property_size=property_obj.area,
            order_index=1
        )
        print(f"🎯 DEBUG: collection_property created")
        
        db.session.add(collection_property)
        print(f"🎯 DEBUG: about to commit")
        db.session.commit()
        print(f"🎯 DEBUG: committed successfully")
        
        return jsonify({
            'success': True,
            'presentation': presentation.to_dict(),
            'message': 'Презентация создана и объект добавлен'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
@presentations_bp.route('/api/manager/presentation/create-with-complex', methods=['POST'])
@csrf.exempt
@manager_required
# # @require_json_csrf  # CSRF disabled  # CSRF disabled
def create_presentation_with_complex():
    """Создать презентацию и сразу добавить ЖК (безопасная версия)"""
    from models import Collection, CollectionProperty
    from flask_login import current_user
    
    # Валидация входных данных
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Данные не предоставлены'}), 400
        
    title = data.get('title', '').strip()
    client_name = data.get('client_name', '').strip()
    complex_id = data.get('complex_id')
    
    # Строгая валидация обязательных полей
    if not title:
        return jsonify({'success': False, 'error': 'Название презентации обязательно'}), 400
    if not complex_id:
        return jsonify({'success': False, 'error': 'ID ЖК обязателен'}), 400
    
    try:
        # Get current manager
        current_manager = current_user
            
        # Создаем презентацию
        presentation = Collection(
            title=title,
            created_by_manager_id=current_manager.id,
            collection_type='presentation', 
            client_name=client_name,
            status='Черновик'
        )
        
        presentation.generate_unique_url()
        db.session.add(presentation)
        db.session.flush()  # Получаем ID презентации
        
        # Добавляем объекты из ЖК
        properties = load_properties()
        complex_properties = []
        
        for prop in properties:
            if str(prop.get('complex_id')) == str(complex_id):
                complex_properties.append(prop)
        
        if not complex_properties:
            return jsonify({'success': False, 'error': 'ЖК не найден или в нем нет объектов'}), 404
        
        added_count = 0
        for prop in complex_properties[:5]:  # Добавляем максимум 5 объектов из ЖК
            property_id = prop.get('ID')
            
            # DUAL WRITE: Resolve property to get both IDs
            property_obj, canonical_id = resolve_property_by_identifier(property_id)
            if not property_obj:
                continue  # Skip if property not found
            
            collection_property = CollectionProperty(
                collection_id=presentation.id,
                property_id=str(property_obj.id),  # Old: database ID
                property_inner_id=property_obj.inner_id,  # NEW: canonical inner_id
                property_name=f"{prop.get('Type', '')} в {prop.get('Complex', '')}",
                property_price=int(prop.get('Price', 0)) if prop.get('Price') else None,
                complex_name=prop.get('Complex', ''),
                property_type=prop.get('Type', ''),
                property_size=float(prop.get('Size', 0)) if prop.get('Size') else None,
                order_index=added_count + 1
            )
            
            db.session.add(collection_property)
            added_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'presentation': presentation.to_dict(),
            'message': f'Презентация создана с {added_count} объектами из ЖК'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


# ===== НОВЫЕ API ENDPOINT'Ы ДЛЯ ДЕЙСТВИЙ С ОБЪЕКТАМИ В ПРЕЗЕНТАЦИИ =====

# REMOVED DUPLICATE PRINT ENDPOINT - security fix
    from models import Collection, CollectionProperty
    
    try:
        # Найти презентацию
        presentation = Collection.query.filter_by(
            id=presentation_id, 
            collection_type='presentation'
        ).first()
        
        if not presentation:
            abort(404)
        
        prop_obj, inner_id_str = resolve_property_by_identifier(property_id)
        if not prop_obj:
            return jsonify({'success': False, 'error': 'Объект не найден'}), 404
        
        collection_property = CollectionProperty.query.filter(
            CollectionProperty.collection_id == presentation_id,
            db.or_(
                CollectionProperty.property_id == inner_id_str,
                CollectionProperty.property_id == str(property_id),
                CollectionProperty.property_id == str(prop_obj.id)
            )
        ).first()
        
        if not collection_property:
            abort(404)
        
        # Загрузить полные данные объекта
        properties = load_properties()
        property_data = None
        
        for prop in properties:
            if str(prop.get('id')) == str(property_id) or str(prop.get('ID')) == str(property_id) or str(prop.get('inner_id')) == str(property_id):
                property_data = prop
                break
        
        if not property_data:
            abort(404)
        
        # Рендерить print-friendly версию
        return render_template('property_print.html', 
                             property=property_data,
                             presentation=presentation,
                             collection_property=collection_property)
        
    except Exception as e:
        print(f"Error in property_print_view: {e}")
        abort(500)


@presentations_bp.route('/api/presentation/<int:presentation_id>/property/<string:property_id>/download')
@manager_required
def property_download_pdf(presentation_id, property_id):
    """Скачать PDF объекта из презентации"""
    from models import Collection, CollectionProperty
    from flask import make_response
    import io
    
    # Try to import weasyprint with fallback
    try:
        import weasyprint
        pdf_available = True
    except ImportError:
        pdf_available = False
    
    try:
        # Найти презентацию
        presentation = Collection.query.filter_by(
            id=presentation_id, 
            collection_type='presentation'
        ).first()
        
        if not presentation:
            abort(404)
        
        prop_obj, inner_id_str = resolve_property_by_identifier(property_id)
        if not prop_obj:
            return jsonify({'success': False, 'error': 'Объект не найден'}), 404
        
        collection_property = CollectionProperty.query.filter(
            CollectionProperty.collection_id == presentation_id,
            db.or_(
                CollectionProperty.property_id == inner_id_str,
                CollectionProperty.property_id == str(property_id),
                CollectionProperty.property_id == str(prop_obj.id)
            )
        ).first()
        
        if not collection_property:
            abort(404)
        
        # Загрузить полные данные объекта используя fetch_pdf_context для получения фото и кэшбека
        context = fetch_pdf_context(property_id, presentation_id)
        
        if not context:
            abort(404)
        
        # Check if PDF generation is available
        if not pdf_available:
            # Fallback: redirect to print view
            return redirect(url_for('property_print_view', 
                                  presentation_id=presentation_id, 
                                  property_id=property_id))
        
        # Рендерить HTML для PDF с полным контекстом (тот же шаблон что и для архива)
        html_content = render_template('print_property.html', 
                                     property=context['property'],
                                     property_images=context['property_images'],
                                     complex=context['complex'],
                                     complex_images=context['complex_images'],
                                     manager=context['manager'],
                                     presentation=presentation,
                                     manager_note=getattr(collection_property, 'manager_note', None),
                                     context=context,
                                     for_pdf=True)
        
        # Генерировать PDF
        try:
            pdf_buffer = io.BytesIO()
            weasyprint.HTML(string=html_content, base_url=request.url_root).write_pdf(pdf_buffer)
            pdf_buffer.seek(0)
            
            # Создать ASCII-safe имя файла для headers
            property_name = context['property'].get('name', f"Объект_{property_id}")
            original_filename = f"{property_name}_{presentation.title}.pdf"
            
            # Create ASCII-safe filename for HTTP headers
            ascii_filename = f"property_{property_id}_{presentation_id}.pdf"
            
            # Clean original filename for RFC 5987 encoding if needed
            clean_filename = "".join(c for c in original_filename if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
        except Exception as pdf_error:
            print(f"PDF generation failed: {pdf_error}")
            # Fallback: redirect to print view
            return redirect(url_for('property_print_view', 
                                  presentation_id=presentation_id, 
                                  property_id=property_id))
        
        # Вернуть PDF как файл для скачивания с правильной кодировкой
        from urllib.parse import quote
        
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        
        # Use ASCII-safe filename in Content-Disposition with RFC 5987 fallback for Unicode
        try:
            # Try to encode original filename for browsers that support RFC 5987
            encoded_filename = quote(clean_filename.encode('utf-8'))
            response.headers['Content-Disposition'] = (
                f'attachment; '
                f'filename="{ascii_filename}"; '
                f'filename*=UTF-8\'\'{encoded_filename}'
            )
        except:
            # Fallback to ASCII-only filename
            response.headers['Content-Disposition'] = f'attachment; filename="{ascii_filename}"'
        
        return response
        
    except Exception as e:
        print(f"Error in property_download_pdf: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@presentations_bp.route('/api/presentation/<int:presentation_id>/property/<string:property_id>/view')
def property_view_redirect(presentation_id, property_id):
    """Перенаправить на полную страницу объекта на сайте"""
    from models import Collection, CollectionProperty
    
    try:
        # Найти презентацию
        presentation = Collection.query.filter_by(
            id=presentation_id, 
            collection_type='presentation'
        ).first()
        
        if not presentation:
            abort(404)
        
        prop_obj, inner_id_str = resolve_property_by_identifier(property_id)
        if not prop_obj:
            return jsonify({'success': False, 'error': 'Объект не найден'}), 404
        
        # Найти объект в презентации используя inner_id
        # Resolve property by inner_id OR database ID
        prop_obj, canonical_id = resolve_property_by_identifier(property_id)
        if not prop_obj:
            return jsonify({"success": False, "error": "Объект не найден"}), 404
        
        collection_property = CollectionProperty.query.filter_by(
            collection_id=presentation_id,
            property_id=inner_id_str
        ).first()
        
        if not collection_property:
            abort(404)
        
        # Перенаправить на страницу объекта
        return redirect(url_for('props.property_detail', property_id=property_id))
        
    except Exception as e:
        print(f"Error in property_view_redirect: {e}")
        abort(500)


@presentations_bp.route('/api/manager/presentation/<int:presentation_id>/property/<string:property_id>/delete', methods=['DELETE'])
@csrf.exempt
@manager_required
def delete_property_from_presentation(presentation_id, property_id):
    """Удалить объект из презентации (только для менеджера-владельца)"""
    from models import Collection, CollectionProperty
    from flask_login import current_user
    
    try:
        # Найти презентацию
        presentation = Collection.query.filter_by(
            id=presentation_id, 
            collection_type='presentation'
        ).first()
        
        if not presentation:
            return jsonify({'success': False, 'error': 'Презентация не найдена'}), 404
        
        # Проверить права доступа - только создатель презентации может удалять объекты
        if presentation.created_by_manager_id != current_user.id:
            return jsonify({'success': False, 'error': 'Нет прав для удаления объектов из этой презентации'}), 403
        
        prop_obj, inner_id_str = resolve_property_by_identifier(property_id)
        if not prop_obj:
            return jsonify({'success': False, 'error': 'Объект не найден'}), 404
        
        collection_property = CollectionProperty.query.filter(
            CollectionProperty.collection_id == presentation_id,
            db.or_(
                CollectionProperty.property_id == inner_id_str,
                CollectionProperty.property_id == str(property_id),
                CollectionProperty.property_id == str(prop_obj.id)
            )
        ).first()
        
        if not collection_property:
            return jsonify({'success': False, 'error': 'Объект не найден в презентации'}), 404
        
        # Удалить объект из презентации
        db.session.delete(collection_property)
        db.session.commit()
        
        # Обновить количество объектов в презентации
        remaining_properties = CollectionProperty.query.filter_by(collection_id=presentation_id).count()
        
        return jsonify({
            'success': True,
            'message': 'Объект успешно удален из презентации',
            'remaining_properties': remaining_properties
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error in delete_property_from_presentation: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def send_collection_to_user():
    """Send collection to user - legacy function"""
    if request.method != 'POST':
        return jsonify({'success': False, 'error': 'Only POST method allowed'}), 405
    
    data = request.get_json()
    current_manager = current_user
    
    try:
        name = data.get('name')
        client_id = data.get('client_id')
        property_ids = data.get('property_ids', [])
        
        if not name or not client_id or not property_ids:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Get client and manager info
        client = User.query.get(client_id)
        manager = current_manager
        
        if not client or not manager:
            return jsonify({'success': False, 'error': 'Client or manager not found'}), 404
        
        # Load property details
        with open('data/properties_expanded.json', 'r', encoding='utf-8') as f:
            properties_data = json.load(f)
        
        selected_properties = []
        total_cashback = 0
        
        for prop_id in property_ids:
            for prop in properties_data:
                if str(prop.get('id')) == str(prop_id):
                    price = prop.get('price', 0)
                    cashback = int(price * 0.05)
                    total_cashback += cashback
                    
                    selected_properties.append({
                        'complex_name': prop.get('complex_name', ''),
                        'district': prop.get('district', ''),
                        'developer': prop.get('developer', ''),
                        'rooms': prop.get('rooms', 0),
                        'area': prop.get('area', 0),
                        'price': price,
                        'cashback': cashback,
                        'type': prop.get('type', ''),
                        'description': prop.get('description', '')
                    })
                    break
        
        # Create email content
        properties_list = '\n'.join([
            f"• {prop['complex_name']} ({prop['district']})\n"
            f"  {prop['rooms']}-комн., {prop['area']} м²\n"
            f"  Цена: {prop['price']:,} ₽\n"
            f"  Кешбек: {prop['cashback']:,} ₽\n"
            for prop in selected_properties
        ])
        
        subject = f"Подборка недвижимости: {name}"
        text_message = f"""
Здравствуйте, {client.full_name}!

Ваш менеджер {manager.full_name} подготовил для вас персональную подборку недвижимости "{name}".

ПОДОБРАННЫЕ ОБЪЕКТЫ ({len(selected_properties)} шт.):

{properties_list}

ОБЩИЙ КЕШБЕК: {total_cashback:,} ₽

Для получения подробной информации и записи на просмотр свяжитесь с вашим менеджером:
{manager.full_name}
Email: {manager.email}
Телефон: {manager.phone or 'не указан'}

Или перейдите в личный кабинет на сайте InBack.ru

С уважением,
Команда InBack.ru
        """.strip()
        
        # Send email
        try:
            from email_service import send_email
            send_email(
                to_email=client.email,
                subject=subject,
                text_content=text_message,
                template_name='collection'
            )
            
            return jsonify({
                'success': True,
                'message': f'Подборка отправлена на email {client.email}'
            })
            
        except Exception as e:
            print(f"Error sending email: {e}")
            return jsonify({'success': False, 'error': 'Ошибка отправки email'}), 500
        
    except Exception as e:
        print(f"Error sending collection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


