/**
 * Writing blocks: finished pieces of writing the assistant produces (an email, a message, a post, a document) in
 *
 *   :::writing{variant="email" id="12345" subject="…" recipient="…"}
 *   ---option {subject="…"} Formal      ← optional, up to 3 alternatives
 *   …text…
 *   :::
 *
 * The chat shows each block as a card with copy / edit / download / open-in-mail. A block still streaming has no
 * closing fence yet and is shown as it grows.
 */

export type WritingVariant = 'email' | 'chat_message' | 'social_post' | 'document' | 'standard'

export interface WritingOption {
  title?: string
  subject?: string
  text: string
}

export interface WritingBlockData {
  variant: WritingVariant
  id: string
  attrs: Record<string, string>
  options: WritingOption[]
  open: boolean // still streaming (no closing fence yet)
}

export type Segment = { kind: 'markdown'; text: string } | { kind: 'writing'; block: WritingBlockData }

const OPEN = /^:::writing\{(.*)\}[ \t]*$/
const CLOSE = /^:::[ \t]*$/
const OPTION = /^---option(?:\s*\{((?:[^}\\]|\\.)*)\})?\s*(.*)$/
const ATTR = /(\w+)="((?:[^"\\]|\\.)*)"/g

const VARIANTS = new Set<WritingVariant>(['email', 'chat_message', 'social_post', 'document', 'standard'])

function attrs(raw: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of raw.matchAll(ATTR)) out[m[1]] = m[2].replace(/\\(.)/g, '$1')
  return out
}

const SUBJECT_LINE = /^\s*(?:\*\*)?subject:(?:\*\*)?\s*(.+)$/i

/** A leading "Subject: …" line in an email body (a common habit) becomes the option's subject. */
function liftSubject(o: WritingOption): WritingOption {
  const lines = o.text.split('\n')
  const first = lines.findIndex((l) => l.trim())
  const m = first >= 0 ? SUBJECT_LINE.exec(lines[first]) : null
  if (!m) return o
  return { ...o, subject: o.subject ?? m[1].trim(), text: lines.slice(first + 1).join('\n').trim() }
}

function options(body: string, email: boolean): WritingOption[] {
  const found: WritingOption[] = [{ text: '' }] // text before the first ---option line is an option too
  for (const line of body.split('\n')) {
    const m = OPTION.exec(line)
    if (m) found.push({ title: m[2].trim() || undefined, subject: m[1] ? attrs(m[1]).subject : undefined, text: '' })
    else found[found.length - 1].text += (found[found.length - 1].text ? '\n' : '') + line
  }
  const kept = found.map((o) => ({ ...o, text: o.text.trim() })).filter((o, i) => i > 0 || o.text)
  return (kept.length ? kept : [{ text: '' }]).map((o) => (email ? liftSubject(o) : o))
}

/** Split a reply into markdown and writing blocks (fences inside code blocks are left alone). */
export function splitWriting(text: string): Segment[] {
  if (!text.includes(':::writing')) return [{ kind: 'markdown', text }]
  const segments: Segment[] = []
  const lines = text.split('\n')
  let md: string[] = []
  let inCode = false
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (/^\s*(```|~~~)/.test(line)) inCode = !inCode
    const open = !inCode && OPEN.exec(line)
    if (!open) {
      md.push(line)
      continue
    }
    let j = i + 1
    while (j < lines.length && !CLOSE.test(lines[j])) j++
    if (md.length) segments.push({ kind: 'markdown', text: md.join('\n') })
    md = []
    const a = attrs(open[1])
    const variant = VARIANTS.has(a.variant as WritingVariant) ? (a.variant as WritingVariant) : 'standard'
    segments.push({
      kind: 'writing',
      block: {
        variant,
        id: a.id ?? String(i),
        attrs: a,
        options: options(lines.slice(i + 1, j).join('\n'), variant === 'email'),
        open: j >= lines.length,
      },
    })
    i = j
  }
  if (md.length && md.join('').trim()) segments.push({ kind: 'markdown', text: md.join('\n') })
  return segments
}

/** Markdown → plain text for pasting into mail and chat apps (keeps line breaks and list markers). */
export function plainText(md: string): string {
  return md
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/(^|[^*])\*(?!\s)(.+?)\*/g, '$1$2')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')
    .replace(/^- \[ \] /gm, '☐ ')
    .replace(/^- \[x\] /gim, '☑ ')
}
