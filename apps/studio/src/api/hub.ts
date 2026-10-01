import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from './client'
import { qk } from './keys'
import { useLive } from './live'
import type { HubCatalog, HubInstallRequest, HubRepo, HubSearchResult, HubSort, HubSource, HubTask, LocalBackend } from './contracts/hub'
import type { Job } from './types'

export interface HubQuery {
  catalog: HubCatalog
  q: string
  task?: HubTask
  sort: HubSort
  gguf: boolean
}

/** Hub search (cached 5 min server-side); keeps the previous results on screen while a new query loads. */
export function useHubSearch(query: HubQuery) {
  const p = new URLSearchParams({ catalog: query.catalog, q: query.q.trim(), sort: query.sort })
  if (query.task) p.set('task', query.task)
  if (query.gguf) p.set('gguf', 'true')
  const qs = p.toString()
  return useQuery({
    queryKey: qk.hubSearch(qs),
    queryFn: () => api.get<HubSearchResult[]>(`/hub/search?${qs}`),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })
}

export interface RepoRef {
  source: HubSource
  id: string
}

export const useHubRepo = (ref: RepoRef | null) =>
  useQuery({
    queryKey: qk.hubRepo(ref?.source ?? '', ref?.id ?? ''),
    queryFn: () => api.get<HubRepo>(`/hub/repo?${new URLSearchParams({ source: ref!.source, id: ref!.id })}`),
    enabled: !!ref,
    staleTime: 5 * 60_000,
  })

/** LM Studio / llama.cpp / Ollama status; refreshed when their runtime state is pushed. */
export const useLocalBackends = () => useQuery({ queryKey: qk.localBackends, queryFn: () => api.get<LocalBackend[]>('/hub/backends') })

export function useInstallVariant() {
  return useMutation({
    mutationFn: (body: HubInstallRequest) => api.post<Job>('/hub/install', body),
    onSuccess: (job) => {
      useLive.getState().upsertJob(job)
      toast.info('Download started', job.title)
    },
    onError: (e: Error) => toast.error('Could not start install', e.message),
  })
}
