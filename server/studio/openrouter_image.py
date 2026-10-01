"""Pinned OpenRouter image models in the Image area: their parameter set (from ``GET /images/models``) as an
``ImageModelProfile``, and generation through the OpenRouter client (``openrouter.py``)."""

from __future__ import annotations

import time
from typing import Any

from . import events, openrouter, openrouter_catalog, openrouter_usage
from .openrouter import GeneratedImage, OpenRouterError
from .schemas import InstalledModel
from .schemas_image import ImageDefaults, ImageModelProfile, ImageOption

_TTL_S = 30 * 60
_cache: tuple[float, dict[str, dict[str, Any]]] | None = None

# Enum parameters we pass through, in display order.
_OPTIONS = {"aspect_ratio": "Aspect ratio", "resolution": "Resolution", "quality": "Quality",
            "output_format": "Format"}
_PREFERRED_DEFAULT = {"aspect_ratio": "1:1", "quality": "auto", "output_format": "png"}
_UNIT = {"image": "image", "megapixel": "megapixel"}


async def supported_parameters() -> dict[str, dict[str, Any]]:
    """``supported_parameters`` per OpenRouter image model id (cached; empty when OpenRouter is unreachable)."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < _TTL_S:
        return _cache[1]
    try:
        listed = await openrouter.list_image_models()
    except OpenRouterError as exc:
        events.log("warn", "openrouter", f"Could not list image model parameters: {exc}")
        return _cache[1] if _cache else {}
    _cache = (time.monotonic(), {m["id"]: m.get("supported_parameters") or {} for m in listed if m.get("id")})
    return _cache[1]


def _cost(slug: str) -> str:
    pinned = openrouter_catalog.pinned(slug)
    if pinned is None or not pinned.prices:
        return f"Billed to your OpenRouter credits; OpenRouter lists no fixed price (see openrouter.ai/{slug})"
    lines = [f"${p.usd:.3f} per {_UNIT.get(p.unit, p.unit)}" for p in pinned.prices]
    return " · ".join(lines) + " (OpenRouter credits)"


def profile(m: InstalledModel, params: dict[str, Any]) -> ImageModelProfile:
    slug = openrouter_catalog.slug(m)
    options = []
    for key, label in _OPTIONS.items():
        spec = params.get(key) or {}
        values = [str(v) for v in spec.get("values") or []]
        if spec.get("type") == "enum" and values:
            default = _PREFERRED_DEFAULT.get(key)
            options.append(ImageOption(id=key, label=label, values=values,
                                       default=default if default in values else values[0]))
    refs = params.get("input_references") or {}
    max_images = int(refs.get("max") or 0)
    needs_image = int(refs.get("min") or 0) > 0
    modes: list[Any] = ["edit"] if needs_image else ["txt2img", "edit"] if max_images else ["txt2img"]
    notes = [f"Runs on OpenRouter ({slug}): your prompt and reference images leave this machine."]
    if not params:
        notes.append("OpenRouter's parameter list is unavailable right now; only the prompt is sent.")
    return ImageModelProfile(
        model_id=m.id, family=m.name, engine="OpenRouter", location="cloud", modes=modes, guidance="none",
        negative_prompt=False, defaults=ImageDefaults(steps=1, guidance=0.0, width=1024, height=1024, strength=0.7),
        options=options, seed="seed" in params, max_count=4, max_images=max_images, cost=_cost(slug), notes=notes,
    )


def generate(m: InstalledModel, prompt: str, count: int, seed: int | None, options: dict[str, str],
             references: list[str], params: dict[str, Any], job_id: str) -> list[GeneratedImage]:
    """``count`` images: one request when the model's ``n`` allows it, else one request per image."""
    slug = openrouter_catalog.slug(m)
    n_max = int((params.get("n") or {}).get("max") or 1)
    per_call = count if count <= n_max else 1
    known = {k: v for k, v in options.items() if k in _OPTIONS and v}
    images: list[GeneratedImage] = []
    for i in range(0, count, per_call):
        result = openrouter.generate_image(
            slug, prompt, n=per_call if per_call > 1 else None,
            seed=seed + i if seed is not None and "seed" in params else None,
            input_references=references or None, **known)
        if result.usage.cost is None:
            openrouter_usage.record_when_billed("image", slug, result.usage, ref=job_id)
        else:
            openrouter_usage.record("image", slug, result.usage, ref=job_id)
        images += result.images
    return images[:count]
