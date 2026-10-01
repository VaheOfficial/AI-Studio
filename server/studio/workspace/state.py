"""Per-session workspace state (chosen folder + current plan) and the per-folder memory notes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import config, db
from ..events import bus
from ..schemas_workspace import EvWorkspaceUpdate, PlanItem, WorkspaceState

MEMORY_DIR = config.WORKSPACE_DIR / "memory"
MEMORY_LIMIT = 16_000


class WorkspaceError(Exception):
    """User-facing workspace problem (no folder chosen, path outside the folder…)."""


def init() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS workspace_sessions (
        session_id TEXT PRIMARY KEY,
        root TEXT,
        plan TEXT NOT NULL DEFAULT '[]'
    )""")


def get(session_id: str) -> WorkspaceState:
    r = db.query_one("SELECT root, plan FROM workspace_sessions WHERE session_id = ?", (session_id,))
    if r is None:
        return WorkspaceState(session_id=session_id)
    return WorkspaceState(session_id=session_id, root=r["root"], plan=[PlanItem(**p) for p in json.loads(r["plan"])])


def _save(state: WorkspaceState) -> WorkspaceState:
    db.execute(
        """INSERT INTO workspace_sessions(session_id, root, plan) VALUES(?,?,?)
           ON CONFLICT(session_id) DO UPDATE SET root = excluded.root, plan = excluded.plan""",
        (state.session_id, state.root, json.dumps([p.model_dump() for p in state.plan])),
    )
    bus.publish(EvWorkspaceUpdate(state=state))
    return state


def set_root(session_id: str, root: str) -> WorkspaceState:
    path = Path(root).expanduser()
    if not path.is_absolute():
        raise WorkspaceError("Choose an absolute folder path")
    path = path.resolve()
    if not path.is_dir():
        raise WorkspaceError(f"Folder does not exist: {path}")
    if path == Path(path.anchor):
        raise WorkspaceError("Choose a folder, not the root of a drive")
    return _save(get(session_id).model_copy(update={"root": str(path)}))


def set_plan(session_id: str, plan: list[PlanItem]) -> WorkspaceState:
    return _save(get(session_id).model_copy(update={"plan": plan}))


def require_root(session_id: str) -> Path:
    root = get(session_id).root
    if not root:
        raise WorkspaceError("No workspace folder is set for this chat. Ask the user to choose one in the "
                             "workspace panel (folder button above the terminal/files tabs).")
    path = Path(root)
    if not path.is_dir():
        raise WorkspaceError(f"The workspace folder {root} is missing (was the drive disconnected?)")
    return path


def sessions_with_root(root: str) -> list[str]:
    return [r["session_id"] for r in db.query("SELECT session_id FROM workspace_sessions WHERE root = ?", (root,))]


def all_roots() -> list[str]:
    return [r["root"] for r in db.query("SELECT DISTINCT root FROM workspace_sessions WHERE root IS NOT NULL")]


def forget(session_id: str) -> None:
    db.execute("DELETE FROM workspace_sessions WHERE session_id = ?", (session_id,))


# ------------------------------- memory -------------------------------


def memory_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root).lower().encode()).hexdigest()[:16]
    return MEMORY_DIR / f"{digest}.md"


def read_memory(root: Path) -> str:
    p = memory_path(root)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def write_memory(root: Path, text: str) -> None:
    if len(text) > MEMORY_LIMIT:
        raise WorkspaceError(f"Memory notes are limited to {MEMORY_LIMIT} characters; condense them first")
    p = memory_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
