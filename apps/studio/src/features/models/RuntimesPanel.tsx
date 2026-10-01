import { CircleStop, Package } from 'lucide-react'
import { Badge, Button, Card, Progress, Skeleton, StatusDot } from '@studio/ui'
import { useInstallRuntime, useStopRuntime } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { RuntimeInfo } from '../../api/types'
import { isActive } from '../../lib/jobs'
import { KINDS } from '../../lib/kinds'
import { TextEngines } from './TextEngines'
import s from './RuntimesPanel.module.css'

/** Shown by <TextEngines> with their own controls. */
const TEXT_ENGINES = new Set(['lmstudio', 'llamacpp', 'ollama'])

export function RuntimesPanel() {
  const runtimes = useLive((st) => st.runtimes)
  const synced = useLive((st) => st.synced)
  if (!synced) {
    return (
      <div className={s.grid}>
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} height={150} radius={16} />
        ))}
      </div>
    )
  }
  return (
    <div className={s.sections}>
      <section>
        <h2 className={s.sectionTitle}>Language model engines</h2>
        <p className={s.intro}>
          GGUF chat models run in LM Studio, the built-in llama.cpp server or Ollama. The default engine is preselected when
          you download a GGUF from the hub; loading any model first evicts others so it gets the VRAM.
        </p>
        <TextEngines />
      </section>
      <section>
        <h2 className={s.sectionTitle}>Python runtimes</h2>
        <p className={s.intro}>
          Each runtime is an isolated Python environment with its own GPU worker process, so model families with conflicting
          dependencies never break each other. They're created on first use; you can also set them up ahead of time.
        </p>
        <div className={s.grid}>
          {runtimes
            .filter((r) => !TEXT_ENGINES.has(r.id))
            .map((r) => (
              <RuntimeCard key={r.id} runtime={r} />
            ))}
        </div>
      </section>
    </div>
  )
}

function RuntimeCard({ runtime }: { runtime: RuntimeInfo }) {
  const install = useInstallRuntime()
  const stop = useStopRuntime()
  const job = useLive((st) => st.jobs.find((j) => j.kind === 'env' && j.ref === runtime.id && isActive(j)))
  const hue = KINDS[runtime.kinds[0] ?? 'text'].hue

  return (
    <Card padding="md" className={s.card} tint={hue} spotlight>
      <div className={s.head}>
        <span className={s.icon} style={{ ['--hue' as string]: hue }}>
          <Package />
        </span>
        <div className={s.titles}>
          <h3 className={s.name}>{runtime.name}</h3>
          <div className={s.kinds}>
            {runtime.kinds.map((k) => (
              <Badge key={k} size="sm" color={KINDS[k].hue}>
                {KINDS[k].label}
              </Badge>
            ))}
          </div>
        </div>
      </div>
      <div className={s.state}>
        <span className={s.stateItem}>
          <StatusDot status={runtime.env_ready ? 'idle' : 'off'} />
          {runtime.env_ready ? 'Environment ready' : 'Not installed'}
        </span>
        <span className={s.stateItem}>
          <StatusDot status={runtime.running ? 'active' : 'off'} />
          {runtime.running ? `Running${runtime.port ? ` · :${runtime.port}` : ''}` : 'Stopped'}
        </span>
        {runtime.loaded_model && <span className={s.loaded}>Loaded: {runtime.loaded_model}</span>}
      </div>
      {job ? (
        <div className={s.job}>
          <Progress value={job.progress} size="xs" />
          <span className={s.jobMsg}>{job.message ?? 'Setting up…'}</span>
        </div>
      ) : (
        <div className={s.actions}>
          {!runtime.env_ready && runtime.id !== 'remote' && (
            <Button size="sm" variant="secondary" loading={install.isPending} onClick={() => install.mutate(runtime.id)}>
              Set up
            </Button>
          )}
          {/* Remote APIs are external services with nothing to stop */}
          {runtime.running && runtime.id !== 'remote' && (
            <Button size="sm" variant="outline" iconLeft={<CircleStop />} loading={stop.isPending} onClick={() => stop.mutate(runtime.id)}>
              Stop & free VRAM
            </Button>
          )}
        </div>
      )}
    </Card>
  )
}
