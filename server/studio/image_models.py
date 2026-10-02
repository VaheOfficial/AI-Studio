"""Local image models: how the installed weights are laid out, what they need to load, and what they can do.

Works for every image repo the hub can install, not just the curated catalog:
- a diffusers pipeline folder (``model_index.json``), incl. pre-quantized ones (bnb NF4/int8, torchao);
- a single GGUF / safetensors denoiser (FLUX GGUF, FLUX fp8, …) paired with a base pipeline folder that
  supplies text encoders, VAE, scheduler and configs (installed as companions, or another installed model);
- a full single-file checkpoint (SD 1.x / SDXL community models).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError

from . import catalog, db, settings
from .catalog import GIB
from .hub.variants import ENCODER_MIN_BYTES, ENCODER_SCALE
from .schemas import InstalledModel, TextEncoderMode
from .schemas_image import (ImageDefaults, ImageGuidance, ImageMode, ImageModelProfile, ImageScheduler,
                            ImageSizeRange)

WeightsFormat = Literal["gguf", "safetensors"]

# Activations, attention buffers and the VAE decode on top of the weights (1024², batch 1).
_WORKING_SET_GB = 2.5

# ---------------------------------------------------------------------------------------------------------
# Families: defaults and capabilities per diffusers pipeline class
# ---------------------------------------------------------------------------------------------------------

SD_SCHEDULERS = [
    ImageScheduler(id="euler", label="Euler"),
    ImageScheduler(id="euler_a", label="Euler ancestral"),
    ImageScheduler(id="dpmpp_2m", label="DPM++ 2M"),
    ImageScheduler(id="dpmpp_2m_karras", label="DPM++ 2M Karras"),
    ImageScheduler(id="dpmpp_sde_karras", label="DPM++ SDE Karras"),
    ImageScheduler(id="unipc", label="UniPC"),
    ImageScheduler(id="ddim", label="DDIM"),
]


@dataclass(frozen=True)
class Family:
    name: str
    guidance: ImageGuidance
    negative: bool
    steps: int
    cfg: float
    modes: tuple[ImageMode, ...]
    cfg_max: float = 10.0
    steps_max: int = 80
    size: int = 1024  # native square side
    size_min: int = 256
    size_max: int = 2048
    size_step: int = 16
    schedulers: tuple[ImageScheduler, ...] = ()
    max_images: int = 0

    def variant(self, **changes: Any) -> Family:
        return Family(**{**self.__dict__, **changes})


_T2I: tuple[ImageMode, ...] = ("txt2img",)
_ALL: tuple[ImageMode, ...] = ("txt2img", "img2img", "inpaint")

FAMILIES: dict[str, Family] = {
    "StableDiffusionPipeline": Family("Stable Diffusion 1.x", "cfg", True, 25, 7.0, _ALL, cfg_max=15, size=512,
                                      size_max=1024, size_step=64, schedulers=tuple(SD_SCHEDULERS)),
    "StableDiffusionXLPipeline": Family("SDXL", "cfg", True, 30, 6.0, _ALL, cfg_max=15, size_min=512,
                                        size_step=64, schedulers=tuple(SD_SCHEDULERS)),
    "StableDiffusion3Pipeline": Family("Stable Diffusion 3", "cfg", True, 28, 5.0, _ALL, cfg_max=12),
    "FluxPipeline": Family("FLUX.1", "distilled", False, 28, 3.5, _ALL),
    "FluxKontextPipeline": Family("FLUX.1 Kontext", "distilled", False, 28, 2.5, ("txt2img", "edit"), max_images=1),
    "Flux2Pipeline": Family("FLUX.2", "distilled", False, 28, 4.0, ("txt2img", "edit"), max_images=4),
    "Flux2KleinPipeline": Family("FLUX.2 [klein]", "cfg", True, 50, 4.0, ("txt2img", "edit", "inpaint"),
                                 max_images=4),
    "ZImagePipeline": Family("Z-Image", "cfg", True, 30, 4.0, _ALL),
    "QwenImagePipeline": Family("Qwen-Image", "true-cfg", True, 30, 4.0, _ALL),
    # One pipeline for text-to-image and editing; meant to be sampled without guidance (cfg 1 = off)
    "QwenImage21Pipeline": Family("Qwen-Image 2.1", "true-cfg", True, 40, 1.0, ("txt2img", "edit"), size_step=32,
                                  max_images=3),
    "QwenImageEditPipeline": Family("Qwen-Image-Edit", "true-cfg", True, 40, 4.0, ("edit", "inpaint"),
                                    max_images=1),
    "QwenImageEditPlusPipeline": Family("Qwen-Image-Edit", "true-cfg", True, 40, 4.0, ("edit",), max_images=3),
    "ChromaPipeline": Family("Chroma", "cfg", True, 26, 4.0, _ALL),
    "HunyuanImagePipeline": Family("HunyuanImage 2.1", "distilled", True, 50, 3.5, _T2I, size=2048,
                                   size_max=2048),
    "HunyuanImage3": Family("HunyuanImage 3", "none", False, 50, 0.0, _T2I),
}
_GENERIC = Family("Diffusers", "cfg", True, 28, 4.5, _T2I)

# Local text-to-image families, best image quality first — what the agent uses when no model is named.
QUALITY = ("HunyuanImage 3", "FLUX.2", "Qwen-Image 2.1", "Qwen-Image", "FLUX.2 [klein]", "HunyuanImage 2.1", "FLUX.1 Krea", "FLUX.1",
           "FLUX.1 Kontext", "Chroma", "Z-Image", "Stable Diffusion 3", "Z-Image-Turbo", "FLUX.1 [schnell]", "SDXL",
           "Stable Diffusion 1.x")


def quality_rank(family: str) -> int:
    return QUALITY.index(family) if family in QUALITY else len(QUALITY)


def _tuned(family: Family, pipeline_class: str, flags: dict[str, Any], hints: str) -> Family:
    """Adjust family defaults for step-distilled checkpoints (schnell, turbo, distilled klein)."""
    if pipeline_class == "FluxPipeline" and (flags.get("guidance_embeds") is False or "schnell" in hints):
        return family.variant(name="FLUX.1 [schnell]", guidance="none", steps=4, cfg=0.0, steps_max=16)
    if pipeline_class == "FluxPipeline" and "krea" in hints:
        return family.variant(name="FLUX.1 Krea", cfg=4.5)
    if pipeline_class == "Flux2KleinPipeline" and flags.get("is_distilled"):
        return family.variant(guidance="none", negative=False, steps=4, cfg=1.0, steps_max=16)
    if pipeline_class == "ZImagePipeline" and "turbo" in hints:
        return family.variant(name="Z-Image-Turbo", steps=9, cfg=0.0, steps_max=30)
    return family


# ---------------------------------------------------------------------------------------------------------
# Layout of the installed weights
# ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    """Where a local image model's pieces are.

    ``pipeline_dir`` holds ``model_index.json`` (the full pipeline, or the base companions for a single
    denoiser file). ``weights`` is a single file: a denoiser that replaces the pipeline's transformer/unet, or
    (``full_checkpoint``) a complete SD-style checkpoint loaded with ``from_single_file``.
    """

    pipeline_dir: Path | None
    weights: Path | None = None
    weights_format: WeightsFormat | None = None
    full_checkpoint: bool = False
    pipeline_class: str | None = None
    flags: dict[str, Any] = field(default_factory=dict)


class LayoutError(Exception):
    """The installed files can't be turned into a pipeline; message is user-facing."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, ValueError):
        return {}


def _find_pipeline_dir(root: Path) -> Path | None:
    if (root / "model_index.json").is_file():
        return root
    for depth in ("*/model_index.json", "*/*/model_index.json"):
        found = sorted(root.glob(depth))
        if found:
            return found[0].parent
    return None


def _weight_file(m: InstalledModel, root: Path) -> tuple[Path, WeightsFormat] | None:
    if m.format not in ("gguf", "safetensors"):
        return None
    suffix = f".{m.format}"
    # The weights sit at the folder root; companions (text encoders, VAE) live in component subfolders
    names = [f for f in (m.files or []) if f.lower().endswith(suffix) and "/" not in f.replace("\\", "/")]
    candidates = [root / n for n in names] or sorted(root.glob(f"*{suffix}"))
    existing = [p for p in candidates if p.is_file()]
    if not existing:
        raise LayoutError(f"{m.name}: no {suffix} weights file found in {root}")
    # Split GGUF sets load from their first shard
    return sorted(existing)[0], m.format


def safetensors_header(path: Path) -> dict[str, Any]:
    """Tensor table of a safetensors file (name → {dtype, shape, data_offsets}) without reading weights."""
    with path.open("rb") as f:
        (length,) = struct.unpack("<Q", f.read(8))
        header: dict[str, Any] = json.loads(f.read(length))
    header.pop("__metadata__", None)
    return header


def _checkpoint_class(path: Path) -> tuple[str | None, bool]:
    """(pipeline class, is a full checkpoint with text encoders + VAE) from a safetensors file's tensor names."""
    keys = safetensors_header(path).keys()
    has = lambda prefix: any(k.startswith(prefix) for k in keys)  # noqa: E731
    full = has("conditioner.") or has("cond_stage_model.") or has("first_stage_model.") or has("text_encoders.")
    if has("conditioner.embedders.1.") or has("model.diffusion_model.label_emb."):
        return "StableDiffusionXLPipeline", full
    if has("model.diffusion_model.input_blocks."):
        return "StableDiffusionPipeline", full
    if has("model.diffusion_model.joint_blocks.") or has("joint_blocks."):
        return "StableDiffusion3Pipeline", full
    return None, False


@cache
def _card_base_models(repo: str) -> frozenset[str]:
    """``base_model`` entries of a Hugging Face model card (cached for the process)."""
    try:
        info = HfApi(token=settings.load().hf_token).model_info(repo, timeout=15)
    except (HfHubHTTPError, OSError, ValueError):
        return frozenset()
    base = (info.card_data or {}).get("base_model") if info.card_data else None
    if isinstance(base, str):
        return frozenset({base})
    return frozenset(b for b in base or [] if isinstance(b, str))


def _repo_of(m: InstalledModel) -> str | None:
    if m.source_repo:
        return m.source_repo
    spec = catalog.get(m.catalog_id)
    return spec.source.repo if spec and spec.source.type == "hf" else None


def installed_base(repo: str, exclude_id: str | None = None) -> tuple[InstalledModel, Path] | None:
    """An installed diffusers pipeline (and its pipeline folder) built on the same base model as the denoiser
    weights from ``repo`` — its text encoders, VAE and configs complete those weights. The hub uses this to skip
    downloading companions that are already on disk."""
    wanted = _card_base_models(repo) | {repo}
    for other in db.list_installed():
        if other.id == exclude_id or other.kind != "image" or other.runtime != "diffusers":
            continue
        pipeline_dir = _find_pipeline_dir(Path(other.path))
        other_repo = _repo_of(other)
        if pipeline_dir and other_repo and ({other_repo} | _card_base_models(other_repo)) & wanted:
            return other, pipeline_dir
    return None


def _installed_base(m: InstalledModel) -> Path | None:
    repo = _repo_of(m)
    found = installed_base(repo, exclude_id=m.id) if repo else None
    return found[1] if found else None


def layout(m: InstalledModel) -> Layout:
    root = Path(m.path)
    if not root.exists():
        raise LayoutError(f"{m.name}: model folder {root} is missing (drive disconnected?)")
    weights = _weight_file(m, root)
    pipeline_dir = _find_pipeline_dir(root)
    if weights is None:
        if pipeline_dir is None:
            raise LayoutError(f"{m.name}: no model_index.json in {root} — not a diffusers pipeline")
        return _with_class(Layout(pipeline_dir=pipeline_dir))
    path, fmt = weights
    if fmt == "safetensors":
        cls, full = _checkpoint_class(path)
        if full:
            return Layout(pipeline_dir=None, weights=path, weights_format=fmt, full_checkpoint=True,
                          pipeline_class=cls)
    base = pipeline_dir or _installed_base(m)
    if base is None:
        bases = ", ".join(sorted(_card_base_models(_repo_of(m) or ""))) or "its base model"
        raise LayoutError(f"{m.name} is a single {fmt} denoiser: it needs the base pipeline ({bases}) for text "
                          "encoders, VAE and configs. Install the variant again from the hub with companions, or "
                          "install the base diffusers model.")
    return _with_class(Layout(pipeline_dir=base, weights=path, weights_format=fmt))


def _with_class(lay: Layout) -> Layout:
    assert lay.pipeline_dir is not None
    index = _read_json(lay.pipeline_dir / "model_index.json")
    flags = {"is_distilled": index.get("is_distilled")}
    flags |= {k: v for k, v in _read_json(lay.pipeline_dir / "transformer" / "config.json").items()
              if k == "guidance_embeds"}
    return Layout(pipeline_dir=lay.pipeline_dir, weights=lay.weights, weights_format=lay.weights_format,
                  pipeline_class=index.get("_class_name"), flags=flags)


# ---------------------------------------------------------------------------------------------------------
# Memory estimate
# ---------------------------------------------------------------------------------------------------------

_BYTES = {"F64": 8, "F32": 4, "F16": 2, "BF16": 2, "I64": 8, "I32": 4, "I16": 2, "I8": 1, "U8": 1,
          "F8_E4M3": 1, "F8_E5M2": 1, "BOOL": 1}


def _loaded_bytes(path: Path) -> int:
    """Bytes a safetensors file occupies once loaded: float weights become bf16, quantized stay packed."""
    total = 0
    for t in safetensors_header(path).values():
        n = 1
        for d in t["shape"]:
            n *= d
        size = _BYTES.get(t["dtype"], 2)
        total += n * (2 if t["dtype"] in ("F32", "F64") else size)
    return total


def _component_bytes(folder: Path) -> int:
    files = sorted(folder.glob("*.safetensors"))
    fp16 = [f for f in files if ".fp16." in f.name]
    return sum(_loaded_bytes(f) for f in fp16 or files)


def large_encoders(lay: Layout) -> dict[str, int]:
    """The pipeline's text encoders big enough to be worth holding quantized: component name → bytes in bf16."""
    if lay.pipeline_dir is None:
        return {}
    found = {}
    for comp, spec in _read_json(lay.pipeline_dir / "model_index.json").items():
        folder = lay.pipeline_dir / comp
        if not comp.startswith("text_encoder") or not isinstance(spec, list) or spec[:1] != ["transformers"]:
            continue
        size = _component_bytes(folder) if folder.is_dir() else 0
        if size >= ENCODER_MIN_BYTES:
            found[comp] = size
    return found


def weights_gb(lay: Layout, encoder: TextEncoderMode | None = None) -> float:
    """``encoder``: how the large text encoders are held (None: full precision)."""
    total = 0.0
    quantized = large_encoders(lay) if encoder not in (None, "full") else {}
    if lay.pipeline_dir is not None:
        index = _read_json(lay.pipeline_dir / "model_index.json")
        for comp in index:
            folder = lay.pipeline_dir / comp
            if comp.startswith("_") or not folder.is_dir():
                continue
            if lay.weights is not None and comp in ("transformer", "unet"):
                continue
            total += quantized[comp] * ENCODER_SCALE[encoder] if comp in quantized and encoder else _component_bytes(folder)
    if lay.weights is not None:
        total += lay.weights.stat().st_size if lay.weights_format == "gguf" else _loaded_bytes(lay.weights)
    return total / GIB


def vram_need_gb(m: InstalledModel, encoder: TextEncoderMode | None = None) -> float:
    """Estimated VRAM to hold ``m`` fully on the GPU and generate at 1024² (``encoder``: with its text encoder
    held that way instead of the way the model is set to)."""
    if m.runtime == "diffusers":
        try:
            return round(weights_gb(layout(m), encoder or m.text_encoder) + _WORKING_SET_GB, 1)
        except (LayoutError, OSError, ValueError, KeyError):
            pass
    spec = catalog.get(m.catalog_id)
    return spec.vram_gb if spec else m.size_bytes / GIB


def load_options(m: InstalledModel) -> dict[str, Any]:
    """Extra ``/load`` fields for the image worker describing how to assemble the pipeline."""
    if m.runtime != "diffusers":
        return {}
    lay = layout(m)
    return {
        "pipeline_dir": str(lay.pipeline_dir) if lay.pipeline_dir else None,
        "weights": str(lay.weights) if lay.weights else None,
        "weights_format": lay.weights_format,
        "full_checkpoint": lay.full_checkpoint,
        "pipeline_class": lay.pipeline_class,
        "quant": m.quant,
        "text_encoder": m.text_encoder or "full",
    }


# ---------------------------------------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------------------------------------


def _hints(m: InstalledModel, lay: Layout | None) -> str:
    parts = [m.id, m.name, m.source_repo or "", _repo_of(m) or ""]
    if lay and lay.weights:
        parts.append(lay.weights.name)
    return " ".join(parts).lower()


def local_profile(m: InstalledModel) -> ImageModelProfile:
    notes: list[str] = []
    lay: Layout | None = None
    if m.runtime == "hunyuan-image3":
        cls = "HunyuanImage3"
    else:
        try:
            lay = layout(m)
            cls = lay.pipeline_class or ""
        except LayoutError as exc:
            cls = ""
            notes.append(str(exc))
    family = _tuned(FAMILIES.get(cls, _GENERIC), cls, lay.flags if lay else {}, _hints(m, lay))
    need = vram_need_gb(m)
    spec = catalog.get(m.catalog_id)
    if spec and spec.notes:
        notes.append(spec.notes)
    if spec and "non-commercial" in spec.license.lower() and "non-commercial" not in (spec.notes or "").lower():
        notes.append(f"License: {spec.license} (personal use)")
    if lay and lay.weights and lay.pipeline_dir and not lay.full_checkpoint:
        where = "its base model" if lay.pipeline_dir == Path(m.path) else f"the installed pipeline in {lay.pipeline_dir}"
        notes.append(f"{(lay.weights_format or '').upper()} {m.quant or ''} transformer ({lay.weights.name}) on the "
                     f"text encoders and VAE of {where}.")
    if lay and m.text_encoder in ("8bit", "4bit") and large_encoders(lay):
        notes.append(f"Text encoder held in {m.text_encoder.removesuffix('bit')} bits (quantized when the model "
                     "loads; the first load also saves that copy next to the model, so later loads are quicker).")
    return ImageModelProfile(
        model_id=m.id, family=family.name, engine=cls or m.runtime, location="local", modes=list(family.modes),
        guidance=family.guidance, negative_prompt=family.negative, steps_range=(1, family.steps_max),
        guidance_range=None if family.guidance == "none" else (0.0, family.cfg_max),
        schedulers=list(family.schedulers),
        defaults=ImageDefaults(steps=family.steps, guidance=family.cfg, width=family.size, height=family.size,
                               strength=0.7),
        size=ImageSizeRange(min=family.size_min, max=family.size_max, step=family.size_step),
        max_count=8, max_images=family.max_images, vram_gb=need, notes=notes,
    )
