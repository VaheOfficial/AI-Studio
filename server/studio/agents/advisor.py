"""Optional advisory reasoning; remote consultation obeys mission spending authorization."""
from __future__ import annotations
import json
from .. import db
from ..agent.providers import get_provider
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from ..agent_plus.provider import MissionProvider, local
from . import store

SPECS = [ToolSpec('consult_advisor', 'Consult the configured advisor model about an obstacle. It cannot execute tools. Local advisors need no remote budget; remote advisors require a mission budget.',
    {'type': 'object', 'properties': {'question': {'type': 'string'}, 'evidence': {'type': 'string'}}, 'required': ['question'], 'additionalProperties': False})]


async def consult(a, ctx):
    from ..agent_plus import store as missions
    model = store.identity(ctx.session_id).advisor_model
    if not model:
        raise ToolFailure('Choose an advisor in Agents settings')
    provider = get_provider(model)
    if not local(model):
        if not missions.owns_session(ctx.session_id):
            raise ToolFailure('Remote advice requires a mission with an authorized spending budget')
        provider = MissionProvider(provider, ctx.session_id, model_override=model)
    elif missions.owns_session(ctx.session_id):
        provider = MissionProvider(provider, ctx.session_id, model_override=model)
    text = await provider.complete('You advise an executing agent. Analyze supplied evidence, distinguish facts from hypotheses, '
        'and propose one concrete next action and a completion check. You cannot execute tools.',
        json.dumps({'question': a['question'], 'evidence': a.get('evidence', '')[:32000]}, ensure_ascii=False))
    return ToolOutcome(True, json.dumps({'model': model, 'advice': text}, ensure_ascii=False))


IMPL = {'consult_advisor': consult}
