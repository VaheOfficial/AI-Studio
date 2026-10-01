import { useEffect, useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { Button, ChipGroup, EmptyState, Input, Select, Skeleton, Switch } from '@studio/ui'
import type { ArchetypeFilters } from '../../api/contracts/voice'
import { useArchetypes, useDesignVocabulary } from '../../api/voice'
import { ArchetypeCard } from './ArchetypeCard'
import s from './GalleryView.module.css'

const ANY = 'any'
const LANGUAGES = [
  ['en', 'English'],
  ['zh', 'Chinese'],
  ['es', 'Spanish'],
  ['fr', 'French'],
  ['de', 'German'],
  ['it', 'Italian'],
  ['pt', 'Portuguese'],
  ['ru', 'Russian'],
  ['hi', 'Hindi'],
  ['ja', 'Japanese'],
  ['ko', 'Korean'],
] as const

/** The archetype gallery: 1,100+ designed voices — filter, preview, add to your voices. */
export function GalleryView() {
  const { data: vocab } = useDesignVocabulary()
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [useCase, setUseCase] = useState(ANY)
  const [facets, setFacets] = useState<Record<string, string>>({})
  const [whisper, setWhisper] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250)
    return () => clearTimeout(t)
  }, [search])

  const filters = useMemo<ArchetypeFilters>(() => {
    const pick = (k: string) => (facets[k] && facets[k] !== ANY ? facets[k] : undefined)
    return {
      q: q || undefined,
      use_case: useCase === ANY ? undefined : useCase,
      gender: pick('gender'),
      age: pick('age'),
      pitch: pick('pitch'),
      accent: pick('accent'),
      language: pick('language'),
      whisper: whisper || undefined,
    }
  }, [q, useCase, facets, whisper])
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useArchetypes(filters)
  const items = data?.pages.flatMap((p) => p.items) ?? []
  const total = data?.pages[0]?.total ?? 0

  const options = (category: string) => vocab?.categories.find((c) => c.id === category)?.options ?? []
  const facet = (key: string, label: string, values: readonly (readonly [string, string])[]) => (
    <Select
      size="sm"
      value={facets[key] ?? ANY}
      onValueChange={(v) => setFacets((f) => ({ ...f, [key]: v }))}
      options={[{ value: ANY, label: `Any ${label.toLowerCase()}` }, ...values.map(([value, text]) => ({ value, label: text }))]}
    />
  )
  const pairs = (xs: string[]) => xs.map((x) => [x, x] as const)

  return (
    <div className={s.gallery}>
      <div className={s.filters}>
        <Input iconLeft={<Search />} placeholder="Search voices, tags…" value={search} onChange={(e) => setSearch(e.target.value)} className={s.search} />
        {facet('gender', 'Gender', pairs(options('Gender')))}
        {facet('age', 'Age', pairs(options('Age')))}
        {facet('pitch', 'Pitch', pairs(options('Pitch')))}
        {facet('accent', 'Accent', pairs([...options('EnglishAccent'), ...options('ChineseDialect')]))}
        {facet('language', 'Language', LANGUAGES)}
        <Switch checked={whisper} onCheckedChange={setWhisper} label="Whisper" />
      </div>
      {vocab && (
        <ChipGroup
          aria-label="Use case"
          value={useCase}
          onValueChange={setUseCase}
          chips={[{ value: ANY, label: 'All' }, ...vocab.use_cases.map((u) => ({ value: u.id, label: u.name }))].map((c) => ({
            ...c,
            color: 'var(--hue-voice)',
          }))}
        />
      )}
      <p className={s.count}>{isLoading ? 'Loading…' : `${total.toLocaleString()} voices`}</p>
      {isLoading ? (
        <div className={s.grid}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} height={150} radius={12} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState tint="var(--hue-voice)" title="No voices match" description="Loosen a filter or clear the search." />
      ) : (
        <div className={s.grid}>
          {items.map((a) => (
            <ArchetypeCard key={a.id} archetype={a} />
          ))}
        </div>
      )}
      {hasNextPage && (
        <Button variant="secondary" className={s.more} loading={isFetchingNextPage} onClick={() => void fetchNextPage()}>
          Load more
        </Button>
      )}
    </div>
  )
}
