"""Generation jobs (music) and transcription, executed by runtime workers. Image jobs live in
``imaging.py`` and speech jobs in ``voice/speech.py``; both reuse the worker helpers below."""

from __future__ import annotations

import random
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import config, db, openrouter_media
from .jobs import JobContext, JobError, jobs
from .models import ModelError, models
from .runtimes import WorkerError, runtimes
from .schemas import InstalledModel, Job, JobResult, ModelKind, MusicRequest, Output, OutputKind, TranscribeResult

_OUTPUT_SUBDIR: dict[OutputKind, str] = {"image": "images", "audio": "audio", "music": "music", "video": "videos"}


def _require(model_id: str, kind: ModelKind) -> InstalledModel:
    m = models.get(model_id)
    if m.kind != kind:
        raise ModelError(f"{m.name} is a {m.kind} model, not {kind}", 400)
    return m


def _new_output_path(kind: OutputKind, ext: str) -> tuple[str, Path, str]:
    oid = uuid.uuid4().hex[:16]
    sub = _OUTPUT_SUBDIR[kind]
    return oid, config.OUTPUTS_DIR / sub / f"{oid}.{ext}", f"/files/outputs/{sub}/{oid}.{ext}"


def _call_worker(ctx: JobContext, runtime: str, path: str, payload: dict[str, Any], label: str,
                 on_poll: Callable[[dict[str, Any]], None] | None = None,
                 span: tuple[float, float] = (0.0, 1.0)) -> dict[str, Any]:
    """POST to the worker while polling its /progress into the job; cancel interrupts the worker.
    ``on_poll`` sees every /progress reply (e.g. to forward image previews). ``span``: the part of the job's
    progress this call covers (a job that makes several calls, like a video in segments)."""

    def cancel() -> None:
        try:
            runtimes.request(runtime, "POST", "/cancel", timeout=5, start=False)
        except WorkerError as exc:
            ctx.log(f"Cancel request to {runtime} failed: {exc}", "warn")

    ctx.on_cancel(cancel)
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(runtimes.request, runtime, "POST", path, payload, 3600)
        while not fut.done():
            time.sleep(0.5)
            try:
                p = runtimes.request(runtime, "GET", "/progress", timeout=5, start=False)
            except WorkerError:
                continue
            if on_poll:
                on_poll(p)
            total = p.get("total") or 0
            if total:
                step = p.get("step", 0)
                # Workers name their current phase (e.g. "Decoding image" after the last step)
                phase = p.get("message") or label
                if span != (0.0, 1.0) and phase != label:  # several calls: say which one ("Segment 2/5 · Denoising")
                    phase = f"{label} · {phase}"
                lo, hi = span
                ctx.update(progress=round(min(lo + (hi - lo) * step / total, 0.99), 3),
                           message=f"{phase}…" if step >= total else f"{phase}: step {step}/{total}")
            elif p.get("message"):
                ctx.update(message=p["message"])
        try:
            return fut.result()
        except WorkerError as exc:
            ctx.check_cancelled()
            raise JobError(str(exc)) from exc


def _load(ctx: JobContext, m: InstalledModel) -> None:
    loading = runtimes.loaded_model(m.runtime) != m.id
    if loading:
        ctx.update(message=f"Loading {m.name}…")

    def stop_loading() -> None:
        # A load can't be interrupted from inside the worker (it's one long library call): stop the worker instead
        if loading:
            runtimes.stop(m.runtime)

    ctx.on_cancel(stop_loading)
    try:
        models.ensure_loaded(m.id)
    except ModelError as exc:
        ctx.check_cancelled()
        raise JobError(str(exc)) from exc
    finally:
        loading = False
    ctx.check_cancelled()


def _save_outputs(outputs: list[tuple[Output, Path]]) -> JobResult:
    for o, path in outputs:
        db.insert_output(o, str(path))
    return JobResult(outputs=[o for o, _ in outputs])


# --------------------------------- music ---------------------------------


def generate_music(req: MusicRequest) -> Job:
    m = _require(req.model_id, "music")
    return jobs.submit("generate", f"Music · {req.tags[:48]}", lambda ctx: _music_job(ctx, m, req), ref=m.id)


def _music_job(ctx: JobContext, m: InstalledModel, req: MusicRequest) -> JobResult:
    _load(ctx, m)
    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    oid, path, url = _new_output_path("music", "wav")
    result = _call_worker(ctx, m.runtime, "/generate", {
        "tags": req.tags, "lyrics": req.lyrics, "duration_s": req.duration_s, "steps": req.steps,
        "guidance": req.guidance, "seed": seed, "out_path": str(path),
    }, "Composing")
    params = req.model_dump(exclude={"model_id", "tags"}, exclude_none=True) | {"seed": seed}
    out = Output(id=oid, kind="music", url=url, model_id=m.id, prompt=req.tags, params=params,
                 created_at=db.now_iso(), duration_s=round(float(result["duration_s"]), 3))
    return _save_outputs([(out, path)])


# ------------------------------- transcribe -------------------------------


def transcribe(model_id: str, audio: Path, language: str | None = None) -> TranscribeResult:
    """Blocking; call from a thread."""
    m = _require(model_id, "stt")
    if m.runtime == "openrouter":
        return openrouter_media.transcribe(m, audio, language)
    models.ensure_loaded(m.id)
    result = runtimes.request(m.runtime, "POST", "/transcribe", {"path": str(audio), "language": language},
                              timeout=3600)
    return TranscribeResult.model_validate(result)
