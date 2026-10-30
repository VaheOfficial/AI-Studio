"""Chat-scoped, versioned animation compositions using the existing artifact store."""
import json,copy
from ..agents import store
from ..schemas_agents import ArtifactCreate
from ..schemas_animation import AnimationComposition

def read(sid,project_id,version=None):
    value=store.artifact(project_id)
    if value.session_id!=sid:raise ValueError('Animation project belongs to another conversation')
    if version is not None and value.version!=version:raise ValueError('Animation project changed; read its current revision before editing or rendering')
    return value,AnimationComposition.model_validate_json(value.content)

def save(sid,composition,old=None):
    return store.save_artifact(sid,ArtifactCreate(title=composition.title,kind='json',content=composition.model_dump_json(),id=old.id if old else None,version=old.version if old else None))

def summary(artifact,composition):
    return {'project_id':artifact.id,'version':artifact.version,'content_hash':artifact.content_hash,'title':composition.title,'duration':composition.duration,'size':[composition.width,composition.height],'fps':composition.fps,'scenes':[{'id':scene.id,'duration':scene.duration,'layers':[{'id':layer.id,'component':layer.component,'parent':layer.parent,**({'nodes':[{'id':node['id'],'kind':node['kind'],'parent':node.get('parent')} for node in layer.props['nodes']]} if layer.component=='scene3d' else {})} for layer in scene.layers]} for scene in composition.scenes]}

def pointer(target,path):
    if not isinstance(path,str) or not path.startswith('/') or len(path)>500:raise ValueError('Edit path must be a bounded JSON pointer such as /props/roughness')
    keys=path[1:].split('/')
    keys=[key.replace('~1','/').replace('~0','~') for key in keys]
    for key in keys[:-1]:
        if isinstance(target,list):
            if not key.isdecimal() or not 0<=int(key)<len(target):raise ValueError('Edit list index is outside the current composition')
            target=target[int(key)]
        elif isinstance(target,dict):
            if key not in target:target[key]={}
            target=target[key]
        else:raise ValueError('Edit path crosses a scalar value')
    key=keys[-1]
    if isinstance(target,list):
        if not key.isdecimal() or not 0<=int(key)<len(target):raise ValueError('Edit list index is outside the current composition')
        key=int(key)
    elif not isinstance(target,dict):raise ValueError('Edit path crosses a scalar value')
    return target,key

def edit(sid,project_id,version,operations):
    if not 1<=len(operations)<=32:raise ValueError('Apply one to 32 bounded edits in a revision')
    old,composition=read(sid,project_id,version);data=composition.model_dump(mode='json')
    for operation in operations:
        op=operation.get('op','set');scene_id=operation.get('scene_id');layer_id=operation.get('layer_id');node_id=operation.get('node_id');target=data;scene=None;selected_layer=None
        if op in ('set','add_scene','add_layer','add_node') and 'value' not in operation:raise ValueError('This edit requires a value')
        if scene_id:
            scene=next((s for s in data['scenes'] if s['id']==scene_id),None)
            if not scene:raise ValueError('Scene not found: '+scene_id)
            target=scene
        if layer_id:
            if not scene:raise ValueError('A layer edit requires its scene_id')
            target=next((layer for layer in scene['layers'] if layer['id']==layer_id),None)
            if not target:raise ValueError('Layer not found: '+layer_id)
            selected_layer=target
        if node_id or op in ('add_node','remove_node'):
            if not selected_layer or selected_layer['component']!='scene3d':raise ValueError('A node edit requires a scene3d layer and its scene_id/layer_id')
            if node_id:
                if op not in ('set','remove','remove_node'):raise ValueError('node_id selects set/remove or a removed node branch')
                target=next((node for node in selected_layer['props']['nodes'] if node['id']==node_id),None)
                if not target:raise ValueError('Node not found: '+node_id)
        if op=='add_scene':data['scenes'].append(copy.deepcopy(operation['value']))
        elif op=='remove_scene':
            if not scene:raise ValueError('Removing a scene requires scene_id')
            data['scenes'].remove(scene)
        elif op=='add_layer':
            if not scene or layer_id:raise ValueError('Adding a layer targets a scene')
            scene['layers'].append(copy.deepcopy(operation['value']))
        elif op=='remove_layer':
            if not layer_id:raise ValueError('Removing a layer requires its scene and layer IDs')
            scene['layers'].remove(target)
        elif op=='add_node':selected_layer['props']['nodes'].append(copy.deepcopy(operation['value']))
        elif op=='remove_node':
            if not node_id:raise ValueError('Removing a node requires its scene/layer/node IDs')
            removed={node_id};nodes=selected_layer['props']['nodes']
            for _ in range(13):removed.update(node['id'] for node in nodes if node.get('parent') in removed)
            selected_layer['props']['nodes']=[node for node in nodes if node['id'] not in removed]
        elif op in ('set','remove'):
            parent,key=pointer(target,operation.get('path'))
            if op=='set':parent[key]=copy.deepcopy(operation['value'])
            elif isinstance(parent,list):parent.pop(key)
            elif key in parent:del parent[key]
            else:raise ValueError('Removed property does not exist')
        else:raise ValueError('Unsupported animation edit operation')
    validated=AnimationComposition.model_validate(data)
    return save(sid,validated,old),validated
