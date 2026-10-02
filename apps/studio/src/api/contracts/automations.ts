/** Automations: prompts the agent runs on a schedule or when a trigger fires (`/api/automations`); mirrored by
 * `server/studio/schemas_automations.py`. */

/**
 * `exact_schedule`: at the time given · `flexible_schedule`: around a daypart (morning 8:00, afternoon 15:00,
 * evening 19:00) · `condition_watch`: a recurring check that only reports when the condition is met · `trigger`: no
 * schedule; a check script runs by itself every few minutes and the agent is woken only when it prints something new.
 */
export type AutomationTiming = 'exact_schedule' | 'flexible_schedule' | 'condition_watch' | 'trigger'
export type AutomationRunStatus = 'reported' | 'quiet' | 'needs_approval' | 'error'

export interface Automation {
  id: string
  title: string
  /** The instruction sent to the agent on every run. */
  prompt: string
  /** iCal VEVENT: DTSTART (local time) and optionally RRULE; empty for a trigger. */
  schedule: string
  /** The schedule in words ("Every day at 08:00", "Checks every 15 minutes"). */
  schedule_text: string
  timing_mode: AutomationTiming
  enabled: boolean
  /** Chat model id that runs it; unset = the default chat model. */
  model?: string
  /** The chat its runs are posted in. */
  session_id: string
  /** ISO UTC; unset when it won't run again. For a trigger, the next check. */
  next_run?: string
  last_run?: string
  last_status?: AutomationRunStatus
  /** Start of the last report (or the error). */
  last_result?: string
  created_at: string
  /**
   * A trigger: Python the app runs by itself (no model) every `check_minutes`. Each line it prints is an item; a
   * line it has not printed before wakes the agent, which gets the new lines with the prompt.
   */
  check?: string
  check_minutes?: number
  /** ISO UTC of a trigger's last check. */
  last_check?: string
  /** Why a trigger's last check failed; unset when it ran. */
  check_error?: string
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
  /** `timing_mode: 'trigger'`: the check script, and minutes between checks (1-1440, default 15); no schedule. */
  check?: string
  check_minutes?: number
}

export type AutomationUpdate = Partial<AutomationCreate> & { enabled?: boolean }

export type AutomationServerEvent =
  | { type: 'automation.update'; automation: Automation }
  | { type: 'automation.removed'; id: string }
  /** A run finished with something for the user: a report, a pending approval, or an error. */
  | { type: 'automation.run'; automation_id: string; title: string; status: AutomationRunStatus; message: string; session_id: string }
