"""Account for every reasoning/research/compaction request against one mission budget."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

from .. import db, settings
from ..agent.providers.base import Provider
from ..agent.types import Message, ModelInfo, ProviderError, StepEnd, StreamEvent, ToolSpec, Usage
from . import store


def local(model: str) -> bool:
    provider = model.partition(":")[0]
    return provider in ("ollama", "llamacpp", "lmstudio") or (provider == "openai" and
        urlparse(settings.load().openai_base_url or "").hostname in ("localhost", "127.0.0.1", "::1"))


class MissionProvider(Provider):
    def __init__(self, inner: Provider, sid: str, allow_inactive: bool = False, model_override: str | None = None) -> None:
        self.inner, self.sid, self.allow_inactive = inner, sid, allow_inactive
        self.model_override = model_override

    async def info(self) -> ModelInfo:
        self.inner.context_limit = self.context_limit
        return await self.inner.info()

    async def stream(self, system: str, history: list[Message], tools: list[ToolSpec] | None
                     ) -> AsyncIterator[StreamEvent]:
        m = store.get(self.sid)
        session = db.get_session(self.sid)
        if session is None:
            raise ProviderError("Agent+ chat no longer exists")
        remote = not local(self.model_override or session.model)
        reservation = 0.25 if remote else 0.0
        if m.status != "running" and not self.allow_inactive:
            raise ProviderError(m.reason or "Mission is not running")
        if m.requests >= m.max_requests or (remote and m.cost + m.reserved_cost + reservation > m.max_cost):
            if m.status not in ('completed', 'cancelled'):
                m.status = 'paused'
            m.reason = "Request or spending budget reached. Review the mission before continuing."
            store.save(m)
            raise ProviderError(m.reason)
        m.requests += 1
        m.reserved_cost += reservation
        store.save(m)
        billed: float | None = None
        finished = False
        try:
            self.inner.context_limit = self.context_limit
            async for ev in self.inner.stream(system, history, tools):
                if isinstance(ev, Usage) and ev.cost is not None:
                    billed = (billed or 0) + ev.cost
                if isinstance(ev, StepEnd):
                    finished = True
                yield ev
        finally:
            m = store.get(self.sid)
            m.reserved_cost = round(max(0, m.reserved_cost - reservation), 8)
            # Unmetered remote or interrupted requests retain the reservation as estimated spend.
            m.cost = round(m.cost + (billed if billed is not None else reservation), 8)
            if remote and (not finished or billed is None):
                store.event(self.sid, "cost", "Remote request cost is estimated; provider did not return a final cost.")
            if m.cost >= m.max_cost and remote:
                if m.status not in ('completed', 'cancelled'):
                    m.status = 'paused'
                m.reason = "Spending budget reached."
            store.save(m)

    async def complete(self, system: str, prompt: str) -> str:
        answer = ""
        async for ev in self.stream(system, [Message("user", prompt)], None):
            if isinstance(ev, StepEnd):
                answer = ev.text
        return answer
