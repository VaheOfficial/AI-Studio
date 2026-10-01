"""Speech synthesis for dubbing, audiobooks and voice conversion.

Targets the OmniVoice runtime contract (``/tts``: ``duration`` for slot fitting, ``ref_audio``/``ref_text``
cloning, ``instruct`` design tags, 600+ languages). Chatterbox (English-only zero-shot cloning) is accepted as
well. Voices resolve through the voice profiles (``voice.profiles.resolve``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import db
from ..jobs import JobContext, JobError
from ..models import ModelError, models
from ..runtimes import WorkerError, runtimes
from ..schemas import InstalledModel
from ..schemas_voice import AUTO_VOICE, SpeakRequest
from ..voice import languages, profiles
from . import worker

TTS_RUNTIMES = ("omnivoice", "chatterbox")


@dataclass(frozen=True)
class Voice:
    """A resolved reference: clone clip + transcript, design instruct and/or a pinned seed."""

    ref_audio: str | None = None
    ref_text: str | None = None
    instruct: str | None = None
    seed: int | None = None
    label: str = ""


def model(model_id: str | None) -> InstalledModel:
    installed = [m for m in db.list_installed() if m.runtime in TTS_RUNTIMES]
    m = next((x for x in installed if x.id == model_id), None) if model_id else None
    if m is None:
        m = next((x for x in installed if x.runtime == "omnivoice"), None) or (installed[0] if installed else None)
    if m is None:
        raise JobError("No speech model that can clone voices is installed. Install OmniVoice from Models.")
    return m


def check_language(m: InstalledModel, lang: str | None) -> None:
    if not languages.supports(m.runtime, lang):
        raise JobError(f"{m.name} cannot speak {languages.name_of(lang) or lang}. Use OmniVoice for other languages.")


def profile_voice(m: InstalledModel, voice_id: str, lang: str | None) -> Voice:
    """Resolve a saved voice profile ('' → the engine's default voice)."""
    if not voice_id:
        return Voice()
    try:
        cond = profiles.resolve(m, SpeakRequest(model_id=m.id, text=".", voice_id=voice_id or AUTO_VOICE,
                                                language=lang))
        cond = profiles.ensure_ref_text(cond)
    except profiles.VoiceError as exc:
        raise JobError(str(exc)) from exc
    return Voice(ref_audio=cond.ref_audio, ref_text=cond.ref_text, instruct=cond.instruct, seed=cond.seed,
                 label=cond.profile_name or voice_id)


def load(ctx: JobContext | None, m: InstalledModel) -> None:
    """Hand the GPU to the TTS model: drop dub stage models, then load through ``models`` (VRAM arbitration)."""
    if runtimes.loaded_model(m.runtime) == m.id:
        return
    worker.release_stage_models()
    if ctx:
        ctx.update(message=f"Loading {m.name}…")
    try:
        models.ensure_loaded(m.id)
    except ModelError as exc:
        raise JobError(str(exc)) from exc


@dataclass(frozen=True)
class Line:
    """One synthesis request."""

    text: str
    out_path: Path
    lang: str | None
    voice: Voice
    speed: float = 1.0
    duration: float | None = None
    num_step: int = 16
    guidance: float = 2.0
    instruct: str | None = None


def _payload(m: InstalledModel, line: Line) -> dict[str, object]:
    line.out_path.parent.mkdir(parents=True, exist_ok=True)
    if m.runtime == "omnivoice":
        payload = {"text": line.text, "language": line.lang or None, "ref_audio": line.voice.ref_audio,
                   "ref_text": line.voice.ref_text,
                   "instruct": ", ".join(filter(None, [line.voice.instruct, line.instruct])) or None,
                   "duration": line.duration, "speed": line.speed, "num_step": line.num_step,
                   "guidance_scale": line.guidance, "seed": line.voice.seed, "out_path": str(line.out_path)}
    else:
        payload = {"text": line.text, "speed": line.speed, "reference_wav": line.voice.ref_audio,
                   "out_path": str(line.out_path)}
    return {k: v for k, v in payload.items() if v is not None}


def synthesize(m: InstalledModel, line: Line) -> float:
    """Render one line (natural rate unless ``duration`` pins its length). Returns seconds."""
    try:
        result = runtimes.request(m.runtime, "POST", "/tts", _payload(m, line), timeout=1800)
    except WorkerError as exc:
        raise JobError(f"Speech synthesis failed: {exc}") from exc
    return float(result.get("duration_s") or 0.0)


BATCH = 16


def synthesize_many(m: InstalledModel, lines: list[Line], on_progress: Callable[[int], None],
                    check: Callable[[], None]) -> list[float]:
    """Render many lines: OmniVoice ``/tts_batch`` (native batches of short lines), one by one elsewhere."""
    durations: list[float] = []
    if m.runtime != "omnivoice":
        for line in lines:
            check()
            durations.append(synthesize(m, line))
            on_progress(len(durations))
        return durations
    for start in range(0, len(lines), BATCH):
        check()
        group = lines[start:start + BATCH]
        try:
            result = runtimes.request(m.runtime, "POST", "/tts_batch", {"items": [_payload(m, x) for x in group]},
                                      timeout=3600)
        except WorkerError as exc:
            raise JobError(f"Speech synthesis failed: {exc}") from exc
        durations += [float(r.get("duration_s") or 0.0) for r in result["items"]]
        on_progress(len(durations))
    return durations
