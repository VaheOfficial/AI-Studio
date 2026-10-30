/** Agent+ missions and tools belong to one chat. */
export interface AcceptanceCase {
  args: Record<string, unknown>
  expected?: unknown
  error_contains?: string
}
export interface MissionCriterion {
  id: string
  text: string
  evidence: string[]
}
export interface AgentPlusMission {
  session_id: string
  original_request: string
  objective: string
  version: number
  status: 'ready' | 'running' | 'paused' | 'blocked' | 'completed' | 'cancelled'
  reason?: string
  criteria: MissionCriterion[]
  max_requests: number
  requests: number
  max_cost: number
  cost: number
  reserved_cost: number
  created_at: string
  updated_at: string
}
export interface ChatCapability {
  id: string
  session_id: string
  name: string
  description: string
  version: number
  status: 'candidate' | 'validated' | 'failed' | 'retired'
  code: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  acceptance: AcceptanceCase[]
  checks: AcceptanceCase[]
  results: { passed: boolean; actual?: unknown; error?: string; case_index?: number; source?: 'acceptance' | 'edge'; args?: Record<string, unknown> }[]
  sources: string[]
  limitations: string
  code_hash: string
  created_at: string
}
export interface MissionAction {
  id: string
  name: string
  args: Record<string, unknown>
  status: 'running' | 'succeeded' | 'failed' | 'uncertain' | 'resolved'
  output?: string
  created_at: string
}
export interface MissionEvent {
  seq: number
  kind: string
  text: string
  data: Record<string, unknown>
  created_at: string
}
export interface AgentPlusDetail {
  mission: AgentPlusMission
  tools: ChatCapability[]
  actions: MissionAction[]
  events: MissionEvent[]
  work: MissionWork[]
}
export interface MissionWork {
  id: string
  kind: 'delivery' | 'learning' | 'alternative' | 'validation'
  objective: string
  dependencies: string[]
  status: 'pending' | 'running' | 'done' | 'blocked' | 'superseded'
  evidence: string[]
  superseded_reason?: string
}
export interface AgentPlusCreate {
  model: string
  objective: string
  criteria: string[]
  max_requests?: number
  max_cost?: number
}
export interface AgentPlusAmend {
  version: number
  objective: string
  criteria: string[]
  max_requests?: number
  max_cost?: number
}
export type AgentPlusServerEvent = { type: 'agentplus.update'; session_id: string }
