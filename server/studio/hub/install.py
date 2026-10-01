"""Install one hub variant: download exactly its files (plus base-pipeline companions) with the resumable download
job, or pull it through Ollama, then record the ``InstalledModel`` with ``source_repo``/``format``/``quant``/``files``."""

from __future__ import annotations

from huggingface_hub import auth_check
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from .. import catalog, config, db, hf, llamacpp, lmstudio, ollama, settings, system
from ..jobs import JobContext, JobError, jobs
from ..models import ModelError, models
from ..runtimes import RUNTIMES
from ..runtimes import envs
from ..schemas import InstalledModel, Job, ModelSource, RuntimeId
from ..schemas_hub import HubInstallRequest, HubRepo, HubVariant
from . import huggingface, ollama_library, variants


def _unique_id(base: str) -> str:
    taken = {m.id for m in db.list_installed()}
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _pick_runtime(v: HubVariant, requested: RuntimeId | None) -> RuntimeId:
    if requested:
        if requested not in v.runtimes:
            raise ModelError(f"{v.label} can't run on {requested}; it runs on {', '.join(v.runtimes)}", 400)
        return requested
    preferred = settings.load().default_local_backend
    if preferred in v.runtimes and (preferred != "lmstudio" or lmstudio.installed()):
        return preferred
    return next(r for r in v.runtimes if r != "lmstudio" or lmstudio.installed())


def _check_access(repo: str, token: str | None) -> None:
    try:
        auth_check(repo, token=token or False)
    except GatedRepoError as exc:
        raise JobError(hf.gated_message(repo)) from exc
    except RepositoryNotFoundError as exc:
        raise JobError(f"{repo} was not found on Hugging Face (or is private: set an HF token in Settings)") from exc
    except HfHubHTTPError as exc:
        raise JobError(f"Could not check access to {repo}: {exc}") from exc


def _wait_for(ctx: JobContext, name: str, setup: Job | None) -> None:
    if setup is None:
        return
    ctx.update(message=f"Waiting for {setup.title}…")
    result = jobs.wait_blocking(setup.id)
    if result.status != "done":
        raise JobError(f"{name} was downloaded, but setting up {setup.title} failed: {result.error or result.status}. "
                       "Retry under Models → Runtimes.")


def install(req: HubInstallRequest) -> Job:
    if req.source == "ollama":
        return _install_ollama_tag(ollama_library.repo(req.repo), req.variant)
    repo = huggingface.repo(req.repo)
    v = next((x for x in repo.variants if x.id == req.variant), None)
    if v is None:
        raise ModelError(f"{req.repo} has no variant '{req.variant}'", 404)
    if v.id.startswith("catalog:"):
        return models.install(v.id.removeprefix("catalog:"))
    if v.installed_id:
        raise ModelError(f"{repo.name} {v.label} is already installed", 409)
    if not v.runtimes:
        raise ModelError(v.note or f"No local runtime can load {v.label}", 400)
    active = jobs.find_active(lambda j: j.kind == "download" and j.ref == v.ref)
    if active:
        return active.job
    runtime = _pick_runtime(v, req.runtime)
    size = v.size_bytes + (v.companions.size_bytes if v.companions else 0)
    free = system.disk_free_bytes()
    if runtime != "ollama" and free and size > free:
        raise ModelError(f"Not enough disk space: {repo.name} {v.label} needs {size / 1e9:.1f} GB, "
                         f"{free / 1e9:.1f} GB free", 507)
    if runtime == "llamacpp":
        setup = llamacpp.ensure_installed_job()
    elif runtime == "ollama":
        ollama.ensure_running()
        setup = None
    else:
        env = RUNTIMES[runtime].env
        setup = envs.ensure_env_job(env, runtime) if env else None
    model_id = _unique_id(variants.slug(f"{repo.name}-{v.quant}" if v.quant else repo.name))
    name = f"{repo.name} {v.quant}" if v.quant else repo.name
    return jobs.submit("download", f"Install {name}", lambda ctx: _run(ctx, repo, v, runtime, model_id, name, setup),
                       ref=v.ref)


def _run(ctx: JobContext, repo: HubRepo, v: HubVariant, runtime: RuntimeId, model_id: str, name: str,
         setup: Job | None) -> None:
    token = settings.load().hf_token
    _check_access(repo.id, token)
    if v.companions and v.companions.repo != repo.id:
        _check_access(v.companions.repo, token)
    common = dict(id=model_id, catalog_id=model_id, name=name, kind=v.kind, runtime=runtime, source_repo=repo.id,
                  format=v.format, quant=v.quant, installed_at=db.now_iso(), status="ready")
    if runtime == "ollama" and v.format == "gguf":
        tag = f"hf.co/{repo.id}:{v.quant or v.label}"  # Ollama pulls GGUFs straight from Hugging Face
        size = models.pull_ollama(ctx, tag)
        models.register(InstalledModel(**common, path=f"ollama://{tag}", size_bytes=size))
    elif runtime == "ollama":
        dest = config.MODELS_DIR / model_id
        hf.download(ctx, ModelSource(type="hf", repo=repo.id, allow_patterns=v.files), dest, token, (0.0, 0.7))
        tag = f"{model_id}:latest"
        size = models.import_into_ollama(ctx, tag, dest)
        models.register(InstalledModel(**{**common, "format": "ollama"}, path=f"ollama://{tag}", size_bytes=size))
    else:
        dest = lmstudio.models_dir() / repo.id if runtime == "lmstudio" else config.MODELS_DIR / model_id
        total = v.size_bytes + (v.companions.size_bytes if v.companions else 0)
        split = v.size_bytes / total if total else 1.0
        size = hf.download(ctx, ModelSource(type="hf", repo=repo.id, allow_patterns=v.files), dest, token, (0.0, split))
        files = list(v.files)
        if v.companions:
            size += hf.download(ctx, ModelSource(type="hf", repo=v.companions.repo, allow_patterns=v.companions.files),
                                dest, token, (split, 1.0))
            files += [f for f in v.companions.files if f not in files]
        models.register(InstalledModel(**common, files=files, path=str(dest), size_bytes=size))
    _wait_for(ctx, name, setup)
    ctx.update(message=f"{name} installed")


def _install_ollama_tag(repo: HubRepo, tag: str) -> Job:
    v = next((x for x in repo.variants if x.id == tag), None)
    if v is None:
        raise ModelError(f"{repo.id} has no tag '{tag}'", 404)
    if v.installed_id:
        raise ModelError(f"{repo.id}:{tag} is already installed", 409)
    active = jobs.find_active(lambda j: j.kind == "download" and j.ref == v.ref)
    if active:
        return active.job
    ollama.ensure_running()
    full = f"{repo.id}:{tag}"
    spec = catalog.by_ollama_tag(full)  # a curated pick keeps its catalog id and friendly name

    def run(ctx: JobContext) -> None:
        size = models.pull_ollama(ctx, full)
        models.register(InstalledModel(
            id=spec.id if spec else _unique_id(variants.slug(full)), catalog_id=spec.id if spec else full,
            name=spec.name if spec else full, kind="text", runtime="ollama", source_repo=repo.id, format="ollama",
            quant=v.quant, path=f"ollama://{full}", size_bytes=size, installed_at=db.now_iso(), status="ready"))
        ctx.update(message=f"{full} installed")

    return jobs.submit("download", f"Pull {full}", run, ref=v.ref)
