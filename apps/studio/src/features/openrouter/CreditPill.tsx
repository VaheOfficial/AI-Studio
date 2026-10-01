import { Link } from 'react-router'
import { CreditCard, RefreshCw, Settings, Wallet } from 'lucide-react'
import { Button, IconButton, Popover, StatusDot, cn } from '@studio/ui'
import type { ChargeKind, OpenRouterAccount } from '../../api/contracts/openrouter'
import { useOpenRouterAccount, useRefreshOpenRouterAccount } from '../../api/openrouter'
import { timeAgo } from '../../lib/format'
import { formatBalance, formatUsd } from '../../lib/money'
import { CREDITS_URL, remaining } from './account'
import s from './CreditPill.module.css'

const KIND_LABEL: Record<ChargeKind, string> = {
  chat: 'Chat',
  title: 'Chat title',
  image: 'Image',
  speech: 'Speech',
  transcription: 'Transcription',
}

/** Topbar pill with the OpenRouter balance and today's spend; opens a usage popover. Hidden without a key. */
export function CreditPill() {
  const { data: account } = useOpenRouterAccount()
  if (!account || (!account.configured && !account.management_key)) return null
  const left = remaining(account)
  const low = left != null && left < 0.5

  return (
    <Popover
      align="end"
      className={s.popover}
      trigger={
        <button className={cn(s.pill, !account.ok && s.error, low && s.low)} aria-label="OpenRouter usage">
          <Wallet size={13} />
          {!account.ok ? (
            <span>OpenRouter key problem</span>
          ) : (
            <>
              {left != null && <span className={s.amount}>{formatBalance(left)}</span>}
              <span className={s.today}>{formatUsd(account.usage_daily ?? account.studio_today)} today</span>
            </>
          )}
        </button>
      }
    >
      <UsagePanel account={account} />
    </Popover>
  )
}

function UsagePanel({ account }: { account: OpenRouterAccount }) {
  const refresh = useRefreshOpenRouterAccount()
  const left = remaining(account)
  return (
    <div className={s.panel}>
      <div className={s.head}>
        <StatusDot status={account.ok ? 'active' : 'error'} />
        <span className={s.title}>OpenRouter</span>
        {account.label && <span className={s.label}>{account.label}</span>}
        <IconButton size="sm" label="Refresh" icon={<RefreshCw />} onClick={() => refresh.mutate()} disabled={refresh.isPending} />
      </div>
      {account.error && <p className={s.errorText}>{account.error}</p>}
      <div className={s.balance}>
        <span className={s.balanceValue}>{left != null ? formatBalance(left) : '—'}</span>
        <span className={s.balanceLabel}>
          {account.balance != null ? 'credits left' : account.limit_remaining != null ? 'left on this key' : 'add a management key in Settings to see the balance'}
        </span>
      </div>
      <dl className={s.grid}>
        <div>
          <dt>Today</dt>
          <dd>{formatUsd(account.usage_daily ?? 0)}</dd>
        </div>
        <div>
          <dt>This week</dt>
          <dd>{formatUsd(account.usage_weekly ?? 0)}</dd>
        </div>
        <div>
          <dt>This month</dt>
          <dd>{formatUsd(account.usage_monthly ?? 0)}</dd>
        </div>
        <div>
          <dt>Studio today</dt>
          <dd>{formatUsd(account.studio_today)}</dd>
        </div>
      </dl>
      {account.recent.length > 0 && (
        <div className={s.recent}>
          <span className={s.recentTitle}>Recent charges</span>
          <ul>
            {account.recent.map((c) => (
              <li key={c.id}>
                <span className={s.kind}>{KIND_LABEL[c.kind]}</span>
                <span className={s.model} title={c.model}>
                  {c.model}
                </span>
                <span className={s.when}>{timeAgo(c.ts)}</span>
                <span className={s.cost}>{c.cost != null ? formatUsd(c.cost) : '—'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className={s.actions}>
        <Button asChild size="sm" variant="primary">
          <a href={CREDITS_URL} target="_blank" rel="noreferrer">
            <CreditCard size={14} /> Buy credits
          </a>
        </Button>
        <Button asChild size="sm" variant="ghost">
          <Link to="/settings">
            <Settings size={14} /> Provider settings
          </Link>
        </Button>
      </div>
    </div>
  )
}
