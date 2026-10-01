import { useRef, useState } from 'react'
import { useLocation } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import { AlertTriangle, Clapperboard, Clock, Film, ImagePlus, Sparkles, X } from 'lucide-react'
import {
  Button,
  EmptyState,
  Field,
  GridBackdrop,
  IconButton,
  Input,
  Kbd,
  SeedField,
  SegmentedControl,
  Select,
  Slider,
  Switch,
  Textarea,
  cn,
  resolveSeed,
} from '@studio/ui'
import type { VideoMode, VideoRequest } from '../../api/contracts/video'
import { useDeleteOutput, useOutputs } from '../../api/hooks'
import { useJob } from '../../api/live'
import type { Output } from '../../api/types'
import { useGenerateVideo, useVideoProfiles } from '../../api/video'
import { AspectPicker } from '../../components/AspectPicker'
import { Developing } from '../../components/Developing'
import { ModelPicker } from '../../components/ModelPicker'
import { StudioLayout } from '../../components/Page'
import { useModelChoice } from '../../components/useModelChoice'
import { RESOLUTIONS, VIDEO_ASPECTS, estimate, formatDuration, sizeFor, type VideoAspect } from './plan'
import { VideoCard, VideoDetail } from './VideoCard'
import s from './VideoPage.module.css'

const IDEAS = [
  'Slow dolly shot through a rain-soaked neon alley at night, reflections on wet asphalt, steam rising, distant thunder',
  'A red fox trotting through fresh snow in a pine forest at sunrise, golden light, crunching snow',
  'Close-up of a barista pouring latte art in slow motion, warm café light, the hiss of the steam wand',
]
const UPSCALE = [
  { value: 'auto', label: 'Auto' },
  { value: 'on', label: 'Always' },
  { value: 'off', label: 'Never' },
] as const

const readDataUrl = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result))
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })

export default function VideoPage() {
  const { models, selected, select, isLoading, unavailable } = useModelChoice('video', 'video', undefined, 'video')
  const { data: profiles = [] } = useVideoProfiles()
  const profile = profiles.find((p) => p.model_id === selected?.id)

  // "Animate" on an image (Image area) opens this page with that image as the start frame
  const handedOver = (useLocation().state as { startImage?: string } | null)?.startImage
  const [mode, setMode] = useState<VideoMode>(handedOver ? 'i2v' : 't2v')
  const [start, setStart] = useState<string | undefined>(handedOver)
  const [prompt, setPrompt] = useState(handedOver ? 'The scene comes to life: gentle camera push-in, subtle natural motion' : IDEAS[0])
  const [negative, setNegative] = useState('')
  const [aspect, setAspect] = useState<VideoAspect | null>('16:9')
  const [short, setShort] = useState<number | null>(null) // null: the model's native size
  const [custom, setCustom] = useState<{ width: number; height: number } | null>(null)
  const [seconds, setSeconds] = useState(5)
  const [auto, setAuto] = useState(false)
  const [steps, setSteps] = useState<number>()
  const [guidance, setGuidance] = useState<number>()
  const [upscale, setUpscale] = useState<'auto' | 'on' | 'off'>('auto')
  const [enhance, setEnhance] = useState(false)
  const [sharp, setSharp] = useState(false)
  const [seed, setSeed] = useState<number | null>(null)
  const [lastSeed, setLastSeed] = useState<number>()
  const [jobId, setJobId] = useState<string>()
  const [viewing, setViewing] = useState<Output | null>(null)
  const picker = useRef<HTMLInputElement>(null)

  // A different model brings its own defaults
  const [shownFor, setShownFor] = useState<string>()
  if (profile && profile.model_id !== shownFor) {
    setShownFor(profile.model_id)
    setSeconds(profile.default_seconds)
    setSteps(profile.steps)
    setGuidance(profile.guidance)
    if (!profile.modes.includes(mode)) setMode(profile.modes[0])
  }

  const generate = useGenerateVideo()
  const job = useJob(jobId)
  const running = job && (job.status === 'queued' || job.status === 'running')
  const { data: videos = [] } = useOutputs('video')
  const del = useDeleteOutput()

  const size = (() => {
    if (!profile) return undefined
    if (custom) return custom
    const nativeShort = Math.min(profile.native_width, profile.native_height)
    return sizeFor(aspect ?? '16:9', short ?? nativeShort, profile.size_step, profile.max_side)
  })()
  /** "W×H" at a short side, in the current frame shape. */
  const dims = (short: number) => {
    const d = profile ? sizeFor(aspect ?? '16:9', short, profile.size_step, profile.max_side) : undefined
    return d ? `${d.width}×${d.height}` : ''
  }
  const est =
    profile && size
      ? estimate(profile, { ...size, seconds, steps, upscale: upscale === 'auto' ? null : upscale === 'on', diffusionDecoder: sharp })
      : undefined
  const needsImage = mode === 'i2v' && !start

  const submit = () => {
    if (!selected || !profile || !size || running || needsImage || !prompt.trim()) return
    const used = resolveSeed(seed)
    setLastSeed(used)
    const req: VideoRequest = {
      model_id: selected.id,
      prompt: prompt.trim(),
      negative_prompt: negative.trim() || undefined,
      mode,
      image: mode === 'i2v' ? start : undefined,
      width: size.width,
      height: size.height,
      duration_s: seconds,
      auto_duration: profile.auto_duration && auto,
      steps: profile.steps != null ? steps : undefined,
      guidance: profile.guidance != null ? guidance : undefined,
      upscale: upscale === 'auto' ? undefined : upscale === 'on',
      enhance_prompt: profile.prompt_enhancer && enhance,
      decoder: profile.diffusion_decoder && sharp ? 'diffusion' : 'vae',
      seed: used,
    }
    generate.mutate(req, { onSuccess: (j) => setJobId(j.id) })
  }

  const reuse = (v: Output) => {
    const p = v.params as Partial<VideoRequest> & { mode?: VideoMode; seed?: number }
    setPrompt(v.prompt)
    setNegative(p.negative_prompt ?? '')
    if (p.seed != null) setSeed(p.seed) // reusing a clip means its seed, locked
    if (p.mode) setMode(p.mode)
    if (p.image) setStart(p.image)
    if (v.width && v.height) setCustom({ width: v.width, height: v.height })
    if (typeof p.duration_s === 'number') setSeconds(Math.max(1, Math.round(p.duration_s)))
    if (v.model_id !== selected?.id) select(v.model_id)
    setViewing(null)
  }

  const pickFile = async (files: FileList | null) => {
    const file = files?.[0]
    if (file && file.type.startsWith('image/')) setStart(await readDataUrl(file))
  }

  const snapTo = (v: number) =>
    profile ? Math.min(profile.max_side, Math.max(profile.size_step, Math.round(v / profile.size_step) * profile.size_step)) : v

  const controls = (
    <form
      className={s.form}
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <div className={s.head}>
        <span className={s.headIcon}>
          <Clapperboard />
        </span>
        <h1>Video</h1>
      </div>

      <ModelPicker kind="video" models={models} selected={selected} onSelect={select} isLoading={isLoading} unavailable={unavailable} />

      {profile && (
        <>
          <SegmentedControl<VideoMode>
            block
            aria-label="Mode"
            value={mode}
            onValueChange={setMode}
            segments={[
              { value: 't2v', label: 'From text', icon: <Film /> },
              { value: 'i2v', label: 'From image', icon: <ImagePlus /> },
            ]}
          />

          {mode === 'i2v' && (
            <Field label="Start image" hint="The first frame; the prompt says how it moves.">
              <div
                className={cn(s.start, start && s.startFilled)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  void pickFile(e.dataTransfer.files)
                }}
              >
                {start ? (
                  <>
                    <img src={start} alt="Start frame" />
                    <IconButton className={s.startClear} size="sm" label="Remove image" icon={<X />} onClick={() => setStart(undefined)} />
                  </>
                ) : (
                  <button type="button" className={s.startPick} onClick={() => picker.current?.click()}>
                    <ImagePlus size={18} />
                    <span>Drop an image or click to choose</span>
                  </button>
                )}
                <input ref={picker} type="file" accept="image/*" hidden onChange={(e) => void pickFile(e.target.files)} />
              </div>
            </Field>
          )}

          <Field label="Prompt" aside={`${prompt.length}`}>
            {(id) => (
              <Textarea
                id={id}
                autoResize
                minRows={5}
                maxRows={14}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder={profile.audio ? 'The shot, the motion and the sounds…' : 'The shot and the motion…'}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault()
                    submit()
                  }
                }}
              />
            )}
          </Field>
          <div className={s.ideas}>
            {IDEAS.map((idea) => (
              <button type="button" key={idea} className={s.idea} onClick={() => setPrompt(idea)}>
                {idea.split(',')[0]}
              </button>
            ))}
          </div>
          <Field label="Avoid" hint="Optional negative prompt.">
            {(id) => <Input id={id} value={negative} onChange={(e) => setNegative(e.target.value)} placeholder="blurry, text, watermark…" />}
          </Field>

          <Field label="Frame" aside={size ? `${size.width}×${size.height}` : undefined}>
            <AspectPicker
              aspects={VIDEO_ASPECTS}
              hue="var(--hue-video)"
              layoutId="video-aspect"
              value={custom ? null : aspect}
              onChange={(a) => {
                setAspect(a)
                setCustom(null)
              }}
            />
          </Field>
          <Field label="Resolution" hint="Anything up to 4K works; larger is slower.">
            {(id) => (
              <Select
                id={id}
                value={custom ? 'custom' : String(short ?? 'native')}
                onValueChange={(v) => {
                  setCustom(v === 'custom' && size ? size : null)
                  if (v !== 'custom') setShort(v === 'native' ? null : Number(v))
                }}
                options={[
                  { value: 'native', label: 'Native', description: `${dims(Math.min(profile.native_width, profile.native_height))} · what the model was trained at` },
                  ...RESOLUTIONS.map((r) => ({
                    value: String(r.value),
                    label: r.label,
                    description: dims(r.value),
                  })),
                  { value: 'custom', label: 'Custom', description: 'Type any width and height' },
                ]}
              />
            )}
          </Field>
          {custom && (
            <div className={s.row2}>
              {(['width', 'height'] as const).map((k) => (
                <Field key={k} label={k === 'width' ? 'Width' : 'Height'}>
                  {(id) => (
                    <Input
                      id={id}
                      inputMode="numeric"
                      value={String(custom[k])}
                      onChange={(e) => setCustom({ ...custom, [k]: Number(e.target.value.replace(/\D/g, '')) || 0 })}
                      onBlur={() => setCustom({ width: snapTo(custom.width), height: snapTo(custom.height) })}
                    />
                  )}
                </Field>
              ))}
            </div>
          )}

          <Field
            label="Length"
            aside={auto ? `auto, up to ${Math.min(seconds, 20)} s` : `${seconds} s`}
            hint={
              seconds > profile.segment_seconds && !auto
                ? `Made in ${Math.ceil(seconds / profile.segment_seconds)} parts of up to ${profile.segment_seconds} s, each continuing from the last frame.`
                : `${profile.fps} fps${profile.audio ? ' · with sound' : ''}`
            }
          >
            <Slider aria-label="Length" value={seconds} onValueChange={setSeconds} min={1} max={profile.max_seconds} step={1} />
          </Field>
          {profile.auto_duration && (
            <Switch checked={auto} onCheckedChange={setAuto} label="Auto length" description="The model decides how long the shot should be, up to the length above (20 s at most)." />
          )}

          {profile.steps != null && profile.steps_range && (
            <div className={s.row2}>
              <Field label="Steps" aside={steps}>
                <Slider aria-label="Steps" value={steps ?? profile.steps} onValueChange={setSteps} min={profile.steps_range[0]} max={profile.steps_range[1]} />
              </Field>
              <Field label="Guidance" aside={guidance}>
                <Slider aria-label="Guidance" value={guidance ?? profile.guidance ?? 5} onValueChange={setGuidance} min={1} max={10} step={0.5} />
              </Field>
            </div>
          )}

          {(profile.prompt_enhancer || profile.diffusion_decoder || profile.upscaler) && (
            <div className={s.switches}>
              {profile.prompt_enhancer && (
                <Switch checked={enhance} onCheckedChange={setEnhance} label="Enhance prompt" description="LTX's own prompt enhancer expands short prompts into detailed shot descriptions." />
              )}
              {profile.diffusion_decoder && (
                <Switch checked={sharp} onCheckedChange={setSharp} label="Sharper decoding" description="LTX-2.5's diffusion decoder: more fine detail, a bit slower." />
              )}
              {profile.upscaler && (
                <Field label="Two-stage upscale" hint="Render at half size, upsample the latents 2× and refine — the official way to high resolutions.">
                  <SegmentedControl<'auto' | 'on' | 'off'> block size="sm" value={upscale} onValueChange={setUpscale} segments={[...UPSCALE]} />
                </Field>
              )}
            </div>
          )}

          <SeedField value={seed} onChange={setSeed} lastUsed={lastSeed} />

          {est && (
            <div className={cn(s.estimate, est.heavy && s.estimateHeavy)}>
              {est.heavy ? <AlertTriangle size={14} /> : <Clock size={14} />}
              <span>
                About {formatDuration(est.seconds)}
                {est.segments > 1 && !auto ? ` · ${est.segments} parts` : ''}
                {est.twoStage ? ' · two-stage 2× upscale' : ''}
                {est.heavy ? ' — far above the native size: very slow, may run out of GPU memory' : ''}
              </span>
            </div>
          )}
          <ul className={s.notes}>
            {profile.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}

      <div className={s.submit}>
        <Button
          type="submit"
          variant="glow"
          size="lg"
          block
          iconLeft={<Sparkles />}
          loading={generate.isPending || !!running}
          disabled={!profile || needsImage || !prompt.trim()}
        >
          {running ? 'Rendering…' : needsImage ? 'Add a start image' : 'Create video'}
        </Button>
        <span className={s.hint}>
          <Kbd>Ctrl</Kbd> <Kbd>Enter</Kbd>
        </span>
      </div>
    </form>
  )

  return (
    <StudioLayout controls={controls} hue="var(--hue-video)">
      <GridBackdrop />
      <div className={s.canvas}>
        {videos.length === 0 && !running ? (
          <EmptyState tint="var(--hue-video)" icon={<Film />} title="No videos yet" description="Describe a shot on the left. Clips land here with their prompt and settings." />
        ) : (
          <motion.div layout className={s.grid}>
            <AnimatePresence initial={false}>
              {running && size && (
                <motion.div
                  key={`pending-${jobId}`}
                  layout
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                  style={{ aspectRatio: `${size.width} / ${size.height}` }}
                >
                  <Developing progress={job?.progress ?? -1} message={job?.message} />
                </motion.div>
              )}
              {videos.map((v) => (
                <motion.div key={v.id} layout>
                  <VideoCard video={v} onOpen={() => setViewing(v)} />
                </motion.div>
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>
      <VideoDetail video={viewing} onClose={() => setViewing(null)} onReuse={reuse} onDelete={(v) => del.mutate(v.id)} />
    </StudioLayout>
  )
}
