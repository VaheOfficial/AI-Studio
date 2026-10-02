import { useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Music, Music2, Sparkles, Trash2 } from 'lucide-react'
import { AudioPlayer, Button, EmptyState, Field, IconButton, Progress, SeedField, Slider, Switch, Textarea, cn, resolveSeed } from '@studio/ui'
import { useDeleteOutput, useGenerateMusic, useOutputs } from '../../api/hooks'
import { useJob } from '../../api/live'
import type { MusicRequest, Output } from '../../api/types'
import { ModelPicker } from '../../components/ModelPicker'
import { useModelChoice } from '../../components/useModelChoice'
import { StudioHead, StudioLayout } from '../../components/Page'
import { WorkingCard } from '../../components/Working'
import s from './MusicPage.module.css'

const GENRES = ['synthwave', 'lo-fi hip hop', 'cinematic orchestral', 'indie pop', 'drum & bass', 'acoustic folk', 'trap', 'jazz', 'metal', 'ambient', 'k-pop', 'house']
const MOODS = ['uplifting', 'melancholic', 'dreamy', 'energetic', 'dark', 'romantic']
const SECTIONS = ['[verse]', '[chorus]', '[bridge]', '[outro]']

export default function MusicPage() {
  const { models, selected, select, isLoading, unavailable } = useModelChoice('music', 'music', undefined, 'music')
  const [tags, setTags] = useState('synthwave, 110 bpm, female vocals, dreamy')
  const [lyrics, setLyrics] = useState('[verse]\nNeon rivers in the midnight rain\nWe were running from the static in our veins\n\n[chorus]\nHold on, hold on to the afterglow\n')
  const [instrumental, setInstrumental] = useState(false)
  const [duration, setDuration] = useState(60)
  const [steps, setSteps] = useState(60)
  const [guidance, setGuidance] = useState(15)
  const [seed, setSeed] = useState<number | null>(null)
  const [lastSeed, setLastSeed] = useState<number>()
  const [jobId, setJobId] = useState<string>()
  const lyricsRef = useRef<HTMLTextAreaElement>(null)

  const generate = useGenerateMusic()
  const job = useJob(jobId)
  const running = job && (job.status === 'queued' || job.status === 'running')
  const { data: tracks = [] } = useOutputs('music')
  const del = useDeleteOutput()

  const toggleTag = (t: string) => {
    const list = tags.split(',').map((x) => x.trim()).filter(Boolean)
    setTags((list.includes(t) ? list.filter((x) => x !== t) : [...list, t]).join(', '))
  }
  const hasTag = (t: string) => tags.split(',').map((x) => x.trim()).includes(t)

  const insertSection = (tag: string) => {
    const el = lyricsRef.current
    const pos = el?.selectionStart ?? lyrics.length
    const before = lyrics.slice(0, pos)
    const insert = `${before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : ''}${tag}\n`
    setLyrics(before + insert + lyrics.slice(pos))
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(pos + insert.length, pos + insert.length)
    })
  }

  const submit = () => {
    if (!selected || running) return
    const used = resolveSeed(seed)
    setLastSeed(used)
    const req: MusicRequest = {
      model_id: selected.id,
      tags,
      lyrics: instrumental ? '[instrumental]' : lyrics,
      duration_s: duration,
      steps,
      guidance,
      seed: used,
    }
    generate.mutate(req, { onSuccess: (j) => setJobId(j.id) })
  }

  const controls = (
    <div className={s.controls}>
      <StudioHead icon={<Music />} title="Music" subtitle="Songs from a style and lyrics" />
      <ModelPicker kind="music" models={models} selected={selected} onSelect={select} isLoading={isLoading} unavailable={unavailable} />

      <Field label="Style" hint="Genre, instruments, tempo, vocals, mood — comma separated.">
        {(id) => <Textarea id={id} autoResize minRows={2} maxRows={5} value={tags} onChange={(e) => setTags(e.target.value)} />}
      </Field>
      <div className={s.chips}>
        {[...GENRES, ...MOODS].map((g) => (
          <button key={g} className={cn(s.chip, hasTag(g) && s.chipOn)} onClick={() => toggleTag(g)}>
            {g}
          </button>
        ))}
      </div>

      <Field label="Length" aside={`${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, '0')}`}>
        <Slider aria-label="Length" value={duration} onValueChange={setDuration} min={10} max={240} step={5} />
      </Field>
      <div className={s.row2}>
        <Field label="Steps" aside={steps}>
          <Slider aria-label="Steps" value={steps} onValueChange={setSteps} min={10} max={120} />
        </Field>
        <Field label="Guidance" aside={guidance}>
          <Slider aria-label="Guidance" value={guidance} onValueChange={setGuidance} min={1} max={30} step={0.5} />
        </Field>
      </div>
      <SeedField value={seed} onChange={setSeed} lastUsed={lastSeed} />
    </div>
  )

  return (
    <StudioLayout controls={controls} hue="var(--hue-music)">
      <div className={s.canvas}>
        <div className={s.lyricsCard}>
          <div className={s.lyricsHead}>
            <span className={s.lyricsTitle}>Lyrics</span>
            {!instrumental && (
              <div className={s.sections}>
                {SECTIONS.map((t) => (
                  <button key={t} className={s.section} onClick={() => insertSection(t)}>
                    {t.slice(1, -1)}
                  </button>
                ))}
              </div>
            )}
            <Switch checked={instrumental} onCheckedChange={setInstrumental} label="Instrumental" />
          </div>
          <AnimatePresence initial={false} mode="wait">
            {instrumental ? (
              <motion.div key="inst" className={s.instrumental} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <Equalizer bars={24} active />
                <span>No vocals — the style prompt drives everything.</span>
              </motion.div>
            ) : (
              <motion.div key="lyrics" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <Textarea ref={lyricsRef} autoResize minRows={10} maxRows={24} value={lyrics} onChange={(e) => setLyrics(e.target.value)} className={s.lyrics} mono />
              </motion.div>
            )}
          </AnimatePresence>
          <div className={s.lyricsFoot}>
            {running ? (
              <div className={s.progressWrap}>
                <Equalizer bars={5} active />
                <Progress value={job.progress} size="xs" className={s.progress} />
                <span className={s.progressText}>{job.message ?? 'Composing…'}</span>
              </div>
            ) : (
              <span />
            )}
            <Button variant="glow" size="lg" iconLeft={<Sparkles />} loading={generate.isPending || !!running} disabled={!selected} onClick={submit}>
              Create song
            </Button>
          </div>
        </div>

        <section className={s.tracks}>
          <h2 className={s.tracksTitle}>Your tracks</h2>
          {tracks.length === 0 && !running ? (
            <EmptyState tint="var(--hue-music)" icon={<Music2 />} title="No songs yet" description="Every track you create lands here with its cover and prompt." />
          ) : (
            <div className={s.trackList}>
              <AnimatePresence initial={false}>
                {running && <WorkingCard key="working" hue="var(--hue-music)" title="Composing your song" message={job.message} progress={job.progress} />}
                {tracks.map((t) => (
                  <Track key={t.id} track={t} onDelete={() => del.mutate(t.id)} />
                ))}
              </AnimatePresence>
            </div>
          )}
        </section>
      </div>
    </StudioLayout>
  )
}

function Track({ track, onDelete }: { track: Output; onDelete: () => void }) {
  const p = track.params as Partial<MusicRequest>
  const title = track.prompt.split(',')[0]?.trim() || 'Untitled'
  return (
    <motion.div layout className={s.track} initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0 }}>
      <Cover seed={String(p.seed ?? track.id)} />
      <div className={s.trackBody}>
        <div className={s.trackHead}>
          <div className={s.trackTitles}>
            <span className={s.trackTitle}>{title}</span>
            <span className={s.trackTags}>{track.prompt}</span>
          </div>
          <IconButton size="sm" variant="danger" label="Delete track" icon={<Trash2 />} onClick={onDelete} />
        </div>
        <AudioPlayer src={track.url} color="var(--hue-music)" height={36} bars={120} downloadName={`${title}.wav`} />
      </div>
    </motion.div>
  )
}

/** Generative cover art from the seed: layered conic/radial gradients. */
function Cover({ seed }: { seed: string }) {
  let h = 0
  for (const c of seed) h = (h * 33 + c.charCodeAt(0)) >>> 0
  const a = h % 360
  const b = (a + 90 + (h % 120)) % 360
  const c = (b + 60) % 360
  return (
    <div
      className={s.cover}
      style={{
        background: `radial-gradient(circle at ${20 + (h % 60)}% ${20 + ((h >> 3) % 60)}%, hsl(${a} 90% 65% / .9), transparent 55%),
          radial-gradient(circle at ${80 - (h % 50)}% ${75 - ((h >> 5) % 40)}%, hsl(${b} 85% 55% / .85), transparent 60%),
          conic-gradient(from ${h % 360}deg, hsl(${c} 70% 25%), hsl(${a} 70% 18%), hsl(${c} 70% 25%))`,
      }}
    />
  )
}

function Equalizer({ bars, active }: { bars: number; active?: boolean }) {
  return (
    <div className={s.eq} aria-hidden>
      {Array.from({ length: bars }, (_, i) => (
        <motion.span
          key={i}
          animate={active ? { scaleY: [0.25, 1, 0.4, 0.8, 0.25] } : { scaleY: 0.25 }}
          transition={{ duration: 1.1 + (i % 4) * 0.17, repeat: Infinity, ease: 'easeInOut', delay: i * 0.07 }}
        />
      ))}
    </div>
  )
}
