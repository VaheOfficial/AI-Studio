import type { ReactNode } from 'react'
import { cn } from '@studio/ui'
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
      {icon && <div className={s.icon}>{icon}</div>}
      <div className={s.titles}>
        <h1 className={s.title}>{title}</h1>
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
      <div className={cn(s.body, wide && s.wide, className)}>{children}</div>
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
