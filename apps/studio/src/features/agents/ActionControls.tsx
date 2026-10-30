import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Field, Input, Select, Switch, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentMutation, useAgentCapabilities } from '../../api/agents'
import type { ActionPolicy, ActionRule, AgentChannel, AgentChannelCreate, SourceMonitor, SourceMonitorCreate, CapabilityEntry } from '../../api/contracts/agents'
import s from './AgentsPage.module.css'

const emptyPolicy: ActionPolicy = { enabled: false, rules: [], deny_unlisted_effects: true, block_opaque_execution: true, version: 0 }
const parseObject = (text: string): Record<string, unknown> => {
  const value: unknown = JSON.parse(text)
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Arguments must be a JSON object.')
  return value as Record<string, unknown>
}

export default function ActionControls({ sid }: { sid: string }) {
  const policy = useQuery({ queryKey: ['agents', 'policy', sid], queryFn: () => api.get<ActionPolicy>(`/agents/sessions/${sid}/policy`) })
  const monitors = useQuery({ queryKey: ['agents', 'monitors', sid], queryFn: () => api.get<SourceMonitor[]>(`/agents/monitors?sid=${encodeURIComponent(sid)}`) })
  const channels = useQuery({ queryKey: ['agents', 'channels'], queryFn: () => api.get<AgentChannel[]>('/agents/channels') })
  const capabilities = useAgentCapabilities()
  const sources = useQuery({ queryKey: ['agents', 'monitor-sources', sid], queryFn: () => api.get<CapabilityEntry[]>(`/agents/capabilities?purpose=monitor&sid=${encodeURIComponent(sid)}`) })
  const [draft, setDraft] = useState<ActionPolicy>(emptyPolicy)
  const [constraintEdits, setConstraintEdits] = useState<Record<number, string>>({})
  const [watch, setWatch] = useState({ name: '', tool: '', arguments: '{}', select: '', prompt: '', interval: '300', memory: false })
  const [channel, setChannel] = useState({ name: '', provider: 'slack', secret: '', senders: '', conversations: '', sendTool: '', arguments: '{}', recipientPath: '/request_body/channel', textPath: '/request_body/text' })
  useEffect(() => {
    // eslint-disable-next-line react/set-state-in-effect -- Synchronize the saved contract revision received from the server.
    if (policy.data) { setDraft(policy.data); setConstraintEdits({}) }
  }, [policy.data])
  const save = useAgentMutation((body: ActionPolicy) => api.put<ActionPolicy>(`/agents/sessions/${sid}/policy`, body))
  const monitorCreate = useAgentMutation((body: SourceMonitorCreate) => api.post<SourceMonitor>('/agents/monitors', body))
  const channelCreate = useAgentMutation((body: AgentChannelCreate) => api.post<AgentChannel>('/agents/channels', body))
  const toggle = useAgentMutation((a: { kind: 'monitors' | 'channels'; id: string; enabled: boolean }) => api.patch(`/agents/${a.kind}/${a.id}`, { enabled: a.enabled }))
  const remove = useAgentMutation((a: { kind: 'monitors' | 'channels'; id: string }) => api.del(`/agents/${a.kind}/${a.id}`))
  const failure = (error: Error) => toast.error('Change could not be saved', error.message)
  const updateRule = (index: number, value: Partial<ActionRule>) => setDraft(old => ({ ...old, rules: old.rules.map((rule, i) => i === index ? { ...rule, ...value } : rule) }))
  const options = [{ value: '', label: 'Choose a tool' }, ...(capabilities.data ?? []).map(tool => ({ value: tool.name, label: tool.description.slice(0, 70) + ' · ' + tool.name }))]
  const replyOptions = options.filter(item => !item.value || item.value.startsWith('api_') || item.value.includes('__'))
  const sourceOptions = [{ value: '', label: 'Choose a read-only source' }, ...(sources.data ?? []).map(tool => ({ value: tool.name, label: tool.name.replaceAll('_', ' ') + ' · ' + tool.name }))]
  return <section className={s.panel}>
    <h2>Ongoing work</h2><p>Set action boundaries, watch changing information, and connect incoming messages to this conversation.</p>
    {[policy.error, monitors.error, channels.error].filter(Boolean).map((error, index) => <p role="alert" key={index}>{error?.message}</p>)}
    <details className={s.row}><summary>Action boundaries <Badge>{draft.enabled ? 'Enforced' : 'Off'}</Badge></summary>
      <div className={s.editor}>
        <Switch checked={draft.enabled} onCheckedChange={enabled => setDraft(old => ({ ...old, enabled }))} label="Enforce a conversation action contract" />
        <Switch checked={draft.deny_unlisted_effects} onCheckedChange={deny_unlisted_effects => setDraft(old => ({ ...old, deny_unlisted_effects }))} label="Block effects outside these rules" />
        <Switch checked={draft.block_opaque_execution} onCheckedChange={block_opaque_execution => setDraft(old => ({ ...old, block_opaque_execution }))} label="Block raw code and pointer actions" />
        {draft.rules.map((rule, index) => <div className={s.editor} key={index}>
          <Field label="Allowed tool or pattern">{id => <Input id={id} value={rule.tool} onChange={event => updateRule(index, { tool: event.target.value })} />}</Field>
          <Field label="Maximum attempts">{id => <Input id={id} type="number" min={1} value={rule.max_calls ?? ''} onChange={event => updateRule(index, { max_calls: event.target.value ? Number(event.target.value) : null })} />}</Field>
          <Field label="Constraints" hint="JSON Pointer fields, for example /to with operator in and a list of allowed recipients.">{id => <Textarea id={id} rows={4} value={constraintEdits[index] ?? JSON.stringify(rule.constraints ?? [], null, 2)} onChange={event => setConstraintEdits(old => ({ ...old, [index]: event.target.value }))} />}</Field>
          <Button variant="ghost" size="sm" onClick={() => { try { const rules = draft.rules.map((item, i) => ({ ...item, constraints: constraintEdits[i] !== undefined ? JSON.parse(constraintEdits[i]) as ActionRule['constraints'] : item.constraints })); setDraft(old => ({ ...old, rules: rules.filter((_, i) => i !== index) })); setConstraintEdits({}) } catch (error) { failure(error as Error) } }}>Remove rule</Button>
        </div>)}
        <div className={s.actions}><Button variant="secondary" onClick={() => setDraft(old => ({ ...old, rules: [...old.rules, { tool: '', constraints: [] }] }))}>Add rule</Button><Button disabled={!policy.data || save.isPending} onClick={() => { try { const rules = draft.rules.map((rule, index) => { const constraints: unknown = constraintEdits[index] !== undefined ? JSON.parse(constraintEdits[index]) : rule.constraints ?? []; if (!Array.isArray(constraints)) throw new Error('Constraints must be a list.'); return { ...rule, constraints } }); save.mutate({ ...draft, rules }, { onError: failure }) } catch (error) { failure(error as Error) } }}>Save boundaries</Button></div>
        <p>Rules constrain structured arguments. Raw code can hide effects, so keep it blocked for unattended work. Pause the owner before changing boundaries.</p>
      </div>
    </details>
    <details className={s.row}><summary>Source watches <Badge>{monitors.data?.length ?? 0}</Badge></summary>
      <form className={s.editor} onSubmit={event => { event.preventDefault(); try { monitorCreate.mutate({ session_id: sid, name: watch.name, tool: watch.tool, arguments: parseObject(watch.arguments), select: watch.select, prompt: watch.prompt, interval_seconds: Number(watch.interval), record_memory: watch.memory }, { onError: failure }) } catch (error) { failure(error as Error) } }}>
        <Field label="Watch name">{id => <Input id={id} required value={watch.name} onChange={event => setWatch(old => ({ ...old, name: event.target.value }))} />}</Field>
        <Field label="Read-only source">{id => <Select id={id} value={watch.tool} onValueChange={tool => setWatch(old => ({ ...old, tool }))} options={sourceOptions} />}</Field>
        <Field label="Source arguments">{id => <Textarea id={id} rows={3} value={watch.arguments} onChange={event => setWatch(old => ({ ...old, arguments: event.target.value }))} />}</Field>
        <Field label="Observation field" hint="Optional JSON Pointer, such as /data/messages, to ignore unrelated changing fields.">{id => <Input id={id} value={watch.select} onChange={event => setWatch(old => ({ ...old, select: event.target.value }))} />}</Field>
        <Field label="Check interval in seconds">{id => <Input id={id} required type="number" min={30} max={86400} value={watch.interval} onChange={event => setWatch(old => ({ ...old, interval: event.target.value }))} />}</Field>
        <Field label="When the source changes">{id => <Textarea id={id} required value={watch.prompt} onChange={event => setWatch(old => ({ ...old, prompt: event.target.value }))} />}</Field>
        <Switch label="Retain the latest source observation in this conversation’s memory" checked={watch.memory} onCheckedChange={memory => setWatch(old => ({ ...old, memory }))} />
        <Button disabled={!watch.tool || monitorCreate.isPending} type="submit">Create watch</Button><p>The first check establishes a baseline. Unchanged observations stay quiet. Your host must remain running.</p>
      </form>
      {monitors.data?.map(item => <article className={s.editor} key={item.id}><strong>{item.name}</strong><Badge>{item.enabled ? item.last_error ? 'Needs attention' : 'Watching' : 'Paused'}</Badge>{item.last_error && <p role="alert">{item.last_error}</p>}<div className={s.actions}><Button variant="secondary" size="sm" disabled={toggle.isPending} onClick={() => toggle.mutate({ kind: 'monitors', id: item.id, enabled: !item.enabled }, { onError: failure })}>{item.enabled ? 'Pause' : 'Resume'}</Button><Button variant="ghost" size="sm" onClick={() => remove.mutate({ kind: 'monitors', id: item.id }, { onError: failure })}>Remove</Button></div></article>)}
    </details>
    <details className={s.row}><summary>Incoming channels <Badge>{channels.data?.filter(item => item.session_id === sid).length ?? 0}</Badge></summary>
      <form className={s.editor} onSubmit={event => { event.preventDefault(); try { channelCreate.mutate({ session_id: sid, name: channel.name, provider: channel.provider as AgentChannel['provider'], secret: channel.secret, allowed_senders: channel.senders.split(',').map(v => v.trim()).filter(Boolean), allowed_conversations: channel.conversations.split(',').map(v => v.trim()).filter(Boolean), send_tool: channel.sendTool || undefined, send_arguments: parseObject(channel.arguments), recipient_path: channel.recipientPath, text_path: channel.textPath }, { onSuccess: () => setChannel(old => ({ ...old, secret: '' })), onError: failure }) } catch (error) { failure(error as Error) } }}>
        <Field label="Channel name">{id => <Input id={id} required value={channel.name} onChange={event => setChannel(old => ({ ...old, name: event.target.value }))} />}</Field>
        <Field label="Provider">{id => <Select id={id} value={channel.provider} onValueChange={provider => setChannel(old => ({ ...old, provider }))} options={[{ value: 'slack', label: 'Slack Events' }, { value: 'telegram', label: 'Telegram' }, { value: 'webhook', label: 'Signed webhook relay' }]} />}</Field>
        <Field label="Signing secret">{id => <Input id={id} required type="password" autoComplete="new-password" value={channel.secret} onChange={event => setChannel(old => ({ ...old, secret: event.target.value }))} />}</Field>
        <Field label="Allowed sender IDs" hint="Comma-separated exact IDs.">{id => <Input id={id} required value={channel.senders} onChange={event => setChannel(old => ({ ...old, senders: event.target.value }))} />}</Field>
        <Field label="Allowed conversation IDs">{id => <Input id={id} required value={channel.conversations} onChange={event => setChannel(old => ({ ...old, conversations: event.target.value }))} />}</Field>
        <Field label="Outgoing operation">{id => <Select id={id} value={channel.sendTool} onValueChange={sendTool => setChannel(old => ({ ...old, sendTool }))} options={replyOptions} />}</Field>
        <Field label="Outgoing arguments">{id => <Textarea id={id} rows={3} value={channel.arguments} onChange={event => setChannel(old => ({ ...old, arguments: event.target.value }))} />}</Field>
        <Field label="Recipient field">{id => <Input id={id} value={channel.recipientPath} onChange={event => setChannel(old => ({ ...old, recipientPath: event.target.value }))} />}</Field>
        <Field label="Message field">{id => <Input id={id} value={channel.textPath} onChange={event => setChannel(old => ({ ...old, textPath: event.target.value }))} />}</Field>
        <Button type="submit" disabled={channelCreate.isPending}>Connect channel</Button><p>Configure the provider subscription against your HTTPS gateway. Incoming text is source material. Replies retain approval and action boundaries.</p>
      </form>
      {channels.data?.filter(item => item.session_id === sid).map(item => <article className={s.editor} key={item.id}><strong>{item.name}</strong><Badge>{item.enabled ? 'Enabled' : 'Paused'}</Badge><p>Gateway callback: /channels/{item.id}/receive</p><div className={s.actions}><Button variant="secondary" size="sm" disabled={toggle.isPending} onClick={() => toggle.mutate({ kind: 'channels', id: item.id, enabled: !item.enabled }, { onError: failure })}>{item.enabled ? 'Pause' : 'Resume'}</Button><Button variant="ghost" size="sm" onClick={() => remove.mutate({ kind: 'channels', id: item.id }, { onError: failure })}>Disconnect</Button></div></article>)}
    </details>
  </section>
}
