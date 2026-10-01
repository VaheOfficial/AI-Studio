import { useState } from 'react'
import { Link } from 'react-router'
import { ListChecks, MessageSquareText, Play, RotateCcw, Square, Trash2 } from 'lucide-react'
import { Badge, Button, EmptyState, IconButton, Progress, Textarea, type BadgeTone } from '@studio/ui'
import type { AgentTask, PlanItem, TaskStatus } from '../../../api/contracts/workspace'
import { useCancelTask, useCreateTask, useDeleteTask, useRetryTask, useTasks } from '../../../api/workspace'
import { PlanList } from '../ToolBodies'
import s from './TasksTab.module.css'

const STATUS: Record<TaskStatus, { label: string; tone: BadgeTone }> = {
  queued: { label: 'Queued', tone: 'neutral' },
  running: { label: 'Running', tone: 'accent' },
  waiting_approval: { label: 'Needs approval', tone: 'warning' },
  succeeded: { label: 'Done', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Stopped', tone: 'neutral' },
}

/** OpenMuse `TaskCard`: status, plan progress, result/error and controls. */
function TaskCard({ task }: { task: AgentTask }) {
  const cancel = useCancelTask()
  const retry = useRetryTask()
  const remove = useDeleteTask()
  const [open, setOpen] = useState(false)
  const done = task.plan.filter((p) => p.status === 'done').length
  const active = ['queued', 'running', 'waiting_approval'].includes(task.status)
  const st = STATUS[task.status]
  return (
    <div className={s.card}>
      <button className={s.cardHead} onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={s.cardTitle}>{task.title}</span>
        <Badge tone={st.tone} size="sm" dot={active} pulse={task.status === 'running'}>
          {st.label}
        </Badge>
      </button>
      {task.plan.length > 0 && (
        <div className={s.progress}>
          <Progress value={done / task.plan.length} />
          <span>
            {done}/{task.plan.length} steps
          </span>
        </div>
      )}
      {(task.error || task.result) && !open && <p className={s.summary}>{task.error ?? task.result}</p>}
      {open && (
        <div className={s.detail}>
          <p className={s.prompt}>{task.prompt}</p>
          {task.plan.length > 0 && <PlanList items={task.plan} />}
          {task.result && <p className={s.result}>{task.result}</p>}
          {task.error && <p className={s.error}>{task.error}</p>}
        </div>
      )}
      <div className={s.actions}>
        <Button asChild size="sm" variant="ghost">
          <Link to={`/chat/${task.session_id}`}>
            <MessageSquareText size={13} /> Open chat
          </Link>
        </Button>
        <div className={s.spacer} />
        {active && <IconButton label="Stop task" icon={<Square />} size="sm" onClick={() => cancel.mutate(task.id)} />}
        {(task.status === 'failed' || task.status === 'cancelled') && (
          <IconButton label="Retry" icon={<RotateCcw />} size="sm" onClick={() => retry.mutate(task.id)} />
        )}
        {!active && <IconButton label="Remove from list" icon={<Trash2 />} size="sm" onClick={() => remove.mutate(task.id)} />}
      </div>
    </div>
  )
}

export function TasksTab({ sessionId, plan }: { sessionId: string; plan: PlanItem[] }) {
  const { data: tasks = [] } = useTasks()
  const create = useCreateTask()
  const [prompt, setPrompt] = useState('')

  const start = () => {
    if (!prompt.trim()) return
    if ('Notification' in window && Notification.permission === 'default') void Notification.requestPermission()
    create.mutate({ origin_session_id: sessionId, prompt: prompt.trim() }, { onSuccess: () => setPrompt('') })
  }

  return (
    <div className={s.tab}>
      {plan.length > 0 && (
        <section className={s.section}>
          <h3 className={s.heading}>This chat's plan</h3>
          <PlanList items={plan} />
        </section>
      )}
      <section className={s.section}>
        <h3 className={s.heading}>New background task</h3>
        <Textarea
          autoResize
          minRows={2}
          maxRows={8}
          value={prompt}
          placeholder="Describe a self-contained job. It runs in its own chat with this folder, keeps going if you close the app, and notifies you when done."
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) start()
          }}
        />
        <Button size="sm" variant="primary" iconLeft={<Play />} disabled={!prompt.trim()} loading={create.isPending} onClick={start} className={s.startBtn}>
          Start task
        </Button>
      </section>
      <section className={s.section}>
        <h3 className={s.heading}>Tasks</h3>
        {tasks.length === 0 ? (
          <EmptyState icon={<ListChecks />} title="No tasks yet" description="Start one above, or ask the agent to hand a job to a background task." />
        ) : (
          tasks.map((t) => <TaskCard key={t.id} task={t} />)
        )}
      </section>
    </div>
  )
}
