"""Helpers for turning CLI output into text fit for job messages shown in the UI."""

from __future__ import annotations

import re

# CSI sequences (colors, cursor moves, line clears like "\x1b[K" and "\x1b[?25l")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Braille spinner frames used by the Ollama CLI
_SPINNER = re.compile(r"[⠀-⣿]")


def clean_line(raw: str) -> str:
    """Latest frame of a redrawn terminal line, without escape codes or spinner glyphs."""
    frames = [f for f in (" ".join(_SPINNER.sub("", _ANSI.sub("", part)).split()) for part in raw.split("\r")) if f]
    return frames[-1] if frames else ""
