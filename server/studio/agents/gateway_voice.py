"""Conversation-scoped local speech for device clients."""
from __future__ import annotations
import asyncio
from pathlib import Path
from fastapi import Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from .. import db
from ..jobs import jobs
from ..schemas_voice import SpeakRequest
from ..schemas_agents import GatewayDictationHello
from .gateway import app, auth

bindings: dict[str, str] = {}


def scoped_job(key, allowed):
    sid = bindings.get(key)
    if sid not in allowed:
        return None
    job = jobs.get(key)
    if not job:
        bindings.pop(key, None)
        return None
    value = job.model_copy(deep=True)
    if value.result:
        for output in value.result.outputs:
            output.url = '/voice/audio/' + key + '/' + output.id
    return value


@app.post('/sessions/{sid}/speak')
async def speak(sid: str, body: SpeakRequest, authorization: str | None = Header(None)):
    auth(authorization, 'chat', sid)
    model = db.get_installed(body.model_id)
    if not model or model.kind != 'voice' or model.runtime == 'openrouter':
        raise HTTPException(400, 'Device speech requires an installed local voice model')
    if len(body.text) > 4000:
        raise HTTPException(400, 'Speak at most 4,000 characters per request')
    from ..voice import speech
    try:
        job = await asyncio.to_thread(speech.tts, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Keep only live job bindings; the job manager bounds its own retained history.
    for key in list(bindings):
        if not jobs.get(key):
            bindings.pop(key, None)
    bindings[job.id] = sid
    return scoped_job(job.id, [sid])


@app.get('/voice/jobs/{key}')
async def job_status(key: str, authorization: str | None = Header(None)):
    _, allowed = auth(authorization, 'read')
    value = scoped_job(key, allowed)
    if not value:
        raise HTTPException(404, 'Speech job not found in your conversations')
    return value


@app.delete('/voice/jobs/{key}')
async def cancel_speech(key: str, authorization: str | None = Header(None)):
    sid = bindings.get(key)
    if not sid:
        raise HTTPException(404,'Speech job not found')
    auth(authorization,'chat',sid)
    return {'cancel_requested': jobs.cancel(key) is not None}


@app.get('/voice/audio/{key}/{output_id}')
async def audio(key: str, output_id: str, authorization: str | None = Header(None)):
    _, allowed = auth(authorization, 'read')
    value = scoped_job(key, allowed)
    if not value or not value.result or not any(output.id == output_id and output.kind == 'audio' for output in value.result.outputs):
        raise HTTPException(404, 'Audio not found in your conversations')
    path = db.get_output_path(output_id)
    if not path or not Path(path).is_file():
        raise HTTPException(404, 'Audio file no longer exists')
    return FileResponse(path, media_type='audio/wav', headers={'Cache-Control':'no-store'})


@app.websocket('/sessions/{sid}/dictate')
async def dictate(socket: WebSocket, sid: str):
    await socket.accept()
    try:
        hello = GatewayDictationHello.model_validate(await asyncio.wait_for(socket.receive_json(), 10))
        token = hello.token
        from . import devices
        authorize = lambda: devices.authorize(token, 'chat', sid)
        authorize()
        from ..voice import dictation
        await dictation.run(socket, hello.model_id, hello.language, accepted=True, authorize=authorize)
    except (ValueError, HTTPException, TimeoutError):
        await socket.close(code=1008)
    except WebSocketDisconnect:
        pass
