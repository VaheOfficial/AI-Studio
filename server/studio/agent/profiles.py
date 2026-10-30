"""Session profiles: chats that something other than the user drives (the swarm's agents) get their own prompt,
their own tool set and rules for tools that would otherwise wait for the user's approval.

A feature registers a resolver that recognises its sessions, plus the tools only its sessions have. The turn loop
asks ``resolve`` at the start of every turn, so a profile also applies when the user types in such a chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .types import Call, ModelInfo, ToolContext, ToolOutcome, ToolSpec

Handler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]


@dataclass
class Profile:
    # This session's whole system prompt (instead of the studio assistant's), given what the model can do; built off
    # the event loop
    prompt: Callable[[ModelInfo | None], str]
    # The normal tool set -> this session's (it may add the feature's own tools)
    tools: Callable[[list[ToolSpec]], list[ToolSpec]]
    # Decide a call before it runs: None permits it; a string refuses it with that message to the model.
    # preserve_approvals keeps the ordinary approval policy. ``gated`` reports that policy's current decision.
    gate: Callable[[str, dict[str, Any], bool], str | None]
    # Every event of the session's turns (whoever started them)
    observe: Callable[[Any], None] | None = None
    preserve_approvals: bool = False
    provider: Callable[[Any], Any] | None = None
    halt: Callable[[], bool] | None = None
    result: Callable[[Call, ToolOutcome], ToolOutcome] | None = None


_resolvers: list[Callable[[str], Profile | None]] = []
SPECS: dict[str, ToolSpec] = {}
IMPL: dict[str, Handler] = {}


def register(resolver: Callable[[str], Profile | None], specs: list[ToolSpec], impl: dict[str, Handler]) -> None:
    _resolvers.append(resolver)
    SPECS.update({s.name: s for s in specs})
    IMPL.update(impl)


def resolve(session_id: str) -> Profile | None:
    for resolver in _resolvers:
        profile = resolver(session_id)
        if profile is not None:
            return profile
    return None
