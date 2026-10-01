"""Agent tools for the user's cross-chat memory (``remember`` / ``forget``); see ``studio/memories.py``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .. import memories, settings
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

SPECS: list[ToolSpec] = [
    ToolSpec("remember", "Save one durable fact about the user for future chats (a preference, their setup, a "
                         "project, how they like things done). Also call it whenever the user asks you to remember "
                         "something. One fact per call, written so it makes sense on its own later.",
             {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}),
    ToolSpec("forget", "Delete a saved memory by its id (shown as [id] in your memory list) when the user asks you "
                       "to forget it or it turned out wrong.",
             {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}),
]


async def _remember(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    if not settings.load().memory_enabled:
        raise ToolFailure("Memory is turned off in Settings → Assistant")
    try:
        m = memories.add(a["fact"])
    except memories.MemoryError as exc:
        raise ToolFailure(str(exc)) from exc
    return ToolOutcome(True, f"Saved to memory as [{m.id}]: {m.text}")


async def _forget(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    found = memories.delete(a["id"].strip().strip("[]"))
    if found is None:
        raise ToolFailure(f"No memory with id {a['id']!r}")
    return ToolOutcome(True, f"Forgot [{found.id}]: {found.text}")


IMPL: dict[str, Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]] = {
    "remember": _remember, "forget": _forget,
}
