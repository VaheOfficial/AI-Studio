"""Authored landscape studies using reusable pressure strokes and tiled vector artwork."""
import math,random
from .recipes import layer,text,scene,keys
from ..schemas_animation import AnimationComposition

def stroke(points,width=.004,color='#253532',opacity=1,start=0,duration=1,style='ink',seed=1):
    return dict(points=points,width=width,color=color,opacity=opacity,start=start,duration=duration,style=style,seed=seed)

def ink(*,title,width,height,fps,seed):
    rng=random.Random(seed);strokes=[]
    # Separate mountain profiles place the darkest deposits on the ridge, thinning into mist.
    ridges=[([(.03,.54),(.14,.43),(.23,.47),(.33,.31),(.4,.4),(.49,.37),(.61,.53)],.64,.12,0),
            ([(.35,.58),(.47,.43),(.55,.48),(.68,.35),(.75,.46),(.86,.44),(.98,.57)],.68,.15,1.5),
            ([(.12,.63),(.25,.5),(.36,.25),(.405,.36),(.46,.32),(.53,.46),(.61,.43),(.72,.64)],.7,.75,3)]
    for ri,(ridge,base,density,begin) in enumerate(ridges):
        for j in range(65):
            x=ridge[0][0]+(ridge[-1][0]-ridge[0][0])*j/64
            for k in range(1,len(ridge)):
                if x<=ridge[k][0]:
                    a,b=ridge[k-1],ridge[k];u=(x-a[0])/(b[0]-a[0]);y=a[1]+(b[1]-a[1])*u;break
            drift=.022*math.sin(j*.9);y+=rng.uniform(-.006,.006)
            strokes.append(stroke([[x,y,.03],[x+drift*.1,y+(base-y)*.05,.9],[x+drift*.4,y+(base-y)*.22,1.2],[x+drift,y+(base-y)*.55,.8],[x+drift*.8,base+rng.uniform(-.02,.025),.015]],.085,'#2c3935',density*(.55+rng.random()*.4),begin+j*.033,2.2,'wash',ri*100+j))
        strokes.append(stroke([[x,y,.2+rng.random()*.7] for x,y in ridge],.006 if ri==2 else .0035,'#26312e',density,begin+.2,4,'dry',ri+30))
        if ri==2:
            for j in range(35):
                x=.33+rng.random()*.18;y=.32+abs(x-.36)*1.3+rng.uniform(0,.1)
                strokes.append(stroke([[x,y,.1],[x+.015,y+.04,.8],[x+.034,y+.085,.5],[x+.07,y+.14,.03]],.003,'#303b34',.25,5+j*.07,1.7,'dry',300+j))
    # Foreground island: horizontally dragged pigment, then branching pines.
    strokes.extend([stroke([[.065,.805,.05],[.19,.78,.8],[.3,.79,1],[.42,.82,.03]],.028,'#303a31',.7,10,2,'dry',41),stroke([[.11,.824,.03],[.27,.808,.8],[.43,.826,.03]],.012,'#414b3e',.3,10.3,2,'wash',42)])
    for ti,(x,y,h) in enumerate([(.205,.79,.19),(.28,.79,.24),(.335,.797,.16)]):
        strokes.append(stroke([[x,y,.9],[x-.006,y-h*.4,.7],[x+.012,y-h*.74,.5],[x+.005,y-h,.05]],.0045,'#24302c',1,11+ti*.7,1.5,'dry',ti+70))
        for j in range(7):
            yy=y-h*(.26+j*.102)+rng.uniform(-.007,.007);xx=x+.007*math.sin(j);reach=h*(.12+.22*(1-j/8))*rng.uniform(.8,1.15)
            for side in (-1,1):
                strokes.append(stroke([[xx,yy,.45],[xx+side*reach*.55,yy-.01,.75],[xx+side*reach,yy+.008,.1]],.004,'#26322c',.85,11.8+ti*.7+j*.09,.75,'dry',ti*100+j+80))
                for n in range(2):
                    cx=xx+side*reach*(.3+n*.4);cy=yy-.009+rng.uniform(-.006,.006)
                    strokes.append(stroke([[cx-.017,cy,.05],[cx-.006,cy-.009,.8],[cx+.006,cy-.006,1],[cx+.019,cy+.001,.02]],.014,'#26352d',.95,12+ti*.7+j*.08,.7,'dry',ti*100+j*3+n+90))
    # Quiet water strokes keep the foreground open rather than filling the frame.
    ripples=[]
    for j in range(26):
        x=.46+rng.random()*.42;y=.7+rng.random()*.17;length=.01+rng.random()*.06
        ripples.append(stroke([[x,y,.05],[x+length*.4,y-.001,.7],[x+length,y,.02]],.0012,'#718075',.45,14+j*.11,.7,'dry',j+530))
    layers=[layer('mountains','brush',{'strokes':strokes[:233],'grain':.72},width=1,height=1,enter='none'),layer('pines','brush',{'strokes':strokes[233:],'grain':.6},width=1,height=1,enter='none'),layer('water','brush',{'strokes':ripples,'grain':.5},width=1,height=1,enter='none')]
    sun={'view_box':[0,0,100,100],'texture':'ink','paths':[{'d':'M50 4 C78 2 98 26 96 51 C96 76 77 97 49 96 C22 98 3 76 4 49 C2 23 25 2 50 4Z','fill':'#a74835'}]}
    layers.append(layer('sun','vector',sun,x=.76,y=.23,width=.057,height=.102,start=16,enter='fade',enter_duration=2.5))
    bird={'view_box':[0,0,100,100],'paths':[{'d':'M7 55 Q27 32 49 54 Q72 34 94 44','stroke':'#39453d','width':3}]}
    for i in range(3):layers.append(layer('bird-'+str(i),'vector',bird,x=.6+i*.028,y=.16+i*.015,width=.025,height=.032,start=18+i*.1,enter='fade',tracks={'x':keys((0,.58+i*.028),(5,.65+i*.028)),'y':keys((0,.19+i*.015),(5,.145+i*.015))}))
    boat={'view_box':[0,0,100,100],'texture':'ink','paths':[{'d':'M4 58Q48 76 96 53L75 72L29 78Z','fill':'#344039'},{'d':'M54 58L49 26M47 42L37 58M49 29L68 43','stroke':'#344039','width':3},{'d':'M44 18Q48 8 54 17L54 25L45 26Z','fill':'#344039'}]}
    layers.append(layer('boat','vector',boat,x=.68,y=.77,width=.065,height=.075,start=15,enter='fade',enter_duration=2,tracks={'x':keys((0,.67),(9,.69))}))
    layers.append(text('signature','After the rain',x=.81,y=.89,width=.3,height=.065,size=.028,font='serif',color='#626a5c',start=19,enter='fade',enter_duration=2))
    layers.append(layer('seal','vector',{'view_box':[0,0,100,100],'paths':[{'d':'M8 8L91 5L94 92L5 95Z','fill':'#a64a37'},{'d':'M25 24L70 24L70 43L35 43L35 72L75 72 M52 17L52 83','stroke':'#e9e4d5','width':6}]},x=.91,y=.89,width=.018,height=.032,start=20,enter='fade'))
    return AnimationComposition.model_validate({'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'ink','palette':{'background':'#ede9dc','ink':'#283730'},'finishing':{'grain':.055,'vignette':.025},'sound':{'music':'ambient','gain':.025,'cues':[{'time':16.3,'type':'chime','gain':.025}]},'scenes':[scene('painting',24,layers)]})

def art(id,paths,**kw):
    return layer(id,'vector',{'view_box':[0,0,100,100],'paths':paths,'texture':'mosaic','tile_size':kw.pop('tile_size',.014),'tile_gap':.12,'tile_flow':kw.pop('tile_flow','grid')},enter='none',**kw)

def mosaic(*,title,width,height,fps,seed):
    navy='#102d48';gold='#b89855';water='#3a9299';cream='#ddd5a5';coral='#d7773c'
    layers=[art('wall',[{'d':'M0 0H100V100H0Z','fill':navy}],width=1,height=1,tile_size=.013),art('arch',[{'d':'M8 100V39C8 -5 92 -5 92 39V100Z','fill':gold},{'d':'M12 100V39C12 0 88 0 88 39V100Z','fill':'#234d65'},{'d':'M16 100V40C16 6 84 6 84 40V100Z','fill':'#186778'}],width=.95,height=1,y=.49,tile_flow='radial',tile_size=.012)]
    # A richly tiled window world, with the moon and water bowl sharing circular bands.
    layers.append(art('moon',[{'d':'M50 4A46 46 0 1 1 49.9 4Z','fill':cream},{'d':'M37 18Q55 3 75 19Q48 12 30 46Q22 32 37 18Z','fill':'#eee6c5'}],x=.68,y=.245,width=.165,height=.165,tile_flow='radial',start=1,enter_duration=1.5,opacity=.9))
    for i in range(24):
        x=.22+(i*37%61)/100;y=.12+(i*17%27)/100
        if (x-.68)**2+(y-.245)**2<.015:continue
        layers.append(layer('star-'+str(i),'shape',{'kind':'circle','fill':'#e2d39c'},x=x,y=y,width=.0035,height=.0035,start=2+i*.025,enter='fade',opacity=.55))
    layers.append(art('sill',[{'d':'M0 10H100V100H0Z','fill':'#153a4e'},{'d':'M0 10H100V28H0Z','fill':gold},{'d':'M0 34H100V41H0Z','fill':'#407780'},{'d':'M0 78H100V85H0Z','fill':gold}],width=1,height=.2,y=.9,tile_size=.035))
    layers.append(art('bowl',[{'d':'M25 10Q50 5 75 10L70 23C111 43 100 89 75 96Q50 108 25 96C0 89 -11 43 30 23Z','fill':cream},{'d':'M28 15Q50 12 72 15L64 27C101 43 92 84 72 91Q50 101 28 91C8 84 -1 43 36 27Z','fill':water},{'d':'M31 21Q50 25 69 21L66 27Q48 32 34 27Z','fill':'#b9d6bf'},{'d':'M11 60Q32 48 53 60T92 57L91 80Q51 112 16 86Z','fill':'#297980'},{'d':'M19 43Q9 65 22 79','stroke':'#bad5bc','width':2},{'d':'M27 10Q50 3 74 10Q52 17 27 10Z','stroke':'#faf0c6','width':1.8}],x=.5,y=.61,width=.61,height=.59,tile_flow='radial',tile_size=.014))
    # Individual fins pivot while the body follows a loop through the bowl.
    layers.append(layer('fish-rig','group',x=.5,y=.625,width=.285,height=.16,tracks={'x':keys((0,.45),(5,.58),(10,.54),(15,.42),(20,.5),(24,.5)),'y':keys((0,.64),(5,.6),(10,.67),(15,.63),(20,.6),(24,.625)),'rotation':keys((0,-4),(5,7),(10,-6),(15,3),(24,-4))}))
    layers.append(art('tail',[{'d':'M96 50Q47 7 2 4Q27 50 1 95Q54 90 96 50Z','fill':coral},{'d':'M82 50L13 19 M85 51L20 48 M80 53L15 81','stroke':'#f0b75b','width':2}],parent='fish-rig',x=.1,y=.5,width=.48,height=1,anchor_x=.9,tracks={'rotation':keys((0,-9),(1,12),(2,-9),(3,12),(4,-9),(5,12),(6,-9),(7,12),(8,-9),(9,12),(10,-9),(11,12),(12,-9),(13,12),(14,-9),(15,12),(16,-9),(17,12),(18,-9),(19,12),(20,-9),(21,12),(22,-9),(23,12),(24,-9))},tile_size=.035))
    paths=[{'d':'M4 50Q24 3 61 17Q86 19 98 49Q83 82 53 84Q23 94 4 50Z','fill':'#df8942'},{'d':'M12 49Q36 17 61 23Q82 27 88 41Q48 30 19 58Z','fill':'#edb05b'},{'d':'M42 21Q32 0 61 2L67 21Z','fill':'#b55430'},{'d':'M44 77L64 96L70 75Z','fill':'#b55430'},{'d':'M82 33A8 8 0 1 1 81.9 33Z','fill':'#f5e7ba'},{'d':'M83 37A4 4 0 1 1 82.9 37Z','fill':'#182c32'},{'d':'M93 53L99 51','stroke':'#7b3e25','width':2}]
    for row in range(3):
        for col in range(5):
            x=24+col*9+(row%2)*4;y=36+row*12
            paths.append({'d':f'M{x} {y}q9 -5 9 4','stroke':'#b66835','width':1.5})
    layers.append(art('fish-body',paths,parent='fish-rig',x=.59,y=.5,width=.86,height=1,tile_flow='radial',tile_size=.031))
    for item in layers:
        if item['id'] in ('fish-body','tail'):item['props']['fit']='stretch'
        if item['id']=='fish-body':item['props'].update(tile_flow='grid',tile_size=.055)
        if item['id']=='moon':item['props']['tile_size']=.055
        if item['id']=='tail':item.update(x=.34,width=.42)
        if item['id']=='fish-rig':item['tracks']={'x':keys((0,.45),(5,.58),(9,.48),(12,.52),(14,.59),(17,.48),(20,.5),(24,.5)),'y':keys((0,.64),(5,.6),(9,.65),(12,.36),(14,.265),(17,.57),(19,.66),(24,.625)),'rotation':keys((0,-4),(5,7),(9,-8),(11,-24),(14,8),(17,24),(19,-7),(24,-4))}
    for i in range(7):layers.append(art('bubble-'+str(i),[{'d':'M50 12A38 38 0 1 1 49.9 12Z','stroke':'#c1d9bd','width':6}],x=.58+(i%3)*.017,y=.62-i*.037,width=.01+i*.001,height=.01+i*.001,tile_size=.065,tracks={'y':keys((0,.63-i*.037),(12,.49-i*.021),(24,.63-i*.037))},opacity=.5))
    # Curved grasses provide a foreground silhouette and a softer organic counterpoint.
    for i in range(6):
        side=-1 if i<3 else 1;x=.5+side*(.28+(i%3)*.037)
        layers.append(art('reed-'+str(i),[{'d':'M45 99C55 62 4 36 31 2C47 39 71 54 51 99Z','fill':'#4f8071'},{'d':'M48 100Q58 56 91 31Q90 73 48 100Z','fill':'#779274'},{'d':'M48 96Q24 71 7 63Q8 92 48 96Z','fill':'#b2a56b'}],x=x,y=.78,width=.12,height=.25,rotation=-side*9,tile_size=.027))
    return AnimationComposition.model_validate({'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'mosaic','palette':{'background':'#0c2436','ink':cream},'finishing':{'grain':.025,'vignette':.17},'sound':{'music':'ambient','gain':.035,'cues':[]},'scenes':[scene('aquarium',24,layers,camera={'tracks':{'zoom':keys((0,1.08),(8,1.02),(20,1),(24,1))}})]})
