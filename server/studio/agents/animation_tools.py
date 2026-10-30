"""Agents direct reusable animation components rather than authoring a renderer."""
from __future__ import annotations
import asyncio,json
from pathlib import Path
from .. import config
from ..agent.types import ToolFailure,ToolOutcome,ToolSpec
from ..schemas_animation import AnimationComposition,AnimationRenderRequest
from ..schemas_workspace import AnimationDisplay,AudioTimingDisplay
from ..animation import catalog,recipes,render,projects
from ..jobs import jobs
from .tools import obj,S,O

SPECS=[
 ToolSpec('animation_analyze_audio','Measure an attached local audio track before directing: duration, energy hits, quiet gaps, loudness and an explicitly uncertain tempo estimate. No speech model or provider calls. Use hits to place cues and actions; word subtitles still need the existing transcription/alignment tools.',obj({'source':S},['source'])),
 ToolSpec('animation_catalog','Discover reusable animation components, grouped vector artwork, material-lit 3D surfaces, typography, motion tracks, styles, recipes and the composition JSON Schema. Supply component to read a focused parameter contract. Local export uses Canvas and software WebGL; no generation model is required.',obj({'component':S})),
 ToolSpec('animation_recipe','Get an editable original composition recipe. Direct its scenes, copy, palette, camera and motion as data. Use animation_catalog to find recipe IDs.',obj({'recipe':S,'title':S,'width':{'type':'integer'},'height':{'type':'integer'},'fps':{'type':'integer'},'seed':{'type':'integer'}},['recipe'])),
 ToolSpec('animation_project','Create a chat-scoped, versioned animation from a recipe or composition, read its compact scene/layer manifest, or revise it with small atomic edits. Edits select stable scene_id/layer_id and a relative JSON pointer such as /props/roughness. Use the returned project_id and observed version with animation_render; avoid repeating an entire film JSON for each change.',obj({'action':{'type':'string','enum':['create','read','edit']},'recipe':S,'composition':O,'title':S,'width':{'type':'integer'},'height':{'type':'integer'},'fps':{'type':'integer'},'project_id':S,'version':{'type':'integer','minimum':1},'scene_id':S,'include_composition':{'type':'boolean'},'edits':{'type':'array','minItems':1,'maxItems':32,'items':obj({'op':{'type':'string','enum':['set','remove','add_scene','remove_scene','add_layer','remove_layer']},'scene_id':S,'layer_id':S,'path':S,'value':{}},['op'])}},['action'])),
 ToolSpec('animation_validate','Validate a composition’s component parameters, timing and readable text holds before rendering.',obj({'composition':O},['composition'])),
 ToolSpec('animation_render','Render a composition OR an observed project_id/version to a local player, storyboard, report and exact-frame MP4. No model or network calls. Use quality:final for lossless intermediate frames. Set preview_only to inspect before export. Optional review_times selects up to 24 global timestamps; review_crop requests normalized full-resolution face/joint/type crops and a separate contact sheet. Voice is never generated implicitly.',obj({'composition':O,'project_id':S,'version':{'type':'integer','minimum':1},'preview_only':{'type':'boolean'},'wait':{'type':'boolean'},'quality':{'type':'string','enum':['draft','standard','final']},'review_times':{'type':'array','maxItems':24,'items':{'type':'number','minimum':0,'maximum':120}},'review_crop':obj({key:{'type':'number','minimum':0,'maximum':1} for key in ('x','y','width','height')},['x','y','width','height'])}),needs_approval=True),
 ToolSpec('animation_prepare_voice','Explicitly prepare planned narration cues using Studio’s existing text_to_speech dispatcher. Reuses normal voice/provider permissions. Returns actual clip durations and the updated composition for retiming. This is separate from animation rendering and is not required for silent or synthesized-score films.',obj({'composition':O},['composition']),needs_approval=True),
]
project_parameters=next(spec for spec in SPECS if spec.name=='animation_project').parameters['properties']
project_parameters.update(layer_id=S,node_id=S)
project_parameters['edits']['items']['properties']['node_id']=S
project_parameters['edits']['items']['properties']['op']['enum'].extend(['add_node','remove_node'])
async def discover(a,ctx):
    value=catalog.catalog()
    if a.get('component'):
        name=a['component']
        if name not in value['components']:raise ToolFailure('Unknown animation component; inspect the catalog overview')
        value={'version':value['version'],'component':name,**value['components'][name],'directing_controls':value['directing_controls'],'coordinates':value['coordinates']}
    return ToolOutcome(True,json.dumps(value,ensure_ascii=False))
async def analyze_audio(a,ctx):
    from ..animation.audio_analysis import analyze
    value=await asyncio.to_thread(analyze,a['source'],ctx.session_id)
    display=AudioTimingDisplay(**{key:value[key] for key in ('source','duration','peak_dbfs','tempo_estimate_bpm','hits','pauses','energy_by_second')})
    return ToolOutcome(True,json.dumps(value,ensure_ascii=False),display=display)
async def recipe(a,ctx):
    value=recipes.recipe(a['recipe'],**{key:value for key,value in a.items() if key!='recipe'})
    return ToolOutcome(True,value.model_dump_json())
async def validate(a,ctx):
    value=AnimationComposition.model_validate(a['composition'])
    return ToolOutcome(True,render.validation(value).model_dump_json())
async def project(a,ctx):
    action=a['action']
    if action!='read' and any(a.get(key) for key in ('scene_id','layer_id','node_id')):raise ToolFailure('Read selectors belong to read actions; editing targets are inside edits')
    if action=='create':
        if ('recipe' in a)==('composition' in a):raise ToolFailure('Create using exactly one recipe or composition')
        composition=recipes.recipe(a['recipe'],**{key:a[key] for key in ('title','width','height','fps') if key in a}) if 'recipe' in a else AnimationComposition.model_validate(a['composition'])
        artifact=projects.save(ctx.session_id,composition)
    elif action=='edit':
        if not a.get('project_id') or not a.get('version') or not a.get('edits'):raise ToolFailure('Editing requires project_id, its observed version and edits')
        artifact,composition=projects.edit(ctx.session_id,a['project_id'],a['version'],a['edits'])
    else:
        if not a.get('project_id'):raise ToolFailure('Reading requires a project_id')
        artifact,composition=projects.read(ctx.session_id,a['project_id'],a.get('version'))
    result=projects.summary(artifact,composition)
    if (a.get('layer_id') or a.get('node_id')) and not a.get('scene_id'):raise ToolFailure('A layer/node read requires its scene_id')
    if a.get('node_id') and not a.get('layer_id'):raise ToolFailure('A node read requires its layer_id')
    if a.get('scene_id'):
        selected=next((scene for scene in composition.scenes if scene.id==a['scene_id']),None)
        if not selected:raise ToolFailure('Scene not found')
        if a.get('layer_id'):
            selected_layer=next((layer for layer in selected.layers if layer.id==a['layer_id']),None)
            if not selected_layer:raise ToolFailure('Layer not found')
            if a.get('node_id'):
                if selected_layer.component!='scene3d':raise ToolFailure('A node read requires a scene3d layer')
                selected_node=next((node for node in selected_layer.props['nodes'] if node['id']==a['node_id']),None)
                if not selected_node:raise ToolFailure('Node not found')
                result['node']=selected_node
            else:result['layer']=selected_layer.model_dump(mode='json')
        else:result['scene']=selected.model_dump(mode='json')
    if a.get('include_composition'):result['composition']=composition.model_dump(mode='json')
    return ToolOutcome(True,json.dumps(result,ensure_ascii=False))
async def export(a,ctx):
    receipt={}
    if ('composition' in a)==('project_id' in a):raise ToolFailure('Render exactly one composition or versioned project')
    if 'project_id' in a:
        if not a.get('version'):raise ToolFailure('Rendering a project requires its observed version')
        artifact,value=projects.read(ctx.session_id,a['project_id'],a['version']);receipt={'project_id':artifact.id,'project_version':artifact.version,'project_hash':artifact.content_hash}
    else:value=AnimationComposition.model_validate(a['composition'])
    job=await asyncio.to_thread(render.submit,AnimationRenderRequest(composition=value,session_id=ctx.session_id,preview_only=a.get('preview_only',False),quality=a.get('quality','standard'),review_times=a.get('review_times',[]),review_crop=a.get('review_crop')))
    if not a.get('wait',True):return ToolOutcome(True,json.dumps({'job_id':job.id,'status':job.status,**receipt,'next':'Inspect get_job; a queued job is not a finished animation.'}))
    try:result=await jobs.wait(job.id)
    except asyncio.CancelledError:jobs.cancel(job.id);raise
    if result.status!='done':return ToolOutcome(False,result.error or result.message or 'Animation did not complete')
    directory=config.OUTPUTS_DIR/'animations'/job.id
    report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    if receipt:report['project']=receipt;(directory/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    prefix=f'/files/outputs/animations/{job.id}/'
    display=AnimationDisplay(title=value.title,preview=prefix+'preview.html',storyboard=prefix+'storyboard.jpg',composition=prefix+'composition.json',report=prefix+'report.json',duration=report['duration'],frames=report['frames'],scenes=report['scenes'],deterministic=report['deterministic'],warnings=report['warnings'],width=report['width'],height=report['height'],fps=report['fps'],quality=report.get('quality','standard'))
    review={'review_crops':prefix+'review-crops.jpg','review_times':report['review_times']} if a.get('review_crop') else {}
    return ToolOutcome(True,json.dumps({'job_id':job.id,**display.model_dump(),'encoded_frames':report.get('encoded_frames'),'voice_generated':False,**receipt,**review},ensure_ascii=False),artifacts=result.result.outputs if result.result else [],display=display,images=[directory/'storyboard.jpg']+([directory/'review-crops.jpg'] if a.get('review_crop') else []))
async def voice(a,ctx):
    if not ctx.invoke:raise ToolFailure('Voice preparation requires the normal agent dispatcher')
    value=AnimationComposition.model_validate(a['composition']);data=value.model_dump(mode='json');timings=[];overruns=[]
    for cue in data['audio']:
        if not cue['text'] or cue['source']:continue
        args={'text':cue['text']}
        if cue['model_id']:args['model_id']=cue['model_id']
        if cue['voice_id']:args['voice_id']=cue['voice_id']
        result=await ctx.invoke('text_to_speech',args)
        if not result.ok:return result
        output=next((o for o in result.artifacts if o.kind=='audio'),None)
        if not output:raise ToolFailure('Speech dispatcher did not return an audio artifact')
        path=render.asset_path(output.url,ctx.session_id);duration=await asyncio.to_thread(render.probe_audio,path)
        cue['source']=output.url;end=cue['start']+duration
        timings.append({'id':cue['id'],'start':cue['start'],'duration':duration,'end':end,'source':output.url})
        if end>value.duration:overruns.append({'id':cue['id'],'required_end':end})
    return ToolOutcome(True,json.dumps({'composition':data,'timings':timings,'overruns':overruns,'next':'Use these measured cue durations to retime scenes and captions. Do not assume estimated narration timing or silently truncate speech.'},ensure_ascii=False))
IMPL={'animation_catalog':discover,'animation_recipe':recipe,'animation_project':project,'animation_validate':validate,'animation_render':export,'animation_prepare_voice':voice,'animation_analyze_audio':analyze_audio}
