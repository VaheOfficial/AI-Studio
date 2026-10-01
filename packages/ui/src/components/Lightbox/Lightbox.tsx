import type { ReactNode } from 'react'
import { Dialog as D } from 'radix-ui'
import { AnimatePresence, motion } from 'motion/react'
import { Download, X } from 'lucide-react'
import s from './Lightbox.module.css'

export interface LightboxProps {
  /** Image to show; null/undefined closes the lightbox. */
  src?: string | null
  alt?: string
  caption?: ReactNode
  onClose: () => void
  /** Offer a download button with this file name. */
  downloadName?: string
}

/** Full-screen image viewer: click anywhere or press Esc to close. */
export function Lightbox({ src, alt = '', caption, onClose, downloadName }: LightboxProps) {
  const open = !!src
  return (
    <D.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <AnimatePresence>
        {open && (
          <D.Portal forceMount>
            <D.Overlay asChild forceMount>
              <motion.div className={s.overlay} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
            </D.Overlay>
            <D.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                className={s.stage}
                onClick={onClose}
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              >
                <D.Title className="sr-only">{alt || 'Image'}</D.Title>
                <img className={s.image} src={src} alt={alt} onClick={(e) => e.stopPropagation()} />
                <div className={s.bar} onClick={(e) => e.stopPropagation()}>
                  {caption && <div className={s.caption}>{caption}</div>}
                  {downloadName && (
                    <a className={s.action} href={src} download={downloadName} aria-label="Download">
                      <Download size={16} />
                    </a>
                  )}
                  <D.Close className={s.action} aria-label="Close">
                    <X size={16} />
                  </D.Close>
                </div>
              </motion.div>
            </D.Content>
          </D.Portal>
        )}
      </AnimatePresence>
    </D.Root>
  )
}
