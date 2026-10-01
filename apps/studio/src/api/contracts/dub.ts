/**
 * Contract for dubbing, audiobooks and audio tools (+ the shared ffmpeg media tools).
 * Mirrored by `server/studio/schemas_dub.py`; routes are listed in `docs/api/dub.md`.
 * Long work returns a core `Job` whose `ref` is `dub:<project id>` / `audiobook:<project id>` / `audio-tools`.
 */

import type { Job } from '../types'

/* ------------------------------ media tools ------------------------------ */

export interface MediaToolInfo {
  tool: 'ffmpeg' | 'ffprobe'
  ok: boolean
  path?: string
  origin?: 'env' | 'bundled' | 'system'
  version?: string
}

export interface MediaToolsStatus {
  ready: boolean
  tools: MediaToolInfo[]
  /** A pinned, checksummed static build exists for this platform. */
  bundle_available: boolean
}

/* --------------------------------- status -------------------------------- */

export interface NllbModel {
  repo: string
  name: string
  size_gb: number
  /** Weights already in the local Hugging Face cache. */
  cached: boolean
}

export interface DubStatus {
  media: MediaToolsStatus
  /** A Hugging Face token is configured (pyannote diarization is gated behind accepted terms). */
  hf_token: boolean
  nllb: NllbModel[]
}

/* -------------------------------- projects ------------------------------- */

export type DubTiming = 'strict_slot' | 'smart_fit' | 'stretch_video' | 'concise'
export type DubVoiceMatch = 'per_line' | 'consistent'
export type DubQuality = 'fast' | 'cinematic' | 'autofit' | 'agent'
export type DubPlanStatus = 'fits' | 'tight' | 'impossible'
/** `overflow_trimmed`: still too long after using the gap — cut with a fade; `silent`: the render had no audio. */
export type DubFitStatus = 'fits' | 'audio_stretched' | 'audio_slowed' | 'hybrid' | 'overflow_trimmed' | 'silent' | 'video_stretched'
export type DubDiarizationSource = 'pyannote' | 'phrase_embeddings' | 'heuristic' | 'single' | 'imported'

export interface DubSource {
  kind: 'file' | 'url'
  filename: string
  url?: string
  input_type: 'video' | 'audio'
  duration: number
  /** Browser-playable original (transcoded when the upload's codecs are not). */
  media_url: string
  thumb_url?: string
}

export interface DubSeparation {
  vocals_url: string
  background_url: string
}

export interface DubPlan {
  status: DubPlanStatus
  est_s: number
  available_s: number
  overrun_s: number
  /** Estimate uses this project's measured speaking rate instead of the static table. */
  calibrated: boolean
  /** Shorter rewrite for an impossible line (opt-in "condense"); never applied automatically. */
  suggested_text?: string
}

export interface DubFit {
  status: DubFitStatus
  audio_rate?: number
  video_ratio?: number
  overflow_s?: number
  natural_s?: number
}

export interface DubQc {
  drift: number
  flagged: boolean
  recognized: string
}

/** One segment's text in one target language, plus its translation/render/QC state. */
export interface DubLine {
  text: string
  literal?: string
  critique?: string
  error?: string
  degraded?: string
  rate_ratio?: number
  rate_error?: string
  plan?: DubPlan
  /** Fingerprint of the inputs the current track audio was rendered from. */
  fingerprint?: string
  fit?: DubFit
  qc?: DubQc
}

export interface DubSegment {
  id: string
  start: number
  end: number
  speaker: string
  /** Source-language text (what translation reads). */
  text: string
  /** Per-line voice override: a voice id, 'auto' (clone this line's own source audio) or absent (speaker's). */
  voice?: string
  gain?: number
  speed?: number
  /** Delivery direction, e.g. "urgent, whispered" — steers translation and lip-sync pacing. */
  direction?: string
  translations: Record<string, DubLine>
  /** Recognised words of `text` with their timing (empty for typed/edited text). */
  words: DubWord[]
}

/** A recognised source word; `sp` is false when it is glued to the previous word (no space before it). */
export interface DubWord {
  text: string
  start: number
  end: number
  sp: boolean
}

export interface DubSpeaker {
  id: string
  /** 'auto' = clone from the source video, '' = engine default voice, otherwise a voice id. */
  voice: string
  ref_url?: string
  ref_duration?: number
  ref_kind?: 'speaker' | 'segment'
  /** What the clone sample says (its transcript). */
  ref_text?: string
  /** The sample was picked by the user (used for all of this speaker's lines). */
  ref_pinned: boolean
}

/** One of a speaker's line clips offered as its clone sample. */
export interface DubVoiceSample {
  segment_id: string
  start: number
  end: number
  text: string
  duration: number
  chars_per_s: number
  /** Same URL as `DubSpeaker.ref_url` when it is the speaker's current sample. */
  url: string
  /** Among the steadiest (ordinary speaking rate, 4–10 s). */
  suggested: boolean
}

export interface DubTranslationSettings {
  engine: 'llm' | 'nllb'
  /** Chat model id (`<provider>:<model>`); also powers the LLM passes when the engine is NLLB. */
  model?: string
  nllb_repo: string
  quality: DubQuality
  auto_glossary: boolean
  reflect: boolean
  condense: boolean
  instructions: string
  /** Target language → regional dialect code, e.g. { es: 'es-AR' }. */
  dialects: Record<string, string>
}

export interface DubTtsSettings {
  model_id?: string
  num_step: number
  guidance: number
  speed: number
  instruct: string
}

export interface DubFitSettings {
  max_audio_only_rate: number
  audio_rate_cap: number
  video_slow_cap: number
  allow_video_retime: boolean
}

export interface DubSettings {
  targets: string[]
  translation: DubTranslationSettings
  tts: DubTtsSettings
  timing: DubTiming
  voice_match: DubVoiceMatch
  fit: DubFitSettings
  asr_model_id?: string
}

export interface DubTrack {
  lang: string
  url: string
  duration: number
  timing: DubTiming
  created_at: string
  /** Segment ids whose inputs changed since this track was rendered. */
  stale: string[]
  /** How the video is retimed to stay in sync with this track (smart fit / stretch video); empty when it isn't. */
  retime: DubRetimeChunk[]
}

/** A contiguous stretch of the source, `start`–`end` (source seconds), shown `ratio`× slower from `at` on the track. */
export interface DubRetimeChunk {
  start: number
  end: number
  at: number
  ratio: number
}

export type DubExportFormat = 'mp4' | 'wav' | 'mp3' | 'srt' | 'vtt' | 'ass' | 'stems' | 'clips'

export interface DubExport {
  id: string
  format: DubExportFormat
  label: string
  url: string
  filename: string
  size: number
  created_at: string
}

export interface DubDiarization {
  source: DubDiarizationSource
  warning?: string
}

export interface DubProject {
  id: string
  name: string
  created_at: string
  updated_at: string
  source: DubSource
  source_lang?: string
  num_speakers?: number
  /** Ingest, separation and transcription have finished. */
  prepared: boolean
  separation?: DubSeparation
  diarization?: DubDiarization
  warnings: string[]
  segments: DubSegment[]
  speakers: DubSpeaker[]
  settings: DubSettings
  tracks: Record<string, DubTrack>
  exports: DubExport[]
}

export interface DubProjectSummary {
  id: string
  name: string
  created_at: string
  updated_at: string
  filename: string
  input_type: 'video' | 'audio'
  duration: number
  thumb_url?: string
  segments: number
  tracks: string[]
}

export interface DubCreateResponse {
  project: DubProject
  job: Job
}

export interface DubSegmentInput {
  id: string
  start: number
  end: number
  speaker: string
  text: string
  voice?: string
  gain?: number
  speed?: number
  direction?: string
  /** Target language → edited line text. Unchanged text keeps its translation/render state. */
  translations: Record<string, string>
  /** Word timing carried through merges/splits; kept only while it still spells `text`. */
  words?: DubWord[]
}

export interface DubSpeakerInput {
  id: string
  voice?: string
  /** Clone this line's voice clip for the speaker; null returns to the automatic reference. */
  ref_segment?: string | null
}

export interface DubProjectPatch {
  name?: string
  source_lang?: string
  num_speakers?: number
  settings?: DubSettings
  speakers?: DubSpeakerInput[]
  segments?: DubSegmentInput[]
}

export interface DubRunRequest {
  langs?: string[]
  segment_ids?: string[]
  /** Translate: only lines that failed last time. */
  only_failed?: boolean
  /** Generate: re-render only lines whose inputs changed (everything else is re-mixed). */
  only_stale?: boolean
}

export interface DubPreviewRequest {
  segment_id: string
  lang: string
}

export interface DubPreviewResponse {
  url: string
  duration: number
}

export interface DubExportRequest {
  format: DubExportFormat
  /** Tracks for mp4 (each becomes an audio stream); the first one for audio/subtitle/stem formats. */
  langs: string[]
  include_original: boolean
  default_lang?: string
  preserve_bg: boolean
  bitrate: number
  burn_subs: boolean
  dual: boolean
  karaoke: boolean
}

export interface DubWaveform {
  peaks: number[]
  onsets: number[]
  duration: number
}

export interface DubSubtitleCue {
  start: number
  end: number
  text: string
}

export interface DubParsedSubtitles {
  cues: DubSubtitleCue[]
  skipped: number
  dropped: number
}

export interface DubParseSubtitlesRequest {
  text: string
}

export interface DubAutoGlossaryRequest {
  lang: string
}

export interface DubGlossaryTerm {
  id: string
  source: string
  target: string
  note: string
  auto: boolean
}

export interface DubGlossaryInput {
  source: string
  target: string
  note?: string
}

/* ------------------------------- audiobooks ------------------------------ */

export interface AudiobookMetadata {
  title: string
  author: string
  narrator: string
  year: string
  genre: string
  description: string
}

export type AudiobookLoudness = 'off' | 'acx' | 'podcast'
export type AudiobookBitrate = '64k' | '96k' | '128k' | '192k' | '256k' | '320k'

export interface AudiobookSettings {
  tts_model_id?: string
  /** Voice for unmarked text ('' = engine default). */
  default_voice: string
  /** `[voice:NAME]` → voice id. */
  voice_map: Record<string, string>
  /** Language code, '' = auto. */
  language: string
  format: 'm4b' | 'mp3'
  bitrate: AudiobookBitrate
  loudness: AudiobookLoudness
  line_gap_ms: number
  paragraph_gap_ms: number
  num_step: number
  guidance: number
  speed: number
  seed?: number
  metadata: AudiobookMetadata
}

export interface AudiobookChapterPlan {
  title: string
  chars: number
  words: number
  voices: string[]
  est_s: number
}

export interface AudiobookPlan {
  chapters: AudiobookChapterPlan[]
  voices: string[]
  words: number
  est_s: number
}

export interface AudiobookChapterMark {
  title: string
  start: number
  end: number
}

export interface AudiobookRender {
  id: string
  url: string
  filename: string
  format: 'm4b' | 'mp3'
  duration: number
  size: number
  chapters: AudiobookChapterMark[]
  cached_chapters: number
  created_at: string
}

export interface AudiobookPreview {
  url: string
  duration: number
}

export interface AudiobookProject {
  id: string
  name: string
  script: string
  settings: AudiobookSettings
  cover_url?: string
  renders: AudiobookRender[]
  /** Chapter index → rendered chapter preview. */
  previews: Record<string, AudiobookPreview>
  created_at: string
  updated_at: string
}

export interface AudiobookSummary {
  id: string
  name: string
  updated_at: string
  chapters: number
  renders: number
}

export interface AudiobookCreate {
  name?: string
  script?: string
}

export interface AudiobookPatch {
  name?: string
  script?: string
  settings?: AudiobookSettings
}

export interface AudiobookPlanRequest {
  script: string
}

export interface AudiobookImportResult {
  script: string
  title?: string
  chapters: number
}

export interface AudiobookRenderRequest {
  /** Render only this chapter as a preview instead of the whole book. */
  preview_chapter?: number
}
