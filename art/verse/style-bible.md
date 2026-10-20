# Verse capital ship: interior style bible

Status: v1, 2026-10-19. This is the art-direction source of truth for the interior decks of the
Dodaios capital ship. The ship is 1.6 km long. The decks are seen top-down at about 60° as cut-away
plates: pre-rendered Blender Cycles backgrounds with realtime characters on top.

The look is **fleet-navy brutalist industrial**. It descends from the capital-ship interiors of a
classic space-opera film series and its recent prequel series, which this document calls "the
reference films". Every rule below is written so that an artist who has never seen those films
can build the look from numbers.

**Legal rule.** This file and every file in the repository describe the style generically.

- They never name the franchise, its ships, factions, characters, studios, alphabets or titles.
- They never reproduce its insignia, rank-tile grids, helmet faces or vehicle silhouettes.
- Where the reference has an iconic element, this bible specifies an original variant.
- Reference images stay on the art lead's machine and are never committed.

**Confidence tags** on numbers:

- **[S]** stated by a production, vendor or replica source.
- **[E]** estimated from film frames against human scale (a crew member is 1.75 m).
- **[D]** a design decision for this project, chosen to evoke the reference while reading well top-down.

---

## 0. The look in six sentences

1. The architecture is a disciplined grid of chamfered rectangles: 45° corners, elongated hexagons and trapezoids, never organic curves. The only curved forms are cylinders and big circular rooms.
2. Colour is almost absent. Black, graphite, cool grey and white carry 95% of every frame. Light, not paint, does the work.
3. Light comes **from the architecture**: panels set into walls, ceilings, floors, console faces and rim copings. There are no visible lamps, no glowing lines added for decoration, and no omni fill.
4. Floors are either **black mirror gloss** (command, ceremony, hangar) or **pale satin grey plate** (working decks). The gloss floor doubles every light and makes the room feel twice as tall and twice as cold.
5. Accents are small, rectangular and functional: grids of white and red square indicators, a few amber and blue screens. A rare warm wall panel marks a control room. Every accent means something.
6. Scale is conveyed by repetition. The same portal, rib, light panel or console repeats at an exact rhythm until it disappears into haze, and the people are small against it.

---

## 1. Scale, grid and deck heights

| Item | Value | Tag |
|---|---|---|
| Ship length | 1,600 m | [D] (the reference ship class is 1,600 m [S]) |
| Base module | **0.6 m**. Every panel, tile and light dimension is a multiple or simple fraction of it. | [D] |
| Major bay | **2.4 m** (4 modules): wall bay, light-panel rhythm, floor-plate rhythm on working decks | [D] |
| Structural frame spacing | **4.8 m** (2 bays): portal frames, ribs, buttresses | [D] |
| Standard deck, floor to floor | **4.2 m**: 3.0 m clear plus 1.2 m service plenum | [D] |
| Command and ceremony deck clear height | 4.8–6.0 m | [D] |
| Hangar clear height | 24 m main bay, 12 m secondary bay | [D] (the reference stage was 13.7 m to the grid, with mattes above [S]) |
| Average crew height | 1.75 m; armoured marine 1.85 m; tallest robot 1.72 m | [E] |
| Eye height (standing / seated) | 1.62 m / 1.20 m | [D] |

**Rule:** if a dimension is not in this document, snap it to the 0.6 m grid. Snap sub-module details
to 0.15 m, 0.3 m or 0.05 m.

---

## 2. Architectural language

### 2.1 Shape grammar

- **Chamfer, don't fillet.** Every outside corner of a room, frame or console is cut at 45°.
  - Architectural chamfer legs: 0.3 m on portals and 0.6 m on room corners.
  - Furniture chamfer legs: 0.05–0.15 m.
  - Fillets are allowed only on furniture edges (≤ 10 mm) and on cylinders.
- **The elongated hexagon** is the signature cross-section: vertical sides with 45° upper and lower chamfers. Use it for tubes, door frames and portal outlines. Seen from above it reads as a rectangle with bevelled shoulders.
- **The trapezoid** is the signature opening: viewports alternate upright and inverted trapezoids along a curve, and wall reliefs taper upward.
- **Splayed feet.** Portal frames and buttresses widen at the floor with a 45° kick, about 0.4 m tall, so the structure looks planted and load-bearing.
- **Cylinders** appear only as ducts (Ø 0.9–1.2 m), pilasters (Ø 0.6 m), lift shafts (Ø 2.4 m), reactor columns and round rooms.
- **Stepped profiles.** Frames, sills and copings step down in 2–3 risers of 0.05–0.1 m. Flat slabs with one plain edge look cheap; avoid them.
- **Symmetry.** Every room has one main axis, and the layout is mirror-symmetric about it unless a function forces otherwise, such as a side door or a lift. Deck-plan symmetry is visible from above.

### 2.2 Corridor cross-sections

All widths are clear widths at the floor unless noted.

```
TYPE A  SPINE CORRIDOR (main circulation)            TYPE B  HEX TUBE (connector / service)
        ____________________________                          ________
   ____/  duct  |light|  duct       \____                    /  1.6   \       ceiling 2.8 m
  |   0.3 chamfer at portal head       |                    /  45°     \
  |                                    |  3.3 clear        |            |  vertical 0.6-2.2 m
  |                                    |  under portal     |    2.8     |
  |___/  splayed foot 0.4 h        \___|                    \  45°     /
       |<------- 4.2 clear ------>|                           \__1.6___/      floor walkway 1.0 grating
```

| Parameter | A Spine | B Hex tube | C Panel corridor | D Clinical corridor |
|---|---|---|---|---|
| Clear width at floor | 4.2 m [D] (reference set about 4–5 m [E]) | 1.6 m [D] | 3.6 m [D] (3.0–3.6 m [E]) | 3.0 m [D] |
| Maximum width | 4.8 m between wall faces | 2.8 m at mid height | 3.6 m | 3.0 m |
| Height | 3.3 m under portal header, 3.6 m to ceiling soffit, ducts below the soffit to 3.0 m | 2.8 m | 3.0 m | 2.7 m |
| Wall profile | Vertical panels between portals | Lower 45° chamfer from floor to 0.6 m; vertical from 0.6 to 2.2 m; upper 45° chamfer from 2.2 to 2.8 m | Vertical | Vertical |
| Structural rhythm | Portal frame every **4.8 m** | Rib every **1.2 m** | Light-panel unit every **2.4 m**, cylindrical pilaster every 9.6 m | Light bar every 2.4 m |
| Floor | Pale satin grey plate, plus two black grating strips 0.9 × 2.4 m centred 1.2 m off the axis | Black gloss shell, plus a 1.0 m warm-lit grating walkway | Black mirror gloss | White satin tile 0.6 × 0.6 m |
| Light | Ceiling troughs between ducts, plus red/white linear strips in angled reveals | Rim light on every rib edge, plus floor uplight through the grating | Vertical wall-light units, 0.6 × 2.3 m | Recessed ceiling bars, 0.15 × 1.2 m |
| Use | Main spine and deck ring | Short connectors (≤ 30 m), escape tubes, reactor access | Ceremonial and command approaches, detention, lift lobbies | Medical, labs, simulator, detention cells |

The Type B tube is the most recognisable silhouette, so keep it short. A 30 m tube with 25 ribs reads; a 200 m tube reads as a screensaver.

### 2.3 Portal frames (bulkheads)

- **Outline.** Elongated-hexagon or chamfered-rectangle opening: vertical jambs, a 0.3 m 45° chamfer at each head corner, and a 0.4 m splayed foot at each jamb base.
- **Size.**
  - Frame face 0.4 m wide, depth 0.6 m; it stands proud of the wall by 0.15 m.
  - Opening: 4.2 m wide × 3.3 m clear in Type A; 2.4 × 2.7 m for room entrances.
- **Detail.** Two stepped returns of 0.05 m on the inner edge. A 6 mm seam every 0.6 m along the face.
- **Lit variant** for command areas: a dotted line of small white rectangular lamps (40 × 15 mm, pitch 0.15 m) follows the inner chamfered edge.
- **Never** put a continuous glowing tube around a portal.

### 2.4 Wall panel system

- **Panel field sizes.** Horizontal panels 1.2 × 0.6 m on working decks; vertical panels 0.6 × 2.4 m on command decks. [D] (reference corridor panels read about 1.2 × 0.6 m [E])
- **Seams.**
  - 6 mm wide × 4 mm deep square reveal between panels.
  - Every panel edge has a 3 mm × 45° bevel; this is what catches the light.
  - Major joints between bays are 20 mm wide × 15 mm deep.
- **Inset fields.** One panel in four carries a recessed field: inset 20 mm, with a 50 mm border, often a tapered trapezoid (wider at the bottom, top 70% of bottom width).
- **Base.** A 0.3 m tall plinth or vent strip at floor level, recessed 20 mm, with horizontal slots 0.15 × 0.012 m at 25 mm pitch. A 0.05 m cornice return sits at the ceiling line.
- **Wall-light unit** (signature panel) [S size, D pattern]:
  - Size 0.6 × 2.3 m: a dark panel holding three columns of vertical pill-shaped lamps.
  - Each lamp is 40 mm wide, 80–320 mm long, with full round ends.
  - Arrange the lamps in a **non-repeating pattern of three lengths** (80, 160, 320 mm), 60 mm column gap, 40 mm vertical gap.
  - Make 4 pattern variants and rotate them; never mirror-repeat one pattern down a corridor.
- **Greeble ratio.** Plain panel to detailed panel is about **3 : 1** on walls and **1 : 2** on ceilings. Walls are calm; ceilings are busy.

### 2.5 Floors

| Floor type | Plate size | Seams | Finish | Where |
|---|---|---|---|---|
| **Black mirror gloss** | 1.2 × 1.2 m (rooms), 2.4 × 2.4 m (hangars and halls) [E: about 2.4 m in hangar frames] | 3 mm dark seam, plus a 6 mm brushed-steel inlay on every 4th line; 40 × 40 mm steel corner stud at inlay crossings | Roughness 0.06–0.12, clearcoat | Bridge walkway, briefing, hangar, ceremonial halls, panel corridors |
| **Pale satin grey plate** | 1.2 × 1.2 m | 5 mm recessed seam | Roughness 0.45 | Spine corridors, pit floors, engineering, mess |
| **Grating** | 0.9 × 2.4 m panels | 25 mm bar pitch, 5 mm bars, 40 mm deep, black | Roughness 0.5, metallic | Corridor strips, catwalks, reactor galleries, hex tube walkway (warm-lit from below) |
| **White clinical tile** | 0.6 × 0.6 m | 4 mm grey seam | Roughness 0.25 | Medical, simulator, detention cells |
| **Hangar deck** | 2.4 × 2.4 m | 10 mm seam; lashing rings Ø 0.15 m at plate corners on a 4.8 m grid | Black gloss (ceremony bay) or mid-grey satin (working bay, roughness 0.55) | Hangars |

Flush details sit at 1 per 2–3 plates on working floors:

- Oval hatch pulls, 0.12 × 0.04 m.
- Rectangular vent grilles, 0.6 × 0.3 m.
- Round floor lights, Ø 0.06 m, on a 2.4 m grid in hangars only.

### 2.6 Ceilings and light panels

- **Working decks.**
  - Recessed light troughs 0.6 m wide run along the corridor between ducts. Each holds diffuser panels 0.6 × 1.2 m with 0.15 m gaps.
  - Colour temperature 5600–6500 K.
  - Panel luminance is uniform. Don't add hotspots or visible LEDs on the diffusers.
- **Command decks.**
  - Ceilings are dark (graphite) and heavily structured: beams 0.6 m deep every 2.4 m, long rectangular plates and 2–3 tiers of depth.
  - Sparse pin and slot lamps (20 × 80 mm), white with about 1 in 6 red.
  - The ceiling is **not** a light source here; the floor and consoles are.
- **Clinical and staff rooms.** One big ring or disc luminaire per room: Ø 4–6 m, a diffuser disc framed by a ring of vertical white fins (0.05 × 0.6 m, pitch 0.12 m). Under it, a white faceted-tile ceiling or dome.
- **Red and white linear strips.** 0.03 × 1.2 m strips set into the 45° reveals of ceiling troughs, in pairs: one red, one white, 0.1 m apart. They are an accent only, never the main light.

### 2.7 Doors

| Door | Clear opening | Leaf design | Frame |
|---|---|---|---|
| Personnel sliding door | 1.8 × 2.5 m [D] (reference about 1.8–2.2 × 2.5–2.7 m [E]) | Two leaves split vertically; each leaf has a vertical light slot (0.04 × 1.2 m) at the meeting edge | Chamfered head 0.3 m; frame 0.3 m face, 0.4 m deep |
| **Diagonal blast door** | 3.0 × 3.0 m [D] | Two leaves meeting on a 45° diagonal seam, each with a 0.2 m raised diagonal rib along the seam and one 0.3 m square hazard plate | Recessed 0.6 m into the wall; cylindrical pilasters Ø 0.6 m either side |
| Hatch door (hex) | 1.2 × 2.2 m elongated hexagon | Single leaf sliding up into the head | Lit-edge variant for command |
| Cargo shutter | 6.0 × 4.8 m | Horizontal slats 0.3 m with a black/hazard-yellow diagonal band on the bottom slat | Splayed-foot portal |
| Hangar magnetic aperture | Up to 72 × 18 m, rounded-rectangle opening, corner radius 3 m | No leaf: a field plane with faint blue-white surface sheen (alpha 3–6%) | A **glowing white frame band 1.2 m wide**, the only large continuous emitter in the ship |

Door states: closed is dark. Opening shows a red slot lamp for 0.5 s, then the leaves slide at 2 m/s.
Locked doors show a single red 0.1 × 0.1 m lamp on the frame at 1.4 m height.

### 2.8 Railings and edges

The reference is notably **railing-poor**. Danger edges (crew pits, reactor catwalks, chasms) are mostly
unprotected, which is part of the cold, inhuman feel.

- **Crew pit coping:** 0.3 m wide brushed-steel or pale-grey lip, 0.05 m upstand, no railing.
- **Galleries above hangars and work halls:** a single thin rail, Ø 0.04 m tube at 1.0 m, with a mid rail at 0.5 m and posts every 2.4 m. Graphite. No glass.
- **Reactor catwalks: no railings at all.** Edges are marked with a 0.05 m white edge line and nothing else.
- Stairs get one handrail only, Ø 0.04 m at 0.9 m.

### 2.9 Columns, ribs, buttresses

- **Hangar and hall buttresses.**
  - A-frame or raked ribs: the wall face leans inward at 10–15° from vertical over the bottom 6 m, then goes vertical.
  - 0.6 m wide, one per 4.8 m.
  - Each carries a **vertical column of white dash lamps**: 0.1 × 0.3 m, gap 0.15 m, 8–16 dashes. Every third buttress adds a red strip 0.05 × 2.4 m.
- **Cylindrical pilasters:** Ø 0.6 m with 3 horizontal 10 mm grooves at 0.3, 1.2 and 2.4 m. Used at blast doors and in panel corridors.
- **Room corners:** 0.6 m chamfer. Large rooms get a 0.6 m deep rib every 4.8 m on walls and ceiling.

### 2.10 Crew pits

These are the heart of the command bridge, and also used in control rooms.

| Parameter | Value | Tag |
|---|---|---|
| Depth below walkway | **1.7 m**. Seated crew eye height (1.20 m) sits 0.5 m below walkway level, so officers look down onto heads. | [S fan analysis] |
| Pit floor width | 3.6 m | [E] |
| Plan shape | Long rectangle with 45° chamfered ends (octagonal); the inner long side follows the walkway | [E] |
| Pit wall consoles | Full-height cabinets, 1.7 m (floor to coping), 0.6 m deep, bays 0.6 m wide; vertical white light bar (0.05 × 0.9 m) between every 2 bays | [E] |
| Freestanding duty consoles | 6 per pit side (reference: 6 [S fan]); 2.4 m pitch along the pit | [S]/[D] |
| Console orientation | Facing the bow (perpendicular to the walkway) on the main bridge; parallel to the walkway in secondary control rooms | [S]/[D] |
| Access | Straight stair at the aft end of each pit: 9 risers × 0.19 m, treads 0.28 m, width 1.2 m | [D] |
| Coping | 0.3 m wide, 0.05 m upstand, brushed steel or pale grey; **lit underside** (a 0.02 m white strip under the lip washing the cabinet faces) | [E] |
| Population | 6–12 seated crew, 1–2 standing supervisors, 2 armoured guards at the pit entrance | [S fan] |

### 2.11 Command walkway and viewports

- **Walkway.** 3.6 m wide, running from the rear foyer to the viewport sill. Black mirror gloss in 1.2 m tiles with steel inlays. A 2-lamp white marker (0.04 × 0.15 m each, 0.1 m apart) sits flush in the floor every 2.4 m along both edges.
- **Viewport wall** (the bow):
  - A shallow arc (half-ellipse in plan) of **7 or 9 panes**.
  - Panes are trapezoids alternating upright and inverted, about 2.0 m tall [S fan] and 2.4 m wide at the wide edge.
  - Sill at 1.0–1.1 m above the walkway [S fan / E].
  - Mullions 0.6 m wide, stepped in 3 risers of 0.1 m.
  - A console shelf 0.6 m deep runs along the whole sill at 1.0 m with short indicator rows.
- **Glass.** Nearly invisible. Reflections only at grazing angles (fresnel), with a faint cool tint. The exterior (starfield, planet limb, escorting hulls) must be visible and dark.

### 2.12 Holo-table and projectors

- **Holo-table** (war room, bridge foyer, engineering):
  - Black octagonal plinth, 2.4 m across flats, 0.9 m high, with a 0.15 m chamfered top edge.
  - Inset projection disc Ø 1.8 m, matte black with a fine radial grid.
  - The projection is **monochrome line art**: thin 1–2 px vector strokes in pale info-blue (#9EC3F0) or pale green-white (#C8F0D8), with no solid fills. Volume about 1.8 m tall. Brightness modest; it must not light the room.
- **Briefing projector:** a black gloss hemisphere Ø 0.6 m on a short collar at the table centre.
- **Wall tactical display:** 6–12 m wide × 2.4–3.0 m tall black screen with a 0.3 m grid in dim green-grey and vector diagrams in pale cyan-white. Text uses digits and simple Latin capitals only.

### 2.13 Consoles

| Console | Size (W × D × H) | Work surface | Screen | Controls |
|---|---|---|---|---|
| Seated duty console (pit) | 1.2 × 0.9 × 1.25 m | 0.72 m high, sloped 15° toward the user | Upper cowl at 0.95–1.25 m, screen tilted 15° back from vertical, 0.45 × 0.3 m | Button banks: square lamp-buttons 24 × 24 mm at 30 mm pitch in blocks of 3×4 or 4×6 |
| Back-to-back wedge console | 2.4 × 1.4 × 1.1 m | Two sloped faces at 25° | Two screens per face, blue-lit | Toggle rows of 12 |
| Standing console | 1.2 × 0.6 × 1.05 m | Top sloped 30° | Inset 0.3 × 0.2 m | 1 keypad, 2 toggle rows |
| Wall console bay | 2.4 × 0.5 × 2.2 m | Shelf at 0.9 m | 2–3 small screens at 1.4–1.7 m, round dial Ø 0.2 m | Indicator grid 8 × 6 |
| Full-height cabinet | 0.6 × 0.6 × 2.2 m (1.7 m in pits) | — | — | Grid of 40 × 40 mm lamp tiles, 1/3 lit |

**Lamp-tile colour mix** (per console face): 70% white (6500 K), 20% red, 7% amber, 3% blue or green.

- Lit tiles are flat, evenly lit squares with a dark bezel of 4 mm. No bloom halo bigger than one tile.
- Screens show simple graphics: horizontal bar meters, wireframe silhouettes, numeric columns, sine traces. They are monochrome per screen (blue-white or amber or green-white), low resolution, with visible scan structure at close range.

### 2.14 Greebles, conduits and vents

- **Where.** Ceilings, pit walls, hangar walls, reactor. Never on floors, never on the walkway, rarely on corridor walls (one wall console bay per 9.6 m at most).
- **Greeble vocabulary:**
  - Long rectangular plates in 3 depths (0.02, 0.05, 0.12 m).
  - Ribbed conduit bundles (Ø 0.05–0.15 m, 3–7 pipes).
  - Cylindrical ducts (Ø 0.9–1.2 m) with flange rings every 2.4 m.
  - Slot lamps (20 × 80 mm), louvre vents (0.6 × 0.3 m with 8 slats).
  - Junction boxes 0.3 × 0.3 × 0.15 m.
- **Logic.** Every greeble cluster follows a line: a beam, a duct, a seam. No scatter. Conduits run parallel to the main axis and turn at 90° or 45° with a visible elbow.

### 2.15 Signage and floor markings

- **Typography.** A plain geometric or technical sans in Latin capitals and digits only (DIN-like or condensed grotesque). No invented alien script. No pseudo-glyph scribbles.
  - Letter height 0.1 m on walls and 0.6 m on hangar floors.
  - Colour: off-white #D8DCDE at 70% opacity on walls; hangar markings #C9CCC8 matte paint.
- **Code format:** `DECK 07 · SEC 31` or `H-2 / BAY 04`. Short. Sparse: one wall code per portal, one door code per door.
- **Corridor floor markings:** a pair of 0.1 m off-white lines 0.6 m in from each wall at junctions only, plus a 0.6 m chevron pointing to the nearest lift.
- **Hangar floor markings** (the most important top-down graphic in the ship):
  - Large flat geometric shapes: chevrons 6 × 3 m, trapezoids, arrow bars, 0.3 m wide guide lines, 0.6 m dashed taxi lines with 2.4 m pitch.
  - Landing pad outlines: an octagon 24 m across flats with a 0.6 m border.
  - Colour: pale grey-white on black gloss. Hazard-yellow #D9B23A only at blast-door thresholds and lift edges.
  - All markings are crisp, flat paint with a roughness of 0.7 (they read matte against the gloss), worn on tyre and foot paths.
- **Bridge and briefing floor marks:** none, except the flush lamp pairs on walkway edges.

### 2.16 Hangar features

- **Deck:** 2.4 m plates; lashing rings on a 4.8 m grid; round floor lights Ø 0.06 m on a 2.4 m grid around pads.
- **Lift pits:** octagonal or square floor openings, 9.6 × 9.6 m, with a lit edge band 0.15 m wide and visible lit shaft walls below.
- **Aperture:** see the door table. The field plane reads as black space framed by the glowing band.
- **Walls:** raked buttresses with dash-lamp columns. Between them, recessed bays 3.6 m wide holding fuel and power service points:
  - Floor-standing pedestal 0.6 × 0.6 × 1.2 m.
  - Reeled hose Ø 0.08 m.
  - Hazard band on the plinth.
- **Gantry cranes:** box-girder beam 1.2 × 1.8 m spanning the bay on wall rails at 18 m, with a trolley and a 4-cable hook. Graphite with yellow warning band on the hook block only.
- **Control gallery:** glazed control room 6–12 m above the deck on one side wall; slanted windows (inward-leaning 15°) with warm-white interior glow 4000 K, the only warm light in a hangar.
- **Ships and cargo:**
  - Ships sit on pads in a strict grid; nose to the aperture.
  - Containers in orderly rows 1.2 m apart, never randomly scattered.
  - Fuel lines run in floor trenches with grating covers 0.6 m wide.
- **Ordnance and parts racks:** wall-mounted overhead racks for small craft (rail at 14 m with 6 m spacing). Use a generic original craft silhouette; do not reproduce any reference fighter.

### 2.17 Reactor shaft features

- A **bottomless vertical shaft**, Ø 40 m, falling 300 m or more into blue-black haze.
- A **core column** Ø 8 m on the shaft axis.
  - Segmented into 4.8 m tall drums with 0.3 m recessed bands.
  - At reactor level: an energy aperture, a horizontal ring gap 1.2 m tall, emitting cold white-blue (9000 K).
- **Catwalks** radiate from the wall gallery to the core:
  - 1.2 m wide grating, **no railings**, 0.05 m white edge line. [E: the reference ledge about 0.4–0.5 m, catwalks about 1.2–1.5 m]
  - A gallery ring around the shaft wall every 4.8 m of height, 2.4 m deep.
- **Shaft wall:** tall vertical slabs 2.4 m wide, with a horizontal band of small blue pin lamps (Ø 0.04 m, 0.3 m pitch) every 9.6 m, plus conduit bundles running vertically.
- **Power terminal:** octagonal pedestal 2.4 m across, 3.0 m tall, on a platform at a catwalk end. Recessed control face. A vertical beam of light above it.
- **Atmosphere:** the deepest haze in the ship. Visibility falls to 15% at 60 m depth.

---

## 3. Materials (Blender Principled BSDF recipes)

sRGB hex is the base colour as authored. Linear is the value to type into Principled when not using a texture.
Roughness and metallic values are the centre of the range. Always add a roughness variation map
(±0.05 noise at 0.6 m scale plus wear masks) unless noted.

| Surface | Base colour sRGB | Linear | Metallic | Roughness | Clearcoat | Normal detail | Wear / dirt |
|---|---|---|---|---|---|---|---|
| **Black mirror floor** | #0B0C0E | 0.003, 0.004, 0.004 | 0.0 | 0.08 (wear lanes 0.15, edges 0.05) | 1.0, coat roughness 0.03 | Micro-scratch 0.02 strength, 0.1 m scale, aligned to walking direction | Faint scuff lanes along walkways; no dust |
| Pale satin grey deck plate | #9A9FA3 | 0.323, 0.347, 0.366 | 0.0 | 0.45 | 0 | Orange-peel paint 0.03 | Darker traffic lanes (−8% value), grime in seams |
| Light-grey wall paint (working decks) | #8C9196 | 0.262, 0.283, 0.305 | 0.0 | 0.55 | 0 | Panel bevels 3 mm, seams 6 mm | Edge chipping on frame corners only (≤ 2% area) |
| Mid-grey wall (secondary) | #5E6368 | 0.112, 0.125, 0.138 | 0.0 | 0.5 | 0 | As above | As above |
| **Graphite structure** (command decks, consoles) | #2A2D31 | 0.023, 0.026, 0.031 | 0.0 (painted) | 0.42 | 0.3, coat roughness 0.2 | Bevels 3 mm everywhere | Almost none; sterile |
| Dark gunmetal (exposed structure, ducts) | #3B3F47 | 0.044, 0.050, 0.063 | 0.85 | 0.35 | 0 | Brushed anisotropy 0.5 along the long axis | Light grime in recesses |
| Cool white panel (ceilings, clinical) | #D9DDE0 | 0.694, 0.723, 0.745 | 0.0 | 0.35 | 0 | None | None |
| White room shell (faceted tile) | #E8EAEA | 0.807, 0.823, 0.823 | 0.0 | 0.3 | 0.2 | Triangular facets 0.3 m, 15 mm relief | None |
| Diffuser panel (emissive) | #F2F4F5 | — | 0 | 0.3 | 0 | None | None; emission 6500 K, strength 8–15 (Cycles W/m², tune per scene) |
| Brushed steel trim (copings, inlays, buckles) | #A9ADB2 | 0.397, 0.418, 0.445 | 1.0 | 0.28 | 0 | Anisotropic 0.6 | Fingerprint smudge near hand contact |
| Chrome (chair bases, rails) | #D6D9DC | 0.672, 0.694, 0.716 | 1.0 | 0.06 | 0 | None | None |
| Rubber (seals, chair seats, cable jackets) | #1A1A1B | 0.010, 0.010, 0.011 | 0 | 0.85 | 0 | Fine grain | Dust 5% |
| Black grating | #16171A | 0.008, 0.009, 0.010 | 0.8 | 0.5 | 0 | Real geometry, not a normal map | Grime 10% |
| Screen glass | #06080B | 0.002, 0.002, 0.003 | 0 | 0.05 | 1.0 | None | None; emission texture under glass at strength 2–4 |
| Viewport glass | #FFFFFF | — | 0 | 0.0 | — | — | Transmission 1.0, IOR 1.5, tint 0.92/0.95/0.98; reflections only at grazing angles |
| Officer uniform wool, olive-grey | #5E6253 | 0.112, 0.122, 0.087 | 0 | 0.8 | 0 | Twill weave 2 mm | Sheen 0.3, sheen tint 0.5 |
| Black uniform | #17181A | 0.009, 0.009, 0.010 | 0 | 0.75 | 0 | Twill | Sheen 0.4 |
| Technician jumpsuit, cool light grey | #9AA3AA | 0.323, 0.366, 0.402 | 0 | 0.75 | 0 | Poplin | Sheen 0.25; slight knee and elbow darkening |
| Staff / intelligence tunic, off-white | #E4E1D8 | 0.776, 0.753, 0.687 | 0 | 0.7 | 0 | Gabardine | Sheen 0.3 |
| **White armour plastic** | #E6E6E2 | 0.791, 0.791, 0.761 | 0 | 0.28 | 0.4, coat roughness 0.15 | Subtle panel undulation 0.01 | Scuffs 3% on knees and shins; slight warm yellowing toward the edges |
| Black helmet gloss | #0E0F11 | 0.004, 0.005, 0.006 | 0 | 0.1 | 1.0 | None | Fine swirl marks |
| Leather boots and belts | #121212 | 0.006, 0.006, 0.006 | 0 | 0.32 | 0.5, coat roughness 0.2 | Leather grain 0.5 mm, creases at the ankle | Polish highlights; dust on soles only |
| Hangar marking paint | #C9CCC8 | 0.584, 0.604, 0.578 | 0 | 0.7 | — | Paint edge 1 mm | Tyre and boot wear, 10–25% erosion along paths |
| Hazard yellow | #D9B23A | 0.694, 0.445, 0.042 | 0 | 0.6 | — | — | Chipped, 15% |

Material rules:

- **Bevel everything.** Use the Bevel shader at 3 mm radius on hard-surface materials, or real 3 mm geometry bevels on hero assets. An unbevelled box edge is a defect.
- **Gloss hierarchy.** Floors and helmets are the glossiest surfaces; walls are satin; cloth is matte. Never make walls glossier than floors.
- **Dirt is near zero on command decks.** Working decks get grime only in seams and on traffic lanes. Hangars and reactor get the most (still subtle).
- **No plastic-toy look.** Paint gets orange-peel normal detail, metal gets anisotropy, cloth gets sheen and weave. No surface is a flat colour with uniform roughness.

---

## 4. Lighting recipes

### 4.1 Global principles

- **Practical-only lighting.** Every light in a frame must come from a visible or implied architectural source: a panel, strip, console, screen, the aperture or the reactor.
  - Fill light is allowed only as a large, dim, cool area light standing in for bounce. It is at most 10% of key intensity and must not cast its own visible shadow.
- **Colour temperature ladder:**

  | Source | Temperature |
  |---|---|
  | Clinical rooms and the reactor | 6500–9000 K |
  | Ceilings and wall lights | 5600–6500 K |
  | Console whites | 6500 K |
  | Officer mess sconces | 3200 K |
  | Hangar control gallery | 4000 K |

  - Only the last two are warm, and both are contained.
- **Contrast.** Command decks are very low key: about 70% of frame pixels below sRGB 40, and a key-to-shadow ratio of 16 : 1 or more. Working decks: key-to-fill about 6 : 1. Clinical rooms: high key, 2 : 1.
- **Haze.** Use a volume scatter of density 0.002–0.006 in large spaces (hangar, reactor, bridge) and 0 in small rooms and corridors (or 0.001 for depth). Haze must show light beams only from strong sources: the aperture, the reactor ring, ceiling troughs.
- **Glossy-floor reflections are the main mood device.**
  - Every emitter must have its reflection visible in a gloss floor, elongated by viewing angle.
  - Reflections are slightly blurred (roughness 0.08 gives soft edges) and darker than the source (about 40% of source luminance).
  - **Check every bridge, hangar and briefing render for a readable reflection of the light rhythm.**
- **Cold, sterile, militaristic, immense** comes from:
  - Cool white light.
  - Near-black surroundings.
  - Repetition of identical fixtures.
  - Hard horizontal edges.
  - Deep falloff into darkness beyond the work zones.
  - People and machines lit from below and from the side by consoles rather than by a friendly top light.
  - No warm fill.

### 4.2 Per-room lighting table

| Room | Key | Kelvin | Fill | Accent | Haze | Notes |
|---|---|---|---|---|---|---|
| Command bridge | Consoles (pit walls, duty consoles) and floor-edge marker lamps; starfield through viewports | 6500 | Dim cool area light from the viewport side, 5% | Red angled light slabs at pit corners (0.15 × 0.9 m, #E3242B), red pin lamps in the ceiling 1 per 6 | 0.002 | Walkway reads as a black mirror with doubled console lights. Faces are underlit by consoles. |
| Spine corridor (A) | Ceiling troughs | 5600 | Bounce from the pale floor, 15% | Red/white strip pairs in reveals; door slot lamps | 0 | Floor gratings read as dark rectangles in a pale floor. |
| Hex tube (B) | Rib rim lights (cool white) | 6500 | None | Floor uplight through grating 3000 K amber-orange, the warm floor glow | 0.001 | Strong vanishing-point rhythm. |
| Panel corridor (C) | Wall-light units | 6500 | None | Diagonal blast-door hazard plate | 0.001 | Light columns doubled in the floor. |
| Briefing room (dark variant) | Under-cornice strips washing down the wall bays; inset table plates | 5600 | None | Projector dome specular | 0 | The table is the darkest, glossiest object; seats glow. |
| Staff room (white variant) | Ring luminaire, Ø 5 m | 6500 | Strong bounce off white walls, 50% | Black ring table as the contrast object | 0 | High key; the only black object is the table. |
| Mess hall | Cool ceiling panels at 30%, plus warm vertical sconces (0.08 × 0.9 m) on wall ribs | 6500 / 3200 | Bounce from light-grey tables | Serving-line counter strip | 0.003 (steam) | The one room with warmth. |
| Crew quarters | Bunk reading lamps (warm 4000 K, small) and a cool corridor light strip | 5600 / 4000 | Low | Locker number plates | 0 | Calm, low. |
| Armoury / quartermaster | Linear overhead strips on a 2.4 m grid (diagonal pairs over racks) | 6500 | Medium | Red cage-lock lamps | 0 | Rack contents read in silhouette against lit back panels. |
| Records / rank hall | Light slots in rack ends (tiny white pips), plus a high clerestory band | 6500 | Very low | Each rank board backlit | 0.004 | Canyon depth, receding pip lines. |
| Simulator / training | White ceiling bars and floor perimeter strip | 6500 | High bounce | Pod interiors blue-white; target-lane red markers | 0 | Clinical variant. |
| Reactor core | Energy ring at the core aperture | 9000 | Blue haze bounce | Blue pin lamp bands; green-white terminal light (#C8F0D8) at the terminal only | 0.006 | Light shafts in haze; the bottom fades to black. |
| Engineering control | Console banks and wall display | 6500 | Low | Amber warning tiles (more amber than elsewhere, 15%) | 0.001 | Faces lit from the console front. |
| Main hangar | Aperture frame band (huge soft source), buttress dash lamps, floor pin lights | 6500 | Large cool overhead area light, 20% (stands in for the high ceiling grid) | Control gallery warm windows 4000 K; hazard markings | 0.004 | The floor markings must read; marking paint is the brightest diffuse surface. |
| Turbolift lobby | Wall-light units, plus a lit ring around each lift door | 6500 | Low | Floor medallion line | 0 | Symmetric, ceremonial. |

---

## 5. Colour palette

### 5.1 Global palette (share of a typical frame)

| Role | Hex | Share |
|---|---|---|
| Void / mirror black | #0B0C0E | 30–60% on command decks |
| Graphite | #2A2D31 | 15–30% |
| Gunmetal | #3B3F47 | 5–15% |
| Mid grey | #5E6368 | 5–15% |
| Light grey | #8C9196, #9A9FA3 | 5–30% on working decks |
| Cool white (light) | #D9DDE0, #F2F4F5 | 3–8% |
| Signal red (lamps only) | #E3242B | ≤ 1.5% |
| Amber (lamps, screens) | #F2A33A | ≤ 0.8% |
| Info blue (screens) | #4D86D9 | ≤ 0.8% |
| Status green (rare) | #4FB86A | ≤ 0.3% |
| Brand gold (project rule: only on flag-tier rank pips, the commander's station rim and the commander's floor mark) | #C8A24A | ≤ 0.5% |

### 5.2 Per-room palettes

| Room | Dominant | Secondary | Accent | Character |
|---|---|---|---|---|
| Command bridge | #0B0C0E floor, #2A2D31 structure | #3B3F47 ceiling, #A9ADB2 coping | #E3242B slabs, #F4F7FF lamp tiles, #4D86D9 screens | Black, red, white |
| Spine corridor | #8C9196 walls, #9A9FA3 floor | #16171A gratings, #3B3F47 ducts | #E3242B / #F4F7FF strip pairs | Pale grey and cool |
| Hex tube | #0B0C0E shell | #2A2D31 ribs | #E89A4A floor uplight | Black with a warm floor |
| Panel corridor / lift lobby | #3B3F47 walls | #0B0C0E floor | #F2F4F5 light columns | Blue-grey night |
| Briefing (dark) | #2A2D31 walls, #0B0C0E table | #1A1A1B chairs | #F2F4F5 seat plates | Black velvet |
| Staff room (white) | #E8EAEA walls | #0B0C0E table | #A9ADB2 chrome | White with a black ring |
| Mess hall | #4A4F4A walls (green-grey) | #C9CCC8 tables | #F0B060 sconces | Muted, warmish |
| Crew quarters | #5E6368 walls | #2A2D31 bunks | #E4E1D8 bedding | Plain |
| Armoury | #2A2D31 | #9A9FA3 floor | #E3242B locks, #D9B23A hazard | Hard |
| Records hall | #1E2126 racks | #0B0C0E floor | #F4F7FF pips | Canyon |
| Simulator | #E8EAEA | #D9DDE0 | #4D86D9 pods | Clinical |
| Reactor | #1E2A3A (blue-black haze) | #3B3F47 | #BFD8FF core, #C8F0D8 terminal | Blue-cold |
| Engineering | #2A2D31 | #5E6368 | #F2A33A amber tiles | Graphite and amber |
| Main hangar | #0B0C0E or #4A4D52 deck | #3B3F47 walls | #C9CCC8 markings, #F2F4F5 aperture | Monumental |
| A warm control room (one per deck at most) | #2A2D31 | — | **#B5452B red-orange painted wall panel** with square buttons | A single warm surprise |

### 5.3 Never colours

- Neon cyan (#00FFFF and anything with saturation > 0.8 at hue 170–200°) as light or trim.
- Magenta, purple, violet.
- Saturated green as room light. Pale green-white is allowed only on reactor terminals and vector displays.
- Rainbow or multi-hue gradients.
- Warm orange or yellow ambient light outside the mess hall, the hex-tube floor glow and the hangar control gallery.
- Brown or wood tones, beige walls (beige upholstery only in quarters booths), pure saturated primaries on walls.
- Coloured fog.
- Gold on anything except the brand-gold rule in 5.1.

---

## 6. Composition rules for the top-down 60° cut-away

The camera looks down at about 60° from horizontal onto a deck plate whose walls are cut at
2.6–3.0 m. This hides most ceilings, so **the floor plan and its light must carry the image**.

1. **The floor is the canvas.** Black mirror floors with crisp seam grids, lit edges and painted markings read better from above than any wall detail. Spend detail budget on floors, rims and furniture tops.
2. **Lit rims define shapes.** Give every important object a light-coloured or self-lit top edge: pit copings, pod rims, table edges, console tops, door thresholds. The octagonal pods with luminous rim caps are the model: from above you see bright outlines on dark masses.
3. **Light-panel rhythm must survive the cut.** Because ceilings are cut away, bring the rhythm down:
   - Wall-light units below 2.6 m.
   - Floor-edge lamp pairs.
   - Floor grating strips.
   - The reflections of the (cut) ceiling troughs.
   - Bake the reflections of the original ceiling into the plate before cutting it (render with the ceiling present, holdout-masked).
4. **Pits are dark rectangles with bright borders.** Crew pits, lift pits and the reactor shaft are the strongest top-down shapes. Keep their interiors darker than the surrounding deck and their copings brighter.
5. **One axis per room, mirrored.** Align the main axis of each room with the deck's grid. Asymmetry only for function.
6. **Section cut treatment.**
   - Cut walls show a solid graphite cap (#2A2D31) with a 0.05 m pale edge line (#8C9196) on the cut face.
   - No glowing cut edges.
   - Cut height 2.6 m in corridors and rooms; 3.0 m on the bridge so the viewport sills remain visible.
7. **Value structure from above.**
   - Command deck: 60% dark, 30% mid, 10% light.
   - Working deck: 30 / 50 / 20.
   - Clinical rooms invert it: 10 / 30 / 60.
8. **Scale cues in every plate.** At least one door (2.5 m), one console (1.25 m) and one person-size object per room so the eye can measure. Repeat elements (consoles, bunks, containers) in counts of 6, 8, 12 or 24, never random counts.
9. **Paths are readable.** Walk lanes are the clearest floor zones: no props, a visible lane edge, worn sheen on gloss floors. Props sit against walls or on the grid.
10. **Depth below the deck.** Where possible, show something below: a lit lift pit, a pit floor, the reactor void. Vertical depth from above is the cheapest way to sell immensity.

---

## 7. Characters and dress

All designs below are **original variants** that evoke the reference silhouettes without copying
its insignia, plaque layout, helmet faces or armour sculpt.

### 7.1 Officers

- **Tunic.**
  - Fitted, hip-length (hem at 0.25 m below the waist).
  - Stand collar 40 mm.
  - **Asymmetric front closure**: a straight vertical flap edge 70 mm to the wearer's right of the centre line, with hidden fasteners.
  - Two welt chest slits (no flaps), set-in sleeves, no epaulettes, no visible buttons.
- **Trousers.** Riding-cut: flared at the thigh by 0.06 m per side, narrow at the knee, tucked into boots.
- **Boots.** Knee-high black riding boots, shaft top at 0.48 m, a 25 mm heel, polished (see materials).
- **Belt.** 45 mm black leather. Buckle plate **64 × 44 mm brushed steel with two horizontal grooves** (original). A small black holster on the right hip for security officers only.
- **Cap.**
  - **Flat-crown service cap**: crown 85 mm tall, slightly larger than the band, with a 35 mm rigid visor raked 20° down, in the tunic colour.
  - Front badge: an 18 mm steel elongated-hexagon disc with one horizontal bar (original).
  - Worn by officers and pit crew.
- **Uniform by rank tier.** This follows the four tiers of the Verse level system (`docs/agent-society/level-system.md`, section 4) and must stay in step with it.

  | Tier (ranks) | Uniform | Trousers and boots |
  |---|---|---|
  | `deck`, enlisted ratings (Recruit to Senior Technician) | Charcoal work jumpsuit #3B3F47, black 40 mm belt, service cap | Ankle boots |
  | `line`, officers (Ensign to Captain) | Olive-grey tunic #5E6253 with cap | Olive-grey riding trousers, knee boots |
  | `command` (Line Captain, Commodore) | Black tunic #17181A with cap | Black riding trousers, knee boots |
  | `flag` (Rear Admiral to Fleet Admiral) | Off-white tunic #E4E1D8 with cap | Black riding trousers, knee boots |

  Gloves: black leather for security posts only.
- **Rank tier dress cues.**
  - Deck ratings and junior line officers wear the cap at all times.
  - Command and flag officers may go bareheaded on the bridge.
  - Flag officers are the only figures in white. Keep them rare (1–2 per scene) so white reads as authority.

### 7.2 Rank plate (original rendering of the level-system plate)

**What the reference does, and must not be copied.** It uses a chest plaque of square, internally lit
tiles in mixed red and blue rows.

**What the level system specifies, and stays.** A steel chest plate with **six slots in two rows of
three**, one lit pattern per rank (`plateTiles(rankId)`), and one tile colour per tier: steel (deck),
blue (line), red (command), gold (flag). The art keeps that data model exactly and renders it in an
original way:

- **Plate.** Brushed steel #A9ADB2, 54 × 22 × 3 mm, with **45° chamfered ends** (an elongated-hexagon outline, not a rectangle). Pinned on the left chest at the height of the second rib. Two 3 mm steel pin heads, one at each end.
- **Slots.** Six **elongated-hexagon sockets**, 12 × 7 mm, recessed 1 mm, in two rows of three. Pitch 15 mm horizontally and 9 mm vertically. Unlit slots are empty dark sockets (#2A2D31).
- **Lit pips.** A lit slot holds a raised enamel pip in the tier colour:

  | Tier | Pip colour |
  |---|---|
  | Steel | #A9ADB2 |
  | Blue | #4D86D9 |
  | Red | #E3242B |
  | Gold | #C8A24A |

  - **One colour per plate, never mixed.** The reference mixes two colours on one plaque; ours never does.
  - Pips are enamel with a satin finish (roughness 0.35). They are **not emissive**: no glow, no backlight.
- **Readability.** In the overview a character is 60–90 px tall and the plate is one or two pixels; the **uniform colour** carries the tier. At the close follow camera (§7.7) the plate is about 12 px wide and its lit pips read.
- **Access tabs** (replacing the reference's chest cylinders): up to two **flat steel key-tabs**, 45 × 12 × 3 mm, clipped vertically into a slot pocket on the upper left sleeve, not on the chest. Close range only.
- **Collar pin.** One 12 mm steel hexagon on the right collar point for officers on duty.
- **Ribbons** (level-system rewards): a single row of 30 × 8 mm ribbon bars directly above the plate, with at most 4. Each is a flat two-tone stripe from the palette, without metallic thread.

### 7.3 Crew, technicians and gunners

- **Deck ratings, pit crew and technicians.**
  - One-piece charcoal work jumpsuit #3B3F47 (the `deck` tier uniform) with a black 40 mm belt and steel plate buckle.
  - Black service cap; black ankle boots.
  - A small square branch patch, 50 × 50 mm, on the left upper arm, showing the hex-bar mark (7.6).
  - Headset with a single boom mic for console operators.
  - In crowd scenes a deck-tier extra may wear a cool light-grey duty overall #9AA3AA instead. This breaks up large crews and still reads as "not an officer".
- **Gunners and reactor crew.**
  - Black jumpsuit with a black utility harness.
  - **Original helmet**: a black gloss **rounded dome with a flat 40 mm brim all round, sloped 15° down**, and a smoked full-face visor ending at the chin.
  - The dome has two parallel raised ridges front to back, 30 mm apart, and one small white rectangular unit mark 30 × 12 mm on the left side.
  - Total helmet height 0.30 m, brim width 0.36 m.
- **Deck security (navy guards).**
  - Black uniform.
  - Black gloss **open-face helmet** with cheek guards, a raised brow ridge and a short neck flare 40 mm.
  - Chin strap; a sidearm on the hip.
  - They stand in pairs at pit entrances and lift lobbies.

### 7.4 Armoured marines (original variation of the white-armour look)

- **Overall.** Off-white hard armour #E6E6E2 over a graphite under-suit #2A2D31. Total height 1.85 m. Plates have bevelled 4 mm edges and a satin finish with clear coat.
- **Helmet** (original):
  - Smooth **ovoid shell** 0.30 m tall.
  - A **horizontal smoked visor band** 35 mm tall wrapping 180°, at eye level.
  - A vertical chin ridge with two small horizontal grille slots.
  - A graphite neck seal.
  - **No** eye lenses, no mouth frown, no cheek tubes, no brow ridge.
- **Torso:** chest plate with three horizontal raised ribs (6 mm), separate abdomen plate, back plate with a flat pack 0.3 × 0.2 × 0.08 m.
- **Shoulders:** a rounded shoulder bell on each side, 0.15 m, rim slightly flared.
- **Limbs:** forearm, thigh and shin shells. Graphite gaps at the joints: elbow, knee 40 mm.
- **Belt:** graphite utility belt with six small bevelled pouches 50–60 × 46 × 28 mm and an off-white buckle plate.
- **Unit mark:** a 30 mm coloured band around the left upper arm. Gold for the commander's guard, red for shipboard security, blue for the engineering detail.
- **Weapon:** an original compact rifle, 0.65 m long, graphite. Keep the silhouette simple, with no recognisable reference weapon.

### 7.5 Service robots aboard

| Robot | Size | Look | Behaviour |
|---|---|---|---|
| Floor courier | 0.48 L × 0.30 W × 0.24 H m [reference small box robot is 0.25 m tall S] | Black satin box with 45° chamfered top edges, hidden wheels, one amber status pip at the front | Darts along wall edges at 1.2 m/s, stops, turns 90°, continues |
| Hover sentinel | Ø 0.40 m sphere | Black gloss, six radial seams, one red lens Ø 40 mm, two folding manipulator arms | Hovers at 1.6 m, slow patrol in security zones |
| Humanoid liaison | 1.72 m tall [reference 1.7 m S fan] | Matte gunmetal #3B3F47, slim, horizontal-rib abdomen, capsule head with two round amber sensors Ø 30 mm, no face grille | Walks with officers, stands at consoles |
| Maintenance crawler | 0.7 × 0.5 × 0.6 m | Tracked graphite crate, one folding 1.1 m arm, hazard-yellow band 50 mm | Works at wall bays, hangar service points |
| Cargo sled | 2.4 × 1.2 m deck, 0.3 m float height | Flat graphite pallet with rear operator post 1.1 m and four corner lamps | Moves containers in hangars |
| Deck cleaner | Ø 0.6 × 0.12 m disc | Dark grey, a ring of white pips | Slow spirals on gloss floors (leaves a fresh-gloss trail) |

### 7.6 Original markings

The ship's own mark, for patches, floors and doors, is the **Dodaios hex-bar**:

- An elongated hexagon outline with a horizontal bar through its centre.
- Line weight 1/8 of the height.
- Off-white on dark, or graphite on light.

Never use cog, wheel or spoke shapes as insignia.

### 7.7 Close camera (the commander as a game character)

The follow camera frames a standing figure 200–260 px tall (about 200 px per metre at 60°).
At that size a pixel is 5 mm, so the crew carry painted detail (one texture atlas per model,
`art/verse/characters/README.md`), drawn a little bolder than life:

- **Faces.** Skin with warmer cheeks, nose and ears; eye sockets in soft shadow; eyes with
  sclera, iris and pupil; a dark upper lash line; brows 6–8 mm tall in the hair colour; lips
  a shade redder than the skin with a dark mouth line; a close-shaven jaw on men.
- **Hair.** Real volume (10–16 mm on top, tapered over the ears and at the nape), combed back
  in visible locks; a side parting for men, a centre parting and a bun for women.
- **Tailoring.** Seams 4–7 mm wide (princess, side, set-in sleeve, centre back, outer leg),
  welt chest slits, stitched collar, cuffs, belt edges and skirt hem, folds at elbows, waist
  and over the boots. On the black tiers the detail lives in relief and gloss, not colour.
- **Armour and drones.** Panel lines, vents and inset panels on every plate; the hex-bar
  mark (7.6) on the companion's top and back and on the floor courier's deck.
- **Tintable.** Uniform, trousers, trim, cap and accent stay neutral in the atlas, so the
  rank tier still sets their colour.

---

## 8. Props catalogue

Sizes are W × D × H in metres unless noted.

| # | Prop | Size | Notes |
|---|---|---|---|
| 1 | Seated duty console | 1.2 × 0.9 × 1.25 | Section 2.13 |
| 2 | Back-to-back wedge console | 2.4 × 1.4 × 1.1 | Blue screens |
| 3 | Standing console | 1.2 × 0.6 × 1.05 | 30° top |
| 4 | Wall console bay | 2.4 × 0.5 × 2.2 | Dial plus 3 screens |
| 5 | Full-height lamp cabinet | 0.6 × 0.6 × 2.2 | 1/3 tiles lit |
| 6 | Pit cabinet | 0.6 × 0.6 × 1.7 | Under the coping |
| 7 | Operator chair, high-back swivel | 0.6 × 0.6 × 1.15 | Black, 5-star chrome base |
| 8 | Briefing shell chair | 0.5 × 0.55 × 1.1 | Thin black shell, 4-star chrome base |
| 9 | Staff chair, white | 0.55 × 0.6 × 1.2 | White leather, black frame |
| 10 | Ring briefing table | Outer Ø 6.0, inner Ø 3.0, H 0.74 | Black gloss, 0.6 m entry gap |
| 11 | Projector dome | Ø 0.6 × 0.35 | Table centre |
| 12 | Holo-table | 2.4 across flats × 0.9 | Octagonal |
| 13 | Wall tactical display | 6–12 × 0.2 × 2.4–3.0 | Vector graphics |
| 14 | Rank-board panel | 1.2 × 0.1 × 3.6 | Backlit, records hall |
| 15 | Data rack | 0.9 × 1.2 × 4.8 | Pip lamps on the end face |
| 16 | Pedestal mess table | 1.8 × 0.8 × 0.74 | Light grey top, graphite pedestal |
| 17 | Bucket shell stool or chair | 0.5 × 0.5 × 0.8 | Grey plastic |
| 18 | Serving counter module | 2.4 × 0.9 × 1.0 | Steel top, sneeze glass |
| 19 | Food tray | 0.45 × 0.32 × 0.03 | Steel, 4 compartments |
| 20 | Drink cup | Ø 0.08 × 0.11 | Matte grey |
| 21 | Triple bunk module | 2.1 × 0.9 × 2.6 | 3 berths, reading lamp each |
| 22 | Crew locker | 0.6 × 0.6 × 2.1 | Number plate |
| 23 | Officer cabin desk | 1.4 × 0.7 × 0.74 | Wall-hung |
| 24 | Officer bunk | 2.1 × 1.0 × 0.5 | Integrated drawer |
| 25 | Armour stand | 0.6 × 0.6 × 1.9 | Holds a full white armour set |
| 26 | Rifle rack | 2.4 × 0.4 × 1.8 | 12 rifles, locking bar |
| 27 | Issue cage counter | 4.8 × 0.9 × 1.1 | Mesh above to 2.4 m |
| 28 | Helmet shelf | 2.4 × 0.4 × 0.4 | 6 helmets |
| 29 | Ammunition and power-cell crate | 0.6 × 0.4 × 0.3 | Graphite, yellow stencil band |
| 30 | Supply crate | 1.2 × 0.8 × 0.8 | Stackable |
| 31 | Cargo container | 6.0 × 2.4 × 2.6 | Ribbed, end doors, code stencil |
| 32 | Half container | 3.0 × 2.4 × 2.6 | — |
| 33 | Fuel service pedestal | 0.6 × 0.6 × 1.2 | Reel hose Ø 0.08 |
| 34 | Power coupler cart | 1.2 × 0.8 × 1.0 | Cable spool |
| 35 | Gantry crane beam | Span 48–72 × 1.2 × 1.8 | Trolley 2.4 × 2.4 |
| 36 | Crane hook block | 0.8 × 0.6 × 1.2 | Hazard band |
| 37 | Boarding ramp stair | 2.4 × 6.0 × 2.4 | Folding |
| 38 | Small-craft overhead rack | Rail 0.6 × 0.6, cradle 3 × 3 | Wall-mounted |
| 39 | Landing pad light | Ø 0.06 × 0.01 | Flush |
| 40 | Lashing ring | Ø 0.15 | Flush |
| 41 | Floor grating panel | 0.9 × 2.4 × 0.04 | Real bars |
| 42 | Vent grille | 0.6 × 0.3 | 8 slats |
| 43 | Wall-light unit | 0.6 × 0.05 × 2.3 | 4 pattern variants |
| 44 | Ceiling light trough panel | 0.6 × 1.2 | Diffuser |
| 45 | Ring luminaire | Ø 5.0 × 0.9 | Fins 0.05 × 0.6 |
| 46 | Cylindrical duct segment | Ø 1.2 × 2.4 | Flange rings |
| 47 | Conduit bundle | 5 pipes Ø 0.08, 2.4 long | Clips every 0.6 m |
| 48 | Junction box | 0.3 × 0.15 × 0.3 | Red pip |
| 49 | Cylindrical pilaster | Ø 0.6 × 3.0 | Three grooves |
| 50 | Personnel door | 1.8 × 2.5 opening | Section 2.7 |
| 51 | Diagonal blast door | 3.0 × 3.0 opening | Section 2.7 |
| 52 | Lift door with ring light | 1.8 × 2.5, ring Ø 3.0 | Lobby |
| 53 | Lift car (cylinder) | Ø 2.4 × 2.6 | Interior wall-light units |
| 54 | Reactor power terminal | 2.4 across flats × 3.0 | Octagonal |
| 55 | Coolant capsule tank | Ø 1.8 × 2.4 | Octagonal shell |
| 56 | Catwalk segment | 1.2 × 4.8 | No rail |
| 57 | Simulator pod | 3.0 × 2.4 × 2.4 | Capsule with open hatch, blue-white interior |
| 58 | Target lane frame | 3.0 × 0.3 × 2.7 | Red markers |
| 59 | Medical bed | 2.1 × 0.9 × 0.9 | White, overhead scanner arm |
| 60 | Detention cell door | 1.2 × 2.2 | Hex hatch, red lock lamp |
| 61 | Detention control desk | 3.6 × 1.2 × 1.0 | Red key panel |
| 62 | Datapad | 0.18 × 0.12 × 0.012 | Graphite, amber screen |
| 63 | Wall code plate | 0.6 × 0.15 | Latin and digits |
| 64 | Hazard threshold plate | Door width × 0.6 | Diagonal black/yellow 0.15 m stripes |
| 65 | Floor lamp pair (walkway marker) | 2 × (0.04 × 0.15) | Every 2.4 m |

---

## 9. Per-room composition sheets

The camera is at 60° in all sheets. "N" is the bow direction or the room's main axis.

### 9.1 Command bridge

- **Footprint.** 30 × 18 m, plus a rear foyer of 10 × 9.6 m. Clear height 4.8 m over the walkway.
- **Layout.**
  - The central **command walkway** (3.6 m wide) runs 24 m from the foyer to the bow.
  - Two **crew pits** flank it. Each is 4.8 m wide (3.6 m clear floor) × 18 m long × 1.7 m deep, with chamfered ends converging toward the bow.
  - Each pit has 6 duty consoles facing the bow, wall cabinets along the outer side, and 9 steps at the aft end.
  - The bow: an arc of 9 trapezoid viewports, sill 1.0 m, with a console shelf.
  - Port and starboard alcoves (3.6 × 3.6 m) hold the weapons and defence stations, each with a standing console and a small window.
  - **Rear foyer:**
    - Holo-table centred on the axis.
    - Communications console arc (5 seats) on one side; a turbolift (Ø 2.4 m) on the other.
    - Access doors to the spine corridor.
    - Two guards at the pit stairs.
- **Materials.** Black mirror walkway and foyer; pale-grey pit floors; graphite structure; brushed copings.
- **Lighting.** Section 4.2.
- **Top-down read.** A black spine with two bright-rimmed dark trenches pointing at a starfield arc.
- **Population.** 12–18 crew, 3–5 officers, 2–4 guards, the commander (the player) on the walkway.
- **Gold.** Only the commander's floor mark (a 0.6 m hex-bar inlay at the walkway's bow end), the commander's station rim and flag-tier rank pips.

### 9.2 Main corridor (spine)

- **Footprint.** Type A section. Runs the deck length, with junctions every 28.8 m.
- **Layout.**
  - Portal frames every 4.8 m.
  - Floor gratings in pairs between portals.
  - One wall console bay per 9.6 m, alternating sides.
  - Doors to rooms centred between portals.
  - At junctions: a lift lobby or a Type B tube branching at 90°.
- **Top-down read.** A pale band with a dark dotted double line (gratings) and regular dark ticks (portals).
- **Population.** Groups of 2–3 crew, couriers along the edges, an occasional patrol pair.

### 9.3 Briefing / conference room

- **Footprint.** Circular, Ø 12 m, height 4.2 m. Entry by one personnel door on the axis.
- **Layout.**
  - Ring table: outer Ø 6.0 m, inner Ø 3.0 m, with a 0.6 m entry gap facing the door.
  - 12 seats, each with an inset lit plate (0.3 × 0.2 m).
  - Projector dome at the centre.
  - 24 wall bays of 1.5 m, each with a tapered trapezoid relief and an under-cornice wash light.
- **Variants.** Dark (graphite and black) or staff-white (white faceted walls, ring luminaire, black table, white chairs).
- **Top-down read.** A black ring on a dark floor, ringed by 12 small glowing rectangles and 24 wall washes.

### 9.4 Mess hall

- **Footprint.** 24 × 14.4 m, height 3.6 m.
- **Layout.**
  - 4 rows × 4 pedestal tables (1.8 × 0.8 m) with 4 shell chairs each, on a 3.6 m × 2.4 m grid.
  - Serving line of 5 counter modules (12 m) along the aft wall; tray rack and cup dispenser at its end.
  - Wall ribs every 2.4 m with warm vertical sconces.
  - Two doors to the spine.
- **Materials.** Pale satin grey floor; green-grey walls #4A4F4A; light-grey tables.
- **Top-down read.** A tidy grid of light rectangles in a mid-dark room, with warm dots along the walls.
- **Population.** 20–40 crew, mostly seated in uniform colours.

### 9.5 Crew quarters / bunk room

- **Footprint.** 12 × 7.2 m, height 3.0 m (enlisted). Officer cabin 4.8 × 3.6 m.
- **Enlisted layout.**
  - 8 triple bunk modules (24 berths) in two rows facing a central 1.8 m aisle.
  - Lockers between modules.
  - A wash-room door at the end.
- **Officer cabin layout.** Bunk along one wall, wall desk, locker, a small window if on the hull.
- **Top-down read.** Long rhythmic rows of identical dark modules with a pale aisle; bedding the only off-white.

### 9.6 Quartermaster / armoury

- **Footprint.** 18 × 12 m, height 3.6 m.
- **Layout.**
  - Issue cage counter (4.8 m) across the entry third.
  - Behind it, 3 aisles of armour stands (8 per row, white armour sets) and rifle racks on the walls.
  - Helmet shelves; crates on a 1.2 m grid.
  - Diagonal paired light strips over the racks, following the 45° grammar.
- **Top-down read.** White armour figures in exact rows inside a dark cage, a bright counter edge, red lock pips.

### 9.7 Records / rank hall

- **Footprint.** 30 × 12 m, height 9.6 m (2 decks).
- **Layout.**
  - A central nave 4.8 m wide.
  - Data racks (0.9 m deep, 4.8 m tall) in 2 × 10 perpendicular rows, forming canyons on both sides.
  - At the far end, a **rank wall**: one backlit rank-board panel (1.2 × 3.6 m) per rank of the level system, 15 boards grouped into 4 tier bays (deck, line, command, flag) with a 1.2 m gap between bays. Each board carries its rank plate pattern enlarged as hexagonal pips in the tier colour. This is where the game's level progression is shown in the world.
  - A gallery with a thin rail at 4.8 m.
- **Top-down read.** A dark comb of racks with pip lines, a lit nave, and a glowing row of boards at the end.

### 9.8 Simulator / training room

- **Footprint.** 20 × 14.4 m, height 4.2 m. Clinical variant.
- **Layout.**
  - 4 simulator pods (3.0 × 2.4 m) on one side, hatches facing the centre.
  - A target lane 3 × 18 m on the other side, with frame gates every 4.8 m.
  - An instructor's standing console on the axis.
  - Floor perimeter light strip 0.05 m.
- **Top-down read.** A bright white plate with blue-glowing pod mouths and a red-marked lane.

### 9.9 Reactor core

- **Footprint.** Shaft Ø 40 m, viewed across 2–3 gallery levels.
- **Layout.**
  - Gallery ring (2.4 m deep) at deck level.
  - 4 catwalks (1.2 m, no rails) radiating to a ring platform around the core column (Ø 8 m), which carries the power terminal at one catwalk end.
  - Coolant capsule tanks on the gallery.
  - The shaft falls away below into haze.
  - The energy ring at the core is visible one level down.
- **Top-down read.** Four thin bright spokes over a black-blue void, a glowing ring around the core: the most graphic plate in the ship.

### 9.10 Engineering control room

- **Footprint.** 24 × 16.8 m, height 4.8 m.
- **Layout.**
  - Three concentric arcs of console banks (8 / 10 / 12 seats) stepping down 0.3 m each toward a wall tactical display (12 × 3 m) showing the reactor schematic.
  - Master console on the axis at the top tier.
  - A holo-table at the back.
  - Wall cabinets with a higher amber share.
- **Top-down read.** Arcs of lit console tops focusing on one bright wall: a theatre of work.

### 9.11 Main hangar

- **Footprint.** 96 × 48 m, height 24 m. Aperture 72 × 18 m on one long side.
- **Layout.**
  - Two landing pads (24 m octagons) on the axis.
  - A shuttle (about 20 m, original folding-wing design) on pad 1, ramp down.
  - Pad 2 empty with a crew formation (armoured marines in 4 × 12 blocks).
  - Cargo containers in orderly rows along the rear wall.
  - Gantry crane across the bay; fuel pedestals in wall bays.
  - Buttresses every 4.8 m with dash-lamp columns.
  - Control gallery 9.6 m above the deck on the short wall.
  - A lift pit (9.6 × 9.6 m) near the rear.
- **Floor markings.**
  - Chevron arrows from the aperture to each pad.
  - Taxi dashes.
  - Hazard thresholds at the blast doors.
- **Top-down read.** A black mirror field printed with huge pale geometry, a white-glowing aperture edge, blocks of white figures.

### 9.12 Turbolift lobby

- **Footprint.** 12 × 9.6 m, height 3.6 m. Type C panel walls.
- **Layout.**
  - 4 lift doors, 2 per long wall, each with a lit ring frame Ø 3.0 m around the door.
  - Wall-light units between them.
  - A floor medallion (Ø 2.4 m) on the axis: the Dodaios hex-bar in a brushed-steel inlay on black gloss.
  - Two guards on high-security decks.
- **Top-down read.** A symmetric black room with four bright rings and a central steel mark.

---

## 10. Anti-slop list (what makes generated sci-fi look generic, and the rule that fixes it)

| # | Slop | Rule |
|---|---|---|
| 1 | Neon cyan or magenta light lines on every edge | Light only from functional sources. Edge lighting is allowed only as dotted lamp lines on command portals and as pit-coping underglow. Cyan is banned (5.3). |
| 2 | Random glowing lines and "tech" patterns on walls | Every lamp belongs to a panel, console or fixture with a function. Wall-light units use 4 fixed patterns of pill lamps. |
| 3 | Uniform flat lighting with no darkness | 60–70% of a command frame is near-black. Light falls off into darkness outside work zones. |
| 4 | Plastic, toy-like materials with uniform roughness | Each material has roughness variation, a normal detail and the correct gloss hierarchy (floors and helmets glossiest). |
| 5 | Unbevelled boxes with razor CG edges | 3 mm bevels on everything hard-surface; stepped profiles on frames. |
| 6 | Clutter without purpose (scattered crates, cables everywhere) | Props on a grid, in counts of 6/8/12/24, against walls or in designated zones. Floors and walkways stay clear. |
| 7 | Greebles sprinkled everywhere | Greebles follow lines (beams, ducts, seams); ceilings busy, walls calm (3 : 1 plain to detailed), floors clean. |
| 8 | Holograms as solid blue glowing blobs | Monochrome thin vector line art, dim, not lighting the room. |
| 9 | Alien-script gibberish signage | Latin capitals and digits only, sparse codes. |
| 10 | Rainbow of accent colours | Red, white and small amber/blue only, under 3% of the frame combined. |
| 11 | Curvy organic "spaceship" interiors with fillets | 45° chamfers, hexagons, trapezoids; curves only as cylinders and round rooms. |
| 12 | Glossy everything (walls like mirrors) | Only floors, helmets, tables and screens are glossy; walls satin; cloth matte. |
| 13 | No sense of scale | Rhythm repeated to the vanishing point; people small; doors and consoles at true size as scale cues. |
| 14 | Bloom halos swallowing the image | Bloom threshold above 1.0 linear and small radius; a lamp tile's glow must not exceed one tile width. |
| 15 | Fog everywhere at the same density | Haze only in big volumes (hangar, reactor, bridge); zero in rooms and corridors. |
| 16 | Railings on every edge, safety yellow everywhere | Danger edges are cold and bare. Yellow only at thresholds and lift edges. |
| 17 | Generic military camo or brown palettes | Uniform colours are olive-grey, black, light grey and off-white only. |

How the reference avoids slop: it was built physically. Lights are real fixtures inside real panels,
and floors are real lacquered boards that reflect them. Furniture is real office and industrial hardware
painted grey, and repetition comes from casting the same panel many times. Imitate that logic: **build
like a set, not like a texture**.

---

## 11. QA checklist for renders

A reviewer can check these on any plate:

1. **Rhythm.** Measure the spacing of portals, lights and ribs in the render: 4.8 m, 2.4 m or 1.2 m as specified. Deviation ≤ 5%.
2. **Darkness share.** In a command-deck plate, ≥ 55% of pixels are below sRGB 40. In a working deck, 20–40%. In a clinical room, ≤ 10%.
3. **Saturation.** Pixels with HSV saturation > 0.6 make up ≤ 3% of the frame.
4. **Banned hues.** No pixel cluster larger than 0.1% of the frame with hue 170–200° (cyan) or 270–330° (purple to magenta) at saturation > 0.7.
5. **Floor reflection.** Gloss-floor plates show the light rhythm reflected and readable.
6. **Bevels.** No visible hard-surface edge without a highlight at 1:1 crop.
7. **Text.** Only Latin capitals and digits; no franchise marks, no invented glyphs.
8. **Scale.** A door, a console and a person each measure true to this document within 5%.
9. **Insignia.** No square-tile rank grid, no cog emblem, no reference helmet face.
10. **Symmetry.** The main room axis is mirrored except for listed functional exceptions.

---

## Appendix: confidence summary

- **Values with a stated source:**
  - Ship length 1,600 m.
  - Wall-light unit about 2.30 × 0.61 m (replica builders).
  - Crew-pit depth about 1.7 m, 6 consoles per pit, viewport panes about 2 m tall from about 1 m above the deck (fan technical analysis of the reference films).
  - Small courier robot 0.25 m tall; humanoid robot 1.7 m.
  - Original-era hangar stage 76 × 37 × 13.7 m.
  - Rank-tile lens 18 mm (so our 10 × 6 mm pips are deliberately different).
- **Values estimated from frames (crew = 1.75 m):** corridor widths and heights, door sizes, pit floor width, briefing-table diameter, hangar plate size, catwalk widths.
- **Everything else is a design decision [D],** made on the 0.6 m grid to read well from a 60° top-down camera.
