"""Automations: the agent runs a prompt on a schedule (reminders, recurring summaries, condition watches).

Each automation owns a chat; every run is an agent turn posted there, so reports keep their history and tools work
as usual. Schedules are iCal VEVENTs (DTSTART in local time, optional RRULE; at most hourly), or a relative one-off
("in 4 hours") given as ``dateutil.relativedelta`` arguments. A condition watch reports only when its condition
is met: the model answers ``NO_UPDATE`` otherwise, and that quiet exchange is removed from the chat. Runs missed
while the server was off happen once on the next start. Status changes push ``automation.update``; a report, an
error or a pending approval pushes ``automation.run`` (the UI notifies)."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrulestr
from pydantic import BaseModel

from . import db, events, settings
from .events import bus
from .schemas import AgentSession, EvError, EvToolApproval
from .schemas_automations import (Automation, AutomationCreate, AutomationRunStatus, AutomationTiming,
                                  AutomationUpdate, EvAutomationRemoved, EvAutomationRun, EvAutomationUpdate)
from .workspace import state as workspace_state

if TYPE_CHECKING:
    from .agent.loop import AgentService

QUIET = "NO_UPDATE"
TICK_S = 20
_COLUMNS = ("id", "title", "prompt", "schedule", "timing_mode", "enabled", "model", "session_id", "next_run",
            "last_run", "last_status", "last_result", "created_at")
_DAYS = {"MO": "Monday", "TU": "Tuesday", "WE": "Wednesday", "TH": "Thursday", "FR": "Friday", "SA": "Saturday",
         "SU": "Sunday"}


class AutomationError(ValueError):
    """User-facing reason an automation can't be created or changed."""


# ------------------------------ schedules ------------------------------


def _fields(vevent: str) -> dict[str, str]:
    """``DTSTART`` / ``RRULE`` (and their parameters) from a VEVENT or bare lines."""
    out: dict[str, str] = {}
    for raw in vevent.replace("\\n", "\n").splitlines():
        line = raw.strip()
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        name = head.split(";", 1)[0].upper()
        if name in ("DTSTART", "RRULE"):
            out[name] = value.strip()
            if name == "DTSTART" and ";" in head:
                out["DTSTART_PARAMS"] = head.split(";", 1)[1]
    return out


def _local_dt(value: str, params: str = "") -> datetime:
    """A DTSTART value as a naive local datetime (UTC 'Z' and TZID= values are converted)."""
    v = value.strip()
    try:
        if v.endswith("Z"):
            return datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        dt = datetime.strptime(v, "%Y%m%dT%H%M%S") if "T" in v else datetime.strptime(v, "%Y%m%d").replace(hour=9)
    except ValueError as exc:
        raise AutomationError(f"DTSTART {value!r} isn't a date-time like 20260611T080000") from exc
    m = re.search(r"TZID=([^;:]+)", params or "")
    if m:
        from zoneinfo import ZoneInfo

        try:
            dt = dt.replace(tzinfo=ZoneInfo(m.group(1))).astimezone().replace(tzinfo=None)
        except (KeyError, ValueError):
            pass
    return dt


def normalize(schedule: str | None, offset_json: str | None, timing: AutomationTiming) -> str:
    """A clean VEVENT (DTSTART in local time + optional RRULE), validated. Raises AutomationError."""
    now = datetime.now().replace(second=0, microsecond=0)
    f = _fields(schedule or "")
    if offset_json:
        try:
            offset = relativedelta(**json.loads(offset_json))
        except (ValueError, TypeError) as exc:
            raise AutomationError(f"dtstart_offset_json {offset_json!r} isn't relativedelta arguments like "
                                  '{"hours": 4}') from exc
        start = datetime.now().replace(microsecond=0) + offset
    elif "DTSTART" in f:
        start = _local_dt(f["DTSTART"], f.get("DTSTART_PARAMS", ""))
    elif "RRULE" in f:
        start = now
    else:
        raise AutomationError("Give a schedule (an iCal VEVENT with DTSTART and/or RRULE) or dtstart_offset_json")
    rule = f.get("RRULE", "").upper()
    if rule:
        freq = re.search(r"FREQ=(\w+)", rule)
        if not freq:
            raise AutomationError(f"RRULE {rule!r} has no FREQ")
        if freq.group(1) in ("SECONDLY", "MINUTELY"):
            raise AutomationError("Automations run at most once an hour")
        rule = re.sub(r";?DTEND=[^;]*", "", rule)
    elif timing == "condition_watch":
        raise AutomationError("A condition watch must repeat: add an RRULE (e.g. FREQ=HOURLY or FREQ=DAILY)")
    text = f"BEGIN:VEVENT\nDTSTART:{start:%Y%m%dT%H%M%S}\n" + (f"RRULE:{rule}\n" if rule else "") + "END:VEVENT"
    if next_after(text, datetime.now() - timedelta(minutes=1)) is None:
        raise AutomationError("That schedule has no run in the future")
    return text


def _rule_text(vevent: str) -> str:
    f = _fields(vevent)
    return f"DTSTART:{f['DTSTART']}" + (f"\nRRULE:{f['RRULE']}" if "RRULE" in f else "")


def next_after(vevent: str, after: datetime) -> datetime | None:
    """The first run strictly after ``after`` (naive local), or None."""
    f = _fields(vevent)
    if "RRULE" not in f:
        start = _local_dt(f["DTSTART"])
        return start if start > after else None
    rule = rrulestr(_rule_text(vevent))
    return rule.after(after)  # type: ignore[union-attr]


def describe(vevent: str) -> str:
    """The schedule in words: "Every Monday and Wednesday at 15:00", "Once on Sep 30, 2026 at 08:00"."""
    f = _fields(vevent)
    start = _local_dt(f["DTSTART"])
    at = f"{start:%H:%M}"
    rule = f.get("RRULE")
    if not rule:
        return f"Once on {start:%a, %b} {start.day}, {start.year} at {at}"
    parts = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
    freq, n = parts.get("FREQ", "DAILY"), int(parts.get("INTERVAL", "1"))
    every = "Every" if n == 1 else f"Every {n}"
    if freq == "HOURLY":
        text = "Every hour" if n == 1 else f"Every {n} hours"
    elif freq == "DAILY":
        text = f"{every} day{'s' if n > 1 else ''} at {at}"
    elif freq == "WEEKLY":
        days = [_DAYS.get(d[-2:], d) for d in parts.get("BYDAY", "").split(",") if d] or [f"{start:%A}"]
        joined = days[0] if len(days) == 1 else ", ".join(days[:-1]) + " and " + days[-1]
        text = (f"Every {joined}" if n == 1 else f"Every {n} weeks on {joined}") + f" at {at}"
    elif freq == "MONTHLY":
        day = parts.get("BYMONTHDAY", str(start.day))
        text = f"{every} month{'s' if n > 1 else ''} on day {day} at {at}"
    elif freq == "YEARLY":
        text = f"Every year on {start:%b} {start.day} at {at}"
    else:
        text = rule
    if "COUNT" in parts:
        text += f", {parts['COUNT']} times"
    if "UNTIL" in parts:
        try:
            until = _local_dt(parts["UNTIL"] if "T" in parts["UNTIL"] else parts["UNTIL"] + "T235959")
            text += f", until {until:%b} {until.day}, {until.year}"
        except AutomationError:
            pass
    return text


def _utc_iso(local: datetime | None) -> str | None:
    if local is None:
        return None
    return local.astimezone().astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ------------------------------ storage ------------------------------


def init() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS automations (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL, schedule TEXT NOT NULL,
        timing_mode TEXT NOT NULL, enabled INTEGER NOT NULL, model TEXT, session_id TEXT NOT NULL, next_run TEXT,
        last_run TEXT, last_status TEXT, last_result TEXT, created_at TEXT NOT NULL)""")


def _row(r: object) -> Automation:
    data = {k: r[k] for k in _COLUMNS}  # type: ignore[index]
    data["enabled"] = bool(data["enabled"])
    return Automation(**data, schedule_text=describe(data["schedule"]))


def list_all() -> list[Automation]:
    return [_row(r) for r in db.query("SELECT * FROM automations ORDER BY created_at DESC")]


def get(automation_id: str) -> Automation:
    r = db.query_one("SELECT * FROM automations WHERE id = ?", (automation_id,))
    if r is None:
        raise AutomationError(f"No automation '{automation_id}'")
    return _row(r)


def _save(a: Automation) -> Automation:
    values = [a.id, a.title, a.prompt, a.schedule, a.timing_mode, int(a.enabled), a.model, a.session_id, a.next_run,
              a.last_run, a.last_status, a.last_result, a.created_at]
    db.execute(f"INSERT OR REPLACE INTO automations({', '.join(_COLUMNS)}) VALUES({', '.join('?' * len(_COLUMNS))})",
               values)
    saved = get(a.id)
    bus.publish(EvAutomationUpdate(automation=saved))
    return saved


def _default_model() -> str | None:
    s = settings.load()
    return s.default_chat_model


def _session_for(title: str, model: str | None, origin_session_id: str | None) -> str:
    model = model or _default_model()
    if not model:
        raise AutomationError("Pick a chat model first (Settings → default chat model): automations run with it")
    now = db.now_iso()
    session = AgentSession(id=uuid.uuid4().hex[:16], title=f"Automation · {title}", model=model, mode="agent",
                           created_at=now, updated_at=now)
    db.insert_session(session)
    root = workspace_state.get(origin_session_id).root if origin_session_id else None
    if root:
        workspace_state.set_root(session.id, root)
    return session.id


def create(req: AutomationCreate, origin_session_id: str | None = None) -> Automation:
    vevent = normalize(req.schedule, req.dtstart_offset_json, req.timing_mode)
    origin = db.get_session(origin_session_id) if origin_session_id else None
    model = req.model or (origin.model if origin else None)
    a = Automation(id=uuid.uuid4().hex[:10], title=req.title.strip(), prompt=req.prompt.strip(), schedule=vevent,
                   schedule_text=describe(vevent), timing_mode=req.timing_mode, enabled=True, model=model,
                   session_id=_session_for(req.title.strip(), model, origin_session_id),
                   next_run=_utc_iso(next_after(vevent, datetime.now())), created_at=db.now_iso())
    events.log("info", "automations", f"Created '{a.title}': {a.schedule_text}")
    return _save(a)


def update(automation_id: str, req: AutomationUpdate) -> Automation:
    a = get(automation_id)
    changes = req.model_dump(exclude_unset=True)
    timing = changes.get("timing_mode") or a.timing_mode
    if changes.get("schedule") or changes.get("dtstart_offset_json"):
        changes["schedule"] = normalize(changes.get("schedule"), changes.get("dtstart_offset_json"), timing)
    elif "timing_mode" in changes:
        normalize(a.schedule, None, timing)  # a watch must still repeat
    changes.pop("dtstart_offset_json", None)
    if not changes.get("schedule"):
        changes.pop("schedule", None)
    updated = a.model_copy(update=changes)
    updated.next_run = _utc_iso(next_after(updated.schedule, datetime.now())) if updated.enabled else None
    if db.get_session(updated.session_id) is None:
        updated.session_id = _session_for(updated.title, updated.model, None)
    return _save(updated)


def delete(automation_id: str) -> Automation:
    a = get(automation_id)
    db.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
    bus.publish(EvAutomationRemoved(id=automation_id))
    return a


# ------------------------------ runner ------------------------------


def _instruction(a: Automation) -> str:
    when = datetime.now().astimezone()
    head = (f"[Scheduled automation “{a.title}”, set up by the user; running now, "
            f"{when:%A %Y-%m-%d %H:%M %Z}.]")
    if a.timing_mode == "condition_watch":
        rule = (f"This is a recurring check. If the condition isn't met or nothing meaningful changed since the last "
                f"check (see earlier runs in this chat), reply with exactly {QUIET} and nothing else. Otherwise "
                "report what happened, briefly - it is sent to the user as a notification.")
    else:
        rule = "Do it now and write the result for the user; the start of your reply is sent as a notification."
    return f"{head} {rule}\n\n{a.prompt}"


class AutomationRunner:
    def __init__(self) -> None:
        self._agent: AgentService | None = None
        self._loop: asyncio.Task[None] | None = None
        self._running: set[str] = set()

    def start(self, agent: AgentService) -> None:
        self._agent = agent
        self._loop = asyncio.create_task(self._tick_forever(), name="automations")

    async def shutdown(self) -> None:
        if self._loop:
            self._loop.cancel()
            await asyncio.gather(self._loop, return_exceptions=True)
        self._loop = None

    async def _tick_forever(self) -> None:
        await asyncio.sleep(5)  # let the server finish starting
        while True:
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - a bad row must not stop the scheduler
                events.log("error", "automations", f"Scheduler error: {exc}")
            await asyncio.sleep(TICK_S)

    def _tick(self) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        for a in list_all():
            if a.enabled and a.next_run and a.next_run <= now and a.id not in self._running:
                self.run_now(a.id)

    def run_now(self, automation_id: str) -> Automation:
        a = get(automation_id)
        if a.id in self._running:
            raise AutomationError("It's already running")
        if self._agent is None:
            raise AutomationError("The agent isn't ready yet")
        self._running.add(a.id)
        # the next run is scheduled from now, so a long run or a restart doesn't fire it twice
        a = _save(a.model_copy(update={"next_run": _utc_iso(next_after(a.schedule, datetime.now()))}))
        asyncio.get_running_loop().create_task(self._run(a), name=f"automation-{a.id}")
        return a

    async def _run(self, a: Automation) -> None:
        status: AutomationRunStatus = "error"
        message = ""
        try:
            status, message = await self._turn(a)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            events.log("error", "automations", f"'{a.title}' failed: {exc}")
        finally:
            self._running.discard(a.id)
        try:
            current = get(a.id)
        except AutomationError:
            return  # deleted while running
        done = current.next_run is None and "RRULE" not in current.schedule
        _save(current.model_copy(update={"last_run": db.now_iso(), "last_status": status,
                                         "last_result": message[:500] or None,
                                         "enabled": current.enabled and not done}))
        events.log("info", "automations", f"'{a.title}' ran: {status}")
        if status != "quiet":
            bus.publish(EvAutomationRun(automation_id=a.id, title=a.title, status=status, message=message[:300],
                                        session_id=current.session_id))

    async def _turn(self, a: Automation) -> tuple[AutomationRunStatus, str]:
        assert self._agent is not None
        session = db.get_session(a.session_id)
        if session is None:
            a = _save(a.model_copy(update={"session_id": _session_for(a.title, a.model, None)}))
            session = db.get_session(a.session_id)
            assert session is not None
        errors: list[str] = []
        asked: list[bool] = []

        def listen(event: BaseModel) -> None:
            if isinstance(event, EvError):
                errors.append(event.message)
            elif isinstance(event, EvToolApproval) and not asked:
                asked.append(True)  # tell the user once: the run waits in its chat
                bus.publish(EvAutomationRun(automation_id=a.id, title=a.title, status="needs_approval",
                                            message="Waiting for your approval in its chat", session_id=a.session_id))

        turn = self._agent.start(session, _instruction(a), listen)
        assert turn.task is not None
        await asyncio.wait({turn.task})
        reply = turn.reply.content.strip()
        if errors and not reply:
            return "error", errors[-1]
        if reply.strip(" .`*\"'") == QUIET or reply.endswith(QUIET):
            self._forget_quiet(a.session_id, turn.user_message.id)
            return "quiet", ""
        return "reported", reply

    @staticmethod
    def _forget_quiet(session_id: str, user_message_id: str) -> None:
        """A watch with nothing to report leaves no trace in its chat (else it fills with NO_UPDATE)."""
        found = db.find_message(session_id, user_message_id)
        if found:
            db.delete_messages_from(session_id, found[0])


runner = AutomationRunner()
