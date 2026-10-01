import { useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Circle, Scissors, Square, Upload } from 'lucide-react'
import { AudioPlayer, Button, LiveWaveform, SegmentedControl, Spinner, cn } from '@studio/ui'
import type { StagedReference } from '../../api/contracts/voice'
import { useStageReference } from '../../api/voice'
import { useRecorder } from './useRecorder'
import s from './ReferenceInput.module.css'

const SAMPLE_SCRIPT =
  'The quick brown fox jumps over the lazy dog. I spend my mornings walking by the river, and in the evening I like to read a good book with a cup of tea.'

/**
 * Record (with a live level meter) or upload a reference clip; the server normalises it, trims clips over
 * 20 s to the best ~15 s of speech and transcribes it. Calls `onStaged` with the result.
 */
export function ReferenceInput({ staged, onStaged }: { staged: StagedReference | null; onStaged: (ref: StagedReference) => void }) {
  const [source, setSource] = useState<'record' | 'upload'>('record')
  const [dragging, setDragging] = useState(false)
  const stage = useStageReference()
  const send = (file: Blob) => stage.mutate({ file }, { onSuccess: onStaged })
  const rec = useRecorder(send)
  const fileInput = useRef<HTMLInputElement>(null)

  return (
    <div className={s.root}>
      <SegmentedControl<'record' | 'upload'>
        block
        value={source}
        onValueChange={setSource}
        segments={[
          { value: 'record', label: 'Record', icon: <Circle /> },
          { value: 'upload', label: 'Upload file', icon: <Upload /> },
        ]}
      />
        {source === 'record' ? (
          <motion.div key="rec" className={s.recorder} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
            <p className={s.script}>“{SAMPLE_SCRIPT}”</p>
            <div className={cn(s.stage, rec.recording && s.live)}>
              <LiveWaveform stream={rec.stream} height={56} color="var(--hue-voice)" />
            </div>
            <div className={s.bar}>
              <span className={s.timer}>
                {rec.recording && <span className={s.dot} />}
                {rec.elapsed.toFixed(1)}s
              </span>
              {rec.error && <span className={s.warn}>{rec.error}</span>}
              {rec.recording ? (
                <Button size="sm" variant="danger" iconLeft={<Square fill="currentColor" />} onClick={rec.stop} disabled={rec.elapsed < 3}>
                  {rec.elapsed < 3 ? 'Keep talking…' : 'Stop'}
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="secondary"
                  iconLeft={<Circle fill="var(--danger)" color="var(--danger)" />}
                  disabled={stage.isPending}
                  onClick={() => void rec.start()}
                >
                  {staged ? 'Record again' : 'Start recording'}
                </Button>
              )}
            </div>
          </motion.div>
        ) : (
          <motion.div key="up" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
            <button
              type="button"
              className={cn(s.drop, dragging && s.dragging)}
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                const f = e.dataTransfer.files[0]
                if (f) send(f)
              }}
            >
              <Upload size={20} />
              <span>Drop an audio or video file, or click to browse</span>
              <span className={s.sub}>3–20 s of one clear speaker works best; longer clips are trimmed to their best 15 s</span>
            </button>
            <input
              ref={fileInput}
              type="file"
              accept="audio/*,video/*"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) send(f)
                e.target.value = ''
              }}
            />
          </motion.div>
        )}
      {stage.isPending ? (
        <div className={s.busy}>
          <Spinner size={14} /> Preparing the clip — trimming and transcribing…
        </div>
      ) : (
        staged && (
          <div className={s.result}>
            <AudioPlayer src={staged.url} color="var(--hue-voice)" height={40} />
            {staged.trimmed && (
              <span className={s.trimmed}>
                <Scissors size={12} /> Trimmed from {staged.source_duration_s.toFixed(0)} s to the best {staged.duration_s.toFixed(1)} s of speech
              </span>
            )}
          </div>
        )
      )}
    </div>
  )
}
