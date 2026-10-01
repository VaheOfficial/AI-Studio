import { useId, type ReactNode } from 'react'
import { cn } from '../../lib/cn'
import s from './Field.module.css'

export interface FieldProps {
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  /** Right-aligned content on the label row (e.g. current slider value). */
  aside?: ReactNode
  className?: string
  /** Render-prop receives the generated id to wire up htmlFor. */
  children: ReactNode | ((id: string) => ReactNode)
}

export function Field({ label, hint, error, aside, className, children }: FieldProps) {
  const id = useId()
  return (
    <div className={cn(s.field, className)}>
      <div className={s.row}>
        <label htmlFor={id} className={s.label}>
          {label}
        </label>
        {aside && <span className={s.aside}>{aside}</span>}
      </div>
      {typeof children === 'function' ? children(id) : children}
      {error ? <p className={s.error}>{error}</p> : hint ? <p className={s.hint}>{hint}</p> : null}
    </div>
  )
}
