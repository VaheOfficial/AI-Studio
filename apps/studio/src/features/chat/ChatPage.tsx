import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowDown, ArrowUp, Globe, ListChecks, PanelRightOpen, SquareTerminal, Wrench } from 'lucide-react'
import { Aurora, CircuitField, ConfirmDialog, IconButton, Lightbox, Logo, ResizablePanels, Skeleton, toast } from '@studio/ui'
import { api, ApiError } from '../../api/client'
import type { ToolDisplay } from '../../api/contracts/workspace'
import {
  useChatModels,
  useCompactSession,
  useCreateSession,
  useForkSession,
  useOlderMessages,
  useRewindSession,
  useSession,
  useSettings,
  useUpdateSession,
} from '../../api/hooks'
import { qk } from '../../api/keys'
import { agent, useLive } from '../../api/live'
import type { AgentMessage, AgentMode, SessionTotals } from '../../api/types'
import { useSetRoot } from '../../api/workspace'
import { formatCount, formatTokens, formatUsage, tokensPerSecond } from '../../lib/format'
import { formatUsd } from '../../lib/money'
import { parseTokens } from './commands'
import { Composer } from './Composer'
import { useChatQueue, useConversationQueue } from './conversationQueue'
import { useChatLightbox } from './lightbox'
import { blockCount } from './blocks'
import { MessageView } from './MessageView'
import { useWorkspacePanel } from './workspace/panel'
import s from './ChatPage.module.css'

// Terminal (xterm) and editor (CodeMirror) are heavy: load the panel in its own chunk
const WorkspacePanel = lazy(() => import('./workspace/WorkspacePanel').then((m) => ({ default: m.WorkspacePanel })))

interface ThreadItem {
  key: string
  message: AgentMessage
  live: boolean
}

const SUGGESTIONS = [
  { icon: <SquareTerminal />, text: 'Create a small Python CLI in this folder, run it, and fix anything that fails' },
  { icon: <Globe />, text: 'Open news.ycombinator.com and summarize the top stories' },
  { icon: <ListChecks />, text: 'Plan and build a static landing page, then open it in the browser' },
  { icon: <Wrench />, text: 'What models can my machine run well?' },
]

type Diff = Extract<ToolDisplay, { kind: 'diff' }>

/** How far above the end of the thread (px) the way back to it is offered. */
const AWAY_GAP = 160

/** Blocks (messages, and the text, thinking and tool cards of replies) a chat opens with; each step up adds as many. */
const PAGE = 60

/** A block of the thread: the message it belongs to and its place in it. */
interface BlockRef {
  id: string
  skip: number
}

/** Where a block is in the thread, counted in blocks from its start; undefined when its message is not there. */
function offsetOf(items: ThreadItem[], counts: number[], at: BlockRef): number | undefined {
  let offset = 0
  for (let i = 0; i < items.length; i++) {
    if (items[i].message.id === at.id) return offset + Math.min(at.skip, counts[i] - 1)
    offset += counts[i]
  }
  return undefined
}

function refAt(items: ThreadItem[], counts: number[], offset: number): BlockRef | undefined {
  let start = 0
  for (let i = 0; i < items.length; i++) {
    if (offset < start + counts[i]) return { id: items[i].message.id, skip: offset - start }
    start += counts[i]
  }
  return undefined
}

type Stats = SessionTotals

const NO_STATS: Stats = { cost: 0, output_tokens: 0, generation_s: 0, usage: { requests: 0, input_tokens: 0, cached_tokens: 0, output_tokens: 0 } }

/** `base` with the usage of `messages` added (or taken away, `sign` -1). */
function addUp(base: Stats, messages: AgentMessage[], sign = 1): Stats {
  return messages.reduce<Stats>(
    (s, m) => ({
      cost: s.cost + sign * (m.cost ?? 0),
      output_tokens: s.output_tokens + sign * (m.output_tokens ?? 0),
      generation_s: s.generation_s + sign * (m.generation_s ?? 0),
      usage: {
        requests: s.usage.requests + sign * (m.usage?.requests ?? 0),
        input_tokens: s.usage.input_tokens + sign * (m.usage?.input_tokens ?? 0),
        cached_tokens: s.usage.cached_tokens + sign * (m.usage?.cached_tokens ?? 0),
        output_tokens: s.usage.output_tokens + sign * (m.usage?.output_tokens ?? 0),
      },
    }),
    base,
  )
}
/** Within this distance (px) of the top of a chat, earlier blocks are shown. */
const EARLIER_GAP = 1200

/**
 * Upload attachments: pictures go with the message (the model sees them), other files into the chat's workspace
 * folder. Returns the picture URLs and the text to append to the message for the files.
 */
async function attach(sid: string, files: File[]): Promise<{ images: string[]; suffix: string }> {
  const pictures = files.filter((f) => f.type.startsWith('image/'))
  const others = files.filter((f) => !f.type.startsWith('image/'))
  let images: string[] = []
  let suffix = ''
  if (pictures.length) {
    const form = new FormData()
    for (const f of pictures) form.append('files', f, f.name)
    images = (await api.upload<{ urls: string[] }>('/agent/images', form)).urls
  }
  if (others.length) {
    const form = new FormData()
    for (const f of others) form.append('files', f, f.name)
    const { paths } = await api.upload<{ paths: string[] }>(`/workspace/sessions/${sid}/upload`, form)
    suffix = `\n\nAttached files (in the workspace folder): ${paths.join(', ')}`
  }
  return { images, suffix }
}

export default function ChatPage({ basePath = '/agents/chat', agentPlus = false }: { basePath?: string; agentPlus?: boolean }) {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: session, isLoading, error: sessionError } = useSession(sessionId)
  const { data: chatModels } = useChatModels()
  const { data: settings } = useSettings()
  const create = useCreateSession()
  const update = useUpdateSession()
  const turn = useLive((st) => (sessionId ? st.turns[sessionId] : undefined))

  // Model + mode for a new chat; an existing chat uses its own
  const [draftModel, setDraftModel] = useState<string>()
  const [draftMode, setDraftMode] = useState<AgentMode>('agent')
  const fallbackModel = settings?.default_chat_model ?? chatModels?.find((m) => m.available)?.id
  const model = session?.model ?? draftModel ?? fallbackModel
  const mode = session?.mode ?? draftMode

  const streaming = !!turn?.streaming
  // The server sends the latest page of a long chat; earlier pages come when the user scrolls up to them
  const [olderWantedIn, setOlderWantedIn] = useState<string>()
  const older = useOlderMessages(sessionId, session?.has_older ? session.messages?.[0]?.id : undefined, olderWantedIn === sessionId)
  const moreOnServer = !!session?.has_older && (older.data ? older.hasNextPage : true)
  // Persisted history, then the live turn. The server saves the reply while it streams, so a fetch made mid-turn
  // already contains a stale copy of it: the live version replaces any persisted message with the same id.
  const items = useMemo<ThreadItem[]>(() => {
    const recent = session?.messages ?? []
    const recentIds = new Set(recent.map((m) => m.id))
    const earlier = (older.data?.pages ?? []).slice().reverse().flatMap((p) => p.messages).filter((m) => !recentIds.has(m.id))
    const live = turn ? [turn.user_message, turn.message] : []
    const liveIds = new Set(live.map((m) => m.id))
    const list: ThreadItem[] = [...earlier, ...recent]
      .filter((m) => !liveIds.has(m.id))
      .map((m) => ({ key: m.id, message: m, live: false }))
    if (turn) {
      list.push({ key: 'turn:user', message: turn.user_message, live: true })
      list.push({ key: 'turn:assistant', message: turn.message, live: true })
    }
    return list
  }, [session?.messages, older.data, turn])
  // The chat's usage: the server's totals over every saved reply (pages not loaded included), with the live turn in
  // place of its saved copy
  const totals = session?.totals
  const recent = session?.messages
  const stats = useMemo(() => {
    if (!totals) return addUp(NO_STATS, items.map((it) => it.message))
    const live = turn ? [turn.user_message, turn.message] : []
    const liveIds = new Set(live.map((m) => m.id))
    return addUp(addUp(totals, (recent ?? []).filter((m) => liveIds.has(m.id)), -1), live)
  }, [totals, recent, items, turn])
  const sessionCost = stats.cost
  // Average generation speed over the chat's replies (total tokens over total generation time)
  const sessionSpeed = tokensPerSecond(stats.output_tokens, stats.generation_s)
  const sessionUsage = formatUsage(stats.usage)
  // Kept as the same array while no diff changes, so the workspace panel does not re-render on every streamed token
  const foundDiffs = useMemo(
    () => items.flatMap((it) => (it.message.tool_calls ?? []).flatMap((c) => (c.display?.kind === 'diff' ? [c.display as Diff] : []))),
    [items],
  )
  const [diffs, setDiffs] = useState(foundDiffs)
  if (foundDiffs !== diffs && (foundDiffs.length !== diffs.length || foundDiffs.some((d, i) => d !== diffs[i]))) setDiffs(foundDiffs)

  // Workspace folder picked before the chat exists; applied right after it is created
  const [draftRoot, setDraftRoot] = useState<string>()
  const setRoot = useSetRoot()
  const panel = useWorkspacePanel()
  // A new chat starts with the workspace collapsed: it opens from its button or a tool card's "show" links
  const setPanelOpen = panel.setOpen
  useEffect(() => {
    if (!sessionId) setPanelOpen(false)
  }, [sessionId, setPanelOpen])
  const queue = useChatQueue(sessionId)

  const ensureSession = async (): Promise<string> => {
    if (sessionId) return sessionId
    const created = await create.mutateAsync({ model: model!, mode })
    qc.setQueryData(qk.session(created.id), { ...created, messages: [] })
    if (draftRoot) await setRoot.mutateAsync({ sid: created.id, root: draftRoot })
    navigate(`${basePath}/${created.id}`)
    return created.id
  }

  /** Send now; a failure pauses the queue so nothing is re-sent implicitly. */
  const deliver = async (sid: string, text: string, files: File[]) => {
    let attached = { images: [] as string[], suffix: '' }
    try {
      attached = await attach(sid, files)
    } catch (e) {
      toast.error('Attachments not uploaded', (e as Error).message)
      useConversationQueue.getState().pause(sid)
      return
    }
    if (!agent.send(sid, text + attached.suffix, attached.images)) useConversationQueue.getState().pause(sid)
  }

  const send = async (text: string, files: File[] = []) => {
    if (!model) return
    const sid = await ensureSession()
    const q = useConversationQueue.getState()
    const busy = !!useLive.getState().turns[sid]?.streaming
    if (busy || q.queues[sid]?.pending.length) {
      q.enqueue(sid, { id: `q-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, text, files })
      return
    }
    q.resume(sid) // a new message may continue after Stop; held follow-ups still need an explicit resume
    await deliver(sid, text, files)
  }

  // When a reply finishes, the next queued follow-up goes out
  const deliverRef = useRef(deliver)
  useEffect(() => {
    deliverRef.current = deliver
  })
  useEffect(() => {
    if (!sessionId || streaming || queue.paused || !queue.pending.length) return
    const next = useConversationQueue.getState().take(sessionId)
    if (next) void deliverRef.current(sessionId, next.text, next.files)
  }, [sessionId, streaming, queue])

  // A deleted chat (an old link, or removed in another tab): start a new one rather than show an empty thread
  // whose messages would go nowhere
  const missing = sessionError instanceof ApiError && sessionError.status === 404
  useEffect(() => {
    if (!missing) return
    toast.info('That chat no longer exists', 'Starting a new one.')
    navigate(basePath, { replace: true })
  }, [missing, navigate, basePath])

  // Slash commands (see commands.ts); returns false for unknown ones so the text is sent as a message
  const compact = useCompactSession()
  const runCommand = async (name: string, args: string): Promise<boolean> => {
    switch (name) {
      case 'new':
        navigate(basePath)
        return true
      case 'mode': {
        if (agentPlus) return true
        const m = args.toLowerCase()
        if (m !== 'agent' && m !== 'chat') {
          toast.error('Usage: /mode agent or /mode chat')
          return true
        }
        if (sessionId) update.mutate({ id: sessionId, mode: m })
        else setDraftMode(m)
        toast.success(m === 'agent' ? 'Agent mode: tools on' : 'Chat mode: no tools')
        return true
      }
      case 'model': {
        const q = args.toLowerCase()
        const found = q ? (chatModels ?? []).filter((m) => m.available && `${m.name} ${m.id}`.toLowerCase().includes(q)) : []
        if (!found.length) {
          toast.error(q ? `No available model matches "${args}"` : 'Usage: /model <part of a name>')
          return true
        }
        if (sessionId) update.mutate({ id: sessionId, model: found[0].id })
        else setDraftModel(found[0].id)
        toast.success(`Model: ${found[0].name}`, found.length > 1 ? `${found.length - 1} more matched; be more specific to pick another` : undefined)
        return true
      }
      case 'context': {
        const size = parseTokens(args)
        if (size === undefined) {
          toast.error('Usage: /context 32k, /context 1m or /context auto')
          return true
        }
        if (!sessionId) {
          toast.error('Send a first message, then set the context window for this chat')
          return true
        }
        update.mutate({ id: sessionId, context_size: size })
        toast.success(size ? `Context window: ${formatTokens(size)} tokens for this chat` : 'Context window: automatic')
        return true
      }
      case 'compact': {
        if (!sessionId) {
          toast.error('Nothing to compact yet')
          return true
        }
        if (streaming) {
          toast.error('Wait for the reply to finish (or stop it) before compacting')
          return true
        }
        if (compact.isPending) {
          toast.info('Already compacting this chat', 'It takes a minute or two on a local model.')
          return true
        }
        const r = await compact.mutateAsync({ id: sessionId, focus: args || undefined }).catch(() => undefined)
        if (r) toast.success(`Compacted ${r.folded} messages`, 'The model now continues from a summary; the chat stays visible here.')
        return true
      }
      default:
        return false
    }
  }

  const stop = () => {
    if (!sessionId) return
    useConversationQueue.getState().pause(sessionId)
    agent.stop(sessionId)
  }

  // A prompt handed over from the Home screen is sent once a model is known
  const location = useLocation()
  const handoff = (location.state as { prompt?: string } | null)?.prompt
  const sendRef = useRef(send)
  useEffect(() => {
    sendRef.current = send
  })
  useEffect(() => {
    if (!handoff || !model) return
    navigate(location.pathname, { replace: true, state: null })
    void sendRef.current(handoff)
  }, [handoff, model, navigate, location.pathname])

  // Follow the end of the thread — through streaming, late-loading media and the thread mounting after the
  // hero's exit — for as long as the user stays there. Any move up lets go at once, however small: the thread then
  // stays where they put it while the reply grows below. Coming back to the end (by scrolling, or the button) takes
  // hold again. Opening a chat and sending a message start at the end.
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const lastTop = useRef(0)
  /** Distance from the end of the thread to the top of the view: kept while earlier blocks are put above it. */
  const fromBottom = useRef(0)
  // The user is reading further up: offer the way back. Remembered with the chat it is about, so another chat
  // starts without it.
  const [awayIn, setAwayIn] = useState<string>()
  const away = !!sessionId && awayIn === sessionId
  const setAway = (on: boolean) => setAwayIn(on ? sessionId : undefined)
  const release = () => {
    stick.current = false
  }
  const toEnd = () => {
    const el = scroller.current
    if (!el || !stick.current) return
    // Higher than where it was left, and not at the end: the user moved up and the scroll event that says so is
    // still on its way (a reply streams faster than events arrive). Let go rather than pull the thread back.
    if (el.scrollTop < lastTop.current - 0.5 && el.scrollHeight - el.scrollTop - el.clientHeight >= 4) return release()
    el.scrollTop = el.scrollHeight
    lastTop.current = el.scrollTop
  }
  const follow = () => {
    stick.current = true
    setAway(false)
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }
  const sentId = turn?.user_message.id
  useLayoutEffect(() => {
    stick.current = true
    lastTop.current = 0
  }, [sessionId, sentId])
  useLayoutEffect(toEnd, [items])
  const followThread = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return
      // The thread grew (or shrank): keep to its end, or, when the user is further up, see how far behind they are
      const grown = () => {
        toEnd()
        const el = scroller.current
        if (!el) return
        fromBottom.current = el.scrollHeight - el.scrollTop
        setAwayIn(!stick.current && el.scrollHeight - el.scrollTop - el.clientHeight > AWAY_GAP ? sessionId : undefined)
      }
      grown()
      const ro = new ResizeObserver(grown)
      ro.observe(node)
      return () => ro.disconnect()
    },
    [sessionId], // eslint-disable-line react-hooks/exhaustive-deps -- toEnd only reads refs
  )

  const empty = !sessionId || (!isLoading && items.length === 0)
  const clock = useMemo(
    () => (turn ? { startedAt: turn.startedAt, waitedMs: turn.waitedMs, waitingSince: turn.waitingSince } : undefined),
    [turn?.startedAt, turn?.waitedMs, turn?.waitingSince], // eslint-disable-line react-hooks/exhaustive-deps
  )
  // Stable, so saved messages (memoized) are not re-rendered by every token of a streaming reply
  const approve = useCallback((callId: string, ok: boolean) => {
    if (sessionId) agent.approve(sessionId, callId, ok)
  }, [sessionId])
  const answer = useCallback((callId: string, text: string) => {
    if (sessionId) agent.answer(sessionId, callId, text)
  }, [sessionId])

  // A long chat opens on its latest blocks; near the top, earlier ones are shown a page at a time (fetching earlier
  // messages when none are left), keeping the view where it was. The first block shown is held by its message, so
  // what is shown stays put while a reply grows below and earlier pages arrive above, except while following the
  // end: then the oldest blocks give way, so a long session does not keep growing the page.
  const counts = useMemo(() => items.map((it) => blockCount(it.message)), [items])
  const total = counts.reduce((sum, n) => sum + n, 0)
  const latest = Math.max(0, total - PAGE)
  // `keep`: earlier blocks were just put above the view, which stays on what it showed
  const [startIn, setStartIn] = useState<{ sid: string; at: BlockRef; keep: boolean }>()
  const held = startIn && startIn.sid === sessionId ? offsetOf(items, counts, startIn.at) : undefined
  const hidden = Math.min(held ?? latest, latest)
  const startAt = (offset: number, keep = false) => {
    const at = refAt(items, counts, offset)
    if (sessionId && at) setStartIn({ sid: sessionId, at, keep })
  }
  // Opening a chat, or the first block shown is gone (a rewind; a live message saved under its real id)
  if (session && session.id === sessionId && items.length && held === undefined) startAt(hidden)
  // Earlier messages asked of the server (with the pages loaded when asked): shown once they arrive
  const [revealIn, setRevealIn] = useState<{ sid: string; pages: number }>()
  const loadedPages = older.data?.pages.length ?? 0
  if (revealIn && revealIn.sid === sessionId && !older.isFetching && (older.isError || loadedPages > revealIn.pages)) {
    setRevealIn(undefined)
    if (!older.isError && hidden > 0) startAt(Math.max(0, hidden - PAGE), true)
  }
  const visible = useMemo(() => {
    const out: { it: ThreadItem; skip: number }[] = []
    let before = 0
    items.forEach((it, i) => {
      if (before + counts[i] > hidden) out.push({ it, skip: Math.max(0, hidden - before) })
      before += counts[i]
    })
    return out
  }, [items, counts, hidden])
  const showEarlier = () => {
    const el = scroller.current
    if (!el || !sessionId) return
    if (hidden > 0) {
      release()
      fromBottom.current = el.scrollHeight - el.scrollTop
      startAt(Math.max(0, hidden - PAGE), true)
    } else if (moreOnServer && !older.isFetching && revealIn?.sid !== sessionId) {
      release()
      setRevealIn({ sid: sessionId, pages: loadedPages })
      if (olderWantedIn !== sessionId) setOlderWantedIn(sessionId) // the first page loads as the query turns on
      else if (older.data) void older.fetchNextPage()
      else void older.refetch() // the first page failed
    }
  }
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el || !startIn?.keep) return
    el.scrollTop = el.scrollHeight - fromBottom.current
    lastTop.current = el.scrollTop
  }, [startIn])
  useLayoutEffect(() => {
    if (stick.current && total - hidden > PAGE * 3) startAt(total - PAGE)
  }, [total, hidden]) // eslint-disable-line react-hooks/exhaustive-deps -- startAt is rebuilt every render

  // Checkpoints: rewind to one of the user's messages (its text returns to the composer), or fork into a new chat
  const rewind = useRewindSession()
  const { mutate: forkSession } = useForkSession()
  const [rewindTarget, setRewindTarget] = useState<AgentMessage | null>(null)
  const [draft, setDraft] = useState<{ text: string }>()
  const onRewind = useCallback((m: AgentMessage) => setRewindTarget(m), [])
  const onFork = useCallback(
    (m: AgentMessage) => {
      if (!sessionId) return
      forkSession({ id: sessionId, message_id: m.id }, { onSuccess: (s) => navigate(`/agents/chat/${s.id}`) })
    },
    [sessionId, forkSession, navigate],
  )
  const confirmRewind = async () => {
    if (!sessionId || !rewindTarget) return
    const r = await rewind.mutateAsync({ id: sessionId, message_id: rewindTarget.id })
    setRewindTarget(null)
    setDraft({ text: r.prompt })
    const files = r.restored.length + r.removed.length
    toast.success('Rewound', files ? `${files} file${files === 1 ? '' : 's'} put back as they were` : 'No file changes to undo')
    if (r.commands.length || r.skipped.length) {
      toast.warning(
        'Some changes stay',
        [
          r.commands.length && `${r.commands.length} terminal command${r.commands.length === 1 ? '' : 's'} can't be undone (${r.commands.slice(0, 2).join('; ')}${r.commands.length > 2 ? '…' : ''})`,
          r.skipped.length && `${r.skipped.length} file${r.skipped.length === 1 ? '' : 's'} couldn't be restored`,
        ]
          .filter(Boolean)
          .join('. '),
      )
    }
  }

  const chat = (
    <div className={s.page}>
      {!panel.open && (
        <IconButton
          className={s.panelToggle}
          label="Show workspace (context, terminal, files, browser, tasks)"
          icon={<PanelRightOpen />}
          onClick={() => panel.setOpen(true)}
          tooltipSide="left"
        />
      )}
      <div
        ref={scroller}
        className={s.scroll}
        onWheel={(e) => {
          // Let go before the scroll itself happens, so nothing pulls the thread back under the wheel
          if (e.deltaY < 0 && e.currentTarget.scrollTop > 0) release()
          // At the very top no scroll event follows, so the wheel itself asks for earlier blocks
          if (e.deltaY < 0 && e.currentTarget.scrollTop < EARLIER_GAP) showEarlier()
        }}
        onScroll={(e) => {
          const el = e.currentTarget
          const gap = el.scrollHeight - el.scrollTop - el.clientHeight
          if (gap < 4) stick.current = true
          else if (el.scrollTop < lastTop.current - 0.5) release() // moved up: by wheel, keys, touch or the scrollbar
          lastTop.current = el.scrollTop
          fromBottom.current = el.scrollHeight - el.scrollTop
          setAway(!stick.current && gap > AWAY_GAP)
          if (!stick.current && el.scrollTop < EARLIER_GAP) showEarlier()
        }}
      >
        <AnimatePresence mode="wait">
          {empty ? (
            <motion.div key="hero" className={s.hero} exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.2 }}>
              <Aurora colors={['#e11d48', '#7f1d1d', '#9f1239']} intensity={0.7} className={s.heroAurora} />
              <CircuitField density={3.2} />
              <motion.div
                className={s.heroInner}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className={s.heroIcon}>
                  <Logo size={112} mode="assemble" glow />
                </div>
                <h1 className={s.heroTitle}>{agentPlus ? 'Ready to work on this mission.' : 'What should we build?'}</h1>
                <p className={s.heroSub}>
                  {agentPlus ? 'Start the mission from its progress panel, or send instructions here. Its evidence and tools stay with this chat.' : mode === 'agent'
                    ? 'The agent works in a folder you pick: it runs commands in a terminal you can watch, edits files, drives a browser you can take over, and manages your models — asking before anything risky.'
                    : 'Plain chat — no tools, just the model.'}
                </p>
                <div className={s.suggestions}>
                  {!agentPlus && SUGGESTIONS.map((sg, i) => (
                    <motion.button
                      key={sg.text}
                      className={s.suggestion}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.15 + i * 0.05, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                      onClick={() => void send(sg.text)}
                      disabled={!model}
                    >
                      {sg.icon}
                      <span>{sg.text}</span>
                    </motion.button>
                  ))}
                </div>
              </motion.div>
            </motion.div>
          ) : (
            <motion.div key={sessionId} ref={followThread} className={s.thread}>
              {isLoading && !items.length ? (
                <div className={s.loading}>
                  <Skeleton height={18} width="40%" />
                  <Skeleton height={72} />
                  <Skeleton height={18} width="55%" />
                </div>
              ) : (
                <>
                {(hidden > 0 || moreOnServer) && (
                  <button className={s.earlier} onClick={showEarlier} disabled={hidden === 0 && older.isFetching}>
                    <ArrowUp size={13} />
                    {hidden > 0
                      ? `Show earlier · ${formatCount(hidden)} more ${hidden === 1 ? 'step' : 'steps'}`
                      : older.isFetching
                        ? 'Loading earlier messages…'
                        : older.isError
                          ? 'Earlier messages did not load · Try again'
                          : 'Show earlier messages'}
                  </button>
                )}
                {visible.map(({ it, skip }) => (
                  <MessageView
                    key={it.key}
                    skip={skip}
                    message={it.message}
                    streaming={it.live && streaming && it.message.role === 'assistant'}
                    appear={it.live}
                    clock={it.live && it.message.role === 'assistant' ? clock : undefined}
                    draft={it.live && it.message.role === 'assistant' ? turn?.draft : undefined}
                    onApprove={approve}
                    onAnswer={it.live ? answer : undefined}
                    onRewind={agentPlus || it.live || streaming ? undefined : onRewind}
                    onFork={agentPlus || it.live || streaming ? undefined : onFork}
                  />
                ))}
                </>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className={s.composerWrap}>
        <AnimatePresence>
          {away && !empty && (
            <motion.button
              className={s.toEnd}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              transition={{ duration: 0.18 }}
              onClick={follow}
              aria-label="Go to the latest message"
            >
              <ArrowDown size={14} />
              {streaming ? 'Follow the reply' : 'Latest'}
            </motion.button>
          )}
        </AnimatePresence>
        <Composer
          models={chatModels ?? []}
          model={model}
          onModelChange={(id) => (sessionId ? update.mutate({ id: sessionId, model: id }) : setDraftModel(id))}
          mode={mode}
          fixedMode={agentPlus}
          onModeChange={(m) => !agentPlus && (sessionId ? update.mutate({ id: sessionId, mode: m }) : setDraftMode(m))}
          streaming={streaming}
          onSend={send}
          onStop={stop}
          queued={queue.pending}
          queuePaused={queue.paused}
          onRemoveQueued={(id) => sessionId && useConversationQueue.getState().remove(sessionId, id)}
          onResumeQueue={() => sessionId && useConversationQueue.getState().resume(sessionId)}
          draft={draft}
          context={session?.context}
          contextNote={turn?.contextNote}
          onCommand={runCommand}
          busy={compact.isPending ? 'Compacting: the model is summarizing this chat so it can go on with less context…' : undefined}
        />
        <ConfirmDialog
          open={!!rewindTarget}
          onOpenChange={(open) => !open && setRewindTarget(null)}
          title="Rewind to this message?"
          description="This message and everything after it are removed, and files the agent created or edited since then are put back as they were. Your message returns to the box so you can change it and send again. Commands it ran in the terminal can't be undone."
          confirmLabel="Rewind"
          tone="danger"
          onConfirm={confirmRewind}
        />
        <ChatLightbox />
        <p className={s.disclaimer}>
          {sessionSpeed && (
            <span className={s.sessionCost} title="Average generation speed of this chat's replies">
              Avg {sessionSpeed}
            </span>
          )}
          {sessionUsage && (
            <span className={s.sessionCost} title="Tokens this chat has used over all model requests">
              {sessionUsage}
            </span>
          )}
          {sessionCost > 0 && <span className={s.sessionCost}>This chat: {formatUsd(sessionCost)} on OpenRouter</span>}
        </p>
      </div>
    </div>
  )

  return (
    <ResizablePanels
      main={chat}
      side={
        panel.open && mode === 'agent' ? (
          <Suspense fallback={<Skeleton height="100%" radius={0} />}>
            <WorkspacePanel sessionId={sessionId} draftRoot={draftRoot} onDraftRoot={setDraftRoot} diffs={diffs} />
          </Suspense>
        ) : null
      }
      size={panel.size}
      onSizeChange={panel.setSize}
      min={360}
      mainMin={420}
    />
  )
}

function ChatLightbox() {
  const { src, caption, close } = useChatLightbox()
  return <Lightbox src={src} alt={caption} caption={caption} onClose={close} downloadName={src?.split('/').pop()} />
}
