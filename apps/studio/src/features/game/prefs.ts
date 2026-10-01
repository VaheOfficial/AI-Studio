import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface GamePrefs {
  /** Narrate each new turn aloud as it arrives. */
  autoRead: boolean
  /** Play the current location's composed music. */
  music: boolean
  setAutoRead: (on: boolean) => void
  setMusic: (on: boolean) => void
}

export const useGamePrefs = create<GamePrefs>()(
  persist(
    (set) => ({
      autoRead: false,
      music: true,
      setAutoRead: (autoRead) => set({ autoRead }),
      setMusic: (music) => set({ music }),
    }),
    { name: 'studio-game-prefs' },
  ),
)
