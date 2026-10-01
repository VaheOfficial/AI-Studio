/** Automations: prompts the agent runs on a schedule (`/api/automations`); mirrored by
 * `server/studio/schemas_automations.py`. */

/**
 * `exact_schedule`: at the time given · `flexible_schedule`: around a daypart (morning 8:00, afternoon 15:00,
 * evening 19:00) · `condition_watch`: a recurring check that only reports when the condition is met.
 */
export type AutomationTiming = 'exact_schedule' | 'flexible_schedule' | 'condition_watch'
export type AutomationRunStatus = 'reported' | 'quiet' | 'needs_approval' | 'error'

export interface Automation {
  id: string
  title: string
  /** The instruction sent to the agent on every run. */
  prompt: string
  /** iCal VEVENT: DTSTART (local time) and optionally RRULE. */
  schedule: string
  /** The schedule in words ("Every day at 08:00"). */
  schedule_text: string
  timing_mode: AutomationTiming
  enabled: boolean
  /** Chat model id that runs it; unset = the default chat model. */
  model?: string
  /** The chat its runs are posted in. */
  session_id: string
  /** ISO UTC; unset when it won't run again. */
  next_run?: string
  last_run?: string
  last_status?: AutomationRunStatus
  /** Start of the last report (or the error). */
  last_result?: string
  created_at: string
}

export interface AutomationCreate {
  title: string
  prompt: string
  timing_mode: AutomationTiming
  /** An iCal VEVENT (DTSTART and/or RRULE)… */
  schedule?: string
  /** …or a relative one-off: dateutil.relativedelta kwargs as JSON, e.g. `{"hours": 4}`. */
  dtstart_offset_json?: string
  model?: string
}

export type AutomationUpdate = Partial<AutomationCreate> & { enabled?: boolean }

export type AutomationServerEvent =
  | { type: 'automation.update'; automation: Automation }
  | { type: 'automation.removed'; id: string }
  /** A run finished with something for the user: a report, a pending approval, or an error. */
  | { type: 'automation.run'; automation_id: string; title: string; status: AutomationRunStatus; message: string; session_id: string }
