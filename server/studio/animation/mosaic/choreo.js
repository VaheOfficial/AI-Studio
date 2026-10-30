// choreo.js — the acting. Every channel is a pure function of time.
//
// Fish pose = pivot path + orientation (axis angle, yaw) + body channels
// (curl, swim amplitude/frequency, tail spread, fins, loosen, squash, eyes).
// Heading follow-through: each spine sample looks up the heading a little
// in the past, so the head leads and the tail trails (overlapping action).
'use strict';

const Choreo = (() => {
  const TM = CONFIG.timing, B = CONFIG.scene.bowl;
  const T = U.track, PI = Math.PI;

  // ---------------- fish path (pivot ≈ centre of mass) ----------------
  const path = U.path([
    { t: 0.0, x: 638, y: 484, vx: -40, vy: -6 },
    { t: 1.4, x: 596, y: 472 },
    { t: 2.5, x: 566, y: 456 },
    { t: 2.95, x: 560, y: 451, vx: -10, vy: -4 },
    { t: 3.85, x: 628, y: 440, vx: 10, vy: -6 },
    { t: 4.35, x: 636, y: 437, vx: 0, vy: 0 },
    { t: 4.85, x: 620, y: 458, vx: 0, vy: 0 },             // wind-up: back and down
    { t: TM.breach, x: 652, y: 332, vx: 150, vy: -318 },    // burst through the surface
    { t: 6.5, x: 724, y: 156, vx: 30, vy: -4 },             // apex
    { t: 7.6, x: 731, y: 146, vx: 6, vy: -4 },              // suspended
    { t: 8.7, x: 737, y: 138, vx: 8, vy: -4 },
    { t: 9.7, x: 744, y: 134, vx: 2, vy: 1 },               // crescent toward the moon
    { t: 10.5, x: 740, y: 145, vx: -16, vy: 30 },           // turning back
    { t: TM.entry, x: 628, y: 334, vx: -150, vy: 262 },     // the dive
    { t: 12.8, x: 595, y: 412, vx: -50, vy: 82 },
    { t: 13.5, x: 572, y: 452, vx: -24, vy: 18 },
    { t: TM.flick, x: 562, y: 462, vx: -10, vy: 3 },
    { t: 14.6, x: 547, y: 466, vx: -30, vy: 0 },
    { t: 15.0, x: 538, y: 467, vx: -12, vy: 0 },
  ]);

  const yaw = T([[0, PI], [TM.turn[0], PI], [TM.turn[1], 0, 'inOut3'], [TM.airTurn[0], 0], [TM.airTurn[1], PI, 'inOut3'], [15, PI]]);
  // axis angle: right-facing → nose direction; left-facing → nose dir − π (positive = nose up)
  const axisKey = T([
    [0, 0.08], [1.4, 0.14], [2.5, 0.1], [2.95, 0.16],
    [3.85, -0.36, 'inOut'], [4.35, -0.5], [4.85, -0.62, 'inOut'], [5.2, -1.0],
    [6.5, -0.42, 'inOut'], [7.6, -0.12, 'inOut'], [8.7, -0.18], [9.7, -0.42, 'inOut'],
    [TM.airTurn[0], -0.3], [TM.airTurn[1], -0.95, 'inOut'], [11.6, -1.05],
    [12.9, -0.55, 'out'], [13.6, -0.04, 'inOut'], [15, 0.05],
  ]);
  const autoW = T([[0, 0], [4.9, 0], [5.15, 0.85], [6.15, 0.85], [6.6, 0], [10.8, 0], [11.3, 0.9], [12.5, 0.9], [13.1, 0]]);
  const curl = T([
    [0, 0.02], [2.95, 0.04], [3.4, -0.18], [3.85, 0.0], [4.35, 0.05],
    [4.85, 0.34, 'inOut'], [5.15, -0.26, 'out'], [5.7, 0.04], [6.5, 0.1],
    [8.4, -0.05], [9.6, -0.78, 'inOut'], [TM.airTurn[0], -0.6], [10.6, 0.15], [11.6, 0.05],
    [TM.entry, 0.0], [12.42, 0.36, 'out'], [12.95, -0.12], [13.6, 0.02], [14.15, 0], [14.3, -0.12], [14.6, 0.05], [15, 0],
  ]);
  const amp = T([
    [0, 0.55], [2.6, 0.5], [2.95, 0.35], [3.85, 0.42], [4.35, 0.18], [4.85, 0.14],
    [5.0, 1.25, 'out'], [5.42, 1.0], [6.1, 0.45], [6.6, 0.32], [10.0, 0.32], [10.85, 0.4], [12.0, 0.25],
    [12.35, 0.95, 'out'], [13.0, 0.6], [13.8, 0.3], [TM.flick, 0.25], [14.28, 1.0, 'out'], [14.7, 0.35], [15, 0.25],
  ]);
  const freq = T([
    [0, 1.45], [2.95, 1.2], [3.85, 1.0], [4.35, 0.8], [4.85, 0.6], [5.0, 4.4, 'out'], [5.42, 3.6], [6.2, 1.6],
    [6.8, 0.75], [10.0, 0.75], [10.85, 1.1], [12.1, 1.3], [12.4, 2.8], [13.2, 1.6], [13.9, 1.0],
    [TM.flick, 1.0], [14.25, 3.6, 'out'], [14.7, 1.2], [15, 1.0],
  ]);
  const spread = T([[0, 1.0], [4.35, 0.95], [4.85, 0.78], [5.42, 0.86], [6.5, 1.08], [8.5, 1.18], [10, 1.12], [11.6, 0.86], [12.4, 0.95], [13.4, 1.04], [15, 1.02]]);
  const pect = T([[0, 0.55], [2.75, 0.6], [2.95, 1.0, 'out'], [3.85, 0.85], [4.35, 0.9], [4.85, 0.15], [5.42, 0.05],
    [6.5, 0.6], [7.3, 1.0], [10, 1.0], [10.85, 0.6], [11.6, 0.15], [12.4, 0.2], [12.9, 0.9], [14, 0.7], [15, 0.65]]);
  const loosen = T([[0, 0], [5.2, 0], [5.9, 0.55, 'out'], [7.2, 0.75], [9.4, 1.0], [10.6, 0.8], [11.9, 0.4],
    [TM.entry, 0.3], [12.32, 0.85, 'out'], [12.62, 0.22, 'inOut'], [12.95, 0.4], [13.4, 0.06], [13.9, 0]]);
  const stretch = T([[0, 1], [4.35, 1], [4.85, 0.92, 'inOut'], [5.12, 1.08, 'out'], [5.7, 1.0], [11.8, 1.0],
    [TM.entry, 1.06], [12.38, 0.95, 'out'], [12.75, 1.0], [14.15, 1.0], [14.25, 0.97], [14.45, 1.0]]);
  const lookX = T([[0, 0.35], [2.6, 0.35], [2.78, -0.55, 'out'], [3.0, -0.6], [3.6, 0.6], [4.35, 0.75],
    [6.5, 0.7], [8.4, 0.9], [10.0, 0.9], [10.5, 0.2], [11.0, 0.7], [12.9, 0.7], [13.8, 0.35], [15, 0.3]]);
  const lookY = T([[0, 0.0], [2.6, 0.0], [2.78, 0.8, 'out'], [3.6, 0.85], [4.35, 0.7], [6.5, 0.4], [8.4, 0.3],
    [10.0, 0.2], [10.5, -0.6], [12.4, -0.6], [13.2, -0.1], [15, -0.05]]);

  // swim phase = 2π ∫ freq dt (fixed-step integral → deterministic, order-free)
  function phase(t) {
    const h = 1 / 240; let p = 0, tt = 0;
    while (tt + h <= t) { p += freq(tt + h * 0.5) * h; tt += h; }
    p += freq((tt + t) * 0.5) * (t - tt);
    return 2 * PI * p;
  }

  function vel(t) {
    const h = 1 / 240;
    const a = path(t - h), b = path(t + h);
    return [(b[0] - a[0]) / (2 * h), (b[1] - a[1]) / (2 * h)];
  }
  function axisAt(t) {
    const key = axisKey(t), w = autoW(t);
    if (w <= 0) return key;
    const v = vel(t), sp = Math.hypot(v[0], v[1]);
    const s = Math.cos(yaw(t));
    let a = Math.atan2(v[1], v[0]);
    if (s < 0) a -= PI;
    a = key + U.wrapAngle(a - key);
    return U.lerp(key, a, w * U.smoothstep(30, 120, sp));
  }

  // breathing idle motion so the fish never sits perfectly still
  function idle(t) { return [Math.sin(t * 1.3) * 1.2, Math.sin(t * 0.9 + 1) * 1.0]; }

  function fishPose(t) {
    const p = path(t), id = idle(t);
    const iw = 1 - U.smoothstep(4.6, 5.0, t) + U.smoothstep(13.0, 14.0, t);
    const sx = Math.cos(yaw(t));
    const ax = axisAt(t);
    const sgn = sx >= 0 ? 1 : -1;
    const v = vel(t), speed = Math.hypot(v[0], v[1]);
    const lag = (l) => {
      const tau = 0.26 * l / Fish.Ltot;
      return -sgn * (axisAt(t - tau) - ax) * 0.9;
    };
    return {
      t, x: p[0] + id[0] * Math.min(1, iw), y: p[1] + id[1] * Math.min(1, iw),
      axis: ax, sx, curl: curl(t), phase: phase(t), amp: amp(t), spread: spread(t),
      pect: pect(t), drag: U.smoothstep(60, 320, speed), loosen: loosen(t), stretch: stretch(t),
      lookX: lookX(t), lookY: lookY(t), lag, speed,
    };
  }

  // ---------------- camera ----------------
  const camPath = U.path(CONFIG.camera.map((k) => ({ t: k[0], x: k[1], y: k[2] })));
  const camZoom = U.track(CONFIG.camera.map((k) => [k[0], k[3], 'inOut']));
  function camera(t) { const p = camPath(t); return { x: p[0], y: p[1], zoom: camZoom(t) }; }

  // ---------------- night wave ----------------
  const SUN = CONFIG.scene.sun;
  function flipTime(x, y, rnd) {
    return TM.nightStart + Math.hypot(x - SUN.x, y - SUN.y) / TM.nightSpeed + (rnd - 0.5) * TM.flipJitter;
  }
  function nightAt(x, y, t) {
    const f = flipTime(x, y, 0.5);
    return U.smoothstep(f, f + TM.flipDur, t);
  }

  // ---------------- glint & sunlight ----------------
  const glint = T([[0, 0], [TM.glintOn, 0], [TM.notice, 1.0, 'out'], [3.1, 0.55], [3.5, 0.95], [4.2, 0.6], [5.0, 0.9],
    [6.3, 1.0], [7.1, 0.8], [7.9, 0.0]]);
  function sunBand(t) { return 360 + 92 * t; }

  // ---------------- water ribbon & splash (ballistic, analytic) ----------------
  const RIB = 46, SPL = 44, G1 = 520, G2 = 1050;
  const ribbon = [];
  for (let k = 0; k < RIB; k++) {
    const r = U.hash1(k * 31 + 7), r2 = U.hash1(k * 17 + 3), r3 = U.hash1(k * 13 + 11);
    ribbon.push({ te: TM.breach + 0.02 + k * 0.017 + r * 0.01, r, r2, r3 });
  }
  const splash = [];
  for (let k = 0; k < SPL; k++) {
    const r = U.hash1(k * 37 + 101), r2 = U.hash1(k * 19 + 55), r3 = U.hash1(k * 23 + 77);
    const side = k & 1 ? 1 : -1;
    splash.push({ r, r2, r3, vx: side * (40 + 170 * r) - 40, vy: -(190 + 260 * r2) * (1 - 0.35 * Math.abs(r - 0.5)), te: TM.entry + 0.01 + r3 * 0.09 });
  }
  // Ribbon emission state is cached per droplet (it depends only on constants).
  let ribState = null;
  function ribInit() {
    ribState = ribbon.map((d, k) => {
      const ps = fishPose(d.te);
      const tail = Fish.pointWorld(ps, -Fish.Lb * (0.62 + 0.3 * d.r), (d.r2 - 0.5) * 18);
      const v = vel(d.te);
      const keep = 0.97 - 0.42 * (k / RIB) - 0.08 * d.r3;
      return {
        x: tail[0], y: Math.min(tail[1], B.waterY - 2),
        vx: v[0] * keep * 0.55 + (d.r - 0.5) * 26, vy: v[1] * keep + (d.r3 - 0.5) * 24,
      };
    });
  }
  // cb(x, y, vx, vy, size, life, seed)
  function particles(t, cb) {
    if (!ribState) ribInit();
    for (let k = 0; k < RIB; k++) {
      const d = ribbon[k], s = ribState[k];
      const dt = t - d.te; if (dt < 0) continue;
      const x = s.x + s.vx * dt, y = s.y + s.vy * dt + 0.5 * G1 * dt * dt;
      const vy = s.vy + G1 * dt;
      if (vy > 0 && y > B.waterY + 2) continue;           // back in the bowl
      const life = U.smoothstep(0, 0.08, dt);
      cb(x, y, s.vx, vy, (3.6 + 3.6 * d.r2) * (1 - 0.3 * k / RIB), life, k);
    }
    for (let k = 0; k < SPL; k++) {
      const d = splash[k];
      const dt = t - d.te; if (dt < 0) continue;
      const x0 = 622 + (d.r - 0.5) * 46;
      const x = x0 + d.vx * dt, y = B.waterY - 2 + d.vy * dt + 0.5 * G2 * dt * dt;
      const vy = d.vy + G2 * dt;
      if (vy > 0 && y > B.waterY + 1) continue;
      cb(x, y, d.vx, vy, 3.0 + 3.8 * d.r3, U.smoothstep(0, 0.04, dt), 100 + k);
    }
  }

  // Ripple events: [x, y, t0, amplitude]
  const ripples = [
    [640, B.waterY + 2, TM.breach - 0.06, 5.5],
    [664, B.waterY + 2, TM.breach + 0.24, 3.0],
    [690, B.waterY + 2, 6.35, 2.2],
    [628, B.waterY + 2, TM.entry - 0.04, 8.0],
    [612, B.waterY + 2, TM.entry + 0.3, 3.0],
    [575, B.waterY + 2, TM.flick + 0.12, 1.4],
  ];

  return { fishPose, camera, flipTime, nightAt, glint, sunBand, particles, ripples, path };
})();
