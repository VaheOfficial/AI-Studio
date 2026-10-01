# Dubbing, audiobooks, audio tools, media tools

Types: [`apps/studio/src/api/contracts/dub.ts`](../../apps/studio/src/api/contracts/dub.ts) (mirrored by
`server/studio/schemas_dub.py`). Server code: `server/studio/dub/`, `server/studio/audiobook/`,
`server/studio/audio_tools.py`, `server/studio/media.py`, routes in `server/studio/routes/{dub,audiobook,audio_tools}.py`.
Heavy models (Demucs, faster-whisper, pyannote, NLLB) run in the `dub` runtime (`data/envs/dub`,
`server/workers/dub_worker.py`); speech is rendered by the OmniVoice (or Chatterbox, English) worker.
Every long operation is a `Job` (kind `generate`) whose `job.update` events carry progress; jobs for a project use
`ref = "dub:<id>"` / `"audiobook:<id>"`, and the UI refetches the project when such a job ends (no polling).

## Media tools (ffmpeg / ffprobe, shared by every feature)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/media-tools` | | `MediaToolsStatus` — found via `STUDIO_FFMPEG` env, `data/tools`, then `PATH` |
| POST | `/api/media-tools/install` | | `Job` (ref `media-tools`): downloads a pinned, SHA-256-verified Windows build into `data/tools` |

Server code calls `studio.media.ffmpeg()` / `ffprobe()` / `run(cmd, ctx)` (cancellable, long filter graphs moved
to `-filter_complex_script`).

## Dubbing
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/dub/status` | | `DubStatus` (media tools, HF token present, NLLB models and whether cached) |
| GET | `/api/dub/projects` | | `DubProjectSummary[]` newest first |
| POST | `/api/dub/projects` | multipart: `file` **or** `url`, `name?`, `source_lang?`, `num_speakers?` | `DubCreateResponse` (project + preparing `Job`) |
| GET | `/api/dub/projects/{id}` | | `DubProject` |
| PATCH | `/api/dub/projects/{id}` | `DubProjectPatch` | `DubProject` |
| DELETE | `/api/dub/projects/{id}` | | `204` (`409` while a job runs) |
| POST | `/api/dub/projects/{id}/transcribe` | | `Job` — re-run recognition + diarization on the prepared audio |
| POST | `/api/dub/projects/{id}/translate` | `DubRunRequest` | `Job` |
| POST | `/api/dub/projects/{id}/generate` | `DubRunRequest` | `Job` — synthesize lines and assemble each language's track |
| POST | `/api/dub/projects/{id}/qc/{lang}` | | `Job` — re-transcribe the dubbed track, per-line WER (`DubLine.qc`) |
| POST | `/api/dub/projects/{id}/preview` | `DubPreviewRequest` | `DubPreviewResponse` — one line, synchronously |
| POST | `/api/dub/projects/{id}/export` | `DubExportRequest` | `Job`; the file is appended to `DubProject.exports` |
| DELETE | `/api/dub/projects/{id}/exports/{export_id}` | | `DubProject` |
| GET | `/api/dub/projects/{id}/waveform` | | `DubWaveform` (peaks + speech onsets; `404` until prepared) |
| GET | `/api/dub/projects/{id}/speakers/{speaker}/samples` | | `DubVoiceSample[]` — the speaker's line clips as clone samples, steadiest first; pick one with `PATCH` `speakers: [{ id, ref_segment }]` (`null` = automatic) |
| POST | `/api/dub/projects/{id}/cleanup` | | `DubProject` — re-run the segment merge/stitch passes |
| POST | `/api/dub/projects/{id}/import-subtitles` | multipart `file` (SRT/VTT), `lang?` | `DubProject` — replaces the source segments, or fills `lang` lines by overlap |
| POST | `/api/dub/parse-subtitles` | `{ text }` | `DubParsedSubtitles` (used by the paste panel) |
| GET | `/api/dub/projects/{id}/glossary` | | `DubGlossaryTerm[]` |
| POST | `/api/dub/projects/{id}/glossary` | `DubGlossaryInput` | `DubGlossaryTerm` |
| PUT | `/api/dub/projects/{id}/glossary/{term_id}` | `DubGlossaryInput` | `DubGlossaryTerm` |
| DELETE | `/api/dub/projects/{id}/glossary/{term_id}` | | `204` |
| POST | `/api/dub/projects/{id}/glossary/auto` | `{ lang }` | `DubGlossaryTerm[]` — LLM-proposed terms added as `auto` rows |

- **Preparation** (create / transcribe): `url` is fetched with yt-dlp (any site it supports, or a direct media
  link); the source is probed, re-encoded to a browser-playable proxy only when needed, split into 16 kHz mono
  (recognition) and 44.1 kHz stereo (mixing), scene cuts are detected, Demucs separates vocals / background,
  faster-whisper transcribes with word timestamps, speakers come from pyannote 3.1 (needs a Hugging Face token with
  the model terms accepted; otherwise phrase-embedding clustering or a single speaker, reported in
  `DubProject.diarization` and `warnings`), segments are cleaned up and snapped to speech onsets, and per-speaker /
  per-segment reference clips are cut and re-transcribed for cloning.
- **Translation** (`settings.translation`): `engine: "llm"` uses any chat provider id (`model`, e.g.
  `ollama:<tag>`, `openrouter:<id>`, `openai:<id>`); `"nllb"` uses an NLLB-200 checkpoint in the dub runtime.
  `quality`: `fast` (direct), `cinematic` (reflect + adapt), `autofit` (trim/expand to the slot using the measured
  speech rate), `agent` (renders, measures and rewrites until the line fits). Glossary terms, `instructions` and
  per-language `dialects` are applied to every prompt. Direct translations run concurrently (4 workers).
  `DubRunRequest`: `langs` (default: all targets), `segment_ids`, `only_failed`, `only_stale`.
- **Generation**: each speaker's `voice` is `"auto"` (clone the speaker's reference clip), `"segment"` (clone each
  line's own clip; `voice_match: "per_line"`), or a voice profile id. `timing`: `strict_slot` (render to the slot
  length), `smart_fit` (natural render, then tempo ≤ `fit.audio_rate_cap` and, if allowed, retime the video),
  `stretch_video` (keep natural speech, retime the video around it), `concise` (natural speech that may run on into
  the silence after the line). A line that still doesn't fit is cut with a fade and gets `fit.status:
  "overflow_trimmed"` (+ `overflow_s`); an empty render gets `"silent"`. Neither fails the job — its message counts them.
  Unchanged lines are reused (fingerprints); `DubTrack.stale` lists lines edited since the last render.
  `DubTrack.retime` is the export's video retime on the track timeline (`start`–`end` of the source shown `ratio`×
  slower from track time `at`; empty when not retimed) — the preview player slows the video along it.
- **Export** (`DubExportRequest.format`): `mp4` (video + one AAC track per language, ISO 639-2 language tags,
  `default_lang` marked default, optional original audio as the first track, optional burned-in subtitles), `wav` / `mp3` (one
  language), `srt` / `vtt` / `ass` (per language; `dual` = source + translation; `karaoke` ASS), `stems` (zip of
  dialogue / background / mixes), `clips` (zip of per-line audio). `preserve_bg` mixes the separated background
  (surgically spliced where speech was removed) under the dub.

## Audiobooks
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/audiobook/projects` | | `AudiobookSummary[]` |
| POST | `/api/audiobook/projects` | `{ name?, script? }` | `AudiobookProject` |
| GET | `/api/audiobook/projects/{id}` | | `AudiobookProject` |
| PATCH | `/api/audiobook/projects/{id}` | `AudiobookPatch` | `AudiobookProject` |
| DELETE | `/api/audiobook/projects/{id}` | | `204` (`409` while rendering) |
| POST | `/api/audiobook/import` | multipart `file` (`.txt`, `.md`, `.epub`, `.pdf`) | `AudiobookImportResult` (script with `#` chapters) |
| POST | `/api/audiobook/plan` | `{ script }` | `AudiobookPlan` (chapters, voices used, words, estimated length) |
| POST | `/api/audiobook/projects/{id}/render` | `{ preview_chapter? }` | `Job` — full book, or one chapter into `previews` |
| POST | `/api/audiobook/projects/{id}/cover` | multipart `file` (.jpg/.png ≤ 8 MB) | `AudiobookProject` |
| DELETE | `/api/audiobook/projects/{id}/renders/{render_id}` | | `AudiobookProject` |

Script grammar: `# Title` starts a chapter; `[voice: Name]` switches the speaker (mapped through
`settings.voice_map` to a voice profile, else `default_voice`); `[pause 1.5s]`, `[slow]…[/slow]`,
`[fast]…[/fast]`, `[emphasis]…[/emphasis]`, `[spell]…[/spell]`; blank lines are paragraph gaps. Rendered segments
and whole chapters are cached by content hash, so re-rendering after an edit only re-synthesizes what changed.
Output: `m4b` (AAC with chapter atoms, metadata tags, cover) or `mp3` (ID3 chapters); `loudness: "acx"`
(−19 LUFS, −3 dBTP) or `"podcast"` (−16 LUFS, −1.5 dBTP) uses a two-pass loudnorm.

## Audio tools
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/audio-tools/isolate` | multipart `file`, `mode` (`vocals`, `stems4`, `stems4_ft`, `stems6`) | `Job`; each stem is an audio `Output` (`params.tool = "isolate"`) |
| POST | `/api/audio-tools/convert` | multipart `file`, `voice_id`, `stt_model_id`, `tts_model_id?`, `language?`, `match_duration` | `Job`; an audio `Output` (`params.tool = "convert"`) |

Convert transcribes the recording, speaks the transcript with the chosen profile, and (with `match_duration`)
applies one pitch-preserving tempo pass toward the source length.

## Dub worker contract (`server/workers/dub_worker.py`, env `dub`)
Besides `/load`, `/unload`, `/cancel`, `GET /health`, `GET /progress` (worker_base): `/separate`, `/transcribe`,
`/transcribe_clips`, `/diarize`, `/analyze`, `/cut_refs`, `/translate_mt`, `/assemble`, `/splice_bed`. Models load
on first use and stay resident until `/unload`; the server unloads them before loading a speech model so the two
stages never hold VRAM at once.
