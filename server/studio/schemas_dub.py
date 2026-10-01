"""Pydantic mirror of ``apps/studio/src/api/contracts/dub.ts`` (dubbing, audiobooks, audio tools, media tools).
Optional TS fields are ``T | None = None`` and omitted from responses (routers exclude ``None``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .schemas import Job

# ------------------------------ media tools ------------------------------


class MediaToolInfo(BaseModel):
    tool: Literal["ffmpeg", "ffprobe"]
    ok: bool
    path: str | None = None
    origin: Literal["env", "bundled", "system"] | None = None
    version: str | None = None


class MediaToolsStatus(BaseModel):
    ready: bool
    tools: list[MediaToolInfo]
    bundle_available: bool


# --------------------------------- status --------------------------------


class NllbModel(BaseModel):
    repo: str
    name: str
    size_gb: float
    cached: bool


class DubStatus(BaseModel):
    media: MediaToolsStatus
    hf_token: bool
    nllb: list[NllbModel]


# -------------------------------- projects -------------------------------

DubTiming = Literal["strict_slot", "smart_fit", "stretch_video", "concise"]
DubVoiceMatch = Literal["per_line", "consistent"]
DubQuality = Literal["fast", "cinematic", "autofit", "agent"]
DubPlanStatus = Literal["fits", "tight", "impossible"]
DubFitStatus = Literal["fits", "audio_stretched", "audio_slowed", "hybrid", "overflow_trimmed", "silent", "video_stretched"]
DubDiarizationSource = Literal["pyannote", "phrase_embeddings", "heuristic", "single", "imported"]
DubExportFormat = Literal["mp4", "wav", "mp3", "srt", "vtt", "ass", "stems", "clips"]


class DubSource(BaseModel):
    kind: Literal["file", "url"]
    filename: str
    url: str | None = None
    input_type: Literal["video", "audio"]
    duration: float
    media_url: str
    thumb_url: str | None = None


class DubSeparation(BaseModel):
    vocals_url: str
    background_url: str


class DubPlan(BaseModel):
    status: DubPlanStatus
    est_s: float
    available_s: float
    overrun_s: float
    calibrated: bool
    suggested_text: str | None = None


class DubFit(BaseModel):
    status: DubFitStatus
    audio_rate: float | None = None
    video_ratio: float | None = None
    overflow_s: float | None = None
    natural_s: float | None = None


class DubQc(BaseModel):
    drift: float
    flagged: bool
    recognized: str


class DubLine(BaseModel):
    text: str
    literal: str | None = None
    critique: str | None = None
    error: str | None = None
    degraded: str | None = None
    rate_ratio: float | None = None
    rate_error: str | None = None
    plan: DubPlan | None = None
    fingerprint: str | None = None
    fit: DubFit | None = None
    qc: DubQc | None = None


class DubWord(BaseModel):
    text: str
    start: float
    end: float
    sp: bool = True


class DubSegment(BaseModel):
    id: str
    start: float
    end: float
    speaker: str
    text: str
    voice: str | None = None
    gain: float | None = None
    speed: float | None = None
    direction: str | None = None
    translations: dict[str, DubLine] = Field(default_factory=dict)
    words: list[DubWord] = Field(default_factory=list)


class DubSpeaker(BaseModel):
    id: str
    voice: str
    ref_url: str | None = None
    ref_duration: float | None = None
    ref_kind: Literal["speaker", "segment"] | None = None
    ref_text: str | None = None
    ref_pinned: bool = False


class DubVoiceSample(BaseModel):
    segment_id: str
    start: float
    end: float
    text: str
    duration: float
    chars_per_s: float
    url: str
    suggested: bool


class DubTranslationSettings(BaseModel):
    engine: Literal["llm", "nllb"] = "llm"
    model: str | None = None
    nllb_repo: str = "facebook/nllb-200-distilled-600M"
    quality: DubQuality = "fast"
    auto_glossary: bool = True
    reflect: bool = True
    condense: bool = False
    instructions: str = Field("", max_length=5000)
    dialects: dict[str, str] = Field(default_factory=dict)


class DubTtsSettings(BaseModel):
    model_id: str | None = None
    num_step: int = Field(16, ge=4, le=64)
    guidance: float = Field(2.0, ge=0, le=4)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    instruct: str = ""


class DubFitSettings(BaseModel):
    max_audio_only_rate: float = Field(1.2, ge=1.0, le=2.0)
    audio_rate_cap: float = Field(1.5, ge=1.0, le=2.0)
    video_slow_cap: float = Field(2.0, ge=1.0, le=3.0)
    allow_video_retime: bool = True


class DubSettings(BaseModel):
    targets: list[str] = Field(default_factory=list)
    translation: DubTranslationSettings = Field(default_factory=DubTranslationSettings)
    tts: DubTtsSettings = Field(default_factory=DubTtsSettings)
    timing: DubTiming = "strict_slot"
    voice_match: DubVoiceMatch = "per_line"
    fit: DubFitSettings = Field(default_factory=DubFitSettings)
    asr_model_id: str | None = None


class DubRetimeChunk(BaseModel):
    start: float
    end: float
    at: float
    ratio: float


class DubTrack(BaseModel):
    lang: str
    url: str
    duration: float
    timing: DubTiming
    created_at: str
    stale: list[str]
    retime: list[DubRetimeChunk]


class DubExport(BaseModel):
    id: str
    format: DubExportFormat
    label: str
    url: str
    filename: str
    size: int
    created_at: str


class DubDiarization(BaseModel):
    source: DubDiarizationSource
    warning: str | None = None


class DubProject(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    source: DubSource
    source_lang: str | None = None
    num_speakers: int | None = None
    prepared: bool
    separation: DubSeparation | None = None
    diarization: DubDiarization | None = None
    warnings: list[str]
    segments: list[DubSegment]
    speakers: list[DubSpeaker]
    settings: DubSettings
    tracks: dict[str, DubTrack]
    exports: list[DubExport]


class DubProjectSummary(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    filename: str
    input_type: Literal["video", "audio"]
    duration: float
    thumb_url: str | None = None
    segments: int
    tracks: list[str]


class DubCreateResponse(BaseModel):
    project: DubProject
    job: Job


class DubSegmentInput(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    speaker: str
    text: str
    voice: str | None = None
    gain: float | None = Field(None, ge=0, le=2)
    speed: float | None = Field(None, ge=0.5, le=2)
    direction: str | None = None
    translations: dict[str, str] = Field(default_factory=dict)
    words: list[DubWord] | None = None


class DubSpeakerInput(BaseModel):
    id: str
    voice: str | None = None
    # A line whose voice clip this speaker clones; explicit null returns to the automatic reference.
    ref_segment: str | None = None


class DubProjectPatch(BaseModel):
    name: str | None = None
    source_lang: str | None = None
    num_speakers: int | None = Field(None, ge=0, le=20)
    settings: DubSettings | None = None
    speakers: list[DubSpeakerInput] | None = None
    segments: list[DubSegmentInput] | None = None


class DubRunRequest(BaseModel):
    langs: list[str] | None = None
    segment_ids: list[str] | None = None
    only_failed: bool | None = None
    only_stale: bool | None = None


class DubPreviewRequest(BaseModel):
    segment_id: str
    lang: str


class DubPreviewResponse(BaseModel):
    url: str
    duration: float


class DubExportRequest(BaseModel):
    format: DubExportFormat
    langs: list[str] = Field(default_factory=list)
    include_original: bool = False
    default_lang: str | None = None
    preserve_bg: bool = True
    bitrate: int = Field(192, ge=64, le=320)
    burn_subs: bool = False
    dual: bool = False
    karaoke: bool = False


class DubWaveform(BaseModel):
    peaks: list[float]
    onsets: list[float]
    duration: float


class DubSubtitleCue(BaseModel):
    start: float
    end: float
    text: str


class DubParsedSubtitles(BaseModel):
    cues: list[DubSubtitleCue]
    skipped: int
    dropped: int


class DubParseSubtitlesRequest(BaseModel):
    text: str = Field(max_length=2_000_000)


class DubGlossaryTerm(BaseModel):
    id: str
    source: str
    target: str
    note: str
    auto: bool


class DubGlossaryInput(BaseModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    note: str = ""


class DubAutoGlossaryRequest(BaseModel):
    lang: str


# ------------------------------- audiobooks ------------------------------


class AudiobookMetadata(BaseModel):
    title: str = ""
    author: str = ""
    narrator: str = ""
    year: str = ""
    genre: str = ""
    description: str = ""


AudiobookLoudness = Literal["off", "acx", "podcast"]


class AudiobookSettings(BaseModel):
    tts_model_id: str | None = None
    default_voice: str = ""
    voice_map: dict[str, str] = Field(default_factory=dict)
    language: str = ""
    format: Literal["m4b", "mp3"] = "m4b"
    bitrate: Literal["64k", "96k", "128k", "192k", "256k", "320k"] = "128k"
    loudness: AudiobookLoudness = "off"
    line_gap_ms: int = Field(250, ge=0, le=5000)
    paragraph_gap_ms: int = Field(600, ge=0, le=5000)
    num_step: int = Field(32, ge=4, le=64)
    guidance: float = Field(2.0, ge=0, le=4)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    seed: int | None = None
    metadata: AudiobookMetadata = Field(default_factory=AudiobookMetadata)


class AudiobookChapterPlan(BaseModel):
    title: str
    chars: int
    words: int
    voices: list[str]
    est_s: float


class AudiobookPlan(BaseModel):
    chapters: list[AudiobookChapterPlan]
    voices: list[str]
    words: int
    est_s: float


class AudiobookChapterMark(BaseModel):
    title: str
    start: float
    end: float


class AudiobookRender(BaseModel):
    id: str
    url: str
    filename: str
    format: Literal["m4b", "mp3"]
    duration: float
    size: int
    chapters: list[AudiobookChapterMark]
    cached_chapters: int
    created_at: str


class AudiobookPreview(BaseModel):
    url: str
    duration: float


class AudiobookProject(BaseModel):
    id: str
    name: str
    script: str
    settings: AudiobookSettings
    cover_url: str | None = None
    renders: list[AudiobookRender]
    previews: dict[str, AudiobookPreview]
    created_at: str
    updated_at: str


class AudiobookSummary(BaseModel):
    id: str
    name: str
    updated_at: str
    chapters: int
    renders: int


class AudiobookCreate(BaseModel):
    name: str = "Untitled audiobook"
    script: str = ""


class AudiobookPatch(BaseModel):
    name: str | None = None
    script: str | None = Field(None, max_length=20_000_000)
    settings: AudiobookSettings | None = None


class AudiobookPlanRequest(BaseModel):
    script: str = Field(max_length=20_000_000)


class AudiobookImportResult(BaseModel):
    script: str
    title: str | None = None
    chapters: int


class AudiobookRenderRequest(BaseModel):
    preview_chapter: int | None = Field(None, ge=0)
