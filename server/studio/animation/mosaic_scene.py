"""Bounded controls and packaging for the supplied contour-mosaic scene modules."""
from pathlib import Path
import re
from .schema_helpers import schema

ROOT=Path(__file__).with_name('mosaic')
PALETTE_KEYS=re.findall(r'^\s+(\w+):\s*[\'\"]#', (ROOT/'config.js').read_text(), re.M)
def number(a,b):return {'type':'number','minimum':a,'maximum':b}
def row(items):return {'type':'array','prefixItems':items,'items':False,'minItems':len(items),'maxItems':len(items)}
def rows(items,n=64):return {'type':'array','items':row(items),'minItems':2,'maxItems':n}
TIME=number(0,15)
CHANNELS={'curl':(-1.5,1.5),'amp':(0,2),'freq':(.1,6),'spread':(.3,1.8),'pect':(0,1.5),'loosen':(0,1),'stretch':(.7,1.3),'lookX':(-1,1),'lookY':(-1,1)}
PROPS={
 'palette':schema({k:{'type':'string','pattern':'^#[0-9a-fA-F]{6}$'} for k in PALETTE_KEYS}),
 'seed':{'type':'integer','minimum':0,'maximum':2147483647},
 'fish_scale':number(.5,1.3),'wave_strength':number(0,2),'tail_spread':number(.3,1.8),'fin_activity':number(0,1.5),'curl_bias':number(-.5,.5),
 'playhead':TIME,
 'body_profile':rows([number(0,1),number(0,40),number(-40,0)],24),
 'camera':rows([TIME,number(400,900),number(180,500),number(1,1.5)]),
 'path':{'type':'array','minItems':2,'maxItems':64,'items':schema({'t':TIME,'x':number(420,900),'y':number(80,530),'vx':number(-600,600),'vy':number(-600,600)},('t','x','y'))},
 'motion':schema({k:rows([TIME,number(*bounds)]) for k,bounds in CHANNELS.items()}),
}

def validate(props):
    def ordered(values):
        if any(a>=b for a,b in zip(values,values[1:])):raise ValueError('Mosaic keys must be strictly increasing')
    if 'body_profile' in props:
        profile=props['body_profile'];ordered([r[0] for r in profile])
        if profile[0][0]!=0 or profile[-1][0]!=1:raise ValueError('Body profile must cover zero through one')
    if 'camera' in props:ordered([r[0] for r in props['camera']])
    if 'path' in props:ordered([r['t'] for r in props['path']])
    for frames in props.get('motion',{}).values():ordered([r[0] for r in frames])

def script():
    parts=['window.createMosaicScene = function(OPTIONS) {']
    parts.append((ROOT/'config.js').read_text())
    parts.append('''Object.assign(CONFIG.palette, OPTIONS.palette || {});
CONFIG.seed = OPTIONS.seed ?? CONFIG.seed;
CONFIG.fish.scale = OPTIONS.fish_scale ?? CONFIG.fish.scale;
CONFIG.fish.profile = OPTIONS.body_profile || CONFIG.fish.profile;
CONFIG.camera = OPTIONS.camera || CONFIG.camera;''')
    for name in ['util','tiler','scene','fish','choreo','renderer','frame']:
        source=(ROOT/(name+'.js')).read_text()
        if name=='choreo':
            source=source.replace('const path = U.path([','const path = U.path(OPTIONS.path || [')
            for key in CHANNELS:source=source.replace(f'const {key} = T([',f'const {key} = T(OPTIONS.motion?.{key} || [')
        parts.append(source)
    parts.append('''const surface = document.createElement('canvas');
surface.width = CONFIG.width; surface.height = CONFIG.height;
try { Short.init(surface); } catch(error) { try { Renderer.dispose(); } catch {} throw error; }
return {surface, render: t => Short.frame(t), dispose: () => Renderer.dispose()};
};''')
    return '\n'.join(parts)
