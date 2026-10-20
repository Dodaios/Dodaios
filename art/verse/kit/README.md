# Verse kit

The modular kit every deck is assembled from: `lib/kit.py` (registry,
placement, sockets, occluders, mesh building), `lib/materials.py` (the
Cycles material library) and the architecture pieces in
`kit/architecture/`. Props live in `kit/props/` and use the same API.

The APIs below are stable. New pieces and materials are added; existing
names, signatures and conventions do not change without a note here.

## Conventions

- **Axes (Blender):** X = bow, Z = up, -Y = toward the plate camera
  (three.js +Z). Metres. The plate camera looks down at 60 degrees, yaw 0.
- **Piece space:** centred on X, floor at Z = 0. Wall-like pieces have their
  room face on the plane Y = 0 facing -Y; the body extends toward +Y.
  Place a near (camera-side) wall with `rot_z_deg=180`, a west wall facing
  east with `90`, an east wall facing west with `-90`.
- **Module:** 1.2 m. Widths are 1.2 / 2.4 / 4.8 m; names carry centimetres
  (`SM_Wall_240`). Heights other than the default carry `_H<cm>`.
- **Cutaway (BRIEF section 5):** a `_Cut` variant stops at 1.1 m with a
  `M_Section_Cap` top. Above it sits a *ceiling ghost* of the full piece
  (see `kit.ghost`): invisible to the camera and to shadow rays, it still
  mirrors in the black floor, emits light where it has fixtures and closes
  the room for env/probe renders. Ghost objects carry `ceiling_ghost=True`
  and `nav="none"`; they never emit sockets or occluders. The cook hides
  every object in the `Ceiling` collection or with a truthy `ceiling_ghost`
  from the plate camera and shows them for env/probe panoramas; because
  ghosts live in the `KIT_MASTERS` sources, that covers every instance.
- **Ceilings** and their light panels are always `visible_camera=False`.
- **Custom properties** read by the cook: `room`, `nav` (`walk`, `block`,
  `none`), `station`, `station_kind`, plus `piece` (on placements) and
  `owner` (on sockets and occluders).
- **Nav:** floors, stairs, catwalks, gratings and walkways are `walk`; hull
  bays, decals, ceilings and ghosts are `none`; walls, consoles, doors and
  pillars are `block`.
- **Sockets:** `SOCKET_<kind>_<id>`, kinds from `lib.naming.SOCKET_KINDS`.
  Seat, stand, spawn and waypoint sockets: the character faces the empty's
  local -Y (`kit.facing_matrix(loc, facing_deg)`: 0 = toward the camera,
  180 = away from it, i.e. toward a console). Screen sockets: local XY is
  the screen plane, +Z its normal, `size_w`/`size_h` in metres
  (`kit.screen_matrix(center, tilt_deg, yaw_deg)`). Same conventions as
  `lib.scene.add_socket` / `add_screen`.
- **Socket ids** of placed pieces are `<placement id>__<local id>`. An `id`
  that starts with `_` inside a piece builder is anonymous, so
  `place("SM_ConsoleStation", ..., id="pit_p_1")` yields
  `SOCKET_screen_pit_p_1`, `SOCKET_seat_pit_p_1`, `SOCKET_stand_pit_p_1`.
- **Collections:** placements go to the current collection (`kit.into`).
  Sockets, `UCX_` occluders and `ROOM_` polygons go to the deck's `Sockets`,
  `Occluders` and `NavOnly` collections whenever the scene was made by
  `lib.scene.new_deck`. Piece masters live in `KIT_MASTERS` (excluded from
  the view layer) and are placed as collection instances.

## `lib/kit.py`

```python
from lib import kit
from kit import architecture
architecture.load_all()                    # registers every architecture piece

with kit.into(scene.collection("Architecture")):
    kit.place("SM_Wall_480", (0.0, 5.7, 0.0), 0.0, room="bridge")
    kit.place("SM_ConsoleStation", (3.0, 4.2, -1.4), 0.0, room="bridge",
              id="pit_p_1", station="pit_p_1", station_kind="agents_list")
```

| Function | Purpose |
|---|---|
| `@kit.piece(name, dims=(x, y, z), nav="block", **params)` | register a builder function as a piece |
| `kit.register_variant(name, fn, dims=..., nav=..., **params)` | register a sized variant of a builder |
| `kit.place(name, location, rot_z_deg=0, room=None, *, id=None, scale=None, realize=False, collection=None, nav=None, station=None, station_kind=None, **props)` | place an instance; emits its sockets and occluders in world space; returns the instancer empty |
| `kit.build_master(name)` | build a piece's master collection (done by `place`) |
| `kit.registry()` | `{name: PieceDef}` with `dims`, `nav`, `sockets`, `occluders` |
| `kit.socket(kind, id, matrix_world, **props)` | socket empty (recorded as a local spec inside a builder) |
| `kit.occluder(obj_or_bbox, name=None, **props)` | `UCX_` depth proxy from a mesh or `((min), (max))` |
| `kit.room(id, name, polygon, z=0, **props)` | `ROOM_<id>` floor polygon (prop `name`) |
| `kit.tag(obj, room=, nav=, station=, station_kind=, **extra)` | set cook properties (None skipped) |
| `kit.facing_matrix(loc, facing_deg)`, `kit.screen_matrix(center, tilt_deg, yaw_deg)`, `kit.socket_matrix(loc, normal, up)` | socket matrices |
| `kit.bevel(obj, width, segments, angle_deg, harden=True)` | angle-limited bevel + hardened normals |
| `kit.MeshBuilder(matrix=None)` | `.box(lo, hi, mat)`, `.box_c(center, size, mat)`, `.prism_x(profile_yz, x0, x1, mat)`, `.prism_y(profile_xz, y0, y1, mat)`, `.prism_z(poly_xy, z0, z1, mat)`, `.tube(p0, p1, r, mat)`, `.polyline_tube(...)`, `.quad(corners, mat)`, `.build(name, bevel_width=0.006, segments=2, angle_deg=30, recalc_normals=True, **props)` |
| `kit.mesh_object(name, verts, faces, mat, bevel_width=0, **props)` | single mesh, winding kept |
| `kit.emissive_panel(name, center, (w, h), mat, normal="-Z", camera_visible=True)` | fixture face |
| `kit.hide_from_camera(obj)` | ceiling convention |
| `kit.ghost(clip_z)` | context: build the cut-away upper part (see above) |
| `kit.into(collection_or_name)`, `kit.ensure_collection(name)`, `kit.link(obj)` | collection helpers |
| `kit.seed_for(*parts)` | stable seed (never Python's `hash`) |

## `lib/materials.py`

`materials.get("M_Name")` builds a material once per file and returns it;
`materials.names()` lists them; `materials.build_all()` builds all. No
material needs UVs: surfaces use instance-local object coordinates in real
metres with a per-instance offset (and per-island variation), floors use
world space so plate seams run on one global grid. CC0 scans come from
`lib.textures` (`lookdev/fetch_textures.py`); without them the procedural
layers carry the detail. Emission strengths and their real-world anchors
are in the module docstring. `VERSE_MATERIAL_QUALITY=preview` drops the
ray-traced AO and Bevel nodes.

| Group | Names |
|---|---|
| Floors | `M_Floor_GlossBlack` (black mirror deck, light joint lines), `M_Floor_SatinDark`, `M_Floor_Grating` |
| Walls | `M_Wall_Charcoal` (hero), `M_Wall_PaintedLight` (#9EA3A8), `M_Wall_PaintedMid`, `M_Wall_PaintedDark`, `M_Ceiling_Panel`, `M_Recess_Dark`, `M_Section_Cap` |
| Metal, rubber | `M_Struct_Gunmetal`, `M_Trim_BrushedSteel`, `M_Trim_Chrome`, `M_Rubber_Black` |
| Light fixtures | `M_Light_CeilingPanel` (16), `M_Light_WallStrip` (24), `M_Light_Backlit` (9), `M_Light_FloorInlay` (10), `M_Light_RedTrim` (5), `M_Light_Maint_Red`, `M_Light_Maint_Amber` (4), `M_Emit_BacklitPanel` (2.6) |
| Indicators | `M_Indicator_Red`, `_Green`, `_Amber`, `_Blue`, `_White` |
| Consoles, glass | `M_Console_Body`, `M_Console_Deck`, `M_Console_Keys`, `M_Screen`, `M_Glass_Viewport`, `M_Glass_Clear`, `M_Starfield` |
| Furniture | `M_Lacquer_BlackGloss`, `M_Plastic_BlackSatin`, `M_Plastic_LampOff`, `M_Plastic_MedWhite`, `M_Fabric_BunkGrey`, `M_Paint_TrimRed`, `M_Seat_Upholstery`, `M_Crate_Paint` |
| Markings | `M_Deck_Marking_White`, `M_Deck_Hazard` (thin worn bands only) |
| Hull | `M_Hull_Structure`, `M_Hull_Pipe`, `M_Hull_PipeInsulated` |

## Architecture pieces

Dimensions are X x Y x Z in metres (nominal footprint).

| Piece | Size | Sockets | Notes |
|---|---|---|---|
| `SM_Wall_120/240/480` | w x 0.3 x 4.5 | | hero wall: light columns + grilles |
| `SM_Wall_*_H540` | w x 0.3 x 5.4 | | taller hero wall |
| `SM_Wall_*_Cut` | w x 0.3 x 1.1 | | + ghost |
| `SM_WallLight_120/240/480` (+`_H540`, `_Cut`, `120/240_Hatch`) | w x 0.3 x 4.5 | | light-grey panelling, hidden light channel |
| `SM_Wall_Corner` (+`_Cut`) | 0.3 x 0.3 | | |
| `SM_CorridorWall_240/480` (+`_Cut`) | l x 0.9 x 3.6 | | chamfered profile, floor edge at Y = 0 |
| `SM_Corridor_240/480` | l x 5.4 x 3.6 | | floor 3.6 m clear, far wall full, near cut, ceiling + lights |
| `SM_Corridor_240/480_Full` | l x 5.4 x 3.6 | | both walls full (corridor along the camera axis, rot 90) |
| `SM_Corridor_Junction` | 6 x 6 | | four pilasters |
| `SM_Bulkhead_Pilaster` (+`_Cut`) | 0.9 x 0.9 | | junctions, door jambs |
| `SM_Bulkhead_Frame_Corridor` (+`_Cut`) | 0.3 x 5.4 | | ring around a corridor |
| `SM_BlastDoor_240` (+`_Closed`, `_Cut`, `_Cut_Closed`) | 3.6 x 0.6 x 4.5 | door | opening 2.4 x 3.0 |
| `SM_Turbolift_Door` | 2.4 x 0.42 x 4.5 | lift, spawn | far walls |
| `SM_Turbolift_Lobby_480` | 4.8 | lift, spawn x2 | |
| `SM_Viewport_240/480` | w x 1.3 x 4.5 | | far walls; star field inside the glass |
| `SM_GlassPartition_120/240/480` (+`_Cut`) | w x 0.2 x 4.5 | | glazed partition |
| `SM_PitWall_120/240` | w x 0.3 x 1.4 | | place at pit floor height |
| `SM_Console_Pit` | 1.1 x 0.78 x 1.16 | screen | origin back-bottom, front -Y |
| `SM_Seat_Crew` | 0.5 x 0.5 x 1.05 | | faces -Y |
| `SM_ConsoleStation` | 1.1 x 2.0 | screen, seat, stand | console + seat |
| `SM_CrewPit_240` (+`_RailFar`) | 2.4 x 4.2, 1.4 deep | 2x screen/seat/stand | origin at walkway level |
| `SM_CommandWalkway_240` | 2.4 x 4.8 | | edge inlays |
| `SM_Stairs_120/240_H060/H140` | run x w | waypoint x2 | one solid flight, descends toward +X |
| `SM_Railing_120/240` | l x 0.12 x 1.0 | | |
| `SM_Catwalk_240` | 2.4 x 1.2 | | grated, no rails |
| `SM_Pillar_120` (+`_Cut`) | 1.2 x 1.2 | | |
| `SM_Grating_120` (+`_Lit`) | 1.2 x 1.2 | | trench with pipes below |
| `SM_CeilingLight_Grid_480` | 4.8 x 4.8 | | camera-invisible |
| `SM_Hull_Bay_A/B/C/D`, `SM_Hull_Bay_LampRed/LampWhite` | 2.4 x 2.4, 2.4 deep | | below deck level only |

Area functions: `floors.fill_floor(name, polygon, z, room=, material=,
nav=)`, `floors.fill_rect(...)`, `floors.inlay_strip(name, p0, p1)`,
`floors.marking(name, x0, y0, x1, y1, hazard=)`;
`ceiling.fill_ceiling(room_id, x_range, y_range, z, pitch, size)` (emits
`SOCKET_light_<room>_ceiling`), `ceiling.ceiling_slab`, `ceiling.panel_grid`,
`ceiling.light_panel`; `hull.fill_hull(prefix, x_range, y_range)`.

Custom heights or widths: register a variant of the builder, e.g.
`kit.register_variant("SM_Wall_480_H1200", walls.build_wall, width=4.8, height=12.0)`.

## Lookdev

- `lookdev/hero_vignette.py` - the production benchmark (corridor junction,
  crew pit, hero wall, viewports, hull framing).
- `lookdev/kit_sheet.py` - every piece in a labelled lineup;
  `--build-only` validates all pieces and prints sizes, sockets, occluders.

Both run through `scripts/verse/blender.py run <script> --out <png> --ppm 96`.
Renders and notes go to `art/verse/.cache/lookdev/` and
`art/verse/.cache/notes/kit-artist-lookdev.md`.
