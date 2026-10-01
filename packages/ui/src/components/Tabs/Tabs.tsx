import { useId, type ReactNode } from 'react'
import { Tabs as R } from 'radix-ui'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'
import s from './Tabs.module.css'

export interface TabItem<V extends string = string> {
  value: V
  label: ReactNode
  icon?: ReactNode
  badge?: ReactNode
}

export interface TabsProps<V extends string = string> {
  value: V
  onValueChange: (value: V) => void
  items: TabItem<V>[]
  /** "underline" for page sections, "pill" for compact switchers. */
  variant?: 'underline' | 'pill'
  className?: string
  children?: ReactNode
}

/** Tab bar with a spring-animated active indicator. Pair with <TabPanel> children. */
export function Tabs<V extends string = string>({ value, onValueChange, items, variant = 'underline', className, children }: TabsProps<V>) {
  const layoutId = useId()
  return (
    <R.Root value={value} onValueChange={(v) => onValueChange(v as V)} className={className}>
      <R.List className={cn(s.list, s[variant])}>
        {items.map((item) => (
          <R.Trigger key={item.value} value={item.value} className={s.trigger}>
            {value === item.value && (
              <motion.span
                layoutId={layoutId}
                className={s.indicator}
                transition={{ type: 'spring', stiffness: 500, damping: 38 }}
              />
            )}
            <span className={s.triggerInner}>
              {item.icon}
              {item.label}
              {item.badge}
            </span>
          </R.Trigger>
        ))}
      </R.List>
      {children}
    </R.Root>
  )
}

export function TabPanel({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <R.Content value={value} className={cn(s.panel, className)}>
      {children}
    </R.Content>
  )
}
