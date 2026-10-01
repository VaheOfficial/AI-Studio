import type { BadgeTone } from '@studio/ui'
import type { OpenRouterAccount } from '../../api/contracts/openrouter'
import { formatBalance, formatUsd } from '../../lib/money'

export const CREDITS_URL = 'https://openrouter.ai/settings/credits'
export const KEYS_URL = 'https://openrouter.ai/settings/keys'

/** Spendable USD: the account balance (management key) or what's left of the key's cap. */
export const remaining = (a: OpenRouterAccount) => a.balance ?? a.limit_remaining

export function accountStatus(a: OpenRouterAccount | undefined): { tone: BadgeTone; label: string } {
  if (!a) return { tone: 'neutral', label: 'Checking…' }
  if (!a.configured && !a.management_key) return { tone: 'neutral', label: 'Not connected' }
  if (!a.ok) return { tone: 'danger', label: 'Key problem' }
  const left = remaining(a)
  if (left != null) return { tone: left < 0.5 ? 'warning' : 'success', label: `Connected · ${formatBalance(left)} left` }
  return { tone: 'success', label: `Connected · ${formatUsd(a.usage_daily ?? 0)} today` }
}
