"""Connectors: MCP servers whose tools the agent can use (``/api/connectors``); mirrored by
``apps/studio/src/api/contracts/connectors.ts``. Secret values (env vars, HTTP headers) come back masked as
``•••``; sending ``•••`` back keeps the stored value."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConnectorTransport = Literal["stdio", "http"]  # stdio: a local program · http: a remote Streamable HTTP endpoint
ConnectorStatus = Literal["disabled", "connecting", "connected", "error"]
ConnectorApproval = Literal["ask", "auto"]  # ask: every tool call needs the user's OK · auto: runs without asking


class ConnectorTool(BaseModel):
    name: str  # the MCP tool's own name
    agent_name: str  # what the agent calls it: "<connector>__<tool>"
    description: str = ""


class Connector(BaseModel):
    id: str
    name: str
    transport: ConnectorTransport
    command: str | None = None  # stdio
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)  # values masked
    url: str | None = None  # http
    headers: dict[str, str] = Field(default_factory=dict)  # values masked
    enabled: bool
    approval: ConnectorApproval
    status: ConnectorStatus
    error: str | None = None
    tools: list[ConnectorTool] = Field(default_factory=list)
    created_at: str


class ConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    transport: ConnectorTransport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    approval: ConnectorApproval = "ask"


class ConnectorUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=40)
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None  # replaces the map; "•••" values keep what's stored
    url: str | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None
    approval: ConnectorApproval | None = None


class EvConnectorUpdate(BaseModel):
    type: Literal["connector.update"] = "connector.update"
    connector: Connector


class EvConnectorRemoved(BaseModel):
    type: Literal["connector.removed"] = "connector.removed"
    id: str


CONNECTOR_SERVER_EVENTS = (EvConnectorUpdate, EvConnectorRemoved)
