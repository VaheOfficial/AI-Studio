import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { away, notifySystem } from '../lib/notify'
import { api } from './client'
import type { Automation, AutomationCreate, AutomationServerEvent, AutomationUpdate } from './contracts/automations'

export const automationKeys = { all: ['automations'] as const }

/**
 * The message that starts an automation's run in its chat is written by the server, not typed by the user
 * (`studio/automations.py`, `_instruction`): "[Scheduled automation “Title”, …] …" or "[Trigger “Title”, … found N
 * new items. …] …". Returns the automation's title and how the run came about, or undefined for any other message.
 */
export function automationRunOf(content: string): { title: string; trigger: boolean; items?: number } | undefined {
  const m = /^\[(Scheduled automation|Trigger) “([^”]*)”/.exec(content)
  if (!m) return undefined
  const items = /found (\d+) new item/.exec(content.slice(0, 400))
  return { title: m[2], trigger: m[1] === 'Trigger', items: items ? Number(items[1]) : undefined }
}

export const useAutomations = () =>
  useQuery({ queryKey: automationKeys.all, queryFn: () => api.get<Automation[]>('/automations') })

const upsert = (qc: QueryClient, a: Automation) =>
  qc.setQueryData<Automation[]>(automationKeys.all, (old) =>
    old ? (old.some((x) => x.id === a.id) ? old.map((x) => (x.id === a.id ? a : x)) : [a, ...old]) : old,
  )

const failed = (title: string) => (e: Error) => toast.error(title, e.message)

export function useCreateAutomation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AutomationCreate) => api.post<Automation>('/automations', body),
    onSuccess: (a) => upsert(qc, a),
    onError: failed('Could not create the automation'),
  })
}

export function useUpdateAutomation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...patch }: AutomationUpdate & { id: string }) => api.patch<Automation>(`/automations/${id}`, patch),
    onSuccess: (a) => upsert(qc, a),
    onError: failed('Could not update the automation'),
  })
}

export function useDeleteAutomation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/automations/${id}`),
    onMutate: (id) => qc.setQueryData<Automation[]>(automationKeys.all, (old = []) => old.filter((a) => a.id !== id)),
    onError: failed('Could not delete the automation'),
  })
}

export function useRunAutomation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<Automation>(`/automations/${id}/run`, {}),
    onSuccess: (a) => {
      upsert(qc, a)
      toast.info(`Running “${a.title}”`, 'The result appears in its chat.')
    },
    onError: failed('Could not run the automation'),
  })
}

/** Apply a pushed automation frame; a finished run notifies (a system notification when the app is not in front). */
export function dispatchAutomation(qc: QueryClient, ev: AutomationServerEvent, open: (sessionId: string) => void) {
  switch (ev.type) {
    case 'automation.update':
      upsert(qc, ev.automation)
      return
    case 'automation.removed':
      qc.setQueryData<Automation[]>(automationKeys.all, (old) => old?.filter((a) => a.id !== ev.id))
      return
    case 'automation.run': {
      const title = ev.status === 'error' ? `“${ev.title}” failed` : ev.status === 'needs_approval' ? `“${ev.title}” needs you` : ev.title
      const body = ev.message.length > 160 ? `${ev.message.slice(0, 157)}…` : ev.message
      toast({
        title,
        description: body,
        tone: ev.status === 'error' ? 'error' : ev.status === 'needs_approval' ? 'warning' : 'info',
        duration: 9000,
        action: { label: 'Open chat', onClick: () => open(ev.session_id) },
      })
      void qc.invalidateQueries({ queryKey: ['session', ev.session_id] })
      if (away()) notifySystem({ title, body, tag: `automation-${ev.automation_id}`, path: `/chat/${ev.session_id}` })
      return
    }
  }
}
