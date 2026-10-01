import { useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Popover as P } from 'radix-ui'
import { Check, ChevronDown, Search } from 'lucide-react'
import { cn } from '../../lib/cn'
import s from './Combobox.module.css'

export interface ComboboxOption<V extends string = string> {
  value: V
  label: string
  description?: ReactNode
  /** Extra text matched by the search (e.g. a language code). */
  keywords?: string
  disabled?: boolean
  /** Section heading the option is listed under, e.g. "Popular". Options keep their order within a group. */
  group?: string
}

export interface ComboboxProps<V extends string = string> {
  value: V | undefined
  onValueChange: (value: V) => void
  options: ComboboxOption<V>[]
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  id?: string
  size?: 'sm' | 'md'
  disabled?: boolean
  className?: string
}

/** A select with a search box — for long option lists (hundreds of languages, voices). */
export function Combobox<V extends string = string>({
  value,
  onValueChange,
  options,
  placeholder = 'Select…',
  searchPlaceholder = 'Search…',
  emptyText = 'No matches',
  id,
  size = 'md',
  disabled,
  className,
}: ComboboxProps<V>) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listId = useId()
  const listRef = useRef<HTMLDivElement>(null)
  const selected = options.find((o) => o.value === value)

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => o.label.toLowerCase().includes(q) || o.keywords?.toLowerCase().includes(q))
  }, [options, query])

  const setOpenState = (next: boolean) => {
    setOpen(next)
    if (next) {
      setQuery('')
      setActive(Math.max(0, options.findIndex((o) => o.value === value)))
    }
  }

  const choose = (o: ComboboxOption<V>) => {
    if (o.disabled) return
    onValueChange(o.value)
    setOpen(false)
  }

  const move = (delta: number) => {
    if (!shown.length) return
    let next = active
    for (let i = 0; i < shown.length; i++) {
      next = (next + delta + shown.length) % shown.length
      if (!shown[next].disabled) break
    }
    setActive(next)
    listRef.current?.querySelector(`[data-index="${next}"]`)?.scrollIntoView({ block: 'nearest' })
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      move(e.key === 'ArrowDown' ? 1 : -1)
    } else if (e.key === 'Enter' && shown[active]) {
      e.preventDefault()
      choose(shown[active])
    }
  }

  return (
    <P.Root open={open} onOpenChange={setOpenState}>
      <P.Trigger id={id} disabled={disabled} className={cn(s.trigger, s[size], className)} aria-haspopup="listbox">
        <span className={cn(s.value, !selected && s.placeholder)}>{selected?.label ?? placeholder}</span>
        <ChevronDown size={15} className={s.chevron} />
      </P.Trigger>
      <P.Portal>
        <P.Content className={s.content} align="start" sideOffset={6} onOpenAutoFocus={(e) => e.preventDefault()}>
          <div className={s.search}>
            <Search size={14} />
            <input
              autoFocus
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActive(0)
              }}
              onKeyDown={onKeyDown}
              placeholder={searchPlaceholder}
              role="combobox"
              aria-expanded
              aria-controls={listId}
              aria-activedescendant={shown[active] ? `${listId}-${active}` : undefined}
            />
          </div>
          <div ref={listRef} id={listId} role="listbox" className={s.list}>
            {shown.length === 0 && <div className={s.empty}>{emptyText}</div>}
            {shown.map((o, i) => (
              <div key={`${o.group ?? ''}:${o.value}`}>
                {o.group && o.group !== shown[i - 1]?.group && <div className={s.group}>{o.group}</div>}
                <div
                  id={`${listId}-${i}`}
                  data-index={i}
                  role="option"
                  aria-selected={o.value === value}
                  aria-disabled={o.disabled}
                  className={cn(s.item, i === active && s.active, o.disabled && s.disabled)}
                  onMouseMove={() => i !== active && !o.disabled && setActive(i)}
                  onClick={() => choose(o)}
                >
                  <span className={s.itemText}>
                    <span className={s.label}>{o.label}</span>
                    {o.description && <span className={s.description}>{o.description}</span>}
                  </span>
                  {o.value === value && <Check size={14} className={s.check} />}
                </div>
              </div>
            ))}
          </div>
        </P.Content>
      </P.Portal>
    </P.Root>
  )
}
