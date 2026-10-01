"""Pydantic mirror of ``apps/studio/src/api/contracts/voice.ts`` (voice core: profiles, takes, languages,
voice design, archetype gallery, pronunciation, dictation). Routes are listed in ``docs/api/voice.md``."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from .schemas import Job, TTSRequest

ProfileKind = Literal["preset", "clone", "design"]

# ------------------------------ profiles ------------------------------


class VoiceProfile(BaseModel):
    id: str
    name: str
    kind: ProfileKind
    model_id: str | None = None  # presets: the installed model they belong to
    language: str | None = None  # language id (see /voice/languages); absent = auto
    gender: str | None = None
    tags: list[str]
    ref_audio_url: str | None = None
    ref_text: str | None = None
    ref_duration_s: float | None = None
    instruct: str | None = None
    vd_states: dict[str, str] | None = None
    seed: int | None = None
    is_locked: bool = False
    locked_audio_url: str | None = None
    locked_text: str | None = None
    archetype_id: str | None = None
    created_at: str | None = None


class StagedReference(BaseModel):
    id: str
    url: str
    duration_s: float
    source_duration_s: float
    trimmed: bool
    text: str
    language: str | None = None
    transcribed: bool
    note: str | None = None


class CloneProfileCreate(BaseModel):
    kind: Literal["clone"]
    name: str = Field(min_length=1, max_length=80)
    ref_id: str
    ref_text: str = Field(min_length=1)
    language: str | None = None
    instruct: str | None = None
    tags: list[str] = Field(default_factory=list)


class DesignProfileCreate(BaseModel):
    kind: Literal["design"]
    name: str = Field(min_length=1, max_length=80)
    take_id: str
    vd_states: dict[str, str] | None = None
    tags: list[str] = Field(default_factory=list)


ProfileCreate = Annotated[Union[CloneProfileCreate, DesignProfileCreate], Field(discriminator="kind")]


class ProfileUpdate(BaseModel):
    """Partial update; ``""`` clears ``language`` / ``instruct``. ``ref_id`` replaces the reference clip."""

    name: str | None = Field(None, min_length=1, max_length=80)
    ref_text: str | None = None
    instruct: str | None = None
    language: str | None = None
    tags: list[str] | None = None
    vd_states: dict[str, str] | None = None
    ref_id: str | None = None


# -------------------------------- speech --------------------------------

AUTO_VOICE = "auto"


class SpeakRequest(TTSRequest):
    """``TTSRequest`` plus OmniVoice controls. ``voice_id`` is a profile id, a preset id, or ``"auto"``
    (OmniVoice picks a voice, or designs one from ``instruct``)."""

    language: str | None = None
    instruct: str | None = None
    ref_id: str | None = None
    ref_text: str | None = None
    duration: float | None = Field(None, gt=0.2, le=600)
    num_step: int | None = Field(None, ge=1, le=128)
    guidance_scale: float | None = Field(None, ge=0, le=10)
    t_shift: float | None = Field(None, gt=0, le=1)
    position_temperature: float | None = Field(None, ge=0, le=20)
    class_temperature: float | None = Field(None, ge=0, le=5)
    denoise: bool | None = None
    postprocess_output: bool | None = None
    seed: int | None = Field(None, ge=0, le=2**31 - 1)


class VoiceTake(BaseModel):
    id: str
    url: str
    text: str
    model_id: str
    engine: str
    language: str | None = None
    instruct: str | None = None
    profile_id: str | None = None
    profile_name: str | None = None
    seed: int | None = None
    params: dict[str, Any]
    duration_s: float
    gen_time_s: float
    starred: bool
    created_at: str


class TakeUpdate(BaseModel):
    starred: bool


class TakeLock(BaseModel):
    profile_id: str | None = None


# ------------------------------- languages -------------------------------


class Language(BaseModel):
    id: str
    name: str


class LanguageCatalog(BaseModel):
    languages: list[Language]
    popular: list[str]
    engines: dict[str, list[str] | None]  # runtime id -> supported language ids (None = all)


# --------------------------------- design ---------------------------------


class DesignCategory(BaseModel):
    id: str
    label: str
    options: list[str]


class Personality(BaseModel):
    id: str
    name: str
    instruct: str
    attrs: dict[str, str]
    description: str


class UseCase(BaseModel):
    id: str
    name: str


class DesignVocabulary(BaseModel):
    categories: list[DesignCategory]
    exclusive: list[list[str]]
    personalities: list[Personality]
    reaction_tags: list[str]
    use_cases: list[UseCase]


class DescribeRequest(BaseModel):
    description: str = Field(max_length=2000)


class DescribeMatch(BaseModel):
    category: str
    token: str
    phrase: str


class DescribeResult(BaseModel):
    attrs: dict[str, str]
    instruct: str
    matched: list[DescribeMatch]
    unmatched: list[str]


class Archetype(BaseModel):
    id: str
    name: str
    use_case: str
    instruct: str
    attrs: dict[str, str]
    gender: str | None = None
    age: str | None = None
    pitch: str | None = None
    accent: str | None = None
    whisper: bool
    language: str
    language_name: str
    sample_script: str
    featured: bool
    preview_url: str | None = None
    profile_id: str | None = None


class ArchetypePage(BaseModel):
    items: list[Archetype]
    total: int
    offset: int


class ArchetypePreview(BaseModel):
    url: str
    job: Job | None = None  # present while the preview is being rendered


class ArchetypeUse(BaseModel):
    profile: VoiceProfile | None = None
    job: Job | None = None  # present when the preview has to be rendered first


# ------------------------------ pronunciation ------------------------------


class PronunciationEntry(BaseModel):
    id: str
    term: str
    replacement: str
    language: str  # "*" = every language, else a language id
    enabled: bool
    created_at: str


class PronunciationInput(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    replacement: str = Field(max_length=500)
    language: str = "*"
    enabled: bool = True


class PronunciationPatch(BaseModel):
    term: str | None = Field(None, min_length=1, max_length=200)
    replacement: str | None = Field(None, max_length=500)
    language: str | None = None
    enabled: bool | None = None


class PronunciationTestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    language: str | None = None


class PronunciationHit(BaseModel):
    term: str
    replacement: str


class PronunciationTestResult(BaseModel):
    spoken: str
    hits: list[PronunciationHit]


# ------------------------- dictation (WebSocket /api/voice/dictate) -------------------------


class DictationStatus(BaseModel):
    type: Literal["status"] = "status"
    stage: Literal["loading", "ready"]
    model_id: str


class DictationPartial(BaseModel):
    type: Literal["partial"] = "partial"
    text: str


class DictationFinal(BaseModel):
    type: Literal["final"] = "final"
    text: str
    final_kind: Literal["utterance", "summary"]
    duration_s: float


class DictationError(BaseModel):
    type: Literal["error"] = "error"
    message: str
