import { useState } from 'react'
import { Check, Download, Layers, Sparkles, X } from 'lucide-react'
import { Badge, Button, IconButton, Progress, Select, Tooltip } from '@studio/ui'
import { useInstallVariant } from '../../api/hub'
import { useCancelJob } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { HubFit, HubRepo, HubVariant, LocalBackend } from '../../api/contracts/hub'
import type { LocalBackendId, RuntimeId, TextEncoderMode } from '../../api/types'
import { formatBytes, formatSpeed } from '../../lib/format'
import { isActive } from '../../lib/jobs'
import { FIT, FORMAT_LABEL } from './hubMeta'
import s from './ModelDetailSheet.module.css'

const LOCAL_BACKENDS: RuntimeId[] = ['lmstudio', 'llamacpp', 'ollama']

/** Why a runtime can't take an install right now, or undefined when it can. */
function unavailable(runtime: RuntimeId, backends: LocalBackend[]): string | undefined {
  const b = backends.find((x) => x.id === runtime)
  if (!b || b.installed) return undefined
  return `${b.name} isn't installed on this machine`
}

export interface VariantRowProps {
  repo: HubRepo
  variant: HubVariant
  backends: LocalBackend[]
  defaultBackend: LocalBackendId
  runtimeNames: Record<string, string>
  /** Memory estimate and fit to show: the variant's own, or the ones for the chosen text-encoder mode. */
  fit?: HubFit
  /** Whether this is the pick to highlight (it depends on the text-encoder mode); defaults to the variant's flag. */
  recommended?: boolean
  /** How the text encoder will be held when this variant is installed (image pipelines). */
  textEncoder?: TextEncoderMode
}

export function VariantRow({ repo, variant: v, backends, defaultBackend, runtimeNames, fit: shown, recommended, textEncoder }: VariantRowProps) {
  const install = useInstallVariant()
  const cancel = useCancelJob()
  const job = useLive((st) => st.jobs.find((j) => j.ref === v.ref && j.kind === 'download' && isActive(j)))
  const installedOn = useLive((st) => st.models.find((m) => m.id === v.installed_id)?.runtime)
  const choosable = v.runtimes.filter((r) => LOCAL_BACKENDS.includes(r))
  const preferred: RuntimeId | undefined =
    (v.runtimes.includes(defaultBackend) && !unavailable(defaultBackend, backends) ? defaultBackend : undefined) ??
    v.runtimes.find((r) => !unavailable(r, backends))
  const [picked, setPicked] = useState<RuntimeId | undefined>()
  const runtime = picked ?? preferred
  const blocked = runtime ? unavailable(runtime, backends) : (v.note ?? 'No local runtime can load this variant')
  const need = shown ?? { vram_gb: v.vram_gb, fit: v.fit }
  const fit = FIT[need.fit]
  const pick = recommended ?? !!v.recommended
  const total = v.size_bytes + (v.companions?.size_bytes ?? 0)
  const name = (r: RuntimeId) => runtimeNames[r] ?? r

  return (
    <div className={s.variant} data-recommended={pick || undefined} data-installed={!!v.installed_id || undefined}>
      <div className={s.variantMain}>
        <div className={s.variantTitle}>
          <span className={s.variantLabel}>{v.label}</span>
          {pick && (
            <Badge size="sm" tone="accent" icon={<Sparkles />}>
              Recommended
            </Badge>
          )}
          <Badge size="sm" tone={v.format === 'gguf' ? 'accent' : 'neutral'}>
            {FORMAT_LABEL[v.format]}
            {v.quant && v.quant !== v.label ? ` · ${v.quant}` : ''}
          </Badge>
        </div>
        {v.companions && (
          <span className={s.companions}>
            <Layers size={12} />
            <span>
              + {formatBytes(v.companions.size_bytes)} of text encoders, VAE & configs from <span className={s.mono}>{v.companions.repo}</span>
              {v.companions.gated && ' (gated)'}
            </span>
          </span>
        )}
        {v.note && <p className={s.variantNote}>{v.note}</p>}
      </div>

      <div className={s.variantSize}>
        <span className={s.sizeMain}>{formatBytes(total)}</span>
        <Tooltip content={`${fit.hint} Estimated ${need.vram_gb.toFixed(1)} GB to run fully on GPU${textEncoder && textEncoder !== 'full' ? ` with the text encoder in ${textEncoder === '8bit' ? '8' : '4'} bits` : ''}.`}>
          <span>
            <Badge size="sm" tone={fit.tone} dot>
              {fit.label}
            </Badge>
          </span>
        </Tooltip>
      </div>

      <div className={s.variantRuntime}>
        {installedOn ? (
          <Badge size="sm" tone="success">
            {name(installedOn)}
          </Badge>
        ) : choosable.length > 1 ? (
          <Select<RuntimeId>
            size="sm"
            value={runtime}
            onValueChange={setPicked}
            options={choosable.map((r) => ({ value: r, label: name(r), description: unavailable(r, backends), disabled: !!unavailable(r, backends) }))}
          />
        ) : v.runtimes.length ? (
          <div className={s.runtimeChips}>
            {v.runtimes.map((r) => (
              <Badge key={r} size="sm">
                {name(r)}
              </Badge>
            ))}
          </div>
        ) : (
          <Badge size="sm" tone="danger">
            No local runtime
          </Badge>
        )}
      </div>

      <div className={s.variantAction}>
        {v.installed_id ? (
          <Badge tone="success" icon={<Check />}>
            Installed
          </Badge>
        ) : job ? (
          <div className={s.jobState}>
            <div className={s.jobText}>
              <span className={s.pct}>{job.progress >= 0 ? `${Math.round(job.progress * 100)}%` : 'Starting…'}</span>
              <span className={s.speed}>{formatSpeed(job.speed_bps)}</span>
              <IconButton size="sm" label="Cancel download" icon={<X />} onClick={() => cancel.mutate(job.id)} />
            </div>
            <Progress value={job.status === 'queued' ? null : job.progress} size="xs" />
          </div>
        ) : (
          <Tooltip content={blocked ?? `Download ${formatBytes(total)}${runtime ? ` to run with ${name(runtime)}` : ''}`}>
            <span>
              <Button
                size="sm"
                variant={pick ? 'primary' : 'secondary'}
                iconLeft={<Download />}
                disabled={!!blocked}
                loading={install.isPending}
                onClick={() => install.mutate({ source: repo.source, repo: repo.id, variant: v.id, runtime, text_encoder: textEncoder })}
              >
                Download
              </Button>
            </span>
          </Tooltip>
        )}
      </div>
    </div>
  )
}
