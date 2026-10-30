"""Protocol, scoped memory, authenticated file transport and repository roundtrips."""
import base64
import json
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch
import httpx
import test_agents as foundation
from studio import db, config
from studio.agent.types import Call, Message, StepEnd, ToolContext
from studio.agent import history
from studio.agents import google_workspace, model_checks, services, service_templates, store, git_workspace
from studio.schemas_agents import ServiceCreate, KnowledgeCreate
from studio.workspace import state


class ProtocolTransferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await foundation.AgentStateTests.asyncSetUp(self)
        state.set_root('owner',str(self.root))
        self.ctx=ToolContext('owner','test',lambda _:None)
    async def asyncTearDown(self): await foundation.AgentStateTests.asyncTearDown(self)

    async def test_probe_requires_structured_call_and_new_tool_result(self):
        class Good:
            async def stream(self,system,messages,specs):
                if specs:
                    marker=messages[0].content.split('marker ')[1].split('.')[0]
                    yield StepEnd('',[Call('probe','protocol_probe',{'marker':marker})])
                else: yield StepEnd(messages[-2].content,[])
        class Fabricated:
            async def stream(self,*args): yield StepEnd('I called the tool successfully.',[])
        with patch('studio.agent.providers.get_provider',return_value=Good()):
            self.assertTrue((await model_checks.check('ollama:fixture'))['tools'])
        with patch('studio.agent.providers.get_provider',return_value=Fabricated()):
            self.assertFalse((await model_checks.check('ollama:fixture'))['tools'])
        with self.assertRaisesRegex(ValueError,'spending'): await model_checks.check('openrouter:fixture')

    async def test_stale_protocol_evidence_is_not_reported_supported(self):
        endpoint=model_checks.endpoint('ollama:fixture')
        db.execute('INSERT INTO agent_model_checks VALUES(?,?,?)',('ollama:fixture',endpoint,json.dumps({'tools':True,'checked_at':'2020-01-01T00:00:00Z'})))
        self.assertFalse(model_checks.get('ollama:fixture')['tools'])
        self.assertTrue(model_checks.get('ollama:fixture')['stale'])

    async def test_provider_state_is_replayed_only_to_same_model(self):
        step={'text':'Observed','calls':[],'provider_state':{'model':'openrouter:fixture','payload':{'reasoning_details':[{'type':'encrypted','data':'opaque'}]}}}
        self.assertEqual(history.step_messages(step,'openrouter:fixture')[0].raw,step['provider_state']['payload'])
        self.assertIsNone(history.step_messages(step,'llamacpp:fixture')[0].raw)

    async def test_structured_output_requests_native_schema_and_rejects_invalid_response(self):
        from studio.agent.providers.openai_chat import OpenAIProvider
        from studio.agents import structured_output
        from studio.agent.types import ToolFailure
        schema={'type':'object','properties':{'count':{'type':'integer'}},'required':['count'],'additionalProperties':False}
        provider=OpenAIProvider('fixture','http://127.0.0.1:1/v1',None)
        provider.response_schema=schema
        body=provider._body('Extract',[Message('user','Count')],None)
        self.assertEqual(body['response_format']['json_schema']['schema'],schema)
        class Generated:
            response='{"count":3}'
            async def stream(self,*_): yield StepEnd(self.response,[])
        generated=Generated()
        with patch.object(structured_output,'get_provider',return_value=generated):
            value=await structured_output.generate({'prompt':'Count three items','schema':schema},self.ctx)
            self.assertEqual(json.loads(value.output)['value'],{'count':3})
            self.assertEqual(generated.response_schema,schema)
            for response in ('{"count":"3"}','{"count":3,"extra":true}','not JSON','{"count":NaN}'):
                generated.response=response
                with self.assertRaisesRegex(ToolFailure,'validation'): await structured_output.generate({'prompt':'Count','schema':schema},self.ctx)
        with self.assertRaisesRegex(ToolFailure,'local'): structured_output.validator({'$ref':'https://example.invalid/schema'})

    async def test_code_review_findings_require_real_source_lines(self):
        from studio.agents import code_review
        from studio.agent.types import ToolFailure,ToolOutcome
        (self.root/'source.py').write_text('def lookup(conn, name):\n    return conn.execute("SELECT " + name)\n',encoding='utf-8')
        report={'findings':[{'severity':'high','title':'Untrusted SQL','file':'source.py','line':2,'evidence':'conn.execute("SELECT " + name)','recommendation':'Use a parameterized query'}],'limitations':['Only supplied source']}
        async def infer(name,args):
            self.assertEqual(name,'structured_output')
            return ToolOutcome(True,json.dumps({'value':report}))
        self.ctx.invoke=infer
        value=await code_review.review({'paths':['source.py']},self.ctx)
        parsed=json.loads(value.output)
        self.assertEqual(parsed['review'],'advisory');self.assertTrue(parsed['syntax_checks'][0]['passed'])
        report['findings'][0]['line']=1
        with self.assertRaisesRegex(ToolFailure,'source location'): await code_review.review({'paths':['source.py']},self.ctx)

    async def test_semantic_notes_do_not_cross_scope_or_keep_stale_vectors(self):
        item=store.add_knowledge(KnowledgeCreate(scope='chat',scope_id='owner',text='Car listing available',source='fixture'))
        store.add_knowledge(KnowledgeCreate(scope='chat',scope_id='other',text='Private other fact'))
        with patch('studio.agents.collections.embed',side_effect=lambda model,texts:[[1.0,0.0] for _ in texts]):
            self.assertEqual([v.id for v in store.semantic_knowledge('owner','vehicle','fixture')],[item.id])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM agent_knowledge_vectors')['n'],1)
        store.update_knowledge(item.id,KnowledgeCreate(scope='chat',scope_id='owner',text='Listing withdrawn'),item.updated_at)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM agent_knowledge_vectors')['n'],0)

    def service(self,kind):
        profile=next(v for v in service_templates.listing() if v['id']==kind)
        return services.create(ServiceCreate(**{**profile['service'],'enabled':True}))

    async def test_gmail_mime_draft_preserves_attachment_without_sending(self):
        service=self.service('gmail');(self.root/'receipt.txt').write_text('Measured receipt: 42',encoding='utf-8')
        requests=[]
        def respond(request):
            requests.append(request)
            self.assertEqual(request.url.path,'/gmail/v1/users/me/drafts')
            body=json.loads(request.content);decoded=base64.urlsafe_b64decode(body['message']['raw'])
            mail=BytesParser(policy=policy.default).parsebytes(decoded)
            self.assertEqual(mail['To'],'test@example.invalid');self.assertEqual(mail['Subject'],'Draft only')
            attachment=list(mail.iter_attachments())[0]
            self.assertEqual(attachment.get_filename(),'receipt.txt');self.assertEqual(attachment.get_payload(decode=True),b'Measured receipt: 42')
            return httpx.Response(200,json={'id':'draft-1','message':{'id':'message-1'}})
        real=httpx.AsyncClient
        with patch.object(google_workspace.oauth,'authorized_config',return_value={'headers':{'Authorization':'Bearer fixture-secret'}}),patch.object(google_workspace.httpx,'AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(respond))):
            result=await google_workspace.invoke({'action':'draft_mail','service_id':service.id,'to':['test@example.invalid'],'subject':'Draft only','text':'Local transport verification','sources':['receipt.txt']},self.ctx)
        self.assertTrue(result.ok);self.assertEqual(len(requests),1);self.assertNotIn('fixture-secret',result.output)

    async def test_drive_authenticated_download_rejects_redirect_and_stays_managed(self):
        service=self.service('google-drive');real=httpx.AsyncClient
        with patch.object(google_workspace.oauth,'authorized_config',return_value={'headers':{'Authorization':'Bearer fixture'}}),patch.object(google_workspace.httpx,'AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'verified bytes')))):
            result=await google_workspace.invoke({'action':'download_drive','service_id':service.id,'file_id':'file-1','name':'../../verified.txt'},self.ctx)
        self.assertTrue(result.ok);artifact=result.display.files[0]
        self.assertEqual(Path(artifact.path).read_bytes(),b'verified bytes')
        self.assertEqual(Path(artifact.path).name,'verified.txt')
        with patch.object(google_workspace.oauth,'authorized_config',return_value={'headers':{}}),patch.object(google_workspace.httpx,'AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(lambda request:httpx.Response(302,headers={'location':'https://other.invalid'})))):
            refused=await google_workspace.invoke({'action':'download_drive','service_id':service.id,'file_id':'file-1'},self.ctx)
        self.assertFalse(refused.ok)

    async def test_managed_worktree_dirty_refusal_and_owner_checks(self):
        repository=self.root/'repo';repository.mkdir();state.set_root('owner',str(repository));state.set_root('other',str(repository))
        patcher=patch.object(config,'WORKTREES_DIR',self.root/'worktrees');patcher.start();self.patches.append(patcher)
        await git_workspace.git(repository,'init')
        await git_workspace.git(repository,'config','user.name','Test fixture')
        await git_workspace.git(repository,'config','user.email','test@example.invalid')
        (repository/'source.txt').write_text('original',encoding='utf-8')
        await git_workspace.invoke({'action':'stage','paths':['source.txt']},self.ctx)
        await git_workspace.invoke({'action':'commit','message':'Fixture baseline'},self.ctx)
        created=await git_workspace.invoke({'action':'create_worktree','branch':'codex/fixture'},self.ctx)
        value=json.loads(created.output);path=Path(value['path'])
        self.assertTrue((path/'source.txt').is_file());self.assertNotIn(repository,path.parents)
        (path/'source.txt').write_text('modified',encoding='utf-8')
        with self.assertRaises(Exception): await git_workspace.invoke({'action':'remove_worktree','worktree_id':value['id']},self.ctx)
        self.assertTrue(path.exists())
        (path/'source.txt').write_text('original',encoding='utf-8')
        with self.assertRaises(Exception): await git_workspace.invoke({'action':'remove_worktree','worktree_id':value['id']},ToolContext('other','other',lambda _:None))
        await git_workspace.invoke({'action':'remove_worktree','worktree_id':value['id']},self.ctx)
        self.assertFalse(path.exists())
