"""Rebuild provider-neutral history from persisted messages.

Assistant turns are stored with a ``steps`` transcript: ``[{"text", "calls": [{"id", "name", "args",
"output", "ok", "images"?}]}]``; each step becomes an assistant message followed by its tool results, which keep the
pictures a tool returned (providers deliver them the way their API allows). Earlier turns are replayed without
thinking blocks (only the current turn replays provider-native content), so the rebuilt prefix is identical on
every request. When a long chat was summarized (``context.compact_history``), the summary stands in for the
messages it covers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import db
from . import images
from .types import Call, Message, ToolFailure

SUMMARY_HEAD = "(Summary of the earlier part of this conversation, written to fit the context window.)"


def load(session_id: str) -> list[Message]:
    history: list[Message] = []
    summary = db.get_summary(session_id)
    if summary:
        history.append(Message("user", f"{SUMMARY_HEAD}\n{summary[0]}"))
    for row in db.list_message_steps(session_id):
        if summary and row.seq <= summary[1]:
            continue
        if row.role == "user":
            attached = _files(row.images)
            note = ("\n(Attached images: " + ", ".join(images.public_url(f) or str(f) for f in attached) + ")"
                    if attached else "")
            history.append(Message("user", row.content + note, images=attached))
            continue
        for step in row.steps or [{"text": row.content, "calls": []}]:
            history.extend(step_messages(step))
    return history


def step_messages(step: dict[str, Any]) -> list[Message]:
    calls = step.get("calls") or []
    if not step.get("text") and not calls:
        return []
    out = [Message("assistant", step.get("text") or "",
                   calls=[Call(c["id"], c["name"], c.get("args") or {}) for c in calls])]
    for c in calls:
        # A call without output was interrupted (stop/crash); providers still need a result for it.
        out.append(Message("tool", c.get("output") or "Cancelled before completion", call_id=c["id"],
                           name=c["name"], is_error=not c.get("ok", False), images=_files(c.get("images") or [])))
    if step.get("nudge"):  # the loop's reminder to act after a step that only announced an action
        out.append(Message("user", step["nudge"]))
    return out


def _files(refs: list[str]) -> list[Path]:
    """Stored image references that still exist (a deleted picture is dropped, not an error)."""
    out = []
    for ref in refs:
        try:
            out.append(images.to_path(ref))
        except ToolFailure:
            continue
    return out
