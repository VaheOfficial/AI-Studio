import { useEffect, useRef } from 'react'
import { animate, motion, useMotionValue, useTransform } from 'motion/react'
import { cn } from '../../lib/cn'
import s from './Effects.module.css'

export interface AuroraProps {
  /** Concrete colors (hex/rgb) for the drifting blobs. */
  colors?: string[]
  className?: string
  /** 0..1 */
  intensity?: number
}

/**
 * Slow-drifting, heavily blurred color fields. Rendered to a tiny canvas and
 * upscaled with CSS blur — cheap enough to leave running on the home screen.
 */
export function Aurora({ colors = ['#7c3aed', '#2563eb', '#06b6d4', '#db2777'], className, intensity = 1 }: AuroraProps) {
  const ref = useRef<HTMLCanvasElement>(null)
  const key = colors.join(',')

  useEffect(() => {
    const canvas = ref.current!
    const ctx = canvas.getContext('2d')!
    const W = (canvas.width = 160)
    const H = (canvas.height = 100)
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const blobs = key.split(',').map((c, i) => ({
      c,
      r: 38 + i * 6,
      sx: 0.00011 + i * 0.00003,
      sy: 0.00009 + i * 0.00004,
      ox: i * 1.7,
      oy: i * 2.3,
    }))
    let raf = 0
    const frame = (t: number) => {
      ctx.clearRect(0, 0, W, H)
      ctx.globalCompositeOperation = 'lighter'
      for (const b of blobs) {
        const x = W / 2 + Math.sin(t * b.sx + b.ox) * W * 0.36
        const y = H / 2 + Math.cos(t * b.sy + b.oy) * H * 0.3
        const g = ctx.createRadialGradient(x, y, 0, x, y, b.r)
        g.addColorStop(0, b.c)
        g.addColorStop(1, 'transparent')
        ctx.globalAlpha = 0.55 * intensity
        ctx.fillStyle = g
        ctx.fillRect(0, 0, W, H)
      }
      if (!reduce) raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [key, intensity])

  return (
    <div className={cn(s.aurora, className)} aria-hidden>
      <canvas ref={ref} />
      <div className={s.grain} />
    </div>
  )
}

export interface AnimatedNumberProps {
  value: number
  format?: (n: number) => string
  className?: string
}

/** Springs between values instead of jumping — for stats and meters. */
export function AnimatedNumber({ value, format = (n) => Math.round(n).toString(), className }: AnimatedNumberProps) {
  const mv = useMotionValue(value)
  const text = useTransform(mv, format)
  useEffect(() => {
    const controls = animate(mv, value, { type: 'spring', stiffness: 90, damping: 20 })
    return () => controls.stop()
  }, [mv, value])
  return <motion.span className={cn(s.number, className)}>{text}</motion.span>
}

/** Dot grid that fades out toward the edges — a subtle canvas backdrop. */
export function GridBackdrop({ className }: { className?: string }) {
  return <div className={cn(s.grid, className)} aria-hidden />
}
