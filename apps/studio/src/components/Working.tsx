import { motion } from 'motion/react'
import { Logo, Progress, ScrambleText, SignalWave } from '@studio/ui'
import s from './Working.module.css'

/**
 * A result that is still being made, shown where it will land: the logo at work, a live signal in the area's
 * hue behind the text, and the job's own progress.
 */
export function WorkingCard({ hue, title, message, progress }: { hue: string; title: string; message?: string; progress: number }) {
  return (
    <motion.div
      layout
      className={s.card}
      style={{ ['--hue' as string]: hue }}
      initial={{ opacity: 0, y: -10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, height: 0, marginBottom: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 26 }}
    >
      <SignalWave className={s.wave} />
      <span className={s.mark}>
        <Logo size={48} mode="working" />
      </span>
      <div className={s.text}>
        <span className={s.title}>{title}</span>
        <ScrambleText className={s.message} text={message ?? 'Working…'} duration={420} />
        <Progress value={progress >= 0 ? progress : null} size="xs" />
      </div>
      <span className={s.pct}>{progress >= 0 ? `${Math.round(progress * 100)}%` : ''}</span>
    </motion.div>
  )
}
