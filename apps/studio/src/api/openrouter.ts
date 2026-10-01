import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from './client'
import { qk } from './keys'
import type { CloudCatalogPage, CloudModel, CloudOutputFilter, CloudSort, OpenRouterAccount } from './contracts/openrouter'

interface CloudQuery {
  output: CloudOutputFilter
  q: string
  tools: boolean
  free: boolean
  pinned: boolean
  sort: CloudSort
  limit: number
  /** USD per 1M input tokens. */
  maxInputPrice?: number
  minContext?: number
}

function queryString(c: CloudQuery): string {
  const p = new URLSearchParams({ output: c.output, q: c.q.trim(), sort: c.sort, limit: String(c.limit) })
  if (c.tools) p.set('tools', 'true')
  if (c.free) p.set('free', 'true')
  if (c.pinned) p.set('pinned', 'true')
  if (c.maxInputPrice != null) p.set('max_input_price', String(c.maxInputPrice))
  if (c.minContext) p.set('min_context', String(c.minContext))
  return p.toString()
}

/** The OpenRouter catalog, filtered and cached server-side; keeps the previous page while a new filter loads. */
export function useCloudModels(query: CloudQuery) {
  const qs = queryString(query)
  return useQuery({
    queryKey: qk.cloudModels(qs),
    queryFn: () => api.get<CloudCatalogPage>(`/openrouter/models?${qs}`),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })
}

/** Balance and spend. Kept fresh by `openrouter.account` pushes after every billed request. */
export const useOpenRouterAccount = () =>
  useQuery({
    queryKey: qk.openrouterAccount,
    queryFn: () => api.get<OpenRouterAccount>('/openrouter/account'),
    staleTime: 60_000,
  })

/** Re-read the balance now (e.g. after buying credits, which OpenRouter doesn't push to us). */
export function useRefreshOpenRouterAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.get<OpenRouterAccount>('/openrouter/account?refresh=true'),
    onSuccess: (a) => qc.setQueryData(qk.openrouterAccount, a),
    onError: (e: Error) => toast.error('Could not refresh the balance', e.message),
  })
}

export function usePinCloudModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ model, pin }: { model: CloudModel; pin: boolean }) =>
      pin
        ? api.put<CloudModel>(`/openrouter/pins/${model.id}`, {})
        : api.del(`/openrouter/pins/${model.id}`).then(() => ({ ...model, pinned: false })),
    onSuccess: (m) => {
      qc.setQueriesData<CloudCatalogPage>({ queryKey: ['openrouter', 'models'] }, (page) =>
        page && { ...page, models: page.models.map((x) => (x.id === m.id ? { ...x, pinned: m.pinned } : x)) },
      )
      // Pinned-only views must drop / gain the model; the picker and voice lists follow pins
      void qc.invalidateQueries({ queryKey: ['openrouter', 'models'], refetchType: 'inactive' })
      void qc.invalidateQueries({ queryKey: qk.chatModels })
      if (m.use === 'voice') void qc.invalidateQueries({ queryKey: qk.voiceProfiles })
      toast.success(m.pinned ? 'Pinned' : 'Unpinned', m.name)
    },
    onError: (e: Error) => toast.error('Could not update pin', e.message),
  })
}
