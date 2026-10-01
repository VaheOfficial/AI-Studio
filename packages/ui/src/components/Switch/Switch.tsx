import type { ReactNode } from 'react'
import { Switch as R } from 'radix-ui'
import { cn } from '../../lib/cn'
import s from './Switch.module.css'

export interface SwitchProps {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  id?: string
  disabled?: boolean
  label?: ReactNode
  description?: ReactNode
  className?: string
}

export function Switch({ checked, onCheckedChange, id, disabled, label, description, className }: SwitchProps) {
  const control = (
    <R.Root id={id} checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} className={s.root}>
      <R.Thumb className={s.thumb} />
    </R.Root>
  )
  if (!label) return control
  return (
    <label className={cn(s.row, disabled && s.disabled, className)}>
      <span className={s.text}>
        <span className={s.label}>{label}</span>
        {description && <span className={s.description}>{description}</span>}
      </span>
      {control}
    </label>
  )
}
