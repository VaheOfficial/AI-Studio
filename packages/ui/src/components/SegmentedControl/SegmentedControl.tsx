import { useId, type ReactNode } from 'react'
import { RadioGroup } from 'radix-ui'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'
import s from './SegmentedControl.module.css'

export interface Segment<V extends string = string> {
  value: V
  label: ReactNode
  icon?: ReactNode
  title?: string
}

export interface SegmentedControlProps<V extends string = string> {
  value: V
  onValueChange: (value: V) => void
  segments: Segment<V>[]
  size?: 'sm' | 'md'
  block?: boolean
  className?: string
  'aria-label'?: string
}

/** A radio group that looks like a toggle with a sliding thumb. */
export function SegmentedControl<V extends string = string>({
  value,
  onValueChange,
  segments,
  size = 'md',
  block,
  className,
  ...aria
}: SegmentedControlProps<V>) {
  const layoutId = useId()
  return (
    <RadioGroup.Root
      value={value}
      onValueChange={(v) => onValueChange(v as V)}
      orientation="horizontal"
      loop
      className={cn(s.root, s[size], block && s.block, className)}
      aria-label={aria['aria-label']}
    >
      {segments.map((seg) => (
        <RadioGroup.Item key={seg.value} value={seg.value} className={s.item} title={seg.title}>
          {value === seg.value && (
            <motion.span layoutId={layoutId} className={s.thumb} transition={{ type: 'spring', stiffness: 520, damping: 40 }} />
          )}
          <span className={s.inner}>
            {seg.icon}
            {seg.label}
          </span>
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  )
}
