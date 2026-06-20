import os
import sys
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import render_template, url_for, request
from datetime import datetime

# SendGrid integration - from blueprint:python_sendgrid
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content
    sendgrid_available = True
except ImportError:
    # Fallback classes for LSP compatibility
    class SendGridAPIClient:
        def __init__(self, *args): pass
        def send(self, *args): pass
    class Mail:
        def __init__(self, *args, **kwargs): pass
    class Email:
        def __init__(self, *args): pass
    class To:
        def __init__(self, *args): pass
    class Content:
        def __init__(self, *args): pass
    sendgrid_available = False
    print("SendGrid not available - falling back to SMTP")

# Email configuration - using standard SMTP
EMAIL_HOST = 'smtp.gmail.com'  # Gmail SMTP для реальной отправки
EMAIL_PORT = 587
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USER = os.environ.get('EMAIL_USER', 'test.inback@gmail.com')  # Замените на реальный email
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')  # App Password от Gmail

# Telegram configuration - using working token
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    print("WARNING: TELEGRAM_BOT_TOKEN not set - Telegram notifications will be disabled")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
# For manager notifications (insurance applications, etc.)
MANAGER_TELEGRAM_IDS = os.environ.get('MANAGER_TELEGRAM_IDS', '')

try:
    from telegram.ext import Application
    from telegram import Bot
    if TELEGRAM_BOT_TOKEN:
        telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
        print("✅ Telegram bot initialized successfully")
    else:
        telegram_bot = None
        print("TELEGRAM_BOT_TOKEN not found")
except ImportError:
    print("Telegram bot setup failed: ImportError with telegram package")
    telegram_bot = None
except Exception as e:
    telegram_bot = None
    print(f"Telegram bot setup failed: {e}")

def send_email_sendgrid(to_email, subject, template_name, **template_data):
    """
    Send email using SendGrid with HTML template
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        template_name: HTML template file name (e.g., 'emails/welcome.html')
        **template_data: Data to pass to the template
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    if not sendgrid_available:
        return send_email_smtp(to_email, subject, template_name, **template_data)
    
    try:
        sendgrid_key = os.environ.get('SENDGRID_API_KEY')
        if not sendgrid_key:
            print("SendGrid API key not found - falling back to SMTP")
            return send_email_smtp(to_email, subject, template_name, **template_data)
        
        if 'subject' not in template_data:
            template_data['subject'] = subject
        html_content = render_template(template_name, **template_data)
        
        # Create SendGrid message
        sg = SendGridAPIClient(sendgrid_key)
        
        message = Mail(
            from_email=Email(EMAIL_USER, "InBack"),
            to_emails=To(to_email),
            subject=subject,
            html_content=Content("text/html", html_content)
        )
        
        # Send email
        response = sg.send(message)
        if response.status_code in [200, 201, 202]:
            print(f"✅ Email sent to {to_email}: {subject}")
            return True
        else:
            print(f"❌ SendGrid error: {response.status_code}")
            return False
        
    except Exception as e:
        print(f"SendGrid error: {e}")
        # Fallback to SMTP
        return send_email_smtp(to_email, subject, template_name, **template_data)

def send_email_smtp(to_email, subject, template_name, **template_data):
    """
    Send email using standard SMTP with HTML template
    """
    try:
        if 'subject' not in template_data:
            template_data['subject'] = subject
        html_content = render_template(template_name, **template_data)

        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = f"InBack <{EMAIL_USER}>"
        message['To'] = to_email

        html_part = MIMEText(html_content, 'html', 'utf-8')
        message.attach(html_part)

        if EMAIL_PASSWORD:
            import smtplib
            if int(EMAIL_PORT) == 465:
                with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
                    server.login(EMAIL_USER, EMAIL_PASSWORD)
                    server.send_message(message)
            else:
                with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
                    server.starttls()
                    server.login(EMAIL_USER, EMAIL_PASSWORD)
                    server.send_message(message)
            return True
        else:
            return False
    except Exception as e:
        print(f"SMTP error: {e}")
        return False


def send_email(to_email, subject, template_name, **template_data):
    """
    Unified email sending function - tries SendGrid first, falls back to SMTP
    """
    return send_email_sendgrid(to_email, subject, template_name, **template_data)


def send_recommendation_email(user, data):
    """
    Send recommendation email to user
    
    Args:
        user: User object 
        data: Dict with recommendation data
    
    Returns:
        bool: True if email sent successfully
    """
    try:
        template_data = {
            'user': user,
            'title': data.get('title', 'Новая рекомендация'),
            'item_name': data.get('item_name', ''),
            'description': data.get('description', ''),
            'manager_name': data.get('manager_name', 'Ваш менеджер'),
            'priority_text': data.get('priority_text', 'Обычный'),
            'base_url': request.url_root if request else 'https://inback.ru'
        }
        
        subject = f"Новая рекомендация от {data.get('manager_name', 'InBack')}"
        
        return send_email(
            to_email=user.email,
            subject=subject,
            template_name="emails/recommendation.html",
            **template_data
        )
    except Exception as e:
        print(f"Error sending recommendation email: {e}")
        return False

def send_saved_search_results_email(user, data):
    """
    Send saved search results email to user
    
    Args:
        user: User object
        data: Dict with search data
    
    Returns:
        bool: True if email sent successfully  
    """
    try:
        template_data = {
            'user': user,
            'search_name': data.get('search_name', 'Ваш поиск'),
            'properties_count': data.get('properties_count', 0),
            'properties_list': data.get('properties_list', ''),
            'search_url': data.get('search_url', ''),
            'base_url': request.url_root if request else 'https://inback.ru'
        }
        
        subject = f"Новые результаты поиска: {data.get('search_name', 'Ваш поиск')}"
        
        return send_email(
            to_email=user.email,
            subject=subject,
            template_name="emails/saved_search_results.html",
            **template_data
        )
    except Exception as e:
        print(f"Error sending saved search results email: {e}")
        return False

def send_verification_email(user, base_url=None):
    """Send email verification link to new user"""
    if not base_url:
        try:
            base_url = request.url_root.rstrip('/')
        except:
            base_url = 'https://inback.ru'
    
    verification_url = f"{base_url}/confirm/{user.verification_token}"
    
    return send_email(
        to_email=user.email,
        subject="Подтвердите ваш email | inback 🏠",
        template_name="emails/verification.html",
        user=user,
        verification_url=verification_url,
        base_url=base_url
    )

def send_welcome_email(user, base_url=None):
    """Send welcome email to new user"""
    if not base_url:
        try:
            base_url = request.url_root.rstrip('/')
        except:
            base_url = 'https://inback.ru'
    
    return send_email(
        to_email=user.email,
        subject="Добро пожаловать в inback! 🏠",
        template_name="emails/welcome.html",
        user=user,
        base_url=base_url
    )

def send_password_reset_email(user, reset_token):
    """Send password reset email"""
    base_url = request.url_root.rstrip('/')
    reset_url = f"{base_url}/reset-password/{reset_token}"
    
    return send_email(
        to_email=user.email,
        subject="Восстановление пароля | inback",
        template_name="emails/password_reset.html",
        user=user,
        reset_url=reset_url,
        base_url=base_url
    )

def send_application_confirmation_email(user, application):
    """Send application confirmation email"""
    base_url = request.url_root.rstrip('/')
    
    return send_email(
        to_email=user.email,
        subject="Заявка принята | inback",
        template_name="emails/application_confirmation.html",
        user=user,
        application=application,
        base_url=base_url
    )

def send_cashback_notification_email(user, cashback_record):
    """Send cashback notification email"""
    base_url = request.url_root.rstrip('/')
    
    return send_email(
        to_email=user.email,
        subject="Кешбек одобрен! 💰 | inback",
        template_name="emails/cashback_notification.html",
        user=user,
        cashback_record=cashback_record,
        base_url=base_url
    )




# Telegram notification functions
async def send_telegram_message(chat_id, message, parse_mode='HTML'):
    """
    Send message to Telegram chat
    
    Args:
        chat_id: Telegram chat ID (числовой ID или @username)
        message: Message text
        parse_mode: Message format (HTML, Markdown, etc.)
    
    Returns:
        bool: True if message sent successfully
    """
    # Use simple HTTP API instead of telegram_bot
    from telegram_bot import send_telegram_message
    return send_telegram_message(chat_id, message)
    
    try:
        # Конвертируем chat_id в правильный формат
        if isinstance(chat_id, str) and chat_id.startswith('@'):
            # Username формат - попробуем как есть
            actual_chat_id = chat_id
        else:
            # Числовой ID
            actual_chat_id = int(chat_id) if str(chat_id).isdigit() else chat_id
        
        await telegram_bot.send_message(
            chat_id=actual_chat_id,
            text=message,
            parse_mode=parse_mode
        )
        print(f"✓ Telegram message sent to {actual_chat_id}")
        return True
    except Exception as e:
        print(f"✗ Telegram error: {e}")
        if "unauthorized" in str(e).lower():
            print("📱 Решение: Проверьте токен бота в @BotFather")
        elif "chat not found" in str(e).lower() or "user not found" in str(e).lower():
            print(f"📱 Решение: Получите chat_id через get_telegram_chat_id.py")
            print(f"📱 Текущий ID: {chat_id} (возможно неверный)")
        return False

def send_telegram_notification(user, notification_type, **data):
    """
    Send Telegram notification to user
    
    Args:
        user: User object with telegram_id
        notification_type: Type of notification
        **data: Additional data for the message
    """
    
    if not hasattr(user, 'telegram_id') or not user.telegram_id:
        return False
    
    # Ensure base_url is set
    if 'base_url' not in data or not data['base_url']:
        data['base_url'] = 'https://inback.ru'
    
    messages = {
        'welcome': f"""
🏠 <b>Добро пожаловать в InBack!</b>

Привет, {getattr(user, 'first_name', None) or (user.full_name.split()[0] if hasattr(user, 'full_name') and user.full_name else 'Клиент')}! 
Теперь вы можете получать уведомления о новых объектах и важных событиях прямо в Telegram.

🔔 Настройте уведомления в личном кабинете
💰 Отслеживайте статус кэшбека
🏘️ Получайте информацию о новых ЖК

<a href="{data.get('base_url', '')}/dashboard">Перейти в личный кабинет</a>
        """,
        
        'password_reset': f"""
🔐 <b>Восстановление пароля</b>

{getattr(user, 'first_name', None) or (user.full_name.split()[0] if hasattr(user, 'full_name') and user.full_name else 'Клиент')}, поступил запрос на восстановление пароля для вашего аккаунта.

🔗 <a href="{data.get('reset_url', '')}">Восстановить пароль</a>

Если это были не вы, проигнорируйте это сообщение.
        """,
        
        'application_confirmation': f"""
✅ <b>Заявка принята!</b>

{getattr(user, 'first_name', None) or (user.full_name.split()[0] if hasattr(user, 'full_name') and user.full_name else 'Клиент')}, ваша заявка на объект "{data.get('property_name', '')}" принята.

📋 Номер заявки: #{data.get('application_id', '')}
🏠 Объект: {data.get('property_name', '')}
💰 Предварительный кэшбек: {data.get('cashback_amount', 0):,} ₽

Наш менеджер свяжется с вами в ближайшее время.
        """,
        
        'cashback_approved': f"""
💰 <b>Кэшбек одобрен!</b>

Поздравляем, {getattr(user, 'first_name', None) or (user.full_name.split()[0] if hasattr(user, 'full_name') and user.full_name else 'Клиент')}! 

✅ Ваш кэшбек одобрен: {data.get('amount', 0):,} ₽
🏠 Объект: {data.get('property_name', '')}
📅 Дата одобрения: {datetime.now().strftime('%d.%m.%Y')}

Средства будут переведены в течение 5 рабочих дней.
        """,
        
        'new_favorites': f"""
🔔 <b>Новые объекты по вашим критериям!</b>

{getattr(user, 'first_name', None) or (user.full_name.split()[0] if hasattr(user, 'full_name') and user.full_name else 'Клиент')}, появились новые объекты, которые могут вас заинтересовать:

{data.get('properties_list', '')}

<a href="{data.get('base_url', '')}/properties">Посмотреть все объекты</a>
        """,
        
        'recommendation': f"""
🏠 <b>Новая рекомендация от менеджера</b>

{getattr(user, 'first_name', None) or (user.full_name.split()[0] if hasattr(user, 'full_name') and user.full_name else 'Клиент')}, ваш менеджер {data.get('manager_name', 'InBack')} рекомендует:

📋 <b>{data.get('title', '')}</b>
🏢 {data.get('item_name', '')}

{data.get('description', '')}

💡 <i>Приоритет:</i> {data.get('priority_text', 'Обычный')}

🔗 <a href="{data.get('base_url', '')}/{('complex' if data.get('recommendation_type') == 'complex' else 'object')}/{data.get('item_id', '')}">Посмотреть объект</a>
💼 <a href="{data.get('base_url', '')}/dashboard">Личный кабинет</a>
        """,
        
        'saved_search_results': f"""
🔍 <b>Новые объекты по вашему поиску</b>

{getattr(user, 'first_name', None) or (user.full_name.split()[0] if hasattr(user, 'full_name') and user.full_name else 'Клиент')}, по вашему сохраненному поиску "{data.get('search_name', '')}" найдены новые объекты:

{data.get('properties_list', '')}

📊 Всего найдено: {data.get('properties_count', 0)} объектов

<a href="{data.get('search_url', '')}/properties">Посмотреть результаты</a>
        """
    }
    
    message = messages.get(notification_type, f"Уведомление от InBack: {notification_type}")
    
    try:
        asyncio.run(send_telegram_message(user.telegram_id, message))
        return True
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")
        return False

def should_notify_manager(manager, notification_type):
    """
    Check if a manager wants to receive a specific notification type.
    Returns dict with 'email' and 'telegram' booleans.
    """
    type_map = {
        'new_lead': 'notify_new_leads',
        'new_deal': 'notify_new_deals',
        'task_reminder': 'notify_task_reminders',
        'overdue_task': 'notify_overdue_tasks',
        'presentation_view': 'notify_presentation_views',
        'booking_request': 'notify_booking_requests',
        'daily_digest': 'notify_daily_digest',
    }
    
    pref_field = type_map.get(notification_type)
    type_enabled = True
    if pref_field:
        type_enabled = getattr(manager, pref_field, True)
        if type_enabled is None:
            type_enabled = True
    
    email_enabled = getattr(manager, 'notify_email', True)
    if email_enabled is None:
        email_enabled = True
    telegram_enabled = getattr(manager, 'notify_telegram', True)
    if telegram_enabled is None:
        telegram_enabled = True
    
    return {
        'email': type_enabled and email_enabled,
        'telegram': type_enabled and telegram_enabled
    }


def send_manager_notification(manager, notification_type, telegram_message, email_subject=None, email_template=None, **email_data):
    """
    Send notification to manager respecting their preferences.
    """
    import requests as req_lib
    
    prefs = should_notify_manager(manager, notification_type)
    results = {'email': False, 'telegram': False}
    
    if prefs['telegram'] and manager.telegram_id:
        try:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': manager.telegram_id,
                'text': telegram_message,
                'parse_mode': 'Markdown'
            }
            response = req_lib.post(telegram_url, data=payload, timeout=10)
            results['telegram'] = response.status_code == 200
        except Exception as e:
            print(f"Manager TG notification error: {e}")
    
    if prefs['email'] and manager.email and email_subject and email_template:
        try:
            results['email'] = send_email(
                to_email=manager.email,
                subject=email_subject,
                template_name=email_template,
                **email_data
            )
        except Exception as e:
            print(f"Manager email notification error: {e}")
    
    return results


# Enhanced unified notification system
def send_notification(recipient_email, subject, message, notification_type, user_id=None, manager_id=None, **extra_data):
    """
    Enhanced notification system that handles different recipients and methods
    
    Args:
        recipient_email: Email address of recipient
        subject: Subject/title of notification  
        message: Message content
        notification_type: Type of notification
        user_id: Optional user ID for database lookups
        manager_id: Optional manager ID
        **extra_data: Additional data for templates
    """
    from models import User
    
    # Try to get user object for enhanced notifications
    user = None
    if user_id:
        try:
            user = User.query.get(user_id)
        except:
            pass
    
    # If no user object but we have email, create basic user object for compatibility
    if not user and recipient_email:
        class BasicUser:
            def __init__(self, email):
                self.email = email
                self.full_name = None
                self.first_name = None
                self.preferred_contact = 'email'
                self.telegram_id = None
                self.phone = None
                
        user = BasicUser(recipient_email)
    
    results = {
        'email': False,
        'telegram': False
    }
    
    # Send email if user prefers email or has no preference
    if user and (not hasattr(user, 'preferred_contact') or 
                user.preferred_contact in ['email', 'both', None]):
        try:
            if notification_type == 'recommendation':
                results['email'] = send_recommendation_email(user, extra_data)
            elif notification_type == 'saved_search_results':
                results['email'] = send_saved_search_results_email(user, extra_data)
            else:
                # Fallback to basic email
                results['email'] = send_email(
                    to_email=recipient_email,
                    subject=subject,
                    template_name="emails/general_notification.html",
                    user=user,
                    message=message,
                    **extra_data
                )
        except Exception as e:
            print(f"Email notification failed: {e}")
    
    # Send Telegram if user has telegram_id (regardless of preference for now, since we're testing)
    if user and hasattr(user, 'telegram_id') and user.telegram_id:
        try:
            results['telegram'] = send_telegram_notification(user, notification_type, **extra_data)
        except Exception as e:
            print(f"Telegram notification failed: {e}")
    
    # Send WhatsApp if user has phone and prefers it
    if (user and hasattr(user, 'phone') and user.phone and
        hasattr(user, 'preferred_contact') and user.preferred_contact in ['whatsapp', 'both']):
        try:
            from whatsapp_integration import send_whatsapp_notification
            results['whatsapp'] = send_whatsapp_notification(user, notification_type, **extra_data)
        except Exception as e:
            print(f"WhatsApp notification failed: {e}")
    
    return results

def send_telegram_insurance_notification(name, phone, bank, credit_amount, birth_date, gender, comment, current_time):
    """
    Send insurance application notification to Telegram managers
    
    Args:
        name: Клиент имя
        phone: Телефон клиента
        bank: Банк
        credit_amount: Сумма кредита
        birth_date: Дата рождения
        gender: Пол
        comment: Комментарий
        current_time: Время подачи заявки
    
    Returns:
        bool: True if message sent successfully, False otherwise
    """
    try:
        # Check if Telegram is configured
        if not TELEGRAM_BOT_TOKEN:
            print("❌ Telegram not configured: missing TELEGRAM_BOT_TOKEN")
            return False
        
        if not telegram_bot:
            print("❌ Telegram bot not initialized")
            return False
        
        # Get manager chat IDs (try MANAGER_TELEGRAM_IDS first, fallback to TELEGRAM_CHAT_ID)
        manager_ids = MANAGER_TELEGRAM_IDS if MANAGER_TELEGRAM_IDS else TELEGRAM_CHAT_ID
        if not manager_ids:
            print("❌ No manager Telegram IDs configured")
            return False
        
        # Parse manager IDs (can be comma-separated)
        chat_ids = [id.strip() for id in str(manager_ids).split(',') if id.strip()]
        
        # Format the message
        message = f"""🛡 НОВАЯ ЗАЯВКА НА СТРАХОВАНИЕ

👤 Клиент: {name}
📞 Телефон: {phone}
🏦 Банк: {bank}
💰 Сумма кредита: {credit_amount}
📅 Дата рождения: {birth_date}
⚤ Пол: {gender}
💬 Комментарий: {comment if comment else 'Не указан'}

⏰ Время подачи: {current_time}"""
        
        # Send message using requests API (more reliable than async in this context)
        import requests
        
        # Send to all manager chat IDs
        success_count = 0
        for chat_id in chat_ids:
            try:
                # Use Telegram HTTP API directly
                telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                payload = {
                    'chat_id': chat_id,
                    'text': message,
                    'parse_mode': 'HTML'
                }
                
                response = requests.post(telegram_url, data=payload, timeout=30)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('ok'):
                        print(f"✅ Telegram insurance notification sent to {chat_id}")
                        success_count += 1
                    else:
                        print(f"❌ Telegram API error for {chat_id}: {result.get('description', 'Unknown error')}")
                else:
                    print(f"❌ Telegram HTTP error for {chat_id}: {response.status_code}")
            except Exception as e:
                print(f"❌ Error sending to {chat_id}: {e}")
                continue
        
        # Return True if at least one message was sent successfully
        return success_count > 0
            
    except Exception as e:
        print(f"❌ Error sending Telegram insurance notification: {e}")
        return False

# Legacy function for backward compatibility
def send_notification_legacy(user, notification_type, **data):
    """
    Send notification via user's preferred method (legacy version)
    
    Args:
        user: User object
        notification_type: Type of notification
        **data: Additional data
    """
    results = {
        'email': False,
        'telegram': False
    }
    
    # Map notification types to email functions
    email_functions = {
        'welcome': send_welcome_email,
        'password_reset': lambda u, **d: send_password_reset_email(u, d.get('reset_token')),
        'application_confirmation': lambda u, **d: send_application_confirmation_email(u, d.get('application')),
        'cashback_approved': lambda u, **d: send_cashback_notification_email(u, d.get('cashback_record')),
        'recommendation': lambda u, **d: send_recommendation_email(u, d),
        'saved_search_results': lambda u, **d: send_saved_search_results_email(u, d)
    }
    
    # Send email notification
    if user.preferred_contact in ['email', 'both'] or not hasattr(user, 'preferred_contact'):
        email_func = email_functions.get(notification_type)
        if email_func:
            results['email'] = email_func(user, **data)
    
    # Send Telegram notification
    if hasattr(user, 'preferred_contact') and user.preferred_contact in ['telegram', 'both']:
        results['telegram'] = send_telegram_notification(user, notification_type, **data)
    
    return results

def send_test_manager_notification(manager_email, telegram_id=None):
    """
    Test all notification channels for a manager
    """
    subject = "InBack: Тестовое уведомление"
    message = "Проверка работы всех каналов уведомлений (Email + Telegram)."
    
    results = {
        'email': send_email(
            to_email=manager_email,
            subject=subject,
            template_name="emails/general_notification.html",
            user_name="Менеджер",
            message=message
        ),
        'telegram': False
    }
    
    if telegram_id:
        import requests
        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': telegram_id,
            'text': f"🔔 <b>InBack Test</b>\n\n{message}",
            'parse_mode': 'HTML'
        }
        try:
            response = requests.post(telegram_url, data=payload, timeout=10)
            results['telegram'] = response.status_code == 200
        except Exception as e:
            print(f"Telegram test failed: {e}")
            
    return results
