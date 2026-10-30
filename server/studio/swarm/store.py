"""The swarm's ledger in SQLite: swarms, their agents, work items, the event history, the owner's inbox, which chat
session belongs to which agent and item, and what was spent per day. Every change is pushed to the clients."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from ..events import bus
from ..schemas_swarm import (EvSwarmAgent, EvSwarmEvent, EvSwarmInbox, EvSwarmItem, EvSwarmRemoved, EvSwarmUpdate,
                             Swarm, SwarmAgent, SwarmEvent, SwarmHandoff, SwarmInboxEntry, SwarmItem, SwarmReview)


class SwarmError(ValueError):
    """User-facing reason a swarm request can't be done."""


def new_id(n: int = 10) -> str:
    return uuid.uuid4().hex[:n]


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def init() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS swarms (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL, folder TEXT NOT NULL, status TEXT NOT NULL,
        status_reason TEXT, max_parallel INTEGER NOT NULL, daily_budget REAL, item_budget REAL,
        rules TEXT NOT NULL DEFAULT '{}', report TEXT, report_at TEXT, wake TEXT NOT NULL DEFAULT '[]',
        seen_seq INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    have = {r["name"] for r in db.query("PRAGMA table_info(swarms)")}
    for name, sql_type in {"hiring": "INTEGER NOT NULL DEFAULT 0", "max_agents": "INTEGER NOT NULL DEFAULT 8",
                           "max_price": "REAL"}.items():
        if name not in have:
            db.execute(f"ALTER TABLE swarms ADD COLUMN {name} {sql_type}")
    db.execute("""CREATE TABLE IF NOT EXISTS swarm_agents (
        id TEXT PRIMARY KEY, swarm_id TEXT NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL,
        role TEXT NOT NULL, model TEXT NOT NULL, purpose TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
        item_id TEXT, session_id TEXT, accepted INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
        last_active TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS swarm_items (
        id TEXT PRIMARY KEY, swarm_id TEXT NOT NULL, parent_id TEXT, kind TEXT NOT NULL, title TEXT NOT NULL,
        spec TEXT NOT NULL, acceptance TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL,
        blocked_by TEXT NOT NULL, assign_to TEXT, owner_agent_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        rejections INTEGER NOT NULL DEFAULT 0, handoff TEXT, review TEXT, session_ids TEXT NOT NULL DEFAULT '[]',
        cost REAL NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS swarm_items_swarm ON swarm_items(swarm_id, status)")
    db.execute("""CREATE TABLE IF NOT EXISTS swarm_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, swarm_id TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
        text TEXT NOT NULL, agent_id TEXT, item_id TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS swarm_events_swarm ON swarm_events(swarm_id, seq)")
    db.execute("""CREATE TABLE IF NOT EXISTS swarm_inbox (
        id TEXT PRIMARY KEY, swarm_id TEXT NOT NULL, kind TEXT NOT NULL, agent_id TEXT NOT NULL, item_id TEXT,
        text TEXT NOT NULL, options TEXT NOT NULL DEFAULT '[]', tool TEXT, args TEXT, status TEXT NOT NULL,
        answer TEXT, created_at TEXT NOT NULL, resolved_at TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS swarm_sessions (
        session_id TEXT PRIMARY KEY, swarm_id TEXT NOT NULL, agent_id TEXT NOT NULL, item_id TEXT,
        purpose TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS swarm_spend (
        swarm_id TEXT NOT NULL, day TEXT NOT NULL, cost REAL NOT NULL DEFAULT 0, PRIMARY KEY(swarm_id, day))""")


def _json(value: Any) -> str:
    return json.dumps(value)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


# ------------------------------ swarms ------------------------------


def _last_hour(swarm_id: str) -> float:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    r = db.query_one("SELECT COALESCE(SUM(u.cost), 0) AS c FROM openrouter_usage u JOIN swarm_sessions s "
                     "ON s.session_id = u.session_id WHERE s.swarm_id = ? AND u.ts >= ?", (swarm_id, since))
    return round(r["c"], 4) if r else 0.0


def _swarm(r: Any) -> Swarm:
    spent = db.query_one("SELECT COALESCE(SUM(cost), 0) AS total, COALESCE(SUM(CASE WHEN day = ? THEN cost END), 0) "
                         "AS today FROM swarm_spend WHERE swarm_id = ?", (today(), r["id"]))
    return Swarm(id=r["id"], name=r["name"], goal=r["goal"], folder=r["folder"], status=r["status"],
                 status_reason=r["status_reason"], max_parallel=r["max_parallel"], daily_budget=r["daily_budget"],
                 item_budget=r["item_budget"], rules=_load(r["rules"], {}), hiring=bool(r["hiring"]),
                 max_agents=r["max_agents"], max_price=r["max_price"], report=r["report"],
                 report_at=r["report_at"], spent_today=round(spent["today"], 6) if spent else 0.0,
                 spent_total=round(spent["total"], 6) if spent else 0.0, spent_last_hour=_last_hour(r["id"]),
                 created_at=r["created_at"],
                 updated_at=r["updated_at"])


def list_swarms() -> list[Swarm]:
    return [_swarm(r) for r in db.query("SELECT * FROM swarms ORDER BY created_at DESC")]


def get_swarm(swarm_id: str) -> Swarm:
    r = db.query_one("SELECT * FROM swarms WHERE id = ?", (swarm_id,))
    if r is None:
        raise SwarmError(f"No swarm '{swarm_id}'")
    return _swarm(r)


def insert_swarm(s: Swarm) -> Swarm:
    db.execute("INSERT INTO swarms(id, name, goal, folder, status, status_reason, max_parallel, daily_budget, "
               "item_budget, rules, hiring, max_agents, max_price, report, report_at, created_at, updated_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (s.id, s.name, s.goal, s.folder, s.status, s.status_reason, s.max_parallel, s.daily_budget,
                s.item_budget, _json(s.rules), int(s.hiring), s.max_agents, s.max_price, s.report, s.report_at,
                s.created_at, s.updated_at))
    return publish_swarm(s.id)


_SWARM_FIELDS = {"name", "goal", "status", "status_reason", "max_parallel", "daily_budget", "item_budget", "rules",
                 "hiring", "max_agents", "max_price", "report", "report_at"}


def update_swarm(swarm_id: str, **fields: Any) -> Swarm:
    unknown = set(fields) - _SWARM_FIELDS
    if unknown:
        raise ValueError(f"Unknown swarm fields: {sorted(unknown)}")
    if "rules" in fields:
        fields["rules"] = _json(fields["rules"])
    if "hiring" in fields:
        fields["hiring"] = int(fields["hiring"])
    fields["updated_at"] = db.now_iso()
    db.execute(f"UPDATE swarms SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
               (*fields.values(), swarm_id))
    return publish_swarm(swarm_id)


def publish_swarm(swarm_id: str) -> Swarm:
    s = get_swarm(swarm_id)
    bus.publish(EvSwarmUpdate(swarm=s))
    return s


def delete_swarm(swarm_id: str) -> list[str]:
    """Remove the swarm and its records; returns its chat sessions (the caller deletes them)."""
    sessions = [r["session_id"] for r in db.query("SELECT session_id FROM swarm_sessions WHERE swarm_id = ?",
                                                    (swarm_id,))]
    for table in ("swarm_agents", "swarm_items", "swarm_events", "swarm_inbox", "swarm_sessions", "swarm_spend"):
        db.execute(f"DELETE FROM {table} WHERE swarm_id = ?", (swarm_id,))
    db.execute("DELETE FROM swarms WHERE id = ?", (swarm_id,))
    _owned.difference_update(sessions)
    bus.publish(EvSwarmRemoved(id=swarm_id))
    return sessions


def add_wake(swarm_id: str, reason: str) -> None:
    """Something the lead should plan around at its next planning session (kept across restarts)."""
    r = db.query_one("SELECT wake FROM swarms WHERE id = ?", (swarm_id,))
    reasons = _load(r["wake"], []) if r else []
    if reason not in reasons:
        reasons.append(reason)
    db.execute("UPDATE swarms SET wake = ? WHERE id = ?", (_json(reasons[-50:]), swarm_id))


def take_wake(swarm_id: str) -> list[str]:
    r = db.query_one("SELECT wake FROM swarms WHERE id = ?", (swarm_id,))
    db.execute("UPDATE swarms SET wake = '[]' WHERE id = ?", (swarm_id,))
    return _load(r["wake"], []) if r else []


def wake_reasons(swarm_id: str) -> list[str]:
    r = db.query_one("SELECT wake FROM swarms WHERE id = ?", (swarm_id,))
    return _load(r["wake"], []) if r else []


def seen_seq(swarm_id: str) -> int:
    r = db.query_one("SELECT seen_seq FROM swarms WHERE id = ?", (swarm_id,))
    return int(r["seen_seq"]) if r else 0


def set_seen_seq(swarm_id: str, seq: int) -> None:
    db.execute("UPDATE swarms SET seen_seq = ? WHERE id = ?", (seq, swarm_id))


# ------------------------------ agents ------------------------------

_AGENT_COLUMNS = ("id", "swarm_id", "name", "role", "model", "purpose", "state", "item_id", "session_id",
                  "accepted", "rejected", "failed", "cost", "notes", "last_active")


def _agent(r: Any) -> SwarmAgent:
    return SwarmAgent(**{k: r[k] for k in _AGENT_COLUMNS})


def list_agents(swarm_id: str, with_dismissed: bool = False) -> list[SwarmAgent]:
    """The swarm's agents; dismissed ones (kept so the history keeps their names) only when asked for."""
    agents = [_agent(r) for r in db.query("SELECT * FROM swarm_agents WHERE swarm_id = ? ORDER BY position",
                                          (swarm_id,))]
    return agents if with_dismissed else [a for a in agents if a.state != "dismissed"]


def get_agent(agent_id: str) -> SwarmAgent:
    r = db.query_one("SELECT * FROM swarm_agents WHERE id = ?", (agent_id,))
    if r is None:
        raise SwarmError(f"No agent '{agent_id}'")
    return _agent(r)


def insert_agent(a: SwarmAgent) -> SwarmAgent:
    r = db.query_one("SELECT COALESCE(MAX(position), 0) + 1 AS n FROM swarm_agents WHERE swarm_id = ?",
                     (a.swarm_id,))
    db.execute(f"INSERT INTO swarm_agents(position, {', '.join(_AGENT_COLUMNS)}) "
               f"VALUES(?, {', '.join('?' * len(_AGENT_COLUMNS))})",
               (r["n"] if r else 1, *(getattr(a, k) for k in _AGENT_COLUMNS)))
    return publish_agent(a.id)


def update_agent(agent_id: str, **fields: Any) -> SwarmAgent:
    unknown = set(fields) - set(_AGENT_COLUMNS[2:])
    if unknown:
        raise ValueError(f"Unknown agent fields: {sorted(unknown)}")
    db.execute(f"UPDATE swarm_agents SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
               (*fields.values(), agent_id))
    return publish_agent(agent_id)


def bump_agent(agent_id: str, column: str, amount: float = 1) -> None:
    assert column in ("accepted", "rejected", "failed", "cost")
    db.execute(f"UPDATE swarm_agents SET {column} = {column} + ? WHERE id = ?", (amount, agent_id))


def publish_agent(agent_id: str) -> SwarmAgent:
    a = get_agent(agent_id)
    bus.publish(EvSwarmAgent(agent=a))
    return a


# ------------------------------ items ------------------------------

_ITEM_COLUMNS = ("id", "swarm_id", "parent_id", "kind", "title", "spec", "acceptance", "status", "priority",
                 "blocked_by", "assign_to", "owner_agent_id", "attempts", "rejections", "handoff", "review",
                 "session_ids", "cost", "created_by", "created_at", "updated_at")
_ITEM_JSON = {"acceptance", "blocked_by", "handoff", "review", "session_ids"}


def _item(r: Any) -> SwarmItem:
    data = {k: r[k] for k in _ITEM_COLUMNS}
    data["acceptance"] = _load(data["acceptance"], [])
    data["blocked_by"] = _load(data["blocked_by"], [])
    data["session_ids"] = _load(data["session_ids"], [])
    handoff, review = _load(data.pop("handoff"), None), _load(data.pop("review"), None)
    return SwarmItem(**data, handoff=SwarmHandoff(**handoff) if handoff else None,
                     review=SwarmReview(**review) if review else None)


def list_items(swarm_id: str) -> list[SwarmItem]:
    return [_item(r) for r in db.query("SELECT * FROM swarm_items WHERE swarm_id = ? ORDER BY created_at, rowid",
                                       (swarm_id,))]


def get_item(item_id: str) -> SwarmItem:
    r = db.query_one("SELECT * FROM swarm_items WHERE id = ?", (item_id,))
    if r is None:
        raise SwarmError(f"No item '{item_id}'")
    return _item(r)


def _dump(column: str, value: Any) -> Any:
    if column not in _ITEM_JSON:
        return value
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return _json(value.model_dump())
    return _json(value)


def insert_item(i: SwarmItem) -> SwarmItem:
    db.execute(f"INSERT INTO swarm_items({', '.join(_ITEM_COLUMNS)}) VALUES({', '.join('?' * len(_ITEM_COLUMNS))})",
               tuple(_dump(k, getattr(i, k)) for k in _ITEM_COLUMNS))
    return publish_item(i.id)


def update_item(item_id: str, **fields: Any) -> SwarmItem:
    unknown = set(fields) - set(_ITEM_COLUMNS[2:])
    if unknown:
        raise ValueError(f"Unknown item fields: {sorted(unknown)}")
    fields["updated_at"] = db.now_iso()
    db.execute(f"UPDATE swarm_items SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
               (*(_dump(k, v) for k, v in fields.items()), item_id))
    return publish_item(item_id)


def add_item_cost(item_id: str, cost: float) -> None:
    db.execute("UPDATE swarm_items SET cost = cost + ? WHERE id = ?", (cost, item_id))


def publish_item(item_id: str) -> SwarmItem:
    i = get_item(item_id)
    bus.publish(EvSwarmItem(item=i))
    return i


# ------------------------------ events ------------------------------


def _event(r: Any) -> SwarmEvent:
    return SwarmEvent(seq=r["seq"], swarm_id=r["swarm_id"], at=r["at"], kind=r["kind"], text=r["text"],
                      agent_id=r["agent_id"], item_id=r["item_id"])


def add_event(swarm_id: str, kind: str, text: str, agent_id: str | None = None,
              item_id: str | None = None) -> SwarmEvent:
    db.execute("INSERT INTO swarm_events(swarm_id, at, kind, text, agent_id, item_id) VALUES(?,?,?,?,?,?)",
               (swarm_id, db.now_iso(), kind, text[:4000], agent_id, item_id))
    r = db.query_one("SELECT * FROM swarm_events WHERE swarm_id = ? ORDER BY seq DESC LIMIT 1", (swarm_id,))
    assert r is not None
    ev = _event(r)
    bus.publish(EvSwarmEvent(event=ev))
    return ev


def recent_events(swarm_id: str, limit: int = 200) -> list[SwarmEvent]:
    rows = db.query("SELECT * FROM swarm_events WHERE swarm_id = ? ORDER BY seq DESC LIMIT ?", (swarm_id, limit))
    return [_event(r) for r in reversed(rows)]


def events_after(swarm_id: str, seq: int) -> list[SwarmEvent]:
    return [_event(r) for r in db.query("SELECT * FROM swarm_events WHERE swarm_id = ? AND seq > ? ORDER BY seq",
                                        (swarm_id, seq))]


def last_seq(swarm_id: str) -> int:
    r = db.query_one("SELECT COALESCE(MAX(seq), 0) AS n FROM swarm_events WHERE swarm_id = ?", (swarm_id,))
    return int(r["n"]) if r else 0


# ------------------------------ inbox ------------------------------


def _entry(r: Any) -> SwarmInboxEntry:
    return SwarmInboxEntry(id=r["id"], swarm_id=r["swarm_id"], kind=r["kind"], agent_id=r["agent_id"],
                           item_id=r["item_id"], text=r["text"], options=_load(r["options"], []), tool=r["tool"],
                           args=_load(r["args"], None), status=r["status"], answer=r["answer"],
                           created_at=r["created_at"], resolved_at=r["resolved_at"])


def list_inbox(swarm_id: str) -> list[SwarmInboxEntry]:
    return [_entry(r) for r in db.query("SELECT * FROM swarm_inbox WHERE swarm_id = ? ORDER BY created_at DESC "
                                        "LIMIT 200", (swarm_id,))]


def get_entry(entry_id: str) -> SwarmInboxEntry:
    r = db.query_one("SELECT * FROM swarm_inbox WHERE id = ?", (entry_id,))
    if r is None:
        raise SwarmError(f"No inbox entry '{entry_id}'")
    return _entry(r)


def open_permission(swarm_id: str, tool: str) -> SwarmInboxEntry | None:
    """An open request for this tool already in the inbox (another one would only repeat it)."""
    r = db.query_one("SELECT * FROM swarm_inbox WHERE swarm_id = ? AND kind = 'permission' AND tool = ? AND "
                     "status = 'open'", (swarm_id, tool))
    return _entry(r) if r else None


def insert_entry(e: SwarmInboxEntry) -> SwarmInboxEntry:
    db.execute("INSERT INTO swarm_inbox(id, swarm_id, kind, agent_id, item_id, text, options, tool, args, status, "
               "answer, created_at, resolved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (e.id, e.swarm_id, e.kind, e.agent_id, e.item_id, e.text, _json(e.options), e.tool,
                _json(e.args) if e.args is not None else None, e.status, e.answer, e.created_at, e.resolved_at))
    bus.publish(EvSwarmInbox(entry=e))
    return e


def resolve_entry(entry_id: str, status: str, answer: str | None) -> SwarmInboxEntry:
    db.execute("UPDATE swarm_inbox SET status = ?, answer = ?, resolved_at = ? WHERE id = ?",
               (status, answer, db.now_iso(), entry_id))
    e = get_entry(entry_id)
    bus.publish(EvSwarmInbox(entry=e))
    return e


# ------------------------------ sessions and spend ------------------------------

# Every chat session that belongs to a swarm (they are kept out of the normal chat list)
_owned: set[str] = set()


def load_owned() -> None:
    _owned.clear()
    _owned.update(r["session_id"] for r in db.query("SELECT session_id FROM swarm_sessions"))


def owns_session(session_id: str) -> bool:
    return session_id in _owned


def add_session(session_id: str, swarm_id: str, agent_id: str, item_id: str | None, purpose: str) -> None:
    db.execute("INSERT OR REPLACE INTO swarm_sessions(session_id, swarm_id, agent_id, item_id, purpose) "
               "VALUES(?,?,?,?,?)", (session_id, swarm_id, agent_id, item_id, purpose))
    _owned.add(session_id)


def session_link(session_id: str) -> tuple[str, str, str | None, str] | None:
    """(swarm id, agent id, item id, purpose) of a swarm's session."""
    if session_id not in _owned:
        return None
    r = db.query_one("SELECT * FROM swarm_sessions WHERE session_id = ?", (session_id,))
    return (r["swarm_id"], r["agent_id"], r["item_id"], r["purpose"]) if r else None


def add_spend(swarm_id: str, cost: float) -> None:
    db.execute("INSERT INTO swarm_spend(swarm_id, day, cost) VALUES(?,?,?) ON CONFLICT(swarm_id, day) DO UPDATE "
               "SET cost = cost + excluded.cost", (swarm_id, today(), cost))
