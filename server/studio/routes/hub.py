"""Model hub: search Hugging Face / Ollama / LM Studio's catalog, repo detail with variants, variant installs,
and the local text backends' status."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Query

from .. import lmstudio, ollama
from ..hub import backends, huggingface, install, ollama_library
from ..hub.huggingface import HubError
from ..models import ModelError
from ..schemas import Job
from ..schemas_hub import HubCatalog, HubInstallRequest, HubRepo, HubSearchResult, HubSort, HubSource, LocalBackend
from . import StudioRouter

router = StudioRouter(prefix="/api/hub")

HUB_TASKS = ("text-generation", "image-text-to-text", "text-to-image", "image-to-image", "text-to-speech",
             "automatic-speech-recognition", "text-to-audio", "audio-to-audio")


async def _run(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except (HubError, ModelError) as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except (ollama.OllamaError, lmstudio.LMStudioError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/search", response_model=list[HubSearchResult])
async def search(catalog: HubCatalog = "hf", q: str = "", task: str | None = None, sort: HubSort = "trending",
                 gguf: bool = False) -> list[HubSearchResult]:
    if task and task not in HUB_TASKS:
        raise HTTPException(400, f"Unknown task '{task}'. Known: {', '.join(HUB_TASKS)}")
    if catalog == "ollama":
        return await _run(ollama_library.search, q.strip())
    return await _run(huggingface.search, q.strip(), task, sort, gguf, catalog == "lmstudio")


@router.get("/repo", response_model=HubRepo)
async def repo(source: HubSource, id: str = Query(min_length=1)) -> HubRepo:
    if source == "ollama":
        return await _run(ollama_library.repo, id)
    return await _run(huggingface.repo, id)


@router.post("/install", response_model=Job)
async def install_variant(body: HubInstallRequest) -> Job:
    return await _run(install.install, body)


@router.get("/backends", response_model=list[LocalBackend])
async def local_backends() -> list[LocalBackend]:
    return await _run(backends.local_backends)
