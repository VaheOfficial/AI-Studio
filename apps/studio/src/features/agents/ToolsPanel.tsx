import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ChevronRight, Search, ShieldCheck, Wrench } from 'lucide-react'
import { Badge, Button, Input, Select, Skeleton } from '@studio/ui'
import { api } from '../../api/client'
import { useAgentCapabilities } from '../../api/agents'
import type { CapabilityFamily } from '../../api/contracts/agents'
import { toolMeta, toolLabel, toolSummary } from '../chat/toolMeta'
import CoveragePanel from './CoveragePanel'
import s from './AgentsPage.module.css'

export default function ToolsPanel() {
  const [query, setQuery] = useState('')
  const [family, setFamily] = useState('all')
  const [view, setView] = useState('tools')
  const { data, isLoading, error, refetch } = useAgentCapabilities()
  const coverage = useQuery({ queryKey: ['agents', 'coverage'], queryFn: () => api.get<CapabilityFamily[]>('/agents/coverage') })
  const selected = coverage.data?.find(item => item.id === family)
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const tools = (data ?? []).filter(tool => (!selected || selected.tools.includes(tool.name)) && terms.every(term => `${tool.name} ${toolMeta(tool.name).verb} ${tool.description}`.toLowerCase().includes(term)))
  return <section className={s.panel}>
    <div className={s.titleRow}><div><h2>Tool library</h2><p>One agent, with the right tools for each task.</p></div><Link className={s.textLink} to="/agents/services">Connect an application <ChevronRight size={14} /></Link></div>
    <div className={s.toolbar}>
      <div className={s.search}><Input iconLeft={<Search size={16} />} aria-label="Find a tool" placeholder="Search tools by name or task…" value={query} onChange={event => setQuery(event.target.value)} /></div>
      <Select aria-label="Tool category" value={family} onValueChange={setFamily} options={[{ value: 'all', label: 'All categories' }, ...(coverage.data ?? []).map(item => ({ value: item.id, label: item.name }))]} />
    </div>
    <div className={s.viewBar}><div className={s.segmented} role="group" aria-label="Tool library view"><button aria-pressed={view === 'tools'} onClick={() => setView('tools')}>Tools{data && <span>{tools.length}</span>}</button><button aria-pressed={view === 'setup'} onClick={() => setView('setup')}>Setup status</button></div><span className={s.hint}>Tools are discovered as needed</span></div>
    {view === 'setup' ? <CoveragePanel query={query} family={family} /> : <>
      {selected && <p className={s.notice}>{selected.requirements}</p>}
      {isLoading && <Skeleton height={160} />}
      {error && <div className={s.empty} role="alert"><p>{error.message}</p><Button variant="secondary" onClick={() => void refetch()}>Retry</Button></div>}
      {!isLoading && !error && !tools.length && <div className={s.empty}><Wrench size={24} /><h3>No matching tools</h3><p>Try another task or category.</p><Button variant="secondary" onClick={() => { setQuery(''); setFamily('all') }}>Clear filters</Button></div>}
      <div className={s.toolGrid}>{tools.map(tool => {
        const meta = toolMeta(tool.name)
        return <details className={s.toolCard} key={tool.name}>
          <summary><span className={s.toolIcon}>{meta.icon}</span><span className={s.toolInfo}><strong>{toolLabel(tool.name)}</strong><span>{toolSummary(tool.name, tool.description)}</span></span><ChevronRight className={s.disclosureIcon} size={15} /></summary>
          <div className={s.toolDetail}><div className={s.actions}><Badge>{tool.origin}</Badge>{tool.needs_approval && <Badge icon={<ShieldCheck size={12} />}>Approval required</Badge>}</div><p>{tool.description}</p><code className={s.hint}>{tool.name}</code><details className={s.technical}><summary>Input schema</summary><pre>{JSON.stringify(tool.parameters, null, 2)}</pre></details></div>
        </details>
      })}</div>
    </>}
  </section>
}
