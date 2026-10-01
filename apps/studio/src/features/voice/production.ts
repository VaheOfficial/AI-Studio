import type { SpeakRequest } from '../../api/contracts/voice'

/** OmniVoice sampling overrides. `duration` 0 = natural length; `seed` null = random each render. */
export interface Production {
  num_step: number
  guidance_scale: number
  duration: number
  t_shift: number
  position_temperature: number
  class_temperature: number
  denoise: boolean
  postprocess_output: boolean
  seed: number | null
}

export const DEFAULT_PRODUCTION: Production = {
  num_step: 16,
  guidance_scale: 2,
  duration: 0,
  t_shift: 0.1,
  position_temperature: 5,
  class_temperature: 0,
  denoise: true,
  postprocess_output: true,
  seed: null,
}


/** The request fields for these settings (defaults are left to the server). */
export function productionFields(p: Production): Partial<SpeakRequest> {
  return {
    num_step: p.num_step,
    guidance_scale: p.guidance_scale,
    duration: p.duration > 0 ? p.duration : undefined,
    t_shift: p.t_shift,
    position_temperature: p.position_temperature,
    class_temperature: p.class_temperature,
    denoise: p.denoise,
    postprocess_output: p.postprocess_output,
    seed: p.seed ?? undefined,
  }
}
