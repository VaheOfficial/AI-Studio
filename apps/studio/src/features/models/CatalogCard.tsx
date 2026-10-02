import { forwardRef } from 'react'
import { motion } from 'motion/react'
import { Check, Download, Info } from 'lucide-react'
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

/** A curated ("Featured") model: one-click install of the studio's preset variant; the card opens its hub page. */
export const CatalogCard = forwardRef<HTMLDivElement, CatalogCardProps>(function CatalogCard({ entry, index, onOpen }, ref) {
  const meta = KINDS[entry.kind]
  const install = useInstallModel()
  const job = useLive((st) => st.jobs.find((j) => j.ref === entry.id && j.kind === 'download' && isActive(j)))
  const fit = FIT[entry.fit]
  const repo = catalogRepo(entry)
  const open = repo ? () => onOpen(repo) : undefined

  return (
    <motion.div
      ref={ref}
      className={s.cell}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: Math.min(index * 0.03, 0.3), ease: [0.16, 1, 0.3, 1] }}
    >
      <Card
        spotlight
        interactive={!!open}
        tint={meta.hue}
        padding="none"
        className={s.card}
        style={{ ['--hue' as string]: meta.hue }}
        role={open ? 'button' : undefined}
        tabIndex={open ? 0 : undefined}
        aria-label={open ? `Open ${entry.name}` : undefined}
        onClick={open}
        onKeyDown={(e) => {
          if (open && e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            open()
          }
        }}
      >
        <span className={s.ghost} aria-hidden>
          {meta.icon}
        </span>
        <div className={s.top}>
          <span className={s.kind}>{meta.icon}</span>
          <div className={s.titles}>
            <h3 className={s.name} title={entry.name}>
              {entry.name}
            </h3>
            <span className={s.vendor}>
              {entry.vendor}
              {entry.params && <> · {entry.params}</>}
            </span>
          </div>
        </div>

        <p className={s.desc}>{entry.description}</p>

        {entry.notes && (
          <Tooltip content={<span className={s.noteFull}>{entry.notes}</span>}>
            <p className={s.note}>
              <Info />
              <span>{entry.notes}</span>
            </p>
          </Tooltip>
        )}

        <div className={s.footer}>
          <div className={s.stats}>
            <Tooltip content={`${formatGB(entry.size_gb)} to download · ${formatGB(entry.vram_gb)} of VRAM recommended`}>
              <span className={s.stat}>
                {formatGB(entry.size_gb)}
                <i>·</i>
                {formatGB(entry.vram_gb)} VRAM
              </span>
            </Tooltip>
            <Tooltip content={fit.hint}>
              <span className={s.fit} data-tone={fit.tone}>
                {fit.label}
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
              variant="secondary"
              className={s.install}
              iconLeft={<Download />}
              loading={install.isPending && install.variables === entry.id}
              disabled={entry.runtime === 'remote'}
              title={entry.runtime === 'remote' ? 'Use via an OpenAI-compatible endpoint in Settings' : undefined}
              onClick={(e) => {
                e.stopPropagation()
                install.mutate(entry.id)
              }}
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
