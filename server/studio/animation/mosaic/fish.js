// fish.js — the goldfish: shape, tessellation, colouring and the rig that
// bends it every frame.
//
// Local fish space: fx runs forward (nose at 0, tail toward negative), fy is
// dorsal-up. Tiles are cut once in this space by the same contour tiler as
// the set, then every vertex is carried through a bending spine:
//   spine angle θ(l) = curl + travelling wave + heading lag (follow-through)
// so the head leads and the wave flows into the tail.
'use strict';

const Fish = (() => {
  const FC = CONFIG.fish, P = Scene.P;
  const Lb = FC.bodyLen, Lt = FC.tailLen, Ltot = Lb + Lt;

  // ---------- body profile ----------
  const prof = FC.profile;
  function profAt(u, col) {
    if (u <= 0) return 0;
    if (u >= 1) return prof[prof.length - 1][col];
    let i = 1; while (u > prof[i][0]) i++;
    const a = prof[i - 1], b = prof[i];
    const pa = prof[Math.max(0, i - 2)], pb = prof[Math.min(prof.length - 1, i + 1)];
    const h = b[0] - a[0], s = (u - a[0]) / h;
    const ma = (b[col] - pa[col]) / (b[0] - pa[0]) * h, mb = (pb[col] - a[col]) / (pb[0] - a[0]) * h;
    const s2 = s * s, s3 = s2 * s;
    return (2 * s3 - 3 * s2 + 1) * a[col] + (s3 - 2 * s2 + s) * ma + (-2 * s3 + 3 * s2) * b[col] + (s3 - s2) * mb;
  }
  const top = (u) => profAt(u, 1), bot = (u) => profAt(u, 2);

  // ---------- fin outlines (closed Catmull–Rom through control points) ----------
  function closedSpline(pts, sub = 8) {
    const n = pts.length, out = [];
    for (let i = 0; i < n; i++) {
      const p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
      for (let k = 0; k < sub; k++) {
        const t = k / sub, t2 = t * t, t3 = t2 * t;
        out.push([
          0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
          0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
        ]);
      }
    }
    return out;
  }
  function inPoly(poly, x, y) {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const a = poly[i], b = poly[j];
      if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) c = !c;
    }
    return c;
  }

  const FINS = {
    dorsal: closedSpline([[-26, 22], [-29, 36], [-35, 49], [-45, 53], [-57, 48], [-69, 38], [-81, 28], [-77, 18], [-62, 15], [-44, 19]]),
    tail: closedSpline([[-86, 5], [-100, 12], [-116, 21], [-133, 29], [-150, 35], [-165, 37], [-171, 31], [-163, 22], [-151, 13],
      [-140, 5], [-136, -1], [-141, -8], [-152, -16], [-164, -24], [-168, -33], [-157, -36], [-141, -31], [-124, -24],
      [-108, -16], [-96, -10], [-86, -5]]),
    pelvic: closedSpline([[-35, -22], [-40, -30], [-47, -37], [-54, -40], [-55, -35], [-50, -28], [-45, -22]]),
    anal: closedSpline([[-64, -12], [-69, -20], [-76, -26], [-83, -28], [-82, -22], [-78, -15], [-73, -10]]),
    pectoral: closedSpline([[-20, -8], [-25, -13], [-31, -19], [-39, -24], [-45, -25], [-42, -19], [-35, -12], [-27, -6]]),
  };
  const ATTACH = { pectoral: [-21, -9], pelvic: [-40, -23], anal: [-69, -13], dorsal: [-50, 20], tail: [-90, 0] };
  const EYE = { x: -0.112 * Lb, y: 5.2, r: 6.9, pr: 4.3 };

  const FR = { body: 1, head: 2, belly: 3, gill: 4, iris: 5, pupil: 6, eyeHi: 7, mouth: 8,
    dorsal: 9, tail: 10, pelvic: 11, anal: 12, pectoral: 13 };

  function gillU(fy) { return 0.215 + 0.045 * (fy / 26) * (fy / 26); }

  function regionMain(fx, fy) {
    const u = -fx / Lb;
    if (u >= -0.01 && u <= 1.0) {
      const t = top(u), b = bot(u);
      if (fy < t && fy > b) {
        const ex = fx - EYE.x, ey = fy - EYE.y, er = Math.hypot(ex, ey);
        if (er < EYE.r) {
          if (Math.hypot(ex - 1.7, ey - 1.8) < 1.55) return FR.eyeHi;
          return er < EYE.pr ? FR.pupil : FR.iris;
        }
        if (fx > -4.2 && Math.abs(fy + 1.2) < 1.6) return FR.mouth;
        const gu = gillU(fy);
        if (u < gu) return FR.head;
        if (u < gu + 0.035 && fy < t * 0.86 && fy > b * 0.86) return FR.gill;
        if (fy < b * 0.42 + 2 * Math.sin(u * 6) && u > 0.14 && u < 0.86) return FR.belly;
        return FR.body;
      }
    }
    if (inPoly(FINS.dorsal, fx, fy)) return FR.dorsal;
    if (inPoly(FINS.tail, fx, fy)) return FR.tail;
    if (inPoly(FINS.pelvic, fx, fy)) return FR.pelvic;
    if (inPoly(FINS.anal, fx, fy)) return FR.anal;
    return 0;
  }
  function regionPect(fx, fy) { return inPoly(FINS.pectoral, fx, fy) ? FR.pectoral : 0; }

  const LAYER = { [FR.tail]: 0, [FR.dorsal]: 1, [FR.anal]: 2, [FR.pelvic]: 2, [FR.body]: 4, [FR.head]: 4, [FR.belly]: 4,
    [FR.gill]: 4, [FR.mouth]: 4, [FR.iris]: 5, [FR.pupil]: 6, [FR.eyeHi]: 7, [FR.pectoral]: 8 };
  const PART = { [FR.tail]: 'tail', [FR.dorsal]: 'dorsal', [FR.anal]: 'anal', [FR.pelvic]: 'pelvic', [FR.pectoral]: 'pectoral' };

  // ---------- colour ----------
  function styleTile(t, rng) {
    const r = t.region, x = t.cx, y = t.cy;
    const u = U.clamp(-x / Lb);
    const r1 = rng(), r2 = rng(), r3 = rng();
    let col, mat = Scene.MAT.ceramic, alpha = 1, amt = 0.55;
    const v = U.clamp((y - bot(u)) / Math.max(1, top(u) - bot(u)));
    const scaleShade = () => {
      // overlapping-scale rhythm: darker toward each scale's trailing edge
      const row = Math.floor((y + 40) / 6.2);
      const f = ((-x) / 7.2 + (row & 1) * 0.5) % 1;
      return 1 - 0.13 * U.smoothstep(0.45, 1, f) + 0.05 * U.smoothstep(0.3, 0, f);
    };
    switch (r) {
      case FR.body: {
        col = U.mixc(P.fishBelly, P.fishBody, U.smoothstep(0.08, 0.5, v));
        col = U.mixc(col, P.fishBack, U.smoothstep(0.62, 1, v) * 0.75);
        col = U.mixc(col, P.fishBack, U.smoothstep(0.7, 1, u) * 0.25);
        col = U.mulc(col, scaleShade());
        mat = r1 < 0.35 ? Scene.MAT.glass : Scene.MAT.ceramic;
        if (r2 < 0.06 && v > 0.35) { col = U.mixc(P.gold, P.goldPale, r3); mat = Scene.MAT.gold; }
        break;
      }
      case FR.head:
        col = U.mixc(P.fishHead, P.fishBack, U.smoothstep(0.55, 1, v) * 0.55);
        col = U.mixc(col, P.fishBelly, U.smoothstep(0.45, 0.05, v) * 0.6);
        col = U.mixc(col, P.goldPale, Math.exp(-((x + 12) ** 2 + (y + 5) ** 2) / 40) * 0.35);
        mat = r1 < 0.3 ? Scene.MAT.glass : Scene.MAT.ceramic; break;
      case FR.belly:
        col = U.mixc(P.fishCream, P.fishBelly, U.smoothstep(0, 0.35, v) * 0.8);
        col = U.mulc(col, 0.5 + 0.5 * scaleShade()); break;
      case FR.gill: col = P.fishGill; break;
      case FR.mouth: col = U.mulc(P.fishGill, 0.7); break;
      case FR.iris: col = U.mixc(P.fishIris, P.goldPale, r1 * 0.5); mat = Scene.MAT.gold; amt = 0.3; break;
      case FR.pupil: col = P.fishEye; mat = Scene.MAT.glass; amt = 0.1; break;
      case FR.eyeHi: col = [1, 1, 0.97]; mat = Scene.MAT.glass; amt = 0; break;
      default: {
        // fins & tail: translucent glass, lighter toward the tips, ray stripes
        const a = ATTACH[PART[r]];
        const d = Math.hypot(x - a[0], y - a[1]);
        const maxD = r === FR.tail ? 80 : r === FR.dorsal ? 34 : 22;
        const tip = U.smoothstep(0.35, 1.05, d / maxD);
        col = U.mixc(P.fishFin, P.fishFinTip, tip * 0.85);
        const ray = Math.floor((Math.atan2(y - a[1], x - a[0]) + 7) * (r === FR.tail ? 7.5 : 9));
        if (t.row === -2 && (ray & 1)) col = U.mixc(col, P.fishFinRay, 0.32 * (1 - tip));
        if (t.row === 0) col = U.mixc(col, P.fishFinTip, 0.3);
        mat = Scene.MAT.glass; alpha = 0.72 + 0.2 * (1 - tip); amt = 0.5;
        if (r === FR.pectoral) { col = U.mixc(P.fishFin, P.fishFinTip, tip * 0.5); alpha = 0.62 + 0.15 * (1 - tip); }
        if (t.row === 0 && r2 < 0.14 && r !== FR.pectoral) { col = P.goldPale; mat = Scene.MAT.gold; alpha = 1; }
      }
    }
    return { col: U.vary(col, r1, r2, r3, amt), mat, alpha, rnd: r3 };
  }

  // ---------- build tiles ----------
  function build(seed) {
    const s = FC.scale, gap = CONFIG.tiles.gapFine / s;
    const polar = (cx, cy, a0, a1, rays, grow = 0) => ({ type: 'polar', cx, cy, a0, a1, rays, grow, r0: 2 });
    const common = { x0: -172, y0: -56, w: 182, h: 116, res: 0.5, gap };
    const ghost = { size: 4.4, rows: 1, ghost: true };
    const main = Tiler.build(Object.assign({}, common, {
      rng: U.mulberry32(seed),
      regionAt: regionMain,
      spec: {
        0: ghost,
        [FR.body]: { size: FC.tileBody, rowScale: 0.92 },
        [FR.head]: { size: FC.tileHead },
        [FR.belly]: { size: FC.tileBody * 0.95 },
        [FR.gill]: { size: 3.0, gap: gap * 0.8, minArea: 0.05, priority: -1 },
        [FR.iris]: { size: 2.6, gap: gap * 0.7, minArea: 0.05, priority: -2, jitter: 0.08 },
        [FR.pupil]: { size: 3.3, gap: gap * 0.7, minArea: 0.05, priority: -2, jitter: 0.06 },
        [FR.eyeHi]: { size: 2.6, gap: gap * 0.5, minArea: 0.02, priority: -3, jitter: 0 },
        [FR.mouth]: { size: 2.4, gap: gap * 0.6, minArea: 0.05 },
        [FR.dorsal]: { size: FC.tileFin, rows: 1, fill: polar(-50, 17, 0.6, 2.75, 10, 0.004) },
        [FR.tail]: { size: FC.tileTail, rows: 1, fill: polar(-88, 0, Math.PI - 0.95, Math.PI + 0.95, 13, 0.006) },
        [FR.pelvic]: { size: 4.2, rows: 1, fill: polar(-40, -21, -2.8, -1.9, 3) },
        [FR.anal]: { size: 4.2, rows: 1, fill: polar(-69, -11, -2.8, -1.9, 3) },
      },
    }));
    const pect = Tiler.build(Object.assign({}, common, {
      rng: U.mulberry32(seed + 1),
      regionAt: regionPect,
      spec: { 0: ghost, [FR.pectoral]: { size: 4.3, rows: 1, fill: polar(-20, -8, -3.1, -2.2, 5, 0.01) } },
    }));
    const rng = U.mulberry32(seed + 7);
    const tiles = main.tiles.concat(pect.tiles).map((t) => {
      const st = styleTile(t, rng);
      return Object.assign(t, st, { layer: LAYER[t.region], part: PART[t.region] || 'body',
        dirx: t.cx + 40, diry: t.cy });
    });
    tiles.sort((a, b) => a.layer - b.layer);
    return tiles;
  }

  // ---------- rig ----------
  const NS = 64;
  const spX = new Float64Array(NS), spY = new Float64Array(NS), spA = new Float64Array(NS);

  // pose: {x, y, axis, sx, curl, phase, amp, spread, pect, drag, loosen, stretch,
  //        lookX, lookY, lag(l) → local angle offset from heading history, t}
  function buildSpine(pose) {
    const dl = Ltot / (NS - 1);
    let x = 0, y = 0;
    const k = 2 * Math.PI / (1.15 * Ltot);
    for (let i = 0; i < NS; i++) {
      const l = i * dl;
      const w = U.smoothstep(0.1 * Lb, 0.55 * Lb, l);
      const ln = l / Ltot;
      const wave = pose.amp * (0.03 + 0.62 * Math.pow(ln, 1.5)) * Math.sin(pose.phase - k * l);
      const th = w * (pose.curl * (l - 0.1 * Lb) / Lb + pose.lag(l)) + wave * (0.25 + 0.75 * w);
      spA[i] = th;
      spX[i] = x; spY[i] = y;
      x += -Math.cos(th) * dl; y += -Math.sin(th) * dl;
    }
  }
  function mapLocal(fx, fy, out, pose, part) {
    const st = pose.stretch;
    fx *= st; fy /= Math.sqrt(st);
    let l = -fx;
    const dl = Ltot / (NS - 1);
    let px, py, th;
    if (l <= 0) { th = spA[0]; px = -Math.cos(th) * l; py = -Math.sin(th) * l; }
    else if (l >= Ltot) { th = spA[NS - 1]; const e = l - Ltot; px = spX[NS - 1] - Math.cos(th) * e; py = spY[NS - 1] - Math.sin(th) * e; }
    else {
      const f = l / dl, i = Math.floor(f), t = f - i;
      const i1 = Math.min(NS - 1, i + 1);
      th = spA[i] + (spA[i1] - spA[i]) * t;
      px = spX[i] + (spX[i1] - spX[i]) * t; py = spY[i] + (spY[i1] - spY[i]) * t;
    }
    if (l > Lb * st) {
      // tail fan: spread & a 3/4-view flutter from the lateral beat
      const tl = (l - Lb * st) / (Lt * st);
      fy *= pose.spread * (1 + 0.16 * tl * Math.sin(pose.phase - 1.4 - tl * 2.2));
    }
    out[0] = px - Math.sin(th) * fy;
    out[1] = py + Math.cos(th) * fy;
  }

  // Fin articulation in local space (before the spine carries it).
  function finLocal(part, fx, fy, pose, out) {
    if (part === 'dorsal') {
      const h = Math.max(0, fy - top(U.clamp(-fx / Lb)));
      const k = 0.18 + 0.4 * pose.drag + 0.1 * Math.sin(pose.phase * 0.9 - h * 0.12);
      out[0] = fx - h * k; out[1] = fy - h * 0.12 * pose.drag; return;
    }
    if (part === 'pectoral' || part === 'pelvic' || part === 'anal') {
      const a = ATTACH[part];
      let ang;
      if (part === 'pectoral') ang = -0.55 * (1 - pose.pect) + 0.42 * pose.drag + 0.22 * Math.sin(pose.t * 5.2 + 0.4) * pose.pect;
      else ang = 0.35 * pose.drag + 0.12 * Math.sin(pose.phase * 0.8 + (part === 'anal' ? 1.2 : 0));
      // fold toward the body when dragging (positive = toward tail/up)
      const dx = fx - a[0], dy = fy - a[1];
      const c = Math.cos(ang), s = Math.sin(ang);
      const flex = 1 + 0.15 * Math.hypot(dx, dy) / 20 * Math.sin(pose.t * 6 + fx * 0.1) * pose.pect;
      out[0] = a[0] + (dx * c + dy * s) * flex; out[1] = a[1] + (-dx * s + dy * c) * flex; return;
    }
    out[0] = fx; out[1] = fy;
  }

  // Emit world-space tile polygons for this pose. cb(tile, worldPolyFlat, cx, cy)
  const tmp = [0, 0], tmp2 = [0, 0];
  function pose(tiles, ps, cb) {
    buildSpine(ps);
    const sc = FC.scale;
    // pivot
    mapLocal(-FC.pivotU * Lb, 0, tmp, ps, 'body');
    const pvx = tmp[0], pvy = tmp[1];
    const ca = Math.cos(ps.axis), sa = Math.sin(ps.axis);
    const toWorld = (lx, ly, o) => {
      const ax = (lx - pvx) * sc * ps.sx, ay = (ly - pvy) * sc;
      // fx along the axis, fy up (screen y is down)
      o[0] = ps.x + ax * ca + ay * sa;
      o[1] = ps.y + ax * sa - ay * ca;
    };
    for (const t of tiles) {
      const poly = t.poly, n = poly.length >> 1;
      // loosening: drift outward from the body, small twist and shrink
      const L = ps.loosen;
      const rnd = t.rnd;
      let ox = 0, oy = 0, rot = 0, shr = 1;
      if (L > 0) {
        const dx = t.cx + 46, dy = t.cy;
        const dd = Math.hypot(dx, dy) + 1e-3;
        const amp = L * (0.5 + 1.5 * rnd) * (0.5 + 0.5 * Math.min(1, dd / 40));
        const fl = Math.sin(ps.t * (1.7 + rnd * 1.3) + rnd * 40);
        ox = dx / dd * amp + Math.cos(rnd * 90) * L * 0.6 * fl;
        oy = dy / dd * amp + Math.sin(rnd * 90) * L * 0.6 * fl;
        rot = L * (rnd - 0.5) * 0.7 * (0.6 + 0.4 * fl);
        shr = 1 - 0.12 * L;
      }
      let lookx = 0, looky = 0;
      if (t.region === FR.pupil) { lookx = ps.lookX * 1.5; looky = ps.lookY * 1.4; }
      const cr = Math.cos(rot), sr = Math.sin(rot);
      const out = new Array(n * 2);
      let wcx = 0, wcy = 0;
      for (let i = 0; i < n; i++) {
        let lx = poly[2 * i] - t.cx, ly = poly[2 * i + 1] - t.cy;
        const rx = (lx * cr - ly * sr) * shr, ry = (lx * sr + ly * cr) * shr;
        lx = t.cx + rx + ox + lookx; ly = t.cy + ry + oy + looky;
        finLocal(t.part, lx, ly, ps, tmp2);
        mapLocal(tmp2[0], tmp2[1], tmp, ps, t.part);
        toWorld(tmp[0], tmp[1], tmp2);
        out[2 * i] = tmp2[0]; out[2 * i + 1] = tmp2[1];
        wcx += tmp2[0]; wcy += tmp2[1];
      }
      cb(t, out, wcx / n, wcy / n);
    }
  }

  // world position of a local fish point (for ribbon emission etc.)
  function pointWorld(ps, fx, fy) {
    buildSpine(ps);
    mapLocal(-FC.pivotU * Lb, 0, tmp, ps, 'body');
    const pvx = tmp[0], pvy = tmp[1];
    mapLocal(fx, fy, tmp, ps, 'body');
    const sc = FC.scale, ca = Math.cos(ps.axis), sa = Math.sin(ps.axis);
    const ax = (tmp[0] - pvx) * sc * ps.sx, ay = (tmp[1] - pvy) * sc;
    return [ps.x + ax * ca + ay * sa, ps.y + ax * sa - ay * ca];
  }

  return { build, pose, pointWorld, Lb, Lt, Ltot, FR };
})();
