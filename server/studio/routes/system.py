from __future__ import annotations

import asyncio

from fastapi import HTTPException

from .. import __version__, capabilities, settings, storage, system
from ..schemas import (Capabilities, HealthResponse, Job, MoveModelsRequest, SecretValue, Settings, SettingsUpdate,
                       StorageInfo, SystemInfo)
from . import StudioRouter

router = StudioRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, version=__version__)


@router.get("/system", response_model=SystemInfo)
async def get_system() -> SystemInfo:
    return await asyncio.to_thread(system.info)


@router.get("/capabilities", response_model=Capabilities)
async def get_capabilities() -> Capabilities:
    return await asyncio.to_thread(capabilities.get)


@router.get("/settings", response_model=Settings)
async def get_settings() -> Settings:
    return settings.masked()


@router.put("/settings", response_model=Settings)
async def put_settings(patch: SettingsUpdate) -> Settings:
    try:
        return settings.masked(settings.update(patch))
    except settings.SettingsError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/settings/secrets/{name}", response_model=SecretValue)
async def get_secret(name: str) -> SecretValue:
    """A stored key or token in the clear, when the user asks to see it (to copy it to another copy of the studio).
    Only pages of the studio itself can read it: other origins get no CORS headers."""
    try:
        return SecretValue(value=settings.secret(name))
    except settings.SettingsError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/storage", response_model=StorageInfo)
async def get_storage() -> StorageInfo:
    return await asyncio.to_thread(storage.info)


@router.post("/storage/models-dir", response_model=Job)
async def move_models(body: MoveModelsRequest) -> Job:
    """Move every model into another folder (e.g. an SSD), or with ``adopt`` use a folder of models as it is;
    runs as a ``storage`` job."""
    try:
        return await asyncio.to_thread(storage.move, body.path, body.adopt)
    except storage.StorageError as exc:
        raise HTTPException(409 if "Wait" in str(exc) else 400, str(exc)) from exc
