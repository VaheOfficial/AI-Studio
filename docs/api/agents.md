# Agents

Agents consolidates conversations, persistent sequential missions and optional bounded subagents at `/agents`. Old `/chat`, `/agent-plus` and `/swarm` UI addresses redirect into this section. Existing conversations and mission records remain in the database. Saved teams can be inspected and imported; their autonomous team scheduler is retired.

Contracts are in `apps/studio/src/api/contracts/agents.ts`, re-exported by `api/types.ts`, and mirrored in `server/studio/schemas_agents.py`. Mission contracts remain in `contracts/agentPlus.ts` and `schemas_agent_plus.py`. Existing conversation endpoints and `/api/ws` remain the transport for chat, approvals, questions and streaming.

## Routes

All paths below start with `/api/agents`.

| Method | Path | Body or query | Result |
| --- | --- | --- | --- |
| GET | `/` | | `AgentsOverview`: identities, owner conversations, missions, delegations, wakes and saved teams |
| GET / POST | `/identities` | POST `IdentityPatch` | Identity list / new identity |
| PATCH | `/identities/{id}` | `IdentityPatch` | Updated identity |
| PUT | `/sessions/{sid}/identity` | `{agent_id}` | 204; conversation must be idle |
| GET | `/capabilities` | `query?`, `sid?`, `schemas?`, `mode?: bm25 | regex` | Compact searchable catalog; a supplied conversation applies its tool scope |
| POST / GET | `/sessions/{sid}/delegations` | POST `DelegateCreate` | Scoped child task / child task list |
| POST | `/sessions/{sid}/delegations/{id}/cancel` | | Stop an owned subagent |
| GET / POST | `/knowledge` | GET `scope?`, `scope_id?`; POST `KnowledgeCreate` | Scoped facts / saved fact |
| PATCH | `/knowledge/{id}` | `KnowledgeUpdate`, including current `updated_at` | Edited fact; 409 for stale edits |
| DELETE | `/knowledge/{id}` | | Forget fact |
| GET / POST | `/skills` | POST `SkillCreate` | Skill versions / new version |
| PATCH | `/skills/{id}` | `{enabled}` | Enable or disable a version; dependencies are checked |
| GET | `/artifacts` | `sid?` | Current artifacts |
| GET | `/artifacts/{id}` | `version?` | Current or historical artifact |
| GET | `/artifacts/{id}/history` | | Revision metadata and hashes |
| GET | `/artifacts/{id}/export` | `version?` | Attachment download |
| POST | `/sessions/{sid}/artifacts` | `ArtifactCreate` | New artifact or revision; updates require `id` and current `version` |
| GET | `/connections` | | OAuth status, OS vault availability and installed plugin ownership |
| GET | `/connections/{id}/resources` | | MCP resource and template metadata |
| GET | `/connections/{id}/resource` | `uri` | MCP resource contents, capped at 1 MiB |
| POST | `/connections/{id}/call` | `ApplicationCall` | User-approved MCP app action; owner conversation must be idle |
| POST | `/oauth/start` | `OAuthConfig` | Authorization URL and loopback callback address |
| GET | `/oauth/callback` | `state`, `code` | One-use PKCE completion page |
| DELETE | `/oauth/{id}` | | Disconnect authorization |
| POST | `/plugins/inspect` | Multipart `file` | `PluginReview` with instructions, connections, retained text sources and warnings |
| POST | `/plugins/install` | Multipart `file` | Installed plugin and owned skill/connector IDs |
| DELETE | `/plugins/{id}` | | Remove owned records and retained plugin sources |
| GET / POST | `/devices` | POST `DeviceCreate` | Device metadata / one-time `DeviceGrant` token |
| DELETE | `/devices/{id}` | | Revoke grant |
| GET | `/host` | | Host identity, service state and device gateway state |
| POST / DELETE | `/host/register` | | Register/remove next-sign-in host startup |
| POST / DELETE | `/host/gateway` | | Start/stop the separate device listener; choice persists |
| GET | `/documents` | | Advertised live editor sessions and implemented commands |
| POST | `/sessions/{sid}/wakes` | `WakeCreate` | One scheduled or event-triggered continuation |
| PATCH | `/wakes/{id}` | `{status: scheduled \| cancelled}` | Reschedule a reviewed wake or cancel it |
| POST | `/events/{topic}` | `AgentEventDelivery` | Idempotent local event delivery; number of activated wakes |
| POST | `/sessions/{sid}/recording/start` | | Start user browser demonstration |
| POST | `/sessions/{sid}/recording/finish` | `{name}` | Disabled skill draft |
| DELETE | `/sessions/{sid}/recording` | | Discard demonstration |
| GET | `/legacy/{id}` | | Historical team detail |
| POST | `/legacy/{id}/import` | `{model, max_requests?}` | Ready sequential mission with retained acceptance requirements and source context; repeat imports reuse the conversation |

Mission endpoints are `/missions`, `/missions/{sid}`, `/missions/{sid}/resume`, `/pause`, `/cancel` and PATCH `/missions/{sid}`. Their bodies and persistence rules are described in [Mission API](agent-plus.md). `/api/agent-plus` remains a compatibility alias. Creating a mission does not start inference. The `start_mission` tool can promote an existing owner conversation while retaining its chat, with 80 requests and zero authorized remote spending.

## Action contracts and incoming work

`review_code` reads up to eight explicitly selected UTF-8 workspace files, bounded to 24 KB total, without executing them. Python syntax is parsed locally. The current local model produces advisory findings through `structured_output`; every reported location and evidence substring is checked against the exact supplied source line. Source hashes support later readback. This is a bounded code review, not a dependency scanner or a guarantee of security. Git read operations disable filesystem-monitor hooks, external diff helpers and text-conversion commands.

Protocol evidence expires after seven days. Local model checks are keyed by installation metadata and path size/modification time so replacement or removal invalidates the corresponding check. Endpoint checks remain evidence about a specific configured endpoint and model identifier, not a guarantee about future server changes.

`setup_document_ocr` installs checksum-pinned English language data from the official Tesseract 4.1.0 fast-data release in the CPU document runtime. `office_file` OCR uses PyMuPDF's integrated Tesseract engine when the language data is present, with a CLI fallback for an existing local Tesseract installation. It downloads no source documents and performs recognition locally. Other languages require their locally installed data. The [PyMuPDF installation reference](https://pymupdf.readthedocs.io/en/latest/installation.html#enabling-integrated-ocr-support) describes the integrated engine and language-data requirement.

`GET /api/agents/capabilities?purpose=monitor&sid=...` filters discovery to supported read-only monitor sources. The UI uses that filtered catalog and retains backend validation when creating a watch.

`structured_output` requests JSON Schema decoding through the current local Ollama or OpenAI-compatible model, then validates the decoded value independently. Schemas and prompts are bounded to 32 KB, output to 256 KB and inference to 180 seconds. External schema references and regex constraints are refused. A valid shape does not establish factual correctness; unsupported endpoint schema formats return an error rather than silently falling back to unconstrained text. These native controls follow the [Ollama schema interface](https://docs.ollama.com/capabilities/structured-outputs) and [llama.cpp server interface](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

Continuous local voice has an opt-in recognized-speech interruption control. With it enabled, browser echo cancellation remains active while Whisper listens during playback, and recognized speech cancels current synthesis/playback. Headphones improve isolation. This is transcription-triggered interruption, not a native audio-token realtime model; microphone/echo behavior still requires live hardware acceptance.

Outbound channel replies reserve a persistent receipt before invoking the configured sending operation. Repeating the same text for the same observed message returns its successful receipt, or refuses to retry an uncertain attempt. Delivery confirmation remains the sending operation’s evidence, and altered reply text is a distinct action under ordinary approval.

GET/PUT `/sessions/{sid}/policy` reads or replaces a versioned action contract while the owner is idle. Matching rules constrain JSON Pointer argument paths with `eq`, `in`, numeric bounds, prefix or HTTPS host checks, optional expiry and call limits. All matching rules must pass. Children inherit the owner contract. Denied calls never reach dispatch; accepted attempts receive durable quota receipts before execution. Lost or failed outcomes retain their consumed quota. Enabled contracts can deny unlisted effects and opaque execution, including raw code and pointer actions. Tool-name constraints cannot infer the semantic effects of arbitrary code or opaque browser actions. Contracts supplement normal approvals and are never generated or relaxed by model tools.

POST `/model-checks` with `{model}` runs two bounded requests to a configured local or compatible endpoint. The first must produce the requested structured call; the second must consume a newly generated result. GET `/model-checks/{model}` returns evidence or unknown. OpenRouter models are excluded from this check. Basic protocol success does not establish complex task competence. Unchecked compatible endpoints are not advertised as tool-capable.

GET/POST `/channels` lists masked configuration or creates a communication channel. PATCH `/channels/{id}` enables/disables it; DELETE removes it. POST `/channels/{id}/receive` accepts signed Slack Events requests, Telegram secret-token deliveries or timestamped HMAC webhook envelopes. Webhook envelopes contain `message_id`, `sender`, `conversation`, and `text`; signatures use `v1:` + Unix timestamp + `:` + raw body and header `X-Studio-Signature: v1=<SHA256 HMAC>`, with `X-Studio-Timestamp`. Slack uses its documented v0 signature and five-minute window. Exact sender/conversation grants are required. Bot echoes, unsupported events and duplicate message IDs do not start new work. Received messages create scoped continuations and remain external source material. `channel_messages` reads them; approved `channel_reply` derives the recipient from the stored grant and invokes the configured outgoing operation through the ordinary dispatcher. Studio does not provision provider apps, subscriptions or a public HTTPS endpoint automatically. Teams/WhatsApp/SMS can use an authenticated relay through the generic webhook; that is not a native adapter for those providers.

GET/POST `/monitors` lists or creates approved source monitors; PATCH `/monitors/{id}` enables/disables and DELETE removes them. Monitors accept selected local read tools and enabled read-only GET/HEAD HTTP operations. Optional `select` extracts a JSON Pointer observation before hashing. The first read establishes a baseline unless `notify_initial` is enabled. Changes create event continuations; unchanged observations stay quiet. Failures preserve the previous baseline and back off. Owner Stop disables that conversation's monitors and channels. Re-enable only after reviewing the work. Monitors require a running host; account permissions and current source access remain necessary.

POST `/sessions/{sid}/delegations/{id}/followup` continues an idle owned child with the same conversation and tool scope. `{message, additional_requests?}` extends its request allowance, capped at 100 total. `DelegateCreate.model` optionally selects a configured provider before a child is queued. The parent retains ownership and mission spending limits.

`google_workspace_file` prepares MIME mail drafts/sends with workspace attachments, downloads Gmail attachments and transfers Drive content through an authorized matching service. Multipart Drive uploads are capped at 5 MiB; mail attachments and downloaded files at 20 MiB. Native Google documents use `export_drive` with a target MIME type. Account responses and file IDs must be read back through the corresponding service. Calendar deletion, free/busy, Gmail profile/history/labels/draft updates and Drive permissions are available in the reviewed starter profiles. API availability does not establish a real account's authorization.

`git_workspace` provides status/diff/history, exact-path staging, commit and conversation-owned worktrees. The chosen workspace must be the repository root. Worktrees live in managed data storage outside the checkout; removal verifies ownership and refuses dirty checkouts. It never pushes or merges. Enabled contracts that block opaque execution also block Git mutations, since repository hooks and filters can execute code.

Additional `office_file` actions are `fill_pdf` (text/choice AcroForm fields with readback; XFA, signatures and button fields are rejected), `ocr_pdf` (up to 20 pages using installed local Tesseract), `recalculate_sheet` and `export_office_pdf` (installed local LibreOffice with a separate profile and high macro security). Unchanged Word character runs are preserved; replacements inherit the first matched run. Unsupported inline structures fail explicitly rather than flattening formatting. Render PDF exports and inspect them before claiming visual quality. These CPU tools remain configuration-dependent.

Native desktop actions are serialized across conversations. Windows retains physical virtual-desktop coordinates. The optional PyAutoGUI backend supports macOS and Linux X11 on the primary display, reports Retina coordinate scale, requires local OS access grants, and rejects unreliable Unicode typing. Wayland remains unavailable without a portal backend. Use structured application tools or browser form input for Unicode on portable backends. No cross-platform acceptance result is implied by the presence of this code.

`knowledge_search` accepts `mode: semantic` and an explicit local Ollama `embedding_model`. Vectors are scoped, tied to source hashes, invalidated on edits and removed on explicit deletion. One query handles at most 500 facts and bounded embedding input. Lexical search remains the default. A source watch may explicitly retain its latest timestamped observation as chat memory; it never infers a user preference from that observation. Replacing that projection removes the prior observation's vectors. Provider-native assistant continuation state up to 256,000 characters is retained in the internal step transcript and replayed only to the exact same model; public tool results do not expose that state.

Enabled HTTP operations marked read-only do not require a mutation approval. Mutations retain ordinary approval. Read-only operations are constrained to GET/HEAD at installation; enabling a service grants its reviewed read operations, subject to conversation scope and action contracts.

Browser demonstrations capture unique IDs, test IDs, labels or named fields where available and record parameter names for text inputs. `replay_demonstration` requires an enabled reviewed skill, explicit new input values and an active dispatcher. It rejects coordinate-only, unsupported or secure-input steps before acting. Each step verifies the current origin/path against the reviewed recording and retains normal approvals and takeover. After replay, read back and verify the actual outcome. A successful replay is not a general guarantee about a changing website or inferred decision rules.

Artifact creation omits both ID and version; revision requires the real observed pair. Artifact existence, ownership, revision and JSON checks run before an action quota is consumed. Exhausted/expired authorization stops the turn. Three identical tool failures also stop the turn with an explicit incomplete-work message instead of spending the remaining reasoning requests on the same failure.

## Tool discovery, composition and subagents

The ordinary agent sees a compact initial tool set and persisted loaded schemas. `search_tools` ranks descriptions with BM25 or a bounded regex search; `load_tools` loads at most 30 schemas per call and retains the 30 most recently loaded schemas alongside the initial set. Scope and approval checks still occur at execution. Mission controls become available when a conversation enters the mission engine. Connected MCP and live editor tools appear dynamically.

`execute_tools` runs up to 20 ordered calls. Arguments can bind earlier results using `{"$result":"step-id#/json/pointer"}`. A failed call stops the composition. `return_fields` limits the result sent back to the model. `run_tool_script` supplies Python with `tools.NAME(**args)`, `inputs` and a final `result`. Nested calls go through the ordinary dispatcher, approvals and action receipts; intermediate results remain in the UI and persisted tool history. Scripts are limited to 20 dispatched calls, 64,000 code characters and a 5–600 second deadline. Arbitrary Python in process mode has the local user's OS authority.

`delegate_task` creates an explicit child conversation with an objective, tool allowlist and request limit. Defaults are read-oriented tools. Subagents cannot create more subagents, owner missions, wakes, advisor consultations, automation tools or orchestration scripts. Explicit effect-capable scopes use ordinary approval policy. A mission's child requests share its request and remote spending accounting. The parent's identity limits active subagents. Parent Stop suspends future wakes and stops active children. Child results are observations to inspect, rather than automatic acceptance of the owner's mission.

The missing-capability path retains `research_tool`, immutable Python revisions, frozen acceptance cases, distinct additional checks and bounded repair. Validated chat tools can be promoted explicitly into reusable skills. Promotion stores the source conversation and code hash; execution checks the source's validation state and exact hash again. Executable skills must declare `run_python`. Dependency cycles and disabled dependencies are rejected. Declared permissions describe a skill's contract; they do not grant OS isolation to process-mode Python.

## Memory, retrieval and artifacts

Knowledge carries source text, an agent/chat/workspace scope, timestamps and optional timezone-aware expiry. Default relevance retrieval uses lexical overlap; explicit semantic search uses a configured local embedding model with scope-filtered cached vectors. Initial prompt insertion is capped separately from explicit `knowledge_search` results. The Memory screen supports editing and deletion.

`index_documents` indexes workspace text, code, CSV, JSON, PDF text layers and DOCX text. SQLite FTS5 retrieves passages with source hashes and page/line locations. A document is capped at 32 MiB. An indexing request supports at most 5,000 passages and 16 MiB of embedding vectors. Optional `embedding_model` uses an already installed local Ollama model through `/api/embed` with truncation disabled. Semantic search requires the named collection and its original model; changing models or adding embeddings requires rebuilding the collection. Embedding failures leave the prior index intact. Search results mark source hashes that no longer match as stale. Scanned PDFs require OCR through another available capability; the indexer does not infer missing text.

Artifacts store immutable revisions and SHA-256 content hashes. Markdown is rendered, JSON is parsed before saving, and HTML previews use an opaque sandbox with a restrictive CSP and no network access. Export downloads the saved revision. Concurrent stale edits are refused. Revising an evidenced artifact invalidates earlier affected mission evidence and dependent work; completion checks the current artifact hash again.

## Browser and desktop

`browser_action` extends the existing browser with pointer and keyboard controls, scroll, form input, workspace upload, JavaScript, owned tabs, history, console and network metadata, screenshot crops and authenticated downloads. User takeover still prevents agent interaction. Network diagnostics omit request headers and response bodies. Downloaded files stay under the conversation's managed outputs. Popups remain owned tabs so their opener survives authorization flows.

`computer_action` implements native Windows screenshot/crop, cursor, click/drag/scroll, text and key operations, plus an optional PyAutoGUI primary-display backend for macOS and Linux X11. Desktop control is disabled until enabled in Agent settings, and mutations use approvals. Windows screenshot origins describe physical virtual-desktop coordinates, including monitors left of the primary display. Portable backends require their dependency and OS permissions; Wayland is unsupported. An elevated application may refuse input from a non-elevated host.

Browser demonstrations record user input for at most ten minutes or 1,200 events. Recognized sensitive text fields are omitted. The result is a disabled instruction draft requiring selector/value review; this is not a credential recorder or a guarantee that a coordinate sequence remains reusable.

## Connections, plugins and application views

New connector environment and header values use Windows DPAPI, macOS Keychain through `keyring`, or Linux Secret Service through `secret-tool`. Existing plaintext connector configuration is migrated when the OS vault is available. Secrets are resolved when creating a transport, masked in UI responses and omitted from scoped device endpoints. The keychain must be unlocked. Process-mode Python running as the same OS user is not a separate credential security boundary.

HTTP connectors support user-configured authorization-code PKCE, one-use expiring state, vault-backed tokens and serialized refresh. Tokens are not accepted from plugin bundles. MCP elicitation passes non-secret forms through `ask_user`; sensitive requests require a secure handoff. Remote advice through `consult_advisor` requires the mission's authorized spending budget. Local advice uses the configured local model.

Native plugin ZIPs use `plugin.json` with `format: "grom-plugin-v1"`, `id`, `version`, `skills` and `connectors`. Skill entries use `SkillCreate` fields and may load instructions from a `file` in the archive. Connections use `ConnectorCreate` and install disabled with approvals. Limits are 10 MiB compressed, 20 MiB expanded, 200 entries, 1 MiB per entry, 50 skills and 20 connections; unsafe paths and duplicate names are rejected. Supporting UTF-8 files remain readable through `plugin_read_file`.

The importer also accepts the default `.claude-plugin/plugin.json`, `skills/*/SKILL.md` and `.mcp.json` layout described in the [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference). Imported instructions are namespaced and disabled for review. Compatible MCP configurations install disabled; configurations needing credentials, substituted variables or an unsupported transport report manual setup warnings. Provider-specific hooks, agents, commands, custom paths, settings, channels and workflows are retained as source material rather than executed by Studio. This is an instruction/MCP importer, not a complete emulation of the provider's plugin runtime.

MCP tools declaring `meta.ui.resourceUri` can display bundled HTML through the official MCP Apps bridge. The host installs its message transport before loading app scripts. Views receive the original tool input and structured result. App-initiated tool calls queue for explicit human review and may execute only against that connection while the owning agent is idle. Network access is blocked initially. Resource metadata may request exact HTTPS connect/resource origins; the user can inspect and allow those origins for the current view. Wildcards, insecure origins, embedded frames and browser device permissions remain blocked. The bridge supports resource listing, reviewed resource reads/downloads, reviewed text messages and persistent application context, and reviewed HTTP(S) links. Tools with `meta.ui.visibility: ["app"]` stay out of the model catalog. Application context is source material, not instructions.

## Host, devices, documents and voice

A data-directory lock prevents two hosts from owning the same database. Registering the background host creates a limited Windows sign-in task, Linux user service, or macOS LaunchAgent. Registration starts at the next sign-in; it does not spawn another owner during the current session. Desktop startup can attach to a running service with the matching data-directory identity. The machine must remain awake, and moving the installation may require re-registering its path.

The device listener defaults to `127.0.0.1:8767` and exposes its own scoped API, not the unrestricted Studio API. It starts only after explicit configuration; that choice is restored on host startup. Device tokens are shown once and stored as hashes. Grants list exact conversation IDs and any of `read`, `chat`, `approve`, `events`, `deliver_events`, `documents`, `notifications`. Revocation is checked on each operation and during WebSocket delivery. Local HTTPS can be configured with an encrypted private key and a one-year localhost certificate. Trust installation is a separate explicit user action; certificates near expiry can be renewed. Remote access requires a separately configured HTTPS proxy; Studio does not create a tunnel.

Gateway endpoints are GET `/`, `/permissions`, `/sessions`, `/sessions/{sid}`, `/voice/models`; POST `/sessions/{sid}/send`, `/stop`, `/approve/{call_id}`, `/answer/{call_id}`, `/transcribe`, and `/events/{topic}`. HTTP requests use `Authorization: Bearer …`. WebSocket `/events` and `/documents` receive the token in the first JSON message, not in their URL. Reading event streams does not grant event delivery. External event deliveries require `deliver_events` and include `session_id`, `event_id` and `payload` and activate only wakes in the granted conversation. Receipts deduplicate events per source/topic/conversation. A wake interrupted during execution is paused for inspection rather than silently replayed. Recurring routines continue to use the existing Automations engine.

`documentBridge.ts` lets an editor advertise handlers it actually implements. The built-in Documents panel supports text and JSON sheet editing. Command schemas enter the owning conversation's catalog and explicitly scoped children, execute with normal approval and fail on disconnect or a 60-second deadline. An Office add-in or another native editor must implement and connect its own handlers; no installed Office integration is assumed.

The Voice panel supports reviewed recordings and a continuous local conversation. Whisper endpoints finished utterances into messages or answers to agent questions; local TTS reads new replies. Queued speech waits for an active agent turn, and transcription is muted during playback to prevent echoes. Interrupt speech stops playback and requests cancellation of pending synthesis. Synthesis has a three-minute client deadline. A full utterance queue reports the unsent text rather than silently dropping older messages. Approvals require visible controls. This is turn-based continuous voice, with no audio-to-audio model or automatic voice approval. The mobile page supports the same local dictation/speech flow with authenticated, conversation-scoped job events and audio downloads. Audio input is capped at one second per frame and thirty seconds of queued PCM.

Notifications persist in the Activity inbox and deduplicate durable receipts. Approval requests, questions, errors, completed missions, scheduled work and subagent results can notify their owner. Independent desktop notifications are opt-in and activate when there are no connected Studio clients. Browser push is separately opt-in, requires HTTPS, browser permission and a `notifications` device grant, and uses the browser vendor relay. Push subscriptions and VAPID private keys use the OS vault. Push carries generic status and conversation ID, without chat content. Revoked devices and ungranted conversations are excluded at delivery time. The mobile page provides enable/disable controls and an installable web manifest.

## Execution configuration

Process mode is the default. Optional container mode requires a local Docker engine and the worker image:

```powershell
docker build -f server/workers/agent-container.Dockerfile -t grom-agent-worker:1 .
```

`STUDIO_AGENT_WORKER_IMAGE` selects an existing local image. Runs use `--pull=never`, no network, a read-only root, dropped capabilities, resource limits, a non-root user and a dedicated output mount. Missing Docker/image configuration fails explicitly; container selection does not fall back to host execution. The image supplies the standard-library worker; additional libraries must be provided by a reviewed custom image. Existing general shell and persistent Python tools retain their own execution policy; this container selection applies to constructed tools and `run_tool_script`.

## Validation scope

Frontend type checks/build and isolated backend startup/shutdown checks can run without starting models or changing the user's database. Live generation, desktop interaction, Docker execution, account authorization, remote proxies and real editor clients require separate acceptance runs with the relevant local configuration. API presence and a passing build alone do not establish those integrations' end-to-end behavior.


## HTTP application services

The Applications screen includes 15 starter profiles: GitHub, Slack, Gmail, Google Calendar, Drive, Sheets, Docs, Slides, Microsoft 365, Notion, Linear, self-hosted Nominatim places, self-hosted OSRM routes, OpenLigaDB sports and HubSpot CRM. Starter operations are a documented subset; they are not complete vendor SDKs. Native request objects support wider Sheets/Docs/Slides batches and Linear GraphQL. Account registration, appropriate scopes, shared-resource access and provider-specific headers remain required. No account is provisioned automatically. HTTP results include an observation timestamp and endpoint provenance; observation time does not establish the freshness of the provider’s underlying data.

OpenAPI 3 JSON import resolves bounded local references in inputs, separates path/query bindings, applies operation parameter overrides, normalizes nullable input types, and supports JSON bodies. Recursive or external input references, file uploads, complex query serialization and required header/cookie parameters report a manual-adapter requirement. Import is capped at 2 MiB and 500 operations. Review does not install or call the service; installation defaults to disabled. All HTTP service tools retain approval requirements. JSON schemas are checked at installation and input validation uses the JSON Schema validator. HTTPS is required except for loopback development endpoints, redirects are disabled, results are capped at 2 MiB and common credential response fields are redacted. A mutation that fails after dispatch can be uncertain and must be inspected before retrying.

Credentials use the OS vault. OAuth configuration selects `target: mcp | service`. Raw API-key Authorization headers can be supplied where a provider does not use Bearer tokens. Documentation links on starter profiles point to the providers' current API references.

| Method | Path | Body/query | Result |
| --- | --- | --- | --- |
| GET | `/coverage` | `sid?` | `CapabilityFamily[]`, requirements and ready/setup state |
| GET | `/service-templates` | | `ServiceTemplate[]`, disabled starter operations and provider documentation |
| GET / POST | `/services` | POST `ServiceCreate` | Masked service list / installed service |
| POST | `/services/import` | `ServiceImport` | `ServiceReview`, operation schemas and warnings |
| PATCH | `/services/{id}` | `{enabled}` | Masked updated service |
| DELETE | `/services/{id}` | | 204 |
| PUT | `/connections/{id}/context` | `ApplicationContext` | Latest human-reviewed source context for the conversation |
| GET | `/notifications` | `sid?` | `AgentNotification[]`, latest 200 records |
| PATCH | `/notifications/{id}` | | 204; mark read |
| GET / PUT | `/notification-settings` | PUT `NotificationSettings` | Owner delivery preferences |
| POST | `/host/tls` | | Configure or renew encrypted localhost certificate; does not trust it |
| POST | `/host/trust` | `GatewayTrustRequest` | Explicit OS user-store trust installation; Linux uses manual browser setup |

## Native Office and local document files

The document gateway serves `/office` and `/office/manifest.xml?host=word|excel|powerpoint&base_url=<trusted HTTPS origin>`. Sideload the corresponding manifest into an installed supported Office application, then connect with a document-scoped token and conversation ID. Minimum requirement sets are WordApi 1.3, ExcelApi 1.9 and PowerPointApi 1.4. The task pane loads Microsoft's Office.js. It advertises only commands implemented for the current Office host.

Word commands cover document/selection/paragraph reads, exact passage replacement, headings, selection formatting, tables and small images. Excel commands cover sheets/ranges, values and formulas, calculation, formatting, sorting, tables and charts. PowerPoint commands cover slide/shape reads, text boxes, geometric shapes, text formatting and checked geometry changes. Expected text, cell values, formulas and geometry detect conflicting edits where provided or required. A disconnected pane discards queued commands rather than executing them against a new connection. Native Office editing needs acceptance testing in the actual installed Office client.

`office_file_help` documents the structured `office_file` fields. The CPU document environment supplies DOCX/XLSX/PPTX/PDF reading, creation, checked text editing, charts, formatting, row sorting, slide notes, PDF merge/extraction and PDF rendering. Every edit produces a new managed output with a hash and download link; originals are retained. Source files are restricted to the conversation workspace or managed outputs/uploads. Document sources are capped at 32 MiB and expanded Office archives at 100 MiB. Image indexes must refer to explicit validated assets. Literal strings starting with `=` remain literal unless formulas are explicitly allowed. Formula caches are calculated by the spreadsheet application; the local file worker does not emulate Excel calculation. Replacing a paragraph resets that paragraph's inline formatting. PDF renders are capped at 20 pages and 20 megapixels per page.

## Research and media inspection

`research_search` uses the conversation browser for public web, image, news, Reddit or X searches with optional domains and date filters. It returns observed links and page text; it does not provide a private global X index or bypass account walls. `read_social_thread` reads loaded X/Reddit thread text and visible media metadata. Continue scrolling with browser tools when replies are not loaded.

`inspect_media` reads local video/audio stream metadata and source hashes and optionally extracts up to 12 timestamped reference frames. It uses installed FFmpeg/FFprobe on CPU and confines inputs to the workspace or managed files, with a 500 MiB source cap. It does not generate a model result or download remote media.

Additional scoped gateway endpoints are GET `/voice/speech-models`, `/voice/jobs/{id}`, `/voice/audio/{job_id}/{output_id}`, `/office`, `/office/manifest.xml`, `/office/icon.png`, `/manifest.webmanifest`, `/mobile-sw.js`, `/push/key`; POST `/sessions/{sid}/speak` and `/push/subscribe`; DELETE `/push/subscriptions` and `/voice/jobs/{id}`; WebSocket `/sessions/{sid}/dictate`. Dictation authenticates with `GatewayDictationHello` in its first frame; job and audio access retain conversation grants. The gateway rejects cloud speech models. The service worker contains no device token.

Implementation references: [Office manifests](https://learn.microsoft.com/en-us/office/dev/add-ins/develop/add-in-manifests), [PowerPoint shapes](https://learn.microsoft.com/en-us/office/dev/add-ins/powerpoint/shapes), [MCP Apps CSP](https://github.com/modelcontextprotocol/ext-apps/blob/main/docs/csp-cors.md), [Ollama embeddings](https://github.com/ollama/ollama/blob/main/docs/capabilities/embeddings.mdx), [browser push transport](https://web.dev/articles/push-notifications-how-push-works).
