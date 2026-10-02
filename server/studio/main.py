"""FastAPI app factory: routers, CORS, static files and startup/shutdown wiring."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from . import (__version__, automations, config, connectors, db, events, imaging, library, memories, ollama, openrouter_catalog, openrouter_usage, storage,
               workspace)
from .agent import agent
from .agent import pykernel
from .events import bus
from .game import store as game_store
from .game.master import games
from .models import models
from .routes import agent as agent_routes
from .routes import audio_tools as audio_tools_routes
from .routes import audiobook as audiobook_routes
from .routes import automations as automation_routes
from .routes import connectors as connector_routes
from .routes import dub as dub_routes
from .routes import generate as generate_routes
from .routes import hub as hub_routes
from .routes import image as image_routes
from .routes import models as model_routes
from .routes import openrouter as openrouter_routes
from .routes import system as system_routes
from .routes import voice as voice_routes
from .routes import workspace as workspace_routes
from .routes import game as game_routes
from .routes import video as video_routes
from .routes import ws as ws_routes
from .runtimes import runtimes
from .voice import store as voice_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs every request at INFO; the Ollama health poll alone adds a line every ~2 s
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class PublicDataFiles(StaticFiles):
    """Serve only the public parts of the data dir (never studio.db, envs or model weights)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        top = path.replace("\\", "/").lstrip("/").split("/", 1)[0]
        if top not in config.PUBLIC_SUBDIRS:
            raise HTTPException(404, "Not found")
        return await super().get_response(path, scope)


def _bring_up_ollama() -> None:
    try:
        ollama.ensure_running()
        models.sync_ollama()
    except ollama.OllamaError as exc:
        events.log("warn", "ollama", str(exc))
    ollama.refresh_status()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    config.ensure_dirs()
    db.init()
    storage.apply()  # a moved models folder (Settings → Storage)
    library.backfill()  # every model's folder says what it holds, so another copy of the studio can pick it up
    openrouter_catalog.init()
    openrouter_usage.init()
    imaging.init()
    workspace.init()
    voice_store.init()
    game_store.init()
    memories.init()
    automations.init()
    connectors.init()
    bus.bind_loop(asyncio.get_running_loop())
    workspace.start(agent)
    automations.runner.start(agent)
    connectors.manager.start_all()
    psutil.cpu_percent(interval=None)  # prime: the first reading is always 0
    for m in db.list_installed():
        # Workers don't survive a restart, so nothing non-Ollama can still be loaded.
        if m.runtime != "ollama" and m.status in ("loaded", "loading"):
            db.set_installed_status(m.id, "ready")
    threading.Thread(target=_bring_up_ollama, name="ollama-start", daemon=True).start()
    events.log("info", "server", f"Grom AI Studio server {__version__} started; data dir {config.DATA_DIR}")
    yield
    ws_routes.ticker.stop()
    await automations.runner.shutdown()
    await connectors.manager.shutdown()
    await asyncio.to_thread(pykernel.stop_all)
    await workspace.shutdown()  # first: background tasks must see a shutdown, not a user stop
    await agent.shutdown()  # running turns save their final state (pending approvals -> denied)
    await games.shutdown()
    await asyncio.to_thread(runtimes.stop_all)


def create_app() -> FastAPI:
    app = FastAPI(title="Grom AI Studio", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(OSError)
    async def storage_error(_request: Request, exc: OSError) -> JSONResponse:
        events.log("error", "server", f"I/O error: {exc}")
        return JSONResponse(status_code=503, content={
            "detail": f"Storage error ({exc}). If the data drive was disconnected, reconnect it and retry."})

    for module in (system_routes, model_routes, hub_routes, generate_routes, image_routes, agent_routes,
                   openrouter_routes, voice_routes, workspace_routes, dub_routes, audiobook_routes,
                   audio_tools_routes, game_routes, video_routes, automation_routes,
                   connector_routes, ws_routes):
        app.include_router(module.router)
    config.ensure_dirs()
    app.mount("/files", PublicDataFiles(directory=config.DATA_DIR, check_dir=False), name="files")
    _serve_web(app)
    return app


def _serve_web(app: FastAPI) -> None:
    """Serve the built web app (apps/studio/dist) from this server, so the desktop app and a plain
    ``http://127.0.0.1:<port>`` work without the Vite dev server. Unknown paths get index.html (client routing)."""
    web = config.WEB_DIR
    index = web / "index.html"
    if not index.is_file():
        return
    root = web.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str) -> FileResponse:
        if path.startswith(("api/", "files/")):
            raise HTTPException(404, "Not found")
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            return FileResponse(target)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
