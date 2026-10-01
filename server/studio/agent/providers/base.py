"""Provider interface: stream one model response over provider-neutral history."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..types import Message, ModelInfo, StreamEvent, ToolSpec


class Provider(ABC):
    # A chat's own context window (``/context``); providers that size requests themselves (Ollama) honor it
    context_limit: int | None = None

    @abstractmethod
    def stream(self, system: str, history: list[Message], tools: list[ToolSpec] | None
               ) -> AsyncIterator[StreamEvent]:
        """Yield text/thinking deltas, then exactly one ``StepEnd``."""

    @abstractmethod
    async def complete(self, system: str, prompt: str) -> str:
        """Short non-streaming completion without tools (used for titles)."""

    async def info(self) -> ModelInfo:
        """Whether the model sees images and its context window; unknown by default."""
        return ModelInfo()
