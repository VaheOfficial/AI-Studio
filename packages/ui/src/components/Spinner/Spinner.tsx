import type { CSSProperties } from 'react'
import { cn } from '../../lib/cn'
import s from './Spinner.module.css'

export interface SpinnerProps {
  size?: number
  className?: string
  label?: string
}

/** A comet chasing its tail, in the current text color. For small inline waits; pages use `Loader`. */
export function Spinner({ size = 16, className, label = 'Loading' }: SpinnerProps) {
  const style = { width: size, height: size, ['--w' as string]: `${Math.max(1.5, size * 0.13)}px` } as CSSProperties
  return <span role="status" aria-label={label} className={cn(s.spinner, className)} style={style} />
}
