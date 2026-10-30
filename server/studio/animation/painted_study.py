"""Declarative lake scene for the source-derived brushstroke renderer."""
import math
import random
from ..schemas_animation import AnimationComposition


def make(*,title='A light across the water',width=1280,height=720,fps=24,seed=42):
    rng=random.Random(seed)
    layers=[]
    def vector(name,paths,**extra):
        layers.append(dict(id=name,component='vector',width=1,height=1,props={'view_box':[0,0,1600,900],'fit':'stretch','paths':paths},**extra))
    def path(d,fill):return {'d':d,'fill':fill}
    def ellipse(x,y,rx,ry):return f'M {x-rx} {y} a {rx} {ry} 0 1 0 {rx*2} 0 a {rx} {ry} 0 1 0 {-rx*2} 0'
    layers.append(dict(id='sky',component='shape',width=1,height=1,paint={'kind':'linear','colors':['#0b153c','#403b6b','#bc806f'],'angle':90},props={'kind':'rect','fill':'#293655'}))
    stars=[path(ellipse(rng.uniform(30,1570),rng.uniform(20,320),rng.uniform(1,2.5),1.5),'#98a9c4') for _ in range(60)]
    vector('stars',stars)
    vector('moon',[path(ellipse(1100,175,46,46),'#efe5c5')])
    layers.append(dict(id='moon-halo',component='shape',x=1100/1600,y=175/900,width=.19,height=.32,paint_pass='light',opacity=.45,paint={'kind':'radial','colors':['#514932','#171209','#000000','#000000']},props={'kind':'circle','fill':'#706442'}))
    for k,(base,amp,col) in enumerate([(390,135,'#454b70'),(455,120,'#303e60'),(520,75,'#192e46')]):
        points=[(x,base-amp*(.45+.33*math.sin(x*.004+k*2)+.22*math.sin(x*.011+k))) for x in range(-40,1660,35)]
        d='M -40 900 L '+' L '.join(f'{x} {y:.2f}' for x,y in points)+' L 1660 900 Z'
        vector(f'ridge-{k}',[path(d,col)])
    layers.append(dict(id='water',component='shape',x=.5,y=.79,width=1,height=.43,paint={'kind':'linear','colors':['#42616a','#12283b','#081426'],'angle':90},props={'kind':'rect','fill':'#234555'}))
    for name,col,count,light in [('ripples','#65868a',55,False),('moon-water','#9e9271',35,True)]:
        strokes=[]
        for i in range(count):
            y=rng.uniform(540,890);spread=(y-500)*.48
            x=rng.uniform(0,1600) if not light else 1100+rng.uniform(-spread,spread)
            length=rng.uniform(8,80)*(y/700)
            strokes.append({'d':f'M {x:.2f} {y:.2f} q {length/2:.2f} -2 {length:.2f} 0','stroke':col,'width':rng.uniform(1,3)})
        vector(name,strokes,paint_pass='light' if light else 'base',opacity=.6,motion={'type':'float','amount':.002,'speed':.4,'phase':2 if light else 0})
    vector('near-bank',[path('M -30 690 Q 130 650 310 742 Q 450 790 570 900 L -30 900 Z','#091b29')])
    for i,(x,y,size) in enumerate([(95,735,390),(225,759,290),(330,792,205)]):
        paths=[path(f'M {x-5} {y} L {x-2} {y-size} L {x+4} {y} Z','#101d2b')]
        for j in range(8):
            py=y-size+j*size*.11;w=12+j*size*.045
            paths.append(path(f'M {x} {py-25} Q {x-w*.5} {py+30} {x-w} {py+52} Q {x} {py+30} {x+w} {py+52} Z','#0b1c29'))
        vector(f'pine-{i}',paths)
    vector('boat',[path('M 730 654 Q 844 683 963 641 Q 940 703 816 695 Q 760 683 730 654 Z','#101d2b'),path('M 746 656 Q 855 676 952 646 L 947 653 Q 850 685 758 664 Z','#8a6450')],motion={'type':'float','amount':.003,'speed':.55})
    vector('traveler',[path('M 833 654 Q 830 620 844 606 Q 868 608 876 645 L 906 670 L 837 672 Z','#20263b'),path(ellipse(852,600,14,18),'#826650'),path('M 844 638 Q 877 620 917 644 L 914 651 Q 870 641 847 652 Z','#3c3440')])
    vector('lantern',[path('M 905 640 L 930 640 L 934 677 L 902 677 Z','#c99b59'),path('M 911 646 L 924 646 L 927 670 L 908 670 Z','#ffe0a0')])
    layers.append(dict(id='lantern-light',component='shape',paint_pass='light',x=.573,y=.733,width=.15,height=.25,paint={'kind':'radial','colors':['#b87739','#321709','#000000','#000000']},props={'kind':'circle','fill':'#ffb85c'},tracks={'opacity':[{'time':0,'value':.6},{'time':3,'value':1},{'time':6,'value':.7},{'time':10,'value':.9}]}))
    vector('lantern-reflection',[{'d':f'M {917-i*3} {692+i*9} q {10+i*2} -3 {22+i*4} 0','stroke':'#c98c49','width':max(1,4-i*.2)} for i in range(17)],paint_pass='light',opacity=.65,motion={'type':'float','amount':.002,'speed':.7})
    return AnimationComposition.model_validate({'version':1,'title':title,'width':width,'height':height,'fps':fps,'seed':seed,'style':'studio','scenes':[{'id':'lake','duration':10,'background':'#0b153c','painterly':{},'camera':{'tracks':{'zoom':[{'time':0,'value':1},{'time':10,'value':1.22}],'x':[{'time':0,'value':.5},{'time':10,'value':.55}],'y':[{'time':0,'value':.5},{'time':10,'value':.57}]}},'layers':layers}]})
