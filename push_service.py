"""
Centralized Web Push notification service for InBack.
Respects user notification preferences (notify_* columns).
Sends rich browser push notifications like major property platforms (CIAN, Avito, Domclick).
"""
import logging
import json
from datetime import datetime

log = logging.getLogger(__name__)

# ── Icons per notification category ───────────────────────────────────────────
_ICONS = {
    'default':     '/static/images/icon-192.png',
    'chat':        '/static/images/icon-192.png',
    'deal':        '/static/images/icon-192.png',
    'cashback':    '/static/images/icon-192.png',
    'search':      '/static/images/icon-192.png',
    'application': '/static/images/icon-192.png',
    'marketing':   '/static/images/icon-192.png',
}
_BADGE = '/static/images/badge-72.png'


# ── Low-level sender ───────────────────────────────────────────────────────────

def _send_one(sub, payload: dict) -> bool:
    """Send a single Web Push notification. Auto-deactivates expired subscriptions."""
    try:
        from pywebpush import webpush
        from flask import current_app
        webpush(
            subscription_info={
                'endpoint': sub.endpoint,
                'keys': {'p256dh': sub.p256dh, 'auth': sub.auth_key},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=current_app.config['VAPID_PRIVATE_KEY'],
            vapid_claims=current_app.config['VAPID_CLAIMS'],
        )
        return True
    except Exception as e:
        status = getattr(getattr(e, 'response', None), 'status_code', None)
        if status in (404, 410):
            try:
                from app import db
                sub.is_active = False
                db.session.commit()
            except Exception:
                pass
        log.warning(f'[Push] Failed for sub {sub.id}: {e}')
        return False


def _get_user_subs(user_id):
    from models import PushSubscription
    return PushSubscription.query.filter_by(user_id=user_id, is_active=True).all()


def _is_night() -> bool:
    """Returns True between 22:00 and 08:00 Moscow time (UTC+3)."""
    hour = (datetime.utcnow().hour + 3) % 24
    return hour >= 22 or hour < 8


def _send_to_user(user, payload: dict, pref_field: str = None, skip_night: bool = True):
    """
    Send push to all active subscriptions of a user.
    Checks the user's preference column (pref_field) before sending.
    Skips sending at night for non-urgent (marketing) events.
    """
    if user is None:
        return
    if pref_field and not getattr(user, pref_field, True):
        return  # user opted out
    if skip_night and _is_night():
        return  # don't disturb at night
    subs = _get_user_subs(user.id)
    for sub in subs:
        _send_one(sub, payload)


# ── Public notification functions ──────────────────────────────────────────────

def push_chat_message(user, manager_name: str, text: str, room_id: int):
    """Manager replied in chat — highest priority, no night-skip."""
    payload = {
        'title': f'InBack: ответ от {manager_name}',
        'body': text[:120],
        'icon': _ICONS['chat'],
        'badge': _BADGE,
        'tag': f'chat-{room_id}',
        'requireInteraction': False,
        'actions': [
            {'action': 'open_chat', 'title': '💬 Открыть чат'},
        ],
        'data': {'url': '/dashboard?tab=chat', 'room_id': room_id},
    }
    _send_to_user(user, payload, pref_field=None, skip_night=False)


def push_deal_stage_changed(user, deal_number: str, old_label: str, new_label: str,
                             complex_name: str = '', deal_id: int = None):
    """Deal moved to a new pipeline stage."""
    body = f'Сделка {deal_number}'
    if complex_name:
        body += f' · {complex_name}'
    body += f'\n{old_label} → {new_label}'
    payload = {
        'title': 'InBack: статус сделки изменён',
        'body': body[:200],
        'icon': _ICONS['deal'],
        'badge': _BADGE,
        'tag': f'deal-stage-{deal_id or deal_number}',
        'requireInteraction': False,
        'actions': [
            {'action': 'view_deal', 'title': '📋 Открыть сделку'},
        ],
        'data': {'url': '/dashboard#deals'},
    }
    _send_to_user(user, payload, pref_field='notify_applications')


def push_cashback_paid(user, amount: str, complex_name: str = ''):
    """Cashback has been credited to user."""
    body = f'Вам начислен кешбэк {amount} ₽'
    if complex_name:
        body += f' за {complex_name}'
    payload = {
        'title': '💰 InBack: кешбэк начислен!',
        'body': body[:200],
        'icon': _ICONS['cashback'],
        'badge': _BADGE,
        'tag': 'cashback-paid',
        'requireInteraction': True,
        'actions': [
            {'action': 'view_balance', 'title': '💳 Мой баланс'},
        ],
        'data': {'url': '/dashboard#cashback'},
    }
    _send_to_user(user, payload, pref_field='notify_cashback', skip_night=False)


def push_application_confirmed(user, property_title: str, viewing_date: str = ''):
    """Viewing / application has been confirmed."""
    body = f'Заявка на просмотр подтверждена: {property_title}'
    if viewing_date:
        body += f'\n📅 {viewing_date}'
    payload = {
        'title': 'InBack: заявка подтверждена',
        'body': body[:200],
        'icon': _ICONS['application'],
        'badge': _BADGE,
        'tag': 'application-confirmed',
        'requireInteraction': False,
        'actions': [
            {'action': 'view_apps', 'title': '📋 Мои заявки'},
        ],
        'data': {'url': '/dashboard#applications'},
    }
    _send_to_user(user, payload, pref_field='notify_applications')


def push_saved_search_match(user, count: int, title: str, url: str = '/dashboard#saved-searches'):
    """New properties found matching user's saved search."""
    body = f'Найдено {count} новых объект{"ов" if count > 4 else "а" if count > 1 else ""}' \
           f' по запросу «{title[:60]}»'
    payload = {
        'title': 'InBack: новые объекты по вашему запросу',
        'body': body[:200],
        'icon': _ICONS['search'],
        'badge': _BADGE,
        'tag': f'saved-search-match',
        'requireInteraction': False,
        'actions': [
            {'action': 'view_results', 'title': '🔍 Смотреть'},
        ],
        'data': {'url': url},
    }
    _send_to_user(user, payload, pref_field='notify_saved_searches')


def push_price_drop(user, complex_name: str, old_price: str, new_price: str, url: str = '/'):
    """Price dropped on a complex the user has favorited."""
    body = f'{complex_name}\n{old_price} → {new_price} ₽  📉'
    payload = {
        'title': 'InBack: снижение цены',
        'body': body[:200],
        'icon': _ICONS['search'],
        'badge': _BADGE,
        'tag': f'price-drop',
        'requireInteraction': False,
        'actions': [
            {'action': 'view_complex', 'title': '🏠 Смотреть ЖК'},
        ],
        'data': {'url': url},
    }
    _send_to_user(user, payload, pref_field='notify_recommendations')


def push_marketing(user, title: str, body: str, url: str = '/'):
    """Promotional push (user must have opted in)."""
    payload = {
        'title': title[:80],
        'body': body[:200],
        'icon': _ICONS['marketing'],
        'badge': _BADGE,
        'tag': 'marketing',
        'requireInteraction': False,
        'data': {'url': url},
    }
    _send_to_user(user, payload, pref_field='notify_marketing')


# ── Manager push (for manager PWA / web panel) ────────────────────────────────

def push_manager_new_lead(manager, lead_name: str, phone: str = ''):
    """New lead assigned to this manager."""
    from models import PushSubscription
    subs = PushSubscription.query.filter_by(manager_id=manager.id, is_active=True).all() \
        if hasattr(PushSubscription, 'manager_id') else []
    body = f'Новый клиент: {lead_name}'
    if phone:
        body += f'\n📞 {phone}'
    payload = {
        'title': 'InBack: новый лид',
        'body': body[:200],
        'icon': _ICONS['default'],
        'badge': _BADGE,
        'tag': 'manager-new-lead',
        'requireInteraction': True,
        'actions': [
            {'action': 'view_lead', 'title': '👤 Открыть'},
        ],
        'data': {'url': '/manager/clients'},
    }
    for sub in subs:
        _send_one(sub, payload)


def send_web_push(subscription_obj, payload_dict: dict) -> bool:
    """Backward-compatible wrapper used by chat routes in app.py."""
    return _send_one(subscription_obj, payload_dict)


def send_chat_push_to_user(room, manager_name: str, text: str):
    """Send a Web Push to all active subscriptions belonging to the room's user/guest."""
    try:
        from models import PushSubscription
        if room.user_id:
            subs = PushSubscription.query.filter_by(user_id=room.user_id, is_active=True).all()
        elif room.guest_session:
            subs = PushSubscription.query.filter_by(guest_session=room.guest_session, is_active=True).all()
        else:
            return
        payload = {
            'title': 'InBack — ответ менеджера',
            'body': f'{manager_name}: {text[:100]}',
            'icon': _ICONS['chat'],
            'badge': _BADGE,
            'tag': f'chat-{room.id}',
            'requireInteraction': False,
            'data': {'url': '/dashboard?tab=chat', 'room_id': room.id},
        }
        for sub in subs:
            _send_one(sub, payload)
    except Exception as e:
        log.warning(f'send_chat_push_to_user error: {e}')


def push_manager_new_chat(manager, client_name: str, text: str, room_id: int):
    """User sent a message in chat — notify manager."""
    from models import PushSubscription
    subs = PushSubscription.query.filter_by(manager_id=manager.id, is_active=True).all() \
        if hasattr(PushSubscription, 'manager_id') else []
    payload = {
        'title': f'InBack: сообщение от {client_name}',
        'body': text[:120],
        'icon': _ICONS['chat'],
        'badge': _BADGE,
        'tag': f'mgr-chat-{room_id}',
        'requireInteraction': False,
        'actions': [
            {'action': 'open_chat', 'title': '💬 Ответить'},
        ],
        'data': {'url': f'/manager/chat/{room_id}'},
    }
    for sub in subs:
        _send_one(sub, payload)
