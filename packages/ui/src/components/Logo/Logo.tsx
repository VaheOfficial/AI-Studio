import { useEffect, useMemo, useRef, type CSSProperties } from 'react'
import { motion, useReducedMotion, type Transition } from 'motion/react'
import { cn } from '../../lib/cn'
import { LOGO_HEIGHT, LOGO_MEMBRANES, LOGO_PARTS, LOGO_WIDTH, type LogoPart } from './logoParts'
import { createStrike } from './strike.js'
import s from './Logo.module.css'

/**
 * - `still`: the mark, nothing moves.
 * - `assemble`: builds itself once (the head docks, the plates stack from the top, the wings unfold), then rests.
 * - `alive`: rests, with a quick double wing beat every few seconds.
 * - `working`: keeps moving, calmly: the wings fan, a pulse runs down the body, the mark floats. For loading and
 *   generating, where it may be on screen for minutes. Every part moves on the same clock (`WORK_S` or a whole
 *   fraction of it), so the motion reads as one loop.
 */
export type LogoMode = 'still' | 'assemble' | 'alive' | 'working'

export interface LogoProps {
  /** Width in px; the height follows the artwork's proportions. */
  size?: number
  mode?: LogoMode
  /** A soft glow in the mark's own color behind it. */
  glow?: boolean
  /**
   * Fills the wings, which are otherwise outlines. On by default below 64px, where the outlines alone are too
   * thin to carry the mark; the smaller the mark, the more solid the fill.
   */
  filled?: boolean
  className?: string
  /** Accessible name; without one the mark is decorative. */
  label?: string
}

const WHOLE = LOGO_PARTS.map((p) => p.d).join('')
const by = (region: LogoPart['region']) => LOGO_PARTS.filter((p) => p.region === region)
const HEAD = by('head')
const ANTENNAE = by('antenna')
const BODY = by('body')
const WINGS = { l: by('wing-l'), r: by('wing-r') }
const MID = LOGO_WIDTH / 2

/** One cycle of the `working` mode, in seconds. */
const WORK_S = 2.4

const spring = (delay: number, stiffness = 260, damping = 18): Transition => ({ type: 'spring', stiffness, damping, delay })

/** The logo. Its pieces are separate shapes, so it can build itself and move (see `LogoMode`). */
export function Logo({ size = 28, mode = 'still', glow = false, filled = size < 64, className, label }: LogoProps) {
  const reduce = useReducedMotion()
  const active = reduce ? 'still' : mode
  const height = (size * LOGO_HEIGHT) / LOGO_WIDTH
  const a11y = label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true }
  // A wave needs each plate's place in the top-to-bottom order
  const plates = useMemo(() => BODY.map((p, i) => ({ ...p, t: i / (BODY.length - 1) })), [])

  const membrane = (side: 'l' | 'r') =>
    filled && <path d={LOGO_MEMBRANES[side]} fillOpacity={Math.min(0.7, Math.max(0.35, 0.85 - size / 100))} />

  if (active === 'still') {
    return (
      <svg {...a11y} className={cn(s.logo, glow && s.glow, className)} width={size} height={height} viewBox={`0 0 ${LOGO_WIDTH} ${LOGO_HEIGHT}`}>
        {membrane('l')}
        {membrane('r')}
        <path fillRule="evenodd" d={WHOLE} />
      </svg>
    )
  }

  const assemble = active === 'assemble'
  const working = active === 'working'
  // After building itself the mark rests; `alive` and `working` loop from the start
  const beat = working ? { duration: WORK_S / 2, repeat: Infinity, ease: 'easeInOut' as const } : { duration: 0.16, repeat: Infinity, repeatDelay: 5.5, ease: 'easeInOut' as const }

  const wing = (side: 'l' | 'r') => {
    const dir = side === 'l' ? -1 : 1
    return (
      <motion.g
        // Hinged where the wings meet the body
        style={{ originX: side === 'l' ? 1 : 0, originY: 0.5 }}
        initial={assemble ? { rotate: dir * 68, scale: 0.55, opacity: 0 } : false}
        animate={
          assemble
            ? { rotate: 0, scale: 1, opacity: 1 }
            : working
              ? { rotate: [0, dir * -5, 0], scaleY: [1, 0.92, 1] }
              : { rotate: [0, dir * -9, 0, dir * -6, 0], scaleY: [1, 0.84, 1, 0.9, 1] }
        }
        transition={assemble ? spring(0.55, 150, 11) : working ? beat : { ...beat, duration: 0.42 }}
      >
        {membrane(side)}
        {WINGS[side].map((p) => (
          <path key={p.d.length + p.cx} fillRule="evenodd" d={p.d} />
        ))}
      </motion.g>
    )
  }

  return (
    <motion.svg
      {...a11y}
      className={cn(s.logo, glow && s.glow, className)}
      width={size}
      height={height}
      viewBox={`0 0 ${LOGO_WIDTH} ${LOGO_HEIGHT}`}
      animate={working ? { y: [0, -size * 0.02, 0] } : undefined}
      transition={working ? { duration: WORK_S, repeat: Infinity, ease: 'easeInOut' } : undefined}
    >
      {wing('l')}
      {wing('r')}
      {plates.map((p, i) => (
        <motion.path
          key={i}
          fillRule="evenodd"
          d={p.d}
          initial={assemble ? { opacity: 0, scale: 0.3, y: -14 } : false}
          // The pulse starts from fully lit, so the body never drops dark the moment the mark starts working
          animate={assemble ? { opacity: 1, scale: 1, y: 0 } : working ? { opacity: [1, 0.5, 1] } : { opacity: 1 }}
          transition={
            assemble
              ? spring(0.2 + p.t * 0.38, 320, 20)
              : working
                ? { duration: WORK_S, repeat: Infinity, ease: 'easeInOut', delay: p.t * 0.9 }
                : { duration: 0.3 }
          }
        />
      ))}
      {/* The head arrives on its own and docks onto the body, its antennae flicking out after it */}
      <motion.g
        initial={assemble ? { y: -46, opacity: 0 } : false}
        animate={assemble ? { y: 0, opacity: 1 } : working ? { y: [0, -1.5, 0] } : { y: 0 }}
        transition={assemble ? spring(0, 210, 13) : working ? { duration: WORK_S, repeat: Infinity, ease: 'easeInOut' } : { duration: 0.3 }}
      >
        {HEAD.map((p) => (
          <path key={p.cx} fillRule="evenodd" d={p.d} />
        ))}
        {ANTENNAE.map((p) => {
          const dir = p.cx < MID ? -1 : 1
          return (
            <motion.path
              key={p.cx}
              fillRule="evenodd"
              d={p.d}
              // Rooted at the head: the inner bottom corner of each antenna
              style={{ originX: dir < 0 ? 1 : 0, originY: 1 }}
              initial={assemble ? { rotate: dir * -38, opacity: 0 } : false}
              animate={assemble ? { rotate: 0, opacity: 1 } : working ? { rotate: [0, dir * 3, 0] } : { rotate: [0, dir * 4, 0] }}
              transition={
                assemble
                  ? spring(0.18, 300, 9)
                  : { duration: working ? WORK_S : 0.5, repeat: Infinity, repeatDelay: working ? 0 : 5.4, ease: 'easeInOut' }
              }
            />
          )
        })}
      </motion.g>
    </motion.svg>
  )
}

export interface LoaderProps {
  /** Width of the mark in px. */
  size?: number
  /** What is happening, shown under the mark. */
  label?: string
  className?: string
}

const STRIKE_LOGO = { width: LOGO_WIDTH, height: LOGO_HEIGHT, parts: LOGO_PARTS }

/**
 * Page-level loading: the logo builds itself out of its own pieces and then hunts, is cut, darts and
 * shatters, for as long as the wait lasts (see strike.js). It takes the whole of the space it is given. For small
 * inline waits use `Spinner`.
 */
export function Loader({ size = 120, label, className }: LoaderProps) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (!canvas.current) return
    const strike = createStrike(canvas.current, { logo: STRIKE_LOGO, size: () => size })
    return () => strike.destroy()
  }, [size])
  return (
    <div role="status" aria-label={label ?? 'Loading'} className={cn(s.loader, className)} style={{ ['--size' as string]: `${size}px` } as CSSProperties}>
      <canvas ref={canvas} className={s.strike} aria-hidden />
      {label && <span className={s.loaderLabel}>{label}</span>}
    </div>
  )
}
