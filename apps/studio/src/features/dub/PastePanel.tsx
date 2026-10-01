import { useEffect, useMemo, useRef, useState } from 'react'
import { ClipboardPaste, FileUp, X } from 'lucide-react'
import { Badge, Button, IconButton, Textarea } from '@studio/ui'
import type { DubSubtitleCue } from '../../api/contracts/dub'
import { useLanguageName } from '../../api/voice'
import { parseSubtitles } from './api'
import { setText, textOf, useDubEditor } from './editor'
import { buildPastePlan, detectPasteMode } from './paste'
import s from './Panels.module.css'

/** Paste a translation made elsewhere (SRT/VTT, numbered or plain lines) onto the existing segments. */
export function PastePanel({ lang, onClose }: { lang: string; onClose: () => void }) {
  const languageName = useLanguageName()
  const segments = useDubEditor((st) => st.segments)
  const edit = useDubEditor((st) => st.edit)
  const [text, setTextValue] = useState('')
  const [cues, setCues] = useState<DubSubtitleCue[] | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const mode = detectPasteMode(text)

  useEffect(() => {
    if (mode !== 'timestamped') return
    let alive = true
    const t = setTimeout(() => {
      parseSubtitles(text)
        .then((r) => alive && setCues(r.cues))
        .catch(() => alive && setCues([]))
    }, 300)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [text, mode])

  const plan = useMemo(
    () => buildPastePlan(text, segments.map((seg) => ({ id: seg.id, start: seg.start, end: seg.end, text: textOf(seg, lang) })), mode === 'timestamped' ? cues : null),
    [text, segments, lang, cues, mode],
  )

  const apply = () => {
    const byId = new Map(plan.rows.filter((r) => r.after != null).map((r) => [r.id, r.after!]))
    edit((segs) => segs.map((seg) => (byId.has(seg.id) ? setText(seg, lang, byId.get(seg.id)!) : seg)))
    onClose()
  }

  return (
    <section className={s.panel}>
      <header className={s.panelHead}>
        <ClipboardPaste size={15} />
        <strong>Paste translation</strong>
        <span className={s.panelHint}>Into {lang ? languageName(lang) : 'the transcript'} — timing and the source text stay untouched.</span>
        <IconButton size="sm" label="Close" icon={<X />} onClick={onClose} />
      </header>
      <Textarea
        mono
        autoResize
        minRows={4}
        maxRows={12}
        value={text}
        placeholder={'Paste an SRT/VTT, numbered lines ("1. …") or one line per segment'}
        onChange={(e) => setTextValue(e.target.value)}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          const f = e.dataTransfer.files[0]
          if (f) void f.text().then(setTextValue)
        }}
      />
      <div className={s.pasteBar}>
        <Button size="sm" variant="ghost" iconLeft={<FileUp />} onClick={() => fileInput.current?.click()}>
          Load file
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept=".srt,.vtt,.txt"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void f.text().then(setTextValue)
            e.target.value = ''
          }}
        />
        {text.trim() && (
          <>
            <Badge size="sm">{mode}</Badge>
            <span className={s.panelHint}>
              {plan.matched} of {plan.rows.length} matched{plan.unused ? ` · ${plan.unused} unused` : ''}
            </span>
          </>
        )}
        <span className={s.grow} />
        <Button size="sm" variant="primary" disabled={!plan.matched} onClick={apply}>
          Apply {plan.matched || ''}
        </Button>
      </div>
      {text.trim() && (
        <div className={s.planRows}>
          {plan.rows.slice(0, 120).map((r) => (
            <div key={r.id} className={s.planRow} data-unmatched={r.after == null || undefined}>
              <span className={s.planIndex}>{r.index + 1}</span>
              <span className={s.planBefore}>{r.before || '—'}</span>
              <span>{r.after ?? 'unmatched'}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
