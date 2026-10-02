"""Provider-neutral conversation and streaming types used by the agent loop."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from ..openrouter import Usage
from ..schemas import Output


@dataclass
class Call:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    calls: list[Call] = field(default_factory=list)
    # tool results
    call_id: str | None = None
    name: str | None = None
    is_error: bool = False
    # Images the model sees with this message (local files; providers downscale and encode them)
    images: list[Path] = field(default_factory=list)
    # Provider-native assistant content for exact replay inside the current turn (e.g. OpenRouter's
    # reasoning details). Never persisted.
    raw: Any = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (type=object)
    needs_approval: bool = False
    # For a tool that is only sometimes risky: given the arguments, the name of the tool whose approval rule
    # applies to this call (the user allowing that tool allows this too), or None when the call needs no approval
    asks_like: Callable[[dict[str, Any]], str | None] | None = None


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class CallDraft:
    """The model is writing a tool call: the tool's name as far as it is known, and how long the arguments are so
    far. The call itself arrives with ``StepEnd``; this only says that something is being written."""

    name: str
    size: int


@dataclass
class StepEnd:
    """The model finished one response; ``calls`` are tools it wants to run."""

    text: str
    calls: list[Call]
    raw: Any = None
    stop_reason: str | None = None
    prompt_tokens: int | None = None  # what the request actually used, when the provider reports it
    cached_tokens: int | None = None  # the part of prompt_tokens read from the provider's prompt cache
    output_tokens: int | None = None  # tokens the model generated in this step, when the provider reports them
    generation_s: float | None = None  # the provider's own generation time (llama.cpp, Ollama); else the loop times it


# ``Usage`` (from providers that bill per request, e.g. OpenRouter) arrives just before ``StepEnd``.
StreamEvent = TextDelta | ThinkingDelta | CallDraft | Usage | StepEnd


@dataclass
class ModelInfo:
    """What the loop needs to know about the chat model: whether it can see images, and the context window a
    request gets (tokens; None = unknown, the provider's own limit applies)."""

    vision: bool = False
    context: int | None = None


class ProviderError(RuntimeError):
    """User-facing provider failure (bad key, model missing, endpoint down…)."""


@dataclass
class ToolContext:
    """What a tool knows about the call it serves: its chat session, and a way to push a live
    ``display`` (a ``ToolDisplay`` model) while it runs."""

    session_id: str
    call_id: str
    progress: Callable[[BaseModel], None]
    # Asks the user a question in the chat and waits for the answer (ask_user); None outside an agent turn
    ask: Callable[[str, list[str]], Awaitable[str]] | None = None
    vision: bool = False  # the chat model can see images


@dataclass
class ToolOutcome:
    ok: bool
    output: str
    artifacts: list[Output] = field(default_factory=list)
    display: BaseModel | None = None
    # Images for the model to look at (a screenshot, a generated picture); only sent to models that can see
    images: list[Path] = field(default_factory=list)


class ToolFailure(Exception):
    """Expected tool error; the message is returned to the model."""
