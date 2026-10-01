"""Archetype gallery: listing with cached previews, preview rendering and "use voice".

A preview is rendered once with OmniVoice at a fixed seed (32 steps — 16 under-converges on some
script/seed points) and cached under ``voices/archetypes/``. "Use" turns the archetype into a design
profile whose reference is that preview, so the voice is identical everywhere it is used.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import config
from ..jobs import JobContext, jobs
from ..schemas import Job
from ..schemas_voice import Archetype, ArchetypePage, ArchetypePreview, ArchetypeUse, SpeakRequest, VoiceProfile
from . import archetypes, profiles, speech
from .profiles import Conditioning, VoiceError

PREVIEW_DIR = config.VOICES_DIR / "archetypes"
PREVIEW_SEED = 42
PREVIEW_STEPS = 32


def _preview_path(a: Archetype) -> Path:
    key = hashlib.sha256(f"{a.instruct}|{a.language}".encode()).hexdigest()[:16]
    return PREVIEW_DIR / f"{key}.wav"


def _preview_url(path: Path) -> str:
    return f"/files/voices/archetypes/{path.name}"


def page(items: list[Archetype], offset: int, limit: int) -> ArchetypePage:
    owned = profiles.archetype_profile_ids()
    out = []
    for a in items[offset:offset + limit]:
        path = _preview_path(a)
        out.append(a.model_copy(update={"preview_url": _preview_url(path) if path.exists() else None,
                                        "profile_id": owned.get(a.id)}))
    return ArchetypePage(items=out, total=len(items), offset=offset)


def _get(archetype_id: str) -> Archetype:
    a = archetypes.get(archetype_id)
    if a is None:
        raise VoiceError(f"Archetype '{archetype_id}' not found", 404)
    return a


def _render_preview(ctx: JobContext, a: Archetype) -> None:
    m = speech.default_omnivoice()
    req = SpeakRequest(model_id=m.id, text=a.sample_script, voice_id="auto", num_step=PREVIEW_STEPS)
    cond = Conditioning(language=a.language, instruct=a.instruct, seed=PREVIEW_SEED)
    path = _preview_path(a)
    tmp = path.with_suffix(".part.wav")
    speech.synthesize(ctx, m, req, cond, tmp)
    tmp.replace(path)


def _use_cached(a: Archetype) -> VoiceProfile:
    existing = profiles.find_archetype_profile(a.id)
    if existing:
        return existing
    return profiles.create_design(a.name, _preview_path(a), a.sample_script, a.instruct, PREVIEW_SEED, a.language,
                                  a.attrs, [a.use_case], archetype_id=a.id)


def _job(a: Archetype, title: str, then_use: bool) -> Job:
    active = jobs.find_active(lambda j: j.title == title)
    if active:
        return active.job

    def run(ctx: JobContext) -> None:
        _render_preview(ctx, a)
        if then_use:
            ctx.update(message=f"Added “{_use_cached(a).name}” to your voices")

    return jobs.submit("generate", title, run, ref=speech.default_omnivoice().id)


def preview(archetype_id: str) -> ArchetypePreview:
    a = _get(archetype_id)
    path = _preview_path(a)
    if path.exists():
        return ArchetypePreview(url=_preview_url(path))
    return ArchetypePreview(url=_preview_url(path), job=_job(a, f"Voice preview · {a.name}", then_use=False))


def use(archetype_id: str) -> ArchetypeUse:
    a = _get(archetype_id)
    if _preview_path(a).exists() or profiles.find_archetype_profile(a.id):
        return ArchetypeUse(profile=_use_cached(a))
    return ArchetypeUse(job=_job(a, f"Add voice · {a.name}", then_use=True))
