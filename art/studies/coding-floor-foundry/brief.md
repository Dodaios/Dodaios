# Coding floor: the Foundry deck

## Intent

The coding floor shows every coding-agent pane of the Agentic IDE as a figure
at a desk. Its previous dressing was a plain open-plan office (oak floor, rugs,
bookcases, potted trees): readable, but nothing on it said "this is where code
is made", nothing reacted to the agents' work, and every department looked like
the next one. The rebuild turns the floor into a place that is worth walking
through and that reads the agents' real state at a glance.

Direction: an orbital code foundry. The floor is an open deck of a station
floating in a nebula above a ringed planet. Charcoal steel and gold (the brand
colours) carry the architecture; each workspace owns one saturated signal
colour; code-related light is cool cyan. Nothing glows without a reason.

## Pillars

1. **One landmark.** The Core stands at the spawn point in the middle of a wide
   concourse: gyroscope rings round a plasma heart and a light column into the
   sky. It is visible from every part of the floor and its pace follows how
   many agents are working.
2. **The world is the status display.** Every effect maps to real pane state:
   - working pane: its desk's signal light breathes in the bay colour;
   - pane that asks or failed: a beam of amber (asking) or red (failed) rises
     from its desk into the sky, visible across the whole floor;
   - pane output: a packet of light runs along the floor rail from its bay to
     the Core, which flares when it arrives;
   - idle floor: the Core turns slowly and dims; a busy floor spins it up.
   No decorative effect pretends activity that is not happening.
3. **Bays, not cubicles.** A workspace is a bay: a steel deck plate framed by a
   light strip in its colour, a truss gantry with its name as a holographic
   sign, consoles instead of office desks, and its own signal colour on rail,
   trim and sign.
4. **Fun to cross.** A wide concourse for sprint-jumping, light that answers the
   player's steps, drones overhead, a planet and nebula that make the edge of
   the deck worth walking to.

## Shape language, palette, materials

- Shapes: chamfered steel slabs, trusses, rings; long horizontal light lines;
  no rounded office furniture.
- Palette: deck `#1b1d22`–`#2a2d34`, steel `#3a3e47`, gold `#d8ae52`, code
  cyan `#5fe6ff`, nebula violet/teal; bay signals cyan, magenta, amber, lime,
  violet, coral.
- Materials: matte painted steel with panel seams (canvas textures), brushed
  gold trim, emissive light strips (tone mapping off, bloomed).
- Lighting: low hemisphere fill, one cool key light for shadows, light pools as
  additive decals, bloom on emissives only (threshold above lit surfaces).

## Camera and viewing distance

The office's three-quarter orbit camera (35° FOV, 40° down by default).
Overhead pieces (drones, gantry tops) stay below 5 m and out of the walkways
so the close camera never looks through them; the beams and the Core column
are additive and do not hide figures.

## Budgets

- Draw calls: repeated parts are instanced; static dressing does not grow with
  the number of panes beyond one instance per desk.
- Bloom renders at reduced resolution and is skipped in the compact (side
  panel) stage; reduced motion freezes rotations, pulses and drones.
- Measured on the maintainer's desktop (see `technical_report`); other devices
  remain unverified until measured.

## Scope of this study

Procedural runtime geometry in the existing Three.js stage, like the rest of
the office floors; no GLB is promoted. The floor plan keeps its rooms and
stations (Mission Control, team room, server room, reception, break room,
spawn point); the concourse is widened for the Core.
