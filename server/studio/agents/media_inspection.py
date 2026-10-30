"""CPU media inspection with bounded local-file access and sampled reference frames."""
from __future__ import annotations
import asyncio
import hashlib
import json
import math
import uuid
from pathlib import Path
from .. import config, media
from ..agent.types import ToolSpec, ToolOutcome, ToolFailure
from ..agent.pykernel import file_url
from ..osenv import NO_WINDOW
from ..proc import kill_tree
from ..schemas_workspace import FileArtifact, PythonDisplay
from .tools import obj, S
from .file_tools import resolve_source

SPECS = [ToolSpec('inspect_media','Inspect local video/audio streams, duration and source hash. Optionally extract up to 12 timestamped video frames for visual analysis. No model generation or remote download. Requires installed FFmpeg/FFprobe.',obj({'source':S,'timestamps':{'type':'array','items':{'type':'number','minimum':0},'maxItems':12}},['source']))]


async def run(arguments):
    process = await asyncio.create_subprocess_exec(*arguments,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,creationflags=NO_WINDOW)
    async def read(stream):
        chunks,total = [],0
        while chunk := await stream.read(16384):
            total += len(chunk)
            if total > 2*1024*1024: raise ToolFailure('Media process output exceeds its limit')
            chunks.append(chunk)
        return b''.join(chunks)
    try:
        out,error = await asyncio.wait_for(asyncio.gather(read(process.stdout),read(process.stderr)),60)
        await asyncio.wait_for(process.wait(),10)
        if process.returncode: raise ToolFailure('Media inspection failed: ' + error.decode(errors='replace')[-2000:])
        return out
    finally:
        if process.returncode is None:
            await asyncio.to_thread(kill_tree,process.pid); await process.wait()


async def inspect(a,ctx):
    source = Path(resolve_source(ctx.session_id,a['source'],max_bytes=500*1024*1024))
    if source.suffix.lower() not in ('.mp4','.mov','.mkv','.webm','.avi','.wav','.mp3','.m4a','.flac','.ogg'):
        raise ToolFailure('Choose a supported video or audio file')
    try: ffprobe = media.ffprobe()
    except media.MediaError as exc: raise ToolFailure(str(exc)) from exc
    value = json.loads(await run([ffprobe,'-v','error','-protocol_whitelist','file,pipe','-print_format','json','-show_format','-show_streams',str(source)]))
    duration = float(value.get('format',{}).get('duration') or 0)
    timestamps = a.get('timestamps',[])
    if len(timestamps)>12 or any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or t<0 or (duration and t>=duration) for t in timestamps):
        raise ToolFailure('Supply at most 12 finite timestamps inside the clip duration')
    digest = await asyncio.to_thread(hash_file,source)
    directory = config.OUTPUTS_DIR/'media-inspection'/ctx.session_id/uuid.uuid4().hex[:12]
    directory.mkdir(parents=True,exist_ok=True)
    frames,attachments,paths = [],[],[]
    for i,timestamp in enumerate(timestamps):
        target = directory/f'frame-{i+1}.png'
        await run([media.ffmpeg(),'-v','error','-threads','2','-protocol_whitelist','file,pipe','-ss',str(timestamp),'-i',str(source),'-frames:v','1','-filter_threads','2','-vf','scale=1024:1024:force_original_aspect_ratio=decrease',str(target)])
        if not target.is_file(): raise ToolFailure('No video frame at requested timestamp')
        url = file_url(ctx.session_id,target)
        frames.append({'timestamp':timestamp,'url':url,'path':str(target)})
        attachments.append(FileArtifact(name=target.name,path=str(target),url=url,size=target.stat().st_size)); paths.append(target)
    output = json.dumps({'source':str(source),'source_hash':digest,'metadata':value,'frames':frames},ensure_ascii=False)
    return ToolOutcome(True,output,display=PythonDisplay(code='',output=output[:16000],files=attachments,images=[item['url'] for item in frames if item['url']]),images=paths if ctx.vision else [])


def hash_file(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


IMPL = {'inspect_media':inspect}
