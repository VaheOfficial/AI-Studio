/* Frame state is a pure function of composition, seed and time. */
(() => {
  'use strict';
  const TAU = Math.PI * 2;
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const rand = (i, seed = 0) => { let n = Math.imul((i + seed * 131) | 0, 1597334677); n ^= n >>> 16; n = Math.imul(n, 2246822519); return (n >>> 0) / 4294967296; };
  const hash = s => [...s].reduce((h, c) => (Math.imul(h, 31) + c.charCodeAt(0)) | 0, 0);
  const ease = (x, kind = 'smooth') => {
    x = clamp(x);
    if (kind === 'linear') return x;
    if (kind === 'step') return x >= 1 ? 1 : 0;
    if (kind === 'cubic_in') return x ** 3;
    if (kind === 'cubic_out') return 1 - (1 - x) ** 3;
    if (kind === 'cubic_in_out') return x < .5 ? 4 * x ** 3 : 1 - (-2 * x + 2) ** 3 / 2;
    if (kind === 'back_out') return 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2;
    if (kind === 'elastic_out') return x === 0 || x === 1 ? x : 2 ** (-10 * x) * Math.sin((x * 10 - .75) * TAU / 3) + 1;
    if (kind === 'bounce_out') { const n = 7.5625, d = 2.75; if (x < 1 / d) return n * x * x; if (x < 2 / d) return n * (x -= 1.5 / d) * x + .75; if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + .9375; return n * (x -= 2.625 / d) * x + .984375; }
    return x * x * (3 - 2 * x);
  };
  function track(frames, t, initial) {
    if (!frames?.length) return initial;
    if (t <= frames[0].time) return frames[0].value;
    for (let i = 1; i < frames.length; i++) if (t <= frames[i].time) {
      const a = frames[i - 1], b = frames[i], mode=b.interpolation || 'eased', logarithmic=mode==='log'||mode==='monotone_log';
      const value=k=>logarithmic?Math.log(frames[k].value):frames[k].value, duration=b.time-a.time, u=(t-a.time)/duration;
      let result;
      if(mode==='monotone'||mode==='monotone_log') {
        const slope=k=>(value(k+1)-value(k))/(frames[k+1].time-frames[k].time);
        const tangent=k=>{
          if(k===0||k===frames.length-1)return 0;
          const left=slope(k-1),right=slope(k);if(left*right<=0)return 0;
          const h0=frames[k].time-frames[k-1].time,h1=frames[k+1].time-frames[k].time,w0=2*h1+h0,w1=h1+2*h0;
          return (w0+w1)/(w0/left+w1/right);
        };
        result=(2*u**3-3*u*u+1)*value(i-1)+(u**3-2*u*u+u)*duration*tangent(i-1)+(-2*u**3+3*u*u)*value(i)+(u**3-u*u)*duration*tangent(i);
      } else result=lerp(value(i-1),value(i),ease(u,b.ease));
      return logarithmic?Math.exp(result):result;
    }
    return frames.at(-1).value;
  }
  let spec, canvas, ctx, W, H, palettes, sceneStarts, assets = {}, reports = [], grainCache = {}, surfaceRenderer = null;
  const color = (value, p, fallback = 'ink') => value?.startsWith('$') ? p[value.slice(1)] : value || p[fallback];
  const font = (kind = 'body', size = 32, weight = 500) => `${weight} ${size}px ${kind === 'serif' ? 'Georgia,serif' : kind === 'mono' ? 'StageMono,monospace' : kind === 'condensed' ? 'StageCondensed,"Arial Narrow",sans-serif' : kind === 'rounded' ? '"Trebuchet MS",sans-serif' : ['body','display'].includes(kind) ? 'StageSans,Arial,sans-serif' : `StageFont_${kind},sans-serif`}`;
  function rounded(g, x, y, w, h, r = 0) { g.beginPath(); g.roundRect(x, y, Math.max(.001, w), Math.max(.001, h), Math.max(0, Math.min(r, w / 2, h / 2))); }
  function line(g, points, fill, stroke, width = 2, closed = false) { g.beginPath(); points.forEach((p, i) => i ? g.lineTo(...p) : g.moveTo(...p)); if (closed) g.closePath(); if (fill) { g.fillStyle = fill; g.fill(); } if (stroke) { g.strokeStyle = stroke; g.lineWidth = width; g.stroke(); } }
  function circle(g, x, y, radius, fill, stroke, width = 1) { g.beginPath(); g.arc(x, y, Math.max(0, radius), 0, TAU); if (fill) { g.fillStyle = fill; g.fill(); } if (stroke) { g.strokeStyle = stroke; g.lineWidth = width; g.stroke(); } }
  function label(g, text, x, y, size, fill, align = 'center', weight = 500, face = 'body') { g.font = font(face, size, weight); g.textAlign = align; g.textBaseline = 'middle'; g.fillStyle = fill; g.fillText(text, x, y); }
  function fitLines(g, text, width, size, face, weight) {
    const lines = [];
    for (const paragraph of String(text).split('\n')) {
      let current = '';
      for (const word of paragraph.split(/\s+/)) {
        g.font=font(face,size,weight);
        if(g.measureText(word).width>width) {
          if(current){lines.push(current);current='';}
          for(const {segment} of new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(word)) {
            if(current&&g.measureText(current+segment).width>width){lines.push(current);current=segment;}else current+=segment;
          }
        } else {const next=current?`${current} ${word}`:word;if(current&&g.measureText(next).width>width){lines.push(current);current=word;}else current=next;}
      }
      lines.push(current);
    }
    return lines;
  }
  const draw = {};
  const materials=window.AnimationMaterials({color});draw.brush=materials.brush;
  const fluidRenderer=window.AnimationFluid({color});draw.fluid=fluidRenderer.draw;
  draw.tiles = (g,b,p,s,t,layer) => {
    const q=layer.props,cols=q.columns||72,rows=q.rows||42,cw=b.w/cols,ch=b.h/rows,release=clamp(s.phase),gap=q.gap??.12,material=q.material||'glass';
    const rgb=value=>{const c=color(value,p);return [1,3,5].map(i=>parseInt(c.slice(i,i+2),16));};
    const figure=rgb(q.color||'$accent'),ground=rgb(q.background_color||'$muted'),seed=spec.seed+hash(layer.id);
    let artwork;
    if(q.source) {
      const key=layer.id+':tiles:'+q.source+':'+cols+':'+rows;
      if(!assets[key]){const cv=document.createElement('canvas');cv.width=cols;cv.height=rows;const cg=cv.getContext('2d');cg.fillStyle=color(q.background_color||'$muted',p);cg.fillRect(0,0,cols,rows);cg.drawImage(assets[layer.id+':'+q.source],0,0,cols,rows);assets[key]=cg.getImageData(0,0,cols,rows).data;}
      artwork=assets[key];
    }
    const inside=(x,y)=>q.formation==='bird'?(Math.abs(x)<.08&&Math.abs(y)<.19||Math.abs(x)<.37&&y>-.22+Math.abs(x)*.65&&y<.08-Math.abs(x)*.12):q.formation==='moon'?x*x+y*y<.12&&(x-.13)**2+(y+.03)**2>.085:q.formation==='circle'?x*x+y*y<.1:((x/.28)**2+(y/.17)**2<1||x<-.22&&x>-.4&&Math.abs(y)<(-x-.2)*.8);
    const tiles=[];
    for(let y=0;y<rows;y++)for(let x=0;x<cols;x++) {
      const nx=(x+.5)/cols-.5,ny=(y+.5)/rows-.5,i=y*cols+x,member=inside(nx,ny),delay=(nx+.5)*.2;
      const a=member?clamp((release-delay)/(1-delay)):0,flutter=(q.flutter??.006)*a*Math.sin(Math.PI*a),body=(q.wave??.025)*Math.sin(nx*15-t*(q.speed??1)*3)*a;
      const px=(nx+(q.travel_x??0)*a+Math.sin(t*2+rand(i,seed)*TAU)*flutter)*b.w,py=(ny+(q.travel_y??0)*a+body+Math.cos(t*2.7+rand(i+1,seed)*TAU)*flutter)*b.h;
      const lift=Math.sin(a*Math.PI*.75)*.5,z=member?lift:0,angle=clamp(((q.flip??0)-nx*.2-.1)/.8)*Math.PI+rand(i,seed)*.08;
      let base=angle>Math.PI/2?(member?rgb('$glow'):rgb(q.night_color||'$background')):artwork?Array.from(artwork.slice(i*4,i*4+3)):member?figure:ground;
      if(member&&!artwork) {
        if(!inside(nx-1/cols,ny)||!inside(nx+1/cols,ny)||!inside(nx,ny-1/rows)||!inside(nx,ny+1/rows))base=rgb('$secondary');
        else if(q.formation==='fish'&&(nx-.19)**2+(ny+.04)**2<.00065)base=rgb('$ink');
        else if(q.formation==='fish'&&(nx-.19)**2+(ny+.04)**2<.0015)base=rgb('$paper');
        else if(q.formation==='fish'&&Math.abs(ny)<.13&&Math.sin(nx*48+ny*32)> .65)base=base.map(v=>Math.min(255,v*1.16));
      }
      const light=q.light_phase??t*.6,shade=.77+rand(i+2,seed)*.23+(material==='gold'?.35*Math.max(0,Math.sin(light+nx*5+ny*3))**12:.12*Math.max(0,Math.sin(light+nx*8+ny*4))**24);
      tiles.push({px,py,z,angle,base,shade,i,member});
    }
    tiles.sort((a,b)=>a.z-b.z);
    for(const tile of tiles) {
      const width=cw*(1-gap)*(1+tile.z*.16)*Math.max(.05,Math.abs(Math.cos(tile.angle))),height=ch*(1-gap)*(1+tile.z*.16),x=tile.px-width/2,y=tile.py-height/2;
      g.save();g.translate(tile.px,tile.py);g.rotate((rand(tile.i+3,seed)-.5)*.08);g.translate(-tile.px,-tile.py);
      if(tile.z>.05){g.fillStyle=`rgba(10,20,25,${tile.z*.35})`;g.fillRect(x+tile.z*cw*.8,y+tile.z*ch,width,height);}
      g.fillStyle='rgb('+tile.base.map(v=>Math.round(Math.min(255,v*tile.shade))).join(',')+')';g.fillRect(x,y,width,height);
      if(material!=='paper'){g.globalAlpha*=.16;g.fillStyle='#fff9e9';g.fillRect(x,y,width,Math.max(.5,ch*.08));g.fillRect(x,y,Math.max(.5,cw*.07),height);g.globalAlpha/= .16;g.fillStyle='#081923';g.globalAlpha*=.14;g.fillRect(x,y+height-ch*.07,width,ch*.07);}
      g.restore();
    }
  };
  draw.text = (g, b, p, s, t, layer) => {
    const q = layer.props, face = q.font || 'display', weight = q.weight || 700, align = q.align || 'center';
    if(q.size===0)return;
    g.direction=q.direction==='rtl'?'rtl':q.direction==='ltr'?'ltr':'inherit';
    g.letterSpacing = `${(q.tracking ?? 0) * H}px`;
    let size = (q.size || .11) * H, lines = fitLines(g, q.text, b.w, size, face, weight), lineHeight = q.line_height || 1.08;
    while ((lines.length * size * lineHeight > b.h || lines.some(v => g.measureText(v).width > b.w)) && size > H * .015) { size *= .94; lines = fitLines(g, q.text, b.w, size, face, weight); }
    if (size < H * .022) reports.push({ layer: layer.id, warning: 'Text became small; shorten copy or increase its box.' });
    const x = align === 'left' ? -b.w / 2 : align === 'right' ? b.w / 2 : 0;
    const top = -(lines.length - 1) * size * lineHeight / 2;
    let index = 0;
    for (let j = 0; j < lines.length; j++) {
      const y = top + j * size * lineHeight, content = lines[j];
      if (q.mode === 'lines') {
        const a = ease((t - j * (q.stagger ?? .12)) / (q.duration ?? .8), q.overshoot ? 'back_out' : 'cubic_out');
        g.save(); if (q.clip !== false) { g.beginPath(); g.rect(-b.w / 2 - 2, y - size * .63, b.w + 4, size * 1.3); g.clip(); }
        g.translate(0, (1 - a) * size * (q.travel ?? 1.1)); g.globalAlpha *= clamp(a * 1.4); if (q.effect === 'blur') g.filter = `blur(${(1 - clamp(a)) * size * .15}px)`;
        label(g, content, x, y, size, s.paint || color(q.color, p), align, weight, face); g.restore();
      } else if (q.mode === 'words' || q.mode === 'letters') {
        g.letterSpacing = '0px';
        const letters = q.mode === 'letters', parts = letters ? Array.from(new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(content),item=>item.segment) : content.split(' '), spacing = letters ? (q.tracking ?? .003) * H : size * .25;
        if(q.direction==='rtl')parts.reverse();
        g.font = font(face, size, weight); const widths = parts.map(v => g.measureText(v).width), total = widths.reduce((a, v) => a + v, 0) + spacing * (parts.length - 1);
        let left = align === 'left' ? -b.w / 2 : align === 'right' ? b.w / 2 - total : -total / 2;
        for (let i = 0; i < parts.length; i++) { const a = ease((t - index++ * (q.stagger ?? (letters ? .025 : .1))) / (q.duration ?? .65), q.overshoot ? 'back_out' : 'cubic_out'); g.save(); if (q.clip) { g.beginPath(); g.rect(left - 2, y - size * .6, widths[i] + 4, size * 1.25); g.clip(); } g.globalAlpha *= clamp(a * 1.5); g.translate(left + widths[i] / 2, y + (1 - a) * size * (q.travel ?? .65)); if (q.effect === 'rotate') g.rotate((1 - a) * -.35); if (q.effect === 'scale') g.scale(.3 + .7 * a, .3 + .7 * a); if (q.effect === 'blur') g.filter = `blur(${(1 - clamp(a)) * size * .18}px)`; label(g, parts[i], -widths[i] / 2, 0, size, s.paint || color(q.color, p), 'left', weight, face); g.restore(); left += widths[i] + spacing; }
      } else if (q.mode === 'outline') { g.font = font(face, size, weight); g.textAlign = align; g.textBaseline = 'middle'; g.strokeStyle = color(q.color, p); g.lineWidth = Math.max(1, size * .018); g.strokeText(content, x, y); }
      else label(g, layer.enter === 'type' ? content.slice(0, Math.floor(content.length * s.reveal)) : content, x, y, size, s.paint || color(q.color, p), align, weight, face);
    }
  };
  function shapePoints(kind, count, phase = 0, rays = 5, inner = .48) {
    const points = [];
    for (let i = 0; i < count; i++) {
      const a = i / count * TAU - Math.PI / 2; let r = .5;
      if (kind === 'star') r = Math.cos(a * rays) > 0 ? .5 : inner * .5;
      if (kind === 'blob') r *= .86 + .14 * Math.sin(3 * a + phase) + .06 * Math.sin(5 * a - phase);
      if (kind === 'rect') { const m = Math.max(Math.abs(Math.cos(a)), Math.abs(Math.sin(a))); r /= m; }
      if (kind === 'triangle') { const sector = ((a + Math.PI / 2 + Math.PI / 3) % (TAU / 3) + TAU / 3) % (TAU / 3) - Math.PI / 3; r = .25 / Math.cos(sector); }
      points.push([Math.cos(a) * r, Math.sin(a) * r]);
    }
    return points;
  }
  draw.shape = (g, b, p, s, t, layer) => {
    const q = layer.props, kind = q.kind || 'circle', fill = s.paint || color(q.fill, p, 'accent'), stroke = q.stroke ? color(q.stroke, p) : null;
    if (kind === 'ring' && !q.to) { g.beginPath(); g.arc(0, 0, Math.min(b.w, b.h) / 2, -Math.PI / 2, -Math.PI / 2 + TAU * s.reveal); g.strokeStyle = fill; g.lineWidth = (q.line_width || .025) * H; g.stroke(); return; }
    if (kind === 'rect' && !q.to) { rounded(g, -b.w / 2, -b.h / 2, b.w, b.h, (q.corners ?? .04) * H); g.fillStyle = fill; g.fill(); if (stroke) { g.strokeStyle = stroke; g.lineWidth = (q.line_width || .004) * H; g.stroke(); } return; }
    const a = shapePoints(kind, 80, t * .8, q.points || 5, q.inner ?? .48), c = shapePoints(q.to || kind, 80, t * .8, q.points || 5, q.inner ?? .48), m = clamp(s.phase);
    const points = a.map((v, i) => [lerp(v[0], c[i][0], m) * b.w, lerp(v[1], c[i][1], m) * b.h]);
    line(g, points.slice(0, Math.max(3, Math.floor(points.length * s.reveal))), fill, stroke, (q.line_width || .004) * H, true);
  };
  draw.path = (g, b, p, s, t, layer) => {
    const q = layer.props, controls = q.points.map(v => [v[0] * b.w, v[1] * b.h]), pts = [], lengths = [];
    if (q.curve === 'smooth') { for (let i = 0; i < controls.length - 1; i++) { const a = controls[Math.max(0, i - 1)], b = controls[i], c = controls[i + 1], d = controls[Math.min(controls.length - 1, i + 2)]; for (let j = 0; j < 20; j++) { const u = j / 20; pts.push([0, 1].map(k => .5 * ((2 * b[k]) + (-a[k] + c[k]) * u + (2 * a[k] - 5 * b[k] + 4 * c[k] - d[k]) * u * u + (-a[k] + 3 * b[k] - 3 * c[k] + d[k]) * u * u * u))); } } pts.push(controls.at(-1)); } else pts.push(...controls);
    const total = pts.slice(1).reduce((n, v, i) => { const d = Math.hypot(v[0] - pts[i][0], v[1] - pts[i][1]); lengths.push(d); return n + d; }, 0), begin = clamp(s.trim_start ?? q.trim_start ?? 0) * total, end = clamp(s.trim_end ?? q.trim_end ?? s.reveal) * total;
    let distance = 0, visible = [], marker = pts[0];
    for (let i = 0; i < lengths.length; i++) { const length = lengths[i]; if (length > 0 && distance + length >= begin && distance <= end) { const from = clamp((begin - distance) / length), to = clamp((end - distance) / length), start = pts[i].map((x, k) => lerp(x, pts[i + 1][k], from)); marker = pts[i].map((x, k) => lerp(x, pts[i + 1][k], to)); if (!visible.length) visible.push(start); visible.push(marker); } distance += length; }
    if (q.dash) g.setLineDash([H * .009, H * .007]); g.lineCap = 'round'; g.lineJoin = 'round';
    if (visible.length) line(g, visible, q.fill ? color(q.fill, p) : null, s.paint || color(q.color, p, 'accent'), (q.line_width || .006) * H, q.closed);
    g.setLineDash([]); if (q.marker && visible.length) circle(g, ...marker, H * (q.marker_size ?? .012), p.secondary);
  };
  function particle(i, n, pattern, time, seed) {
    const u = (i + .5) / n, a = i * 2.3999632297 + time;
    if (pattern === 'sphere') { const y = 1 - 2 * u, r = Math.sqrt(1 - y * y); return [Math.cos(a) * r, y, Math.sin(a) * r]; }
    if (pattern === 'torus') { const v = i / n * TAU * 13, r = .68 + .3 * Math.cos(v); return [Math.cos(a) * r, Math.sin(v) * .3, Math.sin(a) * r]; }
    if (pattern === 'helix') return [Math.cos(a * .22) * .6, u * 2 - 1, Math.sin(a * .22) * .6];
    if (pattern === 'wave') return [u * 2 - 1, Math.sin(u * 16 - time * 2) * .4, Math.cos(a) * .35];
    if (pattern === 'grid') { const side = Math.ceil(Math.sqrt(n)); return [(i % side) / side * 2 - 1, Math.floor(i / side) / side * 2 - 1, Math.sin(a) * .1]; }
    return [Math.cos(a) * Math.sqrt(u), Math.sin(a) * Math.sqrt(u), rand(i, seed) * 2 - 1];
  }
  draw.particles = (g, b, p, s, t, layer) => {
    const q = layer.props, n = q.count || 240, seed = spec.seed + hash(layer.id), points = [];
    for (let i = 0; i < n; i++) { const a = particle(i, n, q.pattern || 'sphere', t * (q.speed ?? .35), seed), c = particle(i, n, q.to || q.pattern || 'sphere', t * (q.speed ?? .35), seed), v = a.map((x, j) => lerp(x, c[j], clamp(s.phase))); const z = 1 + v[2] * (q.depth ?? .3), radius = Math.min(b.w,b.h)*.43; points.push({ x: v[0] * radius * z * s.spread, y: v[1] * radius * z * s.spread, z, i }); }
    points.sort((a, b) => a.z - b.z);
    for (const v of points) { g.globalAlpha = s.alpha * clamp(v.z * .65) * s.reveal; circle(g, v.x, v.y, H * (q.size || .0028) * v.z, color(q.color, p, v.i % 7 === 0 ? 'secondary' : 'accent')); }
    g.globalAlpha = s.alpha;
    if (q.links) for (let i = 1; i < points.length; i += 4) { const a = points[i - 1], c = points[i]; if (Math.hypot(a.x - c.x, a.y - c.y) < b.w * .18) { g.globalAlpha = s.alpha * .12; line(g, [[a.x, a.y], [c.x, c.y]], null, p.accent, 1); } }
  };
  draw.grid = (g, b, p, s, t, layer) => {
    const q = layer.props, spacing = (q.spacing || .07) * H, c = color(q.color, p, 'line'); g.globalAlpha *= .6;
    if (q.kind === 'perspective') { for (let i = -12; i <= 12; i++) line(g, [[i * b.w * .013, -b.h / 2], [i * b.w * .13, b.h / 2]], null, c, 1); for (let i = 0; i < 16; i++) { const d = ((i / 16 + t * (q.speed || .06)) % 1) ** 2; line(g, [[-b.w / 2, -b.h / 2 + d * b.h], [b.w / 2, -b.h / 2 + d * b.h]], null, c, 1); } return; }
    for (let x = -b.w / 2; x <= b.w / 2; x += spacing) for (let y = -b.h / 2; y <= b.h / 2; y += spacing) { if (q.kind === 'lines') { line(g, [[x, -b.h / 2], [x, b.h / 2]], null, c, 1); break; } const r = q.kind === 'halftone' ? spacing * .35 * (.3 + .7 * Math.abs(Math.sin(x / b.w * 4 + y / b.h * 3))) : (q.size || .0015) * H; circle(g, x, y, r, c); }
    if (q.kind === 'lines') for (let y = -b.h / 2; y <= b.h / 2; y += spacing) line(g, [[-b.w / 2, y], [b.w / 2, y]], null, c, 1);
  };
  draw.chart = (g, b, p, s, t, layer) => {
    const q = layer.props, values = q.values, maximum = Math.max(...values, 1), left = -b.w / 2, bottom = b.h / 2 - H * .04, usable = b.h - H * .1;
    g.globalAlpha *= .45; for (let i = 0; i < 5; i++) line(g, [[left, bottom - usable * i / 4], [b.w / 2, bottom - usable * i / 4]], null, p.line, 1); g.globalAlpha = s.alpha;
    const points = [];
    values.forEach((v, i) => { const a = ease(clamp((t - i * .09) / .9), 'cubic_out') * s.reveal, x = left + (i + .5) / values.length * b.w, y = bottom - usable * v / maximum * a; points.push([x, y]); if (q.kind !== 'line') { const width = b.w / values.length * .6; rounded(g, x - width / 2, y, width, Math.max(.1, bottom - y), H * .006); g.fillStyle = color(q.color, p, i % 2 ? 'secondary' : 'accent'); g.fill(); } if (q.labels?.[i]) label(g, q.labels[i], x, bottom + H * .029, H * .019, p.ink); if (q.show_values) label(g, String(Math.round(v * a)), x, y - H * .025, H * .027, p.ink, 'center', 600); });
    if (q.kind === 'line') { line(g, points, null, color(q.color, p, 'accent'), H * .006); for (const pt of points) circle(g, ...pt, H * .006, p.secondary); }
  };
  draw.diagram = (g, b, p, s, t, layer) => {
    const q = layer.props, nodes = Object.fromEntries(q.nodes.map(n => [n.id, n])), pos = n => [(n.x - .5) * b.w, (n.y - .5) * b.h];
    for (let i = 0; i < q.edges.length; i++) { const edge = q.edges[i], a = pos(nodes[edge[0]]), c = pos(nodes[edge[1]]), f = (t * .4 + i * .17) % 1; line(g, [a, c], null, p.line, H * .003); const angle = Math.atan2(c[1] - a[1], c[0] - a[0]); g.save(); g.translate(lerp(a[0], c[0], .8), lerp(a[1], c[1], .8)); g.rotate(angle); line(g, [[-H * .008, -H * .006], [0, 0], [-H * .008, H * .006]], null, p.muted, 2); g.restore(); circle(g, lerp(a[0], c[0], f), lerp(a[1], c[1], f), H * .005, color(q.color, p, 'accent')); }
    q.nodes.forEach((n, i) => { const [x, y] = pos(n), width = Math.min(b.w * .24, H * .2), height = H * .09, active = q.active === undefined ? Math.floor(t * .6) % q.nodes.length === i : q.active === i; rounded(g, x - width / 2, y - height / 2, width, height, H * .01); g.fillStyle = active ? p.accent : p.paper; g.fill(); g.strokeStyle = p.line; g.lineWidth = 1; g.stroke(); label(g, n.label, x, y, Math.min(H * .024, width / Math.max(n.label.length, 4) * 1.45), active ? p.background : p.ink, 'center', 600); });
  };
  draw.interface = (g, b, p, s, t, layer) => {
    const q = layer.props, kind = q.kind || 'card', dark = q.variant === 'dark', bg = dark ? p.ink : p.paper, ink = dark ? p.paper : p.ink;
    if (kind === 'cursor') { line(g, [[0, 0], [H * .033, H * .083], [H * .04, H * .053], [H * .07, H * .051]], p.paper, p.ink, H * .002, true); return; }
    if (kind === 'toggle') { rounded(g, -b.w / 2, -b.h / 2, b.w, b.h, b.h / 2); g.fillStyle = color(q.color, p, s.phase > .5 ? 'accent' : 'muted'); g.fill(); circle(g, lerp(-b.w / 2 + b.h / 2, b.w / 2 - b.h / 2, clamp(s.phase)), 0, b.h * .36, p.paper); return; }
    g.save(); g.shadowColor = '#00000030'; g.shadowBlur = H * .035; g.shadowOffsetY = H * .012; rounded(g, -b.w / 2, -b.h / 2, b.w, b.h, H * (kind === 'phone' ? .045 : .025)); g.fillStyle = bg; g.fill(); g.restore();
    if (kind === 'browser') { for (let i = 0; i < 3; i++) circle(g, -b.w / 2 + H * (.025 + i * .018), -b.h / 2 + H * .028, H * .004, i === 0 ? p.secondary : p.muted); line(g, [[-b.w / 2, -b.h / 2 + H * .055], [b.w / 2, -b.h / 2 + H * .055]], null, p.line, 1); }
    if (kind === 'phone') { rounded(g, -b.w * .2, -b.h / 2 + H * .018, b.w * .4, H * .013, H * .007); g.fillStyle = p.ink; g.fill(); }
    const y = -b.h / 2 + H * (kind === 'browser' ? .1 : .07);
    label(g, q.title || 'Your next idea', -b.w / 2 + H * .04, y, Math.min(H * .045, b.w * .095), ink, 'left', 650);
    if (q.subtitle) label(g, q.subtitle, -b.w / 2 + H * .04, y + H * .045, H * .022, dark ? p.line : p.muted, 'left');
    (q.items || ['Plan the work', 'Make something', 'Review the result']).forEach((item, i) => { const yy = y + H * .12 + i * H * .07; if (yy > b.h / 2 - H * .035) return; const a = ease((t - i * .15) / .5); g.save(); g.globalAlpha *= clamp(a); circle(g, -b.w / 2 + H * .045, yy, H * .008, color(q.color, p, i === 0 ? 'accent' : 'secondary')); label(g, item, -b.w / 2 + H * .067, yy, H * .025, ink, 'left'); line(g, [[-b.w / 2 + H * .04, yy + H * .033], [b.w / 2 - H * .04, yy + H * .033]], null, dark ? p.muted : p.line, 1); g.restore(); });
    if (q.value !== undefined) label(g, Math.round(q.value * clamp(s.reveal)).toLocaleString('en-US'), 0, b.h * .19, H * .08, color(q.color, p, 'accent'), 'center', 700);
    if (q.progress !== undefined) { rounded(g, -b.w * .4, b.h * .43, b.w * .8, H * .009, H * .004); g.fillStyle = p.line; g.fill(); rounded(g, -b.w * .4, b.h * .43, b.w * .8 * q.progress * clamp(s.reveal), H * .009, H * .004); g.fillStyle = color(q.color, p, 'accent'); g.fill(); }
    if (kind === 'dashboard') { const values = [0.45, .7, .54, .88, .75, .95]; for (let i = 0; i < values.length; i++) { const hh = b.h * .2 * values[i] * ease(t / 1.2); g.fillStyle = i === 5 ? p.secondary : p.accent; g.fillRect(-b.w * .38 + i * b.w * .125, b.h * .4 - hh, b.w * .07, hh); } }
  };
  draw.character = (g, b, p, s, t, layer) => {
    const q = layer.props, action = q.action || 'idle', time = t * (q.speed || 1), moving = ['walk', 'run'].includes(action), dance = action === 'dance', stride = moving ? Math.sin(time * (action === 'run' ? 11 : 7)) : dance ? Math.sin(time * 5) * .6 : 0;
    g.save(); if (q.facing === 'left') g.scale(-1, 1); const bh = Math.min(b.h, b.w * 2), headY = -bh * .31, hipY = bh * .13, shoulderY = -bh * .14, floor = bh * .48, limb = bh * .034, jacket = color(q.color, p, 'accent');
    const bob = moving ? -Math.abs(stride) * bh * .018 : dance ? Math.sin(time * 5) * bh * .018 : Math.sin(time * 1.6) * bh * .005;
    g.translate(dance ? Math.sin(time * 2.5) * bh * .02 : 0, bob);
    g.lineCap = 'round';
    for (const side of [-1, 1]) { const footX = side * bh * .075 + stride * side * bh * .09, kneeX = side * bh * .045 + stride * side * bh * .06, lift = moving ? Math.max(0, -stride * side) * bh * .07 : 0; line(g, [[side * bh * .055, hipY], [kneeX, hipY + bh * .16], [footX, floor - lift - bob]], null, p.ink, limb); line(g, [[footX - bh * .025, floor - lift - bob], [footX + bh * .055, floor - lift - bob]], null, p.ink, limb * 1.1); }
    line(g, [[-bh * .095, shoulderY], [bh * .095, shoulderY], [bh * .09, hipY], [-bh * .09, hipY]], jacket, p.ink, bh * .006, true);
    if (q.costume === 'suit') line(g, [[-bh * .035, shoulderY], [0, shoulderY + bh * .095], [bh * .035, shoulderY]], p.paper, null, 0, true);
    if (q.costume === 'astronaut') { circle(g, 0, headY, bh * .11, p.paper, p.muted, bh * .007); circle(g, bh * .012, headY, bh * .078, p.background); }
    else { circle(g, 0, headY, bh * .093, color(q.skin, p, 'paper'), p.ink, bh * .006); g.beginPath(); g.arc(0, headY - bh * .014, bh * .095, Math.PI * 1.05, TAU * .95); g.fillStyle = p.ink; g.fill(); if (q.costume === 'hoodie') { g.strokeStyle = jacket; g.lineWidth = bh * .04; g.stroke(); } circle(g, bh * .025, headY - bh * .005, bh * .007, p.ink); line(g, [[bh * .004, headY + bh * .03], [bh * .035, headY + bh * .034]], null, p.ink, bh * .005); }
    for (const side of [-1, 1]) { const wave = action === 'wave' && side === 1, elbow = [side * bh * .16, shoulderY + (wave ? -bh * .08 : bh * .09)], hand = [side * bh * (wave ? .21 : .17) + (moving ? -stride * side * bh * .065 : 0), shoulderY + (wave ? -bh * (.2 + Math.sin(time * 7) * .035) : dance ? bh * .02 + Math.sin(time * 5 + side) * bh * .09 : bh * .21)]; line(g, [[side * bh * .08, shoulderY], elbow, hand], null, jacket, limb * 1.1); circle(g, ...hand, bh * .023, color(q.skin, p, 'paper')); if (side === 1 && q.prop === 'lantern') { g.save(); g.shadowColor = p.glow; g.shadowBlur = bh * .15; rounded(g, hand[0] - bh * .035, hand[1] + bh * .035, bh * .07, bh * .085, bh * .012); g.fillStyle = p.glow; g.fill(); g.restore(); line(g, [[hand[0], hand[1]], [hand[0], hand[1] + bh * .035]], null, p.ink, bh * .006); } }
    if (q.prop === 'umbrella') { line(g, [[bh * .16, shoulderY + bh * .18], [bh * .16, headY - bh * .15]], null, p.ink, bh * .009); g.beginPath(); g.arc(bh * .16, headY - bh * .15, bh * .23, Math.PI, TAU); g.closePath(); g.fillStyle = p.secondary; g.fill(); }
    if (q.prop === 'flag') { line(g, [[bh * .17, shoulderY + bh * .21], [bh * .17, headY - bh * .21]], null, p.ink, bh * .009); line(g, [[bh * .17, headY - bh * .21], [bh * .42, headY - bh * .18], [bh * .39, headY - bh * .05], [bh * .17, headY - bh * .08]], p.secondary, p.ink, bh * .004, true); }
    g.restore();
  };
  draw.landscape = (g, b, p, s, t, layer) => {
    const q = layer.props, kind = q.kind || 'hills', seed = spec.seed + hash(layer.id), levels = q.layers || 4;
    if (kind === 'stage') { g.fillStyle = color(q.color, p, 'paper'); g.fillRect(-b.w / 2, b.h * .27, b.w, b.h * .23); for (const side of [-1, 1]) { line(g, [[side * b.w * .5, -b.h * .5], [side * b.w * .33, -b.h * .5], [side * b.w * .41, b.h * .29], [side * b.w * .5, b.h * .29]], p.accent, p.line, 1, true); } for (let i = 0; i < (q.detail || 6); i++) line(g, [[-b.w / 2, b.h * (.29 + i * .03)], [b.w / 2, b.h * (.29 + i * .03)]], null, p.line, 1); return; }
    if (q.sun) { g.save(); g.globalAlpha *= .9; circle(g, b.w * .28, -b.h * .28, b.h * .08, p.glow); g.restore(); }
    if (kind === 'city') {
      for (let depth = 0; depth < levels; depth++) { const count = 9 + depth * 3, bottom = b.h * (.1 + depth * .095); g.save(); g.globalAlpha *= .35 + depth / levels * .65; for (let i = 0; i < count; i++) { const width = b.w / count * .92, x = -b.w / 2 + i * b.w / count, height = b.h * (.12 + rand(i + depth * 300, seed) * .32); g.fillStyle = depth === levels - 1 ? p.ink : p.muted; g.fillRect(x, bottom - height, width, height); if (q.windows !== false) for (let row = 0; row < height / 18; row++) for (let col = 0; col < width / 15 - 1; col++) { if (rand(i * 600 + row * 10 + col, seed) > .58) { g.fillStyle = p.glow; g.fillRect(x + 7 + col * 15, bottom - height + 10 + row * 18, 5, 8); } } } g.restore(); }
      g.fillStyle = p.background; g.fillRect(-b.w / 2, b.h * .39, b.w, b.h * .11); for (let i = 0; i < 16; i++) { g.save(); g.globalAlpha *= .22; g.fillStyle = i % 2 ? p.secondary : p.glow; g.fillRect(-b.w / 2 + rand(i, seed) * b.w, b.h * .4, b.w * .045, b.h * .07); g.restore(); } return;
    }
    if (kind === 'island') { g.save(); g.scale(1, .42); circle(g, 0, b.h * .1, b.w * .38, p.secondary); circle(g, 0, -b.h * .04, b.w * .3, p.paper); g.restore(); for (let i = 0; i < 7; i++) { const x = (rand(i, seed) - .5) * b.w * .5, y = (rand(i + 12, seed) - .5) * b.h * .18; line(g, [[x, y], [x + b.w * .01, y - b.h * .2]], null, p.ink, H * .01); for (let j = 0; j < 5; j++) { const a = j / 5 * TAU + Math.sin(t) * .06; line(g, [[x + b.w * .01, y - b.h * .2], [x + Math.cos(a) * b.w * .07, y - b.h * .2 + Math.sin(a) * b.h * .06]], null, p.accent, H * .018); } } return; }
    for (let depth = 0; depth < levels; depth++) { const points = [[-b.w / 2, b.h / 2]], baseline = -b.h * .02 + depth * b.h * .12, amp = b.h * (.16 - depth * .014); for (let i = 0; i <= 100; i++) { const x = -b.w / 2 + i / 100 * b.w, nx = i / 100, shift = t * (q.speed ?? .015) * (depth + 1); let y = baseline - Math.sin(nx * 6 + depth * 1.3 + shift) * amp - Math.sin(nx * (7 + (q.detail || 6)) + depth) * amp * .4; if (kind === 'mountains') y -= Math.max(0, 1 - Math.abs(nx - .3 - depth * .12) * 8) * b.h * .27; points.push([x, y]); } points.push([b.w / 2, b.h / 2]); g.save(); g.globalAlpha *= (.22 + depth / levels * .58) * s.reveal; if (kind === 'mountains') { const gradient = g.createLinearGradient(0, -b.h / 2, 0, b.h / 2); gradient.addColorStop(0, p.ink); gradient.addColorStop(1, p.background); line(g, points, gradient, null, 0, true); } else line(g, points, color(q.color, p, depth % 2 ? 'secondary' : 'accent'), null, 0, true); g.restore(); }
    if (kind === 'mountains' && t > .8) { for (let i = 0; i < 3; i++) { const x = -b.w * .3 + i * b.w * .05, y = b.h * .26, height = b.h * (.11 + i * .016); line(g, [[x, y], [x - b.w * .004, y - height]], null, p.ink, H * .004); for (let j = 0; j < 5; j++) line(g, [[x, y - height * (.3 + j * .14)], [x + (j % 2 ? 1 : -1) * b.w * .035, y - height * (.45 + j * .13)]], null, p.ink, H * .009); } }
  };
  draw.orbit = (g, b, p, s, t, layer) => {
    const q = layer.props, n = q.count || 4, speed = q.speed ?? .7;
    if (q.kind === 'pendulum' || q.kind === 'cradle') { const count = q.kind === 'cradle' ? Math.max(3, n) : 1, length = b.h * .65, radius = b.h * .065, gap = radius * 2.12; line(g, [[-count * gap / 2 - radius, -b.h * .4], [count * gap / 2 + radius, -b.h * .4]], null, p.ink, H * .008); for (let i = 0; i < count; i++) { const phase = Math.sin(t * speed * 2.4), a = q.kind === 'pendulum' ? phase * .45 : i === 0 ? Math.min(0, phase) * .55 : i === count - 1 ? Math.max(0, phase) * .55 : 0, x = (i - (count - 1) / 2) * gap, end = [x + Math.sin(a) * length, -b.h * .4 + Math.cos(a) * length]; line(g, [[x, -b.h * .4], end], null, p.muted, H * .002); circle(g, ...end, radius, i === count - 1 ? p.accent : p.paper, p.ink, H * .003); } return; }
    g.save(); g.shadowColor = p.glow; g.shadowBlur = H * .035; circle(g, 0, 0, b.h * .09, p.glow); g.restore(); for (let i = 0; i < n; i++) { const rx = b.w * (.13 + i * .09), ry = b.h * (.1 + i * .075); g.beginPath(); g.ellipse(0, 0, rx, ry, -.3, 0, TAU); g.strokeStyle = p.line; g.lineWidth = 1; g.stroke(); const a = t * speed / (i + 1) + i * 2; const x = Math.cos(a) * rx, y = Math.sin(a) * ry; circle(g, x, y, b.h * (.022 + i * .004), i % 2 ? p.secondary : p.accent); if (q.labels?.[i]) label(g, q.labels[i], x, y + H * .035, H * .019, p.ink); }
  };
  function project(v, angleX, angleY) { const cy = Math.cos(angleY), sy = Math.sin(angleY), cx = Math.cos(angleX), sx = Math.sin(angleX), x = v[0] * cy + v[2] * sy, zz = -v[0] * sy + v[2] * cy, y = v[1] * cx - zz * sx, z = v[1] * sx + zz * cx, scale = 2.7 / (2.7 + z); return [x * scale, y * scale, z]; }
  draw.cube = (g, b, p, s, t, layer) => {
    const q = layer.props, n = q.count || 1, faces = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 4, 7, 3], [1, 5, 6, 2], [3, 2, 6, 7], [0, 1, 5, 4]];
    const verts = [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]].map(v => v.map(x => x * .38));
    const count = n ** 3, cubes = [];
    for (let z = 0; z < n; z++) for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) { const spread = 1 + (q.explode || 0) * 1.2 + (s.spread - 1), center = [x, y, z].map(v => (v - (n - 1) / 2) * .82 * spread), v = verts.map(v => project(v.map((a, j) => (a + center[j]) / n), -.38, t * (q.speed ?? .4) + .5)); for (let j = 0; j < faces.length; j++) { const face = faces[j].map(i => v[i]); cubes.push({ points: face.map(p => [p[0] * Math.min(b.w, b.h) / 2, p[1] * Math.min(b.w, b.h) / 2]), z: face.reduce((v, p) => v + p[2], 0) / 4, face: j }); } }
    cubes.sort((a, b) => b.z - a.z); for (const face of cubes) { g.save(); const base = color(q.color, p, 'accent'), brightness = [.65, .95, .75, .85, .55, 1][face.face], fill = '#' + [1, 3, 5].map(i => Math.round(parseInt(base.slice(i, i + 2), 16) * brightness).toString(16).padStart(2, '0')).join(''); line(g, face.points, q.wireframe ? null : fill, p.ink, Math.max(1, H * .002), true); g.restore(); }
  };
  draw.machine = (g, b, p, s, t, layer) => {
    const q = layer.props, stages = 7, explode = (q.explode || 0) + s.phase * .6;
    for (let j = stages - 1; j >= 0; j--) { const x = (j - 3) * b.w * (.092 + explode * .035), r = b.h * (j === 0 ? .32 : .19 - j * .011); g.save(); g.translate(x, 0); g.scale(.45, 1); circle(g, 0, 0, r, j % 2 ? p.paper : p.muted, p.ink, H * .005); const blades = j === 0 ? 18 : 12; for (let i = 0; i < blades; i++) { const a = i / blades * TAU + t * (q.speed ?? 2) * (j % 2 ? -1 : 1); line(g, [[Math.cos(a) * r * .25, Math.sin(a) * r * .25], [Math.cos(a + .15) * r * .93, Math.sin(a + .15) * r * .93]], null, color(q.color, p, j > 3 ? 'secondary' : 'accent'), H * .007); } circle(g, 0, 0, r * .15, p.ink); g.restore(); }
    for (let i = 0; i < 28; i++) { const x = (((t * .28 + i / 28) % 1) - .5) * b.w, y = (rand(i, spec.seed) - .5) * b.h * .26; g.save(); g.globalAlpha *= .55; line(g, [[x - b.w * .025, y], [x + b.w * .025, y]], null, x > 0 ? p.secondary : p.accent, H * .002); g.restore(); }
    if (q.labels) { for (const [i, text] of ['Intake', 'Compress', 'Burn', 'Exhaust'].entries()) { const x = (i - 1.5) * b.w * .22; line(g, [[x, -b.h * .25], [x, -b.h * .35]], null, p.muted, 1); label(g, text, x, -b.h * .4, H * .025, p.ink); } }
  };
  draw.weather = (g, b, p, s, t, layer) => {
    const q = layer.props, seed = spec.seed + hash(layer.id), kind = q.kind || 'stars', n = q.count ?? (['mist', 'smoke'].includes(kind) ? 20 : 100), speed = q.speed ?? 1;
    for (let i = 0; i < n; i++) { const rx = rand(i * 3, seed), ry = rand(i * 3 + 1, seed), r = rand(i * 3 + 2, seed); let x = (rx - .5) * b.w, y = (ry - .5) * b.h;
      g.save();
      if (kind === 'rain') { x = (((rx + t * speed * .09) % 1) - .5) * b.w; y = (((ry + t * speed * (.3 + r * .3)) % 1) - .5) * b.h; g.globalAlpha *= .2 + r * .4; line(g, [[x, y], [x + H * .01, y + H * .04]], null, color(q.color, p, 'secondary'), Math.max(1, H * .001)); }
      else if (kind === 'mist' || kind === 'smoke') { x += Math.sin(t * speed * .2 + i) * b.w * .13; y -= (((t * speed * .05 + r) % 1) - .5) * b.h * .2; g.globalAlpha *= kind === 'mist' ? .035 : .05; g.filter = `blur(${H * .025}px)`; circle(g, x, y, H * (.025 + r * .055), color(q.color, p, 'paper')); }
      else { const pulse = .35 + .65 * (.5 + .5 * Math.sin(t * speed * 1.5 + i)); g.globalAlpha *= pulse; if (kind === 'fireflies') { x += Math.sin(t * speed + i * 2) * b.w * .03; y += Math.cos(t * speed * .7 + i) * b.h * .04; g.shadowColor = p.glow; g.shadowBlur = H * .018; } circle(g, x, y, H * (q.size || .002) * (.6 + r), color(q.color, p, kind === 'fireflies' ? 'glow' : 'ink')); }
      g.restore();
    }
  };
  draw.image = (g, b, p, s, t, layer) => {
    const q=layer.props,image=assets[layer.id+':'+q.source];if(!image)return;
    const frames=q.frames??1,columns=q.columns??1,rows=Math.ceil(frames/columns),width=image.width/columns,height=image.height/rows,index=q.loop===false?Math.min(frames-1,Math.floor(t*(q.frame_rate??12))):Math.floor(t*(q.frame_rate??12))%frames;
    const ratio=q.fit==='cover'?Math.max(b.w/width,b.h/height):Math.min(b.w/width,b.h/height);
    rounded(g,-b.w/2,-b.h/2,b.w,b.h,(q.radius??0)*H);g.clip();g.imageSmoothingEnabled=!q.pixelated;
    g.drawImage(image,(index%columns)*width,Math.floor(index/columns)*height,width,height,-width*ratio/2,-height*ratio/2,width*ratio,height*ratio);
  };
  Object.assign(draw, window.AnimationAdvanced({ color, clamp, lerp, stage: () => ({ W, H, spec, surfaceRenderer: value => { surfaceRenderer = value; }, warning: (layer, warning) => reports.push({layer,warning}) }) }));
  const plainVector=draw.vector;draw.vector=(g,b,p,s,t,layer)=>layer.props.texture==='mosaic'?materials.mosaic(g,b,p,s,t,layer):plainVector(g,b,p,s,t,layer);
  function layerState(layer, t, scene) {
    const duration = layer.duration ?? scene.duration - layer.start, local = t - layer.start;
    if (local < 0 || local > duration) return null;
    const s = { x: layer.x, y: layer.y, scale: layer.scale, scale_x: layer.scale_x ?? 1, scale_y: layer.scale_y ?? 1, skew_x: layer.skew_x ?? 0, skew_y: layer.skew_y ?? 0, blur: layer.blur ?? 0, rotation: layer.rotation, opacity: layer.opacity, reveal: 1, phase: 0, spread: 1, amount: 1, local, duration };
    for (const [key, frames] of Object.entries(layer.tracks)) s[key] = track(frames, local, s[key]);
    const entry = clamp(local / layer.enter_duration), leaving = clamp((duration - local) / layer.exit_duration);
    if (layer.enter === 'fade' || layer.enter === 'slide_up' || layer.enter === 'pop') s.opacity *= ease(entry, 'cubic_out');
    if (layer.enter === 'slide_up') s.y += (1 - ease(entry, 'cubic_out')) * .055;
    if (layer.enter === 'pop') s.scale *= ease(entry, 'back_out');
    if (layer.enter === 'draw' || layer.enter === 'type') s.reveal *= ease(entry, 'cubic_in_out');
    if (layer.exit === 'fade') s.opacity *= ease(leaving);
    if (layer.exit === 'shrink') { s.opacity *= ease(leaving); s.scale *= ease(leaving, 'cubic_in'); }
    const motion = layer.motion, angle = local * motion.speed * TAU + motion.phase;
    if (motion.type === 'float') { s.x += Math.sin(angle * .41) * motion.amount * .25; s.y += Math.sin(angle) * motion.amount; }
    if (motion.type === 'spin') s.rotation += local * motion.speed * 360;
    if (motion.type === 'bounce') s.y -= Math.abs(Math.sin(angle)) * motion.amount;
    if (motion.type === 'wiggle') s.rotation += Math.sin(angle) * motion.amount * 30;
    return s;
  }
  function transformLayer(g, layer, s, parentBox, p) {
    const b = { w: layer.width * parentBox.w, h: layer.height * parentBox.h };
    g.globalAlpha *= clamp(s.opacity); g.translate((s.x - (layer.parent ? .5 : 0)) * parentBox.w, (s.y - (layer.parent ? .5 : 0)) * parentBox.h); g.rotate(s.rotation * Math.PI / 180); g.transform(1, Math.tan(s.skew_y * Math.PI / 180), Math.tan(s.skew_x * Math.PI / 180), 1, 0, 0); g.scale(s.scale * s.scale_x, s.scale * s.scale_y);
    g.translate((.5 - (layer.anchor_x ?? .5)) * b.w, (.5 - (layer.anchor_y ?? .5)) * b.h);
    if (s.blur) g.filter = `blur(${s.blur * H}px)`;
    if (layer.blend && layer.blend !== 'source-over') g.globalCompositeOperation = layer.blend;
    if (layer.shadow) { g.shadowColor = color(layer.shadow.color, p); g.shadowBlur = layer.shadow.blur * H; g.shadowOffsetX = layer.shadow.x * H; g.shadowOffsetY = layer.shadow.y * H; }
    if (layer.mask) {
      const m = layer.mask, reveal = s.mask_reveal ?? m.reveal; g.beginPath();
      if (m.kind === 'ellipse') g.ellipse(0, 0, b.w / 2 * Math.sqrt(reveal), b.h / 2 * Math.sqrt(reveal), 0, 0, TAU);
      else { const horizontal = ['left', 'right'].includes(m.direction), width = b.w * (horizontal ? reveal : 1), height = b.h * (horizontal ? 1 : reveal), x = m.direction === 'right' ? b.w / 2 - width : -b.w / 2, y = m.direction === 'up' ? b.h / 2 - height : -b.h / 2; rounded(g, x, y, width, height, m.radius * H); }
      g.clip();
    }
    if (layer.paint) { const q = layer.paint, angle = q.angle * Math.PI / 180, r = Math.hypot(b.w, b.h) / 2, gradient = q.kind === 'radial' ? g.createRadialGradient(q.x * b.w, q.y * b.h, 0, 0, 0, r) : g.createLinearGradient(-Math.cos(angle) * b.w / 2, -Math.sin(angle) * b.h / 2, Math.cos(angle) * b.w / 2, Math.sin(angle) * b.h / 2); q.colors.forEach((c, i) => gradient.addColorStop(i / (q.colors.length - 1), color(c, p))); s.paint = gradient; }
    return b;
  }
  function renderLayer(g, layer, t, scene, p) {
    if (layer.component === 'group') return;
    const s = layerState(layer, t, scene); if (!s) return;
    const props = { ...layer.props };
    for (const [key, frames] of Object.entries(layer.props_tracks || {})) { const bounds = window.AnimationPropertyLimits[layer.component][key]; props[key] = clamp(track(frames,s.local,props[key]),bounds.minimum ?? -10000,bounds.maximum ?? 10000); }
    for (const [key, frames] of Object.entries(layer.color_tracks || {})) {
      let a = frames[0], b = frames[0]; for (let i=1;i<frames.length;i++) { a=frames[i-1];b=frames[i];if(s.local<=b.time)break; } const f = a===b ? 0 : ease((s.local-a.time)/(b.time-a.time),b.ease), first=color(a.value,p), last=color(b.value,p); props[key]='#'+[1,3,5].map(i=>Math.round(lerp(parseInt(first.slice(i,i+2),16),parseInt(last.slice(i,i+2),16),clamp(f))).toString(16).padStart(2,'0')).join('');
    }
    g.save(); let b = { w: W, h: H }, chain = [], parent = layer.parent;
    while (parent) { const ancestor = scene.layers.find(item => item.id === parent); chain.unshift(ancestor); parent = ancestor.parent; }
    for (const ancestor of chain) { const state = layerState(ancestor, t, scene); if (!state) { g.restore(); return; } b = transformLayer(g, ancestor, state, b, p); }
    b = transformLayer(g, layer, s, b, p); s.alpha = g.globalAlpha;
    if (['paper', 'punk', 'ink'].includes(scene.style || spec.style)) { const n = Math.floor(t * 8), jitter = rand(n, hash(layer.id) + spec.seed) - .5; g.rotate(jitter * .005); }
    draw[layer.component](g, b, p, s, s.local, { ...layer, props }); g.restore();
  }
  function texture(g, style, p) {
    if (!['paper', 'ink', 'punk', 'mosaic', 'blueprint'].includes(style)) return;
    const key = `${style}:${p.ink}`;
    if (!grainCache[key]) { const c = document.createElement('canvas'); c.width = W; c.height = H; const cg = c.getContext('2d'); cg.fillStyle = p.ink; for (let i = 0; i < (style === 'punk' ? 2700 : 1400); i++) { const x = rand(i * 2, spec.seed) * W, y = rand(i * 2 + 1, spec.seed) * H; cg.globalAlpha = .02 + rand(i + 3, spec.seed) * (style === 'punk' ? .14 : .045); cg.fillRect(x, y, style === 'punk' ? 1 + rand(i, 7) * 4 : 1, 1 + rand(i, 9) * 3); } grainCache[key] = c; }
    g.drawImage(grainCache[key], 0, 0);
  }
  let painterly, painterlyCanvas;
  function renderScene(scene, t, target) {
    const p = { ...palettes[scene.style || spec.style], ...spec.palette }, style = scene.style || spec.style;
    if(scene.painterly) {
      const opts=scene.painterly;
      for(const [pass,g] of [['base',painterly.sctx],['light',painterly.fctx]]) {
        g.setTransform(1,0,0,1,0,0);g.globalAlpha=1;g.globalCompositeOperation='source-over';g.filter='none';g.fillStyle=pass==='base'?color(scene.background,p,'background'):'#000000';g.fillRect(0,0,g.canvas.width,g.canvas.height);
        g.save();g.scale(g.canvas.width/W,g.canvas.height/H);
        const camera={...scene.camera};for(const [name,frames] of Object.entries(camera.tracks))camera[name]=track(frames,t,camera[name]);
        g.translate(W/2,H/2);g.rotate(camera.rotation*Math.PI/180);g.scale(clamp(camera.zoom,.01,8),clamp(camera.zoom,.01,8));g.translate(-camera.x*W,-camera.y*H);
        for(const layer of scene.layers)if((layer.paint_pass||'base')===pass)renderLayer(g,layer,t,scene,p);
        g.restore();
      }
      painterly.present(t,{boil:opts.boil,strokeK:opts.stroke_scale,flowK:opts.flow,smear:opts.smear,grain:opts.grain,vig:opts.vignette,bloom:opts.bloom});
      target.setTransform(1,0,0,1,0,0);target.globalAlpha=1;target.globalCompositeOperation='source-over';target.filter='none';target.drawImage(painterlyCanvas,0,0);
      return;
    }
    target.setTransform(1, 0, 0, 1, 0, 0); target.globalAlpha = 1; target.filter = 'none'; target.fillStyle = color(scene.background, p, 'background'); target.fillRect(0, 0, W, H);
    target.save(); const camera = { ...scene.camera }; for (const [name, frames] of Object.entries(camera.tracks)) camera[name] = track(frames, t, camera[name]);
    target.translate(W / 2, H / 2); target.rotate(camera.rotation * Math.PI / 180); target.scale(clamp(camera.zoom,.01,8), clamp(camera.zoom,.01,8)); target.translate(-camera.x * W, -camera.y * H);
    for (const layer of scene.layers) renderLayer(target, layer, t, scene, p);
    target.restore();
    if (style === 'mosaic' && !scene.layers.some(layer=>layer.component==='tiles'||layer.props.texture==='mosaic')) { const data = target.getImageData(0, 0, W, H), tile = Math.max(5, Math.round(H / 65)); target.fillStyle = p.line; target.fillRect(0, 0, W, H); for (let y = 0; y < H; y += tile) for (let x = 0; x < W; x += tile) { const index = (Math.min(H - 1, y + tile / 2 | 0) * W + Math.min(W - 1, x + tile / 2 | 0)) * 4; target.fillStyle = `rgb(${data.data[index]},${data.data[index + 1]},${data.data[index + 2]})`; target.fillRect(x + 1, y + 1, tile - 1, tile - 1); } }
    texture(target, style, p);
    if(scene.pixel_size||style==='pixel'){
      const size=scene.pixel_size||Math.max(2,Math.round(H/180));pixelCanvas.width=Math.max(1,Math.ceil(W/size));pixelCanvas.height=Math.max(1,Math.ceil(H/size));
      const pg=pixelCanvas.getContext('2d');pg.imageSmoothingEnabled=true;pg.drawImage(target.canvas,0,0,pixelCanvas.width,pixelCanvas.height);
      target.save();target.setTransform(1,0,0,1,0,0);target.globalAlpha=1;target.imageSmoothingEnabled=false;target.drawImage(pixelCanvas,0,0,W,H);target.restore();
    }
  }
  let previousCanvas, currentCanvas, blurCanvas, pixelCanvas;
  function seekFrame(time) {
    reports = []; const t = clamp(Number(time), 0, Math.max(0, spec.scenes.reduce((a, s) => a + s.duration, 0) - 1e-7));
    let index = spec.scenes.length - 1; for (let i = 0; i < sceneStarts.length; i++) if (t < sceneStarts[i] + spec.scenes[i].duration) { index = i; break; }
    const scene = spec.scenes[index], local = t - sceneStarts[index], transition = scene.transition, amount = ease(local / Math.min(transition.duration, scene.duration));
    renderScene(scene, local, currentCanvas.getContext('2d'));
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.filter = 'none';
    if (index > 0 && local < transition.duration && transition.type !== 'cut') {
      renderScene(spec.scenes[index - 1], spec.scenes[index - 1].duration - 1e-6, previousCanvas.getContext('2d'));
      ctx.drawImage(previousCanvas, 0, 0); ctx.save();
      if (transition.type === 'crossfade') ctx.globalAlpha = amount;
      else if (transition.type === 'wipe') { ctx.beginPath(); ctx.rect(0, 0, W * amount, H); ctx.clip(); }
      else if (transition.type === 'iris') { ctx.beginPath(); ctx.arc(W / 2, H / 2, Math.hypot(W, H) * amount / 2, 0, TAU); ctx.clip(); }
      else if (transition.type === 'slide') ctx.translate(W * (1 - amount), 0);
      else if (transition.type === 'glitch') { ctx.globalAlpha = amount; ctx.translate(Math.sin(local * 90) * W * .04 * (1 - amount), 0); }
      ctx.drawImage(currentCanvas, 0, 0); ctx.restore();
    } else ctx.drawImage(currentCanvas, 0, 0);
    const caption = spec.captions.find(c => t >= c.start && t < c.end);
    if (caption) {
      ctx.save(); let size = H * .033, lines;
      do { ctx.font = font('body', size, 600); lines = []; let line = ''; for (const word of caption.text.split(/\s+/)) { const next = line ? line + ' ' + word : word; if (line && ctx.measureText(next).width > W * .84) { lines.push(line); line = word; } else line = next; } if (line) lines.push(line); if (lines.length <= 3 && lines.every(line => ctx.measureText(line).width <= W * .84)) break; size *= .9; } while (size > H * .012);
      const height = lines.length * size * 1.35 + H * .035, top = H * .96 - height;
      rounded(ctx, W * .05, top, W * .9, height, H * .014); ctx.fillStyle = '#10131ddd'; ctx.fill(); lines.forEach((line, i) => label(ctx, line, W / 2, top + H * .018 + size * (.7 + i * 1.35), size, '#ffffff', 'center', 600)); ctx.restore();
    }
    const finish = spec.finishing || {};
    if (finish.vignette) { ctx.save(); const gradient = ctx.createRadialGradient(W / 2, H * .46, H * .22, W / 2, H / 2, Math.hypot(W, H) * .6); gradient.addColorStop(0, '#00000000'); gradient.addColorStop(1, `rgba(0,0,0,${finish.vignette})`); ctx.fillStyle = gradient; ctx.fillRect(0, 0, W, H); ctx.restore(); }
    if (finish.grain) { const key = 'finish-grain:' + Math.floor(t * 12) % 8; if (!grainCache[key]) { const noise = document.createElement('canvas'); noise.width = noise.height = 128; const ng = noise.getContext('2d'), data = ng.createImageData(128, 128); for (let i = 0; i < 128 * 128; i++) { const value = Math.floor(rand(i, spec.seed + Math.floor(t * 12) % 8) * 255); data.data.set([value, value, value, 255], i * 4); } ng.putImageData(data, 0, 0); grainCache[key] = noise; } ctx.save(); ctx.globalCompositeOperation = 'overlay'; ctx.globalAlpha = finish.grain; ctx.fillStyle = ctx.createPattern(grainCache[key], 'repeat'); ctx.fillRect(0, 0, W, H); ctx.restore(); }
    window.AnimationReport = { time: t, scene: scene.id, warnings: reports, surface_renderer: surfaceRenderer };
    return window.AnimationReport;
  }
  function seek(time) {
    const finish = spec.finishing || {}, count = finish.motion_blur ? finish.samples || 3 : 1;
    if (count === 1) return seekFrame(time);
    const accum = blurCanvas.getContext('2d'); accum.setTransform(1, 0, 0, 1, 0, 0); accum.globalAlpha = 1; accum.clearRect(0, 0, W, H);
    for (let i = 0; i < count; i++) { seekFrame(Math.max(0, Number(time) - finish.motion_blur / spec.fps * (1 - i / (count - 1)))); accum.globalAlpha = 1 / (i + 1); accum.drawImage(canvas, 0, 0); }
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.drawImage(blurCanvas, 0, 0); return window.AnimationReport;
  }
  let scene3d;
  let mosaicScenes = new Map();
  draw.mosaic_scene = (g,b,p,s,t,layer) => {
    let entry=mosaicScenes.get(layer.id);
    if(!entry) {
      const options={...layer.props};
      entry={options,renderer:window.createMosaicScene(options)};
      mosaicScenes.set(layer.id,entry);
    }
    Object.assign(entry.options,layer.props);
    entry.renderer.render(layer.props.playhead ?? Math.max(0,Math.min(15,t/s.duration*15)));
    g.drawImage(entry.renderer.surface,-b.w/2,-b.h/2,b.w,b.h);
  };
  async function initialize(composition, element, theme) {
    fluidRenderer.reset();materials.reset();
    for(const entry of mosaicScenes.values())entry.renderer.dispose();
    mosaicScenes.clear();
    painterly?.dispose();painterly=null;painterlyCanvas=null;
    scene3d?.dispose(); scene3d = null;
    spec = composition; canvas = element; W = spec.width; H = spec.height; canvas.width = W; canvas.height = H; ctx = canvas.getContext('2d', { willReadFrequently: false }); palettes = theme;
    previousCanvas = document.createElement('canvas'); currentCanvas = document.createElement('canvas'); previousCanvas.width = currentCanvas.width = W; previousCanvas.height = currentCanvas.height = H;
    blurCanvas = document.createElement('canvas'); blurCanvas.width = W; blurCanvas.height = H;
    pixelCanvas = document.createElement('canvas');
    let start = 0; sceneStarts = spec.scenes.map(scene => { const value = start; start += scene.duration; return value; });
    assets = {}; grainCache = {}; surfaceRenderer = null;
    if(spec.scenes.some(scene=>scene.painterly)) {
      painterlyCanvas=document.createElement('canvas');painterly=window.AnimationPainterly(W,H);painterly.init(painterlyCanvas);
    }
    if (spec.scenes.some(scene => scene.layers.some(layer => layer.component === 'scene3d'))) {
      const module = await window.Animation3DReady;
      scene3d = module.createSceneRenderer({ color, track, ease, report: value => { surfaceRenderer = value; } });
      await scene3d.prepare(spec);
      draw.scene3d = scene3d.draw;
    }
    await Promise.allSettled([document.fonts.load('700 48px StageSans'),document.fonts.load('500 24px StageMono')]);
    await document.fonts.load('700 48px StageCondensed');
    await document.fonts.ready;
    await Promise.all((spec.fonts || []).map(face => document.fonts.load(`500 48px StageFont_${face.id}`)));
    await Promise.all(spec.scenes.flatMap(scene => scene.layers.filter(layer => ['image','tiles'].includes(layer.component)&&layer.props.source).map(layer => new Promise((resolve, reject) => { const image = new Image(); image.onload = () => { assets[layer.id + ':' + layer.props.source] = image; resolve(); }; image.onerror = () => reject(Error('Image asset could not be decoded')); image.src = layer.props.source; }))));
    seek(0); return { duration: start };
  }
  window.AnimationRenderer = { initialize, seek, ease, track };
})();

