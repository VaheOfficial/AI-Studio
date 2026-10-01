import { useRef, useState, type DragEvent } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  AudioLines,
  Clapperboard,
  FileText,
  Gauge,
  Languages,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Users,
  X,
} from 'lucide-react'
import {
  AudioPlayer,
  Badge,
  Button,
  ChipGroup,
  Field,
  IconButton,
  Input,
  SegmentedControl,
  Select,
  Slider,
  Switch,
  Textarea,
  Tooltip,
} from '@studio/ui'
import type { DubProject, DubTiming } from '../../api/contracts/dub'
import { useChatModels, useModelsOfKind } from '../../api/hooks'
import { useLive } from '../../api/live'
import { useLanguageName, useVoiceProfiles } from '../../api/voice'
import { AUTO_LANGUAGE, LanguagePicker } from '../voice/LanguagePicker'
import { useDubStatus, useImportSubtitles, usePatchDubProject, useRunDub } from './api'
import { fmtDuration, speakerColor } from './format'
import { PreviewPlayer } from './PreviewPlayer'
import { useSettings } from './settings'
import { SidebarSection } from './SidebarSection'
import { VoiceSampleDialog } from './VoiceSampleDialog'
import s from './Sidebar.module.css'

/** Regional dialects the translation prompt knows (VoiceStudio `dialects.ts`), keyed by target language id. */
const DIALECTS: Record<string, [string, string][]> = {
  es: [['es-ES', 'Spain'], ['es-MX', 'Mexico'], ['es-AR', 'Argentina'], ['es-CO', 'Colombia'], ['es-CL', 'Chile']],
  pt: [['pt-BR', 'Brazil'], ['pt-PT', 'Portugal']],
  en: [['en-US', 'US'], ['en-GB', 'UK'], ['en-AU', 'Australia'], ['en-IN', 'India']],
  fr: [['fr-FR', 'France'], ['fr-CA', 'Québec'], ['fr-BE', 'Belgium']],
  de: [['de-DE', 'Germany'], ['de-AT', 'Austria'], ['de-CH', 'Switzerland']],
  arb: [['ar-EG', 'Egypt'], ['ar-SA', 'Gulf'], ['ar-MA', 'Morocco']],
  nl: [['nl-NL', 'Netherlands'], ['nl-BE', 'Flanders']],
}

const TIMING: { value: DubTiming; label: string; hint: string }[] = [
  { value: 'strict_slot', label: 'Lip-sync', hint: 'Each line is rendered to its exact slot (stretched or gently slowed).' },
  { value: 'smart_fit', label: 'Smart fit', hint: 'Mild audio speed-up, then per-segment video slow-down for the rest.' },
  { value: 'stretch_video', label: 'Stretch video', hint: 'Audio at natural pace; the video stretches to match.' },
  { value: 'concise', label: 'Concise', hint: 'Natural pace; a line may run on into the silence after it. Lines still too long are cut and marked.' },
]

/* ------------------------------------------------------------------ source */

export function SourceSection({ project, busy, onClose }: { project: DubProject; busy: boolean; onClose: () => void }) {
  const patch = usePatchDubProject(project.id)
  const transcribe = useRunDub(project.id, 'transcribe')
  const importSrt = useImportSubtitles(project.id)
  const update = useSettings(project)
  const stt = useModelsOfKind('stt').filter((m) => m.runtime === 'faster-whisper')
  const srtInput = useRef<HTMLInputElement>(null)
  const [speakers, setSpeakers] = useState(project.num_speakers ? String(project.num_speakers) : '')
  const diar = project.diarization
  return (
    <SidebarSection title="Source" icon={<Clapperboard />} aside={fmtDuration(project.source.duration)}>
      <div className={s.fileChip}>
        <IconButton size="sm" label="All projects" icon={<ArrowLeft />} onClick={onClose} />
        <span className={s.fileName} title={project.source.url ?? project.source.filename}>
          {project.source.filename}
        </span>
      </div>
      <Field label="Spoken language">
        {(id) => (
          <LanguagePicker
            id={id}
            size="sm"
            value={project.source_lang ?? AUTO_LANGUAGE}
            onChange={(v) => patch.mutate({ source_lang: v === AUTO_LANGUAGE ? '' : v })}
          />
        )}
      </Field>
      <div className={s.row2}>
        <Field label="Speakers" hint="Empty = detect">
          {(id) => (
            <Input
              id={id}
              size="sm"
              type="number"
              min={1}
              max={20}
              placeholder="Auto"
              value={speakers}
              onChange={(e) => setSpeakers(e.target.value)}
              onBlur={() => patch.mutate({ num_speakers: Number(speakers) || 0 })}
            />
          )}
        </Field>
        <Field label="Recognition">
          {(id) => (
            <Select
              id={id}
              size="sm"
              value={project.settings.asr_model_id}
              onValueChange={(v) => update((st) => void (st.asr_model_id = v))}
              options={stt.map((m) => ({ value: m.id, label: m.name }))}
              placeholder="Install Whisper"
            />
          )}
        </Field>
      </div>
      {diar && (
        <div className={s.diar}>
          <Badge size="sm" tone={diar.source === 'heuristic' ? 'warning' : 'success'} dot>
            {{ pyannote: 'pyannote 3.1', phrase_embeddings: 'pyannote + phrase clustering', heuristic: 'Pause heuristic', single: 'Single speaker', imported: 'Imported subtitles' }[diar.source]}
          </Badge>
          {diar.warning && <p className={s.warn}>{diar.warning}</p>}
        </div>
      )}
      <div className={s.actions}>
        <Button size="sm" variant="secondary" iconLeft={<RefreshCw />} disabled={busy} loading={transcribe.isPending} onClick={() => transcribe.mutate({})}>
          Re-transcribe
        </Button>
        <Button size="sm" variant="ghost" iconLeft={<FileText />} disabled={busy} onClick={() => srtInput.current?.click()}>
          Import SRT
        </Button>
        <input
          ref={srtInput}
          type="file"
          accept=".srt,.vtt"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) importSrt.mutate({ file })
            e.target.value = ''
          }}
        />
      </div>
    </SidebarSection>
  )
}

/* ------------------------------------------------------------------ preview */

export function PreviewSection({ project, linePreview }: { project: DubProject; linePreview: string | null }) {
  return (
    <SidebarSection title="Preview" icon={<AudioLines />}>
      <PreviewPlayer project={project} />
      {linePreview && (
        <div className={s.linePreview}>
          <span className={s.label}>Line preview</span>
          <AudioPlayer src={linePreview} compact autoPlay color="var(--hue-voice)" height={32} />
        </div>
      )}
    </SidebarSection>
  )
}

/* ------------------------------------------------------------------ targets + translator */

export function TargetsSection({ project, busy }: { project: DubProject; busy: boolean }) {
  const update = useSettings(project)
  const languageName = useLanguageName()
  const { data: chatModels = [] } = useChatModels()
  const { data: status } = useDubStatus()
  const engine = useLive((st) => st.models.find((m) => m.id === project.settings.tts.model_id)?.runtime)
  const t = project.settings.translation
  const [brief, setBrief] = useState(t.instructions)
  const [adding, setAdding] = useState('')
  return (
    <SidebarSection title="Target languages" icon={<Languages />} aside={project.settings.targets.length || undefined}>
      <div className={s.targets}>
        {project.settings.targets.map((lang) => (
          <span key={lang} className={s.target}>
            {languageName(lang)}
            {DIALECTS[lang] && (
              <select
                className={s.dialect}
                value={t.dialects[lang] ?? ''}
                aria-label={`${languageName(lang)} dialect`}
                onChange={(e) =>
                  update((st) => {
                    if (e.target.value) st.translation.dialects[lang] = e.target.value
                    else delete st.translation.dialects[lang]
                  })
                }
              >
                <option value="">Default</option>
                {DIALECTS[lang].map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            )}
            <button type="button" aria-label={`Remove ${languageName(lang)}`} disabled={busy} onClick={() => update((st) => void (st.targets = st.targets.filter((x) => x !== lang)))}>
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      <LanguagePicker
        size="sm"
        allowAuto={false}
        value={adding}
        engine={engine}
        onChange={(lang) => {
          setAdding('')
          if (!project.settings.targets.includes(lang)) update((st) => void st.targets.push(lang))
        }}
      />
      <Field label="Translator">
        <SegmentedControl
          size="sm"
          block
          value={t.engine}
          onValueChange={(v) => update((st) => void (st.translation.engine = v))}
          segments={[
            { value: 'llm', label: 'LLM' },
            { value: 'nllb', label: 'NLLB-200 (offline)' },
          ]}
        />
      </Field>
      <Field label={t.engine === 'llm' ? 'Chat model' : 'Model for LLM passes (optional)'} hint={t.engine === 'llm' ? 'Any chat provider: Ollama, LM Studio, OpenRouter, an OpenAI-compatible endpoint…' : undefined}>
        {(id) => (
          <Select
            id={id}
            size="sm"
            value={t.model}
            onValueChange={(v) => update((st) => void (st.translation.model = v))}
            options={chatModels.map((m) => ({ value: m.id, label: m.name, description: m.provider }))}
            placeholder="Choose a model"
          />
        )}
      </Field>
      {t.engine === 'nllb' && (
        <Field label="NLLB model" hint="Meta NLLB-200 weights are CC-BY-NC 4.0 (non-commercial). Downloaded on first use.">
          {(id) => (
            <Select
              id={id}
              size="sm"
              value={t.nllb_repo}
              onValueChange={(v) => update((st) => void (st.translation.nllb_repo = v))}
              options={(status?.nllb ?? []).map((m) => ({
                value: m.repo,
                label: m.name,
                description: `${m.size_gb} GB${m.cached ? ' · downloaded' : ''}`,
              }))}
            />
          )}
        </Field>
      )}
      <Field label="Quality">
        <ChipGroup
          value={t.quality}
          onValueChange={(v) => update((st) => void (st.translation.quality = v))}
          chips={[
            { value: 'fast', label: 'Fast' },
            { value: 'cinematic', label: 'Cinematic' },
            { value: 'autofit', label: 'Autofit' },
            { value: 'agent', label: 'Agent' },
          ]}
        />
      </Field>
      <p className={s.hint}>
        {{
          fast: 'Direct translation.',
          cinematic: 'Critique → adapt pass for natural, in-character lines.',
          autofit: 'Rewrites lines so their reading time fits the slot.',
          agent: 'Renders, measures real durations, rewrites misses and re-renders (≤2 passes).',
        }[t.quality]}
      </p>
      {t.engine === 'llm' && (
        <>
          <Switch label="Auto-glossary" description="One pass over the transcript for names and recurring terms" checked={t.auto_glossary} onCheckedChange={(v) => update((st) => void (st.translation.auto_glossary = v))} />
          <Switch label="Reflect pass" description="Critique, then polish each line into natural speech" checked={t.reflect} onCheckedChange={(v) => update((st) => void (st.translation.reflect = v))} />
        </>
      )}
      <Switch label="Suggest condensed lines" description="For lines that cannot fit their slot" checked={t.condense} onCheckedChange={(v) => update((st) => void (st.translation.condense = v))} />
      <Field label="Style brief" hint="Tone and wording only (≤5000 chars)">
        {(id) => (
          <Textarea
            id={id}
            autoResize
            minRows={2}
            maxRows={8}
            maxLength={5000}
            value={brief}
            placeholder="e.g. casual, playful, keep brand names in English"
            onChange={(e) => setBrief(e.target.value)}
            onBlur={() => brief !== t.instructions && update((st) => void (st.translation.instructions = brief))}
          />
        )}
      </Field>
    </SidebarSection>
  )
}

/* ------------------------------------------------------------------ cast */

export function CastSection({ project, busy }: { project: DubProject; busy: boolean }) {
  const patch = usePatchDubProject(project.id)
  const { data: profiles = [] } = useVoiceProfiles()
  const ttsId = project.settings.tts.model_id
  const usable = profiles.filter((p) => p.kind !== 'preset' || p.model_id === ttsId)
  const speakerIds = project.speakers.map((sp) => sp.id)
  const [over, setOver] = useState<string | null>(null)
  const [picking, setPicking] = useState<string | null>(null)
  const options = [
    { label: 'From the video', options: [{ value: 'auto', label: 'Auto · clone this speaker' }] },
    { label: 'Engine', options: [{ value: '', label: 'Default voice' }] },
    ...(usable.length ? [{ label: 'Your voices', options: usable.map((p) => ({ value: p.id, label: p.name, description: p.kind })) }] : []),
  ]
  const assign = (speaker: string, voice: string) => patch.mutate({ speakers: [{ id: speaker, voice }] })
  const drop = (e: DragEvent, speaker: string) => {
    e.preventDefault()
    setOver(null)
    const voice = e.dataTransfer.getData('text/plain')
    if (voice !== undefined) assign(speaker, voice)
  }
  return (
    <SidebarSection title="Cast" icon={<Users />} aside={project.speakers.length || undefined} defaultOpen={false}>
      <div className={s.chips}>
        {[{ id: 'auto', name: 'Auto clone' }, { id: '', name: 'Default' }, ...usable.map((p) => ({ id: p.id, name: p.name }))].map((v) => (
          <span key={v.id || 'default'} className={s.voiceChip} draggable onDragStart={(e) => e.dataTransfer.setData('text/plain', v.id)}>
            {v.id === 'auto' && <Sparkles size={11} />}
            {v.name}
          </span>
        ))}
      </div>
      <p className={s.hint}>Drag a voice onto a speaker, or pick one. Auto clones each speaker from the source audio.</p>
      {project.speakers.map((sp) => (
        <div
          key={sp.id}
          className={s.speaker}
          data-over={over === sp.id || undefined}
          style={{ ['--c' as string]: speakerColor(speakerIds, sp.id) }}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(sp.id)
          }}
          onDragLeave={() => setOver(null)}
          onDrop={(e) => drop(e, sp.id)}
        >
          <div className={s.speakerHead}>
            <span className={s.speakerDot} />
            <strong>{sp.id}</strong>
            {sp.ref_duration != null && (
              <Tooltip content={sp.ref_pinned ? 'The sample you picked' : sp.ref_kind === 'speaker' ? 'Pooled clone reference' : 'Longest line of this speaker'}>
                <Badge size="sm" tone={sp.ref_pinned ? 'accent' : 'neutral'}>
                  {sp.ref_duration.toFixed(1)}s {sp.ref_pinned ? 'picked' : 'ref'}
                </Badge>
              </Tooltip>
            )}
          </div>
          <Select size="sm" disabled={busy} value={sp.voice} onValueChange={(v) => assign(sp.id, v)} options={options} />
          {sp.voice === 'auto' && (
            <>
              {sp.ref_url && <AudioPlayer src={sp.ref_url} compact height={26} color="var(--c)" />}
              {sp.ref_text && <p className={s.refText}>“{sp.ref_text}”</p>}
              <Button size="sm" variant="secondary" iconLeft={<AudioLines />} disabled={busy} onClick={() => setPicking(sp.id)}>
                Choose sample…
              </Button>
            </>
          )}
        </div>
      ))}
      {picking && project.speakers.some((sp) => sp.id === picking) && (
        <VoiceSampleDialog
          project={project}
          speaker={project.speakers.find((sp) => sp.id === picking)!}
          color={speakerColor(speakerIds, picking)}
          onClose={() => setPicking(null)}
        />
      )}
    </SidebarSection>
  )
}

/* ------------------------------------------------------------------ timing */

export function TimingSection({ project }: { project: DubProject }) {
  const update = useSettings(project)
  const st = project.settings
  const hint = TIMING.find((x) => x.value === st.timing)?.hint
  const video = project.source.input_type === 'video'
  return (
    <SidebarSection title="Timing" icon={<Gauge />} defaultOpen={false}>
      <ChipGroup
        value={st.timing}
        onValueChange={(v) => update((x) => void (x.timing = v))}
        chips={TIMING.filter((x) => video || x.value !== 'stretch_video').map((x) => ({ value: x.value, label: x.label }))}
      />
      <p className={s.hint}>{hint}</p>
      {st.timing === 'smart_fit' && (
        <>
          <Field label="Audio-only speed-up" aside={`${st.fit.max_audio_only_rate.toFixed(2)}×`}>
            <Slider min={1} max={1.5} step={0.05} value={st.fit.max_audio_only_rate} onValueChange={(v) => update((x) => void (x.fit.max_audio_only_rate = v))} />
          </Field>
          <Field label="Audio cap" aside={`${st.fit.audio_rate_cap.toFixed(2)}×`}>
            <Slider min={1} max={2} step={0.05} value={st.fit.audio_rate_cap} onValueChange={(v) => update((x) => void (x.fit.audio_rate_cap = v))} />
          </Field>
          {video && (
            <>
              <Field label="Video slow-down cap" aside={`${st.fit.video_slow_cap.toFixed(2)}×`}>
                <Slider min={1} max={3} step={0.1} value={st.fit.video_slow_cap} onValueChange={(v) => update((x) => void (x.fit.video_slow_cap = v))} />
              </Field>
              <Switch label="Allow video retime" checked={st.fit.allow_video_retime} onCheckedChange={(v) => update((x) => void (x.fit.allow_video_retime = v))} />
            </>
          )}
        </>
      )}
      <Field label="Voice match">
        <SegmentedControl
          size="sm"
          block
          value={st.voice_match}
          onValueChange={(v) => update((x) => void (x.voice_match = v))}
          segments={[
            { value: 'per_line', label: 'Per line' },
            { value: 'consistent', label: 'Consistent' },
          ]}
        />
      </Field>
      <p className={s.hint}>
        {st.voice_match === 'per_line'
          ? 'Each line clones its own source clip — best prosody.'
          : 'One reference per speaker — the most stable voice identity.'}
      </p>
    </SidebarSection>
  )
}

/* ------------------------------------------------------------------ production */

export function ProductionSection({ project }: { project: DubProject }) {
  const update = useSettings(project)
  const voiceModels = useModelsOfKind('voice').filter((m) => m.runtime === 'omnivoice' || m.runtime === 'chatterbox')
  const tts = project.settings.tts
  const [style, setStyle] = useState(tts.instruct)
  const model = voiceModels.find((m) => m.id === tts.model_id)
  return (
    <SidebarSection title="Production" icon={<SlidersHorizontal />} defaultOpen={false}>
      <Field label="Speech model">
        {(id) => (
          <Select
            id={id}
            size="sm"
            value={tts.model_id}
            onValueChange={(v) => update((x) => void (x.tts.model_id = v))}
            options={voiceModels.map((m) => ({
              value: m.id,
              label: m.name,
              description: m.runtime === 'chatterbox' ? 'English only' : '646 languages · weights CC-BY-NC',
            }))}
            placeholder="Install OmniVoice"
          />
        )}
      </Field>
      {!voiceModels.length && (
        <p className={s.warn}>
          <AlertTriangle size={12} /> No cloning speech model installed — install OmniVoice from Models.
        </p>
      )}
      {model?.runtime === 'omnivoice' && (
        <>
          <Field label="Steps" aside={tts.num_step}>
            <Slider min={8} max={64} step={4} value={tts.num_step} onValueChange={(v) => update((x) => void (x.tts.num_step = v))} />
          </Field>
          <Field label="Guidance" aside={tts.guidance.toFixed(1)}>
            <Slider min={0} max={4} step={0.1} value={tts.guidance} onValueChange={(v) => update((x) => void (x.tts.guidance = v))} />
          </Field>
        </>
      )}
      <Field label="Speed" aside={`${tts.speed.toFixed(2)}×`}>
        <Slider min={0.5} max={2} step={0.05} value={tts.speed} onValueChange={(v) => update((x) => void (x.tts.speed = v))} />
      </Field>
      {model?.runtime === 'omnivoice' && (
        <Field label="Style" hint="Voice-design tags, e.g. whisper">
          {(id) => (
            <Input id={id} size="sm" value={style} onChange={(e) => setStyle(e.target.value)} onBlur={() => style !== tts.instruct && update((x) => void (x.tts.instruct = style))} />
          )}
        </Field>
      )}
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          setStyle('')
          update((x) => {
            x.tts.num_step = 16
            x.tts.guidance = 2
            x.tts.speed = 1
            x.tts.instruct = ''
          })
        }}
      >
        Reset
      </Button>
    </SidebarSection>
  )
}
