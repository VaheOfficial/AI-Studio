"""One main agent per mission; learning runs only while that agent awaits its delegated tool."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from .. import db
from ..schemas import EvDone, EvError, EvToolCall, EvToolResult, EvTurnStart
from ..schemas_agent_plus import MissionAction
from . import store

READ_ONLY = {"system_info", "list_models", "search_catalog", "list_dir", "read_file", "find_files", "search_files",
             "fetch_url", "read_skill", "browser_read", "browser_screenshot", "read_process_output",
             "mission_status", "mission_context", "record_evidence", "complete_mission", "resolve_action", "record_learning",
             "search_tools", "load_tools", "knowledge_search", "skill_read", "artifact_read",
             "delegation_status", "search_documents", "connector_resources", "connector_read_resource",
             "observe_artifact", "plugin_list", "plugin_read_file"}


def is_read_only(name: str, args: dict) -> bool:
    if name.startswith('api_'):
        from ..agents.services import identify
        try:
            return identify(name)[1].read_only
        except Exception:
            return False
    if name == 'browser_action':
        from ..agents.browser_tools import READ
        return args.get('action') in READ
    if name == 'computer_action':
        return args.get('action') in ('screenshot', 'zoom', 'cursor_position', 'wait')
    return name in READ_ONLY


class Controller:
    def __init__(self) -> None:
        self.agent: Any = None
        self.pending: dict[str, asyncio.Task[None]] = {}
        self.closing = False

    def start(self, agent: Any) -> None:
        self.agent, self.closing = agent, False

    def observe(self, sid: str, ev: Any) -> None:
        m = store.get(sid)
        if isinstance(ev, EvTurnStart):
            if m.status not in ("running", "cancelled"):
                m.status, m.reason = "running", None
                store.save(m)
            store.event(sid, "turn", "Main agent started a step.")
        elif isinstance(ev, EvToolCall) and ev.call.status == "running":
            try:
                store.action(sid, ev.call.id)
            except ValueError:
                store.save_action(sid, MissionAction(id=ev.call.id, name=ev.call.name, args=ev.call.args,
                    status="running", created_at=db.now_iso()))
        elif isinstance(ev, EvToolResult):
            try:
                a = store.action(sid, ev.call_id)
            except ValueError:
                if not ev.ok:
                    m.status, m.reason = "blocked", ev.output
                    store.save(m)
                return
            no_effect = is_read_only(a.name, a.args)
            if not ev.ok and a.name == 'research_tool':
                from .learning import preflight
                try:
                    preflight(a.args)
                except (ValueError, KeyError, TypeError):
                    # Research validates this exact request before any delegation or execution.
                    no_effect = True
                if any(e.kind in ('research.conflict', 'research.stopped') and e.data.get('action_id') == a.id
                       and e.data.get('code_executed') is False for e in store.detail(sid).events):
                    no_effect = True
            a.status = "succeeded" if ev.ok else ("failed" if no_effect else "uncertain")
            a.output = ev.output
            store.save_action(sid, a)
            from .tools import CONTROLS
            if ev.ok and a.name not in CONTROLS:
                fingerprint = store.digest(json.dumps({'name': a.name, 'args': a.args, 'output': a.output}, sort_keys=True))
                recent = [e for e in store.detail(sid).events if e.kind == 'action.observed'][-8:]
                if not any(e.data.get('fingerprint') == fingerprint for e in recent):
                    store.event(sid, 'action.observed', 'Result observed: ' + a.name,
                                {'action_id': a.id, 'fingerprint': fingerprint})
        elif isinstance(ev, EvError):
            if m.status == "running":
                m.status, m.reason = "blocked", ev.message
                store.save(m)
        elif isinstance(ev, EvDone) and m.status == "running" and not self.closing:
            if sid not in self.pending:
                task = asyncio.create_task(self._continue(sid), name=f"agentplus-{sid}")
                self.pending[sid] = task
                task.add_done_callback(lambda t: self.pending.pop(sid, None) if self.pending.get(sid) is t else None)

    async def _continue(self, sid: str) -> None:
        # EvDone is emitted just before AgentService removes its live turn.
        await asyncio.sleep(0)
        if self.closing or store.get(sid).status != "running" or self.agent.busy(sid):
            return
        recent = store.detail(sid).events
        progress_kinds = ('evidence', 'learning', 'tool.validated', 'action.observed', 'alternative')
        since = [e for e in recent if e.kind == 'turn' or e.kind in progress_kinds][-6:]
        directive = ''
        if len(since) >= 4 and all(e.kind == "turn" for e in since[-4:]):
            last_progress = max((e.seq for e in recent if e.kind in progress_kinds), default=0)
            if any(e.kind == 'alternative.requested' and e.seq > last_progress for e in recent):
                m = store.get(sid)
                m.status, m.reason = 'blocked', 'No new evidence after an alternative was requested. Review the obstacle or amend the mission.'
                store.save(m)
                return
            store.event(sid, 'alternative.requested', 'Progress stalled; request a fresh approach and test its mechanism.')
            directive = 'Call propose_alternative now with the actual obstacle and receipt IDs. Test its changed mechanism. '
        session = db.get_session(sid)
        if session:
            self.pending.pop(sid, None)
            self.agent.start(session, directive + "Continue the current mission from its persisted evidence. Inspect unresolved "
                "actions before repeating any effect. Use a different approach after repeated failure. "
                "Call complete_mission only when every criterion has evidence, or ask_user if input is required.")

    async def pause(self, sid: str, status: str = "paused", cancel_wakes: bool = True) -> None:
        m = store.get(sid)
        m.status, m.reason = status, "Stopped by user. Review interrupted actions before resuming."
        store.save(m)
        if self.agent:
            await self.agent.stop_and_wait(sid)
        from ..agents import delegation
        from ..workspace.tasks import tasks
        for child in delegation.list_all(sid):
            if child.status in ("queued", "running", "waiting_approval"):
                await tasks.cancel(child.task_id)
        if cancel_wakes:
            db.execute("UPDATE agent_wakes SET status='paused',result='Agent paused by user' WHERE session_id=? AND status IN ('scheduled','ready')", (sid,))

    async def shutdown(self) -> None:
        self.closing = True
        for task in list(self.pending.values()):
            task.cancel()
        if self.pending:
            await asyncio.gather(*list(self.pending.values()), return_exceptions=True)
        for m in store.list_all():
            if m.status == "running":
                await self.pause(m.session_id, cancel_wakes=False)


controller = Controller()
