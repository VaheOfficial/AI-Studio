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
  /** Leans toward the pointer in 3D while hovered. */
  tilt?: boolean
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { variant = 'surface', padding = 'md', spotlight, tint, interactive, tilt, className, style, onPointerMove, onPointerLeave, ...rest },
  ref,
) {
  const handleMove = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      onPointerMove?.(e)
      if (!spotlight && !tilt) return
      const el = e.currentTarget
      const r = el.getBoundingClientRect()
      const x = e.clientX - r.left
      const y = e.clientY - r.top
      if (spotlight) {
        el.style.setProperty('--mx', `${x}px`)
        el.style.setProperty('--my', `${y}px`)
      }
      if (tilt) {
        // Up to 7 degrees, away from the corner the pointer is over
        el.style.setProperty('--ry', `${((x / r.width) * 2 - 1) * 7}deg`)
        el.style.setProperty('--rx', `${(1 - (y / r.height) * 2) * 7}deg`)
      }
    },
    [spotlight, tilt, onPointerMove],
  )
  const handleLeave = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      onPointerLeave?.(e)
      if (!tilt) return
      e.currentTarget.style.setProperty('--rx', '0deg')
      e.currentTarget.style.setProperty('--ry', '0deg')
    },
    [tilt, onPointerLeave],
  )

  return (
    <div
      ref={ref}
      data-padding={padding}
      className={cn(s.card, s[variant], spotlight && s.spotlight, interactive && s.interactive, tilt && s.tilt, className)}
      style={tint ? { ...style, ['--tint' as string]: tint } : style}
      onPointerMove={handleMove}
      onPointerLeave={handleLeave}
      {...rest}
    />
  )
})
