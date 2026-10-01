import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ClipboardPaste,
  Languages,
  MoreHorizontal,
  Redo2,
  RefreshCw,
  Sparkles,
  Undo2,
  Wand2,
  X,
} from 'lucide-react'
import {
  Badge,
  Button,
  EmptyState,
  IconButton,
  Menu,
  Progress,
  Select,
  Spinner,
  Timeline,
  VirtualList,
  type SelectGroup,
  type VirtualListHandle,
} from '@studio/ui'
import type { DubProject } from '../../api/contracts/dub'
import { useCancelJob } from '../../api/hooks'
import { useLanguageName, useVoiceProfiles } from '../../api/voice'
import { StudioLayout } from '../../components/Page'
import {
  useCleanupSegments,
  useDubProject,
  useDubWaveform,
  useGlossary,
  usePatchDubProject,
  useFailedProjectJob,
  usePreviewLine,
  useProjectJob,
  useRunDub,
  useVerifyDub,
} from './api'
import { textOf, useDubEditor, type EditSegment } from './editor'
import { ExportSection } from './ExportSection'
import { speakerColor } from './format'
import { GlossaryPanel } from './GlossaryPanel'
import { PastePanel } from './PastePanel'
import { usePlayback } from './playback'
import { RuntimeGate } from './RuntimeGate'
import { SegmentRow } from './SegmentRow'
import { CastSection, PreviewSection, ProductionSection, SourceSection, TargetsSection, TimingSection } from './Sidebar'
import s from './DubEditor.module.css'

const SAVE_DELAY_MS = 700

export function DubEditor({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { data: project, error } = useDubProject(projectId)
  if (error) {
    return <EmptyState tint="var(--danger)" icon={<AlertTriangle />} title="Project not found" description={error.message} action={<Button onClick={onClose}>All projects</Button>} />
  }
  if (!project) {
    return (
      <div className={s.loading}>
        <Spinner size={20} />
      </div>
    )
  }
  return <Editor project={project} onClose={onClose} />
}

function Editor({ project, onClose }: { project: DubProject; onClose: () => void }) {
  const job = useProjectJob(project.id)
  const busy = !!job
  const [linePreview, setLinePreview] = useState<string | null>(null)
  const saveNow = useAutosave(project, busy)
  return (
    <StudioLayout
      hue="var(--hue-voice)"
      controls={
        <>
          <SourceSection project={project} busy={busy} onClose={onClose} />
          <PreviewSection project={project} linePreview={linePreview} />
          <TargetsSection project={project} busy={busy} />
          <CastSection project={project} busy={busy} />
          <TimingSection project={project} />
          <ProductionSection project={project} />
          <ExportSection project={project} busy={busy} />
        </>
      }
    >
      <Workspace project={project} busy={busy} onLinePreview={setLinePreview} saveNow={saveNow} />
    </StudioLayout>
  )
}

/** Loads the project into the editor store and saves segment edits back (debounced). */
function useAutosave(project: DubProject, busy: boolean) {
  const load = useDubEditor((st) => st.load)
  const segments = useDubEditor((st) => st.segments)
  const saved = useDubEditor((st) => st.saved)
  const markSaved = useDubEditor((st) => st.markSaved)
  const patch = usePatchDubProject(project.id)
  const { mutateAsync } = patch

  useEffect(() => {
    load(project, busy)
  }, [project, busy, load])

  const save = useCallback(async () => {
    const current = useDubEditor.getState()
    if (current.projectId !== project.id || JSON.stringify(current.segments) === current.saved) return
    const snapshot = current.segments
    await mutateAsync({ segments: snapshot })
    markSaved(snapshot)
  }, [mutateAsync, markSaved, project.id])

  useEffect(() => {
    if (busy || JSON.stringify(segments) === saved) return
    const t = setTimeout(() => void save(), SAVE_DELAY_MS)
    return () => clearTimeout(t)
  }, [segments, saved, busy, save])

  return save
}

function Workspace({
  project,
  busy,
  onLinePreview,
  saveNow,
}: {
  project: DubProject
  busy: boolean
  onLinePreview: (url: string | null) => void
  saveNow: () => Promise<void>
}) {
  const job = useProjectJob(project.id)
  const failedJob = useFailedProjectJob(project.id)
  const cancel = useCancelJob()
  const languageName = useLanguageName()
  const segments = useDubEditor((st) => st.segments)
  const lang = useDubEditor((st) => st.lang)
  const selected = useDubEditor((st) => st.selected)
  const activeId = useDubEditor((st) => st.activeId)
  const { edit, undo, redo, setLang, setSelected, setActive } = useDubEditor.getState()
  const canUndo = useDubEditor((st) => st.undoStack.length > 0)
  const canRedo = useDubEditor((st) => st.redoStack.length > 0)
  const dirty = useDubEditor((st) => JSON.stringify(st.segments) !== st.saved)
  const playhead = usePlayback((st) => st.time)
  const { seek, playRange } = usePlayback.getState()
  const { data: waveform } = useDubWaveform(project.id, project.prepared)
  const { data: glossary = [] } = useGlossary(project.id)
  const { data: profiles = [] } = useVoiceProfiles()
  const translate = useRunDub(project.id, 'translate')
  const generate = useRunDub(project.id, 'generate')
  const verify = useVerifyDub(project.id)
  const cleanup = useCleanupSegments(project.id)
  const preview = usePreviewLine(project.id)
  const [previewing, setPreviewing] = useState<string | null>(null)
  const [panel, setPanel] = useState<'glossary' | 'paste' | null>(null)
  const [dismissed, setDismissed] = useState<string[]>([])
  const list = useRef<VirtualListHandle>(null)

  const targets = project.settings.targets
  const speakers = useMemo(() => project.speakers.map((sp) => sp.id), [project.speakers])
  const serverLines = useMemo(() => new Map(project.segments.map((seg) => [seg.id, seg.translations])), [project.segments])
  const track = lang ? project.tracks[lang] : undefined
  const stale = useMemo(() => new Set(track?.stale ?? []), [track])
  const ttsId = project.settings.tts.model_id
  const usable = profiles.filter((p) => p.kind !== 'preset' || p.model_id === ttsId)
  const voiceOptions = useMemo<SelectGroup[]>(
    () => [
      { label: 'From the video', options: [{ value: 'auto', label: 'Auto · clone this line' }] },
      { label: 'Engine', options: [{ value: '', label: 'Default voice' }] },
      ...(usable.length ? [{ label: 'Your voices', options: usable.map((p) => ({ value: p.id, label: p.name })) }] : []),
    ],
    [usable],
  )
  const voiceName = useCallback(
    (binding: string | undefined) =>
      binding === 'auto' ? 'Auto clone' : !binding ? 'Default voice' : (profiles.find((p) => p.id === binding)?.name ?? binding),
    [profiles],
  )
  const speakerVoice = useMemo(() => new Map(project.speakers.map((sp) => [sp.id, sp.voice])), [project.speakers])

  const failed = lang ? project.segments.filter((seg) => seg.translations[lang]?.error).length : 0
  const changed = [...new Set(Object.values(project.tracks).flatMap((t) => t.stale))].length
  const staleLangs = Object.values(project.tracks).filter((t) => t.stale.length).map((t) => t.lang)
  const translatedAll = targets.length > 0 && targets.every((t) => project.segments.every((seg) => seg.translations[t] || t === project.source_lang))
  const anyTranslation = targets.some((t) => project.segments.some((seg) => seg.translations[t]))
  const hasTracks = Object.keys(project.tracks).length > 0
  const warnings = lang
    ? project.segments.filter((seg) => {
        const t = seg.translations[lang]
        return t?.fit?.status === 'overflow_trimmed' || t?.fit?.status === 'silent' || t?.plan?.status === 'impossible'
      }).length
    : 0
  const readOnly = busy

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (readOnly || !(e.ctrlKey || e.metaKey)) return
      const key = e.key.toLowerCase()
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault()
        undo()
      } else if ((key === 'z' && e.shiftKey) || key === 'y') {
        e.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [readOnly, undo, redo])

  const run = async (fn: () => void) => {
    await saveNow()
    fn()
  }

  const onPreview = useCallback(
    (id: string) => {
      if (!lang) return
      setPreviewing(id)
      void saveNow()
        .then(() => preview.mutateAsync({ segment_id: id, lang }))
        .then((r) => onLinePreview(r.url))
        .finally(() => setPreviewing(null))
    },
    [lang, preview, saveNow, onLinePreview],
  )

  const timelineItems = useMemo(
    () => segments.map((seg, i) => ({ id: seg.id, start: seg.start, end: seg.end, label: String(i + 1), color: speakerColor(speakers, seg.speaker) })),
    [segments, speakers],
  )

  const stage = !anyTranslation ? 'asr' : !hasTracks ? 'translate' : 'done'
  const bulk = (fn: (seg: EditSegment) => EditSegment) => edit((segs) => segs.map((x) => (selected.includes(x.id) ? fn(x) : x)))

  if (!project.prepared) {
    return (
      <div className={s.center}>
        <RuntimeGate />
        {job ? (
          <div className={s.preparing}>
            <Spinner size={22} />
            <strong>Preparing {project.source.filename}</strong>
            <span>{job.message ?? 'Queued'}</span>
            <Progress value={job.progress} size="sm" />
            <Button size="sm" variant="ghost" onClick={() => cancel.mutate(job.id)}>
              Cancel
            </Button>
          </div>
        ) : (
          <EmptyState tint="var(--warning)" icon={<AlertTriangle />} title="Preparation did not finish" description="Check the job's error, then transcribe again." />
        )}
      </div>
    )
  }

  return (
    <div className={s.editor}>
      <div className={s.status}>
        <NameField project={project} />
        {job && (
          <div className={s.job}>
            <span className={s.jobText}>{job.message ?? job.title}</span>
            <Progress value={job.progress} size="xs" className={s.jobBar} />
            <Button size="sm" variant="ghost" iconLeft={<X />} onClick={() => cancel.mutate(job.id)}>
              Cancel
            </Button>
          </div>
        )}
      </div>
      <RuntimeGate />
      {project.warnings.map((w) => (
        <div key={w} className={s.warning}>
          <AlertTriangle size={14} /> {w}
        </div>
      ))}
      {failedJob && (
        <div className={s.warning} role="alert">
          <AlertTriangle size={14} /> {failedJob.title} failed: {(failedJob.error ?? failedJob.message ?? '').replace(/\.$/, '')}.
          Nothing was replaced — the previous result is still in place.
        </div>
      )}

      <div className={s.toolbar}>
        <Badge size="sm">{segments.length} lines</Badge>
        <Select
          size="sm"
          className={s.langSelect}
          value={lang || '__source'}
          onValueChange={(v) => setLang(v === '__source' ? '' : v)}
          options={[{ value: '__source', label: `Transcript${project.source_lang ? ` · ${languageName(project.source_lang)}` : ''}` }, ...targets.map((t) => ({ value: t, label: languageName(t) }))]}
        />
        <input
          type="checkbox"
          className={s.checkAll}
          aria-label="Select all lines"
          checked={selected.length > 0 && selected.length === segments.length}
          onChange={(e) => setSelected(e.target.checked ? segments.map((x) => x.id) : [])}
        />
        <IconButton size="sm" label="Undo (Ctrl+Z)" icon={<Undo2 />} disabled={!canUndo || readOnly} onClick={undo} />
        <IconButton size="sm" label="Redo (Ctrl+Shift+Z)" icon={<Redo2 />} disabled={!canRedo || readOnly} onClick={redo} />
        {failed > 0 && (
          <Button size="sm" variant="secondary" iconLeft={<RefreshCw />} disabled={busy} onClick={() => run(() => translate.mutate({ langs: [lang], only_failed: true }))}>
            Retry failed ({failed})
          </Button>
        )}
        <Button size="sm" variant={panel === 'paste' ? 'secondary' : 'ghost'} iconLeft={<ClipboardPaste />} disabled={readOnly} onClick={() => setPanel(panel === 'paste' ? null : 'paste')}>
          Paste translation
        </Button>
        <Button size="sm" variant={panel === 'glossary' ? 'secondary' : 'ghost'} iconLeft={<BookOpen />} onClick={() => setPanel(panel === 'glossary' ? null : 'glossary')}>
          Glossary{glossary.length ? ` (${glossary.length})` : ''}
        </Button>
        <span className={s.grow} />
        {dirty && <span className={s.saving}>Saving…</span>}
        <Menu
          trigger={<IconButton size="sm" label="More" icon={<MoreHorizontal />} />}
          items={[
            { label: 'Clean up segments', icon: <Wand2 size={14} />, disabled: readOnly, onSelect: () => void run(() => cleanup.mutate()) },
            ...Object.keys(project.tracks).map((t) => ({
              label: `Verify ${languageName(t)} (re-recognise the dub)`,
              icon: <CheckCircle2 size={14} />,
              disabled: busy,
              onSelect: () => verify.mutate(t),
            })),
          ]}
        />
      </div>

      <AnimatePresence>
        {!dismissed.includes(stage) && (
          <motion.div className={s.checkpoint} initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <Sparkles size={15} />
            <span className={s.grow}>
              {stage === 'asr'
                ? targets.length
                  ? 'Transcript ready — fix any recognition errors, then translate.'
                  : 'Transcript ready — add target languages in the settings column.'
                : stage === 'translate'
                  ? 'Translation ready — review the lines, cast the voices, then generate the dub.'
                  : `Dub ready${warnings ? ` · ${warnings} timing warning${warnings === 1 ? '' : 's'} in this language` : ''}.`}
            </span>
            {stage === 'asr' && targets.length > 0 && (
              <Button size="sm" variant="primary" disabled={busy} onClick={() => run(() => translate.mutate({}))}>
                Translate →
              </Button>
            )}
            {stage === 'translate' && (
              <Button size="sm" variant="primary" disabled={busy || !translatedAll} onClick={() => run(() => generate.mutate({ only_stale: false }))}>
                Generate →
              </Button>
            )}
            <IconButton size="sm" label="Dismiss" icon={<X />} onClick={() => setDismissed([...dismissed, stage])} />
          </motion.div>
        )}
      </AnimatePresence>

      {panel === 'glossary' && (
        <GlossaryPanel projectId={project.id} lang={lang || targets[0] || ''} canAuto={!!project.settings.translation.model} onClose={() => setPanel(null)} />
      )}
      {panel === 'paste' && <PastePanel lang={lang} onClose={() => setPanel(null)} />}

      {selected.length > 0 && (
        <div className={s.selection}>
          <strong>{selected.length} selected</strong>
          <Select size="sm" className={s.bulkSelect} placeholder="Set voice" value={undefined} disabled={readOnly} onValueChange={(v) => bulk((x) => ({ ...x, voice: v }))} options={voiceOptions} />
          <Select size="sm" className={s.bulkSelect} placeholder="Set speaker" value={undefined} disabled={readOnly} onValueChange={(v) => bulk((x) => ({ ...x, speaker: v }))} options={speakers.map((sp) => ({ value: sp, label: sp }))} />
          <Button size="sm" variant="danger" disabled={readOnly} onClick={() => {
            edit((segs) => segs.filter((x) => !selected.includes(x.id)))
            setSelected([])
          }}>
            Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
            Clear
          </Button>
        </div>
      )}

      <Timeline
        items={timelineItems}
        duration={project.source.duration}
        peaks={waveform?.peaks}
        onsets={waveform?.onsets}
        playhead={playhead}
        selectedId={activeId}
        disabled={readOnly}
        previewingId={previewing}
        onSelect={(id) => {
          setActive(id)
          list.current?.scrollToIndex(segments.findIndex((x) => x.id === id))
        }}
        onSeek={seek}
        onChange={(id, span) => edit((segs) => segs.map((x) => (x.id === id ? { ...x, ...span } : x)))}
        onDelete={(id) => edit((segs) => segs.filter((x) => x.id !== id))}
        onPlayRange={(item) => playRange(item.start, item.end)}
        onPreview={lang ? (item) => onPreview(item.id) : undefined}
      />

      <VirtualList
        ref={list}
        className={s.list}
        items={segments}
        itemKey={(seg) => seg.id}
        estimateSize={96}
        empty={<EmptyState icon={<Languages />} title="No lines" description="Import subtitles or transcribe again." />}
        renderItem={(seg, index) => (
          <SegmentRow
            seg={seg}
            index={index}
            line={lang ? serverLines.get(seg.id)?.[lang] : undefined}
            lang={lang}
            speakers={speakers}
            color={speakerColor(speakers, seg.speaker)}
            voiceOptions={voiceOptions}
            voiceLabel={voiceName(seg.voice ?? speakerVoice.get(seg.speaker))}
            selected={selected.includes(seg.id)}
            active={activeId === seg.id}
            stale={stale.has(seg.id)}
            readOnly={readOnly}
            duration={project.source.duration}
            previewing={previewing === seg.id}
            canPreview={!!lang && !!textOf(seg, lang).trim() && !busy}
            onPreview={onPreview}
          />
        )}
      />

      <footer className={s.footer}>
        <span className={s.footerInfo}>
          {hasTracks ? (changed ? `${changed} line${changed === 1 ? '' : 's'} changed since the last render` : 'All tracks up to date') : `${targets.length} target language${targets.length === 1 ? '' : 's'}`}
        </span>
        <Button variant="secondary" disabled={busy || !targets.length} loading={translate.isPending} onClick={() => run(() => translate.mutate({}))}>
          Translate all
        </Button>
        {changed > 0 && (
          <Button variant="secondary" disabled={busy} loading={generate.isPending} onClick={() => run(() => generate.mutate({ langs: staleLangs, only_stale: true }))}>
            Regenerate changed ({changed})
          </Button>
        )}
        <Button variant="glow" disabled={busy || !translatedAll} loading={generate.isPending} onClick={() => run(() => generate.mutate({ only_stale: false }))}>
          {targets.length > 1 ? `Generate ${targets.length} dubs` : 'Generate dub'}
        </Button>
      </footer>
    </div>
  )
}

function NameField({ project }: { project: DubProject }) {
  const patch = usePatchDubProject(project.id)
  const [name, setName] = useState(project.name)
  return (
    <input
      className={s.name}
      value={name}
      aria-label="Project name"
      onChange={(e) => setName(e.target.value)}
      onBlur={() => name.trim() && name !== project.name && patch.mutate({ name })}
      onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
    />
  )
}
