import { useEffect } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { useAgents } from '../../api/agents'
import ChatPage from '../chat/ChatPage'
import MissionPage from '../agentPlus/AgentPlusPage'
import ArtifactsPanel from './ArtifactsPanel'
import ActivityPanel from './ActivityPanel'
import DocumentsPanel from './DocumentsPanel'
import { openSettings } from '../settings/settingsState'

const SETTINGS_SECTIONS: Record<string, string> = { capabilities: 'tools', knowledge: 'memory', skills: 'skills', settings: 'agent', connections: 'devices', services: 'applications', voice: 'voice' }

export default function AgentsPage() {
  const { sessionId } = useParams()
  const section = useLocation().pathname.split('/')[2] || 'chat'
  const navigate = useNavigate()
  const { data } = useAgents()
  useEffect(() => {
    if (SETTINGS_SECTIONS[section]) {
      openSettings(SETTINGS_SECTIONS[section])
      navigate('/agents/chat', { replace: true })
    }
  }, [section, navigate])
  if (sessionId && (section === 'missions' || data?.missions.some(item => item.session_id === sessionId))) return <ChatPage basePath="/agents/missions" agentPlus />
  if (section === 'missions') return <MissionPage />
  if (section === 'artifacts') return <ArtifactsPanel />
  if (section === 'documents') return <DocumentsPanel />
  if (section === 'activity' || section === 'legacy') return <ActivityPanel />
  return <ChatPage />
}
