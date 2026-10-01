"""Connectors: MCP servers whose tools the agent can use - a local program over stdio or a remote Streamable HTTP
endpoint. The studio ships none; the user adds them in Settings → Connectors.

Each enabled connector keeps one session open in a background task (connect → list tools → wait); a change or a
test reconnects it. Its tools reach the agent as ``<connector>__<tool>`` with the server's own JSON schemas; calls
ask for approval unless the connector is set to run without asking. Status changes push ``connector.update``."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, db, events
from .events import bus
from .schemas_connectors import (Connector, ConnectorCreate, ConnectorStatus, ConnectorTool, ConnectorUpdate,
                                 EvConnectorRemoved, EvConnectorUpdate)

MASK = "•••"
SEP = "__"
CONNECT_TIMEOUT_S = 45
CALL_TIMEOUT_S = 120
MAX_RESULT_CHARS = 30_000
_COLUMNS = ("id", "name", "transport", "command", "args", "env", "url", "headers", "enabled", "approval", "created_at")


class ConnectorError(ValueError):
    """User-facing reason a connector can't be saved, reached or called."""


@dataclass
class _Live:
    status: ConnectorStatus = "connecting"
    error: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)  # name, description, inputSchema
    client: Any = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s[:24] or "connector"


# ------------------------------ storage ------------------------------


def init() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS connectors (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, transport TEXT NOT NULL, command TEXT, args TEXT NOT NULL,
        env TEXT NOT NULL, url TEXT, headers TEXT NOT NULL, enabled INTEGER NOT NULL, approval TEXT NOT NULL,
        created_at TEXT NOT NULL)""")


def _raw(connector_id: str) -> dict[str, Any]:
    r = db.query_one("SELECT * FROM connectors WHERE id = ?", (connector_id,))
    if r is None:
        raise ConnectorError(f"No connector '{connector_id}'")
    d = {k: r[k] for k in _COLUMNS}
    d["args"], d["env"], d["headers"] = json.loads(d["args"]), json.loads(d["env"]), json.loads(d["headers"])
    d["enabled"] = bool(d["enabled"])
    return d


def _all_raw() -> list[dict[str, Any]]:
    return [_raw(r["id"]) for r in db.query("SELECT id FROM connectors ORDER BY created_at")]


def _write(d: dict[str, Any]) -> None:
    values = [d["id"], d["name"], d["transport"], d.get("command"), json.dumps(d.get("args") or []),
              json.dumps(d.get("env") or {}), d.get("url"), json.dumps(d.get("headers") or {}), int(d["enabled"]),
              d["approval"], d["created_at"]]
    db.execute(f"INSERT OR REPLACE INTO connectors({', '.join(_COLUMNS)}) VALUES({', '.join('?' * len(_COLUMNS))})",
               values)


def _validate(d: dict[str, Any], exclude_id: str | None = None) -> None:
    if d["transport"] == "stdio" and not (d.get("command") or "").strip():
        raise ConnectorError("A local connector needs the command that starts it (e.g. npx, uvx, python)")
    if d["transport"] == "http" and not re.match(r"^https?://", d.get("url") or ""):
        raise ConnectorError("A remote connector needs its MCP endpoint URL (http:// or https://)")
    taken = {slug(o["name"]) for o in _all_raw() if o["id"] != exclude_id}
    if slug(d["name"]) in taken:
        raise ConnectorError(f"Another connector is already called {d['name']!r}")


# ------------------------------ manager ------------------------------


class ConnectorManager:
    def __init__(self) -> None:
        self._live: dict[str, _Live] = {}

    # ---- views ----

    def view(self, d: dict[str, Any]) -> Connector:
        live = self._live.get(d["id"])
        status: ConnectorStatus = "disabled" if not d["enabled"] else (live.status if live else "connecting")
        prefix = slug(d["name"])
        tools = [ConnectorTool(name=t["name"], agent_name=f"{prefix}{SEP}{t['name']}"[:64],
                               description=(t.get("description") or "")[:500])
                 for t in (live.tools if live and d["enabled"] else [])]
        return Connector(**{**d, "env": {k: MASK for k in d["env"]}, "headers": {k: MASK for k in d["headers"]}},
                         status=status, error=live.error if live and d["enabled"] else None, tools=tools)

    def list(self) -> list[Connector]:
        return [self.view(d) for d in _all_raw()]

    def get(self, connector_id: str) -> Connector:
        return self.view(_raw(connector_id))

    def _publish(self, connector_id: str) -> None:
        try:
            bus.publish(EvConnectorUpdate(connector=self.get(connector_id)))
        except ConnectorError:
            pass

    # ---- CRUD ----

    def create(self, req: ConnectorCreate) -> Connector:
        d = {**req.model_dump(), "id": uuid.uuid4().hex[:10], "created_at": db.now_iso(), "name": req.name.strip()}
        _validate(d)
        _write(d)
        events.log("info", "connectors", f"Added connector '{d['name']}'")
        if d["enabled"]:
            self._start(d)
        self._publish(d["id"])
        return self.get(d["id"])

    async def update(self, connector_id: str, req: ConnectorUpdate) -> Connector:
        d = _raw(connector_id)
        changes = req.model_dump(exclude_unset=True)
        for key in ("env", "headers"):  # masked values keep what's stored
            if key in changes and changes[key] is not None:
                changes[key] = {k: (d[key].get(k, "") if v == MASK else v) for k, v in changes[key].items()}
        d.update({k: v for k, v in changes.items() if v is not None})
        _validate(d, exclude_id=connector_id)
        _write(d)
        await self._stop(connector_id)
        if d["enabled"]:
            self._start(d)
        self._publish(connector_id)
        return self.get(connector_id)

    async def delete(self, connector_id: str) -> None:
        _raw(connector_id)
        await self._stop(connector_id)
        db.execute("DELETE FROM connectors WHERE id = ?", (connector_id,))
        self._live.pop(connector_id, None)
        bus.publish(EvConnectorRemoved(id=connector_id))

    async def test(self, connector_id: str) -> Connector:
        """Reconnect now and wait for the result (the UI's Test button)."""
        d = _raw(connector_id)
        await self._stop(connector_id)
        if not d["enabled"]:
            raise ConnectorError("Turn the connector on first")
        live = self._start(d)
        try:
            await asyncio.wait_for(live.ready.wait(), CONNECT_TIMEOUT_S + 5)
        except TimeoutError:
            pass
        return self.get(connector_id)

    # ---- sessions ----

    def start_all(self) -> None:
        for d in _all_raw():
            if d["enabled"]:
                self._start(d)

    async def shutdown(self) -> None:
        for cid in list(self._live):
            await self._stop(cid)

    def _start(self, d: dict[str, Any]) -> _Live:
        live = self._live[d["id"]] = _Live()
        live.task = asyncio.get_running_loop().create_task(self._session(d, live), name=f"connector-{d['id']}")
        return live

    async def _stop(self, connector_id: str) -> None:
        live = self._live.get(connector_id)
        if live is None or live.task is None:
            return
        live.stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(live.task), 10)
        except (TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001 - it's going away either way
            live.task.cancel()
        live.client = None

    async def _session(self, d: dict[str, Any], live: _Live) -> None:
        from mcp import Client

        try:
            async with asyncio.timeout(CONNECT_TIMEOUT_S):
                client = Client(_server(d))
                await client.__aenter__()
            try:
                tools: list[dict[str, Any]] = []
                cursor = None
                while True:
                    page = await client.list_tools(cursor=cursor)
                    for t in page.tools:
                        schema = _get(t, "inputSchema", "input_schema") or {"type": "object", "properties": {}}
                        tools.append({"name": t.name, "description": t.description or "", "inputSchema": schema})
                    cursor = _get(page, "nextCursor", "next_cursor")
                    if not cursor:
                        break
                live.client, live.tools, live.status, live.error = client, tools, "connected", None
                live.ready.set()
                events.log("info", "connectors", f"'{d['name']}' connected: {len(tools)} tools")
                self._publish(d["id"])
                await live.stop.wait()
            finally:
                live.client = None
                await client.__aexit__(None, None, None)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - report any connection failure on the connector
            live.status, live.error = "error", _reason(exc)
            live.ready.set()
            events.log("warn", "connectors", f"'{d['name']}' failed: {live.error}")
            self._publish(d["id"])

    # ---- the agent's side ----

    def tool_specs(self) -> list[tuple[str, str, dict[str, Any], bool]]:
        """(agent name, description, JSON schema, needs approval) for every connected connector's tools."""
        out = []
        for d in _all_raw():
            live = self._live.get(d["id"])
            if not d["enabled"] or live is None or live.status != "connected":
                continue
            prefix = slug(d["name"])
            for t in live.tools:
                schema = dict(t["inputSchema"])
                schema.setdefault("type", "object")
                schema.setdefault("properties", {})
                desc = f"[{d['name']} connector] {t['description']}".strip()
                out.append((f"{prefix}{SEP}{t['name']}"[:64], desc[:1024], schema, d["approval"] == "ask"))
        return out

    def summary(self) -> list[tuple[str, int]]:
        """(name, tool count) of the connected connectors, for the system prompt."""
        return [(d["name"], len(self._live[d["id"]].tools)) for d in _all_raw()
                if d["enabled"] and d["id"] in self._live and self._live[d["id"]].status == "connected"]

    def owns(self, agent_name: str) -> bool:
        return SEP in agent_name and any(agent_name == n for n, *_ in self.tool_specs())

    async def call(self, agent_name: str, args: dict[str, Any]) -> tuple[bool, str, list[Path]]:
        """Run a connector tool: (ok, text for the model, image files it returned)."""
        prefix, _, tool = agent_name.partition(SEP)
        d = next((x for x in _all_raw() if slug(x["name"]) == prefix), None)
        live = self._live.get(d["id"]) if d else None
        if d is None or live is None or live.client is None:
            raise ConnectorError(f"The connector for {agent_name} isn't connected")
        name = next((t["name"] for t in live.tools if f"{prefix}{SEP}{t['name']}"[:64] == agent_name), tool)
        result = await live.client.call_tool(name, args, read_timeout_seconds=CALL_TIMEOUT_S)
        texts, images = [], []
        for part in result.content or []:
            kind = getattr(part, "type", "")
            if kind == "text":
                texts.append(part.text)
            elif kind == "image":
                images.append(_save_image(part))
            elif kind == "resource":
                res = part.resource
                texts.append(getattr(res, "text", None) or f"[resource {getattr(res, 'uri', '')}]")
            elif kind == "resource_link":
                texts.append(f"[link {getattr(part, 'uri', '')}]")
        structured = _get(result, "structuredContent", "structured_content")
        if structured and not texts:
            texts.append(json.dumps(structured, indent=1, default=str))
        text = "\n".join(texts) or "(no output)"
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f"\n[... {len(text) - MAX_RESULT_CHARS} characters cut]"
        return not bool(_get(result, "isError", "is_error")), text, images


def _get(obj: Any, *names: str) -> Any:
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


def _server(d: dict[str, Any]) -> Any:
    if d["transport"] == "stdio":
        from mcp import StdioServerParameters

        return StdioServerParameters(command=d["command"].strip(), args=list(d.get("args") or []),
                                     env=dict(d.get("env") or {}) or None)
    if d.get("headers"):
        import httpx2  # the MCP SDK's HTTP client
        from mcp.client.streamable_http import streamable_http_client

        return streamable_http_client(d["url"], http_client=httpx2.AsyncClient(headers=d["headers"], timeout=60))
    return d["url"]


def _reason(exc: BaseException) -> str:
    """The first meaningful message of an exception (task groups wrap the real one)."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, TimeoutError):
        return f"No answer within {CONNECT_TIMEOUT_S} s (is the command or URL right?)"
    if isinstance(exc, FileNotFoundError):
        return f"Command not found: {exc.filename or exc}"
    return f"{type(exc).__name__}: {exc}"[:500]


def _save_image(part: Any) -> Path:
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(
        _get(part, "mimeType", "mime_type") or "", ".png")
    out = config.OUTPUTS_DIR / "connectors" / f"{uuid.uuid4().hex[:12]}{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(part.data))
    return out


manager = ConnectorManager()
