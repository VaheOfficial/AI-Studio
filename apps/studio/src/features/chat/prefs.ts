import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ChatPrefs {
  /** Show every thinking block and tool step expanded (readable, not raw) so a run can be followed live. */
  verbose: boolean
  setVerbose: (verbose: boolean) => void
}

export const useChatPrefs = create<ChatPrefs>()(
  persist((set) => ({ verbose: false, setVerbose: (verbose) => set({ verbose }) }), { name: 'studio-chat-prefs' }),
)
