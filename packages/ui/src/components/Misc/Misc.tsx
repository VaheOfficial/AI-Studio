import type { CSSProperties, HTMLAttributes, ReactNode } from 'react'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'
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
}

export function EmptyState({ icon, title, description, action, className, tint }: EmptyStateProps) {
  return (
    <motion.div
      className={cn(s.empty, className)}
      style={tint ? { ['--tint' as string]: tint } : undefined}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
    >
      {icon && <div className={s.emptyIcon}>{icon}</div>}
      <h3 className={s.emptyTitle}>{title}</h3>
      {description && <p className={s.emptyDesc}>{description}</p>}
      {action && <div className={s.emptyAction}>{action}</div>}
    </motion.div>
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
