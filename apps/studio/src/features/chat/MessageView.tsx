import { memo, useState } from 'react'
import { motion } from 'motion/react'
import { Brain, ChevronRight, GitBranch, RotateCcw } from 'lucide-react'
import { cn, IconButton } from '@studio/ui'
import type { AgentMessage, ToolCall } from '../../api/types'
import { tokensPerSecond } from '../../lib/format'
import { formatUsd } from '../../lib/money'
import { Markdown } from './Markdown'
import { useChatPrefs } from './prefs'
import { useChatLightbox } from './lightbox'
import { ToolCallCard } from './ToolCallCard'
import s from './MessageView.module.css'

export interface MessageViewProps {
  message: AgentMessage
  streaming?: boolean
  /** Animate in — true only for messages that arrive while the chat is open. */
  appear?: boolean
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

export const MessageView = memo(function MessageView({ message, streaming, appear, onApprove, onAnswer, onRewind, onFork }: MessageViewProps) {
  const actions = (onRewind || onFork) && (
    <div className={s.actions}>
      {onRewind && message.role === 'user' && (
        <IconButton size="sm" label="Rewind to here — remove this message and everything after, and undo the agent's file changes" icon={<RotateCcw />} onClick={() => onRewind(message)} />
      )}
      {onFork && <IconButton size="sm" label="Fork from here — continue in a new chat" icon={<GitBranch />} onClick={() => onFork(message)} />}
    </div>
  )
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
  const endsInText = last?.kind === 'text'
  const hasContent = parts.length > 0
  return (
    <motion.div className={s.assistant} initial={appear ? { opacity: 0 } : false} animate={{ opacity: 1 }}>
      <div className={s.avatar} data-streaming={streaming || undefined} />
      <div className={s.body}>
        {parts.map((p) =>
          p.kind === 'call' ? (
            <ToolCallCard key={p.call.id} call={p.call} onApprove={onApprove} onAnswer={onAnswer} />
          ) : p.kind === 'thinking' ? (
            <Thinking key={p.key} text={p.text} live={streaming && p === last} />
          ) : (
            <Markdown key={p.key} text={p.text} />
          ),
        )}
        {streaming && !hasContent && <TypingDots />}
        {streaming && endsInText && <span className={s.caret} />}
        <ReplyMeta message={message} />
        {actions}
      </div>
    </motion.div>
  )
})

/** Under a reply: its average generation speed and, for OpenRouter models, what it cost. */
function ReplyMeta({ message }: { message: AgentMessage }) {
  const speed = tokensPerSecond(message.output_tokens, message.generation_s)
  if (!speed && message.cost == null) return null
  return (
    <span className={s.meta}>
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

function TypingDots() {
  return (
    <div className={s.dots} aria-label="Assistant is typing">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          animate={{ opacity: [0.25, 1, 0.25], y: [0, -3, 0] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.15, ease: 'easeInOut' }}
        />
      ))}
    </div>
  )
}
