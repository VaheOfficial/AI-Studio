import { memo, useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { AlarmClock, Brain, ChevronRight, GitBranch, Radar, RotateCcw } from 'lucide-react'
import { cn, IconButton, Logo } from '@studio/ui'
import { automationRunOf } from '../../api/automations'
import type { TurnClock } from '../../api/live'
import type { AgentMessage, ToolCall } from '../../api/types'
import { formatCount, formatDuration, formatUsage, tokensPerSecond } from '../../lib/format'
import { formatUsd } from '../../lib/money'
import { Markdown } from './Markdown'
import { useChatPrefs } from './prefs'
import { useChatLightbox } from './lightbox'
import { ToolCallCard } from './ToolCallCard'
import { toolMeta } from './toolMeta'
import s from './MessageView.module.css'

export interface MessageViewProps {
  message: AgentMessage
  streaming?: boolean
  /** Animate in — true only for messages that arrive while the chat is open. */
  appear?: boolean
  /** The running turn's stopwatch — only for the reply being produced. */
  clock?: TurnClock
  /** The tool call the model is writing right now — only for the reply being produced. */
  draft?: { name: string; chars: number }
  onApprove: (callId: string, approved: boolean) => void
  /** Answers an `ask_user` question — only for the live turn. */
  onAnswer?: (callId: string, answer: string) => void
  /** Checkpoint actions — only for saved messages while no reply is streaming. */
  onRewind?: (message: AgentMessage) => void
  onFork?: (message: AgentMessage) => void
}

/** The agent's completion verdict `[[DONE: yes|no]]` (see agent/loop.py) — kept in the saved text, hidden here. */
const DONE_MARK = /\s*\[\[\s*DONE\s*(?::\s*(?:yes|no))?\s*\]\]\s*/gi
/** Tool calls a model printed as text (the server runs them — agent/textcalls.py); hidden while they stream. */
const CALL_MARKUP = /<(?:[\w-]+:)?function_calls>[\s\S]*?(?:<\/(?:[\w-]+:)?function_calls>|$)|<tool_call>[\s\S]*?(?:<\/tool_call>|$)/g

export const MessageView = memo(function MessageView({ message, streaming, appear, clock, draft, onApprove, onAnswer, onRewind, onFork }: MessageViewProps) {
  const actions = (onRewind || onFork) && (
    <div className={s.actions}>
      {onRewind && message.role === 'user' && (
        <IconButton size="sm" label="Rewind to here — remove this message and everything after, and undo the agent's file changes" icon={<RotateCcw />} onClick={() => onRewind(message)} />
      )}
      {onFork && <IconButton size="sm" label="Fork from here — continue in a new chat" icon={<GitBranch />} onClick={() => onFork(message)} />}
    </div>
  )
  const run = message.role === 'user' ? automationRunOf(message.content) : undefined
  if (run) return <AutomationRun run={run} text={message.content} appear={appear} />
  if (message.role === 'user') {
    return (
      <motion.div
        className={s.user}
        initial={appear ? { opacity: 0, y: 10, scale: 0.98 } : false}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 400, damping: 32 }}
      >
        {actions}
        <div className={s.userStack}>
          {message.images && message.images.length > 0 && (
            <div className={s.userImages}>
              {message.images.map((url) => (
                <button key={url} className={s.userImage} onClick={() => useChatLightbox.getState().show(url, 'Attached image')}>
                  <img src={url} alt="Attached" loading="lazy" />
                </button>
              ))}
            </div>
          )}
          {message.content && <div className={s.userBubble}>{message.content}</div>}
        </div>
      </motion.div>
    )
  }

  const parts = interleave(message)
  const last = parts.at(-1)
  // What the model is doing at the end of the reply: writing a tool call, writing the last part, or (nothing on the
  // page moving: before its first word, and between a finished tool and its next step) reading and getting started
  const writing = streaming && !draft
  const settled = last?.kind === 'call' && last.call.status !== 'running' && last.call.status !== 'pending_approval' && last.call.status !== 'awaiting_input'
  const starting = writing && (!last || settled)
  return (
    <motion.div className={s.assistant} initial={appear ? { opacity: 0 } : false} animate={{ opacity: 1 }}>
      <div className={s.avatar} data-streaming={streaming || undefined}>
        <Logo size={24} mode={streaming ? 'working' : 'still'} />
      </div>
      <div className={s.body}>
        {parts.map((p) =>
          p.kind === 'call' ? (
            <ToolCallCard key={p.call.id} call={p.call} onApprove={onApprove} onAnswer={onAnswer} />
          ) : p.kind === 'thinking' ? (
            <Thinking key={p.key} text={p.text} live={writing && p === last} />
          ) : (
            <Markdown key={p.key} text={p.text} live={writing && p === last} />
          ),
        )}
        {streaming && draft && <DraftCall name={draft.name} chars={draft.chars} />}
        {starting && <TypingDots />}
        <ReplyMeta message={message} clock={streaming ? clock : undefined} />
        {actions}
      </div>
    </motion.div>
  )
})

/**
 * The start of an automation's run in the chat: a line saying which automation ran and why, in place of the
 * instruction the server sent the agent (which opens underneath).
 */
function AutomationRun({ run, text, appear }: { run: NonNullable<ReturnType<typeof automationRunOf>>; text: string; appear?: boolean }) {
  const [open, setOpen] = useState(false)
  const why = run.trigger ? (run.items ? `${run.items} new ${run.items === 1 ? 'item' : 'items'}` : 'checked by hand') : 'scheduled run'
  return (
    <motion.div className={s.run} initial={appear ? { opacity: 0, y: 6 } : false} animate={{ opacity: 1, y: 0 }}>
      <button className={s.runHead} onClick={() => setOpen(!open)} aria-expanded={open}>
        {run.trigger ? <Radar size={13} /> : <AlarmClock size={13} />}
        <span className={s.runTitle}>{run.title}</span>
        <span>{why}</span>
        <ChevronRight size={13} className={cn(s.chev, open && s.chevOpen)} />
      </button>
      {open && <div className={s.runBody}>{text}</div>}
    </motion.div>
  )
}

/** The model is writing a tool call: long ones (a script, a file) take a while before their card appears. */
function DraftCall({ name, chars }: { name: string; chars: number }) {
  const meta = toolMeta(name)
  const label = !name ? 'Preparing a tool call' : (meta.writing ?? `Preparing a tool call: ${name.replaceAll('__', ' · ').replaceAll('_', ' ')}`)
  return (
    <div className={s.draft}>
      <span className={s.draftIcon}>{meta.icon}</span>
      <span className={s.shimmerText}>{label}…</span>
      {chars >= 200 && <span className={s.draftSize}>{formatCount(chars)} characters</span>}
    </div>
  )
}

/** The running turn's stopwatch. It stands still while the turn waits for the user. */
function LiveTimer({ clock }: { clock: TurnClock }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const until = clock.waitingSince ?? Math.max(now, clock.startedAt)
  return (
    <span title={clock.waitingSince ? 'Waiting for you; the clock is stopped' : 'How long this turn has been working (time spent waiting for you is not counted)'}>
      {formatDuration((until - clock.startedAt - clock.waitedMs) / 1000)}
    </span>
  )
}

/**
 * Under a reply: how long its turn worked, its average generation speed, the tokens it used and, for OpenRouter
 * models, what it cost.
 */
function ReplyMeta({ message, clock }: { message: AgentMessage; clock?: TurnClock }) {
  const speed = tokensPerSecond(message.output_tokens, message.generation_s)
  const usage = formatUsage(message.usage)
  if (!clock && message.elapsed_s == null && !speed && !usage && message.cost == null) return null
  return (
    <span className={s.meta}>
      {clock ? (
        <LiveTimer clock={clock} />
      ) : (
        message.elapsed_s != null && (
          <span title="How long this turn worked: model requests, reading and tools (time spent waiting for you is not counted)">
            {formatDuration(message.elapsed_s)}
          </span>
        )
      )}
      {usage && (
        <span title="Every model request re-reads the whole conversation, so input adds up over the steps of a turn. Cached input is billed at a fraction of the price.">
          {usage}
        </span>
      )}
      {speed && (
        <span
          title={`${message.output_tokens} tokens generated in ${message.generation_s?.toFixed(1)} s (reading the prompt not included)`}
        >
          {speed}
        </span>
      )}
      {message.cost != null && <span title="Billed by OpenRouter for this reply">{formatUsd(message.cost)}</span>}
    </span>
  )
}

type Part =
  | { kind: 'text'; key: string; text: string }
  | { kind: 'thinking'; key: string; text: string }
  | { kind: 'call'; call: ToolCall }

const clean = (text: string) => text.replace(CALL_MARKUP, '').replace(DONE_MARK, '\n').trim()

/**
 * Text, thinking and tool cards in the order they happened: calls and thinking parts know the text length when they
 * began (`at`) and their order among each other (`seq`).
 */
function interleave(message: AgentMessage): Part[] {
  const content = message.content
  const calls = message.tool_calls ?? []
  const thoughts = message.thinking_parts ?? []
  if (calls.some((c) => c.at == null)) {
    // Messages saved before calls carried a position: thinking, then cards, then the text
    const text = clean(content)
    return [
      ...(message.thinking ? [{ kind: 'thinking', key: 'thinking', text: message.thinking } as Part] : []),
      ...calls.map((call): Part => ({ kind: 'call', call })),
      ...(text ? [{ kind: 'text', key: 'text', text } as Part] : []),
    ]
  }
  const items: { at: number; seq: number; part: Part }[] = [
    ...calls.map((call) => ({ at: call.at!, seq: call.seq ?? 0, part: { kind: 'call', call } as Part })),
    ...thoughts.map((t) => ({ at: t.at, seq: t.seq, part: { kind: 'thinking', key: `thinking-${t.seq}`, text: t.text } as Part })),
  ]
  if (!thoughts.length && message.thinking) {
    items.push({ at: 0, seq: -1, part: { kind: 'thinking', key: 'thinking', text: message.thinking } })
  }
  items.sort((a, b) => a.at - b.at || a.seq - b.seq)
  const parts: Part[] = []
  let from = 0
  const pushText = (to: number) => {
    const text = clean(content.slice(from, to))
    if (text) parts.push({ kind: 'text', key: `text-${from}`, text })
    from = to
  }
  for (const item of items) {
    pushText(Math.min(Math.max(item.at, from), content.length))
    parts.push(item.part)
  }
  pushText(content.length)
  return parts
}

function Thinking({ text, live }: { text: string; live?: boolean }) {
  const verbose = useChatPrefs((st) => st.verbose)
  const [toggled, setToggled] = useState<boolean>()
  const open = toggled ?? verbose // verbose shows every block expanded; the user's own toggle wins
  return (
    <div className={s.thinking}>
      <button className={s.thinkingHead} onClick={() => setToggled(!open)} aria-expanded={open}>
        <Brain size={13} />
        <span className={cn(live && s.shimmerText)}>{live ? 'Thinking…' : 'Thought process'}</span>
        <ChevronRight size={13} className={cn(s.chev, open && s.chevOpen)} />
      </button>
      {open && <div className={s.thinkingBody}>{text}</div>}
    </div>
  )
}

/** Before the first token: a signal trace, its bars rising and falling in a wave. */
function TypingDots() {
  return (
    <div className={s.dots} aria-label="Assistant is thinking">
      {[0, 1, 2, 3, 4, 5, 6].map((i) => (
        <motion.span
          key={i}
          animate={{ scaleY: [0.25, 1, 0.25], opacity: [0.35, 1, 0.35] }}
          transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.09, ease: 'easeInOut' }}
        />
      ))}
    </div>
  )
}
