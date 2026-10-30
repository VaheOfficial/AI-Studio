import { useState } from 'react'
import { Badge, Button, Field, Input, Select, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentKnowledge, useAgentMutation, useAgents } from '../../api/agents'
import type { AgentKnowledge, KnowledgeCreate, KnowledgeUpdate } from '../../api/contracts/agents'
import s from './AgentsPage.module.css'

export default function MemoryPanel() {
  const { data, error } = useAgentKnowledge()
  const { data: overview } = useAgents()
  const [editing, setEditing] = useState<AgentKnowledge>()
  const [text, setText] = useState('')
  const [source, setSource] = useState('')
  const [scope, setScope] = useState<AgentKnowledge['scope']>('agent')
  const [scopeId, setScopeId] = useState('main')
  const [expiry, setExpiry] = useState('')
  const err = (e: Error) => toast.error('Memory could not be updated', e.message)
  const save = useAgentMutation((body: KnowledgeCreate | KnowledgeUpdate) => editing
    ? api.patch<AgentKnowledge>(`/agents/knowledge/${editing.id}`, body)
    : api.post<AgentKnowledge>('/agents/knowledge', body))
  const remove = useAgentMutation((id: string) => api.del(`/agents/knowledge/${id}`))
  const reset = () => { setEditing(undefined); setText(''); setSource(''); setExpiry('') }
  return <section className={`${s.panel} ${s.narrow}`}><h2>Memory with sources</h2><p>Knowledge is retrieved by relevance and scoped to an agent, workspace or conversation.</p>
    <form className={s.editor} onSubmit={e => {
      e.preventDefault()
      save.mutate({ text, source, scope, scope_id: scopeId, expires_at: expiry || null, ...(editing ? { updated_at: editing.updated_at } : {}) }, { onSuccess: reset, onError: err })
    }}>
      <Field label="Memory scope"><Select aria-label="Memory scope" value={scope} options={[{ value: 'agent', label: 'Agent' }, { value: 'chat', label: 'Conversation' }, { value: 'workspace', label: 'Workspace' }]} onValueChange={v => { setScope(v as AgentKnowledge['scope']); setScopeId(v === 'agent' ? 'main' : '') }} /></Field>
      {scope === 'chat' ? <Field label="Memory conversation"><Select aria-label="Memory conversation" value={scopeId} onValueChange={setScopeId} placeholder="Choose a conversation" options={(overview?.sessions ?? []).map(v => ({ value: v.id, label: v.title }))} /></Field>
        : <Input aria-label={scope === 'agent' ? 'Agent identifier' : 'Workspace absolute path'} required value={scopeId} onChange={e => setScopeId(e.target.value)} placeholder={scope === 'agent' ? 'main' : 'Exact absolute workspace path'} />}
      <Field label="Knowledge"><Textarea aria-label="Knowledge" placeholder="A fact to remember" required value={text} onChange={e => setText(e.target.value)} rows={4} /></Field>
      <Field label="Knowledge source"><Input aria-label="Knowledge source" placeholder="Source or provenance" value={source} onChange={e => setSource(e.target.value)} /></Field>
      <Field label="Memory expiry"><Input aria-label="Memory expiry" placeholder="Optional expiry with timezone, such as 2026-12-01T00:00:00Z" value={expiry} onChange={e => setExpiry(e.target.value)} /></Field>
      <div className={s.actions}><Button type="submit" disabled={save.isPending || !scopeId}>{editing ? 'Save edit' : 'Save memory'}</Button>{editing && <Button variant="ghost" onClick={reset}>Cancel edit</Button>}</div>
    </form>{error && <p>{error.message}</p>}
    {data?.map(k => <article key={k.id} className={s.row}><Badge>{k.scope}</Badge><small>{k.scope_id}</small><p>{k.text}</p><small>{k.source || 'No source recorded'}{k.expires_at && ` · Expires ${k.expires_at}`}</small>
      <div className={s.actions}><Button size="sm" variant="secondary" onClick={() => { setEditing(k); setText(k.text); setSource(k.source); setScope(k.scope); setScopeId(k.scope_id); setExpiry(k.expires_at ?? '') }}>Edit</Button>
        <Button size="sm" variant="ghost" onClick={() => remove.mutate(k.id, { onError: err })}>Forget</Button></div></article>)}
  </section>
}
