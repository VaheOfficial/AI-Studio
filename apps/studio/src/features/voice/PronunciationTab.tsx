import { useState } from 'react'
import { BookA, FlaskConical, Plus, Trash2, Volume2 } from 'lucide-react'
import { AudioPlayer, Badge, Button, Card, EmptyState, Field, IconButton, Input, Skeleton, Switch, Textarea } from '@studio/ui'
import { AUTO_VOICE, type PronunciationEntry } from '../../api/contracts/voice'
import { useModelsOfKind } from '../../api/hooks'
import {
  useCreatePronunciation,
  useDeletePronunciation,
  useOnJobDone,
  usePronunciation,
  useSpeak,
  useTestPronunciation,
  useUpdatePronunciation,
} from '../../api/voice'
import { LanguagePicker } from './LanguagePicker'
import { PageHeader } from '../../components/Page'
import s from './PronunciationTab.module.css'

const EVERY = { value: '*', label: 'All languages', group: 'Scope' }

/** Pronunciation dictionary (respellings, global or per language) and a test box. */
export function PronunciationTab() {
  const { data: entries, isLoading } = usePronunciation()
  const create = useCreatePronunciation()
  const [term, setTerm] = useState('')
  const [replacement, setReplacement] = useState('')
  const [language, setLanguage] = useState('*')

  const add = () =>
    create.mutate(
      { term: term.trim(), replacement: replacement.trim(), language, enabled: true },
      {
        onSuccess: () => {
          setTerm('')
          setReplacement('')
        },
      },
    )

  return (
    <div className={s.page}>
      <PageHeader
        hue="var(--hue-voice)"
        icon={<BookA />}
        title="Pronunciation"
        subtitle={
          <>
            Respell words the voice gets wrong. Entries match whole words, case-insensitively, longest first, in every speech request. For
            a one-off, write <code>[[GIF|jiff]]</code> in the script.
          </>
        }
      />

      <Card padding="md" className={s.addRow}>
        <Input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Word or phrase, e.g. GIF" />
        <Input value={replacement} onChange={(e) => setReplacement(e.target.value)} placeholder="Say it as, e.g. jiff" onKeyDown={(e) => e.key === 'Enter' && term.trim() && add()} />
        <LanguagePicker value={language} onChange={setLanguage} allowAuto={false} extra={EVERY} />
        <Button variant="primary" iconLeft={<Plus />} disabled={!term.trim()} loading={create.isPending} onClick={add}>
          Add
        </Button>
      </Card>

      {isLoading ? (
        <Skeleton height={120} radius={12} />
      ) : !entries?.length ? (
        <EmptyState tint="var(--hue-voice)" icon={<BookA />} title="No entries yet" description="Add a word above; it applies to every engine." />
      ) : (
        <div className={s.table} role="table">
          <div className={s.headRow} role="row">
            <span>Word</span>
            <span>Say it as</span>
            <span>Language</span>
            <span>On</span>
            <span />
          </div>
          {entries.map((e) => (
            <EntryRow key={e.id} entry={e} />
          ))}
        </div>
      )}

      <TestBox />
    </div>
  )
}

function EntryRow({ entry }: { entry: PronunciationEntry }) {
  const update = useUpdatePronunciation()
  const del = useDeletePronunciation()
  const [term, setTerm] = useState(entry.term)
  const [replacement, setReplacement] = useState(entry.replacement)
  const commit = () => {
    if (term.trim() && (term !== entry.term || replacement !== entry.replacement)) update.mutate({ id: entry.id, term: term.trim(), replacement })
  }
  return (
    <div className={s.row} role="row">
      <Input size="sm" value={term} onChange={(e) => setTerm(e.target.value)} onBlur={commit} aria-label="Word" />
      <Input size="sm" value={replacement} onChange={(e) => setReplacement(e.target.value)} onBlur={commit} aria-label="Say it as" />
      <LanguagePicker size="sm" value={entry.language} onChange={(v) => update.mutate({ id: entry.id, language: v })} allowAuto={false} extra={EVERY} />
      <Switch checked={entry.enabled} onCheckedChange={(v) => update.mutate({ id: entry.id, enabled: v })} />
      <IconButton size="sm" variant="danger" label="Delete entry" icon={<Trash2 />} onClick={() => del.mutate(entry.id)} />
    </div>
  )
}

function TestBox() {
  const omni = useModelsOfKind('voice').find((m) => m.runtime === 'omnivoice')
  const test = useTestPronunciation()
  const speak = useSpeak()
  const [text, setText] = useState('Dr. Smith sent 3 GIF files at 10:30.')
  const [language, setLanguage] = useState('en')
  const [jobId, setJobId] = useState<string>()
  const [url, setUrl] = useState<string>()
  const job = useOnJobDone(jobId, (j) => setUrl(j.result?.outputs[0]?.url))
  const running = job?.status === 'queued' || job?.status === 'running'

  return (
    <Card padding="lg" className={s.test}>
      <h2 className={s.testTitle}>Test a sentence</h2>
      <Textarea autoResize minRows={2} maxRows={6} value={text} onChange={(e) => setText(e.target.value)} />
      <div className={s.testBar}>
        <div className={s.lang}>
          <LanguagePicker value={language} onChange={setLanguage} />
        </div>
        <Button iconLeft={<FlaskConical />} disabled={!text.trim()} loading={test.isPending} onClick={() => test.mutate({ text, language })}>
          Show what's spoken
        </Button>
        {omni && (
          <Button
            variant="glow"
            iconLeft={<Volume2 />}
            disabled={!text.trim()}
            loading={speak.isPending || running}
            onClick={() =>
              speak.mutate({ model_id: omni.id, text, voice_id: AUTO_VOICE, speed: 1, language }, { onSuccess: (j) => setJobId(j.id) })
            }
          >
            Listen
          </Button>
        )}
      </div>
      {test.data && (
        <Field label="The engine receives">
          <div className={s.result}>
            <p className={s.spoken}>{test.data.spoken}</p>
            <div className={s.hits}>
              {test.data.hits.length ? (
                test.data.hits.map((h) => (
                  <Badge key={h.term} size="sm" tone="accent">
                    {h.term} → {h.replacement}
                  </Badge>
                ))
              ) : (
                <span className={s.none}>No dictionary entry matched.</span>
              )}
            </div>
          </div>
        </Field>
      )}
      {url && <AudioPlayer key={url} src={url} color="var(--hue-voice)" autoPlay />}
    </Card>
  )
}
