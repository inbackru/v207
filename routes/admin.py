"""
Admin Blueprint — admin panel routes.
All /admin/* endpoints extracted from app.py.
"""
import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Scripts live in <project_root>/scripts/, one level up from this routes/ directory
_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts')


def _load_city_config_live() -> dict:
    """Load and normalize city config from disk every call so newly added cities are visible immediately."""
    import json as _json
    _cfg_path = os.path.join(_SCRIPTS_DIR, 'city_config.json')
    try:
        with open(_cfg_path, encoding='utf-8') as _f:
            _raw = _json.load(_f)
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
        from app import CITY_CONFIG_ALL
        return CITY_CONFIG_ALL

from flask import (Blueprint, abort, flash, jsonify, make_response,
                   redirect, render_template, request, send_file,
                   session, url_for, current_app)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import text

from app import db, csrf, admin_required, manager_required

admin_bp = Blueprint('adm', __name__)


def _capitalize_name(name):
    """Capitalize each word of a name (supports Cyrillic)."""
    if not name:
        return ''
    return ' '.join(w.capitalize() for w in name.strip().split())


def _normalize_phone(phone):
    """Normalize phone to +7 (XXX) XXX-XX-XX format."""
    import re
    if not phone:
        return phone or ''
    digits = re.sub(r'\D', '', phone)
    if len(digits) > 0 and digits[0] in ('7', '8'):
        digits = digits[1:]
    if len(digits) == 10:
        return f'+7 ({digits[:3]}) {digits[3:6]}-{digits[6:8]}-{digits[8:10]}'
    return phone


@admin_bp.route('/admin/coordinates')
def admin_coordinates():
    """Административная панель для редактирования координат районов"""
    from models import District
    
    # Получаем все районы
    districts = District.query.order_by(District.name).all()
    
    return render_template('admin/coordinates.html', 
                         districts=districts,
                         yandex_api_key=os.environ.get('YANDEX_MAPS_API_KEY'))


@admin_bp.route('/admin/update-coordinates', methods=['POST'])
@csrf.exempt
def admin_update_coordinates():
    """API для обновления координат района"""
    from models import District
    import math
    
    try:
        district_id = request.form.get('district_id')
        latitude = float(request.form.get('latitude'))
        longitude = float(request.form.get('longitude'))
        
        # Вычисляем расстояние до центра
        theater_lat, theater_lon = 45.035180, 38.977414
        
        def haversine_distance(lat1, lon1, lat2, lon2):
            R = 6371
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
            c = 2 * math.asin(math.sqrt(a))
            return R * c
        
        distance = haversine_distance(latitude, longitude, theater_lat, theater_lon)
        
        # Обновляем координаты
        district = District.query.get(district_id)
        if district:
            district.latitude = latitude
            district.longitude = longitude
            district.distance_to_center = distance
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Координаты района {district.name} обновлены',
                'distance': round(distance, 1)
            })
        else:
            return jsonify({'success': False, 'message': 'Район не найден'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ========================================
# АЛИАСЫ ДЛЯ СТАРЫХ URL РАЙОНОВ
# ========================================


@admin_bp.route('/admin/login', methods=['GET', 'POST'])
@csrf.exempt  # Exempt admin login from CSRF protection
def admin_login():
    """Admin login page - ИСПРАВЛЕНО: использует Flask-Login"""
    if request.method == 'POST':
        from models import Admin
        email = request.form.get('email')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(email=email, is_active=True).first()
        
        if admin and admin.check_password(password):
            # Используем Flask-Login вместо ручных сессий
            login_user(admin, remember=True)
            session.permanent = True  # Ensure 30-day session lifetime
            
            # Update last login data for Admin
            now = datetime.utcnow()
            ip = request.remote_addr
            ua = request.headers.get('User-Agent')
            
            admin.last_login = now
            admin.last_ip = ip
            admin.last_user_agent = ua
            
            # Cross-update Manager record with same email if exists
            from models import Manager
            manager = Manager.query.filter_by(email=email).first()
            if manager:
                manager.last_login = now
                manager.last_ip = ip
                manager.last_user_agent = ua
                
            db.session.commit()
            flash('Добро пожаловать в панель администратора!', 'success')
            return redirect(url_for('adm.admin_dashboard'))
        else:
            flash('Неверный email или пароль', 'error')
    
    return render_template('admin/admin_login.html')


@admin_bp.route('/admin/logout')
def admin_logout():
    """Admin logout - ИСПРАВЛЕНО: использует Flask-Login"""
    logout_user()  # Используем Flask-Login
    flash('Вы вышли из панели администратора', 'info')
    return redirect(url_for('adm.admin_login'))


@admin_bp.route('/admin')
def admin_base():
    """Base admin route - redirects to dashboard or login - ИСПРАВЛЕНО: проверяет тип модели"""
    from models import Admin
    # Проверяем что пользователь авторизован и это Admin
    if current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin):
        return redirect(url_for('adm.admin_dashboard'))
    return redirect(url_for('adm.admin_login'))


@admin_bp.route('/admin/client-management')
@admin_required
def admin_client_management():
    """Separate page for client-manager assignment"""
    try:
        from models import Admin
        
        # ИСПРАВЛЕНО: Используем Flask-Login current_user
        current_admin = current_user
        if not current_admin:
            flash('Админ не найден', 'error')
            return redirect(url_for('adm.admin_login'))
        
        return render_template('admin/client_management.html', admin=current_admin)
        
    except Exception as e:
        print(f"ERROR in admin_client_management: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Ошибка загрузки страницы: {str(e)}', 'error')
        return redirect(url_for('adm.admin_dashboard'))


@admin_bp.route('/admin/scheduler')
@admin_required
def admin_scheduler():
    from routes.admin_api import scheduler
    current_admin = current_user
    jobs_info = []
    is_running = scheduler.running
    
    import pytz
    moscow_tz = pytz.timezone('Europe/Moscow')
    
    if is_running:
        for job in scheduler.get_jobs():
            next_run = job.next_run_time
            if next_run:
                # Конвертируем время следующего запуска в московское для отображения
                next_run_display = next_run.astimezone(moscow_tz).strftime('%d.%m.%Y %H:%M:%S')
            else:
                next_run_display = 'Не запланировано'
                
            jobs_info.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run_display,
                'trigger': str(job.trigger),
            })
    return render_template('admin/scheduler.html', admin=current_admin, 
                         is_running=is_running, jobs=jobs_info)


@admin_bp.route('/admin/scheduler/run-job', methods=['POST'])
@admin_required
def admin_scheduler_run_job():
    from routes.admin_api import (run_task_reminders, run_overdue_task_alerts, run_instant_alerts,
                     run_daily_digest, run_weekly_digest, run_record_price_history,
                     run_auto_geocode, run_sitemap_ping, run_enrichment_job,
                     run_daily_price_update, run_update_complex_distances,
                     run_infrastructure_update_job as run_infrastructure_update,
                     run_update_complex_nearby,
                     run_tg_promo_parser, run_cleanup_vanished_properties,
                     run_deactivate_stale_properties)
    job_id = request.form.get('job_id')
    job_map = {
        'task_reminders_job':       run_task_reminders,
        'overdue_task_alerts_job':  run_overdue_task_alerts,
        'instant_alerts_job':       run_instant_alerts,
        'daily_digest_job':         run_daily_digest,
        'weekly_digest_job':        run_weekly_digest,
        'price_history_job':        run_record_price_history,
        'auto_geocode_job':         run_auto_geocode,
        'sitemap_ping_job':         run_sitemap_ping,
        'cian_enrichment_job':      run_enrichment_job,
        'cian_daily_price_job':     run_daily_price_update,
        'complex_distances_job':    run_update_complex_distances,
        'infrastructure_update_job': run_infrastructure_update,
        'complex_nearby_job':        run_update_complex_nearby,
        'tg_promo_parser_job':       run_tg_promo_parser,
        'cleanup_vanished_job':      run_cleanup_vanished_properties,
        'deactivate_stale_job':      run_deactivate_stale_properties,
    }
    func = job_map.get(job_id)
    if func:
        try:
            func()
            flash(f'✅ Задача выполнена успешно', 'success')
        except Exception as e:
            flash(f'❌ Ошибка: {str(e)}', 'error')
    else:
        flash('Неизвестная задача', 'error')
    return redirect(url_for('adm.admin_scheduler'))



def _auto_assign_districts_for_city(city_id):
    """
    Universal district assignment for one city (idempotent, overwrites existing).

    Step 1 — PIP: try point-in-polygon for every district that has polygon geometry.
              Smaller bbox districts are tested first (microrayons before city-spanning okrugs).
    Step 2 — Nearest-neighbour fallback for unmatched properties:
              Prefer districts WITH polygon geometry (okrugs) over centroid-only districts
              (microrayons without geometry). If all districts lack geometry, use any centroid.

    Returns (pip_count, nn_count).
    """
    import math
    from utils.geo import point_in_geometry as _pip_check, geometry_bbox

    dist_rows = db.session.execute(text(
        "SELECT id, name, latitude, longitude, geometry FROM districts "
        "WHERE city_id=:cid AND latitude IS NOT NULL AND longitude IS NOT NULL"
    ), {'cid': city_id}).fetchall()

    if not dist_rows:
        return 0, 0

    # Build polygon district list — sort by bbox area ascending (smallest = most specific first)
    poly_dists = []
    for r in dist_rows:
        if r.geometry and len(r.geometry) > 10:
            try:
                bb = geometry_bbox(r.geometry)
                area = (bb[2] - bb[0]) * (bb[3] - bb[1]) if bb else 9999
            except Exception:
                area = 9999
            poly_dists.append((r.id, r.geometry, area))
    poly_dists.sort(key=lambda x: x[2])

    # For NN fallback: prefer districts with polygon geometry (higher-level admin boundaries)
    # Fall back to centroid-only districts only if no polygon districts exist
    poly_centroids = [(r.id, float(r.latitude), float(r.longitude))
                      for r in dist_rows if r.geometry and len(r.geometry) > 10]
    all_centroids  = [(r.id, float(r.latitude), float(r.longitude)) for r in dist_rows]
    nn_pool = poly_centroids if poly_centroids else all_centroids

    props = db.session.execute(text(
        "SELECT id, latitude, longitude FROM properties "
        "WHERE city_id=:cid AND is_active=true "
        "AND latitude IS NOT NULL AND longitude IS NOT NULL"
    ), {'cid': city_id}).fetchall()

    if not props:
        return 0, 0

    pip_updates, nn_updates = [], []

    for prop in props:
        lat, lng = float(prop.latitude), float(prop.longitude)
        matched_id = None

        for did, geom, _area in poly_dists:
            try:
                if _pip_check(lat, lng, geom):
                    matched_id = did
                    break
            except Exception:
                pass

        if matched_id is not None:
            pip_updates.append({'did': matched_id, 'pid': prop.id})
        else:
            matched_id = min(nn_pool, key=lambda d: (lat - d[1])**2 + (lng - d[2])**2)[0]
            nn_updates.append({'did': matched_id, 'pid': prop.id})

    all_updates = pip_updates + nn_updates
    for i in range(0, len(all_updates), 2000):
        db.session.execute(
            text('UPDATE properties SET district_id=:did WHERE id=:pid'),
            all_updates[i:i + 2000]
        )
    if all_updates:
        db.session.commit()

    return len(pip_updates), len(nn_updates)


@admin_bp.route('/admin/districts/auto-assign', methods=['POST'])
@admin_required
def admin_districts_auto_assign():
    """Universal district auto-assignment: PIP + nearest-neighbour for all cities or one."""
    data = request.get_json(silent=True) or {}
    raw_cid = data.get('city_id')
    city_id = int(raw_cid) if raw_cid else None

    from models import City as _City
    if city_id:
        cities = _City.query.filter_by(id=city_id).all()
    else:
        cities = _City.query.filter_by(is_active=True).all()

    total_pip = total_nn = 0
    details = []
    errors = []
    for city in cities:
        try:
            pip_c, nn_c = _auto_assign_districts_for_city(city.id)
            total_pip += pip_c
            total_nn  += nn_c
            if pip_c + nn_c:
                details.append(f'{city.name}: {pip_c} по полигону + {nn_c} по ближайшему')
        except Exception as _e:
            errors.append(f'{city.name}: {_e}')

    msg = f'Назначено {total_pip + total_nn} объектов ({total_pip} PIP + {total_nn} nearest-neighbour)'
    if errors:
        msg += '; ошибки: ' + '; '.join(errors)
    return jsonify({'success': True, 'message': msg, 'details': details})


@admin_bp.route('/admin/geo/assign-districts', methods=['POST'])
@admin_required
def admin_assign_districts():
    """Bulk-assign properties to nearest district centroid (idempotent)."""
    import math
    from collections import defaultdict

    city_id = request.form.get('city_id', type=int)
    try:
        rows = db.session.execute(text(
            'SELECT id, city_id, latitude, longitude FROM districts '
            'WHERE latitude IS NOT NULL AND longitude IS NOT NULL'
            + (' AND city_id = :cid' if city_id else '')
        ), {'cid': city_id} if city_id else {}).fetchall()

        city_districts = defaultdict(list)
        for did, cid, lat, lng in rows:
            city_districts[cid].append((did, float(lat), float(lng)))

        total_updated = 0
        for cid, dists in city_districts.items():
            props = db.session.execute(text(
                'SELECT id, latitude, longitude FROM properties '
                'WHERE is_active=true AND city_id=:cid '
                'AND latitude IS NOT NULL AND longitude IS NOT NULL'
            ), {'cid': cid}).fetchall()

            updates = []
            for pid, plat, plng in props:
                plat, plng = float(plat), float(plng)
                best_did = min(dists, key=lambda d: (plat-d[1])**2 + (plng-d[2])**2)[0]
                updates.append({'did': best_did, 'pid': pid})

            for batch_start in range(0, len(updates), 2000):
                batch = updates[batch_start:batch_start+2000]
                db.session.execute(text(
                    'UPDATE properties SET district_id=:did WHERE id=:pid'
                ), batch)
            db.session.commit()
            total_updated += len(updates)

        flash(f'✅ Привязано {total_updated} объектов к районам', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Ошибка: {str(e)}', 'error')
    return redirect(url_for('adm.admin_scheduler'))


@admin_bp.route('/admin/geo/enrich-yandex', methods=['POST'])
@admin_required
def admin_geo_enrich_yandex():
    """Enrich streets/districts missing geometry using Yandex Geocoder."""
    from utils.geo import enrich_streets_with_yandex, enrich_districts_with_yandex
    city_name = request.form.get('city_name', 'Краснодар')
    entity = request.form.get('entity', 'streets')
    limit = request.form.get('limit', 50, type=int)
    try:
        if entity == 'districts':
            count = enrich_districts_with_yandex(city_name)
        else:
            count = enrich_streets_with_yandex(city_name, limit=limit)
        flash(f'✅ Обогащено {count} записей ({entity}) для {city_name}', 'success')
    except Exception as e:
        flash(f'❌ Ошибка: {str(e)}', 'error')
    return redirect(url_for('adm.admin_scheduler'))


@admin_bp.route('/admin/scheduler/reschedule', methods=['POST'])
@admin_required
def admin_scheduler_reschedule():
    """Reschedule a job to a new cron time."""
    job_id = request.form.get('job_id', '').strip()
    hour = request.form.get('hour', '').strip()
    minute = request.form.get('minute', '0').strip()

    if not job_id or not hour:
        flash('Укажите задачу и час запуска', 'error')
        return redirect(url_for('adm.admin_scheduler'))

    try:
        hour = int(hour)
        minute = int(minute)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError('Invalid time')
    except (ValueError, TypeError):
        flash('Некорректное время (часы: 0–23, минуты: 0–59)', 'error')
        return redirect(url_for('adm.admin_scheduler'))

    try:
        from routes.admin_api import scheduler
        from apscheduler.triggers.cron import CronTrigger
        job = scheduler.get_job(job_id)
        if job is None:
            flash(f'Задача {job_id} не найдена в планировщике', 'error')
            return redirect(url_for('adm.admin_scheduler'))
        scheduler.reschedule_job(job_id, trigger=CronTrigger(hour=hour, minute=minute))
        flash(f'✅ Время задачи изменено на {hour:02d}:{minute:02d}', 'success')
    except Exception as e:
        flash(f'❌ Ошибка изменения расписания: {str(e)}', 'error')

    return redirect(url_for('adm.admin_scheduler'))



@admin_bp.route('/admin/parse-jk-by-url', methods=['GET', 'POST'])
@admin_required
def admin_parse_jk_by_url():
    """Парсинг конкретного ЖК с ЦИАН по URL."""
    result = None
    error = None
    if request.method == 'POST':
        jk_url = request.form.get('jk_url', '').strip()
        city_id = request.form.get('city_id', '1')
        if not jk_url:
            error = 'Введите URL ЖК'
        else:
            try:
                import subprocess, sys
                script = os.path.join(_SCRIPTS_DIR, 'parse_jk_by_url.py')
                proc = subprocess.run(
                    [sys.executable, script, jk_url, city_id],
                    capture_output=True, text=True, timeout=120,
                    env={**os.environ}
                )
                output = proc.stdout + proc.stderr
                if proc.returncode == 0 or 'Готово' in output:
                    result = output
                    flash('ЖК успешно спарсен!', 'success')
                else:
                    error = output or 'Ошибка при парсинге'
            except subprocess.TimeoutExpired:
                error = 'Таймаут — парсинг занял более 2 минут'
            except Exception as e:
                error = str(e)

    from models import City
    cities = City.query.order_by(City.name).all()
    return render_template('admin/parse_jk_by_url.html',
                           admin=current_user, result=result, error=error, cities=cities)



@admin_bp.route('/admin/deal-stages')
@admin_required
def admin_deal_stages():
    from models import Admin, DealStageConfig
    current_admin = current_user
    DealStageConfig.seed_defaults()
    stages = DealStageConfig.query.order_by(DealStageConfig.sort_order).all()
    return render_template('admin/deal_stages.html', admin=current_admin, stages=stages)


@admin_bp.route('/admin/deal-stages/save', methods=['POST'])
@admin_required
def admin_deal_stages_save():
    from models import DealStageConfig
    stage_id = request.form.get('stage_id')
    key = request.form.get('key', '').strip().lower()
    label = request.form.get('label', '').strip()
    color = request.form.get('color', '#6b7280').strip()
    sort_order = int(request.form.get('sort_order', 0))
    is_terminal = 'is_terminal' in request.form
    is_success = 'is_success' in request.form
    is_active = 'is_active' in request.form
    if not key or not label:
        flash('Заполните ключ и название', 'error')
        return redirect(url_for('adm.admin_deal_stages'))
    if stage_id:
        stage = DealStageConfig.query.get(int(stage_id))
        if stage:
            stage.label = label
            stage.color = color
            stage.sort_order = sort_order
            stage.is_terminal = is_terminal
            stage.is_success = is_success
            stage.is_active = is_active
            db.session.commit()
            flash(f'Этап "{label}" обновлён', 'success')
    else:
        existing = DealStageConfig.query.filter_by(key=key).first()
        if existing:
            flash(f'Этап с ключом "{key}" уже существует', 'error')
            return redirect(url_for('adm.admin_deal_stages'))
        stage = DealStageConfig(key=key, label=label, color=color, sort_order=sort_order,
                               is_terminal=is_terminal, is_success=is_success, is_active=is_active)
        db.session.add(stage)
        db.session.commit()
        flash(f'Этап "{label}" добавлен', 'success')
    return redirect(url_for('adm.admin_deal_stages'))


@admin_bp.route('/admin/deal-stages/move', methods=['POST'])
@admin_required
def admin_deal_stages_move():
    from models import DealStageConfig
    stage_id = int(request.form.get('stage_id', 0))
    direction = request.form.get('direction', 'up')
    stage = DealStageConfig.query.get(stage_id)
    if not stage:
        flash('Этап не найден', 'error')
        return redirect(url_for('adm.admin_deal_stages'))
    if direction == 'up' and stage.sort_order > 0:
        swap = DealStageConfig.query.filter_by(sort_order=stage.sort_order - 1).first()
        if swap:
            swap.sort_order, stage.sort_order = stage.sort_order, swap.sort_order
    elif direction == 'down':
        swap = DealStageConfig.query.filter_by(sort_order=stage.sort_order + 1).first()
        if swap:
            swap.sort_order, stage.sort_order = stage.sort_order, swap.sort_order
    db.session.commit()
    return redirect(url_for('adm.admin_deal_stages'))


@admin_bp.route('/admin/deal-stages/<int:stage_id>/delete', methods=['POST'])
@admin_required
def admin_deal_stages_delete(stage_id):
    from models import DealStageConfig
    stage = DealStageConfig.query.get(stage_id)
    if not stage:
        flash('Этап не найден', 'error')
    elif stage.is_terminal:
        flash('Нельзя удалить финальный этап', 'error')
    else:
        label = stage.label
        db.session.delete(stage)
        db.session.commit()
        flash(f'Этап "{label}" удалён', 'success')
    return redirect(url_for('adm.admin_deal_stages'))




@admin_bp.route('/admin/org-tree')
@admin_required
def admin_org_tree():
    from models import Department, OrgRole, Manager
    OrgRole.seed_defaults()
    departments = Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()
    roles = OrgRole.query.filter_by(is_active=True).order_by(OrgRole.level.desc()).all()
    managers = Manager.query.filter_by(is_active=True).order_by(Manager.first_name).all()
    return render_template('admin/org_tree.html',
                         admin=current_user,
                         departments=departments,
                         roles=roles,
                         managers=managers)



@admin_bp.route('/admin/api/departments', methods=['POST'])
@admin_bp.route('/admin/api/departments/<int:dept_id>', methods=['POST'])
@csrf.exempt
@admin_required
def admin_api_departments(dept_id=None):
    from models import Department, Manager
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'success': False, 'error': 'Название обязательно'})
    
    if dept_id:
        dept = Department.query.get(dept_id)
        if not dept:
            return jsonify({'success': False, 'error': 'Отдел не найден'})
    else:
        dept = Department()
        db.session.add(dept)
    
    dept.name = data['name'].strip()
    dept.description = data.get('description', '').strip() or None
    dept.parent_id = int(data['parent_id']) if data.get('parent_id') else None
    dept.head_manager_id = int(data['head_manager_id']) if data.get('head_manager_id') else None
    
    db.session.commit()
    return jsonify({'success': True})



@admin_bp.route('/admin/api/departments/<int:dept_id>', methods=['DELETE'])
@csrf.exempt
@admin_required
def admin_api_delete_department(dept_id):
    from models import Department, Manager
    dept = Department.query.get(dept_id)
    if not dept:
        return jsonify({'success': False, 'error': 'Отдел не найден'})
    
    Manager.query.filter_by(department_id=dept_id).update({'department_id': None})
    for child in dept.children.all():
        child.parent_id = dept.parent_id
    
    dept.is_active = False
    db.session.commit()
    return jsonify({'success': True})



@admin_bp.route('/admin/api/managers/assign', methods=['POST'])
@csrf.exempt
@admin_required
def admin_api_assign_manager():
    from models import Manager
    data = request.get_json()
    manager_id = data.get('manager_id')
    if not manager_id:
        return jsonify({'success': False, 'error': 'Менеджер не указан'})
    
    manager = Manager.query.get(int(manager_id))
    if not manager:
        return jsonify({'success': False, 'error': 'Менеджер не найден'})
    
    manager.department_id = int(data['department_id']) if data.get('department_id') else None
    manager.org_role_id = int(data['org_role_id']) if data.get('org_role_id') else None
    
    from models import OrgRole
    if manager.org_role_id:
        role = OrgRole.query.get(manager.org_role_id)
        if role and role.key == 'rop':
            manager.is_rop = True
        else:
            manager.is_rop = False
    
    db.session.commit()
    return jsonify({'success': True})



@admin_bp.route('/admin/api/roles/<int:role_id>', methods=['GET'])
@admin_required
def admin_api_role_get(role_id):
    from models import OrgRole
    role = OrgRole.query.get(role_id)
    if not role:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'id': role.id,
        'name': role.name,
        'key': role.key,
        'level': role.level,
        'can_view_all_deals': role.can_view_all_deals,
        'can_view_department_deals': role.can_view_department_deals,
        'can_view_own_deals': role.can_view_own_deals,
        'can_change_deal_responsible': role.can_change_deal_responsible,
        'can_view_all_archive': role.can_view_all_archive,
        'can_view_department_archive': role.can_view_department_archive,
        'can_view_own_archive': role.can_view_own_archive,
        'can_manage_department': role.can_manage_department,
        'can_view_statistics': role.can_view_statistics,
        'can_manage_managers': role.can_manage_managers,
        'can_receive_leads': role.can_receive_leads
    })


@admin_bp.route('/api/admin/assign-client', methods=['POST'])
@csrf.exempt
@admin_required
def api_admin_assign_client():
    """Assign or unassign a manager to a client (user)"""
    from models import User, Manager
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Нет данных'})
    client_id = data.get('client_id')
    manager_id = data.get('manager_id')
    if not client_id:
        return jsonify({'success': False, 'error': 'Клиент не указан'})
    client = User.query.get(int(client_id))
    if not client:
        return jsonify({'success': False, 'error': 'Клиент не найден'})
    if manager_id:
        manager = Manager.query.get(int(manager_id))
        if not manager:
            return jsonify({'success': False, 'error': 'Менеджер не найден'})
        client.assigned_manager_id = manager.id
        db.session.commit()
        mgr_name = f"{manager.first_name or ''} {manager.last_name or ''}".strip() or manager.email
        return jsonify({'success': True, 'message': f'Менеджер {mgr_name} назначен', 'manager_name': mgr_name})
    else:
        client.assigned_manager_id = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Менеджер снят', 'manager_name': None})


@admin_bp.route('/admin/api/roles/<int:role_id>/delete', methods=['POST'])
@csrf.exempt
@admin_required
def admin_api_delete_role(role_id):
    from models import OrgRole, Manager
    role = OrgRole.query.get(role_id)
    if not role:
        return jsonify({'success': False, 'error': 'Роль не найдена'})
    if role.key in ('director', 'rop', 'manager'):
        return jsonify({'success': False, 'error': 'Нельзя удалить базовую роль'})
    Manager.query.filter_by(org_role_id=role_id).update({'org_role_id': None})
    db.session.delete(role)
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/admin/api/roles', methods=['POST'])
@admin_bp.route('/admin/api/roles/<int:role_id>', methods=['POST'])
@csrf.exempt
@admin_required
def admin_api_roles(role_id=None):
    from models import OrgRole
    data = request.get_json()
    if not data or not data.get('name') or not data.get('key'):
        return jsonify({'success': False, 'error': 'Название и ключ обязательны'})
    
    if role_id:
        role = OrgRole.query.get(role_id)
        if not role:
            return jsonify({'success': False, 'error': 'Роль не найдена'})
    else:
        existing = OrgRole.query.filter_by(key=data['key']).first()
        if existing:
            return jsonify({'success': False, 'error': 'Роль с таким ключом уже существует'})
        role = OrgRole()
        db.session.add(role)
    
    role.name = data['name'].strip()
    role.key = data['key'].strip()
    role.level = int(data.get('level', 10))
    
    perm_fields = ['can_view_all_deals', 'can_view_department_deals', 'can_view_own_deals',
                   'can_change_deal_responsible', 'can_view_all_archive', 'can_view_department_archive',
                   'can_view_own_archive', 'can_manage_department', 'can_view_statistics', 'can_manage_managers',
                   'can_receive_leads']
    for field in perm_fields:
        val = data.get(field)
        if val is not None:
            setattr(role, field, val in (True, 'true', 'on', '1', 1))
    
    db.session.commit()
    return jsonify({'success': True})



@admin_bp.route('/admin/deals-archive')
@admin_required
def admin_deals_archive():
    from models import Deal, Manager
    from sqlalchemy import func
    from datetime import timedelta

    manager_id = request.args.get('manager_id', type=int)
    status_filter = request.args.get('status', '')
    period = request.args.get('period', '')

    query = Deal.query.filter(Deal.status.in_(['completed', 'successful', 'rejected']))

    if manager_id:
        query = query.filter(Deal.manager_id == manager_id)
    if status_filter:
        if status_filter == 'completed':
            query = query.filter(Deal.status.in_(['completed', 'successful']))
        else:
            query = query.filter(Deal.status == status_filter)
    if period:
        now = datetime.utcnow()
        if period == 'week':
            query = query.filter(Deal.updated_at >= now - timedelta(days=7))
        elif period == 'month':
            query = query.filter(Deal.updated_at >= now - timedelta(days=30))
        elif period == 'quarter':
            query = query.filter(Deal.updated_at >= now - timedelta(days=90))
        elif period == 'year':
            query = query.filter(Deal.updated_at >= now - timedelta(days=365))

    deals = query.order_by(Deal.updated_at.desc()).all()

    all_closed = Deal.query.filter(Deal.status.in_(['completed', 'successful', 'rejected']))
    if manager_id:
        all_closed = all_closed.filter(Deal.manager_id == manager_id)
    if period:
        now = datetime.utcnow()
        periods_map = {'week': 7, 'month': 30, 'quarter': 90, 'year': 365}
        if period in periods_map:
            all_closed = all_closed.filter(Deal.updated_at >= now - timedelta(days=periods_map[period]))
    all_closed_list = all_closed.all()

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

    managers = Manager.query.filter_by(is_active=True).order_by(Manager.first_name).all()

    manager_stats_data = []
    all_managers = Manager.query.filter_by(is_active=True).all()
    for m in all_managers:
        m_deals = [d for d in Deal.query.filter(Deal.manager_id == m.id, Deal.status.in_(['completed', 'successful', 'rejected'])).all()]
        if not m_deals:
            continue
        m_success = [d for d in m_deals if d.status in ('completed', 'successful')]
        m_rejected = [d for d in m_deals if d.status == 'rejected']
        m_revenue = sum(float(d.property_price or 0) for d in m_success)
        m_conv = round(len(m_success) / len(m_deals) * 100, 1) if m_deals else 0
        manager_stats_data.append({
            'name': m.full_name,
            'total': len(m_deals),
            'successful': len(m_success),
            'rejected': len(m_rejected),
            'conversion': m_conv,
            'revenue': m_revenue,
        })
    manager_stats_data.sort(key=lambda x: -x['successful'])

    return render_template('admin/deals_archive.html',
                         admin=current_user,
                         deals=deals, stats=stats,
                         rejection_stats=rejection_stats,
                         managers=managers,
                         manager_stats=manager_stats_data)



@admin_bp.route('/admin/data-stats')
@admin_required
def admin_data_stats():
    """JSON endpoint: counts for properties, complexes, developers used in dashboard."""
    from models import Property, ResidentialComplex, Developer
    try:
        return jsonify({
            'success': True,
            'properties': Property.query.filter_by(is_active=True).count(),
            'complexes': ResidentialComplex.query.filter_by(is_active=True).count(),
            'developers': Developer.query.filter_by(is_active=True).count(),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@admin_bp.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard with comprehensive operational analytics"""
    from models import Admin, User, Manager, CashbackApplication, CallbackRequest, Deal, Property, ResidentialComplex, Partner, PartnerWithdrawal
    from sqlalchemy import func

    current_admin = current_user
    if not current_admin:
        return redirect(url_for('adm.admin_login'))

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # ── Users ──────────────────────────────────────────────────────────
    total_users      = User.query.count()
    active_users     = User.query.filter_by(is_active=True).count()
    new_users_today  = User.query.filter(User.created_at >= today_start).count()
    new_users_week   = User.query.filter(User.created_at >= week_ago).count()
    new_users_month  = User.query.filter(User.created_at >= month_ago).count()

    # ── Managers ───────────────────────────────────────────────────────
    total_managers  = Manager.query.count()
    active_managers = Manager.query.filter_by(is_active=True).count()

    # ── Deals ──────────────────────────────────────────────────────────
    deal_counts_raw = db.session.query(Deal.status, func.count(Deal.id)).group_by(Deal.status).all()
    deal_by_status  = {s: c for s, c in deal_counts_raw}
    total_deals     = sum(deal_by_status.values())
    deals_new       = deal_by_status.get('new', 0)
    deals_in_prog   = deal_by_status.get('in_progress', 0) + deal_by_status.get('meeting_scheduled', 0)
    deals_reserved  = deal_by_status.get('reserved', 0) + deal_by_status.get('mortgage', 0)
    deals_success   = deal_by_status.get('successful', 0) + deal_by_status.get('completed', 0)
    deals_rejected  = deal_by_status.get('rejected', 0)
    deals_active    = deals_new + deals_in_prog + deals_reserved
    new_deals_week  = Deal.query.filter(Deal.created_at >= week_ago).count()

    # Cashback from deals
    cashback_total_q = db.session.query(func.sum(Deal.cashback_amount)).filter(
        Deal.status.in_(['successful', 'completed'])
    ).scalar()
    cashback_total = float(cashback_total_q or 0)

    # Avg deal size
    avg_deal_price_q = db.session.query(func.avg(Deal.property_price)).filter(
        Deal.status.in_(['successful', 'completed'])
    ).scalar()
    avg_deal_price = float(avg_deal_price_q or 0)

    # ── Callback Requests ──────────────────────────────────────────────
    total_callbacks   = CallbackRequest.query.count()
    new_callbacks     = CallbackRequest.query.filter_by(status='Новая').count()
    today_callbacks   = CallbackRequest.query.filter(CallbackRequest.created_at >= today_start).count()
    week_callbacks    = CallbackRequest.query.filter(CallbackRequest.created_at >= week_ago).count()

    # ── Cashback Applications ──────────────────────────────────────────
    total_applications   = CashbackApplication.query.count()
    pending_applications = CashbackApplication.query.filter_by(status='На рассмотрении').count()
    approved_applications= CashbackApplication.query.filter_by(status='Одобрена').count()
    paid_applications    = CashbackApplication.query.filter_by(status='Выплачена').count()
    cashback_approved_sum= db.session.query(func.sum(CashbackApplication.cashback_amount)).filter_by(status='Одобрена').scalar() or 0
    cashback_paid_sum    = db.session.query(func.sum(CashbackApplication.cashback_amount)).filter_by(status='Выплачена').scalar() or 0

    # ── Properties & Complexes ─────────────────────────────────────────
    total_properties  = Property.query.count()
    active_properties = Property.query.filter_by(is_active=True).count()
    total_complexes   = ResidentialComplex.query.count()
    active_complexes  = ResidentialComplex.query.filter_by(is_active=True).count()

    # ── Partners ───────────────────────────────────────────────────────
    total_partners          = Partner.query.count()
    pending_withdrawals     = PartnerWithdrawal.query.filter_by(status='pending').count()
    withdrawal_amount_q     = db.session.query(func.sum(PartnerWithdrawal.amount)).filter_by(status='pending').scalar()
    pending_withdrawal_sum  = float(withdrawal_amount_q or 0)

    stats = {
        # Users
        'total_users': total_users,
        'active_users': active_users,
        'new_users_today': new_users_today,
        'new_users_week': new_users_week,
        'new_users_month': new_users_month,
        # Managers
        'total_managers': total_managers,
        'active_managers': active_managers,
        # Deals
        'total_deals': total_deals,
        'deals_active': deals_active,
        'deals_new': deals_new,
        'deals_in_progress': deals_in_prog,
        'deals_reserved': deals_reserved,
        'deals_success': deals_success,
        'deals_rejected': deals_rejected,
        'new_deals_week': new_deals_week,
        'cashback_total': cashback_total,
        'avg_deal_price': avg_deal_price,
        # Callbacks
        'total_callbacks': total_callbacks,
        'new_callbacks': new_callbacks,
        'today_callbacks': today_callbacks,
        'week_callbacks': week_callbacks,
        # Cashback applications
        'total_applications': total_applications,
        'pending_applications': pending_applications,
        'approved_applications': approved_applications,
        'paid_applications': paid_applications,
        'total_cashback_approved': float(cashback_approved_sum),
        'total_cashback_paid': float(cashback_paid_sum),
        # Properties
        'total_properties': total_properties,
        'active_properties': active_properties,
        'total_complexes': total_complexes,
        'active_complexes': active_complexes,
        # Partners
        'total_partners': total_partners,
        'pending_withdrawals': pending_withdrawals,
        'pending_withdrawal_sum': pending_withdrawal_sum,
    }

    # ── Recent Activity ────────────────────────────────────────────────
    recent_applications  = CashbackApplication.query.order_by(CashbackApplication.created_at.desc()).limit(5).all()
    recent_users         = User.query.order_by(User.created_at.desc()).limit(8).all()
    recent_callbacks     = CallbackRequest.query.order_by(CallbackRequest.created_at.desc()).limit(6).all()
    recent_deals         = Deal.query.order_by(Deal.created_at.desc()).limit(6).all()

    return render_template('admin/dashboard.html',
                           admin=current_admin,
                           stats=stats,
                           recent_applications=recent_applications,
                           recent_users=recent_users,
                           recent_callbacks=recent_callbacks,
                           recent_deals=recent_deals,
                           current_date=now)


@admin_bp.route('/admin/profile', methods=['GET', 'POST'])
@admin_required
def admin_profile():
    from models import Admin
    admin = current_user
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            admin.full_name = request.form.get('full_name', admin.full_name)
            
            profile_image = request.form.get('profile_image')
            if profile_image:
                admin.profile_image = profile_image
            
            db.session.commit()
            flash('Данные профиля обновлены', 'success')
            return redirect(url_for('adm.admin_profile'))
        
        elif action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not admin.check_password(current_password):
                flash('Неверный текущий пароль', 'error')
            elif new_password != confirm_password:
                flash('Новые пароли не совпадают', 'error')
            elif len(new_password) < 6:
                flash('Пароль должен содержать минимум 6 символов', 'error')
            else:
                admin.set_password(new_password)
                db.session.commit()
                flash('Пароль успешно изменён', 'success')
            
            return redirect(url_for('adm.admin_profile'))
    
    return render_template('admin/profile.html', admin=admin)



@admin_bp.route('/admin/analytics')
@admin_required
def admin_analytics():
    from models import Deal, DealStageConfig, Manager, Department, User, DealTask
    from sqlalchemy import func, extract
    from datetime import datetime, timedelta
    from decimal import Decimal
    
    current_admin = current_user
    
    total_deals = Deal.query.count()
    active_deals = Deal.query.filter(~Deal.status.in_(['completed', 'successful', 'rejected', 'cancelled'])).count()
    successful_deals = Deal.query.filter(Deal.status.in_(['completed', 'successful'])).count()
    rejected_deals = Deal.query.filter_by(status='rejected').count()
    
    total_cashback = db.session.query(func.coalesce(func.sum(Deal.cashback_amount), 0)).scalar()
    total_revenue = db.session.query(func.coalesce(func.sum(Deal.property_price), 0)).scalar()
    successful_cashback = db.session.query(func.coalesce(func.sum(Deal.cashback_amount), 0)).filter(Deal.status.in_(['completed', 'successful'])).scalar()
    successful_revenue = db.session.query(func.coalesce(func.sum(Deal.property_price), 0)).filter(Deal.status.in_(['completed', 'successful'])).scalar()
    avg_deal_size = db.session.query(func.coalesce(func.avg(Deal.property_price), 0)).filter(Deal.status.in_(['completed', 'successful'])).scalar()
    
    conversion_rate = round((successful_deals / total_deals * 100), 1) if total_deals > 0 else 0
    
    stages = DealStageConfig.query.filter_by(is_active=True).order_by(DealStageConfig.sort_order).all()
    funnel_data = []
    for stage in stages:
        count = Deal.query.filter_by(status=stage.key).count()
        amount = db.session.query(func.coalesce(func.sum(Deal.property_price), 0)).filter_by(status=stage.key).scalar()
        funnel_data.append({'label': stage.label, 'key': stage.key, 'color': stage.color, 'count': count, 'amount': float(amount)})
    
    managers = Manager.query.filter_by(is_active=True).all()
    manager_stats = []
    for m in managers:
        m_deals = Deal.query.filter_by(manager_id=m.id).count()
        m_successful = Deal.query.filter(Deal.manager_id == m.id, Deal.status.in_(['completed', 'successful'])).count()
        m_cashback = db.session.query(func.coalesce(func.sum(Deal.cashback_amount), 0)).filter(Deal.manager_id == m.id, Deal.status.in_(['completed', 'successful'])).scalar()
        m_revenue = db.session.query(func.coalesce(func.sum(Deal.property_price), 0)).filter(Deal.manager_id == m.id, Deal.status.in_(['completed', 'successful'])).scalar()
        m_active = Deal.query.filter(Deal.manager_id == m.id, ~Deal.status.in_(['completed', 'successful', 'rejected', 'cancelled'])).count()
        m_conversion = round((m_successful / m_deals * 100), 1) if m_deals > 0 else 0
        m_pending_tasks = DealTask.query.join(Deal).filter(Deal.manager_id == m.id, DealTask.is_completed == False).count()
        manager_stats.append({
            'id': m.id,
            'name': m.full_name or f"{m.first_name} {m.last_name}".strip(),
            'department': m.department.name if m.department else '\u2014',
            'role': m.org_role.name if m.org_role else '\u041c\u0435\u043d\u0435\u0434\u0436\u0435\u0440',
            'total_deals': m_deals,
            'active_deals': m_active,
            'successful_deals': m_successful,
            'cashback': float(m_cashback),
            'revenue': float(m_revenue),
            'conversion': m_conversion,
            'pending_tasks': m_pending_tasks
        })
    manager_stats.sort(key=lambda x: x['successful_deals'], reverse=True)
    
    departments = Department.query.all()
    dept_stats = []
    for dept in departments:
        dept_manager_ids = [m.id for m in Manager.query.filter_by(department_id=dept.id).all()]
        if not dept_manager_ids:
            continue
        d_deals = Deal.query.filter(Deal.manager_id.in_(dept_manager_ids)).count()
        d_successful = Deal.query.filter(Deal.manager_id.in_(dept_manager_ids), Deal.status.in_(['completed', 'successful'])).count()
        d_cashback = db.session.query(func.coalesce(func.sum(Deal.cashback_amount), 0)).filter(Deal.manager_id.in_(dept_manager_ids), Deal.status.in_(['completed', 'successful'])).scalar()
        d_revenue = db.session.query(func.coalesce(func.sum(Deal.property_price), 0)).filter(Deal.manager_id.in_(dept_manager_ids), Deal.status.in_(['completed', 'successful'])).scalar()
        d_conversion = round((d_successful / d_deals * 100), 1) if d_deals > 0 else 0
        dept_stats.append({
            'name': dept.name,
            'managers_count': len(dept_manager_ids),
            'total_deals': d_deals,
            'successful_deals': d_successful,
            'cashback': float(d_cashback),
            'revenue': float(d_revenue),
            'conversion': d_conversion
        })
    
    now = datetime.utcnow()
    monthly_data = []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=i*30)).replace(day=1)
        if i > 0:
            next_month = (month_start + timedelta(days=32)).replace(day=1)
        else:
            next_month = now
        month_deals = Deal.query.filter(Deal.created_at >= month_start, Deal.created_at < next_month).count()
        month_successful = Deal.query.filter(Deal.created_at >= month_start, Deal.created_at < next_month, Deal.status.in_(['completed', 'successful'])).count()
        month_names_ru = ['\u042f\u043d\u0432', '\u0424\u0435\u0432', '\u041c\u0430\u0440', '\u0410\u043f\u0440', '\u041c\u0430\u0439', '\u0418\u044e\u043d', '\u0418\u044e\u043b', '\u0410\u0432\u0433', '\u0421\u0435\u043d', '\u041e\u043a\u0442', '\u041d\u043e\u044f', '\u0414\u0435\u043a']
        monthly_data.append({
            'month': month_names_ru[month_start.month - 1],
            'total': month_deals,
            'successful': month_successful
        })
    
    rejection_stats = db.session.query(Deal.rejection_reason, func.count(Deal.id)).filter(Deal.status == 'rejected', Deal.rejection_reason != None).group_by(Deal.rejection_reason).all()
    rejection_data = [{'reason': r[0] or 'Не указана', 'count': r[1]} for r in rejection_stats]
    
    from models import CallbackRequest, CashbackApplication
    
    total_users = User.query.count()
    total_leads = CallbackRequest.query.count()
    new_leads = CallbackRequest.query.filter_by(status='Новая').count()
    processed_leads = CallbackRequest.query.filter_by(status='Обработана').count()
    called_leads = CallbackRequest.query.filter(CallbackRequest.status == 'Звонок совершен').count()
    
    total_applications = CashbackApplication.query.count()
    pending_applications = CashbackApplication.query.filter_by(status='На рассмотрении').count()
    approved_applications = CashbackApplication.query.filter_by(status='Одобрена').count()
    paid_applications = CashbackApplication.query.filter_by(status='Выплачена').count()
    
    lead_to_deal = round((total_deals / total_leads * 100), 1) if total_leads > 0 else 0
    lead_to_registration = round((total_users / total_leads * 100), 1) if total_leads > 0 else 0
    
    reg_sources = db.session.query(User.registration_source, func.count(User.id)).group_by(User.registration_source).all()
    source_data = [{'source': s[0] or 'Не указан', 'count': s[1]} for s in reg_sources]
    source_data.sort(key=lambda x: x['count'], reverse=True)
    
    monthly_leads = []
    month_names_ru = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=i*30)).replace(day=1)
        if i > 0:
            next_month = (month_start + timedelta(days=32)).replace(day=1)
        else:
            next_month = now
        m_leads = CallbackRequest.query.filter(CallbackRequest.created_at >= month_start, CallbackRequest.created_at < next_month).count()
        m_regs = User.query.filter(User.created_at >= month_start, User.created_at < next_month).count()
        monthly_leads.append({
            'month': month_names_ru[month_start.month - 1],
            'leads': m_leads,
            'registrations': m_regs
        })
    
    lead_interest_stats = db.session.query(CallbackRequest.interest, func.count(CallbackRequest.id)).filter(CallbackRequest.interest != None, CallbackRequest.interest != '').group_by(CallbackRequest.interest).all()
    interest_data = [{'interest': r[0], 'count': r[1]} for r in lead_interest_stats]
    interest_data.sort(key=lambda x: x['count'], reverse=True)
    
    lead_budget_stats = db.session.query(CallbackRequest.budget, func.count(CallbackRequest.id)).filter(CallbackRequest.budget != None, CallbackRequest.budget != '').group_by(CallbackRequest.budget).all()
    budget_data = [{'budget': r[0], 'count': r[1]} for r in lead_budget_stats]
    budget_data.sort(key=lambda x: x['count'], reverse=True)
    
    return render_template('admin/analytics.html',
        admin=current_admin,
        total_deals=total_deals,
        active_deals=active_deals,
        successful_deals=successful_deals,
        rejected_deals=rejected_deals,
        total_cashback=float(total_cashback),
        total_revenue=float(total_revenue),
        successful_cashback=float(successful_cashback),
        successful_revenue=float(successful_revenue),
        avg_deal_size=float(avg_deal_size),
        conversion_rate=conversion_rate,
        funnel_data=funnel_data,
        manager_stats=manager_stats,
        dept_stats=dept_stats,
        monthly_data=monthly_data,
        rejection_data=rejection_data,
        total_users=total_users,
        total_leads=total_leads,
        new_leads=new_leads,
        processed_leads=processed_leads,
        called_leads=called_leads,
        total_applications=total_applications,
        pending_applications=pending_applications,
        approved_applications=approved_applications,
        paid_applications=paid_applications,
        lead_to_deal=lead_to_deal,
        lead_to_registration=lead_to_registration,
        source_data=source_data,
        monthly_leads=monthly_leads,
        interest_data=interest_data,
        budget_data=budget_data)


@admin_bp.route('/admin/balance-management')
@admin_required
def admin_balance_management():
    """Admin panel for balance and withdrawal management"""
    try:
        from models import User, WithdrawalRequest, UserBalance
        from services.withdrawal_service import WithdrawalService
        
        # Get statistics (use real DB columns: balance, pending_balance, not property aliases)
        from sqlalchemy import func as sqlfunc
        total_users_with_balance = db.session.query(UserBalance).filter(
            (UserBalance.balance > 0) | (UserBalance.pending_balance > 0)
        ).count()
        
        total_available = db.session.query(sqlfunc.sum(UserBalance.balance)).scalar() or 0
        total_pending = db.session.query(sqlfunc.sum(UserBalance.pending_balance)).scalar() or 0
        total_earned = db.session.query(sqlfunc.sum(UserBalance.total_earned)).scalar() or 0
        total_withdrawn = db.session.query(sqlfunc.sum(UserBalance.total_withdrawn)).scalar() or 0
        
        # Pending withdrawals count
        pending_count = WithdrawalRequest.query.filter_by(status='pending').count()
        
        return render_template('admin/balance_management.html',
                             total_users_with_balance=total_users_with_balance,
                             total_available=total_available,
                             total_pending=total_pending,
                             total_earned=total_earned,
                             total_withdrawn=total_withdrawn,
                             pending_count=pending_count)
    except Exception as e:
        logger.error(f"Error loading balance management: {str(e)}")
        flash('Ошибка загрузки панели управления балансом', 'error')
        return redirect(url_for('adm.admin_dashboard'))


@admin_bp.route('/admin/cashback-requests')
@admin_required
def admin_cashback_requests():
    """View all cashback requests"""
    from models import CallbackRequest
    
    # Get page number
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Filter cashback requests
    cashback_requests = CallbackRequest.query.filter(
        CallbackRequest.notes.contains('кешбек')
    ).order_by(CallbackRequest.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('admin/cashback_requests.html',
                         requests=cashback_requests)


@admin_bp.route('/admin/callback-request/<int:request_id>/status', methods=['POST'])
@csrf.exempt
@admin_required
def update_callback_request_status(request_id):
    """Update callback request status"""
    from models import CallbackRequest
    
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        callback_request = CallbackRequest.query.get_or_404(request_id)
        callback_request.status = new_status
        
        if new_status == 'Обработана':
            callback_request.processed_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Статус обновлен'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/users')
@admin_required
def admin_users():
    """User management page"""
    try:
        from models import Admin, User
        
        # ИСПРАВЛЕНО: Используем Flask-Login current_user
        current_admin = current_user
        
        page = request.args.get('page', 1, type=int)
        search = request.args.get('search', '', type=str)
        status = request.args.get('status', '', type=str)
        
        query = User.query
        
        if search:
            query = query.filter(User.email.contains(search) | User.full_name.contains(search))
        
        if status == 'active':
            query = query.filter_by(is_active=True)
        elif status == 'inactive':
            query = query.filter_by(is_active=False)
        elif status == 'verified':
            query = query.filter_by(is_verified=True)
        elif status == 'unverified':
            query = query.filter_by(is_verified=False)
        
        users = query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False
        )
        
        # Обработка пользователей для безопасного отображения дат
        from datetime import datetime
        for user in users.items:
            if user.created_at is None:
                # Устанавливаем текущую дату для пользователей без даты создания
                user.created_at = datetime.now()
        
        print(f"DEBUG: Loading admin_users page - Found {users.total} users")
        
        return render_template('admin/users.html', 
                             admin=current_admin, 
                             users=users,
                             search=search,
                             status=status)
                             
    except Exception as e:
        print(f"ERROR in admin_users: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Ошибка загрузки страницы пользователей: {str(e)}', 'error')
        return redirect(url_for('adm.admin_dashboard'))


@admin_bp.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(user_id):
    """Edit user details"""
    from models import Admin, User, Manager
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    user = User.query.get_or_404(user_id)
    managers = Manager.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        user.email = request.form.get('email')
        user.full_name = _capitalize_name(request.form.get('full_name'))
        user.phone = request.form.get('phone')
        user.client_status = request.form.get('client_status')
        user.client_notes = request.form.get('client_notes')
        user.is_active = 'is_active' in request.form
        user.is_verified = 'is_verified' in request.form
        
        assigned_manager_id = request.form.get('assigned_manager_id')
        if assigned_manager_id and assigned_manager_id.isdigit():
            user.assigned_manager_id = int(assigned_manager_id)
        else:
            user.assigned_manager_id = None
        
        try:
            db.session.commit()
            flash('Пользователь успешно обновлен', 'success')
            return redirect(url_for('adm.admin_users'))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при обновлении пользователя', 'error')
    
    return render_template('admin/edit_user.html', 
                         admin=current_admin, 
                         user=user,
                         managers=managers)


@admin_bp.route('/admin/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def admin_toggle_user_status(user_id):
    """Toggle user active status (block/activate)"""
    from models import User, Admin
    
    user = User.query.get_or_404(user_id)
    current_admin = current_user
    
    try:
        # Toggle the status
        user.is_active = not user.is_active
        status_text = "активирован" if user.is_active else "заблокирован"
        
        db.session.commit()
        
        # Log the action
        print(f"ADMIN ACTION: {current_admin.full_name} (ID: {current_admin.id}) {'activated' if user.is_active else 'blocked'} user {user.full_name} (ID: {user.id}, Email: {user.email})")
        
        flash(f'Пользователь {user.full_name} успешно {status_text}', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"ERROR in admin_toggle_user_status: {str(e)}")
        flash(f'Ошибка при изменении статуса пользователя: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_users'))


@admin_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    """Delete user"""
    from models import User
    
    user = User.query.get_or_404(user_id)
    
    try:
        from sqlalchemy import text
        uid = user.id

        deal_ids_result = db.session.execute(
            text("SELECT id FROM deals WHERE client_id = :uid"), {'uid': uid}
        ).fetchall()
        deal_ids = [r[0] for r in deal_ids_result]

        if deal_ids:
            db.session.execute(text("DELETE FROM deal_history WHERE deal_id = ANY(:ids)"), {'ids': deal_ids})
            db.session.execute(text("DELETE FROM deal_comments WHERE deal_id = ANY(:ids)"), {'ids': deal_ids})
            db.session.execute(text("DELETE FROM deal_tasks WHERE deal_id = ANY(:ids)"), {'ids': deal_ids})
            db.session.execute(text("DELETE FROM balance_transactions WHERE deal_id = ANY(:ids)"), {'ids': deal_ids})
            db.session.execute(text("DELETE FROM deals WHERE id = ANY(:ids)"), {'ids': deal_ids})

        cleanup_tables = [
            ("user_notifications", "user_id"),
            ("balance_transactions", "user_id"),
            ("withdrawal_requests", "user_id"),
            ("cashback_records", "user_id"),
            ("cashback_applications", "user_id"),
            ("cashback_payouts", "user_id"),
            ("applications", "user_id"),
            ("favorites", "user_id"),
            ("favorite_properties", "user_id"),
            ("favorite_complexes", "user_id"),
            ("saved_searches", "user_id"),
            ("user_balances", "user_id"),
            ("documents", "user_id"),
            ("blog_comments", "user_id"),
            ("developer_appointments", "user_id"),
            ("client_property_recommendations", "client_id"),
            ("search_analytics", "user_id"),
        ]
        from sqlalchemy import inspect as sa_inspect
        existing_tables = sa_inspect(db.engine).get_table_names()
        for table_name, col_name in cleanup_tables:
            if table_name in existing_tables:
                try:
                    nested = db.session.begin_nested()
                    db.session.execute(text(f"DELETE FROM {table_name} WHERE {col_name} = :uid"), {'uid': uid})
                    nested.commit()
                except Exception:
                    nested.rollback()

        try:
            nested = db.session.begin_nested()
            db.session.execute(text("UPDATE collections SET assigned_to_user_id = NULL WHERE assigned_to_user_id = :uid"), {'uid': uid})
            nested.commit()
        except Exception:
            nested.rollback()

        db.session.delete(user)
        db.session.commit()
        flash('Пользователь успешно удален', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting user {user_id}: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Ошибка при удалении пользователя: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_users'))


@admin_bp.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def admin_reset_user_password(user_id):
    """Admin reset user password - generates new password and sends via SMS"""
    from models import User
    from werkzeug.security import generate_password_hash
    import secrets
    import string
    
    user = User.query.get_or_404(user_id)
    
    try:
        # Generate new random password
        alphabet = string.ascii_letters + string.digits
        new_password = ''.join(secrets.choice(alphabet) for _ in range(8))
        
        # Update user password
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        
        # Send SMS with new password if user has phone
        if user.phone:
            phone_clean = ''.join(filter(str.isdigit, user.phone))
            if phone_clean.startswith('8'):
                phone_clean = '7' + phone_clean[1:]
            elif not phone_clean.startswith('7'):
                phone_clean = '7' + phone_clean
            
            sms_message = f"InBack: Ваш новый пароль: {new_password}"
            
            try:
                from sms_service import RedSMSService; sms_service = RedSMSService()
                sms_result = sms_service.send_sms(phone_clean, sms_message)
                if sms_result.get('success'):
                    flash(f'Новый пароль успешно отправлен на телефон {user.phone}', 'success')
                else:
                    error_msg = sms_result.get('message', 'Неизвестная ошибка')
                    flash(f'Пароль изменён, но SMS не удалось отправить ({error_msg}). Новый пароль: {new_password}', 'warning')
            except Exception as e:
                print(f"Error sending SMS: {e}")
                flash(f'Пароль изменён, но SMS не удалось отправить. Новый пароль: {new_password}', 'warning')
        else:
            flash(f'У пользователя нет телефона. Новый пароль: {new_password}', 'warning')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при сбросе пароля: {str(e)}', 'error')
        
    return redirect(url_for('adm.admin_users'))


@admin_bp.route('/admin/users/<int:user_id>/toggle-role', methods=['POST'])
@admin_required 
def admin_toggle_user_role(user_id):
    """Admin change user role"""
    from models import User
    
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('role')
    
    # Validate role
    valid_roles = ['buyer', 'manager', 'admin', None]
    if new_role == '':
        new_role = None
    
    if new_role not in valid_roles:
        flash('Неверная роль пользователя', 'error')
        return redirect(url_for('adm.admin_users'))
    
    try:
        old_role = user.role or 'Не назначена'
        user.role = new_role
        db.session.commit()
        
        new_role_display = new_role or 'Не назначена'
        flash(f'Роль пользователя {user.email} изменена с "{old_role}" на "{new_role_display}"', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при изменении роли: {str(e)}', 'error')
        
    return redirect(url_for('adm.admin_users'))


@admin_bp.route('/admin/users/bulk-role', methods=['POST'])
@admin_required
def admin_bulk_assign_role():
    """Bulk assign role to users"""
    from models import User
    
    user_ids = request.form.getlist('user_ids')
    new_role = request.form.get('role')
    
    if new_role == '':
        new_role = None
    
    valid_roles = ['buyer', 'manager', 'admin', None]
    if new_role not in valid_roles:
        flash('Неверная роль пользователя', 'error')
        return redirect(url_for('adm.admin_users'))
    
    if not user_ids:
        flash('Не выбраны пользователи', 'error')
        return redirect(url_for('adm.admin_users'))
    
    try:
        users = User.query.filter(User.id.in_(user_ids)).all()
        role_display = new_role or 'Не назначена'
        updated_count = 0
        
        for user in users:
            user.role = new_role
            updated_count += 1
        
        db.session.commit()
        flash(f'Роль "{role_display}" назначена для {updated_count} пользователей', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при массовом назначении роли: {str(e)}', 'error')
        
    return redirect(url_for('adm.admin_users'))


@admin_bp.route('/admin/users/bulk-status', methods=['POST'])
@admin_required
def admin_bulk_toggle_status():
    """Bulk toggle user status"""
    from models import User
    
    user_ids = request.form.getlist('user_ids')
    
    if not user_ids:
        flash('Не выбраны пользователи', 'error')
        return redirect(url_for('adm.admin_users'))
    
    try:
        users = User.query.filter(User.id.in_(user_ids)).all()
        activated_count = 0
        deactivated_count = 0
        
        for user in users:
            if user.is_active:
                user.is_active = False
                deactivated_count += 1
            else:
                user.is_active = True
                activated_count += 1
        
        db.session.commit()
        
        if activated_count > 0 and deactivated_count > 0:
            flash(f'Активировано: {activated_count}, деактивировано: {deactivated_count} пользователей', 'success')
        elif activated_count > 0:
            flash(f'Активировано {activated_count} пользователей', 'success')
        else:
            flash(f'Деактивировано {deactivated_count} пользователей', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при массовом изменении статуса: {str(e)}', 'error')
        
    return redirect(url_for('adm.admin_users'))


@admin_bp.route('/admin/users/bulk-delete', methods=['POST'])
@admin_required
def admin_bulk_delete_users():
    """Bulk delete users"""
    from models import User
    
    user_ids = request.form.getlist('user_ids')
    
    if not user_ids:
        flash('Не выбраны пользователи', 'error')
        return redirect(url_for('adm.admin_users'))
    
    try:
        from sqlalchemy import text
        from sqlalchemy import inspect as sa_inspect

        users = User.query.filter(User.id.in_(user_ids)).all()
        deleted_count = len(users)
        uid_list = [u.id for u in users]

        deal_ids_result = db.session.execute(
            text("SELECT id FROM deals WHERE client_id = ANY(:uids)"), {'uids': uid_list}
        ).fetchall()
        deal_ids = [r[0] for r in deal_ids_result]
        if deal_ids:
            db.session.execute(text("DELETE FROM deal_history WHERE deal_id = ANY(:ids)"), {'ids': deal_ids})
            db.session.execute(text("DELETE FROM deal_comments WHERE deal_id = ANY(:ids)"), {'ids': deal_ids})
            db.session.execute(text("DELETE FROM deal_tasks WHERE deal_id = ANY(:ids)"), {'ids': deal_ids})
            db.session.execute(text("DELETE FROM balance_transactions WHERE deal_id = ANY(:ids)"), {'ids': deal_ids})
            db.session.execute(text("DELETE FROM deals WHERE id = ANY(:ids)"), {'ids': deal_ids})

        cleanup_tables = [
            ("user_notifications", "user_id"),
            ("balance_transactions", "user_id"),
            ("withdrawal_requests", "user_id"),
            ("cashback_records", "user_id"),
            ("cashback_applications", "user_id"),
            ("cashback_payouts", "user_id"),
            ("applications", "user_id"),
            ("favorites", "user_id"),
            ("favorite_properties", "user_id"),
            ("favorite_complexes", "user_id"),
            ("saved_searches", "user_id"),
            ("user_balances", "user_id"),
            ("documents", "user_id"),
            ("blog_comments", "user_id"),
            ("developer_appointments", "user_id"),
            ("client_property_recommendations", "client_id"),
            ("search_analytics", "user_id"),
        ]
        existing_tables = sa_inspect(db.engine).get_table_names()
        for table_name, col_name in cleanup_tables:
            if table_name in existing_tables:
                try:
                    nested = db.session.begin_nested()
                    db.session.execute(text(f"DELETE FROM {table_name} WHERE {col_name} = ANY(:uids)"), {'uids': uid_list})
                    nested.commit()
                except Exception:
                    nested.rollback()

        try:
            nested = db.session.begin_nested()
            db.session.execute(text("UPDATE collections SET assigned_to_user_id = NULL WHERE assigned_to_user_id = ANY(:uids)"), {'uids': uid_list})
            nested.commit()
        except Exception:
            nested.rollback()

        for user in users:
            db.session.delete(user)
        
        db.session.commit()
        flash(f'Удалено {deleted_count} пользователей', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при массовом удалении: {str(e)}', 'error')
        
    return redirect(url_for('adm.admin_users'))


@admin_bp.route('/admin/users/create', methods=['GET', 'POST'])
@csrf.exempt
@admin_required
def admin_create_user():
    """Create new user by admin"""
    from models import Admin, User, Manager
    import re
    import secrets
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    managers = Manager.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        # Validate required fields
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        
        if not all([full_name, email, phone]):
                flash('Заполните все обязательные поля', 'error')
                return render_template('admin/create_user.html', 
                                     admin=current_admin, 
                                     managers=managers)
        
        # Validate email format
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
                flash('Некорректный формат email', 'error')
                return render_template('admin/create_user.html', 
                                     admin=current_admin, 
                                     managers=managers)
        
        try:
            logger.info('🔍 Executing user lookup query...')
            existing_user = User.query.filter(
                    (User.email == email) | (User.phone == phone)
            ).first()
            
            if existing_user:
                    flash('Пользователь с таким email или телефоном уже существует', 'error')
                    return render_template('admin/create_user.html', 
                                         admin=current_admin, 
                                         managers=managers)
            
            phone_clean = re.sub(r'[^\d]', '', phone)
            if len(phone_clean) == 11 and phone_clean.startswith('8'):
                    phone_clean = '7' + phone_clean[1:]
            elif len(phone_clean) == 10:
                    phone_clean = '7' + phone_clean
            
            if len(phone_clean) != 11 or not phone_clean.startswith('7'):
                    flash('Некорректный формат телефона', 'error')
                    return render_template('admin/create_user.html', 
                                         admin=current_admin, 
                                         managers=managers)
            
            temp_password = secrets.token_urlsafe(12)
            
            user = User(
                    email=email,
                    full_name=full_name,
                    phone=phone_clean,
                    client_status=request.form.get('client_status', 'Новый'),
                    client_notes=request.form.get('client_notes', ''),
                    is_active='is_active' in request.form,
                    is_verified='is_verified' in request.form,
                    temp_password_hash=temp_password,
                    created_by_admin=True
            )
            
            assigned_manager_id = request.form.get('assigned_manager_id')
            if assigned_manager_id and assigned_manager_id.isdigit():
                    user.assigned_manager_id = int(assigned_manager_id)
            
            user.set_password(temp_password)
            user.must_change_password = True
            
            db.session.add(user)
            db.session.commit()
            
            try:
                from sms_service import RedSMSService; sms_service = RedSMSService()
                sms_message = f"InBack.ru - Ваш пароль для входа: {temp_password}"
                sms_result = sms_service.send_sms(phone_clean, sms_message)
                if sms_result.get('success'):
                    flash(f'Пользователь {full_name} успешно создан! SMS с паролем отправлено на {phone_clean}', 'success')
                else:
                    flash(f'Пользователь {full_name} создан, но SMS не отправлено. Временный пароль: {temp_password}', 'warning')
            except Exception as sms_error:
                print(f"SMS send error: {sms_error}")
                flash(f'Пользователь {full_name} создан. Временный пароль: {temp_password}', 'warning')
            
            return redirect(url_for('adm.admin_users'))
            
        except Exception as e:
            db.session.rollback()
            print(f"Error creating user: {str(e)}")
            flash(f'Ошибка при создании пользователя: {str(e)}', 'error')
            return render_template('admin/create_user.html', 
                                     admin=current_admin, 
                                     managers=managers)
    
    return render_template('admin/create_user.html', 
                         admin=current_admin, 
                         managers=managers)


@admin_bp.route('/admin/users/<int:user_id>/verify', methods=['POST'])
@admin_required
def admin_verify_user(user_id):
    """Verify user account manually"""
    from models import User, Admin
    
    try:
        user = User.query.get_or_404(user_id)
        
        # Проверяем, что пользователь не верифицирован
        if user.is_verified:
            flash(f'Пользователь {user.full_name} уже подтвержден', 'info')
            return redirect(url_for('adm.admin_users'))
        
        # Подтверждаем пользователя
        user.is_verified = True
        
        # ИСПРАВЛЕНО: Используем Flask-Login current_user
        # Логирование действия админа
        current_admin = current_user
        admin_name = current_admin.full_name if current_admin else 'Неизвестный админ'
        
        print(f"ADMIN ACTION: {admin_name} (ID: {current_admin.id}) verified user {user.full_name} (ID: {user.id}, Email: {user.email})")
        
        db.session.commit()
        flash(f'Аккаунт пользователя {user.full_name} успешно подтвержден', 'success')
        
        # Поддержка AJAX запросов
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({
                'success': True,
                'message': f'Аккаунт пользователя {user.full_name} подтвержден',
                'user_id': user.id,
                'verified': True
            })
            
    except Exception as e:
        db.session.rollback()
        error_message = f'Ошибка при подтверждении пользователя: {str(e)}'
        print(f"Error verifying user {user_id}: {str(e)}")
        flash(error_message, 'error')
        
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({
                'success': False,
                'error': error_message
            }), 500
    
    return redirect(url_for('adm.admin_users'))


@admin_bp.route('/admin/users/<int:user_id>/unverify', methods=['POST'])
@admin_required 
def admin_unverify_user(user_id):
    """Unverify user account manually"""
    from models import User, Admin
    
    try:
        user = User.query.get_or_404(user_id)
        
        # Проверяем, что пользователь верифицирован
        if not user.is_verified:
            flash(f'Пользователь {user.full_name} уже не подтвержден', 'info')
            return redirect(url_for('adm.admin_users'))
        
        # Отменяем подтверждение
        user.is_verified = False
        
        # ИСПРАВЛЕНО: Используем Flask-Login current_user
        # Логирование действия админа
        current_admin = current_user
        admin_name = current_admin.full_name if current_admin else 'Неизвестный админ'
        
        print(f"ADMIN ACTION: {admin_name} (ID: {current_admin.id}) unverified user {user.full_name} (ID: {user.id}, Email: {user.email})")
        
        db.session.commit()
        flash(f'Подтверждение аккаунта пользователя {user.full_name} отменено', 'warning')
        
        # Поддержка AJAX запросов
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({
                'success': True,
                'message': f'Подтверждение аккаунта {user.full_name} отменено',
                'user_id': user.id,
                'verified': False
            })
            
    except Exception as e:
        db.session.rollback()
        error_message = f'Ошибка при отмене подтверждения: {str(e)}'
        print(f"Error unverifying user {user_id}: {str(e)}")
        flash(error_message, 'error')
        
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({
                'success': False,
                'error': error_message
            }), 500
    
    return redirect(url_for('adm.admin_users'))


# Property Management Routes

@admin_bp.route('/admin/property/<int:property_id>/mark-sold', methods=['POST'])
@admin_required
def admin_mark_property_sold(property_id):
    """
    Mark a property as sold and notify all users who have it in:
    - favorites
    - comparisons
    - presentations/collections
    """
    from models import Property
    from services.alert_service import AlertService
    
    try:
        property = Property.query.get_or_404(property_id)
        
        if not property.is_active:
            return jsonify({
                'success': False,
                'message': 'Объект уже помечен как проданный'
            }), 400
        
        # Mark property as sold (inactive)
        property.is_active = False
        property.status = 'Продан'
        
        db.session.commit()
        
        # Send notifications to all affected users
        logger.info(f"Property {property_id} marked as sold, sending notifications...")
        notification_result = AlertService.notify_property_sold(property_id)
        
        flash(f'Объект "{property.title}" помечен как проданный. Уведомления отправлены.', 'success')
        
        return jsonify({
            'success': True,
            'message': 'Объект помечен как проданный, уведомления отправлены',
            'property_id': property_id,
            'notifications_sent': notification_result
        })
        
    except Exception as e:
        db.session.rollback()
        error_message = f'Ошибка при пометке объекта как проданного: {str(e)}'
        logger.error(error_message)
        flash(error_message, 'error')
        
        return jsonify({
            'success': False,
            'error': error_message
        }), 500

# Manager Management Routes

@admin_bp.route('/admin/managers')
@admin_required
def admin_managers():
    """Manager management page"""
    from models import Admin, Manager
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    status = request.args.get('status', '', type=str)
    
    query = Manager.query
    
    if search:
        query = query.filter(Manager.email.contains(search) | Manager.first_name.contains(search) | Manager.last_name.contains(search))
    
    if status == 'active':
        query = query.filter_by(is_active=True)
    elif status == 'inactive':
        query = query.filter_by(is_active=False)
    
    managers = query.order_by(Manager.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    all_managers = Manager.query.filter_by(is_active=True).order_by(Manager.first_name).all()
    
    return render_template('admin/managers.html', 
                         admin=current_admin, 
                         managers=managers,
                         all_managers=all_managers,
                         search=search,
                         status=status)


@admin_bp.route('/admin/api/manager/<int:manager_id>/deal-count')
@admin_required
def admin_api_manager_deal_count(manager_id):
    from models import Deal
    count = Deal.query.filter_by(manager_id=manager_id).count()
    return jsonify({'deal_count': count})


@admin_bp.route('/admin/managers/<int:manager_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_manager(manager_id):
    """Edit manager details"""
    from models import Admin, Manager
    
    try:
        # ИСПРАВЛЕНО: Используем Flask-Login current_user
        current_admin = current_user
        manager = Manager.query.get(manager_id)
        
        if not manager:
            flash(f'Менеджер с ID {manager_id} не найден', 'error')
            return redirect(url_for('adm.admin_managers'))
            
        print(f"DEBUG: Found manager {manager_id}: {manager.email}")
    except Exception as e:
        print(f"ERROR in admin_edit_manager: {e}")
        flash('Ошибка при загрузке менеджера', 'error')
        return redirect(url_for('adm.admin_managers'))
    
    if request.method == 'POST':
        try:
            manager.email = request.form.get('email')
            manager.first_name = _capitalize_name(request.form.get('first_name'))
            manager.last_name = _capitalize_name(request.form.get('last_name'))
            manager.phone = _normalize_phone(request.form.get('phone'))
            manager.position = request.form.get('position')
            manager.is_active = 'is_active' in request.form
            manager.show_on_index = 'show_on_index' in request.form
            manager.telegram_id = request.form.get('telegram_id')

            org_role_id = request.form.get('org_role_id')
            department_id = request.form.get('department_id')
            manager.org_role_id = int(org_role_id) if org_role_id else None
            manager.department_id = int(department_id) if department_id else None

            from models import OrgRole
            if manager.org_role_id:
                role = OrgRole.query.get(manager.org_role_id)
                manager.is_rop = bool(role and role.key in ('rop', 'director'))
            else:
                manager.is_rop = False

            new_password = request.form.get('new_password')
            if new_password:
                manager.set_password(new_password)

            # Handle profile image upload
            profile_image_file = request.files.get('profile_image')
            if profile_image_file and profile_image_file.filename:
                try:
                    from werkzeug.utils import secure_filename
                    import os
                    import uuid
                    filename = secure_filename(profile_image_file.filename)
                    upload_dir = 'static/uploads/profiles'
                    os.makedirs(upload_dir, exist_ok=True)
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    file_path = os.path.join(upload_dir, unique_filename)
                    profile_image_file.save(file_path)
                    manager.profile_image = f"/{file_path}"
                except Exception as img_e:
                    logger.error(f"Error uploading profile image: {img_e}")
                    flash('Ошибка при загрузке изображения', 'error')

            db.session.commit()
            flash('Менеджер успешно обновлен', 'success')
            return redirect(url_for('adm.admin_managers'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"admin_edit_manager POST error for manager {manager_id}: {e}", exc_info=True)
            print(f"ERROR admin_edit_manager POST: {e}")
            flash(f'Ошибка при сохранении: {e}', 'error')
    
    from datetime import datetime
    from models import OrgRole, Department
    try:
        roles = OrgRole.query.filter_by(is_active=True).order_by(OrgRole.level.desc()).all()
    except Exception:
        roles = OrgRole.query.order_by(OrgRole.level.desc()).all()
    try:
        departments = Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()
    except Exception:
        departments = Department.query.order_by(Department.name).all()

    return render_template('admin/edit_manager.html', 
                         admin=current_admin, 
                         manager=manager,
                         roles=roles,
                         departments=departments,
                         current_date=datetime.utcnow())



# Blog Management Routes

@admin_bp.route('/admin/blog')
@admin_required
def admin_blog():
    """Blog management page"""
    from models import Admin, BlogPost
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    status = request.args.get('status', '', type=str)
    category_id = request.args.get('category_id', '', type=str)
    
    query = BlogPost.query
    
    if search:
        query = query.filter(BlogPost.title.contains(search) | BlogPost.content.contains(search))
    
    if status:
        query = query.filter_by(status=status)
    
    if category_id:
        query = query.filter_by(category_id=int(category_id))
    
    posts = query.order_by(BlogPost.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False
    )
    
    # Get categories for filter from Category table
    from models import Category
    categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
    
    return render_template('admin/blog.html', 
                         admin=current_admin, 
                         posts=posts,
                         search=search,
                         status=status,
                         category_id=category_id,
                         categories=categories)


@admin_bp.route('/admin/blog/create', methods=['GET', 'POST'])
@admin_required
# @csrf.exempt  # CSRF disabled  # Временно отключаем CSRF для отладки
def admin_create_post():
    """Create new blog post with full TinyMCE integration"""
    from models import Admin, BlogPost, Category
    from datetime import datetime
    import re
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    if request.method == 'GET':
        # Load categories for the form
        categories = Category.query.order_by(Category.name).all()
        return render_template('admin/create_article.html', admin=current_admin, categories=categories)
    
    if request.method == 'POST':
        try:
            title = request.form.get('title')
            content = request.form.get('content')
            excerpt = request.form.get('excerpt')
            category_id = request.form.get('category_id')
            
            # Handle featured image upload
            featured_image_url = request.form.get('featured_image', '')
            uploaded_file = request.files.get('featured_image_file')
            
            if uploaded_file and uploaded_file.filename:
                # Secure filename and save
                from werkzeug.utils import secure_filename
                import os
                filename = secure_filename(uploaded_file.filename)
                
                # Create upload directory if it doesn't exist
                upload_dir = 'static/uploads/blog'
                os.makedirs(upload_dir, exist_ok=True)
                
                # Save file with unique name
                import uuid
                unique_filename = f"{uuid.uuid4()}_{filename}"
                file_path = os.path.join(upload_dir, unique_filename)
                uploaded_file.save(file_path)
                
                # Set the URL for the database
                featured_image_url = f"/{file_path}"
            
            if not title or not content or not category_id:
                flash('Заголовок, содержание и категория обязательны', 'error')
                categories = Category.query.order_by(Category.name).all()
                return render_template('admin/create_article.html', admin=current_admin, categories=categories)
            
            # Get category name from category_id
            category = Category.query.get(int(category_id))
            if not category:
                flash('Выбранная категория не найдена', 'error')
                categories = Category.query.order_by(Category.name).all()
                return render_template('admin/create_article.html', admin=current_admin, categories=categories)
            
            # Generate slug from title
            slug = request.form.get('slug', '')
            if not slug:
                # Auto-generate slug from title
                def transliterate(text):
                    rus_to_eng = {
                        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh', 'з': 'z',
                        'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
                        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
                        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
                    }
                    return ''.join(rus_to_eng.get(char.lower(), char) for char in text)
                
                slug = transliterate(title.lower())
                slug = re.sub(r'[^\w\s-]', '', slug)
                slug = re.sub(r'[-\s]+', '-', slug).strip('-')
            
            # Ensure unique slug
            original_slug = slug
            counter = 1
            while BlogPost.query.filter_by(slug=slug).first():
                slug = f"{original_slug}-{counter}"
                counter += 1
            
            post = BlogPost(
                title=title,
                slug=slug,
                content=content,
                excerpt=excerpt,
                meta_title=request.form.get('meta_title'),
                meta_description=request.form.get('meta_description'),
                meta_keywords=request.form.get('meta_keywords'),
                category_id=category.id,  # Store category ID for proper relation
                category=category.name,  # Store category name for compatibility
                tags=request.form.get('tags'),
                featured_image=featured_image_url,
                status=request.form.get('status', 'draft'),
                author_id=current_admin.id,
                created_at=datetime.utcnow()
            )
            
            if post.status == 'published':
                post.published_at = datetime.utcnow()
            
            db.session.add(post)
            db.session.commit()
            
            # Update category article count
            if post.status == 'published':
                category.articles_count = BlogPost.query.filter_by(category=category.name, status='published').count()
                db.session.commit()
            
            flash('Статья успешно создана!', 'success')
            return redirect(url_for('adm.admin_blog'))
            
        except Exception as e:
            db.session.rollback()
            print(f'ERROR creating blog post: {str(e)}')
            flash(f'Ошибка при создании статьи: {str(e)}', 'error')
            categories = Category.query.order_by(Category.name).all()
            return render_template('admin/create_article.html', admin=current_admin, categories=categories)



@admin_bp.route('/admin/blog/<int:post_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_post(post_id):
    """Edit blog post"""
    from models import Admin, BlogPost, Category
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    try:
        post = BlogPost.query.get_or_404(post_id)
    except Exception as e:
        flash(f'Статья не найдена: {str(e)}', 'error')
        return redirect(url_for('adm.admin_blog'))
    
    if request.method == 'POST':
        post.title = request.form.get('title')
        post.content = request.form.get('content')
        post.excerpt = request.form.get('excerpt')
        post.meta_title = request.form.get('meta_title')
        post.meta_description = request.form.get('meta_description')
        post.meta_keywords = request.form.get('meta_keywords')
        post.category = request.form.get('category')
        post.tags = request.form.get('tags')
        post.featured_image = request.form.get('featured_image')
        
        old_status = post.status
        post.status = request.form.get('status', 'draft')
        
        # Handle publishing
        if post.status == 'published' and old_status != 'published':
            post.published_at = datetime.utcnow()
        elif post.status != 'published':
            post.published_at = None
        
        try:
            db.session.commit()
            flash('Статья успешно обновлена', 'success')
            return redirect(url_for('adm.admin_blog'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при обновлении статьи: {str(e)}', 'error')
    
    # Get categories for dropdown
    try:
        categories = Category.query.order_by(Category.name).all()
    except Exception as e:
        print(f'Error loading categories: {e}')
        categories = []
    
    return render_template('admin/blog_post_create.html', 
                         admin=current_admin, 
                         post=post, 
                         categories=categories)


@admin_bp.route('/admin/blog/<int:post_id>/delete', methods=['POST'])
@admin_required
def admin_delete_post(post_id):
    """Delete blog post"""
    from models import BlogPost
    
    post = BlogPost.query.get_or_404(post_id)
    
    try:
        db.session.delete(post)
        db.session.commit()
        flash('Статья успешно удалена', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ошибка при удалении статьи', 'error')
    
    return redirect(url_for('adm.admin_blog'))

# Analytics Routes

@admin_bp.route('/admin/analytics/cashback')
@admin_required
def admin_cashback_analytics():
    """Cashback analytics page"""
    from models import Admin, CashbackApplication
    from sqlalchemy import func
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    # Monthly cashback stats
    monthly_stats = db.session.query(
        func.date_trunc('month', CashbackApplication.created_at).label('month'),
        func.count(CashbackApplication.id).label('count'),
        func.sum(CashbackApplication.cashback_amount).label('total_amount')
    ).group_by(func.date_trunc('month', CashbackApplication.created_at)).order_by('month').all()
    
    # Status breakdown
    status_stats = db.session.query(
        CashbackApplication.status,
        func.count(CashbackApplication.id).label('count'),
        func.sum(CashbackApplication.cashback_amount).label('total_amount')
    ).group_by(CashbackApplication.status).all()
    
    # Recent large cashbacks
    large_cashbacks = CashbackApplication.query.filter(
        CashbackApplication.cashback_amount >= 100000
    ).order_by(CashbackApplication.created_at.desc()).limit(10).all()
    
    return render_template('admin/cashback_analytics.html',
                         admin=current_admin,
                         monthly_stats=monthly_stats,
                         status_stats=status_stats,
                         large_cashbacks=large_cashbacks)

# Admin Blog Management Routes


@admin_bp.route('/admin/blog/<int:article_id>/edit', methods=['GET', 'POST'])
@admin_required  
def admin_edit_article(article_id):
    """Edit blog article"""
    from models import Admin, BlogPost
    import re
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    article = BlogPost.query.get_or_404(article_id)
    
    if request.method == 'POST':
        article.title = request.form.get('title')
        article.slug = request.form.get('slug')
        article.content = request.form.get('content')
        article.excerpt = request.form.get('excerpt')
        article.category = request.form.get('category')
        article.tags = request.form.get('tags')
        article.featured_image = request.form.get('featured_image')
        article.meta_title = request.form.get('meta_title')
        article.meta_description = request.form.get('meta_description')
        article.meta_keywords = request.form.get('meta_keywords')
        action = request.form.get('action', 'save')
        
        # Auto-generate slug if empty
        if not article.slug:
            slug = re.sub(r'[^\w\s-]', '', article.title.lower())
            slug = re.sub(r'[\s_-]+', '-', slug)
            article.slug = slug.strip('-')
        
        # Set status based on action
        if action == 'publish':
            article.status = 'published'
            if not article.published_at:
                article.published_at = datetime.now()
        else:
            article.status = request.form.get('status', 'draft')
        
        # Handle scheduled posts
        if article.status == 'scheduled':
            scheduled_str = request.form.get('scheduled_for')
            if scheduled_str:
                try:
                    article.scheduled_for = datetime.fromisoformat(scheduled_str)
                except:
                    pass
        else:
            article.scheduled_for = None
            
        article.updated_at = datetime.now()
        
        try:
            db.session.commit()
            flash('Статья успешно обновлена', 'success')
            return redirect(url_for('adm.admin_blog'))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при обновлении статьи', 'error')
    
    return render_template('admin/create_article.html', admin=current_admin, article=article)


@admin_bp.route('/admin/blog/<int:article_id>/delete', methods=['POST'])
@admin_required
def admin_delete_article(article_id):
    """Delete blog article"""
    from models import BlogPost
    
    article = BlogPost.query.get_or_404(article_id)
    
    try:
        db.session.delete(article)
        db.session.commit()
        flash('Статья успешно удалена', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ошибка при удалении статьи', 'error')
    
    return redirect(url_for('adm.admin_blog'))


@admin_bp.route('/admin/blog/<int:article_id>/publish', methods=['POST'])
@admin_required
def admin_publish_article(article_id):
    """Publish blog article"""
    from models import BlogPost
    
    article = BlogPost.query.get_or_404(article_id)
    article.status = 'published'
    article.published_at = datetime.now()
    article.updated_at = datetime.now()
    
    try:
        db.session.commit()
        flash('Статья успешно опубликована', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ошибка при публикации статьи', 'error')
    
    return redirect(url_for('adm.admin_blog'))


# ==========================================
# ADMIN OFFERS MANAGEMENT ROUTES
# ==========================================


@admin_bp.route('/admin/complexes-offers')
@csrf.exempt
@admin_required
def admin_complexes_offers():
    """List all residential complexes for managing their offers"""
    from models import ResidentialComplex, Developer, Offer
    
    # Get search parameter
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    # Build query with developer info
    query = ResidentialComplex.query.join(Developer, isouter=True)
    
    # Apply search filter if provided
    if search:
        query = query.filter(ResidentialComplex.name.ilike(f'%{search}%'))
    
    # Order by name
    query = query.order_by(ResidentialComplex.name)
    
    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    complexes = pagination.items
    
    # Count active offers for each complex
    for complex in complexes:
        complex.offers_count = Offer.query.filter_by(
            residential_complex_id=complex.id, 
            is_active=True
        ).count()
    
    return render_template('admin/complexes_offers_list.html',
                         admin=current_user,
                         complexes=complexes,
                         pagination=pagination,
                         search=search)


@admin_bp.route('/admin/complex/<int:complex_id>/offers')
@csrf.exempt
@admin_required
def admin_complex_offers(complex_id):
    """List all offers for a residential complex"""
    from models import ResidentialComplex, Offer
    
    complex = ResidentialComplex.query.get_or_404(complex_id)
    offers = Offer.query.filter_by(residential_complex_id=complex_id).order_by(Offer.sort_order, Offer.created_at.desc()).all()
    
    return render_template('admin/complex_offers.html',
                         admin=current_user,
                         complex=complex,
                         offers=offers)


@admin_bp.route('/admin/complex/<int:complex_id>/offer/new')
@csrf.exempt
@admin_required
def admin_new_offer(complex_id):
    """Form to create new offer"""
    from models import ResidentialComplex
    
    complex = ResidentialComplex.query.get_or_404(complex_id)
    
    return render_template('admin/complex_offers.html',
                         admin=current_user,
                         complex=complex,
                         offers=[],
                         show_form=True,
                         edit_offer=None)


@admin_bp.route('/admin/complex/<int:complex_id>/offer/create', methods=['POST'])
@admin_required
def admin_create_offer(complex_id):
    """Create new offer with image upload"""
    from models import ResidentialComplex, Offer
    from werkzeug.utils import secure_filename
    import os
    from datetime import datetime
    
    complex = ResidentialComplex.query.get_or_404(complex_id)
    
    try:
        # Get form data
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        is_active = request.form.get('is_active') == 'on'
        sort_order = int(request.form.get('sort_order', 0))
        
        # Validate title
        if not title:
            flash('Название акции обязательно', 'error')
            return redirect(url_for('adm.admin_complex_offers', complex_id=complex_id))
        
        # Handle image upload
        image_file = request.files.get('image')
        if not image_file or image_file.filename == '':
            flash('Изображение обязательно для новой акции', 'error')
            return redirect(url_for('adm.admin_complex_offers', complex_id=complex_id))
        
        # Validate file type
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        filename = secure_filename(image_file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            flash('Неподдерживаемый формат изображения. Используйте JPG, PNG или WEBP', 'error')
            return redirect(url_for('adm.admin_complex_offers', complex_id=complex_id))
        
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        
        # Save file
        upload_folder = 'static/uploads/offers'
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, unique_filename)
        image_file.save(file_path)
        
        # Store relative path in database
        image_url = f'/static/uploads/offers/{unique_filename}'
        
        # Create offer
        offer = Offer(
            residential_complex_id=complex_id,
            title=title,
            description=description,
            image_url=image_url,
            is_active=is_active,
            sort_order=sort_order
        )
        
        db.session.add(offer)
        db.session.commit()
        
        flash('Акция успешно создана', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при создании акции: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_complex_offers', complex_id=complex_id))


@admin_bp.route('/admin/price-analytics')
@admin_required
def admin_price_analytics():
    return render_template('admin/price_analytics.html')



@admin_bp.route('/admin/offer/<int:offer_id>/edit')
@csrf.exempt
@admin_required
def admin_edit_offer(offer_id):
    """Form to edit offer"""
    from models import Offer
    
    offer = Offer.query.get_or_404(offer_id)
    complex_id = offer.residential_complex_id
    
    from models import ResidentialComplex
    complex = ResidentialComplex.query.get_or_404(complex_id)
    offers = Offer.query.filter_by(residential_complex_id=complex_id).order_by(Offer.sort_order, Offer.created_at.desc()).all()
    
    return render_template('admin/complex_offers.html',
                         admin=current_user,
                         complex=complex,
                         offers=offers,
                         show_form=True,
                         edit_offer=offer)


@admin_bp.route('/admin/offer/<int:offer_id>/update', methods=['POST'])
@admin_required
def admin_update_offer(offer_id):
    """Update offer"""
    from models import Offer
    from werkzeug.utils import secure_filename
    import os
    from datetime import datetime
    
    offer = Offer.query.get_or_404(offer_id)
    complex_id = offer.residential_complex_id
    
    try:
        # Update form data
        offer.title = request.form.get('title', '').strip()
        offer.description = request.form.get('description', '').strip()
        offer.is_active = request.form.get('is_active') == 'on'
        offer.sort_order = int(request.form.get('sort_order', 0))
        
        # Validate title
        if not offer.title:
            flash('Название акции обязательно', 'error')
            return redirect(url_for('adm.admin_complex_offers', complex_id=complex_id))
        
        # Handle image upload (optional for update)
        image_file = request.files.get('image')
        if image_file and image_file.filename != '':
            # Validate file type
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
            filename = secure_filename(image_file.filename)
            file_ext = os.path.splitext(filename)[1].lower()
            
            if file_ext not in allowed_extensions:
                flash('Неподдерживаемый формат изображения. Используйте JPG, PNG или WEBP', 'error')
                return redirect(url_for('adm.admin_complex_offers', complex_id=complex_id))
            
            # Delete old image if exists
            if offer.image_url:
                old_image_path = offer.image_url.lstrip('/')
                if os.path.exists(old_image_path):
                    try:
                        os.remove(old_image_path)
                    except:
                        pass
            
            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_filename = f"{timestamp}_{filename}"
            
            # Save file
            upload_folder = 'static/uploads/offers'
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, unique_filename)
            image_file.save(file_path)
            
            # Update image URL
            offer.image_url = f'/static/uploads/offers/{unique_filename}'
        
        offer.updated_at = datetime.utcnow()
        db.session.commit()
        
        flash('Акция успешно обновлена', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при обновлении акции: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_complex_offers', complex_id=complex_id))


@admin_bp.route('/admin/offer/<int:offer_id>/delete', methods=['POST'])
@csrf.exempt
@admin_required
def admin_delete_offer(offer_id):
    """Delete offer"""
    from models import Offer
    import os
    
    offer = Offer.query.get_or_404(offer_id)
    complex_id = offer.residential_complex_id
    
    try:
        # Delete image file if exists
        if offer.image_url:
            image_path = offer.image_url.lstrip('/')
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except:
                    pass
        
        db.session.delete(offer)
        db.session.commit()
        
        flash('Акция успешно удалена', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении акции: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_complex_offers', complex_id=complex_id))

# ==========================================
# Admin Marketing Materials Management Routes
# ==========================================


@admin_bp.route('/admin/complexes-materials')
@csrf.exempt
@admin_required
def admin_complexes_materials():
    """List all residential complexes for managing their marketing materials"""
    try:
        import logging
        from models import ResidentialComplex, Developer, MarketingMaterial
        from sqlalchemy import func
        from sqlalchemy.orm import joinedload
        
        logging.debug("Starting admin_complexes_materials")
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        logging.debug("Creating material_counts subquery")
        material_counts = db.session.query(
            MarketingMaterial.residential_complex_id,
            func.count(MarketingMaterial.id).label('materials_count')
        ).group_by(MarketingMaterial.residential_complex_id).subquery()
        
        logging.debug("Creating complexes_query")
        complexes_query = db.session.query(ResidentialComplex).options(
            joinedload(ResidentialComplex.developer)
        ).outerjoin(
            material_counts,
            ResidentialComplex.id == material_counts.c.residential_complex_id
        ).add_columns(
            func.coalesce(material_counts.c.materials_count, 0).label('materials_count')
        ).order_by(ResidentialComplex.name)
        
        logging.debug("Getting pagination")
        pagination = complexes_query.paginate(page=page, per_page=per_page, error_out=False)
        logging.debug(f"Pagination total: {pagination.total}, items: {len(pagination.items)}")
        
        complexes = []
        for i, row in enumerate(pagination.items):
            logging.debug(f"Processing row {i}: type={type(row)}, value={row}")
            complex_obj = row[0]
            materials_count = row[1]
            
            complexes.append({
                'id': complex_obj.id,
                'name': complex_obj.name,
                'address': complex_obj.address,
                'main_image': complex_obj.main_image,
                'developer': complex_obj.developer,
                'developer_name': complex_obj.developer.name if complex_obj.developer else 'Не указан',
                'materials_count': materials_count
            })
        
        logging.debug(f"Rendering template with {len(complexes)} complexes")
        return render_template('admin/complexes_materials_list.html',
                             admin=current_user,
                             complexes=complexes,
                             pagination=pagination)
    except Exception as e:
        import traceback
        import logging
        logging.error(f"ERROR in admin_complexes_materials: {str(e)}")
        logging.error(traceback.format_exc())
        return render_template('500.html'), 500




@admin_bp.route('/admin/complex/<int:complex_id>/materials')
@csrf.exempt
@admin_required
def admin_complex_materials(complex_id):
    """Manage marketing materials for a specific residential complex"""
    from models import ResidentialComplex, MarketingMaterial
    
    complex = ResidentialComplex.query.get_or_404(complex_id)
    materials = MarketingMaterial.query.filter_by(
        residential_complex_id=complex_id
    ).order_by(MarketingMaterial.sort_order, MarketingMaterial.created_at.desc()).all()
    
    return render_template('admin/complex_materials.html',
                         admin=current_user,
                         complex=complex,
                         materials=materials)



@admin_bp.route('/admin/complex/<int:complex_id>/material/create', methods=['POST'])
@admin_required
def admin_create_material(complex_id):
    """Create new marketing material with file upload"""
    from models import ResidentialComplex, MarketingMaterial
    from werkzeug.utils import secure_filename
    import os
    from datetime import datetime
    
    complex = ResidentialComplex.query.get_or_404(complex_id)
    
    try:
        # Get form data
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        material_type = request.form.get('material_type', 'other').strip()
        is_active = request.form.get('is_active') == 'on'
        sort_order = int(request.form.get('sort_order', 0))
        
        # Validate title
        if not title:
            flash('Название материала обязательно', 'error')
            return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
        
        # Validate material type
        allowed_material_types = ['brochure', 'photo', 'render', 'other']
        if material_type not in allowed_material_types:
            flash('Неверный тип материала', 'error')
            return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
        
        # Handle file upload
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Файл обязателен для нового материала', 'error')
            return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
        
        # Validate file type and size
        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        
        # Determine file type and validate
        if file_ext == '.pdf':
            file_type = 'pdf'
            max_size = 10 * 1024 * 1024  # 10MB
        elif file_ext in ['.jpg', '.jpeg', '.png', '.webp']:
            file_type = 'image'
            max_size = 5 * 1024 * 1024  # 5MB
        else:
            flash('Неподдерживаемый формат файла. Используйте PDF, JPG, PNG или WEBP', 'error')
            return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
        
        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > max_size:
            max_size_mb = max_size / (1024 * 1024)
            flash(f'Размер файла превышает максимально допустимый ({max_size_mb}MB)', 'error')
            return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
        
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        
        # Save file
        upload_folder = 'static/uploads/marketing_materials'
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        # Store relative path in database
        file_url = f'/static/uploads/marketing_materials/{unique_filename}'
        
        # Create marketing material
        material = MarketingMaterial(
            residential_complex_id=complex_id,
            title=title,
            description=description,
            file_url=file_url,
            file_type=file_type,
            material_type=material_type,
            is_active=is_active,
            sort_order=sort_order
        )
        
        db.session.add(material)
        db.session.commit()
        
        flash('Материал успешно создан', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при создании материала: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))



@admin_bp.route('/admin/material/<int:material_id>/update', methods=['POST'])
@admin_required
def admin_update_material(material_id):
    """Update marketing material"""
    from models import MarketingMaterial
    from werkzeug.utils import secure_filename
    import os
    from datetime import datetime
    
    material = MarketingMaterial.query.get_or_404(material_id)
    complex_id = material.residential_complex_id
    
    try:
        # Get form data
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        material_type = request.form.get('material_type', 'other').strip()
        is_active = request.form.get('is_active') == 'on'
        sort_order = int(request.form.get('sort_order', 0))
        
        # Validate title
        if not title:
            flash('Название материала обязательно', 'error')
            return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
        
        # Validate material type
        allowed_material_types = ['brochure', 'photo', 'render', 'other']
        if material_type not in allowed_material_types:
            flash('Неверный тип материала', 'error')
            return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
        
        # Update basic fields
        material.title = title
        material.description = description
        material.material_type = material_type
        material.is_active = is_active
        material.sort_order = sort_order
        
        # Handle file replacement (optional)
        file = request.files.get('file')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file_ext = os.path.splitext(filename)[1].lower()
            
            # Determine file type and validate
            if file_ext == '.pdf':
                file_type = 'pdf'
                max_size = 10 * 1024 * 1024  # 10MB
            elif file_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                file_type = 'image'
                max_size = 5 * 1024 * 1024  # 5MB
            else:
                flash('Неподдерживаемый формат файла. Используйте PDF, JPG, PNG или WEBP', 'error')
                return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
            
            # Check file size
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            
            if file_size > max_size:
                max_size_mb = max_size / (1024 * 1024)
                flash(f'Размер файла превышает максимально допустимый ({max_size_mb}MB)', 'error')
                return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))
            
            # Delete old file if exists
            if material.file_url:
                old_file_path = material.file_url.lstrip('/')
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                    except:
                        pass
            
            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_filename = f"{timestamp}_{filename}"
            
            # Save new file
            upload_folder = 'static/uploads/marketing_materials'
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, unique_filename)
            file.save(file_path)
            
            # Update file info in database
            material.file_url = f'/static/uploads/marketing_materials/{unique_filename}'
            material.file_type = file_type
        
        db.session.commit()
        flash('Материал успешно обновлен', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при обновлении материала: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_complex_materials', complex_id=complex_id))



@admin_bp.route('/admin/material/<int:material_id>/delete', methods=['POST'])
@csrf.exempt
@admin_required
def admin_delete_material(material_id):
    """Delete marketing material"""
    from models import MarketingMaterial
    import os
    
    material = MarketingMaterial.query.get_or_404(material_id)
    complex_id = material.residential_complex_id
    
    try:
        # Delete file if exists
        if material.file_url:
            file_path = material.file_url.lstrip('/')
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
        
        db.session.delete(material)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Материал успешно удален'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# Admin Complex Cashback Management Routes

@admin_bp.route('/admin/complexes/cashback')
@admin_required
def admin_complex_cashback():
    """Complex cashback management page — all JK, client-side filter/sort"""
    rows = db.session.execute(text("""
        SELECT
            rc.id, rc.name, rc.slug, rc.is_active,
            rc.cashback_rate, rc.max_cashback_amount,
            rc.main_image, rc.address, rc.city_id,
            rc.end_build_year, rc.end_build_quarter,
            rc.object_class_display_name,
            COALESCE(d.name, 'Не указан')  AS dev_name,
            COALESCE(ci.name, '—')         AS city_name,
            COUNT(DISTINCT CASE WHEN p.is_active THEN p.id END) AS apt_count,
            COALESCE(MIN(CASE WHEN p.is_active THEN p.price END), 0) AS price_min
        FROM residential_complexes rc
        LEFT JOIN developers d  ON d.id  = rc.developer_id
        LEFT JOIN cities ci     ON ci.id = rc.city_id
        LEFT JOIN properties p  ON p.complex_id = rc.id
        GROUP BY rc.id, rc.name, rc.slug, rc.is_active,
                 rc.cashback_rate, rc.max_cashback_amount,
                 rc.main_image, rc.address, rc.city_id,
                 rc.end_build_year, rc.end_build_quarter,
                 rc.object_class_display_name,
                 d.name, ci.name
        ORDER BY rc.cashback_rate DESC NULLS LAST, apt_count DESC, rc.name
    """)).fetchall()

    cities = db.session.execute(text(
        "SELECT id, name FROM cities ORDER BY name"
    )).fetchall()

    total       = len(rows)
    with_cb     = sum(1 for r in rows if r.cashback_rate and r.cashback_rate > 0)
    avg_cb      = (sum(r.cashback_rate for r in rows if r.cashback_rate) / with_cb) if with_cb else 0
    max_cb      = max((r.cashback_rate or 0) for r in rows) if rows else 0

    return render_template('admin/complex_cashback.html',
                           admin=current_user,
                           complexes=rows,
                           cities=cities,
                           total=total,
                           with_cb=with_cb,
                           avg_cb=avg_cb,
                           max_cb=max_cb)


@admin_bp.route('/admin/complex-cashback/<int:complex_id>/update-cashback', methods=['POST'])
@csrf.exempt  # CSRF disabled for admin routes
@admin_required
def update_complex_cashback(complex_id):
    """API endpoint to update complex cashback rate"""
    from models import ResidentialComplex
    
    try:
        complex = ResidentialComplex.query.get_or_404(complex_id)
        
        data = request.get_json()
        cashback_percent = data.get('cashback_percent')
        
        if cashback_percent is None:
            return jsonify({'success': False, 'message': 'Не указан процент кешбека'})
        
        # Validate percentage
        try:
            cashback_percent = float(cashback_percent)
            if cashback_percent < 0 or cashback_percent > 15:
                return jsonify({'success': False, 'message': 'Процент должен быть от 0% до 15%'})
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Неверный формат процента'})
        
        # Update cashback rate
        complex.cashback_rate = cashback_percent
        complex.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Кешбек успешно обновлен',
            'cashback_percent': cashback_percent,
            'complex_name': complex.name
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating complex cashback: {e}")
        return jsonify({'success': False, 'message': 'Ошибка сервера'})


@admin_bp.route('/admin/complexes/cashback/create', methods=['GET', 'POST'])
@admin_required
def admin_create_complex_cashback():
    """Create new complex cashback settings"""
    from models import Admin, ResidentialComplex, District, Developer
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    if request.method == 'POST':
        name = request.form.get('name')
        developer_id = request.form.get('developer_id')
        district_id = request.form.get('district_id') 
        cashback_rate = request.form.get('cashback_rate', 5.0)
        
        try:
            # Create new complex
            complex = ResidentialComplex(
                name=name,
                slug=name.lower().replace(' ', '-'),
                developer_id=int(developer_id) if developer_id else None,
                district_id=int(district_id) if district_id else None,
                cashback_rate=float(cashback_rate),
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.session.add(complex)
            db.session.commit()
            
            flash('ЖК успешно создан', 'success')
            return redirect(url_for('adm.admin_complex_cashback'))
            
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при создании ЖК', 'error')
    
    # Load data for form
    developers = Developer.query.filter_by(is_active=True).order_by(Developer.name).all()
    districts = District.query.filter_by(is_active=True).order_by(District.name).all()
    
    return render_template('admin/create_complex_cashback.html',
                         admin=current_admin,
                         developers=developers,
                         districts=districts)


@admin_bp.route('/admin/complexes/cashback/<int:complex_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_complex_cashback(complex_id):
    """Edit complex cashback settings"""
    from models import ResidentialComplex, District, Developer
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    complex_item = ResidentialComplex.query.get_or_404(complex_id)
    
    if request.method == 'POST':
        complex_item.name = request.form.get('name') or request.form.get('complex_name')
        complex_item.developer_id = int(request.form.get('developer_id')) if request.form.get('developer_id') else None
        complex_item.district_id = int(request.form.get('district_id')) if request.form.get('district_id') else None
        
        # Handle cashback_rate
        try:
            cashback_rate = request.form.get('cashback_rate')
            if cashback_rate:
                complex_item.cashback_rate = float(cashback_rate.replace(',', '.'))
        except (ValueError, TypeError):
            pass

        complex_item.is_active = request.form.get('is_active') == 'on' or request.form.get('is_active') == '1'
        complex_item.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('ЖК успешно обновлен', 'success')
            return redirect(url_for('adm.admin_complex_cashback'))
        except Exception as e:
            db.session.rollback()
            print(f"Error updating complex {complex_id}: {e}")
            flash(f'Ошибка при обновлении ЖК: {str(e)}', 'error')
    
    # Load data for form
    developers = Developer.query.filter_by(is_active=True).order_by(Developer.name).all()
    districts = District.query.order_by(District.name).all()
    
    return render_template('admin/edit_complex_cashback.html',
                         admin=current_admin,
                         complex=complex_item,
                         developers=developers,
                         districts=districts)


@admin_bp.route('/admin/complexes/cashback/<int:complex_id>/delete', methods=['POST'])
@admin_required
def admin_delete_complex_cashback(complex_id):
    """Delete complex cashback settings"""
    from models import ResidentialComplex
    
    complex = ResidentialComplex.query.get_or_404(complex_id)
    
    try:
        db.session.delete(complex)
        db.session.commit()
        flash('ЖК успешно удален', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ошибка при удалении ЖК', 'error')
    
    return redirect(url_for('adm.admin_complex_cashback'))

# Helper function for secure image validation

@admin_bp.route('/admin/complex/<int:complex_id>/update-nearby', methods=['POST'])
@login_required
def admin_update_complex_nearby(complex_id):
    """Обновить близлежащие объекты для ЖК через OpenStreetMap API"""
    from models import Admin as _Admin
    if not isinstance(current_user._get_current_object(), _Admin):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        # Получаем ЖК из БД
        complex = db.session.query(ResidentialComplex).get(complex_id)
        if not complex:
            return jsonify({'success': False, 'error': 'ЖК не найден'}), 404
        
        # Проверяем наличие координат
        if not complex.latitude or not complex.longitude:
            return jsonify({
                'success': False,
                'error': 'У ЖК не указаны координаты. Добавьте широту и долготу для автоматического поиска.'
            }), 400
        
        # Получаем близлежащие объекты через Overpass API
        print(f"Fetching nearby places for {complex.name} at {complex.latitude}, {complex.longitude}")
        nearby_data = nearby_places.fetch_nearby_places(
            latitude=float(complex.latitude),
            longitude=float(complex.longitude),
            radius_meters=3000
        )
        
        # Сохраняем в БД
        complex.nearby = json.dumps(nearby_data, ensure_ascii=False)
        complex.nearby_updated_at = datetime.utcnow()
        db.session.commit()
        
        # Подсчитываем количество найденных объектов
        total_found = sum(len(nearby_data.get(cat, [])) for cat in ['transport', 'shopping', 'education', 'healthcare', 'leisure'])
        
        return jsonify({
            'success': True,
            'message': f'Близлежащие объекты обновлены. Найдено объектов: {total_found}',
            'data': {
                'transport': len(nearby_data.get('transport', [])),
                'shopping': len(nearby_data.get('shopping', [])),
                'education': len(nearby_data.get('education', [])),
                'healthcare': len(nearby_data.get('healthcare', [])),
                'leisure': len(nearby_data.get('leisure', [])),
                'total': total_found
            }
        })
    
    except Exception as e:
        print(f"Error updating nearby places: {e}")



@admin_bp.route('/admin/nearby/auto-update', methods=['POST'])
@csrf.exempt
@login_required  
def admin_auto_update_nearby():
    """Автоматически обновить nearby для ЖК без данных (добавленных парсером)"""
    from models import Admin as _Admin
    if not isinstance(current_user._get_current_object(), _Admin):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        import nearby_auto_updater
        
        # Получаем параметры
        batch_size = int(request.form.get('batch_size', 5))
        
        # Запускаем обновление
        stats = nearby_auto_updater.process_batch(
            batch_size=batch_size,
            delay_between=2
        )
        
        return jsonify({
            'success': True,
            'stats': stats,
            'message': f"Обновлено {stats['success']} из {stats['total']} ЖК. Найдено {stats['objects_total']} объектов."
        })
    
    except Exception as e:
        print(f"Error in auto-update: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500



@admin_bp.route('/admin/nearby/status', methods=['GET'])
@login_required
def admin_nearby_status():
    """Получить статистику по nearby данным"""
    from models import Admin as _Admin
    if not isinstance(current_user._get_current_object(), _Admin):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        from datetime import timedelta
        
        # Статистика
        total_complexes = db.session.query(ResidentialComplex).filter(
            ResidentialComplex.latitude.isnot(None),
            ResidentialComplex.longitude.isnot(None)
        ).count()
        
        with_nearby = db.session.query(ResidentialComplex).filter(
            ResidentialComplex.nearby.isnot(None),
            ResidentialComplex.nearby_updated_at.isnot(None)
        ).count()
        
        without_nearby = db.session.query(ResidentialComplex).filter(
            ResidentialComplex.latitude.isnot(None),
            ResidentialComplex.longitude.isnot(None),
            db.or_(
                ResidentialComplex.nearby.is_(None),
                ResidentialComplex.nearby_updated_at.is_(None)
            )
        ).count()
        
        six_months_ago = datetime.utcnow() - timedelta(days=180)
        outdated = db.session.query(ResidentialComplex).filter(
            ResidentialComplex.nearby_updated_at < six_months_ago
        ).count()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_with_coordinates': total_complexes,
                'with_nearby_data': with_nearby,
                'without_nearby_data': without_nearby,
                'outdated': outdated,
                'completion_rate': round((with_nearby / total_complexes * 100) if total_complexes > 0 else 0, 1)
            }
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


        import traceback



@admin_bp.route('/admin/nearby-manager')
@login_required
def admin_nearby_manager():
    """Страница управления автообновлением nearby данных"""
    from models import Admin as _Admin
    if not isinstance(current_user._get_current_object(), _Admin):
        abort(403)
    
    from datetime import timedelta
    from models import ResidentialComplex
    
    # Статистика
    total_complexes = db.session.query(ResidentialComplex).filter(
        ResidentialComplex.latitude.isnot(None),
        ResidentialComplex.longitude.isnot(None)
    ).count()
    
    with_nearby = db.session.query(ResidentialComplex).filter(
        ResidentialComplex.nearby.isnot(None),
        ResidentialComplex.nearby_updated_at.isnot(None)
    ).count()
    
    without_nearby = db.session.query(ResidentialComplex).filter(
        ResidentialComplex.latitude.isnot(None),
        ResidentialComplex.longitude.isnot(None),
        db.or_(
            ResidentialComplex.nearby.is_(None),
            ResidentialComplex.nearby_updated_at.is_(None)
        )
    ).all()
    
    six_months_ago = datetime.utcnow() - timedelta(days=180)
    outdated = db.session.query(ResidentialComplex).filter(
        ResidentialComplex.nearby_updated_at < six_months_ago
    ).all()
    
    stats = {
        'total': total_complexes,
        'with_data': with_nearby,
        'without_data_count': len(without_nearby),
        'without_data': without_nearby[:10],  # Показать первые 10
        'outdated_count': len(outdated),
        'outdated': outdated[:10],
        'completion_rate': round((with_nearby / total_complexes * 100) if total_complexes > 0 else 0, 1)
    }
    
    # Also get distance stats
    with_distance = db.session.query(ResidentialComplex).filter(
        ResidentialComplex.distance_to_center.isnot(None)
    ).count()
    stats['with_distance'] = with_distance
    stats['without_distance'] = total_complexes - with_distance

    # APScheduler next run times for relevant jobs
    try:
        from routes.admin_api import scheduler as _sched
        import pytz
        moscow_tz = pytz.timezone('Europe/Moscow')
        schedule_info = {}
        for job in _sched.get_jobs():
            if job.id in ('complex_nearby_job', 'complex_distances_job'):
                nxt = job.next_run_time
                schedule_info[job.id] = nxt.astimezone(moscow_tz).strftime('%d.%m.%Y %H:%M МСК') if nxt else 'Не запланировано'
    except Exception:
        schedule_info = {}
    stats['schedule_info'] = schedule_info

    from models import City as _City
    cities = _City.query.filter_by(is_active=True).order_by(_City.name).all()
    return render_template('admin/nearby_manager.html', admin=current_user, stats=stats, cities=cities)


# ── Globals for nearby/distance background jobs ──────────────────────────────
NEARBY_LOG_FILE  = os.path.join(_SCRIPTS_DIR, '.nearby_run.log')
NEARBY_PID_FILE  = os.path.join(_SCRIPTS_DIR, '.nearby_pid')
NEARBY_SETTINGS_FILE = os.path.join(_SCRIPTS_DIR, '.nearby_settings.json')
_nearby_proc = None


def _nearby_is_running():
    global _nearby_proc
    if _nearby_proc is not None and _nearby_proc.poll() is None:
        return True
    if os.path.exists(NEARBY_PID_FILE):
        try:
            with open(NEARBY_PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            pass
    return False


def _load_nearby_settings():
    defaults = {'proxy_url': '', 'proxy_pool': [], 'delay': 1.5, 'radius': 1500}
    try:
        if os.path.exists(NEARBY_SETTINGS_FILE):
            with open(NEARBY_SETTINGS_FILE) as f:
                return {**defaults, **json.load(f)}
    except Exception:
        pass
    return defaults


@admin_bp.route('/admin/nearby/run-full', methods=['POST'])
@admin_required
def admin_nearby_run_full():
    """Start update_complex_nearby.py as background subprocess."""
    global _nearby_proc
    if _nearby_is_running():
        return jsonify({'success': False, 'message': 'Задача уже выполняется'})
    script = os.path.join(_SCRIPTS_DIR, 'update_complex_nearby.py')
    if not os.path.exists(script):
        return jsonify({'success': False, 'message': 'Скрипт update_complex_nearby.py не найден'})
    settings = _load_nearby_settings()
    data = request.get_json(silent=True) or {}
    proxy_url = data.get('proxy_url', settings.get('proxy_url', ''))
    city_id = data.get('city_id')
    env = {**os.environ}
    if proxy_url:
        env['HTTP_PROXY']  = proxy_url
        env['HTTPS_PROXY'] = proxy_url
        env['NEARBY_PROXY'] = proxy_url
    cmd = ['python3', '-u', script]
    if city_id:
        cmd += ['--city', str(city_id)]
    import subprocess as _subprocess
    log_f = open(NEARBY_LOG_FILE, 'w')
    _nearby_proc = _subprocess.Popen(cmd, env=env,
                                      stdout=log_f, stderr=_subprocess.STDOUT,
                                      start_new_session=True)
    with open(NEARBY_PID_FILE, 'w') as f:
        f.write(str(_nearby_proc.pid))
    city_note = f' (город ID={city_id})' if city_id else ' (все города)'
    return jsonify({'success': True, 'message': f'Обогащение инфраструктуры запущено{city_note} (PID {_nearby_proc.pid})'})



@admin_bp.route('/admin/nearby/run-distances', methods=['POST'])
@admin_required
def admin_nearby_run_distances():
    """Recalculate distance_to_center for all complexes synchronously."""
    try:
        from routes.admin_api import run_update_complex_distances
        run_update_complex_distances()
        return jsonify({'success': True, 'message': 'Расстояния до центра пересчитаны для всех ЖК'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500



@admin_bp.route('/admin/nearby/job-status')
@admin_required
def admin_nearby_job_status():
    running = _nearby_is_running()
    log_tail = ''
    try:
        if os.path.exists(NEARBY_LOG_FILE):
            with open(NEARBY_LOG_FILE, 'r', errors='replace') as f:
                lines = f.readlines()
            log_tail = ''.join(lines[-50:])
    except Exception:
        pass
    # Count current progress
    try:
        from models import ResidentialComplex as _RC
        with_nearby = _RC.query.filter(_RC.nearby.isnot(None)).count()
        total = _RC.query.count()
        with_dist = _RC.query.filter(_RC.distance_to_center.isnot(None)).count()
    except Exception:
        with_nearby = total = with_dist = 0
    return jsonify({'running': running, 'log': log_tail,
                    'with_nearby': with_nearby, 'total': total, 'with_dist': with_dist})



@admin_bp.route('/admin/nearby/stop', methods=['POST'])
@admin_required
def admin_nearby_stop():
    global _nearby_proc
    stopped = False
    if _nearby_proc is not None and _nearby_proc.poll() is None:
        _nearby_proc.terminate()
        stopped = True
    if os.path.exists(NEARBY_PID_FILE):
        try:
            with open(NEARBY_PID_FILE) as f:
                pid = int(f.read().strip())
            import signal as _signal
            os.kill(pid, _signal.SIGTERM)
            stopped = True
        except Exception:
            pass
        os.remove(NEARBY_PID_FILE)
    return jsonify({'success': True, 'message': 'Задача остановлена' if stopped else 'Задача не запущена'})



@admin_bp.route('/admin/nearby/save-settings', methods=['POST'])
@admin_required
def admin_nearby_save_settings():
    data = request.get_json(force=True) or {}
    settings = _load_nearby_settings()
    settings.update({k: data[k] for k in ('proxy_url', 'proxy_pool', 'delay', 'radius') if k in data})
    try:
        with open(NEARBY_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@admin_bp.route('/admin/managers/create', methods=['GET', 'POST'])
@admin_required
def admin_create_manager():
    """Create new manager"""
    from models import Admin, Manager
    from werkzeug.security import generate_password_hash
    import json
    import random
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    if request.method == 'POST':
        full_name = request.form.get('full_name', '')
        email = request.form.get('email')
        phone = request.form.get('phone')
        position = request.form.get('position', 'Менеджер')
        password = request.form.get('password', 'demo123')  # Default password
        password_confirm = request.form.get('password_confirm', 'demo123')
        is_active = request.form.get('is_active') != 'False'  # Default True
        
        # Handle profile image (file upload or URL)
        profile_image = None
        profile_image_file = request.files.get('profile_image_file')
        profile_image_url = request.form.get('profile_image_url')
        
        if profile_image_file and profile_image_file.filename:
            try:
                import os
                import uuid
                from werkzeug.utils import secure_filename
                _fname = secure_filename(profile_image_file.filename)
                _ext = os.path.splitext(_fname)[1].lower()
                _allowed = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
                if _ext not in _allowed:
                    flash('Недопустимый формат файла. Используйте JPG, PNG или WebP.', 'error')
                    from models import OrgRole, Department
                    _roles = OrgRole.query.filter_by(is_active=True).order_by(OrgRole.level.desc()).all()
                    _depts = Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()
                    return render_template('admin/create_manager.html', admin=current_admin, roles=_roles, departments=_depts)
                upload_dir = 'static/uploads/managers'
                os.makedirs(upload_dir, exist_ok=True)
                unique_filename = f"{uuid.uuid4().hex}{_ext}"
                filepath = os.path.join(upload_dir, unique_filename)
                profile_image_file.save(filepath)
                profile_image = f'/{filepath}'
            except Exception as e:
                flash(f'Ошибка загрузки файла: {str(e)}', 'error')
                profile_image = None
        elif profile_image_url:
            profile_image = profile_image_url
        else:
            profile_image = None
        
        # Split full name into first and last name
        name_parts = full_name.split(' ', 1)
        first_name = name_parts[0] if name_parts else 'Имя'
        last_name = name_parts[1] if len(name_parts) > 1 else 'Фамилия'
        
        # Validate passwords
        if password != password_confirm:
            flash('Пароли не совпадают', 'error')
            from models import OrgRole, Department
            _roles = OrgRole.query.filter_by(is_active=True).order_by(OrgRole.level.desc()).all()
            _depts = Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()
            return render_template('admin/create_manager.html', admin=current_admin, roles=_roles, departments=_depts)
        
        if not password:
            password = 'demo123'  # Default password
        
        # Check if email already exists
        if email:
            existing_manager = Manager.query.filter_by(email=email).first()
            if existing_manager:
                flash('Менеджер с таким email уже существует', 'error')
                from models import OrgRole, Department
                _roles = OrgRole.query.filter_by(is_active=True).order_by(OrgRole.level.desc()).all()
                _depts = Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()
                return render_template('admin/create_manager.html', admin=current_admin, roles=_roles, departments=_depts)
        
        # Create manager
        manager = Manager()
        manager.email = email or f'manager{random.randint(1000,9999)}@inback.ru'
        manager.first_name = _capitalize_name(first_name)
        manager.last_name = _capitalize_name(last_name)
        manager.phone = _normalize_phone(phone)
        manager.position = position
        manager.profile_image = profile_image or '/static/images/no-photo.svg'
        manager.set_password(password)
        manager.is_active = is_active
        
        org_role_id = request.form.get('org_role_id')
        department_id = request.form.get('department_id')
        manager.org_role_id = int(org_role_id) if org_role_id else None
        manager.department_id = int(department_id) if department_id else None
        
        if manager.org_role_id:
            from models import OrgRole
            _role = OrgRole.query.get(manager.org_role_id)
            manager.is_rop = bool(_role and _role.key in ('rop', 'director'))
        else:
            manager.is_rop = False
        
        try:
            db.session.add(manager)
            db.session.commit()
            flash('Менеджер успешно создан', 'success')
            return redirect(url_for('adm.admin_managers'))
        except Exception as e:
            db.session.rollback()
            print(f"ERROR creating manager: {str(e)}")
            import traceback
            traceback.print_exc()
            flash(f'Ошибка при создании менеджера: {str(e)}', 'error')
    
    from models import OrgRole, Department
    try:
        roles = OrgRole.query.filter_by(is_active=True).order_by(OrgRole.level.desc()).all()
    except Exception:
        roles = []
    try:
        departments = Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()
    except Exception:
        departments = []
    return render_template('admin/create_manager.html', admin=current_admin, roles=roles, departments=departments)


@admin_bp.route('/admin/managers/<int:manager_id>/delete', methods=['POST'])
@admin_required
def admin_delete_manager(manager_id):
    """Delete manager with option to reassign deals"""
    from models import (Manager, ManagerFavoriteProperty, ManagerFavoriteComplex,
                        ManagerSavedSearch, ManagerComparison, Collection, User,
                        Deal, DealComment, DealTask, DealHistory, ManagerNotification,
                        ManagerCheckin, Department)
    
    manager = Manager.query.get_or_404(manager_id)
    reassign_to_id = request.form.get('reassign_to', '', type=str)
    reassign_manager = None
    
    if reassign_to_id:
        reassign_manager = Manager.query.get(int(reassign_to_id))
    
    try:
        if reassign_manager:
            Deal.query.filter_by(manager_id=manager_id).update(
                {'manager_id': reassign_manager.id}, synchronize_session=False)
            DealComment.query.filter_by(author_id=manager_id).update(
                {'author_id': reassign_manager.id}, synchronize_session=False)
            DealTask.query.filter_by(author_id=manager_id).update(
                {'author_id': reassign_manager.id}, synchronize_session=False)
            DealHistory.query.filter_by(author_id=manager_id).update(
                {'author_id': reassign_manager.id}, synchronize_session=False)
            User.query.filter_by(assigned_manager_id=manager_id).update(
                {'assigned_manager_id': reassign_manager.id}, synchronize_session=False)
            Collection.query.filter_by(created_by_manager_id=manager_id).update(
                {'created_by_manager_id': reassign_manager.id}, synchronize_session=False)
        else:
            deals = Deal.query.filter_by(manager_id=manager_id).all()
            deal_ids = [d.id for d in deals]
            if deal_ids:
                DealHistory.query.filter(DealHistory.deal_id.in_(deal_ids)).delete(synchronize_session=False)
                DealComment.query.filter(DealComment.deal_id.in_(deal_ids)).delete(synchronize_session=False)
                DealTask.query.filter(DealTask.deal_id.in_(deal_ids)).delete(synchronize_session=False)
                Deal.query.filter(Deal.id.in_(deal_ids)).delete(synchronize_session=False)
            User.query.filter_by(assigned_manager_id=manager_id).update(
                {'assigned_manager_id': None}, synchronize_session=False)
            Collection.query.filter_by(created_by_manager_id=manager_id).delete(synchronize_session=False)

        ManagerFavoriteProperty.query.filter_by(manager_id=manager_id).delete(synchronize_session=False)
        ManagerFavoriteComplex.query.filter_by(manager_id=manager_id).delete(synchronize_session=False)
        ManagerSavedSearch.query.filter_by(manager_id=manager_id).delete(synchronize_session=False)
        ManagerComparison.query.filter_by(manager_id=manager_id).delete(synchronize_session=False)
        
        try:
            ManagerNotification.query.filter_by(manager_id=manager_id).delete(synchronize_session=False)
        except Exception:
            pass
        try:
            ManagerCheckin.query.filter_by(manager_id=manager_id).delete(synchronize_session=False)
        except Exception:
            pass
        try:
            Department.query.filter_by(head_manager_id=manager_id).update(
                {'head_manager_id': None}, synchronize_session=False)
        except Exception:
            pass
        
        db.session.delete(manager)
        db.session.commit()
        
        if reassign_manager:
            flash(f'Менеджер удален. Сделки и клиенты переданы: {reassign_manager.full_name}', 'success')
        else:
            flash('Менеджер успешно удален', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting manager: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Ошибка при удалении менеджера: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_managers'))


@admin_bp.route('/admin/managers/<int:manager_id>/toggle-status', methods=['POST'])
@admin_required
def admin_toggle_manager_status(manager_id):
    """Toggle manager active status"""
    from models import Manager
    
    manager = Manager.query.get_or_404(manager_id)
    manager.is_active = not manager.is_active
    
    try:
        db.session.commit()
        status = 'активирован' if manager.is_active else 'заблокирован'
        flash(f'Менеджер {status}', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ошибка при изменении статуса менеджера', 'error')
    
    return redirect(url_for('adm.admin_managers'))

# Additional Pages Routes

@admin_bp.route('/admin/blog-manager')
@manager_required
def admin_blog_manager():
    """Manager blog management page"""
    from models import BlogArticle, Category
    
    try:
        # Get filter parameters
        search = request.args.get('search', '')
        status = request.args.get('status', '')
        category_id = request.args.get('category_id', '')
        
        # Build query
        query = BlogArticle.query
        
        if search:
            query = query.filter(BlogArticle.title.contains(search) | 
                               BlogArticle.content.contains(search))
        
        if status:
            query = query.filter(BlogArticle.status == status)
            
        if category_id:
            query = query.filter(BlogArticle.category_id == int(category_id))
        
        # Order by creation date
        articles = query.order_by(BlogArticle.created_at.desc()).all()
        
        # Get categories for filter dropdown
        categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
        
        return render_template('admin/blog_manager.html',
                             articles=articles,
                             categories=categories,
                             search=search,
                             status=status,
                             category_id=category_id)
        
    except Exception as e:
        flash(f'Ошибка загрузки блога: {str(e)}', 'error')
        return redirect(url_for('mgr.manager_dashboard'))



@admin_bp.route('/admin/blog/create-new', methods=['GET', 'POST'])
@manager_required
def admin_create_new_article():
    """Create new blog article"""
    from models import Category, BlogArticle
    import re
    from datetime import datetime
    
    if request.method == 'GET':
        categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
        return render_template('admin/blog_create_new.html', categories=categories)
    
    try:
        # Get form data
        title = request.form.get('title')
        excerpt = request.form.get('excerpt')
        content = request.form.get('content')
        category_id = request.form.get('category_id')
        status = request.form.get('status', 'draft')
        is_featured = 'is_featured' in request.form
        
        # Generate slug from title
        slug = re.sub(r'[^\w\s-]', '', (title or '').lower())
        slug = re.sub(r'[-\s]+', '-', slug).strip('-')
        
        # Ensure slug is unique
        original_slug = slug
        counter = 1
        while BlogArticle.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1
        
        # Create article
        article = BlogArticle(
            title=title,
            slug=slug,
            excerpt=excerpt,
            content=content,
            category_id=int(category_id),
            author_id=current_user.id,
            status=status,
            is_featured=is_featured
        )
        
        # Set publish date if status is published
        if status == 'published':
            article.published_at = datetime.utcnow()
        
        # Calculate reading time (approx 200 words per minute)
        word_count = len(content.split()) if content else 0
        article.reading_time = max(1, word_count // 200)
        
        db.session.add(article)
        db.session.commit()
        
        flash('Статья успешно создана!', 'success')
        return redirect(url_for('adm.admin_blog_manager'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка создания статьи: {str(e)}', 'error')
        return redirect(url_for('adm.admin_create_new_article'))



@admin_bp.route('/admin/blog/<int:article_id>/edit-article', methods=['GET', 'POST'])
@manager_required 
def admin_edit_new_article(article_id):
    """Edit existing blog article"""
    from models import BlogArticle, Category
    import re
    from datetime import datetime
    
    article = BlogArticle.query.get_or_404(article_id)
    
    if request.method == 'GET':
        categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
        return render_template('admin/blog_edit_new.html', article=article, categories=categories)
    
    try:
        # Get form data
        title = request.form.get('title')
        excerpt = request.form.get('excerpt') 
        content = request.form.get('content')
        category_id = request.form.get('category_id')
        status = request.form.get('status')
        is_featured = 'is_featured' in request.form
        
        # Update slug if title changed
        if title != article.title:
            slug = re.sub(r'[^\w\s-]', '', (title or '').lower())
            slug = re.sub(r'[-\s]+', '-', slug).strip('-')
            
            # Ensure slug is unique (exclude current article)
            original_slug = slug
            counter = 1
            while BlogArticle.query.filter_by(slug=slug).filter(BlogArticle.id != article_id).first():
                slug = f"{original_slug}-{counter}"
                counter += 1
            
            article.slug = slug
        
        # Update article
        article.title = title
        article.excerpt = excerpt
        article.content = content
        article.category_id = int(category_id)
        article.status = status
        article.is_featured = is_featured
        article.updated_at = datetime.utcnow()
        
        # Set/update publish date if status changed to published
        if status == 'published' and not article.published_at:
            article.published_at = datetime.utcnow()
        
        # Recalculate reading time
        word_count = len(content.split()) if content else 0
        article.reading_time = max(1, word_count // 200)
        
        db.session.commit()
        
        flash('Статья успешно обновлена!', 'success')
        return redirect(url_for('adm.admin_blog_manager'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления статьи: {str(e)}', 'error')
        return redirect(url_for('adm.admin_edit_new_article', article_id=article_id))



@admin_bp.route('/admin/blog/<int:article_id>/delete-article', methods=['POST'])
@manager_required
def admin_delete_new_article(article_id):
    """Delete blog article"""
    from models import BlogArticle
    
    try:
        article = BlogArticle.query.get_or_404(article_id)
        db.session.delete(article)
        db.session.commit()
        
        flash('Статья успешно удалена!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления статьи: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_blog_manager'))



@admin_bp.route('/admin/blog/news-enricher', methods=['GET'])
@admin_required
def admin_blog_news_enricher():
    """News enricher — fetch real-estate news from RSS and uniqualize."""
    from models import BlogPost
    from services.news_enricher import RSS_SOURCES
    recent_posts = BlogPost.query.order_by(BlogPost.created_at.desc()).limit(8).all()
    has_openai = bool(os.environ.get('OPENAI_API_KEY'))
    return render_template('admin/blog_news_enricher.html',
                           admin=current_user,
                           rss_sources=RSS_SOURCES,
                           recent_posts=recent_posts,
                           has_openai=has_openai)


@admin_bp.route('/admin/blog/news-enricher/check-sources', methods=['GET'])
@csrf.exempt
@admin_required
def admin_blog_news_enricher_check():
    """Quick health-check of all RSS sources."""
    from services.news_enricher import check_sources_status
    try:
        results = check_sources_status()
        return jsonify({'ok': True, 'sources': results})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


import threading as _threading
import uuid as _uuid

# In-memory job store: {job_id: {status, stats, error, progress}}
_enricher_jobs: dict = {}


@admin_bp.route('/admin/blog/news-enricher/fetch', methods=['POST'])
@csrf.exempt
@admin_required
def admin_blog_news_enricher_fetch():
    """Start news enrichment in background thread; returns job_id for polling."""
    from services.news_enricher import run_enrichment, RSS_SOURCES

    try:
        source_indices = request.form.getlist('sources')
        uniqualize_mode = request.form.get('uniqualize_mode', 'smart')
        status_val = request.form.get('status', 'draft')
        limit = min(int(request.form.get('limit_per_source', 3)), 5)

        if source_indices:
            selected = [RSS_SOURCES[int(i)] for i in source_indices if int(i) < len(RSS_SOURCES)]
        else:
            selected = RSS_SOURCES

        admin_id = current_user.id
        job_id = _uuid.uuid4().hex[:10]
        _enricher_jobs[job_id] = {'status': 'running', 'stats': None, 'error': None,
                                   'progress': 'Запускаем обогащение…'}

        def _run(app=current_app._get_current_object()):
            with app.app_context():
                try:
                    _enricher_jobs[job_id]['progress'] = 'Собираем статьи из источников…'
                    stats = run_enrichment(
                        admin_id=admin_id,
                        sources=selected,
                        uniqualize_mode=uniqualize_mode,
                        status=status_val,
                        limit_per_source=limit,
                    )
                    _enricher_jobs[job_id].update({'status': 'done', 'stats': stats,
                                                    'progress': 'Готово'})
                except Exception as exc:
                    _enricher_jobs[job_id].update({'status': 'error', 'error': str(exc),
                                                    'progress': 'Ошибка'})

        t = _threading.Thread(target=_run, daemon=True)
        t.start()

        return jsonify({'ok': True, 'job_id': job_id, 'background': True})

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@admin_bp.route('/admin/blog/news-enricher/fetch/status/<job_id>', methods=['GET'])
@csrf.exempt
@admin_required
def admin_blog_news_enricher_fetch_status(job_id):
    """Poll background enrichment job status."""
    job = _enricher_jobs.get(job_id)
    if not job:
        return jsonify({'ok': False, 'error': 'Задача не найдена'}), 404
    return jsonify({'ok': True, **job})


@admin_bp.route('/admin/blog/categories')
@admin_required
def admin_blog_categories():
    """Manage blog categories"""
    from models import Admin, Category, BlogPost, BlogArticle
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    categories = Category.query.order_by(Category.sort_order, Category.name).all()
    
    # Добавляем подсчет статей для каждой категории
    for category in categories:
        # Считаем статьи из BlogPost (по названию категории)
        blog_post_count = BlogPost.query.filter_by(
            category=category.name, 
            status='published'
        ).count()
        
        # Считаем статьи из BlogArticle (по category_id)
        blog_article_count = BlogArticle.query.filter_by(
            category_id=category.id,
            status='published'
        ).count()
        
        # Общее количество статей
        category.articles_count = blog_post_count + blog_article_count
    
    return render_template('admin/blog_categories.html', admin=current_admin, categories=categories)



@admin_bp.route('/admin/blog/categories/create', methods=['GET', 'POST'])
@admin_required
# @csrf.exempt  # CSRF disabled  # Отключаем CSRF для админ панели
def admin_create_category():
    """Create new blog category - both form and JSON API"""
    from models import Admin, Category
    import re
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    # Handle JSON requests (from inline category creation)
    if request.is_json:
        try:
            data = request.get_json()
            name = data.get('name')
            description = data.get('description', '')
            
            if not name:
                return jsonify({'success': False, 'error': 'Название категории обязательно'})
            
            # Generate slug from Russian name
            def transliterate(text):
                rus_to_eng = {
                    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh', 'з': 'z',
                    'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
                    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
                    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
                }
                return ''.join(rus_to_eng.get(char.lower(), char) for char in text)
            
            slug = transliterate(name.lower())
            slug = re.sub(r'[^\w\s-]', '', slug)
            slug = re.sub(r'[-\s]+', '-', slug).strip('-')
            
            # Ensure unique slug
            original_slug = slug
            counter = 1
            while Category.query.filter_by(slug=slug).first():
                slug = f"{original_slug}-{counter}"
                counter += 1
            
            category = Category(
                name=name,
                slug=slug,
                description=description,
                is_active=True
            )
            
            db.session.add(category)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'category': {
                    'id': category.id,
                    'name': category.name,
                    'slug': category.slug
                }
            })
            
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    # Handle form requests (standard category creation page)
    if request.method == 'GET':
        return render_template('admin/blog_category_create.html', admin=current_admin)
    
    try:
        name = request.form.get('name')
        if not name:
            flash('Название категории обязательно', 'error')
            return render_template('admin/blog_category_create.html', admin=current_admin)
            
        description = request.form.get('description', '')
        
        # Generate slug
        slug = re.sub(r'[^\w\s-]', '', name.lower())
        slug = re.sub(r'[-\s]+', '-', slug).strip('-')
        
        # Ensure unique slug
        original_slug = slug
        counter = 1
        while Category.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1
        
        category = Category(
            name=name,
            slug=slug,
            description=description
        )
        
        db.session.add(category)
        db.session.commit()
        
        flash(f'Категория "{name}" успешно создана!', 'success')
        return redirect(url_for('adm.admin_blog'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка создания категории: {str(e)}', 'error')
        return render_template('admin/blog_category_create.html', admin=current_admin)


# Blog Public Routes  

@admin_bp.route('/admin/blog-management')
@admin_required
def admin_blog_management():
    """Admin blog management page"""
    from models import BlogPost, Category
    
    try:
        # Get filter parameters
        search = request.args.get('search', '')
        status = request.args.get('status', '')
        category_name = request.args.get('category', '')
        page = request.args.get('page', 1, type=int)
        
        # Build query
        query = BlogPost.query
        
        if search:
            query = query.filter(BlogPost.title.contains(search) | 
                               BlogPost.content.contains(search))
        
        if status:
            query = query.filter(BlogPost.status == status)
            
        if category_name:
            query = query.filter(BlogPost.category == category_name)
        
        # Order by creation date and paginate
        posts = query.order_by(BlogPost.created_at.desc()).paginate(
            page=page, per_page=10, error_out=False
        )
        
        # Get categories for filter dropdown
        categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
        
        # Get admin user for template
        from flask_login import current_user
        admin = current_user if current_user.is_authenticated else None
        
        return render_template('admin/blog_management.html',
                             posts=posts,
                             categories=categories,
                             search=search,
                             status=status,
                             category_name=category_name,
                             admin=admin)
        
    except Exception as e:
        flash(f'Ошибка загрузки блога: {str(e)}', 'error')
        return redirect(url_for('adm.admin_dashboard'))



@admin_bp.route('/admin/blog-management/create', methods=['GET', 'POST'])
@admin_required
def admin_create_blog_post():
    """Create new blog post"""
    from models import BlogPost, Category, Admin
    import re
    from datetime import datetime
    
    if request.method == 'GET':
        # ИСПРАВЛЕНО: Используем Flask-Login current_user
        # Get current admin
        current_admin = current_user
        
        categories = Category.query.order_by(Category.name).all()
        return render_template('admin/blog_post_create.html', categories=categories, admin=current_admin)
    
    try:
        # Get form data
        title = request.form.get('title')
        excerpt = request.form.get('excerpt')
        content = request.form.get('content')
        category_id = request.form.get('category_id')
        status = request.form.get('status', 'draft')
        is_featured = 'is_featured' in request.form
        featured_image = request.form.get('featured_image', '')
        meta_title = request.form.get('meta_title', '')
        meta_description = request.form.get('meta_description', '')
        keywords = request.form.get('keywords', '')
        
        # Get category name from category_id
        category = Category.query.get(int(category_id))
        if not category:
            flash('Выбранная категория не найдена', 'error')
            return redirect(url_for('adm.admin_create_blog_post'))
        
        # Generate slug from title
        slug = re.sub(r'[^\w\s-]', '', (title or '').lower())
        slug = re.sub(r'[-\s]+', '-', slug).strip('-')
        
        # Ensure slug is unique
        original_slug = slug
        counter = 1
        while BlogPost.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1
        
        # Calculate reading time (approx 200 words per minute)
        word_count = len(content.split()) if content else 0
        reading_time = max(1, word_count // 200)
        
        # Create blog post using BlogPost model
        post = BlogPost(
            title=title,
            slug=slug,
            excerpt=excerpt,
            content=content,
            category=category.name,  # Use category name, not ID
            author_id=1,  # Default author
            status=status,
            featured_image=featured_image,
            tags=keywords
        )
        
        if status == 'published':
            post.published_at = datetime.utcnow()
        
        db.session.add(post)
        db.session.commit()
        
        # Обновим счетчик статей в категории
        category.articles_count = BlogPost.query.filter_by(category=category.name, status='published').count()
        db.session.commit()
        
        print(f'DEBUG: Created article "{title}" in category "{category.name}" with status "{status}"')
        print(f'DEBUG: Updated category "{category.name}" article count to {category.articles_count}')
        
        flash('Статья успешно создана!', 'success')
        return redirect(url_for('adm.admin_blog_management'))
        
    except Exception as e:
        db.session.rollback()
        print(f'ERROR creating blog post: {str(e)}')
        flash(f'Ошибка создания статьи: {str(e)}', 'error')
        return redirect(url_for('adm.admin_create_blog_post'))


@admin_bp.route('/admin/upload-image', methods=['POST'])
@admin_required
@csrf.exempt
def admin_upload_image():
    """Upload image for TinyMCE editor and blog posts"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    # Check if file is an image
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    if not (file.filename and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
        return jsonify({'success': False, 'error': 'Разрешены только изображения (PNG, JPG, JPEG, GIF, WebP)'}), 400
    
    try:
        # Generate secure filename
        from werkzeug.utils import secure_filename
        import os, uuid
        
        filename = secure_filename(file.filename) if file.filename else 'unnamed_file'
        
        # Create upload directory if it doesn't exist
        upload_dir = 'static/uploads/blog/content'
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save file with unique name to avoid conflicts
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(upload_dir, unique_filename)
        file.save(file_path)
        
        # Return URL - TinyMCE expects 'location' field
        file_url = f"/{file_path}"
        
        return jsonify({
            'success': True,
            'location': file_url,  # TinyMCE expects 'location' field
            'url': file_url,       # Для совместимости с другими частями кода
            'filename': unique_filename
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Ошибка загрузки файла: {str(e)}'}), 500

# Duplicate route removed - already defined earlier



@admin_bp.route('/admin/blog-management/<int:post_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_blog_post(post_id):
    """Edit blog post"""
    from models import BlogPost, Category, Admin
    import re
    from datetime import datetime
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    # Get current admin
    current_admin = current_user
    
    post = BlogPost.query.get_or_404(post_id)
    
    if request.method == 'GET':
        categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
        return render_template('admin/blog_post_create.html', post=post, categories=categories, admin=current_admin)
    
    try:
        # Get form data
        title = request.form.get('title')
        excerpt = request.form.get('excerpt')
        content = request.form.get('content')
        category_id = request.form.get('category_id')
        status = request.form.get('status')
        is_featured = 'is_featured' in request.form
        featured_image = request.form.get('featured_image', '')
        meta_title = request.form.get('meta_title', '')
        meta_description = request.form.get('meta_description', '')
        keywords = request.form.get('keywords', '')
        
        # Validation
        if not title or title.strip() == '':
            flash('Заголовок статьи обязателен', 'error')
            return redirect(url_for('adm.admin_edit_blog_post', post_id=post_id))
        
        if not content or content.strip() == '':
            flash('Содержание статьи обязательно', 'error')
            return redirect(url_for('adm.admin_edit_blog_post', post_id=post_id))
        
        if not category_id or category_id == '':
            flash('Выберите категорию статьи', 'error')
            return redirect(url_for('adm.admin_edit_blog_post', post_id=post_id))

        # Get category name from category_id
        category = Category.query.get(int(category_id))
        if not category:
            flash('Выбранная категория не найдена', 'error')
            return redirect(url_for('adm.admin_edit_blog_post', post_id=post_id))
        
        # Update slug if title changed
        if title != post.title:
            slug = re.sub(r'[^\w\s-]', '', (title or '').lower())
            slug = re.sub(r'[-\s]+', '-', slug).strip('-')
            
            original_slug = slug
            counter = 1
            while BlogPost.query.filter_by(slug=slug).filter(BlogPost.id != post_id).first():
                slug = f"{original_slug}-{counter}"
                counter += 1
            
            post.slug = slug
        
        # Calculate reading time
        word_count = len(content.split()) if content else 0
        reading_time = max(1, word_count // 200)
        
        # Update post
        old_category = post.category
        post.title = title
        post.excerpt = excerpt
        post.content = content
        post.category = category.name  # BlogPost uses category name as string
        post.status = status
        post.is_featured = is_featured
        post.featured_image = featured_image
        post.meta_title = meta_title or title
        post.meta_description = meta_description or excerpt  
        post.tags = keywords  # BlogPost uses tags field
        post.reading_time = reading_time
        post.updated_at = datetime.utcnow()
        
        if status == 'published' and not post.published_at:
            post.published_at = datetime.utcnow()
        
        db.session.commit()
        
        # Update category article counts for both old and new categories
        for cat_name in [old_category, category.name]:
            if cat_name:
                cat = Category.query.filter_by(name=cat_name).first()
                if cat:
                    cat.articles_count = BlogPost.query.filter_by(category=cat_name, status='published').count()
        
        db.session.commit()
        
        flash('Статья успешно обновлена!', 'success')
        return redirect(url_for('adm.admin_blog_management'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления статьи: {str(e)}', 'error')
        return redirect(url_for('adm.admin_edit_blog_post', post_id=post_id))



@admin_bp.route('/admin/blog-management/<int:post_id>/delete', methods=['POST'])
@admin_required
def admin_delete_blog_post(post_id):
    """Delete blog post"""
    from models import BlogPost, Category
    
    try:
        post = BlogPost.query.get_or_404(post_id)
        category_name = post.category
        
        db.session.delete(post)
        db.session.commit()
        
        # Update category article count
        if category_name:
            category = Category.query.filter_by(name=category_name).first()
            if category:
                category.articles_count = BlogPost.query.filter_by(category=category_name, status='published').count()
                db.session.commit()
        
        flash('Статья успешно удалена!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления статьи: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_blog_management'))



@admin_bp.route('/admin/blog-categories-management')
@admin_required
def admin_blog_categories_management():
    """Admin blog categories management"""
    from models import Category
    
    try:
        categories = Category.query.order_by(Category.sort_order).all()
        return render_template('admin/blog_categories.html', categories=categories)
        
    except Exception as e:
        flash(f'Ошибка загрузки категорий: {str(e)}', 'error')
        return redirect(url_for('adm.admin_dashboard'))



@admin_bp.route('/admin/blog-categories-management/create', methods=['GET', 'POST'])
@admin_required
def admin_create_blog_category_new():
    """Create blog category"""
    from models import Category
    import re
    
    def transliterate_russian_to_latin(text):
        """Convert Russian text to Latin characters for URL slugs"""
        translit_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
            ' ': '-', '_': '-'
        }
        
        result = ''
        for char in text.lower():
            result += translit_map.get(char, char)
        
        return result
    
    if request.method == 'GET':
        return render_template('admin/blog_category_create.html')
    
    try:
        # Get form data
        name = request.form.get('name')
        description = request.form.get('description', '')
        color = request.form.get('color', 'blue')
        icon = request.form.get('icon', 'fas fa-folder')
        sort_order = request.form.get('sort_order', 0, type=int)
        
        # Generate slug with proper Russian transliteration
        slug = transliterate_russian_to_latin(name)
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)  # Keep only safe characters
        slug = re.sub(r'[-\s]+', '-', slug).strip('-')
        
        # Ensure slug is unique
        original_slug = slug
        counter = 1
        while Category.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1
        
        category = Category(
            name=name,
            slug=slug,
            description=description,
            color=color,
            icon=icon,
            sort_order=sort_order,
            is_active=True,
            articles_count=0
        )
        
        db.session.add(category)
        db.session.commit()
        
        flash('Категория успешно создана!', 'success')
        return redirect(url_for('adm.admin_blog_categories_management'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка создания категории: {str(e)}', 'error')
        return redirect(url_for('adm.admin_create_blog_category_new'))



@admin_bp.route('/admin/blog-categories-management/<int:category_id>/edit', methods=['GET', 'POST'])
@admin_required  
def admin_edit_blog_category_new(category_id):
    """Edit blog category"""
    from models import Category
    import re
    
    category = Category.query.get_or_404(category_id)
    
    if request.method == 'GET':
        return render_template('admin/blog_category_edit.html', category=category)
    
    try:
        # Get form data
        name = request.form.get('name')
        description = request.form.get('description', '')
        color = request.form.get('color', 'blue')
        icon = request.form.get('icon', 'fas fa-folder')
        sort_order = request.form.get('sort_order', 0, type=int)
        is_active = 'is_active' in request.form
        
        # Update slug if name changed
        if name != category.name:
            def transliterate_russian_to_latin(text):
                """Convert Russian text to Latin characters for URL slugs"""
                translit_map = {
                    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
                    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
                    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
                    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
                    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
                    ' ': '-', '_': '-'
                }
                
                result = ''
                for char in text.lower():
                    result += translit_map.get(char, char)
                
                return result
                
            slug = transliterate_russian_to_latin(name)
            slug = re.sub(r'[^a-z0-9\s-]', '', slug)  # Keep only safe characters
            slug = re.sub(r'[-\s]+', '-', slug).strip('-')
            
            original_slug = slug
            counter = 1
            while Category.query.filter_by(slug=slug).filter(Category.id != category_id).first():
                slug = f"{original_slug}-{counter}"
                counter += 1
            
            category.slug = slug
        
        category.name = name
        category.description = description
        category.color = color
        category.icon = icon
        category.sort_order = sort_order
        category.is_active = is_active
        
        db.session.commit()
        
        flash('Категория успешно обновлена!', 'success')
        return redirect(url_for('adm.admin_blog_categories_management'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления категории: {str(e)}', 'error')
        return redirect(url_for('adm.admin_edit_blog_category_new', category_id=category_id))



@admin_bp.route('/admin/blog-categories-management/<int:category_id>/delete', methods=['POST'])
@admin_required
def admin_delete_blog_category_new(category_id):
    """Delete blog category"""
    from models import Category, BlogArticle
    
    try:
        category = Category.query.get_or_404(category_id)
        
        # Check if category has posts
        posts_count = BlogArticle.query.filter_by(category_id=category_id).count()
        if posts_count > 0:
            flash(f'Нельзя удалить категорию с {posts_count} статьями. Сначала переместите статьи в другие категории.', 'error')
            return redirect(url_for('adm.admin_blog_categories_management'))
        
        db.session.delete(category)
        db.session.commit()
        
        flash('Категория успешно удалена!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления категории: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_blog_categories_management'))


# === JOB MANAGEMENT ADMIN ROUTES ===


@admin_bp.route('/admin/jobs')
@admin_required
def admin_jobs_management():
    """Admin jobs management"""
    from models import Job, JobCategory, Admin
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    try:
        jobs = Job.query.order_by(Job.created_at.desc()).all()
        categories = JobCategory.query.filter_by(is_active=True).order_by(JobCategory.sort_order).all()
        
        # Calculate statistics
        stats = {
            'total': len(jobs),
            'active': len([job for job in jobs if job.status == 'active']),
            'paused': len([job for job in jobs if job.status == 'paused']),
            'closed': len([job for job in jobs if job.status == 'closed']),
            'featured': len([job for job in jobs if job.is_featured])
        }
        
        return render_template('admin/careers_panel.html', vacancies=jobs, categories=categories, admin=current_admin, stats=stats)
        
    except Exception as e:
        flash(f'Ошибка загрузки вакансий: {str(e)}', 'error')
        return redirect(url_for('adm.admin_dashboard'))



@admin_bp.route('/admin/jobs/create', methods=['GET', 'POST'])
@admin_required
def admin_create_job():
    """Create new job"""
    from models import Job, JobCategory, Admin
    import re
    
    def transliterate_russian_to_latin(text):
        """Convert Russian text to Latin characters for URL slugs"""
        translit_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
            ' ': '-', '_': '-'
        }
        
        result = ''
        for char in text.lower():
            result += translit_map.get(char, char)
        
        return result
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    if request.method == 'GET':
        categories = JobCategory.query.filter_by(is_active=True).order_by(JobCategory.sort_order).all()
        return render_template('admin/create_vacancy.html', categories=categories, admin=current_admin)
    
    try:
        # Get form data
        title = request.form.get('title')
        category_id = request.form.get('category_id', type=int)
        description = request.form.get('description')
        
        # Validate required fields
        if not title or not category_id or not description:
            flash('Заполните все обязательные поля', 'error')
            categories = JobCategory.query.filter_by(is_active=True).order_by(JobCategory.sort_order).all()
            return render_template('admin/create_vacancy.html', categories=categories, admin=current_admin)
        requirements = request.form.get('requirements', '')
        benefits = request.form.get('benefits', '')
        responsibilities = request.form.get('responsibilities', '')
        location = request.form.get('location')
        salary_min = request.form.get('salary_min', type=int)
        salary_max = request.form.get('salary_max', type=int)
        employment_type = request.form.get('employment_type', 'full_time')
        experience_level = request.form.get('experience_level', '')
        is_remote = 'is_remote' in request.form
        is_featured = 'is_featured' in request.form
        
        # Additional fields
        department = request.form.get('department', '')
        is_urgent = 'is_urgent' in request.form
        status = request.form.get('status', 'active')
        contact_email = request.form.get('contact_email', '')
        contact_phone = request.form.get('contact_phone', '')
        meta_title = request.form.get('meta_title', '')
        meta_description = request.form.get('meta_description', '')
        
        # Generate slug
        slug = transliterate_russian_to_latin(title)
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug).strip('-')
        
        # Ensure slug is unique
        original_slug = slug
        counter = 1
        while Job.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1
        
        job = Job(
            title=title,
            slug=slug,
            category_id=category_id,
            description=description,
            requirements=requirements,
            benefits=benefits,
            responsibilities=responsibilities,
            location=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency='RUB',
            salary_period='month',
            employment_type=employment_type,
            experience_level=experience_level,
            is_remote=is_remote,
            is_featured=is_featured,
            is_urgent=is_urgent,
            status=status,
            department=department,
            is_active=True,
            contact_email=contact_email,
            contact_phone=contact_phone,
            meta_title=meta_title,
            meta_description=meta_description,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.session.add(job)
        db.session.commit()
        
        flash('Вакансия успешно создана!', 'success')
        return redirect(url_for('adm.admin_jobs_management'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка создания вакансии: {str(e)}', 'error')
        return redirect(url_for('adm.admin_create_job'))



@admin_bp.route('/admin/jobs/<int:job_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_job(job_id):
    """Edit job"""
    from models import Job, JobCategory, Admin
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    job = Job.query.get_or_404(job_id)
    
    if request.method == 'GET':
        categories = JobCategory.query.filter_by(is_active=True).order_by(JobCategory.sort_order).all()
        return render_template('admin/edit_vacancy.html', job=job, categories=categories, admin=current_admin)
    
    try:
        # Update job data
        job.title = request.form.get('title')
        job.category_id = request.form.get('category_id', type=int)
        job.description = request.form.get('description')
        job.requirements = request.form.get('requirements', '')
        job.benefits = request.form.get('benefits', '')
        job.responsibilities = request.form.get('responsibilities', '')
        job.location = request.form.get('location')
        job.salary_min = request.form.get('salary_min', type=int)
        job.salary_max = request.form.get('salary_max', type=int)
        job.employment_type = request.form.get('employment_type', 'full_time')
        job.experience_level = request.form.get('experience_level', '')
        job.is_remote = 'is_remote' in request.form
        job.is_featured = 'is_featured' in request.form
        job.is_urgent = 'is_urgent' in request.form
        job.status = request.form.get('status', 'active')
        job.department = request.form.get('department', '')
        job.contact_email = request.form.get('contact_email', '')
        job.contact_phone = request.form.get('contact_phone', '')
        job.meta_title = request.form.get('meta_title', '')
        job.meta_description = request.form.get('meta_description', '')
        job.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        flash('Вакансия успешно обновлена!', 'success')
        return redirect(url_for('adm.admin_jobs_management'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления вакансии: {str(e)}', 'error')
        return redirect(url_for('adm.admin_edit_job', job_id=job_id))



@admin_bp.route('/admin/jobs/<int:job_id>/delete', methods=['POST'])
@admin_required
def admin_delete_job(job_id):
    """Delete job"""
    from models import Job
    
    try:
        job = Job.query.get_or_404(job_id)
        db.session.delete(job)
        db.session.commit()
        
        flash('Вакансия успешно удалена!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления вакансии: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_jobs_management'))



@admin_bp.route('/admin/jobs/<int:vacancy_id>/toggle-status', methods=['POST'])
@admin_required
def admin_toggle_vacancy_status(vacancy_id):
    """Toggle vacancy status between active and paused"""
    from models import Job
    
    job = Job.query.get_or_404(vacancy_id)
    
    # Toggle between 'active' and 'paused' status
    if job.status == 'active':
        job.status = 'paused'
        status_text = 'приостановлена'
    else:
        job.status = 'active'
        status_text = 'активна'
    
    try:
        db.session.commit()
        flash(f'Вакансия "{job.title}" {status_text}', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ошибка при изменении статуса вакансии', 'error')
    
    return redirect(url_for('adm.admin_jobs_management'))



@admin_bp.route('/admin/job-categories')
@admin_required
def admin_job_categories_management():
    """Admin job categories management"""
    from models import JobCategory, Admin
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    try:
        categories = JobCategory.query.order_by(JobCategory.sort_order).all()
        return render_template('admin/job_categories_management.html', categories=categories, admin=current_admin)
        
    except Exception as e:
        flash(f'Ошибка загрузки категорий вакансий: {str(e)}', 'error')
        return redirect(url_for('adm.admin_dashboard'))



@admin_bp.route('/admin/job-categories/create', methods=['GET', 'POST'])
@admin_required
@csrf.exempt
def admin_create_job_category():
    """Create new job category"""
    from models import JobCategory, Admin
    import re
    
    def transliterate_russian_to_latin(text):
        """Convert Russian text to Latin characters for URL slugs"""
        translit_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
            ' ': '-', '_': '-'
        }
        
        result = ''
        for char in text.lower():
            result += translit_map.get(char, char)
        
        return result
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    if request.method == 'GET':
        return render_template('admin/create_job_category.html', admin=current_admin)
    
    try:
        # Get form data
        name = request.form.get('name')
        description = request.form.get('description', '')
        color = request.form.get('color', 'blue')
        icon = request.form.get('icon', 'fas fa-briefcase')
        sort_order = request.form.get('sort_order', 0, type=int)
        
        # Generate slug
        slug = transliterate_russian_to_latin(name)
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug).strip('-')
        
        # Ensure slug is unique
        original_slug = slug
        counter = 1
        while JobCategory.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1
        
        category = JobCategory(
            name=name,
            slug=slug,
            description=description,
            color=color,
            icon=icon,
            sort_order=sort_order,
            is_active=True
        )
        
        db.session.add(category)
        db.session.commit()
        
        flash('Категория вакансий успешно создана!', 'success')
        return redirect(url_for('adm.admin_job_categories_management'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка создания категории вакансий: {str(e)}', 'error')
        return redirect(url_for('adm.admin_create_job_category'))



@admin_bp.route('/admin/job-categories/<int:category_id>/edit', methods=['GET', 'POST'])
@csrf.exempt
@admin_required
def admin_edit_job_category(category_id):
    """Edit job category"""
    from models import JobCategory, Admin
    import re
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    current_admin = current_user
    
    category = JobCategory.query.get_or_404(category_id)
    
    def transliterate_russian_to_latin(text):
        """Convert Russian text to Latin characters for URL slugs"""
        translit_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
            ' ': '-', '_': '-'
        }
        
        result = ''
        for char in text.lower():
            result += translit_map.get(char, char)
        
        return result
    
    if request.method == 'GET':
        return render_template('admin/edit_job_category.html', category=category, admin=current_admin)
    
    try:
        # Get new name first (before updating)
        new_name = request.form.get('name')
        
        # Update other fields
        category.description = request.form.get('description', '')
        category.color = request.form.get('color', 'blue')
        category.icon = request.form.get('icon', 'fas fa-briefcase')
        category.sort_order = request.form.get('sort_order', 0, type=int)
        category.is_active = 'is_active' in request.form
        
        # Update slug only if name changed
        if new_name and category.name != new_name:
            # Update name
            category.name = new_name
            
            # Generate new slug
            slug = transliterate_russian_to_latin(new_name)
            slug = re.sub(r'[^a-z0-9\s-]', '', slug)
            slug = re.sub(r'[-\s]+', '-', slug).strip('-')
            
            # Ensure slug is unique (excluding current category)
            original_slug = slug
            counter = 1
            while JobCategory.query.filter(JobCategory.slug == slug, JobCategory.id != category_id).first():
                slug = f"{original_slug}-{counter}"
                counter += 1
            
            category.slug = slug
        
        db.session.commit()
        
        flash('Категория вакансий успешно обновлена!', 'success')
        return redirect(url_for('adm.admin_job_categories_management'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления категории вакансий: {str(e)}', 'error')
        return redirect(url_for('adm.admin_edit_job_category', category_id=category_id))



@admin_bp.route('/admin/job-categories/<int:category_id>/delete', methods=['POST'])
@admin_required
def admin_delete_job_category(category_id):
    """Delete job category"""
    from models import JobCategory, Job
    
    try:
        category = JobCategory.query.get_or_404(category_id)
        
        # Check if category has jobs
        jobs_count = Job.query.filter_by(category_id=category_id).count()
        if jobs_count > 0:
            flash(f'Нельзя удалить категорию с {jobs_count} вакансиями. Сначала переместите вакансии в другие категории.', 'error')
            return redirect(url_for('adm.admin_job_categories_management'))
        
        db.session.delete(category)
        db.session.commit()
        
        flash('Категория вакансий успешно удалена!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления категории вакансий: {str(e)}', 'error')
    
    return redirect(url_for('adm.admin_job_categories_management'))


# Admin API Endpoints

@admin_bp.route('/admin/attendance')
@admin_required
def admin_attendance():
    from models import ManagerCheckin, Manager
    date_str = request.args.get('date', '')
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = datetime.utcnow().date()
    else:
        from zoneinfo import ZoneInfo
        selected_date = datetime.now(ZoneInfo('Europe/Moscow')).date()
    checkins = ManagerCheckin.query.filter_by(date=selected_date).order_by(ManagerCheckin.check_in_time).all()
    managers = Manager.query.filter_by(is_active=True).all()
    checkin_map = {}
    for c in checkins:
        if c.manager_id not in checkin_map:
            checkin_map[c.manager_id] = []
        checkin_map[c.manager_id].append(c)
    attendance_data = []
    for m in managers:
        manager_checkins = checkin_map.get(m.id, [])
        total_minutes = sum(c.duration_minutes for c in manager_checkins)
        hours = total_minutes // 60
        mins = total_minutes % 60
        attendance_data.append({
            'manager': m,
            'checkins': manager_checkins,
            'total_time': f'{hours}ч {mins}м' if hours > 0 else f'{mins}м',
            'is_currently_active': any(c.is_active for c in manager_checkins),
            'first_checkin': manager_checkins[0].check_in_time.strftime('%d.%m.%Y %H:%M') if manager_checkins else None,
            'last_activity': manager_checkins[-1].check_out_time.strftime('%d.%m.%Y %H:%M') if manager_checkins and manager_checkins[-1].check_out_time else (manager_checkins[-1].check_in_time.strftime('%d.%m.%Y %H:%M') if manager_checkins else None),
        })
    from zoneinfo import ZoneInfo
    return render_template('admin/attendance.html',
                         attendance_data=attendance_data,
                         selected_date=selected_date,
                         today=datetime.now(ZoneInfo('Europe/Moscow')).date(),
                         admin=current_user)






@admin_bp.route('/admin/scraper')
@admin_required
def admin_scraper():
    """Admin panel for developer scraper management"""
    from models import Admin
    
    # ИСПРАВЛЕНО: Используем Flask-Login current_user
    admin = current_user
    
    return render_template('admin/scraper.html', admin=admin)


@admin_bp.route('/admin/scraper/run', methods=['POST'])
@admin_required
def run_scraper():
    """Run the AI-powered developer scraper"""
    try:
        from developer_parser_integration import DeveloperParserService
        
        # Получаем параметр лимита (по умолчанию 10)
        limit = 10
        try:
            data = request.get_json(force=True) if request.data else {}
        except:
            data = {}
        
        if data:
            limit = data.get('limit', 10)
        
        service = DeveloperParserService()
        result = service.parse_and_save_developers(limit=limit)
        
        return jsonify({
            'success': True,
            'stats': {
                'developers_created': result.get('created', 0),
                'developers_updated': result.get('updated', 0),
                'total_processed': result.get('total_processed', 0),
                'errors': result.get('errors', 0)
            },
            'message': f'ИИ-парсинг завершен! Обработано {result["total_processed"]} застройщиков. Создано: {result["created"]}, обновлено: {result["updated"]}',
            'errors_list': result.get('errors_list', [])
        })
        
    except Exception as e:
        print(f"AI Scraper error: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'message': f'Ошибка при ИИ-парсинге: {str(e)}'
        }), 500


@admin_bp.route('/admin/scraper/test', methods=['POST'])
@admin_required
def test_scraper():
    """Test AI scraper with sample data"""
    try:
        # Простые тестовые данные
        test_data = {
            'name': 'Тестовый застройщик',
            'description': 'Описание тестового застройщика',
            'website': 'https://example.com',
            'phone': '+7-918-000-00-00',
            'email': 'test@example.com'
        }
        
        return jsonify({
            'success': True,
            'data': test_data,
            'stats': {
                'developers_tested': 1,
                'complexes_found': 0,
                'ai_extraction': True,
                'mock_data': True
            },
            'message': 'ИИ-тест завершен! Застройщик: Тестовый застройщик'
        })
        
    except Exception as e:
        print(f"AI Scraper test error: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'message': f'Ошибка при тестировании ИИ-парсера: {str(e)}'
        }), 500


@admin_bp.route('/admin/scraper/statistics')
@admin_required
def scraper_statistics():
    """Get AI parser statistics"""
    try:
        from developer_parser_integration import DeveloperParserService
        
        service = DeveloperParserService()
        stats = service.get_parsing_statistics()
        
        return jsonify({
            'success': True,
            'data': stats
        })
        
    except Exception as e:
        print(f"Statistics error: {e}")
        return jsonify({
            'success': False,
            'message': f'Ошибка получения статистики: {str(e)}'
        }), 500


@admin_bp.route('/admin/scraper/files')
@admin_required
def scraper_files():
    """List scraped data files"""
    try:
        import glob
        import os
        from datetime import datetime
        
        files = glob.glob('scraped_developers_*.json')
        file_info = []
        
        for file in files:
            stat = os.stat(file)
            file_info.append({
                'name': file,
                'size': stat.st_size,
                'created': datetime.fromtimestamp(stat.st_ctime).strftime('%d.%m.%Y %H:%M'),
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M')
            })
        
        # Sort by creation time, newest first
        file_info.sort(key=lambda x: x['modified'], reverse=True)
        
        return jsonify({
            'success': True,
            'files': file_info
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении списка файлов: {str(e)}'
        }), 500


@admin_bp.route('/admin/scraper/view-file/<filename>')
@admin_required
def view_scraped_file(filename):
    """View scraped data file content"""
    try:
        import json
        import os
        
        # Security check - only allow scraped files
        if not filename.startswith('scraped_developers_') or not filename.endswith('.json'):
            return jsonify({'success': False, 'message': 'Недопустимое имя файла'}), 400
        
        if not os.path.exists(filename):
            return jsonify({'success': False, 'message': 'Файл не найден'}), 404
        
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return jsonify({
            'success': True,
            'data': data,
            'filename': filename
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при чтении файла: {str(e)}'
        }), 500

ENRICH_SETTINGS_FILE = os.path.join(_SCRIPTS_DIR, '.enrich_settings.json')
ENRICH_LOG_FILE = os.path.join(_SCRIPTS_DIR, '.enrich_run.log')
ENRICH_CACHE_FILE = os.path.join(_SCRIPTS_DIR, '.enrich_cache.json')
_enrich_proc = None  # subprocess handle for running enrichment
_city_procs = {}    # {city_id: subprocess} for per-city runs via run_city.py


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
    pid_file = os.path.join(_SCRIPTS_DIR, '.enrich_pid')
    try:
        if os.path.exists(pid_file):
            with open(pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
    except Exception:
        pass
    return False


def _city_log_file(city_id):
    return os.path.join(_SCRIPTS_DIR, f'.city_{city_id}.log')


def _city_is_running(city_id):
    global _city_procs
    proc = _city_procs.get(city_id)
    if proc is None:
        return False
    return proc.poll() is None



@admin_bp.route('/admin/developers')
@admin_required
def admin_developers():
    from models import db
    rows = db.session.execute(text("""
        SELECT
            d.id, d.name, d.logo_url, d.source_url, d.is_active, d.is_partner,
            d.inn, d.website, d.phone, d.email, d.rating, d.founded_year,
            d.description, d.full_name, d.created_at,
            COUNT(DISTINCT rc.id)                                         AS jk_count,
            COUNT(DISTINCT CASE WHEN rc.is_active THEN rc.id END)         AS jk_active,
            COUNT(DISTINCT CASE WHEN p.is_active THEN p.id END)           AS apt_count,
            COALESCE(MIN(CASE WHEN p.is_active THEN p.price END), 0)      AS price_min,
            COALESCE(AVG(CASE WHEN p.is_active THEN p.price_per_sqm END)::int, 0) AS avg_ppm2,
            COUNT(DISTINCT CASE WHEN p.is_active THEN rc.city_id END)     AS cities_count
        FROM developers d
        LEFT JOIN residential_complexes rc ON rc.developer_id = d.id
        LEFT JOIN properties p ON p.complex_id = rc.id
        WHERE d.name IS NOT NULL AND d.name != ''
        GROUP BY d.id, d.name, d.logo_url, d.source_url, d.is_active, d.is_partner,
                 d.inn, d.website, d.phone, d.email, d.rating, d.founded_year,
                 d.description, d.full_name, d.created_at
        ORDER BY jk_count DESC, apt_count DESC, d.name
    """)).fetchall()
    return render_template('admin/developers.html', admin=current_user, developers=rows)



@admin_bp.route('/admin/developers/<int:dev_id>')
@admin_required
def admin_developer_detail(dev_id):
    from models import db
    dev = db.session.execute(text("""
        SELECT d.*,
            COUNT(DISTINCT rc.id)                                          AS jk_count,
            COUNT(DISTINCT CASE WHEN p.is_active THEN p.id END)           AS apt_count,
            COALESCE(MIN(CASE WHEN p.is_active THEN p.price END), 0)      AS price_min,
            COALESCE(MAX(CASE WHEN p.is_active THEN p.price END), 0)      AS price_max,
            COALESCE(AVG(CASE WHEN p.is_active THEN p.price_per_sqm END)::int, 0) AS avg_ppm2
        FROM developers d
        LEFT JOIN residential_complexes rc ON rc.developer_id = d.id
        LEFT JOIN properties p ON p.complex_id = rc.id
        WHERE d.id = :dev_id
        GROUP BY d.id
    """), {'dev_id': dev_id}).fetchone()
    if not dev:
        abort(404)

    complexes_raw = db.session.execute(text("""
        SELECT
            rc.id, rc.name, rc.slug, rc.main_image, rc.city_id,
            rc.end_build_year, rc.end_build_quarter,
            rc.buildings_count, rc.object_class_display_name,
            rc.address, rc.is_active,
            ci.name AS city_name,
            COUNT(DISTINCT CASE WHEN p.is_active THEN p.id END)           AS apt_active,
            COUNT(DISTINCT CASE WHEN NOT p.is_active THEN p.id END)       AS apt_sold,
            COALESCE(MIN(CASE WHEN p.is_active THEN p.price END), 0)      AS price_min,
            COALESCE(MAX(CASE WHEN p.is_active THEN p.price END), 0)      AS price_max,
            COALESCE(AVG(CASE WHEN p.is_active THEN p.price_per_sqm END)::int, 0) AS avg_ppm2
        FROM residential_complexes rc
        LEFT JOIN properties p ON p.complex_id = rc.id
        LEFT JOIN cities ci ON ci.id = rc.city_id
        WHERE rc.developer_id = :dev_id
        GROUP BY rc.id, rc.name, rc.slug, rc.main_image, rc.city_id,
                 rc.end_build_year, rc.end_build_quarter, rc.buildings_count,
                 rc.object_class_display_name, rc.address, rc.is_active, ci.name
        ORDER BY rc.is_active DESC, apt_active DESC, rc.name
    """), {'dev_id': dev_id}).fetchall()

    # Buildings per complex
    buildings_raw = db.session.execute(text("""
        SELECT
            p.complex_id,
            COALESCE(p.complex_building_name, 'Без корпуса')              AS building_name,
            COUNT(DISTINCT CASE WHEN p.is_active THEN p.id END)           AS apt_active,
            COUNT(DISTINCT CASE WHEN NOT p.is_active THEN p.id END)       AS apt_sold,
            COALESCE(MIN(CASE WHEN p.is_active THEN p.price END), 0)      AS price_min,
            COALESCE(MAX(CASE WHEN p.is_active THEN p.price END), 0)      AS price_max,
            COALESCE(AVG(CASE WHEN p.is_active THEN p.price_per_sqm END)::int, 0) AS avg_ppm2,
            COUNT(DISTINCT CASE WHEN p.is_active AND p.rooms=0 THEN p.id END) AS r_studio,
            COUNT(DISTINCT CASE WHEN p.is_active AND p.rooms=1 THEN p.id END) AS r_1,
            COUNT(DISTINCT CASE WHEN p.is_active AND p.rooms=2 THEN p.id END) AS r_2,
            COUNT(DISTINCT CASE WHEN p.is_active AND p.rooms=3 THEN p.id END) AS r_3,
            COUNT(DISTINCT CASE WHEN p.is_active AND p.rooms>=4 THEN p.id END) AS r_4plus
        FROM properties p
        WHERE p.complex_id = ANY(
            SELECT id FROM residential_complexes WHERE developer_id = :dev_id
        )
        GROUP BY p.complex_id, COALESCE(p.complex_building_name, 'Без корпуса')
        ORDER BY p.complex_id, building_name
    """), {'dev_id': dev_id}).fetchall()

    # Organize buildings by complex_id
    buildings_by_complex = {}
    for b in buildings_raw:
        buildings_by_complex.setdefault(b.complex_id, []).append(b)

    return render_template('admin/developer_detail.html',
                           admin=current_user,
                           dev=dev,
                           complexes=complexes_raw,
                           buildings_by_complex=buildings_by_complex)



# ── Districts Manager ──────────────────────────────────────────────────────────

@admin_bp.route('/admin/districts')
@admin_required
def admin_districts_manager():
    """Страница управления районами городов."""
    from models import City as _City, District as _District
    from sqlalchemy import func as _func

    cities = _City.query.filter_by(is_active=True).order_by(_City.name).all()

    # Per-city stats
    city_stats = []
    for city in cities:
        total = _District.query.filter_by(city_id=city.id).count()
        with_geom = _District.query.filter(
            _District.city_id == city.id,
            _District.geometry.isnot(None),
            _District.geometry != ''
        ).count()
        with_osm = _District.query.filter(
            _District.city_id == city.id,
            _District.osm_id.isnot(None)
        ).count()
        city_stats.append({
            'city_id': city.id,
            'city_name': city.name,
            'district_count': total,
            'with_geometry': with_geom,
            'with_osm': with_osm,
            'geometry_pct': round(with_geom / total * 100) if total > 0 else 0
        })

    # Full district list with property count
    districts_raw = db.session.execute(text(
        """
        SELECT d.id, d.name, d.city_id, d.district_type, d.geometry, d.osm_id,
               COUNT(p.id) AS property_count
        FROM districts d
        LEFT JOIN properties p ON p.district_id = d.id AND p.is_active = TRUE
        GROUP BY d.id
        ORDER BY d.city_id, d.name
        """
    )).fetchall()

    # Attach city relationship lazily
    city_map = {c.id: c for c in cities}

    class _DRow:
        pass

    districts = []
    for r in districts_raw:
        dr = _DRow()
        dr.id = r.id
        dr.name = r.name
        dr.city_id = r.city_id
        dr.district_type = r.district_type or 'micro'
        dr.geometry = r.geometry
        dr.osm_id = r.osm_id
        dr.property_count = r.property_count
        dr.city = city_map.get(r.city_id)
        districts.append(dr)

    total_districts = len(districts)
    return render_template(
        'admin/districts_manager.html',
        admin=current_user,
        cities=cities,
        city_stats=city_stats,
        districts=districts,
        total_districts=total_districts
    )


@admin_bp.route('/admin/districts/add', methods=['POST'])
@admin_required
def admin_districts_add():
    """Manually create a district."""
    from models import City as _City, District as _District
    import re as _re

    city_id = request.form.get('city_id', type=int)
    name = request.form.get('name', '').strip()
    district_type = request.form.get('district_type', 'micro')
    lat = request.form.get('latitude', type=float)
    lng = request.form.get('longitude', type=float)

    if not city_id or not name:
        flash('Заполните все обязательные поля', 'error')
        return redirect(url_for('adm.admin_districts_manager'))

    slug = _re.sub(r'[^a-z0-9]+', '-', name.lower().replace('ё', 'e').replace('а', 'a')
                   .replace('е', 'e').replace('и', 'i').replace('о', 'o')
                   .replace('у', 'u').replace('ы', 'y').replace('э', 'e')
                   ).strip('-')
    if not slug:
        slug = f'district-{city_id}'

    # Ensure unique slug
    existing = _District.query.filter_by(city_id=city_id, slug=slug).first()
    if existing:
        slug = slug + '-2'

    try:
        d = _District(
            name=name, slug=slug, city_id=city_id,
            district_type=district_type, latitude=lat, longitude=lng
        )
        db.session.add(d)
        db.session.commit()
        flash(f'✅ Район «{name}» создан (id={d.id}, slug={slug})', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Ошибка: {e}', 'error')
    return redirect(url_for('adm.admin_districts_manager'))


@admin_bp.route('/admin/districts/edit/<int:district_id>')
@admin_required
def admin_districts_edit(district_id):
    """Redirect to inline edit — placeholder for now."""
    from models import District as _District
    d = _District.query.get_or_404(district_id)
    flash(f'Редактирование района «{d.name}» (ID={d.id}) — используйте прямое редактирование через БД', 'info')
    return redirect(url_for('adm.admin_districts_manager'))


@admin_bp.route('/admin/districts/import-inline', methods=['POST'])
@csrf.exempt
@admin_required
def admin_districts_import_inline():
    """
    Import districts or streets from OSM Overpass API inline (no subprocess).
    Returns JSON with full list of imported items + stats.
    Works for ANY city — uses hardcoded bbox or derives from city.latitude/longitude.
    """
    import re as _re
    import time as _time
    import requests as _requests
    from models import City as _City
    from sqlalchemy import text as _text

    data = request.get_json(silent=True) or {}
    city_id = data.get('city_id')
    mode = data.get('mode', 'districts')   # 'districts' | 'streets'
    rewrite = data.get('rewrite', False)

    if not city_id:
        return jsonify({'success': False, 'message': 'Не указан city_id'})

    city = _City.query.get(city_id)
    if not city:
        return jsonify({'success': False, 'message': f'Город {city_id} не найден'})

    # ── Bbox map: hardcoded for known cities; fallback: city.lat/lng ± delta ──
    _BBOX = {
        'krasnodar':    (44.82, 38.60, 45.25, 39.35),
        'sochi':        (43.30, 39.55, 44.05, 40.35),
        'maykop':       (44.47, 39.90, 44.78, 40.35),
        'kursk':        (51.68, 36.08, 51.82, 36.32),
        'anapa':        (44.70, 37.05, 45.12, 37.75),
        'gelendzhik':   (44.40, 37.78, 44.82, 38.45),
        'novorossiysk': (44.58, 37.50, 44.95, 38.05),
        'armavir':      (44.85, 40.90, 45.12, 41.35),
        'tuapse':       (43.92, 38.85, 44.28, 39.30),
    }

    slug = city.slug or ''
    if slug in _BBOX:
        lat_min, lon_min, lat_max, lon_max = _BBOX[slug]
    elif city.latitude and city.longitude and city.latitude != 0 and city.longitude != 0:
        delta = 0.18
        lat_min = city.latitude - delta
        lat_max = city.latitude + delta
        lon_min = city.longitude - delta
        lon_max = city.longitude + delta
    else:
        return jsonify({'success': False,
                        'message': f'Нет bbox для города «{city.name}». Задайте координаты города в настройках.'})

    bbox_str = f"{lat_min},{lon_min},{lat_max},{lon_max}"

    # ── Overpass query helpers ────────────────────────────────────────────────
    OVERPASS_URL = 'https://overpass-api.de/api/interpreter'

    def _ovp(query, timeout=90):
        for attempt in range(3):
            try:
                r = _requests.post(OVERPASS_URL, data={'data': query},
                                   timeout=timeout,
                                   headers={'User-Agent': 'InBackRealEstate/2.0'})
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 429:
                    _time.sleep(8 * (attempt + 1))
                else:
                    _time.sleep(3 * (attempt + 1))
            except Exception as _e:
                logger.warning(f'Overpass attempt {attempt+1}: {_e}')
                _time.sleep(4)
        return None

    _CYRILLIC = _re.compile(r'[а-яёА-ЯЁ]')
    _RU = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh',
           'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
           'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts',
           'ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}

    def _translit(txt):
        s = ''.join(_RU.get(c, c) for c in txt.lower())
        s = _re.sub(r'[^\w\s-]', '', s)
        s = _re.sub(r'[\s_]+', '-', s)
        return _re.sub(r'-+', '-', s).strip('-')

    def _centroid(geom_str):
        pts = []
        for pair in geom_str.split(';'):
            p = pair.strip().split(',')
            if len(p) >= 2:
                try:
                    pts.append((float(p[0]), float(p[1])))
                except ValueError:
                    pass
        if not pts:
            return None, None
        return round(sum(x[0] for x in pts)/len(pts), 6), round(sum(x[1] for x in pts)/len(pts), 6)

    # ── DISTRICTS mode ────────────────────────────────────────────────────────
    if mode == 'districts':
        q = f"""[out:json][timeout:90];
(
  relation["boundary"="administrative"]["admin_level"~"^(7|8|9|10)$"](bbox:{bbox_str});
  way["place"~"^(suburb|quarter|neighbourhood|residential)$"]["name"](bbox:{bbox_str});
  relation["place"~"^(suburb|quarter|neighbourhood)$"]["name"](bbox:{bbox_str});
);
out body;
>;
out skel qt;"""

        raw = _ovp(q)
        if not raw:
            return jsonify({'success': False, 'message': 'Overpass API не ответил (timeout/rate-limit). Попробуйте позже.'})

        elements = raw.get('elements', [])
        node_coords, way_nodes, way_geom = {}, {}, {}
        relations, ways_place = [], []

        for el in elements:
            t = el.get('type')
            if t == 'node':
                node_coords[el['id']] = (el.get('lat', 0), el.get('lon', 0))
            elif t == 'way':
                way_nodes[el['id']] = el.get('nodes', [])
                if el.get('tags'):
                    ways_place.append(el)
            elif t == 'relation':
                relations.append(el)

        for wid, nids in way_nodes.items():
            coords = [node_coords[n] for n in nids if n in node_coords]
            if coords:
                way_geom[wid] = coords

        def _stitch_ways(way_ids):
            """
            Stitch a list of OSM way IDs into a single closed polygon ring.
            Each way is a list of (lat, lng) points. We chain them end-to-end,
            reversing individual ways as needed so endpoints connect.

            Strategy:
            1. Greedily pick the nearest remaining way endpoint (fwd or rev).
            2. Only attach if the gap is ≤ MAX_GAP_DEG (~2 km). Otherwise skip the
               disconnected way entirely to avoid cross-city jumps from shared boundary
               ways between adjacent administrative districts.
            3. After chaining, take only the largest contiguous sub-ring (no big jumps).

            Returns list of (lat, lng) tuples.
            """
            segs = [list(way_geom[w]) for w in way_ids if w in way_geom and len(way_geom[w]) >= 2]
            if not segs:
                return []
            if len(segs) == 1:
                return segs[0]

            MAX_GAP_DEG = 0.02  # ~2 km — reject jumps larger than this

            def dist(a, b):
                return abs(a[0] - b[0]) + abs(a[1] - b[1])

            chain = list(segs[0])
            remaining = segs[1:]

            for _ in range(len(remaining)):
                if not remaining:
                    break
                tail = chain[-1]
                best_i, best_rev, best_d = None, False, 1e9
                for i, seg in enumerate(remaining):
                    d_fwd = dist(tail, seg[0])
                    d_rev = dist(tail, seg[-1])
                    if d_fwd < best_d:
                        best_i, best_rev, best_d = i, False, d_fwd
                    if d_rev < best_d:
                        best_i, best_rev, best_d = i, True, d_rev
                if best_i is None or best_d > MAX_GAP_DEG:
                    # No close match — drop the disconnected segment
                    if best_i is not None:
                        remaining.pop(best_i)
                    continue
                seg = remaining.pop(best_i)
                if best_rev:
                    seg = list(reversed(seg))
                chain.extend(seg[1:])  # skip duplicate junction point

            # Deduplicate consecutive identical points
            result = [chain[0]] if chain else []
            for pt in chain[1:]:
                if abs(pt[0] - result[-1][0]) > 1e-7 or abs(pt[1] - result[-1][1]) > 1e-7:
                    result.append(pt)
            return result

        def _ring(members):
            outer = [m['ref'] for m in members if m.get('type') == 'way' and m.get('role') == 'outer']
            if not outer:
                outer = [m['ref'] for m in members if m.get('type') == 'way']
            outer = [w for w in outer if w in way_geom and len(way_geom[w]) >= 2]
            if not outer:
                return None
            pts = _stitch_ways(outer)
            if len(pts) < 3:
                return None
            return ';'.join(f"{la},{lo}" for la, lo in pts)

        def _dtype_from_tags(tags):
            """Map OSM admin_level + place tags to our district_type values."""
            al = tags.get('admin_level', '')
            place = tags.get('place', '')
            if al in ('6', '7', '8', '9'):
                return 'okrug'
            if place in ('suburb', 'neighbourhood', 'quarter', 'village', 'hamlet'):
                return 'microrayon'
            if al == '10':
                return 'microrayon'
            return 'microrayon'

        def _in_bbox(la, lo):
            """Return True only if centroid falls strictly inside the city bbox."""
            if la is None or lo is None:
                return False
            return lat_min <= la <= lat_max and lon_min <= lo <= lon_max

        candidates = []
        for rel in relations:
            tags = rel.get('tags', {})
            name = tags.get('name:ru') or tags.get('name', '')
            if not name or len(name) < 2 or not _CYRILLIC.search(name):
                continue
            al = tags.get('admin_level', '')
            if al == '8' and not tags.get('place'):
                continue
            geom = _ring(rel.get('members', []))
            if not geom:
                continue
            lat, lng = _centroid(geom)
            if not _in_bbox(lat, lng):
                continue
            dtype = _dtype_from_tags(tags)
            candidates.append({'osm_id': rel['id'], 'name': name, 'geometry': geom,
                                'lat': lat, 'lng': lng, 'district_type': dtype})

        for way in ways_place:
            tags = way.get('tags', {})
            name = tags.get('name:ru') or tags.get('name', '')
            if not name or len(name) < 2 or not _CYRILLIC.search(name):
                continue
            if way['id'] not in way_geom:
                continue
            coords = way_geom[way['id']]
            if len(coords) < 3:
                continue
            geom = ';'.join(f"{la},{lo}" for la, lo in coords)
            lat, lng = _centroid(geom)
            if not _in_bbox(lat, lng):
                continue
            candidates.append({'osm_id': way['id'], 'name': name, 'geometry': geom,
                                'lat': lat, 'lng': lng, 'district_type': _dtype_from_tags(tags)})

        if not candidates:
            return jsonify({'success': False,
                            'message': f'OSM не вернул районы для «{city.name}». Попробуйте ещё раз или добавьте вручную.',
                            'imported': [], 'updated': []})

        # ── Upsert to DB ──────────────────────────────────────────────────────
        existing_rows = db.session.execute(_text(
            "SELECT id, name, slug, osm_id FROM districts WHERE city_id = :cid"
        ), {'cid': city_id}).fetchall()

        by_osm  = {r.osm_id: r.id for r in existing_rows if r.osm_id}
        by_name = {r.name.lower(): r.id for r in existing_rows}
        slugs   = {r.slug for r in existing_rows}

        inserted_names, updated_names = [], []

        for d in candidates:
            oid, name, geom = d['osm_id'], d['name'], d['geometry']
            lat, lng, dtype = d['lat'], d['lng'], d['district_type']

            if oid in by_osm:
                db.session.execute(_text("""
                    UPDATE districts SET geometry=:g, geometry_source='osm',
                        latitude=COALESCE(latitude,:la), longitude=COALESCE(longitude,:lo),
                        updated_at=NOW() WHERE id=:did
                """), {'g': geom, 'la': lat, 'lo': lng, 'did': by_osm[oid]})
                updated_names.append(name)
                continue

            if name.lower() in by_name:
                did = by_name[name.lower()]
                db.session.execute(_text("""
                    UPDATE districts SET geometry=:g, geometry_source='osm', osm_id=:oid,
                        latitude=COALESCE(latitude,:la), longitude=COALESCE(longitude,:lo),
                        updated_at=NOW() WHERE id=:did
                """), {'g': geom, 'oid': oid, 'la': lat, 'lo': lng, 'did': did})
                by_osm[oid] = did
                updated_names.append(name)
                continue

            base = _translit(name)
            slug = base
            n = 2
            while slug in slugs:
                slug = f"{base}-{n}"; n += 1
            slugs.add(slug)

            db.session.execute(_text("""
                INSERT INTO districts
                    (name, slug, city_id, geometry, geometry_source, osm_id,
                     latitude, longitude, district_type, created_at, updated_at)
                VALUES
                    (:name, :slug, :cid, :geom, 'osm', :oid,
                     :lat, :lng, :dtype, NOW(), NOW())
                ON CONFLICT (city_id, slug) DO UPDATE SET
                    geometry=EXCLUDED.geometry, geometry_source='osm',
                    osm_id=EXCLUDED.osm_id,
                    latitude=COALESCE(districts.latitude, EXCLUDED.latitude),
                    longitude=COALESCE(districts.longitude, EXCLUDED.longitude),
                    updated_at=NOW()
            """), {'name': name, 'slug': slug, 'cid': city_id, 'geom': geom,
                   'oid': oid, 'lat': lat, 'lng': lng, 'dtype': dtype})
            by_osm[oid] = None
            by_name[name.lower()] = None
            inserted_names.append(name)

        db.session.commit()

        # Auto-assign properties to the freshly imported districts
        try:
            _pip_c, _nn_c = _auto_assign_districts_for_city(city_id)
            assign_note = f' Привязано {_pip_c + _nn_c} объектов к районам ({_pip_c} PIP + {_nn_c} nearest).'
        except Exception as _ae:
            assign_note = f' (Автоназначение не удалось: {_ae})'

        return jsonify({
            'success': True,
            'message': (f'Импортировано {len(inserted_names)} новых районов, '
                        f'обновлено {len(updated_names)} для города «{city.name}».{assign_note}'),
            'city': city.name,
            'inserted': inserted_names,
            'updated': updated_names,
        })

    # ── STREETS mode ──────────────────────────────────────────────────────────
    elif mode == 'streets':
        q = f"""[out:json][timeout:90];
way["highway"~"^(primary|secondary|tertiary|residential|unclassified|living_street)$"]["name"](bbox:{bbox_str});
out body;
>;
out skel qt;"""

        raw = _ovp(q)
        if not raw:
            return jsonify({'success': False, 'message': 'Overpass API не ответил.'})

        elements = raw.get('elements', [])
        node_coords, ways = {}, []
        for el in elements:
            if el['type'] == 'node':
                node_coords[el['id']] = (el.get('lat', 0), el.get('lon', 0))
            elif el['type'] == 'way':
                ways.append(el)

        street_map = {}
        for way in ways:
            tags = way.get('tags', {})
            name = tags.get('name:ru') or tags.get('name', '')
            if not name or len(name) < 2:
                continue
            coords = [node_coords[n] for n in way.get('nodes', []) if n in node_coords]
            if len(coords) < 2:
                continue
            if name not in street_map or len(coords) > len(street_map[name]['coords']):
                street_map[name] = {'osm_id': way['id'], 'name': name, 'coords': coords,
                                    'hw': tags.get('highway', '')}

        existing_rows = db.session.execute(_text(
            "SELECT id, name, slug, osm_id FROM streets WHERE city_id = :cid"
        ), {'cid': city_id}).fetchall()

        by_osm  = {r.osm_id: r.id for r in existing_rows if r.osm_id}
        by_name = {r.name.lower(): r.id for r in existing_rows}
        slugs   = {r.slug for r in existing_rows}

        inserted_names, updated_names = [], []

        for name, sd in list(street_map.items())[:800]:
            oid = sd['osm_id']
            coords = sd['coords']
            geom = ';'.join(f"{la},{lo}" for la, lo in coords)
            mid = coords[len(coords) // 2]
            lat, lng = round(mid[0], 6), round(mid[1], 6)

            if oid in by_osm:
                db.session.execute(_text("""
                    UPDATE streets SET geometry=:g, geometry_source='osm',
                        latitude=COALESCE(latitude,:la), longitude=COALESCE(longitude,:lo),
                        updated_at=NOW() WHERE id=:did
                """), {'g': geom, 'la': lat, 'lo': lng, 'did': by_osm[oid]})
                updated_names.append(name)
                continue

            if name.lower() in by_name:
                did = by_name[name.lower()]
                db.session.execute(_text("""
                    UPDATE streets SET geometry=:g, geometry_source='osm', osm_id=:oid,
                        latitude=COALESCE(latitude,:la), longitude=COALESCE(longitude,:lo),
                        updated_at=NOW() WHERE id=:did
                """), {'g': geom, 'oid': oid, 'la': lat, 'lo': lng, 'did': did})
                by_osm[oid] = did
                updated_names.append(name)
                continue

            base = _translit(name)
            slug = base
            n = 2
            while slug in slugs:
                slug = f"{base}-{n}"; n += 1
            slugs.add(slug)

            db.session.execute(_text("""
                INSERT INTO streets
                    (name, slug, city_id, geometry, geometry_source, osm_id,
                     latitude, longitude, created_at, updated_at)
                VALUES
                    (:name, :slug, :cid, :geom, 'osm', :oid,
                     :lat, :lng, NOW(), NOW())
                ON CONFLICT (city_id, slug) DO UPDATE SET
                    geometry=EXCLUDED.geometry, geometry_source='osm',
                    osm_id=EXCLUDED.osm_id,
                    latitude=COALESCE(streets.latitude, EXCLUDED.latitude),
                    longitude=COALESCE(streets.longitude, EXCLUDED.longitude),
                    updated_at=NOW()
            """), {'name': name, 'slug': slug, 'cid': city_id, 'geom': geom,
                   'oid': oid, 'lat': lat, 'lng': lng})
            by_osm[oid] = None
            by_name[name.lower()] = None
            inserted_names.append(name)

        db.session.commit()
        return jsonify({
            'success': True,
            'message': (f'Импортировано {len(inserted_names)} новых улиц, '
                        f'обновлено {len(updated_names)} для города «{city.name}»'),
            'city': city.name,
            'inserted': inserted_names,
            'updated': updated_names,
        })

    return jsonify({'success': False, 'message': f'Неизвестный режим: {mode}'})


@admin_bp.route('/admin/districts/fetch-osm', methods=['POST'])
@admin_required
def admin_districts_fetch_osm():
    """Launch fetch_osm_boundaries.py for a specific city as background subprocess."""
    data = request.get_json(silent=True) or {}
    city_slug = data.get('city_slug', '')
    streets = data.get('streets', False)
    rewrite = data.get('rewrite', False)

    if not city_slug:
        return jsonify({'success': False, 'message': 'Не указан город'})

    script = os.path.join(_SCRIPTS_DIR, 'fetch_osm_boundaries.py')
    if not os.path.exists(script):
        return jsonify({'success': False, 'message': 'Скрипт fetch_osm_boundaries.py не найден'})

    cmd = ['python3', '-u', script, '--city', city_slug]
    if streets:
        cmd.append('--streets')
    if rewrite:
        cmd.append('--all')

    try:
        import subprocess as _subprocess
        proc = _subprocess.Popen(cmd, stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                                  start_new_session=True)
        return jsonify({'success': True,
                        'message': f'Загрузка OSM границ запущена для «{city_slug}» (PID {proc.pid}). Займёт 1–5 минут.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/admin/districts/run-pip', methods=['POST'])
@admin_required
def admin_districts_run_pip():
    """Run point-in-polygon district/street assignment synchronously."""
    data = request.get_json(silent=True) or {}
    city_id = data.get('city_id')
    mode = data.get('mode', 'districts')

    import sys as _sys
    script_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts')
    if script_dir not in _sys.path:
        _sys.path.insert(0, script_dir)

    try:
        from assign_district_ids import assign_districts, assign_streets
        from models import City as _City

        if city_id:
            city_ids = [city_id]
        else:
            city_ids = [c.id for c in _City.query.filter_by(is_active=True).all()]

        total = 0
        for cid in city_ids:
            if mode == 'districts':
                count = assign_districts(city_id=cid, batch_size=1000, only_unlinked=False)
            else:
                count = assign_streets(city_id=cid, batch_size=1000, only_unlinked=False)
            total += count

        entity = 'районам' if mode == 'districts' else 'улицам'
        return jsonify({'success': True, 'message': f'Привязано {total} объектов к {entity} в {len(city_ids)} городах'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})




# ── DaData address enrichment for residential complexes ──────────────────────

_dadata_enrich_thread = None  # background thread handle
_dadata_enrich_log_file = '/tmp/dadata_addr_enrich.log'
_dadata_enrich_status = {}   # {city_id: {running, done, total, error}}


def _run_dadata_enrichment_thread(city_id: int, app_ctx):
    """Run DaData address enrichment for one city in background."""
    import os, re, time, requests, psycopg2
    global _dadata_enrich_status
    _dadata_enrich_status[city_id] = {'running': True, 'done': 0, 'total': 0, 'error': None}
    log_lines = []
    def _log(msg):
        log_lines.append(msg)
        with open(_dadata_enrich_log_file, 'a') as _f:
            _f.write(msg + '\n')
    try:
        DB = os.environ['DATABASE_URL']
        TOKEN = os.environ.get('DADATA_API_KEY', '')
        SECRET = os.environ.get('DADATA_SECRET_KEY', '')
        if not TOKEN:
            raise RuntimeError('DADATA_API_KEY not set')
        CLEAN_URL = 'https://cleaner.dadata.ru/api/v1/clean/address'
        GEO_URL = 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/geolocate/address'
        CH = {'Content-Type': 'application/json', 'Authorization': f'Token {TOKEN}', 'X-Secret': SECRET}
        GH = {'Content-Type': 'application/json', 'Authorization': f'Token {TOKEN}'}

        def _clean_d(raw):
            if not raw: return ''
            s = re.sub(r'\s*(внутригородской|внутригородский)\s*(район|р-н)?\s*', '', raw, flags=re.I)
            return re.sub(r'\s*(район|р-н)\s*$', '', s, flags=re.I).strip()

        def _parse_dd(data):
            if not data: return {}
            raw_st = data.get('settlement') or ''
            st_type = (data.get('settlement_type_full') or '').lower()
            raw_cd = data.get('city_district') or ''
            cd_type = (data.get('city_district_type_full') or '').lower()
            district = ''; quarter = ''
            if raw_st and ('район' in st_type or 'внутригородской' in st_type):
                district = _clean_d(raw_st)
            elif raw_cd and ('район' in cd_type or 'внутригородской' in cd_type):
                district = _clean_d(raw_cd)
            elif raw_cd:
                district = _clean_d(raw_cd)
            if raw_st and 'район' not in st_type and 'внутригородской' not in st_type:
                quarter = raw_st
            region = data.get('region') or ''
            if 'краснодарск' in region.lower() and 'край' not in region.lower():
                region += ' край'
            return {'region': region, 'city': data.get('city') or '',
                    'district': district, 'quarter': quarter}

        conn = psycopg2.connect(DB)
        cur = conn.cursor()
        cur.execute('SELECT id, name, addr_region, addr_city, address_city_district, '
                    'address_quarter, addr_street, latitude, longitude '
                    'FROM residential_complexes WHERE city_id=%s ORDER BY id', (city_id,))
        rcs = cur.fetchall()
        _dadata_enrich_status[city_id]['total'] = len(rcs)
        _log(f'[DaData] city_id={city_id}: {len(rcs)} RCs to process')
        with open(_dadata_enrich_log_file, 'a') as _f:
            _f.write(f'=== city_id={city_id} {len(rcs)} RCs ===\n')

        for rc_id, name, cur_reg, cur_city, cur_dist, cur_q, cur_st, lat, lng in rcs:
            cur.execute('SELECT address FROM properties WHERE complex_id=%s AND address IS NOT NULL '
                        'AND address!=\'\' GROUP BY address ORDER BY COUNT(*) DESC LIMIT 1', (rc_id,))
            row = cur.fetchone()
            data = None
            if row:
                q = f'{row[0]}, {cur_city or "Краснодар"}, Краснодарский край'
                r = requests.post(CLEAN_URL, headers=CH, json=[q], timeout=15)
                data = r.json()[0] if r.status_code == 200 and r.json() else None
                source = 'clean'
            elif lat and lng:
                r = requests.post(GEO_URL, headers=GH,
                                  json={'lat': float(lat), 'lon': float(lng), 'radius_meters': 500},
                                  timeout=15)
                sug = r.json().get('suggestions', []) if r.status_code == 200 else []
                data = sug[0].get('data', {}) if sug else None
                source = 'geo'
            else:
                source = 'none'
            time.sleep(1.05)
            p = _parse_dd(data) if data else {}
            new_reg = p.get('region') or cur_reg or 'Краснодарский край'
            new_city = p.get('city') or cur_city or 'Краснодар'
            new_dist = p.get('district') or cur_dist or ''
            new_q = p.get('quarter') or cur_q or ''

            # ── bbox fallback for Krasnodar okrugs ────────────────────────────
            # DaData often returns empty city_district for central Krasnodar.
            # Use coordinate bounding boxes as a last resort when district is empty.
            if not new_dist and lat and lng and city_id == 1:
                _krd_bbox = [
                    # (district_name, lat_min, lat_max, lon_min, lon_max)
                    # Ordered most-specific first; first match wins.
                    ('Прикубанский округ', 45.055, 45.220, 38.850, 39.100),
                    ('Карасунский округ',  44.975, 45.058, 38.970, 39.170),
                    ('Западный округ',     44.990, 45.060, 38.750, 38.990),
                    ('Центральный округ',  45.010, 45.060, 38.935, 39.050),
                ]
                _lat, _lng = float(lat), float(lng)
                for _dname, _la_min, _la_max, _lo_min, _lo_max in _krd_bbox:
                    if _la_min <= _lat <= _la_max and _lo_min <= _lng <= _lo_max:
                        new_dist = _dname
                        _log(f'[{rc_id}] {name} → bbox fallback: {new_dist!r}')
                        break

            _log(f'[{rc_id}] {name} [{source}] → dist={new_dist!r} q={new_q!r}')
            cur.execute('UPDATE residential_complexes SET addr_region=%s, addr_city=%s, '
                        'address_city_district=%s, address_quarter=%s, updated_at=NOW() WHERE id=%s',
                        (new_reg, new_city, new_dist, new_q, rc_id))
            conn.commit()
            _dadata_enrich_status[city_id]['done'] += 1

        cur.close()
        conn.close()
        _log(f'[DaData] Done city_id={city_id}')
        _dadata_enrich_status[city_id]['running'] = False
    except Exception as exc:
        import traceback
        _log(f'[DaData ERROR] {exc}\n{traceback.format_exc()}')
        _dadata_enrich_status[city_id] = {'running': False, 'done': 0, 'total': 0, 'error': str(exc)}


@admin_bp.route('/admin/addresses/enrich-rc-dadata', methods=['POST'])
@admin_required
def admin_enrich_rc_dadata():
    """Start DaData address enrichment for RCs in a city (background thread)."""
    import threading
    data = request.get_json(silent=True) or request.form
    city_id = int(data.get('city_id', 1))
    # Reset log for new run
    with open(_dadata_enrich_log_file, 'w') as _f:
        _f.write('')
    t = threading.Thread(
        target=_run_dadata_enrichment_thread,
        args=(city_id, None),
        daemon=True
    )
    t.start()
    return jsonify({'success': True, 'message': f'Enrichment started for city_id={city_id}'})


@admin_bp.route('/admin/addresses/enrich-rc-dadata/status')
@admin_required
def admin_enrich_rc_dadata_status():
    """Return current DaData enrichment status + tail of log."""
    data = request.args
    city_id = int(data.get('city_id', 1))
    status = _dadata_enrich_status.get(city_id, {'running': False, 'done': 0, 'total': 0})
    log = ''
    try:
        if os.path.exists(_dadata_enrich_log_file):
            with open(_dadata_enrich_log_file, 'r', errors='replace') as f:
                lines = f.readlines()
            log = ''.join(lines[-50:])
    except Exception:
        pass
    return jsonify({**status, 'log': log})


@admin_bp.route('/admin/addresses/sync-to-properties', methods=['POST'])
@admin_required
def admin_sync_addresses_to_properties():
    """
    Propagate RC address fields → properties:
      RC.address_city_district → properties.parsed_district  (overwrite if RC has value)
      RC.address_quarter       → properties.parsed_settlement (overwrite if RC has value)
    Also copies buildings.address → properties.address where property.address is blank.
    """
    from sqlalchemy import text as _text
    data = request.get_json(silent=True) or request.form
    city_id = int(data.get('city_id', 1))

    try:
        # 1. RC district/quarter → properties
        res1 = db.session.execute(_text("""
            UPDATE properties p
            SET
                parsed_district   = CASE WHEN rc.address_city_district IS NOT NULL AND rc.address_city_district != ''
                                         THEN rc.address_city_district
                                         ELSE p.parsed_district END,
                parsed_settlement = CASE WHEN rc.address_quarter IS NOT NULL AND rc.address_quarter != ''
                                         THEN rc.address_quarter
                                         ELSE p.parsed_settlement END,
                updated_at        = NOW()
            FROM residential_complexes rc
            WHERE p.complex_id = rc.id
              AND p.city_id = :city_id
              AND (rc.address_city_district IS NOT NULL AND rc.address_city_district != ''
                   OR rc.address_quarter IS NOT NULL AND rc.address_quarter != '')
        """), {'city_id': city_id})

        # 2. buildings.address → properties.address (where address is blank)
        res2 = db.session.execute(_text("""
            UPDATE properties p
            SET address    = b.address,
                updated_at = NOW()
            FROM buildings b
            JOIN residential_complexes rc ON rc.id = b.complex_id
            WHERE b.name IS NOT NULL
              AND b.address IS NOT NULL AND b.address != ''
              AND (p.address IS NULL OR p.address = '')
              AND p.complex_building_name = b.name
              AND p.complex_id = rc.id
              AND p.city_id = :city_id
        """), {'city_id': city_id})

        db.session.commit()
        return jsonify({
            'success': True,
            'props_district_updated': res1.rowcount,
            'props_address_updated': res2.rowcount,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/admin/addresses/bbox-assign-districts', methods=['POST'])
@admin_required
def admin_bbox_assign_districts():
    """
    Quick bbox-based district assignment for RCs missing address_city_district.
    Currently covers Krasnodar (city_id=1) okrugs. Safe to re-run — only fills
    empty district fields, never overwrites existing DaData values.
    """
    from sqlalchemy import text as _text
    data = request.get_json(silent=True) or request.form
    city_id = int(data.get('city_id', 1))

    # ── Krasnodar okrug bboxes ───────────────────────────────────────────────
    _KRD_BBOX = [
        ('Прикубанский округ', 45.055, 45.220, 38.850, 39.100),
        ('Карасунский округ',  44.975, 45.058, 38.970, 39.170),
        ('Западный округ',     44.990, 45.060, 38.750, 38.990),
        ('Центральный округ',  45.010, 45.060, 38.935, 39.050),
    ]

    if city_id != 1:
        return jsonify({'success': False, 'error': 'bbox assignment only implemented for Krasnodar (city_id=1)'})

    try:
        rows = db.session.execute(_text(
            "SELECT id, latitude, longitude FROM residential_complexes "
            "WHERE city_id = :cid AND (address_city_district IS NULL OR address_city_district = '') "
            "AND latitude IS NOT NULL AND latitude < 46 AND longitude IS NOT NULL"
        ), {'cid': city_id}).fetchall()

        updated = 0
        for rc_id, lat, lng in rows:
            lat, lng = float(lat), float(lng)
            assigned = None
            for dname, la_min, la_max, lo_min, lo_max in _KRD_BBOX:
                if la_min <= lat <= la_max and lo_min <= lng <= lo_max:
                    assigned = dname
                    break
            if assigned:
                db.session.execute(_text(
                    "UPDATE residential_complexes SET address_city_district = :d, updated_at = NOW() WHERE id = :id"
                ), {'d': assigned, 'id': rc_id})
                updated += 1

        db.session.commit()
        total_now = db.session.execute(_text(
            "SELECT COUNT(*) FROM residential_complexes WHERE city_id = :cid "
            "AND address_city_district IS NOT NULL AND address_city_district != ''"
        ), {'cid': city_id}).scalar()
        return jsonify({'success': True, 'assigned': updated, 'total_with_district': int(total_now)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/admin/addresses')
@admin_required
def admin_addresses():
    """Address enrichment management page."""
    from models import City
    cities = City.query.filter_by(is_active=True).order_by(City.id).all()
    return render_template('admin/addresses.html', admin=current_user, cities=cities)


@admin_bp.route('/admin/districts/enrich-dadata', methods=['POST'])
@admin_required
def admin_districts_enrich_dadata():
    """Create missing districts from DaData parsed_area / parsed_settlement values on properties."""
    from models import Property as _Prop, District as _District, City as _City
    from app import db as _db
    from sqlalchemy import text as _text

    data = request.get_json(silent=True) or {}
    city_id = data.get('city_id')

    try:
        if city_id:
            city_ids = [int(city_id)]
        else:
            city_ids = [c.id for c in _City.query.filter_by(is_active=True).all()]

        created_total = 0
        skipped_total = 0
        details = []

        for cid in city_ids:
            city_obj = _City.query.get(cid)
            if not city_obj:
                continue

            rows = _db.session.execute(
                _text("""
                    SELECT DISTINCT
                        COALESCE(NULLIF(TRIM(parsed_area), ''), NULL)      AS area,
                        COALESCE(NULLIF(TRIM(parsed_settlement), ''), NULL) AS settlement
                    FROM   properties
                    WHERE  city_id = :cid
                      AND  (parsed_area IS NOT NULL OR parsed_settlement IS NOT NULL)
                    ORDER  BY area, settlement
                """),
                {'cid': cid}
            ).fetchall()

            existing_names = {
                d.name.lower()
                for d in _District.query.filter_by(city_id=cid).all()
            }

            for row in rows:
                area       = row[0]
                settlement = row[1]

                candidates = []
                if settlement:
                    candidates.append(settlement)
                if area and area not in (settlement or ''):
                    candidates.append(area)

                for name in candidates:
                    if name.lower() in existing_names:
                        skipped_total += 1
                        continue
                    import re as _re
                    slug = _re.sub(r'[^a-z0-9]+', '-',
                                   name.lower()
                                   .replace('ё', 'e').replace('ъ', '')
                                   .replace('ь', '').replace('й', 'j')
                                   .replace('а', 'a').replace('б', 'b')
                                   .replace('в', 'v').replace('г', 'g')
                                   .replace('д', 'd').replace('е', 'e')
                                   .replace('ж', 'zh').replace('з', 'z')
                                   .replace('и', 'i').replace('к', 'k')
                                   .replace('л', 'l').replace('м', 'm')
                                   .replace('н', 'n').replace('о', 'o')
                                   .replace('п', 'p').replace('р', 'r')
                                   .replace('с', 's').replace('т', 't')
                                   .replace('у', 'u').replace('ф', 'f')
                                   .replace('х', 'h').replace('ц', 'c')
                                   .replace('ч', 'ch').replace('ш', 'sh')
                                   .replace('щ', 'sch').replace('э', 'e')
                                   .replace('ю', 'yu').replace('я', 'ya')
                           ).strip('-')
                    suffix = 1
                    base_slug = slug
                    while _District.query.filter_by(city_id=cid, slug=slug).first():
                        slug = f'{base_slug}-{suffix}'
                        suffix += 1

                    district = _District(
                        city_id=cid,
                        name=name,
                        slug=slug,
                        district_type='microrayon',
                    )
                    _db.session.add(district)
                    existing_names.add(name.lower())
                    created_total += 1
                    details.append(f'{city_obj.name}: {name}')

        _db.session.commit()
        return jsonify({
            'success': True,
            'created': created_total,
            'skipped': skipped_total,
            'details': details[:50],
            'message': f'Создано {created_total} новых районов, пропущено {skipped_total} (уже существуют)'
        })
    except Exception as e:
        _db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/admin/cities')
@admin_required
def admin_cities():
    import json as _json
    cfg_path = os.path.join(_SCRIPTS_DIR, 'city_config.json')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            city_configs = _json.load(f)
    except Exception:
        city_configs = {}

    # Статистика по каждому городу
    city_stats = {}
    for ckey, cfg in city_configs.items():
        db_city_id = cfg.get('db_city_id', int(ckey))
        try:
            complexes_count = db.session.execute(
                text('SELECT COUNT(*) FROM residential_complexes WHERE city_id = :cid AND is_active = TRUE'),
                {'cid': db_city_id}
            ).scalar() or 0
            props_count = db.session.execute(
                text('SELECT COUNT(*) FROM properties WHERE city_id = :cid AND is_active = TRUE'),
                {'cid': db_city_id}
            ).scalar() or 0
        except Exception:
            complexes_count = props_count = 0
        city_stats[ckey] = {'complexes': complexes_count, 'properties': props_count}

    # Все города из БД (включая те, что ещё не в конфиге)
    db_cities_raw = db.session.execute(
        text('SELECT id, name, slug, is_active, latitude, longitude, name_genitive, name_prepositional FROM cities ORDER BY id')
    ).fetchall()

    # Словарь склонений по city_id
    city_declensions = {
        row[0]: {'genitive': row[6] or '', 'prepositional': row[7] or ''}
        for row in db_cities_raw
    }

    # Вычисляем extra_cities (есть в БД, нет в конфиге) в Python
    config_db_ids = set()
    for cfg_val in city_configs.values():
        db_id = cfg_val.get('db_city_id')
        if db_id is not None:
            config_db_ids.add(int(db_id))
    extra_cities = [c for c in db_cities_raw if c[0] not in config_db_ids]

    return render_template('admin/cities.html', admin=current_user,
                           city_configs=city_configs, city_stats=city_stats,
                           db_cities=db_cities_raw, extra_cities=extra_cities,
                           city_declensions=city_declensions)



@admin_bp.route('/admin/nashdom')
@admin_required
def admin_nashdom():
    """Страница ручного просмотра и подтверждения матчинга ЖК с наш.дом.рф"""
    from sqlalchemy import text as _t
    import json as _json

    city_id = int(request.args.get('city_id', 1))
    search_q = request.args.get('q', '').strip()
    filter_mode = request.args.get('mode', 'all')  # all | matched | unmatched | photos

    cities_q = db.session.execute(_t("SELECT id, name FROM cities ORDER BY id")).fetchall()
    cities = [{'id': r[0], 'name': r[1]} for r in cities_q]

    where_parts = ["rc.city_id = :city_id", "rc.is_active = TRUE"]
    params = {'city_id': city_id}
    if search_q:
        where_parts.append("rc.name ILIKE :q")
        params['q'] = f'%{search_q}%'
    if filter_mode == 'matched':
        where_parts.append("rc.nashdom_id IS NOT NULL")
    elif filter_mode == 'unmatched':
        where_parts.append("rc.nashdom_id IS NULL")
    elif filter_mode == 'photos':
        where_parts.append("rc.nashdom_photos IS NOT NULL")

    where_clause = ' AND '.join(where_parts)
    rows = db.session.execute(_t(f"""
        SELECT rc.id, rc.name, rc.slug, rc.nashdom_id, rc.nashdom_photos,
               rc.main_image, rc.gallery_images, rc.nashdom_confirmed,
               d.name as developer_name,
               count(DISTINCT b.id) as buildings_count,
               count(DISTINCT p.id) as apts_count,
               count(DISTINCT p.id) FILTER (WHERE p.is_active = FALSE) as sold_count
        FROM residential_complexes rc
        LEFT JOIN developers d ON d.id = rc.developer_id
        LEFT JOIN buildings b ON b.complex_id = rc.id
        LEFT JOIN properties p ON p.complex_id = rc.id
        WHERE {where_clause}
        GROUP BY rc.id, rc.name, rc.slug, rc.nashdom_id, rc.nashdom_photos,
                 rc.main_image, rc.gallery_images, rc.nashdom_confirmed, d.name
        ORDER BY
            CASE WHEN rc.nashdom_id IS NOT NULL THEN 0 ELSE 1 END,
            count(DISTINCT p.id) DESC
        LIMIT 200
    """), params).fetchall()

    # Buildings per complex
    complex_ids = [r[0] for r in rows]
    bld_map = {}
    if complex_ids:
        bld_rows = db.session.execute(_t("""
            SELECT complex_id, building_name, building_id, end_build_year, end_build_quarter,
                   total_floors, total_apartments, released
            FROM buildings
            WHERE complex_id = ANY(:ids)
            ORDER BY complex_id, end_build_year, end_build_quarter
        """), {'ids': complex_ids}).fetchall()
        for br in bld_rows:
            bld_map.setdefault(br[0], []).append({
                'name': br[1] or br[2],
                'building_id': br[2],
                'year': br[3],
                'quarter': br[4],
                'floors': br[5],
                'total_apts': br[6],
                'released': br[7],
            })

    complexes = []
    for r in rows:
        nd_photos = []
        if r[4]:
            try:
                nd_photos = _json.loads(r[4]) if isinstance(r[4], str) else (r[4] if isinstance(r[4], list) else [])
            except Exception:
                pass
        gallery = []
        if r[6]:
            try:
                gallery = _json.loads(r[6]) if isinstance(r[6], str) else (r[6] if isinstance(r[6], list) else [])
            except Exception:
                pass
        complexes.append({
            'id': r[0], 'name': r[1], 'slug': r[2],
            'nashdom_id': r[3], 'nd_photos': nd_photos,
            'main_image': r[5], 'gallery': gallery[:4],
            'confirmed': r[7],
            'developer': r[8] or '',
            'buildings': bld_map.get(r[0], []),
            'apts_count': r[10] or 0,
            'sold_count': r[11] or 0,
        })

    stats = {
        'total': len(complexes),
        'matched': sum(1 for c in complexes if c['nashdom_id']),
        'with_photos': sum(1 for c in complexes if c['nd_photos']),
        'confirmed': sum(1 for c in complexes if c['confirmed']),
    }

    return render_template(
        'admin/nashdom.html',
        complexes=complexes, cities=cities, current_city_id=city_id,
        search_q=search_q, filter_mode=filter_mode, stats=stats,
        admin=current_user,
    )



@admin_bp.route('/admin/nashdom/confirm', methods=['POST'])
@admin_required
def admin_nashdom_confirm():
    """Подтвердить или отклонить матчинг ЖК с наш.дом.рф"""
    from sqlalchemy import text as _t
    data = request.get_json() or {}
    complex_id = data.get('complex_id')
    action = data.get('action')  # confirm | reject | set_id
    nashdom_id = data.get('nashdom_id', '').strip()
    if not complex_id:
        return jsonify({'ok': False, 'error': 'complex_id required'}), 400
    try:
        if action == 'confirm':
            db.session.execute(_t(
                "UPDATE residential_complexes SET nashdom_confirmed=TRUE, updated_at=NOW() WHERE id=:id"
            ), {'id': complex_id})
        elif action == 'reject':
            db.session.execute(_t(
                "UPDATE residential_complexes SET nashdom_id=NULL, nashdom_photos=NULL, "
                "nashdom_confirmed=FALSE, updated_at=NOW() WHERE id=:id"
            ), {'id': complex_id})
        elif action == 'set_id' and nashdom_id:
            db.session.execute(_t(
                "UPDATE residential_complexes SET nashdom_id=:nd_id, nashdom_confirmed=FALSE, "
                "updated_at=NOW() WHERE id=:id"
            ), {'nd_id': nashdom_id, 'id': complex_id})
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500



@admin_bp.route('/admin/nashdom/push-photos', methods=['POST'])
@admin_required
def admin_nashdom_push_photos():
    """Переносит nashdom_photos в gallery_images для выбранного ЖК (замена ЦИАН-фотографий)"""
    from sqlalchemy import text as _t
    import json as _json
    data = request.get_json() or {}
    complex_id = data.get('complex_id')
    if not complex_id:
        return jsonify({'ok': False, 'error': 'complex_id required'}), 400
    try:
        row = db.session.execute(_t(
            "SELECT nashdom_photos FROM residential_complexes WHERE id=:id"
        ), {'id': complex_id}).fetchone()
        if not row or not row[0]:
            return jsonify({'ok': False, 'error': 'Нет фотографий с наш.дом.рф для этого ЖК'}), 404
        nd_photos = row[0] if isinstance(row[0], list) else _json.loads(row[0])
        if not nd_photos:
            return jsonify({'ok': False, 'error': 'Список фотографий пуст'}), 404
        new_gallery = _json.dumps(nd_photos, ensure_ascii=False)
        db.session.execute(_t(
            "UPDATE residential_complexes SET gallery_images=:g, main_image=:m, "
            "updated_at=NOW() WHERE id=:id"
        ), {'g': new_gallery, 'm': nd_photos[0], 'id': complex_id})
        db.session.commit()
        # Clear complexes route cache so new images appear immediately
        global _complexes_route_cache, _complexes_route_cache_ts
        _complexes_route_cache.clear()
        _complexes_route_cache_ts.clear()
        return jsonify({'ok': True, 'photos_count': len(nd_photos), 'main_image': nd_photos[0]})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500



@admin_bp.route('/admin/enrichment')
@admin_required
def admin_enrichment():
    from app import CITY_CONFIG_ALL, _load_enrich_settings
    settings = _load_enrich_settings()
    return render_template('admin/enrichment.html', admin=current_user, settings=settings,
                           cities=CITY_CONFIG_ALL)


@admin_bp.route('/admin/enrichment/status')
@admin_required
def admin_enrichment_status():
    cache = _enrich_cache_info()
    running = _enrich_is_running()
    # Get DB JK count
    try:
        from models import ResidentialComplex
        db_total = db.session.query(ResidentialComplex).filter_by(city_id=1, is_active=True).count()
    except Exception:
        db_total = None
    detail = ''
    if running:
        phase = cache.get('phase', 0)
        labels = {0:'Сбор страниц ЦИАН', 2:'Скрапинг страниц ЖК',
                  3:'Скрапинг застройщиков', 4:'Обновление базы данных'}
        if phase == 1:
            jk_done = cache.get('jk_done', 0)
            jk_total = cache.get('jk_count', 0)
            detail = f'Phase 1b: {jk_done}/{jk_total} ЖК ({cache.get("apt_count",0):,} квартир)'
        else:
            detail = labels.get(phase, f'Фаза {phase}')
    return jsonify({**cache, 'running': running, 'running_detail': detail, 'db_total': db_total})


@admin_bp.route('/admin/enrichment/log')
@admin_required
def admin_enrichment_log():
    try:
        if os.path.exists(ENRICH_LOG_FILE):
            with open(ENRICH_LOG_FILE, 'r', errors='replace') as f:
                lines = f.readlines()
            # Return last 200 lines
            log = ''.join(lines[-200:])
        else:
            log = '(лог-файл не найден — запустите обогащение)'
    except Exception as e:
        log = f'Ошибка чтения лога: {e}'
    return jsonify({'log': log})



@admin_bp.route('/admin/enrichment/proxy-pool', methods=['GET'])
@admin_required
def admin_enrichment_get_proxy_pool():
    from app import _load_enrich_settings
    try:
        settings = _load_enrich_settings()
        pool = settings.get('proxy_pool', [])
        return jsonify({'pool': pool})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/admin/enrichment/proxy-pool', methods=['POST'])
@admin_required
def admin_enrichment_save_proxy_pool():
    from app import _load_enrich_settings
    try:
        data = request.get_json(force=True) or {}
        pool = data.get('pool', [])
        pool = [p.strip() for p in pool if isinstance(p, str) and p.strip()]
        settings = _load_enrich_settings()
        settings['proxy_pool'] = pool
        with open(ENRICH_SETTINGS_FILE, 'w') as f:
            import json as _json
            _json.dump(settings, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'pool': pool, 'count': len(pool)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/enrichment/settings', methods=['POST'])
@admin_required
def admin_enrichment_settings_save():
    from app import _load_enrich_settings, _save_enrich_settings
    try:
        data = request.get_json(force=True)
        settings = _save_enrich_settings(data)
        # Reschedule APScheduler enrichment job with new day/time (supports multiple days)
        try:
            from routes.admin_api import scheduler as _sched
            from apscheduler.triggers.cron import CronTrigger
            dow_names = ['mon','tue','wed','thu','fri','sat','sun']
            days_list = settings.get('schedule_days') or [settings.get('schedule_day_of_week', 6)]
            days_list = [int(d) for d in days_list if 0 <= int(d) <= 6]
            if not days_list:
                days_list = [6]
            dow_str = ','.join(dow_names[d] for d in sorted(set(days_list)))
            _sched.reschedule_job(
                'cian_enrichment_job',
                trigger=CronTrigger(
                    day_of_week=dow_str,
                    hour=settings['schedule_hour'],
                    minute=settings['schedule_minute'],
                    timezone='Europe/Moscow'
                )
            )
        except Exception:
            pass
        return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/admin/enrichment/start', methods=['POST'])
@admin_required
def admin_enrichment_start():
    from app import _load_enrich_settings
    global _enrich_proc
    import subprocess
    if _enrich_is_running():
        return jsonify({'success': False, 'message': 'Обогащение уже выполняется'})
    settings = _load_enrich_settings()
    script = os.path.join(_SCRIPTS_DIR, 'enrich_complexes.py')
    if not os.path.exists(script):
        return jsonify({'success': False, 'message': 'Скрипт enrich_complexes.py не найден'})
    # Optionally reset cache
    if settings.get('reset_on_run'):
        try:
            if os.path.exists(ENRICH_CACHE_FILE):
                with open(ENRICH_CACHE_FILE) as f:
                    c = json.load(f)
                c['phase'] = 0
                c['jk_search_data'] = {}
                with open(ENRICH_CACHE_FILE, 'w') as f:
                    json.dump(c, f, ensure_ascii=False)
        except Exception:
            if os.path.exists(ENRICH_CACHE_FILE):
                os.remove(ENRICH_CACHE_FILE)
    # Support mode=prices for fast price-only run
    req_data = request.get_json(silent=True) or {}
    enrich_mode = req_data.get('mode', 'full')
    env = {**os.environ,
           'ENRICH_MODE':        enrich_mode,
           'ENRICH_TOTAL_PAGES': str(settings['total_pages']),
           'ENRICH_REGION_ID':   str(settings['cian_region_id']),
           'ENRICH_CITY_ID':     str(settings['city_id']),
           'ENRICH_CREATE_NEW':  '1' if settings['create_new_jk'] else '0',
           'ENRICH_DELAY':       str(settings['request_delay']),
           'ENRICH_PROXY':       str(settings.get('proxy_url', '')),
           'ENRICH_ANTICAPTCHA': str(settings.get('anticaptcha_key', '')),
           'ENRICH_USE_VPN':     '1' if settings.get('use_vpn') else '0'}
    log_f = open(ENRICH_LOG_FILE, 'w')
    _enrich_proc = subprocess.Popen(
        [__import__('sys').executable, script], env=env,
        stdout=log_f, stderr=subprocess.STDOUT,
        start_new_session=True
    )
    with open(os.path.join(_SCRIPTS_DIR, '.enrich_pid'), 'w') as f:
        f.write(str(_enrich_proc.pid))

    # For full runs: launch a watcher thread that cleans up vanished/stale properties after enrichment finishes
    if enrich_mode == 'full':
        import threading as _threading
        from datetime import datetime as _dt
        def _post_enrich_cleanup(proc, log_path):
            proc.wait()
            if proc.returncode == 0:
                try:
                    started_at = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
                    _sep = '=' * 60
                    with open(log_path, 'a') as _lf:
                        _lf.write(f'\n\n{_sep}\n')
                        _lf.write(f'🧹 АВТ0-ОЧИСТКА ({started_at})\n')
                        _lf.write(f'{_sep}\n')
                        _lf.write('Шаг 1/2: удаление пропавших с ЦИАН...\n')
                    logger.info('🧹 Post-enrichment cleanup started (vanished + stale)...')

                    from routes.admin_api import run_cleanup_vanished_properties, run_deactivate_stale_properties
                    vanished_n, vanished_err = run_cleanup_vanished_properties()
                    with open(log_path, 'a') as _lf:
                        if vanished_err:
                            _lf.write(f'  ⚠️  Пропавшие с ЦИАН — ошибка: {vanished_err}\n')
                        else:
                            _lf.write(f'  ✅ Пропавшие с ЦИАН: деактивировано {vanished_n} объектов\n')
                        _lf.write('Шаг 2/2: деактивация устаревших (60+ дней, без inner_id)...\n')

                    stale_n, stale_err = run_deactivate_stale_properties()
                    total_cleaned = vanished_n + stale_n
                    finished_at = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
                    with open(log_path, 'a') as _lf:
                        if stale_err:
                            _lf.write(f'  ⚠️  Устаревшие — ошибка: {stale_err}\n')
                        else:
                            _lf.write(f'  ✅ Устаревшие (60+ дней): деактивировано {stale_n} объявлений\n')
                        _lf.write(f'{_sep}\n')
                        _lf.write(f'✅ ОЧИСТКА ЗАВЕРШЕНА ({finished_at})\n')
                        _lf.write(f'   Пропавших с ЦИАН:      {vanished_n}\n')
                        _lf.write(f'   Устаревших (60+ дней): {stale_n}\n')
                        _lf.write(f'   Итого деактивировано:  {total_cleaned}\n')
                        _lf.write(f'{_sep}\n')

                    logger.info(
                        f'✅ Post-enrichment cleanup done: '
                        f'пропавших с ЦИАН → {vanished_n}, '
                        f'устаревших → {stale_n}, '
                        f'итого → {total_cleaned}'
                    )
                    # Parse added/updated counts from enrichment log file
                    import re as _re2
                    _added_log = _updated_log = 0
                    try:
                        with open(log_path, 'r', errors='replace') as _rf:
                            _log_text = _rf.read()
                        _am = _re2.search(r'новых[:\s]*(\d+)', _log_text)
                        _um = _re2.search(r'обновл[а-яё\.]*[:\s]*(\d+)', _log_text)
                        _added_log   = int(_am.group(1)) if _am else 0
                        _updated_log = int(_um.group(1)) if _um else 0
                    except Exception:
                        pass
                    # Send Telegram report
                    _send_enrich_report_tg(_added_log, _updated_log, vanished_n, stale_n, mode='full')
                    # Ping Google/Yandex/IndexNow after successful enrichment
                    try:
                        from routes.admin_api import ping_search_engines
                        ping_search_engines()
                        logger.info('⚡ Search engine ping sent after enrichment')
                    except Exception as _pe:
                        logger.warning(f'⚠️  Search engine ping failed: {_pe}')
                except Exception as _e:
                    logger.warning(f'⚠️  Post-enrichment cleanup error: {_e}')
                    try:
                        with open(log_path, 'a') as _lf:
                            _lf.write(f'❌ Ошибка авто-очистки: {_e}\n')
                        _send_enrich_report_tg(0, 0, 0, 0, mode='full', error=str(_e)[:200])
                    except Exception:
                        pass
        _threading.Thread(
            target=_post_enrich_cleanup,
            args=(_enrich_proc, ENRICH_LOG_FILE),
            daemon=True
        ).start()

    mode_label = '⚡ Обновление цен' if enrich_mode == 'prices' else '🏗️ Полное обогащение'
    return jsonify({'success': True, 'message': f'{mode_label} запущено (PID {_enrich_proc.pid})'})


@admin_bp.route('/admin/enrichment/reset-cache', methods=['POST'])
@admin_required
def admin_enrichment_reset_cache():
    try:
        if os.path.exists(ENRICH_CACHE_FILE):
            os.remove(ENRICH_CACHE_FILE)
        enrich_pid_f = os.path.join(_SCRIPTS_DIR, '.enrich_pid')
        if os.path.exists(enrich_pid_f):
            os.remove(enrich_pid_f)
        return jsonify({'success': True, 'message': 'Кэш сброшен — следующий запуск начнёт с нуля'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500



@admin_bp.route('/admin/enrichment/propagate-address', methods=['POST'])
@admin_required
def admin_enrichment_propagate_address():
    """Propagate RC address fields (okrug/quarter/street/city) to linked properties.
    
    Copies:
      RC.address_city_district → Property.parsed_area
      RC.address_quarter       → Property.parsed_settlement
      RC.addr_street           → Property.parsed_street
      RC.addr_city             → Property.parsed_city

    Use after CIAN enrichment (fix_jk_bulk.py) to keep properties in sync.
    """
    try:
        req = request.get_json(silent=True) or {}
        force = bool(req.get('force', False))
        city_id = req.get('city_id')
        city_id = int(city_id) if city_id else None

        from sqlalchemy import text as _text

        city_filter = '' if city_id is None else f'AND p.city_id = {int(city_id)}'
        stats = {}

        def _upd(sql_str):
            return db.session.execute(_text(sql_str)).rowcount

        if force:
            stats['parsed_area']       = _upd(f"UPDATE properties p SET parsed_area = rc.address_city_district FROM residential_complexes rc WHERE p.complex_id=rc.id AND rc.address_city_district IS NOT NULL {city_filter}")
            stats['parsed_settlement'] = _upd(f"UPDATE properties p SET parsed_settlement = rc.address_quarter FROM residential_complexes rc WHERE p.complex_id=rc.id AND rc.address_quarter IS NOT NULL {city_filter}")
            stats['parsed_street']     = _upd(f"UPDATE properties p SET parsed_street = rc.addr_street FROM residential_complexes rc WHERE p.complex_id=rc.id AND rc.addr_street IS NOT NULL {city_filter}")
            stats['parsed_city']       = _upd(f"UPDATE properties p SET parsed_city = rc.addr_city FROM residential_complexes rc WHERE p.complex_id=rc.id AND rc.addr_city IS NOT NULL AND (p.parsed_city IS NULL OR p.parsed_city='') {city_filter}")
        else:
            stats['parsed_area']       = _upd(f"UPDATE properties p SET parsed_area = rc.address_city_district FROM residential_complexes rc WHERE p.complex_id=rc.id AND p.parsed_area IS NULL AND rc.address_city_district IS NOT NULL {city_filter}")
            stats['parsed_settlement'] = _upd(f"UPDATE properties p SET parsed_settlement = rc.address_quarter FROM residential_complexes rc WHERE p.complex_id=rc.id AND p.parsed_settlement IS NULL AND rc.address_quarter IS NOT NULL {city_filter}")
            stats['parsed_street']     = _upd(f"UPDATE properties p SET parsed_street = rc.addr_street FROM residential_complexes rc WHERE p.complex_id=rc.id AND p.parsed_street IS NULL AND rc.addr_street IS NOT NULL {city_filter}")
            stats['parsed_city']       = _upd(f"UPDATE properties p SET parsed_city = rc.addr_city FROM residential_complexes rc WHERE p.complex_id=rc.id AND (p.parsed_city IS NULL OR p.parsed_city='') AND rc.addr_city IS NOT NULL {city_filter}")

        db.session.commit()

        totals_q = db.session.execute(_text('''
            SELECT
                count(*) FILTER (WHERE parsed_area IS NOT NULL) as has_area,
                count(*) FILTER (WHERE parsed_settlement IS NOT NULL) as has_quarter,
                count(*) FILTER (WHERE parsed_street IS NOT NULL) as has_street,
                count(*) as total
            FROM properties WHERE is_active=true
        ''')).fetchone()

        return jsonify({
            'success': True,
            'message': (
                f"Обновлено: округ {stats['parsed_area']}, мкр {stats['parsed_settlement']}, "
                f"улица {stats['parsed_street']}, город {stats['parsed_city']}"
            ),
            'stats': stats,
            'coverage': {
                'total': totals_q[3],
                'has_area': totals_q[0],
                'has_quarter': totals_q[1],
                'has_street': totals_q[2],
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/admin/enrichment/stop', methods=['POST'])
@admin_required
def admin_enrichment_stop():
    """Создаёт стоп-флаг файл — парсер остановится после текущего ЖК."""
    try:
        stop_flag = os.path.join(_SCRIPTS_DIR, '.enrich_stop')
        with open(stop_flag, 'w') as f:
            f.write('stop')
        return jsonify({'success': True, 'message': 'Сигнал остановки отправлен. Парсер остановится после текущего ЖК.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500



@admin_bp.route('/admin/enrichment/empty-stats')
@admin_required
def admin_enrichment_empty_stats():
    """Возвращает количество ЖК без фото и/или без описания."""
    try:
        from models import ResidentialComplex
        from sqlalchemy import func, case
        total = db.session.query(func.count(ResidentialComplex.id)).filter_by(is_active=True).scalar()
        no_photo = db.session.query(func.count(ResidentialComplex.id)).filter(
            ResidentialComplex.is_active == True,
            (ResidentialComplex.main_image == None) | (ResidentialComplex.main_image == '')
        ).scalar()
        no_desc = db.session.query(func.count(ResidentialComplex.id)).filter(
            ResidentialComplex.is_active == True,
            (ResidentialComplex.description == None) | (ResidentialComplex.description == '')
        ).scalar()
        no_both = db.session.query(func.count(ResidentialComplex.id)).filter(
            ResidentialComplex.is_active == True,
            (ResidentialComplex.main_image == None) | (ResidentialComplex.main_image == ''),
            (ResidentialComplex.description == None) | (ResidentialComplex.description == '')
        ).scalar()
        return jsonify({
            'no_photo_no_desc': no_both,
            'no_photo': no_photo,
            'no_desc': no_desc,
            'total': total,
        })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500



@admin_bp.route('/admin/enrichment/fix-empty', methods=['POST'])
@admin_required
def admin_enrichment_fix_empty():
    """Запускает парсинг только тех ЖК у которых нет фото и/или описания."""
    import subprocess, sys
    try:
        data = request.get_json(silent=True) or {}
        mode = data.get('mode', 'no_photo_no_desc')

        enrich_pid_f = os.path.join(_SCRIPTS_DIR, '.enrich_pid')
        if os.path.exists(enrich_pid_f):
            try:
                with open(enrich_pid_f) as pf:
                    pid = int(pf.read().strip())
                import psutil
                if psutil.pid_exists(pid):
                    return jsonify({'success': False, 'message': 'Парсер уже запущен. Дождитесь окончания или остановите его.'}), 409
            except Exception:
                pass

        script = os.path.join(_SCRIPTS_DIR, 'fix_empty_complexes.py')
        log_file = os.path.join(_SCRIPTS_DIR, '.enrich_log.txt')

        env = {**os.environ, 'FIX_EMPTY_MODE': mode}
        try:
            _settings_path = os.path.join(_SCRIPTS_DIR, '.enrich_settings.json')
            import json as _json
            with open(_settings_path) as sf:
                sett = _json.load(sf)
            env['ENRICH_CITY_ID']    = str(sett.get('city_id', 1))
            env['ENRICH_REGION_ID']  = str(sett.get('region_id', 4820))
            env['ENRICH_DELAY']      = str(sett.get('request_delay', 0.5))
            env['ENRICH_PROXY']      = sett.get('proxy_url', '')
            env['ENRICH_ANTICAPTCHA'] = sett.get('anticaptcha_key', '')
        except Exception:
            pass

        with open(log_file, 'w') as lf:
            lf.write(f'[fix-empty] Запуск режима: {mode}\n')

        with open(log_file, 'a') as lf:
            proc = subprocess.Popen(
                [sys.executable, script, mode],
                stdout=lf, stderr=lf,
                env=env,
                start_new_session=True,
            )

        with open(enrich_pid_f, 'w') as pf:
            pf.write(str(proc.pid))

        return jsonify({'success': True, 'message': f'Запущено обновление пустых ЖК (режим: {mode})'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500



@admin_bp.route('/admin/complex/<int:complex_id>/enrich-single', methods=['POST'])
@admin_required
def admin_complex_enrich_single(complex_id):
    """Обогащение одного ЖК через fix_jk_bulk.py --id <rc_id> --force"""
    import subprocess, sys
    try:
        from models import ResidentialComplex
        rc = db.session.get(ResidentialComplex, complex_id)
        if not rc:
            return jsonify({'success': False, 'message': 'ЖК не найден'}), 404
        if not rc.complex_id:
            return jsonify({'success': False, 'message': 'У этого ЖК нет CIAN ID — обогащение по данным ЦИАН невозможно'})

        script = os.path.join(_SCRIPTS_DIR, 'fix_jk_bulk.py')
        if not os.path.exists(script):
            return jsonify({'success': False, 'message': 'Скрипт fix_jk_bulk.py не найден'})

        log_file = os.path.join(_SCRIPTS_DIR, f'.enrich_single_{complex_id}.log')
        with open(log_file, 'w', encoding='utf-8') as lf:
            lf.write(f'[enrich-single] ЖК: {rc.name} (id={complex_id}, city_id={rc.city_id}, cian={rc.complex_id})\n')

        with open(log_file, 'a', encoding='utf-8') as lf:
            proc = subprocess.Popen(
                [sys.executable, '-u', script,
                 '--city', str(rc.city_id),
                 '--id', str(complex_id),
                 '--force'],
                stdout=lf, stderr=subprocess.STDOUT,
                env={**os.environ},
                start_new_session=True,
            )

        return jsonify({'success': True, 'message': f'Обогащение ЖК «{rc.name}» запущено (PID {proc.pid})', 'log_file': log_file})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/admin/complex/<int:complex_id>/enrich-single-log')
@admin_required
def admin_complex_enrich_single_log(complex_id):
    """Возвращает лог обогащения конкретного ЖК"""
    log_file = os.path.join(_SCRIPTS_DIR, f'.enrich_single_{complex_id}.log')
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                return jsonify({'log': f.read()})
        return jsonify({'log': '(лог ещё не создан — запустите обогащение)'})
    except Exception as e:
        return jsonify({'log': f'Ошибка чтения лога: {e}'})


@admin_bp.route('/admin/enrichment/parse-single', methods=['POST'])
@admin_required
def admin_enrichment_parse_single():
    """Парсинг одного ЖК по URL ЦИАН — фото, описание, застройщик, квартиры."""
    import subprocess, sys
    try:
        data = request.get_json(silent=True) or {}
        jk_url = (data.get('jk_url') or '').strip()
        city_id = str(data.get('city_id', 1))

        if not jk_url:
            return jsonify({'success': False, 'message': 'Не указан URL ЖК'}), 400
        if 'cian.ru' not in jk_url:
            return jsonify({'success': False, 'message': 'URL должен быть ссылкой на ЦИАН'}), 400

        script = os.path.join(_SCRIPTS_DIR, 'parse_jk_by_url.py')
        log_file = os.path.join(_SCRIPTS_DIR, '.enrich_log.txt')

        with open(log_file, 'w') as lf:
            lf.write(f'[parse-single] URL: {jk_url}\n')

        with open(log_file, 'a') as lf:
            proc = subprocess.Popen(
                [sys.executable, script, jk_url, city_id],
                stdout=lf, stderr=lf,
                env={**os.environ},
                start_new_session=True,
            )

        return jsonify({'success': True, 'message': f'Парсинг ЖК запущен (PID {proc.pid})'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500





@admin_bp.route('/admin/enrichment/db-stats')
@admin_required
def admin_enrichment_db_stats():
    """Live DB stats: apartment count, JK count, speed — bypasses cache."""
    try:
        from sqlalchemy import func
        from models import ResidentialComplex, Property
        apt_count = db.session.query(func.count(Property.id)).filter_by(is_active=True, city_id=1).scalar() or 0
        jk_count  = db.session.query(func.count(ResidentialComplex.id)).filter_by(is_active=True, city_id=1).scalar() or 0
        # Parse last batch-save line from log for speed info
        last_batch = None
        total_saved = 0
        try:
            log_path = os.path.join(_SCRIPTS_DIR, '.enrich_log.txt')
            if os.path.exists(log_path):
                with open(log_path, 'r', errors='replace') as lf:
                    lines = lf.readlines()
                for line in reversed(lines):
                    if '💾 Записано в БД' in line:
                        last_batch = line.strip()
                        break
                # Count total saved from all batch lines
                import re
                for line in lines:
                    m = re.search(r'в этом прогоне:\s*(\d+)', line)
                    if m:
                        total_saved = max(total_saved, int(m.group(1)))
        except Exception:
            pass
        return jsonify({
            'apt_count': apt_count,
            'jk_count': jk_count,
            'last_batch': last_batch,
            'total_saved': total_saved,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Multi-city parser control ──────────────────────────────────────────────────


@admin_bp.route('/admin/enrichment/full-stats')
@admin_required
def admin_enrichment_full_stats():
    """Full DB stats: developers, complexes, buildings, apartments per city."""
    try:
        from app import _load_city_config_all
        from models import ResidentialComplex, Property, Developer, Building
        from sqlalchemy import func as sqlfunc
        cities = _load_city_config_all()
        # Count developers per city (via complexes)
        dev_rows = db.session.execute(text("""
            SELECT rc.city_id, COUNT(DISTINCT rc.developer_id) as devs
            FROM residential_complexes rc
            WHERE rc.developer_id IS NOT NULL AND rc.is_active = true
            GROUP BY rc.city_id
        """)).fetchall()
        dev_map = {r.city_id: r.devs for r in dev_rows}
        # Count all developers
        total_devs = db.session.execute(text("SELECT COUNT(*) FROM developers WHERE is_active=true")).scalar() or 0
        # Count complexes per city
        rc_rows = db.session.query(
            ResidentialComplex.city_id,
            sqlfunc.count(ResidentialComplex.id).label("rc")
        ).filter(ResidentialComplex.is_active == True).group_by(ResidentialComplex.city_id).all()
        rc_map = {r.city_id: r.rc for r in rc_rows}
        # Count buildings per city (via complexes)
        try:
            bld_rows = db.session.execute(text("""
                SELECT rc.city_id, COUNT(b.id) as blds
                FROM buildings b
                JOIN residential_complexes rc ON b.complex_id = rc.id
                WHERE b.is_active = true
                GROUP BY rc.city_id
            """)).fetchall()
            bld_map = {r.city_id: r.blds for r in bld_rows}
        except Exception:
            db.session.rollback()
            bld_map = {}
        # Count apartments per city
        apt_rows = db.session.query(
            Property.city_id,
            sqlfunc.count(Property.id).label("apt"),
            sqlfunc.max(Property.updated_at).label("last_upd")
        ).filter(Property.is_active == True).group_by(Property.city_id).all()
        apt_map = {r.city_id: {"apt": r.apt, "last_upd": r.last_upd.strftime("%d.%m %H:%M") if r.last_upd else None} for r in apt_rows}
        result = []
        for cid, cfg in cities.items():
            result.append({
                "id": cid,
                "name": cfg["name"],
                "developers": dev_map.get(cid, 0),
                "complexes": rc_map.get(cid, 0),
                "buildings": bld_map.get(cid, 0),
                "apartments": apt_map.get(cid, {}).get("apt", 0),
                "last_updated": apt_map.get(cid, {}).get("last_upd"),
                "running": _city_is_running(cid),
            })
        return jsonify({
            "cities": result,
            "totals": {
                "developers": total_devs,
                "complexes": sum(rc_map.values()),
                "buildings": sum(bld_map.values()),
                "apartments": sum(a["apt"] for a in apt_map.values()),
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/admin/enrichment/cities-stats')
@admin_required
def admin_enrichment_cities_stats():
    """Return per-city stats: complexes, apartments, last update, running status."""
    try:
        city_config_live = _load_city_config_live()
        from models import ResidentialComplex, Property
        from sqlalchemy import func as sqlfunc
        rows = db.session.query(
            Property.city_id,
            sqlfunc.count(Property.id).label('apt'),
            sqlfunc.max(Property.updated_at).label('last_upd'),
        ).filter(Property.is_active == True).group_by(Property.city_id).all()
        apt_map = {r.city_id: {'apt': r.apt, 'last_upd': r.last_upd.strftime('%d.%m.%Y %H:%M') if r.last_upd else None} for r in rows}
        rc_rows = db.session.query(
            ResidentialComplex.city_id,
            sqlfunc.count(ResidentialComplex.id).label('rc'),
        ).filter(ResidentialComplex.is_active == True).group_by(ResidentialComplex.city_id).all()
        rc_map = {r.city_id: r.rc for r in rc_rows}
        result = []
        for cid, cfg in city_config_live.items():
            result.append({
                'id': cid,
                'name': cfg['name'],
                'complexes': rc_map.get(cid, 0),
                'apartments': apt_map.get(cid, {}).get('apt', 0),
                'last_updated': apt_map.get(cid, {}).get('last_upd'),
                'running': _city_is_running(cid),
                'pages': cfg['total_pages'],
            })
        return jsonify({'cities': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@admin_bp.route('/admin/enrichment/start-city', methods=['POST'])
@admin_required
def admin_enrichment_start_city():
    """Start run_city.py for a specific city and mode."""
    import json as _json
    global _city_procs
    import subprocess
    data = request.get_json(silent=True) or {}
    city_id = int(data.get('city_id', 0))
    mode = data.get('mode', 'full')  # 'full', 'prices', 'jk'

    # Always reload city config from disk (not the stale in-memory CITY_CONFIG_ALL)
    # so newly added cities are immediately available without a server restart.
    city_config_live = _load_city_config_live()

    if city_id not in city_config_live:
        return jsonify({'success': False, 'message': f'Неизвестный город: {city_id}'}), 400
    if _city_is_running(city_id):
        return jsonify({'success': False, 'message': f'{city_config_live[city_id]["name"]}: уже выполняется'})
    scripts_dir = _SCRIPTS_DIR
    log_file = _city_log_file(city_id)
    lf = open(log_file, 'w', encoding='utf-8')
    data = request.get_json(silent=True) or {}
    batch_limit = int(data.get('limit', 0))  # 0 = без лимита (осторожно!)

    if mode in ('jk', 'jk-force'):
        script = os.path.join(scripts_dir, 'fix_jk_bulk.py')
        cmd = [__import__('sys').executable, '-u', script, '--city', str(city_id)]
        force_mode = (mode == 'jk-force')
        if force_mode:
            cmd.append('--force')
            # При --force обрабатываем все активные ЖК, без лимита (или заданный)
            effective_limit = batch_limit if batch_limit > 0 else 0
            if effective_limit:
                cmd += ['--limit', str(effective_limit)]
            label = f'🔄 Обогащение ВСЕХ ЖК (принудительно{"" if not effective_limit else f", до {effective_limit}"})'
        else:
            # Защита от зависания: по умолчанию батч 30 ЖК за сессию
            effective_limit = batch_limit if batch_limit > 0 else 30
            cmd += ['--limit', str(effective_limit)]
            label = f'🖼️ Обогащение ЖК (до {effective_limit} шт.)'
    else:
        script = os.path.join(scripts_dir, 'run_city.py')
        cmd = [__import__('sys').executable, '-u', script, '--city', str(city_id), '--mode', mode]
        if mode == 'full':
            cmd.append('--reset')  # всегда сбрасываем кэш при полном прогоне — собираем актуальные данные
        label = '⚡ Обновление цен' if mode == 'prices' else '🏗️ Полный прогон'
    if not os.path.exists(script):
        lf.close()
        return jsonify({'success': False, 'message': f'Скрипт не найден: {os.path.basename(script)}'}), 500

    # Watchdog: следит за процессом — убивает при зависании, запускает пост-шаги при успехе
    MAX_RUNTIME = 3600 if mode == 'full' else 1800  # 1ч для full, 30мин для остальных

    proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env={**os.environ},
                            start_new_session=True)
    _city_procs[city_id] = proc

    def _watchdog(p, city, max_sec, logf, enrich_mode, s_dir):
        """Мониторит дочерний процесс. После успешного завершения jk/jk-force
        автоматически запускает parse_cian_addresses.py для города (автопайплайн)."""
        import time as _t
        import sys as _sys

        start = _t.time()
        # Поллинг каждые 5 сек вместо sleep(max_sec) — быстро замечаем завершение
        while p.poll() is None:
            if _t.time() - start > max_sec:
                try:
                    import signal as _sig
                    p.send_signal(_sig.SIGTERM)
                    _t.sleep(5)
                    if p.poll() is None:
                        p.kill()
                except Exception:
                    pass
                try:
                    with open(logf, 'a', encoding='utf-8') as _lf:
                        _lf.write(f'\n⏱️ WATCHDOG: процесс убит по таймауту ({max_sec//60} мин)\n')
                except Exception:
                    pass
                logger.warning(f'⏱️ Enrichment watchdog killed city={city} after {max_sec}s')
                return
            _t.sleep(5)

        rc = p.returncode
        try:
            with open(logf, 'a', encoding='utf-8') as _lf:
                _lf.write(f'\n✅ Процесс завершён (код {rc})\n')
        except Exception:
            pass

        # ── Автопайплайн: после jk/jk-force → разбираем адреса автоматически ──
        if enrich_mode in ('jk', 'jk-force') and rc == 0:
            try:
                with open(logf, 'a', encoding='utf-8') as _lf:
                    _lf.write('\n🔄 АВТО: запускаем разбор адресов (parse_cian_addresses.py)...\n')
                parse_script = os.path.join(s_dir, 'parse_cian_addresses.py')
                parse_cmd = [_sys.executable, '-u', parse_script]
                if city:
                    parse_cmd += ['--city', str(city)]
                with open(logf, 'a', encoding='utf-8') as _lf_parse:
                    parse_proc = subprocess.Popen(
                        parse_cmd, stdout=_lf_parse, stderr=subprocess.STDOUT,
                        env={**os.environ}, start_new_session=True
                    )
                    parse_proc.wait(timeout=300)  # 5 минут максимум
                with open(logf, 'a', encoding='utf-8') as _lf:
                    _lf.write(f'✅ Разбор адресов завершён (код {parse_proc.returncode})\n')
                logger.info(f'Auto parse_cian_addresses city={city}: rc={parse_proc.returncode}')

                # ── Авто-шаг 2: propagate RC address → properties ──────────
                try:
                    with open(logf, 'a', encoding='utf-8') as _lf:
                        _lf.write('\n🔄 АВТО: синхронизируем адреса квартир (propagate_rc_address.py)...\n')
                    prop_script = os.path.join(s_dir, 'propagate_rc_address.py')
                    prop_cmd = [_sys.executable, '-u', prop_script]
                    if city:
                        prop_cmd += ['--city', str(city)]
                    with open(logf, 'a', encoding='utf-8') as _lf_prop:
                        prop_proc = subprocess.Popen(
                            prop_cmd, stdout=_lf_prop, stderr=subprocess.STDOUT,
                            env={**os.environ}, start_new_session=True
                        )
                        prop_proc.wait(timeout=120)
                    with open(logf, 'a', encoding='utf-8') as _lf:
                        _lf.write(f'✅ Синхронизация адресов завершена (код {prop_proc.returncode})\n')
                    logger.info(f'Auto propagate_rc_address city={city}: rc={prop_proc.returncode}')
                except Exception as _pe:
                    logger.error(f'Auto propagate_rc_address failed city={city}: {_pe}')

            except Exception as _ex:
                logger.error(f'Auto parse_addresses failed city={city}: {_ex}')
                try:
                    with open(logf, 'a', encoding='utf-8') as _lf:
                        _lf.write(f'❌ Разбор адресов: ошибка — {_ex}\n')
                except Exception:
                    pass

    import threading as _thr
    _thr.Thread(target=_watchdog,
                args=(proc, city_id, MAX_RUNTIME, _city_log_file(city_id), mode, scripts_dir),
                daemon=True).start()

    return jsonify({'success': True, 'message': f'{label} для {city_config_live[city_id]["name"]} запущено (PID {proc.pid}). После завершения адреса разберутся автоматически.'})



@admin_bp.route('/admin/enrichment/geocode-rc', methods=['POST'])
@admin_required
def admin_enrichment_geocode_rc():
    """Batch DaData address normalization for ResidentialComplex.
    Fills addr_city, addr_street, addr_house, address_city_district, latitude, longitude
    for all active RCs of a given city that have a raw `address` field.
    Runs in a background thread so the endpoint returns immediately.
    """
    from app import db
    import threading as _thr
    data = request.get_json(silent=True) or {}
    city_id = int(data.get('city_id', 1))
    force = bool(data.get('force', False))  # if True, overwrite existing addr_street too

    try:
        from services.dadata_client import get_dadata_client
        dadata = get_dadata_client()
        if dadata is None:
            return jsonify({'success': False, 'message': 'DaData не настроен (нет DADATA_API_KEY)'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'DaData недоступен: {e}'}), 400

    from models import ResidentialComplex
    query = ResidentialComplex.query.filter_by(city_id=city_id, is_active=True)
    if not force:
        # Only process RCs that are missing structured address
        query = query.filter(
            db.or_(
                ResidentialComplex.addr_street.is_(None),
                ResidentialComplex.addr_street == ''
            )
        )
    rcs = query.filter(
        ResidentialComplex.address.isnot(None),
        ResidentialComplex.address != ''
    ).all()

    if not rcs:
        return jsonify({'success': True, 'message': 'Нет ЖК для геокодирования'})

    def _run_geocode(rc_list, cid, force_flag):
        from app import app as _app
        ok = err = skip = 0
        with _app.app_context():
            from app import db as _db
            from models import ResidentialComplex as RC
            from services.dadata_client import get_dadata_client
            dd = get_dadata_client()
            for rc in rc_list:
                try:
                    result = dd.enrich_property_address(
                        rc.address,
                        city_id=cid
                    )
                    if not result:
                        skip += 1
                        continue
                    # Map DaData result fields onto RC model fields
                    if result.get('parsed_street'):
                        rc.addr_street = result['parsed_street']
                    if result.get('parsed_house'):
                        rc.addr_house = result['parsed_house']
                    if result.get('parsed_city'):
                        rc.addr_city = result['parsed_city']
                    if result.get('parsed_area'):
                        rc.address_city_district = result['parsed_area']
                    if result.get('parsed_settlement') and not rc.address_city_district:
                        rc.address_city_district = result['parsed_settlement']
                    # Update coordinates only if missing or force
                    if result.get('latitude') and result.get('longitude'):
                        if force_flag or not rc.latitude:
                            rc.latitude = float(result['latitude'])
                            rc.longitude = float(result['longitude'])
                    ok += 1
                except Exception as ex:
                    logger.warning(f'DaData geocode RC id={rc.id}: {ex}')
                    err += 1
            try:
                _db.session.commit()
            except Exception as ex:
                _db.session.rollback()
                logger.error(f'DaData geocode commit error: {ex}')
        logger.info(f'DaData geocode city={cid}: ok={ok} skip={skip} err={err} / {len(rc_list)} ЖК')

    _thr.Thread(target=_run_geocode, args=(rcs, city_id, force), daemon=True).start()
    return jsonify({
        'success': True,
        'message': f'Геокодирование DaData запущено для {len(rcs)} ЖК города {city_id} (фон)'
    })


@admin_bp.route('/admin/enrichment/parse-addresses', methods=['POST'])
@admin_required
def admin_enrichment_parse_addresses():
    """Run parse_cian_addresses.py to split the raw `address` field into
    addr_region / addr_city / address_city_district / address_quarter / addr_street / addr_house.
    Fast (pure-Python, no network), runs in a background thread.
    Supports force=true to overwrite existing values (not just fill NULLs).
    """
    import threading as _thr
    data = request.get_json(silent=True) or {}
    city_id = int(data.get('city_id', 0))  # 0 = all cities
    force = bool(data.get('force', False))

    def _run(cid, force_mode):
        from app import app as _app, db as _db
        from sqlalchemy import text as _text
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', 'scripts'))
        from parse_cian_addresses import parse_address
        updated = errors = 0
        with _app.app_context():
            q = "SELECT id, address FROM residential_complexes WHERE address IS NOT NULL AND address != ''"
            params = {}
            if cid:
                q += " AND city_id = :city_id"
                params['city_id'] = cid
            rows = _db.session.execute(_text(q), params).fetchall()
            for row in rows:
                try:
                    parsed = parse_address(row[1])
                    if force_mode:
                        # Build SET clause only for non-NULL parsed values
                        set_parts = []
                        set_params = {'id': row[0]}
                        for col in ('addr_region', 'addr_city', 'address_city_district',
                                    'address_quarter', 'addr_street', 'addr_house'):
                            if parsed.get(col) is not None:
                                set_parts.append(f"{col} = :{col}")
                                set_params[col] = parsed[col]
                        if set_parts:
                            _db.session.execute(
                                _text(f"UPDATE residential_complexes SET {', '.join(set_parts)} WHERE id = :id"),
                                set_params
                            )
                    else:
                        _db.session.execute(_text("""
                            UPDATE residential_complexes SET
                                addr_region           = COALESCE(addr_region,           :addr_region),
                                addr_city             = COALESCE(addr_city,             :addr_city),
                                address_city_district = COALESCE(address_city_district, :address_city_district),
                                address_quarter       = COALESCE(address_quarter,       :address_quarter),
                                addr_street           = COALESCE(addr_street,           :addr_street),
                                addr_house            = COALESCE(addr_house,            :addr_house)
                            WHERE id = :id
                        """), {**parsed, 'id': row[0]})
                    updated += 1
                except Exception as ex:
                    logger.warning(f'parse_addresses RC id={row[0]}: {ex}')
                    errors += 1
            try:
                _db.session.commit()
            except Exception as ex:
                _db.session.rollback()
                logger.error(f'parse_addresses commit error: {ex}')
        city_label = f'city_id={cid}' if cid else 'все города'
        mode_label = 'force' if force_mode else 'coalesce'
        logger.info(f'parse_cian_addresses ({city_label}, {mode_label}): updated={updated} errors={errors}')

    _thr.Thread(target=_run, args=(city_id, force), daemon=True).start()
    city_label = f'города {city_id}' if city_id else 'всех городов'
    mode_msg = ' (перезапись существующих)' if force else ' (только пустые поля)'
    return jsonify({'success': True, 'message': f'Разбор адресов ЖК {city_label} запущен в фоне{mode_msg} (~10 сек)'})


@admin_bp.route('/admin/enrichment/enrich-addresses-novostroyki', methods=['POST'])
@admin_required
def admin_enrichment_addresses_novostroyki():
    """Запускает enrich_addresses_from_novostroyki.py — заполняет адреса ЖК
    (округ, микрорайон, город, улица) напрямую из CIAN newobject API (/novostroyki/).
    Требует прокси (ENRICH_PROXY_URL) для обхода блокировки CIAN.
    """
    import threading as _thr
    data = request.get_json(silent=True) or {}
    city_id = int(data.get('city_id', 0))
    force = bool(data.get('force', False))

    def _run(cid, force_mode):
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..'))
        try:
            from scripts.enrich_addresses_from_novostroyki import (
                enrich_city_addresses, CITY_CONFIG
            )
            if cid:
                cfg = CITY_CONFIG.get(str(cid))
                if cfg:
                    stats = enrich_city_addresses(
                        city_id=cid,
                        cian_region_id=cfg['cian_region_id'],
                        force=force_mode,
                        dry_run=False,
                    )
                    logger.info(f'novostroyki_addresses city={cid}: {stats}')
            else:
                for city_id_str, cfg in CITY_CONFIG.items():
                    stats = enrich_city_addresses(
                        city_id=int(city_id_str),
                        cian_region_id=cfg['cian_region_id'],
                        force=force_mode,
                        dry_run=False,
                    )
                    logger.info(f'novostroyki_addresses city={city_id_str}: {stats}')
        except Exception as ex:
            logger.error(f'enrich_addresses_novostroyki error: {ex}', exc_info=True)

    _thr.Thread(target=_run, args=(city_id, force), daemon=True).start()
    city_label = f'города {city_id}' if city_id else 'всех городов'
    mode_msg = ' (перезапись)' if force else ' (только пустые поля)'
    return jsonify({
        'success': True,
        'message': f'Обогащение адресов из CIAN /novostroyki/ для {city_label} запущено{mode_msg}. '
                   f'Требует прокси для обхода блокировки CIAN (~2-10 мин).'
    })


@admin_bp.route('/admin/enrichment/stop-city', methods=['POST'])
@admin_required
def admin_enrichment_stop_city():
    from app import CITY_CONFIG_ALL
    global _city_procs
    import signal
    data = request.get_json(silent=True) or {}
    city_id = int(data.get('city_id', 0))
    proc = _city_procs.get(city_id)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
        return jsonify({'success': True, 'message': f'Остановлено: {CITY_CONFIG_ALL.get(city_id, {}).get("name", city_id)}'})
    return jsonify({'success': False, 'message': 'Процесс не найден или уже завершён'})



@admin_bp.route('/admin/enrichment/city-log')
@admin_required
def admin_enrichment_city_log():
    city_id = int(request.args.get('city_id', 0))
    log_file = _city_log_file(city_id)
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r', errors='replace') as f:
                lines = f.readlines()
            log = ''.join(lines[-300:])
        else:
            log = f'(лог для города {city_id} не найден — запустите обогащение)'
    except Exception as e:
        log = f'Ошибка чтения лога: {e}'
    return jsonify({'log': log, 'running': _city_is_running(city_id)})



@admin_bp.route('/admin/enrichment/cities-status')
@admin_required
def admin_enrichment_cities_status():
    city_config_live = _load_city_config_live()
    return jsonify({str(cid): _city_is_running(cid) for cid in city_config_live})



@admin_bp.route('/admin/enrichment/cian-region-lookup', methods=['POST'])
@admin_required
def admin_enrichment_cian_region_lookup():
    """Find correct CIAN region ID for any city by name or subdomain."""
    import re as _re
    import json as _json
    try:
        import requests as _rq
    except ImportError:
        return jsonify({'success': False, 'error': 'requests не установлен'}), 500

    data = request.get_json(silent=True) or {}
    city_name      = (data.get('city_name') or '').strip()
    subdomain_hint = (data.get('subdomain') or '').strip().lower()
    direct_region  = data.get('region_id')   # integer — from URL extraction in frontend
    cian_url_raw   = (data.get('cian_url') or '').strip()

    # If no input at all
    if not city_name and not subdomain_hint and not direct_region and not cian_url_raw:
        return jsonify({'success': False, 'error': 'Укажите название города или вставьте URL'}), 400

    # Load proxy from enrich settings
    cfg_path = os.path.join(_SCRIPTS_DIR, '.enrich_settings.json')
    try:
        with open(cfg_path, encoding='utf-8') as _f:
            _es = _json.load(_f)
    except Exception:
        _es = {}
    proxy_url = _es.get('proxy_url', '').strip()

    # Fast path: region ID already known (extracted from CIAN URL in frontend)
    if direct_region:
        direct_region = int(direct_region)
        # Derive subdomain from cian_url_raw if available
        _sd_match = _re.search(r'https?://([a-z0-9-]+)\.cian\.ru', cian_url_raw) if cian_url_raw else None
        subdomain_from_url = _sd_match.group(1) if _sd_match else 'cian'

        api_sess = _rq.Session()
        api_sess.headers.update({'Content-Type': 'application/json', 'Origin': 'https://www.cian.ru'})
        if proxy_url:
            api_sess.proxies = {'http': proxy_url, 'https': proxy_url}

        q = {
            '_type': 'flatsale',
            'engine_version': {'type': 'term', 'value': 2},
            'region': {'type': 'terms', 'value': [direct_region]},
            'newobject': {'type': 'term', 'value': True},
            'from_developer': {'type': 'term', 'value': True},
            'page': {'type': 'term', 'value': 1},
        }
        offers_count = 0
        sample_url   = ''
        try:
            ar = api_sess.post(
                'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                json={'jsonQuery': q}, timeout=20
            )
            if ar.status_code == 200:
                ad = ar.json()
                offers = ad.get('data', {}).get('offersSerialized', [])
                offers_count = ad.get('data', {}).get('aggregatedCount', 0)
                if offers:
                    sample_url = str(offers[0].get('fullUrl', ''))
        except Exception:
            pass

        # Also try newobjectsale if flatsale+from_dev returned 0
        if offers_count == 0:
            try:
                q2 = {
                    '_type': 'newobjectsale',
                    'engine_version': {'type': 'term', 'value': 2},
                    'region': {'type': 'terms', 'value': [direct_region]},
                    'page': {'type': 'term', 'value': 1},
                }
                ar2 = api_sess.post(
                    'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                    json={'jsonQuery': q2}, timeout=20
                )
                if ar2.status_code == 200:
                    ad2 = ar2.json()
                    offers2 = ad2.get('data', {}).get('offersSerialized', [])
                    offers_count = ad2.get('data', {}).get('aggregatedCount', 0)
                    if offers2:
                        sample_url = str(offers2[0].get('fullUrl', ''))
            except Exception:
                pass

        # Check if city already exists in city_config.json
        city_config_path = os.path.join(_SCRIPTS_DIR, 'city_config.json')
        try:
            with open(city_config_path, encoding='utf-8') as _cf:
                _ecfg = _json.load(_cf)
            existing_id = next(
                (int(_cid) for _cid, _ccfg in _ecfg.items()
                 if _ccfg.get('cian_region_id') == direct_region),
                None
            )
        except Exception:
            existing_id = None

        return jsonify({
            'success': True,
            'cian_region_id': direct_region,
            'subdomain': subdomain_from_url,
            'offers_count': offers_count,
            'sample_url': sample_url,
            'page_url': cian_url_raw or f'https://www.cian.ru/?region={direct_region}',
            'city_already_exists': existing_id,
            'source': 'url',
        })

    # Russian → CIAN subdomain transliteration (GOST-style)
    def _ru_to_slug(s, alt=False):
        _t_main = {
            'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
            'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
            'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
            'щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
        }
        _t_alt = {
            'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
            'и':'i','й':'i','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
            'с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh',
            'щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
        }
        _t = _t_alt if alt else _t_main
        out = ''
        for c in s.lower():
            if c in _t:
                out += _t[c]
            elif c in (' ', '-'):
                out += '-'
            elif c.isalpha() and c.isascii():
                out += c
        return _re.sub(r'-+', '-', out).strip('-')

    # Build candidate subdomains to try
    candidates = []
    if subdomain_hint:
        candidates.append(subdomain_hint)
    if city_name:
        s1 = _ru_to_slug(city_name, alt=False)
        s2 = _ru_to_slug(city_name, alt=True)
        if s1 not in candidates:
            candidates.append(s1)
        if s2 and s2 != s1 and s2 not in candidates:
            candidates.append(s2)

    # HTTP session (with proxy)
    page_sess = _rq.Session()
    page_sess.headers.update({
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,*/*',
        'Accept-Language': 'ru-RU,ru;q=0.9',
    })
    if proxy_url:
        page_sess.proxies = {'http': proxy_url, 'https': proxy_url}

    api_sess = _rq.Session()
    api_sess.headers.update({
        'Content-Type': 'application/json',
        'Origin': 'https://www.cian.ru',
    })
    if proxy_url:
        api_sess.proxies = {'http': proxy_url, 'https': proxy_url}

    def _strip_non_latin(s):
        """Remove emoji and non-ASCII chars that would break a subdomain."""
        out = ''
        for c in s:
            if c.isascii() and (c.isalnum() or c == '-'):
                out += c
        return out.strip('-')

    def _test_cian_id(sess, rid):
        """Test a CIAN region/city ID via search API. Returns (count, sample_url)."""
        for _type in ('newobjectsale', 'flatsale'):
            q = {
                '_type': _type,
                'engine_version': {'type': 'term', 'value': 2},
                'region': {'type': 'terms', 'value': [rid]},
                'newobject': {'type': 'term', 'value': True},
                'from_developer': {'type': 'term', 'value': True},
                'page': {'type': 'term', 'value': 1},
            }
            try:
                ar = sess.post(
                    'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
                    json={'jsonQuery': q}, timeout=20
                )
                if ar.status_code == 200:
                    ad = ar.json()
                    cnt = ad.get('data', {}).get('aggregatedCount', 0)
                    offers = ad.get('data', {}).get('offersSerialized', [])
                    url = str(offers[0].get('fullUrl', '')) if offers else ''
                    if cnt > 0:
                        return cnt, url
            except Exception:
                pass
        return 0, ''

    # Sanitize candidates — strip emojis that break subdomains
    candidates = [_strip_non_latin(c) for c in candidates if _strip_non_latin(c)]

    best = None
    for subdomain in candidates[:4]:
        # Try multiple CIAN page URL patterns
        page_text = None
        used_page_url = None
        for _path in ('/novostrojki/', '/kupit-novostrojku/', '/'):
            try:
                _url = f'https://{subdomain}.cian.ru{_path}'
                r = page_sess.get(_url, timeout=20, allow_redirects=True)
                if r.status_code == 200 and 'captcha' not in r.text[:500].lower():
                    page_text = r.text
                    used_page_url = _url
                    break
            except Exception:
                continue

        if not page_text:
            continue

        # Extract regionId — for CIAN search API this is the Oblast/Krai level ID
        # IMPORTANT: regionId (Oblast) must be used, NOT cityId (city).
        # The CIAN search 'region' filter accepts only region-level IDs.
        city_id_raw = None
        region_id_raw = None
        for pat in (
            r'"regionId"\s*:\s*(\d+)',
            r'currentRegionId["\s:]+(\d+)',
            r'regionId["\s:=]+(\d+)',
        ):
            m = _re.search(pat, page_text)
            if m:
                v = int(m.group(1))
                if v > 1:
                    region_id_raw = v
                    break
        for pat in (
            r'"cityId"\s*:\s*(\d+)',
            r'cityId["\s:=]+(\d+)',
        ):
            m = _re.search(pat, page_text)
            if m:
                v = int(m.group(1))
                if v > 1:
                    city_id_raw = v
                    break

        # Also try extracting from redirect URL if CIAN redirected with ?region=
        redir_match = _re.search(r'[?&]region=(\d+)', r.url if hasattr(r, 'url') else '')
        if redir_match:
            region_id_raw = region_id_raw or int(redir_match.group(1))

        if not region_id_raw and not city_id_raw:
            continue

        # Test regionId first (correct for CIAN search API), then cityId as fallback
        offers_count = 0
        sample_url   = ''
        cian_id      = None

        if region_id_raw:
            offers_count, sample_url = _test_cian_id(api_sess, region_id_raw)
            if offers_count > 0:
                cian_id = region_id_raw

        if not cian_id and city_id_raw:
            offers_count, sample_url = _test_cian_id(api_sess, city_id_raw)
            if offers_count > 0:
                cian_id = city_id_raw

        # Even with 0 offers, keep regionId as best guess (city may have few new builds)
        if not cian_id:
            cian_id = region_id_raw or city_id_raw

        if not cian_id:
            continue

        best = {
            'cian_region_id': cian_id,
            'subdomain': subdomain,
            'offers_count': offers_count,
            'sample_url': sample_url,
            'page_url': used_page_url or f'https://{subdomain}.cian.ru/novostrojki/',
            'city_id_raw': city_id_raw,
            'region_id_raw': region_id_raw,
        }
        # Confirmed — stop
        if offers_count > 0:
            break

    # Fallback: если субдомен не нашёл — пробуем ЦИАН suggest API по имени города
    if not best and city_name:
        _suggest_urls = [
            f'https://api.cian.ru/geo-suggest/v2/suggest/?term={_rq.utils.quote(city_name)}&type=location',
            f'https://api.cian.ru/geo-suggest/v2/suggest/?term={_rq.utils.quote(city_name)}&type=all',
        ]
        for _surl in _suggest_urls:
            try:
                _sr = api_sess.get(_surl, timeout=15)
                if _sr.status_code == 200:
                    _sd = _sr.json()
                    # Ищем элемент типа city/district с matching именем
                    for _item in (_sd.get('items') or _sd.get('suggestions') or [])[:8]:
                        _rid = (_item.get('id') or _item.get('regionId') or
                                _item.get('data', {}).get('id'))
                        _itype = (_item.get('type') or '').lower()
                        if _rid and _itype in ('city', 'district', 'region', 'location', ''):
                            _rid = int(_rid)
                            _cnt, _sampleurl = _test_cian_id(api_sess, _rid)
                            best = {
                                'cian_region_id': _rid,
                                'subdomain': 'cian',
                                'offers_count': _cnt,
                                'sample_url': _sampleurl,
                                'page_url': f'https://www.cian.ru/?region={_rid}',
                                'city_id_raw': _rid,
                                'region_id_raw': None,
                            }
                            if _cnt > 0:
                                break
                    if best and best['offers_count'] > 0:
                        break
            except Exception:
                pass

    # Second fallback: попробуем ЦИАН поиск по названию через основной suggest
    if not best and city_name:
        try:
            _alt = api_sess.get(
                f'https://api.cian.ru/location-suggester/v1/get/?text={_rq.utils.quote(city_name)}&limit=5',
                timeout=15
            )
            if _alt.status_code == 200:
                _adata = _alt.json()
                for _loc in (_adata.get('data') or [])[:5]:
                    _rid = _loc.get('id') or _loc.get('locationId')
                    if _rid:
                        _rid = int(_rid)
                        _cnt, _sampleurl = _test_cian_id(api_sess, _rid)
                        best = {
                            'cian_region_id': _rid,
                            'subdomain': 'cian',
                            'offers_count': _cnt,
                            'sample_url': _sampleurl,
                            'page_url': f'https://www.cian.ru/?region={_rid}',
                            'city_id_raw': _rid,
                            'region_id_raw': None,
                        }
                        if _cnt > 0:
                            break
        except Exception:
            pass

    if not best:
        return jsonify({
            'success': False,
            'error': (
                f'Не удалось найти CIAN регион для «{city_name or subdomain_hint}». '
                'Проверьте название или укажите CIAN-поддомен вручную '
                '(например: rostov-na-donu для Ростова-на-Дону).'
            )
        })

    # Check if city already exists in city_config.json
    city_config_path = os.path.join(_SCRIPTS_DIR, 'city_config.json')
    try:
        with open(city_config_path, encoding='utf-8') as _cf:
            _existing_cfg = _json.load(_cf)
        existing_id = None
        for _cid, _ccfg in _existing_cfg.items():
            if _ccfg.get('cian_region_id') == best['cian_region_id']:
                existing_id = int(_cid)
                break
    except Exception:
        existing_id = None

    best['success'] = True
    best['city_already_exists'] = existing_id
    return jsonify(best)



@admin_bp.route('/admin/enrichment/update-city-config', methods=['POST'])
@admin_required
def admin_enrichment_update_city_config():
    """Update CIAN region ID for an existing city in city_config.json."""
    import json as _json
    data = request.get_json(silent=True) or {}
    city_id      = int(data.get('city_id', 0))
    cian_region_id = data.get('cian_region_id')

    if not city_id or not cian_region_id:
        return jsonify({'success': False, 'message': 'city_id и cian_region_id обязательны'}), 400

    cfg_path = os.path.join(_SCRIPTS_DIR, 'city_config.json')
    try:
        with open(cfg_path, encoding='utf-8') as _f:
            city_configs = _json.load(_f)
    except Exception as e:
        return jsonify({'success': False, 'message': f'Ошибка чтения конфига: {e}'}), 500

    key = str(city_id)
    if key not in city_configs:
        return jsonify({'success': False, 'message': f'Город {city_id} не найден в конфиге'}), 404

    old_id = city_configs[key].get('cian_region_id', '?')
    city_configs[key]['cian_region_id'] = int(cian_region_id)
    with open(cfg_path, 'w', encoding='utf-8') as _f:
        _json.dump(city_configs, _f, ensure_ascii=False, indent=2)

    # Reload CITY_CONFIG_ALL from file (so it's properly typed)
    from app import _load_city_config_all
    global CITY_CONFIG_ALL
    CITY_CONFIG_ALL = _load_city_config_all()

    city_name = city_configs[key].get('name', f'city_{city_id}')
    return jsonify({
        'success': True,
        'message': f'{city_name}: CIAN region ID обновлён {old_id} → {cian_region_id}'
    })



# ═══════════════════════════════════════════════════════════════
# Наш.дом.рф (nashdom) — обогащение ЖК
# ═══════════════════════════════════════════════════════════════


@admin_bp.route('/admin/enrichment/nashdom/stats')
@login_required
def admin_nashdom_stats():
    """Статистика: сколько ЖК обогащено с наш.дом.рф"""
    try:
        from sqlalchemy import text as _t
        with db.engine.connect() as conn:
            rows = conn.execute(_t("""
                SELECT c.id as city_id, c.name as city_name,
                    count(rc.id) as total_rc,
                    count(rc.nashdom_id) as enriched_rc,
                    count(rc.nashdom_photos) as with_photos,
                    count(b.id) as total_buildings
                FROM cities c
                LEFT JOIN residential_complexes rc ON rc.city_id = c.id
                LEFT JOIN buildings b ON b.complex_id = rc.id AND b.building_id LIKE 'nd-%'
                WHERE c.is_active = true
                GROUP BY c.id, c.name
                ORDER BY c.id
            """)).fetchall()
        data = [{
            'city_id': r.city_id,
            'city_name': r.city_name,
            'total_rc': r.total_rc,
            'enriched_rc': r.enriched_rc,
            'with_photos': r.with_photos,
            'total_buildings': r.total_buildings,
        } for r in rows]
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



@admin_bp.route('/admin/enrichment/nashdom/run', methods=['POST'])
@login_required
def admin_nashdom_run():
    """Запустить обогащение наш.дом.рф для города в фоне"""
    import subprocess, sys, os
    data = request.get_json(silent=True) or {}
    city_id = int(data.get('city_id', 1))
    jk_id   = data.get('jk_id')
    dry_run = bool(data.get('dry_run', False))
    limit   = data.get('limit')

    cmd = [sys.executable, '-u', 'scripts/nashdom_scraper.py', '--city', str(city_id)]
    if jk_id:
        cmd += ['--jk', str(jk_id)]
    if dry_run:
        cmd.append('--dry-run')
    if limit:
        cmd += ['--limit', str(limit)]

    log_path = f'/tmp/nashdom_city{city_id}.log'
    try:
        from app import _load_enrich_settings
        _es = _load_enrich_settings()
        proxy_url = _es.get('proxy_url', '').strip()
        run_env = {**os.environ}
        run_env['PYTHONUNBUFFERED'] = '1'
        if proxy_url:
            run_env['ENRICH_PROXY'] = proxy_url
            run_env['HTTP_PROXY']   = proxy_url
            run_env['HTTPS_PROXY']  = proxy_url
        with open(log_path, 'w') as lf:
            subprocess.Popen(
                cmd,
                stdout=lf, stderr=lf,
                cwd=os.getcwd(),
                env=run_env
            )
        return jsonify({'success': True, 'log_path': log_path,
                        'proxy_active': bool(proxy_url),
                        'message': f'Запущен для города {city_id}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



@admin_bp.route('/admin/enrichment/nashdom/log')
@login_required
def admin_nashdom_log():
    """Вернуть последние N строк лога + распарсенный прогресс"""
    import re as _re, os as _os, time as _time
    city_id = request.args.get('city_id', '1')
    log_path = f'/tmp/nashdom_city{city_id}.log'
    try:
        if not _os.path.exists(log_path):
            return jsonify({'success': True, 'log': '(лог пуст, процесс ещё не запускался)',
                            'running': False, 'progress': None})
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines_all = f.readlines()
        full_text = ''.join(lines_all)
        tail = ''.join(lines_all[-300:])
        running = _nashdom_is_running(city_id)

        # ── Парсим прогресс из лога ──────────────────────────────────────
        progress = None
        # Общее количество ЖК: «🏠 ... | 233 ЖК»
        m_total = _re.search(r'\|\s*(\d+)\s*ЖК', full_text)
        total = int(m_total.group(1)) if m_total else 0
        # Текущий ЖК: «[12/233] ЖК Название»
        all_progress = _re.findall(r'\[(\d+)/(\d+)\](.+)', full_text)
        current = 0
        current_name = ''
        if all_progress:
            last = all_progress[-1]
            current = int(last[0])
            total = int(last[1])
            current_name = last[2].strip()
        # Итоговая статистика: «📊 Итог: найдено X, обновлено Y, пропущено Z»
        m_summary = _re.search(r'найдено\s+(\d+),\s*обновлено\s+(\d+),\s*пропущено\s+(\d+)', full_text)
        # Счётчики
        matched_count  = len(_re.findall(r'🔍 Найден:', full_text))
        updated_count  = len(_re.findall(r'✅ Обновлено:', full_text))
        skipped_count  = len(_re.findall(r'⏭️.*кэш', full_text))
        failed_count   = len(_re.findall(r'❌ Не найден', full_text))
        photos_count   = len(_re.findall(r'hobjRenderPhotoUrl|фото', full_text))
        # Время
        elapsed = None
        if _os.path.exists(log_path):
            elapsed = int(_time.time() - _os.path.getmtime(log_path)) if not running else \
                      int(_time.time() - (_os.path.getctime(log_path)))
        # Прокси статус
        from app import _load_enrich_settings
        _es = _load_enrich_settings()
        proxy_url = _es.get('proxy_url', '').strip()
        proxy_pool = _es.get('proxy_pool', [])

        progress = {
            'total': total,
            'current': current,
            'pct': round(current / total * 100, 1) if total > 0 else 0,
            'current_name': current_name,
            'matched': matched_count,
            'updated': updated_count,
            'skipped': skipped_count,
            'failed': failed_count,
            'photos': photos_count,
            'finished': bool(m_summary),
            'proxy_url': proxy_url,
            'proxy_pool_count': len(proxy_pool),
        }

        return jsonify({'success': True, 'log': tail, 'running': running, 'progress': progress})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



@admin_bp.route('/admin/enrichment/nashdom/test', methods=['POST'])
@login_required
def admin_nashdom_test():
    """Тест: сухой прогон по 3 ЖК без записи в БД"""
    import subprocess, sys, os
    data = request.get_json(silent=True) or {}
    city_id = int(data.get('city_id', 1))
    cmd = [sys.executable, 'scripts/nashdom_scraper.py',
           '--city', str(city_id), '--limit', '3', '--dry-run']
    log_path = f'/tmp/nashdom_test_city{city_id}.log'
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=os.getcwd(), env={**os.environ}
        )
        output = proc.stdout + proc.stderr
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(output)
        return jsonify({'success': True, 'output': output[-3000:], 'log_path': log_path})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Превышено время ожидания (120с)'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



@admin_bp.route('/admin/enrichment/nashdom/status')
@login_required
def admin_nashdom_status():
    """Статус процесса обогащения по городам"""
    cities_status = {}
    import json as _json2
    for city_id in range(1, 9):
        log_path = f'/tmp/nashdom_city{city_id}.log'
        cities_status[str(city_id)] = {
            'running': _nashdom_is_running(str(city_id)),
            'has_log': os.path.exists(log_path),
        }
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    tail = f.readlines()[-5:]
                cities_status[str(city_id)]['last_line'] = tail[-1].strip() if tail else ''
            except Exception:
                pass
    return jsonify({'success': True, 'status': cities_status})



@admin_bp.route('/admin/upload-excel', methods=['POST'])
def admin_upload_excel():
    """Handle Excel file upload from admin panel"""
    try:
        if 'excel_file' not in request.files:
            return jsonify({'success': False, 'error': 'Файл не выбран'})
        
        file = request.files['excel_file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Файл не выбран'})
        
        if not file.filename.endswith(('.xlsx', '.xls')):
            return jsonify({'success': False, 'error': 'Поддерживаются только файлы Excel (.xlsx, .xls)'})
        
        # Save file to attached_assets directory
        import os
        import uuid
        
        # Ensure attached_assets directory exists
        os.makedirs('attached_assets', exist_ok=True)
        
        # Generate unique filename
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"upload_{uuid.uuid4().hex[:8]}{file_extension}"
        file_path = os.path.join('attached_assets', unique_filename)
        
        # Save the file
        file.save(file_path)
        
        # Запуск импорта в фоновом процессе для больших файлов
        try:
            import threading
            import time
            
            # Создаем уникальный ID задачи
            task_id = unique_filename.replace('.', '_')
            
            # Статус импорта (будем хранить в глобальной переменной)
            global import_status
            if 'import_status' not in globals():
                import_status = {}
            
            import_status[task_id] = {
                'status': 'processing',
                'progress': 0,
                'message': 'Обработка файла...',
                'started_at': time.time()
            }
            
            def background_import():
                try:
                    with app.app_context():
                        result = import_excel_to_database(file_path)
                    
                    # Обновляем статус при успехе
                    import_status[task_id] = {
                        'status': 'completed',
                        'progress': 100,
                        'message': f'✅ {result["message"]} Импортировано: {result["imported"]} записей.',
                        'result': result,
                        'completed_at': time.time()
                    }
                    
                    # Очищаем кеш
                    global _properties_cache, _cache_timestamp
                    _properties_cache = None
                    _cache_timestamp = None
                    
                except Exception as import_error:
                    # Обновляем статус при ошибке
                    import_status[task_id] = {
                        'status': 'error',
                        'progress': 0,
                        'message': f'❌ Ошибка импорта: {str(import_error)}',
                        'error': str(import_error),
                        'failed_at': time.time()
                    }
            
            # Запускаем импорт в отдельном потоке
            thread = threading.Thread(target=background_import, daemon=True)
            thread.start()
            
            # Сразу возвращаем ответ о начале обработки
            return jsonify({
                'success': True,
                'message': f'📤 Файл загружен! Обработка запущена в фоне. Проверьте статус через несколько минут.',
                'task_id': task_id,
                'background': True
            })
            
        except Exception as import_error:
            return jsonify({
                'success': False, 
                'error': f'Ошибка запуска импорта: {str(import_error)}'
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'Ошибка обработки файла: {str(e)}'})


@admin_bp.route('/admin/check-import-status/<task_id>')
def admin_check_import_status(task_id):
    """Проверка статуса фонового импорта"""
    try:
        global import_status
        if 'import_status' not in globals():
            import_status = {}
        
        if task_id not in import_status:
            return jsonify({
                'success': False,
                'error': 'Задача не найдена'
            })
        
        status_info = import_status[task_id]
        
        # Добавляем время обработки
        import time
        if 'started_at' in status_info:
            elapsed = time.time() - status_info['started_at']
            status_info['elapsed_time'] = f"{elapsed:.1f} сек"
        
        return jsonify({
            'success': True,
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Ошибка получения статуса: {str(e)}'
        })

# ================== REGIONAL FUNCTIONS ==================


@admin_bp.route('/admin/banners')
@admin_required
def admin_banners():
    from models import PromoBanner
    banners = PromoBanner.query.order_by(PromoBanner.sort_order, PromoBanner.created_at.desc()).all()
    return render_template('admin/banners.html', banners=banners, admin=current_user)



@admin_bp.route('/admin/partners')
@admin_required
def admin_partners():
    from models import Partner, Manager, PartnerReferral, PartnerManagerRequest
    partners = Partner.query.order_by(Partner.created_at.desc()).all()
    try:
        managers = Manager.query.filter_by(is_active=True).all()
    except Exception:
        managers = Manager.query.all()

    partners_data = []
    for p in partners:
        refs = PartnerReferral.query.filter_by(partner_id=p.id).count()
        credited = PartnerReferral.query.filter_by(partner_id=p.id, status='credited').count()
        mgr = Manager.query.get(p.assigned_manager_id) if getattr(p, 'assigned_manager_id', None) else None
        pending_req = PartnerManagerRequest.query.filter_by(
            partner_id=p.id, status='pending'
        ).order_by(PartnerManagerRequest.created_at.desc()).first()
        partners_data.append({
            'partner': p,
            'refs_total': refs,
            'refs_credited': credited,
            'manager': mgr,
            'manager_request': pending_req,
        })

    pending_requests = PartnerManagerRequest.query.filter_by(status='pending').count()

    return render_template('admin/partners.html', admin=current_user,
                           partners_data=partners_data, managers=managers,
                           pending_requests=pending_requests)


@admin_bp.route('/admin/partners/manager-request/<int:req_id>/resolve', methods=['POST'])
@admin_required
def admin_resolve_manager_request(req_id):
    from models import PartnerManagerRequest
    req = PartnerManagerRequest.query.get_or_404(req_id)
    req.status = 'resolved'
    from datetime import datetime
    req.resolved_at = datetime.utcnow()
    db.session.commit()
    flash('Запрос помечен как обработан', 'success')
    return redirect(url_for('adm.admin_partners'))



@admin_bp.route('/admin/partners/<int:partner_id>/assign-manager', methods=['POST'])
@admin_required
def admin_assign_partner_manager(partner_id):
    from models import Partner
    p = Partner.query.get_or_404(partner_id)
    manager_id = request.form.get('manager_id', '').strip()
    p.assigned_manager_id = int(manager_id) if manager_id else None
    db.session.commit()
    flash(f'Менеджер для партнёра {p.partner_id} обновлён', 'success')
    return redirect(url_for('adm.admin_partners'))



@admin_bp.route('/admin/banners/create', methods=['POST'])
@admin_required
def admin_banner_create():
    from models import PromoBanner
    from werkzeug.utils import secure_filename
    image_url = request.form.get('image_url', '')
    image_file = request.files.get('image_file')
    if image_file and image_file.filename:
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
        filename = secure_filename(image_file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in allowed_extensions:
            flash('Допустимые форматы: JPG, PNG, WebP, GIF', 'error')
            return redirect(url_for('adm.admin_banners'))
        image_file.seek(0, os.SEEK_END)
        file_size = image_file.tell()
        image_file.seek(0)
        if file_size > 5 * 1024 * 1024:
            flash('Максимальный размер файла: 5 МБ', 'error')
            return redirect(url_for('adm.admin_banners'))
        banners_dir = os.path.join('static', 'uploads', 'banners')
        os.makedirs(banners_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(banners_dir, filename)
        image_file.save(filepath)
        image_url = '/' + filepath.replace('\\', '/')
    try:
        _overlay = float(request.form.get('overlay_opacity', 0) or 0)
    except (ValueError, TypeError):
        _overlay = 0.0
    banner = PromoBanner(
        title=request.form.get('title', ''),
        subtitle=request.form.get('subtitle', ''),
        image_url=image_url,
        link_url=request.form.get('link_url', ''),
        link_text=request.form.get('link_text', 'Подробнее'),
        bg_color=request.form.get('bg_color', '#EEF2FF'),
        is_active=request.form.get('is_active') == 'on',
        sort_order=int(request.form.get('sort_order', 0)),
        placement=request.form.get('placement', 'header'),
        deadline_text=request.form.get('deadline_text', ''),
        large_text=request.form.get('large_text', ''),
        overlay_opacity=_overlay,
    )
    db.session.add(banner)
    db.session.commit()
    flash('Баннер создан', 'success')
    return redirect(url_for('adm.admin_banners'))



@admin_bp.route('/admin/banners/<int:banner_id>/toggle', methods=['POST'])
@admin_required
def admin_banner_toggle(banner_id):
    from models import PromoBanner
    banner = PromoBanner.query.get_or_404(banner_id)
    banner.is_active = not banner.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': banner.is_active})



@admin_bp.route('/admin/banners/<int:banner_id>/edit', methods=['GET'])
@admin_required
def admin_banner_edit_get(banner_id):
    return redirect(url_for('adm.admin_banners'))


@admin_bp.route('/admin/banners/<int:banner_id>/edit', methods=['POST'])
@admin_required
def admin_banner_edit(banner_id):
    from models import PromoBanner
    from werkzeug.utils import secure_filename
    banner = PromoBanner.query.get_or_404(banner_id)
    banner.title = request.form.get('title', banner.title)
    banner.subtitle = request.form.get('subtitle', banner.subtitle)
    image_file = request.files.get('image_file')
    if image_file and image_file.filename:
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
        filename = secure_filename(image_file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in allowed_extensions:
            flash('Допустимые форматы: JPG, PNG, WebP, GIF', 'error')
            return redirect(url_for('adm.admin_banners'))
        image_file.seek(0, os.SEEK_END)
        file_size = image_file.tell()
        image_file.seek(0)
        if file_size > 5 * 1024 * 1024:
            flash('Максимальный размер файла: 5 МБ', 'error')
            return redirect(url_for('adm.admin_banners'))
        banners_dir = os.path.join('static', 'uploads', 'banners')
        os.makedirs(banners_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(banners_dir, filename)
        image_file.save(filepath)
        banner.image_url = '/' + filepath.replace('\\', '/')
    else:
        banner.image_url = request.form.get('image_url', banner.image_url)
    banner.link_url = request.form.get('link_url', banner.link_url)
    banner.link_text = request.form.get('link_text', banner.link_text)
    banner.bg_color = request.form.get('bg_color', banner.bg_color)
    banner.sort_order = int(request.form.get('sort_order', banner.sort_order))
    banner.placement = request.form.get('placement', banner.placement)
    banner.deadline_text = request.form.get('deadline_text', banner.deadline_text)
    banner.large_text = request.form.get('large_text', banner.large_text)
    try:
        banner.overlay_opacity = float(request.form.get('overlay_opacity', 0) or 0)
    except (ValueError, TypeError):
        banner.overlay_opacity = 0.0
    db.session.commit()
    flash('Баннер обновлён', 'success')
    return redirect(url_for('adm.admin_banners'))



@admin_bp.route('/admin/banners/<int:banner_id>/delete', methods=['POST'])
@admin_required
def admin_banner_delete(banner_id):
    from models import PromoBanner
    banner = PromoBanner.query.get_or_404(banner_id)
    db.session.delete(banner)
    db.session.commit()
    flash('Баннер удалён', 'success')
    return redirect(url_for('adm.admin_banners'))



@admin_bp.route('/admin/reviews')
@admin_bp.route('/admin/otzyvy')
@admin_required
def admin_reviews():
    from models import ComplexReview
    status_filter = request.args.get('status', 'pending')
    query = ComplexReview.query
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    reviews = query.order_by(ComplexReview.created_at.desc()).all()
    pending_count = ComplexReview.query.filter_by(status='pending').count()
    approved_count = ComplexReview.query.filter_by(status='approved').count()
    rejected_count = ComplexReview.query.filter_by(status='rejected').count()
    return render_template('admin/reviews.html', admin=current_user, 
                         reviews=reviews, 
                         status_filter=status_filter,
                         pending_count=pending_count,
                         approved_count=approved_count,
                         rejected_count=rejected_count)



@admin_bp.route('/admin/reviews/<int:review_id>/approve', methods=['POST'])
@admin_required
def admin_approve_review(review_id):
    from models import ComplexReview
    review = ComplexReview.query.get_or_404(review_id)
    review.status = 'approved'
    review.moderated_at = datetime.utcnow()
    review.moderated_by = current_user.id
    review.admin_comment = request.form.get('admin_comment', '')
    db.session.commit()
    flash(f'Отзыв от {review.author_name} одобрен.', 'success')
    return redirect(url_for('adm.admin_reviews'))



@admin_bp.route('/admin/reviews/<int:review_id>/reject', methods=['POST'])
@admin_required
def admin_reject_review(review_id):
    from models import ComplexReview
    review = ComplexReview.query.get_or_404(review_id)
    review.status = 'rejected'
    review.moderated_at = datetime.utcnow()
    review.moderated_by = current_user.id
    review.admin_comment = request.form.get('admin_comment', '')
    db.session.commit()
    flash(f'Отзыв от {review.author_name} отклонён.', 'success')
    return redirect(url_for('adm.admin_reviews'))



@admin_bp.route('/admin/reviews/<int:review_id>/delete', methods=['POST'])
@admin_required
def admin_delete_review(review_id):
    from models import ComplexReview
    review = ComplexReview.query.get_or_404(review_id)
    db.session.delete(review)
    db.session.commit()
    flash('Отзыв удалён.', 'success')
    return redirect(url_for('adm.admin_reviews'))


# ═══════════════════════════════════════════════════════════════════════
# TELEGRAM PROMOTIONS — Admin management
# ═══════════════════════════════════════════════════════════════════════


@admin_bp.route('/admin/tg-promotions')
@admin_required
def admin_tg_promotions():
    from models import TelegramPromotion, ResidentialComplex, Developer
    filter_matched = request.args.get('matched', '')
    filter_active  = request.args.get('active', '1')
    search_q       = request.args.get('q', '').strip()
    page           = request.args.get('page', 1, type=int)

    query = TelegramPromotion.query
    if filter_active == '1':
        query = query.filter_by(is_active=True)
    elif filter_active == '0':
        query = query.filter_by(is_active=False)
    if filter_matched == '1':
        query = query.filter_by(is_matched=True)
    elif filter_matched == '0':
        query = query.filter_by(is_matched=False)
    if search_q:
        like = f'%{search_q}%'
        query = query.filter(db.or_(
            TelegramPromotion.title.ilike(like),
            TelegramPromotion.tg_thread_title.ilike(like),
            TelegramPromotion.description.ilike(like),
        ))

    promotions = query.order_by(TelegramPromotion.posted_at.desc()).paginate(page=page, per_page=30, error_out=False)

    all_complexes = ResidentialComplex.query.filter_by(is_active=True).order_by(ResidentialComplex.name).all()
    all_developers = Developer.query.order_by(Developer.name).all()

    total = TelegramPromotion.query.count()
    matched = TelegramPromotion.query.filter_by(is_matched=True).count()
    unmatched = TelegramPromotion.query.filter_by(is_matched=False).count()
    active = TelegramPromotion.query.filter_by(is_active=True).count()

    return render_template('admin/tg_promotions.html',
                           promotions=promotions,
                           all_complexes=all_complexes,
                           all_developers=all_developers,
                           stats={'total': total, 'matched': matched, 'unmatched': unmatched, 'active': active},
                           filter_matched=filter_matched,
                           filter_active=filter_active,
                           search_q=search_q)



@admin_bp.route('/admin/tg-promotions/<int:promo_id>/match', methods=['POST'])
@admin_required
def admin_tg_promo_match(promo_id):
    from models import TelegramPromotion
    promo = TelegramPromotion.query.get_or_404(promo_id)
    complex_id  = request.form.get('complex_id', type=int)
    developer_id = request.form.get('developer_id', type=int)
    if complex_id:
        promo.residential_complex_id = complex_id
        promo.is_matched = True
    if developer_id:
        promo.developer_id = developer_id
        promo.is_matched = True
    db.session.commit()
    flash('Акция привязана.', 'success')
    return redirect(request.referrer or url_for('adm.admin_tg_promotions'))



@admin_bp.route('/admin/tg-promotions/<int:promo_id>/toggle', methods=['POST'])
@admin_required
def admin_tg_promo_toggle(promo_id):
    from models import TelegramPromotion
    promo = TelegramPromotion.query.get_or_404(promo_id)
    promo.is_active = not promo.is_active
    db.session.commit()
    state = 'активирована' if promo.is_active else 'скрыта'
    flash(f'Акция {state}.', 'success')
    return redirect(request.referrer or url_for('adm.admin_tg_promotions'))



@admin_bp.route('/admin/tg-promotions/<int:promo_id>/delete', methods=['POST'])
@admin_required
def admin_tg_promo_delete(promo_id):
    from models import TelegramPromotion
    import json, os
    promo = TelegramPromotion.query.get_or_404(promo_id)
    # Удаляем скачанные фото
    try:
        for photo_path in json.loads(promo.photos or '[]'):
            abs_path = os.path.join(os.getcwd(), photo_path.lstrip('/'))
            if os.path.exists(abs_path):
                os.remove(abs_path)
    except Exception:
        pass
    db.session.delete(promo)
    db.session.commit()
    flash('Акция удалена.', 'success')
    return redirect(request.referrer or url_for('adm.admin_tg_promotions'))



@admin_bp.route('/admin/tg-promotions/<int:promo_id>/edit', methods=['POST'])
@admin_required
def admin_tg_promo_edit(promo_id):
    from models import TelegramPromotion
    promo = TelegramPromotion.query.get_or_404(promo_id)
    promo.title = request.form.get('title', promo.title)
    promo.description = request.form.get('description', promo.description)
    db.session.commit()
    flash('Акция обновлена.', 'success')
    return redirect(request.referrer or url_for('adm.admin_tg_promotions'))


# ═══════════════════════════════════════════════════════════════════════
# CHAT SYSTEM — InBack built-in chat (user ↔ manager)
# ═══════════════════════════════════════════════════════════════════════


@admin_bp.route('/admin/chat-settings', methods=['GET'])
@login_required
def admin_chat_settings():
    from models import Manager, ChatSettings, Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return redirect(url_for('adm.admin_login'))
    settings = {
        'welcome_message': ChatSettings.get('welcome_message', 'Привет! 👋 Я ваш персональный менеджер InBack. Задайте любой вопрос о недвижимости — отвечу быстро!'),
        'offline_message': ChatSettings.get('offline_message', 'Все операторы сейчас офлайн. Мы ответим в ближайшее время. Вы также можете позвонить: 8 (862) 266-62-16'),
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
        # New settings
        'chat_phone': ChatSettings.get('chat_phone', '8 (862) 266-62-16'),
        'work_hours_start': ChatSettings.get('work_hours_start', '09:00'),
        'work_hours_end': ChatSettings.get('work_hours_end', '20:00'),
        'work_days': ChatSettings.get('work_days', '1,2,3,4,5,6,7'),
        'sound_enabled': ChatSettings.get('sound_enabled', 'true'),
        'auto_open_delay': ChatSettings.get('auto_open_delay', '0'),
    }
    managers = Manager.query.filter_by(is_active=True).order_by(Manager.first_name).all()
    return render_template('admin/chat_settings.html', settings=settings, managers=managers)



@admin_bp.route('/admin/chat-settings', methods=['POST'])
@csrf.exempt
@login_required
def admin_chat_settings_save():
    from models import ChatSettings, Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        all_keys = ['welcome_message', 'offline_message', 'chat_enabled', 'response_time',
                    'proactive_message', 'trigger_delay', 'exit_intent', 'offline_form',
                    'telegram_url', 'whatsapp_url', 'vk_url', 'phone_url',
                    'chat_phone', 'work_hours_start', 'work_hours_end', 'work_days',
                    'sound_enabled', 'auto_open_delay']
        for key in all_keys:
            if key in data:
                ChatSettings.set_value(key, data[key])
        db.session.commit()
        if request.is_json:
            return jsonify({'ok': True})
        flash('Настройки чата сохранены', 'success')
        return redirect(url_for('adm.admin_chat_settings'))
    except Exception as e:
        db.session.rollback()
        logger.error(f'chat_settings_save error: {e}', exc_info=True)
        if request.is_json:
            return jsonify({'ok': False, 'error': str(e)}), 500
        flash(f'Ошибка сохранения: {e}', 'error')
        return redirect(url_for('adm.admin_chat_settings'))



@admin_bp.route('/admin/push-test', methods=['POST'])
@login_required
def admin_push_test():
    """Send a test push notification to the current admin or a specified subscription."""
    from models import PushSubscription, Admin
    from app import app
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json() or {}
    target = data.get('target', 'self')  # 'self', 'all_users', 'all_managers'
    payload = {
        'title': '🔔 Тест пуш-уведомлений InBack',
        'body': 'Уведомления работают! Вы получили это из панели администратора.',
        'icon': '/static/images/icon-192.png',
        'badge': '/static/images/badge-72.png',
        'tag': 'push-test',
        'data': {'url': '/admin/chat-settings'},
    }
    sent = 0
    failed = 0
    try:
        from pywebpush import webpush
        if target == 'all_users':
            subs = PushSubscription.query.filter_by(is_active=True).all()
        elif target == 'all_managers':
            subs = PushSubscription.query.filter(
                PushSubscription.manager_id.isnot(None), PushSubscription.is_active == True
            ).all()
        else:
            # Send to all active subscriptions for this admin session
            subs = PushSubscription.query.filter_by(is_active=True).limit(5).all()

        for sub in subs:
            try:
                webpush(
                    subscription_info={'endpoint': sub.endpoint, 'keys': {'p256dh': sub.p256dh, 'auth': sub.auth_key}},
                    data=__import__('json').dumps(payload, ensure_ascii=False),
                    vapid_private_key=current_app.config['VAPID_PRIVATE_KEY'],
                    vapid_claims=current_app.config['VAPID_CLAIMS'],
                )
                sent += 1
            except Exception as e:
                status = getattr(getattr(e, 'response', None), 'status_code', None)
                if status in (404, 410):
                    sub.is_active = False
                failed += 1
        db.session.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True, 'sent': sent, 'failed': failed, 'total': sent + failed})



@admin_bp.route('/admin/notifications-management')
@login_required
def admin_notifications_management():
    from models import Notification, User, Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return redirect(url_for('adm.admin_login'))
    recent = Notification.query.order_by(Notification.created_at.desc()).limit(50).all()
    users_count = User.query.filter_by(is_active=True).count() if hasattr(User, 'is_active') else User.query.count()
    return render_template('admin/notifications_management.html', recent=recent, users_count=users_count)


@admin_bp.route('/admin/notifications-management/send', methods=['POST'])
@csrf.exempt
@login_required
def admin_notifications_send():
    from models import Notification, User, Admin
    from app import db
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    message = (data.get('message') or '').strip()
    notif_type = data.get('type', 'info')
    target = data.get('target', 'all')
    user_id = data.get('user_id')
    if not title or not message:
        return jsonify({'error': 'Заголовок и текст обязательны'}), 400
    try:
        if target == 'user' and user_id:
            user = User.query.get(int(user_id))
            if not user:
                return jsonify({'error': 'Пользователь не найден'}), 404
            n = Notification(user_id=user.id, title=title, message=message, type=notif_type)
            db.session.add(n)
            db.session.commit()
            return jsonify({'ok': True, 'sent': 1})
        else:
            users = User.query.all()
            count = 0
            for user in users:
                n = Notification(user_id=user.id, title=title, message=message, type=notif_type)
                db.session.add(n)
                count += 1
            db.session.commit()
            return jsonify({'ok': True, 'sent': count})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/admin/push-broadcast')
@login_required
def admin_push_broadcast():
    from models import PushBroadcast, Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return redirect(url_for('adm.admin_login'))
    history = PushBroadcast.query.order_by(PushBroadcast.sent_at.desc()).limit(20).all()
    return render_template('admin/push_broadcast.html', history=history)



@admin_bp.route('/admin/push-broadcast/send', methods=['POST'])
@login_required
def admin_push_broadcast_send():
    from models import PushSubscription, PushBroadcast, Admin
    from app import app
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    data   = request.get_json() or {}
    title  = (data.get('title') or '').strip()
    body   = (data.get('body') or '').strip()
    url    = (data.get('url') or '/').strip()
    target = data.get('target', 'all')
    if not title or not body:
        return jsonify({'error': 'title and body required'}), 400

    payload = {
        'title': title, 'body': body,
        'icon': '/static/images/icon-192.png',
        'badge': '/static/images/badge-72.png',
        'tag': f'broadcast-{int(__import__("time").time())}',
        'data': {'url': url},
    }

    sent = 0
    failed = 0
    try:
        from pywebpush import webpush
        import json as _json

        if target == 'self':
            subs = PushSubscription.query.filter_by(is_active=True).limit(10).all()
        elif target == 'all_users':
            subs = PushSubscription.query.filter(
                PushSubscription.is_active == True,
                PushSubscription.user_id.isnot(None)
            ).all()
        elif target == 'all_managers':
            subs = PushSubscription.query.filter(
                PushSubscription.is_active == True,
                PushSubscription.manager_id.isnot(None)
            ).all()
        elif target == 'guests':
            subs = PushSubscription.query.filter(
                PushSubscription.is_active == True,
                PushSubscription.user_id.is_(None),
                PushSubscription.manager_id.is_(None)
            ).all()
        else:  # all
            subs = PushSubscription.query.filter_by(is_active=True).all()

        for sub in subs:
            try:
                webpush(
                    subscription_info={'endpoint': sub.endpoint, 'keys': {'p256dh': sub.p256dh, 'auth': sub.auth_key}},
                    data=_json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=current_app.config['VAPID_PRIVATE_KEY'],
                    vapid_claims=current_app.config['VAPID_CLAIMS'],
                )
                sent += 1
            except Exception as e:
                status = getattr(getattr(e, 'response', None), 'status_code', None)
                if status in (404, 410):
                    sub.is_active = False
                failed += 1

        # Save to history (skip for test sends)
        if target != 'self':
            broadcast = PushBroadcast(
                title=title, body=body, url=url, target=target,
                delivered=sent, failed=failed,
                sent_by=current_user.id
            )
            db.session.add(broadcast)

        db.session.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'ok': True, 'sent': sent, 'failed': failed})



@admin_bp.route('/admin/push-history')
@login_required
def admin_push_history():
    from models import PushBroadcast, Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return redirect(url_for('adm.admin_login'))
    history = PushBroadcast.query.order_by(PushBroadcast.sent_at.desc()).all()
    return jsonify([{
        'id': h.id, 'title': h.title, 'body': h.body, 'url': h.url,
        'target': h.target, 'delivered': h.delivered, 'failed': h.failed,
        'sent_at': h.sent_at.strftime('%d.%m.%Y %H:%M')
    } for h in history])



# ─── Search engine ping / IndexNow ───────────────────────────────────────────

@admin_bp.route('/admin/api/indexnow-ping', methods=['POST'])
@csrf.exempt
@admin_required
def admin_indexnow_ping():
    """Manually ping Google/Yandex sitemap and submit URLs via IndexNow.

    POST body (optional JSON):
        {
          "urls": ["https://inback.ru/krasnodar/zk/...", ...],
          "ping_new_complexes": true   // also collect recent RC URLs
        }
    """
    from models import Admin as _Admin
    if not (current_user.is_authenticated and
            isinstance(current_user._get_current_object(), _Admin)):
        return jsonify({'error': 'Forbidden'}), 403

    body = request.get_json(silent=True) or {}
    urls = list(body.get('urls', []))

    # Optionally auto-add recent RC URLs (created/updated in last 7 days)
    if body.get('ping_new_complexes'):
        try:
            from models import ResidentialComplex, City
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=7)
            from app import CANONICAL_BASE_URL
            cities = {c.id: c.slug for c in City.query.filter_by(is_active=True).all()}
            recent = (ResidentialComplex.query
                      .filter(ResidentialComplex.is_active == True,
                              ResidentialComplex.updated_at >= cutoff)
                      .with_entities(ResidentialComplex.slug, ResidentialComplex.city_id)
                      .limit(500).all())
            for rc in recent:
                cs = cities.get(rc.city_id)
                if cs and rc.slug:
                    urls.append(f'{CANONICAL_BASE_URL}/{cs}/zk/{rc.slug}')
        except Exception as _e:
            logger.warning(f'Could not collect recent RC URLs: {_e}')

    try:
        from routes.admin_api import ping_search_engines
        import threading as _t
        _t.Thread(target=ping_search_engines, args=(urls or None,), daemon=True).start()
        return jsonify({
            'ok': True,
            'message': f'Пинг запущен в фоне. Отправлено URL: {len(urls)}',
            'urls_count': len(urls),
            'indexnow_enabled': bool(os.environ.get('INDEXNOW_KEY')),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ─── OSM Enrichment: districts + RC building polygons ────────────────────────

_RC_POLYGON_JOB = {
    'running': False, 'done': 0, 'total': 0, 'errors': 0,
    'last_result': None, 'current_rc': None,
    'logs': []  # list of {idx, ts, msg} for live log streaming
}


@admin_bp.route('/admin/api/osm/enrich-districts', methods=['POST'])
@csrf.exempt
@login_required
def admin_osm_enrich_districts():
    """Bulk-fetch district boundaries from OSM Overpass and upsert into DB."""
    from models import Admin as _Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), _Admin)):
        return jsonify({'error': 'Forbidden'}), 403

    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', 'scripts'))
    from fetch_osm_boundaries import fetch_districts_for_city, upsert_districts, CITY_CONFIGS
    from sqlalchemy import text

    body = request.get_json(silent=True) or {}
    city_id_filter = body.get('city_id')

    results = {}
    for slug, cfg in CITY_CONFIGS.items():
        if city_id_filter and cfg['id'] != int(city_id_filter):
            continue
        try:
            districts_data = fetch_districts_for_city(slug, cfg)
            if districts_data:
                ins, upd = upsert_districts(db.session, cfg['id'], cfg['name'], districts_data, text)
                results[slug] = {'inserted': ins, 'updated': upd, 'found': len(districts_data)}
            else:
                results[slug] = {'inserted': 0, 'updated': 0, 'found': 0}
        except Exception as exc:
            current_app.logger.error(f'OSM district enrichment failed for {slug}: {exc}')
            results[slug] = {'error': str(exc)}

    total_ins = sum(r.get('inserted', 0) for r in results.values())
    total_upd = sum(r.get('updated', 0) for r in results.values())
    return jsonify({'ok': True, 'results': results,
                    'total_inserted': total_ins, 'total_updated': total_upd})


@admin_bp.route('/admin/api/osm/prefetch-rc-polygons', methods=['POST'])
@csrf.exempt
@login_required
def admin_osm_prefetch_rc_polygons():
    """Start background job to bulk-prefetch OSM building polygons for all active RCs."""
    from models import Admin as _Admin, ResidentialComplex
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), _Admin)):
        return jsonify({'error': 'Forbidden'}), 403

    if _RC_POLYGON_JOB['running']:
        return jsonify({'ok': False, 'error': 'Job already running', 'status': _RC_POLYGON_JOB})

    body = request.get_json(silent=True) or {}
    city_id_filter = body.get('city_id')

    q = ResidentialComplex.query.filter(
        ResidentialComplex.is_active == True,
        ResidentialComplex.latitude.isnot(None),
        ResidentialComplex.longitude.isnot(None),
        db.or_(ResidentialComplex.boundary_geometry == None,
               ResidentialComplex.boundary_geometry == '')
    )
    if city_id_filter:
        q = q.filter(ResidentialComplex.city_id == int(city_id_filter))

    rc_ids = [rc.id for rc in q.with_entities(ResidentialComplex.id).all()]

    if not rc_ids:
        return jsonify({'ok': True, 'message': 'All RCs already have polygon data', 'total': 0})

    import threading, time as _time_mod
    _app = current_app._get_current_object()

    def _log(msg):
        import datetime as _dt
        entry = {'idx': len(_RC_POLYGON_JOB['logs']), 'ts': _dt.datetime.utcnow().strftime('%H:%M:%S'), 'msg': msg}
        _RC_POLYGON_JOB['logs'].append(entry)
        if len(_RC_POLYGON_JOB['logs']) > 500:
            _RC_POLYGON_JOB['logs'] = _RC_POLYGON_JOB['logs'][-500:]

    def _fetch_complex_area(lat, lon, rc_name=None):
        """Try landuse=residential area first (CIAN-style), then building cluster fallback."""
        OVERPASS = 'https://overpass-api.de/api/interpreter'
        # 1st try: landuse=residential area containing the point
        area_q = (
            f'[out:json][timeout:20];'
            f'way["landuse"="residential"](around:500,{lat},{lon});'
            f'out geom;'
        )
        try:
            r = requests.post(OVERPASS, data={'data': area_q},
                              headers={'User-Agent': 'InBack-Real-Estate/1.0'}, timeout=22)
            els = [e for e in r.json().get('elements', [])
                   if e.get('geometry') and len(e['geometry']) >= 3]
            if els:
                # Pick the smallest area (most precise) that has >= 4 nodes
                els.sort(key=lambda e: len(e.get('geometry', [])))
                el = els[0]
                geom = el['geometry']
                poly = ';'.join(f"{p['lat']},{p['lon']}" for p in geom)
                return poly, 'landuse'
        except Exception:
            pass
        # 2nd fallback: building cluster within 250m (original approach)
        bld_q = (
            f'[out:json][timeout:20];'
            f'way["building"](around:250,{lat},{lon});'
            f'out geom;'
        )
        try:
            r = requests.post(OVERPASS, data={'data': bld_q},
                              headers={'User-Agent': 'InBack-Real-Estate/1.0'}, timeout=22)
            els = [e for e in r.json().get('elements', [])
                   if e.get('geometry') and len(e['geometry']) > 2]
            if els:
                els.sort(key=lambda e: len(e.get('geometry', [])), reverse=True)
                polys = [';'.join(f"{p['lat']},{p['lon']}" for p in el['geometry']) for el in els[:25]]
                return '|'.join(polys), 'buildings'
        except Exception:
            pass
        return None, None

    def _run(app_inst, ids):
        with app_inst.app_context():
            _RC_POLYGON_JOB['running'] = True
            _RC_POLYGON_JOB['total'] = len(ids)
            _RC_POLYGON_JOB['done'] = 0
            _RC_POLYGON_JOB['errors'] = 0
            _RC_POLYGON_JOB['logs'] = []
            _log(f'Запуск: {len(ids)} ЖК в очереди')
            for rc_id in ids:
                try:
                    from models import ResidentialComplex as _RC
                    rc = _RC.query.get(rc_id)
                    if not rc or rc.boundary_geometry:
                        _RC_POLYGON_JOB['done'] += 1
                        continue
                    _RC_POLYGON_JOB['current_rc'] = rc.name
                    n = _RC_POLYGON_JOB['done'] + 1
                    total = _RC_POLYGON_JOB['total']
                    _log(f'[{n}/{total}] ЖК "{rc.name}" ({rc.city_id}) — запрос OSM...')
                    geom, source = _fetch_complex_area(rc.latitude, rc.longitude, rc.name)
                    if geom:
                        rc.boundary_geometry = geom
                        db.session.commit()
                        poly_count = geom.count('|') + 1
                        _log(f'  ✓ {source}: сохранено {poly_count} полигон(ов)')
                    else:
                        _log(f'  — не найдено в OSM')
                        _RC_POLYGON_JOB['errors'] += 1
                except Exception as e:
                    _RC_POLYGON_JOB['errors'] += 1
                    _log(f'  ✗ ошибка: {e}')
                    app_inst.logger.warning(f'RC polygon prefetch rc_id={rc_id}: {e}')
                finally:
                    _RC_POLYGON_JOB['done'] += 1
                _time_mod.sleep(1.5)
            done = _RC_POLYGON_JOB['done']
            errs = _RC_POLYGON_JOB['errors']
            _log(f'Готово! Обработано: {done}, ошибок: {errs}')
            _RC_POLYGON_JOB['running'] = False
            _RC_POLYGON_JOB['current_rc'] = None
            _RC_POLYGON_JOB['last_result'] = {k: v for k, v in _RC_POLYGON_JOB.items() if k != 'logs'}

    threading.Thread(target=_run, args=(_app, rc_ids), daemon=True).start()
    return jsonify({'ok': True, 'started': True, 'total': len(rc_ids),
                    'message': f'Started background prefetch for {len(rc_ids)} RCs (~{len(rc_ids)*2//60+1} min)'})


@admin_bp.route('/admin/api/osm/prefetch-rc-polygons/status')
@login_required
def admin_osm_prefetch_rc_polygons_status():
    """Check status of the running RC polygon prefetch job."""
    from models import Admin as _Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), _Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify({'ok': True, 'status': _RC_POLYGON_JOB})


@admin_bp.route('/admin/api/osm/prefetch-rc-polygons/logs')
@login_required
def admin_osm_prefetch_rc_polygons_logs():
    """Return live log entries for the running RC polygon prefetch job (polling endpoint).
    Pass ?since=N to get only entries with idx >= N.
    """
    from models import Admin as _Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), _Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    since = request.args.get('since', default=0, type=int)
    logs = [e for e in _RC_POLYGON_JOB.get('logs', []) if e['idx'] >= since]
    return jsonify({
        'ok': True,
        'logs': logs,
        'running': _RC_POLYGON_JOB['running'],
        'done': _RC_POLYGON_JOB.get('done', 0),
        'total': _RC_POLYGON_JOB.get('total', 0),
        'errors': _RC_POLYGON_JOB.get('errors', 0),
        'current_rc': _RC_POLYGON_JOB.get('current_rc'),
    })


@admin_bp.route('/admin/osm-enrichment')
@login_required
def admin_osm_enrichment_page():
    """Admin page: OSM enrichment dashboard for districts and RC polygons."""
    from models import Admin as _Admin, ResidentialComplex, District, City
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), _Admin)):
        return redirect(url_for('adm.admin_login'))

    cities = City.query.order_by(City.id).all()
    stats = []
    for city in cities:
        rc_total = ResidentialComplex.query.filter_by(city_id=city.id, is_active=True).count()
        rc_poly = ResidentialComplex.query.filter(
            ResidentialComplex.city_id == city.id,
            ResidentialComplex.is_active == True,
            ResidentialComplex.boundary_geometry.isnot(None),
            ResidentialComplex.boundary_geometry != ''
        ).count()
        dist_total = District.query.filter_by(city_id=city.id).count()
        dist_geo = District.query.filter(
            District.city_id == city.id,
            District.geometry.isnot(None),
            District.geometry != ''
        ).count()
        stats.append({
            'city': city,
            'rc_total': rc_total, 'rc_poly': rc_poly,
            'dist_total': dist_total, 'dist_geo': dist_geo,
        })

    return render_template('admin/osm_enrichment.html',
                           admin=current_user, stats=stats, job=_RC_POLYGON_JOB)


@admin_bp.route('/admin/chat-settings/operator/<int:mgr_id>/toggle', methods=['POST'])
@csrf.exempt
@login_required
def admin_chat_operator_toggle(mgr_id):
    """Toggle chat_accept flag for a manager (grant/revoke operator rights)."""
    from models import Manager, Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    mgr = Manager.query.get_or_404(mgr_id)
    mgr.chat_accept = not mgr.chat_accept
    # If revoking, also mark offline
    if not mgr.chat_accept:
        mgr.is_online = False
    db.session.commit()
    return jsonify({'ok': True, 'chat_accept': mgr.chat_accept, 'manager_id': mgr_id})


@admin_bp.route('/admin/api/toggle-image-proxy', methods=['POST'])
@csrf.exempt
@login_required
def admin_toggle_image_proxy():
    """Toggle image proxy on/off. State saved in DB (ChatSettings) + synced to /tmp cache."""
    from models import Admin, ChatSettings
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    flag_file = '/tmp/image_proxy_disabled'
    # Текущее состояние определяем по /tmp (быстро) или по DB
    currently_enabled = not os.path.exists(flag_file)
    enabled = not currently_enabled  # переключаем
    # Сохраняем в DB
    try:
        ChatSettings.set_value('image_proxy_enabled', '1' if enabled else '0')
        db.session.commit()
    except Exception:
        db.session.rollback()
    # Синхронизируем /tmp кэш
    if enabled:
        if os.path.exists(flag_file):
            os.remove(flag_file)
    else:
        open(flag_file, 'w').close()
    # Сбрасываем in-memory кэш карты ЖК — он хранит URL изображений,
    # которые могли быть проксированы. Следующий запрос перестроит его с актуальными URL.
    try:
        from routes.public_api import _complexes_map_cache, _complexes_map_cache_ts
        _complexes_map_cache.clear()
        _complexes_map_cache_ts.clear()
    except Exception:
        pass
    return jsonify({'ok': True, 'image_proxy_enabled': enabled})


@admin_bp.route('/admin/api/image-proxy-status')
@login_required
def admin_image_proxy_status():
    """Return current image proxy enabled/disabled status (from DB, with /tmp fallback)."""
    from models import Admin, ChatSettings
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        val = ChatSettings.get('image_proxy_enabled', '1')
        enabled = (val != '0')
    except Exception:
        enabled = not os.path.exists('/tmp/image_proxy_disabled')
    return jsonify({'image_proxy_enabled': enabled})


@admin_bp.route('/admin/api/proxy-stats')
@login_required
def admin_proxy_stats():
    """Return live image proxy request counters (resets on server restart)."""
    from models import Admin
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Admin)):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        from routes.api import _PROXY_STATS, _IMG_CACHE, _IMG_DISK_DIR
        import os as _os
        # Disk cache file count
        disk_files = 0
        try:
            for root, dirs, files in _os.walk(_IMG_DISK_DIR):
                disk_files += len(files)
        except Exception:
            pass
        stats = dict(_PROXY_STATS)
        stats['mem_cached'] = len(_IMG_CACHE)
        stats['disk_cached'] = disk_files
        total = stats['total'] or 1
        stats['cache_hit_rate'] = round((stats['mem_hits'] + stats['disk_hits']) / total * 100, 1)
        return jsonify({'ok': True, 'stats': stats})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@admin_bp.route('/admin/api/sync-photos', methods=['POST'])
@admin_required
def admin_api_sync_photos():
    """
    Двусторонняя синхронизация фото между ЖК и квартирами.

    POST body (JSON):
      direction  : 'props_to_rc' | 'rc_to_props' | 'both'  (default: 'both')
      complex_id : int | None   — синхронизировать только один ЖК (опционально)
      overwrite  : bool         — перезаписывать существующие фото  (default: False)
    """
    from models import ResidentialComplex, Property
    from app import db

    data = {}
    try:
        import flask
        data = flask.request.get_json(silent=True) or {}
    except Exception:
        pass

    direction  = data.get('direction', 'both')
    complex_id = data.get('complex_id')
    overwrite  = bool(data.get('overwrite', False))

    stats = {
        'rc_updated':   0,   # ЖК получили фото из квартир
        'prop_updated': 0,   # Квартиры получили фото из ЖК
        'skipped':      0,
        'errors':       0,
    }

    def _parse_gallery(raw):
        if not raw:
            return []
        if isinstance(raw, list):
            return raw
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else []
        except Exception:
            return []

    def _save_gallery(imgs):
        return json.dumps(imgs, ensure_ascii=False) if imgs else None

    try:
        # ── Базовый запрос ЖК ────────────────────────────────────────────
        rc_q = ResidentialComplex.query
        if complex_id:
            rc_q = rc_q.filter(ResidentialComplex.id == int(complex_id))

        complexes = rc_q.all()

        for rc in complexes:
            try:
                # ── 1. КВАРТИРЫ → ЖК ─────────────────────────────────────
                if direction in ('props_to_rc', 'both'):
                    needs_main  = not rc.main_image or overwrite
                    needs_gallery = not rc.gallery_images or overwrite

                    if needs_main or needs_gallery:
                        # Собираем квартиры с фото
                        props_with_img = [
                            p for p in rc.properties
                            if p.main_image or p.gallery_images
                        ]

                        if props_with_img:
                            # Первый main_image из любой квартиры
                            if needs_main:
                                for p in props_with_img:
                                    if p.main_image:
                                        rc.main_image = p.main_image
                                        break

                            # Объединяем все галереи квартир → в галерею ЖК
                            if needs_gallery:
                                merged = []
                                seen = set()
                                for p in props_with_img:
                                    for url in ([p.main_image] if p.main_image else []) + _parse_gallery(p.gallery_images):
                                        if url and url not in seen:
                                            merged.append(url)
                                            seen.add(url)
                                if merged:
                                    rc.gallery_images = _save_gallery(merged[:50])  # до 50 фото

                            stats['rc_updated'] += 1
                        else:
                            stats['skipped'] += 1

                # ── 2. ЖК → КВАРТИРЫ ─────────────────────────────────────
                if direction in ('rc_to_props', 'both'):
                    if rc.main_image or rc.gallery_images:
                        rc_gallery = _parse_gallery(rc.gallery_images)
                        rc_imgs = ([rc.main_image] if rc.main_image else []) + rc_gallery

                        for prop in rc.properties:
                            needs_main    = (not prop.main_image) or overwrite
                            needs_gallery = (not prop.gallery_images) or overwrite

                            if not (needs_main or needs_gallery):
                                continue

                            updated = False
                            if needs_main and rc.main_image:
                                prop.main_image = rc.main_image
                                updated = True
                            if needs_gallery and rc_imgs:
                                prop.gallery_images = _save_gallery(rc_imgs[:20])
                                updated = True

                            if updated:
                                stats['prop_updated'] += 1

            except Exception as e:
                logger.error(f'sync-photos error for RC {rc.id}: {e}')
                stats['errors'] += 1

        db.session.commit()
        return jsonify({'ok': True, 'stats': stats})

    except Exception as e:
        db.session.rollback()
        logger.error(f'sync-photos fatal: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@admin_bp.route('/admin/deduplication')
@admin_required
def admin_deduplication():
    from models import Admin
    admin = Admin.query.filter_by(id=session.get('admin_id')).first()
    return render_template('admin/deduplication.html', admin=admin)


# ══════════════════════════════════════════════════════════════════
# TRENDAGENT IMPORT MANAGEMENT
# ══════════════════════════════════════════════════════════════════

import threading as _ta_threading
import sys as _ta_sys

_TA_JOB = {
    'running': False,
    'thread': None,
    'logs': [],
    'started_at': None,
    'finished_at': None,
    'city_slug': None,
    'options': {},
    'stats': {},
}
_TA_JOB_LOCK = _ta_threading.Lock()
_TA_MAX_LOGS = 3000


class _TAJobLogHandler(logging.Handler):
    """Перехватывает лог trendagent_import и складывает в _TA_JOB['logs']."""
    def __init__(self, job_logs, lock):
        super().__init__()
        self._jl  = job_logs
        self._lk  = lock
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S'))

    def emit(self, record):
        try:
            msg = self.format(record)
            with self._lk:
                self._jl.append(msg)
                if len(self._jl) > _TA_MAX_LOGS:
                    del self._jl[0:200]
        except Exception:
            pass


def _run_ta_import_thread(city_slug, options, flask_app):
    """Background thread: запускает import_city из trendagent_import.py."""
    import importlib
    import importlib.util
    import traceback as _tb

    def _log(msg):
        ts = datetime.utcnow().strftime('%H:%M:%S')
        with _TA_JOB_LOCK:
            _TA_JOB['logs'].append(f"{ts} {msg}")

    try:
        with flask_app.app_context():
            _log(f"INFO 🚀 Запуск импорта TrendAgent: город={city_slug}")
            _log(f"INFO ⚙️  Опции: {options}")

            phone    = os.environ.get('TRENDAGENT_PHONE', '').strip()
            password = os.environ.get('TRENDAGENT_PASSWORD', '').strip()
            if not phone or not password:
                _log("ERROR ❌ Не заданы TRENDAGENT_PHONE / TRENDAGENT_PASSWORD в Secrets")
                return

            # Загружаем модуль
            _script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        '..', 'scripts', 'trendagent_import.py')
            _script_path = os.path.normpath(_script_path)
            spec = importlib.util.spec_from_file_location("_ta_imp", _script_path)
            ta = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ta)

            # Перехватываем логи модуля
            _ta_logger = logging.getLogger('_ta_imp')
            _root_log  = logging.getLogger()
            _handler   = _TAJobLogHandler(_TA_JOB['logs'], _TA_JOB_LOCK)
            _ta_logger.addHandler(_handler)
            _ta_logger.setLevel(logging.DEBUG)
            _root_log.addHandler(_handler)

            # Авторизация
            client = ta.TrendagentClient(phone, password)
            if not client.login():
                _log("ERROR ❌ Ошибка авторизации TrendAgent — проверьте TRENDAGENT_PHONE / TRENDAGENT_PASSWORD")
                return
            _log("INFO ✅ Авторизация успешна")

            # Запуск импорта
            block_id = options.get('block_id') or None
            if block_id:
                _log(f"INFO 🏠 Режим: импорт конкретного ЖК (block_id={block_id})")
            ta.import_city(
                client=client,
                city_slug=city_slug,
                limit=options.get('limit', 0),
                import_apartments=options.get('import_apartments', False),
                delete_summaries=options.get('delete_summaries', False),
                geo_filter=options.get('geo_filter', True) if not block_id else False,
                specific_block_id=block_id,
            )
            _log("INFO ✅ Импорт завершён успешно")

            # Снимаем хэндлер
            try:
                _ta_logger.removeHandler(_handler)
                _root_log.removeHandler(_handler)
            except Exception:
                pass

    except Exception as _e:
        _log(f"ERROR ❌ Критическая ошибка: {_e}")
        _log(_tb.format_exc())
    finally:
        with _TA_JOB_LOCK:
            _TA_JOB['running']     = False
            _TA_JOB['finished_at'] = datetime.utcnow().isoformat()


_TA_SUPPORTED_SLUGS = frozenset({
    'krasnodar', 'sochi', 'novorossiysk', 'anapa', 'gelendzhik', 'maykop',
})


@admin_bp.route('/admin/trendagent-import', methods=['GET'])
@admin_required
def admin_trendagent_import():
    """Страница управления импортом TrendAgent."""
    from models import Admin, City, ResidentialComplex, Property
    admin = Admin.query.get(session.get('admin_id'))
    cities = City.query.order_by(City.name).all()
    city_stats = []
    for c in cities:
        supported = c.slug in _TA_SUPPORTED_SLUGS
        rc_count = ResidentialComplex.query.filter_by(city_id=c.id, is_active=True).count()
        apt_count = Property.query.filter(
            Property.city_id == c.id,
            Property.external_id.like('ta_apt_%'),
            Property.is_active == True,
        ).count() if supported else 0
        sum_count = Property.query.filter(
            Property.city_id == c.id,
            Property.external_id.like('ta_bld_%'),
            Property.is_active == True,
        ).count() if supported else 0
        city_stats.append({
            'city': c, 'rc_count': rc_count,
            'apt_count': apt_count, 'sum_count': sum_count,
            'supported': supported,
        })

    # Supported cities first for selector
    supported_stats = [cs for cs in city_stats if cs['supported']]

    with _TA_JOB_LOCK:
        job_snap = {
            'running':     _TA_JOB['running'],
            'city_slug':   _TA_JOB['city_slug'],
            'started_at':  _TA_JOB['started_at'],
            'finished_at': _TA_JOB['finished_at'],
            'log_count':   len(_TA_JOB['logs']),
            'recent_logs': list(_TA_JOB['logs'][-60:]),
        }

    return render_template(
        'admin/trendagent_import.html',
        admin=admin,
        city_stats=city_stats,
        supported_stats=supported_stats,
        job=job_snap,
        ta_phone_set=bool(os.environ.get('TRENDAGENT_PHONE')),
        ta_pass_set=bool(os.environ.get('TRENDAGENT_PASSWORD')),
    )


@admin_bp.route('/admin/api/trendagent/start', methods=['POST'])
@csrf.exempt
@admin_required
def admin_ta_start():
    """Запуск фонового импорта TrendAgent."""
    from flask import current_app
    with _TA_JOB_LOCK:
        if _TA_JOB['running']:
            return jsonify({'ok': False, 'error': 'Импорт уже выполняется'}), 409

    data      = request.get_json(force=True, silent=True) or {}
    city_slug = (data.get('city_slug') or '').strip()
    if not city_slug:
        return jsonify({'ok': False, 'error': 'Укажите город (city_slug)'}), 400

    raw_block = (data.get('block_id') or '').strip()
    import re as _re
    # Извлекаем block_id из URL TrendAgent вида: https://krasnodar.trendagent.ru/object/619f7c88d625d0b5aa7d3c61
    if raw_block and '/' in raw_block:
        _m = _re.search(r'/object/([a-f0-9]{24})', raw_block, _re.IGNORECASE)
        if _m:
            raw_block = _m.group(1)
        else:
            raw_block = raw_block.split('/')[-1].strip()

    options = {
        'limit':             int(data.get('limit', 0) or 0),
        'import_apartments': bool(data.get('import_apartments', False)),
        'delete_summaries':  bool(data.get('delete_summaries', False)),
        'geo_filter':        bool(data.get('geo_filter', True)),
        'block_id':          raw_block or None,
    }

    flask_app = current_app._get_current_object()

    with _TA_JOB_LOCK:
        _TA_JOB['running']     = True
        _TA_JOB['logs']        = []
        _TA_JOB['started_at']  = datetime.utcnow().isoformat()
        _TA_JOB['finished_at'] = None
        _TA_JOB['city_slug']   = city_slug
        _TA_JOB['options']     = options

    t = _ta_threading.Thread(
        target=_run_ta_import_thread,
        args=(city_slug, options, flask_app),
        daemon=True,
        name=f'ta_import_{city_slug}',
    )
    with _TA_JOB_LOCK:
        _TA_JOB['thread'] = t
    t.start()

    return jsonify({'ok': True, 'message': f'Импорт города «{city_slug}» запущен'})


@admin_bp.route('/admin/api/trendagent/status')
@admin_required
def admin_ta_status():
    """Статус текущего или последнего импорта + новые лог-строки (polling)."""
    offset = max(0, int(request.args.get('offset', 0)))
    with _TA_JOB_LOCK:
        all_logs  = list(_TA_JOB['logs'])
        new_logs  = all_logs[offset:]
        snap = {
            'running':          _TA_JOB['running'],
            'city_slug':        _TA_JOB['city_slug'],
            'started_at':       _TA_JOB['started_at'],
            'finished_at':      _TA_JOB['finished_at'],
            'total_log_lines':  len(all_logs),
            'new_logs':         new_logs,
            'new_offset':       len(all_logs),
        }
    return jsonify(snap)


@admin_bp.route('/admin/api/trendagent/stop', methods=['POST'])
@csrf.exempt
@admin_required
def admin_ta_stop():
    """Помечает задание как остановленное (поток завершит текущий ЖК)."""
    with _TA_JOB_LOCK:
        if not _TA_JOB['running']:
            return jsonify({'ok': False, 'error': 'Нет активного импорта'}), 400
        ts = datetime.utcnow().strftime('%H:%M:%S')
        _TA_JOB['logs'].append(f"{ts} WARN ⚠️  Остановка запрошена администратором — завершаем текущий ЖК...")
        _TA_JOB['running']     = False
        _TA_JOB['finished_at'] = datetime.utcnow().isoformat()
    return jsonify({'ok': True})


@admin_bp.route('/admin/api/trendagent/recalc-cashback', methods=['POST'])
@csrf.exempt
@admin_required
def admin_ta_recalc_cashback():
    """Пересчитывает cashback_rate для всех ЖК с ta_reward_label (мин(агент%) × 40%)."""
    import re as _re
    from models import ResidentialComplex

    rcs = ResidentialComplex.query.filter(
        ResidentialComplex.ta_reward_label.isnot(None),
        ResidentialComplex.ta_reward_label != '',
    ).all()

    updated = 0
    skipped = 0
    results = []

    for rc in rcs:
        label = (rc.ta_reward_label or '').strip()
        nums = [float(x) for x in _re.findall(r'\d+(?:\.\d+)?', label)]
        if not nums:
            skipped += 1
            continue
        agent_pct = min(nums)
        inback_pct = round(max(1.0, min(10.0, agent_pct * 0.40)), 2)
        old_cb = float(rc.cashback_rate) if rc.cashback_rate is not None else None
        rc.cashback_rate = inback_pct
        updated += 1
        results.append({
            'id':    rc.id,
            'name':  rc.name,
            'label': label,
            'old':   old_cb,
            'new':   inback_pct,
        })

    db.session.commit()

    return jsonify({
        'ok':      True,
        'updated': updated,
        'skipped': skipped,
        'results': results,
    })
