/**
 * Agent workspace client: REST hooks (React Query) plus the handlers that apply pushed workspace frames
 * (`dispatchWorkspace`, called from the socket dispatcher in live.ts). High-rate streams — terminal output
 * and browser frames — bypass React state and go to small per-id stores the views subscribe to.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from './client'
import { socket } from './socket'
import type {
  AgentTask,
  BrowserInput,
  BrowserSnapshot,
  BrowserState,
  FolderListing,
  FsFile,
  FsListing,
  TerminalBuffer,
  TerminalInfo,
  WorkspaceServerEvent,
  WorkspaceState,
} from './contracts/workspace'

const onError = (title: string) => (e: Error) => toast.error(title, e.message)
const enc = encodeURIComponent

export const wk = {
  state: (sid: string) => ['workspace', sid] as const,
  folders: (path: string) => ['workspace-folders', path] as const,
  dir: (sid: string, path: string) => ['workspace-fs', sid, 'dir', path] as const,
  file: (sid: string, path: string) => ['workspace-fs', sid, 'file', path] as const,
  fs: (sid: string) => ['workspace-fs', sid] as const,
  terminals: (sid: string) => ['workspace-terminals', sid] as const,
  browser: (sid: string) => ['workspace-browser', sid] as const,
  tasks: ['workspace-tasks'] as const,
}

/* --------------------------------- folder --------------------------------- */

export const useWorkspaceState = (sid: string | undefined) =>
  useQuery({
    queryKey: wk.state(sid ?? ''),
    queryFn: () => api.get<WorkspaceState>(`/workspace/sessions/${sid}`),
    enabled: !!sid,
  })

export function useSetRoot() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ sid, root }: { sid: string; root: string }) => api.put<WorkspaceState>(`/workspace/sessions/${sid}`, { root }),
    onSuccess: (st) => {
      qc.setQueryData(wk.state(st.session_id), st)
      void qc.invalidateQueries({ queryKey: wk.fs(st.session_id) })
    },
    onError: onError('Could not use that folder'),
  })
}

export const useFolders = (path: string, enabled: boolean) =>
  useQuery({ queryKey: wk.folders(path), queryFn: () => api.get<FolderListing>(`/workspace/browse?path=${enc(path)}`), enabled })

export function useMakeFolder() {
  return useMutation({
    mutationFn: (body: { parent: string; name: string }) => api.post<FolderListing>('/workspace/browse/mkdir', body),
    onError: onError('Could not create the folder'),
  })
}

/* ---------------------------------- files ---------------------------------- */

export const useDir = (sid: string, path: string, enabled: boolean) =>
  useQuery({
    queryKey: wk.dir(sid, path),
    queryFn: () => api.get<FsListing>(`/workspace/sessions/${sid}/fs?path=${enc(path)}`),
    enabled,
  })

export const useFile = (sid: string, path: string | undefined) =>
  useQuery({
    queryKey: wk.file(sid, path ?? ''),
    queryFn: () => api.get<FsFile>(`/workspace/sessions/${sid}/fs/file?path=${enc(path ?? '')}`),
    enabled: !!path,
  })

export function useSaveFile(sid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { path: string; content: string }) => api.put<FsFile>(`/workspace/sessions/${sid}/fs/file`, body),
    onSuccess: (f) => {
      qc.setQueryData(wk.file(sid, f.path), f)
      toast.success('Saved', f.path)
    },
    onError: onError('Could not save'),
  })
}

/* -------------------------------- terminals -------------------------------- */

export const useTerminals = (sid: string) =>
  useQuery({
    queryKey: wk.terminals(sid),
    queryFn: async () => {
      const buffers = await api.get<TerminalBuffer[]>(`/workspace/sessions/${sid}/terminals`)
      for (const b of buffers) terminalOutput.seed(b)
      return buffers.map((b) => b.terminal)
    },
  })

type OutputListener = (data: string) => void

/**
 * Terminal output by terminal id. `seed` takes the REST scrollback; live frames carry their start offset
 * (`seq`), so overlap with the seeded scrollback is trimmed and nothing is written twice.
 */
export const terminalOutput = (() => {
  const LIMIT = 400_000
  const bufs = new Map<string, { data: string; end: number }>()
  const listeners = new Map<string, Set<OutputListener>>()
  const emit = (id: string, data: string) => listeners.get(id)?.forEach((fn) => fn(data))
  return {
    seed(b: TerminalBuffer) {
      const cur = bufs.get(b.terminal.id)
      if (cur && cur.end >= b.seq) return
      bufs.set(b.terminal.id, { data: b.data, end: b.seq })
      emit(b.terminal.id, cur ? b.data.slice(Math.max(0, b.data.length - (b.seq - cur.end))) : b.data)
    },
    append(id: string, data: string, seq: number) {
      const cur = bufs.get(id) ?? { data: '', end: seq }
      if (seq + data.length <= cur.end) return
      const fresh = data.slice(Math.max(0, cur.end - seq))
      bufs.set(id, { data: (cur.data + fresh).slice(-LIMIT), end: seq + data.length })
      emit(id, fresh)
    },
    read: (id: string) => bufs.get(id)?.data ?? '',
    subscribe(id: string, fn: OutputListener) {
      let set = listeners.get(id)
      if (!set) listeners.set(id, (set = new Set()))
      set.add(fn)
      return () => void set.delete(fn)
    },
    drop(id: string) {
      bufs.delete(id)
      listeners.delete(id)
    },
  }
})()

export const terminal = {
  open: (sid: string, cols: number, rows: number) => sendOrWarn({ type: 'terminal.open', session_id: sid, cols, rows }),
  input: (id: string, data: string) => socket.send({ type: 'terminal.input', id, data }),
  resize: (id: string, cols: number, rows: number) => socket.send({ type: 'terminal.resize', id, cols, rows }),
  close: (id: string) => socket.send({ type: 'terminal.close', id }),
}

function sendOrWarn(message: Parameters<typeof socket.send>[0]) {
  if (!socket.send(message)) toast.error('Not connected', 'The studio server is unreachable.')
}

/* --------------------------------- browser --------------------------------- */

export const useBrowser = (sid: string) =>
  useQuery({ queryKey: wk.browser(sid), queryFn: () => api.get<BrowserSnapshot>(`/workspace/sessions/${sid}/browser`) })

function useBrowserAction<B>(sid: string, path: string, title: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: B) => api.post<BrowserState>(`/workspace/sessions/${sid}/browser/${path}`, body),
    onSuccess: (state) => qc.setQueryData<BrowserSnapshot>(wk.browser(sid), (old) => ({ state, console: old?.console ?? [] })),
    onError: onError(title),
  })
}

export const useNavigate = (sid: string) => useBrowserAction<{ url: string }>(sid, 'navigate', 'Could not open the page')
export const useHistory = (sid: string) =>
  useBrowserAction<{ action: 'back' | 'forward' | 'reload' }>(sid, 'history', 'Browser action failed')
export const useTakeover = (sid: string) => useBrowserAction<{ on: boolean }>(sid, 'takeover', 'Could not change control')

interface Frame {
  src: string
  width: number
  height: number
}

/** Latest live-view frame per session (only arrives while `browser.watch` is on). */
export const browserFrames = (() => {
  const frames = new Map<string, Frame>()
  const listeners = new Map<string, Set<() => void>>()
  return {
    set(sid: string, f: Frame) {
      frames.set(sid, f)
      listeners.get(sid)?.forEach((fn) => fn())
    },
    get: (sid: string) => frames.get(sid),
    subscribe(sid: string, fn: () => void) {
      let set = listeners.get(sid)
      if (!set) listeners.set(sid, (set = new Set()))
      set.add(fn)
      return () => void set.delete(fn)
    },
  }
})()

export const browserLive = {
  watch: (sid: string, watching: boolean) => socket.send({ type: 'browser.watch', session_id: sid, watching }),
  input: (sid: string, input: BrowserInput) => socket.send({ type: 'browser.input', session_id: sid, input }),
}

/* ---------------------------------- tasks ---------------------------------- */

export const useTasks = () => useQuery({ queryKey: wk.tasks, queryFn: () => api.get<AgentTask[]>('/workspace/tasks') })

function useTaskAction(action: 'cancel' | 'retry') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<AgentTask>(`/workspace/tasks/${id}/${action}`),
    onSuccess: (t) => upsertTask(qc, t),
    onError: onError(action === 'cancel' ? 'Could not stop the task' : 'Could not retry the task'),
  })
}

export const useCancelTask = () => useTaskAction('cancel')
export const useRetryTask = () => useTaskAction('retry')

export function useCreateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { origin_session_id: string; prompt: string; title?: string }) => api.post<AgentTask>('/workspace/tasks', body),
    onSuccess: (t) => {
      upsertTask(qc, t)
      void qc.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: onError('Could not start the task'),
  })
}

export function useDeleteTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/workspace/tasks/${id}`),
    onMutate: (id) => qc.setQueryData<AgentTask[]>(wk.tasks, (old) => old?.filter((t) => t.id !== id)),
    onError: onError('Could not remove the task'),
  })
}

function upsertTask(qc: QueryClient, task: AgentTask) {
  qc.setQueryData<AgentTask[]>(wk.tasks, (old) => {
    if (!old) return old
    return old.some((t) => t.id === task.id) ? old.map((t) => (t.id === task.id ? task : t)) : [task, ...old]
  })
}

/* ------------------------------- push handler ------------------------------- */

function patchTerminals(qc: QueryClient, sid: string, fn: (list: TerminalInfo[]) => TerminalInfo[]) {
  qc.setQueryData<TerminalInfo[]>(wk.terminals(sid), (old) => (old ? fn(old) : old))
}

function findTerminalSession(qc: QueryClient, id: string): string | undefined {
  for (const [key, list] of qc.getQueriesData<TerminalInfo[]>({ queryKey: ['workspace-terminals'] })) {
    if (list?.some((t) => t.id === id)) return key[1] as string
  }
  return undefined
}

function notifyTask(prev: AgentTask | undefined, task: AgentTask) {
  if (prev?.status === task.status) return
  if (task.status === 'succeeded') toast.success('Task finished', task.title)
  else if (task.status === 'failed') toast.error('Task failed', `${task.title}: ${task.error ?? ''}`)
  else if (task.status === 'waiting_approval') toast.info('Task needs your approval', task.title)
  if (task.status === 'succeeded' && document.hidden && 'Notification' in window && Notification.permission === 'granted') {
    new Notification('Task finished', { body: task.title })
  }
}

/** Apply one pushed workspace frame to the caches/stores. */
export function dispatchWorkspace(qc: QueryClient, ev: WorkspaceServerEvent) {
  switch (ev.type) {
    case 'workspace.update':
      qc.setQueryData(wk.state(ev.state.session_id), ev.state)
      return
    case 'terminal.update':
      patchTerminals(qc, ev.terminal.session_id, (list) =>
        list.some((t) => t.id === ev.terminal.id) ? list.map((t) => (t.id === ev.terminal.id ? ev.terminal : t)) : [...list, ev.terminal],
      )
      return
    case 'terminal.output':
      terminalOutput.append(ev.id, ev.data, ev.seq)
      return
    case 'terminal.exit':
      return // the matching terminal.update carries the exit code
    case 'terminal.closed': {
      const sid = findTerminalSession(qc, ev.id)
      if (sid) patchTerminals(qc, sid, (list) => list.filter((t) => t.id !== ev.id))
      terminalOutput.drop(ev.id)
      return
    }
    case 'fs.change':
      for (const sid of ev.session_ids) void qc.invalidateQueries({ queryKey: wk.fs(sid) })
      return
    case 'browser.update':
      qc.setQueryData<BrowserSnapshot>(wk.browser(ev.state.session_id), (old) => ({ state: ev.state, console: old?.console ?? [] }))
      return
    case 'browser.frame':
      browserFrames.set(ev.session_id, { src: `data:image/jpeg;base64,${ev.data}`, width: ev.width, height: ev.height })
      return
    case 'browser.console':
      qc.setQueryData<BrowserSnapshot>(wk.browser(ev.session_id), (old) =>
        old ? { ...old, console: [...old.console.slice(-299), ev.entry] } : old,
      )
      return
    case 'task.update': {
      const prev = qc.getQueryData<AgentTask[]>(wk.tasks)?.find((t) => t.id === ev.task.id)
      notifyTask(prev, ev.task)
      upsertTask(qc, ev.task)
      return
    }
    case 'task.removed':
      qc.setQueryData<AgentTask[]>(wk.tasks, (old) => old?.filter((t) => t.id !== ev.id))
      return
  }
}
