"""What the agent is told it can use. Only models that can actually run are passed to it: a cloud model whose API
key isn't set, a remote-only model or a broken install would just fail, so it is left out entirely rather than
listed with a caveat the model may ignore."""

from __future__ import annotations

import asyncio

from .. import catalog, db, imaging, ollama, settings
from ..schemas import CatalogEntry, DefaultTask, InstalledModel, RuntimeId, Settings
from ..schemas_image import ImageMode, ImageModelProfile

# Cloud runtimes and the setting that holds their key.
_KEYS: dict[str, str] = {"openrouter": "openrouter_api_key", "tencent-cloud": "tencent_api_key"}
_KIND_LABELS = {"text": "Chat / text", "image": "Image generation", "voice": "Text-to-speech and voice cloning",
                "stt": "Speech-to-text", "music": "Music generation", "video": "Video generation"}


def runtime_ready(runtime: RuntimeId, s: Settings) -> bool:
    if runtime == "remote":  # only reachable as a chat provider endpoint; nothing the tools can install or run
        return False
    key = _KEYS.get(runtime)
    return key is None or bool(getattr(s, key))


def usable_models() -> list[InstalledModel]:
    s = settings.load()
    return [m for m in db.list_installed() if m.status != "error" and runtime_ready(m.runtime, s)]


_TASK_KIND = {"image": "image", "image_edit": "image", "voice": "voice", "stt": "stt", "music": "music",
              "video": "video"}


def preferred(task: DefaultTask) -> InstalledModel | None:
    """The model Settings names for ``task``, if it is installed and usable right now (a cloud model whose key was
    removed is not: callers then fall back to the best local model)."""
    mid = settings.load().default_models.get(task)
    if not mid:
        return None
    return next((m for m in usable_models() if m.id == mid and m.kind == _TASK_KIND[task]), None)


async def image_choice(mode: ImageMode = "txt2img") -> ImageModelProfile | None:
    """The image model for an automatic pick that needs ``mode``: the Settings default for the task when it can do
    that, else the best installed local model."""
    pref = preferred("image" if mode == "txt2img" else "image_edit")
    if pref is not None:
        chosen = next((p for p in await imaging.profiles() if p.model_id == pref.id and mode in p.modes), None)
        if chosen is not None:
            return chosen
    usable = {m.id for m in await asyncio.to_thread(usable_models)}
    ranked = [p for p in await asyncio.to_thread(imaging.ranked_local) if p.model_id in usable and mode in p.modes]
    return ranked[0] if ranked else None


def usable_catalog() -> list[CatalogEntry]:
    s = settings.load()
    return [e for e in catalog.entries() if runtime_ready(e.runtime, s)]


def _sees(m: InstalledModel) -> bool:
    if m.runtime != "ollama":
        return False
    from ..models import ollama_tag

    try:
        return "vision" in ollama.capabilities(ollama_tag(m))
    except ollama.OllamaError:
        return False


def summary() -> str:
    """The prompt's model section: usable installed models grouped by kind, image models with their family and
    the best one marked. Reads image-model files on first use (cached after), so call it off the event loop."""
    usable = usable_models()
    ranked = [p for p in imaging.ranked_local() if any(m.id == p.model_id for m in usable)]
    family = {p.model_id: p.family for p in ranked}
    order = {p.model_id: i for i, p in enumerate(ranked)}
    image_pref = preferred("image")
    auto_image = image_pref.id if image_pref else (ranked[0].model_id if ranked else None)
    defaults = {m.id: task for task in ("voice", "stt", "music", "image_edit", "video") if (m := preferred(task))}
    lines = []
    for kind, label in _KIND_LABELS.items():
        mine = sorted((m for m in usable if m.kind == kind), key=lambda m: order.get(m.id, len(order)))
        if not mine:
            lines.append(f"{label}: nothing installed (search_catalog can find models to install)")
            continue
        lines.append(f"{label}:")
        for m in mine:
            detail = family.get(m.id, m.runtime) + (", sees images" if kind == "text" and _sees(m) else "")
            if m.runtime in _KEYS:
                detail += ", cloud - billed per use"
            best = " — default; generate_image uses it when no model_id is given" if m.id == auto_image else ""
            if m.id in defaults:
                best += f" — the user's default for {defaults[m.id].replace('_', ' ')}"
            lines.append(f"- {m.id} ({detail}){best}")
    return "\n".join(lines)
