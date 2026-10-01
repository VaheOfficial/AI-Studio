"""SQLite tables for voice profiles, takes and the pronunciation dictionary (created by ``init``)."""

from __future__ import annotations

from .. import db

_TABLES = (
    """CREATE TABLE IF NOT EXISTS voice_profiles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        language TEXT,
        tags TEXT NOT NULL DEFAULT '[]',
        ref_audio TEXT,
        ref_text TEXT,
        instruct TEXT,
        vd_states TEXT,
        seed INTEGER,
        is_locked INTEGER NOT NULL DEFAULT 0,
        locked_audio TEXT,
        locked_text TEXT,
        archetype_id TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS voice_takes (
        id TEXT PRIMARY KEY REFERENCES outputs(id) ON DELETE CASCADE,
        engine TEXT NOT NULL,
        language TEXT,
        instruct TEXT,
        profile_id TEXT,
        profile_name TEXT,
        seed INTEGER,
        gen_time_s REAL NOT NULL,
        starred INTEGER NOT NULL DEFAULT 0,
        spoken_text TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS pronunciation (
        id TEXT PRIMARY KEY,
        term TEXT NOT NULL,
        replacement TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT '*',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
)


def init() -> None:
    for sql in _TABLES:
        db.execute(sql)
    _migrate_legacy_voices()


def _migrate_legacy_voices() -> None:
    """Earlier builds kept Chatterbox clones in a ``voices`` table; they become clone profiles
    (their reference WAV stays where it is; the transcript is filled on first use)."""
    if db.query_one("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'voices'") is None:
        return
    db.execute(
        """INSERT OR IGNORE INTO voice_profiles(id, name, kind, language, tags, ref_audio, created_at)
           SELECT id, name, 'clone', NULL, tags, sample_path, created_at FROM voices WHERE sample_path IS NOT NULL"""
    )
    db.execute("DROP TABLE voices")
