import { useNavigate } from 'react-router'
import { Boxes, CreditCard, ExternalLink, RefreshCw, Route } from 'lucide-react'
import { Badge, Button, Field, IconButton } from '@studio/ui'
import type { OpenRouterAccount } from '../../../api/contracts/openrouter'
import { useOpenRouterAccount, useRefreshOpenRouterAccount } from '../../../api/openrouter'
import { formatBalance, formatUsd } from '../../../lib/money'
import { CREDITS_URL, KEYS_URL, accountStatus, remaining } from '../../openrouter/account'
import { SecretInput, type SettingsForm } from '../form'
import { ProviderCard } from './ProviderCard'
import s from './Providers.module.css'

export function OpenRouterCard({ form }: { form: SettingsForm }) {
  const { data: account } = useOpenRouterAccount()
  const refresh = useRefreshOpenRouterAccount()
  const navigate = useNavigate()
  const status = accountStatus(account)

  return (
    <ProviderCard
      icon={<Route />}
      name="OpenRouter"
      description="One key and one balance for hundreds of cloud models — chat, images, speech and transcription."
      status={
        <Badge size="sm" tone={status.tone} dot>
          {status.label}
        </Badge>
      }
    >
      <div className={s.row2}>
        <Field label="API key" hint="Used for every request. Spending stops when your credits (or the key's limit) run out.">
          {(id) => <SecretInput id={id} {...form.secret('openrouter_api_key')} placeholder="sk-or-v1-…" />}
        </Field>
        <Field label="Management key" hint="Optional — only read to show your credit balance.">
          {(id) => <SecretInput id={id} {...form.secret('openrouter_management_key')} placeholder="Optional" />}
        </Field>
      </div>

      {account?.error && <p className={s.error}>{account.error}</p>}
      {account?.ok && <AccountStats account={account} />}

      <div className={s.actions}>
        <Button asChild size="sm" variant="primary">
          <a href={CREDITS_URL} target="_blank" rel="noreferrer">
            <CreditCard size={14} /> Buy credits
          </a>
        </Button>
        <Button asChild size="sm" variant="ghost">
          <a href={KEYS_URL} target="_blank" rel="noreferrer">
            <ExternalLink size={14} /> Manage keys
          </a>
        </Button>
        <Button size="sm" variant="ghost" iconLeft={<Boxes />} onClick={() => navigate('/models?tab=cloud')}>
          Browse cloud models
        </Button>
        {(account?.configured || account?.management_key) && (
          <IconButton size="sm" label="Refresh balance" icon={<RefreshCw />} onClick={() => refresh.mutate()} disabled={refresh.isPending} />
        )}
      </div>
    </ProviderCard>
  )
}

function AccountStats({ account }: { account: OpenRouterAccount }) {
  const left = remaining(account)
  const stats = [
    {
      label: account.balance != null ? 'Credits left' : 'Key limit left',
      value: left != null ? formatBalance(left) : '—',
      hint: left == null ? 'Add a management key to see the account balance' : account.limit_reset ? `Resets ${account.limit_reset}` : undefined,
    },
    { label: 'Today', value: formatUsd(account.usage_daily ?? 0), hint: 'UTC day, every app using this key' },
    { label: 'This month', value: formatUsd(account.usage_monthly ?? 0) },
    { label: 'Studio today', value: formatUsd(account.studio_today), hint: 'Spent from this studio since midnight' },
  ]
  return (
    <dl className={s.stats}>
      {stats.map((st) => (
        <div key={st.label} className={s.stat} title={st.hint}>
          <dt>{st.label}</dt>
          <dd>{st.value}</dd>
        </div>
      ))}
    </dl>
  )
}
