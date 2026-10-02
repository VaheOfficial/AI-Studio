import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ArrowRight, AudioLines, RotateCcw, Save, Sparkles, WandSparkles } from 'lucide-react'
import { AudioPlayer, Badge, Button, Card, ChipGroup, EmptyState, Field, Input, Progress, SeedField, Skeleton, Textarea, cn, toast } from '@studio/ui'
import { AUTO_VOICE, type Archetype } from '../../api/contracts/voice'
import { useArchetypes, useCreateProfile, useDescribeVoice, useDesignVocabulary, useOnJobDone, useSpeak } from '../../api/voice'
import { SectionFallback } from '../../components/AreaLayout'
import { StudioHead, StudioLayout } from '../../components/Page'
import { ArchetypeCard } from './ArchetypeCard'
import { AUTO, applyAttr, emptyAttrs, instructOf, type DesignAttrs } from './designState'
import { LanguagePicker } from './LanguagePicker'
import { TagMenu } from './TagMenu'
import { useOmniVoice } from './useOmniVoice'
import { VoiceOrb } from './VoiceOrb'
import s from './DesignTab.module.css'

const DEFAULT_SCRIPT = 'The clock tower struck thirteen, and for the first time in her life, she wondered if she had been counting wrong all along.'

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function DesignTab() {
  const omni = useOmniVoice()
  const { data: vocab } = useDesignVocabulary()
  const [attrs, setAttrs] = useState<DesignAttrs>({})
  const [description, setDescription] = useState('')
  const [seed, setSeed] = useState<number | null>(null)
  const [language, setLanguage] = useState('en')
  const [text, setText] = useState(DEFAULT_SCRIPT)
  const [name, setName] = useState('')
  const [jobId, setJobId] = useState<string>()
  const [take, setTake] = useState<{ id: string; url: string; instruct: string }>()
  const script = useRef<HTMLTextAreaElement>(null)
  const speak = useSpeak()
  const create = useCreateProfile()
  const navigate = useNavigate()
  const debounced = useDebounced(description, 350)
  const { mutate: describe, data: mapped } = useDescribeVoice()
  const job = useOnJobDone(jobId, (j) => {
    const out = j.result?.outputs[0]
    if (out) setTake({ id: out.id, url: out.url, instruct: String(out.params.instruct ?? '') })
  })
  const running = job?.status === 'queued' || job?.status === 'running'
  const { data: featured } = useArchetypes({ featured: true, language: 'en' })

  // A (debounced) description drives the pickers; picks made afterwards stay until it changes again
  useEffect(() => {
    if (debounced.trim()) describe(debounced, { onSuccess: (r) => setAttrs(r.attrs) })
  }, [debounced, describe])

  const current = useMemo(() => ({ ...emptyAttrs(vocab), ...attrs }), [vocab, attrs])
  const instruct = instructOf(vocab, current)

  if (omni === undefined) return <SectionFallback />
  if (!omni) {
    return (
      <EmptyState
        className={s.missing}
        tint="var(--hue-voice)"
        icon={<WandSparkles />}
        title="Voice design uses OmniVoice"
        description="Install OmniVoice to design voices from tags or a plain-language description."
        action={
          <Link to="/models?tab=catalog&kind=voice">
            <Button variant="primary" iconRight={<ArrowRight />}>
              Open the catalog
            </Button>
          </Link>
        }
      />
    )
  }

  const pick = (category: string, value: string) => {
    if (!vocab) return
    const [next, cleared] = applyAttr(vocab, current, category, value)
    setAttrs(next)
    if (cleared) toast.info(`${vocab.categories.find((c) => c.id === cleared)?.label} reset`, 'An English accent and a Chinese dialect cannot be combined.')
  }

  const startFrom = (a: Archetype) => {
    setAttrs(a.attrs)
    setText(a.sample_script)
    setLanguage(a.language)
    setDescription('')
  }

  const synthesize = () =>
    speak.mutate(
      { model_id: omni.id, text: text.trim(), voice_id: AUTO_VOICE, speed: 1, language, instruct, seed: seed ?? undefined },
      { onSuccess: (j) => setJobId(j.id) },
    )

  const save = () =>
    take &&
    create.mutate(
      { kind: 'design', name: name.trim(), take_id: take.id, vd_states: current },
      { onSuccess: (p) => navigate(`/voice/speak?voice=${encodeURIComponent(p.id)}`) },
    )

  const controls = (
    <div className={s.controls}>
      <StudioHead icon={<WandSparkles />} title="Design" subtitle="A new voice from a description" />
      <Field label="Describe the voice" hint="Plain language is mapped to tags live — e.g. “a gravelly old British man”.">
        {(id) => (
          <Textarea
            id={id}
            autoResize
            minRows={2}
            maxRows={6}
            maxLength={2000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="A warm, middle-aged woman with a soft British accent…"
          />
        )}
      </Field>
      {mapped && description.trim() && (
        <div className={s.mapping}>
          {mapped.matched.map((m) => (
            <Badge key={m.category} size="sm" tone="accent">
              “{m.phrase}” → {m.token}
            </Badge>
          ))}
          {mapped.unmatched.length > 0 && <span className={s.unmatched}>Ignored: {mapped.unmatched.join(', ')}</span>}
          {mapped.matched.length === 0 && <span className={s.unmatched}>No voice traits recognised yet.</span>}
        </div>
      )}
      {vocab ? (
        <>
          <Field label="Personality">
            <div className={s.personalities}>
              {vocab.personalities.map((p) => (
                <Button key={p.id} size="sm" variant="ghost" title={p.description} onClick={() => setAttrs(p.attrs)}>
                  {p.name}
                </Button>
              ))}
            </div>
          </Field>
          {vocab.categories.map((c) => (
            <Field key={c.id} label={c.label}>
              <ChipGroup
                aria-label={c.label}
                value={current[c.id] ?? AUTO}
                onValueChange={(v) => pick(c.id, v)}
                chips={[AUTO, ...c.options].map((o) => ({ value: o, label: o === AUTO ? 'Auto' : o, color: 'var(--hue-voice)' }))}
              />
            </Field>
          ))}
        </>
      ) : (
        <Skeleton height={240} radius={12} />
      )}
      <SeedField value={seed} onChange={setSeed} hint="Random on every take. Lock a seed to keep the same voice with the same tags." />
      <Field label="Language">{(id) => <LanguagePicker id={id} value={language} onChange={setLanguage} engine="omnivoice" />}</Field>
      <Button variant="ghost" size="sm" iconLeft={<RotateCcw />} onClick={() => setAttrs({})}>
        Reset all tags
      </Button>
    </div>
  )

  return (
    <StudioLayout controls={controls} hue="var(--hue-voice)">
      <div className={s.canvas}>
        <div className={s.identity}>
          <VoiceOrb seed={`${instruct}|${seed}`} size={44} active={running} />
          <div>
            <div className={s.identityName}>{instruct || 'Auto voice'}</div>
            <div className={s.identityMeta}>{seed === null ? 'random seed' : `seed ${seed}`}</div>
          </div>
        </div>

        <section className={s.section}>
          <h2 className={s.sectionTitle}>Starting points</h2>
          <div className={s.featured}>
            {featured
              ? featured.pages[0].items.slice(0, 6).map((a) => <ArchetypeCard key={a.id} archetype={a} onStart={startFrom} />)
              : Array.from({ length: 3 }, (_, i) => <Skeleton key={i} height={150} radius={12} />)}
          </div>
        </section>

        <div className={cn(s.editor, running && s.busy)}>
          <div className={s.editorHead}>
            <span>Test script</span>
            <TagMenu target={script} text={text} onChange={setText} />
          </div>
          <Textarea ref={script} autoResize minRows={4} maxRows={12} value={text} onChange={(e) => setText(e.target.value)} className={s.script} />
          <div className={s.editorFoot}>
            {running ? <Progress value={job.progress} size="xs" className={s.progress} /> : <span />}
            <Button variant="glow" iconLeft={<Sparkles />} disabled={!text.trim()} loading={speak.isPending || running} onClick={synthesize}>
              Synthesize
            </Button>
          </div>
        </div>

        {take ? (
          <Card padding="lg" className={s.result}>
            <AudioPlayer key={take.url} src={take.url} color="var(--hue-voice)" autoPlay />
            <div className={s.save}>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this voice…" />
              <Button variant="primary" iconLeft={<Save />} disabled={!name.trim()} loading={create.isPending} onClick={save}>
                Save as voice
              </Button>
            </div>
            <p className={s.note}>Saving keeps this exact take as the voice's reference, so it sounds the same in every script.</p>
          </Card>
        ) : (
          <EmptyState tint="var(--hue-voice)" icon={<AudioLines />} title="Nothing synthesized yet" description="Pick tags or describe a voice, then synthesize the test script." />
        )}
      </div>
    </StudioLayout>
  )
}
