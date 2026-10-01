import { useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronRight } from 'lucide-react'
import { cn } from '@studio/ui'
import s from './Sidebar.module.css'

/** Collapsible card in the dub settings column. */
export function SidebarSection({
  title,
  icon,
  aside,
  defaultOpen = true,
  children,
}: {
  title: ReactNode
  icon?: ReactNode
  aside?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={s.section}>
      <button type="button" className={s.sectionHead} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <ChevronRight size={14} className={cn(s.chevron, open && s.open)} />
        {icon && <span className={s.sectionIcon}>{icon}</span>}
        <span className={s.sectionTitle}>{title}</span>
        {aside && <span className={s.sectionAside}>{aside}</span>}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            className={s.sectionBody}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className={s.sectionInner}>{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}
