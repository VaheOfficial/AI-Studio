"""Keeping a conversation inside the model's context window.

Local models get 16-64K tokens, and one page read or command output can be several thousand, so a long agent turn
used to overflow and the provider silently dropped the oldest messages - usually the user's request. Before every
model step ``Budget.fit`` applies, in order:

1. Images: only the last few pictures stay attached (older ones become a line naming the file); a model that can't
   see gets none. They go in batches, for the same reason as in 2.
2. Tool-result clearing: past ``TRIM_AT`` of the window, old tool outputs are cut to a short head with a note that
   the tool can be called again. Done in one batch (not a sliding window) so the provider's prompt cache is only
   invalidated once.
3. Compaction: past ``COMPACT_AT``, everything but the user's current request and the latest steps is summarized
   by the chat model itself into one message.

At the start of a turn ``compact_history`` does the same for earlier turns and saves the summary on the session,
so later turns start from it instead of re-summarizing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .. import db, events
from .history import SUMMARY_HEAD
from .providers import Provider
from .types import Message, ModelInfo, ProviderError, StepEnd, TextDelta, ToolSpec

CHARS_PER_TOKEN = 3.2  # conservative for code/JSON-heavy agent transcripts
IMAGE_TOKENS = 1100  # a ~1280 px image in Qwen-VL / Gemma-class models
KEEP_IMAGES = 3  # most recent image-bearing messages that keep their pictures when older ones are taken out...
MAX_IMAGES = 6  # ...which happens when there are more than this many
TRIM_AT = 0.55
COMPACT_AT = 0.80
HISTORY_AT = 0.45  # at the start of a turn, earlier turns above this share of the window get summarized
KEEP_RESULTS = 3  # most recent tool results always kept whole
TRIMMED_HEAD = 400
KEEP_TAIL = 6  # messages kept verbatim after a compaction (from an assistant step on)
MAX_SUMMARY_CHARS = 12_000  # ~3K tokens: a summary longer than that stops saving context
_TRIM_NOTE = "\n[... older output trimmed to save context; call the tool again if you need it]"
_CUT_NOTE = "\n[... cut to fit the context window; ask for less at a time (offset, a narrower query)]"
_SUMMARY_SYSTEM = (
    "You compress an AI agent's working transcript so it can continue the task with far less context. Write a "
    "dense summary in plain prose and short lists. Keep: the user's requests and preferences, decisions made, facts "
    "learned (with exact file paths, URLs, ids, numbers, commands and error messages), what was done and its results, "
    "what failed and why, and what remains to do. Drop chit-chat, repeated attempts and raw output that is no longer "
    "needed. Never invent anything. Do not address the user; do not continue the task.")
_PROGRESS_HEAD = ("(Automatic - your earlier steps on this request were summarized to fit the context window. "
                  "Continue from here.)")


async def compact_now(provider: Provider, session_id: str, limit: int, focus: str | None = None) -> tuple[int, str]:
    """``/compact``: fold the whole chat so far into a saved summary (the next turn starts from it). Returns (messages
    folded, summary); (0, "") when there is nothing to fold."""
    from .history import load

    rows = db.list_message_steps(session_id)
    if not rows:
        return 0, ""
    convo = load(session_id)  # includes an earlier summary, so the new one covers everything
    summary = await summarize(provider, convo, limit, focus)
    existing = db.get_summary(session_id)
    folded = sum(1 for r in rows if not existing or r.seq > existing[1])
    db.set_summary(session_id, summary, rows[-1].seq)
    return folded, summary


def format_tokens(n: int) -> str:
    """Binary units like model cards: 32768 → 32K, 1048576 → 1M."""
    for size, unit in ((1024 * 1024, "M"), (1024, "K")):
        if n >= size:
            x = n / size
            return f"{x:.1f}".rstrip("0").rstrip(".") + unit if x < 10 else f"{round(x)}{unit}"
    return str(n)


# How servers word "the request is bigger than the context window" (llama.cpp, LM Studio, vLLM, OpenAI, Ollama)
_OVERFLOW = re.compile(r"exceeds? the (?:available )?context|context(?: length| window| size)? (?:exceeded|is too small)|"
                       r"maximum context length|prompt is too long|too many tokens|context_length_exceeded|"
                       r"context (?:the )?overflows", re.I)
_TOKEN_COUNTS = re.compile(r"(\d[\d,]*)\s*(?:tokens?\b|maximum)", re.I)


def overflow(message: str) -> tuple[int | None, int | None] | None:
    """(tokens requested, context size) when a provider error says the request didn't fit, else None. llama.cpp:
    "request (32836 tokens) exceeds the available context size (32768 tokens)"; either number may be missing."""
    if not _OVERFLOW.search(message):
        return None
    counts = [int(n.replace(",", "")) for n in _TOKEN_COUNTS.findall(message)]
    if len(counts) >= 2:
        return max(counts), min(counts)
    return (counts[0] if counts else None), None


@dataclass
class Budget:
    info: ModelInfo
    calibration: float = 1.0  # actual/estimated tokens from the last step the provider reported
    last_used: int | None = None
    trimmed: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def limit(self) -> int | None:
        return self.info.context

    def estimate(self, system: str, specs: list[ToolSpec] | None, convo: list[Message]) -> int:
        chars = len(system) + sum(len(m.content) + sum(len(json.dumps(c.args)) + len(c.name) for c in m.calls)
                                  for m in convo)
        if specs:
            chars += sum(len(s.description) + len(json.dumps(s.parameters)) + len(s.name) for s in specs)
        pictures = sum(len(m.images) for m in convo) if self.info.vision else 0
        return int((chars / CHARS_PER_TOKEN + pictures * IMAGE_TOKENS) * self.calibration)

    def observe(self, end: StepEnd, estimated: int) -> None:
        """Learn from what the provider says the request actually used."""
        if end.prompt_tokens:
            self.last_used = end.prompt_tokens
            if estimated > 0:
                self.calibration = max(0.5, min(2.0, self.calibration * end.prompt_tokens / estimated))

    async def recover(self, provider: Provider, system: str, specs: list[ToolSpec] | None, convo: list[Message],
                      current: int, requested: int | None, window: int | None) -> str | None:
        """The server refused the request as too large: learn the real window and how far the estimate was off,
        then make the conversation fit (trimming again even if this turn already trimmed once)."""
        if window:
            self.info.context = min(self.info.context or window, window)
        if not self.limit:
            return None
        estimated = self.estimate(system, specs, convo)
        if requested and estimated > 0:
            self.calibration = max(self.calibration, min(3.0, self.calibration * requested / estimated))
        self.trimmed = False
        return await self.fit(provider, system, specs, convo, current)

    async def fit(self, provider: Provider, system: str, specs: list[ToolSpec] | None, convo: list[Message],
                  current: int) -> str | None:
        """Make ``convo`` fit before the next step (mutates it). ``current``: index of the user's message that
        started this turn. Returns a note for the user when something was trimmed or summarized."""
        limit_images(convo, self.info.vision)
        if not self.limit:
            return None
        notes = []
        if not self.trimmed and self.estimate(system, specs, convo) > TRIM_AT * self.limit:
            count = trim_results(convo, KEEP_RESULTS)
            self.trimmed = True  # once per turn: the next trim would move the cached prefix again
            if count:
                notes.append(f"trimmed {count} older tool output{'s' if count != 1 else ''}")
        if self.estimate(system, specs, convo) > COMPACT_AT * self.limit:
            count = await compact(provider, convo, current, self.limit)
            if count:
                notes.append(f"summarized {count} earlier messages")
        if self.estimate(system, specs, convo) > COMPACT_AT * self.limit:
            # Still too big: the latest steps themselves are huge. Trim all but the newest result, then cut that.
            count = trim_results(convo, 1)
            over = self.estimate(system, specs, convo) - int(COMPACT_AT * self.limit)
            last = next((m for m in reversed(convo) if m.role == "tool"), None)
            if over > 0 and last is not None:
                keep = max(TRIMMED_HEAD, len(last.content) - int(over * CHARS_PER_TOKEN / self.calibration))
                if keep < len(last.content):
                    last.content = last.content[:keep].rstrip() + _CUT_NOTE
                    count += 1
            if count:
                notes.append(f"shortened {count} recent tool output{'s' if count != 1 else ''}")
        if not notes:
            return None
        return f"To stay within the {format_tokens(self.limit)} context: " + ", ".join(notes)


def limit_images(convo: list[Message], vision: bool) -> None:
    """Take older pictures out of the conversation. Taking one out changes an earlier message, and the model then
    reads everything after it again instead of from its prompt cache, so they go in batches: up to ``MAX_IMAGES``
    messages keep theirs, and when there are more, all but the newest ``KEEP_IMAGES`` lose them at once. (One out
    for every one in made a turn that looks at many pictures re-read its last steps at every step.)"""
    bearing = [m for m in convo if m.images]
    if vision and len(bearing) <= MAX_IMAGES:
        return
    keep = KEEP_IMAGES if vision else 0
    seen = 0
    for m in reversed(convo):
        if not m.images:
            continue
        if seen < keep:
            seen += 1
            continue
        names = ", ".join(p.name for p in m.images)
        why = "no longer attached, to save context" if vision else "not shown: this model can't see images"
        m.content = f"{m.content}\n[image{'s' if len(m.images) > 1 else ''} {names} {why}]".strip()
        m.images = []


def trim_results(convo: list[Message], keep: int) -> int:
    """Cut all but the newest ``keep`` tool results to a short head."""
    results = [m for m in convo if m.role == "tool"]
    count = 0
    for m in results[:-keep]:
        if len(m.content) > TRIMMED_HEAD + len(_TRIM_NOTE) and not m.content.endswith(_TRIM_NOTE):
            m.content = m.content[:TRIMMED_HEAD].rstrip() + _TRIM_NOTE
            count += 1
    return count


def _tail_start(convo: list[Message], after: int) -> int:
    """First index of the verbatim tail: an assistant step (so no tool result loses its call) among the last
    ``KEEP_TAIL`` messages, never before ``after``."""
    start = max(after, len(convo) - KEEP_TAIL)
    while start < len(convo) and convo[start].role != "assistant":
        start += 1
    if start >= len(convo):  # no assistant step in the tail window: look further back
        start = max(after, len(convo) - KEEP_TAIL)
        while start > after and convo[start].role != "assistant":
            start -= 1
    return start


def transcript(messages: list[Message], budget_chars: int) -> str:
    """Messages as plain text for the summarizer, tool outputs clipped so the whole fits ``budget_chars``."""
    tools = [m for m in messages if m.role == "tool"]
    other = sum(len(m.content) for m in messages if m.role != "tool")
    share = max(300, min(4000, (budget_chars - other) // max(1, len(tools))))
    lines = []
    for m in messages:
        if m.role == "user":
            lines.append(f"USER: {m.content[:budget_chars // 4]}")
        elif m.role == "assistant":
            calls = "".join(f"\n  -> {c.name}({json.dumps(c.args)[:400]})" for c in m.calls)
            lines.append(f"ASSISTANT: {m.content}{calls}".rstrip())
        else:
            body = m.content if len(m.content) <= share else m.content[:share] + " [...]"
            lines.append(f"TOOL RESULT ({m.name}{', error' if m.is_error else ''}): {body}")
    return "\n\n".join(lines)[-budget_chars:]


async def summarize(provider: Provider, messages: list[Message], limit: int, focus: str | None = None) -> str:
    text = transcript(messages, int(limit * 0.55 * CHARS_PER_TOKEN))
    extra = f" Keep full detail about: {focus.strip()}." if focus and focus.strip() else ""
    prompt = (f"<transcript>\n{text}\n</transcript>\n\nSummarize this transcript as instructed.{extra} Start "
              "directly with the summary.")
    out: list[str] = []
    end: StepEnd | None = None
    size = 0
    stream = provider.stream(_SUMMARY_SYSTEM, [Message("user", prompt)], None)
    try:
        async for ev in stream:
            if isinstance(ev, TextDelta):
                out.append(ev.text)
                size += len(ev.text)
                if size >= MAX_SUMMARY_CHARS:  # enough: stop the model instead of letting it run on
                    break
            elif isinstance(ev, StepEnd):
                end = ev
    finally:
        await stream.aclose()  # closes the request, so a local server stops generating
    summary = (end.text if end else "".join(out)).strip()
    if not summary:
        raise ProviderError("The model returned an empty summary")
    return summary


async def compact(provider: Provider, convo: list[Message], current: int, limit: int) -> int:
    """Summarize everything except the user's current request and the latest steps (in place). Returns how many
    messages the summary replaced (0 if there was nothing to fold)."""
    tail = _tail_start(convo, current + 1)
    before, request, middle = convo[:current], convo[current], convo[current + 1:tail]
    folded = before + middle
    if len(folded) < 2:
        return 0
    try:
        summary = await summarize(provider, folded, limit)
    except ProviderError as exc:
        events.log("warn", "agent", f"Context compaction failed: {exc}")
        return 0
    head: list[Message] = [request, Message("user", f"{_PROGRESS_HEAD}\n{summary}")] if middle else \
        [Message("user", f"{SUMMARY_HEAD}\n{summary}"), request]
    if middle and before:  # both earlier turns and this turn's steps were folded: say so once
        head[1].content = f"{_PROGRESS_HEAD}\n(Covers the earlier conversation too.)\n{summary}"
    convo[:tail] = head
    return len(folded)


async def compact_history(provider: Provider, session_id: str, system: str, specs: list[ToolSpec] | None,
                          convo: list[Message], budget: Budget) -> str | None:
    """At the start of a turn (``convo`` = earlier turns + the new user message, last): when earlier turns take
    more than ``HISTORY_AT`` of the window, summarize all but the last exchange and save the summary on the session
    (``history.load`` then starts from it)."""
    if not budget.limit or budget.estimate(system, specs, convo) <= HISTORY_AT * budget.limit:
        return None
    rows = db.list_message_steps(session_id)
    user_rows = [r for r in rows if r.role == "user"]
    if len(user_rows) < 3:  # current message + fewer than 2 earlier exchanges: nothing worth folding
        return None
    keep_from = user_rows[-2].seq  # the previous exchange and the new message stay verbatim
    existing = db.get_summary(session_id)
    start = existing[1] if existing else 0
    earlier = [r for r in rows if start < r.seq < keep_from]
    if not earlier:
        return None
    from .history import step_messages  # the same messages the model saw, for the summarizer

    folded: list[Message] = [Message("user", f"{SUMMARY_HEAD}\n{existing[0]}")] if existing else []
    for r in earlier:
        folded.extend([Message("user", r.content)] if r.role == "user" else
                      [m for s in (r.steps or [{"text": r.content, "calls": []}]) for m in step_messages(s)])
    try:
        summary = await summarize(provider, folded, budget.limit)
    except ProviderError as exc:
        events.log("warn", "agent", f"History compaction failed: {exc}")
        return None
    db.set_summary(session_id, summary, earlier[-1].seq)
    from .history import load

    convo[:] = load(session_id)
    return (f"Summarized {len(earlier)} earlier messages of this chat to stay within the "
            f"{format_tokens(budget.limit)} context")

