"""Provider interface: stream one model response over provider-neutral history."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..types import Message, ModelInfo, StreamEvent, ToolSpec

TITLE_SYSTEM = ("Write a 3-6 word title for a conversation that starts with the message you are given. Reply with "
                "the title only: no quotes, no punctuation at the end. Do not answer the message.")
# The same request, as a message at the end of the chat's own prompt (see ``Provider.title``)
TITLE_ASK = ("(Automatic request, not from the user.) Don't answer the message above and don't call a tool. Reply "
             "with only a 3-6 word title for a conversation that starts with it: no quotes, no punctuation at the "
             "end.")


class Provider(ABC):
    # A chat's own context window (``/context``); providers that size requests themselves (Ollama) honor it
    context_limit: int | None = None

    @abstractmethod
    def stream(self, system: str, history: list[Message], tools: list[ToolSpec] | None
               ) -> AsyncIterator[StreamEvent]:
        """Yield text/thinking deltas, then exactly one ``StepEnd``."""

    @abstractmethod
    async def complete(self, system: str, prompt: str) -> str:
        """Short non-streaming completion without tools."""

    async def title(self, system: str, first: Message, tools: list[ToolSpec] | None) -> str:
        """A title for the chat that ``first`` (the user's first message) opens; '' when the model gave none.
        ``system`` and ``tools`` are the chat's own: a provider whose prompt cache holds one conversation at a time
        asks at the end of that same prompt, so the title costs the chat nothing of what is cached."""
        return await self.complete(TITLE_SYSTEM, f"<message>\n{first.content[:1200]}\n</message>\n\nTitle (3-6 words):")

    async def info(self) -> ModelInfo:
        """Whether the model sees images and its context window; unknown by default."""
        return ModelInfo()
