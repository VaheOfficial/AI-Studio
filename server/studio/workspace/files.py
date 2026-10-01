"""Files inside a session's workspace folder: safe path resolution, listing, reading, atomic writes,
exact-string edits with diffs, glob/grep search, the server-side folder picker and the change watcher.

Path rules are ported from OpenMuse ``apps/computer/files.py``/``workspacePath()``: every path must resolve
inside the chosen folder (no ``..`` escapes, symlinks are followed only when they stay inside), and writes go
through a temp file + ``os.replace``.
"""

from __future__ import annotations

import asyncio
import difflib
import fnmatch
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import psutil
from watchfiles import Change, awatch

from .. import events, osenv
from ..events import bus
from ..schemas_workspace import (EvFsChange, FolderEntry, FolderListing, FsChange, FsEntry, FsFile, FsListing)
from . import state
from .state import WorkspaceError

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".next",
                "dist", "build", ".turbo", ".cache"}
VIEW_LIMIT = 1_000_000  # bytes shown in the file viewer
TOOL_READ_LINES = 2000
TOOL_LINE_CHARS = 2000
DIFF_LIMIT = 60_000
SEARCH_LIMIT = 200


# ------------------------------- paths -------------------------------


def _inside(root: Path, target: Path) -> bool:
    r, t = os.path.normcase(str(root)), os.path.normcase(str(target))
    return t == r or t.startswith(r.rstrip("\\/") + os.sep)


def resolve(root: Path, path: str) -> Path:
    """Absolute path for ``path`` (relative to the root, or absolute inside it)."""
    if "\0" in path:
        raise WorkspaceError("Invalid path")
    raw = Path(path.strip() or ".").expanduser()
    target = (raw if raw.is_absolute() else root / raw).resolve()
    if not _inside(root.resolve(), target):
        raise WorkspaceError(f"'{path}' is outside the workspace folder {root}")
    return target


def rel(root: Path, target: Path) -> str:
    relative = os.path.relpath(target, root)
    return "." if relative == "." else PurePosixPath(Path(relative)).as_posix()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_binary(sample: bytes) -> bool:
    return b"\0" in sample


def read_text(p: Path) -> str:
    """Whole file as text, line endings preserved. Refuses binary files."""
    data = p.read_bytes()
    if _is_binary(data[:8192]):
        raise WorkspaceError(f"{p.name} is a binary file")
    return data.decode("utf-8", errors="replace")


def write_atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


# ------------------------------- diffs -------------------------------


@dataclass
class Diff:
    text: str
    added: int
    removed: int


def unified_diff(path: str, before: str, after: str) -> Diff:
    a = before.replace("\r\n", "\n").splitlines(keepends=True)
    b = after.replace("\r\n", "\n").splitlines(keepends=True)
    lines = list(difflib.unified_diff(a, b, fromfile=f"a/{path}", tofile=f"b/{path}", n=3))
    added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    text = "".join(ln if ln.endswith("\n") else ln + "\n" for ln in lines)
    if len(text) > DIFF_LIMIT:
        text = text[:DIFF_LIMIT] + "\n… diff truncated\n"
    return Diff(text, added, removed)


def replace_exact(text: str, old: str, new: str, replace_all: bool) -> str:
    """Exact-match edit: ``old`` must occur exactly once unless ``replace_all``."""
    if old == new:
        raise WorkspaceError("old_string and new_string are identical")
    if not old:
        raise WorkspaceError("old_string must not be empty (use write_file to create a file)")
    if old not in text and "\r\n" in text and "\n" in old:
        old, new = old.replace("\r\n", "\n").replace("\n", "\r\n"), new.replace("\r\n", "\n").replace("\n", "\r\n")
    count = text.count(old)
    if count == 0:
        raise WorkspaceError("old_string was not found in the file. Read the file again and copy the exact text, "
                             "including whitespace and indentation.")
    if count > 1 and not replace_all:
        raise WorkspaceError(f"old_string occurs {count} times; add surrounding lines to make it unique or set "
                             "replace_all")
    return text.replace(old, new) if replace_all else text.replace(old, new, 1)


# ------------------------------- listing / reading -------------------------------


def list_dir(root: Path, path: str) -> FsListing:
    p = resolve(root, path)
    if not p.is_dir():
        raise WorkspaceError(f"Not a folder: {path}")
    entries: list[FsEntry] = []
    for child in p.iterdir():
        if child.name == ".git":
            continue
        try:
            st = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        entries.append(FsEntry(name=child.name, path=rel(root, child), type="dir" if is_dir else "file",
                               size=0 if is_dir else st.st_size, mtime=_iso(st.st_mtime)))
    entries.sort(key=lambda e: (e.type != "dir", e.name.lower()))
    return FsListing(path=rel(root, p), entries=entries[:2000])


def view_file(root: Path, path: str) -> FsFile:
    p = resolve(root, path)
    if not p.is_file():
        raise WorkspaceError(f"No such file: {path}")
    size = p.stat().st_size
    with open(p, "rb") as f:
        data = f.read(VIEW_LIMIT + 1)
    if _is_binary(data[:8192]):
        return FsFile(path=rel(root, p), content="", size=size, binary=True, truncated=False)
    truncated = len(data) > VIEW_LIMIT
    return FsFile(path=rel(root, p), content=data[:VIEW_LIMIT].decode("utf-8", errors="replace"), size=size,
                  binary=False, truncated=truncated)


def save_file(root: Path, path: str, content: str) -> FsFile:
    p = resolve(root, path)
    if p.is_dir():
        raise WorkspaceError(f"{path} is a folder")
    write_atomic(p, content)
    return view_file(root, path)


def numbered(text: str, offset: int, limit: int) -> tuple[str, int, int]:
    """``cat -n`` style excerpt: (text, lines shown, total lines)."""
    lines = text.splitlines()
    start = max(offset, 1) - 1
    chunk = lines[start:start + limit]
    out = [f"{i:>6}\t{ln if len(ln) <= TOOL_LINE_CHARS else ln[:TOOL_LINE_CHARS] + '…'}"
           for i, ln in enumerate(chunk, start + 1)]
    return "\n".join(out), len(chunk), len(lines)


# ------------------------------- search -------------------------------


def _walk(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in filenames:
            yield Path(dirpath) / name


def _glob_re(pattern: str) -> re.Pattern[str]:
    """Path glob with ``**`` (any depth), ``*`` and ``?`` (within one path segment)."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.IGNORECASE)


def find(root: Path, pattern: str, path: str) -> tuple[list[str], bool]:
    base = resolve(root, path)
    by_name = "/" not in pattern
    rx = _glob_re(pattern.removeprefix("./"))
    hits: list[tuple[float, str]] = []
    for f in _walk(base):
        relative = rel(root, f)
        if (fnmatch.fnmatch(f.name, pattern) if by_name else rx.match(rel(base, f))):
            try:
                hits.append((f.stat().st_mtime, relative))
            except OSError:
                continue
    hits.sort(reverse=True)
    return [h[1] for h in hits[:SEARCH_LIMIT]], len(hits) > SEARCH_LIMIT


@dataclass
class Match:
    path: str
    line: int
    text: str


def _rg_search(root: Path, base: Path, pattern: str, glob: str | None, ignore_case: bool) -> list[Match] | None:
    rg = shutil.which("rg")
    if not rg:
        return None
    cmd = [rg, "--line-number", "--no-heading", "--color", "never", "--max-count", "50", "--max-columns", "300",
           "--with-filename"]
    if ignore_case:
        cmd.append("-i")
    if glob:
        cmd += ["-g", glob]
    cmd += ["-e", pattern, str(base)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode not in (0, 1):
        raise WorkspaceError(f"ripgrep failed: {proc.stderr.strip()[:500]}")
    out: list[Match] = []
    for ln in proc.stdout.splitlines():
        m = re.match(r"^(.*?):(\d+):(.*)$", ln)
        if m:
            out.append(Match(rel(root, Path(m.group(1))), int(m.group(2)), m.group(3)))
        if len(out) > SEARCH_LIMIT:
            break
    return out


def search(root: Path, pattern: str, path: str, glob: str | None, ignore_case: bool) -> tuple[list[Match], bool]:
    base = resolve(root, path)
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise WorkspaceError(f"Invalid regular expression: {exc}") from exc
    found = _rg_search(root, base, pattern, glob, ignore_case)
    if found is None:
        found = []
        files = [base] if base.is_file() else _walk(base)
        for f in files:
            if glob and not fnmatch.fnmatch(f.name, glob):
                continue
            try:
                if f.stat().st_size > 2_000_000:
                    continue
                data = f.read_bytes()
            except OSError:
                continue
            if _is_binary(data[:8192]):
                continue
            for i, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    found.append(Match(rel(root, f), i, line[:300]))
                    if len(found) > SEARCH_LIMIT:
                        break
            if len(found) > SEARCH_LIMIT:
                break
    return found[:SEARCH_LIMIT], len(found) > SEARCH_LIMIT


# ------------------------------- uploads -------------------------------


def save_upload(root: Path, filename: str, data: bytes) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(filename).name).strip(" .") or "file"
    folder = root / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / name, 1
    while target.exists():
        target = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    target.write_bytes(data)
    return rel(root, target)


# ------------------------------- folder picker -------------------------------


def _roots() -> list[FolderEntry]:
    """Where a folder picker starts below Home: the drives on Windows; elsewhere the file system root and the
    places external drives are mounted (psutil's partition list is full of system volumes there)."""
    if osenv.IS_WINDOWS:
        return [FolderEntry(name=p.mountpoint.rstrip("\\"), path=p.mountpoint)
                for p in psutil.disk_partitions(all=False)]
    roots = [FolderEntry(name="/", path="/")]
    for base in ((Path("/Volumes"),) if osenv.IS_MAC else (Path("/media") / Path.home().name, Path("/mnt"))):
        try:
            roots += [FolderEntry(name=c.name, path=str(c)) for c in sorted(base.iterdir()) if c.is_dir()]
        except OSError:
            continue
    return roots


def browse(path: str) -> FolderListing:
    if not path:
        home = Path.home()
        return FolderListing(path="", dirs=[FolderEntry(name=f"Home ({home.name})", path=str(home)), *_roots()])
    p = Path(path).expanduser()
    if not p.is_absolute() or not p.is_dir():
        raise WorkspaceError(f"Not a folder: {path}")
    p = p.resolve()
    dirs = []
    try:
        children = sorted(p.iterdir(), key=lambda c: c.name.lower())
    except PermissionError as exc:
        raise WorkspaceError(f"Access denied: {p}") from exc
    for child in children:
        if child.name.startswith(("$", ".")) or child.name in ("System Volume Information",):
            continue
        try:
            if child.is_dir():
                dirs.append(FolderEntry(name=child.name, path=str(child)))
        except OSError:
            continue
    parent = "" if p.parent == p else str(p.parent)
    return FolderListing(path=str(p), parent=parent, dirs=dirs[:1000])


def make_folder(parent: str, name: str) -> FolderListing:
    if not name.strip() or re.search(r'[<>:"/\\|?*]', name):
        raise WorkspaceError("Enter a folder name without < > : \" / \\ | ? *")
    base = Path(parent)
    if not base.is_absolute() or not base.is_dir():
        raise WorkspaceError(f"Not a folder: {parent}")
    (base / name.strip()).mkdir(exist_ok=True)
    return browse(str(base / name.strip()))


# ------------------------------- watcher -------------------------------


class FileWatcher:
    """One ``watchfiles`` watcher per workspace folder in use; changes are pushed as ``fs.change``."""

    def __init__(self) -> None:
        self._tasks: dict[str, tuple[asyncio.Task[None], asyncio.Event]] = {}

    def sync(self) -> None:
        wanted = {r for r in state.all_roots() if Path(r).is_dir()}
        for root in list(self._tasks):
            if root not in wanted:
                task, stop = self._tasks.pop(root)
                stop.set()
        for root in wanted - set(self._tasks):
            stop = asyncio.Event()
            self._tasks[root] = (asyncio.create_task(self._watch(root, stop), name=f"watch-{root}"), stop)

    async def shutdown(self) -> None:
        for task, stop in self._tasks.values():
            stop.set()
            task.cancel()
        tasks = [t for t, _ in self._tasks.values()]
        self._tasks.clear()
        if tasks:
            await asyncio.wait(tasks, timeout=5)

    @staticmethod
    def _keep(_change: Change, path: str) -> bool:
        parts = Path(path).parts
        return not any(p in IGNORED_DIRS for p in parts) and not path.endswith(".tmp")

    async def _watch(self, root: str, stop: asyncio.Event) -> None:
        kinds = {Change.added: "added", Change.modified: "modified", Change.deleted: "deleted"}
        base = Path(root)
        try:
            async for batch in awatch(root, watch_filter=self._keep, stop_event=stop, debounce=400, step=100,
                                      recursive=True):
                changes = [FsChange(type=kinds[c], path=rel(base, Path(p))) for c, p in batch][:300]
                if changes:
                    bus.publish(EvFsChange(session_ids=state.sessions_with_root(root), changes=changes))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # e.g. the folder was deleted or the drive dropped out
            events.log("warn", "workspace", f"Stopped watching {root}: {exc}")
            self._tasks.pop(root, None)


watcher = FileWatcher()
