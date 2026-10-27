# Verse realtime decks: the eye-level view

Status: all four decks exported (bridge 2026-10-20; engineering, hangar and
ops 2026-10-26, when the lightmap packing was rebuilt and the bridge
re-exported with it).

The plate pipeline photographs a deck from one fixed angle. The realtime
export turns the same Blender scene into a 3D scene the browser walks through
at eye level, so the person steers the commander in third person from behind
their shoulder or in first person through their eyes, with shooter mouse look,
as in a game. The plate stays: it is the bird's-eye view (key 1) and the view
of an IDE side panel smaller than 480 × 360 CSS px (`COMPACT_EYE_MIN` in
`engine/stageView.ts`); a larger side panel walks at eye level like the
full-size stage, on the low quality tier while the setting is "auto".

| | Plate (bird's-eye, small panel) | Realtime (full-size stage or roomy panel, third or first person) |
|---|---|---|
| Camera | orthographic, 60° down, fixed | perspective, over the shoulder or at eye height, shooter mouse look |
| Light | Cycles path tracing, baked into the photograph | Cycles bake of the diffuse light into lightmaps + live reflections |
| Ceilings, upper walls | hidden (cutaway, BRIEF §5) | real geometry |
| Content | `plate/`, `occluders.glb`, `nav.png`, `env.hdr` | `realtime/scene.glb`, `realtime/lm_*.webp`, `realtime/probe_*.webp` |

Both share the manifest, nav grid, sockets, stations, rooms, light probes and
the live people, screens, holograms and beacons.

## Pipeline

```
python scripts/verse/cook.py deck <id> --realtime [--quality preview|final] [--keep-blend]
```

Runs in headless Blender under the GPU lock (`scripts/verse/_realtime_entry.py`
→ `art/verse/lib/realtime.py`), then packages (`scripts/verse/package_realtime.py`,
outside Blender, needs `node` and the frontend's `node_modules` for the meshopt
encoder) and validates. The deck must have been cooked once (its manifest
exists); the plate is not touched, and a later plate cook keeps the
`realtime/` folder and block. `--keep-blend` saves the baked scene to
`art/verse/.cache/blend/RT_<id>.blend`.

| Quality | Pages | Density (weight 1) | Irradiance samples | Probes | Use |
|---|---|---|---|---|---|
| preview | ≤ 2 × 1024² | ≤ 10 px/m | 48 | 256 × 128 | iteration (~2 min) |
| final | ≤ 4 × 4096² | ≤ 48 px/m | 512 | 1024 × 512 | committed content (~15 min for the bridge) |

Stages (`lib/realtime.py`, timings in `realtime.stats`):

1. **Realise.** Every mesh instance of Architecture, Props and Ceiling (kit
   instances included) becomes its own object with modifiers applied (the
   per-material face counts are checked to survive this step).
   Ceiling ghosts (`ceiling_ghost`, the cut-away upper walls) and ceilings
   become normal geometry: visible, casting shadows. Faces of
   `EXCLUDED_MATERIALS` are dropped: `M_Section_Cap` (the cut plane is a
   drawing convention) and the floor decals with worn-through transparency
   (`M_Deck_Hazard`, `M_Deck_Marking_White`; they need an alpha bake, see
   "Open work").
2. **Visibility.** Eye points on a 1.2 m grid in every room polygon, at 0.9,
   1.7 and 2.5 m above its floor, cast 256 rays each; objects no ray reaches
   (hull voids behind full walls, pipe runs inside double walls, the dark
   boxes behind the star fields) stay in the scene for the lighting but are
   neither unwrapped nor exported. On the bridge: 646 of 1395 objects,
   7400 m², 236k triangles.
3. **Unwrap.** Each object gets a second UV set `LM` from Smart UV Project
   into its own square, its islands `ISLAND_GAP_TEXELS` (2.5) apart at the
   expected density, and goes whole, as one rectangle sized by its weighted
   area, onto skyline-packed pages (`lib/lightmap.pack_skyline`; rectangles
   `2 × (margin_px + 1)` texels apart, grouped by room so a room shares few
   pages; about 80 % of a page ends up in rectangles). An object whose
   islands cover less than `MIN_LAYOUT_FILL` (0.3) of its square (thousands
   of slivers, a decimated shaft wall) is sized as if they covered that
   much: it gets fewer texels instead of taking space from everyone else.
   Texel density follows `DENSITY_WEIGHT` (how close people get: hull voids
   0.3, ceilings 0.45, floors 0.75, walls and consoles 1.0); the base density
   steps down until everything fits into `max_pages`.
   Until 2026-10-26 the pages were packed island by island with Blender's
   Pack Islands, a full page margin per island: objects of panels, bevels
   and greebles have thousands of islands, so the margins alone overflowed
   the pages and Pack Islands shrank everything; the bridge's four pages
   held only 3-15 % surface (its reported 38.6 px/m was nominal, the real
   density about a third of it). Measure with `realtime.json`'s chunks:
   the summed LM UV area per page is the share of the page in use.
4. **Join.** Cycles re-syncs the whole scene for every object it bakes, so
   each page's objects are joined (one object per set of ray-visibility
   flags). The kit's materials read Object coordinates and Object Info >
   Random; before joining, each object's local coordinates and a random go
   into the point attributes `rt_orco` / `rt_random`, and the materials are
   rewired to read them, so joined surfaces bake exactly as instanced ones.
5. **Bake** per page (Cycles, OptiX): world normal and position (guides),
   diffuse colour (albedo), emission, and diffuse direct + indirect light
   (irradiance, `samples`). The irradiance is denoised with an edge-aware
   à-trous filter guided by normal and position (`lib/lightmap.denoise`:
   light never crosses a corner or jumps between islands), then
   `radiance = albedo × irradiance + emission` (scene linear, HDR) and the
   gaps between islands are filled by push-pull (`fill_gaps`) so mip levels
   and compression never pull black into an island.
6. **Probes.** One equirect reflection panorama per room at its probe point
   (the light probe's point, eye height), with the real ceilings, and the
   room's box (polygon bounds, floor to the ceiling hit straight up) for
   parallax correction.
7. **Geometry.** Triangles are grouped into chunks by (material, room, page):
   the room is the one the face looks into (centroid moved 8 cm along the
   normal), so each chunk reflects its own room's probe. World positions,
   normals and the LM UV per chunk, welded.

## Files and manifest block

```
public/verse/decks/<id>/realtime/
  scene.glb            meshopt glTF, one node per chunk
  lm_<page>.webp       lightmap pages, RGBA, "rgbm2"
  probe_<room>.webp    reflection panoramas, RGBA, "rgbm2", three.js equirect layout
```

`scene.glb`: glTF 2.0 with `EXT_meshopt_compression` (vertex codec v0,
vertex-cache and vertex-fetch optimised) and `KHR_mesh_quantization`.
Per chunk one node, `extras: {material, room, page}`, translation and one
uniform scale (positions are int16; a uniform scale keeps world normals
right), `NORMAL` int8 normalised, `TEXCOORD_0` = the lightmap UV, uint16
normalised, glTF orientation (v = 0 is the page's top row). Materials in the
file carry only names; the runtime builds them from the manifest.

**rgbm2** (lightmaps and probes): RGBA8, lossy colour, lossless alpha (WebP
`alpha_quality=100`). Decode: `m = a² · range`, `rgb = c² · m` (a, c in
0..1). Both factors are squared, so precision follows brightness: dark
texels keep fine steps, fixtures up to `range` (a power of two, ≤ 64) never
clip. `lib/lightmap.rgbm_encode` / `rgbm_decode`; the shader decodes the
same way. Decode images with `premultiplyAlpha: "none"` and
`colorSpaceConversion: "none"`.

Manifest (`verse.deck/1`, optional, backwards compatible; schema in
`art/verse/schema/deck.schema.json`, runtime parser in `content/manifest.ts`):

```json
"realtime": {
  "version": 1,
  "quality": "final",
  "scene": { "url": "realtime/scene.glb", "vertices": 1319724, "triangles": 1023325, "chunks": 295 },
  "lightmaps": { "encoding": "rgbm2", "range": 32,
                 "pages": [{ "url": "realtime/lm_0.webp", "size": 4096, "density": 38.61 }] },
  "probes": [{ "room": "bridge", "url": "realtime/probe_bridge.webp", "w": 1024, "h": 512, "range": 32,
               "position": [36, 1.4, 16.12], "box_min": [3.6, 0, 3.6], "box_max": [68.4, 7.2, 31.2] }],
  "materials": { "M_Floor_GlossBlack": { "roughness": 0.3, "metalness": 0, "color": [0, 0, 0],
                 "clearcoat": 1, "clearcoat_roughness": 0.06, "specular": 0.12,
                 "detail": "deck_plates", "transparent": false, "opacity": 1, "collide": true } },
  "bytes": 16500000,
  "stats": { "objects": 749, "hidden_objects": 646, "density": [38.61], "bake_s": 816 }
}
```

Materials: the bake holds all diffuse light with the albedo in it, so a
realtime material is only the **specular layer** on top: roughness,
metalness, metal tint (`color`), clear coat, specular level (Blender's
Specular IOR Level, 0.5 = F0 4 %), transparency (glass), whether the camera
collides with it, and a close-up `detail` layer. `MATERIALS` in
`lib/realtime.py` lists them per kit material; a material missing there is
read off its Principled BSDF defaults. **Add new kit materials to that table.**

A runtime that does not read `version` ignores the block and shows the plate.

## Runtime

Code: `src/components/society/verse/engine/realtime/`.

| File | Role |
|---|---|
| `realtimeScene.ts` | Loads the glb (GLTFLoader + MeshoptDecoder), the pages (ImageBitmap, flipY off) and the probes (decoded on the GPU into half-float equirects, PMREM); builds one material per chunk key; builds the collision BVH (three-mesh-bvh) over chunks whose material collides. |
| `deckMaterial.ts` | `makeDeckMaterial`: MeshStandardMaterial, or MeshPhysicalMaterial where a coat, a specular level or glass needs it. `patchDeckShader` adds the baked radiance (`totalEmissiveRadiance += decode(lightMap)`), removes lightmap irradiance and environment diffuse, box-projects reflections into the room's box (grown to hold a fragment just past it, such as a doorway or a lift alcove, so the projection never jumps), and for `deck_plates` draws the 2.4 × 1.2 m plate joints and bolts and broad, soft smudges on the coat (no fine noise in the coat's roughness: it drew lights as blocky squares). Glass blends `ONE, ONE_MINUS_SRC_ALPHA` (its reflection plus what is behind it). |
| `shoulderRig.ts` | The camera, third and first person (below). Pure. |
| `viewMode.ts` | The three views and their keys, the wheel's hand-over between third and first person (`zoomStep`), which way the body faces while walking in a shooter view (`bodyFacing`). Pure. |
| `mouseLook.ts` | Shooter mouse look shared with the duel: the turn rate per pointer-lock pixel, sensitivity and inverted axis (`lookDelta`), taking the mouse with raw movement where the browser allows it (`requestMouseLook`). |
| `RealtimeBackdrop.tsx` | Loads the scene into the stage's scene on `REALTIME_LAYER`, owns the frame while active: rig → camera → post chain → stats → `afterFrame`. Publishes `runtime.eye` (camera + collider) for the HUD and the pointer. |
| `orbitInput.ts` | Mouse: a click on the view takes the mouse (pointer lock); then movement turns the view and the left button works what the crosshair is on; Esc gives it back (the HUD's buttons work again). A drag still turns the view where the lock is refused. Touch and pen: drag turns, pinch zooms, a tap picks. The wheel zooms through the stage, which hands over between third and first person. |
| `viewSettings.ts` | The person's settings, kept in this browser: sensitivity, inverted look, field of view per person, quality, and the view they last chose. |
| `eyePick.ts` | Pointer picking at eye level: bodies as upright cylinders (only in front of the deck's geometry), stations near the deck point hit, floor points to walk to. |

The first-person viewmodel (the commander's own arms and, in a duel, the
blaster) lives in `src/components/society/verse/viewmodel/` (below).

The stage (`VerseStage.tsx`) shows the realtime view when the stage is
full size, the deck has a realtime block and the view is third or first
person; the bird's-eye view is the plate (the realtime scene stays loaded,
the plate idles while hidden). A deck whose realtime scene fails to load
falls back to the plate. `runtime.toScreen` and `runtime.ray` project through
the eye-level camera while it is on screen, so name plates, station labels,
crew cards and clicks work in both views. In the realtime view the keys are
camera-relative (`CommanderControl.directionFrom`), beacons get world sizes
and depth, and the plate-only lamp sprites (LightsLayer) are off.

People: the same actors as on the plate, lit by the room's SH light probe
and the deck's environment map (`actors/roomLight.ts`), with AgX at the
plate's exposure; the baked room light and the people match because both
come from the same Cycles scene.

Post chain (tier "high"): HDR half-float target with 4× MSAA, bloom
(UnrealBloom, threshold 1.5, strength 0.035, radius 0.3, scene linear before
the exposure; UnrealBloom sums five blur levels, so more veils the dark deck
in grey), output pass with AgX and `toneMappingExposure = 2^exposure`. The
eye view clears to true black (AgX lifts the plate view's near-black clear
colour to a visible grey). Deck materials are double-sided: Cycles renders
both sides of a face, and builders leave open quads (star fields, decals)
facing either way.

Depth order (2026-10-27): the kit lays many faces in one plane (a raised
floor's edge flush with a wall, a recess panel on wall paint, a beam on the
hull plating, two rooms' walls back to back, 1,500 to 10,000 m² per deck),
and without an order the GPU picked one surface per pixel and per frame, so
whole strips of wall flickered as the camera moved. The deck shader moves
every vertex back along its view ray by a fraction of its distance (the
picture stays put, only the depth changes): each material of a deck gets
its own step (`depthOrder`: keys, lights and screens in front, then trims,
structure, walls and floors, the hull), back faces lose to all of them, and
the near plane is 8 cm (was 5 cm). Measured with a near-plane jitter (pixels
that change when only the depth mapping moves) over 30 to 40 random eye
points per deck: hangar 13,500 → 1,030, engineering 257 → 129, ops
11,663 → 10,087, bridge 819 → 799. A per-material polygon offset and larger
steps measured worse: they push surfaces that sit millimetres apart into
new ties. What is left in ops is wall panels that cross each other by a
millimetre or two (the int16 positions of two chunks round differently):
a fixed jagged edge, not a flicker.
Tier "low" (a GPU that stays slower than ~45 fps for 2.5 s at "high"):
direct render, no bloom, pixel ratio at most 1. `runtime.stats.tier` shows
the tier; `window.__verseStats` exposes the frame numbers in every build.

QA hook: `window.__verseTune = { bloomStrength, bloomRadius, bloomThreshold,
envGain, bakedGain, coatBias, exposureBias, materials: { <name prefix>:
{ <numeric material property>: value } } }` overrides the look while a run
measures it (read every frame; unset, the built-in values apply). Tune
against Cycles renders from the same camera (`SHOULDER` numbers; ceiling
ghosts visible), then move the values into the code.

### Views

Three views (`viewMode.ts`), switched on the tool rail's three-part control
(bird's-eye, third person, first person; the one on screen pressed and
named, the others an icon and their key) or from the keyboard. The last view
chosen is kept in this browser (`viewSettings`, `view`). First person needs
the eye-level scene; where there is none (the IDE panel, decks not exported)
its button is disabled and a remembered first person shows third person.

| Input | Bird's-eye | Third person | First person |
|---|---|---|---|
| 1 / 2 / 3 | pick the view (top row or keypad) | | |
| V | cycle bird's-eye → third → first → bird's-eye | | |
| Mouse | drag pans, click walks / selects / uses | shooter look (pointer lock): X turns, Y pitches | same |
| Click on the view | walk / select / use | takes the mouse (when free) | same |
| Left button (mouse taken) | | works what the crosshair is on: a crew member (again: their record), a station; never walks | same |
| E | station within reach | what the crosshair is on, else the station within reach | same |
| Esc | closes card / panel | gives the mouse back (HUD usable), then closes card / panel | same |
| L | | takes or gives back the mouse | same |
| W A S D | pan the map | walk relative to the view (A/D strafe), Shift hurries | same |
| Wheel, + / − | zoom the plate | shoulder distance 1.2–5 m, eased; one notch past 1.2 m goes to first person | a notch out returns to third person at 1.2 m |

Choosing third or first person with a click or a key takes the mouse at once
(the browser needs that gesture); the bird's-eye view gives it back. With the
mouse free the crosshair dims and *Click to look around* shows under it.
Pointer lock asks for raw movement (`unadjustedMovement`) and falls back to a
plain lock. Touch and pen keep drag-to-turn and tap-to-pick.

While walking in a shooter view the commander faces the view, leaning at
most 45° into a strafe; walking backwards they keep facing it and the walk
clip plays in reverse (`bodyFacing`, `Actor.drive`). Standing still they turn
freely. The camera never turns on its own (no recentring). The duel uses the
same mouse look (`lookDelta`, `requestMouseLook`; see combat.md).

### Camera

`SHOULDER` in `shoulderRig.ts`; the third-person framing copies the reference
shot the person gave: the commander in the lower right third, seen from about
mid-thigh up, the room at eye level in depth.

| | Value |
|---|---|
| Horizontal field of view | third person 70°, first person 85° (each 55–110° in the view settings; vertical from the aspect, at least 40°); blends with the person |
| Mouse look | 0.0022 rad per pointer-lock pixel × sensitivity (0.25–3), the duel's rate too; drag 0.0042 rad/px |
| Pivot | 1.74 m above the feet (top of the head), 0.47 m to the camera's left of the commander, so they stand right of centre (~0.63 of the width) |
| Distance | 2.4 m behind the pivot (wheel: 1.2–5 m, eased with 0.09 s); the commander fills the frame from mid-thigh up, head top at ~0.48 of the height, as in the reference |
| Pitch | third person 7° down by default, −35° (up) to 60° (down); first person ±80° |
| Height | ~2.03 m at the default pitch (a little above the commander's head, looking slightly down on their shoulders); the horizon sits a little above the middle of the frame |
| First person | eyes 1.65 m above the feet, 0.1 m in front of the body's axis, no sideways lag, the pivot's vertical lag; a segment test keeps them 0.12 m short of a wall in front; the commander's body is hidden past 30 % of the blend, where the viewmodel's arms take over |
| Hand-over | third ↔ first blends position and field of view in about 0.2 s (time constant 0.07 s, smoothstep) |
| Follow | pivot lags 0.07 s horizontally, 0.16 s vertically (no head bob; the pivot ignores the walk cycle) |
| Collision | segment tests head → shoulder → camera against the BVH; in at once with 0.24 m clearance, back out at 3.2 m/s |
| Keys | W away from the camera, S toward it, A/D strafe; the commander faces the view while walking (9 rad/s) with the shared clips; Shift hurries |

### First-person viewmodel

In first person the commander sees their own arms, cut from their own body
with its real skin weights: gloved hands at the bottom of the frame on the
deck, and in a duel fought through the eyes the blaster in the right hand
with the left supporting it. Code:
`src/components/society/verse/viewmodel/`.

| File | Role |
|---|---|
| `motion.ts` | Pure: who is drawn (`viewmodelVisibility`: arms in exactly where the third-person body goes out, past 30 % of the blend; the body also goes when a wall pushes the shoulder camera within 0.55 m), the walk bob (a dip per footfall, a sway per stride, scaled by ground speed / walk speed up to 1.7), idle breathing, look lag (the arms trail a turn by up to 0.07 rad and settle in ~0.1 s) and the recoil spring (a shot kicks the blaster back ~2 cm and the muzzle up ~2.5°, settling in ~0.25 s). prefers-reduced-motion drops bob, sway and lag and halves the recoil. |
| `armMesh.ts` | The arms cut from the commander's own body (`cutArms`): the officer the deck and the duel draw for them (`SK_Officer_M`/`_F`, chosen by id), every triangle hanging at least half on an arm bone (upper arm to fingertips: sleeve, cuff, hand) with its painted atlas UVs, baked occlusion and the body's own skin weights. The shared skeleton has one bone for the four fingers and one for the thumb, so the cut re-rigs the hand from its geometry: finger vertices are sorted into index, middle, ring and little finger across the hand (1-D k-means), each finger's axis and length are measured, and the finger bone's weight is shared out along three phalanges (joints at 47 % and 75 % of the finger, blended over ±6.5 %), the thumb's along three bones of its own. The forearm gets a twist bone (its weight runs from the elbow's hinge to the wrist's twist), so turning the hand over rolls the forearm as a radius does. 19 bones per arm. |
| `arms.ts` | One arm's bones (`ViewArm`): two-bone IK from shoulder to wrist with the body's own lengths (`solveElbow`; a wrist out of reach draws the shoulder after it, never the hand off the sleeve), the forearm's hinge in the elbow's plane and its twist following the back of the hand, and a hand pose (`HandPose`: the three outer fingers, the index finger and the thumb apart; each finger curls through all three joints, the end joint following the middle one). |
| `viewmodel.ts` | The rig, its own scene and camera, posed every frame in the camera's space; the layout (`VIEWMODEL`: poses, holds, hand poses, gloves, shoulders, field of view, light). Holds say where the held part sits in the hand's frame; `solveHolds` closes the hands on the blaster by searching each hold's knuckle and middle joints so every finger's joints and tip rest a finger's thickness off the grip (a raked box) or the shroud (a cylinder), and rests the right index finger's pad on the trigger. |
| `rigMesh.ts` | The blaster and the shield emitter as one skinned mesh: `RigBuilder` bakes every part into one geometry on its bone, `RigPalette` holds every surface as a texel of three float textures under one material; `chamferBox` (44 triangles). |
| `viewmodelPass.ts` | The draw: a pass in the eye view's post chain after the deck's render pass, into the same multisampled HDR target with depth cleared first (so the arms get the deck's anti-aliasing, bloom and AgX and never meet a wall); on the low tier the same draw straight to the screen. No full-screen pass of its own. |
| `ViewmodelLayer.tsx` | Mounts the viewmodel on a stage with an eye-level view (`runtime.viewmodel`), cuts the arms from the commander's body once the character library has it (`attachArms`; until then only the blaster shows), and tells it each frame what to show: the deck's hands, the duel's blaster, or nothing. |

The arms wear the body's atlas under one material: the material colours
multiply into the vertex colours over the baked occlusion (the sleeves in the
rank tier's `M_Uniform`, repainted on a promotion; the cuff's trim band in
the same cloth, because a hand's breadth from the eye its sawtooth edge
would show as a change of tone, and lifted 1.8 mm off the sleeve it cuts
through). The officer's bare hands are gloved (`VIEWMODEL.gloves`, dark
leather multiplied into the hands' painted atlas, so knuckles and tendons
keep their relief; `null` shows the skin).

The viewmodel camera takes the eye camera's orientation but sits at the
origin with its own near plane (1 cm) and a fixed horizontal field of view
(88°, 76° in the sights), so the arms keep their shape whatever the person's
field-of-view setting. Because the rig is turned with the view, the room's
SH probe (`RoomLight`) and the deck's environment light it as they light the
deck; a soft key light over the shoulder (divided by the deck's exposure, so
it reads the same on every deck) keeps dark uniforms and gloves legible.

In a duel the blaster is the duel's own model (`buildBlaster`, chamfered
edges for the close view, the stock left out so it never hides the right
hand, the sight's glowing pane swapped for a see-through reticle). Poses,
blended over ~0.1 s: hip (low on the right, the right hand on the grip with
the index finger on the trigger, the support arm coming up from the bottom
edge; the centre of the screen and its left half stay clear), sights (`ads`
moves the sight's window onto the view axis 0.3 m ahead; the field of view
narrows), sprint (lowered, turned in and canted across the bottom of the
frame, still in view), shield (Q: the blaster drops, the left
forearm comes up before the face, palm forward, its emitter lit with the
shield's energy and flaring on a parry), vent (R: the blaster tips up and the
left hand slaps the receiver's side), knocked out (the arms drop away). A
dodge dips the arms. Each shot kicks the recoil spring and flashes at the
muzzle (a sprite and a short light on the hands); the world's own muzzle
flash and vent steam for the person are skipped in first person.

Budget: both arms are one skinned mesh under one material (about 3,070
triangles from the officer body); the blaster and the shield emitter are a
second (`rigMesh.ts`: every rigid part baked into one geometry at full weight
on its bone, every surface a texel of a small float palette; about 1,100
triangles). The blaster's glowing parts copy its heat colours into the
palette each frame; on the deck its vertices collapse to a point. That is two
draws on the deck and four in a duel (the arms, the blaster, the sight's
reticle, the muzzle flash), about 4,200 triangles. The rig test holds it to
4 draws and 6,000 triangles; the cut's tests hold every vertex to four
normalised weights on its own arm, blended elbows, wrists and knuckles, three
weighted phalanges per finger and thumb, the fingers sorted across the hand,
the bind pose reproduced exactly, and a bent elbow with a closed fist that
neither tears nor collapses a triangle.

Development handle (dev builds only): `window.__verseViewmodel = { layout,
arm, cut, motion, retune(), viewmodel }` tunes the layout live: change
`layout` (or `arm`), then `retune()` (it repaints and closes the hands
again); `cut` takes effect when the arms are next cut.

QA hook (every build): `window.__verseView = { set(view), look(dx, dy),
zoom(factor), state() }` switches views, turns and zooms without a mouse
(headless browsers cannot lock the pointer); `state()` reports the view, the
person, distances, the blend, field of view, yaw, pitch and whether the mouse
is taken.

## Measured (bridge slice, RTX 5070 Ti, 2560 × 1392)

Headless Chrome against an isolated instance of the built app, tier "high":

| | Value |
|---|---|
| Frame rate | 60 fps (vsync) standing, walking and looking around; uncapped (`--disable-gpu-vsync --disable-frame-rate-limit`) ~600 fps, frame ~2 ms, CPU ~1.5–2.3 ms |
| Draw calls | 200–290 (deck chunks, crew, effects) |
| Triangles drawn | 0.6–0.95 M |
| Content | 1.02 M triangles in 295 chunks; `realtime/` ~16.5 MB (glb 11.2 MB, 4 lightmap pages 4.7 MB, 6 probes ~0.6 MB) of the 25 MB budget |
| Export | ~15 min on the GPU (bake 13.6 min of it), package ~2.5 min |

The look was tuned against Cycles renders from the rig's exact camera with
the ceiling ghosts visible (`window.__verseTune`): baked deck levels match
the Cycles render; the floor's coat reflections, bloom and the windows were
corrected until the dark areas matched.

## Decks (final quality, 2026-10-26)

| Deck | Export | `realtime/` | Triangles / chunks | Density (weight 1) | Pages in use |
|---|---|---|---|---|---|
| bridge | 15 min (bake 11.5 min) | 19.4 MB | 1.07 M / 360 | 37.6 px/m | 4 pages (wall cladding 2026-10-26, ready room corner wall 2026-10-27) |
| engineering | 11 min (bake 7.5 min) | 21.2 MB | 1.56 M / 206 | 29.5 px/m | 25-41 % surface, 82 % in rectangles |
| hangar | 12 min (bake 9 min) | 18.7 MB | 1.09 M / 197 | 27.7 px/m | 21-54 % surface, 80 % in rectangles |
| ops | 17 min (bake 11 min) | 16.2 MB | 0.91 M / 441 | 29.5 px/m | 38-53 % surface |

Closing the rooms at eye level (step 1 below), besides the ceiling ghosts:
engineering's plain full-height walls (west hull wall, lobby | bay,
bay | gallery) carry dark panelling with a rail and thin light strips
(`eng_upper.cladding`, Architecture), the door slots in them have heads,
and the near hull wall's upper panels are dark paint and charcoal instead
of flat mid grey; the hangar's front band (booth, crew bay, arrivals, lift
lobby, armoury) got the same upper panelling (`hangar_upper`). On the
bridge (`decks/bridge/cladding.py`) the side hull walls and the aft
bulkhead's hall face carry charcoal panels with recessed seams, gunmetal
ribs every 4.8 m with dash lamps, light columns in alternating bays, louvre
vents, a conduit bundle on a rail and a recessed cornice; the aft rooms'
walls carry the light-grey room panelling with a light channel (one lamp of
half the bay's length per 2.4 m bay, so the rooms read no brighter than the
hall's sparse lamps). All of it is
ceiling ghosts built below the lowest floor (nothing clipped; the bulkhead's
room faces, which the plate sees below the cut, are clipped at it), so the
plate, nav grid and occluders keep their shape. The one exception is the
ready room's diagonal corner wall with its two slit windows: the plate sees
it whole, so its panelling (`cladding.window_wall`: gunmetal jambs, sill and
head around each slit) is real geometry, built inside the wall's former
volume so nav and occluders stay the same.

"Surface" is the share of each page the lightmap UVs cover; before the
packing rebuild the bridge's pages held 3-15 %. The bridge numbers in
"Measured" above are from the first slice (2026-10-20, old packing).

## Exporting another deck

1. Close the rooms at eye level. Everything the plate's cutaway removes must
   exist above the cut as ceiling ghosts: build the upper parts of cut walls
   with `kit.ghost(L.CUT_H)` into the `Ceiling` collection (see
   `art/verse/decks/bridge/upper.py`; kit `*_Cut` pieces already carry their
   ghosts). Door openings need heads and jambs up to the door height.
   Ghosts stay invisible to the plate camera and to shadow rays, so the
   committed plate does not change until the deck is recooked (then they
   show only in floor reflections, as BRIEF §5 asks).
2. Check the eye-level look before baking: render a few Cycles views from
   walkable spots with ceilings visible (perspective camera ~1.9 m high,
   72° HFOV) and look for black voids above walls, missing ceilings and hull
   gaps.
3. Add every new material to `MATERIALS` (and `DENSITY_WEIGHT` if people
   never get close to it) in `lib/realtime.py`.
4. `python scripts/verse/cook.py deck <id> --realtime --quality preview`,
   check it in the app (isolated instance), then `--quality final`.
5. `python scripts/verse/validate.py` and `pytest tests/verse` must pass;
   the realtime folder of a deck has a 25 MB budget, the whole
   `public/verse` 160 MB.

## Open work

- The viewmodel's arms are procedural rigid parts on bones (no authored skin
  weights, so joints do not bend their surfaces); there is no reload or
  inspect animation beyond the vent slap.
- There are no strafe or backwards clips: strafing leans the walk up to 45°,
  backwards plays the walk in reverse.

- Engineering's reactor shaft and the hangar are tall open volumes with one
  probe each; the probe box runs from the room floor to its ceiling, so the
  52 m shaft below the reactor hall's floor reflects as if it ended there.
- Floor markings with worn-through paint (`M_Deck_Hazard`,
  `M_Deck_Marking_White`) are left out: bake their paint coverage as alpha
  (an extra EMIT bake of the `keep` mask) and draw them alpha-tested.
- Planar reflections for the main floors would add the crew and consoles to
  the black deck's mirror; the box-projected probes show the room only.
- The x-ray silhouettes of the plate view are off at eye level.
- Lightmap texels are 2.6–3.5 cm: crisp enough with the live reflections and
  the floor's plate detail, soft on small console details up close. Tiling
  detail normals per material (`detail` "painted"/"metal" today only break
  up the roughness) would sharpen walls and consoles further.
