# OpenRouter platform API

One OpenRouter key (and one credit balance) gives the studio any OpenRouter model: chat/agent, image, speech,
transcription. Types: [`apps/studio/src/api/contracts/openrouter.ts`](../../apps/studio/src/api/contracts/openrouter.ts)
(mirrored by `server/studio/schemas_openrouter.py`). Keys live in `Settings.openrouter_api_key` /
`openrouter_management_key` (write-only, masked like every secret).

## Routes
| Method | Path | Returns |
|---|---|---|
| GET | `/api/openrouter/models?output=&q=&tools=&free=&pinned=&max_input_price=&min_context=&sort=&limit=&offset=&refresh=` | `CloudCatalogPage` |
| PUT | `/api/openrouter/pins/{model_id}` | `CloudModel` — pin (model ids contain `/`, e.g. `/pins/openai/gpt-4o-mini`) |
| DELETE | `/api/openrouter/pins/{model_id}` | `204` — unpin |
| GET | `/api/openrouter/account?refresh=` | `OpenRouterAccount` |

- **Catalog** — `GET https://openrouter.ai/api/v1/models?output_modalities=all` (public, no key) normalized and
  cached server-side for 30 min (`refresh=true` refetches). Per-image prices come from the Images API
  (`/images/models/{id}/endpoints`) and fill in shortly after the first load. `output` filters by output modality;
  `max_input_price` is USD per 1M input tokens; `sort`: `newest | price | context | name`; default `limit` 60.
- **Pins** — pinning is how cloud models join the studio. Chat models (`use: "chat"`) appear in
  `GET /api/chat/models` as `openrouter:<slug>` with `price` + `context_length`. Image / speech / transcription models
  become `InstalledModel`s `{ id: "openrouter:<slug>", runtime: "openrouter", size_bytes: 0 }` (pushed as
  `model.update`), so the Image and Voice areas list them. `DELETE /api/models/openrouter:<slug>` unpins too.
  Video / embeddings models are browse-only (400 on pin).
- **Speech / transcription** of pinned models go through the normal routes: `POST /api/voice/tts`
  (`voice_id` = `openrouter:<slug>:<voice>` from the model's `supported_voices`, or `openrouter:<slug>:default`)
  returns a `Job` whose output is an mp3; `POST /api/voice/transcribe` with `model_id=openrouter:<slug>` returns a
  `TranscribeResult` (segments when the model supports `verbose_json`, else one segment with the full text).
- **Account** — `GET /key` with the inference key (usage today/week/month, key limit) plus `GET /credits` with the
  management key (`balance = total_credits − total_usage`); cached for a minute. `studio_today` and `recent` come from
  the studio's own ledger.

## Realtime
- Agent event `{ type: "usage", cost, total }` after every billed model step of an OpenRouter chat turn; `total` is
  the reply's cost so far and is also `AgentMessage.cost` (persisted messages carry it on
  `GET /api/agent/sessions/{id}`).
- Server event `{ type: "openrouter.account", account }` ~2 s after any billed request (chat step, chat title,
  image, speech, transcription). The UI writes it into the `['openrouter', 'account']` query — no polling.

## Errors
OpenRouter failures surface with clear messages, e.g. `OpenRouter: out of credits — add credits at …` (402),
`OpenRouter: the API key was rejected …` (401), key-limit and in-flight-budget variants of 402, rate limits (429,
with `Retry-After`), `no provider could serve this request` (502/503). Mid-stream `error` chunks raise the same way.

## Server client — `server/studio/openrouter.py`
Pure HTTP (no DB/jobs), safe to import anywhere. Blocking media calls are meant for job threads.

```python
from studio import openrouter, openrouter_usage

result = openrouter.generate_image("bytedance-seed/seedream-4.5", prompt, aspect_ratio="16:9", n=2)
openrouter_usage.record("image", "bytedance-seed/seedream-4.5", result.usage, ref=job_id)  # cost → ledger + push

speech = openrouter.speech(model, text, voice="Kore")            # raw audio bytes, cost looked up afterwards:
openrouter_usage.record_when_billed("speech", model, speech.usage, ref=job_id)
t = openrouter.transcribe(model, audio_bytes, "wav", language="en")  # Transcript(text, language, segments, usage)
```

Also: `list_models()`, `list_image_models()`, `image_model_endpoints()`, `key_info()`, `credits()`, `generation()`,
`stream_chat()` / `chat()`, `inference_key()`. All raise `OpenRouterError` (`.status`, `.error_type`,
`.retry_after`). Set `STUDIO_OPENROUTER_URL` to point the client at another base URL (used for fixture testing).
