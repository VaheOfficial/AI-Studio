"""Thread-based job manager. Every state change is broadcast as a ``job.update`` event."""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from . import events
from .db import now_iso
from .events import bus
from .schemas import EvJobUpdate, Job, JobKind, JobResult

MAX_JOBS = 100
_FINISHED = ("done", "error", "cancelled")
_PUBLISH_INTERVAL_S = 0.2


class JobCancelled(Exception):
    """Raised inside a job function to abort it after a cancel request."""


class JobError(Exception):
    """A job failure with a user-facing message (no traceback logged)."""


class JobContext:
    """Handle passed to job functions for reporting progress and observing cancellation."""

    def __init__(self, job: Job) -> None:
        self.job = job
        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self._cancel_hooks: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._last_publish = 0.0
        self._trailing = False

    @property
    def id(self) -> str:
        return self.job.id

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()

    def on_cancel(self, hook: Callable[[], None]) -> None:
        """Register a callback run (once) when the job is cancelled, e.g. to kill a subprocess."""
        with self._lock:
            self._cancel_hooks.append(hook)
            fire = self.cancel_event.is_set()
        if fire:
            hook()

    def update(self, **fields: Any) -> None:
        """Apply changes and broadcast. Pure progress updates are throttled to ~5/s; status
        changes are always sent immediately."""
        with self._lock:
            self.job = self.job.model_copy(update=fields)
            now = time.monotonic()
            if "status" not in fields and now - self._last_publish < _PUBLISH_INTERVAL_S:
                if not self._trailing:
                    # Make sure the latest state still goes out once the interval has passed.
                    self._trailing = True
                    timer = threading.Timer(_PUBLISH_INTERVAL_S, self._flush)
                    timer.daemon = True
                    timer.start()
                return
            self._last_publish = now
        bus.publish(EvJobUpdate(job=self.job))

    def _flush(self) -> None:
        with self._lock:
            self._trailing = False
            self._last_publish = time.monotonic()
        bus.publish(EvJobUpdate(job=self.job))

    def log(self, message: str, level: events.LogLevel = "info") -> None:
        """Set the job message and mirror it to the global log stream."""
        self.update(message=message[-500:])
        events.log(level, f"job:{self.job.kind}", message)

    def _cancel(self) -> None:
        with self._lock:
            already = self.cancel_event.is_set()
            self.cancel_event.set()
            hooks = [] if already else list(self._cancel_hooks)
        for hook in hooks:
            try:
                hook()
            except Exception as exc:  # a failing hook must not prevent the others
                events.log("warn", "jobs", f"cancel hook failed for {self.job.id}: {exc}")


JobFn = Callable[[JobContext], JobResult | None]


class JobManager:
    def __init__(self) -> None:
        self._jobs: OrderedDict[str, JobContext] = OrderedDict()
        self._lock = threading.Lock()

    def create(self, kind: JobKind, title: str, ref: str | None = None) -> JobContext:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, ref=ref, status="queued", progress=-1,
                  created_at=now_iso())
        ctx = JobContext(job)
        with self._lock:
            self._jobs[job.id] = ctx
            self._trim()
        bus.publish(EvJobUpdate(job=job))
        return ctx

    def start(self, ctx: JobContext, fn: JobFn) -> Job:
        threading.Thread(target=self._run, args=(ctx, fn), name=f"job-{ctx.id}", daemon=True).start()
        return ctx.job

    def submit(self, kind: JobKind, title: str, fn: JobFn, ref: str | None = None) -> Job:
        ctx = self.create(kind, title, ref)
        return self.start(ctx, fn)

    def _run(self, ctx: JobContext, fn: JobFn) -> None:
        if ctx.cancelled:
            ctx.update(status="cancelled", message="Cancelled")
            ctx.done_event.set()
            return
        ctx.update(status="running")
        try:
            result = fn(ctx)
            if ctx.cancelled:
                raise JobCancelled()
            ctx.update(status="done", progress=1.0, result=result, speed_bps=None)
        except JobCancelled:
            ctx.update(status="cancelled", message="Cancelled", speed_bps=None)
        except JobError as exc:
            ctx.update(status="error", error=str(exc), speed_bps=None)
            events.log("error", f"job:{ctx.job.kind}", f"{ctx.job.title}: {exc}")
        except Exception as exc:
            if ctx.cancelled:
                ctx.update(status="cancelled", message="Cancelled", speed_bps=None)
            else:
                ctx.update(status="error", error=f"{type(exc).__name__}: {exc}", speed_bps=None)
                events.log("error", f"job:{ctx.job.kind}",
                           f"{ctx.job.title} failed: {exc}\n{traceback.format_exc(limit=8)}")
        finally:
            ctx.done_event.set()

    def _trim(self) -> None:
        while len(self._jobs) > MAX_JOBS:
            victim = next((jid for jid, c in self._jobs.items() if c.job.status in _FINISHED), None)
            if victim is None:
                return
            del self._jobs[victim]

    def get_ctx(self, job_id: str) -> JobContext | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get(self, job_id: str) -> Job | None:
        ctx = self.get_ctx(job_id)
        return ctx.job if ctx else None

    def list(self) -> list[Job]:
        with self._lock:
            jobs = [c.job for c in self._jobs.values()]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:MAX_JOBS]

    def find_active(self, predicate: Callable[[Job], bool]) -> JobContext | None:
        with self._lock:
            for ctx in self._jobs.values():
                if ctx.job.status in ("queued", "running") and predicate(ctx.job):
                    return ctx
        return None

    def cancel(self, job_id: str) -> Job | None:
        ctx = self.get_ctx(job_id)
        if ctx is None:
            return None
        if ctx.job.status in ("queued", "running"):
            ctx._cancel()
            ctx.update(message="Cancelling…")
        return ctx.job

    def dismiss(self, job_id: str) -> bool:
        with self._lock:
            ctx = self._jobs.get(job_id)
            if ctx is None:
                return False
            if ctx.job.status not in _FINISHED:
                raise ValueError("Job is still running; cancel it first")
            del self._jobs[job_id]
            return True

    def wait_blocking(self, job_id: str, timeout: float | None = None) -> Job:
        ctx = self.get_ctx(job_id)
        if ctx is None:
            raise KeyError(job_id)
        ctx.done_event.wait(timeout)
        return ctx.job

    async def wait(self, job_id: str, poll_s: float = 0.25) -> Job:
        ctx = self.get_ctx(job_id)
        if ctx is None:
            raise KeyError(job_id)
        while not ctx.done_event.is_set():
            await asyncio.sleep(poll_s)
        return ctx.job


jobs = JobManager()


class RateMeter:
    """Exponentially smoothed bytes/s for download progress."""

    def __init__(self) -> None:
        self._last: tuple[float, int] | None = None
        self.bps: float | None = None

    def sample(self, done: int) -> float | None:
        now = time.monotonic()
        if self._last is not None:
            dt = now - self._last[0]
            if dt > 0:
                inst = max(0.0, (done - self._last[1]) / dt)
                self.bps = inst if self.bps is None else 0.7 * self.bps + 0.3 * inst
        self._last = (now, done)
        return self.bps
