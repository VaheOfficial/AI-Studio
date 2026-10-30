// scene.js — the static set: wall, window, sky, sill and the glass bowl.
// regionAt() defines the shapes the mosaic follows; tileStyle() decides each
// tessera's day colour, night colour, material and flags.
'use strict';

const Scene = (() => {
  const G = CONFIG.scene, T = CONFIG.tiles;
  const P = {};
  for (const k in CONFIG.palette) {
    const v = CONFIG.palette[k];
    P[k] = Array.isArray(v) ? v.map(U.hex) : U.hex(v);
  }

  const REG = {
    wall: 1, frame: 2, sky: 3, sun: 4, moonDark: 5, roof: 6, litWin: 7,
    sillTop: 8, sillFront: 9, goldLine: 10, under: 11,
    bowlAir: 12, water: 13, surface: 14, edge: 15, rimBack: 16, rimFront: 17,
    gravel: 18, base: 19, reflect: 20, opening: 21,
  };
  // Materials (shader ids)
  const MAT = { ceramic: 0, glass: 1, gold: 2, silver: 3, water: 4, emissive: 5 };
  // Flags (bitfield, decoded in the shader)
  const F = { ripple: 1, sky: 2, star: 4, glint: 8, dynamic: 16, sunbeam: 32, fish: 64, overlay: 128 };

  const W = G.window, B = G.bowl, S = G.sill;
  const rimRx = Math.sqrt(B.r * B.r - (B.rimY - B.cy) ** 2);
  const surfRx = Math.sqrt(B.r * B.r - (B.waterY - B.cy) ** 2) - B.edgeW * 0.6;
  const SILL_X0 = 232, SILL_X1 = 1048;

  // Distant rooftops seen through the lower panes: [xL, xR, eaveY, peakY]
  // Distant hills with a few small houses, low in the lower panes: [xc, halfW, height]
  const HOUSES = [[352, 20, 22], [398, 13, 15], [884, 22, 25], [936, 14, 16], [830, 12, 13]];
  const hill = (x) => 530 + 6 * Math.sin(x * 0.011 + 0.5) + 3 * Math.sin(x * 0.031 + 2);
  const LIT = HOUSES.map((h) => [h[0] + (h[0] % 2 ? -4 : 4), hill(h[0]) - h[2] * 0.42, 6, 7]);

  function roofLine(x) {
    let y = hill(x);
    for (const h of HOUSES) {
      const d = Math.abs(x - h[0]);
      if (d > h[1]) continue;
      const base = hill(h[0]);
      y = Math.min(y, base - h[2] + d / h[1] * h[2] * 0.42);
    }
    return y;
  }

  // ---------------- regions ----------------
  function inWindow(x, y) { return x > W.x0 && x < W.x1 && y > W.y0 && y < W.y1; }

  function bgRegion(x, y) {
    if (x > SILL_X0 && x < SILL_X1 && y >= S.top) {
      if (y < S.front) return REG.sillTop;
      if (y < S.bottom) return (y > S.front + 4 && y < S.front + 10 && x > SILL_X0 + 10 && x < SILL_X1 - 10) ? REG.goldLine : REG.sillFront;
      return REG.under;
    }
    if (y >= S.bottom) return REG.under;
    if (!inWindow(x, y)) return REG.wall;
    const f = W.frame, hb = W.bar / 2;
    if (x < W.x0 + f || x > W.x1 - f || y < W.y0 + f || y > W.y1 - f) return REG.frame;
    if (Math.abs(x - W.mullionX) < hb || Math.abs(y - W.transomY) < hb) return REG.frame;
    const sx = x - G.sun.x, sy = y - G.sun.y;
    if (sx * sx + sy * sy < G.sun.r * G.sun.r) {
      const mx = x - (G.sun.x + G.moonCut.dx), my = y - (G.sun.y + G.moonCut.dy);
      return mx * mx + my * my < G.moonCut.r * G.moonCut.r ? REG.moonDark : REG.sun;
    }
    if (y > W.transomY && y > roofLine(x)) {
      for (const l of LIT) if (Math.abs(x - l[0]) < l[2] / 2 && Math.abs(y - l[1]) < l[3] / 2) return REG.litWin;
      return REG.roof;
    }
    return REG.sky;
  }

  // Bowl regions (0 = not part of the bowl)
  function bowlRegion(x, y) {
    const dx = x - B.cx, dy = y - B.cy;
    const rr = Math.sqrt(dx * dx + dy * dy);
    // rim ellipse ring
    const ex = dx, ey = y - B.rimY;
    const eOut = (ex / (rimRx + 3)) ** 2 + (ey / (B.rimRy + 3)) ** 2;
    const eIn = (ex / (rimRx - 4)) ** 2 + (ey / (B.rimRy - 3.5)) ** 2;
    if (eOut < 1 && eIn >= 1) return ey < 0 ? REG.rimBack : REG.rimFront;
    if (rr >= B.r || y < B.rimY || y > B.baseY) return 0;
    if (eIn < 1) return REG.opening;
    if (y > B.baseY - 6) return REG.base;
    if (rr > B.r - B.edgeW) return REG.edge;
    // reflections of the window on the front of the glass
    const ang = Math.atan2(dy, dx) * 180 / Math.PI; // -180..180, y down
    const rn = rr / B.r;
    // curved window reflection hugging the glass (broken by the mullion), and a small one on the right
    const arcW = 0.055 * Math.sin(U.clamp((ang + 178) / 62) * Math.PI);
    if (Math.abs(rn - 0.84) < arcW && ang > -178 && ang < -116 && Math.abs(ang + 150) > 2.5) return REG.reflect;
    const arcW2 = 0.035 * Math.sin(U.clamp((ang + 58) / 26) * Math.PI);
    if (Math.abs(rn - 0.86) < arcW2 && ang > -58 && ang < -32) return REG.reflect;
    // water surface ellipse
    const sx = dx / surfRx, sy = (y - B.waterY) / B.surfRy;
    if (sx * sx + sy * sy < 1) return REG.surface;
    if (y < B.waterY) return REG.bowlAir;
    const front = B.waterY + B.surfRy * Math.sqrt(Math.max(0, 1 - sx * sx));
    if (y < front) return REG.bowlAir;
    const gTop = B.baseY - 34 + 6 * Math.sin(x * 0.045) + 0.0022 * dx * dx;
    if (y > gTop) return REG.gravel;
    return REG.water;
  }

  function regionAt(x, y) { return bowlRegion(x, y) || bgRegion(x, y); }

  // Where the background is seen through the water (a stylised lens).
  function refractPoint(x, y, k0 = 0.74, k1 = 0.2) {
    const dx = x - B.cx, dy = y - B.cy;
    const rn = Math.min(1, Math.hypot(dx, dy) / B.r);
    const k = k0 - k1 * rn * rn;
    return [B.cx + dx * k, B.cy + 30 + dy * k * 0.9];
  }

  // ---------------- background colour ----------------
  function bgColor(r, x, y, night, rnd) {
    const sunD = Math.hypot(x - G.sun.x, y - G.sun.y);
    const winD = Math.max(0, Math.max(W.x0 - x, x - W.x1, W.y0 - y, y - W.y1));
    const noise = U.fbm(x * 0.012, y * 0.012, 7, 3);
    switch (r) {
      case REG.sky: {
        const t = U.clamp((y - W.y0) / (W.y1 - W.y0));
        if (!night) {
          let c = t < 0.55 ? U.mixc(P.skyDayTop, P.skyDayMid, U.smoothstep(0, 0.55, t))
                           : U.mixc(P.skyDayMid, P.skyDayLow, U.smoothstep(0.55, 1, t));
          const cloud = U.smoothstep(0.55, 0.75, U.fbm(x * 0.006, y * 0.022, 3, 4));
          c = U.mixc(c, [1, 0.97, 0.9], cloud * 0.35);
          return U.mixc(c, P.sunCore, Math.exp(-Math.max(0, sunD - G.sun.r) / 60) * 0.8);
        }
        let c = U.mixc(P.skyNightTop, P.skyNightLow, Math.pow(t, 1.3));
        return U.mixc(c, [0.36, 0.45, 0.72], Math.exp(-Math.max(0, sunD - G.sun.r) / 70) * 0.45);
      }
      case REG.sun:
        if (!night) return U.mixc(P.sunGold, P.sunCore, U.smoothstep(G.sun.r, 6, sunD));
        return U.mixc(P.moonGold, P.moonLit, U.smoothstep(G.sun.r, 10, sunD) * 0.8 + 0.2);
      case REG.moonDark:
        if (!night) return U.mixc(P.sunGold, P.sunCore, U.smoothstep(G.sun.r, 6, sunD));
        return P.moonDark;
      case REG.roof: {
        const hi = Math.floor(U.hash1(Math.floor((x - 280) / 46)) * 3);
        if (!night) {
          const c = [P.roofDayA, P.roofDayB, P.roofDayC][hi];
          return U.mixc(c, P.skyDayMid, 0.25);
        }
        return U.mixc(P.roofNightA, P.roofNightB, hi / 2);
      }
      case REG.litWin: return night ? P.litWindow : P.darkWindowDay;
      case REG.frame: {
        const f = W.frame;
        // distance to the glass edge, for an inner shadow line
        let edge = Math.min(Math.abs(x - (W.x0 + f)), Math.abs(x - (W.x1 - f)), Math.abs(y - (W.y0 + f)), Math.abs(y - (W.y1 - f)),
          Math.abs(Math.abs(x - W.mullionX) - W.bar / 2), Math.abs(Math.abs(y - W.transomY) - W.bar / 2));
        const shade = U.smoothstep(6, 0, edge) * 0.55 + noise * 0.15;
        return night ? U.mixc(P.frameNight, P.frameNightShade, shade) : U.mixc(P.frameDay, P.frameDayShade, shade);
      }
      case REG.wall: {
        if (!night) {
          let c = U.mixc(P.wallDayWarm, P.wallDay, U.smoothstep(0, 140, winD));
          c = U.mixc(c, P.wallDayShade, U.smoothstep(150, 420, winD) * 0.8);
          return U.mulc(c, 0.95 + noise * 0.1);
        }
        let c = U.mixc(P.wallNightLit, P.wallNight, U.smoothstep(0, 170, winD));
        return U.mulc(c, 0.93 + noise * 0.12);
      }
      case REG.sillTop: {
        let c = night ? P.sillNight : P.sillDay;
        // bowl shadow thrown forward-left, with a focused caustic inside
        const sh = Math.exp(-(((x - (B.cx - 46)) / 130) ** 2 + ((y - 608) / 15) ** 2) * 1.4);
        const ca = Math.exp(-(((x - (B.cx - 54)) / 34) ** 2 + ((y - 610) / 5.5) ** 2) * 1.5);
        const contact = Math.exp(-(((x - B.cx) / 64) ** 2 + ((y - 601) / 3.5) ** 2) * 2);
        if (!night) {
          c = U.mixc(c, U.mixc(P.shadowDay, [0.42, 0.36, 0.3], sh * 0.4), U.clamp(sh * 1.1));
          c = U.mixc(c, U.mixc(P.causticDay, P.causticGold, rnd * 0.8), U.clamp(ca * 1.2));
        } else {
          c = U.mixc(c, P.sillNightFront, sh * 0.6);
          c = U.mixc(c, [0.55, 0.72, 0.9], ca * 0.5);
        }
        c = U.mulc(c, 1 - contact * 0.35);
        return U.mulc(c, 1.04 - 0.08 * U.smoothstep(S.top, S.front, y));
      }
      case REG.sillFront: return night ? P.sillNightFront : U.mulc(P.sillDayFront, 0.96 + noise * 0.08);
      case REG.goldLine: return night ? U.mulc(P.gold, 0.85) : P.gold;
      case REG.under: {
        const t = U.smoothstep(S.bottom, S.bottom + 60, y);
        return night ? U.mulc(P.underSillNight, 1.1 - 0.2 * t) : U.mulc(P.underSillDay, 1.0 - 0.18 * t);
      }
    }
    return [1, 0, 1];
  }

  // ---------------- per-tile style ----------------
  function tileStyle(t, rng) {
    const x = t.cx, y = t.cy, r = t.region;
    const r1 = rng(), r2 = rng(), r3 = rng(), r4 = rng();
    let day, night, md = MAT.ceramic, mn = MAT.ceramic, flags = 0, alpha = 1, amt = 0.8;
    const isBg = r <= REG.under;
    if (isBg) {
      day = bgColor(r, x, y, false, r4); night = bgColor(r, x, y, true, r4);
      if (r === REG.sky || r === REG.sun || r === REG.moonDark || r === REG.roof || r === REG.litWin) flags |= F.sky;
      if (r === REG.sky) { md = mn = MAT.glass; amt = 0.45; }
      if (r === REG.sun) { md = MAT.gold; mn = MAT.silver; amt = 0.5; }
      if (r === REG.moonDark) { md = MAT.gold; mn = MAT.ceramic; amt = 0.4; }
      if (r === REG.litWin) { mn = MAT.emissive; md = MAT.glass; }
      if (r === REG.goldLine) { md = mn = MAT.gold; amt = 0.5; }
      if (r === REG.frame) amt = 0.45;
      if (r === REG.wall) amt = 0.5;
      if (r === REG.wall || r === REG.sillTop || r === REG.sillFront || r === REG.frame || r === REG.under) flags |= F.sunbeam;
      if (r === REG.sky) {
        const md2 = Math.hypot(x - G.sun.x, y - G.sun.y);
        const edgeD = Math.min(Math.abs(x - W.mullionX), Math.abs(y - W.transomY), x - W.x0, W.x1 - x, y - W.y0);
        if (y < 470 && edgeD > 30 && md2 > G.sun.r + 26 && U.hash1(t.sx * 7 + t.sy * 131) < 0.026) {
          flags |= F.star; mn = MAT.emissive;
          night = r1 < 0.28 ? P.starGold : U.mixc(P.star, [0.62, 0.72, 0.95], r2 * 0.5);
        }
        const gd = Math.hypot(x - G.glint.x, y - G.glint.y);
        if (gd < 26) flags |= F.glint;
      }
    } else {
      // bowl: colour = what is behind, seen through tinted glass / water
      const behind = (px, py, nt) => { const br = bgRegion(px, py); return bgColor(br, px, py, nt, r4); };
      const dx = x - B.cx, dy = y - B.cy, rn = Math.hypot(dx, dy) / B.r;
      switch (r) {
        case REG.water: case REG.gravel: {
          const q = refractPoint(x, y);
          const dep = U.clamp((y - B.waterY) / (B.baseY - B.waterY));
          const edgeK = Math.pow(rn, 4);
          let wd = U.mixc(P.waterLight, P.water, U.smoothstep(0, 0.32, dep));
          wd = U.mixc(wd, P.waterDeep, U.smoothstep(0.35, 1, dep) * 0.55 + edgeK * 0.45);
          let wn = U.mixc(P.waterNight, P.waterNightDeep, U.smoothstep(0.1, 1, dep) * 0.6 + edgeK * 0.4);
          const bd = behind(q[0], q[1], false), bn = behind(q[0], q[1], true);
          day = U.mixc(wd, [bd[0] * wd[0] * 1.9, bd[1] * wd[1] * 1.5, bd[2] * wd[2] * 1.35], 0.26);
          night = U.mixc(wn, [bn[0] * 1.2, bn[1] * 1.3, bn[2] * 1.4], 0.14);
          md = mn = MAT.water; flags |= F.ripple; amt = 0.5;
          if (r === REG.gravel) {
            const g = P.gravel[Math.floor(r1 * P.gravel.length)];
            day = U.mixc(g, wd, 0.3); night = U.mixc(U.mulc(g, 0.45), wn, 0.45);
            md = mn = (r1 > 0.5 ? MAT.glass : MAT.ceramic); amt = 0.6;
            if (r2 < 0.12) { md = mn = MAT.gold; day = U.mixc(P.gold, wd, 0.2); night = U.mixc(P.gold, wn, 0.5); }
          }
          break;
        }
        case REG.surface: {
          const sx = dx / surfRx;
          const back = U.smoothstep(B.waterY + 4, B.waterY - B.surfRy, y);
          day = U.mixc(P.waterSurfaceDay, P.skyDayLow, back * 0.35 + U.smoothstep(0.2, 1, sx) * 0.25);
          night = U.mixc(P.waterSurfaceNight, P.waterNightDeep, 0.35 - back * 0.3);
          if (sx > 0.25 && sx < 0.7 && back > 0.3) night = U.mixc(night, P.moonLit, 0.45);
          md = mn = MAT.water; flags |= F.ripple; amt = 0.35;
          break;
        }
        case REG.opening: {
          day = U.mixc(behind(x, y + 6, false), P.glassDay, 0.45);
          night = U.mixc(behind(x, y + 6, true), P.glassNight, 0.35);
          md = mn = MAT.glass; amt = 0.25;
          break;
        }
        case REG.bowlAir: {
          const q = refractPoint(x, y, 0.97, 0.03);
          day = U.mixc(behind(q[0], q[1], false), P.glassDay, 0.34);
          night = U.mixc(behind(q[0], q[1], true), P.glassNight, 0.18);
          md = mn = MAT.glass; amt = 0.35;
          break;
        }
        case REG.edge: case REG.base: {
          const below = y > B.waterY + 8;
          const q = refractPoint(x, y, 0.6, 0.1);
          const bd = behind(q[0], q[1], false), bn = behind(q[0], q[1], true);
          day = U.mixc(below ? U.mixc(P.glassEdgeDay, P.waterDeep, 0.45) : P.glassEdgeDay, bd, 0.2);
          night = U.mixc(below ? U.mixc(P.glassNight, P.waterNightDeep, 0.5) : P.glassNight, bn, 0.2);
          // the lit (upper-right) side of the glass is brighter
          const lit = U.clamp(0.5 + 0.5 * (dx / B.r) - 0.4 * (dy / B.r));
          day = U.mulc(day, 0.85 + 0.3 * lit); night = U.mulc(night, 0.8 + 0.35 * lit);
          md = mn = MAT.glass; amt = 0.3;
          if (r === REG.edge && below) flags |= F.ripple;
          break;
        }
        case REG.rimBack: case REG.rimFront:
          day = U.mulc(P.rimDay, r === REG.rimBack ? 0.88 : 1); night = U.mulc(P.rimNight, r === REG.rimBack ? 0.85 : 1);
          if (r3 < 0.18) { day = P.goldPale; md = MAT.gold; } else md = MAT.glass;
          mn = MAT.glass; amt = 0.25;
          if (r === REG.rimFront) { flags |= F.overlay; alpha = 0.9; }
          break;
        case REG.reflect: {
          const ang = Math.atan2(dy, dx);
          const core = Math.exp(-Math.pow((rn - 0.84) / 0.03, 2));
          day = U.mixc(U.mixc(P.reflectDay, P.skyDayLow, r1 * 0.25), [1, 1, 1], core * 0.4);
          night = U.mixc(U.mixc(P.reflectNight, P.skyNightLow, 0.25 + r1 * 0.2), P.moonLit, core * 0.3 * (ang > -1.2 ? 1.5 : 0.6));
          md = mn = MAT.glass; flags |= F.overlay; alpha = 0.55 + 0.35 * core; amt = 0.2;
          break;
        }
      }
    }
    day = U.vary(day, r1, r2, r3, amt);
    night = U.vary(night, r2, r3, r1, amt * 0.8);
    return { day, night, md, mn, flags, alpha, rnd: r4 };
  }

  function specs() {
    const c = (size, rows, extra = {}) => Object.assign({ size, rows }, extra);
    const courses = (amp = 0, freq = 0, angle = 0) => ({ type: 'courses', waveAmp: amp, waveFreq: freq, angle });
    return {
      [REG.wall]: c(T.wall, 2, { fill: courses(1.2, 0.01), gap: 1.15 }),
      [REG.frame]: c(T.frame, undefined, { priority: -1 }),
      [REG.sky]: c(T.sky, 1, { fill: { type: 'rings', cx: G.sun.x, cy: G.sun.y, r0: G.sun.r + T.sky * 0.5, r1: 1100 }, gap: 1.3 }),
      [REG.sun]: c(T.sun, undefined, { priority: -2 }),
      [REG.moonDark]: c(T.sun, undefined, { priority: -2 }),
      [REG.roof]: c(T.roof, 2, { fill: courses(0, 0) }),
      [REG.litWin]: c(4.5, undefined, { minArea: 0.05 }),
      [REG.sillTop]: c(T.sill, 1, { fill: courses(0, 0) }),
      [REG.sillFront]: c(T.sill, 1, { fill: courses(0, 0) }),
      [REG.goldLine]: c(6, undefined, { gap: 1.2 }),
      [REG.under]: c(T.under, 2, { fill: courses(0, 0) }),
      [REG.bowlAir]: c(T.glass, 2, { fill: courses(1.5, 0.03) }),
      [REG.water]: c(T.water, 3, { fill: courses(3.2, 0.035) }),
      [REG.surface]: c(T.surface, undefined, { gap: 1.3 }),
      [REG.edge]: c(T.edge, undefined, { gap: 1.3, priority: -3 }),
      [REG.rimBack]: c(T.rim, undefined, { gap: 1.1, priority: -4, minArea: 0.05 }),
      [REG.rimFront]: c(T.rim, undefined, { gap: 1.1, priority: -4, minArea: 0.05 }),
      [REG.gravel]: c(T.gravel, 1, { fill: courses(2, 0.05), gap: 2.6, cap: 0.75 }),
      [REG.base]: c(T.base, undefined, { gap: 1.2 }),
      [REG.reflect]: c(5.0, undefined, { gap: 1.1, priority: -3, minArea: 0.04 }),
      [REG.opening]: c(4.6, undefined, { gap: 1.1, priority: -4, minArea: 0.04 }),
    };
  }

  function build(seed) {
    const w = CONFIG.world;
    const rng = U.mulberry32(seed);
    const res = Tiler.build({
      x0: w.x0, y0: w.y0, w: w.x1 - w.x0, h: w.y1 - w.y0, res: 1,
      regionAt, spec: specs(), gap: T.gapBg, rng,
    });
    const srng = U.mulberry32(seed ^ 0x5bd1e995);
    const tiles = res.tiles.map((t) => Object.assign(t, tileStyle(t, srng)));
    // overlay tiles last so they can be redrawn over the fish
    tiles.sort((a, b) => ((a.flags & F.overlay) ? 1 : 0) - ((b.flags & F.overlay) ? 1 : 0));
    const overlayStart = tiles.findIndex((t) => t.flags & F.overlay);
    return { tiles, overlayStart };
  }

  // Is a world point inside the water body (for the fish's submerged tint)?
  function waterDepthAt(x, y) {
    const dx = x - B.cx, dy = y - B.cy;
    if (dx * dx + dy * dy > B.r * B.r) return -1;
    return y - B.waterY;
  }

  return { REG, MAT, F, P, build, regionAt, bgRegion, refractPoint, waterDepthAt, rimRx, surfRx };
})();
