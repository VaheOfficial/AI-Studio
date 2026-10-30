"""Stop an owner, its delegated work and its pending continuations together."""
from __future__ import annotations
from .. import db
from ..agent import agent
from ..agent_plus import controller, store as missions
from . import delegation, store


async def pause(sid: str) -> None:
    from . import monitors, channels
    monitors.pause(sid)
    for channel in channels.listing():
        if channel.session_id == sid and channel.enabled:
            channels.enable(channel.id, False)
    db.execute("UPDATE agent_wakes SET status='paused', result='Agent paused by user' WHERE session_id=? AND status IN ('scheduled','ready')", (sid,))
    if missions.owns_session(sid):
        await controller.pause(sid)
    else:
        await agent.stop_and_wait(sid)
        from ..workspace.tasks import tasks
        for child in delegation.list_all(sid):
            if child.status in ('queued', 'running', 'waiting_approval'):
                await tasks.cancel(child.task_id)
        db.execute("UPDATE agent_wakes SET status='paused', result='Agent paused by user' WHERE session_id=? AND status IN ('scheduled','ready')", (sid,))
    store.notify('activity', sid)
