import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { motion } from 'motion/react'
import {
  ArrowLeft,
  AudioLines,
  BookHeadphones,
  BookOpen,
  ChevronsLeft,
  ChevronsRight,
  Download,
  FileUp,
  Image as ImageIcon,
  Pause,
  Play,
  Plus,
  SlidersHorizontal,
  SpellCheck,
  Trash2,
  Type,
  Users,
  X,
} from 'lucide-react'
import {
  AudioPlayer,
  Badge,
  Button,
  Card,
  ChipGroup,
  ConfirmDialog,
  EmptyState,
  Field,
  IconButton,
  Input,
  Progress,
  SegmentedControl,
  Select,
  Skeleton,
  Slider,
  Textarea,
  SeedField,
} from '@studio/ui'
import type { AudiobookBitrate, AudiobookProject, AudiobookSettings } from '../../api/contracts/dub'
import { useCancelJob, useModelsOfKind } from '../../api/hooks'
import { useVoiceProfiles } from '../../api/voice'
import { StudioLayout } from '../../components/Page'
import { formatBytes, timeAgo } from '../../lib/format'
import { fmtDuration } from '../dub/format'
import { RuntimeGate } from '../dub/RuntimeGate'
import { SidebarSection } from '../dub/SidebarSection'
import { AUTO_LANGUAGE, LanguagePicker } from '../voice/LanguagePicker'
import {
  useAudiobook,
  useAudiobooks,
  useCreateAudiobook,
  useDeleteAudiobook,
  useDeleteRender,
  useImportManuscript,
  usePatchAudiobook,
  usePlan,
  useRenderAudiobook,
  useRenderJob,
  useUploadCover,
} from './api'
import s from './AudiobookPage.module.css'

const SAMPLE = `# Chapter One: The Lighthouse
[voice:Narrator] The storm had been building since noon. By the time the ferry reached the harbour, the lighthouse on the point was the only light for miles. [pause 700ms]
[voice:Mara] Is anyone still up there? [slow]Someone has to be.[/slow]

# Chapter Two: The Keeper
[voice:Narrator] The door at the top of the tower was open, and the lamp was turning on its own. [pause]
[voice:Mara] Hello? My name is Mara. I saw the light from the ferry.
[voice:Narrator] Nobody answered, but on the desk a kettle was still warm.`

const BITRATES: AudiobookBitrate[] = ['64k', '96k', '128k', '192k']

const TAGS = ['[laughter]', '[sigh]', '[confirmation-en]', '[question-en]', '[question-ah]', '[surprise-ah]', '[surprise-wa]', '[dissatisfaction-hnn]']

/** Voice → Audiobook: chaptered long-form narration with a cast, rendered to M4B (chapters + cover) or MP3. */
export default function AudiobookPage() {
  const [params, setParams] = useSearchParams()
  const id = params.get('book')
  const open = (bookId: string | null) => setParams(bookId ? { book: bookId } : {})
  return id ? <BookEditor id={id} onClose={() => open(null)} /> : <Library onOpen={open} />
}

function Library({ onOpen }: { onOpen: (id: string) => void }) {
  const { data: books, isLoading } = useAudiobooks()
  const create = useCreateAudiobook()
  const remove = useDeleteAudiobook()
  const importFile = useImportManuscript()
  const fileInput = useRef<HTMLInputElement>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  return (
    <div className={s.library}>
      <header className={s.header}>
        <span className={s.headerIcon}>
          <BookHeadphones />
        </span>
        <div className={s.headerText}>
          <h1>Audiobooks</h1>
          <p>Chapters, a cast of voices, loudness mastering — out comes an M4B with chapter marks.</p>
        </div>
        <Button variant="secondary" iconLeft={<FileUp />} loading={importFile.isPending} onClick={() => fileInput.current?.click()}>
          Import TXT / MD / EPUB / PDF
        </Button>
        <Button variant="glow" iconLeft={<Plus />} loading={create.isPending} onClick={() => create.mutate({ name: 'Untitled audiobook', script: '' }, { onSuccess: (p) => onOpen(p.id) })}>
          New audiobook
        </Button>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept=".txt,.md,.markdown,.epub,.pdf"
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (!f) return
            importFile.mutate(f, {
              onSuccess: (res) => create.mutate({ name: res.title ?? f.name, script: res.script }, { onSuccess: (p) => onOpen(p.id) }),
            })
          }}
        />
      </header>
      <RuntimeGate needsEnv={false} />
      {isLoading ? (
        <div className={s.grid}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height={96} radius={14} />
          ))}
        </div>
      ) : !books?.length ? (
        <EmptyState tint="var(--hue-voice)" icon={<BookOpen />} title="No audiobooks yet" description="Start from scratch or import a manuscript." />
      ) : (
        <div className={s.grid}>
          {books.map((b, i) => (
            <motion.div key={b.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }}>
              <Card padding="md" interactive className={s.bookCard} onClick={() => onOpen(b.id)}>
                <BookOpen className={s.bookIcon} />
                <div className={s.bookText}>
                  <strong>{b.name}</strong>
                  <span>
                    {b.chapters} chapter{b.chapters === 1 ? '' : 's'} · {b.renders} render{b.renders === 1 ? '' : 's'} · {timeAgo(b.updated_at)}
                  </span>
                </div>
                <IconButton
                  size="sm"
                  label="Delete audiobook"
                  icon={<Trash2 />}
                  onClick={(e) => {
                    e.stopPropagation()
                    setConfirm(b.id)
                  }}
                />
              </Card>
            </motion.div>
          ))}
        </div>
      )}
      <ConfirmDialog
        open={confirm != null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title="Delete this audiobook?"
        description="The script, rendered chapters and exported files are removed."
        confirmLabel="Delete"
        tone="danger"
        onConfirm={() => {
          if (confirm) remove.mutate(confirm)
          setConfirm(null)
        }}
      />
    </div>
  )
}

function BookEditor({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: book } = useAudiobook(id)
  if (!book) {
    return (
      <div className={s.loading}>
        <Skeleton height={320} radius={14} />
      </div>
    )
  }
  return <Editor book={book} onClose={onClose} />
}

function Editor({ book, onClose }: { book: AudiobookProject; onClose: () => void }) {
  const patch = usePatchAudiobook(book.id)
  const render = useRenderAudiobook(book.id)
  const cancel = useCancelJob()
  const job = useRenderJob(book.id)
  const [script, setScript] = useState(book.script)
  const { data: plan } = usePlan(script)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const st = book.settings
  const update = (fn: (x: AudiobookSettings) => void) => {
    const next = structuredClone(st)
    fn(next)
    patch.mutate({ settings: next })
  }

  // Save the script shortly after typing stops.
  const { mutate } = patch
  useEffect(() => {
    if (script === book.script) return
    const t = setTimeout(() => mutate({ script }), 800)
    return () => clearTimeout(t)
  }, [script, book.script, mutate])

  const edit = (snippet: string, wrapClose?: string) => {
    const el = textarea.current
    if (!el) return
    const start = el.selectionStart
    const end = el.selectionEnd
    const selected = el.value.slice(start, end)
    const text = wrapClose ? `${snippet}${selected}${wrapClose}` : snippet
    const next = el.value.slice(0, start) + text + el.value.slice(end)
    setScript(next)
    requestAnimationFrame(() => {
      el.focus()
      const caret = wrapClose && !selected ? start + snippet.length : start + text.length
      el.setSelectionRange(caret, caret)
    })
  }

  return (
    <StudioLayout
      hue="var(--hue-voice)"
      controls={
        <>
          <BookSection book={book} onClose={onClose} update={update} />
          <CastSection book={book} voices={plan?.voices ?? []} update={update} />
          <ChaptersSection book={book} titles={plan?.chapters.map((c) => c.title) ?? []} busy={!!job} onPreview={(i) => render.mutate({ preview_chapter: i })} />
          <ProductionSection book={book} update={update} />
          <MasteringSection book={book} update={update} />
          <div className={s.generate}>
            {job ? (
              <>
                <span className={s.jobText}>{job.message ?? job.title}</span>
                <Progress value={job.progress} size="sm" />
                <Button variant="secondary" iconLeft={<Pause />} onClick={() => cancel.mutate(job.id)}>
                  Stop
                </Button>
              </>
            ) : (
              <Button variant="glow" block iconLeft={<AudioLines />} disabled={!plan?.chapters.length} loading={render.isPending} onClick={() => render.mutate({})}>
                Render {st.format.toUpperCase()}
              </Button>
            )}
            <p className={s.hint}>Finished lines are cached — a stopped or edited book resumes where it left off.</p>
          </div>
        </>
      }
    >
      <div className={s.canvas}>
        <div className={s.scriptHead}>
          <div>
            <h2>Script</h2>
            <p className={s.hint}>
              <code># Chapter</code> starts a chapter · <code>[voice:Name]</code> switches the narrator · <code>[pause 700ms]</code> ·{' '}
              <code>[slow]…[/slow]</code>
            </p>
          </div>
          {!script.trim() && (
            <Button size="sm" variant="secondary" onClick={() => setScript(SAMPLE)}>
              Load sample
            </Button>
          )}
          {script.trim() && (
            <Button size="sm" variant="ghost" iconLeft={<X />} onClick={() => setScript('')}>
              Clear
            </Button>
          )}
        </div>
        <div className={s.toolbar} role="toolbar" aria-label="Markup">
          <Button size="sm" variant="ghost" iconLeft={<Pause />} onClick={() => edit('[pause 500ms]')}>
            Pause
          </Button>
          <Button size="sm" variant="ghost" iconLeft={<Users />} onClick={() => edit('[voice:NAME]')}>
            Voice
          </Button>
          <Button size="sm" variant="ghost" iconLeft={<ChevronsLeft />} onClick={() => edit('[slow]', '[/slow]')}>
            Slow
          </Button>
          <Button size="sm" variant="ghost" iconLeft={<ChevronsRight />} onClick={() => edit('[fast]', '[/fast]')}>
            Fast
          </Button>
          <Button size="sm" variant="ghost" iconLeft={<Type />} onClick={() => edit('[emphasis]', '[/emphasis]')}>
            Emphasis
          </Button>
          <Button size="sm" variant="ghost" iconLeft={<SpellCheck />} onClick={() => edit('[spell]', '[/spell]')}>
            Spell
          </Button>
          <Select size="sm" className={s.tagSelect} placeholder="Non-verbal…" value={undefined} onValueChange={(t) => edit(t)} options={TAGS.map((t) => ({ value: t, label: t }))} />
        </div>
        <Textarea ref={textarea} className={s.script} mono value={script} onChange={(e) => setScript(e.target.value)} placeholder="Paste or write your manuscript…" />
        <div className={s.stats}>
          {plan ? `${plan.chapters.length} chapter${plan.chapters.length === 1 ? '' : 's'} · ${plan.words.toLocaleString()} words · ~${fmtDuration(plan.est_s)}` : ' '}
        </div>
        <Renders book={book} />
      </div>
    </StudioLayout>
  )
}

type Update = (fn: (x: AudiobookSettings) => void) => void

function useVoiceOptions(modelId: string | undefined) {
  const { data: profiles = [] } = useVoiceProfiles()
  return useMemo(
    () => [
      { label: 'Engine', options: [{ value: '', label: 'Default voice' }] },
      ...(profiles.length
        ? [{ label: 'Your voices', options: profiles.filter((p) => p.kind !== 'preset' || p.model_id === modelId).map((p) => ({ value: p.id, label: p.name })) }]
        : []),
    ],
    [profiles, modelId],
  )
}

function BookSection({ book, onClose, update }: { book: AudiobookProject; onClose: () => void; update: Update }) {
  const patch = usePatchAudiobook(book.id)
  const [name, setName] = useState(book.name)
  const st = book.settings
  const voiceOptions = useVoiceOptions(st.tts_model_id)
  return (
    <SidebarSection title="Book" icon={<BookOpen />}>
      <div className={s.titleRow}>
        <IconButton size="sm" label="All audiobooks" icon={<ArrowLeft />} onClick={onClose} />
        <Input size="sm" value={name} aria-label="Title" onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== book.name && patch.mutate({ name })} />
      </div>
      <Field label="Narrator voice" hint="Used for unmarked text">
        {(id) => <Select id={id} size="sm" value={st.default_voice} onValueChange={(v) => update((x) => void (x.default_voice = v))} options={voiceOptions} />}
      </Field>
      <Field label="Language">
        {(id) => (
          <LanguagePicker id={id} size="sm" value={st.language || AUTO_LANGUAGE} onChange={(v) => update((x) => void (x.language = v === AUTO_LANGUAGE ? '' : v))} />
        )}
      </Field>
      <Field label="Format">
        <SegmentedControl
          size="sm"
          block
          value={st.format}
          onValueChange={(v) => update((x) => void (x.format = v))}
          segments={[
            { value: 'm4b', label: 'M4B · chapters + cover' },
            { value: 'mp3', label: 'MP3' },
          ]}
        />
      </Field>
    </SidebarSection>
  )
}

function CastSection({ book, voices, update }: { book: AudiobookProject; voices: string[]; update: Update }) {
  const options = useVoiceOptions(book.settings.tts_model_id)
  return (
    <SidebarSection title="Cast" icon={<Users />} aside={voices.length || undefined}>
      {voices.length === 0 ? (
        <p className={s.hint}>
          Add <code>[voice:Name]</code> markers to the script to cast characters.
        </p>
      ) : (
        voices.map((v) => (
          <Field key={v} label={v}>
            {(id) => (
              <Select
                id={id}
                size="sm"
                value={book.settings.voice_map[v] ?? '__default'}
                onValueChange={(voice) =>
                  update((x) => {
                    if (voice === '__default') delete x.voice_map[v]
                    else x.voice_map[v] = voice
                  })
                }
                options={[{ label: 'Book', options: [{ value: '__default', label: 'Narrator voice' }] }, ...options]}
              />
            )}
          </Field>
        ))
      )}
    </SidebarSection>
  )
}

function ChaptersSection({ book, titles, busy, onPreview }: { book: AudiobookProject; titles: string[]; busy: boolean; onPreview: (i: number) => void }) {
  return (
    <SidebarSection title="Chapters" icon={<BookHeadphones />} aside={titles.length || undefined}>
      {titles.map((t, i) => {
        const preview = book.previews[String(i)]
        return (
          <div key={`${i}-${t}`} className={s.chapter}>
            <div className={s.chapterHead}>
              <span className={s.chapterIndex}>{i + 1}</span>
              <span className={s.chapterTitle}>{t}</span>
              <IconButton size="sm" label={`Preview ${t}`} icon={<Play />} disabled={busy} onClick={() => onPreview(i)} />
            </div>
            {preview && <AudioPlayer src={preview.url} compact height={26} color="var(--hue-voice)" />}
          </div>
        )
      })}
    </SidebarSection>
  )
}

function ProductionSection({ book, update }: { book: AudiobookProject; update: Update }) {
  const st = book.settings
  const models = useModelsOfKind('voice').filter((m) => m.runtime === 'omnivoice' || m.runtime === 'chatterbox')
  const omni = models.find((m) => m.id === st.tts_model_id)?.runtime !== 'chatterbox'
  return (
    <SidebarSection title="Production" icon={<SlidersHorizontal />} defaultOpen={false}>
      <Field label="Speech model">
        {(id) => (
          <Select
            id={id}
            size="sm"
            value={st.tts_model_id ?? models.find((m) => m.runtime === 'omnivoice')?.id}
            onValueChange={(v) => update((x) => void (x.tts_model_id = v))}
            options={models.map((m) => ({ value: m.id, label: m.name, description: m.runtime === 'chatterbox' ? 'English only' : '646 languages · weights CC-BY-NC' }))}
            placeholder="Install OmniVoice"
          />
        )}
      </Field>
      {omni && (
        <>
          <Field label="Steps" aside={st.num_step}>
            <Slider min={8} max={64} step={4} value={st.num_step} onValueChange={(v) => update((x) => void (x.num_step = v))} />
          </Field>
          <Field label="Guidance" aside={st.guidance.toFixed(1)}>
            <Slider min={0} max={4} step={0.1} value={st.guidance} onValueChange={(v) => update((x) => void (x.guidance = v))} />
          </Field>
        </>
      )}
      <Field label="Speed" aside={`${st.speed.toFixed(2)}×`}>
        <Slider min={0.5} max={2} step={0.05} value={st.speed} onValueChange={(v) => update((x) => void (x.speed = v))} />
      </Field>
      <SeedField
        value={st.seed ?? null}
        onChange={(v) => update((x) => void (x.seed = v ?? undefined))}
        hint="Random on every render. Lock one for reproducible takes (per-line seeds derive from it)."
      />
    </SidebarSection>
  )
}

function MasteringSection({ book, update }: { book: AudiobookProject; update: Update }) {
  const st = book.settings
  const cover = useUploadCover(book.id)
  const coverInput = useRef<HTMLInputElement>(null)
  const meta = st.metadata
  const metaField = (key: keyof typeof meta, label: string) => (
    <Field label={label}>
      {(id) => <Input id={id} size="sm" defaultValue={meta[key]} onBlur={(e) => e.target.value !== meta[key] && update((x) => void (x.metadata[key] = e.target.value))} />}
    </Field>
  )
  return (
    <SidebarSection title="Book file" icon={<ImageIcon />} defaultOpen={false}>
      <div className={s.cover}>
        {book.cover_url ? <img src={book.cover_url} alt="Cover" /> : <ImageIcon />}
        <Button size="sm" variant="secondary" loading={cover.isPending} disabled={st.format === 'mp3'} onClick={() => coverInput.current?.click()}>
          {book.cover_url ? 'Replace cover' : 'Add cover'}
        </Button>
        <input ref={coverInput} type="file" accept=".jpg,.jpeg,.png" hidden onChange={(e) => e.target.files?.[0] && cover.mutate(e.target.files[0])} />
      </div>
      {metaField('title', 'Title tag')}
      <div className={s.row2}>
        {metaField('author', 'Author')}
        {metaField('narrator', 'Narrator')}
      </div>
      <div className={s.row2}>
        {metaField('year', 'Year')}
        {metaField('genre', 'Genre')}
      </div>
      <Field label="Loudness">
        <ChipGroup
          value={st.loudness}
          onValueChange={(v) => update((x) => void (x.loudness = v))}
          chips={[
            { value: 'off', label: 'Off' },
            { value: 'acx', label: 'ACX (−19 LUFS)' },
            { value: 'podcast', label: 'Podcast (−16 LUFS)' },
          ]}
        />
      </Field>
      <Field label="Line gap" aside={`${st.line_gap_ms} ms`}>
        <Slider min={0} max={2000} step={50} value={st.line_gap_ms} onValueChange={(v) => update((x) => void (x.line_gap_ms = v))} />
      </Field>
      <Field label="Paragraph gap" aside={`${st.paragraph_gap_ms} ms`}>
        <Slider min={0} max={3000} step={50} value={st.paragraph_gap_ms} onValueChange={(v) => update((x) => void (x.paragraph_gap_ms = v))} />
      </Field>
      <Field label="Bitrate">
        <ChipGroup value={st.bitrate} onValueChange={(v) => update((x) => void (x.bitrate = v))} chips={BITRATES.map((b) => ({ value: b, label: b }))} />
      </Field>
    </SidebarSection>
  )
}

function Renders({ book }: { book: AudiobookProject }) {
  const remove = useDeleteRender(book.id)
  if (!book.renders.length) return null
  return (
    <section className={s.renders}>
      <h3>Renders</h3>
      {book.renders.map((r) => (
        <Card key={r.id} padding="md" className={s.render}>
          <div className={s.renderHead}>
            <Badge size="sm" color="var(--hue-voice)">
              {r.format.toUpperCase()}
            </Badge>
            <strong className={s.renderName}>{r.filename}</strong>
            <span className={s.hint}>
              {fmtDuration(r.duration)} · {formatBytes(r.size)} · {r.cached_chapters} cached · {timeAgo(r.created_at)}
            </span>
            <Button size="sm" variant="secondary" iconLeft={<Download />} asChild>
              <a href={r.url} download={r.filename}>
                Download
              </a>
            </Button>
            <IconButton size="sm" label="Delete render" icon={<Trash2 />} onClick={() => remove.mutate(r.id)} />
          </div>
          <AudioPlayer src={r.url} color="var(--hue-voice)" />
          <ol className={s.marks}>
            {r.chapters.map((c) => (
              <li key={`${c.start}-${c.title}`}>
                <span className={s.markTime}>{fmtDuration(c.start)}</span> {c.title}
              </li>
            ))}
          </ol>
        </Card>
      ))}
    </section>
  )
}
