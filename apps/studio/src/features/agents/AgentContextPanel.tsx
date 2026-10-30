import { useState } from 'react'
import { ArrowLeft, FileText, Settings2 } from 'lucide-react'
import { Badge, Button } from '@studio/ui'
import { useAgentArtifacts, useAgents } from '../../api/agents'
import { Markdown } from '../chat/Markdown'
import { openSettings } from '../settings/settingsState'
import { MissionProgress } from '../agentPlus/AgentPlusPage'
import ActivityPanel from './ActivityPanel'
import DocumentsPanel from './DocumentsPanel'
import ArtifactsPanel from './ArtifactsPanel'
import DelegationsPanel from './DelegationsPanel'
import ActionControls from './ActionControls'
import s from './AgentContextPanel.module.css'

export default function AgentContextPanel({ sessionId }: { sessionId?: string }) {
  const [view, setView] = useState('context')
  const { data } = useAgents()
  const { data: artifacts } = useAgentArtifacts()
  const mission = data?.missions.find(item => item.session_id === sessionId)
  const items = artifacts?.filter(item => item.session_id === sessionId) ?? []
  if (view !== 'context') return <div className={s.subview}><Button variant="ghost" size="sm" iconLeft={<ArrowLeft />} onClick={() => setView('context')}>Back to context</Button>{view === 'operations' && sessionId ? <ActionControls key={sessionId} sid={sessionId} /> : view === 'documents' ? <DocumentsPanel /> : view === 'artifacts' ? <ArtifactsPanel /> : <ActivityPanel />}</div>
  return <div className={s.panel}>
    <header><div><h2>Conversation context</h2><p>Saved work and ongoing tasks.</p></div><Button variant="ghost" size="sm" iconLeft={<Settings2 />} onClick={() => openSettings('agent')}>Settings</Button></header>
    {mission && sessionId && <MissionProgress sessionId={sessionId} />}
    {sessionId && <DelegationsPanel sid={sessionId} />}
    <section className={s.section}><div className={s.heading}><FileText size={16} /><h3>Artifacts</h3>{items.length > 0 && <Badge>{items.length}</Badge>}</div>
      {!items.length && <p>Documents and other work saved in this conversation will appear here.</p>}
      {items.map(item => <details key={item.id} className={s.artifact}><summary>{item.title}<Badge>v{item.version}</Badge></summary><div>{item.kind === 'markdown' ? <Markdown text={item.content} /> : <pre>{item.content}</pre>}<a href={`/api/agents/artifacts/${item.id}/export`} download>Download</a></div></details>)}
    </section>
    <div className={s.links}>{sessionId && <Button variant="ghost" size="sm" onClick={() => setView('operations')}>Ongoing work & boundaries</Button>}{items.length > 0 && <Button variant="ghost" size="sm" onClick={() => setView('artifacts')}>Edit artifacts</Button>}<Button variant="ghost" size="sm" onClick={() => setView('documents')}>Connect a document</Button><Button variant="ghost" size="sm" onClick={() => setView('activity')}>Activity & notifications</Button></div>
  </div>
}
