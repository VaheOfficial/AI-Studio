import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { Badge, Button, Field, Input, Select, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentMutation, useAgents } from '../../api/agents'
import { useChatModels } from '../../api/hooks'
import type { AgentWake, WakeCreate } from '../../api/contracts/agents'
import DelegationsPanel from './DelegationsPanel'
import SavedTeamPanel from './SavedTeamPanel'
import NotificationsPanel from './NotificationsPanel'
import s from './AgentsPage.module.css'

export default function ActivityPanel() {
  const { data, error } = useAgents()
  const navigate = useNavigate()
  const { swarmId } = useParams()
  const { data: models = [] } = useChatModels()
  const [sid, setSid] = useState('')
  const [prompt, setPrompt] = useState('')
  const [time, setTime] = useState('')
  const [topic, setTopic] = useState('')
  const err = (e: Error) => toast.error('Activity could not be updated', e.message)
  const schedule = useAgentMutation((body: WakeCreate) => api.post<AgentWake>(`/agents/sessions/${sid}/wakes`, body))
  const change = useAgentMutation((body: { id: string; status: 'scheduled' | 'cancelled' }) => api.patch(`/agents/wakes/${body.id}`, { status: body.status }))
  const localModel = models.find(m => m.available && m.tools && ['ollama', 'llamacpp', 'lmstudio'].includes(m.provider))
  const importTeam = useAgentMutation((id: string) => api.post<{ mission: { session_id: string } }>(`/agents/legacy/${id}/import`, { model: localModel?.id }))
  return <section className={s.panel}><h2>Agent activity</h2>{error && <p>{error.message}</p>}
    <div className={s.actions}><Link to="/automations">Scheduled routines</Link><Link to="/agents/connections">Connections and devices</Link></div>
    <DelegationsPanel />
    <NotificationsPanel />
    <details className={s.row}><summary>Schedule a continuation</summary><form className={s.editor} onSubmit={e => {
      e.preventDefault()
      schedule.mutate({ prompt, wake_at: time ? new Date(time).toISOString() : undefined, topic: topic || undefined }, { onSuccess: () => { setPrompt(''); setTime(''); setTopic('') }, onError: err })
    }}><p>A wake starts one agent turn while the host is online. Events are accepted through a scoped device gateway. Recurring work is managed in Automations.</p>
      <Field label="Wake conversation"><Select aria-label="Wake conversation" value={sid} onValueChange={setSid} placeholder="Choose a conversation" options={(data?.sessions ?? []).map(v => ({ value: v.id, label: v.title }))} /></Field>
      <Field label="Wake instruction"><Textarea aria-label="Wake instruction" value={prompt} onChange={e => setPrompt(e.target.value)} required rows={3} placeholder="What should the agent do when it wakes?" /></Field>
      <Field label="Wake local date and time"><Input aria-label="Wake local date and time" type="datetime-local" value={time} onChange={e => setTime(e.target.value)} /></Field>
      <Field label="Wake event topic"><Input aria-label="Wake event topic" value={topic} onChange={e => setTopic(e.target.value)} placeholder="Or an event topic" /></Field>
      <Button type="submit" disabled={!sid || (!time && !topic) || schedule.isPending}>Schedule wake</Button>
    </form></details>
    {data?.wakes.map(w => <article className={s.row} key={w.id}><Badge>{w.status}</Badge><p>{w.prompt}</p><small>{w.wake_at || w.topic}</small><p>{w.result}</p><div className={s.actions}>
      <Link to={`/agents/chat/${w.session_id}`}>Open conversation</Link>
      {['scheduled', 'ready', 'paused', 'failed'].includes(w.status) && <Button size="sm" variant="ghost" disabled={change.isPending} onClick={() => change.mutate({ id: w.id, status: 'cancelled' }, { onError: err })}>Cancel wake</Button>}
      {['paused', 'failed'].includes(w.status) && <Button size="sm" variant="secondary" disabled={change.isPending} onClick={() => change.mutate({ id: w.id, status: 'scheduled' }, { onError: err })}>Reschedule reviewed wake</Button>}
    </div></article>)}
    {!!data?.legacy_swarms.length && <h3>Saved teams</h3>}
    {swarmId && <SavedTeamPanel id={swarmId} />}
    {data?.legacy_swarms.map(v => <article className={s.row} key={v.id}><p>{v.title}</p><Badge>{v.status}</Badge><div className={s.actions}><Link to={`/agents/legacy/${v.id}`}>Inspect saved history</Link><Button size="sm" variant="secondary" disabled={!localModel || importTeam.isPending} onClick={() => importTeam.mutate(v.id, { onSuccess: d => navigate(`/agents/missions/${d.mission.session_id}`), onError: err })}>Continue as a mission</Button></div>{swarmId === v.id && <small>Historical work is retained.</small>}</article>)}
  </section>
}
