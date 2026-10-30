import { useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { AudioLines, Blocks, Brain, Cpu, Folder, KeyRound, Palette, Plug, Settings2, ShieldCheck, Sparkles, Wrench } from 'lucide-react'
import { ConfirmDialog, Dialog } from '@studio/ui'
import SettingsPage from './SettingsPage'
import { useSettingsDialog } from './settingsState'
import { AgentSettings, Skills } from '../agents/AgentPreferences'
import ServicesPanel from '../agents/ServicesPanel'
import ConnectionsPanel from '../agents/ConnectionsPanel'
import MemoryPanel from '../agents/MemoryPanel'
import VoicePanel from '../agents/VoicePanel'
import ToolsPanel from '../agents/ToolsPanel'
import s from './SettingsModal.module.css'

const SECTIONS = [
  { title: 'Studio', items: [['general', 'Appearance & updates', Palette], ['models', 'Models & runtime', Cpu], ['providers', 'Providers & keys', KeyRound], ['storage', 'Storage', Folder]] },
  { title: 'Agent', items: [['agent', 'Behavior', Settings2], ['permissions', 'Permissions', ShieldCheck], ['skills', 'Skills', Sparkles], ['memory', 'Memory', Brain], ['tools', 'Tool library', Wrench]] },
  { title: 'Connections', items: [['applications', 'Applications', Blocks], ['devices', 'Devices & plugins', Plug], ['voice', 'Voice', AudioLines]] },
] as const
const CORE = new Set(['general', 'models', 'providers', 'storage', 'permissions'])

export default function SettingsModal() {
  const { open, section, setSection, setOpen } = useSettingsDialog()
  const [dirty, setDirty] = useState(false)
  const [discard, setDiscard] = useState(false)
  const reduced = useReducedMotion()
  return <>
    <Dialog open={open} onOpenChange={value => { if (!value && dirty) setDiscard(true); else setOpen(value) }} title="Settings" size="xl" className={s.dialog}>
      <div className={s.layout}>
        <nav className={s.navigation} aria-label="Settings categories">{SECTIONS.map(group => <div key={group.title} className={s.group}><span>{group.title}</span>{group.items.map(([id, label, Icon]) => <button key={id} aria-current={section === id ? 'page' : undefined} onClick={() => setSection(id)}>{section === id && <motion.span layoutId="settings-selection" className={s.selection} transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 450, damping: 38 }} />}<Icon size={16} /><span>{label}</span></button>)}</div>)}</nav>
        <div className={s.body}>
          <div hidden={!CORE.has(section)} className={s.core}><SettingsPage category={section} onDirtyChange={setDirty} /></div>
          {!CORE.has(section) && <motion.div key={section} className={s.detail} initial={reduced ? false : { opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .18 }}>
            {section === 'agent' ? <AgentSettings /> : section === 'skills' ? <Skills /> : section === 'memory' ? <MemoryPanel /> : section === 'tools' ? <ToolsPanel /> : section === 'applications' ? <ServicesPanel /> : section === 'devices' ? <ConnectionsPanel /> : <VoicePanel />}
          </motion.div>}
        </div>
      </div>
    </Dialog>
    <ConfirmDialog open={discard} onOpenChange={setDiscard} title="Discard unsaved settings?" description="Your saved settings will stay as they are." confirmLabel="Discard changes" tone="danger" onConfirm={() => { setDirty(false); setOpen(false) }} />
  </>
}
