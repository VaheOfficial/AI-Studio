import type { DesignVocabulary } from '../../api/contracts/voice'

/** Picker state of the Design page: category id -> tag or "Auto" (the profile's `vd_states`). */
export type DesignAttrs = Record<string, string>

export const AUTO = 'Auto'

export const emptyAttrs = (vocab: DesignVocabulary | undefined): DesignAttrs =>
  Object.fromEntries((vocab?.categories ?? []).map((c) => [c.id, AUTO]))

/** Set one category, clearing the other members of its exclusive group. Returns the cleared category, if any. */
export function applyAttr(vocab: DesignVocabulary, attrs: DesignAttrs, category: string, value: string): [DesignAttrs, string | null] {
  const next = { ...attrs, [category]: value }
  let cleared: string | null = null
  if (value !== AUTO) {
    for (const group of vocab.exclusive) {
      if (!group.includes(category)) continue
      for (const other of group) {
        if (other !== category && next[other] && next[other] !== AUTO) {
          next[other] = AUTO
          cleared = other
        }
      }
    }
  }
  return [next, cleared]
}

/** Comma-joined tags in category order — what OmniVoice's `instruct` takes. */
export function instructOf(vocab: DesignVocabulary | undefined, attrs: DesignAttrs): string {
  return (vocab?.categories ?? [])
    .map((c) => attrs[c.id])
    .filter((v) => v && v !== AUTO)
    .join(', ')
}
