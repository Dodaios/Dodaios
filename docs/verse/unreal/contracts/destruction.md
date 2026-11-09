# Contract: destruction and penetration

Owner module: `VerseDestruction` (pieces, state machine, fracture authority,
debris, holes, repair drones, penetration queries, nav updates). Shared types
live in `VerseCore` (architecture §2). Consumers: `VerseCombat` (bolts,
breach charge, melee), `VerseBot` (perception, cover, wall shots), `VerseGore`
(decal cleanup), `VerseUI` (kill cam replay), `VerseHarness` (gates).

Units: Unreal centimetres, Z-up, server time in milliseconds. Everything in
this file builds on README "Destruction" and architecture §4 and §7; where a
number repeats from there it must stay equal.

## 1. Rules that hold everywhere

| # | Rule |
|---|---|
| DR1 | Only the server applies piece damage and decides a state change (`HasAuthority()`). Clients never change a piece state, not even predicted |
| DR2 | Gameplay collision (movement, bolts, sight, nav) comes only from the authored per-state proxy meshes and the replicated hole records. Simulated debris never blocks anything gameplay-relevant |
| DR3 | Debris is client-side cosmetic (Chaos Geometry Collection, GC replication off). A dedicated server and every `-nullrhi` run spawn no debris |
| DR4 | The hall floor, concrete and armor steel never change state |
| DR5 | Breakable pieces are solid, closed volume meshes with real thickness. Never double planes, never open shells (section 9) |
| DR6 | The bot learns of a piece change only by perceiving it (sight, sound, its own action). It never reads piece truth it could not have perceived (section 6) |

## 2. Material penetration table

`DA_PenetrationTable` in `VerseCore`, one row per material. Material ids are
gameplay tags `Verse.Material.<Id>` plus a `uint8` wire id in the order below
(order is frozen; new materials append).

Power scale: a bolt starts with its weapon's `PenetrationPower`. **100 = the
assault rifle**; the combat contract sets every other weapon against that
anchor. Passing a piece costs `cost x clamp(traced_thickness / ref_thickness,
0.5, 3.0)`, where `traced_thickness` is the distance between the entry and exit
hit on the piece's current proxy. The bolt passes if its remaining power is
at least that cost; its remaining damage is then multiplied by the row's
multiplier. A bolt passes at most 3 pieces; the 4th stops it. A weapon may
lower that limit with its `MaxPenetrations` (combat contract, 3); it never
raises it.

| Wire | Material id | Ref thickness cm | Penetration cost | Damage multiplier after passing | Breakable by bullets | Breakable by breach | Debris type |
|---|---|---|---|---|---|---|---|
| 0 | `sheet_metal` | 0.3 | 15 | 0.85 | y | y | `MetalShards` (rigid) + sparks |
| 1 | `container_wall` | 0.4 (corrugated) | 25 | 0.75 | y | y | `CorrugatedChunks` (rigid) + sparks |
| 2 | `glass` | 2.4 (laminated) | 5 | 0.95 | y | y | `GlassShards` (Niagara only, no rigid bodies) |
| 3 | `cladding_panel` | 4.0 (composite) | 30 | 0.70 | y | y | `PanelChunks` (rigid) + insulation dust |
| 4 | `catwalk_grating` | 3.0 (bar grating) | 10 | 0.90 | n | y | `GratingTwisted` (rigid, few large pieces) |
| 5 | `ceiling_panel` | 2.5 (metal tile) | 8 | 0.90 | y | y | `CeilingTile` (rigid, whole tile falls) + dust |
| 6 | `concrete` | 30 | 400 | 0.00 | n | n | `DustChips` (Niagara only) |
| 7 | `armor_steel` | 2.5 | 10000 (impassable) | 0.00 | n | n | Sparks only |

Reading the table at reference thickness: the rifle (100) passes two
container walls (25 + 25) and keeps 0.75 x 0.75 = 0.5625 of its damage; the
pistol (50, two passes) passes one container wall, or glass and sheet metal;
nothing passes concrete or armor steel. Non-destructible world geometry gets
its row through its physical material (the hall floor and structural walls
are `concrete`, structural beams `armor_steel`).
"Breakable by bullets n" means bolts may still pass (grating) or scorch, but
never change the piece state.

Sight and bolts use different channels (section 5): Intact glass and grating
let sight through and stop or charge bolts as the table says.

## 3. Piece classes and damage states

### 3.1 States

`EVersePieceState : uint8`, values and order frozen:

| Value | State | Gameplay proxy | Meaning |
|---|---|---|---|
| 0 | `Intact` | Full solid | As built |
| 1 | `Damaged` | Full solid + bolt holes (section 5) | Scorches, dents, cracks, small holes |
| 2 | `Holed` | Authored hole variant | Openings to see and shoot through, not to walk through |
| 3 | `Breached` | Authored breach variant | Opening a standing pawn walks through (at least 90 cm x 200 cm), or a low breach to mantle through |
| 4 | `Destroyed` | None, plus optional authored `Remains` proxy on the floor | Piece gone (glass shattered, tile or segment fallen) |
| 5 | `Repairing` | The proxy of the state it repairs from | A drone is rebuilding it (section 7) |

Holed and Breached each have up to 4 authored variants per piece. The server
picks the variant whose opening centroid is closest to the damage centroid
(Holed) or the charge position (Breached) and replicates its index.

### 3.2 Classes

Piece HP is per piece, quantised to 8 bits in replication (`HealthQ =
round(255 x hp / maxHp)`). Piece damage per bolt and per breach charge comes
from the combat contract; the anchor is 10 piece damage per rifle bolt.

| Class | Material | Max HP | Intact to Damaged | to Holed | to Breached | to Destroyed | Repair time s |
|---|---|---|---|---|---|---|---|
| Wall panel | `sheet_metal` | 200 | first hit | HP at or below 100 (bullets) | breach charge | never | 8 |
| Cladding wall | `cladding_panel` | 250 | first hit | HP at or below 125 (bullets) | breach charge | never | 8 |
| Container wall | `container_wall` | 300 | first hit | HP at or below 150 (bullets) | breach charge | never | 8 |
| Glass pane | `glass` | 20 | first hit (crack web) | never | never | HP 0, breach charge, melee on Damaged glass | 4 |
| Catwalk segment | `catwalk_grating` | n/a | never | never | never | breach charge only | 10 |
| Ceiling panel | `ceiling_panel` | 60 | first hit | never | never | HP 0 (bullets), breach charge | 5 |

Breach charge radius effect (server, one detonation): the target piece goes
to its breach result; other breakable pieces with any proxy vertex within
150 cm go to Holed (walls) or Destroyed (glass, ceiling). Bullets never take
a wall past Holed. Melee changes only glass. Transitions only move forward
(towards Destroyed); only Repairing and Reset move back.

### 3.3 Replicated state

One `FFastArraySerializer` on `AVerseDestructionManager` (one per arena world
partition cell set, always relevant), push model, items change only on a
state change, an HP change of at least 1 quantum, or a hole.

| Field | Type | Notes |
|---|---|---|
| `PieceIndex` | `uint16` | Index into `DA_PieceManifest` (section 8), same on server and clients |
| `State` | `EVersePieceState` | |
| `HealthQ` | `uint8` | 0..255 |
| `Variant` | `uint8` | Holed or Breached variant, else 0 |
| `RepairFrom` | `EVersePieceState` | Valid while `Repairing` |
| `LastSeed` | `uint32` | Seed of the last fracture |
| `LastImpulse` | 3 x `int16` | Last fracture impulse, 1 unit = 0.1 N s |
| `LastLocation` | 3 x `int16` | Piece-local, 1 mm |
| `StateTimeMs` | `uint32` | Server time of the last state change |
| `Epoch` | `uint16` | Destruction epoch (section 11) |

Bolt holes replicate in a second fast array (section 5). Late joiners
receive both arrays and build the broken look directly, without debris and
with holes already cooled.

## 4. Fracture event

`FVerseFractureEvent` in `VerseCore`. Sent as an unreliable multicast for
instant debris and published on the event hub (server and clients) for every
state change, repair and reset. The fast array (section 3.3) is the truth; a
lost event only costs that client its debris burst.

| Field | Type | Notes |
|---|---|---|
| `PieceIndex` | `uint16` | `0xFFFF` = all pieces (reset only) |
| `FromState`, `ToState` | `EVersePieceState` | |
| `Cause` | `uint8` enum | `Bolt, Breach, Melee, Repair, Reset` |
| `Variant` | `uint8` | Chosen proxy variant |
| `Seed` | `uint32` | Server RNG draw; drives the Chaos strain pattern and Niagara seeds |
| `Impulse` | 3 x `int16` | World space, 0.1 N s per unit |
| `Location` | 3 x `int16` | Piece-local, 1 mm; impact or charge point |
| `Radius` | `uint8` | cm; strain field radius |
| `Instigator` | `uint8` | Player slot, `0xFF` = world (repair, reset) |
| `ServerTimeMs` | `uint32` | |
| `Epoch` | `uint16` | Events with an old epoch are dropped |

About 30 bytes on the wire, under the 64-byte budget (architecture §7).
Clients apply the same strain field at the same location with the same seed;
a different crack pattern on another client is allowed (architecture §4).

**Kill cam replay.** `UVerseDebrisSubsystem::ReplayFracture(const
FVerseFractureEvent&)` redraws the debris burst of a recorded fracture
inside the same debris budget, without touching the piece state; repairs
and resets are not replayed. `VerseUI` cannot include `VerseDestruction`, so
the primary module binds `UVerseUiSubsystem::OnKillCamFracture` to it when a
world begins play.

## 5. Bolt holes as sightlines

A bolt that passes a `Damaged`-capable piece (sheet metal, container wall,
cladding, glass, ceiling) leaves a hole at entry and exit. A bolt that stops
in it leaves a dent decal and no hole. Concrete and armor steel get scorch
decals only.

| Topic | Rule |
|---|---|
| Record | `FVerseBoltHole`: `PieceIndex uint16`, axis position piece-local 3 x `int16` (1 mm), axis direction octahedral 2 x `int8`, `RadiusMm uint8`, `ServerTimeMs uint32`, `Epoch uint16` (about 16 bytes) |
| Radius | From the weapon (combat contract); anchor 15 mm for the rifle |
| Caps | 24 holes per piece, 512 per arena. Hole 25 on a wall piece turns it `Holed` (variant from the hole centroid) and clears its holes; at the arena cap the oldest hole of the piece with the most holes is dropped |
| Sightline test | A sight or bolt ray through a piece with holes passes only if both its entry and exit points lie within the radius of one hole's axis. Thin sheet metal gives a wide view cone through a hole, a 4 cm panel a narrow one. Server and bot use exactly this test; the client renders the same records, so what the person sees through a hole is what the bot can see |
| Rendering | Per-piece hole mask (opacity mask in piece UV space, 256 x 256 render target, created on the first hole) plus a rim decal. No dynamic light per hole |
| Glow | Emissive rim, incandescent white-amber at impact, exponential cooling with tau 1.2 s, dull red at about 2.5 s, glow ends at 4 s; then a permanent charred rim. At most 128 glowing holes rendered, oldest cools first. Never cyan or violet |
| Lifetime | The hole itself lasts until its piece changes to `Holed`/`Breached`/`Destroyed`, is repaired, or reset |
| Cue | A hole appearing in the bot's view cone is a perception stimulus (shot origin hint with error), the same cue the person gets from the glow |

Damaged glass (crack web) blocks sight except through its holes; Intact glass
and grating never block sight. Dust and smoke from breaks are cosmetic and
never block sight.

## 6. Navmesh and bot perception

### 6.1 Navmesh (server only; the bot is the only nav user)

| Topic | Rule |
|---|---|
| Generation | Recast, runtime generation `Dynamic`, tile size 32 x 32 cells at 10 cm cells; agents `Stand` (radius 34, height 180) and `Crouch` (height 110) |
| Trigger | On every state change the manager marks the piece's old and new proxy bounds (+50 cm) dirty |
| Budget | At most 4 tiles rebuilding at once; a change is navigable within 100 ms (gate) |
| Breached | Opening becomes walkable nav; low breaches get a mantle nav link |
| Destroyed catwalk | Its polys and links vanish; drop-down links to the floor below are added from authored link points |
| Holed, Damaged | No nav change (not passable) |
| Path invalidation | Paths crossing a dirtied tile are re-planned on the next bot decision tick |

### 6.2 Bot perception

`VerseBot` keeps a belief copy of piece states. Truth is available through
`IVersePieceQuery`, but the bot's perception layer may write a piece into its
belief only when one of these holds:

| Channel | Condition | Error |
|---|---|---|
| Sight | Part of the piece is in the bot's first-person view cone with line of sight (sight channel, holes honoured) | None on state; the bot sees what is there |
| Sound | A fracture produces an `FVerseNoiseEvent` with tag `Noise.Fracture` and `Loudness` by cause: breach 1.0, wall break 0.7, glass 0.6, tile 0.5, bolt hole 0.2 (audible range = loudness x 40 m, `contracts/bot.md` 3.2) | Position error per tier, as for shots |
| Own action | The bot caused the change | None |

Unperceived pieces keep their believed state. Cover points (EQS-generated)
record which pieces they depend on; a belief change rescores only those
points. Wall shots: the bot fires through a piece only at a heard or believed
opponent position, and only if its believed piece state and this table say a
bolt passes. Harness gate: no bot action ever depends on a piece state the
bot has not perceived (extends `bot.test.ts:32-46` into Unreal).

## 7. Repair drones

| Topic | Rule |
|---|---|
| Delay | 60 s after the piece's last state-changing or hole-making damage. Any further damage restarts the 60 s |
| Dispatch | Server picks the free drone nearest the piece. At most 3 drones active in the arena; others wait in the queue |
| Order | Queue sorted by class first: catwalk segments, then walls and container walls, then glass, then ceiling panels; within a class the longest-broken first |
| Flight | Drone actor flies dock to piece (cosmetic path, replicated movement); `Repairing` starts on arrival |
| Repair | Duration per class (table 3.2). Visual rebuild is cosmetic (amber weld sparks, panels sliding in). Gameplay proxy stays the pre-repair proxy until completion, then switches to `Intact` in one tick, holes cleared |
| Encroachment | Completion waits while any pawn overlaps the Intact proxy bounds +10 cm; re-checked every 0.5 s |
| Interruptible | Yes. Any damage to the piece while `Repairing` cancels the repair: the piece returns to `RepairFrom`, the drone leaves, the 60 s restarts |
| Can be shot | Yes. 30 HP, its own hit box on the bolt channel, stops bolts (no penetration). Downing it cancels the repair as above and drops it as client debris; the dock dispatches a new drone when the timer fires again. No score, no XP |
| Harm | Drones never damage or block pawns |
| Noise | Flight and welding emit `Noise.Drone` events with loudness 0.15 the bot may hear |

## 8. Piece identity

| Topic | Rule |
|---|---|
| Stable id | The One File Per Actor GUID of the `AVerseDestructible` actor |
| Wire id | `PieceIndex` = position of the GUID in `DA_PieceManifest`, sorted by GUID at cook time, per arena; checked by hash in the server welcome |
| Limit | At most 2,000 pieces per deck (the arena zone targets about 600) |

## 9. Geometry rule and validation

Breakable pieces are solid, closed (watertight, manifold) volume meshes whose
thickness matches the material's reference thickness within 10 %. Never two
coincident planes, never one-sided shells. Penetration needs a real entry and
exit hit to measure `traced_thickness`, and Chaos fracture needs volume. This
rule governs every destructible piece, its render mesh and its proxies; the
minimum thicknesses of `contracts/art-pipeline.md` (10 cm visual in 6.3,
20 cm collision in 5) apply only to non-destructible architecture. A
destructible piece that separates a lit from an unlit space sits in front of
a non-destructible backing or accepts the Lumen leak; that choice is the
zone owner's.

Each piece ships: a Nanite render mesh, a Geometry Collection fractured from
the same solid, proxy meshes for every reachable state and variant, the
material id, the class.

Checks, both blocking: the art builder validator (`scripts/verse/cook.py`
step, before export) and the editor validator `UVerseDestructibleValidator`
in `unreal-static`/`unreal-build` (watertight, thickness by inward ray
sampling, all proxies present, GC present, material id set, piece in the
manifest).

## 10. Performance budget

| Budget | Value |
|---|---|
| Active debris rigid bodies | at most 400 on High (architecture §7), 150 on Low; oldest removed first with a 0.3 s fade |
| Bodies per fracture | at most 40; fragments under 5 cm are Niagara particles, not rigid bodies |
| Debris lifetime | sleeps after 3 s, despawns at 10 s (6 s on Low) |
| Geometry Collection actors | pooled, at most 32 alive |
| Fracture events | at most 64 per s; above that the server coalesces per piece per tick |
| Physics | at most 2 ms per frame with the debris cap hit |
| Penetration traces | at most 0.3 ms server game thread per tick |
| Holes | 24 per piece, 512 per arena, 128 glowing |
| Nav rebuild | at most 4 tiles in flight, navigable within 100 ms |
| Bandwidth | state item about 20 bytes per change; full reset burst under 16 KB |

Harness scenario `destruction_storm`: two breach charges plus a full magazine
into a container row every 2 s for 60 s; all budgets must hold.

## 11. Reset

The mode is endless deathmatch, so respawns never reset the world; drones are
the running reset.

| Moment | Effect |
|---|---|
| Arena on (hangar switches from day deck to arena) | Full reset |
| Arena off (back to the day deck), match end | Full reset, so the normal deck is always intact |
| Round boundary | Only if the ruleset asks: `UVerseRuleset::ShouldResetDestruction(EVerseBoundary)`; deathmatch returns false |
| Full reset | Server bumps `Epoch`, sets every item `Intact`/full HP, clears holes, recalls drones, rebuilds dirty nav tiles, multicasts `FVerseFractureEvent{PieceIndex=0xFFFF, Cause=Reset}`. Clients purge debris, hole masks and decals on pieces; the bot's belief resets to Intact (it is told, like the person sees the reset) |

## Frozen interface

Other packages may rely on exactly these:

| Item | Where |
|---|---|
| `EVersePieceState` values and order (section 3.1) | `VerseCore` |
| Material ids, wire order, columns of `DA_PenetrationTable`, the cost formula, 3-piece limit, power anchor 100 = assault rifle (section 2) | `VerseCore` |
| `FVerseFractureEvent` fields and semantics (section 4) | `VerseCore` |
| `FVerseBoltHole` record and the two-point sightline test (section 5) | `VerseCore` |
| Noise loudness per destruction cause (section 6.2), carried in `FVerseNoiseEvent` | `VerseCore` |
| `IVersePenetrationQuery`: `TraceBolt(Origin, Dir, MaxDist, Power, Damage, RadiusMm, MaxPieces) -> TArray<FVersePenetrationHit>` (piece index, material wire id, entry, exit, traced thickness, power and damage left, passed) and `TestSight(Eye, Target) -> bool` (holes honoured, glass and grating see-through) | `VerseDestruction` |
| `IVersePieceDamage::ApplyPieceDamage(FVersePieceDamage)` server only: piece, amount, cause, location, direction, instigator, breach radius | `VerseDestruction` |
| `IVersePieceQuery`: `GetPieceState`, `GetPieceMaterial`, `GetPieceBounds`, `GetPiecesInBox`; bot use only behind its perception gate | `VerseDestruction` |
| Trace channels `VerseBolt` (pieces, world, Bulwark, drones), `VerseSight` (sight traces; `TestSight` applies the per-state glass, grating and hole rules of section 5; the Bulwark field ignores it) and `VerseHitBody` (per-bone hit bodies only; pieces, world and debris ignore it); object channel `VerseDebris` (ignores pawns, bolts, sight, hit bodies) | Project collision profile (integration owner) |
| `AVerseRepairDrone` is a bolt-channel target with 30 HP | `VerseDestruction` |
| `DA_PieceManifest` index rule (section 8) and the geometry rule (section 9) | `VerseDestruction`, art pipeline |
| Reset semantics and `UVerseRuleset::ShouldResetDestruction` (section 11) | `VerseCombat` calls, `VerseDestruction` executes |

Numbers marked as thresholds, HP, times and budgets live in
`DA_PenetrationTable` and `DA_DestructionTuning` and may be retuned; the
columns, fields, enums, channels and function shapes above may not.

## Change rule

Every change to this contract, including a retuned number in the DataAssets
above, goes through the integration owner only: a PR that edits this file
and the DataAsset together, with a green `unreal-gauntlet` run and the
`destruction_storm` perf scenario attached. Packages that need something new
ask the integration owner; they never extend the structs, enums or
interfaces themselves.
