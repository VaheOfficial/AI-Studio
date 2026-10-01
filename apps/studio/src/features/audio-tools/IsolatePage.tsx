import { useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Layers, Upload } from 'lucide-react'
import { AudioPlayer, Badge, Button, ChipGroup, EmptyState, Progress, cn } from '@studio/ui'
import { useOutputs } from '../../api/hooks'
import { useJob } from '../../api/live'
import type { Output } from '../../api/types'
import { timeAgo } from '../../lib/format'
import { RuntimeGate } from '../dub/RuntimeGate'
import { useIsolate, type IsolateMode } from './api'
import s from './Tools.module.css'

const MODES: { value: IsolateMode; label: string; hint: string }[] = [
  { value: 'vocals', label: 'Vocals + instrumental', hint: 'htdemucs two-stem — clean dialogue or a karaoke track.' },
  { value: 'stems4', label: '4 stems', hint: 'htdemucs: vocals, drums, bass, other.' },
  { value: 'stems4_ft', label: '4 stems (fine-tuned)', hint: 'htdemucs_ft: best quality, ~4× slower.' },
  { value: 'stems6', label: '6 stems', hint: 'htdemucs_6s: adds guitar and piano.' },
]

/** Demucs source separation. Voice → Tools → Isolate and Music → Stems share this page. */
function Separator({ hue, defaultMode, title, subtitle }: { hue: string; defaultMode: IsolateMode; title: string; subtitle: string }) {
  const isolate = useIsolate()
  const [mode, setMode] = useState<IsolateMode>(defaultMode)
  const [jobId, setJobId] = useState<string>()
  const [dragging, setDragging] = useState(false)
  const job = useJob(jobId)
  const fileInput = useRef<HTMLInputElement>(null)
  const { data: outputs = [] } = useOutputs('audio')
  const history = outputs.filter((o) => o.params.tool === 'isolate')
  const groups = new Map<string, Output[]>()
  for (const o of history) {
    const key = `${o.params.source}|${o.created_at.slice(0, 16)}`
    groups.set(key, [...(groups.get(key) ?? []), o])
  }
  const run = (file: File) => isolate.mutate({ file, mode }, { onSuccess: (j) => setJobId(j.id) })
  const running = job && (job.status === 'running' || job.status === 'queued')

  return (
    <div className={s.page} style={{ ['--hue' as string]: hue }}>
      <header className={s.header}>
        <span className={s.headerIcon}>
          <Layers />
        </span>
        <div>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
      </header>
      <RuntimeGate />
      <ChipGroup value={mode} onValueChange={setMode} chips={MODES.map((m) => ({ value: m.value, label: m.label, color: hue }))} />
      <p className={s.hint}>{MODES.find((m) => m.value === mode)?.hint}</p>
      <div
        className={cn(s.drop, dragging && s.dragging)}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const f = e.dataTransfer.files[0]
          if (f) run(f)
        }}
      >
        {running ? (
          <div className={s.progress}>
            <span>{job.message ?? 'Queued'}</span>
            <Progress value={job.progress} size="sm" />
          </div>
        ) : (
          <>
            <Upload className={s.dropIcon} />
            <strong>Drop a song, recording or video</strong>
            <Button variant="secondary" iconLeft={<Upload />} loading={isolate.isPending} onClick={() => fileInput.current?.click()}>
              Choose file
            </Button>
          </>
        )}
        <input
          ref={fileInput}
          type="file"
          hidden
          accept="audio/*,video/*"
          onChange={(e) => {
            if (e.target.files?.[0]) run(e.target.files[0])
            e.target.value = ''
          }}
        />
      </div>
      {groups.size === 0 ? (
        <EmptyState tint={hue} title="No separations yet" description="Stems appear here, ready to play and download." />
      ) : (
        <AnimatePresence initial={false}>
          {[...groups.entries()].map(([key, stems]) => (
            <motion.section key={key} className={s.result} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
              <div className={s.resultHead}>
                <strong>{String(stems[0].params.source)}</strong>
                <Badge size="sm">{stems.length} stems</Badge>
                <span className={s.hint}>{timeAgo(stems[0].created_at)}</span>
              </div>
              {stems.map((o) => (
                <div key={o.id} className={s.stem}>
                  <span className={s.stemName}>{o.prompt.split(' · ')[0]}</span>
                  <AudioPlayer src={o.url} color={hue} downloadName={`${o.prompt.replace(/[^\w\- ]+/g, '').trim()}.wav`} />
                </div>
              ))}
            </motion.section>
          ))}
        </AnimatePresence>
      )}
    </div>
  )
}

export function IsolateTab() {
  return <Separator hue="var(--hue-voice)" defaultMode="vocals" title="Isolate" subtitle="Split speech from music and noise with Demucs." />
}

export function StemsTab() {
  return <Separator hue="var(--hue-music)" defaultMode="stems4" title="Stems" subtitle="Split a song into vocals, drums, bass and more with Demucs." />
}
