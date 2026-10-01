"""Agent tools for automations (``studio/automations.py``): create, update, list and delete scheduled prompts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .. import automations
from ..schemas_automations import Automation, AutomationCreate, AutomationUpdate
from ..schemas_workspace import AutomationDisplay
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

_TIMING = {"type": "string", "enum": ["exact_schedule", "flexible_schedule", "condition_watch"]}
_SCHEDULE = {"type": "string", "description": "iCal VEVENT lines: DTSTART:YYYYMMDDTHHMMSS in the user's local time "
                                             "and/or RRULE:FREQ=...;... (no SUMMARY/DTEND)"}
_OFFSET = {"type": "string", "description": 'Relative one-off start as dateutil.relativedelta JSON, e.g. '
                                           '{"hours": 4} or {"days": 3}'}

SPECS: list[ToolSpec] = [
    ToolSpec(
        "automation_create",
        "Schedule a prompt for you to run later or repeatedly (a reminder, a recurring summary, a condition watch). "
        "Each run is posted in the automation's own chat and notifies the user.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Short card headline, 2-5 words"},
            "prompt": {"type": "string", "description": "Imperative instruction to yourself for each run, keeping "
                                                        "the user's intent and qualifiers; no schedule in it"},
            "timing_mode": _TIMING, "schedule": _SCHEDULE, "dtstart_offset_json": _OFFSET,
        }, "required": ["title", "prompt", "timing_mode"]},
    ),
    ToolSpec(
        "automation_update",
        "Change an automation: its title, prompt, schedule or timing mode, or pause/resume it (enabled).",
        {"type": "object", "properties": {
            "id": {"type": "string"}, "title": {"type": "string"}, "prompt": {"type": "string"},
            "timing_mode": _TIMING, "schedule": _SCHEDULE, "dtstart_offset_json": _OFFSET,
            "enabled": {"type": "boolean"},
        }, "required": ["id"]},
    ),
    ToolSpec("automation_list", "List the user's automations (ids, schedules, next and last runs). Use it to find "
                                "one before changing it.", {"type": "object", "properties": {}}),
    ToolSpec("automation_delete", "Delete an automation for good (its chat stays).",
             {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, needs_approval=True),
]


def _display(a: Automation) -> AutomationDisplay:
    return AutomationDisplay(automation_id=a.id, title=a.title, schedule=a.schedule_text, next_run=a.next_run)


def _summary(a: Automation) -> str:
    state = "on" if a.enabled else "paused"
    return (f"[{a.id}] {a.title} - {a.schedule_text} ({a.timing_mode}, {state}); next run {a.next_run or 'none'}; "
            f"last {a.last_status or 'never'}")


async def _create(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    try:
        created = automations.create(AutomationCreate(**a), origin_session_id=ctx.session_id)
    except (automations.AutomationError, ValueError) as exc:
        raise ToolFailure(str(exc)) from exc
    return ToolOutcome(True, f"Created {_summary(created)}. Its runs appear in the chat "
                             f"“{'Automation · ' + created.title}”.", display=_display(created))


async def _update(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    automation_id = a.pop("id")
    try:
        updated = automations.update(automation_id, AutomationUpdate(**a))
    except (automations.AutomationError, ValueError) as exc:
        raise ToolFailure(str(exc)) from exc
    return ToolOutcome(True, f"Updated {_summary(updated)}", display=_display(updated))


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
