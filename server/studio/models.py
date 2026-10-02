"""Installed-model lifecycle: install (download / pull / import), delete, load, unload."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import (catalog, config, db, events, hf, image_models, library, llamacpp, lmstudio, ollama, openrouter_catalog,
               settings, system)
from .catalog import GIB, Spec
from .hub import variants
from .events import bus
from .jobs import JobContext, JobError, RateMeter, jobs
from .proc import kill_tree
from .runtimes import RUNTIMES, RuntimeNotReady, runtimes
from .runtimes import envs
from .schemas import EvModelRemoved, EvModelUpdate, InstalledModel, InstalledStatus, Job, TextEncoderMode


class ModelError(Exception):
    """User-facing failure with an HTTP status hint."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


_LLM_RUNTIMES = ("ollama", "llamacpp", "lmstudio")
_LLM_CONTEXT_GB = 1.5  # KV cache + buffers at the agent's 16k context, on top of the weights


def _await_release(need: int, timeout_s: float = 15.0) -> None:
    """After an unload, wait until the driver reports the VRAM free: Ollama and the workers return before their
    memory is released, and deciding right away (fits? offload?) would see the old usage."""
    start = last_rise = time.monotonic()
    last = system.vram_free_bytes()
    while time.monotonic() - start < timeout_s:
        if last >= need:
            return
        time.sleep(0.25)
        now = system.vram_free_bytes()
        if now > last + 64 * 1024 * 1024:
            last, last_rise = now, time.monotonic()
        elif time.monotonic() - last_rise > 1.5:
            return  # stopped rising: this unload has released what it will


def _ollama_path(tag: str) -> str:
    return f"ollama://{tag}"


def ollama_tag(m: InstalledModel) -> str:
    return m.path.removeprefix("ollama://")


class ModelManager:
    def __init__(self) -> None:
        # Worker models loaded with CPU offload (they hold little VRAM until they generate)
        self._offloaded: set[str] = set()

    # ------------------------------ queries ------------------------------

    def get(self, model_id: str) -> InstalledModel:
        m = db.get_installed(model_id)
        if m is None:
            raise ModelError(f"Model '{model_id}' is not installed", 404)
        return m

    def set_status(self, model_id: str, status: InstalledStatus, error: str | None = None) -> InstalledModel | None:
        m = db.set_installed_status(model_id, status, error)
        if m:
            bus.publish(EvModelUpdate(model=m))
        return m

    def list(self) -> list[InstalledModel]:
        self.sync_ollama()
        self.sync_lmstudio()
        return db.list_installed()

    def sync_ollama(self) -> None:
        """Mirror the Ollama daemon's model list into ``installed_models`` (catalog installs and
        models pulled outside the studio), and reflect which ones are loaded."""
        if not ollama.version():
            return
        try:
            present = {t["name"]: t for t in ollama.tags()}
            loaded = set(ollama.running_models())
        except ollama.OllamaError as exc:
            events.log("warn", "ollama", f"Could not sync models: {exc}")
            return
        known = {ollama_tag(m): m for m in db.list_installed() if m.runtime == "ollama"}
        for tag, info in present.items():
            status: InstalledStatus = "loaded" if tag in loaded else "ready"
            m = known.get(tag)
            if m is None:
                spec = catalog.by_ollama_tag(tag)
                # "hf.co/<org>/<repo>:<quant>" tags are GGUFs Ollama pulled straight from Hugging Face
                hf_repo, _, hf_quant = tag.removeprefix("hf.co/").rpartition(":")
                from_hf = tag.startswith("hf.co/")
                self.register(InstalledModel(
                    id=spec.id if spec else tag, catalog_id=spec.id if spec else tag,
                    name=spec.name if spec else tag, kind="text", runtime="ollama",
                    source_repo=hf_repo if from_hf else tag.partition(":")[0], format="gguf" if from_hf else "ollama",
                    quant=variants.gguf_quant(hf_quant) if from_hf else None, path=_ollama_path(tag),
                    size_bytes=int(info.get("size", 0)), installed_at=info.get("modified_at") or db.now_iso(),
                    status=status,
                ))
            elif m.status in ("ready", "loaded") and m.status != status:
                self.set_status(m.id, status)
        for tag, m in known.items():
            if tag not in present and m.status != "loading":
                db.delete_installed(m.id)
                bus.publish(EvModelRemoved(id=m.id))

    def sync_lmstudio(self) -> None:
        """Mirror LLMs downloaded inside LM Studio into ``installed_models`` (and drop ones removed there).
        Only while its server runs: `lms` would otherwise launch LM Studio's daemon on every snapshot."""
        if lmstudio.lms_exe() is None or not lmstudio.reachable():
            return
        try:
            present = lmstudio.list_downloaded()
            loaded = lmstudio.list_loaded()
        except (lmstudio.LMStudioError, ValueError) as exc:
            events.log("warn", "lmstudio", f"Could not sync models: {exc}")
            return
        root = lmstudio.models_dir()
        known = {m.id: m for m in db.list_installed() if m.runtime == "lmstudio"}
        by_file = {(Path(m.path) / f).resolve(): m for m in known.values() for f in (m.files or [])}
        seen: set[str] = set()
        for entry in present:
            file = (root / entry["path"]).resolve()
            m = by_file.get(file)
            if m is None:
                rel = Path(entry["path"])
                m = InstalledModel(
                    id=f"lms-{variants.slug(rel.stem)}", catalog_id=f"lms-{variants.slug(rel.stem)}",
                    name=entry.get("displayName") or rel.stem, kind="text", runtime="lmstudio",
                    source_repo=rel.parent.as_posix(), format="gguf", quant=variants.gguf_quant(rel.name),
                    files=[rel.name], path=str(file.parent), size_bytes=int(entry.get("sizeBytes") or 0),
                    installed_at=db.now_iso(), status="ready",
                )
                self.register(m)
            seen.add(m.id)
            status: InstalledStatus = "loaded" if m.id in loaded else "ready"
            if m.status in ("ready", "loaded") and m.status != status:
                self.set_status(m.id, status)
        for model_id, m in known.items():
            if model_id not in seen and m.status != "loading":
                db.delete_installed(model_id)
                bus.publish(EvModelRemoved(id=model_id))

    # ------------------------------ install ------------------------------

    def install(self, catalog_id: str) -> Job:
        spec = catalog.get(catalog_id)
        if spec is None:
            raise ModelError(f"Unknown catalog id '{catalog_id}'", 404)
        if spec.runtime == "remote":
            raise ModelError(f"{spec.name} cannot be installed locally. {spec.notes or ''}".strip(), 400)
        if db.get_installed(spec.id):
            raise ModelError(f"{spec.name} is already installed", 409)
        active = jobs.find_active(lambda j: j.kind == "download" and j.ref == spec.id)
        if active:
            return active.job

        free = system.disk_free_bytes(config.MODELS_DIR)
        if free and spec.size_gb * 1e9 > free:
            raise ModelError(f"Not enough disk space for {spec.name}: needs ~{spec.size_gb:.1f} GB, "
                             f"{free / 1e9:.1f} GB free in {config.MODELS_DIR}", 507)

        env_job = None
        env_name = RUNTIMES[spec.runtime].env
        if env_name:
            env_job = envs.ensure_env_job(env_name, spec.runtime)
        if spec.runtime == "ollama":
            ollama.ensure_running()

        return jobs.submit("download", f"Install {spec.name}", lambda ctx: self._install_job(ctx, spec, env_job),
                           ref=spec.id)

    def _install_job(self, ctx: JobContext, spec: Spec, env_job: Job | None) -> None:
        if spec.source.type == "remote":  # cloud model (e.g. Tencent HY-Image): nothing to download
            self._register(spec, f"{spec.runtime}://{spec.source.repo}", 0)
        elif spec.source.type == "ollama":
            self._register(spec, _ollama_path(spec.source.repo), self.pull_ollama(ctx, spec.source.repo))
        else:
            dest = config.MODELS_DIR / spec.id
            token = settings.load().hf_token
            span = (0.0, 0.7) if spec.runtime == "ollama" else (0.0, 1.0)
            size = hf.download(ctx, spec.source, dest, token, span)
            for extra in spec.extras:
                size += hf.download(ctx, extra, dest, token, span)
            if spec.runtime == "ollama":
                assert spec.ollama_name
                self._register(spec, _ollama_path(spec.ollama_name),
                               self.import_into_ollama(ctx, spec.ollama_name, dest))
            else:
                self._register(spec, str(dest), size, hf.local_files(dest))
        if env_job:
            ctx.update(message=f"Waiting for the runtime environment ({env_job.title})…")
            env_result = jobs.wait_blocking(env_job.id)
            if env_result.status != "done":
                raise JobError(f"{spec.name} was downloaded, but its runtime environment failed: "
                               f"{env_result.error or env_result.status}. Retry via Runtimes → Install.")
        ctx.update(message=f"{spec.name} installed")

    def pull_ollama(self, ctx: JobContext, tag: str) -> int:
        """``ollama pull`` with byte progress; returns the model's size."""
        layers: dict[str, tuple[int, int]] = {}
        meter = RateMeter()

        def on_progress(line: dict) -> None:
            if "digest" in line and line.get("total"):
                layers[line["digest"]] = (int(line.get("completed", 0)), int(line["total"]))
                done = sum(c for c, _ in layers.values())
                total = sum(t for _, t in layers.values())
                speed = meter.sample(done)
                ctx.update(progress=round(done / total, 4) if total else -1, bytes_done=done, bytes_total=total,
                           speed_bps=round(speed) if speed else None, message=line.get("status"))
            else:
                ctx.update(message=line.get("status"))

        ollama.pull(tag, on_progress, lambda: ctx.cancelled)
        ctx.check_cancelled()
        return next((int(t.get("size", 0)) for t in ollama.tags() if t["name"] == tag), 0)

    def import_into_ollama(self, ctx: JobContext, name: str, src: Path) -> int:
        """``ollama create -q q8_0`` from a downloaded safetensors dir (removed afterwards); returns the size."""
        ctx.update(progress=0.72, message=f"Importing into Ollama as {name} (q8_0)…", speed_bps=None)
        ollama.ensure_running()
        ollama.create_from_dir(name, src, "q8_0", on_line=lambda s: ctx.update(message=s),
                               on_proc=lambda p: ctx.on_cancel(lambda: kill_tree(p)))
        ctx.check_cancelled()
        size = next((int(t.get("size", 0)) for t in ollama.tags() if t["name"] == name), 0)
        ctx.log(f"Imported {name}; removing the {src} safetensors copy")
        shutil.rmtree(src, ignore_errors=False)
        return size

    def _register(self, spec: Spec, path: str, size: int, files: list[str] | None = None) -> None:
        fmt, quant = variants.detect(files) if files else (None, None)
        self.register(InstalledModel(
            id=spec.id, catalog_id=spec.id, name=spec.name, kind=spec.kind, runtime=spec.runtime,
            source_repo=spec.source.repo if spec.source.type != "remote" else None,
            format="ollama" if path.startswith("ollama://") else fmt, quant=quant, files=files,
            path=path, size_bytes=size, installed_at=db.now_iso(), status="ready",
        ))

    def register(self, m: InstalledModel) -> None:
        if m.path.startswith("ollama://"):
            # A concurrent Ollama sync may have mirrored the freshly pulled tag under its own id first.
            for other in db.list_installed():
                if other.path == m.path and other.id != m.id:
                    db.delete_installed(other.id)
                    bus.publish(EvModelRemoved(id=other.id))
        db.upsert_installed(m)
        library.write_manifest(m)
        bus.publish(EvModelUpdate(model=m))

    # ------------------------------ delete ------------------------------

    def delete(self, model_id: str) -> None:
        m = self.get(model_id)
        if m.runtime == "openrouter":  # a pinned cloud model: nothing on disk, deleting unpins it
            openrouter_catalog.unpin(openrouter_catalog.slug(m))
            return
        if m.status in ("loaded", "loading"):
            try:
                self.unload(model_id)
            except (ModelError, RuntimeError) as exc:
                events.log("warn", "models", f"Unload before delete failed for {model_id}: {exc}")
        if m.runtime == "ollama":
            ollama.ensure_running()
            ollama.delete(ollama_tag(m))
        elif m.runtime == "lmstudio":
            self._delete_lmstudio_files(m)
        else:
            path = Path(m.path)
            if path.exists():
                if config.MODELS_DIR not in path.resolve().parents:
                    raise ModelError(f"Refusing to delete {path}: outside {config.MODELS_DIR}", 400)
                shutil.rmtree(path)
        db.delete_installed(model_id)
        bus.publish(EvModelRemoved(id=model_id))
        events.log("info", "models", f"Deleted {m.name}")

    @staticmethod
    def _delete_lmstudio_files(m: InstalledModel) -> None:
        """Remove only this model's files from LM Studio's library (other quants of the repo may sit beside them)."""
        root = lmstudio.models_dir().resolve()
        folder = Path(m.path).resolve()
        if root not in folder.parents:
            raise ModelError(f"Refusing to delete {folder}: outside LM Studio's models folder {root}", 400)
        for f in m.files or []:
            (folder / f).unlink(missing_ok=True)
        shutil.rmtree(folder / ".cache", ignore_errors=True)  # Hugging Face download metadata
        while folder != root and folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent

    # --------------------------- load / unload ---------------------------

    def offload_mode(self, m: InstalledModel) -> str:
        """'none' | 'model' | 'sequential' CPU offload for diffusers-style workers."""
        policy = settings.load().offload_policy
        if policy == "gpu":
            return "none"
        if policy == "cpu-offload":
            return "model"
        if policy == "sequential-offload":
            return "sequential"
        return "model" if self._vram_need_gb(m) * GIB > system.vram_free_bytes() else "none"

    def _vram_need_gb(self, m: InstalledModel) -> float:
        if m.kind == "image":  # estimated from the weights actually installed (quantized variants, companions)
            return image_models.vram_need_gb(m)
        spec = catalog.get(m.catalog_id)
        if spec:
            return spec.vram_gb
        return m.size_bytes / GIB + (_LLM_CONTEXT_GB if m.runtime in _LLM_RUNTIMES else 0.0)

    def prepare_ollama_chat(self, tag: str) -> None:
        """Before a chat request to Ollama: it loads the model on demand, bypassing ``_make_room`` — so when the model
        isn't resident, first evict what it wouldn't fit next to (e.g. an image model left from a tool call), like
        any other load. Keeps a big LLM and a diffusion model from sharing VRAM and spilling into system RAM."""
        m = next((x for x in db.list_installed() if x.runtime == "ollama" and ollama_tag(x) == tag), None)
        if m is None:
            return
        try:
            if tag in ollama.running_models():
                return
        except ollama.OllamaError:
            return
        self._make_room(m)

    def _make_room(self, m: InstalledModel) -> None:
        """Evict other resident models until ``m`` fits in free VRAM.

        Windows silently spills over-committed CUDA memory into shared system RAM, which makes
        generation 5-10x slower instead of failing — so we free memory up front, ComfyUI-style.
        LLMs go first (they reload quickly), then other workers' models.
        """
        need = int(self._vram_need_gb(m) * GIB * 1.1)
        if system.vram_free_bytes() >= need:
            return
        # Ollama loads chat models on request, behind our back: refresh which ones are resident so they can be evicted
        self.sync_ollama()
        candidates = [x for x in db.list_installed() if x.id != m.id and x.status == "loaded"]
        candidates.sort(key=lambda x: x.runtime not in _LLM_RUNTIMES)
        for other in candidates:
            if system.vram_free_bytes() >= need:
                return
            events.log("info", "models", f"Unloading {other.name} to make room for {m.name}")
            try:
                self.unload(other.id)
            except Exception as exc:  # eviction is best-effort; loading may still fit with offload
                events.log("warn", "models", f"Could not unload {other.name}: {exc}")
                continue
            _await_release(need)

    def _room_before_generating(self, m: InstalledModel) -> None:
        """A model loaded with CPU offload holds little VRAM while idle, so an LLM may have loaded next to it since;
        generating moves its weights onto the GPU — make room for its full size first."""
        if m.id in self._offloaded:
            self._make_room(m)

    def load(self, model_id: str) -> InstalledModel:
        m = self.get(model_id)
        if m.runtime in ("remote", "openrouter", "tencent-cloud"):
            raise ModelError("Remote models are not loaded locally", 400)
        if m.status == "loaded" and (m.runtime == "ollama" or runtimes.loaded_model(m.runtime) == m.id):
            return m
        if llamacpp.is_draft_model(m):  # before anything is unloaded to make room for it
            raise ModelError(f"{m.name} is a speculative-decoding draft model: it only runs next to the model it "
                             "was made for, not on its own", 400)
        self.set_status(m.id, "loading")
        self._make_room(m)
        try:
            if m.runtime == "ollama":
                ollama.ensure_running()
                ollama.load(ollama_tag(m))
            elif m.runtime == "llamacpp":
                previous = runtimes.loaded_model("llamacpp")
                llamacpp.server.load(m)
                if previous and previous != m.id:  # llama-server holds one model at a time
                    self.set_status(previous, "ready")
            elif m.runtime == "lmstudio":
                lmstudio.load(m, settings.load().llamacpp_ctx_size)
            else:
                previous = runtimes.loaded_model(m.runtime)
                from . import video  # late: video builds on this module

                extra = (image_models.load_options(m) if m.kind == "image" else
                         video.load_options(m) if m.kind == "video" else {})
                offload = self.offload_mode(m)
                runtimes.request(m.runtime, "POST", "/load", timeout=1800, json={
                    "model_id": m.id, "path": m.path, "offload": offload, **extra,
                })
                if previous and previous != m.id:
                    self.set_status(previous, "ready")
                    self._offloaded.discard(previous)
                runtimes.set_loaded(m.runtime, m.id)
                if offload == "none":
                    self._offloaded.discard(m.id)
                else:
                    self._offloaded.add(m.id)
        except Exception as exc:
            self.set_status(m.id, "error", str(exc))
            status = 409 if isinstance(exc, RuntimeNotReady) else 500
            raise ModelError(f"Failed to load {m.name}: {exc}", status) from exc
        return self.set_status(m.id, "loaded") or m

    def set_text_encoder(self, model_id: str, mode: TextEncoderMode) -> InstalledModel:
        """How a local image pipeline holds its large text encoders. Takes effect at the next load, so a loaded
        model is taken out of memory."""
        m = self.get(model_id)
        if m.kind != "image" or m.runtime != "diffusers":
            raise ModelError(f"{m.name} has no text encoder to choose a precision for", 400)
        try:
            if not image_models.large_encoders(image_models.layout(m)):
                raise ModelError(f"{m.name}'s text encoders are small; there is nothing to gain from quantizing "
                                 "them", 400)
        except image_models.LayoutError as exc:
            raise ModelError(str(exc), 409) from exc
        wanted = None if mode == "full" else mode
        if m.text_encoder == wanted:
            return m
        if m.status in ("loaded", "loading"):
            m = self.unload(model_id)
        m = m.model_copy(update={"text_encoder": wanted})
        self.register(m)
        events.log("info", "models", f"{m.name}: text encoder set to {mode}")
        return m

    def unload(self, model_id: str) -> InstalledModel:
        m = self.get(model_id)
        if m.runtime == "ollama":
            if ollama.version():
                ollama.unload(ollama_tag(m))
        elif m.runtime == "llamacpp":
            if runtimes.loaded_model("llamacpp") == m.id:
                llamacpp.server.stop()
        elif m.runtime == "lmstudio":
            lmstudio.unload(m)
        elif runtimes.loaded_model(m.runtime) == m.id:
            runtimes.request(m.runtime, "POST", "/unload", timeout=120, start=False)
            runtimes.set_loaded(m.runtime, None)
        self._offloaded.discard(m.id)
        return self.set_status(m.id, "ready") or m

    def ensure_loaded(self, model_id: str) -> InstalledModel:
        m = self.get(model_id)
        if m.runtime != "ollama" and runtimes.loaded_model(m.runtime) == m.id:
            self._room_before_generating(m)
            return m
        return self.load(model_id)


models = ModelManager()
