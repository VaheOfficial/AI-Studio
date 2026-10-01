"""Subtitle parsing and writing (ported from VoiceStudio ``services/srt_parser.py`` and the SRT/VTT writers in
``api/routers/dub_export.py``). Lenient reader: BOM, CRLF, ``.`` or ``,`` milliseconds, missing indices, optional
hours, WebVTT NOTE/STYLE/REGION blocks and player markup; overlapping cues are pushed back, not dropped."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_TS = r"(?:(\d{1,2}):)?([0-5]?\d):([0-5]?\d)[,.](\d{1,3})"
_H = r"[^\S\n]*"  # horizontal whitespace only (plain \s made the scan quadratic on blank-line floods)
_TIMING_RE = re.compile(rf"^{_H}{_TS}{_H}-->{_H}{_TS}.*$", re.MULTILINE)
_WEBVTT_TAG_RE = re.compile(r"<[^<>\n]*>")
_SRT_MARKUP_RE = re.compile(
    r"</?(?:[biu]|c|ruby|rt)(?:\.[^\s.<>]+)*>"
    r"|<(?:v|lang)(?:\.[^\s.<>]+)*[ \t][^<>\n]*>|</(?:v|lang)>"
    r"|<font[ \t][^<>\n]*>|</?font>"
    r"|<(?:\d+:)?\d{2}:\d{2}\.\d{3}>",
    re.IGNORECASE,
)
_ASS_OVERRIDE_RE = re.compile(r"\{\\[^{}\n]*\}")
_LINE_BREAK_RE = re.compile(r"<br[ \t]*/?>", re.IGNORECASE)
_BARE_AMPERSAND_RE = re.compile(r"&(?!#\d+;|#[xX][0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]*;)")


@dataclass
class ParseResult:
    cues: list[dict]  # {start, end, text}
    skipped: int
    dropped: int


def _seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int((ms + "000")[:3]) / 1000.0


def spoken_text(text: str, *, webvtt: bool) -> str:
    """The words a cue speaks: player tags and ASS overrides removed; ``<br>`` separates words."""
    out = _LINE_BREAK_RE.sub(" ", _ASS_OVERRIDE_RE.sub("", text))
    out = (_WEBVTT_TAG_RE if webvtt else _SRT_MARKUP_RE).sub("", out)
    if webvtt:
        out = html.unescape(out)
    return " ".join(line.strip() for line in out.split("\n") if line.strip())


def parse(content: str) -> ParseResult:
    if not content:
        return ParseResult([], 0, 0)
    text = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    webvtt = bool(re.match(r"WEBVTT(?:[ \t]|\n|$)", text.lstrip()))
    if webvtt:
        blocks = []
        for block in re.split(r"\n[^\S\n]*\n", text):
            lines = block.strip().split("\n")
            first = lines[0].strip()
            is_cue = len(lines) > 1 and _TIMING_RE.match(lines[1])
            if (first in {"STYLE", "REGION"} or re.match(r"NOTE(?:[ \t]|$)", first)) and not is_cue:
                continue
            blocks.append(block)
        text = "\n\n".join(blocks)
    raw: list[dict] = []
    skipped = 0
    matches = list(_TIMING_RE.finditer(text))
    for i, m in enumerate(matches):
        body = text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        if webvtt:
            body = re.split(r"\n[^\S\n]*\n", body, maxsplit=1)[0]
        else:
            lines = body.rstrip("\n").split("\n")
            if i + 1 < len(matches) and lines and lines[-1].strip().isascii() and lines[-1].strip().isdigit():
                lines = lines[:-1]  # the next cue's index number
            body = "\n".join(lines)
        start = _seconds(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _seconds(m.group(5), m.group(6), m.group(7), m.group(8))
        cue_text = spoken_text(body.strip("\n"), webvtt=webvtt)
        if end <= start or not cue_text:
            skipped += 1
            continue
        raw.append({"start": start, "end": end, "text": cue_text})
    raw.sort(key=lambda r: r["start"])
    cues, dropped, last_end = [], 0, 0.0
    for r in raw:
        s = max(r["start"], last_end)
        if r["end"] <= s:
            dropped += 1
            continue
        cues.append({"start": round(s, 3), "end": round(r["end"], 3), "text": r["text"]})
        last_end = r["end"]
    return ParseResult(cues, skipped, dropped)


def timestamp(seconds: float, sep: str) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def escape_webvtt(text: str) -> str:
    return _BARE_AMPERSAND_RE.sub("&amp;", text).replace("<", "&lt;").replace("-->", "--&gt;")


def _cue_text(cue: dict, dual: bool, escape) -> str:
    """Dual layout stacks the translation over the italicised original (Netflix / language-learning style)."""
    text = (cue.get("text") or "").strip()
    original = (cue.get("original") or "").strip()
    if not dual or not original or original == text:
        return escape(text or original)
    return f"{escape(text)}\n<i>{escape(original)}</i>"


def to_srt(cues: list[dict], *, dual: bool = False) -> str:
    lines: list[str] = []
    for i, cue in enumerate(cues):
        lines += [str(i + 1), f"{timestamp(cue['start'], ',')} --> {timestamp(cue['end'], ',')}",
                  _cue_text(cue, dual, lambda t: t), ""]
    return "\n".join(lines)


def to_vtt(cues: list[dict], *, dual: bool = False) -> str:
    lines = ["WEBVTT", ""]
    for i, cue in enumerate(cues):
        lines += [str(i + 1), f"{timestamp(cue['start'], '.')} --> {timestamp(cue['end'], '.')}",
                  _cue_text(cue, dual, escape_webvtt), ""]
    return "\n".join(lines)
