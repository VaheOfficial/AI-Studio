import { create } from 'zustand'

export const useSettingsDialog = create<{
  open: boolean
  section: string
  setOpen: (open: boolean) => void
  setSection: (section: string) => void
}>()(set => ({
  open: false,
  section: 'general',
  setOpen: open => set({ open }),
  setSection: section => set({ section }),
}))

export function openSettings(section = 'general') {
  useSettingsDialog.setState({ open: true, section })
}
