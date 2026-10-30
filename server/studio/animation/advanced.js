/* Data-directed vector artwork and solid parametric geometry. No external renderer. */
(() => {
  'use strict';
  window.AnimationAdvanced = ({ color, clamp, lerp, stage }) => {
    const TAU = Math.PI * 2, cache = new Map(), paths = new Map(); let surface = null, surfaceAttempted = false;
    const normalize = v => { const n = Math.hypot(...v) || 1; return v.map(x => x / n); };
    const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    const dot = (a, b) => a.reduce((sum, x, i) => sum + x * b[i], 0);
    const add = (a, b) => a.map((x, i) => x + b[i]);
    const knot = u => [(2 + Math.cos(3 * u)) * Math.cos(2 * u) / 3, Math.sin(3 * u) / 3, (2 + Math.cos(3 * u)) * Math.sin(2 * u) / 3];
    const point = (kind, u, v, q) => {
      const tube = q.tube ?? .28;
      if (kind === 'sphere') return [Math.cos(u) * Math.sin(v / 2), Math.cos(v / 2), Math.sin(u) * Math.sin(v / 2)];
      if (kind === 'superquadric') { const f = x => Math.sign(x) * Math.abs(x) ** .48; return [f(Math.cos(u)) * f(Math.sin(v / 2)), f(Math.cos(v / 2)), f(Math.sin(u)) * f(Math.sin(v / 2))]; }
      if (kind === 'torus') return [(1 + tube * Math.cos(v)) * Math.cos(u), tube * Math.sin(v), (1 + tube * Math.cos(v)) * Math.sin(u)];
      if (kind === 'knot') { const center = knot(u), tangent = normalize(knot(u + .001).map((x, i) => x - center[i])), side = normalize(cross(tangent, [0, 1, 0])), up = normalize(cross(side, tangent)); return center.map((x, i) => x + tube * .65 * (side[i] * Math.cos(v) + up[i] * Math.sin(v))); }
      const width = (v / TAU * 2 - 1) * .38, twist = q.twist ?? 1;
      return [(1 + width * Math.cos(u * twist / 2)) * Math.cos(u), width * Math.sin(u * twist / 2), (1 + width * Math.cos(u * twist / 2)) * Math.sin(u)];
    };
    function geometry(kind, q) {
      const U = q.segments ?? 64, V = q.rings ?? 20, key = JSON.stringify([kind, U, V, q.tube, q.twist]);
      if (cache.has(key)) return cache.get(key);
      const vertices = [];
      for (let i = 0; i <= U; i++) for (let j = 0; j <= V; j++) {
        const u = i / U * TAU, v = j / V * TAU, value = point(kind, u, v, q), du = point(kind, u + .001, v, q).map((x, k) => x - value[k]), dv = point(kind, u, v + .001, q).map((x, k) => x - value[k]);
        let normal = normalize(cross(du, dv));
        if (kind !== 'ribbon') { const center = kind === 'knot' ? knot(u) : kind === 'torus' ? [Math.cos(u), 0, Math.sin(u)] : [0, 0, 0], outward = value.map((x, k) => x - center[k]); if (dot(normal, outward) < 0) normal = normal.map(x => -x); if (Math.hypot(...du) < .000001) normal = normalize(outward); }
        vertices.push({ value, normal });
      }
      const faces = [];
      for (let i = 0; i < U; i++) for (let j = 0; j < V; j++) { const a = i * (V + 1) + j, b = (i + 1) * (V + 1) + j; faces.push([a, b, b + 1, a + 1]); }
      const result = { vertices, faces }; if (cache.size > 32) cache.clear(); cache.set(key, result); return result;
    }
    function rotate(v, angles) {
      let [x, y, z] = v; const [a, b, c] = angles, ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b), cc = Math.cos(c), sc = Math.sin(c);
      [y, z] = [y * ca - z * sa, y * sa + z * ca]; [x, z] = [x * cb + z * sb, -x * sb + z * cb]; return [x * cc - y * sc, x * sc + y * cc, z];
    }
    const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    function createSurface() {
      const canvas = document.createElement('canvas'), gl = canvas.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: false, preserveDrawingBuffer: true });
      if (!gl) return null;
      const vertex = `attribute vec3 position;attribute vec3 normal;varying vec3 world;varying vec3 direction;uniform vec2 viewport;uniform float radius;uniform float distance;void main(){world=position;direction=normal;float w=distance-position.z;gl_Position=vec4(position.x*2.0*radius*distance/viewport.x,position.y*2.0*radius*distance/viewport.y,1.08333333*w-.8333333,w);}`;
      const fragment = `precision highp float;varying vec3 world;varying vec3 direction;uniform vec3 base;uniform vec3 light;uniform float distance;uniform float roughness;uniform float material;uniform float ambient;void main(){vec3 n=normalize(direction);if(!gl_FrontFacing)n=-n;vec3 view=normalize(vec3(0.,0.,distance)-world);vec3 l=normalize(light);vec3 h=normalize(l+view);float diffuse=max(0.,dot(n,l));float spec=pow(max(0.,dot(n,h)),mix(8.,128.,pow(1.-roughness,2.)));vec3 r=reflect(-view,n);float boxA=exp(-pow((r.y-.6)/.28,2.));float boxB=exp(-pow((r.x+.62)/.2,2.))*.55;float fresnel=pow(1.-max(0.,dot(n,view)),4.);vec3 linear=pow(base,vec3(2.2));vec3 lit=linear*(ambient*.45+.045+diffuse*.65);if(material>.5&&material<1.5){vec3 environment=vec3(.025,.035,.055)+vec3(.9,.85,.78)*(boxA*.8+boxB*.55)+vec3(.1,.16,.25)*fresnel;lit=linear*(.08+diffuse*.15)+environment*mix(vec3(1.),linear,.35);lit+=vec3(1.,.96,.89)*spec*.22;}else{lit+=vec3(1.,.96,.9)*spec*(material>1.5?.48:.07);lit+=vec3(.08,.11,.16)*fresnel*.3;}gl_FragColor=vec4(pow(max(lit,vec3(0.)),vec3(1./2.2)),1.);}`;
      function shader(type, source) { const value = gl.createShader(type); gl.shaderSource(value, source); gl.compileShader(value); if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) throw Error('Surface shader compilation failed: ' + gl.getShaderInfoLog(value)); return value; }
      const program = gl.createProgram(); gl.attachShader(program, shader(gl.VERTEX_SHADER, vertex)); gl.attachShader(program, shader(gl.FRAGMENT_SHADER, fragment)); gl.linkProgram(program); if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error('Surface shader link failed');
      const buffer = gl.createBuffer(); gl.useProgram(program); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      for (const [name, offset] of [['position', 0], ['normal', 12]]) { const location = gl.getAttribLocation(program, name); gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 24, offset); }
      const uniforms = Object.fromEntries(['viewport','radius','distance','base','light','roughness','material','ambient'].map(name => [name, gl.getUniformLocation(program, name)]));
      const debug = gl.getExtension('WEBGL_debug_renderer_info'), renderer = debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : 'WebGL';
      return { canvas, gl, program, buffer, uniforms, renderer };
    }
    function smoothSurface(vertices, geometry, q, b, radius, base, light, distance, kind) {
      if (!surfaceAttempted) { surfaceAttempted = true; surface = createSurface(); }
      if (!surface || q.wireframe) return null;
      const { canvas, gl, program, buffer, uniforms } = surface, resolution = Math.min(1.5, 2048 / Math.max(b.w,b.h));
      const width = Math.max(32, Math.ceil(b.w * resolution)), height = Math.max(32, Math.ceil(b.h * resolution));
      if (canvas.width !== width) canvas.width = width; if (canvas.height !== height) canvas.height = height;
      gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);
      if (kind === 'ribbon' || q.to === 'ribbon') gl.disable(gl.CULL_FACE); else { gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK); }
      const data = [];
      for (const ids of geometry.faces) {
        const face = ids.map(i => vertices[i]), faceNormal = cross(face[1].position.map((x,i)=>x-face[0].position[i]),face[2].position.map((x,i)=>x-face[0].position[i])), expected = face.reduce((n,v)=>add(n,v.normal),[0,0,0]);
        const order = dot(faceNormal,expected)<0 ? [0,2,1,0,3,2] : [0,1,2,0,2,3];
        for (const index of order) data.push(...face[index].position,...face[index].normal);
      }
      gl.useProgram(program);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.DYNAMIC_DRAW);
      gl.uniform2f(uniforms.viewport,canvas.width,canvas.height);gl.uniform1f(uniforms.radius,radius*resolution);gl.uniform1f(uniforms.distance,distance);gl.uniform3fv(uniforms.base,base.map(x=>x/255));gl.uniform3fv(uniforms.light,light);gl.uniform1f(uniforms.roughness,q.roughness??.22);gl.uniform1f(uniforms.material,q.material==='metal'?1:q.material==='matte'?0:2);gl.uniform1f(uniforms.ambient,q.ambient??.3);gl.drawArrays(gl.TRIANGLES,0,data.length/6);
      stage().surfaceRenderer(surface.renderer); return canvas;
    }
    function shade(normal, base, q, light) {
      const material = q.material || 'ceramic', ambient = q.ambient ?? .3, diffuse = Math.max(0, dot(normal, light)), half = normalize(add(light, [0, 0, 1])), roughness = q.roughness ?? (material === 'matte' ? .7 : .22);
      const specular = Math.max(0, dot(normal, half)) ** (5 + (1 - roughness) * 100), rim = Math.max(0, 1 - Math.abs(normal[2])) ** 3;
      let illumination = ambient + diffuse * .68, highlight = specular * (material === 'matte' ? .12 : .9);
      if (material === 'metal') { const stripe = Math.exp(-(((normal[1] - .26) / .19) ** 2)) + Math.exp(-(((normal[0] + .55) / .12) ** 2)) * .6; illumination = .18 + diffuse * .32 + stripe * .7; highlight += rim * .15; }
      return base.map((value, i) => Math.round(clamp(value * illumination + [255, 247, 233][i] * highlight + [90, 107, 143][i] * rim * .12, 0, 255)));
    }
    function mesh(g, b, palette, state, t, layer) {
      const { H } = stage(), q = layer.props, kind = q.kind || 'torus', a = geometry(kind, q), target = q.to ? geometry(q.to, q) : a, phase = clamp(state.phase), angles = [(state.rotation_x ?? q.rotation_x ?? 24) * Math.PI / 180, (state.rotation_y ?? q.rotation_y ?? 0) * Math.PI / 180 + t * (q.speed ?? .22), (state.rotation_z ?? q.rotation_z ?? -18) * Math.PI / 180], distance = q.perspective ?? 4;
      const radius = Math.min(b.w, b.h) * .36, base = rgb(color(q.color, palette, 'accent')), light = normalize([q.light_x ?? -.6, q.light_y ?? 1, q.light_z ?? 1.5]);
      const vertices = a.vertices.map((v, i) => {
        const position = rotate(v.value.map((x, j) => lerp(x, target.vertices[i].value[j], phase)), angles), normal = normalize(rotate(v.normal.map((x, j) => lerp(x, target.vertices[i].normal[j], phase)), angles)), perspective = distance / Math.max(.5, distance - position[2]);
        return { position, normal, x: position[0] * radius * perspective, y: -position[1] * radius * perspective, lit: shade(normal, base, q, light) };
      });
      const faces = a.faces.map(ids => { const points = ids.map(i => vertices[i]), center = points[0].position.map((_, j) => points.reduce((sum, v) => sum + v.position[j], 0) / 4), normal = normalize(points[0].normal.map((_, j) => points.reduce((sum, v) => sum + v.normal[j], 0))); return { points, normal, center, z: center[2] }; }).filter(face => kind === 'ribbon' || q.to === 'ribbon' || dot(face.normal, [-face.center[0], -face.center[1], distance - face.center[2]]) > -.025).sort((a, b) => a.z - b.z);
      const floor = b.h * .42;
      if (q.shadow !== false) { g.save(); g.globalAlpha *= .18; g.filter = `blur(${H * .02}px)`; g.beginPath(); g.ellipse(0, floor, radius * .84, radius * .11, 0, 0, TAU); g.fillStyle = palette.ink; g.fill(); g.restore(); }
      const smooth = smoothSurface(vertices, a, q, b, radius, base, light, distance, kind);
      if (smooth) {
        if (q.reflection) { g.save(); g.beginPath(); g.rect(-b.w, floor, b.w*2, b.h); g.clip(); g.translate(0,floor*2);g.scale(1,-1);g.globalAlpha*=q.reflection;g.drawImage(smooth,-b.w/2,-b.h/2,b.w,b.h);g.restore(); }
        g.drawImage(smooth,-b.w/2,-b.h/2,b.w,b.h);return;
      }
      if (!surface && !q.wireframe) stage().warning(layer.id,'WebGL is unavailable; using the faceted Canvas surface fallback.');
      const paintFaces = () => {
        for (const face of faces) {
          const points = face.points, ordered = [...points].sort((a, b) => a.lit.reduce((x, y) => x + y, 0) - b.lit.reduce((x, y) => x + y, 0)), low = ordered[0], high = ordered.at(-1);
          g.beginPath(); points.forEach((v, i) => i ? g.lineTo(v.x, v.y) : g.moveTo(v.x, v.y)); g.closePath();
          if (!q.wireframe) { const gradient = g.createLinearGradient(low.x, low.y, high.x + .01, high.y + .01); gradient.addColorStop(0, `rgb(${low.lit.join(',')})`); gradient.addColorStop(1, `rgb(${high.lit.join(',')})`); g.fillStyle = gradient; g.fill(); g.strokeStyle = gradient; g.lineWidth = .65; g.stroke(); }
          else { g.strokeStyle = color(q.color, palette, 'accent'); g.lineWidth = H * .0007; g.stroke(); }
        }
      };
      if (q.reflection) { g.save(); g.beginPath(); g.rect(-b.w, floor, b.w * 2, b.h); g.clip(); g.translate(0, floor * 2); g.scale(1, -1); g.globalAlpha *= q.reflection; paintFaces(); g.restore(); }
      paintFaces();
    }
    function vector(g, b, palette, state, t, layer) {
      const q = layer.props, [x, y, width, height] = q.view_box, scale = Math.min(b.w / width, b.h / height);
      g.save(); g.scale(q.fit==='stretch'?b.w/width:scale,q.fit==='stretch'?b.h/height:scale); g.translate(-x - width / 2, -y - height / 2);
      for (const item of q.paths) { if (!paths.has(item.d)) { if (paths.size > 512) paths.clear(); paths.set(item.d, new Path2D(item.d)); } const path = paths.get(item.d); g.save(); g.globalAlpha *= item.opacity ?? 1; if (item.fill) { g.fillStyle = state.paint || color(item.fill, palette); g.fill(path);
        if(q.texture&&q.texture!=='none') {
          g.save();g.clip(path);g.globalCompositeOperation='soft-light';g.globalAlpha*=q.texture==='ink'?.22:.13;
          for(let i=0;i<110;i++){const n=((Math.imul(i+1,1597334677)>>>0)/4294967295),m=((Math.imul(i+17,2246822519)>>>0)/4294967295),r=.12+(i%7)*.07;g.fillStyle=i%2?'#fff5df':'#383428';g.beginPath();g.ellipse(x+n*width,y+m*height,r,r*(1+i%3),i,0,Math.PI*2);g.fill();}g.restore();
        }
      } if (item.stroke) { g.strokeStyle = color(item.stroke, palette); g.lineWidth = item.width ?? 1; g.lineCap = 'round'; g.lineJoin = 'round'; g.stroke(path); } g.restore(); }
      g.restore();
    }
    return { mesh, vector, group: () => {} };
  };
})();
