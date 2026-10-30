"""Explicit, bounded function-call checks. No model inference runs during inventory reads."""
from __future__ import annotations
import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .. import db, settings
from ..agent.types import Message, StepEnd, ToolOutcome, ToolSpec
from .tools import obj, S

SPECS = [ToolSpec('check_model_tools', 'Verify a configured model makes a real structured function call and consumes its result. Runs two bounded inference requests; no account actions. This checks basic protocol support, not general task competence.',
                 obj({'model': S}, ['model']), needs_approval=True)]
_locks = {}


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_model_checks (model TEXT NOT NULL, endpoint TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(model,endpoint))')


def endpoint(model):
    s = settings.load()
    provider = model.partition(':')[0]
    if provider == 'openai':
        value = s.openai_base_url
    elif provider == 'ollama':
        from .. import config
        value = config.OLLAMA_URL
    else:
        installed = db.get_installed(model.partition(':')[2])
        value = str(installed.path) + ':' + installed.installed_at if installed else provider
        if installed:
            try:
                stat=Path(installed.path).stat()
                value+=':'+str(stat.st_size)+':'+str(stat.st_mtime_ns)
            except OSError:
                value+=':missing'
    return hashlib.sha256(str(value).encode()).hexdigest()


def get(model):
    row = db.query_one('SELECT data FROM agent_model_checks WHERE model=? AND endpoint=?', (model, endpoint(model)))
    if not row: return None
    value=json.loads(row['data'])
    try:
        checked=datetime.fromisoformat(value['checked_at'].replace('Z','+00:00'))
        expired=checked < datetime.now(timezone.utc)-timedelta(days=7)
    except (ValueError,KeyError,TypeError): expired=True
    if expired: value={**value,'tools':False,'stale':True}
    return value


async def check(model):
    from ..agent.providers import get_provider
    if model.startswith('openrouter:'):
        raise ValueError('Use a local or explicitly configured compatible endpoint for the protocol check; remote spending is not authorized by this tool')
    async with _locks.setdefault(model, asyncio.Lock()):
        provider = get_provider(model)
        marker = uuid.uuid4().hex
        spec = ToolSpec('protocol_probe', 'Return the exact marker supplied by the user.', obj({'marker': S}, ['marker']))
        evidence = {'model': model, 'tools': False, 'checked_at': db.now_iso(), 'checks': [], 'scope': 'basic structured call and result consumption'}
        try:
            async with asyncio.timeout(180):
                history = [Message('user', f'Call protocol_probe with marker {marker}. Do not invent its result.')]
                end = None
                async for event in provider.stream('You are checking tool protocol compatibility. Follow the exact requested call.', history, [spec]):
                    if isinstance(event, StepEnd): end = event
                valid = end is not None and len(end.calls) == 1 and end.calls[0].name == spec.name and end.calls[0].args == {'marker': marker}
                evidence['checks'].append({'name': 'structured_call', 'passed': valid})
                if valid:
                    result = 'verified-' + uuid.uuid4().hex
                    call = end.calls[0]
                    history += [Message('assistant', end.text, calls=end.calls, raw=end.raw),
                                Message('tool', result, call_id=call.id, name=spec.name),
                                Message('user', 'Reply with exactly the result returned by the tool and no other text.')]
                    consumed = None
                    async for event in provider.stream('Return the observed tool result exactly.', history, None):
                        if isinstance(event, StepEnd): consumed = event
                    valid = consumed is not None and not consumed.calls and consumed.text.strip() == result
                    evidence['checks'].append({'name':'result_consumption', 'passed':valid})
                    evidence['tools'] = valid
        except Exception as exc:
            evidence['error'] = str(exc)[:1000]
        db.execute('INSERT INTO agent_model_checks VALUES(?,?,?) ON CONFLICT(model,endpoint) DO UPDATE SET data=excluded.data', (model, endpoint(model), json.dumps(evidence)))
        from . import store
        store.notify('coverage')
        return evidence


async def invoke(a, ctx):
    evidence = await check(a['model'])
    return ToolOutcome(evidence['tools'], json.dumps(evidence))


IMPL = {'check_model_tools': invoke}
