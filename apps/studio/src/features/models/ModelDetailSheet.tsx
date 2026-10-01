import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Boxes, ChevronRight, Clock, Download, ExternalLink, FileText, GitBranch, Heart, KeyRound, Lock, TriangleAlert } from 'lucide-react'
import { Badge, Button, EmptyState, SegmentedControl, Sheet, Skeleton } from '@studio/ui'
import { useHubRepo, useLocalBackends, type RepoRef } from '../../api/hub'
import { useSettings } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { HubRepo } from '../../api/contracts/hub'
import { formatBytes, formatCount, timeAgo } from '../../lib/format'
import { KINDS } from '../../lib/kinds'
import { MASK } from '../settings/form'
import { FORMAT_LABEL, isNonCommercial } from './hubMeta'
import { VariantRow } from './VariantRow'
import s from './ModelDetailSheet.module.css'

export interface ModelDetailSheetProps {
  repo: RepoRef | null
  onOpenRepo: (repo: RepoRef) => void
  onClose: () => void
}

/** A model's hub page: card summary, every installable variant with size / fit / runtimes, related quantized builds. */
export function ModelDetailSheet({ repo, onOpenRepo, onClose }: ModelDetailSheetProps) {
  const { data, isLoading, error } = useHubRepo(repo)
  const meta = data?.kind ? KINDS[data.kind] : undefined
  const hue = meta?.hue ?? 'var(--accent)'
  const name = data?.name ?? repo?.id.split('/').pop() ?? ''

  return (
    <Sheet
      open={!!repo}
      onOpenChange={(o) => !o && onClose()}
      icon={
        <span className={s.kind} style={{ ['--hue' as string]: hue }}>
          {meta?.icon ?? <Boxes />}
        </span>
      }
      title={name}
      description={repo ? `${repo.source === 'ollama' ? 'Ollama library' : 'Hugging Face'} · ${repo.id}` : undefined}
      actions={
        data && (
          <Button asChild size="sm" variant="ghost" iconRight={<ExternalLink />}>
            <a href={data.url} target="_blank" rel="noreferrer">
              {data.source === 'ollama' ? 'ollama.com' : 'huggingface.co'}
            </a>
          </Button>
        )
      }
    >
      {isLoading ? (
        <div className={s.loading}>
          <Skeleton height={20} width="60%" />
          <Skeleton height={64} radius={12} />
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} height={58} radius={12} />
          ))}
        </div>
      ) : error ? (
        <EmptyState icon={<TriangleAlert />} title="Couldn't load this model" description={error.message} />
      ) : (
        data && <RepoDetail repo={data} onOpenRepo={onOpenRepo} />
      )}
    </Sheet>
  )
}

type VariantFilter = 'all' | 'fits'

function RepoDetail({ repo, onOpenRepo }: { repo: HubRepo; onOpenRepo: (r: RepoRef) => void }) {
  const { data: settings } = useSettings()
  const { data: backends = [] } = useLocalBackends()
  const runtimes = useLive((st) => st.runtimes)
  const runtimeNames = useMemo(() => Object.fromEntries(runtimes.map((r) => [r.id, r.name])), [runtimes])
  const [filter, setFilter] = useState<VariantFilter>('all')
  const variants = repo.variants.filter((v) => filter === 'all' || v.fit === 'yes')
  const gatedRepos = [...new Set([...(repo.gated ? [repo.id] : []), ...repo.variants.filter((v) => v.companions?.gated).map((v) => v.companions!.repo)])]
  const hasToken = settings?.hf_token === MASK
  const totalFiles = repo.files.reduce((a, f) => a + f.size, 0)

  return (
    <div className={s.detail}>
      <div className={s.stats}>
        {repo.downloads != null && (
          <span className={s.stat}>
            <Download size={13} /> {formatCount(repo.downloads)} {repo.source === 'ollama' ? 'pulls' : 'downloads'}
          </span>
        )}
        {repo.likes != null && (
          <span className={s.stat}>
            <Heart size={13} /> {formatCount(repo.likes)}
          </span>
        )}
        {repo.updated_at && (
          <span className={s.stat}>
            <Clock size={13} /> updated {timeAgo(repo.updated_at)}
          </span>
        )}
        {repo.license && (
          <Badge size="sm" tone={isNonCommercial(repo.license) ? 'warning' : 'neutral'}>
            {repo.license}
            {isNonCommercial(repo.license) && ' · non-commercial use only'}
          </Badge>
        )}
        {repo.tags.slice(0, 6).map((t) => (
          <span key={t} className={s.tag}>
            {t}
          </span>
        ))}
      </div>

      {gatedRepos.length > 0 && (
        <div className={s.callout} data-tone="warning">
          <Lock size={15} />
          <div>
            <strong>Gated download.</strong> Accept the terms of{' '}
            {gatedRepos.map((r, i) => (
              <span key={r}>
                {i > 0 && ' and '}
                <a href={`https://huggingface.co/${r}`} target="_blank" rel="noreferrer">
                  {r}
                </a>
              </span>
            ))}{' '}
            on huggingface.co with your account.{' '}
            {hasToken ? (
              'Your HF token is set, so downloads will work once access is granted.'
            ) : (
              <>
                Then add a read token in <Link to="/settings">Settings → Hugging Face</Link>.
              </>
            )}
          </div>
          {!hasToken && <KeyRound size={15} className={s.calloutIcon} />}
        </div>
      )}

      {repo.summary && <p className={s.summary}>{repo.summary}</p>}

      {repo.base_models.length > 0 && (
        <div className={s.baseModels}>
          <GitBranch size={13} />
          <span>Based on</span>
          {repo.base_models.map((b) => (
            <button key={b} type="button" className={s.linkChip} onClick={() => onOpenRepo({ source: 'hf', id: b })}>
              {b}
            </button>
          ))}
        </div>
      )}

      <section className={s.section}>
        <div className={s.sectionHead}>
          <h3 className={s.sectionTitle}>
            Variants <span className={s.count}>{repo.variants.length}</span>
          </h3>
          <SegmentedControl<VariantFilter>
            size="sm"
            value={filter}
            onValueChange={setFilter}
            segments={[
              { value: 'all', label: 'All' },
              { value: 'fits', label: 'Fits my GPU' },
            ]}
          />
        </div>
        {variants.length === 0 ? (
          <p className={s.empty}>
            {repo.variants.length ? 'No variant fits entirely in GPU memory — switch to All to see offload options.' : 'This repo has no files the studio can install.'}
          </p>
        ) : (
          <div className={s.variants}>
            {variants.map((v) => (
              <VariantRow
                key={v.id}
                repo={repo}
                variant={v}
                backends={backends}
                defaultBackend={settings?.default_local_backend ?? 'llamacpp'}
                runtimeNames={runtimeNames}
              />
            ))}
          </div>
        )}
      </section>

      {repo.related.length > 0 && (
        <section className={s.section}>
          <h3 className={s.sectionTitle}>
            Quantized builds <span className={s.count}>{repo.related.length}</span>
          </h3>
          <div className={s.related}>
            {repo.related.map((r) => (
              <button key={r.id} type="button" className={s.relatedRow} onClick={() => onOpenRepo({ source: r.source, id: r.id })}>
                <span className={s.relatedName}>
                  <span>{r.name}</span>
                  <span className={s.relatedAuthor}>{r.author}</span>
                </span>
                <span className={s.relatedMeta}>
                  {r.formats.map((f) => (
                    <Badge key={f} size="sm" tone={f === 'gguf' ? 'accent' : 'neutral'}>
                      {FORMAT_LABEL[f]}
                    </Badge>
                  ))}
                  <span className={s.stat}>
                    <Download size={12} /> {formatCount(r.downloads)}
                  </span>
                  <ChevronRight size={14} />
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {repo.files.length > 0 && (
        <details className={s.files}>
          <summary>
            <FileText size={13} /> {repo.files.length} files · {formatBytes(totalFiles)}
          </summary>
          <ul>
            {repo.files.map((f) => (
              <li key={f.path}>
                <span className={s.filePath}>{f.path}</span>
                <span className={s.fileSize}>{formatBytes(f.size)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
