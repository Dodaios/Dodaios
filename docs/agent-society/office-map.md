# Agent office map (Jarvis Verse)

Product name: **Jarvis Verse** (since 2026-09-30). The interface calls the
whole map, the Map tab and the IDE side-panel tab "Jarvis Verse"; the code keeps
its `office` identifiers, and rooms and floors inside it keep their own names.

Status: **team campus (2026-10-12).** The agents floor was rebuilt from the
2026-09-28 prototype: one studio per team instead of provider departments, a
larger plan with an atrium and commons, stations that are the objects
themselves, team-aware behaviour and the Level Hall on its own floor (§5g–§5i).
Sections 2–5 describe the engine and the rooms the rebuild kept; where they
disagree with §5g–§5i, the later sections hold.
It replaces the Mars colony as the renderer behind **Agents > Jarvis Verse**. The Mars
code, its backend contracts and the communications station remain in the tree
and reachable from the Agents workspace; only the map surface changed.

Per [game-art-pipeline.md](game-art-pipeline.md) §3 this runtime scene is the
reference for the office direction. Do not roll its style out to other asset
families or replace figures before the maintainer approves it.

Code: `jarvis/ui/web/frontend/src/components/society/office/`.

## 1. Why an office

The previous worlds (pixel island, Mars colony) were large, navigable places
that cost a lot of authored art and backend navigation to show one thing: what
the agents are doing. The office answers that question in one screen. Every
agent has a desk, departments group them, and a status ring, a monitor face and
a name pill show the run state. It is a projection of the roster only: the map
never moves an agent, starts work or invents activity (world-behaviour-manual
§1 still holds).

## 2. Style guide

| Aspect | Rule |
|---|---|
| Genre | Stylised "toy office" diorama: chunky low-poly 3D, not anime, not pixel art, not realistic. |
| Characters | Chibi proportions (big head, short body), dot eyes, flat matte colours, no textures. Seated at desks; the stored figure recipe is kept, agents without one get a stable chibi look. |
| Furniture | A contemporary workplace built from rounded primitives: light-oak bench desks on black steel T-legs with a white pedestal and a felt privacy screen, slim monitors on arms, ergonomic chairs with a mesh back on a five-star base, open oak-and-steel shelving, low modular sofas on slim legs, tall charcoal planters with full crowns. Department back walls are fluted acoustic felt with a charcoal name plate in white type and oak ledges with small plants. |
| Materials | Mostly matte; black steel and chrome arms carry a little metalness. Light microcement floor, a rounded felt rug per department whose colour also dyes that department's felt screens and seat fabric (`DEPARTMENT_ZONES`). Rooms: slate felt (team), terrazzo (wardrobe), pale stone (reception), light oak (break room). Glass walls and the outer balustrade have slim black frames. |
| Light | Cool sky / neutral ground hemisphere light plus one soft, slightly warm directional sun with PCF shadows. Always bright enough to read, never moody. |
| Setting | The agents floor and the Level Hall are floors of a tower in a city at night: a window wall on the far sides, the tower's body below, lit towers outside (§5h). The coding floor still floats in its own violet night behind glass railings. |
| Camera | Perspective, 35° FOV, three-quarter view from the south-east about 40° below the horizon. Orbit, pan and zoom within limits (20°–72° polar, from 2.5 m out to wherever the overview needs: 140 m at least, more on a large campus). The overview frames the whole floor (§5i). |
| Labels | From across the floor an agent is one small state dot. The dark translucent plate (hexagon badge with the initial or the lead's star, name, rank chip, state dot and activity) fades in over the dot when the camera or the person is near, when the pointer or keyboard focus rests on the agent, or when it is selected (§5g). Scale is clamped by distance. |
| State language | Green = working (pulsing floor ring, code on the monitor), amber = waiting for the person, grey = idle (smiley monitor) or paused (dark monitor). |
| HUD | Theme-token cards over the canvas, so light and dark mode both work: one floor card (name and who is doing what), the level card, the minimap, a small icon toolbar and one prompt (§5g). The diorama itself keeps one palette in both modes. |

## 3. Technology decision

**Three.js through React Three Fiber, in the existing frontend.** This beat the
runner-up (a Blender-authored scene exported as GLB) because the office look is
built from boxes, cylinders and rounded boxes: code builds it in milliseconds,
it adapts to any roster size, and it needs no asset pipeline. Blender stays the
tool for anything organic later (new character bases, special props), following
the game-art pipeline. No engine change (Unity, Godot, Babylon) is warranted:
the renderer is already Three.js inside the WebView, the figures and their
animation clips (`sit`, `work`, `idle`, `walk`, …) already exist, and every OS
target runs WebGL.

## 4. Floor plan and data model

The plans are pure and tested. `officeLayout.ts` holds the shared vocabulary
(types, footprints, desk and wall helpers) and the coding floor's plan;
`buildOfficeLayout(agents, { variant, teams })` hands the agents floor to
`campusLayout.ts`. The Level Hall (`hallFloorLayout.ts`) and the arcade
(`arcade/arcadeFloorLayout.ts`) have floors of their own.

- **Agents floor: a team campus** (§5h). North strip: focus booths, lead
  office, team room, wardrobe, library. Middle: one studio per team, shoulder
  to shoulder in rows of four, two either side of the boulevard. South strip:
  café, lobby with the elevator, break room.
- **Coding floor:** north strip Mission Control, team room, server room;
  departments = IDE workspaces, two columns, at least four (spare ones are
  "Open space"), at most six (the rest fold into "Other"); south strip lobby
  and break room.
- **Spawn point (both working floors):** a round pad with a terminal. On the
  agents floor it stands in the atrium, where the two boulevards cross; on the
  coding floor on the crossing of the centre aisle and the cross aisle nearest
  the floor's middle. `layout.arrival` (south of the terminal) is where anyone
  new to the floor appears.
- **Furniture** has fixed footprints (`FURNITURE_SIZE`) shared by renderer and
  navigation; **spots** are hangout places with pose and facing; **checkpoints**
  are action places; **obstacles** are every solid footprint.
- Seating is by arrival (`createdMs`, then id), so a refetch never re-seats anyone.

## 5. Behaviour, player and interaction

- **Navigation** (`officeNav.ts`): a 0.2 m occupancy grid, A* with line-of-sight
  smoothing, and a final snap onto seats that sit inside a furniture footprint.
- **Agents** (`officeBehavior.ts`, `OfficeAgents.tsx`): working → seated at their
  own screen; waiting → standing at the desk, waving; paused → napping on a
  couch; idle → a weighted day that, on the agents floor, happens mostly in and
  around the agent's own team studio and only sometimes at the shared places
  (§5i). A running round of a team and a message from one agent to another are
  shown as they happen (§5i). Places are reserved so nobody sits or stands on
  anybody. All of it is client-side, deterministic per agent, costs no tokens
  and never starts or stops work. Reduced motion places agents without walking.
  Agents created while the office is open appear on the spawn pad in a column
  of light and walk to their desk.
- **The person's character** (`OfficePlayer.tsx`, `playerProfile.ts`): WASD /
  arrows (camera-relative, Shift runs) or click the floor to walk; a click
  draws the route as dots to a ring at the destination. E interacts with the
  nearest agent or station. The character walks round people and furniture
  and never comes to rest inside anything solid (§5i). Name and body are
  chosen in the wardrobe and stored per browser profile (not roster data).
- **Camera** (`OfficeCameraRig.tsx`): one orbit camera that glides after the
  character; zoom out and it is the overview. Everything stays clickable from
  afar, so walking is optional. A right-drag pan or a fly-to stops following;
  moving resumes it. Inside a walled room the walls between camera and
  character drop to a kerb (§5i).
- **Stations** (`stations.ts`, `StationObjects.tsx`, `OfficePanels.tsx`): every
  action place is an object of the room, one station per job. Spawn terminal →
  a new Jarvis agent (the app's create dialog; a host without one, like the IDE
  side panel, creates at once); reception desk → the directory (agents, places,
  controls, settings); team board → teams (the existing chat groups); a team
  studio's board → that team; wardrobe mirror → your look; the lead's desk →
  talk to the lead; coffee bar → call free agents for a coffee break (visual
  only). §5g has the details.
- **Agent panel:** open chat, walk there, call over, show on map, add to a new team.

## 5a. Figures, pets and live monitors (2026-09-28, round 2)

- **Toy figures** (`ToyFigure.tsx`, `toyFigureModel.ts`): every agent and the
  person are procedural toy characters — big round
  head, dot eyes, smile, T-shirt, trousers, chunky sneakers, eight hair/hat
  styles. Colours come from the stored figure recipe; hair from a stable hash
  (the person picks it in the wardrobe). Poses are pure and tested: the hips
  land exactly on each seat height (chair 0.52, couch 0.56, meeting 0.50,
  beanbag 0.42) and nothing reaches more than 0.16 m behind the seat centre,
  so figures no longer clip through backrests. Chairs sit 0.62 m from the desk
  centre and keyboards at the desk edge so the short arms reach them.
  The agent creator still shows the older rigged figures; switching it to the
  toy style is the rollout step after the maintainer approves this look.
- **Pets**: each agent's symbol (the profile companion) follows it at about a
  fifth of its height, reusing `AgentFollower`; the lead is drawn as the
  person's own pet (see *Jarvis is the person's pet* below).
- **Accessories** (`companion/accessories.ts`): a symbol can wear one item per
  slot, chosen in the agent profile's Appearance tab or the companion editor
  and stored as `companion.accessories` in the avatar JSON. The set is ten
  finished pieces (suit, tuxedo, lab coat, coder hoodie, crown, top hat, cap,
  headphones, sunglasses, cigar); clothing starts just below the eyes with
  sloped shoulders so the face stays free, and the hoodie's hood frames the head.
  `scripts/art/companion_accessories.py` writes one catalog of 3D primitives
  (`accessories.json`); the flat symbol draws their front projection and
  `scripts/art/build_companion_accessories.py` (background Blender) builds the
  same parts into `assets/society/companions/accessories.glb`, so the profile
  picture and the map companion always match. Clothing is clipped to each
  silhouette; unknown ids from a newer build are skipped, never rejected.
- **Live monitors** (`LiveMonitors.tsx`, `useDeskChats.ts`, `deskChat.ts`): an
  agent seated at its own desk shows the tail of its chat (user lines, replies,
  running tools) on its monitor, refreshed by jittered polling of the existing
  session endpoint for seated agents only (at most six reads at once, the
  longest unread first, so every monitor of a full floor gets its turn; each
  read has an eight-second timeout and the ticks do not wait for it). Clicking the
  screen dives the camera into it and then opens that agent's chat.
  Follow-up: a `limit` query on the session endpoint, so long chats are not
  fetched whole.
- **Pace**: the person walks at 2.0 m/s and sprints at 4.4 m/s (Shift).
  Working agents stay at their screen even when called.

## 5b. Coding floor (2026-09-29)

A second floor for the coding agents that run in the Agentic IDE's terminal
panes. It shares the office's engine, style and controls; only the people and
the floor plan differ.

- **Elevator**: the reception elevator is a checkpoint on every floor. Its
  call button opens the floor picker (see §5e; before the arcade floor it
  simply went up or down). The ride is a short door-like fade, and
  the person steps out at the elevator of the other floor. The floor survives
  a remount of the stage.
- **Floor plan** (`buildOfficeLayout(agents, { variant: "coding" })`): one
  department per IDE workspace; no lead office and no wardrobe (a quiet zone
  takes their place, built from existing furniture); reception with the
  elevator and the break room stay. The agents office layout is unchanged.
- **Spawn point** (2026-09-30): the coding floor's spawn point replaces the old
  lobby kiosk. Its panel is Mission Control's launcher (CLI, workspace, how
  many, optional first task, through the IDE's own `POST /terminals`); every new
  pane appears on the pad and walks to its desk. `SpawnPoint.tsx` builds pad,
  terminal and fittings in each floor's own materials (oak, bronze and a mint
  glow with the brass ghost downstairs; walnut, brass and amber with a brass
  `>_` upstairs); two gyroscope rings turn round the floor token.
- **Jarvis follows**: on the coding floor Jarvis flies (or walks) in "follow"
  mode beside and behind the person with a smoothed lag and never inside a
  wall, including in the elevator. In the agents office it keeps its
  lead-office behaviour.
- **Jarvis is the person's pet** (2026-10-02): Jarvis appears as the pet
  chosen in Settings → My Pets (`docs/pets.md`), in 3D, not always as Gigi.
  `companion/petCompanions.ts` maps a pet to its companion:
  Gigi keeps its hover model; the eight other built-ins have authored Blender
  models (`scripts/art/build_pet_companions.py`, study
  `art/studies/jarvis-pet-companions`, one GLB per pet under
  `assets/society/companions/pets/`) and a gait of their own: Ember the
  dragon flies with beating wings, Miso the cat trots, Cocoa the puppy trots
  with flopping ears and a wagging tail, Bolt the battery
  waddles, Brew the teapot hops with a rattling lid, Mochi bounces, Shelly
  the snail crawls and Dodaios, the hooded figure built of cubes like its
  pixels, walks upright on its two legs with its cape streaming. Pets that fly hover at head height with Gigi's halo and
  sparkles; pets on the floor (`gigiFlight.ts` `ground` mode) walk right
  behind the person's feet, take floor routes (`findPath`) on errands instead
  of flying over desks, and carry their nameplate low. Limbs move by
  `companion/petRig.ts`, phased by ground covered so feet do not slide;
  reduced motion stops every gait. A pet the person drew becomes a voxel
  figure extruded from its own idle frames (`voxelPet.ts`), facing the camera
  and floating low. The stage feeds the choice through
  `companion/companionPetStore.ts`, so a change in My Pets swaps the
  companion live.
- **Pane to character** (`codingFloor.ts`): every running coding-agent pane
  (Claude Code, Codex and the other agent CLIs; not plain shells, not archived
  panes) is one character. Its id is `pane:<workspace>:<history id or key>`,
  and its look (figure and palette) is random but stable, hashed from the
  pane's history id. Name comes from the pane's short title, department from
  its workspace.
- **States**: working, starting or pending → sits at its computer; asking →
  waits at its desk and waves; idle, done or exited → walks around and hangs
  out in the break room; an error keeps the agent at its desk. The exact
  mapping lives in `codingFloor.ts` and its tests.
- **Live monitors** (`TerminalMonitors.tsx`, `usePaneScreens.ts`,
  `terminalScreen.ts`): an agent seated at its desk shows its terminal live —
  dark background, monospace text, the last rows that fit, a cursor block and a
  title bar with its name and state dot. Screens come from the read-only
  `GET /api/agentic-ide/screens?pane=<workspace>:<key>` feed (at most eight
  panes per call; it never resizes, attaches to or writes into a terminal).
  Only seated agents near the camera are polled (six at most), on a jittered
  1.2–2 s schedule that pauses while the stage is asleep, and a monitor
  redraws only when its screen changed. Idle or absent agents show a dim
  screensaver.
- **Open session**: clicking a monitor (or E at the agent → "Open session")
  dives the camera into the screen and then opens the Agentic IDE with that
  pane focused (`codingNavigate.ts`).
- **IDE side-panel tab**: the coding floor is also the "Office" tab of the
  Agentic IDE's side panel (`components/agentic/sidePanel/OfficeTab.tsx`),
  added from the panel's "+" menu or its closed-panel rail. It lazy-loads the
  stage in a compact layout on the coding floor, inside its own error boundary,
  so a failed scene stays inside the tab. Bringing the tab forward widens a
  narrow panel to 520 px once; the user can drag it back. There a monitor click
  focuses the pane in the grid right next to it, and the office's "open the
  ledger" action brings the Agents tab forward.
- **Its own look** (`CodingFloorLook.tsx`, `CODING_SCENE` / `CODING_STUDIOS`
  in `officePalette.ts`): same plan as the agents office, none of its
  surfaces. A violet night instead of navy, a fine terrazzo floor instead of
  warm planks, and a glowing cyan rim under the slab edge. Every workspace
  department is furnished as a studio of its own — carpet pattern (grid,
  stripes, checker, dots, diagonal, zigzag) with a border, a painted sign wall,
  and desk and chair colours — cycled by the department's index. All of it is
  flat or outside the railing, so navigation is unchanged.

## 5c. Lead office as an executive suite (2026-09-29)

The lead office is the one room that breaks the plain toy-office palette on
purpose, so the boss's room reads as the most precious place on the floor
(`LeadSuite.tsx`, colours in `LEAD_SUITE`):

- **Shell:** smoked-oak chevron floor, the same steel-and-glass walls as
  every room, a door sign lettered in bronze. Since 2026-10-12 the suite's
  palette is the campus's own a tone deeper (smoked oak, bronze, cognac
  leather, a slate rug; see 5h), so where this section says walnut, brass,
  oxblood or navy, read those.
- **Feature wall (north, 2.9 m):** walnut slats around a backlit black-glass
  star emblem, two lit bookcases with books, trophies and vases, warm LED coves.
- **Executive desk:** 2.4 m walnut desk with a brass edge, three monitors, a
  banker's lamp, a star plaque on the visitor side and a high-back oxblood
  leather chair. Seat distance and height match every other desk, so the
  seating and figure-pose contracts are unchanged. A second lead gets a
  partner desk; there is never an empty lead desk.
- **Furnishing:** navy rug with a gold border and medallion, two tan club
  armchairs for visitors, a bar cabinet and a chesterfield lounge with a glass
  coffee table along the west wall (fronts towards the camera), a floor globe,
  two floor lamps and palms. Two warm point lights make the room glow.
- **Sit at the desk (2026-09-29):** the executive chair is solid, so nobody walks
  through it. Walk up and press E, or click the chair, to sit (`leadSeat.ts`);
  any movement stands the character up. Clicking the monitors dives into them
  and opens the lead agent in the agents view, like any agent's desk screen.
- **Office dog (`OfficeDog.tsx`, `dogLife.ts`, `dogProps.tsx`):** a black-and-tan
  rottweiler figure with jointed legs, head, ears, tail and tongue. It has baskets in
  the lead office, the team room and the break room and lives in the room of its
  current basket: sleeps, roams, sniffs, sits, lies down. Now and then it walks (never
  jumps) to another basket. Pet it with E or a click: it sits, wags, shows hearts and
  follows the person inside its room for 30 s. Easter egg: the treat jar beside the
  break room's coffee bar hands out a bone; give it to the dog and it begs, catches
  it, spins twice in the air with gold sparks and chews it in its basket.
- Every piece stays inside its `FURNITURE_SIZE` footprint (props test) and the
  navigation tests still reach every seat, spot and checkpoint.

Awaiting the maintainer's visual review like the rest of the office.

## 5d. Contemporary look (2026-09-29)

The maintainer rejected the first look as a 1990s office and asked for a
genuinely modern one. The shared kit (`OfficeFurniture.tsx`,
`DeskInstances.tsx`), the floors and room surfaces (`OfficeScene.tsx`,
`OfficeRooms.tsx`) and the palette (`officePalette.ts`) were restyled as in §2;
the coding floor keeps its own terrazzo, night and studios, now in the same
contemporary kit with tone-on-tone patterns. Seat height, desk height, monitor
screen position and every footprint are unchanged, so poses, live screens and
navigation work as before. Still in the earlier style and waiting on the
maintainer's review of this reference before they follow: the lead suite, the
reception desk, the team room table and chairs, the lockers and
mirror, the coffee bar, the water cooler and the arcade.

## 5e. Arcade floor (2026-10-02)

A third floor on top of the building: a retro arcade hall with ten playable
cabinets. No agents work here; it is a place for the person (and their pet,
which follows like on the coding floor).

- **Elevator**: pressing the call button (click, or E at the doors) opens a
  floor picker (`ElevatorPanel.tsx`) that lists all four floors top first;
  a click, Enter on the focused floor or the floor's number key (0 agents,
  1 coding, 2 arcade, 3 Level Hall) rides there, Escape closes it. The call button shows
  up, down or both arrows depending on the floor (`callDirection`).
- **Floor plan** (`arcade/arcadeFloorLayout.ts`, `buildArcadeLayout()`),
  reworked 2026-10-02 after the maintainer found the first open hall
  confusing: it now reads like the floors below. North strip: three walled
  game rooms (Classics: Pixel Raiders, Maze Muncher, City Defense, Paddle
  Duel; Puzzle corner: Block Drop, Neon Snake, Brick Breaker; Action zone:
  Asteroid Run, Desert Dash, Road Hopper), cabinets on each back wall facing
  the door. Middle: the open hall (pinballs, air hockey, dance floor, floor
  logo). South strip: the foyer with the elevator and token machines, the
  prize shop (counter, claw machines) and the snack bar. The doors of north
  and south rooms face each other on three lanes that stay clear. Cabinets
  are furniture of kind `retroCabinet` with the id `cabinet-<gameId>`; the
  person plays standing 0.85 m in front of one (`OfficePlayer`
  nearest-interactable, E opens it). Tests prove every play spot, counter
  and room is reachable from the elevator and that the lanes stay free.
- **Look** (`arcade/ArcadeHall.tsx`, `ArcadeHallProps.tsx`,
  `arcadeHallLook.ts`, `arcadeScreens.ts`): smoked-glass walls with a neon
  cap in each room's colour (never hidden or popping away at any camera
  angle; frames, glass and neon are three merged meshes), a lit name board
  over every door, each room's own floor and neon floor logo, a calm
  blacklight carpet in the hall. One shadow light plus hemisphere and
  ambient; neon is self-lit. Cabinets show two-frame attract screens
  flipped by a texture offset. The first version's live title-screen
  preview froze the frame for 0.2-0.6 s whenever the person walked up to a
  cabinet and was removed; frames at a cabinet now take 2-11 ms in a dev
  build (measured with `window.__officeGl.info` and timed `__officeStep`).
- **Games** (`arcade/games/*.ts`, contract in `arcade/retroGame.ts`, registry
  in `arcade/arcadeGames.ts`): Neon Snake, Brick Breaker, Paddle Duel, Block
  Drop, Maze Muncher, Desert Dash, Pixel Raiders, Road Hopper and City
  Defense are original Canvas 2D games (pure state + fixed 60 Hz step, no
  assets, no ROMs), code-split and loaded on first play. Asteroid Run, the
  break room's 3D game, has a cabinet here too.
- **Cabinet overlay** (`arcade/RetroArcadeOverlay.tsx`): a modal at the
  cabinet with marquee, crisp integer scaling, start / pause (P, blur) /
  game over, best score per game in localStorage, keyboard, gamepad, mouse
  where a game aims with it, and a touch pad on coarse pointers. Escape or E
  leaves.

## 5f. Levels (2026-10-03, ranks 2026-10-05)

The person, their pet and every agent level up from real work: finished
Jarvis turns, agent results, quests, missions, new agents, plus small metered
actions in the Verse (daily visit, floors, the office dog, arcade rounds, team
meetings, walks with the pet). Levels climb a military rank ladder from
private to a five-star general. A level card sits under the floor title,
every name plate wears a rank chip, `L` opens the Level Hall screen, and a
promotion plays a gold ring and a rising insignia plate in the world plus the
promotion card on screen. Figures wear their insignia on the sleeves or
shoulder boards, and the person their unlocked uniform, cap and decorations.
The whole contract lives in [level-system.md](level-system.md).

The Level Hall is the levels' own floor, the top one of the building (floor
3 in the elevator, `hallFloorLayout.ts`): a small foyer where the person steps
out of the elevator, and behind its door the hall, 9.2 m wide and 34 m deep.
No agents work there; the person's pet comes along. Visiting it is not yet
paid as a discovered floor: the server's list of floors does not know it, so
the map does not report it. It is dressed as a hall of honour: cream and charcoal marble underfoot, walnut and brass, a red
runner up the middle. The rank wall in the north holds all 24 insignia in a
walnut-framed velvet shadow box (held ranks struck in metal, the current one
framed in brass, the ones ahead as pewter silhouettes) above a brass plaque
with the person's rank, level, XP and next promotion; the studio dais stands
in front of it. Display cases line the runner, one per uniform piece (lowest
unlock in the south): a mannequin in the uniform with the person's own
insignia, a cap on a velvet head form, or the decoration on a slanted velvet
board — the same geometry the figures wear. Unlocked cases are lit, locked
ones stay dim behind smoked glass; a brass plaque names the piece and its
rank, and a click opens it on the promotion road. The framed service guide
stands at the runner's start. Its two checkpoints, the dais (`studio`) and the
guide (`levels`), open the Level Hall screen (level-system.md §6).

## 5g. Stations, HUD and name plates (2026-10-12)

Stations used to be floating tokens over gold floor rings with a label pill
each, and every one opened a narrow side card. They are now the objects
themselves, and what they open is the app's own surface.

- **A station is an object** (`stations.ts`, pure and tested). Every checkpoint
  and every team studio's board is bound to the piece of the room that stands
  for it, by furniture kind nearest to the checkpoint: spawn terminal,
  reception desk, team board, dressing mirror, coffee bar, elevator, Mission
  Control's wall, the Level Hall's dais and guide, and the lead's desks (their
  `desk:<id>` groups). Nothing floats over the floor and nothing is painted on
  it at rest.
- **Showing that it can be used** (`StationObjects.tsx`, `stationRim.ts`): an
  invisible click target the size of the object keeps every station usable from
  the overview, so walking stays optional. While the person stands at it,
  points at it or has it open, the object wears a thin blue rim on its own
  silhouette: each of its meshes gets a shell pushed out along the normals and
  drawn back faces only. The rim fades in and out; reduced motion switches it.
  The lead desk's target is its visitor-side front panel, so the chair and the
  monitors keep their own clicks.
- **One prompt** (`OfficeHud.tsx`): bottom centre, a key cap, the action and
  the object's name ("E · Create an agent · Spawn point"). It names what the
  character stands at, or, with "Click" in place of the key, what the pointer
  rests on from afar. It is a real button.
- **Keyboard and screen readers**: the toolbar's Places button opens a card
  that lists every station of the floor as real buttons (open it, or walk
  there), the rooms' places first and the team studios under "Teams", each
  under its team's name (the studio of agents without a team is "Without a
  team"). Arrow keys move through the rows, right and left reach a row's
  "walk there", Home and End jump; arrow down on the button opens the card
  on its first row. Resting on a row lights its object in the world. The
  card is opaque, as tall as its list down to the stage's lower edge (capped
  at 680 px), and fades at its lower edge while there is more to scroll. The reception's Places tab is the same list.
- **Focus**: closing a dialog (Escape, its close button) hands focus to the
  map's canvas host, so the walking keys answer at once; a docked panel does
  the same on Escape.
- **What a station opens** (`OfficePanels.tsx`, `StationSheet.tsx`):

  | Station | Opens |
  |---|---|
  | Spawn terminal (agents floor) | The camera dives into its screen, then the app's create-agent dialog opens. Agents are created only here. |
  | Spawn terminal (coding floor) | Mission Control's launcher, as a dialog. |
  | Reception desk | The directory: agents (show on the map, open, the agents view), places, the controls guide, settings. `H` opens it on the controls from anywhere and closes it again. |
  | Team board (team room) | Teams: members with their state, meet at the table, the team's real chat, rename, members, delete, new team. |
  | A team studio's board | The same sheet on that studio's team (`{ kind: "team", id: <Studio.board.id> }`). Its "Meet at the board" gathers the team right there, on the standing places in front of the board (`boardSeats`, `TeamMeeting.boardId`); the meeting card then counts who is "at the board" and offers "Go to the board". The board of agents without a team offers to make them one. |
  | The free plot's stand | The same sheet, opened on the new-team form ("Start a team here"). The stand is the furniture piece whose id starts with `team-stand` (`TEAM_STAND_ID`); it selects `{ kind: "team", id: <its id> }`. |
  | Wardrobe mirror | The look editor, docked at the side so the character stays in view and can keep walking. |
  | Lead's desk | Selects the lead (the walkie-talkie panel). |
  | Coffee bar | Calls the free agents to the lounge; using it again sends them back. The answer is one line in the HUD. |
  | Elevator, Mission Control, Level Hall | As before: the floor picker, Mission Control, the Level Hall screen. |

  The teams sheet does one job at a time: the new-team form replaces the
  list, its member list scrolls on its own (search from seven agents up) and
  its buttons stay pinned to the sheet's lower edge.
  Dialogs are built like every other dialog of the app (same scrim, surface,
  header and type scale, the shared button, input, tabs and switch). A team
  sent to the table closes the sheet so the person sees it gather; the
  gathering then shows as a small card under the level card, which also lets
  the team go when its time is up.
- **Live means a real round** (`teamStatus.ts`, pure and tested): "Meet" is a
  gathering on the map only — members walk over, nothing is posted to the
  team and no agent starts work. The card says so ("Launch crew · called to
  the table", "Send them back", no live dot), the team's row and the team
  room's board mark it with a plain "Called". The green "Live" mark, on the
  row and on the board, comes only from the backend's running round
  (teamwork's `TeamRound.running`).
- **HUD**: top left the floor card (name, and one line of working / waiting /
  idle) and the level card; top right the minimap with a five-button icon
  toolbar beside it (follow me, overview, places, the floor's list, help);
  bottom centre the prompt. The compass bar, the six text buttons and the
  permanent controls line are gone: the wardrobe and the Level Hall are places,
  `L` and the level card open the Level Hall. First-time visitors see the four
  essential controls once in a card they dismiss; that is remembered per
  browser profile (`officeSettings.ts`, `hintsSeen`) and the reception's
  settings bring it back. In the IDE side panel the toolbar is a column in the
  corner.
- **Name plates** (`namePlate.ts`, pure and tested): a dot from afar, the whole
  plate within 10.5 m of the camera or 4.6 m of the person, for the agent the
  pointer or keyboard focus rests on, and for the selected one. A plate closes
  again only beyond 12.5 m / 6 m, so it does not flicker at the threshold. Dot
  and plate share one grid cell, so nothing moves when one takes over from the
  other; the plate's button stays in the tab order while it shows a dot.
- **Plates in a crowd** (`plateCrowd.ts`, pure and tested): a plate is wider
  than the figure under it, so people standing together would stack their
  plates. Every frame the plates that want to open report where they would
  sit on screen and are seated in order: the selected or pointed-at agent
  (always), whoever speaks in a team round (with room kept free above the
  plate for its speech bubble), plates that are already open, then the
  nearest to the person. A plate that would cover a seated one, or the
  person's own plate, stays a dot. Opening needs 12 px of clear space,
  staying open only 2 px, so a plate at the edge of another does not flicker.
  The seating is kept per stage (keyed by its scene, released when its last
  plate unmounts), so two offices awake at once never seat each other's plates.
- **In-world labels stay under the HUD**: the viewport is one stacking
  context, so no plate or bubble can lie over a HUD card.
- **Faces in lists** (`AgentFace.tsx`: directory, team rows, member lists,
  member picker) are drawn without the run state: a working agent's symbol
  would turn into its three thinking dots, which in a list reads as a picture
  still loading. The state dot and word beside the face say it. Every face
  sits on a neutral tile from theme tokens with a hairline in the text colour
  round the symbol's own outline, so a white symbol stays readable on a light
  dialog and a black one on a dark dialog.

## 5h. Team campus and the building (2026-10-12)

The maintainer found the agents floor far too small and built round model
providers instead of teams. It is now a campus whose unit is the team: a
street of team rooms round an atrium, with commons people use in between.

- **Teams are studios.** A team is a society chat group (`teams` option, fed
  from `useSocietyChatGroups` in the stage). Every team has a studio; agents
  without a team share the pool studio, which always comes first. An agent in
  several teams sits in the oldest one (ties by id); lead-tier agents keep the
  lead office; a team whose members are unknown still has its (empty) studio.
  `planStudios` decides who sits where, `layout.studios` describes each
  studio (team, seated members, board, huddle places, centre) and
  `Department.teamId` links its desks.
- **A team's lead sits at the head of its studio.** The roster names a lead
  per team (`lead_agent_id` of the chat group, `OfficeTeamInput.leadId`). A
  lead who is a member the roster knows, and who does not sit in the lead
  office, takes the head desk: the first desk of the bench nearest the name
  wall (`dept.desks[0]`). It changes places with the earliest arrival, who
  would sit there; everyone else keeps arrival order. So naming a lead
  moves two people and changing one at most three (old lead back to its own
  place, new lead to the head, the earliest arrival to the new lead's
  place); the studio's size and everyone outside the team stay as they are.
  Leading a team comes before "the oldest team" for an agent in several and
  before the seat cap; an agent named lead of two teams sits with the older
  one. `Studio.leadId` is that seated lead and null in every other case (no
  lead, not a member, unknown, in the lead office): never guessed.
  `leadDesks(layout)` lists the desks. The lead's place is marked
  (`leadMark` in deskKit.ts, drawn as instances by `DeskDressing`): a deep
  red shell on the back of its chair with a bronze cap along the top edge
  and a pad on the seat in the same red (one red in every studio, because
  the studio's own chairs already wear the team's colour; a test holds it
  clear of every studio's fabric, panel and rug), a chair mat in the team's colour
  on the floor under it, and a name stand on the desk's front right corner
  whose plate, in the team's colour, leans back towards the camera. The chair is what the south-east camera sees first
  and it stays when the lead is at the board; the mat is what reads from
  the overview. `leadMark.test.tsx` puts the mark through the real cameras
  at 1600 x 900: in the follow view the shell covers about 43 x 45 px and
  the plate 15 x 12 px, in the overview the mat at least 11 px each way,
  with no monitor, screen, chair, sitter or pendant in front. The plan is
  rebuilt when a lead is named or changed, and by nothing else new.
- **A studio is a room** (`studioShape`, one cell: 11 m wide). At its back a
  name wall capped in the team's colour, the team's name on the west half and
  the studio board in front of the east half with four to seven huddle places
  south of it. Low felt-and-glass screens close both sides (two studios
  shoulder to shoulder share the one between them). The front is planted,
  with a 4.8 m entrance in its middle. Inside: the desks — one free desk to
  grow into, whole facing pairs, spread evenly over as few benches as hold
  them (two members: four desks; twelve: fourteen) — a storage cabinet under
  the name, a sofa by the entrance and a standing table opposite, each with
  its spots; a rug in the team's colour and a slim pendant light over every
  desk row (five centimetres wide, 2.75 m up, on two wires from the ceiling
  line, a soft pool of light on the floor below). Nothing overhead is wide
  enough to stand between the camera and the people at the desks. Only the
  desks grow with the team, so a team of three still has a furnished room.
  Twelve colours, so a full campus never repeats one. A studio seats up to
  32; the newest members of a larger team sit in the pool, and a pool of more
  than 32 opens a second pool studio.
- **The plan** is four cells wide at every size (51.8 m between the window
  strips: four cells, the boulevard and a 1.4 m promenade along each window)
  and grows southwards by a row of studios whenever a row is full, up to
  three rows (twelve studios; later teams fold into the pool). Along both
  windows the promenade leaves 2.35 m to walk between the benches and
  planters at the glass and the outer studios' screens. The
  boulevard (5 m) runs on the floor's axis from the lobby to the team room's
  door; streets between rows are 3.6 m. The main boulevard (9 m) crosses in
  the gap between two blocks nearest the floor's middle, and at the crossing
  lies the atrium. Every route from the lobby to a studio or a north room
  passes over it. Rooms, studios and commons take about 70 % of the plan.
  Sizes including the window strip: 55.0 m x 47.0 m for one row (five agents
  without a team, or fifteen in three teams), 55.0 m x 81.2 m for forty
  agents in eight teams. The floor it replaces measured 24.4 m x 38.2 m plus
  the Level Hall's wing.
- **The atrium** is the campus's heart: the spawn point on a pale stone disc
  inside a bronze ring, a flight of step seating on either side facing it, a
  large tree behind each, and a ring of light over it. The step seating has
  dark risers under pale oak treads that nose out over them; the lowest tier
  is plainly a seat (a linen pad and a back cushion per place, where people
  sit) and loose cushions in the studios' colours lie on the tiers above.
  The ring is a light fitting: a steel band the size of the disc, 2.9 m up,
  whose inner face is a warm lamp, hung on six rods from the ceiling line.
  The lobby's name stands on an arch against the back of the reception desk
  (`Room.arch`), not at the atrium's rim.
- **Commons** are named places with spots, so idle people go there: the café
  beside the lobby (kitchen run, island, standing tables, sofas), the library
  in the north-east corner (bookcases, reading chairs, a sofa on a rug), the
  focus booths in the north-west corner (three booths a person walks into, a
  sofa, a standing table), and in a cell without a studio the free plot or a
  garden court (a lawn, one large tree, two olives, two benches). The free
  plot is the first empty cell, the next team's place: the bare floor taped
  out with dashed marking tape, its lettering on the floor, a stack of moving
  crates and a plant at the back, and at the street side the team stand
  (furniture kind `teamStand`, id `team-stand`, one per plan while a plot
  exists), where a new team is started.
- **Stations** stand in front of what the person uses: the spawn terminal in
  the atrium, the reception desk (the one directory and help station; the
  agent-board totem and the reception's own create station are gone), the
  team board, the wardrobe mirror, the lead's desk, the coffee bar, the
  elevator, and the free plot's team stand.
- **Fittings and planting are data** (`agentsAmbience.ts`, `layout.ambience`):
  screens, cabinets, sofas, standing tables, booths, step seating, the
  kitchen, benches, planters, crates, olive trees and large trees are items with a
  footprint, each an obstacle and a few entries of instanced meshes
  (`CampusFittings.tsx`, `AgentsFloorAmbience.tsx`). Planting is a few
  deliberate groups of two kinds of tree, not rows. `layout.zones` names the
  flat areas (boulevard, plaza, atrium, plot, garden, booths, library, café)
  for the ground (`CampusGround.tsx`) and the maps.
- **Maps:** the minimap and the full map paint the paved boulevards, the
  atrium, the commons' carpets, the free plot, trees, fittings and every
  studio's name wall. The full map's sheet takes the plan's shape, names
  each studio on the street behind its wall (shrunk or cut to the studio's
  width, clear of the people inside) and each commons along its south edge;
  the pool is "The Pool". The minimap zooms out to 90 m.
- **The building** (`BuildingShell.tsx`, agents floor and Level Hall): the
  tower's dark body under the slab, and on the floor's far sides a 3.4 m
  window wall with steel mullions and a ceiling edge. The floor is shown like
  a cut-open model: a side's window wall stands only while the camera is on
  the opposite side of the floor; the other sides keep the glass balustrade.
  Outside lies a city at night that stays a backdrop: a few dozen unlit
  towers a shade lighter than the deep navy sky, the first 62 m from the
  building, every roof at least 24 m below the floor and the nearest ones
  lowest. About one window in twenty is dimly lit, from one small tiling
  texture; a tower sinks into the sky's colour towards its foot and with its
  distance, the scene's sun never reaches it, and the faintest glow lies
  over the streets where detail would be. Apart from the sparse windows
  nothing outside is brighter than a dark navy (#1a2233). The office is
  always the brightest and most detailed thing on screen.
- **One material language** from the studios to the last room: light plank
  oak, limestone and felt on the floor; light oak for timber; dark steel for
  metal, with bronze as the one accent; steel-framed clear glass with a
  frosted band for every wall. The rooms' floors come from that family
  (`CAMPUS_ROOM_FLOORS`, agents floor only): the break room lies on the open
  floor's plank oak, the lobby on the window band's limestone, the wardrobe
  on a terrazzo of the same stone with oak chips, the team room on the focus
  booths' slate felt, and the lead office on the same oak a tone deeper,
  laid as a chevron. The lead suite stays the richest room but in the
  family: smoked oak, bronze, cognac leather and a slate rug (`LEAD_SUITE`),
  behind the same glazing as every room. The team room's timber is the
  campus's oak, and the rooms' small metal details are the same bronze.
- **Cost** (2026-10-12, counted without a GPU as visible meshes plus the
  shadow-casting ones again for the shadow pass; a browser adds one merged
  mesh per textured material):
  - The agents floor's furniture, room signs, studio walls and meeting chairs
    never change once built, so they are drawn merged (`StaticBatch.tsx`):
    parts whose material is only a colour share one material per finish and
    carry the colour in their vertices, textured and glowing parts merge per
    material, parts smaller than a hand's width cast no shadow. A station's
    prop is merged within its own group, so its rim still finds it. The
    static floor is 441 / 452 / 507 draw calls for 5 / 15 / 40 people (it was
    about 2450 piece by piece for 15) and 0.48 / 0.60 / 0.92 million
    triangles over both passes.
  - Planting, studio fittings, commons, desks and the city are instanced:
    another studio adds no draw call for its furniture, another tree none.
    Grass blades are eight-sided spindles and olive foliage twenty-sided
    clusters (planting was the largest triangle count on the floor). A crown
    is a few large clusters (fourteen on a large tree, eleven on an olive),
    and two of its three leaf tones throw its shadow.
  - A glass wall run is three meshes whatever its length.
  - A figure is 19 meshes (13 casting, 32 draw calls) and about 31 thousand
    triangles over both passes: its rigid head and torso and each half of an
    arm (shoulder cap, sleeve and upper arm; forearm, cuff, hand and thumb)
    are merged in the frame of their joint, so every pose moves them as
    before, and its spheres have fewer segments. An arm's merged half casts
    as one, so the figure's shadow keeps its arms. The merged parts are baked
    again only when the look or what is worn changes by content
    (`contentKey`): the level store's minute-by-minute re-read hands out new
    JSX for the same regalia, and that bakes nothing. It was 41 meshes (28
    casting) and 43 thousand triangles in a single pass. The legs stay
    parts of their own: shoe and sole differ in finish, so merging them
    would save nothing.
  - Rounded boxes have one bevel segment, the task chair's tubes and bevels
    fewer segments; small things on desks cast no shadow.
  - The sun's shadow map is 4096 px on this floor, so shadows keep their
    detail over the longer plan.
  - A studio's lettering shows a name the person typed, so its texture is
    never cached by its text: the wall owns it (`ownedCanvasTexture`) and
    disposes it when the team is renamed or deleted. The session-long
    texture cache only holds keys from fixed sets (kinds, palette entries,
    a locale's own strings).

## 5i. Team life, teamwork and movement (2026-10-12)

The maintainer asked for teams that visibly work together, mechanics that
hold up, and agents that behave well in the larger world. The rule that
governs all of it: the floor shows what is real. Run state, a team's round
and a message between two agents come from the roster, the team's meeting and
the board; idle life is seeded choreography; nothing else is ever staged.

**Agents belong somewhere** (`officeBehavior.ts`, `officeTeams.ts`). The state
rules are unchanged: working sits at its own screen, waiting stands at its
desk, paused rests. An idle agent with a studio picks its next activity from
a weighted table (`TEAM_IDLE_WEIGHTS`, `POOL_IDLE_WEIGHTS`):

| Idle choice | Team member | Agent without a team |
|---|---|---|
| Sit at its own desk (40–90 s) | 30 | 20 |
| Look in on a studio mate who sits at their desk | 14 | — |
| Stand at the studio board | 12 | — |
| Stroll between its studio's benches | 12 | 10 |
| A hangout place round the corner of the studio | 12 | 10 |
| Look in on a working colleague | — | 8 |
| A trip to a shared place anywhere on the floor | 14 | 40 |
| A stroll within 12 m of the studio | 6 | 12 |

Four in five of a team member's idle choices keep it at home; an agent in
the pool studio uses the shared places far more. A trip earns a long stay
(below), so the weights are tuned by the clock: simulated, a team member
spends about two thirds of its idle time in and around its studio and 16 %
walking; an agent without a team a little over half. A trip picks among all
free shared places, weighted by what the place is (couch 22, coffee 18,
window 12, cooler 8, arcade 8, books 7, beanbag 8, team table 4, team board
3) and by how far from the studio it lies: at the trip's reach a place is
half as likely as one next door, at twice the reach a fifth. The reach is
10 m with up to six agents on the floor and grows to 20 m at thirty, so a
handful of agents on a large campus keep to their neighbourhood and the
commons near it, and nobody crosses the campus for a window when there is a
coffee round the corner. The same home activity is never taken twice in a
row. Standing at the studio board and looking in on a studio mate are idle
life, and the name plate says so ("In the studio"); "At the team board" is
shown only for a gathering that is real, a running round or a meeting the
person called there. A visitor stands in the gap between the colleague's chair and the next
one (out of the aisle behind the chairs and out of the way the colleague
gets up) and watches: the talking pose is kept for exchanges that really
happened. Every standing place beside a desk and at a board is reserved
through the same book as the spots. A stroll ends on open ground (floor a
body's width to every side), so nobody stops for a rest in a doorway. A floor
without studios (the coding floor) keeps its plain idle day.

Long ways are walked briskly (1.35 m/s up to 9 m of route left, rising to
2.1 m/s at 26 m), and an agent that got work hurries to its screen (2.1 m/s
on anything but the last steps). Measured along real routes from the lobby
to a desk, corners and getting up included, an agent averages 1.45–1.6 m/s.
A stay lasts at least 3.2 times as long as the walk to it would take at
walking pace, up to 150 s. Simulated over twenty minutes with
60 idle agents, about one agent in six is on the move at any moment.

**Real teamwork** (`teamwork.ts`, `useTeamRounds.ts`). Two things are shown,
because they are what the app can see:

- *A round of a team.* A team's meeting is read from
  `GET /api/society/chat-groups/{id}/meeting` (running, transcript, the room's
  next speaker); that a round opened or settled and each line said in it also
  arrive on the socket (`SocietyRoomChanged`, `SocietyMessageSent` with a
  `meeting:<group>:…` room id). While a round runs, its idle members walk to
  their studio board and stand there in loose arcs (2.2 m, 3.3 m and 4.4 m
  from the board, every place more than a metre from the next), the arc
  nearest the board first; when it settles they return to their desks. They
  take no place within 1.25 m of the person's character, and when the person
  walks up to one of them (closer than 0.95 m) it moves to another place in
  the arcs. A working member stays at its screen, with one exception that is
  the round itself: the member contributing right now (the room's next
  speaker) reads "working" and stands at the board in the talking pose, with
  a thought bubble until its line is written. A line said in the round
  appears over its speaker in its own words for up to nine seconds, and gives
  way the moment the next member has the word: only one member of a team
  carries a bubble at a time, and a listener at the board shows none of its
  own. A member of the team that sits in another studio comes to the board
  of the team whose round it is. Waiting and paused members stay where their
  state puts them. The person's own call still outranks a round. A meeting
  the person starts at a studio's own board uses the same arcs:
  `boardSeats(layout, studio, members)` gives every member its place,
  and `startMeeting` holds them there as it holds a team at the team room's
  table.
- *A message from one agent to another.* `SocietyMessageSent` without a room,
  between two roster agents other than the lead (ASSIGN, SAY, QUERY, ANSWER,
  PROPOSE). The sender's bubble shows "To <name>: <text>"; once the sender is
  idle (within 90 s) it walks to a place beside the receiver's chair, or to
  where the receiver stands, and stays eight seconds. A working sender never
  leaves its screen. The lead's own messages remain its pet's errands.

Reads are scheduled, jittered (2.4–3.6 s between ticks), capped at four at
once and silent while the stage sleeps. The ticks do not wait for the reads:
each is folded in when its answer comes, is given up after eight seconds and
aborted when the poller stops, so a request that hangs holds nothing back.
There is one poller for the whole app: when two floors are awake at once
(the Agents view and the IDE's side panel), one of them reads and the other
takes over when it sleeps. What is read: running rounds every tick, a team the
roster shows in a room every six seconds, a team whose board is near the
camera every eighteen, and the sweep. The sweep makes the floor independent
of the socket: every team is read once after the stage wakes (two a tick)
and again about once a minute, so a round that was already running when the
Verse was opened, or whose event was missed, is found. A round that fails to
read five times in a row is no longer shown as running.

A team can have a lead (`lead_agent_id` of its chat group, `Studio.leadId` on
the floor). The floor shows that and invents nothing more: the studio board
lists the lead first and names it ("Lead: <name>"), and in a gathering at the
board (a running round, or a meeting the person called there) the lead stands
at the centre of the front arc when it is among those gathering; the others
leave that place free while any other is. A working lead stays at its screen
like anyone, an idle lead lives the same idle day as its team, and a team
without a lead is planned and drawn exactly as before.

Not shown, because the app cannot see it: when a line was said (the meeting's
messages carry no time), a task shared by several agents, and whether a
hand-off was accepted.

**Studio boards** (`StudioBoards.tsx`, `studioBoardContent.ts`). Each board's
face shows the team's name, its members with their real run state (the
speaker marked), and the newest lines of the team's chat, or says honestly
that nothing has been said, that the chat is still being read or cannot be
read right now, or that the pool has no team chat. A face is a canvas texture on the board's own paper
sheet, created the first time the camera comes within 60 m and redrawn only
when its content changed. The three boards nearest the camera (within 30 m)
are live. The faces take no pointer events; the board's station does.

**Movement** (`officeMotion.ts`, `officeWalk.ts`). One controller walks every
agent and the person's click-to-move:

- Every step is checked against the floor and against the other bodies; the
  candidates are the steered direction, straight at the waypoint, then a slide
  past whatever is in the way, right before left. When none is free the figure
  waits. Bodies keep 0.62 m between their centres.
- A figure turns before it walks (it slows as soon as it faces more than
  about 30° off its way, down to a crawl of 8 % of its pace), faces where it
  moves, and lands exactly on its last waypoint. Leaving a seat it waits for
  whoever stands in its way and leaves on the free side.
- The route is recomputed when steering carried the figure off it, and when
  the floor plan changes under a walk (a team was created or deleted). A plan
  survives a rebuilt floor only if its place still exists there; otherwise the
  agent plans again, and a target the new plan walls off is reported instead
  of walked at.
- A figure that makes less than 0.4 m of progress in 1.5 s takes a detour
  planned round the bodies near it. After two detours that did not help, or
  when a walk overruns three times its expected duration plus eight seconds,
  the walk ends. Within 3 m of its target the figure is placed: on its
  reserved seat, or on free ground at the target, never on top of anybody.
  Further away it gives the walk up and its agent plans again from where it
  stands: nobody is moved across the floor. The one exception is a place the
  agent's real state demands (its screen while it works, the board while its
  round runs): after two walks given up in a row it is placed there. The
  person's own character always just stops.
- Blocked beside someone who stands on the place it was heading for, a figure
  stops there: that is an arrival.

**Camera and character** (`OfficeCameraRig.tsx`, `officeCamera.ts`,
`wallCutaway.ts`, `OfficePlayer.tsx`). While the character stands in a walled
room, the sides of that room the camera looks in through drop to 12 % of
their height and rise again when the character leaves or the camera turns;
the rule is by side, so nothing flickers while the character walks about
inside. The rig moves any object tagged `userData.officeWall`. The overview
is fitted to the viewport: the look-at point is moved until the plan sits in
the middle of the view (seen at an angle, the near corner looms larger than
the far one), and the camera comes as close as the plan allows, so the plan
spans 85 % of whichever axis binds — the height in a wide window, the width
in the IDE's narrow panel. The zoom limit grows with the floor so the wheel
can always reach that view. A wheel notch zooms 12 % of the way up close and up to 35 % from
90 m out, so the overview of a large campus comes down to a studio in about
five notches while the last metres stay fine. Following is exponential (the
same motion at any frame rate); resumed more than 12 m from the character,
the view glides over in 0.6 s instead of snapping, and after the overview it
also glides back to the distance the person walked at (15 m when there was
none), unless the person zoomed by hand meanwhile. A remembered view (after
a monitor dive, or from the last visit) is checked against the current floor
plan: one that looks at a place the floor no longer has starts from the
character instead, and a camera that would stand inside a wall backs out
along its line of sight. A click-to-move target on free floor is the target
itself. A click on a bench desk, its chair or whoever sits there resolves to
a standing place at that desk (in the gap beside the chair, where a visiting
colleague would stand, else behind it), and anything else solid or occupied
to the nearest free floor beside it, 0.75 m from everybody: the character
never ends up on a chair, in a desk or inside a figure. Sitting down stays
its own action (the executive chair, Mission Control's chair). The person's
pet follows on free floor that is nobody's, 0.5 m from every agent. A long
click-to-move route is
jogged (up to the sprint pace of 4.4 m/s with more than 22 m to go) and ends
in a walk over the last 7 m; and a character left standing in a solid cell
by a rebuilt floor plan is put on the nearest free ground.

**Dev handles** (development builds only):

- `__officeLife.walkers()` — one row per agent: `team`, `studio`, `role`
  (its part in a running round: none, gather, speaker, busy), `plan`, `phase`,
  `target`, `spot`, `with`, `at`, `remainingM`, `stuckS` (seconds without
  progress on the current walk), `walkS` and `speed` (seconds walked and
  average m/s along the route on the current walk, by the frame time the
  walker was really given), and counters since it mounted: `replans`
  (detours), `rescues` (placements), `blocked` (walks given up), `repaths`
  (route repairs), `near` (arrivals beside an occupied place), `lost`
  (targets a new floor plan walled off). `__officeLife.walker(id)` is one
  row, `__officeLife.stuck()` the rows with a detour, a placement or a walk
  given up.
- `__officeLife.teamwork()` — rounds by team (`running`, `speakerId`,
  `members`, `lines`, `spoke`) and the messages still to be walked over;
  `__officeLife.store` is the store itself, so a round or a message can be
  set by hand; `__officeLife.boards()` lists the teams whose board is live.
- Measuring speeds: while the frame loop runs, `__officeStep(frames, dtMs)`
  renders `frames` frames but each gets the real time since the one before,
  not `dtMs`; distance over `frames x dtMs` is therefore not a speed. Read
  `speed` from the handle instead.
- `__officeCamera.cut()` — the walls lowered right now; `.walls()` how many
  wall objects are tagged; `.limits()` this floor's zoom limits.

## 6. Plan

1. First map (done 2026-09-28).
2. Walkable prototype (done 2026-09-28): rooms, checkpoints, agent life, own character.
3. **Review:** the maintainer plays it and gives feedback on look, camera, rooms and actions.
4. Polish: typing animation while working, speech bubbles for "waiting for you",
   door animations, agents greeting the person, sound.
5. Scale: instanced chairs/props beyond desks, measured frame times on a laptop
   GPU and a low-end integrated GPU, macOS/Linux WebViews.

## 7. Verification so far

- Unit tests: layout (grouping, stable seating, no overlap, camera framing),
  navigation (every seat, spot and checkpoint reachable from the elevator for
  0/10/40 agents; paths never cross obstacles), motion, behaviour (state rules,
  exclusive spots, determinism), props (every kind renders inside its footprint).
- Team campus (2026-10-12), unit tests: team grouping (several teams, an
  agent in two, unknown members, leads, the studio cap), studio sizing, stable
  seating, a studio's enclosure and entrance, the furnished share of the
  plan, no two solid things in one place, free doorways and streets, every
  seat, spot, station and studio board reachable for zero, one, three and
  eight teams and teams of two and twelve, the route over the main
  boulevard, the Level Hall's floor and its elevator stop, the map painting
  and sheet, and a mount of the whole dressing without a GPU (mesh counts,
  bounds). The first plan was checked in a browser by the orchestrator and
  reworked into this one, which the orchestrator checked too. The third
  round (the receded city, pendants instead of baffles, the atrium's ring,
  the step seating, the rooms' materials, the promenade and the furnished
  free plot) is covered by unit tests for the plan (the stand and its
  standing place, the arch at the desk, 1.2 m or more to walk along both
  windows) and was then checked in a browser by the orchestrator.
- Floors (2026-10-12): `progression/verseFloors.test.ts` reads
  `VERSE_FLOORS` from jarvis/progression/service.py and holds it equal to the
  client's `METERED_FLOORS` and the elevator's `OFFICE_FLOORS`; a world
  action the server refuses is logged (`reportWorldAction`).
- Team life and movement (2026-10-12), unit and component tests; a browser
  run on a scripted roster confirmed the live board, the gathering, the wall
  cutaway, the route marker and stuck recovery. Tested: the idle weights and
  that a team member's day stays at home; trips staying near on a five-agent
  floor; exclusive places; a round gathering its free members in arcs with a
  metre between them, the speaker, the return to the desks, making room for
  the person; a round found by reading alone; a message walked over; the
  reducers behind rounds and messages and which meetings are read when; the
  board's content; a long diagonal walk across a 60-agent campus (on the
  floor all the way, no gliding, exact arrival); two walkers swapping places
  through a door and in a 1.6 m aisle without touching; a studio built on a
  walker's route; detour, placement, a walk given up and the walk budget; the
  wall cutaway by side; the overview holding every corner of small and large
  floors in wide and portrait viewports; the wheel's reach, the follow
  distance after the overview and a remembered view on a rebuilt floor; the
  click-to-move pace; a click on an occupied bench seat, a desk top and an
  empty chair ending beside them. A mounted floor of 40 agents (a quarter working, one
  team round) simulated for ten minutes kept every pair of bodies 0.62 m
  apart, with 17 detours, no placement and no walk given up.
- Runtime (Chrome, dev build, live roster of ten agents): walking by click and
  by keyboard, camera follow and overview, nearby prompt and E, agent panel,
  "call over". Desks are instanced; the full floor measured ~730 draw calls and
  ~18 ms per frame on the development machine.
- Runtime: checked in Chrome against the live roster (ten agents, one lead)
  through a temporary dev preview: rendering, click on figure and on pill.
- Not yet measured: frame time and device coverage; macOS/Linux WebViews.
