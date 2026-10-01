"""Static configuration: filesystem layout and well-known endpoints.

User-editable settings live in the database (see ``settings.py``); this module only holds
values that are fixed for the lifetime of the process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent
WORKERS_DIR = SERVER_DIR / "workers"

DATA_DIR = Path(os.environ.get("STUDIO_DATA_DIR", REPO_DIR / "data")).resolve()
MODELS_DIR = DATA_DIR / "models"
ENVS_DIR = DATA_DIR / "envs"
OUTPUTS_DIR = DATA_DIR / "outputs"
VOICES_DIR = DATA_DIR / "voices"
WORKSPACE_DIR = DATA_DIR / "workspace"
UPLOADS_DIR = DATA_DIR / "uploads"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "studio.db"

# Only these top-level folders of the data dir are served under /files.
PUBLIC_SUBDIRS = ("outputs", "voices", "workspace")

HOST = "127.0.0.1"
PORT = int(os.environ.get("STUDIO_PORT", "8765"))  # the desktop app picks a free port
# The built web app (apps/studio/dist): served by this server when present, so the app is one origin without Vite
WEB_DIR = Path(os.environ.get("STUDIO_WEB_DIR", REPO_DIR / "apps" / "studio" / "dist"))
# 5173 is the default dev UI; 8871-8876 are extra dev UI ports (several UIs against separate servers).
CORS_ORIGINS = [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, *range(8871, 8877))]

OLLAMA_URL = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")

# Python used for the uv CLI (the server venv has uv installed as a dependency).
SERVER_PYTHON = Path(sys.executable)
TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu128"
WORKER_PYTHON_VERSION = "3.11"


def uv_env() -> dict[str, str]:
    """Environment for uv subprocesses: keep caches and managed Pythons inside the data dir
    so wheels can be hard-linked into envs on the same drive."""
    env = dict(os.environ)
    env["UV_CACHE_DIR"] = str(CACHE_DIR / "uv")
    env["UV_PYTHON_INSTALL_DIR"] = str(ENVS_DIR / ".python")
    env["UV_LINK_MODE"] = "hardlink"
    env["UV_NO_PROGRESS"] = "1"
    env["NO_COLOR"] = "1"  # plain text — these lines are shown in the UI
    env["PYTHONUTF8"] = "1"
    return env


def ensure_dirs() -> None:
    for d in (DATA_DIR, MODELS_DIR, ENVS_DIR, OUTPUTS_DIR / "images", OUTPUTS_DIR / "audio",
              OUTPUTS_DIR / "music", OUTPUTS_DIR / "videos", VOICES_DIR, WORKSPACE_DIR, UPLOADS_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
