import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'
import s from './Progress.module.css'

export interface ProgressProps {
  /** 0..1, or null/negative for indeterminate. */
  value: number | null
  size?: 'xs' | 'sm' | 'md'
  tone?: 'accent' | 'success' | 'danger' | 'warning'
  className?: string
  'aria-label'?: string
}

export function Progress({ value, size = 'sm', tone = 'accent', className, ...aria }: ProgressProps) {
  const indeterminate = value == null || value < 0
  const pct = indeterminate ? 0 : Math.min(1, Math.max(0, value)) * 100
  return (
    <div
      role="progressbar"
      aria-label={aria['aria-label']}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      className={cn(s.track, s[size], s[tone], className)}
    >
      {indeterminate ? (
        <div className={s.indeterminate} />
      ) : (
        <motion.div
          className={s.bar}
          initial={false}
          animate={{ width: `${pct}%` }}
          transition={{ type: 'spring', stiffness: 120, damping: 24 }}
        />
      )}
    </div>
  )
}

export interface ProgressRingProps {
  value: number | null
  size?: number
  stroke?: number
  className?: string
  children?: ReactNode
}

export function ProgressRing({ value, size = 36, stroke = 3, className, children }: ProgressRingProps) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const indeterminate = value == null || value < 0
  return (
    <div className={cn(s.ring, indeterminate && s.ringSpin, className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className={s.ringTrack} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          className={s.ringBar}
          strokeDasharray={c}
          initial={false}
          animate={{ strokeDashoffset: indeterminate ? c * 0.72 : c * (1 - Math.min(1, Math.max(0, value))) }}
          transition={{ type: 'spring', stiffness: 100, damping: 22 }}
        />
      </svg>
      {children && <div className={s.ringLabel}>{children}</div>}
    </div>
  )
}
