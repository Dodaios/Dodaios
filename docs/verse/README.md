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
| [`realtime.md`](realtime.md) | The eye-level view: realtime export of a deck (lightmaps, probes, glTF), its manifest block, the runtime and the over-the-shoulder camera. |
| [`combat.md`](combat.md) | The optional reactor duel: the combat core (simulation, netcode, bot, balance) and how it plays in the 3D view (start, controls, camera, effects, HUD, sound). |
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

B folds out the **hoverboard** under the commander (the tool rail has the same
button): the movement keys then glide at 5.5 m/s instead of walking at about
1.3 (Shift boosts to 8.5), the board coasts to a stop when the keys are let
go and loses its speed against a wall, and a click on the deck rides the path
at four times the walking pace. The rider stands on it a hand's breadth off
the floor, leaning into speed and turns; B folds it away. It never comes into
a duel. Motion and look live in `actors/hoverboard.ts`.

**Duel.** At any of the four consoles on the reactor's control ring (Reactor
Engineering) E offers *Start a duel*; the **Duel** button on the tool rail does
the same from any deck (the turbolift rides down first). Choose normal, hard
or elite and fight a 1v1 blaster duel against a bot, best of three; Esc pauses,
Esc again leaves and puts the commander back on the deck. See
[`combat.md`](combat.md).

**Taking over a terminal.** Every desk monitor in Reactor Engineering that
shows a coding pane is a station: within reach, E offers *Take over the
terminal* and opens the pane's screen large (`hud/TakeoverPanel.tsx`). For a
pane the IDE has mounted, every key goes straight to the agent as typed in the
IDE (Enter, arrows, Tab, Esc interrupts, Ctrl+C, a paste arrives bracketed),
through the IDE's own pane-input event with `focus: false`, so the hidden pane
never steals the keyboard; Ctrl+Q or the close button leaves. A pane the IDE
has not mounted shows the server's replay and takes a whole prompt per send
(`/api/agentic-ide/terminals/{name}/prompt`, uncomposed). The master station's
grid screens are not stations: they show every pane at once.

**Views.** The tool rail's switch offers the **bird's-eye** view, **third
person** and **first person**; 1, 2 and 3 pick one and V cycles them (the last
choice is remembered). The bird's-eye view pulls the camera back over the
whole deck; there WASD pans the map. Choosing third or first person returns
to the commander at the close zoom. In both views a click on the floor walks there, a click on a
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

A deck exported as a real-time 3D scene ([`realtime.md`](realtime.md); the
bridge so far) is walked at eye level instead on the full-size stage: the
camera sits behind the commander's shoulder (the commander stands in the
lower right third of the frame) or, in first person, at their eyes. Both play
like a shooter: a click on the view takes the mouse, moving it turns the view,
the left button or E works what the crosshair is on, Esc gives the mouse back
so the HUD's buttons work. WASD walk relative to the view (A/D strafe) and the
commander faces it while walking. The wheel moves the third-person camera
between 1.2 and 5 m; scrolling in past that is first person, scrolling out of
first person comes back. The camera never passes through walls. The view
settings set mouse sensitivity, inverted look and the field of view of each
person. The IDE side panel offers all three views once it is at least
480 × 360 CSS px (rendered at the low quality tier unless the person pins
high); a smaller panel keeps the plate. A click on the panel takes the keys
from the terminal beside it. Details: [`realtime.md`](realtime.md)
("Views").

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
