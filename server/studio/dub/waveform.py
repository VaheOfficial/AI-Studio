"""Timeline waveform (``waveform.json``): speech-stem peaks at a fixed rate — fine enough to see the gaps between
words on a zoomed timeline — plus the worker's speech onsets."""

from __future__ import annotations

import json
from array import array
from pathlib import Path
from typing import Any

from .. import media
from . import store

PEAKS_PER_S = 50  # one bar per 20 ms
_RATE = 8000


def speech_audio(p: dict[str, Any]) -> Path:
    """The audio the timeline shows: separated vocals when available, else the full mix."""
    d = store.project_dir(p["id"])
    return d / p["separation"]["vocals"] if p.get("separation") else d / "audio16k.wav"


def peaks(audio: Path) -> list[float]:
    """Normalised 0..1 peak per 20 ms."""
    samples = array("h")
    samples.frombytes(media.pcm16(audio, _RATE))
    step = _RATE // PEAKS_PER_S
    raw = [max(max(c), -min(c)) for c in (samples[i:i + step] for i in range(0, len(samples), step))]
    top = max(raw, default=0) or 1
    return [round(v / top, 3) for v in raw]


def write(p: dict[str, Any], onsets: list[float], duration: float) -> None:
    path = store.project_dir(p["id"]) / "waveform.json"
    path.write_text(json.dumps({"peaks": peaks(speech_audio(p)), "onsets": onsets, "duration": duration}),
                    encoding="utf-8")


def load(p: dict[str, Any]) -> dict[str, Any] | None:
    """The stored waveform; one saved at the old fixed resolution (1200 bars) is upgraded on first read."""
    path = store.project_dir(p["id"]) / "waveform.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if len(data["peaks"]) < data["duration"] * PEAKS_PER_S * 0.9 and speech_audio(p).is_file():
        write(p, data["onsets"], data["duration"])
        data = json.loads(path.read_text(encoding="utf-8"))
    return data
