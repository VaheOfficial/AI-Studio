import type { ReactNode } from 'react'
import { Command as C } from 'cmdk'
import { Dialog as D } from 'radix-ui'
import { AnimatePresence, motion } from 'motion/react'
import { Search } from 'lucide-react'
import { Kbd } from '../Misc/Misc'
import s from './Command.module.css'

export interface CommandAction {
  id: string
  label: string
  group: string
  icon?: ReactNode
  hint?: ReactNode
  shortcut?: string
  keywords?: string[]
  onRun: () => void
}

export interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  actions: CommandAction[]
  placeholder?: string
}

/** ⌘K palette. Fuzzy filtering and keyboard nav come from cmdk. */
export function CommandPalette({ open, onOpenChange, actions, placeholder = 'Type a command or search…' }: CommandPaletteProps) {
  const groups = [...new Set(actions.map((a) => a.group))]
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <D.Portal forceMount>
            <D.Overlay asChild forceMount>
              <motion.div className={s.overlay} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
            </D.Overlay>
            <D.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                className={s.dialog}
                initial={{ opacity: 0, scale: 0.96, y: -8 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98, y: -4 }}
                transition={{ type: 'spring', stiffness: 500, damping: 36 }}
              >
                <D.Title className="sr-only">Command palette</D.Title>
                <C loop className={s.command}>
                  <div className={s.inputRow}>
                    <Search size={16} className={s.searchIcon} />
                    <C.Input autoFocus placeholder={placeholder} className={s.input} />
                    <Kbd>Esc</Kbd>
                  </div>
                  <C.List className={s.list}>
                    <C.Empty className={s.empty}>No results.</C.Empty>
                    {groups.map((g) => (
                      <C.Group key={g} heading={g} className={s.group}>
                        {actions
                          .filter((a) => a.group === g)
                          .map((a) => (
                            <C.Item
                              key={a.id}
                              value={`${a.label} ${a.group}`}
                              keywords={a.keywords}
                              className={s.item}
                              onSelect={() => {
                                onOpenChange(false)
                                a.onRun()
                              }}
                            >
                              {a.icon && <span className={s.icon}>{a.icon}</span>}
                              <span className={s.label}>{a.label}</span>
                              {a.hint && <span className={s.hint}>{a.hint}</span>}
                              {a.shortcut && <Kbd>{a.shortcut}</Kbd>}
                            </C.Item>
                          ))}
                      </C.Group>
                    ))}
                  </C.List>
                </C>
              </motion.div>
            </D.Content>
          </D.Portal>
        )}
      </AnimatePresence>
    </D.Root>
  )
}
