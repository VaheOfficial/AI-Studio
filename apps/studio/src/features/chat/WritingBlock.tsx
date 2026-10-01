import { useState, type ReactNode } from 'react'
import { AtSign, Check, Copy, Download, FileText, Mail, MessageSquare, PenLine, Pencil, Send } from 'lucide-react'
import { Button, SegmentedControl, Spinner, Textarea } from '@studio/ui'
import { plainText, type WritingBlockData, type WritingVariant } from './writing'
import s from './WritingBlock.module.css'

const META: Record<WritingVariant, { icon: ReactNode; label: string; ext: string }> = {
  email: { icon: <Mail size={14} />, label: 'Email', ext: 'txt' },
  chat_message: { icon: <MessageSquare size={14} />, label: 'Message', ext: 'txt' },
  social_post: { icon: <AtSign size={14} />, label: 'Post', ext: 'txt' },
  document: { icon: <FileText size={14} />, label: 'Document', ext: 'md' },
  standard: { icon: <PenLine size={14} />, label: 'Draft', ext: 'md' },
}

const PLAIN = new Set<WritingVariant>(['email', 'chat_message', 'social_post'])

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const safeName = (s: string) => s.replace(/[\\/:*?"<>|]+/g, ' ').trim().slice(0, 80) || 'draft'

/** A finished piece of writing as a card: pick an option, edit, copy, download or open it in the mail app. */
export function WritingBlock({ block, render }: { block: WritingBlockData; render: (md: string) => ReactNode }) {
  const meta = META[block.variant]
  const [pick, setPick] = useState(0)
  const option = block.options[Math.min(pick, block.options.length - 1)] ?? { text: '' }
  const [edits, setEdits] = useState<Record<number, string>>({})
  const [editing, setEditing] = useState(false)
  const [copied, setCopied] = useState(false)
  const text = edits[pick] ?? option.text
  const subject = option.subject ?? block.attrs.subject
  const title = block.variant === 'document' ? block.attrs.title : subject

  const copy = () => {
    void navigator.clipboard.writeText(block.variant === 'document' ? text : plainText(text))
    setCopied(true)
    setTimeout(() => setCopied(false), 1400)
  }
  const mail = () => {
    const to = block.attrs.recipient ?? ''
    const q = new URLSearchParams()
    if (subject) q.set('subject', subject)
    q.set('body', plainText(text))
    window.location.href = `mailto:${encodeURIComponent(to)}?${q.toString().replace(/\+/g, '%20')}`
  }

  return (
    <div className={s.card} data-variant={block.variant}>
      <div className={s.head}>
        <span className={s.kind}>
          {meta.icon}
          {meta.label}
        </span>
        {title && <span className={s.title}>{title}</span>}
        {block.open && <Spinner size={12} />}
      </div>
      {block.options.length > 1 && (
        <SegmentedControl<string>
          size="sm"
          value={String(pick)}
          onValueChange={(v) => {
            setPick(Number(v))
            setEditing(false)
          }}
          segments={block.options.map((o, i) => ({ value: String(i), label: o.title ?? `Option ${i + 1}` }))}
        />
      )}
      {block.variant === 'email' && (block.attrs.recipient || subject) && (
        <div className={s.fields}>
          {block.attrs.recipient && (
            <span>
              <b>To</b> {block.attrs.recipient}
            </span>
          )}
          {subject && (
            <span>
              <b>Subject</b> {subject}
            </span>
          )}
        </div>
      )}
      {editing ? (
        <Textarea autoResize minRows={4} maxRows={30} value={text} onChange={(e) => setEdits((x) => ({ ...x, [pick]: e.target.value }))} />
      ) : (
        <div className={s.body}>
          {/* Emails, messages and posts are plain text: keep their line breaks; documents are markdown */}
          {PLAIN.has(block.variant) ? <div className={s.plain}>{plainText(text)}</div> : render(text)}
        </div>
      )}
      {!block.open && (
        <div className={s.actions}>
          <Button size="sm" variant="secondary" iconLeft={copied ? <Check /> : <Copy />} onClick={copy}>
            {copied ? 'Copied' : 'Copy'}
          </Button>
          <Button size="sm" variant="ghost" iconLeft={editing ? <Check /> : <Pencil />} onClick={() => setEditing(!editing)}>
            {editing ? 'Done' : 'Edit'}
          </Button>
          {block.variant === 'email' && (
            <Button size="sm" variant="ghost" iconLeft={<Send />} onClick={mail}>
              Open in mail app
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            iconLeft={<Download />}
            onClick={() => download(`${safeName(title ?? meta.label)}.${meta.ext}`, meta.ext === 'txt' ? plainText(text) : text)}
          >
            Download
          </Button>
        </div>
      )}
    </div>
  )
}
