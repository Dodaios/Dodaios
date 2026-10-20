# Verse crew: characters, skeleton and clips

Source of truth for the realtime people and drones of the Verse. Everything here is
Blender Python; the cooked files live in
`dodaios/ui/web/frontend/public/verse/characters/`. No `.blend` is committed.

## Build

From the worktree root (Blender 5.0, through the pipeline runner):

```
python scripts/verse/blender.py run --no-lock art/verse/characters/fetch_base.py   # once
python scripts/verse/blender.py run --no-lock art/verse/characters/build.py        # humans + clips
python scripts/verse/blender.py run --no-lock art/verse/characters/build_drones.py # drones
python scripts/verse/blender.py run art/verse/characters/build.py --qa             # + Cycles QA
python scripts/verse/blender.py run art/verse/characters/build.py --qa-contact     # contact sheets only
python scripts/verse/blender.py run --no-lock --device cpu art/verse/characters/lookdev.py  # look-dev
node art/verse/characters/check_glb.mjs                                          # three.js check
```

`build.py --only SK_Officer_M,SK_Trooper` rebuilds a subset; `--no-clips` skips the
animation export (the clip files only change when the skeleton or `anim.py` does).
Builds are deterministic (no random numbers, fixed iteration order). Run
`build_drones.py` before `build.py`: `build.py` merges the drone entries into
`characters.json`.

| Module | Job |
|---|---|
| `body.py`, `outfits.py`, `crew.py`, `drones.py` | geometry, skinning, vertex AO |
| `paint.py` | UV atlas, rasteriser, normal bake from the full-resolution garment, images, material wiring |
| `looks.py`, `looks_gear.py` | what the atlases show (faces, hair, tailoring, armour, drones) |
| `anim.py`, `posing.py` | clips |
| `qa.py`, `lookdev.py`, `check_glb.mjs` | checks and look-development renders |

Human base body: Blender Studio "Human Base Meshes" v1.4.1 (CC0, see
`art/verse/LICENSES.md`), realistic male and female bodies at their base level only.
`fetch_base.py` downloads it into `art/verse/.cache/characters/download/` and checks the
SHA-256.

## Files

| File | Content |
|---|---|
| `SK_Officer_M.glb`, `SK_Officer_F.glb` | Officer, male 1.78 m / female 1.68 m |
| `SK_Technician.glb` | Engineering technician (male skeleton) |
| `SK_Trooper.glb` | Armoured marine, ambient patrols (male skeleton) |
| `SK_Drone_Companion.glb` | The commander's hovering companion drone (own rig + clips) |
| `SK_Drone_Utility.glb` | Ambient floor drone (own rig + clips) |
| `A_Human_M.glb`, `A_Human_F.glb` | Skeleton + every human clip, per body variant |
| `characters.json` | Manifest: models, material slots, tiers, clips, speeds, heights |

The SK files carry no animation. Clips live once per skeleton in `A_Human_<variant>.glb`;
a three.js `AnimationClip` binds tracks by node name, so one clip set drives every
character with that skeleton (`skeleton` in the manifest: `M` or `F`).

## Space and scale

- glTF 2.0 binary, +Y up, metres. The origin is on the floor between the feet.
- Every character faces **+Z** in three.js (Blender -Y).
- Rest pose: A-pose (arms ~40 degrees down), as in the base mesh.
- Skinning: at most 4 influences per vertex, normalised.
- Vertex colour `COLOR_0` holds baked ambient occlusion. three.js multiplies it with the
  material colour, so runtime tints keep the shading.

## Skeleton (25 bones, both variants)

Names are fixed. Sides use `_L`/`_R` (three.js strips `.` from node names). `_L` is the
character's left (+X in three.js when facing +Z).

```
Hips
├─ Spine ─ Chest ─┬─ Neck ─ Head
│                 ├─ Shoulder_L ─ UpperArm_L ─ ForeArm_L ─ Hand_L ─┬─ Fingers_L
│                 │                                                └─ Thumb_L
│                 └─ Shoulder_R ─ … (mirror)
├─ UpperLeg_L ─ LowerLeg_L ─ Foot_L ─ Toe_L
└─ UpperLeg_R ─ LowerLeg_R ─ Foot_R ─ Toe_R
```

Only `Hips` has a translation track; every other bone is rotation only.

## Clips (30 fps, in place, names exact)

| Clip | Loop | Length | Notes |
|---|---|---|---|
| `A_Idle` | yes | 6 s | Standing, weight shift, breathing, looks around |
| `A_Walk` | yes | 1 s (2 steps) | Move the root at `skeletons.<v>.walkSpeed` (M 1.40 m/s); feet stay planted |
| `A_Sit_Idle` | yes | 6 s | Seated upright, hands on thighs |
| `A_Sit_Type` | yes | 4 s | Seated, typing at a console |
| `A_Stand_Type` | yes | 4 s | Standing at a console, typing |
| `A_Talk` | yes | 4 s | Standing, gesturing |
| `A_Listen` | yes | 6 s | Parade rest, hands behind the back, nods |
| `A_Salute` | no | 2.4 s | Comes to attention, salutes, returns to rest |
| `A_Wave` | yes | 2 s | Right hand raised and waving ("waiting for you") |
| `A_Attention` | yes | 4 s | Standing at attention, heels together |
| `A_Sit_Down` | no | 1.5 s | Standing (feet where the seated feet go, ~0.42 m in front of the root) to seated |
| `A_Stand_Up` | no | 1.27 s | Seated to standing (ends with the feet ~0.42 m in front of the root) |
| `A_Sleep` | yes | 6 s | Lying on the back, slow breathing |

Placement conventions (all three.js axes, relative to the character root):

- **Seat**: the clip puts the buttocks on a seat surface `seatHeight` (0.46 m) above the
  root; the seat centre is 0.06 m in front of the root (+Z). Feet are flat on the floor
  about 0.45 m in front. Keyboard / typing surface: `deskHeight` (0.74 m), hands about
  0.40 m in front of the root. Put the root on the floor under the seat socket, facing
  the console.
- **Standing console**: hands on a surface `standDeskHeight` (1.02 m) high, 0.36 m in
  front of the root.
- **Bunk**: `A_Sleep` puts the root on the mattress top surface; the body lies on its
  back along the root's Z axis, head towards -Z (about 0.95 m), feet towards +Z
  (about 0.85 m). Place the root on the bunk socket at mattress height.
- **Walk**: the clip is in place; translate the root along its +Z at the walk speed.
  The female skeleton has its own (shorter) stride; use its own `walkSpeed`.

## Material slots (stable names, tint by name)

Clone the materials per character, then set colours by material name. Reference colours
per tier are in `characters.json` (`tiers`, sRGB hex; `THREE.Color.set()` converts).

| Slot | Officer | Use |
|---|---|---|
| `M_Uniform` | tunic, collar | tier colour |
| `M_Trousers` | riding trousers | tier colour (flag tier: black) |
| `M_Trim` | cuffs, front-flap seam (raised bead) | tier trim colour: a shade darker; on the `deck` tier a lighter grey, so the seam and cuffs read as the zip and cuffs of a work suit |
| `M_Accent` | shoulder-seam and collar piping | the agent's personal accent colour |
| `M_Cap` | cap (mesh `Cap`) | tier colour |
| `M_Skin`, `M_Hair` | face, hands / hair | per person |
| `M_Eye` | eyeballs (sclera, iris, pupil in the atlas) | leave |
| `M_Boots`, `M_Belt` | knee boots / belt | black leather |
| `M_RankPlate` | steel plate, buckle, cap badge | steel |
| `M_RankTile_1..6` | six pips on the plate | unlit `tileUnlit`; lit: tier tile colour (optionally `emissive`) |

- Mesh `Cap` is separate: hide it for bareheaded officers (deck tier per BRIEF §8).
- Mesh `RankPlate` holds the plate and the six pips. Pips 1–3 are the top row, 4–6 the
  bottom row, left to right as seen from the front (= `plateTiles()` slots 0–5).
  `models[].rankPlate` gives the plate centre and facing (model space, rest pose) and its
  parent bone `Chest`, for anything the runtime wants to attach there.
- Model kinds: `officer`, `technician`, `trooper`, `companion` (the pet drone), `drone`.
  Drones carry their own rig and clips inside their glb.
- Technician: `M_Uniform` (black suit), `M_Helmet`, `M_Visor`, `M_Mark`, `M_ChestBox`,
  `M_Glow` (chest-box lights), `M_Trim`, `M_Gloves`, `M_Boots`, `M_Belt`, `M_Skin`.
- Trooper: `M_Armor` (white plates, helmet, boots), `M_Undersuit`, `M_Visor`, `M_Belt`
  (utility belt and pouches), `M_Gloves`, `M_Accent` (unit band on the left upper arm).
  Plates are parametric shells with bevelled rims, each rigid on one bone.

## Using it in three.js

```ts
const sk = await loader.loadAsync(url);              // SK_*.glb
const clips = (await loader.loadAsync(clipsUrl)).animations; // A_Human_<skeleton>.glb
const actor = SkeletonUtils.clone(sk.scene);          // one per agent
actor.traverse((o) => { if (o.isMesh) o.material = o.material.clone(); });
const mixer = new THREE.AnimationMixer(actor);
mixer.clipAction(THREE.AnimationClip.findByName(clips, "A_Idle")).play();
```

## Atlases (close camera)

The follow camera shows a character about 200–260 px tall (~200 px per metre, 60° from
above), so every model carries one UV atlas shared by all its meshes, painted in 3D by
`paint.py` from `looks.py` / `looks_gear.py` (nothing hand-painted, deterministic):

| Image | Content |
|---|---|
| `T_<model>_BaseColor` | a **multiplier** on the material colour: neutral grey on tinted slots (uniform, trousers, trim, cap, accent), so `color.set()` by tier still decides the colour; skin features, eyes, hair locks, brows, lips relative to the skin/hair colour |
| `T_<model>_Normal` | tangent space (OpenGL, no tangents in the file: three.js derives the frame from screen derivatives); the undecimated garment surface baked onto the game mesh plus seams, welts, folds, stitching, panel lines, strands |
| `T_<model>_ORM` | glTF metallicRoughness: G = absolute roughness (factor 1), B = 1 (metallic stays the material's factor) |

Humans use 1024 × 1024, drones 512 × 512, all WebP inside the glb (`EXT_texture_webp`,
required; three.js r185 decodes it). Texel density is about 380 texels/m on cloth and
850 on the face and hair, i.e. two texels per screen pixel at the game camera. Details
are drawn a little bolder than life (seams 4–7 mm, brows 6–8 mm), since 1 px ≈ 5 mm.
`M_RankTile_*`, `M_Glow` and `M_Lens` stay flat colour. Material copies keep the
textures shared, so cloning per actor costs no texture memory.

The sheen of cloth slots is exported as `sheenColorFactor` ≈ 0.08 (the glTF exporter
writes the Blender sheen *tint*, not the weight; a white tint washed every uniform out).

## Budgets

≤ 15 000 triangles and ≤ 2 MB per glb (atlas included: humans ≈ 0.8–1.2 MB, drones
≈ 0.2–0.4 MB). See `characters.json` for the measured values.

Draw calls: one per material primitive. An officer is 19 primitives (body 10, cap 2,
rank plate 7), the technician 12, the trooper 6. For large crowds the runtime may merge
the six `M_RankTile_n` primitives into one material driven by a per-tile colour array.

## QA

`lookdev.py` imports the shipped glb files, dresses them as `look.ts` does and renders
with Cycles through the game camera: the lineup at 200 px/m (front and back), a close
set at 400 px/m, upper bodies at 800 px/m (`--only front,back,close,detail,detailback,gear`,
`--dir` to render another set of files, e.g. a previous build).

`build.py --qa` renders, with Cycles at the game camera (orthographic, 60 degrees below
the horizon), on a glossy black deck under overhead panels:
`art/verse/.cache/characters/qa/contact_1x.png` (96 px/m), `contact_3x.png` (288 px/m)
and `walk_filmstrip.png`. `check_glb.mjs` loads every file with three.js and checks bones,
clip bindings, triangle counts, facing, floor contact, sitting height, walk foot slide and
that every model carries its three atlas images with UVs on every textured primitive
(Node cannot decode images, so the atlases are stripped before three.js parses a file).
The atlases are also written as PNG to `art/verse/.cache/characters/atlas/`.
