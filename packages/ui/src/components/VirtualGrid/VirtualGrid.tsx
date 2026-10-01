import { useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '../../lib/cn'
import s from './VirtualGrid.module.css'

export interface VirtualGridProps<T> {
  items: T[]
  itemKey: (item: T) => string
  renderItem: (item: T, index: number) => ReactNode
  /** Columns are as many as fit at this minimum width. */
  minItemWidth?: number
  gap?: number
  /** Item height as a multiple of its width (1 = square tiles). */
  itemAspect?: number
  /** Extra rows rendered above and below the viewport. */
  overscan?: number
  className?: string
}

/** Scrollable grid that only mounts the rows in view — for thousands of equally sized tiles. */
export function VirtualGrid<T>({
  items,
  itemKey,
  renderItem,
  minItemWidth = 220,
  gap = 10,
  itemAspect = 1,
  overscan = 3,
  className,
}: VirtualGridProps<T>) {
  const ref = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  // width: the grid's content width (scroller padding excluded); top: where the grid starts inside the scroller
  const [box, setBox] = useState({ width: 0, height: 0, top: 0 })
  const [scrollTop, setScrollTop] = useState(0)

  useEffect(() => {
    const el = ref.current
    const canvas = canvasRef.current
    if (!el || !canvas) return
    const ro = new ResizeObserver(() => setBox({ width: canvas.clientWidth, height: el.clientHeight, top: canvas.offsetTop }))
    ro.observe(el)
    ro.observe(canvas)
    let frame = 0
    const onScroll = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setScrollTop(el.scrollTop))
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      ro.disconnect()
      cancelAnimationFrame(frame)
      el.removeEventListener('scroll', onScroll)
    }
  }, [])

  const columns = Math.max(1, Math.floor((box.width + gap) / (minItemWidth + gap)))
  const itemWidth = box.width > 0 ? (box.width - gap * (columns - 1)) / columns : minItemWidth
  const rowHeight = itemWidth * itemAspect
  const stride = rowHeight + gap
  const rows = Math.ceil(items.length / columns)
  const top = Math.max(0, scrollTop - box.top)
  const first = Math.max(0, Math.floor(top / stride) - overscan)
  const last = Math.min(rows - 1, Math.ceil((top + box.height) / stride) + overscan)

  const visible: ReactNode[] = []
  for (let row = first; row <= last; row++) {
    for (let col = 0; col < columns; col++) {
      const index = row * columns + col
      if (index >= items.length) break
      const item = items[index]
      visible.push(
        <div
          key={itemKey(item)}
          className={s.cell}
          style={{ top: row * stride, left: col * (itemWidth + gap), width: itemWidth, height: rowHeight }}
        >
          {renderItem(item, index)}
        </div>,
      )
    }
  }

  return (
    <div ref={ref} className={cn(s.scroller, className)}>
      <div ref={canvasRef} className={s.canvas} style={{ height: Math.max(0, rows * stride - gap) }}>
        {visible}
      </div>
    </div>
  )
}
