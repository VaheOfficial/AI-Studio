import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Field, Input, Select, Switch, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentMutation, useAgents } from '../../api/agents'
import type { AgentDevice, AgentHost, AgentConnections, OAuthConfig, DeviceCreate, DeviceGrant, PluginReview } from '../../api/contracts/agents'
import s from './AgentsPage.module.css'

export default function ConnectionsPanel() {
  const { data: overview } = useAgents()
  const { data: connections, error } = useQuery({ queryKey: ['agents', 'connections'], queryFn: () => api.get<AgentConnections>('/agents/connections') })
  const { data: host } = useQuery({ queryKey: ['agents', 'host'], queryFn: () => api.get<AgentHost>('/agents/host') })
  const { data: devices } = useQuery({ queryKey: ['agents', 'devices'], queryFn: () => api.get<AgentDevice[]>('/agents/devices') })
  const [connector, setConnector] = useState('')
  const [target, setTarget] = useState<'mcp' | 'service'>('mcp')
  const [authorizeUrl, setAuthorizeUrl] = useState('')
  const [tokenUrl, setTokenUrl] = useState('')
  const [clientId, setClientId] = useState('')
  const [secret, setSecret] = useState('')
  const [scopes, setScopes] = useState('')
  const [deviceName, setDeviceName] = useState('')
  const [sid, setSid] = useState('')
  const [grant, setGrant] = useState('read')
  const [token, setToken] = useState('')
  const [notifications, setNotifications] = useState(false)
  const [plugin, setPlugin] = useState<File>()
  const [manifest, setManifest] = useState<PluginReview>()
  const [skillName, setSkillName] = useState('')
  const [authorizationLink, setAuthorizationLink] = useState('')
  const err = (e: Error) => toast.error('Operation could not be completed', e.message)
  const authorize = useAgentMutation((body: OAuthConfig) => api.post<{ authorize_url: string; redirect_uri: string }>('/agents/oauth/start', body))
  const issue = useAgentMutation((body: DeviceCreate) => api.post<DeviceGrant>('/agents/devices', body))
  const revoke = useAgentMutation((id: string) => api.del(`/agents/devices/${id}`))
  const hostAction = useAgentMutation((action: 'register' | 'unregister' | 'gateway' | 'stop-gateway' | 'tls' | 'trust') => action === 'unregister' ? api.del('/agents/host/register') : action === 'stop-gateway' ? api.del('/agents/host/gateway') : api.post(`/agents/host/${action}`, action === 'trust' ? {confirmed:true} : undefined))
  const inspect = useAgentMutation((file: File) => { const form = new FormData(); form.append('file', file); return api.upload<PluginReview>('/agents/plugins/inspect', form) })
  const install = useAgentMutation((file: File) => { const form = new FormData(); form.append('file', file); return api.upload<unknown>('/agents/plugins/install', form) })
  const remove = useAgentMutation((id: string) => api.del(`/agents/plugins/${id}`))
  const record = useAgentMutation((action: 'start' | 'finish' | 'cancel') => action === 'cancel' ? api.del(`/agents/sessions/${sid}/recording`) : api.post(`/agents/sessions/${sid}/recording/${action}`, action === 'finish' ? { name: skillName } : undefined))
  return <section className={`${s.panel} ${s.narrow}`}><h2>Connections and devices</h2><p>Application tools come from configured MCP connections and installed plugins.</p>{error && <p>{error.message}</p>}
    <div className={s.actions}><a href="/settings">Manage MCP connections</a><Badge>{connections?.vault_available ? 'OS credential storage available' : 'OS keychain unavailable'}</Badge></div>
    <details className={s.row}><summary>Authorize an application</summary><form className={s.editor} onSubmit={e => { e.preventDefault(); authorize.mutate({ target, connector_id: connector, authorize_url: authorizeUrl, token_url: tokenUrl, client_id: clientId, client_secret: secret || undefined, scopes: scopes.split(/\s+/).filter(Boolean) }, { onSuccess: result => { setSecret(''); setAuthorizationLink(result.authorize_url) }, onError: err }) }}>
      <Field label="Authorization connection type"><Select aria-label="Authorization connection type" value={target} onValueChange={value => setTarget(value as 'mcp' | 'service')} options={[{ value: 'mcp', label: 'MCP connection' }, { value: 'service', label: 'HTTP application service' }]} /></Field>
      <Field label="Connector ID"><Input aria-label="Connector ID" placeholder="Connector ID from Settings" required value={connector} onChange={e => setConnector(e.target.value)} /></Field>
      <Field label="Authorization URL"><Input aria-label="Authorization URL" placeholder="Authorization endpoint" required type="url" value={authorizeUrl} onChange={e => setAuthorizeUrl(e.target.value)} /></Field>
      <Field label="Token URL"><Input aria-label="Token URL" placeholder="Token endpoint" required type="url" value={tokenUrl} onChange={e => setTokenUrl(e.target.value)} /></Field>
      <Field label="Client ID"><Input aria-label="Client ID" placeholder="Client ID" required value={clientId} onChange={e => setClientId(e.target.value)} /></Field>
      <Field label="Client secret"><Input aria-label="Client secret" placeholder="Client secret (optional)" type="password" value={secret} onChange={e => setSecret(e.target.value)} autoComplete="off" /></Field>
      <Field label="OAuth scopes"><Input aria-label="OAuth scopes" placeholder="Scopes separated by spaces" value={scopes} onChange={e => setScopes(e.target.value)} /></Field>
      <Button type="submit" disabled={authorize.isPending || !connections?.vault_available}>Authorize</Button>
      {authorizationLink && <a href={authorizationLink} target="_blank" rel="noreferrer">Continue secure authorization</a>}
    </form></details>
    <details className={s.row}><summary>Plugins</summary><p>Review a native bundle or a Claude plugin ZIP before installation. Imported skills and new connections stay disabled until reviewed.</p>
      <input type="file" accept=".zip,.plugin" aria-label="Plugin bundle" onChange={e => { setPlugin(e.target.files?.[0]); setManifest(undefined) }} />
      <div className={s.actions}><Button variant="secondary" disabled={!plugin || inspect.isPending} onClick={() => plugin && inspect.mutate(plugin, { onSuccess: setManifest, onError: err })}>Inspect bundle</Button>
        <Button disabled={!plugin || !manifest || install.isPending} onClick={() => plugin && install.mutate(plugin, { onSuccess: () => { setManifest(undefined); toast.success('Plugin installed') }, onError: err })}>Install reviewed bundle</Button></div>
      {manifest != null && <pre>{JSON.stringify(manifest, null, 2)}</pre>}
      {connections?.plugins.map(p => <div className={s.actions} key={p.id}><span>{p.id} · {p.version}</span><Button variant="ghost" size="sm" onClick={() => remove.mutate(p.id, { onError: err })}>Remove</Button></div>)}
    </details>
    <details className={s.row}><summary>Background host</summary><p>A sign-in service keeps local work available while the desktop window is closed. The computer must remain online.</p>
      <Badge>{host?.service ? 'Independent host' : 'Desktop-managed host'}</Badge><div className={s.actions}>
        <Button variant="secondary" disabled={!host?.supports_service_install || hostAction.isPending} onClick={() => hostAction.mutate('register', { onSuccess: () => toast.success('Host registered', 'Starts at your next sign-in.'), onError: err })}>Start at sign-in</Button>
        <Button variant="ghost" disabled={hostAction.isPending} onClick={() => hostAction.mutate('unregister', { onError: err })}>Remove sign-in registration</Button>
        <Button variant="secondary" disabled={hostAction.isPending} onClick={() => hostAction.mutate(host?.gateway_running ? 'stop-gateway' : 'gateway', { onError: err })}>{host?.gateway_running ? 'Stop device gateway' : 'Start device gateway'}</Button>
        <Button variant="secondary" disabled={hostAction.isPending} onClick={() => hostAction.mutate('tls', { onSuccess: () => toast.success('Local HTTPS configured', 'Trust its certificate before connecting Office or this browser.'), onError: err })}>Configure or renew local HTTPS</Button>
        <Button variant="secondary" disabled={hostAction.isPending || !host?.gateway_tls} onClick={() => hostAction.mutate('trust', { onSuccess: () => toast.success('Local certificate trusted in your account'), onError: err })}>Trust local gateway certificate</Button>
      </div>{host?.gateway_running && <p>Gateway: {host.gateway_url}. Remote access uses an HTTPS proxy to this separate endpoint.</p>}
    </details>
    <details className={s.row}><summary>Connect a device</summary><form className={s.editor} onSubmit={e => { e.preventDefault(); issue.mutate({ name: deviceName, scopes: [...(grant === 'events' ? ['deliver_events'] : grant === 'documents' ? ['documents'] : grant === 'read' ? ['read', 'events'] : ['read', 'events', 'chat', 'approve']), ...(notifications ? ['notifications'] : [])], session_ids: [sid] }, { onSuccess: r => setToken(r.token), onError: err }) }}>
      <Field label="Device name"><Input aria-label="Device name" required value={deviceName} onChange={e => setDeviceName(e.target.value)} placeholder="Device name" /></Field>
      <Field label="Granted conversation"><Select aria-label="Granted conversation" value={sid} onValueChange={setSid} placeholder="Choose a conversation" options={(overview?.sessions ?? []).map(v => ({ value: v.id, label: v.title }))} /></Field>
      <Field label="Device permissions"><Select aria-label="Device permissions" value={grant} onValueChange={setGrant} options={[{ value: 'read', label: 'Read this conversation' }, { value: 'control', label: 'Read, send and approve in this conversation' }, { value: 'documents', label: 'Connect a document editor to this conversation' }, { value: 'events', label: 'Deliver continuation events to this conversation' }]} /></Field>
      <Switch checked={notifications} onCheckedChange={setNotifications} label="Allow browser notifications for this conversation" />
      <Button type="submit" disabled={!sid || issue.isPending}>Create device token</Button>
      {token && <><p>Copy this token now. Only its hash is stored.</p><Field label="New device token"><Textarea aria-label="New device token" readOnly value={token} /></Field><Button variant="ghost" onClick={() => setToken('')}>Hide token</Button></>}
    </form></details>{devices?.map(d => <div className={s.actions} key={d.id}><span>{d.name}</span><Badge>{d.enabled ? 'Enabled' : 'Revoked'}</Badge><Button variant="ghost" size="sm" disabled={!d.enabled} onClick={() => revoke.mutate(d.id, { onError: err })}>Revoke</Button></div>)}
    <details className={s.row}><summary>Teach a browser task</summary><p>Select a conversation, start recording, then use its browser takeover controls. Sensitive fields are omitted. Finish to create a disabled skill draft for review.</p>
      <Field label="Demonstration conversation"><Select aria-label="Demonstration conversation" value={sid} onValueChange={setSid} options={(overview?.sessions ?? []).map(v => ({ value: v.id, label: v.title }))} placeholder="Choose a conversation" /></Field>
      <Field label="Demonstration skill name"><Input aria-label="Demonstration skill name" value={skillName} onChange={e => setSkillName(e.target.value)} placeholder="Skill name" /></Field>
      <div className={s.actions}><Button disabled={!sid || record.isPending} onClick={() => record.mutate('start', { onSuccess: () => toast.success('Recording browser actions'), onError: err })}>Start recording</Button>
        <Button variant="secondary" disabled={!sid || !skillName || record.isPending} onClick={() => record.mutate('finish', { onSuccess: () => toast.success('Skill draft saved', 'Review and enable it in Skills.'), onError: err })}>Finish draft</Button>
        <Button variant="ghost" disabled={!sid || record.isPending} onClick={() => record.mutate('cancel', { onError: err })}>Discard recording</Button></div>
    </details>
  </section>
}
