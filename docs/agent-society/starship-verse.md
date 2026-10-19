# Dodaios Verse: the starship

Status: **rebuilt from scratch as a starship (2026-10-19).** It replaces the
office tower (team campus, coding floor, arcade floor, Level Hall). The
maintainer asked for a ship in the spirit of the big space-opera franchises
on which you see the agents walk the decks and do their work, and delegated
every decision below that line. The brief and references are in
`art/studies/starship-verse/brief.md`.

Code: `dodaios/ui/web/frontend/src/components/society/starship/`. The stage
(`ShipStage.tsx`) is what **Agents > Dodaios Verse** and the IDE side panel's
Verse tab (on engineering, compact) mount.

## 1. The idea

The ship is called **Dodaios**. The person is its **captain**. The agents are
its **crew**: androids, because they are AI. The person's pet (Jarvis) is the
**companion** and keeps to the captain's shoulder. The map shows only what is
real: run state, a team's round and a message between two agents come from
the roster, the team's meeting and the board; idle life is seeded
choreography; nothing else is staged, nothing starts or stops work, and it
costs no tokens.

## 2. Look

| Aspect | Rule |
|---|---|
| Shape | Long horizontal lines, rounded corners, chamfered frames. Walls have a dark base band, ceramic panels and graphite ribs every 2.4 m with a light slit. Consoles are wedge desks with a sloped screen. |
| Colour | Charcoal deck plating and graphite structure, warm-white ceramic, gold for command and everything the captain uses, cyan for information; state colours (green working, amber waiting, grey idle) only on real state. |
| Light | Emissive strips, screens and holograms made to glow by a bloom pass; one overhead key light with soft shadows; light pools on the floor under the cut-away ceiling fittings; an environment map for the metal. |
| Outside | A star field and nebula on a sky sphere, the destination's planet below the ship (surface, clouds, night-side lights, atmosphere rim), its rings, its sun; at one destination a black hole. |
| Camera | A cut-away deck seen from above at 25–80°, orbiting and following the captain; drag to turn, right-drag (or Shift-drag) to pan, wheel to zoom from the shoulder to the whole deck. |
| HUD | One dark glass look in both themes (the scene is always space): the deck card with the crew line, the rank card, a small toolbar, one prompt. |

No franchise asset, logo, insignia, typeface or interface (such as LCARS or
the delta) is copied; the ranks are the generic naval ladder.

## 3. The shared kit

- **Deck plans** (`plan/`): pure data — rooms, walls with doorways, furniture
  footprints, places people use (seats, standing places, pods), stations the
  captain uses, divisions. `PlanBuilder` refuses duplicate ids per kind; the
  hull is a convex polygon clockwise from the bow (north, −z) with the
  turbolift centred on the stern wall.
- **Navigation** (`nav/shipNav.ts`): an occupancy grid (0.2 m) rasterised from
  the plan with a body's clearance, A* and a line-of-sight pass. A target
  inside something solid (a pod, a tucked-in seat) is reached by walking to
  the nearest free cell and stepping on.
- **Geometry** (`render/kit/geo.ts`): every static part is merged per finish
  (one material each, colour in the vertices), so a deck costs about 90–140
  draw calls. Finishes and procedural canvas textures in `render/kit/materials.ts`.
- **The cut-away** (`render/kit/cutaway.ts`): hull walls the camera is outside
  of, and inner walls standing between the camera and the captain, sink to a
  dark kerb in the shared finishes' vertex shader (two attributes per part:
  the wall's line and its kind). Wall-mounted pieces, door frames and room
  signs sink with their wall.
- **Structure, exterior, dressing** (`render/deck/`): walls, floors and door
  frames; the ship around every deck (nacelles on swept pylons, main engines,
  plating); wall consoles, hatches, conduits, a lit corridor runner, the lobby
  emblem and rings round the divisions.
- **Screens** (`render/deck/screens.ts`): every console screen of a deck in one
  atlas texture, redrawn only when its content changes.
- **Renderer** (`render/ShipRenderer.tsx`): ACES tone mapping, a multisampled
  HDR target, bloom, output. The low quality setting (fewer than four CPU
  threads) drops bloom and shadows.

## 4. Figures

One skeleton for everyone (`crew/rig.ts`, poses are pure and tested): stand,
walk, sit, type, wave, talk, listen, lean, rest; changes blend over a third of
a second.

- **Androids** (`crew/figure.ts`): one skinned mesh each (a ceramic shell,
  graphite joints, shoulder caps and wrist bands in the division's colour,
  rank pips at the collar, a gold bar for a division lead) and a **face
  display**: the agent's own profile face — its pixel creature (painted by the
  profile picture's code) or its shape with eyes — on a dark screen that
  blinks, glances and shows the thinking sweep (`crew/faceAtlas.ts`, one atlas
  for every face).
- **The captain**: a flight suit with gold shoulders, a helmet with a visor and
  a pack. Colours, trim and visor come from the quartermaster; the cut (duty
  suit, field armour, command coat, dress whites, admiral's coat) from the
  level system.
- **The companion** (`life/ShipPet.tsx`): the pet from My Pets, flying at head
  height or walking behind on free floor.

## 5. Life aboard

`life/crewLife.ts` decides, `life/CrewLayer.tsx` walks:

- **working** → sits at its own console and types; its screen shows the tail
  of its chat (the captain's lines gold, its replies white, tools cyan).
- **waiting** → stands at its console and waves, turning to the captain when
  the captain comes close.
- **paused** → rests in a pod.
- **idle** → a seeded day between its console, the mess, the lounge sofas,
  the windows, the galley, the gardens and its division's table.
- A **running round** of its team gathers the free members round the
  division's holo-table (the speaker talks, the rest listen).
- The captain's **call to the mess** brings the off-duty crew for 90 s.

Places are reserved so nobody sits on anybody; bodies give way to each other
and to the captain; an agent created while the ship is open beams in at the
transporter and walks to its seat. Reduced motion places everyone without
walking. Name plates are dots from afar and open near the camera, near the
captain, under the pointer and for the selected agent.

## 6. Decks

The turbolift (E at its doors, or the toolbar) rides between them behind
closing doors. Deck modules (`decks/<deck>/`) register their plan, scene,
station behaviour and panel (`decks/registry.ts`); the stage never changes
for a new deck.

| # | Deck | Crew | What is there |
|---|---|---|---|
| 1 | **Bridge** | none | A panoramic bow window, the command well (captain's chair, first officer, a port seat) inside a horseshoe tactical rail, helm and operations consoles, aft stations, the star chart (a turning galaxy with the destinations), the captain's ready room. |
| 2 | **Operations** | Jarvis agents | One **division** per team — a bay off the spine with a horseshoe of consoles round a holo-table (the team's name, its members as lights, the lead at the gold head console); the crew without a team in the first bay; a free bay for the next team; hydroponics in the spare bays. The transporter in the plaza, the quartermaster, the rest pods, the observation lounge and mess at the bow, the turbolift lobby at the stern. |
| 3 | **Engineering** | coding panes | The reactor core in the middle (its plasma pulses faster the more panes work), one bay per IDE workspace with live terminals on the consoles, power feeds that carry pulses to working bays, the master systems display, a rest nook at the bow. |
| 4 | **Holodeck** | none | A black chamber with a gold grid; the ten games as holographic cabinets on an arc. |
| 5 | **Hall of Honour** | none | A ceremonial hall: the rank wall (all sixteen ranks, the captain's lit in gold), the dais, a display case per officer and flag rank. |

## 7. Stations

| Station | What it does |
|---|---|
| Transporter | The app's create-agent dialog (a host without one creates at once). |
| Turbolift | The deck list. |
| A division's holo-table | Opens that team (the crew without a team: the agents list). |
| Free bay | The agents list, where a team is made. |
| Galley | Calls the off-duty crew to the mess; again ends the break. |
| Quartermaster | The captain's suit, docked at the side. |
| Captain's chair | Sit (walks there first from afar); moving stands up. |
| First officer | The lead's chat. |
| Helm / star chart | Set a course: every destination with the level it opens at; a jump streaks the stars past, flashes and arrives. |
| Operations table | The agents list. |
| Master systems display | Launch coding agents (CLI, workspace, how many, a first task). |
| Holo cabinet | Plays the game. |
| Rank wall / display case | The service record (ranks / rewards). |

E uses the station the captain stands at; a click on it works from anywhere
(the turbolift and the captain's chair walk over first). O shows the whole
deck, F follows again, Escape closes.

## 8. Development handles

Development builds only: `window.__ship` (`captain`, `useShip` — e.g.
`useShip.getState().setDeck("bridge")`, `.place({x, z})`, `.overview()` —
`orbit`, `crewPoses`) and `window.__shipStats` (the last frame's draw calls,
triangles and CPU milliseconds).

## 9. Verification

- Unit tests: every deck's plan (every place and station reachable from the
  turbolift for empty, small and large crews; deterministic; ids unique;
  divisions, leads and caps), the crew's decisions, the poses, the screens
  and faces, the level system's catalogue, insignia and UI, the ship's locale
  parity (five languages, real umlauts).
- Runtime (Chrome against the development build and the live roster of nine
  agents and nine coding panes, 2026-10-19): every deck in the overview and up
  close, the cut-away, the division with its consoles and holo-table, the
  captain and the companion, the quartermaster, the service record. Draw
  calls 86–140 per deck, about 0.1–0.3 million triangles. Frame times were not
  measured reliably: the Chrome window was in the background and throttled
  to about 1.5 frames per second for every page.
- Not verified yet: macOS and Linux WebViews, an integrated GPU, the promotion
  ceremony with a real promotion.
