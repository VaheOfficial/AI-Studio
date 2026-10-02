"""Pydantic mirror of ``apps/studio/src/api/types.ts`` (the API contract).

Optional TS fields (``field?: T``) are ``T | None = None`` here and are omitted from JSON
responses (routers serialize with ``exclude_none``).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from .schemas_automations import AUTOMATION_SERVER_EVENTS
from .schemas_connectors import CONNECTOR_SERVER_EVENTS
from .schemas_game import GAME_SERVER_EVENTS
from .schemas_image import EvImagePreview
from .schemas_openrouter import EvOpenRouterAccount
from .schemas_workspace import (WORKSPACE_SERVER_EVENTS, BrowserInputMessage, BrowserWatchMessage,
                                TerminalCloseMessage, TerminalInputMessage, TerminalOpenMessage, TerminalResizeMessage,
                                ToolDisplay)

ModelKind = Literal["text", "image", "voice", "stt", "music", "video"]
RuntimeId = Literal[
    "ollama", "remote", "diffusers", "hunyuan-image3", "kokoro", "chatterbox", "faster-whisper", "ace-step",
    "omnivoice", "dub", "openrouter", "tencent-cloud", "lmstudio", "llamacpp", "diffusers-video", "python",
]
Fit = Literal["yes", "offload", "no"]
WeightFormat = Literal["gguf", "safetensors", "diffusers", "ollama", "onnx", "ct2", "other"]


class ModelSource(BaseModel):
    type: Literal["hf", "ollama", "remote"]
    repo: str
    revision: str | None = None
    allow_patterns: list[str] | None = None


class CatalogEntry(BaseModel):
    id: str
    name: str
    vendor: str
    kind: ModelKind
    runtime: RuntimeId
    source: ModelSource
    description: str
    params: str | None = None
    size_gb: float
    vram_gb: float
    license: str
    tags: list[str]
    fit: Fit
    notes: str | None = None
    featured: bool | None = None
    installed: bool


InstalledStatus = Literal["ready", "loading", "loaded", "error"]


# How an image model's large text encoders are held in memory: as shipped (bf16), or quantized when the model is
# loaded (bitsandbytes 8-bit / 4-bit NF4). The denoiser's own precision is the variant that was installed.
TextEncoderMode = Literal["full", "8bit", "4bit"]


class InstalledModel(BaseModel):
    id: str
    catalog_id: str
    name: str
    kind: ModelKind
    runtime: RuntimeId
    source_repo: str | None = None
    format: WeightFormat | None = None
    quant: str | None = None
    files: list[str] | None = None
    path: str
    size_bytes: int
    installed_at: str
    status: InstalledStatus
    error: str | None = None
    text_encoder: TextEncoderMode | None = None  # local image pipelines; None = full precision


class ModelPatch(BaseModel):
    """``PATCH /api/models/{id}``: change how an installed model is loaded."""

    text_encoder: TextEncoderMode | None = None


JobKind = Literal["download", "env", "generate", "storage"]
JobStatus = Literal["queued", "running", "done", "error", "cancelled"]
OutputKind = Literal["image", "audio", "music", "video"]


class Output(BaseModel):
    id: str
    kind: OutputKind
    url: str
    model_id: str
    prompt: str
    params: dict[str, Any]
    created_at: str
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None


class JobResult(BaseModel):
    outputs: list[Output]


class Job(BaseModel):
    id: str
    kind: JobKind
    title: str
    ref: str | None = None  # catalog id (download), runtime id (env), model id (generate)
    status: JobStatus
    progress: float
    bytes_done: int | None = None
    bytes_total: int | None = None
    speed_bps: float | None = None
    message: str | None = None
    created_at: str
    result: JobResult | None = None
    error: str | None = None


class GpuInfo(BaseModel):
    name: str
    vram_total: int
    vram_used: int
    util: float
    temp_c: float | None = None


class OllamaStatus(BaseModel):
    installed: bool
    running: bool
    version: str | None = None


class SystemInfo(BaseModel):
    gpus: list[GpuInfo]
    ram_total: int
    ram_used: int
    cpu_percent: float
    disk_free: int
    data_dir: str
    ollama: OllamaStatus


# Areas of the studio that depend on the machine (see capabilities.py)
FeatureId = Literal["image", "voice", "music", "video", "dub", "game", "llamacpp"]


class Feature(BaseModel):
    available: bool
    local: bool = False  # runs on this machine
    cloud: bool = False  # runs through a configured cloud provider
    reason: str | None = None  # why not, when unavailable


class Capabilities(BaseModel):
    """``GET /api/capabilities``: what this machine can do; the UI and the agent's tools follow it."""

    platform: Literal["windows", "macos", "linux"]
    machine: str  # "Windows PC" | "Mac" | "Linux PC"
    arch: str
    gpu: Literal["nvidia", "apple", "none"]
    shell: str  # the agent terminal's shell: "PowerShell 7", "zsh", ...
    features: dict[FeatureId, Feature]


class RuntimeInfo(BaseModel):
    id: RuntimeId
    name: str
    kinds: list[ModelKind]
    env_ready: bool
    running: bool
    port: int | None = None
    loaded_model: str | None = None


OffloadPolicy = Literal["auto", "gpu", "cpu-offload", "sequential-offload"]
# When the agent gets a completion check after a tool-using turn: for models running on this machine (small ones
# tend to stop early), for every model, or never (each check is one more full-size request)
CompletionCheck = Literal["local", "always", "never"]
LocalBackendId = Literal["lmstudio", "llamacpp", "ollama"]


DefaultTask = Literal["image", "image_edit", "voice", "stt", "music", "video"]


# llama.cpp KV cache precision: 8-bit halves its memory (a longer context fits on the GPU) at negligible quality cost
KvCacheType = Literal["q8_0", "f16"]
# Voice of the assistant: friendly (warm, curious, witty), default (balanced), efficient (plain and brief)
Personality = Literal["friendly", "default", "efficient"]


class Settings(BaseModel):
    data_dir: str
    hf_token: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_management_key: str | None = None
    tencent_api_key: str | None = None
    default_chat_model: str | None = None
    # Model the automatic picks use per task (agent tools, game media, pages' first choice); a missing task = the best
    # local model. May name a pinned cloud model: the user chose to pay for it.
    default_models: dict[DefaultTask, str] = Field(default_factory=dict)
    agent_auto_approve: list[str] = Field(default_factory=list)
    agent_completion_check: CompletionCheck = "local"
    offload_policy: OffloadPolicy = "auto"
    default_local_backend: LocalBackendId = "llamacpp"
    # 96K: the largest window that keeps a ~18 GB model entirely on a 24 GB GPU (8-bit KV cache, vision on the CPU)
    llamacpp_ctx_size: int = 98304
    llamacpp_kv_cache: KvCacheType = "q8_0"
    ollama_ctx_size: int = 32768  # context window of Ollama chat requests (capped at what the model supports)
    # The assistant's system prompt (Settings → Assistant)
    assistant_personality: Personality = "friendly"
    assistant_verbosity: int = 4  # 1 = only what's needed … 10 = exhaustive; the user's own requests win
    about_me: str = ""
    custom_instructions: str = ""
    memory_enabled: bool = True


class SettingsUpdate(BaseModel):
    """Partial update for PUT /api/settings. ``""`` clears a value; ``"•••"`` leaves a secret unchanged."""

    data_dir: str | None = None
    hf_token: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_management_key: str | None = None
    tencent_api_key: str | None = None
    default_chat_model: str | None = None
    default_models: dict[DefaultTask, str] | None = None  # replaces the whole map
    agent_auto_approve: list[str] | None = None
    agent_completion_check: CompletionCheck | None = None
    offload_policy: OffloadPolicy | None = None
    default_local_backend: LocalBackendId | None = None
    llamacpp_ctx_size: int | None = Field(None, ge=2048, le=262144)
    llamacpp_kv_cache: KvCacheType | None = None
    ollama_ctx_size: int | None = Field(None, ge=4096, le=262144)
    assistant_personality: Personality | None = None
    assistant_verbosity: int | None = Field(None, ge=1, le=10)
    about_me: str | None = Field(None, max_length=4000)
    custom_instructions: str | None = Field(None, max_length=8000)
    memory_enabled: bool | None = None


class Memory(BaseModel):
    """One fact the assistant remembers about the user across chats (``/api/agent/memories``)."""

    id: str
    text: str
    created_at: str


class MemoryCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class StorageInfo(BaseModel):
    """``GET /api/storage``: where model weights live (``models_dir``, movable) and how much room there is."""

    models_dir: str
    default_models_dir: str
    size_bytes: int
    free_bytes: int  # on the drive holding models_dir
    data_dir: str


class MoveModelsRequest(BaseModel):
    """``POST /api/storage/models-dir``: move every model into ``path`` (an empty or new folder)."""

    path: str = Field(min_length=1, max_length=1000)


class ChatPrice(BaseModel):
    input: float
    output: float


class ChatModelOption(BaseModel):
    id: str
    provider: Literal["ollama", "openai", "lmstudio", "llamacpp", "openrouter"]
    name: str
    tools: bool
    available: bool
    price: ChatPrice | None = None
    context_length: int | None = None
    vision: bool = False  # can look at images


# ------------------------------ Agent ------------------------------

AgentMode = Literal["agent", "chat"]
ToolCallStatus = Literal["pending_approval", "awaiting_input", "running", "done", "error", "denied"]


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any]
    status: ToolCallStatus
    output: str | None = None
    artifacts: list[Output] | None = None
    display: ToolDisplay | None = None
    # Where the call was made: the length of the message's text at that moment, and its place among the message's
    # calls and thinking blocks (cards render there, in order)
    at: int | None = None
    seq: int | None = None


class ThinkingPart(BaseModel):
    """One stretch of the model's reasoning, placed like a tool call (``at`` text offset, ``seq`` order)."""
    at: int
    seq: int
    text: str


class TokenUsage(BaseModel):
    """What an assistant reply used, summed over the model requests of its turn. Each request re-reads the whole
    conversation so far (the API keeps no state), so a turn of N tool steps sends the context N times:
    ``input_tokens`` is that sum, not the size of the conversation. ``cached_tokens`` is the part of it the provider
    served from its prompt cache, which is billed at a fraction of the price."""

    requests: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0


class AgentMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    images: list[str] | None = None  # pictures attached to a user message (/files/outputs/chat/... URLs)
    thinking: str | None = None
    thinking_parts: list[ThinkingPart] | None = None
    tool_calls: list[ToolCall] | None = None
    created_at: str
    cost: float | None = None
    # Generation speed of an assistant reply: tokens the model generated (text, reasoning, tool calls) over all its
    # steps, and the seconds spent generating them (prompt reading excluded)
    output_tokens: int | None = None
    generation_s: float | None = None
    usage: TokenUsage | None = None
    # How long the turn that produced an assistant reply took, in seconds: model requests, reading prompts and
    # running tools, without the time it waited for the user (an approval, a question). Set when the turn ends; in an
    # ActiveTurn snapshot it is the time worked so far.
    elapsed_s: float | None = None


class ContextUsage(BaseModel):
    """Tokens the last model request used out of its context window (``limit`` unknown for some providers)."""

    used: int
    limit: int | None = None


class AgentSession(BaseModel):
    id: str
    title: str
    model: str
    mode: AgentMode
    created_at: str
    updated_at: str
    messages: list[AgentMessage] | None = None
    context: ContextUsage | None = None
    context_size: int | None = None  # this chat's context window (tokens); None = automatic


class AgentImages(BaseModel):
    """``POST /api/agent/images``: public URLs of the stored pictures, in upload order."""

    urls: list[str]


class CreateSessionRequest(BaseModel):
    model: str
    mode: AgentMode = "agent"


class PatchSessionRequest(BaseModel):
    title: str | None = None
    model: str | None = None
    mode: AgentMode | None = None
    context_size: int | None = Field(None, ge=0, le=16 * 2**20)  # tokens; 0 = automatic (the model's / Settings)


class CompactRequest(BaseModel):
    """``/compact``: summarize the chat now; ``focus`` says what the summary should keep in detail."""

    focus: str | None = Field(None, max_length=1000)


class CompactResult(BaseModel):
    session: AgentSession
    folded: int  # messages the summary now stands in for
    summary: str


class MessageRef(BaseModel):
    message_id: str


class RewindResult(BaseModel):
    """What rewinding undid: files put back (``restored``), files the agent had created and that are gone again
    (``removed``), ones that couldn't be reverted (``skipped``: too large, locked), and terminal commands that
    ran in the removed turns — their effects stay. ``prompt`` is the removed user message, for editing."""
    session: AgentSession
    prompt: str
    restored: list[str]
    removed: list[str]
    skipped: list[str]
    commands: list[str]


class EvTurnStart(BaseModel):
    type: Literal["turn.start"] = "turn.start"
    user_message: AgentMessage


class EvMessageStart(BaseModel):
    type: Literal["message.start"] = "message.start"
    message_id: str


class EvTextDelta(BaseModel):
    type: Literal["text.delta"] = "text.delta"
    text: str


class EvThinkingDelta(BaseModel):
    type: Literal["thinking.delta"] = "thinking.delta"
    text: str
    # The thinking part this belongs to (a new seq starts a new block at text offset ``at``)
    at: int
    seq: int


class EvToolCall(BaseModel):
    type: Literal["tool.call"] = "tool.call"
    call: ToolCall


class EvToolDraft(BaseModel):
    """The model is writing a tool call (``chars`` of arguments so far); the call follows as ``tool.call`` when
    its step ends. Not part of the saved message."""

    type: Literal["tool.draft"] = "tool.draft"
    name: str
    chars: int


class EvToolApproval(BaseModel):
    type: Literal["tool.approval"] = "tool.approval"
    call_id: str


class EvToolProgress(BaseModel):
    type: Literal["tool.progress"] = "tool.progress"
    call_id: str
    display: ToolDisplay


class EvToolResult(BaseModel):
    type: Literal["tool.result"] = "tool.result"
    call_id: str
    ok: bool
    output: str
    artifacts: list[Output] | None = None
    display: ToolDisplay | None = None


class EvTitle(BaseModel):
    type: Literal["title"] = "title"
    title: str


class EvDone(BaseModel):
    type: Literal["done"] = "done"


class EvError(BaseModel):
    type: Literal["error"] = "error"
    message: str


class EvUsage(BaseModel):
    """A billed model step (OpenRouter): ``cost`` USD of the step, ``total`` of the message so far."""

    type: Literal["usage"] = "usage"
    cost: float
    total: float


class EvSpeed(BaseModel):
    """After a model step: the reply's generated tokens and generation seconds so far (tok/s = tokens / seconds)."""

    type: Literal["speed"] = "speed"
    output_tokens: int
    generation_s: float


class EvTokens(BaseModel):
    """After a model step: the reply's token totals so far."""

    type: Literal["tokens"] = "tokens"
    usage: TokenUsage


class EvContext(BaseModel):
    """Context use after a model step; ``note`` when older steps were trimmed or summarized to make room."""

    type: Literal["context"] = "context"
    usage: ContextUsage
    note: str | None = None


AgentEvent = Annotated[
    Union[EvTurnStart, EvMessageStart, EvTextDelta, EvThinkingDelta, EvToolDraft, EvToolCall, EvToolApproval,
          EvToolProgress,
          EvToolResult, EvTitle, EvDone, EvError, EvUsage, EvSpeed, EvTokens, EvContext],
    Field(discriminator="type"),
]


class ActiveTurn(BaseModel):
    """A turn still running on the server — lets a reconnecting client resume rendering it."""

    session_id: str
    user_message: AgentMessage
    message: AgentMessage  # the assistant message streamed so far


class Snapshot(BaseModel):
    """Full state sent on every (re)connect."""

    system: SystemInfo
    jobs: list[Job]
    models: list[InstalledModel]
    runtimes: list[RuntimeInfo]
    active_turns: list[ActiveTurn]


# ----------------------------- Server events (WebSocket /api/ws) -----------------------------

LogLevel = Literal["debug", "info", "warn", "error"]


class EvHello(BaseModel):
    type: Literal["hello"] = "hello"
    version: str
    snapshot: Snapshot


class EvSystem(BaseModel):
    type: Literal["system"] = "system"
    system: SystemInfo


class EvJobUpdate(BaseModel):
    type: Literal["job.update"] = "job.update"
    job: Job


class EvModelUpdate(BaseModel):
    type: Literal["model.update"] = "model.update"
    model: InstalledModel


class EvModelRemoved(BaseModel):
    type: Literal["model.removed"] = "model.removed"
    id: str


class EvRuntimeUpdate(BaseModel):
    type: Literal["runtime.update"] = "runtime.update"
    runtime: RuntimeInfo


class EvLog(BaseModel):
    type: Literal["log"] = "log"
    level: LogLevel
    source: str
    message: str
    ts: str


class EvAgent(BaseModel):
    type: Literal["agent"] = "agent"
    session_id: str
    event: AgentEvent


class EvErrorReply(BaseModel):
    """Reply to a client message that could not be handled."""

    type: Literal["error"] = "error"
    message: str
    ref: str | None = None


ServerEvent = Annotated[
    Union[EvHello, EvSystem, EvJobUpdate, EvModelUpdate, EvModelRemoved, EvRuntimeUpdate, EvLog, EvAgent,
          EvErrorReply, EvOpenRouterAccount, EvImagePreview, *WORKSPACE_SERVER_EVENTS, *GAME_SERVER_EVENTS,
          *AUTOMATION_SERVER_EVENTS, *CONNECTOR_SERVER_EVENTS],
    Field(discriminator="type"),
]
server_event_adapter: TypeAdapter[Any] = TypeAdapter(ServerEvent)

# ----------------------------- Client messages (WebSocket /api/ws) -----------------------------


class AgentSendMessage(BaseModel):
    type: Literal["agent.send"]
    session_id: str
    content: str
    images: list[str] = Field(default_factory=list, max_length=8)  # URLs from POST /agent/images
    ref: str | None = None


class AgentApproveMessage(BaseModel):
    type: Literal["agent.approve"]
    session_id: str
    call_id: str
    approved: bool
    ref: str | None = None


class AgentStopMessage(BaseModel):
    type: Literal["agent.stop"]
    session_id: str
    ref: str | None = None


class AgentAnswerMessage(BaseModel):
    """The user's answer to an ``ask_user`` question."""

    type: Literal["agent.answer"]
    session_id: str
    call_id: str
    answer: str = Field(min_length=1, max_length=4000)
    ref: str | None = None


ClientMessage = Annotated[
    Union[AgentSendMessage, AgentApproveMessage, AgentStopMessage, AgentAnswerMessage, TerminalOpenMessage, TerminalInputMessage,
          TerminalResizeMessage, TerminalCloseMessage, BrowserWatchMessage, BrowserInputMessage],
    Field(discriminator="type"),
]
client_message_adapter: TypeAdapter[Any] = TypeAdapter(ClientMessage)

# ------------------------------ Generation ------------------------------


class TTSRequest(BaseModel):
    """``voice_id``: a voice profile id (see ``schemas_voice.VoiceProfile``) or a model preset id."""

    model_id: str
    text: str = Field(min_length=1)
    voice_id: str
    speed: float = Field(1.0, gt=0.1, le=4.0)
    exaggeration: float | None = Field(None, ge=0, le=2)
    cfg_weight: float | None = Field(None, ge=0, le=2)


class TranscribeSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResult(BaseModel):
    text: str
    language: str
    segments: list[TranscribeSegment]


class MusicRequest(BaseModel):
    model_id: str
    tags: str
    lyrics: str = "[instrumental]"
    duration_s: float = Field(30, ge=5, le=240)
    steps: int = Field(60, ge=1, le=200)
    guidance: float = Field(15.0, ge=0, le=50)
    seed: int | None = None


class HealthResponse(BaseModel):
    ok: bool
    version: str
