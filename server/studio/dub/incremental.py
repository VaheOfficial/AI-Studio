"""Incremental re-dub fingerprints (ported from VoiceStudio ``services/incremental.py``).

A segment's rendered audio is reused while the hash of its *generation inputs* is unchanged; timing edits and
fit settings never force a re-synthesis (they only re-mix)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canon(value: Any) -> Any:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def fingerprint(inputs: dict[str, Any], *, lang: str, voice_match: str) -> str:
    """``inputs``: text, voice binding, instruct, speed, direction, engine settings — everything that changes
    the synthesized audio. The track language and a non-default voice-match mode are part of the key so audio
    of one track/mode never vouches for another."""
    payload = {k: _canon(v) for k, v in sorted(inputs.items())}
    payload["track_lang"] = lang
    if voice_match != "per_line":
        payload["voice_match"] = voice_match
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
