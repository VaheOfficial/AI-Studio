import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { AlertTriangle, Headphones, Maximize2, Play, ZoomIn, ZoomOut } from 'lucide-react'
import { cn } from '../../lib/cn'
import { IconButton } from '../IconButton/IconButton'
import { Spinner } from '../Spinner/Spinner'
import {
  clampSegmentEdit,
  detectOverlaps,
  formatTime,
  nearestOnset,
  snapCandidates,
  snapTime,
  SNAP_PX,
  type Span,
} from './timelineMath'
import s from './Timeline.module.css'

export interface TimelineItem {
  id: string
  start: number
  end: number
  /** Short label drawn inside the block (defaults to its 1-based index). */
  label?: string
  /** Block color, e.g. a per-speaker hue ("var(--hue-voice)"). */
  color?: string
}

export interface TimelineProps {
  /** Blocks in chronological order. */
  items: TimelineItem[]
  duration: number
  /** Normalised 0..1 waveform peaks across the whole duration. */
  peaks?: number[]
  /** Speech onsets (seconds) — drawn as ticks and used as snap targets. */
  onsets?: number[]
  /** Current playback position (seconds). */
  playhead?: number
  selectedId?: string | null
  disabled?: boolean
  previewingId?: string | null
  onSelect?: (id: string) => void
  onSeek?: (time: number) => void
  /** Committed once per drag/resize/nudge. */
  onChange?: (id: string, span: Span) => void
  onDelete?: (id: string) => void
  onPlayRange?: (item: TimelineItem) => void
  onPreview?: (item: TimelineItem) => void
  className?: string
}

const MAX_ZOOM = 64

interface Gesture {
  index: number
  id: string
  mode: 'start' | 'end' | 'move'
  x: number
  start: number
  end: number
}

/**
 * Waveform lane with draggable, resizable segment blocks (ported from VoiceStudio's dub timeline).
 * Drag to move, drag an edge to resize; edges snap to speech onsets, neighbours, the playhead and (zoomed
 * out) whole seconds — hold Alt to disable snapping and allow a small overlap. Keyboard: ←/→ focus, Enter
 * toggles edit mode (←/→ nudge start, Shift = end, Alt = move, Ctrl ×10), S / Shift+S snap to the nearest
 * onset, Delete removes. Double-click plays the block's range.
 */
export function Timeline({
  items,
  duration: mediaDuration,
  peaks = [],
  onsets = [],
  playhead,
  selectedId,
  disabled,
  previewingId,
  onSelect,
  onSeek,
  onChange,
  onDelete,
  onPlayRange,
  onPreview,
  className,
}: TimelineProps) {
  const viewport = useRef<HTMLDivElement>(null)
  const lane = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const blocks = useRef(new Map<string, HTMLDivElement>())
  const gesture = useRef<Gesture | null>(null)
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(1000)
  const [live, setLive] = useState<(Span & { id: string }) | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [editMode, setEditMode] = useState(false)
  const duration = Math.max(0.3, mediaDuration || 0, ...items.map((i) => i.end))
  const latest = useRef({ items, selectedId, playhead })
  latest.current = { items, selectedId, playhead }

  const effective = useMemo(
    () => (live ? items.map((i) => (i.id === live.id ? { ...i, start: live.start, end: live.end } : i)) : items),
    [items, live],
  )
  const overlaps = useMemo(() => detectOverlaps(effective), [effective])

  // The canvas covers only the visible part of the lane (redrawn on scroll), so deep zoom stays sharp.
  useEffect(() => {
    const c = canvas.current
    const host = lane.current
    const vp = viewport.current
    if (!c || !host || !vp) return
    let frame = 0
    const draw = () => {
      frame = 0
      const laneW = host.clientWidth
      const h = host.clientHeight
      setWidth(laneW)
      if (!laneW) return
      const left = Math.min(vp.scrollLeft, laneW)
      const viewW = Math.max(1, Math.min(vp.clientWidth, laneW - left))
      const dpr = window.devicePixelRatio || 1
      c.width = Math.max(1, Math.round(viewW * dpr))
      c.height = Math.max(1, Math.round(h * dpr))
      c.style.left = `${left}px`
      c.style.width = `${viewW}px`
      c.style.height = `${h}px`
      const ctx = c.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, c.width, c.height)
      const color = getComputedStyle(c).color
      const toX = (t: number) => ((t / duration) * laneW - left) * dpr
      if (peaks.length) {
        const mid = c.height / 2
        const amp = (v: number) => Math.min(1, Math.max(0.02, v)) * c.height * 0.42
        const binW = (laneW / peaks.length) * dpr
        const binDur = duration / peaks.length
        ctx.fillStyle = color
        ctx.globalAlpha = 0.3
        if (binW >= 3) {
          const first = Math.max(0, Math.floor(left / (laneW / peaks.length)))
          const last = Math.min(peaks.length, Math.ceil((left + viewW) / (laneW / peaks.length)))
          for (let i = first; i < last; i++) {
            const a = amp(peaks[i])
            ctx.fillRect(toX(i * binDur), mid - a, binW * 0.65, a * 2)
          }
        } else {
          // Several bins per device pixel: draw each column's loudest bin.
          const perPx = 1 / binW
          const offset = (left * dpr) / binW
          for (let x = 0; x < c.width; x++) {
            const from = Math.floor(offset + x * perPx)
            const to = Math.min(peaks.length, Math.max(from + 1, Math.floor(offset + (x + 1) * perPx)))
            let v = 0
            for (let i = from; i < to; i++) v = Math.max(v, peaks[i])
            const a = amp(v)
            ctx.fillRect(x, mid - a, 1, a * 2)
          }
        }
        ctx.globalAlpha = 1
      }
      ctx.strokeStyle = color
      ctx.lineWidth = dpr
      ctx.beginPath()
      for (const o of onsets) {
        const x = Math.round(toX(o)) + 0.5
        if (x < 0 || x > c.width) continue
        ctx.moveTo(x, c.height * 0.62)
        ctx.lineTo(x, c.height)
      }
      ctx.stroke()
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(draw)
    }
    draw()
    const ro = new ResizeObserver(draw)
    ro.observe(host)
    ro.observe(vp)
    vp.addEventListener('scroll', schedule, { passive: true })
    return () => {
      ro.disconnect()
      vp.removeEventListener('scroll', schedule)
      cancelAnimationFrame(frame)
    }
  }, [duration, onsets, peaks, zoom])

  // Keep the selected block (else the playhead) in view when it changes or the zoom does.
  useEffect(() => {
    const vp = viewport.current
    const host = lane.current
    if (!vp || !host) return
    const { items: all, selectedId: sel, playhead: now } = latest.current
    const item = all.find((i) => i.id === sel)
    const [a, b] = item ? [item.start, item.end] : [now ?? 0, now ?? 0]
    const px = (t: number) => (t / duration) * host.clientWidth
    if (px(a) < vp.scrollLeft || px(b) > vp.scrollLeft + vp.clientWidth) {
      vp.scrollLeft = Math.max(0, (px(a) + px(b)) / 2 - vp.clientWidth / 2)
    }
  }, [selectedId, zoom, duration])

  const pxWidth = (i: TimelineItem) => ((i.end - i.start) / duration) * width

  const begin = (e: PointerEvent<HTMLDivElement>, index: number) => {
    if (disabled || !onChange || e.button !== 0) return
    const item = effective[index]
    if (pxWidth(item) < 16) return
    const edge = (e.target as HTMLElement).dataset.edge
    gesture.current = { index, id: item.id, mode: edge === 'start' ? 'start' : edge === 'end' ? 'end' : 'move',
      x: e.clientX, start: item.start, end: item.end }
    e.currentTarget.setPointerCapture(e.pointerId)
    onSelect?.(item.id)
  }

  const move = (e: PointerEvent<HTMLDivElement>) => {
    const g = gesture.current
    const w = lane.current?.clientWidth || 0
    if (!g || !w) return
    const delta = ((e.clientX - g.x) / w) * duration
    const proposed =
      g.mode === 'move'
        ? { start: g.start + delta, end: g.end + delta }
        : g.mode === 'start'
          ? { start: g.start + delta, end: g.end }
          : { start: g.start, end: g.end + delta }
    let snapped = proposed
    if (!e.altKey) {
      const edge = g.mode === 'end' ? proposed.end : proposed.start
      const res = snapTime(
        edge,
        snapCandidates({
          onsets,
          prevEnd: items[g.index - 1]?.end,
          nextStart: items[g.index + 1]?.start,
          playhead,
          pxPerSec: w / duration,
          t: edge,
        }),
        (SNAP_PX / w) * duration,
      )
      if (res.candidate != null) {
        snapped =
          g.mode === 'move'
            ? { start: res.time, end: res.time + (g.end - g.start) }
            : g.mode === 'start'
              ? { ...proposed, start: res.time }
              : { ...proposed, end: res.time }
      }
    }
    setLive({ id: g.id, ...clampSegmentEdit(items, g.index, g.mode, snapped, { allowOverlap: e.altKey, duration }) })
  }

  const finish = (e: PointerEvent<HTMLDivElement>, commit: boolean) => {
    const g = gesture.current
    gesture.current = null
    if (commit && g && live?.id === g.id && (live.start !== g.start || live.end !== g.end)) {
      onChange?.(g.id, { start: live.start, end: live.end })
    }
    setLive(null)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
  }

  const focus = (id: string) => {
    setFocusId(id)
    onSelect?.(id)
    requestAnimationFrame(() => blocks.current.get(id)?.focus({ preventScroll: false }))
  }

  const onKey = (e: KeyboardEvent<HTMLDivElement>, index: number) => {
    const item = items[index]
    if (disabled) return
    const stop = () => {
      e.preventDefault()
      e.stopPropagation()
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && onDelete) {
      stop()
      const neighbour = items[index + 1] ?? items[index - 1]
      onDelete(item.id)
      if (neighbour) focus(neighbour.id)
      return
    }
    if (e.key === 'Enter') {
      stop()
      setEditMode((v) => !v)
      return
    }
    if (e.key === 'Escape' && editMode) {
      stop()
      setEditMode(false)
      return
    }
    if (e.key.toLowerCase() === 's' && onChange) {
      stop()
      const toEnd = e.shiftKey
      const onset = nearestOnset(toEnd ? item.end : item.start, onsets)
      if (onset == null) return
      onChange(item.id, clampSegmentEdit(items, index, toEnd ? 'end' : 'start',
        toEnd ? { start: item.start, end: onset } : { start: onset, end: item.end }, { duration }))
      return
    }
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    stop()
    const dir = e.key === 'ArrowLeft' ? -1 : 1
    if (!editMode || !onChange) {
      const next = items[index + dir]
      if (next) focus(next.id)
      return
    }
    const amount = (e.ctrlKey || e.metaKey ? 0.1 : 0.01) * dir
    const mode = e.altKey ? 'move' : e.shiftKey ? 'end' : 'start'
    const proposed =
      mode === 'move'
        ? { start: item.start + amount, end: item.end + amount }
        : mode === 'end'
          ? { start: item.start, end: item.end + amount }
          : { start: item.start + amount, end: item.end }
    onChange(item.id, clampSegmentEdit(items, index, mode, proposed, { duration }))
  }

  return (
    <section className={cn(s.timeline, className)} aria-label="Segment timeline">
      <div className={s.zoom}>
        {playhead != null && (
          <span className={s.now} title="Playhead">
            {formatTime(playhead, 2)}
          </span>
        )}
        <span className={s.zoomLabel}>×{zoom}</span>
        <IconButton size="sm" label="Zoom out" icon={<ZoomOut />} disabled={zoom <= 1} onClick={() => setZoom((z) => Math.max(1, z / 2))} />
        <IconButton size="sm" label="Zoom in" icon={<ZoomIn />} disabled={zoom >= MAX_ZOOM} onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z * 2))} />
        <IconButton size="sm" label="Fit" icon={<Maximize2 />} onClick={() => setZoom(1)} />
      </div>
      <div ref={viewport} className={s.viewport}>
        <div
          ref={lane}
          className={s.lane}
          style={{ width: `${zoom * 100}%` }}
          role="listbox"
          aria-orientation="horizontal"
          onClick={(e) => {
            if ((e.target as HTMLElement).closest('[data-block]') || !onSeek) return
            const r = e.currentTarget.getBoundingClientRect()
            if (r.width > 0) onSeek(((e.clientX - r.left) / r.width) * duration)
          }}
        >
          <canvas ref={canvas} aria-hidden className={s.wave} />
          {playhead != null && playhead > 0 && (
            <span aria-hidden className={s.playhead} style={{ left: `${(Math.min(playhead, duration) / duration) * 100}%` }} />
          )}
          {effective.map((item, index) => {
            const px = pxWidth(item)
            const selected = selectedId === item.id
            return (
              <div
                key={item.id}
                ref={(el) => {
                  if (el) blocks.current.set(item.id, el)
                  else blocks.current.delete(item.id)
                }}
                data-block
                role="option"
                aria-selected={selected}
                aria-label={`Segment ${index + 1}, ${formatTime(item.start)} – ${formatTime(item.end)}`}
                tabIndex={focusId === item.id || (!focusId && index === 0) ? 0 : -1}
                className={cn(
                  s.block,
                  selected && s.selected,
                  focusId === item.id && editMode && s.editing,
                  overlaps.has(item.id) && s.overlap,
                  disabled && s.disabled,
                )}
                style={{
                  left: `${(item.start / duration) * 100}%`,
                  width: `${((item.end - item.start) / duration) * 100}%`,
                  ['--c' as string]: item.color ?? 'var(--accent)',
                }}
                onClick={() => focus(item.id)}
                onDoubleClick={() => onPlayRange?.(item)}
                onKeyDown={(e) => onKey(e, index)}
                onFocus={() => setFocusId(item.id)}
                onBlur={(e) => {
                  if (!e.currentTarget.parentElement?.contains(e.relatedTarget)) setEditMode(false)
                }}
                onPointerDown={(e) => begin(e, index)}
                onPointerMove={move}
                onPointerUp={(e) => finish(e, true)}
                onPointerCancel={(e) => finish(e, false)}
              >
                {px >= 24 && onChange && <span data-edge="start" aria-hidden className={cn(s.edge, s.edgeStart)} />}
                {px >= 18 && <span className={s.label}>{item.label ?? index + 1}</span>}
                {selected && px > 60 && (
                  <span className={s.actions}>
                    {onPlayRange && (
                      <button
                        type="button"
                        aria-label="Play segment"
                        className={s.action}
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation()
                          onPlayRange(item)
                        }}
                      >
                        <Play size={11} fill="currentColor" />
                      </button>
                    )}
                    {onPreview && px > 90 && (
                      <button
                        type="button"
                        aria-label="Preview the dubbed line"
                        className={s.action}
                        disabled={!!previewingId}
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation()
                          onPreview(item)
                        }}
                      >
                        {previewingId === item.id ? <Spinner size={11} /> : <Headphones size={11} />}
                      </button>
                    )}
                  </span>
                )}
                {px >= 24 && onChange && <span data-edge="end" aria-hidden className={cn(s.edge, s.edgeEnd)} />}
              </div>
            )
          })}
        </div>
      </div>
      <div className={s.footer}>
        <span>0:00.0</span>
        {overlaps.size > 0 && (
          <button
            type="button"
            className={s.overlapLink}
            onClick={() => {
              const id = [...overlaps][0]
              setZoom(16)
              focus(id)
            }}
          >
            <AlertTriangle size={12} /> Overlap
          </button>
        )}
        <span>{formatTime(duration)}</span>
      </div>
    </section>
  )
}
