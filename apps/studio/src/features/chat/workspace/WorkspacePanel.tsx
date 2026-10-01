import { useState } from 'react'
import { FolderOpen, FolderTree, Globe, ListChecks, PanelRightClose, SquareTerminal } from 'lucide-react'
import { Button, IconButton, Tabs, Tooltip, type TabItem } from '@studio/ui'
import type { ToolDisplay } from '../../../api/contracts/workspace'
import { useWorkspaceState } from '../../../api/workspace'
import { BrowserTab } from './BrowserTab'
import { FilesTab } from './FilesTab'
import { FolderPicker } from './FolderPicker'
import { useWorkspacePanel, type WorkspaceTab } from './panel'
import { TasksTab } from './TasksTab'
import { TerminalTab } from './TerminalTab'
import s from './WorkspacePanel.module.css'

const TABS: TabItem<WorkspaceTab>[] = [
  { value: 'terminal', label: <span className={s.tabLabel}>Terminal</span>, icon: <SquareTerminal size={14} /> },
  { value: 'files', label: <span className={s.tabLabel}>Files</span>, icon: <FolderTree size={14} /> },
  { value: 'browser', label: <span className={s.tabLabel}>Browser</span>, icon: <Globe size={14} /> },
  { value: 'tasks', label: <span className={s.tabLabel}>Tasks</span>, icon: <ListChecks size={14} /> },
]

export interface WorkspacePanelProps {
  /** Undefined for a chat that hasn't been created yet. */
  sessionId?: string
  /** Folder chosen before the chat exists; applied when it is created. */
  draftRoot?: string
  onDraftRoot: (root: string) => void
  /** Diffs the agent made in this chat (for the Files tab's change view). */
  diffs: Extract<ToolDisplay, { kind: 'diff' }>[]
}

/** The agent's computer, OpenMuse-style: terminal, files, browser and background tasks next to the chat. */
export function WorkspacePanel({ sessionId, draftRoot, onDraftRoot, diffs }: WorkspacePanelProps) {
  const { tab, setTab, setOpen } = useWorkspacePanel()
  const { data: state } = useWorkspaceState(sessionId)
  const [picking, setPicking] = useState(false)
  const root = sessionId ? state?.root : draftRoot
  const name = root?.split(/[\\/]/).filter(Boolean).pop()

  return (
    <aside className={s.panel} aria-label="Workspace">
      <header className={s.header}>
        <Tooltip content={root ? `${root} — change folder` : 'Choose the folder the agent works in'} side="bottom">
          <button className={s.folder} data-empty={!root || undefined} onClick={() => setPicking(true)}>
            <FolderOpen size={14} />
            <span>{name ?? 'Choose folder'}</span>
          </button>
        </Tooltip>
        <Tabs<WorkspaceTab> value={tab} onValueChange={setTab} items={TABS} variant="pill" className={s.tabs} />
        <IconButton label="Hide workspace" icon={<PanelRightClose />} size="sm" onClick={() => setOpen(false)} tooltipSide="bottom" />
      </header>

      <div className={s.body}>
        {!sessionId ? (
          <div className={s.intro}>
            <FolderOpen size={22} />
            <p>
              The agent works in a folder you choose on this PC: it can run commands in a terminal you can watch, edit files
              and drive a browser you can take over.
            </p>
            <Button variant="secondary" iconLeft={<FolderOpen />} onClick={() => setPicking(true)}>
              {draftRoot ? `Folder: ${name}` : 'Choose a folder'}
            </Button>
            <p className={s.hint}>Send a message to start; the terminal, files and browser appear here.</p>
          </div>
        ) : (
          <>
            <div className={s.pane} hidden={tab !== 'terminal'}>
              <TerminalTab sessionId={sessionId} root={root} onPickFolder={() => setPicking(true)} />
            </div>
            {tab === 'files' && (
              <div className={s.pane}>
                <FilesTab sessionId={sessionId} root={root} diffs={diffs} onPickFolder={() => setPicking(true)} />
              </div>
            )}
            {tab === 'browser' && (
              <div className={s.pane}>
                <BrowserTab sessionId={sessionId} />
              </div>
            )}
            {tab === 'tasks' && (
              <div className={s.pane}>
                <TasksTab sessionId={sessionId} plan={state?.plan ?? []} />
              </div>
            )}
          </>
        )}
      </div>

      {picking && <FolderPicker onClose={() => setPicking(false)} sessionId={sessionId} current={root} onDraft={onDraftRoot} />}
    </aside>
  )
}
