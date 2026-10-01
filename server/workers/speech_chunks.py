"""Long-text chunking and crossfade joining for TTS workers.

Ported from VoiceStudio ``backend/services/chunked_tts.py`` (itself adapted from voicebox,
https://github.com/jamiepine/voicebox, MIT License, Copyright (c) voicebox contributors), working
on numpy arrays instead of torch tensors. Pure functions, stdlib + numpy only.
"""

from __future__ import annotations

import re

import numpy as np

DEFAULT_MAX_CHUNK_CHARS = 800
DEFAULT_CROSSFADE_MS = 50

_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "ave", "blvd",
    "inc", "ltd", "corp", "dept", "est", "approx", "vs", "etc",
    "e.g", "i.e", "a.m", "p.m", "u.s", "u.s.a", "u.k",
})

# Inline bracket tags ([laughter], [pause 300ms]): the splitter never cuts inside one.
_BRACKET_TAG_RE = re.compile(r"\[[^\]]*\]")
# Any letter or digit in any script — punctuation alone is not speech.
_SPEAKABLE_RE = re.compile(r"[^\W_]", re.UNICODE)

# Dense scripts (CJK, kana, Hangul): ~1 char = 1 syllable, so chunks get a smaller char budget.
_DENSE_FRACTION_THRESHOLD = 0.3
_DENSE_SPEECH_FACTOR = 2.5


def _dense_char_count(text: str) -> int:
    n = 0
    for ch in text:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
                or 0xAC00 <= o <= 0xD7AF or 0xF900 <= o <= 0xFAFF):
            n += 1
    return n


def _effective_max_chars(text: str, max_chars: int) -> int:
    if max_chars <= 0 or not text:
        return max_chars
    dense = _dense_char_count(text)
    if dense and dense / len(text) >= _DENSE_FRACTION_THRESHOLD:
        return max(120, min(max_chars, round(max_chars / _DENSE_SPEECH_FACTOR)))
    return max_chars


def split_text_into_chunks(text: str, max_chars: int = DEFAULT_MAX_CHUNK_CHARS) -> list[str]:
    """Split at natural boundaries into chunks of at most ``max_chars``.

    Priority: sentence end (not after an abbreviation/decimal, not inside a ``[tag]``, plus
    fullwidth enders) -> clause boundary -> whitespace -> hard cut that avoids splitting a tag.
    """
    text = text.strip()
    if not text:
        return []
    max_chars = _effective_max_chars(text, max_chars)
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        remaining = remaining.lstrip()
        if not remaining:
            break
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        segment = remaining[:max_chars]
        split_pos = _find_last_sentence_end(segment)
        if split_pos == -1:
            split_pos = _find_last_clause_boundary(segment)
        if split_pos == -1:
            split_pos = segment.rfind(" ")
        if split_pos == -1:
            split_pos = _safe_hard_cut(segment, max_chars)
        chunk = remaining[: split_pos + 1].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos + 1:]
    return _merge_unspeakable(chunks, max_chars)


def _merge_unspeakable(chunks: list[str], max_chars: int) -> list[str]:
    """Fold punctuation-only chunks into a neighbour so no chunk renders silence."""
    if len(chunks) < 2:
        return chunks
    out: list[str] = []
    for chunk in chunks:
        if _SPEAKABLE_RE.search(chunk) or not out:
            out.append(chunk)
            continue
        merged = f"{out[-1]} {chunk}"
        if len(merged) <= max_chars:
            out[-1] = merged
            continue
        head, sep, last_word = out[-1].rpartition(" ")
        if sep and head and _SPEAKABLE_RE.search(last_word):
            out[-1] = head
            out.append(f"{last_word} {chunk}")
        else:
            out[-1] = merged
    if len(out) > 1 and not _SPEAKABLE_RE.search(out[0]):
        merged = f"{out[0]} {out[1]}"
        if len(merged) <= max_chars:
            out[1] = merged
            out.pop(0)
        else:
            first_word, sep, tail = out[1].partition(" ")
            if sep and tail and _SPEAKABLE_RE.search(first_word):
                out[0] = f"{out[0]} {first_word}"
                out[1] = tail
            else:
                out[1] = merged
                out.pop(0)
    return out


def _find_last_sentence_end(text: str) -> int:
    best = -1
    for m in re.finditer(r"[.!?](?:\s|$)", text):
        pos = m.start()
        if text[pos] == ".":
            word_start = pos - 1
            while word_start >= 0 and text[word_start].isalpha():
                word_start -= 1
            word = text[word_start + 1: pos].lower()
            if word in _ABBREVIATIONS:
                continue
            if word_start >= 0 and text[word_start].isdigit():
                continue
        if _inside_bracket_tag(text, pos):
            continue
        best = pos
    for m in re.finditer("[。！？]", text):  # ideographic full stop, fullwidth ! ?
        if m.start() > best:
            best = m.start()
    return best


def _find_last_clause_boundary(text: str) -> int:
    best = -1
    for m in re.finditer(r"[;:,—](?:\s|$)", text):
        if not _inside_bracket_tag(text, m.start()):
            best = m.start()
    return best


def _inside_bracket_tag(text: str, pos: int) -> bool:
    return any(m.start() < pos < m.end() for m in _BRACKET_TAG_RE.finditer(text))


def _safe_hard_cut(segment: str, max_chars: int) -> int:
    cut = max_chars - 1
    for m in _BRACKET_TAG_RE.finditer(segment):
        if m.start() < cut < m.end():
            return m.start() - 1 if m.start() > 0 else cut
    return cut


def concatenate(chunks: list[np.ndarray], sample_rate: int, crossfade_ms: int = DEFAULT_CROSSFADE_MS) -> np.ndarray:
    """Join 1-D waveforms with a linear crossfade (clamped to the shorter neighbour)."""
    kept = [c for c in chunks if c.size]
    if not kept:
        return np.zeros(0, dtype=np.float32)
    fade = int(sample_rate * crossfade_ms / 1000)
    out = kept[0].astype(np.float32, copy=True)
    for chunk in kept[1:]:
        overlap = max(0, min(fade, out.size, chunk.size))
        if overlap:
            ramp = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
            out[-overlap:] = out[-overlap:] * (1.0 - ramp) + chunk[:overlap] * ramp
        out = np.concatenate([out, chunk[overlap:].astype(np.float32, copy=False)])
    return out
