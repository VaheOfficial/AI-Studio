// tiler.js — contour-following mosaic tessellation ("andamento").
//
// 1. A region map is rasterised from an analytic regionAt(x, y).
// 2. An exact Euclidean distance transform gives every pixel its distance to
//    the nearest region boundary.
// 3. Seeds are laid in rows that follow iso-distance contours (opus
//    vermiculatum): each row is traced by stepping along the contour tangent
//    and projecting back onto the iso-line.  Interiors can then be filled with
//    straight / wavy courses (opus tessellatum) or radial rays (fins, tail).
// 4. Each seed's cell is a size-weighted Voronoi cell (half-plane clipping),
//    so rows on both sides of a boundary meet exactly on the outline.
// 5. Cells are inset by the grout gap, chamfered and jittered → tesserae.
'use strict';

const Tiler = (() => {
  // Sutherland–Hodgman clip of a polygon (flat [x,y,...]) by n·p <= c.
  function clip(poly, nx, ny, c) {
    const out = [];
    const n = poly.length >> 1;
    if (n === 0) return out;
    let px = poly[2 * n - 2], py = poly[2 * n - 1];
    let pd = nx * px + ny * py - c;
    for (let i = 0; i < n; i++) {
      const x = poly[2 * i], y = poly[2 * i + 1];
      const d = nx * x + ny * y - c;
      if (d <= 0) {
        if (pd > 0) { const t = pd / (pd - d); out.push(px + (x - px) * t, py + (y - py) * t); }
        out.push(x, y);
      } else if (pd <= 0) {
        const t = pd / (pd - d); out.push(px + (x - px) * t, py + (y - py) * t);
      }
      px = x; py = y; pd = d;
    }
    return out;
  }

  function area(poly) {
    let a = 0; const n = poly.length >> 1;
    for (let i = 0, j = n - 1; i < n; j = i++) a += poly[2 * j] * poly[2 * i + 1] - poly[2 * i] * poly[2 * j + 1];
    return a / 2;
  }
  function centroid(poly) {
    let a = 0, cx = 0, cy = 0; const n = poly.length >> 1;
    for (let i = 0, j = n - 1; i < n; j = i++) {
      const f = poly[2 * j] * poly[2 * i + 1] - poly[2 * i] * poly[2 * j + 1];
      a += f; cx += (poly[2 * j] + poly[2 * i]) * f; cy += (poly[2 * j + 1] + poly[2 * i + 1]) * f;
    }
    if (Math.abs(a) < 1e-9) return [poly[0], poly[1]];
    return [cx / (3 * a), cy / (3 * a)];
  }

  // Inset a convex polygon by g (intersection of inward-offset half-planes).
  function inset(poly, g) {
    const n = poly.length >> 1;
    const sgn = area(poly) > 0 ? 1 : -1;
    let out = poly;
    for (let i = 0; i < n; i++) {
      const x0 = poly[2 * i], y0 = poly[2 * i + 1];
      const x1 = poly[2 * ((i + 1) % n)], y1 = poly[2 * ((i + 1) % n) + 1];
      let ex = x1 - x0, ey = y1 - y0; const L = Math.hypot(ex, ey);
      if (L < 1e-6) continue;
      ex /= L; ey /= L;
      // outward normal for this orientation
      const nx = sgn * ey, ny = -sgn * ex;
      out = clip(out, nx, ny, nx * x0 + ny * y0 - g);
      if (out.length < 6) return null;
    }
    return out;
  }

  // Cut every corner a little: hand-cut, softened tesserae.
  function chamfer(poly, amount) {
    const n = poly.length >> 1, out = [];
    for (let i = 0; i < n; i++) {
      const x = poly[2 * i], y = poly[2 * i + 1];
      const pi = (i + n - 1) % n, ni = (i + 1) % n;
      const ax = poly[2 * pi] - x, ay = poly[2 * pi + 1] - y;
      const bx = poly[2 * ni] - x, by = poly[2 * ni + 1] - y;
      const la = Math.hypot(ax, ay), lb = Math.hypot(bx, by);
      const ca = Math.min(0.3, amount / Math.max(la, 1e-6));
      const cb = Math.min(0.3, amount / Math.max(lb, 1e-6));
      out.push(x + ax * ca, y + ay * ca, x + bx * cb, y + by * cb);
    }
    return out;
  }

  function dedupe(poly, eps) {
    const out = []; const n = poly.length >> 1;
    for (let i = 0; i < n; i++) {
      const x = poly[2 * i], y = poly[2 * i + 1];
      const m = out.length;
      if (m >= 2 && Math.abs(out[m - 2] - x) < eps && Math.abs(out[m - 1] - y) < eps) continue;
      out.push(x, y);
    }
    while (out.length >= 6 && Math.abs(out[0] - out[out.length - 2]) < eps && Math.abs(out[1] - out[out.length - 1]) < eps) out.length -= 2;
    return out;
  }

  // 1-D squared distance transform (Felzenszwalb & Huttenlocher).
  function edt1d(f, n, d, v, z) {
    let k = 0; v[0] = 0; z[0] = -Infinity; z[1] = Infinity;
    for (let q = 1; q < n; q++) {
      let s;
      while (true) {
        const p = v[k];
        s = ((f[q] + q * q) - (f[p] + p * p)) / (2 * q - 2 * p);
        if (s <= z[k]) { k--; if (k < 0) { k = 0; break; } } else break;
      }
      k++; v[k] = q; z[k] = s; z[k + 1] = Infinity;
    }
    k = 0;
    for (let q = 0; q < n; q++) {
      while (z[k + 1] < q) k++;
      const dq = q - v[k];
      d[q] = dq * dq + f[v[k]];
    }
  }
  function edt(mask, W, H) {
    const INF = 1e20;
    const g = new Float64Array(W * H);
    for (let i = 0; i < W * H; i++) g[i] = mask[i] ? 0 : INF;
    const N = Math.max(W, H);
    const f = new Float64Array(N), d = new Float64Array(N), v = new Int32Array(N), z = new Float64Array(N + 1);
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) f[y] = g[y * W + x];
      edt1d(f, H, d, v, z);
      for (let y = 0; y < H; y++) g[y * W + x] = d[y];
    }
    const out = new Float32Array(W * H);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) f[x] = g[y * W + x];
      edt1d(f, W, d, v, z);
      for (let x = 0; x < W; x++) out[y * W + x] = Math.sqrt(d[x]);
    }
    return out;
  }

  // ------------------------------------------------------------------
  function build(opt) {
    const { x0, y0, w, h, res, regionAt, spec } = opt;
    const rng = opt.rng;
    const W = Math.ceil(w / res), H = Math.ceil(h / res);
    const reg = new Int16Array(W * H);
    for (let j = 0; j < H; j++) {
      const y = y0 + (j + 0.5) * res;
      for (let i = 0; i < W; i++) reg[j * W + i] = regionAt(x0 + (i + 0.5) * res, y);
    }
    // boundary pixels
    const bnd = new Uint8Array(W * H);
    for (let j = 0; j < H; j++) for (let i = 0; i < W; i++) {
      const k = j * W + i, r = reg[k];
      if ((i > 0 && reg[k - 1] !== r) || (i < W - 1 && reg[k + 1] !== r) ||
          (j > 0 && reg[k - W] !== r) || (j < H - 1 && reg[k + W] !== r)) bnd[k] = 1;
    }
    const dist = edt(bnd, W, H);
    for (let k = 0; k < W * H; k++) dist[k] = (dist[k] + (bnd[k] ? 0.5 : 0.5)) * res;

    const R = (x, y) => {
      const i = Math.floor((x - x0) / res), j = Math.floor((y - y0) / res);
      if (i < 0 || j < 0 || i >= W || j >= H) return -1;
      return reg[j * W + i];
    };
    const D = (x, y) => {
      let fx = (x - x0) / res - 0.5, fy = (y - y0) / res - 0.5;
      fx = Math.max(0, Math.min(W - 1.001, fx)); fy = Math.max(0, Math.min(H - 1.001, fy));
      const i = Math.floor(fx), j = Math.floor(fy), tx = fx - i, ty = fy - j;
      const k = j * W + i;
      const a = dist[k], b = dist[k + 1], c = dist[k + W], d = dist[k + W + 1];
      return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
    };
    const grad = (x, y) => {
      const e = res;
      return [(D(x + e, y) - D(x - e, y)) / (2 * e), (D(x, y + e) - D(x, y - e)) / (2 * e)];
    };

    // ---- seeds + spatial hash ----
    let maxS = 0;
    for (const k in spec) maxS = Math.max(maxS, spec[k].size);
    const cell = maxS * 1.3;
    const hash = new Map();
    const S = { x: [], y: [], r: [], s: [], a: [], row: [] };
    const hkey = (cx, cy) => cx * 100003 + cy;
    function addSeed(x, y, r, s, a, row) {
      const idx = S.x.length;
      S.x.push(x); S.y.push(y); S.r.push(r); S.s.push(s); S.a.push(a); S.row.push(row);
      const key = hkey(Math.floor(x / cell), Math.floor(y / cell));
      let b = hash.get(key); if (!b) { b = []; hash.set(key, b); } b.push(idx);
      return idx;
    }
    function near(x, y, rad, r) {
      const cx = Math.floor(x / cell), cy = Math.floor(y / cell);
      const rr = rad * rad;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const b = hash.get(hkey(cx + dx, cy + dy)); if (!b) continue;
        for (const i of b) {
          if (r !== undefined && S.r[i] !== r) continue;
          const ex = S.x[i] - x, ey = S.y[i] - y;
          if (ex * ex + ey * ey < rr) return true;
        }
      }
      return false;
    }

    // bucket pixels per region (+ bbox)
    const buckets = new Map();
    for (let k = 0; k < W * H; k++) {
      const r = reg[k]; if (!spec[r]) continue;
      let b = buckets.get(r);
      if (!b) { b = { px: [], x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 }; buckets.set(r, b); }
      b.px.push(k);
      const i = k % W, j = (k / W) | 0;
      const x = x0 + (i + 0.5) * res, y = y0 + (j + 0.5) * res;
      if (x < b.x0) b.x0 = x; if (x > b.x1) b.x1 = x; if (y < b.y0) b.y0 = y; if (y > b.y1) b.y1 = y;
    }

    // ---- contour rows ----
    const order = Object.keys(spec).map(Number).sort((a, b) => (spec[a].priority || 0) - (spec[b].priority || 0));
    for (const r of order) {
      const sp = spec[r], b = buckets.get(r); if (!b) continue;
      const s = sp.size, rows = sp.rows === undefined ? 1e9 : sp.rows;
      const rs = sp.rowScale || 1;
      for (let k = 0; k < rows; k++) {
        const L = (k + 0.5) * s * rs + (sp.rowOffset || 0);
        let found = false;
        for (const p of b.px) {
          const dv = dist[p];
          if (Math.abs(dv - L) > 0.6 * res + 0.15) continue;
          found = true;
          const x = x0 + ((p % W) + 0.5) * res, y = y0 + (((p / W) | 0) + 0.5) * res;
          if (near(x, y, 0.75 * s, r)) continue;
          trace(x, y, L, r, s, k);
        }
        if (!found) break;
      }
    }
    function project(x, y, L) {
      for (let it = 0; it < 4; it++) {
        const g = grad(x, y); const gl = Math.hypot(g[0], g[1]);
        if (gl < 1e-3) break;
        const e = L - D(x, y);
        x += g[0] / gl * e; y += g[1] / gl * e;
        if (Math.abs(e) < 0.05) break;
      }
      return [x, y];
    }
    function trace(x, y, L, r, s, row) {
      let p = project(x, y, L);
      if (R(p[0], p[1]) !== r || Math.abs(D(p[0], p[1]) - L) > 0.3 * s || near(p[0], p[1], 0.72 * s, r)) return;
      const g0 = grad(p[0], p[1]);
      addSeed(p[0], p[1], r, s, Math.atan2(g0[0], -g0[1]), row);
      for (const dir of [1, -1]) {
        let q = p, pt = null;
        for (let steps = 0; steps < 4000; steps++) {
          const g = grad(q[0], q[1]); const gl = Math.hypot(g[0], g[1]);
          if (gl < 1e-3) break;
          let tx = -g[1] / gl * dir, ty = g[0] / gl * dir;
          if (pt && tx * pt[0] + ty * pt[1] < 0.35) break;
          const step = s * (0.9 + 0.2 * rng());
          let nq = project(q[0] + tx * step, q[1] + ty * step, L);
          if (R(nq[0], nq[1]) !== r) break;
          if (Math.abs(D(nq[0], nq[1]) - L) > 0.3 * s) break;
          if (near(nq[0], nq[1], 0.72 * s, r)) break;
          const ddx = nq[0] - q[0], ddy = nq[1] - q[1], dl = Math.hypot(ddx, ddy);
          if (dl < 0.4 * s) break;
          pt = [ddx / dl, ddy / dl];
          addSeed(nq[0], nq[1], r, s, Math.atan2(pt[1], pt[0]), row);
          q = nq;
        }
      }
    }

    // ---- interior fills ----
    for (const r of order) {
      const sp = spec[r], b = buckets.get(r); if (!b || !sp.fill) continue;
      const s = sp.size;
      const minD = sp.rows === undefined ? 0 : sp.rows * s * (sp.rowScale || 1) - 0.25 * s;
      const f = sp.fill;
      if (f.type === 'courses') {
        const ang = f.angle || 0, ca = Math.cos(ang), sa = Math.sin(ang);
        const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
        const ext = Math.hypot(b.x1 - b.x0, b.y1 - b.y0) / 2 + s;
        const nr = Math.ceil(ext / s);
        for (let j = -nr; j <= nr; j++) {
          const off = (j & 1) ? 0.5 * s : 0;
          const ph = rng() * 6.283;
          let u = -ext + off + rng() * 0.3 * s;
          while (u < ext) {
            const vv = j * s + (f.waveAmp || 0) * Math.sin(u * (f.waveFreq || 0) + ph) + (rng() - 0.5) * 0.12 * s;
            const x = cx + u * ca - vv * sa, y = cy + u * sa + vv * ca;
            if (R(x, y) === r && D(x, y) >= minD && !near(x, y, 0.72 * s, r)) addSeed(x, y, r, s, ang, -1);
            u += s * (0.88 + 0.24 * rng());
          }
        }
      } else if (f.type === 'rings') {
        // concentric courses radiating from a point (sun / moon halo)
        for (let rr = f.r0; rr < f.r1; rr += s * (0.96 + 0.08 * rng())) {
          const n = Math.max(6, Math.round(2 * Math.PI * rr / s));
          const off = rng() * 6.283;
          for (let i = 0; i < n; i++) {
            const a = off + (i + (rng() - 0.5) * 0.2) * 2 * Math.PI / n;
            const x = f.cx + Math.cos(a) * rr, y = f.cy + Math.sin(a) * rr;
            if (R(x, y) === r && D(x, y) >= minD && !near(x, y, 0.72 * s, r)) addSeed(x, y, r, s, a + Math.PI / 2, -1);
          }
        }
      } else if (f.type === 'polar') {
        const { cx, cy, a0, a1, rays } = f;
        for (let i = 0; i < rays; i++) {
          const a = a0 + (i + 0.5) / rays * (a1 - a0) + (rng() - 0.5) * 0.25 * (a1 - a0) / rays;
          let rr = (f.r0 || 0) + s * (0.5 + rng() * 0.6);
          while (rr < (f.r1 || 400)) {
            const x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
            if (R(x, y) === r && D(x, y) >= minD && !near(x, y, 0.62 * s, r)) addSeed(x, y, r, s, a, -2);
            rr += s * (0.95 + 0.25 * rng()) * (f.grow ? 1 + rr * f.grow : 1);
          }
        }
      }
    }

    // ---- weighted Voronoi cells ----
    const tiles = [];
    const n = S.x.length;
    for (let i = 0; i < n; i++) {
      const r = S.r[i], sp = spec[r];
      if (sp.ghost) continue;
      const ax = S.x[i], ay = S.y[i], sa = S.s[i];
      const capR = sa * (sp.cap || 1.12);
      let poly = [];
      const a0 = S.a[i] + Math.PI / 8;
      for (let k = 0; k < 8; k++) {
        const a = a0 + k * Math.PI / 4;
        poly.push(ax + Math.cos(a) * capR * 1.08, ay + Math.sin(a) * capR * 1.08);
      }
      const cx = Math.floor(ax / cell), cy = Math.floor(ay / cell);
      for (let dy = -2; dy <= 2 && poly.length >= 6; dy++) for (let dx = -2; dx <= 2; dx++) {
        const bk = hash.get(hkey(cx + dx, cy + dy)); if (!bk) continue;
        for (const j of bk) {
          if (j === i) continue;
          const bx = S.x[j], by = S.y[j], sb = S.s[j];
          const ex = bx - ax, ey = by - ay;
          const d2 = ex * ex + ey * ey;
          const lim = (sa + sb) * 1.25;
          if (d2 > lim * lim || d2 < 1e-6) continue;
          const t = sa / (sa + sb);
          const mx = ax + ex * t, my = ay + ey * t;
          poly = clip(poly, ex, ey, ex * mx + ey * my);
          if (poly.length < 6) break;
        }
      }
      if (poly.length < 6) continue;
      poly = dedupe(poly, 0.25);
      if (poly.length < 6) continue;
      const gap = sp.gap !== undefined ? sp.gap : opt.gap;
      let ins = inset(poly, gap / 2);
      if (!ins) continue;
      ins = dedupe(ins, 0.2);
      if (ins.length < 6) continue;
      const ar = Math.abs(area(ins));
      if (ar < sa * sa * (sp.minArea || 0.1)) continue;
      let fin = chamfer(ins, Math.min(sa * 0.07, sp.chamfer !== undefined ? sp.chamfer : 0.75));
      const jit = sp.jitter !== undefined ? sp.jitter : 0.16;
      for (let k = 0; k < fin.length; k++) fin[k] += (rng() - 0.5) * 2 * jit;
      const c = centroid(fin);
      tiles.push({ region: r, sx: ax, sy: ay, cx: c[0], cy: c[1], poly: fin, size: sa, ang: S.a[i], row: S.row[i], area: ar });
    }
    return { tiles, R, D, W, H };
  }

  return { build, clip, area, centroid, inset, chamfer };
})();
