import { useEffect } from 'react'
import type { ImageModelProfile } from '../../api/contracts/image'
import { useModelsOfKind } from '../../api/hooks'
import { useImageProfiles } from '../../api/image'
import { useLive } from '../../api/live'
import { useUI } from '../../stores/ui'
import { useDefaultModel } from '../../components/useModelChoice'
import type { DefaultTask } from '../../api/types'

/** Image model selection for a page, limited to models whose profile passes `accepts`; starts from the Settings
 * default for `task`. */
export function useImageModelChoice(page: string, accepts: (p: ImageModelProfile) => boolean = () => true, task?: DefaultTask) {
  const models = useModelsOfKind('image')
  const { data: profiles = [], isPending } = useImageProfiles()
  const synced = useLive((st) => st.synced)
  const offline = useLive((st) => st.status === 'closed')
  const stored = useUI((st) => st.lastModel[page])
  const setLastModel = useUI((st) => st.setLastModel)
  const eligible = models.filter((m) => {
    const p = profiles.find((x) => x.model_id === m.id)
    return p && accepts(p)
  })
  const preferred = useDefaultModel(task)
  const selected = eligible.find((m) => m.id === stored) ?? eligible.find((m) => m.id === preferred) ?? eligible[0]
  const profile = profiles.find((p) => p.model_id === selected?.id)

  useEffect(() => {
    if (selected && selected.id !== stored) setLastModel(page, selected.id)
  }, [selected, stored, page, setLastModel])

  return {
    models: eligible,
    profiles,
    selected,
    profile,
    isLoading: (!synced && !offline) || (models.length > 0 && isPending),
    unavailable: !synced && offline,
    select: (id: string) => setLastModel(page, id),
  }
}
