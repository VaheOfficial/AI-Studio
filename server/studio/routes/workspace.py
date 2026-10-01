"""Agent workspace REST routes (docs/api/workspace.md). Live updates (terminal output, file changes, browser
frames, task status) arrive over ``/api/ws``; these routes serve on-demand reads and user actions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from fastapi.responses import FileResponse
from fastapi import File, HTTPException, Query, Response, UploadFile

from .. import db
from ..schemas import AgentSession
from ..schemas_workspace import (AgentTask, BrowserSnapshot, BrowserState, CreateTaskRequest, FolderListing, FsFile,
                                 FsListing, HistoryRequest, MakeFolderRequest, NavigateRequest, SetRootRequest,
                                 TakeoverRequest, TerminalBuffer, UploadResult, WorkspaceState, WriteFileRequest)
from ..workspace import files, state
from ..workspace.browser import browser
from ..workspace.state import WorkspaceError
from ..workspace.tasks import tasks
from ..workspace.terminal import terminals
from . import StudioRouter

router = StudioRouter(prefix="/api/workspace")
T = TypeVar("T")
UPLOAD_LIMIT = 50 * 1024 * 1024


def _session(session_id: str) -> AgentSession:
    s = db.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"Session '{session_id}' not found")
    return s


async def _call(fn: Callable[..., T], *args: Any) -> T:
    """Run blocking filesystem work off the loop; workspace problems become 400s."""
    try:
        return await asyncio.to_thread(fn, *args)
    except WorkspaceError as exc:
        raise HTTPException(400, str(exc)) from exc


async def _guard(coro: Any) -> Any:
    try:
        return await coro
    except WorkspaceError as exc:
        raise HTTPException(400, str(exc)) from exc


# ------------------------------- folder -------------------------------


@router.get("/sessions/{session_id}", response_model=WorkspaceState)
async def get_workspace(session_id: str) -> WorkspaceState:
    _session(session_id)
    return state.get(session_id)


@router.put("/sessions/{session_id}", response_model=WorkspaceState)
async def set_workspace_root(session_id: str, body: SetRootRequest) -> WorkspaceState:
    _session(session_id)
    result = await _call(state.set_root, session_id, body.root)
    files.watcher.sync()
    return result


@router.get("/browse", response_model=FolderListing)
async def browse(path: str = "") -> FolderListing:
    return await _call(files.browse, path)


@router.post("/browse/mkdir", response_model=FolderListing)
async def make_folder(body: MakeFolderRequest) -> FolderListing:
    return await _call(files.make_folder, body.parent, body.name)


# ------------------------------- files -------------------------------


def _root(session_id: str) -> Path:
    _session(session_id)
    try:
        return state.require_root(session_id)
    except WorkspaceError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/sessions/{session_id}/fs", response_model=FsListing)
async def list_files(session_id: str, path: str = ".") -> FsListing:
    return await _call(files.list_dir, _root(session_id), path)


@router.get("/sessions/{session_id}/fs/file", response_model=FsFile)
async def read_file(session_id: str, path: str = Query(...)) -> FsFile:
    return await _call(files.view_file, _root(session_id), path)


@router.get("/sessions/{session_id}/fs/download")
async def download_file(session_id: str, path: str = Query(...)) -> FileResponse:
    """A file from the chat's workspace folder as a download (documents the agent made, for example)."""
    target = await _call(files.resolve, _root(session_id), path)
    if not target.is_file():
        raise HTTPException(404, f"{path} is not a file")
    return FileResponse(target, filename=target.name)


@router.put("/sessions/{session_id}/fs/file", response_model=FsFile)
async def write_file(session_id: str, body: WriteFileRequest) -> FsFile:
    return await _call(files.save_file, _root(session_id), body.path, body.content)


@router.post("/sessions/{session_id}/upload", response_model=UploadResult)
async def upload(session_id: str, files_: list[UploadFile] = File(..., alias="files")) -> UploadResult:
    root = _root(session_id)
    paths = []
    for f in files_:
        data = await f.read(UPLOAD_LIMIT + 1)
        if len(data) > UPLOAD_LIMIT:
            raise HTTPException(413, f"{f.filename} is larger than 50 MB")
        paths.append(await _call(files.save_upload, root, f.filename or "file", data))
    return UploadResult(paths=paths)


# ------------------------------- terminals -------------------------------


@router.get("/sessions/{session_id}/terminals", response_model=list[TerminalBuffer])
async def list_terminals(session_id: str) -> list[TerminalBuffer]:
    _session(session_id)
    return [t.buffer() for t in terminals.for_session(session_id)]


# ------------------------------- browser -------------------------------


@router.get("/sessions/{session_id}/browser", response_model=BrowserSnapshot)
async def browser_snapshot(session_id: str) -> BrowserSnapshot:
    _session(session_id)
    return await browser.snapshot(session_id)


@router.post("/sessions/{session_id}/browser/navigate", response_model=BrowserState)
async def browser_navigate(session_id: str, body: NavigateRequest) -> BrowserState:
    _session(session_id)
    return await _guard(browser.navigate(session_id, body.url))


@router.post("/sessions/{session_id}/browser/history", response_model=BrowserState)
async def browser_history(session_id: str, body: HistoryRequest) -> BrowserState:
    _session(session_id)
    return await _guard(browser.history(session_id, body.action))


@router.post("/sessions/{session_id}/browser/takeover", response_model=BrowserState)
async def browser_takeover(session_id: str, body: TakeoverRequest) -> BrowserState:
    _session(session_id)
    return await _guard(browser.set_takeover(session_id, body.on))


@router.post("/sessions/{session_id}/browser/close", status_code=204)
async def browser_close(session_id: str) -> Response:
    _session(session_id)
    await browser.close(session_id)
    return Response(status_code=204)


# ------------------------------- tasks -------------------------------


@router.get("/tasks", response_model=list[AgentTask])
async def list_tasks() -> list[AgentTask]:
    return tasks.list()


@router.post("/tasks", response_model=AgentTask)
async def create_task(body: CreateTaskRequest) -> AgentTask:
    _session(body.origin_session_id)
    try:
        return tasks.create(body.origin_session_id, body.prompt, body.title)
    except WorkspaceError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/tasks/{task_id}/cancel", response_model=AgentTask)
async def cancel_task(task_id: str) -> AgentTask:
    return await _guard(tasks.cancel(task_id))


@router.post("/tasks/{task_id}/retry", response_model=AgentTask)
async def retry_task(task_id: str) -> AgentTask:
    try:
        return tasks.retry(task_id)
    except WorkspaceError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str) -> Response:
    await _guard(tasks.delete(task_id))
    return Response(status_code=204)
