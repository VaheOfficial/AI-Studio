"""Action boundaries and incoming-work acceptance checks in isolated local storage."""
import asyncio
import hashlib
import hmac
import json
import time
import unittest
import uuid
from unittest.mock import patch
import test_agents as foundation
from studio import db
from studio.agent import tools
from studio.agent.types import ToolContext, ToolOutcome
from studio.agents import channels, monitors, policies, wakes, delegation, services, model_checks
from studio.schemas_agents import ActionPolicy, AgentChannelCreate, SourceMonitorCreate, DelegateCreate, DelegationFollowup
from studio.workspace import state, checkpoints
from studio.agent.loop import AgentService
from studio.agent.types import Call, ModelInfo, StepEnd
from studio.agent.providers.base import Provider


class ActionContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await foundation.AgentStateTests.asyncSetUp(self)
        checkpoints.init()

    async def asyncTearDown(self):
        await foundation.AgentStateTests.asyncTearDown(self)

    def ctx(self, sid='owner', call_id=None): return ToolContext(sid,call_id or uuid.uuid4().hex,lambda _:None)

    async def test_constraints_reject_before_effects_and_preserve_other_conversation(self):
        policy=policies.configure('owner',ActionPolicy(enabled=True,rules=[{'tool':'write_file','constraints':[{'path':'/path','operator':'eq','value':'approved.txt'}],'max_calls':1}]))
        state.set_root('owner',str(self.root))
        denied=await tools.execute('write_file',{'path':'outside.txt','content':'x'},self.ctx())
        self.assertFalse(denied.ok);self.assertFalse((self.root/'outside.txt').exists())
        accepted=await tools.execute('write_file',{'path':'approved.txt','content':'x'},self.ctx())
        self.assertTrue(accepted.ok,accepted.output);self.assertEqual((self.root/'approved.txt').read_text(),'x')
        repeated=await tools.execute('write_file',{'path':'approved.txt','content':'y'},self.ctx())
        self.assertFalse(repeated.ok);self.assertEqual((self.root/'approved.txt').read_text(),'x')
        policies.enforce('write_file',{'path':'anything.txt'},self.ctx('other'))
        with self.assertRaisesRegex(ValueError,'changed'):
            policies.configure('owner',ActionPolicy(version=policy.version-1))

    async def test_all_matching_rules_apply_and_missing_numeric_boolean_rejected(self):
        policies.configure('owner',ActionPolicy(enabled=True,rules=[
            {'tool':'calculate','constraints':[{'path':'/offer','operator':'gte','value':15000}]},
            {'tool':'cal*','constraints':[{'path':'/recipient','operator':'in','value':['buyer-1']}]}]))
        for value in ({'offer':14000,'recipient':'buyer-1'},{'offer':True,'recipient':'buyer-1'},
                      {'offer':16000,'recipient':'buyer-2'},{'recipient':'buyer-1'}):
            with self.assertRaises(Exception): policies.enforce('calculate',value,self.ctx())
        policies.enforce('calculate',{'offer':16000,'recipient':'buyer-1'},self.ctx())

    async def test_quota_atomicity_and_uncertain_retry(self):
        policies.configure('owner',ActionPolicy(enabled=True,rules=[{'tool':'calculate','max_calls':1}]))
        def attempt():
            try: policies.enforce('calculate',{},self.ctx());return True
            except Exception: return False
        results=await asyncio.gather(*[asyncio.to_thread(attempt) for _ in range(8)])
        self.assertEqual(sum(results),1)
        row=db.query_one('SELECT call_id FROM agent_policy_receipts')
        call_id=row['call_id'].split(':',1)[1]
        with self.assertRaisesRegex(Exception,'receipt already exists'):
            policies.enforce('calculate',{},self.ctx(call_id=call_id))

    async def test_invalid_artifact_preflight_does_not_consume_effect_quota(self):
        policies.configure('owner',ActionPolicy(enabled=True,rules=[{'tool':'artifact_save','max_calls':1}]))
        invalid=await tools.execute('artifact_save',{'title':'Result','kind':'json','content':'{}','id':'invented','version':1},self.ctx())
        self.assertFalse(invalid.ok)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM agent_policy_receipts')['n'],0)
        saved=await tools.execute('artifact_save',{'title':'Result','kind':'json','content':'{}'},self.ctx())
        self.assertTrue(saved.ok,saved.output)
        exhausted=await tools.execute('artifact_save',{'title':'Second','kind':'json','content':'{}'},self.ctx())
        self.assertFalse(exhausted.ok);self.assertTrue(exhausted.terminal_error)

    async def test_repeated_failure_stops_instead_of_fabricating_completion(self):
        class Failing(Provider):
            requests=0
            async def info(self): return ModelInfo(context=32768,tools=True)
            async def complete(self,*_): return 'Failure check'
            async def stream(self,*_):
                self.requests+=1
                yield StepEnd('',[Call(str(self.requests),'read_file',{'path':'missing.txt'})])
        state.set_root('owner',str(self.root));provider=Failing();service=AgentService();events=[]
        with patch('studio.agent.loop.get_provider',return_value=provider), patch('studio.agent.prompt.build',return_value='Read the required source using tools.'):
            turn=service.start(db.get_session('owner'),'Read the required source',events.append)
            await turn.task
        self.assertEqual(provider.requests,3)
        self.assertTrue(all(call.status=='error' for call in turn.reply.tool_calls))
        self.assertIn('Work stopped before completion',turn.reply.content)
        self.assertTrue(any(getattr(event,'type',None)=='error' for event in events))

    async def test_children_inherit_and_opaque_execution_cannot_bypass_contract(self):
        child=delegation.create('owner',DelegateCreate(objective='Read only',allowed_tools=['read_file']))
        policies.configure('owner',ActionPolicy(enabled=True,rules=[{'tool':'run_command'}]))
        with self.assertRaisesRegex(Exception,'opaque'):
            policies.enforce('run_command',{'command':'anything'},self.ctx(child.session_id))
        with self.assertRaisesRegex(ValueError,'owner'):
            policies.configure(child.session_id,ActionPolicy())

    def signed(self,body,secret='s'*24,timestamp=None):
        timestamp=str(timestamp if timestamp is not None else int(time.time()))
        digest=hmac.new(secret.encode(),b'v1:'+timestamp.encode()+b':'+body,hashlib.sha256).hexdigest()
        return {'x-studio-timestamp':timestamp,'x-studio-signature':'v1='+digest}

    def channel(self):
        with patch.object(channels.vault,'protect',side_effect=lambda v:'test:'+v):
            return channels.create(AgentChannelCreate(session_id='owner',name='Buyer channel',provider='webhook',secret='s'*24,
                                   allowed_senders=['buyer-1'],allowed_conversations=['listing-1']))

    async def test_signed_inbound_idempotence_grants_tampering_and_pause(self):
        channel=self.channel()
        body=json.dumps({'message_id':'m1','sender':'buyer-1','conversation':'listing-1','text':'Is it available?'}).encode()
        with patch.object(channels.vault,'reveal',side_effect=lambda v:v.removeprefix('test:')):
            self.assertTrue(channels.receive(channel.id,body,self.signed(body))['accepted'])
            self.assertTrue(channels.receive(channel.id,body,self.signed(body))['duplicate'])
            self.assertEqual(len(wakes.list_all('owner')),1)
            for content,headers in [(body+b' ',self.signed(body)),(body,self.signed(body,timestamp=0))]:
                with self.assertRaises(ValueError): channels.receive(channel.id,content,headers)
            denied=json.dumps({'message_id':'m2','sender':'buyer-2','conversation':'listing-1','text':'x'}).encode()
            with self.assertRaisesRegex(ValueError,'grant'): channels.receive(channel.id,denied,self.signed(denied))
            channels.enable(channel.id,False)
            with self.assertRaisesRegex(ValueError,'disabled'): channels.receive(channel.id,body,self.signed(body))
        self.assertNotIn('secret',channel.model_dump())
        with self.assertRaises(Exception): await channels.messages({'channel_id':channel.id},self.ctx('other'))

    async def test_read_monitor_baseline_change_quiet_error_recovery(self):
        item=monitors.create(SourceMonitorCreate(session_id='owner',name='Inventory',tool='read_file',arguments={'path':'fixture.txt'},prompt='Inspect changes'))
        state.set_root('owner',str(self.root))
        runner=monitors.MonitorRunner()
        async def poll(text,ok=True):
            db.execute('UPDATE agent_monitors SET next_at=0 WHERE id=?',(item['id'],))
            (self.root/'fixture.txt').write_text(text,encoding='utf-8')
            if ok:
                await runner.tick()
            else:
                with patch.object(tools,'execute',return_value=ToolOutcome(False,text)):
                    await runner.tick()
        await poll('baseline');self.assertEqual(len(wakes.list_all('owner')),0)
        await poll('baseline');self.assertEqual(len(wakes.list_all('owner')),0)
        await poll('changed');self.assertEqual(len(wakes.list_all('owner')),1)
        before=monitors.listing('owner')[0]['source_hash']
        await poll('network failure',False)
        observed=monitors.listing('owner')[0]
        self.assertEqual(observed['source_hash'],before);self.assertEqual(observed['failures'],1)
        await poll('changed');self.assertIsNone(monitors.listing('owner')[0]['last_error'])
        monitors.pause('owner');await poll('another change');self.assertEqual(len(wakes.list_all('owner')),1)
        with self.assertRaisesRegex(ValueError,'read-only'):
            monitors.create(SourceMonitorCreate(session_id='owner',name='Bad',tool='run_command',prompt='Run'))

    async def test_outbound_receipt_survives_success_and_uncertain_delivery(self):
        item=self.channel()
        value=channels.raw(item.id);value['send_tool']='api_fixture_send'
        db.execute('UPDATE agent_channels SET data=? WHERE id=?',(json.dumps(value),item.id))
        for mid in ('success','timeout'):
            db.execute('INSERT INTO agent_channel_messages VALUES(?,?,?,?,?,?)',(item.id,mid,'buyer-1','listing-1','Hello',db.now_iso()))
        sends=[]
        async def deliver(name,args):
            sends.append(args)
            return ToolOutcome(True,'Delivered')
        ctx=self.ctx();ctx.invoke=deliver
        args={'channel_id':item.id,'message_id':'success','text':'It is available'}
        self.assertTrue((await channels.reply(args,ctx)).ok)
        db._conn.close();db._conn=None;db.init()
        self.assertIn('duplicate_suppressed',(await channels.reply(args,ctx)).output)
        self.assertEqual(len(sends),1)
        async def timeout(*_): raise TimeoutError('Delivery outcome unknown')
        ctx.invoke=timeout;args['message_id']='timeout'
        with self.assertRaises(TimeoutError): await channels.reply(args,ctx)
        db._conn.close();db._conn=None;db.init()
        ctx.invoke=deliver
        with self.assertRaisesRegex(Exception,'uncertain'): await channels.reply(args,ctx)
        self.assertEqual(len(sends),1)

    async def test_followup_preserves_child_scope_and_request_budget(self):
        child=delegation.create('owner',DelegateCreate(objective='Read',allowed_tools=['read_file'],max_requests=4))
        db.execute("UPDATE workspace_tasks SET status='succeeded' WHERE id=?",(child.task_id,))
        result=delegation.followup('owner',child.id,DelegationFollowup(message='Read a second file',additional_requests=3))
        self.assertEqual(result.allowed_tools,['read_file']);self.assertEqual(result.max_requests,7);self.assertEqual(result.status,'queued')
        with self.assertRaises(ValueError): delegation.followup('other',child.id,DelegationFollowup(message='Wrong owner'))
        with self.assertRaises(ValueError): delegation.followup('owner',child.id,DelegationFollowup(message='Still running'))
