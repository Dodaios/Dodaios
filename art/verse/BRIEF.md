# Dodaios Verse — production brief (capital ship rebuild)

Status: greenlit 2026-10-19. This brief is the contract between every team on
the rebuild. If a document and this brief disagree, this brief wins until it is
changed here.

## 1. Vision

The Verse is the interior of **Dodaios**, a 1.6 km wedge-hulled capital ship of
a fleet navy, seen from above. It must read as a real place photographed, not as
a game prototype: polished black decks that mirror the ceiling light panels,
light-grey wall panelling with recessed light strips, gunmetal structure, cold
5600–6500 K light, red and green indicator lights, immense symmetric halls. The
art direction is "fleet-navy brutalist industrial": militaristic, sterile,
monumental, ordered. The person is the ship's **commanding officer**; the
agents are its **officers and crew**; coding panes are **engineering
technicians**; the pet is the commander's **companion drone**.

Everything is new. Nothing from the previous starship build (code, plans,
figures, ranks, look) is reused; the old module is deleted.

Legal: no film or franchise name, logo, crest, insignia, typeface, alien script
or character is copied or named anywhere in the repository. Use generic words
("fleet", "capital ship", "trooper", "officer"). The ship's emblem is original.

## 2. Camera and framing (fixed)

- Orthographic camera, **pitch 60° below the horizon, yaw 0**: the camera looks
  toward −Z (three.js) and down. Screen right = +X. Each deck orients its own
  layout (the bridge faces its viewports at the top of the screen); see
  LEVELS.md.
- The ship fills the whole viewport at every zoom. Nothing outside the hull is
  ever rendered: the area of a deck plate around the rooms is hull structure
  (frames, conduits, machinery voids, dim maintenance light), never stars.
  Viewports in the bridge may show a dim star field *inside the window glass*.
- Pan and zoom only (no orbit). Zoom-out stops where the plate covers the
  viewport; zoom-in stops at 1.25× the plate's native density.
- Decks are separate floors stacked in the hull, reached by turbolift. New
  decks are added as modules without touching the stage.

## 3. Rendering technique (fixed)

Hybrid "pre-rendered plate + realtime actors", the technique of the classic
isometric RPGs, done with a modern path tracer:

1. Each deck is assembled in **Blender** from a modular kit and rendered with
   **Cycles** (OptiX) through the fixed orthographic camera into a
   high-resolution **plate** (full GI, glossy reflections, area lights, AO,
   haze, bloom). This is our "lighting build".
2. The same cook exports what the runtime needs to put live things *into* that
   photograph: simplified **occluder** meshes (depth only), a **nav grid**,
   **sockets** (screens, seats, standing spots, holo emitters, lights, doors,
   spawn points), **stations**, **rooms**, an **environment map** and
   **light probes** for the characters.
3. The web runtime (three.js) draws the plate, writes the occluders into the
   depth buffer, then draws characters, screens, holograms and light effects in
   the same world space with the same camera, so they sit inside the picture
   and disappear correctly behind walls and consoles.

Blender is the level editor, the cook is the build, the browser is the engine.

## 4. Coordinate system and units (fixed)

- Metres. three.js axes: X = screen right, Y = up, Z = toward the camera
  (screen bottom). Deck floor at Y = 0.
- Blender axes: X = three X, Y = −(three Z), Z = three Y. The glTF exporter's
  "+Y up" conversion does this; manifests are always written in **three.js
  axes**.
- The plate camera: centre `C`, right vector `R = (1, 0, 0)`, up vector
  `U = (0, cos 60°, −sin 60°)`, view direction `D = (0, −sin 60°, −cos 60°)`.
  A world point P maps to plate metres `u = (P−C)·R`, `v = (P−C)·U`.
- Density: **192 px per metre** along u at full resolution (L0), served as a
  tile pyramid (L0, mips at 1/2 and 1/4, overview L1 at 1/8).

## 5. Cutaway rules (the look of a section drawing, fixed)

- No ceiling is visible to the camera. Ceilings exist in the Cycles scene with
  camera visibility off so they still light the room and mirror in the floor.
- Walls running along X (east–west) that have walkable space on their −Z side
  (behind them, seen from the camera) are cut at **1.1 m**; the cut face gets
  the section cap material (dark steel, faint hatching). The outermost −Z hull
  wall of a deck and any east–west wall with no walkable space behind it stand
  at full height and show their panelling.
- Walls running along Z are seen edge-on and may stand at full height.
- Consoles face +Z where possible so their screens face the camera (the crew
  sits on their +Z side and is seen over the shoulder).

## 6. Decks (first release)

| # | id | Name | Purpose in the app |
|---|---|---|---|
| 1 | `bridge` | Command Bridge | Agents work at consoles in two sunken crew pits either side of the command walkway; forward viewports; the commander's station at the walkway's end; strategy holo-table; briefing room off the bridge (team rounds). |
| 2 | `ops` | Operations Deck | Main corridor spine; mess hall (idle crew); crew quarters with bunks (paused agents); quartermaster (the commander's uniform); records hall (service record, rank board); simulator room (the games). |
| 3 | `engineering` | Reactor Engineering | Reactor shaft with the core column and catwalks; engineering control room whose terminal banks are the coding panes (technicians at live terminals); power conduits. |
| 4 | `hangar` | Main Hangar | Shuttle on the pad, cargo, gantry crane, control booth; new agents arrive here by shuttle. |

Every deck has a turbolift lobby. Rooms are sized for the real crew: up to 16
agent consoles on the bridge, 12 terminals in engineering.

## 7. People

- **Commanding officer** (the person): walks where clicked; uniform by rank tier.
- **Officers and crew** (agents): fleet uniform, colour by rank tier, a personal
  accent colour from the agent, a name plate; duty status shown by what they do
  and a small status beacon.
- **Technicians** (coding panes): black work uniform and helmet at a terminal.
- **Companion drone** (the pet): a small drone at the commander's heel.
- **Ship's company** (ambient, not agents): a few patrol troopers and utility
  drones on fixed rounds, no name plates, never interactive.

One shared human skeleton for all humans (shared animation clips). glTF 2.0
binary, Y up, metres, origin at the feet, facing +Z.

## 8. Ranks and duty status (new)

Ladder (first level of each rank; the XP curve is unchanged):

| Tier | Ranks |
|---|---|
| Deck (enlisted) | Recruit 1 · Deckhand 3 · Technician 5 · Senior Technician 8 |
| Line (officers) | Ensign 11 · Lieutenant 14 · Senior Lieutenant 17 · Commander 21 · Captain 25 |
| Command | Line Captain 29 · Commodore 33 |
| Flag | Rear Admiral 37 · Vice Admiral 41 · Admiral 45 · Fleet Admiral 50 |

Insignia: a chest **rank plate** (original design: a small steel plate with up
to six inset tiles; tile colour by tier — steel, blue, red, gold). Uniform by
tier: deck = charcoal work uniform, line = olive-grey tunic with cap, command =
black tunic with cap, flag = white tunic with cap.

Duty status (from the agent's real run state): **working** (seated at its
console, typing, screen live), **waiting for you** (stands, turns to you, amber
beacon), **idle** (seeded off-duty life: mess, corridor, viewports), **paused**
(in its bunk), **error** (red beacon at its console).

## 9. Production pipeline (see docs/verse/pipeline.md once written)

- Asset naming: `SM_` static mesh, `SK_` skeletal mesh, `A_` animation,
  `M_`/`MI_` material/instance, `T_` texture (`_BC`, `_N`, `_ORM`), `UCX_`
  occluder/collision proxy, `SOCKET_` attachment points, `LV_` deck level,
  `BP_` runtime actor.
- Source of truth is **code**: Blender Python builders under `art/verse/`
  (kit pieces, materials, decks, characters). `.blend` files and downloaded
  textures are derived data in a git-ignored cache and are never committed.
- Only CC0 third-party textures/HDRIs (e.g. Poly Haven), recorded in a license
  ledger with URL and hash.
- Cooked output lives in `dodaios/ui/web/frontend/public/verse/` (plates as
  AVIF tiles, glb, json). Budget for the whole cooked Verse: **≤ 90 MB**,
  at most 16 MB of plate per deck.
- Gates: asset validator (names, budgets, sockets, manifest schema), cook
  reproducibility, runtime checks (draw calls, frame time), visual QA in Chrome
  against the reference contact sheet.
- Blender is driven headless for cooks and through the Blender MCP bridge for
  interactive assembly and viewport checks.

## 10. Quality bar ("photographed, not generated")

- Every hard edge bevelled; no perfectly flat, perfectly clean surface;
  roughness variation and subtle grime in crevices; real-world scale on
  everything.
- Light has a reason: every light source is a fixture you can point at.
- Restraint: grey, black, white, gunmetal; colour only on indicators, screens
  and the reactor. No neon, no random glowing lines, no clutter without purpose.
- Symmetry and rhythm: panel modules, light panels and floor seams on a 1.2 m
  grid.
