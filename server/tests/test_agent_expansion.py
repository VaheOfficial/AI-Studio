"""CPU checks for application adapters, scoped speech, retrieval and notifications."""
from __future__ import annotations
import json
import asyncio
import ssl
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
import test_agents as foundation
from studio import connectors, db
from studio.agents import collections, coverage, devices, gateway, gateway_voice, notifications, registry, services, service_templates
from studio.agent.types import ToolContext, ToolFailure, ToolSpec
from studio.schemas import InstalledModel, Job, JobResult, Output
from studio.schemas_agents import DeviceCreate, PushSubscriptionInput, ServiceCreate, ServiceImport
from studio.workspace import state


class ExpansionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = foundation.AgentStateTests.asyncSetUp
    asyncTearDown = foundation.AgentStateTests.asyncTearDown

    async def test_templates_install_disabled_and_mutations_keep_approval(self):
        templates = service_templates.listing()
        self.assertEqual(len(templates),15)
        for template in templates:
            value = services.create(ServiceCreate.model_validate(template['service']))
            self.assertFalse(value.enabled)
            self.assertEqual(services.specs(),[])
        github = services.list_all()[-1]
        services.enable(github.id,True)
        specs=services.specs()
        self.assertTrue(specs)
        for tool, operation in zip(specs,github.operations):
            self.assertEqual(tool.needs_approval,not operation.read_only)
        self.assertTrue(any(operation.read_only for operation in github.operations))

    async def test_openapi_parameter_overrides_and_separate_locations(self):
        operation = {'operationId':'read','parameters':[
            {'name':'q','in':'query','required':True,'schema':{'type':'string'}},
            {'name':'id','in':'query','schema':{'type':'integer'}}],
            'responses':{'200':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Recursive'}}}}}}
        path_item = {'parameters':[
            {'name':'id','in':'path','required':True,'schema':{'type':'string'}},
            {'name':'q','in':'query','schema':{'type':'string'}}], 'get':operation}
        document = {'openapi':'3.0.3','paths':{'/items/{id}':path_item}}
        reviewed = services.import_openapi(ServiceImport(name='Fixture',base_url='https://example.com/api',document=document))
        self.assertEqual(reviewed['warnings'],[])
        value = services.create(ServiceCreate.model_validate(reviewed['service']))
        operation = value.operations[0]
        self.assertEqual(set(operation.parameters['required']),{'id','q'})
        url,query,_ = services.request(value,operation,{'id':'a/b','q':'exact words','query_id':3})
        self.assertEqual(url,'https://example.com/api/items/a%2Fb')
        self.assertEqual(query,{'q':'exact words','id':3})
        with self.assertRaises(ToolFailure): services.request(value,operation,{'id':'..','q':'q'})

    async def test_service_schema_invalid_input_never_reaches_network(self):
        value = services.create(ServiceCreate.model_validate(service_templates.listing()[0]['service']))
        services.enable(value.id,True)
        name = services.operation_name(value.id,value.operations[0])
        with self.assertRaises(ToolFailure):
            await services.call(name,{'owner':'owner','repo':'repo','per_page':1000},ToolContext('owner','fixture',lambda _:None))
        with self.assertRaises(ValueError):
            services.create(ServiceCreate(name='Unsafe',base_url='https://example.com',operations=[value.operations[0].model_copy(update={'path':'/../escape'})]))

    async def test_app_only_mcp_tools_are_hidden_from_model_catalog(self):
        value = connectors.manager.create(__import__('studio.schemas_connectors',fromlist=['ConnectorCreate']).ConnectorCreate(name='Fixture',transport='stdio',command='not-launched',enabled=False))
        db.execute('UPDATE connectors SET enabled=1 WHERE id=?',(value.id,))
        live = connectors._Live(status='connected',tools=[{'name':'visible','description':'Visible','inputSchema':{'type':'object','properties':{}},'meta':{}},
            {'name':'app-only','description':'App only','inputSchema':{'type':'object','properties':{}},'meta':{'ui':{'visibility':['app']}}}])
        with patch.dict(connectors.manager._live,{value.id:live},clear=True):
            names = [name for name,*_ in connectors.manager.tool_specs()]
            self.assertEqual(names,['fixture__visible'])
            self.assertEqual(len(connectors.manager.get(value.id).tools),2)

    async def test_bm25_regex_and_whole_catalog(self):
        specs = [ToolSpec('tool_'+str(i),'Ordinary utility',{'type':'object','properties':{}}) for i in range(140)]
        specs.append(ToolSpec('office_file','Create spreadsheets with charts',{'type':'object','properties':{}}))
        self.assertEqual(len(registry.search(specs,'',2000)),141)
        self.assertEqual(registry.search(specs,'spreadsheet charts')[0].name,'office_file')
        self.assertEqual([entry.name for entry in registry.search(specs,'^office_',mode='regex')],['office_file'])
        with self.assertRaises(ValueError): registry.search(specs,'[',mode='regex')

    async def test_semantic_retrieval_scope_staleness_and_atomic_failure(self):
        root = self.root/'workspace'; root.mkdir(); (root/'a.txt').write_text('Blue orbit project',encoding='utf-8')
        other = self.root/'other'; other.mkdir()
        state.set_root('owner',str(root)); state.set_root('other',str(other))
        with patch.object(collections,'embed',return_value=[[1.0,0.0]]):
            collections.index('owner','notes',['a.txt'],'fixture-embed')
            result = collections.search('owner','orbit','notes',mode='semantic')
            self.assertEqual(result[0]['similarity'],1)
            self.assertFalse(result[0]['stale'])
            self.assertEqual(collections.search('other','orbit','notes'),[])
        (root/'a.txt').write_text('Changed project',encoding='utf-8')
        with patch.object(collections,'embed',side_effect=ValueError('Fixture outage')):
            with self.assertRaises(ValueError): collections.index('owner','notes',['a.txt'],'fixture-embed')
        result = collections.search('owner','orbit','notes')
        self.assertTrue(result[0]['stale']); self.assertIn('Blue orbit',result[0]['text'])
        with patch.object(collections,'embed',return_value=[[0.0,0.0]]):
            with self.assertRaises(ValueError): collections.search('owner','orbit','notes',mode='semantic')

    async def test_notifications_deduplicate_and_require_push_scope(self):
        first = notifications.save('owner','notice','Finished','Fixture output','same-receipt')
        self.assertIsNotNone(first)
        self.assertIsNone(notifications.save('owner','notice','Finished','Fixture output','same-receipt'))
        self.assertEqual(notifications.list_all('other'),[])
        notifications.mark_read(first.id); self.assertTrue(notifications.list_all('owner')[0].read)
        grant = devices.issue(DeviceCreate(name='Viewer',scopes=['read'],session_ids=['owner']))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://test') as client:
            response = await client.get('/push/key',headers={'Authorization':'Bearer '+grant['token']})
            self.assertEqual(response.status_code,403)
        with self.assertRaises(ValueError): notifications.subscribe(grant['device'],PushSubscriptionInput(endpoint='https://example.com/push',keys={'p256dh':'test','auth':'test'}))

    async def test_gateway_speech_is_local_and_conversation_scoped(self):
        grant = devices.issue(DeviceCreate(name='Phone',scopes=['read','chat'],session_ids=['owner']))
        headers = {'Authorization':'Bearer '+grant['token']}
        local = InstalledModel(id='fixture-voice',name='Local voice',kind='voice',runtime='kokoro',catalog_id='fixture-voice',path='fixture',size_bytes=0,status='ready',installed_at=db.now_iso())
        request = {'model_id':'fixture-voice','voice_id':'af_heart','text':'Fixture speech','speed':1}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://test') as client:
            with patch.object(db,'get_installed',return_value=local.model_copy(update={'runtime':'openrouter'})), patch('studio.voice.speech.tts') as synthesize:
                self.assertEqual((await client.post('/sessions/owner/speak',headers=headers,json=request)).status_code,400)
                synthesize.assert_not_called()
            self.assertEqual((await client.post('/sessions/other/speak',headers=headers,json=request)).status_code,403)
            job = Job(id='speech-fixture',kind='generate',title='Fixture',status='done',progress=1,created_at=db.now_iso(),result=JobResult(outputs=[Output(id='audio-fixture',kind='audio',model_id='fixture-voice',prompt='Fixture',params={},url='/files/audio.wav',created_at=db.now_iso())]))
            with patch.object(db,'get_installed',return_value=local),patch('studio.voice.speech.tts',return_value=job),patch.object(gateway_voice.jobs,'get',return_value=job):
                value = await client.post('/sessions/owner/speak',headers=headers,json=request)
                self.assertEqual(value.status_code,200); self.assertEqual(value.json()['result']['outputs'][0]['url'],'/voice/audio/speech-fixture/audio-fixture')
                other = devices.issue(DeviceCreate(name='Other',scopes=['read'],session_ids=['other']))
                response = await client.get('/voice/jobs/speech-fixture',headers={'Authorization':'Bearer '+other['token']})
                self.assertEqual(response.status_code,404)
                denied = await client.delete('/voice/jobs/speech-fixture',headers={'Authorization':'Bearer '+other['token']})
                self.assertEqual(denied.status_code,403)
                with patch.object(gateway_voice.jobs,'cancel',return_value=job) as cancel:
                    accepted = await client.delete('/voice/jobs/speech-fixture',headers=headers)
                    self.assertEqual(accepted.status_code,200);cancel.assert_called_once_with('speech-fixture')
        gateway_voice.bindings.clear()

    async def test_coverage_and_public_mobile_office_resources(self):
        families = coverage.listing('owner')
        self.assertEqual(len({item.id for item in families}),len(families))
        self.assertGreaterEqual(len(families),20)
        self.assertIn('inspect_media',next(item.tools for item in families if item.id=='media-inspection'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://test') as client:
            for path in ('/','/manifest.webmanifest','/mobile-sw.js','/office','/office/icon.png','/office/icon.png?size=512','/office/manifest.xml?host=word&base_url=https://localhost:8767'):
                response = await client.get(path); self.assertEqual(response.status_code,200,path)
            self.assertEqual((await client.get('/office/manifest.xml?host=word&base_url=http://localhost:8767')).status_code,400)

    async def test_local_https_keys_are_encrypted_and_setup_does_not_trust_the_os(self):
        from studio.agents import gateway_tls, vault
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        secrets = {}
        def protect(value):
            key = 'fixture-secret-' + str(len(secrets)); secrets[key] = value; return key
        with patch.object(vault,'protect',side_effect=protect),patch.object(vault,'reveal',side_effect=lambda key:secrets[key]),patch.object(gateway_tls,'trust_certificate') as trust:
            first = gateway_tls.configure(); certificate,key = gateway_tls.paths()
            original = certificate.read_bytes()
            second = gateway_tls.configure()
            self.assertEqual(certificate.read_bytes(),original)
            self.assertTrue(first['requires_user_trust']); self.assertEqual(first,second); trust.assert_not_called()
            self.assertIn(b'ENCRYPTED PRIVATE KEY',key.read_bytes())
            options = gateway_tls.options()
            private = serialization.load_pem_private_key(key.read_bytes(),password=options['ssl_keyfile_password'].encode())
            cert = x509.load_pem_x509_certificate(original)
            self.assertEqual(cert.public_key().public_numbers(),private.public_key().public_numbers())
            import truststore
            # Verify this fixture against its temporary CA file without changing the OS trust store.
            original_context = ssl.SSLContext
            truststore.extract_from_ssl()
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(options['ssl_certfile'],options['ssl_keyfile'],options['ssl_keyfile_password'])
                async def respond(reader,writer):
                    writer.write(b'fixture TLS'); await writer.drain(); writer.close(); await writer.wait_closed()
                server = await asyncio.start_server(respond,'127.0.0.1',0,ssl=context)
                try:
                    client_context = ssl.create_default_context(cafile=str(certificate))
                    reader,writer = await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1],ssl=client_context,server_hostname='localhost')
                    self.assertEqual(await reader.read(),b'fixture TLS'); writer.close(); await writer.wait_closed()
                finally:
                    server.close(); await server.wait_closed()

            finally:
                if original_context is truststore.SSLContext: truststore.inject_into_ssl()


    async def test_push_delivery_is_scoped_revocable_and_has_no_chat_contents(self):
        from studio.schemas_agents import NotificationSettings
        owner = devices.issue(DeviceCreate(name='Phone',scopes=['notifications'],session_ids=['owner']))
        other = devices.issue(DeviceCreate(name='Other',scopes=['notifications'],session_ids=['other']))
        for grant,key in [(owner,'owner'),(other,'other')]:
            notifications.subscribe(grant['device'],PushSubscriptionInput(endpoint='https://fcm.googleapis.com/fcm/send/fixture-'+key,keys={'p256dh':'fixture','auth':'fixture'}))
        value = notifications.save('owner','notice','Secret project title','Secret project contents','fixture-push')
        notifications.configure(NotificationSettings(web_push=True))
        with patch('pywebpush.webpush') as send:
            await notifications.deliver(value)
            self.assertEqual(send.call_count,1)
            payload = json.loads(send.call_args.kwargs['data'])
            self.assertNotIn('Secret',json.dumps(payload)); self.assertEqual(payload['session_id'],'owner')
            devices.revoke(owner['device'].id)
            await notifications.deliver(value)
            self.assertEqual(send.call_count,1)

    async def test_real_cpu_video_sampling_and_dispatch(self):
        from studio import media
        from studio.agents import media_inspection
        from studio.agent import tools as dispatcher
        if not media.find('ffmpeg') or not media.find('ffprobe'): self.skipTest('FFmpeg/FFprobe are not installed')
        root = self.root/'workspace'; root.mkdir(); state.set_root('owner',str(root))
        source = root/'fixture.mp4'
        await media_inspection.run([media.ffmpeg(),'-v','error','-f','lavfi','-i','color=c=blue:s=128x128:r=24','-t','1','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)])
        value = await dispatcher.execute('inspect_media',{'source':'fixture.mp4','timestamps':[0.2,0.6]},ToolContext('owner','fixture',lambda _:None,vision=True))
        self.assertTrue(value.ok,value.output)
        result = json.loads(value.output)
        self.assertEqual(len(result['frames']),2); self.assertEqual(len(value.images),2)
        self.assertEqual(float(result['metadata']['format']['duration']),1)
        refused = await dispatcher.execute('inspect_media',{'source':'fixture.mp4','timestamps':[2]},ToolContext('owner','fixture',lambda _:None))
        self.assertFalse(refused.ok)

    async def test_office_dispatch_returns_managed_files_and_preserves_scopes(self):
        from studio.agent import tools as dispatcher
        from studio.agents import file_tools
        from studio.runtimes import envs
        if not envs.is_ready('python'): self.skipTest('CPU document environment is not installed')
        value = await dispatcher.execute('office_file',{'action':'create_document','name':'fixture','options':{'blocks':[{'type':'heading','text':'Verified result'},{'type':'paragraph','text':'A local document worker produced this file.'}]}},ToolContext('owner','fixture',lambda _:None))
        self.assertTrue(value.ok,value.output)
        document = json.loads(value.output)['outputs'][0]
        self.assertTrue(Path(document['path']).is_file()); self.assertTrue(document['url'].startswith('/files/outputs/'))
        self.assertEqual(len(value.display.files),1)
        with self.assertRaises(ToolFailure): file_tools.resolve_source('owner',str(self.root/'studio.db'))
