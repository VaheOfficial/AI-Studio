import { Check, Wand2 } from 'lucide-react'
import { AudioPlayer, Badge, Button, Dialog, EmptyState, Skeleton } from '@studio/ui'
import type { DubProject, DubSpeaker } from '../../api/contracts/dub'
import { usePatchDubProject, useVoiceSamples } from './api'
import { fmtClock } from './format'
import s from './VoiceSampleDialog.module.css'

/**
 * Pick the clip a speaker is cloned from. Candidates are the speaker's own line clips (separated vocals, trimmed
 * to the words), steadiest speech first; a pick is used for all of the speaker's lines until "Automatic".
 */
export function VoiceSampleDialog({ project, speaker, color, onClose }: { project: DubProject; speaker: DubSpeaker; color: string; onClose: () => void }) {
  const { data: samples, isPending } = useVoiceSamples(project.id, speaker.id, true)
  const patch = usePatchDubProject(project.id)
  const pick = (segment: string | null) => patch.mutate({ speakers: [{ id: speaker.id, ref_segment: segment }] })

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      size="lg"
      title={`Voice sample · ${speaker.id}`}
      description="Everything this speaker says in the dub is cloned from one sample. Listen, and pick a clip of plain speech — no singing, shouting or music. Your pick is used for all of the speaker's lines; changed lines re-render on the next Generate."
      footer={
        <>
          {speaker.ref_pinned && (
            <Button variant="ghost" iconLeft={<Wand2 />} disabled={patch.isPending} onClick={() => pick(null)}>
              Back to automatic
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            Done
          </Button>
        </>
      }
    >
      <div className={s.list} style={{ ['--c' as string]: color }}>
        {isPending ? (
          [0, 1, 2].map((i) => <Skeleton key={i} height={64} />)
        ) : !samples?.length ? (
          <EmptyState title="No clips for this speaker" description="Only lines with at least 3 s of clear speech get a clip. Merge short lines or fix the speaker labels, then generate again." />
        ) : (
          samples.map((x) => {
            const current = x.url === speaker.ref_url
            return (
              <div key={x.segment_id} className={s.sample} data-current={current || undefined}>
                <div className={s.meta}>
                  <span className={s.time}>{fmtClock(x.start)}</span>
                  <span>{x.duration.toFixed(1)}s</span>
                  <span>{x.chars_per_s} chars/s</span>
                  {x.suggested && (
                    <Badge size="sm" tone="accent">
                      Suggested
                    </Badge>
                  )}
                  {current && (
                    <Badge size="sm" tone="success" icon={<Check size={10} />}>
                      {speaker.ref_pinned ? 'Your pick' : 'In use'}
                    </Badge>
                  )}
                  <span className={s.grow} />
                  <Button size="sm" variant={current ? 'ghost' : 'secondary'} disabled={current || patch.isPending} onClick={() => pick(x.segment_id)}>
                    {current ? 'In use' : 'Use this'}
                  </Button>
                </div>
                <p className={s.text}>{x.text}</p>
                <AudioPlayer src={x.url} compact height={26} color="var(--c)" />
              </div>
            )
          })
        )}
        {!isPending && !!samples?.length && !speaker.ref_pinned && !samples.some((x) => x.url === speaker.ref_url) && speaker.ref_url && (
          <p className={s.note}>In use now: an automatic mix of several lines{speaker.ref_text ? ` — “${speaker.ref_text}”` : ''}.</p>
        )}
      </div>
    </Dialog>
  )
}
