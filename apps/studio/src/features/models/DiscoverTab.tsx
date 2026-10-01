import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Search, SearchX, Sparkles, TriangleAlert } from 'lucide-react'
import { ChipGroup, EmptyState, Input, SegmentedControl, Select, Skeleton, Spinner, Switch } from '@studio/ui'
import type { HubCatalog, HubSort } from '../../api/contracts/hub'
import { useHubSearch, type RepoRef } from '../../api/hub'
import { useCatalog } from '../../api/hooks'
import type { ModelKind } from '../../api/types'
import { CatalogCard } from './CatalogCard'
import { HubResultCard } from './HubResultCard'
import { TASK_CHIPS, type TaskFilter } from './hubMeta'
import s from './DiscoverTab.module.css'

const CATALOGS: { value: HubCatalog; label: string; blurb: string }[] = [
  { value: 'hf', label: 'Hugging Face', blurb: 'Every public model, with its GGUF, fp8 and other quantized builds.' },
  { value: 'lmstudio', label: 'LM Studio', blurb: 'LM Studio’s curated GGUF uploads (lmstudio-community) — what its in-app catalog downloads.' },
  { value: 'ollama', label: 'Ollama', blurb: 'The ollama.com library; tags are pulled straight into Ollama.' },
]

const SORTS: { value: HubSort; label: string }[] = [
  { value: 'trending', label: 'Trending' },
  { value: 'downloads', label: 'Most downloaded' },
  { value: 'likes', label: 'Most liked' },
  { value: 'updated', label: 'Recently updated' },
]

const TASK_KIND: Partial<Record<TaskFilter, ModelKind>> = {
  'text-generation': 'text',
  'image-text-to-text': 'text',
  'text-to-image': 'image',
  'image-to-image': 'image',
  'text-to-speech': 'voice',
  'audio-to-audio': 'voice',
  'automatic-speech-recognition': 'stt',
  'text-to-audio': 'music',
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

/** Unified search over Hugging Face, LM Studio's catalog and the Ollama library, with the curated picks on top. */
/** The task chip a `kind` deep link (`/models?tab=catalog&kind=image`) starts on. */
const KIND_TASK: Record<ModelKind, TaskFilter> = {
  text: 'text-generation',
  image: 'text-to-image',
  voice: 'text-to-speech',
  stt: 'automatic-speech-recognition',
  music: 'text-to-audio',
  video: 'all', // the hub's task filters have no video category yet
}

export function DiscoverTab({ initialKind, onOpen }: { initialKind: ModelKind | 'all'; onOpen: (repo: RepoRef) => void }) {
  const [catalog, setCatalog] = useState<HubCatalog>('hf')
  const [text, setText] = useState('')
  const [task, setTask] = useState<TaskFilter>(initialKind === 'all' ? 'all' : KIND_TASK[initialKind])
  const [picked, setSort] = useState<HubSort | null>(null)
  const [gguf, setGguf] = useState(false)
  const q = useDebounced(text.trim(), 350)
  // Browsing shows what's trending; a typed search finds the model itself, so the most-used repos come first
  // (trending would rank this week's remixes above the official upload)
  const sort: HubSort = picked ?? (q ? 'downloads' : 'trending')
  const hf = catalog !== 'ollama'
  const search = useHubSearch({ catalog, q, task: hf && task !== 'all' ? task : undefined, sort, gguf: catalog === 'hf' && gguf })
  const { data: featured = [] } = useCatalog()
  const picks = useMemo(
    () => featured.filter((e) => e.featured && (task === 'all' || TASK_KIND[task] === e.kind)),
    [featured, task],
  )
  const showFeatured = catalog === 'hf' && !q && picks.length > 0
  const results = search.data ?? []
  const blurb = CATALOGS.find((c) => c.value === catalog)!.blurb

  return (
    <div className={s.discover}>
      <div className={s.bar}>
        <SegmentedControl<HubCatalog>
          aria-label="Catalog"
          value={catalog}
          onValueChange={setCatalog}
          segments={CATALOGS.map((c) => ({ value: c.value, label: c.label }))}
        />
        <Input
          iconLeft={<Search />}
          placeholder={catalog === 'ollama' ? 'Search the Ollama library…' : 'Search models — “flux”, “qwen3 gguf”, “whisper”…'}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className={s.search}
          trailing={search.isFetching ? <Spinner size={14} /> : undefined}
        />
        {hf && (
          <Select<HubSort> size="sm" value={sort} onValueChange={setSort} options={SORTS} className={s.sort} />
        )}
        {catalog === 'hf' && <Switch checked={gguf} onCheckedChange={setGguf} label="GGUF only" />}
      </div>
      {hf && <ChipGroup<TaskFilter> aria-label="Task" value={task} onValueChange={setTask} chips={TASK_CHIPS} />}
      <p className={s.blurb}>{blurb}</p>

      {showFeatured && (
        <section className={s.section}>
          <h2 className={s.heading}>
            <Sparkles size={15} /> Featured <span className={s.sub}>curated picks, tested on this studio</span>
          </h2>
          <div className={s.grid}>
            {picks.map((e, i) => (
              <CatalogCard key={e.id} entry={e} index={i} onOpen={onOpen} />
            ))}
          </div>
        </section>
      )}

      <section className={s.section}>
        <h2 className={s.heading}>
          {q ? (
            <>
              Results for “{q}” <span className={s.sub}>{search.isSuccess && `${results.length} models`}</span>
            </>
          ) : (
            <>
              {SORTS.find((x) => x.value === sort)!.label} on {CATALOGS.find((c) => c.value === catalog)!.label}
            </>
          )}
        </h2>
        {search.isError ? (
          <EmptyState icon={<TriangleAlert />} title="Search failed" description={search.error.message} />
        ) : search.isLoading ? (
          <div className={s.grid}>
            {Array.from({ length: 9 }, (_, i) => (
              <Skeleton key={i} height={168} radius={16} />
            ))}
          </div>
        ) : results.length === 0 ? (
          <EmptyState icon={<SearchX />} title="No models found" description="Try another name, task or catalog." />
        ) : (
          <motion.div layout className={s.grid} data-stale={search.isPlaceholderData || undefined}>
            <AnimatePresence mode="popLayout">
              {results.map((r, i) => (
                <HubResultCard key={`${r.source}:${r.id}`} result={r} index={i} onOpen={() => onOpen({ source: r.source, id: r.id })} />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </section>
    </div>
  )
}
