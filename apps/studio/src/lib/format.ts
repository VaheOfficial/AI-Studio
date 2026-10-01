export function formatBytes(bytes: number | undefined, digits = 1): string {
  if (bytes == null || !isFinite(bytes)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = bytes
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : digits)} ${units[i]}`
}

export const formatGB = (gb: number) => (gb >= 1000 ? `${(gb / 1000).toFixed(1)} TB` : gb < 1 ? `${Math.round(gb * 1024)} MB` : `${gb.toFixed(gb < 10 ? 1 : 0)} GB`)

export const formatSpeed = (bps: number | undefined) => (bps ? `${formatBytes(bps)}/s` : '')

export function formatEta(done?: number, total?: number, bps?: number): string {
  if (!done || !total || !bps) return ''
  const s = (total - done) / bps
  if (s < 60) return `${Math.ceil(s)}s left`
  if (s < 3600) return `${Math.ceil(s / 60)}m left`
  return `${(s / 3600).toFixed(1)}h left`
}

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

export function timeAgo(iso: string): string {
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  const abs = Math.abs(diff)
  if (abs < 45) return 'just now'
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 604800) return rtf.format(Math.round(diff / 86400), 'day')
  return new Date(iso).toLocaleDateString()
}

/**
 * Token counts the way model cards write them: binary units, so 32 768 → "32K", 262 144 → "256K", 1 048 576 → "1M".
 */
export function formatTokens(n: number): string {
  const trim = (x: number) => String(+x.toFixed(x < 10 ? 1 : 0))
  if (n >= 1024 * 1024) return `${trim(n / (1024 * 1024))}M`
  if (n >= 1024) return `${trim(n / 1024)}K`
  return String(n)
}

/** Generation speed, "84 tok/s"; undefined unless both numbers are known. */
export function tokensPerSecond(tokens: number | undefined, seconds: number | undefined): string | undefined {
  if (!tokens || !seconds || seconds <= 0) return undefined
  const rate = tokens / seconds
  return `${rate >= 10 ? Math.round(rate) : rate.toFixed(1)} tok/s`
}

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

/** 1234567 → "1.2M" (downloads, likes, pulls). */
export const formatCount = (n: number | undefined) => (n == null ? '—' : compact.format(n))
