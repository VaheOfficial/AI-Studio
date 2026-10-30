"""Bounded, explicitly scoped subagents attached to their parent conversation."""
from __future__ import annotations
import json
from typing import Any
from .. import db
from ..agent import profiles
from ..agent.providers.base import Provider
from ..agent.types import Message, ProviderError, StepEnd
from ..schemas_agents import AgentDelegation, DelegateCreate
from ..workspace.tasks import tasks
from . import store

READ_TOOLS = {'system_info', 'list_models', 'search_catalog', 'list_dir', 'read_file', 'find_files', 'browser_navigate',
              'search_files', 'fetch_url', 'browser_read', 'browser_screenshot', 'view_image',
              'read_skill', 'knowledge_search', 'skill_read', 'calculate', 'convert', 'world_time',
              'search_tools', 'load_tools', 'search_documents', 'research_search', 'read_social_thread', 'inspect_media', 'office_file_help', 'plugin_list', 'plugin_read_file'}
FORBIDDEN = {'start_mission', 'delegate_task', 'followup_delegation', 'start_task', 'wake_schedule', 'execute_tools', 'run_tool_script', 'consult_advisor', 'check_model_tools','watch_source','pause_source_watch'}


def init() -> None:
    db.execute('CREATE TABLE IF NOT EXISTS agent_delegations (session_id TEXT PRIMARY KEY, parent_session_id TEXT NOT NULL, data TEXT NOT NULL)')
    if profile not in profiles._resolvers:
        profiles.register(profile, [], {})


def get(sid: str) -> AgentDelegation | None:
    row = db.query_one('SELECT data FROM agent_delegations WHERE session_id = ?', (sid,))
    if not row:
        return None
    value = AgentDelegation.model_validate_json(row['data'])
    try:
        task = tasks.get(value.task_id)
        value.status, value.result, value.error = task.status, task.result, task.error
    except Exception:
        value.status = 'unavailable'
    return value


def list_all(parent: str | None = None) -> list[AgentDelegation]:
    rows = db.query('SELECT session_id FROM agent_delegations WHERE (? IS NULL OR parent_session_id = ?) ORDER BY rowid DESC LIMIT 200', (parent, parent))
    return [v for r in rows if (v := get(r['session_id']))]


def create(parent: str, body: DelegateCreate) -> AgentDelegation:
    from .registry import catalog
    if get(parent):
        raise ValueError('Subagents cannot delegate further work')
    identity = store.identity(parent)
    if not identity.allow_subagents:
        raise ValueError('Subagents are disabled for this agent')
    active = [v for v in list_all(parent) if v.status in ('queued', 'running', 'waiting_approval')]
    if len(active) >= identity.max_subagents:
        raise ValueError('This agent has reached its active subagent limit')
    specs = {s.name for s in catalog(parent)}
    allowed = body.allowed_tools or sorted(READ_TOOLS & specs)
    if any(n not in specs or n in FORBIDDEN or n.startswith('automation_') for n in allowed):
        raise ValueError('A requested tool is unavailable or cannot be delegated')
    instructions = ('Delegated task. Complete only this objective; report evidence, limitations and output paths. '
                    'Do not claim verification you did not perform.\n\n' + body.objective)
    if body.model:
        from ..agent.providers import get_provider
        get_provider(body.model)
    task = tasks.create(parent, instructions, body.title)
    if body.model:
        db.execute('UPDATE sessions SET model=? WHERE id=?', (body.model, task.session_id))
    value = AgentDelegation(id=task.id, parent_session_id=parent, session_id=task.session_id,
        task_id=task.id, objective=body.objective, allowed_tools=allowed, max_requests=body.max_requests,
        status=task.status, created_at=task.created_at)
    db.execute('INSERT INTO agent_delegations VALUES(?,?,?)', (value.session_id, parent, value.model_dump_json()))
    store.bind(value.session_id, identity.id)
    store.notify('delegations', parent)
    return value


def followup(parent, did, body):
    from ..agent import agent
    from ..agent_plus.store import atomic
    with atomic():
        value = next((v for v in list_all(parent) if v.id == did), None)
        if not value:
            raise ValueError('Subagent not owned by this conversation')
        if agent.busy(value.session_id) or value.status in ('queued', 'running', 'waiting_approval'):
            raise ValueError('Wait for or cancel the current child turn before continuing it')
        if value.max_requests + body.additional_requests > 100:
            raise ValueError('A child can receive at most 100 total requests')
        value.max_requests += body.additional_requests
        db.execute('UPDATE agent_delegations SET data=? WHERE session_id=?', (value.model_dump_json(), value.session_id))
        # Retry retains the existing child conversation and its original tool scope.
        db.execute("UPDATE workspace_tasks SET prompt=?,status='queued',result=NULL,error=NULL WHERE id=?", (body.message, value.task_id))
    tasks._update(value.task_id, finished_at=None)
    tasks._queue.put_nowait(value.task_id)
    store.notify('delegations', parent)
    return get(value.session_id)


class DelegatedProvider(Provider):
    def __init__(self, inner: Provider, sid: str, parent: str):
        from ..agent_plus import store as missions
        from ..agent_plus.provider import MissionProvider
        self.inner = MissionProvider(inner, parent, model_override=db.get_session(sid).model) if missions.owns_session(parent) else inner
        self.sid = sid

    async def info(self):
        self.inner.context_limit = self.context_limit
        return await self.inner.info()

    async def stream(self, system, history, tools):
        value = get(self.sid)
        if not value or value.requests >= value.max_requests:
            raise ProviderError('Subagent request limit reached')
        value.requests += 1
        db.execute('UPDATE agent_delegations SET data = ? WHERE session_id = ?', (value.model_dump_json(), self.sid))
        self.inner.context_limit = self.context_limit
        async for ev in self.inner.stream(system, history, tools):
            yield ev


    async def complete(self, system: str, prompt: str) -> str:
        text = ""
        async for ev in self.stream(system, [Message("user", prompt)], None):
            if isinstance(ev, StepEnd):
                text = ev.text
        return text


def profile(sid: str) -> profiles.Profile | None:
    value = get(sid)
    if not value:
        return None
    allowed = set(value.allowed_tools)
    def build(info):
        from ..agent.prompt import build as base
        return base('agent', sid, info, db.get_session(sid).model) + '\nYou are a bounded subagent. Your only objective is:\n' + value.objective
    return profiles.Profile(build, lambda specs: [s for s in specs if s.name in allowed],
        lambda name, args, gated: None if name in allowed else 'Outside delegated tool scope',
        preserve_approvals=True, provider=lambda p: DelegatedProvider(p, sid, value.parent_session_id))
