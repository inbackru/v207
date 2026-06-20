import os
import json
import hashlib
import hmac
import time
import secrets
import random
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

import requests
from flask import Blueprint, redirect, request, url_for, session, flash, current_app
from flask_login import login_user
from werkzeug.security import generate_password_hash

from app import db

social_auth = Blueprint('social_auth', __name__)

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '')
VK_CLIENT_ID = os.environ.get('VK_CLIENT_ID', '')
VK_CLIENT_SECRET = os.environ.get('VK_CLIENT_SECRET', '')
MAILRU_CLIENT_ID = os.environ.get('MAILRU_CLIENT_ID', '')
MAILRU_CLIENT_SECRET = os.environ.get('MAILRU_CLIENT_SECRET', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_BOT_USERNAME = os.environ.get('TELEGRAM_BOT_USERNAME', 'InBackBot')


def get_base_url():
    if os.environ.get('REPLIT_DEV_DOMAIN'):
        return f"https://{os.environ['REPLIT_DEV_DOMAIN']}"
    return request.url_root.rstrip('/')


def get_or_create_user(email, full_name, provider, social_id, avatar_url=None, account_type='user'):
    from models import User, Partner

    if account_type == 'partner':
        return _get_or_create_partner(email, full_name, provider, social_id, avatar_url)

    user = None
    if email:
        user = User.query.filter_by(email=email).first()
    if not user and social_id:
        user = User.query.filter(User.social_provider == provider, User.social_id == str(social_id)).first()

    if user:
        if not user.social_provider:
            user.social_provider = provider
            user.social_id = str(social_id)
        if avatar_url and not user.social_avatar:
            user.social_avatar = avatar_url
        user.last_login = datetime.utcnow()
        db.session.commit()
        return user

    phone_placeholder = f"+7000{random.randint(1000000, 9999999)}"
    while User.query.filter_by(phone=phone_placeholder).first():
        phone_placeholder = f"+7000{random.randint(1000000, 9999999)}"

    user_id_num = f"CB{random.randint(10000000, 99999999)}"
    while User.query.filter_by(user_id=user_id_num).first():
        user_id_num = f"CB{random.randint(10000000, 99999999)}"

    user = User(
        email=email,
        phone=phone_placeholder,
        full_name=full_name or (email.split('@')[0] if email else 'User'),
        user_id=user_id_num,
        social_provider=provider,
        social_id=str(social_id),
        social_avatar=avatar_url,
        phone_verified=False,
        profile_completed=bool(full_name),
        is_active=True,
        is_verified=True,
        registration_source=f'OAuth:{provider}',
        balance=Decimal('0.00'),
        registration_bonus=Decimal('10000.00'),
        total_earned=Decimal('0.00'),
        total_withdrawn=Decimal('0.00'),
    )
    db.session.add(user)
    db.session.commit()
    return user


def _get_or_create_partner(email, full_name, provider, social_id, avatar_url):
    from models import Partner

    partner = None
    if email:
        partner = Partner.query.filter_by(email=email).first()
    if not partner and social_id:
        partner = Partner.query.filter(Partner.social_provider == provider, Partner.social_id == str(social_id)).first()

    if partner:
        if not partner.social_provider:
            partner.social_provider = provider
            partner.social_id = str(social_id)
        partner.last_login = datetime.utcnow()
        db.session.commit()
        return partner

    phone_placeholder = f"+7000{random.randint(1000000, 9999999)}"
    while Partner.query.filter_by(phone=phone_placeholder).first():
        phone_placeholder = f"+7000{random.randint(1000000, 9999999)}"

    name_parts = (full_name or '').split(' ', 1)
    first_name = name_parts[0] if name_parts else (email.split('@')[0] if email else 'Partner')
    last_name = name_parts[1] if len(name_parts) > 1 else ''

    partner = Partner(
        email=email,
        phone=phone_placeholder,
        first_name=first_name,
        last_name=last_name,
        social_provider=provider,
        social_id=str(social_id),
        social_avatar=avatar_url,
        is_active=True,
    )
    db.session.add(partner)
    db.session.commit()
    return partner


def login_social_user(user_or_partner, account_type='user'):
    from models import Partner
    if account_type == 'partner' and isinstance(user_or_partner, Partner):
        session['p_partner_id'] = user_or_partner.id
        session['p_partner_name'] = user_or_partner.full_name
        session['is_partner'] = True
        user_or_partner.last_login = datetime.utcnow()
        db.session.commit()
    else:
        login_user(user_or_partner, remember=True)


# =============================================================================
# GOOGLE OAuth 2.0
# =============================================================================

@social_auth.route('/auth/google')
def google_login():
    if not GOOGLE_CLIENT_ID:
        flash('Google авторизация временно недоступна', 'error')
        return redirect(_get_return_url())

    account_type = request.args.get('type', 'user')
    session['social_auth_type'] = account_type

    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state

    redirect_uri = get_base_url() + '/auth/google/callback'
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'offline',
        'prompt': 'select_account',
    }
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@social_auth.route('/auth/google/callback')
def google_callback():
    if request.args.get('state') != session.pop('oauth_state', None):
        flash('Ошибка безопасности. Попробуйте ещё раз.', 'error')
        return redirect(_get_return_url())

    code = request.args.get('code')
    if not code:
        flash('Авторизация отменена', 'error')
        return redirect(_get_return_url())

    try:
        redirect_uri = get_base_url() + '/auth/google/callback'
        token_resp = requests.post('https://oauth2.googleapis.com/token', data={
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,
        }, timeout=10)

        if token_resp.status_code != 200:
            flash('Ошибка авторизации через Google', 'error')
            return redirect(_get_return_url())

        token_data = token_resp.json()
        access_token = token_data.get('access_token')
        if not access_token:
            flash('Ошибка авторизации через Google', 'error')
            return redirect(_get_return_url())

        userinfo = requests.get('https://www.googleapis.com/oauth2/v2/userinfo',
                                headers={'Authorization': f'Bearer {access_token}'}, timeout=10).json()

        email = userinfo.get('email')
        name = userinfo.get('name', '')
        picture = userinfo.get('picture', '')
        google_id = userinfo.get('id')

        if not email or not google_id:
            flash('Не удалось получить email от Google', 'error')
            return redirect(_get_return_url())

        account_type = session.pop('social_auth_type', 'user')
        user = get_or_create_user(email, name, 'google', google_id, picture, account_type)
        login_social_user(user, account_type)

        flash(f'Вы вошли через Google как {name}', 'success')
        return redirect(_get_redirect_after_login(account_type))
    except Exception:
        flash('Ошибка авторизации через Google. Попробуйте позже.', 'error')
        return redirect(_get_return_url())


# =============================================================================
# VK OAuth 2.0
# =============================================================================

@social_auth.route('/auth/vk')
def vk_login():
    if not VK_CLIENT_ID:
        flash('VK авторизация временно недоступна', 'error')
        return redirect(_get_return_url())

    account_type = request.args.get('type', 'user')
    session['social_auth_type'] = account_type

    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state

    redirect_uri = get_base_url() + '/auth/vk/callback'
    params = {
        'client_id': VK_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'display': 'page',
        'scope': 'email',
        'response_type': 'code',
        'state': state,
        'v': '5.131',
    }
    return redirect(f"https://oauth.vk.com/authorize?{urlencode(params)}")


@social_auth.route('/auth/vk/callback')
def vk_callback():
    if request.args.get('state') != session.pop('oauth_state', None):
        flash('Ошибка безопасности. Попробуйте ещё раз.', 'error')
        return redirect(_get_return_url())

    code = request.args.get('code')
    if not code:
        flash('Авторизация отменена', 'error')
        return redirect(_get_return_url())

    try:
        redirect_uri = get_base_url() + '/auth/vk/callback'
        token_resp = requests.post('https://oauth.vk.com/access_token', data={
            'client_id': VK_CLIENT_ID,
            'client_secret': VK_CLIENT_SECRET,
            'redirect_uri': redirect_uri,
            'code': code,
        }, timeout=10)

        if token_resp.status_code != 200:
            flash('Ошибка авторизации через VK', 'error')
            return redirect(_get_return_url())

        token_data = token_resp.json()
        access_token = token_data.get('access_token')
        vk_user_id = token_data.get('user_id')
        if not access_token or not vk_user_id:
            flash('Ошибка авторизации через VK', 'error')
            return redirect(_get_return_url())

        email = token_data.get('email')

        user_resp = requests.get('https://api.vk.com/method/users.get', params={
            'access_token': access_token,
            'fields': 'photo_200,first_name,last_name',
            'v': '5.131',
        }, timeout=10).json()

        vk_user = user_resp.get('response', [{}])[0] if user_resp.get('response') else {}
        first_name = vk_user.get('first_name', '')
        last_name = vk_user.get('last_name', '')
        full_name = f"{first_name} {last_name}".strip()
        avatar = vk_user.get('photo_200', '')

        account_type = session.pop('social_auth_type', 'user')
        user = get_or_create_user(email, full_name, 'vk', vk_user_id, avatar, account_type)
        login_social_user(user, account_type)

        flash(f'Вы вошли через VK как {full_name}', 'success')
        return redirect(_get_redirect_after_login(account_type))
    except Exception:
        flash('Ошибка авторизации через VK. Попробуйте позже.', 'error')
        return redirect(_get_return_url())


# =============================================================================
# MAIL.RU OAuth 2.0
# =============================================================================

@social_auth.route('/auth/mailru')
def mailru_login():
    if not MAILRU_CLIENT_ID:
        flash('Mail.ru авторизация временно недоступна', 'error')
        return redirect(_get_return_url())

    account_type = request.args.get('type', 'user')
    session['social_auth_type'] = account_type

    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state

    redirect_uri = get_base_url() + '/auth/mailru/callback'
    params = {
        'client_id': MAILRU_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'userinfo',
        'state': state,
    }
    return redirect(f"https://oauth.mail.ru/login?{urlencode(params)}")


@social_auth.route('/auth/mailru/callback')
def mailru_callback():
    if request.args.get('state') != session.pop('oauth_state', None):
        flash('Ошибка безопасности. Попробуйте ещё раз.', 'error')
        return redirect(_get_return_url())

    code = request.args.get('code')
    if not code:
        flash('Авторизация отменена', 'error')
        return redirect(_get_return_url())

    try:
        redirect_uri = get_base_url() + '/auth/mailru/callback'
        token_resp = requests.post('https://oauth.mail.ru/token', data={
            'client_id': MAILRU_CLIENT_ID,
            'client_secret': MAILRU_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
        }, timeout=10)

        if token_resp.status_code != 200:
            flash('Ошибка авторизации через Mail.ru', 'error')
            return redirect(_get_return_url())

        token_data = token_resp.json()
        access_token = token_data.get('access_token')
        if not access_token:
            flash('Ошибка авторизации через Mail.ru', 'error')
            return redirect(_get_return_url())

        userinfo = requests.get('https://oauth.mail.ru/userinfo',
                                params={'access_token': access_token}, timeout=10).json()

        email = userinfo.get('email')
        first_name = userinfo.get('first_name', '')
        last_name = userinfo.get('last_name', '')
        full_name = f"{first_name} {last_name}".strip() or userinfo.get('name', '')
        avatar = userinfo.get('image', '')
        mailru_id = userinfo.get('id')

        if not email or not mailru_id:
            flash('Не удалось получить email от Mail.ru', 'error')
            return redirect(_get_return_url())

        account_type = session.pop('social_auth_type', 'user')
        user = get_or_create_user(email, full_name, 'mailru', mailru_id, avatar, account_type)
        login_social_user(user, account_type)

        flash(f'Вы вошли через Mail.ru как {full_name}', 'success')
        return redirect(_get_redirect_after_login(account_type))
    except Exception:
        flash('Ошибка авторизации через Mail.ru. Попробуйте позже.', 'error')
        return redirect(_get_return_url())


# =============================================================================
# TELEGRAM Login Widget
# =============================================================================

@social_auth.route('/auth/telegram/callback')
def telegram_callback():
    if not TELEGRAM_BOT_TOKEN:
        flash('Telegram авторизация временно недоступна', 'error')
        return redirect(_get_return_url())

    data = {k: v for k, v in request.args.items() if k != 'hash'}
    received_hash = request.args.get('hash', '')

    check_string = '\n'.join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if computed_hash != received_hash:
        flash('Ошибка проверки данных Telegram', 'error')
        return redirect(_get_return_url())

    auth_date = int(data.get('auth_date', 0))
    if time.time() - auth_date > 86400:
        flash('Данные авторизации устарели. Попробуйте ещё раз.', 'error')
        return redirect(_get_return_url())

    tg_id = data.get('id')
    first_name = data.get('first_name', '')
    last_name = data.get('last_name', '')
    username = data.get('username', '')
    photo_url = data.get('photo_url', '')
    full_name = f"{first_name} {last_name}".strip()

    account_type = request.args.get('type', session.pop('social_auth_type', 'user'))
    user = get_or_create_user(None, full_name, 'telegram', tg_id, photo_url, account_type)

    if username and hasattr(user, 'telegram_id'):
        user.telegram_id = str(tg_id)
        db.session.commit()

    login_social_user(user, account_type)

    flash(f'Вы вошли через Telegram как {full_name}', 'success')
    return redirect(_get_redirect_after_login(account_type))


# =============================================================================
# Helpers
# =============================================================================

def _get_return_url():
    account_type = session.get('social_auth_type', 'user')
    if account_type == 'partner':
        return url_for('partner_login')
    return url_for('login')


def _get_redirect_after_login(account_type):
    if account_type == 'partner':
        return '/partner/dashboard'
    return url_for('user_dashboard')


def social_auth_available():
    telegram_bot_id = TELEGRAM_BOT_TOKEN.split(':')[0] if TELEGRAM_BOT_TOKEN and ':' in TELEGRAM_BOT_TOKEN else ''
    return {
        'google': bool(GOOGLE_CLIENT_ID),
        'vk': bool(VK_CLIENT_ID),
        'mailru': bool(MAILRU_CLIENT_ID),
        'telegram': bool(TELEGRAM_BOT_TOKEN),
        'telegram_bot_id': telegram_bot_id,
    }
