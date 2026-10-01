import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from './client'
import type { Connector, ConnectorCreate, ConnectorServerEvent, ConnectorUpdate } from './contracts/connectors'

export const connectorKeys = { all: ['connectors'] as const }

export const useConnectors = () =>
  useQuery({ queryKey: connectorKeys.all, queryFn: () => api.get<Connector[]>('/connectors') })

const upsert = (qc: QueryClient, c: Connector) =>
  qc.setQueryData<Connector[]>(connectorKeys.all, (old) =>
    old ? (old.some((x) => x.id === c.id) ? old.map((x) => (x.id === c.id ? c : x)) : [...old, c]) : old,
  )

const failed = (title: string) => (e: Error) => toast.error(title, e.message)

export function useCreateConnector() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ConnectorCreate) => api.post<Connector>('/connectors', body),
    onSuccess: (c) => upsert(qc, c),
    onError: failed('Could not add the connector'),
  })
}

export function useUpdateConnector() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...patch }: ConnectorUpdate & { id: string }) => api.patch<Connector>(`/connectors/${id}`, patch),
    onSuccess: (c) => upsert(qc, c),
    onError: failed('Could not update the connector'),
  })
}

export function useDeleteConnector() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/connectors/${id}`),
    onMutate: (id) => qc.setQueryData<Connector[]>(connectorKeys.all, (old = []) => old.filter((c) => c.id !== id)),
    onError: failed('Could not remove the connector'),
  })
}

export function useTestConnector() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<Connector>(`/connectors/${id}/test`, {}),
    onSuccess: (c) => {
      upsert(qc, c)
      if (c.status === 'connected') toast.success(`${c.name} connected`, `${c.tools.length} tool${c.tools.length === 1 ? '' : 's'} available`)
      else toast.error(`${c.name} didn't connect`, c.error)
    },
    onError: failed('Could not test the connector'),
  })
}

export function dispatchConnector(qc: QueryClient, ev: ConnectorServerEvent) {
  if (ev.type === 'connector.update') upsert(qc, ev.connector)
  else qc.setQueryData<Connector[]>(connectorKeys.all, (old) => old?.filter((c) => c.id !== ev.id))
}
