"""Agent tools over the session's workspace: files, terminal commands/background processes, the browser,
the live plan, per-folder memory and background tasks. Each tool returns a typed ``display`` for its card."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .. import config, osenv
from ..agent.types import ToolContext, ToolFailure, ToolOutcome, ToolSpec
from ..schemas_workspace import (BrowserDisplay, DiffDisplay, FileDisplay, FileItem, FilesDisplay, PlanDisplay,
                                 PlanItem, TaskDisplay, TerminalDisplay)
from . import checkpoints, files, state
from .browser import browser
from .tasks import tasks
from .terminal import Terminal, terminals

MAX_OUTPUT_CHARS = 12_000
EXCERPT_CHARS = 4_000
DONE = "Done - do not repeat this call."


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_S = {"type": "string"}
_PATH = {"type": "string", "description": "Relative to the workspace folder (or absolute inside it)"}

SPECS: list[ToolSpec] = [
    ToolSpec("list_dir", "List a folder of the workspace ('.' for the workspace root).", _obj({"path": _PATH})),
    ToolSpec("read_file", "Read a text file of the workspace. Returns numbered lines (cat -n); use offset/limit "
             "for long files.",
             _obj({"path": _PATH, "offset": {"type": "integer", "minimum": 1, "description": "First line (1-based)"},
                   "limit": {"type": "integer", "minimum": 1, "maximum": 5000}}, ["path"])),
    ToolSpec("write_file", "Create a file or overwrite it completely. Prefer edit_file for changes to existing "
             "files.", _obj({"path": _PATH, "content": _S}, ["path", "content"]), needs_approval=True),
    ToolSpec("edit_file", "Replace an exact piece of text in a file. old_string must match the file exactly "
             "(whitespace included) and be unique unless replace_all is true. Read the file first.",
             _obj({"path": _PATH, "old_string": _S, "new_string": _S, "replace_all": {"type": "boolean"}},
                  ["path", "old_string", "new_string"]), needs_approval=True),
    ToolSpec("find_files", "Find files by glob pattern, newest first (e.g. '*.py' matches by name anywhere, "
             "'src/**/*.ts' matches paths). Skips node_modules, .git, virtualenvs.",
             _obj({"pattern": _S, "path": _PATH}, ["pattern"])),
    ToolSpec("search_files", "Search file contents with a regular expression; returns path:line: text.",
             _obj({"pattern": _S, "path": _PATH, "glob": {"type": "string", "description": "File name filter, "
                                                                                          "e.g. '*.py'"},
                   "ignore_case": {"type": "boolean"}}, ["pattern"])),
    ToolSpec("run_command", f"Run a {osenv.shell_name()} command in a terminal the user can watch (cwd defaults to the "
             "workspace folder). Returns exit code and output. If it is still running after timeout_s it keeps "
             "running in the background: poll it with read_process_output, end it with stop_process.",
             _obj({"command": _S, "cwd": _PATH,
                   "timeout_s": {"type": "integer", "minimum": 5, "maximum": 600,
                                 "description": "Default 120"}}, ["command"]), needs_approval=True),
    ToolSpec("start_process", "Start a long-running command (dev server, watcher…) in the background and return "
             "after a few seconds with its first output and process id.",
             _obj({"command": _S, "cwd": _PATH}, ["command"]), needs_approval=True),
    ToolSpec("read_process_output", "New output of a background process since the last read, and whether it is "
             "still running. wait_s waits up to that long for more output or exit.",
             _obj({"process_id": _S, "wait_s": {"type": "integer", "minimum": 0, "maximum": 120}},
                  ["process_id"])),
    ToolSpec("stop_process", "Stop a background process (and its child processes).",
             _obj({"process_id": _S}, ["process_id"])),
    ToolSpec("browser_navigate", "Open a URL in the agent's browser (shared with the user's live view) for pages you "
             "need to interact with; to just read a page, fetch_url is faster. Returns the title and the start of "
             "the page text.", _obj({"url": _S}, ["url"])),
    ToolSpec("browser_click", "Click in the browser: by ref from browser_read's snapshot (most reliable), CSS "
             "selector, visible text, or x/y (page is 1280x800).",
             _obj({"ref": {"type": "string", "description": "e.g. e32"}, "selector": _S, "text": _S,
                   "x": {"type": "number"}, "y": {"type": "number"}}),
             needs_approval=True),
    ToolSpec("browser_type", "Type text into the browser: fills the field with that ref (from the snapshot) or "
             "selector, otherwise types at the focused element. submit presses Enter afterwards.",
             _obj({"text": _S, "ref": _S, "selector": _S, "submit": {"type": "boolean"}}, ["text"]),
             needs_approval=True),
    ToolSpec("browser_read", "Read the current page: 'text' (visible text) or 'snapshot' (the page's elements with "
             "[ref=eN] ids to click or type into). Includes recent console errors.",
             _obj({"mode": {"type": "string", "enum": ["text", "snapshot"]}})),
    ToolSpec("browser_screenshot", "Screenshot the current page: shown to the user, and to you when your model can "
             "see images (check layouts, maps, charts and other visual state).",
             _obj({})),
    ToolSpec("update_plan", "Set the checklist for multi-step work (shown live to the user). Send the full list "
             "each time; mark exactly one item in_progress while working.",
             _obj({"items": {"type": "array", "items": {
                 "type": "object", "properties": {
                     "text": _S, "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
                 "required": ["text", "status"]}}}, ["items"])),
    ToolSpec("memory", "Notes kept for this workspace folder across chats (preferences, project facts, decisions). "
             "read returns them; append adds a line; replace rewrites them all.",
             _obj({"action": {"type": "string", "enum": ["read", "append", "replace"]}, "content": _S},
                  ["action"])),
    ToolSpec("start_task", "Hand a self-contained job to a background task: it runs in its own chat with the same "
             "workspace folder, keeps going when the app is closed and notifies the user when done.",
             _obj({"prompt": {"type": "string", "description": "Complete instructions; the task cannot see this "
                                                               "chat"},
                   "title": _S}, ["prompt"])),
]


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    head, tail = text[:3_000], text[-8_000:]
    return f"{head}\n…[{len(text) - len(head) - len(tail)} chars omitted]…\n{tail}"


def _excerpt(text: str) -> str:
    return text[-EXCERPT_CHARS:]


# ------------------------------- files -------------------------------


async def _list_dir(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    root = state.require_root(ctx.session_id)
    listing = await asyncio.to_thread(files.list_dir, root, a.get("path") or ".")
    rows = [f"{'d' if e.type == 'dir' else 'f'} {e.name}{'/' if e.type == 'dir' else f'  ({e.size} B)'}"
            for e in listing.entries]
    display = FilesDisplay(query=listing.path, truncated=len(rows) > 200,
                           items=[FileItem(path=e.path, dir=e.type == "dir") for e in listing.entries[:200]])
    return ToolOutcome(True, _truncate("\n".join(rows) or "(empty folder)"), display=display)


async def _read_file(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    root = state.require_root(ctx.session_id)
    p = files.resolve(root, a["path"])
    if not p.is_file():
        raise ToolFailure(f"No such file: {a['path']}")
    text = await asyncio.to_thread(files.read_text, p)
    offset = a.get("offset", 1)
    body, shown, total = files.numbered(text, offset, a.get("limit", files.TOOL_READ_LINES))
    rel = files.rel(root, p)
    end = offset - 1 + shown
    more = f"\n… {total - end} more lines (continue with offset={end + 1})" if end < total else ""
    display = FileDisplay(path=rel, excerpt=body[:EXCERPT_CHARS], lines=shown, total_lines=total)
    return ToolOutcome(True, (body or "(empty file)") + more, display=display)


async def _write_file(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    root = state.require_root(ctx.session_id)
    p = files.resolve(root, a["path"])
    if p.is_dir():
        raise ToolFailure(f"{a['path']} is a folder")
    created = not p.exists()
    before = "" if created else await asyncio.to_thread(files.read_text, p)
    await asyncio.to_thread(checkpoints.record, ctx.session_id, ctx.call_id, p)
    await asyncio.to_thread(files.write_atomic, p, a["content"])
    rel = files.rel(root, p)
    diff = files.unified_diff(rel, before, a["content"])
    display = DiffDisplay(path=rel, diff=diff.text, added=diff.added, removed=diff.removed, created=created)
    verb = "Created" if created else "Overwrote"
    return ToolOutcome(True, f"{verb} {rel} ({len(a['content'])} chars, +{diff.added} -{diff.removed}). {DONE}",
                       display=display)


async def _edit_file(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    root = state.require_root(ctx.session_id)
    p = files.resolve(root, a["path"])
    if not p.is_file():
        raise ToolFailure(f"No such file: {a['path']} (use write_file to create it)")
    before = await asyncio.to_thread(files.read_text, p)
    after = files.replace_exact(before, a["old_string"], a["new_string"], bool(a.get("replace_all")))
    await asyncio.to_thread(checkpoints.record, ctx.session_id, ctx.call_id, p)
    await asyncio.to_thread(files.write_atomic, p, after)
    rel = files.rel(root, p)
    diff = files.unified_diff(rel, before, after)
    display = DiffDisplay(path=rel, diff=diff.text, added=diff.added, removed=diff.removed, created=False)
    return ToolOutcome(True, f"Edited {rel} (+{diff.added} -{diff.removed}). {DONE}", display=display)


async def _find_files(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    root = state.require_root(ctx.session_id)
    hits, more = await asyncio.to_thread(files.find, root, a["pattern"], a.get("path") or ".")
    display = FilesDisplay(query=a["pattern"], items=[FileItem(path=h) for h in hits], truncated=more)
    text = "\n".join(hits) or "No files match"
    return ToolOutcome(True, text + ("\n… more results; narrow the pattern" if more else ""), display=display)


async def _search_files(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    root = state.require_root(ctx.session_id)
    matches, more = await asyncio.to_thread(files.search, root, a["pattern"], a.get("path") or ".", a.get("glob"),
                                            bool(a.get("ignore_case")))
    display = FilesDisplay(query=a["pattern"], truncated=more,
                           items=[FileItem(path=m.path, line=m.line, text=m.text[:200]) for m in matches])
    text = "\n".join(f"{m.path}:{m.line}: {m.text}" for m in matches) or "No matches"
    return ToolOutcome(True, _truncate(text + ("\n… more matches; narrow the search" if more else "")),
                       display=display)


# ------------------------------- terminal -------------------------------


def _term_display(term: Terminal, command: str, status: str, text: str) -> TerminalDisplay:
    return TerminalDisplay(terminal_id=term.info.id, command=command, cwd=term.info.cwd, excerpt=_excerpt(text),
                           status=status, exit_code=term.info.exit_code)  # type: ignore[arg-type]


async def _follow(term: Terminal, command: str, ctx: ToolContext, seconds: float) -> bool:
    """Stream the command's output to the tool card until it exits or ``seconds`` pass; True if it exited."""
    deadline = time.monotonic() + seconds
    seen = -1
    while not term.exited.done():
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        await asyncio.wait({term.exited}, timeout=min(0.75, left))
        if term.seq != seen:
            seen = term.seq
            ctx.progress(_term_display(term, command, "running", term.clean_output()))
    return True


async def _start(a: dict[str, Any], ctx: ToolContext) -> tuple[Terminal, str]:
    root = state.require_root(ctx.session_id)
    cwd = files.resolve(root, a.get("cwd") or ".")
    if not cwd.is_dir():
        raise ToolFailure(f"Not a folder: {a.get('cwd')}")
    term = terminals.run_command(ctx.session_id, a["command"], cwd, ctx.call_id)
    ctx.progress(_term_display(term, a["command"], "running", ""))
    return term, a["command"]


def _finished(term: Terminal, command: str) -> ToolOutcome:
    code = term.info.exit_code if term.info.exit_code is not None else -1
    out = term.clean_output(term.read_cursor)
    term.read_cursor = len(term.transcript)
    return ToolOutcome(code == 0, _truncate(f"exit code {code}\n{out}".rstrip()),
                       display=_term_display(term, command, "exited", out))


def _backgrounded(term: Terminal, command: str, note: str) -> ToolOutcome:
    out = term.clean_output(term.read_cursor)
    term.read_cursor = len(term.transcript)
    return ToolOutcome(True, _truncate(f"{note} Process id: {term.info.id} (read_process_output / stop_process)."
                                       f"\nOutput so far:\n{out or '(none yet)'}"),
                       display=_term_display(term, command, "background", out))


async def _run_command(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    term, command = await _start(a, ctx)
    timeout = a.get("timeout_s", 120)
    try:
        exited = await _follow(term, command, ctx, timeout)
    except asyncio.CancelledError:
        term.kill()  # the user pressed Stop: don't leave the command running unseen
        raise
    if exited:
        return _finished(term, command)
    return _backgrounded(term, command, f"Still running after {timeout}s; it keeps running in the background.")


async def _start_process(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    term, command = await _start(a, ctx)
    if await _follow(term, command, ctx, 4):
        return _finished(term, command)
    return _backgrounded(term, command, "Started in the background.")


def _own_process(process_id: str, ctx: ToolContext) -> Terminal:
    term = terminals.get(process_id)
    if term.info.session_id != ctx.session_id:
        raise ToolFailure(f"Process {process_id} belongs to another chat")
    return term


async def _read_process_output(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    term = _own_process(a["process_id"], ctx)
    command = term.info.title
    wait = a.get("wait_s", 0)
    if wait and term.running:
        start_seq = term.seq
        deadline = time.monotonic() + wait
        while term.running and term.seq == start_seq and time.monotonic() < deadline:
            await asyncio.wait({term.exited}, timeout=0.5)
    if not term.running:
        return _finished(term, command)
    out = term.clean_output(term.read_cursor)
    term.read_cursor = len(term.transcript)
    return ToolOutcome(True, _truncate(f"Still running.\n{out or '(no new output)'}"),
                       display=_term_display(term, command, "background", out))


async def _stop_process(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    term = _own_process(a["process_id"], ctx)
    if term.running:
        term.kill()
        await asyncio.wait({term.exited}, timeout=5)
    result = _finished(term, term.info.title)
    result.ok = True
    result.output = f"Stopped process {term.info.id}. {result.output}"
    return result


# ------------------------------- browser -------------------------------


async def _browser_display(ctx: ToolContext, action: str, shot: bool = True) -> BrowserDisplay:
    url, title = await browser.title(ctx.session_id)
    screenshot = await browser.screenshot(ctx.session_id) if shot else None
    return BrowserDisplay(action=action, url=url, title=title, screenshot=screenshot)


async def _browser_navigate(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    await browser.navigate(ctx.session_id, a["url"], agent=True)
    url, title, text, _ = await browser.read(ctx.session_id, "text")
    preview = " ".join(text.split())[:1500]
    display = await _browser_display(ctx, "Opened")
    return ToolOutcome(True, f"Loaded {url}\nTitle: {title}\nStart of the page text:\n{preview}\n"
                             "(browser_read gives the full text or an accessibility snapshot)", display=display)


async def _browser_click(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    await browser.click(ctx.session_id, a.get("selector"), a.get("text"), a.get("x"), a.get("y"), a.get("ref"))
    display = await _browser_display(ctx, "Clicked")
    return ToolOutcome(True, f"Clicked. The page is now {display.url} — {display.title}", display=display)


async def _browser_type(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    await browser.type(ctx.session_id, a["text"], a.get("selector"), bool(a.get("submit")), a.get("ref"))
    display = await _browser_display(ctx, "Typed")
    return ToolOutcome(True, f"Typed {len(a['text'])} chars{' and pressed Enter' if a.get('submit') else ''}. "
                             f"The page is now {display.url} — {display.title}", display=display)


async def _browser_read(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    mode = a.get("mode") or "text"
    url, title, content, truncated = await browser.read(ctx.session_id, mode)
    errors = browser.console_tail(ctx.session_id)
    console = ("\n\nRecent console warnings/errors:\n" + "\n".join(f"[{c.level}] {c.text[:300]}" for c in errors)
               if errors else "")
    note = "\n… page text truncated" if truncated else ""
    display = BrowserDisplay(action="Read", url=url, title=title)
    return ToolOutcome(True, f"{url}\nTitle: {title}\n\n{content}{note}{console}", display=display)


async def _browser_screenshot(_a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    await browser.agent_page(ctx.session_id)
    display = await _browser_display(ctx, "Screenshot")
    if ctx.vision and display.screenshot:
        shot = config.DATA_DIR / display.screenshot.removeprefix("/files/")
        return ToolOutcome(True, f"Screenshot of {display.url} - attached below for you to look at.",
                           display=display, images=[shot])
    return ToolOutcome(True, f"Screenshot saved and shown to the user ({display.url}). Your model cannot see "
                             "images; use browser_read, or view_image to have it described.", display=display)


# ------------------------------- plan / memory / tasks -------------------------------


async def _update_plan(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    raw = a["items"]
    if not isinstance(raw, list) or not raw:
        raise ToolFailure("items must be a non-empty list of {text, status}")
    try:
        items = [PlanItem.model_validate(i) for i in raw][:30]
    except ValueError as exc:
        raise ToolFailure(f"Invalid plan item: {exc}") from exc
    state.set_plan(ctx.session_id, items)
    tasks.plan_changed(ctx.session_id, items)
    done = sum(i.status == "done" for i in items)
    return ToolOutcome(True, f"Plan updated ({done}/{len(items)} done).", display=PlanDisplay(items=items))


async def _memory(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    root = state.require_root(ctx.session_id)
    action = a["action"]
    current = state.read_memory(root)
    if action == "read":
        return ToolOutcome(True, current or "(no notes yet)")
    content = (a.get("content") or "").strip()
    if not content:
        raise ToolFailure(f"memory {action} needs content")
    text = content if action == "replace" else (current.rstrip() + "\n" if current.strip() else "") + f"- {content}"
    checkpoints.record(ctx.session_id, ctx.call_id, state.memory_path(root))
    state.write_memory(root, text + "\n")
    return ToolOutcome(True, f"Memory updated ({len(text)} chars). {DONE}")


async def _start_task(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    if tasks.is_task_session(ctx.session_id):
        raise ToolFailure("A background task cannot start further tasks; do the work here instead")
    task = tasks.create(ctx.session_id, a["prompt"], a.get("title"))
    return ToolOutcome(True, f"Started background task {task.id} ('{task.title}'). It runs on its own; the user is "
                             f"notified when it finishes. {DONE}",
                       display=TaskDisplay(task_id=task.id, title=task.title))


IMPL: dict[str, Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]] = {
    "list_dir": _list_dir, "read_file": _read_file, "write_file": _write_file, "edit_file": _edit_file,
    "find_files": _find_files, "search_files": _search_files, "run_command": _run_command,
    "start_process": _start_process, "read_process_output": _read_process_output, "stop_process": _stop_process,
    "browser_navigate": _browser_navigate, "browser_click": _browser_click, "browser_type": _browser_type,
    "browser_read": _browser_read, "browser_screenshot": _browser_screenshot, "update_plan": _update_plan,
    "memory": _memory, "start_task": _start_task,
}
