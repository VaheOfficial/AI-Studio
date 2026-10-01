/** Slash commands typed in the chat composer (`/compact`, `/context 32k`, …). ChatPage runs them. */
export interface SlashCommand {
  name: string
  args?: string
  description: string
}

export const COMMANDS: SlashCommand[] = [
  { name: 'compact', args: '[what to keep]', description: 'Summarize the chat so far to free context; the model continues from the summary' },
  { name: 'context', args: '<32k | 1m | auto>', description: "Set this chat's context window (smaller = faster, cheaper)" },
  { name: 'model', args: '<name>', description: 'Switch this chat to another model' },
  { name: 'mode', args: '<agent | chat>', description: 'Agent (tools) or plain chat' },
  { name: 'new', description: 'Start a new chat' },
  { name: 'help', description: 'List the commands' },
]

/** `/name args…` → [name, args]; undefined when the text isn't a command. */
export function parseCommand(text: string): [string, string] | undefined {
  const m = /^\/(\w+)\s*([\s\S]*)$/.exec(text.trim())
  return m ? [m[1].toLowerCase(), m[2].trim()] : undefined
}

/** Commands matching what has been typed after the slash (only while typing the name). */
export function matchCommands(text: string): SlashCommand[] {
  const m = /^\/(\w*)$/.exec(text)
  if (!m) return []
  return COMMANDS.filter((c) => c.name.startsWith(m[1].toLowerCase()))
}

/** "32k" → 32768, "1m" → 1048576, "200000" → 200000, "auto" → 0; undefined when unreadable. */
export function parseTokens(value: string): number | undefined {
  const v = value.trim().toLowerCase()
  if (v === 'auto' || v === 'default') return 0
  const m = /^(\d+(?:\.\d+)?)\s*([km]?)$/.exec(v)
  if (!m) return undefined
  const n = Number(m[1]) * (m[2] === 'm' ? 1024 * 1024 : m[2] === 'k' ? 1024 : 1)
  return Number.isFinite(n) && n >= 1024 ? Math.round(n) : undefined
}
