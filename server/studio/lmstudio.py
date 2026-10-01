"""LM Studio integration: detect the app and its ``lms`` CLI, start its local server, list / load / unload models,
and serve chat through its OpenAI-compatible endpoint (``http://127.0.0.1:1234/v1``).

Models live in LM Studio's own library (``~/.lmstudio/models/<publisher>/<repo>/<file>.gguf``); the hub can
download straight into it so LM Studio sees them too."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from . import osenv
from .osenv import NO_WINDOW
from . import events
from .localhttp import client
from .runtimes import runtimes
from .runtimes.manager import ExternalStatus
from .schemas import InstalledModel

HOME = Path.home() / ".lmstudio"
PORT = 1234
API = f"http://127.0.0.1:{PORT}"
INSTALL_URL = "https://lmstudio.ai/download"
_CLI_TIMEOUT_S = 600  # `lms load` returns once the weights are in memory


class LMStudioError(RuntimeError):
    pass


def lms_exe() -> Path | None:
    """The ``lms`` CLI: on PATH, bootstrapped into ~/.lmstudio/bin, or the copy bundled inside the app."""
    found = shutil.which("lms")
    if found:
        return Path(found)
    app = app_exe()
    bundled = app.parent / "resources" / "app" / ".webpack" / "lms.exe" if app and osenv.IS_WINDOWS else None
    for candidate in (HOME / "bin" / osenv.exe("lms"), bundled):
        if candidate and candidate.exists():
            return candidate
    return None


def app_exe() -> Path | None:
    if osenv.IS_MAC:
        mac = Path("/Applications/LM Studio.app")
        return mac if mac.exists() else None
    if not osenv.IS_WINDOWS:
        return None
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
        for sub in (("Programs", "LM Studio"), ("LM Studio",), ("Programs", "lm-studio")):
            exe = Path(base, *sub, "LM Studio.exe")
            if base and exe.exists():
                return exe
    return None


def installed() -> bool:
    return lms_exe() is not None or app_exe() is not None


def set_up() -> bool:
    """LM Studio's first launch creates ~/.lmstudio and registers the install; until then `lms` can't start it."""
    return HOME.is_dir()


def models_dir() -> Path:
    """LM Studio's download folder (configurable in the app; stored in ``~/.lmstudio/settings.json``)."""
    try:
        folder = json.loads((HOME / "settings.json").read_text(encoding="utf-8")).get("downloadsFolder")
    except (OSError, ValueError):
        folder = None
    return Path(folder) if folder else HOME / "models"


# ------------------------------ status ------------------------------

_state_lock = threading.Lock()
_running = False
_loaded: str | None = None  # studio model id we last loaded (LM Studio can hold several)
_version: str | None = None


def status() -> ExternalStatus:
    return ExternalStatus(installed=installed(), running=_running, port=PORT if _running else None,
                          loaded_model=_loaded if _running else None)


_REACHABLE_TTL_S = 2.0  # one system tick: the snapshot's system info and model sync share a probe
_reachable_at = (0.0, False)


def reachable() -> bool:
    # Short connect timeout: a local server accepts in milliseconds, while Windows retries a refused
    # localhost connect for ~1 s — and this probe runs on every system tick.
    global _reachable_at
    checked, ok = _reachable_at
    if time.monotonic() - checked < _REACHABLE_TTL_S:
        return ok
    try:
        ok = client.get(f"{API}/v1/models", timeout=httpx.Timeout(0.8, connect=0.2)).status_code == 200
    except httpx.HTTPError:
        ok = False
    _reachable_at = (time.monotonic(), ok)
    return ok


def refresh_status() -> bool:
    """Probe the local server (cheap no-op when LM Studio isn't installed); publishes changes."""
    global _running
    running = installed() and reachable()
    with _state_lock:
        changed, _running = running != _running, running
    if changed:
        runtimes.publish("lmstudio")
    return running


def version() -> str | None:
    """The app's version, from its bundled package.json (the CLI only reports a commit hash)."""
    global _version
    app = app_exe()
    if _version is None and app:
        try:
            _version = json.loads((app.parent / "resources" / "app" / "package.json").read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            return None
    return _version


def _lms(args: list[str], timeout: float = 60) -> str:
    exe = lms_exe()
    if exe is None:
        raise LMStudioError(f"LM Studio's `lms` CLI was not found. Install LM Studio from {INSTALL_URL} and open "
                            "it once (it installs `lms` into ~/.lmstudio/bin).")
    try:
        proc = subprocess.run([str(exe), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise LMStudioError(f"`lms {' '.join(args)}` timed out after {timeout:.0f}s") from exc
    if proc.returncode != 0:
        raise LMStudioError(f"`lms {' '.join(args)}` failed: {(proc.stderr or proc.stdout).strip()[-600:]}")
    return proc.stdout


def ensure_server(timeout_s: float = 60) -> None:
    """Start LM Studio's local server (`lms server start`) if it isn't answering."""
    if refresh_status():
        return
    if not set_up():
        raise LMStudioError("LM Studio is installed but has never been opened. Open it once so it can finish setting "
                            "itself up, then start the server again.")
    global _reachable_at
    events.log("info", "lmstudio", "Starting the LM Studio server (lms server start)")
    _lms(["server", "start", "--port", str(PORT)], timeout=timeout_s)
    _reachable_at = (0.0, False)  # probe afresh instead of reusing the pre-start answer
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if refresh_status():
            return
        time.sleep(0.5)
    raise LMStudioError(f"LM Studio's server did not answer on {API} within {timeout_s:.0f}s")


# ------------------------------ library ------------------------------


def model_key(m: InstalledModel) -> str:
    """The library path `lms load` takes: ``<publisher>/<repo>/<file>.gguf`` relative to the models dir."""
    main = next((f for f in sorted(m.files or []) if f.lower().endswith(".gguf") and "mmproj" not in f.lower()),
                None)
    if main is None:
        raise LMStudioError(f"{m.name} has no GGUF file recorded")
    return (Path(m.path) / main).relative_to(models_dir()).as_posix()


def list_downloaded() -> list[dict[str, Any]]:
    """LLMs in LM Studio's library (`lms ls --json`)."""
    data = json.loads(_lms(["ls", "--json"]) or "[]")
    return [d for d in data if d.get("type", "llm") in ("llm", "vlm") and d.get("path")]


def list_loaded() -> set[str]:
    """Identifiers of models LM Studio currently holds in memory (`lms ps --json`)."""
    data = json.loads(_lms(["ps", "--json"]) or "[]")
    return {str(d.get("identifier") or d.get("modelKey")) for d in data}


def load(m: InstalledModel, ctx_size: int) -> None:
    global _loaded
    ensure_server()
    if m.id in list_loaded():
        _loaded = m.id
        return
    events.log("info", "lmstudio", f"Loading {m.name} in LM Studio")
    # No --gpu: LM Studio picks the offload ratio that fits the VRAM left after _make_room.
    _lms(["load", model_key(m), "--identifier", m.id, "--context-length", str(ctx_size), "--yes"],
         timeout=_CLI_TIMEOUT_S)
    _loaded = m.id
    runtimes.publish("lmstudio")


def unload(m: InstalledModel) -> None:
    global _loaded
    if not reachable():
        return
    if m.id in list_loaded():
        _lms(["unload", m.id])
    if _loaded == m.id:
        _loaded = None
    runtimes.publish("lmstudio")


def unload_all() -> None:
    global _loaded
    if reachable():
        _lms(["unload", "--all"])
    _loaded = None
    runtimes.publish("lmstudio")


runtimes.register_external("lmstudio", status)
