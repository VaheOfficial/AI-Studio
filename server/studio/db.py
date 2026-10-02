"""SQLite persistence (stdlib ``sqlite3``) for settings, installed models, outputs and agent
sessions/messages (feature modules add their own tables in their ``init``). One shared connection
guarded by a lock; safe to call from threads."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, NamedTuple

from . import config
from .schemas import (AgentMessage, AgentSession, ContextUsage, InstalledModel, Output, ThinkingPart, TokenUsage,
                      ToolCall)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS installed_models (
    id TEXT PRIMARY KEY,
    catalog_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    runtime TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    installed_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    error TEXT
);
CREATE TABLE IF NOT EXISTS outputs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    path TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    params TEXT NOT NULL,
    created_at TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    duration_s REAL
);
CREATE INDEX IF NOT EXISTS outputs_created ON outputs(created_at);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    model TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    thinking TEXT,
    tool_calls TEXT,
    steps TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, seq);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def init() -> None:
    global _conn
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    _add_missing_columns(conn, "installed_models", _INSTALLED_VARIANT_COLUMNS)
    _add_missing_columns(conn, "messages", {"thinking_parts": "TEXT", "images": "TEXT", "output_tokens": "INTEGER",
                                            "generation_s": "REAL", "usage": "TEXT", "elapsed_s": "REAL"})
    _add_missing_columns(conn, "sessions", _SESSION_CONTEXT_COLUMNS)
    _conn = conn


# Agent context: the last request's token use, and a summary standing in for the messages up to ``summary_seq``
# (written when a long chat outgrows the model's context window).
_SESSION_CONTEXT_COLUMNS = {"context_used": "INTEGER", "context_limit": "INTEGER", "summary": "TEXT",
                            "summary_seq": "INTEGER", "context_size": "INTEGER"}

# Hub variant fields, added after the first release; databases created before carry the old table.
_INSTALLED_VARIANT_COLUMNS = {"source_repo": "TEXT", "format": "TEXT", "quant": "TEXT", "files": "TEXT",
                              "text_encoder": "TEXT"}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, sql_type in columns.items():
        if name in have:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
        except sqlite3.OperationalError as exc:  # another server process sharing the db added it first
            if "duplicate column" not in str(exc):
                raise


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialised; call db.init() first")
    return _conn


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with _lock:
        return _db().execute(sql, tuple(params)).rowcount


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with _lock:
        return _db().execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with _lock:
        return _db().execute(sql, tuple(params)).fetchone()


# ------------------------------- settings -------------------------------


def get_setting_values() -> dict[str, Any]:
    return {r["key"]: json.loads(r["value"]) for r in query("SELECT key, value FROM settings")}


def set_setting_value(key: str, value: Any) -> None:
    if value is None:
        execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


# --------------------------- installed models ---------------------------


def _row_to_model(r: sqlite3.Row) -> InstalledModel:
    return InstalledModel(
        id=r["id"], catalog_id=r["catalog_id"], name=r["name"], kind=r["kind"], runtime=r["runtime"],
        source_repo=r["source_repo"], format=r["format"], quant=r["quant"],
        files=json.loads(r["files"]) if r["files"] else None,
        path=r["path"], size_bytes=r["size_bytes"], installed_at=r["installed_at"], status=r["status"],
        error=r["error"], text_encoder=r["text_encoder"],
    )


def list_installed() -> list[InstalledModel]:
    return [_row_to_model(r) for r in query("SELECT * FROM installed_models ORDER BY installed_at DESC")]


def get_installed(model_id: str) -> InstalledModel | None:
    r = query_one("SELECT * FROM installed_models WHERE id = ?", (model_id,))
    return _row_to_model(r) if r else None


def upsert_installed(m: InstalledModel) -> None:
    execute(
        """INSERT INTO installed_models(id, catalog_id, name, kind, runtime, source_repo, format, quant, files, path,
                                        size_bytes, installed_at, status, error, text_encoder)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET catalog_id=excluded.catalog_id, name=excluded.name, kind=excluded.kind,
             runtime=excluded.runtime, source_repo=excluded.source_repo, format=excluded.format,
             quant=excluded.quant, files=excluded.files, path=excluded.path, size_bytes=excluded.size_bytes,
             installed_at=excluded.installed_at, status=excluded.status, error=excluded.error,
             text_encoder=excluded.text_encoder""",
        (m.id, m.catalog_id, m.name, m.kind, m.runtime, m.source_repo, m.format, m.quant,
         json.dumps(m.files) if m.files is not None else None, m.path, m.size_bytes, m.installed_at, m.status,
         m.error, m.text_encoder),
    )


def set_installed_status(model_id: str, status: str, error: str | None = None) -> InstalledModel | None:
    execute("UPDATE installed_models SET status = ?, error = ? WHERE id = ?", (status, error, model_id))
    return get_installed(model_id)


def delete_installed(model_id: str) -> None:
    execute("DELETE FROM installed_models WHERE id = ?", (model_id,))


# -------------------------------- outputs --------------------------------


def _row_to_output(r: sqlite3.Row) -> Output:
    return Output(
        id=r["id"], kind=r["kind"], url=r["url"], model_id=r["model_id"], prompt=r["prompt"],
        params=json.loads(r["params"]), created_at=r["created_at"], width=r["width"], height=r["height"],
        duration_s=r["duration_s"],
    )


def insert_output(o: Output, path: str) -> None:
    execute(
        """INSERT INTO outputs(id, kind, url, path, model_id, prompt, params, created_at, width, height, duration_s)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (o.id, o.kind, o.url, path, o.model_id, o.prompt, json.dumps(o.params), o.created_at, o.width, o.height,
         o.duration_s),
    )


def list_outputs(kind: str | None, limit: int) -> list[Output]:
    if kind:
        rows = query("SELECT * FROM outputs WHERE kind = ? ORDER BY created_at DESC LIMIT ?", (kind, limit))
    else:
        rows = query("SELECT * FROM outputs ORDER BY created_at DESC LIMIT ?", (limit,))
    return [_row_to_output(r) for r in rows]


def get_output_path(output_id: str) -> str | None:
    r = query_one("SELECT path FROM outputs WHERE id = ?", (output_id,))
    return r["path"] if r else None


def delete_output(output_id: str) -> None:
    execute("DELETE FROM outputs WHERE id = ?", (output_id,))


# ------------------------------- sessions -------------------------------


def _row_to_session(r: sqlite3.Row) -> AgentSession:
    return AgentSession(
        id=r["id"], title=r["title"], model=r["model"], mode=r["mode"], created_at=r["created_at"],
        updated_at=r["updated_at"],
        context=ContextUsage(used=r["context_used"], limit=r["context_limit"]) if r["context_used"] else None,
        context_size=r["context_size"] or None,
    )


def list_sessions() -> list[AgentSession]:
    return [_row_to_session(r) for r in query("SELECT * FROM sessions ORDER BY updated_at DESC")]


def get_session(session_id: str) -> AgentSession | None:
    r = query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    return _row_to_session(r) if r else None


def insert_session(s: AgentSession) -> None:
    execute(
        "INSERT INTO sessions(id, title, model, mode, created_at, updated_at) VALUES(?,?,?,?,?,?)",
        (s.id, s.title, s.model, s.mode, s.created_at, s.updated_at),
    )


_SESSION_COLUMNS = {"title", "model", "mode", "context_size"}


def update_session(session_id: str, **fields: Any) -> None:
    unknown = set(fields) - _SESSION_COLUMNS
    if unknown:
        raise ValueError(f"Unknown session fields: {sorted(unknown)}")
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    execute(f"UPDATE sessions SET {cols} WHERE id = ?", (*fields.values(), session_id))


def set_context_usage(session_id: str, used: int, limit: int | None) -> None:
    execute("UPDATE sessions SET context_used = ?, context_limit = ? WHERE id = ?", (used, limit, session_id))


def get_summary(session_id: str) -> tuple[str, int] | None:
    """(summary, seq of the last message it covers) of a chat whose early part was summarized."""
    r = query_one("SELECT summary, summary_seq FROM sessions WHERE id = ?", (session_id,))
    return (r["summary"], r["summary_seq"]) if r and r["summary"] else None


def set_summary(session_id: str, summary: str | None, upto_seq: int | None) -> None:
    execute("UPDATE sessions SET summary = ?, summary_seq = ? WHERE id = ?", (summary, upto_seq, session_id))


def delete_session(session_id: str) -> None:
    execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def _row_to_message(r: sqlite3.Row) -> AgentMessage:
    calls = json.loads(r["tool_calls"]) if r["tool_calls"] else None
    return AgentMessage(
        id=r["id"], role=r["role"], content=r["content"], images=json.loads(r["images"]) if r["images"] else None,
        thinking=r["thinking"] or None,
        thinking_parts=[ThinkingPart.model_validate(x) for x in json.loads(r["thinking_parts"])] if r["thinking_parts"] else None,
        tool_calls=[ToolCall.model_validate(c) for c in calls] if calls else None, created_at=r["created_at"],
        output_tokens=r["output_tokens"], generation_s=r["generation_s"],
        usage=TokenUsage.model_validate_json(r["usage"]) if r["usage"] else None, elapsed_s=r["elapsed_s"],
    )


def list_messages(session_id: str) -> list[AgentMessage]:
    rows = query("SELECT * FROM messages WHERE session_id = ? ORDER BY seq", (session_id,))
    return [_row_to_message(r) for r in rows]


def find_message(session_id: str, message_id: str) -> tuple[int, AgentMessage] | None:
    """(seq, message) of one message of a session."""
    r = query_one("SELECT * FROM messages WHERE session_id = ? AND id = ?", (session_id, message_id))
    return (r["seq"], _row_to_message(r)) if r else None


def delete_messages_from(session_id: str, seq: int) -> None:
    """Drop the message at ``seq`` and every later one (rewinding a chat)."""
    execute("DELETE FROM messages WHERE session_id = ? AND seq >= ?", (session_id, seq))
    summary = get_summary(session_id)
    if summary and summary[1] >= seq:  # the summary covered messages that are gone
        set_summary(session_id, None, None)
    update_session(session_id)


def copy_messages(src: str, dst: str, upto_seq: int) -> None:
    """Copy a session's messages up to ``upto_seq`` (inclusive) into another session under fresh ids (forking)."""
    rows = query("SELECT * FROM messages WHERE session_id = ? AND seq <= ? ORDER BY seq", (src, upto_seq))
    with _lock:
        for r in rows:
            execute(
                """INSERT INTO messages(id, session_id, seq, role, content, images, thinking, thinking_parts, tool_calls,
                                         steps, created_at, output_tokens, generation_s, usage, elapsed_s)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex[:16], dst, r["seq"], r["role"], r["content"], r["images"], r["thinking"],
                 r["thinking_parts"], r["tool_calls"], r["steps"], r["created_at"], r["output_tokens"],
                 r["generation_s"], r["usage"], r["elapsed_s"]),
            )


class MessageRow(NamedTuple):
    """A persisted message as the agent's history needs it; ``steps`` is the provider-neutral transcript of an
    assistant turn (see ``agent.history``), ``images`` the pictures attached to a user message."""

    seq: int
    role: str
    content: str
    steps: list[dict[str, Any]] | None
    images: list[str]


def list_message_steps(session_id: str) -> list[MessageRow]:
    rows = query("SELECT seq, role, content, steps, images FROM messages WHERE session_id = ? ORDER BY seq",
                 (session_id,))
    return [MessageRow(r["seq"], r["role"], r["content"], json.loads(r["steps"]) if r["steps"] else None,
                       json.loads(r["images"]) if r["images"] else []) for r in rows]


def save_message(session_id: str, msg: AgentMessage, steps: list[dict[str, Any]] | None = None) -> None:
    """Insert or update a message (assistant messages are saved repeatedly while streaming)."""
    tool_calls = (
        json.dumps([c.model_dump(mode="json", exclude_none=True) for c in msg.tool_calls]) if msg.tool_calls else None
    )
    steps_json = json.dumps(steps) if steps is not None else None
    parts_json = json.dumps([p.model_dump() for p in msg.thinking_parts]) if msg.thinking_parts else None
    usage_json = msg.usage.model_dump_json() if msg.usage else None
    with _lock:
        if query_one("SELECT 1 FROM messages WHERE id = ?", (msg.id,)):
            execute(
                "UPDATE messages SET content = ?, thinking = ?, thinking_parts = ?, tool_calls = ?, steps = ?, "
                "output_tokens = ?, generation_s = ?, usage = ?, elapsed_s = ? WHERE id = ?",
                (msg.content, msg.thinking, parts_json, tool_calls, steps_json, msg.output_tokens, msg.generation_s,
                 usage_json, msg.elapsed_s, msg.id),
            )  # images are set once, when a user message is created
        else:
            row = query_one("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM messages WHERE session_id = ?", (session_id,))
            execute(
                """INSERT INTO messages(id, session_id, seq, role, content, images, thinking, thinking_parts, tool_calls,
                                       steps, created_at, output_tokens, generation_s, usage, elapsed_s)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (msg.id, session_id, row["n"] if row else 1, msg.role, msg.content,
                 json.dumps(msg.images) if msg.images else None, msg.thinking, parts_json, tool_calls, steps_json,
                 msg.created_at, msg.output_tokens, msg.generation_s, usage_json, msg.elapsed_s),
            )
        update_session(session_id)
