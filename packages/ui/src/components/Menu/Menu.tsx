import type { ReactNode } from 'react'
import { DropdownMenu as M, Popover as P } from 'radix-ui'
import { cn } from '../../lib/cn'
import s from './Menu.module.css'

export interface MenuItem {
  label: ReactNode
  icon?: ReactNode
  shortcut?: string
  danger?: boolean
  disabled?: boolean
  onSelect: () => void
}

export type MenuEntry = MenuItem | 'separator' | { heading: string }

export interface MenuProps {
  trigger: ReactNode
  items: MenuEntry[]
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
}

export function Menu({ trigger, items, align = 'end', side = 'bottom' }: MenuProps) {
  return (
    <M.Root>
      <M.Trigger asChild>{trigger}</M.Trigger>
      <M.Portal>
        <M.Content className={s.content} align={align} side={side} sideOffset={6}>
          {items.map((item, i) =>
            item === 'separator' ? (
              <M.Separator key={i} className={s.separator} />
            ) : 'heading' in item ? (
              <M.Label key={i} className={s.heading}>
                {item.heading}
              </M.Label>
            ) : (
              <M.Item
                key={i}
                className={cn(s.item, item.danger && s.danger)}
                disabled={item.disabled}
                onSelect={item.onSelect}
              >
                {item.icon && <span className={s.icon}>{item.icon}</span>}
                <span className={s.label}>{item.label}</span>
                {item.shortcut && <span className={s.shortcut}>{item.shortcut}</span>}
              </M.Item>
            ),
          )}
        </M.Content>
      </M.Portal>
    </M.Root>
  )
}

export interface PopoverProps {
  trigger: ReactNode
  children: ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  className?: string
}

export function Popover({ trigger, children, open, onOpenChange, align = 'start', side = 'bottom', className }: PopoverProps) {
  return (
    <P.Root open={open} onOpenChange={onOpenChange}>
      <P.Trigger asChild>{trigger}</P.Trigger>
      <P.Portal>
        <P.Content className={cn(s.content, s.popover, className)} align={align} side={side} sideOffset={8}>
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  )
}
