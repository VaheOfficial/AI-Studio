"""OpenRouter chat: any OpenRouter model as the agent's brain, with tools, reasoning and per-step cost."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ... import openrouter, openrouter_catalog, openrouter_usage
from ...openrouter import OpenRouterError, Usage
from ..types import (Call, CallDraft, Message, ModelInfo, ProviderError, StepEnd, StreamEvent, TextDelta, ThinkingDelta,
                     ToolSpec)
from .base import Provider
from .openai_chat import followup_content, mark_cache_breakpoints, user_content

_TITLE_MAX_TOKENS = 800  # headroom for models that reason before answering (they are asked to keep it short)


# Providers that cache prompts only where the request marks a breakpoint (OpenRouter passes `cache_control` through);
# OpenAI, DeepSeek, Grok and most others cache repeated prefixes automatically.
_EXPLICIT_CACHE = ("anthropic/", "google/gemini")


def _cache_breakpoints(model: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cache breakpoints for the models that need them (see ``mark_cache_breakpoints``)."""
    return mark_cache_breakpoints(messages) if model.startswith(_EXPLICIT_CACHE) else messages


def _merge_reasoning(acc: list[dict[str, Any]], items: list[Any]) -> None:
    """Rebuild ``reasoning_details`` from stream fragments: consecutive pieces of the same
    (type, index) are one block whose text is concatenated; other fields keep their latest value."""
    for item in items:
        if not isinstance(item, dict):
            continue
        last = acc[-1] if acc else None
        if last is None or last.get("type") != item.get("type") or last.get("index") != item.get("index"):
            acc.append(dict(item))
            continue
        for k, v in item.items():
            if k in ("text", "summary", "data") and isinstance(v, str):
                last[k] = (last.get(k) or "") + v
            elif v is not None:
                last[k] = v


class OpenRouterProvider(Provider):
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self.api_key = api_key

    async def info(self) -> ModelInfo:
        m = next((m for m in openrouter_catalog.pins() if m.id == self.model), None)
        return ModelInfo(vision=bool(m and "image" in m.input_modalities), context=m.context_length if m else None)

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
                # Reasoning must go back unmodified while the model is mid tool loop (signed/encrypted blocks)
                if isinstance(m.raw, dict) and m.raw.get("reasoning_details"):
                    msg["reasoning_details"] = m.raw["reasoning_details"]
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

    async def stream(self, system: str, history: list[Message], tools: list[ToolSpec] | None
                     ) -> AsyncIterator[StreamEvent]:
        body: dict[str, Any] = {"model": self.model, "messages": _cache_breakpoints(self.model,
                                                                            self._messages(system, history))}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        text: list[str] = []
        partial: dict[int, dict[str, str]] = {}
        details: list[dict[str, Any]] = []
        stop: str | None = None
        generation_id: str | None = None
        usage: Usage | None = None
        try:
            async for chunk in openrouter.stream_chat(body, self.api_key):
                generation_id = chunk.get("id") or generation_id
                if chunk.get("usage"):
                    usage = Usage.from_json(chunk["usage"], generation_id)
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning"):
                        yield ThinkingDelta(delta["reasoning"])
                    if delta.get("reasoning_details"):
                        _merge_reasoning(details, delta["reasoning_details"])
                    if delta.get("content"):
                        text.append(delta["content"])
                        yield TextDelta(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = partial.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["args"] += fn.get("arguments") or ""
                        yield CallDraft(slot["name"], len(slot["args"]))
                    stop = choice.get("finish_reason") or stop
        except OpenRouterError as exc:
            raise ProviderError(str(exc)) from exc
        if usage is not None:
            yield usage
        calls = []
        for slot in partial.values():
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": slot["args"]}
            calls.append(Call(id=f"call_{uuid.uuid4().hex[:12]}", name=slot["name"], args=args))
        yield StepEnd(text="".join(text), calls=calls, raw={"reasoning_details": details} if details else None,
                      stop_reason=stop)

    async def complete(self, system: str, prompt: str) -> str:
        body = {"model": self.model, "max_tokens": _TITLE_MAX_TOKENS, "reasoning": {"effort": "low"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        try:
            message, usage = await openrouter.chat(body, self.api_key)
        except OpenRouterError as exc:
            raise ProviderError(str(exc)) from exc
        openrouter_usage.record("title", self.model, usage)
        return str(message.get("content") or "")
