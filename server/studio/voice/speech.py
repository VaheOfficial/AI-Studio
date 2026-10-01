"""Speech jobs for every TTS engine (OmniVoice, Kokoro, Chatterbox; OpenRouter cloud models are delegated).

Text goes through normalization + the pronunciation dictionary first; each local render is recorded as
a take. OmniVoice keeps ``[pause]`` markers and non-verbal tags (the worker handles them); the other
engines would read them aloud, so they are removed for those.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .. import db, openrouter_media
from ..generation import _call_worker, _load, _new_output_path
from ..jobs import JobContext, JobError, jobs
from ..models import ModelError, models
from ..schemas import InstalledModel, Job, JobResult, Output, TTSRequest
from ..schemas_voice import SpeakRequest
from . import profiles, pronunciation, takes
from .profiles import Conditioning, VoiceError

_MARKUP_RE = re.compile(
    r"\[\s*(?:pause[^\]]*|laughter|sigh|confirmation-en|question-\w+|surprise-\w+|dissatisfaction-\w+)\]",
    re.IGNORECASE)
_OMNI_FIELDS = ("duration", "num_step", "guidance_scale", "t_shift", "position_temperature", "class_temperature",
                "denoise", "postprocess_output")


def default_omnivoice() -> InstalledModel:
    m = next((x for x in db.list_installed() if x.runtime == "omnivoice"), None)
    if m is None:
        raise VoiceError("OmniVoice is not installed. Install it from Models → Catalog (Voice).", 409)
    return m


def tts(req: TTSRequest) -> Job:
    """Start a speech job. Accepts a plain ``TTSRequest`` (agent tools) or a ``SpeakRequest``."""
    speak = req if isinstance(req, SpeakRequest) else SpeakRequest.model_validate(req.model_dump())
    m = models.get(speak.model_id)
    if m.kind != "voice":
        raise ModelError(f"{m.name} is a {m.kind} model, not a voice model", 400)
    if m.runtime == "openrouter":
        return openrouter_media.tts(m, speak)
    cond = profiles.resolve(m, speak)
    return jobs.submit("generate", f"Speech · {speak.text[:48]}", lambda ctx: _job(ctx, m, speak, cond), ref=m.id)


def _payload(m: InstalledModel, req: SpeakRequest, cond: Conditioning, text: str, out: Path) -> dict[str, Any]:
    if m.runtime == "omnivoice":
        return {"text": text, "language": cond.language, "ref_audio": cond.ref_audio, "ref_text": cond.ref_text,
                "instruct": cond.instruct, "speed": req.speed, "seed": cond.seed, "out_path": str(out),
                **req.model_dump(include=set(_OMNI_FIELDS), exclude_none=True)}
    plain = " ".join(_MARKUP_RE.sub(" ", text).split())
    if not plain:
        raise JobError("Nothing to speak once pause markers and reaction tags are removed")
    if m.runtime == "kokoro":
        return {"text": plain, "speed": req.speed, "voice_path": cond.kokoro_voice, "lang_code": cond.kokoro_lang,
                "out_path": str(out)}
    return {"text": plain, "speed": req.speed, "reference_wav": cond.ref_audio, "exaggeration": req.exaggeration,
            "cfg_weight": req.cfg_weight, "out_path": str(out)}


def synthesize(ctx: JobContext, m: InstalledModel, req: SpeakRequest, cond: Conditioning,
               out: Path) -> tuple[dict[str, Any], Conditioning, str, float]:
    """Blocking: prepare the text, load the model, render to ``out``.
    Returns (worker result, final conditioning, text the engine spoke, seconds of synthesis)."""
    if m.runtime == "omnivoice" and cond.ref_audio and not cond.ref_text:
        ctx.update(message="Transcribing the voice reference…")
        try:
            cond = profiles.ensure_ref_text(cond)
        except VoiceError as exc:
            raise JobError(str(exc)) from exc
    prepared, _hits = pronunciation.prepare(req.text, cond.language)
    _load(ctx, m)
    payload = _payload(m, req, cond, prepared, out)
    started = time.monotonic()
    result = _call_worker(ctx, m.runtime, "/tts", payload, "Synthesizing")
    return result, cond, payload["text"], time.monotonic() - started


def render(ctx: JobContext, m: InstalledModel, req: SpeakRequest, cond: Conditioning) -> Output:
    """Synthesize into a new audio output and record it as a take."""
    oid, path, url = _new_output_path("audio", "wav")
    result, cond, spoken, gen_time = synthesize(ctx, m, req, cond, path)
    seed = result.get("seed")
    params = req.model_dump(exclude={"text", "model_id", "ref_id", "ref_text"}, exclude_none=True)
    if seed is not None:
        params["seed"] = seed
    out = Output(id=oid, kind="audio", url=url, model_id=m.id, prompt=req.text, params=params,
                 created_at=db.now_iso(), duration_s=round(float(result["duration_s"]), 3))
    db.insert_output(out, str(path))
    takes.record(out, engine=m.runtime, language=cond.language, instruct=cond.instruct, profile_id=cond.profile_id,
                 profile_name=cond.profile_name, seed=seed, gen_time_s=gen_time, spoken=spoken)
    return out


def _job(ctx: JobContext, m: InstalledModel, req: SpeakRequest, cond: Conditioning) -> JobResult:
    return JobResult(outputs=[render(ctx, m, req, cond)])
