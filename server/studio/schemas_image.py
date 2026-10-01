"""Image-area contract: mirrors ``apps/studio/src/api/contracts/image.ts``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ImageMode = Literal["txt2img", "img2img", "inpaint", "edit"]
"""txt2img; img2img (init image + strength); inpaint (init image + mask); edit (reference images the model
conditions on natively — FLUX Kontext / FLUX.2 / Qwen-Image-Edit / cloud models)."""

ImageGuidance = Literal["cfg", "true-cfg", "distilled", "none"]
"""cfg: classic classifier-free guidance; true-cfg: CFG that needs a negative prompt (Qwen-Image);
distilled: guidance is an embedded conditioning value (FLUX); none: guidance is ignored."""


class ImageScheduler(BaseModel):
    id: str
    label: str


class ImageDefaults(BaseModel):
    steps: int
    guidance: float
    width: int
    height: int
    strength: float


class ImageSizeRange(BaseModel):
    min: int
    max: int
    step: int
    max_pixels: int | None = None


class ImageOption(BaseModel):
    """A provider-specific enum parameter (OpenRouter: aspect_ratio, resolution, quality, …)."""

    id: str
    label: str
    values: list[str]
    default: str


class ImageModelProfile(BaseModel):
    """What an installed image model can do and its sensible defaults — drives the Generate/Edit forms."""

    model_id: str
    family: str
    engine: str  # diffusers pipeline class, worker runtime, or cloud provider
    location: Literal["local", "cloud"]
    modes: list[ImageMode]
    guidance: ImageGuidance
    negative_prompt: bool
    steps_range: tuple[int, int] | None = None  # None: the model has no step control (cloud)
    guidance_range: tuple[float, float] | None = None
    schedulers: list[ImageScheduler] = Field(default_factory=list)
    defaults: ImageDefaults
    size: ImageSizeRange | None = None  # None: the size comes from ``options`` (aspect ratio / resolution)
    options: list[ImageOption] = Field(default_factory=list)
    seed: bool = True
    max_count: int
    max_images: int  # reference images accepted in edit mode
    vram_gb: float | None = None  # estimated need of the weights actually installed
    cost: str | None = None  # cloud pricing notice
    notes: list[str] = Field(default_factory=list)


class ImageRequest(BaseModel):
    """Mirrors the core ``ImageRequest`` in ``types.ts``; lives here because only the image area uses it
    (``schemas.py`` imports this module for its event unions, so the base can't sit there)."""

    model_id: str
    prompt: str
    negative_prompt: str | None = None
    width: int = Field(1024, ge=64, le=4096)
    height: int = Field(1024, ge=64, le=4096)
    steps: int = Field(28, ge=1, le=200)
    guidance: float = Field(4.0, ge=0, le=50)
    seed: int | None = None
    count: int = Field(1, ge=1, le=8)


class ImageGenerateRequest(ImageRequest):
    """The core ``ImageRequest`` plus edit inputs. Images are data URLs or ``/files/outputs/...`` URLs."""

    mode: ImageMode = "txt2img"
    scheduler: str | None = None
    images: list[str] = Field(default_factory=list, max_length=20)
    mask: str | None = None  # data URL; white = repaint
    strength: float = Field(0.7, ge=0.0, le=1.0)
    options: dict[str, str] = Field(default_factory=dict)


class StarRequest(BaseModel):
    starred: bool


class EvImagePreview(BaseModel):
    """Low-res preview of the image being denoised (latent → RGB), pushed while a local job runs."""

    type: Literal["image.preview"] = "image.preview"
    job_id: str
    step: int
    total: int
    image: str  # data:image/jpeg;base64,…
