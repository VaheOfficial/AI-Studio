export type ArenaSide = 'left' | 'right'
export interface ArenaContender {
  name: string
  model: string
  stance: string
  persona: string
  session_id?: string
  state: 'idle' | 'preparing' | 'writing' | 'working' | 'waiting' | 'done' | 'error'
  error?: string
}
export interface ArenaCreate {
  mode: 'task' | 'argument'
  prompt: string
  left: ArenaContender
  right: ArenaContender
  pacing: 'free' | 'alternating'
  inference: 'auto' | 'one' | 'two'
  replies: number
  time_limit: number
}
export interface ArenaMessage {
  id: string
  side: ArenaSide | 'host'
  content: string
  created_at: string
  status: 'streaming' | 'done' | 'interrupted' | 'error'
  responding_to?: string
}
export interface ArenaMatch extends ArenaCreate {
  id: string
  status: 'ready' | 'running' | 'paused' | 'stopped' | 'done' | 'error'
  messages: ArenaMessage[]
  created_at: string
  updated_at: string
  revision: number
  elapsed_s: number
  reason: string
  winner?: ArenaSide | 'tie'
  generation_slots?: number
  context_per_slot?: number
  runtime_note: string
}
export interface ArenaControl { action: 'start' | 'pause' | 'stop' | 'step' | 'vote'; side?: ArenaSide; winner?: ArenaSide | 'tie' }
export interface ArenaServerEvent { type: 'arena.update'; match: ArenaMatch }
