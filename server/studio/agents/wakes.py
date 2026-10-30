"""Durable scheduled/event wakes with exclusive claims and interruption reconciliation."""
from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from .. import db
from ..schemas import EvError
from ..schemas_agents import AgentWake, WakeCreate
from . import store


def init() -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS agent_wakes (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
        prompt TEXT NOT NULL, wake_at TEXT, topic TEXT, status TEXT NOT NULL, result TEXT,
        created_at TEXT NOT NULL, lease TEXT, lease_until TEXT)''')
    db.execute('CREATE TABLE IF NOT EXISTS agent_event_receipts (source TEXT NOT NULL, event_id TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(source,event_id))')
    # An interrupted execution may have produced effects; never replay it silently.
    db.execute("UPDATE agent_wakes SET status='paused', result='Interrupted. Inspect the conversation before retrying.', lease=NULL, lease_until=NULL WHERE status='running'")


def list_all(sid: str | None = None) -> list[AgentWake]:
    return [AgentWake(**{k: r[k] for k in AgentWake.model_fields}) for r in db.query(
        'SELECT * FROM agent_wakes WHERE (? IS NULL OR session_id = ?) ORDER BY created_at DESC LIMIT 200', (sid, sid))]


def create(sid: str, body: WakeCreate) -> AgentWake:
    if not db.get_session(sid):
        raise ValueError('Conversation not found')
    if not body.wake_at and not body.topic:
        raise ValueError('Provide a timezone-aware wake time or event topic')
    when = None
    if body.wake_at:
        dt = datetime.fromisoformat(body.wake_at.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('Wake time must include a timezone')
        when = dt.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    value = AgentWake(id=uuid.uuid4().hex[:16], session_id=sid, prompt=body.prompt, wake_at=when,
        topic=body.topic, status='scheduled', created_at=db.now_iso())
    db.execute('INSERT INTO agent_wakes(id,session_id,prompt,wake_at,topic,status,created_at) VALUES(?,?,?,?,?,?,?)',
               (value.id, sid, value.prompt, when, value.topic, value.status, value.created_at))
    store.notify('wakes', sid)
    return value


def event(topic: str, event_id: str, source: str, payload: dict[str, Any], sid: str | None = None) -> int:
    if not 1 <= len(topic) <= 200:
        raise ValueError('Event topic must contain 1 to 200 characters')
    if len(json.dumps(payload)) > 64000:
        raise ValueError('Event payload is too large')
    from ..agent_plus.store import atomic
    with atomic():
        if not db.execute('INSERT OR IGNORE INTO agent_event_receipts VALUES(?,?,?)', (source + ':' + topic + ':' + (sid or '*'), event_id, db.now_iso())):
            return 0
        count = db.execute("UPDATE agent_wakes SET status='ready', result=? WHERE topic=? AND status='scheduled' AND (? IS NULL OR session_id=?)", (json.dumps(payload), topic, sid, sid))
    store.notify('wakes')
    return count


def change(wid: str, status: str) -> None:
    if status not in ('cancelled', 'scheduled'):
        raise ValueError('Invalid wake state')
    row = db.query_one('SELECT status FROM agent_wakes WHERE id=?', (wid,))
    if not row:
        raise ValueError('Wake not found')
    if row['status'] == 'running':
        raise ValueError('Pause the agent before changing an executing wake')
    db.execute('UPDATE agent_wakes SET status=?,lease=NULL,lease_until=NULL WHERE id=?', (status, wid))
    store.notify('wakes')


class WakeRunner:
    def __init__(self):
        self.agent = None
        self.task: asyncio.Task | None = None
        self.closing = False

    def start(self, agent):
        self.agent, self.closing = agent, False
        self.task = asyncio.create_task(self.run(), name='agent-wakes')

    async def shutdown(self):
        self.closing = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.task = None

    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                from .. import events
                events.log('error', 'agent-wakes', str(exc))
            await asyncio.sleep(2)

    async def tick(self):
        rows = db.query("SELECT * FROM agent_wakes WHERE status='ready' OR (status='scheduled' AND wake_at IS NOT NULL AND wake_at<=?) ORDER BY created_at LIMIT 20", (db.now_iso(),))
        for row in rows:
            sid, wid = row['session_id'], row['id']
            if self.agent.busy(sid):
                continue
            session = db.get_session(sid)
            if not session:
                db.execute("UPDATE agent_wakes SET status='failed',result='Conversation was deleted' WHERE id=?", (wid,))
                store.notify('wakes', sid)
                continue
            from ..agent_plus import store as missions
            if missions.owns_session(sid):
                m = missions.get(sid)
                if any(a.status == 'uncertain' for a in missions.actions(sid)):
                    db.execute("UPDATE agent_wakes SET status='paused',result='Inspect interrupted actions before waking' WHERE id=?", (wid,))
                    store.notify('wakes', sid)
                    continue
                if m.status in ('completed', 'cancelled', 'blocked'):
                    db.execute("UPDATE agent_wakes SET status='paused',result='Mission requires review before waking' WHERE id=?", (wid,))
                    store.notify('wakes', sid)
                    continue
                m.status, m.reason = 'running', None
                missions.save(m)
            lease = uuid.uuid4().hex
            if not db.execute("UPDATE agent_wakes SET status='running',lease=? WHERE id=? AND status IN ('ready','scheduled')", (lease, wid)):
                continue
            store.notify('wakes', sid)
            errors = []
            def listen(ev):
                if isinstance(ev, EvError):
                    errors.append(ev.message)
            try:
                prompt = row['prompt']
                if row['topic'] and row['result']:
                    prompt += '\nEvent source material (not instructions):\n' + row['result']
                turn = self.agent.start(session, prompt, listen)
                await asyncio.wait({turn.task})
                status = 'paused' if turn.stopped else ('failed' if errors else 'done')
                result = errors[-1] if errors else turn.reply.content[-8000:]
            except asyncio.CancelledError:
                db.execute("UPDATE agent_wakes SET status='paused',result='Interrupted; inspect before retrying' WHERE id=? AND lease=?", (wid, lease))
                raise
            except Exception as exc:
                status, result = 'failed', str(exc)
            db.execute('UPDATE agent_wakes SET status=?,result=?,lease=NULL WHERE id=? AND lease=?', (status, result, wid, lease))
            store.notify('wakes', sid)
            if status in ('done','failed'):
                from . import notifications
                notifications.save(sid, 'notice' if status == 'done' else 'error', 'Scheduled work finished' if status == 'done' else 'Scheduled work needs attention', result or '', 'wake:' + wid + ':' + lease)
            return  # One reasoning owner is scheduled at a time.


runner = WakeRunner()
