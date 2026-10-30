"""Declarative animation catalog, validation, preview and exact-frame export."""
import asyncio
from fastapi import HTTPException
from ..schemas import Job
from ..schemas_animation import AnimationComposition,AnimationRenderRequest,AnimationValidation
from ..animation import catalog,recipes,render
from . import StudioRouter
router=StudioRouter(prefix='/api/animation')
@router.get('/catalog')
async def get_catalog():return catalog.catalog()
@router.get('/recipes/{key}',response_model=AnimationComposition)
async def get_recipe(key:str,width:int=1280,height:int=720,fps:int=24):
    try:return recipes.recipe(key,width=width,height=height,fps=fps)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.post('/validate',response_model=AnimationValidation)
async def validate(body:AnimationComposition):return render.validation(body)
@router.post('/render',response_model=Job)
async def export(body:AnimationRenderRequest):
    try:return await asyncio.to_thread(render.submit,body)
    except (ValueError,render.media.MediaError) as exc:raise HTTPException(400,str(exc)) from exc
