"""Expand built-in rigs into the same editable bounded scene graph as authored nodes."""
import copy

def expand_presets(nodes):
    result=[]
    for original in nodes:
        if original['kind']!='preset':
            if any(key in original for key in ('preset','action')):raise ValueError('Preset and action controls belong to preset nodes')
            result.append(original);continue
        from .scene_recipes import mascot,paper_bird,town
        factories={'mascot':mascot,'paper_bird':paper_bird,'town':town}
        if original.get('preset') not in factories:raise ValueError('Preset node requires mascot, paper_bird or town')
        name=original['preset'];action=original.get('action','idle')
        if action not in {'mascot':{'idle','wave','look'},'paper_bird':{'idle','flight'},'town':{'idle'}}[name]:raise ValueError('The requested action is unavailable for this rig')
        parts=copy.deepcopy(factories[name]())
        if name=='mascot':parts=[n for n in parts if n['id'] not in ('floor','platform')]
        root={'mascot':'actor','paper_bird':'bird','town':'town'}[name];prefix=original['id']
        for part in parts:
            part.pop('tracks',None)
            if name=='mascot' and part.get('parent')==root:part['position'][1]-=.1384
            if part['id']==root:
                part={**part,**{key:value for key,value in original.items() if key not in ('kind','preset','action')},'kind':'group'}
            else:
                source_id=part['id'];part['id']=prefix+'-'+source_id
                part['parent']=prefix if part.get('parent')==root or not part.get('parent') else prefix+'-'+part['parent']
                if original.get('color') and part.get('color')=='#9babc1':part['color']=original['color']
                if name=='mascot' and source_id=='head':part['motion']={'axis':'rz','kind':'sway','amount':5,'speed':.45}
                if name=='mascot' and action=='wave' and source_id=='right-arm-pivot':part['rotation']=[0,0,90];part['motion']={'axis':'rz','kind':'sway','amount':18,'speed':1.2}
                if name=='mascot' and action=='look' and source_id=='head':part['motion']={'axis':'ry','kind':'sway','amount':25,'speed':.25}
                if name=='paper_bird' and action=='flight' and source_id in ('bird-near','bird-far'):part['motion']={'axis':'rx','kind':'sway','amount':45 if source_id=='bird-near' else -45,'speed':1.5}
            result.append(part)
    return result
