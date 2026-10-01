"""In-process pub/sub feeding the ``/api/ws`` WebSocket.

``publish`` is thread-safe: job threads and worker log readers call it from outside the event
loop, so delivery is marshalled onto the loop with ``call_soon_threadsafe``. Each event is
serialized once and fanned out to every connected client's bounded queue. A client that falls
``QUEUE_SIZE`` frames behind is dropped (its socket gets closed and it resyncs from ``hello`` on
reconnect) instead of blocking the others or buffering without limit.
"""

from __future__ import annotations

import asyncio
import json
import logging

from pydantic import BaseModel

from .db import now_iso
from .schemas import EvLog, LogLevel

logger = logging.getLogger("studio")

QUEUE_SIZE = 2000
_PY_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


def serialize(event: BaseModel) -> str:
    """One WebSocket text frame. Optional fields are omitted, never ``null``."""
    return json.dumps(event.model_dump(mode="json", exclude_none=True), ensure_ascii=False)


class Subscriber:
    """One connected client's outgoing frames. Only touched from the event loop."""

    def __init__(self) -> None:
        # +1 slot so the drop sentinel always fits.
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=QUEUE_SIZE + 1)
        self.dropped = False

    def put(self, frame: str) -> None:
        if self.dropped:
            return
        if self._queue.qsize() >= QUEUE_SIZE:
            self.dropped = True
            while not self._queue.empty():  # free the backlog now; the client will resync anyway
                self._queue.get_nowait()
            self._queue.put_nowait(None)
            return
        self._queue.put_nowait(frame)

    def send(self, event: BaseModel) -> None:
        """Queue a frame for this client only (e.g. an error reply)."""
        self.put(serialize(event))

    @property
    def backlog(self) -> int:
        """Frames queued but not yet sent (lets bulky optional streams skip a slow client)."""
        return self._queue.qsize()

    async def get(self) -> str | None:
        """Next frame, or ``None`` once this client has been dropped for falling behind."""
        return await self._queue.get()


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def client_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: BaseModel) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        frame = serialize(event)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(frame)
        else:
            loop.call_soon_threadsafe(self._deliver, frame)

    def _deliver(self, frame: str) -> None:
        for sub in list(self._subscribers):
            sub.put(frame)

    def subscribe(self) -> Subscriber:
        """Register a client (call on the event loop). Events published from now on are queued for it."""
        sub = Subscriber()
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)


bus = EventBus()


def log(level: LogLevel, source: str, message: str) -> None:
    """Log to Python logging and broadcast a ``log`` server event."""
    logger.log(_PY_LEVELS[level], "[%s] %s", source, message)
    bus.publish(EvLog(level=level, source=source, message=message, ts=now_iso()))
