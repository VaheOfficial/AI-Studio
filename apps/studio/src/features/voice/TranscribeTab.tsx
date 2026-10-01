import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check, Circle, Copy, Ear, Square, Upload } from 'lucide-react'
import { Badge, Button, EmptyState, LiveWaveform, cn } from '@studio/ui'
import { useTranscribe } from '../../api/hooks'
import type { TranscribeResult } from '../../api/types'
import { ModelPicker } from '../../components/ModelPicker'
import { useModelChoice } from '../../components/useModelChoice'
import { DictationCard } from './DictationCard'
import { useRecorder } from './useRecorder'
import s from './TranscribeTab.module.css'

const ts = (t: number) => `${Math.floor(t / 60)}:${Math.floor(t % 60).toString().padStart(2, '0')}`

export function TranscribeTab() {
  const { models, selected, select, isLoading, unavailable } = useModelChoice('stt', 'stt', undefined, 'stt')
  const transcribe = useTranscribe()
  const rec = useRecorder()
  const [result, setResult] = useState<TranscribeResult | null>(null)
  const [dragging, setDragging] = useState(false)
  const [copied, setCopied] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const { mutate } = transcribe
  const run = useCallback(
    (file: Blob) => {
      if (!selected) return
      setResult(null)
      mutate({ file, modelId: selected.id }, { onSuccess: setResult })
    },
    [selected, mutate],
  )

  // A finished recording is transcribed immediately (only on a new blob, not on model change)
  const runRef = useRef(run)
  useEffect(() => {
    runRef.current = run
  }, [run])
  useEffect(() => {
    if (rec.blob) runRef.current(rec.blob)
  }, [rec.blob])

  return (
    <div className={s.page}>
      <div className={s.top}>
        <div className={s.picker}>
          <ModelPicker kind="stt" label="Transcription model" models={models} selected={selected} onSelect={select} isLoading={isLoading} unavailable={unavailable} />
        </div>
      </div>

      <DictationCard model={selected} />

      <div
        className={cn(s.drop, dragging && s.dragging, rec.recording && s.recording)}
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
        {rec.recording ? (
          <>
            <LiveWaveform stream={rec.stream} height={72} color="var(--hue-stt)" />
            <div className={s.actions}>
              <span className={s.timer}>{rec.elapsed.toFixed(1)}s</span>
              <Button variant="danger" iconLeft={<Square fill="currentColor" />} onClick={rec.stop}>
                Stop & transcribe
              </Button>
            </div>
          </>
        ) : (
          <>
            <span className={s.dropIcon}>
              <Ear />
            </span>
            <p className={s.dropTitle}>Drop audio or video here</p>
            <p className={s.dropSub}>Any common format. Language is detected automatically.</p>
            <div className={s.actions}>
              <Button variant="secondary" iconLeft={<Upload />} disabled={!selected} onClick={() => fileInput.current?.click()}>
                Choose file
              </Button>
              <Button variant="secondary" iconLeft={<Circle fill="var(--danger)" color="var(--danger)" />} disabled={!selected} onClick={() => void rec.start()}>
                Record
              </Button>
            </div>
            <input ref={fileInput} type="file" accept="audio/*,video/*" hidden onChange={(e) => e.target.files?.[0] && run(e.target.files[0])} />
          </>
        )}
      </div>
      {rec.error && <p className={s.error}>{rec.error}</p>}

      <AnimatePresence mode="wait">
        {transcribe.isPending ? (
          <motion.div key="busy" className={s.busy} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <span className={s.shimmer}>Transcribing…</span>
          </motion.div>
        ) : result ? (
          <motion.div key="result" className={s.result} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            <div className={s.resultHead}>
              <Badge tone="info">{result.language}</Badge>
              <span className={s.resultMeta}>{result.segments.length} segments</span>
              <Button
                size="sm"
                variant="ghost"
                iconLeft={copied ? <Check /> : <Copy />}
                onClick={() => {
                  void navigator.clipboard.writeText(result.text)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 1400)
                }}
              >
                {copied ? 'Copied' : 'Copy text'}
              </Button>
            </div>
            <div className={s.segments}>
              {result.segments.map((seg, i) => (
                <motion.div key={i} className={s.segment} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(i * 0.02, 0.6) }}>
                  <span className={s.time}>{ts(seg.start)}</span>
                  <span>{seg.text.trim()}</span>
                </motion.div>
              ))}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
      {!result && !transcribe.isPending && models.length > 0 && (
        <EmptyState tint="var(--hue-stt)" title="No transcript yet" description="Timestamps and language detection appear here." />
      )}
    </div>
  )
}
