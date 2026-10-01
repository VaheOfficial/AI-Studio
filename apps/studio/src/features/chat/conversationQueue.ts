import { create } from 'zustand'

/**
 * Follow-up queue (port of OpenMuse `conversation-queue.ts`): one turn at a time per chat while the user keeps
 * composing. Stopping a reply pauses the queue; held messages are only sent after an explicit resume, and a
 * message that failed to send is never re-sent implicitly.
 */
export interface QueuedMessage {
  id: string
  text: string
  files: File[]
}

interface ChatQueue {
  pending: QueuedMessage[]
  paused: boolean
}

interface QueueState {
  queues: Record<string, ChatQueue>
  enqueue: (sid: string, message: QueuedMessage) => void
  remove: (sid: string, id: string) => void
  /** Take the next message if the queue may flush. */
  take: (sid: string) => QueuedMessage | undefined
  pause: (sid: string) => void
  resume: (sid: string) => void
}

const EMPTY: ChatQueue = { pending: [], paused: false }

export const useConversationQueue = create<QueueState>((set, get) => {
  const patch = (sid: string, fn: (q: ChatQueue) => ChatQueue) =>
    set((s) => ({ queues: { ...s.queues, [sid]: fn(s.queues[sid] ?? EMPTY) } }))
  return {
    queues: {},
    enqueue: (sid, message) => patch(sid, (q) => ({ ...q, pending: [...q.pending, message] })),
    remove: (sid, id) => patch(sid, (q) => ({ ...q, pending: q.pending.filter((m) => m.id !== id) })),
    take: (sid) => {
      const q = get().queues[sid] ?? EMPTY
      if (q.paused || !q.pending.length) return undefined
      const [next, ...rest] = q.pending
      patch(sid, () => ({ ...q, pending: rest }))
      return next
    },
    pause: (sid) => patch(sid, (q) => ({ ...q, paused: true })),
    resume: (sid) => patch(sid, (q) => ({ ...q, paused: false })),
  }
})

export const useChatQueue = (sid: string | undefined) => useConversationQueue((s) => (sid ? s.queues[sid] : undefined) ?? EMPTY)
