"""Mirrors the declarative animation contract; no executable source is accepted."""
from __future__ import annotations
import math,re,json
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

Style=Literal['studio','paper','ink','neon','punk','pixel','mosaic','blueprint']
Component=Literal['text','shape','path','brush','particles','grid','chart','diagram','interface','character','landscape','orbit','cube','machine','weather','image','group','vector','mesh','scene3d','tiles','fluid','mosaic_scene']
Ease=Literal['linear','smooth','cubic_in','cubic_out','cubic_in_out','back_out','elastic_out','bounce_out','step']

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

class AnimationKeyframe(Strict):
    time:float=Field(ge=0,le=120)
    value:float=Field(ge=-10000,le=10000)
    ease:Ease='smooth'
    interpolation:Literal['eased','monotone','log','monotone_log']='eased'

class AnimationColorKeyframe(Strict):
    time:float=Field(ge=0,le=120)
    value:str
    ease:Ease='smooth'

class AnimationMotion(Strict):
    type:Literal['none','float','spin','bounce','wiggle']='none'
    amount:float=Field(default=0.04,ge=0,le=4)
    speed:float=Field(default=1,ge=0,le=20)
    phase:float=Field(default=0,ge=-100,le=100)

class AnimationMask(Strict):
    kind:Literal['rect','ellipse']='rect'
    reveal:float=Field(default=1,ge=0,le=1)
    direction:Literal['left','right','up','down']='up'
    radius:float=Field(default=0,ge=0,le=.5)

class AnimationShadow(Strict):
    color:str='#000000'
    blur:float=Field(default=.025,ge=0,le=.15)
    x:float=Field(default=0,ge=-.5,le=.5)
    y:float=Field(default=.015,ge=-.5,le=.5)

class AnimationPaint(Strict):
    kind:Literal['linear','radial']='linear'
    colors:list[str]=Field(min_length=2,max_length=6)
    angle:float=Field(default=0,ge=-360,le=360)
    x:float=Field(default=0,ge=-1,le=1)
    y:float=Field(default=0,ge=-1,le=1)

class AnimationFinishing(Strict):
    grain:float=Field(default=0,ge=0,le=.25)
    vignette:float=Field(default=0,ge=0,le=1)
    motion_blur:float=Field(default=0,ge=0,le=1)
    samples:int=Field(default=3,ge=1,le=6)

class AnimationFont(Strict):
    id:str=Field(min_length=1,max_length=48,pattern=r'^[a-zA-Z][a-zA-Z0-9_-]+$')
    source:str=Field(min_length=1,max_length=1000)

class AnimationLayer(Strict):
    id:str=Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    component:Component
    paint_pass:Literal['base','light']='base'
    start:float=Field(default=0,ge=0,le=120)
    duration:float|None=Field(default=None,gt=0,le=120)
    x:float=Field(default=0.5,ge=-4,le=4)
    y:float=Field(default=0.5,ge=-4,le=4)
    width:float=Field(default=0.8,gt=0,le=4)
    height:float=Field(default=0.7,gt=0,le=4)
    scale:float=Field(default=1,ge=0,le=10)
    rotation:float=Field(default=0,ge=-10000,le=10000)
    opacity:float=Field(default=1,ge=0,le=1)
    parent:str|None=Field(default=None,min_length=1,max_length=80)
    anchor_x:float=Field(default=.5,ge=0,le=1)
    anchor_y:float=Field(default=.5,ge=0,le=1)
    scale_x:float=Field(default=1,ge=-10,le=10)
    scale_y:float=Field(default=1,ge=-10,le=10)
    skew_x:float=Field(default=0,ge=-75,le=75)
    skew_y:float=Field(default=0,ge=-75,le=75)
    blur:float=Field(default=0,ge=0,le=.15)
    blend:Literal['source-over','multiply','screen','overlay','lighter']='source-over'
    mask:AnimationMask|None=None
    shadow:AnimationShadow|None=None
    paint:AnimationPaint|None=None
    props:dict[str,Any]=Field(default_factory=dict)
    enter:Literal['none','fade','slide_up','pop','draw','type']='none'
    enter_duration:float=Field(default=0.6,ge=0.01,le=10)
    exit:Literal['none','fade','shrink']='none'
    exit_duration:float=Field(default=0.4,ge=0.01,le=10)
    motion:AnimationMotion=Field(default_factory=AnimationMotion)
    tracks:dict[str,list[AnimationKeyframe]]=Field(default_factory=dict)
    props_tracks:dict[str,list[AnimationKeyframe]]=Field(default_factory=dict)
    color_tracks:dict[str,list[AnimationColorKeyframe]]=Field(default_factory=dict)

class AnimationCamera(Strict):
    x:float=Field(default=0.5,ge=-4,le=4)
    y:float=Field(default=0.5,ge=-4,le=4)
    zoom:float=Field(default=1,gt=0,le=8)
    rotation:float=Field(default=0,ge=-10000,le=10000)
    tracks:dict[str,list[AnimationKeyframe]]=Field(default_factory=dict)

class AnimationTransition(Strict):
    type:Literal['cut','crossfade','wipe','iris','slide','glitch']='cut'
    duration:float=Field(default=0.5,ge=0.01,le=4)

class AnimationPainterly(Strict):
    boil:float=Field(default=8,ge=0,le=24)
    stroke_scale:float=Field(default=1,ge=.25,le=3)
    flow:float=Field(default=1,ge=0,le=3)
    smear:tuple[float,float]=(0,0)
    grain:float=Field(default=.08,ge=0,le=.25)
    vignette:float=Field(default=.55,ge=0,le=1)
    bloom:float=Field(default=1.2,ge=0,le=3)

    @model_validator(mode='after')
    def bounded_smear(self):
        if any(not math.isfinite(x) or abs(x)>120 for x in self.smear):raise ValueError('Painterly smear must be finite and within -120..120')
        return self

class AnimationScene(Strict):
    id:str=Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    duration:float=Field(ge=0.25,le=120)
    style:Style|None=None
    background:str|None=None
    pixel_size:int=Field(default=0,ge=0,le=32)
    painterly:AnimationPainterly|None=None
    camera:AnimationCamera=Field(default_factory=AnimationCamera)
    transition:AnimationTransition=Field(default_factory=AnimationTransition)
    layers:list[AnimationLayer]=Field(min_length=1,max_length=96)

class AnimationCaption(Strict):
    start:float=Field(ge=0,le=120)
    end:float=Field(gt=0,le=120)
    text:str=Field(min_length=1,max_length=240)

class AnimationAudio(Strict):
    id:str=Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    source:str|None=None
    start:float=Field(default=0,ge=0,le=120)
    gain:float=Field(default=1,ge=0,le=2)
    text:str|None=Field(default=None,max_length=4000)
    model_id:str|None=None
    voice_id:str|None=None

class AnimationSoundCue(Strict):
    time:float=Field(ge=0,le=120)
    type:Literal['click','whoosh','chime','impact']
    gain:float=Field(default=0.35,ge=0,le=1)

class AnimationSound(Strict):
    music:Literal['none','ambient','electro','lofi']='none'
    gain:float=Field(default=0.18,ge=0,le=0.5)
    cues:list[AnimationSoundCue]=Field(default_factory=list,max_length=100)

class AnimationComposition(Strict):
    version:Literal[1]=1
    title:str=Field(min_length=1,max_length=160)
    width:int=Field(default=1280,ge=256,le=1920)
    height:int=Field(default=720,ge=256,le=1920)
    fps:int=Field(default=24,ge=12,le=60)
    seed:int=Field(default=42,ge=0,le=2147483647)
    bpm:float=Field(default=110,ge=30,le=240)
    style:Style='studio'
    palette:dict[str,str]=Field(default_factory=dict,max_length=8)
    scenes:list[AnimationScene]=Field(min_length=1,max_length=40)
    captions:list[AnimationCaption]=Field(default_factory=list,max_length=200)
    audio:list[AnimationAudio]=Field(default_factory=list,max_length=30)
    sound:AnimationSound=Field(default_factory=AnimationSound)
    finishing:AnimationFinishing=Field(default_factory=AnimationFinishing)
    fonts:list[AnimationFont]=Field(default_factory=list,max_length=4)

    @property
    def duration(self):return sum(scene.duration for scene in self.scenes)

    @model_validator(mode='after')
    def coherent(self):
        from .animation.catalog import validate_props,valid_color,SCHEMAS
        if self.width%2 or self.height%2:raise ValueError('Video dimensions must be even')
        if self.width*self.height>1920*1080:raise ValueError('Render at most 1920×1080 pixels or its portrait equivalent')
        if self.duration>120 or math.ceil(self.duration*self.fps)>7200:raise ValueError('Composition exceeds the 120-second/7200-frame limit')
        if len({scene.id for scene in self.scenes})!=len(self.scenes):raise ValueError('Scene IDs must be unique')
        font_ids=[font.id for font in self.fonts]
        builtins={'display','body','mono','serif','condensed','rounded'}
        if len(set(font_ids))!=len(font_ids) or any(name in builtins for name in font_ids):raise ValueError('Custom font IDs must be unique and not shadow built-in font roles')
        for key,color in self.palette.items():
            if key not in ('background','ink','accent','secondary','muted','paper','line','glow') or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Palette uses known roles with six-digit hex colors')
        mosaic_ids=set();count=0;scene_nodes=0;fluid_count=0;instances=0;brush_strokes=0;texture_variants=set();fiber_count=0
        for scene in self.scenes:
            if not scene.painterly and any(layer.paint_pass=='light' for layer in scene.layers):raise ValueError('Light paint passes require a painterly scene')
            if scene.transition.type!='cut' and scene.transition.duration>scene.duration:raise ValueError('Transition duration must fit its incoming scene')
            if scene.background and not valid_color(scene.background):raise ValueError('Invalid scene background color')
            if len({layer.id for layer in scene.layers})!=len(scene.layers):raise ValueError('Layer IDs must be unique within each scene')
            check_tracks(scene.camera.tracks,scene.duration,{'x','y','zoom','rotation'})
            by_id={layer.id:layer for layer in scene.layers}
            for layer in scene.layers:
                count+=1
                duration=layer.duration or scene.duration-layer.start
                if duration<=0 or layer.start+duration>scene.duration+1e-7:raise ValueError('Layer timing must fit its scene')
                validate_props(layer.component,layer.props)
                if layer.component=='mosaic_scene':
                    if layer.id in mosaic_ids:raise ValueError('Mosaic layer IDs must be unique across the film')
                    mosaic_ids.add(layer.id)
                    if len(mosaic_ids)>2:raise ValueError('Use at most two mosaic scenes per composition')
                if layer.component=='brush':
                    brush_strokes+=len(layer.props['strokes'])
                    if brush_strokes>512:raise ValueError('Composition exceeds 512 brush strokes')
                    for stroke in layer.props['strokes']:
                        if stroke.get('start',0)+stroke.get('duration',1)>duration+1e-7:raise ValueError('Brush stroke timing must fit its layer')
                if layer.component=='fluid':
                    fluid_count+=1
                    if fluid_count>4 or duration>30:raise ValueError('Use at most four fluid layers, each at most 30 seconds')
                    if any(e.get('start',0)>=duration or e.get('end',duration)>duration for e in layer.props['emitters']):raise ValueError('Fluid emitter timing must fit its layer')
                if layer.component=='scene3d':
                    from .animation.rigs import expand_presets
                    scene_nodes+=len(expand_presets(layer.props['nodes']))
                    texture_variants.update((node.get('texture'),node.get('texture_scale',5)) for node in expand_presets(layer.props['nodes']) if node.get('texture','none')!='none')
                    if len(texture_variants)>32:raise ValueError('Use at most 32 procedural texture variants per composition')
                    fiber_count+=sum(node.get('fibers',{}).get('count',0) for node in expand_presets(layer.props['nodes']))
                    if fiber_count>64000:raise ValueError('Composition exceeds 64000 surface fibers')
                    instances+=sum(node.get('repeat',{}).get('count',0) for node in layer.props['nodes'])
                    if instances>16384:raise ValueError('Composition exceeds 16384 instanced 3D parts')
                    if scene_nodes>1536:raise ValueError('Composition exceeds the 1536-node 3D budget')
                    for target in [*layer.props['nodes'],layer.props.get('camera',{})]:
                        if any(frames[-1]['time']>duration for frames in [*target.get('tracks',{}).values(),*target.get('color_tracks',{}).values()]):raise ValueError('3D tracks must fit the layer duration')
                if layer.component=='text' and layer.props.get('font','display') not in builtins|set(font_ids):raise ValueError('Text font must be a built-in role or an attached font ID')
                check_tracks(layer.tracks,duration,{'x','y','scale','scale_x','scale_y','skew_x','skew_y','blur','rotation','opacity','reveal','phase','spread','amount','rotation_x','rotation_y','rotation_z','mask_reveal','trim_start','trim_end'})
                parameters=SCHEMAS[layer.component]['properties']
                numeric={key for key,schema in parameters.items() if schema.get('type')=='number'}
                if layer.component=='mosaic_scene':numeric.discard('fish_scale')
                check_tracks(layer.props_tracks,duration,numeric)
                for key,frames in layer.props_tracks.items():
                    schema=parameters[key]
                    if any(frame.value<schema.get('minimum',-10000) or frame.value>schema.get('maximum',10000) for frame in frames):raise ValueError('Animated component values must fit their parameter bounds')
                for key,frames in layer.color_tracks.items():
                    if parameters.get(key,{}).get('pattern')!=SCHEMAS['shape']['properties']['fill']['pattern']:raise ValueError('Color tracks target a documented component color property')
                    times=[frame.time for frame in frames]
                    if not 1<=len(frames)<=100 or times!=sorted(set(times)) or times[-1]>duration or any(not valid_color(frame.value) for frame in frames):raise ValueError('Color keyframes require ordered local times and valid colors')
                colors=(layer.paint.colors if layer.paint else [])+([layer.shadow.color] if layer.shadow else [])
                if any(not valid_color(color) for color in colors):raise ValueError('Paint and shadow colors use palette roles or six-digit hex')
                ancestor=layer;visited={layer.id}
                while ancestor.parent:
                    if ancestor.parent not in by_id or by_id[ancestor.parent].component!='group':raise ValueError('Parent must identify a group in the same scene')
                    ancestor=by_id[ancestor.parent]
                    if ancestor.id in visited or len(visited)>8:raise ValueError('Groups must be acyclic and at most eight levels deep')
                    visited.add(ancestor.id)
        if count>512:raise ValueError('Composition exceeds 512 total layers')
        if len(json.dumps(self.model_dump(),ensure_ascii=False).encode('utf-8'))>5_000_000:raise ValueError('Composition exceeds the five-megabyte data limit')
        for cue in self.captions:
            if cue.end<=cue.start or cue.end>self.duration+1e-7:raise ValueError('Caption timing must fit the composition')
        captions=sorted(self.captions,key=lambda cue:cue.start)
        if any(a.end>b.start for a,b in zip(captions,captions[1:])):raise ValueError('Caption cues must not overlap')
        if len({track.id for track in self.audio})!=len(self.audio):raise ValueError('Audio track IDs must be unique')
        for track in self.audio:
            if track.start>=self.duration:raise ValueError('Audio begins after the composition ends')
        if any(cue.time>=self.duration for cue in self.sound.cues):raise ValueError('Sound cue begins after the composition ends')
        return self

def check_tracks(tracks,duration,allowed):
    for name,frames in tracks.items():
        if name not in allowed or not 1<=len(frames)<=100:raise ValueError('Unsupported track property or keyframe count')
        times=[frame.time for frame in frames]
        if times!=sorted(set(times)) or times[-1]>duration+1e-7:raise ValueError('Keyframe times must be increasing and fit their layer or camera')
        if any(frame.interpolation in ('log','monotone_log') for frame in frames) and any(frame.value<=0 for frame in frames):raise ValueError('Logarithmic tracks require positive values')
        if name in ('opacity','reveal','mask_reveal','trim_start','trim_end') and any(not 0<=frame.value<=1 for frame in frames):raise ValueError('Opacity/reveal/trim tracks use values from zero to one')
        if name=='zoom' and any(not 0<frame.value<=8 for frame in frames):raise ValueError('Camera zoom must be positive and at most eight')
        if name=='scale' and any(not 0<=frame.value<=10 for frame in frames):raise ValueError('Layer scale must be between zero and ten')
        if name in ('scale_x','scale_y') and any(not -10<=frame.value<=10 for frame in frames):raise ValueError('Axis scale must be between minus ten and ten')
        if name in ('skew_x','skew_y') and any(not -75<=frame.value<=75 for frame in frames):raise ValueError('Layer skew must be within 75 degrees')
        if name=='blur' and any(not 0<=frame.value<=.15 for frame in frames):raise ValueError('Layer blur is a stage-height fraction from zero to 0.15')

class AnimationReviewCrop(Strict):
    x:float=Field(ge=0,le=1)
    y:float=Field(ge=0,le=1)
    width:float=Field(gt=0,le=1)
    height:float=Field(gt=0,le=1)
    @model_validator(mode='after')
    def inside(self):
        if self.x+self.width>1 or self.y+self.height>1:raise ValueError('Review crop must fit the stage')
        return self

class AnimationRenderRequest(Strict):
    composition:AnimationComposition
    session_id:str|None=Field(default=None,max_length=120,pattern=r'^[a-zA-Z0-9_-]+$')
    preview_only:bool=False
    quality:Literal['draft','standard','final']='standard'
    review_times:list[float]=Field(default_factory=list,max_length=24)
    review_crop:AnimationReviewCrop|None=None
    @model_validator(mode='after')
    def review_inside(self):
        if any(not 0<=time<self.composition.duration for time in self.review_times):raise ValueError('Review times must be finite and inside the film')
        return self

class AnimationValidation(Strict):
    valid:bool=True
    duration:float
    frames:int
    warnings:list[str]
    component_counts:dict[str,int]
