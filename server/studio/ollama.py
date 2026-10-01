"""Ollama daemon management and REST client (http://127.0.0.1:11434)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx

from . import osenv
from .osenv import NO_WINDOW, detached
from . import config, events
from .localhttp import client
from .runtimes import runtimes
from .textutil import clean_line

_capabilities: dict[str, tuple[list[str], int | None]] = {}  # /api/show: (capabilities, context length)
_start_lock = threading.Lock()


class OllamaError(RuntimeError):
    pass


def _default_exe() -> Path:
    """Where the installer puts it when it isn't on PATH."""
    if osenv.IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if osenv.IS_MAC:
        for candidate in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama",
                          "/Applications/Ollama.app/Contents/Resources/ollama"):
            if Path(candidate).exists():
                return Path(candidate)
    return Path("/usr/local/bin/ollama")


def executable() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    default = _default_exe()
    return default if default.exists() else None


def version() -> str | None:
    """Daemon version, or None when it isn't reachable."""
    try:
        r = client.get(f"{config.OLLAMA_URL}/api/version", timeout=1.5)
        return r.json().get("version") if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def refresh_status() -> tuple[bool, bool, str | None]:
    installed = executable() is not None
    ver = version()
    runtimes.set_ollama_status(installed or ver is not None, ver is not None)
    return installed, ver is not None, ver


def ensure_running(timeout_s: float = 30) -> str:
    """Start ``ollama serve`` if the daemon isn't reachable. Returns the daemon version."""
    ver = version()
    if ver:
        return ver
    with _start_lock:
        ver = version()
        if ver:
            return ver
        exe = executable()
        if exe is None:
            runtimes.set_ollama_status(False, False)
            raise OllamaError("Ollama is not installed (not found on PATH or in its usual install folder). "
                              "Install it from https://ollama.com/download.")
        events.log("info", "ollama", f"Starting `{exe} serve`")
        # Its own hidden console (CREATE_NO_WINDOW) and process group, so the daemon outlives server restarts
        # like the Ollama tray app would. Not DETACHED_PROCESS: without a console, every model runner the daemon
        # spawns gets a new visible console window.
        subprocess.Popen([str(exe), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL,
                         **detached())
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            ver = version()
            if ver:
                events.log("info", "ollama", f"Ollama {ver} is up")
                runtimes.set_ollama_status(True, True)
                return ver
            time.sleep(0.5)
    raise OllamaError(f"Ollama did not respond on {config.OLLAMA_URL} within {timeout_s:.0f}s after `ollama serve`")


def _raise_for(r: httpx.Response, what: str) -> None:
    if r.status_code >= 400:
        try:
            detail = r.json().get("error", r.text)
        except ValueError:
            detail = r.text
        raise OllamaError(f"Ollama {what} failed ({r.status_code}): {detail}")


def tags() -> list[dict[str, Any]]:
    r = client.get(f"{config.OLLAMA_URL}/api/tags", timeout=10)
    _raise_for(r, "list")
    return list(r.json().get("models", []))


def running_models() -> list[str]:
    r = client.get(f"{config.OLLAMA_URL}/api/ps", timeout=5)
    _raise_for(r, "ps")
    return [m["name"] for m in r.json().get("models", [])]


def _show(model: str) -> tuple[list[str], int | None]:
    if model not in _capabilities:
        try:
            r = client.post(f"{config.OLLAMA_URL}/api/show", json={"model": model}, timeout=15)
        except httpx.HTTPError as exc:  # not running: callers treat it like any other Ollama failure
            raise OllamaError(f"Ollama is not reachable: {exc}") from exc
        _raise_for(r, f"show {model}")
        data = r.json()
        info = data.get("model_info") or {}
        ctx = next((v for k, v in info.items() if k.endswith(".context_length") and isinstance(v, int)), None)
        _capabilities[model] = (list(data.get("capabilities", [])), ctx)
    return _capabilities[model]


def capabilities(model: str) -> list[str]:
    """Model capabilities from /api/show, e.g. ["completion", "vision", "tools", "thinking"] (cached)."""
    return _show(model)[0]


def context_length(model: str) -> int | None:
    """The longest context the model was trained for (from /api/show; cached)."""
    return _show(model)[1]


def pull(tag: str, on_progress: Callable[[dict[str, Any]], None], should_stop: Callable[[], bool]) -> None:
    """Stream ``/api/pull``; closing the stream on cancel makes Ollama abort the pull."""
    with client.stream("POST", f"{config.OLLAMA_URL}/api/pull", json={"model": tag, "stream": True},
                       timeout=httpx.Timeout(30, read=600)) as r:
        if r.status_code >= 400:
            r.read()
            _raise_for(r, f"pull {tag}")
        for line in _lines(r):
            if should_stop():
                return
            if "error" in line:
                raise OllamaError(f"Ollama pull {tag} failed: {line['error']}")
            on_progress(line)


def _lines(r: httpx.Response) -> Iterator[dict[str, Any]]:
    for raw in r.iter_lines():
        if raw.strip():
            yield json.loads(raw)


def delete(tag: str) -> None:
    r = client.request("DELETE", f"{config.OLLAMA_URL}/api/delete", json={"model": tag}, timeout=30)
    if r.status_code == 404:
        events.log("warn", "ollama", f"{tag} was already absent from Ollama")
        return
    _raise_for(r, f"delete {tag}")
    _capabilities.pop(tag, None)


def load(tag: str, keep_alive: str = "30m") -> None:
    r = client.post(f"{config.OLLAMA_URL}/api/generate", json={"model": tag, "keep_alive": keep_alive},
                    timeout=httpx.Timeout(10, read=600))
    _raise_for(r, f"load {tag}")


def unload(tag: str) -> None:
    r = client.post(f"{config.OLLAMA_URL}/api/generate", json={"model": tag, "keep_alive": 0}, timeout=60)
    _raise_for(r, f"unload {tag}")


def create_from_dir(name: str, model_dir: Path, quantize: str, on_line: Callable[[str], None],
                    on_proc: Callable[[subprocess.Popen[str]], None]) -> None:
    """``ollama create <name> -q <quantize>`` from a safetensors directory via a Modelfile."""
    exe = executable()
    if exe is None:
        raise OllamaError("Ollama is not installed; cannot import safetensors")
    modelfile = model_dir / "Modelfile"
    modelfile.write_text(f"FROM {model_dir}\n", encoding="utf-8")
    proc = subprocess.Popen([str(exe), "create", name, "-q", quantize, "-f", str(modelfile)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=NO_WINDOW)
    on_proc(proc)
    tail: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = clean_line(raw)  # the CLI redraws progress with \r, spinners and escape codes
        if line:
            tail = (tail + [line])[-10:]
            on_line(line)
    if proc.wait() != 0:
        raise OllamaError(f"`ollama create {name}` failed (exit {proc.returncode}):\n" + "\n".join(tail))
