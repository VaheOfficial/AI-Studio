import type { RefObject } from 'react'
import { Button, Menu, type MenuEntry } from '@studio/ui'
import { Tags } from 'lucide-react'
import { useDesignVocabulary } from '../../api/voice'

const PAUSES = [
  { tag: '[pause]', label: 'Pause (350 ms)' },
  { tag: '[pause 500ms]', label: 'Pause 500 ms' },
  { tag: '[pause 1s]', label: 'Pause 1 s' },
  { tag: '[pause 2s]', label: 'Pause 2 s' },
]

/** Insert `snippet` at the textarea's caret (spaced from its neighbours) and restore focus after it. */
function insertAtCaret(el: HTMLTextAreaElement | null, text: string, snippet: string, set: (next: string) => void) {
  const start = el?.selectionStart ?? text.length
  const end = el?.selectionEnd ?? text.length
  const before = text.slice(0, start)
  const after = text.slice(end)
  const piece = `${before && !/\s$/.test(before) ? ' ' : ''}${snippet}${after && !/^\s/.test(after) ? ' ' : ''}`
  set(before + piece + after)
  requestAnimationFrame(() => {
    if (!el) return
    const caret = before.length + piece.length
    el.focus()
    el.setSelectionRange(caret, caret)
  })
}

/** "Insert tag" menu for OmniVoice scripts: pause markers and non-verbal reaction tags. */
export function TagMenu({
  target,
  text,
  onChange,
  disabled,
}: {
  target: RefObject<HTMLTextAreaElement | null>
  text: string
  onChange: (next: string) => void
  disabled?: boolean
}) {
  const { data } = useDesignVocabulary()
  const insert = (tag: string) => insertAtCaret(target.current, text, tag, onChange)
  const items: MenuEntry[] = [
    { heading: 'Silence' },
    ...PAUSES.map((p) => ({ label: p.label, shortcut: p.tag, onSelect: () => insert(p.tag) })),
    'separator',
    { heading: 'Reactions' },
    ...(data?.reaction_tags ?? []).map((tag) => ({ label: tag.slice(1, -1).replace('-', ' · '), onSelect: () => insert(tag) })),
  ]
  return (
    <Menu
      align="start"
      trigger={
        <Button size="sm" variant="ghost" iconLeft={<Tags />} disabled={disabled}>
          Insert tag
        </Button>
      }
      items={items}
    />
  )
}
