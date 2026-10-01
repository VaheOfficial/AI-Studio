import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { Globe, ListChecks, MessageSquareText, PanelRightOpen, SquareTerminal, Sparkles, Wrench } from 'lucide-react'
import { Aurora, ConfirmDialog, IconButton, Lightbox, ResizablePanels, Skeleton, toast } from '@studio/ui'
import { api, ApiError } from '../../api/client'
import type { ToolDisplay } from '../../api/contracts/workspace'
import {
  useChatModels,
  useCompactSession,
  useCreateSession,
  useForkSession,
  useRewindSession,
  useSession,
  useSettings,
  useUpdateSession,
} from '../../api/hooks'
import { qk } from '../../api/keys'
import { agent, useLive } from '../../api/live'
import type { AgentMessage, AgentMode } from '../../api/types'
import { useSetRoot } from '../../api/workspace'
import { formatTokens, tokensPerSecond } from '../../lib/format'
import { formatUsd } from '../../lib/money'
import { parseTokens } from './commands'
import { Composer } from './Composer'
import { useChatQueue, useConversationQueue } from './conversationQueue'
import { useChatLightbox } from './lightbox'
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

export default function ChatPage() {
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
  // Persisted history, then the live turn. The server saves the reply while it streams, so a fetch made mid-turn
  // already contains a stale copy of it: the live version replaces any persisted message with the same id.
  const items = useMemo<ThreadItem[]>(() => {
    const persisted = session?.messages ?? []
    const live = turn ? [turn.user_message, turn.message] : []
    const liveIds = new Set(live.map((m) => m.id))
    const list: ThreadItem[] = persisted
      .filter((m) => !liveIds.has(m.id))
      .map((m) => ({ key: m.id, message: m, live: false }))
    if (turn) {
      list.push({ key: 'turn:user', message: turn.user_message, live: true })
      list.push({ key: 'turn:assistant', message: turn.message, live: true })
    }
    return list
  }, [session?.messages, turn])
  const sessionCost = items.reduce((sum, it) => sum + (it.message.cost ?? 0), 0)
  // Average generation speed over the chat's replies (total tokens over total generation time)
  const sessionSpeed = tokensPerSecond(
    items.reduce((sum, it) => sum + (it.message.output_tokens ?? 0), 0),
    items.reduce((sum, it) => sum + (it.message.generation_s ?? 0), 0),
  )
  const diffs = useMemo(
    () => items.flatMap((it) => (it.message.tool_calls ?? []).flatMap((c) => (c.display?.kind === 'diff' ? [c.display as Diff] : []))),
    [items],
  )

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
    navigate(`/chat/${created.id}`)
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
    navigate('/chat', { replace: true })
  }, [missing, navigate])

  // Slash commands (see commands.ts); returns false for unknown ones so the text is sent as a message
  const compact = useCompactSession()
  const runCommand = async (name: string, args: string): Promise<boolean> => {
    switch (name) {
      case 'new':
        navigate('/chat')
        return true
      case 'mode': {
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
  // hero's exit — until the user scrolls up; opening a chat starts at its end.
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const toEnd = () => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }
  useLayoutEffect(() => {
    stick.current = true
  }, [sessionId])
  useLayoutEffect(toEnd, [items])
  const followThread = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    toEnd()
    const ro = new ResizeObserver(toEnd)
    ro.observe(node)
    return () => ro.disconnect()
  }, [])

  const empty = !sessionId || (!isLoading && items.length === 0)
  const approve = (callId: string, ok: boolean) => sessionId && agent.approve(sessionId, callId, ok)
  const answer = (callId: string, text: string) => sessionId && agent.answer(sessionId, callId, text)

  // Checkpoints: rewind to one of the user's messages (its text returns to the composer), or fork into a new chat
  const rewind = useRewindSession()
  const { mutate: forkSession } = useForkSession()
  const [rewindTarget, setRewindTarget] = useState<AgentMessage | null>(null)
  const [draft, setDraft] = useState<{ text: string }>()
  const onRewind = useCallback((m: AgentMessage) => setRewindTarget(m), [])
  const onFork = useCallback(
    (m: AgentMessage) => {
      if (!sessionId) return
      forkSession({ id: sessionId, message_id: m.id }, { onSuccess: (s) => navigate(`/chat/${s.id}`) })
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
          label="Show workspace (terminal, files, browser, tasks)"
          icon={<PanelRightOpen />}
          onClick={() => panel.setOpen(true)}
          tooltipSide="left"
        />
      )}
      <div
        ref={scroller}
        className={s.scroll}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
      >
        <AnimatePresence mode="wait">
          {empty ? (
            <motion.div key="hero" className={s.hero} exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.2 }}>
              <Aurora colors={['#7c3aed', '#4338ca', '#0891b2']} intensity={0.7} className={s.heroAurora} />
              <motion.div
                className={s.heroInner}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className={s.heroIcon}>
                  <Sparkles />
                </div>
                <h1 className={s.heroTitle}>What should we build?</h1>
                <p className={s.heroSub}>
                  {mode === 'agent'
                    ? 'The agent works in a folder you pick: it runs commands in a terminal you can watch, edits files, drives a browser you can take over, and manages your models — asking before anything risky.'
                    : 'Plain chat — no tools, just the model.'}
                </p>
                <div className={s.suggestions}>
                  {SUGGESTIONS.map((sg, i) => (
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
                items.map((it) => (
                  <MessageView
                    key={it.key}
                    message={it.message}
                    streaming={it.live && streaming && it.message.role === 'assistant'}
                    appear={it.live}
                    onApprove={approve}
                    onAnswer={it.live ? answer : undefined}
                    onRewind={it.live || streaming ? undefined : onRewind}
                    onFork={it.live || streaming ? undefined : onFork}
                  />
                ))
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className={s.composerWrap}>
        <Composer
          models={chatModels ?? []}
          model={model}
          onModelChange={(id) => (sessionId ? update.mutate({ id: sessionId, model: id }) : setDraftModel(id))}
          mode={mode}
          onModeChange={(m) => (sessionId ? update.mutate({ id: sessionId, mode: m }) : setDraftMode(m))}
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
          <MessageSquareText size={11} /> Runs locally unless you pick a cloud provider. Risky tool calls always ask first.
          {sessionSpeed && (
            <span className={s.sessionCost} title="Average generation speed of this chat's replies">
              Avg {sessionSpeed}
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
