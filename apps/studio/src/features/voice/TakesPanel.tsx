import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { AudioLines, Lock, RotateCcw, Star, Trash2 } from 'lucide-react'
import { AudioPlayer, Badge, EmptyState, IconButton, SegmentedControl, Skeleton, Tooltip, cn } from '@studio/ui'
import type { VoiceTake } from '../../api/contracts/voice'
import { useDeleteTake, useLanguageName, useLockTake, useStarTake, useTakes } from '../../api/voice'
import s from './TakesPanel.module.css'

const ago = (iso: string) => {
  const sec = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`
  return new Date(iso).toLocaleDateString()
}

/** Every render with its settings: star, reuse, lock into its voice, delete, download. */
export function TakesPanel({ onReuse, lockable }: { onReuse: (take: VoiceTake) => void; lockable: (take: VoiceTake) => boolean }) {
  const { data: takes, isLoading } = useTakes()
  const [filter, setFilter] = useState<'all' | 'starred'>('all')
  const shown = useMemo(() => (takes ?? []).filter((t) => filter === 'all' || t.starred), [takes, filter])

  return (
    <section className={s.panel}>
      <div className={s.head}>
        <h2 className={s.title}>Takes</h2>
        <SegmentedControl
          size="sm"
          value={filter}
          onValueChange={setFilter}
          segments={[
            { value: 'all', label: 'All' },
            { value: 'starred', label: 'Starred', icon: <Star /> },
          ]}
        />
      </div>
      {isLoading ? (
        <Skeleton height={72} radius={12} />
      ) : shown.length === 0 ? (
        <EmptyState
          tint="var(--hue-voice)"
          icon={<AudioLines />}
          title={filter === 'starred' ? 'No starred takes' : 'No takes yet'}
          description="Every render lands here with the voice, language, seed and settings that made it."
        />
      ) : (
        <div className={s.list}>
          <AnimatePresence initial={false}>
            {shown.map((t) => (
              <motion.div key={t.id} layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0 }}>
                <TakeRow take={t} onReuse={onReuse} lockable={lockable(t)} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </section>
  )
}

function TakeRow({ take, onReuse, lockable }: { take: VoiceTake; onReuse: (t: VoiceTake) => void; lockable: boolean }) {
  const star = useStarTake()
  const del = useDeleteTake()
  const lock = useLockTake()
  const languageName = useLanguageName()
  const meta = [
    take.profile_name ?? (take.instruct ? 'Designed' : 'Auto voice'),
    languageName(take.language),
    take.seed !== undefined ? `seed ${take.seed}` : null,
    `${take.duration_s.toFixed(1)} s`,
    `rendered in ${take.gen_time_s.toFixed(1)} s`,
  ].filter(Boolean)

  return (
    <div className={s.take}>
      <div className={s.top}>
        <p className={s.text}>{take.text}</p>
        <div className={s.actions}>
          <IconButton
            size="sm"
            label={take.starred ? 'Unstar' : 'Star'}
            active={take.starred}
            icon={<Star className={cn(take.starred && s.starred)} />}
            onClick={() => star.mutate({ id: take.id, starred: !take.starred })}
          />
          <IconButton size="sm" label="Reuse text and settings" icon={<RotateCcw />} onClick={() => onReuse(take)} />
          {lockable && (
            <IconButton
              size="sm"
              label={`Lock “${take.profile_name}” to this take`}
              icon={<Lock />}
              disabled={lock.isPending}
              onClick={() => lock.mutate({ id: take.id })}
            />
          )}
          <IconButton size="sm" variant="danger" label="Delete take" icon={<Trash2 />} onClick={() => del.mutate(take.id)} />
        </div>
      </div>
      <AudioPlayer src={take.url} color="var(--hue-voice)" compact height={30} bars={72} downloadName={`take-${take.id}.wav`} />
      <div className={s.meta}>
        <Badge size="sm">{take.engine}</Badge>
        {take.instruct && (
          <Tooltip content="Design tags">
            <Badge size="sm" tone="accent">
              {take.instruct}
            </Badge>
          </Tooltip>
        )}
        <span>{meta.join(' · ')}</span>
        <span className={s.when}>{ago(take.created_at)}</span>
      </div>
    </div>
  )
}
