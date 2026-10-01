import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Slot } from 'radix-ui'
import { cn } from '../../lib/cn'
import { Spinner } from '../Spinner/Spinner'
import s from './Button.module.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger' | 'glow'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  iconLeft?: ReactNode
  iconRight?: ReactNode
  /** Render the child element (e.g. a router Link) with button styling. */
  asChild?: boolean
  block?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    loading = false,
    iconLeft,
    iconRight,
    asChild,
    block,
    className,
    children,
    disabled,
    type = 'button',
    ...rest
  },
  ref,
) {
  const classes = cn(s.button, s[variant], s[size], block && s.block, loading && s.loading, className)

  if (asChild) {
    return (
      <Slot.Root ref={ref} className={classes} {...rest}>
        {children}
      </Slot.Root>
    )
  }

  return (
    <button ref={ref} type={type} className={classes} disabled={disabled || loading} {...rest}>
      {loading ? <Spinner size={size === 'lg' ? 16 : 14} className={s.icon} /> : iconLeft && <span className={s.icon}>{iconLeft}</span>}
      {children != null && <span className={s.label}>{children}</span>}
      {iconRight && !loading && <span className={s.icon}>{iconRight}</span>}
    </button>
  )
})
