"""CPU-only integration coverage. Scripted providers never call a network model."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import agent_plus, agents, config, db
from studio.agent.loop import AgentService
from studio.agent.providers.base import Provider
from studio.agent.types import Call, Message, ModelInfo, StepEnd, ToolContext, ToolOutcome
from studio.agent import tools as agent_tools, web_tools
from studio.agent_plus import alternatives, learning, runner, store
from studio.agent_plus.controller import controller
from studio.agent_plus.provider import MissionProvider
from studio.agent_plus.tools import complete, evidence, invoke, reconcile, record
from studio.agent_plus.tools import artifact, plan, select, finish, status, context_records, supersede
from studio.routes import agent_plus as routes
from studio.schemas import AgentSession, EvToolResult
from studio.schemas_agent_plus import AgentPlusAmend, AgentPlusCreate, ChatCapability, MissionAction
from studio.workspace import state

INPUT = {"type": "object", "properties": {"csv": {"type": "string"}}, "required": ["csv"], "additionalProperties": False}
OUTPUT = {"type": "integer"}
GOOD = '''import csv, json
from pathlib import Path
def execute(args):
    total = sum(int(cell.strip()) for row in csv.reader([args["csv"]]) for cell in row if cell.strip())
    Path("report.json").write_text(json.dumps({"total": total}), encoding="utf-8")
    return total
'''
BAD = 'def execute(args):\n    return "wrong"\n'
REQUEST = {"name": "sum_csv", "task": "Sum signed CSV integers and write report.json", "input_schema": INPUT,
           "output_schema": OUTPUT, "acceptance": [{"args": {"csv": "1,2"}, "expected": 3},
               {"args": {"csv": "-5, 8"}, "expected": 3}], "source_urls": ["https://docs.python.org/3/library/csv.html"]}


class ScriptedProvider(Provider):
    async def info(self):
        return ModelInfo(context=128000)

    async def complete(self, system, prompt):
        return "CSV report"

    async def stream(self, system, history, tools):
        sid = ScriptedProvider.sid
        if "delegated research agent" in system:
            submissions = [m for m in history if m.role == "tool" and m.name == "submit_candidate"]
            if not any(m.name == "fetch_url" for m in history):
                call = Call("source", "fetch_url", {"url": "https://docs.python.org/3/library/csv.html"})
            else:
                call = Call("candidate" + str(len(submissions)), "submit_candidate", {
                    "code": GOOD if submissions else BAD,
                    "checks": [{"args": {"csv": ""}, "expected": 0},
                               {"args": {"csv": "abc"}, "error_contains": "ValueError"}],
                    "sources": ["https://docs.python.org/3/library/csv.html"], "limitations": "Signed integers only"})
        else:
            d = store.detail(sid)
            validated = [t for t in d.tools if t.status == "validated"]
            ids = {a.id for a in d.actions}
            if not validated:
                call = Call("research", "research_tool", REQUEST)
            elif "use1" not in ids:
                call = Call("use1", "invoke_chat_tool", {"tool_id": validated[-1].id, "args": {"csv": "7,-2,4"}})
            elif "use2" not in ids:
                call = Call("use2", "invoke_chat_tool", {"tool_id": validated[-1].id, "args": {"csv": "10,3"}})
            elif "artifact" not in ids:
                call = Call("artifact", "observe_artifact", {"path": str(config.OUTPUTS_DIR / "agentplus" / sid / "report.json")})
            elif not d.mission.criteria[0].evidence:
                call = Call("evidence", "record_evidence", {"criterion_id": d.mission.criteria[0].id,
                    "action_ids": ["use1", "use2", "artifact"], "explanation": "Both calls matched expected totals; report observed."})
            else:
                call = Call("finish", "complete_mission", {"result": "Created report.json with total 13; reused the tool twice."})
        yield StepEnd("", calls=[call])


class AgentPlusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(config, "DB_PATH", self.root / "studio.db"),
                        patch.object(config, "DATA_DIR", self.root),
                        patch.object(config, "CACHE_DIR", self.root / "cache"),
                        patch.object(config, "OUTPUTS_DIR", self.root / "outputs"),
                        patch("studio.agent.prompt.build", return_value="Use tools to perform the user's task."),
                        patch("studio.agent.tools.all_specs", return_value=web_tools.SPECS)]
        for p in self.patches:
            p.start()
        db.init()
        state.init()
        agent_plus.init()
        agents.init()
        self.service = AgentService()
        route_patch = patch.object(routes, "agent", self.service)
        route_patch.start()
        self.patches.append(route_patch)
        controller.start(self.service)
        db.set_setting_value("agent_auto_approve", ["run_python"])

    async def asyncTearDown(self):
        await controller.shutdown()
        await self.service.shutdown()
        if db._conn:
            db._conn.close()
            db._conn = None
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    async def mission(self):
        d = await routes.create(AgentPlusCreate(model="ollama:scripted", objective="Create a verified sum report",
            criteria=["Report sums signed CSV inputs correctly"]))
        ScriptedProvider.sid = d.mission.session_id
        return d.mission.session_id

    async def test_full_research_repair_reuse_artifact_completion(self):
        sid = await self.mission()
        provider = ScriptedProvider()
        async def source(args, ctx):
            return ToolOutcome(True, "csv.reader returns lists of strings; int parses signed integers. Official Python csv documentation.")
        with patch("studio.agent.loop.get_provider", return_value=provider), patch.object(learning, "get_provider", return_value=provider), \
             patch.dict(web_tools.IMPL, {"fetch_url": source}):
            await routes.resume(sid)
            await asyncio.wait_for(self.service._turns[sid].task, 45)
        d = store.detail(sid)
        self.assertEqual(d.mission.status, "completed")
        self.assertEqual([t.status for t in d.tools], ["failed", "validated"])
        self.assertTrue(all(x["passed"] for x in d.tools[-1].results))
        self.assertEqual(json.loads(store.action(sid, "use1").output)["value"], 9)
        self.assertEqual(json.loads(store.action(sid, 'use1').output)['_receipt_id'], 'use1')
        self.assertEqual(json.loads(store.action(sid, "use2").output)["value"], 13)
        first = json.loads(store.action(sid, 'use1').output)['artifacts'][0]
        second = json.loads(store.action(sid, 'use2').output)['artifacts'][0]
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(Path(first).read_text())['total'], 9)
        self.assertEqual(json.loads(Path(second).read_text())['total'], 13)
        self.assertEqual(json.loads((config.OUTPUTS_DIR / "agentplus" / sid / "report.json").read_text())["total"], 13)
        self.assertTrue(any(e.kind == "research.source" for e in d.events))
        self.assertTrue(d.mission.criteria[0].evidence)
        # This chat can reuse the validated revision after a requirement amendment.
        amended = await routes.amend(sid, AgentPlusAmend(version=1, objective="Another sum", criteria=["New total is correct"]))
        self.assertEqual(amended.mission.version, 2)
        self.assertEqual(len(amended.tools), 2)
        self.assertFalse(amended.mission.criteria[0].evidence)
        r = await invoke({"tool_id": d.tools[-1].id, "args": {"csv": "20,1"}}, ToolContext(sid, "reuse", lambda _: None))
        self.assertEqual(json.loads(r.output)["value"], 21)

    async def test_invalid_research_request_has_no_uncertain_effect(self):
        sid = await self.mission()
        malformed = {**REQUEST, 'acceptance': REQUEST['acceptance'] * 11}
        with self.assertRaisesRegex(ValueError, 'between 1 and 20'):
            await learning.research(malformed, ToolContext(sid, 'invalid', lambda _: None))
        store.save_action(sid, MissionAction(id='invalid', name='research_tool', args=malformed,
                                            status='running', created_at=db.now_iso()))
        controller.observe(sid, EvToolResult(call_id='invalid', ok=False, output='Supply between 1 and 20 concrete cases'))
        self.assertEqual(store.action(sid, 'invalid').status, 'failed')
        self.assertFalse(store.tools(sid))
        # Failure after a valid request remains uncertain: generated code might have run.
        store.save_action(sid, MissionAction(id='dispatched', name='research_tool', args=REQUEST,
                                            status='running', created_at=db.now_iso()))
        controller.observe(sid, EvToolResult(call_id='dispatched', ok=False, output='Research interrupted'))
        self.assertEqual(store.action(sid, 'dispatched').status, 'uncertain')

    async def test_research_can_challenge_an_oracle_without_changing_it(self):
        sid = await self.mission()
        class ConflictProvider(ScriptedProvider):
            async def stream(self, system, history, tools):
                request = json.loads(history[0].content)
                self_outer.assertEqual(request['authoritative_mission'], store.get(sid).objective)
                self_outer.assertEqual(request['delegated_request']['acceptance'], REQUEST['acceptance'])
                yield StepEnd('', calls=[Call('conflict', 'report_acceptance_conflict', {
                    'case_index': 0, 'explanation': 'Concrete fixed-oracle contradiction', 'corrected_expected_json': '4'})])
        self_outer = self
        store.save_action(sid, MissionAction(id='research-conflict', name='research_tool', args=REQUEST,
                                            status='running', created_at=db.now_iso()))
        m = store.get(sid); m.status = 'running'; store.save(m)
        with patch.object(learning, 'get_provider', return_value=ConflictProvider()):
            result = await learning.research(REQUEST, ToolContext(sid, 'research-conflict', lambda _: None))
        self.assertFalse(result.ok)
        self.assertEqual(json.loads(result.output)['proposed_expected'], 4)
        self.assertEqual(json.loads(result.output)['case']['expected'], 3)
        self.assertFalse(store.tools(sid))
        controller.observe(sid, EvToolResult(call_id='research-conflict', ok=False, output=result.output))
        self.assertEqual(store.action(sid, 'research-conflict').status, 'failed')
        self.assertEqual(store.get(sid).status, 'running')

    async def test_research_reserves_requests_for_construction(self):
        sid = await self.mission()
        self_outer = self
        class SourceLoopProvider(ScriptedProvider):
            async def stream(self, system, history, tools):
                names = {tool.name for tool in tools}
                if 'fetch_url' in names:
                    yield StepEnd('', calls=[Call('read', 'fetch_url', {'url': 'https://docs.python.org/3/library/csv.html'})])
                else:
                    self_outer.assertEqual(names, {'submit_candidate', 'report_acceptance_conflict'})
                    yield StepEnd('', calls=[Call('build', 'submit_candidate', {'code': GOOD,
                        'checks': [{'args': {'csv': ''}, 'expected': 0}], 'sources': [], 'limitations': 'Integer CSV only'})])
        m = store.get(sid); m.status = 'running'; store.save(m)
        async def source(args, ctx):
            return ToolOutcome(True, 'Official csv.reader documentation')
        with patch.object(learning, 'get_provider', return_value=SourceLoopProvider()), \
             patch.object(learning, 'MAX_RESEARCH_STEPS', 4), patch.dict(web_tools.IMPL, {'fetch_url': source}):
            result = await learning.research(REQUEST, ToolContext(sid, 'bounded-research', lambda _: None))
        self.assertTrue(result.ok)
        self.assertEqual(store.tools(sid)[-1].status, 'validated')

    async def test_repeated_learning_cannot_create_new_progress(self):
        sid = await self.mission()
        statement = {'kind': 'hypothesis', 'text': 'A different parser may solve the problem', 'action_ids': []}
        await record(statement, ToolContext(sid, 'first-learning', lambda _: None))
        result = await record(statement, ToolContext(sid, 'repeated-learning', lambda _: None))
        self.assertTrue(result.ok)
        self.assertIn('not new evidence', result.output)
        self.assertEqual(len([e for e in store.detail(sid).events if e.kind == 'learning']), 1)



    async def test_chat_scope_and_unvalidated_tool(self):
        sid = await self.mission()
        t = await self.make_tool(sid, BAD)
        with self.assertRaisesRegex(ValueError, "not passed validation"):
            await invoke({"tool_id": t.id, "args": {"csv": "1"}}, ToolContext(sid, "c", lambda _: None))
        other = (await routes.create(AgentPlusCreate(model="ollama:x", objective="Other", criteria=["Other"]))).mission.session_id
        with self.assertRaisesRegex(ValueError, "does not belong"):
            store.capability(other, t.id)

    async def make_tool(self, sid, code=GOOD):
        t = ChatCapability(id="testtool", session_id=sid, name="sum", description="sum", version=1, status="candidate",
            code=code, input_schema=INPUT, output_schema=OUTPUT, acceptance=learning.cases(REQUEST["acceptance"]),
            checks=learning.cases([{"args": {"csv": ""}, "expected": 0}]), code_hash=store.digest(code), created_at=db.now_iso())
        store.save_tool(t)
        return t

    async def test_validation_feedback_keeps_nested_mismatch_without_fixture_bulk(self):
        sid = await self.mission()
        t = await self.make_tool(sid)
        rows = [{'id': i, 'label': 'x' * 200} for i in range(500)]
        expected = {'rows': rows, 'audit': {'tag_counts': {'a': 1}}}
        actual = {'rows': rows, 'audit': {'tag_counts': {'a': 2}}}
        t.acceptance = learning.cases([{'args': {'rows': rows}, 'expected': expected}])
        t.checks = []
        t.results = [{'passed': False, 'source': 'acceptance', 'actual': actual, 'error': None}]
        before = t.model_dump_json()
        feedback = learning.validation_feedback(t)
        self.assertLess(len(json.dumps(feedback)), 1500)
        self.assertEqual(feedback['failed_cases'][0]['differences'],
                         [{'path': '$.audit.tag_counts.a', 'expected': 1, 'actual': 2}])
        self.assertEqual(before, t.model_dump_json())

    async def test_revision_immutable_and_schema_enforced(self):
        sid = await self.mission()
        t = await self.make_tool(sid)
        t.code = BAD
        with self.assertRaisesRegex(ValueError, "immutable"):
            store.save_tool(t)
        with self.assertRaisesRegex(ValueError, "missing"):
            runner.check_schema({}, INPUT)
        with self.assertRaisesRegex(ValueError, "expected integer"):
            runner.check_schema(True, OUTPUT)

    async def test_completion_needs_real_receipts_and_no_unknown_effect(self):
        sid = await self.mission()
        ctx = ToolContext(sid, "complete", lambda _: None)
        with self.assertRaises(ValueError):
            await complete({"result": "Done"}, ctx)
        store.save_action(sid, MissionAction(id="real", name="read_file", args={}, status="succeeded", output="data", created_at=db.now_iso()))
        await evidence({"criterion_id": store.get(sid).criteria[0].id, "action_ids": ["real"], "explanation": "observed"}, ctx)
        store.save_action(sid, MissionAction(id="unknown", name="run_command", args={}, status="uncertain", created_at=db.now_iso()))
        with self.assertRaisesRegex(ValueError, "unresolved"):
            await complete({"result": "Done"}, ctx)
        store.save_action(sid, MissionAction(id="later", name="read_file", args={}, status="succeeded", output="done", created_at=db.now_iso()))
        await reconcile({"action_id": "unknown", "observation_action_id": "later", "explanation": "Effect observed"}, ctx)
        self.assertTrue((await complete({"result": "Done"}, ctx)).ok)

    async def test_restart_preserves_tools_and_marks_unknown_actions(self):
        sid = await self.mission()
        t = await self.make_tool(sid)
        await learning.validate(t)
        m = store.get(sid)
        m.status = "running"
        store.save(m)
        store.save_action(sid, MissionAction(id="interrupted", name="run_command", args={}, status="running", created_at=db.now_iso()))
        store.recover()
        self.assertEqual(store.get(sid).status, "paused")
        self.assertEqual(store.action(sid, "interrupted").status, "uncertain")
        self.assertEqual(store.capability(sid, t.id).status, "validated")
        self.assertIsNotNone(agent_plus.tools.profile(sid).gate("invoke_chat_tool", {}, False))

    async def test_timeout_and_failed_runtime_degrade_revision(self):
        sid = await self.mission()
        r = await runner.invoke("def execute(args):\n    while True: pass", {}, sid, timeout=0.3)
        self.assertFalse(r["ok"])
        self.assertIn("timed out", r["error"])
        t = await self.make_tool(sid)
        await learning.validate(t)
        r = await invoke({"tool_id": t.id, "args": {"csv": "bad"}}, ToolContext(sid, "c", lambda _: None))
        self.assertFalse(r.ok)
        self.assertEqual(store.capability(sid, t.id).status, "failed")

    async def test_permission_denial_never_executes_research(self):
        sid = await self.mission()
        db.set_setting_value("agent_auto_approve", [])
        with patch("studio.agent.loop.get_provider", return_value=ScriptedProvider()), \
             patch.object(learning, "research", side_effect=AssertionError("must not execute")):
            await routes.resume(sid)
            turn = self.service._turns[sid]
            for _ in range(100):
                if turn.approvals:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(self.service.approve(sid, "research", False))
            await asyncio.wait_for(turn.task, 5)
        self.assertFalse(store.tools(sid))
        self.assertEqual(store.get(sid).status, "blocked")

    async def test_profile_refusal_never_records_a_dispatched_effect(self):
        sid = await self.mission()
        class RefusedProvider(ScriptedProvider):
            async def stream(self, system, history, tools):
                yield StepEnd('', calls=[Call('refused', 'run_command', {'command': 'unused'})])
        with patch('studio.agent.loop.get_provider', return_value=RefusedProvider()):
            await routes.resume(sid)
            await asyncio.wait_for(self.service._turns[sid].task, 5)
        self.assertEqual(store.get(sid).status, 'blocked')
        self.assertFalse(store.actions(sid))

    async def test_zero_budget_blocks_remote_before_request(self):
        sid = await self.mission()
        db.update_session(sid, model="openrouter:paid")
        m = store.get(sid)
        m.status = "running"
        store.save(m)
        with self.assertRaisesRegex(Exception, "budget"):
            async for _ in MissionProvider(ScriptedProvider(), sid).stream("", [Message("user", "x")], []):
                self.fail("Remote provider should not be reached")
        self.assertEqual(store.get(sid).requests, 0)

    async def test_inactive_compaction_still_consumes_request_budget(self):
        sid = await self.mission()
        m = store.get(sid)
        m.status = 'completed'
        store.save(m)
        class CompactProvider(ScriptedProvider):
            async def stream(self, system, history, tools):
                yield StepEnd('Compact summary', calls=[])
        text = await MissionProvider(CompactProvider(), sid, allow_inactive=True).complete('Summarize', 'history')
        self.assertEqual(text, 'Compact summary')
        self.assertEqual(store.get(sid).requests, 1)
        self.assertEqual(store.get(sid).status, 'completed')

    async def test_compact_status_never_repeats_previous_status_output(self):
        sid = await self.mission()
        ctx = ToolContext(sid, 'status', lambda _: None)
        initial = await status({}, ctx)
        for i in range(8):
            store.save_action(sid, MissionAction(id=f'status{i}', name='mission_status', args={}, status='succeeded',
                output=initial.output * 100, created_at=db.now_iso()))
        result = await status({}, ctx)
        self.assertEqual(json.loads(result.output)['actions'], [])
        self.assertEqual(len(initial.output), len(result.output))
        store.save_action(sid, MissionAction(id='exact', name='read_file', args={}, status='succeeded',
            output='Exact raw evidence', created_at=db.now_iso()))
        retrieved = await context_records({'action_ids': ['exact']}, ctx)
        self.assertIn('Exact raw evidence', retrieved.output)

    async def test_fresh_alternative_is_hypothesis_and_preserves_requirements(self):
        sid = await self.mission()
        m = store.get(sid)
        m.status = 'running'
        store.save(m)
        store.save_action(sid, MissionAction(id='failed', name='fetch_url', args={}, status='failed',
            output='Missing documentation endpoint', created_at=db.now_iso()))
        class AlternativeProvider(ScriptedProvider):
            async def stream(self, system, history, tools):
                self.packet = json.loads(history[0].content)
                yield StepEnd(json.dumps({'changed_assumption': 'Documentation endpoint is unavailable',
                    'mechanism': 'Read the installed library source', 'distinguishing_test': 'Import fixture on local data',
                    'next_action': 'Find the installed source', 'limitation': 'May differ from hosted API'}), calls=[])
        provider = AlternativeProvider()
        with patch.object(alternatives, 'get_provider', return_value=provider):
            result = await alternatives.propose({'obstacle': 'Docs failed', 'action_ids': ['failed']}, ToolContext(sid, 'alternative', lambda _: None))
        self.assertTrue(result.ok)
        self.assertEqual(provider.packet['objective'], m.objective)
        self.assertNotIn('plan', provider.packet)
        self.assertEqual(store.detail(sid).events[-1].data['kind'], 'hypothesis')
        self.assertEqual(store.get(sid).requests, 1)

    async def test_stale_amendment_and_unchanged_criteria(self):
        sid = await self.mission()
        original = store.get(sid)
        await routes.amend(sid, AgentPlusAmend(version=1, objective="Updated", criteria=[c.text for c in original.criteria]))
        self.assertEqual(store.get(sid).criteria[0].id, original.criteria[0].id)
        with self.assertRaises(Exception) as ctx:
            await routes.amend(sid, AgentPlusAmend(version=1, objective="Stale", criteria=["new"]))
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_transaction_rolls_back_state_and_history_together(self):
        sid = await self.mission()
        original = store.get(sid)
        before = len(store.detail(sid).events)
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            with store.atomic():
                m = store.get(sid)
                m.objective = 'Uncommitted change'
                store.save(m)
                store.event(sid, 'amended', 'Uncommitted change')
                raise RuntimeError('interrupted')
        self.assertEqual(store.get(sid).objective, original.objective)
        self.assertEqual(len(store.detail(sid).events), before)

    async def test_user_can_adjust_resources_without_erasing_spending(self):
        sid = await self.mission()
        m = store.get(sid)
        m.requests, m.cost = 80, 0.5
        store.save(m)
        result = await routes.amend(sid, AgentPlusAmend(version=1, objective=m.objective,
            criteria=[c.text for c in m.criteria], max_requests=10, max_cost=2))
        self.assertEqual(result.mission.requests, 0)
        self.assertEqual(result.mission.max_requests, 10)
        self.assertEqual(result.mission.max_cost, 2)
        self.assertEqual(result.mission.cost, 0.5)

    async def test_dependency_order_cycles_and_downstream_invalidation(self):
        sid = await self.mission()
        ctx = ToolContext(sid, 'graph', lambda _: None)
        items = [{'id': 'build', 'kind': 'delivery', 'objective': 'Build report', 'dependencies': []},
                 {'id': 'check', 'kind': 'validation', 'objective': 'Check report', 'dependencies': ['build']}]
        await plan({'items': items}, ctx)
        with self.assertRaisesRegex(ValueError, 'Dependencies'):
            await select({'work_id': 'check'}, ctx)
        with self.assertRaisesRegex(ValueError, 'cycle'):
            await plan({'items': [{**items[0], 'dependencies': ['check']}]}, ctx)
        await select({'work_id': 'build'}, ctx)
        store.save_action(sid, MissionAction(id='report', name='read_file', args={}, status='succeeded', output='report', created_at=db.now_iso()))
        await finish({'work_id': 'build', 'action_ids': ['report']}, ctx)
        await select({'work_id': 'check'}, ctx)
        await finish({'work_id': 'check', 'action_ids': ['report']}, ctx)
        await evidence({'criterion_id': store.get(sid).criteria[0].id, 'action_ids': ['report'], 'explanation': 'checked'}, ctx)
        await plan({'items': [{**items[0], 'objective': 'Build changed report'}]}, ctx)
        self.assertEqual([w.status for w in store.work(sid)], ['pending', 'pending'])
        self.assertFalse(store.get(sid).criteria[0].evidence)

    async def test_replacement_branch_preserves_history_and_invalidates_old_evidence(self):
        sid = await self.mission()
        ctx = ToolContext(sid, 'graph', lambda _: None)
        await plan({'items': [
            {'id': 'old', 'kind': 'delivery', 'objective': 'Old implementation', 'dependencies': []},
            {'id': 'oldcheck', 'kind': 'validation', 'objective': 'Old test', 'dependencies': ['old']},
            {'id': 'replacement', 'kind': 'delivery', 'objective': 'Different implementation', 'dependencies': []}]}, ctx)
        await select({'work_id': 'old'}, ctx)
        store.save_action(sid, MissionAction(id='oldreceipt', name='read_file', args={}, status='succeeded', output='old result', created_at=db.now_iso()))
        await finish({'work_id': 'old', 'action_ids': ['oldreceipt']}, ctx)
        await evidence({'criterion_id': store.get(sid).criteria[0].id, 'action_ids': ['oldreceipt'], 'explanation': 'old result'}, ctx)
        with self.assertRaisesRegex(ValueError, 'independent'):
            await supersede({'work_ids': ['old'], 'replacement_ids': ['oldcheck'], 'reason': 'Different mechanism'}, ctx)
        await supersede({'work_ids': ['old'], 'replacement_ids': ['replacement'], 'reason': 'Observed incompatibility'}, ctx)
        work = {w.id: w for w in store.work(sid)}
        self.assertEqual(work['old'].status, 'superseded')
        self.assertEqual(work['oldcheck'].status, 'superseded')
        self.assertEqual(work['old'].superseded_reason, 'Observed incompatibility')
        self.assertFalse(store.get(sid).criteria[0].evidence)
        self.assertEqual(store.action(sid, 'oldreceipt').output, 'old result')
        self.assertTrue((await select({'work_id': 'replacement'}, ctx)).ok)

    async def test_capability_build_work_can_use_validated_research_but_mission_cannot(self):
        sid = await self.mission()
        ctx = ToolContext(sid, 'graph', lambda _: None)
        t = await self.make_tool(sid)
        await learning.validate(t)
        await plan({'items': [{'id': 'build', 'kind': 'learning', 'objective': 'Build missing tool', 'dependencies': []}]}, ctx)
        await select({'work_id': 'build'}, ctx)
        store.save_action(sid, MissionAction(id='research-result', name='research_tool', args={}, status='succeeded',
            output=json.dumps({'tool_id': t.id}), created_at=db.now_iso()))
        self.assertTrue((await finish({'work_id': 'build', 'action_ids': ['research-result']}, ctx)).ok)
        with self.assertRaisesRegex(ValueError, 'self-declared'):
            await evidence({'criterion_id': store.get(sid).criteria[0].id, 'action_ids': ['research-result'], 'explanation': 'checks passed'}, ctx)

    async def test_control_receipts_cannot_prove_an_outcome(self):
        sid = await self.mission()
        ctx = ToolContext(sid, 'check', lambda _: None)
        for name in ('plan_work', 'select_work', 'finish_work', 'resolve_action', 'research_tool'):
            store.save_action(sid, MissionAction(id=name, name=name, args={}, status='succeeded', output='done', created_at=db.now_iso()))
            with self.assertRaisesRegex(ValueError, 'self-declared'):
                await evidence({'criterion_id': store.get(sid).criteria[0].id, 'action_ids': [name], 'explanation': 'done'}, ctx)

    async def test_deleted_artifact_invalidates_completion_evidence(self):
        sid = await self.mission()
        path = config.OUTPUTS_DIR / 'proof.txt'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('first')
        ctx = ToolContext(sid, 'check', lambda _: None)
        observed = await artifact({'path': str(path)}, ctx)
        store.save_action(sid, MissionAction(id='proof', name='observe_artifact', args={'path': str(path)},
            status='succeeded', output=observed.output, created_at=db.now_iso()))
        await evidence({'criterion_id': store.get(sid).criteria[0].id, 'action_ids': ['proof'], 'explanation': 'observed'}, ctx)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'disappeared'):
            await complete({'result': 'done'}, ctx)
        self.assertFalse(store.get(sid).criteria[0].evidence)

    async def test_cancelled_research_does_not_promote_candidate(self):
        sid = await self.mission()
        m = store.get(sid)
        m.status = 'running'
        store.save(m)
        class CandidateProvider(ScriptedProvider):
            async def stream(self, system, history, tools):
                yield StepEnd('', calls=[Call('submit', 'submit_candidate', {'code': GOOD,
                    'checks': [{'args': {'csv': ''}, 'expected': 0}], 'sources': [], 'limitations': ''})])
        checking = asyncio.Event()
        async def slow_validate(t):
            checking.set()
            await asyncio.Future()
        with patch.object(learning, 'get_provider', return_value=CandidateProvider()), patch.object(learning, 'validate', side_effect=slow_validate):
            task = asyncio.create_task(learning.research(REQUEST, ToolContext(sid, 'research', lambda _: None)))
            await asyncio.wait_for(checking.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual([t.status for t in store.tools(sid)], ['failed'])

    async def test_changed_artifact_invalidates_completion_evidence(self):
        sid = await self.mission()
        path = config.OUTPUTS_DIR / 'proof.txt'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('first')
        ctx = ToolContext(sid, 'check', lambda _: None)
        observed = await artifact({'path': str(path)}, ctx)
        store.save_action(sid, MissionAction(id='proof', name='observe_artifact', args={'path': str(path)},
            status='succeeded', output=observed.output, created_at=db.now_iso()))
        await evidence({'criterion_id': store.get(sid).criteria[0].id, 'action_ids': ['proof'], 'explanation': 'observed'}, ctx)
        path.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            await complete({'result': 'done'}, ctx)
        self.assertFalse(store.get(sid).criteria[0].evidence)

    async def test_sequential_continuation_after_plain_response(self):
        sid = await self.mission()
        class Continuing(ScriptedProvider):
            count = 0
            async def stream(self, system, history, tools):
                self.count += 1
                if self.count == 1:
                    yield StepEnd('I need another step.', calls=[])
                else:
                    m = store.get(sid)
                    m.status, m.reason = 'completed', 'Continuation reached'
                    store.save(m)
                    yield StepEnd('Finished.', calls=[])
        provider = Continuing()
        db.set_setting_value('agent_completion_check', 'never')
        with patch('studio.agent.loop.get_provider', return_value=provider):
            await routes.resume(sid)
            for _ in range(100):
                if store.get(sid).status == 'completed' and not self.service.busy(sid):
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(store.get(sid).status, 'completed')
            self.assertEqual(provider.count, 2)


if __name__ == "__main__":
    unittest.main()
