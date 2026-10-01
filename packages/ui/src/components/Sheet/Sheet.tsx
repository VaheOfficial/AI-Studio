import type { ReactNode } from 'react'
import { Dialog as D } from 'radix-ui'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn'
import s from './Sheet.module.css'

export interface SheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  /** Leading visual in the header (icon tile, avatar). */
  icon?: ReactNode
  /** Buttons/links shown next to the close button. */
  actions?: ReactNode
  children?: ReactNode
  size?: 'md' | 'lg'
  className?: string
}

/** A panel that slides in from the right edge — for detail views that keep the page behind them in context. */
export function Sheet({ open, onOpenChange, title, description, icon, actions, children, size = 'lg', className }: SheetProps) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <D.Portal forceMount>
            <D.Overlay asChild forceMount>
              <motion.div
                className={s.overlay}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
              />
            </D.Overlay>
            <D.Content asChild forceMount>
              <motion.aside
                className={cn(s.content, s[size], className)}
                initial={{ x: '100%', opacity: 0.6 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: '100%', opacity: 0.6 }}
                transition={{ type: 'spring', stiffness: 380, damping: 40 }}
              >
                <header className={s.header}>
                  {icon && <div className={s.icon}>{icon}</div>}
                  <div className={s.titles}>
                    <D.Title className={s.title}>{title}</D.Title>
                    {description ? (
                      <D.Description className={s.description}>{description}</D.Description>
                    ) : (
                      <D.Description className="sr-only">{title}</D.Description>
                    )}
                  </div>
                  {actions && <div className={s.actions}>{actions}</div>}
                  <D.Close className={s.close} aria-label="Close">
                    <X size={16} />
                  </D.Close>
                </header>
                <div className={s.body}>{children}</div>
              </motion.aside>
            </D.Content>
          </D.Portal>
        )}
      </AnimatePresence>
    </D.Root>
  )
}
