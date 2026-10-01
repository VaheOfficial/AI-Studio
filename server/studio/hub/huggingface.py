"""Hugging Face side of the hub: search (including LM Studio's ``lmstudio-community`` catalog) and repo detail
with installable variants, companions from base pipelines, fit on this machine and related quantized repos."""

from __future__ import annotations

import fnmatch
import re
from typing import Any

import httpx
from huggingface_hub import HfApi, ModelInfo
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from .. import catalog, db, image_models, settings
from ..catalog import Spec
from ..schemas import InstalledModel, ModelKind
from ..schemas_hub import HubCompanions, HubFile, HubRepo, HubSearchResult, HubSort, HubVariant
from . import variants
from .cache import cached

LMSTUDIO_ORG = "lmstudio-community"
_SEARCH_TTL_S = 300
_INFO_TTL_S = 600
_SORT = {"downloads": "downloads", "trending": "trending_score", "likes": "likes", "updated": "last_modified"}
_EXPAND = ["downloads", "likes", "gated", "pipeline_tag", "library_name", "tags", "lastModified"]


class HubError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def _token() -> str | bool:
    # False, not None: never fall back to a token cached by some other tool on this machine.
    return settings.load().hf_token or False


def _call(what: str, fn: Any) -> Any:
    try:
        return fn()
    except RepositoryNotFoundError as exc:
        raise HubError(f"{what}: not found on Hugging Face (or private — set an HF token in Settings)", 404) from exc
    except GatedRepoError as exc:
        raise HubError(f"{what} is gated: accept its terms on huggingface.co and set an HF token in Settings", 403) from exc
    except (HfHubHTTPError, httpx.HTTPError, OSError) as exc:
        raise HubError(f"Hugging Face request failed ({what}): {exc}") from exc


def _license(tags: list[str]) -> str | None:
    return next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None)


def _result(m: ModelInfo) -> HubSearchResult:
    tags = list(m.tags or [])
    author, _, name = m.id.rpartition("/")
    return HubSearchResult(
        id=m.id, source="hf", name=name, author=author or None, kind=variants.kind_of(m.pipeline_tag, tags),
        task=m.pipeline_tag, downloads=m.downloads, likes=m.likes,
        updated_at=m.last_modified.isoformat() if m.last_modified else None, license=_license(tags),
        gated=bool(m.gated), formats=variants.formats_from_tags(tags), tags=[],
    )


def _is_adapter(m: ModelInfo) -> bool:
    """LoRA / adapter repos: add-ons for a base model, which no studio runtime applies."""
    return any(t == "lora" or t.startswith("base_model:adapter:") for t in m.tags or [])


def search(query: str, task: str | None, sort: HubSort, gguf: bool, lmstudio: bool, limit: int = 40
           ) -> list[HubSearchResult]:
    """``lmstudio`` restricts to LM Studio's curated GGUF uploads (the builds its in-app catalog downloads).
    Adapters are dropped; the query over-fetches so ``limit`` real models usually remain."""
    kwargs: dict[str, Any] = {"search": query or None, "pipeline_tag": task, "sort": _SORT[sort], "limit": limit * 3,
                              "expand": _EXPAND}
    if gguf or lmstudio:
        kwargs["filter"] = "gguf"
    if lmstudio:
        kwargs["author"] = LMSTUDIO_ORG

    def run() -> list[HubSearchResult]:
        found = (m for m in HfApi(token=_token()).list_models(**kwargs) if not _is_adapter(m))
        return [_result(m) for m, _ in zip(found, range(limit))]

    key = ("hf-search", query, task, sort, gguf, lmstudio, limit)
    return cached(key, _SEARCH_TTL_S, lambda: _call("search", run))


def info(repo: str) -> ModelInfo:
    return cached(("hf-info", repo), _INFO_TTL_S, lambda: _call(
        repo, lambda: HfApi(token=_token()).model_info(repo, files_metadata=True)))


# ------------------------------------------------------------------ detail

_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
# headings, images/badges, HTML, tables, fences, quotes, rules, bold-only labels and list items (usually link dumps)
_SKIP_LINE = re.compile(r"^\s*(#|!\[|\[!\[|<|\||```|>|-{3,}|\*\*?[A-Z][^*]*\*\*?:?\s*$|[-*+]\s|\d+\.\s)")


def _summary(repo: str) -> str | None:
    """First prose paragraph of the model card, without headings, badges, HTML or tables."""
    def fetch() -> str | None:
        token = settings.load().hf_token
        try:
            r = httpx.get(f"https://huggingface.co/{repo}/raw/main/README.md", timeout=10, follow_redirects=True,
                          headers={"Authorization": f"Bearer {token}"} if token else None)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        text = _FRONT_MATTER.sub("", r.text.replace("\r\n", "\n"))
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        paragraphs = []
        for block in re.split(r"\n\s*\n", text):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip() and not _SKIP_LINE.match(ln)]
            prose = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", " ".join(lines))
            prose = re.sub(r"<[^>]+>", "", prose).strip()
            if len(prose) >= 60:
                paragraphs.append(prose)
            if sum(len(p) for p in paragraphs) > 400:
                break
        summary = " ".join(paragraphs)
        return summary[:700].rsplit(" ", 1)[0] + "…" if len(summary) > 700 else summary or None
    return cached(("hf-summary", repo), _INFO_TTL_S, fetch)


def _files(i: ModelInfo) -> dict[str, int]:
    return {s.rfilename: int(s.size or 0) for s in i.siblings or []}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _base_pipeline(repo: str, files: dict[str, int], base_models: list[str]) -> tuple[str, dict[str, int], bool] | None:
    """The diffusers pipeline that alternative denoiser weights plug into: this repo or its declared base."""
    if "model_index.json" in files:
        return repo, files, bool(info(repo).gated)
    for base in base_models[:3]:
        try:
            bi = info(base)
        except HubError:
            continue
        bfiles = _files(bi)
        if "model_index.json" in bfiles:
            return base, bfiles, bool(bi.gated)
    return None


def _installed_match(repo: str, files: list[str], fmt: str, quant: str | None,
                     installed: list[InstalledModel]) -> str | None:
    wanted = set(files)
    for m in installed:
        if m.source_repo != repo:
            continue
        if m.files and wanted <= set(m.files):
            return m.id
        if not m.files and m.format == fmt and m.quant == quant:  # pulled through Ollama: no local file list
            return m.id
    return None


def _preset_variant(spec: Spec, files: dict[str, int], installed_ids: set[str]) -> HubVariant:
    patterns = spec.source.allow_patterns
    paths = sorted(p for p in files if patterns is None or any(fnmatch.fnmatch(p, pat) for pat in patterns))
    fmt, quant = variants.detect(paths)
    return HubVariant(
        id=f"catalog:{spec.id}", ref=spec.id, label="Studio preset", format=fmt, quant=quant, kind=spec.kind,
        files=paths, size_bytes=sum(files[p] for p in paths), vram_gb=spec.vram_gb,
        fit=catalog.compute_fit(spec.vram_gb, spec.runtime), runtimes=[] if spec.runtime == "remote" else [spec.runtime],
        note=spec.notes, recommended=True, installed_id=spec.id if spec.id in installed_ids else None,
    )


def _variant(repo: str, d: variants.Draft, base: tuple[str, dict[str, int], bool] | None,
             installed: list[InstalledModel]) -> HubVariant:
    companions = None
    notes = [d.note] if d.note else []
    runtimes = list(d.runtimes)
    base_bytes = 0  # text encoders / VAE the denoiser runs with, for the VRAM estimate
    if d.needs_base:
        comp_files, comp_note = variants.companion_files(base[1], d) if base else ([], None)
        base_bytes = sum(base[1][f] for f in comp_files) if base else 0
        reuse = image_models.installed_base(repo) if d.kind == "image" else None
        if reuse:
            # The loader pairs these weights with the installed pipeline, so nothing else is downloaded — which also
            # sidesteps gated base repos (FLUX.1-dev GGUF quants run on the ungated NF4 pipeline's encoders).
            notes.append(f"Uses the text encoders and VAE of your installed {reuse[0].name}.")
        elif base and comp_files:
            companions = HubCompanions(repo=base[0], files=comp_files, size_bytes=base_bytes, gated=base[2])
        else:
            runtimes = []
            notes.append(comp_note or "No diffusers base pipeline found in this repo's base_model metadata, so the "
                         "rest of the pipeline can't be assembled.")
    vram = variants.vram_gb(d, base_bytes)
    return HubVariant(
        id=d.id, ref=f"hf:{repo}#{d.id}", label=d.label, format=d.format, quant=d.quant, kind=d.kind, files=d.files,
        size_bytes=d.size, companions=companions, vram_gb=vram,
        fit=catalog.compute_fit(vram, runtimes[0] if runtimes else "diffusers"), runtimes=runtimes,
        note=" ".join(notes) or None, installed_id=_installed_match(repo, d.files, d.format, d.quant, installed),
    )


def _recommend(vs: list[HubVariant], kind: ModelKind | None) -> None:
    """Flag one sensible default: Q4_K_M for LLMs when it fits, otherwise the largest variant that fits the GPU."""
    if any(v.recommended for v in vs):
        return
    usable = [v for v in vs if v.runtimes and v.fit == "yes"]
    pick = next((v for v in usable if kind in (None, "text") and v.quant == "Q4_K_M"), None)
    pick = pick or max(usable, key=lambda v: v.size_bytes + (v.companions.size_bytes if v.companions else 0),
                       default=None)
    if pick:
        pick.recommended = True


def _related(repo: str, name: str, kind: ModelKind | None, has_gguf: bool) -> list[HubSearchResult]:
    def fetch() -> list[HubSearchResult]:
        api = HfApi(token=_token())
        found = list(api.list_models(filter=f"base_model:quantized:{repo}", sort="downloads", limit=12,
                                     expand=_EXPAND))
        if not found and kind in (None, "text") and not has_gguf:
            found = list(api.list_models(search=name, filter="gguf", sort="downloads", limit=8, expand=_EXPAND))
        return [_result(m) for m in found if m.id != repo]
    return cached(("hf-related", repo), _INFO_TTL_S, lambda: _call(f"{repo} quantizations", fetch))


def repo(repo_id: str) -> HubRepo:
    i = info(repo_id)
    files = _files(i)
    tags = list(i.tags or [])
    kind = variants.kind_of(i.pipeline_tag, tags)
    card = i.card_data.to_dict() if i.card_data else {}
    base_models = _as_list(card.get("base_model"))
    drafts = variants.group(files, kind, tags)
    installed = db.list_installed()
    out = [_preset_variant(s, files, {m.id for m in installed})
           for s in catalog.SPECS if s.source.type == "hf" and s.source.repo == repo_id]
    base = _base_pipeline(repo_id, files, base_models) if any(d.needs_base for d in drafts) else None
    out += [_variant(repo_id, d, base, installed) for d in drafts]
    _recommend(out, kind)
    author, _, name = repo_id.rpartition("/")
    return HubRepo(
        id=repo_id, source="hf", name=name, author=author or None, kind=kind, task=i.pipeline_tag,
        license=card.get("license_name") or card.get("license") or _license(tags), gated=bool(i.gated),
        base_models=base_models, downloads=i.downloads, likes=i.likes,
        updated_at=i.last_modified.isoformat() if i.last_modified else None,
        tags=[t for t in tags if ":" not in t][:12], summary=_summary(repo_id), url=f"https://huggingface.co/{repo_id}",
        files=[HubFile(path=p, size=s) for p, s in sorted(files.items())], variants=out,
        related=_related(repo_id, name, kind, any(d.format == "gguf" for d in drafts)),
    )
