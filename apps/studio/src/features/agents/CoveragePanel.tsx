import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ChevronRight, Wrench } from 'lucide-react'
import { Badge, Button, Select } from '@studio/ui'
import { useChatModels } from '../../api/hooks'
import { api } from '../../api/client'
import type { CapabilityFamily } from '../../api/contracts/agents'
import { toolMeta, toolLabel } from '../chat/toolMeta'
import s from './AgentsPage.module.css'

export default function CoveragePanel({ query = '', family = 'all' }: { query?: string; family?: string }) {
  const models = useChatModels()
  const [model, setModel] = useState('')
  const qc = useQueryClient()
  const check = useMutation({ mutationFn: () => api.post<{ tools: boolean; error?: string }>('/agents/model-checks', { model }), onSuccess: () => { void qc.invalidateQueries({ queryKey: ['agents'] }); void models.refetch() } })
  const { data, error, isLoading } = useQuery({ queryKey: ['agents', 'coverage'], queryFn: () => api.get<CapabilityFamily[]>('/agents/coverage') })
  const items = data?.filter(item => (family === 'all' || item.id === family) && `${item.name} ${item.tools.join(' ')} ${item.requirements}`.toLowerCase().includes(query.toLowerCase()))
  return <div className={s.coverage}>
    <p className={s.notice}>Available means prerequisites are present. Verified means a recorded check passed; it does not guarantee every task will succeed.</p>
    <div className={s.toolbar}><Select aria-label="Model to verify" value={model} onValueChange={setModel} options={[{ value: '', label: 'Choose a model to verify' }, ...(models.data ?? []).filter(item => item.available && item.provider !== 'openrouter').map(item => ({ value: item.id, label: item.name }))]} /><Button variant="secondary" disabled={!model || check.isPending} onClick={() => check.mutate()}>{check.isPending ? 'Checking…' : 'Verify tool protocol'}</Button></div>
    {check.error && <p role="alert">{check.error.message}</p>}
    {check.data && <p role="status">{check.data.tools ? 'Structured call and result readback passed.' : check.data.error ?? 'This model did not pass the tool protocol check.'}</p>}
    {error && <p role="alert">{error.message}</p>}
    {isLoading && <p className={s.hint}>Loading setup status…</p>}
    {items?.map(item => <details className={s.toolCard} key={item.id}>
      <summary><span className={s.toolIcon}>{item.tools[0] ? toolMeta(item.tools[0]).icon : <Wrench />}</span><span className={s.toolInfo}><strong>{item.name}</strong><span>{item.tools.length ? `${item.tools.length} tools` : 'Available after connection'}</span></span><Badge tone={item.verified ? 'success' : 'neutral'} dot>{item.status === 'ready' ? item.verified ? 'Verified' : 'Available' : item.status === 'unknown' ? 'Unverified' : item.status === 'unsupported' ? 'Unsupported' : 'Setup needed'}</Badge><ChevronRight className={s.disclosureIcon} size={15} /></summary>
      <div className={s.toolDetail}><p>{item.requirements}</p><div className={s.actions}>{item.tools.map(name => <Badge key={name}>{toolLabel(name)}</Badge>)}</div></div>
    </details>)}
    {!isLoading && !error && !items?.length && <p className={s.empty}>No categories match your search.</p>}
  </div>
}
