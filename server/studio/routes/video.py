"""Video area: model profiles and generation (text-to-video, image-to-video)."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from .. import video
from ..models import ModelError
from ..schemas import Job
from ..schemas_video import VideoModelProfile, VideoRequest
from . import StudioRouter

router = StudioRouter(prefix="/api/video")


@router.get("/models", response_model=list[VideoModelProfile])
async def video_models() -> list[VideoModelProfile]:
    return await asyncio.to_thread(video.profiles)


@router.post("/generate", response_model=Job)
async def generate(req: VideoRequest) -> Job:
    try:
        return await asyncio.to_thread(video.generate, req)
    except ModelError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
