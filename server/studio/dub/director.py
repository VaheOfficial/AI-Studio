"""Per-line delivery directions (ported from VoiceStudio ``services/director.py``, heuristic parser).

"make it urgent and surprised" → taxonomy tokens used as a translation hint for the cinematic/adapt prompts
and as a speaking-rate bias for Lip-sync (strict slot) synthesis."""

from __future__ import annotations

import re

_KEYWORD_HINTS = {
    "urgent": ("energy", "urgent"), "urgency": ("energy", "urgent"), "rushed": ("pace", "rushed"),
    "quick": ("pace", "quick"), "fast": ("pace", "quick"), "slow": ("pace", "slow"),
    "surprised": ("emotion", "surprised"), "shocked": ("emotion", "surprised"), "angry": ("emotion", "angry"),
    "sad": ("emotion", "sad"), "happy": ("emotion", "happy"), "warm": ("emotion", "warm"),
    "cold": ("emotion", "cold"), "hopeful": ("emotion", "hopeful"), "whisper": ("intimacy", "whispered"),
    "whispered": ("intimacy", "whispered"), "intimate": ("intimacy", "intimate"),
    "announcing": ("intimacy", "announcing"), "announcer": ("intimacy", "announcing"),
    "casual": ("formality", "casual"), "formal": ("formality", "formal"), "calm": ("energy", "calm"),
    "energetic": ("energy", "energetic"),
}
_ORDER = ("emotion", "energy", "pace", "intimacy", "formality")


def parse(text: str | None) -> dict[str, list[str]]:
    tokens: dict[str, list[str]] = {}
    lower = (text or "").lower()
    for kw, (dim, val) in _KEYWORD_HINTS.items():
        if re.search(rf"\b{re.escape(kw)}\b", lower) and val not in tokens.setdefault(dim, []):
            tokens[dim].append(val)
    return {k: v for k, v in tokens.items() if v}


def translate_hint(text: str | None) -> str:
    tokens = parse(text)
    terms = [v for dim in _ORDER for v in tokens.get(dim, [])]
    return f"Deliver this with a {', '.join(dict.fromkeys(terms))} tone." if terms else ""


def rate_bias(text: str | None) -> float:
    """>1 speaks faster (urgent/rushed), <1 slower (calm/slow)."""
    tokens = parse(text)
    energy, pace = set(tokens.get("energy", [])), set(tokens.get("pace", []))
    if energy & {"urgent", "frantic"} or pace & {"rushed", "quick"}:
        return 1.1
    if energy & {"calm", "relaxed"} or "slow" in pace:
        return 0.92
    return 1.0
