"""Calls into the ``dub`` runtime worker with job progress, plus GPU hand-over between pipeline stages.

Stage models (Demucs, Whisper, pyannote, NLLB) live in the dub worker only while a stage needs them; before a
stage the other resident models are evicted until the stage fits (loaded LLMs first — they reload fastest), and
before TTS the dub worker drops its models so the TTS model can take the GPU."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import db, events, system
from ..catalog import GIB
from ..jobs import JobContext, JobError
from ..models import models
from ..runtimes import RuntimeNotReady, WorkerError, runtimes

RUNTIME = "dub"
# One pipeline stage on the GPU at a time across all dub/audiobook/tool jobs.
gpu = threading.Lock()


def acquire_gpu(ctx: JobContext) -> None:
    if not gpu.acquire(blocking=False):
        ctx.update(message="Waiting for another audio job to finish…")
        while not gpu.acquire(timeout=0.5):
            ctx.check_cancelled()


def free_vram(need_gb: float) -> None:
    """Unload resident models until ``need_gb`` fits (Windows spills over-committed VRAM into slow shared RAM)."""
    need = need_gb * GIB
    if system.vram_free_bytes() >= need:
        return
    models.sync_ollama()  # chat models Ollama loaded on request count as resident too
    loaded = [m for m in db.list_installed() if m.status == "loaded"]
    loaded.sort(key=lambda m: m.runtime != "ollama")
    for m in loaded:
        if system.vram_free_bytes() >= need:
            return
        events.log("info", "dub", f"Unloading {m.name} to make room for a dubbing stage")
        try:
            models.unload(m.id)
        except Exception as exc:  # eviction is best-effort
            events.log("warn", "dub", f"Could not unload {m.name}: {exc}")


def release_stage_models() -> None:
    """Drop the dub worker's models (no-op when the worker isn't running)."""
    if runtimes.info(RUNTIME).running:
        try:
            runtimes.request(RUNTIME, "POST", "/unload", timeout=60, start=False)
        except WorkerError as exc:
            events.log("warn", "dub", f"Could not release dub stage models: {exc}")


def call(ctx: JobContext, path: str, payload: dict[str, Any], label: str, span: tuple[float, float] | None = None,
         timeout: float = 7200) -> dict[str, Any]:
    """POST to the dub worker while mirroring its ``/progress`` into the job (``span`` maps it onto a slice of
    the job's progress bar). Cancelling the job interrupts the worker."""
    try:
        runtimes.ensure_running(RUNTIME)
    except RuntimeNotReady as exc:
        raise JobError("The dubbing runtime is not installed yet — install it from the Dub page.") from exc
    except WorkerError as exc:
        raise JobError(str(exc)) from exc

    def cancel() -> None:
        try:
            runtimes.request(RUNTIME, "POST", "/cancel", timeout=5, start=False)
        except WorkerError:
            pass

    ctx.on_cancel(cancel)
    ctx.update(message=f"{label}…")
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(runtimes.request, RUNTIME, "POST", path, payload, timeout)
        while not fut.done():
            time.sleep(0.5)
            try:
                p = runtimes.request(RUNTIME, "GET", "/progress", timeout=5, start=False)
            except WorkerError:
                continue
            total, step = p.get("total") or 0, p.get("step") or 0
            msg = p.get("message") or label
            if total and span:
                ctx.update(progress=round(span[0] + (span[1] - span[0]) * min(step / total, 1.0), 3),
                           message=f"{msg} ({step}/{total})" if total < 10000 else msg)
            else:
                ctx.update(message=f"{msg}…")
        try:
            result = fut.result()
        except WorkerError as exc:
            ctx.check_cancelled()
            raise JobError(str(exc)) from exc
    if span:
        ctx.update(progress=span[1])
    return result
