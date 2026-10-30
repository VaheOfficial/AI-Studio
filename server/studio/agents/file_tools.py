"""First-class document, spreadsheet, presentation and PDF tools over the CPU runtime."""
from __future__ import annotations
import asyncio
import json
import os
import uuid
from pathlib import Path
from urllib.parse import unquote
from .. import config
from ..agent.types import ToolSpec, ToolOutcome, ToolFailure
from ..agent import python_tools, pykernel
from ..runtimes import envs
from ..osenv import NO_WINDOW
from ..proc import kill_tree
from ..schemas_workspace import FileArtifact, PythonDisplay
from ..workspace import files, state
from .tools import obj, S, O

ACTIONS = ['inspect','create_document','edit_document','create_sheet','write_cells','format_cells','sort_rows','add_chart','create_slides','replace_slide_text','create_pdf','merge_pdf','extract_pdf','render_pdf','fill_pdf','ocr_pdf','recalculate_sheet','export_office_pdf']
SPECS = [ToolSpec('office_file', 'Read, create and edit DOCX, XLSX, PPTX and PDF files; charts, formatting, slide notes, PDF merge/extract/render. Edits create new managed outputs. options supplies structured blocks, rows, ranges or slides; use office_file_help for exact action fields. Formula caches require a spreadsheet calculation engine.',
    obj({'action':{'type':'string','enum':ACTIONS},'source':S,'sources':{'type':'array','items':S,'maxItems':20},'assets':{'type':'array','items':S,'maxItems':30},'name':S,'options':O},['action']),asks_like=lambda _: 'run_python'),
    ToolSpec('office_file_help','Read the structured schema and examples for first-class document operations.',obj({})),
    ToolSpec('setup_document_ocr','Install the checksum-pinned English OCR language data in the local CPU document runtime. Downloads approximately 4 MB from the official Tesseract repository; no external OCR service.',obj({}),needs_approval=True)]

OCR_URL='https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/eng.traineddata'
OCR_SHA256='7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'


async def setup_ocr(a,ctx):
    import hashlib
    import httpx
    from ..localhttp import tls
    await python_tools._ensure_env(ctx,'Local document OCR')
    destination=envs.env_dir('python')/'share'/'tessdata'/'eng.traineddata'
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest()==OCR_SHA256:
        return ToolOutcome(True,json.dumps({'installed':True,'language':'eng','path':str(destination),'sha256':OCR_SHA256}))
    data=bytearray()
    async with httpx.AsyncClient(verify=tls,timeout=45) as client:
        async with client.stream('GET',OCR_URL) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data)>8*1024*1024: raise ToolFailure('OCR language download exceeds 8 MB')
    if hashlib.sha256(data).hexdigest()!=OCR_SHA256: raise ToolFailure('OCR language download checksum did not match the pinned release')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    try: temporary.write_bytes(data);temporary.replace(destination)
    finally: temporary.unlink(missing_ok=True)
    return ToolOutcome(True,json.dumps({'installed':True,'language':'eng','path':str(destination),'sha256':OCR_SHA256}))


def resolve_source(sid, value, max_bytes=32*1024*1024):
    if value.startswith('/files/'):
        path = (config.DATA_DIR / unquote(value.removeprefix('/files/'))).resolve()
    elif Path(value).is_absolute():
        path = Path(value).resolve()
    else:
        path = files.resolve(state.require_root(sid),value)
    roots = [config.OUTPUTS_DIR.resolve(),config.UPLOADS_DIR.resolve()]
    if state.get(sid).root: roots.append(Path(state.get(sid).root).resolve())
    if not any(root in path.parents for root in roots) or not path.is_file() or path.stat().st_size > max_bytes:
        raise ToolFailure('Choose a file within the size limit in this workspace or managed outputs/uploads')
    return str(path)


async def help_tool(a, ctx):
    return ToolOutcome(True, json.dumps({
        'create_document/create_pdf':{'options':{'title':'Report','blocks':[{'type':'heading','text':'Results'},{'type':'paragraph','text':'Verified results'},{'type':'table','rows':[['Metric','Value'],['Count',3]]},{'type':'image','asset_index':0}]}},
        'edit_document':{'source':'report.docx','options':{'old':'exact original passage','replacement':'new passage','expected_count':1}},
        'create_sheet/write_cells':{'options':{'sheet':'Results','rows':[['Name','Count'],['A',3]],'start_row':1,'start_column':1,'allow_formulas':False}},
        'format_cells':{'options':{'sheet':'Results','range':'A1:B5','bold':True,'number_format':'0.00','fill':'FFF0CC','wrap':True}},
        'sort_rows':{'options':{'sheet':'Results','column':1,'headers':True,'descending':False}},
        'add_chart':{'options':{'sheet':'Results','range':'A1:B5','chart':'bar','title':'Counts','anchor':'D2'}},
        'create_slides':{'options':{'slides':[{'title':'Results','bullets':['Verified outcome'],'notes':'Presenter notes','asset_index':0}]}},
        'replace_slide_text':{'options':{'slide':0,'old':'exact passage','replacement':'updated passage','expected_count':1}},
        'merge_pdf':{'sources':['first.pdf','second.pdf']},'extract_pdf':{'source':'source.pdf','options':{'pages':[0,2]}},
        'render_pdf':{'source':'source.pdf','options':{'pages':[0],'dpi':120}},
        'fill_pdf':{'source':'form.pdf','options':{'fields':{'name':'Approved value'}}},
        'ocr_pdf':{'source':'scanned.pdf','options':{'pages':[0],'language':'eng'},'requires':'Local Tesseract and selected language data'},
        'recalculate_sheet':{'source':'source.xlsx','requires':'Local LibreOffice; returns formula cache readback'},
        'export_office_pdf':{'source':'source.docx','requires':'Local LibreOffice; open the produced PDF and inspect its rendered pages'},
        'inspect':{'source':'source.xlsx','options':{'cached_values':False}},
        'assets':'Image blocks reference zero-based indexes in the explicit assets list. All source paths stay within the conversation workspace or managed files.',
    },ensure_ascii=False))


async def action(a, ctx):
    source = resolve_source(ctx.session_id,a['source']) if a.get('source') else None
    sources = [resolve_source(ctx.session_id,item) for item in a.get('sources',[])]
    assets = [resolve_source(ctx.session_id,item) for item in a.get('assets',[])]
    if a['action'] == 'merge_pdf' and not sources: raise ToolFailure('merge_pdf needs sources')
    if a['action'] not in ('create_document','create_sheet','create_slides','create_pdf','merge_pdf') and not source: raise ToolFailure('This operation needs a source')
    directory = config.OUTPUTS_DIR / 'documents' / ctx.session_id / uuid.uuid4().hex[:12]
    directory.mkdir(parents=True,exist_ok=True)
    await python_tools._ensure_env(ctx,'Structured document operation: ' + a['action'])
    payload = {**a,'source':source,'sources':sources,'assets':assets,'directory':str(directory)}
    raw = json.dumps(payload,allow_nan=False).encode()
    if len(raw) > 2*1024*1024: raise ToolFailure('Document request exceeds 2 MiB')
    environment = {**os.environ,'PYTHONIOENCODING':'utf-8','CUDA_VISIBLE_DEVICES':'-1','MPLCONFIGDIR':str(config.CACHE_DIR/'document-fonts')}
    proc = await asyncio.create_subprocess_exec(str(envs.env_python('python')),'-I',str(config.WORKERS_DIR/'office_file_worker.py'),
        cwd=directory,env=environment,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,creationflags=NO_WINDOW)
    async def read(stream,limit):
        chunks,size = [],0
        while chunk := await stream.read(16384):
            size += len(chunk)
            if size > limit: raise ToolFailure('Document process output exceeds its limit')
            chunks.append(chunk)
        return b''.join(chunks)
    async def exchange():
        proc.stdin.write(raw); await proc.stdin.drain(); proc.stdin.close()
        stdout,stderr = await asyncio.gather(read(proc.stdout,2*1024*1024),read(proc.stderr,64000))
        await proc.wait()
        return stdout,stderr
    try:
        stdout,stderr = await asyncio.wait_for(exchange(),120)
        if proc.returncode: raise ToolFailure('Document process failed: ' + stderr.decode(errors='replace')[:2000])
        value = json.loads(stdout)
        if not value.get('ok'): return ToolOutcome(False,value.get('error','Document operation failed'))
        output = value['result']; attachments = []
        for item in output.get('outputs',[]):
            path = Path(item['path']).resolve()
            if directory.resolve() not in path.parents: raise ToolFailure('Worker returned a file outside its output directory')
            url = pykernel.file_url(ctx.session_id,path); item['url'] = url
            attachments.append(FileArtifact(name=path.name,path=str(path),url=url,size=path.stat().st_size))
        preview = json.dumps(output,ensure_ascii=False)
        image_files = [Path(item['path']) for item in output.get('outputs',[]) if item['path'].lower().endswith('.png')][:10]
        image_urls = [pykernel.file_url(ctx.session_id,path) for path in image_files]
        return ToolOutcome(True,preview,display=PythonDisplay(code='',output=preview[:16000],files=attachments,images=[url for url in image_urls if url]),images=image_files if ctx.vision else [])
    finally:
        if proc.returncode is None:
            await asyncio.to_thread(kill_tree,proc.pid); await proc.wait()


IMPL = {'office_file':action,'office_file_help':help_tool,'setup_document_ocr':setup_ocr}
