"""Music generation, transcription and outputs (image routes: ``routes/image.py``, voice: ``routes/voice.py``)."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from fastapi import File, Form, HTTPException, Query, Response, UploadFile

from .. import config, db, generation
from ..models import ModelError
from ..runtimes import WorkerError
from ..schemas import Job, MusicRequest, Output, OutputKind, TranscribeResult
from . import StudioRouter

router = StudioRouter(prefix="/api")


def _model_http(exc: ModelError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.post("/music/generate", response_model=Job)
async def music_generate(req: MusicRequest) -> Job:
    try:
        return generation.generate_music(req)
    except ModelError as exc:
        raise _model_http(exc) from exc


async def save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower() or ".bin"
    dest = config.UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        await asyncio.to_thread(shutil.copyfileobj, upload.file, f)
    return dest


@router.post("/voice/transcribe", response_model=TranscribeResult)
async def voice_transcribe(file: UploadFile = File(...), model_id: str = Form(...),
                           language: str | None = Form(None)) -> TranscribeResult:
    path = await save_upload(file)
    try:
        return await asyncio.to_thread(generation.transcribe, model_id, path, language)
    except ModelError as exc:
        raise _model_http(exc) from exc
    except WorkerError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)


# -------------------------------- outputs --------------------------------


@router.get("/outputs", response_model=list[Output])
async def list_outputs(kind: OutputKind | None = None,
                       limit: int = Query(100, ge=1, le=1000)) -> list[Output]:
    return db.list_outputs(kind, limit)


@router.delete("/outputs/{output_id}", status_code=204)
async def delete_output(output_id: str) -> Response:
    path = db.get_output_path(output_id)
    if path is None:
        raise HTTPException(404, f"Output '{output_id}' not found")
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(500, f"Could not delete {path}: {exc}") from exc
    db.delete_output(output_id)
    return Response(status_code=204)
