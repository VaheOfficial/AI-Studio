import { memo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowLeftToLine, ArrowRightToLine, ChevronRight, Clock, Headphones, MoreHorizontal, Scissors, Trash2 } from 'lucide-react'
import { Badge, Button, Field, IconButton, Input, Menu, Select, Spinner, Textarea, Tooltip, cn, type SelectGroup } from '@studio/ui'
import type { DubLine } from '../../api/contracts/dub'
import { insertAfter, mergeSegments, setText, splitSegment, textOf, useDubEditor, type EditSegment } from './editor'
import { fmtClock } from './format'
import { usePlayback } from './playback'
import s from './SegmentRow.module.css'

export interface SegmentRowProps {
  seg: EditSegment
  index: number
  /** Server-side state of this line in the editing language (translation errors, plan, fit, QC). */
  line?: DubLine
  lang: string
  speakers: string[]
  color: string
  voiceOptions: SelectGroup[]
  voiceLabel: string
  selected: boolean
  active: boolean
  stale: boolean
  readOnly: boolean
  duration: number
  previewing: boolean
  canPreview: boolean
  onPreview: (id: string) => void
}

const num = (v: string) => (v.trim() === '' ? undefined : Number(v))
const MIN_LINE_S = 0.3

function LineBadges({ line, stale }: { line?: DubLine; stale: boolean }) {
  if (!line && !stale) return null
  const plan = line?.plan
  const fit = line?.fit
  return (
    <>
      {line?.error && (
        <Tooltip content={line.error}>
          <Badge size="sm" tone="danger">
            Error
          </Badge>
        </Tooltip>
      )}
      {line?.degraded && (
        <Tooltip content={line.degraded}>
          <Badge size="sm" tone="warning">
            Fast quality
          </Badge>
        </Tooltip>
      )}
      {plan?.status === 'tight' && (
        <Tooltip content={`Needs ~${plan.est_s.toFixed(1)}s, ${plan.available_s.toFixed(1)}s available`}>
          <Badge size="sm" tone="warning" icon={<Clock size={10} />}>
            Tight
          </Badge>
        </Tooltip>
      )}
      {plan?.status === 'impossible' && (
        <Tooltip content={`Needs ~${plan.est_s.toFixed(1)}s, ${plan.available_s.toFixed(1)}s available`}>
          <Badge size="sm" tone="danger">
            +{plan.overrun_s.toFixed(1)}s over
          </Badge>
        </Tooltip>
      )}
      {fit?.status === 'overflow_trimmed' && (
        <Tooltip content="Doesn't fit even using the silence after it — the end was cut. Shorten the text or regenerate the line.">
          <Badge size="sm" tone="danger" icon={<Scissors size={10} />}>
            Overflows +{(fit.overflow_s ?? 0).toFixed(1)}s
          </Badge>
        </Tooltip>
      )}
      {fit?.status === 'silent' && (
        <Tooltip content="The voice render came out empty, so this line is silent in the dub. Regenerate it.">
          <Badge size="sm" tone="danger">
            No audio
          </Badge>
        </Tooltip>
      )}
      {(fit?.status === 'audio_stretched' || fit?.status === 'hybrid') && fit.audio_rate && (
        <Tooltip content={fit.video_ratio ? `Audio ${fit.audio_rate}× · video slowed ${fit.video_ratio}×` : 'Pitch-preserving speed-up'}>
          <Badge size="sm" tone="info">
            {fit.audio_rate.toFixed(2)}×{fit.video_ratio ? ` · ${fit.video_ratio.toFixed(2)}× video` : ''}
          </Badge>
        </Tooltip>
      )}
      {fit?.status === 'audio_slowed' && (
        <Badge size="sm" tone="info">
          Slowed {fit.audio_rate?.toFixed(2)}×
        </Badge>
      )}
      {fit?.status === 'video_stretched' && fit.video_ratio && (
        <Badge size="sm" tone="info">
          Video {fit.video_ratio.toFixed(2)}×
        </Badge>
      )}
      {line?.qc?.flagged && (
        <Tooltip content={`Heard: “${line.qc.recognized || '—'}” (drift ${line.qc.drift.toFixed(2)})`}>
          <Badge size="sm" tone="warning">
            Verify
          </Badge>
        </Tooltip>
      )}
      {stale && (
        <Tooltip content="Changed since the track was rendered">
          <Badge size="sm" tone="accent" dot>
            Changed
          </Badge>
        </Tooltip>
      )}
    </>
  )
}

/** One transcript/translation line (VoiceStudio dub-page segment row). */
export const SegmentRow = memo(function SegmentRow({
  seg,
  index,
  line,
  lang,
  speakers,
  color,
  voiceOptions,
  voiceLabel,
  selected,
  active,
  stale,
  readOnly,
  duration,
  previewing,
  canPreview,
  onPreview,
}: SegmentRowProps) {
  const edit = useDubEditor((st) => st.edit)
  const toggle = useDubEditor((st) => st.toggleSelected)
  const setActive = useDubEditor((st) => st.setActive)
  const seek = usePlayback((st) => st.seek)
  const caret = useRef(0)
  const [open, setOpen] = useState(false)
  const text = textOf(seg, lang)
  const patch = (fields: Partial<EditSegment>) => edit((segs) => segs.map((x) => (x.id === seg.id ? { ...x, ...fields } : x)))
  // A start past the end moves the whole line (same length); an end is kept ≥ 0.3 s after the start.
  const setStart = (t: number) => {
    if (!Number.isFinite(t)) return
    const start = +Math.max(0, t).toFixed(3)
    const len = seg.end - seg.start
    if (start === seg.start) return
    if (start <= seg.end - MIN_LINE_S) return patch({ start })
    const moved = +Math.max(0, Math.min(start, duration - len)).toFixed(3)
    patch({ start: moved, end: +(moved + len).toFixed(3) })
  }
  const setEnd = (t: number) => {
    if (!Number.isFinite(t)) return
    const end = +Math.min(duration, Math.max(t, seg.start + MIN_LINE_S)).toFixed(3)
    if (end !== seg.end) patch({ end })
  }

  const split = () => edit((segs) => splitSegment(segs, seg.id, lang, caret.current))
  const merge = (dir: -1 | 1) => edit((segs) => mergeSegments(segs, seg.id, dir))
  const remove = () => edit((segs) => segs.filter((x) => x.id !== seg.id))

  return (
    <article className={cn(s.row, active && s.active, selected && s.selected)} style={{ ['--c' as string]: color }} onFocusCapture={() => setActive(seg.id)}>
      <div className={s.gutter}>
        <input type="checkbox" className={s.check} checked={selected} aria-label={`Select line ${index + 1}`} onChange={() => toggle(seg.id)} />
        <button type="button" className={s.time} onClick={() => seek(seg.start)} title="Seek here">
          {fmtClock(seg.start)}
          <span className={s.timeEnd}>{fmtClock(seg.end)}</span>
        </button>
      </div>
      <div className={s.main}>
        <div className={s.head}>
          <button type="button" className={s.speaker} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <ChevronRight size={12} className={cn(s.chevron, open && s.open)} />
            <span className={s.dot} />
            {seg.speaker} · {voiceLabel}
          </button>
          <LineBadges line={line} stale={stale} />
          <span className={s.spacer} />
          <span className={s.actions}>
            {canPreview && (
              <IconButton size="sm" label="Hear this line" icon={previewing ? <Spinner size={13} /> : <Headphones />} disabled={previewing} onClick={() => onPreview(seg.id)} />
            )}
            {!readOnly && (
              <Menu
                trigger={<IconButton size="sm" label="Line actions" icon={<MoreHorizontal />} />}
                items={[
                  { label: 'Split at cursor', shortcut: 'Ctrl+D', onSelect: split },
                  { label: 'Merge with previous', shortcut: 'Ctrl+Shift+M', onSelect: () => merge(-1) },
                  { label: 'Merge with next', shortcut: 'Ctrl+M', onSelect: () => merge(1) },
                  { label: 'Insert line after', onSelect: () => edit((segs) => insertAfter(segs, seg.id, duration)) },
                ]}
              />
            )}
            {!readOnly && <IconButton size="sm" label="Delete line" icon={<Trash2 />} onClick={remove} />}
          </span>
        </div>
        {lang && seg.text !== text && <p className={s.original}>{seg.text}</p>}
        <Textarea
          className={s.text}
          autoResize
          minRows={1}
          maxRows={10}
          value={text}
          readOnly={readOnly}
          placeholder={lang ? 'Not translated yet' : 'Empty line'}
          onChange={(e) => edit((segs) => segs.map((x) => (x.id === seg.id ? setText(x, lang, e.target.value) : x)), `text:${seg.id}:${lang}`)}
          onSelect={(e) => (caret.current = e.currentTarget.selectionStart)}
          onKeyDown={(e) => {
            if (readOnly || !(e.ctrlKey || e.metaKey)) return
            const key = e.key.toLowerCase()
            if (key === 'd') {
              e.preventDefault()
              split()
            } else if (key === 'm') {
              e.preventDefault()
              merge(e.shiftKey ? -1 : 1)
            }
          }}
        />
        {line?.plan?.suggested_text && (
          <div className={s.suggestion}>
            <span>{line.plan.suggested_text}</span>
            <Button size="sm" variant="secondary" disabled={readOnly} onClick={() => edit((segs) => segs.map((x) => (x.id === seg.id ? setText(x, lang, line.plan!.suggested_text!) : x)))}>
              Apply
            </Button>
          </div>
        )}
        <AnimatePresence initial={false}>
          {open && (
            <motion.div className={s.options} initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
              <div className={s.optionsGrid}>
                <Field label="Speaker">
                  {(id) => (
                    <Select id={id} size="sm" disabled={readOnly} value={seg.speaker} onValueChange={(v) => patch({ speaker: v })} options={speakers.map((sp) => ({ value: sp, label: sp }))} />
                  )}
                </Field>
                <Field label="Voice">
                  {(id) => (
                    <Select
                      id={id}
                      size="sm"
                      disabled={readOnly}
                      value={seg.voice ?? '__speaker'}
                      onValueChange={(v) => patch({ voice: v === '__speaker' ? undefined : v })}
                      options={[{ label: 'This line', options: [{ value: '__speaker', label: 'Speaker’s voice' }] }, ...voiceOptions]}
                    />
                  )}
                </Field>
                <Field label="Start (s)">
                  {(id) => (
                    <div className={s.timeField}>
                      <Input
                        key={seg.start}
                        id={id}
                        size="sm"
                        type="number"
                        step={0.01}
                        min={0}
                        readOnly={readOnly}
                        defaultValue={seg.start}
                        onBlur={(e) => setStart(Number(e.target.value))}
                      />
                      {!readOnly && (
                        <IconButton size="sm" label="Start at the playhead (moves the line if it's past the end)" icon={<ArrowRightToLine />} onClick={() => setStart(usePlayback.getState().time)} />
                      )}
                    </div>
                  )}
                </Field>
                <Field label="End (s)">
                  {(id) => (
                    <div className={s.timeField}>
                      <Input
                        key={seg.end}
                        id={id}
                        size="sm"
                        type="number"
                        step={0.01}
                        readOnly={readOnly}
                        defaultValue={seg.end}
                        onBlur={(e) => setEnd(Number(e.target.value))}
                      />
                      {!readOnly && <IconButton size="sm" label="End at the playhead" icon={<ArrowLeftToLine />} onClick={() => setEnd(usePlayback.getState().time)} />}
                    </div>
                  )}
                </Field>
                <Field label="Volume">
                  {(id) => (
                    <Input id={id} size="sm" type="number" step={0.1} min={0} max={2} placeholder="1" readOnly={readOnly} defaultValue={seg.gain ?? ''} onBlur={(e) => patch({ gain: num(e.target.value) })} />
                  )}
                </Field>
                <Field label="Speed">
                  {(id) => (
                    <Input id={id} size="sm" type="number" step={0.05} min={0.5} max={2} placeholder="Global" readOnly={readOnly} defaultValue={seg.speed ?? ''} onBlur={(e) => patch({ speed: num(e.target.value) })} />
                  )}
                </Field>
              </div>
              <Field label="Direction" hint="e.g. urgent, whispered — guides the adaptation and lip-sync pacing">
                {(id) => <Input id={id} size="sm" readOnly={readOnly} defaultValue={seg.direction ?? ''} onBlur={(e) => patch({ direction: e.target.value.trim() || undefined })} />}
              </Field>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </article>
  )
})
