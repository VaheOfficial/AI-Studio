"""Local exact-frame export. Rendering uses no model, network service or arbitrary agent code."""
from __future__ import annotations
import base64,html,json,math,shutil,subprocess,threading,time,uuid,wave,array
from pathlib import Path
from collections import Counter
from .. import config,db,media
from ..jobs import jobs,JobError
from ..osenv import NO_WINDOW
from ..schemas import JobResult,Output
from ..schemas_animation import AnimationComposition,AnimationRenderRequest,AnimationValidation
from .catalog import PALETTES,SCHEMAS

_LOCK=threading.Lock()
ENGINE=Path(__file__).with_name('engine.js')
ADVANCED=Path(__file__).with_name('advanced.js')
FLUID=Path(__file__).with_name('fluid.js')
PLAYER_CSS=Path(__file__).with_name('player.css')
MATERIALS=Path(__file__).with_name('materials.js')
PAINTERLY=Path(__file__).with_name('painterly.js')

def validation(composition):
    warnings=[];counts=Counter()
    for scene in composition.scenes:
        for layer in scene.layers:
            counts[layer.component]+=1
            if layer.component=='text':
                duration=layer.duration or scene.duration-layer.start
                words=len(layer.props['text'].split())
                if words/3.5>duration: warnings.append(f'{scene.id}/{layer.id}: shorten the text or hold it longer for reading.')
                if not layer.props['text'].strip():warnings.append(f'{scene.id}/{layer.id}: text is empty.')
                if layer.props.get('mode') in ('letters','words','lines'):
                    mode=layer.props['mode'];units=len(layer.props['text']) if mode=='letters' else len(layer.props['text'].split()) if mode=='words' else len(layer.props['text'].splitlines())
                    stagger=layer.props.get('stagger',.025 if mode=='letters' else .1 if mode=='words' else .12)
                    if max(0,units-1)*stagger+layer.props.get('duration',.8 if mode=='lines' else .65)>duration:warnings.append(f'{scene.id}/{layer.id}: staggered text will not fully settle before the layer ends.')
                if layer.props.get('size',.11)<.025:warnings.append(f'{scene.id}/{layer.id}: small text may not survive mobile viewing.')
    for cue in composition.audio:
        if cue.text and not cue.source:warnings.append(f'{cue.id}: narration is planned but no audio is attached. Render will not invoke a voice model.')
    return AnimationValidation(duration=composition.duration,frames=math.ceil(composition.duration*composition.fps),warnings=warnings,component_counts=dict(counts))

def probe_audio(path):
    completed=subprocess.run([media.ffprobe(),'-v','error','-protocol_whitelist','file,pipe','-show_entries','format=duration','-of','json',str(path)],capture_output=True,timeout=20,creationflags=NO_WINDOW)
    if completed.returncode:raise JobError('The attached audio could not be inspected')
    duration=float(json.loads(completed.stdout).get('format',{}).get('duration',0))
    if not math.isfinite(duration) or duration<=0 or duration>180:raise JobError('Audio must have a finite duration of at most 180 seconds')
    return duration

def asset_path(source,sid):
    from ..agents.file_tools import resolve_source
    if not sid and not source.startswith('/files/') and not Path(source).is_absolute():raise JobError('Relative asset paths require a conversation workspace')
    return Path(resolve_source(sid or 'animation-standalone',source,max_bytes=64*1024*1024))

def prepare_assets(composition,directory,sid):
    from PIL import Image,ImageOps
    result=composition.model_dump(mode='json');audio=[];copied={};asset_bytes=0;decoded_pixels=0;model_elements=0;checked_models={};image_sizes={}
    assets=directory/'assets';assets.mkdir(exist_ok=True)
    if any(layer.component=='scene3d' for scene in composition.scenes for layer in scene.layers):
        shutil.copytree(ENGINE.parent/'vendor'/'three',assets/'three')
        shutil.copyfile(ENGINE.with_name('scene3d.js'),assets/'scene3d.js')
    def account(target):
        nonlocal asset_bytes
        asset_bytes+=target.stat().st_size
        if asset_bytes>256*1024*1024:raise JobError('Composition assets exceed the 256 MB copy budget')
    def account_decoded(pixels,elements=0):
        nonlocal decoded_pixels,model_elements
        decoded_pixels+=pixels;model_elements+=elements
        if decoded_pixels>64000000:raise JobError('Composition images and model textures exceed a combined 64 megapixels')
        if model_elements>8000000:raise JobError('Composition models exceed eight million scalar accessor elements')
    def copy_asset(source):
        if source not in copied:
            target=assets/(uuid.uuid4().hex[:10]+source.suffix.lower());shutil.copyfile(source,target);account(target);copied[source]=target
        return copied[source]
    for scene in result['scenes']:
        for layer in scene['layers']:
            if layer['component']=='scene3d':
                from .glb import inspect_glb
                from .rigs import expand_presets
                layer['props']['nodes']=expand_presets(layer['props']['nodes'])
                for node in layer['props']['nodes']:
                    if node['kind']!='model':continue
                    source=asset_path(node['source'],sid)
                    if source.suffix.lower()!='.glb':raise JobError('3D assets must use self-contained GLB files')
                    if source not in checked_models:
                        checked_models[source]=inspect_glb(source);budget=checked_models[source]['_studio_resource_budget'];account_decoded(budget['texture_pixels'],budget['scalar_elements'])
                    document=checked_models[source]
                    if node.get('clip') and node['clip'] not in [clip.get('name','') for clip in document.get('animations',[])]:raise JobError('Requested animation clip is absent from the GLB')
                    node['source']='assets/'+copy_asset(source).name
            if layer['component'] not in ('image','tiles') or not layer['props'].get('source'):continue
            source=asset_path(layer['props']['source'],sid)
            if source.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):raise JobError('Animation image assets must be PNG, JPEG or WebP')
            if source not in copied:
                with Image.open(source) as image:
                    if image.width*image.height>16000000:raise JobError('Image asset exceeds 16 megapixels')
                    account_decoded(image.width*image.height)
                    oriented=ImageOps.exif_transpose(image)
                    image_sizes[source]=oriented.size
                    target=assets/(uuid.uuid4().hex[:10]+'.png');oriented.convert('RGBA' if 'A' in oriented.getbands() or 'transparency' in oriented.info else 'RGB').save(target);account(target);copied[source]=target
            target=copied[source]
            if layer['component']=='image':
                columns=layer['props'].get('columns',1);rows=math.ceil(layer['props'].get('frames',1)/columns);width,height=image_sizes[source]
                if width%columns or height%rows:raise JobError('Sprite sheet dimensions must divide evenly into its grid')
            layer['props']['source']='assets/'+target.name
    for track in composition.audio:
        if not track.source:continue
        source=asset_path(track.source,sid)
        if source.suffix.lower() not in ('.wav','.mp3','.flac','.m4a','.ogg'):raise JobError('Attach a supported local audio file')
        duration=probe_audio(source)
        encoded_duration=math.ceil(composition.duration*composition.fps)/composition.fps
        if track.start+duration>encoded_duration+1e-6:raise JobError(f'Audio {track.id} runs beyond the encoded film. Extend or retime the scenes instead of silently cutting narration.')
        target=copy_asset(source)
        audio.append({'id':track.id,'path':str(target),'start':track.start,'gain':track.gain,'duration':duration,'narration':bool(track.text)})
    for face in result['fonts']:
        source=asset_path(face['source'],sid)
        if source.suffix.lower() not in ('.woff2','.woff','.ttf','.otf') or source.stat().st_size>10*1024*1024:raise JobError('Attach a local WOFF2, WOFF, TTF or OTF font of at most 10 MB')
        face['source']='assets/'+copy_asset(source).name
    for face,prefix in [('sans','geist-latin-wght-normal'),('mono','geist-mono-latin-wght-normal')]:
        candidates=list((config.WEB_DIR/'assets').glob(prefix+'-*.woff2'))
        if candidates:
            shutil.copyfile(candidates[0],assets/(face+'.woff2'))
            license_name='Geist-LICENSE.txt' if face=='sans' else 'GeistMono-LICENSE.txt'
            shutil.copyfile(ENGINE.parent/'vendor'/'fonts'/license_name,assets/license_name)
    for source,target in [('Oswald.ttf','condensed.ttf'),('OFL-Oswald.txt','OFL-Oswald.txt')]:
        shutil.copyfile(ENGINE.parent/'vendor'/'fonts'/source,assets/target)
    return result,audio

def page_html(data, *, soundtrack=False):
    encoded=json.dumps(data,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    theme=json.dumps(PALETTES)
    limits=json.dumps({name:{key:{k:v for k,v in parameter.items() if k in ('minimum','maximum')} for key,parameter in schema['properties'].items() if parameter.get('type')=='number'} for name,schema in SCHEMAS.items()})
    title=html.escape(data['title'])
    fluid_script='<script>'+FLUID.read_text(encoding='utf-8')+MATERIALS.read_text(encoding='utf-8')+'</script>'
    scene3d='<script type="importmap">{"imports":{"three":"./assets/three/build/three.module.js"}}</script><script>window.Animation3DReady=import("./assets/scene3d.js");</script>' if any(layer['component']=='scene3d' for scene in data['scenes'] for layer in scene['layers']) else ''
    font_css=''.join(f"@font-face{{font-family:StageFont_{face['id']};src:url('{html.escape(face['source'],quote=True)}');font-weight:100 900;font-display:block}}" for face in data.get('fonts',[]))
    font_css+='@font-face{font-family:StageCondensed;src:url(assets/condensed.ttf);font-weight:200 700;font-display:block}'
    scene3d+=fluid_script
    if any(layer['component']=='mosaic_scene' for scene in data['scenes'] for layer in scene['layers']):
        from .mosaic_scene import script
        scene3d+='<script>'+script()+'</script>'
    if any(scene.get('painterly') for scene in data['scenes']):scene3d+='<script>'+PAINTERLY.read_text(encoding='utf-8')+'</script>'
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>{font_css}{PLAYER_CSS.read_text(encoding='utf-8')}main{{max-width:{data['width']}px}}</style></head>
<body>{scene3d}<main><canvas id="stage" aria-label="{title}"></canvas><footer><button id="play" aria-label="Play animation">Play</button><input id="seek" aria-label="Animation position" type="range" min="0" step="0.001" value="0"><span id="clock">0.0s</span></footer><p>{title}</p></main>{'<audio id="soundtrack" src="soundtrack.wav" preload="metadata"></audio>' if soundtrack else ''}
<script>window.AnimationPropertyLimits={limits};{ADVANCED.read_text(encoding='utf-8')}{ENGINE.read_text(encoding='utf-8')}</script><script>const film={encoded};const theme={theme};let playing=false,start=0,offset=0;const slider=document.getElementById('seek'),button=document.getElementById('play'),audio=document.getElementById('soundtrack');const duration=film.scenes.reduce((a,s)=>a+s.duration,0);slider.max=duration;function show(t){{AnimationRenderer.seek(t);slider.value=t;document.getElementById('clock').textContent=t.toFixed(1)+'s'}}window.AnimationReady=AnimationRenderer.initialize(film,document.getElementById('stage'),theme).then(()=>{{show(0);return true}});window.seek=t=>{{show(t);return AnimationReport}};function tick(now){{if(!playing)return;let t=offset+(now-start)/1000;if(t>=duration){{playing=false;button.textContent='Play';button.setAttribute('aria-label','Play animation');audio?.pause();show(duration);return}}show(t);requestAnimationFrame(tick)}}button.onclick=async()=>{{await AnimationReady;playing=!playing;button.textContent=playing?'Pause':'Play';button.setAttribute('aria-label',playing?'Pause animation':'Play animation');if(playing){{offset=Number(slider.value);if(offset>=duration)offset=0;start=performance.now();if(audio){{audio.currentTime=offset;void audio.play().catch(()=>{{}})}}requestAnimationFrame(tick)}}else{{audio?.pause()}}}};slider.oninput=()=>{{offset=Number(slider.value);start=performance.now();show(offset);if(audio)audio.currentTime=offset}};if(matchMedia('(prefers-reduced-motion: reduce)').matches)playing=false;</script></body></html>'''

def synthesize(composition,path,audio):
    rate=24000;count=math.ceil(composition.duration*rate);samples=array.array('h');beat=60/composition.bpm
    voiced=[(a['start'],a['start']+a['duration']) for a in audio if a['narration']]
    for i in range(count):
        t=i/rate;bar=int(t/(beat*4));root=[110,146.8324,164.8138,130.8128][bar%4];value=0
        if composition.sound.music!='none':
            chord=sum(math.sin(math.tau*root*ratio*t+math.sin(t*.31)*.025)*weight for ratio,weight in [(1,.6),(1.259921,.25),(1.498307,.2)])*.16
            if composition.sound.music=='ambient':value=chord*(.6+.4*math.sin(t*.38)**2)
            else:
                u=t%beat;kick=math.sin(math.tau*(42*u+138/28*(1-math.exp(-28*u))))*math.exp(-u*18)*.32
                eighth=t%(beat/2);noise=((i*1103515245+12345)&65535)/32768-1
                hat=noise*math.exp(-eighth*170)*.04
                value=chord*.5+kick+hat
                if composition.sound.music=='lofi':value=chord*.85+kick*.55+hat*.3
            value*=composition.sound.gain*(.25 if any(a<=t<=b+.15 for a,b in voiced) else 1)
        for cue in composition.sound.cues:
            u=t-cue.time
            if not 0<=u<.8:continue
            if cue.type=='click':effect=math.sin(math.tau*1200*u)*math.exp(-u*100)*.35
            elif cue.type=='chime':effect=(math.sin(math.tau*880*u)+math.sin(math.tau*1320*u)*.35)*math.exp(-u*7)*.3
            elif cue.type=='impact':effect=math.sin(math.tau*(42*u+6*(1-math.exp(-u*15))))*math.exp(-u*12)*.6
            else:effect=math.sin(math.tau*(180*u+1700*u*u))*math.sin(math.pi*clamp_num(u/.7))**2*.15
            value+=effect*cue.gain
        fade=min(1,t/.025,max(0,(composition.duration-t)/.25));samples.append(int(math.tanh(value)*fade*32700))
    if __import__('sys').byteorder!='little':samples.byteswap()
    with wave.open(str(path),'wb') as output:output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(samples.tobytes())

def clamp_num(x):return max(0,min(1,x))

def soundtrack(composition,directory,audio,ctx):
    if composition.sound.music=='none' and not composition.sound.cues and not audio:return None
    bed=directory/'bed.wav';synthesize(composition,bed,audio);target=directory/'soundtrack.wav'
    if not audio:bed.replace(target);return target
    args=[media.ffmpeg(),'-v','error','-y','-protocol_whitelist','file,pipe','-i',str(bed)]
    filters=['[0:a]aresample=48000[bed]'];names=['[bed]']
    for index,track in enumerate(audio,1):
        args+=['-protocol_whitelist','file,pipe','-i',track['path']]
        name=f'a{index}';filters.append(f'[{index}:a]aresample=48000,adelay=delays={round(track["start"]*48000)}S:all=1,volume={track["gain"]}[{name}]');names.append(f'[{name}]')
    filters.append(''.join(names)+f'amix=inputs={len(names)}:normalize=0,alimiter=limit=0.95[mix]')
    args+=['-filter_complex',';'.join(filters),'-map','[mix]','-t',str(composition.duration),'-ac','1','-ar','48000',str(target)]
    media.run(args,ctx=ctx,timeout=120);bed.unlink(missing_ok=True);return target

def sample_times(composition):
    values=[];start=0
    for scene in composition.scenes:
        values.extend([start+scene.duration*.18,start+scene.duration*.55,start+scene.duration*.88]);start+=scene.duration
    if len(values)>24:values=[composition.duration*(i+.5)/24 for i in range(24)]
    return values

def render(ctx,request):
    from playwright.sync_api import sync_playwright
    from PIL import Image,ImageDraw
    from urllib.parse import urlsplit,unquote
    composition=request.composition;report=validation(composition)
    directory=config.OUTPUTS_DIR/'animations'/ctx.id;directory.mkdir(parents=True,exist_ok=False)
    try:
        data,audio=prepare_assets(composition,directory,request.session_id)
        score=soundtrack(composition,directory,audio,ctx)
        (directory/'composition.json').write_text(composition.model_dump_json(indent=2),encoding='utf-8')
        page_path=directory/'preview.html';page_path.write_text(page_html(data,soundtrack=score is not None),encoding='utf-8')
        ctx.check_cancelled();ctx.log('Preparing deterministic browser renderer')
        with _LOCK:
            ctx.check_cancelled()
            with sync_playwright() as playwright:
                candidates=['msedge','chrome',None];browser=None
                for channel in candidates:
                    try:
                        browser=playwright.chromium.launch(channel=channel,headless=True,args=['--disable-gpu','--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-background-timer-throttling']);break
                    except Exception:continue
                if not browser:raise JobError('Install Edge, Chrome or the Playwright Chromium runtime for animation rendering')
                try:
                    page=browser.new_page(viewport={'width':composition.width,'height':composition.height},device_scale_factor=1)
                    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    def route(request_route):
                        parsed=urlsplit(request_route.request.url)
                        if parsed.scheme=='data':request_route.continue_();return
                        # Serve copied assets from one intercepted origin. file:// images taint a
                        # Canvas in Chromium; fulfilling local bytes avoids disabling browser security.
                        if parsed.scheme=='http' and parsed.netloc=='animation.local':
                            candidate=(directory/unquote(parsed.path).lstrip('/')).resolve()
                            if candidate.is_relative_to(directory.resolve()) and candidate.is_file():
                                request_route.fulfill(path=str(candidate));return
                        request_route.abort()
                    page.route('**/*',route)
                    page.goto('http://animation.local/preview.html',wait_until='load',timeout=30000)
                    if errors:raise JobError('Animation runtime error: '+errors[0][:1000])
                    page.evaluate('async()=>await AnimationReady')
                    width=320;height=max(90,round(width*composition.height/composition.width));times=request.review_times or sample_times(composition);columns=3
                    sheet=Image.new('RGB',(columns*width,math.ceil(len(times)/columns)*(height+26)),'#131720');draw=ImageDraw.Draw(sheet)
                    samples=[];render_warnings=[];crop_sheet=None
                    if request.review_crop:
                        crop=request.review_crop
                        crop_box=(round(crop.x*composition.width),round(crop.y*composition.height),round((crop.x+crop.width)*composition.width),round((crop.y+crop.height)*composition.height))
                        if crop_box[2]<=crop_box[0] or crop_box[3]<=crop_box[1]:raise JobError('Review crop is smaller than one pixel')
                        crop_height=max(1,round(320*(crop_box[3]-crop_box[1])/(crop_box[2]-crop_box[0])))
                        if crop_height>1280:raise JobError('Review crop aspect ratio exceeds the contact-sheet budget')
                        crop_sheet=Image.new('RGB',(columns*320,math.ceil(len(times)/columns)*(crop_height+26)),'#131720');crop_draw=ImageDraw.Draw(crop_sheet)
                    def frame(t):
                        ctx.check_cancelled()
                        value=page.evaluate('(t)=>{seek(t);return {pixels:document.getElementById("stage").toDataURL("image/png"),report:AnimationReport}}',t)
                        if errors:raise JobError('Animation runtime error: '+errors[0][:1000])
                        render_warnings.extend(value['report']['warnings']);return base64.b64decode(value['pixels'].split(',',1)[1])
                    for i,t in enumerate(times):
                        import io
                        pixels=frame(t);target=directory/f'frame-{i+1:02d}.png';target.write_bytes(pixels)
                        if crop_sheet:
                            full=Image.open(io.BytesIO(pixels));cropped=full.crop(crop_box);cropped.save(directory/f'crop-{i+1:02d}.png');cx=i%columns*320;cy=i//columns*(crop_height+26);crop_sheet.paste(cropped.convert('RGB').resize((320,crop_height)),(cx,cy));crop_draw.text((cx+8,cy+crop_height+5),f'{t:.3f}s',fill='white')
                        image=Image.open(io.BytesIO(pixels)).convert('RGB').resize((width,height));x=i%columns*width;y=i//columns*(height+26);sheet.paste(image,(x,y));draw.text((x+8,y+height+5),f'{t:.2f}s',fill='white');samples.append({'time':t,'path':target.name})
                    sheet.save(directory/'storyboard.jpg',quality=92)
                    if crop_sheet:crop_sheet.save(directory/'review-crops.jpg',quality=95)
                    # Seeking backwards must reproduce the same pixels, including textures and text.
                    first=frame(composition.duration*.37);frame(composition.duration*.81);second=frame(composition.duration*.37)
                    if first!=second:raise JobError('Renderer failed seek determinism; export was stopped')
                    runtime=page.evaluate('AnimationReport')
                    result={'title':composition.title,'duration':composition.duration,'frames':report.frames,'fps':composition.fps,'width':composition.width,'height':composition.height,'scenes':len(composition.scenes),'deterministic':True,'warnings':report.warnings+sorted({item['warning'] for item in render_warnings}),'samples':samples,'voice_generated':False,'audio_tracks':audio,'network':'blocked','engine':'declarative-canvas-v2','quality':request.quality,'surface_renderer':runtime.get('surface_renderer'),'finishing':composition.finishing.model_dump()}
                    output=None
                    result.update(engine='declarative-canvas-v3',review_times=times,review_crop=request.review_crop.model_dump() if request.review_crop else None)
                    if not request.preview_only:
                        target=directory/'film.mp4';log=(directory/'encode.log').open('wb')
                        args=[media.ffmpeg(),'-v','error','-y','-f','image2pipe','-framerate',str(composition.fps),'-i','pipe:0']
                        if score:args+=['-protocol_whitelist','file,pipe','-i',str(score)]
                        args+=['-c:v','libx264','-preset','medium' if request.quality=='final' else 'fast','-crf',{'draft':'23','standard':'18','final':'16'}[request.quality],'-pix_fmt','yuv420p','-threads','2','-movflags','+faststart']
                        args+=['-vf','scale=in_range=pc:out_range=tv:out_color_matrix=bt709,setparams=range=limited:color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709','-filter_threads','2','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','iec61966-2-1']
                        if score:args+=['-c:a','aac','-b:a','160k','-af','apad','-t',str(report.frames/composition.fps)]
                        args+=[str(target)]
                        try:
                            process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log,creationflags=NO_WINDOW)
                        except BaseException:
                            log.close();raise
                        def stop_encoder():
                            # FFmpeg has no child workers. Popen keeps the owned process handle,
                            # avoiding a PID lookup race between the cancel hook and cleanup.
                            try:
                                if process.poll() is None:process.kill()
                            except ProcessLookupError:pass
                        started=time.monotonic()
                        try:
                            ctx.on_cancel(stop_encoder)
                            for index in range(report.frames):
                                if time.monotonic()-started>900:raise JobError('Animation export exceeded the 15-minute budget; use a smaller stage or simpler layers')
                                ctx.check_cancelled()
                                encoded=page.evaluate('(v)=>{seek(v.time);return document.getElementById("stage").toDataURL(v.format,0.94).split(",")[1]}',{'time':index/composition.fps,'format':'image/png' if request.quality=='final' else 'image/jpeg'})
                                if errors:raise JobError('Animation runtime error: '+errors[0][:1000])
                                process.stdin.write(base64.b64decode(encoded));ctx.update(progress=.12+.83*(index+1)/report.frames,message=f'Frame {index+1} of {report.frames}')
                            process.stdin.close();process.wait(timeout=60)
                            if process.returncode:raise JobError('Animation encoder failed; inspect encode.log')
                        finally:
                            try:
                                stop_encoder();process.wait(timeout=20)
                            finally:
                                try:
                                    if process.stdin and not process.stdin.closed:process.stdin.close()
                                except OSError:pass
                                log.close()
                        value=json.loads(subprocess.run([media.ffprobe(),'-v','error','-count_frames','-show_streams','-of','json',str(target)],capture_output=True,timeout=30,creationflags=NO_WINDOW).stdout)
                        video=next(stream for stream in value['streams'] if stream['codec_type']=='video')
                        if int(video.get('nb_read_frames',0))!=report.frames:raise JobError('Encoded video frame count did not match the composition')
                        expected={'color_range':'tv','color_space':'bt709','color_primaries':'bt709','color_transfer':'iec61966-2-1'}
                        if any(video.get(key)!=value for key,value in expected.items()):raise JobError('Encoder did not retain the declared color profile')
                        result['color_profile']=expected
                        result['encoded_frames']=int(video['nb_read_frames']);result['encoded_duration']=float(video.get('duration',report.frames/composition.fps));result['audio_present']=any(s['codec_type']=='audio' for s in value['streams'])
                        output=Output(id=ctx.id,kind='video',url=f'/files/outputs/animations/{ctx.id}/film.mp4',model_id='animation:canvas',prompt=composition.title,params={'engine':'declarative-canvas-v2','quality':request.quality,'fps':composition.fps,'scenes':len(composition.scenes),'seed':composition.seed,'composition':f'/files/outputs/animations/{ctx.id}/composition.json','preview':f'/files/outputs/animations/{ctx.id}/preview.html','storyboard':f'/files/outputs/animations/{ctx.id}/storyboard.jpg'},created_at=db.now_iso(),width=composition.width,height=composition.height,duration_s=report.frames/composition.fps)
                        output.params['engine']='declarative-canvas-v3';db.insert_output(output,str(target))
                    (directory/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                    ctx.update(message='Animation preview ready' if request.preview_only else 'Animation exported and frame count verified')
                    return JobResult(outputs=[output] if output else [])
                finally:browser.close()
    except Exception:
        (directory/'FAILED').write_text('Render did not complete. Partial files are not a successful export.',encoding='utf-8')
        raise

def submit(request:AnimationRenderRequest):
    media.ffmpeg();media.ffprobe()
    return jobs.submit('generate','Animation · '+request.composition.title,lambda ctx:render(ctx,request),ref='animation:canvas')
