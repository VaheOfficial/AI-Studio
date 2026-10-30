// config.js — every tunable of the short lives here:
// canvas & timing, palette, scene geometry, camera, fish build & choreography.
'use strict';

const CONFIG = {
  width: 1280,
  height: 720,
  fps: 30,
  duration: 15,
  seed: 20261013,

  // World-space area that gets tiled (screen space at zoom 1, plus margin
  // for the camera follow during the leap).
  world: { x0: -48, y0: -96, x1: 1328, y1: 776 },

  // ------------------------------------------------------------------
  // PALETTE (sRGB hex). Day = warm afternoon, night = moonlit.
  // ------------------------------------------------------------------
  palette: {
    grout:        '#1d2f7c',
    groutDeep:    '#101b4f',
    groutNight:   '#0d1640',

    wallDay:      '#d8c095',
    wallDayWarm:  '#e7cf9f',
    wallDayShade: '#b59b74',
    wallNight:    '#3c4675',
    wallNightLit: '#56618f',

    frameDay:     '#f2e7cf',
    frameDayShade:'#d5c19c',
    frameNight:   '#6a79ad',
    frameNightShade:'#333f73',

    skyDayTop:    '#86bfd3',
    skyDayMid:    '#c6e0da',
    skyDayLow:    '#f4d69c',
    skyNightTop:  '#050d31',
    skyNightLow:  '#1c2f6e',

    sunCore:      '#fff1c2',
    sunGold:      '#f2c45a',
    moonLit:      '#eef0f2',
    moonGold:     '#e8d79a',
    moonDark:     '#1b2a63',
    star:         '#f2f4fb',
    starGold:     '#ffe7a3',

    roofDayA:     '#9fb4b6',
    roofDayB:     '#a9b9ae',
    roofDayC:     '#c7a98f',
    roofNightA:   '#0d1640',
    roofNightB:   '#17225a',
    litWindow:    '#ffc45e',
    darkWindowDay:'#7f8f9a',

    sillDay:      '#efe0bf',
    sillDayFront: '#cdb48d',
    sillNight:    '#4f5d95',
    sillNightFront:'#2e3a6e',
    underSillDay: '#a68c69',
    underSillNight:'#1c2556',
    shadowDay:    '#8d775d',
    causticDay:   '#bff3e4',
    causticGold:  '#ffe39a',

    water:        '#2fb6b4',
    waterDeep:    '#13798a',
    waterLight:   '#8fe3d6',
    waterNight:   '#1f8299',
    waterNightDeep:'#0f4570',
    waterSurfaceDay:'#bdeee2',
    waterSurfaceNight:'#6fb0c8',
    glassDay:     '#e7f4ef',
    glassEdgeDay: '#cfece6',
    glassNight:   '#8fb1dc',
    rimDay:       '#f6fbf7',
    rimNight:     '#b9cdf0',
    reflectDay:   '#fbfdf6',
    reflectNight: '#a9bfe6',

    gravel: ['#2a3f8f', '#e9d7b3', '#c7883f', '#f0c35c', '#7d8fb9', '#b45a2c'],

    gold:         '#e8b84a',
    goldPale:     '#f6dc8a',

    // fish
    fishHead:     '#f4862e',
    fishBody:     '#ea6a18',
    fishBack:     '#c44513',
    fishBelly:    '#f8bb55',
    fishCream:    '#f8dcab',
    fishFin:      '#ee7d36',
    fishFinTip:   '#f7b47c',
    fishFinRay:   '#d1561d',
    fishEye:      '#0e1230',
    fishIris:     '#e9b445',
    fishGill:     '#a83a19',
  },

  // ------------------------------------------------------------------
  // SCENE GEOMETRY (world px, y down)
  // ------------------------------------------------------------------
  scene: {
    window: { x0: 288, y0: 34, x1: 992, y1: 566, frame: 26, bar: 22, transomY: 232, mullionX: 640 },
    sill: { top: 588, front: 624, bottom: 670 },
    bowl: {
      cx: 640, cy: 430, r: 180,
      rimY: 280, rimRy: 11, rimW: 7,
      waterY: 330, surfRy: 13,
      baseY: 600, edgeW: 8,
    },
    sun: { x: 878, y: 124, r: 36 },        // becomes the moon at night
    moonCut: { dx: 15, dy: -9, r: 32 },    // offset disc that carves the crescent
    glint: { x: 724, y: 176 },             // what the fish sees and leaps toward
  },

  // Tile sizes (px) per region family, before grout gap.
  tiles: { wall: 19, frame: 8, sky: 11, sun: 6.2, roof: 9.5, sill: 10.5, under: 13,
           water: 8.2, surface: 6.5, glass: 8.5, edge: 6.5, rim: 5.2, gravel: 11, base: 6,
           gapBg: 1.45, gapFine: 1.0 },

  // ------------------------------------------------------------------
  // TIMING (seconds)
  // ------------------------------------------------------------------
  timing: {
    glintOn: 2.45, notice: 2.75, turn: [3.0, 3.85],
    windUp: [4.35, 5.0], breach: 5.42, apex: 7.0,
    nightStart: 7.85, nightSpeed: 360, flipDur: 0.55, flipJitter: 0.28,
    curl: [8.7, 9.8], airTurn: [10.0, 10.85],
    entry: 12.22, flick: 14.15,
  },

  // Camera keys [t, cx, cy, zoom]; interpolated with smooth Hermite.
  camera: [
    [0.0, 640, 366, 1.100],
    [4.2, 640, 364, 1.116],
    [5.3, 648, 338, 1.135],
    [6.7, 676, 276, 1.175],
    [8.1, 688, 264, 1.185],
    [10.2, 698, 262, 1.185],
    [11.5, 670, 306, 1.155],
    [12.9, 642, 352, 1.132],
    [15.0, 636, 362, 1.125],
  ],

  // ------------------------------------------------------------------
  // FISH
  // ------------------------------------------------------------------
  fish: {
    scale: 1.1,
    bodyLen: 92,          // nose → tail base (local units)
    tailLen: 72,
    pivotU: 0.34,         // pose position sits at this fraction of body length
    tileBody: 5.3, tileHead: 4.8, tileFin: 5.0, tileTail: 5.8,
    // Body half-height profile: [u, top, bottom]
    profile: [
      [0.00, 0, 0], [0.03, 7.5, -6.5], [0.08, 14.5, -12.5], [0.15, 21, -18.5],
      [0.25, 26, -23.5], [0.36, 28.5, -26.5], [0.47, 27.5, -27], [0.60, 22.5, -23],
      [0.74, 15.5, -16], [0.87, 9.5, -10], [1.00, 6.5, -6.5],
    ],
  },
};
