"""Bounded scene graphs and analytic keyframes for the local 3D renderer."""
from .schema_helpers import schema,enum,C,F,B

NUMBER={'type':'number','minimum':-100,'maximum':100}
VEC={'type':'array','items':NUMBER,'minItems':3,'maxItems':3}
POSITIVE={'type':'array','items':{'type':'number','minimum':.001,'maximum':100},'minItems':3,'maxItems':3}
ID={'type':'string','pattern':r'^[a-zA-Z][a-zA-Z0-9_-]{0,47}$'}
FRAME=schema({'time':{'type':'number','minimum':0,'maximum':120},'value':{'type':'number','minimum':-10000,'maximum':10000},'ease':enum('linear','smooth','cubic_in','cubic_out','cubic_in_out','back_out','elastic_out','bounce_out','step')},('time','value'))
FRAME['properties']['interpolation']=enum('eased','monotone','log','monotone_log')
def tracks(names):return schema({name:{'type':'array','minItems':1,'maxItems':100,'items':FRAME} for name in names})
NODE=schema({'id':ID,'parent':ID,'kind':enum('group','box','rounded_box','sphere','capsule','cylinder','cone','torus','knot','plane'),'position':VEC,'rotation':{'type':'array','items':{'type':'number','minimum':-10000,'maximum':10000},'minItems':3,'maxItems':3},'scale':POSITIVE,'dimensions':POSITIVE,'color':C,'roughness':F,'metalness':F,'clearcoat':F,'emissive':C,'emissive_intensity':{'type':'number','minimum':0,'maximum':10},'cast_shadow':B,'receive_shadow':B,'tracks':tracks(('x','y','z','rx','ry','rz','sx','sy','sz'))},('id','kind'))
PROPS={'nodes':{'type':'array','minItems':1,'maxItems':192,'items':NODE},'camera':schema({'position':VEC,'target':VEC,'fov':{'type':'number','minimum':10,'maximum':100},'tracks':tracks(('x','y','z','target_x','target_y','target_z','fov'))}),'lights':{'type':'array','maxItems':6,'items':schema({'kind':enum('directional','point'),'position':VEC,'color':C,'intensity':{'type':'number','minimum':0,'maximum':100},'shadow':B},('kind',))},'ambient':{'type':'number','minimum':0,'maximum':3},'exposure':{'type':'number','minimum':.1,'maximum':4},'shadows':B,'environment':B}
NODE['properties']['texture']=enum('none','wool','paper','brushed','canvas')
PROPS.update(shadow_extent={'type':'number','minimum':2,'maximum':50},shadow_resolution={'type':'integer','enum':[512,1024,2048]})
NODE['properties'].update(texture_scale={'type':'number','minimum':.25,'maximum':16},bump_strength={'type':'number','minimum':0,'maximum':.2},glow={'type':'number','minimum':0,'maximum':3})
NODE['properties']['fibers']=schema({'count':{'type':'integer','minimum':1,'maximum':8000},'length':{'type':'number','minimum':.001,'maximum':.08},'thickness':{'type':'number','minimum':.0001,'maximum':.01},'seed':{'type':'integer','minimum':0,'maximum':1000000}},('count','length'))
NODE['properties']['kind']['enum'].append('model')
NODE['properties']['kind']['enum'].append('polygon')
NODE['properties']['kind']['enum'].append('preset')
NODE['properties']['kind']['enum'].extend(['lathe','tube'])
NODE['properties'].update(profile={'type':'array','minItems':2,'maxItems':64,'items':{'type':'array','minItems':2,'maxItems':2,'prefixItems':[{'type':'number','minimum':0,'maximum':100},NUMBER]}},curve={'type':'array','minItems':2,'maxItems':32,'items':VEC},angle_start={'type':'number','minimum':-360,'maximum':360},angle_length={'type':'number','minimum':1,'maximum':360})
NODE['properties'].update(preset=enum('mascot','paper_bird','town'),action=enum('idle','wave','look','flight'),motion=schema({'axis':enum('x','y','z','rx','ry','rz'),'kind':enum('sway','spin'),'amount':{'type':'number','minimum':-360,'maximum':360},'speed':{'type':'number','minimum':0,'maximum':20},'phase':{'type':'number','minimum':-100,'maximum':100}},('axis','kind','amount')))
NODE['properties'].update(points={'type':'array','minItems':3,'maxItems':128,'items':{'type':'array','items':NUMBER,'minItems':2,'maxItems':2}},depth={'type':'number','minimum':.001,'maximum':10})
NODE['properties'].update(source={'type':'string','maxLength':1000},clip={'type':'string','maxLength':100},clip_speed={'type':'number','minimum':.01,'maximum':10},clip_offset={'type':'number','minimum':0,'maximum':120})
PROPS['environment_intensity']={'type':'number','minimum':0,'maximum':3}
PROPS['fog']=schema({'color':C,'near':{'type':'number','minimum':0,'maximum':200},'far':{'type':'number','minimum':.1,'maximum':400}},('color','near','far'))
NODE['properties']['tracks']['properties'].update(tracks(('roughness','metalness','clearcoat','emissive_intensity'))['properties'])
NODE['properties']['tracks']['properties'].update(tracks(('spread','flip'))['properties'])
NODE['properties']['repeat']=schema({'count':{'type':'integer','minimum':1,'maximum':1024},'layout':enum('radial','grid','spiral'),'radius':{'type':'number','minimum':.001,'maximum':20},'spread':{'type':'number','minimum':0,'maximum':4},'flip':F,'wave':{'type':'number','minimum':0,'maximum':5},'turns':{'type':'number','minimum':1,'maximum':20}},('count','layout'))
COLOR_FRAME=schema({'time':{'type':'number','minimum':0,'maximum':120},'value':C,'ease':FRAME['properties']['ease']},('time','value'))
NODE['properties']['color_tracks']=schema({name:{'type':'array','minItems':1,'maxItems':100,'items':COLOR_FRAME} for name in ('color','emissive')})

def validate_scene(props):
    camera=props.get('camera',{})
    if not camera.get('tracks') and camera.get('position',[6,4,9])==camera.get('target',[0,.5,0]):raise ValueError('Camera position must differ from its target')
    if props.get('fog') and props['fog']['near']>=props['fog']['far']:raise ValueError('Fog far distance must exceed near distance')
    from .rigs import expand_presets
    expanded=expand_presets(props['nodes'])
    if len(expanded)>192:raise ValueError('3D scene exceeds 192 nodes after preset expansion')
    nodes={node['id']:node for node in expanded}
    if sum(node.get('repeat',{}).get('count',0) for node in expanded)>4096:raise ValueError('3D scene exceeds 4096 instanced parts')
    if sum(node.get('fibers',{}).get('count',0) for node in expanded)>16000:raise ValueError('3D scene exceeds 16000 surface fibers')
    if len(nodes)!=len(expanded):raise ValueError('3D node IDs must be unique after preset expansion')
    for node in nodes.values():
        if node.get('fibers') and node['kind']!='sphere':raise ValueError('Surface fibers require a sphere node; its scale can form an ellipsoid')
        if node['kind']=='model' and not node.get('source'):raise ValueError('A 3D model node requires a local self-contained GLB source')
        if node['kind']=='polygon' and not node.get('points'):raise ValueError('A polygon node requires an ordered 2D outline')
        if node['kind']=='lathe' and not node.get('profile'):raise ValueError('A lathe node requires radius/height profile points')
        if node['kind']=='tube' and not node.get('curve'):raise ValueError('A tube node requires a 3D curve')
        if node['kind']=='tube' and len({tuple(point) for point in node['curve']})<2:raise ValueError('A tube curve requires distinct points')
        if node['kind']=='lathe' and (not any(point[0]>0 for point in node['profile']) or len({tuple(point) for point in node['profile']})<2):raise ValueError('A lathe requires a nondegenerate radius/height profile')
        if node['kind']=='polygon':
            points=node['points'];area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))
            if len({tuple(point) for point in points})<3 or abs(area)<1e-8:raise ValueError('A polygon outline must enclose a nonzero area')
        if node['kind']!='lathe' and any(key in node for key in ('profile','angle_start','angle_length')):raise ValueError('Revolution profiles belong to lathe nodes')
        if node['kind']!='tube' and 'curve' in node:raise ValueError('3D curves belong to tube nodes')
        if node.get('repeat') and node['kind'] not in ('box','plane','polygon'):raise ValueError('Instancing supports bounded box, plane or polygon parts')
        if node['kind']!='polygon' and any(key in node for key in ('points','depth')):raise ValueError('Polygon outlines belong to polygon nodes')
        if node.get('motion',{}).get('axis') in ('x','y','z') and abs(node['motion']['amount'])>10:raise ValueError('Positional motion amplitude is at most ten world units')
        if node['kind']!='model' and any(key in node for key in ('source','clip','clip_speed','clip_offset')):raise ValueError('Model assets and clips belong to model nodes')
        seen={node['id']};parent=node.get('parent')
        while parent:
            if parent not in nodes:raise ValueError('3D parent must identify an existing node')
            if parent in seen or len(seen)>12:raise ValueError('3D hierarchy must be acyclic and at most 12 levels deep')
            seen.add(parent);parent=nodes[parent].get('parent')
    for target in [*nodes.values(),props.get('camera',{})]:
        for name,frames in target.get('tracks',{}).items():
            if any(a['time']>=b['time'] for a,b in zip(frames,frames[1:])):raise ValueError('3D keyframe times must increase strictly')
            if any(frame.get('interpolation') in ('log','monotone_log') for frame in frames) and any(frame['value']<=0 for frame in frames):raise ValueError('Logarithmic 3D tracks require positive values')
            low,high=(0,1) if name in ('roughness','metalness','clearcoat','flip') else (0,4) if name=='spread' else (0,10) if name=='emissive_intensity' else (.001,100) if name in ('sx','sy','sz') else (10,100) if name=='fov' else (-10000,10000) if name in ('rx','ry','rz') else (-100,100)
            if name in ('spread','flip') and not target.get('repeat'):raise ValueError('Spread and flip tracks require instanced parts')
            if name in ('roughness','metalness','clearcoat','emissive_intensity') and target.get('kind') in ('group','model','preset'):raise ValueError('Material tracks require a primitive mesh node')
            if any(not low<=frame['value']<=high for frame in frames):raise ValueError('3D track values exceed the target bounds')
        if target.get('color_tracks') and target.get('kind') in ('group','model','preset'):raise ValueError('Color tracks require a primitive mesh node')
        for frames in target.get('color_tracks',{}).values():
            if any(a['time']>=b['time'] for a,b in zip(frames,frames[1:])):raise ValueError('3D color keyframe times must increase strictly')
