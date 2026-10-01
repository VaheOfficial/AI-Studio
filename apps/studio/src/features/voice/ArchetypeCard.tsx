import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Play, Plus, WandSparkles } from 'lucide-react'
import { AudioPlayer, Badge, Button, Card, toast } from '@studio/ui'
import type { Archetype } from '../../api/contracts/voice'
import { qk } from '../../api/keys'
import { useAdoptArchetype, useOnJobDone, usePreviewArchetype } from '../../api/voice'
import { VoiceOrb } from './VoiceOrb'
import s from './ArchetypeCard.module.css'

/** A gallery voice: preview (rendered once, then cached) and add it to the library, or start a design from it. */
export function ArchetypeCard({ archetype: a, onStart }: { archetype: Archetype; onStart?: (a: Archetype) => void }) {
  const qc = useQueryClient()
  const preview = usePreviewArchetype()
  const adopt = useAdoptArchetype()
  const [previewJob, setPreviewJob] = useState<string>()
  const [adoptJob, setAdoptJob] = useState<string>()
  const [url, setUrl] = useState(a.preview_url)
  const refresh = () => void qc.invalidateQueries({ queryKey: ['voice', 'archetypes'] })

  const rendering = useOnJobDone(previewJob, () => {
    setUrl(preview.data?.url)
    refresh()
  })
  const adding = useOnJobDone(adoptJob, () => {
    toast.success('Added to your voices', a.name)
    void qc.invalidateQueries({ queryKey: qk.voiceProfiles })
    refresh()
  })
  const busy = (j: typeof rendering) => j?.status === 'queued' || j?.status === 'running'
  const shownUrl = url ?? a.preview_url

  return (
    <Card padding="md" className={s.card} tint="var(--hue-voice)">
      <div className={s.head}>
        <VoiceOrb seed={a.id} size={34} />
        <div className={s.titles}>
          <span className={s.name}>{a.name}</span>
          <span className={s.instruct}>{a.instruct || 'neutral'}</span>
        </div>
        {a.featured && (
          <Badge size="sm" tone="accent">
            Featured
          </Badge>
        )}
      </div>
      {shownUrl ? (
        <AudioPlayer src={shownUrl} color="var(--hue-voice)" compact height={28} bars={48} />
      ) : (
        <Button
          size="sm"
          variant="ghost"
          iconLeft={<Play />}
          loading={preview.isPending || busy(rendering)}
          onClick={() =>
            preview.mutate(a.id, {
              onSuccess: (r) => (r.job ? setPreviewJob(r.job.id) : setUrl(r.url)),
            })
          }
        >
          {busy(rendering) ? 'Rendering preview…' : 'Preview'}
        </Button>
      )}
      <div className={s.foot}>
        <span className={s.lang}>{a.language_name}</span>
        {onStart && (
          <Button size="sm" variant="ghost" iconLeft={<WandSparkles />} onClick={() => onStart(a)}>
            Start from
          </Button>
        )}
        {a.profile_id ? (
          <Badge size="sm" tone="success" icon={<Check />}>
            In library
          </Badge>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            iconLeft={<Plus />}
            loading={adopt.isPending || busy(adding)}
            onClick={() => adopt.mutate(a.id, { onSuccess: (r) => r.job && setAdoptJob(r.job.id) })}
          >
            Use voice
          </Button>
        )}
      </div>
    </Card>
  )
}
