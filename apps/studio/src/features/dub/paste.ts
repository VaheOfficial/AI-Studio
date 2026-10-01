/**
 * Map externally produced translations onto the existing segments without touching timing or the source text
 * (ported from VoiceStudio `shared/utils/pasteTranslations.js`). Three auto-detected shapes:
 * timestamped (SRT/VTT, matched one-to-one by largest time overlap), numbered (`1.` / `2)` / `[3]`, by number
 * when it is a clean 1-based index, else by position) and plain (one line per segment, by position).
 */
import type { DubSubtitleCue } from '../../api/contracts/dub'

export type PasteMode = 'timestamped' | 'numbered' | 'plain'

const TIMING_RE =
  /^[^\S\n]*(?:\d{1,2}:)?[0-5]?\d:[0-5]?\d[,.]\d{1,3}[^\S\n]*-->[^\S\n]*(?:\d{1,2}:)?[0-5]?\d:[0-5]?\d[,.]\d{1,3}/m
const NUMBERED_RE = /^\s*(?:\[\s*(\d{1,5})\s*\]|\(\s*(\d{1,5})\s*\)|(\d{1,5}))\s*[.):\-—]?\s+(.*)$/

const nonBlank = (text: string) =>
  text
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

export function detectPasteMode(text: string): PasteMode {
  if (TIMING_RE.test(text)) return 'timestamped'
  const lines = nonBlank(text)
  if (lines.length >= 2) {
    const numbered = lines.filter((l) => NUMBERED_RE.test(l)).length
    if (numbered >= 2 && numbered / lines.length >= 0.6) return 'numbered'
  }
  return 'plain'
}

function parseNumbered(text: string): { num: number; text: string }[] {
  const entries: { num: number; text: string }[] = []
  for (const line of nonBlank(text)) {
    const m = NUMBERED_RE.exec(line)
    if (m) entries.push({ num: parseInt(m[1] ?? m[2] ?? m[3], 10), text: (m[4] || '').trim() })
    else if (entries.length) entries[entries.length - 1].text = `${entries[entries.length - 1].text} ${line}`.trim()
  }
  return entries.filter((e) => e.text)
}

interface Timed {
  start: number
  end: number
}

/** Greedy one-to-one matching by best overlap: strongest pairs first, weaker rows stay honestly unmatched. */
function matchByOverlap(cues: Timed[], segments: Timed[]): Map<number, number> {
  const bySegStart = segments.map((s, i) => ({ i, ...s })).sort((a, b) => a.start - b.start || a.i - b.i)
  const byCueStart = cues.map((c, i) => ({ i, ...c })).sort((a, b) => a.start - b.start || a.i - b.i)
  const pairs: { si: number; ci: number; ov: number }[] = []
  let lo = 0
  for (const s of bySegStart) {
    while (lo < byCueStart.length && byCueStart[lo].end <= s.start) lo++
    for (let k = lo; k < byCueStart.length && byCueStart[k].start < s.end; k++) {
      const ov = Math.min(s.end, byCueStart[k].end) - Math.max(s.start, byCueStart[k].start)
      if (ov > 0) pairs.push({ si: s.i, ci: byCueStart[k].i, ov })
    }
  }
  pairs.sort((a, b) => b.ov - a.ov || a.si - b.si || a.ci - b.ci)
  const bySeg = new Map<number, number>()
  const used = new Set<number>()
  for (const p of pairs) {
    if (bySeg.has(p.si) || used.has(p.ci)) continue
    bySeg.set(p.si, p.ci)
    used.add(p.ci)
  }
  return bySeg
}

export interface PasteRow {
  id: string
  index: number
  before: string
  after: string | null
}

export interface PastePlan {
  mode: PasteMode
  rows: PasteRow[]
  matched: number
  unused: number
}

export function buildPastePlan(
  text: string,
  segments: (Timed & { id: string; text: string })[],
  cues: DubSubtitleCue[] | null,
): PastePlan {
  const mode = detectPasteMode(text)
  const assigned = new Map<number, string>()
  let source = 0
  if (mode === 'timestamped') {
    const list = cues ?? []
    source = list.length
    for (const [si, ci] of matchByOverlap(list, segments)) if (list[ci].text.trim()) assigned.set(si, list[ci].text.trim())
  } else if (mode === 'numbered') {
    const entries = parseNumbered(text)
    source = entries.length
    const nums = entries.map((e) => e.num)
    const usable = nums.every((n, i) => n >= 1 && n <= segments.length && (i === 0 || n > nums[i - 1]))
    entries.forEach((e, i) => {
      const si = usable ? e.num - 1 : i
      if (si < segments.length && !assigned.has(si)) assigned.set(si, e.text)
    })
  } else {
    const lines = nonBlank(text)
    source = lines.length
    lines.forEach((line, i) => i < segments.length && assigned.set(i, line))
  }
  return {
    mode,
    rows: segments.map((s, i) => ({ id: s.id, index: i, before: s.text, after: assigned.get(i) ?? null })),
    matched: assigned.size,
    unused: Math.max(0, source - assigned.size),
  }
}
