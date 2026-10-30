"""Authenticated live document sessions advertise only their implemented commands."""
from __future__ import annotations
import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from fastapi import WebSocket, WebSocketDisconnect
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from . import devices, store


@dataclass
class Document:
    id: str
    session_id: str
    title: str
    kind: str
    tools: list[dict]
    socket: WebSocket
    device_token: str
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


_documents: dict[str, Document] = {}


def list_all(sid=None):
    return [{'id': d.id, 'session_id': d.session_id, 'title': d.title, 'kind': d.kind, 'tools': d.tools}
            for d in _documents.values() if sid is None or d.session_id == sid]


def specs():
    return [ToolSpec('document__' + d.id + '__' + t['name'], f'[{d.title}] ' + t.get('description',''),
            t['parameters'], needs_approval=True) for d in _documents.values() for t in d.tools]


def owned(sid, name):
    parts = name.split('__', 2)
    value = _documents.get(parts[1]) if len(parts) == 3 else None
    if value is None:
        return False
    if value.session_id == sid:
        return True
    from .delegation import get
    child = get(sid)
    return child is not None and child.parent_session_id == value.session_id and name in child.allowed_tools


async def call(name, args, ctx):
    if not owned(ctx.session_id, name):
        raise ToolFailure('Document command is outside this conversation')
    _, did, tool = name.split('__', 2)
    d = _documents[did]
    devices.authorize(d.device_token, 'documents', d.session_id)
    if len(json.dumps(args,allow_nan=False)) > 128000: raise ToolFailure('Document command exceeds the input limit')
    from jsonschema import Draft202012Validator, ValidationError
    definition = next((item for item in d.tools if item['name'] == tool),None)
    if definition is None: raise ToolFailure('Document command is no longer available')
    try: Draft202012Validator(definition['parameters']).validate(args)
    except ValidationError as exc: raise ToolFailure('Document input does not match its schema: ' + exc.message[:500]) from exc
    key = uuid.uuid4().hex
    future = asyncio.get_running_loop().create_future()
    d.pending[key] = future
    try:
        await d.socket.send_json({'type': 'command', 'id': key, 'name': tool, 'args': args})
        result = await asyncio.wait_for(future, 60)
        return ToolOutcome(bool(result.get('ok')), json.dumps(result, ensure_ascii=False)[:64000])
    finally:
        d.pending.pop(key, None)


async def connect(socket: WebSocket):
    await socket.accept()
    document = None
    try:
        hello = await asyncio.wait_for(socket.receive_json(), 10)
        _, allowed = devices.authorize(hello.get('token',''), 'documents', hello.get('session_id'))
        sid = hello.get('session_id')
        if sid not in allowed:
            raise ValueError('Conversation is not granted')
        if len(json.dumps(hello)) > 128000:
            raise ValueError('Document registration exceeds the size limit')
        tools = hello.get('tools', [])
        if not isinstance(tools, list) or not 1 <= len(tools) <= 40:
            raise ValueError('Advertise 1 to 40 supported commands')
        names = set()
        for tool in tools:
            if not isinstance(tool, dict) or len(str(tool.get('description', ''))) > 4000:
                raise ValueError('Invalid document command')
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', tool.get('name','')) or tool['name'] in names:
                raise ValueError('Invalid or duplicate command name')
            names.add(tool['name'])
            schema = tool.get('parameters', {})
            if not isinstance(schema, dict):
                raise ValueError('Command schema must be an object')
            if schema.get('type') != 'object' or not isinstance(schema.get('properties'), dict):
                raise ValueError('Command input requires an object schema')
        document = Document(uuid.uuid4().hex[:10], sid, str(hello.get('title','Document'))[:160],
            str(hello.get('kind','document'))[:80], tools, socket, hello['token'])
        _documents[document.id] = document
        await socket.send_json({'type': 'connected', 'id': document.id})
        store.notify('documents', sid)
        while True:
            message = await socket.receive_json()
            if not isinstance(message, dict) or len(json.dumps(message)) > 1000000:
                raise ValueError('Document response exceeds the size limit')
            devices.authorize(document.device_token, 'documents', sid)
            if message.get('type') == 'result' and message.get('id') in document.pending:
                future = document.pending[message['id']]
                if not future.done():
                    future.set_result(message)
    except (ValueError, asyncio.TimeoutError):
        await socket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        if document:
            _documents.pop(document.id, None)
            for future in document.pending.values():
                if not future.done():
                    future.set_exception(ToolFailure('Document client disconnected'))
            store.notify('documents', document.session_id)
