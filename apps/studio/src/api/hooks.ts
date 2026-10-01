import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from './client'
import { qk } from './keys'
import { useLive } from './live'
import type {
  AgentMode,
  AgentSession,
  Capabilities,
  CatalogEntry,
  ChatModelOption,
  CompactRequest,
  CompactResult,
  InstalledModel,
  Job,
  Memory,
  MessageRef,
  ModelKind,
  MusicRequest,
  Output,
  OutputKind,
  PatchSessionRequest,
  RewindResult,
  RuntimeInfo,
  Settings,
  TranscribeResult,
} from './types'

const onError = (title: string) => (e: Error) => toast.error(title, e.message)

/* --------------------------- pushed state --------------------------- */
// System, jobs, models and runtimes arrive over the WebSocket (snapshot + events); never fetched here.

export const useModelsOfKind = (kind: ModelKind) => {
  const models = useLive((s) => s.models)
  return models.filter((m) => m.kind === kind)
}

/* ---------------------------- on-demand ----------------------------- */

export const useCatalog = () => useQuery({ queryKey: qk.catalog, queryFn: () => api.get<CatalogEntry[]>('/catalog') })

export const useSettings = () => useQuery({ queryKey: qk.settings, queryFn: () => api.get<Settings>('/settings') })

/** What this machine can do. Nothing is hidden until it loads, so a GPU machine never flashes "unavailable". */
export const useCapabilities = () =>
  useQuery({ queryKey: qk.capabilities, queryFn: () => api.get<Capabilities>('/capabilities'), staleTime: 300_000 })

export const useOutputs = (kind?: OutputKind) =>
  useQuery({
    queryKey: qk.outputs(kind),
    queryFn: () => api.get<Output[]>(`/outputs?limit=200${kind ? `&kind=${kind}` : ''}`),
  })

export const useChatModels = () =>
  useQuery({ queryKey: qk.chatModels, queryFn: () => api.get<ChatModelOption[]>('/chat/models') })

export const useSessions = () =>
  useQuery({ queryKey: qk.sessions, queryFn: () => api.get<AgentSession[]>('/agent/sessions') })

export const useSession = (id: string | undefined) =>
  useQuery({
    queryKey: qk.session(id ?? ''),
    queryFn: () => api.get<AgentSession>(`/agent/sessions/${id}`),
    enabled: !!id,
  })

/* ------------------------------ mutations ------------------------------ */
// Results are also pushed over the socket; patching the live store here just makes the UI instant.

const upsertJob = (job: Job) => useLive.getState().upsertJob(job)

export function useInstallModel() {
  return useMutation({
    mutationFn: (catalogId: string) => api.post<Job>(`/models/${encodeURIComponent(catalogId)}/install`),
    onSuccess: (job) => {
      upsertJob(job)
      toast.info('Download started', job.title)
    },
    onError: onError('Could not start install'),
  })
}

export function useDeleteModel() {
  return useMutation({
    mutationFn: (id: string) => api.del(`/models/${encodeURIComponent(id)}`),
    onSuccess: (_, id) => {
      useLive.getState().removeModel(id)
      toast.success('Model deleted')
    },
    onError: onError('Could not delete model'),
  })
}

export function useModelPower() {
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'load' | 'unload' }) =>
      api.post<InstalledModel>(`/models/${encodeURIComponent(id)}/${action}`),
    onSuccess: (m) => useLive.getState().upsertModel(m),
    onError: onError('Model action failed'),
  })
}

export function useCancelJob() {
  return useMutation({
    mutationFn: (id: string) => api.post<Job>(`/jobs/${id}/cancel`),
    onSuccess: upsertJob,
    onError: onError('Could not cancel'),
  })
}

export function useDismissJob() {
  return useMutation({
    mutationFn: (id: string) => api.del(`/jobs/${id}`),
    onMutate: (id) => useLive.getState().removeJob(id),
  })
}

export function useInstallRuntime() {
  return useMutation({
    mutationFn: (id: string) => api.post<Job>(`/runtimes/${id}/install`),
    onSuccess: upsertJob,
    onError: onError('Could not set up runtime'),
  })
}

export function useStopRuntime() {
  return useMutation({
    mutationFn: (id: string) => api.post<RuntimeInfo>(`/runtimes/${id}/stop`),
    onSuccess: (r) => useLive.getState().upsertRuntime(r),
    onError: onError('Could not stop runtime'),
  })
}

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<Settings>) => api.put<Settings>('/settings', patch),
    onSuccess: (s) => {
      qc.setQueryData(qk.settings, s)
      void qc.invalidateQueries({ queryKey: qk.capabilities })
      void qc.invalidateQueries({ queryKey: qk.chatModels })
      void qc.invalidateQueries({ queryKey: qk.openrouterAccount })
      toast.success('Settings saved')
    },
    onError: onError('Could not save settings'),
  })
}

/** Generation endpoints all return a Job; progress and outputs arrive over the socket. */
function useGenerate<B>(path: string, title: string) {
  return useMutation({
    mutationFn: (body: B) => api.post<Job>(path, body),
    onSuccess: upsertJob,
    onError: onError(title),
  })
}

export const useGenerateMusic = () => useGenerate<MusicRequest>('/music/generate', 'Music generation failed')

export function useTranscribe() {
  return useMutation({
    mutationFn: ({ file, modelId }: { file: Blob; modelId: string }) => {
      const form = new FormData()
      form.append('file', file, file instanceof File ? file.name : 'recording.webm')
      form.append('model_id', modelId)
      return api.upload<TranscribeResult>('/voice/transcribe', form)
    },
    onError: onError('Transcription failed'),
  })
}

export function useDeleteOutput() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/outputs/${id}`),
    onMutate: (id) => {
      qc.setQueriesData<Output[]>({ queryKey: ['outputs'] }, (old) => old?.filter((o) => o.id !== id))
    },
    onError: onError('Could not delete'),
  })
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { model: string; mode: AgentMode }) => api.post<AgentSession>('/agent/sessions', body),
    onSuccess: (s) => qc.setQueryData<AgentSession[]>(qk.sessions, (old = []) => [s, ...old]),
    onError: onError('Could not start chat'),
  })
}

export function useUpdateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: string } & PatchSessionRequest) =>
      api.patch<AgentSession>(`/agent/sessions/${id}`, patch),
    onSuccess: (s) => {
      qc.setQueryData<AgentSession[]>(qk.sessions, (old = []) => old.map((x) => (x.id === s.id ? { ...x, ...s } : x)))
      qc.setQueryData<AgentSession>(qk.session(s.id), (old) => (old ? { ...old, ...s, messages: old.messages } : old))
    },
  })
}

/** `/compact`: summarize the chat so far; the model's next turn starts from the summary. */
export function useCompactSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, focus }: { id: string; focus?: string }) =>
      api.post<CompactResult>(`/agent/sessions/${id}/compact`, { focus } satisfies CompactRequest),
    onSuccess: (r) => {
      qc.setQueryData<AgentSession>(qk.session(r.session.id), (old) => (old ? { ...old, ...r.session, messages: old.messages } : old))
    },
    onError: onError('Could not compact the chat'),
  })
}

export function useRewindSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, message_id }: { id: string } & MessageRef) =>
      api.post<RewindResult>(`/agent/sessions/${id}/rewind`, { message_id } satisfies MessageRef),
    onSuccess: (r) => qc.setQueryData(qk.session(r.session.id), r.session),
    onError: onError('Could not rewind'),
  })
}

export function useForkSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, message_id }: { id: string } & MessageRef) =>
      api.post<AgentSession>(`/agent/sessions/${id}/fork`, { message_id } satisfies MessageRef),
    onSuccess: (s) => {
      qc.setQueryData(qk.session(s.id), s)
      qc.setQueryData<AgentSession[]>(qk.sessions, (old = []) => [{ ...s, messages: undefined }, ...old])
    },
    onError: onError('Could not fork'),
  })
}

export function useDeleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/agent/sessions/${id}`),
    onMutate: (id) => qc.setQueryData<AgentSession[]>(qk.sessions, (old = []) => old.filter((s) => s.id !== id)),
  })
}

/* ------------------------------ memory ------------------------------ */

/** What the assistant remembers about the user across chats. */
export const useMemories = () => useQuery({ queryKey: qk.memories, queryFn: () => api.get<Memory[]>('/agent/memories') })

export function useAddMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => api.post<Memory>('/agent/memories', { text }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.memories }),
    onError: onError('Could not save the memory'),
  })
}

export function useDeleteMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/agent/memories/${id}`),
    onMutate: (id) => qc.setQueryData<Memory[]>(qk.memories, (old = []) => old.filter((m) => m.id !== id)),
    onError: onError('Could not delete the memory'),
  })
}
