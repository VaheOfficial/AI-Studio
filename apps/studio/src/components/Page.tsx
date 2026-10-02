import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { ScrambleText, cn } from '@studio/ui'
import s from './Page.module.css'

export interface PageHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  icon?: ReactNode
  /** Modality hue for the icon tile. */
  hue?: string
  actions?: ReactNode
  className?: string
}

export function PageHeader({ title, subtitle, icon, hue = 'var(--accent)', actions, className }: PageHeaderProps) {
  return (
    <header className={cn(s.header, className)} style={{ ['--hue' as string]: hue }}>
      {icon && (
        <motion.div
          className={s.icon}
          initial={{ opacity: 0, scale: 0.5, rotate: -20 }}
          animate={{ opacity: 1, scale: 1, rotate: 0 }}
          transition={{ type: 'spring', stiffness: 280, damping: 16 }}
        >
          {icon}
        </motion.div>
      )}
      <div className={s.titles}>
        <h1 className={s.title}>{typeof title === 'string' ? <ScrambleText text={title} duration={420} /> : title}</h1>
        {subtitle && <p className={s.subtitle}>{subtitle}</p>}
      </div>
      {actions && <div className={s.actions}>{actions}</div>}
    </header>
  )
}

/** Scrollable page body with consistent gutters. */
export function PageBody({ children, className, wide }: { children: ReactNode; className?: string; wide?: boolean }) {
  return (
    <div className={s.scroll}>
      <div className={cn(s.body, 'ui-stagger', wide && s.wide, className)}>{children}</div>
    </div>
  )
}

/** The heading of a studio's controls: the section's icon, its name and one line on what it makes. */
export function StudioHead({ icon, title, subtitle }: { icon: ReactNode; title: string; subtitle?: string }) {
  return (
    <div className={s.studioHead}>
      <motion.span
        className={s.studioIcon}
        initial={{ opacity: 0, scale: 0.5, rotate: -20 }}
        animate={{ opacity: 1, scale: 1, rotate: 0 }}
        transition={{ type: 'spring', stiffness: 280, damping: 16 }}
      >
        {icon}
      </motion.span>
      <div className={s.studioTitles}>
        <h1 className={s.studioTitle}>
          <ScrambleText text={title} duration={380} />
        </h1>
        {subtitle && <p className={s.studioSub}>{subtitle}</p>}
      </div>
    </div>
  )
}

/** Two-pane studio layout: controls on the left, canvas/results on the right. */
export function StudioLayout({ controls, children, hue }: { controls: ReactNode; children: ReactNode; hue?: string }) {
  return (
    <div className={s.studio} style={hue ? { ['--hue' as string]: hue } : undefined}>
      <aside className={s.controls}>{controls}</aside>
      <section className={s.canvas}>{children}</section>
    </div>
  )
}

export function Section({ title, aside, children, className }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn(s.section, className)}>
      <div className={s.sectionHead}>
        <h2 className={s.sectionTitle}>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  )
}
