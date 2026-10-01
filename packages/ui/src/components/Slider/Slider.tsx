import { Slider as R } from 'radix-ui'
import { cn } from '../../lib/cn'
import s from './Slider.module.css'

export interface SliderProps {
  value: number
  onValueChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  id?: string
  disabled?: boolean
  className?: string
  'aria-label'?: string
}

export function Slider({ value, onValueChange, min = 0, max = 100, step = 1, id, disabled, className, ...aria }: SliderProps) {
  return (
    <R.Root
      id={id}
      className={cn(s.root, className)}
      value={[value]}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onValueChange={([v]) => onValueChange(v)}
    >
      <R.Track className={s.track}>
        <R.Range className={s.range} />
      </R.Track>
      <R.Thumb className={s.thumb} aria-label={aria['aria-label']} />
    </R.Root>
  )
}
