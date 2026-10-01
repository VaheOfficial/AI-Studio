import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { cn } from '../../lib/cn'
import s from './VirtualList.module.css'

export interface VirtualListHandle {
  /** Scroll so the item is visible (centered when it is far away). */
  scrollToIndex: (index: number) => void
}

export interface VirtualListProps<T> {
  items: T[]
  itemKey: (item: T, index: number) => string
  renderItem: (item: T, index: number) => ReactNode
  /** Height guess for rows that have not been measured yet. */
  estimateSize?: number
  /** Extra rows rendered above and below the viewport. */
  overscan?: number
  gap?: number
  className?: string
  /** Rendered when the list is empty. */
  empty?: ReactNode
}

/**
 * Vertically scrolling list that mounts only the rows in view. Rows may have any height and may change size
 * (e.g. a row expanding into an editor) — each mounted row is measured and the offsets follow.
 */
function VirtualListInner<T>(
  { items, itemKey, renderItem, estimateSize = 72, overscan = 8, gap = 0, className, empty }: VirtualListProps<T>,
  ref: React.ForwardedRef<VirtualListHandle>,
) {
  const scroller = useRef<HTMLDivElement>(null)
  const sizes = useRef(new Map<string, number>())
  const [version, setVersion] = useState(0)
  const [viewport, setViewport] = useState({ top: 0, height: 0 })
  const keys = useMemo(() => items.map(itemKey), [items, itemKey])

  const offsets = useMemo(() => {
    void version
    const out = Array.from({ length: keys.length + 1 }, () => 0)
    for (let i = 0; i < keys.length; i++) out[i + 1] = out[i] + (sizes.current.get(keys[i]) ?? estimateSize) + gap
    return out
  }, [keys, estimateSize, gap, version])

  // Read by the ResizeObserver callback, which is created once.
  const index = useMemo(() => new Map(keys.map((k, i) => [k, i])), [keys])
  const layout = useRef({ offsets, index, estimateSize })
  useLayoutEffect(() => {
    layout.current = { offsets, index, estimateSize }
  }, [offsets, index, estimateSize])
  // Height change of rows above the viewport, applied to scrollTop once the new offsets are rendered
  const pendingShift = useRef(0)
  useLayoutEffect(() => {
    const el = scroller.current
    if (el && pendingShift.current) el.scrollTop += pendingShift.current
    pendingShift.current = 0
  }, [version])

  useLayoutEffect(() => {
    const el = scroller.current
    if (!el) return
    const update = () => setViewport({ top: el.scrollTop, height: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    let frame = 0
    const onScroll = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(update)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      ro.disconnect()
      el.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(frame)
    }
  }, [])

  // Binary search for the first row whose bottom is below the viewport top.
  const first = useMemo(() => {
    let lo = 0
    let hi = keys.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (offsets[mid + 1] <= viewport.top) lo = mid + 1
      else hi = mid
    }
    return Math.max(0, lo - overscan)
  }, [offsets, keys.length, viewport.top, overscan])
  let last = first
  while (last < keys.length && offsets[last] < viewport.top + viewport.height) last++
  last = Math.min(keys.length, last + overscan)

  const observer = useRef<ResizeObserver | null>(null)
  const measured = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    if (!observer.current) {
      observer.current = new ResizeObserver((entries) => {
        const el = scroller.current
        const { offsets: at, index, estimateSize: guess } = layout.current
        let changed = false
        for (const e of entries) {
          const target = e.target as HTMLElement
          const key = target.dataset.key
          // A row that just unmounted reports 0 — keep its last real height instead of collapsing the list
          if (!key || !target.isConnected) continue
          const h = target.offsetHeight
          const prev = sizes.current.get(key) ?? guess
          if (h === 0 || h === prev) continue
          sizes.current.set(key, h)
          changed = true
          // Scroll anchoring: rows above the viewport growing or shrinking must not move what the user sees
          const i = index.get(key)
          if (el && i !== undefined && at[i] + prev <= el.scrollTop) pendingShift.current += h - prev
        }
        if (changed) setVersion((v) => v + 1)
      })
    }
    const obs = observer.current
    obs.observe(node)
    return () => obs.unobserve(node)
  }, [])
  useEffect(() => () => observer.current?.disconnect(), [])

  useImperativeHandle(
    ref,
    () => ({
      scrollToIndex(index: number) {
        const el = scroller.current
        if (!el || index < 0 || index >= keys.length) return
        const top = offsets[index]
        const bottom = offsets[index + 1]
        if (top >= el.scrollTop && bottom <= el.scrollTop + el.clientHeight) return
        el.scrollTo({ top: Math.max(0, top - el.clientHeight / 3), behavior: 'smooth' })
      },
    }),
    [keys.length, offsets],
  )

  return (
    <div ref={scroller} className={cn(s.scroller, className)}>
      {items.length === 0 ? (
        empty
      ) : (
        <div className={s.canvas} style={{ height: offsets[keys.length] }}>
          {items.slice(first, last).map((item, i) => {
            const index = first + i
            return (
              <div key={keys[index]} data-key={keys[index]} ref={measured} className={s.row} style={{ top: offsets[index] }}>
                {renderItem(item, index)}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export const VirtualList = forwardRef(VirtualListInner) as <T>(
  props: VirtualListProps<T> & { ref?: React.Ref<VirtualListHandle> },
) => ReturnType<typeof VirtualListInner>
