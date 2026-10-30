"""An articulated tessera scene with independently directed artwork and lighting."""
import math,random
from .recipes import layer,scene,keys
from ..schemas_animation import AnimationComposition

GROUT='#172322'
def path(d,fill=None,stroke=None,width=1):
    v={'d':d}
    if fill:v['fill']=fill
    if stroke:v.update(stroke=stroke,width=width)
    return v
def circle(x,y,r,color):return path(f'M{x-r} {y}a{r} {r} 0 1 0 {r*2} 0a{r} {r} 0 1 0 {-r*2} 0Z',color)
def tiled(id,paths,*,size=.013,flow='grid',origin=(.5,.5),**kw):
    return layer(id,'vector',{'view_box':[0,0,1000,1000],'paths':paths,'texture':'mosaic','fit':'stretch','tile_size':size,'tile_gap':.085,'tile_flow':flow,'tile_origin':list(origin),'tile_grout':GROUT,'tile_relief':.65,'tile_variation':.32,'tile_outlines':True},width=kw.pop('width',1),height=kw.pop('height',1),**kw)
def plain(id,paths,**kw):return layer(id,'vector',{'view_box':[0,0,1000,1000],'paths':paths,'fit':'stretch'},width=kw.pop('width',1),height=kw.pop('height',1),**kw)
def arch():return 'M190 690V390A310 310 0 0 1 810 390V690Z'
def fin_rays(dorsal=False):
    colors=['#de6824','#f09432','#f8b847','#fbd577','#f9e7ab'];pieces={c:[] for c in colors}
    def ray(x,y,angle,length,width):
        ux,uy=math.cos(angle),math.sin(angle);nx,ny=-uy,ux
        for j in range(6):
            a=5+j*length/6;b=a+length/6-5;half=width*(.65+j*.07)/2
            pts=[(x+ux*r+nx*n,y+uy*r+ny*n) for r,n in [(a,-half),(b,-half),(b,half),(a,half)]]
            pieces[colors[min(4,j)]].append('M'+'L'.join(f'{px:.2f} {py:.2f}' for px,py in pts)+'Z')
    if dorsal:
        for i in range(12):ray(408+i*24,314-54*math.sin(i/11*math.pi),-math.pi*.67,90+50*math.sin(i/11*math.pi),15)
        for i in range(5):ray(450+i*28,702,math.pi*.42,62,12)
    else:
        for side in [-1,1]:
            for j in range(10):ray(300,500,side*math.radians(113+j*6.1),315+25*math.sin(j/9*math.pi),14)
    return [path(' '.join(ds),c,GROUT,1.8) for c,ds in pieces.items()]

def ornament_paths():
    """Cut individual annular tesserae for a repeating fan-and-flower border."""
    colors=['#087b72','#269c87','#16485f','#315788','#e9d6a5','#c77635','#102e42'];pieces={c:[] for c in colors};rng=random.Random(46)
    for row in range(4):
        for col in range(10):
            cx=168+col*72+(row%2)*36;cy=812+row*29
            for band,r in enumerate([12,21,30,38]):
                count=max(5,round(math.pi*r/7))
                for j in range(count):
                    a=math.pi+j*math.pi/count+.024;b=math.pi+(j+1)*math.pi/count-.024;ri=r-6
                    pts=[(cx+rr*math.cos(aa),cy+rr*math.sin(aa)) for rr,aa in [(r,a),(r,b),(ri,b),(ri,a)]]
                    if any(not 155<x<845 or not 793<y<899 for x,y in pts):continue
                    color=colors[(band+row)%4];d='M'+'L'.join(f'{x+rng.uniform(-.35,.35):.2f} {y+rng.uniform(-.35,.35):.2f}' for x,y in pts)+'Z';pieces[color].append(d)
            if 177<cx<820 and 801<cy<886:
                for dx,dy in [(0,-7),(-6,0),(6,0),(0,7)]:pieces[colors[4 if (row+col)%3 else 5]].append(f'M{cx+dx} {cy+dy-3}l3 3l-3 3l-3 -3Z')
    return [path(' '.join(items[start:start+80]),c) for c,items in pieces.items() for start in range(0,len(items),80)]

def architecture(prefix,night=False):
    cream='#172773' if night else '#dfd0a2';trim='#bfc4c2' if night else '#ebe0b7';shade='#151b4f' if night else '#bfae7d'
    out=[tiled(prefix+'-wall',[path('M0 0H1000V1000H0Z',cream)]),tiled(prefix+'-frame',[path('M44 40H956V962H44Z',trim,GROUT,5),path('M65 61H935V940H65Z',shade,GROUT,4),path('M80 77H920V923H80Z',cream,GROUT,3)])]
    # The arch border has its own masonry flow, independent from the sky grid.
    out.append(tiled(prefix+'-arch',[path('M145 712V390A355 355 0 0 1 855 390V712Z',shade),path('M155 700V390A345 345 0 0 1 845 390V700Z',trim),path('M168 695V390A332 332 0 0 1 832 390V695Z',shade),path('M176 695V390A324 324 0 0 1 824 390V695Z',trim)],flow='arch',origin=(.5,.39),size=.013))
    sky=[path(arch(),'#0c194c' if night else '#81c4b3')]
    for j in range(48):
        y=80+j*610/48;u=j/47;x=500-math.sqrt(max(0,310**2-(min(y,390)-390)**2));a,b=((10,20,90),(15,32,135)) if night else ((25,137,130),(245,215,138));c='#'+''.join(f'{round(a[k]+(b[k]-a[k])*u):02x}' for k in range(3))
        sky.append(path(f'M{x:.2f} {y:.2f}H{1000-x:.2f}V{y+13.1:.2f}H{x:.2f}Z',c))
    if night:
        rng=random.Random(29)
        for shade in ['#7e91b2','#b7c4cc','#455889']:
            fragments=[]
            for _ in range(80):
                x=rng.uniform(205,795);y=rng.uniform(120,680)
                if y<390 and (x-500)**2+(y-390)**2>300**2:continue
                fragments.append(f'M{x:.1f} {y:.1f}h10v7h-10Z')
            sky.append(path(' '.join(fragments),shade))
    out.append(tiled(prefix+'-sky',sky,size=.012))
    skyline=[path('M190 689V637L209 618L229 630L262 597L288 625L309 611L338 642L360 627L386 641L414 612L437 637L462 616L485 638L510 608L533 640L561 617L583 637L610 620L637 638L664 615L690 639V524L716 482L738 522V630L759 619L778 636L810 627V690Z','#07152b' if night else '#196a5a')]
    for j in range(26):
        x=195+j*23;skyline.append(path(f'M{x} 656h8v10h-8Z','#18244d' if night else '#99ad6d'))
    skyline.extend([path('M687 627V533Q689 484 716 480Q742 486 746 533V631',None,'#1b2759' if night else trim,12),path('M689 542L716 506L742 542',None,GROUT,7)])
    out.append(tiled(prefix+'-city',skyline,size=.009))
    sill=[path('M143 687H857V736H143Z',trim),path('M155 704H845V716H155Z',shade),path('M168 736H831L849 751H151Z',cream),path('M127 767H873V925H127Z',trim),path('M139 779H861V913H139Z','#d9b337'),path('M153 791H847V901H153Z','#062f40')]
    out.append(tiled(prefix+'-sill',sill,size=.0105))
    pieces=ornament_paths();batch=[];size=0
    for piece in pieces:
        if size+len(piece['d'])>55000:
            out.append(plain(prefix+'-inlay-'+str(len(out)),batch));batch=[];size=0
        batch.append(piece);size+=len(piece['d'])
    if batch:out.append(plain(prefix+'-inlay-last',batch))
    border=[]
    for j in range(19):
        x=j*55; border.extend([path(f'M{x-26} 8Q{x} 57 {x+26} 8',None,'#168f7b',14),path(f'M{x-25} 993Q{x} 944 {x+25} 993',None,'#168f7b',14)])
    out.append(tiled(prefix+'-border',border,size=.008))
    return out

def make(*,title,width,height,fps,seed):
    rng=random.Random(seed);layers=[]
    # All architecture shares a single transform and a reversible day/night envelope.
    layers.append(layer('world','group',width=min(1,height/width),height=min(1,width/height),tracks={
        'x':keys((0,.5),(10,.5),(14,.55),(20,.44),(25,.53),(29,.53),(35,.5),(48,.5),(50,.5),(51,.43),(52,.46),(53,.40),(54,.43),(55,.5),(80,.5)),
        'scale':keys((0,1),(10,1),(14,1.5),(20,1.17),(25,2.3),(29,2.3),(35,1.4),(41,1.1),(46,1.45),(48,1.3),(49,1.35),(50,1.3),(51,1.6),(52,1.75),(53,1.8),(54,1.65),(55,1.4),(56,1.3),(57,1.22),(58,1.05),(60,.92),(63,1.1),(69,1.4),(73,1),(80,1)),
        'y':keys((0,.5),(10,.5),(14,.52),(20,.65),(25,.40),(29,.40),(35,.508),(41,.558),(46,.4),(48,.5),(49,.55),(50,.61),(51,.71),(52,.84),(53,.92),(54,.83),(55,.58),(56,.57),(57,.58),(58,.52),(60,.5),(63,.49),(69,.4),(73,.5),(80,.5))}))

    for night in [False,True]:
        prefix='night' if night else 'day';opacity=keys((0,0),(6.5,0),(9,1),(14,1),(18,0),(80,0)) if not night else keys((0,0),(14,0),(19,1),(38,1),(42,.3),(48,1),(70,1),(74,.28),(80,.28))
        layers.append(layer(prefix,'group',parent='world',width=1,height=1,tracks={'opacity':opacity}))
        for item in architecture(prefix,night):item['parent']=prefix;layers.append(item)
    # Sun and moon remain separate tile objects so the camera can travel past them.
    sun=tiled('sun',[circle(500,500,470,'#d46b21'),circle(500,500,350,'#eeb449')],width=.1,height=.1,x=.285,y=.29,size=.075,flow='radial',parent='world',tracks={'x':keys((0,.285),(10,.285),(16,.25),(80,.25)),'y':keys((0,.29),(10,.29),(16,.67),(80,.67)),'opacity':keys((0,0),(7,0),(9,1),(15,1),(18,0),(80,0))});layers.append(sun)
    moonlight=keys((0,0),(15,0),(19,1),(38,1),(41,.12),(49,1),(70,1),(74,0),(80,0))
    layers.append(tiled('moon-halo',[circle(500,500,490,'#19265c'),circle(500,500,415,'#435684'),circle(500,500,340,'#8397ae'),circle(500,500,260,'#cccfae')],width=.245,height=.245,x=.637,y=.15,size=.046,flow='radial',parent='world',tracks={'opacity':moonlight}))
    layers.append(tiled('moon',[circle(500,500,475,'#fff0b3'),circle(450,430,365,'#f9dc73')],width=.115,height=.115,x=.637,y=.15,size=.065,flow='radial',parent='world',tracks={'opacity':moonlight},shadow={'color':'#e4bf54','blur':.025,'x':0,'y':0}))
    # A dark outline separates glass from the scene. Water rings share a central origin.
    glass='M235 105Q500 34 765 105L795 200C1040 480 891 936 500 950C109 936 -40 480 205 200Z'
    bowl=[path(glass,'#b8d9ce',GROUT,13),path('M232 252Q500 226 768 252C939 492 823 895 500 914C177 895 61 492 232 252Z','#6ebdb8'),path('M250 294Q500 275 750 294C891 520 786 855 500 878C214 855 109 520 250 294Z','#4eaaa5')]
    layers.append(tiled('bowl',bowl,width=.385,height=.363,x=.5,y=.51,size=.025,flow='radial',origin=(.5,.53),parent='world',props_tracks={'tile_assembly':keys((0,0),(3.2,0),(6.3,.66),(8.5,1),(80,1))}))
    rim=[path('M160 101Q500 -7 840 101L801 153Q500 66 199 153Z','#b9cdc4',GROUT,10),path('M204 109Q500 32 796 109Q500 200 204 109Z','#eee1b9',GROUT,6),path('M248 120Q500 83 752 120Q500 166 248 120Z','#759b98',GROUT,4),path('M212 227Q500 264 788 227',None,'#d5ebe1',8),path('M210 265Q94 521 244 737',None,'#d9ede0',14),path('M772 315Q836 419 810 530',None,'#c3e6d6',8)]
    layers.append(tiled('glass-rim',rim,width=.385,height=.363,x=.5,y=.51,size=.023,flow='grid',parent='world',tracks={'opacity':keys((0,0),(6,0),(8.5,1),(80,1))}))
    layers.append(tiled('deep-water',[path('M232 252Q500 226 768 252C939 492 823 895 500 914C177 895 61 492 232 252Z','#142855')],width=.385,height=.363,x=.5,y=.51,size=.025,flow='radial',origin=(.5,.53),parent='world',tracks={'opacity':keys((0,0),(69,0),(74,1),(80,1))}))
    reflections=[]
    for j in range(28):
        a=j*2.4;r=70+j*8;x=500+r*math.cos(a);y=500+r*math.sin(a);reflections.append(path(f'M{x:.1f} {y:.1f}h24v16h-24Z','#ffe4a7'))
    layers.append(plain('moon-reflection',reflections,width=.14,height=.14,x=.441,y=.54,parent='world',blend='lighter',tracks={'opacity':keys((0,0),(23,0),(27,.65),(31,.3),(36,0),(80,0))},shadow={'color':'#ffe9ad','blur':.017,'x':0,'y':0},motion={'type':'spin','speed':.018,'amount':0}))
    # An articulated fish. Every tile belongs to anatomy, rather than sampling a flat sprite.
    layers.append(layer('fish','group',parent='world',width=.175,height=.145,x=.5,y=.52,tracks={
        'x':keys((0,.5),(4,.5),(8,.56),(11,.57),(14,.46),(18,.48),(21,.58),(27,.565),(33,.45),(39,.45),(44,.54),(48,.53),(49,.43),(50,.43),(51,.52),(52,.50),(53,.51),(54,.50),(55,.50),(56,.47),(57,.48),(60,.49),(64,.47),(70,.52),(80,.5)),
        'y':keys((0,.49),(4,.49),(10,.53),(15,.51),(20,.56),(28,.53),(35,.575),(40,.595),(45,.625),(48,.59),(49,.51),(50,.42),(51,.30),(52,.23),(53,.22),(54,.275),(55,.375),(56,.56),(57,.645),(58,.60),(60,.555),(70,.57),(80,.57)),
        'scale':keys((0,1.8),(3,1.8),(7,1),(44,1),(49,1.08),(55,1),(80,1)),
        'scale_x':keys((0,1),(11.65,1),(12,-1),(17.65,-1),(18,1),(24.65,1),(25,-1),(40.65,-1),(41,1),(56.65,1),(57,-1),(80,-1)),
        'rotation':keys((0,0),(40,0),(45,25),(49,0),(50,-65),(51,-55),(52,-35),(53,-35),(54,35),(55,70),(56,105),(57,0),(80,0))}))

    layers.append(plain('dorsal',fin_rays(True),parent='fish',motion={'type':'wiggle','speed':.85,'amount':.1},tracks={'opacity':keys((0,0),(1,0),(3.5,1),(80,1))}))
    layers.append(plain('tail',fin_rays(),parent='fish',anchor_x=.3,anchor_y=.5,x=.3,y=.5,motion={'type':'wiggle','speed':1.8,'amount':.3},tracks={'opacity':keys((0,0),(1.8,0),(4.5,1),(80,1))}))
    body=[path('M273 501C340 164 687 177 853 361Q999 490 843 628C678 810 358 789 273 501Z','#ec691b',GROUT,14),path('M305 511Q462 658 842 542Q710 798 432 688Z','#f8bf42'),path('M355 413Q512 196 753 303Q627 233 477 443Z','#f18c20'),path('M758 342Q946 429 899 540Q853 471 758 450Z','#d35216')]
    for row in range(5):
        for col in range(7):
            x=365+col*57+(row%2)*22;y=345+row*62
            if x<790:body.append(path(f'M{x} {y}q31 -25 44 14',None,'#ffcd46',9))
    for shade,count in [('#ffdc6e',46),('#fff0ab',12)]:
        flecks=[]
        for j in range(count):
            a=rng.uniform(0,math.tau);r=math.sqrt(rng.random());x=580+230*r*math.cos(a);y=510+180*r*math.sin(a);flecks.append(f'M{x:.1f} {y:.1f}h22v19h-22Z')
        body.append(path(' '.join(flecks),shade))
    layers.append(tiled('fish-body',body,parent='fish',size=.029,flow='radial',origin=(.787,.437),props_tracks={'tile_assembly':keys((0,0),(3.5,1),(80,1))}))
    eye=[circle(787,437,58,'#eb9c51'),circle(787,437,43,'#f4e6c6'),circle(787,437,33,'#23384b'),circle(777,425,10,'#fff4c8'),circle(797,449,5,'#fff5d3'),path('M927 503l-43 8',None,'#784723',7)]
    layers.append(tiled('eye',eye,parent='fish',size=.023,flow='radial',origin=(.787,.437),props_tracks={'tile_assembly':keys((0,0),(.8,1),(80,1))}))
    layers.append(plain('pectoral-fin',[path('M530 535L588 563L572 573Z','#fbd16c','#a46b31',2),path('M525 540L562 594L547 592Z','#ffdb82','#a46b31',2),path('M519 542L531 599L518 588Z','#f5b94d','#a46b31',2)],parent='fish',motion={'type':'wiggle','speed':2.2,'amount':.2},tracks={'opacity':keys((0,0),(1,0),(4,1),(80,1))}))

    # Landing droplets follow sampled ballistic arcs and retain deterministic seeking.
    for j in range(48):
        vx=rng.uniform(-.1,.1);vy=rng.uniform(-.22,-.1);life=rng.uniform(1.3,2.1);times=[i*life/6 for i in range(7)]
        layers.append(layer('splash-'+str(j),'shape',{'kind':'star' if j%5==0 else 'rect','points':4,'inner':.2,'fill':'#effffb' if j%3 else '#9fdcec','corners':0},parent='world',start=55.45+j*.008,duration=life,width=.004+j%3*.0015,height=.006,x=.5,y=.375,shadow={'color':'#adebe5','blur':.008,'x':0,'y':0},tracks={'x':keys(*[(t,.5+vx*t) for t in times],ease='linear'),'y':keys(*[(t,.375+vy*t+.115*t*t) for t in times],ease='linear'),'rotation':keys((0,j*37),(life,j*37+180)),'opacity':keys((0,0),(.08,1),(life*.6,1),(life,0))}))
    layers.append(layer('splash-mist','particles',{'count':150,'pattern':'burst','color':'#cefff5','size':.0017,'speed':.3,'depth':.2},parent='world',start=55.45,duration=2,width=.2,height=.2,x=.5,y=.37,blend='lighter',shadow={'color':'#a8e8ef','blur':.005,'x':0,'y':0},tracks={'spread':keys((0,0),(.5,1),(2,1.2)),'y':keys((0,.37),(.65,.29),(2,.38)),'opacity':keys((0,0),(.12,1),(.7,.8),(2,0))}))
    # Floating gold tesserae are individually drawn, with a shared late-scene reveal.
    sparks=[]
    for i in range(56):
        x=rng.uniform(220,790);y=rng.uniform(100,440);sparks.append(path(f'M{x:.1f} {y:.1f}h{rng.uniform(4,10):.1f}v7h-7Z','#ffe291'))
    layers.append(plain('released-light',sparks,parent='world',tracks={'opacity':keys((0,0),(56,0),(60,1),(66,.7),(70,.9),(73,0),(80,0))},shadow={'color':'#ffd777','blur':.012,'x':0,'y':0},motion={'type':'float','speed':.07,'amount':.018}))
    orbit=[]
    for j in range(35):
        a=j*math.tau/35;x=500+415*math.cos(a);y=500+420*math.sin(a);orbit.append(path(f'M{x-9:.2f} {y:.2f}q14 -18 34 -8q-14 18 -34 8Z','#f0c44b'))
    layers.append(plain('water-light',orbit,parent='world',tracks={'opacity':keys((0,0),(60,0),(65,.8),(73,1),(80,1))},motion={'type':'spin','speed':.018,'amount':0},x=.5,y=.53,width=.36,height=.31))
    constellation=[path('M330 242Q462 112 596 190Q667 224 595 270Q462 342 330 242L265 170Q241 216 268 284Z',None,'#d5b96b',3),circle(582,216,10,'#ffe9a3'),path('M631 224l39 -11l-10 18l15 13l-40 -3',None,'#e7c66a',3),path('M425 161Q450 109 485 158M452 295L474 322L495 287',None,'#d5b96b',3)]
    layers.append(tiled('constellation',constellation,parent='world',size=.008,tracks={'opacity':keys((0,0),(70,0),(74,1),(80,1))},shadow={'color':'#ceb252','blur':.009,'x':0,'y':0}))
    for item in layers:
        if item['id'] in ('world','fish'):
            for name,track in item['tracks'].items():
                if name!='scale_x':
                    for frame in track:frame['interpolation']='monotone'
        if item['id']=='bowl':item['props']['tile_reveal']='center'
        if item['id']=='fish-body':
            item['props']['tile_reveal']='right';item['props_tracks']['tile_assembly']=keys((0,0),(4.5,1),(80,1))
    return AnimationComposition.model_validate({'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'mosaic','palette':{'background':'#080908'},'finishing':{'grain':.012,'vignette':.03},'sound':{'music':'ambient','gain':.025,'cues':[{'time':3,'type':'chime','gain':.035},{'time':18,'type':'chime','gain':.025},{'time':51,'type':'whoosh','gain':.025},{'time':73,'type':'chime','gain':.035}]},'scenes':[scene('goldfish',80,layers)]})

