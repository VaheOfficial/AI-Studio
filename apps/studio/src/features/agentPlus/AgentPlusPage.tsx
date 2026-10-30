import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { Check, Circle, FlaskConical, Pause, Play, Plus, Wrench, X } from 'lucide-react'
import { Badge, Button, Field, Input, Select, Skeleton, Textarea, toast } from '@studio/ui'
import { useAgentPlus, useAgentPlusAction, useAgentPlusMissions } from '../../api/agentPlus'
import type { AgentPlusDetail, ChatCapability } from '../../api/contracts/agentPlus'
import { useChatModels } from '../../api/hooks'
import { api } from '../../api/client'
import { useAgentMutation } from '../../api/agents'
import ChatPage from '../chat/ChatPage'
import s from './AgentPlusPage.module.css'

export default function AgentPlusPage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const { data, isLoading, error } = useAgentPlus(sessionId)
  const { data: missions = [] } = useAgentPlusMissions()
  return <div className={s.page}>
    <header className={s.header}>
      <div><h1>Mission</h1><p>One agent. Persistent progress. Tools built when needed.</p></div>
      <div className={s.controls}>
        {!!missions.length && <Select aria-label="Agent mission" value={sessionId ?? ''}
          placeholder="Open a mission" options={missions.map(m => ({ value: m.session_id, label: m.objective.slice(0, 55) }))}
          onValueChange={id => { navigate(`/agents/missions/${id}`) }} />}
        <Button variant="ghost" size="sm" onClick={() => { navigate('/agents/missions') }}><Plus size={15} />New mission</Button>
      </div>
    </header>
    {!sessionId ? <MissionForm onCreated={id => navigate(`/agents/missions/${id}`)} /> : isLoading ? <Skeleton height="100%" /> :
      error || !data ? <div className={s.empty}><p>{error?.message ?? 'Mission unavailable'}</p><Link to="/agents/missions">Open Agents</Link></div> :
      <div className={s.body}>
        <div className={s.conversation}><ChatPage basePath="/agents/missions" agentPlus /></div>
        <MissionProgress sessionId={sessionId} />
      </div>}
  </div>
}

export function MissionProgress({ sessionId }: { sessionId: string }) {
  const { data, isLoading, error } = useAgentPlus(sessionId)
  const action = useAgentPlusAction()
  const [editing, setEditing] = useState(false)
  const change = async (kind: 'resume' | 'pause' | 'cancel') => {
    if (!sessionId) return
    try { await action.mutateAsync({ kind, sid: sessionId }) }
    catch (e) { toast.error('Mission could not be updated', (e as Error).message) }
  }
  if (isLoading) return <Skeleton height={120} />
  if (!data || error) return <p>{error?.message ?? 'Progress is unavailable.'}</p>
  return (        <aside className={s.contextInspector} aria-label="Mission progress">
          <div className={s.missionHeader}>
            <Badge>{data.mission.status}</Badge><span>Version {data.mission.version}</span>
          </div>
          <h2>{data.mission.objective}</h2>
          <div className={s.controls}>
            {data.mission.status === 'running' ? <Button size="sm" variant="secondary" disabled={action.isPending} onClick={() => void change('pause')}><Pause size={14} />Pause</Button> :
              <Button size="sm" disabled={action.isPending || ['completed', 'cancelled'].includes(data.mission.status)} onClick={() => void change('resume')}><Play size={14} />{data.mission.status === 'ready' ? 'Start' : 'Resume'}</Button>}
            <Button size="sm" variant="ghost" disabled={action.isPending || data.mission.status === 'running'} onClick={() => setEditing(!editing)}>Amend</Button>
            <Button size="sm" variant="ghost" disabled={action.isPending || ['completed', 'cancelled'].includes(data.mission.status)} onClick={() => void change('cancel')}><X size={14} />Cancel</Button>
          </div>
          {editing && <MissionForm existing={data} onCreated={() => setEditing(false)} />}
          {data.mission.reason && <p className={s.reason}>{data.mission.reason}</p>}
          <p className={s.budget}>{data.mission.requests} / {data.mission.max_requests} model requests
            {data.mission.max_cost > 0 && <> · ${data.mission.cost.toFixed(3)} / ${data.mission.max_cost.toFixed(2)}</>}</p>
          {!!data.work.length && <section className={s.section}><h3>Current work</h3>
            <ul className={s.criteria}>{data.work.map(w => <li key={w.id}>
              {w.status === 'done' ? <Check size={16} className={s.accepted} /> : <Circle size={16} />}
              <div>{w.objective}<small>{w.kind} · {w.status}</small>{w.superseded_reason && <small>{w.superseded_reason}</small>}</div>
            </li>)}</ul>
          </section>}
          <section className={s.section}><h3>Required outcomes</h3>
            <ul className={s.criteria}>{data.mission.criteria.map(c => <li key={c.id}>
              {c.evidence.length ? <Check size={16} className={s.accepted} /> : <Circle size={16} />}
              <div>{c.text}{!!c.evidence.length && <small>{c.evidence.length} evidence receipt{c.evidence.length === 1 ? '' : 's'}</small>}</div>
            </li>)}</ul>
          </section>
          <section className={s.section}><h3><Wrench size={16} />Tools in this chat</h3>
            {!data.tools.length && <p className={s.hint}>A missing tool triggers research, construction, and checks. Validated tools stay available here.</p>}
            {data.tools.map(t => <Tool key={t.id} tool={t} />)}
          </section>
          {data.actions.some(a => a.status === 'uncertain') && <section className={s.section}>
            <h3>Needs inspection</h3>{data.actions.filter(a => a.status === 'uncertain').map(a => <p key={a.id}>{a.name}: {a.output}</p>)}
          </section>}
          <section className={s.section}><h3><FlaskConical size={16} />Activity and evidence</h3>
            <ol className={s.events}>{[...data.events].filter(e => !['action.intent', 'action.receipt', 'work.state', 'turn'].includes(e.kind)).reverse().map(e => <li key={e.seq}>
              <time>{new Date(e.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
              <details><summary>{e.text.slice(0, 160)}</summary><p>{e.text}</p>
                {Object.keys(e.data).length > 0 && <pre>{JSON.stringify(e.data, null, 2)}</pre>}</details>
            </li>)}</ol>
          </section>
        </aside>)
}

function MissionForm({ existing, onCreated }: { existing?: AgentPlusDetail; onCreated: (id: string) => void }) {
  const { data: models = [] } = useChatModels()
  const action = useAgentPlusAction()
  const [objective, setObjective] = useState(existing?.mission.objective ?? '')
  const [criteria, setCriteria] = useState(existing?.mission.criteria.map(c => c.text).join('\n') ?? '')
  const [model, setModel] = useState('')
  const [budget, setBudget] = useState(String(existing?.mission.max_cost ?? 0))
  const [requests, setRequests] = useState(String(existing?.mission.max_requests ?? 80))
  const available = models.filter(m => m.available && m.tools)
  const selected = model || available.find(m => ['ollama', 'llamacpp', 'lmstudio'].includes(m.provider))?.id || available[0]?.id
  const submit = async () => {
    try {
      const checks = criteria.split('\n').map(c => c.trim()).filter(Boolean)
      const d = await action.mutateAsync(existing ? { kind: 'amend', sid: existing.mission.session_id,
        body: { version: existing.mission.version, objective, criteria: checks.length ? checks : [objective], max_cost: Number(budget), max_requests: Number(requests) } } :
        { kind: 'create', body: { model: selected!, objective, criteria: checks.length ? checks : [objective], max_cost: Number(budget), max_requests: Number(requests) } })
      onCreated(d.mission.session_id)
    } catch (e) { toast.error('Mission could not be saved', (e as Error).message) }
  }
  return <form className={existing ? s.amend : s.form} onSubmit={e => { e.preventDefault(); void submit() }}>
    {!existing && <><h2>Give it an outcome to work toward.</h2><p>The agent works sequentially, retains evidence, and can research and build a missing tool.</p></>}
    <Field label="Objective">{id => <Textarea id={id} required value={objective} onChange={e => setObjective(e.target.value)} placeholder="What should be accomplished?" rows={3} />}</Field>
    <Field label="Acceptance criteria" hint="One outcome per line. If empty, the objective becomes the criterion.">{id => <Textarea id={id} value={criteria} onChange={e => setCriteria(e.target.value)} rows={3} placeholder="How will we know it worked?" />}</Field>
    {!existing && <>
      <Field label="Model"><Select aria-label="Mission model" value={selected ?? ''} onValueChange={setModel} options={available.map(m => ({ value: m.id, label: m.name }))} placeholder="Choose a tool-capable model" /></Field>
    </>}
    <Field label="Model request limit" hint="Includes main reasoning, research, alternatives, and compaction.">{id => <Input id={id} required type="number" min="5" max="500" step="1" value={requests} onChange={e => setRequests(e.target.value)} />}</Field>
    <Field label="Remote model budget ($)" hint="Zero uses local models only. Remote requests reserve $0.25 each; actual billing can differ.">{id => <Input id={id} required type="number" min="0" max="100" step="0.25" value={budget} onChange={e => setBudget(e.target.value)} />}</Field>
    <Button type="submit" disabled={action.isPending || !objective.trim() || (!existing && !selected)}>{existing ? 'Save amendment' : 'Create mission'}</Button>
  </form>
}

function Tool({ tool: t }: { tool: ChatCapability }) {
  const promote = useAgentMutation(() => api.post('/agents/skills', {
    name: t.name, description: t.description, instructions: t.description + '\nLimitations: ' + t.limitations,
    source_session_id: t.session_id, capability_id: t.id, permissions: ['run_python'], dependencies: [],
  }))
  return <details className={s.tool}>
    <summary><span>{t.name} <small>v{t.version}</small></span><Badge>{t.status}</Badge></summary>
    <p>{t.description}</p><p>{t.results.filter(r => r.passed).length} / {t.results.length} checks passed</p>
    {t.limitations && <p>{t.limitations}</p>}
    {t.status === 'validated' && <Button size="sm" variant="secondary" disabled={promote.isPending} onClick={() => promote.mutate(undefined, {
      onSuccess: () => toast.success('Tool added to reusable skills'), onError: e => toast.error('Tool could not be promoted', e.message),
    })}>Add to reusable skills</Button>}
    <pre>{t.code}</pre>
    <details><summary>Input and output</summary><pre>{JSON.stringify({ input: t.input_schema, output: t.output_schema }, null, 2)}</pre></details>
    <details><summary>Validation results</summary><pre>{JSON.stringify(t.results, null, 2)}</pre></details>
    {!!t.sources.length && <ul>{t.sources.map((url, i) => <li key={i}>{/^https?:\/\//.test(url) ? <a href={url} target="_blank" rel="noreferrer">{url}</a> : url}</li>)}</ul>}
  </details>
}
