"""
Deals Blueprint — deal management API endpoints for managers.
Endpoints: /api/deals, /api/deals/<id>, /api/deals/<id>/comments,
           /api/deals/<id>/tasks, /api/deals/<id>/documents,
           /api/deals/<id>/reassign, /api/deals/<id>/stage
"""
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db, csrf

logger = logging.getLogger(__name__)

deals_bp = Blueprint('deals', __name__)


# Import decorators at module init time (safe because app is already initialized when registered)
from app import manager_required, require_json_csrf


def _manager_has_director_access(manager):
    """True for ROP or Директор — can see/edit all deals regardless of assignment."""
    if getattr(manager, 'is_rop', False):
        return True
    role = getattr(manager, 'org_role', None)
    return role is not None and getattr(role, 'key', '') in ('rop', 'director')


@deals_bp.route('/api/deals', methods=['POST'])
@manager_required
@require_json_csrf
def api_create_deal():
    """Create new deal (managers only)"""
    from models import Deal, Manager, User, ResidentialComplex
    from decimal import Decimal
    
    try:
        current_manager = current_user
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'Нет данных для обработки'}), 400
        
        # Validation - client_id and price are required
        if 'client_id' not in data or not data['client_id']:
            return jsonify({'success': False, 'error': 'Поле client_id обязательно'}), 400
        if 'property_price' not in data or not data['property_price']:
            return jsonify({'success': False, 'error': 'Поле property_price обязательно'}), 400
        
        # Get complex name from request
        complex_name = data.get('residential_complex_name', '').strip()
        if not complex_name:
            return jsonify({'success': False, 'error': 'Необходимо указать название ЖК'}), 400
        
        # Validate client exists and belongs to this manager
        client_id = int(data['client_id'])
        client = User.query.get(client_id)
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
        
        # Менеджер может создавать сделки для:
        # 1. Своих назначенных клиентов (assigned_manager_id == current_manager.id)
        # 2. Неназначенных клиентов (assigned_manager_id is None)
        if client.assigned_manager_id is not None and client.assigned_manager_id != current_manager.id:
            return jsonify({'success': False, 'error': 'Этот клиент уже назначен другому менеджеру'}), 403
        
        # Validate price and cashback amounts
        try:
            property_price = Decimal(str(data['property_price']))
            cashback_amount = Decimal(str(data['cashback_amount']))
            
            if property_price <= 0:
                return jsonify({'success': False, 'error': 'Стоимость объекта должна быть больше 0'}), 400
            
            if cashback_amount < 0:
                return jsonify({'success': False, 'error': 'Сумма кешбека не может быть отрицательной'}), 400
                
            # Get complex cashback rate for validation
            max_rate = Decimal('0.15')  # Default max 15% cashback
            if cashback_amount > property_price * max_rate:  # Max cashback validation
                return jsonify({'success': False, 'error': f'Сумма кешбека не может превышать {max_rate * 100}% от стоимости объекта'}), 400
                
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Некорректные значения цены или кешбека'}), 400
        
        # Create new deal
        deal = Deal(
            manager_id=current_manager.id,
            client_id=data['client_id'],
            residential_complex_name=complex_name,  # Save complex name as text
            property_price=property_price,
            cashback_amount=cashback_amount,
            property_description=data.get('property_description', ''),
            property_floor=data.get('property_floor'),
            property_area=data.get('property_area'),
            property_rooms=data.get('property_rooms', ''),
            status=data.get('status', 'new'),
            notes=data.get('notes', ''),
            client_notes=data.get('client_notes', '')
        )
        
        db.session.add(deal)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Сделка успешно создана',
            'deal': {
                'id': deal.id,
                'deal_number': deal.deal_number,
                'status': deal.status,
                'status_display': deal.status_display,
                'property_price': float(deal.property_price),
                'cashback_amount': float(deal.cashback_amount),
                'client_name': client.full_name,
                'complex_name': complex_name,
                'created_at': deal.created_at.isoformat()
            }
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error creating deal: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера при создании сделки'}), 500


@deals_bp.route('/api/deals', methods=['GET'])
def api_get_deals():
    """Get list of deals with filtering"""
    from models import Deal, Manager, User, ResidentialComplex
    from flask_login import current_user
    
    print("🤝 DEBUG: /api/deals endpoint called")
    
    try:
        # Check if user is manager or client
        is_manager = current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)
        
        print(f"🤝 DEBUG: is_manager={is_manager}, authenticated={current_user.is_authenticated}")
        
        is_rop = False
        if is_manager:
            # Manager can see all their deals; ROP/director sees all deals
            current_manager = current_user
            is_rop = _manager_has_director_access(current_manager)
            print(f"🤝 DEBUG: Manager ID = {current_manager.id}, Email = {current_manager.email}, is_rop={is_rop}")
            if is_rop:
                deals_query = Deal.query
            else:
                deals_query = Deal.query.filter_by(manager_id=current_manager.id)
        elif current_user.is_authenticated:
            # Client can only see their own deals
            user_id = current_user.id
            print(f"🤝 DEBUG: Client ID = {user_id}")
            deals_query = Deal.query.filter_by(client_id=user_id)
        else:
            # No authentication
            print("🤝 DEBUG: User not authenticated")
            return jsonify({'success': False, 'error': 'Не авторизован'}), 401
        
        # Apply status filtering if provided
        status_filter = request.args.get('status')
        if status_filter:
            status_list = [s.strip() for s in status_filter.split(',') if s.strip()]
            if status_list:
                print(f"🤝 DEBUG: Applying status filter: {status_list}")
                deals_query = deals_query.filter(Deal.status.in_(status_list))
        
        # Order by creation date (newest first)
        deals = deals_query.order_by(Deal.created_at.desc()).all()
        
        print(f"🤝 DEBUG: Found {len(deals)} deals")
        if len(deals) > 0:
            print(f"🤝 DEBUG: First deal: ID={deals[0].id}, Client={deals[0].client.full_name}, Complex={deals[0].residential_complex_name}")
        
        # Format response
        deals_data = []
        for deal in deals:
            deals_data.append({
                'id': deal.id,
                'deal_number': deal.deal_number,
                'status': deal.status,
                'status_display': deal.status_display,
                'status_color': deal.status_color,
                'property_price': float(deal.property_price),
                'cashback_amount': float(deal.cashback_amount),
                'cashback_percentage': deal.get_cashback_percentage(),
                'property_description': deal.property_description,
                'property_floor': deal.property_floor,
                'property_area': deal.property_area,
                'property_rooms': deal.property_rooms,
                'notes': deal.notes,
                'client_notes': deal.client_notes,
                'client_name': deal.client.full_name,
                'client_profile_image': deal.client.profile_image or '',
                'manager_name': deal.manager.full_name,
                'complex_name': deal.residential_complex_name or (deal.residential_complex.name if deal.residential_complex else ''),
                'complex_image': (deal.residential_complex.main_image or '') if deal.residential_complex else '',
                'complex_url': ('/zk/' + deal.residential_complex.slug if deal.residential_complex and deal.residential_complex.slug else ''),
                'contract_date': deal.contract_date.isoformat() if deal.contract_date else None,
                'completion_date': deal.completion_date.isoformat() if deal.completion_date else None,
                'created_at': deal.created_at.isoformat(),
                'updated_at': deal.updated_at.isoformat(),
                'can_edit': deal.can_edit(current_manager.id if is_manager else current_user.id, is_manager, is_rop=is_rop)
            })
        
        print(f"🤝 DEBUG: Returning {len(deals_data)} deals to client")
        
        return jsonify({
            'success': True,
            'deals': deals_data,
            'total': len(deals_data),
            'is_manager': is_manager
        })
        
    except Exception as e:
        print(f"❌ Error getting deals: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Ошибка сервера при получении сделок'}), 500



@deals_bp.route('/api/deals/<int:deal_id>', methods=['GET'])
@login_required
def api_get_deal(deal_id):
    """Get specific deal with access control"""
    from models import Deal, Manager
    
    try:
        deal = Deal.query.get(deal_id)
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        
        # Check access rights
        is_manager = current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)
        _is_rop = False
        current_manager = None
        
        if is_manager:
            current_manager = current_user
            _is_rop = _manager_has_director_access(current_manager)
            if not _is_rop and deal.manager_id != current_manager.id:
                return jsonify({'success': False, 'error': 'Недостаточно прав для просмотра этой сделки'}), 403
        else:
            # Client can only see their own deals
            if deal.client_id != current_user.id:
                return jsonify({'success': False, 'error': 'Недостаточно прав для просмотра этой сделки'}), 403
        
        # Return deal data
        deal_data = {
            'id': deal.id,
            'deal_number': deal.deal_number,
            'status': deal.status,
            'status_display': deal.status_display,
            'status_color': deal.status_color,
            'property_price': float(deal.property_price),
            'cashback_amount': float(deal.cashback_amount),
            'cashback_percentage': deal.get_cashback_percentage(),
            'property_description': deal.property_description,
            'property_floor': deal.property_floor,
            'property_area': deal.property_area,
            'property_rooms': deal.property_rooms,
            'notes': deal.notes,
            'client_notes': deal.client_notes,
            'client_name': deal.client.full_name if deal.client else '',
            'client_profile_image': (deal.client.profile_image or '') if deal.client else '',
            'client_email': deal.client.email if deal.client else '',
            'client_phone': deal.client.phone if deal.client else '',
            'manager_name': deal.manager.full_name if deal.manager else '',
            'manager_email': deal.manager.email if deal.manager else '',
            'manager_phone': deal.manager.phone if deal.manager else '',
            'manager_profile_image': (deal.manager.profile_image if deal.manager and deal.manager.profile_image and 'randomuser.me' not in deal.manager.profile_image else ''),
            'complex_name': deal.residential_complex_name or (deal.residential_complex.name if deal.residential_complex else ''),
            'complex_id': deal.residential_complex.id if deal.residential_complex else None,
            'contract_date': deal.contract_date.isoformat() if deal.contract_date else None,
            'completion_date': deal.completion_date.isoformat() if deal.completion_date else None,
            'created_at': deal.created_at.isoformat(),
            'updated_at': deal.updated_at.isoformat(),
            'can_edit': deal.can_edit(current_manager.id if is_manager else current_user.id, is_manager, is_rop=_is_rop)
        }
        
        return jsonify({
            'success': True,
            'deal': deal_data
        })
        
    except Exception as e:
        print(f"Error getting deal {deal_id}: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера при получении сделки'}), 500


@deals_bp.route('/api/deals/<int:deal_id>', methods=['PUT'])
@csrf.exempt
def api_update_deal(deal_id):
    """Update deal (status, notes)"""
    from models import Deal
    from datetime import datetime, date
    from flask_login import current_user
    
    from models import Manager
    try:
        # Check authentication
        is_manager = current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)
        
        if not is_manager and not current_user.is_authenticated:
            return jsonify({'success': False, 'error': 'Не авторизован'}), 401
        
        deal = Deal.query.get(deal_id)
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Нет данных для обновления'}), 400
        
        if is_manager:
            current_manager = current_user
            _is_rop = _manager_has_director_access(current_manager)
            if not _is_rop and deal.manager_id != current_manager.id:
                return jsonify({'success': False, 'error': 'Недостаточно прав для редактирования этой сделки'}), 403
            
            allowed_fields = ['status', 'notes', 'client_notes', 'property_description', 
                            'property_floor', 'property_area', 'property_rooms', 
                            'contract_date', 'completion_date', 'property_price', 
                            'cashback_amount', 'residential_complex_id', 'residential_complex_name']
        else:
            # Client can only update their own deals and limited fields
            if deal.client_id != current_user.id:
                return jsonify({'success': False, 'error': 'Недостаточно прав для редактирования этой сделки'}), 403
            
            # Client can only update notes and only if deal is in editable status
            if deal.status not in ['new', 'object_reserved']:
                return jsonify({'success': False, 'error': 'Сделка больше не может быть отредактирована'}), 403
            
            allowed_fields = ['client_notes']
        
        # Store old values for logging
        old_status = deal.status
        old_property_price = float(deal.property_price) if deal.property_price else 0
        old_cashback_amount = float(deal.cashback_amount) if deal.cashback_amount else 0
        
        # Update allowed fields
        updated_fields = []
        
        for field in allowed_fields:
            if field in data:
                if field == 'status':
                    # Validate status
                    valid_statuses = ['new', 'in_progress', 'calculation', 'meeting_scheduled', 'meeting_done',
                                       'postponed', 'verbal_reserve', 'reserved', 'documents', 'mortgage',
                                       'ddu_preparation', 'ddu_signing', 'registration', 'receivables',
                                       'completed', 'rejected',
                                       'object_reserved', 'successful']
                    if data[field] not in valid_statuses:
                        return jsonify({'success': False, 'error': f'Недопустимый статус: {data[field]}'}), 400
                    # Save validated status
                    setattr(deal, field, data[field])
                    updated_fields.append(field)
                
                elif field in ['contract_date', 'completion_date']:
                    # Handle date fields
                    if data[field]:
                        try:
                            date_value = datetime.strptime(data[field], '%Y-%m-%d').date()
                            setattr(deal, field, date_value)
                            updated_fields.append(field)
                        except ValueError:
                            return jsonify({'success': False, 'error': f'Некорректный формат даты для {field}. Используйте YYYY-MM-DD'}), 400
                    else:
                        setattr(deal, field, None)
                        updated_fields.append(field)
                
                elif field == 'property_price':
                    # Validate and handle property_price
                    try:
                        price_value = float(data[field])
                        if price_value <= 0:
                            return jsonify({'success': False, 'error': 'Стоимость объекта должна быть больше нуля'}), 400
                        setattr(deal, field, price_value)
                        updated_fields.append(field)
                        current_app.logger.debug(f"💰 Deal #{deal.deal_number}: property_price set to {price_value}")
                    except (ValueError, TypeError):
                        return jsonify({'success': False, 'error': 'Некорректное значение стоимости объекта'}), 400
                
                elif field == 'cashback_amount':
                    # Validate and handle cashback_amount
                    try:
                        cashback_value = float(data[field])
                        if cashback_value < 0:
                            return jsonify({'success': False, 'error': 'Сумма кешбека не может быть отрицательной'}), 400
                        
                        # Check if cashback exceeds property price (use updated property_price if provided, otherwise use current)
                        property_price = float(data.get('property_price', deal.property_price))
                        if cashback_value > property_price:
                            return jsonify({'success': False, 'error': 'Сумма кешбека не может превышать стоимость объекта'}), 400
                        
                        setattr(deal, field, cashback_value)
                        updated_fields.append(field)
                        current_app.logger.debug(f"💰 Deal #{deal.deal_number}: cashback_amount set to {cashback_value}")
                    except (ValueError, TypeError):
                        return jsonify({'success': False, 'error': 'Некорректное значение суммы кешбека'}), 400
                
                else:
                    # Handle text fields
                    setattr(deal, field, data[field])
                    updated_fields.append(field)
        
        if not updated_fields:
            return jsonify({'success': False, 'error': 'Нет полей для обновления'}), 400
        
        deal.updated_at = datetime.utcnow()
        
        if is_manager:
            from models import DealHistory, Deal as DealModel
            current_manager_obj = current_user
            field_labels = {
                'status': 'Этап', 'property_price': 'Стоимость', 'cashback_amount': 'Кешбек',
                'property_description': 'Описание', 'property_floor': 'Этаж', 'property_area': 'Площадь',
                'property_rooms': 'Комнат', 'notes': 'Заметки', 'contract_date': 'Дата договора',
                'completion_date': 'Дата завершения', 'residential_complex_name': 'ЖК'
            }
            if 'status' in updated_fields and old_status != deal.status:
                old_label = DealModel.STAGE_LABELS.get(old_status, old_status)
                new_label = DealModel.STAGE_LABELS.get(deal.status, deal.status)
                history = DealHistory(
                    deal_id=deal.id, author_id=current_manager_obj.id, action='stage_change',
                    field_name='status', old_value=old_label, new_value=new_label,
                    description=f'Этап изменён: {old_label} → {new_label}'
                )
                db.session.add(history)
                try:
                    from models import UserNotification
                    notification_icons = {
                        'new': 'fas fa-star', 'in_progress': 'fas fa-spinner', 'calculation': 'fas fa-calculator',
                        'meeting_scheduled': 'fas fa-calendar-check', 'meeting_done': 'fas fa-handshake',
                        'postponed': 'fas fa-pause-circle', 'verbal_reserve': 'fas fa-comment-dots',
                        'reserved': 'fas fa-bookmark', 'documents': 'fas fa-file-alt', 'mortgage': 'fas fa-university',
                        'ddu_preparation': 'fas fa-file-contract', 'ddu_signing': 'fas fa-pen-fancy',
                        'registration': 'fas fa-stamp', 'receivables': 'fas fa-money-bill-wave',
                        'completed': 'fas fa-check-circle', 'rejected': 'fas fa-times-circle'
                    }
                    notif_type = 'success' if deal.status in ('completed', 'successful') else ('error' if deal.status == 'rejected' else 'info')
                    complex_name = deal.residential_complex_name or (deal.residential_complex.name if deal.residential_complex else '')
                    notif = UserNotification(
                        user_id=deal.client_id,
                        title=f'Сделка {deal.deal_number}: {new_label}',
                        message=f'Статус вашей сделки' + (f' по {complex_name}' if complex_name else '') + f' изменён с «{old_label}» на «{new_label}»',
                        notification_type=notif_type,
                        icon=notification_icons.get(deal.status, 'fas fa-info-circle'),
                        action_url='/dashboard#deals'
                    )
                    db.session.add(notif)
                except Exception as e:
                    current_app.logger.error(f'Failed to create deal notification in PUT: {e}')
            for field in updated_fields:
                if field == 'status':
                    continue
                old_val = str(locals().get(f'old_{field}', ''))
                new_val = str(getattr(deal, field, ''))
                if old_val != new_val:
                    history = DealHistory(
                        deal_id=deal.id, author_id=current_manager_obj.id, action='field_update',
                        field_name=field_labels.get(field, field), old_value=old_val, new_value=new_val,
                        description=f'{field_labels.get(field, field)}: {old_val} → {new_val}'
                    )
                    db.session.add(history)
        
        # Comprehensive logging for financial fields changes
        if is_manager and ('property_price' in updated_fields or 'cashback_amount' in updated_fields):
            current_manager = current_user
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            
            if 'property_price' in updated_fields:
                new_property_price = float(deal.property_price)
                if old_property_price != new_property_price:
                    current_app.logger.info(
                        f"💰 Deal #{deal.deal_number}: property_price changed from "
                        f"{old_property_price:,.2f}₽ to {new_property_price:,.2f}₽ "
                        f"by manager {current_manager.id} ({current_manager.email}) "
                        f"at {timestamp}"
                    )
            
            if 'cashback_amount' in updated_fields:
                new_cashback_amount = float(deal.cashback_amount)
                if old_cashback_amount != new_cashback_amount:
                    current_app.logger.info(
                        f"💰 Deal #{deal.deal_number}: cashback_amount changed from "
                        f"{old_cashback_amount:,.2f}₽ to {new_cashback_amount:,.2f}₽ "
                        f"by manager {current_manager.id} ({current_manager.email}) "
                        f"at {timestamp}"
                    )
        
        db.session.commit()
        
        # 💰 АВТОМАТИЧЕСКОЕ НАЧИСЛЕНИЕ БАЛАНСА ПРИ ЗАВЕРШЕНИИ СДЕЛКИ

        # Helper function для форматирования денег с копейками
        def _format_money_ru(amount):
            """Format Decimal/float as RUB with kopecks: 1 234,56 ₽"""
            from decimal import Decimal, ROUND_HALF_UP
            KOPECK = Decimal('0.01')
            rounded = Decimal(str(amount)).quantize(KOPECK, rounding=ROUND_HALF_UP)
            formatted = f"{rounded:,.2f}".replace(',', ' ').replace('.', ',')
            return f"{formatted} ₽"

        if 'status' in updated_fields and old_status != deal.status and deal.status == 'successful':
            try:
                from services.balance_service import BalanceService
                from models import BalanceTransaction
                
                # Проверить что баланс еще не начислен за эту сделку
                existing_transaction = BalanceTransaction.query.filter_by(
                    deal_id=deal.id,
                    transaction_type='cashback_earned'
                ).first()
                
                if not existing_transaction and deal.cashback_amount > 0:
                    # Начислить кешбек через новую систему балансов
                    transaction = BalanceService.credit_balance(
                        user_id=deal.client_id,
                        amount=deal.cashback_amount,
                        description=f'Кешбек по сделке {deal.deal_number} ({deal.residential_complex_name or "объект"})',
                        transaction_type='cashback_earned',
                        deal_id=deal.id,
                        created_by_id=deal.manager_id
                    )
                    
                    current_app.logger.info(f"✅ Кешбек {deal.cashback_amount}₽ начислен клиенту (user_id={deal.client_id}) за сделку {deal.deal_number}")
                    
                    # Отправить уведомление клиенту о начислении кешбека
                    try:
                        from telegram_bot import send_telegram_message
                        from models import User
                        client = User.query.get(deal.client_id)
                        
                        if client:
                            message = f"🎉 Поздравляем! Вам начислен кешбек {_format_money_ru(deal.cashback_amount)}₽ по сделке {deal.deal_number}.\n\nСредства доступны для вывода в личном кабинете."
                            
                            # Telegram
                            if client.telegram_chat_id:
                                send_telegram_message(client.telegram_chat_id, message)
                            
                            # Email
                            if client.email:
                                email_subject = f"Начислен кешбек {_format_money_ru(deal.cashback_amount)}₽"
                                email_body = f"""
Здравствуйте, {client.full_name or client.email.split('@')[0]}!

Поздравляем! Вам начислен кешбек {_format_money_ru(deal.cashback_amount)}₽ по сделке {deal.deal_number}.

Детали сделки:
- Объект: {deal.residential_complex_name or 'N/A'}
- Стоимость: {_format_money_ru(deal.property_price)}₽
- Кешбек: {_format_money_ru(deal.cashback_amount)}₽

Средства доступны для вывода в личном кабинете.

С уважением,
Команда InBack
"""
                                send_email_notification(client.email, email_subject, email_body)
                                
                            current_app.logger.info(f"✅ Уведомления отправлены клиенту {client.id} о начислении кешбека")
                    except Exception as e:
                        current_app.logger.error(f"Ошибка отправки уведомления о кешбеке: {str(e)}")
                    
            except Exception as e:
                current_app.logger.error(f"❌ Ошибка начисления кешбека для сделки {deal.id}: {str(e)}")
                # НЕ откатываем всю сделку если не удалось начислить баланс
                # Администратор может начислить вручную через админ-панель

            # ── Начислить реферальный бонус пригласившему (если сделка первая) ──
            try:
                from models import Referral, User as UserModel, UserBalance, BalanceTransaction as BT
                client_user = UserModel.query.get(deal.client_id)
                if client_user and client_user.referred_by_id:
                    pending_ref = Referral.query.filter_by(
                        referrer_id=client_user.referred_by_id,
                        referred_id=client_user.id,
                        status='pending'
                    ).first()
                    if pending_ref:
                        bonus = pending_ref.bonus_amount  # 20 000 ₽
                        referrer = UserModel.query.get(client_user.referred_by_id)
                        if referrer:
                            # Начислить бонус через BalanceService
                            BalanceService.credit_balance(
                                user_id=referrer.id,
                                amount=bonus,
                                description=f'Реферальный бонус: {client_user.full_name or client_user.phone} завершил сделку {deal.deal_number}',
                                transaction_type='referral_bonus',
                                deal_id=deal.id,
                                created_by_id=deal.manager_id
                            )
                            # Обновить статус реферала
                            pending_ref.status = 'credited'
                            pending_ref.bonus_credited_at = datetime.utcnow()
                            db.session.commit()
                            current_app.logger.info(
                                f"✅ Реферальный бонус {bonus}₽ начислен пользователю {referrer.id} "
                                f"за реферала {client_user.id} по сделке {deal.deal_number}"
                            )
                            # Уведомить пригласившего
                            try:
                                if referrer.telegram_chat_id:
                                    from telegram_bot import send_telegram_message
                                    send_telegram_message(
                                        referrer.telegram_chat_id,
                                        f"🎉 Ваш реферал {client_user.full_name or 'пользователь'} завершил сделку!\n"
                                        f"Вам начислен бонус {_format_money_ru(bonus)}.\n"
                                        f"Проверьте баланс в личном кабинете."
                                    )
                            except Exception:
                                pass
            except Exception as e:
                current_app.logger.error(f"❌ Ошибка начисления реферального бонуса для сделки {deal.id}: {str(e)}")
        
        # Логируем изменение статуса
        if 'status' in updated_fields and old_status != deal.status:
            from models import UserActivity
            status_display_map = {
                'new': 'Новая',
                'object_reserved': 'Объект зарезервирован',
                'mortgage': 'Ипотека',
                'successful': 'Успешно завершена',
                'rejected': 'Отклонена'
            }
            old_status_display = status_display_map.get(old_status, old_status)
            new_status_display = status_display_map.get(deal.status, deal.status)
            
            # Translate to Russian if it matches internal keys
            if old_status_display in Deal.STAGE_LABELS:
                old_status_display = Deal.STAGE_LABELS[old_status_display]
            if new_status_display in Deal.STAGE_LABELS:
                new_status_display = Deal.STAGE_LABELS[new_status_display]
            
            UserActivity.log_activity(
                user_id=deal.client_id,
                activity_type='deal_status_update',
                description=f'Статус сделки {deal.deal_number} изменен с "{old_status_display}" на "{new_status_display}"'
            )
        
        return jsonify({
            'success': True,
            'message': 'Сделка успешно обновлена',
            'updated_fields': updated_fields,
            'deal': {
                'id': deal.id,
                'deal_number': deal.deal_number,
                'status': deal.status,
                'status_display': deal.status_display,
                'status_color': deal.status_color,
                'property_price': float(deal.property_price),
                'cashback_amount': float(deal.cashback_amount),
                'cashback_percentage': deal.get_cashback_percentage(),
                'property_description': deal.property_description,
                'property_floor': deal.property_floor,
                'property_area': deal.property_area,
                'property_rooms': deal.property_rooms,
                'notes': deal.notes,
                'client_notes': deal.client_notes,
                'client_name': deal.client.full_name,
                'client_profile_image': deal.client.profile_image or '',
                'complex_name': deal.residential_complex_name or (deal.residential_complex.name if deal.residential_complex else ''),
                'contract_date': deal.contract_date.isoformat() if deal.contract_date else None,
                'completion_date': deal.completion_date.isoformat() if deal.completion_date else None,
                'updated_at': deal.updated_at.isoformat()
            }
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating deal {deal_id}: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера при обновлении сделки'}), 500


@deals_bp.route('/api/deals/<int:deal_id>', methods=['DELETE'])
@manager_required
@require_json_csrf
def api_delete_deal(deal_id):
    """Delete deal (managers only)"""
    from models import Deal
    
    try:
        deal = Deal.query.get(deal_id)
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        
        current_manager = current_user
        _is_rop = _manager_has_director_access(current_manager)
        if not _is_rop and deal.manager_id != current_manager.id:
            return jsonify({'success': False, 'error': 'Недостаточно прав для удаления этой сделки'}), 403
        
        # Check if deal can be deleted (only new or rejected deals)
        if deal.status not in ['new', 'rejected']:
            return jsonify({'success': False, 'error': 'Нельзя удалить сделку со статусом "' + deal.status_display + '"'}), 400
        
        deal_number = deal.deal_number
        db.session.delete(deal)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Сделка {deal_number} успешно удалена'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting deal {deal_id}: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера при удалении сделки'}), 500

@deals_bp.route('/api/manager/checkin', methods=['POST'])
@manager_required
def api_manager_checkin():
    from models import ManagerCheckin
    from zoneinfo import ZoneInfo
    moscow_tz = ZoneInfo('Europe/Moscow')
    now_moscow = datetime.now(moscow_tz)
    current_manager = current_user
    today = now_moscow.date()
    active_checkin = ManagerCheckin.query.filter_by(
        manager_id=current_manager.id, date=today, is_active=True
    ).first()
    if active_checkin:
        active_checkin.check_out_time = now_moscow.replace(tzinfo=None)
        active_checkin.is_active = False
        db.session.commit()
        return jsonify({'success': True, 'status': 'checked_out', 'duration': active_checkin.duration_display})
    else:
        checkin = ManagerCheckin(
            manager_id=current_manager.id,
            check_in_time=now_moscow.replace(tzinfo=None),
            date=today,
            is_active=True
        )
        db.session.add(checkin)
        db.session.commit()
        return jsonify({'success': True, 'status': 'checked_in', 'time': checkin.check_in_time.strftime('%H:%M')})

@deals_bp.route('/api/manager/checkin/status')
@manager_required
def api_manager_checkin_status():
    from models import ManagerCheckin
    from zoneinfo import ZoneInfo
    moscow_tz = ZoneInfo('Europe/Moscow')
    now_moscow = datetime.now(moscow_tz)
    current_manager = current_user
    today = now_moscow.date()
    active_checkin = ManagerCheckin.query.filter_by(
        manager_id=current_manager.id, date=today, is_active=True
    ).first()
    if active_checkin:
        return jsonify({'success': True, 'is_checked_in': True, 'since': active_checkin.check_in_time.strftime('%H:%M'), 'duration': active_checkin.duration_display, 'checked_in_at': active_checkin.check_in_time.isoformat()})
    return jsonify({'success': True, 'is_checked_in': False})

@deals_bp.route('/api/deals/<int:deal_id>/comments', methods=['POST'])
@csrf.exempt
@manager_required
def api_deal_add_comment(deal_id):
    from models import Deal, DealComment, DealHistory
    current_manager = current_user
    deal = Deal.query.get(deal_id)
    if not deal or (deal.manager_id != current_manager.id and not _manager_has_director_access(current_manager)):
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    data = request.get_json()
    text = data.get('text', '').strip() if data else ''
    if not text:
        return jsonify({'success': False, 'error': 'Текст комментария не может быть пустым'}), 400
    comment = DealComment(deal_id=deal.id, author_id=current_manager.id, text=text)
    db.session.add(comment)
    db.session.add(DealHistory(deal_id=deal.id, author_id=current_manager.id, action='comment_added', description=f'Добавлен комментарий'))
    db.session.commit()
    return jsonify({'success': True, 'comment': {'id': comment.id, 'text': comment.text, 'author': current_manager.full_name or current_manager.email, 'created_at': comment.created_at.strftime('%d.%m.%Y %H:%M')}})


@deals_bp.route('/api/deals/<int:deal_id>/comments/<int:comment_id>', methods=['DELETE'])
@csrf.exempt
@manager_required
def api_deal_delete_comment(deal_id, comment_id):
    from models import Deal, DealComment
    current_manager = current_user
    deal = Deal.query.get(deal_id)
    if not deal or (deal.manager_id != current_manager.id and not _manager_has_director_access(current_manager)):
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    comment = DealComment.query.get(comment_id)
    if not comment or comment.deal_id != deal.id:
        return jsonify({'success': False, 'error': 'Комментарий не найден'}), 404
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'success': True})


@deals_bp.route('/api/deals/<int:deal_id>/comments/<int:comment_id>/pin', methods=['POST'])
@csrf.exempt
@manager_required
def api_deal_pin_comment(deal_id, comment_id):
    from models import Deal, DealComment
    current_manager = current_user
    deal = Deal.query.get(deal_id)
    if not deal or (deal.manager_id != current_manager.id and not _manager_has_director_access(current_manager)):
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    comment = DealComment.query.get(comment_id)
    if not comment or comment.deal_id != deal.id:
        return jsonify({'success': False, 'error': 'Комментарий не найден'}), 404
    comment.is_pinned = not comment.is_pinned
    db.session.commit()
    return jsonify({'success': True, 'is_pinned': comment.is_pinned})


@deals_bp.route("/api/deals/<int:deal_id>/tasks", methods=["GET", "POST"])
@csrf.exempt
@manager_required
def api_deal_add_task(deal_id):
    from models import Deal, DealTask, DealHistory
    current_manager = current_user
    deal = Deal.query.get(deal_id)
    if not deal or (deal.manager_id != current_manager.id and not _manager_has_director_access(current_manager)):
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    if request.method == 'GET':
        tasks = DealTask.query.filter_by(deal_id=deal.id).order_by(DealTask.created_at.desc()).all()
        return jsonify({'success': True, 'tasks': [{'id': t.id, 'title': t.title, 'due_date': t.due_date.strftime('%d.%m.%Y %H:%M') if t.due_date else None, 'priority': t.priority, 'is_completed': t.is_completed, 'is_overdue': t.is_overdue} for t in tasks]})
    data = request.get_json()
    title = data.get('title', '').strip() if data else ''
    if not title:
        return jsonify({'success': False, 'error': 'Название задачи обязательно'}), 400
    due_date = None
    if data.get('due_date'):
        try:
            from datetime import datetime as dt
            due_date = dt.strptime(data['due_date'], '%Y-%m-%dT%H:%M') if 'T' in data['due_date'] else dt.strptime(data['due_date'], '%Y-%m-%d')
        except ValueError:
            pass
    task = DealTask(deal_id=deal.id, author_id=current_manager.id, title=title,
                   description=data.get('description', ''), due_date=due_date,
                   priority=data.get('priority', 'normal'))
    db.session.add(task)
    db.session.add(DealHistory(deal_id=deal.id, author_id=current_manager.id, action='task_created', description=f'Создана задача: {title}'))
    db.session.commit()
    return jsonify({'success': True, 'task': {'id': task.id, 'title': task.title, 'due_date': task.due_date.strftime('%d.%m.%Y %H:%M') if task.due_date else None, 'priority': task.priority, 'is_completed': task.is_completed}})


@deals_bp.route('/api/deals/<int:deal_id>/tasks/<int:task_id>/toggle', methods=['POST'])
@csrf.exempt
@manager_required
def api_deal_toggle_task(deal_id, task_id):
    from models import Deal, DealTask, DealHistory
    from datetime import datetime as dt
    current_manager = current_user
    deal = Deal.query.get(deal_id)
    if not deal or (deal.manager_id != current_manager.id and not _manager_has_director_access(current_manager)):
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    task = DealTask.query.get(task_id)
    if not task or task.deal_id != deal.id:
        return jsonify({'success': False, 'error': 'Задача не найдена'}), 404
    task.is_completed = not task.is_completed
    task.completed_at = dt.utcnow() if task.is_completed else None
    action = 'task_completed' if task.is_completed else 'task_created'
    desc = f'Задача выполнена: {task.title}' if task.is_completed else f'Задача открыта заново: {task.title}'
    db.session.add(DealHistory(deal_id=deal.id, author_id=current_manager.id, action=action, description=desc))
    db.session.commit()
    return jsonify({'success': True, 'is_completed': task.is_completed})


@deals_bp.route('/api/deals/<int:deal_id>/tasks/<int:task_id>', methods=['DELETE'])
@csrf.exempt
@manager_required
def api_deal_delete_task(deal_id, task_id):
    from models import Deal, DealTask
    current_manager = current_user
    deal = Deal.query.get(deal_id)
    if not deal or (deal.manager_id != current_manager.id and not _manager_has_director_access(current_manager)):
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    task = DealTask.query.get(task_id)
    if not task or task.deal_id != deal.id:
        return jsonify({'success': False, 'error': 'Задача не найдена'}), 404
    db.session.delete(task)
    db.session.commit()
    return jsonify({'success': True})



@deals_bp.route('/api/deals/<int:deal_id>/tasks/<int:task_id>/reschedule', methods=['POST'])
@csrf.exempt
@manager_required
def api_deal_reschedule_task(deal_id, task_id):
    from models import Deal, DealTask, DealHistory
    from datetime import datetime as dt
    current_manager = current_user
    deal = Deal.query.get(deal_id)
    if not deal or (deal.manager_id != current_manager.id and not _manager_has_director_access(current_manager)):
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    task = DealTask.query.get(task_id)
    if not task or task.deal_id != deal.id:
        return jsonify({'success': False, 'error': 'Задача не найдена'}), 404
    data = request.get_json()
    new_date_str = data.get('due_date') if data else None
    if not new_date_str:
        return jsonify({'success': False, 'error': 'Не указана дата'}), 400
    try:
        new_date = dt.strptime(new_date_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        try:
            new_date = dt.strptime(new_date_str, '%Y-%m-%d')
            if task.due_date:
                new_date = new_date.replace(hour=task.due_date.hour, minute=task.due_date.minute)
        except ValueError:
            return jsonify({'success': False, 'error': 'Неверный формат даты'}), 400
    old_date = task.due_date.strftime('%d.%m.%Y %H:%M') if task.due_date else 'не указана'
    task.due_date = new_date
    db.session.add(DealHistory(deal_id=deal.id, author_id=current_manager.id, action='task_created', description=f'Задача "{task.title}" перенесена: {old_date} → {new_date.strftime("%d.%m.%Y %H:%M")}'))
    db.session.commit()
    return jsonify({'success': True, 'task': {'id': task.id, 'title': task.title, 'due_date': task.due_date.strftime('%d.%m.%Y %H:%M') if task.due_date else None}})




@deals_bp.route('/api/deals/<int:deal_id>/documents', methods=['GET'])
@csrf.exempt
@login_required
def get_deal_documents(deal_id):
    from models import Deal, Document
    deal = Deal.query.get(deal_id)
    if not deal:
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    if deal.client_id != current_user.id and not (hasattr(current_user, 'manager') and deal.manager_id == current_user.id):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    docs = Document.query.filter_by(deal_id=deal_id).order_by(Document.created_at.desc()).all()
    return jsonify({'success': True, 'documents': [{
        'id': d.id,
        'original_filename': d.original_filename,
        'file_type': d.file_type,
        'file_size': d.file_size,
        'document_type': d.document_type,
        'status': d.status,
        'created_at': d.created_at.strftime('%d.%m.%Y %H:%M') if d.created_at else None,
        'reviewer_notes': d.reviewer_notes
    } for d in docs]})


@deals_bp.route('/api/deals/<int:deal_id>/documents', methods=['POST'])
@csrf.exempt
@login_required
def upload_deal_documents(deal_id):
    from models import Deal, Document
    import os
    from werkzeug.utils import secure_filename
    from datetime import datetime as dt
    deal = Deal.query.get(deal_id)
    if not deal:
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    if deal.client_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': 'Нет файлов'}), 400
    files = request.files.getlist('files')
    upload_dir = 'instance/uploads/deals'
    os.makedirs(upload_dir, exist_ok=True)
    uploaded = []
    for file in files:
        if file.filename == '':
            continue
        if file and file.filename:
            orig_name = file.filename
            fname = secure_filename(orig_name) if orig_name else 'file'
            timestamp = str(int(dt.utcnow().timestamp()))
            stored = f"{timestamp}_{fname}"
            fpath = os.path.join(upload_dir, stored)
            try:
                file.save(fpath)
                fsize = os.path.getsize(fpath)
                ext = fname.rsplit('.', 1)[1].lower() if '.' in fname else 'bin'
                doc = Document(
                    user_id=current_user.id,
                    deal_id=deal_id,
                    filename=stored,
                    original_filename=orig_name,
                    file_path=fpath,
                    file_size=fsize,
                    file_type=ext,
                    document_type='Документ к сделке',
                    status='Загружен'
                )
                db.session.add(doc)
                uploaded.append({'filename': orig_name, 'size': fsize})
            except Exception as e:
                print(f"Error uploading file: {e}")
                continue
    db.session.commit()
    return jsonify({'success': True, 'uploaded': uploaded, 'count': len(uploaded)})


@deals_bp.route('/api/deals/<int:deal_id>/documents/<int:doc_id>', methods=['DELETE'])
@csrf.exempt
@login_required
def delete_deal_document(deal_id, doc_id):
    from models import Deal, Document
    import os
    deal = Deal.query.get(deal_id)
    if not deal or deal.client_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    doc = Document.query.filter_by(id=doc_id, deal_id=deal_id, user_id=current_user.id).first()
    if not doc:
        return jsonify({'success': False, 'error': 'Документ не найден'}), 404
    try:
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except Exception:
        pass
    db.session.delete(doc)
    db.session.commit()
    return jsonify({'success': True})


@deals_bp.route('/api/documents/<int:doc_id>/download')
@login_required
def download_document(doc_id):
    from models import Document
    import os
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first()
    if not doc:
        return jsonify({'success': False, 'error': 'Документ не найден'}), 404
    if not doc.file_path or not os.path.exists(doc.file_path):
        return jsonify({'success': False, 'error': 'Файл не найден'}), 404
    from flask import send_file
    return send_file(doc.file_path, download_name=doc.original_filename, as_attachment=True)


@deals_bp.route('/api/deals/<int:deal_id>/reassign', methods=['POST'])
@csrf.exempt
@manager_required
def api_deal_reassign(deal_id):
    from models import Deal, DealHistory, Manager, OrgRole, Department
    current_manager = current_user
    role = current_manager.org_role
    can_change = (role.can_change_deal_responsible if role else False) or _manager_has_director_access(current_manager)
    can_view_all = (role.can_view_all_deals if role else False)
    
    if not can_change:
        return jsonify({'success': False, 'error': 'Нет прав на смену ответственного'}), 403
    
    deal = Deal.query.get(deal_id)
    if not deal:
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    
    if deal.is_locked:
        return jsonify({'success': False, 'error': 'Сделка завершена и не может быть изменена'}), 400
    
    data = request.get_json()
    new_manager_id = data.get('manager_id') if data else None
    if not new_manager_id:
        return jsonify({'success': False, 'error': 'Не указан новый менеджер'}), 400
    
    new_manager = Manager.query.get(int(new_manager_id))
    if not new_manager or not new_manager.is_active:
        return jsonify({'success': False, 'error': 'Менеджер не найден'}), 404
    
    if not can_view_all and current_manager.department_id:
        dept = Department.query.get(current_manager.department_id)
        dept_ids = dept.get_all_manager_ids() if dept else [current_manager.id]
        if new_manager.id not in dept_ids:
            return jsonify({'success': False, 'error': 'Менеджер не принадлежит вашему отделу'}), 403
    
    old_manager = deal.manager
    old_name = old_manager.full_name if old_manager else 'Не назначен'
    new_name = new_manager.full_name
    
    deal.manager_id = new_manager.id
    deal.updated_at = datetime.utcnow()
    
    db.session.add(DealHistory(
        deal_id=deal.id, author_id=current_manager.id, action='field_change',
        field_name='manager_id', old_value=old_name, new_value=new_name,
        description=f'Ответственный изменён: {old_name} → {new_name}'
    ))
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'Ответственный изменён на {new_name}'})


@deals_bp.route('/api/deals/<int:deal_id>/stage', methods=['POST'])
@csrf.exempt
@manager_required
def api_deal_change_stage(deal_id):
    from models import Deal, DealHistory, UserNotification
    current_manager = current_user
    deal = Deal.query.get(deal_id)
    if not deal or (deal.manager_id != current_manager.id and not _manager_has_director_access(current_manager)):
        return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
    data = request.get_json()
    if deal.is_locked:
        return jsonify({'success': False, 'error': 'Сделка завершена и не может быть изменена'}), 400
    new_stage = data.get('stage') if data else None
    stages_config = Deal.get_stages_config()
    if not new_stage or new_stage not in stages_config['order']:
        return jsonify({'success': False, 'error': 'Некорректный этап'}), 400
    old_stage = deal.status
    if old_stage == new_stage:
        return jsonify({'success': True, 'message': 'Этап не изменился'})
    old_label = stages_config['labels'].get(old_stage, old_stage)
    new_label = stages_config['labels'].get(new_stage, new_stage)
    deal.status = new_stage
    deal.updated_at = datetime.utcnow()
    if new_stage in ['completed', 'rejected']:
        deal.closed_at = datetime.utcnow()
        closing_comment = data.get('closing_comment', '').strip() if data else ''
        if closing_comment:
            deal.closing_comment = closing_comment
        if new_stage == 'rejected':
            rejection_reason = data.get('rejection_reason', '').strip() if data else ''
            if rejection_reason:
                deal.rejection_reason = rejection_reason
    db.session.add(DealHistory(deal_id=deal.id, author_id=current_manager.id, action='stage_change',
                               field_name='status', old_value=old_label, new_value=new_label,
                               description=f'Этап изменён: {old_label} → {new_label}'))
    notification_icons = {
        'new': 'fas fa-star', 'in_progress': 'fas fa-spinner', 'calculation': 'fas fa-calculator',
        'meeting_scheduled': 'fas fa-calendar-check', 'meeting_done': 'fas fa-handshake',
        'postponed': 'fas fa-pause-circle', 'verbal_reserve': 'fas fa-comment-dots',
        'reserved': 'fas fa-bookmark', 'documents': 'fas fa-file-alt', 'mortgage': 'fas fa-university',
        'ddu_preparation': 'fas fa-file-contract', 'ddu_signing': 'fas fa-pen-fancy',
        'registration': 'fas fa-stamp', 'receivables': 'fas fa-money-bill-wave',
        'completed': 'fas fa-check-circle', 'rejected': 'fas fa-times-circle'
    }
    notif_type = 'success' if new_stage == 'completed' else ('error' if new_stage == 'rejected' else 'info')
    complex_name = deal.residential_complex_name or (deal.residential_complex.name if deal.residential_complex else '')
    try:
        notif = UserNotification(
            user_id=deal.client_id,
            title=f'Сделка {deal.deal_number}: {new_label}',
            message=f'Статус вашей сделки' + (f' по {complex_name}' if complex_name else '') + f' изменён с «{old_label}» на «{new_label}»',
            notification_type=notif_type,
            icon=notification_icons.get(new_stage, 'fas fa-info-circle'),
            action_url='/dashboard#deals'
        )
        db.session.add(notif)
    except Exception as e:
        current_app.logger.error(f'Failed to create deal notification: {e}')
    db.session.commit()

    # Web Push to client about stage change
    try:
        from push_service import push_deal_stage_changed
        client = User.query.get(deal.client_id)
        if client:
            push_deal_stage_changed(
                user=client,
                deal_number=deal.deal_number or str(deal.id),
                old_label=old_label,
                new_label=new_label,
                complex_name=complex_name,
                deal_id=deal.id,
            )
    except Exception:
        pass

    return jsonify({'success': True, 'stage': new_stage, 'stage_label': new_label})
