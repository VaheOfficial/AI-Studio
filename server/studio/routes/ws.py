"""``WS /api/ws`` — the single realtime channel.

Server → client: ``hello`` (full snapshot) first, then every bus event, plus ``system`` every ~2s
while at least one client is connected. Client → server: ``ClientMessage`` frames driving agent
turns; anything that can't be handled is answered with ``{type: "error", message, ref}`` and the
socket stays open.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from .. import __version__, config, db, events, system, workspace
from ..agent import TurnBusy, agent
from ..events import Subscriber, bus, serialize
from ..jobs import jobs
from ..models import models
from ..runtimes import runtimes
from ..agent.types import ToolFailure
from ..schemas import (ActiveTurn, AgentAnswerMessage, AgentApproveMessage, AgentSendMessage, AgentStopMessage,
                       EvErrorReply, EvHello, EvSystem, Snapshot, client_message_adapter)
from ..schemas_workspace import WORKSPACE_CLIENT_TYPES
from . import StudioRouter

router = StudioRouter(prefix="/api")

SYSTEM_INTERVAL_S = 2.0
_CLOSE_TOO_SLOW = 1013  # "try again later": the client reconnects and resyncs from hello
ALLOWED_ORIGINS = {*config.CORS_ORIGINS, f"http://{config.HOST}:{config.PORT}", f"http://localhost:{config.PORT}"}


class RequestError(Exception):
    """A client message that can't be honoured; becomes an ``error`` frame."""


class _SystemTicker:
    """Publishes ``system`` every ~2s while anyone is connected; not running (no NVML polling) otherwise."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="system-ticker")

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        failing = False
        # The hello snapshot already carries fresh system info, so wait one interval first.
        await asyncio.sleep(SYSTEM_INTERVAL_S)
        while bus.client_count:
            started = loop.time()
            try:
                bus.publish(EvSystem(system=await asyncio.to_thread(system.info)))
                failing = False
            except Exception as exc:
                if not failing:  # log once per outage, not every 2s
                    events.log("warn", "system", f"Could not collect system info: {exc}")
                failing = True
            await asyncio.sleep(max(0.2, SYSTEM_INTERVAL_S - (loop.time() - started)))


ticker = _SystemTicker()


def _collect_rest() -> tuple[Any, ...]:
    """The blocking parts of the snapshot (NVML, Ollama probes/sync)."""
    info = system.info()  # also refreshes the Ollama runtime status
    installed = models.list()  # includes the Ollama sync
    return info, installed, runtimes.all_info()


async def _snapshot(active_turns: list[ActiveTurn]) -> Snapshot:
    info, installed, runtime_infos = await asyncio.to_thread(_collect_rest)
    return Snapshot(system=info, jobs=jobs.list(), models=installed, runtimes=runtime_infos,
                    active_turns=active_turns)


# ------------------------------ client messages ------------------------------


def _dispatch(msg: AgentSendMessage | AgentApproveMessage | AgentStopMessage | AgentAnswerMessage) -> None:
    session = db.get_session(msg.session_id)
    if session is None:
        raise RequestError(f"Session '{msg.session_id}' not found")
    if isinstance(msg, AgentSendMessage):
        if not msg.content.strip():
            raise RequestError("Message content must not be empty")
        try:
            agent.start(session, msg.content, pictures=msg.images)
        except (TurnBusy, ToolFailure) as exc:
            raise RequestError(str(exc)) from exc
    elif isinstance(msg, AgentAnswerMessage):
        if not agent.answer(msg.session_id, msg.call_id, msg.answer):
            raise RequestError(f"No question '{msg.call_id}' is waiting for an answer in this session")
    elif isinstance(msg, AgentApproveMessage):
        if not agent.approve(msg.session_id, msg.call_id, msg.approved):
            raise RequestError(f"No tool call '{msg.call_id}' is awaiting approval in this session")
    else:
        agent.stop(msg.session_id)  # idempotent: stopping an already-finished turn is not an error


def _validation_message(data: Any, exc: ValidationError) -> str:
    known = ("agent.send", "agent.approve", "agent.stop", "agent.answer", *WORKSPACE_CLIENT_TYPES)
    if not isinstance(data, dict):
        return "Message must be a JSON object"
    if data.get("type") not in known:
        return f"Unknown message type {data.get('type')!r}; expected one of: {', '.join(known)}"
    problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:]) or 'message'}: {e['msg']}"
                         for e in exc.errors()[:5])
    return f"Invalid {data['type']} message: {problems}"


def handle_frame(raw: str, sub: Subscriber) -> EvErrorReply | None:
    """Handle one client frame from ``sub``'s client; returns the error reply to send, if any. Never raises."""
    try:
        data = json.loads(raw)
    except ValueError:
        return EvErrorReply(message="Frame is not valid JSON")
    ref = data.get("ref") if isinstance(data, dict) and isinstance(data.get("ref"), str) else None
    try:
        msg = client_message_adapter.validate_python(data)
    except ValidationError as exc:
        return EvErrorReply(message=_validation_message(data, exc), ref=ref)
    try:
        if msg.type in WORKSPACE_CLIENT_TYPES:
            workspace.handle_client(msg, sub)
        else:
            _dispatch(msg)
    except (RequestError, workspace.WorkspaceError) as exc:
        return EvErrorReply(message=str(exc), ref=ref)
    except Exception as exc:
        events.log("error", "ws", f"Handling {msg.type} failed: {type(exc).__name__}: {exc}")
        return EvErrorReply(message=f"{type(exc).__name__}: {exc}", ref=ref)
    return None


# --------------------------------- socket ---------------------------------


async def _pump(ws: WebSocket, sub: Subscriber) -> None:
    while True:
        frame = await sub.get()
        if frame is None:
            events.log("warn", "ws", f"Dropping a client that fell {events.QUEUE_SIZE} events behind")
            await ws.close(code=_CLOSE_TOO_SLOW, reason="Too far behind; reconnect to resync")
            return
        await ws.send_text(frame)


async def _receive(ws: WebSocket, sub: Subscriber) -> None:
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return
        raw = message.get("text")
        if raw is None:
            data = message.get("bytes") or b""
            raw = data.decode("utf-8", errors="replace")
        reply = handle_frame(raw, sub)
        if reply is not None:
            sub.send(reply)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    origin = ws.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        # Browsers always send Origin; refusing foreign ones stops other websites from driving the agent.
        await ws.close(code=1008)
        return
    await ws.accept()
    # Subscribe and capture the active turns in the same synchronous step: every agent event queued
    # from here on applies on top of this snapshot, none is already contained in it.
    sub = bus.subscribe()
    active_turns = agent.active_turns()
    ticker.ensure_running()
    tasks: list[asyncio.Task[None]] = []
    try:
        snapshot = await _snapshot(active_turns)
        await ws.send_text(serialize(EvHello(version=__version__, snapshot=snapshot)))
        tasks = [asyncio.create_task(_pump(ws, sub)), asyncio.create_task(_receive(ws, sub))]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, OSError, RuntimeError)):
                events.log("warn", "ws", f"Socket closed after error: {type(exc).__name__}: {exc}")
    except (WebSocketDisconnect, OSError, RuntimeError):
        pass  # client went away (possibly before hello was sent)
    except Exception as exc:  # e.g. the snapshot could not be built: close cleanly, the client retries
        events.log("error", "ws", f"WebSocket session failed: {type(exc).__name__}: {exc}")
        with contextlib.suppress(Exception):
            await ws.close(code=1011, reason="Server error")
    finally:
        # Synchronous bookkeeping first: if this handler is itself being cancelled, awaits below may not return.
        bus.unsubscribe(sub)
        workspace.release(sub)
        if bus.client_count == 0:
            ticker.stop()
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if ws.application_state == WebSocketState.CONNECTED and ws.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await ws.close()
