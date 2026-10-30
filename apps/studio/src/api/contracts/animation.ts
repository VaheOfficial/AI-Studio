/** Declarative, model-independent motion compositions rendered locally. */
export type AnimationStyle = 'studio' | 'paper' | 'ink' | 'neon' | 'punk' | 'pixel' | 'mosaic' | 'blueprint'
export type AnimationComponent = 'text' | 'shape' | 'path' | 'brush' | 'particles' | 'grid' | 'chart' | 'diagram' | 'interface' | 'character' | 'landscape' | 'orbit' | 'cube' | 'machine' | 'weather' | 'image' | 'group' | 'vector' | 'mesh' | 'scene3d' | 'tiles' | 'fluid' | 'mosaic_scene'

/** Points use layer fractions. Pressure is the third coordinate; width uses layer height. */
export interface AnimationBrushProps {
  strokes: { points: [number, number, number][]; width: number; color: string; opacity?: number; start?: number; duration?: number; style?: 'ink' | 'wash' | 'dry'; seed?: number }[]
  grain?: number
}

export interface AnimationVectorMaterial {
  texture?: 'none' | 'paper' | 'ink' | 'mosaic'
  tile_size?: number
  tile_flow?: 'grid' | 'radial' | 'arch'
  tile_origin?: [number, number]
  tile_grout?: string
  tile_relief?: number
  tile_variation?: number
  tile_outlines?: boolean
  tile_reveal?: 'random' | 'center' | 'left' | 'right'
  tile_gap?: number
  tile_assembly?: number
  tile_scatter?: number
}

export interface AnimationFluidProps {
  resolution?: 'low' | 'medium' | 'high'; mask?: 'none' | 'mountains' | 'circle'
  pre_roll?: number
  emitters: { x: number; y: number; color: string; start?: number; end?: number; radius?: number; strength?: number; direction?: number; wander?: number }[]
}

export interface AnimationScene3DNode {
  id: string
  parent?: string
  kind: 'group' | 'box' | 'rounded_box' | 'sphere' | 'capsule' | 'cylinder' | 'cone' | 'torus' | 'knot' | 'plane' | 'model' | 'polygon' | 'preset' | 'lathe' | 'tube'
  profile?: [number, number][]
  curve?: [number, number, number][]
  angle_start?: number
  angle_length?: number
  preset?: 'mascot' | 'paper_bird' | 'town'
  action?: 'idle' | 'wave' | 'look' | 'flight'
  motion?: { axis: 'x' | 'y' | 'z' | 'rx' | 'ry' | 'rz'; kind: 'sway' | 'spin'; amount: number; speed?: number; phase?: number }
  points?: [number, number][]
  depth?: number
  source?: string
  clip?: string
  clip_speed?: number
  clip_offset?: number
  position?: [number, number, number]
  rotation?: [number, number, number]
  scale?: [number, number, number]
  dimensions?: [number, number, number]
  color?: string
  roughness?: number
  metalness?: number
  clearcoat?: number
  texture?: 'none' | 'wool' | 'paper' | 'brushed' | 'canvas'
  texture_scale?: number
  bump_strength?: number
  fibers?: { count: number; length: number; thickness?: number; seed?: number }
  glow?: number
  emissive?: string
  emissive_intensity?: number
  cast_shadow?: boolean
  receive_shadow?: boolean
  tracks?: Partial<Record<'x' | 'y' | 'z' | 'rx' | 'ry' | 'rz' | 'sx' | 'sy' | 'sz' | 'roughness' | 'metalness' | 'clearcoat' | 'emissive_intensity' | 'spread' | 'flip', AnimationKeyframe[]>>
  color_tracks?: Partial<Record<'color' | 'emissive', AnimationColorKeyframe[]>>
  repeat?: { count: number; layout: 'radial' | 'grid' | 'spiral'; radius?: number; spread?: number; flip?: number; wave?: number; turns?: number }
}

export interface AnimationScene3DProps {
  nodes: AnimationScene3DNode[]
  camera?: { position?: [number, number, number]; target?: [number, number, number]; fov?: number; tracks?: Partial<Record<'x' | 'y' | 'z' | 'target_x' | 'target_y' | 'target_z' | 'fov', AnimationKeyframe[]>> }
  lights?: { kind: 'directional' | 'point'; position?: [number, number, number]; color?: string; intensity?: number; shadow?: boolean }[]
  ambient?: number
  exposure?: number
  shadows?: boolean
  shadow_extent?: number
  shadow_resolution?: 512 | 1024 | 2048
  environment?: boolean
  environment_intensity?: number
  fog?: { color: string; near: number; far: number }
}

export interface AnimationTilesProps {
  columns?: number; rows?: number; formation?: 'fish' | 'bird' | 'moon' | 'circle'
  material?: 'glass' | 'gold' | 'paper'; color?: string; background_color?: string
  source?: string; travel_x?: number; travel_y?: number; wave?: number; speed?: number
  flip?: number; gap?: number; flutter?: number; light_phase?: number; night_color?: string
}
export type AnimationEase = 'linear' | 'smooth' | 'cubic_in' | 'cubic_out' | 'cubic_in_out' | 'back_out' | 'elastic_out' | 'bounce_out' | 'step'
export interface AnimationKeyframe { time: number; value: number; ease?: AnimationEase; interpolation?: 'eased' | 'monotone' | 'log' | 'monotone_log' }
export interface AnimationColorKeyframe { time: number; value: string; ease?: AnimationEase }
export interface AnimationMotion { type: 'none' | 'float' | 'spin' | 'bounce' | 'wiggle'; amount?: number; speed?: number; phase?: number }
export interface AnimationLayer {
  id: string
  component: AnimationComponent
  start?: number
  duration?: number
  x?: number
  y?: number
  width?: number
  height?: number
  scale?: number
  rotation?: number
  opacity?: number
  parent?: string
  anchor_x?: number
  anchor_y?: number
  scale_x?: number
  scale_y?: number
  skew_x?: number
  skew_y?: number
  blur?: number
  blend?: 'source-over' | 'multiply' | 'screen' | 'overlay' | 'lighter'
  paint_pass?: 'base' | 'light'
  mask?: { kind: 'rect' | 'ellipse'; reveal?: number; direction?: 'left' | 'right' | 'up' | 'down'; radius?: number }
  shadow?: { color?: string; blur?: number; x?: number; y?: number }
  paint?: { kind: 'linear' | 'radial'; colors: string[]; angle?: number; x?: number; y?: number }
  props?: Record<string, unknown>
  enter?: 'none' | 'fade' | 'slide_up' | 'pop' | 'draw' | 'type'
  enter_duration?: number
  exit?: 'none' | 'fade' | 'shrink'
  exit_duration?: number
  motion?: AnimationMotion
  tracks?: Record<string, AnimationKeyframe[]>
  props_tracks?: Record<string, AnimationKeyframe[]>
  color_tracks?: Record<string, { time: number; value: string; ease?: AnimationEase }[]>
}
export interface AnimationCamera { x?: number; y?: number; zoom?: number; rotation?: number; tracks?: Record<string, AnimationKeyframe[]> }
export interface AnimationScene {
  painterly?: { boil?: number; stroke_scale?: number; flow?: number; smear?: [number, number]; grain?: number; vignette?: number; bloom?: number }
  pixel_size?: number
  id: string
  duration: number
  style?: AnimationStyle
  background?: string
  camera?: AnimationCamera
  transition?: { type: 'cut' | 'crossfade' | 'wipe' | 'iris' | 'slide' | 'glitch'; duration?: number }
  layers: AnimationLayer[]
}
export interface AnimationCaption { start: number; end: number; text: string }
export interface AnimationAudio { id: string; source?: string; start?: number; gain?: number; text?: string; model_id?: string; voice_id?: string }
export interface AnimationSound { music?: 'none' | 'ambient' | 'electro' | 'lofi'; gain?: number; cues?: { time: number; type: 'click' | 'whoosh' | 'chime' | 'impact'; gain?: number }[] }
export interface AnimationComposition {
  version: 1
  title: string
  width?: number
  height?: number
  fps?: number
  seed?: number
  bpm?: number
  style?: AnimationStyle
  palette?: Record<string, string>
  scenes: AnimationScene[]
  captions?: AnimationCaption[]
  audio?: AnimationAudio[]
  sound?: AnimationSound
  finishing?: { grain?: number; vignette?: number; motion_blur?: number; samples?: number }
  fonts?: { id: string; source: string }[]
}
export interface AnimationRenderRequest { composition: AnimationComposition; session_id?: string; preview_only?: boolean; quality?: 'draft' | 'standard' | 'final'; review_times?: number[]; review_crop?: { x: number; y: number; width: number; height: number } }
export interface AnimationProjectEdit { op: 'set' | 'remove' | 'add_scene' | 'remove_scene' | 'add_layer' | 'remove_layer' | 'add_node' | 'remove_node'; scene_id?: string; layer_id?: string; node_id?: string; path?: string; value?: unknown }
export interface AnimationValidation { valid: boolean; duration: number; frames: number; warnings: string[]; component_counts: Record<string, number> }
export interface AnimationCatalog { version: number; styles: Record<AnimationStyle, Record<string, string>>; components: Record<AnimationComponent, { description: string; parameters: Record<string, unknown> }>; schema: Record<string, unknown>; recipes: { id: string; title: string; description: string }[]; workflow: string[]; directing_controls: Record<string, string>; coordinates: string }

/** Contour-mosaic scene family; source time is 0..15 seconds. */
export interface AnimationMosaicSceneProps {
  palette?: Record<string, string>
  seed?: number
  fish_scale?: number
  wave_strength?: number
  tail_spread?: number
  fin_activity?: number
  curl_bias?: number
  playhead?: number
  body_profile?: [number, number, number][]
  camera?: [number, number, number, number][]
  path?: { t: number; x: number; y: number; vx?: number; vy?: number }[]
  motion?: Partial<Record<'curl' | 'amp' | 'freq' | 'spread' | 'pect' | 'loosen' | 'stretch' | 'lookX' | 'lookY', [number, number][]>>
}
