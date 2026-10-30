import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { AgentArtifact, AgentIdentity, AgentKnowledge, AgentSkill, AgentsOverview, CapabilityEntry } from './contracts/agents'

export const useAgents = () => useQuery({ queryKey: ['agents', 'overview'], queryFn: () => api.get<AgentsOverview>('/agents') })
export const useAgentCapabilities = (query = '') => useQuery({ queryKey: ['agents', 'capabilities', query], queryFn: () => api.get<CapabilityEntry[]>(`/agents/capabilities?schemas=true&query=${encodeURIComponent(query)}`) })
export const useAgentKnowledge = () => useQuery({ queryKey: ['agents', 'knowledge'], queryFn: () => api.get<AgentKnowledge[]>('/agents/knowledge') })
export const useAgentSkills = () => useQuery({ queryKey: ['agents', 'skills'], queryFn: () => api.get<AgentSkill[]>('/agents/skills') })
export const useAgentArtifacts = () => useQuery({ queryKey: ['agents', 'artifacts'], queryFn: () => api.get<AgentArtifact[]>('/agents/artifacts') })
export function useAgentMutation<T, A>(fn: (args: A) => Promise<T>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => { void qc.invalidateQueries({ queryKey: ['agents'] }) } })
}
export const useAgentIdentityUpdate = () => useAgentMutation((a: { id: string; body: Partial<AgentIdentity> }) => api.patch<AgentIdentity>(`/agents/identities/${a.id}`, a.body))
