import * as THREE from './three/build/three.module.js';
import { RoomEnvironment } from './three/examples/jsm/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from './three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { GLTFLoader } from './three/examples/jsm/loaders/GLTFLoader.js';
import { clone } from './three/examples/jsm/utils/SkeletonUtils.js';

// A single context serves all scenes; scene state is reconstructed at every seek.
export function createSceneRenderer({ color, track, ease, report }) {
  const canvas = document.createElement('canvas');
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment();
  const environment = pmrem.fromScene(room, .04);
  room.dispose(); pmrem.dispose();
  const scenes = new Map(), materials = [], geometries = [], textures = new Map(), models = new Map();
  const radians = THREE.MathUtils.degToRad;
  function surface(kind,repeat=5) {
    const key=kind+':'+repeat;
    if (textures.has(key)) return textures.get(key);
    const size=256, data=new Uint8Array(size*size*4);
    for(let y=0;y<size;y++) for(let x=0;x<size;x++) {
      const n=((Math.imul(x+1,374761393)^Math.imul(y+1,668265263))>>>0)/4294967295;
      const weave=kind==='canvas' ? Math.sin(x*Math.PI/3)*Math.cos(y*Math.PI/3) : kind==='wool' ? Math.sin((x+y)*1.7+n)*.6 : kind==='brushed' ? Math.sin(y*3.1)*.55 : 0;
      const value=Math.round(128+n*64+weave*45),index=(y*size+x)*4;data.set([value,value,value,255],index);
    }
    const texture=new THREE.DataTexture(data,size,size,THREE.RGBAFormat);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.repeat.set(repeat,repeat);texture.magFilter=THREE.LinearFilter;texture.minFilter=THREE.LinearMipmapLinearFilter;texture.generateMipmaps=true;texture.anisotropy=Math.min(4,renderer.capabilities.getMaxAnisotropy());texture.needsUpdate=true;textures.set(key,texture);return texture;
  }
  function build(q, palette) {
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(38, 1, .05, 500), objects = new Map(), mixers=[];
    const sceneMaterials=[],sceneGeometries=[];
    if (q.environment !== false) scene.environment = environment.texture;
    scene.environmentIntensity = q.environment_intensity ?? .35;
    if(q.fog) scene.fog=new THREE.Fog(color(q.fog.color,palette),q.fog.near,q.fog.far);
    const ambientLight=new THREE.HemisphereLight('#fff6e8', '#536879', q.ambient ?? .7);scene.add(ambientLight);
    for (const item of q.lights || [{ kind: 'directional', position: [4, 7, 5], intensity: 4, shadow: true }, { kind: 'directional', position: [-4, 2, -4], color: '#9ecbff', intensity: 2 }]) {
      const light = item.kind === 'point' ? new THREE.PointLight(color(item.color || '#ffffff', palette), item.intensity ?? 4, 80, 2) : new THREE.DirectionalLight(color(item.color || '#ffffff', palette), item.intensity ?? 4);
      light.position.fromArray(item.position || [4, 7, 5]);
      light.castShadow = q.shadows !== false && !!item.shadow;
      light.shadow.mapSize.set(q.shadow_resolution??1024,q.shadow_resolution??1024); light.shadow.bias = -.0003; light.shadow.normalBias = .015;light.shadow.radius=2;
      const extent=q.shadow_extent??12;
      if (item.kind === 'directional') Object.assign(light.shadow.camera, { left: -extent, right: extent, top: extent, bottom: -extent, near: .1, far: 100 });
      scene.add(light);
    }
    for (const item of q.nodes) {
      const d = item.dimensions || [1, 1, 1]; let geometry, object;
      switch (item.kind) {
        case 'group': object = new THREE.Group(); break;
        case 'polygon': {
          const shape=new THREE.Shape();shape.moveTo(...item.points[0]);item.points.slice(1).forEach(point=>shape.lineTo(...point));shape.closePath();
          geometry=new THREE.ExtrudeGeometry(shape,{depth:item.depth??.035,bevelEnabled:false,steps:1});break;
        }
        case 'lathe': geometry=new THREE.LatheGeometry(item.profile.map(point=>new THREE.Vector2(...point)),64,radians(item.angle_start??0),radians(item.angle_length??360));break;
        case 'tube': geometry=new THREE.TubeGeometry(new THREE.CatmullRomCurve3(item.curve.map(point=>new THREE.Vector3(...point))),96,d[0],12,false);break;
        case 'model': {
          object=new THREE.Group();const asset=models.get(item.source),model=clone(asset.scene);object.add(model);
          model.traverse(mesh=>{if(mesh.isMesh){mesh.castShadow=item.cast_shadow!==false;mesh.receiveShadow=item.receive_shadow!==false;}});
          if(item.clip){const mixer=new THREE.AnimationMixer(model),clip=asset.animations.find(c=>c.name===item.clip);mixer.clipAction(clip).play();mixers.push({mixer,item});}break;
        }
        case 'sphere': geometry = new THREE.SphereGeometry(d[0], 32, 24); break;
        case 'capsule': geometry = new THREE.CapsuleGeometry(d[0], d[1], 8, 20); break;
        case 'cylinder': geometry = new THREE.CylinderGeometry(d[0], d[2], d[1], 32); break;
        case 'cone': geometry = new THREE.ConeGeometry(d[0], d[1], 32); break;
        case 'torus': geometry = new THREE.TorusGeometry(d[0], d[1], 16, 64); break;
        case 'knot': geometry = new THREE.TorusKnotGeometry(d[0], d[1], 96, 16); break;
        case 'plane': geometry = new THREE.PlaneGeometry(d[0], d[1]); break;
        case 'rounded_box': geometry = new RoundedBoxGeometry(...d, 3, Math.min(...d) * .12); break;
        default: geometry = new THREE.BoxGeometry(...d);
      }
      if (geometry) {
        const material = new THREE.MeshPhysicalMaterial({ color: color(item.color || '$accent', palette), roughness: item.roughness ?? .45, metalness: item.metalness ?? 0, clearcoat: item.clearcoat ?? .1, emissive: color(item.emissive || '#000000', palette), emissiveIntensity: item.emissive_intensity ?? 0, side: item.kind === 'plane' ? THREE.DoubleSide : THREE.FrontSide });
        if(item.texture && item.texture!=='none') {material.bumpMap=surface(item.texture,item.texture_scale??5);material.bumpScale=item.bump_strength??(item.texture==='wool'?.065:.018);if(item.texture==='brushed')material.roughnessMap=material.bumpMap;material.sheen=item.texture==='wool'?.8:item.texture==='canvas'?.35:0;material.sheenColor.copy(material.color);material.sheenRoughness=1;}
        object = item.repeat ? new THREE.InstancedMesh(geometry,material,item.repeat.count) : new THREE.Mesh(geometry, material); sceneGeometries.push(geometry); sceneMaterials.push(material);
        if(item.fibers){
          const f=item.fibers,seed=f.seed??[...item.id].reduce((a,c)=>a*31+c.charCodeAt(0),0),random=n=>{let x=Math.imul((n+seed)|0,1597334677);x^=x>>>16;return (Math.imul(x,2246822519)>>>0)/4294967296;};
          const hairGeometry=new THREE.ConeGeometry(f.thickness??f.length*.12,1,3,1),hairMaterial=new THREE.MeshPhysicalMaterial({color:material.color,roughness:1,metalness:0,sheen:1,sheenColor:material.color,sheenRoughness:1});
          const hairs=new THREE.InstancedMesh(hairGeometry,hairMaterial,f.count),dummy=new THREE.Object3D(),up=new THREE.Vector3(0,1,0),normal=new THREE.Vector3(),tint=new THREE.Color();
          for(let i=0;i<f.count;i++){
            const y=1-2*(i+.5)/f.count,angle=i*2.399963229728653+(random(i)-.5)*.18,r=Math.sqrt(Math.max(0,1-y*y)),length=f.length*(.55+random(i+11)*.7);
            normal.set(r*Math.cos(angle),y,r*Math.sin(angle));dummy.position.copy(normal).multiplyScalar(d[0]+length*.42);dummy.quaternion.setFromUnitVectors(up,normal);dummy.rotateX((random(i+7)-.5)*.65);dummy.scale.set(1,length,1);dummy.updateMatrix();hairs.setMatrixAt(i,dummy.matrix);
            const shade=.78+random(i+23)*.25;tint.setRGB(shade,shade,shade);hairs.setColorAt(i,tint);
          }
          hairs.instanceMatrix.needsUpdate=true;hairs.instanceColor.needsUpdate=true;hairs.receiveShadow=false;object.add(hairs);object.userData.fibers=hairs;sceneGeometries.push(hairGeometry);sceneMaterials.push(hairMaterial);
        }
        if(item.glow){
          let map=textures.get('emission-halo');if(!map){const cv=document.createElement('canvas');cv.width=cv.height=128;const cg=cv.getContext('2d'),gradient=cg.createRadialGradient(64,64,0,64,64,64);gradient.addColorStop(0,'rgba(255,255,255,.7)');gradient.addColorStop(.18,'rgba(255,255,255,.24)');gradient.addColorStop(1,'rgba(255,255,255,0)');cg.fillStyle=gradient;cg.fillRect(0,0,128,128);map=new THREE.CanvasTexture(cv);textures.set('emission-halo',map);}
          const haloMaterial=new THREE.SpriteMaterial({map,color:color(item.emissive||item.color||'#ffffff',palette),transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});const halo=new THREE.Sprite(haloMaterial);halo.scale.setScalar(item.glow*2);object.add(halo);object.userData.halo=halo;sceneMaterials.push(haloMaterial);
        }
        if(item.repeat)object.frustumCulled=false;
        object.castShadow = item.cast_shadow !== false; object.receiveShadow = item.receive_shadow !== false;
      }
      objects.set(item.id, object);
    }
    for (const item of q.nodes) (item.parent ? objects.get(item.parent) : scene).add(objects.get(item.id));
    return { scene, camera, objects, mixers,ambientLight,dispose(){sceneMaterials.forEach(x=>x.dispose());sceneGeometries.forEach(x=>x.dispose());mixers.forEach(({mixer})=>mixer.uncacheRoot(mixer.getRoot()));scene.traverse(object=>{object.shadow?.dispose();if(object.isInstancedMesh)object.dispose();});} };
  }
  function draw(g, box, palette, state, time, layer) {
    const q = layer.props;
    let entry = scenes.get(q.nodes);
    if (!entry) {
      if(scenes.size>=4){const first=scenes.keys().next().value;scenes.get(first).dispose();scenes.delete(first);}
      entry = build(q, palette);scenes.set(q.nodes,entry);
    } else {scenes.delete(q.nodes);scenes.set(q.nodes,entry);}
    const { scene, camera, objects, mixers, ambientLight } = entry;
    ambientLight.intensity=q.ambient??.7;scene.environmentIntensity=q.environment_intensity??.35;
    for(const {mixer,item} of mixers) mixer.setTime(time*(item.clip_speed??1)+(item.clip_offset??0));
    for (const item of q.nodes) {
      const object = objects.get(item.id), values = [...(item.position || [0, 0, 0]), ...(item.rotation || [0, 0, 0]), ...(item.scale || [1, 1, 1])];
      ['x','y','z','rx','ry','rz','sx','sy','sz'].forEach((key, i) => { if (item.tracks?.[key]) values[i] = track(item.tracks[key], time, values[i]); });
      if(item.motion){const m=item.motion,i=['x','y','z','rx','ry','rz'].indexOf(m.axis),phase=time*(m.speed??1)*Math.PI*2+(m.phase??0);values[i]+=m.amount*(m.kind==='spin'?phase/(Math.PI*2):Math.sin(phase));}
      object.position.set(...values.slice(0, 3)); object.rotation.set(...values.slice(3, 6).map(radians)); object.scale.set(...values.slice(6).map(value => Math.max(.001, value)));
      if(item.repeat){
        const q=item.repeat,dummy=new THREE.Object3D(),spread=item.tracks?.spread?track(item.tracks.spread,time,q.spread??0):q.spread??0,flip=item.tracks?.flip?track(item.tracks.flip,time,q.flip??0):q.flip??0,count=q.count;
        for(let i=0;i<count;i++){
          const unit=(i+.5)/count,angle=q.layout==='spiral'?unit*Math.PI*2*(q.turns??8):unit*Math.PI*2,radius=(q.radius??2)*(q.layout==='spiral'?Math.sqrt(unit):1)*(1+Math.max(0,spread));
          const side=Math.ceil(Math.sqrt(count));
          dummy.position.set(q.layout==='grid'?(i%side-(side-1)/2)*(q.radius??2)/side:Math.cos(angle)*radius,q.layout==='grid'?(Math.floor(i/side)-(side-1)/2)*(q.radius??2)/side:Math.sin(angle)*radius,(q.wave??0)*Math.sin(angle*3-time*1.5));
          dummy.rotation.set(Math.PI*Math.max(0,Math.min(1,flip)),0,q.layout==='grid'?0:angle+Math.PI/2);dummy.scale.setScalar(1);dummy.updateMatrix();object.setMatrixAt(i,dummy.matrix);
        }
        object.instanceMatrix.needsUpdate=true;
      }
      if(object.isMesh){
        const m=object.material;
        if(object.userData.halo)object.userData.halo.material.opacity=Math.min(1,(item.tracks?.emissive_intensity?track(item.tracks.emissive_intensity,time,item.emissive_intensity??1):item.emissive_intensity??1)/3);
        for(const [key,defaultValue] of Object.entries({roughness:.45,metalness:0,clearcoat:.1,emissive_intensity:0})) {
          const value=item.tracks?.[key]?track(item.tracks[key],time,item[key]??defaultValue):item[key]??defaultValue;
          m[key==='emissive_intensity'?'emissiveIntensity':key]=Math.max(0,Math.min(key==='emissive_intensity'?10:1,value));
        }
        for(const key of ['color','emissive']) {
          const frames=item.color_tracks?.[key];let value=color(item[key]||(key==='color'?'$accent':'#000000'),palette);
          if(frames){let a=frames[0],b=frames[0];for(let i=1;i<frames.length;i++){a=frames[i-1];b=frames[i];if(time<=b.time)break;}const amount=a===b?0:ease((time-a.time)/(b.time-a.time),b.ease),first=color(a.value,palette),last=color(b.value,palette);value='#'+[1,3,5].map(i=>Math.round(THREE.MathUtils.lerp(parseInt(first.slice(i,i+2),16),parseInt(last.slice(i,i+2),16),Math.max(0,Math.min(1,amount)))).toString(16).padStart(2,'0')).join('');}
          m[key].set(value);
        }
        if(item.texture==='wool')m.sheenColor.copy(m.color);
        if(object.userData.fibers){object.userData.fibers.material.color.copy(m.color);object.userData.fibers.material.sheenColor.copy(m.color);}
      }
    }
    const c = q.camera || {}, position = c.position || [6, 4, 9], target = c.target || [0, .5, 0], values = [...position, ...target, c.fov ?? 38];
    ['x','y','z','target_x','target_y','target_z','fov'].forEach((key, i) => { if (c.tracks?.[key]) values[i] = track(c.tracks[key], time, values[i]); });
    const width = Math.max(2, Math.round(box.w)), height = Math.max(2, Math.round(box.h));
    if (canvas.width !== width || canvas.height !== height) renderer.setSize(width, height, false);
    camera.position.set(...values.slice(0, 3)); camera.lookAt(...values.slice(3, 6)); camera.fov = Math.max(10, Math.min(100, values[6])); camera.aspect = width / height; camera.updateProjectionMatrix();
    renderer.toneMappingExposure = q.exposure ?? 1; renderer.shadowMap.enabled = q.shadows !== false;
    renderer.setClearColor('#000000', 0); renderer.render(scene, camera);
    const gl = renderer.getContext(), ext = gl.getExtension('WEBGL_debug_renderer_info');
    report(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'WebGL2');
    g.drawImage(canvas, -box.w / 2, -box.h / 2, box.w, box.h);
  }
  return { draw, async prepare(composition) {
    const sources=new Set(composition.scenes.flatMap(scene=>scene.layers.filter(layer=>layer.component==='scene3d').flatMap(layer=>layer.props.nodes.filter(node=>node.kind==='model').map(node=>node.source))));
    const loader=new GLTFLoader();
    for(const source of sources) {
      const asset=await loader.loadAsync(source);
      asset.scene.traverse(object=>{if(object.isMesh){geometries.push(object.geometry);materials.push(...(Array.isArray(object.material)?object.material:[object.material]));}});
      models.set(source,asset);
    }
  }, dispose() { scenes.forEach(x=>x.dispose());materials.forEach(x => x.dispose()); geometries.forEach(x => x.dispose()); textures.forEach(x=>x.dispose()); models.forEach(asset=>asset.scene.traverse(object=>{if(object.isMesh)for(const material of Array.isArray(object.material)?object.material:[object.material])for(const value of Object.values(material))if(value?.isTexture)value.dispose();})); environment.dispose(); renderer.dispose(); scenes.clear(); models.clear(); } };
}
