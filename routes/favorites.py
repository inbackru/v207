"""
routes/favorites.py — User and manager favorites / collections / presentations (extracted from app.py)
"""
from flask import (Blueprint, abort, jsonify, redirect, render_template,
                   request, session, url_for, current_app)
from flask_login import current_user, login_required
from app import db, csrf, require_json_csrf, manager_required, admin_required
from repositories.property_repository import PropertyRepository

bp = Blueprint('favorites', __name__)


@bp.route('/api/favorites', methods=['POST'])
@login_required  
# @csrf.exempt  # CSRF disabled  # Disable CSRF for API endpoint
def add_to_favorites():
    """Add property to favorites"""
    from models import FavoriteProperty
    data = request.get_json()
    
    # Check if already in favorites
    existing = FavoriteProperty.query.filter_by(
        user_id=current_user.id,
        property_name=data['property_name']
    ).first()
    
    if existing:
        return jsonify({'success': False, 'error': 'Уже в избранном'})
    
    try:
        favorite = FavoriteProperty(
            user_id=current_user.id,
            property_name=data['property_name'],
            property_type=data['property_type'],
            property_size=float(data['property_size']),
            property_price=int(data['property_price']),
            complex_name=data['complex_name'],
            developer_name=data['developer_name'],
            property_image=data.get('property_image'),
            cashback_amount=int(data.get('cashback_amount', 0)),
            cashback_percent=float(data.get('cashback_percent', 0))
        )
        db.session.add(favorite)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/favorites/<property_id>', methods=['DELETE'])
@login_required
@csrf.exempt  # ✅ FIXED: CSRF protection removed for delete action as requested
def remove_from_favorites(property_id):
    """Remove property from favorites"""
    from models import FavoriteProperty
    
    favorite = FavoriteProperty.query.filter_by(
        user_id=current_user.id,
        property_id=property_id
    ).first()
    
    if favorite:
        try:
            db.session.delete(favorite)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400
    else:
        return jsonify({'success': False, 'error': 'Favorite not found'}), 404

def send_view_notification_to_manager(presentation, view):
    """Отправляет уведомление менеджеру о новом просмотре презентации"""
    try:
        manager = presentation.created_by
        if not manager:
            print(f"Manager not found for presentation {presentation.id}")
            return
            
        # Получаем информацию о просмотре
        client_info = "Неизвестный клиент"
        if presentation.client_name:
            client_info = presentation.client_name
        elif presentation.client_phone:
            client_info = presentation.client_phone
            
        # Формируем сообщение уведомления
        notification_text = f"""📊 Новый просмотр презентации!

📋 "{presentation.title}"
👤 Клиент: {client_info}
🔢 Всего просмотров: {presentation.view_count}
⏰ Время просмотра: {view.viewed_at.strftime('%d.%m.%Y %H:%M')}
🌐 IP: {view.view_ip}
📱 Устройство: {view.user_agent[:50] + '...' if view.user_agent and len(view.user_agent) > 50 else view.user_agent or 'Неизвестно'}

👀 Ссылка на презентацию: {request.url_root}presentation/modern/{presentation.unique_url}
🎯 Панель менеджера: {request.url_root}manager/dashboard"""

        # TODO: Интеграция с Telegram Bot API
        # if hasattr(manager, 'telegram_chat_id') and manager.telegram_chat_id:
        #     send_telegram_notification(manager.telegram_chat_id, notification_text)
        
        # TODO: Интеграция с Email
        # if manager.email:
        #     send_email_notification(manager.email, f"Новый просмотр: {presentation.title}", notification_text)
        
        # Пока просто логируем уведомление
        print(f"📧 NOTIFICATION TO MANAGER {manager.email}:")
        print(notification_text)
        print("-" * 50)
        
        # Отмечаем что уведомление отправлено
        view.notification_sent = True
        db.session.commit()
        
    except Exception as e:
        print(f"Error in send_view_notification_to_manager: {e}")

@bp.route('/presentation/<string:unique_url>')
def redirect_old_presentation_url(unique_url):
    """Редирект со старого формата URL на новый для обратной совместимости"""
    return redirect(url_for('view_presentation', unique_id=unique_url), code=301)

@bp.route('/presentation/view/<string:unique_id>')
def view_presentation(unique_id):
    """Публичная страница просмотра презентации по уникальной ссылке"""
    print(f"🔥 ROUTE HIT: /presentation/view/{unique_id}")
    print(f"🔥 CLIENT IP: {request.remote_addr}")
    print(f"🔥 USER AGENT: {request.headers.get('User-Agent', 'Unknown')}")
    from models import Collection, CollectionProperty, PresentationView
    
    # Находим презентацию по уникальной ссылке
    presentation = Collection.query.filter_by(
        unique_url=unique_id,
        collection_type='presentation'
    ).first()
    
    if not presentation:
        return render_template('error.html', 
                             error="Презентация не найдена", 
                             message="Возможно, ссылка устарела или была удалена"), 404
    
    # Записываем просмотр
    try:
        view = PresentationView(
            collection_id=presentation.id,
            view_ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            referer=request.headers.get('Referer')
        )
        db.session.add(view)
        
        # Увеличиваем счетчик просмотров (без автокоммита)
        presentation.increment_view_count()
        db.session.commit()  # Контролируем транзакцию на уровне view
        
        # Отправляем уведомление менеджеру о новом просмотре
        try:
            send_view_notification_to_manager(presentation, view)
        except Exception as e:
            print(f"Error sending view notification: {e}")
        
    except Exception as e:
        db.session.rollback()
        print(f"Error recording presentation view: {e}")
    
    print("DEBUG: Starting data loading phase...")
    
    # ✅ MIGRATED: Load properties using PostgreSQL (same as manager version)
    try:
        print("DEBUG: Loading presentation data from PostgreSQL...")
        enriched_properties = _load_presentation_properties_from_db(presentation.id)
        print(f"DEBUG: Loaded {len(enriched_properties)} enriched properties")
    except Exception as e:
        print(f"ERROR: Failed to load presentation data: {e}")
        import traceback
        traceback.print_exc()
        # Fallback to empty list to allow page rendering
        print("FALLBACK: Using empty data to allow page rendering")
        enriched_properties = []
    
    print(f"DEBUG: About to render template with {len(enriched_properties)} enriched properties")
    print(f"DEBUG: Presentation object: {presentation}")
    print(f"DEBUG: First property sample: {enriched_properties[0] if enriched_properties else 'No properties'}")
    
    # Format presentation data for template (same structure as manager version)
    presentation_data = {
        'id': presentation.id,
        'title': presentation.title,
        'description': presentation.description,
        'client_name': presentation.client_name,
        'client_phone': presentation.client_phone,
        'status': presentation.status,
        'created_at': presentation.created_at,
        'view_count': presentation.view_count,
        'last_viewed_at': presentation.last_viewed_at,
        'properties_count': len(enriched_properties),
        'properties': enriched_properties,
        'unique_url': presentation.unique_url
    }
    
    try:
        print(f"🔥 RENDERING: presentation_view.html with {len(enriched_properties)} properties")
        print(f"🔥 PRESENTATION: {presentation_data['title']}")
        print(f"🔥 VIEW COUNT: {presentation_data['view_count']}")
        
        template_result = render_template('presentation_view.html', 
                                        presentation=presentation_data,
                                        properties=enriched_properties,
                                        manager=presentation.created_by)
        print("🔥 TEMPLATE RENDERED: presentation_view.html success!")
        return template_result
    except Exception as e:
        print(f"ERROR in view_presentation template rendering: {e}")
        import traceback
        traceback.print_exc()
        return f"Template rendering error: {str(e)}", 500

@bp.route('/presentation/modern/<string:unique_id>')
def view_modern_presentation(unique_id):
    """Современная версия публичной страницы просмотра презентации"""
    from models import Collection, CollectionProperty, PresentationView, ManagerNotification
    
    try:
        # Находим презентацию по уникальной ссылке
        presentation = Collection.query.filter_by(
            unique_url=unique_id,
            collection_type='presentation'
        ).first()
        
        if not presentation:
            return render_template('error.html', 
                                 error="Презентация не найдена", 
                                 message="Возможно, ссылка устарела или была удалена"), 404
        
        print(f"DEBUG: view_modern_presentation - Found presentation ID: {presentation.id}")
        
        # Записываем просмотр
        try:
            view = PresentationView(
                collection_id=presentation.id,
                view_ip=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
                referer=request.headers.get('Referer')
            )
            db.session.add(view)
            presentation.increment_view_count()
            
            # Создаем уведомление для менеджера
            manager_id = presentation.created_by_manager_id
            client_name = presentation.client_name or 'Неизвестный клиент'
            presentation_title = presentation.title or 'Презентация'
            view_ip = request.remote_addr or 'Неизвестный IP'
            
            # Формируем текст уведомления
            notification_title = f"Просмотр презентации: {presentation_title}"
            notification_message = f"Клиент {client_name} просмотрел презентацию \"{presentation_title}\". IP адрес: {view_ip}"
            
            # Дополнительная информация в JSON
            extra_data = {
                'client_name': client_name,
                'presentation_title': presentation_title,
                'view_ip': view_ip,
                'user_agent': request.headers.get('User-Agent', ''),
                'referer': request.headers.get('Referer', ''),
                'presentation_url': f"/presentation/modern/{presentation.unique_url}",
                'view_count': presentation.view_count + 1  # +1 так как еще не сохранили
            }
            
            # Создаем уведомление
            notification = ManagerNotification(
                manager_id=manager_id,
                title=notification_title,
                message=notification_message,
                notification_type='presentation_view',
                presentation_id=presentation.id
            )
            notification.set_extra_data(extra_data)
            
            db.session.add(notification)
            db.session.commit()
            
            print(f"✅ Created notification for manager {manager_id}: {notification_title}")
            
        except Exception as e:
            db.session.rollback()
            print(f"Error recording presentation view or creating notification: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"DEBUG: view_modern_presentation - Starting property loading")
        
        # ✅ MIGRATED: Get property data using repository
        enriched_properties = []
        all_complexes = {}  # Словарь для хранения всех уникальных ЖК
        
        for prop in presentation.properties:
            # Load property - try inner_id first, then database ID (same as manager API)
            from models import Property as PropertyModel
            from sqlalchemy.orm import joinedload
            property_obj_orm = PropertyModel.query.options(
                joinedload(PropertyModel.residential_complex),
                joinedload(PropertyModel.developer),
                joinedload(PropertyModel.district)
            ).filter_by(inner_id=prop.property_id).first()
            
            if not property_obj_orm:
                try:
                    property_id_int = int(prop.property_id)
                    property_obj_orm = PropertyModel.query.options(
                        joinedload(PropertyModel.residential_complex),
                        joinedload(PropertyModel.developer),
                        joinedload(PropertyModel.district)
                    ).get(property_id_int)
                except (ValueError, TypeError):
                    pass
            
            if property_obj_orm:
                # Get cashback rate from complex
                cashback_rate = property_obj_orm.residential_complex.cashback_rate if property_obj_orm.residential_complex else 5.0
                
                # Parse photos
                photos = []
                if property_obj_orm.gallery_images:
                    try:
                        import json
                        if isinstance(property_obj_orm.gallery_images, str):
                            if property_obj_orm.gallery_images.startswith('['):
                                photos = json.loads(property_obj_orm.gallery_images)
                            elif property_obj_orm.gallery_images.startswith('http'):
                                photos = [url.strip() for url in property_obj_orm.gallery_images.split(',') if url.strip()]
                        elif isinstance(property_obj_orm.gallery_images, list):
                            photos = property_obj_orm.gallery_images
                    except Exception as e:
                        photos = []
                
                # Format title
                rooms_text = ""
                if property_obj_orm.rooms == 0:
                    rooms_text = "Студия"
                elif property_obj_orm.rooms:
                    rooms_text = f"{property_obj_orm.rooms}-комнатная квартира"
                else:
                    rooms_text = "Квартира"
                
                # Calculate cashback
                cashback_amount = int((property_obj_orm.price or 0) * cashback_rate / 100)
                
                # Format property object for template
                property_obj = {
                    'property_id': property_obj_orm.inner_id,
                    'title': rooms_text,
                    'rooms': property_obj_orm.rooms or 0,
                    'area': property_obj_orm.area or 0,
                    'price': property_obj_orm.price or 0,
                    'floor': property_obj_orm.floor or 1,
                    'total_floors': property_obj_orm.total_floors or property_obj_orm.floor or 1,
                    'address': property_obj_orm.address or '',
                    'images': photos,
                    'complex_name': property_obj_orm.residential_complex.name if property_obj_orm.residential_complex else '',
                    'developer_name': property_obj_orm.developer.name if property_obj_orm.developer else '',
                    'deadline': '',
                    'renovation_type': property_obj_orm.renovation_type or 'Не указано',
                    'housing_class': property_obj_orm.residential_complex.object_class_display_name if property_obj_orm.residential_complex else 'Комфорт',
                    'cashback_percent': cashback_rate,
                    'cashback_amount': cashback_amount,
                    'manager_note': prop.manager_note if hasattr(prop, 'manager_note') else None
                }
                
                # Format deadline
                if property_obj_orm.residential_complex and property_obj_orm.residential_complex.end_build_year and property_obj_orm.residential_complex.end_build_quarter:
                    quarters = ['I', 'II', 'III', 'IV']
                    quarter_text = quarters[property_obj_orm.residential_complex.end_build_quarter - 1] if property_obj_orm.residential_complex.end_build_quarter <= 4 else 'IV'
                    property_obj['deadline'] = f"{quarter_text} кв. {property_obj_orm.residential_complex.end_build_year} г."
                
                enriched_properties.append(property_obj)
                
                # Collect unique complexes
                if property_obj_orm.residential_complex:
                    complex_key = property_obj_orm.residential_complex.name
                    if complex_key not in all_complexes:
                        all_complexes[complex_key] = {
                            'name': property_obj_orm.residential_complex.name,
                            'developer': property_obj_orm.developer.name if property_obj_orm.developer else '',
                            'address': property_obj_orm.address or '',
                            'end_year': property_obj_orm.residential_complex.end_build_year,
                            'end_quarter': property_obj_orm.residential_complex.end_build_quarter,
                            'photos': [],
                            'lat': float(property_obj_orm.latitude) if property_obj_orm.latitude else None,
                            'lon': float(property_obj_orm.longitude) if property_obj_orm.longitude else None,
                            'cashback_rate': cashback_rate
                        }
        
        # ✅ MIGRATED: Загружаем фотографии для каждого комплекса из normalized tables
        for complex_name in all_complexes.keys():
            # Находим объекты этого комплекса с фотографиями
            complex_photos = []
            complex_properties = PropertyRepository.get_all_active(
                filters={'residential_complex': complex_name},
                limit=10
            )
            
            for prop in complex_properties:
                if prop.gallery_images:
                    try:
                        import json
                        prop_photos = []
                        if isinstance(prop.gallery_images, str) and prop.gallery_images.startswith('['):
                            prop_photos = json.loads(prop.gallery_images)
                        elif isinstance(prop.gallery_images, list):
                            prop_photos = prop.gallery_images
                        elif isinstance(prop.gallery_images, str) and prop.gallery_images.startswith('http'):
                            prop_photos = [url.strip() for url in prop.gallery_images.split(',') if url.strip()]
                        
                        # Добавляем уникальные фотографии
                        for photo in prop_photos:
                            if photo not in complex_photos:
                                complex_photos.append(photo)
                                if len(complex_photos) >= 10:  # Максимум 10 фотографий на комплекс
                                    break
                        
                        if len(complex_photos) >= 10:
                            break
                            
                    except Exception as e:
                        continue
            
            # Обновляем фотографии комплекса
            all_complexes[complex_name]['photos'] = complex_photos
        
        print(f"DEBUG: view_modern_presentation - Loaded {len(enriched_properties)} properties")
        
        # Подготавливаем сводную информацию
        total_complexes = len(all_complexes)
        complex_names = list(all_complexes.keys())
        
        print(f"DEBUG: view_modern_presentation - Rendering template")
        
        # Подготавливаем данные для шаблона
        presentation_data = {
            'id': presentation.id,
            'unique_url': presentation.unique_url,
            'title': presentation.title,
            'client_name': presentation.client_name,
            'description': presentation.description,
            'created_at': presentation.created_at,
            'properties': enriched_properties,
            'total_objects': len(enriched_properties),
            'total_complexes': total_complexes,
            'complex_names': complex_names,
            'all_complexes': all_complexes
        }
        
        return render_template('modern_presentation_view.html', presentation=presentation_data)
        
    except Exception as e:
        print(f"ERROR in view_modern_presentation: {e}")
        import traceback
        traceback.print_exc()
        
        # Return detailed error for debugging
        return render_template('error.html',
                             error="Ошибка загрузки презентации",
                             message=f"Техническая информация: {str(e)}"), 500
@bp.route('/api/manager/presentation/<int:presentation_id>/share', methods=['POST'])
@csrf.exempt
@manager_required
def share_presentation(presentation_id):
    """Получить данные для отправки презентации в мессенджеры (безопасная версия)"""
    from models import Collection
    from flask_login import current_user
    import urllib.parse
    
    current_manager = current_user
    
    print(f"DEBUG: share_presentation - presentation_id: {presentation_id}")
    print(f"DEBUG: share_presentation - current_user: {current_user}")
    print(f"DEBUG: share_presentation - current_manager.id: {current_manager.id}")
    print(f"DEBUG: share_presentation - request.method: {request.method}")
    print(f"DEBUG: share_presentation - request.content_type: {request.content_type}")
    
    try:
        data = request.get_json() or {}  # Пустой JSON валиден
        print(f"DEBUG: share_presentation - request data: {data}")
    except Exception as e:
        print(f"DEBUG: share_presentation - JSON parsing error: {e}")
        return jsonify({'success': False, 'error': f'Invalid JSON: {str(e)}'}), 400
    
    # Безопасное логирование после проверки аутентификации
    print(f"DEBUG: share_presentation - current_user.email: {getattr(current_user, 'email', 'Not authenticated')}")
    
    print(f"DEBUG: share_presentation - Looking for presentation {presentation_id} by manager {current_manager.id}")
    
    presentation = Collection.query.filter_by(
        id=presentation_id,
        created_by_manager_id=current_manager.id,
        collection_type='presentation'
    ).first()
    
    print(f"DEBUG: share_presentation - Found presentation: {presentation}")
    
    if not presentation:
        # Try to find presentation regardless of owner for debugging
        any_presentation = Collection.query.filter_by(
            id=presentation_id,
            collection_type='presentation'
        ).first()
        print(f"DEBUG: share_presentation - Any presentation with this ID: {any_presentation}")
        if any_presentation:
            print(f"DEBUG: share_presentation - Presentation exists but belongs to manager {any_presentation.created_by_manager_id}")
        return jsonify({'success': False, 'error': 'Презентация не найдена или у вас нет прав доступа'}), 404
    
    client_name = data.get('client_name', presentation.client_name)
    print(f"DEBUG: share_presentation - Client name: {client_name}")
    
    # Обновляем имя клиента если передано
    if client_name and client_name != presentation.client_name:
        print(f"DEBUG: share_presentation - Updating client name from '{presentation.client_name}' to '{client_name}'")
        presentation.client_name = client_name
        db.session.commit()
    
    # Формируем ссылку
    base_url = request.url_root.rstrip('/')
    presentation_url = f"{base_url}/presentation/modern/{presentation.unique_url}"
    print(f"DEBUG: share_presentation - Presentation URL: {presentation_url}")
    
    # Формируем сообщение для отправки
    properties_count = len(presentation.properties) if presentation.properties else 0
    print(f"DEBUG: share_presentation - Properties count: {properties_count}")
    
    # Получаем телефон менеджера
    manager_phone = current_user.phone if hasattr(current_user, 'phone') and current_user.phone else None
    manager_name = f"{current_user.first_name} {current_user.last_name}" if hasattr(current_user, 'first_name') and hasattr(current_user, 'last_name') else "Менеджер InBack"
    
    # Формируем контактную информацию
    if manager_phone:
        contact_info = f"👤 {manager_name}\n📞 {manager_phone}"
    else:
        contact_info = "📞 +7 (XXX) XXX-XX-XX"
    
    message_text = f"""🏠 Презентация недвижимости от InBack

📋 {presentation.title}
{f'👤 Для: {client_name}' if client_name else ''}

🔢 Подобрано объектов: {properties_count}
📅 Создано: {presentation.created_at.strftime('%d.%m.%Y')}

👀 Смотреть презентацию:
{presentation_url}

💬 Есть вопросы? Свяжитесь с нами!
{contact_info}"""
    
    response_data = {
        'success': True,
        'share_url': presentation_url,
        'share_data': {
            'presentation_url': presentation_url,
            'message_text': message_text,
            'whatsapp_url': f"https://wa.me/?text={urllib.parse.quote(message_text)}",
            'telegram_url': f"https://t.me/share/url?url={presentation_url}&text={urllib.parse.quote(presentation.title)}",
            'client_name': client_name or 'Клиент',
            'properties_count': properties_count
        }
    }
    
    print(f"DEBUG: share_presentation - Returning response: {response_data}")
    return jsonify(response_data)

@bp.route('/api/favorites/toggle', methods=['POST'])
def toggle_favorite():
    """Toggle favorite status for property - works for both authenticated and guest users"""
    from models import FavoriteProperty
    from services.guest_session import toggle_guest_favorite
    data = request.get_json()
    property_id = data.get('property_id')
    
    if not property_id:
        return jsonify({'success': False, 'error': 'property_id required'}), 400
    
    if not current_user.is_authenticated:
        action, is_fav = toggle_guest_favorite(property_id)
        return jsonify({'success': True, 'action': action, 'is_favorite': is_fav})
    
    print(f"DEBUG: Favorites toggle called by user {getattr(current_user, 'id', 'not_authenticated')} for property {property_id}")
    
    existing = FavoriteProperty.query.filter_by(
        user_id=current_user.id,
        property_id=property_id
    ).first()
    
    try:
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify({'success': True, 'action': 'removed', 'is_favorite': False})
        else:
            favorite = FavoriteProperty(
                user_id=current_user.id,
                property_id=property_id,
                property_name=data.get('property_name', ''),
                property_type=data.get('property_type', ''),
                property_size=float(data.get('property_size', 0)),
                property_price=int(data.get('property_price', 0)),
                complex_name=data.get('complex_name', ''),
                developer_name=data.get('developer_name', ''),
                property_image=data.get('property_image'),
                cashback_amount=int(data.get('cashback_amount', 0)),
                cashback_percent=float(data.get('cashback_percent', 0))
            )
            db.session.add(favorite)
            db.session.commit()
            return jsonify({'success': True, 'action': 'added', 'is_favorite': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400



@bp.route('/api/my-collections', methods=['GET'])
@login_required
def list_personal_collections():
    """List current user's personal collections"""
    from models import PersonalCollection
    cols = PersonalCollection.query.filter_by(user_id=current_user.id).order_by(PersonalCollection.created_at.desc()).all()
    return jsonify({'collections': [c.to_dict() for c in cols]})


@bp.route('/api/my-collections', methods=['POST'])
@login_required
def create_personal_collection():
    """Create a new personal collection for the current user"""
    from models import PersonalCollection
    data = request.get_json() or {}
    title = (data.get('title') or data.get('name') or '').strip()
    if not title:
        return jsonify({'success': False, 'error': 'Название обязательно'}), 400
    try:
        col = PersonalCollection(
            user_id=current_user.id,
            title=title[:100],
            description=(data.get('description') or '')[:300]
        )
        db.session.add(col)
        db.session.commit()
        return jsonify({'success': True, 'id': col.id, 'collection': col.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/my-collections/<int:collection_id>', methods=['DELETE'])
@login_required
def delete_personal_collection(collection_id):
    """Delete a personal collection"""
    from models import PersonalCollection
    col = PersonalCollection.query.filter_by(id=collection_id, user_id=current_user.id).first()
    if not col:
        return jsonify({'success': False, 'error': 'Не найдено'}), 404
    try:
        db.session.delete(col)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/my-collections/<int:collection_id>', methods=['GET'])
@login_required
def get_personal_collection(collection_id):
    """Get a personal collection with its items"""
    from models import PersonalCollection
    col = PersonalCollection.query.filter_by(id=collection_id, user_id=current_user.id).first()
    if not col:
        return jsonify({'success': False, 'error': 'Не найдено'}), 404
    items = [{
        'id': item.id,
        'property_id': item.property_id,
        'property_name': item.property_name or 'Объект #' + str(item.property_id),
        'property_price': item.property_price,
        'added_at': item.added_at.strftime('%d.%m.%Y') if item.added_at else ''
    } for item in col.items]
    data = col.to_dict()
    data['items'] = items
    return jsonify({'success': True, 'collection': data})


@bp.route('/api/my-collections/<int:collection_id>/remove/<int:item_id>', methods=['DELETE'])
@login_required
def remove_from_personal_collection(collection_id, item_id):
    """Remove an item from a personal collection"""
    from models import PersonalCollection, PersonalCollectionItem
    col = PersonalCollection.query.filter_by(id=collection_id, user_id=current_user.id).first()
    if not col:
        return jsonify({'success': False, 'error': 'Не найдено'}), 404
    item = PersonalCollectionItem.query.filter_by(id=item_id, collection_id=collection_id).first()
    if not item:
        return jsonify({'success': False, 'error': 'Объект не найден'}), 404
    try:
        db.session.delete(item)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/my-collections/<int:collection_id>/add', methods=['POST'])
@login_required
def add_to_personal_collection(collection_id):
    """Add a property to a personal collection"""
    from models import PersonalCollection, PersonalCollectionItem
    col = PersonalCollection.query.filter_by(id=collection_id, user_id=current_user.id).first()
    if not col:
        return jsonify({'success': False, 'error': 'Не найдено'}), 404
    data = request.get_json() or {}
    prop_id = str(data.get('property_id', '')).strip()
    if not prop_id:
        return jsonify({'success': False, 'error': 'property_id обязателен'}), 400
    existing = PersonalCollectionItem.query.filter_by(collection_id=collection_id, property_id=prop_id).first()
    if existing:
        return jsonify({'success': True, 'message': 'Уже в подборке'})
    try:
        item = PersonalCollectionItem(
            collection_id=collection_id,
            property_id=prop_id,
            property_name=data.get('property_name'),
            property_price=data.get('property_price')
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/collections', methods=['POST'])
@login_required
def create_collection():
    """Create new property collection"""
    from models import Collection
    data = request.get_json()
    
    try:
        collection = Collection(
            user_id=current_user.id,
            title=data['name'],
            description=data.get('description'),
            image_url=data.get('image_url'),
            category=data.get('category')
        )
        db.session.add(collection)
        db.session.commit()
        
        return jsonify({'success': True, 'collection_id': collection.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/collections/<int:collection_id>', methods=['DELETE'])
@login_required
def delete_collection(collection_id):
    """Delete a collection"""
    from models import Collection
    collection = Collection.query.filter_by(
        id=collection_id,
        user_id=current_user.id
    ).first()
    
    if not collection:
        return jsonify({'success': False, 'error': 'Подборка не найдена'}), 404
    
    try:
        db.session.delete(collection)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/documents/upload', methods=['POST'])
@login_required
def upload_documents():
    """Upload documents"""
    from models import Document
    import os
    from werkzeug.utils import secure_filename
    from datetime import datetime
    
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': 'Нет файлов для загрузки'}), 400
    
    files = request.files.getlist('files')
    uploaded_files = []
    
    # Create uploads directory if it doesn't exist
    upload_dir = 'instance/uploads'
    os.makedirs(upload_dir, exist_ok=True)
    
    for file in files:
        if file.filename == '':
            continue
        
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Add timestamp to avoid conflicts
            timestamp = str(int(datetime.utcnow().timestamp()))
            filename = f"{timestamp}_{filename}"
            file_path = os.path.join(upload_dir, filename)
            
            try:
                file.save(file_path)
                file_size = os.path.getsize(file_path)
                file_ext = filename.rsplit('.', 1)[1].lower()
                
                # Create document record
                document = Document(
                    user_id=current_user.id,
                    original_filename=secure_filename(file.filename) if file.filename else 'unknown',
                    stored_filename=filename,
                    file_path=file_path,
                    file_size=file_size,
                    file_type=file_ext,
                    document_type=determine_document_type(file.filename),
                    status='На проверке'
                )
                db.session.add(document)
                uploaded_files.append({
                    'filename': file.filename,
                    'size': file_size
                })
            except Exception as e:
                return jsonify({'success': False, 'error': f'Ошибка загрузки файла {file.filename}: {str(e)}'}), 400
    
    try:
        db.session.commit()
        return jsonify({'success': True, 'uploaded_files': uploaded_files})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/documents/<int:document_id>', methods=['DELETE'])
@login_required
def delete_document(document_id):
    """Delete a document"""
    from models import Document
    import os
    
    document = Document.query.filter_by(
        id=document_id,
        user_id=current_user.id
    ).first()
    
    if not document:
        return jsonify({'success': False, 'error': 'Документ не найден'}), 404
    
    try:
        # Delete physical file
        if os.path.exists(document.file_path):
            os.remove(document.file_path)
        
        # Delete database record
        db.session.delete(document)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def determine_document_type(filename):
    """Determine document type from filename"""
    filename_lower = filename.lower()
    if any(word in filename_lower for word in ['паспорт', 'passport']):
        return 'Паспорт'
    elif any(word in filename_lower for word in ['справка', 'доходы', 'income']):
        return 'Справка о доходах'
    elif any(word in filename_lower for word in ['договор', 'contract']):
        return 'Договор'
    elif any(word in filename_lower for word in ['снилс', 'снилс']):
        return 'СНИЛС'
    elif any(word in filename_lower for word in ['инн', 'inn']):
        return 'ИНН'
    else:
        return 'Другое'

# Manager authentication and dashboard routes
