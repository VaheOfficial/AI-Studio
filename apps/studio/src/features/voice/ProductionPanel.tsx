import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronDown, SlidersHorizontal } from 'lucide-react'
import { Field, SeedField, SegmentedControl, Slider, Switch, cn } from '@studio/ui'
import type { Production } from './production'
import s from './ProductionPanel.module.css'

const TIERS = [
  { value: '8', label: 'Fast' },
  { value: '16', label: 'Balanced' },
  { value: '32', label: 'Quality' },
  { value: '64', label: 'Max' },
] as const

/** Collapsible "Advanced" production overrides for OmniVoice. */
export function ProductionPanel({ value, onChange }: { value: Production; onChange: (next: Production) => void }) {
  const [open, setOpen] = useState(false)
  const set = <K extends keyof Production>(key: K, v: Production[K]) => onChange({ ...value, [key]: v })
  const tier = TIERS.find((t) => Number(t.value) === value.num_step)?.value

  return (
    <div className={s.panel}>
      <button className={s.toggle} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <SlidersHorizontal size={14} />
        <span>Advanced</span>
        <span className={s.summary}>
          {value.num_step} steps · CFG {value.guidance_scale}
          {value.seed !== null && ` · seed ${value.seed}`}
        </span>
        <ChevronDown size={15} className={cn(s.chevron, open && s.open)} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            className={s.body}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className={s.inner}>
              <Field label="Quality" aside={`${value.num_step} steps`} hint="More decoding steps: cleaner speech, slower render.">
                <SegmentedControl
                  block
                  size="sm"
                  value={tier ?? ''}
                  onValueChange={(v) => set('num_step', Number(v))}
                  segments={TIERS.map((t) => ({ value: t.value, label: t.label }))}
                />
              </Field>
              <Field label="Steps" aside={value.num_step}>
                <Slider aria-label="Steps" value={value.num_step} onValueChange={(v) => set('num_step', v)} min={4} max={64} step={1} />
              </Field>
              <Field label="Guidance (CFG)" aside={value.guidance_scale.toFixed(1)} hint="How strongly the voice and text condition the result.">
                <Slider aria-label="Guidance" value={value.guidance_scale} onValueChange={(v) => set('guidance_scale', v)} min={0} max={5} step={0.1} />
              </Field>
              <Field label="Duration" aside={value.duration > 0 ? `${value.duration.toFixed(1)} s` : 'Natural'} hint="Fix the length of the whole take (overrides speed).">
                <Slider aria-label="Duration" value={value.duration} onValueChange={(v) => set('duration', v)} min={0} max={60} step={0.5} />
              </Field>
              <Field label="Time shift" aside={value.t_shift.toFixed(2)}>
                <Slider aria-label="Time shift" value={value.t_shift} onValueChange={(v) => set('t_shift', v)} min={0.05} max={1} step={0.05} />
              </Field>
              <Field label="Position temperature" aside={value.position_temperature.toFixed(1)}>
                <Slider
                  aria-label="Position temperature"
                  value={value.position_temperature}
                  onValueChange={(v) => set('position_temperature', v)}
                  min={0}
                  max={10}
                  step={0.5}
                />
              </Field>
              <Field label="Token temperature" aside={value.class_temperature.toFixed(2)} hint="0 = greedy (most stable).">
                <Slider
                  aria-label="Token temperature"
                  value={value.class_temperature}
                  onValueChange={(v) => set('class_temperature', v)}
                  min={0}
                  max={2}
                  step={0.05}
                />
              </Field>
              <Switch checked={value.denoise} onCheckedChange={(v) => set('denoise', v)} label="Denoise" description="Clean up noise carried over from the reference." />
              <Switch
                checked={value.postprocess_output}
                onCheckedChange={(v) => set('postprocess_output', v)}
                label="Post-process"
                description="Trim long silences, fade and pad the edges."
              />
              <SeedField value={value.seed} onChange={(v) => set('seed', v)} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
