"""
routes/legal.py — Privacy, legal, consent, and policy pages (extracted from app.py)
"""
from flask import Blueprint, render_template, request, session, g

bp = Blueprint('legal', __name__)

@bp.route('/legal')
def legal_index():
    """Legal documents hub page"""
    return render_template('legal/index.html')

@bp.route('/privacy-policy')
def privacy_policy():
    """Privacy policy page — redirect to unified legal hub"""
    from flask import redirect, url_for
    return redirect(url_for('legal.legal_index') + '?tab=privacy')

@bp.route('/user-agreement')
def user_agreement():
    """User agreement page"""
    return render_template('legal/user_agreement.html')

@bp.route('/public-offer')
def public_offer():
    return render_template('legal/public_offer.html')

@bp.route('/cookie-policy')
def cookie_policy():
    """Cookie policy page"""
    return render_template('legal/cookie_policy.html')

@bp.route('/consent/registration')
def consent_registration():
    """Consent for registration"""
    return render_template('legal/consent_registration.html')

@bp.route('/consent/cashback')
def consent_cashback():
    """Consent for cashback"""
    return render_template('legal/consent_cashback.html')

@bp.route('/consent/marketing')
def consent_marketing():
    """Consent for marketing"""
    return render_template('legal/consent_marketing.html')

@bp.route('/consent/callback')
def consent_callback():
    """Consent for callback"""
    return render_template('legal/consent_callback.html')

@bp.route('/consent/cookies')
def consent_cookies():
    """Consent for cookies"""
    return render_template('legal/consent_cookies.html')

def parse_user_agent(user_agent):
    """Простой парсинг User-Agent строки"""
    info = {
        'raw': user_agent,
        'browser': 'Неизвестно',
        'version': 'Неизвестно',
        'os': 'Неизвестно',
        'device': 'Неизвестно'
    }
    
    # Определяем браузер
    if 'Chrome' in user_agent and 'Edg' not in user_agent:
        info['browser'] = 'Chrome'
        if 'Chrome/' in user_agent:
            version = user_agent.split('Chrome/')[1].split()[0]
            info['version'] = version
    elif 'Firefox' in user_agent:
        info['browser'] = 'Firefox'
        if 'Firefox/' in user_agent:
            version = user_agent.split('Firefox/')[1].split()[0]
            info['version'] = version
    elif 'Edg' in user_agent:
        info['browser'] = 'Microsoft Edge'
        if 'Edg/' in user_agent:
            version = user_agent.split('Edg/')[1].split()[0]
            info['version'] = version
    elif 'Safari' in user_agent and 'Chrome' not in user_agent:
        info['browser'] = 'Safari'
        if 'Version/' in user_agent:
            version = user_agent.split('Version/')[1].split()[0]
            info['version'] = version
    
    # Определяем ОС
    if 'Windows NT' in user_agent:
        info['os'] = 'Windows'
        if 'Windows NT 10.0' in user_agent:
            info['os'] = 'Windows 10/11'
    elif 'Mac OS X' in user_agent:
        info['os'] = 'macOS'
    elif 'Linux' in user_agent:
        info['os'] = 'Linux'
    elif 'Android' in user_agent:
        info['os'] = 'Android'
    elif 'iPhone' in user_agent:
        info['os'] = 'iOS'
    
    # Определяем тип устройства
    if 'Mobile' in user_agent or 'Android' in user_agent or 'iPhone' in user_agent:
        info['device'] = 'Мобильное устройство'
    elif 'Tablet' in user_agent or 'iPad' in user_agent:
        info['device'] = 'Планшет'
    else:
        info['device'] = 'Десктоп'
    
    return info

@bp.route('/technical-info')
def technical_info_redirect():
    """Redirect to legal hub — technical info is now admin-only"""
    from flask import redirect
    return redirect('/legal')

@bp.route('/admin/technical-info')
def technical_info():
    """Страница технической информации с данными о сессии и устройстве"""
    import platform
    import socket
    import uuid
    import secrets
    from datetime import datetime
    from flask_login import current_user
    
    # Генерируем session_id если его нет
    if 'session_id' not in session:
        session['session_id'] = secrets.token_hex(16)
    
    # Парсим User-Agent для более детальной информации
    user_agent = request.headers.get('User-Agent', '')
    browser_info = parse_user_agent(user_agent)
    
    # Собираем техническую информацию
    tech_info = {
        'server_info': {
            'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'hostname': socket.gethostname(),
            'flask_version': '2.3.3',  # или получить динамически
            'environment': 'development'
        },
        'session_info': {
            'session_id': session.get('session_id'),
            'user_id': current_user.id if current_user.is_authenticated else 'Не авторизован',
            'username': current_user.full_name if current_user.is_authenticated and hasattr(current_user, 'full_name') else 'Гость',
            'is_authenticated': current_user.is_authenticated,
            'session_permanent': session.permanent
        },
        'request_info': {
            'user_agent': user_agent,
            'ip_address': request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr),
            'method': request.method,
            'url': request.url,
            'referrer': request.headers.get('Referer', 'Прямой переход'),
            'accept_language': request.headers.get('Accept-Language', 'Неизвестно'),
            'accept_encoding': request.headers.get('Accept-Encoding', 'Неизвестно'),
            'content_type': request.headers.get('Content-Type', 'Неизвестно'),
            'host': request.headers.get('Host', 'Неизвестно')
        },
        'browser_info': browser_info
    }
    
    return render_template('technical_info.html', tech_info=tech_info)

@bp.route('/data-processing-consent')
def data_processing_consent():
    """Data processing consent page — redirect to unified legal hub"""
    from flask import redirect, url_for
    return redirect(url_for('legal.legal_index') + '?tab=consent')

# Override Flask-Login unauthorized handler for API routes
