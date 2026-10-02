import { useEffect, useRef } from 'react'
import { cn } from '../../lib/cn'
import s from './Effects.module.css'

/** Channels of the element's own text color ("r,g,b"), so a canvas draws in `currentColor`. */
function inkOf(el: Element): string {
  const found = getComputedStyle(el).color.match(/[\d.]+/g)
  return found ? found.slice(0, 3).join(',') : '225,29,72'
}

/**
 * Runs `draw` every frame while the canvas is on screen and the tab is visible, sized to the element at up to
 * 1.5x density. Under reduced motion it draws one still frame instead.
 */
function useCanvasLoop(
  ref: React.RefObject<HTMLCanvasElement | null>,
  draw: (ctx: CanvasRenderingContext2D, w: number, h: number, now: number, dt: number, ink: string) => void,
  resized?: (w: number, h: number) => void,
) {
  const drawRef = useRef(draw)
  const resizedRef = useRef(resized)
  useEffect(() => {
    drawRef.current = draw
    resizedRef.current = resized
  })

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
    let w = 0
    let h = 0
    let raf = 0
    let last = 0
    let visible = true
    let ink = inkOf(canvas)
    const frame = (now: number) => {
      const dt = Math.min(2.5, last ? (now - last) / 16.67 : 1)
      last = now
      if (w && h) drawRef.current(ctx, w, h, now, dt, ink)
      raf = reduce ? 0 : requestAnimationFrame(frame)
    }
    const start = () => {
      if (raf || !visible || document.hidden) return
      last = 0
      raf = requestAnimationFrame(frame)
    }
    const stop = () => {
      cancelAnimationFrame(raf)
      raf = 0
    }
    const sized = new ResizeObserver(() => {
      const rect = canvas.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      w = rect.width
      h = rect.height
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ink = inkOf(canvas)
      resizedRef.current?.(w, h)
      if (reduce) frame(performance.now())
    })
    sized.observe(canvas)
    const seen = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      if (visible) start()
      else stop()
    })
    seen.observe(canvas)
    const onVisibility = () => (document.hidden ? stop() : start())
    document.addEventListener('visibilitychange', onVisibility)
    start()
    return () => {
      stop()
      sized.disconnect()
      seen.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [ref])
}

export interface SignalWaveProps {
  className?: string
  /** 0..1: how strongly the signal moves. */
  level?: number
}

/**
 * A live signal: layered waves that swell and travel, tapering to nothing at both ends. Draws in the element's
 * text color (set `color` to a modality hue). For "the model is producing sound" moments.
 */
export function SignalWave({ className, level = 1 }: SignalWaveProps) {
  const ref = useRef<HTMLCanvasElement>(null)
  useCanvasLoop(ref, (ctx, w, h, now, _dt, ink) => {
    ctx.clearRect(0, 0, w, h)
    const mid = h / 2
    const layers = [
      { amp: 0.34, k: 0.021, speed: 0.0031, phase: 0, alpha: 0.95, width: 1.8 },
      { amp: 0.26, k: 0.034, speed: -0.0023, phase: 1.7, alpha: 0.5, width: 1.3 },
      { amp: 0.18, k: 0.055, speed: 0.0042, phase: 3.9, alpha: 0.28, width: 1 },
    ]
    for (const l of layers) {
      ctx.beginPath()
      for (let x = 0; x <= w; x += 3) {
        const t = x / w
        // Quiet at both ends, and a slower swell riding along the line
        const envelope = Math.sin(Math.PI * t) ** 1.6 * (0.55 + 0.45 * Math.sin(x * 0.006 - now * 0.0012 + l.phase))
        const y = mid + Math.sin(x * l.k + now * l.speed + l.phase) * l.amp * h * envelope * level
        if (x === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.strokeStyle = `rgba(${ink},${l.alpha})`
      ctx.lineWidth = l.width
      ctx.stroke()
    }
  })
  return <canvas ref={ref} className={cn(s.fill, className)} aria-hidden />
}

export interface MaterializeProps {
  className?: string
  /** 0..1 of the work done; negative or null when unknown. More of the field stays lit as it grows. */
  progress?: number | null
  /** Cell size in px. */
  cell?: number
}

/**
 * A picture coming into being: a grid of cells that flicker at random, more and more of them staying lit as
 * `progress` grows, with a scan line passing down over them. Draws in the element's text color.
 */
export function Materialize({ className, progress = null, cell = 16 }: MaterializeProps) {
  const ref = useRef<HTMLCanvasElement>(null)
  const grid = useRef({ cols: 0, rows: 0, heat: new Float32Array(0), order: new Float32Array(0) })
  const done = progress == null || progress < 0 ? 0.12 : Math.min(1, Math.max(0, progress))
  const doneRef = useRef(done)
  useEffect(() => {
    doneRef.current = done
  }, [done])

  useCanvasLoop(
    ref,
    (ctx, w, h, now, dt, ink) => {
      const g = grid.current
      if (!g.cols) return
      ctx.clearRect(0, 0, w, h)
      const size = cell - 3
      const scan = ((now * 0.00015) % 1.25) * h // a line travelling down slowly, with a pause off screen
      // Now and then a cell lights up, somewhere. Few of them: this sits behind a picture for minutes, and a
      // field that sparkles all over pulls the eye the whole time. (A fraction of a cell per frame, so on average.)
      const due = g.heat.length * 0.0018 * dt
      const sparks = Math.floor(due) + (Math.random() < due % 1 ? 1 : 0)
      for (let i = 0; i < sparks; i++) g.heat[Math.floor(Math.random() * g.heat.length)] = 1
      for (let row = 0; row < g.rows; row++) {
        const y = row * cell + 1.5
        const near = Math.max(0, 1 - Math.abs(y - scan) / 46)
        for (let col = 0; col < g.cols; col++) {
          const i = row * g.cols + col
          g.heat[i] *= 1 - 0.03 * dt
          // Cells whose turn has come stay faintly lit: the field fills in as the work progresses
          const settled = g.order[i] < doneRef.current ? 0.16 : 0.03
          const a = Math.min(1, settled + g.heat[i] * 0.4 + near * 0.22)
          if (a < 0.035) continue
          ctx.fillStyle = `rgba(${ink},${a})`
          ctx.fillRect(col * cell + 1.5, y, size, size)
        }
      }
      const beam = ctx.createLinearGradient(0, scan - 40, 0, scan + 2)
      beam.addColorStop(0, `rgba(${ink},0)`)
      beam.addColorStop(1, `rgba(${ink},0.2)`)
      ctx.fillStyle = beam
      ctx.fillRect(0, scan - 40, w, 42)
      ctx.fillStyle = `rgba(255,255,255,0.26)`
      ctx.fillRect(0, scan + 1, w, 1)
    },
    (w, h) => {
      const cols = Math.ceil(w / cell)
      const rows = Math.ceil(h / cell)
      const order = new Float32Array(cols * rows)
      for (let i = 0; i < order.length; i++) order[i] = Math.random()
      grid.current = { cols, rows, heat: new Float32Array(cols * rows), order }
    },
  )
  return <canvas ref={ref} className={cn(s.fill, className)} aria-hidden />
}
