import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from './client'
import type { ArenaMatch, ArenaCreate, ArenaControl } from './contracts/arena'
export const arenaKeys = { all: ['arena'] as const, list: ['arena', 'list'] as const, match: (id: string) => ['arena', 'match', id] as const }
export const useArenaMatches = () => useQuery({ queryKey: arenaKeys.list, queryFn: () => api.get<ArenaMatch[]>('/arena') })
export const useArena = (id: string) => useQuery({ queryKey: arenaKeys.match(id), queryFn: () => api.get<ArenaMatch>(`/arena/${id}`), structuralSharing: (old, next) => old && (old as ArenaMatch).revision > (next as ArenaMatch).revision ? old : next })
export function updateArena(qc: QueryClient, match: ArenaMatch) {
  const fresh = (old?: ArenaMatch) => !old || match.revision >= old.revision ? match : old
  qc.setQueryData(arenaKeys.match(match.id), fresh)
  qc.setQueryData<ArenaMatch[]>(arenaKeys.list, (old = []) => [fresh(old.find(v => v.id === match.id)), ...old.filter(v => v.id !== match.id)].sort((a,b) => b.created_at.localeCompare(a.created_at)))
}
export function useCreateArena() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (value: ArenaCreate) => api.post<ArenaMatch>('/arena', value), onSuccess: value => updateArena(qc, value), onError: (e: Error) => toast.error('Could not create match', e.message) })
}
export function useArenaControl(id: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (value: ArenaControl) => api.post<ArenaMatch>(`/arena/${id}/control`, value), onSuccess: value => updateArena(qc,value), onError: (e: Error) => toast.error('Could not update match', e.message) })
}
export function useInterject(id: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (text: string) => api.post<ArenaMatch>(`/arena/${id}/interject`, {text}), onSuccess: value => updateArena(qc,value), onError: (e: Error) => toast.error('Could not send message', e.message) })
}
