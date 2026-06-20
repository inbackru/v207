"""
routes/applications.py — Callback requests, booking, cashback, contact manager,
                          favorites, presentations, collections, documents (extracted from app.py)
"""
from flask import (Blueprint, abort, flash, jsonify, redirect,
                   render_template, request, session, url_for, current_app)
from flask_login import current_user, login_required
import os
from app import csrf, db, require_json_csrf, manager_required

bp = Blueprint('applications', __name__)

try:
    from app import limiter as _limiter
except ImportError:
    _limiter = None

def _rate_limit(limit_str):
    """Apply rate limit decorator only if limiter is available."""
    def decorator(f):
        if _limiter is not None:
            return _limiter.limit(limit_str)(f)
        return f
    return decorator

def send_callback_notification_email(callback_req, manager):
    from app import send_callback_notification_email as _fn
    return _fn(callback_req, manager)

def send_callback_notification_telegram(callback_req, manager):
    from app import send_callback_notification_telegram as _fn
    return _fn(callback_req, manager)




@bp.route('/api/callback-request', methods=['POST'])
@csrf.exempt
@_rate_limit("20 per hour")
def api_callback_request():
    """Submit callback request"""
    from models import CallbackRequest, Manager
    data = request.get_json()
    
    try:
        # Extract data
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        preferred_time = data.get('preferred_time', '')
        notes = data.get('notes', '').strip()
        
        # Quiz responses
        district = data.get('district', '').strip()
        interest = data.get('interest', '')
        budget = data.get('budget', '')
        timing = data.get('timing', '')
        
        # Validation
        if not name or not phone:
            return jsonify({'success': False, 'error': 'Имя и телефон обязательны для заполнения'})
        
        # ИСПРАВЛЕНО: Убираем строгую проверку района, делаем optional
        if not district:
            district = 'Не указан'
        
        # Create callback request
        callback_req = CallbackRequest(
            name=name,
            phone=phone,
            email=email or None,
            preferred_time=preferred_time,
            notes=notes,
            interest=interest,
            budget=budget,
            timing=timing
        )
        
        # Auto-assign via round-robin (least loaded manager with can_receive_leads)
        available_manager = _find_lead_receiving_manager()
        if not available_manager:
            available_manager = Manager.query.filter_by(is_active=True).first()
        if available_manager:
            callback_req.assigned_manager_id = available_manager.id
        
        db.session.add(callback_req)
        
        form_notes_parts = []
        if interest: form_notes_parts.append(f"Интерес: {interest}")
        if budget: form_notes_parts.append(f"Бюджет: {budget}")
        if timing: form_notes_parts.append(f"Сроки: {timing}")
        if district and district != 'Не указан': form_notes_parts.append(f"Район: {district}")
        if preferred_time: form_notes_parts.append(f"Время звонка: {preferred_time}")
        if notes: form_notes_parts.append(f"Комментарий: {notes}")
        deal_notes = '; '.join(form_notes_parts) if form_notes_parts else ''
        
        quiz_info = {}
        if district and district != 'Не указан': quiz_info['district'] = district
        if interest: quiz_info['interest'] = interest
        if budget: quiz_info['budget'] = budget
        if timing: quiz_info['timing'] = timing
        
        deal, _ = create_deal_from_website_form(
            name=name,
            phone=phone,
            email=email,
            source='Форма обратного звонка',
            notes=deal_notes,
            quiz_data=quiz_info if quiz_info else None
        )
        
        db.session.commit()
        
        if deal:
            print(f"✅ Deal {deal.deal_number} created from callback request for {name}")
        
        try:
            send_callback_notification_email(callback_req, available_manager)
            send_callback_notification_telegram(callback_req, available_manager)
        except Exception as e:
            print(f"Failed to send callback notifications: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Заявка отправлена! Наш менеджер свяжется с вами в ближайшее время.'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Callback request error: {e}")
        return jsonify({'success': False, 'error': 'Ошибка при отправке заявки. Попробуйте еще раз.'})

@csrf.exempt  # CSRF disabled for public presentation booking
@bp.route('/api/booking', methods=['POST'])
@_rate_limit("20 per hour")
def api_booking_request():
    """✅ MIGRATED TO NORMALIZED TABLES: Submit booking request for property"""
    from models import BookingRequest, Manager
    
    try:
        data = request.get_json()
        
        # Validate required fields
        property_id = data.get('property_id')
        client_name = data.get('client_name')
        client_phone = data.get('client_phone')
        presentation_id = data.get('presentation_id')
        
        if not all([property_id, client_name, client_phone]):
            return jsonify({'success': False, 'error': 'Не все обязательные поля заполнены'}), 400
        
        # ✅ MIGRATED: Find property details using resolve_property_by_identifier (supports inner_id)
        property_detail, _ = resolve_property_by_identifier(property_id)
        if not property_detail:
            return jsonify({'success': False, 'error': 'Объект не найден'}), 404
        
        # Create booking request
        booking = BookingRequest()
        booking.property_id = property_id
        booking.client_name = client_name
        booking.client_phone = client_phone
        booking.client_email = data.get('client_email')
        booking.comment = data.get('comment')
        booking.presentation_id = presentation_id
        booking.property_price = property_detail.price
        booking.property_address = property_detail.address
        booking.complex_name = property_detail.residential_complex.name if property_detail.residential_complex else 'Не указан'
        booking.rooms_count = property_detail.rooms
        booking.area = property_detail.area
        booking.status = 'new'
        
        db.session.add(booking)
        
        booking_notes = f"Бронирование квартиры в {booking.complex_name}"
        if booking.comment:
            booking_notes += f"; Комментарий: {booking.comment}"
        
        deal, _ = create_deal_from_website_form(
            name=client_name,
            phone=client_phone,
            email=data.get('client_email'),
            source='Бронирование',
            complex_name=booking.complex_name,
            property_price=float(booking.property_price) if booking.property_price else 0,
            notes=booking_notes
        )
        
        db.session.commit()
        
        if deal:
            print(f"✅ Deal {deal.deal_number} created from booking for {client_name}")
        
        try:
            send_booking_notifications(booking, property_detail)
        except Exception as notification_error:
            print(f"Notification error: {notification_error}")
        
        return jsonify({
            'success': True, 
            'message': 'Заявка на бронирование успешно отправлена!',
            'booking_id': booking.id
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Booking request error: {e}")
        return jsonify({'success': False, 'error': 'Ошибка при отправке заявки. Попробуйте еще раз.'}), 500

def send_booking_notifications(booking, property_detail):
    """Send notifications to managers about new booking request"""
    from models import Manager
    
    # Get all active managers
    managers = Manager.query.filter_by(is_active=True).all()
    
    # Email notification (if configured)
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        subject = f"🏠 Новая заявка на бронирование - {property_detail.complex_name}"
        
        # Prepare property details
        rooms_text = "Студия" if property_detail.object_rooms == 0 else f"{property_detail.object_rooms}-комнатная"
        
        body = f"""
🏠 Новая заявка на бронирование квартиры

📋 ИНФОРМАЦИЯ О КЛИЕНТЕ:
👤 Имя: {booking.client_name}
📱 Телефон: {booking.client_phone}
📧 Email: {booking.client_email or 'не указан'}
💬 Комментарий: {booking.comment or 'нет'}

🏢 ИНФОРМАЦИЯ О КВАРТИРЕ:
🏠 ЖК: {property_detail.complex_name}
🏠 Тип: {rooms_text} квартира
📐 Площадь: {property_detail.area} м²
🏢 Этаж: {property_detail.floor}/{property_detail.total_floors}
💰 Цена: {'{:,}'.format(int(property_detail.price)).replace(',', ' ')} ₽
📍 Адрес: {property_detail.address_display_name}
🏗️ Застройщик: {property_detail.developer_name}
🔗 ID объекта: {booking.property_id}

📅 Дата заявки: {booking.created_at.strftime('%d.%m.%Y %H:%M')}
🆔 ID заявки: {booking.id}

⏰ Рекомендуем связаться с клиентом в течение 15 минут!
        """.strip()
        
        for manager in managers:
            if manager.email:
                try:
                    send_email_notification(manager.email, subject, body)
                except Exception as email_error:
                    print(f"Failed to send email to {manager.email}: {email_error}")
                    
    except Exception as e:
        print(f"Email notification error: {e}")
    
    # Telegram notification (if bot configured)
    try:
        send_telegram_booking_notification(booking, property_detail, managers)
    except Exception as e:
        print(f"Telegram notification error: {e}")

def send_email_notification(email, subject, body):
    """Send email notification via SendGrid or SMTP fallback"""
    if not email:
        return
    try:
        sendgrid_key = os.environ.get('SENDGRID_API_KEY')
        if sendgrid_key:
            try:
                from sendgrid import SendGridAPIClient
                from sendgrid.helpers.mail import Mail
                from_email = os.environ.get('EMAIL_FROM', os.environ.get('EMAIL_USER', 'noreply@inback.ru'))
                message = Mail(from_email=from_email, to_emails=email, subject=subject, plain_text_content=body)
                sg = SendGridAPIClient(sendgrid_key)
                sg.send(message)
                print(f"📧 Email sent via SendGrid to {email}: {subject}")
                return
            except Exception as sg_err:
                print(f"SendGrid error: {sg_err}, falling back to SMTP")
        import smtplib
        from email.mime.text import MIMEText
        email_user = os.environ.get('EMAIL_USER', '')
        email_password = os.environ.get('EMAIL_PASSWORD', '')
        email_host = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
        email_port = int(os.environ.get('EMAIL_PORT', 587))
        if not email_user or not email_password:
            print(f"📧 Email not configured (no EMAIL_USER/EMAIL_PASSWORD). Would send to {email}: {subject}")
            return
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = email_user
        msg['To'] = email
        with smtplib.SMTP(email_host, email_port) as server:
            server.starttls()
            server.login(email_user, email_password)
            server.sendmail(email_user, [email], msg.as_string())
        print(f"📧 Email sent via SMTP to {email}: {subject}")
    except Exception as e:
        print(f"📧 Email send error to {email}: {e}")

def send_telegram_booking_notification(booking, property_detail, managers):
    """Send Telegram notification to managers respecting their preferences"""
    try:
        from email_service import send_manager_notification
        
        rooms_text = "Студия" if property_detail.object_rooms == 0 else f"{property_detail.object_rooms}-комнатная"
        
        tg_message = (
            f"🏠 *НОВАЯ ЗАЯВКА НА БРОНИРОВАНИЕ*\n\n"
            f"👤 Клиент: {booking.client_name}\n"
            f"📱 Телефон: {booking.client_phone}\n"
            f"📧 Email: {booking.client_email or 'не указан'}\n\n"
            f"🏢 Квартира: {rooms_text}, {property_detail.area} м²\n"
            f"🏠 ЖК: {property_detail.complex_name}\n"
            f"💰 Цена: {'{:,}'.format(int(property_detail.price)).replace(',', ' ')} ₽\n"
            f"📍 Адрес: {property_detail.address_display_name}\n\n"
            f"💬 Комментарий: {booking.comment or 'нет'}\n"
            f"🆔 ID заявки: {booking.id}\n\n"
            f"⏰ Рекомендуем связаться в течение 15 минут!"
        )
        
        from telegram_bot import send_telegram_message
        _admin_tg = os.environ.get('TELEGRAM_CHAT_ID', '')
        send_telegram_message(_admin_tg, tg_message)
        
        for manager in managers:
            send_manager_notification(
                manager, 'booking_request', tg_message,
                email_subject=f'Заявка на бронирование от {booking.client_name}',
                email_template='emails/general_notification.html',
                user_name=manager.first_name,
                subject=f'Заявка на бронирование от {booking.client_name}',
                message=f'Новая заявка на бронирование квартиры в {property_detail.complex_name}. Клиент: {booking.client_name}, тел: {booking.client_phone}'
            )
                    
    except Exception as e:
        print(f"Telegram notification setup error: {e}")

@bp.route('/api/cashback-application', methods=['POST'])
@login_required
@_rate_limit("10 per hour")
def create_cashback_application():
    """Create new cashback application"""
    from models import CashbackApplication
    data = request.get_json()
    
    try:
        app = CashbackApplication(
            user_id=current_user.id,
            property_name=data['property_name'],
            property_type=data['property_type'],
            property_size=float(data['property_size']),
            property_price=int(data['property_price']),
            complex_name=data['complex_name'],
            developer_name=data['developer_name'],
            cashback_amount=int(data['cashback_amount']),
            cashback_percent=float(data['cashback_percent'])
        )
        db.session.add(app)
        db.session.commit()
        
        return jsonify({'success': True, 'application_id': app.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/contact-manager', methods=['POST'])
@csrf.exempt  # CSRF disabled - отключено для простоты отправки заявок
@_rate_limit("20 per hour")
def contact_manager():
    """API endpoint for contacting manager"""
    try:
        from models import Application
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Validate required fields
        required_fields = ['name', 'phone']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'Field {field} is required'}), 400
        
        # Get current user if logged in
        user_id = session.get('user_id')
        
        # Create application with required fields
        application = Application(
            user_id=user_id,
            contact_name=data.get('name'),
            contact_email=data.get('email'),
            contact_phone=data.get('phone'),
            property_name=data.get('property_name', 'Заявка на подбор жилья'),
            complex_name=data.get('complex_name', 'По предпочтениям клиента'),
            status='new',
            message=data.get('message', f"Цель: {data.get('interest', '')}, Тип: {data.get('property_type', '')}, Комнат: {data.get('rooms', '')}, Заселение: {data.get('completion', '')}, Оплата: {data.get('payment', '')}"),
            preferred_contact=data.get('preferred_contact', 'phone')
        )
        
        db.session.add(application)
        
        contact_notes_parts = []
        if data.get('property_name') and data.get('property_name') != 'Заявка на подбор жилья':
            contact_notes_parts.append(f"Объект: {data.get('property_name')}")
        if data.get('message'):
            contact_notes_parts.append(data.get('message'))
        deal_notes = '; '.join(contact_notes_parts) if contact_notes_parts else ''
        
        quiz_info = {}
        if data.get('interest'): quiz_info['interest'] = data['interest']
        if data.get('property_type'): quiz_info['property_type'] = data['property_type']
        if data.get('district'): quiz_info['district'] = data['district']
        if data.get('rooms'): quiz_info['rooms'] = data['rooms']
        if data.get('completion'): quiz_info['timing'] = data['completion']
        if data.get('payment'): quiz_info['budget'] = data['payment']
        if data.get('budget'): quiz_info['budget'] = data['budget']
        
        deal, _ = create_deal_from_website_form(
            name=data.get('name'),
            phone=data.get('phone'),
            email=data.get('email'),
            source='Заявка на подбор',
            complex_name=data.get('complex_name', 'По предпочтениям клиента'),
            property_price=float(data.get('property_price', 0)) if data.get('property_price') else 0,
            notes=deal_notes,
            quiz_data=quiz_info if quiz_info else None
        )
        
        db.session.commit()
        
        if deal:
            print(f"✅ Deal {deal.deal_number} created from contact form for {data.get('name')}")
        
        try:
            from email_service import send_manager_notification
            send_manager_notification(
                name=data.get('name'),
                phone=data.get('phone'),
                email=data.get('email'),
                message=data.get('message', ''),
                application_id=application.id
            )
        except Exception as e:
            print(f"Failed to send manager notification email: {e}")
            
        # Send Telegram notification
        try:
            from telegram_bot import send_telegram_message
            from datetime import datetime
            
            # Check if this is for a specific property
            is_specific_property = data.get('property_id') and data.get('property_name')
            
            # Prepare Telegram message with quiz data or property info
            if is_specific_property:
                message_parts = [
                    "🏠 *ЗАЯВКА НА ПРОСМОТР КОНКРЕТНОЙ КВАРТИРЫ*",
                    "",
                    "👤 *КОНТАКТНАЯ ИНФОРМАЦИЯ:*",
                    f"• Имя: {data.get('name')}",
                    f"• Телефон: {data.get('phone')}",
                ]
                
                if data.get('email'):
                    message_parts.append(f"• Email: {data.get('email')}")
                    
                message_parts.extend([
                    "",
                    "🏢 *ИНТЕРЕСУЮЩАЯ КВАРТИРА:*",
                    f"• Объект: {data.get('property_name')}",
                ])
                
                if data.get('complex_name'):
                    message_parts.append(f"• ЖК: {data.get('complex_name')}")
                if data.get('property_price'):
                    price_formatted = f"{int(float(data.get('property_price'))):,}".replace(',', ' ')
                    message_parts.append(f"• Цена: {price_formatted} руб.")
                if data.get('property_area'):
                    message_parts.append(f"• Площадь: {data.get('property_area')} м²")
                if data.get('property_floor'):
                    message_parts.append(f"• Этаж: {data.get('property_floor')}")
                if data.get('property_district'):
                    message_parts.append(f"• Район: {data.get('property_district')}")
                if data.get('property_address'):
                    message_parts.append(f"• Адрес: {data.get('property_address')}")
                    
                # Calculate potential cashback
                if data.get('property_price'):
                    try:
                        price = float(data.get('property_price'))
                        cashback = price * 0.03  # 3% cashback
                        cashback_formatted = f"{int(cashback):,}".replace(',', ' ')
                        message_parts.append(f"💰 Потенциальный кэшбек: {cashback_formatted} руб. (3%)")
                    except:
                        pass
                        
                # Add property URL if available
                if data.get('property_url'):
                    message_parts.extend([
                        "",
                        f"🔗 *ССЫЛКА НА КВАРТИРУ:*",
                        f"{data.get('property_url')}"
                    ])
            else:
                message_parts = [
                    "🏠 *НОВАЯ ЗАЯВКА НА ПОДБОР ЖИЛЬЯ*",
                    "",
                    "👤 *КОНТАКТНАЯ ИНФОРМАЦИЯ:*",
                    f"• Имя: {data.get('name')}",
                    f"• Телефон: {data.get('phone')}",
                ]
                
                if data.get('email'):
                    message_parts.append(f"• Email: {data.get('email')}")
                    
                # Add quiz preferences if available
                if data.get('district'):
                    message_parts.extend([
                        "",
                        "🏘️ *ПРЕДПОЧТЕНИЯ КЛИЕНТА:*",
                        f"• Район: {data.get('district')}"
                    ])
                    
                if data.get('rooms'):
                    message_parts.append(f"• Комнат: {data.get('rooms')}")
                    
                if data.get('completion'):
                    message_parts.append(f"• Срок заселения: {data.get('completion')}")
                    
                if data.get('payment'):
                    message_parts.append(f"• Способ оплаты: {data.get('payment')}")
                
            message_parts.extend([
                "",
                f"📝 *ID заявки:* #{application.id}",
                f"📅 *Время:* {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                "",
                "⚡ *ВАЖНО:* Быстрая реакция повышает конверсию!"
            ])
            
            telegram_message = "\n".join(message_parts)
            
            # Send to all manager telegram IDs from environment variable
            manager_telegram_ids = os.environ.get('MANAGER_TELEGRAM_IDS', '').split(',')
            for manager_id in manager_telegram_ids:
                manager_id = manager_id.strip()
                if manager_id:
                    send_telegram_message(manager_id, telegram_message)
            
        except Exception as notify_error:
            print(f"Telegram notification error: {notify_error}")
        
        return jsonify({
            'success': True,
            'message': 'Заявка отправлена! Менеджер свяжется с вами в ближайшее время.',
            'application_id': application.id
        })
        
    except Exception as e:
        print(f"Error creating manager contact application: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Internal server error'}), 500
