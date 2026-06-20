"""
Chat Blueprint — real-time chat API endpoints for guests and managers.
Endpoints: /api/chat/room, /api/chat/send, /api/chat/messages, /api/chat/unread,
           /api/chat/upload, /api/chat/offline-lead, /api/chat/guest-intro,
           /api/chat/presence, /api/chat/presence/leave, /api/chat/operators-status,
           /api/chat/room/<id>/typing, /api/manager/chat/*
"""
import logging
import os
from datetime import datetime

from flask import Blueprint, jsonify, request, current_app, session
from flask_login import current_user, login_required

from app import db, csrf

logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat', __name__)


def __send_chat_push_to_user(room, sender_name, text):
    from app import send_chat_push_to_user
    return _send_chat_push_to_user(room, sender_name, text)


def _send_file_to_telegram(tg_id: str, file_url: str, file_name: str, file_type: str, room_id: int):
    """Forward a chat file attachment to a Telegram chat via Bot API."""
    import os as _os2
    import requests as _req
    token = _os2.environ.get('TELEGRAM_BOT_TOKEN')
    print(f"[TG FILE] called: tg_id={tg_id} file_url={file_url} type={file_type} room={room_id} token={'SET' if token else 'MISSING'}", flush=True)
    if not token:
        print("[TG FILE] ABORT: no TELEGRAM_BOT_TOKEN", flush=True)
        return
    abs_path = _os2.path.join('/home/runner/workspace', file_url.lstrip('/'))
    print(f"[TG FILE] abs_path={abs_path} exists={_os2.path.exists(abs_path)}", flush=True)
    if not _os2.path.exists(abs_path):
        return
    caption = f"📎 Вложение — комната #{room_id}\n📄 {file_name or 'файл'}"
    try:
        is_image = file_type == 'image'
        method = 'sendPhoto' if is_image else 'sendDocument'
        field  = 'photo'    if is_image else 'document'
        api_url = f"https://api.telegram.org/bot{token}/{method}"
        with open(abs_path, 'rb') as fh:
            resp = _req.post(
                api_url,
                data={'chat_id': str(tg_id), 'caption': caption},
                files={field: (file_name or 'file', fh)},
                timeout=30
            )
        print(f"[TG FILE] Telegram response {resp.status_code}: {resp.text[:200]}", flush=True)
        if resp.status_code != 200:
            logging.warning(f"_send_file_to_telegram Telegram error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[TG FILE] exception: {e}", flush=True)
        logging.warning(f"_send_file_to_telegram error: {e}")


def _notify_manager_chat(room, sender_name: str, text: str,
                         file_url=None, file_name=None, file_type=None):
    print(f"[NOTIFY] called: room={room.id} sender={sender_name} text={text[:50] if text else None} file_url={file_url}", flush=True)
    """Send Telegram chat notification to the assigned manager.
    Sends text via send_chat_notify (with reply-routing), then forwards the file if any.
    Falls back to the owner TELEGRAM_CHAT_ID when the manager has no telegram_id set.
    """
    try:
        from scripts.telegram_bot import send_chat_notify
        from telegram_bot import send_telegram_message as _tg_send
        import os as _os

        target_tg_id = None

        if room.manager_id:
            from models import Manager as _Mgr
            mgr = _Mgr.query.get(room.manager_id)
            if mgr and mgr.telegram_id:
                if mgr.notify_telegram:
                    send_chat_notify(mgr.telegram_id, room.id, sender_name, text)
                    target_tg_id = mgr.telegram_id
                else:
                    return  # Manager disabled Telegram notifications

        if target_tg_id is None:
            # Fallback: send to owner TELEGRAM_CHAT_ID
            owner_id = _os.environ.get('TELEGRAM_CHAT_ID')
            if owner_id:
                target_tg_id = owner_id
                preview = text[:200] if text else ''
                label = f"🆕 Сообщение в чат (комната #{room.id})\n👤 {sender_name}: {preview}"
                _tg_send(owner_id, label)
                logging.info(f"_notify_manager_chat: fallback to TELEGRAM_CHAT_ID for room {room.id}")

        # Forward the actual file to Telegram if attachment is present
        if file_url and target_tg_id:
            _send_file_to_telegram(target_tg_id, file_url, file_name or '', file_type or 'document', room.id)

    except Exception as e:
        logging.warning(f"_notify_manager_chat error: {e}")


def _pick_best_manager(preferred_manager_id=None):
    """Pick the best available manager: prefer online+chat_accept, else any active."""
    from models import Manager
    if preferred_manager_id:
        mgr = Manager.query.get(preferred_manager_id)
        if mgr and mgr.is_active:
            return mgr
    # First: online managers who accept chat, ordered by least busy (fewest open rooms)
    from models import ChatRoom as CR
    online = Manager.query.filter_by(is_active=True, is_online=True, chat_accept=True).all()
    if online:
        # pick the one with fewest open rooms
        def load(m):
            return CR.query.filter_by(manager_id=m.id, is_closed=False).count()
        return min(online, key=load)
    # Fallback: any active manager who accepts chat
    mgr = Manager.query.filter_by(is_active=True, chat_accept=True).order_by(Manager.id).first()
    if mgr:
        return mgr
    # Last resort: any active manager
    return Manager.query.filter_by(is_active=True).order_by(Manager.id).first()


def _send_welcome_message(room):
    """Auto-send welcome message to a new chat room if not already sent."""
    from models import ChatMessage, ChatSettings
    if room.welcome_sent:
        return
    welcome_text = ChatSettings.get(
        'welcome_message',
        'Привет! 👋 Я ваш персональный менеджер InBack. Задайте любой вопрос о недвижимости — отвечу быстро!'
    )
    msg = ChatMessage(
        room_id=room.id,
        sender_type='manager',
        sender_id=room.manager_id,
        text=welcome_text,
        is_read_manager=True,
    )
    room.welcome_sent = True
    db.session.add(msg)
    db.session.commit()


def _get_or_create_chat_room(user_id=None, guest_session=None, user_agent=None):
    """Get existing or create new chat room for a user/guest.
    Room is created only when the user actually sends a message (not on first open).
    Welcome message is shown client-side only — no DB record created.
    """
    from models import ChatRoom
    ua = (user_agent or request.headers.get('User-Agent', ''))[:500]
    if user_id:
        room = ChatRoom.query.filter_by(user_id=user_id, is_closed=False).first()
        if not room:
            user = User.query.get(user_id)
            preferred = user.assigned_manager_id if user else None
            mgr = _pick_best_manager(preferred)
            room = ChatRoom(user_id=user_id, manager_id=mgr.id if mgr else None, user_agent=ua)
            db.session.add(room)
            db.session.commit()
        elif not room.user_agent and ua:
            room.user_agent = ua
            db.session.commit()
        return room
    if guest_session:
        room = ChatRoom.query.filter_by(guest_session=guest_session, is_closed=False).first()
        if not room:
            mgr = _pick_best_manager()
            room = ChatRoom(guest_session=guest_session, manager_id=mgr.id if mgr else None, user_agent=ua)
            db.session.add(room)
            db.session.commit()
        elif not room.user_agent and ua:
            room.user_agent = ua
            db.session.commit()
        return room
    return None


@chat_bp.route('/api/chat/room', methods=['GET'])
def api_chat_room():
    """Get chat room info and messages. Does NOT create a room for new guests.
    Room creation happens lazily when the guest sends their first message.
    This prevents empty chat rooms in the manager dashboard.
    """
    from models import ChatRoom, ChatMessage, Manager
    import uuid

    room = None
    msgs = []

    if current_user.is_authenticated and isinstance(current_user._get_current_object(), User):
        # Authenticated users: find existing room (create only if needed)
        room = ChatRoom.query.filter_by(user_id=current_user.id, is_closed=False).first()
        if not room:
            # Authenticated user opening chat for first time — create room
            room = _get_or_create_chat_room(user_id=current_user.id)
    else:
        # Guests: find existing room only — don't create
        gs = session.get('guest_chat_session')
        if not gs:
            gs = str(uuid.uuid4())
            session['guest_chat_session'] = gs
        if gs:
            room = ChatRoom.query.filter_by(guest_session=gs, is_closed=False).first()

    # If room exists, mark manager messages as read and fetch history
    if room:
        ChatMessage.query.filter_by(room_id=room.id, sender_type='manager', is_read_user=False).update({'is_read_user': True})
        db.session.commit()
        msgs = room.messages.order_by(ChatMessage.created_at.asc()).limit(100).all()

    # Always return manager/online info (needed for the welcome animation)
    manager_info = None
    any_online = False

    if room and room.manager_id:
        mgr = Manager.query.get(room.manager_id)
        if mgr:
            any_online = bool(mgr.is_online)
            manager_info = {
                'name': mgr.first_name,
                'position': mgr.display_position,
                'photo': mgr.profile_image,
                'is_online': mgr.is_online,
            }
    if not any_online:
        any_online = Manager.query.filter_by(is_active=True, is_online=True, chat_accept=True).count() > 0
        if any_online and not manager_info:
            # Pick the online manager for the welcome greeting
            best = Manager.query.filter_by(is_active=True, is_online=True, chat_accept=True).first()
            if best:
                manager_info = {
                    'name': best.first_name,
                    'position': best.display_position,
                    'photo': best.profile_image,
                    'is_online': True,
                }

    return jsonify({
        'room_id': room.id if room else None,
        'manager': manager_info,
        'any_online': any_online,
        'messages': [m.to_dict() for m in msgs],
    })


@csrf.exempt
@chat_bp.route('/api/chat/upload', methods=['POST'])
def api_chat_upload():
    """Upload a file attachment for chat (images + documents, max 10 MB)."""
    import uuid, os
    from models import ChatRoom, ChatMessage
    print(f"[UPLOAD] api_chat_upload called, files={list(request.files.keys())}, user_auth={current_user.is_authenticated}", flush=True)
    ALLOWED_IMG = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ALLOWED_DOC = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip'}
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB

    if 'file' not in request.files:
        print(f"[UPLOAD] ERROR: no 'file' in request.files", flush=True)
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename:
        print(f"[UPLOAD] ERROR: empty filename", flush=True)
        return jsonify({'error': 'Empty filename'}), 400

    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    print(f"[UPLOAD] filename={f.filename} ext={ext}", flush=True)
    if ext not in ALLOWED_IMG | ALLOWED_DOC:
        print(f"[UPLOAD] ERROR: bad ext={ext}", flush=True)
        return jsonify({'error': 'Недопустимый тип файла'}), 400

    content = f.read()
    print(f"[UPLOAD] file size={len(content)} bytes", flush=True)
    if len(content) > MAX_SIZE:
        print(f"[UPLOAD] ERROR: file too large", flush=True)
        return jsonify({'error': 'Файл слишком большой (максимум 10 МБ)'}), 400

    try:
        file_type = 'image' if ext in ALLOWED_IMG else 'document'
        safe_name = f.filename.replace(' ', '_')
        unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        save_dir = os.path.join('static', 'uploads', 'chat')
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, unique_name)
        with open(save_path, 'wb') as out:
            out.write(content)
        file_url = f'/static/uploads/chat/{unique_name}'
        print(f"[UPLOAD] saved to {save_path}", flush=True)

        # Create chat message with file
        if current_user.is_authenticated and isinstance(current_user._get_current_object(), User):
            room = _get_or_create_chat_room(user_id=current_user.id)
            sender_type = 'user'
            sender_id = current_user.id
            sender_name = current_user.full_name if hasattr(current_user, 'full_name') else (current_user.first_name or 'Пользователь')
        else:
            gs = session.get('guest_chat_session')
            if not gs:
                gs = str(__import__('uuid').uuid4())
                session['guest_chat_session'] = gs
            room = _get_or_create_chat_room(guest_session=gs)
            sender_type = 'guest'
            sender_id = None
            sender_name = session.get('guest_chat_name') or 'Гость'
            # Save guest name/phone/ua to room if just introduced
            if room and session.get('guest_chat_name') and not room.guest_name:
                room.guest_name = session.get('guest_chat_name')
                room.guest_phone = session.get('guest_chat_phone') or ''
            if room and not room.user_agent:
                room.user_agent = request.headers.get('User-Agent', '')[:500]
        print(f"[UPLOAD] room={getattr(room,'id',None)} sender={sender_name}", flush=True)

        if not room:
            return jsonify({'error': 'No room'}), 500

        msg = ChatMessage(
            room_id=room.id,
            sender_type=sender_type,
            sender_id=sender_id,
            text=None,
            file_url=file_url,
            file_name=f.filename,
            file_type=file_type,
        )
        room.last_message_at = datetime.utcnow()
        db.session.add(msg)
        db.session.commit()
        print(f"[UPLOAD] msg saved id={msg.id} file_url={file_url}", flush=True)

        _notify_manager_chat(room, sender_name, f'📎 Прикреплён файл: {f.filename}',
                             file_url=file_url, file_name=f.filename, file_type=file_type)

        return jsonify({'ok': True, 'message': msg.to_dict()})
    except Exception as _upload_exc:
        print(f"[UPLOAD] EXCEPTION: {type(_upload_exc).__name__}: {_upload_exc}", flush=True)
        import traceback
        traceback.print_exc()
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': str(_upload_exc)}), 500


@chat_bp.route('/api/chat/send', methods=['POST'])
def api_chat_send():
    """Send a message from user/guest."""
    from models import ChatRoom, ChatMessage
    import uuid
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Empty message'}), 400

    if current_user.is_authenticated and isinstance(current_user._get_current_object(), User):
        room = _get_or_create_chat_room(user_id=current_user.id)
        sender_type = 'user'
        sender_id = current_user.id
        sender_name = current_user.full_name if hasattr(current_user, 'full_name') else (current_user.first_name or 'Пользователь')
    else:
        gs = session.get('guest_chat_session')
        if not gs:
            gs = str(uuid.uuid4())
            session['guest_chat_session'] = gs
        room = _get_or_create_chat_room(guest_session=gs)
        sender_type = 'guest'
        sender_id = None
        sender_name = session.get('guest_chat_name') or 'Гость'
        # Save guest name/phone/ua to room on first message if introduced
        if room and session.get('guest_chat_name') and not room.guest_name:
            room.guest_name = session.get('guest_chat_name')
            room.guest_phone = session.get('guest_chat_phone') or ''
        if room and not room.user_agent:
            room.user_agent = request.headers.get('User-Agent', '')[:500]

    if not room:
        return jsonify({'error': 'No room'}), 500

    msg = ChatMessage(room_id=room.id, sender_type=sender_type, sender_id=sender_id, text=text)
    room.last_message_at = datetime.utcnow()
    db.session.add(msg)
    db.session.commit()

    # Send Telegram notification to manager (with reply-routing support)
    _notify_manager_chat(room, sender_name, text)

    return jsonify({'ok': True, 'message': msg.to_dict()})


@chat_bp.route('/api/chat/messages', methods=['GET'])
def api_chat_messages():
    """Poll for new messages (since a given message id)."""
    from models import ChatRoom, ChatMessage
    import uuid
    since_id = request.args.get('since', 0, type=int)

    if current_user.is_authenticated and isinstance(current_user._get_current_object(), User):
        room = ChatRoom.query.filter_by(user_id=current_user.id, is_closed=False).first()
    else:
        gs = session.get('guest_chat_session')
        room = ChatRoom.query.filter_by(guest_session=gs, is_closed=False).first() if gs else None

    if not room:
        return jsonify({'messages': [], 'unread': 0})

    # Mark manager messages as read
    ChatMessage.query.filter_by(room_id=room.id, sender_type='manager', is_read_user=False).update({'is_read_user': True})
    db.session.commit()

    msgs = room.messages.filter(ChatMessage.id > since_id).order_by(ChatMessage.created_at.asc()).all()
    exp = _chat_typing_state.get(room.id)
    is_typing = bool(exp and exp > datetime.utcnow())
    # Highest user message ID that manager has read (for ✓✓ update in client)
    from sqlalchemy import func
    max_read_row = db.session.query(func.max(ChatMessage.id)).filter(
        ChatMessage.room_id == room.id,
        ChatMessage.is_read_manager == True,
        ChatMessage.sender_type.in_(['user', 'guest'])
    ).scalar()
    return jsonify({
        'messages': [m.to_dict() for m in msgs],
        'room_id': room.id,
        'is_typing': is_typing,
        'max_manager_read_id': max_read_row or 0,
    })


@chat_bp.route('/api/chat/unread', methods=['GET'])
def api_chat_unread():
    """Get unread message count badge for the user."""
    from models import ChatRoom, ChatMessage
    count = 0
    if current_user.is_authenticated and isinstance(current_user._get_current_object(), User):
        room = ChatRoom.query.filter_by(user_id=current_user.id, is_closed=False).first()
        if room:
            count = ChatMessage.query.filter_by(room_id=room.id, sender_type='manager', is_read_user=False).count()
    else:
        gs = session.get('guest_chat_session')
        if gs:
            room = ChatRoom.query.filter_by(guest_session=gs, is_closed=False).first()
            if room:
                count = ChatMessage.query.filter_by(room_id=room.id, sender_type='manager', is_read_user=False).count()
    return jsonify({'unread': count})


# ── Manager chat routes ──────────────────────────────────────────────

@chat_bp.route('/api/manager/chat/rooms', methods=['GET'])
def api_manager_chat_rooms():
    """List all chat rooms for the current manager."""
    from models import ChatRoom, ChatMessage, Manager
    from datetime import timedelta
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)):
        return jsonify({'error': 'Unauthorized'}), 403

    rooms = ChatRoom.query.filter_by(manager_id=current_user.id, is_closed=False)\
        .order_by(ChatRoom.last_message_at.desc()).all()

    result = []
    presence_cutoff = datetime.utcnow() - timedelta(seconds=45)
    for room in rooms:
        last = room.last_msg()
        user_name = 'Гость'
        if room.user_id:
            u = User.query.get(room.user_id)
            if u:
                user_name = u.full_name if hasattr(u, 'full_name') else (u.first_name or 'Пользователь')
        elif room.guest_name:
            user_name = room.guest_name
        user_online = _chat_user_presence.get(room.id, datetime.min) > presence_cutoff
        last_text = ''
        if last:
            if last.text:
                last_text = last.text[:60]
            elif last.file_name:
                last_text = f'📎 {last.file_name}'
        unread_count = room.unread_for_manager()
        msk_last = (last.created_at + timedelta(hours=3)) if last else None
        result.append({
            'id': room.id,
            'user_name': user_name,
            'last_message': last_text,
            'last_time': msk_last.strftime('%H:%M') if msk_last else '',
            'unread': unread_count,
            'has_unread': unread_count > 0,
            'user_online': user_online,
        })
    return jsonify({'rooms': result})


@chat_bp.route('/api/manager/chat/<int:room_id>/messages', methods=['GET'])
def api_manager_chat_messages(room_id):
    """Get messages for a specific room (manager view)."""
    from models import ChatRoom, ChatMessage, Manager
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)):
        return jsonify({'error': 'Unauthorized'}), 403

    room = ChatRoom.query.get_or_404(room_id)
    if room.manager_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    since_id = request.args.get('since', 0, type=int)
    # Mark user messages as read
    ChatMessage.query.filter_by(room_id=room.id, sender_type='user', is_read_manager=False).update({'is_read_manager': True})
    ChatMessage.query.filter_by(room_id=room.id, sender_type='guest', is_read_manager=False).update({'is_read_manager': True})
    db.session.commit()

    msgs = room.messages.filter(ChatMessage.id > since_id).order_by(ChatMessage.created_at.asc()).all()
    user_name = 'Гость'
    user_phone = room.guest_phone or ''
    user_email = ''
    if room.user_id:
        u = User.query.get(room.user_id)
        if u:
            user_name = u.full_name if hasattr(u, 'full_name') else (u.first_name or 'Пользователь')
            user_phone = u.phone or ''
            user_email = u.email or ''
    elif room.guest_name:
        user_name = room.guest_name
    # User online status (based on presence heartbeat — 45s window)
    from datetime import timedelta
    presence_cutoff = datetime.utcnow() - timedelta(seconds=45)
    user_online = _chat_user_presence.get(room.id, datetime.min) > presence_cutoff
    last_seen_ts = _chat_user_presence.get(room.id)
    return jsonify({
        'messages': [m.to_dict() for m in msgs],
        'user_name': user_name,
        'user_online': user_online,
        'client': {
            'name': user_name,
            'phone': user_phone,
            'email': user_email,
            'user_agent': room.user_agent or '',
            'first_visit': room.created_at.strftime('%d.%m.%Y %H:%M') if room.created_at else '',
            'last_message': room.last_message_at.strftime('%d.%m.%Y %H:%M') if room.last_message_at else '',
            'last_seen': last_seen_ts.strftime('%H:%M') if last_seen_ts else None,
            'is_guest': room.user_id is None,
        },
    })


@csrf.exempt
@chat_bp.route('/api/manager/chat/<int:room_id>/send', methods=['POST'])
def api_manager_chat_send(room_id):
    """Manager sends a message in a chat room."""
    from models import ChatRoom, ChatMessage, Manager
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)):
        return jsonify({'error': 'Unauthorized'}), 403

    room = ChatRoom.query.get_or_404(room_id)
    if room.manager_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Empty'}), 400

    msg = ChatMessage(room_id=room.id, sender_type='manager', sender_id=current_user.id, text=text, is_read_manager=True)
    room.last_message_at = datetime.utcnow()
    db.session.add(msg)
    db.session.commit()

    # 1. Telegram notification to user
    if room.user_id:
        try:
            from telegram_bot import send_telegram_message
            u = User.query.get(room.user_id)
            if u and u.telegram_id:
                tg_text = (
                    f"💬 Ответ от менеджера {current_user.full_name}:\n"
                    f"✉️ {text[:300]}\n\n"
                    f"🔗 Открыть чат: https://inback.ru/dashboard"
                )
                send_telegram_message(u.telegram_id, tg_text)
        except Exception:
            pass

    # 2. Web Push notification (background push when app closed)
    try:
        from push_service import push_chat_message
        if room.user_id:
            user_obj = User.query.get(room.user_id)
            if user_obj:
                push_chat_message(user_obj, current_user.full_name, text, room.id)
            else:
                _send_chat_push_to_user(room, current_user.full_name, text)
        else:
            _send_chat_push_to_user(room, current_user.full_name, text)
    except Exception:
        pass

    return jsonify({'ok': True, 'message': msg.to_dict()})


@chat_bp.route('/api/manager/chat/unread-total', methods=['GET'])
def api_manager_chat_unread_total():
    """Total unread count across all rooms for manager badge."""
    from models import ChatRoom, ChatMessage, Manager
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)):
        return jsonify({'unread': 0})
    rooms = ChatRoom.query.filter_by(manager_id=current_user.id, is_closed=False).all()
    total = sum(r.unread_for_manager() for r in rooms)
    return jsonify({'unread': total})


@csrf.exempt
@chat_bp.route('/api/manager/chat/heartbeat', methods=['POST'])
def api_manager_chat_heartbeat():
    """Manager pings every ~30s to stay online. Auto-marks offline after 2 min silence."""
    from models import Manager
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)):
        return jsonify({'error': 'Unauthorized'}), 403
    mgr = Manager.query.get(current_user.id)
    mgr.is_online = True
    mgr.last_seen_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'is_online': True})


@csrf.exempt
@chat_bp.route('/api/manager/chat/status', methods=['POST'])
def api_manager_chat_status():
    """Manager manually sets online/offline status."""
    from models import Manager
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)):
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.get_json() or {}
    online = bool(data.get('online', True))
    mgr = Manager.query.get(current_user.id)
    mgr.is_online = online
    if online:
        mgr.last_seen_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'is_online': online})


@csrf.exempt
@chat_bp.route('/api/chat/offline-lead', methods=['POST'])
def api_chat_offline_lead():
    """Save contact from a visitor who came when all operators were offline."""
    from models import CallbackRequest
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    contact = (data.get('contact') or '').strip()
    if not contact:
        return jsonify({'error': 'Contact required'}), 400
    try:
        note = f'Офлайн-чат заявка. Имя: {name or "не указано"}. Контакт: {contact}'
        is_email = '@' in contact
        cb = CallbackRequest(
            name=name or 'Гость',
            phone=contact if not is_email else 'email-only',
            email=contact if is_email else None,
            notes=note,
            status='Новая',
        )
        db.session.add(cb)
        db.session.commit()
        # Notify managers via Telegram
        try:
            from telegram_bot import send_telegram_message
            from models import Manager
            mgrs = Manager.query.filter(
                Manager.is_active == True,
                Manager.telegram_id.isnot(None)
            ).all()
            for m in mgrs:
                send_telegram_message(
                    m.telegram_id,
                    f"📋 <b>Офлайн заявка из чата</b>\n"
                    f"👤 {name or 'Гость'}\n"
                    f"📞 {contact}\n\n"
                    f"<i>Клиент написал когда операторы были офлайн</i>",
                    parse_mode='HTML'
                )
        except Exception:
            pass
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@csrf.exempt
@chat_bp.route('/api/chat/guest-intro', methods=['POST'])
def api_chat_guest_intro():
    """Save guest name and phone to session so messages show the real name."""
    import uuid
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()[:100]
    phone = (data.get('phone') or '').strip()[:30]
    if not name:
        return jsonify({'error': 'name required'}), 400
    if 'guest_chat_session' not in session:
        session['guest_chat_session'] = str(uuid.uuid4())
    session['guest_chat_name'] = name
    if phone:
        session['guest_chat_phone'] = phone
    session.modified = True
    return jsonify({'ok': True})


# In-memory typing state: room_id → expiry datetime (8 seconds TTL)
_chat_typing_state: dict = {}

# In-memory user presence: room_id → last_seen datetime (45 s TTL = online)
_chat_user_presence: dict = {}


@csrf.exempt
@chat_bp.route('/api/chat/presence', methods=['POST'])
def api_chat_presence():
    """User/guest heartbeat while chat is open. Call every 30 s."""
    from models import ChatRoom
    import uuid
    from datetime import timedelta
    if current_user.is_authenticated and isinstance(current_user._get_current_object(), User):
        room = ChatRoom.query.filter_by(user_id=current_user.id, is_closed=False).order_by(ChatRoom.created_at.desc()).first()
    else:
        gs = session.get('guest_chat_session')
        room = ChatRoom.query.filter_by(guest_session=gs, is_closed=False).order_by(ChatRoom.created_at.desc()).first() if gs else None
    if room:
        _chat_user_presence[room.id] = datetime.utcnow()
    return jsonify({'ok': True})


@csrf.exempt
@chat_bp.route('/api/chat/presence/leave', methods=['POST'])
def api_chat_presence_leave():
    """User closed/minimised chat — mark offline immediately."""
    from models import ChatRoom
    if current_user.is_authenticated and isinstance(current_user._get_current_object(), User):
        room = ChatRoom.query.filter_by(user_id=current_user.id, is_closed=False).order_by(ChatRoom.created_at.desc()).first()
    else:
        gs = session.get('guest_chat_session')
        room = ChatRoom.query.filter_by(guest_session=gs, is_closed=False).order_by(ChatRoom.created_at.desc()).first() if gs else None
    if room:
        _chat_user_presence.pop(room.id, None)
    return jsonify({'ok': True})

@chat_bp.route('/api/chat/operators-status', methods=['GET'])
def api_chat_operators_status():
    """Check if any operator is currently online (for chat panel display)."""
    from models import Manager
    # is_online is sticky — no auto-expire. Only explicit toggle changes it.
    online_count = Manager.query.filter_by(is_active=True, is_online=True, chat_accept=True).count()
    return jsonify({'online': online_count > 0, 'count': online_count})

@csrf.exempt
@chat_bp.route('/api/chat/room/<int:room_id>/typing', methods=['POST'])
def api_chat_room_typing(room_id):
    """Bot signals that a manager is typing in this room (short TTL)."""
    from datetime import timedelta
    secret   = request.headers.get('X-Bot-Secret', '')
    expected = os.environ.get('BOT_WEBHOOK_SECRET', 'inback_bot_secret_2024')
    if secret != expected:
        return jsonify({'error': 'Forbidden'}), 403
    _chat_typing_state[room_id] = datetime.utcnow() + timedelta(seconds=8)
    return jsonify({'ok': True})


@csrf.exempt
@chat_bp.route('/api/telegram/chat-file-reply', methods=['POST'])
def api_telegram_chat_file_reply():
    """Endpoint called by Telegram bot when manager replies with a file/photo to a chat notification."""
    import uuid, os
    secret = request.headers.get('X-Bot-Secret', '')
    expected = os.environ.get('BOT_WEBHOOK_SECRET', 'inback_bot_secret_2024')
    if secret != expected:
        return jsonify({'error': 'Forbidden'}), 403

    from models import ChatRoom, ChatMessage, Manager
    room_id = request.form.get('room_id')
    manager_telegram_id = str(request.form.get('telegram_id', ''))
    caption = (request.form.get('caption') or '').strip() or None

    if not room_id:
        return jsonify({'error': 'Missing room_id'}), 400
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400

    mgr = Manager.query.filter_by(telegram_id=manager_telegram_id).first()
    if not mgr:
        return jsonify({'error': 'Manager not found'}), 404

    room = ChatRoom.query.get(int(room_id))
    if not room or room.is_closed:
        return jsonify({'error': 'Room not found or closed'}), 404

    if room.manager_id != mgr.id:
        room.manager_id = mgr.id

    f = request.files['file']
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else 'dat'
    ALLOWED_IMG = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    file_type = 'image' if ext in ALLOWED_IMG else 'document'
    safe_name = f.filename.replace(' ', '_')
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    save_dir = os.path.join('static', 'uploads', 'chat')
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, unique_name)
    f.save(save_path)
    file_url = f'/static/uploads/chat/{unique_name}'

    msg = ChatMessage(
        room_id=room.id,
        sender_type='manager',
        sender_id=mgr.id,
        text=caption,
        file_url=file_url,
        file_name=f.filename,
        file_type=file_type,
        is_read_manager=True,
    )
    room.last_message_at = datetime.utcnow()
    db.session.add(msg)
    db.session.commit()

    return jsonify({'ok': True, 'file_url': file_url, 'message': msg.to_dict()})


@csrf.exempt
@chat_bp.route('/api/telegram/chat-reply', methods=['POST'])
def api_telegram_chat_reply():
    """Endpoint called by Telegram bot when manager replies with #room_id text."""
    secret = request.headers.get('X-Bot-Secret', '')
    expected = os.environ.get('BOT_WEBHOOK_SECRET', 'inback_bot_secret_2024')
    if secret != expected:
        return jsonify({'error': 'Forbidden'}), 403

    from models import ChatRoom, ChatMessage, Manager
    data = request.get_json() or {}
    room_id = data.get('room_id')
    text = (data.get('text') or '').strip()
    manager_telegram_id = str(data.get('telegram_id', ''))

    if not room_id or not text:
        return jsonify({'error': 'Missing room_id or text'}), 400

    # Find manager by telegram_id
    mgr = Manager.query.filter_by(telegram_id=manager_telegram_id).first()
    if not mgr:
        return jsonify({'error': 'Manager not found'}), 404

    room = ChatRoom.query.get(room_id)
    if not room or room.is_closed:
        return jsonify({'error': 'Room not found or closed'}), 404

    # Allow reply even if not assigned — reassign if needed
    if room.manager_id != mgr.id:
        room.manager_id = mgr.id

    msg = ChatMessage(
        room_id=room.id,
        sender_type='manager',
        sender_id=mgr.id,
        text=text,
        is_read_manager=True,
    )
    room.last_message_at = datetime.utcnow()
    db.session.add(msg)
    db.session.commit()

    # Notify user via Telegram if connected
    if room.user_id:
        try:
            from telegram_bot import send_telegram_message
            u = User.query.get(room.user_id)
            if u and getattr(u, 'telegram_id', None):
                send_telegram_message(
                    u.telegram_id,
                    f"💬 <b>Ответ от менеджера {mgr.full_name}:</b>\n\n{text}\n\n"
                    f"<a href='https://inback.ru/krasnodar/'>Открыть сайт InBack</a>",
                    parse_mode='HTML'
                )
        except Exception:
            pass

    return jsonify({'ok': True, 'message': msg.to_dict()})


@csrf.exempt
@chat_bp.route('/api/manager/chat/<int:room_id>/upload', methods=['POST'])
def api_manager_chat_upload(room_id):
    """Manager uploads a file attachment to a chat room."""
    import uuid, os
    from models import ChatRoom, ChatMessage, Manager
    if not (current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager)):
        return jsonify({'error': 'Unauthorized'}), 403

    room = ChatRoom.query.get_or_404(room_id)
    if room.manager_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    ALLOWED_IMG = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ALLOWED_DOC = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip'}
    MAX_SIZE = 10 * 1024 * 1024

    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_IMG | ALLOWED_DOC:
        return jsonify({'error': 'Недопустимый тип файла'}), 400

    content = f.read()
    if len(content) > MAX_SIZE:
        return jsonify({'error': 'Слишком большой файл'}), 400

    file_type = 'image' if ext in ALLOWED_IMG else 'document'
    unique_name = f"{uuid.uuid4().hex[:8]}_{f.filename.replace(' ','_')}"
    save_dir = os.path.join('static', 'uploads', 'chat')
    os.makedirs(save_dir, exist_ok=True)
    with open(os.path.join(save_dir, unique_name), 'wb') as out:
        out.write(content)
    file_url = f'/static/uploads/chat/{unique_name}'

    msg = ChatMessage(
        room_id=room.id, sender_type='manager', sender_id=current_user.id,
        text=None, file_url=file_url, file_name=f.filename, file_type=file_type,
        is_read_manager=True,
    )
    room.last_message_at = datetime.utcnow()
    db.session.add(msg)
    db.session.commit()

    # Notify user via push
    try:
        _send_chat_push_to_user(room, current_user.first_name, f'📎 {f.filename}')
    except Exception:
        pass
