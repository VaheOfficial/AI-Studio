/**
 * Model hub contract: search Hugging Face / Ollama / LM Studio's catalog, repo detail with installable variants,
 * variant installs and the local text backends. Mirrored by server/studio/schemas_hub.py. Routes: docs/api/hub.md.
 */
import type { Fit, LocalBackendId, ModelKind, RuntimeId, WeightFormat } from '../types'

/** Where a search looks. "lmstudio" = LM Studio's curated GGUF uploads (the lmstudio-community org on HF). */
export type HubCatalog = 'hf' | 'ollama' | 'lmstudio'
/** Where a repo lives. */
export type HubSource = 'hf' | 'ollama'
export type HubSort = 'downloads' | 'trending' | 'likes' | 'updated'
/** Hugging Face pipeline tags the hub filters by. */
export type HubTask =
  | 'text-generation'
  | 'image-text-to-text'
  | 'text-to-image'
  | 'image-to-image'
  | 'text-to-speech'
  | 'automatic-speech-recognition'
  | 'text-to-audio'
  | 'audio-to-audio'

export interface HubSearchResult {
  /** HF repo id ("org/name") or Ollama model name ("qwen3", "user/model"). */
  id: string
  source: HubSource
  name: string
  author?: string
  kind?: ModelKind
  task?: string
  downloads?: number
  likes?: number
  updated_at?: string // ISO
  license?: string
  /** Needs accepting terms on huggingface.co + an HF token. */
  gated: boolean
  formats: WeightFormat[]
  /** Ollama: capabilities ("tools", "vision", "thinking") and parameter sizes ("8b"). */
  tags: string[]
  description?: string
}

export interface HubFile {
  path: string
  size: number // bytes
}

/** Base-pipeline parts a quantized image transformer needs (text encoders, VAE, scheduler, configs). */
export interface HubCompanions {
  repo: string
  files: string[]
  size_bytes: number
  gated: boolean
}

/** One installable way of getting a model: a GGUF quant, a diffusers precision, a single-file checkpoint, an Ollama tag… */
export interface HubVariant {
  /** Unique within the repo: "gguf:<stem>", "diffusers:fp16", "file:<path>", "ct2", "catalog:<id>", Ollama tag. */
  id: string
  /** `Job.ref` of this variant's install job. */
  ref: string
  label: string
  format: WeightFormat
  quant?: string
  kind: ModelKind
  /** Repo files that make up the variant (empty for Ollama tags). */
  files: string[]
  size_bytes: number
  companions?: HubCompanions
  /** Estimated memory to run fully on GPU (weights + companions + KV cache / activations). */
  vram_gb: number
  fit: Fit
  /** Runtimes that can load it; empty = no local runtime (the note says why). */
  runtimes: RuntimeId[]
  note?: string
  recommended?: boolean
  /** InstalledModel id when this variant is already installed. */
  installed_id?: string
}

export interface HubRepo {
  id: string
  source: HubSource
  name: string
  author?: string
  kind?: ModelKind
  task?: string
  license?: string
  gated: boolean
  base_models: string[]
  downloads?: number
  likes?: number
  updated_at?: string
  tags: string[]
  /** First prose paragraph of the model card. */
  summary?: string
  url: string
  files: HubFile[]
  variants: HubVariant[]
  /** Quantized builds of this model in other repos (GGUF conversions etc.). */
  related: HubSearchResult[]
}

export interface HubInstallRequest {
  source: HubSource
  repo: string
  variant: string
  /** For GGUF language models: llamacpp | lmstudio | ollama. Defaults to Settings.default_local_backend. */
  runtime?: RuntimeId
}

/** An engine that runs GGUF language models. */
export interface LocalBackend {
  id: LocalBackendId
  name: string
  installed: boolean
  running: boolean
  version?: string
  /** OpenAI-compatible base URL while running. */
  endpoint?: string
  models_dir?: string
  detail?: string
  /** Download page when not installed. */
  install_url?: string
}
