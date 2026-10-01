"""Agent tools over the rest of the studio: looking at images, editing them, transcribing and separating audio, voices
(list, clone), dubbing, the gallery of past outputs, and asking the user a question."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from .. import audio_tools, config, db, generation, imaging, ollama, video
from ..jobs import jobs
from ..localhttp import tls
from ..models import models
from ..schemas_image import ImageGenerateRequest
from ..schemas_video import VideoRequest
from ..schemas_voice import CloneProfileCreate
from ..schemas_workspace import ImageDisplay
from ..voice import profiles
from ..workspace import state as workspace_state
from . import images, inventory
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

MAX_DOWNLOAD_BYTES = 500 * 2**20
_S = {"type": "string"}
_SOURCE = {"type": "string", "description": "A workspace file path, a studio URL (/files/...) or an http(s) URL"}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


SPECS: list[ToolSpec] = [
    ToolSpec("view_image", "Look at an image: an attachment, a screenshot, a generated picture, a workspace file or a "
             "web image. Use it to check results and read what's in pictures.",
             _obj({"source": _SOURCE, "question": {"type": "string", "description": "What to look for"}},
                  ["source"])),
    ToolSpec("edit_image", "Change existing images with the best local image model: by instruction ('make it night', "
             "'put this character in a forest', combine references) or, with strength (0.2 subtle - 0.9 almost new), "
             "a redraw that keeps the composition.",
             _obj({"images": {"type": "array", "items": _SOURCE, "description": "1-4 input images"},
                   "prompt": {"type": "string", "description": "The change, or the full description for a redraw"},
                   "strength": {"type": "number", "minimum": 0.05, "maximum": 1.0},
                   "seed": {"type": "integer"}}, ["images", "prompt"])),
    ToolSpec("transcribe", "Transcribe speech in an audio or video file (Whisper) into timestamped text.",
             _obj({"source": _SOURCE, "language": {"type": "string", "description": "e.g. 'en'; omit to detect"}},
                  ["source"])),
    ToolSpec("list_voices", "Voices for text_to_speech: built-in presets and the user's cloned/designed voices.",
             _obj({"query": {"type": "string", "description": "Filter by name, language, gender or tag"}})),
    ToolSpec("clone_voice", "Make a reusable voice from a recording of one speaker (3-20 s of clean speech is best; "
             "longer clips are trimmed to the best 15 s). Returns its voice_id for text_to_speech.",
             _obj({"source": _SOURCE, "name": _S, "language": {"type": "string"}}, ["source", "name"])),
    ToolSpec("separate_audio", "Split a song or recording into vocals and instrumental (or 4/6 stems) with Demucs.",
             _obj({"source": _SOURCE, "mode": {"type": "string", "enum": sorted(audio_tools.ISOLATE_MODES),
                                               "description": "vocals = vocals + instrumental (default)"}},
                  ["source"])),
    ToolSpec("start_dub", "Create a dubbing project from a video/audio file or a video URL (YouTube etc.): it is "
             "downloaded, transcribed and split by speaker. The user then picks languages and voices in the Dub tab.",
             _obj({"source": _SOURCE, "name": _S,
                   "speakers": {"type": "integer", "minimum": 1, "maximum": 12, "description": "If known"}},
                  ["source"])),
    ToolSpec("list_outputs", "Search the studio's gallery of past generations (images, speech, music, video) by "
             "prompt.",
             _obj({"kind": {"type": "string", "enum": ["image", "audio", "music", "video"]}, "query": _S,
                   "limit": {"type": "integer", "minimum": 1, "maximum": 50}})),
    ToolSpec("generate_video", "Make a video from a prompt, or animate a start image (image = a picture to bring to "
             "life). Any length up to 120 s and any size up to 4K (defaults: 5 s at the model's native size). Takes "
             "minutes on the GPU: only when the user wants a video. Describe the shot, the motion and, for models "
             "with sound, the audio.",
             _obj({"prompt": _S, "image": _SOURCE,
                   "duration_s": {"type": "number", "minimum": 1, "maximum": 120},
                   "width": {"type": "integer", "minimum": 256, "maximum": 3840},
                   "height": {"type": "integer", "minimum": 256, "maximum": 3840},
                   "portrait": {"type": "boolean", "description": "Vertical video at the native size"},
                   "model_id": _S}, ["prompt"])),
    ToolSpec("ask_user", "Ask the user a question and wait for the answer - only when you truly can't continue "
             "without their decision. Offer 2-4 short options when possible (they can also type their own).",
             _obj({"question": _S, "options": {"type": "array", "items": _S, "maxItems": 4}}, ["question"])),
]


# ------------------------------- helpers -------------------------------


def _root(ctx: ToolContext) -> Path | None:
    root = workspace_state.get(ctx.session_id).root
    return Path(root) if root else None


async def _download(url: str, suffix: str = "") -> Path:
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    name = url.split("?", 1)[0].rsplit("/", 1)[-1]
    ext = suffix or (Path(name).suffix.lower() if "." in name else "")
    out = config.UPLOADS_DIR / f"agent-{uuid.uuid4().hex[:12]}{ext}"
    size = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 AI-Studio"}) as client:
            async with client.stream("GET", url) as r:
                if r.status_code >= 400:
                    raise ToolFailure(f"Download failed: HTTP {r.status_code} for {url}")
                with out.open("wb") as f:
                    async for chunk in r.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise ToolFailure(f"{url} is larger than {MAX_DOWNLOAD_BYTES // 2**20} MB")
                        f.write(chunk)
    except httpx.HTTPError as exc:
        out.unlink(missing_ok=True)
        raise ToolFailure(f"Download failed: {exc}") from exc
    except ToolFailure:
        out.unlink(missing_ok=True)
        raise
    return out


def _local(ref: str, ctx: ToolContext) -> Path:
    """A local file from a workspace path, an absolute path or a studio URL."""
    ref = ref.strip().strip('"')
    for prefix in (f"http://{config.HOST}:{config.PORT}", f"http://localhost:{config.PORT}"):
        ref = ref.removeprefix(prefix)
    if ref.startswith("/files/"):
        path = (config.DATA_DIR / ref.removeprefix("/files/").split("?", 1)[0]).resolve()
        if images.public_url(path) is None:
            raise ToolFailure(f"Not a studio file: {ref}")
    else:
        path = Path(ref)
        if not path.is_absolute():
            root = _root(ctx)
            if root is None:
                raise ToolFailure(f"'{ref}' is a relative path but this chat has no workspace folder")
            path = root / path
        path = path.resolve()
    if not path.is_file():
        raise ToolFailure(f"File not found: {ref}")
    return path


async def _file(ref: str, ctx: ToolContext, suffix: str = "") -> Path:
    if ref.strip().startswith(("http://", "https://")) and f":{config.PORT}/files/" not in ref:
        return await _download(ref.strip(), suffix)
    return _local(ref, ctx)


async def _image(ref: str, ctx: ToolContext) -> Path:
    path = await _file(ref, ctx)
    if path.suffix.lower() not in images.EXTENSIONS:
        kind = await asyncio.to_thread(_sniff_image, path)
        if not kind:
            raise ToolFailure(f"{ref} is not an image")
        renamed = path.with_suffix(kind)
        path.replace(renamed)
        path = renamed
    return path


def _sniff_image(path: Path) -> str | None:
    head = path.read_bytes()[:16]
    for magic, ext in ((b"\x89PNG", ".png"), (b"\xff\xd8", ".jpg"), (b"GIF8", ".gif"), (b"RIFF", ".webp")):
        if head.startswith(magic):
            return ext
    return None


async def _job_outputs(job_id: str) -> list[Any]:
    done = await jobs.wait(job_id)
    if done.status != "done":
        raise ToolFailure(f"{done.title} {done.status}: {done.error or done.message or ''}".strip())
    return done.result.outputs if done.result else []


def _vision_helper() -> str | None:
    """An installed Ollama model that can see, for models that can't (the largest, since they describe better)."""
    try:
        tags = ollama.tags()
    except ollama.OllamaError:
        return None
    seeing = [t for t in tags if "vision" in ollama.capabilities(t["name"])]
    return max(seeing, key=lambda t: t.get("size", 0))["name"] if seeing else None


async def _describe(path: Path, question: str) -> str:
    tag = await asyncio.to_thread(_vision_helper)
    if tag is None:
        raise ToolFailure("The chat model can't see images and no vision model is installed (e.g. gemma4, "
                          "qwen3.6 or qwen2.5vl in Ollama)")
    await asyncio.to_thread(ollama.ensure_running)
    await asyncio.to_thread(models.prepare_ollama_chat, tag)
    body = {"model": tag, "stream": False, "think": False, "options": {"num_ctx": 8192},
            "messages": [{"role": "user", "content": question or "Describe this image in detail, including any "
                          "text in it.", "images": [images.encode(path)[1]]}]}
    async with httpx.AsyncClient(verify=tls, timeout=httpx.Timeout(30, read=600)) as client:
        r = await client.post(f"{config.OLLAMA_URL}/api/chat", json=body)
        if r.status_code == 400 and "think" in r.text:
            body.pop("think")
            r = await client.post(f"{config.OLLAMA_URL}/api/chat", json=body)
    if r.status_code >= 400:
        raise ToolFailure(f"{tag} could not describe the image: {r.text[:300]}")
    return f"({tag} looked at it for you) " + str(r.json().get("message", {}).get("content", "")).strip()


# ------------------------------- tools -------------------------------


async def _view_image(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    path = await _image(a["source"], ctx)
    url = images.public_url(path) or a["source"]
    display = ImageDisplay(url=url, question=a.get("question"))
    if ctx.vision:
        return ToolOutcome(True, f"The image {path.name} is attached below for you to look at.", images=[path],
                           display=display)
    return ToolOutcome(True, await _describe(path, a.get("question") or ""), display=display)


async def _edit_image(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    refs = a["images"] if isinstance(a["images"], list) else [a["images"]]
    if not 1 <= len(refs) <= 4:
        raise ToolFailure("edit_image takes 1-4 images")
    inputs = []
    for ref in refs:
        path = await _image(str(ref), ctx)
        url = images.public_url(path)
        inputs.append(url if url and url.startswith("/files/outputs/") else images.data_url(path))
    redraw = a.get("strength") is not None
    mode = "img2img" if redraw else "edit"
    profile = await inventory.image_choice(mode)
    if profile is None:
        raise ToolFailure(f"No installed image model supports {mode}")
    if mode == "edit" and len(inputs) > profile.max_images:
        raise ToolFailure(f"{profile.model_id} takes at most {profile.max_images} reference image(s)")
    d = profile.defaults
    req = ImageGenerateRequest(model_id=profile.model_id, prompt=a["prompt"], mode=mode, images=inputs,
                               strength=float(a.get("strength") or d.strength), width=d.width, height=d.height,
                               steps=d.steps, guidance=d.guidance, seed=a.get("seed"), count=1)
    job = await asyncio.to_thread(imaging.generate, req)
    outputs = await _job_outputs(job.id)
    files = [images.to_path(o.url) for o in outputs]
    return ToolOutcome(True, f"Edited with {profile.model_id} ({mode}): {', '.join(o.url for o in outputs)}"
                             + (" - the result is attached below; check it." if ctx.vision else ""),
                       outputs, images=files if ctx.vision else [])


def _clock(s: float) -> str:
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


async def _transcribe(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    m = await asyncio.to_thread(lambda: inventory.preferred("stt") or profiles.stt_model())
    if m is None:
        raise ToolFailure("No speech-to-text model is installed (search_catalog kind='stt', e.g. faster-whisper)")
    path = await _file(a["source"], ctx)
    result = await asyncio.to_thread(generation.transcribe, m.id, path, a.get("language") or None)
    lines = [f"[{_clock(s.start)}] {s.text.strip()}" for s in result.segments]
    body = "\n".join(lines) or result.text
    note = ""
    if len(body) > 10_000:
        root = _root(ctx)
        if root:
            out = root / f"transcript-{path.stem[:40]}.txt"
            out.write_text(body, encoding="utf-8")
            note = f"\n[... transcript truncated; the full text is in {out.name}]"
        else:
            note = "\n[... transcript truncated]"
        body = body[:10_000]
    return ToolOutcome(True, f"Transcribed {path.name} with {m.name} (language: {result.language}):\n{body}{note}")


async def _list_voices(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    voices = await asyncio.to_thread(profiles.list_profiles)
    q = (a.get("query") or "").lower()
    rows = []
    for v in voices:
        hay = " ".join([v.id, v.name, v.kind, v.language or "", v.gender or "", *v.tags]).lower()
        if q and not all(w in hay for w in q.split()):
            continue
        rows.append({"voice_id": v.id, "name": v.name, "kind": v.kind, "language": v.language, "gender": v.gender,
                     "model_id": v.model_id, "tags": v.tags or None})
    note = ("Presets belong to their model_id. Cloned/designed voices work with OmniVoice or Chatterbox "
            "(text_to_speech picks one when model_id is left out).")
    return ToolOutcome(True, (json.dumps(rows[:60], indent=1) + f"\n{note}") if rows else "No voices match")


async def _clone_voice(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    src = await _file(a["source"], ctx)
    staged = await asyncio.to_thread(profiles.stage_reference, src, a.get("language") or None)
    if not staged.text.strip():
        raise ToolFailure("No speech was recognized in the clip; use a recording of one person talking")
    body = CloneProfileCreate(kind="clone", name=a["name"], ref_id=staged.id, ref_text=staged.text,
                              language=a.get("language") or None)
    voice = await asyncio.to_thread(profiles.create_clone, body)
    trimmed = f" (trimmed from {staged.source_duration_s:.0f} s)" if staged.trimmed else ""
    return ToolOutcome(True, f"Created voice '{voice.name}' - voice_id {voice.id}, {staged.duration_s:.1f} s "
                             f"reference{trimmed}: \"{staged.text[:160]}\". Use it with text_to_speech. "
                             "Done - do not repeat this call.")


async def _separate_audio(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    src = await _file(a["source"], ctx)
    copy = config.UPLOADS_DIR / f"agent-{uuid.uuid4().hex[:12]}{src.suffix}"
    await asyncio.to_thread(shutil.copyfile, src, copy)  # the job owns (and may clean up) its input
    job = await asyncio.to_thread(audio_tools.isolate, copy, src.name, a.get("mode") or "vocals")
    outputs = await _job_outputs(job.id)
    return ToolOutcome(True, "Separated: " + ", ".join(f"{o.prompt or o.kind}: {o.url}" for o in outputs), outputs)


async def _start_dub(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    from ..dub import pipeline, store

    ref = a["source"].strip()
    url = ref if ref.startswith(("http://", "https://")) and f":{config.PORT}/files/" not in ref else None
    upload = None
    if url is None:
        src = _local(ref, ctx)
        upload = config.UPLOADS_DIR / f"{uuid.uuid4().hex}{src.suffix.lower()}"
        await asyncio.to_thread(shutil.copyfile, src, upload)  # the project takes ownership of (moves) its file
    try:
        project, job = await asyncio.to_thread(pipeline.create, upload, url, Path(ref).name if upload else ref,
                                               a.get("name"), None, a.get("speakers"))
    except pipeline.DubError as exc:
        raise ToolFailure(str(exc)) from exc
    info = store.to_api(project)
    return ToolOutcome(True, f"Created dub project '{info.name}' ({info.id}); job {job.id} is downloading, "
                             "transcribing and splitting speakers. Tell the user to open the Dub tab to choose target "
                             "languages and voices. Done - do not repeat this call.")


async def _list_outputs(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    rows = await asyncio.to_thread(db.list_outputs, a.get("kind"), 400)
    q = (a.get("query") or "").lower().split()
    hits = [o for o in rows if all(w in o.prompt.lower() for w in q)][:a.get("limit") or 15]
    if not hits:
        return ToolOutcome(True, "No outputs match")
    return ToolOutcome(True, json.dumps([{"url": o.url, "kind": o.kind, "model": o.model_id, "prompt": o.prompt[:200],
                                          "created": o.created_at[:16]} for o in hits], indent=1))


async def _generate_video(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    usable = [m for m in await asyncio.to_thread(inventory.usable_models) if m.kind == "video"]
    pref = await asyncio.to_thread(inventory.preferred, "video")
    m = next((x for x in usable if x.id == a.get("model_id")), None) or pref or (usable[0] if usable else None)
    if m is None:
        raise ToolFailure("No video model is installed: install_model 'ltx-2.5' (with sound) or "
                          "'wan2.2-ti2v-5b' from the catalog")
    prof = video.profile(m)
    if prof is None:
        raise ToolFailure(f"{m.name} is not a video model the studio can run")
    width, height = a.get("width"), a.get("height")
    if not (width and height):
        width, height = prof.native_width, prof.native_height
        if a.get("portrait"):
            width, height = height, width
    seconds = min(prof.max_seconds, float(a.get("duration_s") or prof.default_seconds))
    start = None
    if a.get("image"):
        path = await _image(str(a["image"]), ctx)
        url = images.public_url(path)
        start = url if url and url.startswith("/files/outputs/") else images.data_url(path)
    req = VideoRequest(model_id=m.id, prompt=a["prompt"], mode="i2v" if start else "t2v", image=start,
                       width=width, height=height, duration_s=seconds)
    job = await asyncio.to_thread(video.generate, req)
    outputs = await _job_outputs(job.id)
    sound = " with sound" if prof.audio else " (silent)"
    made = outputs[0] if outputs else None
    size = f"{made.width}x{made.height}" if made else f"{width}x{height}"
    return ToolOutcome(True, f"Made a {seconds:g} s {size} video{sound} with {m.name}: "
                             + ", ".join(o.url for o in outputs), outputs)


async def _ask_user(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    if ctx.ask is None:
        raise ToolFailure("Nobody can answer here (background task): decide yourself and say what you assumed")
    options = [str(o).strip() for o in (a.get("options") or []) if str(o).strip()][:4]
    answer = await ctx.ask(a["question"].strip(), options)
    return ToolOutcome(True, f"The user answered: {answer}")


IMPL: dict[str, Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]] = {
    "view_image": _view_image, "edit_image": _edit_image, "transcribe": _transcribe, "list_voices": _list_voices,
    "clone_voice": _clone_voice, "separate_audio": _separate_audio, "start_dub": _start_dub,
    "list_outputs": _list_outputs, "ask_user": _ask_user, "generate_video": _generate_video,
}
