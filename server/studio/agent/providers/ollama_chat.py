"""Ollama ``/api/chat`` streaming with tool calls and thinking."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ... import config, ollama, settings
from ...localhttp import tls
from ...models import models
from .. import images
from ..types import (Call, Message, ModelInfo, ProviderError, StepEnd, StreamEvent, TextDelta, ThinkingDelta,
                     ToolSpec)
from .base import Provider

MIN_CTX = 4096


class OllamaProvider(Provider):
    def __init__(self, model: str) -> None:
        self.model = model

    async def _capabilities(self) -> list[str]:
        """Start Ollama if needed and make VRAM room for the model before the request loads it."""
        try:
            await asyncio.to_thread(ollama.ensure_running)
            await asyncio.to_thread(models.prepare_ollama_chat, self.model)
            return await asyncio.to_thread(ollama.capabilities, self.model)
        except ollama.OllamaError as exc:
            raise ProviderError(str(exc)) from exc

    async def info(self) -> ModelInfo:
        """Vision from Ollama's capabilities; the context is the Settings value, capped at what the model supports."""
        caps = await self._capabilities()
        trained = await asyncio.to_thread(ollama.context_length, self.model)
        want = self.context_limit or settings.load().ollama_ctx_size
        return ModelInfo(vision="vision" in caps, context=max(MIN_CTX, min(want, trained or want)))

    @staticmethod
    def _messages(system: str, history: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        pending: list[tuple[str, list[Any]]] = []  # pictures from the current run of tool results
        for i, m in enumerate(history):
            if m.role == "user":
                msg = {"role": "user", "content": m.content}
                if m.images:
                    msg["images"] = [images.encode(p)[1] for p in m.images]
                out.append(msg)
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content}
                if m.calls:
                    msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.args}} for c in m.calls]
                out.append(msg)
            else:
                out.append({"role": "tool", "content": m.content, "tool_name": m.name or ""})
            if m.role == "tool" and m.images:
                pending.append((m.name or "tool", m.images))
            if pending and (i + 1 == len(history) or history[i + 1].role != "tool"):
                # Ollama only shows images from user messages: deliver them right after the tool results, labeled
                out.append({"role": "user", "content": images.tool_followup(pending),
                            "images": [images.encode(p)[1] for _, paths in pending for p in paths]})
                pending = []
        return out

    async def stream(self, system: str, history: list[Message], tools: list[ToolSpec] | None
                     ) -> AsyncIterator[StreamEvent]:
        caps = await self._capabilities()
        ctx = (await self.info()).context
        messages = await asyncio.to_thread(self._messages, system, history)  # encodes images
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True,
                                "options": {"num_ctx": ctx}}
        if tools:
            if "tools" not in caps:
                raise ProviderError(f"{self.model} does not support tool calling in Ollama; switch the session to "
                                    "chat mode or pick a tools-capable model (e.g. qwen3, gpt-oss, llama3.1).")
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        if "thinking" in caps:
            body["think"] = True

        text: list[str] = []
        calls: list[Call] = []
        stop: str | None = None
        used: int | None = None
        generated: int | None = None
        seconds: float | None = None
        async with httpx.AsyncClient(verify=tls, timeout=httpx.Timeout(30, read=600)) as client:
            async with client.stream("POST", f"{config.OLLAMA_URL}/api/chat", json=body) as r:
                if r.status_code >= 400:
                    detail = (await r.aread()).decode(errors="replace")
                    try:
                        detail = json.loads(detail).get("error", detail)
                    except ValueError:
                        pass
                    raise ProviderError(f"Ollama chat failed ({r.status_code}): {detail}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise ProviderError(f"Ollama: {chunk['error']}")
                    msg = chunk.get("message") or {}
                    if msg.get("thinking"):
                        yield ThinkingDelta(msg["thinking"])
                    if msg.get("content"):
                        text.append(msg["content"])
                        yield TextDelta(msg["content"])
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function", {})
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {"_raw": args}
                        # Always mint our own id: Ollama's ids can repeat when a model re-issues the
                        # same call, which would collide in the approval registry and persistence.
                        calls.append(Call(id=f"call_{uuid.uuid4().hex[:12]}", name=fn.get("name", ""), args=args))
                    if chunk.get("done"):
                        stop = chunk.get("done_reason")
                        if chunk.get("prompt_eval_count") is not None:
                            used = int(chunk["prompt_eval_count"]) + int(chunk.get("eval_count") or 0)
                        if chunk.get("eval_count") and chunk.get("eval_duration"):
                            generated = int(chunk["eval_count"])
                            seconds = int(chunk["eval_duration"]) / 1e9  # nanoseconds
        yield StepEnd(text="".join(text), calls=calls, stop_reason=stop, prompt_tokens=used, output_tokens=generated,
                      generation_s=seconds)

    async def complete(self, system: str, prompt: str) -> str:
        await self._capabilities()
        body = {"model": self.model, "stream": False, "think": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "options": {"num_predict": 64}}
        async with httpx.AsyncClient(verify=tls, timeout=60) as client:
            r = await client.post(f"{config.OLLAMA_URL}/api/chat", json=body)
            if r.status_code == 400 and "think" in r.text:
                body.pop("think")
                r = await client.post(f"{config.OLLAMA_URL}/api/chat", json=body)
        if r.status_code >= 400:
            raise ProviderError(f"Ollama chat failed ({r.status_code}): {r.text[:300]}")
        return str(r.json().get("message", {}).get("content", ""))
