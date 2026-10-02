import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { cn } from '../../lib/cn'
import s from './VirtualGrid.module.css'

export interface MasonryProps<T> {
  items: T[]
  itemKey: (item: T) => string
  /** An item's height as a multiple of its width (1 = square, 0.5625 = 16:9, 1.5 = 2:3 portrait). */
  aspect: (item: T) => number
  renderItem: (item: T, index: number) => ReactNode
  /** Columns are as many as fit at this minimum width. */
  minColumnWidth?: number
  gap?: number
  /** Scrolls by itself and only mounts the items in view, for long lists. Without it, it is as tall as its content. */
  virtual?: boolean
  /** With `virtual`: how far above and below the viewport items stay mounted, in pixels. */
  overscan?: number
  className?: string
}

interface Placed {
  index: number
  x: number
  y: number
  height: number
}

/**
 * Items of different shapes packed into columns of equal width: each goes to the column that is shortest so far,
 * so the columns end near the same height and nothing is cropped to a common shape.
 */
export function Masonry<T>({
  items,
  itemKey,
  aspect,
  renderItem,
  minColumnWidth = 240,
  gap = 12,
  virtual = false,
  overscan = 600,
  className,
}: MasonryProps<T>) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState({ width: 0, height: 0, top: 0 })
  const [scrollTop, setScrollTop] = useState(0)

  useEffect(() => {
    const canvas = canvasRef.current
    const scroller = scrollerRef.current
    if (!canvas) return
    const ro = new ResizeObserver(() =>
      setBox({ width: canvas.clientWidth, height: scroller?.clientHeight ?? 0, top: scroller ? canvas.offsetTop : 0 }),
    )
    ro.observe(canvas)
    if (!scroller) return () => ro.disconnect()
    ro.observe(scroller)
    let frame = 0
    const onScroll = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setScrollTop(scroller.scrollTop))
    }
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      ro.disconnect()
      cancelAnimationFrame(frame)
      scroller.removeEventListener('scroll', onScroll)
    }
  }, [virtual])

  const columns = Math.max(1, Math.floor((box.width + gap) / (minColumnWidth + gap)))
  const columnWidth = box.width > 0 ? (box.width - gap * (columns - 1)) / columns : 0

  const { placed, total } = useMemo(() => {
    const heights = Array.from({ length: columns }, () => 0)
    const out: Placed[] = []
    if (columnWidth <= 0) return { placed: out, total: 0 }
    items.forEach((item, index) => {
      let col = 0
      for (let c = 1; c < columns; c++) if (heights[c] < heights[col] - 0.5) col = c
      const height = Math.round(columnWidth * Math.min(3, Math.max(0.3, aspect(item) || 1)))
      out.push({ index, x: col * (columnWidth + gap), y: heights[col], height })
      heights[col] += height + gap
    })
    return { placed: out, total: Math.max(0, Math.max(...heights) - gap) }
  }, [items, aspect, columns, columnWidth, gap])

  const from = scrollTop - box.top - overscan
  const to = scrollTop - box.top + box.height + overscan
  const shown = virtual ? placed.filter((p) => p.y + p.height >= from && p.y <= to) : placed

  const canvas = (
    <div ref={canvasRef} className={cn(s.canvas, !virtual && className)} style={{ height: total }}>
      {shown.map((p) => {
        const item = items[p.index]
        return (
          <div
            key={itemKey(item)}
            className={s.brick}
            style={{ transform: `translate(${p.x}px, ${p.y}px)`, width: columnWidth, height: p.height }}
          >
            {renderItem(item, p.index)}
          </div>
        )
      })}
    </div>
  )
  return virtual ? (
    <div ref={scrollerRef} className={cn(s.scroller, className)}>
      {canvas}
    </div>
  ) : (
    canvas
  )
}
