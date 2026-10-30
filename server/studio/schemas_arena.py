"""Persisted arena matches and their realtime snapshots."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Side = Literal['left', 'right']

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class ArenaContender(Strict):
    name: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=3, max_length=200)
    stance: str = Field(default='', max_length=1200)
    persona: str = ''
    session_id: str | None = None
    state: Literal['idle','preparing','writing','working','waiting','done','error'] = 'idle'
    error: str | None = None

class ArenaCreate(Strict):
    mode: Literal['task','argument'] = 'argument'
    prompt: str = Field(min_length=1, max_length=12000)
    left: ArenaContender
    right: ArenaContender
    pacing: Literal['free','alternating'] = 'free'
    inference: Literal['auto','one','two'] = 'auto'
    replies: int = Field(default=6, ge=1, le=20)
    time_limit: int = Field(default=180, ge=15, le=1800)

class ArenaMessage(Strict):
    id: str
    side: Side | Literal['host']
    content: str = ''
    created_at: str
    status: Literal['streaming','done','interrupted','error'] = 'streaming'
    responding_to: str | None = None

class ArenaMatch(ArenaCreate):
    id: str
    status: Literal['ready','running','paused','stopped','done','error'] = 'ready'
    messages: list[ArenaMessage] = Field(default_factory=list)
    created_at: str
    updated_at: str
    revision: int = 0
    elapsed_s: float = 0
    reason: str = ''
    winner: Side | Literal['tie'] | None = None
    generation_slots: int | None = Field(default=None,ge=1,le=2)
    context_per_slot: int | None = None
    runtime_note: str = ''

class ArenaControl(Strict):
    action: Literal['start','pause','stop','step','vote']
    side: Side | None = None
    winner: Side | Literal['tie'] | None = None

class ArenaInterjection(Strict):
    text: str = Field(min_length=1, max_length=2000)

class EvArenaUpdate(BaseModel):
    type: Literal['arena.update'] = 'arena.update'
    match: ArenaMatch
