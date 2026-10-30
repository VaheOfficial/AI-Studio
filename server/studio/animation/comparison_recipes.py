"""Reference studies and original films composed from the public animation components."""
import math,random
from .recipes import layer,text,scene,keys
from .pigment_recipes import ink,stroke
from .scene_recipes import node
from ..schemas_animation import AnimationComposition

def ink_reference(*,title,width,height,fps,seed):
    data=ink(title=title,width=width,height=height,fps=fps,seed=seed).model_dump(mode='json');rng=random.Random(seed);marks=[];underpaint=[]
    ridges=[([(.02,.61),(.15,.48),(.25,.55),(.39,.61),(.6,.64)],.69,.19,1.5,7),([(.14,.7),(.27,.59),(.43,.29),(.51,.43),(.58,.49),(.71,.71)],.76,.62,6,10),([(.6,.72),(.69,.62),(.78,.43),(.86,.61),(.98,.71)],.77,.6,15,8)]
    for ri,(ridge,base,density,begin,span) in enumerate(ridges):
        for band in range(18):
            depth=band/18
            points=[[x,y+(base-y)*depth,.07 if index in (0,len(ridge)-1) else 1] for index,(x,y) in enumerate(ridge)]
            underpaint.append(stroke(points,.025,'#39403a',density*.22*(1-depth)**1.7,begin+span*.25+band*.09,span*.6,'ink',ri*50+band))
        for j in range(74):
            x=ridge[0][0]+(ridge[-1][0]-ridge[0][0])*j/73
            a,b=next((a,b) for a,b in zip(ridge,ridge[1:]) if x<=b[0]+1e-8);u=(x-a[0])/(b[0]-a[0]);y=a[1]+(b[1]-a[1])*u+rng.uniform(-.003,.003);drift=.025*math.sin(j*.45)
            marks.append(stroke([[x,y,.05],[x+drift*.2,y+(base-y)*.09,.9],[x+drift,y+(base-y)*.48,.8],[x+drift*.8,base,.01]],.047,'#303735',density*rng.uniform(.65,1),begin+j/74*span,2.6,'wash',ri*100+j))
        marks.append(stroke([[x,y,rng.uniform(.2,.8)] for x,y in ridge],.004,'#242b29',density,begin+.2,span,'dry',ri+800))
        if ri:
            peak=ridge[2]
            for j in range(16):
                x=peak[0]+j*.004;yy=peak[1]+j*.006
                marks.append(stroke([[x,yy,.05],[x+.024,yy+.09,.7],[x+.072,yy+.18,.02]],.002,'#384039',.28,begin+span*.4+j*.12,1.9,'dry',ri*300+j))
    layers=[layer('mountain-wash','brush',{'strokes':underpaint,'grain':.3},width=1,height=1,blur=.008),layer('ridges','brush',{'strokes':marks[:256],'grain':.75},width=1,height=1)]
    if len(marks)>256:layers.append(layer('ridge-detail','brush',{'strokes':marks[256:],'grain':.75},width=1,height=1))
    for item in data['scenes'][0]['layers']:
        if item['id'] in ('mountains','signature'):continue
        if item['component']=='brush':
            for mark in item['props']['strokes']:mark['start']+=15 if item['id']=='pines' else 16
            if item['id']=='pines':
                for mark in item['props']['strokes']:
                    for pt in mark['points']:pt[1]-=.035
        elif item['id']=='sun':item['start']=32;item.update(x=.81,y=.265)
        elif item['id']=='boat':item['start']=30;item['tracks']['x']=keys((0,.69),(9,.74));item.update(y=.795)
        elif item['id'].startswith('bird-'):item['start']=34
        elif item['id']=='seal':item['start']=34;item.update(x=.88,y=.43)
        layers.append(item)
    layers.append(text('inscription','After\nthe\nrain',x=.89,y=.28,width=.08,height=.25,size=.027,font='serif',start=31,enter='fade',enter_duration=2))
    data.update(scenes=[scene('painting',39.2,layers)],finishing={'grain':.045,'vignette':.025});data['sound']['cues']=[{'time':32,'type':'chime','gain':.025}]
    return AnimationComposition.model_validate(data)

def mosaic_reference(*,title,width,height,fps,seed):
    from .mosaic_study import make
    return make(title=title,width=width,height=height,fps=fps,seed=seed)

def night_bloom(*,title,width,height,fps,seed):
    nodes=[node('ground','plane',(0,-.08,0),(100,100,1),'#102e2e',rotation=[-90,0,0],roughness=1,cast_shadow=False),node('stem','tube',color='#47776b',curve=[[0,0,0],[-.15,.8,.02],[.12,1.5,0],[0,2.1,0]],dimensions=[.045,1,1],roughness=1)]
    for i in range(5):
        side=-1 if i%2 else 1
        nodes.append(node('leaf-'+str(i),'polygon',(0,.35+i*.28,.02),color='#397568' if i%2 else '#5c8970',points=[[0,0],[side*.35,.08],[side*.73,.35],[side*.54,.53],[side*.13,.31]],depth=.025,rotation=[10,side*15,side*-12],texture='paper',roughness=1))
    nodes.append(node('flower','group',(0,2.08,0),rotation=[52,0,-8],tracks={'rz':keys((0,-8),(16,5))}))
    for ring,count,reach,shade in [(0,9,1.1,'#8fa6c2'),(1,7,.8,'#d9d7c7')]:
        for i in range(count):
            tag=f'petal-{ring}-{i}';nodes.append(node(tag,'group',parent='flower',rotation=[0,0,i/count*360+ring*20]))
            outline=[[side*.32*math.sin(t*math.pi)**.7,t*(reach+.1)] for side,steps in [(-1,range(9)),(1,range(8,-1,-1))] for t in [steps_i/8 for steps_i in steps]]
            nodes.append(node(tag+'-blade','polygon',parent=tag,points=outline,depth=.026,color=shade,texture='paper',roughness=1,clearcoat=0,tracks={'rx':keys((0,83),(1+ring*.4,83),(5+i*.13,13+ring*8),(16,18+ring*8))}))
    nodes.append(node('heart','sphere',(0,0,.14),(.23,1,1),'#dfb65c',parent='flower',scale=[1,1,.55],texture='wool',fibers={'count':2500,'length':.024,'thickness':.002},roughness=1,clearcoat=0,emissive='#e8b968',emissive_intensity=.2,glow=.34,tracks={'emissive_intensity':keys((0,.1),(5,.35),(9,1.2),(16,.5))}))
    nodes.append(node('moth','group',(-2.5,2.5,1),scale=[.45,.45,.45],tracks={'x':keys((0,-3),(4,-3),(6,-1.6),(8,.9),(10,.2),(12,0),(16,0)),'y':keys((0,2.7),(4,2.7),(6,3.6),(8,3.3),(10,2.7),(12,2.35),(16,2.35)),'z':keys((0,1),(8,1.4),(12,.47),(16,.47)),'rz':keys((0,-20),(6,15),(8,-15),(12,0),(16,0))}))
    nodes.append(node('moth-body','capsule',dimensions=[.085,.4,.085],color='#c5ab7a',parent='moth',rotation=[0,0,0],roughness=1))
    for side in (-1,1):
        tag='wing-'+str(side);frames=[]
        for i in range(81):
            t=i*.2;fade=max(0,min(1,(12-t)/2));frames.append((t,side*(18+50*math.sin(t*math.tau*1.8)*fade)))
        nodes.append(node(tag,'group',parent='moth',tracks={'ry':keys(*frames,ease='linear')}))
        nodes.append(node(tag+'-shape','polygon',parent=tag,points=[[side*x,y] for x,y in [(0,.15),(.12,.4),(.34,.66),(.67,.72),(.87,.6),(.95,.39),(.82,.16),(.61,.05),(.79,-.14),(.86,-.37),(.65,-.57),(.4,-.58),(.18,-.35),(0,-.18)]],depth=.02,color='#eedcb0',roughness=1,texture='paper'))
        for j in range(3):nodes.append(node(tag+'-vein-'+str(j),'tube',parent=tag,curve=[[side*.1,0,.035],[side*(.3+j*.08),.08-j*.12,.035],[side*(.68+j*.04),.43-j*.38,.035]],dimensions=[.009,1,1],color='#b39064',roughness=1))
        nodes.append(node(tag+'-eye','sphere',(side*.5,.16,.03),(.13,1,1),'#3c6570',parent=tag,scale=[1,1,.12],roughness=1))
        nodes.append(node('antenna-'+str(side),'tube',parent='moth',curve=[[side*.025,.24,0],[side*.1,.42,0],[side*.2,.45,0]],dimensions=[.009,1,1],color='#cab985',roughness=1))
    for i in range(14):nodes.append(node('star-'+str(i),'sphere',(-6+(i*3.31)%12,2.4+(i*1.17)%3,-6),(.014+(i%3)*.006,1,1),'#d2dfc5',emissive='#d2dfc5',emissive_intensity=1,cast_shadow=False))
    moth=next(n for n in nodes if n['id']=='moth');moth['tracks']['y']=keys((0,2.7),(4,2.7),(6,3.05),(8,3),(10,2.7),(12,2.35),(16,2.35));moth['tracks']['x']=keys((0,-1.9),(4,-1.7),(6,-.8),(8,.55),(10,.2),(12,0),(16,0))
    props={'nodes':nodes,'camera':{'position':[3,2.9,6.5],'target':[0,1.65,0],'fov':37,'tracks':{'x':keys((0,3),(5,1.2),(10,-.4),(16,1.5)),'z':keys((0,6.5),(5,4.8),(10,5.2),(16,7.5)),'target_y':keys((0,1.65),(5,2),(10,2),(16,1.65))}},'ambient':.45,'environment_intensity':.18,'shadow_extent':5,'shadow_resolution':2048,'fog':{'color':'#102a2e','near':10,'far':25},'lights':[{'kind':'directional','position':[-3,6,4],'color':'#d2e1ee','intensity':2.8,'shadow':True},{'kind':'directional','position':[4,4,-4],'color':'#5ac7ba','intensity':2},{'kind':'point','position':[0,2.4,1],'color':'#ffc576','intensity':2}]}
    return AnimationComposition.model_validate({'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'studio','palette':{'background':'#102a2e','ink':'#d8dfcf'},'finishing':{'grain':.018,'vignette':.2},'sound':{'music':'ambient','gain':.045,'cues':[{'time':5,'type':'chime','gain':.05},{'time':12,'type':'chime','gain':.025}]},'scenes':[scene('bloom',16,[layer('garden','scene3d',props,width=1,height=1),text('close','Some things open after dark.',y=.91,width=.8,height=.08,size=.031,font='serif',start=12,enter='fade',enter_duration=1.5)])]})

def field_form(*,title,width,height,fps,seed):
    marks=[]
    for j in range(9):marks.append(stroke([[.05,.25+j*.055,.05],[.28,.04+j*.07,1],[.5,.64-j*.035,.6],[.72,.2+j*.055,1.4],[.97,.55+j*.025,.03]],.024,'#77d6ce' if j%2 else '#f3dba8',.8,j*.09,1.8,'dry',seed+j))
    first=scene('pressure',4,[layer('marks','brush',{'strokes':marks,'grain':.8},width=1,height=1),text('word','PRESSURE',width=.9,height=.35,size=.2,font='condensed',color='#f7eac9',start=.8,enter='fade'),text('sub','A line finds its weight.',y=.87,width=.8,height=.08,size=.035,font='serif',start=1.5,enter='fade')])
    paths=[{'d':'M50 2A48 48 0 1 1 49.9 2Z','fill':'#ecb961'},{'d':'M50 15A35 35 0 1 1 49.9 15Z','fill':'#214f66'},{'d':'M50 28A22 22 0 1 1 49.9 28Z','fill':'#e97f62'},{'d':'M50 40A10 10 0 1 1 49.9 40Z','fill':'#e5ddbb'}]
    second=scene('pattern',4,[layer('disc','vector',{'view_box':[0,0,100,100],'paths':paths,'texture':'mosaic','tile_flow':'radial','tile_size':.018,'tile_scatter':.65},width=.55,height=.95,x=.69,props_tracks={'tile_assembly':keys((0,0),(1.5,1),(3.2,1),(4,.35))},tracks={'rotation':keys((0,-25),(4,35),ease='linear')}),text('word','PATTERN',x=.32,y=.49,width=.58,height=.4,size=.2,font='condensed',color='#f7eac9',rotation=-4),text('sub','A mark becomes a system.',x=.29,y=.85,width=.52,height=.08,size=.035,font='serif')])
    second['background']='#e8dfc4'
    for item in second['layers']:
        if item['component']=='text':item['props']['color']='#183c4a'
    pieces=[node('rosette','group',rotation=[-10,25,0],tracks={'ry':keys((0,25),(4,-15)),'rz':keys((0,0),(4,70))}),node('petals','polygon',parent='rosette',points=[[-.1,0],[0,.9],[.1,0],[0,-.2]],depth=.035,color='#82bdb7',roughness=.8,texture='paper',repeat={'count':64,'layout':'radial','radius':1.5},tracks={'spread':keys((0,.8),(1.3,0),(4,.1)),'flip':keys((0,.7),(1.3,0),(4,.25))}),node('center','sphere',dimensions=[.35,1,1],parent='rosette',color='#e5b666',metalness=.55,roughness=.25)]
    third=scene('form',4,[layer('sculpture','scene3d',{'nodes':pieces,'camera':{'position':[0,0,9],'target':[0,0,0],'fov':35},'ambient':.8,'environment_intensity':.4},width=.7,height=1,x=.5),text('word','FORM',width=.8,height=.35,size=.23,font='condensed',color='#f7eac9',y=.48),text('sub','Give the idea another dimension.',y=.88,width=.8,height=.08,size=.035,font='serif')])
    return AnimationComposition.model_validate({'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'studio','palette':{'background':'#132c39','ink':'#f7eac9'},'finishing':{'grain':.025,'vignette':.1},'sound':{'music':'electro','gain':.07,'cues':[{'time':4,'type':'impact','gain':.09},{'time':8,'type':'whoosh','gain':.1}]},'scenes':[first,second,third]})
