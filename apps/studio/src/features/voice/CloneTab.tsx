import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ArrowRight, AudioLines, RefreshCw, Save, Sparkles } from 'lucide-react'
import { AudioPlayer, Button, Card, EmptyState, Field, Input, Progress, Textarea } from '@studio/ui'
import { AUTO_VOICE, type StagedReference } from '../../api/contracts/voice'
import { useCreateProfile, useOnJobDone, useRetranscribe, useSpeak } from '../../api/voice'
import { SectionFallback } from '../../components/AreaLayout'
import { StudioLayout } from '../../components/Page'
import { AUTO_LANGUAGE, LanguagePicker } from './LanguagePicker'
import { ReferenceInput } from './ReferenceInput'
import { useOmniVoice } from './useOmniVoice'
import s from './CloneTab.module.css'

const TRY_TEXT = 'Hello! This is my cloned voice. It can read anything you type, in hundreds of languages.'

export function CloneTab() {
  const omni = useOmniVoice()
  const [staged, setStaged] = useState<StagedReference | null>(null)
  const [transcript, setTranscript] = useState('')
  const [name, setName] = useState('')
  const [voiceLanguage, setVoiceLanguage] = useState(AUTO_LANGUAGE)
  const [style, setStyle] = useState('')
  const [tryText, setTryText] = useState(TRY_TEXT)
  const [tryLanguage, setTryLanguage] = useState('en')
  const [jobId, setJobId] = useState<string>()
  const [previewUrl, setPreviewUrl] = useState<string>()
  const retranscribe = useRetranscribe()
  const speak = useSpeak()
  const create = useCreateProfile()
  const navigate = useNavigate()
  const job = useOnJobDone(jobId, (j) => setPreviewUrl(j.result?.outputs[0]?.url))
  const running = job?.status === 'queued' || job?.status === 'running'

  const onStaged = (ref: StagedReference) => {
    setStaged(ref)
    setTranscript(ref.text)
    setPreviewUrl(undefined)
    if (ref.language) setVoiceLanguage(ref.language)
  }

  if (omni === undefined) return <SectionFallback />
  if (!omni) {
    return (
      <EmptyState
        className={s.missing}
        tint="var(--hue-voice)"
        icon={<AudioLines />}
        title="Cloning uses OmniVoice"
        description="Install OmniVoice (646 languages, zero-shot cloning) to clone a voice from a short clip."
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

  const ready = !!staged && transcript.trim().length > 0

  const preview = () =>
    staged &&
    speak.mutate(
      {
        model_id: omni.id,
        text: tryText.trim(),
        voice_id: AUTO_VOICE,
        speed: 1,
        ref_id: staged.id,
        ref_text: transcript.trim(),
        language: tryLanguage,
        instruct: style.trim() || undefined,
      },
      { onSuccess: (j) => setJobId(j.id) },
    )

  const save = () =>
    staged &&
    create.mutate(
      {
        kind: 'clone',
        name: name.trim(),
        ref_id: staged.id,
        ref_text: transcript.trim(),
        language: voiceLanguage === AUTO_LANGUAGE ? undefined : voiceLanguage,
        instruct: style.trim() || undefined,
      },
      { onSuccess: (p) => navigate(`/voice/speak?voice=${encodeURIComponent(p.id)}`) },
    )

  const controls = (
    <div className={s.controls}>
      <Field label="Reference clip" hint="Zero-shot: no training. One speaker, little background noise.">
        <ReferenceInput staged={staged} onStaged={onStaged} />
      </Field>
      {staged && (
        <Field
          label="Transcript"
          hint={staged.note ?? 'Must match the clip word for word — fix any mistakes.'}
          aside={
            <Button
              size="sm"
              variant="ghost"
              iconLeft={<RefreshCw />}
              loading={retranscribe.isPending}
              onClick={() => retranscribe.mutate(staged.id, { onSuccess: onStaged })}
            >
              Transcribe again
            </Button>
          }
        >
          {(id) => <Textarea id={id} autoResize minRows={3} maxRows={8} value={transcript} onChange={(e) => setTranscript(e.target.value)} />}
        </Field>
      )}
    </div>
  )

  return (
    <StudioLayout controls={controls} hue="var(--hue-voice)">
      <div className={s.canvas}>
        <Card padding="lg" className={s.card}>
          <h2 className={s.title}>Try the voice</h2>
          <p className={s.sub}>Speak any text with the clip — in its own language or any of the 646 others.</p>
          <Textarea autoResize minRows={3} maxRows={8} value={tryText} onChange={(e) => setTryText(e.target.value)} />
          <div className={s.row}>
            <div className={s.grow}>
              <LanguagePicker value={tryLanguage} onChange={setTryLanguage} engine="omnivoice" />
            </div>
            <Button variant="glow" iconLeft={<Sparkles />} disabled={!ready || !tryText.trim()} loading={speak.isPending || running} onClick={preview}>
              Preview
            </Button>
          </div>
          {running && <Progress value={job.progress} size="xs" />}
          {previewUrl && <AudioPlayer key={previewUrl} src={previewUrl} color="var(--hue-voice)" autoPlay />}
        </Card>

        <Card padding="lg" className={s.card}>
          <h2 className={s.title}>Save to your voices</h2>
          <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Grandpa — storyteller" />}</Field>
          <div className={s.pair}>
            <Field label="Voice language" hint="Used when a request doesn't pick one.">
              {(id) => <LanguagePicker id={id} value={voiceLanguage} onChange={setVoiceLanguage} engine="omnivoice" />}
            </Field>
            <Field label="Style (optional)" hint="Design tags applied on top, e.g. “whisper”.">
              {(id) => <Input id={id} value={style} onChange={(e) => setStyle(e.target.value)} placeholder="whisper, low pitch" />}
            </Field>
          </div>
          <div className={s.actions}>
            <Button variant="primary" iconLeft={<Save />} disabled={!ready || !name.trim()} loading={create.isPending} onClick={save}>
              Save voice
            </Button>
          </div>
        </Card>
      </div>
    </StudioLayout>
  )
}
