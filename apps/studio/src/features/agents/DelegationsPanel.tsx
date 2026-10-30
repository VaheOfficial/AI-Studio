import { Link } from 'react-router'
import { Badge, Button, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentMutation, useAgents } from '../../api/agents'
import type { AgentDelegation } from '../../api/contracts/agents'
import s from './AgentsPage.module.css'

export default function DelegationsPanel({ sid }: { sid?: string }) {
  const { data } = useAgents()
  const cancel = useAgentMutation((d: AgentDelegation) => api.post(`/agents/sessions/${d.parent_session_id}/delegations/${d.id}/cancel`))
  const children = (data?.delegations ?? []).filter(d => !sid || d.parent_session_id === sid)
  if (!children.length) return null
  return <details className={s.row}><summary>Subagents <Badge>{children.length}</Badge></summary>
    {children.map(d => <article key={d.id}><div className={s.actions}><Badge>{d.status}</Badge><Link to={`/agents/chat/${d.session_id}`}>Inspect conversation</Link><Link to={`/agents/chat/${d.parent_session_id}`}>Parent</Link>
      {['queued', 'running', 'waiting_approval'].includes(d.status) && <Button size="sm" variant="ghost" disabled={cancel.isPending} onClick={() => cancel.mutate(d, { onError: e => toast.error('Subagent could not be stopped', e.message) })}>Stop subagent</Button>}</div>
      <p>{d.objective}</p><small>{d.requests}/{d.max_requests} model requests · Tools: {d.allowed_tools.join(', ')}</small><pre>{d.result || d.error}</pre></article>)}
  </details>
}
