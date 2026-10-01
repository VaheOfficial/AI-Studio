import { useSearchParams } from 'react-router'
import { Boxes, HardDrive } from 'lucide-react'
import { AnimatedNumber, SegmentedControl, TabPanel, Tabs, type Segment, type TabItem } from '@studio/ui'
import { useLocalBackends, type RepoRef } from '../../api/hub'
import { useSettings, useUpdateSettings } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { ModelKind } from '../../api/types'
import { JobList } from '../../components/JobRow'
import { isActive } from '../../lib/jobs'
import { PageBody, PageHeader } from '../../components/Page'
import { formatBytes } from '../../lib/format'
import { KINDS, KIND_ORDER } from '../../lib/kinds'
import { CloudTab } from './CloudTab'
import { DefaultBackendPicker } from './DefaultBackendPicker'
import { DiscoverTab } from './DiscoverTab'
import { InstalledList } from './InstalledList'
import { ModelDetailSheet } from './ModelDetailSheet'
import { RuntimesPanel } from './RuntimesPanel'
import s from './ModelsPage.module.css'

/** `tab` URL values; "catalog" is the Discover tab (kept so existing `/models?tab=catalog&kind=…` links work). */
type Tab = 'installed' | 'catalog' | 'cloud' | 'runtimes' | 'downloads'
type KindFilter = ModelKind | 'all'

const KIND_SEGMENTS: Segment<KindFilter>[] = [
  { value: 'all', label: 'All' },
  ...KIND_ORDER.map((k) => ({ value: k, label: KINDS[k].label === 'Speech-to-text' ? 'STT' : KINDS[k].label, icon: KINDS[k].icon })),
]

/** `open` URL param of the detail sheet: "<source>:<repo id>", e.g. "hf:city96/FLUX.1-dev-gguf". */
function parseRepo(value: string | null): RepoRef | null {
  const [source, ...rest] = (value ?? '').split(':')
  const id = rest.join(':')
  return (source === 'hf' || source === 'ollama') && id ? { source, id } : null
}

export default function ModelsPage() {
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'installed'
  const kind = (params.get('kind') as KindFilter) || 'all'
  const setParam = (k: string, v: string | null) =>
    setParams(
      (p) => {
        if (v === null) p.delete(k)
        else p.set(k, v)
        return p
      },
      { replace: k !== 'open' }, // opening a model is a history entry, so Back closes the sheet
    )
  const openRepo = (r: RepoRef) => setParam('open', `${r.source}:${r.id}`)

  const synced = useLive((st) => st.synced)
  const models = useLive((st) => st.models)
  const jobs = useLive((st) => st.jobs)
  const system = useLive((st) => st.system)
  const activeDownloads = jobs.filter((j) => isActive(j) && j.kind !== 'generate')
  const totalBytes = models.reduce((a, m) => a + m.size_bytes, 0)

  const tabs: TabItem<Tab>[] = [
    { value: 'installed', label: 'Installed', badge: synced ? <span className={s.count}>{models.length}</span> : undefined },
    { value: 'catalog', label: 'Discover' },
    { value: 'cloud', label: 'Cloud' },
    { value: 'runtimes', label: 'Runtimes' },
    {
      value: 'downloads',
      label: 'Activity',
      badge: activeDownloads.length ? <span className={s.countLive}>{activeDownloads.length}</span> : undefined,
    },
  ]

  return (
    <PageBody wide>
      <PageHeader
        icon={<Boxes />}
        title="Models"
        subtitle="Find any model on Hugging Face, LM Studio or Ollama — in the exact quantization you want — then run, switch and remove it. Everything runs on this machine."
        actions={
          <div className={s.storage}>
            <HardDrive size={15} />
            {synced && (
              <span>
                <AnimatedNumber value={models.length} /> installed · {formatBytes(totalBytes)}
              </span>
            )}
            {system && <span className={s.free}>{formatBytes(system.disk_free, 0)} free</span>}
          </div>
        }
      />

      <Tabs<Tab> value={tab} onValueChange={(v) => setParam('tab', v)} items={tabs}>
        <div className={s.toolbar}>
          {tab === 'installed' && (
            <>
              <SegmentedControl<KindFilter>
                aria-label="Filter by kind"
                value={kind}
                onValueChange={(v) => setParam('kind', v)}
                segments={KIND_SEGMENTS}
              />
              <DefaultEngine />
            </>
          )}
        </div>
        <TabPanel value="installed">
          <InstalledList kind={kind} onBrowse={() => setParam('tab', 'catalog')} />
        </TabPanel>
        <TabPanel value="catalog">
          <DiscoverTab initialKind={kind} onOpen={openRepo} />
        </TabPanel>
        <TabPanel value="cloud">
          <CloudTab />
        </TabPanel>
        <TabPanel value="runtimes">
          <RuntimesPanel />
        </TabPanel>
        <TabPanel value="downloads">
          <div className={s.activity}>
            <JobList jobs={jobs.filter((j) => j.kind !== 'generate')} empty="No downloads or installs yet." />
          </div>
        </TabPanel>
      </Tabs>

      <ModelDetailSheet repo={parseRepo(params.get('open'))} onOpenRepo={openRepo} onClose={() => setParam('open', null)} />
    </PageBody>
  )
}

/** Switch the engine GGUF chat models install to and run on by default. */
function DefaultEngine() {
  const { data: settings } = useSettings()
  const { data: backends = [] } = useLocalBackends()
  const update = useUpdateSettings()
  if (!settings) return null
  return (
    <div className={s.engine}>
      <span className={s.engineLabel}>Default engine</span>
      <DefaultBackendPicker
        size="sm"
        value={settings.default_local_backend}
        onValueChange={(v) => update.mutate({ default_local_backend: v })}
        backends={backends}
      />
    </div>
  )
}
