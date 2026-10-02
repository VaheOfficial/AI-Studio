import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import { AudioLines, Fingerprint, Library, Lock, Mic2, Pencil, Search, WandSparkles } from 'lucide-react'
import { AudioPlayer, Badge, Button, Card, EmptyState, IconButton, Input, Skeleton, Tabs } from '@studio/ui'
import type { VoiceProfile } from '../../api/contracts/voice'
import { useLive } from '../../api/live'
import { useLanguageName, useVoiceProfiles } from '../../api/voice'
import { GalleryView } from './GalleryView'
import { ProfileEditor } from './ProfileEditor'
import { VoiceOrb } from './VoiceOrb'
import { PageHeader } from '../../components/Page'
import s from './VoicesTab.module.css'

type Tab = 'mine' | 'presets' | 'gallery'

const speakLink = (p: VoiceProfile) => `/voice/speak?voice=${encodeURIComponent(p.id)}`

export function VoicesTab() {
  const { data: profiles, isLoading } = useVoiceProfiles()
  const models = useLive((st) => st.models)
  const languageName = useLanguageName()
  const [tab, setTab] = useState<Tab>('mine')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<string | null>(null)

  const matches = (p: VoiceProfile) => {
    const q = query.trim().toLowerCase()
    return !q || [p.name, p.instruct, p.gender, languageName(p.language), ...p.tags].some((f) => f?.toLowerCase().includes(q))
  }
  const mine = useMemo(() => (profiles ?? []).filter((p) => p.kind !== 'preset'), [profiles])
  const presets = useMemo(() => (profiles ?? []).filter((p) => p.kind === 'preset'), [profiles])
  const byModel = new Map<string, VoiceProfile[]>()
  for (const p of presets.filter(matches)) byModel.set(p.model_id ?? '', [...(byModel.get(p.model_id ?? '') ?? []), p])

  return (
    <div className={s.page}>
      <PageHeader
        hue="var(--hue-voice)"
        icon={<Library />}
        title="Voices"
        subtitle="Your cloned and designed voices, the presets that come with each engine, and a gallery to pick from."
      />
      <div className={s.toolbar}>
        <Tabs<Tab>
          variant="pill"
          value={tab}
          onValueChange={setTab}
          items={[
            { value: 'mine', label: 'My voices', badge: mine.length || undefined },
            { value: 'presets', label: 'Presets', badge: presets.length || undefined },
            { value: 'gallery', label: 'Gallery' },
          ]}
        />
        {tab !== 'gallery' && (
          <Input iconLeft={<Search />} placeholder="Search voices…" value={query} onChange={(e) => setQuery(e.target.value)} className={s.search} />
        )}
      </div>

      {tab === 'gallery' ? (
        <GalleryView />
      ) : isLoading ? (
        <div className={`${s.grid} ui-stagger`}>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height={170} radius={14} />
          ))}
        </div>
      ) : tab === 'mine' ? (
        mine.length === 0 ? (
          <EmptyState
            tint="var(--hue-voice)"
            icon={<AudioLines />}
            title="No voices of your own yet"
            description="Clone one from a short clip, design one from tags, or pick one from the gallery."
            action={
              <div className={s.emptyActions}>
                <Link to="/voice/clone">
                  <Button iconLeft={<Fingerprint />}>Clone</Button>
                </Link>
                <Link to="/voice/design">
                  <Button iconLeft={<WandSparkles />}>Design</Button>
                </Link>
                <Button variant="ghost" onClick={() => setTab('gallery')}>
                  Browse gallery
                </Button>
              </div>
            }
          />
        ) : (
          <motion.div layout className={s.grid}>
            <AnimatePresence initial={false}>
              {mine.filter(matches).map((p, i) => (
                <motion.div
                  key={p.id}
                  layout
                  initial={{ opacity: 0, scale: 0.96 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.94 }}
                  transition={{ duration: 0.3, delay: Math.min(i * 0.02, 0.25) }}
                >
                  <Card spotlight tint="var(--hue-voice)" padding="none" className={s.card}>
                    <div className={s.cardHead}>
                      <VoiceOrb seed={p.id} size={44} />
                      <div className={s.cardTitles}>
                        <span className={s.name}>{p.name}</span>
                        <span className={s.meta}>{p.instruct || languageName(p.language)}</span>
                      </div>
                      <IconButton size="sm" label="Edit voice" icon={<Pencil />} onClick={() => setEditing(p.id)} />
                    </div>
                    <div className={s.tags}>
                      <Badge size="sm" tone="accent">
                        {p.kind}
                      </Badge>
                      {p.language && <Badge size="sm">{languageName(p.language)}</Badge>}
                      {p.is_locked && (
                        <Badge size="sm" tone="success" icon={<Lock />}>
                          locked
                        </Badge>
                      )}
                      {p.tags.slice(0, 2).map((t) => (
                        <Badge key={t} size="sm">
                          {t}
                        </Badge>
                      ))}
                    </div>
                    <Sample url={p.locked_audio_url ?? p.ref_audio_url} />
                    <Link to={speakLink(p)} className={s.speak}>
                      <Button size="sm" variant="ghost" iconLeft={<Mic2 />}>
                        Speak with this voice
                      </Button>
                    </Link>
                  </Card>
                </motion.div>
              ))}
            </AnimatePresence>
          </motion.div>
        )
      ) : presets.length === 0 ? (
        <EmptyState tint="var(--hue-voice)" title="No presets" description="Install Kokoro or Chatterbox from the catalog for their built-in voices." />
      ) : (
        [...byModel].map(([modelId, list]) => (
          <section key={modelId} className={s.group}>
            <h2 className={s.groupTitle}>{models.find((m) => m.id === modelId)?.name ?? modelId}</h2>
            <div className={s.presetGrid}>
              {list.map((p) => (
                <Link key={p.id} to={speakLink(p)} className={s.preset}>
                  <VoiceOrb seed={p.id} size={30} />
                  <span className={s.cardTitles}>
                    <span className={s.name}>{p.name}</span>
                    <span className={s.meta}>{[p.gender, languageName(p.language)].filter(Boolean).join(' · ')}</span>
                  </span>
                </Link>
              ))}
            </div>
          </section>
        ))
      )}

      <ProfileEditor profile={mine.find((p) => p.id === editing) ?? null} onClose={() => setEditing(null)} />
    </div>
  )
}

function Sample({ url }: { url?: string }) {
  return url ? <AudioPlayer src={url} color="var(--hue-voice)" compact height={28} bars={48} /> : null
}
