"""Dub projects in sqlite: one JSON document per project (internal shape, with file paths relative to the
project folder under ``data/outputs/dub/<id>``) plus a glossary table. ``to_api`` renders the public
``DubProject`` (URLs instead of paths, per-track staleness)."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from .. import config, db
from ..schemas_dub import (DubDiarization, DubExport, DubGlossaryTerm, DubLine, DubProject, DubProjectSummary,
                           DubRetimeChunk, DubSegment, DubSeparation, DubSettings, DubSource, DubSpeaker, DubTrack,
                           DubVoiceSample)
from .retime import expand_chunks

ROOT = config.OUTPUTS_DIR / "dub"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS dub_projects (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dub_glossary (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    auto INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dub_glossary_project ON dub_glossary(project_id);
"""
_ready = False
_lock = threading.RLock()


class NotFound(KeyError):
    pass


def _init() -> None:
    global _ready
    if not _ready:
        for stmt in filter(str.strip, _SCHEMA.split(";")):
            db.execute(stmt)
        _ready = True


def project_dir(pid: str) -> Path:
    return ROOT / pid


def url(pid: str, rel: str, version: str | None = None) -> str:
    return f"/files/outputs/dub/{pid}/{rel}" + (f"?v={version}" if version else "")


def lock() -> threading.RLock:
    """Serialises read-modify-write of project documents across jobs and requests."""
    return _lock


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def create(name: str, source: dict[str, Any], source_lang: str | None, num_speakers: int | None,
           settings: DubSettings) -> dict[str, Any]:
    _init()
    now = db.now_iso()
    project = {
        "id": source["id"], "name": name, "created_at": now, "updated_at": now, "source": source,
        "source_lang": source_lang, "num_speakers": num_speakers, "prepared": False, "separation": None,
        "diarization": None, "warnings": [], "segments": [], "speakers": [], "seg_refs": {},
        "settings": settings.model_dump(), "tracks": {}, "natural_durs": {}, "translation_context": {},
        "exports": [],
    }
    save(project)
    return project


def get(pid: str) -> dict[str, Any]:
    _init()
    row = db.query_one("SELECT data FROM dub_projects WHERE id = ?", (pid,))
    if row is None:
        raise NotFound(pid)
    return json.loads(row["data"])


def save(project: dict[str, Any]) -> None:
    project["updated_at"] = db.now_iso()
    db.execute("INSERT INTO dub_projects(id, data, updated_at) VALUES(?,?,?) "
               "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
               (project["id"], json.dumps(project, ensure_ascii=False), project["updated_at"]))


def update(pid: str, fn: Any) -> dict[str, Any]:
    """Apply ``fn(project)`` under the store lock and persist."""
    with _lock:
        project = get(pid)
        fn(project)
        save(project)
        return project


def all_projects() -> list[dict[str, Any]]:
    _init()
    return [json.loads(r["data"]) for r in db.query("SELECT data FROM dub_projects ORDER BY updated_at DESC")]


def delete(pid: str) -> None:
    _init()
    get(pid)
    db.execute("DELETE FROM dub_projects WHERE id = ?", (pid,))
    db.execute("DELETE FROM dub_glossary WHERE project_id = ?", (pid,))
    shutil.rmtree(project_dir(pid), ignore_errors=True)


# ------------------------------------------------------------------ glossary


def glossary(pid: str) -> list[DubGlossaryTerm]:
    _init()
    rows = db.query("SELECT * FROM dub_glossary WHERE project_id = ? ORDER BY auto, created_at", (pid,))
    return [DubGlossaryTerm(id=r["id"], source=r["source"], target=r["target"], note=r["note"], auto=bool(r["auto"]))
            for r in rows]


def add_term(pid: str, source: str, target: str, note: str, auto: bool = False) -> DubGlossaryTerm:
    _init()
    tid = uuid.uuid4().hex[:12]
    db.execute("INSERT INTO dub_glossary(id, project_id, source, target, note, auto, created_at) VALUES(?,?,?,?,?,?,?)",
               (tid, pid, source.strip(), target.strip(), note.strip(), int(auto), db.now_iso()))
    return DubGlossaryTerm(id=tid, source=source.strip(), target=target.strip(), note=note.strip(), auto=auto)


def update_term(pid: str, tid: str, source: str, target: str, note: str) -> DubGlossaryTerm:
    _init()
    if not db.execute("UPDATE dub_glossary SET source = ?, target = ?, note = ?, auto = 0 WHERE id = ? AND project_id = ?",
                      (source.strip(), target.strip(), note.strip(), tid, pid)):
        raise NotFound(tid)
    return DubGlossaryTerm(id=tid, source=source.strip(), target=target.strip(), note=note.strip(), auto=False)


def delete_term(pid: str, tid: str) -> None:
    _init()
    if not db.execute("DELETE FROM dub_glossary WHERE id = ? AND project_id = ?", (tid, pid)):
        raise NotFound(tid)


# ------------------------------------------------------------------ API rendering


def _retime_map(track: dict[str, Any]) -> list[DubRetimeChunk]:
    """The export's video retime (same chunks) laid out on the track timeline, so the preview can play in sync."""
    if not track.get("plan"):
        return []
    out, at = [], 0.0
    for a, b, ratio in expand_chunks(track["plan"], float(track.get("orig_duration") or 0.0)):
        out.append(DubRetimeChunk(start=round(a, 4), end=round(b, 4), at=round(at, 4), ratio=ratio))
        at += (b - a) * ratio
    return out


def speaker_ref(p: dict[str, Any], spk: dict[str, Any]) -> dict | None:
    """The clone reference a speaker uses: the line clip the user picked (``pin``) while it exists, else the
    automatic pooled one."""
    clip = (p.get("seg_refs") or {}).get(spk.get("pin") or "")
    return {**clip, "kind": "speaker", "pinned": True} if clip else spk.get("ref")


IDEAL_CHARS_PER_S = 13.0  # ordinary conversational speech
IDEAL_SAMPLE_S = (4.0, 10.0)
SUGGESTED_SAMPLES = 3


def voice_samples(p: dict[str, Any], speaker: str) -> list[DubVoiceSample]:
    """The speaker's line clips (cut from the separated vocals, trimmed to their words) as clone-sample choices,
    steadiest first: a speaking rate near ordinary speech (songs and chants sit far from it) and 4–10 s long."""
    if not any(x["id"] == speaker for x in p["speakers"]):
        raise NotFound(speaker)
    lines = {s["id"]: s for s in p["segments"] if s["speaker"] == speaker}
    ranked = []
    for sid, clip in (p.get("seg_refs") or {}).items():
        s = lines.get(sid)
        if s is None or clip["duration"] <= 0:
            continue
        rate = len(clip["text"].strip()) / clip["duration"]
        lo, hi = IDEAL_SAMPLE_S
        score = abs(rate - IDEAL_CHARS_PER_S) / IDEAL_CHARS_PER_S + (max(lo - clip["duration"], clip["duration"] - hi, 0.0) / lo)
        ranked.append((score, sid, s, clip, rate))
    ranked.sort(key=lambda r: (r[0], r[2]["start"]))
    return [DubVoiceSample(segment_id=sid, start=s["start"], end=s["end"], text=clip["text"], duration=clip["duration"],
                           chars_per_s=round(rate, 1), url=url(p["id"], clip["path"]), suggested=i < SUGGESTED_SAMPLES)
            for i, (_score, sid, s, clip, rate) in enumerate(ranked)]


def stale_ids(project: dict[str, Any], lang: str) -> list[str]:
    from .pipeline import segment_fingerprint  # late import: pipeline imports this module

    track = project["tracks"].get(lang)
    if not track:
        return []
    prints = track.get("fingerprints") or {}
    return [s["id"] for s in project["segments"] if prints.get(s["id"]) != segment_fingerprint(project, s, lang)]


def to_api(p: dict[str, Any]) -> DubProject:
    pid = p["id"]
    version = p["updated_at"].replace(":", "").replace("-", "").replace(".", "")
    src = p["source"]
    segments = []
    for s in p["segments"]:
        lines = {}
        for lang, line in (s.get("translations") or {}).items():
            lines[lang] = DubLine.model_validate(line)
        segments.append(DubSegment(id=s["id"], start=s["start"], end=s["end"], speaker=s["speaker"], text=s["text"],
                                   voice=s.get("voice"), gain=s.get("gain"), speed=s.get("speed"),
                                   direction=s.get("direction"), translations=lines, words=s.get("words") or []))
    speakers = []
    for spk in p["speakers"]:
        ref = speaker_ref(p, spk)
        speakers.append(DubSpeaker(id=spk["id"], voice=spk.get("voice", "auto"),
                                   ref_url=url(pid, ref["path"]) if ref else None,
                                   ref_duration=ref["duration"] if ref else None,
                                   ref_kind=ref["kind"] if ref else None, ref_text=ref.get("text") if ref else None,
                                   ref_pinned=bool(ref and ref.get("pinned"))))
    tracks = {}
    for lang, t in p["tracks"].items():
        tracks[lang] = DubTrack(lang=lang, url=url(pid, t["file"], t["created_at"].replace(":", "")),
                                duration=t["duration"], timing=t["timing"], created_at=t["created_at"],
                                stale=stale_ids(p, lang), retime=_retime_map(t))
    sep = p.get("separation")
    return DubProject(
        id=pid, name=p["name"], created_at=p["created_at"], updated_at=p["updated_at"],
        source=DubSource(kind=src["kind"], filename=src["filename"], url=src.get("url"), input_type=src["input_type"],
                         duration=src.get("duration") or 0.0,
                         media_url=url(pid, src["media"]) if src.get("media") else "",
                         thumb_url=url(pid, src["thumb"], version) if src.get("thumb") else None),
        source_lang=p.get("source_lang"), num_speakers=p.get("num_speakers"), prepared=bool(p.get("prepared")),
        separation=DubSeparation(vocals_url=url(pid, sep["vocals"]), background_url=url(pid, sep["background"]))
        if sep else None,
        diarization=DubDiarization.model_validate(p["diarization"]) if p.get("diarization") else None,
        warnings=list(p.get("warnings") or []), segments=segments, speakers=speakers,
        settings=DubSettings.model_validate(p["settings"]), tracks=tracks,
        exports=[DubExport.model_validate(e) for e in p.get("exports") or []],
    )


def to_summary(p: dict[str, Any]) -> DubProjectSummary:
    src = p["source"]
    return DubProjectSummary(id=p["id"], name=p["name"], created_at=p["created_at"], updated_at=p["updated_at"],
                             filename=src["filename"], input_type=src["input_type"], duration=src.get("duration") or 0,
                             thumb_url=url(p["id"], src["thumb"]) if src.get("thumb") else None,
                             segments=len(p["segments"]), tracks=list(p["tracks"]))
