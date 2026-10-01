import { useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Mic2, Sparkles } from 'lucide-react'
import { Button, Combobox, Field, Kbd, Progress, Slider, Textarea, cn, type ComboboxOption } from '@studio/ui'
import { AUTO_VOICE, type VoiceProfile, type VoiceTake } from '../../api/contracts/voice'
import type { InstalledModel } from '../../api/types'
import { useLanguageName, useOnJobDone, useSpeak, useVoiceProfiles, vk } from '../../api/voice'
import { ModelPicker } from '../../components/ModelPicker'
import { StudioLayout } from '../../components/Page'
import { useModelChoice } from '../../components/useModelChoice'
import { AUTO_LANGUAGE, LanguagePicker } from './LanguagePicker'
import { ProductionPanel } from './ProductionPanel'
import { DEFAULT_PRODUCTION, productionFields, type Production } from './production'
import { TagMenu } from './TagMenu'
import { TakesPanel } from './TakesPanel'
import { VoiceOrb } from './VoiceOrb'
import s from './SpeakTab.module.css'

/** Voices an engine can speak with: its own presets, plus your clones/designs for the cloning engines. */
function voicesFor(m: InstalledModel | undefined, profiles: VoiceProfile[]): VoiceProfile[] {
  if (!m) return []
  const presets = profiles.filter((p) => p.kind === 'preset' && p.model_id === m.id)
  if (m.runtime === 'omnivoice') return profiles.filter((p) => p.kind !== 'preset')
  if (m.runtime === 'chatterbox') return [...presets, ...profiles.filter((p) => p.kind !== 'preset' && (p.ref_audio_url || p.locked_audio_url))]
  return presets
}

export function SpeakTab() {
  const { models, selected, select, isLoading, unavailable } = useModelChoice('voice', 'speak', (m) => m.runtime === 'omnivoice', 'voice')
  const { data: profiles = [] } = useVoiceProfiles()
  const [params] = useSearchParams()
  const [voiceId, setVoiceId] = useState<string | undefined>(params.get('voice') ?? undefined)
  const [language, setLanguage] = useState(AUTO_LANGUAGE)
  const [text, setText] = useState('')
  const [speed, setSpeed] = useState(1)
  const [exaggeration, setExaggeration] = useState(0.5)
  const [production, setProduction] = useState<Production>(DEFAULT_PRODUCTION)
  const [jobId, setJobId] = useState<string>()
  const script = useRef<HTMLTextAreaElement>(null)
  const qc = useQueryClient()
  const speak = useSpeak()
  const languageName = useLanguageName()
  const job = useOnJobDone(jobId, () => void qc.invalidateQueries({ queryKey: vk.takes }))
  const running = job?.status === 'queued' || job?.status === 'running'

  const runtime = selected?.runtime
  const omni = runtime === 'omnivoice'
  const available = useMemo(() => voicesFor(selected, profiles), [selected, profiles])
  const voice = available.find((v) => v.id === voiceId) ?? (omni ? undefined : available[0])

  const voiceOptions = useMemo<ComboboxOption[]>(() => {
    const describe = (p: VoiceProfile) =>
      [p.kind === 'preset' ? null : p.kind, p.gender, languageName(p.language), p.is_locked ? 'locked' : null].filter(Boolean).join(' · ')
    return [
      ...(omni ? [{ value: AUTO_VOICE, label: 'Auto voice', description: 'OmniVoice picks a voice' }] : []),
      ...available.map((p) => ({
        value: p.id,
        label: p.name,
        description: describe(p),
        keywords: `${p.tags.join(' ')} ${p.instruct ?? ''}`,
        group: p.kind === 'preset' ? 'Presets' : 'My voices',
      })),
    ]
  }, [available, omni, languageName])

  const chooseVoice = (id: string) => {
    setVoiceId(id)
    const p = available.find((v) => v.id === id)
    setLanguage(p?.language ?? AUTO_LANGUAGE)
  }

  const submit = () => {
    if (!selected || !text.trim() || running || (!omni && !voice)) return
    speak.mutate(
      {
        model_id: selected.id,
        text: text.trim(),
        voice_id: voice?.id ?? AUTO_VOICE,
        speed,
        exaggeration: runtime === 'chatterbox' ? exaggeration : undefined,
        ...(omni ? { language, ...productionFields(production) } : {}),
      },
      { onSuccess: (j) => setJobId(j.id) },
    )
  }

  const reuse = (t: VoiceTake) => {
    setText(t.text)
    if (t.profile_id && available.some((v) => v.id === t.profile_id)) setVoiceId(t.profile_id)
    else if (!t.profile_id) setVoiceId(AUTO_VOICE)
    setLanguage(t.language ?? AUTO_LANGUAGE)
    const p = t.params as Partial<Production> & { speed?: number }
    if (p.speed) setSpeed(p.speed)
    setProduction((cur) => ({
      ...cur,
      ...Object.fromEntries(Object.entries(p).filter(([k]) => k in DEFAULT_PRODUCTION)),
      duration: p.duration ?? 0,
      seed: t.seed ?? null,
    }))
    script.current?.focus()
  }

  const storedIds = useMemo(() => new Set(profiles.filter((p) => p.kind !== 'preset').map((p) => p.id)), [profiles])
  const seconds = Math.max(1, Math.round(text.trim().split(/\s+/).filter(Boolean).length / 2.6 / speed))

  const controls = (
    <div className={s.controls}>
      <ModelPicker kind="voice" label="Engine" models={models} selected={selected} onSelect={select} isLoading={isLoading} unavailable={unavailable} />
      {selected && (
        <Field label="Voice" aside={`${available.length} saved`} hint={omni && available.length === 0 ? 'Design or clone a voice to see it here.' : undefined}>
          {(id) => (
            <Combobox
              id={id}
              value={voice?.id ?? (omni ? AUTO_VOICE : undefined)}
              onValueChange={chooseVoice}
              options={voiceOptions}
              placeholder={available.length ? 'Pick a voice' : 'No voices for this engine'}
              searchPlaceholder="Search voices…"
            />
          )}
        </Field>
      )}
      {selected && runtime !== 'openrouter' && (
        <Field label="Language" hint={omni ? undefined : `${selected.name} speaks English only — use OmniVoice for other languages.`}>
          {(id) => <LanguagePicker id={id} value={language} onChange={setLanguage} engine={runtime} />}
        </Field>
      )}
      <Field label="Speed" aside={`${speed.toFixed(2)}×`}>
        <Slider aria-label="Speed" value={speed} onValueChange={setSpeed} min={0.5} max={2} step={0.05} />
      </Field>
      {runtime === 'chatterbox' && (
        <Field label="Expressiveness" aside={exaggeration.toFixed(2)} hint="Higher values are more emotive and dramatic.">
          <Slider aria-label="Expressiveness" value={exaggeration} onValueChange={setExaggeration} min={0} max={1} step={0.05} />
        </Field>
      )}
      {omni && <ProductionPanel value={production} onChange={setProduction} />}
    </div>
  )

  return (
    <StudioLayout controls={controls} hue="var(--hue-voice)">
      <div className={s.canvas}>
        <div className={cn(s.editor, running && s.editorBusy)}>
          <div className={s.editorHead}>
            <span className={s.speaker}>
              {voice ? <VoiceOrb seed={voice.id} size={22} active={running} /> : <Mic2 size={15} />}
              {voice?.name ?? (omni ? 'Auto voice' : 'Script')}
            </span>
            <span className={s.headTools}>
              {omni && <TagMenu target={script} text={text} onChange={setText} />}
              <span className={s.counts}>
                {text.length.toLocaleString()} chars · ~{seconds}s
              </span>
            </span>
          </div>
          <Textarea
            ref={script}
            autoResize
            minRows={8}
            maxRows={22}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              omni
                ? 'Type or paste a script. Add [pause 500ms] for silence or [laughter] for a reaction; wrap a word as [[GIF|jiff]] to respell it once.'
                : 'Type or paste a script. Line breaks become natural pauses.'
            }
            className={s.script}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                submit()
              }
            }}
          />
          <div className={s.editorFoot}>
            {running ? (
              <span className={s.status}>
                <Progress value={job.progress} size="xs" className={s.progress} />
                <span>{job.message}</span>
              </span>
            ) : (
              <span className={s.hint}>
                <Kbd>Ctrl</Kbd> <Kbd>Enter</Kbd>
              </span>
            )}
            <Button
              variant="glow"
              iconLeft={<Sparkles />}
              loading={speak.isPending || running}
              disabled={!selected || !text.trim() || (!omni && !voice)}
              onClick={submit}
            >
              Generate speech
            </Button>
          </div>
        </div>

        <TakesPanel onReuse={reuse} lockable={(t) => t.engine === 'omnivoice' && !!t.profile_id && storedIds.has(t.profile_id)} />
      </div>
    </StudioLayout>
  )
}
