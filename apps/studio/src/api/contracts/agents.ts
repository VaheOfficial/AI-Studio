import type { AgentSession } from '../types'
import type { AgentPlusMission } from './agentPlus'

export interface AgentIdentity {
  id: string
  name: string
  instructions: string
  model?: string | null
  advisor_model?: string | null
  allow_subagents: boolean
  max_subagents: number
  sandbox: 'process' | 'container'
  desktop_control: boolean
  created_at: string
  updated_at: string
}
export interface CapabilityEntry {
  name: string
  description: string
  origin: 'builtin' | 'connector' | 'mission'
  needs_approval: boolean
  parameters?: Record<string, unknown>
}
export interface AgentKnowledge {
  id: string
  scope: 'agent' | 'workspace' | 'chat'
  scope_id: string
  text: string
  source: string
  expires_at?: string | null
  created_at: string
  updated_at: string
}
export interface AgentSkill {
  id: string
  name: string
  version: number
  description: string
  instructions: string
  permissions: string[]
  dependencies: string[]
  capability_id?: string | null
  source_session_id?: string | null
  code_hash?: string | null
  enabled: boolean
  created_at: string
}
export interface AgentArtifact {
  id: string
  session_id: string
  title: string
  kind: 'markdown' | 'html' | 'json' | 'text'
  version: number
  content: string
  content_hash: string
  created_at: string
  updated_at: string
}
export interface AgentDelegation {
  id: string
  parent_session_id: string
  session_id: string
  task_id: string
  objective: string
  allowed_tools: string[]
  max_requests: number
  requests: number
  status: string
  result?: string | null
  error?: string | null
  created_at: string
}
export interface AgentWake {
  id: string
  session_id: string
  prompt: string
  wake_at?: string | null
  topic?: string | null
  status: 'scheduled' | 'ready' | 'running' | 'done' | 'paused' | 'failed' | 'cancelled'
  result?: string | null
  created_at: string
}
export interface AgentDevice {
  id: string
  name: string
  scopes: string[]
  enabled: boolean
  created_at: string
  last_seen?: string | null
}
export interface AgentsOverview {
  identities: AgentIdentity[]
  sessions: AgentSession[]
  missions: AgentPlusMission[]
  delegations: AgentDelegation[]
  wakes: AgentWake[]
  legacy_swarms: { id: string; title: string; status: string }[]
}
export type AgentsServerEvent = { type: 'agents.update'; area: string; session_id?: string | null }

export type IdentityPatch = Partial<Pick<AgentIdentity, 'name' | 'instructions' | 'model' | 'advisor_model' | 'allow_subagents' | 'max_subagents' | 'sandbox' | 'desktop_control'>>
export interface KnowledgeCreate { scope?: AgentKnowledge['scope']; scope_id?: string; text: string; source?: string; expires_at?: string | null }
export interface KnowledgeUpdate extends KnowledgeCreate { updated_at: string }
export interface SkillCreate { name: string; description?: string; instructions: string; permissions?: string[]; dependencies?: string[]; capability_id?: string | null; source_session_id?: string | null }
export interface ArtifactCreate { title: string; kind?: AgentArtifact['kind']; content: string; id?: string | null; version?: number | null }
export interface DelegateCreate { objective: string; title?: string; allowed_tools?: string[]; max_requests?: number; model?: string }
export interface DelegationFollowup { message: string; additional_requests?: number }
export interface ActionConstraint { path: string; operator: 'eq' | 'in' | 'gte' | 'lte' | 'prefix' | 'host'; value: unknown }
export interface ActionRule { tool: string; constraints?: ActionConstraint[]; max_calls?: number | null; expires_at?: string | null }
export interface ActionPolicy { enabled: boolean; rules: ActionRule[]; deny_unlisted_effects: boolean; block_opaque_execution: boolean; version: number }
export interface SourceMonitorCreate { session_id: string; name: string; tool: string; arguments?: Record<string, unknown>; select?: string; interval_seconds?: number; prompt: string; notify_initial?: boolean; record_memory?: boolean; enabled?: boolean }
export interface SourceMonitor extends SourceMonitorCreate { id: string; source_hash?: string | null; observation?: string | null; last_error?: string | null; failures: number; next_at: number; updated_at: string; memory_id?: string | null }
export interface AgentChannel { id: string; session_id: string; name: string; provider: 'slack' | 'telegram' | 'webhook'; allowed_senders: string[]; allowed_conversations: string[]; send_tool?: string | null; enabled: boolean; created_at: string }
export interface AgentChannelCreate extends Omit<AgentChannel, 'id' | 'created_at' | 'enabled'> { secret: string; send_arguments?: Record<string, unknown>; recipient_path?: string; text_path?: string; enabled?: boolean }
export interface WakeCreate { prompt: string; wake_at?: string | null; topic?: string | null }
export interface AgentHost { service: boolean; data_identity: string; gateway_running: boolean; gateway_url: string; gateway_tls: boolean; supports_service_install: boolean }
export interface OAuthConfig { target?: 'mcp' | 'service'; connector_id: string; authorize_url: string; token_url: string; client_id: string; client_secret?: string | null; scopes?: string[] }
export interface DeviceCreate { name: string; scopes?: string[]; session_ids: string[] }
export interface DeviceGrant { device: AgentDevice; token: string; session_ids: string[] }
export interface AgentConnections { vault_available: boolean; oauth: { connector_id: string; authorized: boolean; expires_at?: number | null }[]; plugins: { id: string; version: string; skill_ids: string[]; connector_ids: string[] }[] }
export interface ArtifactRevision { version: number; content_hash: string; updated_at: string }
export interface LiveDocumentTool { name: string; description?: string; parameters: Record<string, unknown> }
export interface LiveDocument { id: string; session_id: string; title: string; kind: string; tools: LiveDocumentTool[] }
export interface ApplicationCall { session_id: string; name: string; arguments?: Record<string, unknown> }
export interface AgentEventDelivery { event_id: string; payload?: Record<string, unknown> }
export interface PluginReview { id: string; version: string; skills: SkillCreate[]; connectors: Record<string, unknown>[]; source_files: Record<string, string>; warnings: string[]; imported: boolean }

export interface ServiceOperation { id: string; description: string; method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD'; path: string; parameters: Record<string, unknown>; bindings: Record<string, { location: 'path' | 'query'; name: string }>; body_field?: string | null; read_only: boolean }
export interface AgentService { id: string; name: string; base_url: string; enabled: boolean; headers: Record<string, string>; operations: ServiceOperation[]; created_at: string }
export interface ServiceCreate { name: string; base_url: string; headers?: Record<string, string>; operations?: ServiceOperation[]; enabled?: boolean }
export interface ServiceImport { name: string; base_url: string; document: Record<string, unknown>; headers?: Record<string, string> }
export interface AgentNotification { id: string; session_id: string; kind: 'completed' | 'approval' | 'question' | 'error' | 'notice'; title: string; body: string; read: boolean; created_at: string }
export interface NotificationSettings { web_push: boolean; native_desktop: boolean; contact: string }
export interface PushSubscriptionInput { endpoint: string; keys: { p256dh: string; auth: string } }

export interface ApplicationContext { session_id: string; content: string }
export interface ServiceReview { service: ServiceCreate; warnings: string[] }
export interface ApplicationResource { contents: { uri: string; text?: string; blob?: string; mimeType?: string; _meta?: { ui?: { csp?: { connectDomains?: string[]; resourceDomains?: string[] } } } }[] }

export interface ServiceTemplate { id: string; documentation: string; requirements: string; service: ServiceCreate }

export interface CapabilityFamily { id: string; name: string; status: 'ready' | 'setup' | 'unknown' | 'unsupported'; verified: boolean; tools: string[]; requirements: string }

export interface GatewayVoiceModel { id: string; name: string; runtime: string }
export interface GatewayDictationHello { token: string; model_id?: string; language?: string }

export interface GatewayTrustRequest { confirmed: true }
