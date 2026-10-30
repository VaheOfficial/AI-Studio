# Animation

Agents compose animation data using reusable Canvas and material-lit WebGL components. Export runs in a browser with software surface rendering and encodes exact frames with FFmpeg. It does not call a model or fetch remote assets. The tools appear in the existing Agents catalog; there is no additional top-level page. Composition version 1 remains compatible; catalog version 3 adds connected scenes, reusable rigs, formations and continuous interpolation.

| Method | Route | Result |
|---|---|---|
| GET | `/api/animation/catalog` | Component schemas, palettes, recipes and composition schema |
| GET | `/api/animation/recipes/{key}?width=1280&height=720&fps=24` | Editable `AnimationComposition` |
| POST | `/api/animation/validate` | Composition → `AnimationValidation` |
| POST | `/api/animation/render` | `{composition, session_id?, preview_only?, quality?}` → `Job` |

Invalid request bodies return 422; unknown recipes and unavailable encoding prerequisites return 400. Encoding and asset failures appear on the job. Inspect the final job status before treating an export as complete.

Agent tools: `animation_catalog`, `animation_recipe`, `animation_project`, `animation_validate`, `animation_render`, `animation_prepare_voice`, `animation_analyze_audio`. The catalog accepts an optional `component` for a focused parameter contract. Export and voice preparation follow ordinary approval rules. Rendering returns the native video artifact, an animation result card, a storyboard image for visual inspection, and links to the local player, composition and report. With `wait:false`, it returns a queued job instead.

## Directing a film

1. Choose a visual treatment and 3–6 readable story beats.
2. Request a recipe or assemble component layers from the catalog.
3. Adjust scene durations, copy, palette, keyframes and camera moves.
4. Validate. Render with `preview_only:true`, inspect the storyboard and revise.
5. Export with `preview_only:false` and check the job/report.

Original recipes cover kinetic typography, paper narrative, product demonstrations, science illustration, ink scenery, rainy pixel scenery, mosaic, orbital systems, engineering, data stories, comics, punk posters, interface morphs, pendulums and grainy night scenery, with additional material, botanical, spline, connected scene and fluid studies. Recipes are editable starting points, not substitutes for directing the user's requested story.

Components: text, shapes, paths, particles, grids, charts, diagrams, interfaces, cutout characters, landscapes, orbits, projected cubes, turbines, weather, local images, groups, authored vectors and parametric 3D meshes. Styles provide coherent palettes and selected texture treatments. Cubes and turbines use Canvas projection; mesh surfaces use depth buffering and interpolated normals. Orbital and pendulum scenes are illustrative rather than physical simulations. Ink scenery uses layered procedural washes rather than a fluid solver. Character movement uses a stable stylized rig.

`scene3d` adds a connected Three.js scene graph: groups and geometric primitives share physical materials, hemisphere/directional/point lighting, environment reflections, and optional shadow maps. Nodes have unique IDs, optional parents, world-unit position/dimensions, Euler rotation in degrees and positive scale. Joint tracks (`x/y/z`, `rx/ry/rz`, `sx/sy/sz`) and perspective camera tracks (`x/y/z`, `target_x/y/z`, `fov`) use layer-local seconds. Backward seeks recompute each transform. Materials support roughness, metalness, clearcoat, emissive color/intensity and deterministic wool/paper/brushed/canvas bump textures. Camera field of view is 10–100 degrees. A scene accepts at most 192 nodes, six explicit lights and a hierarchy of 12 levels.

Model nodes require an explicit scoped local `.glb` source. Geometry and textures must be embedded; external/data URIs and Draco/Meshopt/Basis compression are rejected. Assets are inspected for chunk lengths, texture resolution and complexity before browser loading. Optional `clip` selects an existing named animation, with `clip_speed` and `clip_offset`; the mixer is sampled at absolute local time. This imports 3D geometry, without invoking a generation model. Bundled Three.js 0.186.1 is MIT licensed; its archive integrity and individual file checksums are recorded in `server/studio/animation/vendor/three/manifest.json`. Exports use the same local software browser path and block external requests.

`little-companion` exercises an original articulated mascot with a waving arm and tracked cameras; `precision-assembly` exercises independently rotating metal stages and an exploded assembly. These are editable recipe data, not evidence of universal quality parity with another model.

`scene3d` nodes also accept bounded polygon outlines with an extrusion `depth`, and deterministic joint `motion` (sway/spin, axis, amplitude, speed and phase). A `preset` node expands into an editable scene graph: `preset:mascot` supports idle/wave/look, `paper_bird` supports idle/flight, and `town` supports idle. Root transform tracks apply to the whole rig. Preset expansion counts toward the 192-node scene and 1536-node composition budgets. Only four built scenes are retained in the browser; discarded geometry, materials, mixers and shadow maps are disposed. Local GLB textures have a combined 32-megapixel budget.

Box, plane and polygon nodes may use `repeat` to instance up to 1024 parts in radial/grid/spiral layouts. `spread` and `flip` tracks control assembly/release and turning; wave adds an analytic depth ripple. Limits: 4096 instances per scene, 16384 per composition. `paper-medallion` uses 336 paper pieces across three mesh instances; an agent need not submit hundreds of separate layers. Instance buffers are disposed when their scene leaves the four-scene cache.

Lathe nodes revolve bounded radius/height `profile` points, with optional `angle_start/length` for cutaway shells. Tube nodes sweep along bounded 3D `curve` points, using `dimensions[0]` as radius. Primitive meshes accept numeric material tracks for roughness/metalness/clearcoat/emissive intensity, plus color/emissive `color_tracks`. Imported GLB meshes retain their authored materials; primitive material tracks do not silently override them. `turbofan-study` combines a hollow housing, a blade assembly, streamlines and an illustrated aircraft wing; it is a mechanical illustration rather than a validated engine simulation.

Numeric keyframes optionally select `interpolation:eased` (default), `monotone` (continuous shape-preserving Hermite spline), `log` (eased interpolation in logarithmic value space), or `monotone_log`. Log tracks require strictly positive values. Monotone modes have zero endpoint slopes and continuous interior tangents; `ease` only applies to the eased modes. This applies to layer, component, camera and 3D joint tracks.

Text supports explicit ltr/rtl/auto direction. Long unbroken text wraps on grapheme boundaries; letter animation also segments graphemes rather than splitting combining marks. Joined Arabic/Indic scripts reject letter-by-letter animation to preserve shaping; use whole lines or words with a suitable local font. Empty copy and text that cannot finish its stagger within the allotted hold produce validation warnings.

The condensed role uses bundled Oswald variable font data with a verified source fingerprint and SIL Open Font License. Standalone exports copy its license and the licenses for the copied Geist/Geist Mono faces. Serif/rounded roles still use documented system fallbacks unless an explicit local font is attached.

`tiles` draws up to 100×80 seeded tiles with gold/glass/paper treatments. A fish, bird, moon or circle retains its formation while `phase` releases it and `travel_x/y` moves it. `wave` and `flutter` control internal motion. Returning phase to zero restores the original cells. `flip` sends a spatial wave across the wall; `light_phase` gives explicit lighting control for seamless loops. Optional scoped `source` raster artwork supplies tile colors. `living-mosaic` exercises release, travel, return and a night flip without a stateful particle simulation.

`animation_analyze_audio({source})` measures a scoped local track using FFmpeg and deterministic signal analysis. It returns duration, peak dBFS, energy onsets, quiet gaps, per-second energy and an uncertain tempo estimate. It invokes no speech model, provider or network service. Energy hits may be speech/noise, and estimated tempo may be an octave alias. Use the existing transcription/alignment capabilities for word timing; these measurements alone do not justify word-aligned subtitles.

`fluid` uses a bounded CPU dye/velocity grid, semi-Lagrangian advection, pressure projection and vorticity confinement. Fixed 30 Hz steps and immutable one-second checkpoints reproduce backward seeks. Choose low/medium/high grid resolution, up to eight timed colored emitters and an optional circle/mountain mask. Limit: four fluid layers per film, each at most 30 seconds. This is an art-directed approximation without a free surface, scientific accuracy guarantee or wet-paper chemistry. The older `ink-landscape` recipe remains illustrative; `flowing-ink` exercises the solver.

Fluid `pre_roll` (0–6 integer seconds) seeds a visible opening before layer time zero. Emitters starting at zero participate in the pre-roll; delayed emitters still start at their specified layer-local times. The simulation clock and checkpoints include the extra steps, while emitter end times remain layer-local.

Vector artwork preserves its view-box proportions by default (`fit:contain`). Explicit `fit:stretch` maps the view box to the layer box for authored backgrounds and masks; it may deliberately alter artwork proportions. Optional paper/ink texture treatments are deterministic.

Image layers may describe a uniform sprite sheet with `frames`, `columns`, `frame_rate` and `loop` (defaults 1/1/12/true). Frame selection is a pure function of layer-local time. Sheet dimensions must divide evenly into the grid. `pixelated:true` preserves nearest-neighbor sprite edges. Imported raster assets honor EXIF orientation. Scene `pixel_size` (0–32) optionally downsamples and redraws with nearest-neighbor blocks; the pixel style uses a default coarse grid. This is distinct from the mosaic tile material/formation system.

Render requests may provide `review_times` (up to 24 global timestamps inside the film) and `review_crop` (`x/y/width/height`, normalized inside the stage). The normal full-stage frames are retained, along with full-resolution `crop-XX.png` and `review-crops.jpg`. Agents receive both contact sheets. This allows deliberate face, joint, typography and cut-boundary inspection rather than relying solely on the default three samples per scene.

Scenes run sequentially. Layer positions and sizes use stage fractions; text size uses stage-height fractions. Layer and camera keyframes use local seconds. Rotation uses degrees. Tracks interpolate with smooth, cubic, back, elastic, bounce, linear or step easing. `phase` directs morphs; `spread` directs formations. A scene's transition introduces it from the previous scene. All state is derived from seed and time, allowing backward seeking and exact frame capture.

## Versioned projects and small edits

`animation_project` uses the existing JSON artifact store. Create from exactly one recipe or composition; its compact response contains the real project ID, revision, hash and scene/layer manifest. Read a selected scene when needed. Edit with the observed ID/revision and 1–32 operations: `set`, `remove`, `add_scene`, `remove_scene`, `add_layer`, `remove_layer`. Set/remove operations select optional scene/layer IDs and a relative JSON pointer. For example, targeting `first-form` / `hero` with `/props/roughness` changes one material parameter without resubmitting the film.

For connected scenes, the manifest also lists node IDs. A read may select scene/layer/node IDs to return only the chosen node. Edits may select `node_id` with scene/layer IDs and use a node-relative pointer (`/roughness`, `/tracks/rz`, etc.). `add_node` appends a node to a scene3d layer; `remove_node` removes that node and its descendant branch. All edits in the revision are validated and saved atomically; a missing ID, invalid hierarchy or stale revision commits nothing.

An edit batch validates the entire resulting composition before saving. Invalid batches commit nothing. Stale revisions and cross-chat access are rejected. `animation_render` accepts either a composition or a project ID with its observed revision. The export snapshots that revision and records its ID/hash in the report; later project edits do not alter an exported film. Project content follows the existing artifact limit of one million characters.

## Artwork and motion controls

`brush` layers contain up to 256 pressure strokes per layer and 512 per composition. Each stroke supplies `[x,y,pressure]` points in layer fractions, a width in layer-height fractions, color, opacity, start and duration, and `ink`, `wash` or `dry` medium. Stroke timing must fit the layer. Pigment textures are deterministic, cached within a 32-megapixel budget, and support backward seeking. Wash deposition fades along the stroke; this is an illustrative pigment renderer, not a paper-fluid simulation.

Vector `texture:mosaic` rasterizes authored paths into irregular bevelled tiles with either staggered rows or radial bands. `tile_size` is relative to the layer's smaller dimension; `tile_gap` controls grout. These materials and explicit `tiles` layers bypass the older whole-frame mosaic pixel treatment. Parent groups can animate separate fins, bodies and scenery while retaining each object's tile artwork.

Primitive 3D materials expose `texture_scale` (0.25–16), `bump_strength` (0–0.2) and `glow` (0–3 world units). A composition permits at most 32 procedural texture variants. Wool and canvas retain their authored roughness; their bump textures do not make them glossy. Glow is an additive billboard halo, not volumetric lighting or global illumination.

Scene3D `shadow_resolution` selects 512, 1024 or 2048 pixels per shadow map. `shadow_extent` (2–50 world units) sets the directional shadow camera's half-width and half-height around the world origin. Use a tighter extent for small character scenes; it must still include every relevant caster and receiver. Larger maps increase memory and rendering cost.

- **Hierarchy:** a layer's `parent` names a group in the same scene. Children use parent-box fractions. Group transforms, opacity and clipping are inherited. Child starts remain scene-relative; a parent hides its children outside its active interval. `anchor_x/y` choose the scale/rotation pivot. Group graphs must be acyclic and at most eight levels deep.
- **Transforms/compositing:** separate X/Y scale and skew, blur, palette-aware shadows, linear/radial paint, and source-over/multiply/screen/overlay/lighter blend modes. Rectangle and ellipse masks support animated `mask_reveal` and directional reveals.
- **Typography:** built-in display/body/mono/serif/condensed/rounded roles or attached local fonts. Plain text, clipped line reveals, word/letter staggering, rotation/scale/blur effects, duration, travel, tracking, line height and controlled overshoot. Tracking uses stage-height fractions in all modes. The condensed role uses bundled Oswald; serif and rounded roles use system fallbacks unless a local font is attached.
- **Paths:** smooth Catmull–Rom splines with arc-length `trim_start/end` and optional traveling markers. Authored vector layers accept bounded SVG path commands, fills and strokes; SVG documents, scripts and external resources are not accepted.
- **Surfaces:** sphere, torus, knot, ribbon and superquadric geometry; matched-vertex morphs, Euler rotations, ceramic/metal/matte treatments, roughness, ambient/light direction, perspective, illustrative ground shadows and optional mirrored reflections. Lighting is a stylized analytic shader, not a path tracer or measured material system. WebGL-unavailable players use a faceted Canvas fallback and report a warning.
- **Parameter animation:** `props_tracks` animate documented numeric component parameters within their bounds. `color_tracks` animate documented color properties using palette roles or hex colors. Integer topology parameters remain static. Keyframe times are layer-local.
- **Finishing:** restrained grain and vignette, plus deterministic temporal motion blur with a shutter fraction of a frame and 1–6 samples. More geometry and blur samples increase render time.

`quality` is `draft`, `standard` (default), or `final`. Final uses lossless PNG intermediate frames and H.264 CRF 16; standard uses JPEG intermediates and CRF 18. The final MP4 remains compressed. Preview/report rendering uses the same composition controls.

New exports explicitly convert full-range Canvas RGB to limited-range YUV with the Rec.709 matrix, retain sRGB transfer/Rec.709 primaries metadata and verify those tags with FFprobe. The report records the declared profile. This avoids leaving HD decoder color assumptions unspecified; H.264 chroma subsampling and compression still prevent pixel-identical output. Attached audio must fit the actual rounded encoded duration rather than an extra-frame allowance.

Sphere nodes accept optional `fibers: {count, length, thickness?, seed?}` for short surface tufts. Node scale turns the sphere into an ellipsoid while retaining its fibers. Fibers follow the parent transform and base-color tracks, with deterministic placement. Limits are 8,000 fibers per node, 16,000 per 3D layer and 64,000 per composition. This is bounded instanced geometry, not a hair simulation; fibers do not cast shadows. Length is 0.001–0.08 world units before node scaling. `smallest-light` demonstrates this treatment on the face and ears.

Tiled vector artwork supports `tile_assembly` from 0 (absent) to 1 (complete), and `tile_scatter` from 0 to 2 layer dimensions. Animate these through `props_tracks` to assemble or disperse the artwork. Placement and reveal delays are deterministic; the complete artwork uses its cached raster while intermediate states render individual tesserae. Reversing the assembly returns to the same artwork. Wash strokes now diffuse their pigment before applying the paper fade and granulation.

The `ink-reference-study` recipe follows the observed 39.2-second ink-landscape sequence. `mosaic-reference-study` is an 80-second goldfish sequence with independently grouped architecture, day/night states, water, glass, articulated fins, a jump and a constellation ending. These are visual recreation studies rather than reproductions of the original source code. `night-bloom` and `field-form` are original compositions combining the same public components.

For tiled artwork, `tile_grout` supplies an opaque grout color within the artwork silhouette. `tile_origin` supplies normalized coordinates for radial and arch layouts; `tile_flow:arch` follows circular courses above that point and straight courses below it. `tile_relief` and `tile_variation` control glaze shading and seeded brightness variation. `tile_outlines:true` preserves explicit strokes on filled paths over the tesserae; unfilled stroke artwork remains tiled. `tile_reveal` chooses random, center-out, left-to-right or right-to-left assembly order. These controls retain deterministic seeking. Layer `scale_x` and `scale_y`, including their tracks, accept -10 through 10 for mirrored artwork. Uniform `scale` remains nonnegative.

## Sound and narration

`sound` provides optional synthesized ambient/electro/lofi accompaniment and click, whoosh, chime and impact cues. These are procedural signals, not model-generated music. Attached audio uses explicit local files and global `start` times. Narration tracks with `text` duck the accompaniment. Captions have explicit global start/end times and wrap for the stage size.

`animation_prepare_voice` delegates text-bearing audio cues without a source to the existing `text_to_speech` tool, preserving its provider and permission checks. It returns the updated composition and measured clip durations. Retime scenes and captions using those durations before rendering. Speech exceeding the film is rejected rather than silently truncated. Rendering never generates voice implicitly; planned narration without a file produces a warning. Word-level transcription/alignment remains a separate workflow.

## Files and requirements

Requires FFmpeg, FFprobe, Playwright and compatible Edge, Chrome or Chromium. No GPU or generation model is required. Export explicitly uses software WebGL; a live browser may use its normal graphics backend. The renderer uses bundled fonts when available and system fallbacks otherwise. Attached WOFF2/WOFF/TTF/OTF fonts (up to 10 MB each), raster images and audio pass through the existing scoped file resolver. Transparent images remain transparent; repeated assets reuse one copied file. Total copied assets are limited to 256 MB. Remote assets and executable composition fields are not supported.

Outputs live under `<data_dir>/outputs/animations/<job_id>/`: `film.mp4`, `preview.html`, `storyboard.jpg`, `composition.json`, `report.json`, sample frames, optional soundtrack and copied assets. The player starts paused, supports seeking and respects reduced-motion startup. Keep the directory together for portable HTML playback.

Limits: 120 seconds, 7200 frames, even dimensions, at most 1920×1080 pixels (including portrait equivalents), 40 scenes, 96 layers per scene, 512 total layers, 100 keyframes per track and five megabytes of composition data. Reports distinguish seek determinism from encoded frame counts and list visual/timing warnings. Cancellation terminates encoding; partial failures are not successful exports.

## Source-derived painterly rendering

Set `scene.painterly: {}` to repaint the scene through three instanced WebGL2 brush layers. The renderer is adapted from Joshua Ledbetter's MIT-licensed Functional Emotions, pinned at `b34c20a4f8f64ee87079a2ae2fdedf2cf1990a49` (`js/paint.js`). Its copyright and license are embedded in `painterly.js` and in exported HTML. The song and lyrics are not included.

Ordinary layers form a half-resolution underpainting. `layer.paint_pass: "light"` draws into a separate black-backed additive light surface; this requires `scene.painterly`. Parent transforms and opacity still apply. Captions are composited after painting. Painterly scenes bypass legacy style grain and pixelation; composition finishing remains available afterward.

Controls: `boil` (0–24 paint changes/second), `stroke_scale` (.25–3), `flow` (0–3), `smear` ([x,y], each -120..120), `bloom` (0–3), `grain` (0–.25), `vignette` (0–1). Defaults reproduce the source renderer at 1920×1080. Strokes scale with output height; WebGL2 failure is explicit. Start with `painted-lake` and edit its named layers and camera tracks.

The source implementation samples underpainting color and luminance gradients per stroke, aligns fine strokes with edges, uses a flow field in flat regions, shuffles deterministic draw order, adds dry-bristle opacity, then composites light, weave and vignette. This surface treatment does not generate scene geometry or choreography.
# Contour mosaic scene

`animation_recipe` / `animation_project` accept `contour-aquarium`. The recipe uses
the `mosaic_scene` component adapted from a film the user provided.
Source hashes and the adaptation list are in `animation/mosaic/provenance.json`.
The original directory is not modified. No generated scene code is accepted by this API.

This component preserves the supplied contour tiler, material shaders, bending
spine, fin articulation, bowl optics and choreography. It is an aquarium scene
family, not a general character generator. `animation_catalog(component="mosaic_scene")`
returns the exact bounded parameter schema. Projects can edit these properties:

- `palette`: named scene/material colors such as `fishBody`, `fishFin`, `water`, `skyDayTop`.
- `body_profile`: ordered `[u, top, bottom]` body cross-sections spanning `u=0..1`.
- `fish_scale`, `wave_strength`, `tail_spread`, `fin_activity`, `curl_bias`: acting controls.
- `motion`: ordered `[time,value]` tracks for curl, amp, freq, spread, pect, loosen,
  stretch, lookX and lookY. Times refer to the original 15-second timeline.
- `path`: ordered `{t,x,y,vx?,vy?}` points in the native 1280×720 world.
- `camera`: ordered `[time,cx,cy,zoom]` keys.
- `playhead`: explicit source time, also usable through `props_tracks`.

Without `playhead`, the layer duration retimes the complete original timeline.
Numeric acting multipliers support ordinary `props_tracks`. Palette, geometry,
path and camera are build-time data; edit the project and re-render to change them.
The original scene proportions are stretched into the layer box; use 16:9 to
preserve them. Custom motion paths require visual checking of rim and water contact;
the original splash locations are retained. At most two instances are allowed,
with distinct IDs across the composition. Browser WebGL2 is required; rendering
uses the same sandboxed preview/export and review outputs as other components.

