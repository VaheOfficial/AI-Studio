import type { ReactNode } from 'react'
import { Select as S } from 'radix-ui'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '../../lib/cn'
import s from './Select.module.css'

export interface SelectOption<V extends string = string> {
  value: V
  label: ReactNode
  description?: ReactNode
  icon?: ReactNode
  disabled?: boolean
}

export interface SelectGroup<V extends string = string> {
  label: string
  options: SelectOption<V>[]
}

export interface SelectProps<V extends string = string> {
  value: V | undefined
  onValueChange: (value: V) => void
  options: SelectOption<V>[] | SelectGroup<V>[]
  placeholder?: string
  id?: string
  size?: 'sm' | 'md'
  disabled?: boolean
  className?: string
  /** Render in trigger instead of the selected option's label. */
  renderValue?: (option: SelectOption<V> | undefined) => ReactNode
}

function isGrouped<V extends string>(o: SelectOption<V>[] | SelectGroup<V>[]): o is SelectGroup<V>[] {
  return o.length > 0 && 'options' in o[0]
}

export function Select<V extends string = string>({
  value,
  onValueChange,
  options,
  placeholder = 'Select…',
  id,
  size = 'md',
  disabled,
  className,
  renderValue,
}: SelectProps<V>) {
  const groups: SelectGroup<V>[] = isGrouped(options) ? options : [{ label: '', options }]
  const flat = groups.flatMap((g) => g.options)
  const selected = flat.find((o) => o.value === value)

  return (
    <S.Root value={value} onValueChange={(v) => onValueChange(v as V)} disabled={disabled}>
      <S.Trigger id={id} className={cn(s.trigger, s[size], className)}>
        <span className={s.value}>
          {renderValue ? (
            renderValue(selected)
          ) : selected ? (
            <>
              {selected.icon && <span className={s.optIcon}>{selected.icon}</span>}
              <span className={s.truncate}>{selected.label}</span>
            </>
          ) : (
            <span className={s.placeholder}>{placeholder}</span>
          )}
        </span>
        <S.Icon className={s.chevron}>
          <ChevronDown size={15} />
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content className={s.content} position="popper" sideOffset={6}>
          <S.Viewport className={s.viewport}>
            {groups.map((g, gi) => (
              <S.Group key={g.label || gi}>
                {g.label && <S.Label className={s.groupLabel}>{g.label}</S.Label>}
                {g.options.map((o) => (
                  <S.Item key={o.value} value={o.value} disabled={o.disabled} className={s.item}>
                    {o.icon && <span className={s.optIcon}>{o.icon}</span>}
                    <span className={s.itemText}>
                      <S.ItemText>{o.label}</S.ItemText>
                      {o.description && <span className={s.description}>{o.description}</span>}
                    </span>
                    <S.ItemIndicator className={s.check}>
                      <Check size={14} />
                    </S.ItemIndicator>
                  </S.Item>
                ))}
              </S.Group>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  )
}
