import { useState } from 'react'
import { ChevronDown, ChevronRight, Pencil, Plug, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { Button, ConfirmDialog, Dialog, Field, IconButton, Input, SegmentedControl, StatusDot, Switch, Textarea } from '@studio/ui'
import { useConnectors, useCreateConnector, useDeleteConnector, useTestConnector, useUpdateConnector } from '../../api/connectors'
import type { Connector, ConnectorApproval, ConnectorStatus, ConnectorTransport } from '../../api/contracts/connectors'
import { SettingsSection } from './form'
import s from './ConnectorsSection.module.css'

const DOT: Record<ConnectorStatus, 'active' | 'busy' | 'error' | 'off'> = {
  connected: 'active',
  connecting: 'busy',
  error: 'error',
  disabled: 'off',
}
const STATUS_TEXT: Record<ConnectorStatus, string> = {
  connected: 'Connected',
  connecting: 'Connecting…',
  error: 'Not connected',
  disabled: 'Off',
}

/** MCP connectors: apps and services whose tools the agent can use. The studio ships none; any MCP server works. */
export function ConnectorsSection() {
  const { data: connectors = [] } = useConnectors()
  const [editing, setEditing] = useState<Connector | 'new' | null>(null)
  const [removing, setRemoving] = useState<Connector | null>(null)
  const del = useDeleteConnector()
  return (
    <SettingsSection
      icon={<Plug />}
      title="Connectors"
      description="Connect apps and services through MCP servers. Their tools become available to the agent in Agent chats. Any MCP server works: a local program (stdio) or a remote URL."
    >
      {connectors.length > 0 ? (
        <ul className={s.list}>
          {connectors.map((c) => (
            <ConnectorRow key={c.id} c={c} onEdit={() => setEditing(c)} onRemove={() => setRemoving(c)} />
          ))}
        </ul>
      ) : (
        <p className={s.empty}>No connectors yet. Add an MCP server to let the agent use its tools.</p>
      )}
      <div>
        <Button size="sm" variant="secondary" iconLeft={<Plus />} onClick={() => setEditing('new')}>
          Add connector
        </Button>
      </div>
      {editing && <ConnectorEditor connector={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.name}?`}
        description="The agent loses its tools. The MCP server itself isn't uninstalled."
        confirmLabel="Remove"
        tone="danger"
        onConfirm={() => {
          if (removing) del.mutate(removing.id)
          setRemoving(null)
        }}
      />
    </SettingsSection>
  )
}

function ConnectorRow({ c, onEdit, onRemove }: { c: Connector; onEdit: () => void; onRemove: () => void }) {
  const update = useUpdateConnector()
  const test = useTestConnector()
  const [open, setOpen] = useState(false)
  const where = c.transport === 'stdio' ? [c.command, ...c.args].join(' ') : c.url
  return (
    <li className={s.row}>
      <div className={s.head}>
        <StatusDot status={DOT[c.status]} label={STATUS_TEXT[c.status]} />
        <div className={s.titles}>
          <span className={s.name}>{c.name}</span>
          <span className={s.where} title={where}>
            {where}
          </span>
        </div>
        <Switch checked={c.enabled} onCheckedChange={(on) => update.mutate({ id: c.id, enabled: on })} aria-label={c.enabled ? 'Turn off' : 'Turn on'} />
      </div>
      <div className={s.meta}>
        <span>{STATUS_TEXT[c.status]}</span>
        {c.status === 'connected' && (
          <button className={s.toggle} onClick={() => setOpen(!open)}>
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {c.tools.length} tool{c.tools.length === 1 ? '' : 's'}
          </button>
        )}
        <span>{c.approval === 'ask' ? 'Asks before each tool call' : 'Runs tools without asking'}</span>
      </div>
      {c.error && <p className={s.error}>{c.error}</p>}
      {open && (
        <ul className={s.tools}>
          {c.tools.map((t) => (
            <li key={t.name}>
              <code>{t.name}</code>
              {t.description && <span>{t.description}</span>}
            </li>
          ))}
        </ul>
      )}
      <div className={s.actions}>
        <Button size="sm" variant="ghost" iconLeft={<RefreshCw />} loading={test.isPending} disabled={!c.enabled} onClick={() => test.mutate(c.id)}>
          Test
        </Button>
        <span className={s.spacer} />
        <IconButton size="sm" label="Edit" icon={<Pencil />} onClick={onEdit} />
        <IconButton size="sm" label="Remove" variant="danger" icon={<Trash2 />} onClick={onRemove} />
      </div>
    </li>
  )
}

const toLines = (m: Record<string, string>, sep: string) =>
  Object.entries(m)
    .map(([k, v]) => `${k}${sep}${v}`)
    .join('\n')

function fromLines(text: string, sep: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const i = line.indexOf(sep)
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + sep.length).trim()
  }
  return out
}

function ConnectorEditor({ connector, onClose }: { connector?: Connector; onClose: () => void }) {
  const create = useCreateConnector()
  const update = useUpdateConnector()
  const [name, setName] = useState(connector?.name ?? '')
  const [transport, setTransport] = useState<ConnectorTransport>(connector?.transport ?? 'stdio')
  const [command, setCommand] = useState(connector?.command ?? '')
  const [args, setArgs] = useState((connector?.args ?? []).join('\n'))
  const [env, setEnv] = useState(toLines(connector?.env ?? {}, '='))
  const [url, setUrl] = useState(connector?.url ?? '')
  const [headers, setHeaders] = useState(toLines(connector?.headers ?? {}, ': '))
  const [approval, setApproval] = useState<ConnectorApproval>(connector?.approval ?? 'ask')
  const busy = create.isPending || update.isPending
  const valid = name.trim() && (transport === 'stdio' ? command.trim() : /^https?:\/\//.test(url.trim()))

  const save = () => {
    const body = {
      name: name.trim(),
      approval,
      ...(transport === 'stdio'
        ? { command: command.trim(), args: args.split('\n').map((a) => a.trim()).filter(Boolean), env: fromLines(env, '=') }
        : { url: url.trim(), headers: fromLines(headers, ':') }),
    }
    const done = { onSuccess: onClose }
    if (connector) update.mutate({ id: connector.id, ...body }, done)
    else create.mutate({ ...body, transport }, done)
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={connector ? `Edit ${connector.name}` : 'Add connector'}
      description="Any MCP server. Its tools show up for the agent as <name>__<tool>."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid} loading={busy} onClick={save}>
            {connector ? 'Save' : 'Add'}
          </Button>
        </>
      }
    >
      <div className={s.form}>
        <Field label="Name" hint="Short, e.g. GitHub, Notes, Calendar. It prefixes the tools' names.">
          {(id) => <Input id={id} value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Type">
          <SegmentedControl<ConnectorTransport>
            value={transport}
            onValueChange={(t) => !connector && setTransport(t)}
            segments={[
              { value: 'stdio', label: 'Local program' },
              { value: 'http', label: 'Remote URL' },
            ]}
          />
        </Field>
        {transport === 'stdio' ? (
          <>
            <Field label="Command" hint="The program that starts the server, e.g. npx, uvx, python or a full path.">
              {(id) => <Input id={id} value={command} placeholder="npx" onChange={(e) => setCommand(e.target.value)} />}
            </Field>
            <Field label="Arguments" hint="One per line.">
              {(id) => (
                <Textarea id={id} autoResize minRows={2} maxRows={8} value={args} placeholder={'-y\n@modelcontextprotocol/server-filesystem\nC:\\Notes'} onChange={(e) => setArgs(e.target.value)} />
              )}
            </Field>
            <Field label="Environment variables" hint="KEY=value, one per line: API tokens and settings the server needs. Stored values show as •••; leave them to keep them.">
              {(id) => <Textarea id={id} autoResize minRows={2} maxRows={8} value={env} placeholder="API_TOKEN=…" onChange={(e) => setEnv(e.target.value)} />}
            </Field>
          </>
        ) : (
          <>
            <Field label="URL" hint="The server's Streamable HTTP endpoint.">
              {(id) => <Input id={id} value={url} placeholder="https://example.com/mcp" onChange={(e) => setUrl(e.target.value)} />}
            </Field>
            <Field label="Headers" hint="Header: value, one per line (e.g. Authorization: Bearer …). Stored values show as •••.">
              {(id) => <Textarea id={id} autoResize minRows={2} maxRows={6} value={headers} onChange={(e) => setHeaders(e.target.value)} />}
            </Field>
          </>
        )}
        <Field label="Tool calls">
          <SegmentedControl<ConnectorApproval>
            value={approval}
            onValueChange={setApproval}
            segments={[
              { value: 'ask', label: 'Ask every time' },
              { value: 'auto', label: 'Run without asking' },
            ]}
          />
        </Field>
      </div>
    </Dialog>
  )
}
