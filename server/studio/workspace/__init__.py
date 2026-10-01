"""Agent workspace (OpenMuse port): per-chat folder, PTY terminals, file watching, the agent's browser and
durable background tasks. Agent tools live in ``workspace/tools.py``; REST routes in ``routes/workspace.py``."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..events import Subscriber
from ..schemas import EvErrorReply
from ..schemas_workspace import (BrowserInputMessage, BrowserWatchMessage, TerminalCloseMessage, TerminalInputMessage,
                                 TerminalOpenMessage, TerminalResizeMessage, WorkspaceClientMessage)
from . import checkpoints, state
from .browser import browser
from .files import watcher
from .state import WorkspaceError
from .tasks import tasks
from .terminal import terminals

if TYPE_CHECKING:
    from ..agent.loop import AgentService

__all__ = ["WorkspaceError", "forget_session", "handle_client", "init", "release", "shutdown", "start"]


def init() -> None:
    state.init()
    checkpoints.init()
    tasks.init_db()


def start(agent: AgentService) -> None:
    watcher.sync()
    tasks.start(agent)


async def shutdown() -> None:
    """Before the agent stops its turns: tasks must know it's a shutdown, not a user stop."""
    await tasks.shutdown()
    terminals.shutdown()
    await watcher.shutdown()
    await browser.shutdown()


async def forget_session(session_id: str) -> None:
    tasks.forget_session(session_id)
    terminals.forget_session(session_id)
    await browser.close(session_id)
    state.forget(session_id)
    checkpoints.forget_session(session_id)
    watcher.sync()


def handle_client(msg: WorkspaceClientMessage, sub: Subscriber) -> None:
    """A workspace frame from one client. Synchronous work raises ``WorkspaceError`` (→ error reply);
    browser work is async and reports its own errors to the sender."""
    if isinstance(msg, TerminalOpenMessage):
        root = state.require_root(msg.session_id)
        terminals.open_shell(msg.session_id, root, msg.cols or 120, msg.rows or 30)
    elif isinstance(msg, TerminalInputMessage):
        terminals.get(msg.id).write(msg.data)
    elif isinstance(msg, TerminalResizeMessage):
        terminals.get(msg.id).resize(msg.cols, msg.rows)
    elif isinstance(msg, TerminalCloseMessage):
        terminals.close(msg.id)
    elif isinstance(msg, BrowserWatchMessage):
        _spawn(browser.watch(msg.session_id, sub, msg.watching), sub, msg.ref)
    elif isinstance(msg, BrowserInputMessage):
        _spawn(browser.user_input(msg.session_id, msg.input), sub, msg.ref)


def release(sub: Subscriber) -> None:
    """A client disconnected: stop streaming the browser to it."""
    asyncio.ensure_future(browser.release(sub))


def _spawn(coro: object, sub: Subscriber, ref: str | None) -> None:
    async def run() -> None:
        try:
            await coro  # type: ignore[misc]
        except WorkspaceError as exc:
            sub.send(EvErrorReply(message=str(exc), ref=ref))

    asyncio.ensure_future(run())
