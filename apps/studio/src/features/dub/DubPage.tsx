import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { motion } from 'motion/react'
import { Clapperboard, Film, Link2, Music2, Trash2, Upload } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, EmptyState, Field, IconButton, Input, Skeleton, cn } from '@studio/ui'
import { useLanguageName } from '../../api/voice'
import { useLive } from '../../api/live'
import { formatBytes, timeAgo } from '../../lib/format'
import { AUTO_LANGUAGE, LanguagePicker } from '../voice/LanguagePicker'
import { useCreateDubProject, useDeleteDubProject, useDubProjects } from './api'
import { DubEditor } from './DubEditor'
import { RuntimeGate } from './RuntimeGate'
import { fmtDuration } from './format'
import s from './DubPage.module.css'

/** Voice → Dub: the project list / new dub form, or the editor for `?project=<id>`. */
export default function DubPage() {
  const [params, setParams] = useSearchParams()
  const projectId = params.get('project')
  const open = (id: string | null) => setParams(id ? { project: id } : {})
  return projectId ? <DubEditor projectId={projectId} onClose={() => open(null)} /> : <Projects onOpen={open} />
}

function Projects({ onOpen }: { onOpen: (id: string) => void }) {
  const { data: projects, isLoading } = useDubProjects()
  const remove = useDeleteDubProject()
  const [confirm, setConfirm] = useState<string | null>(null)
  const languageName = useLanguageName()
  return (
    <div className={s.page}>
      <header className={s.header}>
        <span className={s.headerIcon}>
          <Clapperboard />
        </span>
        <div>
          <h1 className={s.title}>Dubbing</h1>
          <p className={s.subtitle}>Translate a video or recording into 600+ languages in the speakers’ own voices.</p>
        </div>
      </header>
      <RuntimeGate />
      <NewDub onCreated={onOpen} />
      <section className={s.list}>
        <h2 className={s.sectionTitle}>Projects</h2>
        {isLoading ? (
          <div className={s.grid}>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} height={188} radius={14} />
            ))}
          </div>
        ) : !projects?.length ? (
          <EmptyState tint="var(--hue-voice)" icon={<Film />} title="No dubs yet" description="Your dubbing projects appear here." />
        ) : (
          <div className={s.grid}>
            {projects.map((p, i) => (
              <motion.div key={p.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }}>
                <Card padding="none" interactive className={s.card} onClick={() => onOpen(p.id)}>
                  <div className={s.thumb}>
                    {p.thumb_url ? <img src={p.thumb_url} alt="" /> : p.input_type === 'audio' ? <Music2 /> : <Film />}
                    <span className={s.duration}>{fmtDuration(p.duration)}</span>
                  </div>
                  <div className={s.cardBody}>
                    <div className={s.cardTitle}>{p.name}</div>
                    <div className={s.cardMeta}>
                      {p.segments} segments · {timeAgo(p.updated_at)}
                    </div>
                    <div className={s.tracks}>
                      {p.tracks.length ? (
                        p.tracks.map((t) => (
                          <Badge key={t} size="sm" color="var(--hue-voice)">
                            {languageName(t)}
                          </Badge>
                        ))
                      ) : (
                        <span className={s.noTracks}>No dubbed tracks yet</span>
                      )}
                    </div>
                  </div>
                  <IconButton
                    className={s.delete}
                    size="sm"
                    label="Delete project"
                    icon={<Trash2 />}
                    onClick={(e) => {
                      e.stopPropagation()
                      setConfirm(p.id)
                    }}
                  />
                </Card>
              </motion.div>
            ))}
          </div>
        )}
      </section>
      <ConfirmDialog
        open={confirm != null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title="Delete this dub?"
        description="The project, its dubbed tracks and exports are removed from disk."
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

function NewDub({ onCreated }: { onCreated: (id: string) => void }) {
  const create = useCreateDubProject()
  const fileInput = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [url, setUrl] = useState('')
  const [lang, setLang] = useState(AUTO_LANGUAGE)
  const [speakers, setSpeakers] = useState('')
  const [dragging, setDragging] = useState(false)
  const envReady = useLive((st) => st.runtimes.find((r) => r.id === 'dub')?.env_ready ?? false)

  const start = () =>
    create.mutate(
      {
        file: file ?? undefined,
        url: file ? undefined : url.trim(),
        sourceLang: lang === AUTO_LANGUAGE ? undefined : lang,
        numSpeakers: Number(speakers) || undefined,
      },
      { onSuccess: (res) => onCreated(res.project.id) },
    )

  return (
    <Card
      padding="lg"
      className={cn(s.new, dragging && s.dragging)}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        const f = e.dataTransfer.files[0]
        if (f) setFile(f)
      }}
    >
      <div className={s.newMain}>
        <span className={s.dropIcon}>
          <Upload />
        </span>
        <div className={s.newText}>
          <strong>{file ? file.name : 'Drop a video or audio file'}</strong>
          <span>{file ? formatBytes(file.size) : 'mp4, mov, mkv, webm, wav, mp3, m4a… or paste a link (YouTube and 1000+ sites via yt-dlp)'}</span>
        </div>
        <Button variant="secondary" iconLeft={<Upload />} onClick={() => fileInput.current?.click()}>
          Choose file
        </Button>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept="audio/*,video/*,.mkv,.mov,.mp4,.wav,.mp3"
          onChange={(e) => {
            if (e.target.files?.[0]) setFile(e.target.files[0])
            e.target.value = ''
          }}
        />
      </div>
      <div className={s.newOptions}>
        <Field label="Or a link">
          {(id) => (
            <Input
              id={id}
              iconLeft={<Link2 size={14} />}
              placeholder="https://…"
              value={url}
              disabled={!!file}
              onChange={(e) => setUrl(e.target.value)}
            />
          )}
        </Field>
        <Field label="Spoken language">{(id) => <LanguagePicker id={id} value={lang} onChange={setLang} />}</Field>
        <Field label="Speakers" hint="Leave empty to detect">
          {(id) => (
            <Input id={id} type="number" min={1} max={20} placeholder="Auto" value={speakers} onChange={(e) => setSpeakers(e.target.value)} />
          )}
        </Field>
        <div className={s.newActions}>
          {file && (
            <Button variant="ghost" onClick={() => setFile(null)}>
              Clear
            </Button>
          )}
          <Button variant="glow" loading={create.isPending} disabled={!envReady || (!file && !/^https?:\/\//.test(url.trim()))} onClick={start}>
            Transcribe
          </Button>
        </div>
      </div>
    </Card>
  )
}
