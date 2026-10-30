"""Real local tool roundtrips in temporary storage; no paid APIs or large downloads."""
import asyncio
import io
import json
import os
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import test_agents as foundation
from studio import config, db, automations, memories
from studio.agent import tools
from studio.agent.types import ToolContext
from studio.agents import plugins
from studio.workspace import state, terminals, checkpoints
from studio.voice import store as voice_store

RECORDS=[]

class ToolIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await foundation.AgentStateTests.asyncSetUp(self)
        state.set_root('owner',str(self.root))
        self.memory_patch=patch.object(state,'MEMORY_DIR',self.root/'memory');self.memory_patch.start()
        memories.init();automations.init();voice_store.init();checkpoints.init()
        model_patch=patch.object(config,'MODELS_DIR',self.root/'models');model_patch.start();self.patches.append(model_patch)
        self.ctx=ToolContext('owner','fixture',lambda _:None,ask=self.answer,vision=True,invoke=self.invoke)

    async def answer(self,*_): return 'Continue'

    async def invoke(self,name,args):
        outcome=await tools.execute(name,args,self.ctx)
        RECORDS.append({'name':name,'args':args,'ok':outcome.ok,'output':outcome.output,
                        'display':outcome.display.model_dump(mode='json') if outcome.display else None})
        return outcome

    async def check(self,name,args):
        outcome=await self.invoke(name,args)
        self.assertTrue(outcome.ok,outcome.output)
        return outcome

    async def asyncTearDown(self):
        terminals.shutdown()
        self.memory_patch.stop()
        destination=os.environ.get('TOOL_TEST_REPORT')
        if destination:Path(destination).write_text(json.dumps(RECORDS,ensure_ascii=False,indent=2),encoding='utf-8')
        await foundation.AgentStateTests.asyncTearDown(self)

    async def test_local_utilities_and_question(self):
        self.assertIn('714',(await self.check('calculate',{'expression':'37*19+11'})).output)
        value=await self.check('convert',{'value':10,'from_unit':'mile','to_unit':'km'})
        self.assertAlmostEqual(value.display.result,16.09344)
        await self.check('world_time',{'locations':['America/Los_Angeles','UTC']})
        await self.check('ask_user',{'question':'Proceed with fixture?','options':['Continue','Stop']})
        await self.check('system_info',{})
        await self.check('list_models',{})
        await self.check('list_outputs',{})
        await self.check('list_voices',{})
        await self.check('search_catalog',{'kind':'text','query':'gemma'})

    async def test_workspace_files_and_plan(self):
        await self.check('write_file',{'path':'fixture.txt','content':'alpha beta gamma\n'})
        await self.check('read_file',{'path':'fixture.txt'})
        await self.check('edit_file',{'path':'fixture.txt','old_string':'beta','new_string':'delta'})
        self.assertEqual((self.root/'fixture.txt').read_text(encoding='utf-8'),'alpha delta gamma\n')
        for name,args in [('list_dir',{}),('find_files',{'pattern':'*.txt'}),('search_files',{'pattern':'delta'}),
                          ('update_plan',{'items':[{'text':'Read fixture','status':'done'}]}),
                          ('memory',{'action':'replace','content':'The fixture contains alpha delta gamma.'}),('memory',{'action':'read'})]:
            await self.check(name,args)
        self.assertFalse((await self.invoke('read_file',{'path':'../outside.txt'})).ok)

    async def test_sequential_composition_and_scripts(self):
        value=await self.check('execute_tools',{'steps':[{'id':'first','name':'calculate','args':{'expression':'3+5'}},
                                                        {'id':'second','name':'convert','args':{'value':10,'from_unit':'m','to_unit':'cm'}}]})
        self.assertIn('1000',value.output)
        value=await self.check('run_tool_script',{'code':"result = tools.calculate(expression='6*7')"})
        self.assertIn('42',value.output)

    async def test_artifacts_knowledge_and_memories(self):
        value=await self.check('artifact_save',{'title':'Orbit','kind':'json','content':'{"count":3}'})
        artifact=json.loads(value.output)
        await self.check('artifact_read',{'id':artifact['id']})
        await self.check('artifact_save',{'id':artifact['id'],'version':artifact['version'],'title':'Orbit','kind':'json','content':'{"count":4}'})
        await self.check('artifact_read',{})
        await self.check('knowledge_save',{'text':'The fixture is called orbit','scope':'chat','source':'fixture'})
        self.assertIn('orbit',(await self.check('knowledge_search',{'query':'orbit'})).output)
        value=await self.check('remember',{'fact':'The test fixture is called orbit.'})
        mid=memories.list_all()[0].id
        await self.check('forget',{'id':mid});self.assertEqual(memories.list_all(),[])
        await self.check('notify_user',{'title':'Test complete','body':'Fixture checks finished.'})

    async def test_discovery_guides_plugins_and_retrieval(self):
        await self.check('search_tools',{'query':'current time'})
        await self.check('search_tools',{'query':'^world_time$','mode':'regex'})
        await self.check('load_tools',{'names':['world_time','calculate']})
        await self.check('skill_read',{})
        for name in tools.python_tools.SKILLS:
            await self.check('read_skill',{'name':name})
        await self.check('office_file_help',{})
        (self.root/'notes.txt').write_text('Orbit means the verification fixture. It has three rows.',encoding='utf-8')
        await self.check('index_documents',{'collection':'fixture','paths':['notes.txt']})
        self.assertIn('Orbit',(await self.check('search_documents',{'query':'Orbit','collection':'fixture'})).output)
        bundle=io.BytesIO()
        with zipfile.ZipFile(bundle,'w') as archive:
            archive.writestr('plugin.json',json.dumps({'format':'grom-plugin-v1','id':'fixture','version':'1','skills':[]}))
            archive.writestr('notes.txt','Verified fixture source')
        plugins.install(plugins.inspect(bundle.getvalue()))
        await self.check('plugin_list',{})
        await self.check('plugin_read_file',{'plugin_id':'fixture','path':'notes.txt'})

    async def test_automation_lifecycle_without_starting_scheduler(self):
        value=await self.check('automation_create',{'title':'Fixture reminder','prompt':'Inspect fixture','timing_mode':'exact_schedule','dtstart_offset_json':'{"days":1}'})
        aid=value.display.automation_id
        await self.check('automation_update',{'id':aid,'enabled':False,'title':'Paused fixture'})
        await self.check('automation_list',{})
        await self.check('automation_delete',{'id':aid})
        self.assertEqual(automations.list_all(),[])
        await self.check('wake_schedule',{'prompt':'Inspect fixture','wake_at':'2099-01-01T00:00:00Z'})

    async def test_missing_connections_fail_as_tool_results(self):
        cases=[('consult_advisor',{'question':'Check fixture'}),('invoke_skill',{'name':'missing','args':{}}),
               ('computer_action',{'action':'screenshot'}),('connector_resources',{'connector_id':'missing'}),
               ('connector_read_resource',{'connector_id':'missing','uri':'fixture://missing'}),
               ('cancel_delegation',{'id':'missing'}),('plugin_read_file',{'plugin_id':'missing','path':'notes.txt'})]
        for name,args in cases:
            with self.subTest(name=name):self.assertFalse((await self.invoke(name,args)).ok)
        await self.check('delegation_status',{})

    async def test_terminal_and_background_process(self):
        from studio.osenv import IS_WINDOWS
        command = "Write-Output 'tool-smoke-ok'" if IS_WINDOWS else "printf tool-smoke-ok"
        value=await self.check('run_command',{'command':command,'timeout_s':10})
        self.assertIn('tool-smoke-ok',value.output)
        command = "Start-Sleep -Seconds 5" if IS_WINDOWS else "sleep 5"
        value=await self.check('start_process',{'command':command})
        pid=value.display.terminal_id
        await self.check('read_process_output',{'process_id':pid})
        await self.check('stop_process',{'process_id':pid})

    async def test_browser_roundtrip_against_local_fixture(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from studio.workspace.browser import browser
        import importlib
        browser_module=importlib.import_module("studio.workspace.browser")
        from studio.agents import browser_tools
        class Handler(BaseHTTPRequestHandler):
            shifted=False
            def do_GET(self):
                data=b"<html><title>Tool fixture</title><body><h1>Orbit fixture</h1><label>Name<input id='name'></label><button id='apply' onclick=\"document.getElementById('result').textContent=document.getElementById('name').value\">Apply</button><p id='result'>Ready</p></body></html>"
                if self.shifted: data=b'<style>body{padding:100px 40px}button{margin-left:200px}</style>'+data
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(data)
            def log_message(self,*_):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        patches=[patch.object(browser_module,'PROFILE_DIR',self.root/'profile'),patch.object(browser_module,'SHOTS_DIR',self.root/'shots')]
        for item in patches:item.start()
        try:
            await self.check('browser_navigate',{'url':f'http://127.0.0.1:{server.server_port}'})
            await self.check('browser_read',{})
            await self.check('browser_type',{'selector':'#name','text':'Verified browser value'})
            await self.check('browser_click',{'selector':'#apply'})
            self.assertIn('Verified browser value',(await self.check('browser_read',{})).output)
            await self.check('browser_screenshot',{})
            for action in ['console','network','list_tabs']:
                await self.check('browser_action',{'action':action})
            await self.check('browser_action',{'action':'javascript','script':'document.querySelector("#result").textContent'})
            from studio.agents import recording
            recording.start('owner')
            page=(await browser.agent_page('owner')).page
            await page.locator('#name').focus()
            await recording.record('owner',page,{'type':'text','text':'Old recorded value'})
            bounds=await page.locator('#apply').bounding_box()
            await recording.record('owner',page,{'type':'click','x':bounds['x']+bounds['width']/2,'y':bounds['y']+bounds['height']/2})
            skill=recording.finish('owner','Apply a name')
            with self.assertRaisesRegex(Exception,'enable'): await recording.replay({'skill_id':skill.id,'inputs':{'name':'New replay value'}},self.ctx)
            skill.enabled=True
            db.execute('UPDATE agent_skills SET data=? WHERE id=?',(skill.model_dump_json(),skill.id))
            Handler.shifted=True
            await self.check('replay_demonstration',{'skill_id':skill.id,'inputs':{'name':'New replay value'}})
            self.assertIn('New replay value',(await self.check('browser_read',{})).output)
            db.execute('UPDATE agent_browser_demonstrations SET data=? WHERE skill_id=?',(json.dumps({'events':[{'type':'text','url':page.url,'selector':'#name','input_name':'name','text':'[input omitted: field could not be inspected]'}]}),skill.id))
            with self.assertRaisesRegex(Exception,'secure-input'): await recording.replay({'skill_id':skill.id,'inputs':{'name':'Unsafe replay'}},self.ctx)
        finally:
            await browser_tools.shutdown();await browser.shutdown()
            server.shutdown();server.server_close()
            for item in reversed(patches):item.stop()

    async def test_all_application_template_requests_with_local_transport(self):
        import httpx
        from studio.agents import services,service_templates
        from studio.schemas_agents import ServiceCreate
        requests=[]
        def respond(request):
            requests.append(request)
            return httpx.Response(200,json={'verified':True,'method':request.method,'path':request.url.path})
        original=httpx.AsyncClient
        def client(**kwargs):
            kwargs['transport']=httpx.MockTransport(respond)
            return original(**kwargs)
        def sample(schema):
            if 'enum' in schema:return schema['enum'][0]
            kind=schema.get('type','string')
            if kind=='object':return {key:sample(schema.get('properties',{}).get(key,{})) for key in schema.get('required',[])}
            if kind=='array':return [sample(schema.get('items',{})) for _ in range(schema.get('minItems',0))]
            if kind in ('integer','number'):return schema.get('minimum',1)
            if kind=='boolean':return True
            return 'fixture'
        for template in service_templates.listing():
            service=services.create(ServiceCreate.model_validate(template['service']));services.enable(service.id,True)
            for operation in service.operations:
                args=sample(operation.parameters)
                with patch.object(httpx,'AsyncClient',client):
                    result=await services.call(services.operation_name(service.id,operation),args,self.ctx)
                self.assertTrue(result.ok,result.output)
                self.assertEqual(requests[-1].method,operation.method)
        self.assertEqual(len(requests),sum(len(profile['service']['operations']) for profile in service_templates.listing()))

    async def test_model_delete_is_confined_to_temporary_fixture(self):
        from studio.schemas import InstalledModel
        folder=(self.root/'models'/'fixture-model').resolve();folder.mkdir(parents=True)
        self.assertTrue(folder.is_relative_to(self.root.resolve()))
        (folder/'fixture.bin').write_bytes(b'fixture')
        db.upsert_installed(InstalledModel(id='fixture-model',catalog_id='fixture-model',name='Fixture model',kind='image',runtime='diffusers',path=str(folder),size_bytes=7,installed_at=db.now_iso(),status='ready'))
        await self.check('delete_model',{'model_id':'fixture-model'})
        self.assertIsNone(db.get_installed('fixture-model'))
        self.assertFalse(folder.exists())

    async def test_captcha_pages_are_not_successful_research(self):
        from unittest.mock import AsyncMock
        from studio.agents import research
        page=('https://example.com/check','Prove your humanity',None,'Prove your humanity',{'links':[]})
        with patch.object(research.browser,'navigate',new=AsyncMock()), patch.object(research.browser,'page',new=AsyncMock(return_value=page)):
            for name,args in [('research_search',{'query':'fixture'}),('read_social_thread',{'url':'https://www.reddit.com/r/test/comments/fixture'})]:
                result=await self.invoke(name,args)
                self.assertFalse(result.ok)
                self.assertIn('human check',result.output)
                self.assertEqual(result.display.kind,'browser')
        self.assertTrue(research.needs_human('DuckDuckGo','Unfortunately, bots use DuckDuckGo too. Please complete the following challenge to confirm this search was made by a human.'))

    async def test_search_redirects_are_resolved_and_domain_constraints_enforced(self):
        from unittest.mock import AsyncMock
        from studio.agents import research
        page=('https://html.duckduckgo.com/html/','Search results',None,'Three results',{'links':[
            {'title':'Official CSV','url':'https://duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2Flibrary%2Fcsv.html'},
            {'title':'Unrelated','url':'https://example.invalid/result'},
            {'title':'Credentials','url':'https://user:secret@docs.python.org/private'}]})
        with patch.object(research.browser,'navigate',new=AsyncMock()),patch.object(research.browser,'page',new=AsyncMock(return_value=page)):
            result=await research.search({'query':'CSV','domains':['docs.python.org']},self.ctx)
        self.assertEqual(json.loads(result.output)['links'],[{'title':'Official CSV','url':'https://docs.python.org/3/library/csv.html'}])

    async def test_paging_failure_recovers_idle_workers_and_preserves_busy_workers(self):
        from types import SimpleNamespace
        from studio.models import models
        from studio.runtimes import WorkerError, runtimes
        from studio.schemas import InstalledModel
        folder=self.root/'video-model';folder.mkdir()
        model=InstalledModel(id='video-fixture',catalog_id='video-fixture',name='Video fixture',kind='video',runtime='diffusers-video',path=str(folder),size_bytes=1,installed_at=db.now_iso(),status='ready')
        db.upsert_installed(model)
        attempts=[]
        def request(runtime,method,path,**kwargs):
            if path=='/health':return {'busy':runtime=='ace-step'}
            attempts.append((runtime,path))
            if len(attempts)==1:raise WorkerError('The paging file is too small (os error 1455)')
            return {}
        infos=[SimpleNamespace(id='kokoro',name='Kokoro',running=True),SimpleNamespace(id='ace-step',name='Music',running=True)]
        with patch.object(models,'_make_room'),patch.object(runtimes,'all_info',return_value=infos),patch.object(runtimes,'request',side_effect=request),patch.object(runtimes,'stop') as stop,patch.object(runtimes,'set_loaded'):
            loaded=models.load(model.id)
            self.assertEqual(loaded.status,'loaded')
            self.assertEqual(len(attempts),2)
            self.assertEqual([call.args[0] for call in stop.call_args_list],['kokoro','diffusers-video'])
