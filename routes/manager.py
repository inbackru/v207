"""
Manager Blueprint — manager portal routes.
Endpoints: manager_login, manager_logout, manager_dashboard, manager_profile,
           manager_favorites, manager_collections, manager_analytics,
           manager_clients, manager_deals, manager_deals_kanban,
           manager_tasks_calendar, manager_deal_card, manager_employees, etc.
"""
from datetime import datetime
from werkzeug.security import generate_password_hash

from flask import (Blueprint, abort, flash, jsonify, make_response,
                   redirect, render_template, request, session, url_for)
from flask_login import current_user, login_user, logout_user

# These are defined early in app.py (before blueprint registration) — safe to import
from app import db, csrf, manager_required

def get_manager_sidebar_data(current_manager, active_page='dashboard'):
    """Thin wrapper — delegates to manager_api to avoid circular imports at startup."""
    from routes.manager_api import get_manager_sidebar_data as _fn
    return _fn(current_manager, active_page=active_page)

manager_bp = Blueprint('mgr', __name__)


@manager_bp.route('/manager/logout')
def manager_logout():
    """Manager logout"""
    logout_user()
    flash('Вы успешно вышли из системы', 'success')
    return redirect(url_for('mgr.manager_login'))


@manager_bp.route('/manager/login', methods=['GET', 'POST'])
@csrf.exempt  # CSRF disabled  # Temporarily disable CSRF for login
def manager_login():
    """Simplified manager login with step-by-step error isolation"""
    if request.method == 'POST':
        # Step 1: Import and basic validation
        try:
            print("STEP 1: Starting manager login process")
            email = request.form.get('email')
            password = request.form.get('password')
            print(f"STEP 1: Got email={email}, password={'*' * len(password) if password else 'None'}")
            
            if not email or not password:
                print("STEP 1: Missing credentials")
                flash('Заполните все поля', 'error')
                return render_template('auth/manager_login.html')
            print("STEP 1: Basic validation passed")
            
        except Exception as e:
            print(f"ERROR IN STEP 1: {e}")
            flash('Ошибка обработки данных', 'error')
            return render_template('auth/manager_login.html')
        
        # Step 2: Database query
        try:
            print("STEP 2: Importing Manager model")
            from models import Manager
            print("STEP 2: Manager model imported successfully")
            
            print("STEP 2: Querying database for manager")
            manager = Manager.query.filter_by(email=email, is_active=True).first()
            print(f"STEP 2: Database query result: {manager is not None}")
            
            if not manager:
                print("STEP 2: Manager not found")
                flash('Неверные данные для входа', 'error')
                return render_template('auth/manager_login.html')
            
            print(f"STEP 2: Manager found - ID: {manager.id}, Email: {manager.email}")
            
        except Exception as e:
            print(f"ERROR IN STEP 2: {e}")
            import traceback
            traceback.print_exc()
            flash('Ошибка подключения к базе данных', 'error')
            return render_template('auth/manager_login.html')
        
        # Step 3: Password verification
        try:
            print("STEP 3: Checking password")
            password_valid = manager.check_password(password)
            print(f"STEP 3: Password check result: {password_valid}")
            
            if not password_valid:
                print("STEP 3: Password invalid")
                flash('Неверные данные для входа', 'error')
                return render_template('auth/manager_login.html')
            
            print("STEP 3: Password verification passed")
            
        except Exception as e:
            print(f"ERROR IN STEP 3: {e}")
            import traceback
            traceback.print_exc()
            flash('Ошибка проверки пароля', 'error')
            return render_template('auth/manager_login.html')
        
        # Step 4: Flask-Login авторизация (ИСПРАВЛЕНО)
        try:
            print("STEP 4: Using Flask-Login")
            login_user(manager, remember=True)  # Используем Flask-Login вместо ручных сессий
            session.permanent = True  # Ensure 30-day session lifetime
            print(f"STEP 4: Flask-Login successful, manager.get_id()={manager.get_id()}")
            
        except Exception as e:
            print(f"ERROR IN STEP 4: {e}")
            import traceback
            traceback.print_exc()
            flash('Ошибка авторизации', 'error')
            return render_template('auth/manager_login.html')
        
        # Step 5: Database update
        try:
            print("STEP 5: Updating last login time")
            from datetime import datetime
            manager.last_login = datetime.utcnow()
            manager.last_ip = request.remote_addr
            manager.last_user_agent = request.headers.get('User-Agent')
            db.session.commit()
            print("STEP 5: Database commit successful")
            
        except Exception as e:
            print(f"ERROR IN STEP 5: {e}")
            import traceback
            traceback.print_exc()
            flash('Ошибка обновления базы данных', 'error')
            return render_template('auth/manager_login.html')
        
        # Step 6: Success redirect
        try:
            print("STEP 6: Preparing success response")
            print(f"STEP 6: Login successful for manager {manager.email}")
            return redirect(url_for('mgr.manager_dashboard'))
            
        except Exception as e:
            print(f"ERROR IN STEP 6: {e}")
            import traceback
            traceback.print_exc()
            flash('Ошибка перенаправления', 'error')
            return render_template('auth/manager_login.html')
    
    # GET request - show login form
    return render_template('auth/manager_login.html')



# Manager Comparison Routes

@manager_bp.route('/manager/property-comparison')
@manager_required
def manager_property_comparison():
    """Manager property comparison page"""
    from models import Manager
    
    current_manager = current_user
    
    return render_template('auth/manager_property_comparison.html', current_manager=current_manager)


@manager_bp.route('/manager/complex-comparison')
@manager_required
def manager_complex_comparison():
    """Manager complex comparison page"""
    from models import Manager
    
    current_manager = current_user
    
    return render_template('auth/manager_complex_comparison.html', current_manager=current_manager)


@manager_bp.route('/manager/dashboard')
@manager_required
def manager_dashboard():
    from models import Manager, User, CashbackApplication, Document
    
    # ИСПРАВЛЕНО: используем Flask-Login вместо session
    current_manager = current_user
    print(f"DEBUG: Manager dashboard - current_manager: {current_manager.email if current_manager else None}")
    
    current_city = None

    # Get statistics (используем current_manager.id)
    try:
        print('DEBUG: Starting statistics queries...')
        print('DEBUG: Querying total_clients...')
        total_clients = User.query.filter_by(assigned_manager_id=current_manager.id).count()
        print(f'DEBUG: total_clients = {total_clients}')
        
        print('DEBUG: Querying new_clients_count...')
        new_clients_count = User.query.filter_by(
            assigned_manager_id=current_manager.id, 
            client_status='Новый'
        ).count()
        
        print('DEBUG: Querying pending_applications_count...')
        pending_applications_count = CashbackApplication.query.join(User).filter(
            User.assigned_manager_id == current_manager.id,
            CashbackApplication.status == 'На рассмотрении'
        ).count()
        
        print('DEBUG: Querying pending_documents_count...')
        pending_documents_count = Document.query.join(User).filter(
            User.assigned_manager_id == current_manager.id,
            Document.status == 'На проверке'
        ).count()
    except Exception as e:
        print(f"DEBUG: Error in statistics queries: {e}")
        total_clients = 0
        new_clients_count = 0
        pending_applications_count = 0
        pending_documents_count = 0
    
    # Calculate total approved cashback (оптимизировано - используем SQL SUM вместо загрузки в память)
    total_approved_cashback = 0
    try:
        from sqlalchemy import func
        from models import CashbackApplication, User
        # Исправлено: суммируем cashback_amount из CashbackApplication
        total_approved_cashback = db.session.query(
            func.sum(CashbackApplication.cashback_amount)
        ).join(User).filter(
            User.assigned_manager_id == current_manager.id,
            CashbackApplication.status == 'Одобрена'
        ).scalar() or 0
    except Exception as e:
        print(f"DEBUG: Error calculating cashback: {e}")
        total_approved_cashback = 0
    
    # Recent activities (mock data for now)
    recent_activities = [
        {
            'message': 'Новый клиент Иван Петров зарегистрировался',
            'time_ago': '5 минут назад',
            'color': 'blue',
            'icon': 'user-plus'
        },
        {
            'message': 'Заявка на кешбек от Анны Сидоровой требует проверки',
            'time_ago': '1 час назад',
            'color': 'yellow',
            'icon': 'file-alt'
        }
    ]
    
    try:
        from models import Collection, Deal, ManagerFavoriteProperty, ManagerFavoriteComplex, ManagerComparison, ComparisonComplex, ComparisonProperty
        
        print('DEBUG: About to query collections...')
        collections_count = Collection.query.filter_by(created_by_manager_id=current_manager.id).count()
        recent_collections = Collection.query.filter_by(created_by_manager_id=current_manager.id).order_by(Collection.created_at.desc()).limit(5).all()
        
        # Get presentations statistics
        presentations_count = Collection.query.filter_by(
            created_by_manager_id=current_manager.id, 
            collection_type='presentation'
        ).count()
        
        # Get deals statistics
        deals_count = Deal.query.filter_by(manager_id=current_manager.id).count()
        
        # Load data for manager filters
        from app import get_districts_list, get_developers_list
        districts = get_districts_list()
        developers = get_developers_list()
        
        print(f"DEBUG: Rendering dashboard with manager: {current_manager.full_name}")

        # Load manager favorites and comparison counts
        print("DEBUG: Loading manager favorites counts...")
        manager_favorites_count = ManagerFavoriteProperty.query.filter_by(manager_id=current_manager.id).count()
        manager_complexes_count = ManagerFavoriteComplex.query.filter_by(manager_id=current_manager.id).count()
        manager_comparison_properties = db.session.query(ComparisonProperty).join(
            ManagerComparison, ComparisonProperty.manager_comparison_id == ManagerComparison.id
        ).filter(ManagerComparison.manager_id == current_manager.id).count()
        manager_comparison_complexes = ComparisonComplex.query.join(ManagerComparison, ComparisonComplex.manager_comparison_id == ManagerComparison.id).filter(ManagerComparison.manager_id == current_manager.id).count()
        total_favorites = manager_favorites_count + manager_complexes_count
        total_comparison = manager_comparison_properties + manager_comparison_complexes
    except Exception as e:
        print(f"DEBUG: Error loading extra manager data: {e}")
        collections_count = 0
        recent_collections = []
        presentations_count = 0
        deals_count = 0
        districts = []
        developers = []
        total_favorites = 0
        total_comparison = 0
    
    print(f"DEBUG: Extra data loaded - favorites={total_favorites}, comparison={total_comparison}")
        # Sidebar links для менеджера  
    sidebar_links = [
        {'label': 'На главную', 'href': '/', 'page': 'home', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"/></svg>'},
        {'label': 'Главная', 'href': '#dashboard', 'page': 'dashboard', 'active': True, 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M10 2L3 7v11h3v-6h8v6h3V7l-7-5z"/></svg>'},
        {'label': 'Клиенты', 'href': '#clients', 'page': 'clients', 'badge': str(total_clients) if total_clients else '0', 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/></svg>'},
        {'label': 'Презентации', 'href': '#presentations', 'page': 'presentations', 'badge': str(presentations_count), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z"/></svg>'},
        {'label': 'Сохраненные поиски', 'href': '#saved-searches', 'page': 'saved-searches', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>'},
        {'label': 'Избранное', 'href': '#favorites', 'page': 'favorites', 'badge': str(total_favorites), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M3.172 5.172a4 4 0 015.656 0L10 6.343l1.172-1.171a4 4 0 115.656 5.656L10 17.657l-6.828-6.829a4 4 0 010-5.656z" clip-rule="evenodd"/></svg>'},
        {'label': 'Сравнение', 'href': '#comparison', 'page': 'comparison', 'badge': str(total_comparison), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>'},
        {'label': 'Чат', 'href': '#chat', 'page': 'chat', 'icon': '<svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>'},
        {'label': 'Сделки', 'href': url_for('mgr.manager_deals_kanban'), 'page': 'deals', 'badge': str(deals_count), 'badge_color': 'gray', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M6 2a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V7.414A2 2 0 0015.414 6L12 2.586A2 2 0 0010.586 2H6zm5 6a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V8z" clip-rule="evenodd"/></svg>'},
        {'label': 'Архив сделок', 'href': url_for('mgr.manager_deals_archive'), 'page': 'deals_archive', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M4 3a2 2 0 100 4h12a2 2 0 100-4H4z"/><path fill-rule="evenodd" d="M3 8h14v7a2 2 0 01-2 2H5a2 2 0 01-2-2V8zm5 3a1 1 0 011-1h2a1 1 0 110 2H9a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>'},
        {'label': 'Сотрудники', 'href': url_for('mgr.manager_employees'), 'page': 'employees', 'icon': '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-3a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 15v3h-3zM4.75 12.094A5.973 5.973 0 004 15v3H1v-3a3 3 0 013.75-2.906z"/></svg>'},
    ]
    
    assigned_manager = None

    user_profile = {'name': f"{current_manager.first_name} {current_manager.last_name}".strip() or current_manager.email.split('@')[0], 'role': current_manager.org_role.name if current_manager.org_role else ('РОП' if getattr(current_manager, 'is_rop', False) else 'Менеджер'), 'initials': current_manager.first_name[0].upper() if current_manager.first_name else current_manager.email[0].upper(), 'href': url_for('mgr.manager_profile'), 'avatar': current_manager.profile_image if current_manager.profile_image else None}
    # Profile completion for managers (always 100% since they don't need profile completion)
    profile_completion = 100
    profile_missing_fields = []
    try:
        # Balance data for template (manager doesn't have balance, set defaults)
        user_balance = 0
        balance_transactions = []
        
        print("DEBUG: About to render manager dashboard template")
        response = make_response(render_template('auth/manager_dashboard.html',
                             current_manager=current_manager,
                             current_city=current_city,
                             total_clients=total_clients,
                             new_clients_count=new_clients_count,
                             pending_applications_count=pending_applications_count,
                             pending_documents_count=pending_documents_count,
                             total_approved_cashback=total_approved_cashback,
                             recent_activities=recent_activities,
                             pending_notifications=pending_applications_count + pending_documents_count,
                             collections_count=collections_count,
                             presentations_count=presentations_count,
                             deals_count=deals_count,
                             recent_collections=recent_collections,
                             districts=districts,
                             developers=developers,
                             sidebar_links=sidebar_links,
                             user_profile=user_profile,
                             user_balance=user_balance,
                             balance_transactions=balance_transactions,
                             assigned_manager=assigned_manager,
                             profile_completion=profile_completion,
                             profile_missing_fields=profile_missing_fields))
        # Add anti-cache headers
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        print(f"DEBUG: Error rendering dashboard: {e}")
        import traceback
        traceback.print_exc()
        return f"Error rendering dashboard: {e}", 500



@manager_bp.route('/manager/favorites')
@manager_required
def manager_favorites():
    """Manager favorites page - separate page like user favorites"""
    from models import Manager
    
    current_manager = current_user
    
    return render_template('manager/favorites.html', current_manager=current_manager)



@manager_bp.route('/manager/presentation/<int:presentation_id>')
@manager_required
def manager_presentation_view(presentation_id):
    """Redirect to main dashboard with presentation open inline"""
    return redirect(url_for('mgr.manager_dashboard') + f'?tab=presentations&presentation_id={presentation_id}')


# API routes for manager actions

@manager_bp.route('/manager/profile', methods=['GET', 'POST'])
@manager_required
def manager_profile():
    """Manager profile page"""
    from models import Manager
    
    current_manager = current_user
    
    if request.method == 'POST':
        try:
            # Update profile information
            full_name = request.form.get('full_name', '')
            if full_name:
                name_parts = full_name.strip().split(maxsplit=1)
                current_manager.first_name = name_parts[0] if len(name_parts) > 0 else current_manager.first_name
                current_manager.last_name = name_parts[1] if len(name_parts) > 1 else current_manager.last_name
            
            current_manager.telegram_id = request.form.get('telegram_id', current_manager.telegram_id)
            
            years_exp = request.form.get('years_of_experience')
            if years_exp:
                current_manager.years_of_experience = int(years_exp)
            
            current_manager.notify_email = 'notify_email' in request.form
            current_manager.notify_telegram = 'notify_telegram' in request.form
            current_manager.notify_new_leads = 'notify_new_leads' in request.form
            current_manager.notify_new_deals = 'notify_new_deals' in request.form
            current_manager.notify_task_reminders = 'notify_task_reminders' in request.form
            current_manager.notify_overdue_tasks = 'notify_overdue_tasks' in request.form
            current_manager.notify_presentation_views = 'notify_presentation_views' in request.form
            current_manager.notify_booking_requests = 'notify_booking_requests' in request.form
            current_manager.notify_daily_digest = 'notify_daily_digest' in request.form
            
            # Update password if provided
            new_password = request.form.get('new_password')
            if new_password:
                confirm_password = request.form.get('confirm_password')
                if new_password == confirm_password:
                    current_manager.password_hash = generate_password_hash(new_password)
                    flash('Пароль успешно изменен', 'success')
                else:
                    flash('Пароли не совпадают', 'error')
                    return redirect(url_for('mgr.manager_profile'))
            
            db.session.commit()
            flash('Профиль успешно обновлен', 'success')
            return redirect(url_for('mgr.manager_profile'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при обновлении профиля: {str(e)}', 'error')
            return redirect(url_for('mgr.manager_profile'))
    
    return render_template('auth/manager_profile.html', 
                         manager=current_manager)



@manager_bp.route('/manager/collections')
@manager_required
def manager_collections():
    """Manager collections list"""
    from models import Collection, Manager
    current_manager = current_user
    collections = Collection.query.filter_by(created_by_manager_id=current_manager.id).order_by(Collection.created_at.desc()).all()
    return render_template('manager/collections.html', collections=collections, manager=current_manager)


@manager_bp.route('/manager/collections/new')
@manager_required
def manager_create_collection():
    """Create new collection"""
    from models import Manager, User
    current_manager = current_user
    # Get all clients assigned to this manager
    clients = User.query.filter_by(assigned_manager_id=current_manager.id).all()
    return render_template('manager/create_collection.html', manager=current_manager, clients=clients)


@manager_bp.route('/manager/analytics')
@manager_required
def manager_analytics():
    """Manager analytics page"""
    from models import Manager, User, Collection, CashbackApplication
    from sqlalchemy import func
    
    current_manager = current_user
    
    # Manager stats
    clients_count = User.query.filter_by(assigned_manager_id=current_manager.id).count()
    collections_count = Collection.query.filter_by(created_by_manager_id=current_manager.id).count()
    sent_collections = Collection.query.filter_by(created_by_manager_id=current_manager.id, status='Отправлена').count()
    
    # Monthly collection stats
    monthly_collections = db.session.query(
        func.date_trunc('month', Collection.created_at).label('month'),
        func.count(Collection.id).label('count')
    ).filter_by(created_by_manager_id=current_manager.id).group_by(
        func.date_trunc('month', Collection.created_at)
    ).order_by('month').all()
    
    # Client activity stats
    client_stats = db.session.query(
        User.client_status,
        func.count(User.id).label('count')
    ).filter_by(assigned_manager_id=current_manager.id).group_by(User.client_status).all()
    
    # Recent activity
    recent_collections = Collection.query.filter_by(
        created_by_manager_id=current_manager.id
    ).order_by(Collection.created_at.desc()).limit(5).all()
    
    return render_template('manager/analytics.html',
                         manager=current_manager,
                         clients_count=clients_count,
                         collections_count=collections_count,
                         sent_collections=sent_collections,
                         monthly_collections=monthly_collections,
                         client_stats=client_stats,
                         recent_collections=recent_collections)


@manager_bp.route('/manager/search-properties', methods=['POST'])
@manager_required
def manager_search_properties():
    """Search properties for collection"""
    import json
    
    data = request.get_json()
    min_price = data.get('min_price')
    max_price = data.get('max_price')
    rooms = data.get('rooms')
    
    try:
        with open('data/properties.json', 'r', encoding='utf-8') as f:
            properties_data = json.load(f)
        
        filtered_properties = []
        for prop in properties_data:
            # Apply filters
            if min_price and prop['price'] < int(min_price):
                continue
            if max_price and prop['price'] > int(max_price):
                continue
            if rooms and str(prop['rooms']) != str(rooms):
                continue
                
            filtered_properties.append({
                'id': prop_orm.inner_id or str(prop_orm.id),
                'title': f"{prop.get('rooms', 0)}-комн {prop.get('area', 0)} м²" if prop.get('rooms', 0) > 0 else f"Студия {prop.get('area', 0)} м²",
                'price': prop['price'],
                'complex_name': prop.get('residential_complex', 'ЖК не указан'),
                'rooms': prop['rooms'],
                'size': prop.get('area', 0)
            })
        
        return jsonify({'properties': filtered_properties[:50]})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Additional API routes for collection management

@manager_bp.route('/manager/clients')
@manager_required
def manager_clients():
    """Manager clients page"""
    from models import User, Manager
    
    current_manager = current_user
    
    if not current_manager:
        return redirect(url_for('mgr.manager_login'))
    
    # Get clients assigned to this manager
    clients = User.query.filter_by(assigned_manager_id=current_manager.id).order_by(User.created_at.desc()).all()
    
    return render_template('manager/clients.html', 
                         manager=current_manager,
                         clients=clients)

# Manager Deals Management Routes  

@manager_bp.route('/manager/deals')
@manager_required
def manager_deals():
    """Manager deals page"""
    from models import User, Manager, Deal, ResidentialComplex
    from sqlalchemy import func
    
    current_manager = current_user
    
    if not current_manager:
        return redirect(url_for('mgr.manager_login'))
    
    # Get deals for this manager
    deals = Deal.query.filter_by(manager_id=current_manager.id).order_by(Deal.created_at.desc()).all()
    
    # Get clients available for this manager (assigned OR unassigned)
    # Менеджер может создавать сделки для своих клиентов и для неназначенных клиентов
    assigned_clients = User.query.filter(
        db.or_(
            User.assigned_manager_id == current_manager.id,
            User.assigned_manager_id == None
        )
    ).filter_by(role='buyer').order_by(User.full_name).all()
    
    residential_complexes = ResidentialComplex.query.order_by(ResidentialComplex.name).all()
    
    # Calculate stats
    active_deals_count = Deal.query.filter(
        Deal.manager_id == current_manager.id,
        Deal.status.in_(['new', 'reserved', 'mortgage'])
    ).count()
    
    completed_deals_count = Deal.query.filter(
        Deal.manager_id == current_manager.id,
        Deal.status == 'completed'
    ).count()
    
    in_progress_deals_count = Deal.query.filter(
        Deal.manager_id == current_manager.id,
        Deal.status.in_(['reserved', 'mortgage'])
    ).count()
    
    # Calculate total cashback
    total_cashback = db.session.query(func.sum(Deal.cashback_amount)).filter(
        Deal.manager_id == current_manager.id,
        Deal.status == 'completed'
    ).scalar() or 0
    
    return render_template('manager/deals.html',
                         manager=current_manager,
                         deals=deals,
                         assigned_clients=assigned_clients,
                         residential_complexes=residential_complexes,
                         active_deals_count=active_deals_count,
                         completed_deals_count=completed_deals_count,
                         in_progress_deals_count=in_progress_deals_count,
                         total_cashback=int(total_cashback))



@manager_bp.route('/manager/get-client/<int:client_id>')
@manager_required
@csrf.exempt
def manager_get_client(client_id):
    """Get client data for editing"""
    from models import User
    
    try:
        current_manager = current_user
        
        client = User.query.filter_by(id=client_id, assigned_manager_id=current_manager.id).first()
        
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
        
        return jsonify({
            'success': True,
            'id': client.id,
            'full_name': client.full_name or '',
            'email': client.email or '',
            'phone': client.phone or '',
            'is_active': client.is_active if hasattr(client, 'is_active') else True,
            'status': getattr(client, 'status', 'active'),
            'search_preferences': getattr(client, 'search_preferences', None),
            'profile_image': getattr(client, 'profile_image', None) or '',
            'created_at': client.created_at.isoformat() if hasattr(client, 'created_at') and client.created_at else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ================================
# DEAL MANAGEMENT API ENDPOINTS
# ================================


@manager_bp.route('/manager/deals-archive')
@manager_required
def manager_deals_archive():
    from models import Deal, Manager, OrgRole, Department
    current_manager = current_user
    role = current_manager.org_role
    is_rop = getattr(current_manager, 'is_rop', False)
    can_view_all = (role.can_view_all_archive if role else False) or is_rop
    can_view_dept = role.can_view_department_archive if role else False
    
    manager_id_filter = request.args.get('manager_id', type=int)
    status_filter = request.args.get('status', '')
    period = request.args.get('period', '')
    
    query = Deal.query.filter(Deal.status.in_(['completed', 'successful', 'rejected']))
    if can_view_all:
        if manager_id_filter:
            query = query.filter(Deal.manager_id == manager_id_filter)
    elif can_view_dept and current_manager.department_id:
        dept = Department.query.get(current_manager.department_id)
        dept_manager_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
        if manager_id_filter and manager_id_filter in dept_manager_ids:
            query = query.filter(Deal.manager_id == manager_id_filter)
        else:
            query = query.filter(Deal.manager_id.in_(dept_manager_ids))
    else:
        query = query.filter(Deal.manager_id == current_manager.id)
    
    if status_filter:
        if status_filter == 'completed':
            query = query.filter(Deal.status.in_(['completed', 'successful']))
        else:
            query = query.filter(Deal.status == status_filter)
    if period:
        from datetime import timedelta
        now = datetime.utcnow()
        periods_map = {'week': 7, 'month': 30, 'quarter': 90, 'year': 365}
        if period in periods_map:
            query = query.filter(Deal.updated_at >= now - timedelta(days=periods_map[period]))
    
    deals = query.order_by(Deal.updated_at.desc()).all()
    
    all_closed_list = deals
    
    successful = [d for d in all_closed_list if d.status in ('completed', 'successful')]
    rejected_list = [d for d in all_closed_list if d.status == 'rejected']
    total_revenue = sum(float(d.property_price or 0) for d in successful)
    total_cashback = sum(float(d.cashback_amount or 0) for d in successful)
    avg_deal = total_revenue / len(successful) if successful else 0
    conversion = round(len(successful) / len(all_closed_list) * 100, 1) if all_closed_list else 0
    
    stats = {
        'total': len(all_closed_list),
        'successful': len(successful),
        'rejected': len(rejected_list),
        'conversion': conversion,
        'total_revenue': total_revenue,
        'total_cashback': total_cashback,
        'avg_deal': avg_deal,
    }
    
    rejection_reasons = {}
    for d in rejected_list:
        reason = d.rejection_reason or 'Не указана'
        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
    rejection_stats = sorted([{'reason': r, 'count': c} for r, c in rejection_reasons.items()], key=lambda x: -x['count'])
    
    managers = []
    if can_view_all:
        managers = Manager.query.filter_by(is_active=True).order_by(Manager.first_name).all()
    elif can_view_dept and current_manager.department_id:
        dept = Department.query.get(current_manager.department_id)
        dept_ids = dept.get_all_manager_ids() if dept else []
        managers = Manager.query.filter(Manager.id.in_(dept_ids)).order_by(Manager.first_name).all()
    
    manager_stats_data = []
    if can_view_all or can_view_dept:
        if can_view_all:
            stats_managers = Manager.query.filter_by(is_active=True).all()
        else:
            dept = Department.query.get(current_manager.department_id) if current_manager.department_id else None
            dept_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
            stats_managers = Manager.query.filter(Manager.id.in_(dept_ids), Manager.is_active == True).all()
        for m in stats_managers:
            m_deals = [d for d in Deal.query.filter(Deal.manager_id == m.id, Deal.status.in_(['completed', 'successful', 'rejected'])).all()]
            if not m_deals:
                continue
            m_success = [d for d in m_deals if d.status in ('completed', 'successful')]
            m_rejected_l = [d for d in m_deals if d.status == 'rejected']
            m_revenue = sum(float(d.property_price or 0) for d in m_success)
            m_conv = round(len(m_success) / len(m_deals) * 100, 1) if m_deals else 0
            manager_stats_data.append({
                'name': m.full_name,
                'total': len(m_deals),
                'successful': len(m_success),
                'rejected': len(m_rejected_l),
                'conversion': m_conv,
                'revenue': m_revenue,
            })
        manager_stats_data.sort(key=lambda x: -x['successful'])
    
    sidebar_links, user_profile = get_manager_sidebar_data(current_manager, active_page='deals_archive')
    return render_template('manager/deals_archive.html',
                         manager=current_manager,
                         is_rop=can_view_all or can_view_dept,
                         deals=deals, stats=stats,
                         rejection_stats=rejection_stats,
                         managers=managers,
                         manager_stats=manager_stats_data,
                         sidebar_links=sidebar_links,
                         user_profile=user_profile)



@manager_bp.route('/manager/kanban')
@manager_required
def manager_deals_kanban():
    if request.args.get('view') == 'calendar':
        return redirect(url_for('mgr.manager_tasks_calendar'))
    from models import Deal, DealStageConfig, User, ResidentialComplex
    current_manager = current_user
    DealStageConfig.seed_defaults()
    stages_config = Deal.get_stages_config()
    stages_db = DealStageConfig.get_ordered_stages()
    if not stages_db:
        stages_db = []
        for i, key in enumerate(Deal.STAGE_ORDER):
            class FakeStage:
                pass
            s = FakeStage()
            s.key = key
            s.label = Deal.STAGE_LABELS.get(key, key)
            s.color = Deal.STAGE_COLORS.get(key, '#6b7280')
            s.sort_order = i
            s.is_terminal = key in ['completed', 'rejected']
            stages_db.append(s)
    from models import OrgRole, Department, Manager as ManagerModel
    role = current_manager.org_role
    can_view_all = role.can_view_all_deals if role else False
    can_view_dept = role.can_view_department_deals if role else getattr(current_manager, 'is_rop', False)
    can_change_responsible = role.can_change_deal_responsible if role else False
    
    manager_filter_id = request.args.get('manager_id', type=int)
    
    if can_view_all:
        if manager_filter_id:
            deals = Deal.query.filter_by(manager_id=manager_filter_id).all()
        else:
            deals = Deal.query.all()
    elif can_view_dept and current_manager.department_id:
        dept = Department.query.get(current_manager.department_id)
        dept_manager_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
        if manager_filter_id and manager_filter_id in dept_manager_ids:
            deals = Deal.query.filter_by(manager_id=manager_filter_id).all()
        else:
            deals = Deal.query.filter(Deal.manager_id.in_(dept_manager_ids)).all()
    elif getattr(current_manager, 'is_rop', False):
        deals = Deal.query.all()
    else:
        deals = Deal.query.filter_by(manager_id=current_manager.id).all()
    
    deals_by_stage = {}
    for deal in deals:
        if deal.status not in deals_by_stage:
            deals_by_stage[deal.status] = []
        deals_by_stage[deal.status].append(deal)
    for key in deals_by_stage:
        deals_by_stage[key].sort(key=lambda d: d.updated_at or d.created_at, reverse=True)
    total_deals = len(deals)
    assigned_clients = User.query.filter(
        db.or_(User.assigned_manager_id == current_manager.id, User.assigned_manager_id == None)
    ).filter_by(role='buyer').order_by(User.full_name).all()
    residential_complexes = ResidentialComplex.query.order_by(ResidentialComplex.name).all()
    
    viewable_managers = []
    if can_view_all:
        viewable_managers = ManagerModel.query.filter_by(is_active=True).order_by(ManagerModel.first_name).all()
    elif can_view_dept and current_manager.department_id:
        dept = Department.query.get(current_manager.department_id)
        dept_manager_ids = dept.get_all_manager_ids() if dept else []
        viewable_managers = ManagerModel.query.filter(ManagerModel.id.in_(dept_manager_ids)).order_by(ManagerModel.first_name).all()
    elif getattr(current_manager, 'is_rop', False):
        viewable_managers = ManagerModel.query.filter_by(is_active=True).order_by(ManagerModel.first_name).all()
    
    sidebar_links, user_profile = get_manager_sidebar_data(current_manager, active_page='deals')
    
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    from datetime import timedelta
    now_moscow = datetime.now(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
    today_moscow = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
    weekday = today_moscow.weekday()
    week_end_moscow = today_moscow + timedelta(days=(6 - weekday))
    week_end_moscow = week_end_moscow.replace(hour=23, minute=59, second=59)
    next_week_end_moscow = week_end_moscow + timedelta(days=7)
    
    import json as json_mod
    from models import DealTask
    all_tasks = DealTask.query.join(Deal).filter(Deal.manager_id == current_manager.id).order_by(DealTask.due_date.asc().nullslast()).all()
    calendar_stats = {
        'total': len(all_tasks),
        'active': sum(1 for t in all_tasks if not t.is_completed),
        'overdue': sum(1 for t in all_tasks if not t.is_completed and t.due_date and t.due_date < now_moscow),
        'completed': sum(1 for t in all_tasks if t.is_completed),
    }
    priority_labels = {'high': 'Высокий', 'normal': 'Обычный', 'low': 'Низкий'}
    calendar_events = []
    for t in all_tasks:
        if not t.due_date:
            continue
        if t.is_completed:
            color = '#10b981'
        elif t.due_date < now_moscow:
            color = '#ef4444'
        elif t.priority == 'high':
            color = '#6366f1'
        else:
            color = '#f59e0b'
        calendar_events.append({
            'id': 'task_' + str(t.id),
            'title': t.title,
            'start': t.due_date.isoformat(),
            'color': color,
            'extendedProps': {
                'type': 'task',
                'deal_id': t.deal_id,
                'deal_number': t.deal.deal_number if t.deal else '',
                'client_name': t.deal.client.full_name if t.deal and t.deal.client else '',
                'description': t.description or '',
                'priority_label': priority_labels.get(t.priority, 'Обычный'),
                'is_overdue': not t.is_completed and t.due_date < now_moscow,
            }
        })
    for d in deals:
        stage_cfg = {s.key: s for s in stages_db}.get(d.status)
        stage_label = stage_cfg.label if stage_cfg else d.status
        stage_color = stage_cfg.color if stage_cfg else '#0088CC'
        calendar_events.append({
            'id': 'deal_' + str(d.id),
            'title': f'{d.deal_number} — {stage_label}',
            'start': d.updated_at.isoformat() if d.updated_at else d.created_at.isoformat(),
            'color': stage_color,
            'display': 'block',
            'extendedProps': {
                'type': 'deal',
                'deal_id': d.id,
                'deal_number': d.deal_number,
                'client_name': d.client.full_name if d.client else '',
                'description': f'ЖК: {d.residential_complex.name if d.residential_complex else (d.residential_complex_name or "Не указан")}',
                'priority_label': stage_label,
            }
        })
        if d.contract_date:
            calendar_events.append({
                'id': 'contract_' + str(d.id),
                'title': f'📋 Договор {d.deal_number}',
                'start': d.contract_date.isoformat(),
                'color': '#059669',
                'display': 'block',
                'extendedProps': {
                    'type': 'deal',
                    'deal_id': d.id,
                    'deal_number': d.deal_number,
                    'client_name': d.client.full_name if d.client else '',
                    'description': 'Дата подписания договора',
                    'priority_label': 'Договор',
                }
            })
    calendar_events_json = json_mod.dumps(calendar_events, ensure_ascii=False)
    
    task_columns_data = {'overdue': [], 'today': [], 'this_week': [], 'next_week': [], 'no_tasks': []}
    today_str = today_moscow.strftime('%Y-%m-%d')
    week_end_str = week_end_moscow.strftime('%Y-%m-%d')
    next_week_end_str = next_week_end_moscow.strftime('%Y-%m-%d')
    for deal in deals:
        active_tasks = [t for t in deal.tasks.filter_by(is_completed=False).all() if t.due_date]
        no_date_tasks = [t for t in deal.tasks.filter_by(is_completed=False).all() if not t.due_date]
        if not active_tasks and not no_date_tasks:
            task_columns_data['no_tasks'].append({'deal': deal, 'task': None})
            continue
        if not active_tasks and no_date_tasks:
            task_columns_data['no_tasks'].append({'deal': deal, 'task': no_date_tasks[0]})
            continue
        deal_placed = set()
        for t in sorted(active_tasks, key=lambda x: x.due_date):
            td = t.due_date.strftime('%Y-%m-%d')
            if t.due_date < now_moscow and 'overdue' not in deal_placed:
                task_columns_data['overdue'].append({'deal': deal, 'task': t})
                deal_placed.add('overdue')
            elif td == today_str and 'today' not in deal_placed:
                task_columns_data['today'].append({'deal': deal, 'task': t})
                deal_placed.add('today')
            elif td > today_str and td <= week_end_str and 'this_week' not in deal_placed:
                task_columns_data['this_week'].append({'deal': deal, 'task': t})
                deal_placed.add('this_week')
            elif td > week_end_str and td <= next_week_end_str and 'next_week' not in deal_placed:
                task_columns_data['next_week'].append({'deal': deal, 'task': t})
                deal_placed.add('next_week')
        if not deal_placed:
            task_columns_data['no_tasks'].append({'deal': deal, 'task': active_tasks[0] if active_tasks else None})
    
    return render_template('manager/deals_kanban.html',
                         manager=current_manager, stages=stages_db,
                         deals_by_stage=deals_by_stage, total_deals=total_deals,
                         assigned_clients=assigned_clients,
                         residential_complexes=residential_complexes,
                         stages_config=stages_config,
                         sidebar_links=sidebar_links, user_profile=user_profile,
                         current_manager=current_manager,
                         can_change_responsible=can_change_responsible,
                         viewable_managers=viewable_managers,
                         now_moscow=now_moscow,
                         week_end_moscow=week_end_moscow,
                         next_week_end_moscow=next_week_end_moscow,
                         calendar_events_json=calendar_events_json,
                         calendar_stats=calendar_stats,
                         task_columns_data=task_columns_data)


@manager_bp.route('/manager/calendar')
@manager_required
def manager_tasks_calendar():
    import json as json_mod
    from models import Deal, DealTask, DealStageConfig
    current_manager = current_user
    tasks = DealTask.query.join(Deal).filter(Deal.manager_id == current_manager.id).order_by(DealTask.due_date.asc().nullslast()).all()
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
    stats = {
        'total': len(tasks),
        'active': sum(1 for t in tasks if not t.is_completed),
        'overdue': sum(1 for t in tasks if not t.is_completed and t.due_date and t.due_date < now),
        'completed': sum(1 for t in tasks if t.is_completed),
    }
    priority_labels = {'high': 'Высокий', 'normal': 'Обычный', 'low': 'Низкий'}
    events = []
    for t in tasks:
        if not t.due_date:
            continue
        if t.is_completed:
            color = '#10b981'
        elif t.due_date < now:
            color = '#ef4444'
        elif t.priority == 'high':
            color = '#6366f1'
        else:
            color = '#f59e0b'
        events.append({
            'id': 'task_' + str(t.id),
            'title': t.title,
            'start': t.due_date.isoformat(),
            'color': color,
            'extendedProps': {
                'type': 'task',
                'deal_id': t.deal_id,
                'deal_number': t.deal.deal_number if t.deal else '',
                'client_name': t.deal.client.full_name if t.deal and t.deal.client else '',
                'description': t.description or '',
                'priority_label': priority_labels.get(t.priority, 'Обычный'),
                'is_overdue': not t.is_completed and t.due_date < now,
            }
        })
    stage_configs = {s.key: s for s in DealStageConfig.query.all()}
    deals = Deal.query.filter_by(manager_id=current_manager.id).all()
    for d in deals:
        stage_cfg = stage_configs.get(d.status)
        stage_label = stage_cfg.label if stage_cfg else d.status_display if hasattr(d, 'status_display') else d.status
        stage_color = stage_cfg.color if stage_cfg else '#0088CC'
        events.append({
            'id': 'deal_' + str(d.id),
            'title': f'{d.deal_number} — {stage_label}',
            'start': d.updated_at.isoformat() if d.updated_at else d.created_at.isoformat(),
            'color': stage_color,
            'display': 'block',
            'extendedProps': {
                'type': 'deal',
                'deal_id': d.id,
                'deal_number': d.deal_number,
                'client_name': d.client.full_name if d.client else '',
                'description': f'ЖК: {d.residential_complex.name if d.residential_complex else (d.residential_complex_name or "Не указан")}',
                'priority_label': stage_label,
            }
        })
        if d.contract_date:
            events.append({
                'id': 'contract_' + str(d.id),
                'title': f'📋 Договор {d.deal_number}',
                'start': d.contract_date.isoformat(),
                'color': '#059669',
                'display': 'block',
                'extendedProps': {
                    'type': 'deal',
                    'deal_id': d.id,
                    'deal_number': d.deal_number,
                    'client_name': d.client.full_name if d.client else '',
                    'description': 'Дата подписания договора',
                    'priority_label': 'Договор',
                }
            })
    tasks_json = json_mod.dumps(events, ensure_ascii=False)
    sidebar_links, user_profile = get_manager_sidebar_data(current_manager, active_page='deals')
    return render_template('manager/tasks_calendar.html',
                         manager=current_manager, stats=stats, tasks_json=tasks_json,
                         sidebar_links=sidebar_links, user_profile=user_profile,
                         current_manager=current_manager)


@manager_bp.route('/manager/deals/<int:deal_id>')
@manager_required
def manager_deal_card(deal_id):
    try:
        from models import Deal, DealComment, DealTask, DealHistory, User, ResidentialComplex, OrgRole, Department, Manager as ManagerModel
        current_manager = current_user
        deal = Deal.query.get(deal_id)
        if not deal:
            return redirect(url_for('mgr.manager_deals'))
        role = current_manager.org_role
        can_view_all = (role.can_view_all_deals if role else False) or getattr(current_manager, 'is_rop', False)
        can_view_dept = role.can_view_department_deals if role else False
        can_change_responsible = (role.can_change_deal_responsible if role else False) or getattr(current_manager, 'is_rop', False)
        is_own = deal.manager_id == current_manager.id
        can_view = is_own or can_view_all
        if not can_view and can_view_dept and current_manager.department_id:
            dept = Department.query.get(current_manager.department_id)
            can_view = deal.manager_id in (dept.get_all_manager_ids() if dept else [])
        if not can_view:
            return redirect(url_for('mgr.manager_deals'))
        comments = DealComment.query.filter_by(deal_id=deal.id).order_by(DealComment.created_at.desc()).all()
        tasks = DealTask.query.filter_by(deal_id=deal.id).order_by(DealTask.is_completed, DealTask.due_date.asc().nullslast(), DealTask.created_at.desc()).all()
        history = DealHistory.query.filter_by(deal_id=deal.id).order_by(DealHistory.created_at.desc()).all()
        activity = []
        for c in comments:
            activity.append({'type': 'comment', 'id': c.id, 'text': c.text, 'author': c.author.full_name or c.author.email if c.author else 'Менеджер', 'created_at': c.created_at, 'is_pinned': c.is_pinned})
        for h in history:
            activity.append({'type': 'history', 'id': h.id, 'action': h.action, 'description': h.description, 'author': h.author.full_name or h.author.email if h.author else 'Система', 'created_at': h.created_at, 'old_value': h.old_value, 'new_value': h.new_value})
        activity.sort(key=lambda x: x['created_at'], reverse=True)
        residential_complexes = ResidentialComplex.query.order_by(ResidentialComplex.name).all()
        assigned_clients = User.query.filter(db.or_(User.assigned_manager_id == current_manager.id, User.assigned_manager_id == None)).filter_by(role='buyer').order_by(User.full_name).all()
        stages_config = Deal.get_stages_config()
        sidebar_links, user_profile = get_manager_sidebar_data(current_manager, active_page='deals')
        available_managers = []
        if can_change_responsible:
            if can_view_all:
                available_managers = ManagerModel.query.filter_by(is_active=True).order_by(ManagerModel.first_name).all()
            elif current_manager.department_id:
                dept = Department.query.get(current_manager.department_id)
                dept_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
                available_managers = ManagerModel.query.filter(ManagerModel.id.in_(dept_ids), ManagerModel.is_active == True).order_by(ManagerModel.first_name).all()
            else:
                available_managers = ManagerModel.query.filter_by(is_active=True).order_by(ManagerModel.first_name).all()
        
        return render_template('manager/deal_card.html',
                             deal=deal, manager=current_manager, comments=comments,
                             tasks=tasks, history=history, activity=activity,
                             residential_complexes=residential_complexes,
                             assigned_clients=assigned_clients,
                             stages=stages_config['order'], stage_labels=stages_config['labels'],
                             stage_colors=stages_config['colors'],
                             hasattr=hasattr,
                             sidebar_links=sidebar_links, user_profile=user_profile,
                             current_manager=current_manager,
                             can_change_responsible=can_change_responsible,
                             available_managers=available_managers)
    except Exception as e:
        logging.error(f"Error in manager_deal_card: {str(e)}")
        logging.error(traceback.format_exc())
        return str(e), 500



@manager_bp.route('/manager/edit-client', methods=['POST'])
@csrf.exempt
@manager_required
def manager_edit_client():
    """Edit existing client"""
    from models import User
    
    current_manager = current_user
    
    try:
        client_id = request.form.get('client_id')
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        is_active = 'is_active' in request.form
        
        if not client_id:
            return jsonify({'success': False, 'error': 'ID клиента не указан'}), 400
        
        # Try to find client assigned to this manager first, then any buyer
        client = User.query.filter_by(id=client_id, assigned_manager_id=current_manager.id).first()
        if not client:
            client = User.query.filter_by(id=client_id, role='buyer').first()
        
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
        
        if not all([full_name, email]):
            return jsonify({'success': False, 'error': 'Заполните обязательные поля'}), 400
        
        # Check if email already exists (excluding current client)
        existing_user = User.query.filter(User.email == email, User.id != client_id).first()
        if existing_user:
            return jsonify({'success': False, 'error': 'Пользователь с таким email уже существует'}), 400
        
        # Check if phone already exists (excluding current client, normalized like registration)
        if phone:
            import re as re_mod
            from sqlalchemy import func as sqlfunc
            phone_digits = re_mod.sub(r'[^0-9]', '', phone)
            existing_phone_user = User.query.filter(
                sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits,
                User.id != int(client_id)
            ).first()
            if existing_phone_user:
                return jsonify({'success': False, 'error': 'Пользователь с таким номером телефона уже существует'}), 400
        
        # Update client data
        client.full_name = _capitalize_name(full_name)
        client.email = email
        client.phone = phone
        client.is_active = is_active
        client.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@manager_bp.route('/manager/delete-client', methods=['POST'])
@csrf.exempt
@manager_required
def manager_delete_client():
    """Delete client"""
    from models import User
    
    current_manager = current_user
    
    try:
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            data = request.get_json()
            client_id = data.get('client_id')
        else:
            client_id = request.form.get('client_id')
        
        if not client_id:
            return jsonify({'success': False, 'error': 'ID клиента не указан'}), 400
        
        # Try to find client assigned to this manager first, then any buyer
        client = User.query.filter_by(id=client_id, assigned_manager_id=current_manager.id).first()
        if not client:
            client = User.query.filter_by(id=client_id, role='buyer').first()
        
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
        
        # Instead of deleting, mark as inactive
        client.is_active = False
        client.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@manager_bp.route('/manager/employees')
@manager_required
def manager_employees():
    from models import Manager, Department, OrgRole, ManagerCheckin, Deal, DealHistory
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    
    current_manager = current_user
    role = current_manager.org_role
    can_view_all = (role.can_view_all_deals if role else False)
    can_view_dept = (role.can_view_department_deals if role else False)
    is_rop = getattr(current_manager, 'is_rop', False) or can_view_dept or can_view_all
    
    now_msk = datetime.now(ZoneInfo('Europe/Moscow'))
    today = now_msk.date()
    
    if can_view_all:
        managers = Manager.query.filter_by(is_active=True).order_by(Manager.first_name).all()
    elif can_view_dept or is_rop:
        if current_manager.department_id:
            dept = Department.query.get(current_manager.department_id)
            dept_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
            managers = Manager.query.filter(Manager.id.in_(dept_ids), Manager.is_active == True).order_by(Manager.first_name).all()
        else:
            managers = [current_manager]
    else:
        if current_manager.department_id:
            dept = Department.query.get(current_manager.department_id)
            dept_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
            managers = Manager.query.filter(Manager.id.in_(dept_ids), Manager.is_active == True).order_by(Manager.first_name).all()
        else:
            managers = [current_manager]
    
    employees_data = []
    for m in managers:
        today_checkins = ManagerCheckin.query.filter_by(manager_id=m.id, date=today).order_by(ManagerCheckin.check_in_time).all()
        total_minutes_today = sum(c.duration_minutes for c in today_checkins)
        hours = total_minutes_today // 60
        mins = total_minutes_today % 60
        is_currently_active = any(c.is_active for c in today_checkins)
        
        active_deals = Deal.query.filter(Deal.manager_id == m.id, Deal.status.in_(['active', 'new'])).count()
        
        recent_activities = DealHistory.query.filter_by(author_id=m.id).order_by(DealHistory.created_at.desc()).limit(5).all()
        
        last_login = getattr(m, 'last_login', None) or getattr(m, 'last_login_at', None)
        
        dept_name = m.department.name if m.department else None
        role_name = m.org_role.name if m.org_role else None
        
        employees_data.append({
            'manager': m,
            'is_currently_active': is_currently_active,
            'today_time': f'{hours}ч {mins}м' if hours > 0 else f'{mins}м',
            'active_deals': active_deals,
            'recent_activities': recent_activities,
            'last_login': last_login,
            'department': dept_name,
            'role': role_name,
            'first_checkin': today_checkins[0].check_in_time if today_checkins else None,
        })
    
    sidebar_links, user_profile = get_manager_sidebar_data(current_manager, active_page='employees')

    all_departments = Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()
    root_departments = [d for d in all_departments if d.parent_id is None]

    return render_template('manager/employees.html',
                         employees_data=employees_data,
                         current_manager=current_manager,
                         is_rop=is_rop,
                         today=today,
                         sidebar_links=sidebar_links,
                         user_profile=user_profile,
                         manager=current_manager,
                         root_departments=root_departments,
                         all_departments=all_departments)



@manager_bp.route('/manager/employee/<int:manager_id>')
@manager_required
def manager_employee_profile(manager_id):
    from models import Manager, Department, OrgRole, Deal, DealHistory, DealTask, User, ManagerCheckin
    from datetime import datetime, timedelta
    import pytz
    
    current_manager = current_user
    employee = Manager.query.get_or_404(manager_id)
    
    role = current_manager.org_role
    can_view_all = role.can_view_all_deals if role else False
    can_view_dept = role.can_view_department_deals if role else False
    
    if not can_view_all and employee.id != current_manager.id:
        if can_view_dept and current_manager.department_id:
            dept = Department.query.get(current_manager.department_id)
            dept_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
            if employee.id not in dept_ids:
                flash('Нет доступа к профилю этого сотрудника', 'error')
                return redirect(url_for('mgr.manager_employees'))
        elif not can_view_dept or not current_manager.department_id:
            flash('Нет доступа к профилю этого сотрудника', 'error')
            return redirect(url_for('mgr.manager_employees'))
    
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
    
    stats = {
        'active_deals': active_deals,
        'completed_deals': completed_deals,
        'clients': clients,
        'pending_tasks': pending_tasks
    }
    
    subordinates = []
    if employee.department_id:
        dept = Department.query.get(employee.department_id)
        if dept and dept.head_manager_id == employee.id:
            subordinates = Manager.query.filter(
                Manager.department_id == employee.department_id,
                Manager.id != employee.id,
                Manager.is_active == True
            ).all()
    
    supervisor = None
    if employee.department_id:
        dept = Department.query.get(employee.department_id)
        if dept and dept.head_manager_id and dept.head_manager_id != employee.id:
            supervisor = Manager.query.get(dept.head_manager_id)
    
    from datetime import timedelta
    recent_activities = []
    week_ago = datetime.utcnow() - timedelta(days=7)
    histories = DealHistory.query.join(Deal).filter(
        Deal.manager_id == employee.id,
        DealHistory.created_at >= week_ago
    ).order_by(DealHistory.created_at.desc()).limit(10).all()
    for h in histories:
        recent_activities.append({
            'action': h.action,
            'description': h.description,
            'created_at': h.created_at
        })
    
    sidebar_links, user_profile = get_manager_sidebar_data(current_manager, active_page='employees')
    
    return render_template('manager/employee_profile.html',
                         employee=employee,
                         emp_role=emp_role,
                         emp_department=emp_department,
                         is_online=is_online,
                         stats=stats,
                         subordinates=subordinates,
                         supervisor=supervisor,
                         recent_activities=recent_activities,
                         sidebar_links=sidebar_links,
                         user_profile=user_profile)


