import type { OutputKind } from './types'

/** React Query keys for data fetched on demand over REST (pushed state lives in `useLive`). */
export const qk = {
  catalog: ['catalog'] as const,
  settings: ['settings'] as const,
  /** Follows the settings: a cloud key turns image and voice on for machines without a GPU. */
  capabilities: ['capabilities'] as const,
  outputs: (kind?: OutputKind) => ['outputs', kind ?? 'all'] as const,
  /** Voice profiles: presets appear/disappear with their models. */
  voiceProfiles: ['voice', 'profiles'] as const,
  chatModels: ['chat-models'] as const,
  memories: ['memories'] as const,
  sessions: ['sessions'] as const,
  session: (id: string) => ['session', id] as const,
  openrouterAccount: ['openrouter', 'account'] as const,
  cloudModels: (query: string) => ['openrouter', 'models', query] as const,
  hubSearch: (query: string) => ['hub', 'search', query] as const,
  /** Prefix of every repo detail (installed markers change when models are installed or removed). */
  hubRepos: ['hub', 'repo'] as const,
  hubRepo: (source: string, id: string) => ['hub', 'repo', source, id] as const,
  localBackends: ['hub', 'backends'] as const,
}
