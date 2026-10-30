// renderer.js — WebGL2. Every tessera is a fan of triangles carrying its own
// centre, colours, material and flags; the vertex shader performs the
// night-wave flip and the water ripple, the fragment shader gives each
// material its surface (matte ceramic, glass, gold / silver leaf, water,
// emissive). Grout is a full-screen pass drawn first.
'use strict';

const Renderer = (() => {
  const STRIDE = 20; // floats per vertex
  // layout: pos2 center2 edge1 day3 night3 matD1 matN1 rnd1 tilt2 flags1 axis1 alpha1 extra1

  const VS = `#version 300 es
  precision highp float;
  layout(location=0) in vec2 aPos;
  layout(location=1) in vec2 aCenter;
  layout(location=2) in float aEdge;
  layout(location=3) in vec3 aDay;
  layout(location=4) in vec3 aNight;
  layout(location=5) in vec2 aMat;
  layout(location=6) in float aRnd;
  layout(location=7) in vec2 aTilt;
  layout(location=8) in float aFlags;
  layout(location=9) in float aAxis;
  layout(location=10) in float aAlpha;
  layout(location=11) in float aExtra;
  uniform vec2 uRes; uniform vec3 uCam; uniform float uTime;
  uniform vec2 uSun; uniform vec4 uNight; // start, speed, dur, jitter
  uniform vec4 uRip[6];
  uniform float uPass;
  uniform vec3 uBowl; uniform float uWaterY;
  out vec2 vLocal; out float vEdge; out vec3 vCol; out float vMat; out float vRnd;
  out vec2 vTilt; out float vFlags; out float vNight; out float vSheen; out float vAlpha;
  out vec2 vWorld; out float vExtra; out vec2 vCenter;
  void main(){
    int fl = int(aFlags + 0.5);
    bool dyn = (fl & 16) != 0;
    vec2 c = aCenter, p = aPos;
    vec2 tilt = aTilt;
    float ft = uNight.x + distance(c, uSun) / uNight.y;
    float night, sheen = 0.0, mat;
    vec3 col;
    if (!dyn) {
      ft += (aRnd - 0.5) * uNight.w;
      float fp = clamp((uTime - ft) / uNight.z, 0.0, 1.0);
      fp = fp * fp * (3.0 - 2.0 * fp);
      float ang = fp * 3.14159265;
      vec2 wd = normalize(c - uSun + vec2(1e-3));
      float ra = (aRnd - 0.5) * 0.6;
      wd = vec2(wd.x * cos(ra) - wd.y * sin(ra), wd.x * sin(ra) + wd.y * cos(ra));
      vec2 ax = vec2(-wd.y, wd.x);
      vec2 d = p - c;
      float lift = 1.0 + 0.16 * sin(ang);
      p = c + (ax * dot(d, ax) + wd * dot(d, wd) * abs(cos(ang))) * lift;
      night = fp > 0.5 ? 1.0 : 0.0;
      sheen = sin(ang);
      tilt += wd * sin(ang * 2.0) * 0.9;
      col = night > 0.5 ? aNight : aDay;
      mat = night > 0.5 ? aMat.y : aMat.x;
    } else {
      night = smoothstep(ft, ft + uNight.z * 1.6, uTime);
      col = aDay; mat = aMat.x;
    }
    // ripples through the water tiles
    if ((fl & 1) != 0) {
      vec2 disp = vec2(0.0);
      for (int i = 0; i < 6; i++) {
        vec4 r = uRip[i];
        float dt = uTime - r.z;
        if (dt <= 0.0) continue;
        vec2 dv = c - r.xy; dv.y *= 1.6;
        float rr = length(dv) + 1e-3;
        float front = 165.0 * dt;
        float w = 18.0 + 26.0 * dt;
        float env = 0.62 * r.w * exp(-dt * 1.35) * exp(-(rr - front) * (rr - front) / (2.0 * w * w));
        float ph = (rr - front) * 0.17;
        vec2 dir = dv / rr;
        disp += dir * env * sin(ph) * 0.8;
        float surf = smoothstep(uWaterY + 40.0, uWaterY - 8.0, c.y);
        disp.y += env * sin(ph + 0.8) * 0.9 * surf;
        tilt += dir * env * cos(ph) * 0.12;
      }
      // gentle slosh on the surface
      float surf = smoothstep(uWaterY + 26.0, uWaterY - 8.0, c.y);
      disp.y += sin(c.x * 0.045 + uTime * 1.7) * 0.9 * surf;
      tilt.x += cos(c.x * 0.045 + uTime * 1.7) * 0.05 * surf;
      p += disp; c += disp;
    }
    vLocal = p - c; vEdge = aEdge; vCol = col; vMat = mat; vRnd = aRnd; vTilt = tilt;
    vFlags = aFlags; vNight = night; vSheen = sheen;
    vAlpha = (uPass > 0.5 || dyn) ? aAlpha : 1.0;
    vWorld = p; vExtra = aExtra; vCenter = c;
    vec2 s = (p - uCam.xy) * uCam.z + uRes * 0.5;
    gl_Position = vec4(s.x / uRes.x * 2.0 - 1.0, 1.0 - s.y / uRes.y * 2.0, 0.0, 1.0);
  }`;

  const FS = `#version 300 es
  precision highp float;
  in vec2 vLocal; in float vEdge; in vec3 vCol; in float vMat; in float vRnd;
  in vec2 vTilt; in float vFlags; in float vNight; in float vSheen; in float vAlpha;
  in vec2 vWorld; in float vExtra; in vec2 vCenter;
  uniform float uTime, uGlint, uSunBand; uniform vec2 uGlintPos; uniform vec3 uBowl;
  uniform vec2 uRes; uniform vec3 uLightDay; uniform vec3 uLightNight;
  out vec4 o;
  float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
  float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
    return mix(mix(h21(i), h21(i+vec2(1,0)), f.x), mix(h21(i+vec2(0,1)), h21(i+vec2(1,1)), f.x), f.y); }
  void main(){
    int fl = int(vFlags + 0.5);
    int mat = int(vMat + 0.5);
    if (vExtra > 0.5 && (distance(vWorld, uBowl.xy) > uBowl.z - 5.0 || vWorld.y > uBowl.y + 168.0)) discard;
    float e = clamp(vEdge, 0.0, 1.0);
    vec2 rad = vLocal / max(length(vLocal), 1e-3);
    float bev = pow(1.0 - e, 3.2);
    vec2 micro = vec2(vn(vWorld * 0.9) - 0.5, vn(vWorld * 0.9 + 17.0) - 0.5);
    float rough = mat == 0 ? 0.1 : mat == 2 || mat == 3 ? 0.55 : 0.05;
    vec3 N = normalize(vec3(vTilt + rad * bev * 0.95 + micro * rough, 1.0));
    vec3 L = normalize(mix(uLightDay, uLightNight, vNight));
    vec3 H = normalize(L + vec3(0.0, 0.0, 1.0));
    float diff = max(dot(N, L), 0.0);
    float nh = max(dot(N, H), 0.0);
    vec3 lc = mix(vec3(1.0, 0.95, 0.84), vec3(0.78, 0.86, 1.0), vNight);
    vec3 base = vCol;
    // sunbeam sweeping across selected ceramic tiles (afternoon only)
    if ((fl & 32) != 0) {
      float b = dot(vCenter, vec2(0.8, 0.6));
      float beam = exp(-pow((b - uSunBand) / 75.0, 2.0)) * (1.0 - vNight);
      base *= 1.0 + 0.2 * beam;
    }
    vec3 c;
    float shade = 0.8 + 0.32 * diff;
    if (mat == 0) {           // matte ceramic
      float grain = 0.95 + 0.1 * h21(floor(vWorld * 1.3));
      c = base * shade * grain + lc * pow(nh, 14.0) * 0.07;
      c *= 0.9 + 0.1 * smoothstep(0.0, 0.3, e);
    } else if (mat == 1 || mat == 4) {   // glass / water glass
      float core = 0.93 + 0.1 * smoothstep(0.15, 0.8, e);
      c = base * (0.74 + 0.36 * diff) * core;
      float streak = sin((vLocal.x * 0.7 + vLocal.y * 0.45) + vRnd * 30.0);
      c += base * streak * 0.03;
      float catchL = 0.25 + 0.75 * pow(vRnd, 2.0);
      c += lc * pow(nh, 70.0) * 0.45 * catchL;
      if (mat == 4) {
        float t = uTime;
        float caus = 0.5 + 0.5 * sin(dot(vCenter, vec2(0.052, 0.071)) + t * 1.4 + 2.3 * sin(vCenter.y * 0.043 - t * 0.9 + vCenter.x * 0.012));
        caus *= 0.5 + 0.5 * sin(dot(vCenter, vec2(-0.061, 0.038)) - t * 1.1 + 1.7 * sin(vCenter.x * 0.031 + t * 0.7));
        caus = pow(caus, 3.0);
        c += mix(vec3(0.95, 1.0, 0.85) * 0.28, vec3(0.55, 0.7, 1.0) * 0.12, vNight) * caus;
      }
    } else if (mat == 2 || mat == 3) {   // gold / silver leaf
      vec3 tint = mat == 2 ? vec3(1.0, 0.8, 0.42) : vec3(0.9, 0.94, 1.0);
      c = base * (0.55 + 0.55 * diff);
      float g = pow(nh, 48.0);
      c += tint * g * 1.7 * lc + tint * pow(nh, 6.0) * 0.12;
      c *= 0.9 + 0.1 * smoothstep(0.0, 0.3, e);
    } else if (mat == 6) {    // grout bed under moving tiles
      c = base * (0.86 + 0.24 * h21(floor(vWorld * 2.0)));
    } else {                  // emissive (lit windows, stars)
      c = base * (1.05 + 0.25 * e);
      if ((fl & 4) != 0) c *= 0.92 + 0.2 * sin(uTime * (2.2 + vRnd * 3.0) + vRnd * 40.0);
    }
    // glint the fish notices
    if ((fl & 8) != 0 && uGlint > 0.001) {
      float gd = distance(vCenter, uGlintPos);
      float k = uGlint * exp(-gd * gd / (2.0 * 11.0 * 11.0));
      float tw = 0.55 + 0.45 * pow(0.5 + 0.5 * sin(uTime * 8.0 + vRnd * 30.0), 3.0);
      c = mix(c, vec3(1.0, 0.85, 0.45) * (0.9 + 0.5 * pow(nh, 8.0)), clamp(k * 1.1, 0.0, 1.0));
      c += vec3(1.0, 0.95, 0.8) * k * tw * 0.55 * (0.4 + 0.6 * e);
    }
    // the card-flip catches light mid-turn
    c *= 1.0 - 0.28 * vSheen;
    c += lc * pow(vSheen, 3.0) * 0.32 * (0.5 + 0.5 * diff);
    // fish under water: tinted and dimmed by the water
    if (vExtra > 0.001) {
      vec3 tint = mix(vec3(0.8, 0.97, 0.93), vec3(0.62, 0.8, 0.95), vNight);
      c = mix(c, c * tint + mix(vec3(0.02, 0.06, 0.05), vec3(0.0, 0.02, 0.06), vNight), 0.24 * min(vExtra, 1.0));
    }
    // dynamic tiles (fish, water ribbon) are relit by the moon as the wave passes
    if ((fl & 16) != 0) c = mix(c, c * vec3(0.8, 0.82, 1.0) + vec3(0.03, 0.04, 0.08), vNight * 0.55);
    // vignette
    vec2 q = gl_FragCoord.xy / uRes - 0.5;
    c *= mix(0.72, 1.0, smoothstep(0.85, 0.3, length(q * vec2(1.0, 1.25))));
    o = vec4(c, vAlpha);
  }`;

  const GVS = `#version 300 es
  void main(){ vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2); gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0); }`;
  const GFS = `#version 300 es
  precision highp float;
  uniform vec2 uRes; uniform vec3 uCam; uniform float uTime; uniform vec2 uSun; uniform vec4 uNight;
  uniform vec3 uGrout, uGroutDeep, uGroutNight;
  out vec4 o;
  float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
  float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
    return mix(mix(h21(i), h21(i+vec2(1,0)), f.x), mix(h21(i+vec2(0,1)), h21(i+vec2(1,1)), f.x), f.y); }
  void main(){
    vec2 s = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
    vec2 w = (s - uRes * 0.5) / uCam.z + uCam.xy;
    float ft = uNight.x + distance(w, uSun) / uNight.y;
    float night = smoothstep(ft, ft + uNight.z, uTime);
    float n = vn(w * 0.05) * 0.6 + vn(w * 0.4) * 0.4;
    vec3 c = mix(uGrout, uGroutDeep, n * 0.8);
    c = mix(c, uGroutNight, night * 0.85);
    c *= 0.86 + 0.24 * h21(floor(w * 2.0));
    vec2 q = gl_FragCoord.xy / uRes - 0.5;
    c *= mix(0.7, 1.0, smoothstep(0.85, 0.3, length(q * vec2(1.0, 1.25))));
    o = vec4(c, 1.0);
  }`;

  let gl, prog, gprog, U_ = {}, GU = {};
  let staticVao, staticCount, overlayStartIdx, overlayCount;
  let dynVao, dynVbo, dynIbo, dynV, dynI, dynVN = 0, dynIN = 0;
  const DYN_MAX_V = 60000, DYN_MAX_I = 180000;

  function compile(type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) + '\n' + src);
    return s;
  }
  function link(vs, fs) {
    const p = gl.createProgram();
    gl.attachShader(p, compile(gl.VERTEX_SHADER, vs)); gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  }
  function setupAttribs() {
    const B = STRIDE * 4;
    const sizes = [2, 2, 1, 3, 3, 2, 1, 2, 1, 1, 1, 1];
    let off = 0;
    sizes.forEach((sz, i) => { gl.enableVertexAttribArray(i); gl.vertexAttribPointer(i, sz, gl.FLOAT, false, B, off * 4); off += sz; });
  }

  // Append one tessera (fan around its centroid) to growable arrays.
  function pushTile(V, I, vn, poly, cx, cy, a) {
    const n = poly.length >> 1;
    const base = vn;
    const put = (x, y, edge) => {
      const o = vn * STRIDE;
      V[o] = x; V[o + 1] = y; V[o + 2] = cx; V[o + 3] = cy; V[o + 4] = edge;
      V[o + 5] = a.day[0]; V[o + 6] = a.day[1]; V[o + 7] = a.day[2];
      V[o + 8] = a.night[0]; V[o + 9] = a.night[1]; V[o + 10] = a.night[2];
      V[o + 11] = a.md; V[o + 12] = a.mn; V[o + 13] = a.rnd;
      V[o + 14] = a.tx; V[o + 15] = a.ty; V[o + 16] = a.flags; V[o + 17] = a.axis || 0;
      V[o + 18] = a.alpha; V[o + 19] = a.extra || 0;
      vn++;
    };
    put(cx, cy, 1);
    for (let i = 0; i < n; i++) put(poly[2 * i], poly[2 * i + 1], 0);
    const ii = [];
    for (let i = 0; i < n; i++) ii.push(base, base + 1 + i, base + 1 + ((i + 1) % n));
    return { vn, ii };
  }

  function init(canvas, staticTiles, overlayStart) {
    gl = canvas.getContext('webgl2', { antialias: true, preserveDrawingBuffer: true, alpha: false });
    if (!gl) throw new Error('WebGL2 not available');
    prog = link(VS, FS);
    gprog = link(GVS, GFS);
    for (const n of ['uRes', 'uCam', 'uTime', 'uSun', 'uNight', 'uRip', 'uPass', 'uBowl', 'uWaterY', 'uGlint', 'uSunBand',
      'uGlintPos', 'uLightDay', 'uLightNight']) U_[n] = gl.getUniformLocation(prog, n);
    for (const n of ['uRes', 'uCam', 'uTime', 'uSun', 'uNight', 'uGrout', 'uGroutDeep', 'uGroutNight']) GU[n] = gl.getUniformLocation(gprog, n);

    // ---- static mesh ----
    let nv = 0, ni = 0;
    for (const t of staticTiles) { nv += 1 + (t.poly.length >> 1); ni += 3 * (t.poly.length >> 1); }
    const V = new Float32Array(nv * STRIDE), I = new Uint32Array(ni);
    let vn = 0, inn = 0;
    overlayStartIdx = -1;
    staticTiles.forEach((t, k) => {
      if (k === overlayStart) overlayStartIdx = inn;
      const tr = U.hash1(k * 977 + 13);
      const r = pushTile(V, I, vn, t.poly, t.cx, t.cy, {
        day: t.day, night: t.night, md: t.md, mn: t.mn, rnd: t.rnd,
        tx: (U.hash1(k * 31 + 1) - 0.5) * 0.34, ty: (U.hash1(k * 53 + 2) - 0.5) * 0.34,
        flags: t.flags, axis: t.ang, alpha: t.alpha,
      });
      vn = r.vn; for (const x of r.ii) I[inn++] = x;
      void tr;
    });
    staticCount = inn;
    overlayCount = overlayStartIdx >= 0 ? inn - overlayStartIdx : 0;
    staticVao = gl.createVertexArray(); gl.bindVertexArray(staticVao);
    const vb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, vb); gl.bufferData(gl.ARRAY_BUFFER, V, gl.STATIC_DRAW);
    setupAttribs();
    const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, I, gl.STATIC_DRAW);

    // ---- dynamic mesh ----
    dynV = new Float32Array(DYN_MAX_V * STRIDE); dynI = new Uint32Array(DYN_MAX_I);
    dynVao = gl.createVertexArray(); gl.bindVertexArray(dynVao);
    dynVbo = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, dynVbo); gl.bufferData(gl.ARRAY_BUFFER, dynV.byteLength, gl.DYNAMIC_DRAW);
    setupAttribs();
    dynIbo = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, dynIbo); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, dynI.byteLength, gl.DYNAMIC_DRAW);
    gl.bindVertexArray(null);
  }

  // Dynamic tiles are collected in groups: 'under' (behind the fish), 'fish', 'over'.
  const groups = { under: [], bed: [], fish: [], over: [] };
  function beginDynamic() { for (const k in groups) groups[k].length = 0; }
  function addDynamic(group, poly, cx, cy, a) { groups[group].push({ poly, cx, cy, a }); }
  function flushDynamic() {
    let vn = 0, inn = 0;
    const ranges = {};
    for (const g of ['under', 'bed', 'fish', 'over']) {
      const start = inn;
      for (const d of groups[g]) {
        if (vn + 1 + (d.poly.length >> 1) >= DYN_MAX_V) break;
        const r = pushTile(dynV, dynI, vn, d.poly, d.cx, d.cy, d.a);
        vn = r.vn; for (const x of r.ii) dynI[inn++] = x;
      }
      ranges[g] = [start, inn - start];
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, dynVbo);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, dynV, 0, vn * STRIDE);
    return ranges;
  }

  function render(state) {
    const W = CONFIG.width, H = CONFIG.height, TM = CONFIG.timing, P = Scene.P;
    gl.viewport(0, 0, W, H);
    gl.disable(gl.DEPTH_TEST);
    // grout
    gl.disable(gl.BLEND);
    gl.useProgram(gprog);
    gl.uniform2f(GU.uRes, W, H);
    gl.uniform3f(GU.uCam, state.cam.x, state.cam.y, state.cam.zoom);
    gl.uniform1f(GU.uTime, state.t);
    gl.uniform2f(GU.uSun, CONFIG.scene.sun.x, CONFIG.scene.sun.y);
    gl.uniform4f(GU.uNight, TM.nightStart, TM.nightSpeed, TM.flipDur, TM.flipJitter);
    gl.uniform3fv(GU.uGrout, P.grout); gl.uniform3fv(GU.uGroutDeep, P.groutDeep); gl.uniform3fv(GU.uGroutNight, P.groutNight);
    gl.bindVertexArray(null);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    // tiles
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(prog);
    gl.uniform2f(U_.uRes, W, H);
    gl.uniform3f(U_.uCam, state.cam.x, state.cam.y, state.cam.zoom);
    gl.uniform1f(U_.uTime, state.t);
    gl.uniform2f(U_.uSun, CONFIG.scene.sun.x, CONFIG.scene.sun.y);
    gl.uniform4f(U_.uNight, TM.nightStart, TM.nightSpeed, TM.flipDur, TM.flipJitter);
    gl.uniform4fv(U_.uRip, state.ripples);
    const b = CONFIG.scene.bowl;
    gl.uniform3f(U_.uBowl, b.cx, b.cy, b.r);
    gl.uniform1f(U_.uWaterY, b.waterY);
    gl.uniform1f(U_.uGlint, state.glint);
    gl.uniform1f(U_.uSunBand, state.sunBand);
    gl.uniform2f(U_.uGlintPos, CONFIG.scene.glint.x, CONFIG.scene.glint.y);
    gl.uniform3fv(U_.uLightDay, state.lightDay);
    gl.uniform3fv(U_.uLightNight, state.lightNight);

    gl.uniform1f(U_.uPass, 0);
    gl.bindVertexArray(staticVao);
    gl.drawElements(gl.TRIANGLES, staticCount, gl.UNSIGNED_INT, 0);

    const ranges = flushDynamic();
    gl.bindVertexArray(dynVao);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, dynIbo);
    gl.bufferSubData(gl.ELEMENT_ARRAY_BUFFER, 0, dynI, 0, ranges.over[0] + ranges.over[1]);
    if (ranges.under[1]) gl.drawElements(gl.TRIANGLES, ranges.under[1], gl.UNSIGNED_INT, ranges.under[0] * 4);
    if (ranges.bed[1]) gl.drawElements(gl.TRIANGLES, ranges.bed[1], gl.UNSIGNED_INT, ranges.bed[0] * 4);
    if (ranges.fish[1]) gl.drawElements(gl.TRIANGLES, ranges.fish[1], gl.UNSIGNED_INT, ranges.fish[0] * 4);

    // glass in front of the fish: rim front arc and window reflections
    if (overlayCount > 0) {
      gl.uniform1f(U_.uPass, 1);
      gl.bindVertexArray(staticVao);
      gl.drawElements(gl.TRIANGLES, overlayCount, gl.UNSIGNED_INT, overlayStartIdx * 4);
      gl.uniform1f(U_.uPass, 0);
    }
    if (ranges.over[1]) {
      gl.bindVertexArray(dynVao);
      gl.drawElements(gl.TRIANGLES, ranges.over[1], gl.UNSIGNED_INT, ranges.over[0] * 4);
    }
    gl.bindVertexArray(null);
  }

  return { init, render, beginDynamic, addDynamic, dispose: () => gl.getExtension("WEBGL_lose_context")?.loseContext() };
})();
