"""Agent tools: the studio itself (system info, models, generation), the rest of the studio's features
(``media_tools.py``: images, audio, voices, dubbing, the gallery, questions to the user), the web
(``web_tools.py``) plus the chat's workspace (files, terminal, browser, plan, memory, background tasks — see
``workspace/tools.py``)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import psutil

from .. import capabilities, config, connectors, generation, imaging, system
from ..jobs import jobs
from ..models import ModelError, models
from ..runtimes import WorkerError
from ..schemas import Job, MusicRequest, Output, TTSRequest
from ..schemas_image import ImageGenerateRequest
from ..voice import profiles, speech
from ..voice.profiles import VoiceError
from ..workspace import tools as workspace_tools
from ..workspace.state import WorkspaceError
from . import (automation_tools, images, inventory, media_tools, memory_tools, python_tools, web_tools,
               widget_tools)
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

# Small local models tend to re-issue a side-effecting call after it succeeded.
_DONE_HINT = "Done - do not repeat this call."


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_KIND = {"type": "string", "enum": ["text", "image", "voice", "stt", "music"]}

SPECS: list[ToolSpec] = [
    ToolSpec("system_info", "GPU, VRAM, RAM, CPU and disk status of this machine.", _obj({})),
    ToolSpec("list_models", "List installed models (optionally filtered by kind) with their load status.",
             _obj({"kind": _KIND})),
    ToolSpec("search_catalog",
             "Search the model catalog. Returns ids, sizes, VRAM needs, hardware fit and whether installed.",
             _obj({"query": {"type": "string", "description": "Words matched against name, id, vendor, tags and "
                                                               "notes (any order); omit to list a kind"},
                   "kind": _KIND})),
    ToolSpec("install_model", "Start downloading/installing a catalog model. Returns the job id; runs in the "
             "background.", _obj({"catalog_id": {"type": "string"}}, ["catalog_id"]), needs_approval=True),
    ToolSpec("delete_model", "Delete an installed model and its files.",
             _obj({"model_id": {"type": "string"}}, ["model_id"]), needs_approval=True),
    ToolSpec("load_model", "Preload a model into GPU memory. Only for an explicit user request to preload (pass "
             "force=true): generate_image, text_to_speech and generate_music load their model themselves — without "
             "force this does nothing.",
             _obj({"model_id": {"type": "string"},
                   "force": {"type": "boolean", "description": "true only when the user asked to preload this model"}},
                  ["model_id"])),
    ToolSpec("unload_model", "Unload a model and free its VRAM.",
             _obj({"model_id": {"type": "string"}}, ["model_id"])),
    ToolSpec("generate_image", "Generate an image from a prompt. Leave model_id out to use the best installed image "
             "model (recommended); set it only when the user asks for a specific model. To change an existing "
             "image use edit_image.",
             _obj({"prompt": {"type": "string"}, "model_id": {"type": "string"},
                   "width": {"type": "integer", "minimum": 256, "maximum": 2048},
                   "height": {"type": "integer", "minimum": 256, "maximum": 2048},
                   "steps": {"type": "integer", "minimum": 1, "maximum": 100},
                   "seed": {"type": "integer"}}, ["prompt"])),
    ToolSpec("text_to_speech", "Synthesize speech to a WAV file. Defaults to Kokoro with the af_heart voice; "
             "voice_id from list_voices (the right model is picked for it when model_id is left out).",
             _obj({"text": {"type": "string"}, "voice_id": {"type": "string"}, "model_id": {"type": "string"}},
                  ["text"])),
    ToolSpec("generate_music", "Generate a song or instrumental from style tags and optional lyrics.",
             _obj({"tags": {"type": "string", "description": "Style, e.g. 'synthwave, 110 bpm, female vocals'"},
                   "lyrics": {"type": "string", "description": "[verse]/[chorus] lyrics or [instrumental]"},
                   "duration_s": {"type": "number", "minimum": 5, "maximum": 240},
                   "model_id": {"type": "string"}}, ["tags"])),
    *media_tools.SPECS,
    *web_tools.SPECS,
    *workspace_tools.SPECS,
    *memory_tools.SPECS,
    *python_tools.SPECS,
    *widget_tools.SPECS,
    *automation_tools.SPECS,
]
BY_NAME = {s.name: s for s in SPECS}


def connector_specs() -> list[ToolSpec]:
    """Tools of the connected MCP connectors (they come and go with Settings → Connectors)."""
    return [ToolSpec(name, desc, schema, needs_approval=ask) for name, desc, schema, ask in connectors.manager.tool_specs()]


def all_specs() -> list[ToolSpec]:
    """The agent's tools for a turn: the built-in ones this machine can run, plus the connectors'."""
    caps = capabilities.get()
    usable = [s for s in SPECS if (f := capabilities.TOOL_FEATURE.get(s.name)) is None or caps.features[f].available]
    return [*usable, *connector_specs()]


def _spec(name: str) -> ToolSpec | None:
    return BY_NAME.get(name) or next((s for s in connector_specs() if s.name == name), None)


def needs_approval(name: str, auto_approve: list[str]) -> bool:
    spec = _spec(name)
    return bool(spec and spec.needs_approval and name not in auto_approve)


def validate_args(name: str, args: Any) -> dict[str, Any]:
    """Check model-produced arguments against the tool's JSON schema (types + required keys)."""
    spec = _spec(name)
    if spec is None:
        raise ToolFailure(f"Unknown tool '{name}'. Available: {', '.join(s.name for s in all_specs())}")
    if not isinstance(args, dict):
        raise ToolFailure(f"Arguments for {name} must be a JSON object")
    props: dict[str, Any] = spec.parameters["properties"]
    missing = [k for k in spec.parameters.get("required", []) if k not in args]
    if missing:
        raise ToolFailure(f"Missing required argument(s) for {name}: {', '.join(missing)}")
    clean: dict[str, Any] = {}
    for key, value in args.items():
        if key not in props or value is None:
            continue  # small models often add stray keys; ignore rather than fail
        expected = props[key].get("type")
        if expected == "integer" and isinstance(value, (int, float, str)) and not isinstance(value, bool):
            try:
                value = int(value)
            except ValueError as exc:
                raise ToolFailure(f"{name}.{key} must be an integer") from exc
        elif expected == "number" and isinstance(value, (int, float, str)) and not isinstance(value, bool):
            try:
                value = float(value)
            except ValueError as exc:
                raise ToolFailure(f"{name}.{key} must be a number") from exc
        elif expected == "string" and not isinstance(value, str):
            raise ToolFailure(f"{name}.{key} must be a string")
        elif expected == "boolean" and not isinstance(value, bool):
            if str(value).lower() not in ("true", "false", "1", "0"):
                raise ToolFailure(f"{name}.{key} must be true or false")
            value = str(value).lower() in ("true", "1")
        elif expected == "array" and isinstance(value, str):
            try:  # small models sometimes send the list JSON-encoded
                value = json.loads(value)
            except ValueError as exc:
                raise ToolFailure(f"{name}.{key} must be a list") from exc
        if "enum" in props[key] and value not in props[key]["enum"]:
            raise ToolFailure(f"{name}.{key} must be one of {props[key]['enum']}")
        clean[key] = value
    return clean


def _json(data: Any) -> str:
    return json.dumps(data, indent=1, default=str)


# ------------------------------- helpers -------------------------------


def _default_model(kind: str, preferred_runtimes: tuple[str, ...] = ()) -> str:
    installed = [m for m in inventory.usable_models() if m.kind == kind]
    for rt in preferred_runtimes:
        for m in installed:
            if m.runtime == rt:
                return m.id
    if not installed:
        raise ToolFailure(f"No {kind} model is installed. Use search_catalog(kind='{kind}') and install_model first.")
    return installed[0].id


async def _run_job(job: Job) -> tuple[Job, list[Output]]:
    done = await jobs.wait(job.id)
    if done.status != "done":
        raise ToolFailure(f"Job {done.title} {done.status}: {done.error or done.message or ''}".strip())
    outputs = done.result.outputs if done.result else []
    return done, outputs


# ------------------------------- tools -------------------------------


async def _system_info(_: dict[str, Any]) -> ToolOutcome:
    vm = psutil.virtual_memory()
    data = {
        "gpus": [{"name": g.name, "vram_total_gb": round(g.vram_total / 2**30, 1),
                  "vram_used_gb": round(g.vram_used / 2**30, 1), "util_pct": g.util, "temp_c": g.temp_c}
                 for g in system.gpus()],
        "ram_total_gb": round(vm.total / 2**30, 1), "ram_used_gb": round(vm.used / 2**30, 1),
        "cpu_percent": psutil.cpu_percent(interval=None), "disk_free_gb": round(system.disk_free_bytes() / 2**30, 1),
        "data_dir": str(config.DATA_DIR),
    }
    return ToolOutcome(True, _json(data))


async def _list_models(a: dict[str, Any]) -> ToolOutcome:
    usable = {m.id for m in await asyncio.to_thread(inventory.usable_models)}
    items = [m for m in await asyncio.to_thread(models.list) if m.id in usable]
    ranked = [p for p in await asyncio.to_thread(imaging.ranked_local) if p.model_id in usable] \
        if a.get("kind") in (None, "image") else []
    family = {p.model_id: p.family for p in ranked}
    rows = [{"id": m.id, "name": m.name, "kind": m.kind, "runtime": m.runtime, "status": m.status,
             "size_gb": round(m.size_bytes / 1e9, 2),
             **({"family": family[m.id], "recommended": m.id == ranked[0].model_id} if m.id in family else {})}
            for m in items if not a.get("kind") or m.kind == a["kind"]]
    return ToolOutcome(True, _json(rows) if rows else "No models installed" + (f" of kind {a['kind']}" if a.get("kind") else ""))


async def _search_catalog(a: dict[str, Any]) -> ToolOutcome:
    words = [w for w in (a.get("query") or "").lower().replace("-", " ").split() if w]
    scored = []
    for e in await asyncio.to_thread(inventory.usable_catalog):
        if a.get("kind") and e.kind != a["kind"]:
            continue
        hay = " ".join([e.id, e.name, e.vendor, e.kind, *e.tags, e.notes or ""]).lower().replace("-", " ")
        hits = sum(w in hay for w in words)
        if words and not hits:
            continue
        scored.append((hits, e))
    scored.sort(key=lambda x: -x[0])
    rows = []
    for _, e in scored[:40]:
        rows.append({"id": e.id, "name": e.name, "kind": e.kind, "runtime": e.runtime, "params": e.params,
                     "size_gb": e.size_gb, "vram_gb": e.vram_gb, "fit": e.fit, "installed": e.installed,
                     "notes": e.notes})
    return ToolOutcome(True, _json(rows) if rows else "No catalog entries match (the catalog has text, image, voice, "
                                                      "stt and music models only)")


async def _install_model(a: dict[str, Any]) -> ToolOutcome:
    job = await asyncio.to_thread(models.install, a["catalog_id"])
    return ToolOutcome(True, f"Started install job {job.id} ({job.title}). It runs in the background; progress is "
                             f"visible in the Jobs panel. {_DONE_HINT}")


async def _delete_model(a: dict[str, Any]) -> ToolOutcome:
    await asyncio.to_thread(models.delete, a["model_id"])
    return ToolOutcome(True, f"Deleted {a['model_id']}. {_DONE_HINT}")


async def _load_model(a: dict[str, Any]) -> ToolOutcome:
    # Models preload by habit before generating; on a GPU the chat model can't share, that unloads the agent itself,
    # which reloads for its next step and evicts the preloaded model again. The generation tools load what they need.
    if not a.get("force"):
        m = models.get(a["model_id"])
        use = {"image": "generate_image", "voice": "text_to_speech", "music": "generate_music"}.get(m.kind)
        hint = f"Call {use} now — it loads {m.name} itself." if use else "Models load automatically when used."
        return ToolOutcome(True, f"Not loaded (not needed). {hint}")
    m = await asyncio.to_thread(models.load, a["model_id"])
    return ToolOutcome(True, f"{m.name} is {m.status}")


async def _unload_model(a: dict[str, Any]) -> ToolOutcome:
    m = await asyncio.to_thread(models.unload, a["model_id"])
    return ToolOutcome(True, f"{m.name} unloaded")


async def _generate_image(a: dict[str, Any]) -> ToolOutcome:
    chosen = None if a.get("model_id") else await inventory.image_choice()
    model_id = a.get("model_id") or (chosen.model_id if chosen else _default_model("image"))
    m = models.get(model_id)
    profile = next((p for p in await imaging.profiles() if p.model_id == m.id), None)
    d = profile.defaults if profile else None
    req = ImageGenerateRequest(model_id=model_id, prompt=a["prompt"], width=a.get("width", d.width if d else 1024),
                               height=a.get("height", d.height if d else 1024),
                               steps=a.get("steps", d.steps if d else 28), guidance=d.guidance if d else 4.0,
                               seed=a.get("seed"), count=1)
    job = await asyncio.to_thread(imaging.generate, req)
    _, outputs = await _run_job(job)
    cloud = " (cloud, billed per image)" if profile and profile.location == "cloud" else ""
    return ToolOutcome(True, f"Generated {len(outputs)} image(s) with {m.name}{cloud}: "
                             + ", ".join(o.url for o in outputs), outputs)


def _voice_model(voice_id: str | None) -> str:
    """A voice model for ``voice_id``: a preset's own model; OmniVoice or Chatterbox for the user's voices; without
    one, the Settings default (else Kokoro)."""
    if not voice_id:
        pref = inventory.preferred("voice")
        return pref.id if pref else _default_model("voice", ("kokoro", "chatterbox"))
    preset = next((v for v in profiles.presets() if v.id == voice_id), None)
    if preset and preset.model_id:
        return preset.model_id
    return _default_model("voice", ("omnivoice", "chatterbox"))


async def _text_to_speech(a: dict[str, Any]) -> ToolOutcome:
    model_id = a.get("model_id") or await asyncio.to_thread(_voice_model, a.get("voice_id"))
    m = models.get(model_id)
    voice_id = a.get("voice_id") or (f"{m.id}:af_heart" if m.runtime == "kokoro" else f"{m.id}:default")
    cloud = " (cloud, billed per use)" if m.runtime == "openrouter" else ""
    job = await asyncio.to_thread(speech.tts, TTSRequest(model_id=model_id, text=a["text"], voice_id=voice_id,
                                                             speed=1.0))
    _, outputs = await _run_job(job)
    return ToolOutcome(True, f"Spoke {len(a['text'])} chars with {m.name}{cloud} / {voice_id}: "
                             + ", ".join(f"{o.url} ({o.duration_s}s)" for o in outputs), outputs)


async def _generate_music(a: dict[str, Any]) -> ToolOutcome:
    pref = inventory.preferred("music")
    model_id = a.get("model_id") or (pref.id if pref else _default_model("music"))
    req = MusicRequest(model_id=model_id, tags=a["tags"], lyrics=a.get("lyrics") or "[instrumental]",
                       duration_s=a.get("duration_s", 30), steps=60, guidance=15.0)
    job = await asyncio.to_thread(generation.generate_music, req)
    _, outputs = await _run_job(job)
    return ToolOutcome(True, "Generated music: " + ", ".join(f"{o.url} ({o.duration_s}s)" for o in outputs), outputs)


_IMPL: dict[str, Callable[[dict[str, Any]], Awaitable[ToolOutcome]]] = {
    "system_info": _system_info, "list_models": _list_models, "search_catalog": _search_catalog,
    "install_model": _install_model, "delete_model": _delete_model, "load_model": _load_model,
    "unload_model": _unload_model, "generate_image": _generate_image, "text_to_speech": _text_to_speech,
    "generate_music": _generate_music,
}


async def execute(name: str, raw_args: Any, ctx: ToolContext) -> ToolOutcome:
    try:
        args = validate_args(name, raw_args)
        if connectors.SEP in name and name not in BY_NAME:
            ok, text, pictures = await connectors.manager.call(name, args)
            return ToolOutcome(ok, text, images=pictures if ctx.vision else [])
        for module in (workspace_tools, media_tools, web_tools, memory_tools, python_tools, widget_tools,
                       automation_tools):
            if name in module.IMPL:
                return await module.IMPL[name](args, ctx)
        outcome = await _IMPL[name](args)
        if name == "generate_image" and ctx.vision and outcome.artifacts:  # let the model check its result
            outcome.images = [images.to_path(o.url) for o in outcome.artifacts]
            outcome.output += " - attached below; check it matches the request."
        return outcome
    except TimeoutError:
        return ToolOutcome(False, f"{name} timed out")
    except (ToolFailure, WorkspaceError, ModelError, WorkerError, VoiceError, ValueError, OSError) as exc:
        return ToolOutcome(False, f"Error: {exc}")
    except connectors.ConnectorError as exc:
        return ToolOutcome(False, f"Error: {exc}")
    except httpx.HTTPError as exc:  # widgets and web lookups: the service was unreachable or refused
        return ToolOutcome(False, f"Error: network request failed ({type(exc).__name__}: {exc})")
