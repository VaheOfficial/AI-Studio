/**
 * Game mode: a text RPG with a chat model as game master (mirrored by `server/studio/schemas_game.py`).
 *
 * The truth is the structured `GameState` kept by the server. The model only proposes changes each turn, which the
 * server validates and applies, so the story survives any context loss. Routes: docs/api/game.md.
 */

export type GameItemKind = 'weapon' | 'armor' | 'consumable' | 'key' | 'misc'
export type GameStatus = 'playing' | 'dead' | 'won'
export type GameQuestStatus = 'active' | 'done' | 'failed'
export type GameChangeTone = 'good' | 'bad' | 'neutral'

export interface GameStats {
  strength: number
  dexterity: number
  intelligence: number
  charisma: number
}

export interface GamePlayer {
  name: string
  role: string
  level: number
  xp: number
  xp_next: number
  hp: number
  max_hp: number
  gold: number
  stats: GameStats
  conditions: string[]
}

export interface GameItem {
  id: string
  name: string
  kind: GameItemKind
  qty: number
  description: string
  equipped: boolean
  /** Damage for weapons, defense for armor, healing for consumables. */
  power?: number
}

export interface GameEnemy {
  id: string
  name: string
  hp: number
  max_hp: number
  description: string
  /** Armor class: an attack roll plus bonus must reach it to hit. */
  ac: number
  /** Added to the enemy's d20 attack roll. */
  attack: number
  /** Base damage of a hit. */
  damage: number
  /** Awarded when it is defeated. */
  xp: number
}

export interface GameQuest {
  id: string
  title: string
  status: GameQuestStatus
  notes: string
}

export interface GameState {
  setting: string
  player: GamePlayer
  inventory: GameItem[]
  location: { name: string; description: string }
  quests: GameQuest[]
  /** The current encounter; empty when there is none. */
  enemies: GameEnemy[]
  /** What the game master must remember (names, promises, secrets). */
  facts: string[]
  /** The story before the journal, rewritten by the game master whenever the journal is folded into it. */
  summary: string
  /** The journal: one line per turn, kept by the server (the oldest are folded into `summary`). */
  chronicle: string[]
  status: GameStatus
  /** d20 results still in the bag: rolls are drawn without replacement and the bag refills at 4 left. */
  dice_bag: number[]
  /** The enemies' own d20 bag. */
  enemy_bag: number[]
}

/** One applied change, as shown on the turn (e.g. "-6 HP", "+ Iron Key"). */
export interface GameChange {
  text: string
  tone: GameChangeTone
}

/** One attack (or escape attempt) the rules resolved: `roll` + `bonus` = `total` against `against`. */
export interface CombatRoll {
  actor: string
  /** The one attacked, or "escape" for a flee attempt. */
  target: string
  roll: number
  bonus: number
  total: number
  against: number
  hit: boolean
  damage: number
  /** "critical", "fumble", "escaped", "with Iron Sword"… */
  note: string
}

export interface GameTurn {
  id: string
  seq: number
  action: string
  /** The d20 the server rolled for the action (none for the opening scene). */
  roll?: number
  narration: string
  choices: string[]
  changes: GameChange[]
  /** A combat round the rules resolved (empty for other turns). */
  combat: CombatRoll[]
  /** What "Illustrate" draws: a visual description of the moment. */
  scene: string
  /** Music style tags for the moment (what "Compose music" plays). */
  mood: string
  image?: string
  audio?: string
  created_at: string
}

/** A turn being written: the action, its roll and the narration streamed so far. */
export interface GamePending {
  action: string
  roll?: number
  narration: string
  combat: CombatRoll[]
}

export interface GameSummary {
  id: string
  title: string
  player_name: string
  role: string
  level: number
  status: GameStatus
  turns: number
  updated_at: string
}

export interface Game {
  id: string
  title: string
  model: string
  created_at: string
  updated_at: string
  state: GameState
  turns: GameTurn[]
  pending?: GamePending
  /** Location name -> composed music url. */
  soundtrack: Record<string, string>
}

export interface NewGameRequest {
  model: string
  setting: string
  name: string
  role: string
  title?: string
}

export interface GameActionRequest {
  action: string
}

export interface CombatRequest {
  kind: 'attack' | 'defend' | 'flee' | 'item'
  /** Enemy id for "attack" (default: the first enemy). */
  target?: string
  /** Consumable name for "item". */
  item?: string
}

export interface GamePatch {
  title?: string
  model?: string
}

export type GameServerEvent =
  | { type: 'game.delta'; game_id: string; text: string }
  | { type: 'game.turn'; game_id: string; turn: GameTurn; state: GameState }
  | { type: 'game.error'; game_id: string; message: string }
  | {
      type: 'game.media'
      game_id: string
      turn_id?: string
      image?: string
      audio?: string
      location?: string
      music?: string
      /** Set when the art, narration or music failed. */
      error?: string
    }
