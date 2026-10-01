import { Info, Ruler } from 'lucide-react'
import { Field, IconButton, Input, SeedField, SegmentedControl, Select, Slider, cn } from '@studio/ui'
import type { ImageModelProfile, ImageOption } from '../../api/contracts/image'
import { AspectPicker } from '../../components/AspectPicker'
import type { ImageDraft } from './draft'
import { ASPECTS, fitSize, ratioOf, sizeForRatio } from './sizes'
import s from './ImageSettings.module.css'

const GUIDANCE_LABEL = { cfg: 'Guidance (CFG)', 'true-cfg': 'True CFG', distilled: 'Distilled guidance', none: 'Guidance' }
const DEFAULT_SCHEDULER = 'default'

export interface ImageSettingsProps {
  profile: ImageModelProfile
  draft: ImageDraft
  patch: (p: Partial<ImageDraft>) => void
  /** Output size follows this width/height ratio (an edit source image) instead of the aspect picker. */
  lockedRatio?: number
}

function OptionField({ option, value, onChange }: { option: ImageOption; value: string; onChange: (v: string) => void }) {
  return (
    <Field label={option.label}>
      {(id) =>
        option.values.length <= 4 ? (
          <SegmentedControl block size="sm" value={value} onValueChange={onChange} segments={option.values.map((v) => ({ value: v, label: v }))} />
        ) : (
          <Select id={id} size="sm" value={value} onValueChange={onChange} options={option.values.map((v) => ({ value: v, label: v }))} />
        )
      }
    </Field>
  )
}

function SizeField({ profile, draft, patch, lockedRatio }: ImageSettingsProps) {
  if (!profile.size) return null
  const size = profile.size
  const label = `${draft.width}×${draft.height}`
  if (lockedRatio) {
    return (
      <Field label="Output size" aside={label}>
        <p className={s.sizeHint}>Follows the source image's aspect ratio</p>
      </Field>
    )
  }
  const setDim = (key: 'width' | 'height', raw: string) => patch({ aspect: null, [key]: Number(raw.replace(/\D/g, '')) || 0 })
  const settle = () => {
    const { w, h } = fitSize(draft.width, draft.height, profile)
    patch({ width: w, height: h })
  }
  return (
    <Field
      label="Size"
      aside={
        <span className={s.sizeAside}>
          {label}
          <IconButton
            size="sm"
            label={draft.aspect ? 'Custom size' : 'Preset ratios'}
            icon={<Ruler />}
            active={!draft.aspect}
            onClick={() => (draft.aspect ? patch({ aspect: null }) : patch({ aspect: '1:1', ...wh(sizeForRatio(1, profile)) }))}
          />
        </span>
      }
    >
      {draft.aspect ? (
        <AspectPicker aspects={ASPECTS} hue="var(--hue-image)" value={draft.aspect} onChange={(a) => patch({ aspect: a, ...wh(sizeForRatio(ratioOf(a), profile)) })} />
      ) : (
        <div className={s.custom}>
          <Input size="sm" aria-label="Width" value={String(draft.width)} onChange={(e) => setDim('width', e.target.value)} onBlur={settle} />
          <span className={s.times}>×</span>
          <Input size="sm" aria-label="Height" value={String(draft.height)} onChange={(e) => setDim('height', e.target.value)} onBlur={settle} />
          <span className={s.sizeHint}>
            {size.min}–{size.max}, ×{size.step}
          </span>
        </div>
      )}
    </Field>
  )
}

const wh = (v: { w: number; h: number }) => ({ width: v.w, height: v.h })

/** Parameters that adapt to what the selected model supports. */
export function ImageSettings(props: ImageSettingsProps) {
  const { profile, draft, patch } = props
  const counts = ['1', '2', '4'].filter((c) => Number(c) <= profile.max_count)
  return (
    <>
      {profile.negative_prompt && (
        <Field label="Negative prompt" hint={profile.guidance === 'cfg' && draft.guidance === 0 ? 'Only used when guidance is above 0' : undefined}>
          {(id) => <Input id={id} value={draft.negative} onChange={(e) => patch({ negative: e.target.value })} placeholder="blurry, watermark, extra fingers" />}
        </Field>
      )}

      <SizeField {...props} />

      {profile.options.map((o) => (
        <OptionField key={o.id} option={o} value={draft.options[o.id] ?? o.default} onChange={(v) => patch({ options: { ...draft.options, [o.id]: v } })} />
      ))}

      {(profile.steps_range || profile.guidance_range) && (
        <div className={s.row2}>
          {profile.steps_range && (
            <Field label="Steps" aside={draft.steps}>
              <Slider aria-label="Steps" value={draft.steps} onValueChange={(v) => patch({ steps: v })} min={profile.steps_range[0]} max={profile.steps_range[1]} />
            </Field>
          )}
          {profile.guidance_range && (
            <Field label={GUIDANCE_LABEL[profile.guidance]} aside={draft.guidance.toFixed(1)}>
              <Slider
                aria-label="Guidance"
                value={draft.guidance}
                onValueChange={(v) => patch({ guidance: v })}
                min={profile.guidance_range[0]}
                max={profile.guidance_range[1]}
                step={0.1}
              />
            </Field>
          )}
        </div>
      )}

      {profile.schedulers.length > 0 && (
        <Field label="Sampler">
          {(id) => (
            <Select
              id={id}
              value={draft.scheduler || DEFAULT_SCHEDULER}
              onValueChange={(v) => patch({ scheduler: v === DEFAULT_SCHEDULER ? '' : v })}
              options={[{ value: DEFAULT_SCHEDULER, label: 'Model default' }, ...profile.schedulers.map((x) => ({ value: x.id, label: x.label }))]}
            />
          )}
        </Field>
      )}

      {counts.length > 1 && (
        <Field label="Images">
          <SegmentedControl
            block
            value={String(Math.min(draft.count, profile.max_count))}
            onValueChange={(v) => patch({ count: Number(v) })}
            segments={counts.map((c) => ({ value: c, label: c }))}
          />
        </Field>
      )}

      {profile.seed && (
        <SeedField
          value={draft.lockSeed ? draft.seed : null}
          onChange={(v) => patch(v === null ? { lockSeed: false } : { seed: v, lockSeed: true })}
          lastUsed={draft.lockSeed ? undefined : draft.lastSeed}
        />
      )}
    </>
  )
}

/** Honest caveats for the selected model: cloud cost, offload, license, missing companions. */
export function ModelNotes({ profile, className }: { profile: ImageModelProfile; className?: string }) {
  const lines = [...(profile.cost ? [`Cost: ${profile.cost}`] : []), ...profile.notes]
  if (!lines.length) return null
  return (
    <div className={cn(s.notes, className)}>
      <Info className={s.notesIcon} />
      <ul>
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </div>
  )
}
