# Verse content pipeline

How a deck of the Verse goes from reference to the running app. The Verse is a
pre-rendered plate per deck (path traced in Blender Cycles through one fixed
orthographic camera) with realtime actors drawn into it by three.js. Blender is
the level editor, the cook is the build, the browser is the engine.

Source of truth is code: Blender Python builders under `art/verse/`. `.blend`
files, downloaded textures and scratch renders are derived data in
`art/verse/.cache/` (git-ignored). Only builders, tools and the cooked output
under `dodaios/ui/web/frontend/public/verse/` are committed.

## Stages

| # | Stage | Output | Tool / owner |
|---|---|---|---|
| 1 | Reference | `art/verse/style-bible.md`, contact sheet | ref-research |
| 2 | Blockout (graybox) | `art/verse/decks/<id>/build.py` with primitives, sockets, rooms, UCX proxies; cooked with `--quality preview` | level builder |
| 3 | Kit | Modular pieces and materials on the 1.2 m grid (`lib/kit.py`, `lib/materials.py`, `kit/architecture/**`) | kit-artist |
| 4 | Set dressing | Kit pieces and props replace the primitives in the builder | level builder |
| 5 | Lighting build (cook) | Plate tiles, nav grid, occluders, env map, probes, manifest | `scripts/verse/cook.py` |
| 6 | Runtime import | `content/manifest.ts` parses the manifest; the engine streams tiles and places actors | engine |
| 7 | QA gates | Validator, unit tests, visual check in the app against the contact sheet | `scripts/verse/validate.py`, `tests/verse/` |
| 8 | Ship | Final cook committed, `dist` rebuilt by the coordinator | coordinator |

## Folder layout

```
art/verse/
  BRIEF.md TEAM.md LEVELS.md style-bible.md LICENSES.md
  lib/        scene.py cook.py naming.py textures.py   (pipeline)
              kit.py materials.py                      (kit)
  kit/        modular pieces            lookdev/  material tests
  decks/<id>/ build.py (+ helpers)      characters/  character builders
  schema/     deck.schema.json
  .cache/     blend/ cook/ textures/ logs/ mcp/ notes/ gpu.lock   (git-ignored)
scripts/verse/  blender.py cook.py package.py validate.py closeup.py mcp_bridge.py textures.py avif_test.py
tests/verse/  test_verse_content.py
dodaios/ui/web/frontend/public/verse/decks/<id>/   cooked deck (committed)
dodaios/ui/web/frontend/src/components/society/verse/content/manifest.ts
```

## Naming

| Prefix | Meaning | Where |
|---|---|---|
| `LV_<deck>` | Deck level: scene and root collection | Blender |
| `SM_<Piece>_<n>` | Static mesh (placed kit piece or primitive) | Architecture, Props, Ceiling |
| `SK_` | Skeletal mesh (characters, `.glb`) | `public/verse/characters/` |
| `A_` | Animation clip | characters |
| `M_` / `MI_` | Material / material instance | Blender materials |
| `T_<name>_BC` `_N` `_ORM` | Texture: base colour, normal, occlusion-roughness-metal | baked textures |
| `UCX_<id>` | Occluder proxy: simplified closed mesh, depth only, never rendered | Occluders |
| `SOCKET_<kind>_<id>` | Attachment point (empty); kinds: screen, seat, stand, bunk, holo, light, door, spawn, lift, station, waypoint | Sockets |
| `ROOM_<id>` | Flat room polygon with a `name` property | NavOnly |
| `LT_` | Light object | Lights |
| `BP_` | Runtime actor (three.js side) | engine |

Socket ids are unique per kind (`SOCKET_seat_console_a` and
`SOCKET_screen_console_a` may coexist). Names are checked by `lib/naming.py`,
the cook and the validator.

## Coordinates and camera

- Metres. three.js: X = screen right, Y = up, Z = toward the camera.
  Blender: X = X, Y = −Z, Z = Y. Builders work in Blender axes; manifests are
  in three.js axes.
- Plate camera: orthographic, pitch 60° below the horizon, yaw 0. Right
  `R = (1, 0, 0)`, up `U = (0, cos 60°, −sin 60°)`, forward
  `D = (0, −sin 60°, −cos 60°)`. A world point P maps to plate metres
  `u = (P − C)·R`, `v = (P − C)·U` and to L0 pixels
  `x = W/2 + u·ppm`, `y = H/2 − v·ppm` (`worldToPlatePx` in `manifest.ts`).
- `C` is the floor point (y = 0) at the plate centre. The frame is the
  smallest 16-px-aligned rectangle that shows the deck bounds (ground
  rectangle, lowest floor to highest wall top) plus 0.5 m.

## Deck scene contract

`lib.scene.new_deck(deck_id, Bounds(...), name=..., floor=..., exposure=...)`
resets the file and creates `LV_<deck>` with child collections:

| Collection | Contents | Plate camera | Nav |
|---|---|---|---|
| Architecture | Floors, walls, structure | visible | yes |
| Props | Consoles, furniture, machinery | visible | yes |
| Lights | Light objects (fixtures you can point at) | — | no |
| Ceiling | Ceilings, light fixtures above eye level and the cut-away upper parts of walls | **hidden** (still lights, shadows, reflects, and shows in env/probe panoramas) | no |
| Occluders | `UCX_*` proxies | not rendered | no |
| Sockets | `SOCKET_*` empties | not rendered | no |
| NavOnly | `ROOM_*` polygons | not rendered | no |

Custom properties (set with `scene.tag()`):

- `nav`: `walk` (floor surface), `block` (obstacle, default for meshes in
  Architecture/Props), `none` (ignored by nav, e.g. hull structure, decals).
- `room`, `station`, `station_kind` on objects and sockets. A station is a
  `SOCKET_station_<id>` with a `station_kind` (engine's `STATION_KINDS`);
  other sockets join it with `station=<id>`.
- Screens: `scene.add_screen()` creates `SOCKET_screen_<id>` with `size_w`,
  `size_h`; the empty's local XY plane is the screen, +Z its normal.
- Socket facing is the empty's local −Y. yaw 0 faces three +Z (the camera),
  90 faces screen right (+X). One rule for every kind: the character's root
  takes the socket's position and yaw. Seats face their console (usually
  180) and sit on the cushion top (hip point, ~0.46 m); bunks sit on the
  mattress top centre with the yaw pointing from head to feet (the sleep
  clip lies with the head at the root's back, −Z); stands and spawns sit on
  the floor. `props.approach = [x, z]` is an optional walk-in point.
- Kit placements join placement and local ids with a double underscore
  (`SOCKET_seat_brief__01`).
- Rooms: `ROOM_<id>` with `name`, optionally `main=True` (env map location)
  and `probe_at=(x, y, z)` (Blender metres) when the centroid is a bad probe
  spot; other properties (e.g. `kind`) are exported as `rooms[].props`.

Cutaway (BRIEF §5): east–west walls with walkable space behind them are built
1.1 m high with the section cap on top. Their upper part goes into `Ceiling`
with `visible_shadow = False`: floor reflections and the character env map
still see a closed room, and the cap below it still receives light (with
shadows on, the hidden wall sits on the cap and it renders black, reading as
void). Kit `*_Cut` pieces carry this upper part as a ghost object inside their
instanced master collection, marked with the custom property
`ceiling_ghost=True`; the cook treats those exactly like `Ceiling` objects.
Upward faces at ceiling height (tops of full-height pillars and walls) get no
light at all; give them the section-cap material and keep them thin.

Helpers in `lib/scene.py`: `link`, `tag`, `add_socket`, `add_screen`,
`add_room`, `add_ucx_box`, `add_ucx_from_bounds`, `add_area_light`
(temperature in kelvin), `collection`, `objects_in`. Lookdev scenes that are
not decks render like a cook with `configure_render(scene, quality, exposure)`
and `plate_camera(scene, Bounds(...), px_per_m)`.

## Cook

```
python scripts/verse/cook.py deck <id> [--quality preview|final] [--keep-blend] [--device auto|optix|cuda|cpu]
```

1. Headless Blender (`scripts/verse/blender.py`, GPU lock) runs
   `art/verse/decks/<id>/build.py::build()`, optionally saves
   `art/verse/.cache/blend/LV_<id>.blend`, then `lib.cook.cook_deck()` writes
   raw output to `art/verse/.cache/cook/<id>/<quality>/`.
2. `scripts/verse/package.py` encodes and writes
   `public/verse/decks/<id>/` atomically (staging directory, then rename).
3. The validator checks the result; a failing deck stops the command.

| Quality | Density | Samples (adaptive) | Use |
|---|---|---|---|
| preview | 48 px/m | 96, threshold 0.03 | iteration |
| final | 192 px/m | 192, threshold 0.02 | committed content |

The final density is set by the runtime's close third-person camera: it shows
the plate at up to ~200 CSS px per metre (a 1.8 m figure ~220 px tall on a
1392 px high window), so L0 is drawn about 1:1 there; the tile pyramid below
serves the wider views. A plate pixel is 5 mm, which is why the floor paint
wear (`materials.paint_wear`) uses a crisp edge: a soft threshold leaves
half-transparent paint that reads as grey clouds at full zoom.

Close-ups before a long cook: `python scripts/verse/closeup.py <id> <out_dir>
--socket spawn/commander --socket station/<id> [--three x,y,z] [--px x,y]
[--size 1600x900] [--samples N --threshold T]` builds the deck and renders just
those windows exactly as the cook would (same density, settings, denoiser,
glow, AgX and dither) to `<out_dir>/<name>.png`, in ~15–20 s per 1600 × 900
window.

Render settings: Cycles on OptiX (CUDA, then CPU fallback), OptiX denoiser
with albedo + normal, fixed seed 0, 12 bounces (glossy 6, diffuse 4), indirect
clamp 8, auto tiles of 2048 px, persistent data between regions, black world
(all light comes from fixtures). Colour: **AgX, look None** — the actors use
three.js `AgXToneMapping` (the same curve) with
`toneMappingExposure = 2^exposure`, so characters match the plate; contrast is
a lighting decision, not a look.

Plate assembly (`lib/plate_post.py`): a full-frame GPU denoise of a
100 × 62 m deck (9696 × 5616 px) needs ~8.6 GB extra VRAM, so the plate is
rendered as border regions of at most 4096 px with a 64 px overlap that is
cropped (one region for plates up to 3968 px). Each region is a half-float
scene-linear EXR. The glow (bloom: threshold 1.0, strength 0.12, three
Gaussian radii 0.04 / 0.15 / 0.5 m) is computed once for the whole plate at
quarter resolution and added back per region, so seams and density do not
change it. Blender's view transform then turns each region into 16-bit
display values, which get triangular dither before 8-bit quantisation; the
packager stitches the regions. Measured on a 9696 × 5616 frame: 6 regions,
peak VRAM +4.5 GB over the desktop's baseline (was +8.6 GB full-frame), no
measurable seam against a full-frame render. The env map and probes get no
glow.

Outputs per deck:

| File | Content |
|---|---|
| `manifest.json` | schema `verse.deck/1` (`art/verse/schema/deck.schema.json`) |
| `plate/L0_{col}_{row}.avif` | full density (`px_per_m`), 2048 px tiles (edge tiles smaller) |
| `plate/M2_{col}_{row}.avif` | mip level: the plate downscaled by 2 (Lanczos on the 8-bit plate), cut into 2048 px tiles |
| `plate/M4_{col}_{row}.avif` | mip level: downscaled by 4, 2048 px tiles |
| `plate/L1.avif` | whole plate at 1/8 (~24 px/m at the final density), one image |
| `nav.png` | 8-bit grey, 0.2 m cells, row 0 = far (−Z) edge; 0 = blocked, else floor y = (v − 128) · 0.025 m; already eroded by the 0.25 m body clearance |
| `occluders.glb` | all `UCX_*` merged into one mesh, positions only, +Y up |
| `env.hdr` | 512 × 256 Radiance equirect at the main room, 1.4 m (three.js layout: centre column +X, then +Z) |

Nav rasterisation: vertical rays per 1/3 cell; a cell is walkable when every
sample finds a `walk` surface (the highest one) and no `block` solid occupies
0.15–2.0 m above it, and its samples differ by at most 0.3 m. Neighbours with
a larger height jump are not connected (platform and pit edges); steps up to
0.3 m are. The walkable area is then eroded by a 0.25 m body radius
(`nav.clearance`): a cell stays walkable only if every cell the body disc
overlaps is walkable and within 0.3 m of its height, so crew never clip walls
or hang over drops. One walk level per cell (`lib/navgrid.py`). Walk surfaces
and solids are cast against separate ray trees, so a solid standing flush on
the floor (sill, inlay, wall bottom) never hides the floor under it.

Light probes: one per room at `probe_at` or the room centre, 1.4 m above its floor; a 64 × 32
panorama projected to 9 RGB radiance coefficients in three.js
`SphericalHarmonics3` order (`lightProbe.sh.fromArray(sh.flat())`).

Plate pyramid (manifest `plate`, schema `verse.deck/1`, backwards
compatible): `tile_px`, `cols`, `rows`, `tile_url` describe L0;
`mips` lists the tiled levels finest first, each `{divisor, w_px, h_px, cols,
rows, tile_url}` with `w_px = round(plate_w_px / divisor)`,
`cols = ceil(w_px / tile_px)`; `l1_url`, `l1_w_px`, `l1_h_px` describe the
overview (`round(plate_w_px / 8)`). Manifests cooked before the pyramid have
no `mips` and an L1 at 1/4; the runtime still reads them, the validator asks
for a recook. The engine picks the level to stream per zoom
(`engine/tileStreamer.ts`).

Measured final cooks (192 px/m, 192 samples, RTX 5070 Ti shared with the
desktop; plate = L0 + M2 + M4 + L1 on disk):

| Deck | Plate px | Regions | Plate render | Whole cook | Plate |
|---|---|---|---|---|---|
| bridge | 14016 × 8096 | 12 | 11 min | 13 min | 2.7 MB |
| ops | 18624 × 10688 | 15 | 26 min | 30 min | 3.7 MB |
| engineering | 16320 × 10432 | 15 | 20 min | 23 min | 3.6 MB |
| hangar | 19392 × 12240 | 20 | 27 min | 30 min | 3.5 MB |

L0 is ~60 % of a plate, M2 ~25 %, M4 ~10 %, L1 ~4 %; packaging (stitch,
plate.png, 80+ AVIF tiles) takes 1.5–3 min. Sample count was chosen against a
1024-sample, threshold 0.004 reference of the same windows: 160–256 samples
are within 48–51 dB PSNR and visually identical at 1:1 (the streaks in floor
reflections are the coat's wipe marks, not noise).

AVIF: quality 72, speed 4, 4:4:4 (indicator lights stay crisp; 4:2:0 saves
only ~1 %); at 192 px/m a busy bridge L0 tile keeps 48.9 dB luma PSNR.
Measure on a real plate with
`python scripts/verse/avif_test.py art/verse/.cache/cook/<id>/final/plate.png`
and keep luma PSNR ≥ 44 dB.

Reproducibility: fixed seeds and settings. Two final cooks of the testbed gave
identical manifests apart from `stats` and probe coefficients in the fifth
decimal, and plates within 1/255 on 0.5 % of the pixels (GPU float order), so
compare plates with a tolerance, never byte for byte. Measured on the testbed
at the former 96 px/m final density (26 × 17.7 m frame, 2592 × 1696 px,
RTX 5070 Ti): final plate render 31–35 s
(longer while the GPU is shared), whole cook ~40 s, 0.43 MB on disk; preview
4–10 s. A 100 × 62 m frame at 64 samples renders in ~33 s.

## Adding a deck (multi-floor)

1. Add the id to `DECK_IDS` in `src/components/society/verse/decks.ts` (deck
   order = floor order) and the layout to `art/verse/LEVELS.md`.
2. Create `art/verse/decks/<id>/build.py` with `build()`: call
   `scene.new_deck(<id>, Bounds(...), name=..., floor=<n>)`, place kit pieces,
   add rooms (one `main=True`), sockets (a lift lobby with
   `SOCKET_lift_main`, a `station` of kind `lift`, a spawn), and UCX proxies
   for everything that can hide a character (walls, consoles, pit rims).
3. Iterate: `python scripts/verse/cook.py deck <id> --quality preview --keep-blend`,
   inspect the .blend through the MCP bridge, then cook `final`.
4. `python scripts/verse/validate.py` and `pytest tests/verse` must pass.

No other file changes: the engine discovers decks by id and manifest.

## Budgets and gates

| Gate | Limit | Checked by |
|---|---|---|
| Whole `public/verse` | ≤ 90 MB | validator, pytest |
| Plate per deck (L0 + M2 + M4 + L1) | ≤ 16 MB | validator |
| Character `.glb` | ≤ 2 MB each, `SK_`/`SM_`/`A_`/`T_` prefix | validator |
| Manifest | JSON Schema, ids match folders, tile count and sizes of every level (mips per the contract, no stray files), nav size, occluders without materials and named `UCX_*`, env is Radiance HDR | validator |
| References | sockets → rooms and stations, stations → sockets, probes → rooms, unique ids | cook + validator |
| Framing | every socket and screen corner inside the plate | cook + validator + pytest |
| Visual | Plate checked against the contact sheet; app checked in Chrome | QA |

`python scripts/verse/validate.py` (CI: `pytest tests/verse`, no Blender).

## Blender

- Headless: `python scripts/verse/blender.py run [--blend F] [--no-lock] <script.py> [args]`
  (`info` prints the device). `--factory-startup -b`; `art/verse` and
  `scripts/verse` are on `sys.path`; an exception inside Blender exits 1; heavy
  jobs wait for `art/verse/.cache/gpu.lock`. `DODAIOS_BLENDER` overrides the
  executable.
- Interactive (agents): `scripts/verse/mcp_bridge.py` talks to the Blender MCP
  add-on's local TCP server.

```
python scripts/verse/mcp_bridge.py --port 9877 launch --blend art/verse/.cache/blend/LV_<id>.blend
python scripts/verse/mcp_bridge.py --port 9877 exec my_edit.py        # bpy code; `from lib import scene` works
python scripts/verse/mcp_bridge.py --port 9877 scene
python scripts/verse/mcp_bridge.py --port 9877 screenshot out.png --camera --shading material
python scripts/verse/mcp_bridge.py --port 9877 stop
```

  `launch` opens Blender with its GUI (user add-ons load; the add-on is
  enabled for that session only) and waits until the server answers;
  `--camera` looks through the plate camera and hides `Ceiling` in the
  viewport. Edits made this way are not source: port them into the builder.
- MCP server for Claude Code sessions: registered at user scope on the
  production machine with every telemetry switch off:
  `claude mcp add blender --scope user -e DISABLE_TELEMETRY=true
  -e BLENDER_MCP_DISABLE_TELEMETRY=true -- uvx blender-mcp`. Without those
  variables the server sends anonymous usage data even when the add-on's
  "Allow Telemetry" preference is off; keep that preference off too. Start
  Blender with the add-on's server running (`mcp_bridge.py launch`) before a
  session uses the `blender` tools.

## Third-party content

CC0 only. `from lib import textures; textures.ensure(asset, maps, res)` (or
`python scripts/verse/textures.py <asset> --maps Diffuse nor_gl Rough`) fetches
from the Poly Haven API with this pipeline's own User-Agent, verifies the MD5,
caches under `art/verse/.cache/textures/<asset>/` and appends the file, URL
and SHA-256 to `art/verse/LICENSES.md` once. Textures courtesy of Poly Haven
(polyhaven.com).
