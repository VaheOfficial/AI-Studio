"""Discovery, composition, delegation, knowledge, reusable skills and artifacts."""
from __future__ import annotations
import asyncio
import json
from typing import Any
from ..agent.types import ToolContext, ToolFailure, ToolOutcome, ToolSpec
from ..schemas_agents import ArtifactCreate, DelegateCreate, DelegationFollowup, KnowledgeCreate, WakeCreate
from . import delegation, registry, store

S = {'type': 'string'}
O = {'type': 'object'}
def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}

SPECS = [
    ToolSpec('start_mission', 'Use the persistent mission engine for multi-step work, missing-tool construction or completion evidence. Keeps this conversation; starts with a local-only budget and 80 requests. Budget changes belong to the user.', obj({'objective': S, 'criteria': {'type': 'array', 'items': S, 'maxItems': 30}}, ['objective'])),
    ToolSpec('search_tools', 'Search available capabilities by task. Returns compact descriptions; use load_tools for schemas.', obj({'query': S, 'limit': {'type': 'integer'}, 'mode':{'type':'string','enum':['bm25','regex']}}, ['query'])),
    ToolSpec('load_tools', 'Load schemas for discovered tools into this conversation. Tools remain subject to permissions.', obj({'names': {'type': 'array', 'items': S, 'maxItems': 30}}, ['names'])),
    ToolSpec('execute_tools', 'Compose up to 20 sequential tool calls through normal approvals. Bind arguments with {"$result":"step-id#/json/pointer"}; return_fields filters results. No new reasoning agents are spawned.', obj({'steps': {'type': 'array', 'maxItems': 20, 'items': obj({'id': S, 'name': S, 'args': O, 'return_fields': {'type': 'array', 'items': S}}, ['id', 'name', 'args'])}}, ['steps'])),
    ToolSpec('delegate_task', 'Create a bounded subagent for a self-contained objective. Default tools are read-only; explicit allowed_tools restrict its authority. Optional model selects a configured provider; mission spending limits still apply. The parent remains sequential.', obj({'objective': S, 'title': S, 'allowed_tools': {'type': 'array', 'items': S}, 'max_requests': {'type': 'integer'}, 'model': S}, ['objective']), asks_like=lambda a: 'delegate_task' if set(a.get('allowed_tools', [])) - delegation.READ_TOOLS else None),    ToolSpec('followup_delegation', 'Continue an idle owned subagent in its existing conversation and original tool scope. Does not change its model or approval boundaries.', obj({'id': S, 'message': S, 'additional_requests': {'type':'integer','minimum':1,'maximum':100}}, ['id','message'])),
    ToolSpec('delegation_status', 'Inspect delegated tasks and their evidence/results. Optional wait_seconds waits up to 30 seconds.', obj({'wait_seconds': {'type': 'integer'}})),
    ToolSpec('cancel_delegation', 'Cancel a subagent owned by this conversation.', obj({'id': S}, ['id'])),
    ToolSpec('knowledge_search', 'Retrieve relevant scoped knowledge with provenance. Semantic mode requires an explicit installed local Ollama embedding model; source changes invalidate cached vectors.', obj({'query': S, 'limit': {'type': 'integer'}, 'mode':{'type':'string','enum':['lexical','semantic']},'embedding_model':S}, ['query'])),
    ToolSpec('knowledge_save', 'Store factual knowledge with scope, source and optional expiry. Never store passwords or tokens.', obj({'text': S, 'scope': {'type': 'string', 'enum': ['agent', 'workspace', 'chat']}, 'source': S, 'expires_at': S}, ['text'])),
    ToolSpec('skill_read', 'Read a versioned reusable skill and its dependency/permission contract. Without name, lists enabled skills.', obj({'name': S})),
    ToolSpec('invoke_skill', 'Invoke a reviewed promoted capability. Its original validation hash and input/output schemas are enforced.', obj({'name': S, 'args': O}, ['name', 'args']), asks_like=lambda _: 'run_python'),
    ToolSpec('artifact_save', 'Create an artifact by supplying ONLY title, kind and content: OMIT id and version. The runtime returns its real id and version. To revise an existing artifact, additionally supply its OBSERVED id and current version. NEVER invent an id. JSON content must be valid JSON.', obj({'title': S, 'kind': {'type': 'string', 'enum': ['markdown', 'html', 'json', 'text']}, 'content': S, 'id': S, 'version': {'type': 'integer','minimum':1}}, ['title', 'kind', 'content'])),
    ToolSpec('artifact_read', 'Read an artifact owned by this conversation, optionally an earlier version; no id lists artifacts.', obj({'id': S, 'version': {'type': 'integer'}})),
    ToolSpec('notify_user', 'Record a useful update in the owner inbox. Desktop and browser delivery follow the user’s notification settings. Do not include credentials.', obj({'title':S,'body':S}, ['title','body'])),
    ToolSpec('wake_schedule', 'Arrange a timezone-aware future wake or an event-triggered continuation. pause_now suspends this mission until that wake. User pause cancels pending wakes.', obj({'prompt': S, 'wake_at': S, 'topic': S, 'pause_now': {'type': 'boolean'}}, ['prompt']), needs_approval=True),
]


def result(value: Any) -> ToolOutcome:
    return ToolOutcome(True, json.dumps(value, ensure_ascii=False, default=lambda v: v.model_dump()))


async def start_mission(a, ctx):
    from .. import db
    from ..agent_plus import store as missions
    from ..schemas_agent_plus import AgentPlusMission
    if delegation.get(ctx.session_id):
        raise ToolFailure('Subagents cannot create owner missions')
    if missions.owns_session(ctx.session_id):
        return result(missions.get(ctx.session_id))
    if not a['objective'].strip():
        raise ToolFailure('Mission objective is required')
    checks = missions.criteria(a.get('criteria') or [a['objective']])
    messages = db.list_messages(ctx.session_id)
    original = next((m.content for m in reversed(messages) if m.role == 'user'), a['objective'])
    now = db.now_iso()
    with missions.atomic():
        missions.save(AgentPlusMission(session_id=ctx.session_id, original_request=original,
            objective=a['objective'], criteria=checks, status='running', max_requests=80, max_cost=0, created_at=now, updated_at=now))
        missions.event(ctx.session_id, 'created', 'Persistent mission enabled in this conversation.')
    store.notify('missions', ctx.session_id)
    return result(missions.get(ctx.session_id))


async def wake_schedule(a, ctx):
    from . import wakes
    value = wakes.create(ctx.session_id, WakeCreate(prompt=a['prompt'], wake_at=a.get('wake_at'), topic=a.get('topic')))
    if a.get('pause_now'):
        from ..agent_plus import store as missions
        if missions.owns_session(ctx.session_id):
            mission = missions.get(ctx.session_id)
            mission.status, mission.reason = 'paused', 'Waiting for scheduled wake: ' + value.id
            missions.save(mission)
    return result(value)


def resolve(value: Any, outputs: dict[str, Any]) -> Any:
    if isinstance(value, dict) and set(value) == {'$result'}:
        name, _, pointer = str(value['$result']).partition('#')
        if name not in outputs:
            raise ToolFailure('Result binding refers to an unavailable step: ' + name)
        current = outputs[name]
        for part in pointer.lstrip('/').split('/') if pointer else []:
            key = part.replace('~1', '/').replace('~0', '~')
            current = current[int(key)] if isinstance(current, list) else current[key]
        return current
    if isinstance(value, dict):
        return {k: resolve(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, outputs) for v in value]
    return value


async def search(a, ctx):
    return result(registry.search(registry.catalog(ctx.session_id), a['query'], max(1,min(a.get('limit',12),100)), mode=a.get('mode','bm25')))



async def load(a, ctx):
    return result(registry.load(ctx.session_id, a['names'], registry.catalog(ctx.session_id)))


async def compose(a, ctx):
    if not ctx.invoke:
        raise ToolFailure('Composition requires an active agent turn')
    steps = a['steps']
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise ToolFailure('Provide 1 to 20 steps')
    allowed = {s.name for s in registry.catalog(ctx.session_id)}
    seen: set[str] = set()
    for step in steps:
        if step['id'] in seen or step['name'] not in allowed or step['name'] in {'execute_tools', 'run_tool_script'}:
            raise ToolFailure('Duplicate step id or unavailable/nested composition tool')
        seen.add(step['id'])
    outputs, visible = {}, []
    for step in steps:
        try:
            arguments = resolve(step['args'], outputs)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ToolFailure('Invalid result binding in step: ' + step['id']) from exc
        outcome = await ctx.invoke(step['name'], arguments)
        try:
            payload = json.loads(outcome.output)
        except ValueError:
            payload = outcome.output
        outputs[step['id']] = payload
        fields = step.get('return_fields')
        filtered = {k: payload.get(k) for k in fields} if fields and isinstance(payload, dict) else payload
        visible.append({'id': step['id'], 'ok': outcome.ok, 'result': filtered})
        if not outcome.ok:
            return ToolOutcome(False, json.dumps({'steps': visible, 'stopped_at': step['id']}, ensure_ascii=False))
    return result({'steps': visible})


async def delegate(a, ctx):
    return result(delegation.create(ctx.session_id, DelegateCreate.model_validate(a)))


async def status(a, ctx):
    wait = max(0, min(int(a.get('wait_seconds', 0)), 30))
    if wait:
        await asyncio.sleep(wait)
    return result(delegation.list_all(ctx.session_id))


async def cancel(a, ctx):
    from ..workspace.tasks import tasks
    value = next((v for v in delegation.list_all(ctx.session_id) if v.id == a['id']), None)
    if not value:
        raise ToolFailure('Subagent is not owned by this conversation')
    return result(await tasks.cancel(value.task_id))


async def knowledge_search(a, ctx):
    if a.get('mode') == 'semantic':        if not a.get('embedding_model'): raise ToolFailure('Semantic memory needs an explicit local embedding_model')        return result(await asyncio.to_thread(store.semantic_knowledge,ctx.session_id,a['query'],a['embedding_model'],a.get('limit',8)))    return result(store.retrieve(ctx.session_id, a['query'], a.get('limit', 8)))


async def knowledge_save(a, ctx):
    from ..workspace import state
    scope = a.get('scope', 'agent')
    sid = ctx.session_id if scope == 'chat' else (str(state.require_root(ctx.session_id)) if scope == 'workspace' else store.identity(ctx.session_id).id)
    return result(store.add_knowledge(KnowledgeCreate(scope=scope, scope_id=sid, text=a['text'], source=a.get('source', ''), expires_at=a.get('expires_at'))))


async def skill_read(a, ctx):
    if a.get('name'):
        return result(store.skill(a['name']))
    return result([{'name': v.name, 'version': v.version, 'description': v.description} for v in store.skills() if v.enabled])


async def invoke_skill(a, ctx):
    from ..agent_plus import runner, store as missions
    skill = store.skill(a['name'])
    if not skill.enabled or not skill.capability_id or not skill.source_session_id:
        raise ToolFailure('This skill has no enabled executable capability')
    for dependency in skill.dependencies:
        if not store.skill(dependency).enabled:
            raise ToolFailure('Disabled dependency: ' + dependency)
    capability = missions.capability(skill.source_session_id, skill.capability_id)
    if capability.status != 'validated' or capability.code_hash != skill.code_hash or store_hash(capability.code) != skill.code_hash:
        raise ToolFailure('Promoted capability changed; review a new version')
    runner.check_schema(a['args'], capability.input_schema)
    output = await runner.invoke(capability.code, a['args'], ctx.session_id)
    if output.get('ok'):
        runner.check_schema(output['value'], capability.output_schema)
    return ToolOutcome(bool(output.get('ok')), json.dumps(output, ensure_ascii=False))


def store_hash(code: str) -> str:
    import hashlib
    return hashlib.sha256(code.encode()).hexdigest()


async def artifact_save(a, ctx):
    return result(store.save_artifact(ctx.session_id, ArtifactCreate.model_validate(a)))


async def artifact_read(a, ctx):
    if not a.get('id'):
        return result([{'id': v.id, 'title': v.title, 'kind': v.kind, 'version': v.version} for v in store.artifacts(ctx.session_id)])
    value = store.artifact(a['id'], a.get('version'))
    if value.session_id != ctx.session_id:
        raise ToolFailure('Artifact belongs to another conversation')
    return result(value)


async def notify_user(a, ctx):
    from . import notifications
    import uuid
    return result(notifications.save(ctx.session_id, 'notice', a['title'], a['body'], 'notice:' + uuid.uuid4().hex))


async def followup(a, ctx):    return result(delegation.followup(ctx.session_id, a['id'], DelegationFollowup(**{k:v for k,v in a.items() if k != 'id'})))IMPL = {'followup_delegation':followup, 'notify_user':notify_user, 'start_mission': start_mission, 'wake_schedule': wake_schedule, 'search_tools': search, 'load_tools': load, 'execute_tools': compose, 'delegate_task': delegate,
        'delegation_status': status, 'cancel_delegation': cancel, 'knowledge_search': knowledge_search,
        'knowledge_save': knowledge_save, 'skill_read': skill_read, 'invoke_skill': invoke_skill,
        'artifact_save': artifact_save, 'artifact_read': artifact_read}
