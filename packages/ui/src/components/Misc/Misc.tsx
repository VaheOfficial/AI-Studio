import type { CSSProperties, HTMLAttributes, ReactNode } from 'react'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'
import { CircuitField } from '../Effects/CircuitField'
import s from './Misc.module.css'

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <kbd className={cn(s.kbd, className)}>{children}</kbd>
}

export interface SkeletonProps {
  width?: CSSProperties['width']
  height?: CSSProperties['height']
  radius?: CSSProperties['borderRadius']
  className?: string
}

export function Skeleton({ width = '100%', height = 14, radius, className }: SkeletonProps) {
  return <span aria-hidden className={cn(s.skeleton, className)} style={{ width, height, borderRadius: radius }} />
}

export interface EmptyStateProps {
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  className?: string
  /** Color for the icon halo. */
  tint?: string
  /** `lg` is the hero of an empty page: bigger, with room to breathe. */
  size?: 'md' | 'lg'
  /** A circuit field in the tint behind it (give the parent a size: it fills it). */
  backdrop?: boolean
  /** Shown under the action, e.g. `Suggestions` to start from. */
  children?: ReactNode
}

const emptyLine = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const } },
}

/**
 * "Nothing here yet". The icon springs in on a tile that two rings orbit (solder pads riding them), and the lines
 * follow one after another.
 */
export function EmptyState({ icon, title, description, action, className, tint, size = 'md', backdrop, children }: EmptyStateProps) {
  return (
    <motion.div
      className={cn(s.empty, size === 'lg' && s.emptyLg, className)}
      style={tint ? { ['--tint' as string]: tint } : undefined}
      initial="hidden"
      animate="show"
      variants={{ show: { transition: { staggerChildren: 0.08 } } }}
    >
      {backdrop && <CircuitField className={s.emptyBackdrop} density={3.4} tone={tint ? 'current' : 'accent'} />}
      {icon && (
        <motion.div
          className={s.emptyIcon}
          variants={{
            hidden: { opacity: 0, scale: 0.4, rotate: -18 },
            show: { opacity: 1, scale: 1, rotate: 0, transition: { type: 'spring', stiffness: 260, damping: 16 } },
          }}
        >
          <span className={s.emptyOrbit} aria-hidden />
          <span className={cn(s.emptyOrbit, s.emptyOrbitOuter)} aria-hidden />
          {icon}
        </motion.div>
      )}
      <motion.h3 className={s.emptyTitle} variants={emptyLine}>
        {title}
      </motion.h3>
      {description && (
        <motion.p className={s.emptyDesc} variants={emptyLine}>
          {description}
        </motion.p>
      )}
      {action && (
        <motion.div className={s.emptyAction} variants={emptyLine}>
          {action}
        </motion.div>
      )}
      {children && (
        <motion.div className={s.emptyExtra} variants={emptyLine}>
          {children}
        </motion.div>
      )}
    </motion.div>
  )
}

export interface SuggestionsProps {
  items: string[]
  onPick: (item: string) => void
  icon?: ReactNode
  className?: string
}

/** Starting points to click: each fills in whatever `onPick` says (a prompt box, usually). */
export function Suggestions({ items, onPick, icon, className }: SuggestionsProps) {
  return (
    <div className={cn(s.suggestions, 'ui-stagger', className)}>
      {items.map((item) => (
        <button key={item} type="button" className={s.suggestion} onClick={() => onPick(item)}>
          {icon && <span className={s.suggestionIcon}>{icon}</span>}
          <span>{item}</span>
        </button>
      ))}
    </div>
  )
}

export function Divider({ label, className }: { label?: ReactNode; className?: string }) {
  return (
    <div role="separator" className={cn(s.divider, className)}>
      {label && <span>{label}</span>}
    </div>
  )
}

export interface StackProps extends HTMLAttributes<HTMLDivElement> {
  direction?: 'row' | 'column'
  gap?: 1 | 2 | 3 | 4 | 5 | 6 | 8 | 10
  align?: CSSProperties['alignItems']
  justify?: CSSProperties['justifyContent']
  wrap?: boolean
}

/** Flex layout primitive; spacing follows the 4px token grid. */
export function Stack({ direction = 'column', gap = 3, align, justify, wrap, className, style, ...rest }: StackProps) {
  return (
    <div
      className={className}
      style={{
        display: 'flex',
        flexDirection: direction,
        gap: `var(--space-${gap})`,
        alignItems: align,
        justifyContent: justify,
        flexWrap: wrap ? 'wrap' : undefined,
        minWidth: 0,
        ...style,
      }}
      {...rest}
    />
  )
}
