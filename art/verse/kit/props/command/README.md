# Command props

Consoles, tables, seats and crew fittings for the Verse decks (bridge, ops,
engineering, hangar booths). Blender Python builders; importing the package
registers every piece with the kit registry:

```python
import kit.props.command  # noqa: F401
from lib import kit

kit.place("SM_Console_CrewPit", (x, y, 0), 0.0, room="bridge_pit_p", id="pit_p_1")
kit.place("SM_Console_Command", (36, -7, 0), 0.0, room="walkway",
          id="command", station="command", station_kind="agents_list")
```

## Conventions

- **Axes** (kit, BRIEF section 4): Blender X = screen right, -Y = toward the
  plate camera, Z = up, floor at Z = 0. Real-world metres.
- **Anchor**: every prop is centred on its footprint in X and Y. Wall props
  (`SM_Terminal_Wall`, `SM_Board_Rank`, `SM_Dispenser`, `SM_Lockers_Uniform`)
  put their back on local Y = 0 (the room face of a wall piece) and extend
  toward -Y, so they take the same location and rotation as the wall.
- **Facing**: consoles, terminals, counters and boards face the camera
  (their screens look toward -Y and up); the operator stands or sits on the
  -Y side facing +Y and is seen over the shoulder (BRIEF section 5).
  The commander's desk is the exception: the commander sits behind it,
  facing the camera.
- **Sockets** face their local **-Y** (the cook reads yaw from -Y, like
  `lib.scene.add_socket`), +Z up. `SOCKET_seat` sits on the cushion top at
  0.46 m (hip point). `SOCKET_screen` has +Z = screen normal, +Y = screen up,
  `size_w`/`size_h` = the glass. `SOCKET_bunk` lies on the mattress top,
  local -Y toward the feet (the head lies toward local +Y). `SOCKET_holo` sits on the emitter lens with
  `radius`/`height` of the projection volume.
- **Socket ids**: single-operator pieces use the local id `""`, so the
  placement id becomes the socket id (`id="pit_p_1"` gives
  `SOCKET_seat_pit_p_1`, `SOCKET_screen_pit_p_1`, `SOCKET_stand_pit_p_1`).
  Multi-seat pieces add `__01`, `__02`... (clockwise on the plate, starting
  with the left-most seat on the camera side).
- **Stations**: pieces meant as stations carry a `SOCKET_station` with local
  id `""` at the commander's use spot. Pass `id=X, station=X,
  station_kind=K` to `place()` so the cook's station has members.
- **Occluders**: `UCX_` boxes/prisms for bodies, hoods, table tops and every
  chair back (so a seated character disappears behind it correctly).
- **Materials**: role constants in `_base.py`, resolved through
  `lib.materials.get`; roles the library does not have yet get a `TMP_`
  stand-in built from `_base._SPECS`.

## Lookdev

```
python scripts/verse/blender.py run art/verse/kit/props/command/sheet.py -- [--pieces A,B] [--no-crop]
python art/verse/kit/props/command/compose_sheet.py
```

Renders every piece alone through the plate camera (orthographic, 60 degrees,
yaw 0) at 96 px/m and a 3x crop, on the black gloss deck under the kit's
ceiling light grid. Output (git-ignored): `art/verse/.cache/lookdev/props-command/`
(`sheet_game.png`, `sheet_crop.png`, per-piece PNGs, `pieces.json` with
measured dims and sockets).

## Pieces

Measured dims (bounding box incl. chairs) and sockets by local id; `''` means
the placement id itself (`SOCKET_<kind>_<id>`), others become
`SOCKET_<kind>_<id>__<local>`. Anchors: `centre`, `wall` (see above) and
`design` (the piece keeps a deck contract's origin, see below).

| Piece | W x D x H (m) | Anchor | Sockets |
|---|---|---|---|
| `SM_Console_CrewPit` | 0.92 x 1.62 x 1.21 | centre | screen ''; seat ''; stand '' |
| `SM_Console_CrewPitB` | 0.92 x 1.62 x 1.21 | centre | screen ''; seat ''; stand '' |
| `SM_Console_CrewPitDouble` | 1.84 x 1.62 x 1.21 | centre | screen 1 2; seat 1 2; stand 1 2 |
| `SM_Console_Standing` | 1.00 x 0.63 x 1.39 | centre | screen ''; stand '' |
| `SM_Terminal_Wall` | 0.84 x 0.30 x 1.32 | wall | screen ''; stand '' |
| `SM_Console_Command` | 3.28 x 1.18 x 1.39 | centre | screen c l r; station ''; stand '' |
| `SM_Console_MasterSystems` | 6.20 x 0.95 x 2.62 | centre | screen 1 2 3 d1 d2 d3 d4; station ''; stand d1 d2 d3 d4 |
| `SM_Terminal_Desk` | 1.35 x 1.54 x 1.29 | centre | screen ''; seat ''; stand '' |
| `SM_Terminal_Engineering` | 2.40 x 1.88 x 1.50 | design | screen ''; seat ''; stand '' |
| `SM_Terminal_EngineeringFill` | 2.40 x 1.10 x 1.50 | design | - |
| `SM_Terminal_EngineeringFillShort` | 1.80 x 1.10 x 1.50 | design | - |
| `SM_Terminal_EngineeringEnd` | 0.12 x 1.12 x 1.56 | design | - |
| `SM_Terminal_EngineeringBank` | 11.04 x 1.90 x 1.56 | design | screen 1 2; seat 1 2; stand 1 2 |
| `SM_Console_MasterDesk` | 9.70 x 2.67 x 2.15 | design | screen 1-5; station '' |
| `SM_Console_BoothRear` | 3.78 x 1.09 x 1.31 | centre | screen 1 2 3 |
| `SM_Counter_Arrivals` | 5.46 x 1.02 x 1.29 | centre | screen ''; station ''; stand arrival |
| `SM_Console_Instructor` | 2.10 x 1.62 x 1.21 | centre | screen '' aux; seat ''; stand '' |
| `SM_Chair_Crew` | 0.61 x 0.65 x 1.08 | centre | seat '' |
| `SM_Chair_Bridge` | 0.61 x 0.67 x 0.97 | centre | seat '' |
| `SM_Chair_Conference` | 0.64 x 0.70 x 1.05 | centre | seat '' |
| `SM_Chair_Commander` | 0.69 x 0.78 x 1.14 | centre | seat '' |
| `SM_Stool` | 0.47 x 0.47 x 0.46 | centre | seat '' |
| `SM_Table_HoloStrategy` | 3.60 x 3.60 x 0.97 | centre | holo ''; stand s1 s2 s3 s4 s5 s6 s7 s8; station '' |
| `SM_Table_Briefing` | 7.24 x 4.04 x 1.05 | centre | seat 01-12; holo ''; station '' |
| `SM_Table_TeamRound` | 3.96 x 3.96 x 1.05 | centre | seat 01-08; holo ''; station '' |
| `SM_Desk_Commander` | 2.20 x 1.77 x 1.14 | centre | screen ''; seat ''; station '' |
| `SM_Case_Display` | 1.22 x 0.58 x 1.40 | centre | stand '' |
| `SM_Lectern` | 0.66 x 0.50 x 1.13 | centre | screen ''; stand '' |
| `SM_Board_Rank` | 3.60 x 0.52 x 2.50 | wall | screen ''; station ''; stand '' |
| `SM_Dispenser` | 0.92 x 0.52 x 2.02 | wall | screen ''; stand '' |
| `SM_Counter_Serving` | 4.84 x 1.15 x 1.27 | centre | station ''; stand server |
| `SM_Counter_Quartermaster` | 3.04 x 0.99 x 1.25 | centre | screen ''; station ''; stand clerk |
| `SM_Lockers_Uniform` | 2.42 x 0.58 x 2.14 | wall | stand 1-4 |
| `SM_Platform_Fitting` | 2.30 x 1.82 x 2.10 | centre | screen ''; stand '' |
| `SM_Table_Mess` | 2.10 x 1.56 x 0.83 | centre | seat 01-06 |
| `SM_Bunk_Double` | 2.73 x 1.00 x 2.04 | centre | bunk 1 2; stand '' |
| `SM_Bunk_Single` | 1.29 x 2.57 x 1.60 | centre | bunk ''; stand '' |
| `SM_Pod_Simulator` | 1.36 x 2.02 x 1.59 | centre | screen ''; seat ''; stand '' |
| `SM_Bed_Medical` | 2.21 x 0.87 x 1.52 | centre | screen ''; bunk ''; stand medic |

## Deck contracts

- **Engineering terminals** (`decks/engineering`): `SM_Terminal_Engineering`
  has its origin on the screen line (`TERM_ROWS_Z`): live screen 1.30 x 0.62 m
  tilted 32 degrees, centre 0.18 m behind the line at 1.13 m, chair 0.85 m in
  front. Butt `SM_Terminal_EngineeringFill` (2.4 m) / `...FillShort` (1.8 m)
  modules between stations and cap the ends with `...End`;
  `SM_Terminal_EngineeringBank` is the two-station 10.8 m bank in one piece.
  Place a station with `id="term_<n>"` to get `SOCKET_seat_term_<n>` /
  `SOCKET_screen_term_<n>`; extra kwargs (`group=`, `link=`, `order=`) land on
  every socket of the placement.
- **Master desk** (`decks/engineering`): `SM_Console_MasterDesk` has its
  origin on the desk's front edge (`MASTER_Z`); the back cabinet reaches
  2.6 m to the far wall's room face. Screen 3 is the centre "master_desk".
- **Hangar booth** (`decks/hangar`): `SM_Console_BoothRear` is modelled
  turned 180 degrees because the deck places it at yaw 180; at that yaw its
  screens face the camera. It has no chairs.
- **Hangar arrivals**: `SM_Counter_Arrivals` (station kind `create_agent`):
  the commander's terminal faces the camera, arriving agents walk up to the
  raised ledge on the +Y side (`SOCKET_stand_<id>__arrival`).
- **Own station anchors**: decks that emit their own `SOCKET_station` place
  a station piece with `kit.props.command.place_without_station(...)`, which
  drops the piece's anchor (the cook rejects an anchor without
  `station_kind`).
- **Ops berths**: `SM_Bunk_Single` runs away from the camera (head at +Y) so
  a paused agent is fully visible; `SM_Bunk_Double` hides about a third of
  the lower sleeper under the upper berth.
