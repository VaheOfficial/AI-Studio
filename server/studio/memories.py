"""What the assistant remembers about the user across chats (Settings → Assistant → Memory).

Saved by the agent's ``remember`` tool or by the user, removed by ``forget`` or the user, and shown to the model in
every chat's system prompt as data. Kept short: a memory is one durable fact, not a transcript."""

from __future__ import annotations

import uuid

from . import db
from .schemas import Memory

MAX_CHARS = 500
MAX_MEMORIES = 200  # the prompt carries all of them


class MemoryError(ValueError):
    """User-facing reason a memory can't be saved."""


def init() -> None:
    db.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL)")


def list_all() -> list[Memory]:
    rows = db.query("SELECT id, text, created_at FROM memories ORDER BY created_at")
    return [Memory(id=r["id"], text=r["text"], created_at=r["created_at"]) for r in rows]


def add(text: str) -> Memory:
    text = " ".join(text.split())
    if not text:
        raise MemoryError("Nothing to remember")
    if len(text) > MAX_CHARS:
        raise MemoryError(f"Keep a memory under {MAX_CHARS} characters: one fact at a time")
    existing = list_all()
    same = next((m for m in existing if m.text.casefold() == text.casefold()), None)
    if same:
        return same
    if len(existing) >= MAX_MEMORIES:
        raise MemoryError(f"Memory is full ({MAX_MEMORIES}); forget something first")
    m = Memory(id=uuid.uuid4().hex[:6], text=text, created_at=db.now_iso())
    db.execute("INSERT INTO memories(id, text, created_at) VALUES(?,?,?)", (m.id, m.text, m.created_at))
    return m


def delete(memory_id: str) -> Memory | None:
    found = next((m for m in list_all() if m.id == memory_id), None)
    if found:
        db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    return found
