import type { VideoModelProfile } from '../../api/contracts/video'

/** Frame shapes offered as tiles; any other size can be typed. */
export const VIDEO_ASPECTS = ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9'] as const
export type VideoAspect = (typeof VIDEO_ASPECTS)[number]

/** Resolutions by their short side (480p … 4K UHD). */
export const RESOLUTIONS = [
  { value: 480, label: '480p' },
  { value: 720, label: '720p' },
  { value: 1080, label: '1080p' },
  { value: 1440, label: '1440p' },
  { value: 2160, label: '4K' },
] as const

export const ratioOf = (a: VideoAspect) => {
  const [w, h] = a.split(':').map(Number)
  return w / h
}

const snap = (v: number, step: number) => Math.max(step, Math.round(v / step) * step)

/** Width × height for a shape and a short side, snapped to what the model accepts. */
export function sizeFor(aspect: VideoAspect, short: number, step: number, maxSide: number): { width: number; height: number } {
  const r = ratioOf(aspect)
  const [w, h] = r >= 1 ? [short * r, short] : [short, short / r]
  const scale = Math.min(1, maxSide / Math.max(w, h))
  return { width: snap(w * scale, step), height: snap(h * scale, step) }
}

/** Above this many pixels per frame LTX-2.5 uses its two-stage path (mirrors server/studio/video.py). */
export const TWO_STAGE_ABOVE = 1280 * 720

export interface Estimate {
  seconds: number
  segments: number
  twoStage: boolean
  /** Much larger than the model was trained at: slow, may run out of memory. */
  heavy: boolean
}

/** Rough render time from the profile's measured speed (loading the model the first time is extra). */
export function estimate(
  p: VideoModelProfile,
  o: { width: number; height: number; seconds: number; steps?: number; upscale: boolean | null; diffusionDecoder: boolean },
): Estimate {
  const frames = o.seconds * p.fps
  const mpx = (o.width * o.height) / 1e6
  const twoStage = p.upscaler && (o.upscale ?? o.width * o.height > TWO_STAGE_ABOVE)
  // two-stage: an 8-step pass at a quarter of the pixels, then a 3-step refine at full size
  let factor = twoStage ? 0.25 + 3 / 8 : 1
  if (p.steps && o.steps) factor *= o.steps / p.steps
  if (o.diffusionDecoder) factor *= 1.3
  // attention grows faster than the pixel count: be more pessimistic for large frames
  const native = (p.native_width * p.native_height) / 1e6
  const bigness = Math.max(1, mpx / native)
  const seconds = p.seconds_per_mpx_frame * mpx * frames * factor * Math.sqrt(bigness)
  return {
    seconds,
    segments: Math.max(1, Math.ceil(o.seconds / p.segment_seconds - 1e-9)),
    twoStage,
    heavy: mpx > native * (twoStage ? 8 : 2.5),
  }
}

export function formatDuration(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s`
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} h`
}
