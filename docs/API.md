# Studio API

Server: FastAPI on `http://127.0.0.1:8765`. All routes under `/api`. Types are defined in
[`apps/studio/src/api/types.ts`](../apps/studio/src/api/types.ts) — that file is the contract.
Generated files are served statically under `/files/...` (mapped to `<data_dir>/...`).

Errors: non-2xx with JSON `{ "detail": string }`.

## Realtime — WebSocket `/api/ws`
The single realtime channel; the UI never polls. Each frame is one JSON object.

- **Server → client**: `ServerEvent`. The first frame after connecting is always
  `{ type: "hello", version, snapshot }` with the full `Snapshot` (system, jobs, models, runtimes, active agent
  turns), so a reconnecting client is fully resynced. `system` frames are pushed every ~2s while at least one
  client is connected. Every agent turn's events are broadcast to all clients as
  `{ type: "agent", session_id, event: AgentEvent }`.
- **Client → server**: `ClientMessage` — `agent.send`, `agent.approve`, `agent.answer`, `agent.stop`. Problems (unknown session,
  a turn already running, no call awaiting approval…) come back as `{ type: "error", message, ref }`.
- Agent turns run on the server independently of any socket: closing or reloading the tab does not stop a turn.
  A call awaiting approval waits until some client answers or the turn is stopped.
- Keepalive: WebSocket protocol ping/pong (uvicorn defaults); no application-level heartbeat.

## System
| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{ ok: true, version }` — for scripts/launchers; the UI uses the socket |
| GET | `/api/system` | `SystemInfo` |
| GET | `/api/capabilities` | `Capabilities` — what this machine can do: platform, GPU kind and, per feature (`image`, `voice`, `music`, `video`, `dub`, `game`, `llamacpp`), whether it is available locally or through a configured cloud provider, with the reason when it is not. Navigation, area sections and the agent's tool list follow it; it changes when a cloud key is saved. |
| GET | `/api/settings` | `Settings` (secrets masked as `"•••"` when set, omitted otherwise) |
| PUT | `/api/settings` | `Settings` — partial update; sending `""` for a secret clears it |
| GET | `/api/settings/secrets/{name}` | `SecretValue` (`value`): a stored key or token in the clear, for the Settings page's 'show' button (to copy it to another copy of the studio). `404` when the name is not a secret or nothing is stored |
| GET | `/api/storage` | `StorageInfo` — the models folder, its size and the free space on its drive |
| POST | `/api/storage/models-dir` | `MoveModelsRequest` → `Job` (kind=`storage`): unloads local models, moves the models folder into an empty/new folder (rename on the same drive, copy + delete across drives), rewrites installed models' paths and saves the new folder. Ollama and LM Studio keep their own stores. With `adopt: true` nothing is moved: the folder (which may already hold models) becomes the models folder and is rescanned; models installed elsewhere stay installed |

A generation feature is local when the machine has an NVIDIA GPU (the model runtimes are CUDA builds). Without one,
chat, the agent workspace, automations, connectors and memory work unchanged; `image` and `voice` remain available
through cloud models when an OpenRouter key is set. `STUDIO_NO_GPU=1` makes the server behave as a machine without
a GPU. Desktop packaging and the server's environment variables: [`DESKTOP.md`](DESKTOP.md).

`Settings.agent_completion_check` (`local` | `always` | `never`) controls the agent's completion check, see
[`api/agent.md`](api/agent.md).

`Settings.default_models` maps a task (`image`, `image_edit`, `voice`, `stt`, `music`) to the model the automatic
picks use — the agent's tools, game media and each page's first choice. A missing task means the best local model;
a named model that is uninstalled, unpinned or whose cloud key was removed falls back to it too. Cloud models are
only ever used when named here or picked on a page (they bill per use).

## Catalog & models
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/catalog` | | `CatalogEntry[]` (with live `fit` and `installed`) |
| GET | `/api/models` | | `InstalledModel[]` |
| POST | `/api/models/{catalog_id}/install` | | `Job` (kind=download; also ensures runtime env) |
| DELETE | `/api/models/{id}` | | `204` — unloads, deletes files (`ollama rm` for Ollama models; only the model's own files in LM Studio's library) |
| POST | `/api/models/rescan` | | `RescanResult` (`added`, `removed`, `unrecognized`): brings the list in line with the models folder. Folders that hold a model and aren't listed are registered, from their `studio-model.json` (written into every model's folder when it is installed) or, without one, from what they contain; models of that folder whose own folder is gone are forgotten. Unfinished downloads are left alone. `409` when the folder can't be read |
| PATCH | `/api/models/{id}` | `ModelPatch` (`text_encoder`: `full` \| `8bit` \| `4bit`) | `InstalledModel` — how a local image pipeline holds its text encoder (see [`docs/api/image.md`](api/image.md)); unloads it if loaded. `400` for a model without a large text encoder |
| POST | `/api/models/{id}/load` | | `InstalledModel` |
| POST | `/api/models/{id}/unload` | | `InstalledModel` |

Searching Hugging Face / Ollama / LM Studio, installing any variant (GGUF quants, fp16, single files…) and the
LM Studio / llama.cpp runtimes: [`docs/api/hub.md`](api/hub.md).

## Jobs
| Method | Path | Returns |
|---|---|---|
| GET | `/api/jobs` | `Job[]` (most recent first, last 100) |
| POST | `/api/jobs/{id}/cancel` | `Job` |
| DELETE | `/api/jobs/{id}` | `204` — dismiss a finished job |

## Runtimes
| Method | Path | Returns |
|---|---|---|
| GET | `/api/runtimes` | `RuntimeInfo[]` |
| POST | `/api/runtimes/{id}/install` | `Job` (kind=env) — `python` is the agent's Python tools env (no models; installs on first `run_python` too) |
| POST | `/api/runtimes/{id}/stop` | `RuntimeInfo` — kills worker, frees VRAM |

## Generation (all return a `Job` of kind=generate; outputs arrive in `job.result.outputs`)
| Method | Path | Body |
|---|---|---|
| POST | `/api/image/generate` | `ImageGenerateRequest` (`ImageRequest` + edit inputs) — image area routes: [`api/image.md`](api/image.md) |
| POST | `/api/voice/tts` | `TTSRequest` |
| POST | `/api/music/generate` | `MusicRequest` |
| POST | `/api/voice/transcribe` | multipart: `file`, `model_id` → returns `TranscribeResult` directly (not a job) |

## Outputs
| Method | Path | Returns |
|---|---|---|
| GET | `/api/outputs?kind=image\|audio\|music\|video&limit=100` | `Output[]` newest first |
| DELETE | `/api/outputs/{id}` | `204` |

## Voices
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/voices` | | `Voice[]` (presets of installed voice models + user voices) |
| POST | `/api/voices/clone` | multipart: `name`, `file` (audio ≥3s), `tags` (comma list) | `Voice` |
| DELETE | `/api/voices/{id}` | | `204` |

## Video
Text-to-video and image-to-video (LTX-2.5 with audio, Wan 2.2): `/api/video/models`, `/api/video/generate` —
[`docs/api/video.md`](api/video.md).

## Automations — [`contracts/automations.ts`](../apps/studio/src/api/contracts/automations.ts)
Prompts the agent runs on a schedule, or when a trigger's check finds something new; each posts its runs in a chat (the one it was created in, or its own). Details: [`docs/api/agent.md`](api/agent.md#automations).
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/automations` | | `Automation[]` newest first |
| POST | `/api/automations` | `AutomationCreate` (`title`, `prompt`, `timing_mode`, `schedule` VEVENT or `dtstart_offset_json`, `model?`; for `timing_mode: "trigger"`: `check` and `check_minutes?` instead of a schedule) | `Automation`; `400` for an invalid schedule (more often than hourly, a non-repeating watch, nothing in the future) or a trigger whose check fails |
| PATCH | `/api/automations/{id}` | `AutomationUpdate` (any field, `enabled`) | `Automation` |
| DELETE | `/api/automations/{id}` | | `204` (its chat stays) |
| POST | `/api/automations/{id}/run` | | `Automation` — runs now (a trigger: its check runs now); `409` while it's already running |

Push: `automation.update`, `automation.removed`, `automation.run` (`status`: `reported` \| `needs_approval` \| `error`; quiet runs send nothing).

## Connectors — [`contracts/connectors.ts`](../apps/studio/src/api/contracts/connectors.ts)
MCP servers whose tools the agent can use. Env var and header values come back as `•••`; sending `•••` keeps them.
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/connectors` | | `Connector[]` with live `status`, `error` and `tools` |
| POST | `/api/connectors` | `ConnectorCreate` (`name`, `transport` stdio \| http, `command`/`args`/`env` or `url`/`headers`, `approval` ask \| auto) | `Connector` (connects in the background) |
| PATCH | `/api/connectors/{id}` | `ConnectorUpdate` | `Connector` (reconnects) |
| DELETE | `/api/connectors/{id}` | | `204` |
| POST | `/api/connectors/{id}/test` | | `Connector` after reconnecting (waits up to ~50 s) |

Push: `connector.update`, `connector.removed`.

## Game
A text RPG with a chat model as game master and the game state kept by the server: `/api/games…` routes and the
`game.delta` / `game.turn` / `game.error` server events are documented in [`docs/api/game.md`](api/game.md).

## Chat / Agent
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/chat/models` | | `ChatModelOption[]` |
| POST | `/api/agent/images` | multipart `files` | `{ urls }` — pictures to attach to a message (`agent.send.images`) |
| GET | `/api/agent/sessions` | | `AgentSession[]` (no messages) |
| POST | `/api/agent/sessions` | `{ model, mode }` | `AgentSession` |
| GET | `/api/agent/sessions/{id}` | | `AgentSession` with messages |
| PATCH | `/api/agent/sessions/{id}` | `PatchSessionRequest` (`title?`, `model?`, `mode?`, `context_size?` — the chat's own context window in tokens, `0` = automatic; `/context`) | `AgentSession` |
| DELETE | `/api/agent/sessions/{id}` | | `204` — also stops a running turn |
| POST | `/api/agent/sessions/{id}/rewind` | `MessageRef` (a user message) | `RewindResult` — drops that message and all later ones, restores files the agent's file tools changed since; lists commands whose effects stay |
| POST | `/api/agent/sessions/{id}/fork` | `MessageRef` | `AgentSession` — new chat with the messages up to and including that one, same workspace folder |
| GET | `/api/agent/memories` | | `Memory[]` — what the assistant remembers about the user across chats (Settings → Assistant), oldest first |
| POST | `/api/agent/memories` | `MemoryCreate` (`text`, ≤ 500 chars) | `Memory` — an identical memory is returned instead of duplicated; `400` when 200 are stored |
| DELETE | `/api/agent/memories/{id}` | | `204` |
| POST | `/api/agent/sessions/{id}/compact` | `CompactRequest` (`focus?`) | `CompactResult` — `/compact`: the chat so far is summarized; the model's next turn starts from the summary (messages stay visible). `409` while a reply runs |

Sending messages, approvals, answers and stopping go over the WebSocket (`agent.send` / `agent.approve` /
`agent.answer` / `agent.stop`). Pictures in chat, vision, the context window (the `context` event), `ask_user` and
the web research tools: [`docs/api/agent.md`](api/agent.md).
OpenRouter models (`openrouter:<slug>`), their `usage` agent event, per-message `cost` and the `openrouter.account`
server event are documented in [`docs/api/openrouter.md`](api/openrouter.md).

### Agent tools
The agent works like a coding agent over the studio itself. Tools marked ⚠ require user approval
unless listed in `settings.agent_auto_approve`.

- `system_info()` — GPU/RAM/disk
- `list_models(kind?)` — installed models
- `search_catalog(query?, kind?)` — catalog entries incl. fit
- ⚠ `install_model(catalog_id)` — starts download job, returns job id
- ⚠ `delete_model(model_id)`
- `load_model(model_id)` / `unload_model(model_id)`
- `generate_image(prompt, model_id?, width?, height?, steps?, seed?)` → artifacts
- `text_to_speech(text, voice_id?, model_id?)` → artifacts
- `generate_music(tags, lyrics?, duration_s?, model_id?)` → artifacts
- Images, audio, voices, dubbing, the gallery, `ask_user` and reading the web (`fetch_url`):
  [`docs/api/agent.md`](api/agent.md)
- `list_dir(path)` / `read_file(path)` — sandboxed to `<data_dir>/workspace`
- ⚠ `write_file(path, content)` — sandboxed to workspace
- ⚠ `run_command(command, cwd?)` — PowerShell on Windows, cwd defaults to workspace, 120s timeout
