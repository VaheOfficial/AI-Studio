"""Arena routes use the normal configured providers and tool permissions."""
from fastapi import HTTPException
from . import StudioRouter
from .. import arena
from ..schemas_arena import ArenaCreate, ArenaMatch, ArenaControl, ArenaInterjection

router=StudioRouter(prefix='/api/arena')

@router.get('',response_model=list[ArenaMatch])
async def matches():
    return [arena.runner.get(m.id) for m in arena.listing()]

@router.post('',response_model=ArenaMatch)
async def create(body:ArenaCreate):
    try:return arena.runner.create(body)
    except (ValueError,RuntimeError) as exc:raise HTTPException(400,str(exc)) from exc

@router.get('/{key}',response_model=ArenaMatch)
async def get(key:str):
    try:return arena.runner.get(key)
    except KeyError as exc:raise HTTPException(404,str(exc)) from exc

@router.post('/{key}/control',response_model=ArenaMatch)
async def control(key:str,body:ArenaControl):
    try:return await arena.runner.control(key,body)
    except KeyError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc

@router.post('/{key}/interject',response_model=ArenaMatch)
async def interject(key:str,body:ArenaInterjection):
    try:return arena.runner.interject(key,body.text)
    except KeyError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
