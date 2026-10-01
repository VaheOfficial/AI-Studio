import { useMemo } from 'react'
import { Combobox, Skeleton, type ComboboxOption } from '@studio/ui'
import { useLanguages } from '../../api/voice'

/** Picker value meaning "let the model detect the language from the text". */
export const AUTO_LANGUAGE = 'auto'

export interface LanguagePickerProps {
  value: string
  onChange: (id: string) => void
  /** Runtime id; languages it can't speak are listed but disabled. */
  engine?: string
  /** Offer "Auto-detect" (a request/profile without a language). */
  allowAuto?: boolean
  /** Extra leading option, e.g. `{ value: '*', label: 'All languages' }` for dictionary scopes. */
  extra?: ComboboxOption
  id?: string
  size?: 'sm' | 'md'
}

/** Searchable picker over OmniVoice's 646 languages, popular ones first. */
export function LanguagePicker({ value, onChange, engine, allowAuto = true, extra, id, size }: LanguagePickerProps) {
  const { data } = useLanguages()
  const options = useMemo<ComboboxOption[]>(() => {
    if (!data) return []
    const supported = engine ? data.engines[engine] : null
    const ok = (lang: string) => !supported || supported.includes(lang)
    const byId = new Map(data.languages.map((l) => [l.id, l]))
    const option = (l: { id: string; name: string }, group: string): ComboboxOption => ({
      value: l.id,
      label: l.name,
      keywords: l.id,
      group,
      disabled: !ok(l.id),
    })
    const all = `All ${data.languages.length} languages`
    return [
      ...(extra ? [extra] : []),
      ...(allowAuto ? [{ value: AUTO_LANGUAGE, label: 'Auto-detect', description: 'From the text and the voice' }] : []),
      ...data.popular.flatMap((code) => {
        const l = byId.get(code)
        return l ? [option(l, 'Popular')] : []
      }),
      ...data.languages.map((l) => option(l, all)),
    ]
  }, [data, engine, allowAuto, extra])

  if (!data) return <Skeleton height={size === 'sm' ? 28 : 34} radius={8} />
  return (
    <Combobox
      id={id}
      size={size}
      value={value}
      onValueChange={onChange}
      options={options}
      placeholder="Language"
      searchPlaceholder="Search 646 languages…"
      emptyText="No language matches"
    />
  )
}
