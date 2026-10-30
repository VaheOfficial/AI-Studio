"""Inspect self-contained binary glTF before the browser decodes geometry."""
import json,struct
from ..jobs import JobError

def inspect_glb(path):
    data=path.read_bytes()
    if len(data)<20 or len(data)>64*1024*1024:raise JobError('GLB assets must be at most 64 MB')
    magic,version,length=struct.unpack_from('<III',data)
    if magic!=0x46546c67 or version!=2 or length!=len(data):raise JobError('Attach a valid binary glTF 2.0 file')
    offset=12;chunks=[]
    while offset<len(data):
        if offset+8>len(data):raise JobError('GLB has a truncated chunk')
        size,kind=struct.unpack_from('<II',data,offset);offset+=8
        if size%4 or offset+size>len(data):raise JobError('GLB chunk length is invalid')
        chunks.append((kind,data[offset:offset+size]));offset+=size
    if not chunks or chunks[0][0]!=0x4e4f534a:raise JobError('GLB must begin with a JSON chunk')
    try:document=json.loads(chunks[0][1])
    except (ValueError,UnicodeDecodeError):raise JobError('GLB JSON cannot be decoded')
    if not isinstance(document,dict):raise JobError('GLB document must be an object')
    forbidden={'KHR_draco_mesh_compression','EXT_meshopt_compression','KHR_texture_basisu'}
    if forbidden&set(document.get('extensionsUsed',[])):raise JobError('Export GLB with uncompressed geometry and PNG/JPEG textures')
    limits={'nodes':2048,'meshes':256,'materials':256,'textures':64,'images':64,'animations':64,'accessors':4096,'skins':64,'cameras':32,'buffers':1,'bufferViews':4096}
    for key,limit in limits.items():
        entries=document.get(key,[])
        if not isinstance(entries,list) or len(entries)>limit or any(not isinstance(item,dict) for item in entries):raise JobError('GLB contains an invalid or oversized resource table')
    if any('uri' in item for key in ('buffers','images') for item in document.get(key,[])):raise JobError('GLB must embed every buffer and texture; external or data URI resources are unsupported')
    accessors=document.get('accessors',[])
    if any(not isinstance(item.get('count',0),int) or item.get('count',0)<0 for item in accessors):raise JobError('GLB accessor counts must be nonnegative integers')
    if sum(item.get('count',0) for item in accessors)>2000000:raise JobError('GLB exceeds two million accessor elements')
    components={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT2':4,'MAT3':9,'MAT4':16}
    scalar_elements=0
    for item in accessors:
        if item.get('type') not in components or item.get('componentType') not in (5120,5121,5122,5123,5125,5126):raise JobError('GLB accessor type is unsupported or invalid')
        scalar_elements+=item.get('count',0)*components[item['type']]
    if scalar_elements>8000000:raise JobError('GLB exceeds eight million scalar accessor elements')
    views=document.get('bufferViews',[])
    binary=sum(len(chunk) for kind,chunk in chunks if kind==0x004e4942)
    if len([chunk for kind,chunk in chunks if kind==0x004e4942])>1:raise JobError('GLB must have at most one embedded binary chunk')
    buffers=document.get('buffers',[])
    if len(buffers)>1 or any(not isinstance(item.get('byteLength'),int) or not 0<=item['byteLength']<=binary for item in buffers):raise JobError('GLB buffers exceed embedded storage')
    if any(not isinstance(view.get('byteOffset',0),int) or not isinstance(view.get('byteLength',0),int) or view.get('buffer',0)!=0 or view.get('byteOffset',0)<0 or view.get('byteLength',0)<0 or view.get('byteOffset',0)+view.get('byteLength',0)>binary for view in views):raise JobError('GLB buffer views exceed embedded storage')
    nodes=document.get('nodes',[]);parents={}
    for index,node in enumerate(nodes):
        children=node.get('children',[])
        if not isinstance(children,list) or any(not isinstance(child,int) for child in children) or len(children)!=len(set(children)):raise JobError('GLB child references must be unique integers')
        for child in children:
            if not isinstance(child,int) or not 0<=child<len(nodes) or child in parents:raise JobError('GLB nodes must form a valid scene hierarchy')
            parents[child]=index
    for index in range(len(nodes)):
        seen={index};parent=parents.get(index)
        while parent is not None:
            if parent in seen or len(seen)>64:raise JobError('GLB hierarchy is cyclic or exceeds 64 levels')
            seen.add(parent);parent=parents.get(parent)
    from PIL import Image
    import io
    texture_pixels=0
    for item in document.get('images',[]):
        index=item.get('bufferView')
        if not isinstance(index,int) or not 0<=index<len(views):raise JobError('GLB image requires an embedded buffer view')
        view=views[index];payload=next((chunk for kind,chunk in chunks if kind==0x004e4942),b'');start=view.get('byteOffset',0)
        try:
            with Image.open(io.BytesIO(payload[start:start+view['byteLength']])) as image:
                if image.width*image.height>16000000:raise JobError('GLB texture exceeds 16 megapixels')
                texture_pixels+=image.width*image.height
                if texture_pixels>32000000:raise JobError('GLB textures exceed a combined 32 megapixels')
        except JobError:raise
        except Exception:raise JobError('GLB texture cannot be decoded')
    document['_studio_resource_budget']={'texture_pixels':texture_pixels,'scalar_elements':scalar_elements}
    return document
