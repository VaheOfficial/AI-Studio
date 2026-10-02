// The loading screen: the logo as something with sharp edges. Drawn on one canvas, in plain JavaScript with no
// framework, because the desktop app's splash screen (a bare HTML page) runs the same file: see
// apps/desktop/scripts/sync-splash.mjs. Types for the web app are in strike.d.ts.
//
// The mark builds itself out of its own pieces thrown in like blades, and then never sits still. In turn it
//   hunts    hovers, wings a blur, inside a turning saw ring while a reticle closes on it step by step
//   is cut   two slashes cross it; it holds still for a beat, then comes apart in four and snaps shut
//   darts    coils, is gone in a smear, and arrives with its wings swinging through; three times
//   shatters gathers itself, bursts into a ring of its own shards that hangs turning, then slams back together
// One round, from the first piece to the slam, takes about six and a half seconds.
//
// The moves are timed for weight, the way drawn animation does it: a move is announced before it happens (the
// coil before a dart, the charge before the burst), the move itself is over in a few frames, and what follows
// takes its time (overshoot, wings swinging through, a slow drift). A hard hit stops time for a moment
// (`blow`): the picture holds, shaking, behind one frame of the mark in black on a white burst.
//
// Over another page (the desktop app's splash screen lies over the web app) it has a way out, `exit`: the mark
// winds up, dashes to a spot on the page underneath and lands with a blow that tears the ground open from there.

const TAU = Math.PI * 2
const FRAME = 1000 / 60
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v)
const easeOut = (t) => 1 - (1 - t) ** 3
const easeIn = (t) => t ** 3
const easeInOut = (t) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2)
/** How far `t` is through the stretch from `a` to `b`, 0..1. */
const span = (t, a, b) => clamp01((t - a) / (b - a))

/** A small seeded generator: every run of the sequence plays the same. */
function generator(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Where things are in the logo's view box
const HINGE = { l: { x: 360, y: 190 }, r: { x: 472, y: 190 } } // the wings turn about these

const FLIGHT = 260 // a piece's time in the air while the mark builds itself
const BUILT = 860 // when the last piece has landed
// The cut: two slashes that cross, the beat before anything shows, the mark apart, and shut
const CUT = { slashes: [{ at: 160, angle: -0.52 }, { at: 300, angle: 0.52 }], part: 520, shut: 820 }
// The darts: when each goes and where to, in mark widths
const DARTS = [
  { go: 110, to: -0.62 },
  { go: 420, to: 0.62 },
  { go: 730, to: 0 },
]
const COIL = 90 // drawing back before a dart
const LEAP = 55 // the dart itself
// Shattering: the charge, the burst, the ring hanging, home, the slam
const CHARGE = 320
const HOME = 1260
const SLAM = 1380
// The way out: winding up, the dash, and the ground tearing open
const WIND = 300
const DASH = 150
const BREACH = 780
/** How far open the tear is: it bursts a little way at the blow, then runs outward faster and faster. */
const opening = (breach) => 0.1 * easeOut(Math.min(1, breach * 6)) + 0.9 * breach ** 2.4

/**
 * @param {HTMLCanvasElement} canvas  covers the area the show may use; drawn in CSS pixels
 * @param {{
 *   logo: { width: number, height: number, parts: { region: string, cx: number, cy: number, d: string }[] },
 *   size: () => number,
 *   center?: () => { x: number, y: number },
 *   onRound?: () => void,
 * }} options  `size`: the mark's width in CSS pixels; `center`: where it sits on the canvas (the middle by default).
 *   Both are read every frame, so the page can move and resize the mark. `onRound`: called each time the sequence
 *   has played through to the end (the mark whole again after shattering).
 */
export function createStrike(canvas, options) {
  const { width: VW, height: VH } = options.logo
  const ctx = canvas.getContext('2d')
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const css = getComputedStyle(canvas)
  const token = (name, fallback) => css.getPropertyValue(name).trim() || fallback
  const BRAND = token('--brand', '#fe4541')
  const ACCENT = token('--accent-rgb', '225 29 72').split(/[\s,]+/).join(',')
  const AMBER = token('--accent-2-rgb', '229 184 78').split(/[\s,]+/).join(',')

  let rand = generator(7)
  const between = (a, b) => a + (b - a) * rand()

  /* ------------------------------ the pieces ------------------------------ */

  const parts = options.logo.parts.map((p, index) => ({ ...p, index, path: new Path2D(p.d) }))
  const whole = new Path2D(options.logo.parts.map((p) => p.d).join(''))
  const of = (region) => parts.filter((p) => p.region === region)
  const plates = of('body').sort((a, b) => a.cy - b.cy)
  const wings = { l: of('wing-l'), r: of('wing-r') }
  const core = parts.filter((p) => !p.region.startsWith('wing')) // everything but the wings
  plates.forEach((p, rank) => {
    p.rank = rank
    // Plates come in from alternate sides, like blades crossing
    p.from = { x: (rank % 2 ? 1 : -1) * VW * 1.5, y: between(-0.15, 0.15) * VH, spin: between(-1.2, 1.2) }
    p.land = 240 + rank * 20
  })
  for (const p of of('head')) {
    p.from = { x: 0, y: -VH * 1.6, spin: 0 }
    p.land = 300
  }
  for (const p of of('antenna')) {
    const dir = p.cx < VW / 2 ? -1 : 1
    p.from = { x: dir * VW * 0.5, y: -VH * 1.5, spin: dir * 2 }
    p.land = 420
  }
  for (const side of ['l', 'r']) {
    const dir = side === 'l' ? -1 : 1
    wings[side]
      .sort((a, b) => Math.abs(a.cx - VW / 2) - Math.abs(b.cx - VW / 2))
      .forEach((p, rank) => {
        p.from = { x: dir * VW * 1.3, y: -VH * (0.9 - rank * 0.25), spin: dir * -2.2 }
        p.land = 640 + rank * 40
      })
  }
  // Each piece's place on the ring it flies out to when the mark shatters: in the order they lie around the center
  parts
    .slice()
    .sort((a, b) => Math.atan2(a.cy - VH / 2, a.cx - VW / 2) - Math.atan2(b.cy - VH / 2, b.cx - VW / 2))
    .forEach((p, i) => {
      p.ringAngle = (i / parts.length) * TAU - Math.PI
      p.ringReach = i % 2 ? 1 : 0.8
      p.twirl = between(2, 5) * (i % 2 ? 1 : -1)
    })

  /* ------------------------------ state ------------------------------ */

  let w = 0
  let h = 0
  let size = 0 // the mark's width in px
  let k = 1 // view box units to px
  let u = 1 // every length in the effects scales with the mark (1 at 300px wide)
  let C = { x: 0, y: 0 }

  let time = 0
  let scene = 0
  let sceneStart = 0
  let local = 0 // time inside the scene
  const fired = new Set()
  let resting = false
  let leaving = null // what to call when the show next reaches a moment the mark is whole (see finish)
  let held = null // the show is over: the pose it ended in and when, to ease out of
  let exit = null // the way out is being played (see exit)
  let fade = 1 // the dust and the glow leave with the show

  // Per piece: where it is relative to home, and how white-hot it is
  const st = parts.map(() => ({ dx: 0, dy: 0, rot: 0, alpha: 1 }))
  const hot = new Float32Array(parts.length)
  // The mark as a whole
  const pose = { x: 0, y: 0, rot: 0, sx: 1, sy: 1, lift: 0, blur: 0, apart: false }
  let flash = 0
  let shake = 0
  let saw = 0 // the saw ring's presence, 0..1
  let lock = -1 // the reticle closing in, 0..1 (-1: not shown)
  let lockFlash = 0
  let web = 0 // lines between the shards of the shattered mark
  let cut = null // { angle, sep }: the mark split along a slash
  let lastGhost = 0
  let stop = 0 // time is stopped for this long yet (a hit)
  let star = null // { x, y, r, turn, age }: the white burst behind the mark at a hit
  let punch = 0 // the picture jumps toward the viewer at a hit, and eases back
  const glints = []
  const sparks = []
  const bursts = []
  const needles = []
  const slashes = []
  const ghosts = []
  const streaks = []
  const dust = []

  /** A point of the view box on the canvas, with the mark's pose applied. */
  function toScreen(vx, vy) {
    const lx = (vx - VW / 2) * k * pose.sx
    const ly = (vy - VH / 2) * k * pose.sy
    const c = Math.cos(pose.rot)
    const s = Math.sin(pose.rot)
    return { x: C.x + pose.x + lx * c - ly * s, y: C.y + pose.y + lx * s + ly * c }
  }

  /** True once, when the scene's clock passes `ms`. */
  const at = (ms, key = ms) => {
    if (local < ms || fired.has(key)) return false
    fired.add(key)
    return true
  }

  /* ------------------------------ effects ------------------------------ */

  const jolt = (amount) => {
    shake = Math.max(shake, amount * u)
  }

  function spray(x, y, count, { angle = 0, spread = TAU, speed = 7, life = 420 } = {}) {
    for (let i = 0; i < count; i++) {
      const a = angle + (rand() - 0.5) * spread
      const v = speed * between(0.35, 1.25) * u
      sparks.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, age: 0, life: life * between(0.5, 1.3), heat: rand() })
    }
  }

  /** A shock front with corners: a star outline that races outward. */
  const burst = (x, y, reach, life = 440) => bursts.push({ x, y, reach: reach * u, age: 0, life, rot: rand() * TAU })

  function spikes(x, y, count, reach) {
    for (let i = 0; i < count; i++) needles.push({ x, y, angle: (i / count) * TAU + between(-0.12, 0.12), reach: reach * u * between(0.6, 1.2), age: 0, life: between(260, 420) })
  }

  /** Everything a hard hit sets off. */
  function impact(x, y, power = 1) {
    burst(x, y, 150 * power)
    burst(x, y, 90 * power, 320)
    spikes(x, y, 16, 170 * power)
    spray(x, y, Math.round(42 * power), { speed: 11 * power })
    flash = Math.max(flash, 0.5 * power)
    jolt(11 * power)
    // The dust is blown outward
    for (const d of dust) {
      const dx = d.x - x
      const dy = d.y - y
      const dist = Math.hypot(dx, dy) || 1
      const push = (260 * power * u) / (dist + 60 * u)
      d.vx += (dx / dist) * push
      d.vy += (dy / dist) * push
    }
  }

  /**
   * A hit with weight: everything `impact` sets off, and time stops for `hold` ms while the picture shakes. For
   * the first frames the mark is black on a white burst.
   */
  function blow(x, y, power, hold) {
    impact(x, y, power)
    stop = hold
    star = { x, y, r: size * 0.8 * power, turn: rand() * TAU, age: 0 }
    punch = 1
  }

  function seedDust() {
    dust.length = 0
    const count = Math.round(clamp01((w * h) / 900000) * 46) + 14
    for (let i = 0; i < count; i++) {
      dust.push({ x: rand() * w, y: rand() * h, vx: 0, vy: 0, turn: rand() * TAU, spin: between(-0.02, 0.02), r: between(2, 6.5), a: between(0.08, 0.3) })
    }
  }

  /* ------------------------------ the scenes ------------------------------ */

  /** Hovering in place; `buzz` beats the wings so fast they blur. */
  function hover(buzz = 1, sway = 1) {
    pose.y += Math.sin(time / 300) * 5 * u * sway
    pose.rot += Math.sin(time / 520) * 0.035 * sway
    pose.lift += Math.sin(time / 14) * 0.12 * buzz
    pose.blur = buzz
    // A pulse runs down the body, starting from fully lit
    const lit = Math.min(1, local / 300)
    for (const p of plates) st[p.index].alpha = 1 - 0.55 * lit * Math.max(0, Math.sin(time / 190 - p.rank * 0.45))
  }

  function build() {
    for (const p of parts) {
      const s = st[p.index]
      const q = span(local, p.land - FLIGHT, p.land)
      if (q <= 0) {
        s.alpha = 0
        continue
      }
      const away = 1 - easeIn(q)
      s.dx = p.from.x * away
      s.dy = p.from.y * away
      s.rot = p.from.spin * away
      s.alpha = Math.min(1, q * 5)
      if (q < 1) {
        // A streak behind it, longer the faster it goes
        const head = toScreen(p.cx + s.dx, p.cy + s.dy)
        const tail = toScreen(p.cx + p.from.x * Math.min(1, away + 0.1 + q * 0.3), p.cy + p.from.y * Math.min(1, away + 0.1 + q * 0.3))
        streaks.push({ x1: head.x, y1: head.y, x2: tail.x, y2: tail.y, a: 0.75 * q })
      } else if (at(p.land, `landed-${p.index}`)) {
        const spot = toScreen(p.cx, p.cy)
        hot[p.index] = 1
        spray(spot.x, spot.y, 5, { speed: 6, life: 300 })
        jolt(2.2)
      }
    }
    if (at(BUILT)) {
      blow(C.x, C.y, 1.1, 90)
      hot.fill(1)
    }
    if (local >= BUILT) {
      const pop = 1 + 0.1 * (1 - easeOut(span(local, BUILT, BUILT + 330)))
      pose.sx = pose.sy = pop
      hover(span(local, BUILT + 120, BUILT + 330))
    }
  }

  function hunt() {
    hover()
    saw = span(local, 40, 300) * (1 - span(local, 680, 850))
    // The reticle closes in three steps, not a glide: each one a small tick, the last one the lock
    const steps = [120, 260, 400]
    let closed = 0
    for (const [i, when] of steps.entries()) {
      closed += easeOut(span(local, when, when + 70)) / steps.length
      if (at(when, `tick-${i}`)) jolt(i === steps.length - 1 ? 3.5 : 1.6)
    }
    lock = closed * (1 - span(local, 720, 850))
    if (at(400)) lockFlash = 1
  }

  /** A glint where a blade is about to come from. */
  const glint = (angle) => glints.push({ x: C.x - Math.cos(angle) * size * 0.78, y: C.y - Math.sin(angle) * size * 0.78, age: 0 })

  function slashed() {
    // It goes still: the blades cross it, and for a beat nothing seems to have happened
    const stir = local < CUT.shut ? 1 - easeOut(span(local, 0, 140)) : span(local, CUT.shut + 100, 1050)
    hover(stir, stir)
    for (const [i, slash] of CUT.slashes.entries()) {
      if (at(slash.at - 120, `glint-${i}`)) glint(slash.angle)
      if (at(slash.at, `slash-${i}`)) slashes.push({ angle: slash.angle, age: 0, offset: 0 })
      if (at(slash.at + 30, `pass-${i}`)) jolt(3)
    }
    if (local >= CUT.part && local < CUT.shut + 45) {
      // Apart heavily, drifting on while it hangs there; shut in an instant
      const open = local < CUT.shut ? easeOut(span(local, CUT.part, CUT.part + 240)) * (1 + 0.3 * span(local, CUT.part + 240, CUT.shut)) : 1.3 * (1 - span(local, CUT.shut, CUT.shut + 45))
      cut = { angles: CUT.slashes.map((s) => s.angle), sep: open * 11 * u }
    }
    if (at(CUT.part)) {
      jolt(6)
      flash = Math.max(flash, 0.22)
      for (const p of core) hot[p.index] = 0.8
      for (const slash of CUT.slashes) {
        for (let n = 0; n < 12; n++) {
          const along = between(-0.5, 0.5) * size
          spray(C.x + Math.cos(slash.angle) * along, C.y + Math.sin(slash.angle) * along, 1, { angle: slash.angle + (rand() < 0.5 ? 1 : -1) * Math.PI / 2, spread: 0.9, speed: 9 })
        }
      }
    }
    if (at(CUT.shut + 45)) {
      blow(C.x, C.y, 0.7, 70)
      hot.fill(0.9)
    }
  }

  function dart() {
    let x = 0 // in mark widths
    let from = 0
    let rested = 0 // seconds since it last arrived
    for (const [i, move] of DARTS.entries()) {
      if (local < move.go - COIL) break
      const dir = Math.sign(move.to - from)
      if (local < move.go) {
        // It coils the other way first
        const q = easeOut(span(local, move.go - COIL, move.go))
        x = from - dir * 0.05 * q
        Object.assign(pose, { rot: -dir * 0.09 * q, sx: 1 - 0.07 * q, sy: 1 + 0.05 * q, lift: -0.18 * q })
        rested = 0
      } else if (local < move.go + LEAP) {
        // Gone: a few frames, drawn as a smear
        const q = span(local, move.go, move.go + LEAP)
        x = from - dir * 0.05 + (move.to - from + dir * 0.05) * q
        Object.assign(pose, { rot: dir * 0.2, sx: 1 + 0.6 * Math.sin(q * Math.PI), sy: 0.88, lift: -0.34 })
        rested = 0
        if (time - lastGhost >= 9) {
          lastGhost = time
          ghosts.push({ x: C.x + x * size, y: C.y, k, rot: pose.rot, age: 0 })
        }
        if (at(move.go, `go-${i}`)) {
          // Speed lines against the direction of travel
          for (let n = 0; n < 14; n++) sparks.push({ x: C.x + between(-0.7, 0.7) * size, y: C.y + between(-0.32, 0.32) * size, vx: -dir * between(16, 30) * u, vy: 0, age: 0, life: between(160, 300), heat: 0.2, flat: true })
        }
      } else {
        // Arrived: it overshoots a touch and its wings swing through before everything comes to rest
        rested = (local - move.go - LEAP) / 1000
        const ring = Math.exp(-rested * 9)
        x = move.to + dir * 0.045 * ring * Math.cos(rested * 38)
        Object.assign(pose, { rot: dir * 0.2 * Math.exp(-rested * 14), sx: 1, sy: 1, lift: 0.4 * ring * Math.cos(rested * 30) })
        if (at(move.go + LEAP, `stop-${i}`)) {
          const spot = { x: C.x + move.to * size, y: C.y }
          burst(spot.x, spot.y, 80, 300)
          spray(spot.x, spot.y, 14, { angle: dir > 0 ? Math.PI : 0, spread: 1.1, speed: 12 })
          jolt(5)
          // The last one lands home, and lands hard
          if (i === DARTS.length - 1) stop = 50
        }
      }
      from = move.to
    }
    pose.x = x * size
    if (rested > 0) hover(Math.min(0.7, rested * 5), Math.min(1, rested * 4))
  }

  function shatter() {
    if (local < CHARGE) {
      // It gathers itself: drawn in, shaking harder, lighting up plate by plate, sparks pulled toward it
      const tense = local / CHARGE
      pose.x = (rand() - 0.5) * 6 * u * tense * tense
      pose.sx = pose.sy = 1 - 0.09 * easeOut(tense)
      pose.lift = 0.22 * tense
      for (const p of plates) if (tense > (p.rank + 1) / (plates.length + 2)) hot[p.index] = Math.max(hot[p.index], 0.9)
      if (time - lastGhost >= 16) {
        lastGhost = time
        const a = rand() * TAU
        const r = size * between(0.5, 0.95)
        const v = r / (200 / FRAME)
        sparks.push({ x: C.x + Math.cos(a) * r, y: C.y + Math.sin(a) * r, vx: -Math.cos(a) * v, vy: -Math.sin(a) * v, age: 0, life: 200, heat: 1, flat: true })
      }
      return
    }
    if (at(CHARGE)) blow(C.x, C.y, 1.2, 100)
    // Out in an instant; then the ring hangs, barely turning, and swells before it comes home
    const out = easeOut(span(local, CHARGE, CHARGE + 180))
    const home = easeIn(span(local, HOME, SLAM))
    const away = out * (1 - home)
    const wheel = 0.9 * easeOut(span(local, CHARGE, CHARGE + 400)) + 0.35 * span(local, CHARGE + 400, HOME)
    const radius = 0.62 * VW * (1 + 0.09 * easeInOut(span(local, HOME - 140, HOME)))
    pose.apart = away > 0
    for (const p of parts) {
      const s = st[p.index]
      const a = p.ringAngle + wheel
      s.dx = (VW / 2 + Math.cos(a) * radius * p.ringReach - p.cx) * away
      s.dy = (VH / 2 + Math.sin(a) * radius * p.ringReach * 0.78 - p.cy) * away
      s.rot = p.twirl * (0.25 * easeOut(span(local, CHARGE, CHARGE + 300)) + (0.12 * (local - CHARGE)) / 1000) * away
    }
    web = away > 0.6 ? (away - 0.6) / 0.4 : 0
    if (at(SLAM)) {
      blow(C.x, C.y, 1.35, 120)
      hot.fill(1)
    }
    if (local >= SLAM) {
      pose.sx = pose.sy = 1 + 0.12 * (1 - easeOut(span(local, SLAM, SLAM + 270)))
      const stir = span(local, SLAM + 120, 1750)
      hover(stir, stir)
    }
  }

  /** The way out, one step: wind up, dash, land; then the ground tears open from where it landed. */
  function depart(dt) {
    const { from, to, dir } = exit
    const since = time - exit.start
    const back = 0.16 * from.size // how far it draws back before it goes
    if (since < WIND) {
      const q = easeOut(since / WIND)
      exit.x = from.x - dir.x * back * q
      exit.y = from.y - dir.y * back * q
      pose.sx = pose.sy = 1 + 0.08 * q
      pose.lift = 0.5 * q
      pose.x = (rand() - 0.5) * 5 * u * q
      saw = q
      for (let i = 0; i < hot.length; i++) hot[i] = Math.max(hot[i], 0.75 * q)
      // It gathers itself: sparks are drawn in from all around
      if (time - lastGhost >= 12) {
        lastGhost = time
        for (let n = 0; n < 2; n++) {
          const a = rand() * TAU
          const r = from.size * between(0.55, 1.05)
          const v = r / (220 / FRAME)
          sparks.push({ x: exit.x + Math.cos(a) * r, y: exit.y + Math.sin(a) * r, vx: -Math.cos(a) * v, vy: -Math.sin(a) * v, age: 0, life: 220, heat: 1, flat: true })
        }
      }
    } else if (since < WIND + DASH) {
      const q = easeIn((since - WIND) / DASH)
      const sx = from.x - dir.x * back
      const sy = from.y - dir.y * back
      exit.x = sx + (to.x - sx) * q
      exit.y = sy + (to.y - sy) * q
      exit.size = from.size + (to.size - from.size) * q
      pose.rot = dir.x * 0.2
      pose.lift = -0.32
      pose.sx = 1.08
      for (let i = 0; i < hot.length; i++) hot[i] = Math.max(hot[i], 0.75)
      if (time - lastGhost >= 9) {
        lastGhost = time
        ghosts.push({ x: exit.x, y: exit.y, k: exit.size / VW, rot: pose.rot, age: 0 })
      }
    } else {
      const landed = since - WIND - DASH
      exit.x = to.x
      exit.y = to.y
      exit.size = to.size
      if (!exit.landed) {
        exit.landed = true
        impact(to.x, to.y, 1.7)
        spray(to.x, to.y, 30, { speed: 20, life: 620 })
        hot.fill(1)
        exit.onLand?.()
      }
      exit.breach = span(landed, 0, BREACH)
      pose.sx = pose.sy = 1 + 0.16 * (1 - easeOut(span(landed, 0, 380)))
      fade = Math.max(0, fade - dt / 380)
      if (exit.breach >= 1 && !exit.over) {
        exit.over = true
        exit.onDone?.()
      }
    }
    place()
  }

  /** The torn edge of the opening in the ground: a ragged star about where the mark landed. */
  function tear(radius) {
    const teeth = exit.teeth
    ctx.beginPath()
    for (let i = 0; i <= teeth.length; i++) {
      const a = exit.turn + (i / teeth.length) * TAU + exit.breach * 0.35
      const reach = radius * teeth[i % teeth.length]
      ctx.lineTo(exit.to.x + Math.cos(a) * reach, exit.to.y + Math.sin(a) * reach)
    }
    ctx.closePath()
  }

  // It builds itself once, then keeps going round the rest. Every scene ends with the mark whole and in place.
  const SCENES = [
    { run: build, length: 1300 },
    { run: hunt, length: 850 },
    { run: slashed, length: 1050 },
    { run: dart, length: 1000 },
    { run: shatter, length: 1750 },
  ]

  /* ------------------------------ one step of time ------------------------------ */

  function step(dt) {
    const f = dt / FRAME
    time += dt
    local = time - sceneStart
    while (local >= SCENES[scene].length) {
      sceneStart += SCENES[scene].length
      if (scene === SCENES.length - 1) {
        scene = 1
        options.onRound?.()
      } else {
        scene += 1
      }
      fired.clear()
      local = time - sceneStart
      if (leaving && !held) {
        held = { ...pose, at: time }
        const done = leaving
        leaving = null
        done()
      }
    }

    const was = held
    Object.assign(pose, { x: 0, y: 0, rot: 0, sx: 1, sy: 1, lift: 0, blur: 0, apart: false })
    for (const s of st) Object.assign(s, { dx: 0, dy: 0, rot: 0, alpha: 1 })
    streaks.length = 0
    saw = 0
    lock = -1
    web = 0
    cut = null
    if (exit) {
      depart(dt)
    } else if (was) {
      // Out of the pose it stopped in, to the mark at rest; the dust and the glow go
      const left = 1 - easeOut(span(time, was.at, was.at + 260))
      Object.assign(pose, { x: was.x * left, y: was.y * left, rot: was.rot * left, sx: 1 + (was.sx - 1) * left, sy: 1 + (was.sy - 1) * left, lift: was.lift * left, blur: was.blur * left })
      fade = Math.max(0, fade - dt / 450)
    } else if (!resting) {
      SCENES[scene].run()
    }

    for (let i = 0; i < hot.length; i++) hot[i] = Math.max(0, hot[i] - dt / 260)
    flash = Math.max(0, flash - dt / 380)
    punch = Math.max(0, punch - dt / 260)
    lockFlash = Math.max(0, lockFlash - dt / 420)
    shake *= 0.86 ** f

    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i]
      s.age += dt
      if (s.age >= s.life) {
        sparks.splice(i, 1)
        continue
      }
      s.x += s.vx * f
      s.y += s.vy * f
      if (!s.flat) {
        s.vx *= 0.955 ** f
        s.vy = s.vy * 0.955 ** f + 0.22 * u * f
      }
    }
    const age = (list, life) => {
      for (let i = list.length - 1; i >= 0; i--) {
        list[i].age += dt
        if (list[i].age >= (life ?? list[i].life)) list.splice(i, 1)
      }
    }
    age(bursts)
    age(needles)
    age(slashes, 560)
    age(ghosts, 300)
    age(glints, 220)
    for (const d of dust) {
      d.x += (d.vx - 0.12) * f
      d.y += (d.vy - 0.3) * f
      d.vx *= 0.94 ** f
      d.vy *= 0.94 ** f
      d.turn += d.spin * f
      if (d.y < -12) d.y = h + 12
      else if (d.y > h + 12) d.y = -12
      if (d.x < -12) d.x = w + 12
      else if (d.x > w + 12) d.x = -12
    }
  }

  /* ------------------------------ drawing ------------------------------ */

  /** The first frames of a hit: the mark in black on the white burst. */
  const silhouette = () => star !== null && star.age < 50

  function piece(p, alpha) {
    const s = st[p.index]
    if (s.alpha <= 0) return
    ctx.save()
    ctx.translate(p.cx + s.dx, p.cy + s.dy)
    if (s.rot) ctx.rotate(s.rot)
    ctx.translate(-p.cx, -p.cy)
    ctx.globalAlpha = alpha * s.alpha
    ctx.fillStyle = silhouette() ? '#080808' : BRAND
    ctx.fill(p.path, 'evenodd')
    if (hot[p.index] > 0.02 && !silhouette()) {
      ctx.globalAlpha = alpha * s.alpha * hot[p.index]
      ctx.fillStyle = '#fff'
      ctx.fill(p.path, 'evenodd')
    }
    ctx.restore()
  }

  function wing(side, lift, alpha) {
    const hinge = HINGE[side]
    ctx.save()
    // Shattered, the wing's pieces are on their own; otherwise the wing turns as one about its hinge
    if (!pose.apart && lift) {
      ctx.translate(hinge.x, hinge.y)
      ctx.rotate(side === 'l' ? lift : -lift)
      ctx.scale(1, 1 - Math.abs(lift) * 0.35)
      ctx.translate(-hinge.x, -hinge.y)
    }
    for (const p of wings[side]) piece(p, alpha)
    ctx.restore()
  }

  /** The mark in its current pose. */
  function mark(alpha) {
    ctx.save()
    ctx.translate(C.x + pose.x, C.y + pose.y)
    ctx.rotate(pose.rot)
    ctx.scale(k * pose.sx, k * pose.sy)
    ctx.translate(-VW / 2, -VH / 2)
    for (const side of ['l', 'r']) {
      if (pose.blur > 0.05 && !pose.apart) {
        // The wings beat too fast to follow: two fainter copies either side of where they are
        wing(side, pose.lift + 0.1, alpha * 0.2 * pose.blur)
        wing(side, pose.lift - 0.1, alpha * 0.2 * pose.blur)
      }
      wing(side, pose.lift, alpha)
    }
    for (const p of core) piece(p, alpha)
    ctx.restore()
  }

  /** The mark cut along one or two lines through its center: each piece pushed away from the lines it lies beside. */
  function markCut(alpha) {
    const far = Math.hypot(w, h)
    const lines = cut.angles.map((angle) => ({ dx: Math.cos(angle), dy: Math.sin(angle) }))
    const sides = lines.length > 1 ? [[1, 1], [1, -1], [-1, 1], [-1, -1]] : [[1], [-1]]
    const cx = C.x + pose.x
    const cy = C.y + pose.y
    for (const side of sides) {
      ctx.save()
      let ox = 0
      let oy = 0
      for (const [i, line] of lines.entries()) {
        ox += -line.dy * side[i] * cut.sep
        oy += line.dx * side[i] * cut.sep
      }
      ctx.translate(ox, oy)
      for (const [i, { dx, dy }] of lines.entries()) {
        // Only the side of this line the piece is on
        ctx.beginPath()
        ctx.moveTo(cx - dx * far, cy - dy * far)
        ctx.lineTo(cx + dx * far, cy + dy * far)
        ctx.lineTo(cx + dx * far - dy * far * side[i], cy + dy * far + dx * far * side[i])
        ctx.lineTo(cx - dx * far - dy * far * side[i], cy - dy * far + dx * far * side[i])
        ctx.clip()
      }
      mark(alpha)
      ctx.restore()
    }
  }

  function drawSaw() {
    const R = 0.6 * size
    const turn = time * 0.0021
    ctx.fillStyle = `rgba(${ACCENT},${0.9 * saw})`
    ctx.beginPath()
    const teeth = 48
    for (let i = 0; i < teeth; i++) {
      const a = turn + (i / teeth) * TAU
      const reach = R + (i % 4 ? 8 : 17) * u * saw
      ctx.moveTo(C.x + Math.cos(a - 0.03) * R, C.y + Math.sin(a - 0.03) * R)
      // The tip leans the way the ring turns: a saw, not a sun
      ctx.lineTo(C.x + Math.cos(a + 0.075) * reach, C.y + Math.sin(a + 0.075) * reach)
      ctx.lineTo(C.x + Math.cos(a + 0.03) * R, C.y + Math.sin(a + 0.03) * R)
    }
    ctx.fill()
    // An inner ring in pieces, turning the other way
    ctx.strokeStyle = `rgba(${AMBER},${0.4 * saw})`
    ctx.lineWidth = Math.max(1, 1.4 * u)
    for (let i = 0; i < 6; i++) {
      const a = -turn * 1.7 + (i / 6) * TAU
      ctx.beginPath()
      ctx.arc(C.x, C.y, R - 9 * u, a, a + 0.62)
      ctx.stroke()
    }
  }

  function drawReticle() {
    const open = 1 + (1 - lock) * 0.9
    const hx = 0.56 * size * open
    const hy = 0.36 * size * open
    const arm = 20 * u
    const jitter = (1 - lock) * 7 * u
    ctx.lineWidth = Math.max(1, 1.6 * u)
    ctx.strokeStyle = lockFlash > 0.02 ? `rgba(255,255,255,${0.5 + 0.5 * lockFlash})` : `rgba(${AMBER},${0.75 * Math.min(1, lock * 2)})`
    ctx.beginPath()
    for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      const x = C.x + pose.x + sx * hx + (rand() - 0.5) * jitter
      const y = C.y + sy * hy + (rand() - 0.5) * jitter
      ctx.moveTo(x - sx * arm, y)
      ctx.lineTo(x, y)
      ctx.lineTo(x, y - sy * arm)
    }
    if (lock > 0.98) {
      // Locked: tick marks on the axes
      for (const [ax, ay] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        ctx.moveTo(C.x + ax * (hx + 8 * u), C.y + ay * (hy + 8 * u))
        ctx.lineTo(C.x + ax * (hx + 22 * u), C.y + ay * (hy + 22 * u))
      }
    }
    ctx.stroke()
  }

  function drawSlashes() {
    const far = Math.hypot(w, h) * 0.6
    for (const s of slashes) {
      const dx = Math.cos(s.angle)
      const dy = Math.sin(s.angle)
      const ox = C.x - dy * s.offset
      const oy = C.y + dx * s.offset
      const head = easeOut(span(s.age, 0, 70)) * 2 - 1 // -1..1 along the line
      const tail = Math.max(-1, head - 0.75 * (1 - span(s.age, 55, 170)))
      const fade = 1 - span(s.age, 70, 560)
      // What it leaves behind: a hairline that fades
      ctx.strokeStyle = `rgba(${ACCENT},${0.7 * fade})`
      ctx.lineWidth = Math.max(1, 1.4 * u)
      ctx.beginPath()
      ctx.moveTo(ox - dx * far, oy - dy * far)
      ctx.lineTo(ox + dx * far * head, oy + dy * far * head)
      ctx.stroke()
      if (tail >= head) continue
      // The blade: widest behind its tip, a point at both ends
      const belly = tail + (head - tail) * 0.72
      for (const [width, color] of [[11 * u, `rgba(${ACCENT},0.5)`], [3.6 * u, '#fff']]) {
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.moveTo(ox + dx * far * tail, oy + dy * far * tail)
        ctx.lineTo(ox + dx * far * belly - dy * width, oy + dy * far * belly + dx * width)
        ctx.lineTo(ox + dx * far * head, oy + dy * far * head)
        ctx.lineTo(ox + dx * far * belly + dy * width, oy + dy * far * belly - dx * width)
        ctx.fill()
      }
    }
  }

  function draw() {
    ctx.setTransform(dpr(), 0, 0, dpr(), 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
    if (exit) {
      // On the way out the canvas paints the ground itself, so that it can be torn open
      ctx.fillStyle = exit.ground
      ctx.fillRect(0, 0, w, h)
      if (exit.breach > 0) {
        ctx.globalCompositeOperation = 'destination-out'
        tear(exit.reach * opening(exit.breach))
        ctx.fill()
        ctx.globalCompositeOperation = 'source-over'
      }
    }
    if (shake > 0.2) ctx.translate((rand() - 0.5) * shake * 2, (rand() - 0.5) * shake * 2)
    if (punch > 0.01) {
      const zoom = 1 + 0.05 * punch * punch
      ctx.translate(C.x, C.y)
      ctx.scale(zoom, zoom)
      ctx.translate(-C.x, -C.y)
    }

    // Razor dust: slivers adrift in the dark
    ctx.fillStyle = `rgb(${ACCENT})`
    for (const d of dust) {
      ctx.globalAlpha = d.a * fade
      ctx.beginPath()
      ctx.moveTo(d.x + Math.cos(d.turn) * d.r * u * 1.8, d.y + Math.sin(d.turn) * d.r * u * 1.8)
      ctx.lineTo(d.x + Math.cos(d.turn + 2.5) * d.r * u, d.y + Math.sin(d.turn + 2.5) * d.r * u)
      ctx.lineTo(d.x + Math.cos(d.turn - 2.5) * d.r * u * 0.6, d.y + Math.sin(d.turn - 2.5) * d.r * u * 0.6)
      ctx.fill()
    }
    ctx.globalAlpha = 1

    // A glow under the mark that flares with every hit
    const lit = (resting ? 0.08 : 0.2 + flash * 0.5) * fade
    const glow = ctx.createRadialGradient(C.x, C.y, 0, C.x, C.y, size * 1.3)
    // Falling away gradually: a straight ramp to nothing reads as the edge of a disc
    for (const [stop, share] of [[0, 1], [0.25, 0.62], [0.5, 0.28], [0.75, 0.08], [1, 0]]) glow.addColorStop(stop, `rgba(${ACCENT},${lit * share})`)
    ctx.fillStyle = glow
    ctx.fillRect(C.x - size * 1.3, C.y - size * 1.3, size * 2.6, size * 2.6)

    if (saw > 0.01) drawSaw()

    if (star) {
      // The burst behind the mark at a hit: white for the first frames, then the mark's red, thinning out
      const first = star.age < 50
      const left = first ? 1 : 1 - span(star.age, 50, 150)
      ctx.fillStyle = first ? '#fff' : `rgba(${ACCENT},${0.75 * left})`
      ctx.beginPath()
      const points = 20
      for (let i = 0; i <= points; i++) {
        const a = star.turn + (i / points) * TAU
        const reach = star.r * (i % 2 ? 0.52 : 1) * (first ? 1 : 1 + 0.25 * (1 - left))
        ctx.lineTo(star.x + Math.cos(a) * reach, star.y + Math.sin(a) * reach)
      }
      ctx.fill()
    }

    // Afterimages of the dart
    for (const g of ghosts) {
      ctx.save()
      ctx.translate(g.x, g.y)
      ctx.rotate(g.rot)
      ctx.scale(g.k, g.k)
      ctx.translate(-VW / 2, -VH / 2)
      ctx.globalAlpha = 0.34 * (1 - g.age / 300)
      ctx.fillStyle = `rgb(${ACCENT})`
      ctx.fill(whole, 'evenodd')
      ctx.restore()
    }

    if (web > 0.01) {
      // The shards are wired to each other: chords across the ring, flickering
      ctx.lineWidth = Math.max(0.6, u)
      ctx.beginPath()
      for (const p of parts) {
        const q = parts[(p.index * 7 + 11) % parts.length]
        if ((p.index + Math.floor(time / 90)) % 3) continue
        const a = toScreen(p.cx + st[p.index].dx, p.cy + st[p.index].dy)
        const b = toScreen(q.cx + st[q.index].dx, q.cy + st[q.index].dy)
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
      }
      ctx.strokeStyle = `rgba(${ACCENT},${0.42 * web})`
      ctx.stroke()
    }

    const alpha = resting ? 0.32 : 1
    if (cut && cut.sep > 0.1) markCut(alpha)
    else mark(alpha)
    ctx.globalAlpha = 1

    if (lock >= 0) drawReticle()

    ctx.globalCompositeOperation = 'lighter'
    for (const s of streaks) {
      const trail = ctx.createLinearGradient(s.x1, s.y1, s.x2, s.y2)
      trail.addColorStop(0, `rgba(255,220,200,${s.a})`)
      trail.addColorStop(1, `rgba(${ACCENT},0)`)
      ctx.strokeStyle = trail
      ctx.lineWidth = Math.max(1, 2.2 * u)
      ctx.beginPath()
      ctx.moveTo(s.x1, s.y1)
      ctx.lineTo(s.x2, s.y2)
      ctx.stroke()
    }
    drawSlashes()
    for (const g of glints) {
      // A four-pointed glint: it opens and shuts in a blink
      const reach = Math.sin((g.age / 220) * Math.PI) * 30 * u
      ctx.fillStyle = '#fff'
      ctx.beginPath()
      for (let i = 0; i < 8; i++) {
        const a = 0.4 + (i / 8) * TAU
        const r = i % 2 ? reach * 0.12 : reach
        ctx.lineTo(g.x + Math.cos(a) * r, g.y + Math.sin(a) * r)
      }
      ctx.fill()
    }
    if (exit && exit.breach > 0 && exit.breach < 1) {
      // The edge of the tear burns as it runs outward
      const radius = exit.reach * opening(exit.breach)
      const left = 1 - exit.breach ** 3
      ctx.lineJoin = 'miter'
      for (const [width, color] of [[16, `rgba(${ACCENT},${0.5 * left})`], [5, `rgba(${AMBER},${0.9 * left})`], [1.6, `rgba(255,255,255,${left})`]]) {
        ctx.strokeStyle = color
        ctx.lineWidth = width
        tear(radius)
        ctx.stroke()
      }
    }
    for (const b of bursts) {
      const p = b.age / b.life
      const r = b.reach * easeOut(p)
      ctx.strokeStyle = `rgba(${p < 0.3 ? AMBER : ACCENT},${(1 - p) * 0.9})`
      ctx.lineWidth = Math.max(0.8, 3.2 * u * (1 - p))
      ctx.lineJoin = 'miter'
      ctx.beginPath()
      const corners = 22
      for (let i = 0; i <= corners; i++) {
        const a = b.rot + (i / corners) * TAU
        const reach = r * (i % 2 ? 0.8 : 1)
        ctx.lineTo(b.x + Math.cos(a) * reach, b.y + Math.sin(a) * reach)
      }
      ctx.stroke()
    }
    for (const n of needles) {
      const p = n.age / n.life
      const inner = n.reach * easeOut(p) * 0.85
      const outer = inner + n.reach * 0.3 * (1 - p)
      const dx = Math.cos(n.angle)
      const dy = Math.sin(n.angle)
      const half = 2.2 * u * (1 - p)
      ctx.fillStyle = `rgba(255,${190 - 90 * p},${150 - 110 * p},${1 - p})`
      ctx.beginPath()
      ctx.moveTo(n.x + dx * inner - dy * half, n.y + dy * inner + dx * half)
      ctx.lineTo(n.x + dx * outer, n.y + dy * outer)
      ctx.lineTo(n.x + dx * inner + dy * half, n.y + dy * inner - dx * half)
      ctx.fill()
    }
    ctx.lineCap = 'butt'
    for (const s of sparks) {
      const p = s.age / s.life
      // White-hot, then amber, then the mark's red as it dies
      ctx.strokeStyle = p < 0.25 + s.heat * 0.2 ? `rgba(255,245,235,${1 - p})` : p < 0.6 ? `rgba(${AMBER},${1 - p})` : `rgba(${ACCENT},${1 - p})`
      ctx.lineWidth = Math.max(0.8, (s.flat ? 1 : 1.7) * u * (1 - p * 0.6))
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(s.x - s.vx * (s.flat ? 3.2 : 2.1), s.y - s.vy * (s.flat ? 3.2 : 2.1))
      ctx.stroke()
    }
    if (flash > 0.01) {
      ctx.fillStyle = `rgba(${ACCENT},${flash * 0.1})`
      ctx.fillRect(-40, -40, w + 80, h + 80)
    }
    ctx.globalCompositeOperation = 'source-over'
  }

  /* ------------------------------ running ------------------------------ */

  const dpr = () => Math.min(window.devicePixelRatio || 1, 2)

  function measure() {
    const box = canvas.getBoundingClientRect()
    w = box.width
    h = box.height
    canvas.width = Math.round(w * dpr())
    canvas.height = Math.round(h * dpr())
    place()
    if (!dust.length) seedDust()
  }

  /** How big the mark is and where: asked of the page every frame, which may be moving it. */
  function place() {
    if (exit) {
      // On the way out it goes where the exit takes it; what it throws off keeps the scale it had
      size = exit.size
      C = { x: exit.x, y: exit.y }
      u = Math.max(0.3, exit.from.size / 300)
    } else {
      size = options.size()
      C = options.center ? options.center() : { x: w / 2, y: h / 2 }
      u = Math.max(0.3, size / 300)
    }
    k = size / VW
  }

  function reset() {
    rand = generator(7)
    time = 0
    lastGhost = 0
    scene = 0
    sceneStart = 0
    fired.clear()
    hot.fill(0)
    flash = 0
    shake = 0
    for (const list of [sparks, bursts, needles, slashes, ghosts, streaks]) list.length = 0
    leaving = null
    held = null
    exit = null
    stop = 0
    star = null
    punch = 0
    glints.length = 0
    fade = 1
    seedDust()
  }

  let raf = 0
  let last = 0
  const frame = (now) => {
    place()
    // In whole steps, however long the frame took (a hidden window delivers them late)
    let due = Math.min(120, last ? now - last : FRAME)
    last = now
    if (star && (star.age += due) > 150) star = null
    // A hit has stopped time: nothing moves on, the picture only shakes
    const paused = Math.min(stop, due)
    stop -= paused
    due -= paused
    for (; due > 0 && stop <= 0; due -= FRAME) step(Math.min(FRAME, due))
    draw()
    raf = requestAnimationFrame(frame)
  }

  // Sizing the canvas wipes it; when no clock is running, what was on it has to be drawn again
  const observer = new ResizeObserver(() => {
    measure()
    if (calm) still()
    else if (!raf) draw()
  })

  /** Without motion: the mark, built and at rest. */
  function still() {
    scene = 1
    local = 0
    Object.assign(pose, { x: 0, y: 0, rot: 0, sx: 1, sy: 1, lift: 0, blur: 0, apart: false })
    draw()
  }

  measure()
  observer.observe(canvas)
  if (calm) still()
  else raf = requestAnimationFrame(frame)

  return {
    /** Stops the show and dims the mark (something went wrong), or starts it again. */
    rest(on) {
      resting = on
      if (!on) {
        reset()
        scene = 1
      }
    },
    /**
     * Ends the show at the next moment the mark is whole (the end of the scene that is playing; at once when called
     * from `onRound`), and calls `done` then. From there the mark is at rest, lit, and nothing else is drawn but
     * what is still in the air: the page can move it wherever it likes with `center` and `size`.
     */
    finish(done) {
      if (calm) done()
      else leaving = done
    },
    /**
     * The way out, for a page that lies over another one. The mark draws back, dashes to `to` (a point and a
     * width on the canvas) and lands with a blow; from that point the ground is torn open in a widening ragged
     * hole, through which the page underneath shows. `ground` is the color the canvas paints behind everything
     * from now on: the page drops its own background when it calls this. `onLand` is called at the blow, `onDone`
     * when the ground is gone and only the mark is left on the canvas. Call it once the show has finished.
     */
    exit({ to, ground, onLand, onDone }) {
      if (calm) {
        onLand?.()
        onDone?.()
        return
      }
      const from = { x: C.x, y: C.y, size }
      const gap = Math.hypot(to.x - from.x, to.y - from.y)
      // Far enough that the innermost tooth of the tear clears the farthest corner
      const reach = Math.max(...[[0, 0], [w, 0], [0, h], [w, h]].map(([x, y]) => Math.hypot(x - to.x, y - to.y))) / 0.66
      exit = {
        from, to, ground, onLand, onDone, reach,
        dir: gap > 1 ? { x: (to.x - from.x) / gap, y: (to.y - from.y) / gap } : { x: 0, y: 0 },
        x: from.x, y: from.y, size: from.size,
        start: time, landed: false, over: false, breach: 0,
        turn: rand() * TAU,
        teeth: Array.from({ length: 30 }, (_, i) => (i % 2 ? between(0.68, 0.82) : between(0.9, 1))),
      }
    },
    /** Draws the moment `ms` into the sequence, with no clock running. For stills and tests. */
    seek(ms) {
      cancelAnimationFrame(raf)
      raf = 0
      reset()
      while (time < ms) {
        step(FRAME)
        // Stills are taken on the scene's own clock: the stops are skipped, the burst at a hit is kept
        stop = 0
        if (star && (star.age += FRAME) > 150) star = null
      }
      draw()
    },
    destroy() {
      cancelAnimationFrame(raf)
      observer.disconnect()
    },
  }
}
