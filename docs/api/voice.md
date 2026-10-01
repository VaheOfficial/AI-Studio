# Voice core (speech, profiles, takes, design, gallery, pronunciation, dictation)

Types: [`apps/studio/src/api/contracts/voice.ts`](../../apps/studio/src/api/contracts/voice.ts) (mirrored by
`server/studio/schemas_voice.py`). Server code: `server/studio/voice/` + `server/studio/routes/voice.py`.
Core changes in `types.ts`: the old `Voice` type is gone (replaced by `VoiceProfile`); `TTSRequest` is unchanged
(`SpeakRequest` extends it). The legacy `/api/voices*` routes are replaced by `/api/voice/profiles*`; clones stored
by earlier builds are migrated into profiles on startup.

## Speech
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/voice/tts` | `SpeakRequest` | `Job` (kind=generate); the audio `Output` is also a take (same id) |
| GET | `/api/voice/languages` | | `LanguageCatalog` — OmniVoice's 646 languages, popular ids, per-engine support |

- Engines: `omnivoice` (every language, cloning, design tags, `[pause]` / non-verbal tags), `kokoro` (its English
  presets), `chatterbox` (English, clones any profile with a reference clip), `openrouter` (delegated to
  `openrouter_media`; no take is recorded).
- `voice_id`: a stored profile id, a preset id (`<model>:<voice>`), or `"auto"` (OmniVoice picks a voice, or
  designs one from `instruct`). `ref_id` + `ref_text` speak with a staged clip (clone preview).
- `language`: omitted = the profile's language; `"auto"` = detect from the text even if the profile has one.
- Text pipeline (all engines): normalization (numbers, times, currency, abbreviations; ported from VoiceStudio)
  → pronunciation dictionary → inline `[[term|replacement]]`. Kokoro/Chatterbox get pause/reaction tags stripped.
- A locked profile renders from its locked take (as reference) with the take's seed → reproducible.

## Profiles and reference clips
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/voice/profiles` | | `VoiceProfile[]` (stored first, then presets of installed models) |
| POST | `/api/voice/profiles` | `ProfileCreate` (`kind: clone` with `ref_id`, or `kind: design` with `take_id`) | `VoiceProfile` |
| PATCH | `/api/voice/profiles/{id}` | `ProfileUpdate` (`ref_id` replaces the clip) | `VoiceProfile` |
| DELETE | `/api/voice/profiles/{id}` | | `204` |
| POST | `/api/voice/profiles/{id}/unlock` | | `VoiceProfile` |
| POST | `/api/voice/references` | multipart `file`, `language?` | `StagedReference` |
| POST | `/api/voice/references/{id}/transcribe` | query `language?` | `StagedReference` |

A staged reference is converted to 24 kHz mono, must be ≥ 3 s, clips over 20 s are cut to the ~15 s window with
the most transcribed speech, and it is transcribed with the installed faster-whisper model (the loaded one, else
the largest). Staged clips expire after 24 h. Profiles without a transcript are transcribed on first use.

## Takes
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/voice/takes` | `limit`, `starred?` | `VoiceTake[]` newest first |
| PATCH | `/api/voice/takes/{id}` | `{ starred }` | `VoiceTake` |
| DELETE | `/api/voice/takes/{id}` | | `204` (removes the audio output too) |
| POST | `/api/voice/takes/{id}/lock` | `{ profile_id? }` (default: the take's profile) | `VoiceProfile` |

## Voice design and gallery
| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/voice/design` | | `DesignVocabulary` (categories, exclusive groups, personalities, reaction tags, use cases) |
| POST | `/api/voice/design/describe` | `{ description }` | `DescribeResult` — deterministic phrase → tag mapping |
| GET | `/api/voice/archetypes` | `q, use_case, gender, age, pitch, accent, whisper, language, featured, offset, limit` | `ArchetypePage` |
| POST | `/api/voice/archetypes/{id}/preview` | | `ArchetypePreview` (`job` while rendering) |
| POST | `/api/voice/archetypes/{id}/use` | | `ArchetypeUse` (`profile`, or `job` that renders then saves) |

Previews render once (seed 42, 32 steps) into `data/voices/archetypes/` and are reused; "use" creates a design
profile whose reference is that preview (idempotent per archetype).

## Pronunciation
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/voice/pronunciation` | | `PronunciationEntry[]` |
| POST | `/api/voice/pronunciation` | `PronunciationInput` | `PronunciationEntry` |
| PATCH | `/api/voice/pronunciation/{id}` | partial `PronunciationInput` | `PronunciationEntry` |
| DELETE | `/api/voice/pronunciation/{id}` | | `204` |
| POST | `/api/voice/pronunciation/test` | `{ text, language? }` | `PronunciationTestResult` |

Whole-word, case-insensitive, longest term first; a language entry overrides a global (`*`) one for the same term.

## Live dictation — WebSocket `/api/voice/dictate?model_id&language`
Client → server: binary 16 kHz mono int16 PCM frames; the text frame `EOF` ends input. Server → client:
`DictationEvent` — `status` (loading/ready), `partial` (current utterance, ~1/s), `final` with
`final_kind: "utterance"` after ~0.7 s of silence (or 25 s of speech), and a `summary` final at EOF, after which the
server closes. Uses an installed faster-whisper model (greedy decoding on the utterance window). Same Origin
allow-list as `/api/ws`.

## OmniVoice worker contract (`server/workers/omnivoice_worker.py`, env `omnivoice`)
Used by the speech routes and by dubbing. Besides `/load {model_id, path}`, `/unload`, `/cancel`, `GET /health`,
`GET /progress` (worker_base):

- `POST /tts {text, language?, ref_audio?, ref_text?, instruct?, duration?, speed=1.0, num_step=16,
  guidance_scale=2.0, t_shift?, position_temperature?, class_temperature?, seed?, denoise=true,
  postprocess_output=true, out_path}` → `{path, duration_s, sample_rate, seed}`
- `POST /tts_batch {items: [...same fields...]}` → `{items: [{path, duration_s, seed}]}`

`language` is a language id or name (none = language-agnostic). `ref_text` is required with `ref_audio` (the worker
has no ASR); prompts are cached per (clip path, mtime, transcript). `duration` fixes the whole utterance length and
overrides `speed`. Text is split at `[pause …]` markers (silence) and into ≤ 800-character sentence chunks joined
with a 50 ms crossfade; non-verbal tags pass through. In `/tts_batch`, single-chunk items with equal generation
settings run as native batches of up to 8 and share the first item's seed (reported per item); others render one
by one. Text normalization / pronunciation are not applied by the worker — call
`studio.voice.pronunciation.prepare(text, language)` first if wanted.
