"""Python sessions for the agent's ``run_python``: one ``workers/py_kernel.py`` process per chat, in the ``python``
env, working in the chat's workspace folder (or a scratch folder under outputs when none is chosen). Variables
persist between calls; a call that runs past its timeout kills the process (the next call starts fresh). Idle
sessions are closed after a while."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from ..osenv import NO_WINDOW
from .. import config
from ..proc import bind_to_server_lifetime, kill_tree
from ..runtimes import envs
from ..workspace import state as workspace_state

ENV = "python"
IDLE_S = 30 * 60
MARK = "\x1e"


class KernelError(RuntimeError):
    """User-facing reason code could not run."""


@dataclass
class Result:
    output: str
    error: str | None
    images: list[str]  # absolute PNG paths
    table: dict | None
    files: list[str]  # absolute paths created or changed
    cwd: Path


@dataclass
class _Kernel:
    proc: subprocess.Popen[str]
    cwd: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    used: float = field(default_factory=time.monotonic)


_kernels: dict[str, _Kernel] = {}
_guard = threading.Lock()


def scratch_dir(session_id: str) -> Path:
    return config.OUTPUTS_DIR / "python" / session_id


def workdir(session_id: str) -> Path:
    root = workspace_state.get(session_id).root
    if root and Path(root).is_dir():
        return Path(root)
    d = scratch_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_url(session_id: str, path: Path) -> str | None:
    """Where the UI downloads a file: /files for the outputs folder, the workspace download route otherwise."""
    try:
        rel = path.resolve().relative_to(config.DATA_DIR.resolve())
        if rel.parts and rel.parts[0] in config.PUBLIC_SUBDIRS:
            return "/files/" + quote(rel.as_posix())
    except ValueError:
        pass
    root = workspace_state.get(session_id).root
    if root:
        try:
            rel = path.resolve().relative_to(Path(root).resolve())
            return f"/api/workspace/sessions/{session_id}/fs/download?path={quote(rel.as_posix())}"
        except ValueError:
            return None
    return None


def _start(session_id: str, cwd: Path) -> _Kernel:
    py = envs.env_python(ENV)
    proc = subprocess.Popen(
        [str(py), "-u", str(config.WORKERS_DIR / "py_kernel.py")], cwd=cwd, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=NO_WINDOW, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    bind_to_server_lifetime(proc)
    return _Kernel(proc=proc, cwd=cwd)


def _kernel(session_id: str) -> _Kernel:
    cwd = workdir(session_id)
    with _guard:
        k = _kernels.get(session_id)
        if k is not None and (k.proc.poll() is not None or k.cwd != cwd):  # died, or the chat's folder changed
            kill_tree(k.proc)
            k = None
        if k is None:
            k = _kernels[session_id] = _start(session_id, cwd)
        return k


def _run_blocking(session_id: str, code: str, timeout_s: float) -> Result:
    if not envs.is_ready(ENV):
        raise KernelError("The Python tools environment isn't installed yet")
    k = _kernel(session_id)
    with k.lock:
        k.used = time.monotonic()
        chart_dir = scratch_dir(session_id) / "_charts"
        assert k.proc.stdin is not None and k.proc.stdout is not None
        k.proc.stdin.write(json.dumps({"code": code, "chart_dir": str(chart_dir)}) + "\n")
        k.proc.stdin.flush()
        reply: dict | None = None
        noise: list[str] = []
        timer = threading.Timer(timeout_s, lambda: kill_tree(k.proc))
        timer.start()
        try:
            for line in k.proc.stdout:
                if line.startswith(MARK):
                    reply = json.loads(line[1:])
                    break
                noise.append(line)  # output that bypassed Python's stdout (C libraries, subprocesses)
        finally:
            timer.cancel()
        if reply is None:
            with _guard:
                _kernels.pop(session_id, None)
            if k.proc.poll() is None:
                kill_tree(k.proc)
            tail = "".join(noise)[-2000:]
            if time.monotonic() - k.used >= timeout_s - 0.5:
                raise KernelError(f"Timed out after {timeout_s:.0f} s; the Python session was restarted, so earlier "
                                  "variables are gone. Split the work or raise timeout_s." + (f"\n{tail}" if tail else ""))
            raise KernelError("The Python session crashed and was restarted (variables are gone)."
                              + (f"\n{tail}" if tail else ""))
        k.used = time.monotonic()
    output = reply["output"]
    if noise:
        output = "".join(noise)[-4000:] + output
    return Result(output=output, error=reply["error"], images=reply["images"], table=reply["table"],
                  files=reply["files"], cwd=k.cwd)


async def run(session_id: str, code: str, timeout_s: float) -> Result:
    return await asyncio.to_thread(_run_blocking, session_id, code, timeout_s)


def reset(session_id: str) -> bool:
    with _guard:
        k = _kernels.pop(session_id, None)
    if k is None:
        return False
    kill_tree(k.proc)
    return True


def close_idle() -> None:
    now = time.monotonic()
    with _guard:
        idle = [sid for sid, k in _kernels.items() if now - k.used > IDLE_S and not k.lock.locked()]
        stale = [_kernels.pop(sid) for sid in idle]
    for k in stale:
        kill_tree(k.proc)


def stop_all() -> None:
    with _guard:
        stale = list(_kernels.values())
        _kernels.clear()
    for k in stale:
        kill_tree(k.proc)
