import type { ImageModelProfile } from '../../api/contracts/image'

export const ASPECTS = ['1:1', '4:3', '3:4', '16:9', '9:16', '3:2', '2:3'] as const

export type Aspect = (typeof ASPECTS)[number]

export const ratioOf = (a: string) => {
  const [w, h] = a.split(':').map(Number)
  return w / h
}

const snap = (v: number, step: number) => Math.max(step, Math.round(v / step) * step)

/** Clamp a size to what the model accepts: side limits, step multiple and pixel budget. */
export function fitSize(width: number, height: number, profile: ImageModelProfile | undefined) {
  const size = profile?.size
  if (!size) return { w: Math.round(width), h: Math.round(height) }
  let w = width
  let h = height
  if (size.max_pixels && w * h > size.max_pixels) {
    const k = Math.sqrt(size.max_pixels / (w * h))
    w *= k
    h *= k
  }
  const clamp = (v: number) => Math.min(size.max, Math.max(size.min, snap(v, size.step)))
  w = clamp(w)
  h = clamp(h)
  // Rounding up may push the area over the budget again
  while (size.max_pixels && w * h > size.max_pixels && w > size.min && h > size.min) {
    if (w >= h) w -= size.step
    else h -= size.step
  }
  return { w, h }
}

/** Native-area size for a width/height ratio (SDXL 4:3 → 1152×896, FLUX 16:9 → 1360×768 …). */
export function sizeForRatio(ratio: number, profile: ImageModelProfile | undefined) {
  const area = profile ? profile.defaults.width * profile.defaults.height : 1024 * 1024
  return fitSize(Math.sqrt(area * ratio), Math.sqrt(area / ratio), profile)
}
