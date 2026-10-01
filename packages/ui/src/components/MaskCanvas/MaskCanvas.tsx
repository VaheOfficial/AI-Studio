import { useImperativeHandle, useRef, useState, type PointerEvent, type Ref } from 'react'
import { cn } from '../../lib/cn'
import s from './MaskCanvas.module.css'

export interface MaskCanvasHandle {
  clear: () => void
  invert: () => void
}

export interface MaskCanvasProps {
  /** Image to paint over; the mask is produced at its natural resolution. */
  src: string
  /** Brush radius in image pixels. */
  brush: number
  tool: 'paint' | 'erase'
  /** PNG data URL (white = selected, black = keep), or null when nothing is painted. */
  onChange: (mask: string | null) => void
  ref?: Ref<MaskCanvasHandle>
  className?: string
}

/** Paint a selection mask over an image (for inpainting). The overlay tint comes from `--mask-color`. */
export function MaskCanvas({ src, brush, tool, onChange, ref, className }: MaskCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const last = useRef<{ x: number; y: number } | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [cursor, setCursor] = useState<{ x: number; y: number; r: number } | null>(null)

  const ctx = () => canvasRef.current?.getContext('2d') ?? null

  const emit = () => {
    const canvas = canvasRef.current
    const c = ctx()
    if (!canvas || !c) return
    const alpha = c.getImageData(0, 0, canvas.width, canvas.height).data
    let painted = false
    for (let i = 3; i < alpha.length; i += 4) {
      if (alpha[i] > 0) {
        painted = true
        break
      }
    }
    if (!painted) return onChange(null)
    // Export as an opaque black/white PNG: painted pixels white, the rest black
    const out = document.createElement('canvas')
    out.width = canvas.width
    out.height = canvas.height
    const o = out.getContext('2d')
    if (!o) return
    o.drawImage(canvas, 0, 0)
    o.globalCompositeOperation = 'source-in'
    o.fillStyle = 'white'
    o.fillRect(0, 0, out.width, out.height)
    o.globalCompositeOperation = 'destination-over'
    o.fillStyle = 'black'
    o.fillRect(0, 0, out.width, out.height)
    onChange(out.toDataURL('image/png'))
  }

  useImperativeHandle(ref, () => ({
    clear: () => {
      const canvas = canvasRef.current
      ctx()?.clearRect(0, 0, canvas?.width ?? 0, canvas?.height ?? 0)
      onChange(null)
    },
    invert: () => {
      const canvas = canvasRef.current
      const c = ctx()
      if (!canvas || !c) return
      c.globalCompositeOperation = 'xor'
      c.fillStyle = tint(canvas)
      c.fillRect(0, 0, canvas.width, canvas.height)
      c.globalCompositeOperation = 'source-over'
      emit()
    },
  }))

  const toImage = (e: PointerEvent) => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const scale = canvas.width / rect.width
    return { x: (e.clientX - rect.left) * scale, y: (e.clientY - rect.top) * scale, scale, rect }
  }

  const stroke = (from: { x: number; y: number }, to: { x: number; y: number }) => {
    const canvas = canvasRef.current
    const c = ctx()
    if (!canvas || !c) return
    c.globalCompositeOperation = tool === 'erase' ? 'destination-out' : 'source-over'
    c.strokeStyle = tint(canvas)
    c.lineWidth = brush * 2
    c.lineCap = 'round'
    c.lineJoin = 'round'
    c.beginPath()
    c.moveTo(from.x, from.y)
    c.lineTo(to.x, to.y)
    c.stroke()
  }

  const onDown = (e: PointerEvent<HTMLCanvasElement>) => {
    const p = toImage(e)
    if (!p) return
    e.currentTarget.setPointerCapture(e.pointerId)
    last.current = p
    stroke(p, p)
  }

  const onMove = (e: PointerEvent<HTMLCanvasElement>) => {
    const p = toImage(e)
    if (!p) return
    setCursor({ x: e.clientX - p.rect.left, y: e.clientY - p.rect.top, r: brush / p.scale })
    if (!last.current) return
    stroke(last.current, p)
    last.current = p
  }

  const onUp = () => {
    if (!last.current) return
    last.current = null
    emit()
  }

  return (
    <div className={cn(s.root, className)}>
      <img
        className={s.image}
        src={src}
        alt=""
        draggable={false}
        onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
      />
      {size && (
        <canvas
          ref={canvasRef}
          className={cn(s.canvas, tool === 'erase' && s.erasing)}
          width={size.w}
          height={size.h}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
          onPointerLeave={() => setCursor(null)}
        />
      )}
      {cursor && (
        <span
          className={s.cursor}
          style={{ left: cursor.x - cursor.r, top: cursor.y - cursor.r, width: cursor.r * 2, height: cursor.r * 2 }}
        />
      )}
    </div>
  )
}

/** Opaque stroke color from the theme; the canvas itself is shown translucent via CSS. */
function tint(el: HTMLElement) {
  return getComputedStyle(el).getPropertyValue('--mask-color').trim() || 'white'
}
