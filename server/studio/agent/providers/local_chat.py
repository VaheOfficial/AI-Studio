"""Chat through the local GGUF runtimes — the built-in llama.cpp server and LM Studio — over their OpenAI-compatible
endpoints. Model ids are the studio's installed-model ids; the first message loads the model through
``models.ensure_loaded`` so VRAM arbitration evicts other models first."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import AsyncIterator

import httpx

from ... import db, llamacpp, lmstudio, settings
from ...localhttp import client
from ...models import ModelError, models
from ...runtimes import WorkerError
from ...schemas import ChatModelOption, InstalledModel, LocalBackendId
from ..types import Message, ModelInfo, ProviderError, StreamEvent, ToolSpec
from .openai_chat import OpenAIProvider, looks_like_vision


class _LocalProvider(OpenAIProvider):
    runtime = ""

    def __init__(self, model_id: str) -> None:
        super().__init__(model_id, "", None)

    @abstractmethod
    def _endpoint(self) -> str:
        """OpenAI-compatible base URL once the model is loaded."""

    async def _ready(self) -> None:
        try:
            m = await asyncio.to_thread(models.ensure_loaded, self.model)
        except (ModelError, lmstudio.LMStudioError) as exc:
            raise ProviderError(str(exc)) from exc
        if m.runtime != self.runtime:
            raise ProviderError(f"{m.name} runs on {m.runtime}, not {self.runtime}")
        self.base_url = self._endpoint()

    async def info(self) -> ModelInfo:
        """The loaded model's context window, so the agent loop trims and summarizes before the server refuses an
        oversized request (without it the chat grew until llama-server answered 400)."""
        await self._ready()
        return await self._model_info()

    async def _model_info(self) -> ModelInfo:
        return ModelInfo(vision=looks_like_vision(self.model), context=settings.load().llamacpp_ctx_size)

    async def stream(self, system: str, history: list[Message], tools: list[ToolSpec] | None
                     ) -> AsyncIterator[StreamEvent]:
        await self._ready()
        async for event in super().stream(system, history, tools):
            yield event

    async def complete(self, system: str, prompt: str) -> str:
        await self._ready()
        return await super().complete(system, prompt)


class LlamaCppProvider(_LocalProvider):
    runtime = "llamacpp"

    def _endpoint(self) -> str:
        url = llamacpp.server.base_url(self.model)
        if url is None:
            raise ProviderError("llama-server stopped before the request could be sent; send the message again")
        return url

    async def _model_info(self) -> ModelInfo:
        """From the running server: ``--fit`` may have lowered the context below the setting to fit the VRAM, and
        a vision projector (mmproj) makes the model see images whatever its name says."""
        fallback = await super()._model_info()
        try:
            r = await asyncio.to_thread(client.get, self.base_url.removesuffix("/v1") + "/props", timeout=5)
            props = r.json()
        except (httpx.HTTPError, ValueError):
            return fallback
        n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
        vision = (props.get("modalities") or {}).get("vision")
        return ModelInfo(vision=bool(vision) if vision is not None else fallback.vision,
                         context=int(n_ctx) if n_ctx else fallback.context)


class LMStudioProvider(_LocalProvider):
    runtime = "lmstudio"

    def _endpoint(self) -> str:
        return f"{lmstudio.API}/v1"


PROVIDERS: dict[str, type[_LocalProvider]] = {"llamacpp": LlamaCppProvider, "lmstudio": LMStudioProvider}


def options() -> list[ChatModelOption]:
    """Installed text models of the llama.cpp and LM Studio runtimes (llama-server uses --jinja: tools work)."""
    available = {"llamacpp": llamacpp.installed(), "lmstudio": lmstudio.installed()}
    return [ChatModelOption(id=f"{m.runtime}:{m.id}", provider=m.runtime, name=m.name, tools=True,
                            available=available[m.runtime], vision=_sees(m))
            for m in db.list_installed()
            if m.kind == "text" and m.runtime in available and not llamacpp.is_draft_model(m)]


def _sees(m: InstalledModel) -> bool:
    """A llama.cpp model with a vision projector (mmproj) takes images; LM Studio models go by their name."""
    if m.runtime == "llamacpp":
        try:
            return llamacpp.model_files(m)[1] is not None
        except WorkerError:
            return False
    return looks_like_vision(m.name)


def preferred_first(opts: list[ChatModelOption], backend: LocalBackendId) -> list[ChatModelOption]:
    """The default local backend's models lead the list (they're picked when no chat model is set)."""
    return sorted(opts, key=lambda o: o.provider != backend)
