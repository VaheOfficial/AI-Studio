"""Mission controls and generated tools, available only to Agent+ sessions."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from typing import Any

from .. import config, db
from ..agent import profiles, prompt
from ..agent.types import Call, ModelInfo, ToolContext, ToolOutcome, ToolSpec
from ..schemas_workspace import FileArtifact, PythonDisplay
from ..schemas_agent_plus import AcceptanceCase, MissionWork
from ..workspace import state as workspace_state
from . import alternatives, learning, runner, store
from .controller import READ_ONLY, controller, is_read_only
from .provider import MissionProvider

S = {"type": "string"}
O = {"type": "object"}
A = {"type": "array", "items": S}
CONTROLS = {'mission_status', 'mission_context', 'record_evidence', 'record_learning', 'complete_mission',
            'search_tools', 'load_tools', 'start_mission', 'research_tool', 'plan_work', 'select_work', 'finish_work', 'supersede_work', 'resolve_action', 'propose_alternative'}

SPECS = [
    ToolSpec("plan_work", "Add or revise the mission's dependency graph. Items need id, kind (delivery, learning, "
             "alternative, validation), objective and dependencies. Runtime checks cycles and references. Existing "
             "done items retain evidence only if their objective and dependencies stay unchanged.",
             learning.obj({"items": {"type": "array", "items": learning.obj({'id': S,
                 'kind': {'type': 'string', 'enum': ['delivery', 'learning', 'alternative', 'validation']},
                 'objective': S, 'dependencies': A})}})),
    ToolSpec("select_work", "Select the one next work item. Dependencies must be done; only one item runs at once.",
             learning.obj({"work_id": S})),
    ToolSpec('supersede_work', 'Replace a failing branch without deleting its history. First plan distinct replacement '
             'items, then provide old work_ids, replacement_ids and a factual reason. Dependent old work and its '
             'criterion evidence are invalidated. Replacement items must not depend on the superseded branch.',
             learning.obj({'work_ids': A, 'replacement_ids': A, 'reason': S})),
    ToolSpec("finish_work", "Complete the current work item using _receipt_id values returned by successful "
             "actions, not criterion IDs or tool IDs. A validated research receipt can finish capability-building "
             "work; validation work needs an actual invocation or environment observation.",
             learning.obj({"work_id": S, "action_ids": A})),
    ToolSpec("mission_status", "Read the current mission, acceptance criteria, action receipts and chat tools.", learning.obj({})),
    ToolSpec('mission_context', 'Retrieve exact action receipts, tool source, or work items by ID, or search retained '
             'event text. Use this after the compact mission_status identifies a needed record. Response is bounded '
             'and reports omitted records. Prior status responses are never included as evidence.',
             learning.obj({'action_ids': A, 'tool_id': S, 'work_ids': A, 'query': S}, [])),
    ToolSpec('propose_alternative', 'Ask a fresh reasoning context for a materially different approach to an '
             'obstacle. Supply the obstacle and actual failed/observation receipts. Returns a changed assumption, '
             'mechanism, distinguishing test and next action; these are hypotheses to test, not outcome evidence.',
             learning.obj({'obstacle': S, 'action_ids': A})),
    ToolSpec("research_tool", "Delegate one missing capability to a research agent while you wait. It reads "
             "documentation/source, builds Python execute(args), tests fixed acceptance and distinct edge cases, "
             "and repairs up to six revisions. Code executes locally with run_python permissions. Supply concrete "
             "1 to 20 concrete JSON input and EXACT expected output cases BEFORE delegation. Ensure each oracle "
             "matches the mission contract and the complete output schema. Use fixtures for effects. Validated tools "
             "stay in this chat only. Inspect actual results before accepting mission criteria.",
             learning.obj({"name": S, "task": S, "input_schema": O, "output_schema": O,
                           "acceptance": {"type": "array", "minItems": 1, "maxItems": 20,
                                          "items": AcceptanceCase.model_json_schema()}, "source_urls": A},
                          ["name", "task", "input_schema", "output_schema", "acceptance"]),
             needs_approval=True, asks_like=lambda _: "run_python"),
    ToolSpec("invoke_chat_tool", "Call a validated tool from this chat with JSON args. Runs a fresh Python process "
             "with a 30 second deadline. Failed calls remove that revision from service; an older validated revision "
             "remains available. Execution uses run_python permissions.",
             learning.obj({"tool_id": S, "args": O}), needs_approval=True, asks_like=lambda _: "run_python"),
    ToolSpec("record_evidence", "Accept one mission criterion using successful action receipt IDs in this chat. "
             "Inspect the actual result first; a research tool's unit checks alone do not prove the user's outcome.",
             learning.obj({"criterion_id": S, "action_ids": A, "explanation": S})),
    ToolSpec("complete_mission", "Finish only when every criterion has successful evidence and no uncertain action "
             "remains. Provide the deliverable/result for the user.", learning.obj({"result": S})),
    ToolSpec("record_learning", "Persist a factual observation, failed assumption or next alternative with its "
             "source action IDs. This survives compaction; distinguish observations from hypotheses.",
             learning.obj({"kind": {"type": "string", "enum": ["observation", "hypothesis", "alternative"]},
                           "text": S, "action_ids": A})),
    ToolSpec("resolve_action", "After inspecting an uncertain action's real outcome, reconcile it using a "
             "successful later observation receipt. Never blindly retry a possible external effect.",
             learning.obj({"action_id": S, "observation_action_id": S, "explanation": S})),
    ToolSpec("observe_artifact", "Inspect a workspace or output file and retain its content hash and metadata "
             "as evidence. Files outside these roots are not accepted.", learning.obj({"path": S})),
]


async def status(_: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    d = store.detail(ctx.session_id)
    m = d.mission
    actions = [a for a in d.actions if a.name not in CONTROLS][-12:]
    packet = {'mission': {'objective': m.objective, 'version': m.version, 'status': m.status, 'reason': m.reason,
                         'criteria': [c.model_dump() for c in m.criteria], 'requests_remaining': m.max_requests - m.requests},
              'work': [w.model_dump() for w in d.work][:12], 'work_omitted': max(0, len(d.work)-12),
              'tools': [{'id': t.id, 'name': t.name, 'version': t.version, 'status': t.status,
                         'input_schema': t.input_schema, 'limitations': t.limitations} for t in d.tools[-8:]],
              'tools_omitted': max(0, len(d.tools)-8),
              'actions': [{'id': a.id, 'name': a.name, 'status': a.status, 'output_excerpt': (a.output or '')[:600]}
                          for a in actions], 'details': 'Use mission_context for exact receipts/source. Execute the next eligible work item.'}
    return ToolOutcome(True, json.dumps(packet, ensure_ascii=False))


async def context_records(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    selected: dict[str, Any] = {}
    if a.get('action_ids'):
        records = [store.action(ctx.session_id, aid) for aid in a['action_ids'][:10]]
        selected['actions'] = [r.model_dump() for r in records if r.name not in ('mission_status', 'mission_context')]
    if a.get('tool_id'):
        selected['tool'] = store.capability(ctx.session_id, a['tool_id']).model_dump()
    if a.get('work_ids'):
        selected['work'] = [w.model_dump() for w in store.work(ctx.session_id) if w.id in a['work_ids'][:10]]
    if a.get('query'):
        rows = store.search_events(ctx.session_id, str(a['query']))
        selected['events'] = rows
    raw = json.dumps(selected, ensure_ascii=False)
    return ToolOutcome(True, json.dumps({'records_json': raw[:24000], 'truncated': len(raw) > 24000,
        'requested_action_ids_omitted': max(0, len(a.get('action_ids', [])) - 10)}, ensure_ascii=False))


async def plan(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    if not isinstance(a['items'], list) or not 1 <= len(a['items']) <= 50:
        raise ValueError('Supply 1 to 50 work items')
    old = {w.id: w for w in store.work(ctx.session_id)}
    proposed = [MissionWork.model_validate({**raw, 'status': 'pending', 'evidence': []}) for raw in a['items']]
    if len({w.id for w in proposed}) != len(proposed):
        raise ValueError('Work IDs must be unique')
    merged = dict(old)
    for w in proposed:
        prior = old.get(w.id)
        if prior and (w.objective, w.dependencies, w.kind) == (prior.objective, prior.dependencies, prior.kind):
            w.status, w.evidence = prior.status, prior.evidence
        merged[w.id] = w
    visited, visiting = set(), set()
    def visit(wid: str) -> None:
        if wid not in merged:
            raise ValueError('Unknown work dependency: ' + wid)
        if wid in visiting:
            raise ValueError('Work dependencies contain a cycle')
        if wid in visited:
            return
        visiting.add(wid)
        for dep in merged[wid].dependencies:
            visit(dep)
        visiting.remove(wid)
        visited.add(wid)
    for wid in merged:
        visit(wid)
    # Changed inputs invalidate downstream work recursively.
    changed = {w.id for w in proposed if w.id in old and
               (w.objective, w.dependencies, w.kind) != (old[w.id].objective, old[w.id].dependencies, old[w.id].kind)}
    while True:
        affected = {w.id for w in merged.values() if set(w.dependencies) & changed} - changed
        if not affected:
            break
        changed |= affected
    invalid_evidence = {aid for wid in changed for aid in old.get(wid, merged[wid]).evidence}
    for wid in changed:
        merged[wid].status, merged[wid].evidence = 'pending', []
    if invalid_evidence:
        m = store.get(ctx.session_id)
        for criterion in m.criteria:
            if invalid_evidence.intersection(criterion.evidence):
                criterion.evidence = []
        store.save(m)
    store.save_work(ctx.session_id, list(merged.values()))
    store.event(ctx.session_id, 'plan', 'Work graph updated.', {'items': [w.model_dump() for w in merged.values()]})
    return ToolOutcome(True, 'Work graph updated. Select an eligible next item.')


async def select(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    items = store.work(ctx.session_id)
    selected = next((w for w in items if w.id == a['work_id']), None)
    if selected is None or selected.status in ('done', 'superseded'):
        raise ValueError('Select an unfinished work item')
    if any(w.status == 'running' and w.id != selected.id for w in items):
        raise ValueError('Finish the current item before selecting another')
    if any(not any(w.id == dep and w.status == 'done' for w in items) for dep in selected.dependencies):
        raise ValueError('Dependencies are not complete')
    selected.status = 'running'
    store.save_work(ctx.session_id, [selected])
    return ToolOutcome(True, selected.objective)


async def supersede(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    items = {w.id: w for w in store.work(ctx.session_id)}
    old, replacements = set(a['work_ids']), set(a['replacement_ids'])
    if not old or not replacements or not str(a['reason']).strip() or (old | replacements) - items.keys():
        raise ValueError('Name existing old and replacement work items and a reason')
    changed = set(old)
    while True:
        affected = {w.id for w in items.values() if set(w.dependencies) & changed} - changed
        if not affected:
            break
        changed |= affected
    if changed & replacements or any(items[r].status in ('done', 'superseded') for r in replacements):
        raise ValueError('Replacements must be unfinished and independent of the superseded branch')
    invalid = {aid for wid in changed for aid in items[wid].evidence}
    for wid in changed:
        items[wid].status, items[wid].evidence = 'superseded', []
        items[wid].superseded_reason = str(a['reason'])
    mission = store.get(ctx.session_id)
    for criterion in mission.criteria:
        if invalid.intersection(criterion.evidence):
            criterion.evidence = []
    with store.atomic():
        store.save_work(ctx.session_id, [items[wid] for wid in changed])
        store.save(mission)
        store.event(ctx.session_id, 'alternative.adopted', a['reason'],
                    {'superseded': sorted(changed), 'replacements': sorted(replacements)})
    return ToolOutcome(True, 'Old branch retained as superseded. Select an eligible replacement and test it.')


async def finish(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    item = next((w for w in store.work(ctx.session_id) if w.id == a['work_id']), None)
    if item is None or item.status != 'running':
        raise ValueError('Only the current running item can finish')
    evidence_actions(ctx.session_id, a['action_ids'], allow_capability=item.kind != 'validation')
    item.status, item.evidence = 'done', a['action_ids']
    store.save_work(ctx.session_id, [item])
    store.event(ctx.session_id, 'evidence', 'Work completed: ' + item.objective, {'work_id': item.id, 'actions': item.evidence})
    return ToolOutcome(True, 'Work item completed')


async def invoke(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    t = store.capability(ctx.session_id, a["tool_id"])
    if t.status != "validated" or store.digest(t.code) != t.code_hash:
        raise ValueError("This tool revision has not passed validation")
    runner.check_schema(a["args"], t.input_schema, "args")
    result = await runner.invoke(t.code, a["args"], ctx.session_id)
    if result.get("ok"):
        try:
            runner.check_schema(result.get("value"), t.output_schema, "result")
        except ValueError as exc:
            result = {"ok": False, "error": str(exc)}
    if not result.get("ok"):
        t.status = "failed"
        store.save_tool(t)
    store.event(ctx.session_id, "tool.outcome", f"{t.name} revision {t.version}: "
                + ("succeeded" if result.get("ok") else "failed"), {"tool_id": t.id, "result": result})
    files = [FileArtifact(name=p.name, path=str(p), size=p.stat().st_size,
             url="/files/" + quote(p.relative_to(config.DATA_DIR).as_posix()))
             for p in (Path(f) for f in result.get("artifacts", [])) if config.DATA_DIR in p.parents and p.is_file()]
    return ToolOutcome(result.get("ok") is True, json.dumps(result, ensure_ascii=False),
        display=PythonDisplay(code='', output=json.dumps(result.get("value"), ensure_ascii=False),
                              error=result.get("error"), files=files))


def evidence_actions(sid: str, ids: list[str], allow_capability: bool = False) -> None:
    if not isinstance(ids, list) or not ids:
        raise ValueError("Supply at least one successful action receipt")
    for aid in ids:
        a = store.action(sid, aid)
        if allow_capability and a.name == 'research_tool' and a.status == 'succeeded':
            result = json.loads(a.output or '{}')
            capability = store.capability(sid, result.get('tool_id', ''))
            if capability.status == 'validated' and capability.results and all(r['passed'] for r in capability.results):
                continue
        if a.status != "succeeded" or a.name in CONTROLS:
            raise ValueError("Evidence must refer to a successful task result or observation, not a self-declared verdict")


async def evidence(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    evidence_actions(ctx.session_id, a["action_ids"])
    m = store.get(ctx.session_id)
    criterion = next((c for c in m.criteria if c.id == a["criterion_id"]), None)
    if criterion is None:
        raise ValueError("Criterion does not belong to the current mission version")
    criterion.evidence = list(dict.fromkeys(a["action_ids"]))
    with store.atomic():
        store.save(m)
        store.event(ctx.session_id, "evidence", a["explanation"], {"criterion_id": criterion.id, "actions": criterion.evidence})
    return ToolOutcome(True, f"Evidence recorded for: {criterion.text}")


async def complete(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    m = store.get(ctx.session_id)
    if any(w.kind in ('delivery', 'validation') and w.status not in ('done', 'superseded') for w in store.work(ctx.session_id)):
        raise ValueError('Delivery and validation work must finish before the mission completes')
    for c in m.criteria:
        evidence_actions(ctx.session_id, c.evidence)
        for aid in c.evidence:
            receipt = store.action(ctx.session_id, aid)
            if receipt.name in ('artifact_save', 'artifact_read'):
                recorded = json.loads(receipt.output or '{}')
                from ..agents.store import artifact as read_artifact
                try:
                    current = read_artifact(recorded['id'])
                    changed = current.content_hash != recorded['content_hash']
                except (ValueError, KeyError, TypeError):
                    changed = True
                if changed:
                    c.evidence = []
                    store.save(m)
                    raise ValueError('An evidenced artifact was revised; inspect and validate its current revision')
            if receipt.name == "observe_artifact":
                recorded = json.loads(receipt.output or "{}")
                try:
                    observed = await artifact({"path": recorded["path"]}, ctx)
                    changed = json.loads(observed.output)["sha256"] != recorded["sha256"]
                except (ValueError, OSError):
                    changed = True
                if changed:
                    c.evidence = []
                    store.save(m)
                    raise ValueError("An evidenced artifact changed or disappeared; inspect and validate it again")
    if any(x.status in ("uncertain", "running") and x.id != ctx.call_id for x in store.actions(ctx.session_id)):
        raise ValueError("Inspect and reconcile unresolved actions before completing")
    m.status, m.reason = "completed", a["result"]
    with store.atomic():
        store.save(m)
        store.event(ctx.session_id, "completed", a["result"])
    return ToolOutcome(True, a["result"])


async def record(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    store.get(ctx.session_id)
    for aid in a["action_ids"]:
        store.action(ctx.session_id, aid)
    if a["kind"] == "observation" and not a["action_ids"]:
        raise ValueError("An observation needs its source receipts; use hypothesis for an untested idea")
    if any(e['kind'] == 'learning' and e['text'] == a['text'] and e['data'].get('kind') == a['kind']
           for e in store.search_events(ctx.session_id, a['text'])):
        return ToolOutcome(True, 'This learning is already recorded; it is not new evidence. '
                           'Execute the next eligible work item rather than repeat the observation.')
    store.event(ctx.session_id, "learning", a["text"], {"kind": a["kind"], "actions": a["action_ids"]})
    return ToolOutcome(True, "Saved for this chat")


async def reconcile(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    old = store.action(ctx.session_id, a["action_id"])
    observation = store.action(ctx.session_id, a["observation_action_id"])
    if old.status != "uncertain" or observation.status != "succeeded" or not is_read_only(observation.name, observation.args):
        raise ValueError("Reconciliation needs an uncertain action and a successful read-only observation")
    if observation.created_at < old.created_at or observation.id == old.id:
        raise ValueError("Inspect after the uncertain action")
    if observation.name in CONTROLS:
        raise ValueError("Use an actual environment observation")
    old.status = "resolved"
    old.output = (old.output or "") + "\nReconciled: " + a["explanation"]
    store.save_action(ctx.session_id, old)
    store.event(ctx.session_id, "reconciled", a["explanation"], {"action": old.id, "observation": observation.id})
    return ToolOutcome(True, "Action reconciled. Continue from the observed outcome.")


async def artifact(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    import hashlib
    root = workspace_state.get(ctx.session_id).root
    path = Path(a["path"]).expanduser()
    if not path.is_absolute():
        path = Path(root or config.OUTPUTS_DIR) / path
    path = path.resolve()
    roots = [config.OUTPUTS_DIR.resolve(), config.CACHE_DIR.resolve() / "agentplus" / ctx.session_id]
    if root:
        roots.append(Path(root).resolve())
    if not any(r in path.parents for r in roots) or not path.is_file():
        raise ValueError("Choose a file in this chat's workspace or outputs")
    def inspect() -> dict[str, Any]:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        stat = path.stat()
        return {"path": str(path), "sha256": digest.hexdigest(), "size": stat.st_size, "modified": stat.st_mtime}
    import asyncio
    data = await asyncio.to_thread(inspect)
    store.event(ctx.session_id, "artifact", "Observed " + path.name, data)
    return ToolOutcome(True, json.dumps(data))


IMPL = {"mission_status": status, 'mission_context': context_records, "research_tool": learning.research, "invoke_chat_tool": invoke,
        'propose_alternative': alternatives.propose,
        "record_evidence": evidence, "complete_mission": complete, "record_learning": record,
        "resolve_action": reconcile, "observe_artifact": artifact, "plan_work": plan, "select_work": select, "finish_work": finish,
        'supersede_work': supersede}
READ_ONLY.add("observe_artifact")
READ_ONLY.update({'plan_work', 'select_work', 'finish_work', 'supersede_work', 'mission_context', 'propose_alternative'})


def profile(sid: str) -> profiles.Profile | None:
    if not store.owns_session(sid):
        return None

    def build(info: ModelInfo | None) -> str:
        session = db.get_session(sid)
        assert session
        detail = store.detail(sid)
        active = [w for w in detail.work if w.status == 'running']
        required = {dep for w in active for dep in w.dependencies}
        selected_work = [*active, *[w for w in detail.work if w.id in required and w not in active],
                         *[w for w in detail.work if w.status == 'pending' and all(
                             any(x.id == dep and x.status == 'done' for x in detail.work) for dep in w.dependencies)]][:8]
        mission = detail.mission.model_dump(exclude={'original_request'})
        compact = {"mission": mission, "tools": [
            {"id": t.id, "name": t.name, "status": t.status, "description": t.description,
             "input_schema": t.input_schema, "limitations": t.limitations} for t in detail.tools if t.status == 'validated'][-8:],
            "work": [w.model_dump() for w in selected_work], 'work_omitted': len(detail.work)-len(selected_work),
            'research_limits': {'per_request_model_calls': learning.MAX_RESEARCH_STEPS,
                                'per_request_candidate_revisions': learning.MAX_REVISIONS,
                                'resets_on_new_research_request': True,
                                'shares_mission_request_budget': True},
            "uncertain_actions": [{'id': x.id, 'name': x.name, 'args': x.args, 'output': (x.output or '')[:1000]}
                                  for x in detail.actions if x.status == "uncertain"],
            "retained_evidence": [{'seq': e.seq, 'kind': e.kind, 'text': e.text[:700], 'data': e.data}
                                  for e in detail.events if e.kind in ('learning', 'evidence', 'artifact', 'alternative')][-6:]}
        return prompt.build("agent", sid, info, session.model) + "\n\n" + (
            "You are the main agent pursuing a persistent mission. Execute one action at a time. "
            "The mission record is authoritative; temporary context summaries are indexes, not proof. "
            "Use plan_work for multi-step delivery, learning, alternatives and validation; select_work chooses one "
            "eligible next item and finish_work records its evidence. Inspect actual results, record evidence for "
            "each criterion and call complete_mission with the deliverable. "
            "If a needed tool is missing, first define concrete input/output acceptance cases, then research_tool. "
            "Supply 1 to 20 acceptance cases using args plus expected (the exact entire successful JSON), or args "
            "plus error_contains (error substring). Check arithmetic, dates, field types and all expected keys against "
            "the mission before freezing the cases. A test oracle must not contradict the user contract. "
            "Use mission_context for omitted records. Once enough information is available, call a tool now; avoid "
            "repeating status reads or narrating a plan without executing it. "
            "While delegated research works, you wait. Reuse validated chat tools through invoke_chat_tool. "
            "A research attempt's sixteen-response limit resets on each NEW research_tool request; it is not a "
            "chat-wide tool-building limit. Only the mission's remaining request/spending allocation is shared. "
            "Retained learning and alternatives are agent interpretations: inspect their cited receipts and prefer "
            "current runtime limits and the authoritative mission over an earlier inference. "
            "Record observations and distinct alternatives with sources; change the approach after repeated failure. "
            "Use propose_alternative for a fresh mechanism and distinguishing test when the current approach stalls. "
            "Plan independent replacement items, then supersede_work to preserve and replace an unsuccessful branch. "
            "Never retry an uncertain effect before inspection and resolve_action. Do not treat a test suite or a "
            "summary as universal validation. Use delegate_task only for bounded independent work with explicit tools; use delegation_status to inspect results. The main agent remains sequential. "
            "Ask the user only for required information or a genuinely new commitment.\nPersistent state:\n"
        ) + json.dumps(compact, ensure_ascii=False)

    def select(specs: list[ToolSpec]) -> list[ToolSpec]:
        return [s for s in specs if s.name != "start_task"] + SPECS

    def gate(name: str, args: dict[str, Any], _gated: bool) -> str | None:
        from ..agent import tools as agent_tools
        if name not in {s.name for s in select(agent_tools.all_specs())}:
            return "Tool is outside this mission profile. Delegate missing capabilities through research_tool."
        if any(a.status == "uncertain" for a in store.actions(sid)) and not is_read_only(name, args):
            return "An action has an uncertain effect. Observe and resolve it before another mutation."
        return None

    def receipt(call: Call, outcome: ToolOutcome) -> ToolOutcome:
        try:
            payload = json.loads(outcome.output)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            payload['_receipt_id'] = call.id
            outcome.output = json.dumps(payload, ensure_ascii=False)
        else:
            outcome.output += '\nAction receipt: ' + call.id
        return outcome

    return profiles.Profile(build, select, gate, observe=lambda ev: controller.observe(sid, ev),
        preserve_approvals=True, provider=lambda p: MissionProvider(p, sid),
        halt=lambda: store.get(sid).status != "running", result=receipt)
