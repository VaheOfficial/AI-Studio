import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { AgentPlusAmend, AgentPlusCreate, AgentPlusDetail, AgentPlusMission } from './contracts/agentPlus'

export const useAgentPlusMissions = () => useQuery({
  queryKey: ['agentplus', 'missions'], queryFn: () => api.get<AgentPlusMission[]>('/agents/missions'),
})
export const useAgentPlus = (sid?: string) => useQuery({
  queryKey: ['agentplus', sid], enabled: !!sid,
  queryFn: () => api.get<AgentPlusDetail>(`/agents/missions/${sid}`),
})
export function useAgentPlusAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (a: { kind: 'create'; body: AgentPlusCreate } | { kind: 'amend'; sid: string; body: AgentPlusAmend } |
      { kind: 'resume' | 'pause' | 'cancel'; sid: string }) => a.kind === 'create'
      ? api.post<AgentPlusDetail>('/agents/missions', a.body)
      : a.kind === 'amend' ? api.patch<AgentPlusDetail>(`/agents/missions/${a.sid}`, a.body)
      : api.post<AgentPlusDetail>(`/agents/missions/${a.sid}/${a.kind}`),
    onSuccess: (d) => {
      qc.setQueryData(['agentplus', d.mission.session_id], d)
      void qc.invalidateQueries({ queryKey: ['agentplus', 'missions'] })
    },
  })
}
