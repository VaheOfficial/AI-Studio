import { Cloud, Zap } from 'lucide-react'
import { Badge, Field, Select, type SelectGroup } from '@studio/ui'
import type { ImageModelProfile } from '../../api/contracts/image'
import { useLive } from '../../api/live'
import type { InstalledModel } from '../../api/types'
import { ModelPicker } from '../../components/ModelPicker'
import s from './ImageModelPicker.module.css'

const GIB = 2 ** 30

/** "GGUF Q4_K_S", "NF4", "fp8"… when the installed weights are a quantized / non-diffusers variant. */
function variantLabel(m: InstalledModel) {
  const fmt = m.format && m.format !== 'diffusers' ? m.format.toUpperCase() : ''
  return [fmt, m.quant].filter(Boolean).join(' ')
}

function FitBadge({ profile }: { profile: ImageModelProfile }) {
  const total = useLive((st) => st.system?.gpus[0]?.vram_total)
  if (profile.location === 'cloud') {
    return (
      <Badge size="sm" tone="info" icon={<Cloud size={11} />}>
        Cloud
      </Badge>
    )
  }
  if (!profile.vram_gb || !total) return null
  const fits = profile.vram_gb * GIB <= total * 0.95
  return (
    <Badge size="sm" tone={fits ? 'success' : 'warning'} title={`Needs ~${profile.vram_gb} GB VRAM`}>
      {fits ? `${profile.vram_gb} GB` : 'CPU offload'}
    </Badge>
  )
}

export interface ImageModelPickerProps {
  models: InstalledModel[]
  profiles: ImageModelProfile[]
  selected: InstalledModel | undefined
  onSelect: (id: string) => void
  isLoading?: boolean
  unavailable?: boolean
}

/** Model picker grouped Local / Cloud, with variant (format/quant), fit and loaded state. */
export function ImageModelPicker({ models, profiles, selected, onSelect, isLoading, unavailable }: ImageModelPickerProps) {
  if (unavailable || isLoading || models.length === 0) {
    return <ModelPicker kind="image" models={[]} selected={undefined} onSelect={onSelect} isLoading={isLoading} unavailable={unavailable} />
  }
  const profileOf = (m: InstalledModel) => profiles.find((p) => p.model_id === m.id)
  const option = (m: InstalledModel) => {
    const p = profileOf(m)
    const detail = p?.location === 'cloud' ? p.cost : p?.vram_gb ? `~${p.vram_gb} GB VRAM` : undefined
    return {
      value: m.id,
      label: m.name,
      icon: m.status === 'loaded' ? <Zap className={s.loaded} /> : p?.location === 'cloud' ? <Cloud /> : undefined,
      description: [p?.family, variantLabel(m), detail].filter(Boolean).join(' · '),
    }
  }
  const groups: SelectGroup[] = [
    { label: 'Local', options: models.filter((m) => profileOf(m)?.location !== 'cloud').map(option) },
    { label: 'Cloud', options: models.filter((m) => profileOf(m)?.location === 'cloud').map(option) },
  ].filter((g) => g.options.length > 0)
  const profile = selected && profileOf(selected)
  const variant = selected && variantLabel(selected)

  return (
    <Field label="Model">
      {(id) => (
        <Select
          id={id}
          value={selected?.id}
          onValueChange={onSelect}
          options={groups}
          renderValue={(o) => (
            <span className={s.value}>
              <span className={s.name}>{o?.label}</span>
              {variant && (
                <Badge size="sm" tone="accent">
                  {variant}
                </Badge>
              )}
              {profile && <FitBadge profile={profile} />}
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
