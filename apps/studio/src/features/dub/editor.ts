/**
 * Dub editor state: an editable copy of the project's segments with undo/redo (ported from VoiceStudio's
 * `dub-session.ts` segment edits: 50-step history, typing in one row coalesces for 800 ms, split/merge/insert,
 * timeline move/resize). The page saves the segments back to the server whenever they differ from `saved`.
 */
import { create } from 'zustand'
import type { DubProject, DubSegmentInput } from '../../api/contracts/dub'

export type EditSegment = DubSegmentInput

const HISTORY = 50
const COALESCE_MS = 800

interface EditorState {
  projectId: string | null
  segments: EditSegment[]
  /** JSON of the segments last confirmed by the server. */
  saved: string
  undoStack: EditSegment[][]
  redoStack: EditSegment[][]
  lastGroup: string | null
  lastAt: number
  selected: string[]
  activeId: string | null
  /** Editing language: '' = source transcript, otherwise a target language id. */
  lang: string
  load: (project: DubProject, force?: boolean) => void
  markSaved: (segments: EditSegment[]) => void
  edit: (fn: (segs: EditSegment[]) => EditSegment[], group?: string) => void
  undo: () => void
  redo: () => void
  setSelected: (ids: string[]) => void
  toggleSelected: (id: string) => void
  setActive: (id: string | null) => void
  setLang: (lang: string) => void
}

export const toEditSegments = (p: DubProject): EditSegment[] =>
  p.segments.map((s) => ({
    id: s.id,
    start: s.start,
    end: s.end,
    speaker: s.speaker,
    text: s.text,
    voice: s.voice,
    gain: s.gain,
    speed: s.speed,
    direction: s.direction,
    translations: Object.fromEntries(Object.entries(s.translations).map(([lang, line]) => [lang, line.text])),
    words: s.words,
  }))

export const useDubEditor = create<EditorState>((set, get) => ({
  projectId: null,
  segments: [],
  saved: '[]',
  undoStack: [],
  redoStack: [],
  lastGroup: null,
  lastAt: 0,
  selected: [],
  activeId: null,
  lang: '',
  load: (project, force) => {
    const s = get()
    const segments = toEditSegments(project)
    const json = JSON.stringify(segments)
    const switching = s.projectId !== project.id
    // Keep local edits that are still waiting to be saved (unless a job rewrote the project).
    if (!switching && !force && JSON.stringify(s.segments) !== s.saved) return
    // A translation job just produced the first text for a target while the transcript is shown: show it.
    const translated = project.settings.targets.find((t) => project.segments.some((seg) => seg.translations[t]))
    const firstTranslation =
      !switching && !s.lang && translated && !s.segments.some((seg) => seg.translations[translated]) ? translated : null
    set({
      projectId: project.id,
      segments,
      saved: json,
      ...(switching
        ? { undoStack: [], redoStack: [], selected: [], activeId: null, lang: project.settings.targets[0] ?? '' }
        : firstTranslation
          ? { lang: firstTranslation }
          : {}),
    })
  },
  markSaved: (segments) => set({ saved: JSON.stringify(segments) }),
  edit: (fn, group) => {
    const s = get()
    const now = Date.now()
    const coalesce = group != null && group === s.lastGroup && now - s.lastAt < COALESCE_MS
    set({
      segments: fn(s.segments),
      undoStack: coalesce ? s.undoStack : [...s.undoStack.slice(-(HISTORY - 1)), s.segments],
      redoStack: [],
      lastGroup: group ?? null,
      lastAt: now,
    })
  },
  undo: () => {
    const s = get()
    const prev = s.undoStack.at(-1)
    if (!prev) return
    set({ segments: prev, undoStack: s.undoStack.slice(0, -1), redoStack: [...s.redoStack, s.segments], lastGroup: null })
  },
  redo: () => {
    const s = get()
    const next = s.redoStack.at(-1)
    if (!next) return
    set({ segments: next, redoStack: s.redoStack.slice(0, -1), undoStack: [...s.undoStack, s.segments], lastGroup: null })
  },
  setSelected: (ids) => set({ selected: ids }),
  toggleSelected: (id) =>
    set((s) => ({ selected: s.selected.includes(id) ? s.selected.filter((x) => x !== id) : [...s.selected, id] })),
  setActive: (id) => set({ activeId: id }),
  setLang: (lang) => set({ lang }),
}))

/* ------------------------------ segment operations ------------------------------ */

let seq = 0
const newId = (base: string) => `${base}-${Date.now().toString(36)}${(seq++).toString(36)}`

/** Text of a segment in the editing language ('' = source). */
export const textOf = (seg: EditSegment, lang: string) => (lang ? (seg.translations[lang] ?? '') : seg.text)

export function setText(seg: EditSegment, lang: string, text: string): EditSegment {
  return lang ? { ...seg, translations: { ...seg.translations, [lang]: text } } : { ...seg, text }
}

const spelling = (text: string) => text.replace(/\s+/g, '').toLowerCase()

/** Index of the first recognised word after source-text offset `cut`, or -1 when the words don't spell the text. */
function wordAt(seg: EditSegment, cut: number): number {
  const words = seg.words ?? []
  if (!words.length || spelling(words.map((w) => w.text).join('')) !== spelling(seg.text)) return -1
  const before = spelling(seg.text.slice(0, cut)).length
  let seen = 0
  for (let k = 0; k < words.length; k++) {
    if (seen >= before) return k
    seen += spelling(words[k].text).length
  }
  return -1
}

/**
 * Split at a character offset of the editing-language text. The source text is cut at the matching word, and
 * the time at the start of the first word after the cut when the line has recognised words (proportionally
 * otherwise).
 */
export function splitSegment(segs: EditSegment[], id: string, lang: string, at: number): EditSegment[] {
  const i = segs.findIndex((s) => s.id === id)
  if (i < 0) return segs
  const seg = segs[i]
  const text = textOf(seg, lang)
  const cut = bestSplitPoint(text, at)
  if (cut <= 0 || cut >= text.length) return segs
  const cutOf = (value: string) => (value === text ? cut : bestSplitPoint(value, Math.round((value.length * cut) / Math.max(1, text.length))))
  const words = seg.words ?? []
  const k = wordAt(seg, cutOf(seg.text))
  const timed = k > 0 && words[k].start > seg.start && words[k].start < seg.end
  const t = timed ? words[k].start : +(seg.start + ((seg.end - seg.start) * cut) / text.length).toFixed(3)
  // The first half ends with its last word (not at the next word's start), so a pause between them stays a gap.
  const leftEnd = timed && words[k - 1].end > seg.start ? Math.min(t, words[k - 1].end) : t
  let left: EditSegment = { ...seg, end: leftEnd, words: timed ? words.slice(0, k) : undefined }
  let right: EditSegment = { ...seg, id: newId(seg.id), start: t, words: timed ? words.slice(k) : undefined }
  for (const key of ['', ...Object.keys(seg.translations)]) {
    const value = textOf(seg, key)
    const c = key === lang ? cut : cutOf(value)
    left = setText(left, key, value.slice(0, c).trim())
    right = setText(right, key, value.slice(c).trim())
  }
  return [...segs.slice(0, i), left, right, ...segs.slice(i + 1)]
}

/** Prefer a sentence end near the caret, then whitespace (VoiceStudio `bestSplitPoint`). */
function bestSplitPoint(text: string, at: number): number {
  if (at > 0 && at < text.length) {
    const ws = text.lastIndexOf(' ', at)
    return ws > 0 ? ws + 1 : at
  }
  const mid = text.length / 2
  const ends = [...text.matchAll(/[.!?。！？](\s|$)/g)].map((m) => (m.index ?? 0) + 1).filter((x) => x < text.length)
  if (ends.length) return ends.reduce((a, b) => (Math.abs(b - mid) < Math.abs(a - mid) ? b : a))
  const spaces = [...text.matchAll(/\s/g)].map((m) => m.index ?? 0)
  return spaces.length ? spaces.reduce((a, b) => (Math.abs(b - mid) < Math.abs(a - mid) ? b : a)) + 1 : 0
}

/**
 * A line's words clipped to its own span — the line's start is often snapped later than the recognizer's first
 * word — so splitting a merged line at the same place restores the original boundaries.
 */
const wordsWithin = (seg: EditSegment) =>
  (seg.words ?? []).map((w) => {
    const start = Math.min(Math.max(w.start, seg.start), seg.end)
    return { ...w, start, end: Math.max(start, Math.min(w.end, seg.end)) }
  })

export function mergeSegments(segs: EditSegment[], id: string, dir: -1 | 1): EditSegment[] {
  const i = segs.findIndex((s) => s.id === id)
  const j = i + dir
  if (i < 0 || j < 0 || j >= segs.length) return segs
  const [a, b] = dir === 1 ? [segs[i], segs[j]] : [segs[j], segs[i]]
  const join = (x: string, y: string) => [x, y].filter(Boolean).join(' ')
  const langs = new Set([...Object.keys(a.translations), ...Object.keys(b.translations)])
  const merged: EditSegment = {
    ...a,
    end: Math.max(a.end, b.end),
    text: join(a.text, b.text),
    translations: Object.fromEntries([...langs].map((l) => [l, join(a.translations[l] ?? '', b.translations[l] ?? '')])),
    words: [...wordsWithin(a), ...wordsWithin(b)],
  }
  const lo = Math.min(i, j)
  return [...segs.slice(0, lo), merged, ...segs.slice(lo + 2)]
}

/** New empty segment in the gap after `id` (at least 0.3 s, never past the next segment). */
export function insertAfter(segs: EditSegment[], id: string, duration: number): EditSegment[] {
  const i = segs.findIndex((s) => s.id === id)
  if (i < 0) return segs
  const seg = segs[i]
  const limit = segs[i + 1]?.start ?? duration
  const start = seg.end
  const end = Math.min(limit, start + 2)
  if (end - start < 0.3) return segs
  const fresh: EditSegment = { id: newId(seg.id), start, end, speaker: seg.speaker, text: '', translations: {} }
  return [...segs.slice(0, i + 1), fresh, ...segs.slice(i + 1)]
}
