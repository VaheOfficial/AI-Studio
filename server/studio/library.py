"""The models folder as its own record.

Every model's folder carries a small manifest (``studio-model.json``) that says what the studio installed there. A
folder of models can then be picked up by another copy of the studio, after a reinstall, or after it was put in
place by hand: ``rescan`` registers what it finds in the models folder and forgets models whose folder is gone.
Folders from before the manifest existed are recognized from what they contain, as far as that can be told.

Models that live elsewhere (Ollama's and LM Studio's own stores, cloud models) are not part of this.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import catalog, config, db, events, gguf_meta
from .events import bus
from .hub import variants
from .schemas import EvModelRemoved, EvModelUpdate, InstalledModel, RescanResult

MANIFEST = "studio-model.json"
# Runtimes whose models are not folders of the models folder
_ELSEWHERE = ("ollama", "lmstudio", "openrouter", "tencent-cloud", "remote")
# ``general.architecture`` of GGUF files that are diffusion models, not language models
_DIFFUSION_GGUF = {"flux", "flux2", "sd1", "sdxl", "sd3", "aura", "hidream", "lumina2", "qwen_image", "chroma",
                   "z_image", "wan", "ltxv", "hyvid", "cosmos"}
_VIDEO_GGUF = {"wan", "ltxv", "hyvid", "cosmos"}
_VIDEO_PIPELINES = ("Wan", "LTX", "HunyuanVideo", "CogVideoX", "Mochi")
_WEIGHTS_MIN = 200 * 2**20  # a root file smaller than this is not a model's weights


class LibraryError(ValueError):
    """User-facing reason the models folder can't be scanned."""


def _in_folder(m: InstalledModel) -> bool:
    return m.runtime not in _ELSEWHERE and "://" not in m.path


def _same(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def write_manifest(m: InstalledModel) -> None:
    """Record ``m`` in its own folder. Best effort: a folder that can't be written (a drive that dropped out, a
    read-only share) just stays without one."""
    folder = Path(m.path)
    if not _in_folder(m) or not folder.is_dir():
        return
    data = m.model_dump(exclude={"path", "status", "error"}, exclude_none=True)
    try:
        current = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = None
    if current == data:
        return
    try:
        (folder / MANIFEST).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        events.log("debug", "library", f"No manifest written for {m.name}: {exc}")


def backfill() -> None:
    """At startup: give every installed model's folder its manifest (models installed before manifests existed)."""
    for m in db.list_installed():
        write_manifest(m)


def _read_manifest(folder: Path) -> InstalledModel | None:
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        return InstalledModel.model_validate({**data, "path": str(folder), "status": "ready"})
    except (OSError, ValueError):
        return None


def _size(folder: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue
    return total


def _files(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file() and ".cache" not in p.parts and ".quantized" not in p.parts and p.name != MANIFEST)


def _guess(folder: Path) -> InstalledModel | None:
    """What a folder without a manifest holds, from its name and contents; None when that can't be told."""
    files = _files(folder)
    if not files:
        return None
    stamp = datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    common = dict(id=folder.name, catalog_id=folder.name, name=folder.name, path=str(folder), size_bytes=_size(folder),
                  installed_at=stamp, status="ready")
    spec = catalog.get(folder.name)
    if spec is not None and spec.runtime not in _ELSEWHERE:  # a curated model keeps the folder name of its catalog id
        fmt, quant = variants.detect(files)
        return InstalledModel(**{**common, "name": spec.name}, kind=spec.kind, runtime=spec.runtime, format=fmt,
                              quant=quant)
    root = [f for f in files if "/" not in f]
    ggufs = [f for f in root if f.lower().endswith(".gguf") and "mmproj" not in f.lower()]
    checkpoints = [f for f in root if f.lower().endswith(".safetensors") and (folder / f).stat().st_size >= _WEIGHTS_MIN]
    weights = ggufs or checkpoints
    quant = variants.gguf_quant(ggufs[0]) if ggufs else None
    if "model_index.json" in root:
        try:
            cls = str(json.loads((folder / "model_index.json").read_text(encoding="utf-8")).get("_class_name") or "")
        except (OSError, ValueError):
            cls = ""
        video = cls.startswith(_VIDEO_PIPELINES)
        fmt = "gguf" if ggufs else "safetensors" if checkpoints else "diffusers"
        return InstalledModel(**common, kind="video" if video else "image",
                              runtime="diffusers-video" if video else "diffusers", format=fmt, quant=quant,
                              files=[*weights, *(f for f in files if f not in weights)])
    if ggufs:
        try:
            arch = gguf_meta.architecture(folder / ggufs[0])
        except (OSError, ValueError):
            arch = None
        if arch in _DIFFUSION_GGUF:  # denoiser weights that run on an installed base pipeline
            video = arch in _VIDEO_GGUF
            return InstalledModel(**common, kind="video" if video else "image",
                                  runtime="diffusers-video" if video else "diffusers", format="gguf", quant=quant,
                                  files=ggufs)
        return InstalledModel(**common, kind="text", runtime="llamacpp", format="gguf", quant=quant,
                              files=[f for f in root if f.lower().endswith(".gguf")])
    if "model.bin" in root and any(f.startswith("vocabulary") for f in root):
        return InstalledModel(**common, kind="stt", runtime="faster-whisper", format="ct2", files=root)
    return None


def _unfinished(folder: Path) -> bool:
    """A download is (or was) writing here: Hugging Face keeps ``*.incomplete`` files until a file is whole."""
    cache = folder / ".cache"
    return cache.is_dir() and any(cache.rglob("*.incomplete"))


def rescan() -> RescanResult:
    """Bring the list of installed models in line with the models folder: register folders that hold a model and
    are not listed, forget listed models whose folder is no longer there."""
    root = config.MODELS_DIR
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError as exc:
        raise LibraryError(f"The models folder {root} can't be read ({exc.strerror or exc}). Is its drive "
                           "connected?") from exc
    installed = db.list_installed()
    ids = {m.id for m in installed}
    added: list[InstalledModel] = []
    unrecognized: list[str] = []
    for folder in folders:
        known = next((m for m in installed if _same(m.path, folder)), None)
        if known is not None:
            write_manifest(known)
            continue
        if _unfinished(folder):
            unrecognized.append(f"{folder.name} (an unfinished download)")
            continue
        m = _read_manifest(folder) or _guess(folder)
        if m is None:
            if any(folder.iterdir()):
                unrecognized.append(folder.name)
            continue
        if m.id in ids:  # another model already goes by this id: keep both
            n = 2
            while f"{m.id}-{n}" in ids:
                n += 1
            m = m.model_copy(update={"id": f"{m.id}-{n}"})
        if not m.size_bytes:
            m = m.model_copy(update={"size_bytes": _size(folder)})
        ids.add(m.id)
        db.upsert_installed(m)
        write_manifest(m)
        bus.publish(EvModelUpdate(model=m))
        added.append(m)
    removed: list[str] = []
    for m in installed:
        # Only models that belong in this folder: one kept elsewhere may just be on a drive that isn't connected
        inside = _in_folder(m) and _same(Path(m.path).parent, root)
        if inside and m.status != "loading" and not Path(m.path).exists():
            db.delete_installed(m.id)
            bus.publish(EvModelRemoved(id=m.id))
            removed.append(m.name)
    if added or removed:
        events.log("info", "library", f"Rescanned {root}: {len(added)} added, {len(removed)} removed")
    return RescanResult(added=added, removed=removed, unrecognized=unrecognized)
