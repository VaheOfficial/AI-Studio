"""``/api/swarms``: agents with roles working on one goal (see ``studio/swarm``)."""

from __future__ import annotations

from fastapi import HTTPException, Response

from .. import swarm
from ..schemas_swarm import (Swarm, SwarmAgent, SwarmAgentSpec, SwarmAgentUpdate, SwarmCreate, SwarmDetail,
                             SwarmInboxEntry, SwarmInboxReply, SwarmMessage, SwarmUpdate)
from ..swarm import manage
from . import StudioRouter

router = StudioRouter(prefix="/api/swarms")


def _fail(exc: swarm.SwarmError) -> HTTPException:
    text = str(exc)
    return HTTPException(404 if text.startswith("No ") else 400, text)


@router.get("", response_model=list[Swarm])
async def list_swarms() -> list[Swarm]:
    return swarm.store.list_swarms()


@router.post("", response_model=SwarmDetail)
async def create_swarm(body: SwarmCreate) -> SwarmDetail:
    raise HTTPException(410, "Create an Agents mission and delegate bounded subagents instead")


@router.get("/{swarm_id}", response_model=SwarmDetail)
async def get_swarm(swarm_id: str) -> SwarmDetail:
    try:
        return manage.detail(swarm_id)
    except swarm.SwarmError as exc:
        raise _fail(exc) from exc


@router.patch("/{swarm_id}", response_model=Swarm)
async def update_swarm(swarm_id: str, body: SwarmUpdate) -> Swarm:
    raise HTTPException(410, "Saved teams are read-only; continue through an Agents mission")


@router.delete("/{swarm_id}", status_code=204)
async def delete_swarm(swarm_id: str) -> Response:
    try:
        swarm.store.get_swarm(swarm_id)
        await swarm.controller.delete(swarm_id)
    except swarm.SwarmError as exc:
        raise _fail(exc) from exc
    return Response(status_code=204)


@router.post("/{swarm_id}/start", response_model=Swarm)
async def start_swarm(swarm_id: str) -> Swarm:
    raise HTTPException(410, "Import this saved team into an Agents mission")


@router.post("/{swarm_id}/pause", response_model=Swarm)
async def pause_swarm(swarm_id: str) -> Swarm:
    """Nothing new starts; sessions already running finish."""
    try:
        return swarm.controller.pause(swarm_id)
    except swarm.SwarmError as exc:
        raise _fail(exc) from exc


@router.post("/{swarm_id}/stop", response_model=Swarm)
async def stop_swarm(swarm_id: str) -> Swarm:
    """Stop every session now; their work goes back to the queue."""
    try:
        return await swarm.controller.stop(swarm_id)
    except swarm.SwarmError as exc:
        raise _fail(exc) from exc


@router.post("/{swarm_id}/message", status_code=204)
async def message_swarm(swarm_id: str, body: SwarmMessage) -> Response:
    raise HTTPException(410, "Saved teams are read-only; continue through an Agents mission")


@router.post("/{swarm_id}/inbox/{entry_id}", response_model=SwarmInboxEntry)
async def reply_inbox(swarm_id: str, entry_id: str, body: SwarmInboxReply) -> SwarmInboxEntry:
    raise HTTPException(410, "Saved teams are read-only; continue through an Agents mission")


@router.post("/{swarm_id}/agents", response_model=SwarmAgent)
async def add_agent(swarm_id: str, body: SwarmAgentSpec) -> SwarmAgent:
    raise HTTPException(410, "Saved teams are read-only; continue through an Agents mission")


@router.patch("/{swarm_id}/agents/{agent_id}", response_model=SwarmAgent)
async def update_agent(swarm_id: str, agent_id: str, body: SwarmAgentUpdate) -> SwarmAgent:
    raise HTTPException(410, "Saved teams are read-only; continue through an Agents mission")


@router.delete("/{swarm_id}/agents/{agent_id}", status_code=204)
async def remove_agent(swarm_id: str, agent_id: str) -> Response:
    raise HTTPException(410, "Saved teams are read-only; continue through an Agents mission")
