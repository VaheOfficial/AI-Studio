"""Actual launch arguments, reported capacity, fallback and cancellation isolation."""
import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from studio import arena_runtime, llamacpp
from studio.schemas_arena import ArenaMatch

def match(inference='auto',mode='argument'):
    return ArenaMatch(id='arena-fixture',created_at='2026-10-13T00:00:00Z',updated_at='2026-10-13T00:00:00Z',
                      prompt='Tabs or spaces?',left={'name':'Red','model':'llamacpp:fixture'},
                      right={'name':'Gold','model':'llamacpp:fixture'},inference=inference,mode=mode)

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches=[patch('studio.agent.agent.active_turns',return_value=[]),
                      patch.object(arena_runtime.settings,'load',return_value=SimpleNamespace(llamacpp_ctx_size=98304))]
        for p in self.patches:p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):p.stop()

    async def prepare_with(self,value,fail=False,cpu_spill=False):
        state={'capacity':None};loads=[]
        def load(model,**kw):
            loads.append(kw)
            if fail and kw['parallel']==2:raise RuntimeError('CUDA out of memory')
            state['capacity']={'slots':kw['parallel'],'context_per_slot':kw['context_per_slot'],'busy':False}
            if cpu_spill:state['capacity']['gpu_offload_complete']=kw['parallel']==1
        with patch.object(llamacpp.server,'capacity',side_effect=lambda:state['capacity']),patch.object(llamacpp.server,'base_url',return_value=None),patch.object(arena_runtime.models,'load',side_effect=load):
            result=await arena_runtime.prepare(value)
        return result,loads

    async def test_auto_uses_two_shared_slots_with_bounded_context(self):
        result,loads=await self.prepare_with(match())
        self.assertEqual(result[:2],(2,8192));self.assertEqual(len(loads),1)
        self.assertEqual(loads[0]['parallel'],2)
        result,loads=await self.prepare_with(match(mode='task'))
        self.assertEqual(result[:2],(2,32768))

    async def test_auto_falls_back_but_explicit_two_reports_failure(self):
        result,loads=await self.prepare_with(match(),True)
        self.assertEqual(result[0],1);self.assertEqual([v['parallel'] for v in loads],[2,1])
        self.assertIn('CUDA out of memory',result[2])
        with self.assertRaisesRegex(RuntimeError,'out of memory'):await self.prepare_with(match('two'),True)

    async def test_one_requests_one_slot(self):
        result,loads=await self.prepare_with(match('one'))
        self.assertEqual(result[0],1);self.assertEqual(loads[0]['parallel'],1)

    async def test_auto_retries_one_when_two_slots_spill_layers_to_cpu(self):
        result,loads=await self.prepare_with(match(),cpu_spill=True)
        self.assertEqual(result[0],1);self.assertEqual([v['parallel'] for v in loads],[2,1])
        self.assertIn('CPU',result[2])
        result,loads=await self.prepare_with(match('two'),cpu_spill=True)
        self.assertEqual(result[0],2);self.assertIn('CPU',result[2])

    async def test_busy_chat_is_not_restarted(self):
        from studio.agent import agent
        current={'slots':1,'context_per_slot':65536,'busy':True}
        with patch.object(agent,'active_turns',return_value=[SimpleNamespace(session_id='chat')]),patch('studio.db.get_session',return_value=SimpleNamespace(model='llamacpp:fixture')),patch.object(llamacpp.server,'capacity',return_value=current),patch.object(llamacpp.server,'base_url',return_value='http://fixture/v1'),patch.object(arena_runtime.models,'load') as load:
            result=await arena_runtime.prepare(match())
            self.assertEqual(result[:2],(1,65536));load.assert_not_called()
            with self.assertRaisesRegex(ValueError,'active chat'):await arena_runtime.prepare(match('two'))

    async def test_cancelled_load_never_starts_a_fallback(self):
        started=threading.Event()
        def loading(model,slots,context,owner,cancel):
            started.set();cancel.wait(2);raise arena_runtime.CapacityCancelled()
        with patch.object(arena_runtime,'configure',side_effect=loading) as configure,patch.object(llamacpp.server,'cancel_load') as cancel_load,patch.object(llamacpp.server,'base_url',return_value=None),patch.object(arena_runtime.models,'set_status'):
            task=asyncio.create_task(arena_runtime.prepare(match()))
            while not started.is_set():await asyncio.sleep(.005)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            configure.assert_called_once();cancel_load.assert_called_once_with('arena-fixture')

    async def test_release_does_not_interrupt_an_active_chat(self):
        from studio.agent import agent
        with patch.object(agent,'active_turns',return_value=[SimpleNamespace(session_id='chat')]),patch('studio.db.get_session',return_value=SimpleNamespace(model='llamacpp:fixture')),patch.object(llamacpp.server,'release_arena') as release:
            await arena_runtime.release({'arena-fixture'})
            release.assert_not_called()

class LaunchTests(unittest.TestCase):
    def test_release_requires_ownership_and_idle_slots(self):
        server=llamacpp.LlamaServer();server._proc=MagicMock();server._proc.poll.return_value=None
        server._load_owner='arena-fixture';server._model_id='fixture'
        with patch.object(server,'capacity',return_value={'slots':2,'context_per_slot':8192,'busy':True}),patch.object(server,'_stop_locked',return_value='fixture') as stop,patch.object(llamacpp,'_mark_unloaded'):
            self.assertFalse(server.release_arena({'different-owner'}));self.assertFalse(server.release_arena({'arena-fixture'}));stop.assert_not_called()
        with patch.object(server,'capacity',return_value={'slots':2,'context_per_slot':8192,'busy':False}),patch.object(server,'_stop_locked',return_value='fixture') as stop,patch.object(llamacpp,'_mark_unloaded') as unloaded:
            self.assertTrue(server.release_arena({'arena-fixture'}));stop.assert_called_once();unloaded.assert_called_once_with('fixture')

    def test_parallel_launch_preserves_context_per_slot_and_disables_single_slot_mtp(self):
        with tempfile.TemporaryDirectory() as root:
            model=Path(root)/'fixture.gguf';model.write_bytes(b'fixture')
            settings=SimpleNamespace(llamacpp_ctx_size=98304,llamacpp_kv_cache='q8_0')
            proc=MagicMock();proc.poll.return_value=None
            server=llamacpp.LlamaServer()
            with patch.object(llamacpp,'installed',return_value=True),patch.object(llamacpp,'model_files',return_value=(model,None)),patch.object(llamacpp,'is_draft_model',return_value=False),patch.object(llamacpp.settings,'load',return_value=settings),patch.object(llamacpp,'chat_template_override',return_value=None),patch.object(llamacpp,'mtp_layers',return_value=4),patch.object(llamacpp,'bind_to_server_lifetime'),patch.object(llamacpp.threading,'Thread'),patch.object(llamacpp,'kill_tree'),patch.object(llamacpp.runtimes,'publish'),patch.object(server,'_wait_healthy'),patch.object(llamacpp.subprocess,'Popen',return_value=proc) as popen:
                m=SimpleNamespace(id='fixture',name='Fixture')
                server.load(m,parallel=2,context_per_slot=8192)
                cmd=popen.call_args.args[0]
                self.assertEqual(cmd[cmd.index('-np')+1],'2');self.assertEqual(cmd[cmd.index('-c')+1],'16384')
                self.assertIn('--cont-batching',cmd);self.assertNotIn('--spec-type',cmd)
                server.load(m)
                cmd=popen.call_args.args[0]
                self.assertEqual(cmd[cmd.index('-np')+1],'1');self.assertEqual(cmd[cmd.index('-c')+1],'98304')
                self.assertIn('--spec-type',cmd)
