import { useEffect, useSyncExternalStore, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { CheckCircle2, Info, TriangleAlert, X, XCircle } from 'lucide-react'
import { cn } from '../../lib/cn'
import s from './Toast.module.css'

type Tone = 'info' | 'success' | 'warning' | 'error'

export interface ToastOptions {
  title: ReactNode
  description?: ReactNode
  tone?: Tone
  /** ms; 0 = sticky */
  duration?: number
  action?: { label: string; onClick: () => void }
}

interface ToastItem extends ToastOptions {
  id: number
}

let items: ToastItem[] = []
let nextId = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

function push(opts: ToastOptions) {
  const id = nextId++
  items = [...items.slice(-4), { duration: 4500, tone: 'info', ...opts, id }]
  emit()
  return id
}

export function dismissToast(id: number) {
  items = items.filter((t) => t.id !== id)
  emit()
}

/** Imperative toast API usable anywhere (no hook needed). */
export const toast = Object.assign(push, {
  success: (title: ReactNode, description?: ReactNode) => push({ title, description, tone: 'success' }),
  error: (title: ReactNode, description?: ReactNode) => push({ title, description, tone: 'error', duration: 7000 }),
  warning: (title: ReactNode, description?: ReactNode) => push({ title, description, tone: 'warning' }),
  info: (title: ReactNode, description?: ReactNode) => push({ title, description, tone: 'info' }),
})

const icons: Record<Tone, ReactNode> = {
  info: <Info />,
  success: <CheckCircle2 />,
  warning: <TriangleAlert />,
  error: <XCircle />,
}

function ToastView({ item }: { item: ToastItem }) {
  useEffect(() => {
    if (!item.duration) return
    const t = setTimeout(() => dismissToast(item.id), item.duration)
    return () => clearTimeout(t)
  }, [item.id, item.duration])

  return (
    <motion.li
      layout
      role="status"
      className={cn(s.toast, s[item.tone ?? 'info'])}
      initial={{ opacity: 0, y: 24, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 40, scale: 0.96, transition: { duration: 0.18 } }}
      transition={{ type: 'spring', stiffness: 420, damping: 34 }}
    >
      <span className={s.icon}>{icons[item.tone ?? 'info']}</span>
      <div className={s.body}>
        <p className={s.title}>{item.title}</p>
        {item.description && <p className={s.description}>{item.description}</p>}
        {item.action && (
          <button
            className={s.action}
            onClick={() => {
              item.action!.onClick()
              dismissToast(item.id)
            }}
          >
            {item.action.label}
          </button>
        )}
      </div>
      <button className={s.close} aria-label="Dismiss" onClick={() => dismissToast(item.id)}>
        <X size={14} />
      </button>
    </motion.li>
  )
}

export function Toaster() {
  const list = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => items,
  )
  return (
    <ol className={s.viewport} aria-live="polite">
      <AnimatePresence initial={false}>
        {list.map((t) => (
          <ToastView key={t.id} item={t} />
        ))}
      </AnimatePresence>
    </ol>
  )
}
