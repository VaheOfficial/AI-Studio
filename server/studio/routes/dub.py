"""Dubbing projects, glossary, subtitles and the shared ffmpeg media tools (see ``docs/api/dub.md``)."""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import File, Form, HTTPException, Response, UploadFile

from .. import config, media, settings
from ..dub import pipeline, segmentation, store, subtitles, translate as tr
from ..dub import waveform as dub_waveform
from ..dub import export as dub_export
from ..dub.llm import Chat, LLMError
from ..schemas import Job
from ..schemas_dub import (DubAutoGlossaryRequest, DubCreateResponse, DubExportRequest, DubGlossaryInput,
                           DubGlossaryTerm, DubParsedSubtitles, DubParseSubtitlesRequest, DubPreviewRequest,
                           DubPreviewResponse, DubProject, DubProjectPatch, DubProjectSummary, DubRunRequest, DubStatus,
                           DubSubtitleCue, DubVoiceSample, DubWaveform, MediaToolsStatus, NllbModel)
from . import StudioRouter

router = StudioRouter(prefix="/api")

NLLB_MODELS = [
    ("facebook/nllb-200-distilled-600M", "NLLB-200 distilled 600M", 2.5),
    ("facebook/nllb-200-distilled-1.3B", "NLLB-200 distilled 1.3B", 5.5),
    ("facebook/nllb-200-1.3B", "NLLB-200 1.3B", 5.5),
    ("facebook/nllb-200-3.3B", "NLLB-200 3.3B", 17.6),
]


def _project(pid: str) -> dict[str, Any]:
    try:
        return store.get(pid)
    except store.NotFound as exc:
        raise HTTPException(404, f"Dub project '{pid}' not found") from exc


def _dub_http(exc: pipeline.DubError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


# ------------------------------------------------------------------ status + media tools


@router.get("/dub/status", response_model=DubStatus)
async def dub_status() -> DubStatus:
    hub = config.CACHE_DIR / "hf" / "hub"
    nllb = [NllbModel(repo=repo, name=name, size_gb=size,
                      cached=(hub / f"models--{repo.replace('/', '--')}" / "snapshots").is_dir())
            for repo, name, size in NLLB_MODELS]
    hf_token = bool(settings.load().hf_token or os.environ.get("HF_TOKEN"))
    return DubStatus(media=await asyncio.to_thread(media.status), hf_token=hf_token, nllb=nllb)


@router.get("/media-tools", response_model=MediaToolsStatus)
async def media_tools() -> MediaToolsStatus:
    return await asyncio.to_thread(media.status)


@router.post("/media-tools/install", response_model=Job)
async def media_tools_install() -> Job:
    try:
        return media.install_job()
    except media.MediaError as exc:
        raise HTTPException(400, str(exc)) from exc


# ------------------------------------------------------------------ projects


@router.get("/dub/projects", response_model=list[DubProjectSummary])
async def list_projects() -> list[DubProjectSummary]:
    return [store.to_summary(p) for p in store.all_projects()]


@router.post("/dub/projects", response_model=DubCreateResponse)
async def create_project(file: UploadFile | None = File(None), url: str | None = Form(None),
                         name: str | None = Form(None), source_lang: str | None = Form(None),
                         num_speakers: int | None = Form(None)) -> DubCreateResponse:
    if (file is None) == (not url):
        raise HTTPException(400, "Send either a file or a URL")
    upload = None
    if file is not None:
        upload = config.UPLOADS_DIR / f"{uuid.uuid4().hex}{Path(file.filename or '').suffix.lower() or '.bin'}"
        upload.parent.mkdir(parents=True, exist_ok=True)
        with upload.open("wb") as f:
            await asyncio.to_thread(shutil.copyfileobj, file.file, f)
    filename = file.filename if file is not None and file.filename else (url or "source")
    try:
        project, job = await asyncio.to_thread(pipeline.create, upload, url, filename, name,
                                               source_lang or None, num_speakers)
    except pipeline.DubError as exc:
        raise _dub_http(exc) from exc
    return DubCreateResponse(project=store.to_api(project), job=job)


@router.get("/dub/projects/{pid}", response_model=DubProject)
async def get_project(pid: str) -> DubProject:
    return store.to_api(_project(pid))


def _spelling(text: str) -> str:
    return "".join(text.split()).casefold()


def _merge_segments(p: dict[str, Any], incoming: list) -> None:
    """Client edits → stored segments. Unchanged text keeps its words/translation/render state; edited text
    drops the stale plan/QC but keeps the render fingerprint (so the track reports it as changed). Words the
    editor carried through a merge/split are kept while they still spell the line's text."""
    old = {s["id"]: s for s in p["segments"]}
    merged = []
    for inp in sorted(incoming, key=lambda s: s.start):
        if inp.end <= inp.start:
            raise HTTPException(400, f"Segment {inp.id} ends before it starts")
        prev = old.get(inp.id, {})
        if inp.words is not None and _spelling("".join(w.text for w in inp.words)) == _spelling(inp.text):
            words = [w.model_dump(exclude_defaults=True) for w in inp.words]
        else:
            words = prev.get("words", []) if prev.get("text") == inp.text else []
        seg: dict[str, Any] = {"id": inp.id, "start": round(inp.start, 3), "end": round(inp.end, 3),
                               "speaker": inp.speaker, "text": inp.text, "words": words, "translations": {}}
        for key in ("voice", "gain", "speed", "direction"):
            value = getattr(inp, key)
            if value not in (None, ""):
                seg[key] = value
        lines = dict(prev.get("translations") or {})
        for lang, text in inp.translations.items():
            line = dict(lines.get(lang) or {})
            if line.get("text") != text:
                line = {k: v for k, v in line.items() if k in ("fingerprint", "fit")}
                line["text"] = text
            lines[lang] = line
        seg["translations"] = lines
        merged.append(seg)
    p["segments"] = merged
    known = {s["id"] for s in p["speakers"]}
    for s in merged:
        if s["speaker"] not in known:
            p["speakers"].append({"id": s["speaker"], "voice": "auto", "ref": None})
            known.add(s["speaker"])


@router.patch("/dub/projects/{pid}", response_model=DubProject)
async def patch_project(pid: str, patch: DubProjectPatch) -> DubProject:
    _project(pid)

    def apply(p: dict[str, Any]) -> None:
        if patch.name is not None:
            p["name"] = patch.name.strip() or p["name"]
        if patch.source_lang is not None:
            p["source_lang"] = patch.source_lang or None
        if patch.num_speakers is not None:
            p["num_speakers"] = patch.num_speakers or None
        if patch.settings is not None:
            p["settings"] = patch.settings.model_dump()
        if patch.speakers is not None:
            inputs = {s.id: s for s in patch.speakers}
            for spk in p["speakers"]:
                inp = inputs.get(spk["id"])
                if inp is None:
                    continue
                if inp.voice is not None:
                    spk["voice"] = inp.voice
                if "ref_segment" in inp.model_fields_set:
                    if inp.ref_segment and inp.ref_segment not in (p.get("seg_refs") or {}):
                        raise HTTPException(400, "That line has no voice clip to clone from")
                    if inp.ref_segment:
                        spk["pin"] = inp.ref_segment
                    else:
                        spk.pop("pin", None)
        if patch.segments is not None:
            _merge_segments(p, patch.segments)

    return store.to_api(await asyncio.to_thread(store.update, pid, apply))


@router.delete("/dub/projects/{pid}", status_code=204)
async def delete_project(pid: str) -> Response:
    _project(pid)
    if pipeline.jobs.find_active(lambda j: j.ref == pipeline.ref(pid)):
        raise HTTPException(409, "A job is running for this project — cancel it first")
    await asyncio.to_thread(store.delete, pid)
    return Response(status_code=204)


@router.post("/dub/projects/{pid}/transcribe", response_model=Job)
async def transcribe(pid: str) -> Job:
    _project(pid)
    try:
        return pipeline.retranscribe(pid)
    except pipeline.DubError as exc:
        raise _dub_http(exc) from exc


@router.post("/dub/projects/{pid}/translate", response_model=Job)
async def translate(pid: str, req: DubRunRequest) -> Job:
    _project(pid)
    try:
        return pipeline.run_translate(pid, req)
    except pipeline.DubError as exc:
        raise _dub_http(exc) from exc


@router.post("/dub/projects/{pid}/generate", response_model=Job)
async def generate(pid: str, req: DubRunRequest) -> Job:
    _project(pid)
    try:
        return pipeline.run_generate(pid, req)
    except pipeline.DubError as exc:
        raise _dub_http(exc) from exc


@router.post("/dub/projects/{pid}/qc/{lang}", response_model=Job)
async def verify(pid: str, lang: str) -> Job:
    _project(pid)
    try:
        return pipeline.run_qc(pid, lang)
    except pipeline.DubError as exc:
        raise _dub_http(exc) from exc


@router.post("/dub/projects/{pid}/preview", response_model=DubPreviewResponse)
async def preview(pid: str, req: DubPreviewRequest) -> DubPreviewResponse:
    _project(pid)
    try:
        path, duration = await asyncio.to_thread(pipeline.preview, pid, req.segment_id, req.lang)
    except pipeline.DubError as exc:
        raise _dub_http(exc) from exc
    rel = path.relative_to(store.project_dir(pid)).as_posix()
    return DubPreviewResponse(url=store.url(pid, rel, str(path.stat().st_mtime_ns)), duration=round(duration, 3))


@router.post("/dub/projects/{pid}/export", response_model=Job)
async def export(pid: str, req: DubExportRequest) -> Job:
    _project(pid)
    try:
        return dub_export.run(pid, req)
    except pipeline.DubError as exc:
        raise _dub_http(exc) from exc


@router.delete("/dub/projects/{pid}/exports/{export_id}", response_model=DubProject)
async def delete_export(pid: str, export_id: str) -> DubProject:
    _project(pid)

    def apply(p: dict[str, Any]) -> None:
        entry = next((e for e in p.get("exports") or [] if e["id"] == export_id), None)
        if entry is None:
            raise HTTPException(404, "Export not found")
        (store.project_dir(pid) / "exports" / entry["filename"]).unlink(missing_ok=True)
        p["exports"] = [e for e in p["exports"] if e["id"] != export_id]

    return store.to_api(await asyncio.to_thread(store.update, pid, apply))


@router.get("/dub/projects/{pid}/waveform", response_model=DubWaveform)
async def waveform(pid: str) -> DubWaveform:
    data = await asyncio.to_thread(dub_waveform.load, _project(pid))
    if data is None:
        raise HTTPException(404, "No waveform yet — the project is still being prepared")
    return DubWaveform.model_validate(data)


@router.get("/dub/projects/{pid}/speakers/{speaker}/samples", response_model=list[DubVoiceSample])
async def voice_samples(pid: str, speaker: str) -> list[DubVoiceSample]:
    try:
        return store.voice_samples(_project(pid), speaker)
    except store.NotFound as exc:
        raise HTTPException(404, "Speaker not found") from exc


@router.post("/dub/projects/{pid}/cleanup", response_model=DubProject)
async def cleanup(pid: str) -> DubProject:
    """Re-run the merge/stitch passes on the current segments (VoiceStudio "Clean up segments")."""
    _project(pid)

    def apply(p: dict[str, Any]) -> None:
        rows = [{"id": s["id"], "start": s["start"], "end": s["end"], "text": s["text"], "speaker": s["speaker"],
                 "words": s.get("words", []),
                 "translations": {lang: line.get("text", "") for lang, line in (s.get("translations") or {}).items()}}
                for s in p["segments"]]
        cleaned = segmentation.clean_up_segments(rows)
        p["segments"] = [{"id": c["id"], "start": c["start"], "end": c["end"], "speaker": c["speaker"],
                          "text": c["text"], "words": c.get("words", []),
                          "translations": {lang: {"text": t} for lang, t in (c.get("translations") or {}).items()}}
                         for c in cleaned]

    return store.to_api(await asyncio.to_thread(store.update, pid, apply))


@router.post("/dub/projects/{pid}/import-subtitles", response_model=DubProject)
async def import_subtitles(pid: str, file: UploadFile = File(...), lang: str | None = Form(None)) -> DubProject:
    """An SRT/VTT becomes the source segments, or (with ``lang``) that language's lines matched by overlap."""
    p = _project(pid)
    raw = await file.read()
    parsed = subtitles.parse(raw.decode("utf-8-sig", errors="replace"))
    if not parsed.cues:
        raise HTTPException(400, "No subtitle cues found in that file")

    def apply(proj: dict[str, Any]) -> None:
        duration = float(proj["source"].get("duration") or 0.0)
        if lang:
            segs = proj["segments"]
            for s in segs:
                best, overlap = None, 0.0
                for c in parsed.cues:
                    ov = min(s["end"], c["end"]) - max(s["start"], c["start"])
                    if ov > overlap:
                        best, overlap = c, ov
                if best:
                    s.setdefault("translations", {})[lang] = {"text": best["text"]}
            if lang not in proj["settings"]["targets"]:
                proj["settings"]["targets"].append(lang)
            return
        cues = [c for c in parsed.cues if not duration or c["start"] < duration]
        proj["segments"] = [{"id": f"s{i:05x}", "start": c["start"], "end": min(c["end"], duration or c["end"]),
                             "speaker": "Speaker 1", "text": c["text"], "words": [], "translations": {}}
                            for i, c in enumerate(cues)]
        proj["speakers"] = [{"id": "Speaker 1", "voice": "auto", "ref": None}]
        proj["diarization"] = {"source": "imported"}
        proj["tracks"] = {}
        proj["prepared"] = (store.project_dir(pid) / "audio16k.wav").is_file()

    if not lang and not p.get("prepared") and pipeline.jobs.find_active(lambda j: j.ref == pipeline.ref(pid)):
        raise HTTPException(409, "Wait for preparation to finish before importing subtitles")
    return store.to_api(await asyncio.to_thread(store.update, pid, apply))


@router.post("/dub/parse-subtitles", response_model=DubParsedSubtitles)
async def parse_subtitles(req: DubParseSubtitlesRequest) -> DubParsedSubtitles:
    parsed = subtitles.parse(req.text)
    return DubParsedSubtitles(cues=[DubSubtitleCue(**c) for c in parsed.cues], skipped=parsed.skipped,
                              dropped=parsed.dropped)


# ------------------------------------------------------------------ glossary


@router.get("/dub/projects/{pid}/glossary", response_model=list[DubGlossaryTerm])
async def glossary(pid: str) -> list[DubGlossaryTerm]:
    _project(pid)
    return store.glossary(pid)


@router.post("/dub/projects/{pid}/glossary", response_model=DubGlossaryTerm)
async def add_term(pid: str, body: DubGlossaryInput) -> DubGlossaryTerm:
    _project(pid)
    return store.add_term(pid, body.source, body.target, body.note)


@router.put("/dub/projects/{pid}/glossary/{tid}", response_model=DubGlossaryTerm)
async def update_term(pid: str, tid: str, body: DubGlossaryInput) -> DubGlossaryTerm:
    try:
        return store.update_term(pid, tid, body.source, body.target, body.note)
    except store.NotFound as exc:
        raise HTTPException(404, "Term not found") from exc


@router.delete("/dub/projects/{pid}/glossary/{tid}", status_code=204)
async def delete_term(pid: str, tid: str) -> Response:
    try:
        store.delete_term(pid, tid)
    except store.NotFound as exc:
        raise HTTPException(404, "Term not found") from exc
    return Response(status_code=204)


@router.post("/dub/projects/{pid}/glossary/auto", response_model=list[DubGlossaryTerm])
async def auto_glossary(pid: str, req: DubAutoGlossaryRequest) -> list[DubGlossaryTerm]:
    """LLM-proposed terminology (proper nouns, recurring terms) added as ``auto`` rows; existing sources skipped."""
    p = _project(pid)
    model = p["settings"]["translation"].get("model")
    if not model:
        raise HTTPException(409, "Choose a translation model first")
    try:
        chat = Chat(model)
        terms = await asyncio.to_thread(tr.auto_extract_glossary, chat, [s["text"] for s in p["segments"]],
                                        p.get("source_lang") or "en", req.lang)
    except LLMError as exc:
        raise HTTPException(502, f"The model could not propose terms: {exc}") from exc
    existing = {t.source.lower() for t in store.glossary(pid)}
    for t in terms:
        if t["source"].lower() not in existing:
            store.add_term(pid, t["source"], t["target"], t["note"], auto=True)
            existing.add(t["source"].lower())
    return store.glossary(pid)
