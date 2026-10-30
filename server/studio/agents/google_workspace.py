"""Structured Gmail MIME preparation and authenticated Drive file transfers."""
from __future__ import annotations
import asyncio
import base64
import json
import mimetypes
import uuid
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import quote
import httpx
from .. import config
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from ..localhttp import tls
from ..schemas_workspace import FileArtifact, PythonDisplay
from . import file_tools, oauth, services, vault
from .tools import obj, S

MAX_FILE = 20 * 1024 * 1024
SPECS = [ToolSpec('google_workspace_file', 'Prepare a Gmail draft or approved send with real MIME attachments; upload or download Drive content; download a Gmail attachment. Requires an authorized matching Google HTTP service. Source files stay within the workspace or managed outputs. Use account tools to read back the resulting IDs.',
         obj({'action':{'type':'string','enum':['draft_mail','send_mail','upload_drive','download_drive','download_attachment','export_drive']},
         'service_id':S,'to':{'type':'array','items':S,'maxItems':30},'cc':{'type':'array','items':S,'maxItems':30},
         'subject':S,'text':S,'sources':{'type':'array','items':S,'maxItems':10},'source':S,
         'name':S,'mime_type':S,'parent_id':S,'file_id':S,'message_id':S,'attachment_id':S,'thread_id':S},['action','service_id']),needs_approval=True)]


def mailbox(a, sid):
    if not a.get('to'): raise ToolFailure('Supply at least one recipient')
    message=EmailMessage()
    for field,key in [('To','to'),('Cc','cc')]:
        values=a.get(key,[])
        for address in values:
            parsed=parseaddr(address)[1]
            if '\r' in address or '\n' in address or not parsed or '@' not in parsed:
                raise ToolFailure('Invalid email recipient')
        if values: message[field]=', '.join(values)
    message['Subject']=a.get('subject','')
    message.set_content(a.get('text',''))
    total=0
    for source in a.get('sources',[]):
        path=Path(file_tools.resolve_source(sid,source,MAX_FILE));total+=path.stat().st_size
        if total>MAX_FILE: raise ToolFailure('Mail attachments exceed 20 MiB')
        mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        major,minor=mime.split('/',1)
        message.add_attachment(path.read_bytes(),maintype=major,subtype=minor,filename=path.name)
    value={'raw':base64.urlsafe_b64encode(message.as_bytes()).decode()}
    if a.get('thread_id'): value['threadId']=a['thread_id']
    return value


async def invoke(a,ctx):
    service=services.raw(a['service_id'])
    if not service.enabled: raise ToolFailure('Google service is disabled')
    action=a['action'];gmail=action in ('draft_mail','send_mail','download_attachment')
    expected='https://gmail.googleapis.com/gmail/v1' if gmail else 'https://www.googleapis.com/drive/v3'
    if service.base_url.rstrip('/')!=expected: raise ToolFailure('Choose the matching Gmail or Google Drive service')
    authorized=await oauth.authorized_config({'id':service.id,'headers':service.headers})
    headers=vault.resolve_map(authorized['headers'])
    method='GET';url=expected;params={};body=None;content=None
    if action in ('draft_mail','send_mail'):
        value=await asyncio.to_thread(mailbox,a,ctx.session_id)
        body={'message':value} if action=='draft_mail' else value
        url+='/users/me/' + ('drafts' if action=='draft_mail' else 'messages/send');method='POST'
    elif action=='upload_drive':
        if not a.get('source'): raise ToolFailure('upload_drive requires source')
        path=Path(file_tools.resolve_source(ctx.session_id,a['source'],5*1024*1024))
        boundary=uuid.uuid4().hex
        metadata={'name':a.get('name') or path.name}
        if a.get('parent_id'): metadata['parents']=[a['parent_id']]
        mime=a.get('mime_type') or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if '\r' in mime or '\n' in mime: raise ToolFailure('Invalid MIME type')
        content=(f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()+json.dumps(metadata).encode()+
                 f'\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n'.encode()+await asyncio.to_thread(path.read_bytes)+f'\r\n--{boundary}--\r\n'.encode())
        headers['Content-Type']='multipart/related; boundary='+boundary
        url='https://www.googleapis.com/upload/drive/v3/files';params={'uploadType':'multipart','fields':'id,name,mimeType,size,webViewLink'};method='POST'
    elif action in ('download_drive','export_drive'):
        if not a.get('file_id'): raise ToolFailure('download_drive requires file_id')
        url+='/files/'+quote(a['file_id'],safe='');params={'alt':'media'}
        if action=='export_drive':
            if not a.get('mime_type'): raise ToolFailure('export_drive requires the target mime_type')
            url+='/export';params={'mimeType':a['mime_type']}
    else:
        if not all(a.get(key) for key in ('message_id','attachment_id')): raise ToolFailure('Supply message_id and attachment_id')
        url+='/users/me/messages/'+quote(a['message_id'],safe='')+'/attachments/'+quote(a['attachment_id'],safe='')
    async with httpx.AsyncClient(timeout=60,verify=tls,trust_env=False,follow_redirects=False) as client:
        async with client.stream(method,url,params=params,headers=headers,json=body,content=content) as response:
            chunks=[];size=0
            async for chunk in response.aiter_bytes():
                size+=len(chunk)
                if size>32*1024*1024: raise ToolFailure('Google response exceeds 32 MiB; inspect outcome before retrying')
                chunks.append(chunk)
            data=b''.join(chunks)
            if not response.is_success:
                return ToolOutcome(False,'Google operation failed ('+str(response.status_code)+'): '+data.decode(errors='replace')[:1500])
    if action in ('download_drive','download_attachment','export_drive'):
        if action=='download_attachment':
            encoded=json.loads(data).get('data','')
            data=base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4))
        if len(data)>MAX_FILE: raise ToolFailure('Downloaded file exceeds 20 MiB')
        name=Path(a.get('name') or 'download.bin').name
        if not name or name in ('.','..'): raise ToolFailure('Supply a valid output filename')
        directory=config.OUTPUTS_DIR/'google'/ctx.session_id/uuid.uuid4().hex[:12];directory.mkdir(parents=True,exist_ok=True)
        path=directory/name;await asyncio.to_thread(path.write_bytes,data)
        artifact=FileArtifact(name=name,path=str(path),url='/files/'+path.relative_to(config.DATA_DIR).as_posix(),size=len(data))
        return ToolOutcome(True,'Downloaded '+name,display=PythonDisplay(code='',output='Authenticated Google download',files=[artifact]))
    return ToolOutcome(True,json.dumps({'action':action,'status':response.status_code,'data':services.redact(json.loads(data))}))


IMPL={'google_workspace_file':invoke}
