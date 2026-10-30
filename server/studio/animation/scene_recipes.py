"""Authored connected scenes with joint choreography and tracked cameras."""
import copy,math
from .recipes import layer,text,scene,keys
from ..schemas_animation import AnimationComposition

def node(id,kind,position=(0,0,0),dimensions=(1,1,1),color='#ffffff',**kwargs):
    return {'id':id,'kind':kind,'position':list(position),'dimensions':list(dimensions),'color':color,**kwargs}

def mascot():
    grey='#9babc1';cream='#eee5dc';pink='#d78c94';dark='#20273b'
    parts=[node('actor','group'),node('body','sphere',(0,1.15,0),(.66,1,1),grey,parent='actor',scale=[1,1.2,.8],roughness=.95),node('belly','sphere',(0,1.1,.42),(.4,1,1),cream,parent='actor',scale=[1,1.1,.28],roughness=1),node('head','group',(0,2.0,0),parent='actor',tracks={'rz':keys((0,-5),(1.5,6),(3,-4),(5,2))}),node('face','sphere',(0,.18,0),(.85,1,1),grey,parent='head',scale=[1,.88,.77],roughness=.95)]
    for side in (-1,1):
        tag='left' if side<0 else 'right'
        parts.extend([node(tag+'-ear','sphere',(side*.74,.62,0),(.38,1,1),grey,parent='head',scale=[1,1,.55],roughness=1),node(tag+'-ear-in','sphere',(side*.74,.62,.19),(.24,1,1),pink,parent='head',scale=[1,1,.3],roughness=1),node(tag+'-eye','sphere',(side*.29,.25,.59),(.065,1,1),dark,parent='head',scale=[1,1.25,.7],roughness=.15),node(tag+'-eye-glint','sphere',(side*.29-.013,.276,.633),(.018,1,1),cream,parent='head'),node(tag+'-cheek','sphere',(side*.4,.07,.565),(.13,1,1),pink,parent='head',scale=[1,.42,.18],roughness=1),node(tag+'-arm-pivot','group',(side*.52,1.5,0),parent='actor'),node(tag+'-arm','capsule',(side*.2,-.24,0),(.18,.44,.18),grey,parent=tag+'-arm-pivot',rotation=[0,0,side*25],roughness=.95),node(tag+'-foot','sphere',(side*.3,.34,.17),(.28,1,1),grey,parent='actor',scale=[1,.72,1.35],roughness=.95)])
    parts.extend([node('nose','sphere',(0,.12,.64),(.17,1,1),dark,parent='head',scale=[1,1.4,.7],roughness=.25),node('mouth','torus',(0,-.12,.58),(.095,.015,1),dark,parent='head',scale=[1,.48,.4]),node('scarf','torus',(0,1.74,0),(.45,.085,1),'#ea946d',parent='actor',rotation=[90,0,0]),node('scarf-tail','rounded_box',(.3,1.35,.45),(.16,.6,.07),'#ea946d',parent='actor',rotation=[0,0,-15]),node('platform','cylinder',(0,.03,0),(1.65,.2,1.65),'#e2d6e7',roughness=.55),node('floor','plane',(0,-.08,0),(100,100,1),'#e8e1ee',rotation=[-90,0,0],cast_shadow=False)])
    for item in parts:
        if item.get('roughness',0)>=.9:item.update(texture='wool',clearcoat=0)
        if item['id']=='belly':item['position'][2]=.51
        if item['id']=='scarf-tail':item['position'][2]=.64
    return parts

def paper_bird(prefix='bird'):
    parts=[node(prefix,'group'),node(prefix+'-body','polygon',color='#eee3c3',parent=prefix,points=[[-.6,0],[.3,.22],[.72,.05],[.15,-.25]],depth=.045,texture='paper',roughness=1),node(prefix+'-beak','polygon',color='#d78e55',parent=prefix,points=[[.55,.12],[.91,.04],[.57,-.04]],depth=.048,texture='paper'),node(prefix+'-tail','polygon',color='#d5c7ab',parent=prefix,points=[[-.42,.1],[-.98,.4],[-.82,-.16],[-.5,-.14]],depth=.03,texture='paper')]
    for side in (-1,1):
        tag=prefix+('-near' if side>0 else '-far')
        parts.append(node(tag,'group',(0,.1,side*.04),parent=prefix,tracks={'rx':keys((0,side*10),(.4,side*65),(.8,side*5),(1.2,side*70),(1.6,side*10),(2,side*65),(2.4,side*5),(2.8,side*70),(3.2,side*10),(3.6,side*65),(4,side*5),(4.4,side*70),(4.8,side*10),(5,side*30))}))
        parts.append(node(tag+'-wing','polygon',color='#bdc9d1' if side<0 else '#f8efda',parent=tag,points=[[-.3,0],[-.51,.95],[.14,.66],[.35,0]],depth=.03,roughness=1,texture='paper'))
    parts.append(node(prefix+'-eye','sphere',(.53,.14,.09),(.025,1,1),'#253948',parent=prefix,scale=[1,1,.3]))
    return parts

def town():
    parts=[node('town','group'),node('ground','plane',(0,-.08,0),(100,100,1),'#233748',rotation=[-90,0,0],roughness=1,texture='paper',cast_shadow=False)]
    for i,(x,z,h) in enumerate([(-3,-1,2.1),(-1.4,-2,1.6),(1,-2,2.6),(2.8,-1,1.9),(-4,1,1.4),(4,1,1.7)]):
        tag='house-'+str(i);color=['#355263','#546e77','#756b77'][i%3]
        parts.extend([node(tag,'group',(x,0,z),parent='town'),node(tag+'-wall','box',(0,h/2,0),(1.3,h,1.1),color,parent=tag,texture='paper',roughness=1),node(tag+'-roof','polygon',(0,h,-.65),(1,1,1),'#243341',parent=tag,points=[[-.8,0],[0,.65],[.8,0]],depth=1.3,texture='paper',roughness=1)])
        for j in range(4):parts.append(node(tag+'-window-'+str(j),'box',(-.32+(j%2)*.64,.55+(j//2)*.65,.562),(.22,.32,.025),'#f6c478',parent=tag,emissive='#ebae56',emissive_intensity=.6,cast_shadow=False))
        parts.append(node(tag+'-door','box',(0,.36,.562),(.25,.7,.03),'#182c3a',parent=tag))
    parts.append(node('moon','sphere',(-2,6,-7),(.7,1,1),'#f2dab2',emissive='#f2dab2',emissive_intensity=.25,cast_shadow=False))
    for i in range(30):parts.append(node('star-'+str(i),'sphere',((i*7.31)%16-8,3+(i*3.71)%4,-8),(.013+(i%3)*.004,1,1),'#eee2bd',emissive='#eee2bd',emissive_intensity=1,cast_shadow=False))
    return parts

def make(identifier,*,title,width,height,fps,seed):
    base={'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'studio','palette':{'background':'#e8e1ee','ink':'#322d49','accent':'#867bb4','secondary':'#ea946d'},'finishing':{'grain':.025,'vignette':.055},'sound':{'music':'lofi','gain':.09,'cues':[]}}
    if identifier=='paper-medallion':
        base.update(palette={'background':'#e4dfd3','ink':'#3e5958','accent':'#bb7965','secondary':'#637d72','paper':'#f1e6d0'},sound={'music':'ambient','gain':.055,'cues':[{'time':5,'type':'whoosh','gain':.09},{'time':12,'type':'chime','gain':.09}]})
        nodes=[node('rosette','group',motion={'axis':'rz','kind':'spin','amount':14,'speed':.1}),node('backdrop','plane',(0,0,-.5),(100,100,1),'$background',roughness=1,cast_shadow=False)]
        for i,(count,radius,width,reach,color) in enumerate([(48,.85,.11,.65,'$accent'),(96,1.55,.075,.49,'$paper'),(192,2.15,.04,.36,'$secondary')]):
            nodes.append(node('ring-'+str(i),'polygon',(0,0,i*.065),color=color,parent='rosette',points=[[-width,0],[-width*.7,reach*.7],[0,reach],[width*.7,reach*.7],[width,0],[0,-.14]],depth=.025,texture='paper',roughness=.95,clearcoat=0,repeat={'count':count,'layout':'radial','radius':radius,'wave':.02},tracks={'spread':keys((0,0),(4,0),(7,.26),(10,.26),(13,0),(18,0)), 'flip':keys((0,0),(6,0),(9,.45),(12,0),(18,0))}))
        nodes.append(node('center','sphere',(0,0,.2),(.23,1,1),'#d0b285',scale=[1,1,.2],roughness=.5,metalness=.45))
        base['scenes']=[scene('unfold',18,[layer('world','scene3d',{'nodes':nodes,'camera':{'position':[0,.2,12],'target':[0,0,0],'fov':34,'tracks':{'x':[{'time':0,'value':-.6},{'time':9,'value':0,'interpolation':'monotone'},{'time':18,'value':.6,'interpolation':'monotone'}]}},'environment_intensity':.2,'ambient':.6,'exposure':.9,'lights':[{'kind':'directional','position':[-4,5,7],'intensity':3,'shadow':True},{'kind':'directional','position':[4,-3,3],'color':'#c3d1c9','intensity':1}]},width=1,height=1),text('copy','Room to unfold.',y=.92,width=.8,height=.12,size=.052,font='serif',enter='none')])]
    elif identifier=='flowing-ink':
        base.update(style='ink',palette={'background':'#ece6d8','ink':'#2b403e','accent':'#b84e3b','secondary':'#6b877d','paper':'#f6efdf'},finishing={'grain':.035,'vignette':.04},sound={'music':'ambient','gain':.055,'cues':[{'time':10,'type':'chime','gain':.08}]})
        base['scenes']=[scene('wash',18,[layer('wash','fluid',{'resolution':'high','mask':'mountains','emitters':[{'x':x,'y':y,'color':color,'start':start,'end':end,'radius':.095,'strength':1.2,'direction':angle,'wander':.075} for x,y,color,start,end,angle in [(.25,.7,'$ink',0,8,-70),(.5,.73,'$secondary',1,10,-105),(.75,.68,'$ink',3,12,-120),(.3,.48,'$secondary',5,11,20)]]},width=1,height=.8,y=.58),layer('sun','shape',{'kind':'circle','fill':'$accent'},x=.72,y=.24,width=.07,height=.125,start=8,enter='fade',enter_duration=2),text('copy',title,y=.1,width=.8,height=.15,size=.065,font='serif',enter='fade',start=.3),text('close','Let the edges find their own way.',y=.93,width=.84,height=.12,size=.034,font='serif',start=10,enter='fade')])]
        ridge={'view_box':[-50,-50,100,100],'texture':'ink','paths':[{'d':'M-50 50 L-50 15 Q-45 12 -42 -6 L-38 -17 L-34 -7 L-30 -10 L-22 18 L-15 -12 L-9 -32 L-4 -19 L0 -21 L7 2 L13 -15 L20 -9 L28 16 L37 -18 L41 -27 L45 -8 L50 -4 L50 50Z','fill':'#b1bbb0'},{'d':'M-42 -6 L-36 2 L-30 19 M-9 -32 L-13 -8 L-8 4 M37 -18 L33 4 L40 14','stroke':'#708477','width':.4,'opacity':.6}]}
        ridge['fit']='stretch'
        layers=base['scenes'][0]['layers'];layers.insert(0,layer('distant-ridge','vector',ridge,width=1.15,height=.85,y=.6,opacity=.6,enter='fade',enter_duration=5))
        layers[1]['opacity']=.7;layers[1]['props']['pre_roll']=3
        layers[0]['enter']='none';layers[0]['tracks']={'opacity':keys((0,.12),(5,.6),(18,.6))}
        river={'view_box':[-50,-50,100,100],'paths':[{'d':'M4 -44 C-4 -24 23 -20 14 -6 C1 6 -23 13 -8 27 C5 36 19 34 16 50 L-4 50 C-5 40 -31 28 -20 14 C-14 2 15 -7 8 -19 C-1 -30 -2 -34 4 -44Z','fill':'$background'}]}
        layers.insert(2,layer('river','vector',river,width=.46,height=.67,x=.52,y=.62,opacity=.75,enter='fade',start=2,enter_duration=4))
        paths=[{'d':'M-20 46 Q-15 4 -9 -45','stroke':'$ink','width':2.2}]
        for j in range(7):
            y=-34+j*10;reach=9+j*2.5
            paths.append({'d':f'M{-12+reach} {y+8} Q-11 {y+2} {-13-reach} {y+9} Q-12 {y-4} -10 {y-7}Z','fill':'$ink'})
        layers.insert(3,layer('pine','vector',{'view_box':[-50,-50,100,100],'paths':paths,'texture':'ink'},x=.16,y=.74,width=.24,height=.4,enter='fade',start=3,enter_duration=4))
        layers.insert(4,layer('boat','vector',{'view_box':[-50,-50,100,100],'paths':[{'d':'M-42 5 Q0 26 42 5 L25 28 L-23 28Z','fill':'$ink'},{'d':'M-12 5 L-12 -29 L19 -5 L-12 -5','stroke':'$ink','width':1.8}]},x=.54,y=.77,width=.11,height=.09,enter='fade',start=5,enter_duration=2,tracks={'x':[{'time':0,'value':.54},{'time':6,'value':.57,'interpolation':'monotone'},{'time':13,'value':.58,'interpolation':'monotone'}]}))
    elif identifier=='living-mosaic':
        base['palette'].update(background='#112d38',ink='#f4dfb8',accent='#d97845',secondary='#438b91',muted='#b9a776',glow='#eadba9')
        base['scenes']=[scene('wall',15,[layer('wall','tiles',{'columns':80,'rows':48,'formation':'fish','material':'glass','color':'$accent','background_color':'$muted','gap':.16,'wave':.012,'flutter':.002,'night_color':'$background'},width=.94,height=.84,y=.47,tracks={'phase':keys((0,0),(2,0),(4,1),(8,1),(10,0),(15,0))},props_tracks={'travel_x':keys((0,0),(4,0),(6,.15),(8,0),(15,0),ease='linear'),'travel_y':keys((0,0),(4,0),(6,-.12),(8,0),(15,0)),'flip':keys((0,0),(10,0),(13,1),(15,1))}),text('copy','Even a still life has somewhere to go.',y=.93,width=.88,height=.1,size=.036,font='serif')],camera={'tracks':{'zoom':keys((0,1),(15,1.03),ease='linear')}})]
    elif identifier=='paper-flight':
        base['palette'].update(background='#1b2e3d',ink='#f2e3c3',accent='#dca677',secondary='#8dafbc')
        shots=[]
        for i,(name,camera,caption) in enumerate([('town',{'position':[8,5,11],'target':[0,1.5,-1],'tracks':{'x':keys((0,8),(5,5))}},'Every journey starts somewhere.'),('flight',{'position':[2.5,3.5,7],'target':[0,2.4,0],'fov':32,'tracks':{'x':keys((0,2.5),(5,-1))}},'Fold a little courage.'),('sky',{'position':[0,3,8],'target':[0,3,0],'tracks':{'z':keys((0,8),(5,6))}},'Then let it carry you.')]):
            nodes=town() if i<2 else [node('moon','sphere',(-3,4,-5),(.8,1,1),'#f2dab2',emissive='#f2dab2',emissive_intensity=.4)]
            bird=paper_bird();bird[0].update(position=[0,2.8,1],scale=[.9,.9,.9],tracks={'x':keys((0,-1.3),(5,1.2)),'y':keys((0,2.5),(2,2.9),(5,3.3)),'rz':keys((0,-5),(2,7),(5,0))})
            nodes+=bird
            shots.append(scene(name,5,[layer('world','scene3d',{'nodes':nodes,'camera':camera,'ambient':.35,'environment':False,'exposure':.9,'lights':[{'kind':'directional','position':[-3,7,5],'color':'#abc6dc','intensity':2,'shadow':True},{'kind':'directional','position':[5,2,-5],'color':'#e8ba81','intensity':1.5}]},width=1,height=1),text('copy',caption,y=.9,width=.9,height=.14,size=.045,font='serif',enter='fade',start=.4)],transition={'type':'crossfade' if i==2 else 'cut','duration':.6}))
        base['scenes']=shots
    elif identifier=='little-companion':
        shots=[]
        for i,(name,duration,camera,caption) in enumerate([('meet',5,{'position':[5,3,7],'target':[0,1.35,0],'fov':35,'tracks':{'x':keys((0,5),(5,2))}},'A little company.'),('hello',5,{'position':[1,2.8,5],'target':[0,1.75,0],'fov':36,'tracks':{'z':keys((0,5),(5,4))}},'A warmer welcome.'),('together',5,{'position':[-3,3.6,7],'target':[0,1.3,0],'fov':38},'Make room for a friend.')]):
            nodes=mascot();by_id={n['id']:n for n in nodes}
            by_id['right-arm-pivot']['tracks']={'rz':keys((0,0),(.7,100),(1.2,75),(1.7,115),(2.2,75),(2.7,110),(3.5,0),(5,0))}
            by_id['actor']['tracks']={'ry':keys((0,0),(5,-12 if i==2 else 8))}
            by_id['body']['tracks']={'sy':keys((0,1.2),(.8,1.215),(1.6,1.2),(2.4,1.21),(3.2,1.2),(5,1.2))}
            for eye in ('left-eye','right-eye'):
                by_id[eye]['tracks']={'sy':keys((0,1.25),(1.7,1.25),(1.78,.08),(1.9,1.25),(4,1.25),(4.08,.08),(4.2,1.25),(5,1.25))}
            if i==1:
                by_id['right-arm-pivot']['tracks']={'rz':keys((0,0),(1.1,72),(3.8,72),(4.6,0),(5,0))}
                by_id['head']['tracks']={'rz':keys((0,0),(1.2,-12),(3.8,-12),(5,0)),'ry':keys((0,0),(1.3,18),(3.5,18),(5,0))}
                bird=paper_bird('visitor');bird[0].update(position=[1.25,2.65,.4],scale=[.35,.35,.35],tracks={'x':keys((0,3),(1.2,1.1),(3.5,1.1),(5,3)),'y':keys((0,3.3),(1.2,2.2),(3.5,2.2),(5,3.8))})
                nodes+=bird;caption='Say hello to something new.'
                camera.update(position=[2.5,2.7,5],target=[.35,1.85,0],tracks={'x':keys((0,2.5),(5,1.5))})
            if i==2:
                by_id['actor']['position']=[-.58,0,0];by_id['actor']['tracks']={'x':keys((0,0),(1.1,-.58),(5,-.58)),'ry':keys((0,0),(1.2,18),(4,0),(5,0))}
                by_id['right-arm-pivot']['tracks']={'rz':keys((0,0),(1.3,40),(4,40),(5,0))}
                companion=mascot();companion=[n for n in companion if n['id'] not in ('floor','platform')]
                for item in companion:
                    item['id']='friend-'+item['id']
                    if item.get('parent'):item['parent']='friend-'+item['parent']
                    if item.get('color')=='#9babc1':item['color']='#c3b09d'
                friend={n['id']:n for n in companion};friend['friend-actor'].update(position=[1.3,.03035,0],scale=[.72,.72,.72],tracks={'x':keys((0,3),(1.8,.7),(5,.7)), 'ry':keys((0,-20),(2,-12),(5,0))})
                friend['friend-left-arm-pivot']['tracks']={'rz':keys((0,0),(1.8,-40),(4,-40),(5,0))}
                friend['friend-left-foot']['tracks']={'y':keys((0,.34),(.25,.46),(.5,.34),(.85,.46),(1.1,.34),(1.5,.46),(1.8,.34),(5,.34))}
                friend['friend-right-foot']['tracks']={'y':keys((0,.46),(.25,.34),(.55,.46),(.85,.34),(1.2,.46),(1.5,.34),(1.8,.34),(5,.34))}
                friend['friend-head']['tracks']={'rz':keys((0,8),(2,-4),(5,3))}
                nodes+=companion;camera.update(position=[3,3.2,8],target=[0,1.2,0],tracks={'z':keys((0,8),(5,7))})
            shots.append(scene(name,duration,[layer('world','scene3d',{'nodes':nodes,'camera':camera,'ambient':.45,'exposure':.9,'environment_intensity':.3,'fog':{'color':'$background','near':10,'far':25}},width=1,height=1),text('copy',caption,x=.5,y=.88,width=.85,height=.14,size=.055,mode='lines',enter='fade',start=.4)],transition={'type':'crossfade' if i==2 else 'cut','duration':.4}))
        base['scenes']=shots
    elif identifier=='precision-assembly':
        base['palette'].update(background='#19232b',ink='#f2ece0',accent='#d7a671',secondary='#688ea6')
        nodes=[node('root','group',rotation=[0,0,-18]),node('floor','plane',(0,-2.2,0),(100,100,1),'#19232b',rotation=[-90,0,0],cast_shadow=False)]
        for i in range(9):
            z=(i-4)*.35
            nodes.append(node('ring-'+str(i),'torus',(0,0,z),(1.12,.09,1),'#d7a671' if i%3==0 else '#c0cad0',parent='root',metalness=.85,roughness=.24,tracks={'z':keys((0,z),(1,z),(4,(i-4)*.8),(6,(i-4)*.8))}))
            nodes.append(node('rotor-'+str(i),'group',(0,0,z),parent='root',tracks={'rz':keys((0,i*7),(6,360+i*7),ease='linear'),'z':keys((0,z),(1,z),(4,(i-4)*.8),(6,(i-4)*.8))}))
            for j in range(8):
                a=j*math.tau/8
                nodes.append(node(f'blade-{i}-{j}','rounded_box',(math.sin(a)*.64,math.cos(a)*.64,0),(.13,.56,.035),'#7897a6',parent='rotor-'+str(i),rotation=[0,25,-j*45],metalness=.8,roughness=.32))
        nodes.append(node('shaft','cylinder',(0,0,0),(.15,5,.15),'#bcc6cd',parent='root',rotation=[90,0,0],metalness=.95,roughness=.2))
        base['scenes']=[scene('assembly',6,[layer('world','scene3d',{'nodes':nodes,'camera':{'position':[5,2.7,7],'target':[0,0,0],'tracks':{'x':keys((0,5),(6,3))}},'ambient':.7,'exposure':1.3},width=1,height=1),text('title',title,y=.12,size=.085,enter='fade'),text('caption','Each stage. One shared purpose.',y=.88,size=.035,enter='fade',start=.6)])]
    return AnimationComposition.model_validate(base)

