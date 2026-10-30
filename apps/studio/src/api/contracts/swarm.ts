/** Swarm: a group of agents with roles working on one goal (`/api/swarms`); mirrored by
 * `server/studio/schemas_swarm.py`. See `docs/api/swarm.md`. */

/**
 * `draft`: set up, never started · `running`: the controller hands out work · `paused`: running sessions finish,
 * nothing new starts · `stopped`: stopped by the owner · `done`: the Foundress judged the goal reached.
 */
export type SwarmStatus = 'draft' | 'running' | 'paused' | 'stopped' | 'done'
/** `lead`: the Foundress, plans and never does the work · `worker`: one task per session · `inspector`: checks work. */
export type SwarmRole = 'lead' | 'worker' | 'inspector'
/** `dismissed`: off the team (by the owner or the Foundress); kept so the history keeps its name. */
export type SwarmAgentState = 'idle' | 'working' | 'reviewing' | 'planning' | 'paused' | 'dismissed'
export type SwarmItemKind = 'milestone' | 'task'
/**
 * `open`: waiting (or back for rework after a rejection) · `running`: a worker is on it · `review`: handed off, waiting
 * for or under an inspector's check · `accepted` · `failed`: given up after repeated failures · `cancelled`.
 */
export type SwarmItemStatus = 'open' | 'running' | 'review' | 'accepted' | 'failed' | 'cancelled'
/** What a tool may do in a swarm: run, be refused, or be refused with a request filed in the owner's inbox. */
export type ToolRule = 'allow' | 'ask' | 'deny'
export type InboxKind = 'question' | 'permission'
export type InboxStatus = 'open' | 'answered' | 'allowed' | 'denied' | 'dismissed'

/** A worker's report on its task, as written. */
export interface SwarmHandoff {
  summary: string
  not_done?: string
  deviations?: string
  concerns?: string
  findings?: string
  follow_ups: string[]
  files: string[]
  agent_id: string
  at: string
}

export interface SwarmCheck {
  criterion: string
  passed: boolean
  evidence: string
}

/** An inspector's verdict. */
export interface SwarmReview {
  accepted: boolean
  summary: string
  checks: SwarmCheck[]
  agent_id: string
  at: string
}

export interface SwarmItem {
  id: string
  swarm_id: string
  /** The milestone a task belongs to. */
  parent_id?: string
  kind: SwarmItemKind
  title: string
  spec: string
  /** What has to be true for it to be accepted, written before the work starts. */
  acceptance: string[]
  status: SwarmItemStatus
  /** 1 high, 2 normal, 3 low. */
  priority: number
  /** Items that must be accepted first. */
  blocked_by: string[]
  /** The agent the Foundress asked for. */
  assign_to?: string
  /** Who is working on it, or last did. */
  owner_agent_id?: string
  /** Sessions started on it (a rejection counts as one). */
  attempts: number
  rejections: number
  handoff?: SwarmHandoff
  review?: SwarmReview
  /** Every session that worked on or checked it, oldest first. */
  session_ids: string[]
  /** USD spent on it (cloud models that report cost). */
  cost: number
  /** Agent id, or "owner". */
  created_by: string
  created_at: string
  updated_at: string
}

export interface SwarmAgent {
  id: string
  swarm_id: string
  name: string
  role: SwarmRole
  /** Chat model id ("<provider>:<model>"). */
  model: string
  /** What it is for and good at, in the owner's words; the Foundress assigns work by it. */
  purpose: string
  state: SwarmAgentState
  /** The item it is on. */
  item_id?: string
  /** Its current (or last) session. */
  session_id?: string
  accepted: number
  rejected: number
  failed: number
  cost: number
  /** Its own notes, carried into every session. */
  notes: string
  last_active?: string
}

/** One line of the swarm's history. */
export interface SwarmEvent {
  seq: number
  swarm_id: string
  at: string
  /** started, planning, planned, assigned, handed_off, reviewing, accepted, rejected, failed, stalled, asked, owner, report… */
  kind: string
  text: string
  agent_id?: string
  item_id?: string
}

/** Something an agent needs from the owner: an answer, or permission for a tool the swarm's rules hold back. */
export interface SwarmInboxEntry {
  id: string
  swarm_id: string
  kind: InboxKind
  agent_id: string
  item_id?: string
  /** The question, or what the agent wanted. */
  text: string
  options: string[]
  /** Permission: the tool and the call that was refused. */
  tool?: string
  args?: Record<string, unknown>
  status: InboxStatus
  answer?: string
  created_at: string
  resolved_at?: string
}

export interface Swarm {
  id: string
  name: string
  /** The charter: what to achieve, what counts as reached, what is out of scope. */
  goal: string
  /** The folder every agent works in. */
  folder: string
  status: SwarmStatus
  /** Why it paused or stopped by itself (or why it is done). */
  status_reason?: string
  /** Sessions at a time, the Foundress's included; local models run one at a time regardless. */
  max_parallel: number
  /** USD per day; unset = no limit. Reaching it pauses the swarm until the next day. */
  daily_budget?: number
  /** USD per work item; unset = no limit. */
  item_budget?: number
  /** Per tool, overriding `SwarmDetail.default_rules`. */
  rules: Record<string, ToolRule>
  /** The Foundress builds the team: it hires workers and inspectors on any model it finds, and dismisses them. */
  hiring: boolean
  /** Workers and inspectors at once, when the Foundress hires. */
  max_agents: number
  /** USD per million input tokens: the most a hired agent's model may cost. Unset = no limit. */
  max_price?: number
  /** The Foundress's latest report. */
  report?: string
  report_at?: string
  spent_today: number
  spent_total: number
  /** What its sessions cost in the last 60 minutes: the current rate. */
  spent_last_hour: number
  created_at: string
  updated_at: string
}

/** `GET /swarms/{id}`: everything the swarm page shows. */
export interface SwarmDetail {
  swarm: Swarm
  agents: SwarmAgent[]
  items: SwarmItem[]
  inbox: SwarmInboxEntry[]
  /** The most recent, oldest first. */
  events: SwarmEvent[]
  /** What applies to a tool the swarm has no rule for. */
  default_rules: Record<string, ToolRule>
}

export interface SwarmAgentSpec {
  name: string
  role: SwarmRole
  model: string
  purpose?: string
}

export interface SwarmCreate {
  name: string
  goal: string
  folder: string
  agents: SwarmAgentSpec[]
  max_parallel?: number
  daily_budget?: number
  item_budget?: number
  rules?: Record<string, ToolRule>
  /** With `hiring` the roster may be the Foundress alone. */
  hiring?: boolean
  max_agents?: number
  max_price?: number
}

export interface SwarmUpdate {
  name?: string
  goal?: string
  max_parallel?: number
  daily_budget?: number
  item_budget?: number
  rules?: Record<string, ToolRule>
  hiring?: boolean
  max_agents?: number
  max_price?: number
  /** Set the daily budget back to no limit. */
  clear_daily_budget?: boolean
  clear_item_budget?: boolean
  clear_max_price?: boolean
}

export interface SwarmAgentUpdate {
  name?: string
  model?: string
  purpose?: string
}

/** `POST /swarms/{id}/inbox/{entry}`: answer a question, or decide a permission request. */
export interface SwarmInboxReply {
  action: 'answer' | 'allow' | 'deny' | 'dismiss'
  answer?: string
}

export type SwarmServerEvent =
  | { type: 'swarm.update'; swarm: Swarm }
  | { type: 'swarm.removed'; id: string }
  | { type: 'swarm.agent'; agent: SwarmAgent }
  | { type: 'swarm.item'; item: SwarmItem }
  | { type: 'swarm.inbox'; entry: SwarmInboxEntry }
  | { type: 'swarm.event'; event: SwarmEvent }
