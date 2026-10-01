# Agent API — images, context, questions, web research

Types: [`apps/studio/src/api/types.ts`](../../apps/studio/src/api/types.ts) (`AgentMessage.images`,
`AgentSession.context`, `ContextUsage`, the `context` agent event, `agent.answer`) and
[`contracts/workspace.ts`](../../apps/studio/src/api/contracts/workspace.ts) (`sources` / `image` / `question`
tool displays), mirrored by `server/studio/schemas.py` and `schemas_workspace.py`.

## System prompt

`agent/prompt.py` builds it per turn (≈ 1K tokens in chat mode, ≈ 2.4K in agent mode): who is answering (the chat's
model by name, local or cloud) and today's date; the machine and installed models; how to respond (warm and
honest, no flattery or patronizing lines, direct answers without reflexive clarifying questions, paragraphs over
list-heavy formatting, balanced on contested politics, describe people in images without identifying them, ground
answers in provided sources, don't offer what no tool can do); the personality and default length from Settings;
the user's own "About you" and custom instructions (which override the defaults); and the memories. Agent mode adds
the studio map, tool rules (when to use the web and how to cite, image generation and editing rules), and the
workspace. It changes only when the date, settings or memories change, so provider prompt caches stay warm.

`Settings`: `assistant_personality` (`friendly` | `default` | `efficient`), `assistant_verbosity` (1–10, default
4), `about_me`, `custom_instructions`, `memory_enabled`.

### Memory

Facts about the user kept across chats (`memories` table; `GET/POST /api/agent/memories`,
`DELETE /api/agent/memories/{id}`). The agent saves one with `remember(fact)` — when asked to, or when the user
shares something durable — and deletes with `forget(id)`; every chat's prompt lists them as `[id] text`, as data.
Secrets and sensitive categories are only saved when the user explicitly asks. Off (`memory_enabled: false`): not
shown to the model and `remember` refuses.

## Writing blocks

When the user asks for a finished piece of writing (email, message, post, document), the reply carries it as
```
:::writing{variant="email" id="48213" subject="…"}
---option {subject="…"} Formal      ← optional; text before the first ---option is an option too
…
:::
```
Variants `email`, `chat_message`, `social_post`, `document` (with `title=""`), `standard`. The chat renders each as a
card (`features/chat/WritingBlock.tsx`): option tabs, Copy (plain text for mail/chat), Edit, Download, and for email
"Open in mail app" (`mailto:`). Emails/messages/posts show as plain text with their line breaks; documents as markdown;
a leading `Subject:` line in an email body becomes the subject. Blocks inside code fences are left alone; an unclosed
block (still streaming) shows as it grows. The prompt's rules decide when a block is used (explicit writing requests
or a named output; not for advice, plans, code, summaries…).

## Python, files and documents

`run_python(code, timeout_s?)` runs code in a persistent session per chat (`agent/pykernel.py` →
`workers/py_kernel.py` in the `python` env: numpy, pandas, matplotlib, scipy, sympy, openpyxl, python-docx,
python-pptx, reportlab, pypdf, pdfplumber, pillow, requests, bs4). It asks for approval (auto-approvable in Settings).
The working directory is the chat's workspace folder, else `outputs/python/<session>/`. A call returns printed
output and the last expression's value (a DataFrame also as a table: first 50 rows), saves open matplotlib figures as
PNGs, and lists files created or changed — offered as downloads (`/files/outputs/…`, or
`GET /api/workspace/sessions/{id}/fs/download?path=` for workspace files). A timeout (default 120 s, max 600) kills
the session; the next call starts fresh. `reset_python` restarts it; idle sessions close after 30 min. Display:
`python` (code, output, error, images, table, files). The env installs on first use (a job, progress on the card).

`read_skill(name)` returns a guide from `agent/skills/` — `docx`, `xlsx`, `pptx`, `pdf`, `charts` — which the prompt
asks the model to read before making that kind of file.

## Quick answers (widgets)

| Tool | Source | Display |
|---|---|---|
| `get_weather(location, days?, units?)` | Open-Meteo geocoding + forecast (no key) | `weather`: now + daily forecast |
| `calculate(expression)` | a safe AST evaluator (arithmetic, math functions, pi/e) | `calc` |
| `convert(value, from_unit, to_unit)` | built-in unit tables; currencies via Frankfurter (ECB rates, no key) | `conversion` |
| `world_time(locations[])` | IANA zones; places geocoded; `here` = this PC's zone | `clock` (ticks live) |

The cards show inline (open by default); the model still states the facts in its reply.

## Automations

`studio/automations.py`. An automation is a prompt with a schedule — an iCal VEVENT (`DTSTART` in local time,
optional `RRULE`, parsed with dateutil; at most hourly) or a relative one-off (`dtstart_offset_json`,
`relativedelta` kwargs) — and a `timing_mode`: `exact_schedule`, `flexible_schedule` (dayparts: morning 08:00,
afternoon 15:00, evening 19:00) or `condition_watch` (must repeat). Each owns a chat ("Automation · title", in the
workspace folder of the chat that created it) where every run is an agent turn with a `[Scheduled automation …]`
header. A watch answers `NO_UPDATE` when there is nothing to report: that exchange is removed and nothing is sent.
A scheduler checks every 20 s; runs missed while the server was off happen once at the next start; a finished
one-off switches itself off. A report, an error or a pending approval pushes `automation.run` (toast, and a desktop
notification when the app is hidden and allowed). Tools: `automation_create`, `automation_update` (incl. `enabled`),
`automation_list`, `automation_delete` (asks). UI: the Automations page (`/automations`).

## Connectors (MCP)

`studio/connectors.py`, with the official `mcp` SDK. The studio ships no connectors; the user adds MCP servers in
Settings → Connectors: a local program (stdio: command, args, env) or a remote Streamable HTTP URL (with headers).
Each enabled connector keeps one session open (connect → list tools → wait); changes and Test reconnect it. Its
tools reach the agent as `<name>__<tool>` (≤ 64 chars) with the server's JSON schemas, listed in the prompt under
"Connected apps"; calls ask for approval unless the connector runs without asking. Results: text parts joined
(cut at 30K chars), images saved to `outputs/connectors/` and shown to vision models, structured content as JSON.

## Pictures in chat

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/agent/images` | multipart `files` (≤ 8 PNG/JPEG/WebP/GIF/BMP, ≤ 20 MB each) | `{ urls }` — stored under `/files/outputs/chat/` |

Send them with the message: `{ type: "agent.send", session_id, content, images: urls }`. The user message keeps them
(`AgentMessage.images`) and the model gets them with the text, downscaled to 1280 px (`agent/images.py`), plus a
line naming their paths so tools can use them. Works in chat and agent mode.

Models that can see (`ChatModelOption.vision`: Ollama's `vision` capability, OpenRouter models with image
input, vision-named OpenAI-compatible models) also get the pictures tools return — browser screenshots,
`view_image`, generated and edited images. Chat APIs only take images in user messages, so they follow the tool results as a user message that starts with
`[Tool output - not from the user]` (the system prompt tells the model that such messages are tool output, not
something the user sent). Only the last 3 image-bearing messages keep their pictures. For models that can't see,
`view_image` asks the largest installed Ollama vision model for a description instead.

## Context window

Ollama chat requests use `settings.ollama_ctx_size` (default 32768), capped at the model's trained length. Before
every model step the loop (`agent/context.py`):

1. keeps only the latest pictures attached;
2. past 55 % of the window, trims old tool outputs (all but the newest 3) to a short head — once per turn, so the
   provider's prompt cache is invalidated once rather than every step;
3. past 80 %, has the chat model summarize everything except the user's current request and the latest steps;
4. if still over, shortens the newest tool outputs.

At the start of a turn, earlier turns that take more than 45 % of the window are summarized and the summary saved
on the session (`summary`, `summary_seq`); later turns start from it. Rewinding past the summarized part clears it.

After each step the server sends `{ type: "context", usage: { used, limit }, note? }` (`used` is what the provider
reported, else an estimate; `note` says what was trimmed/summarized) and stores the usage on the session
(`AgentSession.context`).

The window is the model's own limit (Ollama: `settings.ollama_ctx_size`; llama.cpp: the running server's `n_ctx` from `/props`, which `--fit` may have lowered below `settings.llamacpp_ctx_size`; LM Studio: `settings.llamacpp_ctx_size`, what it is loaded with), or the chat's `context_size` when set
(`PATCH /api/agent/sessions/{id}` with `context_size`, `0` = automatic) — a 1M-token model can run a chat at 64K to
keep it fast and cheap.

If a server still refuses a request as too large (llama.cpp's "exceeds the available context size", OpenAI's
"maximum context length", "prompt is too long", LM Studio's context overflow), the loop takes the real
window and request size from the error, summarizes, and retries the step once; a second refusal ends the turn with
a message suggesting a new chat, `/compact` or a larger context.

### Slash commands

Typed in the composer (a menu opens on `/`); handled by the client, not sent to the model:

| Command | Does |
|---|---|
| `/compact [focus]` | `POST /api/agent/sessions/{id}/compact` — summarizes the chat now (optionally focusing on something); the next turn starts from the summary and the gauge shows the smaller context. One at a time per chat (`409` for a second); the summary is capped at ~3K tokens. The composer shows a status and holds messages until it's done |
| `/context [size\|auto]` | sets the chat's context window (`32k`, `128k`, `1m`, …) |
| `/new` | starts a new chat |
| `/model [name]` | switches the chat's model |
| `/mode chat\|agent` | switches mode |
| `/help` | lists the commands |

### Prompt caching

OpenRouter requests to `anthropic/*` and `google/gemini*` models get `cache_control` breakpoints (the system prompt
and the newest message); OpenAI, DeepSeek, Grok and others behind OpenRouter cache repeated prefixes automatically.
Cached input tokens are read from `usage.prompt_tokens_details.cached_tokens` and logged. Context trimming happens
at most once per turn so it doesn't break the cache every step.

## Generation speed

Assistant messages carry `output_tokens` (tokens the model generated for the reply: text, reasoning and tool calls,
over all its steps) and `generation_s` (seconds spent generating them, prompt reading excluded); the chat shows
`output_tokens / generation_s` as tok/s under each reply and the chat's average under the composer. After each model
step the server sends `{ type: "speed", output_tokens, generation_s }` with the reply's totals so far. Sources:
llama.cpp's own `timings` (decode count and time), Ollama's `eval_count` / `eval_duration`, the `usage` token counts
of OpenAI-compatible APIs (requested with `stream_options.include_usage`) and
OpenRouter's billed completion tokens; when a provider doesn't time itself, the loop times the step from its first
streamed token. A step without both numbers isn't counted.

## Questions to the user

`ask_user(question, options?)` puts the call in status `awaiting_input` with a `question` display. The user answers
with `{ type: "agent.answer", session_id, call_id, answer }`; the call continues with the answer as its result. Not
available in background tasks (the tool tells the model to decide itself). Stopping the turn cancels the question.

## Completion check

When a tool-using turn stops, the loop sends the model a checklist and it answers with a `[[DONE: yes|no]]` verdict
(see `agent/loop.py`). That answer is streamed as a thinking block, not as reply text; if it is the only thing the
model wrote, it becomes the reply.

## Tools added in 2.0

| Tool | What it does |
|---|---|
| `view_image(source, question?)` | Look at an image (workspace path, `/files/...` URL or web URL) |
| `edit_image(images[], prompt, strength?, seed?)` | Edit with the best local model supporting `edit` (references), or `img2img` when `strength` is set |
| `transcribe(source, language?)` | Whisper transcript with timestamps (long ones saved to the workspace) |
| `list_voices(query?)` / `clone_voice(source, name, language?)` | Voices for `text_to_speech`; cloning stages and saves a profile |
| `separate_audio(source, mode?)` | Demucs vocals/instrumental or stems |
| `start_dub(source, name?, speakers?)` | New Dub project from a file or video URL |
| `list_outputs(kind?, query?, limit?)` | Search past generations by prompt |
| `ask_user(question, options?)` | See above |
| `web_search(query, count?)` | Results with snippets (`sources` display) |
| `fetch_url(url, question?, offset?)` | Readable page/PDF text (trafilatura; the agent's browser renders JavaScript-only pages); with `question`, only the BM25-ranked passages that answer it |
| `research(question, queries[])` | 1-4 searches, top 8 pages read in parallel, 10 best passages numbered `[n]` by source for citation |

Search is DuckDuckGo only (other engines serve captchas or junk results to programs). Requests are serialized one
second apart; while DuckDuckGo rate-limits (HTTP 202) a search waits 15, 30, 60 and 120 s, alternating between its
html and lite endpoints, and shows the wait on the call's card; after that it fails with a hint to search in the
browser, where the user can take over. Search results are cached for an hour in memory, fetched pages under
`<data_dir>/cache/web`. `research` drops duplicate queries, and passages must contain at least 30 % of the question's
distinct terms to be used.

Browser: `browser_read` `snapshot` returns the page's accessibility tree with `[ref=eN]` ids on interactive elements
(anonymous wrappers dropped, ≤ 16 000 chars); `browser_click` / `browser_type` accept `ref`.
