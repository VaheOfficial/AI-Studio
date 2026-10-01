"""Audiobook script grammar (ported from VoiceStudio ``services/longform_parser.py``, ``services/ssml_lite.py`` and
OmniVoice's ``parse_pause_markers``). Precedence (outer→inner): ``# chapter`` → ``[voice:NAME]`` → ``[pause]`` →
``[slow]/[fast]/[emphasis]`` → ``[spell]``.

    # Chapter One
    [voice:Narrator] The door creaked open. [pause 700ms] [voice:Mara] Who's there? [slow]Slowly now.[/slow]
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^[ \t]*#[ \t]+(\S.*)$", re.MULTILINE)
_VOICE_RE = re.compile(r"\[voice:([^\]\[]*)\]")
_BLANK_LINE_RE = re.compile(r"\n[ \t\r]*\n")
_PAUSE_RE = re.compile(r"\[\s*pause(?>\s+(\d+(?:\.\d+)?)\s*(ms|s)?)?\s*\]", re.IGNORECASE)
PAUSE_DEFAULT_MS = 350
PAUSE_MAX_MS = 10_000

SLOW_SPEED, FAST_SPEED, EMPHASIS_SPEED = 0.85, 1.15, 0.92
_TAGS = {
    "slow": {"speed": SLOW_SPEED, "spell": None},
    "fast": {"speed": FAST_SPEED, "spell": None},
    "emphasis": {"speed": EMPHASIS_SPEED, "spell": None},
    "spell": {"speed": None, "spell": True},
}
_TAG_RE = re.compile(r"\[(/?)(" + "|".join(_TAGS) + r")\]", re.IGNORECASE)


@dataclass
class Span:
    voice: str | None
    text: str
    pause_ms_after: int = 0
    speed: float | None = None
    #: How this span joins the next when inline markup split one line: "continue" (no gap) or "paragraph".
    join: str | None = None


@dataclass
class Chapter:
    title: str
    spans: list[Span]


def _pause_ms(num: str | None, unit: str | None) -> int:
    if num is None:
        return PAUSE_DEFAULT_MS
    ms = float(num) * 1000.0 if unit and unit.lower() == "s" else float(num)
    return max(0, min(int(round(ms)), PAUSE_MAX_MS))


def parse_pauses(text: str) -> list[tuple[str, int]]:
    """``[(span_text, pause_ms_after)]``; adjacent markers add up (clamped to 10 s)."""
    if not text or "[" not in text:
        return [(text, 0)]
    out: list[tuple[str, int]] = []
    last, pending = 0, ""
    for m in _PAUSE_RE.finditer(text):
        pending += text[last:m.start()]
        last = m.end()
        pause = _pause_ms(m.group(1), m.group(2))
        if pending == "" and out:
            out[-1] = (out[-1][0], min(out[-1][1] + pause, PAUSE_MAX_MS))
        else:
            out.append((pending, pause))
        pending = ""
    tail = pending + text[last:]
    if tail or not out:
        out.append((tail, 0))
    return out


def parse_prosody(text: str) -> list[dict]:
    """``[slow]/[fast]/[emphasis]/[spell]`` runs → ``[{text, speed, spell}]``; innermost tag wins, unclosed tags
    run to the end of the line, adjacent runs with identical prosody merge."""
    if not text:
        return []
    if "[" not in text:
        return [{"text": text, "speed": None, "spell": False}]
    segments: list[dict] = []
    stack: list[str] = []
    last = 0

    def emit(chunk: str) -> None:
        if not chunk:
            return
        speed, spell = None, False
        for name in stack:
            if _TAGS[name]["speed"] is not None:
                speed = _TAGS[name]["speed"]
            if _TAGS[name]["spell"] is not None:
                spell = True
        if segments and segments[-1]["speed"] == speed and segments[-1]["spell"] == spell:
            segments[-1]["text"] += chunk
        else:
            segments.append({"text": chunk, "speed": speed, "spell": spell})

    for m in _TAG_RE.finditer(text):
        emit(text[last:m.start()])
        last = m.end()
        name = m.group(2).lower()
        if m.group(1) == "/":
            for i in range(len(stack) - 1, -1, -1):
                if stack[i] == name:
                    del stack[i]
                    break
        else:
            stack.append(name)
    emit(text[last:])
    return segments


def _spell_out(word: str) -> str:
    return " ".join("".join(word.split()))


def _chapter_spans(body: str, default_voice: str | None) -> list[Span]:
    spans: list[Span] = []
    runs: list[tuple[str | None, str]] = []
    voice, last = default_voice, 0
    for m in _VOICE_RE.finditer(body):
        if m.start() > last:
            runs.append((voice, body[last:m.start()]))
        voice = m.group(1).strip() or default_voice
        last = m.end()
    runs.append((voice, body[last:]))
    for run_voice, run_text in runs:
        for span_text, pause_ms in parse_pauses(run_text):
            t = span_text.strip()
            if not t and pause_ms == 0:
                continue
            rendered: list[tuple[str, float | None, bool]] = []
            between = ""
            for seg in parse_prosody(t) if t else []:
                raw = seg["text"]
                st = (_spell_out(raw) if seg["spell"] else raw).strip()
                if not st:
                    between += raw
                    continue
                lead = raw[:len(raw) - len(raw.lstrip())]
                rendered.append((st, seg["speed"], bool(_BLANK_LINE_RE.search(between + lead))))
                between = raw[len(raw.rstrip()):]
            if not rendered:
                if pause_ms > 0:
                    spans.append(Span(run_voice, "", pause_ms))
                continue
            for j, (st, speed, _brk) in enumerate(rendered):
                span = Span(run_voice, st, pause_ms if j == len(rendered) - 1 else 0, speed)
                if j < len(rendered) - 1:
                    span.join = "paragraph" if rendered[j + 1][2] else "continue"
                spans.append(span)
    return spans


def parse(text: str | None, default_voice: str | None = None) -> list[Chapter]:
    """H1 lines open chapters (untitled bodies become "Chapter N"); each chapter resets the voice."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    matches = list(_HEADING_RE.finditer(text))
    raw: list[tuple[str | None, str]] = []
    if not matches:
        raw = [(None, text)]
    else:
        if text[:matches[0].start()].strip():
            raw.append((None, text[:matches[0].start()]))
        for i, m in enumerate(matches):
            raw.append((m.group(1).strip(), text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]))
    chapters: list[Chapter] = []
    for title, body in raw:
        spans = _chapter_spans(body, default_voice)
        if spans:
            chapters.append(Chapter(title or f"Chapter {len(chapters) + 1}", spans))
    return chapters


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _BLANK_LINE_RE.split(text) if p.strip()]
