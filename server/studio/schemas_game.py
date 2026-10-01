"""Game mode: a text RPG run by a chat model as game master. Mirrors ``apps/studio/src/api/contracts/game.ts``.

The game's truth is the structured ``GameState`` on the server; the model only proposes changes to it each turn
(validated and applied by ``studio.game.rules``), so nothing depends on the model remembering the story."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GameItemKind = Literal["weapon", "armor", "consumable", "key", "misc"]
GameStatus = Literal["playing", "dead", "won"]
GameQuestStatus = Literal["active", "done", "failed"]
GameChangeTone = Literal["good", "bad", "neutral"]


class GameStats(BaseModel):
    strength: int = 10
    dexterity: int = 10
    intelligence: int = 10
    charisma: int = 10


class GamePlayer(BaseModel):
    name: str
    role: str
    level: int = 1
    xp: int = 0
    xp_next: int = 100
    hp: int
    max_hp: int
    gold: int = 0
    stats: GameStats
    conditions: list[str] = Field(default_factory=list)


class GameItem(BaseModel):
    id: str
    name: str
    kind: GameItemKind = "misc"
    qty: int = 1
    description: str = ""
    equipped: bool = False
    power: int | None = None  # damage for weapons, defense for armor, healing for consumables


class GameEnemy(BaseModel):
    id: str
    name: str
    hp: int
    max_hp: int
    description: str = ""
    ac: int = 11  # armor class: an attack roll + bonus must reach it to hit
    attack: int = 2  # added to the enemy's d20 attack roll
    damage: int = 4  # base damage of a hit
    xp: int = 10  # awarded when it is defeated


class GameQuest(BaseModel):
    id: str
    title: str
    status: GameQuestStatus = "active"
    notes: str = ""


class GameLocation(BaseModel):
    name: str = "Unknown"
    description: str = ""


class GameState(BaseModel):
    setting: str
    player: GamePlayer
    inventory: list[GameItem] = Field(default_factory=list)
    location: GameLocation = Field(default_factory=GameLocation)
    quests: list[GameQuest] = Field(default_factory=list)
    enemies: list[GameEnemy] = Field(default_factory=list)  # the current encounter; empty = none
    facts: list[str] = Field(default_factory=list)  # what the game master must remember (NPCs, promises, secrets)
    summary: str = ""  # the story before the journal, rewritten by the game master when the journal is folded
    chronicle: list[str] = Field(default_factory=list)  # the journal: one line per turn, kept by the server
    status: GameStatus = "playing"
    dice_bag: list[int] = Field(default_factory=list)  # d20 results left in the bag (rules.draw_d20)
    enemy_bag: list[int] = Field(default_factory=list)  # the enemies' own d20 bag


class GameChange(BaseModel):
    """One applied change, as shown on the turn (e.g. "-6 HP", "+ Iron Key")."""
    text: str
    tone: GameChangeTone = "neutral"


class CombatRoll(BaseModel):
    """One attack (or escape attempt) the rules resolved: ``roll`` + ``bonus`` = ``total`` against ``against``."""
    actor: str
    target: str
    roll: int
    bonus: int
    total: int
    against: int
    hit: bool
    damage: int = 0
    note: str = ""  # "critical", "fumble", "escaped"…


class GameTurn(BaseModel):
    id: str
    seq: int
    action: str
    roll: int | None = None  # the d20 the server rolled for the action
    narration: str
    choices: list[str]
    changes: list[GameChange] = Field(default_factory=list)
    combat: list[CombatRoll] = Field(default_factory=list)  # a combat round resolved by the rules
    scene: str = ""  # a visual description of the moment (what "Illustrate" draws)
    mood: str = ""  # music style tags for the moment (what "Compose music" plays)
    image: str | None = None
    audio: str | None = None
    created_at: str


class GamePending(BaseModel):
    """A turn being written: the action, its roll and the narration streamed so far."""
    action: str
    roll: int | None = None
    narration: str = ""
    combat: list[CombatRoll] = Field(default_factory=list)


class GameSummary(BaseModel):
    id: str
    title: str
    player_name: str
    role: str
    level: int
    status: GameStatus
    turns: int
    updated_at: str


class Game(BaseModel):
    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    state: GameState
    turns: list[GameTurn]
    pending: GamePending | None = None
    soundtrack: dict[str, str] = Field(default_factory=dict)  # location name -> composed music url


class NewGameRequest(BaseModel):
    model: str
    setting: str = Field(min_length=3, max_length=2000)
    name: str = Field(min_length=1, max_length=60)
    role: str = Field(min_length=1, max_length=60)
    title: str | None = Field(None, max_length=80)


class GameActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=1000)


class CombatRequest(BaseModel):
    kind: Literal["attack", "defend", "flee", "item"]
    target: str | None = None  # enemy id for "attack" (default: the first enemy)
    item: str | None = None  # consumable name for "item"


class GamePatch(BaseModel):
    title: str | None = Field(None, max_length=80)
    model: str | None = None


class EvGameDelta(BaseModel):
    type: Literal["game.delta"] = "game.delta"
    game_id: str
    text: str


class EvGameTurn(BaseModel):
    type: Literal["game.turn"] = "game.turn"
    game_id: str
    turn: GameTurn
    state: GameState


class EvGameError(BaseModel):
    type: Literal["game.error"] = "game.error"
    game_id: str
    message: str


class EvGameMedia(BaseModel):
    """Art, narration or music finished (``error`` when it failed)."""
    type: Literal["game.media"] = "game.media"
    game_id: str
    turn_id: str | None = None
    image: str | None = None
    audio: str | None = None
    location: str | None = None
    music: str | None = None
    error: str | None = None


GAME_SERVER_EVENTS = (EvGameDelta, EvGameTurn, EvGameError, EvGameMedia)
