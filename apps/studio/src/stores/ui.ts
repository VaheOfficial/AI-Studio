import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UIState {
  sidebarCollapsed: boolean
  commandOpen: boolean
  jobsOpen: boolean
  theme: 'dark' | 'light'
  /** Last model picked per page, so switching tabs doesn't reset selections. */
  lastModel: Record<string, string>
  toggleSidebar: () => void
  setCommandOpen: (open: boolean) => void
  setJobsOpen: (open: boolean) => void
  setTheme: (t: 'dark' | 'light') => void
  setLastModel: (page: string, id: string) => void
  /** Forget pages' remembered models, so they start from the Settings default again. */
  forgetModels: (pages: string[]) => void
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      commandOpen: false,
      jobsOpen: false,
      theme: 'dark',
      lastModel: {},
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setCommandOpen: (commandOpen) => set({ commandOpen }),
      setJobsOpen: (jobsOpen) => set({ jobsOpen }),
      setTheme: (theme) => set({ theme }),
      setLastModel: (page, id) => set((s) => ({ lastModel: { ...s.lastModel, [page]: id } })),
      forgetModels: (pages) =>
        set((s) => ({ lastModel: Object.fromEntries(Object.entries(s.lastModel).filter(([k]) => !pages.includes(k))) })),
    }),
    {
      name: 'studio-ui',
      partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed, theme: s.theme, lastModel: s.lastModel }),
    },
  ),
)
