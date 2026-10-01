import type { ReactNode } from 'react'
import { Tooltip as T } from 'radix-ui'
import s from './Tooltip.module.css'

export interface TooltipProps {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
  shortcut?: string
  delay?: number
}

/** Requires <TooltipProvider> once near the app root. */
export function Tooltip({ content, children, side = 'top', shortcut, delay }: TooltipProps) {
  return (
    <T.Root delayDuration={delay}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={6} className={s.content}>
          {content}
          {shortcut && <kbd className={s.shortcut}>{shortcut}</kbd>}
        </T.Content>
      </T.Portal>
    </T.Root>
  )
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <T.Provider delayDuration={350} skipDelayDuration={150}>
      {children}
    </T.Provider>
  )
}
