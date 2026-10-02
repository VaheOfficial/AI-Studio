import { useState } from 'react'
import { useNavigate } from 'react-router'
import { AlarmClock, Bell, MessageSquareText, Pencil, Play, Plus, Radar, Trash2 } from 'lucide-react'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Dialog,
  EmptyState,
  Field,
  IconButton,
  Input,
  SegmentedControl,
  Select,
  Switch,
  Textarea,
  cn,
} from '@studio/ui'
import {
  useAutomations,
  useCreateAutomation,
  useDeleteAutomation,
  useRunAutomation,
  useUpdateAutomation,
} from '../../api/automations'
import type { Automation, AutomationTiming } from '../../api/contracts/automations'
import { useChatModels, useSettings } from '../../api/hooks'
import { PageBody, PageHeader } from '../../components/Page'
import { WEEKDAYS, defaultSchedule, fromVevent, relative, toVevent, type Repeat, type ScheduleForm, type Weekday } from './schedule'
import s from './AutomationsPage.module.css'

const STATUS: Record<NonNullable<Automation['last_status']>, { label: string; tone: 'success' | 'neutral' | 'warning' | 'danger' }> = {
  reported: { label: 'Reported', tone: 'success' },
  quiet: { label: 'Nothing new', tone: 'neutral' },
  needs_approval: { label: 'Needs approval', tone: 'warning' },
  error: { label: 'Failed', tone: 'danger' },
}

const CHECK_EXAMPLE = `# Prints one line per item that matters right now, with a stable id first.
# A line that was not printed before wakes the assistant.
import requests

feed = requests.get("https://example.com/feed.json", timeout=30).json()
for item in feed["items"]:
    if item["score"] >= 9:
        print(item["id"], "|", item["score"], "|", item["title"])
`

/**
 * Prompts the assistant runs on a schedule (reminders, recurring summaries, condition watches) or when a trigger's
 * check finds something new.
 */
export default function AutomationsPage() {
  const { data: automations = [], isLoading } = useAutomations()
  const [editing, setEditing] = useState<Automation | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Automation | null>(null)
  const del = useDeleteAutomation()
  const [permission, setPermission] = useState(() => ('Notification' in window ? Notification.permission : 'denied'))

  return (
    <PageBody>
      <PageHeader
        icon={<AlarmClock />}
        title="Automations"
        subtitle="Prompts the assistant runs for you on a schedule, or whenever a trigger finds something new. Each one posts its results in a chat (the one you asked in, or its own when created here) and notifies you. You can also just ask in a chat: “every morning, summarize the AI news”, “whenever a new release appears, tell me what changed”."
        actions={
          <Button variant="primary" iconLeft={<Plus />} onClick={() => setEditing('new')}>
            New automation
          </Button>
        }
      />
      {permission === 'default' && (
        <div className={s.banner}>
          <Bell size={15} />
          <span>Get a desktop notification when an automation reports while this window is in the background.</span>
          <Button size="sm" variant="secondary" onClick={() => void Notification.requestPermission().then(setPermission)}>
            Turn on
          </Button>
        </div>
      )}
      {!isLoading && automations.length === 0 ? (
        <EmptyState
          icon={<AlarmClock />}
          title="No automations yet"
          description="Reminders, daily briefings, “tell me when…” watches, triggers that wake the assistant when something new shows up. Create one here or ask the assistant in an Agent chat."
          action={
            <Button variant="primary" iconLeft={<Plus />} onClick={() => setEditing('new')}>
              New automation
            </Button>
          }
        />
      ) : (
        <div className={`${s.list} ui-stagger`}>
          {automations.map((a) => (
            <AutomationCard key={a.id} a={a} onEdit={() => setEditing(a)} onDelete={() => setDeleting(a)} />
          ))}
        </div>
      )}
      {editing && <AutomationEditor automation={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete “${deleting?.title}”?`}
        description="It stops running. Its chat with the earlier results stays in your chat list."
        confirmLabel="Delete"
        tone="danger"
        onConfirm={() => {
          if (deleting) del.mutate(deleting.id)
          setDeleting(null)
        }}
      />
    </PageBody>
  )
}

function AutomationCard({ a, onEdit, onDelete }: { a: Automation; onEdit: () => void; onDelete: () => void }) {
  const navigate = useNavigate()
  const update = useUpdateAutomation()
  const run = useRunAutomation()
  const status = a.last_status ? STATUS[a.last_status] : undefined
  const trigger = a.timing_mode === 'trigger'
  const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  return (
    <Card padding="none" spotlight className={cn(s.card, !a.enabled && s.paused)}>
      <div className={s.cardHead}>
        <span className={s.icon}>{trigger ? <Radar size={16} /> : <AlarmClock size={16} />}</span>
        <div className={s.titles}>
          <span className={s.title}>{a.title}</span>
          <span className={s.schedule}>
            {a.schedule_text}
            {a.timing_mode === 'condition_watch' && <Badge size="sm">Watch</Badge>}
            {trigger && <Badge size="sm">Trigger</Badge>}
          </span>
        </div>
        <Switch checked={a.enabled} onCheckedChange={(on) => update.mutate({ id: a.id, enabled: on })} aria-label={a.enabled ? 'Pause' : 'Resume'} />
      </div>
      <p className={s.prompt}>{a.prompt}</p>
      <div className={s.meta}>
        {trigger ? (
          <>
            <span>Next check: {a.enabled ? relative(a.next_run) : 'paused'}</span>
            {a.last_check && (
              <span>
                Checked: {when(a.last_check)}
                {a.check_error && (
                  <Badge size="sm" tone="danger">
                    Check failing
                  </Badge>
                )}
              </span>
            )}
          </>
        ) : (
          <span>Next: {a.enabled ? relative(a.next_run) : a.last_run && !a.schedule.includes('RRULE') ? 'done (one-off)' : 'paused'}</span>
        )}
        {a.last_run && (
          <span>
            {trigger ? 'Woken' : 'Last'}: {when(a.last_run)}
            {status && (
              <Badge size="sm" tone={status.tone}>
                {status.label}
              </Badge>
            )}
          </span>
        )}
      </div>
      {a.check_error && <p className={cn(s.result, s.checkError)}>{a.check_error}</p>}
      {a.last_result && a.last_status !== 'quiet' && <p className={s.result}>{a.last_result}</p>}
      <div className={s.actions}>
        <Button size="sm" variant="secondary" iconLeft={<Play />} loading={run.isPending} onClick={() => run.mutate(a.id)}>
          {trigger ? 'Check now' : 'Run now'}
        </Button>
        <Button size="sm" variant="ghost" iconLeft={<MessageSquareText />} onClick={() => void navigate(`/chat/${a.session_id}`)}>
          Open chat
        </Button>
        <span className={s.spacer} />
        <IconButton size="sm" label="Edit" icon={<Pencil />} onClick={onEdit} />
        <IconButton size="sm" label="Delete" variant="danger" icon={<Trash2 />} onClick={onDelete} />
      </div>
    </Card>
  )
}

const REPEATS: { value: Repeat; label: string }[] = [
  { value: 'hourly', label: 'Every hour' },
  { value: 'daily', label: 'Every day' },
  { value: 'weekdays', label: 'Weekdays' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
]
const DAY_LABEL: Record<Weekday, string> = { MO: 'Mon', TU: 'Tue', WE: 'Wed', TH: 'Thu', FR: 'Fri', SA: 'Sat', SU: 'Sun' }

function AutomationEditor({ automation, onClose }: { automation?: Automation; onClose: () => void }) {
  const create = useCreateAutomation()
  const update = useUpdateAutomation()
  const { data: models = [] } = useChatModels()
  const { data: settings } = useSettings()
  const [title, setTitle] = useState(automation?.title ?? '')
  const [prompt, setPrompt] = useState(automation?.prompt ?? '')
  const [watch, setWatch] = useState(automation?.timing_mode === 'condition_watch')
  const [trigger, setTrigger] = useState(automation?.timing_mode === 'trigger')
  const [check, setCheck] = useState(automation?.check ?? '')
  const [minutes, setMinutes] = useState(String(automation?.check_minutes ?? 15))
  const everyMinutes = Math.round(Number(minutes))
  const minutesOk = Number.isFinite(everyMinutes) && everyMinutes >= 1 && everyMinutes <= 1440
  const [sched, setSched] = useState<ScheduleForm>(() => (automation ? fromVevent(automation.schedule) : defaultSchedule()))
  const available = models.filter((m) => m.available)
  // What the user picked, else the default chat model, else the first available one (the lists load after mount)
  const [picked, setModel] = useState(automation?.model ?? '')
  const model = picked || settings?.default_chat_model || available[0]?.id || ''
  const set = (patch: Partial<ScheduleForm>) => setSched((x) => ({ ...x, ...patch }))
  const timing: AutomationTiming = trigger ? 'trigger' : watch ? 'condition_watch' : 'exact_schedule'
  const busy = create.isPending || update.isPending
  const valid = title.trim() && prompt.trim() && model && (trigger ? check.trim() && minutesOk : !watch || sched.kind !== 'once')

  const save = () => {
    const body = trigger
      ? { title: title.trim(), prompt: prompt.trim(), timing_mode: timing, check, check_minutes: everyMinutes, model }
      : { title: title.trim(), prompt: prompt.trim(), timing_mode: timing, schedule: toVevent(sched), model }
    const done = { onSuccess: onClose }
    if (automation) update.mutate({ id: automation.id, ...body }, done)
    else create.mutate(body, done)
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={automation ? 'Edit automation' : 'New automation'}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid} loading={busy} onClick={save}>
            {automation ? 'Save' : 'Create'}
          </Button>
        </>
      }
    >
      <div className={s.form}>
        <Field label="Title">
          {(id) => <Input id={id} value={title} maxLength={80} placeholder="Morning AI news" onChange={(e) => setTitle(e.target.value)} />}
        </Field>
        <Field label="Runs">
          <SegmentedControl<'schedule' | 'trigger'>
            value={trigger ? 'trigger' : 'schedule'}
            onValueChange={(v) => setTrigger(v === 'trigger')}
            segments={[
              { value: 'schedule', label: 'On a schedule' },
              { value: 'trigger', label: 'When something new shows up' },
            ]}
          />
        </Field>
        <Field
          label="What should the assistant do?"
          hint={
            trigger
              ? 'What to do with the new items it is woken for. It can use all its tools: web research, Python, generation…'
              : 'Written as an instruction for each run. It can use all its tools: web research, Python, generation…'
          }
        >
          {(id) => (
            <Textarea
              id={id}
              autoResize
              minRows={3}
              maxRows={10}
              value={prompt}
              maxLength={4000}
              placeholder="Summarize the most important AI news from the last day in five short bullet points with sources."
              onChange={(e) => setPrompt(e.target.value)}
            />
          )}
        </Field>
        {trigger && (
          <>
            <Field
              label="Check"
              hint="Python that runs by itself, without the model, so it costs nothing while nothing happens. It prints one line per item that matters right now; a line it has not printed before wakes the assistant. It is run once when you save: what it prints then is the starting point, and an error is shown here."
            >
              {(id) => (
                <Textarea
                  id={id}
                  className={s.code}
                  minRows={8}
                  maxRows={18}
                  autoResize
                  spellCheck={false}
                  value={check}
                  placeholder={CHECK_EXAMPLE}
                  onChange={(e) => setCheck(e.target.value)}
                />
              )}
            </Field>
            <Field label="Check every (minutes)" hint="Between 1 and 1440.">
              {(id) => <Input id={id} type="number" min={1} max={1440} value={minutes} onChange={(e) => setMinutes(e.target.value)} />}
            </Field>
          </>
        )}
        {!trigger && (
          <>
            <Switch
              label="Only tell me when something happens"
              description="A watch: each run checks a condition (“when it's going to snow in Tahoe”) and stays quiet until it's met."
              checked={watch}
              onCheckedChange={(on) => {
                setWatch(on)
                if (on && sched.kind === 'once') set({ kind: 'repeat', repeat: 'hourly' })
              }}
            />
            <Field label="When">
              <SegmentedControl<ScheduleForm['kind']>
                value={sched.kind}
                onValueChange={(kind) => set({ kind })}
                segments={[
                  { value: 'once', label: 'Once' },
                  { value: 'repeat', label: 'Repeats' },
                  { value: 'custom', label: 'Custom rule' },
                ]}
              />
            </Field>
            {watch && sched.kind === 'once' && <p className={s.warn}>A watch has to repeat: pick “Repeats”.</p>}
            {sched.kind === 'repeat' && (
              <Field label="How often">
                <SegmentedControl<Repeat> size="sm" value={sched.repeat} onValueChange={(repeat) => set({ repeat })} segments={REPEATS} />
              </Field>
            )}
            {sched.kind === 'repeat' && sched.repeat === 'weekly' && (
              <div className={s.days}>
                {WEEKDAYS.map((d) => (
                  <button
                    key={d}
                    type="button"
                    className={cn(s.day, sched.days.includes(d) && s.dayOn)}
                    onClick={() => set({ days: sched.days.includes(d) ? sched.days.filter((x) => x !== d) : [...sched.days, d] })}
                  >
                    {DAY_LABEL[d]}
                  </button>
                ))}
              </div>
            )}
            {sched.kind === 'custom' && (
              <Field label="RRULE" hint="iCal recurrence, e.g. FREQ=WEEKLY;INTERVAL=2;BYDAY=FR or FREQ=MONTHLY;BYMONTHDAY=1. At most hourly.">
                {(id) => <Input id={id} value={sched.custom} onChange={(e) => set({ custom: e.target.value })} />}
              </Field>
            )}
            <div className={s.row}>
              <Field label={sched.kind === 'once' ? 'Date' : 'Starting'}>
                {(id) => <Input id={id} type="date" value={sched.date} onChange={(e) => set({ date: e.target.value })} />}
              </Field>
              {!(sched.kind === 'repeat' && sched.repeat === 'hourly') && (
                <Field label="Time">
                  {(id) => <Input id={id} type="time" value={sched.time} onChange={(e) => set({ time: e.target.value })} />}
                </Field>
              )}
            </div>
          </>
        )}
        <Field label="Model" hint="Runs with this chat model. A local model is free; it loads when the automation runs and, if it was loaded just for that, is unloaded again afterwards.">
          {(id) => (
            <Select
              id={id}
              value={model}
              onValueChange={setModel}
              options={available.map((m) => ({ value: m.id, label: m.name }))}
              placeholder="Choose a model"
            />
          )}
        </Field>
      </div>
    </Dialog>
  )
}
