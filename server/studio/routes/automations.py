"""``/api/automations``: prompts the agent runs on a schedule (see ``studio/automations.py``)."""

from __future__ import annotations

from fastapi import HTTPException, Response

from .. import automations
from ..schemas_automations import Automation, AutomationCreate, AutomationUpdate
from . import StudioRouter

router = StudioRouter(prefix="/api/automations")


@router.get("", response_model=list[Automation])
async def list_automations() -> list[Automation]:
    return automations.list_all()


@router.post("", response_model=Automation)
async def create_automation(body: AutomationCreate) -> Automation:
    try:
        return automations.create(body)
    except automations.AutomationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/{automation_id}", response_model=Automation)
async def update_automation(automation_id: str, body: AutomationUpdate) -> Automation:
    try:
        return automations.update(automation_id, body)
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
    """Run it now (the regular schedule continues)."""
    try:
        return automations.runner.run_now(automation_id)
    except automations.AutomationError as exc:
        raise HTTPException(409 if "already" in str(exc) else 404, str(exc)) from exc
