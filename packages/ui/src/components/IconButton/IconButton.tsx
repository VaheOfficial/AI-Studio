import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from '../../lib/cn'
import { Tooltip } from '../Tooltip/Tooltip'
import s from './IconButton.module.css'

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  /** Accessible name; also shown as tooltip. */
  label: string
  icon: ReactNode
  size?: 'sm' | 'md' | 'lg'
  variant?: 'ghost' | 'secondary' | 'primary' | 'danger'
  active?: boolean
  tooltip?: boolean
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left'
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, size = 'md', variant = 'ghost', active, tooltip = true, tooltipSide = 'top', className, type = 'button', ...rest },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      data-active={active || undefined}
      className={cn(s.iconButton, s[size], s[variant], className)}
      {...rest}
    >
      {icon}
    </button>
  )
  return tooltip ? (
    <Tooltip content={label} side={tooltipSide}>
      {button}
    </Tooltip>
  ) : (
    button
  )
})
