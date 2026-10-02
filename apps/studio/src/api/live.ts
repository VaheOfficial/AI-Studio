import { useEffect } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { create } from 'zustand'
import { dispatchGame } from './game'
import { dispatchImagePreview } from './image'
import { qk } from './keys'
import { socket, type SocketStatus } from './socket'
import { dispatchWorkspace } from './workspace'
import { automationRunOf, dispatchAutomation } from './automations'
import { away, notifySystem, onNotificationOpen } from '../lib/notify'
import { dispatchConnector } from './connectors'
import type {
  AgentEvent,
  AgentMessage,
  AgentSession,
  CatalogEntry,
  InstalledModel,
  Job,
  Output,
  RuntimeInfo,
  ServerEvent,
  SystemInfo,
  ToolCall,
} from './types'

export interface LogLine {
  id: number
  level: 'debug' | 'info' | 'warn' | 'error'
  source: string
  message: string
  ts: string
}

/** An agent turn in flight (or just finished, until the persisted session replaces it). */
export interface Turn {
  user_message: AgentMessage
  message: AgentMessage
  streaming: boolean
  /** The latest note about trimming/summarizing to fit the context window. */
  contextNote?: string
  /** The tool call the model is writing right now (it becomes a card when its step ends). */
  draft?: { name: string; chars: number }
  /** The turn's stopwatch: when it began (ms), and the time spent waiting for the user, which is not work. */
  startedAt: number
  waitedMs: number
  /** Set while a call waits for the user's approval or answer: since when (ms). */
  waitingSince?: number
}

/** A turn's stopwatch, as the chat shows it while the turn runs. */
export type TurnClock = Pick<Turn, 'startedAt' | 'waitedMs' | 'waitingSince'>

interface LiveState {
  status: SocketStatus
  /** True once the first `hello` snapshot arrived — until then lists are unknown, not empty. */
  synced: boolean
  version?: string
  system?: SystemInfo
  jobs: Job[]
  models: InstalledModel[]
  runtimes: RuntimeInfo[]
  logs: LogLine[]
  turns: Record<string, Turn>
  /** Records a job returned by a REST call. Pushed state is newer, so a job the socket already delivered is kept. */
  upsertJob: (job: Job) => void
  removeJob: (id: string) => void
  upsertModel: (model: InstalledModel) => void
  removeModel: (id: string) => void
  upsertRuntime: (runtime: RuntimeInfo) => void
  clearLogs: () => void
}

const MAX_LOGS = 2000
let logId = 0

const upsert = <T extends { id: string }>(list: T[], item: T, prepend = false) => {
  const i = list.findIndex((x) => x.id === item.id)
  if (i === -1) return prepend ? [item, ...list] : [...list, item]
  const next = list.slice()
  next[i] = item
  return next
}

export const useLive = create<LiveState>((set) => ({
  status: 'closed',
  synced: false,
  jobs: [],
  models: [],
  runtimes: [],
  logs: [],
  turns: {},
  upsertJob: (job) => set((s) => (s.jobs.some((j) => j.id === job.id) ? s : { jobs: [job, ...s.jobs] })),
  removeJob: (id) => set((s) => ({ jobs: s.jobs.filter((j) => j.id !== id) })),
  upsertModel: (model) => set((s) => ({ models: upsert(s.models, model) })),
  removeModel: (id) => set((s) => ({ models: s.models.filter((m) => m.id !== id) })),
  upsertRuntime: (runtime) => set((s) => ({ runtimes: upsert(s.runtimes, runtime) })),
  clearLogs: () => set({ logs: [] }),
}))

/* ------------------------------ selectors ------------------------------ */

export const useJob = (id: string | undefined) => useLive((s) => (id ? s.jobs.find((j) => j.id === id) : undefined))

/* ------------------------------ agent turns ----------------------------- */

const now = () => new Date().toISOString()
const tmpId = () => `tmp-${Math.random().toString(36).slice(2)}`

function patchCall(m: AgentMessage, id: string, fn: (c: ToolCall) => ToolCall): AgentMessage {
  return { ...m, tool_calls: (m.tool_calls ?? []).map((c) => (c.id === id ? fn(c) : c)) }
}

/** Pure reducer: one agent event applied to the assistant message being streamed. */
function applyToMessage(m: AgentMessage, ev: AgentEvent): AgentMessage {
  switch (ev.type) {
    case 'message.start':
      return { ...m, id: ev.message_id }
    case 'text.delta':
      return { ...m, content: m.content + ev.text }
    case 'thinking.delta': {
      const parts = m.thinking_parts ?? []
      const open = parts.find((p) => p.seq === ev.seq)
      return {
        ...m,
        thinking: (m.thinking ?? '') + ev.text,
        thinking_parts: open
          ? parts.map((p) => (p === open ? { ...p, text: p.text + ev.text } : p))
          : [...parts, { at: ev.at, seq: ev.seq, text: ev.text }],
      }
    }
    case 'tool.call':
      return { ...m, tool_calls: [...(m.tool_calls ?? []).filter((c) => c.id !== ev.call.id), ev.call] }
    case 'tool.approval':
      return patchCall(m, ev.call_id, (c) => ({ ...c, status: 'pending_approval' }))
    case 'tool.result':
      return patchCall(m, ev.call_id, (c) => ({
        ...c,
        status: c.status === 'denied' ? 'denied' : ev.ok ? 'done' : 'error',
        output: ev.output,
        artifacts: ev.artifacts,
        display: ev.display ?? c.display,
      }))
    case 'tool.progress':
      return patchCall(m, ev.call_id, (c) => ({ ...c, display: ev.display }))
    case 'error':
      return { ...m, content: m.content || `_${ev.message}_` }
    case 'usage':
      return { ...m, cost: ev.total }
    case 'speed':
      return { ...m, output_tokens: ev.output_tokens, generation_s: ev.generation_s }
    case 'tokens':
      return { ...m, usage: ev.usage }
    default:
      return m
  }
}

function emptyAssistant(): AgentMessage {
  return { id: tmpId(), role: 'assistant', content: '', tool_calls: [], created_at: now() }
}

const waitsForUser = (m: AgentMessage) => (m.tool_calls ?? []).some((c) => c.status === 'pending_approval' || c.status === 'awaiting_input')

/** Keeps the stopwatch honest: time a call spends waiting for the user is set aside. */
function keepClock(t: Turn): Turn {
  const waiting = t.streaming && waitsForUser(t.message)
  if (waiting && t.waitingSince == null) return { ...t, waitingSince: Date.now() }
  if (!waiting && t.waitingSince != null) return { ...t, waitingSince: undefined, waitedMs: t.waitedMs + (Date.now() - t.waitingSince) }
  return t
}

function setTurn(sessionId: string, fn: (t: Turn | undefined) => Turn | undefined) {
  useLive.setState((s) => {
    const changed = fn(s.turns[sessionId])
    const next = changed && keepClock(changed)
    const turns = { ...s.turns }
    if (next) turns[sessionId] = next
    else delete turns[sessionId]
    return { turns }
  })
}

/** Swap a finished turn for the persisted messages without a flash of missing content. */
async function settleTurn(qc: QueryClient, sessionId: string) {
  await qc.invalidateQueries({ queryKey: qk.session(sessionId) })
  setTurn(sessionId, (t) => (t && !t.streaming ? undefined : t))
}

const sendRef = (sessionId: string) => `send:${sessionId}`

export const agent = {
  /** Starts a turn; shows the user's message immediately. `images`: URLs from `POST /agent/images`. Returns false
   *  when offline. */
  send(sessionId: string, content: string, images: string[] = []): boolean {
    const ok = socket.send({ type: 'agent.send', session_id: sessionId, content, images, ref: sendRef(sessionId) })
    if (!ok) {
      toast.error('Not connected', 'The studio server is unreachable — your message was not sent.')
      return false
    }
    setTurn(sessionId, () => ({
      user_message: { id: tmpId(), role: 'user', content, images: images.length ? images : undefined, created_at: now() },
      message: emptyAssistant(),
      streaming: true,
      startedAt: Date.now(),
      waitedMs: 0,
    }))
    return true
  },
  approve(sessionId: string, callId: string, approved: boolean) {
    const ok = socket.send({ type: 'agent.approve', session_id: sessionId, call_id: callId, approved, ref: `approve:${callId}` })
    if (!ok) return toast.error('Not connected', 'Your answer was not sent — try again once reconnected.')
    setTurn(sessionId, (t) =>
      t && { ...t, message: patchCall(t.message, callId, (c) => ({ ...c, status: approved ? 'running' : 'denied' })) },
    )
  },
  /** Answers an `ask_user` question; the turn continues with it. */
  answer(sessionId: string, callId: string, answer: string) {
    const ok = socket.send({ type: 'agent.answer', session_id: sessionId, call_id: callId, answer, ref: `answer:${callId}` })
    if (!ok) return toast.error('Not connected', 'Your answer was not sent — try again once reconnected.')
    setTurn(sessionId, (t) =>
      t && {
        ...t,
        message: patchCall(t.message, callId, (c) => ({
          ...c,
          status: 'running',
          display: c.display?.kind === 'question' ? { ...c.display, answer } : c.display,
        })),
      },
    )
  },
  stop(sessionId: string) {
    socket.send({ type: 'agent.stop', session_id: sessionId })
  },
}

/* ------------------------------ dispatcher ------------------------------ */

function prependOutputs(qc: QueryClient, outputs: Output[]) {
  for (const o of outputs) {
    // Prefix match: also reaches longer keys under the same kind (e.g. the image gallery)
    for (const key of [qk.outputs(o.kind), qk.outputs()]) {
      qc.setQueriesData<Output[]>({ queryKey: key }, (old) => (old && !old.some((x) => x.id === o.id) ? [o, ...old] : old))
    }
  }
}

function setCatalogInstalled(qc: QueryClient, catalogId: string, installed: boolean) {
  qc.setQueryData<CatalogEntry[]>(qk.catalog, (old) => old?.map((e) => (e.id === catalogId ? { ...e, installed } : e)))
}

function handleJob(qc: QueryClient, job: Job) {
  const prev = useLive.getState().jobs.find((j) => j.id === job.id)
  useLive.setState((s) => ({ jobs: upsert(s.jobs, job, true) }))
  if (prev?.status === job.status) return
  if (job.status === 'error') toast.error(`${job.title} failed`, job.error ?? job.message)
  if (job.status !== 'done') return
  if (job.kind === 'download') toast.success('Installed', job.title)
  if (job.kind === 'env') toast.success('Runtime ready', job.title)
  if (job.kind === 'storage') {
    toast.success('Models moved', job.message)
    void qc.invalidateQueries({ queryKey: ['storage'] })
  }
  if (job.result?.outputs.length) prependOutputs(qc, job.result.outputs)
  // New voice presets / chat models appear when their model finishes installing
  if (job.kind === 'download') {
    void qc.invalidateQueries({ queryKey: qk.voiceProfiles })
    void qc.invalidateQueries({ queryKey: qk.chatModels })
    void qc.invalidateQueries({ queryKey: qk.hubRepos }) // "Installed" markers on hub variants
  }
}

/** Runtimes whose state the hub's local-backends summary reports. */
const TEXT_BACKENDS = new Set(['lmstudio', 'llamacpp', 'ollama'])

/** Replies that took at least this long are announced when they finish while the user is elsewhere. */
const LONG_TURN_MS = 20_000

/**
 * A chat wants the user, or finished something long, while they are not looking at it: a system notification when
 * the app is not in front, a toast with a way there when they are in another part of the app. An automation's run
 * is left to `automation.run`, which says the same with the automation's name.
 */
function tell(qc: QueryClient, sessionId: string, note: { title: (chat: string) => string; body?: string; tone: 'info' | 'warning' | 'error' }) {
  const session = qc.getQueryData<AgentSession[]>(qk.sessions)?.find((x) => x.id === sessionId)
  const turn = useLive.getState().turns[sessionId]
  if (turn && automationRunOf(turn.user_message.content)) return
  const title = note.title(session?.title && session.title !== 'New chat' ? `“${session.title}”` : 'A chat')
  const path = `/chat/${sessionId}`
  if (away()) notifySystem({ title, body: note.body, tag: `chat-${sessionId}`, path })
  else if (window.location.pathname !== path) {
    toast({ title, description: note.body, tone: note.tone, duration: 9000, action: { label: 'Open chat', onClick: () => openSession(path) } })
  }
}

const plain = (text: string) => text.replace(/[#*_`>]+/g, '').replace(/\s+/g, ' ').trim()

function announce(qc: QueryClient, sessionId: string, ev: AgentEvent) {
  const turn = useLive.getState().turns[sessionId]
  switch (ev.type) {
    case 'tool.approval': {
      const call = turn?.message.tool_calls?.find((c) => c.id === ev.call_id)
      const what = call ? (typeof call.args.command === 'string' ? `Run: ${call.args.command}` : call.name.replaceAll('_', ' ')) : undefined
      return tell(qc, sessionId, { title: (chat) => `${chat} needs your approval`, body: what, tone: 'warning' })
    }
    case 'tool.call':
      if (ev.call.status === 'awaiting_input' && ev.call.display?.kind === 'question') {
        tell(qc, sessionId, { title: (chat) => `${chat} has a question for you`, body: ev.call.display.question, tone: 'warning' })
      }
      return
    case 'error':
      if (away()) tell(qc, sessionId, { title: (chat) => `${chat} stopped with an error`, body: ev.message, tone: 'error' })
      return
    case 'done':
      if (turn?.streaming && Date.now() - turn.startedAt >= LONG_TURN_MS) {
        tell(qc, sessionId, { title: (chat) => `${chat} is done`, body: plain(turn.message.content).slice(-200) || undefined, tone: 'info' })
      }
      return
  }
}

function handleAgent(qc: QueryClient, sessionId: string, ev: AgentEvent) {
  switch (ev.type) {
    case 'turn.start':
      setTurn(sessionId, (t) => ({
        user_message: ev.user_message,
        message: t?.message ?? emptyAssistant(),
        streaming: true,
        startedAt: t?.startedAt ?? Date.now(),
        waitedMs: t?.waitedMs ?? 0,
      }))
      void qc.invalidateQueries({ queryKey: qk.sessions })
      return
    case 'tool.draft':
      setTurn(sessionId, (t) => t && { ...t, draft: { name: ev.name, chars: ev.chars } })
      return
    case 'title':
      qc.setQueryData<AgentSession[]>(qk.sessions, (old) => old?.map((x) => (x.id === sessionId ? { ...x, title: ev.title } : x)))
      return
    case 'tool.result':
      if (ev.artifacts?.length) prependOutputs(qc, ev.artifacts)
      break
    case 'error':
      toast.error('Agent error', ev.message)
      break
    case 'context':
      qc.setQueryData<AgentSession>(qk.session(sessionId), (old) => old && { ...old, context: ev.usage })
      if (ev.note) setTurn(sessionId, (t) => t && { ...t, contextNote: ev.note })
      return
  }
  announce(qc, sessionId, ev)
  // Whatever comes next, the call that was being written is either on the page now or abandoned
  setTurn(sessionId, (t) => t && { ...t, draft: undefined, message: applyToMessage(t.message, ev) })
  if (ev.type === 'done' || ev.type === 'error') {
    setTurn(sessionId, (t) => t && { ...t, streaming: false })
    void settleTurn(qc, sessionId)
  }
}

function handleHello(qc: QueryClient, ev: Extract<ServerEvent, { type: 'hello' }>) {
  const { snapshot } = ev
  const before = useLive.getState().turns
  const turns: Record<string, Turn> = {}
  for (const t of snapshot.active_turns) {
    // The stopwatch of a turn found running starts from the time the server says it has worked so far
    turns[t.session_id] = {
      user_message: t.user_message,
      message: t.message,
      streaming: true,
      startedAt: Date.now() - (t.message.elapsed_s ?? 0) * 1000,
      waitedMs: 0,
      waitingSince: waitsForUser(t.message) ? Date.now() : undefined,
    }
  }
  useLive.setState({
    synced: true,
    version: ev.version,
    system: snapshot.system,
    jobs: snapshot.jobs,
    models: snapshot.models,
    runtimes: snapshot.runtimes,
    turns,
  })
  // Turns that finished while we were disconnected: load their persisted result
  for (const id of Object.keys(before)) if (!turns[id]) void qc.invalidateQueries({ queryKey: qk.session(id) })
  // On-demand REST data may have changed while offline
  void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'session' })
}

function dispatch(qc: QueryClient, ev: ServerEvent) {
  const live = useLive.getState()
  switch (ev.type) {
    case 'hello':
      return handleHello(qc, ev)
    case 'system':
      return useLive.setState({ system: ev.system })
    case 'job.update':
      return handleJob(qc, ev.job)
    case 'model.update':
      if (!live.models.some((m) => m.id === ev.model.id)) setCatalogInstalled(qc, ev.model.catalog_id, true)
      return live.upsertModel(ev.model)
    case 'model.removed':
      setCatalogInstalled(qc, ev.id, false)
      void qc.invalidateQueries({ queryKey: qk.chatModels })
      void qc.invalidateQueries({ queryKey: qk.hubRepos })
      return live.removeModel(ev.id)
    case 'runtime.update':
      if (TEXT_BACKENDS.has(ev.runtime.id)) {
        void qc.invalidateQueries({ queryKey: qk.localBackends })
        void qc.invalidateQueries({ queryKey: qk.chatModels }) // availability follows the engine's install state
      }
      return live.upsertRuntime(ev.runtime)
    case 'log':
      return useLive.setState((s) => ({
        logs: [...s.logs.slice(-(MAX_LOGS - 1)), { id: ++logId, level: ev.level, source: ev.source, message: ev.message, ts: ev.ts }],
      }))
    case 'agent':
      return handleAgent(qc, ev.session_id, ev.event)
    case 'image.preview':
      return dispatchImagePreview(ev)
    case 'game.delta':
    case 'game.turn':
    case 'game.error':
    case 'game.media':
      return dispatchGame(qc, ev)
    case 'openrouter.account':
      qc.setQueryData(qk.openrouterAccount, ev.account)
      return
    case 'automation.update':
    case 'automation.removed':
    case 'automation.run':
      return dispatchAutomation(qc, ev, (sessionId) => openSession(`/chat/${sessionId}`))
    case 'connector.update':
    case 'connector.removed':
      return dispatchConnector(qc, ev)
    case 'error':
      if (ev.ref?.startsWith('send:')) setTurn(ev.ref.slice('send:'.length), () => undefined)
      toast.error('Request failed', ev.message)
      return
    default:
      return dispatchWorkspace(qc, ev)
  }
}

/** Mount once near the app root: opens the socket and routes every server event into state. */
// In-app navigation for events that link somewhere (a notification opening a chat); set by useRealtime
let openSession: (path: string) => void = (path) => window.location.assign(path)

export function useRealtime() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  useEffect(() => {
    openSession = (path) => void navigate(path)
    onNotificationOpen(openSession)
  }, [navigate])
  useEffect(() => {
    const offStatus = socket.onStatus((status) => useLive.setState({ status }))
    const offEvent = socket.onEvent((ev) => dispatch(qc, ev))
    const release = socket.acquire()
    return () => {
      release()
      offEvent()
      offStatus()
    }
  }, [qc])
}
