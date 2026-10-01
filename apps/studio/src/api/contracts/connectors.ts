/** Connectors: MCP servers whose tools the agent can use (`/api/connectors`); mirrored by
 * `server/studio/schemas_connectors.py`. Secret values (env vars, HTTP headers) come back as `•••`; sending `•••`
 * back keeps the stored value. */

/** `stdio`: a local program · `http`: a remote Streamable HTTP endpoint. */
export type ConnectorTransport = 'stdio' | 'http'
export type ConnectorStatus = 'disabled' | 'connecting' | 'connected' | 'error'
/** `ask`: every tool call needs the user's OK · `auto`: runs without asking. */
export type ConnectorApproval = 'ask' | 'auto'

export interface ConnectorTool {
  name: string
  /** What the agent calls it: `<connector>__<tool>`. */
  agent_name: string
  description: string
}

export interface Connector {
  id: string
  name: string
  transport: ConnectorTransport
  command?: string
  args: string[]
  env: Record<string, string>
  url?: string
  headers: Record<string, string>
  enabled: boolean
  approval: ConnectorApproval
  status: ConnectorStatus
  error?: string
  tools: ConnectorTool[]
  created_at: string
}

export interface ConnectorCreate {
  name: string
  transport: ConnectorTransport
  command?: string
  args?: string[]
  env?: Record<string, string>
  url?: string
  headers?: Record<string, string>
  enabled?: boolean
  approval?: ConnectorApproval
}

export type ConnectorUpdate = Partial<Omit<ConnectorCreate, 'transport'>>

export type ConnectorServerEvent =
  | { type: 'connector.update'; connector: Connector }
  | { type: 'connector.removed'; id: string }
