/** The Automations editor's schedule model ↔ the iCal VEVENT the server stores (DTSTART local time + RRULE). */

export type Repeat = 'hourly' | 'daily' | 'weekdays' | 'weekly' | 'monthly'
export const WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const
export type Weekday = (typeof WEEKDAYS)[number]

export interface ScheduleForm {
  kind: 'once' | 'repeat' | 'custom'
  date: string // YYYY-MM-DD (once; the first day otherwise)
  time: string // HH:MM
  repeat: Repeat
  days: Weekday[] // weekly
  custom: string // raw RRULE for anything else
}

const pad = (n: number) => String(n).padStart(2, '0')

export function defaultSchedule(): ScheduleForm {
  const t = new Date(Date.now() + 60 * 60 * 1000)
  return {
    kind: 'repeat',
    date: `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`,
    time: '08:00',
    repeat: 'daily',
    days: ['MO'],
    custom: 'FREQ=DAILY',
  }
}

export function toVevent(f: ScheduleForm): string {
  const dtstart = `${f.date.replaceAll('-', '')}T${f.time.replace(':', '')}00`
  let rule = ''
  if (f.kind === 'custom') rule = f.custom.replace(/^RRULE:/i, '').trim()
  else if (f.kind === 'repeat') {
    rule = {
      hourly: 'FREQ=HOURLY',
      daily: 'FREQ=DAILY',
      weekdays: 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR',
      weekly: `FREQ=WEEKLY;BYDAY=${(f.days.length ? f.days : ['MO']).join(',')}`,
      monthly: 'FREQ=MONTHLY',
    }[f.repeat]
  }
  return `BEGIN:VEVENT\nDTSTART:${dtstart}\n${rule ? `RRULE:${rule}\n` : ''}END:VEVENT`
}

/** Back from a stored VEVENT; rules the builder can't express open as a custom rule. */
export function fromVevent(v: string): ScheduleForm {
  const base = defaultSchedule()
  const start = /DTSTART[^:]*:(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/.exec(v)
  if (start) {
    base.date = `${start[1]}-${start[2]}-${start[3]}`
    base.time = `${start[4]}:${start[5]}`
  }
  const rule = /RRULE:([^\n]+)/.exec(v)?.[1].trim()
  if (!rule) return { ...base, kind: 'once' }
  const known: Record<string, Repeat> = {
    'FREQ=HOURLY': 'hourly',
    'FREQ=DAILY': 'daily',
    'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR': 'weekdays',
    'FREQ=MONTHLY': 'monthly',
  }
  if (known[rule]) return { ...base, kind: 'repeat', repeat: known[rule] }
  const weekly = /^FREQ=WEEKLY;BYDAY=([A-Z,]+)$/.exec(rule)
  if (weekly) return { ...base, kind: 'repeat', repeat: 'weekly', days: weekly[1].split(',') as Weekday[] }
  return { ...base, kind: 'custom', custom: rule }
}

/** "in 3 h", "in 2 days", "Oct 3, 08:00" for a future ISO time. */
export function relative(iso?: string): string {
  if (!iso) return '—'
  const t = new Date(iso)
  const mins = Math.round((t.getTime() - Date.now()) / 60000)
  if (mins < 1) return 'now'
  if (mins < 60) return `in ${mins} min`
  if (mins < 24 * 60) return `in ${Math.round(mins / 60)} h`
  if (mins < 7 * 24 * 60) return `${t.toLocaleDateString(undefined, { weekday: 'short' })} ${t.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`
  return t.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
