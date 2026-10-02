"""Automations: the agent runs a prompt on a schedule (reminders, recurring summaries, condition watches) or when a
trigger fires.

Every run is an agent turn posted in the automation's chat, so reports keep their history and tools work as usual.
That chat is the one the automation was created in when the agent set it up there (its runs continue that
conversation; a run waits its turn while a reply is being written in it), and a chat of its own when the user asked
for one or created it on the Automations page. Schedules are iCal VEVENTs (DTSTART in local time, optional RRULE; at most hourly), or a relative one-off
("in 4 hours") given as ``dateutil.relativedelta`` arguments. A condition watch reports only when its condition
is met: the model answers ``NO_UPDATE`` otherwise, and that quiet exchange is removed from the chat. Runs missed
while the server was off happen once on the next start. Status changes push ``automation.update``; a report, an
error or a pending approval pushes ``automation.run`` (the UI notifies).

A trigger has no schedule. It has a check: a Python script the server runs by itself every few minutes, with no
model involved. Every line the script prints is an item; the lines it has printed before are remembered, and a line
that is new wakes the agent, which is handed the new lines with the prompt. What the check finds when the trigger
is created is the starting point and is not reported. So the model runs only when there is something to do, and a
model that was loaded just for a run is unloaded again afterwards."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrulestr
from pydantic import BaseModel

from . import config, db, events, settings
from .events import bus
from .models import ModelError, models
from .osenv import NO_WINDOW
from .proc import kill_tree
from .runtimes import envs
from .schemas import AgentSession, EvError, EvToolApproval
from .schemas_automations import (Automation, AutomationCreate, AutomationRunStatus, AutomationTiming,
                                  AutomationUpdate, EvAutomationRemoved, EvAutomationRun, EvAutomationUpdate)
from .workspace import state as workspace_state

if TYPE_CHECKING:
    from .agent.loop import AgentService

QUIET = "NO_UPDATE"
TICK_S = 20
_COLUMNS = ("id", "title", "prompt", "schedule", "timing_mode", "enabled", "model", "session_id", "next_run",
            "last_run", "last_status", "last_result", "created_at", "check_code", "check_minutes", "last_check",
            "check_error")
# Triggers: the check runs in the environment of the agent's run_python (requests and the usual libraries)
CHECK_ENV = "python"
CHECKS_DIR = config.DATA_DIR / "automations"  # one folder per trigger: its check.py, and whatever the script keeps
CHECK_TIMEOUT_S = 60
CHECK_MINUTES = 15  # when none is given
BUSY_WAIT_S = 60 * 60  # how long a run waits for its chat while a reply is being written there
MAX_ITEMS = 200  # lines one check may report
MAX_LINE = 600
MAX_SEEN = 5000  # remembered items per trigger
# Models that are loaded into this machine's memory for a run and can be taken out again ("<runtime>:<model id>")
_UNLOADABLE = ("llamacpp", "lmstudio")
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


def describe_check(minutes: int) -> str:
    """A trigger's rhythm in words: "Checks every 15 minutes"."""
    if minutes == 1:
        return "Checks every minute"
    if minutes % 60 == 0:
        hours = minutes // 60
        return "Checks every hour" if hours == 1 else f"Checks every {hours} hours"
    return f"Checks every {minutes} minutes"


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
    # Triggers came later; ``seen`` is the list of item marks a trigger's check has already printed
    have = {r["name"] for r in db.query("PRAGMA table_info(automations)")}
    for name, sql_type in {"check_code": "TEXT", "check_minutes": "INTEGER", "last_check": "TEXT",
                           "check_error": "TEXT", "seen": "TEXT"}.items():
        if name not in have:
            db.execute(f"ALTER TABLE automations ADD COLUMN {name} {sql_type}")


def _row(r: object) -> Automation:
    data = {k: r[k] for k in _COLUMNS}  # type: ignore[index]
    data["enabled"] = bool(data["enabled"])
    data["check"] = data.pop("check_code")
    text = (describe_check(data["check_minutes"] or CHECK_MINUTES) if data["timing_mode"] == "trigger"
            else describe(data["schedule"]))
    return Automation(**data, schedule_text=text)


def list_all() -> list[Automation]:
    return [_row(r) for r in db.query("SELECT * FROM automations ORDER BY created_at DESC")]


def get(automation_id: str) -> Automation:
    r = db.query_one("SELECT * FROM automations WHERE id = ?", (automation_id,))
    if r is None:
        raise AutomationError(f"No automation '{automation_id}'")
    return _row(r)


def _save(a: Automation) -> Automation:
    values = [a.id, a.title, a.prompt, a.schedule, a.timing_mode, int(a.enabled), a.model, a.session_id, a.next_run,
              a.last_run, a.last_status, a.last_result, a.created_at, a.check, a.check_minutes, a.last_check,
              a.check_error]
    # An update in place: replacing the row would drop what the trigger has seen
    db.execute(f"INSERT INTO automations({', '.join(_COLUMNS)}) VALUES({', '.join('?' * len(_COLUMNS))}) "
               f"ON CONFLICT(id) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in _COLUMNS[1:])}", values)
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


def _next_check(minutes: int | None) -> str | None:
    return _utc_iso(datetime.now() + timedelta(minutes=minutes or CHECK_MINUTES))


def create(req: AutomationCreate, origin_session_id: str | None = None, automation_id: str | None = None,
           known: list[str] | None = None, new_chat: bool = False) -> Automation:
    """``origin_session_id``: the chat the agent creates it in; its runs are posted there unless ``new_chat`` asks
    for a chat of its own. ``known``: for a trigger, the items its check prints right now - where it starts from,
    not news."""
    title = req.title.strip()
    origin = db.get_session(origin_session_id) if origin_session_id else None
    model = req.model or (origin.model if origin else None)
    if origin is not None and not new_chat:
        session_id = origin.id
    else:
        session_id = _session_for(title, model, origin_session_id)
    if req.timing_mode == "trigger":
        if not (req.check or "").strip():
            raise AutomationError("A trigger needs a check: a Python script that prints one line per item")
        minutes = req.check_minutes or CHECK_MINUTES
        vevent, text, next_run = "", describe_check(minutes), _next_check(minutes)
        check: str | None = req.check
    else:
        vevent = normalize(req.schedule, req.dtstart_offset_json, req.timing_mode)
        text, next_run, check, minutes = describe(vevent), _utc_iso(next_after(vevent, datetime.now())), None, None
    a = Automation(id=automation_id or uuid.uuid4().hex[:10], title=title, prompt=req.prompt.strip(),
                   schedule=vevent, schedule_text=text, timing_mode=req.timing_mode, enabled=True, model=model,
                   session_id=session_id, next_run=next_run,
                   created_at=db.now_iso(), check=check, check_minutes=minutes,
                   last_check=db.now_iso() if known is not None else None)
    events.log("info", "automations", f"Created '{a.title}': {a.schedule_text}")
    saved = _save(a)
    if known is not None:
        _remember(a.id, known)
    return saved


def update(automation_id: str, req: AutomationUpdate) -> Automation:
    a = get(automation_id)
    changes = req.model_dump(exclude_unset=True)
    timing = changes.get("timing_mode") or a.timing_mode
    offset = changes.pop("dtstart_offset_json", None)
    if timing == "trigger":
        if not (changes.get("check") or a.check or "").strip():
            raise AutomationError("A trigger needs a check: a Python script that prints one line per item")
        if not changes.get("check"):
            changes.pop("check", None)
        changes["schedule"] = ""
        changes["check_minutes"] = changes.get("check_minutes") or a.check_minutes or CHECK_MINUTES
        updated = a.model_copy(update=changes)
        # Changing the rhythm (or resuming) counts from now; anything else leaves the next check where it was
        moved = updated.check_minutes != a.check_minutes or not a.enabled or a.timing_mode != "trigger"
        updated.next_run = (_next_check(updated.check_minutes) if moved or not a.next_run else a.next_run
                            ) if updated.enabled else None
    else:
        if changes.get("schedule") or offset:
            changes["schedule"] = normalize(changes.get("schedule"), offset, timing)
        else:
            changes.pop("schedule", None)
            if "timing_mode" in changes or not a.schedule:
                normalize(a.schedule, None, timing)  # it must have a schedule, and a watch must still repeat
        changes.update(check=None, check_minutes=None, check_error=None)
        updated = a.model_copy(update=changes)
        updated.next_run = _utc_iso(next_after(updated.schedule, datetime.now())) if updated.enabled else None
    if db.get_session(updated.session_id) is None:
        updated.session_id = _session_for(updated.title, updated.model, None)
    return _save(updated)


def delete(automation_id: str) -> Automation:
    a = get(automation_id)
    db.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
    shutil.rmtree(CHECKS_DIR / automation_id, ignore_errors=True)
    bus.publish(EvAutomationRemoved(id=automation_id))
    return a


# ------------------------------ triggers ------------------------------


def _mark(item: str) -> str:
    return hashlib.sha1(item.encode("utf-8", "replace")).hexdigest()[:16]


def _seen(automation_id: str) -> list[str]:
    """Marks of the items this trigger's check has printed before, oldest first."""
    r = db.query_one("SELECT seen FROM automations WHERE id = ?", (automation_id,))
    try:
        return list(json.loads(r["seen"])) if r and r["seen"] else []
    except ValueError:
        return []


def _remember(automation_id: str, items: list[str], keep: list[str] | None = None) -> None:
    """Record ``items`` as seen. What a check still prints moves to the young end, so a long-standing item is not
    forgotten (and reported again) once the list is full."""
    marks = [_mark(i) for i in items]
    current = set(marks)
    seen = [m for m in (_seen(automation_id) if keep is None else keep) if m not in current] + marks
    db.execute("UPDATE automations SET seen = ? WHERE id = ?", (json.dumps(seen[-MAX_SEEN:]), automation_id))


def _check_blocking(automation_id: str, code: str) -> list[str]:
    if not envs.is_ready(CHECK_ENV):
        raise AutomationError("The Python tools aren't installed yet. They install the first time the assistant runs "
                              "Python in a chat; create the trigger after that.")
    folder = CHECKS_DIR / automation_id
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "check.py"
    script.write_text(code, encoding="utf-8")
    proc = subprocess.Popen([str(envs.env_python(CHECK_ENV)), "-u", str(script)], cwd=folder,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        out, err = proc.communicate(timeout=CHECK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        proc.communicate()
        raise AutomationError(f"The check ran longer than {CHECK_TIMEOUT_S} s and was stopped") from None
    if proc.returncode != 0:
        raise AutomationError(f"The check failed (exit code {proc.returncode}):\n{(err or out).strip()[-1500:]}")
    items: list[str] = []
    for line in out.splitlines():
        item = line.strip()[:MAX_LINE]
        if item and item not in items:
            items.append(item)
    return items[:MAX_ITEMS]


async def run_check(automation_id: str, code: str) -> list[str]:
    """Run a trigger's check: the items it prints (one per line, in order, without repeats). Raises AutomationError
    with the script's own error when it fails or takes too long."""
    return await asyncio.to_thread(_check_blocking, automation_id, code)


async def create_checked(req: AutomationCreate, origin_session_id: str | None = None,
                         new_chat: bool = False) -> tuple[Automation, list[str]]:
    """Create an automation. A trigger's check runs first: a script that fails is refused with its error, and what
    it prints now (returned) is where the trigger starts from."""
    if req.timing_mode != "trigger":
        return create(req, origin_session_id, new_chat=new_chat), []
    if not (req.check or "").strip():
        raise AutomationError("A trigger needs a check: a Python script that prints one line per item")
    automation_id = uuid.uuid4().hex[:10]
    try:
        known = await run_check(automation_id, req.check or "")
        return create(req, origin_session_id, automation_id, known, new_chat), known
    except AutomationError:
        shutil.rmtree(CHECKS_DIR / automation_id, ignore_errors=True)
        raise


async def update_checked(automation_id: str, req: AutomationUpdate) -> tuple[Automation, list[str] | None]:
    """Change an automation. A new check (or becoming a trigger) is run first, and the trigger starts over from
    what it prints: a changed script words its items differently, and they would all look new."""
    a = get(automation_id)
    becomes = (req.timing_mode or a.timing_mode) == "trigger"
    code = (req.check or a.check or "") if becomes else ""
    fresh_start = becomes and (a.timing_mode != "trigger" or code.strip() != (a.check or "").strip())
    known = await run_check(a.id, code) if fresh_start and code.strip() else None
    updated = update(automation_id, req)
    if known is not None:
        _remember(a.id, known, keep=[])
        updated = _save(updated.model_copy(update={"last_check": db.now_iso(), "check_error": None}))
    return updated, known


# ------------------------------ runner ------------------------------


def _instruction(a: Automation, items: list[str] | None = None) -> str:
    when = datetime.now().astimezone()
    if items:
        many = len(items) != 1
        head = (f"[Trigger “{a.title}”, set up by the user, fired now ({when:%A %Y-%m-%d %H:%M %Z}): its check "
                f"found {len(items)} new item{'s' if many else ''}. Nobody is watching, so work on your own. Write "
                "the result for the user; the start of your reply is sent as a notification. If, after looking, "
                f"nothing here is worth their attention, reply with exactly {QUIET} and nothing else.]")
        listing = "\n".join(f"- {i}" for i in items)
        return f"{head}\n\nNew item{'s' if many else ''}:\n{listing}\n\n{a.prompt}"
    head = (f"[Scheduled automation “{a.title}”, set up by the user; running now, "
            f"{when:%A %Y-%m-%d %H:%M %Z}.]")
    if a.timing_mode == "trigger":  # run by hand: nothing new came in
        rule = ("Its check found nothing new; the user asked for a run anyway. Do it now with what is known and "
                "write the result for the user.")
        return f"{head} {rule}\n\n{a.prompt}"
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
        self._checking: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()  # checks and runs in flight (kept so they are not collected)

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
            if not (a.enabled and a.next_run and a.next_run <= now):
                continue
            if a.timing_mode == "trigger":
                if a.id not in self._checking:
                    self._start_check(a)
            elif a.id not in self._running:
                self.run_now(a.id)

    def _spawn(self, coro: object, name: str) -> None:
        task = asyncio.get_running_loop().create_task(coro, name=name)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def run_now(self, automation_id: str) -> Automation:
        """Run it now. For a trigger that is its check: the agent is woken if the check finds something new."""
        a = get(automation_id)
        if self._agent is None:
            raise AutomationError("The agent isn't ready yet")
        if a.timing_mode == "trigger":
            if a.id in self._checking or a.id in self._running:
                raise AutomationError("It's already running")
            return self._start_check(a)
        if a.id in self._running:
            raise AutomationError("It's already running")
        self._running.add(a.id)
        # the next run is scheduled from now, so a long run or a restart doesn't fire it twice
        a = _save(a.model_copy(update={"next_run": _utc_iso(next_after(a.schedule, datetime.now()))}))
        self._spawn(self._run(a), f"automation-{a.id}")
        return a

    def _start_check(self, a: Automation) -> Automation:
        self._checking.add(a.id)
        a = _save(a.model_copy(update={"next_run": _next_check(a.check_minutes) if a.enabled else None}))
        self._spawn(self._check(a), f"automation-check-{a.id}")
        return a

    async def _check(self, a: Automation) -> None:
        """One look by a trigger's script; new items wake the agent."""
        try:
            error: str | None = None
            items: list[str] = []
            try:
                items = await run_check(a.id, a.check or "")
            except AutomationError as exc:
                error = str(exc)
            try:
                current = get(a.id)
            except AutomationError:
                return  # deleted meanwhile
            failing = current.check_error is not None
            current = _save(current.model_copy(update={"last_check": db.now_iso(), "check_error": error}))
            if error is not None:
                if not failing:  # said once, not at every check
                    events.log("warn", "automations", f"The check of '{a.title}' failed: {error}")
                    reason = error.strip().splitlines()[-1]  # of a traceback, the line that says what
                    bus.publish(EvAutomationRun(automation_id=a.id, title=a.title, status="error",
                                                message=f"Its check failed: {reason}"[:300],
                                                session_id=current.session_id))
                return
            seen = _seen(a.id)
            known = set(seen)
            fresh = [i for i in items if _mark(i) not in known]
            if fresh and a.id in self._running:
                return  # still working on the last ones: these stay new until the next check
            _remember(a.id, items, keep=seen)
            if fresh:
                events.log("info", "automations", f"'{a.title}' fired: {len(fresh)} new item(s)")
                self._running.add(a.id)
                self._spawn(self._run(current, fresh), f"automation-{a.id}")
        except Exception as exc:  # noqa: BLE001 - one bad check must not end the scheduler's task quietly
            events.log("error", "automations", f"Checking '{a.title}' failed: {exc}")
        finally:
            self._checking.discard(a.id)

    async def _run(self, a: Automation, items: list[str] | None = None) -> None:
        status: AutomationRunStatus = "error"
        message = ""
        try:
            status, message = await self._turn(a, items)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            events.log("error", "automations", f"'{a.title}' failed: {exc}")
        finally:
            self._running.discard(a.id)
        try:
            current = get(a.id)
        except AutomationError:
            return  # deleted while running
        done = current.timing_mode != "trigger" and current.next_run is None and "RRULE" not in current.schedule
        _save(current.model_copy(update={"last_run": db.now_iso(), "last_status": status,
                                         "last_result": message[:500] or None,
                                         "enabled": current.enabled and not done}))
        events.log("info", "automations", f"'{a.title}' ran: {status}")
        if status != "quiet":
            bus.publish(EvAutomationRun(automation_id=a.id, title=a.title, status=status, message=message[:300],
                                        session_id=current.session_id))

    async def _turn(self, a: Automation, items: list[str] | None = None) -> tuple[AutomationRunStatus, str]:
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

        # Its chat may be one the user talks in: a run takes its turn after the reply being written there
        waited = 0
        while self._agent.busy(session.id):
            if waited >= BUSY_WAIT_S:
                raise AutomationError("its chat was busy for an hour; the run was skipped")
            await asyncio.sleep(5)
            waited += 5
        session = db.get_session(a.session_id) or session
        runtime, _, model_id = session.model.partition(":")
        borrowed = runtime in _UNLOADABLE and not _is_loaded(model_id)  # the run loads the model: it gives it back
        turn = self._agent.start(session, _instruction(a, items), listen)
        assert turn.task is not None
        await asyncio.wait({turn.task})
        if borrowed and not self._agent.active_turns():
            await self._unload(model_id, a.title)
        reply = turn.reply.content.strip()
        if errors and not reply:
            return "error", errors[-1]
        if reply.strip(" .`*\"'") == QUIET or reply.endswith(QUIET):
            self._forget_quiet(a.session_id, turn.user_message.id)
            return "quiet", ""
        return "reported", reply

    @staticmethod
    async def _unload(model_id: str, title: str) -> None:
        """Take a model that was loaded only for a run out of memory again, so a run in the background leaves the
        machine the way it found it."""
        try:
            if _is_loaded(model_id):
                await asyncio.to_thread(models.unload, model_id)
                events.log("info", "automations", f"Unloaded {model_id} after '{title}' (it was loaded for the run)")
        except Exception as exc:  # noqa: BLE001 - the run itself is done
            events.log("warn", "automations", f"Could not unload {model_id} after '{title}': {exc}")

    @staticmethod
    def _forget_quiet(session_id: str, user_message_id: str) -> None:
        """A watch with nothing to report leaves no trace in its chat (else it fills with NO_UPDATE)."""
        found = db.find_message(session_id, user_message_id)
        if found:
            db.delete_messages_from(session_id, found[0])


def _is_loaded(model_id: str) -> bool:
    try:
        return models.get(model_id).status == "loaded"
    except ModelError:
        return False


runner = AutomationRunner()
