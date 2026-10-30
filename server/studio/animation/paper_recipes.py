"""Layered illustrated cutouts with authored joints and a continuous story motif."""
import copy
from .recipes import layer,text,scene,keys
from ..schemas_animation import AnimationComposition

def art(id,paths,**kwargs):
    return layer(id,'vector',{'view_box':[-50,-50,100,100],'paths':paths,'texture':'paper'},**kwargs)

def girl(prefix='girl',**kwargs):
    joint=layer(prefix,'group',{},width=.34,height=.62,x=.35,y=.55,**kwargs)
    parts=[joint,
      art(prefix+'-hair',[{'d':'M-34 5 C-42 -18 -33 -43 -10 -46 C20 -51 42 -30 35 10 L25 26 L-30 25Z','fill':'#292c37'}],parent=prefix,width=.91,height=.53,y=.23),
      art(prefix+'-neck',[{'d':'M-9 -20 L10 -20 L13 23 L-12 23Z','fill':'#e8ac8d'}],parent=prefix,width=.3,height=.21,y=.43),
      art(prefix+'-coat',[{'d':'M-20 -42 Q0 -31 20 -42 L40 -25 L34 45 L-33 45 L-39 -25Z','fill':'#438e91'},{'d':'M-19 -42 L-5 -16 L0 44 M19 -42 L5 -16 L0 44 M-30 19 L-10 19 L-12 32 L-28 32Z M14 19 L30 19 L28 32 L13 32Z','stroke':'#d5ead6','width':1.2},{'d':'M-35 -24 L-24 -27 M24 -27 L35 -24','stroke':'#265e68','width':2}],parent=prefix,width=.89,height=.57,y=.71),
      art(prefix+'-face',[{'d':'M-31 -17 C-26 -36 28 -38 32 -13 C35 18 20 36 0 37 C-23 36 -36 10 -31 -17Z','fill':'#f2c09b'},{'d':'M-31 -17 C-33 -37 19 -47 32 -13 Q13 -18 9 -31 Q-2 -12 -22 -9Z','fill':'#292c37'}],parent=prefix,width=.76,height=.45,y=.27),
      art(prefix+'-features',[{'d':'M-16 -5 Q-12 -10 -8 -5 M9 -5 Q13 -10 17 -5','stroke':'#29313c','width':2.4},{'d':'M-5 13 Q1 19 9 12','stroke':'#a55756','width':2},{'d':'M-24 6 Q-18 0 -12 5 Q-18 11 -24 6Z M12 6 Q19 0 25 5 Q18 11 12 6Z','fill':'#dc8a7e'},{'d':'M18 -28 L30 -24','stroke':'#edc864','width':3}],parent=prefix,width=.74,height=.44,y=.27),
      layer(prefix+'-left','group',{},parent=prefix,width=.35,height=.45,x=.19,y=.59,anchor_y=.12,rotation=-18,tracks={'rotation':keys((0,-18),(2,-4),(5,-18),(7,-8))}),
      art(prefix+'-left-sleeve',[{'d':'M-27 -43 L21 -43 L29 26 L-21 31Z','fill':'#4d9997'},{'d':'M-21 20 L25 17','stroke':'#d8e5d0','width':2}],parent=prefix+'-left',width=1,height=1),
      art(prefix+'-left-hand',[{'d':'M-22 -30 C-36 -17 -26 14 -10 21 L12 25 C31 24 32 -2 16 -15 L1 -29Z','fill':'#f2c09b'}],parent=prefix+'-left',width=.7,height=.43,x=.5,y=.98),
      layer(prefix+'-right','group',{},parent=prefix,width=.34,height=.45,x=.8,y=.57,anchor_y=.12,rotation=21,tracks={'rotation':keys((0,21),(2,8),(5,26),(7,12))}),
      art(prefix+'-right-sleeve',[{'d':'M-22 -43 L25 -43 L22 30 L-29 25Z','fill':'#398284'},{'d':'M-25 17 L20 20','stroke':'#d8e5d0','width':2}],parent=prefix+'-right',width=1,height=1),
      art(prefix+'-right-hand',[{'d':'M-13 -29 C-31 -7 -29 16 -10 24 L11 22 C30 14 34 -15 18 -29Z','fill':'#f2c09b'}],parent=prefix+'-right',width=.7,height=.43,y=.98)]
    return parts

def window():
    return [layer('room','shape',{'kind':'rect','fill':'#edc764'},x=.35,y=.53,width=.56,height=.69),art('curtain-left',[{'d':'M-48 -50 L38 -50 L-8 45 L-48 50Z','fill':'#d98170'},{'d':'M-29 -48 L-31 42 M-9 -48 L-17 29 M16 -48 L-2 6','stroke':'#edaa86','width':2}],x=.14,y=.51,width=.16,height=.68),art('curtain-right',[{'d':'M-38 -50 L48 -50 L48 50 L8 45Z','fill':'#cc746e'},{'d':'M29 -48 L31 42 M9 -48 L17 29 M-16 -48 L2 6','stroke':'#edaa86','width':2}],x=.56,y=.51,width=.16,height=.68),layer('sill','shape',{'kind':'rect','fill':'#e8d4ae'},x=.35,y=.87,width=.64,height=.035),layer('frame-top','shape',{'kind':'rect','fill':'#eedec0'},x=.35,y=.185,width=.64,height=.035),layer('frame-left','shape',{'kind':'rect','fill':'#eedec0'},x=.035,y=.52,width=.018,height=.69),layer('frame-right','shape',{'kind':'rect','fill':'#eedec0'},x=.665,y=.52,width=.018,height=.69)]

def make(*,title,width,height,fps,seed):
    base={'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'paper','palette':{'background':'#243451','ink':'#eeddba','accent':'#da8d72','secondary':'#438e91','muted':'#84949d','paper':'#f5e6bc','line':'#a5b3b1','glow':'#e6c46d'},'finishing':{'grain':.055,'vignette':.08},'sound':{'music':'lofi','gain':.07,'cues':[{'time':7,'type':'click','gain':.1},{'time':14,'type':'whoosh','gain':.1},{'time':21,'type':'chime','gain':.12}]}}
    city=[layer('city','landscape',{'kind':'city','layers':3,'windows':True},x=.84,y=.57,width=.36,height=.88),layer('stars','weather',{'kind':'stars','count':18,'color':'$paper','size':.0015},width=1,height=.35,y=.17)]
    figure=girl();note=art('note',[{'d':'M-35 -44 L30 -41 L36 44 L-30 46Z','fill':'#f8eed5'},{'d':'M-25 -22 L24 -20 M-23 -7 L24 -5 M-21 9 L25 11','stroke':'#719db0','width':1.2}],x=.37,y=.67,width=.085,height=.16,rotation=8)
    first=scene('window',7,[*copy.deepcopy(city),*window(),*figure,note,text('opening','What could a small idea become?',x=.35,y=.075,width=.64,height=.12,size=.043,font='serif',enter='fade',start=.2)],camera={'tracks':{'zoom':[{'time':0,'value':1},{'time':7,'value':1.035,'interpolation':'log','ease':'linear'}]}})
    fold=scene('fold',7,[layer('desk','shape',{'kind':'rect','fill':'#b48d68'},width=1,height=1),art('sheet',[{'d':'M-37 -43 L37 -43 L37 43 L-37 43Z','fill':'#f5eed7'},{'d':'M-30 -28 L31 -28 M-30 -12 L31 -12 M-30 4 L31 4 M-30 20 L31 20 M-30 35 L31 35','stroke':'#a6bec0','width':1}],width=.4,height=.73,y=.46),art('fold-left',[{'d':'M-39 -43 L3 -43 L3 40Z','fill':'#e6ddc3'}],width=.4,height=.73,y=.46,anchor_x=.53,tracks={'scale_x':keys((0,1),(2.5,.05),(4,1),(7,1))}),art('fold-right',[{'d':'M39 -43 L-3 -43 L-3 40Z','fill':'#faf3de'}],width=.4,height=.73,y=.46,anchor_x=.47,tracks={'scale_x':keys((0,1),(2.5,.05),(4,1),(7,1))}),art('hand-a',[{'d':'M-45 45 L-40 -10 C-42 -33 -15 -43 -8 -24 L5 -32 C19 -31 23 -4 12 15 L3 45Z','fill':'#efbb96'}],x=.33,y=.69,width=.19,height=.37,rotation=20,tracks={'x':keys((0,.27),(2.5,.35),(4,.32),(7,.32))}),art('hand-b',[{'d':'M45 45 L40 -10 C42 -33 15 -43 8 -24 L-5 -32 C-19 -31 -23 -4 -12 15 L-3 45Z','fill':'#efbb96'}],x=.67,y=.69,width=.19,height=.37,rotation=-20,tracks={'x':keys((0,.73),(2.5,.65),(4,.68),(7,.68))}),text('fold-copy','Give it a little shape.',y=.94,width=.8,height=.1,size=.045,font='serif')])
    for item in fold['layers']:
        if item['id'] in ('sheet','fold-left','fold-right'):item.setdefault('tracks',{})['opacity']=keys((0,1),(3.8,1),(4.6,0),(7,0))
    fold['layers'].insert(-1,art('folded-plane',[{'d':'M-49 10 L49 -24 L-2 40 L-12 9Z','fill':'#f5eace'},{'d':'M-12 9 L49 -24 L4 18 L-2 40Z','fill':'#c6d4cc'},{'d':'M-12 9 L49 -24','stroke':'#9caca7','width':1}],width=.3,height=.38,y=.45,start=3.8,enter='fade',enter_duration=.8,tracks={'rotation':keys((0,-35),(3.2,-6)), 'y':keys((0,.45),(3.2,.37))}))
    plane=art('plane',[{'d':'M-49 10 L49 -24 L-2 40 L-12 9Z','fill':'#f5eace'},{'d':'M-12 9 L49 -24 L4 18 L-2 40Z','fill':'#c6d4cc'},{'d':'M-12 9 L49 -24','stroke':'#9caca7','width':1}],width=.23,height=.24,x=.4,y=.55,tracks={'x':[{'time':0,'value':.16},{'time':2,'value':.42,'interpolation':'monotone'},{'time':4.5,'value':.65,'interpolation':'monotone'},{'time':7,'value':.81,'interpolation':'monotone'}],'y':keys((0,.68),(2,.48),(4.5,.34),(7,.24)),'rotation':keys((0,-6),(2,-14),(4.5,8),(7,-2))})
    flight=scene('flight',7,[layer('moon','shape',{'kind':'circle','fill':'$glow'},x=.78,y=.22,width=.09,height=.16),layer('hills','landscape',{'kind':'hills','layers':4,'color':'#53677f','speed':.015},width=1,height=.7,y=.77),layer('stars','weather',{'kind':'stars','count':24,'color':'$paper','size':.0014},width=1,height=.6,y=.3),plane,text('flight-copy','Let curiosity take it somewhere.',y=.91,width=.84,height=.12,size=.045,font='serif')],camera={'tracks':{'zoom':keys((0,1),(7,1.07),ease='linear')}})
    ending=copy.deepcopy(first);ending.update(id='return',duration=7,transition={'type':'crossfade','duration':.5});ending['layers']=[item for item in ending['layers'] if item['id'] not in ('note','opening')]
    ending['layers']+=[art('letter',[{'d':'M-35 -42 L34 -41 L35 42 L-34 43Z','fill':'#f5eed7'},{'d':'M0 -24 L6 -8 L23 -8 L10 3 L15 20 L0 10 L-15 20 L-10 3 L-23 -8 L-6 -8Z','fill':'#d87f69'}],x=.4,y=.64,width=.115,height=.21,rotation=-4,enter='slide_up',start=.5),text('end-copy','Bring back a little wonder.',x=.35,y=.075,width=.64,height=.12,size=.043,font='serif',enter='fade',start=.4)]
    base['scenes']=[first,fold,flight,ending]
    return AnimationComposition.model_validate(base)
