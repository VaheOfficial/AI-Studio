import { useState } from 'react'
import { Download, PackageOpen, Trash2 } from 'lucide-react'
import { Button, ChipGroup, Field, IconButton, Select, Switch } from '@studio/ui'
import type { DubExportFormat, DubProject } from '../../api/contracts/dub'
import { useLanguageName } from '../../api/voice'
import { formatBytes, timeAgo } from '../../lib/format'
import { useDeleteExport, useExportDub } from './api'
import { SidebarSection } from './SidebarSection'
import s from './Sidebar.module.css'
import x from './ExportSection.module.css'

const FORMATS: { value: DubExportFormat; label: string; video?: boolean }[] = [
  { value: 'mp4', label: 'MP4', video: true },
  { value: 'wav', label: 'WAV' },
  { value: 'mp3', label: 'MP3' },
  { value: 'srt', label: 'SRT' },
  { value: 'vtt', label: 'VTT' },
  { value: 'ass', label: 'ASS karaoke' },
  { value: 'stems', label: 'Stems' },
  { value: 'clips', label: 'Clips' },
]

/** Export drawer (VoiceStudio `dub-export-panel.tsx`): format, tracks, background, bitrate, burned subtitles. */
export function ExportSection({ project, busy }: { project: DubProject; busy: boolean }) {
  const languageName = useLanguageName()
  const run = useExportDub(project.id)
  const remove = useDeleteExport(project.id)
  const video = project.source.input_type === 'video'
  const tracks = Object.keys(project.tracks)
  const [format, setFormat] = useState<DubExportFormat>(video ? 'mp4' : 'wav')
  const [excluded, setExcluded] = useState<string[]>([])
  const [original, setOriginal] = useState(false)
  const [defaultChoice, setDefaultLang] = useState('')
  const [langChoice, setLang] = useState('')
  const [bg, setBg] = useState(!!project.separation)
  const [bitrate, setBitrate] = useState('192')
  const [burn, setBurn] = useState(false)
  const [dual, setDual] = useState(false)
  const [karaoke, setKaraoke] = useState(false)
  const included = tracks.filter((t) => !excluded.includes(t))
  const lang = langChoice || tracks[0] || project.settings.targets[0] || ''
  const defaultLang =
    (defaultChoice === 'original' && original) || included.includes(defaultChoice) ? defaultChoice : (included[0] ?? 'original')

  const subtitle = format === 'srt' || format === 'vtt' || format === 'ass'
  const langs = format === 'mp4' ? included : lang ? [lang] : []
  const stretched = format === 'mp4' && project.tracks[defaultLang]?.timing === 'stretch_video'
  const ready = subtitle ? !!lang : format === 'mp4' ? included.length > 0 || original : !!project.tracks[lang]
  const langOptions = (subtitle ? project.settings.targets : tracks).map((t) => ({ value: t, label: languageName(t) }))

  return (
    <SidebarSection title="Export" icon={<PackageOpen />} aside={project.exports.length || undefined} defaultOpen={false}>
      <ChipGroup value={format} onValueChange={setFormat} chips={FORMATS.filter((f) => video || !f.video)} />
      {format === 'mp4' ? (
        <>
          <div className={x.trackList}>
            <Switch label="Original audio" checked={original} onCheckedChange={setOriginal} />
            {tracks.map((t) => (
              <Switch
                key={t}
                label={languageName(t)}
                checked={included.includes(t)}
                onCheckedChange={(on) => setExcluded((cur) => (on ? cur.filter((v) => v !== t) : [...cur, t]))}
              />
            ))}
          </div>
          <Field label="Default audio track">
            {(id) => (
              <Select
                id={id}
                size="sm"
                value={defaultLang}
                onValueChange={setDefaultLang}
                options={[...(original ? [{ value: 'original', label: 'Original' }] : []), ...included.map((t) => ({ value: t, label: languageName(t) }))]}
              />
            )}
          </Field>
        </>
      ) : (
        <Field label="Language">
          {(id) => <Select id={id} size="sm" value={lang} onValueChange={setLang} options={langOptions} placeholder="Generate a track first" />}
        </Field>
      )}
      {(format === 'mp4' || format === 'wav' || format === 'mp3') && (
        <Switch
          label="Keep background"
          description={project.separation ? 'Music and effects under the dub' : 'Needs vocal separation (unavailable)'}
          checked={bg}
          disabled={!project.separation}
          onCheckedChange={setBg}
        />
      )}
      {format === 'mp3' && (
        <ChipGroup value={bitrate} onValueChange={setBitrate} chips={['128', '192', '256', '320'].map((b) => ({ value: b, label: `${b}k` }))} />
      )}
      {format === 'mp4' && (
        <>
          <Switch label="Burn subtitles" description={stretched ? 'Not with Stretch video timing' : undefined} disabled={stretched} checked={burn && !stretched} onCheckedChange={setBurn} />
          {burn && !stretched && (
            <>
              <Switch label="Dual (translation over original)" checked={dual} onCheckedChange={setDual} />
              <Switch label="Karaoke word highlight" description={dual ? 'Not with dual subtitles' : undefined} disabled={dual} checked={karaoke && !dual} onCheckedChange={setKaraoke} />
            </>
          )}
        </>
      )}
      {(format === 'srt' || format === 'vtt') && <Switch label="Dual (translation over original)" checked={dual} onCheckedChange={setDual} />}
      <Button
        variant="primary"
        block
        iconLeft={<Download />}
        disabled={!ready || busy}
        loading={run.isPending}
        onClick={() =>
          run.mutate({
            format,
            langs,
            include_original: format === 'mp4' && original,
            default_lang: format === 'mp4' ? defaultLang : undefined,
            preserve_bg: bg && !!project.separation,
            bitrate: Number(bitrate),
            burn_subs: format === 'mp4' && burn && !stretched,
            dual,
            karaoke: karaoke && !dual,
          })
        }
      >
        Export {FORMATS.find((f) => f.value === format)?.label}
      </Button>
      {project.exports.length > 0 && (
        <div className={x.exports}>
          {project.exports.map((e) => (
            <div key={e.id} className={x.export}>
              <a href={e.url} download={e.filename} className={x.exportLink}>
                <Download size={13} />
                <span className={x.exportName}>{e.label}</span>
              </a>
              <span className={s.label}>
                {formatBytes(e.size)} · {timeAgo(e.created_at)}
              </span>
              <IconButton size="sm" label="Delete export" icon={<Trash2 />} onClick={() => remove.mutate(e.id)} />
            </div>
          ))}
        </div>
      )}
    </SidebarSection>
  )
}
