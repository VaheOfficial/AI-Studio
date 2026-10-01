import { forwardRef } from 'react'
import { motion } from 'motion/react'
import { ChevronRight, Check, Cpu, Download, HardDrive, TriangleAlert } from 'lucide-react'
import { Badge, Button, Card, Progress, Tooltip } from '@studio/ui'
import type { RepoRef } from '../../api/hub'
import { useInstallModel } from '../../api/hooks'
import { useLive } from '../../api/live'
import type { CatalogEntry } from '../../api/types'
import { isActive } from '../../lib/jobs'
import { formatGB } from '../../lib/format'
import { KINDS } from '../../lib/kinds'
import { FIT, catalogRepo } from './hubMeta'
import s from './CatalogCard.module.css'

export interface CatalogCardProps {
  entry: CatalogEntry
  index: number
  onOpen: (repo: RepoRef) => void
}

/** A curated ("Featured") model: one-click install of the studio's preset variant, or open its hub page. */
export const CatalogCard = forwardRef<HTMLDivElement, CatalogCardProps>(function CatalogCard({ entry, index, onOpen }, ref) {
  const meta = KINDS[entry.kind]
  const install = useInstallModel()
  const job = useLive((st) => st.jobs.find((j) => j.ref === entry.id && j.kind === 'download' && isActive(j)))
  const fit = FIT[entry.fit]
  const repo = catalogRepo(entry)

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.35, delay: Math.min(index * 0.03, 0.3), ease: [0.16, 1, 0.3, 1] }}
    >
      <Card spotlight tint={meta.hue} padding="none" className={s.card}>
        <div className={s.top}>
          <span className={s.kind} style={{ ['--hue' as string]: meta.hue }}>
            {meta.icon}
          </span>
          <div className={s.titles}>
            <div className={s.nameRow}>
              <h3 className={s.name}>{entry.name}</h3>
              {entry.featured && (
                <Badge size="sm" tone="accent">
                  Featured
                </Badge>
              )}
            </div>
            <span className={s.vendor}>
              {entry.vendor}
              {entry.params && <> · {entry.params}</>}
            </span>
          </div>
          {repo && (
            <Tooltip content="All variants & files">
              <button type="button" className={s.link} onClick={() => onOpen(repo)} aria-label={`Open ${entry.name}`}>
                <ChevronRight size={15} />
              </button>
            </Tooltip>
          )}
        </div>

        <p className={s.desc}>{entry.description}</p>

        {entry.notes && (
          <div className={s.notes}>
            <TriangleAlert size={13} />
            <span>{entry.notes}</span>
          </div>
        )}

        <div className={s.tags}>
          {entry.tags.slice(0, 4).map((t) => (
            <span key={t} className={s.tag}>
              {t}
            </span>
          ))}
        </div>

        <div className={s.footer}>
          <div className={s.stats}>
            <Tooltip content="Download size">
              <span className={s.stat}>
                <HardDrive size={13} />
                {formatGB(entry.size_gb)}
              </span>
            </Tooltip>
            <Tooltip content="Recommended VRAM">
              <span className={s.stat}>
                <Cpu size={13} />
                {formatGB(entry.vram_gb)}
              </span>
            </Tooltip>
            <Tooltip content={fit.hint}>
              <span>
                <Badge size="sm" tone={fit.tone} dot>
                  {fit.label}
                </Badge>
              </span>
            </Tooltip>
          </div>
          {entry.installed ? (
            <Badge tone="success" icon={<Check />}>
              Installed
            </Badge>
          ) : job ? (
            <span className={s.pct}>{job.progress >= 0 ? `${Math.round(job.progress * 100)}%` : 'Starting…'}</span>
          ) : (
            <Button
              size="sm"
              variant={entry.fit === 'no' ? 'ghost' : 'primary'}
              iconLeft={<Download />}
              loading={install.isPending && install.variables === entry.id}
              disabled={entry.runtime === 'remote'}
              title={entry.runtime === 'remote' ? 'Use via an OpenAI-compatible endpoint in Settings' : undefined}
              onClick={() => install.mutate(entry.id)}
            >
              {entry.runtime === 'remote' ? 'Remote only' : 'Install'}
            </Button>
          )}
        </div>
        {job && (
          <div className={s.progress}>
            <Progress value={job.status === 'queued' ? null : job.progress} size="xs" />
          </div>
        )}
      </Card>
    </motion.div>
  )
})
