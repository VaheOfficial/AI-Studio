import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronLeft, ChevronRight, Search, SearchX, Sparkles, TriangleAlert } from 'lucide-react'
import { Button, ChipGroup, EmptyState, IconButton, Input, SegmentedControl, Select, Skeleton, Spinner, Switch, cn } from '@studio/ui'
import type { HubCatalog, HubSort } from '../../api/contracts/hub'
import { useHubSearch, type RepoRef } from '../../api/hub'
import { useCatalog } from '../../api/hooks'
import type { CatalogEntry, ModelKind } from '../../api/types'
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
      <div className={s.finder}>
        <div className={s.bar}>
          <Input
            size="lg"
            iconLeft={<Search />}
            placeholder={catalog === 'ollama' ? 'Search the Ollama library…' : 'Search models — “flux”, “qwen3 gguf”, “whisper”…'}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className={s.search}
            trailing={search.isFetching ? <Spinner size={14} /> : undefined}
          />
          <SegmentedControl<HubCatalog>
            aria-label="Catalog"
            value={catalog}
            onValueChange={setCatalog}
            segments={CATALOGS.map((c) => ({ value: c.value, label: c.label }))}
          />
        </div>
        {hf && (
          <div className={s.filters}>
            <ChipGroup<TaskFilter> aria-label="Task" value={task} onValueChange={setTask} chips={TASK_CHIPS} className={s.tasks} />
            {catalog === 'hf' && <Switch checked={gguf} onCheckedChange={setGguf} label="GGUF only" />}
            <Select<HubSort> size="sm" value={sort} onValueChange={setSort} options={SORTS} className={s.sort} />
          </div>
        )}
      </div>

      {showFeatured && <Featured picks={picks} onOpen={onOpen} />}

      <section className={s.section}>
        <h2 className={s.heading}>
          {q ? (
            <>
              Results for “{q}” <span className={s.sub}>{search.isSuccess && `${results.length} models`}</span>
            </>
          ) : (
            <>
              {SORTS.find((x) => x.value === sort)!.label} on {CATALOGS.find((c) => c.value === catalog)!.label}
              <span className={s.sub}>{blurb}</span>
            </>
          )}
        </h2>
        {search.isError ? (
          <EmptyState icon={<TriangleAlert />} title="Search failed" description={search.error.message} />
        ) : search.isLoading ? (
          <div className={`${s.grid} ui-stagger`}>
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

/** The curated picks: one row to page through, or all of them as a grid. */
function Featured({ picks, onOpen }: { picks: CatalogEntry[]; onOpen: (repo: RepoRef) => void }) {
  const [all, setAll] = useState(false)
  const rail = useRef<HTMLDivElement>(null)
  // Which ends of the row have more behind them
  const [more, setMore] = useState({ before: false, after: false })
  const measure = useCallback(() => {
    const el = rail.current
    if (el) setMore({ before: el.scrollLeft > 4, after: el.scrollLeft + el.clientWidth < el.scrollWidth - 4 })
  }, [])
  useEffect(() => {
    const el = rail.current
    if (!el) return
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [measure, all, picks.length])
  const page = (direction: 1 | -1) => {
    const el = rail.current
    if (el) el.scrollBy({ left: direction * el.clientWidth * 0.85, behavior: 'smooth' })
  }
  return (
    <section className={s.section}>
      <div className={s.headRow}>
        <h2 className={s.heading}>
          <Sparkles size={15} /> Featured <span className={s.sub}>curated picks, tested on this studio</span>
        </h2>
        {!all && (
          <>
            <IconButton size="sm" label="Earlier picks" icon={<ChevronLeft />} disabled={!more.before} onClick={() => page(-1)} />
            <IconButton size="sm" label="More picks" icon={<ChevronRight />} disabled={!more.after} onClick={() => page(1)} />
          </>
        )}
        <Button size="sm" variant="ghost" onClick={() => setAll((v) => !v)}>
          {all ? 'Show less' : `Show all ${picks.length}`}
        </Button>
      </div>
      {all ? (
        <div className={s.grid}>
          {picks.map((e, i) => (
            <CatalogCard key={e.id} entry={e} index={i} onOpen={onOpen} />
          ))}
        </div>
      ) : (
        <div ref={rail} className={cn(s.shelf, more.before && s.fadeBefore, more.after && s.fadeAfter)} onScroll={measure}>
          {picks.map((e, i) => (
            <CatalogCard key={e.id} entry={e} index={i} onOpen={onOpen} />
          ))}
        </div>
      )}
    </section>
  )
}
