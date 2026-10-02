import { useEffect, useRef } from 'react'
import { cn } from '../../lib/cn'
import s from './Effects.module.css'

export interface CircuitFieldProps {
  className?: string
  /** Nodes per 100 000 px² of the field. */
  density?: number
  /** Nodes move away from the pointer and wire themselves to it. */
  interactive?: boolean
  /** `accent`: the brand's crimson and amber. `current`: the element's own text color, e.g. an area's hue. */
  tone?: 'accent' | 'current'
}

interface Node {
  x: number
  y: number
  vx: number
  vy: number
  r: number
  /** A ring (a solder pad) instead of a dot. */
  pad: boolean
  phase: number
}

interface Pulse {
  a: Node
  b: Node
  t: number
  speed: number
}

const LINK = 128 // px: nodes closer than this are wired together
const REACH = 170 // px: how far the pointer pushes and wires

/** Where a trace from `a` to `b` bends: it runs straight along the longer axis, then finishes at 45°, like a PCB track. */
function elbow(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const diag = Math.min(Math.abs(dx), Math.abs(dy))
  return Math.abs(dx) >= Math.abs(dy)
    ? { x: a.x + Math.sign(dx) * (Math.abs(dx) - diag), y: a.y }
    : { x: a.x, y: a.y + Math.sign(dy) * (Math.abs(dy) - diag) }
}

/**
 * A drifting field of nodes that wire themselves to their neighbours with circuit-board traces; now and then a
 * pulse of light travels a trace. Colors come from the accent tokens of wherever it is placed. Stops drawing while
 * it is off screen or the tab is hidden, and holds a single still frame under reduced motion.
 */
export function CircuitField({ className, density = 5, interactive = true, tone = 'accent' }: CircuitFieldProps) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current!
    const ctx = canvas.getContext('2d')!
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const tokens = getComputedStyle(canvas)
    const channels = (name: string, fallback: string) => (tokens.getPropertyValue(name).trim() || fallback).split(/\s+/).join(',')
    const own = tokens.color.match(/[\d.]+/g)?.slice(0, 3).join(',')
    const accent = (tone === 'current' && own) || channels('--accent-rgb', '225 29 72')
    const second = tone === 'current' ? '255,255,255' : channels('--accent-2-rgb', '229 184 78')
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
    let w = 0
    let h = 0
    let nodes: Node[] = []
    const pulses: Pulse[] = []
    const pointer = { x: -9999, y: -9999, live: false }

    const seed = () => {
      const count = Math.max(14, Math.min(120, Math.round(((w * h) / 100_000) * density)))
      nodes = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: 0,
        vy: 0,
        r: 0.8 + Math.random() * 1.5,
        pad: Math.random() < 0.28,
        phase: Math.random() * Math.PI * 2,
      }))
      pulses.length = 0
    }
    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      w = rect.width
      h = rect.height
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      seed()
      if (reduce) draw(0, 0)
    }

    const draw = (now: number, dt: number) => {
      ctx.clearRect(0, 0, w, h)
      // Drift along a slow flow field, rising a little, and step aside for the pointer
      for (const n of nodes) {
        const angle = Math.sin(n.x * 0.0041 + now * 0.00017) * 1.6 + Math.cos(n.y * 0.0053 - now * 0.00013) * 1.6
        n.vx += (Math.cos(angle) * 0.006 - n.vx * 0.02) * dt
        n.vy += (Math.sin(angle) * 0.006 - 0.002 - n.vy * 0.02) * dt
        if (pointer.live) {
          const dx = n.x - pointer.x
          const dy = n.y - pointer.y
          const d = Math.hypot(dx, dy)
          if (d < REACH && d > 0.01) {
            const push = ((1 - d / REACH) ** 2 * 0.09 * dt) / d
            n.vx += dx * push
            n.vy += dy * push
          }
        }
        n.x += n.vx * dt
        n.y += n.vy * dt
        if (n.x < -20) n.x = w + 20
        else if (n.x > w + 20) n.x = -20
        if (n.y < -20) n.y = h + 20
        else if (n.y > h + 20) n.y = -20
      }

      // Traces between neighbours
      ctx.lineWidth = 1
      const wired: [Node, Node][] = []
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i]
          const b = nodes[j]
          const d = Math.hypot(a.x - b.x, a.y - b.y)
          if (d > LINK) continue
          wired.push([a, b])
          const k = elbow(a, b)
          ctx.strokeStyle = `rgba(${accent},${(1 - d / LINK) ** 1.4 * 0.42})`
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(k.x, k.y)
          ctx.lineTo(b.x, b.y)
          ctx.stroke()
        }
      }
      if (pointer.live) {
        for (const n of nodes) {
          const d = Math.hypot(n.x - pointer.x, n.y - pointer.y)
          if (d > REACH) continue
          const k = elbow(pointer, n)
          ctx.strokeStyle = `rgba(${second},${(1 - d / REACH) * 0.5})`
          ctx.beginPath()
          ctx.moveTo(pointer.x, pointer.y)
          ctx.lineTo(k.x, k.y)
          ctx.lineTo(n.x, n.y)
          ctx.stroke()
        }
      }

      // Pulses: a spark that rides one trace from end to end
      if (!reduce && wired.length && pulses.length < 12 && Math.random() < 0.05 * dt) {
        const [a, b] = wired[Math.floor(Math.random() * wired.length)]
        pulses.push(Math.random() < 0.5 ? { a, b, t: 0, speed: 0.0016 + Math.random() * 0.0014 } : { a: b, b: a, t: 0, speed: 0.0016 + Math.random() * 0.0014 })
      }
      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i]
        p.t += p.speed * dt * 16
        if (p.t >= 1 || Math.hypot(p.a.x - p.b.x, p.a.y - p.b.y) > LINK * 1.15) {
          pulses.splice(i, 1)
          continue
        }
        const k = elbow(p.a, p.b)
        const first = Math.hypot(k.x - p.a.x, k.y - p.a.y)
        const rest = Math.hypot(p.b.x - k.x, p.b.y - k.y)
        const along = p.t * (first + rest)
        const [from, to, f] = along <= first ? [p.a, k, first ? along / first : 0] : [k, p.b, rest ? (along - first) / rest : 0]
        const x = from.x + (to.x - from.x) * f
        const y = from.y + (to.y - from.y) * f
        const fade = Math.sin(p.t * Math.PI)
        const halo = ctx.createRadialGradient(x, y, 0, x, y, 9)
        halo.addColorStop(0, `rgba(${second},${0.55 * fade})`)
        halo.addColorStop(1, `rgba(${second},0)`)
        ctx.fillStyle = halo
        ctx.fillRect(x - 9, y - 9, 18, 18)
        ctx.fillStyle = `rgba(255,255,255,${0.9 * fade})`
        ctx.beginPath()
        ctx.arc(x, y, 1.3, 0, Math.PI * 2)
        ctx.fill()
      }

      // Nodes on top: dots, and pads drawn as rings
      for (const n of nodes) {
        const glow = 0.5 + 0.35 * Math.sin(now * 0.0015 + n.phase)
        if (n.pad) {
          ctx.strokeStyle = `rgba(${accent},${glow})`
          ctx.lineWidth = 1.2
          ctx.beginPath()
          ctx.arc(n.x, n.y, n.r + 1.8, 0, Math.PI * 2)
          ctx.stroke()
          ctx.lineWidth = 1
        } else {
          ctx.fillStyle = `rgba(${accent},${glow})`
          ctx.beginPath()
          ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
          ctx.fill()
        }
      }
    }

    let raf = 0
    let last = 0
    let visible = true
    const frame = (now: number) => {
      const dt = Math.min(2.5, last ? (now - last) / 16.67 : 1)
      last = now
      draw(now, dt)
      raf = requestAnimationFrame(frame)
    }
    const start = () => {
      if (raf || reduce || !visible || document.hidden) return
      last = 0
      raf = requestAnimationFrame(frame)
    }
    const stop = () => {
      cancelAnimationFrame(raf)
      raf = 0
    }

    const sized = new ResizeObserver(resize)
    sized.observe(canvas)
    const seen = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      if (visible) start()
      else stop()
    })
    seen.observe(canvas)
    const onVisibility = () => (document.hidden ? stop() : start())
    const onMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect()
      pointer.x = e.clientX - rect.left
      pointer.y = e.clientY - rect.top
      pointer.live = pointer.x >= 0 && pointer.y >= 0 && pointer.x <= rect.width && pointer.y <= rect.height
    }
    document.addEventListener('visibilitychange', onVisibility)
    if (interactive) window.addEventListener('pointermove', onMove, { passive: true })
    resize()
    start()
    return () => {
      stop()
      sized.disconnect()
      seen.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pointermove', onMove)
    }
  }, [density, interactive, tone])

  return <canvas ref={ref} className={cn(s.circuit, className)} aria-hidden />
}
