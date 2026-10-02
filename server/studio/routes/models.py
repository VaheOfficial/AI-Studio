"""Catalog, installed models, jobs and runtimes."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, Response

from .. import catalog, db, llamacpp, lmstudio, ollama
from ..jobs import JobContext, JobError, jobs
from ..models import ModelError, models
from ..runtimes import RUNTIMES, WorkerError, runtimes
from ..runtimes import envs
from ..schemas import CatalogEntry, InstalledModel, Job, ModelPatch, RuntimeInfo
from . import StudioRouter

router = StudioRouter(prefix="/api")


def _http(exc: ModelError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/catalog", response_model=list[CatalogEntry])
async def get_catalog() -> list[CatalogEntry]:
    return await asyncio.to_thread(catalog.entries)


@router.get("/models", response_model=list[InstalledModel])
async def list_models() -> list[InstalledModel]:
    return await asyncio.to_thread(models.list)


@router.post("/models/{catalog_id}/install", response_model=Job)
async def install_model(catalog_id: str) -> Job:
    try:
        return await asyncio.to_thread(models.install, catalog_id)
    except ModelError as exc:
        raise _http(exc) from exc
    except ollama.OllamaError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(model_id: str) -> Response:
    try:
        await asyncio.to_thread(models.delete, model_id)
    except ModelError as exc:
        raise _http(exc) from exc
    except ollama.OllamaError as exc:
        raise HTTPException(502, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Could not delete model files: {exc}") from exc
    return Response(status_code=204)


@router.patch("/models/{model_id}", response_model=InstalledModel)
async def patch_model(model_id: str, body: ModelPatch) -> InstalledModel:
    """Change how an installed model is loaded (a loaded model is unloaded; the change applies at its next load)."""
    try:
        if body.text_encoder is not None:
            return await asyncio.to_thread(models.set_text_encoder, model_id, body.text_encoder)
        return await asyncio.to_thread(models.get, model_id)
    except ModelError as exc:
        raise _http(exc) from exc
    except (WorkerError, ollama.OllamaError) as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/models/{model_id}/load", response_model=InstalledModel)
async def load_model(model_id: str) -> InstalledModel:
    try:
        return await asyncio.to_thread(models.load, model_id)
    except ModelError as exc:
        raise _http(exc) from exc


@router.post("/models/{model_id}/unload", response_model=InstalledModel)
async def unload_model(model_id: str) -> InstalledModel:
    try:
        return await asyncio.to_thread(models.unload, model_id)
    except ModelError as exc:
        raise _http(exc) from exc
    except (WorkerError, ollama.OllamaError) as exc:
        raise HTTPException(502, str(exc)) from exc


# --------------------------------- jobs ---------------------------------


@router.get("/jobs", response_model=list[Job])
async def list_jobs() -> list[Job]:
    return jobs.list()


@router.post("/jobs/{job_id}/cancel", response_model=Job)
async def cancel_job(job_id: str) -> Job:
    job = jobs.cancel(job_id)
    if job is None:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def dismiss_job(job_id: str) -> Response:
    try:
        if not jobs.dismiss(job_id):
            raise HTTPException(404, f"Job '{job_id}' not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)


# ------------------------------- runtimes -------------------------------


def _runtime(runtime_id: str) -> None:
    if runtime_id not in RUNTIMES:
        raise HTTPException(404, f"Unknown runtime '{runtime_id}'. Known: {', '.join(RUNTIMES)}")


@router.get("/runtimes", response_model=list[RuntimeInfo])
async def list_runtimes() -> list[RuntimeInfo]:
    await asyncio.to_thread(ollama.refresh_status)
    return runtimes.all_info()


@router.post("/runtimes/{runtime_id}/install", response_model=Job)
async def install_runtime(runtime_id: str) -> Job:
    _runtime(runtime_id)
    rdef = RUNTIMES[runtime_id]
    if rdef.id == "remote":
        raise HTTPException(400, "The remote runtime needs no local install; configure API keys in Settings")
    if rdef.id == "ollama":
        return jobs.submit("env", "Start Ollama", _start_ollama, ref="ollama")
    if rdef.id == "llamacpp":
        job = llamacpp.ensure_installed_job(force=True)
        assert job is not None
        return job
    if rdef.id == "lmstudio":
        if not lmstudio.installed():
            raise HTTPException(409, f"LM Studio isn't installed on this machine; get it from {lmstudio.INSTALL_URL}")
        return jobs.submit("env", "Start LM Studio server", _start_lmstudio, ref="lmstudio")
    assert rdef.env
    job = envs.ensure_env_job(rdef.env, runtime_id, force=True)
    assert job is not None
    return job


def _start_ollama(ctx: JobContext) -> None:
    ctx.update(message="Starting the Ollama daemon…")
    try:
        version = ollama.ensure_running()
    except ollama.OllamaError as exc:
        raise JobError(str(exc)) from exc
    ollama.refresh_status()
    ctx.update(message=f"Ollama {version} running")


def _start_lmstudio(ctx: JobContext) -> None:
    ctx.update(message="Starting LM Studio's local server…")
    try:
        lmstudio.ensure_server()
    except lmstudio.LMStudioError as exc:
        raise JobError(str(exc)) from exc
    ctx.update(message=f"LM Studio server running on {lmstudio.API}")


def _unload_lmstudio() -> RuntimeInfo:
    """Everything LM Studio holds in memory, including models loaded from its own app."""
    lmstudio.unload_all()
    for m in db.list_installed():
        if m.runtime == "lmstudio" and m.status == "loaded":
            models.set_status(m.id, "ready")
    return runtimes.info("lmstudio")


@router.post("/runtimes/{runtime_id}/stop", response_model=RuntimeInfo)
async def stop_runtime(runtime_id: str) -> RuntimeInfo:
    _runtime(runtime_id)
    if runtime_id in ("ollama", "remote"):
        raise HTTPException(400, f"'{runtime_id}' has no worker process to stop; unload its models instead")
    if runtime_id == "llamacpp":
        await asyncio.to_thread(llamacpp.server.stop)
        return runtimes.info("llamacpp")
    if runtime_id == "lmstudio":
        try:
            return await asyncio.to_thread(_unload_lmstudio)
        except lmstudio.LMStudioError as exc:
            raise HTTPException(502, str(exc)) from exc
    return await asyncio.to_thread(runtimes.stop, runtime_id)
