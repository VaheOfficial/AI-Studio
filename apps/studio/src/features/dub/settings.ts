import type { DubProject, DubSettings } from '../../api/contracts/dub'
import { usePatchDubProject } from './api'

/** `update(st => …)` mutates a copy of the project's settings and saves it. */
export function useSettings(project: DubProject) {
  const patch = usePatchDubProject(project.id)
  return (fn: (st: DubSettings) => void) => {
    const next = structuredClone(project.settings)
    fn(next)
    patch.mutate({ settings: next })
  }
}
