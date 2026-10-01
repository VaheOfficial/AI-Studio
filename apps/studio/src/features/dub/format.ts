/** `1:05` / `1:02:09` */
export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = (s % 60).toString().padStart(2, '0')
  return h ? `${h}:${m.toString().padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

/** `0:32.33` — timestamps to the hundredth, for placing lines. */
export function fmtClock(seconds: number): string {
  const cs = Math.max(0, Math.round(seconds * 100))
  return `${Math.floor(cs / 6000)}:${((cs % 6000) / 100).toFixed(2).padStart(5, '0')}`
}

/** `12.3s` */
export const fmtSeconds = (seconds: number) => `${seconds.toFixed(1)}s`

/** Per-speaker block colors (modality hues + status tokens, theme-aware). */
const SPEAKER_COLORS = [
  'var(--hue-voice)',
  'var(--hue-image)',
  'var(--hue-music)',
  'var(--hue-stt)',
  'var(--hue-text)',
  'var(--accent-2)',
  'var(--success)',
  'var(--warning)',
]

export function speakerColor(speakers: string[], speaker: string): string {
  const i = speakers.indexOf(speaker)
  return SPEAKER_COLORS[(i < 0 ? 0 : i) % SPEAKER_COLORS.length]
}
