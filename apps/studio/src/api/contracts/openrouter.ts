/**
 * OpenRouter platform contract: cloud catalog, pinned models, account balance and spend.
 * Mirrored by server/studio/schemas_openrouter.py. Routes: docs/api/openrouter.md.
 */

/** What the studio does with a cloud model once pinned. Absent = browse only (video, embeddings…). */
export type CloudUse = 'chat' | 'image' | 'voice' | 'stt'

/**
 * Unit of a price line: USD per 1M input / output tokens, per generated image or megapixel,
 * per 1M characters (TTS), per minute of audio (STT), or per request.
 */
export type PriceUnit = 'input_mtok' | 'output_mtok' | 'image' | 'megapixel' | 'mchar' | 'minute' | 'request'

export interface CloudPrice {
  usd: number
  unit: PriceUnit
}

export type CloudSort = 'newest' | 'price' | 'context' | 'name'
export type CloudOutputFilter = 'all' | 'text' | 'image' | 'speech' | 'transcription' | 'video' | 'embeddings'

/** One OpenRouter model, normalized from `GET /models` (+ per-image pricing from the Images API). */
export interface CloudModel {
  id: string // OpenRouter slug, e.g. "openai/gpt-4o-mini"
  name: string
  vendor: string
  description: string
  created: number // unix seconds
  context_length?: number
  input_modalities: string[] // "text" | "image" | "audio" | "video" | "file"
  output_modalities: string[] // "text" | "image" | "speech" | "transcription" | "video" | "embeddings" …
  use?: CloudUse
  tools: boolean // supports tool calling
  reasoning: boolean
  free: boolean
  prices: CloudPrice[]
  /** Some price is variable (router models such as openrouter/auto) or billed in a unit the listing doesn't name. */
  price_dynamic?: boolean
  /** TTS voices the model accepts. */
  voices?: string[]
  pinned: boolean
}

/** `GET /api/openrouter/models` — one page of the filtered, cached catalog. */
export interface CloudCatalogPage {
  models: CloudModel[]
  total: number // matches before paging
  fetched_at: string // when the server last pulled the catalog from OpenRouter
}

export type ChargeKind = 'chat' | 'title' | 'image' | 'speech' | 'transcription'

/** One billed request recorded by the studio. */
export interface OpenRouterCharge {
  id: string
  ts: string
  kind: ChargeKind
  model: string
  cost?: number // USD; absent when OpenRouter did not report it
  session_id?: string
  ref?: string // job id for generations
}

/** `GET /api/openrouter/account`, also pushed as `openrouter.account` after every billed request. */
export interface OpenRouterAccount {
  configured: boolean // an inference key is set
  management_key: boolean // a management key is set (enables `balance`)
  ok: boolean // OpenRouter accepted the key(s)
  error?: string
  label?: string // OpenRouter's masked label of the key
  /** Credits left on the account (total purchased − total used); needs the management key. */
  balance?: number
  total_credits?: number
  /** Per-key spending cap and what is left of it; absent when the key is uncapped. */
  limit?: number
  limit_remaining?: number
  limit_reset?: string
  usage_total?: number
  usage_daily?: number // UTC day, all apps using this key
  usage_weekly?: number
  usage_monthly?: number
  is_free_tier?: boolean
  studio_today: number // spent by this studio since local midnight
  recent: OpenRouterCharge[]
  updated_at: string
}

export type OpenRouterServerEvent = { type: 'openrouter.account'; account: OpenRouterAccount }
