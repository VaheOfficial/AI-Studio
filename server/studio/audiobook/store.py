"""Audiobook projects in sqlite (one JSON document each); files live in ``data/outputs/audiobook/<id>``."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from .. import config, db
from ..schemas_dub import AudiobookPreview, AudiobookProject, AudiobookRender, AudiobookSettings, AudiobookSummary
from . import script

ROOT = config.OUTPUTS_DIR / "audiobook"
_ready = False
_lock = threading.RLock()


class NotFound(KeyError):
    pass


def _init() -> None:
    global _ready
    if not _ready:
        db.execute("CREATE TABLE IF NOT EXISTS audiobook_projects (id TEXT PRIMARY KEY, data TEXT NOT NULL, "
                   "updated_at TEXT NOT NULL)")
        _ready = True


def project_dir(pid: str) -> Path:
    return ROOT / pid


def url(pid: str, rel: str, version: str | None = None) -> str:
    return f"/files/outputs/audiobook/{pid}/{rel}" + (f"?v={version}" if version else "")


def create(name: str, text: str) -> dict[str, Any]:
    _init()
    now = db.now_iso()
    p = {"id": uuid.uuid4().hex[:12], "name": name, "script": text, "settings": AudiobookSettings().model_dump(),
         "cover": None, "renders": [], "previews": {}, "created_at": now, "updated_at": now}
    save(p)
    return p


def get(pid: str) -> dict[str, Any]:
    _init()
    row = db.query_one("SELECT data FROM audiobook_projects WHERE id = ?", (pid,))
    if row is None:
        raise NotFound(pid)
    return json.loads(row["data"])


def save(p: dict[str, Any]) -> None:
    p["updated_at"] = db.now_iso()
    db.execute("INSERT INTO audiobook_projects(id, data, updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET "
               "data = excluded.data, updated_at = excluded.updated_at",
               (p["id"], json.dumps(p, ensure_ascii=False), p["updated_at"]))


def update(pid: str, fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with _lock:
        p = get(pid)
        fn(p)
        save(p)
        return p


def all_projects() -> list[dict[str, Any]]:
    _init()
    return [json.loads(r["data"]) for r in db.query("SELECT data FROM audiobook_projects ORDER BY updated_at DESC")]


def delete(pid: str) -> None:
    get(pid)
    db.execute("DELETE FROM audiobook_projects WHERE id = ?", (pid,))
    shutil.rmtree(project_dir(pid), ignore_errors=True)


def to_api(p: dict[str, Any]) -> AudiobookProject:
    return AudiobookProject(
        id=p["id"], name=p["name"], script=p["script"], settings=AudiobookSettings.model_validate(p["settings"]),
        cover_url=url(p["id"], p["cover"], p["updated_at"].replace(":", "")) if p.get("cover") else None,
        renders=[AudiobookRender.model_validate(r) for r in p["renders"]],
        previews={k: AudiobookPreview.model_validate(v) for k, v in p["previews"].items()},
        created_at=p["created_at"], updated_at=p["updated_at"])


def to_summary(p: dict[str, Any]) -> AudiobookSummary:
    return AudiobookSummary(id=p["id"], name=p["name"], updated_at=p["updated_at"],
                            chapters=len(script.parse(p["script"])), renders=len(p["renders"]))
