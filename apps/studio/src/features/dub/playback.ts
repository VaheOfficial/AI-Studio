import { create } from 'zustand'

/** Shared clock between the preview player, the timeline playhead and the segment list. */
interface PlaybackState {
  time: number
  playing: boolean
  /** A seek or range-play request for the player (nonce makes repeats distinct). */
  request: { start: number; end?: number; nonce: number } | null
  setTime: (time: number) => void
  setPlaying: (playing: boolean) => void
  seek: (start: number) => void
  playRange: (start: number, end: number) => void
}

let nonce = 0

export const usePlayback = create<PlaybackState>((set) => ({
  time: 0,
  playing: false,
  request: null,
  setTime: (time) => set({ time }),
  setPlaying: (playing) => set({ playing }),
  seek: (start) => set({ request: { start, nonce: ++nonce } }),
  playRange: (start, end) => set({ request: { start, end, nonce: ++nonce } }),
}))
