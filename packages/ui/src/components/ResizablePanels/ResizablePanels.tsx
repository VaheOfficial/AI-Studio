import { useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { cn } from '../../lib/cn'
import s from './ResizablePanels.module.css'

export interface ResizablePanelsProps {
  /** Main pane (flexes). */
  main: ReactNode
  /** Side pane on the right; `null` hides it and its handle. */
  side: ReactNode | null
  /** Side pane width in px (what the user chose; narrower when the window can't fit it next to `mainMin`). */
  size: number
  onSizeChange: (size: number) => void
  /** Smallest side pane width the handle allows. */
  min?: number
  /** Width the main pane keeps before the side pane gives way. */
  mainMin?: number
  /** Upper bound as a fraction of the container width. */
  maxFraction?: number
  className?: string
}

/** Horizontal split with a draggable (and keyboard-adjustable) divider. The main pane keeps `mainMin` px: in a
 * narrow window the side pane shrinks first, down to an even split. */
export function ResizablePanels({
  main,
  side,
  size,
  onSizeChange,
  min = 280,
  mainMin = 400,
  maxFraction = 0.75,
  className,
}: ResizablePanelsProps) {
  const root = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  const [width, setWidth] = useState<number>()

  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    setWidth(el.offsetWidth)
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const total = () => root.current?.offsetWidth ?? window.innerWidth
  const clamp = (px: number) => {
    const w = total()
    return Math.round(Math.min(Math.max(px, min), w * maxFraction, Math.max(w - mainMin, min)))
  }
  // What the side pane gets now: the chosen size, minus what the main pane needs, but never less than an even split
  const shown = width === undefined ? size : Math.round(Math.min(size, Math.max(width - mainMin, Math.min(min, width / 2))))

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    setDragging(true)
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging || !root.current) return
    const rect = root.current.getBoundingClientRect()
    onSizeChange(clamp(rect.right - e.clientX))
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 64 : 16
    if (e.key === 'ArrowLeft') onSizeChange(clamp(shown + step))
    else if (e.key === 'ArrowRight') onSizeChange(clamp(shown - step))
    else return
    e.preventDefault()
  }

  return (
    <div ref={root} className={cn(s.panels, dragging && s.dragging, className)}>
      <div className={s.main}>{main}</div>
      {side !== null && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-valuenow={shown}
            aria-label="Resize panel"
            tabIndex={0}
            className={s.handle}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={() => setDragging(false)}
            onPointerCancel={() => setDragging(false)}
            onKeyDown={onKeyDown}
          />
          <div className={s.side} style={{ width: shown }}>
            {side}
          </div>
        </>
      )}
    </div>
  )
}
