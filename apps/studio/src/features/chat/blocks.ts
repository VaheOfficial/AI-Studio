import type { AgentMessage, ToolCall } from '../../api/types'

/** The agent's completion verdict `[[DONE: yes|no]]` (see agent/loop.py) — kept in the saved text, hidden here. */
const DONE_MARK = /\s*\[\[\s*DONE\s*(?::\s*(?:yes|no))?\s*\]\]\s*/gi
/** Tool calls a model printed as text (the server runs them — agent/textcalls.py); hidden while they stream. */
const CALL_MARKUP = /<(?:[\w-]+:)?function_calls>[\s\S]*?(?:<\/(?:[\w-]+:)?function_calls>|$)|<tool_call>[\s\S]*?(?:<\/tool_call>|$)/g

export type Part =
  | { kind: 'text'; key: string; text: string }
  | { kind: 'thinking'; key: string; text: string }
  | { kind: 'call'; call: ToolCall }

const clean = (text: string) => text.replace(CALL_MARKUP, '').replace(DONE_MARK, '\n').trim()

/**
 * Text, thinking and tool cards in the order they happened: calls and thinking parts know the text length when they
 * began (`at`) and their order among each other (`seq`).
 */
export function interleave(message: AgentMessage): Part[] {
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

const blockCounts = new WeakMap<AgentMessage, number>()

/** How many blocks (text, thinking, tool cards) a message shows: the unit a long chat is paged by. */
export function blockCount(message: AgentMessage): number {
  if (message.role === 'user') return 1
  let n = blockCounts.get(message)
  if (n === undefined) {
    n = Math.max(1, interleave(message).length)
    blockCounts.set(message, n)
  }
  return n
}
