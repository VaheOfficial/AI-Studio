import { forwardRef, useCallback, type HTMLAttributes, type PointerEvent } from 'react'
import { cn } from '../../lib/cn'
import s from './Card.module.css'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'surface' | 'glass' | 'outline' | 'elevated'
  padding?: 'none' | 'sm' | 'md' | 'lg'
  /** Radial highlight that follows the cursor. */
  spotlight?: boolean
  /** CSS color for spotlight/glow tint, e.g. "var(--hue-image)". */
  tint?: string
  interactive?: boolean
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { variant = 'surface', padding = 'md', spotlight, tint, interactive, className, style, onPointerMove, ...rest },
  ref,
) {
  const handleMove = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      onPointerMove?.(e)
      if (!spotlight) return
      const r = e.currentTarget.getBoundingClientRect()
      e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
      e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
    },
    [spotlight, onPointerMove],
  )

  return (
    <div
      ref={ref}
      data-padding={padding}
      className={cn(s.card, s[variant], spotlight && s.spotlight, interactive && s.interactive, className)}
      style={tint ? { ...style, ['--tint' as string]: tint } : style}
      onPointerMove={handleMove}
      {...rest}
    />
  )
})
