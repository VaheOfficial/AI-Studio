"""Voice core routes: speech, profiles, reference clips, takes, languages, voice design, archetype gallery,
pronunciation dictionary and live dictation. Documented in docs/api/voice.md."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, TypeVar

from fastapi import Body, File, Form, HTTPException, Query, Response, UploadFile, WebSocket

from ..models import ModelError
from ..schemas import Job
from ..schemas_voice import (
    ArchetypePage,
    ArchetypePreview,
    ArchetypeUse,
    DescribeRequest,
    DescribeResult,
    DesignCategory,
    DesignVocabulary,
    LanguageCatalog,
    ProfileCreate,
    ProfileUpdate,
    PronunciationEntry,
    PronunciationInput,
    PronunciationPatch,
    PronunciationTestRequest,
    PronunciationTestResult,
    SpeakRequest,
    StagedReference,
    TakeLock,
    TakeUpdate,
    VoiceProfile,
    VoiceTake,
)
from ..voice import archetypes, describe, dictation, gallery, languages, profiles, pronunciation, speech, takes
from ..voice.profiles import VoiceError
from ..voice.pronunciation import PronunciationError
from ..voice.taxonomy import CATEGORY_LABELS, CATEGORY_OPTIONS, CATEGORY_ORDER, REACTION_TAGS
from . import StudioRouter
from .generate import save_upload
from .ws import ALLOWED_ORIGINS

router = StudioRouter(prefix="/api/voice")
T = TypeVar("T")


async def _call(fn: Callable[..., T], *args: object) -> T:
    """Run blocking voice work off the event loop, mapping domain errors to HTTP errors."""
    try:
        return await asyncio.to_thread(fn, *args)
    except (VoiceError, ModelError, PronunciationError) as exc:
        raise HTTPException(exc.status, str(exc)) from exc


async def _no_content(awaitable: Awaitable[object]) -> Response:
    await awaitable
    return Response(status_code=204)


# ---------------------------------- speech ----------------------------------


@router.post("/tts", response_model=Job)
async def tts(req: SpeakRequest) -> Job:
    return await _call(speech.tts, req)


@router.get("/languages", response_model=LanguageCatalog)
async def list_languages() -> LanguageCatalog:
    return languages.catalog()


# --------------------------------- profiles ---------------------------------


@router.get("/profiles", response_model=list[VoiceProfile])
async def list_profiles() -> list[VoiceProfile]:
    return await _call(profiles.list_profiles)


@router.post("/profiles", response_model=VoiceProfile)
async def create_profile(body: Annotated[ProfileCreate, Body()]) -> VoiceProfile:
    if body.kind == "clone":
        return await _call(profiles.create_clone, body)
    return await _call(profiles.create_design_from_take, body)


@router.patch("/profiles/{profile_id}", response_model=VoiceProfile)
async def update_profile(profile_id: str, body: ProfileUpdate) -> VoiceProfile:
    return await _call(profiles.update, profile_id, body)


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(profile_id: str) -> Response:
    return await _no_content(_call(profiles.delete, profile_id))


@router.post("/profiles/{profile_id}/unlock", response_model=VoiceProfile)
async def unlock_profile(profile_id: str) -> VoiceProfile:
    return await _call(profiles.unlock, profile_id)


@router.post("/references", response_model=StagedReference)
async def stage_reference(file: UploadFile = File(...), language: str | None = Form(None)) -> StagedReference:
    path = await save_upload(file)
    try:
        return await _call(profiles.stage_reference, path, language)
    finally:
        path.unlink(missing_ok=True)


@router.post("/references/{ref_id}/transcribe", response_model=StagedReference)
async def retranscribe_reference(ref_id: str, language: str | None = None) -> StagedReference:
    return await _call(profiles.retranscribe, ref_id, language)


# ----------------------------------- takes -----------------------------------


@router.get("/takes", response_model=list[VoiceTake])
async def list_takes(limit: int = Query(100, ge=1, le=500), starred: bool | None = None) -> list[VoiceTake]:
    return await _call(takes.list_takes, limit, starred)


@router.patch("/takes/{take_id}", response_model=VoiceTake)
async def update_take(take_id: str, body: TakeUpdate) -> VoiceTake:
    return await _call(takes.set_starred, take_id, body.starred)


@router.delete("/takes/{take_id}", status_code=204)
async def delete_take(take_id: str) -> Response:
    return await _no_content(_call(takes.delete, take_id))


@router.post("/takes/{take_id}/lock", response_model=VoiceProfile)
async def lock_take(take_id: str, body: TakeLock) -> VoiceProfile:
    return await _call(takes.lock, take_id, body.profile_id)


# --------------------------------- design ---------------------------------


@router.get("/design", response_model=DesignVocabulary)
async def design_vocabulary() -> DesignVocabulary:
    return DesignVocabulary(
        categories=[DesignCategory(id=c, label=CATEGORY_LABELS[c], options=CATEGORY_OPTIONS[c])
                    for c in CATEGORY_ORDER],
        exclusive=[["EnglishAccent", "ChineseDialect"]], personalities=archetypes.PERSONALITIES,
        reaction_tags=REACTION_TAGS, use_cases=archetypes.USE_CASES,
    )


@router.post("/design/describe", response_model=DescribeResult)
async def describe_voice(body: DescribeRequest) -> DescribeResult:
    return describe.parse_description(body.description)


@router.get("/archetypes", response_model=ArchetypePage)
async def list_archetypes(q: str | None = None, use_case: str | None = None, gender: str | None = None,
                          age: str | None = None, pitch: str | None = None, accent: str | None = None,
                          whisper: bool | None = None, language: str | None = None, featured: bool | None = None,
                          offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=200)) -> ArchetypePage:
    items = archetypes.search(q, use_case, gender, age, pitch, accent, whisper, language, featured)
    return await _call(gallery.page, items, offset, limit)


@router.post("/archetypes/{archetype_id}/preview", response_model=ArchetypePreview)
async def preview_archetype(archetype_id: str) -> ArchetypePreview:
    return await _call(gallery.preview, archetype_id)


@router.post("/archetypes/{archetype_id}/use", response_model=ArchetypeUse)
async def use_archetype(archetype_id: str) -> ArchetypeUse:
    return await _call(gallery.use, archetype_id)


# ------------------------------ pronunciation ------------------------------


@router.get("/pronunciation", response_model=list[PronunciationEntry])
async def list_pronunciation() -> list[PronunciationEntry]:
    return await _call(pronunciation.list_entries)


@router.post("/pronunciation", response_model=PronunciationEntry)
async def create_pronunciation(body: PronunciationInput) -> PronunciationEntry:
    return await _call(pronunciation.create, body)


@router.patch("/pronunciation/{entry_id}", response_model=PronunciationEntry)
async def update_pronunciation(entry_id: str, body: PronunciationPatch) -> PronunciationEntry:
    return await _call(pronunciation.update, entry_id, body)


@router.delete("/pronunciation/{entry_id}", status_code=204)
async def delete_pronunciation(entry_id: str) -> Response:
    return await _no_content(_call(pronunciation.delete, entry_id))


@router.post("/pronunciation/test", response_model=PronunciationTestResult)
async def test_pronunciation(body: PronunciationTestRequest) -> PronunciationTestResult:
    return await _call(pronunciation.test, body.text, body.language)


# -------------------------------- dictation --------------------------------


@router.websocket("/dictate")
async def dictate(ws: WebSocket, model_id: str | None = None, language: str | None = None) -> None:
    origin = ws.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:  # other websites must not stream to the mic socket
        await ws.close(code=1008)
        return
    await dictation.run(ws, model_id, language)

