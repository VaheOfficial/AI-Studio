import { motion } from 'motion/react'
import { Download, Maximize2, Trash2 } from 'lucide-react'
import { AudioPlayer, IconButton, cn } from '@studio/ui'
import type { Output } from '../api/types'
import { downloadUrl } from '../lib/download'
import s from './OutputView.module.css'

export interface OutputViewProps {
  output: Output
  compact?: boolean
  onOpen?: (o: Output) => void
  onDelete?: (o: Output) => void
}

const fileName = (o: Output) => o.url.split('/').pop() ?? `${o.id}`

/** Renders any generated output: images as tiles, videos as players, audio/music as waveform players. */
export function OutputView({ output, compact, onOpen, onDelete }: OutputViewProps) {
  if (output.kind === 'image') {
    return (
      <motion.figure
        className={cn(s.image, compact && s.compact)}
        style={output.width && output.height ? { aspectRatio: `${output.width} / ${output.height}` } : undefined}
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      >
        <img src={output.url} alt={output.prompt} loading="lazy" onClick={() => onOpen?.(output)} />
        <figcaption className={s.overlay}>
          <p className={s.prompt}>{output.prompt}</p>
          <div className={s.actions}>
            {onOpen && <IconButton size="sm" label="View" icon={<Maximize2 />} onClick={() => onOpen(output)} />}
            <IconButton size="sm" label="Download" icon={<Download />} onClick={() => downloadUrl(output.url, fileName(output))} />
            {onDelete && <IconButton size="sm" variant="danger" label="Delete" icon={<Trash2 />} onClick={() => onDelete(output)} />}
          </div>
        </figcaption>
      </motion.figure>
    )
  }

  if (output.kind === 'video') {
    return (
      <figure className={cn(s.video, compact && s.compact)}>
        <video
          src={output.url}
          style={output.width && output.height ? { aspectRatio: `${output.width} / ${output.height}` } : undefined}
          controls
          loop
          playsInline
          preload="metadata"
        />
        <figcaption className={s.videoBar}>
          <p className={s.videoPrompt}>{output.prompt}</p>
          <IconButton size="sm" label="Download" icon={<Download />} onClick={() => downloadUrl(output.url, fileName(output))} />
          {onDelete && <IconButton size="sm" variant="danger" label="Delete" icon={<Trash2 />} onClick={() => onDelete(output)} />}
        </figcaption>
      </figure>
    )
  }

  const color = output.kind === 'music' ? 'var(--hue-music)' : 'var(--hue-voice)'
  return (
    <div className={cn(s.audio, compact && s.compact)}>
      {!compact && <p className={s.audioPrompt}>{output.prompt}</p>}
      <div className={s.audioRow}>
        <AudioPlayer src={output.url} color={color} compact={compact} downloadName={fileName(output)} />
        {onDelete && <IconButton size="sm" variant="danger" label="Delete" icon={<Trash2 />} onClick={() => onDelete(output)} />}
      </div>
    </div>
  )
}
