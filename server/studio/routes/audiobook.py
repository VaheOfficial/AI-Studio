"""Audiobook projects: script, cast, render (see ``docs/api/dub.md``)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import File, HTTPException, Response, UploadFile

from ..audiobook import importer, render, script, store
from ..schemas import Job
from ..schemas_dub import (AudiobookChapterPlan, AudiobookCreate, AudiobookImportResult, AudiobookPatch, AudiobookPlan,
                           AudiobookPlanRequest, AudiobookProject, AudiobookRenderRequest, AudiobookSummary)
from . import StudioRouter

router = StudioRouter(prefix="/api")
_COVER_TYPES = {".jpg", ".jpeg", ".png"}
_COVER_MAX = 8 * 1024 * 1024
_CPS = 15.0  # speaking-rate estimate for the runtime shown in the editor


def _project(pid: str) -> dict[str, Any]:
    try:
        return store.get(pid)
    except store.NotFound as exc:
        raise HTTPException(404, f"Audiobook '{pid}' not found") from exc


@router.get("/audiobook/projects", response_model=list[AudiobookSummary])
async def list_projects() -> list[AudiobookSummary]:
    return [store.to_summary(p) for p in store.all_projects()]


@router.post("/audiobook/projects", response_model=AudiobookProject)
async def create_project(body: AudiobookCreate) -> AudiobookProject:
    return store.to_api(store.create(body.name.strip() or "Untitled audiobook", body.script))


@router.get("/audiobook/projects/{pid}", response_model=AudiobookProject)
async def get_project(pid: str) -> AudiobookProject:
    return store.to_api(_project(pid))


@router.patch("/audiobook/projects/{pid}", response_model=AudiobookProject)
async def patch_project(pid: str, patch: AudiobookPatch) -> AudiobookProject:
    _project(pid)

    def apply(p: dict[str, Any]) -> None:
        if patch.name is not None:
            p["name"] = patch.name.strip() or p["name"]
        if patch.script is not None:
            p["script"] = patch.script
        if patch.settings is not None:
            p["settings"] = patch.settings.model_dump()

    return store.to_api(await asyncio.to_thread(store.update, pid, apply))


@router.delete("/audiobook/projects/{pid}", status_code=204)
async def delete_project(pid: str) -> Response:
    _project(pid)
    if render.jobs.find_active(lambda j: j.ref == render.ref(pid)):
        raise HTTPException(409, "A render is running for this audiobook — cancel it first")
    await asyncio.to_thread(store.delete, pid)
    return Response(status_code=204)


@router.post("/audiobook/import", response_model=AudiobookImportResult)
async def import_manuscript(file: UploadFile = File(...)) -> AudiobookImportResult:
    data = await file.read()
    try:
        text = await asyncio.to_thread(importer.import_file, file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return AudiobookImportResult(script=text, title=Path(file.filename or "").stem or None,
                                 chapters=len(script.parse(text)))


@router.post("/audiobook/plan", response_model=AudiobookPlan)
async def plan(req: AudiobookPlanRequest) -> AudiobookPlan:
    chapters = script.parse(req.script)
    out = []
    for c in chapters:
        text = " ".join(s.text for s in c.spans if s.text)
        pauses = sum(s.pause_ms_after for s in c.spans) / 1000
        out.append(AudiobookChapterPlan(title=c.title, chars=len(text), words=len(text.split()),
                                        voices=list(dict.fromkeys(s.voice or "" for s in c.spans if s.text)),
                                        est_s=round(len(text) / _CPS + pauses, 1)))
    return AudiobookPlan(chapters=out, voices=sorted({v for c in out for v in c.voices if v}),
                         words=sum(c.words for c in out), est_s=round(sum(c.est_s for c in out), 1))


@router.post("/audiobook/projects/{pid}/render", response_model=Job)
async def render_project(pid: str, req: AudiobookRenderRequest) -> Job:
    _project(pid)
    try:
        return render.run(pid, req.preview_chapter)
    except render.AudiobookError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/audiobook/projects/{pid}/cover", response_model=AudiobookProject)
async def upload_cover(pid: str, file: UploadFile = File(...)) -> AudiobookProject:
    _project(pid)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _COVER_TYPES:
        raise HTTPException(400, "Cover must be a .jpg or .png image")
    data = await file.read()
    if not 0 < len(data) <= _COVER_MAX:
        raise HTTPException(400, "Cover must be at most 8 MB")
    d = store.project_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("cover.*"):
        old.unlink()
    (d / f"cover{ext}").write_bytes(data)
    return store.to_api(await asyncio.to_thread(store.update, pid, lambda p: p.update(cover=f"cover{ext}")))


@router.delete("/audiobook/projects/{pid}/renders/{render_id}", response_model=AudiobookProject)
async def delete_render(pid: str, render_id: str) -> AudiobookProject:
    _project(pid)

    def apply(p: dict[str, Any]) -> None:
        entry = next((r for r in p["renders"] if r["id"] == render_id), None)
        if entry is None:
            raise HTTPException(404, "Render not found")
        (store.project_dir(pid) / entry["filename"]).unlink(missing_ok=True)
        p["renders"] = [r for r in p["renders"] if r["id"] != render_id]

    return store.to_api(await asyncio.to_thread(store.update, pid, apply))
