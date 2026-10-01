"""Chat providers keyed by the ``<provider>:<model>`` ids used in sessions."""

from __future__ import annotations

import asyncio

import httpx

from ... import catalog, events, ollama, openrouter_catalog, settings
from ...schemas import ChatModelOption
from ..types import ProviderError
from .base import Provider
from .local_chat import PROVIDERS as LOCAL_PROVIDERS
from .local_chat import options as local_options
from .local_chat import preferred_first
from .ollama_chat import OllamaProvider
from .openai_chat import OpenAIProvider, looks_like_vision
from .openai_chat import list_models as list_openai_models
from .openrouter_chat import OpenRouterProvider

__all__ = ["Provider", "ProviderError", "get_provider", "list_chat_models"]


def get_provider(model_id: str) -> Provider:
    provider, sep, model = model_id.partition(":")
    if not sep or not model:
        raise ProviderError(f"Model id '{model_id}' must look like '<provider>:<model>'")
    s = settings.load()
    if provider == "ollama":
        return OllamaProvider(model)
    if provider in LOCAL_PROVIDERS:
        return LOCAL_PROVIDERS[provider](model)
    if provider == "openai":
        if not s.openai_base_url:
            raise ProviderError("No OpenAI-compatible base URL configured; add one in Settings")
        return OpenAIProvider(model, s.openai_base_url, s.openai_api_key)
    if provider == "openrouter":
        if not s.openrouter_api_key:
            raise ProviderError("No OpenRouter API key configured; add one in Settings → Providers")
        return OpenRouterProvider(model, s.openrouter_api_key)
    raise ProviderError(f"Unknown provider '{provider}' (expected ollama, llamacpp, lmstudio, openai or "
                        "openrouter)")


def _ollama_options() -> list[ChatModelOption]:
    if not ollama.version():
        return []
    try:
        tags = sorted(t["name"] for t in ollama.tags())
    except (ollama.OllamaError, httpx.HTTPError) as exc:
        events.log("warn", "ollama", f"Could not list Ollama models: {exc}")
        return []
    # Catalog models get their friendly name ("MiMo V2.6 Distill (Qwen 9B)", not "hf.co/…:Q8_0")
    names = {s.ollama_tag: s.name for s in catalog.SPECS if s.ollama_tag}
    result = []
    for tag in tags:
        try:
            caps = ollama.capabilities(tag)
        except ollama.OllamaError as exc:
            events.log("warn", "ollama", f"Could not read capabilities of {tag}: {exc}")
            caps = []
        if "embedding" in caps and "completion" not in caps:
            continue  # embedding-only models can't chat
        result.append(ChatModelOption(id=f"ollama:{tag}", provider="ollama", name=names.get(tag, tag),
                                      tools="tools" in caps, vision="vision" in caps,
                                      context_length=ollama.context_length(tag) if caps else None,
                                      available=True))
    return result


async def list_chat_models() -> list[ChatModelOption]:
    s = settings.load()
    local = await asyncio.to_thread(lambda: _ollama_options() + local_options())
    options = preferred_first(local, s.default_local_backend)
    if s.openai_base_url:
        try:
            ids = await list_openai_models(s.openai_base_url, s.openai_api_key)
            options += [ChatModelOption(id=f"openai:{mid}", provider="openai", name=mid, tools=True, available=True,
                                        vision=looks_like_vision(mid)) for mid in ids]
        except (ProviderError, httpx.HTTPError, ValueError) as exc:
            events.log("warn", "openai", f"Could not list models from {s.openai_base_url}: {exc}")
    options += openrouter_catalog.chat_options(bool(s.openrouter_api_key))
    return options
