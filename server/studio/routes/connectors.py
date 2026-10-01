"""``/api/connectors``: MCP servers whose tools the agent can use (see ``studio/connectors.py``)."""

from __future__ import annotations

from fastapi import HTTPException, Response

from ..connectors import ConnectorError, manager
from ..schemas_connectors import Connector, ConnectorCreate, ConnectorUpdate
from . import StudioRouter

router = StudioRouter(prefix="/api/connectors")


def _status(exc: ConnectorError) -> int:
    return 404 if str(exc).startswith("No connector") else 400


@router.get("", response_model=list[Connector])
async def list_connectors() -> list[Connector]:
    return manager.list()


@router.post("", response_model=Connector)
async def create_connector(body: ConnectorCreate) -> Connector:
    try:
        return manager.create(body)
    except ConnectorError as exc:
        raise HTTPException(_status(exc), str(exc)) from exc


@router.patch("/{connector_id}", response_model=Connector)
async def update_connector(connector_id: str, body: ConnectorUpdate) -> Connector:
    try:
        return await manager.update(connector_id, body)
    except ConnectorError as exc:
        raise HTTPException(_status(exc), str(exc)) from exc


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(connector_id: str) -> Response:
    try:
        await manager.delete(connector_id)
    except ConnectorError as exc:
        raise HTTPException(_status(exc), str(exc)) from exc
    return Response(status_code=204)


@router.post("/{connector_id}/test", response_model=Connector)
async def test_connector(connector_id: str) -> Connector:
    """Reconnect now and return the result: status, error and the tools it offers."""
    try:
        return await manager.test(connector_id)
    except ConnectorError as exc:
        raise HTTPException(_status(exc), str(exc)) from exc
