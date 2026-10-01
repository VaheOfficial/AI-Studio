import { Activity } from 'lucide-react'
import { Popover, ProgressRing, cn } from '@studio/ui'
import { useLive } from '../api/live'
import { JobList } from '../components/JobRow'
import { isActive } from '../lib/jobs'
import { useUI } from '../stores/ui'
import s from './JobsTray.module.css'

export function JobsTray() {
  const jobs = useLive((st) => st.jobs)
  const { jobsOpen, setJobsOpen } = useUI()
  const active = jobs.filter(isActive)
  const determinate = active.filter((j) => j.progress >= 0)
  const avg = determinate.length ? determinate.reduce((a, j) => a + j.progress, 0) / determinate.length : null

  return (
    <Popover
      open={jobsOpen}
      onOpenChange={setJobsOpen}
      align="end"
      className={s.popover}
      trigger={
        <button className={cn(s.trigger, active.length > 0 && s.busy)} aria-label="Activity">
          {active.length > 0 ? (
            <ProgressRing value={avg} size={20} stroke={2.5} />
          ) : (
            <Activity size={16} />
          )}
          {active.length > 0 && <span className={s.count}>{active.length}</span>}
        </button>
      }
    >
      <div className={s.header}>
        <span>Activity</span>
        <span className={s.sub}>{active.length ? `${active.length} running` : 'All quiet'}</span>
      </div>
      <div className={s.scroll}>
        <JobList jobs={jobs.slice(0, 30)} empty="Downloads, installs and generations show up here." />
      </div>
    </Popover>
  )
}
