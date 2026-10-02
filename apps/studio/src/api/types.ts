/**
 * API contract between the Studio UI and the Python server.
 * This file is the source of truth — server/studio/schemas.py mirrors it.
 * All routes are under /api. Server listens on 127.0.0.1:8765.
 */

import type { GameServerEvent } from './contracts/game'
import type { ImageServerEvent } from './contracts/image'
import type { OpenRouterServerEvent } from './contracts/openrouter'
import type { AutomationServerEvent } from './contracts/automations'
import type { ConnectorServerEvent } from './contracts/connectors'
import type { ToolDisplay, WorkspaceClientMessage, WorkspaceServerEvent } from './contracts/workspace'

export type ModelKind = 'text' | 'image' | 'voice' | 'stt' | 'music' | 'video'

/** Which worker/runtime executes a model. */
export type RuntimeId =
  | 'ollama' // text — talks to a local Ollama daemon
  | 'remote' // text — OpenAI-compatible endpoint, nothing local
  | 'diffusers' // image — generic diffusers pipelines
  | 'hunyuan-image3' // image — Tencent HunyuanImage 3.x (trust_remote_code)
  | 'kokoro' // voice — preset-voice TTS
  | 'chatterbox' // voice — zero-shot voice cloning TTS
  | 'faster-whisper' // stt
  | 'ace-step' // music
  | 'omnivoice' // voice — k2-fsa OmniVoice: 646 languages, cloning, tag-based voice design
  | 'dub' // dubbing analysis — demucs separation, word-timestamp ASR, diarization
  | 'openrouter' // cloud — any OpenRouter model (text, image, speech, transcription)
  | 'tencent-cloud' // cloud — Tencent Hunyuan image API (HY-Image 3.5)
  | 'lmstudio' // text — LM Studio's local server (its own model library)
  | 'llamacpp' // text — built-in llama.cpp server for any GGUF from the hub
  | 'diffusers-video' // video — Wan 2.2 and LTX-2.5 through diffusers
  | 'python' // the agent's run_python kernels: pandas, matplotlib, Word/Excel/PowerPoint/PDF libraries (no models)

/** Hardware fit on the current machine, computed server-side from VRAM/RAM. */
export type Fit = 'yes' | 'offload' | 'no'

export interface ModelSource {
  type: 'hf' | 'ollama' | 'remote'
  /** HF repo id ("org/name") or Ollama tag ("qwen3:8b"). */
  repo: string
  revision?: string
  allow_patterns?: string[]
}

export interface CatalogEntry {
  id: string
  name: string
  vendor: string
  kind: ModelKind
  runtime: RuntimeId
  source: ModelSource
  description: string
  params?: string // "8B", "80B MoE (13B active)"
  size_gb: number // download size
  vram_gb: number // recommended VRAM for full-GPU
  license: string
  tags: string[]
  fit: Fit
  notes?: string // honest caveats: "needs 8×H200", "slow with offload"
  featured?: boolean
  installed: boolean
}

export type InstalledStatus = 'ready' | 'loading' | 'loaded' | 'error'

/** How a model's weights are packaged — decides which runtime can load it. */
export type WeightFormat = 'gguf' | 'safetensors' | 'diffusers' | 'ollama' | 'onnx' | 'ct2' | 'other'

/**
 * How a local image pipeline holds its large text encoders in memory: as shipped (bf16), or quantized when the model
 * loads (8-bit, or 4-bit NF4). The denoiser's own precision is the variant that was installed.
 */
export type TextEncoderMode = 'full' | '8bit' | '4bit'

export interface InstalledModel {
  id: string // same as catalog id for catalog installs
  catalog_id: string
  name: string
  kind: ModelKind
  runtime: RuntimeId
  /** Where the weights came from (models installed from the hub); absent for curated/Ollama installs. */
  source_repo?: string
  format?: WeightFormat
  /** Quantization / precision label, e.g. "Q4_K_M", "fp8", "nf4", "bf16". */
  quant?: string
  /** Files of the repo that were downloaded (a single GGUF, or a subset of a diffusers repo). */
  files?: string[]
  path: string
  size_bytes: number
  installed_at: string // ISO
  status: InstalledStatus
  error?: string
  /** Local image pipelines: how the text encoder is held; absent = full precision. */
  text_encoder?: TextEncoderMode
}

/** `PATCH /models/{id}`: change how an installed model is loaded (it is unloaded; applies at the next load). */
export interface ModelPatch {
  text_encoder?: TextEncoderMode
}

export type JobKind = 'download' | 'env' | 'generate' | 'storage'
export type JobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled'

export interface Job {
  id: string
  kind: JobKind
  title: string
  /** What the job concerns: catalog id (download), runtime id (env), model id (generate). */
  ref?: string
  status: JobStatus
  progress: number // 0..1, -1 = indeterminate
  bytes_done?: number
  bytes_total?: number
  speed_bps?: number
  message?: string
  created_at: string
  /** For kind=generate once done. */
  result?: { outputs: Output[] }
  error?: string
}

export type OutputKind = 'image' | 'audio' | 'music' | 'video'

export interface Output {
  id: string
  kind: OutputKind
  url: string // served from /files/outputs/...
  model_id: string
  prompt: string
  params: Record<string, unknown>
  created_at: string
  width?: number
  height?: number
  duration_s?: number
}

export interface GpuInfo {
  name: string
  vram_total: number // bytes
  vram_used: number
  util: number // 0..100
  temp_c?: number
}

export interface SystemInfo {
  gpus: GpuInfo[]
  ram_total: number
  ram_used: number
  cpu_percent: number
  disk_free: number
  data_dir: string
  ollama: { installed: boolean; running: boolean; version?: string }
}

/** Areas of the studio that depend on the machine (server: `capabilities.py`). */
export type FeatureId = 'image' | 'voice' | 'music' | 'video' | 'dub' | 'game' | 'llamacpp'

export interface Feature {
  available: boolean
  local: boolean // runs on this machine
  cloud: boolean // runs through a configured cloud provider
  reason?: string | null // why not, when unavailable
}

/** `GET /api/capabilities`: what this machine can do; navigation and the agent's tools follow it. */
export interface Capabilities {
  platform: 'windows' | 'macos' | 'linux'
  machine: string // "Windows PC" | "Mac" | "Linux PC"
  arch: string
  gpu: 'nvidia' | 'apple' | 'none'
  shell: string // the agent terminal's shell: "PowerShell 7", "zsh", ...
  features: Record<FeatureId, Feature>
}

export interface RuntimeInfo {
  id: RuntimeId
  name: string
  kinds: ModelKind[]
  env_ready: boolean // python env created + deps installed
  running: boolean // worker process up
  port?: number
  loaded_model?: string
}

export interface Settings {
  data_dir: string
  hf_token?: string // write-only; GET returns "•••" when set
  openai_base_url?: string
  openai_api_key?: string // write-only
  openrouter_api_key?: string // write-only; inference key
  openrouter_management_key?: string // write-only; optional, only used to read the account balance
  tencent_api_key?: string // write-only; Tencent Cloud TokenHub key for HY-Image
  default_chat_model?: string // "ollama:qwen3:8b" | "openai:<model>" | "openrouter:<id>"
  /**
   * Model the automatic picks use per task: agent tools, game media and each page's first choice. A missing task
   * means the best local model. May name a pinned cloud model (billed per use).
   */
  default_models: Partial<Record<DefaultTask, string>>
  agent_auto_approve: string[] // tool names that skip approval
  /**
   * When the agent gets a completion check after a tool-using turn: for models running on this machine (small ones
   * tend to stop early), for every model, or never. Each check is one more full-size request.
   */
  agent_completion_check: 'local' | 'always' | 'never'
  offload_policy: 'auto' | 'gpu' | 'cpu-offload' | 'sequential-offload'
  /** Runtime preselected for GGUF language models installed from the hub. */
  default_local_backend: LocalBackendId
  /** Context window llama-server is started with. */
  llamacpp_ctx_size: number
  /** llama.cpp KV cache precision: 8-bit halves its memory, so a longer context fits on the GPU. */
  llamacpp_kv_cache: KvCacheType
  /** Context window of Ollama chat requests (capped at what the model supports). */
  ollama_ctx_size: number
  /** The assistant's voice: friendly (warm, curious, witty), default (balanced), efficient (plain and brief). */
  assistant_personality: Personality
  /** Default answer length, 1 (only what's needed) … 10 (exhaustive); the user's own requests win. */
  assistant_verbosity: number
  /** What the user tells the assistant about themselves (in every chat's system prompt). */
  about_me: string
  /** How the user wants the assistant to answer; takes precedence over its defaults. */
  custom_instructions: string
  /** Whether the assistant keeps and uses memories across chats (`/agent/memories`). */
  memory_enabled: boolean
}

export type KvCacheType = 'q8_0' | 'f16'
export type Personality = 'friendly' | 'default' | 'efficient'

/** One fact the assistant remembers about the user across chats. */
export interface Memory {
  id: string
  text: string
  created_at: string
}

/** Tasks with a default model in Settings (`image_edit`: editing / img2img with reference images). */
export type DefaultTask = 'image' | 'image_edit' | 'voice' | 'stt' | 'music' | 'video'

/** `GET /storage`: where model weights live (`models_dir`, movable) and how much room there is. */
export interface StorageInfo {
  models_dir: string
  default_models_dir: string
  size_bytes: number
  /** Free space on the drive holding models_dir. */
  free_bytes: number
  data_dir: string
}

/** `POST /storage/models-dir`: move every model into `path` (an empty or new folder). Returns a `storage` Job. */
export interface MoveModelsRequest {
  path: string
}

/** Local engines that run GGUF language models. */
export type LocalBackendId = 'lmstudio' | 'llamacpp' | 'ollama'

/** Chat model option for the model picker. `id` is "<provider>:<model>". */
export interface ChatModelOption {
  id: string
  provider: 'ollama' | 'openai' | 'lmstudio' | 'llamacpp' | 'openrouter'
  name: string
  tools: boolean // supports tool calling
  available: boolean
  /** USD per 1M input / output tokens (cloud models that bill per token). */
  price?: { input: number; output: number }
  context_length?: number
  /** Can look at images (attached pictures, screenshots, generated images). */
  vision?: boolean
}

/* ------------------------------ Agent ------------------------------ */

export type AgentMode = 'agent' | 'chat'

export interface ToolCall {
  id: string
  name: string
  args: Record<string, unknown>
  /** `awaiting_input`: an `ask_user` question waiting for the user's answer. */
  status: 'pending_approval' | 'awaiting_input' | 'running' | 'done' | 'error' | 'denied'
  output?: string
  artifacts?: Output[]
  /** Rich render data (diff, terminal excerpt, browser screenshot…), see contracts/workspace.ts. */
  display?: ToolDisplay
  /** Where the call was made: the length of the message's text at that moment (the card renders there). */
  at?: number
  /** Order among the message's tool calls and thinking parts. */
  seq?: number
}

/** One stretch of the model's reasoning, placed like a tool call (`at` text offset, `seq` order). */
export interface ThinkingPart {
  at: number
  seq: number
  text: string
}

export interface AgentMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  /** Pictures attached to a user message (`/files/outputs/chat/...` URLs); the model sees them. */
  images?: string[]
  thinking?: string
  /** The reasoning split where it happened (between text and tool calls); older messages only have `thinking`. */
  thinking_parts?: ThinkingPart[]
  tool_calls?: ToolCall[]
  created_at: string
  /** USD billed for this reply (OpenRouter models). */
  cost?: number
  /** Tokens the model generated for this reply (text, reasoning, tool calls) over all its steps… */
  output_tokens?: number
  /** …and the seconds it spent generating them (prompt reading excluded): tok/s = output_tokens / generation_s. */
  generation_s?: number
  usage?: TokenUsage
  /**
   * How long the turn behind an assistant reply took, in seconds: model requests, reading prompts and running
   * tools, without the time it waited for the user (an approval, a question). Set when the turn ends; in an
   * `ActiveTurn` snapshot it is the time worked so far.
   */
  elapsed_s?: number
}

/**
 * What an assistant reply used, summed over the model requests of its turn. Each request re-reads the whole
 * conversation so far, so a turn of N tool steps sends the context N times: `input_tokens` is that sum, not the size
 * of the conversation. `cached_tokens` is the part of it served from the provider's prompt cache (billed at a
 * fraction of the price).
 */
export interface TokenUsage {
  requests: number
  input_tokens: number
  cached_tokens: number
  output_tokens: number
}

export interface AgentSession {
  id: string
  title: string
  model: string
  mode: AgentMode
  created_at: string
  updated_at: string
  messages?: AgentMessage[]
  /** How full the model's context was on the last request. */
  context?: ContextUsage
  /** This chat's context window in tokens (`/context`); absent = automatic (the model's / Settings). */
  context_size?: number
}

/** `PATCH /agent/sessions/{id}`; `context_size: 0` returns the chat to the automatic window. */
export interface PatchSessionRequest {
  title?: string
  model?: string
  mode?: AgentMode
  context_size?: number
}

/** `POST /agent/sessions/{id}/compact` (`/compact`): the chat so far is summarized for the model. */
export interface CompactRequest {
  /** What the summary should keep in detail. */
  focus?: string
}

export interface CompactResult {
  session: AgentSession
  /** Messages the summary now stands in for. */
  folded: number
  summary: string
}

/** Tokens the last model request used out of its context window (`limit` unknown for some providers). */
export interface ContextUsage {
  used: number
  limit?: number
}

export interface MessageRef {
  message_id: string
}

/**
 * What rewinding undid: files put back (`restored`), files the agent had created that are gone again (`removed`),
 * ones that couldn't be reverted (`skipped`), and terminal commands from the removed turns — their effects stay.
 * `prompt` is the removed user message, for editing and resending.
 */
export interface RewindResult {
  session: AgentSession
  prompt: string
  restored: string[]
  removed: string[]
  skipped: string[]
  commands: string[]
}

/** Events of one agent turn; delivered inside `{ type: 'agent', session_id, event }` on the WebSocket. */
export type AgentEvent =
  /** First event of every turn — carries the persisted user message so every open tab can show it. */
  | { type: 'turn.start'; user_message: AgentMessage }
  | { type: 'message.start'; message_id: string }
  | { type: 'text.delta'; text: string }
  | { type: 'thinking.delta'; text: string; at: number; seq: number }
  /** The model is writing a tool call (`chars` of arguments so far); the call follows as `tool.call` when its step ends. */
  | { type: 'tool.draft'; name: string; chars: number }
  | { type: 'tool.call'; call: ToolCall }
  | { type: 'tool.approval'; call_id: string }
  /** Live update of a running tool's display (e.g. command output so far). */
  | { type: 'tool.progress'; call_id: string; display: ToolDisplay }
  | { type: 'tool.result'; call_id: string; ok: boolean; output: string; artifacts?: Output[]; display?: ToolDisplay }
  | { type: 'title'; title: string }
  | { type: 'done' }
  | { type: 'error'; message: string }
  /** A billed model step (OpenRouter): `cost` of the step, `total` of the reply so far (USD). */
  | { type: 'usage'; cost: number; total: number }
  /** After a model step: the reply's generated tokens and generation seconds so far. */
  | { type: 'speed'; output_tokens: number; generation_s: number }
  /** After a model step: the reply's token totals so far. */
  | { type: 'tokens'; usage: TokenUsage }
  /** Context use after a model step; `note` when older steps were trimmed or summarized to make room. */
  | { type: 'context'; usage: ContextUsage; note?: string }

/** A turn still running on the server — lets a reconnecting client resume rendering it. */
export interface ActiveTurn {
  session_id: string
  user_message: AgentMessage
  /** The assistant message streamed so far (text, thinking, tool calls with their current status). */
  message: AgentMessage
}

/** Full state sent on every (re)connect, so clients never need to poll. */
export interface Snapshot {
  system: SystemInfo
  jobs: Job[]
  models: InstalledModel[]
  runtimes: RuntimeInfo[]
  active_turns: ActiveTurn[]
}

/* ------------------------ WebSocket /api/ws ------------------------ */

/** Server → client. */
export type ServerEvent =
  | { type: 'hello'; version: string; snapshot: Snapshot }
  /** Pushed every ~2s while any client is connected. */
  | { type: 'system'; system: SystemInfo }
  | { type: 'job.update'; job: Job }
  | { type: 'model.update'; model: InstalledModel }
  | { type: 'model.removed'; id: string }
  | { type: 'runtime.update'; runtime: RuntimeInfo }
  | { type: 'log'; level: 'debug' | 'info' | 'warn' | 'error'; source: string; message: string; ts: string }
  | { type: 'agent'; session_id: string; event: AgentEvent }
  /** Reply to a client message that could not be handled (e.g. a turn is already running). */
  | { type: 'error'; message: string; ref?: string }
  | ImageServerEvent
  | OpenRouterServerEvent
  | WorkspaceServerEvent
  | GameServerEvent
  | AutomationServerEvent
  | ConnectorServerEvent

/** Client → server. `ref` is echoed back on a resulting `error`. */
export type ClientMessage =
  /** `images`: URLs from `POST /agent/images` (pictures attached to the message). */
  | { type: 'agent.send'; session_id: string; content: string; images?: string[]; ref?: string }
  | { type: 'agent.approve'; session_id: string; call_id: string; approved: boolean; ref?: string }
  /** The user's answer to an `ask_user` question (one of its options or their own words). */
  | { type: 'agent.answer'; session_id: string; call_id: string; answer: string; ref?: string }
  | { type: 'agent.stop'; session_id: string; ref?: string }
  | WorkspaceClientMessage

/* --------------------------- Generation ---------------------------- */

export interface ImageRequest {
  model_id: string
  prompt: string
  negative_prompt?: string
  width: number
  height: number
  steps: number
  guidance: number
  seed?: number // omitted = random
  count: number
}

/** Base speech request; the voice area sends the richer `SpeakRequest` (contracts/voice.ts). */
export interface TTSRequest {
  model_id: string
  text: string
  /** A voice profile id or a model preset id (`VoiceProfile` in contracts/voice.ts). */
  voice_id: string
  speed: number
  /** chatterbox: 0..1 exaggeration / emotion intensity */
  exaggeration?: number
  cfg_weight?: number
}

export interface TranscribeResult {
  text: string
  language: string
  segments: { start: number; end: number; text: string }[]
}

export interface MusicRequest {
  model_id: string
  tags: string // style prompt, e.g. "synthwave, 110 bpm, female vocals"
  lyrics: string // "[verse]\n...\n[chorus]\n..." or "[instrumental]"
  duration_s: number
  steps: number
  guidance: number
  seed?: number
}
