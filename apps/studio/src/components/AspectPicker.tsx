import type { CSSProperties } from 'react'
import { motion } from 'motion/react'
import { cn } from '@studio/ui'
import s from './AspectPicker.module.css'

export interface AspectPickerProps<A extends string> {
  /** Ratios like "16:9"; each tile shows its actual proportions. */
  aspects: readonly A[]
  value: A | null
  onChange: (a: A) => void
  /** Accent of the selected tile (a `--hue-*` var). */
  hue?: string
  /** Distinct per page, so the selection highlight animates only within one picker. */
  layoutId?: string
}

const ratio = (a: string) => {
  const [w, h] = a.split(':').map(Number)
  return w / h
}

/** Visual ratio tiles — each shows its actual proportions. */
export function AspectPicker<A extends string>({ aspects, value, onChange, hue, layoutId = 'aspect-active' }: AspectPickerProps<A>) {
  const style = { '--count': aspects.length, ...(hue ? { '--tile-hue': hue } : {}) } as CSSProperties
  return (
    <div className={s.grid} role="radiogroup" aria-label="Aspect ratio" style={style}>
      {aspects.map((a) => {
        const r = ratio(a)
        const scale = 22 / Math.max(r, 1)
        const active = a === value
        return (
          <button
            key={a}
            type="button"
            role="radio"
            aria-checked={active}
            className={cn(s.tile, active && s.active)}
            onClick={() => onChange(a)}
          >
            {active && <motion.span layoutId={layoutId} className={s.bg} transition={{ type: 'spring', stiffness: 500, damping: 36 }} />}
            <span className={s.shape} style={{ width: r * scale, height: scale }} />
            <span className={s.label}>{a}</span>
          </button>
        )
      })}
    </div>
  )
}
