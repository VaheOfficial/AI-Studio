import { create } from 'zustand'

/** The chat's full-screen image viewer: any picture in the thread opens here (ChatPage renders the Lightbox). */
export const useChatLightbox = create<{
  src?: string
  caption?: string
  show: (src: string, caption?: string) => void
  close: () => void
}>((set) => ({
  show: (src, caption) => set({ src, caption }),
  close: () => set({ src: undefined, caption: undefined }),
}))
