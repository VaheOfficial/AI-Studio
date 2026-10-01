"""What differs between operating systems, in one place: process flags, venv layout, executable names, the shell.

The studio runs on Windows (its first home, with NVIDIA GPUs), macOS and Linux. Feature availability that follows
from the machine (GPU, engines, tools) is decided in ``capabilities.py``; this module only answers "how is it done
on this OS"."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
PLATFORM = "windows" if IS_WINDOWS else "macos" if IS_MAC else "linux"
# How the agent's prompt and the UI name this computer
MACHINE = {"windows": "Windows PC", "macos": "Mac", "linux": "Linux PC"}[PLATFORM]

# subprocess creationflags: no console window (Windows); 0 elsewhere, which Popen accepts everywhere
NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NEW_GROUP: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def detached() -> dict[str, Any]:
    """Popen kwargs for a long-lived child that must not get this process's Ctrl+C / terminal signals."""
    if IS_WINDOWS:
        return {"creationflags": NO_WINDOW | _NEW_GROUP}
    return {"start_new_session": True}


def exe(name: str) -> str:
    """``llama-server`` → ``llama-server.exe`` on Windows."""
    return f"{name}.exe" if IS_WINDOWS else name


def venv_python(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe" if IS_WINDOWS else venv / "bin" / "python"


def shell() -> str:
    """The shell for the agent's terminal: PowerShell on Windows, the user's login shell elsewhere."""
    if IS_WINDOWS:
        return shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    preferred = os.environ.get("SHELL")
    if preferred and Path(preferred).exists():
        return preferred
    return shutil.which("zsh") or shutil.which("bash") or "/bin/sh"


def shell_name() -> str:
    """What to call it in prompts and tool descriptions: "PowerShell 7", "zsh", "bash"."""
    if IS_WINDOWS:
        return "PowerShell 7" if Path(shell()).stem.lower() == "pwsh" else "Windows PowerShell"
    return Path(shell()).name
