import { AnimatePresence, motion } from 'motion/react'
import { Check, Download, FolderInput, Package, Sparkles, X } from 'lucide-react'
import { IconButton, Progress, cn } from '@studio/ui'
import { useCancelJob, useDismissJob } from '../api/hooks'
import type { ReactNode } from 'react'
import type { Job, JobKind } from '../api/types'
import { formatBytes, formatEta, formatSpeed } from '../lib/format'
import { isActive } from '../lib/jobs'
import s from './JobRow.module.css'

const ICON: Record<JobKind, ReactNode> = { download: <Download />, env: <Package />, generate: <Sparkles />, storage: <FolderInput /> }

export function JobRow({ job }: { job: Job }) {
  const cancel = useCancelJob()
  const dismiss = useDismissJob()
  const active = isActive(job)
  const tone = job.status === 'error' ? 'danger' : job.status === 'done' ? 'success' : 'accent'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, marginTop: 0, paddingTop: 0, paddingBottom: 0 }}
      className={cn(s.row, s[job.status])}
    >
      <span className={s.icon}>{job.status === 'done' ? <Check /> : ICON[job.kind]}</span>
      <div className={s.body}>
        <div className={s.head}>
          <span className={s.title}>{job.title}</span>
          <span className={s.pct}>
            {job.status === 'running' && job.progress >= 0 ? `${Math.round(job.progress * 100)}%` : statusLabel(job)}
          </span>
        </div>
        {active && <Progress value={job.status === 'queued' ? null : job.progress} tone={tone} size="xs" />}
        <div className={s.meta}>
          {job.status === 'error' ? (
            <span className={s.error}>{job.error ?? job.message}</span>
          ) : job.bytes_total && active ? (
            <>
              <span>
                {formatBytes(job.bytes_done)} / {formatBytes(job.bytes_total)}
              </span>
              <span>{formatSpeed(job.speed_bps)}</span>
              <span>{formatEta(job.bytes_done, job.bytes_total, job.speed_bps)}</span>
            </>
          ) : (
            job.message && <span className={s.message}>{job.message}</span>
          )}
        </div>
      </div>
      {active ? (
        <IconButton size="sm" label="Cancel" icon={<X />} onClick={() => cancel.mutate(job.id)} />
      ) : (
        <IconButton size="sm" label="Dismiss" icon={<X />} onClick={() => dismiss.mutate(job.id)} />
      )}
    </motion.div>
  )
}

function statusLabel(j: Job) {
  return { queued: 'Queued', running: 'Working', done: 'Done', error: 'Failed', cancelled: 'Cancelled' }[j.status]
}

export function JobList({ jobs, empty }: { jobs: Job[]; empty?: string }) {
  return (
    <div className={s.list}>
      <AnimatePresence initial={false}>
        {jobs.map((j) => (
          <JobRow key={j.id} job={j} />
        ))}
      </AnimatePresence>
      {jobs.length === 0 && empty && <p className={s.empty}>{empty}</p>}
    </div>
  )
}
