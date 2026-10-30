import { useState } from 'react'
import { Badge, Button, Field, Input, Select, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentIdentityUpdate, useAgentMutation, useAgentSkills, useAgents } from '../../api/agents'
import type { AgentSkill } from '../../api/contracts/agents'
import { useChatModels } from '../../api/hooks'
import s from './AgentsPage.module.css'

export function Skills() {
  const { data, error } = useAgentSkills()
  const [name, setName] = useState('')
  const [instructions, setInstructions] = useState('')
  const save = useAgentMutation((body: { name: string; instructions: string }) => api.post<AgentSkill>('/agents/skills', body))
  const toggle = useAgentMutation((a: { id: string; enabled: boolean }) => api.patch<AgentSkill>(`/agents/skills/${a.id}`, { enabled: a.enabled }))
  return <section className={`${s.panel} ${s.narrow}`}><h2>Reusable skills</h2><p>Save instructions your agent can follow again. Review each skill before enabling it.</p>
    <form className={s.editor} onSubmit={e => { e.preventDefault(); save.mutate({ name, instructions }, { onSuccess: () => { setName(''); setInstructions('') }, onError: e => toast.error('Skill could not be saved', e.message) }) }}>
      <Field label="Skill name"><Input aria-label="Skill name" placeholder="Skill name" required value={name} onChange={e => setName(e.target.value)} /></Field>
      <Field label="Instructions"><Textarea aria-label="Skill instructions" placeholder="Steps, constraints and completion criteria" required value={instructions} onChange={e => setInstructions(e.target.value)} rows={5} /></Field>
      <Button type="submit" disabled={save.isPending}>Save skill</Button>
    </form>{error && <p>{error.message}</p>}
    {data?.map(k => <details key={k.id} className={s.row}><summary>{k.name}<Badge>v{k.version}</Badge><Badge>{k.enabled ? 'Enabled' : 'Disabled'}</Badge></summary><p>{k.description}</p><pre>{k.instructions}</pre><p>Permissions: {k.permissions.join(', ') || 'None declared'}</p><p>Dependencies: {k.dependencies.join(', ') || 'None'}</p><Button size="sm" variant="secondary" onClick={() => toggle.mutate({ id: k.id, enabled: !k.enabled }, { onError: e => toast.error('Skill could not be updated', e.message) })}>{k.enabled ? 'Disable' : 'Enable'}</Button></details>)}
  </section>
}

export function AgentSettings() {
  const { data } = useAgents()
  const { data: models = [] } = useChatModels()
  const value = data?.identities.find(a => a.id === 'main')
  const update = useAgentIdentityUpdate()
  const [instructions, setInstructions] = useState<string>()
  return <section className={`${s.panel} ${s.narrow}`}><h2>Agent settings</h2>{value && <>
    <Field label="Instructions"><Textarea value={instructions ?? value.instructions} onChange={e => setInstructions(e.target.value)} rows={5} aria-label="Agent instructions" /></Field>
    <Button onClick={() => update.mutate({ id: value.id, body: { instructions: instructions ?? value.instructions } }, { onError: e => toast.error('Settings could not be saved', e.message) })}>Save instructions</Button>
    <Field label="Advisor model" hint="Optional model for a planning consultation. Remote use requires an authorized budget."><Select aria-label="Advisor model" value={value.advisor_model ?? 'none'} options={[{ value: 'none', label: 'Disabled' }, ...models.filter(m => m.available).map(m => ({ value: m.id, label: m.name }))]} onValueChange={id => update.mutate({ id: value.id, body: { advisor_model: id === 'none' ? null : id } }, { onError: e => toast.error('Advisor could not be saved', e.message) })} /></Field>
    <Field label="Subagents"><Select aria-label="Subagents" value={value.allow_subagents ? 'enabled' : 'disabled'} options={[{ value: 'enabled', label: 'Available when needed' }, { value: 'disabled', label: 'Sequential only' }]} onValueChange={v => update.mutate({ id: value.id, body: { allow_subagents: v === 'enabled' } }, { onError: e => toast.error('Settings could not be saved', e.message) })} /></Field>
    <Field label="Active subagent limit"><Input type="number" aria-label="Active subagent limit" min={0} max={8} value={value.max_subagents} onChange={e => { const number = Number(e.target.value); if (Number.isInteger(number) && number >= 0 && number <= 8) update.mutate({ id: value.id, body: { max_subagents: number } }, { onError: e => toast.error('Settings could not be saved', e.message) }) }} /></Field>
    <Field label="Desktop control"><Select aria-label="Desktop control" value={value.desktop_control ? "enabled" : "disabled"} options={[{ value: "disabled", label: "Disabled" }, { value: "enabled", label: "Available with approvals" }]} onValueChange={v => update.mutate({ id: value.id, body: { desktop_control: v === "enabled" } }, { onError: e => toast.error("Settings could not be saved", e.message) })} /></Field>
    <Field label="Generated tool execution" hint="Container mode requires a local Docker engine and the configured worker image."><Select aria-label="Tool execution" value={value.sandbox} options={[{ value: 'process', label: 'Local process' }, { value: 'container', label: 'Isolated container' }]} onValueChange={v => update.mutate({ id: value.id, body: { sandbox: v as 'process' | 'container' } }, { onError: e => toast.error('Settings could not be saved', e.message) })} /></Field>
  </>}</section>
}

