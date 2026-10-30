"""Chat-scoped missions, immutable tool revisions, action receipts and event history."""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from typing import Any

from .. import db
from ..events import bus
from ..schemas_agent_plus import (AgentPlusDetail, AgentPlusMission, ChatCapability, EvAgentPlusUpdate,
                                 MissionAction, MissionCriterion, MissionEvent, MissionWork)


def init() -> None:
    for name in ("missions", "capabilities", "actions", "work"):
        db.execute(f"CREATE TABLE IF NOT EXISTS agentplus_{name} (id TEXT PRIMARY KEY, "
                   "session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, data TEXT NOT NULL)")
        db.execute(f"CREATE INDEX IF NOT EXISTS agentplus_{name}_session ON agentplus_{name}(session_id)")
    db.execute("CREATE TABLE IF NOT EXISTS agentplus_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
               "session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, kind TEXT NOT NULL, "
               "text TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS agentplus_events_session ON agentplus_events(session_id, seq)")


def owns_session(sid: str) -> bool:
    return db.query_one("SELECT id FROM agentplus_missions WHERE id=?", (sid,)) is not None


def notify(sid: str) -> None:
    bus.publish(EvAgentPlusUpdate(session_id=sid))


@contextmanager
def atomic():
    """Synchronous projection/event writes share a transaction; never await inside this scope."""
    name = 'agentplus_' + uuid.uuid4().hex
    with db._lock:
        conn = db._db()
        conn.execute('SAVEPOINT ' + name)
        try:
            yield
        except BaseException:
            conn.execute('ROLLBACK TO ' + name)
            raise
        finally:
            conn.execute('RELEASE ' + name)


def event(sid: str, kind: str, text: str, data: dict[str, Any] | None = None) -> None:
    db.execute("INSERT INTO agentplus_events(session_id,kind,text,data,created_at) VALUES(?,?,?,?,?)",
               (sid, kind, text, json.dumps(data or {}), db.now_iso()))
    notify(sid)


def search_events(sid: str, query: str) -> list[dict[str, Any]]:
    rows = db.query('SELECT * FROM agentplus_events WHERE session_id=? AND instr(lower(text), lower(?)) > 0 '
                    'ORDER BY seq DESC LIMIT 15', (sid, query[:1000]))
    return [{'seq': r['seq'], 'kind': r['kind'], 'text': r['text'], 'data': json.loads(r['data']),
             'created_at': r['created_at']} for r in rows]


def save(m: AgentPlusMission) -> None:
    m.updated_at = db.now_iso()
    db.execute("INSERT INTO agentplus_missions(id,session_id,data) VALUES(?,?,?) "
               "ON CONFLICT(id) DO UPDATE SET data=excluded.data", (m.session_id, m.session_id, m.model_dump_json()))
    notify(m.session_id)


def get(sid: str) -> AgentPlusMission:
    row = db.query_one("SELECT data FROM agentplus_missions WHERE id=?", (sid,))
    if row is None:
        raise ValueError("Agent+ chat not found")
    return AgentPlusMission.model_validate_json(row["data"])


def list_all() -> list[AgentPlusMission]:
    return [AgentPlusMission.model_validate_json(r["data"]) for r in
            db.query("SELECT data FROM agentplus_missions ORDER BY rowid DESC")]


def criteria(texts: list[str]) -> list[MissionCriterion]:
    if not texts or any(not t.strip() for t in texts):
        raise ValueError("Acceptance criteria must be nonempty")
    return [MissionCriterion(id=uuid.uuid4().hex[:10], text=t.strip()) for t in texts]


def tools(sid: str) -> list[ChatCapability]:
    return [ChatCapability.model_validate_json(r["data"]) for r in
            db.query("SELECT data FROM agentplus_capabilities WHERE session_id=? ORDER BY rowid", (sid,))]


def capability(sid: str, tid: str) -> ChatCapability:
    row = db.query_one("SELECT data FROM agentplus_capabilities WHERE id=? AND session_id=?", (tid, sid))
    if row is None:
        raise ValueError("Tool does not belong to this chat")
    return ChatCapability.model_validate_json(row["data"])


def save_tool(t: ChatCapability) -> None:
    existing = db.query_one("SELECT data FROM agentplus_capabilities WHERE id=?", (t.id,))
    if existing:
        old = ChatCapability.model_validate_json(existing["data"])
        for field in ("code", "code_hash", "input_schema", "output_schema", "acceptance", "checks", "session_id"):
            if getattr(old, field) != getattr(t, field):
                raise ValueError("A tool revision is immutable; create a new revision")
    db.execute("INSERT INTO agentplus_capabilities(id,session_id,data) VALUES(?,?,?) "
               "ON CONFLICT(id) DO UPDATE SET data=excluded.data", (t.id, t.session_id, t.model_dump_json()))
    notify(t.session_id)


def actions(sid: str) -> list[MissionAction]:
    return [MissionAction.model_validate_json(r["data"]) for r in
            db.query("SELECT data FROM agentplus_actions WHERE session_id=? ORDER BY rowid", (sid,))]


def action(sid: str, aid: str) -> MissionAction:
    row = db.query_one("SELECT data FROM agentplus_actions WHERE id=? AND session_id=?", (aid, sid))
    if row is None:
        raise ValueError("Action not found in this chat")
    return MissionAction.model_validate_json(row["data"])


def save_action(sid: str, a: MissionAction) -> None:
    existing = db.query_one('SELECT session_id,data FROM agentplus_actions WHERE id=?', (a.id,))
    if existing and existing['session_id'] != sid:
        raise ValueError('Action identifier belongs to another chat')
    with atomic():
        db.execute("INSERT INTO agentplus_actions(id,session_id,data) VALUES(?,?,?) "
                   "ON CONFLICT(id) DO UPDATE SET data=excluded.data", (a.id, sid, a.model_dump_json()))
        event(sid, 'action.intent' if a.status == 'running' else 'action.receipt',
              a.name + ': ' + a.status, {'action_id': a.id, 'name': a.name, 'status': a.status})
    notify(sid)


def detail(sid: str) -> AgentPlusDetail:
    records = db.query("SELECT * FROM agentplus_events WHERE session_id=? ORDER BY seq DESC LIMIT 150", (sid,))
    return AgentPlusDetail(mission=get(sid), tools=tools(sid), actions=actions(sid)[-150:], work=work(sid), events=[
        MissionEvent(seq=r["seq"], kind=r["kind"], text=r["text"], data=json.loads(r["data"]),
                     created_at=r["created_at"]) for r in reversed(records)])


def digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def work(sid: str) -> list[MissionWork]:
    return [MissionWork.model_validate_json(r['data']) for r in
            db.query('SELECT data FROM agentplus_work WHERE session_id=? ORDER BY rowid', (sid,))]


def save_work(sid: str, items: list[MissionWork]) -> None:
    # Names are scoped by the compound key; a different chat may use the same readable work ID.
    with atomic():
        for item in items:
            db.execute('INSERT INTO agentplus_work(id,session_id,data) VALUES(?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                       (sid + ':' + item.id, sid, item.model_dump_json()))
        event(sid, 'work.state', 'Work state saved.', {'items': [w.model_dump() for w in items]})
    notify(sid)


def recover() -> None:
    for m in list_all():
        for a in actions(m.session_id):
            if a.status == "running":
                a.status, a.output = "uncertain", "Interrupted before a receipt was recorded; inspect before retrying."
                save_action(m.session_id, a)
        if m.status == "running":
            m.cost += m.reserved_cost
            m.reserved_cost = 0
            m.status, m.reason = "paused", "Server restarted. Review interrupted actions, then resume."
            save(m)
            event(m.session_id, "recovery", m.reason)
