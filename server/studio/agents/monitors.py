"""Persistent read-only source watches. Changes create scoped, idempotent continuations."""
from __future__ import annotations
import asyncio
import hashlib
import json
import time
import uuid
from .. import db
from ..agent.types import ToolContext, ToolFailure, ToolOutcome, ToolSpec
from ..schemas_agents import SourceMonitorCreate, WakeCreate, KnowledgeCreate
from . import policies, services, store, wakes
from .tools import obj, S

READ = {'fetch_url', 'read_file', 'list_dir', 'find_files', 'search_files', 'search_documents', 'knowledge_search'}
SPECS = [ToolSpec('monitor_status', 'Inspect approved read-only source monitors and their last observation or error. No sources are polled by this call.', obj({})),
         ToolSpec('watch_source','Create an approved read-only source watch for this owner conversation. Changes wake the owner; unchanged observations stay quiet. User Stop disables watches. Optional source memory records observations, not inferred preferences.',
             obj({'name':S,'tool':S,'arguments':{'type':'object'},'select':S,'interval_seconds':{'type':'integer','minimum':30,'maximum':86400},'prompt':S,'notify_initial':{'type':'boolean'},'record_memory':{'type':'boolean'}},['name','tool','prompt']),needs_approval=True),
         ToolSpec('pause_source_watch','Pause one watch owned by this conversation. Resuming after user Stop requires the user to enable it in the UI.',obj({'id':S},['id']))]


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_monitors (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, data TEXT NOT NULL, observation TEXT, source_hash TEXT, next_at REAL NOT NULL, failures INTEGER NOT NULL DEFAULT 0, last_error TEXT, updated_at TEXT NOT NULL)')
    if 'memory_id' not in {row['name'] for row in db.query('PRAGMA table_info(agent_monitors)')}:
        db.execute('ALTER TABLE agent_monitors ADD COLUMN memory_id TEXT')


def readonly(name):
    if name in READ: return True
    if name.startswith('api_'):
        try:
            _, operation = services.identify(name)
            return operation.read_only and operation.method in ('GET', 'HEAD')
        except ToolFailure:
            return False
    return False


def create(body: SourceMonitorCreate):
    from ..agent import tools
    if not db.get_session(body.session_id) or policies.owner(body.session_id) != body.session_id:
        raise ValueError('Choose an existing owner conversation')
    if not readonly(body.tool):
        raise ValueError('Monitors require a supported read-only source operation')
    tools.validate_args(body.tool, body.arguments)
    if body.select and not body.select.startswith('/'):
        raise ValueError('Observation selection must be a JSON Pointer')
    if len(json.dumps(body.arguments)) > 64000:
        raise ValueError('Monitor arguments exceed the size limit')
    key = uuid.uuid4().hex[:16]
    db.execute('INSERT INTO agent_monitors(id,session_id,data,next_at,updated_at) VALUES(?,?,?,?,?)', (key,body.session_id,body.model_dump_json(),time.time(),db.now_iso()))
    store.notify('monitors', body.session_id)
    return next(v for v in listing(body.session_id) if v['id'] == key)


def listing(sid=None):
    return [{**json.loads(row['data']), 'id':row['id'], 'source_hash':row['source_hash'],
             'observation':row['observation'], 'last_error':row['last_error'], 'failures':row['failures'],
             'next_at':row['next_at'], 'updated_at':row['updated_at'], 'memory_id':row['memory_id']} for row in db.query(
                 'SELECT * FROM agent_monitors WHERE (? IS NULL OR session_id=?) ORDER BY updated_at DESC', (sid,sid))]


def enable(key, enabled):
    row = db.query_one('SELECT data FROM agent_monitors WHERE id=?', (key,))
    if not row: raise ValueError('Monitor not found')
    data = json.loads(row['data']);data['enabled'] = enabled
    db.execute('UPDATE agent_monitors SET data=?,next_at=?,updated_at=? WHERE id=?', (json.dumps(data),time.time(),db.now_iso(),key))
    store.notify('monitors',data['session_id'])


def pause(sid):
    for item in listing(sid):
        if item['enabled']: enable(item['id'], False)


class MonitorRunner:
    def __init__(self): self.task = None
    def start(self): self.task = asyncio.create_task(self.run(), name='source-monitors')
    async def shutdown(self):
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        self.task = None
    async def run(self):
        while True:
            try: await self.tick()
            except asyncio.CancelledError: raise
            except Exception as exc:
                from .. import events
                events.log('error','monitors',str(exc))
            await asyncio.sleep(2)
    async def tick(self):
        from ..agent import tools
        from ..agent_plus.store import atomic
        for row in db.query('SELECT * FROM agent_monitors WHERE next_at<=? ORDER BY next_at LIMIT 10', (time.time(),)):
            value = SourceMonitorCreate.model_validate_json(row['data'])
            if not value.enabled: continue
            key = row['id']
            try:
                if not readonly(value.tool): raise ToolFailure('Source operation is no longer read-only or available')
                ctx = ToolContext(value.session_id, 'monitor-' + uuid.uuid4().hex, lambda _:None)
                async with asyncio.timeout(90):
                    outcome = await tools.execute(value.tool, value.arguments, ctx)
                if not outcome.ok: raise ToolFailure(outcome.output)
                observation = policies.field(json.loads(outcome.output), value.select) if value.select else outcome.output
                encoded = json.dumps(observation,sort_keys=True,ensure_ascii=False,allow_nan=False)
                if len(encoded) > 64000: raise ToolFailure('Select a smaller observation; monitor output exceeds 64,000 characters')
                digest = hashlib.sha256(encoded.encode()).hexdigest()
                with atomic():
                    # Re-read configuration: pause/revoke can happen while awaiting the source.
                    current = db.query_one('SELECT data,source_hash FROM agent_monitors WHERE id=?', (key,))
                    if not current or not json.loads(current['data'])['enabled']: continue
                    prior = current['source_hash']
                    if digest!=prior and value.record_memory:
                        note='Observed source '+value.name+' at '+db.now_iso()+':\n'+encoded
                        if len(note)>8000: note=note[:7900]+'\n[Source observation truncated; inspect monitor_status for the full value.]'
                        memory=store.add_knowledge(KnowledgeCreate(scope='chat',scope_id=value.session_id,text=note,source='monitor:'+key+' sha256:'+digest))
                        previous=db.query_one('SELECT memory_id FROM agent_monitors WHERE id=?',(key,))['memory_id']
                        if previous:
                            db.execute('DELETE FROM agent_knowledge WHERE id=?',(previous,))
                            db.execute('DELETE FROM agent_knowledge_vectors WHERE id=?',(previous,))
                        db.execute('UPDATE agent_monitors SET memory_id=? WHERE id=?',(memory.id,key))
                    if digest != prior and (prior is not None or value.notify_initial):
                        wake = wakes.create(value.session_id, WakeCreate(prompt=value.prompt + '\nInspect the changed source; verify before performing effects.', topic='monitor:' + key))
                        wakes.event('monitor:' + key,uuid.uuid4().hex,'monitor',
                                    {'monitor_id':key,'previous_hash':prior,'source_hash':digest,'observation':observation},value.session_id)
                    db.execute('UPDATE agent_monitors SET observation=?,source_hash=?,next_at=?,failures=0,last_error=NULL,updated_at=? WHERE id=?',
                               (encoded,digest,time.time()+value.interval_seconds,db.now_iso(),key))
                store.notify('monitors',value.session_id)
            except asyncio.CancelledError: raise
            except Exception as exc:
                failures = row['failures'] + 1
                db.execute('UPDATE agent_monitors SET failures=?,last_error=?,next_at=?,updated_at=? WHERE id=?',
                           (failures,str(exc)[:1600],time.time()+min(86400,value.interval_seconds*2**min(failures,8)),db.now_iso(),key))
                if failures == 1:
                    from . import notifications
                    notifications.save(value.session_id,'error','Source monitor needs attention',str(exc)[:1000],'monitor:'+key+':'+str(row['source_hash']))
                store.notify('monitors',value.session_id)


runner = MonitorRunner()


async def status(a,ctx): return ToolOutcome(True,json.dumps(listing(policies.owner(ctx.session_id))))


async def watch(a,ctx): return ToolOutcome(True,json.dumps(create(SourceMonitorCreate(session_id=ctx.session_id,**a))))


async def pause_watch(a,ctx):
    if not any(item['id']==a['id'] for item in listing(policies.owner(ctx.session_id))): raise ToolFailure('Watch is outside this conversation')
    enable(a['id'],False)
    return ToolOutcome(True,'Source watch paused')


IMPL = {'monitor_status':status,'watch_source':watch,'pause_source_watch':pause_watch}
