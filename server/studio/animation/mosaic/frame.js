// main.js — assembles a frame from time alone, and drives the player.
// seek(t) renders any frame directly, in any order.
'use strict';

const Short = (() => {
  const B = CONFIG.scene.bowl, TM = CONFIG.timing;
  let fishTiles = null, ready = false;
  const fishTilt = [];
  const GROUT = U.mixc(U.hex(CONFIG.palette.grout), U.hex(CONFIG.palette.groutDeep), 0.5);

  function init(canvas) {
    const scene = Scene.build(CONFIG.seed);
    fishTiles = Fish.build(CONFIG.seed + 99);
    fishTiles.forEach((t, k) => fishTilt.push([(U.hash1(k * 71 + 5) - 0.5) * 0.4, (U.hash1(k * 29 + 9) - 0.5) * 0.4]));
    Renderer.init(canvas, scene.tiles, scene.overlayStart);
    ready = true;
    return { bgTiles: scene.tiles.length, fishTiles: fishTiles.length };
  }

  function lightDay(t) {
    const a = -0.82 + 0.045 * Math.min(t, 9);
    return [Math.cos(a) * 0.78, Math.sin(a) * 0.78, 0.6];
  }

  function frame(t) {
    t = Math.max(0, Math.min(CONFIG.duration, t));
    const cam = Choreo.camera(t);
    Renderer.beginDynamic();

    // ---- fish ----
    const ps = Choreo.fishPose(t);
    ps.amp *= OPTIONS.wave_strength ?? 1;
    ps.spread *= OPTIONS.tail_spread ?? 1;
    ps.pect *= OPTIONS.fin_activity ?? 1;
    ps.curl += OPTIONS.curl_bias ?? 0;
    let k = 0;
    const lens = 1.035;
    Fish.pose(fishTiles, ps, (tile, poly, cx, cy) => {
      const tl = fishTilt[k++];
      const depth = Scene.waterDepthAt(cx, cy);
      const sub = depth < -50 ? 0 : U.smoothstep(-2, 5, depth);
      if (sub > 0) {
        const dx = (cx - B.cx) * (lens - 1) * sub;
        for (let i = 0; i < poly.length; i += 2) poly[i] += dx;
        cx += dx;
      }
      // cobalt grout bed beneath each tessera so gaps read as grout, not water
      const bed = [];
      for (let i = 0; i < poly.length; i += 2) {
        const ex = poly[i] - cx, ey = poly[i + 1] - cy, el = Math.hypot(ex, ey) + 1e-6;
        bed.push(poly[i] + ex / el * 1.25, poly[i + 1] + ey / el * 1.25);
      }
      Renderer.addDynamic('bed', bed, cx, cy, {
        day: GROUT, night: GROUT, md: 6, mn: 6, rnd: 0, tx: 0, ty: 0,
        flags: Scene.F.dynamic, alpha: tile.alpha < 1 ? 0.55 : 1, extra: sub,
      });
      Renderer.addDynamic('fish', poly, cx, cy, {
        day: tile.col, night: tile.col, md: tile.mat, mn: tile.mat, rnd: tile.rnd,
        tx: tl[0], ty: tl[1], flags: Scene.F.dynamic | Scene.F.fish, alpha: tile.alpha, extra: sub,
      });
    });

    // ---- water ribbon & splash: shimmering glass droplets ----
    const P = Scene.P;
    Choreo.particles(t, (x, y, vx, vy, size, life, seed) => {
      const r = U.hash1(seed * 13 + 1), r2 = U.hash1(seed * 7 + 3);
      const sp = Math.hypot(vx, vy);
      const ang = Math.atan2(vy, vx) + (r - 0.5) * 0.5 + Math.sin(t * 3 + seed) * 0.2;
      const rx = size * (1 + Math.min(0.9, sp / 700)) * life, ry = size * 0.72 * life;
      const n = 5 + (seed % 2);
      const poly = [];
      const ca = Math.cos(ang), sa = Math.sin(ang);
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + (U.hash1(seed * 31 + i) - 0.5) * 0.7;
        const rr = 0.82 + 0.3 * U.hash1(seed * 17 + i * 5);
        const lx = Math.cos(a) * rx * rr, ly = Math.sin(a) * ry * rr;
        poly.push(x + lx * ca - ly * sa, y + lx * sa + ly * ca);
      }
      const night = Choreo.nightAt(x, y, t);
      const day = r > 0.85 ? [0.96, 1, 0.97] : U.mixc(P.water, P.waterLight, 0.2 + 0.6 * r);
      const nc = U.mixc(P.waterSurfaceNight, P.moonLit, 0.25 + 0.4 * r);
      const col = U.mixc(day, nc, night);
      Renderer.addDynamic(seed % 2 ? 'over' : 'under', poly, x, y, {
        day: col, night: col, md: Scene.MAT.glass, mn: Scene.MAT.glass, rnd: r2,
        tx: Math.sin(t * 7 + seed) * 0.5, ty: Math.cos(t * 6 + seed * 2) * 0.5,
        flags: Scene.F.dynamic, alpha: 0.9 * life,
      });
    });

    const rip = [];
    for (let i = 0; i < 6; i++) { const r = Choreo.ripples[i]; rip.push(r[0], r[1], r[2], r[3]); }
    Renderer.render({
      t, cam, ripples: new Float32Array(rip), glint: Choreo.glint(t), sunBand: Choreo.sunBand(t),
      lightDay: lightDay(t), lightNight: [0.5, -0.62, 0.62],
    });
  }

  return { init, frame, isReady: () => ready };
})();

