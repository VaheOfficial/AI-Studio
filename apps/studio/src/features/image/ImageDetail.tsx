import { useNavigate } from 'react-router'
import { Clapperboard, Download, PencilLine, RotateCcw, Star, Trash2 } from 'lucide-react'
import { Button, Dialog, IconButton } from '@studio/ui'
import type { ImageGenerateRequest } from '../../api/contracts/image'
import { useLive } from '../../api/live'
import type { Output } from '../../api/types'
import { downloadUrl } from '../../lib/download'
import s from './ImageDetail.module.css'

const MODE_LABEL: Record<string, string> = { txt2img: 'Text to image', img2img: 'Image to image', inpaint: 'Inpaint', edit: 'Reference edit' }

export interface ImageDetailProps {
  output: Output | null
  onClose: () => void
  onReuse: (o: Output) => void
  onEdit: (o: Output) => void
  onDelete: (o: Output) => void
  starred?: boolean
  onStar?: (o: Output, starred: boolean) => void
}

/** Full-size view of a generated image with every parameter needed to reproduce it. */
export function ImageDetail({ output, onClose, onReuse, onEdit, onDelete, starred, onStar }: ImageDetailProps) {
  const navigate = useNavigate()
  const models = useLive((st) => st.models)
  const p = (output?.params ?? {}) as Partial<ImageGenerateRequest>
  const model = models.find((m) => m.id === output?.model_id)
  const rows: [string, string | number | undefined][] = output
    ? [
        ['Model', model?.name ?? `${output.model_id} (not installed)`],
        ['Mode', MODE_LABEL[p.mode ?? 'txt2img']],
        ['Size', output.width && output.height ? `${output.width}×${output.height}` : undefined],
        ['Seed', p.seed],
        ['Steps', p.steps],
        ['Guidance', p.guidance],
        ['Sampler', p.scheduler],
        ['Strength', p.strength],
        ['Negative', p.negative_prompt],
        ...Object.entries(p.options ?? {}).map(([k, v]): [string, string] => [k.replace('_', ' '), v]),
        ['Created', new Date(output.created_at).toLocaleString()],
      ]
    : []
  const inputs = [...(p.images ?? []), ...(p.mask ? [p.mask] : [])]

  return (
    <Dialog
      open={!!output}
      onOpenChange={(o) => !o && onClose()}
      size="xl"
      title="Image"
      description={output?.prompt}
      footer={
        output && (
          <>
            <div className={s.footLeft}>
              {onStar && (
                <IconButton
                  label={starred ? 'Unstar' : 'Star'}
                  icon={<Star className={starred ? s.starred : undefined} />}
                  active={starred}
                  onClick={() => onStar(output, !starred)}
                />
              )}
              <IconButton label="Download" icon={<Download />} onClick={() => downloadUrl(output.url, output.url.split('/').pop() ?? output.id)} />
              <IconButton
                label="Delete"
                variant="danger"
                icon={<Trash2 />}
                onClick={() => {
                  onDelete(output)
                  onClose()
                }}
              />
            </div>
            <Button
              variant="secondary"
              iconLeft={<Clapperboard />}
              onClick={() => navigate('/video/create', { state: { startImage: output.url } })}
            >
              Animate
            </Button>
            <Button variant="secondary" iconLeft={<PencilLine />} onClick={() => onEdit(output)}>
              Send to Edit
            </Button>
            <Button variant="primary" iconLeft={<RotateCcw />} onClick={() => onReuse(output)}>
              Reuse settings
            </Button>
          </>
        )
      }
    >
      {output && (
        <div className={s.body}>
          <img className={s.image} src={output.url} alt={output.prompt} />
          <aside className={s.meta}>
            <dl className={s.params}>
              {rows
                .filter(([, v]) => v !== undefined && v !== '')
                .map(([k, v]) => (
                  <div key={k} className={s.param}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
            </dl>
            {inputs.length > 0 && (
              <div className={s.inputs}>
                <span className={s.inputsLabel}>Inputs</span>
                <div className={s.thumbs}>
                  {inputs.map((u) => (
                    <a key={u} href={u} target="_blank" rel="noreferrer">
                      <img src={u} alt="" />
                    </a>
                  ))}
                </div>
              </div>
            )}
          </aside>
        </div>
      )}
    </Dialog>
  )
}
