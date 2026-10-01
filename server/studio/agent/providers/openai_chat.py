"""OpenAI-compatible ``/chat/completions`` streaming with tool calls (vLLM, SGLang, hosted APIs)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ...localhttp import tls
from .. import images
from ..types import (Call, Message, ModelInfo, ProviderError, StepEnd, StreamEvent, TextDelta, ThinkingDelta,
                     ToolSpec)
from .base import Provider

# vLLM/SGLang don't report modalities; vision models are recognizable by name (Qwen2.5-VL, Llama-3.2-Vision, …)
_VISION_NAMES = ("-vl", "vl-", "vision", "gemma-3", "gemma3", "gemma-4", "pixtral", "llava", "internvl", "minicpm-v")


def looks_like_vision(model: str) -> bool:
    return any(n in model.lower() for n in _VISION_NAMES)


def user_content(m: Message) -> str | list[dict[str, Any]]:
    """A user message's content: plain text, or text plus ``image_url`` parts (base64 data URLs)."""
    if not m.images:
        return m.content
    return [{"type": "text", "text": m.content or "(image)"},
            *({"type": "image_url", "image_url": {"url": images.data_url(p)}} for p in m.images)]


def followup_content(pending: list[tuple[str, list[Any]]]) -> list[dict[str, Any]]:
    """The labeled message carrying pictures that tools returned (see ``images.tool_followup``)."""
    return [{"type": "text", "text": images.tool_followup(pending)},
            *({"type": "image_url", "image_url": {"url": images.data_url(p)}} for _, paths in pending for p in paths)]


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def list_models(base_url: str, api_key: str | None) -> list[str]:
    async with httpx.AsyncClient(verify=tls, timeout=10) as client:
        r = await client.get(f"{base_url}/models", headers=_headers(api_key))
    if r.status_code >= 400:
        raise ProviderError(f"GET {base_url}/models failed ({r.status_code}): {r.text[:200]}")
    return [m["id"] for m in r.json().get("data", [])]


class OpenAIProvider(Provider):
    def __init__(self, model: str, base_url: str, api_key: str | None) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key

    async def info(self) -> ModelInfo:
        return ModelInfo(vision=looks_like_vision(self.model))

    @staticmethod
    def _messages(system: str, history: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        pending: list[tuple[str, list[Any]]] = []  # pictures from the current run of tool results
        for i, m in enumerate(history):
            if m.role == "user":
                out.append({"role": "user", "content": user_content(m)})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.calls:
                    msg["tool_calls"] = [{"id": c.id, "type": "function",
                                          "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                                         for c in m.calls]
                out.append(msg)
            else:
                out.append({"role": "tool", "tool_call_id": m.call_id, "content": m.content})
            if m.role == "tool" and m.images:
                pending.append((m.name or "tool", m.images))
            if pending and (i + 1 == len(history) or history[i + 1].role != "tool"):
                # Tool results are text-only here: deliver the pictures right after them, labeled as tool output
                out.append({"role": "user", "content": followup_content(pending)})
                pending = []
        return out

    async def _post(self, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        async with httpx.AsyncClient(verify=tls, timeout=httpx.Timeout(30, read=600)) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=body,
                                     headers=_headers(self.api_key)) as r:
                if r.status_code >= 400:
                    detail = (await r.aread()).decode(errors="replace")
                    raise ProviderError(f"{self.base_url} chat failed ({r.status_code}): {detail[:500]}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    yield json.loads(data)

    async def stream(self, system: str, history: list[Message], tools: list[ToolSpec] | None
                     ) -> AsyncIterator[StreamEvent]:
        body: dict[str, Any] = {"model": self.model, "messages": self._messages(system, history), "stream": True,
                                "stream_options": {"include_usage": True}}  # token counts in the last chunk
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        text: list[str] = []
        partial: dict[int, dict[str, str]] = {}
        stop: str | None = None
        generated: int | None = None
        seconds: float | None = None
        prompt_tokens: int | None = None
        try:
            async for chunk in self._post(body):
                if (chunk.get("usage") or {}).get("completion_tokens") is not None:
                    generated = int(chunk["usage"]["completion_tokens"])
                if (chunk.get("usage") or {}).get("prompt_tokens") is not None:
                    prompt_tokens = int(chunk["usage"]["prompt_tokens"])
                timings = chunk.get("timings") or {}  # llama-server: its own decode count and time
                if timings.get("predicted_n") and timings.get("predicted_ms"):
                    generated, seconds = int(timings["predicted_n"]), float(timings["predicted_ms"]) / 1000
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        yield ThinkingDelta(reasoning)
                    if delta.get("content"):
                        text.append(delta["content"])
                        yield TextDelta(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = partial.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["args"] += fn.get("arguments") or ""
                    stop = choice.get("finish_reason") or stop
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach {self.base_url}: {exc}") from exc
        calls = []
        for slot in partial.values():
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": slot["args"]}
            # Our own ids (history is replayed from our records, so provider ids aren't needed and
            # some servers reuse them across steps).
            calls.append(Call(id=f"call_{uuid.uuid4().hex[:12]}", name=slot["name"], args=args))
        yield StepEnd(text="".join(text), calls=calls, stop_reason=stop, prompt_tokens=prompt_tokens,
                      output_tokens=generated, generation_s=seconds)

    async def complete(self, system: str, prompt: str) -> str:
        body = {"model": self.model, "stream": False, "max_tokens": 64,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        async with httpx.AsyncClient(verify=tls, timeout=60) as client:
            r = await client.post(f"{self.base_url}/chat/completions", json=body, headers=_headers(self.api_key))
        if r.status_code >= 400:
            raise ProviderError(f"{self.base_url} chat failed ({r.status_code}): {r.text[:300]}")
        return str(r.json()["choices"][0]["message"].get("content") or "")
