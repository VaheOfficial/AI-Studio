// util.js — seeded randomness, math helpers, easing, colour and keyframe tracks.
// Everything here is pure: same inputs → same outputs, which is what makes
// seek(t) deterministic.
'use strict';

const U = (() => {
  // ---------- seeded randomness ----------
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // Stateless hash → [0,1). Used for per-tile / per-particle constants.
  function hash1(n) {
    let x = Math.imul((n | 0) ^ 0x9E3779B9, 0x85EBCA6B);
    x ^= x >>> 13; x = Math.imul(x, 0xC2B2AE35); x ^= x >>> 16;
    return (x >>> 0) / 4294967296;
  }
  function hash2(x, y, s = 0) {
    return hash1((x | 0) * 73856093 ^ (y | 0) * 19349663 ^ (s | 0) * 83492791);
  }
  // Smooth value noise in 2D, deterministic.
  function vnoise(x, y, s = 0) {
    const xi = Math.floor(x), yi = Math.floor(y);
    const xf = x - xi, yf = y - yi;
    const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
    const a = hash2(xi, yi, s), b = hash2(xi + 1, yi, s);
    const c = hash2(xi, yi + 1, s), d = hash2(xi + 1, yi + 1, s);
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
  }
  function fbm(x, y, s = 0, oct = 4) {
    let sum = 0, amp = 0.5, f = 1, norm = 0;
    for (let i = 0; i < oct; i++) {
      sum += amp * vnoise(x * f, y * f, s + i * 17);
      norm += amp; amp *= 0.5; f *= 2.03;
    }
    return sum / norm;
  }

  // ---------- math ----------
  const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smoothstep = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
  const smootherstep = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * t * (t * (t * 6 - 15) + 10); };
  const wrapAngle = (a) => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };
  const len = (x, y) => Math.sqrt(x * x + y * y);

  // ---------- easing (for keyframe segments) ----------
  const Ease = {
    linear: (t) => t,
    in: (t) => t * t,
    out: (t) => 1 - (1 - t) * (1 - t),
    inOut: (t) => t * t * (3 - 2 * t),
    in3: (t) => t * t * t,
    out3: (t) => 1 - Math.pow(1 - t, 3),
    inOut3: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    outBack: (t) => { const c = 1.6; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); },
    inBack: (t) => { const c = 1.4; return (c + 1) * t * t * t - c * t * t; },
    outElastic: (t) => (t === 0 || t === 1 ? t : Math.pow(2, -9 * t) * Math.sin((t * 8 - 0.75) * (2 * Math.PI) / 3) + 1),
  };

  // Scalar keyframe track: keys = [[t, v, ease?], ...]. Ease names the curve
  // used to arrive at that key from the previous one.
  function track(keys) {
    return function (t) {
      if (t <= keys[0][0]) return keys[0][1];
      for (let i = 1; i < keys.length; i++) {
        const k1 = keys[i];
        if (t <= k1[0]) {
          const k0 = keys[i - 1];
          const e = Ease[k1[2] || 'inOut'];
          return k0[1] + (k1[1] - k0[1]) * e((t - k0[0]) / (k1[0] - k0[0]));
        }
      }
      return keys[keys.length - 1][1];
    };
  }

  // Smooth vector path (non-uniform Catmull–Rom / cubic Hermite).
  // keys = [{t, x, y}] ; optional {vx, vy} overrides the tangent at a key.
  function path(keys) {
    const n = keys.length;
    const tan = keys.map((k, i) => {
      if (k.vx !== undefined) return [k.vx, k.vy];
      if (i === 0 || i === n - 1) return [0, 0];
      const a = keys[i - 1], b = keys[i + 1];
      const dt = b.t - a.t;
      return [(b.x - a.x) / dt, (b.y - a.y) / dt];
    });
    function at(t) {
      if (t <= keys[0].t) return [keys[0].x, keys[0].y];
      if (t >= keys[n - 1].t) return [keys[n - 1].x, keys[n - 1].y];
      let i = 1;
      while (t > keys[i].t) i++;
      const k0 = keys[i - 1], k1 = keys[i];
      const h = k1.t - k0.t, s = (t - k0.t) / h;
      const s2 = s * s, s3 = s2 * s;
      const h00 = 2 * s3 - 3 * s2 + 1, h10 = s3 - 2 * s2 + s;
      const h01 = -2 * s3 + 3 * s2, h11 = s3 - s2;
      const m0 = tan[i - 1], m1 = tan[i];
      return [
        h00 * k0.x + h10 * h * m0[0] + h01 * k1.x + h11 * h * m1[0],
        h00 * k0.y + h10 * h * m0[1] + h01 * k1.y + h11 * h * m1[1],
      ];
    }
    return at;
  }

  // ---------- colour ----------
  function hex(h) {
    const v = parseInt(h.replace('#', ''), 16);
    return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
  }
  const mixc = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  const mulc = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const addc = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  // Per-tile glaze variation: shift value / warmth / saturation a little.
  function vary(c, r1, r2, r3, amt = 1) {
    const v = 1 + (r1 - 0.5) * 0.16 * amt;
    const warm = (r2 - 0.5) * 0.05 * amt;
    const lum = 0.3 * c[0] + 0.55 * c[1] + 0.15 * c[2];
    const sat = 1 + (r3 - 0.5) * 0.25 * amt;
    return [
      clamp((lum + (c[0] - lum) * sat) * v + warm),
      clamp((lum + (c[1] - lum) * sat) * v),
      clamp((lum + (c[2] - lum) * sat) * v - warm),
    ];
  }

  return {
    mulberry32, hash1, hash2, vnoise, fbm,
    clamp, lerp, smoothstep, smootherstep, wrapAngle, len,
    Ease, track, path,
    hex, mixc, mulc, addc, vary,
  };
})();
