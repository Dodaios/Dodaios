# Dodaios Verse: the capital ship

Status: **rebuilt from scratch, 2026-10-20.** Replaces the starship build of
2026-10-19 (code, plans, figures, ranks and look are all new).

The Verse is the interior of **Dodaios**, a 1.6 km wedge-hulled capital ship of
a fleet navy, seen from above. The person is its **commanding officer**, the
agents are its **officers and crew**, coding panes are **engineering
technicians**, the pet is the commander's **companion drone**. It is mounted
by **Agents > Dodaios Verse** and by the IDE side panel's Verse tab (which opens
on engineering).

| Document | What it covers |
|---|---|
| [`art/verse/BRIEF.md`](../../art/verse/BRIEF.md) | The production brief: vision, camera, technique, axes, cutaway rules, decks, people, ranks. |
| [`art/verse/style-bible.md`](../../art/verse/style-bible.md) | Architecture, dimensions, materials, lighting, palette, dress, props. |
| [`art/verse/LEVELS.md`](../../art/verse/LEVELS.md) | The level design of every deck: rooms, sockets, station kinds. |
| [`art/verse/ART_DIRECTION.md`](../../art/verse/ART_DIRECTION.md) | The art director's standing notes. |
| [`pipeline.md`](pipeline.md) | The production pipeline: stages, naming, budgets, cook, validation, Blender MCP. |
| [`../agent-society/level-system.md`](../agent-society/level-system.md) | Ranks, XP rules, rewards and the service record. |

## How it is made

Each deck is assembled in Blender from a modular kit (Python builders under
`art/verse/`), lit and rendered with Cycles through one fixed orthographic
camera (60° below the horizon) into a high-resolution **plate**. The same cook
exports what the runtime needs to put live things into that photograph:
occluders, a nav grid, sockets (seats, screens, holo emitters, spawn points),
stations, rooms, an environment map and light probes. The browser draws the
plate, writes the occluders into the depth buffer, and draws the crew, screens
and holograms in the same world space with the same camera.

Cooked content lives in `dodaios/ui/web/frontend/public/verse/` (AVIF plate
tiles, glb, json). Code lives in
`dodaios/ui/web/frontend/src/components/society/verse/`.

## Controls

The person is the commanding officer and steers them in **third person** by
default, as in a game: WASD or the arrow keys walk the commander (Shift
hurries), and E works the station within reach (its label shows the key). The
camera sits close, about 12.5 m across the longer side of the window (on a
2560 px window about 205 px per metre, so the commander stands some 225 px
tall), leads them a little in the direction they walk and eases back onto them
when they stop. A small panel such as the IDE's side panel keeps the same
framing at its own size; a low, wide one still shows at least 5 m of floor top
to bottom. The camera never comes closer than the plate is sharp: an older
deck cooked at 96 px/m, or a HiDPI screen, stops a little further out.

**V** (or the bird's-eye button on the tool rail) pulls the camera back over
the whole deck; there WASD pans the map. V again returns to the commander at
the close zoom. In both views a click on the floor walks there, a click on a
crew member selects them, a drag looks around (the camera picks the commander
up again when they walk) and the wheel or +/- zooms between the whole deck and
the closest view the plate allows.

To stay sharp that close, a deck's plate is a pyramid: full-density L0 tiles
(192 px/m), two tiled mips (M2, M4) and a small overview of the whole deck.
The runtime streams the coarsest level that is still sharp for the current
zoom, only for the tiles in view plus a one-tile ring, keeps the level it
already has drawn underneath while a finer one loads, and holds GPU memory to
a shared budget (`engine/tiles.ts`, `engine/tileStreamer.ts`,
`engine/plateLayer.ts`). Older decks without mips stream the overview and L0
as before.

The deck stays a pre-rendered plate seen from one fixed angle, so the third
person camera follows from above, not from behind the shoulder; a camera
behind the commander would need the decks as real-time 3D scenes.

## Decks

| # | Deck | Who is there | Stations |
|---|---|---|---|
| 1 | Command Bridge | Agents at the consoles of the two crew pits | Command station (agents list), strategy holo-table, briefing room (team), ready room (service record), turbolift |
| 2 | Operations | Off-duty crew in the mess, paused agents in their bunks, teams in their ready rooms | Mess counter (call to the mess), records hall (service record), simulator room (games), quartermaster (uniform), team tables, turbolift |
| 3 | Reactor Engineering | Technicians at the terminal banks: one per coding pane | Master systems console (launch coding agents), turbolift |
| 4 | Main Hangar | New agents arrive by shuttle and report at the arrivals desk | Arrivals desk (create agent), turbolift |

## Duty status

What an agent does is its real run state: **working** at its console,
**waiting for you** standing with an amber beacon, **idle** in its off-duty
round, **paused** in its bunk, **error** with a red beacon. Ambient ship's
company (patrols, utility drones) is decoration and never stands for anything.

## Legal

No film or franchise name, logo, crest, insignia, typeface, alien script or
character is copied or named. Third-party content is CC0 only, recorded in
`art/verse/LICENSES.md`.
