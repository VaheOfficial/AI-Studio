"""Pronunciation dictionary: respelling entries (global ``*`` or per language) plus inline
``[[term|replacement]]`` one-off overrides.

Matching is ported from VoiceStudio ``backend/services/pronunciation.py``: whole-word, case-insensitive,
longest term first, one ``re.sub`` pass (a respelling is never rescanned). ReDoS-safe: the pattern is a
literal alternation of ``re.escape``'d terms with word boundaries only where a term edge is a word char.
"""

from __future__ import annotations

import re
import uuid

from .. import db
from ..schemas_voice import (
    PronunciationEntry,
    PronunciationHit,
    PronunciationInput,
    PronunciationPatch,
    PronunciationTestResult,
)
from . import languages, normalize

ALL_LANGUAGES = "*"


class PronunciationError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ------------------------------- matching -------------------------------


def _boundary(edge: str) -> str:
    return r"\b" if edge.isalnum() or edge == "_" else ""


def _lexicon_for(entries: list[PronunciationEntry], language: str | None) -> dict[str, str]:
    """Enabled rows for ``language``; a language row overrides a global row with the same term."""
    glob: dict[str, str] = {}
    lang: dict[str, str] = {}
    for e in entries:
        if not e.enabled or not e.term.strip():
            continue
        if e.language == ALL_LANGUAGES:
            glob[e.term.strip()] = e.replacement
        elif language and e.language == language:
            lang[e.term.strip()] = e.replacement
    return glob | lang


def apply_lexicon(text: str, lexicon: dict[str, str]) -> tuple[str, list[PronunciationHit]]:
    keys = sorted(lexicon, key=len, reverse=True)
    if not text or not keys:
        return text, []
    lookup = {k.casefold(): lexicon[k] for k in keys}
    pattern = re.compile("(?:" + "|".join(f"{_boundary(k[:1])}{re.escape(k)}{_boundary(k[-1:])}" for k in keys) + ")",
                         re.IGNORECASE)
    hits: dict[str, PronunciationHit] = {}

    def repl(m: re.Match[str]) -> str:
        replacement = lookup.get(m.group(0).casefold(), m.group(0))
        hits.setdefault(m.group(0).casefold(), PronunciationHit(term=m.group(0), replacement=replacement))
        return replacement

    return pattern.sub(repl, text), list(hits.values())


# Bounded inner repetition keeps the scan linear on a run of "[" with no closing "]]".
_INLINE_RE = re.compile(r"\[\[([^\]]{0,256})\]\]")


def apply_inline_overrides(text: str) -> tuple[str, list[PronunciationHit]]:
    """``[[term|replacement]]`` -> replacement; ``[[replacement]]`` -> replacement (brackets stripped)."""
    if "[[" not in text:
        return text, []
    hits: list[PronunciationHit] = []

    def repl(m: re.Match[str]) -> str:
        term, sep, replacement = m.group(1).partition("|")
        spoken = replacement if sep else term
        hits.append(PronunciationHit(term=term if sep else m.group(0), replacement=spoken))
        return spoken

    return _INLINE_RE.sub(repl, text), hits


def prepare(text: str, language: str | None) -> tuple[str, list[PronunciationHit]]:
    """Text as the engine should see it: normalization, then the dictionary, then inline overrides."""
    out = normalize.normalize_for_tts(text, language)
    out, dict_hits = apply_lexicon(out, _lexicon_for(list_entries(), language))
    out, inline_hits = apply_inline_overrides(out)
    return out, dict_hits + inline_hits


def test(text: str, language: str | None) -> PronunciationTestResult:
    spoken, hits = prepare(text, language)
    return PronunciationTestResult(spoken=spoken, hits=hits)


# --------------------------------- CRUD ---------------------------------


def _row(r: object) -> PronunciationEntry:
    return PronunciationEntry(id=r["id"], term=r["term"], replacement=r["replacement"],  # type: ignore[index]
                              language=r["language"], enabled=bool(r["enabled"]),  # type: ignore[index]
                              created_at=r["created_at"])  # type: ignore[index]


def list_entries() -> list[PronunciationEntry]:
    return [_row(r) for r in db.query("SELECT * FROM pronunciation ORDER BY created_at")]


def _get(entry_id: str) -> PronunciationEntry:
    r = db.query_one("SELECT * FROM pronunciation WHERE id = ?", (entry_id,))
    if r is None:
        raise PronunciationError(f"Pronunciation entry '{entry_id}' not found", 404)
    return _row(r)


def _check_language(language: str) -> None:
    if language != ALL_LANGUAGES and not languages.is_known(language):
        raise PronunciationError(f"Unknown language '{language}'")


def create(body: PronunciationInput) -> PronunciationEntry:
    _check_language(body.language)
    entry = PronunciationEntry(id=uuid.uuid4().hex[:12], term=body.term.strip(), replacement=body.replacement,
                               language=body.language, enabled=body.enabled, created_at=db.now_iso())
    db.execute("INSERT INTO pronunciation(id, term, replacement, language, enabled, created_at) VALUES(?,?,?,?,?,?)",
               (entry.id, entry.term, entry.replacement, entry.language, int(entry.enabled), entry.created_at))
    return entry


def update(entry_id: str, patch: PronunciationPatch) -> PronunciationEntry:
    entry = _get(entry_id)
    changes = patch.model_dump(exclude_none=True)
    if "language" in changes:
        _check_language(changes["language"])
    if "term" in changes:
        changes["term"] = changes["term"].strip()
    entry = entry.model_copy(update=changes)
    db.execute("UPDATE pronunciation SET term = ?, replacement = ?, language = ?, enabled = ? WHERE id = ?",
               (entry.term, entry.replacement, entry.language, int(entry.enabled), entry.id))
    return entry


def delete(entry_id: str) -> None:
    _get(entry_id)
    db.execute("DELETE FROM pronunciation WHERE id = ?", (entry_id,))
