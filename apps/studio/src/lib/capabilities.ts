import type { Capabilities, FeatureId } from '../api/types'

/**
 * Why a feature can't be used on this machine, or null when it can. `local` asks for the on-device version: some
 * sections (voice cloning, transcription) have no cloud equivalent. Null while the report is still loading.
 */
export function blocked(caps: Capabilities | undefined, feature?: FeatureId, local = false): string | null {
  if (!caps || !feature) return null
  const f = caps.features[feature]
  if (!f.available) return f.reason ?? `Not available on this ${caps.machine}`
  if (local && !f.local) return 'Needs an NVIDIA GPU'
  return null
}
