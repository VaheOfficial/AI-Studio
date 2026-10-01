/**
 * Pure helpers for the segment timeline (ported from VoiceStudio `shared/utils/timeline.js`).
 * All times are seconds, all pixels CSS px.
 */

/** Minimum length a segment can be resized to. */
export const MIN_SEG_DUR = 0.3
/** Alt-drag may push past a neighbour by at most this much. */
export const MAX_OVERLAP = 0.2
/** Snap radius in pixels. */
export const SNAP_PX = 8
const GRID_SNAP_MAX_PX_PER_SEC = 40

export interface Span {
  start: number
  end: number
}

/** Nearest candidate within `thresholdS` wins (ties → earliest). `candidate === null` means no snap. */
export function snapTime(t: number, candidates: number[], thresholdS: number): { time: number; candidate: number | null } {
  let best: number | null = null
  let bestDist = Infinity
  for (const c of candidates) {
    if (!Number.isFinite(c)) continue
    const d = Math.abs(c - t)
    if (d <= thresholdS && (d < bestDist || (d === bestDist && best !== null && c < best))) {
      best = c
      bestDist = d
    }
  }
  return best === null ? { time: t, candidate: null } : { time: best, candidate: best }
}

/** Snap targets: onsets, neighbouring edges, the playhead and (zoomed out) whole seconds. */
export function snapCandidates(o: {
  onsets: number[]
  prevEnd?: number
  nextStart?: number
  playhead?: number
  pxPerSec: number
  t: number
}): number[] {
  const out = [...o.onsets]
  if (o.prevEnd != null) out.push(o.prevEnd)
  if (o.nextStart != null) out.push(o.nextStart)
  if (o.playhead != null) out.push(o.playhead)
  if (o.pxPerSec > 0 && o.pxPerSec < GRID_SNAP_MAX_PX_PER_SEC) out.push(Math.floor(o.t), Math.ceil(o.t))
  return out
}

/**
 * Enforce overlap/ordering rules on a proposed edit: edges clamp at the neighbour (Alt: up to MAX_OVERLAP
 * past it), resizes keep MIN_SEG_DUR, moves keep the duration, nothing reorders past a neighbour.
 */
export function clampSegmentEdit(
  segments: Span[],
  index: number,
  mode: 'start' | 'end' | 'move',
  proposed: Span,
  opts: { allowOverlap?: boolean; duration?: number } = {},
): Span {
  const { allowOverlap = false, duration = Infinity } = opts
  const seg = segments[index]
  const prev = index > 0 ? segments[index - 1] : null
  const next = index < segments.length - 1 ? segments[index + 1] : null
  const give = allowOverlap ? MAX_OVERLAP : 0
  const minStart = Math.max(0, prev ? prev.end - give : 0)
  const maxEnd = Math.min(duration, next ? next.start + give : duration)
  let start: number
  let end: number
  if (mode === 'move') {
    const dur = seg.end - seg.start
    start = Math.max(minStart, Math.min(proposed.start, maxEnd - dur))
    end = start + dur
  } else if (mode === 'start') {
    start = Math.min(Math.max(proposed.start, minStart), seg.end - MIN_SEG_DUR)
    end = seg.end
  } else {
    end = Math.max(Math.min(proposed.end, maxEnd), seg.start + MIN_SEG_DUR)
    start = seg.start
  }
  return { start: +start.toFixed(3), end: +end.toFixed(3) }
}

/** Ids of every segment that overlaps a neighbour (touching edges don't count). */
export function detectOverlaps(segments: (Span & { id: string })[], epsilon = 1e-6): Set<string> {
  const flagged = new Set<string>()
  const sorted = [...segments].sort((x, y) => x.start - y.start || x.end - y.end)
  let active: (Span & { id: string })[] = []
  for (const cur of sorted) {
    active = active.filter((p) => p.end > cur.start + epsilon)
    for (const p of active) {
      flagged.add(p.id)
      flagged.add(cur.id)
    }
    active.push(cur)
  }
  return flagged
}

export function nearestOnset(t: number, onsets: number[]): number | null {
  let best: number | null = null
  let bestDist = Infinity
  for (const o of onsets) {
    const d = Math.abs(o - t)
    if (d < bestDist) {
      best = o
      bestDist = d
    }
  }
  return best
}

export function formatTime(seconds: number, digits = 1): string {
  const m = Math.floor(seconds / 60)
  return `${m}:${(seconds % 60).toFixed(digits).padStart(digits + 3, '0')}`
}
