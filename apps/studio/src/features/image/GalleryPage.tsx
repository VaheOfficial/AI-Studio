import { useDeferredValue, useState } from 'react'
import { useNavigate } from 'react-router'
import { Images, Search, Star } from 'lucide-react'
import { Button, EmptyState, Input, SegmentedControl, Select, Skeleton, VirtualGrid, cn } from '@studio/ui'
import { useDeleteOutput } from '../../api/hooks'
import { useGallery, useStars, useToggleStar } from '../../api/image'
import { useLive } from '../../api/live'
import type { Output } from '../../api/types'
import { useImageHandoff } from './draft'
import { ImageDetail } from './ImageDetail'
import s from './GalleryPage.module.css'

type Period = 'all' | 'day' | 'week' | 'month'
const PERIOD_MS: Record<Period, number> = { all: Infinity, day: 864e5, week: 7 * 864e5, month: 30 * 864e5 }
const ALL = 'all'

export default function GalleryPage() {
  const navigate = useNavigate()
  const { data: outputs, isPending } = useGallery()
  const { data: stars = [] } = useStars()
  const star = useToggleStar()
  const del = useDeleteOutput()
  const send = useImageHandoff((st) => st.send)
  const models = useLive((st) => st.models)
  const [query, setQuery] = useState('')
  const [model, setModel] = useState(ALL)
  const [period, setPeriod] = useState<Period>('all')
  const [starredOnly, setStarredOnly] = useState(false)
  const [viewing, setViewing] = useState<Output | null>(null)
  const q = useDeferredValue(query.trim().toLowerCase())

  const all = outputs ?? []
  const starred = new Set(stars)
  // Rendering time is the reference point for the date filter
  const [now] = useState(() => Date.now())
  const shown = all.filter(
    (o) =>
      (model === ALL || o.model_id === model) &&
      (!starredOnly || starred.has(o.id)) &&
      now - new Date(o.created_at).getTime() <= PERIOD_MS[period] &&
      (!q || o.prompt.toLowerCase().includes(q)),
  )
  const modelIds = [...new Set(all.map((o) => o.model_id))]
  const nameOf = (id: string) => models.find((m) => m.id === id)?.name ?? id

  const open = (target: 'generate' | 'edit', o: Output) => {
    send(target, o)
    navigate(`/image/${target}`)
  }

  return (
    <div className={s.page}>
      <header className={s.bar}>
        <div className={s.title}>
          <Images />
          <h1>Gallery</h1>
          <span className={s.count}>{outputs ? `${shown.length} of ${all.length}` : ''}</span>
        </div>
        <div className={s.filters}>
          <Input
            size="sm"
            className={s.search}
            iconLeft={<Search size={14} />}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search prompts"
            aria-label="Search prompts"
          />
          <Select
            size="sm"
            className={s.model}
            value={model}
            onValueChange={setModel}
            options={[{ value: ALL, label: 'All models' }, ...modelIds.map((id) => ({ value: id, label: nameOf(id) }))]}
          />
          <SegmentedControl
            size="sm"
            value={period}
            onValueChange={setPeriod}
            segments={[
              { value: 'all', label: 'All time' },
              { value: 'day', label: 'Today' },
              { value: 'week', label: '7 days' },
              { value: 'month', label: '30 days' },
            ]}
          />
          <Button size="sm" variant={starredOnly ? 'primary' : 'secondary'} iconLeft={<Star />} onClick={() => setStarredOnly((v) => !v)}>
            Starred
          </Button>
        </div>
      </header>

      <div className={s.body}>
        {isPending ? (
          <div className={s.skeletons}>
            {Array.from({ length: 12 }, (_, i) => (
              <Skeleton key={i} height="100%" radius={12} />
            ))}
          </div>
        ) : shown.length === 0 ? (
          <EmptyState
            tint="var(--hue-image)"
            icon={<Images />}
            title={all.length ? 'Nothing matches these filters' : 'No images yet'}
            description={all.length ? 'Clear a filter to see more.' : 'Everything you generate or edit shows up here.'}
          />
        ) : (
          <VirtualGrid
            className={s.grid}
            items={shown}
            itemKey={(o) => o.id}
            minItemWidth={200}
            gap={10}
            renderItem={(o) => {
              const isStarred = starred.has(o.id)
              return (
                <figure className={s.tile}>
                  <img src={o.url} alt={o.prompt} loading="lazy" onClick={() => setViewing(o)} />
                  <button
                    type="button"
                    className={cn(s.star, isStarred && s.starOn)}
                    aria-label={isStarred ? 'Unstar' : 'Star'}
                    aria-pressed={isStarred}
                    onClick={() => star.mutate({ id: o.id, starred: !isStarred })}
                  >
                    <Star />
                  </button>
                  <figcaption className={s.caption} onClick={() => setViewing(o)}>
                    <span>{o.prompt}</span>
                    <small>{nameOf(o.model_id)}</small>
                  </figcaption>
                </figure>
              )
            }}
          />
        )}
      </div>

      <ImageDetail
        output={viewing}
        onClose={() => setViewing(null)}
        onReuse={(o) => open('generate', o)}
        onEdit={(o) => open('edit', o)}
        onDelete={(o) => del.mutate(o.id)}
        starred={!!viewing && starred.has(viewing.id)}
        onStar={(o, v) => star.mutate({ id: o.id, starred: v })}
      />
    </div>
  )
}
