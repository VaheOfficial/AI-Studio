import { useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'

/**
 * The desktop shell's bridge (`apps/desktop/src/preload.cjs`). Absent in a browser, where the studio is served by
 * `pnpm server` and updates come from the working tree.
 */
export interface UpdateStatus {
  /** False for a run from source: nothing to update from. */
  enabled: boolean
  current: string
  latest: string | null
  /** A newer version the app can install itself. */
  available: boolean
  /** How: 'content' swaps the server and web app in place; 'app' replaces the app itself and restarts it. */
  kind: 'content' | 'app' | null
  /** Download size in bytes. */
  size: number | null
  /** A newer version exists but this copy can't replace itself (it runs from a folder it may not write to). */
  needsInstaller: boolean
  /** The release page of the newest version. */
  notes: string | null
  state: 'idle' | 'checking' | 'downloading' | 'ready'
  error: string | null
}

interface DesktopBridge {
  updates: {
    check(): Promise<UpdateStatus | null>
    install(): Promise<UpdateStatus | null>
    onChanged(handler: (status: UpdateStatus) => void): () => void
    onProgress(handler: (fraction: number) => void): () => void
  }
}

export const desktop: DesktopBridge | undefined = (window as { desktop?: DesktopBridge }).desktop?.updates
  ? (window as { desktop?: DesktopBridge }).desktop
  : undefined

export const updatesKey = ['desktop', 'updates'] as const

/** The desktop app's update state: asked on start and every few hours. Disabled in a browser. */
/**
 * The desktop app opened the page under its splash screen (`#launch`), which ends by setting its mark down on the
 * home page's. The home page then shows its mark as it is, without building it again.
 */
export const launchedUnderSplash = window.location.hash === '#launch'
if (launchedUnderSplash) window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search)

// Whether the splash screen's mark has landed (true from the start when there is no splash screen). Kept here, not
// in a component: it happens once per launch, and pages mounted later must not wait for it again.
let landed = !launchedUnderSplash
const waiting = new Set<() => void>()
if (!landed) {
  const land = () => {
    landed = true
    for (const notify of waiting) notify()
  }
  ;(window as { desktop?: { onLanded?: (handler: () => void) => void } }).desktop?.onLanded?.(land)
  // Never left waiting, whatever becomes of the splash screen
  setTimeout(land, 14000)
}

/**
 * False while the page is still behind the desktop app's splash screen: until that screen's mark lands on the home
 * page's and the page is torn into view. The home page holds its own mark and its entrance until then.
 */
export function useLanded(): boolean {
  return useSyncExternalStore(
    (notify) => {
      waiting.add(notify)
      return () => waiting.delete(notify)
    },
    () => landed,
  )
}

export function useUpdates() {
  return useQuery({
    queryKey: updatesKey,
    queryFn: async () => (await desktop?.updates.check()) ?? null,
    enabled: !!desktop,
    staleTime: 30 * 60_000,
    refetchInterval: 6 * 3600_000,
  })
}
