"""
PWA Blueprint — manifest.json, sw.js, offline page, push subscribe/unsubscribe.
"""
from flask import Blueprint, jsonify, render_template, request, session
from flask_login import current_user

from app import db

pwa_bp = Blueprint('pwa', __name__)


@pwa_bp.route('/manifest.json')
def pwa_manifest():
    from flask import make_response, send_from_directory, current_app
    response = make_response(send_from_directory('static', 'manifest.json'))
    response.headers['Content-Type'] = 'application/manifest+json'
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


@pwa_bp.route('/sw.js')
def pwa_service_worker():
    from flask import make_response, send_from_directory
    response = make_response(send_from_directory('static', 'sw.js'))
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@pwa_bp.route('/offline')
def pwa_offline():
    return render_template('offline.html')


@pwa_bp.route('/api/pwa/push-subscribe', methods=['POST'])
def pwa_push_subscribe():
    try:
        from models import PushSubscription, User, Manager
        data = request.get_json()
        if not data or 'subscription' not in data:
            return jsonify({'success': False, 'error': 'No subscription data'}), 400
        sub = data['subscription']
        endpoint = sub.get('endpoint', '')
        p256dh = sub.get('keys', {}).get('p256dh', '')
        auth_key = sub.get('keys', {}).get('auth', '')
        user_agent = request.headers.get('User-Agent', '')

        uid = current_user.id if (current_user.is_authenticated and isinstance(current_user._get_current_object(), User)) else None
        mid = current_user.id if (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)) else None
        gs = session.get('guest_chat_session') if not uid and not mid else None

        existing = PushSubscription.query.filter_by(endpoint=endpoint).first()
        if existing:
            existing.p256dh = p256dh
            existing.auth_key = auth_key
            existing.is_active = True
            if uid: existing.user_id = uid
            if mid: existing.manager_id = mid
            if gs:  existing.guest_session = gs
        else:
            new_sub = PushSubscription(
                endpoint=endpoint, p256dh=p256dh, auth_key=auth_key,
                user_id=uid, manager_id=mid, guest_session=gs,
                user_agent=user_agent[:500]
            )
            db.session.add(new_sub)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pwa_bp.route('/api/pwa/push-unsubscribe', methods=['POST'])
def pwa_push_unsubscribe():
    try:
        from models import PushSubscription
        data = request.get_json()
        endpoint = data.get('endpoint', '') if data else ''
        if endpoint:
            PushSubscription.query.filter_by(endpoint=endpoint).delete()
            db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
