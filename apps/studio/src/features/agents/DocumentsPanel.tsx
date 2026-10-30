import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Field, Input, Select, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentMutation, useAgents } from '../../api/agents'
import { connectDocument, type DocumentCommand } from './documentBridge'
import s from './AgentsPage.module.css'

import type { LiveDocument, AgentHost, DeviceGrant } from '../../api/contracts/agents'
export default function DocumentsPanel() {
  const { data } = useAgents()
  const { data: host } = useQuery({ queryKey: ['agents', 'host'], queryFn: () => api.get<AgentHost>('/agents/host') })
  const { data: documents, error } = useQuery({ queryKey: ['agents', 'documents'], queryFn: () => api.get<LiveDocument[]>('/agents/documents') })
  const [sid, setSid] = useState('')
  const [title, setTitle] = useState('Untitled document')
  const [kind, setKind] = useState('text')
  const [content, setContent] = useState('')
  const text = useRef('')
  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const connection = useRef<{ stop: () => void; device: string } | undefined>(undefined)
  const change = (value: string) => { text.current = value; setContent(value) }
  const object = (properties: Record<string, unknown>, required: string[] = []) => ({ type: 'object', properties, required, additionalProperties: false })
  useEffect(() => () => { connection.current?.stop(); if (connection.current) void api.del(`/agents/devices/${connection.current.device}`).catch(() => {}) }, [])
  const save = useAgentMutation(() => api.post(`/agents/sessions/${sid}/artifacts`, { title, kind: kind === 'sheet' ? 'json' : 'text', content }))
  const attach = async () => {
    if (connection.current) {
      connection.current.stop()
      await api.del(`/agents/devices/${connection.current.device}`)
      connection.current = undefined
      setConnected(false)
      return
    }
    setConnecting(true)
    try {
      if (kind === 'sheet' && !Array.isArray(JSON.parse(text.current))) throw new Error('Sheet source must be a JSON array of rows')
      const host = await api.post<AgentHost>('/agents/host/gateway')
      const grant = await api.post<DeviceGrant>('/agents/devices', { name: `Editor: ${title}`, scopes: ['documents'], session_ids: [sid] })
      const commands: Record<string, DocumentCommand> = kind === 'sheet' ? {
        read_sheet: { description: 'Read all rows from this live sheet', parameters: object({}), execute: () => JSON.parse(text.current) },
        set_sheet: { description: 'Replace this sheet with an array of rows', parameters: object({ rows: { type: 'array', items: { type: 'array' } } }, ['rows']), execute: a => { if (!Array.isArray(a.rows)) throw new Error('Expected rows'); change(JSON.stringify(a.rows, null, 2)); return { updated: true } } },
        update_cell: { description: 'Set one cell using zero-based row and column indexes', parameters: object({ row: { type: 'integer', minimum: 0 }, column: { type: 'integer', minimum: 0 }, value: {} }, ['row', 'column', 'value']), execute: a => {
          const rows = JSON.parse(text.current) as unknown[][]
          const row = Number(a.row), column = Number(a.column)
          if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || column < 0 || row >= rows.length || !Array.isArray(rows[row]) || column >= rows[row].length) throw new Error('Cell is outside the sheet')
          rows[row][column] = a.value; change(JSON.stringify(rows, null, 2)); return { updated: true, row, column }
        } },
      } : {
        read_text: { description: 'Read this live document', parameters: object({}), execute: () => ({ text: text.current }) },
        replace_text: { description: 'Replace one exact unique passage', parameters: object({ old: { type: 'string' }, replacement: { type: 'string' } }, ['old','replacement']), execute: a => {
          const old = String(a.old)
          if (!old || text.current.split(old).length !== 2) throw new Error('Passage must occur exactly once')
          change(text.current.replace(old, String(a.replacement))); return { updated: true }
        } },
        append_text: { description: 'Append text to this live document', parameters: object({ text: { type: 'string' } }, ['text']), execute: a => { change(text.current + String(a.text)); return { updated: true } } },
      }
      const url = new URL(host.gateway_url)
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      url.pathname = '/documents'
      connection.current = { device: grant.device.id, stop: connectDocument({ url: url.toString(), token: grant.token, sessionId: sid, title, kind, commands,
        onState: state => { setConnecting(false); setConnected(state === 'connected'); if (state === 'error') toast.error('Document could not connect', 'Check that the device gateway is running.') } }) }
    } catch (e) { setConnecting(false); toast.error('Document could not connect', (e as Error).message) }
  }
  return <section className={s.panel}><h2>Live documents</h2><p>Attach an editor to a conversation. The agent discovers its actual commands and uses them through normal approvals.</p>{error && <p>{error.message}</p>}
    <details className={s.row}><summary>Connect Word, Excel or PowerPoint</summary><p>Configure HTTPS and trust the gateway certificate in Connections. Download the manifest for your Office application, sideload it, then enter a document-scoped device token and its conversation ID in the task pane. Your Office version must support the advertised APIs.</p>
      {host?.gateway_running && host.gateway_tls ? <div className={s.actions}>{['word','excel','powerpoint'].map(kind => <a key={kind} href={`${host.gateway_url}/office/manifest.xml?host=${kind}&base_url=${encodeURIComponent(host.gateway_url)}`} download>{kind} add-in manifest</a>)}</div> : <p>Start a trusted HTTPS gateway to enable Office add-in downloads.</p>}
    </details>
    <Field label="Document conversation"><Select aria-label="Document conversation" disabled={connected || connecting} value={sid} onValueChange={setSid} placeholder="Choose a conversation" options={(data?.sessions ?? []).map(c => ({ value: c.id, label: c.title }))} /></Field>
    <Field label="Document title"><Input aria-label="Document title" disabled={connected || connecting} value={title} onChange={e => setTitle(e.target.value)} /></Field>
    <Field label="Document format"><Select aria-label="Document format" disabled={connected || connecting} value={kind} onValueChange={v => { setKind(v); change(v === 'sheet' ? '[[]]' : '') }} options={[{ value: 'text', label: 'Text document' }, { value: 'sheet', label: 'Sheet (JSON rows)' }]} /></Field>
    <Field label="Live document source"><Textarea aria-label="Live document source" value={content} onChange={e => change(e.target.value)} rows={18} /></Field>
    <div className={s.actions}><Button disabled={!sid || connecting} onClick={() => void attach()}>{connected ? 'Disconnect editor' : 'Connect editor'}</Button><Button variant="secondary" disabled={!sid || save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => toast.success('Artifact saved'), onError: e => toast.error('Document could not be saved', e.message) })}>Save as artifact</Button><Badge>{connected ? 'Connected' : 'Local editor'}</Badge></div>
    {documents?.map(d => <article className={s.row} key={d.id}><h3>{d.title}</h3><Badge>{d.kind}</Badge><p>{d.tools.map(t => t.name).join(', ')}</p></article>)}
  </section>
}
