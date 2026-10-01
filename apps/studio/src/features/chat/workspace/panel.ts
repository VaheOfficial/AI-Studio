import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type WorkspaceTab = 'terminal' | 'files' | 'browser' | 'tasks'

interface PanelState {
  open: boolean
  size: number
  tab: WorkspaceTab
  /** Terminal to bring to front (set by tool cards). */
  terminalId?: string
  /** File to open in the Files tab (workspace-relative). */
  filePath?: string
  /** Soft-wrap long lines in the Files tab. */
  wrap: boolean
  setOpen: (open: boolean) => void
  setSize: (size: number) => void
  setTab: (tab: WorkspaceTab) => void
  showTerminal: (id: string) => void
  showFile: (path: string) => void
  showBrowser: () => void
  showTasks: () => void
  setWrap: (wrap: boolean) => void
}

/** Layout and navigation of the chat's workspace panel (persisted: open, width, tab, word wrap). */
export const useWorkspacePanel = create<PanelState>()(
  persist(
    (set) => ({
      open: true,
      size: 560,
      tab: 'terminal',
      wrap: true,
      setOpen: (open) => set({ open }),
      setSize: (size) => set({ size }),
      setTab: (tab) => set({ tab }),
      showTerminal: (terminalId) => set({ open: true, tab: 'terminal', terminalId }),
      showFile: (filePath) => set({ open: true, tab: 'files', filePath }),
      showBrowser: () => set({ open: true, tab: 'browser' }),
      showTasks: () => set({ open: true, tab: 'tasks' }),
      setWrap: (wrap) => set({ wrap }),
    }),
    { name: 'studio-workspace-panel', partialize: (s) => ({ open: s.open, size: s.size, tab: s.tab, wrap: s.wrap }) },
  ),
)
