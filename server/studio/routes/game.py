"""Game mode routes. A turn runs in the background; its narration streams as ``game.delta`` events and the result
arrives as ``game.turn`` (see docs/api/game.md)."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, Response

from ..agent import inventory
from ..game import combat, media, rules, store
from ..game.master import OPENING_ACTION, games
from ..schemas import Job
from ..schemas_game import CombatRequest, Game, GameActionRequest, GamePatch, GameSummary, NewGameRequest
from . import StudioRouter

router = StudioRouter(prefix="/api")


def _game(gid: str) -> Game:
    try:
        row = store.get_row(gid)
    except store.NotFound as exc:
        raise HTTPException(404, "Game not found") from exc
    return Game(id=row["id"], title=row["title"], model=row["model"], created_at=row["created_at"],
                updated_at=row["updated_at"], state=store.state_of(row), turns=store.turns(gid),
                pending=games.pending(gid), soundtrack=store.soundtrack(row))


def _check_model(model: str) -> None:
    if ":" not in model:
        raise HTTPException(400, "model must be '<provider>:<model>', e.g. 'ollama:qwen3:8b'")


@router.get("/games", response_model=list[GameSummary])
async def list_games() -> list[GameSummary]:
    return await asyncio.to_thread(store.summaries)


@router.post("/games", response_model=Game)
async def new_game(body: NewGameRequest) -> Game:
    _check_model(body.model)
    state = rules.new_state(body.setting, body.name, body.role)
    title = (body.title or "").strip() or f"{state.player.name} the {state.player.role}"
    gid = await asyncio.to_thread(store.create, title, body.model, state)
    games.start_turn(gid, OPENING_ACTION, opening=True)
    return await asyncio.to_thread(_game, gid)


@router.get("/games/{gid}", response_model=Game)
async def get_game(gid: str) -> Game:
    return await asyncio.to_thread(_game, gid)


@router.patch("/games/{gid}", response_model=Game)
async def patch_game(gid: str, body: GamePatch) -> Game:
    _game(gid)
    if body.model is not None:
        _check_model(body.model)
    await asyncio.to_thread(store.update, gid, **body.model_dump(exclude_none=True))
    return await asyncio.to_thread(_game, gid)


@router.post("/games/{gid}/actions", response_model=Game)
async def act(gid: str, body: GameActionRequest) -> Game:
    game = await asyncio.to_thread(_game, gid)
    if game.state.status != "playing":
        raise HTTPException(409, "This adventure is over — undo the last turn or start a new game")
    try:
        games.start_turn(gid, body.action.strip())
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return await asyncio.to_thread(_game, gid)


@router.post("/games/{gid}/combat", response_model=Game)
async def fight(gid: str, body: CombatRequest) -> Game:
    """A combat round settled by the rules (attack / defend / flee / use an item); the game master narrates it."""
    game = await asyncio.to_thread(_game, gid)
    if game.state.status != "playing":
        raise HTTPException(409, "This adventure is over — undo the last turn or start a new game")
    try:
        games.start_turn(gid, fight=body)
    except combat.CombatError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return await asyncio.to_thread(_game, gid)


def _turn(gid: str, turn_id: str):
    try:
        return store.get_turn(gid, turn_id)
    except store.NotFound as exc:
        raise HTTPException(404, "Turn not found") from exc


def _media(start):  # media.MediaError (nothing installed) -> 409
    try:
        return start()
    except media.MediaError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/games/{gid}/turns/{turn_id}/illustrate", response_model=Job)
async def illustrate(gid: str, turn_id: str) -> Job:
    game, turn = _game(gid), _turn(gid, turn_id)
    profile = await inventory.image_choice()
    return _media(lambda: media.illustrate(gid, turn, game.state.setting, profile))


@router.post("/games/{gid}/turns/{turn_id}/narrate", response_model=Job)
async def narrate(gid: str, turn_id: str) -> Job:
    _game(gid)
    turn = _turn(gid, turn_id)
    return _media(lambda: media.narrate(gid, turn))


@router.post("/games/{gid}/music", response_model=Job)
async def compose(gid: str) -> Job:
    """Compose a looping track for the current location, in the mood of the latest turn."""
    game = _game(gid)
    mood = next((t.mood for t in reversed(game.turns) if t.mood), "")
    return _media(lambda: media.compose(gid, game.state.location.name, mood, game.state.setting))


@router.post("/games/{gid}/stop", response_model=Game)
async def stop(gid: str) -> Game:
    task = games.stop(gid)
    if task is not None:
        await asyncio.wait({task}, timeout=10)
    return await asyncio.to_thread(_game, gid)


@router.post("/games/{gid}/undo", response_model=Game)
async def undo(gid: str) -> Game:
    game = await asyncio.to_thread(_game, gid)
    if game.pending is not None:
        raise HTTPException(409, "Wait for the current turn to finish, or stop it")
    if len(game.turns) <= 1:
        raise HTTPException(409, "Nothing to undo — this is the opening scene")
    await asyncio.to_thread(store.undo, gid)
    return await asyncio.to_thread(_game, gid)


@router.delete("/games/{gid}", status_code=204)
async def delete_game(gid: str) -> Response:
    _game(gid)
    task = games.stop(gid)
    if task is not None:
        await asyncio.wait({task}, timeout=10)
    await asyncio.to_thread(store.delete, gid)
    return Response(status_code=204)
