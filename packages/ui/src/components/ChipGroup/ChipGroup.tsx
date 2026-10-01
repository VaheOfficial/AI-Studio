import type { ReactNode } from 'react'
import { ToggleGroup } from 'radix-ui'
import { cn } from '../../lib/cn'
import s from './ChipGroup.module.css'

export interface Chip<V extends string = string> {
  value: V
  label: ReactNode
  icon?: ReactNode
  /** CSS color for the selected state, e.g. "var(--hue-image)". Defaults to the accent. */
  color?: string
}

export interface ChipGroupProps<V extends string = string> {
  value: V
  onValueChange: (value: V) => void
  chips: Chip<V>[]
  className?: string
  'aria-label'?: string
}

/** A wrapping row of pill filters; exactly one is selected. Suits long option lists a SegmentedControl can't fit. */
export function ChipGroup<V extends string = string>({ value, onValueChange, chips, className, ...aria }: ChipGroupProps<V>) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      // Radix emits "" when the active chip is clicked again; keep one selected.
      onValueChange={(v) => v && onValueChange(v as V)}
      className={cn(s.root, className)}
      aria-label={aria['aria-label']}
    >
      {chips.map((c) => (
        <ToggleGroup.Item
          key={c.value}
          value={c.value}
          className={s.chip}
          style={c.color ? { ['--c' as string]: c.color } : undefined}
        >
          {c.icon}
          {c.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  )
}
