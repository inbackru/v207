"""
routes/auth.py — Authentication routes: login, register, logout, profile (extracted from app.py)

Imports use the same lazy-wrapper pattern as other blueprints to avoid circular imports.
"""
import re as _re
from datetime import datetime

from flask import (Blueprint, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for, current_app)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from app import csrf, db, require_json_csrf, manager_required, admin_required

def _capitalize_name(name):
    from app import _capitalize_name as _cap
    return _cap(name)



bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
@csrf.exempt
def login():
    """Login page - Phone + Password authentication"""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if current_user.is_authenticated:
        if is_ajax:
            return jsonify({'success': True, 'redirect': url_for('index')})
        return redirect(url_for('index'))
    
    ref_code = request.args.get('ref')
    if ref_code:
        session['referral_code'] = ref_code
    
    if request.method == 'POST':
        from models import User
        import re
        
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
        
        if not phone or not password:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Заполните все поля'})
            flash('Заполните все поля', 'error')
            return render_template('auth/login.html')
        
        # Normalize phone number (remove all non-digits except +)
        phone_clean = re.sub(r'[^\d+]', '', phone)
        if phone_clean.startswith('8'):
            phone_clean = '+7' + phone_clean[1:]
        elif not phone_clean.startswith('+7'):
            phone_clean = '+7' + phone_clean
        
        # Validate phone format
        if len(phone_clean) != 12:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Неверный формат номера телефона'})
            flash('Неверный формат номера телефона', 'error')
            return render_template('auth/login.html')
        
        # OPTIMIZED: Use SQL REPLACE to normalize phone (O(1) query instead of O(n) loop)
        # SECURITY FIX: Check user exists BEFORE password validation to prevent timing attacks
        phone_digits_only = phone_clean.replace("+", "").replace("-", "").replace(" ", "")
        user = User.query.filter(
            func.replace(func.replace(func.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits_only
        ).first()
        
        # SECURITY: Reject non-existent users BEFORE checking password (prevent information leakage)
        if not user:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Неверный номер телефона или пароль'})
            flash('Неверный номер телефона или пароль', 'error')
            return render_template('auth/login.html')
        
        # Check if user is blocked
        if not user.is_active:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Ваш аккаунт заблокирован. Обратитесь в службу поддержки.'})
            flash('Ваш аккаунт заблокирован. Обратитесь в службу поддержки.', 'error')
            return render_template('auth/login.html')

        # User exists - now check password
        password_valid = user.check_password(password)
        if not password_valid:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Неверный пароль'})
            flash('Неверный номер телефона или пароль', 'error')
            return render_template('auth/login.html')
        
        # Authentication successful
        # Clear manager session data if exists
        session.pop('manager_id', None)
        session.pop('is_manager', None)
        
        login_user(user, remember=remember)
        session.permanent = True  # Ensure 30-day session lifetime
        user.last_login = datetime.utcnow()
        user.last_ip = request.remote_addr
        user.last_user_agent = request.headers.get('User-Agent')
        db.session.commit()
        
        try:
            from services.guest_session import merge_guest_to_user
            merge_guest_to_user(user.id, db.session)
        except Exception as e:
            print(f'Guest merge error: {e}')
        
        # Redirect to next page or homepage
        next_page = request.args.get('next')
        redirect_url = next_page if next_page else url_for('index')
        
        if is_ajax:
            return jsonify({'success': True, 'redirect': redirect_url})
        return redirect(redirect_url)
    
    return render_template('auth/login.html')
@bp.route('/setup-password', methods=['GET', 'POST'])
def setup_password():
    """Setup password for users created by managers"""
    temp_user_id = session.get('temp_user_id')
    if not temp_user_id:
        flash('Сессия истекла', 'error')
        return redirect(url_for('auth.login'))
    
    from models import User
    user = User.query.get(temp_user_id)
    if not user or not user.needs_password_setup():
        flash('Пользователь не найден или пароль уже установлен', 'error')
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not password or not confirm_password:
            flash('Заполните все поля', 'error')
            return render_template('auth/setup_password.html', user=user)
        
        if len(password) < 8:
            flash('Пароль должен содержать минимум 8 символов', 'error')
            return render_template('auth/setup_password.html', user=user)
        
        if password != confirm_password:
            flash('Пароли не совпадают', 'error')
            return render_template('auth/setup_password.html', user=user)
        
        # Set password
        user.set_password(password)
        user.is_verified = True
        db.session.commit()
        
        # Clear temp session and manager data
        session.pop('temp_user_id', None)
        session.pop('manager_id', None)
        session.pop('is_manager', None)
        
        # Login user
        login_user(user)
        session.permanent = True  # Ensure 30-day session lifetime
        user.last_login = datetime.utcnow()
        user.last_ip = request.remote_addr
        user.last_user_agent = request.headers.get('User-Agent')
        db.session.commit()
        
        try:
            from services.guest_session import merge_guest_to_user
            merge_guest_to_user(user.id, db.session)
        except Exception as e:
            print(f'Guest merge error: {e}')
        
        flash('Пароль успешно установлен!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('auth/setup_password.html', user=user)

# ================================
# PHONE REGISTRATION ROUTES (Two-step)
# ================================

@bp.route('/register', methods=['GET'])
def register():
    """Step 1: Phone registration page"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    # Clear any old registration session data to allow fresh start
    session.pop('registration_phone', None)
    session.pop('registration_user_id', None)
    session.pop('phone_verified', None)
    
    ref_code = request.args.get('ref')
    if ref_code:
        session['referral_code'] = ref_code
    
    return render_template('auth/register_phone.html')

@bp.route('/api/check-phone', methods=['POST'])
@csrf.exempt
@require_json_csrf
def check_phone():
    """API endpoint to check if phone number exists in database"""
    try:
        data = request.get_json()
        phone = data.get('phone', '').strip()
        
        if not phone:
            return jsonify({"error": "Номер телефона не указан", "status": 400}), 400
        
        # Normalize phone number (remove all non-digits except +)
        import re
        phone_clean = re.sub(r'[^\d+]', '', phone)
        
        # Check if phone starts with +7 or 8
        if phone_clean.startswith('8'):
            phone_clean = '+7' + phone_clean[1:]
        elif not phone_clean.startswith('+7'):
            phone_clean = '+7' + phone_clean
        
        # Validate format: must be +7XXXXXXXXXX (12 characters)
        if len(phone_clean) != 12:
            return jsonify({"error": "Неверный формат номера телефона", "status": 400}), 400
        
        # Check if user exists - normalize database phone for comparison
        from models import User
        from sqlalchemy import func
        
        # Search by normalized phone (remove all non-digits except +)
        # ✅ OPTIMIZED: Use SQL REPLACE to normalize phone in database (O(1) query instead of O(n) loop)
        # Remove spaces, hyphens, and + from both sides for comparison
        phone_digits_only = phone_clean.replace("+", "").replace("-", "").replace(" ", "")
        user = User.query.filter(
            func.replace(func.replace(func.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits_only
        ).first()
        
        return jsonify({
            "exists": user is not None,
            "phone": phone_clean,
            "status": 200
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error checking phone: {e}")
        return jsonify({"error": "Внутренняя ошибка сервера", "status": 500}), 500


@bp.route('/register/send-code', methods=['POST'])
@csrf.exempt  # Allow JSON requests without CSRF token
def register_send_code():
    """Send SMS verification code for registration - with full error logging"""
    import traceback
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        return _register_send_code_impl()
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"CRITICAL ERROR in register_send_code: {str(e)}")
        logger.error(f"Full traceback: {error_trace}")
        print(f"CRITICAL ERROR in register_send_code: {str(e)}")
        print(f"Full traceback: {error_trace}")
        return jsonify({'success': False, 'message': f'Внутренняя ошибка: {str(e)}'}), 500


def _register_send_code_impl():
    """Send SMS verification code for registration"""
    from models import PhoneVerification
    from sms_service import sms_service
    import logging
    
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("📱 /register/send-code called")

    # Check if this is an AJAX request
    is_ajax = request.headers.get('Accept') == 'application/json' or request.is_json
    
    try:
        # Support both JSON and form data
        if request.is_json:
            data = request.get_json()
            phone = data.get('phone', '').strip()
            logger.info(f"📥 JSON request - phone: {phone}")
        else:
            phone = request.form.get('phone', '').strip()
            logger.info(f"📥 Form request - phone: {phone}")
    except Exception as e:
        logger.error(f"❌ Error reading request data: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Ошибка обработки запроса'})
    
    # Format phone: remove all non-digits
    phone_clean = ''.join(filter(str.isdigit, phone))
    logger.info(f"🔢 Phone digits extracted: {phone_clean}")
    
    # Add +7 prefix if needed
    if phone_clean.startswith('8'):
        phone_clean = '7' + phone_clean[1:]
        logger.info(f"✏️ Converted 8 -> 7: {phone_clean}")
    elif phone_clean.startswith('9'):
        phone_clean = '7' + phone_clean
        logger.info(f"✏️ Added 7 prefix: {phone_clean}")
    
    # ✅ STRICT VALIDATION: Enforce 11-digit Russian phone format starting with 7
    logger.info(f"🔍 Validating phone: length={len(phone_clean)}, starts_with_7={phone_clean.startswith('7')}")
    if len(phone_clean) != 11 or not phone_clean.startswith('7'):
        logger.warning(f"❌ Phone validation failed: {phone_clean}")
        if request.is_json:
            return jsonify({'success': False, 'message': 'Неверный формат номера телефона'})
        flash('Неверный формат номера телефона', 'error')
        return redirect(url_for('auth.register'))
    
    logger.info('🚦 Checking rate limiting...')
    # Check rate limiting
    try:
        can_send = PhoneVerification.can_send_code(phone_clean, rate_limit_seconds=60)
        logger.info(f'✅ Rate limit check result: {can_send}')
    except Exception as e:
        logger.error(f'❌ Rate limit check failed: {e}', exc_info=True)
        can_send = True  # Allow on error
    
    if not can_send:
        logger.warning(f'🚫 Rate limit exceeded for {phone_clean}')
        # Calculate exact remaining seconds for client countdown
        try:
            from datetime import timedelta
            _recent = PhoneVerification.query.filter(
                PhoneVerification.phone == phone_clean,
                PhoneVerification.created_at > datetime.utcnow() - timedelta(seconds=60)
            ).order_by(PhoneVerification.created_at.desc()).first()
            _elapsed = (datetime.utcnow() - _recent.created_at).total_seconds() if _recent else 0
            _remaining = max(1, int(60 - _elapsed))
        except Exception:
            _remaining = 60
        if is_ajax:
            return jsonify({'success': False, 'rate_limited': True, 'remaining_seconds': _remaining, 'message': f'Подождите {_remaining} секунд перед повторной отправкой.'})
        flash(f'Слишком много запросов. Пожалуйста, подождите {_remaining} секунд.', 'error')
        return redirect(url_for('auth.register'))
    
    logger.info('👤 Checking if user exists...')
    # Check if user already registered - search by clean phone number
    from models import User
    from sqlalchemy import func as sqlfunc
    
    # Use SQL normalization to find existing users - normalize BOTH stored phone and incoming phone
    existing_user = User.query.filter(
        sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_clean
    ).first()
    
    if existing_user:
        logger.warning(f"⚠️ User already exists with phone: {phone_clean} (stored as: {existing_user.phone})")
        if request.is_json:
            return jsonify({'success': False, 'message': 'Этот номер телефона уже зарегистрирован. Используйте вход по SMS.'})
        flash('Этот номер телефона уже зарегистрирован. Используйте вход по SMS.', 'error')
        return redirect(url_for('auth.register'))
    else:
        logger.info(f"✅ Phone {phone_clean} is NOT registered - allowing registration")
    
    # Check if user already exists
    from models import User
    from sqlalchemy import func
    # ✅ FIX: Use SQL-based normalization to match phones with dashes in database
    phone_digits_only = phone_clean.replace("+", "").replace("-", "").replace(" ", "")
    existing_user = User.query.filter(
        sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits_only
    ).first()
    if existing_user:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Пользователь с таким номером уже зарегистрирован'})
        flash('Пользователь с таким номером уже зарегистрирован', 'error')
        return redirect(url_for('auth.login'))
    
    logger.info('🔐 Creating verification code...')
    # Create verification code
    verification = PhoneVerification.create_code(
        phone=phone_clean,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )
    db.session.add(verification)
    db.session.commit()
    
    logger.info(f'📨 Sending SMS to {phone_clean}...')
    # Send SMS
    result = sms_service.send_verification_code(phone_clean, verification.code)
    
    if result['success']:
        # Store phone in session for verification step
        session['registration_phone'] = phone_clean
        if is_ajax:
            return jsonify({'success': True, 'message': 'Код подтверждения отправлен на ваш телефон', 'code': verification.code})
        flash('Код подтверждения отправлен на ваш телефон', 'success')
    else:
        if is_ajax:
            return jsonify({'success': False, 'message': f'Ошибка отправки SMS: {result["message"]}'})
        flash(f'Ошибка отправки SMS: {result["message"]}', 'error')
    
    return redirect(url_for('auth.register'))

@csrf.exempt  # Allow session reset
@bp.route('/register/reset', methods=['POST', 'GET'])
def register_reset():
    """Reset registration session"""
    session.pop('registration_phone', None)
    session.pop('registration_user_id', None)
    flash('Начните регистрацию заново', 'info')
    return redirect(url_for('auth.register'))

@bp.route('/register/verify-code', methods=['POST'])
@csrf.exempt
def register_verify_code():
    """Verify SMS code, create user with temp password, auto-login and redirect to dashboard"""
    print("[VERIFY_CODE] 🔴 ФУНКЦИЯ ВЫЗВАНА!", flush=True)
    
    from models import PhoneVerification, User
    from sms_service import sms_service
    import secrets
    import string
    import logging
    
    logger = logging.getLogger(__name__)
    print("[VERIFY_CODE] Логирование инициализировано", flush=True)
    
    # Support both JSON and form data
    try:
        if request.is_json:
            print(f"[VERIFY_CODE] Checking if request is JSON: {request.is_json}", flush=True)
            print(f"[VERIFY_CODE] Calling request.get_json()...", flush=True)
            data = request.get_json()
            print(f"[VERIFY_CODE] get_json() returned successfully", flush=True)
            phone = data.get('phone')
            code_raw = data.get('code', '').strip() if data.get('code') else None
            code = code_raw if code_raw else ''
            print(f"[VERIFY_CODE] code_raw={code_raw}, final code={code}", flush=True)
            print(f"[VERIFY_CODE] Получена JSON просьба: phone={phone}, code={code}", flush=True)
        else:
            phone = session.get('registration_phone')
            code = request.form.get('code', '').strip()
    except Exception as e:
        print(f"[VERIFY_CODE] ❌ EXCEPTION: {str(e)}", flush=True)
        logger.error(f"[VERIFY_CODE] Error parsing request: {str(e)}", exc_info=True)
        if request.is_json:
            return jsonify({'success': False, 'message': f'Ошибка парсинга: {str(e)}'}), 500
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('auth.register'))
    
    # If phone not provided in request, try to get from session
    if not phone:
        phone = session.get('registration_phone')
    
    if not phone or not code:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Неверные данные'})
        flash('Неверные данные', 'error')
        return redirect(url_for('auth.register'))
    
    # ✅ NORMALIZE phone format BEFORE searching - remove all formatting
    phone_clean = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    logger.info(f"📱 Incoming phone: {phone}")
    logger.info(f"📱 Cleaned phone: {phone_clean}")
    logger.info(f"🔑 Incoming code: {code}")
    
    # Find valid verification code using cleaned phone
    verification = PhoneVerification.query.filter_by(
        phone=phone_clean,
        code=code
    ).order_by(PhoneVerification.created_at.desc()).first()
    
    # Debug: Log all PhoneVerification records for this phone
    if not verification:
        all_records = PhoneVerification.query.filter_by(phone=phone_clean).all()
        logger.warning(f"❌ No verification found for phone={phone_clean}, code={code}")
        # Debug: Check what IS in the database
        all_phv = PhoneVerification.query.all()
        logger.warning(f"📋 ALL PhoneVerification records in DB: count={len(all_phv)}")
        for pvr in all_phv[-5:]:  # Show last 5
            logger.warning(f"   - phone={pvr.phone} code={pvr.code} created={pvr.created_at}")
        logger.warning(f"📋 Total records for this phone: {len(all_records)}")
        for rec in all_records:
            logger.warning(f"   - Record ID={rec.id}, phone={rec.phone}, code={rec.code}, verified={rec.is_verified}, expires={rec.expires_at}, attempts={rec.attempts}")
        
        if request.is_json:
            return jsonify({'success': False, 'message': 'Неверный код подтверждения'})
        flash('Неверный код подтверждения', 'error')
        return redirect(url_for('auth.register'))
    
    if not verification.is_valid():
        error_msg = 'Код подтверждения истек. Запросите новый код.'
        if verification.is_verified:
            error_msg = 'Код уже был использован'
        elif not verification.is_expired():
            error_msg = 'Превышено количество попыток ввода кода'
        
        if request.is_json:
            return jsonify({'success': False, 'message': error_msg})
        flash(error_msg, 'error')
        return redirect(url_for('auth.register'))
    
    # Increment attempts
    verification.attempts += 1
    
    # Mark as verified
    verification.is_verified = True
    verification.verified_at = datetime.utcnow()
    
    # Format phone to database format: +7-XXX-XXX-XX-XX
    from sqlalchemy import func
    phone_digits_only = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    
    # ✅ STRICT VALIDATION: Enforce 11-digit Russian phone format
    if len(phone_digits_only) != 11 or not phone_digits_only.startswith('7'):
        logger.error(f"❌ Invalid phone format: {phone} (digits: {phone_digits_only})")
        if request.is_json:
            return jsonify({'success': False, 'message': 'Неверный формат номера телефона'})
        flash('Неверный формат номера телефона', 'error')
        return redirect(url_for('auth.register'))
    
    # Format: +7-XXX-XXX-XX-XX (canonical database format)
    phone_formatted = f"+7-{phone_digits_only[1:4]}-{phone_digits_only[4:7]}-{phone_digits_only[7:9]}-{phone_digits_only[9:11]}"
    
    logger.info(f"📞 Phone formatting: {phone} -> {phone_formatted}")
    
    logger.info('👤 Checking if user exists...')
    # Check if user already registered - search by clean phone number
    from models import User
    from sqlalchemy import func as sqlfunc
    
    # Use SQL normalization to find existing users - normalize BOTH stored phone and incoming phone
    existing_user = User.query.filter(
        sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_clean
    ).first()
    
    if existing_user:
        logger.warning(f"⚠️ User already exists with phone: {phone_clean} (stored as: {existing_user.phone})")
        if request.is_json:
            return jsonify({'success': False, 'message': 'Этот номер телефона уже зарегистрирован. Используйте вход по SMS.'})
        flash('Этот номер телефона уже зарегистрирован. Используйте вход по SMS.', 'error')
        return redirect(url_for('auth.register'))
    else:
        logger.info(f"✅ Phone {phone_clean} is NOT registered - allowing registration")
    
    logger.info('🔍 Executing user lookup query...')
    # Check if user already exists (incomplete profile) - use SQL normalization
    user = None
    try:
        logger.debug(f"📋 Querying user with phone={phone_digits_only}")
        user = User.query.filter(
            sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits_only
        ).first()
        logger.debug(f"✅ User lookup complete. Found user={user is not None}")
    except Exception as e:
        logger.error(f"❌ Database error during user lookup: {e}", exc_info=True)
    
    logger.info(f"🔴 ABOUT TO CREATE USER - phone_formatted={phone_formatted}, phone_clean={phone_clean}")
    
    if not user:
        # Create user with temporary password
        # Generate temporary password (8 characters: letters + digits)
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        
        try:
            logger.info(f"👤 Creating User object with phone={phone_formatted}, verified=True")
            user = User(
                phone=phone_formatted,  # ✅ Use formatted phone (required field)
                phone_verified=True,
                is_verified=True,  # Auto-verify on registration
                profile_completed=False
            )
            logger.info(f"✅ User object created successfully")
        except Exception as e:
            logger.error(f"❌ ERROR instantiating User: {str(e)}", exc_info=True)
            if request.is_json:
                return jsonify({'success': False, 'message': f'Ошибка при создании пользователя: {str(e)}'}), 500
            flash(f'Ошибка при создании пользователя: {str(e)}', 'error')
            return redirect(url_for('auth.register'))
        user.set_password(temp_password)
        db.session.add(user)
        user.must_change_password = True  # Требуется смена временного пароля
        
        logger.info(f"✅ Creating new user with temp password: {phone}")
        
        # Save first to get user.id
        try:
            db.session.commit()
            db.session.refresh(user)  # 🔧 CRITICAL FIX #1: Refresh user after commit
        except Exception as e:
            logger.error(f"❌ Error creating user: {str(e)}", exc_info=True)
            db.session.rollback()
            if request.is_json:
                return jsonify({'success': False, 'message': f'Ошибка при создании пользователя: {str(e)}'})
            flash(f'Ошибка при создании пользователя: {str(e)}', 'error')
            return redirect(url_for('auth.register'))
        
        # Grant 10,000₽ registration bonus
        from models import UserBalance, BalanceTransaction
        from decimal import Decimal
        
        try:
            # Create user balance
            logger.info(f"🔧 Creating UserBalance for user {user.id}")
            user_balance = UserBalance(
                user_id=user.id,
                available_amount=Decimal('10000.00'),
                pending_amount=Decimal('0.00'),
                total_earned=Decimal('10000.00'),
                total_withdrawn=Decimal('0.00')
            )
            db.session.add(user_balance)
            
            # Create bonus transaction
            logger.info(f"🔧 Creating BalanceTransaction for user {user.id}")
            bonus_transaction = BalanceTransaction(
                user_id=user.id,
                amount=Decimal('10000.00'),
                transaction_type='registration_bonus',
                description='Приветственный бонус за регистрацию',
                balance_before=Decimal('0.00'),
                balance_after=Decimal('10000.00'),
                status='completed',
                processed_at=datetime.utcnow()
            )
            db.session.add(bonus_transaction)
            
            logger.info(f"💾 Committing UserBalance + BalanceTransaction...")
            db.session.commit()
            db.session.refresh(user)  # 🔧 CRITICAL FIX #2: Refresh user after balance commit
            logger.info(f"✅ Granted 10,000₽ registration bonus to user {user.id}")
        except Exception as e:
            logger.error(f"💥 ERROR creating balance/transaction: {str(e)}", exc_info=True)
            db.session.rollback()
            if request.is_json:
                return jsonify({'success': False, 'message': f'Ошибка при создании баланса: {str(e)}'}), 500
            flash(f'Ошибка при создании баланса: {str(e)}', 'error')
            return redirect(url_for('auth.register'))
        
        try:
            ref_code = session.pop('referral_code', None)
            if ref_code:
                ref_code = ref_code.strip().upper()
                from models import Referral
                existing_referral = Referral.query.filter_by(referred_id=user.id).first()
                referrer = User.query.filter_by(referral_code=ref_code).first() if not existing_referral else None
                if referrer and referrer.id != user.id:
                    # Создаём реферальную запись со статусом 'pending'.
                    # Бонус 20 000 ₽ будет начислен пригласившему ТОЛЬКО когда
                    # приглашённый пользователь успешно завершит сделку.
                    referral = Referral(
                        referrer_id=referrer.id,
                        referred_id=user.id,
                        bonus_amount=Decimal('20000.00'),
                        status='pending',
                    )
                    db.session.add(referral)
                    user.referred_by_id = referrer.id
                    db.session.commit()
                    logger.info(f"✅ Referral record created (pending) for referrer {referrer.id} → new user {user.id}")
        except Exception as e:
            logger.error(f"⚠️ Error processing referral record: {str(e)}", exc_info=True)
            db.session.rollback()
        
        # Send temporary password via SMS
        logger.info(f"📤 Sending temp password via SMS to {phone}")
        sms_result = sms_service.send_sms(
            phone=phone,
            message=f"Ваш временный пароль для входа в InBack: {temp_password}. Измените его в личном кабинете."
        )
        
        if not sms_result['success']:
            logger.warning(f"⚠️ Failed to send temp password SMS: {sms_result['message']}")
            # Don't fail registration, just log warning
        else:
            logger.info(f"✅ Temp password SMS sent successfully")
    else:
        # Update existing incomplete user - regenerate and send temp password
        logger.info(f"User {user.id} already exists with profile_completed={user.profile_completed}")
        
        if user.profile_completed:
            # User already fully registered - should use login instead
            logger.warning(f"Attempted re-registration of completed user {user.id}")
            if request.is_json:
                return jsonify({'success': False, 'message': 'Пользователь с таким номером уже зарегистрирован. Используйте вход.'})
            flash('Пользователь с таким номером уже зарегистрирован. Используйте вход.', 'error')
            return redirect(url_for('auth.login'))
        
        # Generate NEW temporary password for incomplete profile
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        user.set_password(temp_password)
        user.phone_verified = True
        user.must_change_password = True  # Требуется смена временного пароля
        
        # ✅ Check if user has balance - if not, grant registration bonus (migrated users)
        existing_balance = UserBalance.query.filter_by(user_id=user.id).first()
        if not existing_balance:
            logger.info(f"🎁 Migrated user {user.id} has no balance - granting registration bonus")
            
            # Clear stale telegram_id from migration
            if user.telegram_id and not user.profile_completed:
                logger.info(f"🧹 Clearing stale telegram_id for migrated user {user.id}")
                user.telegram_id = None
            
            # Create user balance
            user_balance = UserBalance(
                user_id=user.id,
                available_amount=Decimal('10000.00'),
                pending_amount=Decimal('0.00'),
                total_earned=Decimal('10000.00'),
                total_withdrawn=Decimal('0.00')
            )
            db.session.add(user_balance)
            
            # Create bonus transaction
            bonus_transaction = BalanceTransaction(
                user_id=user.id,
                amount=Decimal('10000.00'),
                transaction_type='registration_bonus',
                description='Приветственный бонус за регистрацию',
                balance_before=Decimal('0.00'),
                balance_after=Decimal('10000.00'),
                status='completed',
                processed_at=datetime.utcnow()
            )
            db.session.add(bonus_transaction)
            
            # Update legacy balance fields
            user.balance = Decimal('10000.00')
            user.registration_bonus = Decimal('10000.00')
            
            logger.info(f"✅ Granted 10,000₽ registration bonus to migrated user {user.id}")
        
        try:
            db.session.commit()
            db.session.refresh(user)  # FIX: Refresh after update
            logger.info(f"✅ Updated existing user {user.id} with new temp password")
            db.session.refresh(user)  # 🔧 CRITICAL FIX #3: Refresh existing user after update
        except Exception as e:
            logger.error(f"❌ Error updating user: {str(e)}", exc_info=True)
            db.session.rollback()
            if request.is_json:
                return jsonify({'success': False, 'message': f'Ошибка при обновлении пользователя: {str(e)}'})
            flash(f'Ошибка при обновлении пользователя: {str(e)}', 'error')
            return redirect(url_for('auth.register'))
        
        # Send temporary password via SMS
        logger.info(f"📤 Sending NEW temp password via SMS to {phone} for existing user {user.id}")
        sms_result = sms_service.send_sms(
            phone=phone,
            message=f"Ваш новый временный пароль для входа в InBack: {temp_password}. Измените его в личном кабинете."
        )
        
        if not sms_result['success']:
            logger.warning(f"⚠️ Failed to send temp password SMS: {sms_result['message']}")
            # Don't fail registration, just log warning
        else:
            logger.info(f"✅ Temp password SMS sent successfully to existing user {user.id}")

        db.session.refresh(user)  # 🔧 CRITICAL FIX #4: Final refresh before login
    logger.info(f"✅ Auto-logging in user: {user.id}")
    login_user(user, remember=True)
    
    try:
        from services.guest_session import merge_guest_to_user
        merge_guest_to_user(user.id, db.session)
    except Exception as e:
        print(f'Guest merge error: {e}')
    
    # Clean up session
    session.pop('registration_phone', None)
    session.pop('registration_user_id', None)
    
    # Redirect to dashboard (modal will show automatically if profile_completed=False)
    logger.info(f"✅ Registration complete, redirecting to dashboard")
    
    if request.is_json:
        return jsonify({'success': True, 'redirect': url_for('dashboard')})
    
    flash('Добро пожаловать! Временный пароль отправлен вам в SMS. Завершите профиль в личном кабинете.', 'success')
    return redirect(url_for('dashboard'))



@bp.route('/register/complete', methods=['GET'])
def register_complete():
    """Step 2: Complete profile form"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    # Check if user has verified phone
    user_id = session.get('registration_user_id')
    if not user_id:
        flash('Сначала подтвердите номер телефона', 'error')
        return redirect(url_for('auth.register'))
    
    from models import User
    user = User.query.get(user_id)
    if not user or not user.phone_verified:
        flash('Неверная сессия регистрации', 'error')
        return redirect(url_for('auth.register'))
    
    return render_template('auth/register_profile.html', user=user)

@bp.route('/register/complete', methods=['POST'])
def register_complete_post():
    """Complete profile and activate account (Step 2 complete)"""
    from models import User, BalanceTransaction
    from decimal import Decimal
    
    # Check session
    user_id = session.get('registration_user_id')
    if not user_id:
        flash('Сессия регистрации истекла', 'error')
        return redirect(url_for('auth.register'))
    
    user = User.query.get(user_id)
    if not user or not user.phone_verified:
        flash('Неверная сессия регистрации', 'error')
        return redirect(url_for('auth.register'))
    
    # Get form data
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    telegram_id = request.form.get('telegram_id', '').strip()
    password = request.form.get('password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    terms = request.form.get('terms')
    
    # Validation
    if not all([full_name, password, confirm_password, terms]):
        flash('Заполните все обязательные поля', 'error')
        return redirect(url_for('auth.register_complete'))
    
    if password != confirm_password:
        flash('Пароли не совпадают', 'error')
        return redirect(url_for('auth.register_complete'))
    
    if len(password) < 8:
        flash('Пароль должен содержать минимум 8 символов', 'error')
        return redirect(url_for('auth.register_complete'))
    
    # Check if email already used (if provided)
    if email:
        existing_email_user = User.query.filter_by(email=email).first()
        if existing_email_user and existing_email_user.id != user.id:
            flash('Пользователь с таким email уже существует', 'error')
            return redirect(url_for('auth.register_complete'))
    
    try:
        # Update user profile
        user.full_name = _capitalize_name(full_name)
        user.email = email if email else None
        user.telegram_id = telegram_id if telegram_id else None
        user.set_password(password)
        user.profile_completed = True
        
        # Grant registration bonus (idempotent check)
        existing_bonus = BalanceTransaction.query.filter_by(
            user_id=user.id,
            transaction_type='registration_bonus'
        ).first()
        
        if not existing_bonus:
            bonus_amount = Decimal('10000.00')
            balance_before = user.balance or Decimal('0')
            
            user.balance = balance_before + bonus_amount
            user.registration_bonus = (user.registration_bonus or Decimal('0')) + bonus_amount
            user.total_earned = (user.total_earned or Decimal('0')) + bonus_amount
            
            balance_after = user.balance
            
            transaction = BalanceTransaction(
                user_id=user.id,
                amount=bonus_amount,
                transaction_type='registration_bonus',
                description='Приветственный бонус за регистрацию',
                balance_before=balance_before,
                balance_after=balance_after,
                status='completed',
                processed_at=datetime.utcnow()
            )
            db.session.add(transaction)
        
        db.session.commit()
        
        # Clear session
        session.pop('registration_user_id', None)
        
        # Login user
        login_user(user)
        user.last_login = datetime.utcnow()
        user.last_ip = request.remote_addr
        user.last_user_agent = request.headers.get('User-Agent')
        db.session.commit()
        
        flash('Регистрация завершена! Добро пожаловать в InBack!', 'success')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        db.session.rollback()
        print(f"Profile completion error: {e}")
        flash(f'Ошибка при завершении регистрации: {str(e)}', 'error')
        return redirect(url_for('auth.register_complete'))

# ================================
# PHONE LOGIN ROUTES
# ================================

@bp.route('/login/send-code', methods=['POST'])
def login_send_code():
    """Send SMS code for phone login"""
    from models import PhoneVerification, User
    from sms_service import sms_service
    
    phone = request.form.get('phone', '').strip()
    
    # Format phone
    phone_clean = ''.join(filter(str.isdigit, phone))
    
    if phone_clean.startswith('8'):
        phone_clean = '7' + phone_clean[1:]
    elif phone_clean.startswith('9'):
        phone_clean = '7' + phone_clean
    elif not phone_clean.startswith('7'):
        return jsonify({'success': False, 'message': 'Неверный формат номера телефона'})
    
    # Check if user exists
    user = User.query.filter_by(phone=phone_clean).first()
    if not user or not user.profile_completed:
        return jsonify({'success': False, 'message': 'Пользователь с таким номером не найден'})
    
    logger.info('🚦 Checking rate limiting...')
    # Check rate limiting
    if not PhoneVerification.can_send_code(phone_clean, rate_limit_seconds=60):
        return jsonify({'success': False, 'message': 'Слишком много запросов. Подождите 60 секунд.'})
    
    logger.info('🔐 Creating verification code...')
    # Create verification code
    verification = PhoneVerification.create_code(
        phone=phone_clean,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )
    db.session.add(verification)
    db.session.commit()
    
    # Send SMS
    result = sms_service.send_login_code(phone_clean, verification.code)
    
    if result['success']:
        session['login_phone'] = phone_clean
        return jsonify({'success': True, 'message': 'Код отправлен на ваш телефон'})
    else:
        return jsonify({'success': False, 'message': f'Ошибка отправки SMS: {result["message"]}'})

@bp.route('/login/verify-code', methods=['POST'])
def login_verify_code():
    """Verify SMS code and login user"""
    from models import PhoneVerification, User
    
    phone = session.get('login_phone')
    code = request.form.get('code', '').strip()
    
    if not phone or not code:
        return jsonify({'success': False, 'message': 'Неверные данные'})
    
    # Find valid verification code
    verification = PhoneVerification.query.filter_by(
        phone=phone,
        code=code
    ).order_by(PhoneVerification.created_at.desc()).first()
    
    if not verification:
        return jsonify({'success': False, 'message': 'Неверный код подтверждения'})
    
    if not verification.is_valid():
        if verification.is_expired():
            return jsonify({'success': False, 'message': 'Код истек. Запросите новый код.'})
        elif verification.is_verified:
            return jsonify({'success': False, 'message': 'Код уже был использован'})
        else:
            return jsonify({'success': False, 'message': 'Превышено количество попыток'})
    
    # Increment attempts
    verification.attempts += 1
    verification.is_verified = True
    verification.verified_at = datetime.utcnow()
    
    # Find user
    user = User.query.filter_by(phone=phone).first()
    if not user:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Пользователь не найден'})
    
    
    # Check if user is blocked
    if not user.is_active:
        db.session.commit()
        return jsonify({'success': False, 'message': 'Ваш аккаунт заблокирован. Обратитесь в службу поддержки.'})
    db.session.commit()
    
    # Clear manager session data if exists
    session.pop('manager_id', None)
    session.pop('is_manager', None)
    session.pop('login_phone', None)
    
    # Login user
    login_user(user)
    user.last_login = datetime.utcnow()
    user.last_ip = request.remote_addr
    user.last_user_agent = request.headers.get('User-Agent')
    db.session.commit()
    
    return jsonify({'success': True, 'redirect': url_for('dashboard')})


@bp.route('/api/send-reset-code', methods=['POST'])
@csrf.exempt
@require_json_csrf
def api_send_reset_code():
    """Send password reset SMS code"""
    from models import PhoneVerification, User
    from sms_service import sms_service
    import logging
    
    logger = logging.getLogger(__name__)
    
    data = request.get_json()
    phone = data.get('phone', '').strip()
    
    if not phone:
        return jsonify({'success': False, 'message': 'Введите номер телефона'})
    
    # Normalize phone number
    phone_clean = ''.join(filter(str.isdigit, phone))
    if phone_clean.startswith('8'):
        phone_clean = '7' + phone_clean[1:]
    elif phone_clean.startswith('9'):
        phone_clean = '7' + phone_clean
    
    # ✅ STRICT VALIDATION: Enforce 11-digit Russian phone format
    if len(phone_clean) != 11 or not phone_clean.startswith('7'):
        return jsonify({'success': False, 'message': 'Неверный формат номера телефона'})
    
    # Check if user exists with this phone
    # ✅ FIX: Use SQL-based normalization to match phones with dashes in database
    phone_digits_only = phone_clean.replace("+", "").replace("-", "").replace(" ", "")
    user = User.query.filter(
        sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits_only
    ).first()
    if not user:
        # For security, don't reveal if user exists or not
        return jsonify({'success': False, 'message': 'Пользователь с таким номером не найден'})
    
    # Rate limiting check (60 seconds cooldown)
    if not PhoneVerification.can_send_code(phone_clean, rate_limit_seconds=60):
        return jsonify({'success': False, 'message': 'Код уже отправлен. Попробуйте через минуту.'})
    
    logger.info('🔐 Creating verification code...')
    # Create verification code (4 digits for password reset)
    verification = PhoneVerification.create_code(
        phone=phone_clean,
        purpose='password_reset',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )
    
    db.session.add(verification)
    
    try:
        db.session.commit()
        
        # Send code via Telegram Gateway (fallback to SMS)
        result = sms_service.send_code_with_fallback(
            phone_clean,
            verification.code,
            f'Ваш код для сброса пароля InBack: {verification.code}. Код действителен 2 минуты.'
        )
        
        if result['success']:
            logger.info(f"✅ Password reset code sent to {phone_clean[:2]}****{phone_clean[-4:]}")
            return jsonify({'success': True, 'message': 'Код отправлен на ваш номер'})
        else:
            logger.error(f"❌ Failed to send reset code: {result['message']}")
            return jsonify({'success': False, 'message': result['message']})
            
    except Exception as e:
        logger.error(f"❌ Error sending reset code: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Ошибка отправки кода. Попробуйте позже.'})


@bp.route('/api/verify-reset-code', methods=['POST'])
@csrf.exempt
@require_json_csrf
def api_verify_reset_code():
    """Verify password reset code and generate reset token"""
    from models import PhoneVerification
    import secrets
    import logging
    
    logger = logging.getLogger(__name__)
    
    data = request.get_json()
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    
    if not phone or not code:
        return jsonify({'success': False, 'message': 'Введите номер телефона и код'})
    
    # Normalize phone number
    phone_clean = ''.join(filter(str.isdigit, phone))
    if phone_clean.startswith('8'):
        phone_clean = '7' + phone_clean[1:]
    elif phone_clean.startswith('9'):
        phone_clean = '7' + phone_clean
    
    # Find verification code
    verification = PhoneVerification.query.filter_by(
        phone=phone_clean,
        code=code,
        purpose='password_reset'
    ).order_by(PhoneVerification.created_at.desc()).first()
    
    if not verification:
        return jsonify({'success': False, 'message': 'Неверный код подтверждения'})
    
    # Increment attempts
    verification.increment_attempts()
    db.session.commit()
    
    # Check if valid
    if not verification.is_valid():
        error_msg = 'Код подтверждения истек. Запросите новый код.'
        if verification.is_verified:
            error_msg = 'Код уже был использован'
        elif not verification.is_expired():
            error_msg = 'Превышено количество попыток ввода кода'
        return jsonify({'success': False, 'message': error_msg})
    
    # Mark as verified
    verification.mark_verified()
    db.session.commit()
    
    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    
    # Save in session
    session['reset_token'] = reset_token
    session['reset_phone'] = phone_clean
    session.modified = True
    
    logger.info(f"✅ Password reset code verified for {phone_clean[:2]}****{phone_clean[-4:]}")
    
    return jsonify({
        'success': True,
        'message': 'Код подтвержден',
        'redirect': url_for('auth.reset_password')
    })


@bp.route('/forgot-password', methods=['GET'])
def forgot_password():
    """Forgot password page"""
    return render_template('auth/forgot_password.html')


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Reset password page"""
    from models import User
    from werkzeug.security import generate_password_hash
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Validate reset token from session
    reset_token = session.get('reset_token')
    reset_phone = session.get('reset_phone')
    
    if not reset_token or not reset_phone:
        flash('Недействительная ссылка для сброса пароля', 'error')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        # Validation
        if not password:
            flash('Введите новый пароль', 'error')
            return render_template('auth/reset_password.html')
        
        if len(password) < 6:
            flash('Пароль должен быть не менее 6 символов', 'error')
            return render_template('auth/reset_password.html')
        
        if password != confirm_password:
            flash('Пароли не совпадают', 'error')
            return render_template('auth/reset_password.html')
        
        # Find user
        # ✅ FIX: Use SQL-based normalization to match phones with dashes in database
        phone_digits_only = reset_phone.replace("+", "").replace("-", "").replace(" ", "")
        user = User.query.filter(
            func.replace(func.replace(func.replace(User.phone, "-", ""), " ", ""), "+", "") == phone_digits_only
        ).first()
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('auth.forgot_password'))
        
        # Update password
        user.password_hash = generate_password_hash(password)
        
        try:
            db.session.commit()
            
            # Clear session tokens
            session.pop('reset_token', None)
            session.pop('reset_phone', None)
            
            # Auto-login user
            login_user(user)
            
            logger.info(f"✅ Password reset successful for user {user.id}")
            flash('Пароль успешно изменен!', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            logger.error(f"❌ Error resetting password: {str(e)}", exc_info=True)
            db.session.rollback()
            flash('Ошибка при изменении пароля. Попробуйте позже.', 'error')
            return render_template('auth/reset_password.html')
    
    # GET request - show form
    return render_template('auth/reset_password.html')

@bp.route('/logout')
@login_required
def logout():
    """Logout user - ИСПРАВЛЕНО: очищает ВСЕ сессии"""
    logout_user()  # Flask-Login logout
    
    # Очищаем все ручные сессии (legacy код)
    session.pop('manager_id', None)
    session.pop('admin_id', None)
    session.pop('is_manager', None)
    session.pop('is_admin', None)
    session.pop('user_id', None)
    session.pop('temp_user_id', None)
    
    flash('Вы успешно вышли из системы', 'success')
    return redirect(url_for('public_api.index'))

@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page - now integrated into dashboard settings tab"""
    
    if request.method == 'POST':
        try:
            # Update profile information
            current_user.full_name = _capitalize_name(request.form.get('full_name', current_user.full_name))
            current_user.telegram_id = request.form.get('telegram_id', current_user.telegram_id)
            
            # Update date of birth
            date_of_birth_str = request.form.get('date_of_birth')
            if date_of_birth_str:
                try:
                    from datetime import datetime
                    current_user.date_of_birth = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            
            # Update password if provided
            new_password = request.form.get('new_password')
            if new_password:
                confirm_password = request.form.get('confirm_password')
                if new_password == confirm_password:
                    current_user.password_hash = generate_password_hash(new_password)
                    flash('Пароль успешно изменен', 'success')
                else:
                    flash('Пароли не совпадают', 'error')
                    return redirect(url_for('dashboard') + '#settings')
            
            db.session.commit()
            flash('Профиль успешно обновлен', 'success')
            return redirect(url_for('dashboard') + '#settings')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при обновлении профиля: {str(e)}', 'error')
            return redirect(url_for('dashboard') + '#settings')
    
    # GET request - redirect to dashboard settings tab
    return redirect(url_for('dashboard') + '#settings')


@bp.route('/api/manager/test-notification', methods=['POST'])
@manager_required
def api_test_manager_notification():
    """Send a test notification to the current manager"""
    from email_service import send_test_manager_notification
    
    results = send_test_manager_notification(
        current_user.email, 
        current_user.telegram_id
    )
    
    if results.get('email') or results.get('telegram'):
        parts = []
        if results.get('email'):
            parts.append('Email')
        if results.get('telegram'):
            parts.append('Telegram')
        return jsonify({'success': True, 'message': f'Уведомление отправлено: {", ".join(parts)}', 'details': results})
    else:
        return jsonify({'success': False, 'error': 'Не удалось отправить уведомление. Проверьте настройки email и Telegram ID.', 'details': results}), 500
  
@bp.route('/api/manager/unlink-telegram', methods=['POST'])
@manager_required
def manager_unlink_telegram():
    """Remove telegram_id from manager account."""
    current_user.telegram_id = None
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/manager/generate-tg-code', methods=['POST'])
@manager_required
def manager_generate_tg_code():
    """Generate a one-time 6-digit code for linking manager account to Telegram bot."""
    import random
    from datetime import timedelta
    from models import Manager
    mgr = current_user
    code = str(random.randint(100000, 999999))
    mgr.tg_link_code = code
    mgr.tg_link_code_expires = datetime.utcnow() + timedelta(minutes=10)
    db.session.commit()
    return jsonify({'success': True, 'code': code, 'expires_in': 600})


@bp.route('/profile/upload-avatar', methods=['POST'])
@login_required
def upload_user_avatar():
    """Upload user avatar"""
    import os
    from werkzeug.utils import secure_filename
    
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    file = request.files['avatar']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    # Check file extension
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    filename = secure_filename(file.filename)
    if '.' not in filename or filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return jsonify({'success': False, 'error': 'Недопустимый формат файла. Разрешены: PNG, JPG, JPEG, GIF, WEBP'}), 400
    
    # Check file size (max 5MB)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > 5 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Размер файла превышает 5MB'}), 400
    
    try:
        # Generate unique filename
        import uuid
        ext = filename.rsplit('.', 1)[1].lower()
        new_filename = f"user_{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
        
        # Save file
        upload_folder = os.path.join('static', 'uploads', 'avatars')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, new_filename)
        file.save(filepath)
        
        # Update user profile_image in database
        avatar_url = f"/static/uploads/avatars/{new_filename}"
        current_user.profile_image = avatar_url
        db.session.commit()
        
        return jsonify({'success': True, 'avatar_url': avatar_url})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при загрузке файла: {str(e)}'}), 500



@bp.route('/api/profile/remove-avatar', methods=['POST'])
@login_required
def remove_user_avatar():
    """Remove user avatar and reset to default"""
    try:
        import os
        old_image = current_user.profile_image
        if old_image and old_image.startswith('/static/uploads/avatars/'):
            old_path = old_image.lstrip('/')
            if os.path.exists(old_path):
                try: os.remove(old_path)
                except: pass
        current_user.profile_image = None
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/profile/request-phone-change', methods=['POST'])
@login_required
def request_phone_change():
    """Запрос на смену номера телефона с SMS верификацией (user/manager/admin)"""
    from models import PhoneChangeRequest, User, Manager, Admin
    from sms_service import sms_service
    
    try:
        if not validate_json_csrf():
            return jsonify({'success': False, 'message': 'Ошибка безопасности. Обновите страницу.'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        new_phone = data.get('new_phone', '').strip()
        if not new_phone:
            return jsonify({'success': False, 'message': 'Укажите новый номер телефона'}), 400
        
        phone_clean = ''.join(filter(str.isdigit, new_phone))
        if phone_clean.startswith('8'):
            phone_clean = '7' + phone_clean[1:]
        elif phone_clean.startswith('9'):
            phone_clean = '7' + phone_clean
        
        if len(phone_clean) != 11 or not phone_clean.startswith('7'):
            return jsonify({'success': False, 'message': 'Неверный формат номера телефона'}), 400
        
        account_type = 'user'
        if isinstance(current_user, Manager):
            account_type = 'manager'
        elif isinstance(current_user, Admin):
            account_type = 'admin'
        
        phone_suffix = phone_clean[-10:]
        existing_user = User.query.filter(User.phone.like(f'%{phone_suffix}%')).first()
        existing_manager = Manager.query.filter(Manager.phone.like(f'%{phone_suffix}%')).first()
        existing_admin = Admin.query.filter(Admin.phone.like(f'%{phone_suffix}%')).first()
        
        if existing_user and not (account_type == 'user' and existing_user.id == current_user.id):
            return jsonify({'success': False, 'message': 'Этот номер телефона уже используется'}), 400
        if existing_manager and not (account_type == 'manager' and existing_manager.id == current_user.id):
            return jsonify({'success': False, 'message': 'Этот номер телефона уже используется'}), 400
        if existing_admin and not (account_type == 'admin' and existing_admin.id == current_user.id):
            return jsonify({'success': False, 'message': 'Этот номер телефона уже используется'}), 400
        
        if not PhoneChangeRequest.can_request_new_code(current_user.id, account_type=account_type, rate_limit_seconds=60):
            return jsonify({'success': False, 'message': 'Подождите 60 секунд перед повторной отправкой кода'}), 429
        
        pending_requests = PhoneChangeRequest.query.filter_by(user_id=current_user.id, account_type=account_type, status='pending').all()
        for req in pending_requests:
            req.mark_expired()
        
        phone_request = PhoneChangeRequest.create_request(current_user.id, phone_clean, account_type=account_type)
        db.session.add(phone_request)
        db.session.commit()
        
        sms_message = f"InBack: Код подтверждения смены номера: {phone_request.verification_code}"
        sms_result = sms_service.send_code_with_fallback(phone_clean, phone_request.verification_code, sms_message)
        
        if sms_result.get('success'):
            logging.info(f"Phone change SMS sent to {phone_clean[:4]}****{phone_clean[-2:]} for {account_type} {current_user.id}")
            return jsonify({
                'success': True,
                'message': 'Код подтверждения отправлен на новый номер',
                'phone': f'+7 (***) ***-**-{phone_clean[-2:]}'
            })
        else:
            phone_request.mark_expired()
            db.session.commit()
            logging.error(f"Failed to send phone change SMS: {sms_result.get('message')}")
            return jsonify({
                'success': False,
                'message': f'Ошибка отправки SMS: {sms_result.get("message", "Неизвестная ошибка")}'
            }), 500
            
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in request_phone_change: {str(e)}")
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500


@bp.route('/api/profile/verify-phone-change', methods=['POST'])
@login_required
def verify_phone_change():
    """Верификация кода и смена номера телефона (user/manager/admin)"""
    from models import PhoneChangeRequest, Manager, Admin
    
    try:
        if not validate_json_csrf():
            return jsonify({'success': False, 'message': 'Ошибка безопасности. Обновите страницу.'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        code = data.get('code', '').strip()
        if not code or len(code) != 6:
            return jsonify({'success': False, 'message': 'Введите 6-значный код'}), 400
        
        account_type = 'user'
        if isinstance(current_user, Manager):
            account_type = 'manager'
        elif isinstance(current_user, Admin):
            account_type = 'admin'
        
        phone_request = PhoneChangeRequest.query.filter_by(
            user_id=current_user.id,
            account_type=account_type,
            status='pending'
        ).order_by(PhoneChangeRequest.created_at.desc()).first()
        
        if not phone_request:
            return jsonify({'success': False, 'message': 'Запрос на смену номера не найден. Запросите код заново.'}), 400
        
        if phone_request.is_expired():
            phone_request.mark_expired()
            db.session.commit()
            return jsonify({'success': False, 'message': 'Код истёк. Запросите новый код.'}), 400
        
        if phone_request.attempts >= phone_request.max_attempts:
            phone_request.mark_expired()
            db.session.commit()
            return jsonify({'success': False, 'message': 'Превышено количество попыток. Запросите новый код.'}), 400
        
        phone_request.increment_attempts()
        
        if code != phone_request.verification_code:
            remaining = phone_request.max_attempts - phone_request.attempts
            db.session.commit()
            return jsonify({
                'success': False,
                'message': f'Неверный код. Осталось попыток: {remaining}'
            }), 400
        
        phone_request.mark_verified()
        current_user.phone = phone_request.new_phone
        if hasattr(current_user, 'phone_verified'):
            current_user.phone_verified = True
        db.session.commit()
        
        logging.info(f"{account_type} {current_user.id} successfully changed phone to {phone_request.new_phone}")
        
        return jsonify({
            'success': True,
            'message': 'Номер телефона успешно изменён',
            'new_phone': phone_request.new_phone
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in verify_phone_change: {str(e)}")
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500



@bp.route('/api/profile/request-email-change', methods=['POST'])
@login_required
def request_email_change():
    """Запрос на смену email с верификацией через ссылку (user/manager/admin)"""
    from models import EmailChangeRequest, User, Manager, Admin
    import re
    
    try:
        if not validate_json_csrf():
            return jsonify({'success': False, 'message': 'Ошибка безопасности. Обновите страницу.'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        new_email = data.get('new_email', '').strip().lower()
        if not new_email:
            return jsonify({'success': False, 'message': 'Укажите новый email'}), 400
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, new_email):
            return jsonify({'success': False, 'message': 'Неверный формат email'}), 400
        
        if current_user.email and current_user.email.lower() == new_email:
            return jsonify({'success': False, 'message': 'Это ваш текущий email'}), 400
        
        account_type = 'user'
        if isinstance(current_user, Manager):
            account_type = 'manager'
        elif isinstance(current_user, Admin):
            account_type = 'admin'
        
        existing_user = User.query.filter(User.email.ilike(new_email)).first()
        existing_manager = Manager.query.filter(Manager.email.ilike(new_email)).first()
        existing_admin = Admin.query.filter(Admin.email.ilike(new_email)).first()
        
        if existing_user and not (account_type == 'user' and existing_user.id == current_user.id):
            return jsonify({'success': False, 'message': 'Этот email уже используется'}), 400
        if existing_manager and not (account_type == 'manager' and existing_manager.id == current_user.id):
            return jsonify({'success': False, 'message': 'Этот email уже используется'}), 400
        if existing_admin and not (account_type == 'admin' and existing_admin.id == current_user.id):
            return jsonify({'success': False, 'message': 'Этот email уже используется'}), 400
        
        if not EmailChangeRequest.can_request_new_token(current_user.id, account_type=account_type, rate_limit_seconds=60):
            return jsonify({'success': False, 'message': 'Слишком много запросов. Подождите минуту.'}), 429
        
        EmailChangeRequest.query.filter_by(
            user_id=current_user.id,
            account_type=account_type,
            status='pending'
        ).update({'status': 'expired'})
        
        email_request = EmailChangeRequest.create_request(current_user.id, new_email, account_type=account_type)
        db.session.add(email_request)
        db.session.commit()
        
        base_url = os.environ.get('REPLIT_DEV_DOMAIN')
        if base_url:
            base_url = f"https://{base_url}"
        else:
            base_url = request.host_url.rstrip('/')
        
        verification_url = f"{base_url}/verify-email-change/{email_request.verification_token}"
        
        email_sent = send_email(
            to_email=new_email,
            subject='InBack: Подтверждение смены email',
            template_name='emails/email_change_verification.html',
            verification_url=verification_url,
            user=current_user,
            base_url=base_url
        )
        
        if not email_sent:
            logging.warning(f"Email not sent to {new_email}, but request created")
        
        logging.info(f"{account_type} {current_user.id} requested email change to {new_email}")
        
        return jsonify({
            'success': True,
            'message': 'Ссылка для подтверждения отправлена на указанный email'
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in request_email_change: {str(e)}")
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500


@bp.route('/verify-email-change/<token>')
def verify_email_change(token):
    """Верификация токена и смена email (user/manager/admin)"""
    from models import EmailChangeRequest, User, Manager, Admin
    
    try:
        email_request = EmailChangeRequest.query.filter_by(
            verification_token=token,
            status='pending'
        ).first()
        
        if not email_request:
            flash('Ссылка недействительна или уже была использована', 'error')
            return redirect(url_for('auth.login'))
        
        if email_request.is_expired():
            email_request.mark_expired()
            db.session.commit()
            flash('Срок действия ссылки истёк. Запросите новую ссылку.', 'error')
            return redirect(url_for('auth.login'))
        
        account_type = email_request.account_type or 'user'
        
        existing_user = User.query.filter(User.email.ilike(email_request.new_email)).first()
        existing_manager = Manager.query.filter(Manager.email.ilike(email_request.new_email)).first()
        existing_admin = Admin.query.filter(Admin.email.ilike(email_request.new_email)).first()
        
        if existing_user and not (account_type == 'user' and existing_user.id == email_request.user_id):
            email_request.mark_expired()
            db.session.commit()
            flash('Этот email уже занят', 'error')
            return redirect(url_for('auth.login'))
        if existing_manager and not (account_type == 'manager' and existing_manager.id == email_request.user_id):
            email_request.mark_expired()
            db.session.commit()
            flash('Этот email уже занят', 'error')
            return redirect(url_for('auth.login'))
        if existing_admin and not (account_type == 'admin' and existing_admin.id == email_request.user_id):
            email_request.mark_expired()
            db.session.commit()
            flash('Этот email уже занят', 'error')
            return redirect(url_for('auth.login'))
        
        if account_type == 'manager':
            account = Manager.query.get(email_request.user_id)
            redirect_url = url_for('mgr.manager_profile')
        elif account_type == 'admin':
            account = Admin.query.get(email_request.user_id)
            redirect_url = url_for('adm.admin_profile')
        else:
            account = User.query.get(email_request.user_id)
            redirect_url = url_for('auth.profile')
        
        if not account:
            flash('Аккаунт не найден', 'error')
            return redirect(url_for('auth.login'))
        
        old_email = account.email
        account.email = email_request.new_email
        email_request.mark_verified()
        db.session.commit()
        
        logging.info(f"{account_type} {email_request.user_id} changed email from {old_email} to {email_request.new_email}")
        
        flash('Email успешно изменён!', 'success')
        
        if current_user.is_authenticated:
            return redirect(redirect_url)
        else:
            return redirect(url_for('auth.login'))
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in verify_email_change: {str(e)}")
        flash('Произошла ошибка при смене email', 'error')
        return redirect(url_for('auth.login'))

@bp.route('/manager/profile/upload-avatar', methods=['POST'])
@manager_required
def upload_manager_avatar():
    """Upload manager avatar"""
    import os
    from werkzeug.utils import secure_filename
    from models import Manager
    
    current_manager = current_user
    
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    file = request.files['avatar']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    # Check file extension
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    filename = secure_filename(file.filename)
    if '.' not in filename or filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return jsonify({'success': False, 'error': 'Недопустимый формат файла. Разрешены: PNG, JPG, JPEG, GIF, WEBP'}), 400
    
    # Check file size (max 5MB)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > 5 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Размер файла превышает 5MB'}), 400
    
    try:
        # Generate unique filename
        import uuid
        ext = filename.rsplit('.', 1)[1].lower()
        new_filename = f"manager_{current_manager.id}_{uuid.uuid4().hex[:8]}.{ext}"
        
        # Save file
        upload_folder = os.path.join('static', 'uploads', 'avatars')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, new_filename)
        file.save(filepath)
        
        # Update manager profile_image in database
        avatar_url = f"/static/uploads/avatars/{new_filename}"
        current_manager.profile_image = avatar_url
        db.session.commit()
        
        return jsonify({'success': True, 'avatar_url': avatar_url})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при загрузке файла: {str(e)}'}), 500



@bp.route('/confirm/<token>')
def confirm_email(token):
    """Email confirmation endpoint"""
    from models import User
    
    try:
        # Find user by verification token
        user = User.query.filter_by(verification_token=token).first()
        
        if not user:
            flash('Неверная или просроченная ссылка подтверждения', 'error')
            return redirect(url_for('auth.login'))
        
        if user.is_verified:
            flash('Ваш аккаунт уже подтвержден', 'info')
            return redirect(url_for('auth.login'))
        
        # Confirm user
        user.is_verified = True
        user.verification_token = None  # Clear the token
        db.session.commit()
        
        # Send welcome email after verification
        try:
            from email_service import send_welcome_email
            send_welcome_email(user, base_url=request.url_root.rstrip('/'))
        except Exception as e:
            print(f"Error sending welcome email: {e}")
        
        flash('Email успешно подтвержден! Теперь вы можете войти в аккаунт.', 'success')
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        print(f"Email confirmation error: {e}")
        flash('Ошибка при подтверждении email', 'error')
        return redirect(url_for('auth.login'))

@bp.route('/resend-verification', methods=['POST'])
@require_json_csrf
def resend_verification():
    """Resend verification email with rate limiting and enhanced security"""
    import re
    from models import User, EmailVerificationAttempt
    
    # Get request data - support both form and JSON
    if request.content_type == 'application/json':
        data = request.get_json() or {}
        email = data.get('email', '').strip().lower()
    else:
        email = request.form.get('email', '').strip().lower()
    
    # Get client info for logging
    ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR'))
    user_agent = request.headers.get('User-Agent', '')[:500]
    
    # Validate email format
    if not email:
        error_msg = 'Введите email для повторной отправки'
        EmailVerificationAttempt.log_attempt(email or 'empty', ip_address, user_agent, False, error_msg)
        if request.content_type == 'application/json':
            return jsonify({'success': False, 'error': error_msg}), 400
        flash(error_msg, 'error')
        return redirect(url_for('auth.login'))
    
    # Basic email format validation
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, email):
        error_msg = 'Введите корректный email адрес'
        EmailVerificationAttempt.log_attempt(email, ip_address, user_agent, False, error_msg)
        if request.content_type == 'application/json':
            return jsonify({'success': False, 'error': error_msg}), 400
        flash(error_msg, 'error')
        return redirect(url_for('auth.login'))
    
    logger.info('🚦 Checking rate limiting...')
    # Check rate limiting (5 minutes between successful attempts)
    if not EmailVerificationAttempt.can_resend_verification(email, rate_limit_minutes=5):
        error_msg = 'Слишком частые запросы. Подождите 5 минут перед повторной отправкой.'
        EmailVerificationAttempt.log_attempt(email, ip_address, user_agent, False, error_msg)
        if request.content_type == 'application/json':
            return jsonify({'success': False, 'error': error_msg}), 429
        flash(error_msg, 'warning')
        return redirect(url_for('auth.login'))
    
    # Check for suspicious activity (more than 10 attempts in 1 hour)
    recent_attempts = EmailVerificationAttempt.get_recent_attempts_count(email, hours=1)
    if recent_attempts >= 10:
        error_msg = 'Превышен лимит попыток. Попробуйте позже или обратитесь в поддержку.'
        EmailVerificationAttempt.log_attempt(email, ip_address, user_agent, False, error_msg)
        if request.content_type == 'application/json':
            return jsonify({'success': False, 'error': error_msg}), 429
        flash(error_msg, 'error')
        return redirect(url_for('auth.login'))
    
    # Find user
    user = User.query.filter_by(email=email).first()
    
    if not user:
        # Don't reveal whether user exists for security
        success_msg = 'Если аккаунт с таким email существует, письмо с подтверждением будет отправлено.'
        EmailVerificationAttempt.log_attempt(email, ip_address, user_agent, False, 'User not found')
        if request.content_type == 'application/json':
            return jsonify({'success': True, 'message': success_msg})
        flash(success_msg, 'info')
        return redirect(url_for('auth.login'))
    
    if user.is_verified:
        error_msg = 'Ваш аккаунт уже подтвержден'
        EmailVerificationAttempt.log_attempt(email, ip_address, user_agent, False, error_msg)
        if request.content_type == 'application/json':
            return jsonify({'success': False, 'error': error_msg}), 400
        flash(error_msg, 'info')
        return redirect(url_for('auth.login'))
    
    # Generate new verification token
    user.verification_token = secrets.token_urlsafe(32)
    db.session.commit()
    
    # Send new verification email
    try:
        from email_service import send_verification_email
        send_verification_email(user, base_url=request.url_root.rstrip('/'))
        
        # Log successful attempt
        EmailVerificationAttempt.log_attempt(email, ip_address, user_agent, True, None)
        
        success_msg = 'Письмо с подтверждением отправлено повторно. Проверьте ваш email.'
        print(f"✅ VERIFICATION RESEND SUCCESS: Email sent to {email} from IP {ip_address}")
        
        if request.content_type == 'application/json':
            return jsonify({'success': True, 'message': success_msg})
        flash(success_msg, 'success')
        
    except Exception as e:
        error_msg = 'Ошибка при отправке письма. Попробуйте позже.'
        EmailVerificationAttempt.log_attempt(email, ip_address, user_agent, False, str(e)[:200])
        print(f"❌ VERIFICATION RESEND ERROR: {e} for email {email}")
        
        if request.content_type == 'application/json':
            return jsonify({'success': False, 'error': error_msg}), 500
        flash(error_msg, 'error')
    
    return redirect(url_for('auth.login'))
