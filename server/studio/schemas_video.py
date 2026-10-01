"""Video area contract: mirrors ``apps/studio/src/api/contracts/video.ts``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VideoMode = Literal["t2v", "i2v"]
"""t2v: from a prompt; i2v: the prompt animates a start image."""

VideoDecoder = Literal["vae", "diffusion"]
"""How LTX-2.5 turns latents into frames: the VAE (fast) or its diffusion decoder (sharper, slower)."""

MAX_SIDE = 3840  # 4K UHD
MAX_SECONDS = 120


class VideoModelProfile(BaseModel):
    """What one installed video model can do. Nothing here is a hard preset: any size (snapped to ``size_step``) and
    length up to ``max_seconds`` can be requested; these fields describe what is native, what is slower and what
    each option does, so the UI can estimate and warn instead of refusing."""

    model_id: str
    name: str
    family: Literal["wan", "ltx2"]
    location: Literal["local", "cloud"]
    modes: list[VideoMode]
    audio: bool  # generates a soundtrack with the picture
    native_width: int  # the size the model was trained at (landscape; portrait swaps them)
    native_height: int
    size_step: int  # width/height are rounded to a multiple of this
    max_side: int
    fps: float
    default_seconds: float
    segment_seconds: float  # longest single pass; longer clips continue from the last frame, segment by segment
    max_seconds: float
    auto_duration: bool  # can pick the length itself (LTX-2.5's duration head)
    upscaler: bool  # two-stage: generate at half size, upsample the latents 2x and refine (above native size)
    prompt_enhancer: bool
    diffusion_decoder: bool
    steps: int | None  # denoising steps; None: fixed schedule (distilled)
    steps_range: tuple[int, int] | None = None
    guidance: float | None = None  # None: not adjustable
    seconds_per_mpx_frame: float  # measured speed: seconds per megapixel-frame at the default steps (estimates)
    notes: list[str] = Field(default_factory=list)


class VideoRequest(BaseModel):
    model_id: str
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str | None = None
    mode: VideoMode = "t2v"
    image: str | None = None  # i2v start frame: a data URL or a /files/outputs/... URL
    width: int | None = Field(None, ge=128, le=MAX_SIDE)  # None: the model's native size
    height: int | None = Field(None, ge=128, le=MAX_SIDE)
    duration_s: float | None = Field(None, gt=0, le=MAX_SECONDS)  # None: the default length
    auto_duration: bool = False  # let the model pick the length (LTX-2.5); duration_s is then the upper bound
    steps: int | None = Field(None, ge=1, le=100)
    guidance: float | None = Field(None, ge=0, le=20)
    upscale: bool | None = None  # two-stage; None: automatic (above the native size)
    enhance_prompt: bool = False
    decoder: VideoDecoder = "vae"
    seed: int | None = None
