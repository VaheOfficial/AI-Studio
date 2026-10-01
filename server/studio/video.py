"""Video generation with local models (Wan 2.2 TI2V-5B, LTX-2.5) run by the ``diffusers-video`` worker.

Nothing is a fixed preset: any size (snapped to what the model needs) up to 4K and any length up to two minutes.
Above the native size LTX-2.5 uses its two-stage path (half-size pass, 2x latent upsampler, refine). Clips longer than
one pass are made in segments, each continuing from the previous segment's last frame, and joined into one MP4."""

from __future__ import annotations

import json
import math
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, db, imaging, media
from .generation import _call_worker, _load, _new_output_path, _require, _save_outputs
from .jobs import JobContext, JobError, jobs
from .models import ModelError
from .schemas import InstalledModel, Job, JobResult, Output
from .schemas_video import MAX_SECONDS, MAX_SIDE, VideoModelProfile, VideoRequest

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_TWO_STAGE_ABOVE = 1280 * 720  # LTX: pixels per frame above which the half-size + upsample path is used


def _family(m: InstalledModel) -> str:
    try:
        index = json.loads((Path(m.path) / "model_index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    name = str(index.get("_class_name", ""))
    return "ltx2" if name.startswith("LTX2") else "wan" if name.startswith("Wan") else ""


def _has(m: InstalledModel, sub: str) -> bool:
    return (Path(m.path) / sub).is_dir()


def profile(m: InstalledModel) -> VideoModelProfile | None:
    family = _family(m)
    if family == "wan":
        return VideoModelProfile(
            model_id=m.id, name=m.name, family="wan", location="local", modes=["t2v", "i2v"], audio=False,
            native_width=1280, native_height=704, size_step=32, max_side=MAX_SIDE, fps=24, default_seconds=5,
            segment_seconds=5, max_seconds=MAX_SECONDS, auto_duration=False, upscaler=False, prompt_enhancer=False,
            diffusion_decoder=False, steps=40, steps_range=(10, 60), guidance=5.0,
            # measured: 832x480, 73 frames, 20 steps in 80 s on an RTX 4090 → at 40 steps
            seconds_per_mpx_frame=5.5,
            notes=["Silent video. Trained at 720p: larger sizes work but take much longer and drift more.",
                   "Clips longer than 5 s continue from the last frame, 5 s at a time."])
    if family == "ltx2":
        return VideoModelProfile(
            model_id=m.id, name=m.name, family="ltx2", location="local", modes=["t2v", "i2v"], audio=True,
            native_width=960, native_height=544, size_step=32, max_side=MAX_SIDE, fps=24, default_seconds=5,
            segment_seconds=10, max_seconds=MAX_SECONDS, auto_duration=_has(m, "duration_head"),
            upscaler=_has(m, "latent_upsampler"), prompt_enhancer=_has(m, "prompt_enhancer"),
            diffusion_decoder=_has(m, "diffusion_decoder"), steps=None, guidance=None,
            # measured: 960x544, 121 frames in 155-162 s on an RTX 4090 (distilled, 8 steps)
            seconds_per_mpx_frame=2.5,
            notes=["Video and audio in one pass: describe sounds and dialogue in the prompt.",
                   "Above 720p it renders at half size, upsamples 2x and refines (the official two-stage path).",
                   "Clips longer than 10 s continue from the last frame, 10 s at a time."])
    return None


def profiles() -> list[VideoModelProfile]:
    installed = [m for m in db.list_installed() if m.kind == "video"]  # a failed load retries on the next job
    return [p for p in (profile(m) for m in installed) if p is not None]


def load_options(m: InstalledModel) -> dict[str, Any]:
    """Extra /load fields: the GGUF transformer file when the model folder has one (LTX-2.5)."""
    gguf = sorted(Path(m.path).rglob("*.gguf"))
    return {"weights": str(gguf[0])} if gguf else {}


def frame_count(family: str, seconds: float, fps: float) -> int:
    """Frames for a clip: Wan needs 4n+1, LTX 8n+1."""
    step = 8 if family == "ltx2" else 4
    return step * max(1, round((seconds * fps - 1) / step)) + 1


@dataclass(frozen=True)
class Plan:
    width: int
    height: int
    seconds: float
    segments: list[float]  # seconds per pass
    two_stage: bool
    auto_duration: bool


def plan(prof: VideoModelProfile, req: VideoRequest) -> Plan:
    width = req.width or prof.native_width
    height = req.height or prof.native_height
    two_stage = prof.upscaler and (req.upscale if req.upscale is not None else width * height > _TWO_STAGE_ABOVE)
    step = prof.size_step * (2 if two_stage else 1)  # the half-size pass must itself be a multiple of size_step
    width = min(MAX_SIDE, max(step, round(width / step) * step))
    height = min(MAX_SIDE, max(step, round(height / step) * step))
    seconds = min(req.duration_s or prof.default_seconds, prof.max_seconds, MAX_SECONDS)
    auto = req.auto_duration and prof.auto_duration
    if auto:  # the model picks the length within one pass
        return Plan(width, height, min(seconds, 20.0), [min(seconds, 20.0)], two_stage, True)
    count = max(1, math.ceil(seconds / prof.segment_seconds - 1e-9))
    base = seconds / count
    return Plan(width, height, seconds, [base] * count, two_stage, False)


def generate(req: VideoRequest) -> Job:
    m = _require(req.model_id, "video")
    prof = profile(m)
    if prof is None:
        raise ModelError(f"{m.name} is not a video model the studio can run", 400)
    if req.mode not in prof.modes:
        raise ModelError(f"{m.name} does not support {req.mode}", 400)
    if req.mode == "i2v" and not req.image:
        raise ModelError("Image-to-video needs a start image", 400)
    if req.enhance_prompt and not prof.prompt_enhancer:
        raise ModelError(f"{m.name} has no prompt enhancer installed", 400)
    if req.decoder == "diffusion" and not prof.diffusion_decoder:
        raise ModelError(f"{m.name} has no diffusion decoder installed", 400)
    p = plan(prof, req)
    start = imaging.input_file(req.image) if req.mode == "i2v" and req.image else None
    title = f"Video · {req.prompt[:48]}"
    return jobs.submit("generate", title, lambda ctx: _job(ctx, m, prof, req, p, start), ref=m.id)


def _job(ctx: JobContext, m: InstalledModel, prof: VideoModelProfile, req: VideoRequest, p: Plan,
         start: imaging.Input | None) -> JobResult:
    try:
        ffmpeg = media.ffmpeg()
    except media.MediaError as exc:
        raise JobError(str(exc)) from exc
    _load(ctx, m)
    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    steps = req.steps or prof.steps or 8
    guidance = req.guidance if req.guidance is not None else (prof.guidance or 1.0)
    oid, path, url = _new_output_path("video", "mp4")
    parts_dir = config.OUTPUTS_DIR / "videos" / f".{oid}"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    frames = 0
    audio = False
    first_image = str(start.path) if start else None
    prompt, enhance = req.prompt, req.enhance_prompt  # the first segment enhances; the rest reuse its prompt
    try:
        n = len(p.segments)
        for i, seconds in enumerate(p.segments):
            part = parts_dir / f"{i:03d}.mp4"
            last = parts_dir / f"{i:03d}.png"
            label = f"Segment {i + 1}/{n}" if n > 1 else "Generating"
            image = first_image if i == 0 else str(parts_dir / f"{i - 1:03d}.png")
            result = _call_worker(ctx, m.runtime, "/generate", {
                "mode": "i2v" if image else "t2v", "prompt": prompt, "negative_prompt": req.negative_prompt,
                "width": p.width, "height": p.height, "fps": prof.fps,
                "frames": None if p.auto_duration else frame_count(prof.family, seconds, prof.fps),
                "max_seconds": seconds, "steps": steps, "guidance": guidance, "seed": seed + i, "image": image,
                "two_stage": p.two_stage, "enhance_prompt": enhance, "decoder": req.decoder,
                "skip_first_frame": i > 0, "out_path": str(part), "last_frame_path": str(last), "ffmpeg": ffmpeg,
            }, label, span=(i / n, (i + 1) / n))
            parts.append(part)
            if enhance:
                prompt, enhance = str(result.get("prompt") or prompt), False
            frames += int(result["frames"])
            audio = audio or bool(result.get("audio"))
        if len(parts) == 1:
            parts[0].replace(path)
        else:
            ctx.update(message="Joining the segments…")
            _concat(ffmpeg, parts, path)
    finally:
        for f in parts_dir.glob("*"):
            f.unlink(missing_ok=True)
        parts_dir.rmdir()
    duration = round(frames / prof.fps, 3)
    params: dict[str, Any] = {"mode": req.mode, "width": p.width, "height": p.height, "duration_s": duration,
                              "fps": prof.fps, "frames": frames, "seed": seed, "audio": audio,
                              "segments": len(p.segments), "two_stage": p.two_stage,
                              "auto_duration": p.auto_duration, "decoder": req.decoder,
                              "enhance_prompt": req.enhance_prompt}
    if prof.steps is not None:
        params |= {"steps": steps, "guidance": guidance}
    if req.negative_prompt:
        params["negative_prompt"] = req.negative_prompt
    if prompt != req.prompt:
        params["enhanced_prompt"] = prompt
    if start:
        params["image"] = start.url
    out = Output(id=oid, kind="video", url=url, model_id=m.id, prompt=req.prompt, params=params,
                 created_at=db.now_iso(), width=p.width, height=p.height, duration_s=duration)
    return _save_outputs([(out, path)])


def _concat(ffmpeg: str, parts: list[Path], out: Path) -> None:
    """Join same-format segments without re-encoding."""
    listing = parts[0].parent / "parts.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    proc = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                           "-c", "copy", "-movflags", "+faststart", str(out)], capture_output=True,
                          creationflags=_NO_WINDOW)
    listing.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise JobError(f"Joining the segments failed: {proc.stderr.decode(errors='replace')[-500:]}")
