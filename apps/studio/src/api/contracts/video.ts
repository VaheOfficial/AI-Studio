/**
 * Video area contract: text-to-video and image-to-video with local models (Wan 2.2, LTX-2.5). Mirrored by
 * server/studio/schemas_video.py. Routes: docs/api/video.md.
 */

/** t2v: from a prompt; i2v: the prompt animates a start image. */
export type VideoMode = 't2v' | 'i2v'

/** How LTX-2.5 turns latents into frames: the VAE (fast) or its diffusion decoder (sharper, slower). */
export type VideoDecoder = 'vae' | 'diffusion'

/** Largest side the server accepts (4K UHD) and the longest clip. */
export const VIDEO_MAX_SIDE = 3840
export const VIDEO_MAX_SECONDS = 120

/**
 * What one installed video model can do. Nothing is a hard preset: any size (snapped to `size_step`) and length up to
 * `max_seconds` can be requested; these fields say what is native and what each option does, so the UI can
 * estimate and warn instead of refusing.
 */
export interface VideoModelProfile {
  model_id: string
  name: string
  family: 'wan' | 'ltx2'
  location: 'local' | 'cloud'
  modes: VideoMode[]
  /** Generates a soundtrack with the picture. */
  audio: boolean
  /** The size the model was trained at (landscape; portrait swaps them). */
  native_width: number
  native_height: number
  size_step: number
  max_side: number
  fps: number
  default_seconds: number
  /** Longest single pass; longer clips continue from the last frame, segment by segment. */
  segment_seconds: number
  max_seconds: number
  /** Can pick the length itself (LTX-2.5's duration head). */
  auto_duration: boolean
  /** Two-stage: generate at half size, upsample the latents 2× and refine (used above the native size). */
  upscaler: boolean
  prompt_enhancer: boolean
  diffusion_decoder: boolean
  /** Denoising steps; absent for a fixed (distilled) schedule. */
  steps?: number
  steps_range?: [number, number]
  /** Absent when guidance isn't adjustable. */
  guidance?: number
  /** Measured speed: seconds per megapixel-frame at the default steps (for estimates). */
  seconds_per_mpx_frame: number
  notes: string[]
}

export interface VideoRequest {
  model_id: string
  prompt: string
  negative_prompt?: string
  mode?: VideoMode
  /** i2v start frame: a data URL or a /files/outputs/... URL. */
  image?: string
  /** Absent: the model's native size. */
  width?: number
  height?: number
  /** Absent: the model's default length. */
  duration_s?: number
  /** Let the model pick the length (LTX-2.5); `duration_s` is then the upper bound. */
  auto_duration?: boolean
  steps?: number
  guidance?: number
  /** Two-stage upscale; absent = automatic (above the native size). */
  upscale?: boolean
  enhance_prompt?: boolean
  decoder?: VideoDecoder
  seed?: number
}
