"""Hugging Face snapshot downloads with byte-level progress and hard cancellation."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from huggingface_hub import HfApi
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from .osenv import NO_WINDOW
from . import config
from .jobs import JobContext, JobError, RateMeter
from .proc import kill_tree
from .schemas import ModelSource

_POLL_S = 0.5


def _matches(name: str, patterns: list[str] | None) -> bool:
    return patterns is None or any(fnmatch.fnmatch(name, p) for p in patterns)


def remote_files(source: ModelSource, token: str | None) -> dict[str, int]:
    """Sizes of the files ``snapshot_download`` will fetch for this source."""
    try:
        info = HfApi(token=token or False).model_info(source.repo, revision=source.revision, files_metadata=True)
    except GatedRepoError as exc:
        raise JobError(gated_message(source.repo)) from exc
    except RepositoryNotFoundError as exc:
        raise JobError(f"Hugging Face repo {source.repo} not found (or private: set an HF token in Settings)") from exc
    except HfHubHTTPError as exc:
        raise JobError(f"Could not query {source.repo} on Hugging Face: {exc}") from exc
    return {s.rfilename: s.size or 0 for s in info.siblings or [] if _matches(s.rfilename, source.allow_patterns)}


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except FileNotFoundError:
                pass  # renamed from .incomplete while walking
    return total


def local_files(path: Path) -> list[str]:
    """Files under ``path`` relative to it (POSIX separators), without Hugging Face's download metadata."""
    return sorted(p.relative_to(path).as_posix() for p in path.rglob("*")
                  if p.is_file() and ".cache" not in p.relative_to(path).parts)


def gated_message(repo: str) -> str:
    return (f"{repo} is gated: accept its terms at https://huggingface.co/{repo} with your account and set an "
            "HF token (read access) in Settings, then install again.")


def _storage_error(dest: Path, exc: OSError) -> JobError:
    return JobError(f"Storage disconnected or unwritable ({dest}): {exc}. Reconnect the data drive and start the "
                    "install again; files already downloaded will be reused.")


def download(ctx: JobContext, source: ModelSource, dest: Path, token: str | None,
             progress_span: tuple[float, float] = (0.0, 1.0)) -> int:
    """Download ``source`` into ``dest`` reporting progress into ``ctx``. Returns the downloaded files' size.

    ``dest`` may already hold other files (a second source's companions, LM Studio's library): progress counts
    only what this call adds on top of the files it finds complete."""
    lo, hi = progress_span
    wanted = remote_files(source, token)
    total = sum(wanted.values())
    try:
        dest.mkdir(parents=True, exist_ok=True)
        already = sum(size for f, size in wanted.items() if (dest / f).is_file() and (dest / f).stat().st_size == size)
        baseline = dir_size(dest)
    except OSError as exc:
        raise _storage_error(dest, exc) from exc
    needed = total - already

    env = dict(os.environ)
    env.update({"HF_HOME": str(config.CACHE_DIR / "hf"), "HF_HUB_DISABLE_PROGRESS_BARS": "1",
                "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "PYTHONUTF8": "1"})
    env.pop("HF_TOKEN", None)
    if token:
        env["HF_TOKEN"] = token
    args = {"repo": source.repo, "dest": str(dest), "revision": source.revision,
            "allow_patterns": source.allow_patterns}
    proc = subprocess.Popen([str(config.SERVER_PYTHON), "-m", "studio._hf_fetch", json.dumps(args)],
                            cwd=config.SERVER_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    ctx.on_cancel(lambda: kill_tree(proc))
    output: list[str] = []
    reader = threading.Thread(target=lambda: output.extend(proc.stdout or []), daemon=True)
    reader.start()

    meter = RateMeter()
    ctx.update(bytes_total=total or None, message=f"Downloading {source.repo}")
    while proc.poll() is None:
        time.sleep(_POLL_S)
        try:
            done = max(0, dir_size(dest) - baseline)
        except OSError as exc:
            kill_tree(proc)
            raise _storage_error(dest, exc) from exc
        speed = meter.sample(done)
        frac = min(done / needed, 1.0) if needed else 1.0
        ctx.update(progress=round(lo + (hi - lo) * frac, 4) if total else -1, bytes_done=min(already + done, total),
                   speed_bps=round(speed) if speed is not None else None)
    reader.join(timeout=5)
    ctx.check_cancelled()
    if proc.returncode != 0:
        text = "".join(output)
        if "GatedRepoError" in text or "401 Client Error" in text or "403 Client Error" in text:
            raise JobError(gated_message(source.repo))
        if not dest.exists() or "OSError" in text or "No space left" in text:
            raise JobError(f"Download of {source.repo} failed with a storage error:\n{text[-1500:]}")
        raise JobError(f"Download of {source.repo} failed (exit {proc.returncode}):\n{text[-1500:]}")
    ctx.update(bytes_done=total, speed_bps=None, progress=hi)
    return total
