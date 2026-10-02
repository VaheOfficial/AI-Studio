"""Automations: prompts the agent runs on a schedule or when a trigger fires (``/api/automations``); mirrored by
``apps/studio/src/api/contracts/automations.ts``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# exact_schedule: at the time given · flexible_schedule: around a daypart (morning 8:00, afternoon 15:00, evening
# 19:00) · condition_watch: recurring check that only reports when the condition is met · trigger: no schedule; a
# check script runs by itself every few minutes, and the agent is woken only when it prints something new
AutomationTiming = Literal["exact_schedule", "flexible_schedule", "condition_watch", "trigger"]
AutomationRunStatus = Literal["reported", "quiet", "needs_approval", "error"]


class Automation(BaseModel):
    id: str
    title: str
    prompt: str  # the instruction sent to the agent on every run
    schedule: str  # iCal VEVENT: DTSTART (local time) and optionally RRULE; empty for a trigger
    schedule_text: str  # the schedule in words ("Every day at 08:00", "Checks every 15 minutes")
    timing_mode: AutomationTiming
    enabled: bool
    model: str | None = None  # chat model id that runs it; None = the default chat model
    session_id: str  # the chat its runs are posted in
    next_run: str | None = None  # ISO UTC; None when it won't run again
    last_run: str | None = None
    last_status: AutomationRunStatus | None = None
    last_result: str | None = None  # start of the last report (or the error)
    created_at: str
    # A trigger: Python the app runs by itself (no model) every ``check_minutes``. Each line it prints is an item;
    # a line it has not printed before wakes the agent, which gets the new lines with the prompt. For a trigger
    # ``next_run`` is the next check.
    check: str | None = None
    check_minutes: int | None = None
    last_check: str | None = None  # ISO UTC
    check_error: str | None = None  # why the last check failed (None: it ran)


class AutomationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=4000)
    timing_mode: AutomationTiming
    # Either an iCal VEVENT (DTSTART and/or RRULE), or dtstart_offset_json for "in 20 minutes" style one-offs
    schedule: str | None = None
    dtstart_offset_json: str | None = None  # dateutil.relativedelta kwargs, e.g. {"hours": 4}
    model: str | None = None
    # timing_mode "trigger": the check script and how often it runs (default 15 minutes); no schedule
    check: str | None = Field(None, max_length=20000)
    check_minutes: int | None = Field(None, ge=1, le=1440)


class AutomationUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=80)
    prompt: str | None = Field(None, min_length=1, max_length=4000)
    timing_mode: AutomationTiming | None = None
    schedule: str | None = None
    dtstart_offset_json: str | None = None
    enabled: bool | None = None
    model: str | None = None
    check: str | None = Field(None, max_length=20000)
    check_minutes: int | None = Field(None, ge=1, le=1440)


class EvAutomationUpdate(BaseModel):
    type: Literal["automation.update"] = "automation.update"
    automation: Automation


class EvAutomationRemoved(BaseModel):
    type: Literal["automation.removed"] = "automation.removed"
    id: str


class EvAutomationRun(BaseModel):
    """A run finished with something for the user (a report, a question for approval, or an error)."""

    type: Literal["automation.run"] = "automation.run"
    automation_id: str
    title: str
    status: AutomationRunStatus
    message: str
    session_id: str


AUTOMATION_SERVER_EVENTS = (EvAutomationUpdate, EvAutomationRemoved, EvAutomationRun)
