"""Parameters are data-only; agents compose existing render components."""
from __future__ import annotations
import re
import math
from jsonschema import Draft202012Validator
from .schema_helpers import F,C,B,enum,schema

PALETTES={
 'studio':{'background':'#f5f4ef','ink':'#121826','accent':'#3059eb','secondary':'#ff795c','muted':'#8893a5','paper':'#ffffff','line':'#c8ced9','glow':'#9faeff'},
 'paper':{'background':'#f2dfbc','ink':'#293744','accent':'#dc7151','secondary':'#3f8e86','muted':'#b09473','paper':'#fff2d5','line':'#705c45','glow':'#ffd791'},
 'ink':{'background':'#eee9df','ink':'#303630','accent':'#b84334','secondary':'#6f8273','muted':'#aeaea0','paper':'#f7f2e6','line':'#62685d','glow':'#dfc7a6'},
 'neon':{'background':'#080d22','ink':'#ecf2ff','accent':'#29ddfa','secondary':'#e658b8','muted':'#555e91','paper':'#162047','line':'#394371','glow':'#8a69ff'},
 'punk':{'background':'#e8e2d3','ink':'#17151b','accent':'#f53983','secondary':'#12a8ba','muted':'#77716c','paper':'#f9f3e5','line':'#38323c','glow':'#f4c94e'},
 'pixel':{'background':'#111b36','ink':'#d9e8ff','accent':'#efa649','secondary':'#65abb5','muted':'#495372','paper':'#293650','line':'#3b4963','glow':'#c474a9'},
 'mosaic':{'background':'#152b36','ink':'#eddcc2','accent':'#de8c49','secondary':'#55b4b1','muted':'#687c7a','paper':'#e5cda4','line':'#18292e','glow':'#dbc16e'},
 'blueprint':{'background':'#0b2d49','ink':'#e4f1ef','accent':'#70d8d1','secondary':'#f5bc65','muted':'#7999ad','paper':'#153c5c','line':'#426c86','glow':'#81cbf0'},
}
S={'type':'string','maxLength':500}
N={'type':'number','minimum':-10,'maximum':10}
I={'type':'integer','minimum':1,'maximum':600}
FONT={'type':'string','maxLength':48,'pattern':r'^[a-zA-Z][a-zA-Z0-9_-]+$'}
POINT={'type':'array','items':N,'minItems':2,'maxItems':2}
COMPONENTS={
 'text':('Fit and track typography; stagger lines, words or letters with clipped rise, rotation, scale and blur. Font roles: display/body/mono/serif/condensed/rounded, or an attached font ID.',{'text':S,'size':F,'font':FONT,'weight':{'type':'integer','minimum':100,'maximum':900},'color':C,'align':enum('left','center','right'),'mode':enum('plain','lines','words','letters','outline'),'line_height':{'type':'number','minimum':0.8,'maximum':2},'tracking':N,'stagger':{'type':'number','minimum':0,'maximum':1},'effect':enum('rise','rotate','scale','blur'),'travel':F,'duration':{'type':'number','minimum':.05,'maximum':4},'overshoot':B,'clip':B}),
 'shape':('Procedural shape with matched-point morphs, outline and reveal.',{'kind':enum('circle','rect','triangle','star','blob','ring'),'to':enum('circle','rect','triangle','star','blob','ring'),'fill':C,'stroke':C,'line_width':F,'corners':F,'points':{'type':'integer','minimum':3,'maximum':24},'inner':F}),
 'path':('Arc-length trimmed smooth spline, draw-on line or path-following marker.',{'points':{'type':'array','items':POINT,'minItems':2,'maxItems':100},'color':C,'line_width':F,'closed':B,'fill':C,'marker':B,'marker_size':F,'dash':B,'curve':enum('linear','smooth'),'trim_start':F,'trim_end':F}),
 'particles':('Seeded formations morph among sphere, torus, wave, burst and helix.',{'count':I,'pattern':enum('sphere','torus','wave','burst','helix','grid'),'to':enum('sphere','torus','wave','burst','helix','grid'),'color':C,'size':F,'speed':N,'links':B,'depth':F}),
 'grid':('Dots, lines, perspective floor or halftone field.',{'kind':enum('dots','lines','perspective','halftone'),'spacing':{'type':'number','minimum':0.015,'maximum':0.3},'color':C,'size':F,'speed':N}),
 'chart':('Animated bars or line series with semantic labels.',{'values':{'type':'array','items':{'type':'number','minimum':0,'maximum':1000000},'minItems':2,'maxItems':24},'labels':{'type':'array','items':{'type':'string','maxLength':40},'maxItems':24},'kind':enum('bar','line'),'color':C,'show_values':B}),
 'diagram':('Nodes and directed links with moving flow pulses.',{'nodes':{'type':'array','maxItems':24,'items':schema({'id':S,'label':{'type':'string','maxLength':80},'x':N,'y':N},('id','label','x','y'))},'edges':{'type':'array','maxItems':48,'items':{'type':'array','items':S,'minItems':2,'maxItems':2}},'color':C,'active':{'type':'integer','minimum':-1,'maximum':23}}),
 'interface':('Reusable browser, phone, card, toggle, cursor and dashboard modules.',{'kind':enum('browser','phone','card','toggle','cursor','dashboard'),'title':S,'subtitle':S,'items':{'type':'array','items':{'type':'string','maxLength':100},'maxItems':8},'color':C,'progress':F,'variant':enum('light','dark'),'value':{'type':'number','minimum':0,'maximum':10000000}}),
 'character':('Stable cutout rig with walk, dance, wave and idle motion; pose is time-driven.',{'action':enum('idle','walk','dance','wave','run'),'costume':enum('coat','hoodie','suit','astronaut'),'color':C,'skin':C,'facing':enum('left','right'),'speed':{'type':'number','minimum':0.1,'maximum':5},'prop':enum('none','lantern','umbrella','flag')}),
 'landscape':('Layered procedural hills, ink mountains, city, island and stage scenery.',{'kind':enum('hills','mountains','city','island','stage'),'layers':{'type':'integer','minimum':1,'maximum':8},'color':C,'sun':B,'windows':B,'speed':N,'detail':{'type':'integer','minimum':1,'maximum':12}}),
 'orbit':('Illustrative orbital paths, satellites, starfield and pendulum motion.',{'kind':enum('planetary','pendulum','cradle'),'count':{'type':'integer','minimum':1,'maximum':12},'color':C,'speed':N,'labels':{'type':'array','items':{'type':'string','maxLength':30},'maxItems':12}}),
 'cube':('Depth-sorted projected cubes, lattice and exploded assembly; Canvas 2.5D.',{'count':{'type':'integer','minimum':1,'maximum':5},'color':C,'wireframe':B,'speed':N,'explode':F}),
 'machine':('Illustrative turbine cross-section with rotating blades, airflow and explosion.',{'color':C,'explode':F,'speed':N,'labels':B}),
 'weather':('Seeded rain, drifting mist, smoke, stars and fireflies.',{'kind':enum('rain','mist','smoke','stars','fireflies'),'count':I,'color':C,'speed':N,'size':F}),
 'image':('Explicit local raster asset with contain/cover; no external fetching or generation.',{'source':{'type':'string','maxLength':1000},'fit':enum('contain','cover'),'radius':F}),
 'group':('Parent transform, clipping and inherited opacity for an authored assembly. Children use group-relative coordinates.',{}),
 'fluid':('Bounded CPU dye/velocity simulation with semi-Lagrangian transport and a pressure projection. Fixed 30 Hz steps and immutable checkpoints reproduce backward seeks. Art-directed ink/smoke, not a scientific solver.',{'resolution':enum('low','medium','high'),'mask':enum('none','mountains','circle'),'emitters':{'type':'array','minItems':1,'maxItems':8,'items':schema({'x':F,'y':F,'color':C,'start':{'type':'number','minimum':0,'maximum':120},'end':{'type':'number','minimum':0,'maximum':120},'radius':{'type':'number','minimum':.01,'maximum':.2},'strength':{'type':'number','minimum':.01,'maximum':3},'direction':{'type':'number','minimum':-360,'maximum':360},'wander':{'type':'number','minimum':0,'maximum':.2}},('x','y','color'))}}),
 'tiles':('Thousands of seeded glass or gold tiles form an intact fish, bird or moon. Lift, swim, flip and return motions are analytic; phase controls release, travel_x/y position the figure and wave controls body motion.',{'columns':{'type':'integer','minimum':8,'maximum':100},'rows':{'type':'integer','minimum':8,'maximum':80},'formation':enum('fish','bird','moon','circle'),'material':enum('glass','gold','paper'),'color':C,'background_color':C,'travel_x':{'type':'number','minimum':-1,'maximum':1},'travel_y':{'type':'number','minimum':-1,'maximum':1},'wave':{'type':'number','minimum':0,'maximum':.12},'speed':N,'flip':F,'gap':{'type':'number','minimum':.03,'maximum':.4},'flutter':{'type':'number','minimum':0,'maximum':.08}}),
 'vector':('Authored SVG path artwork with independent fills and strokes; no scripts, SVG documents or external resources.',{'view_box':{'type':'array','items':{'type':'number','minimum':-10000,'maximum':10000},'minItems':4,'maxItems':4},'paths':{'type':'array','minItems':1,'maxItems':80,'items':schema({'d':{'type':'string','maxLength':12000,'pattern':r'^[MmLlHhVvCcSsQqTtAaZz0-9eE+.,\s-]+$'},'fill':C,'stroke':C,'width':{'type':'number','minimum':0,'maximum':200},'opacity':F},('d',))}}),
 'mesh':('Solid parametric 3D geometry with depth buffering, interpolated normals, material lighting and optional reflection. WebGL surfaces use software rendering during export; a reported faceted Canvas fallback is available.',{'kind':enum('sphere','torus','knot','ribbon','superquadric'),'to':enum('sphere','torus','knot','ribbon','superquadric'),'material':enum('matte','metal','ceramic'),'color':C,'segments':{'type':'integer','minimum':12,'maximum':96},'rings':{'type':'integer','minimum':6,'maximum':32},'rotation_x':{'type':'number','minimum':-10000,'maximum':10000},'rotation_y':{'type':'number','minimum':-10000,'maximum':10000},'rotation_z':{'type':'number','minimum':-10000,'maximum':10000},'speed':N,'tube':{'type':'number','minimum':.05,'maximum':.6},'twist':{'type':'number','minimum':-8,'maximum':8},'light_x':N,'light_y':N,'light_z':N,'ambient':F,'roughness':{'type':'number','minimum':.05,'maximum':1},'shadow':B,'reflection':F,'wireframe':B,'perspective':{'type':'number','minimum':2,'maximum':8}}),
}
from .scene3d_schema import PROPS as SCENE3D_PROPS,validate_scene
COMPONENTS['tiles'][1].update(light_phase=N,night_color=C)
COMPONENTS['tiles'][1]['source']={'type':'string','maxLength':1000}
COMPONENTS['vector'][1]['texture']=enum('none','paper','ink','mosaic')
COMPONENTS['vector'][1].update(tile_size={'type':'number','minimum':.008,'maximum':.08},tile_gap={'type':'number','minimum':.04,'maximum':.3},tile_flow=enum('grid','radial','arch'),tile_origin={'type':'array','items':F,'minItems':2,'maxItems':2},tile_grout=C,tile_relief=F,tile_variation=F)
COMPONENTS['vector'][1].update(tile_assembly=F,tile_scatter={'type':'number','minimum':0,'maximum':2})
COMPONENTS['vector'][1]['tile_outlines']=B
COMPONENTS['vector'][1]['tile_reveal']=enum('random','center','left','right')
COMPONENTS['brush']=('Pressure-shaped pigment strokes with granular edges and progressive deposition. Points are layer fractions [x,y,pressure]; width is a layer-height fraction. Ink, wash and dry media are deterministic and independently timed.',{'grain':F,'strokes':{'type':'array','minItems':1,'maxItems':256,'items':schema({'points':{'type':'array','minItems':2,'maxItems':80,'items':{'type':'array','minItems':3,'maxItems':3,'prefixItems':[{'type':'number','minimum':-.2,'maximum':1.2},{'type':'number','minimum':-.2,'maximum':1.2},{'type':'number','minimum':.01,'maximum':2}],'items':False}},'width':{'type':'number','minimum':.0005,'maximum':.35},'color':C,'opacity':F,'start':{'type':'number','minimum':0,'maximum':120},'duration':{'type':'number','minimum':.01,'maximum':120},'style':enum('ink','wash','dry'),'seed':{'type':'integer','minimum':0,'maximum':1000000}},('points','width','color'))}})
COMPONENTS['vector'][1]['fit']=enum('contain','stretch')
COMPONENTS['fluid'][1]['pre_roll']={'type':'integer','minimum':0,'maximum':6}
COMPONENTS['image'][1].update(pixelated=B,frames={'type':'integer','minimum':1,'maximum':128},columns={'type':'integer','minimum':1,'maximum':64},frame_rate={'type':'number','minimum':.1,'maximum':60},loop=B)
COMPONENTS['text'][1]['direction']=enum('ltr','rtl','auto')
COMPONENTS['scene3d']=('Connected 3D scene graph with physically based materials, shared lighting, shadows and a tracked perspective camera. World units, Euler degrees, layer-local keyframes. No executable source.',SCENE3D_PROPS)
from .mosaic_scene import PROPS as MOSAIC_PROPS
COMPONENTS['mosaic_scene']=('Contour-tiled aquarium scene from the supplied finished film. Editable palette, fish profile, spine performance, camera, path and acting channels. Native world 1280x720 and timeline 0..15 seconds. This is a scene family, not an arbitrary-character generator. Layer duration retimes the whole film; playhead overrides source time. Numeric acting multipliers support props_tracks. Preserve default path for bowl contact; custom paths require visual review.',MOSAIC_PROPS)
REQUIRED={'text':('text',),'path':('points',),'brush':('strokes',),'chart':('values',),'diagram':('nodes','edges'),'image':('source',),'vector':('view_box','paths'),'scene3d':('nodes',),'fluid':('emitters',)}
SCHEMAS={key:schema(value[1],REQUIRED.get(key,())) for key,value in COMPONENTS.items()}
def valid_color(value):return isinstance(value,str) and re.fullmatch(C['pattern'],value) is not None
def validate_props(component,props):
    def finite(value):
        if isinstance(value,float) and not math.isfinite(value):raise ValueError('Animation parameters must contain finite numbers')
        if isinstance(value,dict):
            for item in value.values():finite(item)
        if isinstance(value,list):
            for item in value:finite(item)
    finite(props)
    errors=list(Draft202012Validator(SCHEMAS[component]).iter_errors(props))
    if errors:raise ValueError(component+' parameters: '+errors[0].message[:500])
    if component=='scene3d':validate_scene(props)
    if component=='mosaic_scene':
        from .mosaic_scene import validate
        validate(props)
    if component=='fluid' and any(e.get('end',120)<=e.get('start',0) for e in props['emitters']):raise ValueError('Fluid emitter end must follow its start')
    if component=='text' and props.get('mode')=='letters' and re.search(r'[\u0600-\u08ff\u0900-\u0dff]',props['text']):raise ValueError('Joined-script text must use plain, lines or whole-word animation to preserve shaping')
    if component=='shape' and props.get('to') and ('ring' in (props.get('kind'),props.get('to'))):raise ValueError('Rings support draw-on reveal rather than solid-shape morphs')
    if component=='vector':
        if min(props['view_box'][2:])<=0:raise ValueError('Vector view box width and height must be positive')
        if sum(len(path['d']) for path in props['paths'])>64000:raise ValueError('Vector artwork exceeds the 64,000-character path budget')
        for path in props['paths']:validate_path(path['d'])
    if component=='diagram':
        ids=[node['id'] for node in props['nodes']]
        if len(ids)!=len(set(ids)) or any(node not in ids for edge in props['edges'] for node in edge):raise ValueError('Diagram edges must refer to unique existing nodes')
    if component=='chart' and props.get('labels') and len(props['labels'])!=len(props['values']):raise ValueError('Chart labels must match the value count')
    if component=='weather' and props.get('kind') in ('mist','smoke') and props.get('count',20)>40:raise ValueError('Use at most 40 blurred mist or smoke particles')
def validate_path(path):
    pattern=r'[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
    if re.sub(pattern,'',path).strip(' ,\t\r\n'):raise ValueError('Invalid vector path token')
    tokens=re.findall(pattern,path)
    if not tokens or tokens[0] not in ('M','m'):raise ValueError('A vector path must begin with a move command')
    index=0;arity={'M':2,'L':2,'H':1,'V':1,'C':6,'S':4,'Q':4,'T':2,'A':7,'Z':0}
    while index<len(tokens):
        command=tokens[index].upper()
        if command not in arity:raise ValueError('Invalid vector path command')
        index+=1;values=[]
        while index<len(tokens) and tokens[index].upper() not in arity:
            value=float(tokens[index])
            if not math.isfinite(value) or abs(value)>100000:raise ValueError('Vector coordinates must be finite and within 100,000 view-box units')
            values.append(value);index+=1
        size=arity[command]
        if (not size and values) or (size and (not values or len(values)%size)):raise ValueError('Vector path command has an incomplete parameter group')
        if command=='A' and any(values[i]<0 or values[i+1]<0 or values[i+3] not in (0,1) or values[i+4] not in (0,1) for i in range(0,len(values),7)):raise ValueError('Arc radii must be nonnegative and arc flags must be zero or one')

def catalog():
    from ..schemas_animation import AnimationComposition
    from .recipes import recipe_listing
    value={'version':3,'styles':PALETTES,'components':{key:{'description':value[0],'parameters':SCHEMAS[key]} for key,value in COMPONENTS.items()},'schema':AnimationComposition.model_json_schema(),'recipes':recipe_listing(),
            'directing_controls':{'hierarchy':'Parent groups share transforms, masks and opacity. Child x/y and size use fractions of the parent box. Anchor fractions select a rotation/scale pivot.','typography':'Use mode:lines for clipped line reveals, or letters/words with stagger, effect, duration, travel and overshoot. Tracking is a stage-height fraction for plain/line modes. Attach local fonts when needed.','materials':'Mesh Euler rotation tracks use degrees; speed adds radians per second about Y. Roughness and ambient are zero-to-one controls; light_x/y/z set one light direction. Geometry morphs use phase.','parameter_animation':'props_tracks animate documented number parameters within their schema bounds. color_tracks animate documented color properties using palette roles or hex values. All keyframe times are layer-local.','paths':'Smooth paths use arc-length trimming; trim_start/end range from zero to one. SVG vector paths support standard commands with bounded finite coordinates.','finishing':'Use grain/vignette gently. Motion blur uses a shutter fraction of one frame and 1–6 deterministic samples. Export quality:final uses PNG intermediate frames and CRF 16.'},
            'workflow':['Choose a visual treatment and a few readable story beats.','Use animation_recipe for a ready composition or compose the documented components as JSON.','Validate timing and content before rendering.','Render preview/contact sheet; inspect and revise the composition.','Export exact frames to MP4. Prepare voice only when explicitly requested; attach timed audio or captions to the composition.'],
            'coordinates':'Layer position and size are fractions of the stage; text size is a fraction of stage height. Scenes run sequentially. Layer and camera keyframe times are local seconds. No JavaScript source, external network assets or generation models are needed.'}
    value['directing_controls'].update(scene3d='Nodes form a shared world-unit hierarchy with PBR materials and shadows. Perspective camera and joint tracks use layer-local seconds and Euler degrees. Preset nodes provide mascot idle/wave/look, paper_bird idle/flight and town idle; edit root tracks or use expanded recipe data for individual joints. Model nodes require a scoped self-contained GLB; clip selects an existing named animation.',continuous_motion='Set destination keyframe interpolation:monotone to pass smoothly through interior keys, or monotone_log for positive scales/zoom. Eased tracks retain per-segment ease. Log modes reject zero/negative values.',formations='tiles phase releases a stable figure; travel_x/y move it without losing its formation. Return phase to zero to restore its cells. Explicit light_phase and matching first/last tracks permit loop design.',review='Inspect the storyboard, full-resolution face/joint/type crops, cut boundaries and actual encoded video. A valid render is not proof of visual parity. Direct actions and consequences; avoid repeating one gesture across all shots.',audio='Use animation_analyze_audio for measured energy hits and quiet gaps. Its tempo estimate is uncertain and it does not transcribe or align words.')
    value['directing_controls'].update(pigment='brush strokes use normalized [x,y,pressure] points, layer-height width and independent start/duration. Washes taper pigment into paper; ink/dry preserve granular edges. Compose multiple layers rather than painting every mark at once.',mosaic_art='Set vector texture:mosaic for authored tile artwork. tile_flow:radial follows curved bands; grid uses staggered cells. tile_size is relative to the layer minimum dimension, so small objects need a larger fraction to keep tile sizes coherent. Explicit tiled artwork bypasses the legacy whole-frame mosaic filter.',character_detail='Attach eye highlights to the animated eye, cuffs to the arm joint, and clothing to the actor hierarchy. Set texture_scale and bump_strength deliberately. glow adds a bounded additive halo to an emissive mesh. Review contact and blink frames, not just open-eyed poses.')
    value['directing_controls']['surface_fibers']='Sphere nodes accept fibers:{count,length,thickness?,seed?}. Use short tufts for a soft silhouette, then inspect the face at full resolution. Node scaling forms ellipsoids. Fibers inherit transforms and color tracks; they are not simulated hair. Keep within 8000 per node, 16000 per layer and 64000 per composition.'
    value['directing_controls']['tile_assembly']='For vector texture:mosaic, animate tile_assembly from 0 to 1 to assemble individual tesserae; reverse it to disperse. tile_scatter sets travel in layer dimensions. Use fit:stretch for rectangular wall or border art on portrait stages, and contain for circular artwork. Full assembly is cached; intermediate states render each tile.'
    value['directing_controls']['tessera_art_direction']='Use tile_grout for an opaque silhouette, tile_origin for radial or arch courses, tile_relief for glaze, tile_variation for brightness and tile_outlines for filled-path contours. tile_reveal selects random, center, left or right assembly. Negative scale_x/scale_y mirrors a rig without redrawing artwork. The goldfish recipe exposes world, fish, tail, dorsal, day, night, bowl and constellation groups; edit those controls instead of authoring thousands of tile paths.'
    value['directing_controls']['painterly']='Set scene.painterly:{} to repaint ordinary scene components with the Functional Emotions brushstroke renderer (MIT). Three instanced stroke sizes follow underpainting edges, with timed boil and separate additive light. Controls: stroke_scale .25–3, boil 0–24 Hz, flow 0–3, smear [x,y] -120..120, bloom 0–3, grain 0–.25, vignette 0–1. Use layer.paint_pass:light for glow artwork on black; base is the default. Captions stay sharp. Requires WebGL2; no silent substitution. Start with painted-lake and edit its named layers. A renderer supplies surface treatment, not story or drawing quality.'
    return value
