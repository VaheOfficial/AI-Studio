import {
  forwardRef,
  useCallback,
  useLayoutEffect,
  useRef,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'
import { cn } from '../../lib/cn'
import s from './Input.module.css'

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  iconLeft?: ReactNode
  trailing?: ReactNode
  size?: 'sm' | 'md' | 'lg'
  invalid?: boolean
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { iconLeft, trailing, size = 'md', invalid, className, ...rest },
  ref,
) {
  return (
    <div className={cn(s.wrap, s[size], invalid && s.invalid, rest.disabled && s.disabled, className)}>
      {iconLeft && <span className={s.iconLeft}>{iconLeft}</span>}
      <input ref={ref} className={s.input} aria-invalid={invalid || undefined} {...rest} />
      {trailing && <span className={s.trailing}>{trailing}</span>}
    </div>
  )
})

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Grow with content up to maxRows. */
  autoResize?: boolean
  minRows?: number
  maxRows?: number
  invalid?: boolean
  mono?: boolean
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { autoResize, minRows = 3, maxRows = 16, invalid, mono, className, style, onChange, ...rest },
  forwardedRef,
) {
  const inner = useRef<HTMLTextAreaElement | null>(null)

  const setRef = useCallback(
    (node: HTMLTextAreaElement | null) => {
      inner.current = node
      if (typeof forwardedRef === 'function') forwardedRef(node)
      else if (forwardedRef) forwardedRef.current = node
    },
    [forwardedRef],
  )

  const resize = useCallback(() => {
    const el = inner.current
    if (!el || !autoResize) return
    const cs = getComputedStyle(el)
    const lh = parseFloat(cs.lineHeight) || 20
    const border = parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth)
    const extra = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + border
    el.style.height = 'auto'
    const content = el.scrollHeight + border
    el.style.height = `${Math.min(Math.max(content, lh * minRows + extra), lh * maxRows + extra)}px`
    el.style.overflowY = content > lh * maxRows + extra ? 'auto' : 'hidden'
  }, [autoResize, minRows, maxRows])

  useLayoutEffect(resize, [resize, rest.value])

  // Width changes (initial layout, sidebar toggle, window resize) change wrapping, so re-measure
  useLayoutEffect(() => {
    const el = inner.current
    if (!el || !autoResize) return
    let lastWidth = el.offsetWidth
    const ro = new ResizeObserver(() => {
      if (el.offsetWidth !== lastWidth) {
        lastWidth = el.offsetWidth
        resize()
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [autoResize, resize])

  return (
    <textarea
      ref={setRef}
      rows={minRows}
      aria-invalid={invalid || undefined}
      className={cn(s.textarea, invalid && s.invalid, mono && s.mono, className)}
      style={style}
      onChange={(e) => {
        onChange?.(e)
        resize()
      }}
      {...rest}
    />
  )
})
