/**
 * Voice core contract: voice profiles (presets, clones, designs), speech requests and takes, languages,
 * voice design + archetype gallery, pronunciation dictionary and live dictation.
 * Mirrored by `server/studio/schemas_voice.py`; routes are listed in `docs/api/voice.md`.
 */
import type { Job, TTSRequest } from '../types'

/* -------------------------------- profiles -------------------------------- */

export type ProfileKind = 'preset' | 'clone' | 'design'

export interface VoiceProfile {
  /** Stored profiles: "vp-…" (older clones "clone-…"); presets: "<model id>:<voice>". */
  id: string
  name: string
  kind: ProfileKind
  /** Presets: the installed model they belong to. */
  model_id?: string
  /** Language id (see `LanguageCatalog`); absent = auto. */
  language?: string
  gender?: string
  tags: string[]
  /** Clone: the user's clip; design: the rendered sample that pins the voice. */
  ref_audio_url?: string
  /** Transcript of the reference clip. */
  ref_text?: string
  ref_duration_s?: number
  /** Voice-design tags ("female, elderly, low pitch") — the design itself, or a clone's optional style. */
  instruct?: string
  /** Design picker state: category id -> tag or "Auto". */
  vd_states?: Record<string, string>
  seed?: number
  /** Locked to one of its takes: that take is the reference and its seed is fixed. */
  is_locked: boolean
  locked_audio_url?: string
  locked_text?: string
  /** Set when the profile was created from a gallery archetype. */
  archetype_id?: string
  created_at?: string
}

/** A reference clip uploaded for cloning: normalised, trimmed to the best ~15 s, auto-transcribed. */
export interface StagedReference {
  id: string
  url: string
  duration_s: number
  /** Length of the upload before trimming. */
  source_duration_s: number
  trimmed: boolean
  text: string
  /** Language Whisper detected (ISO code). */
  language?: string
  /** False when no Whisper model is installed (type the transcript). */
  transcribed: boolean
  note?: string
}

export type ProfileCreate =
  | { kind: 'clone'; name: string; ref_id: string; ref_text: string; language?: string; instruct?: string; tags?: string[] }
  /** A designed voice from a take rendered with design tags; the take's audio + seed pin the voice. */
  | { kind: 'design'; name: string; take_id: string; vd_states?: Record<string, string>; tags?: string[] }

/** Partial update; `""` clears `language` / `instruct`. `ref_id` replaces the reference clip. */
export interface ProfileUpdate {
  name?: string
  ref_text?: string
  instruct?: string
  language?: string
  tags?: string[]
  vd_states?: Record<string, string>
  ref_id?: string
}

/* ---------------------------------- speech ---------------------------------- */

/** `voice_id` value for OmniVoice without a profile: the model picks a voice, or designs one from `instruct`. */
export const AUTO_VOICE = 'auto'

/** POST /api/voice/tts. `TTSRequest` plus OmniVoice controls (ignored by other engines). */
export interface SpeakRequest extends TTSRequest {
  /** Language id; "auto" ignores the profile's language. Omitted = the profile's language (or auto). */
  language?: string
  /** Design tags; overrides the profile's. */
  instruct?: string
  /** Speak with a staged reference clip instead of a saved voice (clone preview). */
  ref_id?: string
  ref_text?: string
  /** Fixed length in seconds (overrides speed). */
  duration?: number
  num_step?: number
  guidance_scale?: number
  t_shift?: number
  position_temperature?: number
  class_temperature?: number
  denoise?: boolean
  postprocess_output?: boolean
  seed?: number
}

/** One render. Its audio is also a regular audio `Output` with the same id. */
export interface VoiceTake {
  id: string
  url: string
  text: string
  model_id: string
  /** Runtime id of the engine. */
  engine: string
  language?: string
  instruct?: string
  profile_id?: string
  profile_name?: string
  seed?: number
  params: Record<string, unknown>
  duration_s: number
  gen_time_s: number
  starred: boolean
  created_at: string
}

/* -------------------------------- languages -------------------------------- */

export interface Language {
  id: string
  name: string
}

export interface LanguageCatalog {
  languages: Language[]
  /** Ids shown first in pickers. */
  popular: string[]
  /** Runtime id -> supported language ids; `null` = every language. */
  engines: Record<string, string[] | null>
}

/* ---------------------------------- design ---------------------------------- */

export interface DesignCategory {
  /** "Gender" | "Age" | "Pitch" | "Style" | "EnglishAccent" | "ChineseDialect" */
  id: string
  label: string
  options: string[]
}

export interface Personality {
  id: string
  name: string
  instruct: string
  attrs: Record<string, string>
  description: string
}

export interface UseCase {
  id: string
  name: string
}

export interface DesignVocabulary {
  categories: DesignCategory[]
  /** Category ids of which at most one may be set (English accent vs Chinese dialect). */
  exclusive: string[][]
  personalities: Personality[]
  /** Non-verbal tags OmniVoice renders as sounds: "[laughter]", "[sigh]", … */
  reaction_tags: string[]
  use_cases: UseCase[]
}

export interface DescribeResult {
  attrs: Record<string, string>
  instruct: string
  matched: { category: string; token: string; phrase: string }[]
  /** Parts of the description no tag could express. */
  unmatched: string[]
}

export interface Archetype {
  id: string
  name: string
  use_case: string
  instruct: string
  attrs: Record<string, string>
  gender?: string
  age?: string
  pitch?: string
  /** English accent or Chinese dialect. */
  accent?: string
  whisper: boolean
  language: string
  language_name: string
  sample_script: string
  featured: boolean
  /** Present once the preview has been rendered. */
  preview_url?: string
  /** Present once the archetype is in the library. */
  profile_id?: string
}

export interface ArchetypePage {
  items: Archetype[]
  total: number
  offset: number
}

export interface ArchetypeFilters {
  q?: string
  use_case?: string
  gender?: string
  age?: string
  pitch?: string
  accent?: string
  whisper?: boolean
  language?: string
  featured?: boolean
}

/** `url` plays once `job` (present while rendering) is done. */
export interface ArchetypePreview {
  url: string
  job?: Job
}

/** Either the profile right away, or the job rendering its sample first (profiles refresh when it ends). */
export interface ArchetypeUse {
  profile?: VoiceProfile
  job?: Job
}

/* ------------------------------ pronunciation ------------------------------ */

export interface PronunciationEntry {
  id: string
  term: string
  replacement: string
  /** "*" = every language, else a language id. */
  language: string
  enabled: boolean
  created_at: string
}

export interface PronunciationInput {
  term: string
  replacement: string
  language: string
  enabled: boolean
}

export interface PronunciationTestResult {
  /** Text as the engine receives it (normalised, dictionary and inline `[[term|replacement]]` applied). */
  spoken: string
  hits: { term: string; replacement: string }[]
}

/* ---------------- live dictation: WebSocket /api/voice/dictate?model_id&language ---------------- */

/** Client → server: binary 16 kHz mono int16 PCM frames; the text frame "EOF" ends input. */
export type DictationEvent =
  | { type: 'status'; stage: 'loading' | 'ready'; model_id: string }
  | { type: 'partial'; text: string }
  | { type: 'final'; text: string; final_kind: 'utterance' | 'summary'; duration_s: number }
  | { type: 'error'; message: string }
