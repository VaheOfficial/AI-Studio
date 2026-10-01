"""OpenRouter cloud catalog (every model, every modality, cached server-side) and pinned models.

Pinning is how cloud models join the studio: pinned chat models appear in the chat picker, and
pinned image / speech / transcription models become ``InstalledModel`` rows with
``runtime: "openrouter"`` (nothing is downloaded), so the Image and Voice areas list them next
to local models.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from . import db, events, openrouter
from .events import bus
from .openrouter import OpenRouterError
from .schemas import ChatModelOption, ChatPrice, EvModelRemoved, EvModelUpdate, InstalledModel, ModelKind
from .schemas_openrouter import (CloudCatalogPage, CloudModel, CloudOutputFilter, CloudPrice, CloudSort, CloudUse)
from .schemas_voice import VoiceProfile

CACHE_TTL_S = 30 * 60
_ID_PREFIX = "openrouter:"
_KIND_OF_USE: dict[CloudUse, ModelKind] = {"image": "image", "voice": "voice", "stt": "stt"}

_cache: tuple[float, list[CloudModel], str] | None = None  # (monotonic time, models, fetched_at)
_raw_models: list[dict[str, Any]] = []
_image_prices: dict[str, list[CloudPrice]] = {}  # per-image prices need one request per model: filled in background
_image_task: asyncio.Task[None] | None = None
_refresh_lock = asyncio.Lock()


class CatalogError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def init() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS openrouter_pins (
        model_id TEXT PRIMARY KEY,
        pinned_at TEXT NOT NULL,
        model TEXT NOT NULL
    )""")


def installed_id(model_id: str) -> str:
    """``InstalledModel.id`` / chat model id of an OpenRouter model: ``openrouter:<slug>``."""
    return f"{_ID_PREFIX}{model_id}"


def slug(installed: InstalledModel) -> str:
    return installed.id.removeprefix(_ID_PREFIX)


# ------------------------------ normalizing ------------------------------


def _usd(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _use(outputs: list[str]) -> CloudUse | None:
    if "image" in outputs:
        return "image"
    if "speech" in outputs:
        return "voice"
    if "transcription" in outputs:
        return "stt"
    if "text" in outputs:
        return "chat"
    return None  # video, embeddings, rerank…: browse only


def _prices(raw: dict[str, Any], use: CloudUse | None, image_lines: list[CloudPrice]) -> tuple[list[CloudPrice], bool]:
    pricing = raw.get("pricing") or {}
    prompt, completion, request = (_usd(pricing.get(k)) for k in ("prompt", "completion", "request"))
    dynamic = any(v is not None and v < 0 for v in (prompt, completion, request))
    lines: list[CloudPrice] = []
    if use == "image" and image_lines:
        lines = image_lines
    elif use == "voice" and prompt and not completion:
        lines = [CloudPrice(usd=prompt * 1e6, unit="mchar")]  # TTS is billed per input character
    elif use == "voice" and completion and not prompt:
        return [], True  # billed per unit of generated audio, which the listing doesn't name
    elif use == "stt" and prompt and not completion:
        lines = [CloudPrice(usd=prompt * 60, unit="minute")]  # duration-priced: per second of audio
    else:
        if prompt is not None and prompt >= 0 and (prompt or completion):
            lines.append(CloudPrice(usd=prompt * 1e6, unit="input_mtok"))
        if completion is not None and completion >= 0 and (prompt or completion):
            lines.append(CloudPrice(usd=completion * 1e6, unit="output_mtok"))
    if request and request > 0:
        lines.append(CloudPrice(usd=request, unit="request"))
    return lines, dynamic


def _image_lines(endpoints: list[dict[str, Any]]) -> list[CloudPrice]:
    """Cheapest per-image (or per-megapixel) output price across an image model's providers."""
    best: dict[str, float] = {}
    for ep in endpoints:
        for line in ep.get("pricing") or []:
            unit, cost = line.get("unit"), _usd(line.get("cost_usd"))
            if line.get("billable") != "output_image" or cost is None or unit not in ("image", "megapixel"):
                continue
            best[unit] = min(cost, best.get(unit, cost))
    return [CloudPrice(usd=v, unit=u) for u, v in best.items()]  # type: ignore[arg-type]


def _free(raw: dict[str, Any], use: CloudUse | None, prices: list[CloudPrice], dynamic: bool) -> bool:
    if dynamic:
        return False
    if prices:
        return all(p.usd == 0 for p in prices)
    # No price lines: zero token prices mean free, except image models whose per-image price isn't loaded yet
    pricing = raw.get("pricing") or {}
    return use != "image" and all(_usd(pricing.get(k)) == 0 for k in ("prompt", "completion"))


def _normalize(raw: dict[str, Any], image_lines: list[CloudPrice]) -> CloudModel:
    arch = raw.get("architecture") or {}
    outputs = list(arch.get("output_modalities") or [])
    use = _use(outputs)
    prices, dynamic = _prices(raw, use, image_lines)
    full_name = str(raw.get("name") or raw["id"])
    vendor, sep, name = full_name.partition(": ")
    if not sep:
        vendor, name = raw["id"].split("/")[0], full_name
    params = raw.get("supported_parameters") or []
    return CloudModel(
        id=raw["id"], name=name, vendor=vendor, description=str(raw.get("description") or ""),
        created=int(raw.get("created") or 0), context_length=raw.get("context_length") or None,
        input_modalities=list(arch.get("input_modalities") or []), output_modalities=outputs, use=use,
        tools="tools" in params, reasoning=bool(raw.get("reasoning")) or "reasoning" in params,
        free=raw["id"].endswith(":free") or _free(raw, use, prices, dynamic),
        prices=prices, price_dynamic=dynamic or None, voices=raw.get("supported_voices") or None, pinned=False,
    )


async def _fetch_image_prices() -> dict[str, list[CloudPrice]]:
    try:
        image_models = await openrouter.list_image_models()
    except OpenRouterError as exc:
        events.log("warn", "openrouter", f"Could not list image models: {exc}")
        return {}
    sem = asyncio.Semaphore(8)

    async def one(model_id: str) -> tuple[str, list[CloudPrice]]:
        async with sem:
            try:
                return model_id, _image_lines(await openrouter.image_model_endpoints(model_id))
            except OpenRouterError:
                return model_id, []

    return dict(await asyncio.gather(*(one(m["id"]) for m in image_models if m.get("id"))))


def _normalized() -> list[CloudModel]:
    return [_normalize(m, _image_prices.get(m["id"], [])) for m in _raw_models]


async def _load_image_prices() -> None:
    global _cache
    _image_prices.update(await _fetch_image_prices())
    if _cache:
        _cache = (_cache[0], _normalized(), _cache[2])
        _refresh_pins(_cache[1])


async def _all(force: bool = False) -> tuple[list[CloudModel], str]:
    global _cache, _raw_models, _image_task
    async with _refresh_lock:
        if not force and _cache and time.monotonic() - _cache[0] < CACHE_TTL_S:
            return _cache[1], _cache[2]
        _raw_models = [m for m in await openrouter.list_models("all") if m.get("id")]
        _cache = (time.monotonic(), _normalized(), db.now_iso())
        _refresh_pins(_cache[1])
        if _image_task is None or _image_task.done():
            _image_task = asyncio.create_task(_load_image_prices(), name="openrouter-image-prices")
        return _cache[1], _cache[2]


# -------------------------------- queries --------------------------------


def _primary_price(m: CloudModel) -> float:
    return m.prices[0].usd if m.prices else float("inf")


async def search(output: CloudOutputFilter = "all", q: str = "", tools: bool = False, free: bool = False,
                 pinned_only: bool = False, max_input_price: float | None = None, min_context: int | None = None,
                 sort: CloudSort = "newest", limit: int = 60, offset: int = 0, refresh: bool = False
                 ) -> CloudCatalogPage:
    models, fetched_at = await _all(refresh)
    pins = set(_pinned_rows())
    words = q.lower().split()
    out = []
    for m in models:
        if output != "all" and output not in m.output_modalities:
            continue
        if tools and not m.tools:
            continue
        if free and not m.free:
            continue
        if pinned_only and m.id not in pins:
            continue
        if max_input_price is not None and any(p.unit == "input_mtok" and p.usd > max_input_price for p in m.prices):
            continue
        if min_context and (m.context_length or 0) < min_context:
            continue
        hay = f"{m.id} {m.name} {m.vendor} {m.description}".lower()
        if any(w not in hay for w in words):
            continue
        out.append(m.model_copy(update={"pinned": m.id in pins}))
    if sort == "price":
        out.sort(key=_primary_price)
    elif sort == "context":
        out.sort(key=lambda m: m.context_length or 0, reverse=True)
    elif sort == "name":
        out.sort(key=lambda m: (m.vendor.lower(), m.name.lower()))
    else:
        out.sort(key=lambda m: m.created, reverse=True)
    return CloudCatalogPage(models=out[offset:offset + limit], total=len(out), fetched_at=fetched_at)


# --------------------------------- pins ---------------------------------


def _pinned_rows() -> dict[str, CloudModel]:
    rows = db.query("SELECT model_id, model FROM openrouter_pins ORDER BY pinned_at")
    return {r["model_id"]: CloudModel.model_validate(json.loads(r["model"])) for r in rows}


def _refresh_pins(models: list[CloudModel]) -> None:
    """Keep pinned snapshots (prices, voices, tool support) in step with the latest catalog."""
    fresh = {m.id: m for m in models}
    for model_id in _pinned_rows():
        if model_id in fresh:
            db.execute("UPDATE openrouter_pins SET model = ? WHERE model_id = ?",
                       (fresh[model_id].model_copy(update={"pinned": True}).model_dump_json(), model_id))


def pins() -> list[CloudModel]:
    return list(_pinned_rows().values())


def pinned(model_id: str) -> CloudModel | None:
    return _pinned_rows().get(model_id)


async def pin(model_id: str) -> CloudModel:
    models, _ = await _all()
    found = next((m for m in models if m.id == model_id), None)
    if found is None:
        raise CatalogError(f"OpenRouter has no model '{model_id}'", 404)
    if found.use is None:
        raise CatalogError(f"{found.name} outputs {', '.join(found.output_modalities)}, which the studio can't use yet")
    model = found.model_copy(update={"pinned": True})
    db.execute("INSERT INTO openrouter_pins(model_id, pinned_at, model) VALUES(?,?,?) ON CONFLICT(model_id) "
               "DO UPDATE SET model = excluded.model", (model.id, db.now_iso(), model.model_dump_json()))
    kind = _KIND_OF_USE.get(model.use) if model.use else None
    if kind:
        m = InstalledModel(id=installed_id(model.id), catalog_id=installed_id(model.id), name=model.name, kind=kind,
                           runtime="openrouter", source_repo=model.id, path=f"openrouter://{model.id}",
                           size_bytes=0, installed_at=db.now_iso(), status="ready")
        db.upsert_installed(m)
        bus.publish(EvModelUpdate(model=m))
    events.log("info", "openrouter", f"Pinned {model.id}")
    return model


def unpin(model_id: str) -> None:
    if db.execute("DELETE FROM openrouter_pins WHERE model_id = ?", (model_id,)) == 0:
        raise CatalogError(f"'{model_id}' is not pinned", 404)
    iid = installed_id(model_id)
    if db.get_installed(iid):
        db.delete_installed(iid)
        bus.publish(EvModelRemoved(id=iid))
    events.log("info", "openrouter", f"Unpinned {model_id}")


# ----------------------------- studio integration -----------------------------


def chat_options(key_configured: bool) -> list[ChatModelOption]:
    """Pinned chat models for the composer picker (unavailable until a key is set)."""
    return [
        ChatModelOption(
            id=installed_id(m.id), provider="openrouter", name=m.name, tools=m.tools, available=key_configured,
            context_length=m.context_length, vision="image" in m.input_modalities,
            price=ChatPrice(input=next((p.usd for p in m.prices if p.unit == "input_mtok"), 0.0),
                            output=next((p.usd for p in m.prices if p.unit == "output_mtok"), 0.0)),
        )
        for m in pins() if m.use == "chat"
    ]


def default_voice_id(installed: InstalledModel) -> str:
    return f"{installed.id}:default"


def voices_for(installed: InstalledModel) -> list[VoiceProfile]:
    """Preset voices of a pinned TTS model (its ``supported_voices``, or the provider default)."""
    model = pinned(slug(installed))
    names = model.voices if model and model.voices else []
    if not names:
        return [VoiceProfile(id=default_voice_id(installed), name="Provider default", kind="preset",
                             model_id=installed.id, tags=["default", "cloud"])]
    return [VoiceProfile(id=f"{installed.id}:{name}", name=name, kind="preset", model_id=installed.id, tags=["cloud"])
            for name in names]


def voice_name(installed: InstalledModel, voice_id: str) -> str | None:
    """The OpenRouter ``voice`` parameter for one of :func:`voices_for`'s ids (None = provider default)."""
    prefix = f"{installed.id}:"
    if not voice_id.startswith(prefix):
        raise CatalogError(f"Voice '{voice_id}' does not belong to {installed.name}")
    name = voice_id[len(prefix):]
    return None if voice_id == default_voice_id(installed) else name
