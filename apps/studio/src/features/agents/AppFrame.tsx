import { useEffect, useRef, useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { AppBridge, PostMessageTransport } from '@modelcontextprotocol/ext-apps/app-bridge'

import { Button } from '@studio/ui'

import { api } from '../../api/client'

import { agent, useLive } from '../../api/live'

import type { ApplicationResource } from '../../api/contracts/agents'

import type { ToolDisplay } from '../../api/contracts/workspace'

import s from './AgentsPage.module.css'



type Display = Extract<ToolDisplay, { kind: 'app' }>

type Result = Awaited<ReturnType<NonNullable<AppBridge['oncalltool']>>>

type ReadResult = Awaited<ReturnType<NonNullable<AppBridge['onreadresource']>>>

type Listing = Awaited<ReturnType<NonNullable<AppBridge['onlistresources']>>>

type Templates = Awaited<ReturnType<NonNullable<AppBridge['onlistresourcetemplates']>>>

interface Request { title: string; detail: string; execute: () => Promise<unknown>; resolve: (value: unknown) => void; reject: (reason: Error) => void }

function origins(values?: string[]) {

  return [...new Set((values ?? []).slice(0, 30).flatMap(value => {

    try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && url.pathname === '/' && !url.search && !url.hash ? [url.origin] : [] } catch { return [] }

  }))]

}

function policy(connect: string[], resources: string[]) {

  const directives = `default-src 'none'; script-src 'unsafe-inline' ${resources.join(' ')}; style-src 'unsafe-inline' ${resources.join(' ')}; img-src data: blob: ${resources.join(' ')}; font-src data: ${resources.join(' ')}; media-src data: blob: ${resources.join(' ')}; connect-src ${connect.length ? connect.join(' ') : "'none'"}; form-action 'none'; frame-src 'none'; base-uri 'none'`

  return `<meta http-equiv="Content-Security-Policy" content="${directives.replace(/"/g, '&quot;')}">`

}



export default function AppFrame({ display }: { display: Display }) {

  const frame = useRef<HTMLIFrameElement>(null)

  const [failure, setFailure] = useState('')

  const [queue, setQueue] = useState<Request[]>([])

  const pending = useRef<Request[]>([])

  const [running, setRunning] = useState(false)

  const [networkGrant, setNetworkGrant] = useState('')

  const { data, error } = useQuery({ queryKey: ['agents', 'app-resource', display.connector_id, display.resource_uri],

    queryFn: () => api.get<ApplicationResource>(`/agents/connections/${display.connector_id}/resource?uri=${encodeURIComponent(display.resource_uri)}`) })

  const resource = data?.contents.find(content => content.text && content.mimeType?.includes('html'))

  const html = resource?.text

  const csp = resource?._meta?.ui?.csp

  const connect = origins(csp?.connectDomains), resources = origins(csp?.resourceDomains)

  const networkIdentity = JSON.stringify([display.connector_id,display.resource_uri,connect,resources])

  const networkAllowed = networkGrant === networkIdentity

  useEffect(() => {

    if (!html || !frame.current?.contentWindow) return

    setFailure(''); setQueue([])

    const review = <T,>(title: string, detail: string, execute: () => Promise<T>): Promise<T> => new Promise((resolve, reject) => {

      if (pending.current.length >= 20 || detail.length > 64000) { reject(Error('Application request limit exceeded')); return }

      pending.current = [...pending.current, { title, detail, execute, resolve: value => resolve(value as T), reject }]

      setQueue(pending.current)

    })

    const instance = new AppBridge(null, { name: 'Grom AI Studio', version: '0.2.1' }, { serverTools: {}, serverResources: {}, openLinks: {}, downloadFile: {}, message: { text: {} }, updateModelContext: { text: {}, structuredContent: {} } })

    const base = `/agents/connections/${display.connector_id}`

    instance.oncalltool = params => review('Application tool action', params.name + '\n' + JSON.stringify(params.arguments ?? {}, null, 2), () => api.post<Result>(base + '/call', { session_id: display.session_id, name: params.name, arguments: params.arguments ?? {} }))

    instance.onlistresources = () => api.get<{ resources: Listing['resources'] }>(base + '/resources').then(value => ({ resources: value.resources }))

    instance.onlistresourcetemplates = () => api.get<{ templates: Templates['resourceTemplates'] }>(base + '/resources').then(value => ({ resourceTemplates: value.templates }))

    instance.onreadresource = params => review('Read application resource', params.uri, () => api.get<ReadResult>(base + '/resource?uri=' + encodeURIComponent(params.uri)))

    instance.onupdatemodelcontext = params => review('Share application context with the agent', JSON.stringify(params, null, 2), async () => {

      if ((params.content ?? []).some(item => item.type !== 'text')) throw Error('Only text and structured application context are supported')

      await api.put(base + '/context', { session_id: display.session_id, content: JSON.stringify(params) }); return {}

    })

    instance.onmessage = params => review('Send application content to the conversation', JSON.stringify(params, null, 2), async () => {

      if (useLive.getState().turns[display.session_id]?.streaming) throw Error('Pause or finish the agent turn first')

      if (params.content.some(item => item.type !== 'text')) throw Error('Only text messages are supported')

      const text = params.content.filter(item => item.type === 'text').map(item => item.text).join('\n')

      if (!text.trim() || text.length > 16000) throw Error('Application message must contain 1 to 16,000 characters')

      if (!agent.send(display.session_id, 'Application source material (reviewed by the user):\n' + text)) return { isError: true }

      return {}

    })

    instance.onopenlink = params => review('Open application link', params.url, async () => {

      const url = new URL(params.url)

      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw Error('Unsupported link')

      window.open(url.href, '_blank', 'noopener,noreferrer'); return {}

    })

    instance.ondownloadfile = params => review('Download application files', JSON.stringify(params.contents.map(item => ({ type:item.type, ...(item.type === 'resource_link' ? {uri:item.uri,name:item.name} : {uri:item.resource.uri,mimeType:item.resource.mimeType}) })), null, 2), async () => {
      if (params.contents.length > 20) throw Error('Download at most 20 files per request')
      for (const [index,item] of params.contents.entries()) {
        const contents = item.type === 'resource_link' ? (await api.get<ReadResult>(base + '/resource?uri=' + encodeURIComponent(item.uri))).contents : [item.resource]
        for (const content of contents) {
          const raw = 'text' in content ? new TextEncoder().encode(content.text) : Uint8Array.from(atob(content.blob), character => character.charCodeAt(0))
          if (raw.length > 1024 * 1024) throw Error('Application file exceeds the 1 MiB download limit')
          const bytes = new Uint8Array(raw.length); bytes.set(raw)
          const blob = new Blob([bytes.buffer], {type:content.mimeType ?? 'application/octet-stream'})
          const url = URL.createObjectURL(blob), anchor = document.createElement('a')
          anchor.href = url; anchor.download = ((item.type === 'resource_link' ? item.name : content.uri.split('/').pop()) || `application-file-${index+1}`).replace(/[^a-zA-Z0-9._-]/g,'_').slice(0,120)
          anchor.click(); setTimeout(() => URL.revokeObjectURL(url),1000)
        }
      }
      return {}
    })
    instance.oninitialized = () => { void instance.sendToolInput({ arguments: display.arguments }).then(() => instance.sendToolResult(display.result as Result)).catch(reason => setFailure((reason as Error).message)) }

    instance.onsizechange = params => { if (frame.current && params.height) frame.current.style.height = `${Math.max(160, Math.min(params.height, 900))}px` }

    let disposed = false

    const target = frame.current

    void instance.connect(new PostMessageTransport(target.contentWindow!, target.contentWindow!)).then(() => {

      if (!disposed) target.srcdoc = policy(networkAllowed ? origins(csp?.connectDomains) : [], networkAllowed ? origins(csp?.resourceDomains) : []) + html

    }).catch(reason => { if (!disposed) setFailure((reason as Error).message) })

    return () => { disposed = true; pending.current.forEach(request => request.reject(Error('Application view closed'))); pending.current = []; void instance.close() }

  }, [html, csp, networkAllowed, display.arguments, display.result, display.connector_id, display.session_id])

  const decide = async (approved: boolean) => {

    const request = pending.current[0]

    if (!request) return

    setRunning(true)

    try { if (approved) request.resolve(await request.execute()); else request.reject(Error('Action denied by user')) }

    catch (reason) { request.reject(reason as Error); setFailure((reason as Error).message) }

    finally { pending.current = pending.current.filter(item => item !== request); setQueue(pending.current); setRunning(false) }

  }

  return <div className={s.row}>

    {(error || failure) && <p role="alert">{error?.message || failure}</p>}

    {(connect.length > 0 || resources.length > 0) && <details><summary>Application network access · {networkAllowed ? 'allowed' : 'blocked'}</summary><p>Network access exposes this view’s tool results to the listed application origins.</p><pre>{JSON.stringify({ connections: connect, resources }, null, 2)}</pre><Button variant="secondary" disabled={running} onClick={() => setNetworkGrant(networkAllowed ? '' : networkIdentity)}>{networkAllowed ? 'Block network and reload' : 'Allow listed origins and reload'}</Button></details>}

    {html && <iframe ref={frame} className={s.preview} title={display.title} sandbox="allow-scripts" referrerPolicy="no-referrer" />}

    {queue[0] && <section aria-label="Application action approval"><p>{queue[0].title}</p><pre>{queue[0].detail}</pre><div className={s.actions}><Button variant="secondary" onClick={() => agent.stop(display.session_id)}>Pause agent</Button><Button disabled={running} onClick={() => void decide(true)}>Approve</Button><Button variant="ghost" disabled={running} onClick={() => void decide(false)}>Deny</Button></div></section>}

  </div>

}

