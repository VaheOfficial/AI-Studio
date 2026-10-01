import { useEffect, useState } from 'react'
import { create } from 'zustand'
import type { ImageGenerateRequest, ImageMode, ImageModelProfile } from '../../api/contracts/image'
import type { Output } from '../../api/types'
import { resolveSeed } from '@studio/ui'
import { useUI } from '../../stores/ui'
import { ASPECTS, fitSize, ratioOf, sizeForRatio, type Aspect } from './sizes'

/** Everything the Generate / Edit forms edit, independent of the chosen model. */
export interface ImageDraft {
  prompt: string
  negative: string
  /** null = custom size */
  aspect: Aspect | null
  width: number
  height: number
  steps: number
  guidance: number
  scheduler: string // '' = the model's own
  count: number
  seed: number
  lockSeed: boolean
  /** The seed the last run used (random runs), shown so a good one can be kept. */
  lastSeed?: number
  strength: number
  options: Record<string, string>
}

const initial: ImageDraft = {
  prompt: '',
  negative: '',
  aspect: '1:1',
  width: 1024,
  height: 1024,
  steps: 28,
  guidance: 4.5,
  scheduler: '',
  count: 1,
  seed: resolveSeed(null),
  lockSeed: false,
  strength: 0.7,
  options: {},
}

/** Model defaults (steps, guidance, native size, provider options) layered over a draft. */
export function withProfileDefaults(d: ImageDraft, p: ImageModelProfile): ImageDraft {
  const size = d.aspect ? sizeForRatio(ratioOf(d.aspect), p) : fitSize(d.width, d.height, p)
  return {
    ...d,
    steps: p.defaults.steps,
    guidance: p.defaults.guidance,
    strength: p.defaults.strength,
    scheduler: '',
    width: size.w,
    height: size.h,
    count: Math.min(d.count, p.max_count),
    options: Object.fromEntries(p.options.map((o) => [o.id, o.default])),
  }
}

/** Settings of a finished image, for "reuse settings". */
export function withOutputParams(d: ImageDraft, o: Output): ImageDraft {
  const p = o.params as Partial<ImageGenerateRequest>
  const aspect = ASPECTS.find((a) => o.width && o.height && Math.abs(ratioOf(a) - o.width / o.height) < 0.01) ?? null
  return {
    ...d,
    prompt: o.prompt,
    negative: p.negative_prompt ?? '',
    aspect,
    width: p.width ?? o.width ?? d.width,
    height: p.height ?? o.height ?? d.height,
    steps: p.steps ?? d.steps,
    guidance: p.guidance ?? d.guidance,
    scheduler: p.scheduler ?? '',
    strength: p.strength ?? d.strength,
    options: p.options ?? d.options,
    seed: p.seed ?? d.seed,
    lockSeed: p.seed != null,
  }
}

/** Form state for a page; re-applies model defaults whenever the selected profile changes.
 * `from` (a handed-off output) seeds the form with that image's settings instead of its model's defaults. */
export function useImageDraft(profile: ImageModelProfile | undefined, from?: Output) {
  const [draft, setDraft] = useState(() => (from ? withOutputParams(initial, from) : initial))
  const [defaultsFor, setDefaultsFor] = useState(from?.model_id)
  if (profile && profile.model_id !== defaultsFor) {
    // Adjusting state during render (not in an effect) avoids a flash of the previous model's values
    setDefaultsFor(profile.model_id)
    setDraft((d) => withProfileDefaults(d, profile))
  }
  const patch = (p: Partial<ImageDraft>) => setDraft((d) => ({ ...d, ...p }))
  /** Apply a finished image's settings; `modelId` keeps them from being replaced by that model's defaults. */
  const reuse = (o: Output, modelId?: string) => {
    if (modelId) setDefaultsFor(modelId)
    setDraft((d) => withOutputParams(d, o))
  }
  return { draft, patch, reuse }
}

/** The request for a draft; rolls a new seed unless it is locked. */
export function buildRequest(
  d: ImageDraft,
  profile: ImageModelProfile,
  mode: ImageMode,
  extra: Pick<ImageGenerateRequest, 'images' | 'mask'> = {},
): { req: ImageGenerateRequest; seed: number } {
  const seed = resolveSeed(d.lockSeed ? d.seed : null)
  const { w, h } = fitSize(d.width, d.height, profile)
  const req: ImageGenerateRequest = {
    model_id: profile.model_id,
    prompt: d.prompt.trim(),
    negative_prompt: profile.negative_prompt ? d.negative.trim() || undefined : undefined,
    width: w,
    height: h,
    steps: d.steps,
    guidance: d.guidance,
    seed: profile.seed ? seed : undefined,
    count: Math.min(d.count, profile.max_count),
    mode,
    scheduler: d.scheduler || undefined,
    strength: mode === 'img2img' || mode === 'inpaint' ? d.strength : undefined,
    options: profile.options.length ? d.options : undefined,
    ...extra,
  }
  return { req, seed }
}

/* ------------------- hand-off between Gallery, Generate and Edit ------------------- */

interface Handoff {
  id: number
  target: 'generate' | 'edit'
  output: Output
}

let handoffId = 0

/** Model-choice key of each page (see `useImageModelChoice`). */
export const PAGE_KEY = { generate: 'image', edit: 'image-edit' } as const

/** "Reuse settings" / "Send to Edit" carry an output to the other page and preselect its model there. */
export const useImageHandoff = create<{ handoff?: Handoff; send: (target: Handoff['target'], output: Output) => void }>(
  (set) => ({
    send: (target, output) => {
      useUI.getState().setLastModel(PAGE_KEY[target], output.model_id)
      set({ handoff: { id: ++handoffId, target, output } })
    },
  }),
)

/** The output handed to this page, taken once when it mounts. */
export function useTakeHandoff(target: Handoff['target']): Output | undefined {
  const [taken] = useState(() => {
    const h = useImageHandoff.getState().handoff
    return h?.target === target ? h : undefined
  })
  useEffect(() => {
    if (taken && useImageHandoff.getState().handoff?.id === taken.id) useImageHandoff.setState({ handoff: undefined })
  }, [taken])
  return taken?.output
}
