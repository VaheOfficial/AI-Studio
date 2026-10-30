"""Revocable scoped device grants for a separate authenticated gateway."""
from __future__ import annotations
import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from .. import db
from ..schemas_agents import AgentDevice, DeviceCreate
from . import store



def init():
    db.execute('''CREATE TABLE IF NOT EXISTS agent_devices (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
        data TEXT NOT NULL, sessions TEXT NOT NULL)''')


def issue(body: DeviceCreate):
    import json
    if any(s not in {'read', 'chat', 'approve', 'events', 'deliver_events', 'documents', 'notifications'} for s in body.scopes):
        raise ValueError('Unsupported device scope')
    if any(not db.get_session(sid) for sid in body.session_ids):
        raise ValueError('A granted conversation does not exist')
    token = secrets.token_urlsafe(48)
    value = AgentDevice(id=uuid.uuid4().hex[:16], name=body.name, scopes=body.scopes, enabled=True, created_at=db.now_iso())
    db.execute('INSERT INTO agent_devices VALUES(?,?,?,?)', (value.id, hashlib.sha256(token.encode()).hexdigest(), value.model_dump_json(), json.dumps(body.session_ids)))
    store.notify('devices')
    return {'device': value, 'token': token, 'session_ids': body.session_ids}


def authorize(token: str, scope: str, sid: str | None = None):
    import json
    row = db.query_one('SELECT * FROM agent_devices WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
    if not row:
        raise ValueError('Invalid device token')
    value = AgentDevice.model_validate_json(row['data'])
    sessions = json.loads(row['sessions'])
    if not value.enabled or scope not in value.scopes or (sid and sid not in sessions):
        raise ValueError('Device permission does not cover this operation')
    now = datetime.now(timezone.utc)
    if not value.last_seen or (now - datetime.fromisoformat(value.last_seen.replace('Z', '+00:00'))).total_seconds() >= 30:
        value.last_seen = db.now_iso()
        db.execute('UPDATE agent_devices SET data=? WHERE id=?', (value.model_dump_json(), value.id))
    return value, sessions


def list_all():
    return [AgentDevice.model_validate_json(r['data']) for r in db.query('SELECT data FROM agent_devices ORDER BY rowid DESC')]


def revoke(did: str):
    row = db.query_one('SELECT data FROM agent_devices WHERE id=?', (did,))
    if not row:
        raise ValueError('Device not found')
    value = AgentDevice.model_validate_json(row['data'])
    value.enabled = False
    db.execute('UPDATE agent_devices SET data=? WHERE id=?', (value.model_dump_json(), did))
    store.notify('devices')
