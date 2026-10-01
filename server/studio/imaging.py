"""Image generation and editing for every image model the studio can use — local diffusers / HunyuanImage 3
workers, Tencent HY-Image 3.5 and pinned OpenRouter models — plus model profiles, edit inputs and gallery stars."""

from __future__ import annotations

import asyncio
import base64
import binascii
import random
import re
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, db, image_models, openrouter_catalog, openrouter_image, tencent_image
from .events import bus
from .generation import _call_worker, _load, _new_output_path, _save_outputs
from .jobs import JobContext, JobError, jobs
from .models import ModelError, models
from .openrouter import OpenRouterError
from .schemas import InstalledModel, Job, JobResult, Output
from .schemas_image import EvImagePreview, ImageGenerateRequest, ImageModelProfile
from .tencent_image import TencentError

INPUTS_DIR = config.OUTPUTS_DIR / "inputs"
_INPUT_URL = "/files/outputs/inputs"
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
_DATA_URL = re.compile(r"^data:(image/[a-z+.-]+);base64,(.*)$", re.S)


def init() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS image_stars (
        output_id TEXT PRIMARY KEY REFERENCES outputs(id) ON DELETE CASCADE,
        starred_at TEXT NOT NULL
    )""")


# ------------------------------- profiles -------------------------------


def profile_of(m: InstalledModel, openrouter_params: dict[str, dict[str, Any]]) -> ImageModelProfile:
    if m.runtime == "tencent-cloud":
        return tencent_image.profile(m)
    if m.runtime == "openrouter":
        return openrouter_image.profile(m, openrouter_params.get(openrouter_catalog.slug(m), {}))
    return image_models.local_profile(m)


async def profiles() -> list[ImageModelProfile]:
    installed = [m for m in db.list_installed() if m.kind == "image"]
    params = await openrouter_image.supported_parameters() if any(m.runtime == "openrouter" for m in installed) else {}
    # Local profiles read safetensors headers from a (slow USB) disk
    return await asyncio.to_thread(lambda: [profile_of(m, params) for m in installed])


def ranked_local() -> list[ImageModelProfile]:
    """Installed local text-to-image models, best first (larger weights first within a family). Cloud models
    cost money per image, so they are never picked implicitly."""
    local = [m for m in db.list_installed() if m.kind == "image" and m.runtime not in ("openrouter", "tencent-cloud")]
    found = [p for p in (image_models.local_profile(m) for m in local) if "txt2img" in p.modes]
    return sorted(found, key=lambda p: (image_models.quality_rank(p.family), -(p.vram_gb or 0.0)))


# -------------------------------- inputs --------------------------------


@dataclass(frozen=True)
class Input:
    path: Path
    url: str


def _save_data_url(value: str) -> Input:
    match = _DATA_URL.match(value)
    if not match or match.group(1) not in _EXT:
        raise ModelError("Images must be PNG, JPEG, WebP or GIF data URLs", 400)
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except binascii.Error as exc:
        raise ModelError("Invalid base64 image data", 400) from exc
    name = f"{uuid.uuid4().hex[:16]}.{_EXT[match.group(1)]}"
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (INPUTS_DIR / name).write_bytes(data)
    return Input(INPUTS_DIR / name, f"{_INPUT_URL}/{name}")


def _resolve_input(value: str) -> Input:
    """A data URL (saved under outputs/inputs so the gallery can show it later) or a generated file URL."""
    if value.startswith("data:"):
        return _save_data_url(value)
    if value.startswith("/files/outputs/"):
        path = (config.OUTPUTS_DIR / value.removeprefix("/files/outputs/")).resolve()
        if config.OUTPUTS_DIR.resolve() in path.parents and path.is_file():
            return Input(path, value)
    raise ModelError(f"Image input not found: {value[:80]}", 400)


def input_file(value: str) -> Input:
    """A start or reference image for another area (video): a data URL or a generated file URL."""
    return _resolve_input(value)


def image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) of PNG / JPEG / WebP bytes, without an imaging library."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return int(w), int(h)
            i += 2 + length
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return int(w & 0x3FFF), int(h & 0x3FFF)
    return None


# ------------------------------- generate -------------------------------


def generate(req: ImageGenerateRequest) -> Job:
    m = models.get(req.model_id)
    if m.kind != "image":
        raise ModelError(f"{m.name} is a {m.kind} model, not an image model", 400)
    if req.mode in ("img2img", "inpaint") and not req.images:
        raise ModelError(f"{req.mode} needs a source image", 400)
    if req.mode == "inpaint" and not req.mask:
        raise ModelError("Inpainting needs a mask — paint the area to change", 400)
    if req.mode == "edit" and not req.images:
        raise ModelError("Edit needs at least one reference image", 400)
    if m.runtime not in ("tencent-cloud", "openrouter"):
        modes = image_models.local_profile(m).modes
        if req.mode not in modes:
            raise ModelError(f"{m.name} does not support {req.mode} (supports: {', '.join(modes)})", 400)
    inputs = [_resolve_input(u) for u in req.images] if req.mode != "txt2img" else []
    mask = _save_data_url(req.mask) if req.mask and req.mode == "inpaint" else None
    runner = {"tencent-cloud": _tencent_job, "openrouter": _openrouter_job}.get(m.runtime, _local_job)
    title = f"{'Image' if req.mode == 'txt2img' else 'Edit'} · {req.prompt[:48]}"
    return jobs.submit("generate", title, lambda ctx: runner(ctx, m, req, inputs, mask), ref=m.id)


def _params(req: ImageGenerateRequest, seed: int, inputs: list[Input], mask: Input | None,
            local: bool) -> dict[str, Any]:
    """Everything needed to reproduce an image ("reuse settings" in the gallery)."""
    skip = {"prompt", "model_id", "count", "images", "mask"}
    if req.mode == "txt2img" or req.mode == "edit":
        skip.add("strength")
    if not local:
        skip |= {"steps", "guidance", "scheduler", "negative_prompt"}
    if not req.options:
        skip.add("options")
    params = req.model_dump(exclude=skip, exclude_none=True) | {"seed": seed}
    if inputs:
        params["images"] = [i.url for i in inputs]
    if mask:
        params["mask"] = mask.url
    return params


def _seeds(req: ImageGenerateRequest) -> list[int]:
    base = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    return [base + i for i in range(req.count)]


def _local_job(ctx: JobContext, m: InstalledModel, req: ImageGenerateRequest, inputs: list[Input],
               mask: Input | None) -> JobResult:
    _load(ctx, m)
    seeds = _seeds(req)
    targets = [_new_output_path("image", "png") for _ in seeds]
    last_preview = [-1]

    def on_poll(progress: dict[str, Any]) -> None:
        preview = progress.get("preview")
        if preview and preview["step"] != last_preview[0]:
            last_preview[0] = preview["step"]
            bus.publish(EvImagePreview(job_id=ctx.id, step=preview["step"], total=int(progress.get("total") or 0),
                                       image=preview["image"]))

    result = _call_worker(ctx, m.runtime, "/generate", {
        "prompt": req.prompt, "negative_prompt": req.negative_prompt, "width": req.width, "height": req.height,
        "steps": req.steps, "guidance": req.guidance, "seeds": seeds, "out_paths": [str(t[1]) for t in targets],
        "mode": req.mode, "scheduler": req.scheduler, "strength": req.strength,
        "images": [str(i.path) for i in inputs], "mask": str(mask.path) if mask else None,
    }, "Denoising", on_poll)
    outputs: list[tuple[Output, Path]] = []
    for (oid, path, url), img in zip(targets, result["images"], strict=True):
        outputs.append((Output(id=oid, kind="image", url=url, model_id=m.id, prompt=req.prompt,
                               params=_params(req, img["seed"], inputs, mask, local=True), created_at=db.now_iso(),
                               width=img["width"], height=img["height"]), path))
    return _save_outputs(outputs)


def _tencent_job(ctx: JobContext, m: InstalledModel, req: ImageGenerateRequest, inputs: list[Input],
                 _mask: Input | None) -> JobResult:
    outputs: list[tuple[Output, Path]] = []
    seeds = _seeds(req)
    for i, seed in enumerate(seeds):
        ctx.check_cancelled()
        ctx.update(progress=round(i / len(seeds), 3),
                   message=f"Generating on Tencent Cloud ({i + 1}/{len(seeds)})…")
        oid = uuid.uuid4().hex[:16]
        try:
            img = tencent_image.client.generate(req.prompt, req.width, req.height, seed, [x.path for x in inputs],
                                                config.OUTPUTS_DIR / "images" / oid)
        except TencentError as exc:
            if outputs:  # keep what was already paid for
                ctx.log(f"Stopped after {len(outputs)} image(s): {exc}", "warn")
                break
            raise JobError(str(exc)) from exc
        outputs.append((Output(id=oid, kind="image", url=f"/files/outputs/images/{img.path.name}", model_id=m.id,
                               prompt=req.prompt, params=_params(req, seed, inputs, None, local=False),
                               created_at=db.now_iso(), width=img.width, height=img.height), img.path))
    return _save_outputs(outputs)


def _openrouter_job(ctx: JobContext, m: InstalledModel, req: ImageGenerateRequest, inputs: list[Input],
                    _mask: Input | None) -> JobResult:
    params = asyncio.run(openrouter_image.supported_parameters()).get(openrouter_catalog.slug(m), {})
    seed = _seeds(req)[0]
    ctx.update(message=f"Generating on OpenRouter ({openrouter_catalog.slug(m)})…")
    refs = [tencent_image.data_url(x.path) for x in inputs]
    try:
        images = openrouter_image.generate(m, req.prompt, req.count, seed, req.options, refs, params, ctx.id)
    except OpenRouterError as exc:
        raise JobError(str(exc)) from exc
    outputs: list[tuple[Output, Path]] = []
    for i, image in enumerate(images):
        oid, path, url = _new_output_path("image", _EXT.get(image.media_type, "png"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image.data)
        w, h = image_size(image.data) or (None, None)
        outputs.append((Output(id=oid, kind="image", url=url, model_id=m.id, prompt=req.prompt,
                               params=_params(req, seed + i, inputs, None, local=False), created_at=db.now_iso(),
                               width=w, height=h), path))
    return _save_outputs(outputs)


# -------------------------------- stars --------------------------------


def stars() -> list[str]:
    return [r["output_id"] for r in db.query("SELECT output_id FROM image_stars ORDER BY starred_at DESC")]


def set_star(output_id: str, starred: bool) -> None:
    if db.get_output_path(output_id) is None:
        raise ModelError(f"Output '{output_id}' not found", 404)
    if starred:
        db.execute("INSERT INTO image_stars(output_id, starred_at) VALUES(?, ?) ON CONFLICT(output_id) DO NOTHING",
                   (output_id, db.now_iso()))
    else:
        db.execute("DELETE FROM image_stars WHERE output_id = ?", (output_id,))
