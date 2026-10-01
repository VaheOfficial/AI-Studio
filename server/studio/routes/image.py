"""Image area: model profiles, generation / editing and gallery stars."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, Response

from .. import imaging
from ..models import ModelError
from ..schemas import Job
from ..schemas_image import ImageGenerateRequest, ImageModelProfile, StarRequest
from . import StudioRouter

router = StudioRouter(prefix="/api/image")


@router.get("/models", response_model=list[ImageModelProfile])
async def image_models() -> list[ImageModelProfile]:
    return await imaging.profiles()


@router.post("/generate", response_model=Job)
async def image_generate(req: ImageGenerateRequest) -> Job:
    try:
        # Resolving edit inputs writes files and local checks read model headers: keep them off the event loop
        return await asyncio.to_thread(imaging.generate, req)
    except ModelError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/stars", response_model=list[str])
async def list_stars() -> list[str]:
    return imaging.stars()


@router.put("/stars/{output_id}", status_code=204)
async def set_star(output_id: str, body: StarRequest) -> Response:
    try:
        imaging.set_star(output_id, body.starred)
    except ModelError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return Response(status_code=204)
