"""
SMS service integration for client notifications
"""
import os
import requests
from typing import Optional

def send_sms(phone: str, message: str) -> bool:
    """
    Send SMS using Russian SMS providers (SMS.ru, SMSC.ru)
    Falls back to console logging for development
    """
    
    # Try SMS.ru first (Russian service)
    sms_ru_api_key = os.environ.get('SMS_RU_API_KEY')
    if sms_ru_api_key:
        try:
            url = 'https://sms.ru/sms/send'
            params = {
                'api_id': sms_ru_api_key,
                'to': phone.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', ''),
                'msg': message,
                'json': 1
            }
            
            response = requests.post(url, params=params, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'OK':
                    print(f"✅ SMS sent via SMS.ru to {phone}")
                    return True
                else:
                    print(f"❌ SMS.ru failed: {result.get('status_text', 'Unknown error')}")
            else:
                print(f"❌ SMS.ru service error: HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ SMS.ru error: {e}")
    
    # Try SMSC.ru as fallback (Russian service)
    smsc_login = os.environ.get('SMSC_LOGIN')
    smsc_password = os.environ.get('SMSC_PASSWORD')
    if smsc_login and smsc_password:
        try:
            url = 'https://smsc.ru/sys/send.php'
            params = {
                'login': smsc_login,
                'psw': smsc_password,
                'phones': phone.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', ''),
                'mes': message,
                'fmt': 3  # JSON response
            }
            
            response = requests.post(url, params=params, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get('error'):
                    print(f"❌ SMSC.ru failed: {result.get('error_code')} - {result.get('error')}")
                else:
                    print(f"✅ SMS sent via SMSC.ru to {phone}")
                    return True
            else:
                print(f"❌ SMSC.ru service error: HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ SMSC.ru error: {e}")
    
    # Development fallback - log to console
    print(f"📱 [DEV] SMS to {phone}: {message}")
    return True  # Return True for development (SMS logged)

def format_phone_for_sms(phone: str) -> str:
    """
    Format phone number for SMS sending
    Convert +7-918-123-45-67 to +79181234567
    """
    if not phone:
        return ""
    
    # Remove all non-digit characters except +
    clean_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
    
    # Ensure proper format
    if clean_phone.startswith('+7'):
        return clean_phone
    elif clean_phone.startswith('7') and len(clean_phone) == 11:
        return '+' + clean_phone
    elif clean_phone.startswith('8') and len(clean_phone) == 11:
        return '+7' + clean_phone[1:]
    
    return clean_phone

def send_login_credentials_sms(phone: str, email: str, password: str, manager_name: str = "", login_url: str = "") -> bool:
    """
    Send login credentials via SMS
    """
    formatted_phone = format_phone_for_sms(phone)
    
    message = f"""InBack.ru - Данные для входа:
Email: {email}
Пароль: {password}
{login_url if login_url else 'Войти на сайте InBack.ru'}
{f'Менеджер: {manager_name}' if manager_name else ''}"""
    
    return send_sms(formatted_phone, message)

def send_welcome_sms(phone: str, client_name: str, manager_name: str = "") -> bool:
    """
    Send welcome SMS to new client
    """
    formatted_phone = format_phone_for_sms(phone)
    
    message = f"""Добро пожаловать в InBack.ru, {client_name}! 
Ваш аккаунт создан. Данные для входа отправлены на email.
{f'Ваш менеджер: {manager_name}' if manager_name else ''}
Тел: 8 (862) 266-62-16"""
    
    return send_sms(formatted_phone, message)

def send_verification_code_sms(phone: str, code: str) -> bool:
    """
    Send phone verification code via SMS
    """
    formatted_phone = format_phone_for_sms(phone)
    
    message = f"""InBack.ru - Код подтверждения: {code}
Никому не сообщайте этот код.
Действителен 10 минут."""
    
    return send_sms(formatted_phone, message)