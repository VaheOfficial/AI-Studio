"""Where model weights live, and moving them: the models folder defaults to ``<data>/models`` and can be moved (e.g. to an
SSD for faster loads). A move unloads local models, moves the folder (a rename on the same drive, a copy with progress
otherwise), rewrites every installed model's path and then switches the setting. Ollama and LM Studio keep their own
model stores and are not moved."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import config, db, events
from .events import bus
from .jobs import JobContext, JobError, RateMeter, jobs
from .schemas import EvModelUpdate, Job, StorageInfo

SETTING = "models_dir"
DEFAULT_MODELS_DIR = config.DATA_DIR / "models"


class StorageError(ValueError):
    """User-facing reason a move can't start."""


def apply() -> None:
    """At startup: use the models folder from Settings (after a move)."""
    chosen = db.get_setting_values().get(SETTING)
    if chosen:
        config.MODELS_DIR = Path(chosen)
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)


def _size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue
    return total


def info() -> StorageInfo:
    current = config.MODELS_DIR
    try:
        free = shutil.disk_usage(current).free
    except OSError:
        free = 0
    return StorageInfo(models_dir=str(current), default_models_dir=str(DEFAULT_MODELS_DIR),
                       size_bytes=_size(current) if current.is_dir() else 0, free_bytes=free,
                       data_dir=str(config.DATA_DIR))


def _check(target: Path) -> None:
    current = config.MODELS_DIR.resolve()
    if not target.is_absolute():
        raise StorageError("Give a full path, e.g. D:\\AI Models")
    target = target.resolve()
    if target == current:
        raise StorageError("The models are already there")
    if current in target.parents:
        raise StorageError("The new folder can't be inside the current models folder")
    if target in current.parents:
        raise StorageError("The new folder can't contain the current models folder; pick an empty folder instead")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise StorageError(f"{target} is not an empty folder; pick an empty or new one")
    if jobs.find_active(lambda j: j.kind in ("download", "generate", "storage")):
        raise StorageError("Wait for running downloads and generations to finish first")


def move(target_path: str, adopt: bool = False) -> Job:
    target = Path(target_path.strip().strip('"'))
    if adopt:
        return use(target)
    _check(target)
    return jobs.submit("storage", f"Move models to {target}", lambda ctx: _move(ctx, target.resolve()))


def use(target: Path) -> Job:
    """Make an existing folder the models folder without moving anything, and register the models in it: a
    folder another copy of the studio keeps its models in. Models already installed stay where they are and
    stay installed; new downloads go to the new folder."""
    if not target.is_absolute():
        raise StorageError("Give a full path, e.g. D:\\AI Models")
    if not target.is_dir():
        raise StorageError(f"{target} is not a folder")
    target = target.resolve()
    if target == config.MODELS_DIR.resolve():
        raise StorageError("That is the models folder already")
    if jobs.find_active(lambda j: j.kind in ("download", "storage")):
        raise StorageError("Wait for running downloads to finish first")

    def run(ctx: JobContext) -> None:
        from . import library  # late: library reads the models folder this sets

        db.set_setting_value(SETTING, None if target == DEFAULT_MODELS_DIR.resolve() else str(target))
        config.MODELS_DIR = target
        ctx.update(message="Looking for models…", progress=-1)
        found = library.rescan()
        ctx.update(progress=1.0, message=f"Models folder is now {target}: {len(found.added)} model{'' if len(found.added) == 1 else 's'} found there")

    return jobs.submit("storage", f"Use models in {target}", run)


def _unload_local() -> None:
    from .models import models  # late: models imports this module's settings via config

    for m in db.list_installed():
        if m.status == "loaded" and m.runtime not in ("ollama", "lmstudio", "openrouter", "tencent-cloud", "remote"):
            events.log("info", "storage", f"Unloading {m.name} before moving its files")
            models.unload(m.id)


def _move(ctx: JobContext, target: Path) -> None:
    source = config.MODELS_DIR.resolve()
    ctx.update(message="Unloading models…")
    _unload_local()
    total = _size(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    same_drive = os.path.splitdrive(str(source))[0].lower() == os.path.splitdrive(str(target))[0].lower()
    if not same_drive and total > shutil.disk_usage(target.parent).free:
        raise JobError(f"Not enough free space on {target.drive}: needs {total / 1e9:.1f} GB")
    if same_drive:
        ctx.update(message="Moving (same drive: renaming)…", progress=-1)
        if target.exists():
            target.rmdir()  # checked empty
        os.replace(source, target)
    else:
        try:
            _copy_all(ctx, source, target, total)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)  # checked empty before: only our partial copy is there
            raise
    _repoint(source, target)
    db.set_setting_value(SETTING, None if target == DEFAULT_MODELS_DIR.resolve() else str(target))
    config.MODELS_DIR = target
    if not same_drive:
        ctx.update(message="Removing the old copy…")
        shutil.rmtree(source, ignore_errors=True)
    ctx.update(progress=1.0, message=f"Models are now in {target}")


def _copy_all(ctx: JobContext, source: Path, target: Path, total: int) -> None:
    """Copy with byte progress; nothing is removed until everything is copied (a failure leaves the original)."""
    done = 0
    meter = RateMeter()
    chunk = 16 * 2**20
    for root, _dirs, files in os.walk(source):
        rel = Path(root).relative_to(source)
        (target / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            ctx.check_cancelled()
            src, dst = Path(root) / name, target / rel / name
            with src.open("rb") as fi, dst.open("wb") as fo:
                while block := fi.read(chunk):
                    fo.write(block)
                    done += len(block)
                    speed = meter.sample(done)
                    ctx.update(progress=round(done / total, 4) if total else -1, bytes_done=done, bytes_total=total,
                               speed_bps=round(speed) if speed else None, message=f"Copying {name}")
            shutil.copystat(src, dst)


def _repoint(source: Path, target: Path) -> None:
    """Installed models under the old folder now point at the new one."""
    old = str(source)
    for m in db.list_installed():
        if m.path == old or m.path.startswith(old + os.sep):
            moved = m.model_copy(update={"path": str(target) + m.path[len(old):]})
            db.upsert_installed(moved)
            bus.publish(EvModelUpdate(model=moved))
