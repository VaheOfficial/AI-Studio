import { Link } from 'react-router'
import { ArrowRight, PlugZap, Zap } from 'lucide-react'
import { Badge, Field, Select, Skeleton } from '@studio/ui'
import type { InstalledModel, ModelKind } from '../api/types'
import { KINDS } from '../lib/kinds'
import s from './ModelPicker.module.css'

export interface ModelPickerProps {
  kind: ModelKind
  models: InstalledModel[]
  selected: InstalledModel | undefined
  onSelect: (id: string) => void
  isLoading?: boolean
  unavailable?: boolean
  label?: string
}

export function ModelPicker({ kind, models, selected, onSelect, isLoading, unavailable, label = 'Model' }: ModelPickerProps) {
  const meta = KINDS[kind]
  if (unavailable) {
    return (
      <div className={s.empty} style={{ ['--hue' as string]: 'var(--danger)' }}>
        <span className={s.emptyIcon}>
          <PlugZap />
        </span>
        <span className={s.emptyText}>
          <strong>Studio server is offline</strong>
          <span>Reconnecting automatically…</span>
        </span>
      </div>
    )
  }
  if (isLoading) {
    return (
      <Field label={label}>
        <Skeleton height={34} radius={8} />
      </Field>
    )
  }
  if (models.length === 0) {
    return (
      <Link to={`/models?tab=catalog&kind=${kind}`} className={s.empty} style={{ ['--hue' as string]: meta.hue }}>
        <span className={s.emptyIcon}>{meta.icon}</span>
        <span className={s.emptyText}>
          <strong>No {meta.plural.toLowerCase()} installed</strong>
          <span>Browse the catalog to download one</span>
        </span>
        <ArrowRight size={16} className={s.arrow} />
      </Link>
    )
  }
  return (
    <Field label={label}>
      {(id) => (
        <Select
          id={id}
          value={selected?.id}
          onValueChange={onSelect}
          options={models.map((m) => ({
            value: m.id,
            label: m.name,
            icon: m.status === 'loaded' ? <Zap className={s.loaded} /> : undefined,
            description: m.status === 'loaded' ? 'Loaded in memory' : m.status === 'error' ? m.error : undefined,
          }))}
          renderValue={(o) => (
            <span className={s.value}>
              <span className={s.name}>{o?.label}</span>
              {selected?.status === 'loaded' && (
                <Badge size="sm" tone="success" dot>
                  Loaded
                </Badge>
              )}
              {selected?.status === 'loading' && (
                <Badge size="sm" tone="warning" dot pulse>
                  Loading
                </Badge>
              )}
            </span>
          )}
        />
      )}
    </Field>
  )
}
