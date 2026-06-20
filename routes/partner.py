"""
Partner Blueprint — partner portal routes (/partner/*).
"""
from datetime import datetime

from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_login import current_user, login_required, login_user, logout_user

from app import db, csrf

partner_bp = Blueprint('partner', __name__)


@partner_bp.route('/partner')
@login_required
def partner_cabinet():
    """Standalone partner cabinet page"""
    from models import Referral, UserBalance, Partner
    # Professional partners have their own portal
    if isinstance(current_user, Partner):
        return redirect(url_for('partner.partner_dashboard'))
    if not current_user.referral_code:
        current_user.referral_code = current_user.generate_referral_code()
        db.session.commit()
    referrals = Referral.query.filter_by(referrer_id=current_user.id).order_by(Referral.created_at.desc()).all()
    total_earned = sum(float(r.bonus_amount) for r in referrals)
    user_balance_obj = UserBalance.query.filter_by(user_id=current_user.id).first()
    available_balance = float(user_balance_obj.available_amount) if user_balance_obj and user_balance_obj.available_amount else 0
    referral_link = f"https://inback.ru/login?ref={current_user.referral_code}"
    referrals_data = []
    for r in referrals:
        referrals_data.append({
            'id': r.id,
            'referred_name': (r.referred.full_name or 'Новый пользователь') if r.referred else 'Удалённый пользователь',
            'referred_phone': (r.referred.phone[:7] + '***' + r.referred.phone[-2:]) if r.referred and r.referred.phone else '',
            'bonus_amount': float(r.bonus_amount),
            'status': r.status,
            'created_at': r.created_at.strftime('%d.%m.%Y')
        })
    return render_template('auth/partner_cabinet.html',
        referral_code=current_user.referral_code,
        referral_link=referral_link,
        total_referrals=len(referrals),
        total_earned=total_earned,
        available_balance=available_balance,
        referrals=referrals_data
    )


@partner_bp.route('/partner/login', methods=['GET', 'POST'])
@csrf.exempt
def partner_login():
    from models import Partner
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()
        
        if not phone or not password:
            flash('Заполните все поля', 'error')
            return render_template('partner/login.html')
        
        phone_clean = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        
        from sqlalchemy import func as sqlfunc
        partner = Partner.query.filter(
            sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(Partner.phone, "-", ""), " ", ""), "+", "") == phone_clean
        ).first()
        
        if not partner:
            partner = Partner.query.filter_by(email=phone).first()
        
        if not partner or not partner.is_active:
            flash('Неверные данные для входа', 'error')
            return render_template('partner/login.html')
        
        if not partner.check_password(password):
            flash('Неверные данные для входа', 'error')
            return render_template('partner/login.html')
        
        partner.last_login = datetime.utcnow()
        partner.last_ip = request.remote_addr
        partner.last_user_agent = request.headers.get('User-Agent', '')[:500]
        db.session.commit()
        
        login_user(partner, remember=True)
        session.permanent = True
        return redirect(url_for('partner.partner_dashboard'))
    
    ref = request.args.get('ref', '')
    if ref:
        session['partner_referral_code'] = ref
    return render_template('partner/login.html', ref=ref)



@partner_bp.route('/partner/register', methods=['GET'])
def partner_register():
    ref = request.args.get('ref', '')
    if ref:
        session['partner_referral_code'] = ref
    return render_template('partner/login.html', ref=ref, open_register=True)



@partner_bp.route('/partner/register/send-code', methods=['POST'])
@csrf.exempt
def partner_register_send_code():
    from models import Partner, PhoneVerification
    from sms_service import sms_service
    import logging
    logger = logging.getLogger(__name__)
    
    data = request.get_json() if request.is_json else {}
    phone = data.get('phone', '').strip()
    
    if not phone:
        return jsonify({'success': False, 'message': 'Введите номер телефона'})
    
    phone_clean = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    
    from sqlalchemy import func as sqlfunc
    existing_partner = Partner.query.filter(
        sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(Partner.phone, "-", ""), " ", ""), "+", "") == phone_clean
    ).first()
    
    if existing_partner:
        return jsonify({'success': False, 'message': 'Этот номер уже зарегистрирован как партнёр. Используйте вход.'})
    
    verification = PhoneVerification.create_code(
        phone=phone_clean,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )
    db.session.add(verification)
    db.session.commit()
    
    result = sms_service.send_verification_code(phone_clean, verification.code)
    
    if result['success']:
        session['partner_registration_phone'] = phone_clean
        return jsonify({'success': True, 'message': 'Код подтверждения отправлен', 'code': verification.code})
    else:
        return jsonify({'success': False, 'message': f'Ошибка отправки SMS: {result["message"]}'})



@partner_bp.route('/partner/register/verify-code', methods=['POST'])
@csrf.exempt
def partner_register_verify_code():
    from models import PhoneVerification
    
    data = request.get_json() if request.is_json else {}
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    
    if not phone or not code:
        return jsonify({'success': False, 'message': 'Неверные данные'})
    
    phone_clean = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    
    verification = PhoneVerification.query.filter_by(
        phone=phone_clean,
        code=code
    ).order_by(PhoneVerification.created_at.desc()).first()
    
    if not verification:
        return jsonify({'success': False, 'message': 'Неверный код подтверждения'})
    
    if not verification.is_valid():
        return jsonify({'success': False, 'message': 'Код подтверждения истёк. Запросите новый.'})
    
    verification.attempts += 1
    verification.is_verified = True
    verification.verified_at = datetime.utcnow()
    db.session.commit()
    
    session['partner_verified_phone'] = phone_clean
    return jsonify({'success': True, 'message': 'Код подтверждён'})



@partner_bp.route('/partner/register/complete', methods=['POST'])
@csrf.exempt
def partner_register_complete():
    from models import Partner, PartnerReferral
    from sms_service import sms_service
    import secrets
    import string
    import logging
    logger = logging.getLogger(__name__)
    
    data = request.get_json() if request.is_json else {}
    phone = data.get('phone', '').strip()
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()
    
    if not phone or not first_name:
        return jsonify({'success': False, 'message': 'Заполните имя'})
    
    phone_clean = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    
    verified_phone = session.get('partner_verified_phone', '')
    if verified_phone != phone_clean:
        return jsonify({'success': False, 'message': 'Телефон не подтверждён. Пройдите верификацию заново.'})
    
    from sqlalchemy import func as sqlfunc
    existing = Partner.query.filter(
        sqlfunc.replace(sqlfunc.replace(sqlfunc.replace(Partner.phone, "-", ""), " ", ""), "+", "") == phone_clean
    ).first()
    if existing:
        return jsonify({'success': False, 'message': 'Этот номер уже зарегистрирован'})
    
    phone_digits = phone_clean.replace("+", "")
    if len(phone_digits) == 11 and phone_digits.startswith('7'):
        phone_formatted = f"+7-{phone_digits[1:4]}-{phone_digits[4:7]}-{phone_digits[7:9]}-{phone_digits[9:11]}"
    else:
        phone_formatted = phone_clean
    
    temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    
    ref_code = data.get('ref', '') or session.pop('partner_referral_code', '')
    
    try:
        partner = Partner(
            phone=phone_formatted,
            first_name=_capitalize_name(first_name),
            last_name=_capitalize_name(last_name) if last_name else ''
        )
        partner.set_password(temp_password)
        
        referrer = None
        if ref_code:
            ref_code = ref_code.strip().upper()
            referrer = Partner.query.filter_by(referral_code=ref_code, is_active=True).first()
            if referrer:
                partner.referred_by_id = referrer.id
                partner.level = (referrer.level or 1) + 1
        
        db.session.add(partner)
        db.session.commit()
        db.session.refresh(partner)
        
        if referrer:
            bonus_amount = Decimal('20000.00')
            referral_record = PartnerReferral(
                partner_id=referrer.id,
                referred_partner_id=partner.id,
                bonus_amount=bonus_amount,
                status='credited',
                level=1,
                credited_at=datetime.utcnow()
            )
            db.session.add(referral_record)
            
            referrer.balance = (referrer.balance or Decimal('0.00')) + bonus_amount
            referrer.total_earned = (referrer.total_earned or Decimal('0.00')) + bonus_amount
            referrer.total_referrals = (referrer.total_referrals or 0) + 1
            
            db.session.commit()
            logger.info(f"Partner referral bonus 20000 credited to partner {referrer.id}")
            
            if referrer.referred_by_id:
                level2_referrer = Partner.query.get(referrer.referred_by_id)
                if level2_referrer and level2_referrer.is_active:
                    level2_bonus = Decimal('5000.00')
                    level2_record = PartnerReferral(
                        partner_id=level2_referrer.id,
                        referred_partner_id=partner.id,
                        bonus_amount=level2_bonus,
                        status='credited',
                        level=2,
                        credited_at=datetime.utcnow()
                    )
                    db.session.add(level2_record)
                    level2_referrer.balance = (level2_referrer.balance or Decimal('0.00')) + level2_bonus
                    level2_referrer.total_earned = (level2_referrer.total_earned or Decimal('0.00')) + level2_bonus
                    db.session.commit()
                    logger.info(f"Level 2 partner referral bonus 5000 credited to partner {level2_referrer.id}")
        
        sms_result = sms_service.send_sms(
            phone=phone_clean,
            message=f"Вы зарегистрированы в партнёрской программе InBack! Ваш пароль: {temp_password}. Ваш партнёрский ID: {partner.partner_id}"
        )
        
        session.pop('partner_verified_phone', None)
        session.pop('partner_registration_phone', None)
        
        login_user(partner, remember=True)
        session.permanent = True
        
        return jsonify({'success': True, 'redirect': url_for('partner.partner_dashboard')})
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating partner: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'Ошибка регистрации: {str(e)}'})



@partner_bp.route('/partner/logout')
def partner_logout():
    logout_user()
    return redirect(url_for('partner.partner_login'))



@partner_bp.route('/partner/dashboard')
@login_required
def partner_dashboard():
    from models import Partner, Manager, PartnerReferral
    if not isinstance(current_user, Partner):
        return redirect(url_for('partner.partner_login'))
    
    referral_link = f"https://inback.ru/partner/register?ref={current_user.referral_code}"
    
    assigned_manager = None
    if getattr(current_user, 'assigned_manager_id', None):
        assigned_manager = Manager.query.get(current_user.assigned_manager_id)
    
    # Referral stats
    all_refs = PartnerReferral.query.filter_by(partner_id=current_user.id).all()
    refs_pending = sum(1 for r in all_refs if r.status == 'pending')
    refs_credited = sum(1 for r in all_refs if r.status == 'credited')
    total_pending_amount = sum(r.bonus_amount for r in all_refs if r.status == 'pending')
    
    return render_template('partner/dashboard.html',
        partner=current_user,
        referral_link=referral_link,
        assigned_manager=assigned_manager,
        refs_pending=refs_pending,
        refs_credited=refs_credited,
        total_pending_amount=total_pending_amount,
    )



@partner_bp.route('/partner/api/stats')
@login_required
def partner_api_stats():
    from models import Partner, PartnerReferral
    if not isinstance(current_user, Partner):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    direct_referrals = PartnerReferral.query.filter_by(partner_id=current_user.id, level=1).count()
    level2_referrals = PartnerReferral.query.filter_by(partner_id=current_user.id, level=2).count()
    
    return jsonify({
        'success': True,
        'balance': float(current_user.balance or 0),
        'total_earned': float(current_user.total_earned or 0),
        'total_referrals': current_user.total_referrals or 0,
        'direct_referrals': direct_referrals,
        'level2_referrals': level2_referrals,
        'level': current_user.level or 1,
        'partner_id': current_user.partner_id,
        'referral_code': current_user.referral_code
    })



@partner_bp.route('/partner/api/referrals')
@login_required
def partner_api_referrals():
    from models import Partner, PartnerReferral
    if not isinstance(current_user, Partner):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    referrals = PartnerReferral.query.filter_by(partner_id=current_user.id).order_by(PartnerReferral.created_at.desc()).all()
    
    result = []
    for r in referrals:
        ref_data = {
            'id': r.id,
            'bonus_amount': float(r.bonus_amount),
            'status': r.status,
            'level': r.level,
            'created_at': r.created_at.strftime('%d.%m.%Y') if r.created_at else ''
        }
        if r.referred_partner_id:
            rp = Partner.query.get(r.referred_partner_id)
            if rp:
                ref_data['name'] = rp.full_name
                ref_data['phone'] = rp.phone[:7] + '***' + rp.phone[-2:] if rp.phone and len(rp.phone) > 9 else '***'
            else:
                ref_data['name'] = 'Удалённый партнёр'
                ref_data['phone'] = '***'
        elif r.referred_user_id:
            from models import User
            ru = User.query.get(r.referred_user_id)
            if ru:
                ref_data['name'] = ru.full_name or 'Покупатель'
                ref_data['phone'] = ru.phone[:7] + '***' + ru.phone[-2:] if ru.phone and len(ru.phone) > 9 else '***'
            else:
                ref_data['name'] = 'Удалённый пользователь'
                ref_data['phone'] = '***'
        else:
            ref_data['name'] = 'Неизвестный'
            ref_data['phone'] = '***'
        result.append(ref_data)
    
    return jsonify({'success': True, 'referrals': result})



@partner_bp.route('/partner/api/withdrawal', methods=['POST'])
@login_required
@csrf.exempt
def partner_api_withdrawal():
    from models import Partner, PartnerWithdrawal
    if not isinstance(current_user, Partner):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    data = request.get_json() if request.is_json else {}
    amount = data.get('amount')
    payment_method = data.get('payment_method', '').strip()
    payment_details = data.get('payment_details', '').strip()
    
    if not amount or not payment_method or not payment_details:
        return jsonify({'success': False, 'message': 'Заполните все поля'})
    
    try:
        amount = Decimal(str(amount))
    except:
        return jsonify({'success': False, 'message': 'Некорректная сумма'})
    
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Сумма должна быть больше 0'})
    
    if amount < Decimal('1000'):
        return jsonify({'success': False, 'message': 'Минимальная сумма вывода: 1 000 ₽'})
    
    current_balance = current_user.balance or Decimal('0.00')
    if amount > current_balance:
        return jsonify({'success': False, 'message': 'Недостаточно средств на балансе'})
    
    pending_withdrawals = PartnerWithdrawal.query.filter_by(
        partner_id=current_user.id,
        status='pending'
    ).count()
    
    if pending_withdrawals > 0:
        return jsonify({'success': False, 'message': 'У вас уже есть заявка на вывод в обработке'})
    
    withdrawal = PartnerWithdrawal(
        partner_id=current_user.id,
        amount=amount,
        payment_method=payment_method,
        payment_details=payment_details
    )
    db.session.add(withdrawal)
    
    current_user.balance = current_balance - amount
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Заявка на вывод создана'})



@partner_bp.route('/partner/api/withdrawals')
@login_required
def partner_api_withdrawals():
    from models import Partner, PartnerWithdrawal
    if not isinstance(current_user, Partner):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    withdrawals = PartnerWithdrawal.query.filter_by(partner_id=current_user.id).order_by(PartnerWithdrawal.created_at.desc()).all()
    
    status_labels = {
        'pending': 'На рассмотрении',
        'approved': 'Одобрена',
        'rejected': 'Отклонена',
        'completed': 'Выполнена'
    }
    
    result = []
    for w in withdrawals:
        result.append({
            'id': w.id,
            'amount': float(w.amount),
            'status': w.status,
            'status_label': status_labels.get(w.status, w.status),
            'payment_method': w.payment_method,
            'payment_details': w.payment_details,
            'created_at': w.created_at.strftime('%d.%m.%Y %H:%M') if w.created_at else '',
            'processed_at': w.processed_at.strftime('%d.%m.%Y %H:%M') if w.processed_at else '',
            'admin_comment': w.admin_comment or ''
        })
    
    return jsonify({'success': True, 'withdrawals': result})



@partner_bp.route('/partner/api/structure')
@login_required
def partner_api_structure():
    from models import Partner, PartnerReferral
    if not isinstance(current_user, Partner):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    direct = Partner.query.filter_by(referred_by_id=current_user.id).all()
    
    structure = {'level1': [], 'level2': []}
    
    for p in direct:
        p_data = {
            'id': p.id,
            'name': p.full_name,
            'phone': p.phone[:7] + '***' + p.phone[-2:] if p.phone and len(p.phone) > 9 else '***',
            'partner_id': p.partner_id,
            'joined': p.created_at.strftime('%d.%m.%Y') if p.created_at else '',
            'referrals_count': Partner.query.filter_by(referred_by_id=p.id).count()
        }
        structure['level1'].append(p_data)
        
        sub_partners = Partner.query.filter_by(referred_by_id=p.id).all()
        for sp in sub_partners:
            structure['level2'].append({
                'id': sp.id,
                'name': sp.full_name,
                'phone': sp.phone[:7] + '***' + sp.phone[-2:] if sp.phone and len(sp.phone) > 9 else '***',
                'partner_id': sp.partner_id,
                'joined': sp.created_at.strftime('%d.%m.%Y') if sp.created_at else '',
                'parent_name': p.full_name
            })
    
    return jsonify({'success': True, 'structure': structure})



@partner_bp.route('/partner/api/request-manager', methods=['POST'])
@login_required
@csrf.exempt
def partner_api_request_manager():
    from models import Partner
    if not isinstance(current_user, Partner):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    if getattr(current_user, 'assigned_manager_id', None):
        return jsonify({'success': False, 'message': 'Менеджер уже назначен'})

    message = (request.get_json() or {}).get('message', '').strip()

    # Save request to DB so admin can see it
    try:
        from models import PartnerManagerRequest
        from app import db
        req = PartnerManagerRequest(
            partner_id=current_user.id,
            message=message or None,
            status='pending'
        )
        db.session.add(req)
        db.session.commit()
    except Exception as e:
        current_app.logger.warning(f'Failed to save manager request to DB: {e}')

    try:
        from email_service import send_email
        admin_emails = ['admin@inback.ru']
        body = f"""
Партнёр запросил назначение персонального менеджера.

ID партнёра: {current_user.partner_id}
Имя: {current_user.full_name}
Телефон: {current_user.phone}
Email: {current_user.email or '—'}
Реферальный код: {current_user.referral_code}
Рефералов: {current_user.total_referrals or 0}
Заработано: {float(current_user.total_earned or 0):,.0f} ₽

Сообщение: {message or 'Не указано'}

Назначьте менеджера: https://inback.ru/admin/partners
"""
        for email in admin_emails:
            send_email(email, f'[InBack] Запрос менеджера от партнёра {current_user.partner_id}', body)
    except Exception as e:
        current_app.logger.warning(f'Failed to send manager request email: {e}')

    return jsonify({'success': True, 'message': 'Запрос отправлен! Менеджер свяжется с вами в течение 1 рабочего дня.'})



@partner_bp.route('/partner/profile', methods=['GET', 'POST'])
@login_required
def partner_profile():
    from models import Partner
    if not isinstance(current_user, Partner):
        return redirect(url_for('partner.partner_login'))
    
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        errors = []
        
        if not first_name:
            errors.append('Укажите имя')
        if not last_name:
            errors.append('Укажите фамилию')
        
        if email:
            existing = Partner.query.filter(Partner.email == email, Partner.id != current_user.id).first()
            if existing:
                errors.append('Этот email уже используется другим партнёром')
        
        if new_password:
            if len(new_password) < 6:
                errors.append('Пароль должен содержать минимум 6 символов')
            if new_password != confirm_password:
                errors.append('Пароли не совпадают')
        
        if errors:
            return render_template('partner/profile.html',
                partner=current_user,
                errors=errors
            )
        
        current_user.first_name = _capitalize_name(first_name)
        current_user.last_name = _capitalize_name(last_name)
        current_user.email = email if email else current_user.email
        
        if new_password:
            current_user.set_password(new_password)
        
        db.session.commit()
        
        return render_template('partner/profile.html',
            partner=current_user,
            success='Профиль успешно обновлён'
        )
    
    return render_template('partner/profile.html',
        partner=current_user
    )


# END PARTNER SYSTEM ROUTES

