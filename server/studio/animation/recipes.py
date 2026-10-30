"""Original composition recipes built from reusable scene components."""
from __future__ import annotations
import copy
from ..schemas_animation import AnimationComposition

RECIPES={
 'painted-lake':('A light across the water','An editable moonlit lake, boat and lantern using the source-derived GPU brushstroke renderer and a separate light pass.'),
 'ink-reference-study':('Mountain and water','A 39.2-second recreation study of the observed ink-landscape sequence, using timed pressure strokes and a held composition.'),
 'mosaic-reference-study':('Goldfish window','An 80-second goldfish study: directional tile assembly, day/night architecture, a glass bowl, articulated swimming and jumping, and a constellation ending.'),
 'night-bloom':('The midnight conservatory','A layered paper flower opens beneath a visiting moth; connected petal and wing joints carry one continuous camera move.'),
 'field-form':('Pressure, pattern, form','A graphic film moves from pressure strokes to assembling tesserae to an instanced paper sculpture.'),
 'smallest-light':('The smallest light','A clothed miniature character notices a firefly, raises a hand for it and waves it into the night across three camera shots.'),
 'brush-landscape':('After the rain','Pressure-shaped pigment paints layered mountain ridges, dry-brush pines and quiet water before a vermilion sun appears.'),
 'moonlit-mosaic':('The moon keeps watch','A detailed tiled window, circular glass bowl, articulated goldfish and foreground reeds compose a nocturnal miniature.'),
 'electric-edit':('Change the rhythm','A bold punk graphic edit with clipped typography, instanced metal forms, sweeping curves and beat cuts.'),
 'paper-medallion':('Room to unfold','336 instanced paper pieces form a layered rosette, release outward, turn, and assemble again under shared studio light.'),
 'turbofan-study':('Inside a turbofan','A full engine, hollow cutaway, flowing air paths and separately rotating stages beneath an illustrated aircraft wing.'),
 'flowing-ink':('The shape of quiet','A bounded dye simulation spreads ink through a masked mountain field with a vermilion sun and a held close.'),
 'paper-window':('A small idea','An illustrated girl folds a note into a plane; a night flight returns as a star-bearing letter.'),
 'living-mosaic':('Nothing stays still','An intact glass-tile fish lifts, swims, returns to its original cells and flips the wall into night.'),
 'paper-flight':('Fold a little courage','An authored paper bird with wing joints flies through a layered miniature town and into the night.'),
 'little-companion':('A little company','A jointed original mascot with shared studio lighting, waving choreography and camera cuts.'),
 'precision-assembly':('Made to move','A connected metal rotor assembly with independently rotating stages and an exploded camera study.'),
 'contour':('Contour','Material-lit parametric sculptures, clipped typography and a coordinated shape study.'),
 'small-seasons':('Small seasons','Authored vector botanical artwork with grouped growth, pivoted petals and tactile finishing.'),
 'ribbon-study':('A continuous thought','Smooth arc-length paths, traveling trims and typographic choreography.'),
 'kinetic':('Make room for wonder','A brisk typography and shape reel with follow-through and a particle finale.'),
 'paper-story':('The last lantern','A paper city, a stable walking cutout and a small light that changes the night.'),
 'product':('Nightshift','A quiet product opening, a focused interface demo and an organized dashboard.'),
 'science':('A tiny collision','Converging signals, detector rings and a seeded burst rendered as an illustration.'),
 'ink-landscape':('Cloud crossing','Layered ink mountains paint onto paper, followed by a vermilion sun and drifting mist.'),
 'pixel-city':('Rain on circuit street','A loopable pixel-inspired street with rain, lit windows and warm reflections.'),
 'mosaic':('Midnight aquarium','Tiled water, orbital fish and falling stars that assemble a night composition.'),
 'orbital':('Three small worlds','An illustrative orbital system with moving labels and a slow camera.'),
 'engineering':('Inside the engine','An illustrated turbine opens into its stages while airflow moves through it.'),
 'data-story':('A clearer signal','A source-to-result flow diagram followed by a growing comparative chart.'),
 'comic':('Special delivery','Panel transitions, a dancing courier and a large graphic burst.'),
 'punk-zine':('Stay curious','Scrappy typography, halftone fields, cutout movement and punchy beat cuts.'),
 'ui-morph':('One useful shape','A circle morphs into a card, then a toggle, dashboard and final mark.'),
 'cradle':('Pass it on','A restrained mechanics study using an illustrative Newton’s cradle.'),
 'risograph':('The blue hour','A grainy night city, framed stars and a slow firefly reveal.'),
}
RECIPES['contour-aquarium']=('A fish follows the light','Source-derived contour tesserae, articulated fish, refracted bowl and a day-to-night flip. Edit the mosaic_scene layer data.')

def recipe_listing():return [{'id':key,'title':value[0],'description':value[1]} for key,value in RECIPES.items()]
def layer(id,component,props=None,**kwargs):return {'id':id,'component':component,'props':props or {},**kwargs}
def text(id,value,**kwargs):
    props={'text':value,'size':kwargs.pop('size',.12),'font':kwargs.pop('font','display'),'color':kwargs.pop('color','$ink'),'mode':kwargs.pop('mode','plain'),'align':kwargs.pop('align','center')}
    for key in ('weight','direction','tracking','stagger','effect','line_height','clip','overshoot'):
        if key in kwargs:props[key]=kwargs.pop(key)
    props.update(kwargs.pop('props',{}))
    return layer(id,'text',props,**kwargs)
def keys(*values,ease='smooth'):return [{'time':time,'value':value,'ease':ease} for time,value in values]
def scene(id,duration,layers,**kwargs):return {'id':id,'duration':duration,'layers':layers,**kwargs}

def recipe(identifier, *, title=None, width=1280,height=720,fps=24,seed=42):
    if identifier not in RECIPES:raise ValueError('Unknown animation recipe')
    name=title or RECIPES[identifier][0]
    if identifier=='contour-aquarium':
        return AnimationComposition.model_validate(dict(title=name,width=width,height=height,fps=fps,seed=seed,scenes=[dict(id='aquarium',duration=15,layers=[dict(id='aquarium',component='mosaic_scene',width=1,height=1,props={})])]))
    if identifier=='painted-lake':
        from .painted_study import make
        return make(title=name,width=width,height=height,fps=fps,seed=seed)
    if identifier in ('ink-reference-study','mosaic-reference-study','night-bloom','field-form'):
        from .comparison_recipes import ink_reference,mosaic_reference,night_bloom,field_form
        return {'ink-reference-study':ink_reference,'mosaic-reference-study':mosaic_reference,'night-bloom':night_bloom,'field-form':field_form}[identifier](title=name,width=width,height=height,fps=fps,seed=seed)
    if identifier=='smallest-light':
        from .character_study import make
        return make(title=name,width=width,height=height,fps=fps,seed=seed)
    if identifier in ('brush-landscape','moonlit-mosaic'):
        from .pigment_recipes import ink,mosaic
        return (ink if identifier=='brush-landscape' else mosaic)(title=name,width=width,height=height,fps=fps,seed=seed)
    if identifier=='turbofan-study':
        from .engineering_recipes import make
        return make(title=name,width=width,height=height,fps=fps,seed=seed)
    if identifier=='paper-window':
        from .paper_recipes import make
        return make(title=name,width=width,height=height,fps=fps,seed=seed)
    if identifier in ('little-companion','precision-assembly','paper-flight','living-mosaic','flowing-ink','paper-medallion'):
        from .scene_recipes import make
        return make(identifier,title=name,width=width,height=height,fps=fps,seed=seed)
    if identifier in ('contour','small-seasons','ribbon-study','electric-edit'):
        from .quality_recipes import make
        return make(identifier,title=name,width=width,height=height,fps=fps,seed=seed)
    base={'version':1,'title':name,'width':width,'height':height,'fps':fps,'seed':seed,'bpm':110,'style':'studio','sound':{'music':'ambient','gain':.12,'cues':[]}}
    if identifier=='kinetic':
        base.update(bpm=120,sound={'music':'electro','gain':.16,'cues':[{'time':4,'type':'impact'},{'time':8,'type':'whoosh'},{'time':12,'type':'chime'}]})
        base['scenes']=[
          scene('anticipation',4,[layer('dots','grid',{'spacing':.06,'color':'$line'},opacity=.55,width=1,height=1),layer('ball','shape',{'kind':'circle','fill':'$accent'},width=.07,height=.125,tracks={'x':keys((0,.15),(.8,.15),(1.8,.5),(3.5,.5),ease='back_out'),'y':keys((0,.7),(1,.7),(2,.5),(3.5,.5)), 'scale':keys((0,1),(.8,.7),(1.3,1.2),(2,1))}),text('invitation','Make room',y=.32,size=.14,mode='words',start=1.3,enter='fade')]),
          scene('shape',4,[text('big-word','WONDER',y=.32,size=.21,mode='letters',enter='pop'),layer('form','shape',{'kind':'circle','to':'star','fill':'$secondary','points':7},y=.68,width=.24,height=.38,tracks={'phase':keys((0,0),(2.5,1))},motion={'type':'wiggle','amount':.06,'speed':.5})],background='$accent',transition={'type':'wipe','duration':.35}),
          scene('depth',4,[layer('floor','grid',{'kind':'perspective','color':'$muted'},width=1,height=.7,y=.65),layer('cloud','particles',{'pattern':'sphere','to':'torus','count':300,'size':.0035,'color':'$accent'},width=.7,height=.85,tracks={'phase':keys((0,0),(3,1))}),text('depth-copy','A little depth. A lot of possibility.',y=.87,size=.037,font='body',enter='fade')],style='neon',transition={'type':'iris','duration':.55}),
          scene('resolve',3,[text('end',name,size=.13,enter='slide_up',y=.45),text('sub','Make something worth watching.',size=.034,font='body',y=.64,enter='fade',start=.5)],transition={'type':'crossfade','duration':.6})]
    elif identifier=='risograph':
        base.update(style='paper',palette={'background':'#192746','ink':'#f2dfbc','accent':'#ef8468','secondary':'#6b91a4','paper':'#263c5e','muted':'#506780','glow':'#f0c980','line':'#7898ab'},sound={'music':'ambient','gain':.13,'cues':[{'time':6,'type':'chime'},{'time':11,'type':'whoosh'}]})
        frame=[layer('frame-top','shape',{'kind':'rect','fill':'$ink'},width=.88,height=.022,y=.11),layer('frame-bottom','shape',{'kind':'rect','fill':'$ink'},width=.88,height=.022,y=.86),layer('frame-left','shape',{'kind':'rect','fill':'$ink'},width=.013,height=.77,x=.06,y=.485),layer('frame-right','shape',{'kind':'rect','fill':'$ink'},width=.013,height=.77,x=.94,y=.485)]
        base['scenes']=[scene('window',6,[layer('hills','landscape',{'kind':'hills','layers':3,'speed':.006},width=.88,height=.76,y=.47),layer('moon','shape',{'fill':'$glow'},x=.72,y=.27,width=.085,height=.15,enter='fade',enter_duration=2),layer('stars','weather',{'kind':'stars','count':55,'color':'$ink'},width=.8,height=.54,y=.4),*copy.deepcopy(frame),text('title',name,y=.94,size=.038,font='serif',enter='fade')],camera={'tracks':{'zoom':keys((0,1),(6,1.025))}}),scene('constellation',5,[layer('dust','particles',{'pattern':'helix','count':170,'size':.002,'color':'$glow','speed':.15},width=.6,height=.66),layer('orbit','path',{'points':[[-.35,.1],[-.12,-.2],[.15,.05],[.34,-.18]],'color':'$ink','line_width':.002,'marker':True},width=.8,height=.5,enter='draw',enter_duration=3),*copy.deepcopy(frame),text('whisper','Some nights arrive quietly.',y=.94,size=.034,font='serif',enter='fade')],transition={'type':'crossfade','duration':.8}),scene('dawn',5,[layer('horizon','landscape',{'kind':'hills','layers':3,'speed':.004},width=1,height=1),layer('sunrise','shape',{'fill':'$accent'},width=.14,height=.25,tracks={'y':keys((0,.8),(5,.4))}),text('close','Stay for the light.',y=.23,size=.075,font='serif',enter='fade',start=.8)],transition={'type':'crossfade','duration':1})]
    elif identifier in ('paper-story','pixel-city'):
        base['style']={'paper-story':'paper','risograph':'paper','pixel-city':'pixel'}[identifier]
        base['sound']={'music':'lofi','gain':.12,'cues':[{'time':5,'type':'chime'}]}
        city=layer('city','landscape',{'kind':'city','layers':4,'windows':True,'sun':True},width=1,height=1)
        rain=layer('rain','weather',{'kind':'rain','count':140,'speed':.65},width=1,height=1)
        if identifier=='pixel-city':base['scenes']=[scene('street',12,[city,rain,text('street-title',name,y=.18,size=.065,font='mono',enter='fade'),layer('walker','character',{'action':'walk','costume':'coat','prop':'umbrella','color':'$accent'},width=.11,height=.3,y=.74,tracks={'x':keys((0,-.1),(12,1.1),ease='linear')})])]
        else:
            base['scenes']=[scene('night',5,[city,layer('stars','weather',{'kind':'stars','count':70,'color':'$ink'},width=1,height=.6,y=.3),text('opening',name,y=.2,size=.095,font='serif',enter='fade')]),scene('walk',6,[copy.deepcopy(city),layer('courier','character',{'action':'walk','costume':'coat','prop':'lantern','color':'$secondary'},width=.22,height=.56,y=.62,tracks={'x':keys((0,.18),(6,.68),ease='linear')}),text('story','One small light can change the way home.',y=.18,size=.043,font='serif',enter='fade')],transition={'type':'crossfade','duration':.65}),scene('light',5,[layer('hills','landscape',{'kind':'hills','layers':4,'sun':True},width=1,height=1),layer('lights','weather',{'kind':'fireflies','count':65,'color':'$glow','size':.003},width=.85,height=.6,enter='fade',enter_duration=2),text('ending','Keep a little light.',y=.24,size=.095,font='serif',enter='fade',start=.6)],style='neon',transition={'type':'iris','duration':.8})]
    elif identifier in ('product','ui-morph'):
        base['sound']={'music':'electro','gain':.1,'cues':[{'time':4,'type':'click'},{'time':9,'type':'whoosh'}]}
        if identifier=='ui-morph':
            base['scenes']=[scene('form',4,[layer('shape','shape',{'kind':'circle','to':'rect','fill':'$accent'},width=.22,height=.3,tracks={'phase':keys((0,0),(2,1))}),text('one','One useful shape',y=.2,size=.09,enter='fade')]),scene('switch',4,[layer('toggle','interface',{'kind':'toggle'},width=.27,height=.11,tracks={'phase':keys((0,0),(1.8,1),ease='back_out')}),layer('pointer','interface',{'kind':'cursor'},x=.7,y=.6,tracks={'x':keys((0,.85),(1.3,.53)),'y':keys((0,.7),(1.3,.52))}),text('label','Turn an idea into action.',y=.76,size=.045)],transition={'type':'crossfade','duration':.4}),scene('result',5,[layer('panel','interface',{'kind':'dashboard','title':'A useful rhythm','subtitle':'Fewer moving parts. More progress.','items':['Choose a direction','Move together','See what changed']},width=.66,height=.75,enter='pop'),text('finish',name,y=.08,size=.047)],transition={'type':'slide','duration':.4})]
        else:base['scenes']=[scene('promise',4,[text('name',name,size=.2,enter='pop'),text('promise','Your ideas deserve a quieter workspace.',y=.7,size=.044,font='body',enter='fade',start=.5),layer('accent-line','path',{'points':[[-.35,0],[.35,0]],'color':'$accent','line_width':.006},width=.7,height=.1,y=.61,enter='draw',start=.7)]),scene('workflow',5,[layer('window','interface',{'kind':'browser','title':name,'subtitle':'One calm place for the work.','items':['Capture a thought','Pick the next move','Leave a clear result']},width=.76,height=.7,enter='slide_up'),layer('pointer','interface',{'kind':'cursor'},x=.9,y=.85,tracks={'x':keys((0,.9),(3,.31)),'y':keys((0,.85),(3,.54))})],transition={'type':'crossfade','duration':.5}),scene('overview',5,[layer('dashboard','interface',{'kind':'dashboard','title':'A clearer week','subtitle':'Progress you can actually see.','items':['Research','Design','Finish']},width=.76,height=.78,enter='pop'),text('top','Less noise. Better work.',y=.08,size=.05)],style='blueprint',transition={'type':'wipe','duration':.45}),scene('closing',3,[text('closing-name',name,size=.15,y=.42,enter='fade'),text('closing-copy','Make space for the next good idea.',size=.04,y=.66,font='body',enter='fade',start=.4)])]
    elif identifier in ('science','orbital','cradle','engineering'):
        base['style']='blueprint';base['sound']={'music':'ambient','gain':.12,'cues':[{'time':4,'type':'impact'},{'time':9,'type':'whoosh'}]}
        if identifier=='science':base['scenes']=[scene('approach',4,[layer('grid','grid',{'kind':'lines','spacing':.075},width=1,height=1,opacity=.45),text('intro',name,y=.16,size=.09,enter='fade'),layer('left','shape',{'fill':'$accent'},width=.025,height=.045,tracks={'x':keys((0,.1),(4,.5),ease='cubic_in')}),layer('right','shape',{'fill':'$secondary'},width=.025,height=.045,tracks={'x':keys((0,.9),(4,.5),ease='cubic_in')})]),scene('collision',5,[layer('rings','shape',{'kind':'ring','fill':'$muted','line_width':.008},width=.52,height=.8),layer('tracks','particles',{'pattern':'burst','count':160,'color':'$secondary','size':.004},width=.8,height=.85,tracks={'spread':keys((0,0),(.5,.6),(3,1)), 'reveal':keys((0,0),(.15,1))}),text('fact','A collision becomes a pattern of tracks.',y=.9,size=.036,font='body',enter='fade',start=.7)],transition={'type':'glitch','duration':.25}),scene('decode',5,[layer('flow','diagram',{'nodes':[{'id':'a','label':'Collision','x':.12,'y':.5},{'id':'b','label':'Detector','x':.5,'y':.5},{'id':'c','label':'Evidence','x':.88,'y':.5}],'edges':[['a','b'],['b','c']]},width=.85,height=.5),text('decode-title','Follow the evidence',y=.22,size=.1,enter='fade'),text('scope','An illustration of signal flow, not a physical simulation.',y=.85,size=.025,font='body')],transition={'type':'crossfade','duration':.5})]
        elif identifier=='engineering':base['scenes']=[scene('assembled',5,[text('title',name,y=.13,size=.095,enter='fade'),layer('engine','machine',{'speed':3,'labels':True},width=.8,height=.68,y=.56,enter='fade')]),scene('explode',6,[text('explain','Four stages. One continuous flow.',y=.12,size=.064,enter='slide_up'),layer('stages','machine',{'speed':2,'labels':True},width=.9,height=.7,y=.55,tracks={'phase':keys((0,0),(3,1))})],transition={'type':'crossfade','duration':.55}),scene('result',4,[layer('diagram','diagram',{'nodes':[{'id':'a','label':'Intake','x':.08,'y':.5},{'id':'b','label':'Compress','x':.36,'y':.5},{'id':'c','label':'Burn','x':.64,'y':.5},{'id':'d','label':'Exhaust','x':.92,'y':.5}],'edges':[['a','b'],['b','c'],['c','d']]},width=.88,height=.5),text('closing','Understand the flow.',y=.22,size=.095)])]
        elif identifier=='orbital':base['style']='neon';base['scenes']=[scene('worlds',14,[layer('stars','weather',{'kind':'stars','count':130,'color':'$muted'},width=1,height=1),layer('system','orbit',{'count':3,'labels':['Near','Between','Beyond'],'speed':1.2},width=.8,height=.8,y=.56),text('title',name,y=.12,size=.08,font='serif',enter='fade')],camera={'tracks':{'zoom':keys((0,1),(14,1.09))}})]
        else:base['scenes']=[scene('momentum',12,[text('title',name,y=.12,size=.12,enter='fade'),layer('pendulums','orbit',{'kind':'cradle','count':5,'speed':1.1},width=.68,height=.58,y=.58),text('note','Motion passed from one end to the other.',y=.9,size=.035,font='body',enter='fade',start=1)],camera={'tracks':{'zoom':keys((0,1),(12,1.06))}})]
    elif identifier=='ink-landscape':
        base.update(style='ink',sound={'music':'ambient','gain':.12,'cues':[{'time':5,'type':'chime'}]})
        base['scenes']=[scene('painting',16,[layer('wash','landscape',{'kind':'mountains','layers':5,'speed':0},width=1,height=1,y=.57,enter='draw',enter_duration=7),layer('mist','weather',{'kind':'mist','count':14,'speed':.25},width=1,height=.6,y=.55),layer('sun','shape',{'kind':'circle','fill':'$accent'},x=.77,y=.3,width=.08,height=.14,start=5,enter='fade',enter_duration=2),text('poem',name,x=.25,y=.19,width=.4,height=.18,size=.07,font='serif',enter='type',enter_duration=3,start=2),text('quiet','Leave room for the clouds.',x=.75,y=.83,width=.45,height=.15,size=.033,font='serif',start=8,enter='fade')],camera={'tracks':{'zoom':keys((0,1),(16,1.04))}})]
    elif identifier=='mosaic':
        base.update(style='mosaic',sound={'music':'ambient','gain':.14,'cues':[{'time':7,'type':'chime'}]})
        base['scenes']=[scene('aquarium',14,[layer('stars','weather',{'kind':'stars','count':80,'color':'$paper'},width=1,height=1),layer('moon','shape',{'fill':'$glow'},x=.75,y=.18,width=.08,height=.14,enter='fade'),layer('bowl','shape',{'kind':'circle','fill':'$secondary','stroke':'$paper','line_width':.008},y=.56,width=.38,height=.65,enter='pop'),layer('fish','shape',{'kind':'blob','fill':'$accent'},y=.56,width=.13,height=.1,motion={'type':'float','amount':.05,'speed':.18}),layer('bubbles','weather',{'kind':'fireflies','count':26,'size':.0025},width=.24,height=.45,y=.56,start=3,enter='fade'),text('title',name,y=.9,size=.045,font='serif',enter='fade',start=1)])]
    elif identifier=='data-story':
        base['scenes']=[scene('flow',6,[text('title',name,y=.14,size=.1,enter='fade'),layer('map','diagram',{'nodes':[{'id':'a','label':'Gather','x':.12,'y':.5},{'id':'b','label':'Compare','x':.5,'y':.5},{'id':'c','label':'Decide','x':.88,'y':.5}],'edges':[['a','b'],['b','c']]},width=.86,height=.55,enter='fade'),text('rule','Find the pattern before making the claim.',y=.85,size=.034,font='body')]),scene('evidence',6,[text('chart-title','See what changed.',y=.13,size=.09,enter='fade'),layer('plot','chart',{'kind':'bar','values':[22,38,61,79],'labels':['Start','Listen','Learn','Build'],'show_values':True},width=.78,height=.57,y=.56,enter='draw',enter_duration=1.2),text('label','Illustrative values',y=.94,size=.024,font='body',color='$muted')],transition={'type':'slide','duration':.45}),scene('summary',3,[text('summary','Make the next move clearer.',size=.095,enter='fade')])]
    elif identifier=='comic':
        base.update(style='punk',palette={'accent':'#e95543','secondary':'#326b9b'},bpm=120,sound={'music':'electro','gain':.14,'cues':[{'time':4,'type':'whoosh'},{'time':9,'type':'impact'},{'time':12,'type':'chime'}]})
        base['scenes']=[scene('arrival',4,[layer('city','landscape',{'kind':'city','layers':3},width=1,height=1),layer('runner','character',{'action':'run','costume':'hoodie','prop':'flag'},width=.2,height=.56,y=.67,tracks={'x':keys((0,-.15),(4,.75),ease='linear')}),text('heading',name,y=.17,size=.1,rotation=-3,enter='pop'),text('caption','One message. One very fast courier.',y=.91,size=.03,font='mono')]),scene('delivery',5,[layer('rays','grid',{'kind':'perspective','color':'$secondary'},width=1,height=1),layer('burst','shape',{'kind':'star','points':12,'inner':.7,'fill':'$accent'},width=.55,height=.86,tracks={'scale':keys((0,.2),(.5,1),ease='back_out')}),layer('courier','character',{'action':'wave','costume':'hoodie'},width=.25,height=.7,y=.59),layer('bubble','shape',{'kind':'rect','fill':'$paper','stroke':'$ink','corners':.04},x=.76,y=.22,width=.34,height=.2),text('speech','YOU GOT THIS!',x=.76,y=.22,width=.3,height=.18,size=.057,enter='pop',start=.5)],transition={'type':'slide','duration':.3}),scene('impact',3,[layer('hit','shape',{'kind':'star','fill':'$secondary','points':8},width=.65,height=.95,motion={'type':'spin','speed':.08}),text('impact','KA-POW!',size=.2,rotation=-8,enter='pop')],background='$accent',transition={'type':'glitch','duration':.2}),scene('end',3,[text('resolve','Pass the good news on.',y=.42,size=.1,enter='slide_up'),text('tag','Special delivery. Right on time.',y=.65,size=.032,font='mono',enter='fade')],transition={'type':'iris','duration':.4})]
    elif identifier=='punk-zine':
        base.update(style='punk',bpm=128,sound={'music':'electro','gain':.18,'cues':[{'time':4,'type':'impact'},{'time':8,'type':'whoosh'},{'time':12,'type':'impact'}]})
        base['scenes']=[scene('poster',4,[layer('dots','grid',{'kind':'halftone','color':'$muted','spacing':.04},width=1,height=1,opacity=.45),text('slogan',name,y=.34,size=.2,rotation=-5,mode='words',enter='pop'),text('sub','Break the pattern. Find a new rhythm.',y=.76,size=.04,font='mono',enter='fade',start=.8)]),scene('character',4,[layer('burst','shape',{'kind':'star','points':9,'fill':'$accent','inner':.68},width=.55,height=.86,rotation=10,enter='pop'),layer('courier','character',{'action':'dance','costume':'hoodie','color':'$secondary'},width=.25,height=.7,y=.59),text('call','MOVE!',x=.78,y=.27,width=.35,height=.2,size=.12,rotation=9,enter='pop')],background='$paper',transition={'type':'wipe','duration':.25}),scene('mix',4,[layer('back','grid',{'kind':'halftone','color':'$accent','spacing':.05},width=1,height=1),layer('assembly','cube',{'count':2,'color':'$secondary','speed':.5,'explode':.15},width=.55,height=.7,x=.35,y=.55),text('mix-text','MAKE\nSOMETHING\nDIFFERENT.',x=.74,y=.5,width=.48,height=.72,size=.1,rotation=-3,mode='words')],transition={'type':'glitch','duration':.3}),scene('outro',3,[text('last','Keep the good kind of chaos.',width=.85,size=.13,rotation=2,enter='pop'),text('signature','A new idea starts with a little curiosity.',y=.79,size=.031,font='mono',enter='fade',start=.5)],background='$accent',transition={'type':'slide','duration':.3})]
    return AnimationComposition.model_validate(base)
