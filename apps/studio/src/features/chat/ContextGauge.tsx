import { Tooltip, cn } from '@studio/ui'
import type { ContextUsage } from '../../api/types'
import { formatTokens as k } from '../../lib/format'
import s from './ContextGauge.module.css'

const R = 7
const C = 2 * Math.PI * R

/** How full the model's context window was on the last request; the tooltip says what was trimmed to fit. */
export function ContextGauge({ usage, note }: { usage?: ContextUsage; note?: string }) {
  if (!usage) return null
  const share = usage.limit ? Math.min(1, usage.used / usage.limit) : undefined
  const level = share == null ? undefined : share > 0.8 ? 'high' : share > 0.55 ? 'mid' : 'low'
  const label = usage.limit
    ? `Context: ${k(usage.used)} of ${k(usage.limit)} tokens (${Math.round((share ?? 0) * 100)}%)`
    : `Context: ${k(usage.used)} tokens`
  return (
    <Tooltip
      content={
        <span className={s.tip}>
          {label}
          <span className={s.tipNote}>
            {note ?? 'Older tool output is trimmed, then summarized, when the window fills up.'}
          </span>
        </span>
      }
    >
      <span className={cn(s.gauge, level && s[level])} role="img" aria-label={label}>
        <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden>
          <circle className={s.track} cx="9" cy="9" r={R} />
          {share != null && (
            <circle className={s.fill} cx="9" cy="9" r={R} strokeDasharray={C} strokeDashoffset={C * (1 - share)} />
          )}
        </svg>
        <span className={s.text}>{share != null ? `${Math.round(share * 100)}%` : k(usage.used)}</span>
      </span>
    </Tooltip>
  )
}
