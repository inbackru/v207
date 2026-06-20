"""
Smart Search API Blueprint
Routes: /api/smart-search, /api/search-suggestions, /api/super-search,
        /api/metrics, /api/smart-suggestions, /api/manager/add-client,
        /api/blog/search
"""
import json
import logging
import os
from datetime import datetime

from flask import Blueprint, jsonify, request, session, current_app
from flask_login import current_user, login_required

from app import db, csrf, cache, manager_required
from smart_search import smart_search

logger = logging.getLogger(__name__)

smart_search_api_bp = Blueprint('smart_search_api', __name__)

@smart_search_api_bp.route('/api/smart-search')
def smart_search_api():
    """Умный поиск с OpenAI анализом"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({'results': [], 'criteria': {}, 'suggestions': []})
    
    try:
        # Анализируем запрос с помощью OpenAI (включая определение города)
        criteria = smart_search.analyze_search_query(query)
        # Search criteria processed
        
        # Получаем свойства и применяем фильтры
        from app import load_properties
        properties = load_properties()
        
        # Автоматическая фильтрация по городу если он определен в запросе
        city_id = criteria.get('city_id')
        if city_id:
            # Фильтруем объекты по городу
            properties = [p for p in properties if p.get('city_id') == city_id]
            print(f"🌍 Автофильтр: оставлено {len(properties)} объектов для города ID {city_id}")
        
        # Применяем базовые фильтры на основе критериев
        filtered_properties = apply_smart_filters(properties, criteria)
        
        # Применяем семантический поиск если нужно
        if criteria.get('semantic_search') or criteria.get('features'):
            filtered_properties = smart_search.semantic_property_search(
                filtered_properties, query, criteria
            )
        
        # Подготавливаем результаты
        results = []
        for prop in filtered_properties[:20]:
            results.append({
                'type': 'property',
                'id': prop.get('inner_id') or str(prop.get('id', '')),
                'title': f"{prop.get('rooms', 0)}-комн {prop.get('area', 0)} м²" if prop.get('rooms', 0) > 0 else f"Студия {prop.get('area', 0)} м²",
                'subtitle': f"{prop.get('complex_name', '')} • {prop['district']}",
                'price': prop['price'],
                'rooms': prop.get('rooms', 1),
                'area': prop.get('area', 0),
                'url': f"/object/{prop['id']}"
            })
        
        # Генерируем подсказки
        suggestions = smart_search.generate_search_suggestions(query)
        
        return jsonify({
            'results': results,
            'criteria': criteria,
            'suggestions': suggestions[:5],
            'total': len(filtered_properties),
            'detected_city': {
                'city_id': criteria.get('city_id'),
                'city_name': criteria.get('city_name'),
                'city_slug': criteria.get('city_slug')
            } if criteria.get('city_id') else None
        })
        
    except Exception as e:
        print(f"ERROR: Smart search failed: {e}")
        # Fallback к обычному поиску
        return jsonify({'results': [], 'error': str(e)})

@smart_search_api_bp.route('/api/search-suggestions')
# ❌ КЭШ ОТКЛЮЧЁН для отладки типов квартир
# @cache.memoize(timeout=300)
def search_suggestions_api():
    """Супер-быстрый API для автодополнения поиска - ПРИОРИТЕТ: данные из БД"""
    query = request.args.get('q', '').strip()
    if not query or len(query) < 1:
        return jsonify([])
    
    try:
        from smart_search import smart_search
        
        # 1. ПРИОРИТЕТ: Поиск по реальным данным БД (ЖК, застройщики, районы, улицы)
        db_suggestions = smart_search.database_suggestions(query, limit=8)
        
        # 2. Если нашли результаты в БД - возвращаем их
        if db_suggestions and len(db_suggestions) > 0:
            print(f"✅ Found {len(db_suggestions)} DB suggestions for '{query}'")
            return jsonify(db_suggestions)
        
        # 3. Если ничего не нашли в БД - используем fallback (хардкод подсказки)
        print(f"⚠️ No DB results for '{query}', using fallback")
        fallback_suggestions = smart_search.fallback_suggestions(query, limit=8)
        return jsonify(fallback_suggestions)
        
    except Exception as e:
        # В случае ошибки - используем fallback
        print(f"❌ Database search failed for '{query}': {e}")
        import traceback
        traceback.print_exc()
        return search_suggestions_fallback(query)

def search_suggestions_fallback(query):
    """✅ MIGRATED TO NORMALIZED TABLES: Fallback search using ResidentialComplexRepository"""
    suggestions = []
    query_lower = query.lower()
    
    try:
        # ✅ MIGRATED: Search complexes using ResidentialComplexRepository
        from models import ResidentialComplex
        complexes = (
            db.session.query(
                ResidentialComplex.name,
                func.count(Property.id).label('count')
            )
            .join(Property, ResidentialComplex.id == Property.complex_id)
            .filter(
                ResidentialComplex.name.ilike(f'%{query_lower}%'),
                Property.is_active == True
            )
            .group_by(ResidentialComplex.name)
            .order_by(func.count(Property.id).desc())
            .limit(4)
            .all()
        )
        
        for row in complexes:
            suggestions.append({
                'type': 'complex',
                'title': row[0],
                'subtitle': f'{row[1]} квартир',
                'icon': 'building',
                'url': f'/properties?residential_complex={row[0]}'
            })
        
        return jsonify({'suggestions': suggestions[:6]})
    except Exception as e:
        return jsonify({'suggestions': [], 'error': str(e)})

@smart_search_api_bp.route('/api/super-search')
@cache.memoize(timeout=180)  # Кэш на 3 минуты
def super_search_api():
    """Новый супер-быстрый поиск недвижимости"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'results': [], 'total': 0})
    
    try:
        from smart_search import smart_search
        results = smart_search.search_properties(query, limit=50)
        return jsonify(results)
        
    except Exception as e:
        print(f"Super search error: {e}")
        return jsonify({'results': [], 'total': 0, 'error': str(e)})

@smart_search_api_bp.route('/api/metrics', methods=['POST'])
def collect_metrics():
    """Сбор метрик производительности для анализа"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400
        
        # Логируем важные метрики
        metric_type = data.get('type', 'unknown')
        
        if metric_type == 'page_load':
            duration = data.get('duration', 0)
            url = data.get('url', 'unknown')
            print(f"⚡ Page Load: {url} in {round(duration)}ms")
        
        elif metric_type == 'search_performance':
            query = data.get('query', '')
            response_time = data.get('response_time', 0)
            results_count = data.get('results_count', 0)
            print(f"🔍 Search: '{query}' - {round(response_time)}ms, {results_count} results")
        
        # В реальном приложении здесь бы была запись в базу данных
        # для аналитики производительности
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        print(f"Metrics collection error: {e}")
        return jsonify({'status': 'error'}), 500

@smart_search_api_bp.route('/api/smart-suggestions')
def smart_suggestions_api():
    """API для получения умных подсказок поиска"""
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify({'suggestions': []})
    
    try:
        suggestions = smart_search.generate_search_suggestions(query)
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        print(f"ERROR: Smart suggestions failed: {e}")
        return jsonify({'suggestions': []})

def apply_smart_filters(properties, criteria):
    """Применяет умные фильтры на основе критериев OpenAI"""
    filtered = properties.copy()
    
    # Фильтр по комнатам
    if criteria.get('rooms'):
        rooms_list = criteria['rooms']
        filtered = [p for p in filtered if str(p.get('rooms', '')) in rooms_list]
    
    # Фильтр по району
    if criteria.get('district'):
        district = criteria['district']
        filtered = [p for p in filtered if p.get('district', '') == district]
    
    # Фильтр по ключевым словам (типы недвижимости, классы, материалы)
    if criteria.get('keywords'):
        keywords_filtered = []
        for prop in filtered:
            prop_matches = False
            for keyword in criteria['keywords']:
                keyword_lower = keyword.lower()
                
                # Тип недвижимости
                prop_type_lower = prop.get('property_type', 'Квартира').lower()
                if keyword_lower == prop_type_lower:
                    prop_matches = True
                    break
                
                # Класс недвижимости (точное совпадение)
                prop_class_lower = prop.get('property_class', '').lower()
                if keyword_lower == prop_class_lower:
                    prop_matches = True
                    break
                
                # Материал стен
                wall_material_lower = prop.get('wall_material', '').lower()
                if keyword_lower in wall_material_lower:
                    prop_matches = True
                    break
                
                # Особенности
                features = prop.get('features', [])
                if any(keyword_lower in feature.lower() for feature in features):
                    prop_matches = True
                    break
                
                # Особая логика для ценовых категорий
                if keyword_lower == 'дорого' or keyword_lower == 'недорого':
                    # Эти ключевые слова обрабатываются отдельно после фильтрации
                    continue
                
                # Поиск в заголовке как fallback
                property_title = f"{prop.get('rooms', 0)}-комн {prop.get('area', 0)} м²" if prop.get('rooms', 0) > 0 else f"Студия {prop.get('area', 0)} м²"
                title_lower = property_title.lower()
                if keyword_lower in title_lower:
                    prop_matches = True
                    break
            
            if prop_matches:
                keywords_filtered.append(prop)
        
        filtered = keywords_filtered
        
        # Обработка ценовых ключевых слов после основной фильтрации
        if 'дорого' in criteria.get('keywords', []):
            # Сортируем по цене и берем верхние 50%
            filtered = sorted(filtered, key=lambda x: x.get('price', 0), reverse=True)
            filtered = filtered[:max(1, len(filtered)//2)]
        elif 'недорого' in criteria.get('keywords', []):
            # Сортируем по цене и берем нижние 50%
            filtered = sorted(filtered, key=lambda x: x.get('price', 0))
            filtered = filtered[:max(1, len(filtered)//2)]
    
    # Фильтр по особенностям
    if criteria.get('features'):
        features_list = criteria['features']
        features_filtered = []
        for prop in filtered:
            prop_features = [f.lower() for f in prop.get('features', [])]
            if any(feature.lower() in prop_features for feature in features_list):
                features_filtered.append(prop)
        filtered = features_filtered
    
    # Фильтр по цене
    if criteria.get('price_range'):
        price_range = criteria['price_range']
        if len(price_range) >= 1 and price_range[0]:
            min_price = price_range[0]
            filtered = [p for p in filtered if p.get('price', 0) >= min_price]
        if len(price_range) >= 2 and price_range[1]:
            max_price = price_range[1]
            filtered = [p for p in filtered if p.get('price', 0) <= max_price]
    
    return filtered

# Manager Client Management Routes
@smart_search_api_bp.route('/api/manager/add-client', methods=['POST'])
@manager_required
def manager_add_client():
    """Add new client"""
    from models import User, Manager
    import re
    
    current_manager = current_user
    print(f"DEBUG: Add client endpoint called by manager {current_manager.id}")
    print(f"DEBUG: Request method: {request.method}, Content-Type: {request.content_type}")
    print(f"DEBUG: Request is_json: {request.is_json}")
    
    try:
        # Accept both JSON and form data
        if request.is_json:
            data = request.get_json()
            print(f"DEBUG: Received JSON data: {data}")
            full_name = data.get('full_name', '').strip()
            email = data.get('email', '').strip().lower()
            phone = data.get('phone', '').strip() if data.get('phone') else None
            is_active = data.get('is_active', True)
            client_request = data.get('client_request', '').strip() if data.get('client_request') else None
        else:
            print(f"DEBUG: Received form data: {dict(request.form)}")
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            phone = request.form.get('phone', '').strip() if request.form.get('phone') else None
            is_active = 'is_active' in request.form
            client_request = request.form.get('client_request', '').strip() if request.form.get('client_request') else None
        
        print(f"DEBUG: Parsed data - name: {full_name}, email: {email}, phone: {phone}, active: {is_active}")
        
        # Validation
        if not full_name or len(full_name) < 2:
            return jsonify({'success': False, 'error': 'Полное имя должно содержать минимум 2 символа'}), 400
        
        # Email validation
        email_regex = r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$'
        if not email or not re.match(email_regex, email):
            return jsonify({'success': False, 'error': 'Введите корректный email адрес'}), 400
        
        # Phone validation (optional but must be correct format if provided)
        if phone:
            phone_regex = r'^\+7-\d{3}-\d{3}-\d{2}-\d{2}$'
            if not re.match(phone_regex, phone):
                return jsonify({'success': False, 'error': 'Телефон должен быть в формате +7-918-123-45-67'}), 400
        
        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return jsonify({'success': False, 'error': 'Пользователь с таким email уже существует'}), 400
        
        # Check if phone already exists (normalized comparison like registration)
        if phone:
            from sqlalchemy import func as sqlfunc
            phone_digits = re.sub(r'[^0-9]', '', phone)
            existing_phone_user = User.query.filter(
                sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits
            ).first()
            if existing_phone_user:
                return jsonify({'success': False, 'error': 'Пользователь с таким номером телефона уже существует'}), 400
        
        # Generate temporary password
        import secrets
        import string
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        
        # Create new user with temporary password
        user = User(
            is_verified=True,  # Auto-verify
            full_name=full_name,
            email=email,
            phone=phone,
            is_active=is_active,
            role='buyer',
            assigned_manager_id=current_manager.id,
            registration_source='Manager',
            client_status='Новый',
            client_notes=client_request
        )
        user.must_change_password = True  # Требуется смена временного пароля
        user.set_password(temp_password)  # Set temporary password
        
        db.session.add(user)
        db.session.commit()
        
        print(f"DEBUG: Successfully created client {user.id}: {user.full_name}")
        
        # Send welcome email and SMS with credentials
        try:
            from email_service import send_email
            manager = Manager.query.get(manager_id)
            manager_name = manager.full_name if manager else 'Ваш менеджер'
            
            # Email with login credentials
            subject = "Ваш аккаунт создан в InBack.ru - Данные для входа"
            email_content = f"""Здравствуйте, {full_name}!

Для вас создан аккаунт на платформе InBack.ru

📧 Email для входа: {email}
🔑 Временный пароль: {temp_password}

🌐 Ссылка для входа: {request.url_root.rstrip('/')}/login

ВАЖНО: Рекомендуем сменить пароль после первого входа в разделе "Настройки профиля"

Ваш персональный менеджер: {manager_name}

По всем вопросам обращайтесь к своему менеджеру.

С уважением,
Команда InBack.ru"""
            
            send_email(
                to_email=email,
                subject=subject,
                content=email_content,
                template_name='notification'
            )
            print(f"DEBUG: Welcome email with credentials sent to {email}")
            
            # Send SMS if phone number provided
            if phone:
                try:
                    from sms_service import send_login_credentials_sms
                    
                    sms_sent = send_login_credentials_sms(
                        phone=phone,
                        email=email,
                        password=temp_password,
                        manager_name=manager_name,
                        login_url=f"{request.url_root.rstrip('/')}/login"
                    )
                    
                    if sms_sent:
                        print(f"DEBUG: SMS sent successfully to {phone}")
                    else:
                        print(f"DEBUG: SMS sending failed for {phone}")
                    
                except Exception as sms_e:
                    print(f"DEBUG: Failed to send SMS: {sms_e}")
                    
        except Exception as e:
            print(f"DEBUG: Failed to send welcome email: {e}")
        
        return jsonify({
            'success': True, 
            'client_id': user.id,
            'message': f'Клиент {full_name} успешно добавлен. Данные для входа отправлены на email {email}' + (f' и SMS на {phone}' if phone else '') + '.',
            'client_data': {
                'id': user.id,
                'full_name': user.full_name,
                'email': user.email,
                'phone': user.phone,
                'user_id': user.user_id,
                'login_url': f"{request.url_root.rstrip('/')}/login",
                'temp_password': temp_password  # Include for manager reference
            }
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error adding client: {str(e)}")
        return jsonify({'success': False, 'error': f'Ошибка сервера: {str(e)}'}), 500


def send_callback_notification_email(callback_req, manager):
    """Send email notification about callback request"""
    try:
        from email_service import send_email
        
        # Email content
        subject = f"Новая заявка на обратный звонок - {callback_req.name}"
        
        # Build message content
        content = f"""
        Получена новая заявка на обратный звонок:
        
        Клиент: {callback_req.name}
        Телефон: {callback_req.phone}
        Email: {callback_req.email or 'Не указан'}
        Удобное время: {callback_req.preferred_time}
        
        Интересует: {callback_req.interest}
        Бюджет: {callback_req.budget}
        Планирует покупку: {callback_req.timing}
        
        Дополнительно: {callback_req.notes or 'Нет дополнительной информации'}
        
        Назначенный менеджер: {manager.full_name if manager else 'Не назначен'}
        Дата заявки: {callback_req.created_at.strftime('%d.%m.%Y %H:%M')}
        """
        
        # Try to send to manager first, then to admin email
        recipient_email = manager.email if manager else 'admin@inback.ru'
        
        success = send_email(
            to_email=recipient_email,
            subject=subject,
            content=content,
            template_name='notification'
        )
        
        if success:
            print(f"✓ Callback notification email sent to {recipient_email}")
        else:
            print(f"✗ Failed to send callback notification email to {recipient_email}")
            
    except Exception as e:
        print(f"Error sending callback notification email: {e}")


def send_callback_notification_telegram(callback_req, manager):
    """Send Telegram notification about callback request"""
    try:
        # Check if telegram_bot module can be imported
        try:
            from telegram_bot import send_telegram_message
        except ImportError as e:
            print(f"Telegram bot not available: {e}")
            return False
        
        # Calculate potential cashback
        potential_cashback = ""
        if callback_req.budget:
            if "млн" in callback_req.budget:
                # Extract average from range like "3-5 млн"
                numbers = [float(x) for x in callback_req.budget.replace(" млн", "").replace("руб", "").split("-") if x.strip().replace(".", "").replace(",", "").isdigit()]
                if numbers:
                    avg_price = sum(numbers) / len(numbers) * 1000000
                    cashback = int(avg_price * 0.02)
                    potential_cashback = f"💰 *Потенциальный кэшбек:* {cashback:,} руб. (2%)\n"
        
        # Enhanced Telegram message
        message = f"""📞 *НОВАЯ ЗАЯВКА НА ОБРАТНЫЙ ЗВОНОК*

👤 *КОНТАКТНАЯ ИНФОРМАЦИЯ:*
• Имя: {callback_req.name}
• Телефон: {callback_req.phone}
• Email: {callback_req.email or 'Не указан'}
• Удобное время звонка: {callback_req.preferred_time}

🔍 *КРИТЕРИИ ПОИСКА:*
• Интересует: {callback_req.interest or 'Не указано'}
• Бюджет: {callback_req.budget or 'Не указан'}
• Планы на покупку: {callback_req.timing or 'Не указано'}

{potential_cashback}📝 *ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ:*
{callback_req.notes or 'Нет дополнительной информации'}

📅 *ВРЕМЯ ЗАЯВКИ:* {callback_req.created_at.strftime('%d.%m.%Y в %H:%M')}
🌐 *ИСТОЧНИК:* Форма обратного звонка на сайте InBack.ru
👨‍💼 *НАЗНАЧЕННЫЙ МЕНЕДЖЕР:* {manager.full_name if manager else 'Не назначен'}

📋 *СЛЕДУЮЩИЕ ШАГИ:*
1️⃣ Перезвонить клиенту в указанное время
2️⃣ Провести консультацию по критериям
3️⃣ Подготовить персональную подборку
4️⃣ Запланировать показы объектов

⚡ *ВАЖНО:* Соблюдайте время, удобное для клиента!"""
        
        chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
        success = send_telegram_message(chat_id, message) if chat_id else False
        
        if manager:
            from email_service import send_manager_notification
            send_manager_notification(
                manager, 'new_lead', message,
                email_subject=f'Заявка на обратный звонок: {callback_req.name}',
                email_template='emails/general_notification.html',
                user_name=manager.first_name,
                subject=f'Заявка на обратный звонок: {callback_req.name}',
                message=f'Новая заявка на обратный звонок от {callback_req.name} ({callback_req.phone}). Проверьте панель менеджера для деталей.'
            )
        
        if success:
            print(f"✓ Callback notification sent to Telegram chat {chat_id}")
        else:
            print(f"✗ Failed to send callback notification to Telegram")
            
    except Exception as e:
        print(f"Error sending callback notification to Telegram: {e}")


# Database initialization happens in the app context below


@smart_search_api_bp.route('/api/blog/search')
def blog_search_api():
    """API endpoint for instant blog search and suggestions"""
    from models import BlogPost, Category
    from sqlalchemy import or_, func
    
    try:
        query = request.args.get('q', '').strip()
        category = request.args.get('category', '').strip()
        suggestions_only = request.args.get('suggestions', '').lower() == 'true'
        
        # Start with base query - use BlogPost (where data actually is)
        search_query = BlogPost.query.filter(BlogPost.status == 'published')
        
        # Apply search filter
        if query:
            search_query = search_query.filter(
                or_(
                    BlogPost.title.ilike(f'%{query}%'),
                    BlogPost.content.ilike(f'%{query}%'),
                    BlogPost.excerpt.ilike(f'%{query}%')
                )
            )
        
        # Apply category filter
        if category:
            search_query = search_query.filter(BlogPost.category == category)
        
        # For suggestions, limit to title matches only
        if suggestions_only:
            if query:
                suggestions = search_query.filter(
                    BlogPost.title.ilike(f'%{query}%')
                ).limit(5).all()
                
                return jsonify({
                    'suggestions': [{
                        'title': post.title,
                        'slug': post.slug,
                        'category': post.category or 'Общее'
                    } for post in suggestions]
                })
            else:
                return jsonify({'suggestions': []})
        
        # For full search, return formatted articles
        articles = search_query.order_by(BlogPost.created_at.desc()).limit(20).all()
        
        formatted_articles = []
        for article in articles:
            formatted_articles.append({
                'title': article.title,
                'slug': article.slug,
                'excerpt': article.excerpt or '',
                'featured_image': article.featured_image or '',
                'category': article.category or 'Общее',
                'date': article.created_at.strftime('%d.%m.%Y'),
                'reading_time': getattr(article, 'reading_time', 5),
                'views': getattr(article, 'views', 0)
            })
        return jsonify({
            'articles': formatted_articles,
            'total': len(formatted_articles)
        })
        
    except Exception as e:
        print(f"ERROR in blog search API: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Search failed', 'articles': [], 'suggestions': []}), 500
