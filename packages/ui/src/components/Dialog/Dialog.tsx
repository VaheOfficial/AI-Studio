import { useState, type ReactNode } from 'react'
import { Dialog as D } from 'radix-ui'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn'
import { Button } from '../Button/Button'
import s from './Dialog.module.css'

export interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
}

export function Dialog({ open, onOpenChange, title, description, children, footer, size = 'md', className }: DialogProps) {
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
            <div className={s.positioner}>
              <D.Content asChild forceMount>
                <motion.div
                  className={cn(s.content, s[size], className)}
                  initial={{ opacity: 0, scale: 0.95, y: 10 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.97, y: 6 }}
                  transition={{ type: 'spring', stiffness: 420, damping: 32 }}
                >
                  <header className={s.header}>
                    <div>
                      <D.Title className={s.title}>{title}</D.Title>
                      {description ? (
                        <D.Description className={s.description}>{description}</D.Description>
                      ) : (
                        <D.Description className="sr-only">{title}</D.Description>
                      )}
                    </div>
                    <D.Close className={s.close} aria-label="Close">
                      <X size={16} />
                    </D.Close>
                  </header>
                  {children && <div className={s.body}>{children}</div>}
                  {footer && <footer className={s.footer}>{footer}</footer>}
                </motion.div>
              </D.Content>
            </div>
          </D.Portal>
        )}
      </AnimatePresence>
    </D.Root>
  )
}

export interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  confirmLabel?: string
  tone?: 'danger' | 'primary'
  onConfirm: () => void | Promise<void>
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Confirm',
  tone = 'primary',
  onConfirm,
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false)
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={tone === 'danger' ? 'danger' : 'primary'}
            loading={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onConfirm()
                onOpenChange(false)
              } finally {
                setBusy(false)
              }
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    />
  )
}
