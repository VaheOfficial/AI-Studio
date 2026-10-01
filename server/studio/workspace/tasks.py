"""Durable background tasks (OpenMuse ``engine/worker.ts`` + ``service.ts``, adapted).

A task is a prompt run as an agent turn in its own chat session (same workspace folder as the chat it came
from), so its transcript, approvals and workspace panel use the normal chat UI. Tasks live in sqlite and run
without any open tab; a server restart re-queues the ones that were running with a note to inspect before
repeating work. Status changes push ``task.update``; the UI notifies on completion.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .. import db, events
from ..events import bus
from ..schemas import AgentSession, EvError, EvToolApproval, EvToolCall
from ..schemas_workspace import AgentTask, EvTaskRemoved, EvTaskUpdate, PlanItem
from . import state
from .state import WorkspaceError

if TYPE_CHECKING:
    from ..agent.loop import AgentService

CONCURRENCY = 2
RESUME_NOTE = ("(This background task was interrupted by a server restart. Check the current state of the "
               "workspace before repeating anything, then continue.)\n\n")
_COLUMNS = ("id", "title", "prompt", "status", "origin_session_id", "session_id", "result", "error", "attempts",
            "created_at", "updated_at", "finished_at")


class TaskRunner:
    def __init__(self) -> None:
        self._agent: AgentService | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = False

    # ------------------------------ storage ------------------------------

    @staticmethod
    def init_db() -> None:
        db.execute("""CREATE TABLE IF NOT EXISTS workspace_tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            prompt TEXT NOT NULL,
            status TEXT NOT NULL,
            origin_session_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            result TEXT,
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )""")

    @staticmethod
    def _task(row: object) -> AgentTask:
        data = {k: row[k] for k in _COLUMNS}  # type: ignore[index]
        return AgentTask(**data, plan=state.get(data["session_id"]).plan)

    def list(self) -> list[AgentTask]:
        return [self._task(r) for r in db.query("SELECT * FROM workspace_tasks ORDER BY created_at DESC LIMIT 200")]

    def get(self, task_id: str) -> AgentTask:
        r = db.query_one("SELECT * FROM workspace_tasks WHERE id = ?", (task_id,))
        if r is None:
            raise WorkspaceError(f"Task '{task_id}' not found")
        return self._task(r)

    def _update(self, task_id: str, **fields: object) -> AgentTask:
        fields["updated_at"] = db.now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE workspace_tasks SET {cols} WHERE id = ?", (*fields.values(), task_id))
        task = self.get(task_id)
        bus.publish(EvTaskUpdate(task=task))
        return task

    def is_task_session(self, session_id: str) -> bool:
        return db.query_one("SELECT 1 FROM workspace_tasks WHERE session_id = ?", (session_id,)) is not None

    def plan_changed(self, session_id: str, plan: list[PlanItem]) -> None:
        r = db.query_one("SELECT * FROM workspace_tasks WHERE session_id = ?", (session_id,))
        if r is not None:
            bus.publish(EvTaskUpdate(task=self._task(r).model_copy(update={"plan": plan})))

    # ------------------------------ control ------------------------------

    def create(self, origin_session_id: str, prompt: str, title: str | None = None) -> AgentTask:
        origin = db.get_session(origin_session_id)
        if origin is None:
            raise WorkspaceError(f"Session '{origin_session_id}' not found")
        title = (title or " ".join(prompt.split()[:8])).strip()[:120] or "Background task"
        now = db.now_iso()
        session = AgentSession(id=uuid.uuid4().hex[:16], title=f"Task · {title}", model=origin.model, mode="agent",
                               created_at=now, updated_at=now)
        db.insert_session(session)
        root = state.get(origin_session_id).root
        if root:
            state.set_root(session.id, root)
        task_id = uuid.uuid4().hex[:12]
        db.execute(
            f"INSERT INTO workspace_tasks({', '.join(_COLUMNS)}) VALUES({', '.join('?' * len(_COLUMNS))})",
            (task_id, title, prompt, "queued", origin_session_id, session.id, None, None, 0, now, now, None))
        task = self.get(task_id)
        bus.publish(EvTaskUpdate(task=task))
        self._queue.put_nowait(task_id)
        return task

    async def cancel(self, task_id: str) -> AgentTask:
        task = self.get(task_id)
        if task.status in ("succeeded", "failed", "cancelled"):
            return task
        updated = self._update(task_id, status="cancelled", finished_at=db.now_iso(), error="Stopped by you")
        if self._agent is not None:
            await self._agent.stop_and_wait(task.session_id)
        return updated

    def retry(self, task_id: str) -> AgentTask:
        task = self.get(task_id)
        if task.status not in ("failed", "cancelled"):
            raise WorkspaceError("Only failed or cancelled tasks can be retried")
        updated = self._update(task_id, status="queued", error=None, result=None, finished_at=None)
        self._queue.put_nowait(task_id)
        return updated

    async def delete(self, task_id: str) -> None:
        task = self.get(task_id)
        if task.status in ("queued", "running", "waiting_approval"):
            await self.cancel(task_id)
        db.execute("DELETE FROM workspace_tasks WHERE id = ?", (task_id,))
        bus.publish(EvTaskRemoved(id=task_id))

    def forget_session(self, session_id: str) -> None:
        """A task's own chat was deleted: the task goes with it (the caller stops its turn)."""
        for r in db.query("SELECT id FROM workspace_tasks WHERE session_id = ?", (session_id,)):
            db.execute("DELETE FROM workspace_tasks WHERE id = ?", (r["id"],))
            bus.publish(EvTaskRemoved(id=r["id"]))

    # ------------------------------ runner ------------------------------

    def start(self, agent: AgentService) -> None:
        self._agent = agent
        self._stopping = False
        # Whatever was running when the server stopped continues now.
        for r in db.query("SELECT id, status FROM workspace_tasks WHERE status IN ('queued', 'running', "
                          "'waiting_approval') ORDER BY created_at"):
            if r["status"] != "queued":
                db.execute("UPDATE workspace_tasks SET status = 'queued' WHERE id = ?", (r["id"],))
            self._queue.put_nowait(r["id"])
        self._workers = [asyncio.create_task(self._work(), name=f"task-worker-{i}") for i in range(CONCURRENCY)]

    async def shutdown(self) -> None:
        """Called before the agent stops its turns: running tasks keep their status and resume next start."""
        self._stopping = True
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.wait(self._workers, timeout=5)
        self._workers = []

    async def _work(self) -> None:
        while True:
            task_id = await self._queue.get()
            try:
                await self._run(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                events.log("error", "tasks", f"Task {task_id} crashed: {exc}")
                if not self._stopping:
                    self._update(task_id, status="failed", error=str(exc), finished_at=db.now_iso())

    async def _run(self, task_id: str) -> None:
        try:
            task = self.get(task_id)
        except WorkspaceError:
            return  # deleted while queued
        if task.status != "queued" or self._agent is None:
            return
        session = db.get_session(task.session_id)
        if session is None:
            self._update(task_id, status="failed", error="The task's chat was deleted", finished_at=db.now_iso())
            return
        attempts = task.attempts + 1
        errors: list[str] = []

        def listen(event: BaseModel) -> None:
            if isinstance(event, EvToolApproval):
                self._update(task_id, status="waiting_approval")
            elif isinstance(event, EvToolCall) and event.call.status == "running" and \
                    self.get(task_id).status == "waiting_approval":
                self._update(task_id, status="running")
            elif isinstance(event, EvError):
                errors.append(event.message)

        content = task.prompt if attempts == 1 else RESUME_NOTE + task.prompt
        self._update(task_id, status="running", attempts=attempts)
        try:
            turn = self._agent.start(session, content, listen)
        except Exception as exc:  # e.g. someone is chatting in the task's session right now
            self._update(task_id, status="failed", error=str(exc), finished_at=db.now_iso())
            return
        assert turn.task is not None
        await asyncio.wait({turn.task})
        if self._stopping:
            return  # server shutdown: stays running/queued and resumes on the next start
        try:
            current = self.get(task_id)
        except WorkspaceError:
            return  # deleted while running
        if current.status == "cancelled":
            return
        finished = db.now_iso()
        if turn.stopped:
            self._update(task_id, status="cancelled", error="Stopped in its chat", finished_at=finished)
        elif errors:
            self._update(task_id, status="failed", error=errors[-1], finished_at=finished)
        else:
            result = turn.reply.content.strip()[-4000:] or "Finished (no summary)."
            self._update(task_id, status="succeeded", result=result, finished_at=finished)
        events.log("info", "tasks", f"Task '{task.title}' {self.get(task_id).status}")


tasks = TaskRunner()
