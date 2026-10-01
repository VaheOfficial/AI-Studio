/**
 * Image area contract (mirrored by server/studio/schemas_image.py). Routes: docs/api/image.md.
 */
import type { ImageRequest } from '../types'

/**
 * txt2img; img2img (init image + strength); inpaint (init image + mask); edit (reference images the model
 * conditions on natively — FLUX Kontext / FLUX.2 / Qwen-Image-Edit / cloud models).
 */
export type ImageMode = 'txt2img' | 'img2img' | 'inpaint' | 'edit'

/**
 * cfg: classic classifier-free guidance; true-cfg: CFG that needs a negative prompt (Qwen-Image);
 * distilled: guidance is an embedded conditioning value (FLUX); none: guidance is ignored.
 */
export type ImageGuidance = 'cfg' | 'true-cfg' | 'distilled' | 'none'

export interface ImageScheduler {
  id: string
  label: string
}

export interface ImageDefaults {
  steps: number
  guidance: number
  width: number
  height: number
  strength: number
}

export interface ImageSizeRange {
  min: number
  max: number
  step: number
  max_pixels?: number
}

/** A provider-specific enum parameter (OpenRouter: aspect_ratio, resolution, quality, …). */
export interface ImageOption {
  id: string
  label: string
  values: string[]
  default: string
}

/** What an installed image model can do and its defaults — `GET /api/image/models`. */
export interface ImageModelProfile {
  model_id: string
  family: string // "FLUX.1", "SDXL", "HY-Image 3.5"
  engine: string // diffusers pipeline class, worker runtime or cloud provider
  location: 'local' | 'cloud'
  modes: ImageMode[]
  guidance: ImageGuidance
  negative_prompt: boolean
  /** Absent: the model has no step control (cloud). */
  steps_range?: [number, number]
  guidance_range?: [number, number]
  schedulers: ImageScheduler[]
  defaults: ImageDefaults
  /** Absent: the size comes from `options` (aspect ratio / resolution). */
  size?: ImageSizeRange
  options: ImageOption[]
  seed: boolean
  max_count: number
  /** Reference images accepted in edit mode. */
  max_images: number
  /** Estimated VRAM of the weights actually installed (local). */
  vram_gb?: number
  /** Cloud pricing notice. */
  cost?: string
  notes: string[]
}

/** Body of `POST /api/image/generate`: the core `ImageRequest` plus edit inputs. */
export interface ImageGenerateRequest extends ImageRequest {
  mode?: ImageMode // default txt2img
  scheduler?: string
  /** Data URLs or `/files/outputs/...` URLs; the first is the init image for img2img / inpaint. */
  images?: string[]
  /** PNG data URL, white = repaint. */
  mask?: string
  strength?: number
  /** Values for the profile's `options`. */
  options?: Record<string, string>
}

/** Pushed while a local image job denoises: a small latent → RGB preview. */
export type ImageServerEvent = { type: 'image.preview'; job_id: string; step: number; total: number; image: string }
