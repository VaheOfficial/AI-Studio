/** True on macOS, where shortcuts use ⌘ (the handlers accept either modifier everywhere). */
export const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform)

/** A shortcut label for the platform: "Ctrl K" or "⌘K". */
export const shortcut = (key: string) => (IS_MAC ? `⌘${key.toUpperCase()}` : `Ctrl ${key}`)
