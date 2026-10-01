import { useEffect } from 'react'
import { useModelsOfKind, useSettings } from '../api/hooks'
import { useLive } from '../api/live'
import type { DefaultTask, InstalledModel, ModelKind } from '../api/types'
import { useUI } from '../stores/ui'

/** Pages whose model pick starts from a Settings default (Settings → Default models). */
export const TASK_PAGES: Record<DefaultTask, string> = {
  image: 'image',
  image_edit: 'image-edit',
  voice: 'speak',
  stt: 'stt',
  music: 'music',
  video: 'video',
}

/** The model Settings names as the default for `task`, if any. */
export function useDefaultModel(task: DefaultTask | undefined): string | undefined {
  const { data } = useSettings()
  return task ? data?.default_models?.[task] : undefined
}

/** Selected model for a page, remembered across navigation; falls back to the Settings default for `task`, then
 * the first installed model matching `prefer`, else the first installed. */
export function useModelChoice(kind: ModelKind, page: string, prefer?: (m: InstalledModel) => boolean, task?: DefaultTask) {
  const models = useModelsOfKind(kind)
  const synced = useLive((st) => st.synced)
  const offline = useLive((st) => st.status === 'closed')
  const stored = useUI((st) => st.lastModel[page])
  const setLastModel = useUI((st) => st.setLastModel)
  const preferred = useDefaultModel(task)
  const selected =
    models.find((m) => m.id === stored) ??
    models.find((m) => m.id === preferred) ??
    (prefer && models.find(prefer)) ??
    models[0]

  // Persist the fallback so it survives the model list reordering (writes to an external store)
  useEffect(() => {
    if (selected && selected.id !== stored) setLastModel(page, selected.id)
  }, [selected, stored, page, setLastModel])

  return {
    models,
    selected,
    isLoading: !synced && !offline,
    /** Never reached the server — distinct from "nothing installed". */
    unavailable: !synced && offline,
    select: (id: string) => setLastModel(page, id),
  }
}
