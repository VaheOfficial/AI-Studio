"""The swarm's controller: plain code that runs every swarm. Models plan, work and check; this decides who does what
and when, watches the sessions it starts, and keeps the ledger moving.

Each tick (and whenever something changes) it looks at every running swarm:

1. limits: a swarm over its daily budget pauses (and resumes the next day by itself);
2. stalls: a session with no event for ``STALL_S`` is stopped and its attempt counts as failed;
3. planning: the lead (Foundress) gets a planning session when the swarm starts, when something it must react to
   happened (a milestone done or rejected, a task given up, the owner wrote, answered or allowed something), or when
   workers are running out of ready tasks while new reports wait;
4. reviews: work handed off goes to an idle inspector (preferably on another model than the worker's);
5. work: ready tasks (open, nothing they wait for still unaccepted) go to idle workers: the one the lead asked for,
   else the one who did it before (a rework), else anyone.

A session that ends without its tool call (``hand_off``, ``verdict``) is nudged once in the same chat; after that the
attempt counts as failed. A task fails for good after ``MAX_ATTEMPTS`` attempts or ``MAX_REJECTIONS`` rejections,
and the lead is told. Local models run one session at a time. Sessions belong to the swarm (kept out of the chat
list) and can be opened like any chat."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .. import db, events
from ..schemas import AgentSession, EvError, EvToolCall, EvToolResult, EvUsage
from ..schemas_swarm import (Swarm, SwarmAgent, SwarmHandoff, SwarmItem, SwarmReview)
from ..workspace import state as workspace_state
from . import briefs, store

if TYPE_CHECKING:
    from ..agent.loop import AgentService

TICK_S = 15
STALL_S = 10 * 60  # a session with no event for this long is stopped…
STALL_TOOL_S = 30 * 60  # …or this long while one of its tools runs (a quiet install or test suite)
MAX_ATTEMPTS = 3
MAX_REJECTIONS = 3
MAX_REVIEW_TRIES = 3
REPEAT_LIMIT = 5  # the same tool call with the same arguments, in a row
REFUSED_LIMIT = 8  # refused calls in one session
PLAN_GAP_S = 3 * 60  # between two planning sessions that nothing urgent asked for
# The working context of a swarm session (tokens). Every request re-sends the whole session, so on a model with a
# huge window a long task would carry everything it ever read; past this, old tool output is trimmed and then
# summarized (agent/context.py).
SESSION_CONTEXT = 64_000
EMPTY_PLANS = 3  # planning sessions in a row that changed nothing pause the swarm
LOCAL = ("ollama", "llamacpp", "lmstudio")

NUDGE_WORK = ("(The swarm, not the owner:) Your session ended without `hand_off`. If the task is done, call "
              "`hand_off` now with your report. If it is not, continue the work and then call `hand_off`; if you "
              "cannot finish, call `hand_off` anyway and say what is not done.")
NUDGE_REVIEW = ("(The swarm, not the owner:) Your session ended without `verdict`. Finish checking the criteria, "
                "then call `verdict`.")


@dataclass
class Run:
    """A session the controller started and is watching."""

    session_id: str
    swarm_id: str
    agent_id: str
    item_id: str | None
    purpose: str  # plan | work | review
    local: bool
    started: float = field(default_factory=time.monotonic)
    last_event: float = field(default_factory=time.monotonic)
    calls: Counter[str] = field(default_factory=Counter)
    last_call: str | None = None
    repeats: int = 0
    refused: int = 0
    errors: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    in_tool: bool = False  # one of its tools is running
    requeue: bool = False  # stopped on purpose: the work goes back to the queue, not counted as failed
    planned_seq: int = 0  # the lead's planning: the last event before it began


def _is_local(model: str) -> bool:
    return model.partition(":")[0] in LOCAL


def _family(model: str) -> str:
    """The maker behind a model id, to keep a worker's work from being checked by the same model family."""
    name = model.partition(":")[2].lower()
    return name.split("/")[0] if "/" in name else name.split(":")[0].split("-")[0]


class SwarmController:
    def __init__(self) -> None:
        self._agent: AgentService | None = None
        self._loop: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._runs: dict[str, Run] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._stopping = False
        self._last_plan: dict[str, float] = {}  # swarm -> when its last planning session ended
        self._empty_plans: Counter[str] = Counter()
        self._review_tries: Counter[str] = Counter()  # item -> review sessions that gave no verdict

    # ------------------------------ lifecycle ------------------------------

    def start(self, agent: AgentService) -> None:
        self._agent = agent
        self._stopping = False
        store.load_owned()
        for s in store.list_swarms():
            for i in store.list_items(s.id):
                if i.status == "running":  # its session ended with the server
                    store.update_item(i.id, status="open")
                    store.add_event(s.id, "interrupted", f"[{i.id}] {i.title}: interrupted by a restart; back in "
                                                         "the queue", i.owner_agent_id, i.id)
            for a in store.list_agents(s.id):
                if a.state != "idle":
                    store.update_agent(a.id, state="idle", item_id=None)
        self._loop = asyncio.create_task(self._tick_forever(), name="swarm-controller")

    async def shutdown(self) -> None:
        self._stopping = True
        if self._loop:
            self._loop.cancel()
            await asyncio.gather(self._loop, return_exceptions=True)
        self._loop = None

    def poke(self) -> None:
        self._wake.set()

    def _spawn(self, coro: Any, name: str) -> None:
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _tick_forever(self) -> None:
        await asyncio.sleep(3)
        while True:
            try:
                for s in store.list_swarms():
                    self._step(s)
            except Exception as exc:  # noqa: BLE001 - one bad swarm must not stop the others
                events.log("error", "swarm", f"Controller error: {exc}")
            try:
                await asyncio.wait_for(self._wake.wait(), TICK_S)
            except TimeoutError:
                pass
            self._wake.clear()

    # ------------------------------ owner's controls ------------------------------

    def run(self, swarm_id: str, why: str = "resumed by the owner") -> Swarm:
        s = store.get_swarm(swarm_id)
        if s.status == "running":
            return s
        if not any(a.role == "lead" for a in store.list_agents(swarm_id)):
            raise store.SwarmError("The swarm needs a lead (Foundress) to start")
        if s.status == "draft":
            store.add_wake(swarm_id, "The swarm has just started.")
        store.add_event(swarm_id, "started", "started" if s.status == "draft" else why)
        self._empty_plans.pop(swarm_id, None)
        s = store.update_swarm(swarm_id, status="running", status_reason=None)
        self.poke()
        return s

    def pause(self, swarm_id: str, reason: str | None = None) -> Swarm:
        """Nothing new starts; what is running finishes."""
        store.add_event(swarm_id, "paused", reason or "paused by the owner")
        return store.update_swarm(swarm_id, status="paused", status_reason=reason)

    async def stop(self, swarm_id: str, reason: str | None = None, status: str = "stopped") -> Swarm:
        """Stop every session now; work in progress goes back to the queue."""
        s = store.update_swarm(swarm_id, status=status, status_reason=reason)
        await self._stop_runs([r for r in self._runs.values() if r.swarm_id == swarm_id], reason or "stopped")
        if status == "stopped":
            store.add_event(swarm_id, "stopped", reason or "stopped by the owner")
        return s

    async def delete(self, swarm_id: str) -> None:
        await self._stop_runs([r for r in self._runs.values() if r.swarm_id == swarm_id], "the swarm was deleted")
        from .. import workspace

        for session_id in store.delete_swarm(swarm_id):
            await workspace.forget_session(session_id)
            db.delete_session(session_id)

    def message(self, swarm_id: str, text: str) -> None:
        store.add_event(swarm_id, "owner", f"The owner wrote: {text}")
        store.add_wake(swarm_id, f"The owner wrote: {text}")
        self.poke()

    def notify_owner(self, swarm_id: str, title: str, body: str) -> None:
        events.log("info", "swarm", f"{title}: {body}")

    def finish(self, swarm_id: str, agent_id: str, summary: str) -> None:
        store.add_event(swarm_id, "finished", f"Goal reached: {summary}", agent_id)
        store.update_swarm(swarm_id, status="done", status_reason=summary[:500])
        others = [r for r in self._runs.values() if r.swarm_id == swarm_id and r.agent_id != agent_id]
        self._spawn(self._stop_runs(others, "the goal was reached"), f"swarm-finish-{swarm_id}")

    async def cancel_item(self, item: SwarmItem) -> None:
        targets = [item, *(i for i in store.list_items(item.swarm_id) if i.parent_id == item.id)]
        ids = {t.id for t in targets}
        await self._stop_runs([r for r in self._runs.values() if r.item_id in ids and r.purpose != "plan"],
                              "the task was cancelled")
        for t in targets:
            if t.status not in ("accepted", "cancelled"):
                store.update_item(t.id, status="cancelled")
        self._milestone_check(item.swarm_id, item.parent_id)

    async def _stop_runs(self, runs: list[Run], reason: str) -> None:
        """Stop sessions on purpose (the owner, a cancellation, the end of the goal): their work goes back to the
        queue without counting as a failed attempt."""
        assert self._agent is not None
        for r in runs:
            r.stop_reason = reason
            r.requeue = True
        await asyncio.gather(*(self._agent.stop_and_wait(r.session_id) for r in runs))

    # ------------------------------ what the tools report ------------------------------

    def handed_off(self, item: SwarmItem, agent: SwarmAgent, handoff: SwarmHandoff) -> None:
        inspectors = [a for a in store.list_agents(item.swarm_id) if a.role == "inspector"]
        store.add_event(item.swarm_id, "handed_off", f"handed off [{item.id}] {item.title}", agent.id, item.id)
        if inspectors:
            store.update_item(item.id, handoff=handoff, status="review")
        else:  # nobody to check it: the report is taken as it is
            store.update_item(item.id, handoff=handoff, status="accepted")
            store.bump_agent(agent.id, "accepted")
            store.add_event(item.swarm_id, "accepted", f"[{item.id}] {item.title} (no inspector to check it)",
                            agent.id, item.id)
            self._milestone_check(item.swarm_id, item.parent_id)
        # Follow-ups and concerns are read at the next planning session that happens anyway: a planning session for
        # each report would cost more than the reports are worth
        store.publish_agent(agent.id)
        self.poke()

    def reviewed(self, item: SwarmItem, inspector: SwarmAgent, review: SwarmReview) -> None:
        self._review_tries.pop(item.id, None)
        worker = item.owner_agent_id
        if item.kind == "milestone":
            if review.accepted:
                store.update_item(item.id, review=review, status="accepted")
                store.add_event(item.swarm_id, "accepted", f"milestone [{item.id}] {item.title}", inspector.id,
                                item.id)
                store.add_wake(item.swarm_id, f"Milestone [{item.id}] {item.title} was accepted: plan what comes "
                                              "next.")
            else:
                store.update_item(item.id, review=review, status="open")
                store.add_event(item.swarm_id, "rejected", f"milestone [{item.id}] {item.title}: {review.summary}",
                                inspector.id, item.id)
                store.add_wake(item.swarm_id, f"Milestone [{item.id}] {item.title} was rejected by the inspector: "
                                              "plan the fixes (see its verdict).")
        elif review.accepted:
            store.update_item(item.id, review=review, status="accepted")
            if worker:
                store.bump_agent(worker, "accepted")
                store.publish_agent(worker)
            store.add_event(item.swarm_id, "accepted", f"[{item.id}] {item.title}", inspector.id, item.id)
            self._milestone_check(item.swarm_id, item.parent_id)
        else:
            rejections = item.rejections + 1
            if worker:
                store.bump_agent(worker, "rejected")
                store.publish_agent(worker)
            store.add_event(item.swarm_id, "rejected", f"[{item.id}] {item.title}: {review.summary}", inspector.id,
                            item.id)
            if rejections >= MAX_REJECTIONS:
                store.update_item(item.id, review=review, status="failed", rejections=rejections)
                store.add_wake(item.swarm_id, f"Task [{item.id}] {item.title} was rejected {rejections} times and "
                                              "given up: rethink it (change its spec, split it, or drop it).")
            else:  # back to the same worker, with the verdict
                store.update_item(item.id, review=review, status="open", rejections=rejections, assign_to=worker)
        self.poke()

    def _milestone_check(self, swarm_id: str, milestone_id: str | None) -> None:
        if not milestone_id:
            return
        items = store.list_items(swarm_id)
        milestone = next((i for i in items if i.id == milestone_id), None)
        tasks = [i for i in items if i.parent_id == milestone_id and i.status != "cancelled"]
        if milestone is None or milestone.status != "open" or not tasks:
            return
        if all(t.status == "accepted" for t in tasks):
            if any(a.role == "inspector" for a in store.list_agents(swarm_id)):
                store.update_item(milestone.id, status="review")
                store.add_event(swarm_id, "milestone", f"milestone [{milestone.id}] {milestone.title}: all tasks "
                                                       "accepted, checking it as a whole", item_id=milestone.id)
            else:
                store.update_item(milestone.id, status="accepted")
                store.add_event(swarm_id, "accepted", f"milestone [{milestone.id}] {milestone.title}",
                                item_id=milestone.id)
                store.add_wake(swarm_id, f"Milestone [{milestone.id}] {milestone.title} was accepted: plan what "
                                         "comes next.")

    # ------------------------------ watching sessions ------------------------------

    def observe(self, session_id: str, event: Any) -> None:
        run = self._runs.get(session_id)
        if run is None:
            return
        run.last_event = time.monotonic()
        if isinstance(event, EvError):
            run.errors.append(event.message)
        elif isinstance(event, EvUsage):
            self._spend(run, event.cost)
        elif isinstance(event, EvToolResult):
            run.in_tool = False
        elif isinstance(event, EvToolCall) and event.call.status in ("running", "denied"):
            run.in_tool = event.call.status == "running"
            if event.call.status == "denied":
                run.refused += 1
                if run.refused >= REFUSED_LIMIT:
                    self._interrupt(run, f"kept calling tools it isn't allowed ({run.refused} refused)")
                return
            key = event.call.name + json.dumps(event.call.args, sort_keys=True, default=str)
            run.repeats = run.repeats + 1 if key == run.last_call else 1
            run.last_call = key
            if run.repeats >= REPEAT_LIMIT and event.call.name not in ("read_process_output",):
                self._interrupt(run, f"repeated the same {event.call.name} call {run.repeats} times")

    def _interrupt(self, run: Run, reason: str) -> None:
        if run.stop_reason is not None or self._agent is None:
            return
        run.stop_reason = reason
        self._agent.stop(run.session_id)

    def _spend(self, run: Run, cost: float) -> None:
        if not cost:
            return
        store.add_spend(run.swarm_id, cost)
        store.bump_agent(run.agent_id, "cost", cost)
        if run.item_id:
            store.add_item_cost(run.item_id, cost)
            s = store.get_swarm(run.swarm_id)
            item = store.get_item(run.item_id)
            if s.item_budget is not None and item.cost >= s.item_budget and run.purpose == "work":
                self._interrupt(run, f"spent ${item.cost:.2f}, the swarm's limit per task")

    # ------------------------------ the tick ------------------------------

    def _step(self, s: Swarm) -> None:
        now = time.monotonic()
        for run in [r for r in self._runs.values() if r.swarm_id == s.id]:
            limit = STALL_TOOL_S if run.in_tool else STALL_S
            if now - run.last_event > limit:
                self._interrupt(run, f"no activity for {limit // 60} minutes")
        if s.daily_budget is not None:
            over = s.spent_today >= s.daily_budget
            if s.status == "running" and over:
                self.pause(s.id, f"Daily budget of ${s.daily_budget:.2f} reached; resumes tomorrow")
                return
            if s.status == "paused" and not over and (s.status_reason or "").startswith("Daily budget"):
                s = self.run(s.id, "resumed: a new day's budget")
        if s.status != "running" or self._agent is None:
            return
        agents = store.list_agents(s.id)
        items = store.list_items(s.id)
        busy = {r.agent_id for r in self._runs.values()}
        idle = [a for a in agents if a.id not in busy and a.state != "paused"]
        mine = [r for r in self._runs.values() if r.swarm_id == s.id]
        slots = s.max_parallel - len(mine)
        local_busy = any(r.local for r in self._runs.values())

        def can_run(a: SwarmAgent) -> bool:
            return not (_is_local(a.model) and local_busy)

        if slots <= 0:
            return
        # 1. Planning
        lead = next((a for a in idle if a.role == "lead"), None)
        if lead is not None and can_run(lead) and self._needs_plan(s, items, agents):
            self._plan(s, lead, items, agents)
            return  # the plan comes first; work is handed out on the next tick
        # 2. Reviews
        reviewing = {r.item_id for r in self._runs.values() if r.purpose == "review"}
        for item in sorted((i for i in items if i.status == "review" and i.id not in reviewing),
                           key=lambda i: (i.kind != "milestone", i.updated_at)):
            if slots <= 0:
                return
            worker_model = next((a.model for a in agents if a.id == item.owner_agent_id), "")
            inspectors = sorted((a for a in idle if a.role == "inspector" and can_run(a)),
                                key=lambda a: _family(a.model) == _family(worker_model))
            if not inspectors:
                break
            inspector = inspectors[0]
            self._review(s, inspector, item, items, agents)
            idle.remove(inspector)
            local_busy = local_busy or _is_local(inspector.model)
            slots -= 1
        # 3. Work
        status = {i.id: i.status for i in items}
        ready = [i for i in items if i.kind == "task" and i.status == "open"
                 and all(status.get(b) in ("accepted", "cancelled", None) for b in i.blocked_by)
                 and status.get(i.parent_id or "") != "cancelled"]
        ready.sort(key=lambda i: i.priority)  # stable: within a priority, in the order they were planned
        # Workers the lead asked for by name wait for their own tasks; the others take the rest
        reserved = {i.assign_to for i in ready if i.assign_to}
        for item in ready:
            if slots <= 0:
                return
            workers = [a for a in idle if a.role == "worker" and can_run(a)]
            if not workers:
                return
            if item.assign_to:
                wanted = next((a for a in workers if a.id == item.assign_to), None)
                if wanted is None and any(a.id == item.assign_to for a in agents if a.role == "worker"):
                    continue  # its worker is busy: it waits for them
                worker = wanted or workers[0]
            else:
                free = [a for a in workers if a.id not in reserved]
                worker = (free or workers)[0]
            self._work(s, worker, item, items, agents)
            idle.remove(worker)
            local_busy = local_busy or _is_local(worker.model)
            slots -= 1

    def _needs_plan(self, s: Swarm, items: list[SwarmItem], agents: list[SwarmAgent]) -> bool:
        if any(r.purpose == "plan" and r.swarm_id == s.id for r in self._runs.values()):
            return False
        if store.wake_reasons(s.id):
            return True
        if self._empty_plans[s.id] >= EMPTY_PLANS:
            return False
        if time.monotonic() - self._last_plan.get(s.id, 0) < PLAN_GAP_S:
            return False
        live = [i for i in items if i.status in ("open", "running", "review")]
        if not any(i.kind == "task" for i in live):  # nothing left to do or to check: the lead decides what's next
            return True
        # Otherwise only when workers would run out: one is idle with nothing ready to take, and reports came in
        status = {i.id: i.status for i in items}
        ready = any(i.kind == "task" and i.status == "open"
                    and all(status.get(b) in ("accepted", "cancelled", None) for b in i.blocked_by) for i in live)
        busy = {r.agent_id for r in self._runs.values()}
        idle_worker = any(a.role == "worker" and a.id not in busy for a in agents)
        new_reports = any(e.kind in ("handed_off", "accepted", "rejected", "failed")
                          for e in store.events_after(s.id, store.seen_seq(s.id)))
        return idle_worker and not ready and new_reports

    # ------------------------------ starting sessions ------------------------------

    def _session(self, s: Swarm, agent: SwarmAgent, item: SwarmItem | None, purpose: str, title: str) -> AgentSession:
        now = db.now_iso()
        session = AgentSession(id=uuid.uuid4().hex[:16], title=title[:120], model=agent.model, mode="agent",
                               created_at=now, updated_at=now)
        db.insert_session(session)
        db.update_session(session.id, context_size=SESSION_CONTEXT)
        try:
            workspace_state.set_root(session.id, s.folder)
        except workspace_state.WorkspaceError as exc:
            events.log("warn", "swarm", f"{s.name}: {exc}")
        store.add_session(session.id, s.id, agent.id, item.id if item else None, purpose)
        if item is not None:
            fresh = store.get_item(item.id)
            store.update_item(item.id, session_ids=[*fresh.session_ids, session.id])
        return session

    def _launch(self, s: Swarm, agent: SwarmAgent, session: AgentSession, content: str, run: Run,
                state: str) -> None:
        assert self._agent is not None
        self._runs[session.id] = run
        store.update_agent(agent.id, state=state, item_id=run.item_id, session_id=session.id,
                           last_active=db.now_iso())
        try:
            turn = self._agent.start(session, content)
        except Exception as exc:  # noqa: BLE001 - e.g. the model is gone
            self._runs.pop(session.id, None)
            store.update_agent(agent.id, state="idle", item_id=None)
            store.add_event(s.id, "error", f"could not start a session: {exc}", agent.id, run.item_id)
            raise
        self._spawn(self._watch(run, turn, content), f"swarm-run-{session.id}")

    def _plan(self, s: Swarm, lead: SwarmAgent, items: list[SwarmItem], agents: list[SwarmAgent]) -> None:
        seen = store.seen_seq(s.id)
        reasons = store.take_wake(s.id)
        first = not items
        content = briefs.plan_brief(s, items, agents, store.events_after(s.id, seen), reasons,
                                    store.list_inbox(s.id), first)
        session = self._session(s, lead, None, "plan", f"{lead.name} · planning")
        store.add_event(s.id, "planning", "planning" + (": " + "; ".join(reasons)[:300] if reasons else ""), lead.id)
        run = Run(session.id, s.id, lead.id, None, "plan", _is_local(lead.model), planned_seq=store.last_seq(s.id))
        store.set_seen_seq(s.id, store.last_seq(s.id))
        self._launch(s, lead, session, content, run, "planning")

    def _work(self, s: Swarm, worker: SwarmAgent, item: SwarmItem, items: list[SwarmItem],
              agents: list[SwarmAgent]) -> None:
        session = self._session(s, worker, item, "work", f"{worker.name} · {item.title}")
        store.update_item(item.id, status="running", owner_agent_id=worker.id, attempts=item.attempts + 1)
        store.add_event(s.id, "assigned", f"[{item.id}] {item.title}" + (" (rework)" if item.rejections else ""),
                        worker.id, item.id)
        content = briefs.work_brief(s, store.get_item(item.id), worker, items, agents)
        self._launch(s, worker, session, content, Run(session.id, s.id, worker.id, item.id, "work",
                                                       _is_local(worker.model)), "working")

    def _review(self, s: Swarm, inspector: SwarmAgent, item: SwarmItem, items: list[SwarmItem],
                agents: list[SwarmAgent]) -> None:
        session = self._session(s, inspector, item, "review", f"{inspector.name} · check: {item.title}")
        store.add_event(s.id, "reviewing", f"checking [{item.id}] {item.title}", inspector.id, item.id)
        content = briefs.review_brief(s, item, inspector, items, agents)
        self._launch(s, inspector, session, content, Run(session.id, s.id, inspector.id, item.id, "review",
                                                          _is_local(inspector.model)), "reviewing")

    # ------------------------------ when a session ends ------------------------------

    async def _watch(self, run: Run, turn: Any, content: str) -> None:
        try:
            await asyncio.wait({turn.task})
            if self._stopping:
                return
            if run.stop_reason is None and run.purpose in ("work", "review") and self._unfinished(run):
                # One nudge in the same chat, then the attempt counts as failed
                assert self._agent is not None
                session = db.get_session(run.session_id)
                if session is not None and not self._agent.busy(run.session_id):
                    run.last_event = time.monotonic()
                    store.add_event(run.swarm_id, "nudged", "ended without "
                                    + ("handing off" if run.purpose == "work" else "a verdict") + "; asked again",
                                    run.agent_id, run.item_id)
                    turn = self._agent.start(session, NUDGE_WORK if run.purpose == "work" else NUDGE_REVIEW)
                    await asyncio.wait({turn.task})
                    if self._stopping:
                        return
            self._ended(run, turn)
        except Exception as exc:  # noqa: BLE001
            events.log("error", "swarm", f"Watching session {run.session_id} failed: {exc}")
        finally:
            self._runs.pop(run.session_id, None)
            try:
                agent = store.get_agent(run.agent_id)
                if agent.state not in ("paused", "dismissed"):
                    store.update_agent(run.agent_id, state="idle", item_id=None, last_active=db.now_iso())
            except store.SwarmError:
                pass  # removed meanwhile
            self.poke()

    def _unfinished(self, run: Run) -> bool:
        if run.item_id is None:
            return False
        try:
            item = store.get_item(run.item_id)
        except store.SwarmError:
            return False
        if run.purpose == "work":
            return item.status == "running" and item.owner_agent_id == run.agent_id
        return item.status == "review"

    def _ended(self, run: Run, turn: Any) -> None:
        try:
            swarm = store.get_swarm(run.swarm_id)
        except store.SwarmError:
            return  # deleted
        reason = run.stop_reason or (run.errors[-1] if run.errors else None)
        if run.purpose == "plan":
            self._last_plan[run.swarm_id] = time.monotonic()
            report = turn.reply.content.strip()
            if report:
                store.update_swarm(run.swarm_id, report=report[-6000:], report_at=db.now_iso())
                store.add_event(run.swarm_id, "report", report[:600], run.agent_id)
            planned = any(e.kind == "planned" for e in store.events_after(run.swarm_id, run.planned_seq))
            self._empty_plans[run.swarm_id] = 0 if planned else self._empty_plans[run.swarm_id] + 1
            if reason and not report and not run.requeue:
                store.add_event(run.swarm_id, "error", f"planning ended: {reason}", run.agent_id)
            if self._empty_plans[run.swarm_id] >= EMPTY_PLANS and swarm.status == "running":
                self.pause(run.swarm_id, f"The Foundress planned nothing new {EMPTY_PLANS} times in a row")
            return
        if not self._unfinished(run):
            return
        item = store.get_item(run.item_id or "")
        if run.requeue:
            if item.status == "running":
                store.update_item(item.id, status="open", attempts=max(0, item.attempts - 1))
            return
        why = reason or ("ended without handing off" if run.purpose == "work" else "ended without a verdict")
        if run.purpose == "review":
            self._review_tries[item.id] += 1
            store.add_event(run.swarm_id, "stalled", f"check of [{item.id}] {item.title}: {why}", run.agent_id,
                            item.id)
            if self._review_tries[item.id] >= MAX_REVIEW_TRIES:
                self._review_tries.pop(item.id, None)
                store.update_item(item.id, status="failed")
                store.add_wake(run.swarm_id, f"[{item.id}] {item.title} could not be checked "
                                             f"({MAX_REVIEW_TRIES} tries; last: {why}).")
            return
        store.bump_agent(run.agent_id, "failed")
        store.publish_agent(run.agent_id)
        if item.attempts >= MAX_ATTEMPTS:
            store.update_item(item.id, status="failed")
            store.add_event(run.swarm_id, "failed", f"[{item.id}] {item.title}: {why} (gave up after "
                                                    f"{item.attempts} attempts)", run.agent_id, item.id)
            store.add_wake(run.swarm_id, f"Task [{item.id}] {item.title} failed {item.attempts} times (last: {why}): "
                                         "rethink it.")
        else:
            store.update_item(item.id, status="open", assign_to=None)
            store.add_event(run.swarm_id, "stalled", f"[{item.id}] {item.title}: {why}; back in the queue",
                            run.agent_id, item.id)

    def running_sessions(self, swarm_id: str) -> list[str]:
        return [r.session_id for r in self._runs.values() if r.swarm_id == swarm_id]


controller = SwarmController()
