import { useRef, useState } from 'react'
import { Circle, Repeat2, Square, Upload } from 'lucide-react'
import { AudioPlayer, Badge, Button, Field, LiveWaveform, Progress, Select, Switch, cn } from '@studio/ui'
import { useModelsOfKind, useOutputs } from '../../api/hooks'
import { useJob } from '../../api/live'
import { useLanguageName, useVoiceProfiles } from '../../api/voice'
import { timeAgo } from '../../lib/format'
import { AUTO_LANGUAGE, LanguagePicker } from '../voice/LanguagePicker'
import { useRecorder } from '../voice/useRecorder'
import { RuntimeGate } from '../dub/RuntimeGate'
import { useConvertVoice } from './api'
import s from './Tools.module.css'

/** Voice → Tools → Convert: say it again in another voice (transcribe → speak with the profile, length-matched). */
export function ConvertTab() {
  const convert = useConvertVoice()
  const languageName = useLanguageName()
  const { data: profiles = [] } = useVoiceProfiles()
  const stt = useModelsOfKind('stt').filter((m) => m.runtime === 'faster-whisper')
  const tts = useModelsOfKind('voice').filter((m) => m.runtime === 'omnivoice' || m.runtime === 'chatterbox')
  const [voice, setVoice] = useState<string>()
  const [ttsModel, setTtsModel] = useState<string>()
  const [sttModel, setSttModel] = useState<string>()
  const [lang, setLang] = useState(AUTO_LANGUAGE)
  const [match, setMatch] = useState(true)
  const [source, setSource] = useState<Blob | null>(null)
  const rec = useRecorder(setSource)
  const [jobId, setJobId] = useState<string>()
  const job = useJob(jobId)
  const fileInput = useRef<HTMLInputElement>(null)
  const { data: outputs = [] } = useOutputs('audio')
  const history = outputs.filter((o) => o.params.tool === 'convert')
  const ttsId = ttsModel ?? tts.find((m) => m.runtime === 'omnivoice')?.id ?? tts[0]?.id
  const sttId = sttModel ?? stt[0]?.id
  const usable = profiles.filter((p) => p.kind !== 'preset' || p.model_id === ttsId)
  const running = job && (job.status === 'running' || job.status === 'queued')

  return (
    <div className={s.page} style={{ ['--hue' as string]: 'var(--hue-voice)' }}>
      <header className={s.header}>
        <span className={s.headerIcon}>
          <Repeat2 />
        </span>
        <div>
          <h1>Convert voice</h1>
          <p>Transcribes the recording, then speaks the same words in another voice — matched to the original length.</p>
        </div>
      </header>
      <RuntimeGate needsEnv={false} />
      <div className={s.form}>
        <Field label="Target voice">
          {(id) => <Select id={id} value={voice} onValueChange={setVoice} placeholder="Choose a voice" options={usable.map((p) => ({ value: p.id, label: p.name, description: p.kind }))} />}
        </Field>
        <Field label="Speech model">
          {(id) => <Select id={id} value={ttsId} onValueChange={setTtsModel} options={tts.map((m) => ({ value: m.id, label: m.name }))} placeholder="Install OmniVoice" />}
        </Field>
        <Field label="Recognition">
          {(id) => <Select id={id} value={sttId} onValueChange={setSttModel} options={stt.map((m) => ({ value: m.id, label: m.name }))} placeholder="Install Whisper" />}
        </Field>
        <Field label="Language">{(id) => <LanguagePicker id={id} value={lang} onChange={setLang} />}</Field>
      </div>
      <Switch label="Match the source length" description="One pitch-preserving tempo pass toward the original duration (skipped within ±2 %)" checked={match} onCheckedChange={setMatch} />
      <div className={cn(s.drop, rec.recording && s.dragging)}>
        {rec.recording ? (
          <>
            <LiveWaveform stream={rec.stream} height={56} />
            <Button variant="danger" iconLeft={<Square fill="currentColor" />} onClick={rec.stop}>
              Stop ({rec.elapsed.toFixed(1)}s)
            </Button>
          </>
        ) : (
          <div className={s.sourceRow}>
            <Button variant="secondary" iconLeft={<Upload />} onClick={() => fileInput.current?.click()}>
              Choose file
            </Button>
            <Button variant="secondary" iconLeft={<Circle fill="var(--danger)" color="var(--danger)" />} onClick={() => void rec.start()}>
              Record
            </Button>
            {source && <Badge size="sm">{source instanceof File ? source.name : `Recording · ${(source.size / 1024).toFixed(0)} KB`}</Badge>}
          </div>
        )}
        <input ref={fileInput} type="file" hidden accept="audio/*,video/*" onChange={(e) => e.target.files?.[0] && setSource(e.target.files[0])} />
      </div>
      {rec.error && <p className={s.error}>{rec.error}</p>}
      {running ? (
        <div className={s.progress}>
          <span>{job.message ?? 'Queued'}</span>
          <Progress value={job.progress} size="sm" />
        </div>
      ) : (
        <Button
          variant="glow"
          disabled={!source || !voice || !sttId}
          loading={convert.isPending}
          onClick={() =>
            source &&
            voice &&
            sttId &&
            convert.mutate(
              { file: source, voiceId: voice, sttModelId: sttId, ttsModelId: ttsId, language: lang === AUTO_LANGUAGE ? undefined : lang, matchDuration: match },
              { onSuccess: (j) => setJobId(j.id) },
            )
          }
        >
          Convert
        </Button>
      )}
      {history.map((o) => (
        <section key={o.id} className={s.result}>
          <div className={s.resultHead}>
            <strong>{String(o.params.voice ?? '')}</strong>
            {typeof o.params.language === 'string' && <Badge size="sm">{languageName(o.params.language)}</Badge>}
            <span className={s.hint}>
              from {String(o.params.source)} · {timeAgo(o.created_at)}
            </span>
          </div>
          <p className={s.transcript}>{o.prompt}</p>
          <AudioPlayer src={o.url} color="var(--hue-voice)" downloadName={`converted-${o.id}.wav`} />
        </section>
      ))}
    </div>
  )
}
