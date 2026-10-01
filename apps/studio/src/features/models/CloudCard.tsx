import { forwardRef, type ReactNode } from 'react'
import { motion } from 'motion/react'
import { ArrowRight, AudioLines, Binary, Brain, Clapperboard, Ear, ExternalLink, FileText, Image, MessageSquareText, Pin, PinOff, Wrench } from 'lucide-react'
import { Badge, Button, Card, Tooltip } from '@studio/ui'
import type { CloudModel, CloudUse } from '../../api/contracts/openrouter'
import { usePinCloudModel } from '../../api/openrouter'
import { describePrice, formatPrice } from '../../lib/money'
import { formatTokens } from '../../lib/format'
import s from './CloudCard.module.css'

const MODALITY: Record<string, { icon: ReactNode; label: string }> = {
  text: { icon: <MessageSquareText />, label: 'Text' },
  image: { icon: <Image />, label: 'Image' },
  audio: { icon: <AudioLines />, label: 'Audio' },
  speech: { icon: <AudioLines />, label: 'Speech' },
  transcription: { icon: <Ear />, label: 'Transcription' },
  video: { icon: <Clapperboard />, label: 'Video' },
  file: { icon: <FileText />, label: 'Files' },
  embeddings: { icon: <Binary />, label: 'Embeddings' },
}

const USE: Record<CloudUse, { hue: string; pinHint: string }> = {
  chat: { hue: 'var(--hue-text)', pinHint: 'Adds it to the chat model picker' },
  image: { hue: 'var(--hue-image)', pinHint: 'Adds it to your image models' },
  voice: { hue: 'var(--hue-voice)', pinHint: 'Adds it to your voice models' },
  stt: { hue: 'var(--hue-stt)', pinHint: 'Adds it to your transcription models' },
}

function Modalities({ list }: { list: string[] }) {
  return (
    <span className={s.modalities}>
      {list.map((m) => (
        <Tooltip key={m} content={MODALITY[m]?.label ?? m}>
          <span className={s.modality}>{MODALITY[m]?.icon ?? <span className={s.modalityText}>{m}</span>}</span>
        </Tooltip>
      ))}
    </span>
  )
}


export const CloudCard = forwardRef<HTMLDivElement, { model: CloudModel; index: number }>(function CloudCard({ model, index }, ref) {
  const pin = usePinCloudModel()
  const use = model.use ? USE[model.use] : undefined

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.3, delay: Math.min(index * 0.02, 0.25), ease: [0.16, 1, 0.3, 1] }}
    >
      <Card spotlight tint={use?.hue} padding="none" className={s.card} data-pinned={model.pinned || undefined}>
        <div className={s.top}>
          <div className={s.titles}>
            <span className={s.vendor}>{model.vendor}</span>
            <h3 className={s.name} title={model.name}>
              {model.name}
            </h3>
            <code className={s.id}>{model.id}</code>
          </div>
          <Tooltip content="Open on openrouter.ai">
            <a className={s.link} href={`https://openrouter.ai/${model.id.split(':')[0]}`} target="_blank" rel="noreferrer" aria-label="Open on openrouter.ai">
              <ExternalLink size={14} />
            </a>
          </Tooltip>
        </div>

        <div className={s.flow}>
          <Modalities list={model.input_modalities} />
          <ArrowRight size={12} className={s.arrow} />
          <Modalities list={model.output_modalities} />
          <span className={s.badges}>
            {model.tools && (
              <Badge size="sm" tone="info" icon={<Wrench size={11} />}>
                Tools
              </Badge>
            )}
            {model.reasoning && (
              <Badge size="sm" icon={<Brain size={11} />}>
                Reasoning
              </Badge>
            )}
            {model.free && (
              <Badge size="sm" tone="success">
                Free
              </Badge>
            )}
          </span>
        </div>

        <p className={s.desc}>{model.description}</p>

        <div className={s.footer}>
          <div className={s.prices}>
            {model.prices.length === 0 && !model.free && <span className={s.unknown}>{model.price_dynamic ? 'Price varies — see openrouter.ai' : 'Price not listed'}</span>}
            {model.prices
              .filter((p) => p.usd > 0)
              .map((p) => (
                <Tooltip key={p.unit} content={describePrice(p)}>
                  <span className={s.price}>{formatPrice(p)}</span>
                </Tooltip>
              ))}
            {model.context_length != null && <span className={s.ctx}>{formatTokens(model.context_length)} ctx</span>}
          </div>
          {use ? (
            <Tooltip content={model.pinned ? 'Remove from the studio' : use.pinHint}>
              <Button
                size="sm"
                variant={model.pinned ? 'outline' : 'secondary'}
                iconLeft={model.pinned ? <PinOff /> : <Pin />}
                loading={pin.isPending}
                onClick={() => pin.mutate({ model, pin: !model.pinned })}
              >
                {model.pinned ? 'Unpin' : 'Pin'}
              </Button>
            </Tooltip>
          ) : (
            <span className={s.browseOnly}>Browse only</span>
          )}
        </div>
      </Card>
    </motion.div>
  )
})
