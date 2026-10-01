"""Speech and transcription through OpenRouter for pinned cloud models — the same ``Job`` + ``Output``
flow (TTS) and direct ``TranscribeResult`` (STT) as local models, billed to the OpenRouter ledger."""

from __future__ import annotations

import uuid
from pathlib import Path

from . import config, db, openrouter, openrouter_catalog, openrouter_usage
from .jobs import JobContext, JobError, jobs
from .models import ModelError
from .openrouter import OpenRouterError
from .openrouter_catalog import CatalogError
from .schemas import InstalledModel, Job, JobResult, Output, TranscribeResult, TranscribeSegment, TTSRequest

_AUDIO_EXT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
              "audio/ogg": "ogg", "audio/flac": "flac", "audio/aac": "aac"}


def tts(m: InstalledModel, req: TTSRequest) -> Job:
    try:
        voice = openrouter_catalog.voice_name(m, req.voice_id)
    except CatalogError as exc:
        raise ModelError(str(exc), exc.status) from exc
    return jobs.submit("generate", f"Speech · {req.text[:48]}", lambda ctx: _tts_job(ctx, m, req, voice), ref=m.id)


def _tts_job(ctx: JobContext, m: InstalledModel, req: TTSRequest, voice: str | None) -> JobResult:
    model = openrouter_catalog.slug(m)
    ctx.update(message=f"Synthesizing on OpenRouter ({model})…")
    try:
        result = openrouter.speech(model, req.text, voice=voice, speed=req.speed if req.speed != 1.0 else None)
    except OpenRouterError as exc:
        raise JobError(str(exc)) from exc
    openrouter_usage.record_when_billed("speech", model, result.usage, ref=ctx.id)
    ctx.check_cancelled()
    oid = uuid.uuid4().hex[:16]
    ext = _AUDIO_EXT.get(result.media_type, "mp3")
    path = config.OUTPUTS_DIR / "audio" / f"{oid}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.audio)
    params = {"voice_id": req.voice_id, "speed": req.speed, "provider": "openrouter"}
    out = Output(id=oid, kind="audio", url=f"/files/outputs/audio/{oid}.{ext}", model_id=m.id, prompt=req.text,
                 params=params, created_at=db.now_iso())
    db.insert_output(out, str(path))
    return JobResult(outputs=[out])


def transcribe(m: InstalledModel, audio: Path, language: str | None) -> TranscribeResult:
    """Blocking; call from a thread."""
    model = openrouter_catalog.slug(m)
    try:
        t = openrouter.transcribe(model, audio.read_bytes(), audio.suffix.lstrip(".").lower() or "wav",
                                  language=language)
    except OpenRouterError as exc:
        raise ModelError(str(exc), exc.status if 400 <= exc.status < 600 else 502) from exc
    openrouter_usage.record("transcription", model, t.usage)
    segments = [TranscribeSegment(start=float(s.get("start") or 0), end=float(s.get("end") or 0),
                                  text=str(s.get("text") or "").strip()) for s in t.segments]
    if not segments and t.text:
        segments = [TranscribeSegment(start=0, end=t.duration_s or 0, text=t.text)]
    return TranscribeResult(text=t.text, language=t.language or "", segments=segments)
