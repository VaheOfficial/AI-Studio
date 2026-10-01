import { useEffect, useImperativeHandle, useRef, type Ref } from 'react'
import { Terminal as XTerm, type ITheme } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { cn } from '../../lib/cn'
import s from './Terminal.module.css'

export interface TerminalHandle {
  write: (data: string) => void
  clear: () => void
  focus: () => void
}

export interface TerminalProps {
  ref?: Ref<TerminalHandle>
  /** Keystrokes typed by the user (already encoded for the PTY). */
  onData?: (data: string) => void
  /** Called with the fitted size whenever the element resizes. */
  onResize?: (cols: number, rows: number) => void
  className?: string
}

/** Canvas normalizes any CSS color (e.g. `rgb(1 2 3 / 0.5)`) to a form xterm parses (`#rrggbb` / `rgba()`). */
function normalizeColor(color: string): string {
  const ctx = document.createElement('canvas').getContext('2d')
  if (!ctx) return color
  ctx.fillStyle = color
  return ctx.fillStyle
}

/** Colors come from the design tokens (read once per theme change). */
function themeFromTokens(el: HTMLElement): ITheme {
  const css = getComputedStyle(el)
  const v = (name: string) => normalizeColor(css.getPropertyValue(name).trim())
  return {
    background: v('--bg-0'),
    foreground: v('--text-1'),
    cursor: v('--accent-text'),
    cursorAccent: v('--bg-0'),
    selectionBackground: v('--accent-soft'),
  }
}

/** xterm.js terminal that fills its container. Feed output through the imperative `write`. */
export function Terminal({ ref, onData, onResize, className }: TerminalProps) {
  const host = useRef<HTMLDivElement>(null)
  const term = useRef<XTerm | null>(null)
  const handlers = useRef({ onData, onResize })
  useEffect(() => {
    handlers.current = { onData, onResize }
  })

  useImperativeHandle(
    ref,
    () => ({
      write: (data) => term.current?.write(data),
      clear: () => term.current?.reset(),
      focus: () => term.current?.focus(),
    }),
    [],
  )

  useEffect(() => {
    const el = host.current
    if (!el) return
    const css = getComputedStyle(el)
    const xterm = new XTerm({
      fontFamily: css.getPropertyValue('--font-mono').trim() || 'monospace',
      fontSize: 12.5,
      lineHeight: 1.25,
      cursorBlink: true,
      scrollback: 5000,
      allowProposedApi: false,
      theme: themeFromTokens(el),
    })
    const fit = new FitAddon()
    xterm.loadAddon(fit)
    xterm.open(el)
    term.current = xterm
    const dataSub = xterm.onData((d) => handlers.current.onData?.(d))
    const resizeSub = xterm.onResize(({ cols, rows }) => handlers.current.onResize?.(cols, rows))

    const refit = () => {
      if (el.offsetWidth > 0 && el.offsetHeight > 0) fit.fit()
    }
    const ro = new ResizeObserver(refit)
    ro.observe(el)
    refit()
    handlers.current.onResize?.(xterm.cols, xterm.rows)

    // Follow the app theme (data-theme on <html>)
    const mo = new MutationObserver(() => {
      xterm.options.theme = themeFromTokens(el)
    })
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

    return () => {
      mo.disconnect()
      ro.disconnect()
      dataSub.dispose()
      resizeSub.dispose()
      xterm.dispose()
      term.current = null
    }
  }, [])

  return <div ref={host} className={cn(s.terminal, className)} />
}
