"""Scene art, narration and location music for game mode, made with the studio's own models (the Settings default for
each task, else the best local one): the image model draws a turn's ``scene``, a narrator voice reads its narration, and the music model composes a loop for the
current location from the latest ``mood``. Each is an ordinary studio job (visible in the Jobs tray, swapping models
on the GPU like any other); when it finishes, the result is saved and pushed as ``game.media``."""

from __future__ import annotations

import asyncio
import re

from .. import events, generation, imaging
from ..agent import inventory
from ..events import bus
from ..jobs import jobs
from ..schemas import Job, MusicRequest, TTSRequest
from ..schemas_game import EvGameMedia, GameTurn
from ..schemas_image import ImageGenerateRequest, ImageModelProfile
from ..voice import speech
from . import store

SCENE_SIZE = (1344, 768)  # wide, cinematic
NARRATOR = {"kokoro": "bm_george"}  # a warm British storyteller; other engines use their default voice
MUSIC_SECONDS = 60


class MediaError(RuntimeError):
    """No model for this kind of media is installed; message is user-facing."""


def _usable(kind: str) -> list:
    return [m for m in inventory.usable_models() if m.kind == kind]


def _plain(markdown: str) -> str:
    text = re.sub(r"[*_#`>]+", "", markdown)
    return re.sub(r"\n{2,}", "\n\n", text).strip()[:4000]


def illustrate(gid: str, turn: GameTurn, setting: str, profile: ImageModelProfile | None) -> Job:
    """``profile``: the image model to draw with (``inventory.image_choice()``: the Settings default or the best local
    model)."""
    if profile is None:
        raise MediaError("No image model is installed — add one in Models (FLUX.2 [klein] works well)")
    scene = turn.scene or turn.narration.split("\n")[0][:300]
    prompt = f"{scene} Setting: {setting[:240]} Detailed digital painting, concept art, cinematic lighting, no text."
    width, height = SCENE_SIZE
    if profile.size is not None:  # keep within what the model accepts
        width, height = (min(max(v, profile.size.min), profile.size.max) for v in (width, height))
    d = profile.defaults
    wide = {o.id: "16:9" for o in profile.options if o.id == "aspect_ratio" and "16:9" in o.values}  # cloud models
    job = imaging.generate(ImageGenerateRequest(model_id=profile.model_id, prompt=prompt, width=width, height=height,
                                                steps=d.steps, guidance=d.guidance, count=1, options=wide))
    _follow(gid, job, turn_id=turn.id, kind="image")
    return job


def narrate(gid: str, turn: GameTurn) -> Job:
    voices = _usable("voice")
    m = inventory.preferred("voice") or next((v for v in voices if v.runtime == "kokoro"), None) or next(
        (v for v in voices if v.runtime in ("chatterbox", "omnivoice")), None)
    if m is None:
        raise MediaError("No text-to-speech model is installed — add Kokoro in Models")
    voice = f"{m.id}:{NARRATOR.get(m.runtime, 'default')}"
    job = speech.tts(TTSRequest(model_id=m.id, text=_plain(turn.narration), voice_id=voice, speed=1.0))
    _follow(gid, job, turn_id=turn.id, kind="audio")
    return job


def compose(gid: str, location: str, mood: str, setting: str) -> Job:
    pref = inventory.preferred("music")
    music = [pref] if pref else _usable("music")
    if not music:
        raise MediaError("No music model is installed — add ACE-Step in Models")
    style = mood or f"atmospheric, cinematic, {setting[:80]}"
    tags = f"{style}, instrumental, ambient game soundtrack, seamless loop"
    job = generation.generate_music(MusicRequest(model_id=music[0].id, tags=tags, lyrics="[instrumental]",
                                                 duration_s=MUSIC_SECONDS, steps=60, guidance=15.0))
    _follow(gid, job, location=location, kind="music")
    return job


def _follow(gid: str, job: Job, *, kind: str, turn_id: str | None = None, location: str | None = None) -> None:
    async def wait() -> None:
        done = await jobs.wait(job.id)
        outputs = done.result.outputs if done.status == "done" and done.result else []
        if not outputs:
            bus.publish(EvGameMedia(game_id=gid, turn_id=turn_id, location=location,
                                    error=done.error or done.message or f"{kind} generation {done.status}"))
            return
        url = outputs[0].url
        try:
            if kind == "music" and location is not None:
                await asyncio.to_thread(store.set_music, gid, location, url)
            elif turn_id is not None:
                await asyncio.to_thread(store.set_media, turn_id, **{kind: url})
        except store.NotFound:
            return  # the game or turn was deleted meanwhile
        bus.publish(EvGameMedia(game_id=gid, turn_id=turn_id, location=location, **{kind: url}))

    task = asyncio.get_running_loop().create_task(wait(), name=f"game-media-{job.id}")
    task.add_done_callback(lambda t: t.cancelled() or t.exception() is None or events.log(
        "error", "game", f"Media for game {gid} failed: {t.exception()}"))
