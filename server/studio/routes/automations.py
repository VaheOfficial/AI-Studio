"""``/api/automations``: prompts the agent runs on a schedule or on a trigger (see ``studio/automations.py``)."""

from __future__ import annotations

from fastapi import HTTPException, Response

from .. import automations
from ..runtimes import envs
from ..schemas_automations import Automation, AutomationCreate, AutomationUpdate
from . import StudioRouter

router = StudioRouter(prefix="/api/automations")


def _python_for_checks() -> None:
    """A trigger's check runs in the Python tools environment. When that isn't there yet, start installing it and
    say so, instead of refusing the trigger for a reason the user can do nothing about here."""
    if envs.is_ready(automations.CHECK_ENV):
        return
    envs.ensure_env_job(automations.CHECK_ENV, "python")
    raise HTTPException(409, "The Python tools a check runs with are being installed now (one time, a few hundred "
                             "MB; see the Jobs panel). Save again when that is done.")


@router.get("", response_model=list[Automation])
async def list_automations() -> list[Automation]:
    return automations.list_all()


@router.post("", response_model=Automation)
async def create_automation(body: AutomationCreate) -> Automation:
    if body.timing_mode == "trigger":
        _python_for_checks()
    try:
        return (await automations.create_checked(body))[0]
    except automations.AutomationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/{automation_id}", response_model=Automation)
async def update_automation(automation_id: str, body: AutomationUpdate) -> Automation:
    if body.timing_mode == "trigger" or body.check:
        _python_for_checks()
    try:
        return (await automations.update_checked(automation_id, body))[0]
    except automations.AutomationError as exc:
        raise HTTPException(404 if "No automation" in str(exc) else 400, str(exc)) from exc


@router.delete("/{automation_id}", status_code=204)
async def delete_automation(automation_id: str) -> Response:
    try:
        automations.delete(automation_id)
    except automations.AutomationError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(status_code=204)


@router.post("/{automation_id}/run", response_model=Automation)
async def run_automation(automation_id: str) -> Automation:
    """Run it now (the regular schedule continues). A trigger runs its check now."""
    try:
        return automations.runner.run_now(automation_id)
    except automations.AutomationError as exc:
        raise HTTPException(409 if "already" in str(exc) else 404, str(exc)) from exc
