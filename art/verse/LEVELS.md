# Verse level design (first release)

Level designer's layouts for the four decks. Coordinates are three.js metres
(BRIEF §4): x grows to screen right, z grows toward the camera (screen bottom),
y up, floor at y = 0. `z = 0` is the far (top) edge of the plate. Sizes are
targets; builders may move things by a module (1.2 m) to fit the kit.

Reading rules that drive every layout (BRIEF §2, §5):

- Only faces that look toward +z are visible. Put windows, wall panelling worth
  seeing, signage and consoles' screens on surfaces that face +z: the far
  (north) wall of each room, and consoles facing +z with their crew seated on
  the +z side.
- East–west walls with walkable floor behind them are cut at 1.1 m; the far
  hull wall (z ≈ 0) stands full height and is the "hero wall" of the deck.
- Walls running along z are seen edge-on: use them freely as room dividers.
- Plate aspect ≈ 16:9 at overview: depth D ≈ 0.65 × width W.
- No void anywhere: every metre of the frame is room, corridor or hull
  structure (frames, conduits, machinery, dim maintenance light).
- Every deck has a turbolift lobby with a `SOCKET_lift_main` and a `lift`
  station, and a `SOCKET_spawn_*` where the commander appears.

## Deck 1 — `bridge` · Command Bridge (W 72 × D 44)

The hall faces the far wall: the crew looks "forward" to the viewports at the
top of the screen.

| Area | Rect (x0–x1, z0–z1) | Contents |
|---|---|---|
| Viewport wall | 0–72, 0–3 | Full-height hero wall of slanted viewport panes in heavy mullions, dim star field inside the glass; chamfered corners filled with structure. |
| Command walkway | 32–40, 5–32 | Raised-feel main level (y = 0) running from the aft entrance up to the viewports; floor light inlays along both edges. Commander's station at z ≈ 7 (`station: command`, kind `agents_list`), strategy holo-table at z ≈ 13 (`SOCKET_holo_strategy`). |
| Port crew pit | 5–30, 6–30 | Sunken 1.4 m, stepped access from the walkway, two rows × 4 console seats facing −z (consoles face +z): `SOCKET_seat_pit_p_<n>` + `SOCKET_screen_pit_p_<n>` (n = 1–8), railings at deck level. |
| Starboard crew pit | 42–67, 6–30 | Mirror: `…_pit_s_<n>` (n = 1–8). |
| Aft bulkhead | 0–72, 31–33 | Cut-away wall (1.1 m) with three openings onto the aft rooms. |
| Briefing room | 2–28, 33–43 | Black glossy oval table (12 seats, `SOCKET_seat_brief_<n>`), holo projector in the table (`SOCKET_holo_briefing`, station kind `team`), wall screens on its far wall. Team rounds gather here. |
| Turbolift lobby | 30–42, 34–44 | Two lift doors on the far side of the lobby facing +z, `SOCKET_lift_main`, spawn. |
| Commander's ready room | 44–70, 33–43 | Desk facing +z, chair, a viewport slit, a display case; station kind `service_record`. |

Waypoints for idle crew: walkway edges, viewport rail, pit steps.

## Deck 2 — `ops` · Operations Deck (W 96 × D 60)

A long main corridor (the hexagonal-profile corridor) with rooms off both sides.

| Area | Rect | Contents |
|---|---|---|
| Hull wall | 0–96, 0–2 | Full-height panelling with light strips; structure fills the corners. |
| Mess hall | 3–31, 2–26 | Rows of tables with benches (≥ 24 places, `SOCKET_seat_mess_<n>`), serving counter on the far wall (station kind `mess_call`), drink dispensers, a wide viewport slit on the far wall. |
| Records hall | 33–51, 2–26 | Long hall with a rank board on the far wall (station kind `service_record`), display cases with commendations, a lectern. |
| Simulator room | 53–73, 2–26 | Four simulator pods/consoles facing +z (station kind `games`, `SOCKET_seat_sim_<n>`), instructor console. |
| Quartermaster | 75–93, 2–26 | Uniform lockers on the far wall, fitting platform, counter (station kind `quartermaster`). |
| Main corridor | 2–94, 27–33 | The deck's spine: 6 m wide corridor profile with chamfered lower walls, ceiling light panels mirrored in the floor, blast-door frames every 24 m. Waypoints along it. |
| Crew quarters | 3–37, 34–58 | Bunk rows (≥ 16 bunks, `SOCKET_bunk_<n>`), lockers, a washroom block; paused agents rest here. |
| Team ready rooms A/B | 39–53 and 55–69, 34–58 | Each: round table with holo emitter (`SOCKET_holo_team_a/b`, station kind `team`), 8 seats, wall screens. |
| Turbolift lobby | 71–81, 34–46 | Lift doors, spawn. |
| Medical / storage | 71–93, 47–58 and 83–93, 34–46 | Med bay beds, storage racks (dressing). |

## Deck 3 — `engineering` · Reactor Engineering (W 84 × D 54)

| Area | Rect | Contents |
|---|---|---|
| Hull wall | 0–84, 0–2 | Full height: heavy machinery, coolant pipes, warning panels. |
| Reactor shaft | centre (54, 22), r 13 | A circular shaft through the deck: rim with a low kerb, the glowing core column (r 3, warm white/orange) rising from below, a control ring around the core (r 5–6.5) reached by four narrow catwalks without railings (N, E, S, W). The void falls away into haze and darkness; a few shaft rings below. `nav: block` on the void. |
| Engineering control room | 2–32, 2–40 | 12 terminal stations in three rows of four facing +z (`SOCKET_seat_term_<n>`, `SOCKET_screen_term_<n>`): coding panes' technicians. Master systems console at the far wall (station kind `coding_launcher`). Glass partition on the room's east side looking at the shaft. |
| Power conduit gallery | 34–82, 38–52 | Floor-to-ceiling conduits, junction boxes, cable trays; waypoints for patrols. |
| Turbolift lobby | 2–14, 42–52 | Lift, spawn. |
| Maintenance bay | 16–32, 42–52 | Tool racks, a utility drone dock (`SOCKET_spawn_drone`). |

## Deck 4 — `hangar` · Main Hangar (W 100 × D 62)

| Area | Rect | Contents |
|---|---|---|
| Hangar wall | 0–100, 0–3 | Full-height hangar wall: huge closed blast doors with a pressure frame, gantry rails, deck lights. |
| Flight deck | 3–97, 3–46 | Vast floor of large plates with painted landing markings; a recessed launch well in the floor (30 × 12 m) covered by a faint blue containment field over darkness (never stars); the shuttle (≈ 20 m, original design, wings folded) on a pad (`SOCKET_spawn_arrival` at its ramp); cargo containers and pallets in ordered rows; fuel lines; tow drone. |
| Control booth | 3–25, 47–60 | Raised booth behind a window wall (cut at 1.1 m) with consoles facing −z toward the flight deck (an exception: seen from behind). |
| Arrivals desk | 40–60, 47–60 | Counter and terminal (station kind `create_agent`): new agents come off the shuttle and report here. |
| Turbolift lobby | 64–76, 48–60 | Lift, spawn. |
| Armoury racks | 78–97, 47–60 | Armour racks, crates (dressing). |

## Station kinds (contract with the engine)

`agents_list`, `team`, `service_record`, `mess_call`, `games`,
`quartermaster`, `coding_launcher`, `create_agent`, `lift`. A station is an
object with custom props `station` (unique id) and `station_kind`, plus a
`SOCKET_station_<id>` empty at the spot where the commander stands to use it.
