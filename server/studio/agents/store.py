"""Persistent identities, scoped knowledge, reusable skills and versioned artifacts."""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Any
from .. import db
from ..events import bus
from ..schemas_agents import (AgentArtifact, AgentIdentity, AgentKnowledge, AgentSkill, ArtifactCreate,
                             EvAgentsUpdate, IdentityPatch, KnowledgeCreate, SkillCreate)


def atomic_write(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        from ..agent_plus.store import atomic
        with atomic():
            return fn(*args, **kwargs)
    return wrapped


def notify(area: str, sid: str | None = None) -> None:
    bus.publish(EvAgentsUpdate(area=area, session_id=sid))


def init() -> None:
    for sql in (
        'CREATE TABLE IF NOT EXISTS agent_identities (id TEXT PRIMARY KEY, data TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS agent_bindings (session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS agent_knowledge (id TEXT PRIMARY KEY, scope TEXT NOT NULL, scope_id TEXT NOT NULL, data TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS agent_skills (id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, UNIQUE(name, version))',
        'CREATE TABLE IF NOT EXISTS agent_artifacts (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, data TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS agent_artifact_versions (id TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(id, version))',
        'CREATE TABLE IF NOT EXISTS agent_tool_loads (session_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY(session_id, name))',
        'CREATE TABLE IF NOT EXISTS agent_app_context (session_id TEXT NOT NULL, connector_id TEXT NOT NULL, content TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(session_id,connector_id))',
        'CREATE TABLE IF NOT EXISTS agent_legacy_imports (swarm_id TEXT PRIMARY KEY, session_id TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS agent_knowledge_vectors (id TEXT NOT NULL, model TEXT NOT NULL, source_hash TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(id,model))',
    ):
        db.execute(sql)
    if 'loaded_at' not in {row['name'] for row in db.query('PRAGMA table_info(agent_tool_loads)')}:
        db.execute("ALTER TABLE agent_tool_loads ADD COLUMN loaded_at TEXT NOT NULL DEFAULT ''")
    if not db.query_one('SELECT id FROM agent_identities WHERE id = ?', ('main',)):
        now = db.now_iso()
        save_identity(AgentIdentity(id='main', name='Agent', created_at=now, updated_at=now))


def identities() -> list[AgentIdentity]:
    return [AgentIdentity.model_validate_json(r['data']) for r in db.query('SELECT data FROM agent_identities ORDER BY id')]


def identity(sid: str | None = None, *, agent_id: str | None = None) -> AgentIdentity:
    binding = db.query_one('SELECT agent_id FROM agent_bindings WHERE session_id = ?', (sid,)) if sid else None
    aid = agent_id or (binding['agent_id'] if binding else 'main')
    row = db.query_one('SELECT data FROM agent_identities WHERE id = ?', (aid,))
    if not row:
        raise ValueError('Agent identity not found')
    return AgentIdentity.model_validate_json(row['data'])


def save_identity(value: AgentIdentity) -> AgentIdentity:
    value.updated_at = db.now_iso()
    db.execute('INSERT INTO agent_identities VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
               (value.id, value.model_dump_json()))
    notify('identities')
    return value


def patch_identity(aid: str, body: IdentityPatch) -> AgentIdentity:
    data = identity(agent_id=aid).model_dump()
    data.update(body.model_dump(exclude_unset=True))
    return save_identity(AgentIdentity.model_validate(data))


def bind(sid: str, aid: str) -> None:
    identity(agent_id=aid)
    if not db.get_session(sid):
        raise ValueError('Conversation not found')
    db.execute('INSERT INTO agent_bindings VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET agent_id=excluded.agent_id', (sid, aid))
    notify('identities', sid)


def knowledge(scope: str | None = None, scope_id: str | None = None) -> list[AgentKnowledge]:
    rows = db.query('SELECT data FROM agent_knowledge ORDER BY rowid DESC LIMIT 2000')
    values = [AgentKnowledge.model_validate_json(r['data']) for r in rows]
    return [v for v in values if (scope is None or v.scope == scope) and (scope_id is None or v.scope_id == scope_id)
            and (not v.expires_at or v.expires_at > db.now_iso())]


def add_knowledge(body: KnowledgeCreate) -> AgentKnowledge:
    if body.expires_at:
        dt = datetime.fromisoformat(body.expires_at.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('Expiry must include a timezone')
        body.expires_at = dt.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    now = db.now_iso()
    value = AgentKnowledge(id=uuid.uuid4().hex[:16], created_at=now, updated_at=now, **body.model_dump())
    db.execute('INSERT INTO agent_knowledge VALUES(?,?,?,?)', (value.id, value.scope, value.scope_id, value.model_dump_json()))
    notify('knowledge')
    return value


@atomic_write
def update_knowledge(kid: str, body, expected: str) -> AgentKnowledge:
    row = db.query_one('SELECT data FROM agent_knowledge WHERE id=?', (kid,))
    if not row:
        raise ValueError('Knowledge not found')
    old = AgentKnowledge.model_validate_json(row['data'])
    if old.updated_at != expected:
        raise ValueError('Memory changed; refresh before editing')
    if body.expires_at:
        dt = datetime.fromisoformat(body.expires_at.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('Expiry must include a timezone')
        body.expires_at = dt.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    now = max(datetime.now(timezone.utc), datetime.fromisoformat(old.updated_at.replace('Z', '+00:00')) + timedelta(milliseconds=1))
    value = AgentKnowledge(id=kid, created_at=old.created_at, updated_at=now.isoformat(timespec='milliseconds').replace('+00:00', 'Z'), **body.model_dump())
    db.execute('UPDATE agent_knowledge SET scope=?,scope_id=?,data=? WHERE id=?',
               (value.scope, value.scope_id, value.model_dump_json(), kid))
    db.execute('DELETE FROM agent_knowledge_vectors WHERE id=?',(kid,))
    notify('knowledge')
    return value


def scoped_knowledge(sid):
    from ..workspace import state
    aid, root = identity(sid).id, state.get(sid).root
    return [v for v in knowledge() if (v.scope == 'agent' and v.scope_id == aid)
            or (v.scope == 'chat' and v.scope_id == sid) or (v.scope == 'workspace' and v.scope_id == root)]


def retrieve(sid: str, query: str, limit: int = 8) -> list[AgentKnowledge]:
    terms = set(re.findall(r'[\w-]{2,}', query.lower()))
    eligible = scoped_knowledge(sid)
    def score(v: AgentKnowledge) -> tuple[int, str]:
        return len(terms & set(re.findall(r'[\w-]{2,}', (v.text + ' ' + v.source).lower()))), v.updated_at
    return sorted((v for v in eligible if not terms or score(v)[0]), key=score, reverse=True)[:max(1, min(limit, 30))]


def semantic_knowledge(sid, query, model, limit=8):
    from . import collections
    import math
    eligible=scoped_knowledge(sid)
    # Explicitly bound one semantic query instead of silently embedding an unlimited memory archive.
    if len(eligible)>500: raise ValueError('Semantic memory query supports at most 500 scoped facts')
    vectors=[];missing=[]
    for item in eligible:
        digest=hashlib.sha256((item.text+'\n'+item.source).encode()).hexdigest()
        cached=db.query_one('SELECT data,source_hash FROM agent_knowledge_vectors WHERE id=? AND model=?',(item.id,model))
        if cached and cached['source_hash']==digest: vectors.append((item,json.loads(cached['data'])))
        else: missing.append((item,digest))
    if sum(len(item.text)+len(item.source) for item,_ in missing)>512000: raise ValueError('Memory embedding input exceeds 512,000 characters')
    if missing:
        generated=collections.embed(model,[item.text+'\n'+item.source for item,_ in missing])
        for (item,digest),vector in zip(missing,generated):
            db.execute('INSERT INTO agent_knowledge_vectors VALUES(?,?,?,?) ON CONFLICT(id,model) DO UPDATE SET source_hash=excluded.source_hash,data=excluded.data', (item.id,model,digest,json.dumps(vector)))
            vectors.append((item,vector))
    query_vector=collections.embed(model,[query])[0]
    def score(pair):
        vector=pair[1]
        if len(vector)!=len(query_vector): raise ValueError('Embedding dimensions changed; rebuild the memory projection')
        norm=math.sqrt(sum(v*v for v in vector)*sum(v*v for v in query_vector))
        return sum(a*b for a,b in zip(vector,query_vector))/norm if norm else 0
    return [item for item,_ in sorted(vectors,key=score,reverse=True)[:max(1,min(limit,30))]]


def skills() -> list[AgentSkill]:
    rows = db.query('SELECT data FROM agent_skills ORDER BY name, version DESC')
    return [AgentSkill.model_validate_json(r['data']) for r in rows]


@atomic_write
def add_skill(body: SkillCreate) -> AgentSkill:
    validate_dependencies(body.name, body.dependencies)
    capability = None
    if body.capability_id:
        from ..agent_plus import store as missions
        if not body.source_session_id:
            raise ValueError('A promoted capability needs its source conversation')
        capability = missions.capability(body.source_session_id, body.capability_id)
        if capability.status != 'validated':
            raise ValueError('Only validated capabilities can be promoted')
        if 'run_python' not in body.permissions:
            raise ValueError('Executable skills must declare run_python permission')
    latest = db.query_one('SELECT MAX(version) AS version FROM agent_skills WHERE name = ?', (body.name,))
    value = AgentSkill(id=uuid.uuid4().hex[:16], version=(latest['version'] or 0) + 1,
        code_hash=capability.code_hash if capability else None, created_at=db.now_iso(), **body.model_dump())
    db.execute('INSERT INTO agent_skills VALUES(?,?,?,?)', (value.id, value.name, value.version, value.model_dump_json()))
    notify('skills')
    return value


def validate_dependencies(name: str, dependencies: list[str]) -> None:
    visited = set()
    def visit(key: str, path: set[str]) -> None:
        value = skill(key)
        if value.name == name or value.name in path:
            raise ValueError('Skill dependency cycle: ' + value.name)
        if not value.enabled:
            raise ValueError('Disabled dependency: ' + value.name)
        if value.id in visited:
            return
        visited.add(value.id)
        for nested in value.dependencies:
            visit(nested, path | {value.name})
    for dependency in dependencies:
        if dependency == name:
            raise ValueError('A skill cannot depend on itself')
        visit(dependency, {name})


def skill(key: str) -> AgentSkill:
    row = db.query_one('SELECT data FROM agent_skills WHERE id = ? OR name = ? ORDER BY version DESC LIMIT 1', (key, key))
    if not row:
        raise ValueError('Skill not found')
    return AgentSkill.model_validate_json(row['data'])


def artifacts(sid: str | None = None) -> list[AgentArtifact]:
    rows = db.query('SELECT data FROM agent_artifacts WHERE (? IS NULL OR session_id = ?) ORDER BY rowid DESC LIMIT 200', (sid, sid))
    return [AgentArtifact.model_validate_json(r['data']) for r in rows]


def artifact(aid: str, version: int | None = None) -> AgentArtifact:
    row = (db.query_one('SELECT data FROM agent_artifacts WHERE id = ?', (aid,)) if version is None else
           db.query_one('SELECT data FROM agent_artifact_versions WHERE id = ? AND version = ?', (aid, version)))
    if not row:
        raise ValueError('Artifact not found')
    return AgentArtifact.model_validate_json(row['data'])


def artifact_history(aid: str):
    artifact(aid)
    from ..schemas_agents import ArtifactRevision
    return [ArtifactRevision(version=value.version, content_hash=value.content_hash, updated_at=value.updated_at)
            for row in db.query('SELECT data FROM agent_artifact_versions WHERE id=? ORDER BY version DESC', (aid,))
            if (value := AgentArtifact.model_validate_json(row['data']))]


def validate_artifact(sid, body):
    if not db.get_session(sid):
        raise ValueError('Conversation not found')
    if (body.id is None) != (body.version is None):
        raise ValueError('Creating an artifact: omit BOTH id and version. Revising: use the actual returned id AND current version.')
    old = artifact(body.id) if body.id else None
    if old and (old.session_id != sid or old.version != body.version):
        raise ValueError('Artifact changed or belongs to another conversation; refresh before editing')
    if body.kind == 'json':
        json.loads(body.content)
    return old


@atomic_write
def save_artifact(sid: str, body: ArtifactCreate) -> AgentArtifact:
    old = validate_artifact(sid,body)
    now = db.now_iso()
    value = AgentArtifact(id=old.id if old else uuid.uuid4().hex[:16], session_id=sid,
        title=body.title, kind=body.kind, version=old.version + 1 if old else 1, content=body.content,
        content_hash=hashlib.sha256(body.content.encode()).hexdigest(), created_at=old.created_at if old else now, updated_at=now)
    db.execute('INSERT INTO agent_artifact_versions VALUES(?,?,?)', (value.id, value.version, value.model_dump_json()))
    db.execute('INSERT INTO agent_artifacts VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
               (value.id, sid, value.model_dump_json()))
    notify('artifacts', sid)
    if old and old.content_hash != value.content_hash:
        invalidate_artifact_evidence(value)
    return value


def invalidate_artifact_evidence(value: AgentArtifact) -> None:
    from ..agent_plus import store as missions
    sid = value.session_id
    if not missions.owns_session(sid):
        return
    affected = set()
    for receipt in missions.actions(sid):
        if receipt.name not in ('artifact_save', 'artifact_read') or not receipt.output:
            continue
        try:
            packet = json.loads(receipt.output)
        except ValueError:
            continue
        if isinstance(packet, dict) and packet.get('id') == value.id and packet.get('content_hash') != value.content_hash:
            affected.add(receipt.id)
    if not affected:
        return
    mission = missions.get(sid)
    items = missions.work(sid)
    invalid = {w.id for w in items if affected.intersection(w.evidence)}
    while True:
        children = {w.id for w in items if invalid.intersection(w.dependencies)} - invalid
        if not children:
            break
        invalid |= children
    affected |= {aid for w in items if w.id in invalid for aid in w.evidence}
    for criterion in mission.criteria:
        if affected.intersection(criterion.evidence):
            criterion.evidence = []
    for item in items:
        if item.id in invalid and item.status != 'superseded':
            item.status, item.evidence = 'pending', []
    if mission.status == 'completed':
        mission.status, mission.reason = 'paused', 'Artifact edited; verify the current revision before completing again'
    missions.save_work(sid, [w for w in items if w.id in invalid])
    missions.save(mission)
    missions.event(sid, 'artifact.changed', 'Earlier artifact evidence invalidated by a new revision.', {'artifact_id': value.id, 'version': value.version})


def application_context(sid):
    return [{"connector_id":row["connector_id"],"content":row["content"],"updated_at":row["updated_at"]} for row in db.query("SELECT * FROM agent_app_context WHERE session_id=? ORDER BY updated_at DESC LIMIT 5", (sid,))]
