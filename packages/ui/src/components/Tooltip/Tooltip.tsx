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

// Whether the person is moving around with the keyboard (Tab, arrows) rather than the pointer
let byKeyboard = false
if (typeof window !== 'undefined') {
  window.addEventListener('keydown', (e) => (byKeyboard = e.key === 'Tab' || e.key.startsWith('Arrow')), true)
  window.addEventListener('pointerdown', () => (byKeyboard = false), true)
}

/** Requires <TooltipProvider> once near the app root. */
export function Tooltip({ content, children, side = 'top', shortcut, delay }: TooltipProps) {
  return (
    <T.Root delayDuration={delay}>
      <T.Trigger
        asChild
        // Shown on hover, and on focus only when focus got there by keyboard: a panel that opens on a click and
        // focuses its first button would otherwise open that button's tooltip and leave it up
        onFocus={(e) => {
          if (!byKeyboard) e.preventDefault()
        }}
      >
        {children}
      </T.Trigger>
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
