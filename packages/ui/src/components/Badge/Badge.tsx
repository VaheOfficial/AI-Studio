import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'
import s from './Badge.module.css'

export type BadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info'

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
  /** Custom color (overrides tone), e.g. "var(--hue-voice)". */
  color?: string
  dot?: boolean
  pulse?: boolean
  icon?: ReactNode
  size?: 'sm' | 'md'
}

export function Badge({ tone = 'neutral', color, dot, pulse, icon, size = 'md', className, style, children, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(s.badge, s[tone], s[size], color && s.custom, className)}
      style={color ? { ...style, ['--c' as string]: color } : style}
      {...rest}
    >
      {dot && <span className={cn(s.dot, pulse && s.pulse)} />}
      {icon}
      {children}
    </span>
  )
}

export interface StatusDotProps {
  status: 'idle' | 'active' | 'busy' | 'error' | 'off'
  className?: string
  label?: string
}

/** Small live indicator; "active" and "busy" pulse. */
export function StatusDot({ status, className, label }: StatusDotProps) {
  return <span role="img" aria-label={label ?? status} data-status={status} className={cn(s.status, className)} />
}
