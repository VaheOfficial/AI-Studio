import { useRef } from 'react'
import { Download, RotateCcw, Trash2, Volume2, VolumeX } from 'lucide-react'
import { Badge, Button, Dialog, IconButton } from '@studio/ui'
import { useLive } from '../../api/live'
import type { Output } from '../../api/types'
import { downloadUrl } from '../../lib/download'
import s from './VideoCard.module.css'

interface ClipParams {
  mode?: 't2v' | 'i2v'
  fps?: number
  audio?: boolean
  seed?: number
  segments?: number
  two_stage?: boolean
  decoder?: string
  steps?: number
  guidance?: number
  image?: string
  enhanced_prompt?: string
  negative_prompt?: string
}

/** A clip in the grid: plays muted on hover, opens the detail view on click. */
export function VideoCard({ video, onOpen }: { video: Output; onOpen: () => void }) {
  const p = video.params as ClipParams
  const ref = useRef<HTMLVideoElement>(null)
  return (
    <figure className={s.card}>
      <button className={s.frame} onClick={onOpen} aria-label="Open video">
        <video
          ref={ref}
          // "#t=0.1": the browser fetches and paints that frame as the poster instead of a black tile
          src={`${video.url}#t=0.1`}
          style={video.width && video.height ? { aspectRatio: `${video.width} / ${video.height}` } : undefined}
          muted
          loop
          playsInline
          preload="metadata"
          onMouseEnter={() => void ref.current?.play().catch(() => undefined)}
          onMouseLeave={() => ref.current?.pause()}
        />
        <span className={s.badges}>
          {video.duration_s != null && <span className={s.pill}>{video.duration_s.toFixed(1)}s</span>}
          {p.audio && (
            <span className={s.pill}>
              <Volume2 size={11} />
            </span>
          )}
        </span>
      </button>
      <figcaption className={s.caption} title={video.prompt}>
        {video.prompt}
      </figcaption>
    </figure>
  )
}

/** Full-size player with the clip's settings and actions. */
export function VideoDetail({
  video,
  onClose,
  onReuse,
  onDelete,
}: {
  video: Output | null
  onClose: () => void
  onReuse: (v: Output) => void
  onDelete: (v: Output) => void
}) {
  const models = useLive((st) => st.models)
  if (!video) return null
  const p = video.params as ClipParams
  const model = models.find((m) => m.id === video.model_id)?.name ?? video.model_id
  const facts: [string, string][] = [
    ['Model', model],
    ['Mode', p.mode === 'i2v' ? 'From image' : 'From text'],
    ['Size', video.width ? `${video.width}×${video.height}` : '—'],
    ['Length', video.duration_s != null ? `${video.duration_s.toFixed(1)} s at ${p.fps ?? 24} fps` : '—'],
    ['Sound', p.audio ? 'Yes' : 'No'],
    ...(p.segments && p.segments > 1 ? ([['Parts', String(p.segments)]] as [string, string][]) : []),
    ...(p.two_stage ? ([['Upscale', 'Two-stage 2×']] as [string, string][]) : []),
    ...(p.decoder === 'diffusion' ? ([['Decoder', 'Diffusion (sharper)']] as [string, string][]) : []),
    ...(p.steps ? ([['Steps / guidance', `${p.steps} / ${p.guidance}`]] as [string, string][]) : []),
    ['Seed', p.seed != null ? String(p.seed) : '—'],
  ]
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title="Video"
      size="xl"
      footer={
        <>
          <IconButton label="Download" icon={<Download />} onClick={() => downloadUrl(video.url, `${video.id}.mp4`)} />
          <IconButton
            label="Delete"
            variant="danger"
            icon={<Trash2 />}
            onClick={() => {
              onDelete(video)
              onClose()
            }}
          />
          <Button variant="primary" iconLeft={<RotateCcw />} onClick={() => onReuse(video)}>
            Reuse settings
          </Button>
        </>
      }
    >
      <div className={s.detail}>
        <video className={s.player} src={video.url} controls autoPlay loop playsInline />
        <div className={s.info}>
          <p className={s.prompt}>{video.prompt}</p>
          {p.enhanced_prompt && (
            <details className={s.enhanced}>
              <summary>Enhanced prompt</summary>
              <p>{p.enhanced_prompt}</p>
            </details>
          )}
          {p.negative_prompt && <p className={s.negative}>Avoid: {p.negative_prompt}</p>}
          <dl className={s.facts}>
            {facts.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
          {p.image && (
            <div className={s.startFrame}>
              <Badge size="sm">Start image</Badge>
              <img src={p.image} alt="Start frame" />
            </div>
          )}
          {!p.audio && (
            <span className={s.silent}>
              <VolumeX size={12} /> Silent clip
            </span>
          )}
        </div>
      </div>
    </Dialog>
  )
}
