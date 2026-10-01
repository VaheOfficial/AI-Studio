import { forwardRef } from 'react'
import { motion } from 'motion/react'
import { Boxes, Clock, Download, Heart, Lock } from 'lucide-react'
import { Badge, Card, Tooltip } from '@studio/ui'
import type { HubSearchResult } from '../../api/contracts/hub'
import { formatCount, timeAgo } from '../../lib/format'
import { KINDS } from '../../lib/kinds'
import { FORMAT_LABEL, isNonCommercial } from './hubMeta'
import s from './HubResultCard.module.css'

export interface HubResultCardProps {
  result: HubSearchResult
  index: number
  onOpen: () => void
}

/** One search hit (Hugging Face repo or Ollama library model); opens the model's detail sheet. */
export const HubResultCard = forwardRef<HTMLDivElement, HubResultCardProps>(function HubResultCard({ result, index, onOpen }, ref) {
  const meta = result.kind ? KINDS[result.kind] : undefined
  const hue = meta?.hue ?? 'var(--accent)'
  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.3, delay: Math.min(index * 0.02, 0.25), ease: [0.16, 1, 0.3, 1] }}
    >
      <Card
        spotlight
        interactive
        tint={hue}
        padding="none"
        className={s.card}
        role="button"
        tabIndex={0}
        aria-label={`Open ${result.id}`}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onOpen()
          }
        }}
      >
        <div className={s.top}>
          <span className={s.kind} style={{ ['--hue' as string]: hue }}>
            {meta?.icon ?? <Boxes />}
          </span>
          <div className={s.titles}>
            <h3 className={s.name} title={result.id}>
              {result.name}
            </h3>
            <span className={s.author}>{result.author ?? (result.source === 'ollama' ? 'ollama' : '')}</span>
          </div>
        </div>

        {result.description && <p className={s.desc}>{result.description}</p>}

        <div className={s.badges}>
          {result.gated && (
            <Tooltip content="Accept the terms on huggingface.co and set an HF token in Settings to download.">
              <span>
                <Badge size="sm" tone="warning" icon={<Lock />}>
                  Gated
                </Badge>
              </span>
            </Tooltip>
          )}
          {result.license && (
            <Badge size="sm" tone={isNonCommercial(result.license) ? 'warning' : 'neutral'}>
              {isNonCommercial(result.license) ? `${result.license} · non-commercial` : result.license}
            </Badge>
          )}
          {result.formats
            .filter((f) => f !== 'ollama')
            .map((f) => (
              <Badge key={f} size="sm" tone={f === 'gguf' ? 'accent' : 'neutral'}>
                {FORMAT_LABEL[f]}
              </Badge>
            ))}
          {result.tags.map((t) => (
            <span key={t} className={s.tag}>
              {t}
            </span>
          ))}
        </div>

        <div className={s.footer}>
          {result.downloads != null && (
            <span className={s.stat} title={result.source === 'ollama' ? 'Pulls' : 'Downloads (30 days)'}>
              <Download size={13} />
              {formatCount(result.downloads)}
            </span>
          )}
          {result.likes != null && (
            <span className={s.stat} title="Likes">
              <Heart size={13} />
              {formatCount(result.likes)}
            </span>
          )}
          {result.updated_at && (
            <span className={s.stat} title="Last updated">
              <Clock size={13} />
              {timeAgo(result.updated_at)}
            </span>
          )}
        </div>
      </Card>
    </motion.div>
  )
})
