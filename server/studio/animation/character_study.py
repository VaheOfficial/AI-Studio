"""A clothed miniature character performs three connected beats around a small light."""
import math
from .recipes import layer,text,scene,keys
from .scene_recipes import mascot,node
from ..schemas_animation import AnimationComposition

def actor():
    parts=[n for n in mascot() if n['id'] not in ('scarf','scarf-tail','platform','floor','mouth','belly')]
    by={n['id']:n for n in parts}
    by['face']['fibers']={'count':6500,'length':.016,'thickness':.0016}
    for tag in ('left-ear','right-ear'):by[tag]['fibers']={'count':1600,'length':.022,'thickness':.0018}
    by['body'].update(color='#b66e32',texture='canvas',roughness=1,clearcoat=0)
    for side in ('left','right'):
        by[side+'-eye-glint'].update(parent=side+'-eye',position=[-.013,.0208,.06143],scale=[1,.8,1/.7])
        by[side+'-arm'].update(color='#b66e32',texture='canvas',roughness=1)
        by[side+'-foot'].update(color='#294349',texture='canvas',roughness=.9)
        parts.append(node(side+'-cuff','torus',(-.2 if side=='left' else .2,-.43,.02),(.17,.035,1),'#deaa67',parent=side+'-arm-pivot',rotation=[90,0,-25 if side=='left' else 25],roughness=1,texture='canvas'))
        parts.append(node(side+'-hand','sphere',(-.25 if side=='left' else .25,-.54,.04),(.18,1,1),'#9babc1',parent=side+'-arm-pivot',scale=[1,1.1,.8],texture='wool',roughness=1))
        parts.append(node(side+'-sole','sphere',(-.3 if side=='left' else .3,.24,.17),(.285,1,1),'#d3ba8d',parent='actor',scale=[1,.35,1.35],roughness=.95))
    parts.extend([node('muzzle','sphere',(0,-.11,.58),(.27,1,1),'#c3c5bf',parent='head',scale=[1,.55,.38],texture='wool',roughness=1),node('smile','tube',color='#273a3e',parent='head',curve=[[-.095,-.135,.686],[0,-.17,.7],[.095,-.13,.686]],dimensions=[.012,1,1],roughness=.7),node('collar','torus',(0,1.77,0),(.42,.065,1),'#d9a168',parent='actor',rotation=[90,0,0],roughness=1,texture='canvas'),node('pocket','rounded_box',(0,1.05,.53),(.55,.36,.075),'#c88845',parent='actor',roughness=1,texture='canvas'),node('zip','tube',parent='actor',color='#6a482c',curve=[[0,1.76,.35],[0,1.57,.49],[0,1.38,.54],[0,1.26,.55]],dimensions=[.012,1,1]),node('zip-pull','rounded_box',(0,1.57,.515),(.047,.075,.025),'#d6ba6e',parent='actor',metalness=.7,roughness=.4)])
    parts.extend([node('cap','sphere',(0,.9,-.045),(.61,1,1),'#356166',parent='head',scale=[1,.58,.94],texture='canvas',roughness=1),node('hat-band','torus',(0,.76,-.045),(.57,.08,1),'#4b7b7c',parent='head',rotation=[90,0,0],scale=[1,1,.58],texture='canvas',roughness=1),node('pom','sphere',(.025,1.27,-.07),(.13,1,1),'#bdc9be',parent='head',texture='wool',roughness=1)])
    for j in range(12):
        x=-.245+j*.044
        parts.append(node('stitch-'+str(j),'rounded_box',(x,.93,.574),(.016,.009,.005),'#e6b979',parent='actor',roughness=1))
    for j in range(20):
        az=j*math.tau/20;curve=[]
        for degrees in (28,48,70,92,111):
            a=math.radians(degrees);curve.append([.615*math.sin(a)*math.sin(az),.9+.359*math.cos(a),-.045+.578*math.sin(a)*math.cos(az)])
        parts.append(node('hat-rib-'+str(j),'tube',parent='head',curve=curve,dimensions=[.005,1,1],color='#4a7475',roughness=1,clearcoat=0))
    return parts

def scenery():
    parts=[node('floor','plane',(0,.025,0),(100,100,1),'#122f32',rotation=[-90,0,0],cast_shadow=False,roughness=1),node('stone','sphere',(0,-.05,0),(1.6,1,1),'#294445',scale=[1,.1,.75],roughness=1)]
    for k,(x,z,size) in enumerate([(-2.6,-1.2,1.2),(2.4,-1.8,1.4),(-3.8,-3,1.5),(4,-3,1.6)]):
        parts.append(node('plant-'+str(k),'group',(x,0,z),scale=[size,size,size]))
        parts.append(node('stem-'+str(k),'tube',parent='plant-'+str(k),color='#4d6b5c',curve=[[0,0,0],[.08,.7,0],[-.1,1.5,0]],dimensions=[.025,1,1],roughness=1))
        for j in range(5):
            side=1 if j%2 else -1
            pts=[[-.02,0],[side*.2,.32],[side*.6,.45],[side*.55,.18],[side*.24,-.015]]
            parts.append(node(f'leaf-{k}-{j}','polygon',(0,.23+j*.24,0),color=['#3b685d','#60856c','#7c966e'][j%3],parent='plant-'+str(k),points=pts,depth=.015,rotation=[j*8,side*20,-side*12],roughness=.9,texture='paper'))
    return parts

def make(*,title,width,height,fps,seed):
    shots=[]
    for index,name in enumerate(('a-glimmer','a-meeting','a-goodnight')):
        nodes=actor()+scenery();by={n['id']:n for n in nodes}
        for item in nodes:
            if item.get('texture') in ('wool','canvas'):item.update(texture_scale=1.5,bump_strength=.07 if item['texture']=='wool' else .035,clearcoat=0)
            if item['id'].startswith('plant-'):item['motion']={'axis':'rz','kind':'sway','amount':1.5,'speed':.09,'phase':len(item['id'])}
        by['head']['tracks']={'ry':keys((0,-8),(.8,-8),(1.4,18),(2.5,24),(4,16),(6,5)),'rz':keys((0,-3),(1.2,-3),(1.6,7),(4,5),(6,0))}
        by['actor']['tracks']={'ry':keys((0,-8),(2,5),(6,5))}
        for side in ('left','right'):
            by[side+'-eye']['tracks']={'sy':keys((0,1.25),(2.7,1.25),(2.78,.06),(2.91,1.25),(5.5,1.25),(5.58,.06),(5.7,1.25),(6,1.25))}
        if index==0:
            camera={'position':[5,3.4,8],'target':[0,1.3,0],'fov':34,'tracks':{'x':keys((0,5),(6,3.7)),'z':keys((0,8),(6,7.2))}}
            orb={'x':keys((0,3.2),(1.2,1.6),(3,1.3),(4.5,1.7),(6,1.2)),'y':keys((0,2.4),(1.2,2.8),(3,2.5),(4.5,2.8),(6,2.55))}
            by['right-arm-pivot']['tracks']={'rz':keys((0,0),(3,0),(4.3,28),(6,40))}
        elif index==1:
            camera={'position':[2.8,2.9,5.5],'target':[.4,1.85,.2],'fov':33,'tracks':{'x':keys((0,2.8),(6,1.6))}}
            orb={'x':keys((0,1.2),(1.4,1.05),(2.8,1.1),(5,1.1),(6,1.25)),'y':keys((0,2.55),(1.4,2.05),(2.8,1.97),(5,1.97),(6,2.25))}
            by['right-arm-pivot']['tracks']={'rz':keys((0,40),(1.2,90),(1.7,84),(5,84),(6,65))}
            by['head']['tracks']={'ry':keys((0,16),(1.5,25),(4,22),(6,16)),'rz':keys((0,5),(2,-8),(4,-8),(6,3))}
        else:
            camera={'position':[1.7,2.9,7],'target':[0,1.55,0],'fov':37,'tracks':{'z':keys((0,7),(6,8.8))}}
            orb={'x':keys((0,1.25),(1,1.5),(2,1.1),(3,-.5),(4,-1.3),(6,-2.1)),'y':keys((0,2.25),(1,3),(2,3.6),(3,3.7),(4,3.6),(6,4.3))}
            by['right-arm-pivot']['tracks']={'rz':keys((0,65),(1,100),(1.5,78),(2,108),(2.5,85),(3,110),(4,35),(6,0))}
            by['head']['tracks']={'ry':keys((0,16),(2,0),(4,-20),(6,-20)),'rx':keys((0,0),(2,-12),(6,-12))}
        nodes.extend([node('light','group',(1.2,2.55,.8),tracks=orb),node('light-body','sphere',dimensions=[.07,1,1],color='#e9cf77',parent='light',emissive='#f5bb54',emissive_intensity=3,roughness=.3),node('light-wing-a','sphere',(.055,.02,0),(.075,1,1),'#dcdcb0',parent='light',scale=[1,.25,.55],motion={'axis':'rz','kind':'sway','amount':35,'speed':5}),node('light-wing-b','sphere',(-.055,.02,0),(.075,1,1),'#dcdcb0',parent='light',scale=[1,.25,.55],motion={'axis':'rz','kind':'sway','amount':-35,'speed':5})])
        layers=[layer('world','scene3d',{'nodes':nodes,'camera':camera,'ambient':.3,'environment_intensity':.15,'exposure':1,'lights':[{'kind':'directional','position':[-3,6,5],'color':'#ffe0a7','intensity':3,'shadow':True},{'kind':'directional','position':[4,3,-4],'color':'#77b4b6','intensity':2},{'kind':'point','position':[1.2,2.2,1.2],'color':'#ffca65','intensity':2.4}]},width=1,height=1)]
        layers[0]['props']['fog']={'color':'$background','near':10,'far':25}
        layers[0]['props'].update(shadow_extent=6,shadow_resolution=2048)
        next(n for n in nodes if n['id']=='light-body')['glow']=.32
        if index==2:layers.append(text('close','Small things make a night.',y=.91,width=.8,height=.08,size=.033,font='serif',color='#dfd6b6',start=2,enter='fade',enter_duration=1.2))
        shots.append(scene(name,6,layers,transition={'type':'cut','duration':.1}))
    return AnimationComposition.model_validate({'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'studio','palette':{'background':'#102e32','ink':'#dfd6b6'},'finishing':{'grain':.025,'vignette':.2},'sound':{'music':'ambient','gain':.035,'cues':[{'time':8.8,'type':'chime','gain':.045},{'time':15,'type':'chime','gain':.025}]},'scenes':shots})
