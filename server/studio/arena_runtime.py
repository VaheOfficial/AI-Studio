"""Arena-only requests for verified llama.cpp capacity, with a one-slot fallback."""
from __future__ import annotations
import asyncio
import threading
from contextlib import suppress
from . import llamacpp, settings
from .models import models

class CapacityCancelled(Exception):pass

async def release(owners):
    from .agent import agent
    from . import db
    if any((db.get_session(t.session_id) and db.get_session(t.session_id).model.startswith('llamacpp:'))
           for t in agent.active_turns()):return
    await asyncio.to_thread(llamacpp.server.release_arena,owners)

def configure(model_id,slots,context,owner,cancel):
    """Called in a worker thread; a cancelled two-slot load must not trigger a fallback."""
    if cancel.is_set():raise CapacityCancelled()
    current=llamacpp.server.capacity()
    same=llamacpp.server.base_url(model_id) is not None
    if same and current and (current['slots']==slots or current['busy']):
        return current
    if current and current['busy']:
        raise ValueError('llama.cpp is serving another model in an active chat; wait for it to finish')
    if cancel.is_set():raise CapacityCancelled()
    models.load(model_id,parallel=slots,context_per_slot=context,owner=owner)
    if cancel.is_set():raise CapacityCancelled()
    capacity=llamacpp.server.capacity()
    if not capacity or capacity['slots']!=slots or capacity['context_per_slot']<2048:
        raise ValueError('llama.cpp did not report the requested generation capacity')
    return capacity

async def prepare(match,one=False):
    """Do not restart a busy chat, and never change the persistent ordinary-chat settings."""
    if match.left.model.startswith('llamacpp:') and match.right.model.startswith('llamacpp:') and match.left.model!=match.right.model:
        from .agent import agent
        from . import db
        if any(db.get_session(t.session_id).model.startswith('llamacpp:') for t in agent.active_turns() if db.get_session(t.session_id)):
            raise ValueError('Finish the active llama.cpp chat before switching between Arena models')
        return 1,None,'Different llama.cpp models use one loaded model at a time; requests run sequentially'
    if not (match.left.model.startswith('llamacpp:') and match.left.model==match.right.model):
        if match.inference=='one':return 1,None,'Arena requests run sequentially'
        return None,None,'Runtime manages concurrency'
    from .agent import agent
    from . import db
    model_id=match.left.model.partition(':')[2]
    desired=1 if one or match.inference=='one' else (2 if match.inference=='two' else (1 if match.mode=='argument' and match.pacing=='alternating' else 2))
    context=min(settings.load().llamacpp_ctx_size,8192 if match.mode=='argument' else 32768)
    # Existing user turns must finish before their model server can be restarted.
    busy=any((db.get_session(t.session_id) and db.get_session(t.session_id).model.startswith('llamacpp:'))
             for t in agent.active_turns())
    if busy:
        current=await asyncio.to_thread(llamacpp.server.capacity)
        if llamacpp.server.base_url(model_id) is None:
            raise ValueError('Another llama.cpp model is busy; finish or pause its chat first')
        if not current:raise ValueError('Could not verify the active llama.cpp server')
        used=min(desired,current['slots'])
        if match.inference=='auto' and current.get('gpu_offload_complete') is False:used=1
        if match.inference=='two' and used<2:raise ValueError('Two slots require reloading the model; finish the active chat first')
        return used,current['context_per_slot'],f'Using {used} slot(s) without interrupting the active chat'
    cancel=threading.Event()
    async def load(slots):
        task=asyncio.create_task(asyncio.to_thread(configure,model_id,slots,context,match.id,cancel))
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set();await asyncio.to_thread(llamacpp.server.cancel_load,match.id)
            with suppress(Exception):await task
            if llamacpp.server.base_url(model_id) is None:models.set_status(model_id,'ready')
            raise
    try:
        result=await load(desired)
        if desired==2 and match.inference=='auto' and result.get('gpu_offload_complete') is False:
            raise ValueError('Two-slot loading moved model layers to CPU instead of fitting fully on GPU')
        if result['slots']<desired and match.inference=='two':raise ValueError('The active server has only one slot')
        actual=min(desired,result['slots'])
        note=f'{actual} generation slot(s), shared model weights'
        if actual==2 and result.get('gpu_offload_complete') is False:note+='; some model layers run on CPU'
        if actual<desired:note='One slot: existing requests are active; Arena replies queue'
        return actual,result['context_per_slot'],note
    except asyncio.CancelledError:raise
    except Exception as exc:
        if desired!=2 or match.inference=='two':raise
        result=await load(1)
        return 1,result['context_per_slot'],'Two-slot startup failed; using one slot. '+str(exc)[:300]
