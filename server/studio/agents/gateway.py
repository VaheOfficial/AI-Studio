"""Separate gateway surface; the unrestricted Studio API is never exposed by it."""
from __future__ import annotations
import asyncio
import json
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel, Field
from .. import db
from ..agent import agent
from ..events import bus
from . import devices, store
from ..schemas_agents import PushSubscriptionInput, GatewayVoiceModel

app = FastAPI(title='Grom Agents Gateway', docs_url=None, redoc_url=None, openapi_url=None)
from .documents import connect as document_connect
app.add_api_websocket_route('/documents', document_connect)


@app.post('/channels/{key}/receive')
async def receive_signed_channel(key: str, request: Request):
    from ..routes.agents import receive_channel_message
    return await receive_channel_message(key, request)


@app.get('/manifest.webmanifest')
async def manifest_mobile():
    return Response(json.dumps({'name':'Grom Agents','short_name':'Agents','start_url':'/','scope':'/','display':'standalone','icons':[{'src':'/office/icon.png?size=192','sizes':'192x192','type':'image/png'},{'src':'/office/icon.png?size=512','sizes':'512x512','type':'image/png'}]}), media_type='application/manifest+json')


@app.get('/mobile-sw.js')
async def mobile_worker():
    return Response(Path(__file__).with_name('mobile-sw.js').read_text(), media_type='application/javascript', headers={'Service-Worker-Allowed':'/', 'Cache-Control':'no-cache'})


@app.get('/push/key')
async def push_key(authorization: str | None = Header(None)):
    auth(authorization, 'notifications')
    from . import notifications
    if not notifications.settings().web_push:
        raise HTTPException(409, 'Enable browser push in Studio first')
    return {'public_key': notifications.public_key()}


@app.post('/push/subscribe')
async def push_subscribe(body: PushSubscriptionInput, authorization: str | None = Header(None)):
    device, _ = auth(authorization, 'notifications')
    from .notifications import subscribe
    try:
        return subscribe(device, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete('/push/subscriptions')
async def unsubscribe_push(authorization: str | None = Header(None)):
    device, _ = auth(authorization, 'notifications')
    db.execute('DELETE FROM agent_push_subscriptions WHERE device_id=?', (device.id,))
    return {'unsubscribed':True}


@app.get('/office', response_class=HTMLResponse)
async def office_page():
    from .office import page
    return HTMLResponse(page(), headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})


@app.get('/office/manifest.xml')
async def office_manifest(host: str, base_url: str):
    from .office import manifest
    try:
        return Response(manifest(host, base_url), media_type='application/xml', headers={'Content-Disposition': 'attachment; filename="grom-' + host + '.xml"'})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get('/office/icon.png')
async def office_icon(size: int = 64):
    import io
    from PIL import Image, ImageDraw
    if not 64 <= size <= 512: raise HTTPException(400,'Icon size must be between 64 and 512')
    image = Image.new('RGBA', (size,size), (0,0,0,0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2,2,size-2,size-2), radius=size//5, fill=(190,42,58,255))
    points = [(int(x*size),int(y*size)) for x,y in [(0.72,0.32),(0.6,0.25),(0.4,0.25),(0.28,0.37),(0.28,0.63),(0.4,0.75),(0.6,0.75),(0.72,0.63),(0.72,0.52),(0.53,0.52)]]
    draw.line(points,fill=(255,255,255,255),width=max(3,size//12),joint='curve')
    data = io.BytesIO(); image.save(data, format='PNG')
    return Response(data.getvalue(), media_type='image/png')


@app.get('/', response_class=HTMLResponse)
async def mobile():
    return HTMLResponse(Path(__file__).with_name('mobile.html').read_text(encoding='utf-8'),
        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'})


@app.get('/voice/models', response_model=list[GatewayVoiceModel])
async def voice_models(authorization: str | None = Header(None)):
    auth(authorization, 'read')
    return [{'id': m.id, 'name': m.name, 'runtime':m.runtime} for m in db.list_installed() if m.kind == 'stt' and m.runtime != 'openrouter']


@app.post('/sessions/{sid}/transcribe')
async def transcribe(sid: str, file: UploadFile = File(...), model_id: str = Form(...), authorization: str | None = Header(None)):
    auth(authorization, 'chat', sid)
    import uuid
    from .. import config, generation
    data = await file.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise HTTPException(413, 'Audio exceeds the 32 MiB limit')
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in {'.webm', '.wav', '.mp3', '.m4a', '.ogg', '.mp4'}:
        raise HTTPException(400, 'Unsupported audio format')
    target = config.UPLOADS_DIR / (uuid.uuid4().hex + suffix)
    target.write_bytes(data)
    try:
        return await asyncio.to_thread(generation.transcribe, model_id, target, None)
    finally:
        target.unlink(missing_ok=True)


def auth(header, scope, sid=None):
    if not header or not header.startswith('Bearer '):
        raise HTTPException(401, 'A device token is required')
    try:
        return devices.authorize(header[7:], scope, sid)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.get('/permissions')
async def permissions(authorization: str | None = Header(None)):
    device, allowed = auth(authorization, 'read')
    return {'scopes': device.scopes, 'session_ids': allowed}


@app.get('/sessions')
async def sessions(authorization: str | None = Header(None)):
    _, allowed = auth(authorization, 'read')
    return [s.model_dump(exclude={'messages'}) for sid in allowed if (s := db.get_session(sid))]


@app.get('/sessions/{sid}')
async def session(sid: str, authorization: str | None = Header(None)):
    auth(authorization, 'read', sid)
    value = db.get_session(sid)
    if not value:
        raise HTTPException(404, 'Conversation not found')
    return {'session': value, 'messages': db.list_messages(sid), 'artifacts': store.artifacts(sid)}


class Send(BaseModel):
    content: str = Field(min_length=1, max_length=16000)


@app.post('/sessions/{sid}/send', status_code=202)
async def send(sid: str, body: Send, authorization: str | None = Header(None)):
    auth(authorization, 'chat', sid)
    from ..agent_plus import store as missions
    if missions.owns_session(sid) and missions.get(sid).status in ('completed', 'cancelled'):
        raise HTTPException(409, 'Amend the mission in Studio before starting another task')
    value = db.get_session(sid)
    if not value:
        raise HTTPException(404, 'Conversation not found')
    if agent.busy(sid):
        raise HTTPException(409, 'Agent is working; wait or stop it first')
    agent.start(value, body.content)
    return {'accepted': True}


class Approval(BaseModel):
    approved: bool


class Answer(BaseModel):
    answer: str = Field(min_length=1, max_length=16000)


@app.post('/sessions/{sid}/answer/{call_id}')
async def answer(sid: str, call_id: str, body: Answer, authorization: str | None = Header(None)):
    auth(authorization, 'chat', sid)
    if not agent.answer(sid, call_id, body.answer):
        raise HTTPException(404, 'No matching pending question')
    return {'accepted': True}


@app.post('/sessions/{sid}/approve/{call_id}')
async def approve(sid: str, call_id: str, body: Approval, authorization: str | None = Header(None)):
    auth(authorization, 'approve', sid)
    if not agent.approve(sid, call_id, body.approved):
        raise HTTPException(404, 'No matching pending approval')
    return {'accepted': True}


@app.post('/sessions/{sid}/stop')
async def stop(sid: str, authorization: str | None = Header(None)):
    auth(authorization, 'chat', sid)
    from . import controls
    await controls.pause(sid)
    return {'stopped': True}


class EventDelivery(BaseModel):
    session_id: str
    event_id: str = Field(min_length=1, max_length=200)
    payload: dict = Field(default_factory=dict)


@app.post('/events/{topic}')
async def deliver_event(topic: str, body: EventDelivery, authorization: str | None = Header(None)):
    device, _ = auth(authorization, 'deliver_events', body.session_id)
    from . import wakes
    try:
        return {'wakes_ready': wakes.event(topic, body.event_id, device.id, body.payload, body.session_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.websocket('/events')
async def events(socket: WebSocket):
    await socket.accept()
    subscriber = None
    try:
        hello = await asyncio.wait_for(socket.receive_json(), 10)
        token = hello.get('token', '')
        _, sessions = devices.authorize(token, 'events')
        subscriber = bus.subscribe()
        while True:
            try:
                frame = await asyncio.wait_for(subscriber.get(), 20)
            except TimeoutError:
                devices.authorize(token, 'events')
                await socket.send_json({'type': 'heartbeat'})
                continue
            devices.authorize(token, 'events')
            if frame is None:
                break
            value = json.loads(frame)
            if value.get('type') == 'job.update':
                from .gateway_voice import scoped_job
                job = scoped_job(value.get('job',{}).get('id'), sessions)
                if job:
                    await socket.send_json({'type':'job.update','job':job.model_dump()})
                continue
            if value.get('session_id') in sessions and value.get('type') in ('agent', 'agents.update', 'agentplus.update'):
                await socket.send_text(frame)
    except (ValueError, HTTPException, asyncio.TimeoutError):
        await socket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        if subscriber is not None:
            bus.unsubscribe(subscriber)


@app.get('/voice/speech-models', response_model=list[GatewayVoiceModel])
async def speech_models(authorization: str | None = Header(None)):
    auth(authorization, 'read')
    return [{'id':m.id,'name':m.name,'runtime':m.runtime} for m in db.list_installed() if m.kind == 'voice' and m.runtime != 'openrouter']


from . import gateway_voice  # Register scoped voice routes after app and auth exist.
