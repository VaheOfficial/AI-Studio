"""Audio tools: isolate stems, convert a recording to another voice (see ``docs/api/dub.md``)."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile

from .. import audio_tools, config
from ..schemas import Job
from . import StudioRouter

router = StudioRouter(prefix="/api")


async def _save(upload: UploadFile) -> Path:
    dest = config.UPLOADS_DIR / f"{uuid.uuid4().hex}{Path(upload.filename or '').suffix.lower() or '.bin'}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        await asyncio.to_thread(shutil.copyfileobj, upload.file, f)
    return dest


@router.post("/audio-tools/isolate", response_model=Job)
async def isolate(file: UploadFile = File(...), mode: str = Form("vocals")) -> Job:
    if mode not in audio_tools.ISOLATE_MODES:
        raise HTTPException(400, f"mode must be one of {', '.join(audio_tools.ISOLATE_MODES)}")
    return audio_tools.isolate(await _save(file), file.filename or "audio", mode)


@router.post("/audio-tools/convert", response_model=Job)
async def convert(file: UploadFile = File(...), voice_id: str = Form(...), stt_model_id: str = Form(...),
                  tts_model_id: str | None = Form(None), language: str | None = Form(None),
                  match_duration: bool = Form(True)) -> Job:
    return audio_tools.convert(await _save(file), file.filename or "audio", voice_id, tts_model_id or None,
                               stt_model_id, language or None, match_duration)
