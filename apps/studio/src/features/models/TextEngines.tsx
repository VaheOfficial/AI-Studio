import { CircleStop, Cpu, Download, ExternalLink, Play, Star } from 'lucide-react'
import { Badge, Button, Card, Progress, Skeleton, StatusDot } from '@studio/ui'
import { useLocalBackends } from '../../api/hub'
import { useInstallRuntime, useSettings, useStopRuntime, useUpdateSettings } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { LocalBackend } from '../../api/contracts/hub'
import { isActive } from '../../lib/jobs'
import { BACKEND_ORDER, backendState } from './hubMeta'
import s from './TextEngines.module.css'

/** The three engines that run GGUF language models, with install / start / stop and "make default". */
export function TextEngines() {
  const { data: backends, isLoading } = useLocalBackends()
  const { data: settings } = useSettings()
  if (isLoading || !backends) {
    return (
      <div className={s.grid}>
        {BACKEND_ORDER.map((id) => (
          <Skeleton key={id} height={210} radius={16} />
        ))}
      </div>
    )
  }
  return (
    <div className={s.grid}>
      {BACKEND_ORDER.map((id) => {
        const b = backends.find((x) => x.id === id)
        return b && <EngineCard key={id} backend={b} isDefault={settings?.default_local_backend === id} />
      })}
    </div>
  )
}

function EngineCard({ backend: b, isDefault }: { backend: LocalBackend; isDefault: boolean }) {
  const install = useInstallRuntime()
  const stop = useStopRuntime()
  const update = useUpdateSettings()
  const runtime = useLive((st) => st.runtimes.find((r) => r.id === b.id))
  const models = useLive((st) => st.models)
  const loaded = models.filter((m) => m.runtime === b.id && m.status === 'loaded')
  const job = useLive((st) => st.jobs.find((j) => j.kind === 'env' && j.ref === b.id && isActive(j)))
  const state = backendState(b)

  return (
    <Card padding="md" spotlight tint="var(--hue-text)" className={s.card} data-default={isDefault || undefined}>
      <div className={s.head}>
        <span className={s.icon}>
          <Cpu />
        </span>
        <div className={s.titles}>
          <h3 className={s.name}>
            {b.name}
            {isDefault && (
              <Badge size="sm" tone="accent" icon={<Star />}>
                Default
              </Badge>
            )}
          </h3>
          {b.version && <span className={s.version}>{b.version}</span>}
        </div>
        <span className={s.state}>
          <StatusDot status={state.dot} /> {state.text}
        </span>
      </div>

      {b.detail && <p className={s.detail}>{b.detail}</p>}

      <dl className={s.facts}>
        {b.endpoint && (
          <>
            <dt>Endpoint</dt>
            <dd>{b.endpoint}</dd>
          </>
        )}
        {b.models_dir && (
          <>
            <dt>Models</dt>
            <dd>{b.models_dir}</dd>
          </>
        )}
        {loaded.length > 0 && (
          <>
            <dt>In memory</dt>
            <dd>{loaded.map((m) => m.name).join(', ')}</dd>
          </>
        )}
      </dl>

      {job ? (
        <div className={s.job}>
          <Progress value={job.progress} size="xs" />
          <span className={s.jobMsg}>{job.message ?? 'Setting up…'}</span>
        </div>
      ) : (
        <div className={s.actions}>
          <Actions backend={b} running={!!runtime?.running} install={() => install.mutate(b.id)} installing={install.isPending} stop={() => stop.mutate(b.id)} stopping={stop.isPending} />
          {!isDefault && (
            <Button size="sm" variant="ghost" iconLeft={<Star />} onClick={() => update.mutate({ default_local_backend: b.id })}>
              Make default
            </Button>
          )}
        </div>
      )}
    </Card>
  )
}

function Actions({ backend: b, running, install, installing, stop, stopping }: {
  backend: LocalBackend
  running: boolean
  install: () => void
  installing: boolean
  stop: () => void
  stopping: boolean
}) {
  if (!b.installed && b.install_url) {
    return (
      <Button asChild size="sm" variant="secondary" iconRight={<ExternalLink />}>
        <a href={b.install_url} target="_blank" rel="noreferrer">
          Get {b.name}
        </a>
      </Button>
    )
  }
  if (!b.installed) {
    return (
      <Button size="sm" variant="primary" iconLeft={<Download />} loading={installing} onClick={install}>
        Install {b.name}
      </Button>
    )
  }
  if (b.id === 'llamacpp') {
    return running ? (
      <Button size="sm" variant="outline" iconLeft={<CircleStop />} loading={stopping} onClick={stop}>
        Stop & free VRAM
      </Button>
    ) : (
      <span className={s.hint}>Starts on demand when you chat with or load a GGUF model.</span>
    )
  }
  if (b.id === 'lmstudio') {
    return running ? (
      <Button size="sm" variant="outline" iconLeft={<CircleStop />} loading={stopping} onClick={stop}>
        Unload all
      </Button>
    ) : (
      <Button size="sm" variant="secondary" iconLeft={<Play />} loading={installing} onClick={install}>
        Start server
      </Button>
    )
  }
  return running ? null : (
    <Button size="sm" variant="secondary" iconLeft={<Play />} loading={installing} onClick={install}>
      Start Ollama
    </Button>
  )
}
