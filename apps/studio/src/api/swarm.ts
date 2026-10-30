import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { away, notifySystem } from '../lib/notify'
import { api } from './client'
import type {
  Swarm,
  SwarmAgent,
  SwarmAgentSpec,
  SwarmAgentUpdate,
  SwarmCreate,
  SwarmDetail,
  SwarmInboxEntry,
  SwarmInboxReply,
  SwarmServerEvent,
  SwarmUpdate,
} from './contracts/swarm'

export const swarmKeys = {
  all: ['swarms'] as const,
  one: (id: string) => ['swarms', id] as const,
}

/** Events kept in a swarm's page; the server sends the latest 200 with the page. */
const MAX_EVENTS = 400

/**
 * The messages that start a swarm's sessions are written by the server (`studio/swarm/briefs.py`, `controller.py`),
 * not typed by anyone: "[Swarm “Name”: …]" or "(The swarm, not the owner:) …". Its chats run unattended, so they
 * don't announce themselves like the user's own.
 */
export const isSwarmMessage = (content: string) => content.startsWith('[Swarm “') || content.startsWith('(The swarm, not the owner:)')

export const useSwarms = () => useQuery({ queryKey: swarmKeys.all, queryFn: () => api.get<Swarm[]>('/swarms') })

export const useSwarm = (id: string | undefined) =>
  useQuery({ queryKey: swarmKeys.one(id ?? ''), queryFn: () => api.get<SwarmDetail>(`/swarms/${id}`), enabled: !!id })

const failed = (title: string) => (e: Error) => toast.error(title, e.message)

function upsertById<T extends { id: string }>(list: T[], x: T, first = false): T[] {
  return list.some((y) => y.id === x.id) ? list.map((y) => (y.id === x.id ? x : y)) : first ? [x, ...list] : [...list, x]
}

function setSwarm(qc: QueryClient, s: Swarm) {
  qc.setQueryData<Swarm[]>(swarmKeys.all, (old) => (old ? upsertById(old, s, true) : old))
  qc.setQueryData<SwarmDetail>(swarmKeys.one(s.id), (old) => (old ? { ...old, swarm: s } : old))
}

function patchDetail(qc: QueryClient, swarmId: string, patch: (d: SwarmDetail) => SwarmDetail) {
  qc.setQueryData<SwarmDetail>(swarmKeys.one(swarmId), (old) => (old ? patch(old) : old))
}

export function useCreateSwarm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SwarmCreate) => api.post<SwarmDetail>('/swarms', body),
    onSuccess: (d) => {
      qc.setQueryData(swarmKeys.one(d.swarm.id), d)
      setSwarm(qc, d.swarm)
    },
    onError: failed('Could not create the swarm'),
  })
}

export function useUpdateSwarm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...patch }: SwarmUpdate & { id: string }) => api.patch<Swarm>(`/swarms/${id}`, patch),
    onSuccess: (s) => setSwarm(qc, s),
    onError: failed('Could not change the swarm'),
  })
}

export function useDeleteSwarm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/swarms/${id}`),
    onSuccess: (_r, id) => {
      qc.setQueryData<Swarm[]>(swarmKeys.all, (old) => old?.filter((s) => s.id !== id))
      qc.removeQueries({ queryKey: swarmKeys.one(id) })
    },
    onError: failed('Could not delete the swarm'),
  })
}

/** Start, pause (running sessions finish) or stop (everything now). */
export function useSwarmControl() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'start' | 'pause' | 'stop' }) => api.post<Swarm>(`/swarms/${id}/${action}`, {}),
    onSuccess: (s) => setSwarm(qc, s),
    onError: failed('Could not change the swarm'),
  })
}

export function useMessageSwarm() {
  return useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) => api.post<void>(`/swarms/${id}/message`, { text }),
    onSuccess: () => toast.info('Sent to the Foundress', 'It reads it at its next planning, which starts now.'),
    onError: failed('Could not send it'),
  })
}

export function useReplyInbox() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ swarmId, entryId, ...body }: SwarmInboxReply & { swarmId: string; entryId: string }) =>
      api.post<SwarmInboxEntry>(`/swarms/${swarmId}/inbox/${entryId}`, body),
    onSuccess: (e) => patchDetail(qc, e.swarm_id, (d) => ({ ...d, inbox: upsertById(d.inbox, e, true) })),
    onError: failed('Could not answer'),
  })
}

export function useAddAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ swarmId, ...body }: SwarmAgentSpec & { swarmId: string }) => api.post<SwarmAgent>(`/swarms/${swarmId}/agents`, body),
    onSuccess: (a) => patchDetail(qc, a.swarm_id, (d) => ({ ...d, agents: upsertById(d.agents, a) })),
    onError: failed('Could not add the agent'),
  })
}

export function useUpdateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ swarmId, agentId, ...body }: SwarmAgentUpdate & { swarmId: string; agentId: string }) =>
      api.patch<SwarmAgent>(`/swarms/${swarmId}/agents/${agentId}`, body),
    onSuccess: (a) => patchDetail(qc, a.swarm_id, (d) => ({ ...d, agents: upsertById(d.agents, a) })),
    onError: failed('Could not change the agent'),
  })
}

export function useRemoveAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ swarmId, agentId }: { swarmId: string; agentId: string }) => api.del(`/swarms/${swarmId}/agents/${agentId}`),
    onSuccess: (_r, { swarmId, agentId }) => patchDetail(qc, swarmId, (d) => ({ ...d, agents: d.agents.filter((a) => a.id !== agentId) })),
    onError: failed('Could not remove the agent'),
  })
}

/** Apply a pushed swarm frame. What needs the owner (a question, a permission, a report, a pause) notifies. */
export function dispatchSwarm(qc: QueryClient, ev: SwarmServerEvent, open: (path: string) => void) {
  switch (ev.type) {
    case 'swarm.update': {
      const before = qc.getQueryData<Swarm[]>(swarmKeys.all)?.find((s) => s.id === ev.swarm.id)
      setSwarm(qc, ev.swarm)
      const s = ev.swarm
      if (before && before.status !== s.status && (s.status === 'done' || (s.status === 'paused' && s.status_reason))) {
        tell(s.status === 'done' ? `“${s.name}” reached its goal` : `“${s.name}” paused`, s.status_reason ?? '', s.id, open)
      }
      return
    }
    case 'swarm.removed':
      qc.setQueryData<Swarm[]>(swarmKeys.all, (old) => old?.filter((s) => s.id !== ev.id))
      qc.removeQueries({ queryKey: swarmKeys.one(ev.id) })
      return
    case 'swarm.agent':
      return patchDetail(qc, ev.agent.swarm_id, (d) => ({ ...d, agents: upsertById(d.agents, ev.agent) }))
    case 'swarm.item':
      return patchDetail(qc, ev.item.swarm_id, (d) => ({ ...d, items: upsertById(d.items, ev.item) }))
    case 'swarm.inbox': {
      const e = ev.entry
      const known = qc.getQueryData<SwarmDetail>(swarmKeys.one(e.swarm_id))?.inbox.some((x) => x.id === e.id)
      patchDetail(qc, e.swarm_id, (d) => ({ ...d, inbox: upsertById(d.inbox, e, true) }))
      if (!known && e.status === 'open') {
        const name = qc.getQueryData<Swarm[]>(swarmKeys.all)?.find((s) => s.id === e.swarm_id)?.name ?? 'A swarm'
        tell(e.kind === 'question' ? `“${name}” has a question` : `“${name}” needs your permission`, e.text, e.swarm_id, open, 'warning')
      }
      return
    }
    case 'swarm.event':
      return patchDetail(qc, ev.event.swarm_id, (d) => ({
        ...d,
        events: d.events.some((x) => x.seq === ev.event.seq) ? d.events : [...d.events, ev.event].slice(-MAX_EVENTS),
      }))
  }
}

function tell(title: string, body: string, swarmId: string, open: (path: string) => void, tone: 'info' | 'warning' = 'info') {
  const path = `/swarm/${swarmId}`
  const text = body.length > 160 ? `${body.slice(0, 157)}…` : body
  if (away()) notifySystem({ title, body: text, tag: `swarm-${swarmId}`, path })
  else if (window.location.pathname !== path) {
    toast({ title, description: text, tone, duration: 9000, action: { label: 'Open', onClick: () => open(path) } })
  }
}
