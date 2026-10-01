import { useModelsOfKind } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { InstalledModel } from '../../api/types'

/** The installed OmniVoice model: `undefined` until the live model list has synced, `null` when not installed. */
export function useOmniVoice(): InstalledModel | null | undefined {
  const synced = useLive((st) => st.synced)
  const omni = useModelsOfKind('voice').find((m) => m.runtime === 'omnivoice')
  return synced ? (omni ?? null) : undefined
}
