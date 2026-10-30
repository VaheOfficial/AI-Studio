"""An authored turbofan illustration with a hollow shell and staged rotor geometry."""
import math
from .scene_recipes import node
from .recipes import layer,text,scene,keys
from ..schemas_animation import AnimationComposition

def engine(cutaway,explode,duration):
    steel='#879bab';gold='#c49660';shell='#d8d4c8';parts=[node('engine','group')]
    profile=[[1.25,-2.4],[1.4,-2.15],[1.4,-1.7],[1.08,-.4],[1.07,1.2],[.8,2],[.72,2.2],[.65,2.2],[.74,2],[.97,1.2],[.98,-.4],[1.3,-1.7],[1.3,-2.15],[1.25,-2.4]]
    parts.extend([node('shell','lathe',color=shell,parent='engine',profile=profile,rotation=[90,0,0],angle_start=95 if cutaway else 0,angle_length=180 if cutaway else 360,metalness=.35,roughness=.3,tracks={'y':keys((0,0),(duration,2.2 if explode else 0))}),node('shaft','lathe',color=steel,parent='engine',profile=[[0,-2.4],[.15,-2.2],[.3,-1.65],[.28,1.4],[.14,2.1],[0,2.3]],rotation=[90,0,0],metalness=.85,roughness=.23),node('fan','group',(0,0,-1.9),parent='engine',tracks={'rz':keys((0,0),(duration,540),ease='linear'),'z':keys((0,-1.9),(duration,-3.1 if explode else -1.9))})])
    for j in range(24):
        angle=j*math.tau/24
        parts.append(node('fan-blade-'+str(j),'rounded_box',(math.sin(angle)*.77,math.cos(angle)*.77,0),(.11,.82,.065),steel,parent='fan',rotation=[0,32,-j*15],metalness=.78,roughness=.3,texture='brushed'))
    for i in range(6):
        z=-1.2+i*.48;radius=.9-i*.065;target=z+(i-2.5)*.48 if explode else z
        parts.append(node('stage-'+str(i),'group',(0,0,z),parent='engine',tracks={'rz':keys((0,i*9),(duration,360+i*9),ease='linear'),'z':keys((0,z),(duration,target))}))
        parts.append(node('stage-ring-'+str(i),'torus',(0,0,0),(radius,.055,1),gold if i>3 else steel,parent='stage-'+str(i),metalness=.8,roughness=.28))
        for j in range(12):
            angle=j*math.tau/12
            parts.append(node(f'blade-{i}-{j}','rounded_box',(math.sin(angle)*radius*.58,math.cos(angle)*radius*.58,0),(.095,radius*.7,.045),gold if i>3 else steel,parent='stage-'+str(i),rotation=[0,27,-j*30],metalness=.72,roughness=.32,texture='brushed'))
    if cutaway:
        for i in range(5):
            x=(i-2)*.24
            parts.append(node('flow-'+str(i),'tube',dimensions=(.018,1,1),color='#8fc9d6',parent='engine',curve=[[x,.35,-3],[x,.38,-1.8],[x,.4,-.8],[x,.42,.5],[x,.4,1.6],[x,.35,3]],emissive='#2b899c',emissive_intensity=.6,roughness=.5,cast_shadow=False))
        parts.append(node('combustor','torus',(0,0,.8),(.59,.07,1),gold,parent='engine',emissive='#de7c30',emissive_intensity=.6,metalness=.5))
    parts.extend([node('plane-body','lathe',(-3.1,2.4,3),color='#e4dfd1',profile=[[0,-5.2],[.45,-4.9],[.68,-3.9],[.7,3.9],[.43,4.6],[0,5.4]],rotation=[90,0,0],roughness=.45),node('wing','polygon',(-3.1,2.15,1.6),color='#d9d5ca',points=[[-.25,-2],[.45,-2],[5,2],[4.6,3],[-.5,1.5]],depth=.08,rotation=[90,0,0],roughness=.45),node('pylon','rounded_box',(0,1.55,1.1),(.3,1.5,1.0),'#d0cbbf',roughness=.4),node('floor','plane',(0,-1.6,0),(100,100,1),'#9f96ad',rotation=[-90,0,0],roughness=.9,cast_shadow=False)])
    for i in range(10):parts.append(node('cabin-window-'+str(i),'rounded_box',(-2.42,2.57,-.5+i*.5),(.04,.17,.22),'#354958',roughness=.2))
    parts.append(node('cockpit','sphere',(-2.72,2.65,-1.3),(.34,1,1),'#354958',scale=[.5,.43,1.1],roughness=.18))
    if cutaway:parts[1]['angle_start']=180
    return parts

def make(*,title,width,height,fps,seed):
    shots=[]
    for i,(name,duration,cutaway,explode,caption) in enumerate([('whole',4,False,False,'One machine. Thousands of decisions.'),('inside',6,True,False,'Air in. Compression. Combustion. Thrust.'),('stages',6,True,True,'Separate the stages. See the system.')]):
        camera={'position':[6,3.6,-7],'target':[-.6,.7,0],'fov':40,'tracks':{'x':[{'time':0,'value':6},{'time':duration*.5,'value':4.4,'interpolation':'monotone'},{'time':duration,'value':3.5,'interpolation':'monotone'}],'z':keys((0,-7),(duration,-6))}}
        if explode:camera.update(position=[6,4,-9],target=[0,.8,0],tracks={'x':keys((0,6),(duration,5)),'z':keys((0,-9),(duration,-10))})
        shots.append(scene(name,duration,[layer('world','scene3d',{'nodes':engine(cutaway,explode,duration),'camera':camera,'ambient':.45,'exposure':.85,'environment_intensity':.4,'fog':{'color':'$background','near':15,'far':35},'lights':[{'kind':'directional','position':[4,7,-6],'color':'#fff1d9','intensity':3,'shadow':True},{'kind':'directional','position':[-5,3,4],'color':'#b1c5dd','intensity':2}]},width=1,height=1),text('title',title if i==0 else name.capitalize(),y=.08,width=.9,height=.12,size=.055,color='#2e3346',enter='fade'),text('caption',caption,y=.92,width=.9,height=.12,size=.038,color='#2e3346',enter='fade',start=.3)],transition={'type':'cut','duration':.1}))
    return AnimationComposition.model_validate({'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'studio','palette':{'background':'#aaa0b5','ink':'#f6efe0','accent':'#b9d4d8','secondary':'#d7a167'},'finishing':{'grain':.02,'vignette':.09},'sound':{'music':'ambient','gain':.06,'cues':[{'time':4,'type':'whoosh','gain':.15},{'time':10,'type':'whoosh','gain':.15}]},'scenes':shots})
