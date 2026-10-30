"""CPU-only checks for scoped state, permissions and persistent agent capabilities."""
from __future__ import annotations
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from studio import agent_plus, agents, config, connectors, db
from studio.agent.types import ToolContext, ToolFailure, ToolOutcome, ToolSpec
from studio.agent_plus import store as missions
from studio.agents import delegation, devices, plugins, registry, store, tools, wakes
from studio.schemas import AgentSession
from studio.schemas_agent_plus import AgentPlusMission, MissionAction, MissionWork
from studio.schemas_agents import ArtifactCreate, DelegateCreate, DeviceCreate, KnowledgeCreate, WakeCreate
from studio.workspace import state
from studio.workspace.tasks import TaskRunner


class AgentStateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='studio-agents-')
        self.root = Path(self.temporary.name)
        self.patches = [patch.object(config, 'DATA_DIR', self.root), patch.object(config, 'DB_PATH', self.root / 'studio.db')]
        for name in ('OUTPUTS_DIR', 'CACHE_DIR', 'WORKSPACE_DIR'):
            self.patches.append(patch.object(config, name, self.root / name.removesuffix('_DIR').lower()))
        for item in self.patches:
            item.start()
        db.init(); state.init(); TaskRunner.init_db(); agent_plus.init(); agents.init(); connectors.init()
        now = db.now_iso()
        for sid in ('owner', 'other'):
            db.insert_session(AgentSession(id=sid, title=sid, model='ollama:fixture', mode='agent', created_at=now, updated_at=now))

    async def asyncTearDown(self):
        if db._conn:
            db._conn.close(); db._conn = None
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def mission(self):
        now = db.now_iso()
        value = AgentPlusMission(session_id='owner', original_request='Deliver output', objective='Deliver output',
            criteria=missions.criteria(['Current output is verified']), status='running', created_at=now, updated_at=now)
        missions.save(value)
        return value

    async def test_chat_knowledge_does_not_cross_scope_and_stale_edit_is_refused(self):
        value = store.add_knowledge(KnowledgeCreate(scope='chat', scope_id='owner', text='Project orbit is blue', source='fixture'))
        self.assertEqual([v.id for v in store.retrieve('owner', 'orbit')], [value.id])
        self.assertEqual(store.retrieve('other', 'orbit'), [])
        store.update_knowledge(value.id, KnowledgeCreate(scope='chat', scope_id='owner', text='Project orbit is green'), value.updated_at)
        with self.assertRaises(ValueError):
            store.update_knowledge(value.id, KnowledgeCreate(text='Stale change'), value.updated_at)
        self.assertEqual(store.retrieve('other', 'orbit'), [])

    async def test_artifact_edit_invalidates_evidence_and_dependent_work(self):
        mission = self.mission()
        first = store.save_artifact('owner', ArtifactCreate(title='Result', content='Original'))
        missions.save_action('owner', MissionAction(id='saved', name='artifact_save', args={}, status='succeeded', output=first.model_dump_json(), created_at=db.now_iso()))
        mission.criteria[0].evidence = ['saved']; mission.status = 'completed'; missions.save(mission)
        missions.save_work('owner', [MissionWork(id='deliver', kind='delivery', objective='Write', status='done', evidence=['saved']),
                                   MissionWork(id='check', kind='validation', objective='Verify', dependencies=['deliver'], status='done', evidence=['saved'])])
        second = store.save_artifact('owner', ArtifactCreate(id=first.id, version=1, title='Result', content='Revised'))
        self.assertEqual(second.version, 2)
        self.assertEqual(store.artifact(first.id, 1).content, 'Original')
        self.assertEqual(missions.get('owner').criteria[0].evidence, [])
        self.assertEqual(missions.get('owner').status, 'paused')
        self.assertTrue(all(v.status == 'pending' for v in missions.work('owner')))
        with self.assertRaises(ValueError):
            store.save_artifact('owner', ArtifactCreate(id=first.id, version=1, title='Result', content='Stale'))
        with self.assertRaises(ValueError):
            store.save_artifact('other', ArtifactCreate(id=first.id, version=2, title='Result', content='Cross-chat'))

    async def test_device_read_scope_cannot_deliver_events_or_cross_conversations(self):
        grant = devices.issue(DeviceCreate(name='Viewer', scopes=['read', 'events'], session_ids=['owner']))
        devices.authorize(grant['token'], 'read', 'owner')
        for scope, sid in [('deliver_events', 'owner'), ('read', 'other')]:
            with self.assertRaises(ValueError):
                devices.authorize(grant['token'], scope, sid)
        devices.revoke(grant['device'].id)
        with self.assertRaises(ValueError):
            devices.authorize(grant['token'], 'read', 'owner')

    async def test_event_receipts_are_idempotent_and_scoped(self):
        for sid in ('owner', 'other'):
            wakes.create(sid, WakeCreate(prompt='Inspect result', topic='result-ready'))
        self.assertEqual(wakes.event('result-ready', 'event-1', 'device', {}, 'owner'), 1)
        self.assertEqual(wakes.event('result-ready', 'event-1', 'device', {}, 'owner'), 0)
        self.assertEqual(wakes.list_all('other')[0].status, 'scheduled')
        self.assertEqual(wakes.event('result-ready', 'event-1', 'device', {}, 'other'), 1)

    async def test_tool_composition_binds_results_and_stops_at_failure(self):
        calls = []
        async def invoke(name, args):
            calls.append((name, args))
            return ToolOutcome(name != 'fail', json.dumps({'value': 7}))
        context = ToolContext('owner', 'composition', lambda _: None, invoke=invoke)
        specs = [ToolSpec(name, name, {'type': 'object'}) for name in ('read', 'fail')]
        with patch.object(registry, 'catalog', return_value=specs):
            outcome = await tools.compose({'steps': [{'id': 'a', 'name': 'read', 'args': {}},
                {'id': 'b', 'name': 'fail', 'args': {'input': {'$result': 'a#/value'}}},
                {'id': 'c', 'name': 'read', 'args': {}}]}, context)
            self.assertFalse(outcome.ok)
            self.assertEqual(calls, [('read', {}), ('fail', {'input': 7})])
            with self.assertRaises(ToolFailure):
                await tools.compose({'steps': [{'id': 'a', 'name': 'read', 'args': {}},
                    {'id': 'b', 'name': 'read', 'args': {'input': {'$result': 'a#/missing'}}}]}, context)

    async def test_subagent_scope_forbids_recursive_or_ungranted_tools(self):
        specs = [ToolSpec(name, name, {'type': 'object'}) for name in ('read_file', 'delegate_task', 'run_tool_script')]
        with patch('studio.agent.tools.all_specs', return_value=specs):
            child = delegation.create('owner', DelegateCreate(objective='Inspect file', allowed_tools=['read_file']))
            with self.assertRaises(ValueError):
                registry.load(child.session_id, ['run_tool_script'], registry.catalog(child.session_id))
            with self.assertRaises(ValueError):
                delegation.create(child.session_id, DelegateCreate(objective='Delegate again'))
            with self.assertRaises(ValueError):
                delegation.create('owner', DelegateCreate(objective='Execute nested script', allowed_tools=['run_tool_script']))

    async def test_plugin_import_retains_sources_without_enabling_provider_hooks(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('.claude-plugin/plugin.json', json.dumps({'name': 'fixture', 'version': '1', 'hooks': {'command': 'must-not-run'}}))
            archive.writestr('skills/inspect/SKILL.md', '---\nname: inspect\ndescription: Inspect source\n---\nRead reference.txt and verify the result.')
            archive.writestr('skills/inspect/reference.txt', 'Recorded fixture fact')
        reviewed = plugins.inspect(data.getvalue())
        self.assertTrue(reviewed['warnings'])
        installed = plugins.install(reviewed)
        self.assertFalse(store.skill(installed['skill_ids'][0]).enabled)
        self.assertEqual(plugins.read_file('fixture', 'skills/inspect/reference.txt')['text'], 'Recorded fixture fact')
        with self.assertRaises(ValueError):
            plugins.read_file('fixture', '../studio.db')
        with self.assertRaises(ValueError):
            plugins.inspect(b'not a ZIP')

    async def test_connector_names_do_not_collide_when_truncated_or_normalized(self):
        names = [connectors.tool_name('fixture', 'a' * 100 + suffix) for suffix in ('x', 'y')]
        names += [connectors.tool_name('fixture', name) for name in ('a.b', 'a_b')]
        self.assertEqual(len(set(names)), 4)
        self.assertTrue(all(len(name) <= 64 for name in names))

    async def test_schema_loading_retains_a_bounded_recent_set(self):
        specs = [ToolSpec('fixture_' + str(i), 'Fixture', {'type': 'object'}) for i in range(40)]
        registry.load('owner', [s.name for s in specs[:30]], specs)
        registry.load('owner', [s.name for s in specs[30:]], specs)
        visible = registry.visible('owner', specs)
        self.assertEqual(len(visible), 30)
        self.assertTrue({s.name for s in specs[30:]} <= {s.name for s in visible})


if __name__ == '__main__':
    unittest.main()
