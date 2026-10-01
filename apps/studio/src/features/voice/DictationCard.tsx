import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check, Copy, Mic, Square, X } from 'lucide-react'
import { Badge, Button, LiveWaveform, cn } from '@studio/ui'
import type { InstalledModel } from '../../api/types'
import { useDictation } from './useDictation'
import s from './DictationCard.module.css'

const STAGE_LABEL = { idle: '', connecting: 'Connecting…', loading: 'Loading model…', listening: 'Listening', finishing: 'Finishing…' }

/** Live dictation: partial text while you speak, committed at each pause. Needs a faster-whisper model. */
export function DictationCard({ model }: { model: InstalledModel | undefined }) {
  const usable = model?.runtime === 'faster-whisper'
  const d = useDictation(usable ? model.id : undefined)
  const [copied, setCopied] = useState(false)
  const live = d.stage !== 'idle'
  const text = d.finals.join(' ')

  return (
    <section className={cn(s.card, live && s.live)}>
      <div className={s.head}>
        <span className={s.icon}>
          <Mic size={16} />
        </span>
        <div className={s.titles}>
          <span className={s.title}>Live dictation</span>
          <span className={s.sub}>{usable ? `Speak naturally — text appears as you talk (${model.name}).` : 'Pick a local Whisper model to dictate live.'}</span>
        </div>
        {live && (
          <Badge tone={d.stage === 'listening' ? 'success' : 'warning'} dot pulse>
            {STAGE_LABEL[d.stage]}
          </Badge>
        )}
        {live ? (
          <>
            <Button size="sm" variant="danger" iconLeft={<Square fill="currentColor" />} disabled={d.stage === 'finishing'} onClick={d.stop}>
              Stop
            </Button>
            <Button size="sm" variant="ghost" iconLeft={<X />} onClick={d.cancel}>
              Cancel
            </Button>
          </>
        ) : (
          <Button size="sm" variant="primary" iconLeft={<Mic />} disabled={!usable} onClick={() => void d.start()}>
            Start dictation
          </Button>
        )}
      </div>
      {d.stream && <LiveWaveform stream={d.stream} height={40} color="var(--hue-stt)" />}
      {d.error && <p className={s.error}>{d.error}</p>}
      <AnimatePresence>
        {(text || d.partial) && (
          <motion.div className={s.text} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
            <p>
              {text} <span className={s.partial}>{d.partial}</span>
            </p>
            {!live && text && (
              <Button
                size="sm"
                variant="ghost"
                iconLeft={copied ? <Check /> : <Copy />}
                onClick={() => {
                  void navigator.clipboard.writeText(text)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 1400)
                }}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}
