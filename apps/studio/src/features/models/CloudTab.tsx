import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import { AudioLines, Binary, Clapperboard, CloudOff, Ear, Image, KeyRound, MessageSquareText, Search } from 'lucide-react'
import { Button, EmptyState, Input, SegmentedControl, Select, Skeleton, Switch, type Segment } from '@studio/ui'
import type { CloudOutputFilter, CloudSort } from '../../api/contracts/openrouter'
import { useCloudModels, useOpenRouterAccount } from '../../api/openrouter'
import { timeAgo } from '../../lib/format'
import { CloudCard } from './CloudCard'
import s from './CloudTab.module.css'

const PAGE = 60

const OUTPUTS: Segment<CloudOutputFilter>[] = [
  { value: 'all', label: 'All' },
  { value: 'text', label: 'Text', icon: <MessageSquareText /> },
  { value: 'image', label: 'Image', icon: <Image /> },
  { value: 'speech', label: 'Speech', icon: <AudioLines /> },
  { value: 'transcription', label: 'Transcribe', icon: <Ear /> },
  { value: 'video', label: 'Video', icon: <Clapperboard /> },
  { value: 'embeddings', label: 'Embed', icon: <Binary /> },
]

const SORTS = [
  { value: 'newest', label: 'Newest' },
  { value: 'price', label: 'Cheapest' },
  { value: 'context', label: 'Longest context' },
  { value: 'name', label: 'Name' },
] satisfies { value: CloudSort; label: string }[]

/** Max USD per 1M input tokens. */
const PRICE_CAPS = [
  { value: 'any', label: 'Any price' },
  { value: '0.5', label: '≤ $0.50 /M in' },
  { value: '2', label: '≤ $2 /M in' },
  { value: '10', label: '≤ $10 /M in' },
]

const CONTEXTS = [
  { value: '0', label: 'Any context' },
  { value: '32000', label: '≥ 32K' },
  { value: '128000', label: '≥ 128K' },
  { value: '1000000', label: '≥ 1M' },
]

/** Models → Cloud: every OpenRouter model, filterable; pin one to use it in the studio. */
export function CloudTab() {
  const [output, setOutput] = useState<CloudOutputFilter>('all')
  const [q, setQ] = useState('')
  const [tools, setTools] = useState(false)
  const [free, setFree] = useState(false)
  const [pinned, setPinned] = useState(false)
  const [sort, setSort] = useState<CloudSort>('newest')
  const [priceCap, setPriceCap] = useState('any')
  const [minContext, setMinContext] = useState('0')
  const [limit, setLimit] = useState(PAGE)
  const query = useDeferredValue(q)
  const textish = output === 'all' || output === 'text'

  const { data, isLoading, error, isPlaceholderData } = useCloudModels({
    output,
    q: query,
    tools,
    free,
    pinned,
    sort,
    limit,
    maxInputPrice: textish && priceCap !== 'any' ? Number(priceCap) : undefined,
    minContext: textish ? Number(minContext) : undefined,
  })
  const { data: account } = useOpenRouterAccount()
  const resetPage = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setLimit(PAGE)
  }

  return (
    <div className={s.tab}>
      {account && !account.configured && (
        <div className={s.notice}>
          <KeyRound size={15} />
          <span>Browsing is free. To chat with or generate from a cloud model, add an OpenRouter API key and pin the model.</span>
          <Button asChild size="sm" variant="primary">
            <Link to="/settings">Add key</Link>
          </Button>
        </div>
      )}

      <SegmentedControl<CloudOutputFilter> aria-label="Output modality" size="sm" value={output} onValueChange={resetPage(setOutput)} segments={OUTPUTS} />

      <div className={s.bar}>
        <Input iconLeft={<Search />} placeholder="Search OpenRouter models…" value={q} onChange={(e) => resetPage(setQ)(e.target.value)} className={s.search} />
        <Select<CloudSort> size="sm" className={s.select} value={sort} onValueChange={setSort} options={SORTS} />
        {textish && (
          <>
            <Select size="sm" className={s.select} value={priceCap} onValueChange={resetPage(setPriceCap)} options={PRICE_CAPS} />
            <Select size="sm" className={s.select} value={minContext} onValueChange={resetPage(setMinContext)} options={CONTEXTS} />
          </>
        )}
        <Switch checked={tools} onCheckedChange={resetPage(setTools)} label="Tool calling" />
        <Switch checked={free} onCheckedChange={resetPage(setFree)} label="Free" />
        <Switch checked={pinned} onCheckedChange={resetPage(setPinned)} label="Pinned" />
      </div>

      {error ? (
        <EmptyState icon={<CloudOff />} title="OpenRouter catalog unavailable" description={error.message} />
      ) : isLoading || !data ? (
        <div className={`${s.grid} ui-stagger`}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} height={212} radius={16} />
          ))}
        </div>
      ) : data.total === 0 ? (
        <EmptyState icon={<Search />} title="No matches" description={pinned ? 'Nothing pinned with these filters yet.' : 'Try a different filter or search term.'} />
      ) : (
        <>
          <p className={s.meta}>
            {data.total} model{data.total === 1 ? '' : 's'} · catalog refreshed {timeAgo(data.fetched_at)} · prices in USD as listed by OpenRouter
          </p>
          <motion.div layout className={s.grid} data-stale={isPlaceholderData || undefined}>
            <AnimatePresence mode="popLayout">
              {data.models.map((m, i) => (
                <CloudCard key={m.id} model={m} index={i % PAGE} />
              ))}
            </AnimatePresence>
          </motion.div>
          {data.total > data.models.length && (
            <Button className={s.more} variant="secondary" loading={isPlaceholderData} onClick={() => setLimit((n) => n + PAGE)}>
              Show more ({data.total - data.models.length} left)
            </Button>
          )}
        </>
      )}
    </div>
  )
}
