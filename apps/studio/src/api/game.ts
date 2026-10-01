/**
 * Game mode client (React Query). A turn runs on the server: its narration arrives as `game.delta` frames and the
 * result as `game.turn`, both applied to the cached game by `dispatchGame` (called from the socket dispatcher).
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { create } from 'zustand'
import { api } from './client'
import type { CombatRequest, Game, GamePatch, GameServerEvent, GameSummary, NewGameRequest } from './contracts/game'
import { useLive } from './live'
import type { Job } from './types'

export const gk = {
  list: ['games'] as const,
  game: (id: string) => ['game', id] as const,
}

const path = (id: string) => `/games/${encodeURIComponent(id)}`
const onError = (title: string) => (e: Error) => toast.error(title, e.message)

export const useGames = () => useQuery({ queryKey: gk.list, queryFn: () => api.get<GameSummary[]>('/games') })

export const useGame = (id: string | undefined) =>
  useQuery({ queryKey: gk.game(id ?? ''), queryFn: () => api.get<Game>(path(id!)), enabled: !!id })

/** Every mutation answers with the whole game; keep the cache and the list in step with it. */
function useGameMutation<V>(fn: (v: V) => Promise<Game>, title: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (game) => {
      qc.setQueryData(gk.game(game.id), game)
      void qc.invalidateQueries({ queryKey: gk.list })
    },
    onError: onError(title),
  })
}

export const useNewGame = () => useGameMutation((req: NewGameRequest) => api.post<Game>('/games', req), 'Could not start the game')

export const useGameAction = (id: string) =>
  useGameMutation((action: string) => api.post<Game>(`${path(id)}/actions`, { action }), 'Could not play that')

export const useCombat = (id: string) =>
  useGameMutation((req: CombatRequest) => api.post<Game>(`${path(id)}/combat`, req), 'Could not do that')

export type MediaKind = 'image' | 'audio' | 'music'

/** Art / narration / music being made, keyed `gameId:turnId|location:kind` (cleared by `game.media`). */
export const useGameMedia = create<{ busy: Record<string, true>; set: (key: string, on: boolean) => void }>((set) => ({
  busy: {},
  set: (key, on) =>
    set((s) => {
      const busy = { ...s.busy }
      if (on) busy[key] = true
      else delete busy[key]
      return { busy }
    }),
}))

export const mediaKey = (gameId: string, ref: string, kind: MediaKind) => `${gameId}:${ref}:${kind}`

/** Art or narration for a turn (`turnId`), or music for a location (`location`). */
export interface MediaRequest {
  kind: MediaKind
  turnId?: string
  location?: string
}

/** Start art, narration or music: a studio job (shown in the Jobs tray); the result arrives as `game.media`. */
export function useMakeMedia(gameId: string) {
  const setBusy = useGameMedia((s) => s.set)
  return useMutation({
    mutationFn: ({ kind, turnId }: MediaRequest) =>
      api.post<Job>(
        kind === 'music' ? `${path(gameId)}/music` : `${path(gameId)}/turns/${turnId}/${kind === 'image' ? 'illustrate' : 'narrate'}`,
      ),
    onMutate: ({ kind, turnId, location }: MediaRequest) => setBusy(mediaKey(gameId, turnId ?? location ?? '', kind), true),
    onSuccess: (job) => useLive.getState().upsertJob(job),
    onError: (e: Error, { kind, turnId, location }) => {
      setBusy(mediaKey(gameId, turnId ?? location ?? '', kind), false)
      toast.error(kind === 'image' ? 'Could not illustrate' : kind === 'audio' ? 'Could not narrate' : 'Could not compose music', e.message)
    },
  })
}

export const useUndoTurn = (id: string) => useGameMutation(() => api.post<Game>(`${path(id)}/undo`), 'Could not undo')

export const useStopTurn = (id: string) => useGameMutation(() => api.post<Game>(`${path(id)}/stop`), 'Could not stop')

export const usePatchGame = (id: string) =>
  useGameMutation((patch: GamePatch) => api.patch<Game>(path(id), patch), 'Could not save')

export function useDeleteGame() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(path(id)),
    onMutate: (id) => qc.setQueryData<GameSummary[]>(gk.list, (old = []) => old.filter((g) => g.id !== id)),
    onError: onError('Could not delete the game'),
  })
}

/** Apply a pushed game frame to the cached game (the narration grows, then the finished turn replaces it). */
export function dispatchGame(qc: QueryClient, ev: GameServerEvent) {
  const key = gk.game(ev.game_id)
  switch (ev.type) {
    case 'game.delta':
      return qc.setQueryData<Game>(key, (g) => (g?.pending ? { ...g, pending: { ...g.pending, narration: g.pending.narration + ev.text } } : g))
    case 'game.turn':
      qc.setQueryData<Game>(key, (g) =>
        g ? { ...g, state: ev.state, pending: undefined, turns: [...g.turns.filter((t) => t.id !== ev.turn.id), ev.turn] } : g,
      )
      return void qc.invalidateQueries({ queryKey: gk.list })
    case 'game.error':
      qc.setQueryData<Game>(key, (g) => (g ? { ...g, pending: undefined } : g))
      if (ev.message !== 'Stopped') toast.error('The game master stumbled', ev.message)
      return
    case 'game.media': {
      const ref = ev.turn_id ?? ev.location ?? ''
      const kind: MediaKind = ev.music || ev.location ? 'music' : ev.audio ? 'audio' : 'image'
      const { set } = useGameMedia.getState()
      if (ev.error) {
        for (const k of ['image', 'audio', 'music'] as const) set(mediaKey(ev.game_id, ref, k), false)
        return void toast.error('Media failed', ev.error)
      }
      set(mediaKey(ev.game_id, ref, kind), false)
      return qc.setQueryData<Game>(key, (g) => {
        if (!g) return g
        if (ev.music && ev.location) return { ...g, soundtrack: { ...g.soundtrack, [ev.location]: ev.music } }
        return {
          ...g,
          turns: g.turns.map((t) => (t.id === ev.turn_id ? { ...t, image: ev.image ?? t.image, audio: ev.audio ?? t.audio } : t)),
        }
      })
    }
  }
}
