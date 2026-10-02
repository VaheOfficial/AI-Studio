"""Agent tools for automations (``studio/automations.py``): create, update, list and delete prompts that run on a
schedule or when a trigger's check finds something new."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .. import automations
from ..schemas_automations import Automation, AutomationCreate, AutomationUpdate
from ..schemas_workspace import AutomationDisplay
from . import python_tools
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

_TIMING = {"type": "string", "enum": ["exact_schedule", "flexible_schedule", "condition_watch", "trigger"]}
_SCHEDULE = {"type": "string", "description": "iCal VEVENT lines: DTSTART:YYYYMMDDTHHMMSS in the user's local time "
                                             "and/or RRULE:FREQ=...;... (no SUMMARY/DTEND)"}
_OFFSET = {"type": "string", "description": 'Relative one-off start as dateutil.relativedelta JSON, e.g. '
                                           '{"hours": 4} or {"days": 3}'}

_CHECK = {"type": "string", "description": "timing_mode trigger only: a Python script the app runs by itself, "
                                           "without you. It prints one line per item that matters right now, a "
                                           "stable id first (CVE-2026-1234 | 9.8 | title | url); a line it never "
                                           "printed before wakes you"}
_MINUTES = {"type": "integer", "description": "timing_mode trigger only: minutes between checks, 1-1440 (default 15)"}


def _runs_code(args: dict[str, Any]) -> str | None:
    """A check is code that keeps running unattended: asked for like run_python."""
    return "run_python" if args.get("check") else None


SPECS: list[ToolSpec] = [
    ToolSpec(
        "automation_create",
        "Set up a prompt for you to run later, repeatedly, or whenever a trigger fires (a reminder, a recurring "
        "summary, a condition watch, 'every time a new ... appears'). Each run is posted in this chat, continuing "
        "this conversation, and notifies the user.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Short card headline, 2-5 words"},
            "prompt": {"type": "string", "description": "Imperative instruction to yourself for each run, keeping "
                                                        "the user's intent and qualifiers; no schedule in it"},
            "timing_mode": _TIMING, "schedule": _SCHEDULE, "dtstart_offset_json": _OFFSET,
            "check": _CHECK, "check_minutes": _MINUTES,
            "new_chat": {"type": "boolean", "description": "Only when the user asks for a separate chat: the runs "
                                                           "are posted in a new chat of their own instead of this one"},
        }, "required": ["title", "prompt", "timing_mode"]},
        asks_like=_runs_code,
    ),
    ToolSpec(
        "automation_update",
        "Change an automation: its title, prompt, schedule, timing mode or check, or pause/resume it (enabled).",
        {"type": "object", "properties": {
            "id": {"type": "string"}, "title": {"type": "string"}, "prompt": {"type": "string"},
            "timing_mode": _TIMING, "schedule": _SCHEDULE, "dtstart_offset_json": _OFFSET,
            "check": _CHECK, "check_minutes": _MINUTES, "enabled": {"type": "boolean"},
        }, "required": ["id"]},
        asks_like=_runs_code,
    ),
    ToolSpec("automation_list", "List the user's automations (ids, schedules, next and last runs). Use it to find "
                                "one before changing it.", {"type": "object", "properties": {}}),
    ToolSpec("automation_delete", "Delete an automation for good (the chat it ran in stays).",
             {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, needs_approval=True),
]


def _display(a: Automation) -> AutomationDisplay:
    return AutomationDisplay(automation_id=a.id, title=a.title, schedule=a.schedule_text, next_run=a.next_run)


def _summary(a: Automation) -> str:
    state = "on" if a.enabled else "paused"
    if a.timing_mode == "trigger":
        check = f"check failing: {a.check_error.splitlines()[0][:120]}" if a.check_error else "check ok"
        return (f"[{a.id}] {a.title} - {a.schedule_text} (trigger, {state}); {check}; last woken "
                f"{a.last_run or 'never'}")
    return (f"[{a.id}] {a.title} - {a.schedule_text} ({a.timing_mode}, {state}); next run {a.next_run or 'none'}; "
            f"last {a.last_status or 'never'}")


def _baseline(known: list[str]) -> str:
    """What a trigger's first check found, said so the model can tell its script works."""
    if not known:
        return ("The check ran and printed nothing right now, which is fine if nothing matches yet; if something "
                "should have matched, fix the script with automation_update.")
    shown = "\n".join(f"- {i}" for i in known[:5])
    more = f"\n(and {len(known) - 5} more)" if len(known) > 5 else ""
    return (f"The check ran and printed {len(known)} item(s). They are the starting point and are not reported:\n"
            f"{shown}{more}")


async def _create(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    new_chat = bool(a.pop("new_chat", False))
    try:
        req = AutomationCreate(**a)
        if req.timing_mode == "trigger":
            await python_tools._ensure_env(ctx, req.check or "")
        created, known = await automations.create_checked(req, origin_session_id=ctx.session_id, new_chat=new_chat)
    except (automations.AutomationError, ValueError) as exc:
        raise ToolFailure(str(exc)) from exc
    where = (f"Its runs appear in a chat of their own, “{'Automation · ' + created.title}”." if new_chat
             else "Its runs are posted in this chat.")
    if created.timing_mode == "trigger":
        return ToolOutcome(True, f"Created {_summary(created)}. {_baseline(known)}\nFrom now on the app runs the "
                                 f"check by itself and wakes you only for lines that are new. {where}",
                           display=_display(created))
    return ToolOutcome(True, f"Created {_summary(created)}. {where}", display=_display(created))


async def _update(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    automation_id = a.pop("id")
    try:
        req = AutomationUpdate(**a)
        if req.check:
            await python_tools._ensure_env(ctx, req.check)
        updated, known = await automations.update_checked(automation_id, req)
    except (automations.AutomationError, ValueError) as exc:
        raise ToolFailure(str(exc)) from exc
    return ToolOutcome(True, f"Updated {_summary(updated)}" + (f". {_baseline(known)}" if known is not None else ""),
                       display=_display(updated))


async def _list(_a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    found = automations.list_all()
    return ToolOutcome(True, "\n".join(_summary(x) for x in found) or "No automations yet.")


async def _delete(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    try:
        gone = automations.delete(a["id"])
    except automations.AutomationError as exc:
        raise ToolFailure(str(exc)) from exc
    return ToolOutcome(True, f"Deleted '{gone.title}'")


IMPL: dict[str, Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]] = {
    "automation_create": _create, "automation_update": _update, "automation_list": _list,
    "automation_delete": _delete,
}
