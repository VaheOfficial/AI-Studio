"""Agent+ missions use the existing agent WebSocket for chat and approvals."""
from __future__ import annotations
import uuid
from fastapi import HTTPException
from .. import agent_plus, db
from ..agent import agent
from ..agent_plus import store
from ..schemas import AgentSession
from ..schemas_agent_plus import AgentPlusAmend, AgentPlusCreate, AgentPlusDetail, AgentPlusMission
from . import StudioRouter

router = StudioRouter(prefix="/api/agent-plus")


def detail(sid: str) -> AgentPlusDetail:
    try:
        return store.detail(sid)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/missions", response_model=list[AgentPlusMission])
async def missions() -> list[AgentPlusMission]:
    return store.list_all()


@router.post("/missions", response_model=AgentPlusDetail)
async def create(body: AgentPlusCreate) -> AgentPlusDetail:
    if not body.objective.strip():
        raise HTTPException(400, 'Mission objective must be nonempty')
    provider, sep, model = body.model.partition(":")
    if not sep or not model or provider not in ("ollama", "llamacpp", "lmstudio", "openrouter", "openai"):
        raise HTTPException(400, "Choose a supported chat model")
    try:
        checks = store.criteria(body.criteria)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    sid, now = uuid.uuid4().hex[:16], db.now_iso()
    with store.atomic():
        db.insert_session(AgentSession(id=sid, title=body.objective.strip()[:60], model=body.model, mode="agent",
                                      created_at=now, updated_at=now))
        store.save(AgentPlusMission(session_id=sid, original_request=body.objective.strip(), objective=body.objective.strip(),
            criteria=checks, max_requests=body.max_requests, max_cost=body.max_cost, created_at=now, updated_at=now))
        store.event(sid, "created", "Mission created. Start it when ready.")
    return detail(sid)


@router.get("/missions/{sid}", response_model=AgentPlusDetail)
async def get(sid: str) -> AgentPlusDetail:
    return detail(sid)


@router.post("/missions/{sid}/resume", response_model=AgentPlusDetail)
async def resume(sid: str) -> AgentPlusDetail:
    m = detail(sid).mission
    if agent.busy(sid):
        raise HTTPException(409, "Agent is already working")
    if m.status in ("completed", "cancelled"):
        raise HTTPException(409, "Amend the mission before starting another task in this chat")
    if m.requests >= m.max_requests:
        raise HTTPException(409, "Request budget reached. Amend to authorize another bounded run.")
    m.status, m.reason = "running", None
    with store.atomic():
        store.save(m)
        store.event(sid, "resumed", "Mission resumed.")
    session = db.get_session(sid)
    assert session
    agent.start(session, "Work on this mission: " + m.objective + "\nRead mission_status for criteria and prior evidence.")
    return detail(sid)


@router.post("/missions/{sid}/pause", response_model=AgentPlusDetail)
async def pause(sid: str) -> AgentPlusDetail:
    detail(sid)
    await agent_plus.controller.pause(sid)
    return detail(sid)


@router.post("/missions/{sid}/cancel", response_model=AgentPlusDetail)
async def cancel(sid: str) -> AgentPlusDetail:
    detail(sid)
    await agent_plus.controller.pause(sid, "cancelled")
    return detail(sid)


@router.patch("/missions/{sid}", response_model=AgentPlusDetail)
async def amend(sid: str, body: AgentPlusAmend) -> AgentPlusDetail:
    if not body.objective.strip():
        raise HTTPException(400, 'Mission objective must be nonempty')
    m = detail(sid).mission
    if agent.busy(sid):
        raise HTTPException(409, "Pause before changing requirements")
    if m.version != body.version:
        raise HTTPException(409, "Mission changed; refresh before amending")
    try:
        checks = store.criteria(body.criteria)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    old = {c.text: c for c in m.criteria}
    m.criteria = [old.get(c.text, c) for c in checks]
    for c in m.criteria:
        if c.text in old and m.objective != body.objective.strip():
            c.evidence = []
    m.objective, m.version, m.status, m.reason = body.objective.strip(), m.version + 1, "ready", None
    m.requests = 0
    if body.max_requests is not None:
        m.max_requests = body.max_requests
    if body.max_cost is not None:
        m.max_cost = body.max_cost
    with store.atomic():
        store.save(m)
        store.event(sid, "amended", "Requirements and resources updated; chat tools retained.", body.model_dump(exclude_none=True))
    return detail(sid)
