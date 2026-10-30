import { useState } from 'react'
import { Plug, ChevronRight } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Field, Input, Textarea, toast } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentMutation } from '../../api/agents'
import type { AgentService, ServiceCreate, ServiceImport, ServiceReview, ServiceTemplate } from '../../api/contracts/agents'
import s from './AgentsPage.module.css'

export default function ServicesPanel() {
  const { data, error } = useQuery({ queryKey: ['agents', 'services'], queryFn: () => api.get<AgentService[]>('/agents/services') })
  const { data: templates = [] } = useQuery({ queryKey:['agents','service-templates'], queryFn:() => api.get<ServiceTemplate[]>('/agents/service-templates') })
  const [template, setTemplate] = useState('')
  const [choosing, setChoosing] = useState(true)
  const [headers, setHeaders] = useState('{}')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [source, setSource] = useState('')
  const [review, setReview] = useState<ServiceReview>()
  const err = (error: unknown) => toast.error('Service could not be updated', (error as Error).message)
  const inspect = useAgentMutation((body: ServiceImport) => api.post<ServiceReview>('/agents/services/import', body))
  const install = useAgentMutation((body: ServiceCreate) => api.post<AgentService>('/agents/services', body))
  const toggle = useAgentMutation((value: AgentService) => api.patch<AgentService>(`/agents/services/${value.id}`, { enabled: !value.enabled }))
  const remove = useAgentMutation((id: string) => api.del(`/agents/services/${id}`))
  const credentials = () => { const value: unknown = JSON.parse(headers); if (!value || typeof value !== 'object' || Array.isArray(value) || Object.values(value).some(item => typeof item !== 'string')) throw Error('Additional headers must be a JSON object with string values'); return { ...(value as Record<string,string>), ...(token ? {Authorization:'Bearer ' + token} : {}) } }
  const reviewTemplate = () => { try { const item = templates.find(value => value.id === template); if (!item) return; setReview({service:{...item.service,name,base_url:url,headers:credentials()},warnings:[item.requirements]}) } catch (error) { err(error) } }
  const installReviewed = () => { if (!review) return; try { install.mutate({...review.service,name,base_url:url,headers:credentials()}, {onSuccess:() => {setReview(undefined);setToken('');setHeaders('{}');setChoosing(true);toast.success('Service installed','Enable it after reviewing its operations.')},onError:err}) } catch(error) {err(error)} }
  return <section className={s.panel}><h2>Applications</h2><p>Connect the apps you use. Choose a starter, review its tools, then enable the connection.</p>{error && <p>{error.message}</p>}
    {choosing ? <div className={s.toolGrid}>{templates.map(item => <button className={s.appChoice} key={item.id} onClick={() => { setTemplate(item.id); setName(item.service.name); setUrl(item.service.base_url); setReview(undefined); setChoosing(false) }}><span className={s.toolIcon}><Plug /></span><span className={s.toolInfo}><strong>{item.service.name}</strong><span>{item.service.operations?.length ?? 0} tools available</span></span><ChevronRight size={15} /></button>)}<button className={s.appChoice} onClick={() => { setTemplate(''); setName(''); setUrl(''); setReview(undefined); setChoosing(false) }}><span className={s.toolIcon}><Plug /></span><span className={s.toolInfo}><strong>Custom application</strong><span>Import an OpenAPI specification</span></span><ChevronRight size={15} /></button></div> : <div className={s.actions}><Button variant="ghost" onClick={() => { setChoosing(true); setReview(undefined); setToken(''); setHeaders('{}') }}>Choose another application</Button><Badge>{template ? templates.find(item => item.id === template)?.service.name : 'Custom application'}</Badge></div>}
    {!choosing && <>
    {template && <a href={templates.find(item => item.id === template)?.documentation} target="_blank" rel="noreferrer">Application API documentation</a>}
    <form className={s.editor} onSubmit={e => {
      e.preventDefault()
      try { inspect.mutate({ name, base_url: url, document: JSON.parse(source) as Record<string, unknown>, headers: credentials() }, { onSuccess: setReview, onError: err }) }
      catch (error) { err(error) }
    }}><Field label="Service name"><Input aria-label="Service name" required value={name} onChange={e => { setName(e.target.value); setReview(undefined) }} placeholder="Application name" /></Field>
      <Field label="Service base URL"><Input aria-label="Service base URL" type="url" required value={url} onChange={e => { setUrl(e.target.value); setReview(undefined) }} placeholder="https://api.example.com" /></Field>
      <Field label="Service bearer token"><Input aria-label="Service bearer token" type="password" autoComplete="off" value={token} onChange={e => { setToken(e.target.value); setReview(undefined) }} placeholder="Bearer token (optional; OAuth is available in Connections)" /></Field>
      <details className={s.technical}><summary>Additional headers</summary><Field label="Additional service headers"><Textarea aria-label="Additional service headers" value={headers} onChange={event => { setHeaders(event.target.value); setReview(undefined) }} rows={3} placeholder="Additional headers as JSON (such as Notion-Version)" /></Field></details>
      {!template && <Field label="OpenAPI document"><Textarea aria-label="OpenAPI document" value={source} onChange={e => { setSource(e.target.value); setReview(undefined) }} rows={8} placeholder="Paste the OpenAPI 3 JSON specification" /></Field>}
      {!template && <Button type="submit" disabled={inspect.isPending}>Review operations</Button>}{template && <Button type="button" variant="secondary" onClick={reviewTemplate}>Review application starter</Button>}
    </form>
    {review && <article className={s.row}><h3>{review.service.operations?.length} operations found</h3>{review.warnings.map((warning, i) => <p key={i}>{warning}</p>)}
      <div className={s.operationList}>{review.service.operations?.map(operation => <div key={operation.id}><Badge>{operation.method}</Badge><span><strong>{operation.id.replaceAll('_', ' ')}</strong><small>{operation.description}</small></span></div>)}</div>
      <details className={s.technical}><summary>Technical details</summary><pre>{JSON.stringify({ ...review.service, headers: Object.fromEntries(Object.keys(review.service.headers ?? {}).map(key => [key, '•••'])) }, null, 2)}</pre></details>
      <Button disabled={install.isPending} onClick={installReviewed}>Install reviewed service</Button>
    </article>}
    </>}
    {!!data?.length && <h3>Connected applications</h3>}
    {data?.map(service => <details className={s.row} key={service.id}><summary>{service.name}<Badge>{service.enabled ? 'Enabled' : 'Disabled'}</Badge><Badge>{service.operations.length} tools</Badge></summary>
      <p>{service.base_url}</p><small>Connection ID for OAuth: {service.id}</small><details className={s.technical}><summary>Operation schemas</summary><pre>{JSON.stringify(service.operations, null, 2)}</pre></details>
      <div className={s.actions}><Button variant="secondary" disabled={toggle.isPending} onClick={() => toggle.mutate(service, { onError: err })}>{service.enabled ? 'Disable' : 'Enable reviewed tools'}</Button><Button variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(service.id, { onError: err })}>Remove service</Button></div>
    </details>)}
  </section>
}
