import { useRef, type KeyboardEvent, type PointerEvent, type ReactNode, type WheelEvent } from 'react'
import { cn } from '../../lib/cn'
import s from './BrowserView.module.css'

/** Input in page (CSS pixel) coordinates. `modifiers` is a CDP mask: Alt 1, Ctrl 2, Meta 4, Shift 8. */
export type BrowserViewInput =
  | {
      type: 'mouse'
      action: 'down' | 'up' | 'move'
      x: number
      y: number
      button?: 'left' | 'right' | 'middle'
      click_count?: number
      modifiers?: number
    }
  | { type: 'wheel'; x: number; y: number; dx: number; dy: number }
  | { type: 'key'; action: 'down' | 'up'; key: string; code: string; text?: string; modifiers?: number }
  | { type: 'text'; text: string }

export interface BrowserFrame {
  /** Image URL (e.g. `data:image/jpeg;base64,…`). */
  src: string
  /** Page size in CSS pixels the frame represents. */
  width: number
  height: number
}

export interface BrowserViewProps {
  frame?: BrowserFrame
  /** When true, pointer/wheel/keyboard input is forwarded through `onInput`. */
  interactive?: boolean
  onInput?: (input: BrowserViewInput) => void
  /** Shown when there is no frame yet. */
  placeholder?: ReactNode
  className?: string
}

const BUTTONS = ['left', 'middle', 'right'] as const
const MOVE_INTERVAL_MS = 50

function modifiers(e: { altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) {
  return (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0)
}

/** Live view of a remote page (screencast frames) that can be taken over with mouse and keyboard. */
export function BrowserView({ frame, interactive, onInput, placeholder, className }: BrowserViewProps) {
  const img = useRef<HTMLImageElement>(null)
  const lastMove = useRef(0)

  /** Map a client point to page coordinates, accounting for object-fit letterboxing. */
  const toPage = (clientX: number, clientY: number) => {
    const el = img.current
    if (!el || !frame) return null
    const r = el.getBoundingClientRect()
    const scale = Math.min(r.width / frame.width, r.height / frame.height)
    const left = r.left + (r.width - frame.width * scale) / 2
    const top = r.top + (r.height - frame.height * scale) / 2
    const x = (clientX - left) / scale
    const y = (clientY - top) / scale
    if (x < 0 || y < 0 || x > frame.width || y > frame.height) return null
    return { x: Math.round(x), y: Math.round(y) }
  }

  const send = (input: BrowserViewInput) => interactive && onInput?.(input)

  const onPointer = (action: 'down' | 'up' | 'move') => (e: PointerEvent<HTMLDivElement>) => {
    if (!interactive) return
    if (action === 'move') {
      const now = performance.now()
      if (now - lastMove.current < MOVE_INTERVAL_MS && e.buttons === 0) return
      lastMove.current = now
    }
    const p = toPage(e.clientX, e.clientY)
    if (!p) return
    if (action === 'down') e.currentTarget.focus()
    send({ type: 'mouse', action, ...p, button: BUTTONS[e.button] ?? 'left', click_count: Math.max(1, e.detail), modifiers: modifiers(e) })
  }

  const onWheel = (e: WheelEvent<HTMLDivElement>) => {
    const p = toPage(e.clientX, e.clientY)
    if (p) send({ type: 'wheel', ...p, dx: e.deltaX, dy: e.deltaY })
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!interactive) return
    e.preventDefault()
    const plain = e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey
    if (plain) send({ type: 'text', text: e.key })
    else send({ type: 'key', action: 'down', key: e.key, code: e.code, modifiers: modifiers(e) })
  }

  return (
    <div
      className={cn(s.view, interactive && s.interactive, className)}
      tabIndex={interactive ? 0 : -1}
      onPointerDown={onPointer('down')}
      onPointerUp={onPointer('up')}
      onPointerMove={onPointer('move')}
      onWheel={interactive ? onWheel : undefined}
      onKeyDown={onKeyDown}
      onPaste={(e) => {
        const text = e.clipboardData.getData('text')
        if (text) send({ type: 'text', text })
      }}
      onContextMenu={(e) => interactive && e.preventDefault()}
    >
      {frame ? (
        <img ref={img} className={s.frame} src={frame.src} alt="Live browser view" draggable={false} />
      ) : (
        <div className={s.placeholder}>{placeholder}</div>
      )}
    </div>
  )
}
