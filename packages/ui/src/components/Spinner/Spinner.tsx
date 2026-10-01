import { cn } from '../../lib/cn'
import s from './Spinner.module.css'

export interface SpinnerProps {
  size?: number
  className?: string
  label?: string
}

export function Spinner({ size = 16, className, label = 'Loading' }: SpinnerProps) {
  return (
    <span role="status" aria-label={label} className={cn(s.spinner, className)} style={{ width: size, height: size }}>
      <svg viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="9.5" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.5" />
        <path d="M21.5 12a9.5 9.5 0 0 0-9.5-9.5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    </span>
  )
}
