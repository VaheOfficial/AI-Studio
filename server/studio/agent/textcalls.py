"""Tool calls a model wrote as text. Some local models (or their Ollama chat templates) don't emit native tool calls:
they print the call in the format they were trained on — Anthropic-style XML (``<function_calls><invoke name=…>
<parameter name=…>``, often namespaced like ``<x:invoke>``) or Hermes/Qwen ``<tool_call>{"name", "arguments"}
</tool_call>``. Nothing would run and the turn would end, so recover those calls (known tool names only) and drop the
markup from the text."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .types import Call

_NS = r"(?:[\w-]+:)?"
_XML_BLOCK = re.compile(rf"<{_NS}function_calls>(.*?)(?:</{_NS}function_calls>|$)", re.DOTALL)
_XML_INVOKE = re.compile(rf"<{_NS}invoke\s+name=[\"']([\w.-]+)[\"']\s*>(.*?)(?:</{_NS}invoke>|$)", re.DOTALL)
_XML_PARAM = re.compile(rf"<{_NS}parameter\s+name=[\"']([\w.-]+)[\"']\s*>(.*?)</{_NS}parameter>", re.DOTALL)
_HERMES = re.compile(r"<tool_call>\s*(\{.*?\})\s*(?:</tool_call>|$)", re.DOTALL)


def _value(raw: str) -> Any:
    """Parameter text as JSON when it is JSON (numbers, lists, objects), else the string itself."""
    text = raw.strip()
    if text[:1] in "[{" or text in ("true", "false", "null") or re.fullmatch(r"-?\d+(\.\d+)?", text):
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text


def _call(name: str, args: dict[str, Any]) -> Call:
    return Call(id=f"call_{uuid.uuid4().hex[:12]}", name=name, args=args)


def extract(text: str, known: set[str]) -> tuple[str, list[Call]]:
    """(text without the call markup, recovered calls) — the text unchanged and no calls when there are none."""
    calls: list[Call] = []
    spans: list[tuple[int, int]] = []
    for block in _XML_BLOCK.finditer(text):
        found = [(m.group(1), {k: _value(v) for k, v in _XML_PARAM.findall(m.group(2))})
                 for m in _XML_INVOKE.finditer(block.group(1))]
        if found and all(name in known for name, _ in found):
            calls += [_call(name, args) for name, args in found]
            spans.append(block.span())
    for m in _HERMES.finditer(text):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        name = data.get("name") if isinstance(data, dict) else None
        args = data.get("arguments", data.get("parameters", {})) if isinstance(data, dict) else None
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = None
        if name in known and isinstance(args, dict):
            calls.append(_call(name, args))
            spans.append(m.span())
    if not calls:
        return text, []
    clean = text
    for start, end in sorted(spans, reverse=True):
        clean = clean[:start] + clean[end:]
    return clean.strip(), calls
