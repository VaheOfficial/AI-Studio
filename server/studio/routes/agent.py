"""Chat models and agent sessions. Sending, approving and stopping go over the WebSocket (``routes/ws.py``)."""

from __future__ import annotations

import asyncio
import uuid

from typing import Annotated

from fastapi import File, HTTPException, Query, Response, UploadFile

from .. import db, memories, openrouter_usage, swarm, workspace
from .. import agent_plus
from ..agent import DEFAULT_TITLE, agent, images
from ..agent.providers import list_chat_models
from ..agent.types import ToolFailure
from ..agent import context as agent_context
from ..agent import history as agent_history
from ..agent import prompt as agent_prompt
from ..agent import tools as agent_tools
from ..agent.providers import ProviderError, get_provider
from ..schemas import (AgentImages, AgentMessage, AgentSession, ChatModelOption, CompactRequest, CompactResult,
                       Memory, MemoryCreate,
                       CreateSessionRequest, MessagePage, MessageRef, PatchSessionRequest, RewindResult,
                       SessionTotals, TokenUsage)
from . import StudioRouter

router = StudioRouter(prefix="/api")


def _session(session_id: str) -> AgentSession:
    s = db.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"Session '{session_id}' not found")
    return s


@router.get("/chat/models", response_model=list[ChatModelOption])
async def chat_models() -> list[ChatModelOption]:
    return await list_chat_models()


@router.post("/agent/images", response_model=AgentImages)
async def upload_images(files_: list[UploadFile] = File(..., alias="files")) -> AgentImages:
    """Pictures to attach to a chat message (then sent as ``agent.send.images``)."""
    urls = []
    for f in files_[:8]:
        data = await f.read()
        try:
            urls.append(await asyncio.to_thread(images.save_upload, f.filename or "image.png", data))
        except ToolFailure as exc:
            raise HTTPException(400, str(exc)) from exc
    return AgentImages(urls=urls)


@router.get("/agent/sessions", response_model=list[AgentSession])
async def list_sessions() -> list[AgentSession]:
    """The user's chats: a swarm's sessions are listed on its own page instead."""
    from ..agents import delegation
    from .. import arena
    children = {v.session_id for v in delegation.list_all()}
    arena_sessions={sid for m in arena.listing() for sid in (m.left.session_id,m.right.session_id) if sid}
    return [s for s in db.list_sessions() if not swarm.owns_session(s.id) and not agent_plus.owns_session(s.id) and s.id not in children and s.id not in arena_sessions]


@router.post("/agent/sessions", response_model=AgentSession)
async def create_session(body: CreateSessionRequest) -> AgentSession:
    if ":" not in body.model:
        raise HTTPException(400, "model must be '<provider>:<model>', e.g. 'ollama:qwen3:8b'")
    now = db.now_iso()
    s = AgentSession(id=uuid.uuid4().hex[:16], title=DEFAULT_TITLE, model=body.model, mode=body.mode,
                     created_at=now, updated_at=now)
    db.insert_session(s)
    return s.model_copy(update={"messages": []})


# A page of a long chat: the chat view loads the latest one and earlier ones as the user scrolls up. Replies of agent
# turns can hold dozens of tool calls with their output, so a page is also bounded by size.
PAGE_MESSAGES = 40
PAGE_CHARS = 400_000


@router.get("/agent/sessions/{session_id}", response_model=AgentSession)
async def get_session(session_id: str, limit: Annotated[int | None, Query(ge=1, le=500)] = None,
                      from_: Annotated[str | None, Query(alias="from")] = None) -> AgentSession:
    """The chat with all its messages; with ``limit`` only its latest page, with ``from`` every message from that one
    on (a page the client already shows, plus what came after it; the latest page when it no longer exists)."""
    s = _session(session_id)
    if limit is None and from_ is None:
        return s.model_copy(update={"messages": openrouter_usage.with_costs(session_id, db.list_messages(session_id))})
    start = db.message_seq(session_id, from_) if from_ else None
    if start is None:
        start = db.page_start(session_id, limit or PAGE_MESSAGES, PAGE_CHARS)
    messages = db.list_messages(session_id, from_seq=start) if start is not None else []
    t = db.message_totals(session_id)
    totals = SessionTotals(
        cost=openrouter_usage.session_cost(session_id), output_tokens=t.get("output_tokens", 0),
        generation_s=t.get("generation_s", 0),
        usage=TokenUsage(requests=t.get("requests", 0), input_tokens=t.get("input_tokens", 0),
                         cached_tokens=t.get("cached_tokens", 0), output_tokens=t.get("usage_output_tokens", 0)),
    )
    return s.model_copy(update={"messages": openrouter_usage.with_costs(session_id, messages), "totals": totals,
                                "has_older": start is not None and db.has_messages_before(session_id, start)})


@router.get("/agent/sessions/{session_id}/messages", response_model=MessagePage)
async def older_messages(session_id: str, before: str,
                         limit: Annotated[int, Query(ge=1, le=500)] = PAGE_MESSAGES) -> MessagePage:
    """The page of messages just before ``before``, oldest first."""
    _session(session_id)
    end = db.message_seq(session_id, before)
    if end is None:
        raise HTTPException(404, "That message is no longer in this chat")
    start = db.page_start(session_id, limit, PAGE_CHARS, before_seq=end)
    if start is None:
        return MessagePage(messages=[], has_older=False)
    messages = db.list_messages(session_id, from_seq=start, before_seq=end)
    return MessagePage(messages=openrouter_usage.with_costs(session_id, messages),
                       has_older=db.has_messages_before(session_id, start))


@router.patch("/agent/sessions/{session_id}", response_model=AgentSession)
async def patch_session(session_id: str, body: PatchSessionRequest) -> AgentSession:
    _session(session_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if agent_plus.owns_session(session_id) and (changes.get("mode", "agent") != "agent" or
                                              ("model" in changes and agent.busy(session_id))):
        raise HTTPException(409, "Agent+ requires agent mode; pause before changing its model")
    if "model" in changes and ":" not in changes["model"]:
        raise HTTPException(400, "model must be '<provider>:<model>'")
    if changes.get("context_size") == 0:
        changes["context_size"] = None  # back to automatic
    if changes:
        db.update_session(session_id, **changes)
    return _session(session_id)


@router.get("/agent/memories", response_model=list[Memory])
async def list_memories() -> list[Memory]:
    """What the assistant remembers about the user across chats, oldest first."""
    return memories.list_all()


@router.post("/agent/memories", response_model=Memory)
async def add_memory(body: MemoryCreate) -> Memory:
    try:
        return memories.add(body.text)
    except memories.MemoryError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/agent/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str) -> Response:
    if memories.delete(memory_id) is None:
        raise HTTPException(404, "Memory not found")
    return Response(status_code=204)


# Chats being compacted right now: a second /compact would queue another long summary on the same model
_compacting: set[str] = set()


@router.post("/agent/sessions/{session_id}/compact", response_model=CompactResult)
async def compact_session(session_id: str, body: CompactRequest) -> CompactResult:
    """Summarize the chat now (``/compact``): the model's next turn starts from the summary instead of the full
    history. The messages stay visible in the chat."""
    s = _session(session_id)
    if any(t.session_id == session_id for t in agent.active_turns()):
        raise HTTPException(409, "Wait for the current reply to finish (or stop it) before compacting")
    if session_id in _compacting:
        raise HTTPException(409, "Already compacting this chat")
    _compacting.add(session_id)
    try:
        provider = get_provider(s.model)
        if agent_plus.owns_session(session_id):
            from ..agent_plus.provider import MissionProvider
            provider = MissionProvider(provider, session_id, allow_inactive=True)
        provider.context_limit = s.context_size
        info = await provider.info()
        limit = min(s.context_size or info.context or 32768, info.context or s.context_size or 32768)
        folded, summary = await agent_context.compact_now(provider, session_id, limit, body.focus)
        if folded:  # the gauge shows the smaller context now, not the full one from the last reply
            from ..agent import profiles
            profile = profiles.resolve(session_id)
            system = await asyncio.to_thread(profile.prompt, info) if profile else await asyncio.to_thread(agent_prompt.build, s.mode, session_id, info, s.model)
            specs = agent_tools.all_specs() if s.mode == "agent" else None
            if profile and specs is not None:
                specs = profile.tools(specs)
            used = agent_context.Budget(info).estimate(system, specs, agent_history.load(session_id))
            db.set_context_usage(session_id, used, limit)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        _compacting.discard(session_id)
    if not folded:
        raise HTTPException(400, "Nothing to compact yet")
    return CompactResult(session=_session(session_id), folded=folded, summary=summary)


def _message(session_id: str, message_id: str) -> tuple[int, AgentMessage]:
    found = db.find_message(session_id, message_id)
    if found is None:
        raise HTTPException(404, "Message not found in this chat")
    return found


@router.post("/agent/sessions/{session_id}/rewind", response_model=RewindResult)
async def rewind_session(session_id: str, body: MessageRef) -> RewindResult:
    """Go back to just before one of the user's messages: drop it and everything after, and put the files the
    agent's file tools changed since then back as they were."""
    _session(session_id)
    if agent_plus.owns_session(session_id):
        raise HTTPException(409, 'Amend this mission; rewinding would leave its execution receipts inconsistent')
    seq, msg = _message(session_id, body.message_id)
    if msg.role != "user":
        raise HTTPException(400, "Rewind to one of your own messages")
    await agent.stop_and_wait(session_id)
    msgs = db.list_messages(session_id)  # in order
    later = msgs[next(i for i, m in enumerate(msgs) if m.id == msg.id):]
    calls = [c for m in later for c in (m.tool_calls or [])]
    undone = await asyncio.to_thread(workspace.checkpoints.restore, session_id, {c.id for c in calls})
    db.delete_messages_from(session_id, seq)
    commands = [str(c.args.get("command")) for c in calls
                if c.name in ("run_command", "start_process") and c.args.get("command")]
    return RewindResult(session=await get_session(session_id, limit=PAGE_MESSAGES), prompt=msg.content,
                        restored=undone.restored, removed=undone.removed, skipped=undone.skipped, commands=commands)


@router.post("/agent/sessions/{session_id}/fork", response_model=AgentSession)
async def fork_session(session_id: str, body: MessageRef) -> AgentSession:
    """A new chat with this one's messages up to and including ``message_id``, in the same workspace folder."""
    src = _session(session_id)
    if agent_plus.owns_session(session_id):
        raise HTTPException(409, 'Create a new Agent+ mission; tool capabilities belong to the originating chat')
    seq, _msg = _message(session_id, body.message_id)
    now = db.now_iso()
    fork = AgentSession(id=uuid.uuid4().hex[:16], title=f"{src.title} (fork)", model=src.model, mode=src.mode,
                        created_at=now, updated_at=now)
    db.insert_session(fork)
    db.copy_messages(session_id, fork.id, seq)
    root = workspace.state.get(session_id).root
    if root:
        try:
            workspace.state.set_root(fork.id, root)
        except workspace.WorkspaceError:
            pass  # the folder is gone; the fork asks for one like a new chat
    return await get_session(fork.id, limit=PAGE_MESSAGES)


@router.delete("/agent/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> Response:
    _session(session_id)
    await workspace.forget_session(session_id)  # its terminals, browser page, folder setting and task
    # Let a running turn write its final state first, so nothing is saved into a deleted session.
    await agent.stop_and_wait(session_id)
    db.delete_session(session_id)
    return Response(status_code=204)
