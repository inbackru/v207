"""
Admin API Blueprint — JSON API endpoints for admin operations.
Routes: /api/admin/complex-stats, price-analytics, offer/add, material/add,
        /careers, /security, /api/dashboard/bootstrap, /api/balance,
        /api/withdrawals, /api/admin/balance/*, /api/admin/withdrawals/*,
        /api/admin/users-with-balance, /api/admin/search-users
"""
import json
import logging
import os
from datetime import datetime

_ROOT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR  = os.path.join(_ROOT_DIR, 'scripts')
_SESSIONS_DIR = os.path.join(_ROOT_DIR, 'sessions')

from flask import Blueprint, jsonify, request, current_app, send_file, render_template, redirect, url_for, session
from flask_login import current_user, login_required

from app import db, csrf, invalidate_complexes_cache
from seo_redirects import redirect_to_city_based

logger = logging.getLogger(__name__)

admin_api_bp = Blueprint('admin_api', __name__)

from app import admin_required

@admin_api_bp.route('/api/admin/complex-stats')
@admin_required
def api_admin_complex_stats():
    from models import PriceHistory, ResidentialComplex, Property
    from sqlalchemy import func
    try:
        complexes_data = db.session.query(
            ResidentialComplex.id,
            ResidentialComplex.name,
            ResidentialComplex.city_id,
            func.count(Property.id).label('cnt'),
            func.avg(Property.price).label('avg_p'),
            func.avg(Property.price_per_sqm).label('avg_psm'),
            func.min(Property.price).label('min_p'),
            func.max(Property.price).label('max_p')
        ).join(Property, Property.complex_id == ResidentialComplex.id).filter(
            Property.price.isnot(None), Property.price > 0
        ).group_by(ResidentialComplex.id, ResidentialComplex.name, ResidentialComplex.city_id).order_by(
            func.count(Property.id).desc()
        ).all()

        from models import City
        cities = {c.id: c.name for c in City.query.all()}

        result = []
        total_props = 0
        total_price_sum = 0
        total_psm_sum = 0
        price_count = 0

        for c in complexes_data:
            latest_history = PriceHistory.query.filter_by(
                complex_id=c.id, record_type='complex'
            ).order_by(PriceHistory.year.desc(), PriceHistory.month.desc()).first()

            price_change = None
            if latest_history and latest_history.price_change_percent is not None:
                price_change = latest_history.price_change_percent

            result.append({
                'id': c.id,
                'name': c.name,
                'city': cities.get(c.city_id, ''),
                'properties_count': c.cnt,
                'avg_price': int(c.avg_p) if c.avg_p else None,
                'avg_psm': int(c.avg_psm) if c.avg_psm else None,
                'min_price': int(c.min_p) if c.min_p else None,
                'max_price': int(c.max_p) if c.max_p else None,
                'price_change': price_change
            })
            total_props += c.cnt
            if c.avg_p:
                total_price_sum += float(c.avg_p)
                price_count += 1
            if c.avg_psm:
                total_psm_sum += float(c.avg_psm)

        overall_avg = int(total_price_sum / price_count) if price_count > 0 else None
        overall_psm = int(total_psm_sum / price_count) if price_count > 0 else None

        return jsonify({
            'success': True,
            'total_complexes': len(result),
            'total_properties': total_props,
            'overall_avg_price': overall_avg,
            'overall_avg_psm': overall_psm,
            'complexes': result
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/api/admin/run-price-snapshot', methods=['POST'])
@csrf.exempt
@admin_required
def api_admin_run_price_snapshot():
    try:
        run_record_price_history()
        from models import PriceHistory
        from sqlalchemy import func
        total = PriceHistory.query.count()
        latest = db.session.query(
            func.max(PriceHistory.recorded_at)
        ).scalar()
        return jsonify({
            'success': True,
            'message': 'Обход цен завершён',
            'total_records': total,
            'last_recorded': latest.strftime('%d.%m.%Y %H:%M') if latest else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/api/admin/price-analytics')
@admin_required
def api_admin_price_analytics():
    from models import PriceHistory, ResidentialComplex, City
    from sqlalchemy import func
    try:
        all_records = PriceHistory.query.filter_by(record_type='complex').order_by(
            PriceHistory.year.asc(), PriceHistory.month.asc()
        ).all()

        months_set = sorted(set((r.year, r.month) for r in all_records))
        if not months_set:
            return jsonify({
                'success': True, 'labels': [], 'datasets': [], 
                'market_avg_prices': [], 'market_avg_psm': [],
                'stats': {'total_records': PriceHistory.query.count(), 'unique_months': 0, 'complexes_tracked': 0, 'last_recorded': None}
            })

        month_names = {1:'янв',2:'фев',3:'мар',4:'апр',5:'май',6:'июн',7:'июл',8:'авг',9:'сен',10:'окт',11:'ноя',12:'дек'}
        labels = [f"{month_names[m]} {y}" for y, m in months_set]

        complexes = {c.id: c for c in ResidentialComplex.query.all()}
        cities = {c.id: c.name for c in City.query.all()}

        records_by_complex = {}
        for r in all_records:
            if r.complex_id:
                records_by_complex.setdefault(r.complex_id, {})[( r.year, r.month)] = r

        complex_ids_with_data = sorted(records_by_complex.keys())
        datasets = []
        for cid in complex_ids_with_data:
            rc = complexes.get(cid)
            if not rc:
                continue
            records_map = records_by_complex[cid]
            prices = []
            psm_values = []
            for ym in months_set:
                rec = records_map.get(ym)
                prices.append(int(rec.avg_price) if rec and rec.avg_price else None)
                psm_values.append(int(rec.avg_price_per_sqm) if rec and rec.avg_price_per_sqm else None)

            latest_rec = records_map.get(months_set[-1])
            prop_count = latest_rec.properties_count if latest_rec and latest_rec.properties_count else None

            datasets.append({
                'id': cid,
                'name': rc.name,
                'city': cities.get(rc.city_id, ''),
                'avg_prices': prices,
                'avg_psm': psm_values,
                'latest_avg': prices[-1] if prices else None,
                'latest_psm': psm_values[-1] if psm_values else None,
                'properties_count': prop_count,
            })

        records_by_month = {}
        for r in all_records:
            if r.avg_price:
                records_by_month.setdefault((r.year, r.month), []).append(r)

        market_avg_prices = []
        market_avg_psm = []
        for ym in months_set:
            month_recs = records_by_month.get(ym, [])
            if month_recs:
                total_weighted = sum(r.avg_price * (r.properties_count or 1) for r in month_recs)
                total_count = sum(r.properties_count or 1 for r in month_recs)
                market_avg_prices.append(int(total_weighted / total_count))
                psm_recs = [r for r in month_recs if r.avg_price_per_sqm]
                if psm_recs:
                    total_w_psm = sum(r.avg_price_per_sqm * (r.properties_count or 1) for r in psm_recs)
                    total_c_psm = sum(r.properties_count or 1 for r in psm_recs)
                    market_avg_psm.append(int(total_w_psm / total_c_psm))
                else:
                    market_avg_psm.append(None)
            else:
                market_avg_prices.append(None)
                market_avg_psm.append(None)

        total_records = PriceHistory.query.count()
        last_recorded = db.session.query(func.max(PriceHistory.recorded_at)).scalar()
        unique_months = len(months_set)

        return jsonify({
            'success': True,
            'labels': labels,
            'datasets': datasets,
            'market_avg_prices': market_avg_prices,
            'market_avg_psm': market_avg_psm,
            'stats': {
                'total_records': total_records,
                'unique_months': unique_months,
                'complexes_tracked': len(complex_ids_with_data),
                'last_recorded': last_recorded.strftime('%d.%m.%Y %H:%M') if last_recorded else None
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/api/admin/complex/<int:complex_id>/offer/add', methods=['POST'])
@csrf.exempt
@admin_required
def api_admin_add_offer(complex_id):
    """
    API endpoint for adding offers from residential complex detail page.
    
    Accepts:
        - title (required): Offer title
        - description (optional): Offer description
        - sort_order (optional): Sort order (default 0)
        - image (required): Image file (max 5MB, jpg/jpeg/png/webp)
    
    Returns:
        JSON: {"success": True/False, "message"/"error": str}
    """
    from models import ResidentialComplex, Offer
    from werkzeug.utils import secure_filename
    import os
    from datetime import datetime
    
    try:
        # Check if complex exists
        complex = ResidentialComplex.query.get(complex_id)
        if not complex:
            return jsonify({'success': False, 'error': 'Жилой комплекс не найден'}), 404
        
        # Get form data
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        sort_order = request.form.get('sort_order', '0')
        
        # Validate title (required)
        if not title:
            return jsonify({'success': False, 'error': 'Название акции обязательно'}), 400
        
        # Validate and parse sort_order
        try:
            sort_order = int(sort_order)
        except (ValueError, TypeError):
            sort_order = 0
        
        # Validate image file (required)
        image_file = request.files.get('image')
        if not image_file or image_file.filename == '':
            return jsonify({'success': False, 'error': 'Изображение обязательно'}), 400
        
        # Validate file size (max 5MB)
        image_file.seek(0, os.SEEK_END)
        file_size = image_file.tell()
        image_file.seek(0)
        
        max_size = 5 * 1024 * 1024  # 5MB in bytes
        if file_size > max_size:
            return jsonify({'success': False, 'error': 'Размер файла превышает 5 МБ'}), 400
        
        # Validate file type
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        filename = secure_filename(image_file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            return jsonify({'success': False, 'error': 'Неподдерживаемый формат изображения. Используйте JPG, JPEG, PNG или WEBP'}), 400
        
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        
        # Save file to static/uploads/offers/
        upload_folder = 'static/uploads/offers'
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, unique_filename)
        image_file.save(file_path)
        
        # Store relative path in database (with leading slash)
        image_url = f'/static/uploads/offers/{unique_filename}'
        
        # Create offer record
        offer = Offer(
            residential_complex_id=complex_id,
            title=title,
            description=description if description else None,
            image_url=image_url,
            is_active=True,  # Set active by default
            sort_order=sort_order
        )
        
        db.session.add(offer)
        db.session.commit()
        invalidate_complexes_cache()
        
        return jsonify({
            'success': True,
            'message': 'Акция успешно добавлена',
            'offer': {
                'id': offer.id,
                'title': offer.title,
                'description': offer.description,
                'image_url': offer.image_url,
                'is_active': offer.is_active,
                'sort_order': offer.sort_order
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        # Log the error for debugging
        print(f"Error creating offer: {str(e)}")
        return jsonify({'success': False, 'error': f'Ошибка при создании акции: {str(e)}'}), 500

@admin_api_bp.route('/api/admin/complex/<int:complex_id>/material/add', methods=['POST'])
@csrf.exempt
@admin_required
def api_admin_add_material(complex_id):
    """API endpoint for adding marketing materials from residential complex detail page."""
    from models import ResidentialComplex, MarketingMaterial
    from werkzeug.utils import secure_filename
    import os
    from datetime import datetime
    
    try:
        # 1. Check if complex exists
        complex = ResidentialComplex.query.get(complex_id)
        if not complex:
            return jsonify({'success': False, 'error': 'Жилой комплекс не найден'}), 404
        
        # 2. Get and validate form data
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        material_type = request.form.get('material_type', '').strip()
        sort_order = request.form.get('sort_order', '0')
        
        # Validate title (required)
        if not title:
            return jsonify({'success': False, 'error': 'Название материала обязательно'}), 400
        
        # 3. Validate material_type
        allowed_material_types = ["Буклет", "Фото", "Рендер", "Другое"]
        if not material_type or material_type not in allowed_material_types:
            return jsonify({'success': False, 'error': f'Тип материала должен быть одним из: {", ".join(allowed_material_types)}'}), 400
        
        # Validate and parse sort_order
        try:
            sort_order = int(sort_order)
        except (ValueError, TypeError):
            sort_order = 0
        
        # 4. Get and validate file (required)
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'error': 'Файл обязателен'}), 400
        
        # 6. Validate file extension
        allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.webp'}
        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            return jsonify({'success': False, 'error': 'Неподдерживаемый формат файла. Используйте PDF, JPG, JPEG, PNG или WEBP'}), 400
        
        # Auto-detect file_type from extension
        if file_ext == '.pdf':
            file_type = 'pdf'
            max_size = 10 * 1024 * 1024  # 10MB
        else:
            file_type = 'image'
            max_size = 5 * 1024 * 1024  # 5MB
        
        # 5. Check file size based on type
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > max_size:
            max_size_mb = max_size / (1024 * 1024)
            return jsonify({'success': False, 'error': f'Размер файла превышает {max_size_mb:.0f} МБ'}), 400
        
        # 7. Generate unique filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        
        # 8. Save to static/uploads/marketing_materials/
        upload_folder = 'static/uploads/marketing_materials'
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        # Store relative path in database (with leading slash)
        file_url = f'/static/uploads/marketing_materials/{unique_filename}'
        
        # 9. Create MarketingMaterial record
        material = MarketingMaterial(
            residential_complex_id=complex_id,
            title=title,
            description=description if description else None,
            file_url=file_url,
            file_type=file_type,
            material_type=material_type,
            is_active=True,
            sort_order=sort_order
        )
        
        db.session.add(material)
        db.session.commit()
        invalidate_complexes_cache()
        
        # 10. Return JSON success response
        return jsonify({
            'success': True,
            'message': 'Материал успешно добавлен',
            'material': {
                'id': material.id,
                'title': material.title,
                'file_url': material.file_url,
                'file_type': material.file_type,
                'material_type': material.material_type
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        # Log the error for debugging
        print(f"Error creating marketing material: {str(e)}")
        return jsonify({'success': False, 'error': f'Ошибка при создании материала: {str(e)}'}), 500



def validate_image_file(file):
    """
    Validate uploaded image file for security.
    Returns (is_valid, error_message, file_extension)
    """
    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
    ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
    
    if not file or not file.filename:
        return False, 'Файл не выбран', None
    
    # Check file extension
    import os
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in ALLOWED_EXTENSIONS:
        return False, f'Недопустимый формат файла. Разрешены только: JPG, PNG, WebP', None
    
    # Verify MIME type by reading file header
    file.seek(0)
    header = file.read(12)
    file.seek(0)
    
    # Check magic bytes for common image formats
    is_valid_mime = False
    detected_type = None
    
    # JPEG: FF D8 FF
    if header[:3] == b'\xff\xd8\xff':
        is_valid_mime = True
        detected_type = 'image/jpeg'
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    elif header[:8] == b'\x89\x50\x4e\x47\x0d\x0a\x1a\x0a':
        is_valid_mime = True
        detected_type = 'image/png'
    # WebP: RIFF....WEBP
    elif header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        is_valid_mime = True
        detected_type = 'image/webp'
    
    if not is_valid_mime:
        return False, 'Файл не является допустимым изображением. Возможна попытка загрузки вредоносного файла.', None
    
    # Verify extension matches detected type
    if file_ext in ['.jpg', '.jpeg'] and detected_type != 'image/jpeg':
        return False, 'Расширение файла не соответствует содержимому', None
    if file_ext == '.png' and detected_type != 'image/png':
        return False, 'Расширение файла не соответствует содержимому', None
    if file_ext == '.webp' and detected_type != 'image/webp':
        return False, 'Расширение файла не соответствует содержимому', None
    
    return True, None, file_ext

# Admin Manager Management Routes  


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


@admin_api_bp.route('/careers', endpoint='careers')
def careers():
    """Careers page with dynamic data"""
    from models import Job, JobCategory, Admin
    
    try:
        # Check if current user is admin
        is_admin = False
        current_admin = None
        if 'admin_id' in session:
            admin_id = session.get('admin_id')
            current_admin = Admin.query.get(admin_id)
            is_admin = current_admin is not None
        
        # Get all active job categories
        categories = JobCategory.query.filter_by(is_active=True).order_by(JobCategory.sort_order).all()
        
        # Get all active jobs with their categories (excluding paused jobs)
        jobs = Job.query.filter(Job.is_active == True, Job.status == 'active').order_by(Job.is_featured.desc(), Job.created_at.desc()).all()
        
        return render_template('careers.html', 
                             categories=categories, 
                             jobs=jobs,
                             is_admin=is_admin,
                             admin=current_admin)
        
    except Exception as e:
        print(f"Error loading careers page: {e}")
        # Fallback to static page if database fails
        return render_template('careers.html', 
                             categories=[], 
                             jobs=[],
                             is_admin=False,
                             admin=None)

@admin_api_bp.route('/security', endpoint='security')
def security():
    """Redirect to city-based URL"""
    return redirect_to_city_based('security_city')





# Initialize logger for scheduler
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ============= APScheduler Configuration =============
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

# Настройка московского часового пояса для планировщика
moscow_tz = pytz.timezone('Europe/Moscow')
scheduler = BackgroundScheduler(daemon=True, timezone=moscow_tz)

def run_instant_alerts():
    """Background job: Check for new properties and send instant alerts every 5 minutes"""
    with app.app_context():
        try:
            logger.info("🔔 Running instant alerts check...")
            sent_count = AlertService.send_instant_alerts()
            logger.info(f"✅ Instant alerts job completed: {sent_count} alerts sent")
        except Exception as e:
            logger.error(f"❌ Error in instant alerts job: {e}", exc_info=True)

def run_daily_digest():
    """Background job: Send daily digest at 8:00 AM"""
    with app.app_context():
        try:
            logger.info("📧 Running daily digest job...")
            sent_count = AlertService.send_daily_digest()
            logger.info(f"✅ Daily digest job completed: {sent_count} digests sent")
        except Exception as e:
            logger.error(f"❌ Error in daily digest job: {e}", exc_info=True)

def run_weekly_digest():
    """Background job: Send weekly digest every Monday at 8:00 AM"""
    with app.app_context():
        try:
            logger.info("📆 Running weekly digest job...")
            sent_count = AlertService.send_weekly_digest()
            logger.info(f"✅ Weekly digest job completed: {sent_count} digests sent")
        except Exception as e:
            logger.error(f"❌ Error in weekly digest job: {e}", exc_info=True)

def run_task_reminders():
    """Background job: Check for tasks due in 30 minutes and create notifications"""
    with app.app_context():
        try:
            from models import DealTask, Deal, ManagerNotification
            from datetime import datetime, timedelta
            import json
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo
            
            now = datetime.now(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
            reminder_window_start = now + timedelta(minutes=25)
            reminder_window_end = now + timedelta(minutes=35)
            
            upcoming_tasks = DealTask.query.filter(
                DealTask.is_completed == False,
                DealTask.due_date != None,
                DealTask.due_date >= reminder_window_start,
                DealTask.due_date <= reminder_window_end
            ).all()
            
            created_count = 0
            for task in upcoming_tasks:
                deal = Deal.query.get(task.deal_id)
                if not deal:
                    continue
                existing = ManagerNotification.query.filter_by(
                    manager_id=deal.manager_id,
                    notification_type='task_reminder'
                ).filter(
                    db.or_(
                        ManagerNotification.extra_data.like(f'%"task_id": {task.id},%'),
                        ManagerNotification.extra_data.like(f'%"task_id": {task.id}}}%')
                    ),
                    ManagerNotification.created_at >= now - timedelta(hours=2)
                ).first()
                if existing:
                    continue
                    
                minutes_left = int((task.due_date - now).total_seconds() / 60)
                notif = ManagerNotification(
                    manager_id=deal.manager_id,
                    title=f'⏰ Напоминание: {task.title}',
                    message=f'Задача по сделке {deal.deal_number} через ~{minutes_left} мин. Приоритет: {task.priority_label}',
                    notification_type='task_reminder',
                    presentation_id=None,
                    extra_data=json.dumps({'task_id': task.id, 'deal_id': deal.id, 'deal_number': deal.deal_number}, ensure_ascii=False)
                )
                db.session.add(notif)
                created_count += 1
                
                try:
                    from models import Manager
                    from email_service import send_manager_notification
                    mgr = Manager.query.get(deal.manager_id)
                    if mgr:
                        tg_msg = f"⏰ *Напоминание о задаче*\n\n📋 {task.title}\n📁 Сделка: #{deal.deal_number}\n⏱ Через ~{minutes_left} мин.\n📊 Приоритет: {task.priority_label}"
                        send_manager_notification(mgr, 'task_reminder', tg_msg)
                        # Push notification for task reminder
                        try:
                            from push_service import _send_one
                            from models import PushSubscription
                            import json as _json
                            if mgr.notify_task_reminders:
                                mgr_subs = PushSubscription.query.filter(
                                    PushSubscription.manager_id == mgr.id,
                                    PushSubscription.is_active == True
                                ).all()
                                push_payload = {
                                    'title': f'⏰ Задача через ~{minutes_left} мин.',
                                    'body': f'{task.title} — Сделка #{deal.deal_number}',
                                    'icon': '/static/images/icon-192.png',
                                    'badge': '/static/images/badge-72.png',
                                    'tag': f'task-{task.id}',
                                    'data': {'url': f'/manager/deals/{deal.id}'},
                                }
                                for sub in mgr_subs:
                                    _send_one(sub, push_payload)
                        except Exception as push_err:
                            logger.error(f"Push task reminder error: {push_err}")
                except Exception as tg_err:
                    logger.error(f"Error sending task reminder TG: {tg_err}")
            
            if created_count > 0:
                db.session.commit()
                logger.info(f"🔔 Task reminders: {created_count} notifications created")
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Error in task reminders job: {e}", exc_info=True)

def run_overdue_task_alerts():
    """Background job: Check for overdue tasks and create notifications"""
    with app.app_context():
        try:
            from models import DealTask, Deal, ManagerNotification
            from datetime import datetime, timedelta
            import json
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo
            
            now = datetime.now(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
            
            overdue_tasks = DealTask.query.filter(
                DealTask.is_completed == False,
                DealTask.due_date != None,
                DealTask.due_date < now
            ).all()
            
            created_count = 0
            for task in overdue_tasks:
                deal = Deal.query.get(task.deal_id)
                if not deal:
                    continue
                existing = ManagerNotification.query.filter_by(
                    manager_id=deal.manager_id,
                    notification_type='task_overdue'
                ).filter(
                    db.or_(
                        ManagerNotification.extra_data.like(f'%"task_id": {task.id},%'),
                        ManagerNotification.extra_data.like(f'%"task_id": {task.id}}}%')
                    ),
                    ManagerNotification.created_at >= now - timedelta(hours=24)
                ).first()
                if existing:
                    continue
                
                overdue_minutes = int((now - task.due_date).total_seconds() / 60)
                if overdue_minutes < 60:
                    overdue_text = f'{overdue_minutes} мин.'
                elif overdue_minutes < 1440:
                    overdue_text = f'{overdue_minutes // 60} ч.'
                else:
                    overdue_text = f'{overdue_minutes // 1440} дн.'
                    
                notif = ManagerNotification(
                    manager_id=deal.manager_id,
                    title=f'🔴 Просрочена: {task.title}',
                    message=f'Задача по сделке {deal.deal_number} просрочена на {overdue_text}. Приоритет: {task.priority_label}',
                    notification_type='task_overdue',
                    presentation_id=None,
                    extra_data=json.dumps({'task_id': task.id, 'deal_id': deal.id, 'deal_number': deal.deal_number}, ensure_ascii=False)
                )
                db.session.add(notif)
                created_count += 1
                
                try:
                    from models import Manager
                    from email_service import send_manager_notification
                    mgr = Manager.query.get(deal.manager_id)
                    if mgr:
                        tg_msg = f"🔴 *Просроченная задача*\n\n📋 {task.title}\n📁 Сделка: #{deal.deal_number}\n⏱ Просрочено на {overdue_text}\n📊 Приоритет: {task.priority_label}"
                        send_manager_notification(mgr, 'overdue_task', tg_msg)
                        try:
                            from push_service import _send_one
                            from models import PushSubscription
                            if mgr.notify_overdue_tasks:
                                mgr_subs = PushSubscription.query.filter(
                                    PushSubscription.manager_id == mgr.id,
                                    PushSubscription.is_active == True
                                ).all()
                                push_payload = {
                                    'title': f'🔴 Просроченная задача!',
                                    'body': f'{task.title} — Сделка #{deal.deal_number} (просрочено {overdue_text})',
                                    'icon': '/static/images/icon-192.png',
                                    'badge': '/static/images/badge-72.png',
                                    'tag': f'overdue-{task.id}',
                                    'data': {'url': f'/manager/deals/{deal.id}'},
                                }
                                for sub in mgr_subs:
                                    _send_one(sub, push_payload)
                        except Exception as push_err:
                            logger.error(f"Push overdue task error: {push_err}")
                except Exception as tg_err:
                    logger.error(f"Error sending overdue task TG: {tg_err}")
            
            if created_count > 0:
                db.session.commit()
                logger.info(f"🔴 Overdue task alerts: {created_count} notifications created")
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Error in overdue task alerts job: {e}", exc_info=True)

def run_record_price_history():
    with app.app_context():
        try:
            from models import PriceHistory, ResidentialComplex, Property
            from datetime import datetime
            from sqlalchemy import func

            now = datetime.utcnow()
            current_month = now.month
            current_year = now.year

            logger.info("📊 Recording monthly price history snapshots...")

            complexes = ResidentialComplex.query.all()
            complex_count = 0
            for rc in complexes:
                existing = PriceHistory.query.filter_by(
                    complex_id=rc.id,
                    record_type='complex',
                    month=current_month,
                    year=current_year
                ).first()
                if existing:
                    continue

                stats = db.session.query(
                    func.avg(Property.price).label('avg_price'),
                    func.avg(Property.price_per_sqm).label('avg_psm'),
                    func.min(Property.price).label('min_price'),
                    func.max(Property.price).label('max_price'),
                    func.count(Property.id).label('cnt')
                ).filter(
                    Property.complex_id == rc.id,
                    Property.price.isnot(None),
                    Property.price > 0
                ).first()

                if not stats or not stats.cnt:
                    continue

                prev = PriceHistory.query.filter_by(
                    complex_id=rc.id,
                    record_type='complex'
                ).order_by(PriceHistory.year.desc(), PriceHistory.month.desc()).first()

                change_pct = None
                if prev and prev.avg_price and int(stats.avg_price) > 0 and prev.avg_price > 0:
                    change_pct = round((int(stats.avg_price) - prev.avg_price) / prev.avg_price * 100, 1)

                record = PriceHistory(
                    complex_id=rc.id,
                    record_type='complex',
                    avg_price=int(stats.avg_price),
                    avg_price_per_sqm=int(stats.avg_psm) if stats.avg_psm else None,
                    min_price=int(stats.min_price),
                    max_price=int(stats.max_price),
                    properties_count=stats.cnt,
                    price_change_percent=change_pct,
                    month=current_month,
                    year=current_year,
                    recorded_at=now
                )
                db.session.add(record)
                complex_count += 1

            properties = Property.query.filter(
                Property.price.isnot(None),
                Property.price > 0
            ).all()
            prop_count = 0
            for prop in properties:
                existing = PriceHistory.query.filter_by(
                    property_id=prop.id,
                    record_type='property',
                    month=current_month,
                    year=current_year
                ).first()
                if existing:
                    continue

                prev = PriceHistory.query.filter_by(
                    property_id=prop.id,
                    record_type='property'
                ).order_by(PriceHistory.year.desc(), PriceHistory.month.desc()).first()

                change_pct = None
                if prev and prev.price and prop.price and prev.price > 0:
                    change_pct = round((prop.price - prev.price) / prev.price * 100, 1)

                record = PriceHistory(
                    property_id=prop.id,
                    complex_id=prop.complex_id,
                    record_type='property',
                    price=prop.price,
                    price_per_sqm=prop.price_per_sqm,
                    price_change_percent=change_pct,
                    month=current_month,
                    year=current_year,
                    recorded_at=now
                )
                db.session.add(record)
                prop_count += 1

            db.session.commit()
            logger.info(f"✅ Price history recorded: {complex_count} complexes, {prop_count} properties")
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Error recording price history: {e}", exc_info=True)


def run_auto_geocode():
    """Background job: geocode complexes/properties missing coordinates (every 2 hours)."""
    with app.app_context():
        try:
            from models import ResidentialComplex, Property
            from services.parser_import_service import ParserImportService

            yandex_key = os.environ.get('YANDEX_MAPS_API_KEY') or os.environ.get('YANDEX_API_KEY')
            if not yandex_key:
                logger.info("⏭️  Auto-geocode skipped: YANDEX_MAPS_API_KEY not set")
                return

            complexes = ResidentialComplex.query.filter(
                ResidentialComplex.address.isnot(None),
                ResidentialComplex.latitude.is_(None)
            ).limit(50).all()

            geocoded = 0
            for rc in complexes:
                city_name = rc.city.name if rc.city else 'Краснодар'
                lat, lon = ParserImportService._geocode_address(rc.address, city_name)
                if lat and lon:
                    rc.latitude = lat
                    rc.longitude = lon
                    geocoded += 1

            if geocoded:
                db.session.commit()
                logger.info(f"✅ Auto-geocode: {geocoded} complexes geocoded")
            else:
                logger.info("✅ Auto-geocode: nothing to do")
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Auto-geocode error: {e}", exc_info=True)


def run_enrichment_job():
    """Weekly job: re-enrich all JK/developer data from CIAN (runs as subprocess)."""
    import subprocess, os
    script = os.path.join(_SCRIPTS_DIR, 'enrich_complexes.py')
    if not os.path.exists(script):
        logger.warning('⚠️  enrich_complexes.py not found, skipping')
        return
    # Reset phase 1 so the job fetches fresh data from CIAN
    cache_file = os.path.join(_SCRIPTS_DIR, '.enrich_cache.json')
    try:
        import json as _json
        if os.path.exists(cache_file):
            with open(cache_file) as f:
                c = _json.load(f)
            c['phase'] = 1
            with open(cache_file, 'w') as f:
                _json.dump(c, f)
    except Exception:
        pass
    # Load settings for env vars
    try:
        _enrich_s = _load_enrich_settings()
        _enrich_env = {**os.environ,
            'ENRICH_TOTAL_PAGES': str(_enrich_s.get('total_pages', 15)),
            'ENRICH_REGION_ID':   str(_enrich_s.get('cian_region_id', 4820)),
            'ENRICH_CITY_ID':     str(_enrich_s.get('city_id', 1)),
            'ENRICH_CREATE_NEW':  '1' if _enrich_s.get('create_new_jk', True) else '0',
            'ENRICH_DELAY':       str(_enrich_s.get('request_delay', 0.5)),
            'ENRICH_PROXY':       str(_enrich_s.get('proxy_url', '')),
        }
    except Exception:
        _enrich_env = os.environ.copy()
    logger.info('🏗️  Starting weekly CIAN enrichment job...')
    enrichment_ok = False
    enrich_added = enrich_updated = 0
    # Используем Popen + log file вместо subprocess.run(capture_output=True)
    # чтобы не накапливать весь stdout в RAM (45k квартир = сотни МБ вывода)
    _sched_log = os.path.join(_SCRIPTS_DIR, '.enrich_scheduled.log')
    try:
        import re as _re
        with open(_sched_log, 'w') as _lf:
            proc = subprocess.Popen(
                ['python3', script],
                env=_enrich_env,
                stdout=_lf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        # Ждём завершения (до 30 мин), проверяя каждые 30 сек
        import time as _time_mod
        deadline = _time_mod.time() + 1800
        returncode = None
        while _time_mod.time() < deadline:
            rc = proc.poll()
            if rc is not None:
                returncode = rc
                break
            _time_mod.sleep(30)
        else:
            proc.kill()
            logger.warning('⚠️  Enrichment job timed out after 30 minutes')
            _send_enrich_report_tg(0, 0, 0, 0, mode='full', error='Timeout после 30 минут')
            return
        # Читаем хвост лога для парсинга итогов
        try:
            with open(_sched_log, 'r', errors='replace') as _lf:
                stdout_text = _lf.read()
        except Exception:
            stdout_text = ''
        lines = stdout_text.strip().split('\n')
        summary = next((l for l in reversed(lines) if 'Готово' in l or 'Обновлено' in l), lines[-1] if lines else '')
        _added_m   = _re.search(r'новых[:\s]*(\d+)', stdout_text)
        _updated_m = _re.search(r'обновл[а-яё\.]*[:\s]*(\d+)', stdout_text)
        enrich_added   = int(_added_m.group(1))   if _added_m   else 0
        enrich_updated = int(_updated_m.group(1)) if _updated_m else 0
        if returncode == 0:
            logger.info(f'✅ Enrichment completed: {summary}')
            enrichment_ok = True
        else:
            logger.warning(f'⚠️  Enrichment finished with errors (rc={returncode}): {lines[-1] if lines else ""}')
            _send_enrich_report_tg(enrich_added, enrich_updated, 0, 0,
                                   mode='full', error=lines[-1][:200] if lines else '')
    except Exception as e:
        logger.warning(f'⚠️  Enrichment job error: {e}')

    if enrichment_ok:
        logger.info('🧹 Running post-enrichment cleanup (vanished + stale properties)...')
        vanished_n, vanished_err = run_cleanup_vanished_properties()
        stale_n, stale_err = run_deactivate_stale_properties()
        total_cleaned = vanished_n + stale_n
        logger.info(
            f'🧹 Авто-очистка завершена: '
            f'пропавших с ЦИАН → {vanished_n}, '
            f'устаревших (60+ дней) → {stale_n}. '
            f'Итого деактивировано: {total_cleaned}'
        )
        if vanished_err:
            logger.warning(f'⚠️  Vanished cleanup had errors: {vanished_err}')
        if stale_err:
            logger.warning(f'⚠️  Stale cleanup had errors: {stale_err}')
        # Send Telegram report
        _send_enrich_report_tg(enrich_added, enrich_updated, vanished_n, stale_n, mode='full')


def ping_search_engines(urls=None):
    """Ping Google/Yandex sitemap + submit URLs via IndexNow.

    Args:
        urls: list of absolute URL strings to submit (optional).
              When None, only pings sitemaps.
    """
    import urllib.request
    import urllib.parse as _up
    import json as _j

    base_url = 'https://inback.ru'
    sitemap_url = f'{base_url}/sitemap.xml'

    # 1. Sitemap ping (Google + Yandex)
    for ping_url in [
        f'https://www.google.com/ping?sitemap={_up.quote(sitemap_url, safe="")}',
        f'https://webmaster.yandex.ru/ping?sitemap={_up.quote(sitemap_url, safe="")}',
    ]:
        try:
            with urllib.request.urlopen(ping_url, timeout=10) as r:
                logger.info(f"🗺️  Sitemap ping OK → {ping_url.split('/')[2]} ({r.status})")
        except Exception as e:
            logger.warning(f"⚠️  Sitemap ping failed → {ping_url.split('/')[2]}: {e}")

    # 2. IndexNow (Bing, Yandex, Seznam, …) — requires INDEXNOW_KEY env var
    indexnow_key = os.environ.get('INDEXNOW_KEY', '')
    if indexnow_key and urls:
        # Batch to max 10,000 per request
        for i in range(0, len(urls), 10000):
            batch = urls[i:i + 10000]
            payload = {
                'host': 'inback.ru',
                'key': indexnow_key,
                'keyLocation': f'{base_url}/{indexnow_key}.txt',
                'urlList': batch,
            }
            body = _j.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                'https://api.indexnow.org/indexnow',
                data=body,
                headers={'Content-Type': 'application/json; charset=utf-8'},
                method='POST',
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    logger.info(f"⚡ IndexNow submitted {len(batch)} URLs → status {r.status}")
            except Exception as e:
                logger.warning(f"⚠️  IndexNow submission failed: {e}")
    elif indexnow_key and not urls:
        # Ping sitemap via IndexNow too
        ping_url = (f'https://api.indexnow.org/indexnow'
                    f'?url={_up.quote(sitemap_url, safe="")}'
                    f'&key={indexnow_key}')
        try:
            with urllib.request.urlopen(ping_url, timeout=10) as r:
                logger.info(f"⚡ IndexNow sitemap ping OK → {r.status}")
        except Exception as e:
            logger.warning(f"⚠️  IndexNow sitemap ping failed: {e}")


def run_sitemap_ping():
    """Ping Google and Yandex with our sitemap URL once a day (scheduler wrapper)."""
    ping_search_engines()


# Schedule background jobs
# Instant alerts: every 5 minutes
scheduler.add_job(
    func=run_instant_alerts,
    trigger=IntervalTrigger(minutes=5),
    id='instant_alerts_job',
    name='Проверка новых объектов и отправка мгновенных оповещений',
    replace_existing=True
)

# Daily digest: every day at 8:00 AM
scheduler.add_job(
    func=run_daily_digest,
    trigger=CronTrigger(hour=8, minute=0),
    id='daily_digest_job',
    name='Ежедневная сводка по объектам',
    replace_existing=True
)

# Weekly digest: every Monday at 8:00 AM
scheduler.add_job(
    func=run_weekly_digest,
    trigger=CronTrigger(day_of_week='mon', hour=8, minute=0),
    id='weekly_digest_job',
    name='Еженедельная сводка по объектам',
    replace_existing=True
)

# Task reminders: every 5 minutes
scheduler.add_job(
    func=run_task_reminders,
    trigger=IntervalTrigger(minutes=5),
    id='task_reminders_job',
    name='Напоминания о предстоящих задачах',
    replace_existing=True
)

# Overdue task alerts: every 10 minutes
scheduler.add_job(
    func=run_overdue_task_alerts,
    trigger=IntervalTrigger(minutes=10),
    id='overdue_task_alerts_job',
    name='Оповещения о просроченных задачах',
    replace_existing=True
)

# Price history: 1st day of each month at 3:00 AM
scheduler.add_job(
    func=run_record_price_history,
    trigger=CronTrigger(day=1, hour=3, minute=0),
    id='price_history_job',
    name='Запись истории цен (ежемесячно)',
    replace_existing=True
)

# Auto-geocode: every 2 hours — geocode complexes/properties without coordinates
scheduler.add_job(
    func=run_auto_geocode,
    trigger=IntervalTrigger(hours=2),
    id='auto_geocode_job',
    name='Автогеокодинг объектов без координат',
    replace_existing=True
)

# Sitemap ping: daily at 06:00
scheduler.add_job(
    func=run_sitemap_ping,
    trigger=CronTrigger(hour=6, minute=0),
    id='sitemap_ping_job',
    name='Пинг Google/Яндекс о новом sitemap',
    replace_existing=True
)

# CIAN enrichment: every Sunday at 02:00 — updates JK/developer data
scheduler.add_job(
    func=run_enrichment_job,
    trigger=CronTrigger(day_of_week='sun', hour=2, minute=0),
    id='cian_enrichment_job',
    name='Обогащение данных ЖК с CIAN (еженедельно)',
    replace_existing=True
)

def run_daily_price_update():
    """Daily job: fast price-only CIAN update (~5 min). Skips JK/dev scraping."""
    import subprocess, os as _os
    script = os.path.join(_SCRIPTS_DIR, 'enrich_complexes.py')
    if not _os.path.exists(script):
        logger.warning('⚠️  enrich_complexes.py not found, skipping price update')
        return
    try:
        _enrich_s = _load_enrich_settings()
        _env = {**_os.environ,
            'ENRICH_MODE':        'prices',
            'ENRICH_TOTAL_PAGES': str(_enrich_s.get('total_pages', 15)),
            'ENRICH_REGION_ID':   str(_enrich_s.get('cian_region_id', 4820)),
            'ENRICH_CITY_ID':     str(_enrich_s.get('city_id', 1)),
            'ENRICH_DELAY':       str(_enrich_s.get('request_delay', 0.5)),
            'ENRICH_PROXY':       str(_enrich_s.get('proxy_url', '')),
        }
    except Exception:
        _env = {**_os.environ, 'ENRICH_MODE': 'prices'}
    logger.info('⚡ Starting daily CIAN price update (prices mode)...')
    try:
        result = subprocess.run(
            ['python3', script],
            env=_env, capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            lines = (result.stdout or '').strip().split('\n')
            summary = next((l for l in reversed(lines) if 'Цены обновлены' in l or 'новых' in l), '')
            logger.info(f'✅ Daily price update completed: {summary}')
        else:
            logger.warning(f'⚠️  Daily price update errors: {result.stderr[-300:]}')
    except subprocess.TimeoutExpired:
        logger.warning('⚠️  Daily price update timed out after 10 minutes')
    except Exception as e:
        logger.warning(f'⚠️  Daily price update error: {e}')

# Daily CIAN price update: every day Mon-Sat at 06:00 (full enrichment runs Sunday at 02:00)
scheduler.add_job(
    func=run_daily_price_update,
    trigger=CronTrigger(day_of_week='mon-sat', hour=6, minute=0),
    id='cian_daily_price_job',
    name='Ежедневное обновление цен ЦИАН (Пн-Сб 06:00)',
    replace_existing=True
)

def run_update_complex_distances():
    """Recalculate distance_to_center for all ResidentialComplex with coordinates."""
    import math as _math
    try:
        from models import ResidentialComplex as _RC, City as _City
        cities = {c.id: c for c in _City.query.filter(
            _City.latitude.isnot(None), _City.longitude.isnot(None), _City.is_active == True
        ).all()}
        complexes = _RC.query.filter(
            _RC.latitude.isnot(None), _RC.longitude.isnot(None)
        ).all()
        updated = 0
        for c in complexes:
            city = cities.get(c.city_id)
            if not city:
                continue
            R = 6371.0
            phi1, phi2 = _math.radians(c.latitude), _math.radians(city.latitude)
            dphi = _math.radians(city.latitude - c.latitude)
            dlam = _math.radians(city.longitude - c.longitude)
            a = _math.sin(dphi/2)**2 + _math.cos(phi1)*_math.cos(phi2)*_math.sin(dlam/2)**2
            dist = round(2 * R * _math.asin(_math.sqrt(a)), 1)
            if c.distance_to_center != dist:
                c.distance_to_center = dist
                updated += 1
        if updated:
            db.session.commit()
        logger.info(f'✅ Complex distances updated: {updated} records')
    except Exception as e:
        logger.warning(f'⚠️  Complex distance update error: {e}')

# Complex distances: every day at 07:00 — after geocoding (02:00 geocode → 07:00 distances)
scheduler.add_job(
    func=run_update_complex_distances,
    trigger=CronTrigger(hour=7, minute=0),
    id='complex_distances_job',
    name='Расстояния ЖК до центра города (ежедневно 07:00)',
    replace_existing=True
)

def run_infrastructure_update_job():
    """Scheduled wrapper for infrastructure update."""
    import subprocess, os as _os
    script = os.path.join(_SCRIPTS_DIR, 'auto_infrastructure_update.py')
    if not _os.path.exists(script):
        logger.warning('⚠️  auto_infrastructure_update.py not found, skipping')
        return
    try:
        result = subprocess.run(['python3', script], capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            logger.info('✅ Infrastructure update completed')
        else:
            logger.warning(f'⚠️  Infrastructure update errors: {result.stderr[-300:]}')
    except subprocess.TimeoutExpired:
        logger.warning('⚠️  Infrastructure update timed out')
    except Exception as e:
        logger.warning(f'⚠️  Infrastructure update error: {e}')

# Infrastructure update: every Monday at 04:00
scheduler.add_job(
    func=run_infrastructure_update_job,
    trigger=CronTrigger(day_of_week='mon', hour=4, minute=0),
    id='infrastructure_update_job',
    name='Обновление инфраструктуры районов (еженедельно пн 04:00)',
    replace_existing=True
)


def run_update_complex_nearby():
    """Scheduled wrapper: refresh nearby POI for all complexes via Overpass API."""
    import subprocess, os as _os
    script = os.path.join(_SCRIPTS_DIR, 'update_complex_nearby.py')
    if not _os.path.exists(script):
        logger.warning('⚠️  update_complex_nearby.py not found, skipping')
        return
    try:
        result = subprocess.run(
            ['python3', '-u', script],
            capture_output=True, text=True, timeout=7200
        )
        if result.returncode == 0:
            logger.info('✅ Complex nearby POI update completed')
        else:
            logger.warning(f'⚠️  Nearby update errors: {result.stderr[-300:]}')
    except subprocess.TimeoutExpired:
        logger.warning('⚠️  Nearby update timed out (2h limit)')
    except Exception as e:
        logger.warning(f'⚠️  Nearby update error: {e}')


# Nearby POI update: every Wednesday at 03:00
scheduler.add_job(
    func=run_update_complex_nearby,
    trigger=CronTrigger(day_of_week='wed', hour=3, minute=0),
    id='complex_nearby_job',
    name='Обновление POI (инфраструктура ЖК, еженедельно ср 03:00)',
    replace_existing=True
)


def run_db_backup():
    """Scheduled wrapper: daily PostgreSQL backup to backups/ directory."""
    try:
        import subprocess as _sp
        import sys as _sys
        _script = os.path.join(_SCRIPTS_DIR, 'backup_db.py')
        result = _sp.run(
            [_sys.executable, _script],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            logger.info('✅ DB backup completed')
        else:
            logger.warning(f'⚠️  DB backup failed: {result.stderr[-300:]}')
    except Exception as e:
        logger.warning(f'⚠️  DB backup error: {e}')


# Daily DB backup at 02:00 Moscow time
scheduler.add_job(
    func=run_db_backup,
    trigger=CronTrigger(hour=2, minute=0),
    id='db_backup_job',
    name='Ежедневный бекап БД (02:00 МСК)',
    replace_existing=True
)


def run_tg_promo_parser():
    """Scheduled wrapper: parse Telegram group for developer hot deals."""
    import subprocess, os as _os
    script = os.path.join(_SCRIPTS_DIR, 'telegram_promo_parser.py')
    if not _os.path.exists(script):
        logger.warning('⚠️  telegram_promo_parser.py not found, skipping')
        return
    if not _os.environ.get('TELEGRAM_API_ID') or not _os.environ.get('TELEGRAM_API_HASH'):
        logger.warning('⚠️  TELEGRAM_API_ID/HASH not set, skipping TG promo parsing')
        return
    session_file = os.path.join(_SESSIONS_DIR, 'promo_parser.session')
    if not _os.path.exists(session_file):
        logger.warning('⚠️  Telegram session not found (run telegram_auth_setup.py first), skipping')
        return
    try:
        result = subprocess.run(
            ['python3', '-u', script],
            capture_output=True, text=True, timeout=3600,
            env={**_os.environ}
        )
        if result.returncode == 0:
            logger.info('✅ Telegram promo parser completed')
        else:
            logger.warning(f'⚠️  TG promo parser errors: {result.stderr[-500:]}')
    except subprocess.TimeoutExpired:
        logger.warning('⚠️  TG promo parser timed out (1h limit)')
    except Exception as e:
        logger.warning(f'⚠️  TG promo parser error: {e}')


def run_cleanup_vanished_properties():
    """Scheduled wrapper: mark properties no longer on CIAN as inactive.
    Returns (deactivated_count, error_message_or_None).
    """
    import subprocess, os as _os, re as _re
    script = os.path.join(_SCRIPTS_DIR, 'cleanup_vanished_properties.py')
    if not _os.path.exists(script):
        logger.warning('⚠️  cleanup_vanished_properties.py not found, skipping')
        return 0, 'script not found'
    try:
        result = subprocess.run(
            ['python3', '-u', script, '--all-cities'],
            capture_output=True, text=True, timeout=1800,
            env={**_os.environ}
        )
        output = (result.stdout or '') + (result.stderr or '')
        # Parse all "деактивировано N объектов" lines and sum them
        counts = [int(m) for m in _re.findall(r'деактивировано\s+(\d+)\s+объект', output)]
        total = sum(counts)
        if result.returncode == 0:
            logger.info(f'✅ Cleanup vanished properties: деактивировано {total} объектов')
            return total, None
        else:
            logger.warning(f'⚠️  Cleanup vanished errors: {result.stderr[-300:]}')
            return total, result.stderr[-300:]
    except Exception as e:
        logger.warning(f'⚠️  Cleanup vanished error: {e}')
        return 0, str(e)


def run_deactivate_stale_properties():
    """Scheduled wrapper: deactivate properties not updated in 60+ days (no inner_id).
    Returns (deactivated_count, error_message_or_None).
    """
    import subprocess, os as _os, re as _re
    script = os.path.join(_ROOT_DIR, 'deactivate_stale_properties.py')
    if not _os.path.exists(script):
        logger.warning('⚠️  deactivate_stale_properties.py not found, skipping')
        return 0, 'script not found'
    try:
        result = subprocess.run(
            ['python3', '-u', script, '--days', '60'],
            capture_output=True, text=True, timeout=300,
            env={**_os.environ}
        )
        output = (result.stdout or '') + (result.stderr or '')
        # Parse "Деактивировано N объявлений"
        m = _re.search(r'Деактивировано\s+(\d+)\s+объявлен', output)
        total = int(m.group(1)) if m else 0
        if result.returncode == 0:
            logger.info(f'✅ Deactivate stale properties: деактивировано {total} устаревших объявлений')
            return total, None
        else:
            logger.warning(f'⚠️  Deactivate stale errors: {result.stderr[-300:]}')
            return total, result.stderr[-300:]
    except Exception as e:
        logger.warning(f'⚠️  Deactivate stale error: {e}')
        return 0, str(e)


# Telegram promo parser: every day at 07:00
scheduler.add_job(
    func=run_tg_promo_parser,
    trigger=CronTrigger(hour=7, minute=0),
    id='tg_promo_parser_job',
    name='Парсинг акций из Telegram-группы (ежедневно 07:00)',
    replace_existing=True
)

# Cleanup vanished properties: every day at 05:00
scheduler.add_job(
    func=run_cleanup_vanished_properties,
    trigger=CronTrigger(hour=5, minute=0),
    id='cleanup_vanished_job',
    name='Очистка пропавших объектов ЦИАН (ежедневно 05:00)',
    replace_existing=True
)

# Deactivate stale properties (no inner_id, not updated >60 days): daily at 04:30
scheduler.add_job(
    func=run_deactivate_stale_properties,
    trigger=CronTrigger(hour=4, minute=30),
    id='deactivate_stale_job',
    name='Деактивация устаревших объявлений (ежедневно 04:30)',
    replace_existing=True
)

def run_assign_district_ids():
    """Background job: point-in-polygon district + street assignment for all active cities"""
    with app.app_context():
        try:
            logger.info("🏘️  Running district/street assignment job for all active cities...")
            import sys, os as _os
            script_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'scripts')
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            from assign_district_ids import assign_districts, assign_streets
            from models import City
            active_cities = City.query.filter_by(is_active=True).all()
            total_d = total_s = 0
            for city in active_cities:
                try:
                    count = assign_districts(city_id=city.id, batch_size=500, only_unlinked=True)
                    total_d += count
                    logger.info(f"🏘️  City {city.name} (id={city.id}): {count} properties linked to districts")
                    count_s = assign_streets(city_id=city.id, batch_size=500, only_unlinked=True)
                    total_s += count_s
                    logger.info(f"✅  City {city.name} (id={city.id}): {count_s} properties linked to streets")
                except Exception as ce:
                    logger.warning(f"⚠️ City {city.name} (id={city.id}) district assignment skipped: {ce}")
            logger.info(f"✅ District/street assignment done: {total_d} districts, {total_s} streets linked")
        except Exception as e:
            logger.error(f"❌ Error in district/street assignment job: {e}", exc_info=True)


# District assignment: every 6 hours — link newly geocoded properties to districts
scheduler.add_job(
    func=run_assign_district_ids,
    trigger=IntervalTrigger(hours=6),
    id='assign_district_ids_job',
    name='Привязка объектов к районам (point-in-polygon, каждые 6 часов)',
    replace_existing=True
)


def run_fetch_osm_boundaries():
    """Refresh OSM district/street boundaries for all 8 cities (weekly)."""
    import subprocess
    try:
        logger.info("🌍 Starting OSM boundary refresh for all cities...")
        result = subprocess.run(
            ['python', 'scripts/fetch_osm_boundaries.py', '--all', '--validate'],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            logger.info("✅ OSM boundary refresh complete")
        else:
            logger.error(f"❌ OSM boundary refresh failed:\n{result.stderr[:500]}")
    except Exception as e:
        logger.error(f"❌ OSM boundary refresh job error: {e}", exc_info=True)


# OSM boundary refresh: weekly on Sunday at 03:00 Moscow time
from apscheduler.triggers.cron import CronTrigger
scheduler.add_job(
    func=run_fetch_osm_boundaries,
    trigger=CronTrigger(day_of_week='sun', hour=3, minute=0, timezone='Europe/Moscow'),
    id='fetch_osm_boundaries_job',
    name='Обновление OSM-границ районов (еженедельно, вс 03:00)',
    replace_existing=True
)

def run_news_enricher_job():
    """
    Scheduled job: fetch real estate articles from all sources,
    uniqualize and save as draft BlogPost entries.
    Runs twice daily (08:00 and 20:00 Moscow time).
    """
    with app.app_context():
        try:
            logger.info("📰 Starting news enricher job...")
            from services.news_enricher import run_enrichment
            from models import User
            # Use first admin user as author
            admin = User.query.filter_by(is_admin=True).first()
            if not admin:
                logger.warning("⚠️  No admin user found, skipping news enricher")
                return
            stats = run_enrichment(
                admin_id=admin.id,
                uniqualize_mode='smart',
                status='draft',
                limit_per_source=3,
            )
            logger.info(
                f"✅ News enricher done: fetched={stats['fetched']}, "
                f"relevant={stats['relevant']}, saved={stats['saved']}, "
                f"skipped={stats['skipped']}, errors={stats['errors']}"
            )
            if stats['saved_titles']:
                for t in stats['saved_titles']:
                    logger.info(f"   📄 {t}")
        except Exception as e:
            logger.error(f"❌ News enricher job error: {e}", exc_info=True)


# News enricher: twice a day at 08:00 and 20:00 Moscow time
scheduler.add_job(
    func=run_news_enricher_job,
    trigger=CronTrigger(hour='8,20', minute=0, timezone='Europe/Moscow'),
    id='news_enricher_job',
    name='Обогатитель новостей о недвижимости (ежедневно 08:00 и 20:00)',
    replace_existing=True
)

def run_price_snapshot_job():
    """Monthly price snapshot for all active residential complexes."""
    try:
        from services.price_snapshot import record_price_snapshots
        saved = record_price_snapshots()
        logger.info(f"✅ Price snapshot job: {saved} records saved")
    except Exception as e:
        logger.error(f"❌ Price snapshot job failed: {e}", exc_info=True)

scheduler.add_job(
    func=run_price_snapshot_job,
    trigger=CronTrigger(day=1, hour=3, minute=0, timezone='Europe/Moscow'),
    id='price_snapshot_job',
    name='Снимок цен по ЖК (1-го числа каждого месяца в 03:00)',
    replace_existing=True
)

# Start scheduler only in main process (avoid duplication under Gunicorn)
if os.environ.get('ENABLE_SCHEDULER', 'false').lower() == 'true':
    scheduler.start()
    logger.info("✅ APScheduler started - Background jobs configured:")
    logger.info("   🔔 Instant alerts: Every 5 minutes")
    logger.info("   📧 Daily digest: Every day at 8:00 AM")
    logger.info("   📆 Weekly digest: Every Monday at 8:00 AM")
    logger.info("   ⏰ Task reminders: Every 5 minutes")
    logger.info("   🔴 Overdue task alerts: Every 10 minutes")
    logger.info("   🗺️  Auto-geocode: Every 2 hours")
    logger.info("   🌐 Sitemap ping: Daily at 06:00")
    logger.info("   🏗️  CIAN enrichment: Every Sunday at 02:00 (full)")
    logger.info("   🏘️  District assignment: Every 6 hours")
    logger.info("   ⚡ CIAN prices: Mon-Sat at 06:00 (prices only)")
    logger.info("   🌍 OSM boundaries: Every Sunday at 03:00")
    logger.info("   📊 Price snapshots: 1st of every month at 03:00")
else:
    logger.info("⏸️  APScheduler skipped - Set ENABLE_SCHEDULER=true to run background jobs")

# Register shutdown only if scheduler is running
import atexit
if scheduler.running:
    atexit.register(lambda: scheduler.shutdown())

# ==================== DASHBOARD BOOTSTRAP API ====================

@admin_api_bp.route('/api/dashboard/bootstrap', methods=['GET'])
@login_required
def api_dashboard_bootstrap():
    """
    Single endpoint that returns ALL dashboard data in one request.
    Eliminates 6 sequential API calls that caused 30+ second load times.
    
    Returns: favorites, comparisons, balance, cities, recommendations, collections
    """
    from models import (FavoriteProperty, FavoriteComplex, Property, ResidentialComplex, 
                       Developer, UserComparison, ComparisonProperty, ComparisonComplex,
                       Recommendation, SentSearch, Collection, City)
    from services.balance_service import BalanceService
    from services.withdrawal_service import WithdrawalService
    from decimal import Decimal
    from sqlalchemy import func
    import json
    
    result = {
        'success': True,
        'favorites': {'properties': [], 'complexes': []},
        'comparisons': {'properties': [], 'complexes': [], 'properties_count': 0, 'complexes_count': 0},
        'balance': {},
        'cities': [],
        'recommendations': [],
        'collections': []
    }
    
    try:
        # ============ FAVORITES ============
        # Properties favorites
        prop_favorites = db.session.query(FavoriteProperty).filter_by(user_id=current_user.id).order_by(FavoriteProperty.created_at.desc()).all()
        property_ids = [int(fav.property_id) for fav in prop_favorites if fav.property_id and fav.property_id.isdigit()]
        
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
            ).filter(Property.id.in_(property_ids)).all()
            
            properties_dict = {}
            for prop, complex_name, cashback_rate, complex_image, developer_name in properties_query:
                rooms_text = f"{prop.rooms}-комн" if prop.rooms and prop.rooms > 0 else "Студия"
                properties_dict[prop.id] = {
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
                }
            
            for fav in prop_favorites:
                if fav.property_id:
                    property_id_int = int(fav.property_id) if fav.property_id.isdigit() else None
                    property_data = properties_dict.get(property_id_int)
                    if property_data:
                        property_data['created_at'] = fav.created_at.strftime('%d.%m.%Y в %H:%M') if fav.created_at else 'Недавно'
                        result['favorites']['properties'].append(property_data)
        
        # Complex favorites 
        complex_favorites = db.session.query(FavoriteComplex).filter_by(user_id=current_user.id).all()
        result['favorites']['complexes'] = [{'id': str(fc.complex_id)} for fc in complex_favorites]
        
        # ============ COMPARISONS ============
        user_comparison = UserComparison.query.filter_by(user_id=current_user.id, is_active=True).first()
        if user_comparison:
            comp_properties = ComparisonProperty.query.filter_by(user_comparison_id=user_comparison.id).all()
            comp_complexes = ComparisonComplex.query.filter_by(user_comparison_id=user_comparison.id).all()
            
            result['comparisons']['properties'] = [{'id': str(cp.property_id)} for cp in comp_properties if cp.property_id]
            result['comparisons']['complexes'] = [{'id': str(cc.complex_id)} for cc in comp_complexes if cc.complex_id]
            result['comparisons']['properties_count'] = len(result['comparisons']['properties'])
            result['comparisons']['complexes_count'] = len(result['comparisons']['complexes'])
        
        # ============ BALANCE ============
        balance_info = BalanceService.get_balance(current_user.id)
        registration_bonus_amount = WithdrawalService._get_transaction_sum_by_type(current_user.id, 'registration_bonus')
        cashback_earned_amount = WithdrawalService._get_transaction_sum_by_type(current_user.id, 'cashback_earned')
        available_amount = Decimal(str(balance_info['available_amount']))
        
        if cashback_earned_amount == 0 and registration_bonus_amount > 0:
            withdrawable_amount = max(Decimal('0'), available_amount - registration_bonus_amount)
        else:
            withdrawable_amount = available_amount
        
        result['balance'] = {
            'available_amount': balance_info['available_amount'],
            'pending_amount': balance_info['pending_amount'],
            'total_earned': balance_info['total_earned'],
            'total_withdrawn': balance_info['total_withdrawn'],
            'currency': balance_info['currency'],
            'registration_bonus_amount': float(registration_bonus_amount),
            'cashback_earned_amount': float(cashback_earned_amount),
            'withdrawable_amount': float(withdrawable_amount)
        }
        
        # ============ CITIES ============
        cities_with_counts = db.session.query(
            City, func.count(Property.id).label('property_count')
        ).outerjoin(
            Property, (Property.city_id == City.id) & (Property.is_active == True)
        ).filter(City.is_active == True).group_by(City.id).order_by(func.count(Property.id).desc()).all()
        
        for city, property_count in cities_with_counts:
            if property_count == 0 and not city.is_default:
                continue
            result['cities'].append({
                'id': city.id,
                'name': city.name,
                'slug': city.slug,
                'is_default': city.is_default,
                'address_position_lat': city.latitude,
                'address_position_lon': city.longitude,
                'zoom_level': city.zoom_level,
                'property_count': property_count
            })
        
        # ============ RECOMMENDATIONS ============
        recommendations = Recommendation.query.filter_by(client_id=current_user.id).order_by(Recommendation.sent_at.desc()).all()
        for rec in recommendations:
            rec_data = rec.to_dict()
            rec_data['manager_name'] = f"{rec.manager.first_name} {rec.manager.last_name}" if rec.manager else 'Менеджер'
            result['recommendations'].append(rec_data)
        
        sent_searches = SentSearch.query.filter_by(client_id=current_user.id).order_by(SentSearch.sent_at.desc()).all()
        for search in sent_searches:
            result['recommendations'].append({
                'id': f'search_{search.id}',
                'title': f'Подбор недвижимости: {search.name}',
                'description': search.description or 'Персональный подбор от вашего менеджера',
                'recommendation_type': 'search',
                'item_id': str(search.id),
                'status': search.status,
                'manager_name': search.manager.name if search.manager else 'Менеджер',
                'created_at': search.sent_at.isoformat() if search.sent_at else None,
            })
        result['recommendations'].sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # ============ COLLECTIONS ============
        collections = Collection.query.filter_by(assigned_to_user_id=current_user.id).order_by(Collection.created_at.desc()).all()
        for collection in collections:
            manager = collection.created_by
            manager_name = manager.full_name if manager else 'Менеджер'
            if manager and manager.profile_image and 'randomuser.me' not in manager.profile_image:
                if manager.profile_image.startswith('http'):
                    manager_avatar = manager.profile_image
                else:
                    base_url = request.host_url.rstrip('/')
                    manager_avatar = f"{base_url}{manager.profile_image}"
            else:
                manager_avatar = manager_name[0].upper() if manager_name else 'М'

            from zoneinfo import ZoneInfo
            formatted_date = ''
            if collection.created_at:
                try:
                    formatted_date = collection.created_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y в %H:%M')
                except Exception:
                    formatted_date = collection.created_at.isoformat()

            from repositories.property_repository import PropertyRepository as _PropRepo
            properties_data = []
            for prop in (collection.properties or [])[:4]:
                property_obj = Property.query.filter_by(inner_id=prop.property_id).first()
                if not property_obj:
                    property_obj = _PropRepo.get_by_id(prop.property_id)
                if property_obj:
                    image_url = ''
                    if property_obj.gallery_images:
                        try:
                            photos_list = json.loads(property_obj.gallery_images) if isinstance(property_obj.gallery_images, str) else property_obj.gallery_images
                            image_url = photos_list[0] if photos_list and len(photos_list) > 0 else ''
                        except Exception:
                            pass
                    rooms_text = f"{property_obj.rooms}-комн" if property_obj.rooms and property_obj.rooms > 0 else "Студия"
                    area_text = f"{property_obj.area} м²" if property_obj.area else ""
                    properties_data.append({
                        'id': prop.property_id,
                        'image': image_url,
                        'title': f"{rooms_text}, {area_text}".strip(', ')
                    })

            result['collections'].append({
                'id': collection.id,
                'title': collection.title,
                'description': collection.description,
                'status': collection.status,
                'manager_name': manager_name,
                'manager_avatar': manager_avatar,
                'properties_count': len(collection.properties) if collection.properties else 0,
                'properties': properties_data,
                'unique_url': collection.unique_url,
                'created_at': formatted_date,
            })
        
        print(f"🚀 Dashboard bootstrap: user={current_user.id}, favorites={len(result['favorites']['properties'])}, "
              f"comparisons={result['comparisons']['properties_count']}, recommendations={len(result['recommendations'])}, "
              f"collections={len(result['collections'])}")
        
        return jsonify(result)
        
    except Exception as e:
        import traceback
        current_app.logger.error(f"Dashboard bootstrap error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== BALANCE AND WITHDRAWAL API ENDPOINTS ====================

# User endpoints (require @login_required)
@admin_api_bp.route('/api/balance', methods=['GET'])
@login_required
def api_get_balance():
    """Get current balance for authenticated user with withdrawal restrictions"""
    try:
        from services.balance_service import BalanceService
        from services.withdrawal_service import WithdrawalService
        from decimal import Decimal
        
        balance_info = BalanceService.get_balance(current_user.id)
        
        # Calculate registration bonus and cashback amounts
        registration_bonus_amount = WithdrawalService._get_transaction_sum_by_type(
            current_user.id, 'registration_bonus'
        )
        cashback_earned_amount = WithdrawalService._get_transaction_sum_by_type(
            current_user.id, 'cashback_earned'
        )
        
        # Calculate withdrawable amount based on cashback restriction
        available_amount = Decimal(str(balance_info['available_amount']))
        
        if cashback_earned_amount == 0 and registration_bonus_amount > 0:
            # User has not received cashback yet - cannot withdraw registration bonus
            withdrawable_amount = max(Decimal('0'), available_amount - registration_bonus_amount)
        else:
            # User has received cashback - can withdraw everything
            withdrawable_amount = available_amount
        
        current_app.logger.debug(f"💰 Balance API for user {current_user.id}: "
                        f"available={available_amount}₽, "
                        f"registration_bonus={registration_bonus_amount}₽, "
                        f"cashback_earned={cashback_earned_amount}₽, "
                        f"withdrawable={withdrawable_amount}₽")
        
        return jsonify({
            'success': True,
            'available_amount': balance_info['available_amount'],
            'pending_amount': balance_info['pending_amount'],
            'total_earned': balance_info['total_earned'],
            'total_withdrawn': balance_info['total_withdrawn'],
            'currency': balance_info['currency'],
            # New fields for withdrawal restriction
            'registration_bonus_amount': float(registration_bonus_amount),
            'cashback_earned_amount': float(cashback_earned_amount),
            'withdrawable_amount': float(withdrawable_amount)
        })
    except Exception as e:
        current_app.logger.error(f"Error getting balance for user {current_user.id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400

@admin_api_bp.route('/api/balance/transactions', methods=['GET'])
@login_required
def api_get_transactions():
    """Get transaction history for authenticated user"""
    try:
        from services.balance_service import BalanceService
        
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        transactions = BalanceService.get_transaction_history(current_user.id, limit, offset)
        total_count = BalanceService.get_transaction_count(current_user.id)
        
        # Format transactions with ISO dates
        formatted_transactions = []
        for t in transactions:
            formatted_transactions.append({
                'id': t.id,
                'amount': float(t.amount),
                'type': t.transaction_type,
                'description': t.description,
                'created_at': t.created_at.isoformat() if t.created_at else None,
                'balance_before': float(t.balance_before),
                'balance_after': float(t.balance_after)
            })
        
        return jsonify({
            'success': True,
            'transactions': formatted_transactions,
            'total': total_count
        })
    except Exception as e:
        current_app.logger.error(f"Error getting transactions for user {current_user.id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400



@admin_api_bp.route('/api/admin/balance/transactions/<int:user_id>', methods=['GET'])
@admin_required
def api_admin_get_user_transactions(user_id):
    """Get transaction history for a specific user (admin only)"""
    try:
        from services.balance_service import BalanceService
        from models import User
        
        # Check if user exists
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        transactions = BalanceService.get_transaction_history(user_id, limit=limit, offset=offset)
        total_count = BalanceService.get_transaction_count(user_id)
        
        transactions_data = []
        for tx in transactions:
            transactions_data.append({
                'id': tx.id,
                'amount': float(tx.amount),
                'transaction_type': tx.transaction_type,
                'description': tx.description,
                'balance_before': float(tx.balance_before),
                'balance_after': float(tx.balance_after),
                'status': tx.status,
                'created_at': tx.created_at.strftime('%d.%m.%Y %H:%M'),
                'processed_at': tx.processed_at.strftime('%d.%m.%Y %H:%M') if tx.processed_at else None
            })
        
        return jsonify({
            'success': True,
            'transactions': transactions_data,
            'total_count': total_count,
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/api/withdrawals', methods=['POST'])
@login_required
def api_create_withdrawal():
    """Create withdrawal request for authenticated user"""
    try:
        from services.withdrawal_service import WithdrawalService
        
        data = request.get_json()
        
        amount = data.get('amount')
        payout_method = data.get('payout_method')
        payout_details = data.get('payout_details')
        
        # Validation
        if not amount or float(amount) <= 0:
            return jsonify({'success': False, 'error': 'amount must be greater than 0'}), 400
        
        if not payout_method:
            return jsonify({'success': False, 'error': 'payout_method is required'}), 400
        
        if not payout_details:
            return jsonify({'success': False, 'error': 'payout_details is required'}), 400
        
        withdrawal_request = WithdrawalService.create_withdrawal_request(
            user_id=current_user.id,
            amount=amount,
            payout_method=payout_method,
            payout_details_dict=payout_details
        )
        
        current_app.logger.info(f"✅ Created withdrawal request #{withdrawal_request.id} for user {current_user.id}")
        
        return jsonify({
            'success': True,
            'request_id': withdrawal_request.id,
            'message': 'Withdrawal request created successfully'
        })
    except ValueError as e:
        current_app.logger.warning(f"Validation error creating withdrawal for user {current_user.id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating withdrawal for user {current_user.id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400


@admin_api_bp.route('/api/withdrawals', methods=['GET'])
@login_required
def api_get_withdrawals():
    """Get withdrawal requests for authenticated user"""
    try:
        from services.withdrawal_service import WithdrawalService
        import json
        
        status = request.args.get('status')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        requests_list = WithdrawalService.get_withdrawal_requests(
            user_id=current_user.id,
            status=status,
            limit=limit,
            offset=offset
        )
        total_count = WithdrawalService.get_withdrawal_request_count(
            user_id=current_user.id,
            status=status
        )
        
        # Format requests with ISO dates
        formatted_requests = []
        for r in requests_list:
            formatted_requests.append({
                'id': r.id,
                'amount': float(r.amount),
                'status': r.status,
                'payout_method': r.payout_method,
                'payout_details_dict': json.loads(r.payout_details) if r.payout_details else {},
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'processed_at': r.processed_at.isoformat() if r.processed_at else None,
                'paid_at': r.paid_at.isoformat() if r.paid_at else None
            })
        
        return jsonify({
            'success': True,
            'requests': formatted_requests,
            'total': total_count
        })
    except Exception as e:
        current_app.logger.error(f"Error getting withdrawals for user {current_user.id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400


# Admin endpoints (require @admin_required)
@admin_api_bp.route('/api/admin/balance/credit', methods=['POST'])
@csrf.exempt
@admin_required
def api_admin_credit_balance():
    """Credit balance for a user (admin only)"""
    try:
        from services.balance_service import BalanceService
        from models import User
        
        data = request.get_json()
        
        user_id = data.get('user_id')
        amount = data.get('amount')
        description = data.get('description')
        transaction_type = data.get('transaction_type', 'bonus')
        deal_id = data.get('deal_id')
        
        # Validation
        if not user_id:
            return jsonify({'success': False, 'error': 'user_id is required'}), 400
        
        if not amount or float(amount) <= 0:
            return jsonify({'success': False, 'error': 'amount must be greater than 0'}), 400
        
        if not description:
            return jsonify({'success': False, 'error': 'description is required'}), 400
        
        # Check user exists
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': f'User {user_id} not found'}), 400
        
        transaction = BalanceService.credit_balance(
            user_id=user_id,
            amount=amount,
            description=description,
            transaction_type=transaction_type,
            deal_id=deal_id,
            created_by_id=current_user.id
        )
        
        current_app.logger.info(f"✅ Admin {current_user.id} credited {amount}₽ to user {user_id}")
        
        return jsonify({
            'success': True,
            'transaction_id': transaction.id
        })
    except ValueError as e:
        current_app.logger.warning(f"Validation error in admin credit: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error in admin credit: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400


@admin_api_bp.route('/api/admin/withdrawals', methods=['GET'])
@admin_required
def api_admin_get_withdrawals():
    """Get all withdrawal requests (admin only)"""
    try:
        from services.withdrawal_service import WithdrawalService
        import json
        
        status = request.args.get('status')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        requests_list = WithdrawalService.get_withdrawal_requests(
            user_id=None,  # Get all requests
            status=status,
            limit=limit,
            offset=offset
        )
        total_count = WithdrawalService.get_withdrawal_request_count(
            user_id=None,
            status=status
        )
        
        # Format requests with ISO dates and user info
        formatted_requests = []
        for r in requests_list:
            # Safe JSON parsing with error handling
            try:
                payout_details_dict = json.loads(r.payout_details) if (r.payout_details and r.payout_details.strip()) else {}
            except (ValueError, TypeError, json.JSONDecodeError):
                payout_details_dict = {}
            
            formatted_requests.append({
                'id': r.id,
                'user_id': r.user_id,
                'user_name': r.user.full_name if hasattr(r.user, 'full_name') and r.user.full_name else r.user.email,
                'user_email': r.user.email,
                'amount': float(r.amount),
                'status': r.status,
                'payout_method': r.payout_method,
                'payout_details_dict': payout_details_dict,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'processed_at': r.processed_at.isoformat() if r.processed_at else None,
                'paid_at': r.paid_at.isoformat() if r.paid_at else None,
                'rejection_reason': r.rejection_reason
            })
        
        return jsonify({
            'success': True,
            'requests': formatted_requests,
            'total': total_count
        })
    except Exception as e:
        current_app.logger.error(f"Error getting admin withdrawals: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400


@admin_api_bp.route('/api/admin/withdrawals/<int:request_id>/approve', methods=['POST'])
@csrf.exempt
@admin_required
def api_admin_approve_withdrawal(request_id):
    """Approve withdrawal request (admin only)"""
    try:
        from services.withdrawal_service import WithdrawalService
        
        withdrawal_request = WithdrawalService.approve_withdrawal(
            request_id=request_id,
            admin_id=current_user.id
        )
        
        current_app.logger.info(f"✅ Admin {current_user.id} approved withdrawal request #{request_id}")
        
        return jsonify({
            'success': True,
            'message': 'Withdrawal request approved successfully'
        })
    except ValueError as e:
        current_app.logger.warning(f"Validation error approving withdrawal {request_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error approving withdrawal {request_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400


@admin_api_bp.route('/api/admin/withdrawals/<int:request_id>/reject', methods=['POST'])
@csrf.exempt
@admin_required
def api_admin_reject_withdrawal(request_id):
    """Reject withdrawal request (admin only)"""
    try:
        from services.withdrawal_service import WithdrawalService
        
        data = request.get_json()
        rejection_reason = data.get('rejection_reason')
        
        if not rejection_reason:
            return jsonify({'success': False, 'error': 'rejection_reason is required'}), 400
        
        withdrawal_request = WithdrawalService.reject_withdrawal(
            request_id=request_id,
            admin_id=current_user.id,
            rejection_reason=rejection_reason
        )
        
        current_app.logger.info(f"✅ Admin {current_user.id} rejected withdrawal request #{request_id}")
        
        return jsonify({
            'success': True,
            'message': 'Withdrawal request rejected successfully'
        })
    except ValueError as e:
        current_app.logger.warning(f"Validation error rejecting withdrawal {request_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error rejecting withdrawal {request_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400


@admin_api_bp.route('/api/admin/withdrawals/<int:request_id>/mark-paid', methods=['POST'])
@csrf.exempt
@admin_required
def api_admin_mark_withdrawal_paid(request_id):
    """Mark withdrawal request as paid (admin only)"""
    try:
        from services.withdrawal_service import WithdrawalService
        
        withdrawal_request = WithdrawalService.mark_as_paid(
            request_id=request_id,
            admin_id=current_user.id
        )
        
        current_app.logger.info(f"✅ Admin {current_user.id} marked withdrawal request #{request_id} as paid")
        
        return jsonify({
            'success': True,
            'message': 'Withdrawal request marked as paid successfully'
        })
    except ValueError as e:
        current_app.logger.warning(f"Validation error marking withdrawal {request_id} as paid: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error marking withdrawal {request_id} as paid: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400


@admin_api_bp.route('/api/admin/users-with-balance')
@admin_required
def api_admin_users_with_balance():
    """Get all users with balance (admin only)"""
    try:
        from models import User, UserBalance
        
        users_with_balance = db.session.query(
            User.id.label('user_id'),
            User.email,
            User.full_name,
            UserBalance.available_amount.label('available'),
            UserBalance.pending_amount.label('pending'),
            UserBalance.total_earned,
            UserBalance.total_withdrawn
        ).join(UserBalance, User.id == UserBalance.user_id).filter(
            (UserBalance.available_amount > 0) | 
            (UserBalance.pending_amount > 0) |
            (UserBalance.total_earned > 0)
        ).all()
        
        users_list = [{
            'user_id': u.user_id,
            'email': u.email,
            'full_name': u.full_name,
            'available': float(u.available),
            'pending': float(u.pending),
            'total_earned': float(u.total_earned),
            'total_withdrawn': float(u.total_withdrawn)
        } for u in users_with_balance]
        
        return jsonify({'success': True, 'users': users_list})
    except Exception as e:
        current_app.logger.error(f"Error getting users with balance: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400

@admin_api_bp.route('/api/admin/search-users')
@admin_required
def api_admin_search_users():
    """Search users by email or name (admin only)"""
    try:
        from models import User
        
        query = request.args.get('q', '').strip()
        if len(query) < 3:
            return jsonify({'success': True, 'users': []})
        
        users = User.query.filter(
            db.or_(
                User.email.ilike(f'%{query}%'),
                User.full_name.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
        users_list = [{
            'id': u.id,
            'email': u.email,
            'full_name': u.full_name
        } for u in users]
        
        return jsonify({'success': True, 'users': users_list})
    except Exception as e:
        current_app.logger.error(f"Error searching users: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
if __name__ == '__main__':
    with app.app_context():
        from models import User, Manager, SavedSearch, SentSearch, CashbackRecord, Application, Favorite, Notification, District, Developer, ResidentialComplex, Street, RoomType, Admin, BlogPost, City, Offer, MarketingMaterial, ManagerCheckin
        db.create_all()
        
        # Initialize cities
        try:
            init_cities()
            print("Cities initialized successfully")
        except Exception as e:
            print(f"Error initializing cities: {e}")
            db.session.rollback()
        
        # Initialize search data
        try:
            init_search_data()
            print("Search data initialized successfully")
        except Exception as e:
            print(f"Error initializing search data: {e}")
            db.session.rollback()



# ==================== ADMIN DEVELOPERS & CITIES (extracted from app.py) ====================
@admin_api_bp.route('/api/admin/developers/<int:dev_id>/update', methods=['POST'])
@admin_required
def api_admin_developer_update(dev_id):
    data = request.get_json() or {}
    allowed = ['name', 'full_name', 'website', 'phone', 'email',
               'logo_url', 'inn', 'is_active', 'is_partner',
               'description', 'founded_year', 'rating']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields'}), 400
    set_parts = ', '.join(f'{k} = :{k}' for k in updates)
    updates['dev_id'] = dev_id
    updates['updated_at'] = datetime.utcnow()
    db.session.execute(
        text(f'UPDATE developers SET {set_parts}, updated_at=:updated_at WHERE id=:dev_id'),
        updates
    )
    db.session.commit()
    invalidate_complexes_cache()
    return jsonify({'ok': True})


@admin_api_bp.route('/api/admin/developers/create', methods=['POST'])
@admin_required
def api_admin_developer_create():
    import re as _re
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name обязателен'}), 400
    slug = _re.sub(r'[^a-z0-9-]', '-', name.lower().replace(' ', '-'))[:80].strip('-')
    res = db.session.execute(
        text("""INSERT INTO developers (name, full_name, website, phone, email,
                    logo_url, inn, is_active, is_partner, description, founded_year,
                    slug, created_at, updated_at)
             VALUES (:name, :full_name, :website, :phone, :email,
                    :logo_url, :inn, :is_active, :is_partner, :description, :founded_year,
                    :slug, :now, :now)
             RETURNING id"""),
        {
            'name': name,
            'full_name': (data.get('full_name') or '').strip() or None,
            'website': (data.get('website') or '').strip() or None,
            'phone': (data.get('phone') or '').strip() or None,
            'email': (data.get('email') or '').strip() or None,
            'logo_url': (data.get('logo_url') or '').strip() or None,
            'inn': (data.get('inn') or '').strip() or None,
            'is_active': bool(data.get('is_active', True)),
            'is_partner': bool(data.get('is_partner', False)),
            'description': (data.get('description') or '').strip() or None,
            'founded_year': data.get('founded_year') or None,
            'slug': slug,
            'now': datetime.utcnow(),
        }
    )
    db.session.commit()
    invalidate_complexes_cache()
    new_id = res.fetchone()[0]
    return jsonify({'ok': True, 'id': new_id})


# ── Re-scrape single developer from CIAN ─────────────────────────────────────
@admin_api_bp.route('/api/admin/developers/<int:dev_id>/rescrape', methods=['POST'])
@admin_required
def api_admin_developer_rescrape(dev_id):
    """Повторно скрапит страницу застройщика с CIAN и обновляет поля в БД."""
    try:
        import sys as _sys
        import os as _os
        _scripts = _SCRIPTS_DIR
        if _scripts not in _sys.path:
            _sys.path.insert(0, _scripts)
        from enrich_complexes import scrape_developer_page, _download_logo

        dev_row = db.session.execute(
            text('SELECT id, name, source_url, external_id FROM developers WHERE id=:id'),
            {'id': dev_id}
        ).fetchone()
        if not dev_row:
            return jsonify({'error': 'Застройщик не найден'}), 404

        source_url = dev_row.source_url
        if not source_url:
            return jsonify({'error': 'Нет source_url (CIAN URL) для этого застройщика'}), 400

        pdata = scrape_developer_page(source_url)
        if not pdata:
            return jsonify({'error': 'CIAN не вернул данные (капча или недоступна страница)'}), 502

        # Download logo locally if not yet saved
        if not pdata.get('logo_url') and dev_row.external_id:
            local = _download_logo(str(dev_row.external_id))
            if local:
                pdata['logo_url'] = local

        # Build UPDATE
        fields, values = [], {}
        def _add(col, val):
            if val is not None:
                fields.append(f'{col}=:{col}')
                values[col] = val

        _add('founded_year',      pdata.get('founded_year'))
        _add('established_year',  pdata.get('founded_year'))
        _add('completed_projects', pdata.get('completed_projects'))
        _add('completed_complexes', pdata.get('completed_projects'))
        _add('under_construction', pdata.get('under_construction'))
        _add('construction_complexes', pdata.get('under_construction'))
        _add('logo_url',          pdata.get('logo_url'))
        _add('website',           pdata.get('website'))
        _add('inn',               pdata.get('inn'))
        _add('description',       pdata.get('description'))
        _add('full_name',         pdata.get('full_name'))

        if fields:
            values['dev_id'] = dev_id
            values['now'] = datetime.utcnow()
            db.session.execute(
                text(f'UPDATE developers SET {", ".join(fields)}, updated_at=:now WHERE id=:dev_id'),
                values
            )
            db.session.commit()

        return jsonify({
            'ok': True,
            'updated': len(fields),
            'data': {
                'founded_year':       pdata.get('founded_year'),
                'completed_projects': pdata.get('completed_projects'),
                'under_construction': pdata.get('under_construction'),
                'logo_url':           pdata.get('logo_url'),
                'website':            pdata.get('website'),
                'inn':                pdata.get('inn'),
            }
        })
    except Exception as e:
        current_app.logger.exception('rescrape error')
        return jsonify({'error': str(e)}), 500


# ── Re-scrape ALL developers with missing data (background) ──────────────────
import threading as _threading
from sqlalchemy import text
_rescrape_job = {'status': 'idle', 'done': 0, 'total': 0, 'errors': 0, 'log': []}

@admin_api_bp.route('/api/admin/developers/rescrape-missing', methods=['POST'])
@admin_required
def api_admin_developers_rescrape_missing():
    """Запускает фоновый дозабор данных для всех застройщиков с пустыми полями."""
    global _rescrape_job
    if _rescrape_job['status'] == 'running':
        return jsonify({'ok': False, 'error': 'Уже выполняется'}), 409

    rows = db.session.execute(text("""
        SELECT id, name, source_url, external_id
        FROM developers
        WHERE source_url IS NOT NULL AND source_url != ''
          AND (founded_year IS NULL
               OR completed_projects IS NULL OR completed_projects = 0
               OR under_construction  IS NULL OR under_construction  = 0)
        ORDER BY id
    """)).fetchall()

    _rescrape_job = {'status': 'running', 'done': 0, 'total': len(rows), 'errors': 0, 'log': []}

    def _run():
        import sys as _sys, os as _os, time as _time
        _scripts = _SCRIPTS_DIR
        if _scripts not in _sys.path:
            _sys.path.insert(0, _scripts)
        from enrich_complexes import scrape_developer_page, _download_logo
        import psycopg2

        conn = psycopg2.connect(_os.environ['DATABASE_URL'])
        cur  = conn.cursor()

        for dev_id, name, source_url, ext_id in rows:
            try:
                pdata = scrape_developer_page(source_url)
                if not pdata:
                    _rescrape_job['errors'] += 1
                    _rescrape_job['log'].append(f'⚠ {name}: нет данных')
                else:
                    if not pdata.get('logo_url') and ext_id:
                        local = _download_logo(str(ext_id))
                        if local:
                            pdata['logo_url'] = local
                    # Save
                    sets, vals = [], {}
                    def _add(c, v):
                        if v is not None:
                            sets.append(f'{c}=%s'); vals[c] = v
                    _add('founded_year',       pdata.get('founded_year'))
                    _add('established_year',   pdata.get('founded_year'))
                    _add('completed_projects', pdata.get('completed_projects'))
                    _add('completed_complexes',pdata.get('completed_projects'))
                    _add('under_construction', pdata.get('under_construction'))
                    _add('construction_complexes', pdata.get('under_construction'))
                    _add('logo_url',           pdata.get('logo_url'))
                    _add('website',            pdata.get('website'))
                    _add('inn',                pdata.get('inn'))
                    _add('description',        pdata.get('description'))
                    _add('full_name',          pdata.get('full_name'))
                    if sets:
                        q = f"UPDATE developers SET {', '.join(f'{k}=%s' for k in vals)} WHERE id=%s"
                        cur.execute(q, list(vals.values()) + [dev_id])
                        conn.commit()
                    got = [k for k in ['founded_year','completed_projects','under_construction','logo_url'] if vals.get(k)]
                    _rescrape_job['log'].append(f'✅ {name}: {", ".join(got) or "обновлено"}')
            except Exception as ex:
                _rescrape_job['errors'] += 1
                _rescrape_job['log'].append(f'❌ {name}: {ex}')
            _rescrape_job['done'] += 1
            _time.sleep(0.4)

        conn.close()
        _rescrape_job['status'] = 'done'

    _threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'total': len(rows)})


@admin_api_bp.route('/api/admin/developers/rescrape-status', methods=['GET'])
@admin_required
def api_admin_developers_rescrape_status():
    return jsonify(_rescrape_job)


@admin_api_bp.route('/api/admin/cities/probe-cian', methods=['POST'])
@admin_required
def api_admin_cities_probe_cian():
    """Проверяем CIAN region_id — возвращаем кол-во новостроек."""
    import requests as _req
    data = request.get_json() or {}
    region_id = data.get('region_id')
    if not region_id:
        return jsonify({'error': 'region_id required'}), 400
    try:
        body = {'jsonQuery': {
            '_type': 'flatsale',
            'engine_version': {'type': 'term', 'value': 2},
            'region': {'type': 'terms', 'value': [int(region_id)]},
            'from_developer': {'type': 'term', 'value': True},
            'page': {'type': 'term', 'value': 1},
        }}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        r = _req.post(
            'https://api.cian.ru/search-offers/v2/search-offers-desktop/',
            json=body, headers=headers, timeout=12
        )
        if r.status_code == 200:
            d = r.json().get('data', {})
            count = d.get('offerCount') or d.get('aggregatedCount') or 0
            # Оцениваем кол-во страниц (28 объявлений на страницу как у ЦИАН)
            jk_ids = set()
            for offer in d.get('offersSerialized', []):
                nb = offer.get('newbuilding') or {}
                if nb.get('id'):
                    jk_ids.add(nb['id'])
            return jsonify({'ok': True, 'offers_count': count, 'sample_jk': len(jk_ids)})
        return jsonify({'error': f'CIAN вернул HTTP {r.status_code}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_api_bp.route('/api/admin/cities/lookup-dadata', methods=['POST'])
@admin_required
def api_admin_cities_lookup_dadata():
    """Ищем город через DaData — возвращаем координаты, FIAS, нормализованное имя."""
    import requests as _req
    data = request.get_json() or {}
    city_name = (data.get('name') or '').strip()
    if not city_name:
        return jsonify({'error': 'name required'}), 400
    dadata_key = os.environ.get('DADATA_API_KEY', '')
    if not dadata_key:
        return jsonify({'error': 'DaData API key не настроен (DADATA_API_KEY)'}), 500
    try:
        r = _req.post(
            'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address',
            json={'query': city_name, 'count': 5,
                  'from_bound': {'value': 'city'}, 'to_bound': {'value': 'city'},
                  'locations': [{'fias_level': '4'}]},
            headers={
                'Authorization': f'Token {dadata_key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            timeout=10
        )
        if r.status_code == 200:
            suggestions = r.json().get('suggestions', [])
            results = []
            for s in suggestions:
                d = s.get('data', {})
                results.append({
                    'value': s.get('value', ''),
                    'city': d.get('city') or d.get('settlement') or d.get('region'),
                    'region': d.get('region', ''),
                    'fias_id': d.get('city_fias_id') or d.get('fias_id'),
                    'lat': d.get('geo_lat'),
                    'lon': d.get('geo_lon'),
                    'kladr_id': d.get('city_kladr_id') or d.get('kladr_id'),
                })
            return jsonify({'ok': True, 'suggestions': results})
        return jsonify({'error': f'DaData вернул HTTP {r.status_code}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_api_bp.route('/api/admin/cities/add', methods=['POST'])
@admin_required
def api_admin_cities_add():
    """Создаём новый город: запись в БД + строка в city_config.json."""
    import json as _json
    import re as _re
    data = request.get_json() or {}

    name           = (data.get('name') or '').strip()
    name_en        = (data.get('name_en') or '').strip().lower()
    cian_region_id = data.get('cian_region_id')
    total_pages    = int(data.get('total_pages') or 30)
    lat            = data.get('lat')
    lon            = data.get('lon')
    fias_id        = data.get('fias_id') or None
    name_gen       = (data.get('name_genitive') or '').strip() or None
    name_prep      = (data.get('name_prepositional') or '').strip() or None
    region_name    = (data.get('region_name') or 'Краснодарский край').strip()

    if not name or not name_en or not cian_region_id:
        return jsonify({'error': 'name, name_en и cian_region_id обязательны'}), 400

    # Slug из name_en
    slug = _re.sub(r'[^a-z0-9-]', '-', name_en).strip('-')

    # Slug для региона
    def _make_slug(s):
        tr = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
              'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
              'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
              'щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',' ':'-'}
        out = ''.join(tr.get(c.lower(), c.lower()) for c in s)
        return _re.sub(r'[^a-z0-9-]+', '-', out).strip('-')
    region_slug = _make_slug(region_name)

    # Проверяем: нет ли уже такого города
    existing = db.session.execute(
        text("SELECT id FROM cities WHERE slug = :slug OR name = :name"),
        {'slug': slug, 'name': name}
    ).fetchone()
    if existing:
        return jsonify({'error': f'Город с таким именем/slug уже существует (id={existing[0]})'}), 409

    # Находим или создаём регион
    now = datetime.utcnow()
    region_row = db.session.execute(
        text("SELECT id FROM regions WHERE name = :rname LIMIT 1"),
        {'rname': region_name}
    ).fetchone()
    if region_row:
        region_id = region_row[0]
    else:
        rres = db.session.execute(
            text("""
                INSERT INTO regions (name, slug, is_active, is_default, created_at, updated_at)
                VALUES (:rname, :rslug, true, false, :now, :now)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """),
            {'rname': region_name, 'rslug': region_slug, 'now': now}
        )
        db.session.flush()
        region_id = rres.fetchone()[0]

    # Вставляем город в БД (is_active=true — покажется в шапке как только появятся объявления)
    res = db.session.execute(
        text("""
            INSERT INTO cities (name, slug, region_id, is_active, is_default,
                                latitude, longitude, zoom_level,
                                fias_id, name_genitive, name_prepositional,
                                created_at, updated_at)
            VALUES (:name, :slug, :region_id, true, false,
                    :lat, :lon, 12,
                    :fias_id, :name_gen, :name_prep,
                    :now, :now)
            RETURNING id
        """),
        {'name': name, 'slug': slug, 'region_id': region_id,
         'lat': float(lat) if lat else None,
         'lon': float(lon) if lon else None,
         'fias_id': fias_id,
         'name_gen': name_gen, 'name_prep': name_prep, 'now': now}
    )
    db.session.commit()
    new_city_id = res.fetchone()[0]

    # Вычисляем coordinate bounds (±2 градуса вокруг центра)
    lat_f = float(lat) if lat else None
    lon_f = float(lon) if lon else None
    if lat_f and lon_f:
        lat_min = round(lat_f - 2.0, 2)
        lat_max = round(lat_f + 2.0, 2)
        lon_min = round(lon_f - 3.0, 2)
        lon_max = round(lon_f + 3.0, 2)
    else:
        lat_min, lat_max, lon_min, lon_max = 40.0, 80.0, 19.0, 190.0

    # Добавляем в city_config.json (полный набор полей для ensure_city_in_db)
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'city_config.json')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            city_configs = _json.load(f)
    except Exception:
        city_configs = {}

    city_configs[str(new_city_id)] = {
        'name': name,
        'name_en': name_en,
        'slug': slug,
        'cian_region_id': int(cian_region_id),
        'total_pages': total_pages,
        'db_city_id': new_city_id,
        'lat': lat_f or 0,
        'lon': lon_f or 0,
        'lat_min': lat_min, 'lat_max': lat_max,
        'lon_min': lon_min, 'lon_max': lon_max,
        'region_name': region_name,
        'region_slug': region_slug,
    }
    with open(cfg_path, 'w', encoding='utf-8') as f:
        _json.dump(city_configs, f, ensure_ascii=False, indent=2)

    return jsonify({
        'ok': True,
        'city_id': new_city_id,
        'config_key': str(new_city_id),
        'name': name,
        'slug': slug,
        'message': (f'Город «{name}» создан (id={new_city_id}). '
                    f'Запустите парсер: python3 scripts/run_city.py --city {new_city_id} --mode full')
    })


@admin_api_bp.route('/api/admin/cities/<int:city_id>/toggle-active', methods=['POST'])
@admin_required
def api_admin_city_toggle_active(city_id):
    db.session.execute(
        text("UPDATE cities SET is_active = NOT is_active WHERE id = :cid"),
        {'cid': city_id}
    )
    db.session.commit()
    new_val = db.session.execute(
        text("SELECT is_active FROM cities WHERE id = :cid"), {'cid': city_id}
    ).scalar()
    return jsonify({'ok': True, 'is_active': new_val})


@admin_api_bp.route('/api/admin/cities/<int:city_id>/update-pages', methods=['POST'])
@admin_required
def api_admin_city_update_pages(city_id):
    import json as _json
    data = request.get_json() or {}
    pages = int(data.get('total_pages', 30))
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'city_config.json')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            city_configs = _json.load(f)
        if str(city_id) in city_configs:
            city_configs[str(city_id)]['total_pages'] = pages
            with open(cfg_path, 'w', encoding='utf-8') as f:
                _json.dump(city_configs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True, 'total_pages': pages})


@admin_api_bp.route('/api/admin/cities/<int:city_id>/generate-declensions', methods=['POST'])
@admin_required
def api_admin_city_generate_declensions(city_id):
    """Генерирует родительный и предложный падежи названия города через OpenAI."""
    try:
        city = db.session.execute(
            text("SELECT id, name, name_genitive, name_prepositional FROM cities WHERE id = :cid"),
            {'cid': city_id}
        ).fetchone()
        if not city:
            return jsonify({'ok': False, 'error': 'Город не найден'}), 404

        city_name = city[1]
        import openai as _openai
        _openai.api_key = os.environ.get('OPENAI_API_KEY')
        if not _openai.api_key:
            return jsonify({'ok': False, 'error': 'OPENAI_API_KEY не задан'}), 500

        prompt = (
            f"Просклоняй название российского города «{city_name}» по падежам.\n"
            f"Ответь строго в формате JSON без пояснений:\n"
            f'{{"genitive": "...", "prepositional": "..."}}\n'
            f"genitive — родительный (новостройки ЧЕГО? например: Краснодара, Сочи, Тюмени).\n"
            f"prepositional — предложный (квартиры В/ВО ЧЁМ? например: Краснодаре, Сочи, Тюмени)."
        )

        client = _openai.OpenAI(api_key=_openai.api_key)
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': prompt}],
            response_format={'type': 'json_object'},
            max_tokens=60,
            temperature=0
        )
        import json as _json
        result = _json.loads(resp.choices[0].message.content)
        genitive = (result.get('genitive') or '').strip()
        prepositional = (result.get('prepositional') or '').strip()

        if not genitive or not prepositional:
            return jsonify({'ok': False, 'error': 'OpenAI вернул пустой ответ'}), 500

        data_in = request.get_json() or {}
        if data_in.get('save', True):
            db.session.execute(
                text("UPDATE cities SET name_genitive=:gen, name_prepositional=:prep WHERE id=:cid"),
                {'gen': genitive, 'prep': prepositional, 'cid': city_id}
            )
            db.session.commit()

        return jsonify({'ok': True, 'genitive': genitive, 'prepositional': prepositional, 'city_name': city_name})
    except Exception as e:
        db.session.rollback()
        print(f'generate-declensions error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500



@admin_api_bp.route('/api/admin/cities/generate-declensions-preview', methods=['POST'])
@admin_required
def api_admin_city_generate_declensions_preview():
    """Генерирует склонения для произвольного названия (без сохранения) — для модала добавления."""
    try:
        data = request.get_json() or {}
        city_name = (data.get('name') or '').strip()
        if not city_name:
            return jsonify({'ok': False, 'error': 'Название не указано'}), 400

        import openai as _openai
        _openai.api_key = os.environ.get('OPENAI_API_KEY')
        if not _openai.api_key:
            return jsonify({'ok': False, 'error': 'OPENAI_API_KEY не задан'}), 500

        prompt = (
            f"Просклоняй название российского города «{city_name}» по падежам.\n"
            f"Ответь строго в формате JSON без пояснений:\n"
            f'{{"genitive": "...", "prepositional": "..."}}\n'
            f"genitive — родительный (новостройки ЧЕГО? например: Краснодара, Сочи, Тюмени).\n"
            f"prepositional — предложный (квартиры В/ВО ЧЁМ? например: Краснодаре, Сочи, Тюмени)."
        )
        client = _openai.OpenAI(api_key=_openai.api_key)
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': prompt}],
            response_format={'type': 'json_object'},
            max_tokens=60,
            temperature=0
        )
        import json as _json
        result = _json.loads(resp.choices[0].message.content)
        genitive = (result.get('genitive') or '').strip()
        prepositional = (result.get('prepositional') or '').strip()
        return jsonify({'ok': True, 'genitive': genitive, 'prepositional': prepositional})
    except Exception as e:
        print(f'generate-declensions-preview error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@admin_api_bp.route('/api/admin/clients-managers')
@admin_required
def api_admin_clients_managers():
    """Return all users with their assigned managers for client-management page."""
    from models import User, Manager
    from sqlalchemy import text as _t
    try:
        users_raw = db.session.execute(_t(
            "SELECT u.id, u.full_name, u.email, u.phone, u.created_at, "
            "u.assigned_manager_id, u.is_active "
            "FROM users u ORDER BY u.created_at DESC LIMIT 500"
        )).fetchall()

        managers_raw = Manager.query.filter_by(is_active=True).order_by(Manager.first_name).all()

        # Build manager lookup by id
        from sqlalchemy import text as _t2
        from collections import defaultdict
        mgr_client_counts = defaultdict(int)
        counts_raw = db.session.execute(_t2(
            "SELECT assigned_manager_id, COUNT(*) FROM users "
            "WHERE assigned_manager_id IS NOT NULL GROUP BY assigned_manager_id"
        )).fetchall()
        for row in counts_raw:
            mgr_client_counts[row[0]] = row[1]

        mgr_map = {}
        for m in managers_raw:
            mgr_map[m.id] = f"{m.first_name or ''} {m.last_name or ''}".strip() or m.email

        clients = []
        for u in users_raw:
            mid = u[5]
            assigned_manager = None
            if mid and mid in mgr_map:
                assigned_manager = {'id': mid, 'name': mgr_map[mid]}
            clients.append({
                'id': u[0],
                'full_name': u[1] or 'Без имени',
                'email': u[2] or '',
                'phone': u[3] or '',
                'created_at': u[4].strftime('%d.%m.%Y') if u[4] else '',
                'assigned_manager_id': mid,
                'assigned_manager': assigned_manager,
                'is_active': u[6],
            })

        managers = [{
            'id': m.id,
            'name': mgr_map[m.id],
            'assigned_clients_count': mgr_client_counts.get(m.id, 0),
        } for m in managers_raw]

        return jsonify({'success': True, 'clients': clients, 'managers': managers})
    except Exception as e:
        logger.error(f"clients-managers API error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/api/admin/clients-managers/assign', methods=['POST'])
@admin_required
def api_admin_clients_managers_assign():
    """Assign a manager to a user."""
    from sqlalchemy import text as _t
    data = request.get_json() or {}
    user_id = data.get('user_id')
    manager_id = data.get('manager_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    try:
        if manager_id:
            db.session.execute(
                _t("UPDATE users SET assigned_manager_id = :mid WHERE id = :uid"),
                {'mid': int(manager_id), 'uid': int(user_id)}
            )
        else:
            db.session.execute(
                _t("UPDATE users SET assigned_manager_id = NULL WHERE id = :uid"),
                {'uid': int(user_id)}
            )
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication API
# ─────────────────────────────────────────────────────────────────────────────

@admin_api_bp.route('/api/admin/deduplication/find')
@admin_required
def api_dedup_find():
    """Find property duplicates: same address + area + price."""
    from models import Property
    from sqlalchemy import func, text as _t
    try:
        sql = _t("""
            SELECT
                p.address,
                p.area,
                p.price,
                COUNT(*) AS cnt,
                array_agg(p.id ORDER BY p.id) AS ids
            FROM properties p
            WHERE p.is_active = true
              AND p.address IS NOT NULL
              AND p.area IS NOT NULL
              AND p.price IS NOT NULL
            GROUP BY p.address, p.area, p.price
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 500
        """)
        rows = db.session.execute(sql).fetchall()

        groups = []
        for row in rows:
            ids = list(row.ids)
            # Fetch detail rows
            detail_rows = db.session.execute(
                _t("""
                    SELECT p.id, rc.name AS complex_name, p.rooms, p.floor,
                           p.is_active, to_char(p.created_at, 'DD.MM.YYYY') AS created_at
                    FROM properties p
                    LEFT JOIN residential_complexes rc ON rc.id = p.complex_id
                    WHERE p.id = ANY(:ids)
                    ORDER BY p.id
                """),
                {'ids': ids}
            ).fetchall()
            groups.append({
                'address': row.address,
                'area': float(row.area) if row.area else None,
                'price': int(row.price) if row.price else None,
                'ids': ids,
                'rows': [
                    {
                        'id': r.id,
                        'complex_name': r.complex_name,
                        'rooms': r.rooms,
                        'floor': r.floor,
                        'is_active': r.is_active,
                        'created_at': r.created_at,
                    }
                    for r in detail_rows
                ]
            })
        return jsonify({'ok': True, 'groups': groups, 'total': len(groups)})
    except Exception as e:
        logger.exception('dedup find error')
        return jsonify({'ok': False, 'error': str(e)}), 500


@admin_api_bp.route('/api/admin/deduplication/delete', methods=['POST'])
@admin_required
def api_dedup_delete():
    """Delete a list of property IDs (duplicates)."""
    from models import Property
    try:
        data = request.get_json(force=True) or {}
        ids = [int(i) for i in (data.get('ids') or []) if i]
        if not ids:
            return jsonify({'ok': False, 'error': 'No ids provided'}), 400
        if len(ids) > 200:
            return jsonify({'ok': False, 'error': 'Too many ids at once (max 200)'}), 400
        deleted = db.session.query(Property).filter(Property.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': deleted})
    except Exception as e:
        db.session.rollback()
        logger.exception('dedup delete error')
        return jsonify({'ok': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# /admin/nashdom  — детальный просмотр и ручное управление матчингом с наш.дом
# ─────────────────────────────────────────────────────────────────────────────

