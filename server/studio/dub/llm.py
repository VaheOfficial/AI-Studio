"""One-shot chat completions for translation/fitting, through the studio's chat providers.

Job code runs in plain threads, so each call drives the provider's async stream on its own event loop.
``<think>`` blocks some local models inline in the text are stripped (VoiceStudio ``llm_backend``)."""

from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor

from ..agent.providers import ProviderError, get_provider
from ..agent.types import Message, StepEnd

_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
CONCURRENCY = 4


class LLMError(RuntimeError):
    pass


class Chat:
    """A chat model bound by id (``<provider>:<model>``).

    The provider is resolved per call: each call runs on its own event loop (pool threads), and a provider
    that caches an async client must never reuse it across loops."""

    def __init__(self, model_id: str) -> None:
        try:
            get_provider(model_id)  # validate early: unknown provider / missing key
        except ProviderError as exc:
            raise LLMError(str(exc)) from exc
        self.model_id = model_id

    def __call__(self, system: str, user: str) -> str:
        async def run() -> str:
            text = ""
            provider = get_provider(self.model_id)
            async for ev in provider.stream(system, [Message(role="user", content=user)], None):
                if isinstance(ev, StepEnd):
                    text = ev.text
            return text

        try:
            out = asyncio.run(run())
        except ProviderError as exc:
            raise LLMError(str(exc)) from exc
        except Exception as exc:  # transport errors surface raw from some providers
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        out = _THINK_RE.sub("", out).strip()
        if len(out) > 1 and out[0] == out[-1] == '"':  # models sometimes wrap the whole line in quotes
            out = out[1:-1].strip()
        return out


def pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=CONCURRENCY, thread_name_prefix="dub-llm")
