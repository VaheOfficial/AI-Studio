"""Durable owner notifications and explicitly enabled encrypted browser push."""
from __future__ import annotations
import asyncio
import base64
import json
import time
import uuid
from urllib.parse import urlsplit
from .. import db
from ..schemas import EvDone, EvError, EvToolApproval, EvToolCall
from ..schemas_agents import AgentNotification, NotificationSettings
from . import devices, store, vault

_deliveries: set[asyncio.Task] = set()


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_notifications (id TEXT PRIMARY KEY, receipt TEXT UNIQUE NOT NULL, session_id TEXT NOT NULL, data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS agent_push_subscriptions (id TEXT PRIMARY KEY, device_id TEXT NOT NULL, data TEXT NOT NULL)')


def settings():
    return NotificationSettings.model_validate(db.get_setting_values().get('agents.notifications') or {})


def configure(body):
    if not body.contact.startswith(('mailto:', 'https://')):
        raise ValueError('Push contact must be a mailto or HTTPS address')
    if body.web_push:
        public_key()
    db.set_setting_value('agents.notifications', body.model_dump())
    store.notify('notifications')
    return body


def public_key():
    values = db.get_setting_values()
    if not values.get('agents.vapid_private'):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key = ec.generate_private_key(ec.SECP256R1())
        private = base64.urlsafe_b64encode(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode().rstrip('=')
        public = base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')
        db.set_setting_value('agents.vapid_private', vault.protect(private))
        db.set_setting_value('agents.vapid_public', public)
    return db.get_setting_values()['agents.vapid_public']


def subscribe(device, body):
    host = urlsplit(body.endpoint)
    allowed = ('fcm.googleapis.com', 'updates.push.services.mozilla.com', 'push.services.mozilla.com', 'push.apple.com', 'wns.windows.com', 'notify.windows.com')
    if host.scheme != 'https' or not host.hostname or host.username or host.password or host.fragment or not any(host.hostname == name or host.hostname.endswith('.' + name) for name in allowed):
        raise ValueError('Unsupported browser push service endpoint')
    if set(body.keys) != {'p256dh','auth'} or any(not 1 <= len(value) <= 500 for value in body.keys.values()):
        raise ValueError('Invalid push encryption keys')
    identity = uuid.uuid5(uuid.NAMESPACE_URL, body.endpoint).hex
    db.execute('INSERT INTO agent_push_subscriptions VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET device_id=excluded.device_id,data=excluded.data', (identity, device.id, vault.protect(body.model_dump_json())))
    return {'id': identity}


def list_all(sid=None):
    return [AgentNotification.model_validate_json(row['data']) for row in db.query('SELECT data FROM agent_notifications WHERE (? IS NULL OR session_id=?) ORDER BY rowid DESC LIMIT 200', (sid,sid))]


def mark_read(key):
    row = db.query_one('SELECT data FROM agent_notifications WHERE id=?', (key,))
    if not row:
        raise ValueError('Notification not found')
    value = AgentNotification.model_validate_json(row['data']); value.read = True
    db.execute('UPDATE agent_notifications SET data=? WHERE id=?', (value.model_dump_json(),key))
    store.notify('notifications', value.session_id)


def save(sid, kind, title, body, receipt):
    if not db.get_session(sid):
        return None
    value = AgentNotification(id=uuid.uuid4().hex[:16], session_id=sid, kind=kind, title=title[:160], body=body[:300], created_at=db.now_iso())
    if not db.execute('INSERT OR IGNORE INTO agent_notifications VALUES(?,?,?,?)', (value.id, receipt, sid, value.model_dump_json())):
        return None
    store.notify('notifications', sid)
    if settings().web_push or settings().native_desktop:
        task = asyncio.create_task(deliver(value), name='owner-notification-' + value.id)
        _deliveries.add(task); task.add_done_callback(_deliveries.discard)
    return value


def observe(sid, event):
    if isinstance(event, EvToolApproval):
        save(sid, 'approval', 'Agent needs approval', 'Review the pending action in your conversation.', sid + ':approve:' + event.call_id)
    elif isinstance(event, EvToolCall) and event.call.status == 'awaiting_input':
        save(sid, 'question', 'Agent has a question', 'Open your conversation to answer.', sid + ':question:' + event.call.id)
    elif isinstance(event, EvError):
        save(sid, 'error', 'Agent needs attention', event.message, sid + ':error:' + str(int(time.time() // 60)) + ':' + event.message[:80])
    elif isinstance(event, EvDone):
        from ..agent_plus import store as missions
        if missions.owns_session(sid) and missions.get(sid).status == 'completed':
            mission = missions.get(sid)
            save(sid, 'completed', 'Mission completed', mission.objective, sid + ':completed:' + str(mission.version))


async def deliver(value):
    try:
        settings_value = settings()
        title = {'completed':'Mission completed','approval':'Agent needs approval','question':'Agent has a question','error':'Agent needs attention','notice':'Agent update'}[value.kind]
        from ..events import bus
        if settings_value.native_desktop and bus.client_count == 0:
            from .native_notifications import show
            try:
                await asyncio.to_thread(show,title,'Open Grom AI Studio to inspect the update.')
            except Exception as exc:
                from .. import events
                events.log('warn','notifications','Desktop notification failed: ' + type(exc).__name__)
        if not settings_value.web_push:
            return
        from pywebpush import webpush, WebPushException
        private = vault.reveal(db.get_setting_values()['agents.vapid_private'])
        for row in db.query('SELECT * FROM agent_push_subscriptions'):
            device_row = db.query_one('SELECT data,sessions FROM agent_devices WHERE id=?', (row['device_id'],))
            if not device_row:
                continue
            device = json.loads(device_row['data'])
            if not device.get('enabled') or 'notifications' not in device.get('scopes',[]) or value.session_id not in json.loads(device_row['sessions']):
                continue
            try:
                # Push carries a generic status, without conversation contents or account credentials.
                payload = json.dumps({'title':title,'body':'Open Agents to inspect the update.','session_id':value.session_id})
                await asyncio.to_thread(webpush, subscription_info=json.loads(vault.reveal(row['data'])), data=payload,
                    vapid_private_key=private, vapid_claims={'sub':settings_value.contact}, timeout=15, ttl=3600)
            except WebPushException as exc:
                if exc.response is not None and exc.response.status_code in (404,410):
                    db.execute('DELETE FROM agent_push_subscriptions WHERE id=?',(row['id'],))
    except Exception as exc:
        from .. import events
        events.log('warn','notifications', 'Browser push failed: ' + type(exc).__name__)


async def shutdown():
    for task in list(_deliveries):
        task.cancel()
    if _deliveries:
        await asyncio.gather(*list(_deliveries), return_exceptions=True)
    _deliveries.clear()
