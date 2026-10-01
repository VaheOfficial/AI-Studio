"""File checkpoints: what a file held before the agent changed it, per tool call, so rewinding a chat to an
earlier message can put the files back. Only the agent's own file tools write here (write_file, edit_file,
memory); changes made by terminal commands can't be tracked and are reported instead."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import db

MAX_BYTES = 8 * 1024 * 1024  # larger files are not snapshotted (their rewind is reported as skipped)


def init() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS file_checkpoints (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        call_id TEXT NOT NULL,
        path TEXT NOT NULL,
        existed INTEGER NOT NULL,
        content BLOB
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS file_checkpoints_session ON file_checkpoints(session_id, call_id)")


def record(session_id: str, call_id: str, path: Path) -> None:
    """Snapshot ``path`` before a tool call changes it (once per call and path)."""
    key = str(path.resolve())
    if db.query_one("SELECT 1 FROM file_checkpoints WHERE session_id = ? AND call_id = ? AND path = ?",
                    (session_id, call_id, key)):
        return
    existed = path.is_file()
    content = path.read_bytes() if existed and path.stat().st_size <= MAX_BYTES else None
    db.execute("INSERT INTO file_checkpoints(session_id, call_id, path, existed, content) VALUES(?,?,?,?,?)",
               (session_id, call_id, key, int(existed), content))


@dataclass
class Restored:
    restored: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def restore(session_id: str, call_ids: set[str]) -> Restored:
    """Put every file those calls changed back to its state before the earliest of them, then drop their
    snapshots."""
    out = Restored()
    if not call_ids:
        return out
    marks = ",".join("?" * len(call_ids))
    rows = db.query(f"SELECT path, existed, content FROM file_checkpoints WHERE session_id = ? AND call_id IN ({marks}) "
                    "ORDER BY seq", (session_id, *call_ids))
    first: dict[str, tuple[bool, bytes | None]] = {}
    for r in rows:
        first.setdefault(r["path"], (bool(r["existed"]), r["content"]))
    for key, (existed, content) in first.items():
        p = Path(key)
        try:
            if not existed:
                if p.is_file():
                    p.unlink()
                    out.removed.append(key)
            elif content is None:
                out.skipped.append(key)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(p.name + ".rewind.tmp")
                tmp.write_bytes(content)
                tmp.replace(p)
                out.restored.append(key)
        except OSError:
            out.skipped.append(key)
    db.execute(f"DELETE FROM file_checkpoints WHERE session_id = ? AND call_id IN ({marks})", (session_id, *call_ids))
    return out


def forget_session(session_id: str) -> None:
    db.execute("DELETE FROM file_checkpoints WHERE session_id = ?", (session_id,))
