"""Bounded scheduling, lifecycle and ordinary task-chat integration."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from studio import arena, config, db
from studio.agent.types import TextDelta, StepEnd
from studio.schemas import EvTextDelta
from studio.schemas_arena import ArenaCreate, ArenaControl, ArenaMatch

class FakeProvider:
    active=0
    peak=0
    delay=.03
    failing=''
    prompts=[]
    def __init__(self,model):self.model=model
    async def stream(self,system,history,tools):
        type(self).active+=1;type(self).peak=max(type(self).peak,type(self).active)
        type(self).prompts.append((self.model,system,history[0].content))
        try:
            if self.model==self.failing:raise ValueError('Provider offline')
            await asyncio.sleep(self.delay)
            text='Be sharp and funny.' if system.startswith('Write a compact') else f'{self.model}: Here is my rebuttal.'
            yield TextDelta(text[:10]);await asyncio.sleep(self.delay);yield TextDelta(text[10:])
            yield StepEnd(text,[])
        finally:type(self).active-=1

def body(**values):
    return ArenaCreate.model_validate(dict(prompt='Tabs versus spaces',left={'name':'Red','model':'test:red'},right={'name':'Gold','model':'test:gold'},replies=3,**values))

class ArenaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.prior=db._conn
        self.path=patch.object(config,'DB_PATH',Path(self.folder.name)/'studio.db');self.path.start();db.init();arena.init()
        self.workspace=patch.object(config,'WORKSPACE_DIR',Path(self.folder.name)/'workspace');self.workspace.start()
        self.runner=arena.ArenaRunner()
        FakeProvider.active=FakeProvider.peak=0;FakeProvider.delay=.02;FakeProvider.failing='';FakeProvider.prompts=[]
        self.provider=patch.object(arena,'get_provider',lambda model:FakeProvider(model));self.provider.start()

    async def asyncTearDown(self):
        await self.runner.shutdown();self.provider.stop();db._conn.close();db._conn=self.prior;self.path.stop();self.workspace.stop();self.folder.cleanup()

    async def wait(self,m):
        await asyncio.wait_for(self.runner.tasks[m.id],5)

    async def test_free_fire_runs_both_and_caps_replies(self):
        m=self.runner.create(body())
        await self.runner.control(m.id,ArenaControl(action='start'));await self.wait(m)
        self.assertEqual(m.status,'done');self.assertEqual(FakeProvider.peak,2)
        for side in ('left','right'):
            messages=[v for v in m.messages if v.side==side]
            self.assertTrue(messages);self.assertLessEqual(len(messages),3)
            self.assertTrue(all(v.status=='done' for v in messages))
            self.assertTrue(getattr(m,side).persona)
        self.assertTrue(any(v.responding_to for v in m.messages))
        self.assertEqual(arena.read(m.id).revision,m.revision)

    async def test_one_slot_gates_provider_requests_even_in_free_fire(self):
        m=self.runner.create(body(inference='one'))
        await self.runner.control(m.id,ArenaControl(action='start'));await self.wait(m)
        self.assertEqual(m.status,'done');self.assertEqual(FakeProvider.peak,1)

    async def test_alternating_is_optional_and_strict(self):
        m=self.runner.create(body(pacing='alternating'))
        await self.runner.control(m.id,ArenaControl(action='start'));await self.wait(m)
        self.assertEqual([v.side for v in m.messages],['left','right']*3)

    async def test_pause_cancels_both_and_resume_persists_history(self):
        m=self.runner.create(body());FakeProvider.delay=.15
        await self.runner.control(m.id,ArenaControl(action='start'))
        for _ in range(100):
            if m.messages:break
            await asyncio.sleep(.01)
        await self.runner.control(m.id,ArenaControl(action='pause'))
        self.assertEqual(m.status,'paused');self.assertEqual(FakeProvider.active,0)
        self.assertFalse(any(v.status=='streaming' for v in m.messages))
        old_ids={v.id for v in m.messages};FakeProvider.delay=.01
        await self.runner.control(m.id,ArenaControl(action='start'));await self.wait(m)
        self.assertTrue(old_ids.issubset({v.id for v in m.messages}));self.assertEqual(m.status,'done')

    async def test_single_reply_host_interjection_vote_and_closed_match(self):
        m=self.runner.create(body())
        self.runner.interject(m.id,'No appeals to popularity.')
        await self.runner.control(m.id,ArenaControl(action='step',side='right'));await self.wait(m)
        self.assertEqual(m.status,'paused')
        self.assertEqual([v.side for v in m.messages],['host','right'])
        self.assertTrue(any('No appeals to popularity' in prompt for _,_,prompt in FakeProvider.prompts))
        await self.runner.control(m.id,ArenaControl(action='vote',winner='right'));self.assertEqual(m.winner,'right')
        await self.runner.control(m.id,ArenaControl(action='stop'))
        with self.assertRaises(ValueError):self.runner.interject(m.id,'Restart')
        with self.assertRaises(ValueError):await self.runner.control(m.id,ArenaControl(action='start'))

    async def test_provider_failure_does_not_leave_rival_waiting(self):
        FakeProvider.failing='test:red';m=self.runner.create(body(pacing='alternating'))
        await self.runner.control(m.id,ArenaControl(action='start'));await self.wait(m)
        self.assertEqual(m.left.state,'error');self.assertEqual(m.right.state,'done')
        self.assertIn('offline',m.left.error)

    async def test_elapsed_limit_cancels_streams(self):
        m=self.runner.create(body());m.time_limit=15;m.elapsed_s=14.95;FakeProvider.delay=.2
        await self.runner.control(m.id,ArenaControl(action='start'));await self.wait(m)
        self.assertEqual(m.reason,'Time limit reached');self.assertEqual(FakeProvider.active,0)

    async def test_restart_recovers_running_match_as_paused(self):
        m=self.runner.create(body());m.status='running';m.left.state='writing';m.right.state='done';arena.save(m)
        arena.init();restored=arena.read(m.id)
        self.assertEqual(restored.status,'paused');self.assertEqual(restored.left.state,'idle')
        self.assertEqual(restored.right.state,'done')

    async def test_task_mode_uses_two_distinct_normal_sessions(self):
        from studio.agent import agent
        calls=[]
        def start(session,content,listener):
            calls.append((session.id,content));reply=SimpleNamespace(content='A verified deliverable')
            async def run():
                listener(EvTextDelta(text=reply.content));await asyncio.sleep(.02)
            return SimpleNamespace(task=asyncio.create_task(run()),reply=reply,stopped=False)
        async def stop(sid):pass
        with patch.object(agent,'start',start),patch.object(agent,'stop_and_wait',stop):
            m=self.runner.create(body(mode='task'))
            await self.runner.control(m.id,ArenaControl(action='start'));await self.wait(m)
        self.assertNotEqual(m.left.session_id,m.right.session_id);self.assertEqual(len(calls),2)
        self.assertTrue(all(db.get_session(sid).mode=='agent' for sid,_ in calls))
        self.assertTrue(all(v.content=='A verified deliverable' for v in m.messages))

    async def test_http_validation_and_snapshot(self):
        from studio.routes.arena import router
        app=FastAPI();app.include_router(router)
        with patch.object(arena,'runner',self.runner):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://studio') as client:
                value=body().model_dump();value['replies']=999
                self.assertEqual((await client.post('/api/arena',json=value)).status_code,422)
                response=await client.post('/api/arena',json=body().model_dump())
                self.assertEqual(response.status_code,200);key=response.json()['id']
                self.assertEqual((await client.get('/api/arena/'+key)).json()['status'],'ready')
                self.assertEqual((await client.get('/api/arena/missing')).status_code,404)
                self.assertEqual((await client.post('/api/arena/'+key+'/control',json={'action':'vote','winner':'tie'})).status_code,409)

    async def test_task_contenders_execute_a_real_tool_through_agent_loop(self):
        from studio import agents, memories, agent_plus, connectors, swarm
        from studio.agent.providers.base import Provider
        from studio.agent.types import ModelInfo, Call
        memories.init();agent_plus.init();connectors.init();swarm.store.init();agents.init()
        from studio.workspace import state
        state.init()
        class WorkingProvider(Provider):
            async def info(self):return ModelInfo(context=131072,tools=True)
            async def complete(self,*args):return 'Completed'
            async def stream(self,system,history,tools):
                results=[v.name for v in history if v.role=='tool']
                if 'load_tools' not in results:yield StepEnd('',[Call('load','load_tools',{'names':['calculate']})])
                elif 'calculate' not in results:yield StepEnd('',[Call('calc','calculate',{'expression':'2+2'})])
                else:
                    yield TextDelta('Verified: 2 + 2 = 4.')
                    yield StepEnd('Verified: 2 + 2 = 4.',[])
        with patch('studio.agent.loop.get_provider',return_value=WorkingProvider()):
            m=self.runner.create(body(mode='task'))
            await self.runner.control(m.id,ArenaControl(action='start'));await self.wait(m)
        for c in (m.left,m.right):
            self.assertIsNone(c.error)
            calls=[call for msg in db.list_messages(c.session_id) for call in (msg.tool_calls or [])]
            calculate=next(v for v in calls if v.name=='calculate')
            self.assertEqual(calculate.status,'done')
            self.assertIn('4',calculate.output)
